"""Stock journal foundation: explicit empty migration, preservation and constraints.

These tests verify storage, not a stock workflow or procurement integration.
SQLite is isolated; PostgreSQL requires the guarded opt-in fixture database.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api import migrations
from apps.api.db import (Base, Idempotency, ImportEvidence, ImportReceipt,
                         OrganizationSource, RecordRevision, StockCommandReceipt,
                         StockLedger, StockMovement, make_engine, migrate)
from database_fixture import isolated_database_url
import test_tenant_migration as legacy_fixture


class StockMigrationTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='stock-migration-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name).resolve() / 'fixture.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def versions(self):
        with self.engine.connect() as db:
            return tuple(db.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())

    def prepare_v5(self):
        legacy_fixture.TenantMigrationTests.legacy_schema(self)
        prior_operations = (migrations._tenant_schema, migrations._import_schema,
                            migrations._real_source_schema, migrations._job_heartbeat_schema)
        for version, operation in zip(migrations.VERSIONS[1:5], prior_operations):
            with self.engine.begin() as db:
                operation(db)
                db.execute(text('INSERT INTO schema_migrations VALUES (:version)'), {'version': version})
            self.assertTrue(set(migrations.STOCK_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))
        with self.engine.begin() as db:
            db.execute(text("UPDATE jobs SET status='running', started_at=12340, heartbeat_at=12345 WHERE id='job'"))
            db.execute(ImportEvidence.__table__.insert(), dict(batch_id='batch', organization_id='imports-only',
                actor_id='legacy-user', kind='daily_sales', source={'source_id': 'fixture'},
                summary={'new': 1}, expected_state={}, received_text_sha256='a' * 64))
            db.execute(RecordRevision.__table__.insert(), dict(id='revision', organization_id='demo',
                kind='branches', natural_key='01', branch_id='01', revision=1, record_id=78,
                before_data=None, after_data={'branch_id': '01'}, before_sha256=None,
                after_sha256='b' * 64, batch_id='batch', actor_id='demo-user'))
            db.execute(ImportReceipt.__table__.insert(), dict(id='receipt', organization_id='demo',
                actor_id='demo-user', key='old-import-key', payload_hash='c' * 64, batch_id='batch',
                response={'committed': True}))
            db.execute(OrganizationSource.__table__.insert(), dict(organization_id='demo', source_id='fixture',
                mapping_version='v1', branch_id='01', authorization_reference='artificial-fixture',
                purpose='test_fixture', version=1, actor_id='demo-user'))
        self.assertEqual(self.versions(), migrations.VERSIONS[:5])

    def old_snapshot(self):
        names = (*migrations.LEGACY_TABLE_NAMES, 'organizations',
                 *migrations.IMPORT_TABLE_NAMES, *migrations.SOURCE_TABLE_NAMES)
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(Base.metadata.tables[name]).order_by(
                *Base.metadata.tables[name].primary_key.columns)).mappings()] for name in names}

    def assert_empty_stock(self):
        with self.engine.connect() as db:
            for name in migrations.STOCK_TABLE_NAMES:
                self.assertEqual(list(db.execute(select(Base.metadata.tables[name]))), [], name)

    def ledger_values(self, **changes):
        values = dict(id='ledger', organization_id='A', branch_id='01', baseline_date='2026-01-01',
            baseline_rows=[{'ingredient_id': '0007', 'lot_id': 'lot-01', 'unit': 'kg',
                            'on_hand_qty': '10.5000', 'expiry_date': '2026-01-03'}],
            baseline_lineage={'version': 'fixture', 'source': 'counted'},
            data_context={'data_origin': 'SYNTHETIC', 'usage_mode': 'TEST'}, created_by='operator')
        return values | changes

    def movement_values(self, **changes):
        values = dict(id='movement', ledger_id='ledger', organization_id='A', branch_id='01',
            sequence=1, kind='receipt', business_date='2026-01-01', reason='Artificial test receipt',
            source_reference='document-001', entries=[{'ingredient_id': '0007', 'lot_id': 'lot-01',
                'unit': 'kg', 'expiry_date': '2026-01-03', 'quantity_delta': '0.1000'}], actor_id='operator')
        return values | changes

    def test_earlier_schemas_exclude_stock_journal(self):
        self.assertTrue(set(migrations.STOCK_TABLE_NAMES).isdisjoint(migrations.LEGACY_TABLE_NAMES))
        self.prepare_v5()

    def test_populated_upgrade_preserves_every_old_row_and_invents_no_stock(self):
        self.prepare_v5()
        before = self.old_snapshot()
        self.assertTrue(all(before.values()))
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[5:])
        self.assertEqual(self.versions(), migrations.VERSIONS)
        self.assertEqual(self.old_snapshot(), before)
        self.assert_empty_stock()
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.old_snapshot(), before)
        self.assert_empty_stock()

    def partial_failure(self, db):
        StockLedger.__table__.create(db)
        db.execute(StockLedger.__table__.insert(), self.ledger_values())
        StockMovement.__table__.create(db)
        db.execute(StockMovement.__table__.insert(), self.movement_values())
        raise RuntimeError('Controlled interrupted stock migration')

    def test_upgrade_failure_rolls_back_new_tables_rows_and_marker(self):
        self.prepare_v5()
        before = self.old_snapshot()
        with patch.object(migrations, '_stock_journal_schema', side_effect=self.partial_failure):
            with self.assertRaisesRegex(RuntimeError, 'interrupted stock migration'):
                migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:5])
        self.assertTrue(set(migrations.STOCK_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))
        self.assertEqual(self.old_snapshot(), before)
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[5:])
        self.assert_empty_stock()

    def test_failure_on_fresh_database_rolls_back_all_schema(self):
        with patch.object(migrations, '_stock_journal_schema', side_effect=self.partial_failure):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS)
        self.assert_empty_stock()

    def test_concurrent_upgrade_creates_journal_once(self):
        self.prepare_v5()
        before = self.old_snapshot()
        barrier = threading.Barrier(3)

        def upgrade():
            barrier.wait(timeout=10)
            return migrate(self.engine)

        with ThreadPoolExecutor(max_workers=3) as pool:
            tasks = [pool.submit(upgrade) for _ in range(3)]
            outcomes = [task.result(timeout=30) for task in tasks]
        self.assertEqual(outcomes.count(migrations.VERSIONS[5:]), 1)
        self.assertEqual(outcomes.count(()), 2)
        self.assertEqual(self.old_snapshot(), before)
        self.assertEqual(self.versions(), migrations.VERSIONS)
        self.assert_empty_stock()

    def test_unexpected_existing_table_is_preserved_and_not_stamped(self):
        self.prepare_v5()
        before = self.old_snapshot()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE stock_movements (sentinel TEXT NOT NULL)'))
            db.execute(text("INSERT INTO stock_movements VALUES ('preserve-me')"))
        with self.assertRaises(SQLAlchemyError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:5])
        self.assertEqual(self.old_snapshot(), before)
        self.assertNotIn('stock_ledgers', inspect(self.engine).get_table_names())
        self.assertNotIn('stock_command_receipts', inspect(self.engine).get_table_names())
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM stock_movements')).scalar_one(), 'preserve-me')

    def test_ledger_unique_branch_scope_positive_version_and_exact_evidence(self):
        migrate(self.engine)
        original = self.ledger_values()
        with self.engine.begin() as db:
            db.execute(StockLedger.__table__.insert(), original)
            db.execute(StockLedger.__table__.insert(), self.ledger_values(id='other-org', organization_id='B'))
            db.execute(StockLedger.__table__.insert(), self.ledger_values(id='other-branch', branch_id='02'))
        for identifier, changes in (('duplicate', {}), ('zero', {'branch_id': '03', 'version': 0}),
                                    ('negative', {'branch_id': '04', 'version': -1})):
            with self.subTest(identifier=identifier), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    db.execute(StockLedger.__table__.insert(), self.ledger_values(id=identifier, **changes))
        with self.engine.connect() as db:
            row = db.execute(select(StockLedger.__table__).where(StockLedger.id == 'ledger')).mappings().one()
            self.assertEqual(row['version'], 1)
            for field in ('baseline_rows', 'baseline_lineage', 'data_context'):
                self.assertEqual(row[field], original[field])

    def test_movement_constraints_and_decimal_json_roundtrip(self):
        migrate(self.engine)
        with self.engine.begin() as db:
            db.execute(StockLedger.__table__.insert(), self.ledger_values())
            db.execute(StockLedger.__table__.insert(), self.ledger_values(id='other-ledger', organization_id='B'))
            for sequence, kind in enumerate(('receipt', 'recipe_usage', 'waste', 'adjustment', 'reversal'), 1):
                db.execute(StockMovement.__table__.insert(), self.movement_values(id=kind, sequence=sequence,
                    kind=kind, source_reference=kind,
                    reverses_id='receipt' if kind == 'reversal' else None))
            # Documents and sequence numbers are local to a ledger; null reversals do not collide.
            db.execute(StockMovement.__table__.insert(), self.movement_values(id='other-ledger-receipt',
                ledger_id='other-ledger', organization_id='B', source_reference='receipt'))
        invalid = (('zero', {'sequence': 0}), ('negative', {'sequence': -1}),
                   ('unknown-kind', {'kind': 'sale'}), ('duplicate-sequence', {'sequence': 1}),
                   ('duplicate-source', {'source_reference': 'receipt'}),
                   ('duplicate-reversal', {'kind': 'reversal', 'reverses_id': 'receipt'}),
                   ('unknown-ledger', {'ledger_id': 'missing-ledger'}))
        for identifier, changes in invalid:
            with self.subTest(identifier=identifier), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    values = self.movement_values(id=identifier, sequence=100, source_reference=identifier)
                    db.execute(StockMovement.__table__.insert(), values | changes)
        with self.engine.connect() as db:
            row = db.execute(select(StockMovement.__table__).where(StockMovement.id == 'receipt')).mappings().one()
            self.assertEqual(row['entries'], self.movement_values()['entries'])
            self.assertIsNone(row['recipe_evidence'])
            self.assertIsNone(row['reverses_id'])
            self.assertEqual(db.execute(text('SELECT recipe_evidence FROM stock_movements WHERE id=:id'),
                                       {'id': 'receipt'}).scalar_one(), None)

    def test_stock_receipt_key_scope_and_independent_command_namespace(self):
        migrate(self.engine)
        common = dict(organization_id='A', actor_id='operator', key='shared-client-key', payload_hash='a' * 64)
        with self.engine.begin() as db:
            db.execute(StockLedger.__table__.insert(), self.ledger_values())
            db.execute(StockCommandReceipt.__table__.insert(), dict(id='stock', ledger_id='ledger', response={'version': 1}, **common))
            db.execute(StockCommandReceipt.__table__.insert(), dict(common, id='other-actor', actor_id='peer', ledger_id='ledger', response={}))
            db.execute(StockCommandReceipt.__table__.insert(), dict(common, id='other-org', organization_id='B', ledger_id='ledger', response={}))
            db.execute(ImportReceipt.__table__.insert(), dict(id='import', batch_id='batch', response={}, **common))
            db.execute(Idempotency.__table__.insert(), dict(id='plan', response={}, **common))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as db:
                db.execute(StockCommandReceipt.__table__.insert(), dict(id='duplicate', ledger_id='other', response={}, **common))


if __name__ == '__main__':
    unittest.main()
