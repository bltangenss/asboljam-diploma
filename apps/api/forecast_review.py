"""Reconcile immutable forecasts with explicitly closed, versioned observed sales.

GETs never store anything. Closure commands and explicit refresh commands append snapshots
in their transaction. Synthetic scenarios and retrospective calculations are displayed,
but never represented as prospective business performance.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import uuid
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .data_policy import DEMO_TARGET, DataPolicyError, business_clock, policy_context
from .db import (DayClosure, Forecast, Idempotency, Job, ProductionPlan, Record,
                 RecordRevision, ReconciliationSnapshot, WorkingPlanSelection)
from .importing import rows_for
from .lineage import canonical_row, row_digest


SELECTION_RULE = 'latest_created_forecast_completed_before_local_day_start'
TIMING_LIMITATION = 'NEXT_DAY_CUTOFF_REQUIRES_SCHEDULING'


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _context(db, organization_id):
    context = policy_context(db, organization_id)
    if context['data_origin'] is None:
        raise DataPolicyError('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимі қолжетімсіз.', 403)
    return context


def _forecast_choice(db, organization_id, branch_id, target, cutoff, context):
    forecasts = list(db.scalars(select(Forecast).where(Forecast.organization_id == organization_id,
        Forecast.branch_id == branch_id, Forecast.result['target_date'].as_string() == target)))
    identifiers = [row.id for row in forecasts]
    jobs = list(db.scalars(select(Job).where(Job.organization_id == organization_id,
        Job.branch_id == branch_id, Job.kind == 'forecast', Job.result_id.in_(identifiers)))) if identifiers else []
    jobs_by_result = {row.result_id: row for row in jobs if row.status == 'succeeded'}
    candidates = []
    for forecast in forecasts:
        result = forecast.result
        if result.get('data_origin') != context['data_origin'] or str(result.get('branch_id')) != branch_id:
            continue
        job = jobs_by_result.get(forecast.id)
        created = _instant(job.created_at) if job else None
        finished = _instant(job.finished_at) if job else None
        published = _instant(forecast.created_at)
        execution = result.get('execution_context') or {}
        same_context = (execution.get('timezone') == context.get('timezone')
                        and execution.get('usage_mode') == context.get('usage_mode')
                        and execution.get('target_date') == target)
        prospective = bool(created and finished and published and created < cutoff and finished < cutoff
                           and published < cutoff and same_context)
        candidates.append((forecast, job, prospective, created or published or datetime.min.replace(tzinfo=timezone.utc)))
    eligible = [item for item in candidates if item[2]]
    chosen = max(eligible or candidates, key=lambda item: (item[3], item[0].id)) if candidates else None
    if chosen is None:
        return None, None, 'none'
    kind = 'synthetic_demo' if context['data_origin'] == 'SYNTHETIC' else 'prospective' if chosen[2] else 'historical'
    return chosen[0], chosen[1], kind


def _working_choice(db, organization_id, branch_id, target, cutoff, context):
    choices = list(db.scalars(select(WorkingPlanSelection).where(
        WorkingPlanSelection.organization_id == organization_id, WorkingPlanSelection.branch_id == branch_id,
        WorkingPlanSelection.target_date == target).order_by(WorkingPlanSelection.version.desc())))
    early = [row for row in choices if _instant(row.selected_at) and _instant(row.selected_at) < cutoff]
    choice = (early or choices)[0] if choices else None
    if choice is None:
        return None, {}, {}, False
    plan = db.get(ProductionPlan, choice.production_plan_id)
    source = db.get(Forecast, choice.forecast_id)
    if (plan is None or source is None or plan.organization_id != organization_id or source.organization_id != organization_id
            or plan.branch_id != branch_id or source.branch_id != branch_id or plan.target_date != target
            or plan.forecast_id != source.id or source.result.get('target_date') != target):
        return None, {}, {}, False
    source_job = db.scalar(select(Job).where(Job.organization_id == organization_id, Job.branch_id == branch_id,
        Job.kind == 'forecast', Job.result_id == source.id, Job.status == 'succeeded'))
    times = [choice.selected_at, plan.created_at, source.created_at,
             source_job.created_at if source_job else None, source_job.finished_at if source_job else None]
    early_source = all(_instant(value) and _instant(value) < cutoff for value in times)
    prospective = bool(early and early_source and context['data_origin'] == 'REAL'
                       and source.result.get('data_origin') == context['data_origin']
                       and choice.data_origin == context['data_origin'] and choice.usage_mode == context['usage_mode']
                       and source.result.get('execution_context', {}).get('usage_mode') == context.get('usage_mode')
                       and source.result.get('execution_context', {}).get('timezone') == context.get('timezone'))
    public = {key: getattr(choice, key) for key in ('id', 'production_plan_id', 'forecast_id', 'version',
        'selected_at', 'reason_code', 'reason', 'actor_id')}
    public.update(name=plan.document.get('name'), prospective=prospective)
    portions = {str(row['meal_id']): row['portions'] for row in plan.document.get('portions', [])}
    baseline = {str(row['meal_id']): _number(row.get('point_forecast')) for row in source.result.get('predictions', [])}
    return public, portions, baseline, prospective


def _fact_status(closure, line, recorded):
    if closure is None or closure.status != 'closed':
        return 'unclosed'
    if closure.is_open == 1 and line.get('state') == 'not_offered':
        return 'changed_after_closure' if recorded else 'not_offered'
    if recorded is None:
        return 'missing'
    actual = recorded.data
    if closure.is_open == 0:
        expected = {'units_sold': 0, 'available_portions': 0, 'stockout_flag': 0, 'promo': 0, 'is_open': 0}
    elif line.get('state') == 'sold':
        expected = {key: line.get(key) for key in ('units_sold', 'available_portions', 'stockout_flag', 'promo', 'price_kzt')}
        expected['is_open'] = 1
    else:
        return 'changed_after_closure'
    if any(value is None for value in expected.values()):
        return 'changed_after_closure'
    before, after = canonical_row(expected), canonical_row({key: actual.get(key) for key in expected})
    return 'closed' if before == after else 'changed_after_closure'


def _metrics(rows):
    pairs = [row for row in rows if row['actual_units'] is not None and row['forecast_point'] is not None]
    errors = [row['forecast_point'] - row['actual_units'] for row in pairs]
    total = sum(row['actual_units'] for row in pairs)
    intervals = [row['interval_hit'] for row in pairs if row['interval_hit'] is not None]
    return {'n': len(pairs), 'mae': sum(abs(error) for error in errors) / len(errors) if errors else None,
            'wape': sum(abs(error) for error in errors) / total if total else None,
            'bias': sum(errors) / len(errors) if errors else None,
            'interval_n': len(intervals), 'interval_coverage': sum(intervals) / len(intervals) if intervals else None,
            'nominal_coverage': 0.8, 'bias_definition': 'forecast_minus_observed',
            'wape_notice': 'ZERO_ACTUAL_TOTAL' if pairs and not total else None}


def _adjustment(rows):
    pairs = [row for row in rows if row['plan_absolute_error'] is not None and row['plan_forecast_point'] is not None]
    original = [abs(row['plan_forecast_point'] - row['actual_units']) for row in pairs]
    adjusted = [row['plan_absolute_error'] for row in pairs]
    return {'n': len(pairs), 'forecast_mae': sum(original) / len(pairs) if pairs else None,
            'plan_mae': sum(adjusted) / len(pairs) if pairs else None,
            'closer': sum(b < a for a, b in zip(original, adjusted)),
            'same': sum(b == a for a, b in zip(original, adjusted)),
            'worse': sum(b > a for a, b in zip(original, adjusted))}


def reconcile_day(db, organization_id, branch_id, target, *, context=None):
    """Read a single day. A closed document is not enough when canonical sales changed later."""
    context = context or _context(db, organization_id)
    zone = context.get('timezone') or 'UTC'
    try:
        cutoff = datetime.combine(date.fromisoformat(target), time(), ZoneInfo(zone)).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise DataPolicyError('REVIEW_DATE_RANGE_INVALID', 'Сверка кезеңінің күндерін тексеріңіз.') from None
    closure = db.get(DayClosure, (organization_id, branch_id, target))
    forecast, job, kind = _forecast_choice(db, organization_id, branch_id, target, cutoff, context)
    predictions = {str(row['meal_id']): row for row in forecast.result.get('predictions', [])} if forecast else {}
    working, portions, original, plan_early = _working_choice(db, organization_id, branch_id, target, cutoff, context)
    records = list(db.scalars(select(Record).where(Record.organization_id == organization_id,
        Record.branch_id == branch_id, Record.kind == 'daily_sales', Record.data['date'].as_string() == target)))
    stored = {str(row.data['meal_id']): row for row in records}
    revisions = {}
    for revision in db.scalars(select(RecordRevision).where(RecordRevision.organization_id == organization_id,
        RecordRevision.branch_id == branch_id, RecordRevision.kind == 'daily_sales',
        RecordRevision.after_data['date'].as_string() == target).order_by(RecordRevision.revision.desc())):
        revisions.setdefault(revision.natural_key, revision)
    lines = {str(row['meal_id']): row for row in closure.lines} if closure else {}
    names = {str(row['meal_id']): row.get('meal_name') for row in rows_for(db, organization_id, 'meals')}
    # Missing historical meals must stay visible even if the current menu has changed.
    meals = sorted(set(predictions) | set(portions) | set(stored) | set(lines))
    rows = []
    for meal in meals:
        record, prediction, line = stored.get(meal), predictions.get(meal, {}), lines.get(meal, {})
        status = _fact_status(closure, line, record)
        actual = record.data.get('units_sold') if record else None
        if record and record.data.get('data_origin') != context['data_origin']:
            status = 'changed_after_closure'
        point = _number(prediction.get('point_forecast'))
        low, high = _number(prediction.get('p10')), _number(prediction.get('p90'))
        paired = status == 'closed' and actual is not None and point is not None
        interval = bool(low <= actual <= high) if paired and low is not None and high is not None and low <= high else None
        revision = revisions.get(record.natural_key) if record else None
        identity = ({'natural_key': record.natural_key, 'record_id': record.id,
                     'revision': revision.revision if revision else 0, 'sha256': row_digest(record.data)} if record else None)
        stockout = bool(record.data['stockout_flag']) if record and record.data.get('stockout_flag') is not None else None
        plan_paired = status == 'closed' and actual is not None and portions.get(meal) is not None and original.get(meal) is not None
        rows.append({'date': target, 'meal_id': meal, 'meal_name': names.get(meal), 'forecast_point': point,
            'p10': low, 'p90': high, 'planned_portions': portions.get(meal), 'plan_forecast_point': original.get(meal),
            'actual_units': actual, 'delta': point - actual if paired else None,
            'absolute_error': abs(point - actual) if paired else None, 'interval_hit': interval,
            'stockout': stockout, 'stockout_time': line.get('stockout_time'), 'replenished_time': line.get('replenished_time'),
            'fact_status': status, 'fact_identity': identity,
            'eligible_for_performance': paired and kind == 'prospective' and context['usage_mode'] == 'PILOT',
            'plan_comparison_eligible': bool(plan_paired and plan_early and context['usage_mode'] == 'PILOT'),
            'plan_absolute_error': abs(portions[meal] - actual) if plan_paired else None})
    reasons = []
    if closure is None or closure.status != 'closed': reasons.append('DAY_NOT_CLOSED')
    if kind == 'none': reasons.append('NO_FORECAST')
    if kind == 'historical': reasons.append('FORECAST_NOT_AVAILABLE_BEFORE_DAY')
    if context['usage_mode'] != 'PILOT': reasons.append('DEMONSTRATION_DATA')
    if any(row['fact_status'] in ('missing', 'changed_after_closure') for row in rows): reasons.append('FACTS_INCOMPLETE_OR_CHANGED')
    complete = bool(closure and closure.status == 'closed' and rows and not any(
        row['fact_status'] not in ('closed', 'not_offered') for row in rows))
    # Never report a partial day as complete-period performance.
    if not complete:
        for row in rows:
            row['eligible_for_performance'] = row['plan_comparison_eligible'] = False
    fingerprint = _hash({'closure': {'version': closure.version, 'status': closure.status,
        'lines': closure.lines, 'is_open': closure.is_open, 'closed_at': closure.closed_at} if closure else None,
        'facts': [row['fact_identity'] for row in rows], 'forecast': _hash(forecast.result) if forecast else None,
        'forecast_id': forecast.id if forecast else None, 'job_created': job.created_at if job else None,
        'job_finished': job.finished_at if job else None, 'working': working, 'timezone': zone,
        'data_origin': context['data_origin'], 'usage_mode': context['usage_mode']})
    matched = [row for row in rows if row['absolute_error'] is not None]
    return {'date': target, 'branch_id': branch_id, 'data_origin': context['data_origin'], 'usage_mode': context['usage_mode'],
        'timezone': zone, 'day_start_utc': cutoff.isoformat(), 'closure_status': closure.status if closure else 'none',
        'closure_version': closure.version if closure else None, 'closed_at': closure.closed_at if closure else None,
        'complete': complete, 'fact_fingerprint': fingerprint, 'forecast_id': forecast.id if forecast else None,
        'forecast_kind': kind, 'forecast_created_at': job.created_at if job else None,
        'forecast_available_at': job.finished_at if job else None, 'working_plan': working,
        'eligible_for_performance': bool(complete and kind == 'prospective' and context['usage_mode'] == 'PILOT'),
        'exclusion_reasons': reasons, 'matched_observations': len(matched),
        'missing_observations': sum(row['fact_status'] in ('missing', 'unclosed', 'changed_after_closure') for row in rows),
        'stockout_observations': sum(row['stockout'] is True for row in matched),
        'metrics': _metrics([row for row in rows if row['eligible_for_performance']]),
        'demonstration_metrics': _metrics(matched), 'rows': rows}


def capture_day_snapshot(db, organization_id, branch_id, day):
    """Append in the caller's transaction, or reuse the same canonical input identity."""
    target = day.isoformat() if isinstance(day, date) else day
    # Lock order shared by explicit refresh and close/reopen; no commit inside this helper.
    # SQLite mutations are already serialized by current()'s organization write lock.
    db.scalar(select(DayClosure).where(DayClosure.organization_id == organization_id,
        DayClosure.branch_id == branch_id, DayClosure.business_date == target)
        .with_for_update().execution_options(populate_existing=True))
    document = reconcile_day(db, organization_id, branch_id, target)
    fingerprint = document['fact_fingerprint']
    old = db.scalar(select(ReconciliationSnapshot).where(ReconciliationSnapshot.organization_id == organization_id,
        ReconciliationSnapshot.branch_id == branch_id, ReconciliationSnapshot.target_date == target,
        ReconciliationSnapshot.input_sha256 == fingerprint))
    if old:
        return old
    version = db.scalar(select(func.max(ReconciliationSnapshot.version)).where(
        ReconciliationSnapshot.organization_id == organization_id, ReconciliationSnapshot.branch_id == branch_id,
        ReconciliationSnapshot.target_date == target)) or 0
    row = ReconciliationSnapshot(id=uuid.uuid4().hex, organization_id=organization_id, branch_id=branch_id,
        target_date=target, version=version + 1, input_sha256=fingerprint, document=document)
    db.add(row)
    db.flush()
    return row


