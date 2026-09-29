"""Durable database job worker. Run separately: python -m apps.worker.main."""
import argparse
import hashlib
import json
import time
import uuid
from sqlalchemy import select, update
from apps.api.db import Audit, Forecast, Job, Plan, Record, User, make_engine, migrate, now, sessions
from apps.api.engine import forecast, procurement

LEASE_SECONDS = 1800
PLANNING_ROLES = {'admin', 'manager'}
ERROR_MESSAGES = {
    'JOB_ACCESS_REVOKED': 'Есептеуге рұқсат өзгерген. Менеджерге хабарласыңыз.',
    'JOB_SCOPE_INVALID': 'Есептің бөлімшесі немесе дерек көзі сәйкес емес.',
    'JOB_INPUT_INVALID': 'Есептің кіріс деректерін тексеріп, қайта іске қосыңыз.',
    'JOB_CALCULATION_FAILED': 'Есептеу орындалмады. Әкімшіге есеп идентификаторын беріңіз.',
}


def access_error(db, job, actor):
    if (actor is None or not actor.active or actor.organization_id != job.organization_id
            or actor.role not in PLANNING_ROLES or job.branch_id not in actor.branch_ids):
        return 'JOB_ACCESS_REVOKED'
    if not isinstance(job.payload, dict) or not isinstance(job.snapshot, dict):
        return 'JOB_INPUT_INVALID'
    exists = db.scalar(select(Record.id).where(
        Record.organization_id == job.organization_id, Record.kind == 'branches',
        Record.branch_id == job.branch_id).limit(1))
    if exists is None or job.payload.get('branch_id') != job.branch_id:
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
    kinds = ('sales', 'meals') if job.kind == 'forecast' else (
        'ingredients', 'recipes', 'inventory_lots', 'supplier_offers', 'suppliers')
    for kind in kinds:
        rows = job.snapshot.get(kind)
        if not isinstance(rows, list):
            return 'JOB_INPUT_INVALID'
        for row in rows:
            if not isinstance(row, dict) or row.get('data_origin') != 'SYNTHETIC':
                return 'JOB_INPUT_INVALID'
            if kind in {'sales', 'inventory_lots'} and row.get('branch_id') != job.branch_id:
                return 'JOB_SCOPE_INVALID'
    if job.kind == 'procurement':
        source = job.snapshot.get('forecast_result', {})
        if not isinstance(source, dict):
            return 'JOB_INPUT_INVALID'
        if source.get('data_origin') != 'SYNTHETIC' or source.get('branch_id') != job.branch_id:
            return 'JOB_SCOPE_INVALID'
    return None


def finish(factory, job_id, claim_time, result=None, error=None):
    with factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        # This no-op UPDATE locks the actor on both SQLite and PostgreSQL.
        # Access updates take the same lock before cancelling queued/running jobs.
        db.execute(update(User).where(User.id == job.actor_id).values(active=User.active))
        actor = db.get(User, job.actor_id, populate_existing=True)
        if result is not None:
            error = access_error(db, job, actor)
            if result.get('branch_id') != job.branch_id:
                error = 'JOB_SCOPE_INVALID'
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


def run_once(factory):
    claim_time = time.time()
    with factory() as db:
        db.execute(update(Job).where(Job.status == 'running', Job.started_at < claim_time - LEASE_SECONDS)
                   .values(status='queued', started_at=None))
        db.commit()
        job = db.scalar(select(Job).where(Job.status == 'queued').order_by(Job.created_at).limit(1))
        if job is None:
            return False
        job_id = job.id
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == 'queued')
                             .values(status='running', started_at=claim_time)).rowcount
        db.commit()
        if not claimed:
            return True
        error = access_error(db, job, db.get(User, job.actor_id)) or snapshot_error(job)
        payload, snapshot, kind = job.payload, job.snapshot, job.kind
    if error:
        finish(factory, job_id, claim_time, error=error)
        return True
    try:
        if kind == 'forecast':
            result = forecast(snapshot['sales'], payload['branch_id'], payload['origin'], payload['model'])
            names = {r['meal_id']: r['meal_name'] for r in snapshot.get('meals', [])}
            for item in result['predictions']:
                item['meal_name'] = names.get(str(item['meal_id']), str(item['meal_id']))
        else:
            result = procurement(snapshot['forecast_result'], snapshot['ingredients'], snapshot['recipes'],
                                 snapshot['inventory_lots'], snapshot['supplier_offers'], snapshot['suppliers'],
                                 payload['branch_id'], snapshot['forecast_result']['target_date'],
                                 payload['budget'], payload['strategy'])
            result['recipe_versions'] = sorted({r['recipe_version'] for r in snapshot['recipes']})
            ingredients = {str(r['ingredient_id']): r['ingredient_name'] for r in snapshot['ingredients']}
            suppliers = {str(r['supplier_id']): r['supplier_name'] for r in snapshot['suppliers']}
            for item in result['requirements'] + result['lines']:
                item['ingredient_name'] = ingredients.get(str(item['ingredient_id']), str(item['ingredient_id']))
                if 'supplier_id' in item:
                    item['supplier_name'] = suppliers.get(str(item['supplier_id']), str(item['supplier_id']))
        result['input_snapshot_sha256'] = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        result['data_origin'] = 'SYNTHETIC'
        finish(factory, job_id, claim_time, result=result)
    except Exception as exc:
        code = 'JOB_INPUT_INVALID' if isinstance(exc, ValueError) else 'JOB_CALCULATION_FAILED'
        finish(factory, job_id, claim_time, error=code)
        # DB exceptions can include bound rows or credentials; never log exception text.
        print(f'Job {job_id} failed ({code})', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Process at most one job and exit')
    args = parser.parse_args()
    from apps.api.config import load_settings
    settings = load_settings()
    engine = make_engine(settings.database_url)
    migrate(engine)
    factory = sessions(engine)
    print('AsBoljam worker ready; durable database queue', flush=True)
    if args.once:
        run_once(factory)
        return
    try:
        while True:
            if not run_once(factory):
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
