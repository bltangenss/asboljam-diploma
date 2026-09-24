"""Durable database job worker. Run separately: python -m apps.worker.main."""
import argparse
import hashlib
import json
import time
import traceback
from sqlalchemy import select, update
from apps.api.db import Audit, Forecast, Job, Plan, make_engine, migrate, now, sessions
from apps.api.engine import forecast, procurement

LEASE_SECONDS=1800

def run_once(factory):
    claim_time=time.time()
    with factory() as db:
        db.execute(update(Job).where(Job.status=='running',Job.started_at<claim_time-LEASE_SECONDS).values(status='queued',started_at=None))
        db.commit()
        job=db.scalar(select(Job).where(Job.status=='queued').order_by(Job.created_at).limit(1))
        if job is None:
            return False
        job_id=job.id
        claimed=db.execute(update(Job).where(Job.id==job_id,Job.status=='queued').values(status='running',started_at=claim_time)).rowcount
        db.commit()
        if not claimed:
            return True
        payload,snapshot,kind=job.payload,job.snapshot,job.kind
    try:
        if kind=='forecast':
            result=forecast(snapshot['sales'],payload['branch_id'],payload['origin'],payload['model'])
            names={r['meal_id']:r['meal_name'] for r in snapshot.get('meals',[])}
            for item in result['predictions']:
                item['meal_name']=names.get(str(item['meal_id']),str(item['meal_id']))
        elif kind=='procurement':
            result=procurement(snapshot['forecast_result'],snapshot['ingredients'],snapshot['recipes'],snapshot['inventory_lots'],snapshot['supplier_offers'],snapshot['suppliers'],payload['branch_id'],snapshot['forecast_result']['target_date'],payload['budget'],payload['strategy'])
            result['recipe_versions']=sorted({r['recipe_version'] for r in snapshot['recipes']})
            ingredients={str(r['ingredient_id']):r['ingredient_name'] for r in snapshot['ingredients']}
            suppliers={str(r['supplier_id']):r['supplier_name'] for r in snapshot['suppliers']}
            for item in result['requirements']+result['lines']:
                item['ingredient_name']=ingredients.get(str(item['ingredient_id']),str(item['ingredient_id']))
                if 'supplier_id' in item:
                    item['supplier_name']=suppliers.get(str(item['supplier_id']),str(item['supplier_id']))
        else:
            raise ValueError('Unknown job kind')
        result['input_snapshot_sha256']=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result['data_origin']='SYNTHETIC'
        with factory() as db:
            job=db.get(Job,job_id)
            if job.status!='running' or job.started_at!=claim_time:
                return True
            if kind=='forecast':
                db.add(Forecast(id=job_id,organization_id=job.organization_id,branch_id=job.branch_id,result=result))
            else:
                db.add(Plan(id=job_id,organization_id=job.organization_id,branch_id=job.branch_id,forecast_id=payload['forecast_id'],version=1,status='ready',result=result))
            job.status='succeeded';job.result_id=job_id;job.finished_at=now()
            db.add(Audit(id=job_id,organization_id=job.organization_id,branch_id=job.branch_id,actor_id=job.actor_id,action=kind+'.succeeded',entity_id=job_id,details={'input_snapshot_sha256':result['input_snapshot_sha256']}))
            db.commit()
    except Exception as exc:
        with factory() as db:
            job=db.get(Job,job_id)
            if job.status=='running' and job.started_at==claim_time:
                job.status='failed'
                job.error=str(exc)[:500] if isinstance(exc,ValueError) else 'Есептеу орындалмады; сервер журналын тексеріңіз.'
                job.finished_at=now()
                db.commit()
        print(f'Job {job_id} failed ({type(exc).__name__})',flush=True)
        if not isinstance(exc,ValueError):
            traceback.print_exc()
    return True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--once',action='store_true',help='Process at most one job and exit')
    args=parser.parse_args()
    engine=make_engine();migrate(engine);factory=sessions(engine)
    print('AsBoljam worker ready; durable database queue',flush=True)
    if args.once:
        run_once(factory);return
    try:
        while True:
            if not run_once(factory): time.sleep(1)
    except KeyboardInterrupt:
        pass
if __name__=='__main__':
    main()
