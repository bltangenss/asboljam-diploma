"""Worker permission and lease fences; computations are stubbed, DB transactions are real."""
import contextlib
from copy import deepcopy
import io
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, update
from apps.api.db import Audit, Forecast, Job, Organization, Plan, Record, User, make_engine, migrate, sessions
from apps.api.importing import insert_rows
from apps.worker import main as worker
from database_fixture import isolated_database_url


class WorkerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine(isolated_database_url('sqlite:///' + (Path(self.temp.name) / 'worker.sqlite').as_posix()))
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.factory = sessions(self.engine)
        self.snapshot = {
            'sales': [{'branch_id': '1', 'meal_id': '1', 'date': '2025-12-31',
                       'units_sold': 2, 'data_origin': 'SYNTHETIC'}],
            'meals': [{'meal_id': '1', 'meal_name': 'Fixture meal', 'data_origin': 'SYNTHETIC'}],
        }
        self.result = {'branch_id': '1', 'predictions': [{'meal_id': '1', 'point_forecast': 2}],
                       'target_date': '2026-01-01', 'data_origin': 'SYNTHETIC'}
        with self.factory() as db:
            db.add(Organization(id='A',name='Worker fixture',timezone='Asia/Qyzylorda',data_policy='synthetic_only',provenance='test_fixture'))
            db.add(User(id='actor', organization_id='A', email='worker@fixture.invalid',
                        password_hash='unused', role='manager', branch_ids=['1']))
            insert_rows(db, 'A', 'branches', [{'branch_id': '1', 'branch_name': 'Fixture', 'data_origin': 'SYNTHETIC'}])
            db.add(Job(id='job', organization_id='A', branch_id='1', actor_id='actor', kind='forecast',
                       payload={'branch_id': '1', 'origin': '2025-12-31', 'model': 'seasonal_naive_7'},
                       snapshot=deepcopy(self.snapshot)))
            db.commit()

    def job(self):
        with self.factory() as db:
            return db.get(Job, 'job')

    def assert_failed(self, code):
        job = self.job()
        self.assertEqual(job.status, 'failed')
        self.assertTrue(job.error.startswith(code), job.error)
        self.assertIsNone(job.result_id)
        with self.factory() as db:
            self.assertIsNone(db.get(Forecast, 'job'))
            events = list(db.scalars(select(Audit)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].details, {'code': code})
        self.assertEqual((events[0].organization_id, events[0].branch_id), ('A', '1'))

    def test_authorized_job_publishes_once_with_provenance(self):
        with patch.object(worker, 'forecast', return_value=deepcopy(self.result)) as compute:
            self.assertTrue(worker.run_once(self.factory))
            self.assertFalse(worker.run_once(self.factory))
        compute.assert_called_once()
        self.assertEqual(self.job().status, 'succeeded')
        with self.factory() as db:
            result = db.get(Forecast, 'job')
            self.assertEqual(result.organization_id, 'A')
            self.assertEqual(result.result['predictions'][0]['meal_name'], 'Fixture meal')
            self.assertEqual(len(result.result['input_snapshot_sha256']), 64)
            self.assertEqual(len(list(db.scalars(select(Audit)))), 1)

    def test_revoked_actor_is_checked_before_compute(self):
        for change in ({'active': False}, {'branch_ids': ['2']}, {'organization_id': 'B'}, {'role': 'analyst'}, {'role': 'warehouse'}):
            with self.subTest(change=change):
                with self.factory() as db:
                    db.execute(update(User).where(User.id == 'actor').values(
                        active=True, role='manager', branch_ids=['1'], organization_id='A'))
                    db.execute(update(User).where(User.id == 'actor').values(**change))
                    db.execute(update(Job).where(Job.id == 'job').values(status='queued', error=None))
                    # Prior subtest audit is isolated from the next assertion.
                    for event in db.scalars(select(Audit)):
                        db.delete(event)
                    db.commit()
                with patch.object(worker, 'forecast') as compute:
                    worker.run_once(self.factory)
                compute.assert_not_called()
                self.assert_failed('JOB_ACCESS_REVOKED')

    def test_branch_mismatch_in_snapshot_is_rejected_before_compute(self):
        snapshot = deepcopy(self.snapshot)
        snapshot['sales'][0]['branch_id'] = '2'
        with self.factory() as db:
            db.get(Job, 'job').snapshot = snapshot
            db.commit()
        with patch.object(worker, 'forecast') as compute:
            worker.run_once(self.factory)
        compute.assert_not_called()
        self.assert_failed('JOB_SCOPE_INVALID')

    def test_real_snapshot_is_never_silently_relabelled(self):
        snapshot = deepcopy(self.snapshot)
        snapshot['sales'][0]['data_origin'] = 'REAL'
        with self.factory() as db:
            db.get(Job, 'job').snapshot = snapshot
            db.commit()
        with patch.object(worker, 'forecast') as compute:
            worker.run_once(self.factory)
        compute.assert_not_called()
        self.assert_failed('JOB_INPUT_INVALID')

    def test_foreign_procurement_source_is_rejected_before_compute(self):
        with self.factory() as db:
            db.add(Forecast(id='foreign', organization_id='B', branch_id='1', result=self.result))
            job = db.get(Job, 'job')
            job.kind = 'procurement'
            job.payload = {'branch_id': '1', 'forecast_id': 'foreign', 'budget': '100', 'strategy': 'point'}
            job.snapshot = {'forecast_result': self.result}
            db.commit()
        with patch.object(worker, 'procurement') as compute:
            worker.run_once(self.factory)
        compute.assert_not_called()
        self.assert_failed('JOB_SCOPE_INVALID')

    def test_malformed_procurement_forecast_is_failed_without_crashing_worker(self):
        for malformed in (None, [], 'invalid-shape', 7):
            with self.subTest(forecast_result=malformed):
                with self.factory() as db:
                    source = db.get(Forecast, 'source')
                    if source is None:
                        db.add(Forecast(id='source', organization_id='A', branch_id='1', result=malformed))
                    else:
                        source.result = malformed
                    job = db.get(Job, 'job')
                    job.kind = 'procurement'
                    job.status, job.error, job.finished_at = 'queued', None, None
                    job.payload = {'branch_id': '1', 'forecast_id': 'source', 'budget': '100', 'strategy': 'point'}
                    # Match the stored source so this reaches snapshot shape validation.
                    job.snapshot = {
                        'forecast_result': malformed, 'ingredients': [], 'recipes': [],
                        'inventory_lots': [], 'supplier_offers': [], 'suppliers': [],
                    }
                    for event in db.scalars(select(Audit)):
                        db.delete(event)
                    db.commit()
                with patch.object(worker, 'procurement') as compute:
                    self.assertTrue(worker.run_once(self.factory))
                    self.assertFalse(worker.run_once(self.factory))
                compute.assert_not_called()
                self.assert_failed('JOB_INPUT_INVALID')
                with self.factory() as db:
                    self.assertIsNone(db.get(Plan, 'job'))

    def test_access_revoked_during_compute_discards_result(self):
        def calculate(*args):
            with self.factory() as db:
                db.execute(update(User).where(User.id == 'actor').values(active=False))
                db.commit()
            return deepcopy(self.result)
        with patch.object(worker, 'forecast', side_effect=calculate):
            worker.run_once(self.factory)
        self.assert_failed('JOB_ACCESS_REVOKED')

    def test_stale_worker_cannot_publish_over_reclaimed_job(self):
        def calculate(*args):
            with self.factory() as db:
                job = db.get(Job, 'job')
                job.started_at += 1
                db.commit()
            return deepcopy(self.result)
        with patch.object(worker, 'forecast', side_effect=calculate):
            worker.run_once(self.factory)
        self.assertEqual(self.job().status, 'running')
        with self.factory() as db:
            self.assertIsNone(db.get(Forecast, 'job'))
            self.assertEqual(list(db.scalars(select(Audit))), [])

    def test_two_finishers_publish_only_one_result_and_audit(self):
        claimed_at = time.time()
        with self.factory() as db:
            db.execute(update(Job).where(Job.id == 'job').values(status='running', started_at=claimed_at))
            db.commit()
        result = dict(self.result, input_snapshot_sha256='fixture-hash')
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(worker.finish, self.factory, 'job', claimed_at, result=result) for _ in range(2)]
            for outcome in outcomes:
                outcome.result(timeout=10)
        with self.factory() as db:
            self.assertIsNotNone(db.get(Forecast, 'job'))
            self.assertEqual(len(list(db.scalars(select(Audit)))), 1)
        self.assertEqual(self.job().status, 'succeeded')

    def test_exception_values_are_absent_from_errors_audit_and_logs(self):
        sensitive = 'private-input-connection-string-fixture'
        with patch.object(worker, 'forecast', side_effect=RuntimeError(sensitive)), contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            worker.run_once(self.factory)
        self.assert_failed('JOB_CALCULATION_FAILED')
        with self.factory() as db:
            events = [event.details for event in db.scalars(select(Audit))]
        self.assertNotIn(sensitive, out.getvalue() + err.getvalue() + self.job().error + json.dumps(events))

    def test_expired_lease_is_reclaimed_and_validated_again(self):
        with self.factory() as db:
            db.execute(update(Job).where(Job.id == 'job').values(status='running', started_at=time.time() - worker.LEASE_SECONDS - 10))
            db.execute(update(User).where(User.id == 'actor').values(active=False))
            db.commit()
        with patch.object(worker, 'forecast') as compute:
            worker.run_once(self.factory)
        compute.assert_not_called()
        self.assert_failed('JOB_ACCESS_REVOKED')


if __name__ == '__main__':
    unittest.main()
