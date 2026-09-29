"""Operator recovery CLI against isolated stores; hidden terminal input is stubbed."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from sqlalchemy import select

from apps.api.db import Audit, AuthSession, Job, RefreshToken, User, make_engine, migrate, sessions
from apps.api.security import password_hash, verify_password
from scripts import manage_password


OLD_PASSWORD = 'Synthetic-recovery-old-2026!'
NEW_PASSWORD = 'Synthetic-recovery-new-2026!'


class PasswordCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'recovery.sqlite'
        self.url = 'sqlite:///' + self.path.as_posix()
        self.environment = patch.dict(os.environ, {
            'DATABASE_URL': self.url, 'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
            'ALLOWED_ORIGINS': 'http://localhost:3000', 'DEMO_PASSWORD': '',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.engine = make_engine(self.url)
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.factory = sessions(self.engine)
        with self.factory() as db:
            for user_id, org in [('target', 'A'), ('other', 'B')]:
                db.add(User(id=user_id, organization_id=org, email=f'{user_id}@fixture.invalid',
                            password_hash=password_hash(OLD_PASSWORD), role='admin', branch_ids=['1']))
                db.add(AuthSession(id=user_id, user_id=user_id, token_hash=user_id, csrf_token='fixture',
                                   expires_at=time.time() + 3600))
                db.add(RefreshToken(token_hash=user_id, user_id=user_id, family_id=user_id,
                                    expires_at=time.time() + 3600))
                db.add(Job(id=user_id, organization_id=org, branch_id='1', actor_id=user_id,
                           kind='forecast', payload={}, snapshot={}))
            db.commit()
        self.args = ['--organization-id', 'A', '--user-id', 'target']
        self.apply_args = self.args + ['--apply', '--operator-id', 'support_1', '--reason', 'Verified owner recovery']

    def invoke(self, args=None, passwords=None, interactive=True):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch.object(manage_password.sys.stdin, 'isatty', return_value=interactive), \
                patch.object(manage_password.getpass, 'getpass', side_effect=passwords or []) as prompt:
            try:
                result = manage_password.main(self.args if args is None else args)
            except SystemExit as exc:
                result = exc.code
        captured = out.getvalue() + err.getvalue()
        for secret in (OLD_PASSWORD, NEW_PASSWORD):
            self.assertNotIn(secret, captured)
        return result, captured, prompt.call_count

    def assert_original(self):
        with self.factory() as db:
            self.assertTrue(verify_password(OLD_PASSWORD, db.get(User, 'target').password_hash))
            self.assertFalse(db.get(AuthSession, 'target').revoked)
            self.assertEqual(db.get(Job, 'target').status, 'queued')
            self.assertFalse(list(db.scalars(select(Audit))))

    def test_default_preflight_has_no_writes_or_password_prompts(self):
        code, output, prompts = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(prompts, 0)
        self.assertIn('Preflight only', output)
        self.assertIn('"pending_jobs": 1', output)
        self.assertNotIn('fixture.invalid', output)
        self.assert_original()

    def test_hidden_reset_updates_only_exact_account_and_records_operator(self):
        code, output, prompts = self.invoke(self.apply_args, [NEW_PASSWORD, NEW_PASSWORD])
        self.assertEqual(code, 0, output)
        self.assertEqual(prompts, 2)
        with self.factory() as db:
            self.assertTrue(verify_password(NEW_PASSWORD, db.get(User, 'target').password_hash))
            self.assertTrue(db.get(AuthSession, 'target').revoked)
            self.assertTrue(db.get(RefreshToken, 'target').revoked)
            self.assertEqual(db.get(Job, 'target').status, 'failed')
            self.assertTrue(verify_password(OLD_PASSWORD, db.get(User, 'other').password_hash))
            self.assertFalse(db.get(AuthSession, 'other').revoked)
            self.assertEqual(db.get(Job, 'other').status, 'queued')
            events = list(db.scalars(select(Audit)))
            self.assertTrue(events)
            self.assertTrue(all(event.organization_id == 'A' for event in events))
            self.assertTrue(any(event.actor_id == 'operator:support_1' for event in events))
            self.assertNotIn(NEW_PASSWORD, str([event.details for event in events]))

    def test_wrong_tenant_never_prompts_or_mutates(self):
        code, _, prompts = self.invoke(['--organization-id', 'B', '--user-id', 'target'])
        self.assertEqual((code, prompts), (2, 0))
        self.assert_original()

    def test_mismatch_and_weak_password_leave_state_unchanged(self):
        for passwords in ([NEW_PASSWORD, OLD_PASSWORD], ['short', 'short']):
            with self.subTest(kind=len(passwords[0])):
                code, _, _ = self.invoke(self.apply_args, passwords)
                self.assertEqual(code, 2)
                self.assert_original()

    def test_noninteractive_input_is_rejected(self):
        code, _, prompts = self.invoke(self.apply_args, [NEW_PASSWORD, NEW_PASSWORD], interactive=False)
        self.assertEqual((code, prompts), (2, 0))
        self.assert_original()

    def test_echo_fallback_and_cancelled_prompt_abort(self):
        for error in (manage_password.getpass.GetPassWarning('hidden input unavailable'), EOFError(), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                code, _, prompts = self.invoke(self.apply_args, [error])
                self.assertEqual((code, prompts), (2, 1))
                self.assert_original()

    def test_missing_database_url_does_not_use_demo_default(self):
        with patch.dict(os.environ, {'DATABASE_URL': ''}), patch.object(manage_password, 'make_engine') as engine:
            code, _, prompts = self.invoke()
        self.assertEqual((code, prompts), (2, 0))
        engine.assert_not_called()

    def test_missing_sqlite_file_is_not_created(self):
        missing = Path(self.temp.name) / 'mistyped.sqlite'
        with patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///' + missing.as_posix()}):
            code, _, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertFalse(missing.exists())

    def test_invalid_production_settings_do_not_open_database(self):
        with patch.dict(os.environ, {'ASBOLJAM_ENV': 'production'}), patch.object(manage_password, 'make_engine') as engine:
            code, _, _ = self.invoke()
        self.assertEqual(code, 2)
        engine.assert_not_called()

    def test_arguments_cannot_accept_or_echo_password(self):
        for args in (self.args + ['--password', NEW_PASSWORD], self.args + ['--apply']):
            code, output, prompts = self.invoke(args)
            self.assertEqual((code, prompts), (2, 0))
            self.assertIn('Invalid arguments', output)
        self.assert_original()


if __name__ == '__main__':
    unittest.main()
