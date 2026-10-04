"""Readiness checks actual migration state and never disclose database failures."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, TimeoutError
from apps.api.main import create_app
from apps.api.migrations import VERSIONS
from database_fixture import isolated_database_url


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'ASBOLJAM_ENV':'local', 'COOKIE_SECURE':'false',
                                     'ALLOWED_ORIGINS':'http://localhost:3000'})
        env.start(); self.addCleanup(env.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='readiness-')
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(isolated_database_url('sqlite:///'+(Path(self.temp.name)/'db.sqlite').as_posix()))
        self.addCleanup(self.app.state.engine.dispose)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_ready_is_anonymous_uncached_and_has_no_tenant_or_database_details(self):
        response = self.client.get('/api/v1/ready')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status':'ready'})
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('set-cookie', response.headers)

    def test_missing_migration_is_not_ready_and_does_not_repair_markers(self):
        with self.app.state.engine.begin() as db:
            db.execute(text('DELETE FROM schema_migrations WHERE version=:version'), {'version':VERSIONS[-1]})
        response = self.client.get('/api/v1/ready')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status':'unavailable', 'code':'MIGRATION_REQUIRED'})
        with self.app.state.engine.connect() as db:
            self.assertEqual(db.execute(text('SELECT count(*) FROM schema_migrations')).scalar_one(), len(VERSIONS)-1)
        self.assertEqual(self.client.get('/api/v1/health').json(), {'status':'ok'})

    def test_future_migration_is_not_ready(self):
        with self.app.state.engine.begin() as db:
            db.execute(text("INSERT INTO schema_migrations VALUES ('9999')"))
        self.assertEqual(self.client.get('/api/v1/ready').status_code, 503)

    def test_connection_and_pool_failures_are_sanitized_but_liveness_stays_up(self):
        faults = [OperationalError('private SQL', {'password':'private credential'}, Exception('private connection')),
                  TimeoutError('private pool connection')]
        for fault in faults:
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(fault=type(fault).__name__), \
                    patch.object(self.app.state.engine, 'connect', side_effect=fault), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                response = self.client.get('/api/v1/ready')
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {'status':'unavailable', 'code':'DATABASE_UNAVAILABLE'})
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(self.client.get('/api/v1/health').status_code, 200)
            self.assertNotIn('private', response.text+output.getvalue()+errors.getvalue())

    def test_missing_schema_table_is_503_not_an_uncaught_server_error(self):
        with self.app.state.engine.begin() as db:
            db.execute(text('DROP TABLE schema_migrations'))
        response = self.client.get('/api/v1/ready')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'DATABASE_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
