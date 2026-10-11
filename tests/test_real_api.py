"""REAL-contract HTTP paths using generated TEST fixtures, never enterprise data."""
from copy import deepcopy
import csv
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.data_policy import DataPolicyError, execution_context
from apps.api.db import Audit, Forecast, ImportReceipt, Job, Organization, OrganizationSource, Plan, Record, RecordRevision, User
from apps.api.importing import insert_rows
from apps.api.main import create_app
from apps.api.tenants import bootstrap_tenant, configure_real_source
from apps.worker.main import run_once
from database_fixture import isolated_database_url
from scripts.pilot_fixture import BRANCH, SOURCE, csv_text, dataset


class RealApiTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false', 'ALLOWED_ORIGINS': 'http://localhost:3000'})
        env.start(); self.addCleanup(env.stop)
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='real-api-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(isolated_database_url('sqlite:///' + (Path(self.temp.name).resolve()/'db.sqlite').as_posix()))
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        self.password = 'Artificial-fixture-password-1!'
        with self.factory() as db:
            created = bootstrap_tenant(db, organization_id='fixture', name='ARTIFICIAL ONLY', timezone='Asia/Almaty',
                data_policy='unconfigured', email='contract@fixture.invalid', password=self.password,
                operator_id='test_operator', reason='Generated contract fixture, not a business')
            self.user_id = created['admin_user_id']
            configure_real_source(db, organization_id='fixture', **SOURCE, branch_id=BRANCH,
                authorization_reference='generated-test-fixture-only', purpose='test_fixture',
                operator_id='test_operator', reason='Exercise schema only, no enterprise authorization claimed')
            db.commit()
        self.client = TestClient(self.app); self.addCleanup(self.client.close)
        response = self.client.post('/api/v1/session/login', headers={'Origin':'http://localhost:3000'},
                                    json={'email':'contract@fixture.invalid','password':self.password})
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers.update({'Origin':'http://localhost:3000','X-CSRF-Token':response.json()['csrf_token']})
        self.rows = dataset()

    def preview(self, kind, rows, **extra):
        return self.client.post('/api/v1/imports/preview', json=dict(kind=kind,csv_text=csv_text(kind,rows),source=SOURCE,**extra))

    def upload_all(self):
        for kind, rows in self.rows.items():
            preview = self.preview(kind,rows)
            self.assertEqual(preview.status_code,200,preview.text)
            self.assertTrue(preview.json()['valid'],preview.text)
            committed = self.client.post('/api/v1/imports/'+preview.json()['id']+'/commit')
            self.assertEqual(committed.status_code,200,committed.text)
            self.assertEqual(committed.json()['data_origin'],'REAL')
            self.assertEqual(committed.json()['usage_mode'],'TEST')
            self.assertIsNone(committed.json()['scenario_date'])

    def calculate_forecast(self):
        response = self.client.post('/api/v1/forecasts', json={'branch_id': BRANCH, 'origin': '2026-03-31'})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(run_once(self.factory))
        result = self.client.get('/api/v1/forecasts/' + response.json()['run_id'])
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def calculate_plan(self, forecast):
        response = self.client.post('/api/v1/procurement', json={'branch_id': BRANCH, 'forecast_id': forecast['id'], 'budget': '15000'})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(run_once(self.factory))
        result = self.client.get('/api/v1/plans/' + response.json()['run_id'])
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def approve(self, plan, key):
        return self.client.post('/api/v1/plans/' + plan['id'] + '/approve', headers={'Idempotency-Key': key},
            json={'expected_version': 1, 'reason': 'Reviewed artificial fixture only', 'acknowledge_shortage': True})

    def test_real_csv_to_actual_forecast_procurement_approval_export(self):
        self.upload_all()
        settings=self.client.get('/api/v1/settings',params={'branch_id':BRANCH}).json()['data_context']
        self.assertEqual((settings['mode'],settings['forecast_origin'],settings['target_date']),('real_business','2026-03-31','2026-04-01'))
        self.assertEqual(settings['usage_mode'],'TEST')
        queued=self.client.post('/api/v1/forecasts',json={'branch_id':BRANCH,'origin':'2026-03-31'})
        self.assertEqual(queued.status_code,202,queued.text)
        self.assertTrue(run_once(self.factory))
        forecast=self.client.get('/api/v1/forecasts/'+queued.json()['run_id'])
        self.assertEqual(forecast.status_code,200,forecast.text)
        self.assertEqual(forecast.json()['data_origin'],'REAL')
        self.assertEqual(forecast.json()['execution_context']['usage_mode'],'TEST')
        procurement=self.client.post('/api/v1/procurement',json={'branch_id':BRANCH,'forecast_id':forecast.json()['id'],'budget':'15000'})
        self.assertEqual(procurement.status_code,202,procurement.text)
        self.assertTrue(run_once(self.factory))
        plan=self.client.get('/api/v1/plans/'+procurement.json()['run_id']).json()
        self.assertTrue(plan['constraints_valid']); self.assertEqual(plan['input_freshness'],'unchanged')
        decision=self.client.post('/api/v1/plans/'+plan['id']+'/approve',headers={'Idempotency-Key':'fixture-approval'},
            json={'expected_version':plan['version'],'reason':'Reviewed artificial fixture only','acknowledge_shortage':True})
        self.assertEqual(decision.status_code,200,decision.text)
        exported=self.client.get('/api/v1/plans/'+plan['id']+'/export').text
        self.assertIn('REAL',exported); self.assertIn('TEST',exported); self.assertIn('2026-04-01',exported)
        self.assertNotIn('SYNTHETIC',exported); self.assertNotIn('2026-01-01',exported)
        for path in ('/sales','/forecasts','/plans','/reports','/dashboard','/audit'):
            response=self.client.get('/api/v1'+path,params={'branch_id':BRANCH})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['data_origin'],'REAL')

    def test_import_origin_source_branch_date_and_generator_guards_are_atomic(self):
        bad=dict(self.rows['branches'][0],data_origin='SYNTHETIC')
        response=self.preview('branches',[bad]);self.assertFalse(response.json()['valid'])
        self.assertEqual(self.client.post('/api/v1/imports/'+response.json()['id']+'/commit').status_code,422)
        bad=dict(self.rows['branches'][0],branch_id='other-branch')
        self.assertFalse(self.preview('branches',[bad]).json()['valid'])
        response=self.client.post('/api/v1/imports/preview',json={'kind':'branches','csv_text':csv_text('branches',self.rows['branches'])})
        self.assertEqual(response.status_code,422)
        text=csv_text('branches',self.rows['branches']).replace('data_origin','data_origin,demand_multiplier').replace('REAL\n','REAL,1.5\n')
        response=self.client.post('/api/v1/imports/preview',json={'kind':'branches','csv_text':text,'source':SOURCE})
        self.assertFalse(response.json()['valid'])
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Record)),0)
            self.assertEqual(db.scalar(select(func.count()).select_from(ImportReceipt)),0)

    def test_explicit_completed_day_and_history_are_required_before_queue(self):
        self.upload_all()
        for origin,code in [(None,'ORIGIN_REQUIRED'),('9999-12-30','ORIGIN_NOT_CLOSED'),('2026-03-30','DATA_HISTORY_INCOMPLETE')]:
            payload={'branch_id':BRANCH}
            if origin: payload['origin']=origin
            response=self.client.post('/api/v1/forecasts',json=payload)
            self.assertEqual(response.status_code,422,response.text)
            self.assertEqual(response.json()['detail']['code'],code)
            if code=='DATA_HISTORY_INCOMPLETE':
                # The refusal names the meal and why: 83 of 84 days, no invented zeros.
                coverage=response.json()['detail']['coverage']
                self.assertEqual((coverage['origin'],coverage['required_days'],coverage['ready_meals']),('2026-03-30',84,0))
                self.assertEqual(coverage['meals'],[{'meal_id':'test-meal','meal_name':'Artificial fixture meal','status':'too_short',
                    'first_date':'2026-01-07','last_date':'2026-03-30','observed_days':83,'missing_days':0,
                    'first_missing_date':None,'continuous_days_through_origin':83}])
        today=self.client.get('/api/v1/settings').json()['data_context']['business_date']
        row=dict(self.rows['daily_sales'][-1],date=today)
        preview=self.preview('daily_sales',[row]).json()
        self.assertFalse(preview['valid']);self.assertTrue(any(e['code']=='BUSINESS_DATE_NOT_CLOSED' for e in preview['errors']))
        with self.factory() as db: self.assertEqual(db.scalar(select(func.count()).select_from(Job)),0)

    def test_real_native_operational_requests_fail_explicitly(self):
        token=self.client.post('/api/v1/auth/token',json={'email':'contract@fixture.invalid','password':self.password}).json()['access_token']
        response=self.client.get('/api/v1/branches',headers={'Authorization':'Bearer '+token})
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.json()['detail']['code'],'NATIVE_REAL_UNSUPPORTED')
        self.assertEqual(self.client.get('/api/v1/settings',headers={'Authorization':'Bearer '+token}).status_code,200)

    def test_context_uses_business_timezone_and_does_not_relabel_demo(self):
        with self.factory() as db:
            instant=datetime(2026,4,1,20,30,tzinfo=timezone.utc)
            context=execution_context(db,'fixture',BRANCH,'2026-04-01',instant=instant)
            self.assertEqual(context['as_of_date'],'2026-04-02')
            self.assertEqual(context['data_origin'],'REAL')
            self.assertFalse(context['historical'])
            with self.assertRaises(DataPolicyError): execution_context(db,'fixture',BRANCH,'2026-04-02',instant=instant)

    def test_source_and_metadata_change_after_preview_do_not_commit_any_rows(self):
        mutations = [(OrganizationSource, 'source_id', 'changed-source', 409, 'SOURCE_CONTEXT_CHANGED'),
            (OrganizationSource, 'mapping_version', 'changed-mapping', 409, 'SOURCE_CONTEXT_CHANGED'),
            (OrganizationSource, 'purpose', 'pilot', 409, 'SOURCE_CONTEXT_CHANGED'),
            (Organization, 'timezone', 'Asia/Qyzylorda', 409, 'SOURCE_CONTEXT_CHANGED'),
            (Organization, 'currency', 'USD', 403, 'REAL_SOURCE_REQUIRED')]
        for model, field, value, status, code in mutations:
            with self.subTest(field=field):
                preview = self.preview('branches', self.rows['branches'])
                self.assertEqual(preview.status_code, 200, preview.text)
                self.assertTrue(preview.json()['valid'], preview.text)
                with self.factory() as db:
                    row = db.get(model, 'fixture')
                    original = getattr(row, field)
                    setattr(row, field, value)
                    db.commit()
                response = self.client.post('/api/v1/imports/' + preview.json()['id'] + '/commit')
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.json()['detail']['code'], code)
                with self.factory() as db:
                    self.assertEqual(db.scalar(select(func.count()).select_from(Record)), 0)
                    self.assertEqual(db.scalar(select(func.count()).select_from(RecordRevision)), 0)
                    self.assertEqual(db.scalar(select(func.count()).select_from(ImportReceipt)), 0)
                    setattr(db.get(model, 'fixture'), field, original)
                    db.commit()

    def test_source_change_rejects_new_approval_but_approved_history_and_exact_replay_stay_immutable(self):
        self.upload_all()
        forecast = self.calculate_forecast()
        approved_plan = self.calculate_plan(forecast)
        ready_plan = self.calculate_plan(forecast)
        receipt = self.approve(approved_plan, 'immutable-real-receipt')
        self.assertEqual(receipt.status_code, 200, receipt.text)
        export_before = self.client.get('/api/v1/plans/' + approved_plan['id'] + '/export').content
        with self.factory() as db:
            before = deepcopy(db.get(Plan, approved_plan['id']).result)
            db.get(OrganizationSource, 'fixture').purpose = 'pilot'
            db.commit()
        rejected = self.approve(ready_plan, 'new-real-approval')
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()['detail']['code'], 'SOURCE_CONTEXT_CHANGED')
        replay = self.approve(approved_plan, 'immutable-real-receipt')
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.content, receipt.content)
        self.assertEqual(self.client.get('/api/v1/plans/' + approved_plan['id'] + '/export').content, export_before)
        saved = self.client.get('/api/v1/plans/' + approved_plan['id']).json()
        self.assertEqual(saved['data_origin'], 'REAL')
        self.assertEqual(saved['usage_mode'], 'TEST')
        self.assertEqual(saved['execution_context']['source']['purpose'], 'test_fixture')
        for row in csv.DictReader(io.StringIO(export_before.decode('utf-8-sig'))):
            self.assertEqual((row['data_origin'], row['usage_mode'], row['target_date']), ('REAL', 'TEST', '2026-04-01'))
        with self.factory() as db:
            self.assertEqual(db.get(Plan, approved_plan['id']).result, before)
            self.assertEqual(db.get(Plan, ready_plan['id']).status, 'ready')
            self.assertEqual(db.get(Plan, ready_plan['id']).version, 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action == 'plan.approved')), 1)

    def test_corrections_cannot_relabel_stored_synthetic_data_or_use_changed_reference_origin(self):
        self.upload_all()
        update = dict(self.rows['daily_sales'][-1], units_sold=self.rows['daily_sales'][-1]['units_sold'] + 1)
        with self.factory() as db:
            sale = db.scalar(select(Record).where(Record.kind == 'daily_sales', Record.data['date'].as_string() == update['date']))
            sale_id, original = sale.id, deepcopy(sale.data)
            sale.data = dict(original, data_origin='SYNTHETIC')
            revisions = db.scalar(select(func.count()).select_from(RecordRevision))
            receipts = db.scalar(select(func.count()).select_from(ImportReceipt))
            db.commit()
        rejected = self.preview('daily_sales', [update], mode='correction', reason='Fixture correction review')
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()['detail']['code'], 'DATA_ORIGIN_MISMATCH')
        with self.factory() as db:
            self.assertEqual(db.get(Record, sale_id).data['data_origin'], 'SYNTHETIC')
            db.get(Record, sale_id).data = original
            db.commit()
        preview = self.preview('daily_sales', [update], mode='correction', reason='Fixture correction review')
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()['valid'], preview.text)
        with self.factory() as db:
            meal = db.scalar(select(Record).where(Record.kind == 'meals'))
            meal.data = dict(meal.data, data_origin='SYNTHETIC')
            db.commit()
        rejected = self.client.post('/api/v1/imports/' + preview.json()['id'] + '/commit')
        self.assertEqual(rejected.status_code, 409, rejected.text)
        self.assertEqual(rejected.json()['detail']['code'], 'DATA_ORIGIN_MISMATCH')
        with self.factory() as db:
            self.assertEqual(db.get(Record, sale_id).data, original)
            self.assertEqual(db.scalar(select(func.count()).select_from(RecordRevision)), revisions)
            self.assertEqual(db.scalar(select(func.count()).select_from(ImportReceipt)), receipts)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit).where(Audit.action == 'import.corrected')), 0)

    def test_real_operational_export_retains_test_marker_and_source_report_columns(self):
        self.upload_all()
        for kind in ('sales', 'inventory', 'ingredients'):
            with self.subTest(kind=kind):
                response = self.client.get('/api/v1/exports/' + kind, params={'branch_id': BRANCH})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn('filename="TEST-', response.headers['content-disposition'])
                rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(row['data_origin'], 'REAL')
                    self.assertEqual(row['usage_mode'], 'TEST')
                    self.assertEqual(row['source_id'], SOURCE['source_id'])
                    self.assertEqual(row['mapping_version'], SOURCE['mapping_version'])
                    self.assertEqual(row['source_version'], '1')
                self.assertNotIn('generated-test-fixture-only', response.text)

    def test_missing_required_stock_is_rejected_before_queue_but_explicit_zero_is_accepted(self):
        self.upload_all()
        forecast = self.calculate_forecast()
        added = dict(self.rows['ingredients'][0], ingredient_id='required-extra')
        recipe = dict(self.rows['recipes'][0], ingredient_id='required-extra')
        for kind, rows in (('ingredients', [added]), ('recipes', [recipe])):
            preview = self.preview(kind, rows)
            self.assertTrue(preview.json()['valid'], preview.text)
            commit = self.client.post('/api/v1/imports/' + preview.json()['id'] + '/commit')
            self.assertEqual(commit.status_code, 200, commit.text)
        payload = {'branch_id': BRANCH, 'forecast_id': forecast['id'], 'budget': '15000'}
        response = self.client.post('/api/v1/procurement', json=payload)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()['detail']['code'], 'INVENTORY_COVERAGE_REQUIRED')
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)), 1)
        zero = dict(self.rows['inventory_lots'][0], ingredient_id='required-extra', lot_id='known-zero', on_hand_qty='0')
        preview = self.preview('inventory_lots', [zero])
        self.assertTrue(preview.json()['valid'], preview.text)
        commit = self.client.post('/api/v1/imports/' + preview.json()['id'] + '/commit')
        self.assertEqual(commit.status_code, 200, commit.text)
        plan = self.calculate_plan(forecast)
        self.assertTrue(plan['constraints_valid'])
        missing_offer = next(row for row in plan['requirements'] if row['ingredient_id'] == 'required-extra')
        self.assertEqual(missing_offer['usable_stock'], '0')
        self.assertGreater(float(missing_offer['shortage_qty']), 0)

    def test_scoped_settings_reject_another_branch_without_revealing_its_dates(self):
        self.upload_all()
        response = self.client.get('/api/v1/settings', params={'branch_id': 'unauthorized-branch'})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['code'], 'BRANCH_FORBIDDEN')
        self.assertNotIn('data_context', response.json())
        # Even an out-of-band branch grant cannot bypass the configured single-source branch.
        with self.factory() as db:
            user = db.get(User, self.user_id)
            user.branch_ids = [BRANCH, 'unauthorized-branch']
            insert_rows(db, 'fixture', 'branches', [dict(self.rows['branches'][0], branch_id='unauthorized-branch')])
            db.commit()
        response = self.client.get('/api/v1/settings', params={'branch_id': 'unauthorized-branch'})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()['detail']['code'], 'SOURCE_BRANCH_MISMATCH')

    def test_dashboard_date_bounds_do_not_overflow_or_invent_stock(self):
        self.upload_all()
        ordinary = self.client.get('/api/v1/dashboard', params={'branch_id': BRANCH,
            'inventory_date': '2026-04-01'})
        self.assertEqual(ordinary.status_code, 200, ordinary.text)
        self.assertTrue(ordinary.json()['inventory_known'])
        self.assertEqual(ordinary.json()['warnings'], [dict(code='EXPIRING_LOTS', count=1,
            message='1 партияның мерзімі екі күн ішінде аяқталады.')])
        for selected in ('0001-01-01', '9999-12-30', '9999-12-31'):
            with self.subTest(inventory_date=selected):
                response = self.client.get('/api/v1/dashboard', params={'branch_id': BRANCH,
                    'inventory_date': selected})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result['inventory_date'], selected)
                self.assertFalse(result['inventory_known'])
                self.assertEqual([(row['code'], row['count']) for row in result['warnings']],
                                 [('INVENTORY_UNKNOWN', None)])


if __name__=='__main__': unittest.main()
