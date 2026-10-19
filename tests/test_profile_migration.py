"""Migration0010 is additive, rollback-safe and never assigns a city implicitly."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from apps.api import migrations
from apps.api.db import Base, BranchProfile, migrate
import test_production_migration as previous


class ProfileMigrationTests(unittest.TestCase):
    setUp = previous.ProductionMigrationTests.setUp
    versions = previous.ProductionMigrationTests.versions

    def prepare(self):
        previous.ProductionMigrationTests.prepare(self)
        with self.engine.begin() as db:
            migrations._production_plan_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0009')"))
        self.assertEqual(self.versions(), migrations.VERSIONS[:9])

    def snapshot(self):
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                    for name, table in Base.metadata.tables.items() if name not in migrations.PROFILE_TABLE_NAMES + migrations.CLOSURE_TABLE_NAMES + migrations.WORKDAY_TABLE_NAMES}

    def test_upgrade_preserves_all_prior_rows_and_assigns_no_city(self):
        self.prepare(); before=self.snapshot()
        self.assertTrue(before['stock_count_anchors'])
        self.assertTrue(before['recipe_activations'])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[9:])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), migrations.VERSIONS)
        with self.engine.connect() as db:
            self.assertEqual(list(db.execute(select(BranchProfile.__table__))), [])
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.snapshot(), before)

    def test_failed_upgrade_rolls_back_table_and_marker(self):
        self.prepare(); before=self.snapshot()
        operation=migrations._branch_profile_schema
        def fail(db):
            operation(db)
            raise RuntimeError('Controlled profile schema interruption')
        with patch.object(migrations,'_branch_profile_schema',side_effect=fail), self.assertRaises(RuntimeError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:9])
        self.assertNotIn('branch_profiles', inspect(self.engine).get_table_names())
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(migrate(self.engine),migrations.VERSIONS[9:])

    def test_fresh_database_and_concurrent_migrations(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes=list(pool.map(lambda _:migrate(self.engine),range(3)))
        self.assertCountEqual(outcomes,[migrations.VERSIONS,(),()])
        self.assertIn('branch_profiles', inspect(self.engine).get_table_names())

    def test_unknown_preexisting_table_is_preserved_and_not_stamped(self):
        self.prepare(); before=self.snapshot()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE branch_profiles (sentinel TEXT NOT NULL)'))
            db.execute(text("INSERT INTO branch_profiles VALUES ('preserve')"))
        with self.assertRaises(SQLAlchemyError): migrate(self.engine)
        self.assertEqual(self.versions(),migrations.VERSIONS[:9])
        self.assertEqual(self.snapshot(),before)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM branch_profiles')).scalar_one(),'preserve')


if __name__=='__main__': unittest.main()
