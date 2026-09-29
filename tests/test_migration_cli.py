"""Migration command validates environment before opening a database; no DB writes here."""
import contextlib
import io
import os
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import SQLAlchemyError

from apps.api.migrations import MigrationError
from database import migrate as cli


class MigrationCliTests(unittest.TestCase):
    def invoke(self, environment, operation_error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        engine = MagicMock()
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(cli, 'make_engine', return_value=engine) as make, \
             patch.object(cli, 'migrate', side_effect=operation_error) as operation, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main()
        return code, stdout.getvalue() + stderr.getvalue(), make, operation, engine

    def test_incomplete_production_configuration_does_not_open_default_sqlite(self):
        code, output, make, operation, _ = self.invoke({'ASBOLJAM_ENV': 'production'})
        self.assertEqual(code, 2)
        self.assertIn('MIGRATION_CONFIG_INVALID', output)
        make.assert_not_called()
        operation.assert_not_called()

    def test_malformed_configuration_does_not_echo_input_or_open_database(self):
        marker = 'private-migration-fixture-value'
        code, output, make, operation, _ = self.invoke({'DATABASE_URL': marker})
        self.assertEqual(code, 2)
        self.assertNotIn(marker, output)
        make.assert_not_called()
        operation.assert_not_called()

    def test_valid_configuration_uses_explicit_url_and_disposes_engine(self):
        url = 'postgresql+psycopg://operator@database/asboljam'
        code, output, make, operation, engine = self.invoke({
            'ASBOLJAM_ENV': 'production', 'DATABASE_URL': url,
            'ALLOWED_ORIGINS': 'https://app.example.org', 'COOKIE_SECURE': 'true',
        })
        self.assertEqual(code, 0)
        self.assertIn('0001 and 0002', output)
        self.assertNotIn(url, output)
        make.assert_called_once_with(url)
        operation.assert_called_once_with(engine)
        engine.dispose.assert_called_once()

    def test_unsupported_history_is_reported_without_echoing_raw_error(self):
        marker = 'private-history-fixture-value'
        code, output, _, _, engine = self.invoke({}, MigrationError(marker))
        self.assertEqual(code, 2)
        self.assertIn('MIGRATION_HISTORY_UNSUPPORTED', output)
        self.assertNotIn(marker, output)
        engine.dispose.assert_called_once()

    def test_database_failure_is_redacted_and_connection_disposed(self):
        marker = 'private-database-fixture-value'
        code, output, _, _, engine = self.invoke({}, SQLAlchemyError(marker))
        self.assertEqual(code, 2)
        self.assertIn('MIGRATION_DATABASE_ERROR', output)
        self.assertNotIn(marker, output)
        engine.dispose.assert_called_once()


if __name__ == '__main__':
    unittest.main()
