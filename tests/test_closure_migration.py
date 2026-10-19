"""Migration0011 is additive, rollback-safe and never closes a day implicitly."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from apps.api import migrations
from apps.api.db import Base, BranchProfile, DayClosure, migrate
import test_profile_migration as previous


class ClosureMigrationTests(unittest.TestCase):
    setUp = previous.ProfileMigrationTests.setUp
    versions = previous.ProfileMigrationTests.versions

    def prepare(self):
        previous.ProfileMigrationTests.prepare(self)
        with self.engine.begin() as db:
            migrations._branch_profile_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0010')"))
            db.execute(BranchProfile.__table__.insert(), dict(organization_id='A', branch_id='01', city_code='almaty',
                                                              establishment_type='cafe', updated_by='operator', updated_at='2026-10-19'))
        self.assertEqual(self.versions(), migrations.VERSIONS[:10])

    def snapshot(self):
        with self.engine.connect() as db:
            return {name: [dict(row) for row in db.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                    for name, table in Base.metadata.tables.items() if name not in migrations.CLOSURE_TABLE_NAMES + migrations.WORKDAY_TABLE_NAMES}

    def test_upgrade_preserves_all_prior_rows_and_closes_no_day(self):
        self.prepare(); before=self.snapshot()
        self.assertTrue(before['branch_profiles'])
        self.assertTrue(before['stock_count_anchors'])
        self.assertEqual(migrate(self.engine), migrations.VERSIONS[10:])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.versions(), migrations.VERSIONS)
        with self.engine.connect() as db:
            self.assertEqual(list(db.execute(select(DayClosure.__table__))), [])
        self.assertEqual(migrate(self.engine), ())
        self.assertEqual(self.snapshot(), before)

    def test_failed_upgrade_rolls_back_table_and_marker(self):
        self.prepare(); before=self.snapshot()
        operation=migrations._day_closure_schema
        def fail(db):
            operation(db)
            raise RuntimeError('Controlled day closure schema interruption')
        with patch.object(migrations,'_day_closure_schema',side_effect=fail), self.assertRaises(RuntimeError):
            migrate(self.engine)
        self.assertEqual(self.versions(), migrations.VERSIONS[:10])
        self.assertNotIn('day_closures', inspect(self.engine).get_table_names())
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(migrate(self.engine),migrations.VERSIONS[10:])

    def test_fresh_database_and_concurrent_migrations(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes=list(pool.map(lambda _:migrate(self.engine),range(3)))
        self.assertCountEqual(outcomes,[migrations.VERSIONS,(),()])
        self.assertEqual(set(inspect(self.engine).get_table_names()),set(Base.metadata.tables)|{'schema_migrations'})

    def test_unknown_preexisting_table_is_preserved_and_not_stamped(self):
        self.prepare(); before=self.snapshot()
        with self.engine.begin() as db:
            db.execute(text('CREATE TABLE day_closures (sentinel TEXT NOT NULL)'))
            db.execute(text("INSERT INTO day_closures VALUES ('preserve')"))
        with self.assertRaises(SQLAlchemyError): migrate(self.engine)
        self.assertEqual(self.versions(),migrations.VERSIONS[:10])
        self.assertEqual(self.snapshot(),before)
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT sentinel FROM day_closures')).scalar_one(),'preserve')


if __name__=='__main__': unittest.main()
