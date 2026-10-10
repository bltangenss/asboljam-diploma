"""Stock command transactions against isolated SQLite or opt-in PostgreSQL.

All counts and stock quantities are artificial fixtures; no application DB or
enterprise source is used. Services are tested with actual caller transactions.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from apps.api import stock_service as service
from apps.api.db import (Audit, Organization, OrganizationSource, Record, StockCommandReceipt,
                         StockLedger, StockMovement, User, make_engine, migrate, sessions)
from apps.api.importing import insert_rows
from apps.api.stock import StockError
from database_fixture import isolated_database_url


BASELINE = dict(branch_id='001', ingredient_id='flour', lot_id='001', snapshot_date='2026-01-01',
                expiry_date='2026-01-05', on_hand_qty='10.000', unit='kg', data_origin='SYNTHETIC')


class StockServiceTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='stock-service-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name).resolve() / 'fixture.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.factory = sessions(self.engine)
        with self.factory() as db:
            for organization in ('A', 'B'):
                db.add(Organization(id=organization, name=None, timezone='Asia/Qyzylorda',
                    data_policy='synthetic_only', provenance='test_fixture'))
                fixture = {
                    'branches': [dict(branch_id='001', branch_name='Artificial branch')],
                    'ingredients': [dict(ingredient_id='flour', ingredient_name='Artificial flour', unit='kg',
                        yield_factor='0.8', shelf_life_days=5, storage_capacity='100', reference_cost_kzt='100'),
                        dict(ingredient_id='milk', ingredient_name='Artificial milk', unit='L', yield_factor='1',
                             shelf_life_days=5, storage_capacity='100', reference_cost_kzt='200')],
                    'meals': [dict(meal_id='meal', meal_name='Artificial meal', base_price_kzt='1000')],
                    'inventory_lots': [BASELINE],
                }
                for kind, rows in fixture.items():
                    insert_rows(db, organization, kind, [dict(row, data_origin='SYNTHETIC') for row in rows])
            insert_rows(db, 'A', 'branches', [dict(branch_id='002', branch_name='Private branch', data_origin='SYNTHETIC')])
            for identifier, organization, role in [('admin', 'A', 'admin'), ('manager', 'A', 'manager'),
                    ('warehouse', 'A', 'warehouse'), ('analyst', 'A', 'analyst'), ('foreign', 'B', 'admin')]:
                db.add(User(id=identifier, organization_id=organization, email=identifier + '@fixture.invalid',
                    password_hash='unused-synthetic-fixture-hash', role=role, branch_ids=['001'], active=True))
            db.commit()

    def call(self, name, *, actor='admin', **options):
        with self.factory() as db:
            user = db.get(User, actor)
            result = getattr(service, name)(db, user, **options)
            db.commit()
            return result

    def error(self, code, callback):
        with self.assertRaises(StockError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def counts(self):
        with self.factory() as db:
            return {model.__name__: db.scalar(select(func.count()).select_from(model))
                    for model in (StockLedger, StockMovement, StockCommandReceipt, Audit)}

    def open_options(self):
        return dict(branch_id='001', baseline_date='2026-01-01', reason='Counted artificial opening')

    def open(self, actor='admin', key='open-1'):
        options = self.open_options()
        preview = self.call('preview_open', actor=actor, **options)
        return self.call('open_ledger', actor=actor, **options, expected_fingerprint=preview['preview_fingerprint'],
                         idempotency_key=key)

    def options(self, **changes):
        return dict(branch_id='001', expected_version=1, kind='receipt', business_date='2026-01-01',
            source_reference='source-1', reason='Artificial document', lines=[dict(ingredient_id='flour', lot_id='001',
                expiry_date='2026-01-05', unit='kg', quantity='1')]) | changes

    def post(self, *, actor='admin', key='movement-1', **changes):
        options = self.options(**changes)
        preview = self.call('preview_movement', actor=actor, **options)
        return self.call('post_movement', actor=actor, **options,
            expected_fingerprint=preview['preview_fingerprint'], idempotency_key=key)

    def correct_baseline(self, amount='11'):
        with self.factory() as db:
            record = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'inventory_lots'))
            record.data = dict(record.data, on_hand_qty=amount)
            db.commit()

    def position(self, opening_date='2026-01-02', actor='admin'):
        return self.call('get_position', actor=actor, branch_id='001', opening_date=opening_date)

    def activate(self, recipe_version='v1.0', effective_date='2026-01-01', expected_version=0):
        from apps.api.stock_recipes import activate_recipe, preview_activation
        options=dict(branch_id='001',meal_id='meal',recipe_version=recipe_version,effective_date=effective_date,
            rows=[dict(ingredient_id='flour',net_qty_per_portion='0.08')],expected_version=expected_version,
            reason='Artificial recipe activation')
        with self.factory() as db:
            user=db.get(User,'admin'); preview=preview_activation(db,user,**options)
            result=activate_recipe(db,user,**options,expected_fingerprint=preview['preview_fingerprint'],
                                   idempotency_key='activate-'+str(expected_version))
            db.commit()
            return result

    def test_absent_journal_is_explicitly_unknown_and_previews_post_nothing(self):
        empty = self.position()
        self.assertIsNone(empty['ledger']); self.assertIsNone(empty['opening']['rows'])
        self.assertIsNone(empty['latest']['rows']); self.assertEqual(empty['baseline_freshness'], 'unknown')
        before = self.counts()
        preview = self.call('preview_open', **self.open_options())
        self.assertEqual(preview['baseline_rows'], [BASELINE])
        self.assertEqual(len(preview['preview_fingerprint']), 64)
        self.assertEqual(self.counts(), before)

    def test_open_replay_is_exact_and_does_not_invent_movements_or_repeat_audit(self):
        options = self.open_options()
        preview = self.call('preview_open', **options)
        command = dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='open-1')
        first = self.call('open_ledger', **command)
        before = self.counts()
        self.correct_baseline()
        self.assertEqual(self.call('open_ledger', **command), first)
        self.assertEqual(self.counts(), before)
        self.assertEqual(before, dict(StockLedger=1, StockMovement=0, StockCommandReceipt=1, Audit=1))
        self.error('IDEMPOTENCY_CONFLICT', lambda:self.call('open_ledger', **dict(command, reason='Different command')))

    def test_open_binds_preview_to_actor_and_current_snapshot(self):
        options = self.open_options()
        preview = self.call('preview_open', **options)
        command = dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='open-1')
        self.error('STOCK_PREVIEW_STALE', lambda:self.call('open_ledger', actor='manager', **command))
        self.correct_baseline()
        self.error('STOCK_PREVIEW_STALE', lambda:self.call('open_ledger', **command))
        self.assertEqual(self.counts(), dict(StockLedger=0, StockMovement=0, StockCommandReceipt=0, Audit=0))

    def test_missing_snapshot_and_wrong_demo_baseline_cannot_open(self):
        self.error('DEMO_DATE_FIXED', lambda:self.call('preview_open', **dict(self.open_options(), baseline_date='2026-01-02')))
        with self.factory() as db:
            for record in db.scalars(select(Record).where(Record.organization_id == 'A', Record.kind == 'inventory_lots')):
                db.delete(record)
            db.commit()
        self.error('STOCK_BASELINE_REQUIRED', lambda:self.call('preview_open', **self.open_options()))

    def test_receipt_waste_adjustment_and_opening_date_preserve_exact_quantities(self):
        self.open()
        self.post()
        self.post(key='waste', expected_version=2, kind='waste', source_reference='waste',
                  lines=[dict(self.options()['lines'][0], quantity='0.2')])
        self.post(key='adjustment', expected_version=3, kind='adjustment', source_reference='adjustment',
                  lines=[dict(self.options()['lines'][0], quantity='-0.3')])
        same_day = self.position('2026-01-01')
        self.assertEqual(same_day['opening']['rows'][0]['on_hand_qty'], '10')
        self.assertEqual(same_day['latest']['rows'][0]['on_hand_qty'], '10.5')
        next_day = self.position()
        self.assertEqual(next_day['opening']['rows'][0]['on_hand_qty'], '10.5')
        self.assertEqual(next_day['version'], 4)
        with self.factory() as db:
            record = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'inventory_lots'))
            self.assertEqual(record.data['on_hand_qty'], '10.000')

    def test_retry_receipt_and_source_duplicate_are_separate_guards(self):
        self.open(); options = self.options()
        preview = self.call('preview_movement', **options)
        command = dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='movement-1')
        response = self.call('post_movement', **command); before = self.counts()
        self.assertEqual(self.call('post_movement', **command), response)
        self.error('IDEMPOTENCY_CONFLICT', lambda:self.call('post_movement', **dict(command, reason='Another reason')))
        self.error('STOCK_SOURCE_DUPLICATE', lambda:self.call('preview_movement', **dict(options, expected_version=2)))
        self.assertEqual(self.counts(), before)

    def test_document_reference_whitespace_does_not_bypass_duplicate_detection(self):
        self.open(); self.post(source_reference='  invoice-001  ')
        history=self.call('list_movements',branch_id='001')
        self.assertEqual(history['items'][0]['source_reference'],'invoice-001')
        self.error('STOCK_SOURCE_DUPLICATE',lambda:self.call('preview_movement',
            **self.options(expected_version=2,source_reference='invoice-001')))

    def test_preview_and_post_reject_stale_version_and_change_of_input(self):
        self.open(); options = self.options()
        preview = self.call('preview_movement', **options)
        self.error('STOCK_PREVIEW_STALE', lambda:self.call('post_movement', **dict(options, reason='Unreviewed change'),
            expected_fingerprint=preview['preview_fingerprint'], idempotency_key='changed'))
        self.post()
        self.error('STOCK_VERSION_CONFLICT', lambda:self.call('post_movement', **options,
            expected_fingerprint=preview['preview_fingerprint'], idempotency_key='stale'))

    def test_baseline_correction_and_context_change_block_new_posting_keep_historical_reads(self):
        self.open(); self.post(); before = self.position()
        self.correct_baseline('999')
        changed = self.position()
        for key in ('rows', 'date', 'count_anchor'):
            self.assertEqual(changed['opening'][key], before['opening'][key])
        self.assertEqual(before['opening']['source_freshness'], 'unchanged')
        self.assertEqual(changed['opening']['source_freshness'], 'changed')
        self.assertEqual(changed['baseline_freshness'], 'changed')
        self.error('STOCK_BASELINE_CHANGED', lambda:self.call('preview_movement', **self.options(expected_version=2, source_reference='next')))
        with self.factory() as db:
            db.get(Organization, 'A').timezone='UTC'; db.commit()
        self.assertEqual(self.position()['context_freshness'], 'changed')
        self.error('STOCK_CONTEXT_CHANGED', lambda:self.call('preview_movement', **self.options(expected_version=2, source_reference='next')))

    def test_reversal_uses_original_entries_once_and_cannot_reverse_reversal_or_foreign_document(self):
        self.open(); first = self.post()
        reverse = dict(expected_version=2, kind='reversal', source_reference='undo-1', lines=None,
                       reverses_id=first['movement_id'])
        undone = self.post(key='undo-1', **reverse)
        self.assertEqual(self.position()['opening']['rows'][0]['on_hand_qty'], '10')
        self.error('STOCK_REVERSAL_INVALID', lambda:self.call('preview_movement', **self.options(**dict(reverse,
            expected_version=3, source_reference='undo-2'))))
        self.error('STOCK_REVERSAL_INVALID', lambda:self.call('preview_movement', **self.options(**dict(reverse,
            expected_version=3, source_reference='undo-3', reverses_id=undone['movement_id']))))
        self.error('STOCK_REVERSAL_INPUT', lambda:self.call('preview_movement', **self.options(**dict(reverse,
            expected_version=3, source_reference='forged', lines=self.options()['lines']))))
        self.error('STOCK_MOVEMENT_NOT_FOUND', lambda:self.call('preview_movement', **self.options(**dict(reverse,
            expected_version=3, source_reference='foreign', reverses_id='foreign-document'))))
        history = self.call('list_movements', branch_id='001', limit=1, cursor=1)
        self.assertEqual(history['items'][0]['reversed_by_id'], undone['movement_id'])
        self.assertEqual(history['items'][0]['entries'][0]['quantity_delta'], '1')

    def test_reversing_spent_receipt_and_backdating_fail_without_mutation(self):
        self.open(); first = self.post()
        self.post(key='use', expected_version=2, kind='waste', source_reference='use', business_date='2026-01-02',
                  lines=[dict(self.options()['lines'][0], quantity='10.5')])
        before = self.counts()
        self.error('STOCK_INSUFFICIENT', lambda:self.call('preview_movement', **self.options(expected_version=3,
            kind='reversal', business_date='2026-01-02', source_reference='undo', lines=None, reverses_id=first['movement_id'])))
        self.error('STOCK_BACKDATED', lambda:self.call('preview_movement', **self.options(expected_version=3, source_reference='late')))
        self.assertEqual(self.counts(), before)

    def test_late_invalid_line_and_audit_failure_roll_back_every_command_effect(self):
        self.open(); before = self.counts()
        self.error('STOCK_BALANCE_UNKNOWN', lambda:self.call('preview_movement', **self.options(kind='waste',
            lines=[*self.options()['lines'], dict(self.options()['lines'][0], lot_id='missing')])) )
        options = self.options(); preview = self.call('preview_movement', **options)
        with patch.object(service, '_save', side_effect=RuntimeError('controlled audit failure')):
            with self.assertRaises(RuntimeError):
                self.call('post_movement', **options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='atomic')
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.position()['version'], 1)

    def test_current_scope_role_revocation_and_organization_are_rechecked(self):
        self.error('ROLE_FORBIDDEN', lambda:self.call('preview_open', actor='analyst', **self.open_options()))
        self.error('BRANCH_FORBIDDEN', lambda:self.call('preview_open', **dict(self.open_options(), branch_id='002')))
        self.open(actor='warehouse')
        self.error('ROLE_FORBIDDEN', lambda:self.call('preview_movement', actor='warehouse', **self.options(kind='adjustment')))
        self.assertIsNone(self.position(actor='foreign')['ledger'])
        with self.factory() as db:
            stale = db.get(User, 'manager'); db.expunge(stale)
        with self.factory() as db:
            db.get(User, 'manager').active=False; db.commit()
        with self.factory() as db:
            self.error('AUTH_REQUIRED', lambda:service.preview_movement(db, stale, **self.options()))
        with self.factory() as db:
            db.get(Organization, 'A').status='suspended'; db.commit()
        self.error('AUTH_REQUIRED', lambda:self.position())

    def test_reconciliation_reports_unknown_zero_mismatch_and_matched_without_posting(self):
        self.open(); self.post()
        before = self.counts()
        missing = self.call('reconcile', branch_id='001', count_date='2026-01-02')
        self.assertEqual(missing['status'], 'unresolved')
        self.assertEqual(missing['lines'][0]['status'], 'missing_count')
        self.assertIsNone(missing['lines'][0]['difference'])
        with self.factory() as db:
            insert_rows(db, 'A', 'inventory_lots', [dict(BASELINE, snapshot_date='2026-01-02', on_hand_qty='0')]); db.commit()
        zero = self.call('reconcile', branch_id='001', count_date='2026-01-02')
        self.assertEqual(zero['lines'][0]['difference'], '-11')
        with self.factory() as db:
            row = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'inventory_lots',
                Record.data['snapshot_date'].as_string() == '2026-01-02'))
            row.data = dict(row.data, on_hand_qty='11.0'); db.commit()
        matched = self.call('reconcile', branch_id='001', count_date='2026-01-02')
        self.assertEqual(matched['status'], 'matched')
        self.assertNotEqual(matched['stock_fingerprint'], zero['stock_fingerprint'])
        self.assertEqual(self.counts(), before)

    def test_future_operations_do_not_change_earlier_reconciliation_fingerprint(self):
        self.open(); first = self.call('reconcile', branch_id='001', count_date='2026-01-01')
        self.post()
        later = self.call('reconcile', branch_id='001', count_date='2026-01-01')
        self.assertEqual(later['stock_fingerprint'], first['stock_fingerprint'])
        self.assertNotEqual(later['version'], first['version'])

    def test_real_context_is_preserved_private_attestation_hidden_and_future_stock_refused(self):
        with self.factory() as db:
            org = db.get(Organization, 'A'); org.data_policy='real_only'
            db.add(OrganizationSource(organization_id='A', source_id='test-source', mapping_version='v1',
                branch_id='001', authorization_reference='private-test-attestation', purpose='test_fixture', actor_id='admin'))
            for record in db.scalars(select(Record).where(Record.organization_id == 'A')):
                record.data = dict(record.data, data_origin='REAL')
            db.commit()
        self.open()
        position = self.position()
        self.assertEqual(position['public_context']['usage_mode'], 'TEST')
        self.assertNotIn('authorization_reference', position['public_context']['source'])
        report = self.call('reconcile', branch_id='001', count_date='2026-01-01')
        self.assertNotIn('private-test-attestation', str(report))
        future = (date.today() + timedelta(days=2)).isoformat()
        self.error('STOCK_FUTURE_DATE', lambda:self.call('preview_movement', **self.options(business_date=future)))

    def test_concurrent_same_command_replays_once(self):
        self.open(); options = self.options()
        preview = self.call('preview_movement', **options)
        command = dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='concurrent')
        barrier = threading.Barrier(2)
        def run():
            barrier.wait(timeout=10)
            return self.call('post_movement', **command)
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(run) for _ in range(2)]
            results = [task.result(timeout=30) for task in tasks]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.counts(), dict(StockLedger=1, StockMovement=1, StockCommandReceipt=2, Audit=2))

    def test_concurrent_different_consumptions_cannot_overdraw(self):
        self.open(); commands=[]
        for number in range(2):
            options=self.options(kind='waste', source_reference='concurrent-'+str(number),
                lines=[dict(self.options()['lines'][0], quantity='6')])
            preview=self.call('preview_movement', **options)
            commands.append(dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='waste-'+str(number)))
        barrier=threading.Barrier(2)
        def run(command):
            barrier.wait(timeout=10)
            try:
                return self.call('post_movement', **command)['status']
            except StockError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(run, commands))
        self.assertCountEqual(outcomes, ['posted','STOCK_VERSION_CONFLICT'])
        self.assertEqual(self.position()['opening']['rows'][0]['on_hand_qty'], '4')

    def test_recipe_usage_uses_dated_activation_and_exact_gross_lot_allocation(self):
        self.open(); self.activate()
        required=self.call('recipe_requirements_view',actor='analyst',branch_id='001',business_date='2026-01-01',portions={'meal':10})
        self.assertEqual(required['requirements'][0]['gross_required'],'1')
        self.error('STOCK_RECIPE_ALLOCATION',lambda:self.call('preview_movement',**self.options(kind='recipe_usage',
            recipe_usage={'portions':{'meal':10}},lines=[dict(self.options()['lines'][0],quantity='0.8')])))
        self.post(kind='recipe_usage',recipe_usage={'portions':{'meal':10}})
        self.assertEqual(self.position()['opening']['rows'][0]['on_hand_qty'],'9')
        history=self.call('list_movements',branch_id='001')
        evidence=history['items'][0]['recipe_evidence']
        self.assertEqual(evidence['rows'][0]['yield_factor'],'0.8')
        self.assertEqual(evidence['dated_recipes']['activations'][0]['recipe_version'],'v1.0')

    def test_recipe_activation_change_invalidates_preview_even_with_same_gross_quantities(self):
        self.open(); self.activate()
        options=self.options(kind='recipe_usage',business_date='2026-01-02',recipe_usage={'portions':{'meal':10}})
        preview=self.call('preview_movement',**options)
        self.activate(recipe_version='v2.0',effective_date='2026-01-02',expected_version=1)
        before=self.counts()
        self.error('STOCK_PREVIEW_STALE',lambda:self.call('post_movement',**options,
            expected_fingerprint=preview['preview_fingerprint'],idempotency_key='stale-recipe'))
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.position()['version'],1)


if __name__ == '__main__':
    unittest.main()
