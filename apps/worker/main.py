"""Durable database job worker. Run separately: python -m apps.worker.main."""
import argparse
from copy import deepcopy
import hashlib
import json
import sqlite3
import time
import uuid
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, OperationalError
from apps.api.accounts import lock_user
from apps.api.db import Audit, Forecast, Job, Organization, Plan, Record, User, make_engine, migrate, now, sessions
from apps.api.engine import forecast, procurement, validate_calculation_context

LEASE_SECONDS = 1800
PLANNING_ROLES = {'admin', 'manager'}
ERROR_MESSAGES = {
    'JOB_ACCESS_REVOKED': 'Есептеуге рұқсат өзгерген. Менеджерге хабарласыңыз.',
    'JOB_SCOPE_INVALID': 'Есептің бөлімшесі немесе дерек көзі сәйкес емес.',
    'JOB_INPUT_INVALID': 'Есептің кіріс деректерін тексеріп, қайта іске қосыңыз.',
    'JOB_CALCULATION_FAILED': 'Есептеу орындалмады. Әкімшіге есеп идентификаторын беріңіз.',
}


def sqlite_contention(exc):
    """Retry only SQLite's explicit lock codes, never arbitrary DB failures."""
    original = getattr(exc, 'orig', None)
    code = getattr(original, 'sqlite_errorcode', None)
    return (isinstance(exc, OperationalError) and isinstance(original, sqlite3.Error)
            and isinstance(code, int) and code & 0xff in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


def retry_sqlite_contention(operation, phase):
    delay, reported = 0.25, False
    while True:
        try:
            return operation()
        except OperationalError as exc:
            if not sqlite_contention(exc):
                raise
            if not reported:
                # Do not emit exception text: it can contain SQL and bound secrets.
                print(f'Worker database contention; retrying {phase}.', flush=True)
                reported = True
            time.sleep(delay)
            delay = min(delay * 2, 2.0)


def access_error(db, job, actor):
    organization=db.get(Organization,job.organization_id,populate_existing=True)
    if (organization is None or organization.status!='active'
            or organization.data_policy not in {'synthetic_only', 'real_only'}):
        return 'JOB_ACCESS_REVOKED'
    if (actor is None or not actor.active or actor.organization_id != job.organization_id
            or actor.role not in PLANNING_ROLES or job.branch_id not in actor.branch_ids):
        return 'JOB_ACCESS_REVOKED'
    if not isinstance(job.payload, dict) or not isinstance(job.snapshot, dict):
        return 'JOB_INPUT_INVALID'
    context = job.snapshot.get('execution_context')
    if context is None:
        if organization.data_policy != 'synthetic_only':
            return 'JOB_INPUT_INVALID'
        expected_origin = 'SYNTHETIC'
    else:
        if not isinstance(context, dict):
            return 'JOB_INPUT_INVALID'
        if context.get('organization_id') != job.organization_id or context.get('branch_id') != job.branch_id:
            return 'JOB_SCOPE_INVALID'
        from apps.api.data_policy import DataPolicyError, validate_execution_context
        try:
            validate_execution_context(db, job.organization_id, context)
        except DataPolicyError:
            return 'JOB_ACCESS_REVOKED'
        expected_origin = context.get('data_origin')
    branch = db.scalar(select(Record).where(
        Record.organization_id == job.organization_id, Record.kind == 'branches',
        Record.branch_id == job.branch_id).limit(1))
    if (branch is None or job.payload.get('branch_id') != job.branch_id
            or branch.data.get('data_origin') != expected_origin):
        return 'JOB_SCOPE_INVALID'
    if job.kind == 'procurement':
        forecast_id = job.payload.get('forecast_id')
        if not isinstance(forecast_id, str) or not forecast_id:
            return 'JOB_INPUT_INVALID'
        source = db.get(Forecast, forecast_id)
        if (source is None or source.organization_id != job.organization_id
                or source.branch_id != job.branch_id
                or source.result != job.snapshot.get('forecast_result')):
            return 'JOB_SCOPE_INVALID'
    elif job.kind != 'forecast':
        return 'JOB_INPUT_INVALID'
    return None


def snapshot_error(job):
    """The API builds immutable scoped snapshots; reject mismatched branch/origin."""
    context = job.snapshot.get('execution_context')
    if context is not None:
        try:
            validate_calculation_context(context, job.branch_id,
                origin=job.payload.get('origin') if job.kind == 'forecast' else None)
        except ValueError:
            return 'JOB_INPUT_INVALID'
    expected_origin = context['data_origin'] if context is not None else 'SYNTHETIC'
    lineage=job.snapshot.get('input_lineage')
    if lineage is not None:
        if not isinstance(lineage,dict):
            return 'JOB_INPUT_INVALID'
        if lineage.get('organization_id')!=job.organization_id:
            return 'JOB_SCOPE_INVALID'
    kinds = ('sales', 'meals') if job.kind == 'forecast' else (
        'ingredients', 'recipes', 'inventory_lots', 'supplier_offers', 'suppliers')
    for kind in kinds:
        rows = job.snapshot.get(kind)
        if not isinstance(rows, list):
            return 'JOB_INPUT_INVALID'
        for row in rows:
            if not isinstance(row, dict) or row.get('data_origin') != expected_origin:
                return 'JOB_INPUT_INVALID'
            if kind in {'sales', 'inventory_lots'} and row.get('branch_id') != job.branch_id:
                return 'JOB_SCOPE_INVALID'
            if context is not None:
                if kind == 'sales' and (not isinstance(row.get('date'), str) or row['date'] > context['origin']):
                    return 'JOB_INPUT_INVALID'
                if kind == 'inventory_lots' and row.get('snapshot_date') != context['inventory_snapshot_date']:
                    return 'JOB_INPUT_INVALID'
    if job.kind == 'procurement':
        source = job.snapshot.get('forecast_result', {})
        if not isinstance(source, dict):
            return 'JOB_INPUT_INVALID'
        if source.get('data_origin') != expected_origin or source.get('branch_id') != job.branch_id:
            return 'JOB_SCOPE_INVALID'
        if context is not None and (source.get('target_date') != context['target_date']
                or (source.get('execution_context') != context
                    and not (expected_origin == 'SYNTHETIC' and source.get('execution_context') is None))):
            return 'JOB_SCOPE_INVALID'
    return None


def result_error(job, result):
    if not isinstance(result, dict):
        return 'JOB_INPUT_INVALID'
    context = job.snapshot.get('execution_context')
    expected_origin = context['data_origin'] if context is not None else 'SYNTHETIC'
    if result.get('branch_id') != job.branch_id or result.get('data_origin') != expected_origin:
        return 'JOB_SCOPE_INVALID'
    if context is not None:
        if result.get('execution_context') != context or result.get('target_date') != context['target_date']:
            return 'JOB_SCOPE_INVALID'
        if job.kind == 'forecast' and result.get('origin', context['origin'] if expected_origin == 'SYNTHETIC' else None) != context['origin']:
            return 'JOB_SCOPE_INVALID'
    elif result.get('execution_context') is not None:
        return 'JOB_SCOPE_INVALID'
    return None


def finish(factory, job_id, claim_time, result=None, error=None):
    with factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        # Tenant suspension, credential changes and publication share this lock order.
        actor = lock_user(db,job.actor_id,job.organization_id)
        if result is not None:
            error = access_error(db, job, actor) or snapshot_error(job) or result_error(job, result)
        values = {'status': 'failed' if error else 'succeeded', 'finished_at': now(),
                  'error': f'{error}: {ERROR_MESSAGES[error]}' if error else None,
                  'result_id': None if error else job_id}
        # Fence stale workers atomically; checking ORM state before INSERT is not enough.
        changed = db.execute(update(Job).where(
            Job.id == job_id, Job.status == 'running', Job.started_at == claim_time
        ).values(**values)).rowcount
        if not changed:
            db.rollback()
            return
        if not error:
            if job.kind == 'forecast':
                db.add(Forecast(id=job_id, organization_id=job.organization_id,
                                branch_id=job.branch_id, result=result))
            else:
                db.add(Plan(id=job_id, organization_id=job.organization_id,
                            branch_id=job.branch_id, forecast_id=job.payload['forecast_id'],
                            version=1, status='ready', result=result))
        db.add(Audit(id=uuid.uuid4().hex, organization_id=job.organization_id,
                     branch_id=job.branch_id, actor_id=job.actor_id,
                     action=job.kind + ('.failed' if error else '.succeeded'), entity_id=job_id,
                     details={'code': error} if error else
                     {'input_snapshot_sha256': result['input_snapshot_sha256']}))
        db.commit()


def claim(factory):
    claim_time = time.time()
    with factory() as db:
        db.execute(update(Job).where(Job.status == 'running', Job.started_at < claim_time - LEASE_SECONDS)
                   .values(status='queued', started_at=None))
        db.commit()
        job = db.scalar(select(Job).where(Job.status == 'queued').order_by(Job.created_at).limit(1))
        if job is None:
            return None
        job_id = job.id
        # Read/validate before committing the claim. A lock failure must not leave
        # a newly running job behind when this entire short operation is retried.
        error = access_error(db, job, db.get(User, job.actor_id)) or snapshot_error(job)
        payload, snapshot, kind = job.payload, job.snapshot, job.kind
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == 'queued')
                             .values(status='running', started_at=claim_time)).rowcount
        db.commit()
        if not claimed:
            return ()
        return job_id, claim_time, error, payload, snapshot, kind


