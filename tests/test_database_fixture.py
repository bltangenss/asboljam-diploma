"""The opt-in PostgreSQL fixture must not accidentally target an ordinary database."""
import os
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import make_url

from database_fixture import isolated_database_url


class DatabaseFixtureTests(unittest.TestCase):
    def test_no_opt_in_keeps_sqlite_without_connecting(self):
        with patch.dict(os.environ, {}, clear=True), patch('database_fixture.create_engine') as connect:
            self.assertEqual(isolated_database_url('sqlite:///fixture.sqlite'), 'sqlite:///fixture.sqlite')
        connect.assert_not_called()

    def test_invalid_or_existing_database_names_fail_before_connecting(self):
        for value in ('', 'sqlite:///:memory:', 'postgresql://host/asboljam',
                      'postgresql://host/asboljam_security_short',
                      'postgresql://host/asboljam_security_' + 'a' * 32 + '?dbname=asboljam',
                      'mysql://host/asboljam_security_' + 'a' * 32):
            with self.subTest(value=value), patch.dict(os.environ, {'ASBOLJAM_SECURITY_TEST_DATABASE_URL': value}, clear=True), patch('database_fixture.create_engine') as connect:
                with self.assertRaisesRegex(ValueError, 'fresh security-test'):
                    isolated_database_url('sqlite:///fixture.sqlite')
                connect.assert_not_called()

    def test_each_call_creates_a_unique_schema_and_retains_connection_settings(self):
        url = 'postgresql://test_operator@database/asboljam_security_' + 'a' * 32
        engine = MagicMock()
        with patch.dict(os.environ, {'ASBOLJAM_SECURITY_TEST_DATABASE_URL': url}, clear=True), patch('database_fixture.create_engine', return_value=engine):
            first = make_url(isolated_database_url('sqlite:///fixture.sqlite'))
            second = make_url(isolated_database_url('sqlite:///fixture.sqlite'))
        self.assertEqual(first.database, 'asboljam_security_' + 'a' * 32)
        self.assertEqual(first.drivername, 'postgresql+psycopg')
        self.assertEqual(first.host, 'database')
        self.assertNotEqual(first.query['options'], second.query['options'])
        self.assertRegex(first.query['options'], r'^-csearch_path=test_[0-9a-f]{32}$')
        statements = [str(call.args[0]) for call in engine.begin.return_value.__enter__.return_value.execute.call_args_list]
        self.assertTrue(all(statement.startswith('CREATE SCHEMA "test_') for statement in statements))
        self.assertEqual(engine.dispose.call_count, 2)

    def test_configuration_errors_do_not_repeat_credentials(self):
        marker = 'private-fixture-database-value'
        with patch.dict(os.environ, {'ASBOLJAM_SECURITY_TEST_DATABASE_URL': f'postgresql://operator:{marker}@database/asboljam'}, clear=True):
            try:
                isolated_database_url('sqlite:///fixture.sqlite')
            except ValueError as exc:
                self.assertNotIn(marker, str(exc))
            else:
                self.fail('Expected unsafe target to be rejected')


if __name__ == '__main__':
    unittest.main()
