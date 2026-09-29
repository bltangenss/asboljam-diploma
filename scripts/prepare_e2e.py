"""Create an isolated browser-test organization; does not modify the demo organization."""
import json,secrets,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.api.db import make_engine,migrate,sessions,Record,User
from apps.api.importing import insert_rows
from scripts.seed_demo import seed
from apps.api.tenants import bootstrap_tenant
from sqlalchemy import select
engine=make_engine();migrate(engine);factory=sessions(engine)
password=secrets.token_urlsafe(20);org='e2e-'+uuid.uuid4().hex[:12];email=org+'@asboljam.local'
seed(factory,password,email,org)
with factory() as db:
 rows=db.scalars(select(Record).where(Record.organization_id==org,Record.kind=='daily_sales',Record.branch_id=='1'))
 row=next(r for r in rows if r.data['date']=='2024-01-01' and r.data['meal_id']=='1')
 payload=row.data.copy();db.delete(row);db.commit()
onboarding_org='e2e-empty-'+uuid.uuid4().hex[:12]
onboarding={'organization_id':onboarding_org,'email':onboarding_org+'@asboljam.local',
            'password':secrets.token_urlsafe(20)}
with factory() as db:
 bootstrap_tenant(db,organization_id=onboarding_org,name='Empty synthetic browser fixture',
     timezone='Asia/Qyzylorda',data_policy='synthetic_only',email=onboarding['email'],
     password=onboarding['password'],operator_id='e2e_fixture',reason='Isolated browser onboarding test')
 db.commit()
imports_org='e2e-imports-'+uuid.uuid4().hex[:12]
imports={'organization_id':imports_org,'email':imports_org+'@asboljam.local',
         'password':secrets.token_urlsafe(20)}
with factory() as db:
 created=bootstrap_tenant(db,organization_id=imports_org,name='Synthetic correction browser fixture',
     timezone='Asia/Qyzylorda',data_policy='synthetic_only',email=imports['email'],
     password=imports['password'],operator_id='e2e_fixture',reason='Isolated browser import correction test')
 # A small one-branch fixture reuses supplied SYNTHETIC rows without shifting dates.
 for record in db.scalars(select(Record).where(Record.organization_id==org)):
  row=record.data.copy()
  if row.get('branch_id') not in (None,'1'): continue
  if record.kind in {'meals','recipes','daily_sales'} and row.get('meal_id')!='1': continue
  if record.kind=='daily_sales' and row['date']<'2025-10-01': continue
  insert_rows(db,imports_org,record.kind,[row])
  if record.kind=='daily_sales' and row['date']=='2025-12-31': imports['sale']=row
 db.get(User,created['admin_user_id']).branch_ids=['1']
 db.commit()
p=Path('.cache');p.mkdir(exist_ok=True)
(p/'e2e-login.json').write_text(json.dumps({'email':email,'password':password,'sale':payload,
                                        'onboarding':onboarding,'imports':imports}),encoding='utf-8')
print('Isolated browser-test organization prepared; credentials stored in ignored .cache/e2e-login.json')
