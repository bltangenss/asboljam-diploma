"""Exclusive tenant origins, immutable source contracts and explicit business dates.

No real source is inferred from a file, tenant name or current computer date.
Operator attestation references are declarations, not independently verified consent.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .db import Organization, OrganizationSource, Record

DEMO_ORIGIN = '2025-12-31'
DEMO_TARGET = '2026-01-01'


class DataPolicyError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def policy_context(db, organization_id):
    org = db.get(Organization, organization_id, populate_existing=True)
    if org is None:
        raise DataPolicyError('TENANT_NOT_FOUND', 'Ұйым табылмады.', 403)
    context = dict(data_policy=org.data_policy, data_origin=None, usage_mode=None,
                   timezone=org.timezone, currency=org.currency, source=None)
    if org.data_policy == 'synthetic_only':
        context.update(data_origin='SYNTHETIC', usage_mode='DEMO')
    elif org.data_policy == 'real_only':
        source = db.get(OrganizationSource, organization_id)
        if (source is None or source.purpose not in {'pilot', 'test_fixture'}
                or source.version != 1 or org.currency != 'KZT' or not org.timezone):
            raise DataPolicyError('REAL_SOURCE_REQUIRED', 'Ұйымның дерек көзін оператор баптауы керек.', 403)
        try:
            ZoneInfo(org.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise DataPolicyError('TIMEZONE_INVALID', 'Ұйымның уақыт белдеуін тексеріңіз.', 403) from None
        fields = ('source_id', 'mapping_version', 'branch_id', 'authorization_reference', 'purpose', 'version')
        context.update(data_origin='REAL', usage_mode='TEST' if source.purpose == 'test_fixture' else 'PILOT',
                       source={field: getattr(source, field) for field in fields})
    elif org.data_policy != 'unconfigured':
        raise DataPolicyError('DATA_POLICY_INVALID', 'Деректер режимі жарамсыз.', 403)
    return context


def business_clock(context, instant=None):
    instant = instant or datetime.now(timezone.utc)
    zone = ZoneInfo(context['timezone']) if context.get('timezone') else timezone.utc
    return instant, instant.astimezone(zone).date()


def metadata(db, organization_id):
    context = policy_context(db, organization_id)
    return {'data_origin': context['data_origin'], 'usage_mode': context['usage_mode'],
            'scenario_date': DEMO_TARGET if context['data_origin'] == 'SYNTHETIC' else None}


def ensure_rows(context, rows):
    expected = context['data_origin']
    if expected is None:
        raise DataPolicyError('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимін оператор баптауы керек.', 403)
    source = context.get('source')
    for row in rows:
        if not isinstance(row, dict) or row.get('data_origin') != expected:
            raise DataPolicyError('DATA_ORIGIN_MISMATCH', 'Деректердің шығу тегі ұйым режиміне сәйкес емес.', 409)
        if source and row.get('branch_id', source['branch_id']) != source['branch_id']:
            raise DataPolicyError('SOURCE_BRANCH_MISMATCH', 'Дерек көзінің бөлімшесі сәйкес емес.', 409)


def execution_context(db, organization_id, branch_id, origin, *, instant=None):
    context = policy_context(db, organization_id)
    if not context['data_origin']:
        raise DataPolicyError('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимін оператор баптауы керек.', 403)
    if context['source'] and context['source']['branch_id'] != branch_id:
        raise DataPolicyError('SOURCE_BRANCH_MISMATCH', 'Дерек көзінің бөлімшесі сәйкес емес.', 403)
    if origin is None:
        if context['data_origin'] == 'REAL':
            raise DataPolicyError('ORIGIN_REQUIRED', 'Аяқталған соңғы күнді нақты таңдаңыз.')
        origin = DEMO_ORIGIN
    try:
        day = date.fromisoformat(str(origin))
        if day.isoformat() != str(origin):
            raise ValueError()
        target = day + timedelta(days=1)
    except (ValueError, OverflowError):
        raise DataPolicyError('ORIGIN_INVALID', 'Күн пішімін тексеріңіз.') from None
    instant, today = business_clock(context, instant)
    if context['data_origin'] == 'SYNTHETIC' and origin != DEMO_ORIGIN:
        raise DataPolicyError('DEMO_DATE_FIXED', 'Демоның соңғы күні: 2025-12-31.')
    if context['data_origin'] == 'REAL' and day >= today:
        raise DataPolicyError('ORIGIN_NOT_CLOSED', 'Тек ұйым уақыт белдеуіндегі аяқталған күндерді таңдаңыз.')
    return {**context, 'version': 'execution-v1', 'organization_id': organization_id,
            'branch_id': branch_id, 'date_policy': 'synthetic_fixed' if context['data_origin'] == 'SYNTHETIC' else 'explicit_closed_day',
            'as_of_utc': instant.astimezone(timezone.utc).isoformat(), 'as_of_date': today.isoformat(),
            'origin': day.isoformat(), 'target_date': target.isoformat(), 'inventory_snapshot_date': target.isoformat(),
            'horizon_days': 1, 'historical': context['data_origin'] == 'REAL' and target < today}


def validate_execution_context(db, organization_id, context):
    if not isinstance(context, dict) or context.get('version') != 'execution-v1' or context.get('organization_id') != organization_id:
        raise DataPolicyError('EXECUTION_CONTEXT_INVALID', 'Есептің дерек контексті жарамсыз.', 409)
    current = policy_context(db, organization_id)
    if any(context.get(key) != value for key, value in current.items()):
        raise DataPolicyError('SOURCE_CONTEXT_CHANGED', 'Ұйымның дерек көзі өзгерген. Қайта есептеңіз.', 409)
    if current['source'] and context.get('branch_id') != current['source']['branch_id']:
        raise DataPolicyError('SOURCE_BRANCH_MISMATCH', 'Дерек көзінің бөлімшесі сәйкес емес.', 409)


def workspace_context(db, organization_id, branch_id=None):
    context = policy_context(db, organization_id)
    source = context['source']
    result = dict(version=1, mode={'SYNTHETIC': 'synthetic_fixed', 'REAL': 'real_business'}.get(context['data_origin'], 'unconfigured'),
                  data_origin=context['data_origin'], usage_mode=context['usage_mode'], timezone=context['timezone'],
                  currency=context['currency'], branch_id=branch_id, history_start=None, history_end=None,
                  forecast_origin=None, target_date=None, inventory_date=None, inventory_dates=[],
                  dates_editable=context['data_origin'] == 'REAL', operations_enabled=bool(context['data_origin']),
                  business_date=business_clock(context)[1].isoformat() if context['data_origin'] == 'REAL' else None,
                  source={key: value for key, value in source.items() if key != 'authorization_reference'} if source else None)
    if branch_id is None or context['data_origin'] is None:
        return result
    if source and branch_id != source['branch_id']:
        raise DataPolicyError('SOURCE_BRANCH_MISMATCH', 'Дерек көзінің бөлімшесі сәйкес емес.', 403)
    rows = [row.data for row in db.scalars(select(Record).where(Record.organization_id == organization_id,
            Record.branch_id == branch_id, Record.kind.in_(['daily_sales', 'inventory_lots'])))]
    ensure_rows(context, rows)
    days = sorted({row['date'] for row in rows if 'date' in row})
    snapshots = sorted({row['snapshot_date'] for row in rows if 'snapshot_date' in row})
    result.update(history_start=days[0] if days else None, history_end=days[-1] if days else None, inventory_dates=snapshots)
    if context['data_origin'] == 'SYNTHETIC':
        result.update(forecast_origin=DEMO_ORIGIN, target_date=DEMO_TARGET, inventory_date=DEMO_TARGET)
    else:
        closed = [day for day in days if day < result['business_date']]
        origin = closed[-1] if closed else None
        target = (date.fromisoformat(origin) + timedelta(days=1)).isoformat() if origin else None
        result.update(forecast_origin=origin, target_date=target,
                      inventory_date=target if target in snapshots else snapshots[-1] if snapshots else None)
    return result
