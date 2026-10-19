"""Cities, automatic day factors, weather outlook and self-registration."""
import csv
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api import factor_builder, kz_calendar, weather
from apps.api.cities import CITIES, ESTABLISHMENT_TYPES
from apps.api.db import Audit, BranchProfile, Organization, Record, User
from apps.api.main import create_app
from scripts import generate_kz_demo, seed_demo

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'Places-fixture-password-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class CalendarTests(unittest.TestCase):
    def test_builder_reproduces_the_kz_demo_calendar_factors_for_qyzylorda(self):
        built = {(day.isoformat(), code): str(value) for day, code, value in
                 factor_builder.calendar_rows('kyzylorda', date(2024, 1, 1), date(2026, 1, 1))}
        with (ROOT / 'data/kz/day_factors.csv').open(encoding='utf-8-sig', newline='') as handle:
            demo = {(row['date'], row['factor']): row['value'] for row in csv.DictReader(handle)
                    if row['branch_id'] == '1' and row['factor'] in factor_builder.CALENDAR_CODES}
        self.assertEqual(built, demo)

    def test_generator_and_runtime_calendars_agree_for_the_demo_years(self):
        generated = {date.fromisoformat(text): kind for text, kind, _, _ in generate_kz_demo.DAYS_OFF}
        runtime = {day: kind_tag[0] for day, kind_tag in kz_calendar._KINDS.items() if day.year in (2024, 2025)}
        self.assertEqual(generated, runtime)
        self.assertEqual(generate_kz_demo.RAMADAN, kz_calendar.RAMADAN[:2])
        self.assertEqual(generate_kz_demo.ORAZA_AIT, kz_calendar.ORAZA_AIT[:2])

    def test_local_time_follows_each_city_and_the_2024_time_zone_change(self):
        astana = CITIES['astana']
        before = factor_builder.sunset_minutes(date(2024, 2, 29), astana['latitude'], astana['longitude'], astana['timezone'])
        after = factor_builder.sunset_minutes(date(2024, 3, 1), astana['latitude'], astana['longitude'], astana['timezone'])
        self.assertGreater(before - after, 50)  # UTC+6 -> UTC+5 moves sunset about an hour earlier
        west, east = (factor_builder.calendar_rows(code, date(2026, 6, 21), date(2026, 6, 21)) for code in ('aktau', 'oskemen'))
        sunset = lambda rows: next(value for _, code, value in rows if code == 'sunset_minutes')
        self.assertGreater(sunset(west), sunset(east) + 60)
        self.assertEqual(len(CITIES), 31)
        self.assertTrue(all(42 < item['latitude'] < 56 and 50 < item['longitude'] < 88 for item in CITIES.values()))

    def test_2026_calendar_and_publication_limits(self):
        rows = {(day.isoformat(), code): value for day, code, value in
                factor_builder.calendar_rows('almaty', date(2026, 2, 18), date(2027, 1, 12))}
        self.assertEqual(rows[('2026-02-19', 'ramadan')], 1)
        self.assertEqual(rows[('2026-03-20', 'ait')], 1)
        self.assertEqual(rows[('2026-05-27', 'public_holiday')], 1)
        self.assertEqual(rows[('2026-03-24', 'nauryz')], 1)
        self.assertEqual(rows[('2026-08-31', 'transferred_day_off')], 0)  # Constitution Day moved to 15 March
        self.assertEqual(rows[('2026-12-31', 'pre_holiday')], 1)
        self.assertEqual(rows[('2027-01-05', 'school_holiday')], 1)
        self.assertNotIn(('2027-01-05', 'public_holiday'), rows)  # 2027 transfers are not published yet
        self.assertNotIn(('2027-01-05', 'ramadan'), rows)
        self.assertIn(('2027-01-05', 'sunset_minutes'), rows)
        with self.assertRaises(factor_builder.FactorBuildError):
            factor_builder.calendar_rows('atlantis', date(2026, 1, 1), date(2026, 1, 2))


