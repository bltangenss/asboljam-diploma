"""Cities, branch profiles, automatic day factors, weather outlook and self-registration."""
from datetime import date, datetime, timezone
import csv
import hashlib
import io
import os
import re
import secrets
import time
import uuid
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .cities import ESTABLISHMENT_TYPES, catalogue as city_catalogue, city as find_city
from .data_policy import policy_context
from .db import AuthSession, Audit, BranchProfile, LoginAttempt, Organization, Record, User
from .factor_builder import FactorBuildError, calendar_rows
from .import_service import preview_import
from .importing import insert_rows, rows_for
from .security import password_hash, token_hash
from .weather import WeatherError, daily_forecasts, factor_values, week_ahead

EMAIL = re.compile(r'[^\s@]+@[^\s@]+\.[^\s@]+')


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProfileInput(_Strict):
    city_code: str = Field(min_length=1, max_length=32)
    establishment_type: str | None = Field(default=None, max_length=32)


class FactorFillInput(_Strict):
    branch_id: str = Field(min_length=1, max_length=64)
    date_from: date
    date_to: date
    weather: bool = True


class RegistrationInput(_Strict):
    establishment_name: str = Field(min_length=2, max_length=120)
    establishment_type: str = Field(min_length=1, max_length=32)
    city_code: str = Field(min_length=1, max_length=32)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=1024)
    accept_test_mode: Literal[True]


def registration_enabled() -> bool:
    value = os.environ.get('ASBOLJAM_SELF_REGISTRATION', '').strip().lower()
    if value in {'on', 'off'}:
        return value == 'on'
    return os.environ.get('ASBOLJAM_ENV', 'local').strip().lower() == 'local'


def city_today(place: dict) -> date:
    return datetime.now(ZoneInfo(place['timezone'])).date()


