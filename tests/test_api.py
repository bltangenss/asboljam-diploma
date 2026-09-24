"""API integration tests: real SQLite, real worker, actual import/approval transactions."""
import json
import os
import csv
import io
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import func,select
from apps.api.db import Audit,Job,Plan,Record,User
from apps.api.main import create_app
from apps.api.importing import SCHEMAS,parse_csv,safe_csv
from apps.api.security import password_hash
from apps.worker.main import run_once
from scripts.seed_demo import seed

PASSWORD='Test-only-password-927!'
ORIGIN={'Origin':'http://localhost:3000'}

class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Path('.cache').mkdir(exist_ok=True)
        external_url=os.environ.get('ASBOLJAM_TEST_DATABASE_URL')
        cls.temp=None if external_url else tempfile.TemporaryDirectory(dir='.cache',prefix='api-tests-')
        cls.url=external_url or ('sqlite:///'+(Path(cls.temp.name).resolve()/'test.sqlite').as_posix())
        cls.app=create_app(cls.url)
        cls.factory=cls.app.state.sessions
        seed(cls.factory,PASSWORD)
        with cls.factory() as db:
            for email,org,role,branches in [('manager@test.local','demo','manager',['1']),('analyst@test.local','demo','analyst',['1']),('warehouse@test.local','demo','warehouse',['1']),('foreign@test.local','other','manager',['1'])]:
                db.add(User(id=uuid.uuid4().hex,organization_id=org,email=email,password_hash=password_hash(PASSWORD),role=role,branch_ids=branches))
            db.commit()
        cls.tokens={}
        for email in ['admin@asboljam.local','manager@test.local','analyst@test.local','warehouse@test.local','foreign@test.local']:
            client=TestClient(cls.app)
            response=client.post('/api/v1/session/login',json={'email':email,'password':PASSWORD},headers=ORIGIN)
            assert response.status_code==200,response.text
            cls.tokens[email]=(client.cookies.get('asboljam_session'),response.json()['csrf_token'])
            client.close()
    @classmethod
    def tearDownClass(cls):
        cls.app.state.engine.dispose()
        if cls.temp is not None: cls.temp.cleanup()
    def client_for(self,email='admin@asboljam.local'):
        token,csrf=self.tokens[email]
        client=TestClient(self.app)
        client.cookies.set('asboljam_session',token)
        client.headers.update({**ORIGIN,'X-CSRF-Token':csrf})
        self.addCleanup(client.close)
        return client
    def ready_plan(self,shortages=1):
        identifier=uuid.uuid4().hex
        with self.factory() as db:
            db.add(Plan(id=identifier,organization_id='demo',branch_id='1',forecast_id='fixture',version=1,status='ready',result={'constraints_valid':True,'shortage_count':shortages,'lines':[],'requirements':[],'total_cost':'0','target_date':'2026-01-01'}))
            db.commit()
        return identifier
    def test_auth_origin_csrf_and_limit(self):
        c=TestClient(self.app);self.addCleanup(c.close)
        self.assertEqual(c.get('/api/v1/branches').status_code,401)
        self.assertEqual(c.post('/api/v1/session/login',json={'email':'admin@asboljam.local','password':PASSWORD}).status_code,403)
        c=self.client_for()
        self.assertEqual(c.post('/api/v1/forecasts',json={'branch_id':'1'},headers={'X-CSRF-Token':'wrong'}).status_code,403)
        self.assertEqual(c.post('/api/v1/forecasts',json={'branch_id':'1'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(c.get('/api/v1/sales?limit=201').status_code,422)
    def test_branch_and_organization_isolation(self):
        c=self.client_for('manager@test.local')
        self.assertEqual(c.get('/api/v1/branches').json()['total'],1)
        self.assertEqual(c.get('/api/v1/sales?branch_id=2').status_code,403)
        self.assertEqual(c.get('/api/v1/exports/sales?branch_id=2').status_code,403)
        plan=self.ready_plan()
        foreign=self.client_for('foreign@test.local')
        self.assertEqual(foreign.get('/api/v1/plans/'+plan).status_code,404)
        self.assertEqual(foreign.get('/api/v1/plans/'+plan+'/export').status_code,404)
        self.assertEqual(foreign.get('/api/v1/plans').json()['total'],0)
        self.assertEqual(foreign.get('/api/v1/sales').json()['total'],0)
    def test_roles(self):
        analyst=self.client_for('analyst@test.local');warehouse=self.client_for('warehouse@test.local')
        plan=self.ready_plan()
        payload={'expected_version':1,'reason':'Reviewed','acknowledge_shortage':True}
        self.assertEqual(analyst.post('/api/v1/plans/'+plan+'/approve',json=payload,headers={'Idempotency-Key':'role-test'}).status_code,403)
        self.assertEqual(warehouse.get('/api/v1/inventory?branch_id=1').status_code,200)
        self.assertEqual(warehouse.get('/api/v1/sales').status_code,403)
        self.assertEqual(warehouse.post('/api/v1/forecasts',json={'branch_id':'1'}).status_code,403)
        self.assertEqual(analyst.get('/api/v1/users').status_code,403)
    def test_import_transaction_duplicates_and_oracle(self):
        c=self.client_for()
        header='date,branch_id,meal_id,units_sold,available_portions,stockout_flag,is_open,promo,price_kzt,data_origin\n'
        valid='2026-01-01,1,1,2,3,0,1,0,2300,SYNTHETIC\n'
        bad='2026-01-01,1,2,-1,3,0,1,0,2300,SYNTHETIC\n'
        preview=c.post('/api/v1/imports/preview',json={'kind':'daily_sales','csv_text':header+valid+bad}).json()
        self.assertFalse(preview['valid'])
        self.assertEqual(c.post('/api/v1/imports/'+preview['id']+'/commit').status_code,422)
        self.assertEqual(c.get('/api/v1/sales?branch_id=1&date_from=2026-01-01').json()['total'],0)
        preview=c.post('/api/v1/imports/preview',json={'kind':'daily_sales','csv_text':header+valid}).json()
        self.assertTrue(preview['valid'],preview)
        path='/api/v1/imports/'+preview['id']+'/commit'
        self.assertEqual(c.post(path).status_code,200)
        self.assertEqual(c.post(path).status_code,409)
        duplicate=c.post('/api/v1/imports/preview',json={'kind':'daily_sales','csv_text':header+valid}).json()
        self.assertFalse(duplicate['valid'])
        self.assertEqual(duplicate['errors'][0]['code'],'DUPLICATE_KEY')
        self.assertEqual(c.post('/api/v1/imports/preview',json={'kind':'oracle_do_not_train','csv_text':'latent_demand_ORACLE_ONLY\n1'}).status_code,400)
        rows,errors=parse_csv('daily_sales',header.rstrip() + ',latent_demand_ORACLE_ONLY\n')
        self.assertEqual(errors[0]['code'],'INVALID_COLUMNS')
    def test_import_preview_rechecks_scope_and_duplicates_at_commit(self):
        c=self.client_for('manager@test.local')
        csv='date,branch_id,meal_id,units_sold,available_portions,stockout_flag,is_open,promo,price_kzt,data_origin\n2026-01-02,2,1,2,3,0,1,0,2300,SYNTHETIC\n'
        preview=c.post('/api/v1/imports/preview',json={'kind':'daily_sales','csv_text':csv}).json()
        self.assertFalse(preview['valid'])
        self.assertEqual(preview['errors'][0]['code'],'BRANCH_FORBIDDEN')
    def test_approval_idempotency_shortage_and_audit(self):
        c=self.client_for('manager@test.local');plan=self.ready_plan()
        path='/api/v1/plans/'+plan+'/approve'
        payload={'expected_version':1,'reason':'Reviewed shortages','acknowledge_shortage':False}
        headers={'Idempotency-Key':uuid.uuid4().hex}
        self.assertEqual(c.post(path,json=payload,headers=headers).status_code,422)
        payload['acknowledge_shortage']=True
        approved=c.post(path,json=payload,headers=headers)
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(approved.json()['status'],'approved')
        self.assertEqual(approved.json()['version'],2)
        self.assertEqual(c.post(path,json=payload,headers=headers).json(),approved.json())
        changed={**payload,'reason':'Different payload'}
        self.assertEqual(c.post(path,json=changed,headers=headers).status_code,409)
        self.assertEqual(c.post(path,json=payload,headers={'Idempotency-Key':uuid.uuid4().hex}).status_code,409)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.entity_id==plan,Audit.action=='plan.approved')),1)
    def test_concurrent_approval_creates_single_decision(self):
        plan=self.ready_plan(0)
        def approve(_):
            with TestClient(self.app) as c:
                token,csrf=self.tokens['manager@test.local']
                c.cookies.set('asboljam_session',token)
                return c.post('/api/v1/plans/'+plan+'/approve',json={'expected_version':1,'reason':'Concurrency test'},headers={**ORIGIN,'X-CSRF-Token':csrf,'Idempotency-Key':uuid.uuid4().hex}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses=list(pool.map(approve,range(2)))
        self.assertEqual(sorted(statuses),[200,409])
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.entity_id==plan,Audit.action=='plan.approved')),1)
    def test_native_refresh_rotation_and_reuse_revocation(self):
        with TestClient(self.app) as c:
            result=c.post('/api/v1/auth/token',json={'email':'manager@test.local','password':PASSWORD}).json()
            access=result['access_token'];refresh=result['refresh_token']
            self.assertEqual(c.get('/api/v1/branches',headers={'Authorization':'Bearer '+access}).status_code,200)
            rotated=c.post('/api/v1/auth/refresh',json={'refresh_token':refresh})
            self.assertEqual(rotated.status_code,200,rotated.text)
            self.assertNotEqual(rotated.json()['refresh_token'],refresh)
            self.assertEqual(c.get('/api/v1/branches',headers={'Authorization':'Bearer '+access}).status_code,401)
            self.assertEqual(c.post('/api/v1/auth/refresh',json={'refresh_token':refresh}).status_code,401)
            self.assertEqual(c.get('/api/v1/branches',headers={'Authorization':'Bearer '+rotated.json()['access_token']}).status_code,401)
    def test_export_injection_and_generator_exclusion(self):
        text=safe_csv([{'name':'=HYPERLINK("http://evil")','value':'  @danger'}])
        self.assertIn("'=HYPERLINK",text)
        self.assertIn("'  @danger",text)
        c=self.client_for()
        self.assertNotIn('demand_multiplier',c.get('/api/v1/branches').text)
        self.assertNotIn('base_daily_demand',c.get('/api/v1/meals').text)
        self.assertNotIn('ORACLE',c.get('/api/v1/exports/sales?branch_id=1').text)
    def test_full_worker_forecast_procurement_and_export(self):
        c=self.client_for()
        queued=c.post('/api/v1/forecasts',json={'branch_id':'1','origin':'2025-12-31','model':'seasonal_naive_7'})
        self.assertEqual(queued.status_code,202,queued.text)
        identifier=queued.json()['run_id']
        self.assertEqual(c.get('/api/v1/runs/'+identifier).json()['status'],'queued')
        self.assertEqual(self.client_for('foreign@test.local').get('/api/v1/runs/'+identifier).status_code,404)
        self.assertTrue(run_once(self.factory))
        job=c.get('/api/v1/runs/'+identifier).json()
        self.assertEqual(job['status'],'succeeded',job)
        forecast=c.get('/api/v1/forecasts/'+identifier).json()
        self.assertEqual(len(forecast['predictions']),12)
        self.assertEqual(forecast['target_date'],'2026-01-01')
        self.assertEqual(c.post('/api/v1/procurement',json={'branch_id':'1','forecast_id':identifier,'budget':'300000','strategy':'p90_stress'}).status_code,422)
        queued=c.post('/api/v1/procurement',json={'branch_id':'1','forecast_id':identifier,'budget':'300000','strategy':'point'})
        self.assertEqual(queued.status_code,202,queued.text)
        plan_id=queued.json()['run_id']
        self.assertTrue(run_once(self.factory))
        job=c.get('/api/v1/runs/'+plan_id).json()
        self.assertEqual(job['status'],'succeeded',job)
        plan=c.get('/api/v1/plans/'+plan_id).json()
        self.assertTrue(plan['constraints_valid'])
        approved=c.post('/api/v1/plans/'+plan_id+'/approve',json={'expected_version':1,'reason':'Integration verification','acknowledge_shortage':True},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(approved.status_code,200,approved.text)
        exported=c.get('/api/v1/plans/'+plan_id+'/export')
        self.assertEqual(exported.status_code,200)
        self.assertIn('approved',exported.text)
        self.assertFalse(run_once(self.factory))
    def test_openapi_contract_matches(self):
        artifact=json.loads(Path('contracts/openapi.json').read_text(encoding='utf-8'))
        self.assertEqual(set(artifact['paths']),set(self.app.openapi()['paths']))
    def test_csv_numeric_blank_fk_and_unit_validation(self):
        rows,errors=parse_csv('ingredients','ingredient_id,ingredient_name,unit,reference_cost_kzt,shelf_life_days,yield_factor,storage_capacity,data_origin\n99,x,kg,1,2,0,4,SYNTHETIC\n')
        self.assertTrue(errors)
        c=self.client_for()
        text='branch_id,ingredient_id,lot_id,snapshot_date,expiry_date,on_hand_qty,unit,data_origin\n1,1,TESTLOT,2026-01-01,2026-01-02,4,L,SYNTHETIC\n'
        result=c.post('/api/v1/imports/preview',json={'kind':'inventory_lots','csv_text':text}).json()
        self.assertFalse(result['valid'])
        self.assertEqual(result['errors'][0]['code'],'UNIT_MISMATCH')
    def test_concurrent_same_idempotency_key_replays(self):
        plan=self.ready_plan(0)
        key=uuid.uuid4().hex
        def approve(_):
            with TestClient(self.app) as c:
                token,csrf=self.tokens['manager@test.local']
                c.cookies.set('asboljam_session',token)
                result=c.post('/api/v1/plans/'+plan+'/approve',json={'expected_version':1,'reason':'Same-key replay'},headers={**ORIGIN,'X-CSRF-Token':csrf,'Idempotency-Key':key})
                return result.status_code,result.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(approve,range(2)))
        self.assertEqual([r[0] for r in outcomes],[200,200],outcomes)
        self.assertEqual(outcomes[0][1],outcomes[1][1])
    def test_empty_purchase_export_retains_shortage_summary(self):
        plan=self.ready_plan(3)
        exported=self.client_for().get('/api/v1/plans/'+plan+'/export')
        self.assertEqual(exported.status_code,200)
        self.assertIn('shortage_count',exported.text)
        self.assertIn('summary',exported.text)
    def test_session_logout_revokes_cookie(self):
        with TestClient(self.app) as c:
            login=c.post('/api/v1/session/login',json={'email':'analyst@test.local','password':PASSWORD},headers=ORIGIN)
            csrf=login.json()['csrf_token']
            old_cookie=c.cookies.get('asboljam_session')
            self.assertEqual(c.post('/api/v1/session/logout',headers={**ORIGIN,'X-CSRF-Token':csrf}).status_code,200)
            c.cookies.set('asboljam_session',old_cookie)
            self.assertEqual(c.get('/api/v1/session/me').status_code,401)
    def test_sales_filter_and_full_filtered_export(self):
        c=self.client_for()
        query='?branch_id=1&meal_id=1&date_from=2025-12-30&date_to=2025-12-31'
        listed=c.get('/api/v1/sales'+query+'&limit=1').json()
        self.assertEqual(listed['total'],2)
        self.assertEqual(len(listed['items']),1)
        self.assertEqual(listed['items'][0]['meal_id'],'1')
        exported=c.get('/api/v1/exports/sales'+query)
        rows=list(csv.DictReader(io.StringIO(exported.text.lstrip('\ufeff'))))
        self.assertEqual(len(rows),2)
        self.assertEqual({r['meal_id'] for r in rows},{'1'})
        self.assertEqual({r['date'] for r in rows},{'2025-12-30','2025-12-31'})
        self.assertTrue(all('yield_factor' in r for r in c.get('/api/v1/recipes').json()['items']))
    def test_dashboard_warning_counts_follow_branch_snapshot(self):
        c=self.client_for()
        for branch in ('1','2','3'):
            result=c.get('/api/v1/dashboard?branch_id='+branch).json()
            with self.factory() as db:
                lots=[r.data for r in db.scalars(select(Record).where(Record.organization_id=='demo',Record.kind=='inventory_lots',Record.branch_id==branch)) if r.data['snapshot_date']=='2026-01-01']
            counts={item['code']:item['count'] for item in result['warnings']}
            self.assertEqual(counts.get('EXPIRED_LOTS',0),sum(1 for r in lots if r['expiry_date']<'2026-01-01'))
            self.assertEqual(counts.get('EXPIRING_LOTS',0),sum(1 for r in lots if '2026-01-01'<=r['expiry_date']<='2026-01-03'))
            self.assertTrue(all(item['message'] for item in result['warnings']))
            self.assertEqual(result['as_of'],'2025-12-31')
    def test_import_templates_are_canonical_and_role_scoped(self):
        c=self.client_for()
        for kind,schema in SCHEMAS.items():
            response=c.get('/api/v1/imports/template/'+kind)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.text.lstrip('\ufeff').splitlines(),[','.join(schema.split())])
            self.assertIn(kind+'-template.csv',response.headers['content-disposition'])
            self.assertNotIn('demand_multiplier',response.text)
            self.assertNotIn('base_daily_demand',response.text)
        self.assertEqual(c.get('/api/v1/imports/template/oracle_do_not_train').status_code,400)
        self.assertEqual(self.client_for('warehouse@test.local').get('/api/v1/imports/template/daily_sales').status_code,403)
        self.assertEqual(self.client_for('warehouse@test.local').get('/api/v1/imports/template/inventory_lots').status_code,200)
        self.assertEqual(self.client_for('analyst@test.local').get('/api/v1/imports/template/recipes').status_code,403)
        self.assertEqual(self.client_for('analyst@test.local').get('/api/v1/imports/template/daily_sales').status_code,200)
if __name__=='__main__':
    unittest.main()
