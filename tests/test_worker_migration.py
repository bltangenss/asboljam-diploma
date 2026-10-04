"""Migration0005 preserves original job rows; no heartbeat is backfilled."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import inspect, select, text
from apps.api import migrations
from apps.api.db import make_engine, migrate
from database_fixture import isolated_database_url
import test_tenant_migration as fixtures


class WorkerMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='worker-migration-')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url('sqlite:///' + (Path(self.temp.name)/'fixture.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)

    def prepare(self):
        fixtures.TenantMigrationTests.legacy_schema(self)
        with self.engine.begin() as db:
            migrations._tenant_schema(db)
            migrations._import_schema(db)
            migrations._real_source_schema(db)
            db.execute(text("INSERT INTO schema_migrations VALUES ('0002'),('0003'),('0004')"))
            db.execute(text("UPDATE jobs SET status='running',started_at=12345 WHERE id='job'"))
        self.assertNotIn('heartbeat_at', {c['name'] for c in inspect(self.engine).get_columns('jobs')})

    def jobs(self):
        with self.engine.connect() as db:
            return [dict(row._mapping) for row in db.execute(select(migrations._JOB_V1))]

    def test_original_schema_excludes_future_heartbeat(self):
        self.prepare()
        self.assertEqual(len(self.jobs()), 1)

    def test_populated_upgrade_preserves_rows_and_initial_heartbeat_is_unknown(self):
        self.prepare()
        before = self.jobs()
        self.assertEqual(migrate(self.engine), ('0005',))
        self.assertEqual(self.jobs(), before)
        with self.engine.connect() as db:
            self.assertIsNone(db.execute(text('SELECT heartbeat_at FROM jobs')).scalar_one())
        self.assertEqual(migrate(self.engine), ())

    def test_failure_rolls_back_added_column_and_marker(self):
        self.prepare()
        before, apply = self.jobs(), migrations._job_heartbeat_schema

        def fail(db):
            apply(db)
            raise RuntimeError('controlled migration failure')

        with patch.object(migrations, '_job_heartbeat_schema', side_effect=fail):
            with self.assertRaises(RuntimeError):
                migrate(self.engine)
        self.assertEqual(self.jobs(), before)
        self.assertNotIn('heartbeat_at', {c['name'] for c in inspect(self.engine).get_columns('jobs')})
        with self.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM schema_migrations')).scalar_one(), 4)
        self.assertEqual(migrate(self.engine), ('0005',))

    def test_concurrent_upgrade_adds_heartbeat_once(self):
        self.prepare()
        before = self.jobs()
        with ThreadPoolExecutor(max_workers=3) as pool:
            outcomes = list(pool.map(lambda _: migrate(self.engine), range(3)))
        self.assertEqual(outcomes.count(('0005',)), 1)
        self.assertEqual(outcomes.count(()), 2)
        self.assertEqual(self.jobs(), before)


if __name__ == '__main__':
    unittest.main()
