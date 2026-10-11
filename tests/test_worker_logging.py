"""Worker events describe real committed fixture transactions, never private inputs."""
import contextlib
from copy import deepcopy
import io
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.api.db import Audit, Forecast, Job, User
from apps.worker import main as worker
import test_worker_security as fixtures


SECRET = 'private-worker-logging-password-cookie-token-sentinel'


def events(output):
    # Legacy static retry notices are not lifecycle events.
    return [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]


class WorkerLoggingTests(unittest.TestCase):
    setUp = fixtures.WorkerSecurityTests.setUp
    job = fixtures.WorkerSecurityTests.job
    assert_failed = fixtures.WorkerSecurityTests.assert_failed

    def result_value(self):
        return dict(deepcopy(self.result), input_snapshot_sha256='f' * 64)

    def calculate(self, *args):
        return self.result_value()

    def assert_publication(self, count):
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Forecast)), count)
            self.assertEqual(db.scalar(select(func.count()).select_from(Audit)), count)

    def database_fault(self, busy=False):
        original = sqlite3.OperationalError(SECRET)
        if busy:
            original.sqlite_errorcode = sqlite3.SQLITE_BUSY
        return OperationalError('private SQL ' + SECRET, {'password': SECRET}, original)

    def failing_factory(self, fault, *, commit_number=1, once=False):
        counts = {'commits': 0}

        @contextlib.contextmanager
        def factory():
            with self.factory() as db:
                original = db.commit

                def commit():
                    counts['commits'] += 1
                    if counts['commits'] == commit_number or not once and counts['commits'] > commit_number:
                        raise fault
                    return original()

                with patch.object(db, 'commit', side_effect=commit):
                    yield db

        return factory, counts

    def test_claim_and_success_events_are_visible_only_after_their_commits(self):
        observed, output = [], io.StringIO()
        original = worker.emit_event

        def inspect_commit(name, **fields):
            with self.factory() as db:
                observed.append((name, db.get(Job, 'job').status,
                    db.scalar(select(func.count()).select_from(Forecast)),
                    db.scalar(select(func.count()).select_from(Audit))))
            original(name, **fields)

        with contextlib.redirect_stdout(output), patch.object(worker, 'emit_event', side_effect=inspect_commit):
            self.assertTrue(worker.run_once(self.factory, calculator=self.calculate))
            self.assertFalse(worker.run_once(self.factory, calculator=self.calculate))
        logged = events(output)
        self.assertEqual(observed, [('job.claimed', 'running', 0, 0), ('job.finished', 'succeeded', 1, 1)])
        self.assertEqual([row['event'] for row in logged], ['job.claimed', 'job.finished'])
        self.assertEqual(logged[0]['claim_time'], logged[1]['claim_time'])
        self.assertEqual(logged[1]['claim_time'], self.job().started_at)
        self.assertEqual((logged[1]['job_id'], logged[1]['kind'], logged[1]['status']), ('job', 'forecast', 'succeeded'))
        self.assertNotIn('code', logged[1])

    def test_calculation_failure_is_committed_and_does_not_leak_inputs_or_exception(self):
        with self.factory() as db:
            row = db.get(Job, 'job')
            row.payload = dict(row.payload, password=SECRET, cookie=SECRET)
            row.snapshot = dict(row.snapshot, private_source=SECRET)
            db.commit()
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                patch.object(worker, 'run_calculation', side_effect=RuntimeError(SECRET)):
            worker.run_once(self.factory)
        self.assert_failed('JOB_CALCULATION_FAILED')
        logged = events(output)
        self.assertEqual([row['event'] for row in logged], ['job.claimed', 'job.finished'])
        self.assertEqual((logged[-1]['status'], logged[-1]['code']), ('failed', 'JOB_CALCULATION_FAILED'))
        self.assertNotIn(SECRET, output.getvalue() + errors.getvalue())

    def test_timeout_reports_committed_failure_and_claim_identity(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker, 'run_calculation', side_effect=worker.CalculationTimeout(SECRET)):
            worker.run_once(self.factory)
        self.assert_failed('JOB_TIMEOUT')
        logged = events(output)
        self.assertEqual((logged[-1]['event'], logged[-1]['status'], logged[-1]['code']),
                         ('job.finished', 'failed', 'JOB_TIMEOUT'))
        self.assertEqual(logged[-1]['claim_time'], self.job().started_at)
        self.assertNotIn(SECRET, output.getvalue())

    def test_access_revoked_before_calculation_reports_committed_failure(self):
        with self.factory() as db:
            db.get(User, 'actor').active = False
            db.commit()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker, 'run_calculation') as calculate:
            worker.run_once(self.factory)
        calculate.assert_not_called()
        self.assert_failed('JOB_ACCESS_REVOKED')
        self.assertEqual(events(output)[-1]['code'], 'JOB_ACCESS_REVOKED')

    def test_access_revoked_during_calculation_never_logs_success(self):
        def calculate(*args):
            with self.factory() as db:
                db.get(User, 'actor').active = False
                db.commit()
            return self.result_value()

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            worker.run_once(self.factory, calculator=calculate)
        self.assert_failed('JOB_ACCESS_REVOKED')
        self.assertEqual(events(output)[-1]['status'], 'failed')
        self.assertEqual(events(output)[-1]['code'], 'JOB_ACCESS_REVOKED')

    def test_cancelled_calculation_uses_access_revoked_terminal_code(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker, 'run_calculation', side_effect=worker.CalculationCancelled(SECRET)):
            worker.run_once(self.factory)
        self.assert_failed('JOB_ACCESS_REVOKED')
        self.assertEqual(events(output)[-1]['code'], 'JOB_ACCESS_REVOKED')
        self.assertNotIn(SECRET, output.getvalue())

    def test_stale_claim_is_discarded_without_false_terminal_event(self):
        claimed = worker.claim(self.factory)
        with self.factory() as db:
            db.execute(update(Job).where(Job.id == 'job').values(started_at=claimed[1] + 1))
            db.commit()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            worker.finish(self.factory, 'job', claimed[1], result=self.result_value())
        logged = events(output)
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]['event'], logged[0]['code'], logged[0]['claim_time']),
                         ('job.discarded', 'CLAIM_LOST', claimed[1]))
        self.assertEqual(self.job().status, 'running')
        self.assert_publication(0)

    def test_two_finishers_emit_one_committed_terminal_and_one_discard(self):
        claimed = worker.claim(self.factory)
        captured, lock = [], threading.Lock()

        def collect(name, **fields):
            with lock:
                captured.append(dict(event=name, **fields))

        with patch.object(worker, 'emit_event', side_effect=collect), ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(worker.finish, self.factory, 'job', claimed[1], result=self.result_value()) for _ in range(2)]
            for outcome in outcomes:
                outcome.result(timeout=15)
        self.assertCountEqual([row['event'] for row in captured], ['job.finished', 'job.discarded'])
        self.assertEqual(next(row for row in captured if row['event'] == 'job.finished')['status'], 'succeeded')
        self.assertEqual(next(row for row in captured if row['event'] == 'job.discarded')['code'], 'CLAIM_LOST')
        self.assert_publication(1)

    def test_missing_job_is_discarded_without_publication(self):
        with self.factory() as db:
            db.delete(db.get(Job, 'job'))
            db.commit()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            worker.finish(self.factory, 'job', 123, result=self.result_value())
        logged = events(output)
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]['event'], logged[0]['code']), ('job.discarded', 'JOB_MISSING'))
        self.assert_publication(0)

    def test_failed_publication_commit_rolls_back_and_logs_only_sanitized_fault(self):
        claimed = worker.claim(self.factory)
        factory, _ = self.failing_factory(self.database_fault())
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(OperationalError):
            worker.finish(factory, 'job', claimed[1], result=self.result_value())
        logged = events(output)
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]['event'], logged[0]['code']), ('job.publication_error', 'DATABASE_ERROR'))
        self.assertNotIn('status', logged[0])
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(self.job().status, 'running')
        self.assert_publication(0)

    def test_audit_failure_rolls_back_and_is_not_a_calculation_failure(self):
        claimed = worker.claim(self.factory)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker, 'Audit', side_effect=RuntimeError(SECRET)), \
                self.assertRaises(RuntimeError):
            worker.finish(self.factory, 'job', claimed[1], result=self.result_value())
        logged = events(output)
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]['event'], logged[0]['code']), ('job.publication_error', 'PUBLICATION_ERROR'))
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(self.job().status, 'running')
        self.assert_publication(0)

    def test_contention_retry_emits_only_one_terminal_after_successful_commit(self):
        claimed = worker.claim(self.factory)
        factory, counts = self.failing_factory(self.database_fault(busy=True), once=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker.time, 'sleep'):
            worker.retry_sqlite_contention(
                lambda: worker.finish(factory, 'job', claimed[1], result=self.result_value()), 'publication')
        logged = events(output)
        self.assertEqual(counts['commits'], 2)
        self.assertEqual([row['event'] for row in logged], ['job.publication_error', 'job.finished'])
        self.assertEqual(logged[-1]['status'], 'succeeded')
        self.assertEqual(logged[-1]['claim_time'], claimed[1])
        self.assertNotIn(SECRET, output.getvalue())
        self.assert_publication(1)

    def test_expired_lease_is_logged_after_requeue_commit_then_old_claim_is_discarded(self):
        claimed = worker.claim(self.factory)
        observed, output = [], io.StringIO()
        original = worker.emit_event

        def inspect_commit(name, **fields):
            observed.append((name, self.job().status))
            original(name, **fields)

        later = claimed[1] + worker.LEASE_SECONDS + 1
        with contextlib.redirect_stdout(output), patch.object(worker, 'emit_event', side_effect=inspect_commit), \
                patch.object(worker.time, 'time', return_value=later):
            reclaimed = worker.claim(self.factory)
            worker.finish(self.factory, 'job', claimed[1], result=self.result_value())
        self.assertEqual(reclaimed[:2], ('job', later))
        # Requeue is committed before its event; the new claim follows; the old fence loses.
        self.assertEqual(observed, [('job.lease_expired', 'queued'), ('job.claimed', 'running'),
                                    ('job.discarded', 'running')])
        logged = events(output)
        self.assertEqual(set(logged[0]), {'schema_version', 'timestamp', 'event', 'job_id'})
        self.assertEqual((logged[2]['code'], logged[2]['claim_time']), ('CLAIM_LOST', claimed[1]))
        self.assert_publication(0)

    def test_failed_requeue_commit_does_not_emit_lease_expired(self):
        claimed = worker.claim(self.factory)
        factory, counts = self.failing_factory(self.database_fault())
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(worker.time, 'time',
                return_value=claimed[1] + worker.LEASE_SECONDS + 1), self.assertRaises(OperationalError):
            worker.claim(factory)
        self.assertEqual(counts['commits'], 1)
        self.assertEqual(events(output), [])
        self.assertEqual(self.job().status, 'running')
        self.assertEqual(self.job().started_at, claimed[1])

    def test_failed_claim_commit_does_not_emit_claimed(self):
        # The first commit is the existing lease cleanup; the second owns the claim.
        factory, counts = self.failing_factory(self.database_fault(), commit_number=2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(OperationalError):
            worker.claim(factory)
        self.assertEqual(counts['commits'], 2)
        self.assertEqual(events(output), [])
        self.assertEqual(self.job().status, 'queued')
        self.assert_publication(0)

    def test_release_is_logged_after_commit_and_stale_release_is_discarded(self):
        claimed = worker.claim(self.factory)
        observed, output = [], io.StringIO()
        original = worker.emit_event

        def inspect_commit(name, **fields):
            observed.append((name, self.job().status))
            original(name, **fields)

        with contextlib.redirect_stdout(output), patch.object(worker, 'emit_event', side_effect=inspect_commit):
            worker.release_unstarted_claim(self.factory, 'job', claimed[1])
            worker.release_unstarted_claim(self.factory, 'job', claimed[1])
        self.assertEqual(observed, [('job.released', 'queued'), ('job.discarded', 'queued')])
        logged = events(output)
        self.assertEqual(logged[1]['code'], 'CLAIM_LOST')
        self.assertTrue(all(row['claim_time'] == claimed[1] for row in logged))
        self.assert_publication(0)

    def test_failed_release_commit_does_not_emit_released(self):
        claimed = worker.claim(self.factory)
        factory, _ = self.failing_factory(self.database_fault())
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(OperationalError):
            worker.release_unstarted_claim(factory, 'job', claimed[1])
        self.assertEqual(events(output), [])
        self.assertEqual(self.job().status, 'running')

    def test_emitter_failure_cannot_cancel_claim_publication_or_release(self):
        with patch.object(worker, 'emit_event', side_effect=RuntimeError(SECRET)):
            claimed = worker.claim(self.factory)
            worker.release_unstarted_claim(self.factory, 'job', claimed[1])
            claimed = worker.claim(self.factory)
            worker.finish(self.factory, 'job', claimed[1], result=self.result_value())
        self.assertEqual(self.job().status, 'succeeded')
        self.assert_publication(1)

    def test_closed_output_stream_cannot_cancel_committed_success(self):
        class BrokenOutput:
            def write(self, value):
                raise OSError(SECRET)

            def flush(self):
                raise OSError(SECRET)

        with contextlib.redirect_stdout(BrokenOutput()):
            self.assertTrue(worker.run_once(self.factory, calculator=self.calculate))
        self.assertEqual(self.job().status, 'succeeded')
        self.assert_publication(1)

    def test_emission_does_not_reload_expired_orm_fields_after_commit(self):
        claimed = worker.claim(self.factory)
        factory = sessionmaker(bind=self.engine, expire_on_commit=True)
        state, output = {'committed': False}, io.StringIO()

        def committed(connection):
            state['committed'] = True

        def no_reload(connection, cursor, statement, parameters, context, executemany):
            if state['committed']:
                raise AssertionError('Unexpected database access after committed publication')

        event.listen(self.engine, 'commit', committed)
        event.listen(self.engine, 'before_cursor_execute', no_reload)
        try:
            with contextlib.redirect_stdout(output):
                worker.finish(factory, 'job', claimed[1], result=self.result_value())
        finally:
            event.remove(self.engine, 'commit', committed)
            event.remove(self.engine, 'before_cursor_execute', no_reload)
        logged = events(output)
        self.assertEqual([row['event'] for row in logged], ['job.finished'])
        self.assertEqual(logged[0]['status'], 'succeeded')
        self.assert_publication(1)


if __name__ == '__main__':
    unittest.main()
