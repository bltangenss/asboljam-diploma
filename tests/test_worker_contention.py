"""Actual SQLite writer contention; fixtures never use an application database."""
import contextlib
from copy import deepcopy
import io
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from apps.api.db import Audit, Forecast, Job, Organization, User, make_engine, migrate, sessions
from apps.api.importing import insert_rows
from apps.worker import main as worker


class WorkerContentionTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='worker-contention-', dir='.cache')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'fixture.sqlite'
        self.url = 'sqlite:///' + self.path.as_posix()
        self.engine = make_engine(self.url)
        self.addCleanup(self.engine.dispose)
        # A real busy error is required; do not wait the application timeout in tests.
        event.listen(self.engine, 'connect', lambda connection, _: connection.execute('PRAGMA busy_timeout=10'))
        migrate(self.engine)
        self.factory = sessions(self.engine)
        self.blocker = sqlite3.connect(self.path, isolation_level=None)
        self.addCleanup(self.blocker.close)
        self.result = dict(branch_id='1', origin='2025-12-31', target_date='2026-01-01',
                           data_origin='SYNTHETIC', predictions=[dict(meal_id='1', point_forecast=2)])
        with self.factory() as db:
            db.add(Organization(id='fixture', name='Artificial contention fixture', timezone='Asia/Qyzylorda',
                data_policy='synthetic_only', provenance='test_fixture'))
            db.add(User(id='actor', organization_id='fixture', email='contention@test.invalid',
                        role='manager', branch_ids=['1'], password_hash='unused'))
            insert_rows(db, 'fixture', 'branches', [dict(branch_id='1', branch_name='Fixture', data_origin='SYNTHETIC')])
            db.add(Job(id='job', organization_id='fixture', branch_id='1', actor_id='actor', kind='forecast',
                payload=dict(branch_id='1', origin='2025-12-31', model='seasonal_naive_7'),
                snapshot=dict(sales=[dict(branch_id='1', meal_id='1', date='2025-12-31', units_sold=2, data_origin='SYNTHETIC')],
                    meals=[dict(meal_id='1', meal_name='Fixture meal', data_origin='SYNTHETIC')])))
            db.commit()

    def release_writer(self, delay):
        self.assertGreater(delay, 0)
        self.blocker.execute('COMMIT')

    def assert_one_publication(self):
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'succeeded')
            self.assertIsNone(db.get(Job, 'job').error)
            self.assertEqual(db.scalar(select(func.count()).select_from(Forecast)), 1)
            events = list(db.scalars(select(Audit)))
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].action, 'forecast.succeeded')

    def test_real_competing_writer_during_claim_recovers_in_same_worker(self):
        self.blocker.execute('BEGIN IMMEDIATE')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker.time, 'sleep', side_effect=self.release_writer) as pause, \
                patch.object(worker, 'sqlite_contention', wraps=worker.sqlite_contention) as classify, \
                patch.object(worker, 'forecast', return_value=deepcopy(self.result)) as calculate:
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
            self.assertFalse(worker.run_once(self.factory, calculator=worker.inline_calculation))
        self.assertEqual(pause.call_count, 1)
        self.assertEqual(classify.call_args.args[0].orig.sqlite_errorcode & 0xff, sqlite3.SQLITE_BUSY)
        calculate.assert_called_once()
        self.assertIn('retrying claim', output.getvalue())
        self.assertNotIn('UPDATE', output.getvalue())
        self.assertNotIn(str(self.path), output.getvalue())
        self.assert_one_publication()

    def test_publication_contention_keeps_computed_result_and_does_not_publish_twice(self):
        def calculate(*args, **kwargs):
            self.blocker.execute('BEGIN IMMEDIATE')
            return deepcopy(self.result)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker.time, 'sleep', side_effect=self.release_writer) as pause, \
                patch.object(worker, 'forecast', side_effect=calculate) as compute:
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        self.assertEqual(pause.call_count, 1)
        compute.assert_called_once()
        self.assertIn('retrying publication', output.getvalue())
        self.assertNotIn('CALCULATION_FAILED', output.getvalue())
        self.assert_one_publication()
        with self.factory() as db:
            claim_time = db.get(Job, 'job').started_at
            result = deepcopy(db.get(Forecast, 'job').result)
        worker.finish(self.factory, 'job', claim_time, result=result)
        self.assert_one_publication()

    def test_cancellation_committed_while_publication_is_busy_keeps_fence(self):
        def calculate(*args, **kwargs):
            self.blocker.execute('BEGIN IMMEDIATE')
            self.blocker.execute("UPDATE jobs SET status='failed', error='JOB_ACCESS_REVOKED', result_id=NULL WHERE id='job'")
            return deepcopy(self.result)
        with contextlib.redirect_stdout(io.StringIO()), patch.object(worker.time, 'sleep', side_effect=self.release_writer), \
                patch.object(worker, 'forecast', side_effect=calculate) as compute:
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        compute.assert_called_once()
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'failed')
            self.assertEqual(db.get(Job, 'job').error, 'JOB_ACCESS_REVOKED')
            self.assertIsNone(db.get(Job, 'job').result_id)
            self.assertIsNone(db.get(Forecast, 'job'))
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), 0)

    def database_fault(self):
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql('SELECT * FROM private_fixture_missing_table')
        except OperationalError as exc:
            return exc
        self.fail('The absent fixture table must fail')

    def test_nontransient_sqlite_fault_is_not_retried_or_hidden_by_run_once(self):
        fault = self.database_fault()
        self.assertFalse(worker.sqlite_contention(fault))
        with patch.object(worker, 'claim', side_effect=fault), patch.object(worker.time, 'sleep') as pause:
            with self.assertRaises(OperationalError) as raised:
                worker.run_once(self.factory, calculator=worker.inline_calculation)
        self.assertIs(raised.exception, fault)
        pause.assert_not_called()

    def test_main_reports_fatal_database_error_without_sql_or_exception_trace(self):
        fault = self.database_fault()
        output, errors = io.StringIO(), io.StringIO()
        with patch('sys.argv', ['worker', '--once']), \
                patch('apps.api.config.load_settings', return_value=SimpleNamespace(database_url=self.url)), \
                patch.object(worker, 'make_engine', return_value=self.engine), patch.object(worker, 'migrate'), \
                patch.object(worker, 'run_once', side_effect=fault), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as raised:
                worker.main()
        self.assertEqual(raised.exception.code, 'AsBoljam worker stopped (DATABASE_ERROR).')
        self.assertTrue(raised.exception.__suppress_context__)
        text = output.getvalue() + errors.getvalue()
        self.assertNotIn('private_fixture_missing_table', text)
        self.assertNotIn('SELECT', text)
        self.assertNotIn('Traceback', text)

    def test_extended_lock_codes_are_recognized_without_string_matching(self):
        for code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, 517, 262):
            with self.subTest(code=code):
                original = sqlite3.OperationalError('private fixture detail')
                original.sqlite_errorcode = code
                self.assertTrue(worker.sqlite_contention(OperationalError('private SQL', {}, original)))
        fake_database = SimpleNamespace(sqlite_errorcode=sqlite3.SQLITE_BUSY)
        self.assertFalse(worker.sqlite_contention(OperationalError(None, None, fake_database)))


if __name__ == '__main__':
    unittest.main()