def _snapshot_meta(row):
    return {key: getattr(row, key) for key in ('id', 'target_date', 'version', 'input_sha256', 'created_at')}


def review_period(db, organization_id, branch_id, days=28, end_date=None):
    context = _context(db, organization_id)
    latest = db.scalar(select(func.max(DayClosure.business_date)).where(DayClosure.organization_id == organization_id,
        DayClosure.branch_id == branch_id, DayClosure.status == 'closed'))
    default = date.fromisoformat(latest) if latest else (date.fromisoformat(DEMO_TARGET) if context['data_origin'] == 'SYNTHETIC'
        else business_clock(context)[1] - timedelta(days=1))
    end = end_date or default
    if end.toordinal() < days:
        raise DataPolicyError('REVIEW_DATE_RANGE_INVALID', 'Сверка кезеңінің күндерін тексеріңіз.')
    start = end - timedelta(days=days - 1)
    documents = [reconcile_day(db, organization_id, branch_id, (start + timedelta(days=step)).isoformat(), context=context)
                 for step in range(days)]
    history = [_snapshot_meta(row) for row in db.scalars(select(ReconciliationSnapshot).where(
        ReconciliationSnapshot.organization_id == organization_id, ReconciliationSnapshot.branch_id == branch_id,
        ReconciliationSnapshot.target_date >= start.isoformat(), ReconciliationSnapshot.target_date <= end.isoformat()
        ).order_by(ReconciliationSnapshot.target_date.desc(), ReconciliationSnapshot.version.desc()))]
    for document in documents:
        document['history'] = [item for item in history if item['target_date'] == document['date']]
    rows = [row for document in documents for row in document['rows']]
    eligible = [row for row in rows if row['eligible_for_performance']]
    complete_dates = {doc['date'] for doc in documents if doc['complete']}
    demo = [row for row in rows if row['date'] in complete_dates and row['absolute_error'] is not None
            and not row['eligible_for_performance']]
    closed = [doc for doc in documents if doc['closure_status'] == 'closed']
    latest_document = next((doc for doc in reversed(documents) if doc['date'] == latest), None)
    if latest and latest_document is None:
        latest_document = reconcile_day(db, organization_id, branch_id, latest, context=context)
    return {'branch_id': branch_id, 'date_from': start.isoformat(), 'date_to': end.isoformat(), 'timezone': context.get('timezone') or 'UTC',
        'data_origin': context['data_origin'], 'usage_mode': context['usage_mode'], 'selection_rule': SELECTION_RULE,
        'timing_policy': {'cutoff': 'local_midnight_before_target', 'limitation': TIMING_LIMITATION,
                          'synthetic_rule': 'fixed_scenario_demonstration_excluded_from_business_metrics'},
        'summary': {'closed_days': len(closed), 'incomplete_days': sum(not doc['complete'] for doc in documents),
            'excluded_days': sum(not doc['eligible_for_performance'] for doc in documents),
            'matched_observations': sum(doc['matched_observations'] for doc in documents),
            'stockout_observations': sum(doc['stockout_observations'] for doc in documents),
            'metrics': _metrics(eligible), 'without_stockout_metrics': _metrics([row for row in eligible if row['stockout'] is False]),
            'stockout_metrics': _metrics([row for row in eligible if row['stockout'] is True]),
            'demonstration_metrics': _metrics(demo),
            'adjustment': _adjustment([row for row in rows if row['plan_comparison_eligible']]),
            'demonstration_adjustment': _adjustment([row for row in rows if row['date'] in complete_dates
                                                     and not row['plan_comparison_eligible']])},
        'latest_closed_day': latest_document, 'days': documents, 'rows': rows, 'history': history,
        'fingerprint': _hash([doc['fact_fingerprint'] for doc in documents])}


class RefreshInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: str = Field(min_length=1, max_length=64)
    days: int = Field(default=28, ge=1, le=90)
    end_date: date | None = None


def register_forecast_review_routes(app, *, current, get_db, roles, branch_access, fail, audit):
    def period(db, user, branch, days, end):
        try:
            return review_period(db, user.organization_id, branch, days, end)
        except DataPolicyError as exc:
            fail(exc.code, exc.message, exc.status)

    @app.get('/api/v1/forecast-review')
    def read_review(branch_id: str, days: int = Query(28, ge=1, le=90), end_date: date | None = None,
                    user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst');branch_access(db, user, branch_id)
        return period(db, user, branch_id, days, end_date)

    @app.get('/api/v1/forecast-review/history/{snapshot_id}')
    def read_snapshot(snapshot_id: str, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst')
        row = db.get(ReconciliationSnapshot, snapshot_id)
        if row is None or row.organization_id != user.organization_id:
            fail('NOT_FOUND', 'Сверка табылмады.', 404)
        branch_access(db, user, row.branch_id)
        return {**deepcopy(row.document), 'snapshot': _snapshot_meta(row)}

    @app.post('/api/v1/forecast-review/refresh')
    def refresh_review(data: RefreshInput, idempotency_key: str | None = Header(None),
                       user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager');branch_access(db, user, data.branch_id)
        if not idempotency_key or not 8 <= len(idempotency_key) <= 128 or idempotency_key != idempotency_key.strip():
            fail('IDEMPOTENCY_REQUIRED', 'Idempotency-Key тақырыбы қажет (8–128 таңба).', 422)
        digest = _hash({'action': 'forecast_review.refresh', **data.model_dump(mode='json')})
        previous = db.scalar(select(Idempotency).where(Idempotency.organization_id == user.organization_id,
            Idempotency.actor_id == user.id, Idempotency.key == idempotency_key))
        if previous:
            if previous.payload_hash != digest:
                fail('IDEMPOTENCY_CONFLICT', 'Кілт басқа сұрауға қолданылған.', 409)
            return previous.response
        result = period(db, user, data.branch_id, data.days, data.end_date)
        try:
            snapshots = [capture_day_snapshot(db, user.organization_id, data.branch_id, doc['date'])
                         for doc in result['days'] if doc['closure_status'] == 'closed']
            response = {'snapshots': [_snapshot_meta(row) for row in snapshots],
                        'review': period(db, user, data.branch_id, data.days, data.end_date)}
            db.add(Idempotency(id=uuid.uuid4().hex, organization_id=user.organization_id, actor_id=user.id,
                key=idempotency_key, payload_hash=digest, response=response))
            audit(db, user, 'forecast_review.refreshed', data.branch_id, data.branch_id,
                  {'snapshot_ids': [row.id for row in snapshots]})
            db.commit()
        except IntegrityError:
            db.rollback()
            fail('REVIEW_CONCURRENT_RETRY', 'Сверка өзгерді. Сол кілтпен қайталаңыз.', 409)
        return response
