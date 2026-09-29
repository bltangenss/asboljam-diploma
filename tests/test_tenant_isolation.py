"""Commercial access regression using tiny, isolated SYNTHETIC organizations.

These tests exercise the real API and SQLite transactions, without the full demo
seed, an external business source, or expensive forecast/optimization execution.
"""
import csv
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.db import Audit, Forecast, ImportBatch, Job, Plan, Record, User
from apps.api.importing import SCHEMAS, insert_rows
from apps.api.main import create_app
from apps.api.security import password_hash
from apps.worker.main import run_once


PASSWORD = 'Synthetic-access-fixture-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class TenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_password_hash = password_hash(PASSWORD)

    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='.cache', prefix='tenant-tests-')
        self.addCleanup(self.temp.cleanup)
        url = 'sqlite:///' + (Path(self.temp.name).resolve() / 'test.sqlite').as_posix()
        self.app = create_app(url)
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        with self.factory() as db:
            for org, base in [('A', 10), ('B', 20)]:
                fixture = {
                    'branches': [dict(branch_id=b, branch_name=f'{org}-branch-{b}') for b in ('1', '2')],
                    'meals': [dict(meal_id='1', meal_name=f'{org}-meal', base_price_kzt='1200')],
                    'ingredients': [dict(ingredient_id='1', ingredient_name=f'{org}-ingredient', unit='kg', reference_cost_kzt='100', shelf_life_days=5, yield_factor='0.9', storage_capacity='100')],
                    'recipes': [dict(meal_id='1', ingredient_id='1', net_qty_per_portion='0.1', recipe_version='v1')],
                    'suppliers': [dict(supplier_id='1', supplier_name=f'{org}-supplier', lead_time_days=0)],
                    'supplier_offers': [dict(supplier_id='1', ingredient_id='1', pack_qty='1', unit_cost_kzt=str(base), min_packs=1, max_packs=100, lead_time_days=0)],
                    'calendar': [dict(date='2025-12-31', branch_id=b, weekday=2, temperature_forecast_c='0', synthetic_event=0, is_open=1) for b in ('1', '2')],
                    'daily_sales': [dict(date='2025-12-31', branch_id=b, meal_id='1', units_sold=base + int(b), available_portions=50, stockout_flag=0, is_open=1, promo=0, price_kzt='1200') for b in ('1', '2')],
                    'inventory_lots': [dict(branch_id=b, ingredient_id='1', lot_id=f'{org}-lot-{b}', snapshot_date='2026-01-01', expiry_date='2026-01-05', on_hand_qty=str(base + int(b)), unit='kg') for b in ('1', '2')],
                }
                for kind, rows in fixture.items():
                    insert_rows(db, org, kind, [dict(row, data_origin='SYNTHETIC') for row in rows])
                for branch in ('1', '2'):
                    forecast_id = f'{org}-forecast-{branch}'
                    result = {'target_date': '2026-01-01', 'predictions': [{'meal_id': '1', 'point': base + int(branch), 'p10': None, 'p50': None, 'p90': None}], 'metadata': {'fixture_organization': org}, 'metrics': []}
                    db.add(Forecast(id=forecast_id, organization_id=org, branch_id=branch, result=result))
                    db.add(Job(id=f'{org}-job-{branch}', organization_id=org, branch_id=branch, actor_id=f'{org}-admin', kind='forecast', status='succeeded', payload={}, snapshot={}, result_id=forecast_id))
                    db.add(Plan(id=f'{org}-plan-{branch}', organization_id=org, branch_id=branch, forecast_id=forecast_id, result={'target_date': '2026-01-01', 'constraints_valid': True, 'shortage_count': 0, 'total_cost': str(base), 'lines': [], 'requirements': []}))
                    db.add(Audit(id=f'{org}-audit-{branch}', organization_id=org, branch_id=branch, actor_id=f'{org}-admin', action='fixture.created', entity_id=f'{org}-plan-{branch}', details={'fixture': True}))
            insert_rows(db, 'B', 'meals', [dict(meal_id='B-private', meal_name='B-private-meal', base_price_kzt='2000', data_origin='SYNTHETIC')])
            for identifier, org, role, branches in [
                ('A-admin', 'A', 'admin', ['1', '2']),
                ('A-limited-admin', 'A', 'admin', ['1']),
                ('A-manager', 'A', 'manager', ['1']),
                ('A-peer', 'A', 'manager', ['1']),
                ('A-analyst', 'A', 'analyst', ['1']),
                ('A-warehouse', 'A', 'warehouse', ['1']),
                ('B-admin', 'B', 'admin', ['1', '2']),
            ]:
                db.add(User(id=identifier, organization_id=org, email=identifier.lower() + '@fixture.local', password_hash=self.fixture_password_hash, role=role, branch_ids=branches))
            db.commit()

    def client_for(self, identifier='A-manager'):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        response = client.post('/api/v1/session/login', json={'email': identifier.lower() + '@fixture.local', 'password': PASSWORD}, headers=ORIGIN)
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': response.json()['csrf_token']})
        return client

    def sales_csv(self, branch='1', meal='1', date='2026-01-01'):
        return ','.join(SCHEMAS['daily_sales'].split()) + f'\n{date},{branch},{meal},3,5,0,1,0,1200,SYNTHETIC\n'

    def preview(self, client, csv_text=None, kind='daily_sales'):
        response = client.post('/api/v1/imports/preview', json={'kind': kind, 'csv_text': csv_text or self.sales_csv()})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def count(self, model):
        with self.factory() as db:
            return db.scalar(select(func.count()).select_from(model))

    def test_operational_lists_and_csv_exports_are_scoped(self):
        client = self.client_for()
        expected_totals = {'branches': 1, 'meals': 1, 'ingredients': 1, 'recipes': 1, 'suppliers': 1, 'supplier_offers': 1, 'calendar': 1, 'daily_sales': 1, 'inventory_lots': 1, 'sales': 1, 'inventory': 1}
        for endpoint, expected in expected_totals.items():
            with self.subTest(endpoint=endpoint):
                response = client.get('/api/v1/' + endpoint)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['total'], expected)
                self.assertNotIn('B-', response.text)
                self.assertTrue(all(row.get('branch_id', '1') == '1' for row in response.json()['items']))
                exported = client.get('/api/v1/exports/' + endpoint)
                self.assertEqual(exported.status_code, 200, exported.text)
                rows = list(csv.DictReader(io.StringIO(exported.text.lstrip('\ufeff'))))
                self.assertEqual(len(rows), expected)
                self.assertNotIn('B-', exported.text)
                self.assertTrue(all(row.get('branch_id', '1') == '1' for row in rows))
                self.assertEqual(client.get('/api/v1/' + endpoint + '?branch_id=2').status_code, 403)
                self.assertEqual(client.get('/api/v1/exports/' + endpoint + '?branch_id=2').status_code, 403)
        self.assertEqual(client.get('/api/v1/sales').json()['items'][0]['units_sold'], 11)
        self.assertEqual(self.client_for('B-admin').get('/api/v1/sales?branch_id=1').json()['items'][0]['units_sold'], 21)

    def test_forecast_plan_run_and_download_cannot_cross_scope(self):
        client = self.client_for()
        for endpoint, kind in [('forecasts', 'forecast'), ('plans', 'plan'), ('runs', 'job')]:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(client.get(f'/api/v1/{endpoint}/A-{kind}-1').status_code, 200)
                for denied in (f'A-{kind}-2', f'B-{kind}-1', 'missing'):
                    self.assertEqual(client.get(f'/api/v1/{endpoint}/{denied}').status_code, 404)
        for endpoint in ('forecasts', 'plans'):
            listed = client.get('/api/v1/' + endpoint).json()
            self.assertEqual(listed['total'], 1)
            self.assertEqual(listed['items'][0]['branch_id'], '1')
            self.assertTrue(listed['items'][0]['id'].startswith('A-'))
            self.assertEqual(client.get('/api/v1/' + endpoint + '?branch_id=2').status_code, 403)
        self.assertEqual(client.get('/api/v1/plans/A-plan-1/export').status_code, 200)
        for plan in ('A-plan-2', 'B-plan-1'):
            self.assertEqual(client.get(f'/api/v1/plans/{plan}/export').status_code, 404)

    def test_dashboard_reports_settings_and_audit_use_current_tenant(self):
        client = self.client_for()
        dashboard = client.get('/api/v1/dashboard?branch_id=1').json()
        self.assertEqual(dashboard['sold_portions'], 11)
        self.assertEqual(dashboard['latest_forecast']['id'], 'A-forecast-1')
        self.assertEqual([r['id'] for r in dashboard['latest_plans']], ['A-plan-1'])
        self.assertEqual(client.get('/api/v1/reports?branch_id=1').json()['items'][0]['forecast_id'], 'A-forecast-1')
        self.assertEqual(client.get('/api/v1/settings').json()['organization']['id'], 'A')
        events = client.get('/api/v1/audit').json()['items']
        self.assertIn('A-audit-1', {event['id'] for event in events})
        self.assertNotIn('A-audit-2', {event['id'] for event in events})
        self.assertTrue(all(not event['id'].startswith('B-') for event in events))
        self.assertTrue(all(event['branch_id'] in (None, '1') for event in events))
        for endpoint in ('dashboard', 'reports', 'audit'):
            self.assertEqual(client.get('/api/v1/' + endpoint + '?branch_id=2').status_code, 403)

    def test_import_batch_belongs_to_tenant_and_original_actor(self):
        owner = self.client_for()
        preview = self.preview(owner)
        self.assertTrue(preview['valid'], preview)
        path = '/api/v1/imports/' + preview['id'] + '/commit'
        before = self.count(Record)
        for identifier in ('A-peer', 'A-admin', 'B-admin'):
            self.assertEqual(self.client_for(identifier).post(path).status_code, 404)
        self.assertEqual(self.count(Record), before)
        self.assertEqual(owner.post(path).status_code, 200)
        self.assertEqual(self.count(Record), before + 1)
        self.assertEqual(owner.post(path).status_code, 409)

    def test_import_branch_and_foreign_reference_fail_atomically(self):
        client = self.client_for()
        before = self.count(Record)
        for csv_text, code in [(self.sales_csv(branch='2'), 'BRANCH_FORBIDDEN'), (self.sales_csv(meal='B-private'), 'UNKNOWN_REFERENCE')]:
            with self.subTest(code=code):
                preview = self.preview(client, csv_text)
                self.assertFalse(preview['valid'])
                self.assertIn(code, {e['code'] for e in preview['errors']})
                self.assertEqual(client.post('/api/v1/imports/' + preview['id'] + '/commit').status_code, 422)
        self.assertEqual(self.count(Record), before)

    def test_same_natural_key_can_be_imported_in_independent_tenants(self):
        before = self.count(Record)
        for identifier in ('A-manager', 'B-admin'):
            client = self.client_for(identifier)
            preview = self.preview(client)
            self.assertTrue(preview['valid'], preview)
            self.assertEqual(client.post('/api/v1/imports/' + preview['id'] + '/commit').status_code, 200)
        self.assertEqual(self.count(Record), before + 2)

    def test_enqueue_snapshots_include_only_own_organization_and_branch(self):
        client = self.client_for()
        forecast = client.post('/api/v1/forecasts', json={'branch_id': '1'})
        self.assertEqual(forecast.status_code, 202, forecast.text)
        procurement = client.post('/api/v1/procurement', json={'branch_id': '1', 'forecast_id': 'A-forecast-1', 'budget': '1000'})
        self.assertEqual(procurement.status_code, 202, procurement.text)
        with self.factory() as db:
            forecast_job = db.get(Job, forecast.json()['run_id'])
            procurement_job = db.get(Job, procurement.json()['run_id'])
            for job in (forecast_job, procurement_job):
                self.assertEqual((job.organization_id, job.branch_id, job.actor_id), ('A', '1', 'A-manager'))
                self.assertNotIn('B-', json.dumps(job.snapshot))
            self.assertEqual([row['units_sold'] for row in forecast_job.snapshot['sales']], [11])
            self.assertEqual([row['meal_name'] for row in forecast_job.snapshot['meals']], ['A-meal'])
            self.assertEqual([row['lot_id'] for row in procurement_job.snapshot['inventory_lots']], ['A-lot-1'])
            self.assertEqual(procurement_job.snapshot['forecast_result']['metadata']['fixture_organization'], 'A')

    def test_enqueue_rejects_unauthorized_branch_and_forecast_references(self):
        client = self.client_for()
        before = self.count(Job)
        self.assertEqual(client.post('/api/v1/forecasts', json={'branch_id': '2'}).status_code, 403)
        for branch, forecast_id, expected in [('2', 'A-forecast-2', 403), ('1', 'A-forecast-2', 404), ('1', 'B-forecast-1', 404), ('1', 'missing', 404)]:
            response = client.post('/api/v1/procurement', json={'branch_id': branch, 'forecast_id': forecast_id, 'budget': '1000'})
            self.assertEqual(response.status_code, expected, response.text)
        admin = self.client_for('A-admin')
        mismatch = admin.post('/api/v1/procurement', json={'branch_id': '1', 'forecast_id': 'A-forecast-2', 'budget': '1000'})
        self.assertEqual(mismatch.status_code, 422)
        self.assertEqual(mismatch.json()['detail']['code'], 'BRANCH_MISMATCH')
        self.assertEqual(self.count(Job), before)

    def test_decisions_cannot_change_foreign_plans_or_replay_other_actor(self):
        client = self.client_for()
        body = {'expected_version': 1, 'reason': 'Synthetic review', 'acknowledge_shortage': True}
        headers = {'Idempotency-Key': 'tenant-decision-key'}
        for plan in ('A-plan-2', 'B-plan-1'):
            for action in ('approve', 'reject'):
                response = client.post(f'/api/v1/plans/{plan}/{action}', json=body, headers=headers)
                self.assertEqual(response.status_code, 404, response.text)
        approved = client.post('/api/v1/plans/A-plan-1/approve', json=body, headers=headers)
        self.assertEqual(approved.status_code, 200, approved.text)
        peer = self.client_for('A-peer').post('/api/v1/plans/A-plan-1/approve', json=body, headers=headers)
        self.assertEqual(peer.status_code, 409)
        with self.factory() as db:
            self.assertEqual(db.get(Plan, 'A-plan-2').status, 'ready')
            self.assertEqual(db.get(Plan, 'B-plan-1').status, 'ready')
            events = list(db.scalars(select(Audit).where(Audit.action == 'plan.approved')))
            self.assertEqual(len(events), 1)
            self.assertEqual((events[0].organization_id, events[0].branch_id, events[0].actor_id), ('A', '1', 'A-manager'))
            self.assertEqual(events[0].details['reason'], 'Synthetic review')
            self.assertEqual(events[0].details['version'], 2)

    def test_analyst_can_read_but_cannot_import_plan_or_manage_users(self):
        client = self.client_for('A-analyst')
        for path in ('sales', 'inventory', 'forecasts', 'plans', 'audit', 'plans/A-plan-1/export', 'imports/template/daily_sales', 'imports/template/calendar', 'imports/template/inventory_lots'):
            self.assertEqual(client.get('/api/v1/' + path).status_code, 200)
        before = {model: self.count(model) for model in (Record, ImportBatch, Job, User)}
        mutations = [
            ('imports/preview', {'kind': 'daily_sales', 'csv_text': self.sales_csv()}),
            ('forecasts', {'branch_id': '1'}),
            ('procurement', {'branch_id': '1', 'forecast_id': 'A-forecast-1', 'budget': '1000'}),
            ('plans/A-plan-1/approve', {'expected_version': 1, 'reason': 'Read-only user'}),
            ('plans/A-plan-1/reject', {'expected_version': 1, 'reason': 'Read-only user'}),
            ('users', {'email': 'new@fixture.local', 'password': PASSWORD, 'role': 'manager', 'branch_ids': ['1']}),
        ]
        for path, body in mutations:
            with self.subTest(path=path):
                response = client.post('/api/v1/' + path, json=body, headers={'Idempotency-Key': 'read-only-test'})
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(client.get('/api/v1/users').status_code, 403)
        self.assertEqual(client.patch('/api/v1/users/A-peer', json={'role': 'analyst', 'branch_ids': ['1']}).status_code, 403)
        for model, count in before.items():
            self.assertEqual(self.count(model), count)

    def test_role_downgrade_invalidates_sessions_and_prevents_pending_commit(self):
        manager = self.client_for()
        preview = self.preview(manager)
        before = self.count(Record)
        native = TestClient(self.app)
        self.addCleanup(native.close)
        login = native.post('/api/v1/auth/token', json={'email': 'a-manager@fixture.local', 'password': PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        tokens = login.json()
        admin = self.client_for('A-admin')
        change = admin.patch('/api/v1/users/A-manager', json={'role': 'analyst', 'branch_ids': ['1'], 'active': True})
        self.assertEqual(change.status_code, 200, change.text)
        self.assertEqual(manager.get('/api/v1/session/me').status_code, 401)
        self.assertEqual(native.get('/api/v1/branches', headers={'Authorization': 'Bearer ' + tokens['access_token']}).status_code, 401)
        self.assertEqual(native.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code, 401)
        analyst = self.client_for('A-manager')
        response = analyst.post('/api/v1/imports/' + preview['id'] + '/commit')
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.count(Record), before)
        with self.factory() as db:
            self.assertEqual(db.get(ImportBatch, preview['id']).status, 'preview')

    def test_branch_access_is_rechecked_at_import_commit(self):
        manager = self.client_for()
        preview = self.preview(manager)
        before = self.count(Record)
        response = self.client_for('A-admin').patch('/api/v1/users/A-manager', json={'role': 'manager', 'branch_ids': ['2']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(manager.get('/api/v1/session/me').status_code, 401)
        fresh = self.client_for()
        committed = fresh.post('/api/v1/imports/' + preview['id'] + '/commit')
        self.assertEqual(committed.status_code, 422, committed.text)
        self.assertEqual(self.count(Record), before)

    def test_access_change_cancels_only_pending_jobs_for_target_actor_and_tenant(self):
        manager = self.client_for()
        queued = manager.post('/api/v1/forecasts', json={'branch_id': '1'})
        running = manager.post('/api/v1/procurement', json={'branch_id': '1', 'forecast_id': 'A-forecast-1', 'budget': '1000'})
        self.assertEqual(queued.status_code, 202, queued.text)
        self.assertEqual(running.status_code, 202, running.text)
        pending_ids = {queued.json()['run_id'], running.json()['run_id']}
        peer = self.client_for('A-peer').post('/api/v1/forecasts', json={'branch_id': '1'})
        foreign = self.client_for('B-admin').post('/api/v1/forecasts', json={'branch_id': '1'})
        self.assertEqual(peer.status_code, 202, peer.text)
        self.assertEqual(foreign.status_code, 202, foreign.text)
        with self.factory() as db:
            running_job = db.get(Job, running.json()['run_id'])
            running_job.status = 'running'
            running_job.started_at = time.time()
            completed_result = dict(db.get(Forecast, 'A-forecast-1').result)
            db.add(Forecast(id='A-completed-manager-forecast', organization_id='A', branch_id='1', result=completed_result))
            db.add(Job(id='A-completed-manager-job', organization_id='A', branch_id='1', actor_id='A-manager', kind='forecast', status='succeeded', payload={}, snapshot={}, result_id='A-completed-manager-forecast'))
            db.commit()
        admin = self.client_for('A-admin')
        response = admin.patch('/api/v1/users/A-manager', json={'role': 'manager', 'branch_ids': ['1'], 'active': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(manager.get('/api/v1/session/me').status_code, 401)
        with self.factory() as db:
            self.assertFalse(db.get(User, 'A-manager').active)
            for identifier in pending_ids:
                job = db.get(Job, identifier)
                self.assertEqual(job.status, 'failed')
                self.assertTrue(job.error.startswith('JOB_ACCESS_REVOKED:'))
                self.assertIsNone(job.result_id)
                self.assertIsNotNone(job.finished_at)
                self.assertIsNone(db.get(Forecast, identifier))
                self.assertIsNone(db.get(Plan, identifier))
            for response in (peer, foreign):
                self.assertEqual(db.get(Job, response.json()['run_id']).status, 'queued')
            completed_job = db.get(Job, 'A-completed-manager-job')
            self.assertEqual(completed_job.status, 'succeeded')
            self.assertEqual(completed_job.result_id, 'A-completed-manager-forecast')
            self.assertEqual(db.get(Forecast, completed_job.result_id).result, completed_result)
            events = list(db.scalars(select(Audit).where(Audit.action == 'job.cancelled')))
            self.assertEqual({event.entity_id for event in events}, pending_ids)
            self.assertEqual(len(events), 2)
            for event in events:
                self.assertEqual((event.organization_id, event.branch_id, event.actor_id), ('A', '1', 'A-admin'))
                self.assertEqual(event.details, {'code': 'JOB_ACCESS_REVOKED'})

    def test_regrant_does_not_resurrect_cancelled_forecast_or_procurement(self):
        manager = self.client_for()
        identifiers = []
        for endpoint, payload in [('forecasts', {'branch_id': '1'}), ('procurement', {'branch_id': '1', 'forecast_id': 'A-forecast-1', 'budget': '1000'})]:
            response = manager.post('/api/v1/' + endpoint, json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            identifiers.append(response.json()['run_id'])
        admin = self.client_for('A-admin')
        for role in ('analyst', 'manager'):
            response = admin.patch('/api/v1/users/A-manager', json={'role': role, 'branch_ids': ['1'], 'active': True})
            self.assertEqual(response.status_code, 200, response.text)
        fresh_manager = self.client_for()
        self.assertEqual(fresh_manager.get('/api/v1/session/me').json()['user']['role'], 'manager')
        with patch('apps.worker.main.forecast') as forecast_engine, patch('apps.worker.main.procurement') as procurement_engine:
            self.assertFalse(run_once(self.factory))
            forecast_engine.assert_not_called()
            procurement_engine.assert_not_called()
        with self.factory() as db:
            for identifier in identifiers:
                job = db.get(Job, identifier)
                self.assertEqual(job.status, 'failed')
                self.assertTrue(job.error.startswith('JOB_ACCESS_REVOKED:'))
                self.assertIsNone(job.result_id)
                self.assertIsNone(db.get(Forecast, identifier))
                self.assertIsNone(db.get(Plan, identifier))
            cancellation_count = db.scalar(select(func.count()).select_from(Audit).where(Audit.action == 'job.cancelled'))
            self.assertEqual(cancellation_count, 2)

    def test_warehouse_can_import_only_assigned_inventory(self):
        client = self.client_for('A-warehouse')
        for endpoint in ('inventory', 'ingredients', 'branches', 'exports/inventory', 'imports/template/inventory_lots'):
            self.assertEqual(client.get('/api/v1/' + endpoint).status_code, 200)
        for endpoint in ('sales', 'recipes', 'supplier_offers', 'forecasts', 'plans', 'audit', 'users', 'exports/sales', 'plans/A-plan-1/export'):
            self.assertEqual(client.get('/api/v1/' + endpoint).status_code, 403)
        self.assertEqual(client.post('/api/v1/forecasts', json={'branch_id': '1'}).status_code, 403)
        self.assertEqual(client.post('/api/v1/procurement', json={'branch_id': '1', 'forecast_id': 'A-forecast-1', 'budget': '1000'}).status_code, 403)
        self.assertEqual(client.post('/api/v1/imports/preview', json={'kind': 'daily_sales', 'csv_text': self.sales_csv()}).status_code, 403)
        header = ','.join(SCHEMAS['inventory_lots'].split()) + '\n'
        preview = self.preview(client, header + '1,1,new-lot,2026-01-01,2026-01-05,5,kg,SYNTHETIC\n', 'inventory_lots')
        self.assertTrue(preview['valid'], preview)
        self.assertEqual(client.post('/api/v1/imports/' + preview['id'] + '/commit').status_code, 200)
        forbidden = self.preview(client, header + '2,1,new-lot,2026-01-01,2026-01-05,5,kg,SYNTHETIC\n', 'inventory_lots')
        self.assertFalse(forbidden['valid'])
        self.assertEqual(client.post('/api/v1/imports/' + forbidden['id'] + '/commit').status_code, 422)

    def test_user_administration_stays_inside_organization_and_grantable_branches(self):
        admin = self.client_for('A-admin')
        users = admin.get('/api/v1/users').json()['items']
        self.assertTrue(all(user['organization_id'] == 'A' for user in users))
        self.assertNotIn('B-admin', {user['id'] for user in users})
        self.assertTrue(all('password_hash' not in user for user in users))
        body = {'role': 'analyst', 'branch_ids': ['1']}
        self.assertEqual(admin.patch('/api/v1/users/B-admin', json=body).status_code, 404)
        manager = self.client_for()
        self.assertEqual(manager.get('/api/v1/users').status_code, 403)
        self.assertEqual(manager.patch('/api/v1/users/A-peer', json=body).status_code, 403)
        catalogue = 'meal_id,meal_name,base_price_kzt,data_origin\nnew,New,100,SYNTHETIC\n'
        self.assertEqual(manager.post('/api/v1/imports/preview', json={'kind': 'meals', 'csv_text': catalogue}).status_code, 403)
        limited = self.client_for('A-limited-admin')
        create = {'email': 'new@fixture.local', 'password': PASSWORD, 'role': 'manager', 'branch_ids': ['2']}
        self.assertEqual(limited.post('/api/v1/users', json=create).status_code, 403)
        self.assertEqual(limited.patch('/api/v1/users/A-peer', json={'role': 'manager', 'branch_ids': ['2']}).status_code, 403)
        create['branch_ids'] = ['1']
        created = limited.post('/api/v1/users', json=create)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['organization_id'], 'A')
        self.assertEqual(created.json()['branch_ids'], ['1'])


if __name__ == '__main__':
    unittest.main()