def register_place_routes(app, *, current, get_db, roles, branch_access, fail, audit, origin_check,
                          user_json, metadata, secure):
    def profile_json(profile):
        place = find_city(profile.city_code)
        return {'branch_id': profile.branch_id, 'city_code': profile.city_code, 'city': place,
                'establishment_type': profile.establishment_type, 'updated_at': profile.updated_at}

    def branch_place(db, user, branch_id):
        profile = db.get(BranchProfile, (user.organization_id, branch_id))
        place = find_city(profile.city_code) if profile else None
        if place is None:
            fail('BRANCH_CITY_REQUIRED', 'Алдымен бөлімшенің қаласын таңдаңыз.', 422)
        return place

    @app.get('/api/v1/cities')
    def cities():
        # Public: the registration form lists the cities before any account exists.
        return {'items': city_catalogue(), 'establishment_types': ESTABLISHMENT_TYPES}

    @app.get('/api/v1/branch-profiles')
    def branch_profiles(user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst', 'warehouse')
        rows = db.scalars(select(BranchProfile).where(BranchProfile.organization_id == user.organization_id))
        return {'items': [profile_json(row) for row in rows if row.branch_id in user.branch_ids]}

    @app.put('/api/v1/branches/{branch_id}/profile')
    def set_branch_profile(branch_id: str, data: ProfileInput, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin');branch_access(db, user, branch_id)
        if find_city(data.city_code) is None:
            fail('CITY_UNKNOWN', 'Қала анықтамалықта жоқ.', 422)
        if data.establishment_type is not None and data.establishment_type not in ESTABLISHMENT_TYPES:
            fail('ESTABLISHMENT_TYPE_UNKNOWN', 'Мекеме түрі белгісіз.', 422)
        profile = db.get(BranchProfile, (user.organization_id, branch_id))
        before = profile_json(profile) if profile else None
        if profile is None:
            profile = BranchProfile(organization_id=user.organization_id, branch_id=branch_id,
                                    city_code=data.city_code, updated_by=user.id)
            db.add(profile)
        profile.city_code, profile.establishment_type = data.city_code, data.establishment_type
        profile.updated_by, profile.updated_at = user.id, datetime.now(timezone.utc).isoformat()
        audit(db, user, 'branch.profile_updated', branch_id, branch_id,
              {'city_code': data.city_code, 'establishment_type': data.establishment_type,
               'previous_city_code': before and before['city_code']})
        db.commit()
        return profile_json(profile)

    @app.post('/api/v1/factors/fill')
    def fill_factors(data: FactorFillInput, user=Depends(current), db=Depends(get_db)):
        # Builds a reviewable import preview; nothing is stored until the user commits it.
        roles(user, 'admin', 'manager');branch_access(db, user, data.branch_id)
        place = branch_place(db, user, data.branch_id)
        try:
            built = calendar_rows(place['code'], data.date_from, data.date_to)
        except FactorBuildError as exc:
            fail(exc.code, exc.message, 422)
        weather_status, weather_days = 'not_requested', 0
        if data.weather:
            try:
                forecasts = daily_forecasts(place, data.date_from, data.date_to, today=city_today(place))
                weather_days = len(forecasts)
                built += [(day, code, value) for day in sorted(forecasts) for code, value in factor_values(forecasts[day])]
                weather_status = 'loaded'
            except WeatherError as exc:
                weather_status = exc.code
        existing = {(row['date'], row['factor']) for row in rows_for(db, user.organization_id, 'day_factors', data.branch_id)}
        context = policy_context(db, user.organization_id)
        if context['data_origin'] is None:
            fail('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимі қолжетімсіз.', 403)
        fresh = [(day.isoformat(), code, value) for day, code, value in built if (day.isoformat(), code) not in existing]
        summary = {'city': place, 'calculated_rows': len(built), 'new_rows': len(fresh),
                   'existing_rows_kept': len(built) - len(fresh), 'weather': weather_status, 'weather_days': weather_days}
        if not fresh:
            return {'batch': None, 'summary': summary}
        output = io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\n')
        writer.writerow(['date', 'branch_id', 'factor', 'value', 'data_origin'])
        writer.writerows([[day, data.branch_id, code, value, context['data_origin']] for day, code, value in fresh])
        source = {key: context['source'][key] for key in ('source_id', 'mapping_version')} if context['source'] else None
        batch = preview_import(db, user, kind='day_factors', csv_text=output.getvalue(), mode='append', source=source)
        db.commit()
        return {'batch': batch, 'summary': summary}

    @app.get('/api/v1/weather')
    def weather_outlook(branch_id: str, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst');branch_access(db, user, branch_id)
        place = branch_place(db, user, branch_id)
        try:
            outlook = week_ahead(place, city_today(place))
        except WeatherError as exc:
            fail(exc.code, exc.message, 503)
        return {'city': place, 'items': outlook, 'source': 'Open-Meteo',
                'kind': 'forecast', 'note': 'Model forecast, not a measurement.'}

    @app.get('/api/v1/registration')
    def registration_status():
        return {'enabled': registration_enabled(), 'mode': 'synthetic_only'}

    @app.post('/api/v1/register')
    def register(data: RegistrationInput, request: Request, response: Response, db=Depends(get_db)):
        if not registration_enabled():
            fail('REGISTRATION_DISABLED', 'Өз бетінше тіркелу өшірілген.', 403)
        origin_check(request)
        # Like login attempts, the client address is stored only as a hash.
        identity = 'register:' + hashlib.sha256((request.client.host if request.client else 'unknown').encode()).hexdigest()
        recent = db.scalar(select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.identity == identity, LoginAttempt.timestamp > time.time() - 3600))
        if recent >= 5:
            fail('RATE_LIMITED', 'Тіркелу әрекеті тым көп. Бір сағаттан кейін қайталаңыз.', 429)
        db.add(LoginAttempt(id=uuid.uuid4().hex, identity=identity, timestamp=time.time()))
        db.commit()
        place = find_city(data.city_code)
        if place is None:
            fail('CITY_UNKNOWN', 'Қала анықтамалықта жоқ.', 422)
        if data.establishment_type not in ESTABLISHMENT_TYPES:
            fail('ESTABLISHMENT_TYPE_UNKNOWN', 'Мекеме түрі белгісіз.', 422)
        name, email = data.establishment_name.strip(), data.email.strip().lower()
        if len(name) < 2 or any(ord(character) < 32 for character in name):
            fail('ESTABLISHMENT_NAME_INVALID', 'Мекеме атауы 2–120 таңбадан тұруы керек.', 422)
        if not EMAIL.fullmatch(email):
            fail('EMAIL_INVALID', 'Электрондық поштаны тексеріңіз.', 422)
        local = email.split('@')[0]
        if data.password.lower() in {email, name.lower()} or (len(local) >= 4 and local in data.password.lower()):
            fail('PASSWORD_TOO_SIMILAR', 'Құпиясөз пошта мен атауға ұқсамауы керек.', 422)
        if db.scalar(select(User.id).where(User.email == email)) is not None:
            fail('EMAIL_EXISTS', 'Бұл поштамен тіркелгі бар. Кіріңіз немесе басқа пошта енгізіңіз.', 409)
        organization = Organization(id='org-' + uuid.uuid4().hex[:16], name=name, timezone=place['timezone'],
                                    currency='KZT', status='active', data_policy='synthetic_only',
                                    provenance='self_registration')
        user = User(id=uuid.uuid4().hex, organization_id=organization.id, email=email,
                    password_hash=password_hash(data.password), role='admin', branch_ids=['1'], active=True)
        db.add(organization);db.add(user)
        db.flush()
        insert_rows(db, organization.id, 'branches', [{'branch_id': '1', 'branch_name': name, 'data_origin': 'SYNTHETIC'}])
        db.add(BranchProfile(organization_id=organization.id, branch_id='1', city_code=place['code'],
                             establishment_type=data.establishment_type, updated_by=user.id))
        db.add(Audit(id=uuid.uuid4().hex, organization_id=organization.id, branch_id=None, actor_id=user.id,
                     action='tenant.registered', entity_id=organization.id,
                     details={'city_code': place['code'], 'establishment_type': data.establishment_type,
                              'data_policy': 'synthetic_only'}))
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.add(AuthSession(id=uuid.uuid4().hex, user_id=user.id, token_hash=token_hash(token), csrf_token=csrf,
                           kind='web', expires_at=time.time() + 8 * 3600))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            fail('EMAIL_EXISTS', 'Бұл поштамен тіркелгі бар. Кіріңіз немесе басқа пошта енгізіңіз.', 409)
        response.set_cookie('asboljam_session', token, httponly=True, secure=secure, samesite='lax',
                            max_age=8 * 3600, path='/api')
        return {'user': user_json(user), 'csrf_token': csrf, **metadata(db, organization.id)}
