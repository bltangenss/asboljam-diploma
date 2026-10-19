"""Migration0009 is additive, rollback-safe and does not infer cooking decisions."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from apps.api import migrations
from apps.api.db import Base, ProductionPlan, StockCountAnchor, migrate
import test_count_anchor_migration as previous


class ProductionMigrationTests(unittest.TestCase):
    setUp = previous.CountAnchorMigrationTests.setUp
    versions = previous.CountAnchorMigrationTests.versions

    def prepare(self):
        previous.CountAnchorMigrationTests.prepare(self)
        with self.engine.begin() as db:
            migrations._stock_count_anchor_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0008')"))
            db.execute(StockCountAnchor.__table__.insert(), previous.CountAnchorMigrationTests.values(self))
        self.assertEqual(self.versions(), migrations.VERSIONS[:8])

    def snapshot(self):
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                    for name, table in Base.metadata.tables.items() if name not in migrations.PRODUCTION_TABLE_NAMES + migrations.PROFILE_TABLE_NAMES + migrations.CLOSURE_TABLE_NAMES}

    def test_upgrade_preserves_all_prior_rows_and_is_repeatable(self):
        self.prepare(); before=self.snapshot()
        self.assertTrue(before['stock_count_anchors'])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[8:])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), migrations.VERSIONS)
        with self.engine.connect() as db:
            for name in migrations.PRODUCTION_TABLE_NAMES:
                self.assertEqual(list(db.execute(select(Base.metadata.tables[name]))), [])
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.snapshot(), before)

    def test_failed_upgrade_rolls_back_tables_and_marker(self):
        self.prepare(); before=self.snapshot()
        operation=migrations._production_plan_schema
        def fail(db):
            operation(db)
            raise RuntimeError('Controlled production schema interruption')
        with patch.object(migrations,'_production_plan_schema',side_effect=fail), self.assertRaises(RuntimeError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:8])
        self.assertTrue(set(migrations.PRODUCTION_TABLE_NAMES).isdisjoint(inspect(self.engine).get_table_names()))
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(migrate(self.engine),migrations.VERSIONS[8:])

    def test_fresh_database_and_concurrent_migrations(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes=list(pool.map(lambda _:migrate(self.engine),range(3)))
        self.assertCountEqual(outcomes,[migrations.VERSIONS,(),()])
        self.assertEqual(set(inspect(self.engine).get_table_names()),set(Base.metadata.tables)|{'schema_migrations'})

    def test_unknown_preexisting_table_is_preserved_and_not_stamped(self):
        self.prepare(); before=self.snapshot()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE production_plans (sentinel TEXT NOT NULL)'))
            db.execute(text("INSERT INTO production_plans VALUES ('preserve')"))
        with self.assertRaises(SQLAlchemyError): migrate(self.engine)
        self.assertEqual(self.versions(),migrations.VERSIONS[:8])
        self.assertEqual(self.snapshot(),before)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM production_plans')).scalar_one(),'preserve')

    def test_fresh_failure_rolls_back_all_ddl(self):
        def fail(db):
            ProductionPlan.__table__.create(db)
            raise RuntimeError('Controlled initial schema interruption')
        with patch.object(migrations,'_production_plan_schema',side_effect=fail), self.assertRaises(RuntimeError):
            migrate(self.engine)
        self.assertEqual(inspect(self.engine).get_table_names(),[])


if __name__=='__main__': unittest.main()