def run_once(factory):
    claimed = retry_sqlite_contention(lambda: claim(factory), 'claim')
    if claimed is None:
        return False
    if not claimed:
        return True
    job_id, claim_time, error, payload, snapshot, kind = claimed
    if error:
        retry_sqlite_contention(lambda: finish(factory, job_id, claim_time, error=error), 'publication')
        return True
    result, calculation_error = None, None
    try:
        context = snapshot.get('execution_context')
        context_argument = {'execution_context': context} if context is not None else {}
        if kind == 'forecast':
            result = forecast(snapshot['sales'], payload['branch_id'], payload['origin'], payload['model'], **context_argument)
            names = {r['meal_id']: r['meal_name'] for r in snapshot.get('meals', [])}
            for item in result['predictions']:
                item['meal_name'] = names.get(str(item['meal_id']), str(item['meal_id']))
        else:
            result = procurement(snapshot['forecast_result'], snapshot['ingredients'], snapshot['recipes'],
                                 snapshot['inventory_lots'], snapshot['supplier_offers'], snapshot['suppliers'],
                                 payload['branch_id'], snapshot['forecast_result']['target_date'],
                                 payload['budget'], payload['strategy'], **context_argument)
            result['recipe_versions'] = sorted({r['recipe_version'] for r in snapshot['recipes']})
            ingredients = {str(r['ingredient_id']): r['ingredient_name'] for r in snapshot['ingredients']}
            suppliers = {str(r['supplier_id']): r['supplier_name'] for r in snapshot['suppliers']}
            for item in result['requirements'] + result['lines']:
                item['ingredient_name'] = ingredients.get(str(item['ingredient_id']), str(item['ingredient_id']))
                if 'supplier_id' in item:
                    item['supplier_name'] = suppliers.get(str(item['supplier_id']), str(item['supplier_id']))
        result['input_snapshot_sha256'] = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        expected_origin = context['data_origin'] if context is not None else 'SYNTHETIC'
        if result.get('data_origin', expected_origin) != expected_origin:
            raise ValueError('Calculation returned conflicting data origin')
        result.setdefault('data_origin', expected_origin)
        if context is not None:
            if result.get('execution_context', context) != context:
                raise ValueError('Calculation returned conflicting execution context')
            result.setdefault('execution_context', deepcopy(context))
        # Copy the enqueue-time lineage, even if a correction landed during compute.
        # Freshness is derived when reading/approving, never relabelled at publication.
        result['input_lineage'] = deepcopy(snapshot.get('input_lineage'))
    except Exception as exc:
        calculation_error = 'JOB_INPUT_INVALID' if isinstance(exc, ValueError) else 'JOB_CALCULATION_FAILED'
        result = None
        # DB exceptions can include bound rows or credentials; never log exception text.
        print(f'Job {job_id} failed ({calculation_error})', flush=True)
    # Publication has a fresh transaction on each retry and retains the original
    # claim-time fence. SQLite contention must not discard or recompute a result.
    retry_sqlite_contention(lambda: finish(factory, job_id, claim_time,
                                          result=result, error=calculation_error), 'publication')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Process at most one job and exit')
    args = parser.parse_args()
    from apps.api.config import load_settings
    settings = load_settings()
    engine = make_engine(settings.database_url)
    try:
        migrate(engine)
        factory = sessions(engine)
        print('AsBoljam worker ready; durable database queue', flush=True)
        if args.once:
            run_once(factory)
            return
        while True:
            if not run_once(factory):
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    except DBAPIError:
        # Fatal database faults stay visible without leaking connection/row data.
        raise SystemExit('AsBoljam worker stopped (DATABASE_ERROR).') from None


if __name__ == '__main__':
    main()
