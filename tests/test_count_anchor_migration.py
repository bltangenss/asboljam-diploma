"""Migration0008 preserves old evidence and never invents a counted anchor."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from apps.api import migrations
from apps.api.db import (Base, RecipeActivation, RecipeCommandReceipt, StockCommandReceipt,
                         StockCountAnchor, StockLedger, make_engine, migrate)
from database_fixture import isolated_database_url
import test_recipe_activation as previous_fixture
import test_stock_migration as stock_fixture


class CountAnchorMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='count-anchor-migration-')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url(
            'sqlite:///' + (Path(self.temp.name) / 'fixture.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def versions(self):
        with self.engine.connect() as db:
            return tuple(db.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())

    def prepare(self):
        previous_fixture.RecipeMigrationTests.prepare(self)
        with self.engine.begin() as db:
            migrations._dated_recipes_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0007')"))
            db.execute(RecipeActivation.__table__.insert(), dict(id='recipe', organization_id='A', branch_id='01',
                meal_id='meal', sequence=1, recipe_version='v1.0 fixture', effective_date='2026-01-01',
                rows=[{'ingredient_id': '0007', 'net_qty_per_portion': '0.125000000', 'captured_yield_factor': '0.8'}],
                snapshot_sha256='d' * 64, data_context={'data_origin': 'SYNTHETIC'}, reason='Original recipe', actor_id='operator'))
            db.execute(RecipeCommandReceipt.__table__.insert(), dict(id='recipe-receipt', organization_id='A',
                actor_id='operator', key='recipe-command', payload_hash='e' * 64, activation_id='recipe', response={'version': 1}))
            db.execute(StockCommandReceipt.__table__.insert(), dict(id='stock-receipt', organization_id='A',
                actor_id='operator', key='stock-command', payload_hash='f' * 64, ledger_id='ledger', response={'version': 2}))
        self.assertEqual(self.versions(), migrations.VERSIONS[:7])
        self.assertNotIn('stock_count_anchors', inspect(self.engine).get_table_names())

    def snapshot(self):
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                for name, table in Base.metadata.tables.items() if name not in migrations.COUNT_ANCHOR_TABLE_NAMES + migrations.PRODUCTION_TABLE_NAMES + migrations.PROFILE_TABLE_NAMES + migrations.CLOSURE_TABLE_NAMES}

    def values(self, **changes):
        return dict(id='anchor', ledger_id='ledger', organization_id='A', branch_id='01', sequence=1,
            ledger_version=2, through_movement_sequence=0, count_date='2026-01-01',
            counted_rows=[dict(ingredient_id='0007', lot_id='lot-01', unit='kg', on_hand_qty='10.500000001',
                              expiry_date='2026-01-03', snapshot_date='2026-01-01', branch_id='01', data_origin='SYNTHETIC')],
            count_lineage={'version': 'fixture', 'revision': 2}, data_context={'data_origin': 'SYNTHETIC', 'usage_mode': 'TEST'},
            differences=[{'ingredient_id': '0007', 'lot_id': 'lot-01', 'difference': '0.000000001', 'status': 'mismatch'}],
            previous_fingerprint='a' * 64, reason='Explicit generated count acceptance', actor_id='operator') | changes

    def test_upgrade_preserves_every_existing_row_and_fabricates_no_count(self):
        self.prepare()
        before = self.snapshot()
        self.assertTrue(before['stock_ledgers'])
        self.assertTrue(before['stock_movements'])
        self.assertTrue(before['recipe_activations'])
        self.assertTrue(before['stock_command_receipts'])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[7:])
        self.assertEqual(self.versions(), migrations.VERSIONS)
        self.assertEqual(self.snapshot(), before)
        with self.engine.connect() as db:
            self.assertEqual(list(db.execute(select(StockCountAnchor.__table__))), [])
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.snapshot(), before)

    def test_fresh_database_applies_schema_without_opening_or_anchoring_stock(self):
        self.assertEqual(migrate(self.engine), migrations.VERSIONS)
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(Base.metadata.tables) | {'schema_migrations'})
        with self.engine.connect() as db:
            self.assertEqual(list(db.execute(select(StockCountAnchor.__table__))), [])
            self.assertEqual(list(db.execute(select(StockLedger.__table__))), [])

    def test_interrupted_upgrade_rolls_back_anchor_rows_table_and_marker(self):
        self.prepare()
        before = self.snapshot()
        def fail(db):
            migrations_operation(db)
            db.execute(StockCountAnchor.__table__.insert(), self.values())
            raise RuntimeError('Controlled interrupted count migration')
        migrations_operation = migrations._stock_count_anchor_schema
        with patch.object(migrations, '_stock_count_anchor_schema', side_effect=fail):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:7])
        self.assertNotIn('stock_count_anchors', inspect(self.engine).get_table_names())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[7:])

    def test_fresh_interruption_rolls_back_all_ddl(self):
        def fail(db):
            StockCountAnchor.__table__.create(db)
            raise RuntimeError('Controlled fresh interruption')
        with patch.object(migrations, '_stock_count_anchor_schema', side_effect=fail):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(), [])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS)

    def test_concurrent_upgrades_create_one_anchor_schema(self):
        self.prepare()
        before = self.snapshot()
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(lambda _: migrate(self.engine), range(3)))
        self.assertCountEqual(outcomes, [migrations.VERSIONS[7:], (), ()])
        self.assertEqual(self.snapshot(), before)

    def test_existing_unknown_anchor_table_is_not_overwritten_or_stamped(self):
        self.prepare()
        before = self.snapshot()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE stock_count_anchors (sentinel TEXT NOT NULL)'))
            db.execute(text("INSERT INTO stock_count_anchors VALUES ('preserve-me')"))
        with self.assertRaises(SQLAlchemyError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:7])
        self.assertEqual(self.snapshot(), before)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM stock_count_anchors')).scalar_one(), 'preserve-me')

    def test_constraints_and_exact_frozen_json_roundtrip(self):
        migrate(self.engine)
        with self.engine.begin() as db:
            db.execute(StockLedger.__table__.insert(), stock_fixture.StockMigrationTests.ledger_values(self))
            db.execute(StockLedger.__table__.insert(), stock_fixture.StockMigrationTests.ledger_values(self, id='other', organization_id='B'))
            db.execute(StockCountAnchor.__table__.insert(), self.values())
            db.execute(StockCountAnchor.__table__.insert(), self.values(id='other-anchor', ledger_id='other', organization_id='B'))
        invalid = (
            {'sequence': 0, 'through_movement_sequence': 3, 'ledger_version': 4},
            {'ledger_version': 1, 'sequence': 1, 'through_movement_sequence': -1},
            {'sequence': 2, 'ledger_version': 2, 'through_movement_sequence': -1},
            {'ledger_version': 100},  # counter identity cannot be invented
            {'sequence': 1, 'ledger_version': 3, 'through_movement_sequence': 1},  # duplicate anchor sequence
            {'sequence': 2, 'ledger_version': 3, 'through_movement_sequence': 0, 'count_date': '2026-01-01'},
            {'ledger_id': 'missing'},
        )
        for changes in invalid:
            values = self.values(id='invalid', sequence=2, ledger_version=4,
                                 through_movement_sequence=1, count_date='2026-01-02') | changes
            with self.subTest(changes=changes), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    db.execute(StockCountAnchor.__table__.insert(), values)
        with self.engine.connect() as db:
            stored = db.execute(select(StockCountAnchor.__table__).where(StockCountAnchor.id == 'anchor')).mappings().one()
            for field in ('counted_rows', 'count_lineage', 'data_context', 'differences', 'previous_fingerprint'):
                self.assertEqual(stored[field], self.values()[field])
        with self.engine.begin() as db:
            db.execute(StockCountAnchor.__table__.insert(), self.values(id='next', sequence=2,
                through_movement_sequence=1, ledger_version=4, count_date='2026-01-02'))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as db:
                db.execute(StockCountAnchor.__table__.insert(), self.values(id='same-ledger-version', sequence=3,
                    through_movement_sequence=0, ledger_version=4, count_date='2026-01-03'))


if __name__ == '__main__':
    unittest.main()
