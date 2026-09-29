"""Import API transactions, scoped history and corrections on real isolated databases.

Tiny SYNTHETIC fixtures only. Uses SQLite by default or the explicit PostgreSQL
schema fixture; no seed dataset, forecast computation or operational database.
"""
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api.db import Audit, ImportBatch, ImportReceipt, Organization, Record, RecordRevision, User
from apps.api.importing import SCHEMAS, insert_rows, natural_key
from apps.api.main import create_app
from apps.api.security import password_hash
from database_fixture import isolated_database_url


PASSWORD = 'Synthetic-import-test-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class ImportTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = password_hash(PASSWORD)

    def setUp(self):
        environment = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
                                             'ALLOWED_ORIGINS': ORIGIN['Origin']})
        environment.start()
        self.addCleanup(environment.stop)
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='import-transactions-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name).resolve() / 'test.sqlite').as_posix()))
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        self.calendar = dict(date='2025-12-30', branch_id='1', weekday=1,
                             temperature_forecast_c='0.0', synthetic_event=0, is_open=1, data_origin='SYNTHETIC')
        self.inventory = dict(branch_id='1', ingredient_id='1', lot_id='lot-1', snapshot_date='2026-01-01',
                              expiry_date='2026-01-05', on_hand_qty='10.00', unit='kg', data_origin='SYNTHETIC')
        with self.factory() as db:
            for org in ('A', 'B'):
                db.add(Organization(id=org, name=None, timezone=None, data_policy='synthetic_only', provenance='test_fixture'))
                fixture = {
                    'branches': [dict(branch_id='1', branch_name=f'{org} fixture')],
                    'meals': [dict(meal_id='1', meal_name=f'{org} meal', base_price_kzt='1200.00')],
                    'ingredients': [dict(ingredient_id='1', ingredient_name=f'{org} ingredient', unit='kg', reference_cost_kzt='100.00', shelf_life_days=5, yield_factor='0.9', storage_capacity='100')],
                    'recipes': [dict(meal_id='1', ingredient_id='1', net_qty_per_portion='0.1', recipe_version='v1')],
                    'suppliers': [dict(supplier_id='1', supplier_name=f'{org} supplier', lead_time_days=0)],
                    'supplier_offers': [dict(supplier_id='1', ingredient_id='1', pack_qty='1', unit_cost_kzt='100', min_packs=1, max_packs=100, lead_time_days=0)],
                    'daily_sales': [self.sale(date='2025-12-30', units=2)],
                    'calendar': [self.calendar],
                    'inventory_lots': [self.inventory],
                }
                for kind, rows in fixture.items():
                    insert_rows(db, org, kind, [dict(row, data_origin='SYNTHETIC') for row in rows])
            insert_rows(db, 'A', 'branches', [dict(branch_id='2', branch_name='private-branch-name', data_origin='SYNTHETIC')])
            insert_rows(db, 'A', 'daily_sales', [self.sale(branch='2', date='2025-12-30', price='54321.99')])
            for identifier, org, role, branches in (
                ('admin', 'A', 'admin', ['1', '2']), ('limited', 'A', 'admin', ['1']),
                ('manager', 'A', 'manager', ['1']), ('peer', 'A', 'manager', ['1']),
                ('warehouse', 'A', 'warehouse', ['1']), ('foreign', 'B', 'admin', ['1']),
            ):
                db.add(User(id=identifier, organization_id=org, email=f'{identifier}@fixture.invalid',
                            password_hash=self.password_hash, role=role, branch_ids=branches))
            db.commit()

    def sale(self, *, units=3, branch='1', date='2025-12-31', meal='1', price='1200.00'):
        return dict(date=date, branch_id=branch, meal_id=meal, units_sold=units, available_portions=50,
                    stockout_flag=0, is_open=1, promo=0, price_kzt=price, data_origin='SYNTHETIC')

    def csv_text(self, kind, rows):
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=SCHEMAS[kind].split(), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    def client(self, identifier='manager'):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        response = client.post('/api/v1/session/login', json={'email': f'{identifier}@fixture.invalid', 'password': PASSWORD}, headers=ORIGIN)
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': response.json()['csrf_token']})
        return client

    def preview(self, client, *, kind='daily_sales', rows=None, csv_text=None, expected=200, **options):
        response = client.post('/api/v1/imports/preview', json=dict(
            kind=kind, csv_text=csv_text if csv_text is not None else self.csv_text(kind, rows or [self.sale()]), **options))
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def commit(self, client, preview, key='request-1', expected=200):
        response = client.post('/api/v1/imports/' + preview['id'] + '/commit', headers={'Idempotency-Key': key})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def counts(self):
        with self.factory() as db:
            counts = {model.__name__: db.scalar(select(func.count()).select_from(model))
                      for model in (Record, RecordRevision, ImportReceipt)}
            counts['import_audit'] = db.scalar(select(func.count()).select_from(Audit).where(Audit.action.like('import.%')))
            return counts

    def row(self, kind, data, org='A'):
        with self.factory() as db:
            return db.scalar(select(Record).where(Record.organization_id == org, Record.kind == kind,
                                                 Record.natural_key == natural_key(kind, data))).data

    def revisions(self, kind='daily_sales'):
        with self.factory() as db:
            return list(db.scalars(select(RecordRevision).where(RecordRevision.organization_id == 'A',
                RecordRevision.kind == kind).order_by(RecordRevision.revision)))

    def test_provenance_records_received_text_and_preserves_unverified_declarations(self):
        client = self.client()
        text = self.csv_text('daily_sales', [self.sale()])
        declared = 'a' * 64
        preview = self.preview(client, csv_text=text, source={'source_id': 'offline-fixture',
            'mapping_version': 'mapping-v1', 'declared_original_sha256': declared})
        self.assertEqual(preview['received_text_sha256'], hashlib.sha256(text.encode('utf-8')).hexdigest())
        self.assertEqual(preview['source']['declared_original_sha256'], declared)
        self.assertFalse(preview['source']['original_hash_verified'])
        self.assertEqual(preview['source']['provenance'], 'received_csv_text')
        self.assertIsNone(preview['source']['timezone'])
        self.assertEqual(preview['source']['currency'], 'KZT')
        self.assertTrue(preview['scan_complete'])
        self.assertTrue(preview['validation_complete'])
        self.assertEqual(preview['validation_rows_checked'], 1)
        self.assertIsNone(preview['validation_stop_reason'])
        self.assertEqual(preview['period'], {'from': '2025-12-31', 'to': '2025-12-31'})
        self.assertEqual(client.get('/api/v1/imports/' + preview['id']).json(), preview)
        self.preview(client, source={'source_id': 'fixture', 'original_hash_verified': True}, expected=422)

    def test_canonical_hash_ignores_row_order_and_decimal_spelling_without_rewriting_storage(self):
        client = self.client()
        first_rows = [self.sale(date='2025-12-29', price='1200.00'), self.sale(price='1200.0')]
        second_rows = [self.sale(price='1200'), self.sale(date='2025-12-29', price='1200')]
        first = self.preview(client, rows=first_rows)
        second = self.preview(client, csv_text='\ufeff' + self.csv_text('daily_sales', second_rows))
        self.assertNotEqual(first['received_text_sha256'], second['received_text_sha256'])
        self.assertEqual(first['canonical_rows_sha256'], second['canonical_rows_sha256'])
        self.commit(client, first)
        self.assertEqual(self.row('daily_sales', first_rows[0])['price_kzt'], '1200.00')
        receipt = self.commit(client, second, key='second-file')
        self.assertEqual((receipt['inserted_rows'], receipt['unchanged_rows']), (0, 2))
        self.assertEqual(self.row('daily_sales', first_rows[0])['price_kzt'], '1200.00')

    def test_repeated_commit_replays_receipt_without_records_revisions_or_audit(self):
        client = self.client()
        preview = self.preview(client)
        first = self.commit(client, preview)
        committed = self.counts()
        self.assertEqual(self.commit(client, preview), first)
        self.assertEqual(self.counts(), committed)
        detail = client.get('/api/v1/imports/' + preview['id']).json()
        self.assertEqual(detail['receipt'], first)
        self.assertIsNotNone(detail['committed_at'])
        self.assertFalse(detail['can_commit'])

    def test_idempotency_key_collision_with_another_batch_fails_without_changes(self):
        client = self.client()
        first, second = self.preview(client), self.preview(client, rows=[self.sale(date='2025-12-29')])
        self.commit(client, first)
        before = self.counts()
        response = self.commit(client, second, expected=409)
        self.assertEqual(response['detail']['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.counts(), before)

    def test_same_file_reupload_is_unchanged_without_duplicate_operational_rows(self):
        client = self.client()
        first = self.preview(client)
        self.commit(client, first)
        before = self.counts()
        second = self.preview(client)
        self.assertTrue(second['valid'])
        self.assertEqual(second['counts']['unchanged'], 1)
        result = self.commit(client, second, key='reupload')
        self.assertEqual((result['inserted_rows'], result['updated_rows'], result['unchanged_rows']), (0, 0, 1))
        self.assertEqual(self.counts()['Record'], before['Record'])
        self.assertEqual(self.counts()['RecordRevision'], before['RecordRevision'])

    def test_concurrent_previews_and_commits_do_not_double_insert(self):
        clients = [self.client(), self.client()]
        barrier = threading.Barrier(2)

        def run(index):
            barrier.wait(timeout=10)
            preview = self.preview(clients[index])
            barrier.wait(timeout=10)
            return self.commit(clients[index], preview, key=f'concurrent-{index}')

        before = self.counts()
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(run, index) for index in range(2)]
            receipts = [task.result(timeout=25) for task in tasks]
        self.assertEqual(sorted(result['inserted_rows'] for result in receipts), [0, 1])
        self.assertEqual(sorted(result['unchanged_rows'] for result in receipts), [0, 1])
        self.assertEqual(self.counts()['Record'], before['Record'] + 1)
        self.assertEqual(self.counts()['RecordRevision'], before['RecordRevision'] + 1)

    def test_concurrent_replay_same_batch_and_key_returns_one_receipt(self):
        clients = [self.client(), self.client()]
        preview = self.preview(clients[0])
        barrier = threading.Barrier(2)

        def run(index):
            barrier.wait(timeout=10)
            return self.commit(clients[index], preview)

        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(run, index) for index in range(2)]
            receipts = [task.result(timeout=25) for task in tasks]
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(self.counts()['ImportReceipt'], 1)
        self.assertEqual(self.counts()['import_audit'], 1)

    def test_corrections_require_reason_and_only_allow_three_operational_types(self):
        client = self.client('admin')
        self.preview(client, mode='correction', expected=422)
        self.preview(client, mode='correction', reason='  ', expected=422)
        self.preview(client, mode='append', reason='Unexpected correction reason', expected=422)
        catalog = dict(branch_id='1', branch_name='Changed fixture', data_origin='SYNTHETIC')
        self.preview(client, kind='branches', rows=[catalog], mode='correction', reason='Fix source', expected=422)
        cases = [('daily_sales', self.sale(date='2025-12-30', units=7), 'units_sold', 2, 7),
                 ('calendar', dict(self.calendar, temperature_forecast_c='3.5'), 'temperature_forecast_c', '0.0', '3.5'),
                 ('inventory_lots', dict(self.inventory, on_hand_qty='12.50'), 'on_hand_qty', '10.00', '12.50')]
        for kind, row, field, before, after in cases:
            with self.subTest(kind=kind):
                preview = self.preview(client, kind=kind, rows=[row], mode='correction', reason='Correct synthetic source')
                self.assertTrue(preview['valid'], preview)
                self.assertEqual(preview['changes'][0]['before'][field], before)
                self.assertEqual(preview['changes'][0]['after'][field], after)
                self.assertEqual(self.commit(client, preview, key=kind)['updated_rows'], 1)
                revision, = self.revisions(kind)
                self.assertEqual((revision.revision, revision.before_data[field], revision.after_data[field]), (1, before, after))
                self.assertEqual(revision.reason, 'Correct synthetic source')

    def test_compensating_correction_keeps_original_import_and_all_revisions(self):
        client = self.client()
        original = self.preview(client)
        self.commit(client, original)
        changed = self.preview(client, rows=[self.sale(units=7)], mode='correction', reason='Correct source', corrects_batch_id=original['id'])
        self.commit(client, changed, key='change')
        undo = self.preview(client, mode='correction', reason='Compensate incorrect correction', corrects_batch_id=changed['id'])
        self.commit(client, undo, key='compensate')
        revisions = self.revisions()
        self.assertEqual([revision.revision for revision in revisions], [1, 2, 3])
        self.assertEqual([revision.after_data['units_sold'] for revision in revisions], [3, 7, 3])
        self.assertEqual([revision.batch_id for revision in revisions], [original['id'], changed['id'], undo['id']])
        self.assertEqual(self.row('daily_sales', self.sale())['units_sold'], 3)
        original_detail = client.get('/api/v1/imports/' + original['id']).json()
        self.assertEqual(original_detail['preview'][0]['units_sold'], 3)
        self.assertEqual(original_detail['receipt']['updated_rows'], 0)

    def test_stale_correction_preview_cannot_overwrite_newer_revision(self):
        client = self.client()
        stale = self.preview(client, rows=[self.sale(date='2025-12-30', units=9)], mode='correction', reason='Old review')
        fresh = self.preview(client, rows=[self.sale(date='2025-12-30', units=5)], mode='correction', reason='New review')
        self.commit(client, fresh)
        before = self.counts()
        self.assertEqual(self.commit(client, stale, key='stale', expected=409)['detail']['code'], 'STALE_IMPORT')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.row('daily_sales', self.sale(date='2025-12-30'))['units_sold'], 5)

    def test_aba_correction_rejects_old_preview_even_when_values_return(self):
        client = self.client()
        baseline = self.sale(date='2025-12-30', units=2)
        stale = self.preview(client, rows=[dict(baseline, units_sold=9)], mode='correction', reason='Before both changes')
        for index, units in enumerate((7, 2)):
            changed = self.preview(client, rows=[dict(baseline, units_sold=units)], mode='correction', reason='Controlled intervening correction')
            self.commit(client, changed, key=f'aba-{index}')
        self.assertEqual(self.row('daily_sales', baseline), baseline)
        before = self.counts()
        self.assertEqual(self.commit(client, stale, key='stale-aba', expected=409)['detail']['code'], 'STALE_IMPORT')
        self.assertEqual(self.counts(), before)

    def test_one_bad_reference_keeps_entire_batch_uncommitted(self):
        client = self.client()
        before = self.counts()
        preview = self.preview(client, rows=[self.sale(), self.sale(date='2025-12-29', meal='missing')])
        self.assertFalse(preview['valid'])
        self.assertTrue(preview['scan_complete'])
        self.assertTrue(preview['validation_complete'])
        self.assertEqual(preview['validation_rows_checked'], 2)
        self.assertIn('UNKNOWN_REFERENCE', {error['code'] for error in preview['errors']})
        self.commit(client, preview, expected=422)
        self.assertEqual(self.counts(), before)

    def test_parser_prefix_limit_is_explicit_and_cannot_commit_partial_rows(self):
        client = self.client()
        before = self.counts()
        with patch('apps.api.importing.MAX_ROWS', 1):
            preview = self.preview(client, rows=[self.sale(), self.sale(date='2025-12-29'), self.sale(date='2025-12-28')])
        self.assertFalse(preview['scan_complete'])
        self.assertEqual(preview['stop_reason'], 'row_limit')
        self.assertFalse(preview['validation_complete'])
        self.assertEqual(preview['validation_rows_checked'], 0)
        self.assertEqual(preview['validation_stop_reason'], 'parser_errors')
        self.assertEqual((preview['counts']['rows_seen'], preview['counts']['rows_checked'], preview['counts']['parsed']), (2, 1, 1))
        self.assertFalse(preview['valid'])
        self.commit(client, preview, expected=422)
        self.assertEqual(self.counts(), before)

    def test_parser_error_limit_reports_truncation(self):
        client = self.client()
        rows = [dict(self.sale(), units_sold='invalid') for _ in range(501)]
        preview = self.preview(client, rows=rows)
        self.assertFalse(preview['scan_complete'])
        self.assertEqual(preview['stop_reason'], 'error_limit')
        self.assertTrue(preview['errors_truncated'])
        self.assertEqual(preview['counts']['rows_checked'], 500)
        self.assertEqual(len(preview['errors']), 500)
        self.commit(client, preview, expected=422)

    def test_reference_error_limit_reports_unchecked_tail_and_commits_no_valid_prefix(self):
        client = self.client()
        before = self.counts()
        rows = [self.sale()] + [self.sale(meal=f'missing-{index}') for index in range(501)]
        preview = self.preview(client, rows=rows)
        self.assertEqual((preview['counts']['rows_seen'], preview['counts']['rows_checked'],
                          preview['counts']['parsed']), (502, 502, 502))
        self.assertFalse(preview['scan_complete'])
        self.assertEqual(preview['stop_reason'], 'validation_error_limit')
        self.assertFalse(preview['validation_complete'])
        self.assertEqual(preview['validation_rows_checked'], 501)
        self.assertEqual(preview['validation_stop_reason'], 'error_limit')
        self.assertTrue(preview['errors_truncated'])
        self.assertEqual(len(preview['errors']), 500)
        self.assertEqual({error['code'] for error in preview['errors']}, {'UNKNOWN_REFERENCE'})
        self.assertFalse(preview['valid'])
        self.assertFalse(preview['can_commit'])
        self.assertEqual(client.get('/api/v1/imports/' + preview['id']).json(), preview)
        self.commit(client, preview, expected=422)
        self.assertEqual(self.counts(), before)

    def test_reference_error_limit_at_exact_end_is_complete_without_truncation(self):
        client = self.client()
        preview = self.preview(client, rows=[self.sale(meal=f'missing-{index}') for index in range(500)])
        self.assertTrue(preview['scan_complete'])
        self.assertTrue(preview['validation_complete'])
        self.assertEqual(preview['validation_rows_checked'], 500)
        self.assertIsNone(preview['validation_stop_reason'])
        self.assertIsNone(preview['stop_reason'])
        self.assertFalse(preview['errors_truncated'])
        self.assertEqual(len(preview['errors']), 500)
        self.assertFalse(preview['valid'])

    def test_legacy_batch_is_visible_as_unattributed_and_requires_new_preview(self):
        with self.factory() as db:
            db.add(ImportBatch(id='legacy', organization_id='A', actor_id='manager', kind='daily_sales', rows=[self.sale()], errors=[]))
            db.commit()
        client = self.client()
        detail = client.get('/api/v1/imports/legacy').json()
        self.assertEqual(detail['source']['provenance'], 'legacy_unattributed')
        self.assertIsNone(detail['received_text_sha256'])
        self.assertIsNone(detail['canonical_rows_sha256'])
        self.assertIsNone(detail['committed_at'])
        self.assertFalse(detail['can_commit'])
        self.assertIn('legacy', {row['id'] for row in client.get('/api/v1/imports').json()['items']})
        self.assertEqual(self.commit(client, detail, expected=409)['detail']['code'], 'IMPORT_PREVIEW_REQUIRED')

    def test_history_detail_and_commit_enforce_actor_organization_and_current_role(self):
        manager = self.client()
        preview = self.preview(manager)
        path = '/api/v1/imports/' + preview['id']
        for identifier in ('peer', 'foreign'):
            client = self.client(identifier)
            self.assertEqual(client.get(path).status_code, 404)
            self.assertNotIn(preview['id'], {row['id'] for row in client.get('/api/v1/imports').json()['items']})
            self.assertEqual(client.post(path + '/commit').status_code, 404)
        admin = self.client('admin')
        self.assertEqual(admin.get(path).status_code, 200)
        self.assertEqual(admin.post(path + '/commit').status_code, 404)
        updated = admin.patch('/api/v1/users/manager', json={'role': 'analyst', 'branch_ids': ['1']})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(manager.get(path).status_code, 401)
        analyst = self.client()
        self.assertEqual(analyst.get(path).status_code, 200)
        self.assertFalse(analyst.get(path).json()['can_commit'])
        self.assertEqual(analyst.post(path + '/commit').status_code, 403)

    def test_committed_source_is_readable_by_scoped_peer_but_never_committable(self):
        manager, peer, foreign = self.client(), self.client('peer'), self.client('foreign')
        preview = self.preview(manager)
        path = '/api/v1/imports/' + preview['id']
        self.assertEqual(peer.get(path).status_code, 404)
        self.commit(manager, preview)
        detail = peer.get(path)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()['preview'][0], self.sale())
        self.assertFalse(detail.json()['can_commit'])
        self.assertIn(preview['id'], {row['id'] for row in peer.get('/api/v1/imports').json()['items']})
        self.assertEqual(peer.post(path + '/commit').status_code, 404)
        self.assertEqual(foreign.get(path).status_code, 404)
        self.assertNotIn(preview['id'], {row['id'] for row in foreign.get('/api/v1/imports').json()['items']})

    def test_committed_mixed_branch_source_is_hidden_from_partial_branch_scope(self):
        admin, peer = self.client('admin'), self.client('peer')
        preview = self.preview(admin, rows=[self.sale(), self.sale(branch='2', price='45678.99')])
        self.commit(admin, preview)
        path = '/api/v1/imports/' + preview['id']
        detail = peer.get(path)
        self.assertEqual(detail.status_code, 404)
        self.assertNotIn('45678.99', detail.text)
        history = peer.get('/api/v1/imports')
        self.assertNotIn(preview['id'], {row['id'] for row in history.json()['items']})
        self.assertNotIn('45678.99', history.text)
        self.assertEqual(peer.post(path + '/commit').status_code, 404)

    def test_revoked_branch_hides_own_history_and_prevents_commit(self):
        manager = self.client()
        preview = self.preview(manager)
        response = self.client('admin').patch('/api/v1/users/manager', json={'role': 'manager', 'branch_ids': ['2']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(manager.get('/api/v1/imports').status_code, 401)
        fresh = self.client()
        self.assertEqual(fresh.get('/api/v1/imports/' + preview['id']).status_code, 404)
        self.assertEqual(fresh.get('/api/v1/imports').json()['total'], 0)
        self.commit(fresh, preview, expected=404)

    def test_forbidden_branch_preview_never_reveals_existing_values(self):
        client = self.client()
        preview = self.preview(client, rows=[self.sale(branch='2', date='2025-12-30')], mode='correction', reason='Forbidden scope attempt')
        self.assertFalse(preview['valid'])
        self.assertIn('BRANCH_FORBIDDEN', {error['code'] for error in preview['errors']})
        self.assertIsNone(preview['changes'][0]['before'])
        self.assertNotIn('54321.99', json.dumps(preview))
        self.commit(client, preview, expected=404)

    def test_reimport_cannot_grant_an_existing_forbidden_branch_to_limited_admin(self):
        client = self.client('limited')
        row = dict(branch_id='2', branch_name='private-branch-name', data_origin='SYNTHETIC')
        preview = self.preview(client, kind='branches', rows=[row])
        self.assertFalse(preview['valid'])
        self.assertIn('BRANCH_FORBIDDEN', {error['code'] for error in preview['errors']})
        self.assertIsNone(preview['changes'][0]['before'])
        self.commit(client, preview, expected=422)
        self.assertEqual(client.get('/api/v1/session/me').json()['user']['branch_ids'], ['1'])

    def test_branch_created_by_another_admin_after_preview_does_not_grant_access(self):
        limited, full = self.client('limited'), self.client('admin')
        row = dict(branch_id='3', branch_name='New synthetic branch', data_origin='SYNTHETIC')
        earlier = self.preview(limited, kind='branches', rows=[row])
        later = self.preview(full, kind='branches', rows=[row])
        self.assertTrue(earlier['valid'])
        self.commit(full, later)
        self.assertEqual(self.commit(limited, earlier, expected=403)['detail']['code'], 'BRANCH_FORBIDDEN')
        self.assertEqual(limited.get('/api/v1/session/me').json()['user']['branch_ids'], ['1'])


if __name__ == '__main__':
    unittest.main()
