"""Empty tenant bootstrap, suspension and authenticated transaction boundaries."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from database_fixture import isolated_database_url

from apps.api import main as api, security, tenants
from apps.api.db import Audit, AuthSession, Forecast, ImportBatch, Job, Organization, Plan, Record, RefreshToken, User
from apps.worker import main as worker


PASSWORD = 'Synthetic-tenant-password-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class TenantLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
                                     'ALLOWED_ORIGINS': 'http://localhost:3000'})
        env.start()
        self.addCleanup(env.stop)
        self.url = isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'tenants.sqlite').as_posix())
        self.app = api.create_app(self.url)
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        self.admin_ids = {}
        for org, policy in [('A', 'synthetic_only'), ('B', 'synthetic_only'), ('U', 'unconfigured')]:
            self.admin_ids[org] = self.bootstrap(org, data_policy=policy)['admin_user_id']

    def metadata(self, org='new', **overrides):
        data = dict(organization_id=org, name='Fixture ' + org, timezone='Asia/Qyzylorda',
                    currency='KZT', data_policy='unconfigured', email=org.lower() + '@fixture.invalid',
                    operator_id='fixture-owner', reason='Explicit synthetic test setup')
        data.update(overrides)
        return data

    def bootstrap(self, org='new', **overrides):
        with self.factory() as db:
            result = tenants.bootstrap_tenant(db, password=PASSWORD, **self.metadata(org, **overrides))
            db.commit()
            return result

    def status(self, org='A', status='suspended', expected_status='active'):
        with self.factory() as db:
            result = tenants.set_tenant_status(db, organization_id=org, status=status,
                expected_status=expected_status, operator_id='fixture-owner', reason='Explicit lifecycle verification')
            db.commit()
            return result

    def client(self):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        return client

    def login(self, org='A'):
        client = self.client()
        response = client.post('/api/v1/session/login', json={'email': org.lower() + '@fixture.invalid', 'password': PASSWORD}, headers=ORIGIN)
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': response.json()['csrf_token']})
        return client

    def branch(self, client, branch='1'):
        preview = client.post('/api/v1/imports/preview', json={'kind': 'branches',
            'csv_text': 'branch_id,branch_name,data_origin\n' + branch + ',Synthetic branch,SYNTHETIC\n'})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()['valid'])
        response = client.post('/api/v1/imports/' + preview.json()['id'] + '/commit')
        self.assertEqual(response.status_code, 200, response.text)

    def count(self, model):
        with self.factory() as db:
            return db.scalar(select(func.count()).select_from(model))

    def test_bootstrap_is_empty_then_first_branch_is_explicitly_imported(self):
        self.assertEqual(self.count(Record), 0)
        self.assertEqual(self.count(Forecast), 0)
        self.assertEqual(self.count(Job), 0)
        self.assertEqual(self.count(Plan), 0)
        client = self.login()
        settings = client.get('/api/v1/settings').json()
        self.assertEqual(settings['organization'], dict(id='A', name='Fixture A', timezone='Asia/Qyzylorda',
            currency='KZT', status='active', data_policy='synthetic_only', provenance='operator_bootstrap'))
        self.assertEqual(settings['onboarding'], {'branch_count': 0, 'can_import_branches': True, 'data_policy': 'synthetic_only'})
        self.assertEqual(settings['user']['branch_ids'], [])
        self.assertEqual(client.get('/api/v1/branches').json()['total'], 0)
        self.branch(client)
        self.assertEqual(client.get('/api/v1/session/me').json()['user']['branch_ids'], ['1'])
        self.assertEqual(client.get('/api/v1/settings').json()['onboarding']['branch_count'], 1)
        self.assertEqual(client.get('/api/v1/dashboard?branch_id=1').status_code, 200)
        self.assertEqual(self.login('B').get('/api/v1/branches').json()['total'], 0)
        self.assertEqual(self.count(Record), 1)

    def test_unconfigured_can_manage_identity_but_all_operational_routes_are_denied(self):
        client = self.login('U')
        settings = client.get('/api/v1/settings').json()
        self.assertEqual(settings['onboarding'], {'branch_count': 0, 'can_import_branches': False, 'data_policy': 'unconfigured'})
        self.assertIsNone(settings['data_origin'])
        self.assertIsNone(settings['scenario_date'])
        for path in ('users', 'audit', 'imports/template/branches', 'session/me'):
            self.assertEqual(client.get('/api/v1/' + path).status_code, 200)
        paths = ('branches', 'meals', 'sales', 'inventory', 'recipes', 'suppliers', 'supplier_offers',
                 'calendar', 'forecasts', 'plans', 'runs/missing', 'exports/sales',
                 'dashboard?branch_id=1', 'reports?branch_id=1', 'plans/missing/export')
        for path in paths:
            with self.subTest(path=path):
                response = client.get('/api/v1/' + path)
                self.assertEqual(response.status_code, 403, response.text)
                self.assertEqual(response.json()['detail']['code'], 'TENANT_DATA_POLICY_REQUIRED')
        for path, body in [('imports/preview', {'kind': 'branches', 'csv_text': 'branch_id,branch_name,data_origin\n1,x,SYNTHETIC\n'}),
                           ('imports/missing/commit', None), ('forecasts', {'branch_id': '1'}),
                           ('procurement', {'branch_id': '1', 'forecast_id': 'missing', 'budget': '0'})]:
            self.assertEqual(client.post('/api/v1/' + path, json=body).status_code, 403)
        created = client.post('/api/v1/users', json={'email': 'empty-analyst@fixture.invalid', 'password': PASSWORD,
                                                   'role': 'analyst', 'branch_ids': []})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()['branch_ids'], [])
        changed = client.post('/api/v1/account/password', json={'current_password': PASSWORD, 'new_password': PASSWORD + '-new'})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(self.count(Record), 0)
        self.assertEqual(self.count(ImportBatch), 0)

    def test_bootstrap_rejects_duplicate_email_existing_or_orphaned_organization(self):
        before = {model: self.count(model) for model in (Organization, User, Audit)}
        for org, options, code in [('A', {}, 'ORGANIZATION_EXISTS'), ('unused', {'email': 'A@fixture.invalid'}, 'EMAIL_EXISTS')]:
            with self.subTest(code=code), self.assertRaises(tenants.TenantError) as error:
                self.bootstrap(org, **options)
            self.assertEqual(error.exception.code, code)
        for model, count in before.items():
            self.assertEqual(self.count(model), count)
        with self.factory() as db:
            db.add(User(id='orphan', organization_id='orphaned', email='orphan@fixture.invalid',
                        password_hash='unused', role='manager', branch_ids=[]))
            db.commit()
        with self.assertRaises(tenants.TenantError) as error:
            self.bootstrap('orphaned')
        self.assertEqual(error.exception.code, 'ORGANIZATION_ORPHANED')
        with self.factory() as db:
            self.assertIsNone(db.get(Organization, 'orphaned'))

    def test_concurrent_bootstrap_has_one_complete_winner_without_orphan_users(self):
        rendezvous = threading.Barrier(2)
        def hash_after_preflight(password):
            rendezvous.wait(timeout=5)
            return security.password_hash(password)
        def create(email):
            try:
                return self.bootstrap('concurrent', email=email)
            except tenants.TenantError as exc:
                return exc.code
        with patch.object(tenants, 'password_hash', side_effect=hash_after_preflight), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, email) for email in ('first@fixture.invalid', 'second@fixture.invalid')]
            outcomes = [future.result(timeout=15) for future in futures]
        self.assertEqual(sum(isinstance(outcome, dict) for outcome in outcomes), 1)
        self.assertIn('BOOTSTRAP_CONFLICT', outcomes)
        with self.factory() as db:
            self.assertIsNotNone(db.get(Organization, 'concurrent'))
            self.assertEqual(len(list(db.scalars(select(User).where(User.organization_id == 'concurrent')))), 1)
            self.assertEqual(len(list(db.scalars(select(Audit).where(Audit.organization_id == 'concurrent')))), 1)

    def test_invalid_metadata_and_secret_in_metadata_do_not_write_any_rows(self):
        before = {model: self.count(model) for model in (Organization, User, Audit)}
        cases = [{'organization_id': '../bad'}, {'name': '  '}, {'timezone': 'Missing/Timezone'},
                 {'currency': 'USD'}, {'data_policy': 'real'}, {'email': 'invalid'},
                 {'operator_id': 'with spaces'}, {'reason': ' '}, {'name': PASSWORD}]
        for changes in cases:
            values = self.metadata()
            values.update(changes)
            with self.subTest(fields=tuple(changes)), self.factory() as db, self.assertRaises(tenants.TenantError) as error:
                tenants.bootstrap_tenant(db, password=PASSWORD, **values)
            self.assertNotIn(PASSWORD, str(error.exception))
        for model, count in before.items():
            self.assertEqual(self.count(model), count)

    def test_bootstrap_and_suspend_obey_caller_rollback(self):
        with self.factory() as db:
            tenants.bootstrap_tenant(db, password=PASSWORD, **self.metadata())
            db.rollback()
        with self.factory() as db:
            self.assertIsNone(db.get(Organization, 'new'))
            self.assertIsNone(db.scalar(select(User).where(User.email == 'new@fixture.invalid')))
        client = self.login()
        with self.factory() as db:
            tenants.set_tenant_status(db, organization_id='A', status='suspended', expected_status='active',
                operator_id='fixture-owner', reason='Verify complete rollback')
            db.rollback()
        self.assertEqual(client.get('/api/v1/session/me').status_code, 200)
        self.assertEqual(client.get('/api/v1/settings').json()['organization']['status'], 'active')

    def test_suspend_revokes_whole_tenant_and_resume_never_resurrects_old_work(self):
        client, other = self.login(), self.login('B')
        native = self.client().post('/api/v1/auth/token', json={'email': 'a@fixture.invalid', 'password': PASSWORD}).json()
        with self.factory() as db:
            for identifier, org, actor, status in [('queued', 'A', self.admin_ids['A'], 'queued'),
                    ('running', 'A', self.admin_ids['A'], 'running'), ('done', 'A', self.admin_ids['A'], 'succeeded'),
                    ('orphan-job', 'A', 'missing-user', 'queued'), ('other', 'B', self.admin_ids['B'], 'queued')]:
                db.add(Job(id=identifier, organization_id=org, branch_id='1', actor_id=actor,
                    kind='forecast', status=status, payload={}, snapshot={},
                    result_id='saved' if status == 'succeeded' else None))
            db.commit()
        self.status()
        self.assertEqual(client.get('/api/v1/session/me').status_code, 401)
        self.assertEqual(other.get('/api/v1/session/me').status_code, 200)
        self.assertEqual(self.client().post('/api/v1/auth/token', json={'email': 'a@fixture.invalid', 'password': PASSWORD}).status_code, 401)
        self.assertEqual(self.client().post('/api/v1/auth/refresh', json={'refresh_token': native['refresh_token']}).status_code, 401)
        with self.factory() as db:
            for identifier in ('queued', 'running', 'orphan-job'):
                self.assertEqual(db.get(Job, identifier).status, 'failed')
                self.assertIsNone(db.get(Job, identifier).result_id)
            self.assertEqual(db.get(Job, 'done').result_id, 'saved')
            self.assertEqual(db.get(Job, 'other').status, 'queued')
            events = list(db.scalars(select(Audit).where(Audit.action == 'tenant.suspended')))
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].actor_id, 'operator:fixture-owner')
            self.assertEqual(events[0].details['previous_status'], 'active')
        self.status(status='active', expected_status='suspended')
        self.assertEqual(client.get('/api/v1/session/me').status_code, 401)
        self.assertEqual(self.client().post('/api/v1/auth/refresh', json={'refresh_token': native['refresh_token']}).status_code, 401)
        self.assertEqual(self.login().get('/api/v1/settings').status_code, 200)
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'queued').status, 'failed')

    def test_missing_tenant_fails_login_current_refresh_and_does_not_leak_existence(self):
        with self.factory() as db:
            db.add(User(id='orphan', organization_id='missing', email='missing@fixture.invalid',
                password_hash=security.password_hash(PASSWORD), role='admin', branch_ids=[]))
            db.add(AuthSession(id='orphan-session', user_id='orphan', token_hash=security.token_hash('orphan-access'),
                              csrf_token='unused', kind='native', expires_at=time.time() + 300))
            db.add(RefreshToken(token_hash=security.token_hash('orphan-refresh-token-123456'), user_id='orphan',
                               family_id='orphan-family', expires_at=time.time() + 300))
            db.commit()
        client = self.client()
        self.assertEqual(client.get('/api/v1/settings', headers={'Authorization': 'Bearer orphan-access'}).status_code, 401)
        login = client.post('/api/v1/auth/token', json={'email': 'missing@fixture.invalid', 'password': PASSWORD})
        self.assertEqual(login.status_code, 401)
        self.assertEqual(login.json()['detail']['code'], 'INVALID_CREDENTIALS')
        self.assertEqual(client.post('/api/v1/auth/refresh', json={'refresh_token': 'orphan-refresh-token-123456'}).status_code, 401)

    def test_status_requires_expected_value_and_retains_unknown_legacy_metadata(self):
        with self.assertRaises(tenants.TenantError) as error:
            self.status(expected_status='suspended')
        self.assertEqual(error.exception.code, 'STALE_STATUS')
        with self.factory() as db:
            organization = db.get(Organization, 'A')
            organization.name, organization.timezone, organization.provenance = None, None, 'legacy_migration'
            db.commit()
        with patch.dict(os.environ, {'ORGANIZATION_NAME': 'Wrong global name'}):
            settings = self.login().get('/api/v1/settings').json()
        self.assertIsNone(settings['organization']['name'])
        self.assertIsNone(settings['timezone'])
        self.assertEqual(settings['currency'], 'KZT')

    def test_suspension_after_rate_limit_commit_prevents_mutation(self):
        client = self.login()
        original_lock = api.lock_user
        fired = False
        def suspend_before_revalidation(db, user_id, organization_id=None):
            nonlocal fired
            if not fired:
                fired = True
                self.status()
            return original_lock(db, user_id, organization_id)
        with patch.object(api, 'lock_user', side_effect=suspend_before_revalidation):
            response = client.post('/api/v1/imports/preview', json={'kind': 'branches',
                'csv_text': 'branch_id,branch_name,data_origin\n1,x,SYNTHETIC\n'})
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.count(ImportBatch), 0)
        self.assertEqual(self.count(Record), 0)

    def test_inflight_login_serializes_with_suspension_and_session_is_revoked(self):
        entered, release = threading.Event(), threading.Event()
        def verify(candidate, encoded):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Test did not release login')
            return security.verify_password(candidate, encoded)
        client = self.client()
        with patch.object(api, 'verify_password', side_effect=verify), ThreadPoolExecutor(max_workers=2) as pool:
            login = pool.submit(client.post, '/api/v1/session/login', json={'email': 'a@fixture.invalid', 'password': PASSWORD}, headers=ORIGIN)
            self.assertTrue(entered.wait(5))
            suspension = pool.submit(self.status)
            try:
                with self.assertRaises(TimeoutError):
                    suspension.result(timeout=0.3)
            finally:
                release.set()
            self.assertEqual(login.result(timeout=10).status_code, 200)
            suspension.result(timeout=10)
        self.assertEqual(client.get('/api/v1/session/me').status_code, 401)

    def test_inflight_refresh_serializes_with_suspension_and_new_tokens_are_revoked(self):
        client = self.client()
        tokens = client.post('/api/v1/auth/token', json={'email': 'a@fixture.invalid', 'password': PASSWORD}).json()
        entered, release = threading.Event(), threading.Event()
        original_lock = api.lock_user
        def lock(db, user_id, organization_id=None):
            user = original_lock(db, user_id, organization_id)
            entered.set()
            if not release.wait(5):
                raise AssertionError('Test did not release refresh')
            return user
        with patch.object(api, 'lock_user', side_effect=lock), ThreadPoolExecutor(max_workers=2) as pool:
            refresh = pool.submit(client.post, '/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})
            self.assertTrue(entered.wait(5))
            suspension = pool.submit(self.status)
            try:
                with self.assertRaises(TimeoutError):
                    suspension.result(timeout=0.3)
            finally:
                release.set()
            response = refresh.result(timeout=10)
            suspension.result(timeout=10)
        self.assertEqual(response.status_code, 200, response.text)
        new_tokens = response.json()
        self.assertEqual(client.get('/api/v1/settings', headers={'Authorization': 'Bearer ' + new_tokens['access_token']}).status_code, 401)
        self.status(status='active', expected_status='suspended')
        self.assertEqual(client.post('/api/v1/auth/refresh', json={'refresh_token': new_tokens['refresh_token']}).status_code, 401)

    def test_worker_denies_unconfigured_and_missing_tenants_before_compute(self):
        for org in ('U', 'missing'):
            with self.subTest(organization=org):
                with self.factory() as db:
                    db.add(Job(id='job-' + org, organization_id=org, branch_id='1',
                        actor_id=self.admin_ids.get(org, 'missing-user'), kind='forecast', payload={}, snapshot={}))
                    db.commit()
                with patch.object(worker, 'forecast') as compute:
                    self.assertTrue(worker.run_once(self.factory))
                compute.assert_not_called()
                with self.factory() as db:
                    job = db.get(Job, 'job-' + org)
                    self.assertEqual(job.status, 'failed')
                    self.assertTrue(job.error.startswith('JOB_ACCESS_REVOKED'))

    def test_suspended_worker_never_publishes_or_restores_cancelled_result(self):
        client = self.login()
        self.branch(client)
        result = {'branch_id': '1', 'data_origin': 'SYNTHETIC', 'target_date': '2026-01-01',
                  'predictions': [{'meal_id': '1', 'point_forecast': 2}]}
        with self.factory() as db:
            db.add(Job(id='job', organization_id='A', branch_id='1', actor_id=self.admin_ids['A'], kind='forecast',
                payload={'branch_id': '1', 'origin': '2025-12-31', 'model': 'seasonal_naive_7'},
                snapshot={'sales': [{'branch_id': '1', 'meal_id': '1', 'date': '2025-12-31', 'units_sold': 2, 'data_origin': 'SYNTHETIC'}],
                          'meals': [{'meal_id': '1', 'meal_name': 'Fixture', 'data_origin': 'SYNTHETIC'}]}))
            db.commit()
        def calculate(*args):
            self.status()
            self.status(status='active', expected_status='suspended')
            return deepcopy(result)
        with patch.object(worker, 'forecast', side_effect=calculate):
            self.assertTrue(worker.run_once(self.factory))
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'failed')
            self.assertIsNone(db.get(Forecast, 'job'))
            self.assertEqual(list(db.scalars(select(Audit).where(Audit.action == 'forecast.succeeded'))), [])


if __name__ == '__main__':
    unittest.main()
