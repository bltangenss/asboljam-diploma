"""Immutable counted-anchor recovery with real isolated service transactions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import func, select

from apps.api import stock_service as service
from apps.api.db import (Audit, Organization, OrganizationSource, Record, StockCommandReceipt,
                         StockCountAnchor, StockLedger, StockMovement, User)
from apps.api.importing import insert_rows
from apps.api.stock import StockError
import test_stock_service as fixtures


class StockAnchorTests(unittest.TestCase):
    setUp = fixtures.StockServiceTests.setUp
    call = fixtures.StockServiceTests.call
    error = fixtures.StockServiceTests.error
    open_options = fixtures.StockServiceTests.open_options
    open = fixtures.StockServiceTests.open
    options = fixtures.StockServiceTests.options
    post = fixtures.StockServiceTests.post
    position = fixtures.StockServiceTests.position
    correct_baseline = fixtures.StockServiceTests.correct_baseline

    def counts(self):
        with self.factory() as db:
            return {model.__name__: db.scalar(select(func.count()).select_from(model))
                    for model in (StockLedger, StockMovement, StockCountAnchor, StockCommandReceipt, Audit)}

    def snapshot(self, count_date='2026-01-02', amount='9', extra=()):
        rows = [dict(fixtures.BASELINE, snapshot_date=count_date, on_hand_qty=amount), *extra]
        with self.factory.begin() as db:
            insert_rows(db, 'A', 'inventory_lots', rows)
        return rows

    def anchor_options(self, **changes):
        return dict(branch_id='001', count_date='2026-01-02', expected_version=1,
                    reason='Explicit complete artificial recount') | changes

    def anchor_command(self, *, actor='admin', key='anchor-1', **changes):
        options = self.anchor_options(**changes)
        preview = self.call('preview_count_anchor', actor=actor, **options)
        return dict(**options, expected_fingerprint=preview['preview_fingerprint'],
                    acknowledge_differences=True, idempotency_key=key)

    def anchor(self, *, actor='admin', key='anchor-1', **changes):
        return self.call('post_count_anchor', actor=actor,
                         **self.anchor_command(actor=actor, key=key, **changes))

    def correct_count(self, count_date, amount):
        with self.factory.begin() as db:
            row = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'inventory_lots',
                Record.data['snapshot_date'].as_string() == count_date,
                Record.data['ingredient_id'].as_string() == 'flour'))
            row.data = dict(row.data, on_hand_qty=amount)

    def test_same_baseline_anchor_explicitly_recovers_corrected_count_without_rewriting_baseline(self):
        self.open(); self.correct_baseline('9.000000001')
        before = self.counts()
        preview = self.call('preview_count_anchor', **self.anchor_options(count_date='2026-01-01'))
        self.assertEqual(self.counts(), before)
        self.assertEqual(preview['balances_before'][0]['on_hand_qty'], '10')
        self.assertEqual(preview['counted_rows'][0]['on_hand_qty'], '9.000000001')
        self.assertEqual(preview['differences'][0]['difference'], '-0.999999999')
        result = self.anchor(count_date='2026-01-01')
        view = self.position('2026-01-01')
        self.assertEqual(view['opening']['rows'][0]['on_hand_qty'], '9.000000001')
        self.assertEqual((view['baseline_freshness'], view['effective_freshness']), ('changed', 'unchanged'))
        self.assertEqual(view['latest']['count_anchor']['id'], result['anchor_id'])
        self.assertEqual(view['opening']['source_freshness'], 'unchanged')
        with self.factory() as db:
            ledger = db.scalar(select(StockLedger))
            self.assertEqual(ledger.baseline_rows, [fixtures.BASELINE])
            self.assertEqual((ledger.baseline_date, ledger.version), ('2026-01-01', 2))
            anchor = db.scalar(select(StockCountAnchor))
            self.assertEqual((anchor.sequence, anchor.ledger_version, anchor.through_movement_sequence), (1, 2, 0))
            self.assertEqual(anchor.differences, preview['differences'])
            self.assertEqual(anchor.previous_fingerprint, preview['previous_fingerprint'])
            self.assertEqual(db.scalar(select(func.count()).select_from(StockMovement)), 0)
        self.post(expected_version=2)
        self.assertEqual(self.position()['opening']['rows'][0]['on_hand_qty'], '10.000000001')

    def test_later_anchor_preserves_prior_days_and_separates_movement_sequence_from_version(self):
        self.open(); self.post(); self.snapshot(amount='8.000000001')
        old = self.position('2026-01-01')['opening']
        anchored = self.anchor(expected_version=2)
        self.assertEqual(self.position('2026-01-01')['opening'], old)
        self.assertEqual(self.position()['opening']['rows'][0]['on_hand_qty'], '8.000000001')
        self.assertEqual(self.position()['latest']['rows'][0]['on_hand_qty'], '8.000000001')
        posted = self.post(expected_version=3, business_date='2026-01-02', key='after-anchor', source_reference='after-anchor')
        self.assertEqual((posted['version'], posted['sequence']), (4, 2))
        self.assertEqual(self.position()['opening']['rows'][0]['on_hand_qty'], '8.000000001')
        self.assertEqual(self.position('2026-01-03')['opening']['rows'][0]['on_hand_qty'], '9.000000001')
        history = self.call('list_movements', branch_id='001')
        self.assertEqual([row['sequence'] for row in history['items']], [2, 1])
        self.assertEqual([row['before_count_anchor'] for row in history['items']], [False, True])
        self.snapshot('2026-01-03', '7')
        second = self.anchor(key='anchor-2', count_date='2026-01-03', expected_version=4)
        self.assertEqual((second['version'], second['anchor_sequence']), (5, 2))
        self.assertEqual(self.position()['opening']['count_anchor']['id'], anchored['anchor_id'])
        self.assertEqual(self.position('2026-01-03')['opening']['count_anchor']['id'], second['anchor_id'])
        self.assertEqual(self.position('2026-01-03')['opening']['rows'][0]['on_hand_qty'], '7')
        self.assertEqual(self.call('list_count_anchors', branch_id='001', limit=1)['next_cursor'], '1')
        previous = self.call('list_count_anchors', branch_id='001', limit=1, cursor=1)
        self.assertEqual(previous['items'][0]['id'], anchored['anchor_id'])
        self.assertEqual(previous['items'][0]['counted_rows'][0]['on_hand_qty'], '8.000000001')

    def test_complete_count_requires_explicit_zero_for_every_previously_known_lot(self):
        self.open()
        self.post(lines=[dict(ingredient_id='milk', lot_id='milk-lot', unit='L', expiry_date='2026-01-05', quantity='1')])
        self.snapshot(amount='0')
        before = self.counts()
        self.error('STOCK_ANCHOR_INCOMPLETE', lambda:self.call('preview_count_anchor', **self.anchor_options(expected_version=2)))
        self.assertEqual(self.counts(), before)
        with self.factory.begin() as db:
            insert_rows(db, 'A', 'inventory_lots', [dict(fixtures.BASELINE, ingredient_id='milk', lot_id='milk-lot',
                snapshot_date='2026-01-02', on_hand_qty='0', unit='L')])
        preview = self.call('preview_count_anchor', **self.anchor_options(expected_version=2))
        self.assertEqual([row['difference'] for row in preview['differences']], ['-10', '-1'])
        self.anchor(expected_version=2)
        self.assertEqual([row['on_hand_qty'] for row in self.position()['opening']['rows']], ['0', '0'])

    def test_new_counted_lot_has_unknown_previous_quantity_and_keeps_unit_separate(self):
        self.open()
        extra = dict(fixtures.BASELINE, ingredient_id='milk', lot_id='found-lot', snapshot_date='2026-01-02',
                     on_hand_qty='1.123456789', unit='L')
        self.snapshot(extra=[extra])
        preview = self.call('preview_count_anchor', **self.anchor_options())
        found = next(row for row in preview['differences'] if row['ingredient_id'] == 'milk')
        self.assertEqual(found['status'], 'missing_ledger_lot')
        self.assertIsNone(found['ledger']); self.assertIsNone(found['difference'])
        self.anchor()
        milk = next(row for row in self.position()['opening']['rows'] if row['ingredient_id'] == 'milk')
        self.assertEqual((milk['on_hand_qty'], milk['unit']), ('1.123456789', 'L'))

    def test_metadata_precision_missing_snapshot_and_date_order_fail_without_mutation(self):
        self.open()
        self.error('STOCK_BASELINE_REQUIRED', lambda:self.call('preview_count_anchor', **self.anchor_options()))
        self.snapshot(amount='1.0000000001')
        self.error('STOCK_PRECISION_UNSUPPORTED', lambda:self.call('preview_count_anchor', **self.anchor_options()))
        self.correct_count('2026-01-02', '9')
        with self.factory.begin() as db:
            record = db.scalar(select(Record).where(Record.organization_id == 'A', Record.kind == 'inventory_lots',
                Record.data['snapshot_date'].as_string() == '2026-01-02'))
            record.data = dict(record.data, expiry_date='2026-01-06')
        self.error('STOCK_LOT_METADATA_CHANGED', lambda:self.call('preview_count_anchor', **self.anchor_options()))
        self.error('STOCK_ANCHOR_DATE_ORDER', lambda:self.call('preview_count_anchor', **self.anchor_options(count_date='2025-12-31')))
        self.post()
        self.error('STOCK_ANCHOR_DATE_ORDER', lambda:self.call('preview_count_anchor', **self.anchor_options(count_date='2026-01-01', expected_version=2)))
        self.assertEqual(self.counts()['StockCountAnchor'], 0)

    def test_anchor_acknowledgement_is_strict_and_same_date_cannot_be_reanchored(self):
        self.open(); self.snapshot(amount='10')
        command = self.anchor_command()
        for invalid in (False, 1, 'true', None):
            with self.subTest(ack=invalid):
                self.error('STOCK_ANCHOR_ACK_REQUIRED', lambda:self.call('post_count_anchor',
                    **dict(command, acknowledge_differences=invalid)))
        self.call('post_count_anchor', **command)
        self.error('STOCK_ANCHOR_DATE_ORDER', lambda:self.call('preview_count_anchor', **self.anchor_options(expected_version=2)))
        self.error('STOCK_BACKDATED', lambda:self.call('preview_movement', **self.options(expected_version=2)))

    def test_snapshot_actor_and_version_changes_invalidate_preview_and_exact_replay_is_immutable(self):
        self.open(); self.snapshot(); command = self.anchor_command()
        self.error('STOCK_PREVIEW_STALE', lambda:self.call('post_count_anchor', actor='manager', **command))
        self.correct_count('2026-01-02', '8')
        self.error('STOCK_PREVIEW_STALE', lambda:self.call('post_count_anchor', **command))
        command = self.anchor_command()
        first = self.call('post_count_anchor', **command); before = self.counts()
        self.correct_count('2026-01-02', '7')
        self.assertEqual(self.call('post_count_anchor', **command), first)
        self.assertEqual(self.counts(), before)
        self.error('IDEMPOTENCY_CONFLICT', lambda:self.call('post_count_anchor', **dict(command, reason='Another explanation')))
        self.error('STOCK_VERSION_CONFLICT', lambda:self.call('post_count_anchor', **dict(command, idempotency_key='another-key')))

    def test_newer_explicit_anchor_recovers_corrected_anchor_and_keeps_old_basis_warning(self):
        self.open(); self.snapshot(); self.anchor()
        self.correct_count('2026-01-02', '8')
        view = self.position()
        self.assertEqual(view['opening']['rows'][0]['on_hand_qty'], '9')
        self.assertEqual(view['effective_freshness'], 'changed')
        self.error('STOCK_BASELINE_CHANGED', lambda:self.call('preview_movement',
            **self.options(expected_version=2, business_date='2026-01-02')))
        self.snapshot('2026-01-03', '8')
        self.anchor(key='anchor-2', expected_version=2, count_date='2026-01-03')
        view = self.position()
        self.assertEqual((view['effective_freshness'], view['opening']['source_freshness']), ('unchanged', 'changed'))
        self.assertEqual(view['latest']['rows'][0]['on_hand_qty'], '8')
        self.post(expected_version=3, business_date='2026-01-03')
        self.assertEqual(self.position('2026-01-04')['opening']['rows'][0]['on_hand_qty'], '9')

    def test_future_anchor_and_superseded_baseline_correction_do_not_change_period_fingerprint(self):
        self.open(); self.snapshot()
        before = self.call('reconcile', branch_id='001', count_date='2026-01-01')
        self.anchor()
        self.assertEqual(self.call('reconcile', branch_id='001', count_date='2026-01-01')['stock_fingerprint'], before['stock_fingerprint'])
        counted = self.call('reconcile', branch_id='001', count_date='2026-01-02')
        self.assertEqual(counted['baseline_date'], '2026-01-02')
        self.assertEqual(counted['stock_evidence']['baseline_date'], '2026-01-02')
        self.assertEqual(counted['stock_evidence']['original_baseline_date'], '2026-01-01')
        self.correct_baseline('77')
        checked = self.call('reconcile', branch_id='001', count_date='2026-01-02')
        self.assertEqual(checked['status'], 'matched')
        self.assertEqual(checked['baseline_freshness'], 'changed')
        self.assertEqual(checked['effective_freshness'], 'unchanged')
        self.assertEqual(checked['stock_fingerprint'], counted['stock_fingerprint'])

    def test_reversal_cannot_cross_anchor_but_old_idempotent_document_replays(self):
        self.open(); options = self.options()
        preview = self.call('preview_movement', **options)
        command = dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='original')
        original = self.call('post_movement', **command)
        self.snapshot(); self.anchor(expected_version=2)
        before = self.counts()
        self.assertEqual(self.call('post_movement', **command), original)
        self.error('STOCK_REVERSAL_BEFORE_ANCHOR', lambda:self.call('preview_movement', **self.options(
            expected_version=3, kind='reversal', business_date='2026-01-02', source_reference='undo-original',
            lines=None, reverses_id=original['movement_id'])))
        self.assertEqual(self.counts(), before)
        new = self.post(expected_version=3, business_date='2026-01-02', key='new', source_reference='new')
        self.post(expected_version=4, business_date='2026-01-02', kind='reversal', key='undo-new',
                  source_reference='undo-new', lines=None, reverses_id=new['movement_id'])
        self.assertEqual(self.position('2026-01-03')['opening']['rows'][0]['on_hand_qty'], '9')

    def test_anchor_access_source_policy_and_real_future_date_are_rechecked(self):
        self.open(); self.snapshot()
        for actor in ('warehouse', 'analyst'):
            self.error('ROLE_FORBIDDEN', lambda:self.call('preview_count_anchor', actor=actor, **self.anchor_options()))
        self.error('BRANCH_FORBIDDEN', lambda:self.call('preview_count_anchor', **self.anchor_options(branch_id='002')))
        self.error('STOCK_LEDGER_REQUIRED', lambda:self.call('preview_count_anchor', actor='foreign', **self.anchor_options()))
        self.assertEqual(self.call('list_count_anchors', actor='foreign', branch_id='001')['items'], [])
        with self.factory.begin() as db: db.get(Organization, 'A').timezone = 'UTC'
        self.error('STOCK_CONTEXT_CHANGED', lambda:self.call('preview_count_anchor', **self.anchor_options()))
        with self.factory.begin() as db:
            org = db.get(Organization, 'A'); org.timezone='Asia/Qyzylorda'; org.data_policy='real_only'
            db.add(OrganizationSource(organization_id='A', source_id='test-source', mapping_version='v1',
                branch_id='001', authorization_reference='private-test-attestation', purpose='test_fixture', actor_id='admin'))
            for record in db.scalars(select(Record).where(Record.organization_id == 'A')):
                record.data = dict(record.data, data_origin='REAL')
        future = (date.today() + timedelta(days=2)).isoformat()
        self.error('STOCK_FUTURE_DATE', lambda:self.call('preview_count_anchor', **self.anchor_options(count_date=future)))
        self.error('STOCK_CONTEXT_CHANGED', lambda:self.call('preview_count_anchor', **self.anchor_options()))

    def test_caller_rollback_and_failed_audit_preserve_all_stock_and_receipts(self):
        self.open(); self.snapshot(); command = self.anchor_command(); before = self.counts()
        with self.factory() as db:
            service.post_count_anchor(db, db.get(User, 'admin'), **command)
            db.rollback()
        self.assertEqual(self.counts(), before)
        with patch.object(service, '_save', side_effect=RuntimeError('controlled audit failure')):
            with self.assertRaises(RuntimeError): self.call('post_count_anchor', **command)
        self.assertEqual(self.counts(), before)
        self.assertEqual(self.position()['version'], 1)

    def test_concurrent_identical_anchor_replays_once(self):
        self.open(); self.snapshot(); command = self.anchor_command(); barrier = threading.Barrier(2)
        def run():
            barrier.wait(timeout=10)
            return self.call('post_count_anchor', **command)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.counts(), dict(StockLedger=1, StockMovement=0, StockCountAnchor=1,
                                           StockCommandReceipt=2, Audit=2))

    def test_concurrent_anchor_and_movement_share_atomic_version_fence(self):
        self.open(); self.snapshot(); anchor = self.anchor_command()
        options = self.options(); preview = self.call('preview_movement', **options)
        movement = dict(**options, expected_fingerprint=preview['preview_fingerprint'], idempotency_key='movement')
        barrier = threading.Barrier(2)
        def run(name, command):
            barrier.wait(timeout=10)
            try: return self.call(name, **command)['status']
            except StockError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, name, command) for name, command in
                       [('post_count_anchor', anchor), ('post_movement', movement)]]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(results.count('STOCK_VERSION_CONFLICT'), 1)
        counts = self.counts()
        self.assertEqual(counts['StockCountAnchor'] + counts['StockMovement'], 1)
        self.assertEqual(self.position()['version'], 2)
        self.assertEqual(counts['StockCommandReceipt'], 2)
        self.assertEqual(counts['Audit'], 2)

    def test_concurrent_different_anchor_commands_have_only_one_winner(self):
        self.open(); self.snapshot(); barrier = threading.Barrier(2)
        commands = [self.anchor_command(key='count-'+str(number), reason='Count review '+str(number)) for number in range(2)]
        def run(command):
            barrier.wait(timeout=10)
            try: return self.call('post_count_anchor', **command)['status']
            except StockError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, commands))
        self.assertCountEqual(outcomes, ['anchored', 'STOCK_VERSION_CONFLICT'])
        self.assertEqual(self.counts()['StockCountAnchor'], 1)

    def test_stale_user_or_organization_objects_cannot_post_anchor(self):
        self.open(); self.snapshot(); command = self.anchor_command()
        with self.factory() as held:
            stale = held.get(User, 'admin')
            organization = held.get(Organization, 'A')
            with self.factory.begin() as other:
                other.get(User, 'admin').role = 'analyst'
            self.error('ROLE_FORBIDDEN', lambda:service.post_count_anchor(held, stale, **command))
            held.rollback()
            organization = held.get(Organization, 'A')
            with self.factory.begin() as other:
                other.get(User, 'admin').role = 'admin'
                other.get(Organization, 'A').status = 'suspended'
            self.assertEqual(organization.status, 'active')
            self.error('AUTH_REQUIRED', lambda:service.post_count_anchor(held, stale, **command))
        self.assertEqual(self.counts()['StockCountAnchor'], 0)


if __name__ == '__main__':
    unittest.main()
