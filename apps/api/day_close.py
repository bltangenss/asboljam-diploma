"""Close one business day of a branch: entered facts, their completeness, one transaction.

A draft keeps exactly what a person entered: an empty value stays unknown and zero stays a
confirmed zero. Closing writes the day's daily_sales through the regular import preview and
commit (same parser, reference checks, revisions and audit) in the same transaction as the
closure status, so a day is never marked closed without its sales and identical facts never
add up twice. Different stored values are a conflict that needs an explicit correction reason.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import io
import json
import re
from typing import Annotated, Literal

from fastapi import Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .data_policy import DEMO_TARGET, DataPolicyError, business_clock, policy_context
from .db import DayClosure, Idempotency, ProductionPlan, Record, User, now
from .import_service import ImportProblem, commit_import, preview_import
from .importing import SCHEMAS, parse_csv, rows_for
from .lineage import row_digest

TIME = re.compile(r'([01]\d|2[0-3]):[0-5]\d')
SALE_FIELDS = ('units_sold', 'available_portions', 'stockout_flag', 'promo', 'price_kzt')
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
Flag = Literal[0, 1]


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Line(_Strict):
    meal_id: str = Field(min_length=1, max_length=64)
    state: Literal['sold', 'not_offered'] | None = None
    units_sold: Count | None = None
    available_portions: Count | None = None
    stockout_flag: Flag | None = None
    stockout_time: str | None = Field(default=None, max_length=5)
    replenished_time: str | None = Field(default=None, max_length=5)
    promo: Flag | None = None
    price_kzt: str | None = Field(default=None, max_length=32)


class DraftInput(_Strict):
    branch_id: str = Field(min_length=1, max_length=64)
    business_date: date
    expected_version: int = Field(ge=0)
    is_open: Flag | None = None
    lines: list[Line] = Field(default_factory=list, max_length=1000)


class CloseInput(_Strict):
    branch_id: str = Field(min_length=1, max_length=64)
    business_date: date
    expected_version: int = Field(ge=1)
    correction_reason: str | None = Field(default=None, max_length=1000)


class ReopenInput(_Strict):
    branch_id: str = Field(min_length=1, max_length=64)
    business_date: date
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)


class DayCloseError(ValueError):
    def __init__(self, code, message, status=422, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)


def day_policy(db, organization_id, closed=frozenset()):
    """Which business dates may be edited and closed. SYNTHETIC days stay on the fixed scenario."""
    try:
        context = policy_context(db, organization_id)
    except DataPolicyError as exc:
        raise DayCloseError(exc.code, exc.message, 403) from exc
    if context['data_origin'] == 'SYNTHETIC':
        last = date.fromisoformat(DEMO_TARGET)
        return {'data_origin': 'SYNTHETIC', 'editable_until': last, 'closable_until': last, 'default': last}
    if context['data_origin'] == 'REAL':
        today = business_clock(context)[1]
        yesterday = today - timedelta(days=1)
        # A REAL day is recorded once it has ended, as with any sales import.
        return {'data_origin': 'REAL', 'editable_until': today, 'closable_until': yesterday,
                'default': yesterday if yesterday.isoformat() not in closed else today}
    raise DayCloseError('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимі қолжетімсіз.', 403)


def _menu(db, organization_id):
    return sorted(rows_for(db, organization_id, 'meals'), key=lambda row: str(row['meal_id']))


def _sales_on(db, organization_id, branch_id, day):
    prefix = json.dumps([day, str(branch_id)], separators=(',', ':'))[:-1] + ','
    rows = db.scalars(select(Record).where(Record.organization_id == organization_id, Record.kind == 'daily_sales',
                                           Record.branch_id == str(branch_id), Record.natural_key.startswith(prefix)))
    return {str(r.data['meal_id']): r for r in rows if r.data.get('date') == day and str(r.data.get('branch_id')) == str(branch_id)}


def _check_lines(lines, menu_ids):
    seen, problems = set(), []
    for line in lines:
        if line.meal_id not in menu_ids:
            problems.append({'meal_id': line.meal_id, 'code': 'MEAL_UNKNOWN'})
        if line.meal_id in seen:
            problems.append({'meal_id': line.meal_id, 'code': 'MEAL_DUPLICATE'})
        seen.add(line.meal_id)
        values = [getattr(line, field) for field in SALE_FIELDS] + [line.stockout_time, line.replenished_time]
        if line.state == 'not_offered' and any(value is not None for value in values):
            problems.append({'meal_id': line.meal_id, 'code': 'NOT_OFFERED_WITH_VALUES'})
        for field in ('stockout_time', 'replenished_time'):
            value = getattr(line, field)
            if value is not None and not TIME.fullmatch(value):
                problems.append({'meal_id': line.meal_id, 'code': 'TIME_INVALID', 'field': field})
        if (line.stockout_time or line.replenished_time) and line.stockout_flag != 1:
            problems.append({'meal_id': line.meal_id, 'code': 'TIME_WITHOUT_STOCKOUT'})
        if line.price_kzt is not None:
            try:
                price = Decimal(line.price_kzt)
                if not price.is_finite() or price < 0 or price > Decimal('1000000000000') or price != price.quantize(Decimal('0.000000001')):
                    raise InvalidOperation
            except InvalidOperation:
                problems.append({'meal_id': line.meal_id, 'code': 'PRICE_INVALID', 'field': 'price_kzt'})
    if problems:
        raise DayCloseError('DAY_LINES_INVALID', 'Кейбір тағам жолдары жарамсыз.', 422, problems)


def completeness(closure, menu):
    """What is still missing before the day can be recorded; nothing is guessed."""
    names = {str(row['meal_id']): row.get('meal_name') for row in menu}
    if closure is None or closure.is_open is None:
        return {'complete': False, 'is_open_known': False, 'missing': [], 'unmarked': sorted(names), 'invalid': [],
                'counts': {'meals': len(names), 'sold': 0, 'not_offered': 0, 'unmarked': len(names)}}
    if closure.is_open == 0:
        return {'complete': True, 'is_open_known': True, 'missing': [], 'unmarked': [], 'invalid': [],
                'counts': {'meals': len(names), 'sold': 0, 'not_offered': 0, 'unmarked': 0}}
    lines = {line['meal_id']: line for line in closure.lines}
    missing, unmarked, invalid, sold, offered = [], [], [], 0, 0
    for meal_id, name in names.items():
        line = lines.get(meal_id) or {}
        if line.get('state') == 'not_offered':
            offered += 1
        elif line.get('state') == 'sold':
            sold += 1
            fields = [field for field in SALE_FIELDS if line.get(field) is None]
            if fields:
                missing.append({'meal_id': meal_id, 'meal_name': name, 'fields': fields})
            elif line['units_sold'] > line['available_portions']:
                invalid.append({'meal_id': meal_id, 'meal_name': name, 'code': 'SALES_EXCEED_AVAILABLE'})
        else:
            unmarked.append(meal_id)
    return {'complete': not missing and not unmarked and not invalid, 'is_open_known': True, 'missing': missing,
            'unmarked': unmarked, 'invalid': invalid,
            'counts': {'meals': len(names), 'sold': sold, 'not_offered': offered, 'unmarked': len(unmarked)}}


def sales_rows(closure, menu, data_origin):
    """daily_sales rows of a complete closure. A closed day keeps the dataset convention: zero sales,
    nothing available, no stockout or promotion, the menu price."""
    day, branch = closure.business_date, closure.branch_id
    if closure.is_open == 0:
        return [{'date': day, 'branch_id': branch, 'meal_id': str(row['meal_id']), 'units_sold': 0, 'available_portions': 0,
                 'stockout_flag': 0, 'is_open': 0, 'promo': 0, 'price_kzt': row['base_price_kzt'], 'data_origin': data_origin}
                for row in menu]
    return [{'date': day, 'branch_id': branch, 'meal_id': line['meal_id'], 'units_sold': line['units_sold'],
             'available_portions': line['available_portions'], 'stockout_flag': line['stockout_flag'], 'is_open': 1,
             'promo': line['promo'], 'price_kzt': line['price_kzt'], 'data_origin': data_origin}
            for line in sorted(closure.lines, key=lambda item: item['meal_id']) if line.get('state') == 'sold']


def csv_text(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=SCHEMAS['daily_sales'].split(), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def register_day_close_routes(app, *, current, get_db, roles, branch_access, fail, audit):
    def problem(exc):
        detail = {'code': exc.code, 'message': exc.message}
        if exc.details is not None:
            detail['details'] = exc.details
        from fastapi import HTTPException
        raise HTTPException(exc.status, detail)

    def receipt(db, user, key, digest):
        old = db.scalar(select(Idempotency).where(Idempotency.organization_id == user.organization_id,
                                                  Idempotency.actor_id == user.id, Idempotency.key == key))
        if old and old.payload_hash != digest:
            fail('IDEMPOTENCY_CONFLICT', 'Кілт басқа сұрауға қолданылған.', 409)
        return old.response if old else None

    def require_key(key):
        if not key or len(key) > 128:
            fail('IDEMPOTENCY_REQUIRED', 'Idempotency-Key тақырыбы қажет.', 422)

    def closed_dates(db, user, branch_id):
        return {row.business_date for row in db.scalars(select(DayClosure).where(
            DayClosure.organization_id == user.organization_id, DayClosure.branch_id == branch_id,
            DayClosure.status == 'closed'))}

    def check_day(policy, day, *, closing=False):
        if day > policy['editable_until']:
            raise DayCloseError('BUSINESS_DATE_IN_FUTURE', 'Бұл күн әлі келген жоқ.', 422)
        if closing and day > policy['closable_until']:
            raise DayCloseError('BUSINESS_DATE_NOT_CLOSED', 'Күн аяқталғаннан кейін ғана жабылады. Әзірге жоба ретінде сақтаңыз.', 409)

    def view(db, user, branch_id, day, policy):
        text = day.isoformat()
        closure = db.get(DayClosure, (user.organization_id, branch_id, text))
        menu = _menu(db, user.organization_id)
        lines = {line['meal_id']: line for line in closure.lines} if closure else {}
        recorded = _sales_on(db, user.organization_id, branch_id, text)
        previous = _sales_on(db, user.organization_id, branch_id, (day - timedelta(days=1)).isoformat())
        plan = db.scalars(select(ProductionPlan).where(ProductionPlan.organization_id == user.organization_id,
                                                       ProductionPlan.branch_id == branch_id, ProductionPlan.target_date == text)
                          .order_by(ProductionPlan.created_at.desc()).limit(1)).first()
        planned = {row.get('meal_id'): row.get('portions') for row in (plan.document.get('portions') or [])} if plan else {}
        people = {u.id: u.email for u in db.scalars(select(User).where(User.organization_id == user.organization_id))}
        meals = []
        for row in menu:
            meal_id = str(row['meal_id'])
            stored = recorded.get(meal_id)
            meals.append({'meal_id': meal_id, 'meal_name': row.get('meal_name'), 'base_price_kzt': row.get('base_price_kzt'),
                          'entry': lines.get(meal_id), 'recorded': stored.data if stored else None,
                          # Reference only: never copied into today's facts.
                          'reference': {'previous_day_units_sold': previous[meal_id].data.get('units_sold') if meal_id in previous else None,
                                        'planned_portions': planned.get(meal_id)}})
        return {'branch_id': branch_id, 'business_date': text, 'default_date': policy['default'].isoformat(),
                'data_origin': policy['data_origin'], 'closable': day <= policy['closable_until'],
                'status': closure.status if closure else 'none', 'version': closure.version if closure else 0,
                'is_open': closure.is_open if closure else None, 'meals': meals,
                'completeness': completeness(closure, menu), 'production_plan_id': plan.id if plan else None,
                'updated_by': people.get(closure.updated_by) if closure else None, 'updated_at': closure.updated_at if closure else None,
                'closed_by': people.get(closure.closed_by) if closure and closure.closed_by else None,
                'closed_at': closure.closed_at if closure else None, 'reason': closure.reason if closure else None,
                'batch_ids': closure.batch_ids if closure else []}

    @app.get('/api/v1/day-close')
    def day_close_view(branch_id: str, business_date: date | None = Query(None), user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst');branch_access(db, user, branch_id)
        try:
            policy = day_policy(db, user.organization_id, closed_dates(db, user, branch_id))
            day = business_date or policy['default']
            check_day(policy, day)
        except DayCloseError as exc:
            problem(exc)
        return view(db, user, branch_id, day, policy)

    @app.put('/api/v1/day-close')
    def save_draft(data: DraftInput, idempotency_key: str | None = Header(None), user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager');branch_access(db, user, data.branch_id);require_key(idempotency_key)
        digest = _digest({'action': 'draft', **data.model_dump(mode='json')})
        replay = receipt(db, user, idempotency_key, digest)
        if replay is not None:
            return replay
        try:
            policy = day_policy(db, user.organization_id)
            check_day(policy, data.business_date)
            _check_lines(data.lines, {str(row['meal_id']) for row in _menu(db, user.organization_id)})
        except DayCloseError as exc:
            problem(exc)
        day, lines = data.business_date.isoformat(), [line.model_dump() for line in data.lines]
        key = (user.organization_id, data.branch_id, day)
        try:
            if data.expected_version == 0:
                db.add(DayClosure(organization_id=user.organization_id, branch_id=data.branch_id, business_date=day,
                                  status='draft', version=1, is_open=data.is_open, lines=lines, data_origin=policy['data_origin'],
                                  created_by=user.id, updated_by=user.id, batch_ids=[]))
                db.flush()
            else:
                changed = db.execute(update(DayClosure).where(
                    DayClosure.organization_id == key[0], DayClosure.branch_id == key[1], DayClosure.business_date == key[2],
                    DayClosure.version == data.expected_version, DayClosure.status == 'draft').values(
                    version=data.expected_version + 1, is_open=data.is_open, lines=lines, updated_by=user.id, updated_at=now())).rowcount
                if not changed:
                    db.rollback()
                    stored = db.get(DayClosure, key)
                    if stored is not None and stored.status == 'closed':
                        fail('DAY_CLOSED', 'Күн жабылған. Өзгерту үшін алдымен себебін көрсетіп қайта ашыңыз.', 409)
                    fail('STALE_VERSION', 'Жобаны басқа пайдаланушы өзгерткен. Жаңартып, қайта тексеріңіз.', 409)
            db.expire_all()
            result = view(db, user, data.branch_id, data.business_date, policy)
            db.add(Idempotency(id=hashlib.sha256((idempotency_key + user.id).encode()).hexdigest()[:32] + digest[:32],
                               organization_id=user.organization_id, actor_id=user.id, key=idempotency_key,
                               payload_hash=digest, response=result))
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            replay = receipt(db, user, idempotency_key, digest)
            if replay is not None:
                return replay
            fail('STALE_VERSION', 'Жобаны басқа пайдаланушы өзгерткен. Жаңартып, қайта тексеріңіз.', 409)

    @app.post('/api/v1/day-close/close')
    def close_day(data: CloseInput, idempotency_key: str | None = Header(None), user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager');branch_access(db, user, data.branch_id);require_key(idempotency_key)
        reason = data.correction_reason.strip() if data.correction_reason else None
        if reason is not None and len(reason) < 3:
            fail('CORRECTION_REASON_REQUIRED', 'Түзету себебі кемінде 3 таңба болуы керек.', 422)
        digest = _digest({'action': 'close', **data.model_dump(mode='json')})
        replay = receipt(db, user, idempotency_key, digest)
        if replay is not None:
            return replay
        day = data.business_date.isoformat()
        key = (user.organization_id, data.branch_id, day)
        try:
            policy = day_policy(db, user.organization_id)
            check_day(policy, data.business_date, closing=True)
            closure = db.get(DayClosure, key)
            if closure is None or closure.version != data.expected_version:
                raise DayCloseError('STALE_VERSION', 'Жоба өзгерген. Жаңартып, қайта тексеріңіз.', 409)
            if closure.status != 'draft':
                raise DayCloseError('DAY_CLOSED', 'Күн бұрын жабылған.', 409)
            if closure.data_origin != policy['data_origin']:
                raise DayCloseError('DATA_ORIGIN_MISMATCH', 'Жобаның дерек режимі өзгерген.', 409)
            menu = _menu(db, user.organization_id)
            state = completeness(closure, menu)
            if not state['complete']:
                raise DayCloseError('DAY_INCOMPLETE', 'Күнді жабу үшін деректер толық емес.', 422, state)
            rows = sales_rows(closure, menu, policy['data_origin'])
            parsed, errors = parse_csv('daily_sales', csv_text(rows), expected_origin=policy['data_origin'])
            if errors:
                raise DayCloseError('DAY_ROWS_INVALID', 'Сатылым жолдары тексеруден өтпеді.', 422, errors[:50])
            recorded = _sales_on(db, user.organization_id, data.branch_id, day)
            fresh = [row for row in parsed if row['meal_id'] not in recorded]
            changed = [row for row in parsed if row['meal_id'] in recorded and row_digest(recorded[row['meal_id']].data) != row_digest(row)]
            unchanged = len(parsed) - len(fresh) - len(changed)
            listed = {row['meal_id'] for row in parsed}
            orphaned = sorted(meal_id for meal_id in recorded if meal_id not in listed)
            if orphaned:
                raise DayCloseError('RECORDED_SALES_NOT_LISTED', 'Бұл күнге сақталған сатылымы бар тағам «ұсынылмады» деп белгіленген.', 409,
                                    [{'meal_id': meal_id, 'recorded': recorded[meal_id].data} for meal_id in orphaned])
            if changed and not reason:
                raise DayCloseError('DAY_CONFLICT', 'Бұл күнге басқа мәндер сақталған. Түзету себебін көрсетіңіз.', 409,
                                    [{'meal_id': row['meal_id'], 'recorded': recorded[row['meal_id']].data, 'entered': row} for row in changed])
            if policy['data_origin'] == 'REAL':
                context = policy_context(db, user.organization_id)
                source = {**{field: context['source'][field] for field in ('source_id', 'mapping_version')}, 'channel': 'day_close'}
            else:
                source = {'source_id': 'manual_day_close', 'mapping_version': 'day-close-v1', 'channel': 'day_close'}
            batches, counts = [], {'inserted': len(fresh), 'updated': len(changed), 'unchanged': unchanged}
            for mode, part in (('append', fresh), ('correction', changed)):
                if not part:
                    continue
                preview = preview_import(db, user, kind='daily_sales', csv_text=csv_text(part), mode=mode,
                                         reason=reason if mode == 'correction' else None, source=source)
                if preview['errors']:
                    raise DayCloseError('DAY_ROWS_INVALID', 'Сатылым жолдары тексеруден өтпеді.', 422, preview['errors'][:50])
                commit_import(db, user, preview['id'], 'day-close:' + hashlib.sha256((idempotency_key + mode).encode()).hexdigest()[:48])
                batches.append(preview['id'])
            moved = db.execute(update(DayClosure).where(
                DayClosure.organization_id == key[0], DayClosure.branch_id == key[1], DayClosure.business_date == key[2],
                DayClosure.version == data.expected_version, DayClosure.status == 'draft').values(
                status='closed', version=data.expected_version + 1, closed_by=user.id, closed_at=now(),
                updated_by=user.id, updated_at=now(), batch_ids=batches, reason=reason)).rowcount
            if not moved:
                raise DayCloseError('STALE_VERSION', 'Жоба өзгерген. Жаңартып, қайта тексеріңіз.', 409)
            audit(db, user, 'day_close.closed', f'{data.branch_id}:{day}', data.branch_id,
                  {'business_date': day, 'version': data.expected_version + 1, 'is_open': closure.is_open, **counts,
                   'not_offered': state['counts']['not_offered'], 'batch_ids': batches, 'reason': reason})
            db.flush();db.expire_all()
            result = {**view(db, user, data.branch_id, data.business_date, policy), 'recorded_counts': counts}
            from .forecast_review import capture_day_snapshot
            capture_day_snapshot(db, user.organization_id, data.branch_id, day)
            db.add(Idempotency(id=hashlib.sha256((idempotency_key + user.id).encode()).hexdigest()[:32] + digest[:32],
                               organization_id=user.organization_id, actor_id=user.id, key=idempotency_key,
                               payload_hash=digest, response=result))
            db.commit()
            return result
        except DayCloseError as exc:
            db.rollback()
            problem(exc)
        except ImportProblem as exc:
            db.rollback()
            fail(exc.code, exc.message, exc.status)
        except IntegrityError:
            db.rollback()
            replay = receipt(db, user, idempotency_key, digest)
            if replay is not None:
                return replay
            fail('CONCURRENT_CLOSE', 'Күнді бір уақытта басқа пайдаланушы жапты. Жаңартып көріңіз.', 409)

    @app.post('/api/v1/day-close/reopen')
    def reopen_day(data: ReopenInput, idempotency_key: str | None = Header(None), user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager');branch_access(db, user, data.branch_id);require_key(idempotency_key)
        reason = data.reason.strip()
        if len(reason) < 3:
            fail('REOPEN_REASON_REQUIRED', 'Қайта ашу себебі кемінде 3 таңба болуы керек.', 422)
        digest = _digest({'action': 'reopen', **data.model_dump(mode='json')})
        replay = receipt(db, user, idempotency_key, digest)
        if replay is not None:
            return replay
        day = data.business_date.isoformat()
        try:
            policy = day_policy(db, user.organization_id)
        except DayCloseError as exc:
            problem(exc)
        from .forecast_review import capture_day_snapshot
        # Preserve the previously closed comparison before an explicit correction.
        # The snapshot shares the reopen transaction and cannot survive its rollback.
        capture_day_snapshot(db, user.organization_id, data.branch_id, day)
        moved = db.execute(update(DayClosure).where(
            DayClosure.organization_id == user.organization_id, DayClosure.branch_id == data.branch_id,
            DayClosure.business_date == day, DayClosure.version == data.expected_version, DayClosure.status == 'closed').values(
            status='draft', version=data.expected_version + 1, updated_by=user.id, updated_at=now(), reason=reason)).rowcount
        if not moved:
            db.rollback()
            fail('STALE_VERSION', 'Күн өзгерген немесе жабылмаған. Жаңартып көріңіз.', 409)
        audit(db, user, 'day_close.reopened', f'{data.branch_id}:{day}', data.branch_id,
              {'business_date': day, 'version': data.expected_version + 1, 'reason': reason})
        db.flush();db.expire_all()
        result = view(db, user, data.branch_id, data.business_date, policy)
        db.add(Idempotency(id=hashlib.sha256((idempotency_key + user.id).encode()).hexdigest()[:32] + digest[:32],
                           organization_id=user.organization_id, actor_id=user.id, key=idempotency_key,
                           payload_hash=digest, response=result))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            replay = receipt(db, user, idempotency_key, digest)
            if replay is not None:
                return replay
            fail('STALE_VERSION', 'Күн өзгерген. Жаңартып көріңіз.', 409)
        return result
