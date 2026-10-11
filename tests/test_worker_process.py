"""Actual child processes exercise deadlines, IPC, cancellation and cleanup."""
import contextlib
from copy import deepcopy
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from sqlalchemy import event, select, update
from apps.api.db import Audit, Forecast, Job, User
from apps.worker import calculation_process as calculation
from apps.worker import main as worker
import test_worker_security as fixtures


HELPER = Path(__file__).with_name('worker_process_fixture.py')


class ChildFixture:
    def __init__(self, mode, marker, *, wait_ready=False):
        self.mode, self.marker = mode, marker
        self.wait_ready, self.ready_at = wait_ready, None
        self.original = subprocess.Popen
        self.processes, self.directories, self.options = [], [], []

    def __call__(self, command, **kwargs):
        self.directories.append(Path(command[command.index('--input') + 1]).parent)
        self.options.append(kwargs)
        if self.mode is not None:
            command = [sys.executable, str(HELPER), '--mode', self.mode, '--marker', str(self.marker), *command[3:]]
        process = self.original(command, **kwargs)
        self.processes.append(process)
        if self.wait_ready:
            # Separate interpreter startup from the short running-computation
            # deadline. The production supervisor's clock remains unmodified.
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    marker = json.loads(self.marker.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    marker = None  # The child may still be writing its marker.
                # Match this launch by its private input directory, not Popen.pid: a
                # Windows venv python.exe is a launcher whose interpreter has another PID.
                if isinstance(marker, dict) and marker.get('directory') == str(self.directories[-1]):
                    self.ready_at = time.monotonic()
                    break
                time.sleep(0.01)
            if self.ready_at is None:
                calculation._stop_child(process)
                raise AssertionError('Actual fixture computation did not become ready within 10 seconds')
        return process

    def assert_clean(self, test):
        test.assertTrue(self.processes)
        test.assertTrue(all(process.poll() is not None for process in self.processes))
        test.assertTrue(all(not directory.exists() for directory in self.directories))


class CalculationProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.marker = Path(self.temp.name) / 'active.json'

    def run_fixture(self, mode, **kwargs):
        launched = ChildFixture(mode, self.marker)
        self.addCleanup(launched.assert_clean, self)
        with patch.object(calculation.subprocess, 'Popen', side_effect=launched):
            result = calculation.run_calculation({}, {}, 'forecast', claim_active=lambda: True,
                timeout_seconds=5, **kwargs)
        return result, launched

    def test_timeout_configuration_is_finite_validated_and_sanitized(self):
        self.assertEqual(calculation.load_timeout({}), 900)
        self.assertEqual(calculation.load_timeout({'WORKER_CALCULATION_TIMEOUT_SECONDS': '3600'}), 3600)
        for value in ('0', '-1', '3601', 'nan', 'inf', '1.5', '', 'private-fixture-secret', ' 2'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^WORKER_CALCULATION_TIMEOUT_SECONDS must be an integer from 1 to 3600$'):
                calculation.load_timeout({'WORKER_CALCULATION_TIMEOUT_SECONDS': value})

    def test_real_hung_child_is_terminated_and_private_files_removed(self):
        launched = ChildFixture('hang', self.marker, wait_ready=True)
        self.addCleanup(launched.assert_clean, self)
        with patch.object(calculation.subprocess, 'Popen', side_effect=launched):
            with self.assertRaises(calculation.CalculationTimeout):
                calculation.run_calculation({}, {}, 'forecast', claim_active=lambda: True, timeout_seconds=0.5)
        self.assertTrue(self.marker.exists(), 'Actual child never started')
        self.assertIsNotNone(launched.ready_at)
        elapsed = time.monotonic() - launched.ready_at
        self.assertGreaterEqual(elapsed, 0.5, 'Running computation was stopped before its deadline')
        self.assertLess(elapsed, 4)
        launched.assert_clean(self)

    def test_large_result_cannot_deadlock_on_pipe_capacity(self):
        result, launched = self.run_fixture('large')
        self.assertEqual(len(result['data']), 3 * 1024 * 1024)
        launched.assert_clean(self)

    def test_child_environment_excludes_credentials_and_has_no_window(self):
        with patch.dict(os.environ, DATABASE_URL='private-fixture-connection', DEMO_PASSWORD='private-fixture-password',
                PRIVATE_FIXTURE_SECRET='private-fixture-value', ASBOLJAM_SECURITY_TEST_DATABASE_URL='private-fixture-test-url'):
            result, launched = self.run_fixture('environment')
        self.assertFalse(result['secret_inherited'])
        self.assertEqual(launched.options[0]['creationflags'], subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

    def test_child_exception_and_streams_never_expose_values(self):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(calculation.CalculationFailed) as raised:
                self.run_fixture('error')
        self.assertEqual(str(raised.exception), 'JOB_CALCULATION_FAILED')
        self.assertNotIn('private-fixture', output.getvalue() + errors.getvalue())

    def test_deadline_still_kills_cpu_when_database_observer_is_stalled(self):
        release, observing = threading.Event(), threading.Event()

        def blocked_check():
            observing.set()
            release.wait(10)
            return True

        launched = ChildFixture('hang', self.marker)
        started = time.monotonic()
        try:
            with patch.object(calculation.subprocess, 'Popen', side_effect=launched):
                with self.assertRaises(calculation.CalculationTimeout):
                    calculation.run_calculation({}, {}, 'forecast', claim_active=blocked_check, timeout_seconds=0.5)
            self.assertTrue(observing.is_set())
            self.assertLess(time.monotonic() - started, 4)
            launched.assert_clean(self)
        finally:
            release.set()

    def test_forced_interrupt_reaps_child_and_cleans_private_files(self):
        launched = ChildFixture('hang', self.marker)
        with patch.object(calculation.subprocess, 'Popen', side_effect=launched), \
                patch.object(calculation.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                calculation.run_calculation({}, {}, 'forecast', claim_active=lambda: True, timeout_seconds=5)
        launched.assert_clean(self)

    def test_actual_forecast_matches_in_process_calculation(self):
        first = date(2025, 10, 9)
        payload = dict(branch_id='1', origin='2025-12-31', model='seasonal_naive_7')
        snapshot = dict(sales=[dict(branch_id='1', meal_id='1', date=(first + timedelta(days=day)).isoformat(),
            units_sold=20 + day % 7, data_origin='SYNTHETIC') for day in range(84)],
            meals=[dict(meal_id='1', meal_name='Generated fixture', data_origin='SYNTHETIC')], input_lineage=None)
        expected = worker.inline_calculation(payload, deepcopy(snapshot), 'forecast')
        launched = ChildFixture(None, self.marker)
        with patch.object(calculation.subprocess, 'Popen', side_effect=launched):
            result = calculation.run_calculation(payload, snapshot, 'forecast', claim_active=lambda: True, timeout_seconds=30)
        expected['metadata'].pop('elapsed_seconds')
        result['metadata'].pop('elapsed_seconds')
        expected['metadata'].pop('evaluation_seconds')
        result['metadata'].pop('evaluation_seconds')
        self.assertEqual(result, expected)
        launched.assert_clean(self)

    def test_actual_procurement_matches_in_process_calculation(self):
        from test_real_execution import procurement_inputs
        inputs = procurement_inputs()
        payload = dict(branch_id=inputs['branch_id'], budget='0', strategy='point')
        snapshot = dict(execution_context=inputs['execution_context'], forecast_result=inputs['forecast_result'],
            ingredients=inputs['ingredients'], recipes=inputs['recipes'], inventory_lots=inputs['inventory'],
            supplier_offers=inputs['offers'], suppliers=inputs['suppliers'])
        expected = worker.inline_calculation(payload, deepcopy(snapshot), 'procurement')
        launched = ChildFixture(None, self.marker)
        with patch.object(calculation.subprocess, 'Popen', side_effect=launched):
            result = calculation.run_calculation(payload, snapshot, 'procurement', claim_active=lambda: True, timeout_seconds=30)
        expected['metadata'].pop('elapsed_seconds')
        result['metadata'].pop('elapsed_seconds')
        self.assertEqual(result, expected)
        launched.assert_clean(self)

    def test_parent_death_closes_lifetime_pipe_and_stops_orphan_cpu(self):
        supervisor = subprocess.Popen([sys.executable, str(HELPER), '--mode', 'supervisor', '--marker', str(self.marker)],
            cwd=calculation.ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        details = None
        try:
            deadline = time.monotonic() + 10
            while not self.marker.exists() and time.monotonic() < deadline and supervisor.poll() is None:
                time.sleep(0.02)
            self.assertTrue(self.marker.exists(), 'Grandchild did not start')
            details = json.loads(self.marker.read_text(encoding='utf-8'))
            supervisor.kill()
            supervisor.wait(timeout=5)
            deadline = time.monotonic() + 5
            while _process_running(details['pid']) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertFalse(_process_running(details['pid']), 'Calculation survived its supervisor')
        finally:
            if supervisor.poll() is None:
                supervisor.kill()
                supervisor.wait(timeout=5)
            # Forced parent death cannot execute its normal TemporaryDirectory cleanup.
            if details is not None:
                directory = Path(details['directory']).resolve()
                root = Path(tempfile.gettempdir()).resolve()
                self.assertEqual(directory.parent, root)
                self.assertTrue(directory.name.startswith('asboljam-calculation-'))
                for name in ('input.json', 'result.json', 'result.partial'):
                    (directory / name).unlink(missing_ok=True)
                directory.rmdir()


def _process_running(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    state = Path('/proc') / str(pid) / 'stat'
    if state.exists():
        return state.read_text().split(') ')[1].split()[0] != 'Z'
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class WorkerProcessTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkerSecurityTests.setUp(self)
        self.marker = Path(self.temp.name) / 'active.json'

    def test_claim_monitor_reads_status_without_loading_operational_snapshot(self):
        claimed = worker.claim(self.factory)
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            if 'FROM jobs' in statement:
                statements.append(statement)

        event.listen(self.engine, 'before_cursor_execute', capture)
        try:
            self.assertTrue(worker.claim_is_active(self.factory, claimed[0], claimed[1]))
        finally:
            event.remove(self.engine, 'before_cursor_execute', capture)
        self.assertEqual(len(statements), 1)
        self.assertNotIn('snapshot', statements[0])
        self.assertNotIn('payload', statements[0])

    def test_cancelled_reclaimed_and_revoked_claims_stop_actual_cpu_without_publication(self):
        for mutation in ('cancelled', 'reclaimed', 'revoked'):
            with self.subTest(mutation=mutation):
                self.marker.unlink(missing_ok=True)
                with self.factory() as db:
                    db.execute(update(Job).where(Job.id == 'job').values(status='queued', started_at=None, heartbeat_at=None, error=None))
                    db.execute(update(User).where(User.id == 'actor').values(active=True))
                    for row in db.scalars(select(Audit)):
                        db.delete(row)
                    db.commit()
                errors = []

                def cancel():
                    try:
                        deadline = time.monotonic() + 5
                        while not self.marker.exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        if not self.marker.exists():
                            raise AssertionError('Actual child did not start')
                        with self.factory() as db:
                            job = db.get(Job, 'job')
                            if mutation == 'cancelled':
                                job.status, job.error = 'failed', 'JOB_ACCESS_REVOKED'
                            elif mutation == 'reclaimed':
                                job.started_at += 1
                            else:
                                db.get(User, 'actor').active = False
                            db.commit()
                    except Exception as exc:
                        errors.append(type(exc).__name__)

                thread = threading.Thread(target=cancel)
                launched = ChildFixture('hang', self.marker)
                thread.start()
                try:
                    with patch.object(calculation.subprocess, 'Popen', side_effect=launched):
                        self.assertTrue(worker.run_once(self.factory, timeout_seconds=5))
                finally:
                    thread.join(timeout=10)
                self.assertEqual(errors, [])
                launched.assert_clean(self)
                with self.factory() as db:
                    job = db.get(Job, 'job')
                    self.assertIsNone(db.get(Forecast, 'job'))
                    self.assertIsNone(job.result_id)
                    self.assertEqual(job.status, 'running' if mutation == 'reclaimed' else 'failed')
                    if mutation != 'reclaimed':
                        self.assertTrue(job.error.startswith('JOB_ACCESS_REVOKED'))
                    self.assertEqual(db.scalar(select(Audit).where(Audit.action == 'forecast.succeeded')), None)

    def test_timeout_preserves_heartbeat_and_worker_processes_next_job(self):
        with self.factory() as db:
            row = db.get(Job, 'job')
            row.created_at = '2026-01-01T00:00:00+00:00'
            db.add(Job(id='next-job', organization_id=row.organization_id, branch_id=row.branch_id,
                actor_id=row.actor_id, kind=row.kind, payload=deepcopy(row.payload), snapshot=deepcopy(row.snapshot),
                created_at='2026-01-01T00:00:01+00:00'))
            db.commit()
        hung = ChildFixture('hang', self.marker)
        with patch.object(calculation.subprocess, 'Popen', side_effect=hung), patch.object(worker, 'HEARTBEAT_SECONDS', 0.02):
            self.assertTrue(worker.run_once(self.factory, timeout_seconds=0.5))
        hung.assert_clean(self)
        with self.factory() as db:
            failed = db.get(Job, 'job')
            self.assertEqual(failed.status, 'failed')
            self.assertTrue(failed.error.startswith('JOB_TIMEOUT'))
            self.assertGreater(failed.heartbeat_at, failed.started_at)
            self.assertIsNone(db.get(Forecast, 'job'))
        valid = ChildFixture('valid', self.marker)
        with patch.object(calculation.subprocess, 'Popen', side_effect=valid):
            self.assertTrue(worker.run_once(self.factory, timeout_seconds=5))
        valid.assert_clean(self)
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'next-job').status, 'succeeded')
            self.assertIsNotNone(db.get(Forecast, 'next-job'))
            self.assertEqual(len(list(db.scalars(select(Audit)))), 2)


if __name__ == '__main__':
    unittest.main()
