"""Password changes/recovery with real transactions and controlled issuance races."""
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from database_fixture import isolated_database_url

from apps.api import accounts, main as api, security
from apps.api.db import Audit, AuthSession, Job, Organization, RefreshToken, User


OLD = 'Synthetic-old-password-2026!'
NEW = 'Synthetic-new-password-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}


class PasswordSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_hash = security.password_hash(OLD)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'password.sqlite').as_posix())
        env = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
                                     'ALLOWED_ORIGINS': 'http://localhost:3000'})
        env.start()
        self.addCleanup(env.stop)
        self.app = api.create_app(self.url)
        self.addCleanup(self.app.state.engine.dispose)
        self.factory = self.app.state.sessions
        with self.factory() as db:
            db.add_all([Organization(id=org,name=f'{org} fixture',timezone='Asia/Qyzylorda',data_policy='synthetic_only',provenance='test_fixture') for org in ('A','B')])
            for identifier, org, role in [('target', 'A', 'manager'), ('peer', 'A', 'manager'),
                                           ('foreign', 'B', 'admin'), ('analyst', 'A', 'analyst'),
                                           ('warehouse', 'A', 'warehouse'), ('admin', 'A', 'admin')]:
                db.add(User(id=identifier, organization_id=org, email=identifier + '@fixture.invalid',
                            password_hash=self.old_hash, role=role, branch_ids=['1']))
            for identifier, actor, org, status in [('queued', 'target', 'A', 'queued'),
                                                   ('running', 'target', 'A', 'running'),
                                                   ('done', 'target', 'A', 'succeeded'),
                                                   ('peer-job', 'peer', 'A', 'queued'),
                                                   ('foreign-job', 'foreign', 'B', 'queued')]:
                db.add(Job(id=identifier, organization_id=org, branch_id='1', actor_id=actor,
                           kind='forecast', status=status, payload={}, snapshot={},
                           started_at=time.time() if status == 'running' else None,
                           result_id='retained-result' if status == 'succeeded' else None))
            db.commit()

    def client(self):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        return client

    def web(self, user='target', password=OLD):
        client = self.client()
        login = client.post('/api/v1/session/login', json={'email': user + '@fixture.invalid', 'password': password}, headers=ORIGIN)
        self.assertEqual(login.status_code, 200, login.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': login.json()['csrf_token']})
        return client

    def native(self, user='target'):
        client = self.client()
        login = client.post('/api/v1/auth/token', json={'email': user + '@fixture.invalid', 'password': OLD})
        self.assertEqual(login.status_code, 200, login.text)
        return client, login.json()

    def reset(self, **overrides):
        parameters = {'organization_id': 'A', 'user_id': 'target', 'new_password': NEW,
                      'operator_id': 'local-owner', 'reason': 'Fixture recovery approved by owner'}
        parameters.update(overrides)
        with self.factory() as db:
            result = accounts.reset_password(db, **parameters)
            db.commit()
            return result

    def password_events(self):
        with self.factory() as db:
            return list(db.scalars(select(Audit).where(Audit.action.in_(['account.password_changed', 'account.password_reset']))))

    def test_web_change_revokes_all_credentials_and_pending_jobs_only_for_target(self):
        current, second, peer, foreign = self.web(), self.web(), self.web('peer'), self.web('foreign')
        native, tokens = self.native()
        result = current.post('/api/v1/account/password', json={'current_password': OLD, 'new_password': NEW})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json(), {'status': 'password_changed', 'reauth_required': True})
        self.assertIn('Max-Age=0', result.headers['set-cookie'])
        self.assertIn('HttpOnly', result.headers['set-cookie'])
        self.assertIn('SameSite=lax', result.headers['set-cookie'])
        self.assertIn('Path=/api', result.headers['set-cookie'])
        self.assertEqual(current.get('/api/v1/session/me').status_code, 401)
        self.assertEqual(second.get('/api/v1/session/me').status_code, 401)
        self.assertEqual(native.get('/api/v1/session/me', headers={'Authorization': 'Bearer ' + tokens['access_token']}).status_code, 401)
        self.assertEqual(native.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code, 401)
        self.assertEqual(peer.get('/api/v1/session/me').status_code, 200)
        self.assertEqual(foreign.get('/api/v1/session/me').status_code, 200)
        with self.factory() as db:
            user = db.get(User, 'target')
            self.assertTrue(security.verify_password(NEW, user.password_hash))
            self.assertFalse(security.verify_password(OLD, user.password_hash))
            self.assertNotEqual(user.password_hash.split('$')[1], self.old_hash.split('$')[1])
            self.assertEqual((user.organization_id, user.role, user.branch_ids, user.active), ('A', 'manager', ['1'], True))
            self.assertTrue(all(session.revoked for session in db.scalars(select(AuthSession).where(AuthSession.user_id == 'target'))))
            self.assertTrue(all(token.revoked for token in db.scalars(select(RefreshToken).where(RefreshToken.user_id == 'target'))))
            for identifier in ('queued', 'running'):
                job = db.get(Job, identifier)
                self.assertEqual(job.status, 'failed')
                self.assertTrue(job.error.startswith('JOB_ACCESS_REVOKED:'))
                self.assertIsNone(job.result_id)
            self.assertEqual(db.get(Job, 'done').result_id, 'retained-result')
            for identifier in ('peer-job', 'foreign-job'):
                self.assertEqual(db.get(Job, identifier).status, 'queued')
            audits = list(db.scalars(select(Audit)))
            self.assertTrue(all(event.actor_id == 'target' for event in audits if event.action == 'job.cancelled'))
            persisted_details = json.dumps([event.details for event in audits])
            for secret in (OLD, NEW, user.password_hash, self.old_hash):
                self.assertNotIn(secret, persisted_details + result.text)
        events = self.password_events()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].action, events[0].actor_id, events[0].entity_id, events[0].organization_id), ('account.password_changed', 'target', 'target', 'A'))
        rejected = self.client().post('/api/v1/auth/token', json={'email': 'target@fixture.invalid', 'password': OLD})
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(self.web(password=NEW).get('/api/v1/session/me').status_code, 200)

    def test_native_change_is_available_to_every_active_role_without_origin(self):
        for role in ('admin', 'target', 'analyst', 'warehouse'):
            with self.subTest(user=role):
                client, tokens = self.native(role)
                response = client.post('/api/v1/account/password', json={'current_password': OLD, 'new_password': NEW},
                                       headers={'Authorization': 'Bearer ' + tokens['access_token']})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(client.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']}).status_code, 401)
                self.assertEqual(self.web(role, NEW).get('/api/v1/session/me').status_code, 200)

    def test_wrong_or_unchanged_password_has_no_credential_side_effect(self):
        client = self.web()
        for current_password, new_password, status, code in [('Incorrect-current-value', NEW, 400, 'CURRENT_PASSWORD_INVALID'), (OLD, OLD, 422, 'PASSWORD_UNCHANGED')]:
            with self.subTest(code=code), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                response = client.post('/api/v1/account/password', json={'current_password': current_password, 'new_password': new_password})
                self.assertEqual(response.status_code, status, response.text)
                self.assertEqual(response.json()['detail']['code'], code)
                for secret in (current_password, new_password):
                    self.assertNotIn(secret, response.text + stdout.getvalue() + stderr.getvalue())
        self.assertEqual(client.get('/api/v1/session/me').status_code, 200)
        with self.factory() as db:
            self.assertEqual(db.get(User, 'target').password_hash, self.old_hash)
            self.assertEqual(db.get(Job, 'queued').status, 'queued')
        self.assertEqual(self.password_events(), [])

    def test_sensitive_validation_does_not_echo_password_body_or_extra_fields(self):
        client = self.web()
        bodies = [
            {'current_password': OLD, 'new_password': 'shortsecret'},
            {'current_password': OLD, 'new_password': NEW * 100},
            {'current_password': OLD * 100, 'new_password': NEW},
            {'current_password': OLD, 'new_password': NEW, 'user_id': 'foreign'},
            {'new_password': NEW},
        ]
        for body in bodies:
            with self.subTest(fields=tuple(body)):
                response = client.post('/api/v1/account/password', json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['detail']['code'], 'PASSWORD_INVALID')
                for secret in (OLD, NEW, 'shortsecret'):
                    self.assertNotIn(secret, response.text)
        for route, body in [('session/login', {'email': 'target@fixture.invalid', 'password': OLD * 100}),
                            ('auth/token', {'email': 'target@fixture.invalid', 'password': OLD * 100}),
                            ('auth/refresh', {'refresh_token': NEW}),
                            ('users', {'email': 'new@fixture.invalid', 'password': 'shortsecret', 'role': 'analyst', 'branch_ids': ['1']})]:
            # The refresh token is valid length here; use a deliberately too short one.
            if route == 'auth/refresh':
                body['refresh_token'] = 'shortsecret'
            response = self.web('admin').post('/api/v1/' + route, json=body)
            self.assertEqual(response.status_code, 422, response.text)
            for secret in (OLD, NEW, 'shortsecret'):
                self.assertNotIn(secret, response.text)
        self.assertEqual(self.password_events(), [])

    def test_cookie_mutation_requires_auth_origin_and_csrf(self):
        body = {'current_password': OLD, 'new_password': NEW}
        self.assertEqual(self.client().post('/api/v1/account/password', json=body, headers=ORIGIN).status_code, 401)
        client = self.web()
        for headers in ({'Origin': 'https://other.invalid'}, {'X-CSRF-Token': 'wrong'}):
            self.assertEqual(client.post('/api/v1/account/password', json=body, headers=headers).status_code, 403)
        self.assertEqual(self.password_events(), [])

    def test_operator_reset_is_exact_scoped_and_does_not_reactivate_user(self):
        with self.assertRaises(accounts.CredentialError) as denied:
            self.reset(organization_id='B')
        self.assertEqual(denied.exception.code, 'ACCOUNT_NOT_FOUND')
        with self.factory() as db:
            db.get(User, 'target').active = False
            db.commit()
        self.assertEqual(self.reset(), {'status': 'password_changed', 'reauth_required': True})
        with self.factory() as db:
            user = db.get(User, 'target')
            self.assertFalse(user.active)
            self.assertEqual((user.role, user.branch_ids), ('manager', ['1']))
            self.assertTrue(security.verify_password(NEW, user.password_hash))
            self.assertEqual(db.get(User, 'foreign').password_hash, self.old_hash)
        event = self.password_events()[0]
        self.assertEqual((event.actor_id, event.action, event.organization_id, event.entity_id), ('operator:local-owner', 'account.password_reset', 'A', 'target'))
        self.assertEqual(event.details, {'operator_id': 'local-owner', 'reason': 'Fixture recovery approved by owner'})

    def test_operator_recovery_validates_secret_length_reason_identity_and_no_reuse(self):
        for override, code in [({'new_password': 'short'}, 'PASSWORD_INVALID'),
                               ({'new_password': 'x' * 1025}, 'PASSWORD_INVALID'),
                               ({'new_password': OLD}, 'PASSWORD_UNCHANGED'),
                               ({'operator_id': ''}, 'OPERATOR_INVALID'),
                               ({'operator_id': 'x' * 56}, 'OPERATOR_INVALID'),
                               ({'operator_id': NEW}, 'RECOVERY_METADATA_INVALID'),
                               ({'reason': 'Accidental password: ' + NEW}, 'RECOVERY_METADATA_INVALID'),
                               ({'reason': '  '}, 'REASON_REQUIRED')]:
            with self.subTest(code=code), self.assertRaises(accounts.CredentialError) as error:
                self.reset(**override)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn(NEW, str(error.exception))
        with self.factory() as db:
            self.assertEqual(db.get(User, 'target').password_hash, self.old_hash)
            self.assertEqual(db.get(Job, 'queued').status, 'queued')
        self.assertEqual(self.password_events(), [])

    def test_recovery_transaction_can_roll_back_hash_sessions_jobs_and_audit(self):
        client = self.web()
        with self.factory() as db:
            accounts.reset_password(db, organization_id='A', user_id='target', new_password=NEW,
                                    operator_id='local-owner', reason='Test rollback transaction')
            db.rollback()
        with self.factory() as db:
            self.assertEqual(db.get(User, 'target').password_hash, self.old_hash)
            self.assertEqual(db.get(Job, 'queued').status, 'queued')
            self.assertEqual(db.get(Job, 'running').status, 'running')
        self.assertEqual(client.get('/api/v1/session/me').status_code, 200)
        self.assertEqual(self.password_events(), [])

    def test_two_password_changes_using_old_credentials_have_one_winner(self):
        first, second = self.web(), self.web()
        def change(client, new_password):
            return client.post('/api/v1/account/password', json={'current_password': OLD, 'new_password': new_password})
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(change, first, NEW), pool.submit(change, second, NEW + '-other')]
            responses = [outcome.result(timeout=15) for outcome in outcomes]
        self.assertEqual(sorted(response.status_code for response in responses), [200, 401])
        self.assertEqual(len(self.password_events()), 1)

    def test_reset_waits_for_inflight_login_then_revokes_issued_session(self):
        verified, release = threading.Event(), threading.Event()
        def verify(candidate, encoded):
            verified.set()
            if not release.wait(5):
                raise AssertionError('Login test did not release verification')
            return security.verify_password(candidate, encoded)
        def login():
            with TestClient(self.app) as client:
                response = client.post('/api/v1/session/login', json={'email': 'target@fixture.invalid', 'password': OLD}, headers=ORIGIN)
                return response, client.cookies.get('asboljam_session')
        with patch.object(api, 'verify_password', side_effect=verify), ThreadPoolExecutor(max_workers=2) as pool:
            login_future = pool.submit(login)
            self.assertTrue(verified.wait(5))
            reset_future = pool.submit(self.reset)
            try:
                with self.assertRaises(TimeoutError):
                    reset_future.result(timeout=0.3)
            finally:
                release.set()
            login_response, cookie = login_future.result(timeout=10)
            reset_future.result(timeout=10)
        self.assertEqual(login_response.status_code, 200, login_response.text)
        client = self.client()
        client.cookies.set('asboljam_session', cookie)
        self.assertEqual(client.get('/api/v1/session/me').status_code, 401)
        self.assertEqual(self.client().post('/api/v1/auth/token', json={'email': 'target@fixture.invalid', 'password': OLD}).status_code, 401)

    def test_reset_waits_for_refresh_then_revokes_rotated_family(self):
        client, tokens = self.native()
        entered, release = threading.Event(), threading.Event()
        original_lock = api.lock_user
        def locked(db, user_id, organization_id=None):
            result = original_lock(db, user_id, organization_id)
            entered.set()
            if not release.wait(5):
                raise AssertionError('Refresh test did not release lock')
            return result
        with patch.object(api, 'lock_user', side_effect=locked), ThreadPoolExecutor(max_workers=2) as pool:
            refresh_future = pool.submit(client.post, '/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})
            self.assertTrue(entered.wait(5))
            reset_future = pool.submit(self.reset)
            try:
                with self.assertRaises(TimeoutError):
                    reset_future.result(timeout=0.3)
            finally:
                release.set()
            refreshed = refresh_future.result(timeout=10)
            reset_future.result(timeout=10)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        fresh = refreshed.json()
        self.assertEqual(client.get('/api/v1/session/me', headers={'Authorization': 'Bearer ' + fresh['access_token']}).status_code, 401)
        self.assertEqual(client.post('/api/v1/auth/refresh', json={'refresh_token': fresh['refresh_token']}).status_code, 401)

    def test_concurrent_refresh_reuse_still_revokes_winning_family(self):
        client, tokens = self.native()
        def refresh():
            with TestClient(self.app) as other:
                return other.post('/api/v1/auth/refresh', json={'refresh_token': tokens['refresh_token']})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(refresh) for _ in range(2)]
            responses = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted(response.status_code for response in responses), [200, 401])
        winner = next(response.json() for response in responses if response.status_code == 200)
        self.assertEqual(client.get('/api/v1/session/me', headers={'Authorization': 'Bearer ' + winner['access_token']}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
