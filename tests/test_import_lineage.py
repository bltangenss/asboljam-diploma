"""Calculation provenance/freshness with real stores and stubbed computations."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from database_fixture import isolated_database_url

from apps.api.db import Audit, Forecast, Job, Organization, Plan, Record, RecordRevision, User
from apps.api.importing import insert_rows, natural_key, rows_for
from apps.api.lineage import capture_lineage, input_freshness, row_digest
from apps.api.main import create_app
from apps.api.security import password_hash
from apps.worker import main as worker


PASSWORD = 'Synthetic-lineage-fixture-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class ImportLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = password_hash(PASSWORD)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
                                     'ALLOWED_ORIGINS': 'http://localhost:3000'})
        env.start()
        self.addCleanup(env.stop)
        self.url = isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'lineage.sqlite').as_posix())
        self.app = create_app(self.url)
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        with self.factory() as db:
            for org in ('A', 'B'):
                db.add(Organization(id=org, name=org, timezone='Asia/Qyzylorda', currency='KZT',
                    status='active', data_policy='synthetic_only', provenance='fixture'))
                db.add(User(id=org + '-user', organization_id=org, email=org.lower() + '@fixture.invalid',
                    role='manager', branch_ids=['1'], password_hash=self.password_hash))
                fixture = {
                    'branches': [dict(branch_id=b, branch_name=org + '-branch-' + b) for b in ('1', '2')],
                    'meals': [dict(meal_id='1', meal_name=org + '-meal', base_price_kzt='1200')],
                    'daily_sales': [dict(date='2025-12-31', branch_id='1', meal_id='1', units_sold=2,
                        available_portions=10, stockout_flag=0, is_open=1, promo=0, price_kzt='1200')],
                    'ingredients': [dict(ingredient_id='1', ingredient_name=org + '-ingredient', unit='kg',
                        reference_cost_kzt='100', shelf_life_days=5, yield_factor='0.9', storage_capacity='100')],
                    'recipes': [dict(meal_id='1', ingredient_id='1', net_qty_per_portion='0.1', recipe_version='v1')],
                    'inventory_lots': [dict(branch_id='1', ingredient_id='1', lot_id='lot', snapshot_date='2026-01-01',
                        expiry_date='2026-01-05', on_hand_qty='1', unit='kg')],
                    'suppliers': [dict(supplier_id='1', supplier_name=org + '-supplier', lead_time_days=0)],
                    'supplier_offers': [dict(supplier_id='1', ingredient_id='1', pack_qty='1', unit_cost_kzt='100',
                        min_packs=1, max_packs=100, lead_time_days=0)],
                }
                for kind, rows in fixture.items():
                    insert_rows(db, org, kind, [dict(row, data_origin='SYNTHETIC') for row in rows])
            db.commit()

    def client(self, org='A'):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        login = client.post('/api/v1/session/login', json={'email': org.lower() + '@fixture.invalid', 'password': PASSWORD}, headers=ORIGIN)
        self.assertEqual(login.status_code, 200, login.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': login.json()['csrf_token']})
        return client

    def sales_lineage(self, org='A'):
        with self.factory() as db:
            return capture_lineage(db, org, [dict(kind='daily_sales', rows=rows_for(db, org, 'daily_sales', '1'),
                                               branch_id='1', date_lte='2025-12-31')])

    def fresh(self, lineage, org='A'):
        with self.factory() as db:
            return input_freshness(db, org, lineage)

    def correct_sale(self, units_sold, org='A'):
        # Write the same revision contract as transactional corrections, independently
        # of the import API under development; no source file or real data is used.
        with self.factory() as db:
            record = db.scalar(select(Record).where(Record.organization_id == org, Record.kind == 'daily_sales', Record.branch_id == '1'))
            before = deepcopy(record.data)
            after = dict(before, units_sold=units_sold)
            previous = db.scalar(select(RecordRevision).where(RecordRevision.organization_id == org,
                RecordRevision.kind == record.kind, RecordRevision.natural_key == record.natural_key)
                .order_by(RecordRevision.revision.desc()).limit(1))
            db.add(RecordRevision(id=uuid.uuid4().hex, organization_id=org, kind=record.kind,
                natural_key=record.natural_key, branch_id='1', record_id=record.id,
                revision=previous.revision + 1 if previous else 1, before_data=before, after_data=after,
                before_sha256=row_digest(before), after_sha256=row_digest(after),
                batch_id=uuid.uuid4().hex, actor_id=org + '-user', reason='Synthetic correction fixture'))
            record.data = after
            db.commit()

    def plan(self, lineage, status='ready'):
        identifier = uuid.uuid4().hex
        result = dict(target_date='2026-01-01', constraints_valid=True, shortage_count=0,
                      total_cost='100', budget='200', requirements=[], lines=[])
        if lineage is not None:
            result['input_lineage'] = lineage
        with self.factory() as db:
            db.add(Plan(id=identifier, organization_id='A', branch_id='1', forecast_id='fixture',
                        status=status, version=2 if status == 'approved' else 1, result=result))
            db.commit()
        return identifier

    def approve(self, client, identifier, key=None):
        return client.post('/api/v1/plans/' + identifier + '/approve',
            json={'expected_version': 1, 'reason': 'Fixture input verification'},
            headers={'Idempotency-Key': key or uuid.uuid4().hex})

    def compute_forecast(self, client, side_effect=None):
        queued = client.post('/api/v1/forecasts', json={'branch_id': '1', 'origin': '2025-12-31'})
        self.assertEqual(queued.status_code, 202, queued.text)
        identifier = queued.json()['run_id']
        def calculation(sales, *args, **kwargs):
            result = {'branch_id': '1', 'target_date': '2026-01-01', 'origin': '2025-12-31',
                      'predictions': [{'meal_id': '1', 'point_forecast': sales[0]['units_sold'], 'p50': None, 'p90': None}]}
            if side_effect is not None:
                side_effect()
            return result
        with patch.object(worker, 'forecast', side_effect=calculation):
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        self.assertEqual(client.get('/api/v1/runs/' + identifier).json()['status'], 'succeeded')
        return identifier

    def compute_plan(self, client, forecast_id):
        queued = client.post('/api/v1/procurement', json={'branch_id': '1', 'forecast_id': forecast_id, 'budget': '200'})
        self.assertEqual(queued.status_code, 202, queued.text)
        identifier = queued.json()['run_id']
        result = dict(branch_id='1', target_date='2026-01-01', constraints_valid=True, shortage_count=0,
                      total_cost='100', budget='200', requirements=[], lines=[])
        with patch.object(worker, 'procurement', return_value=result):
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        self.assertEqual(client.get('/api/v1/runs/' + identifier).json()['status'], 'succeeded')
        return identifier

    def test_canonical_decimal_equality_preserves_ids_precision_and_stored_values(self):
        first = {'ingredient_id': '001', 'on_hand_qty': '1.000', 'unit_cost_kzt': '-0.00'}
        second = {'unit_cost_kzt': '0', 'on_hand_qty': '1e0', 'ingredient_id': '001'}
        self.assertEqual(row_digest(first), row_digest(second))
        self.assertEqual(first['on_hand_qty'], '1.000')
        self.assertNotEqual(row_digest(first), row_digest(dict(first, ingredient_id='1')))
        self.assertNotEqual(row_digest({'on_hand_qty': '1.12345678901234567890123456789'}),
                            row_digest({'on_hand_qty': '1.12345678901234567890123456788'}))
        self.assertEqual(row_digest({'on_hand_qty': '10e-1000001'}), row_digest({'on_hand_qty': '1e-1000000'}))

    def test_legacy_operational_rows_have_explicit_zero_revision_and_no_invented_batch(self):
        lineage = self.sales_lineage()
        self.assertEqual(self.fresh(lineage), 'unchanged')
        self.assertEqual(lineage['records'][0]['revision'], 0)
        self.assertIsNone(lineage['records'][0]['batch_id'])
        self.assertEqual(self.fresh(None), 'unknown')
        self.assertEqual(self.fresh(lineage, 'B'), 'unknown')

    def test_revision_prevents_aba_from_looking_unchanged(self):
        lineage = self.sales_lineage()
        original_hash = lineage['records'][0]['row_sha256']
        self.correct_sale(5)
        self.assertEqual(self.fresh(lineage), 'changed')
        self.correct_sale(2)
        current = self.sales_lineage()
        self.assertEqual(current['records'][0]['row_sha256'], original_hash)
        self.assertEqual(current['records'][0]['revision'], 2)
        self.assertEqual(self.fresh(lineage), 'changed')
        self.assertEqual(self.fresh(current), 'unchanged')

    def test_new_relevant_sales_change_membership_but_other_scopes_do_not(self):
        lineage = self.sales_lineage()
        with self.factory() as db:
            original = rows_for(db, 'A', 'daily_sales', '1')[0]
            insert_rows(db, 'A', 'daily_sales', [dict(original, date='2026-01-02'), dict(original, branch_id='2')])
            db.commit()
        self.correct_sale(8, 'B')
        with patch('apps.api.lineage.row_digest', wraps=row_digest) as digest:
            self.assertEqual(self.fresh(lineage), 'unchanged')
        self.assertEqual(digest.call_count, 1)
        self.assertEqual(digest.call_args.args[0]['date'], '2025-12-31')
        with self.factory() as db:
            insert_rows(db, 'A', 'daily_sales', [dict(original, date='2025-12-30')])
            db.commit()
        self.assertEqual(self.fresh(lineage), 'changed')

    def test_inventory_selector_detects_added_same_date_lot_only(self):
        with self.factory() as db:
            rows = rows_for(db, 'A', 'inventory_lots', '1')
            lineage = capture_lineage(db, 'A', [dict(kind='inventory_lots', rows=rows,
                branch_id='1', snapshot_date='2026-01-01')])
            insert_rows(db, 'A', 'inventory_lots', [dict(rows[0], snapshot_date='2026-01-02')])
            db.commit()
        self.assertEqual(self.fresh(lineage), 'unchanged')
        with self.factory() as db:
            insert_rows(db, 'A', 'inventory_lots', [dict(rows[0], lot_id='additional')])
            db.commit()
        self.assertEqual(self.fresh(lineage), 'changed')

    def test_ready_legacy_plan_needs_recomputation_but_historical_approval_stays_readable(self):
        client = self.client()
        legacy = self.plan(None)
        denied = self.approve(client, legacy)
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()['detail']['code'], 'INPUTS_UNVERIFIED')
        self.assertEqual(client.get('/api/v1/plans/' + legacy).json()['input_freshness'], 'unknown')
        approved = self.plan(None, status='approved')
        self.assertEqual(client.get('/api/v1/plans/' + approved).json()['status'], 'approved')
        self.assertEqual(client.get('/api/v1/plans/' + approved + '/export').status_code, 200)

    def test_approved_history_export_and_replay_remain_immutable_after_correction(self):
        client = self.client()
        identifier = self.plan(self.sales_lineage())
        approved = self.approve(client, identifier, 'same-approval')
        self.assertEqual(approved.status_code, 200, approved.text)
        export_before = client.get('/api/v1/plans/' + identifier + '/export').content
        with self.factory() as db:
            stored = deepcopy(db.get(Plan, identifier).result)
        self.correct_sale(5)
        current = client.get('/api/v1/plans/' + identifier).json()
        self.assertEqual(current['input_freshness'], 'changed')
        self.assertEqual(current['status'], 'approved')
        self.assertEqual(current['version'], 2)
        self.assertEqual(self.approve(client, identifier, 'same-approval').json(), approved.json())
        self.assertEqual(client.get('/api/v1/plans/' + identifier + '/export').content, export_before)
        with self.factory() as db:
            self.assertEqual(db.get(Plan, identifier).result, stored)
            self.assertEqual(len(list(db.scalars(select(Audit).where(Audit.action == 'plan.approved')))), 1)

    def test_public_lineage_is_compact_and_list_reuses_only_request_scoped_state(self):
        client = self.client()
        self.correct_sale(5)
        lineage = self.sales_lineage()
        identifier = self.plan(lineage)
        self.plan(lineage)
        detail = client.get('/api/v1/plans/' + identifier).json()
        self.assertNotIn('input_lineage', detail)
        summary = detail['input_provenance']
        self.assertEqual(summary['record_count'], 1)
        self.assertEqual(summary['legacy_record_count'], 0)
        self.assertEqual(len(summary['sha256']), 64)
        source = summary['kinds'][0]
        self.assertEqual(source['kind'], 'daily_sales')
        self.assertEqual(source['batches'], [{'batch_id': lineage['records'][0]['batch_id'],
            'record_count': 1, 'href': '/api/v1/imports/' + lineage['records'][0]['batch_id']}])
        self.assertNotIn('row_sha256', str(summary))
        with patch('apps.api.lineage.row_digest', wraps=row_digest) as digest:
            listed = client.get('/api/v1/plans').json()
        self.assertEqual(listed['total'], 2)
        self.assertEqual(len(listed['items']), 2)
        self.assertEqual(digest.call_count, 1)
        self.assertTrue(all('input_lineage' not in item for item in listed['items']))
        first_page = client.get('/api/v1/plans?limit=1').json()
        self.assertEqual(first_page['total'], 2)
        self.assertEqual(first_page['next_cursor'], '1')
        self.correct_sale(8)
        # No stale request cache may survive into a later request.
        self.assertEqual(client.get('/api/v1/plans/' + identifier).json()['input_freshness'], 'changed')
        self.assertEqual(client.get('/api/v1/plans/' + identifier).json()['input_provenance'], summary)

    def test_correction_during_compute_keeps_original_lineage_and_requires_recompute(self):
        client = self.client()
        old_forecast = self.compute_forecast(client, side_effect=lambda: self.correct_sale(5))
        old = client.get('/api/v1/forecasts/' + old_forecast).json()
        self.assertEqual(old['predictions'][0]['point_forecast'], 2)
        self.assertEqual(old['input_freshness'], 'changed')
        old_plan = self.compute_plan(client, old_forecast)
        denied = self.approve(client, old_plan)
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json()['detail']['code'], 'INPUTS_CHANGED')
        self.assertEqual(client.get('/api/v1/plans/' + old_plan).json()['input_freshness'], 'changed')
        new_forecast = self.compute_forecast(client)
        self.assertEqual(client.get('/api/v1/forecasts/' + new_forecast).json()['input_freshness'], 'unchanged')
        new_plan = self.compute_plan(client, new_forecast)
        self.assertEqual(self.approve(client, new_plan).status_code, 200)
        self.assertEqual(client.get('/api/v1/forecasts/' + old_forecast).json()['predictions'][0]['point_forecast'], 2)

    def test_foreign_lineage_is_not_verified_and_foreign_results_remain_hidden(self):
        client = self.client()
        identifier = self.plan(self.sales_lineage('B'))
        denied = self.approve(client, identifier)
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(denied.json()['detail']['code'], 'INPUTS_UNVERIFIED')
        self.assertIsNone(client.get('/api/v1/plans/' + identifier).json()['input_provenance'])
        self.assertEqual(self.client('B').get('/api/v1/plans/' + identifier).status_code, 404)
        self.assertEqual(self.client('B').get('/api/v1/plans/' + identifier + '/export').status_code, 404)

    def test_worker_rejects_explicit_cross_tenant_lineage(self):
        client = self.client()
        response = client.post('/api/v1/forecasts', json={'branch_id': '1'})
        identifier = response.json()['run_id']
        with self.factory() as db:
            job = db.get(Job, identifier)
            snapshot = deepcopy(job.snapshot)
            snapshot['input_lineage']['organization_id'] = 'B'
            job.snapshot = snapshot
            db.commit()
        with patch.object(worker, 'forecast') as calculate:
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        calculate.assert_not_called()
        with self.factory() as db:
            self.assertEqual(db.get(Job, identifier).status, 'failed')
            self.assertTrue(db.get(Job, identifier).error.startswith('JOB_SCOPE_INVALID'))
            self.assertIsNone(db.get(Forecast, identifier))


if __name__ == '__main__':
    unittest.main()
