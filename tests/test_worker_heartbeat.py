"""Real database lease races; only expensive calculation is stubbed."""
import contextlib
from copy import deepcopy
import io
import threading
import time
import unittest
from unittest.mock import patch

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from apps.api.db import Audit, Forecast, Job
from apps.worker import main as worker
import test_worker_security as fixtures


class WorkerHeartbeatTests(unittest.TestCase):
    def setUp(self):
        fixtures.WorkerSecurityTests.setUp(self)

    def running(self, started=100, heartbeat=None):
        with self.factory() as db:
            db.execute(update(Job).where(Job.id == 'job').values(
                status='running', started_at=started, heartbeat_at=heartbeat))
            db.commit()

    def test_renewal_keeps_original_claim_and_clock_rollback_cannot_shorten_it(self):
        self.running()
        self.assertTrue(worker.renew_lease(self.factory, 'job', 100, timestamp=250))
        self.assertTrue(worker.renew_lease(self.factory, 'job', 100, timestamp=200))
        with self.factory() as db:
            row = db.get(Job, 'job')
            self.assertEqual((row.started_at, row.heartbeat_at), (100, 250))

    def test_fresh_heartbeat_prevents_reclaim_of_old_claim(self):
        self.running(started=100, heartbeat=2099)
        with patch.object(worker.time, 'time', return_value=2100):
            self.assertIsNone(worker.claim(self.factory))
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'running')

    def test_dead_worker_reclaims_then_rejects_old_heartbeat_and_publication(self):
        self.running(started=100, heartbeat=200)
        with patch.object(worker.time, 'time', return_value=2101):
            claimed = worker.claim(self.factory)
        self.assertEqual(claimed[:2], ('job', 2101))
        self.assertFalse(worker.renew_lease(self.factory, 'job', 100, timestamp=2200))
        result = dict(self.result, input_snapshot_sha256='fixture-hash')
        worker.finish(self.factory, 'job', 100, result=result)
        with self.factory() as db:
            self.assertIsNone(db.get(Forecast, 'job'))
            self.assertEqual(db.get(Job, 'job').started_at, 2101)
        worker.finish(self.factory, 'job', 2101, result=result)
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'succeeded')
            self.assertEqual(len(list(db.scalars(select(Audit)))), 1)

    def test_legacy_running_job_uses_original_start_until_first_heartbeat(self):
        self.running(started=100, heartbeat=None)
        with patch.object(worker.time, 'time', return_value=1901):
            self.assertEqual(worker.claim(self.factory)[:2], ('job', 1901))

    def test_cancelled_or_finished_claim_cannot_be_kept_alive(self):
        for status in ('queued', 'failed', 'succeeded'):
            with self.subTest(status=status), self.factory() as db:
                db.execute(update(Job).where(Job.id == 'job').values(
                    status=status, started_at=100, heartbeat_at=100))
                db.commit()
                self.assertFalse(worker.renew_lease(self.factory, 'job', 100, timestamp=200))
                db.expire_all()
                self.assertEqual(db.get(Job, 'job').heartbeat_at, 100)

    def test_actual_background_heartbeat_runs_during_calculation_and_stops_afterward(self):
        beat = threading.Event()
        renew = worker.renew_lease

        def observe(*args, **kwargs):
            renewed = renew(*args, **kwargs)
            if renewed:
                beat.set()
            return renewed

        def calculate(*args):
            self.assertTrue(beat.wait(5), 'No heartbeat committed while calculation was pending')
            with self.factory() as db:
                row = db.get(Job, 'job')
                self.assertGreater(row.heartbeat_at, row.started_at)
            self.assertIsNone(worker.claim(self.factory))
            return deepcopy(self.result)

        with patch.object(worker, 'HEARTBEAT_SECONDS', 0.01), \
                patch.object(worker, 'renew_lease', side_effect=observe), \
                patch.object(worker, 'forecast', side_effect=calculate) as compute:
            self.assertTrue(worker.run_once(self.factory, calculator=worker.inline_calculation))
        compute.assert_called_once()
        self.assertFalse(any(t.name == 'asboljam-job-heartbeat' for t in threading.enumerate()))
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').status, 'succeeded')

    def test_background_database_error_is_sanitized_and_next_pulse_recovers(self):
        self.running()
        recovered = threading.Event()
        attempts = []
        fault = OperationalError('private SQL', {'password': 'private value'}, Exception('private connection'))

        def renew(*args):
            attempts.append(1)
            if len(attempts) == 1:
                raise fault
            recovered.set()
            return False

        output = io.StringIO()
        with patch.object(worker, 'HEARTBEAT_SECONDS', 0.01), \
                patch.object(worker, 'renew_lease', side_effect=renew), contextlib.redirect_stdout(output):
            with worker.keep_lease(self.factory, 'job', 100):
                self.assertTrue(recovered.wait(5))
        self.assertIn('DATABASE_ERROR', output.getvalue())
        self.assertNotIn('private', output.getvalue())
        self.assertEqual(len(attempts), 2)

    def test_live_renewal_and_reclaimer_serialize_on_same_job(self):
        self.running(started=time.time() - worker.LEASE_SECONDS - 100)
        with self.factory() as db:
            claim_time = db.get(Job, 'job').started_at
        # Hold the renewal's uncommitted update so a real concurrent reclaimer waits.
        with self.factory() as renewal:
            renewal.execute(update(Job).where(Job.id == 'job').values(heartbeat_at=time.time()))
            started, finished = threading.Event(), threading.Event()
            outcomes, errors = [], []

            def reclaim():
                started.set()
                try:
                    outcomes.append(worker.claim(self.factory))
                except Exception as exc:
                    errors.append(type(exc).__name__)
                finally:
                    finished.set()

            thread = threading.Thread(target=reclaim)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                renewal.commit()
                self.assertTrue(finished.wait(10))
            finally:
                renewal.rollback()
                thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(outcomes, [None])
        with self.factory() as db:
            self.assertEqual(db.get(Job, 'job').started_at, claim_time)


if __name__ == '__main__':
    unittest.main()
