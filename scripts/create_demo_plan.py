"""Compute an initial plan through the real authenticated API and durable worker."""
import argparse,os,time
import httpx
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--email',default=os.environ.get('DEMO_EMAIL','admin@asboljam.local'))
parser.add_argument('--api',default='http://127.0.0.1:8000/api/v1')
args=parser.parse_args()
password=os.environ.get('DEMO_PASSWORD')
if not password: raise SystemExit('Set DEMO_PASSWORD in your environment; it is never printed.')
with httpx.Client(base_url=args.api,headers={'Origin':'http://127.0.0.1:3000'},timeout=60) as client:
 login=client.post('/session/login',json={'email':args.email,'password':password});login.raise_for_status()
 client.headers['X-CSRF-Token']=login.json()['csrf_token']
 def job(path,body):
  response=client.post(path,json=body);response.raise_for_status();run=response.json()['run_id']
  for attempt in range(180):
   status=client.get('/runs/'+run);status.raise_for_status();status=status.json()
   if status['status']=='succeeded': return status['result_id']
   if status['status']=='failed': raise RuntimeError(status['error'])
   time.sleep(1)
  raise TimeoutError('Worker did not complete the run; inspect its log.')
 existing=client.get('/plans',params={'branch_id':'1'});existing.raise_for_status()
 if existing.json()['total']:
  print('Existing branch 1 plan preserved.')
 else:
  forecast=job('/forecasts',{'branch_id':'1','origin':'2025-12-31','model':'hist_gradient_boosting'})
  plan=job('/procurement',{'branch_id':'1','forecast_id':forecast,'budget':'150000','strategy':'p50'})
  print('Computed SYNTHETIC draft for manager review:',plan)
 client.post('/session/logout',json={}).raise_for_status()
