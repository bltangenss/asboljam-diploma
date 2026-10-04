"""Stop claiming, drain a running job, and preserve cancellation/claim fences."""
from copy import deepcopy
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from apps.api.db import Audit, Forecast, Job
from apps.worker import main as worker
import test_worker_security as fixtures


class WorkerShutdownTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkerSecurityTests.setUp(self)

    def add_second_job(self):
        with self.factory() as db:
            original = db.get(Job, 'job')
            original.created_at = '2026-01-01T00:00:00+00:00'
            db.add(Job(id='next-job', organization_id=original.organization_id,
                branch_id=original.branch_id, actor_id=original.actor_id, kind=original.kind,
                payload=deepcopy(original.payload), snapshot=deepcopy(original.snapshot),
                created_at='2026-01-01T00:00:01+00:00'))
            db.commit()

    def test_stop_before_claim_leaves_queue_unchanged(self):
        stopped = threading.Event(); stopped.set()
        with patch.object(worker, 'claim') as claim:
            self.assertFalse(worker.run_once(self.factory, stop_event=stopped))
        claim.assert_not_called()
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'queued')

    def test_stop_during_claim_releases_only_this_claim_without_computation(self):
        stopped, claim = threading.Event(), worker.claim

        def during_commit(factory):
            result = claim(factory)
            stopped.set()
            return result

        with patch.object(worker, 'claim', side_effect=during_commit), patch.object(worker, 'forecast') as compute:
            self.assertFalse(worker.run_once(self.factory, stop_event=stopped))
        compute.assert_not_called()
        with self.factory() as db:
            row = db.get(Job, 'job')
            self.assertEqual((row.status, row.started_at, row.heartbeat_at), ('queued', None, None))
            self.assertEqual(list(db.scalars(select(Audit))), [])

    def test_release_cannot_resurrect_cancellation_or_release_new_claim(self):
        for status, started in (('failed', 100), ('succeeded', 100), ('running', 200)):
            with self.subTest(status=status), self.factory() as db:
                db.execute(update(Job).where(Job.id == 'job').values(status=status, started_at=started, heartbeat_at=started))
                db.commit()
                worker.release_unstarted_claim(self.factory, 'job', 100)
                db.expire_all()
                row = db.get(Job, 'job')
                self.assertEqual((row.status, row.started_at, row.heartbeat_at), (status, started, started))

    def test_busy_claim_wait_is_interruptible_before_next_attempt(self):
        stopped = threading.Event()
        original = sqlite3.OperationalError('private fixture detail')
        original.sqlite_errorcode = sqlite3.SQLITE_BUSY
        fault = OperationalError('private SQL', {}, original)

        def stop_during_wait(delay):
            stopped.set()
            return True

        with patch.object(stopped, 'wait', side_effect=stop_during_wait), \
                patch.object(worker, 'claim', side_effect=fault) as claim:
            self.assertFalse(worker.run_once(self.factory, stop_event=stopped))
        claim.assert_called_once()

    def test_first_signal_finishes_current_job_without_claiming_next(self):
        self.add_second_job()
        handlers, initial = {}, {signal.SIGINT:signal.getsignal(signal.SIGINT), signal.SIGTERM:signal.getsignal(signal.SIGTERM)}

        def register(signum, handler):
            previous = handlers.get(signum, initial[signum])
            handlers[signum] = handler
            return previous

        def compute(*args):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return deepcopy(self.result)

        with patch('sys.argv', ['worker']), patch.object(worker.signal, 'signal', side_effect=register), \
                patch('apps.api.config.load_settings', return_value=SimpleNamespace(database_url='unused')), \
                patch.object(worker, 'make_engine', return_value=self.engine), \
                patch.object(worker, 'forecast', side_effect=compute) as calculate:
            worker.main()
        calculate.assert_called_once()
        self.assertEqual(handlers, initial)
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'succeeded')
            self.assertEqual(db.get(Job, 'next-job').status, 'queued')

    @unittest.skipIf(os.name == 'nt', 'Real SIGTERM drain uses POSIX; Windows termination forcibly kills the process')
    def test_real_sigterm_drains_child_process_and_keeps_heartbeat_until_publication(self):
        self.add_second_job()
        marker = Path(self.temp.name)/'calculation-active'
        environment = dict(os.environ, DATABASE_URL=self.engine.url.render_as_string(hide_password=False),
                           ASBOLJAM_ENV='local', COOKIE_SECURE='false', ALLOWED_ORIGINS='http://localhost:3000',
                           WORKER_TEST_MARKER=str(marker))
        program = '''
from pathlib import Path
import os,time
from apps.worker import main as worker
def compute(*args, **kwargs):
    Path(os.environ['WORKER_TEST_MARKER']).touch()
    time.sleep(1)
    return dict(branch_id='1',target_date='2026-01-01',data_origin='SYNTHETIC',predictions=[dict(meal_id='1',point_forecast=2)])
worker.forecast=compute
worker.HEARTBEAT_SECONDS=0.02
worker.main()
'''
        process = subprocess.Popen([sys.executable, '-u', '-c', program], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic()+10
            while not marker.exists() and process.poll() is None and time.monotonic()<deadline:
                time.sleep(0.01)
            self.assertTrue(marker.exists(), 'Child calculation did not start')
            process.send_signal(signal.SIGTERM)
            output, errors = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, 'Child worker did not drain cleanly')
            self.assertIn('stopping after the current job', output)
            self.assertNotIn('Traceback', errors)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        with self.factory() as db:
            row = db.get(Job, 'job')
            self.assertEqual(row.status, 'succeeded')
            self.assertGreater(row.heartbeat_at, row.started_at)
            self.assertIsNotNone(db.get(Forecast, 'job'))
            self.assertEqual(db.get(Job, 'next-job').status, 'queued')


if __name__ == '__main__':
    unittest.main()
