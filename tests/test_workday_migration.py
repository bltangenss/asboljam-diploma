"""Migration0012 preserves existing facts and never selects or reconciles a day implicitly."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from apps.api import migrations
from apps.api.db import Base, DayClosure, migrate
import test_closure_migration as previous


class WorkdayMigrationTests(unittest.TestCase):
    setUp = previous.ClosureMigrationTests.setUp
    versions = previous.ClosureMigrationTests.versions

    def prepare(self):
        previous.ClosureMigrationTests.prepare(self)
        with self.engine.begin() as db:
            migrations._day_closure_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0011')"))
            db.execute(DayClosure.__table__.insert(), dict(organization_id='A', branch_id='01',
                business_date='2026-01-01', status='draft', version=2, is_open=1,
                lines=[{'meal_id': '01', 'state': None, 'units_sold': None}], data_origin='SYNTHETIC',
                created_by='operator', updated_by='operator', batch_ids=[]))
        self.assertEqual(self.versions(), migrations.VERSIONS[:11])

    def snapshot(self):
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                    for name, table in Base.metadata.tables.items() if name not in migrations.WORKDAY_TABLE_NAMES}

    def test_upgrade_preserves_prior_rows_and_adds_only_empty_tables(self):
        self.prepare(); before = self.snapshot()
        self.assertTrue(before['day_closures'])
        self.assertEqual(migrate(self.engine), ('0012',))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), migrations.VERSIONS)
        with self.engine.connect() as db:
            for name in migrations.WORKDAY_TABLE_NAMES:
                self.assertEqual(list(db.execute(select(Base.metadata.tables[name]))), [], name)
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.snapshot(), before)

    def test_failed_upgrade_rolls_back_all_new_tables_and_marker(self):
        self.prepare(); before = self.snapshot()
        operation = migrations._workday_schema
        def fail(db):
            operation(db)
            raise RuntimeError('Controlled workday schema interruption')
        with patch.object(migrations, '_workday_schema', side_effect=fail), self.assertRaises(RuntimeError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:11])
        self.assertTrue(set(migrations.WORKDAY_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(migrate(self.engine), ('0012',))

    def test_fresh_database_and_concurrent_migrations(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(lambda _: migrate(self.engine), range(3)))
        self.assertCountEqual(outcomes, [migrations.VERSIONS, (), ()])
        self.assertEqual(set(inspect(self.engine).get_table_names()), set(Base.metadata.tables) | {'schema_migrations'})

    def test_unknown_preexisting_table_is_preserved_and_not_stamped(self):
        self.prepare(); before = self.snapshot()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE notification_receipts (sentinel TEXT NOT NULL)'))
            db.execute(text("INSERT INTO notification_receipts VALUES ('preserve')"))
        with self.assertRaises(SQLAlchemyError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:11])
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn('working_plan_selections', inspect(self.engine).get_table_names())
        self.assertNotIn('reconciliation_snapshots', inspect(self.engine).get_table_names())
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM notification_receipts')).scalar_one(), 'preserve')


if __name__ == '__main__':
    unittest.main()
