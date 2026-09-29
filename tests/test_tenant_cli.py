"""Operator boundary: explicit store, hidden input and empty tenant creation."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import select, text

from apps.api.db import Audit, Organization, Record, User, make_engine, migrate, sessions
from apps.api.security import verify_password
from scripts import manage_tenant, seed_demo


PASSWORD = 'Synthetic-bootstrap-fixture-2026!'


class TenantCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tenant.sqlite'
        self.url = 'sqlite:///' + self.path.as_posix()
        environment = patch.dict(os.environ, {
            'DATABASE_URL': self.url, 'ASBOLJAM_ENV': 'local', 'COOKIE_SECURE': 'false',
            'ALLOWED_ORIGINS': 'http://localhost:3000', 'DEMO_PASSWORD': '',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.engine = make_engine(self.url)
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.factory = sessions(self.engine)
        self.args = ['bootstrap', '--organization-id', 'empty_fixture', '--name', 'Empty fixture',
                     '--timezone', 'Asia/Qyzylorda', '--admin-email', 'owner@fixture.invalid',
                     '--operator-id', 'support_1', '--reason', 'Prepare isolated workspace']

    def invoke(self, args=None, passwords=None, interactive=True):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                patch.object(manage_tenant.sys.stdin, 'isatty', return_value=interactive), \
                patch.object(manage_tenant.getpass, 'getpass', side_effect=passwords or []) as prompt:
            try:
                result = manage_tenant.main(self.args if args is None else args)
            except SystemExit as exc:
                result = exc.code
        captured = out.getvalue() + err.getvalue()
        self.assertNotIn(PASSWORD, captured)
        return result, captured, prompt.call_count

    def assert_empty(self):
        with self.factory() as db:
            for model in (Organization, User, Record, Audit):
                self.assertFalse(list(db.scalars(select(model))), model.__name__)

    def create(self):
        code, output, prompts = self.invoke(self.args + ['--apply'], [PASSWORD, PASSWORD])
        self.assertEqual((code, prompts), (0, 2), output)

    def test_default_preflight_neither_writes_nor_prompts(self):
        code, output, prompts = self.invoke()
        self.assertEqual((code, prompts), (0, 0), output)
        self.assertIn('Preflight only', output)
        self.assert_empty()

    def test_bootstrap_creates_only_empty_organization_and_hashed_admin(self):
        self.create()
        with self.factory() as db:
            organization = db.get(Organization, 'empty_fixture')
            self.assertEqual((organization.data_policy, organization.status), ('unconfigured', 'active'))
            self.assertEqual(organization.timezone, 'Asia/Qyzylorda')
            user = db.scalar(select(User))
            self.assertEqual((user.role, user.branch_ids), ('admin', []))
            self.assertTrue(verify_password(PASSWORD, user.password_hash))
            self.assertNotEqual(user.password_hash, PASSWORD)
            self.assertFalse(list(db.scalars(select(Record))))
            events = list(db.scalars(select(Audit)))
            self.assertEqual(len(events), 1)
            self.assertEqual((events[0].action, events[0].actor_id), ('tenant.created', 'operator:support_1'))
            self.assertNotIn(PASSWORD, str(events[0].details))
        code, output, prompts = self.invoke(self.args + ['--apply'], [PASSWORD, PASSWORD])
        self.assertEqual((code, prompts), (2, 0), output)
        with self.factory() as db:
            self.assertEqual(len(list(db.scalars(select(User)))), 1)

    def test_password_mismatch_weak_or_noninteractive_input_never_creates_tenant(self):
        for passwords, interactive in (([PASSWORD, 'mismatch'], True), (['short', 'short'], True),
                                       ([PASSWORD, PASSWORD], False)):
            with self.subTest(interactive=interactive, length=len(passwords[0])):
                code, _, _ = self.invoke(self.args + ['--apply'], passwords, interactive)
                self.assertEqual(code, 2)
                self.assert_empty()

    def test_hidden_input_failure_never_creates_tenant(self):
        for error in (manage_tenant.getpass.GetPassWarning('input unavailable'), EOFError(), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                code, _, prompts = self.invoke(self.args + ['--apply'], [error])
                self.assertEqual((code, prompts), (2, 1))
                self.assert_empty()

    def test_no_implicit_or_new_database(self):
        for url in ('', 'sqlite:///:memory:', 'sqlite:///' + (Path(self.temp.name) / 'missing.sqlite').as_posix()):
            with self.subTest(url=url), patch.dict(os.environ, {'DATABASE_URL': url}), \
                    patch.object(manage_tenant, 'make_engine') as engine:
                code, _, prompts = self.invoke()
                self.assertEqual((code, prompts), (2, 0))
                engine.assert_not_called()
        self.assertFalse((Path(self.temp.name) / 'missing.sqlite').exists())
        self.assert_empty()

    def test_bad_arguments_do_not_echo_password(self):
        code, output, prompts = self.invoke(self.args + ['--password', PASSWORD])
        self.assertEqual((code, prompts), (2, 0))
        self.assertIn('Invalid arguments', output)
        self.assert_empty()

    def test_unapplied_or_future_schema_never_prompts_or_mutates(self):
        for query, undo in [
            ("DELETE FROM schema_migrations WHERE version='0002'", "INSERT INTO schema_migrations VALUES ('0002')"),
            ("INSERT INTO schema_migrations VALUES ('0003')", "DELETE FROM schema_migrations WHERE version='0003'")]:
            with self.subTest(query=query):
                with self.engine.begin() as connection:
                    connection.execute(text(query))
                code, output, prompts = self.invoke(self.args + ['--apply'], [PASSWORD, PASSWORD])
                self.assertEqual((code, prompts), (2, 0))
                self.assertIn('MIGRATION_REQUIRED', output)
                self.assert_empty()
                with self.engine.begin() as connection:
                    connection.execute(text(undo))

    def test_production_configuration_checked_before_database(self):
        with patch.dict(os.environ, {'ASBOLJAM_ENV': 'production'}), \
                patch.object(manage_tenant, 'make_engine') as engine:
            code, _, _ = self.invoke()
        self.assertEqual(code, 2)
        engine.assert_not_called()
        self.assert_empty()

    def test_status_requires_expected_value_and_explicit_apply(self):
        self.create()
        args = ['status', '--organization-id', 'empty_fixture', '--status', 'suspended',
                '--expected-status', 'active', '--operator-id', 'support_1', '--reason', 'Fixture suspension']
        self.assertEqual(self.invoke(args)[0], 0)
        with self.factory() as db:
            self.assertEqual(db.get(Organization, 'empty_fixture').status, 'active')
            self.assertEqual(len(list(db.scalars(select(Audit)))), 1)
        self.assertEqual(self.invoke(args + ['--apply'])[0], 0)
        self.assertEqual(self.invoke(args + ['--apply'])[0], 2)
        with self.factory() as db:
            self.assertEqual(db.get(Organization, 'empty_fixture').status, 'suspended')
            self.assertEqual(len([a for a in db.scalars(select(Audit)) if a.action == 'tenant.suspended']), 1)

    def test_demo_seed_refuses_unconfigured_or_suspended_workspace(self):
        self.create()
        for policy, status in [('unconfigured', 'active'), ('synthetic_only', 'suspended')]:
            with self.subTest(policy=policy, status=status):
                with self.factory() as db:
                    organization = db.get(Organization, 'empty_fixture')
                    organization.data_policy, organization.status = policy, status
                    db.commit()
                with patch.object(seed_demo, 'parse_csv') as parse:
                    with self.assertRaisesRegex(ValueError, 'active synthetic-only'):
                        seed_demo.seed(self.factory, PASSWORD, organization_id='empty_fixture')
                    parse.assert_not_called()
                with self.factory() as db:
                    self.assertFalse(list(db.scalars(select(Record))))
                    self.assertEqual(len(list(db.scalars(select(User)))), 1)


if __name__ == '__main__':
    unittest.main()
