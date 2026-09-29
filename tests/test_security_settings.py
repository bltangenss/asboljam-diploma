"""Transport settings wiring on an isolated SQLite fixture, not a live TLS deployment."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from apps.api import main as api
from apps.api.config import ConfigurationError
from apps.api.db import User, make_engine
from apps.api.security import password_hash
from apps.worker import main as worker
from scripts import seed_demo


class SettingsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = 'sqlite:///' + (Path(self.temp.name) / 'test.sqlite').as_posix()
        env = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
                                    'ALLOWED_ORIGINS': 'http://localhost:3000'})
        env.start()
        self.addCleanup(env.stop)

    def test_unsafe_production_fails_before_database_is_opened(self):
        with patch.dict(os.environ, {'ASBOLJAM_ENV': 'production'}), patch.object(api, 'make_engine') as database:
            with self.assertRaises(ConfigurationError):
                api.create_app(self.url)
        database.assert_not_called()

    def test_bad_content_length_is_rejected_with_security_headers(self):
        app = api.create_app(self.url)
        self.addCleanup(app.state.engine.dispose)
        with TestClient(app) as client:
            for length, status in [('not-a-size', 400), ('-1', 400), ('999999999999999999999999', 400), (str(23 * 1024 * 1024), 413)]:
                with self.subTest(length=length):
                    response = client.post('/api/v1/session/login', content='{}', headers={'Content-Length': length})
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertNotIn('Strict-Transport-Security', response.headers)

    def test_secure_cookie_and_headers_reach_http_responses(self):
        # Only DB selection is stubbed: exercise actual routes/middleware with a local store.
        environment = {'ASBOLJAM_ENV': 'production', 'ALLOWED_ORIGINS': 'https://app.example.org',
                       'COOKIE_SECURE': 'true', 'DEMO_PASSWORD': '',
                       'DATABASE_URL': 'postgresql+psycopg://operator@database/asboljam'}
        engine = make_engine(self.url)
        self.addCleanup(engine.dispose)
        with patch.dict(os.environ, environment), patch.object(api, 'make_engine', return_value=engine):
            app = api.create_app()
        password = 'Synthetic-cookie-fixture-2026!'
        with app.state.sessions() as db:
            db.add(User(id='fixture', organization_id='A', email='cookie@fixture.invalid',
                        password_hash=password_hash(password), role='analyst', branch_ids=['1']))
            db.commit()
        with TestClient(app, base_url='https://app.example.org') as client:
            login = client.post('/api/v1/session/login', json={'email': 'cookie@fixture.invalid', 'password': password},
                                headers={'Origin': 'https://app.example.org'})
            self.assertEqual(login.status_code, 200, login.text)
            self.assertIn('Secure', login.headers['set-cookie'])
            self.assertIn('HttpOnly', login.headers['set-cookie'])
            self.assertIn('SameSite=lax', login.headers['set-cookie'])
            self.assertEqual(login.headers['Strict-Transport-Security'], 'max-age=31536000')
            self.assertEqual(login.headers['Access-Control-Allow-Origin'], 'https://app.example.org')
            self.assertEqual(client.get('/api/v1/session/me').status_code, 200)
            denied = client.post('/api/v1/session/login', json={'email': 'cookie@fixture.invalid', 'password': password},
                                 headers={'Origin': 'https://other.example.org'})
            self.assertEqual(denied.status_code, 403)
            self.assertNotIn('Access-Control-Allow-Origin', denied.headers)
            logout = client.post('/api/v1/session/logout', headers={
                'Origin': 'https://app.example.org', 'X-CSRF-Token': login.json()['csrf_token']})
            self.assertEqual(logout.status_code, 200)
            self.assertIn('Secure', logout.headers['set-cookie'])
            self.assertIn('HttpOnly', logout.headers['set-cookie'])
            self.assertEqual(client.get('/api/v1/session/me').status_code, 401)

    def test_demo_seed_guard_refuses_before_calling_database_factory(self):
        factory = Mock()
        with patch.dict(os.environ, {'ASBOLJAM_ENV': 'production'}):
            with self.assertRaisesRegex(ValueError, 'local mode'):
                seed_demo.seed(factory, 'not-a-real-password')
        factory.assert_not_called()

    def test_worker_refuses_unsafe_configuration_before_database(self):
        with patch.dict(os.environ, {'ASBOLJAM_ENV': 'production'}), patch('sys.argv', ['worker', '--once']), patch.object(worker, 'make_engine') as database:
            with self.assertRaises(ConfigurationError):
                worker.main()
        database.assert_not_called()


if __name__ == '__main__':
    unittest.main()
