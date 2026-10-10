"""Real HTTP transactions and procurement evidence using artificial scoped stock."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import io
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.db import Audit, Forecast, Job, Organization, Plan, Record, StockLedger, StockMovement, User
from apps.api.main import create_app
from apps.api.data_policy import execution_context
from apps.api.importing import insert_rows, rows_for
from apps.api.lineage import capture_lineage, input_freshness
from apps.api.security import password_hash
from apps.api.stock_dependencies import capture_dependencies, dependency_freshness
from apps.api.engine import procurement
from apps.worker.main import run_once
from database_fixture import isolated_database_url


PASSWORD = 'Synthetic-stock-test-742!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class StockApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stock-api-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'stock.sqlite').as_posix()))
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        with self.factory.begin() as db:
            for org in ('A', 'B'):
                db.add(Organization(id=org, name='Artificial stock fixture', timezone='Asia/Qyzylorda',
                    data_policy='synthetic_only', provenance='test_fixture'))
                for role in ('admin', 'manager', 'warehouse', 'analyst'):
                    db.add(User(id=org+role, organization_id=org, email=(org+role+'@fixture.invalid').lower(),
                        password_hash=password_hash(PASSWORD), role=role, branch_ids=['001']))
                insert_rows(db, org, 'branches', [dict(branch_id='001', branch_name='Fixture', data_origin='SYNTHETIC')])
                insert_rows(db, org, 'meals', [dict(meal_id='01', meal_name='Fixture meal', base_price_kzt='1000', data_origin='SYNTHETIC')])
                insert_rows(db, org, 'ingredients', [dict(ingredient_id='0007', ingredient_name='Fixture rice', unit='kg',
                    reference_cost_kzt='400', shelf_life_days=5, yield_factor='0.5', storage_capacity='100', data_origin='SYNTHETIC')])
                insert_rows(db, org, 'recipes', [dict(meal_id='01', ingredient_id='0007', net_qty_per_portion='0.1',
                    recipe_version='legacy', data_origin='SYNTHETIC')])
                insert_rows(db, org, 'inventory_lots', [dict(branch_id='001', snapshot_date='2026-01-01', ingredient_id='0007',
                    lot_id='lot01', on_hand_qty='10', unit='kg', expiry_date='2026-01-05', data_origin='SYNTHETIC')])
                insert_rows(db, org, 'daily_sales', [dict(branch_id='001', meal_id='01', date='2025-12-31', units_sold=4,
                    available_portions=4, stockout_flag=0, is_open=1, promo=0, price_kzt='1000', data_origin='SYNTHETIC')])
        self.clients = {}

    def client(self, actor='Amanager'):
        if actor not in self.clients:
            client = TestClient(self.app); self.addCleanup(client.close)
            result = client.post('/api/v1/session/login', json=dict(email=actor+'@fixture.invalid', password=PASSWORD), headers=ORIGIN)
            self.assertEqual(result.status_code, 200, result.text)
            client.headers.update({**ORIGIN, 'X-CSRF-Token': result.json()['csrf_token']})
            self.clients[actor] = client
        return self.clients[actor]

    def open(self):
        body = dict(branch_id='001', baseline_date='2026-01-01', reason='Explicit counted fixture opening')
        return self.post_preview('/stock/open', body, 'open-key')

    def post_preview(self, route, body, key, actor='Amanager'):
        client = self.client(actor)
        preview = client.post('/api/v1'+route+'/preview', json=body)
        self.assertEqual(preview.status_code, 200, preview.text)
        committed = client.post('/api/v1'+route, json={**body, 'expected_fingerprint': preview.json()['preview_fingerprint']},
                                headers={'Idempotency-Key': key})
        self.assertEqual(committed.status_code, 200, committed.text)
        return committed.json()

    def movement(self, **changes):
        return dict(branch_id='001', expected_version=1, kind='receipt', business_date='2026-01-01',
            source_reference='receipt-001', reason='Generated receipt', lines=[dict(ingredient_id='0007', lot_id='lot01',
                unit='kg', expiry_date='2026-01-05', quantity='2')]) | changes

    def activation(self, **changes):
        return dict(branch_id='001', meal_id='01', recipe_version='v1.0 fixture', effective_date='2026-01-01',
            expected_version=0, reason='Complete recipe explicitly activated',
            rows=[dict(ingredient_id='0007', net_qty_per_portion='0.25')]) | changes

    def forecast(self):
        with self.factory.begin() as db:
            context = execution_context(db, 'A', '001', '2025-12-31')
            collections = [dict(kind='daily_sales', branch_id='001', date_lte='2025-12-31', rows=rows_for(db, 'A', 'daily_sales', '001')),
                           dict(kind='meals', rows=rows_for(db, 'A', 'meals'))]
            result = dict(branch_id='001', origin='2025-12-31', target_date='2026-01-01', data_origin='SYNTHETIC',
                execution_context=context, predictions=[dict(meal_id='01', point_forecast=4, p10=None, p50=None, p90=None)],
                input_lineage=capture_lineage(db, 'A', collections))
            db.add(Forecast(id='forecast', organization_id='A', branch_id='001', result=result))

    def queue_plan(self):
        response = self.client().post('/api/v1/procurement', json=dict(
            branch_id='001', forecast_id='forecast', budget='0', strategy='point'))
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()['run_id']

    def compute_plan(self):
        identifier = self.queue_plan()
        self.assertTrue(run_once(self.factory))
        response = self.client().get('/api/v1/plans/' + identifier)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'ready')
        return identifier

    def approve(self, identifier, key='approval', **changes):
        return self.client().post('/api/v1/plans/' + identifier + '/approve',
            json=dict(expected_version=1, reason='Reviewed synthetic stock evidence',
                      acknowledge_shortage=False) | changes,
            headers={'Idempotency-Key': key})

    def legacy_plan_copy(self, identifier):
        # Represent a pre-journal calculation with valid canonical lineage but
        # without the dependency evidence introduced by this feature.
        legacy_id = identifier + '-legacy'
        with self.factory.begin() as db:
            current = db.get(Plan, identifier)
            result = deepcopy(current.result)
            result['input_lineage'].pop('stock_dependencies')
            result.pop('stock_evidence', None)
            result.pop('recipe_evidence', None)
            db.add(Plan(id=legacy_id, organization_id=current.organization_id,
                branch_id=current.branch_id, forecast_id=current.forecast_id,
                status='ready', version=1, result=result))
        return legacy_id

    def test_access_csrf_native_and_scope_are_enforced_before_stock(self):
        c = self.client()
        self.assertEqual(c.post('/api/v1/stock/open/preview', json=dict(branch_id='001', baseline_date='2026-01-01', reason='fixture'),
            headers={'X-CSRF-Token': 'wrong'}).status_code, 403)
        self.assertEqual(self.client('Aanalyst').post('/api/v1/stock/open/preview',
            json=dict(branch_id='001', baseline_date='2026-01-01', reason='fixture')).status_code, 403)
        self.assertEqual(c.get('/api/v1/stock/ledger?branch_id=foreign&opening_date=2026-01-01').status_code, 403)
        self.open()
        foreign = self.client('Bmanager').get('/api/v1/stock/ledger?branch_id=001&opening_date=2026-01-01').json()
        self.assertIsNone(foreign['ledger'])
        token = c.post('/api/v1/auth/token', json=dict(email='Amanager@fixture.invalid', password=PASSWORD)).json()['access_token']
        self.assertEqual(c.get('/api/v1/stock/catalog?branch_id=001', headers={'Authorization': 'Bearer '+token}).status_code, 403)
        for kind in ('adjustment', 'reversal'):
            self.assertEqual(self.client('Awarehouse').post('/api/v1/stock/movements/preview', json=self.movement(kind=kind)).status_code, 403)

    def test_open_preview_stale_guard_and_exact_receipt_replay(self):
        c = self.client(); body = dict(branch_id='001', baseline_date='2026-01-01', reason='Counted baseline')
        preview = c.post('/api/v1/stock/open/preview', json=body).json()
        with self.factory.begin() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(StockLedger)), 0)
            row = db.scalar(select(Record).where(Record.organization_id=='A', Record.kind=='inventory_lots'))
            row.data = row.data | {'on_hand_qty':'11'}
        request = body | {'expected_fingerprint': preview['preview_fingerprint']}
        self.assertEqual(c.post('/api/v1/stock/open', json=request, headers={'Idempotency-Key':'open'}).status_code, 409)
        request['expected_fingerprint'] = c.post('/api/v1/stock/open/preview', json=body).json()['preview_fingerprint']
        first = c.post('/api/v1/stock/open', json=request, headers={'Idempotency-Key':'open'})
        self.assertEqual(first.status_code, 200, first.text)
        replay = c.post('/api/v1/stock/open', json=request, headers={'Idempotency-Key':'open'})
        self.assertEqual(replay.json(), first.json())

    def test_bad_line_changes_no_balance_or_business_audit(self):
        self.open(); c=self.client()
        body=self.movement(kind='waste', lines=[dict(ingredient_id='0007',lot_id='lot01',unit='kg',expiry_date='2026-01-05',quantity='11')])
        self.assertEqual(c.post('/api/v1/stock/movements/preview',json=body).status_code,422)
        body=self.movement(); body['lines'][0]['quantity']=2.25
        self.assertEqual(c.post('/api/v1/stock/movements/preview',json=body).status_code,422)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)),0)
            self.assertEqual(db.scalar(select(StockLedger.version)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='stock.movement_posted')),0)

    def test_concurrent_version_writers_and_source_duplicate_do_not_double_stock(self):
        self.open(); c=self.client(); requests=[]
        for reference in ('doc-A','doc-B'):
            body=self.movement(source_reference=reference)
            preview=c.post('/api/v1/stock/movements/preview',json=body).json()
            requests.append(body|{'expected_fingerprint':preview['preview_fingerprint']})
        # Independent clients share the same authorized session; actual DB transactions race.
        def post(body):
            with TestClient(self.app) as parallel:
                parallel.cookies.update(c.cookies); parallel.headers.update(c.headers)
                return parallel.post('/api/v1/stock/movements',json=body,headers={'Idempotency-Key':body['source_reference']})
        with ThreadPoolExecutor(max_workers=2) as pool: responses=list(pool.map(post,requests))
        self.assertEqual(sorted(r.status_code for r in responses),[200,409])
        winner=next(body for body,response in zip(requests,responses) if response.status_code==200)
        retry=c.post('/api/v1/stock/movements',json=winner,headers={'Idempotency-Key':winner['source_reference']})
        self.assertEqual(retry.status_code,200,retry.text)
        duplicate={key:value for key,value in winner.items() if key!='expected_fingerprint'};duplicate['expected_version']=2
        self.assertEqual(c.post('/api/v1/stock/movements/preview',json=duplicate).status_code,409)
        view=c.get('/api/v1/stock/ledger?branch_id=001&opening_date=2026-01-02').json()
        self.assertEqual(view['opening']['rows'][0]['on_hand_qty'],'12')

    def test_recipe_consumption_reversal_and_exact_date_reconciliation(self):
        self.open(); self.post_preview('/stock/recipes',self.activation(),'recipe-key'); c=self.client()
        gross=c.post('/api/v1/stock/recipe-requirements',json=dict(branch_id='001',business_date='2026-01-01',portions={'01':4})).json()
        self.assertEqual(gross['requirements'][0]['gross_required'],'2')
        posted=self.post_preview('/stock/movements',self.movement(kind='recipe_usage',recipe_usage={'portions':{'01':4}}),'consume-key')
        today=c.get('/api/v1/stock/reconciliation?branch_id=001&count_date=2026-01-01').json()
        self.assertEqual(today['status'],'matched')
        missing=c.get('/api/v1/stock/reconciliation?branch_id=001&count_date=2026-01-02').json()
        self.assertEqual(missing['status'],'unresolved'); self.assertNotIn('stock_evidence',missing)
        corrected=self.movement(kind='reversal',expected_version=2,source_reference='reverse-001',lines=None,reverses_id=posted['movement_id'])
        self.post_preview('/stock/movements',corrected,'reverse-key')
        with self.factory.begin() as db:
            row=rows_for(db,'A','inventory_lots','001')[0]
            insert_rows(db,'A','inventory_lots',[row|{'snapshot_date':'2026-01-02'}])
        check=c.get('/api/v1/stock/reconciliation?branch_id=001&count_date=2026-01-02').json()
        self.assertEqual(check['status'],'matched')

    def test_procurement_uses_active_recipe_and_captures_reconciled_stock(self):
        self.open(); self.post_preview('/stock/recipes',self.activation(),'recipe-key');self.forecast();c=self.client()
        response=c.post('/api/v1/procurement',json=dict(branch_id='001',forecast_id='forecast',budget='0',strategy='point'))
        self.assertEqual(response.status_code,202,response.text)
        run_id=response.json()['run_id']; self.assertTrue(run_once(self.factory))
        plan=c.get('/api/v1/plans/'+run_id).json()
        self.assertEqual(plan['stock_evidence']['source'],'reconciled_counted_snapshot')
        self.assertEqual(plan['recipe_evidence']['source'],'dated_activations')
        self.assertEqual(plan['requirements'][0]['gross_required'],'2')
        self.assertEqual(plan['input_freshness'],'unchanged')
        with self.factory() as db:
            saved=deepcopy(db.get(Plan,run_id).result)
        # Later dated activation leaves this prior target unchanged.
        self.post_preview('/stock/recipes',self.activation(recipe_version='v2',effective_date='2026-01-02',expected_version=1),'recipe-next')
        self.assertEqual(c.get('/api/v1/plans/'+run_id).json()['input_freshness'],'unchanged')
        with self.factory() as db:self.assertEqual(db.get(Plan,run_id).result,saved)

    def test_dependency_detects_new_recipe_but_ignores_future_movements(self):
        self.open()
        with self.factory() as db:
            before=capture_dependencies(db,'A','001','2026-01-01',['01'])
            next_day_before=capture_dependencies(db,'A','001','2026-01-02',['01'])
        self.post_preview('/stock/movements',self.movement(),'receipt')
        with self.factory() as db:
            self.assertEqual(dependency_freshness(db,'A',before),'unchanged')
            self.assertEqual(dependency_freshness(db,'A',next_day_before),'changed')
            next_day_after=capture_dependencies(db,'A','001','2026-01-02',['01'])
        self.post_preview('/stock/movements',self.movement(expected_version=2,
            business_date='2026-01-02',source_reference='future-receipt'),'future-receipt')
        with self.factory() as db:
            self.assertEqual(dependency_freshness(db,'A',before),'unchanged')
            self.assertEqual(dependency_freshness(db,'A',next_day_after),'unchanged')
        self.post_preview('/stock/recipes',self.activation(),'recipe-key')
        with self.factory() as db:self.assertEqual(dependency_freshness(db,'A',before),'changed')

    def test_new_ledger_blocks_ready_new_and_legacy_plan_approval(self):
        self.forecast(); current=self.compute_plan(); legacy=self.legacy_plan_copy(current); c=self.client()
        frozen={}
        for identifier in (current,legacy):
            self.assertEqual(c.get('/api/v1/plans/'+identifier).json()['input_freshness'],'unchanged')
            with self.factory() as db:frozen[identifier]=deepcopy(db.get(Plan,identifier).result)
        self.open()
        for identifier in (current,legacy):
            with self.subTest(plan=identifier):
                plan=c.get('/api/v1/plans/'+identifier).json()
                self.assertEqual((plan['status'],plan['version'],plan['input_freshness']),('ready',1,'changed'))
                denied=self.approve(identifier,'blocked-'+identifier)
                self.assertEqual(denied.status_code,409,denied.text)
                self.assertEqual(denied.json()['detail']['code'],'INPUTS_CHANGED')
                with self.factory() as db:self.assertEqual(db.get(Plan,identifier).result,frozen[identifier])
        with self.factory() as db:
            self.assertEqual(input_freshness(db,'A',db.get(Forecast,'forecast').result['input_lineage']),'unchanged')
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='plan.approved')),0)

    def test_activation_after_enqueue_preserves_calculation_but_blocks_approval(self):
        self.forecast(); identifier=self.queue_plan(); c=self.client()
        with self.factory() as db: queued=deepcopy(db.get(Job,identifier).snapshot)
        self.post_preview('/stock/recipes',self.activation(),'late-recipe')
        self.assertTrue(run_once(self.factory))
        legacy=self.legacy_plan_copy(identifier)
        for plan_id in (identifier,legacy):
            with self.subTest(plan=plan_id):
                plan=c.get('/api/v1/plans/'+plan_id).json()
                self.assertEqual(plan['requirements'][0]['gross_required'],'0.8')
                self.assertEqual(plan['input_freshness'],'changed')
                denied=self.approve(plan_id,'blocked-'+plan_id)
                self.assertEqual(denied.status_code,409,denied.text)
                self.assertEqual(denied.json()['detail']['code'],'INPUTS_CHANGED')
        with self.factory() as db:
            self.assertEqual(db.get(Job,identifier).snapshot,queued)
            self.assertEqual(db.get(Plan,identifier).result['recipe_evidence']['source'],'canonical_csv')
        # A newly queued calculation uses the newly activated recipe and can be approved.
        recomputed=self.compute_plan()
        self.assertEqual(c.get('/api/v1/plans/'+recomputed).json()['requirements'][0]['gross_required'],'2')
        self.assertEqual(self.approve(recomputed,'recomputed').status_code,200)

    def test_approved_export_and_exact_replay_preserve_frozen_stock_after_csv_correction(self):
        opened=self.open(); self.post_preview('/stock/recipes',self.activation(),'recipe-key'); self.forecast()
        identifier=self.compute_plan(); c=self.client()
        approved=self.approve(identifier,'frozen-approval')
        self.assertEqual(approved.status_code,200,approved.text)
        before=c.get('/api/v1/plans/'+identifier+'/export')
        self.assertEqual(before.status_code,200,before.text)
        export_rows=list(csv.DictReader(io.StringIO(before.content.decode('utf-8-sig'))))
        self.assertTrue(export_rows)
        for row in export_rows:
            self.assertEqual(row['stock_basis'],'reconciled_counted_snapshot')
            self.assertEqual(row['stock_ledger_id'],opened['ledger_id'])
            self.assertEqual(row['stock_fingerprint'],approved.json()['stock_evidence']['fingerprint'])
            self.assertEqual(row['recipe_basis'],'dated_activations')
            self.assertEqual(row['recipe_fingerprint'],approved.json()['recipe_evidence']['fingerprint'])
            self.assertEqual(row['recipe_versions'],'v1.0 fixture')
        with self.factory() as db:
            frozen=deepcopy(db.get(Plan,identifier).result)
            inventory=rows_for(db,'A','inventory_lots','001')[0] | {'on_hand_qty':'9'}
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)),0)
        stream=io.StringIO(); writer=csv.DictWriter(stream,fieldnames=list(inventory))
        writer.writeheader();writer.writerow(inventory)
        preview=c.post('/api/v1/imports/preview',json=dict(kind='inventory_lots',csv_text=stream.getvalue(),
            mode='correction',reason='Correct a synthetic count after historical approval'))
        self.assertEqual(preview.status_code,200,preview.text)
        corrected=c.post('/api/v1/imports/'+preview.json()['id']+'/commit',headers={'Idempotency-Key':'correct-count'})
        self.assertEqual(corrected.status_code,200,corrected.text)
        current=c.get('/api/v1/plans/'+identifier).json()
        self.assertEqual((current['status'],current['version'],current['input_freshness']),('approved',2,'changed'))
        self.assertEqual(self.approve(identifier,'frozen-approval').json(),approved.json())
        self.assertEqual(c.get('/api/v1/plans/'+identifier+'/export').content,before.content)
        rejected=self.approve(identifier,'frozen-approval',reason='Changed payload with reused key')
        self.assertEqual((rejected.status_code,rejected.json()['detail']['code']),(409,'IDEMPOTENCY_CONFLICT'))
        with self.factory() as db:
            self.assertEqual(db.get(Plan,identifier).result,frozen)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action=='plan.approved')),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)),0)
            self.assertEqual(db.scalar(select(StockLedger)).baseline_rows[0]['on_hand_qty'],'10')

    def test_other_branch_tenant_and_target_day_operations_leave_plan_fresh(self):
        self.open(); self.forecast(); identifier=self.compute_plan(); c=self.client()
        with self.factory.begin() as db:
            insert_rows(db,'A','branches',[dict(branch_id='002',branch_name='Other fixture',data_origin='SYNTHETIC')])
            insert_rows(db,'A','inventory_lots',[rows_for(db,'A','inventory_lots','001')[0]|{'branch_id':'002'}])
            db.get(User,'Amanager').branch_ids=['001','002']
        for actor,branch in (('Amanager','002'),('Bmanager','001')):
            self.post_preview('/stock/open',dict(branch_id=branch,baseline_date='2026-01-01',
                reason='Independent counted branch'),actor+'-open',actor)
            self.post_preview('/stock/recipes',self.activation(branch_id=branch),actor+'-recipe',actor)
        self.post_preview('/stock/movements',self.movement(),'target-day-receipt')
        self.post_preview('/stock/recipes',self.activation(effective_date='2026-01-02'),'future-recipe')
        plan=c.get('/api/v1/plans/'+identifier).json()
        self.assertEqual(plan['input_freshness'],'unchanged')
        self.assertEqual(plan['stock_evidence']['movement_count'],0)
        self.assertEqual(plan['recipe_evidence']['source'],'canonical_csv')
        self.assertEqual(plan['requirements'][0]['gross_required'],'0.8')
        self.assertEqual(self.approve(identifier,'period-scope').status_code,200)

    def test_baseline_correction_blocks_new_procurement_without_rewriting_history(self):
        self.open();self.forecast();c=self.client()
        with self.factory.begin() as db:
            row=db.scalar(select(Record).where(Record.organization_id=='A',Record.kind=='inventory_lots'))
            row.data=row.data|{'on_hand_qty':'9'}
        result=c.post('/api/v1/procurement',json=dict(branch_id='001',forecast_id='forecast',budget='0'))
        self.assertEqual(result.status_code,409,result.text)
        self.assertEqual(result.json()['detail']['code'],'STOCK_RECONCILIATION_REQUIRED')
        with self.factory() as db:self.assertEqual(db.scalar(select(StockLedger)).baseline_rows[0]['on_hand_qty'],'10')


class CapturedYieldTests(unittest.TestCase):
    def test_shared_ingredient_uses_each_activated_recipe_yield_once(self):
        forecast=dict(branch_id='001',target_date='2026-01-01',predictions=[dict(meal_id='01',point_forecast=2),dict(meal_id='02',point_forecast=4)])
        ingredients=[dict(ingredient_id='0007',unit='kg',yield_factor='0.9',storage_capacity='100')]
        recipes=[dict(meal_id=meal,ingredient_id='0007',net_qty_per_portion='0.25',captured_yield_factor=factor,
                      unit='kg',activation_id=meal) for meal,factor in [('01','0.5'),('02','0.25')]]
        inventory=[dict(branch_id='001',snapshot_date='2026-01-01',ingredient_id='0007',lot_id='lot',on_hand_qty='0',unit='kg',expiry_date='2026-01-01')]
        result=procurement(forecast,ingredients,recipes,inventory,[],[],'001','2026-01-01','0')
        row=result['requirements'][0]
        self.assertEqual((row['net_required'],row['gross_required'],row['shortage_qty']),('1.5','5','5'))
        self.assertIsNone(row['yield_factor']);self.assertEqual(row['yield_basis'],'captured_recipe_rows')
        for bad in ('0','1.1','NaN'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                procurement(forecast,ingredients,[recipes[0]|{'captured_yield_factor':bad},recipes[1]],inventory,[],[],'001','2026-01-01','0')
