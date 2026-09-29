"""Create an isolated browser-test organization; does not modify the demo organization."""
import json,secrets,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from apps.api.db import make_engine,migrate,sessions,Record
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
p=Path('.cache');p.mkdir(exist_ok=True)
(p/'e2e-login.json').write_text(json.dumps({'email':email,'password':password,'sale':payload,
                                        'onboarding':onboarding}),encoding='utf-8')
print('Isolated browser-test organization prepared; credentials stored in ignored .cache/e2e-login.json')