class WeatherTests(unittest.TestCase):
    def response(self, start, end, mean=10.0, high=34.0, rain=1.25):
        days = [(start + timedelta(days=step)).isoformat() for step in range((end - start).days + 1)]
        return {'daily': {'time': days, 'temperature_2m_mean': [mean] * len(days),
                          'temperature_2m_max': [high] * len(days), 'precipitation_sum': [rain] * len(days)}}

    def test_past_days_use_the_forecast_archive_and_future_days_the_live_forecast(self):
        calls = []
        def fake(url, params, timeout):
            calls.append((url, params['start_date'], params['end_date']))
            return self.response(date.fromisoformat(params['start_date']), date.fromisoformat(params['end_date']))
        with patch.object(weather, '_get', side_effect=fake), patch.dict(os.environ, {'WEATHER_PROVIDER': 'open-meteo'}):
            values = weather.daily_forecasts(CITIES['astana'], date(2026, 10, 10), date(2026, 11, 20), today=date(2026, 10, 19))
        self.assertEqual(calls, [(weather.ARCHIVE_URL, '2026-10-10', '2026-10-18'), (weather.FORECAST_URL, '2026-10-19', '2026-11-03')])
        self.assertEqual(max(values), date(2026, 11, 3))
        self.assertEqual(weather.factor_values(values[date(2026, 10, 19)]),
                         [('temperature_forecast_c', 10.0), ('precipitation_mm', 1.2), ('heat_alert', 1)])

    def test_missing_days_stay_missing_and_failures_never_echo_the_key(self):
        payload = self.response(date(2026, 10, 19), date(2026, 10, 20))
        payload['daily']['temperature_2m_mean'][1] = None
        with patch.object(weather, '_get', return_value=payload):
            self.assertEqual(list(weather.daily_forecasts(CITIES['almaty'], date(2026, 10, 19), date(2026, 10, 20),
                                                          today=date(2026, 10, 19))), [date(2026, 10, 19)])
        with patch.dict(os.environ, {'WEATHER_API_KEY': 'secret-weather-key'}), \
                patch('urllib.request.urlopen', side_effect=OSError('https://x?apikey=secret-weather-key')):
            with self.assertRaises(weather.WeatherError) as raised:
                weather._get(weather.FORECAST_URL, {'latitude': 1}, 1)
        self.assertNotIn('secret', str(raised.exception))
        with patch.dict(os.environ, {'WEATHER_PROVIDER': 'off'}), self.assertRaises(weather.WeatherError):
            weather.daily_forecasts(CITIES['almaty'], date(2026, 1, 1), date(2026, 1, 2), today=date(2026, 1, 1))


class ApiTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='.cache', prefix='places-tests-')
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local'})
        environment.start();self.addCleanup(environment.stop)
        self.app = create_app('sqlite:///' + (Path(self.temp.name).resolve() / 'places.sqlite').as_posix())
        self.addCleanup(self.app.state.engine.dispose)

    def client(self, email=None):
        client = TestClient(self.app);self.addCleanup(client.close)
        if email:
            response = client.post('/api/v1/session/login', json={'email': email, 'password': PASSWORD}, headers=ORIGIN)
            self.assertEqual(response.status_code, 200, response.text)
            client.headers.update({**ORIGIN, 'X-CSRF-Token': response.json()['csrf_token']})
        return client

    def registration(self, **changes):
        return {'establishment_name': 'Шымкент самса', 'establishment_type': 'cafe', 'city_code': 'shymkent',
                'email': 'owner@samsa.test', 'password': PASSWORD, 'accept_test_mode': True, **changes}

    def test_registration_creates_a_test_cabinet_for_the_chosen_city_and_signs_in(self):
        client = self.client()
        self.assertEqual(client.get('/api/v1/registration').json(), {'enabled': True, 'mode': 'synthetic_only'})
        self.assertEqual(len(client.get('/api/v1/cities').json()['items']), 31)
        created = client.post('/api/v1/register', json=self.registration(), headers=ORIGIN)
        self.assertEqual(created.status_code, 200, created.text)
        body = created.json()
        self.assertEqual((body['user']['role'], body['user']['branch_ids']), ('admin', ['1']))
        self.assertNotIn(PASSWORD, created.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': body['csrf_token']})
        me = client.get('/api/v1/session/me').json()
        self.assertEqual(me['user']['email'], 'owner@samsa.test')
        self.assertEqual(client.get('/api/v1/branches').json()['items'][0]['branch_name'], 'Шымкент самса')
        profiles = client.get('/api/v1/branch-profiles').json()['items']
        self.assertEqual((profiles[0]['city_code'], profiles[0]['establishment_type']), ('shymkent', 'cafe'))
        with self.app.state.sessions() as db:
            organization = db.get(Organization, body['user']['organization_id'])
            self.assertEqual((organization.data_policy, organization.provenance, organization.timezone),
                             ('synthetic_only', 'self_registration', 'Asia/Almaty'))
            audit = db.scalar(select(Audit).where(Audit.action == 'tenant.registered'))
            self.assertNotIn('owner@samsa.test', json.dumps(audit.details))

    def test_registration_refusals(self):
        client = self.client()
        self.assertEqual(client.post('/api/v1/register', json=self.registration()).status_code, 403)  # no Origin
        refused = client.post('/api/v1/register', json=self.registration(password='short'), headers=ORIGIN)
        self.assertEqual(refused.status_code, 422);self.assertNotIn('short', refused.text)
        for changes, code in (({'city_code': 'atlantis'}, 'CITY_UNKNOWN'), ({'establishment_type': 'spaceport'}, 'ESTABLISHMENT_TYPE_UNKNOWN'),
                              ({'password': 'owner-owner-owner'}, 'PASSWORD_TOO_SIMILAR')):
            response = client.post('/api/v1/register', json=self.registration(**changes), headers=ORIGIN)
            self.assertEqual(response.json()['detail']['code'], code)
        self.assertEqual(client.post('/api/v1/register', json=self.registration(accept_test_mode=False), headers=ORIGIN).status_code, 422)
        for _ in range(2):  # refused attempts count too: five per hour and address
            client.post('/api/v1/register', json=self.registration(city_code='atlantis'), headers=ORIGIN)
        limited = client.post('/api/v1/register', json=self.registration(), headers=ORIGIN)
        self.assertEqual(limited.json()['detail']['code'], 'RATE_LIMITED')  # five attempts per hour and address
        with self.app.state.sessions() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Organization)), 0)
        with patch.dict(os.environ, {'ASBOLJAM_SELF_REGISTRATION': 'off'}):
            self.assertFalse(client.get('/api/v1/registration').json()['enabled'])
            self.assertEqual(client.post('/api/v1/register', json=self.registration(), headers=ORIGIN).json()['detail']['code'],
                             'REGISTRATION_DISABLED')

    def test_duplicate_email_is_refused(self):
        seed_demo.seed(self.app.state.sessions, PASSWORD, dataset='kz')
        response = self.client().post('/api/v1/register', json=self.registration(email='admin@asboljam.local'), headers=ORIGIN)
        self.assertEqual((response.status_code, response.json()['detail']['code']), (409, 'EMAIL_EXISTS'))

    def test_factor_fill_builds_a_reviewable_preview_and_keeps_existing_rows(self):
        seed_demo.seed(self.app.state.sessions, PASSWORD, dataset='kz')
        admin = self.client('admin@asboljam.local')
        profiles = {row['branch_id']: row['city_code'] for row in admin.get('/api/v1/branch-profiles').json()['items']}
        self.assertEqual(profiles, {'1': 'kyzylorda', '2': 'kyzylorda', '3': 'kyzylorda'})
        forecasts = {date(2025, 12, 30) + timedelta(days=step): {'temperature_mean': -3.0, 'temperature_max': 1.0, 'precipitation': 2.0}
                     for step in range(3)}
        with patch('apps.api.places_api.daily_forecasts', return_value=forecasts) as fetched:
            filled = admin.post('/api/v1/factors/fill', json={'branch_id': '2', 'date_from': '2025-12-30', 'date_to': '2026-01-01'}).json()
        self.assertEqual(fetched.call_args.args[0]['code'], 'kyzylorda')
        summary, batch = filled['summary'], filled['batch']
        # Calendar and temperature rows already exist in the demo; only precipitation is new.
        self.assertEqual((summary['new_rows'], summary['weather'], batch['kind'], batch['status']), (3, 'loaded', 'day_factors', 'preview'))
        self.assertEqual(admin.post(f"/api/v1/imports/{batch['id']}/commit", headers={'Idempotency-Key': 'fill-1'}).status_code, 200)
        with self.app.state.sessions() as db:
            rows = [r.data for r in db.scalars(select(Record).where(Record.kind == 'day_factors', Record.branch_id == '2'))
                    if r.data['factor'] == 'precipitation_mm']
        self.assertEqual(sorted(row['date'] for row in rows), ['2025-12-30', '2025-12-31', '2026-01-01'])
        moved = admin.put('/api/v1/branches/2/profile', json={'city_code': 'atyrau', 'establishment_type': 'cafe'})
        self.assertEqual(moved.json()['city']['timezone'], 'Asia/Atyrau')
        manager_payload = {'branch_id': '1', 'date_from': '2026-01-02', 'date_to': '2026-01-03', 'weather': False}
        nothing = admin.post('/api/v1/factors/fill', json={**manager_payload, 'date_to': '2023-12-31', 'date_from': '2023-12-30'}).json()
        self.assertEqual((nothing['batch'], nothing['summary']['new_rows']), (None, 0))
        new_year = admin.post('/api/v1/factors/fill', json=manager_payload).json()
        self.assertEqual(new_year['summary']['weather'], 'not_requested')
        self.assertGreater(new_year['summary']['new_rows'], 10)

    def test_profiles_are_admin_only_and_fill_needs_a_city(self):
        seed_demo.seed(self.app.state.sessions, PASSWORD, dataset='raw')
        with self.app.state.sessions() as db:
            db.add(User(id='manager-places', organization_id='demo', email='manager@places.test',
                        password_hash=seed_demo.password_hash(PASSWORD), role='manager', branch_ids=['1']))
            db.commit()
        manager = self.client('manager@places.test')
        self.assertEqual(manager.put('/api/v1/branches/1/profile', json={'city_code': 'almaty'}).status_code, 403)
        refused = manager.post('/api/v1/factors/fill', json={'branch_id': '1', 'date_from': '2025-01-01', 'date_to': '2025-01-02'})
        self.assertEqual(refused.json()['detail']['code'], 'BRANCH_CITY_REQUIRED')
        self.assertEqual(manager.get('/api/v1/weather', params={'branch_id': '1'}).json()['detail']['code'], 'BRANCH_CITY_REQUIRED')


if __name__ == '__main__':
    unittest.main()
