"""Prospective review is a closed-fact comparison, not a retrospectively chosen score."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from apps.api.db import (AuthSession, DayClosure, Forecast, Job, Organization, OrganizationSource, ProductionPlan,
                         ReconciliationSnapshot, Record, RecordRevision, User, WorkingPlanSelection, make_engine)
from apps.api.forecast_review import capture_day_snapshot, reconcile_day, review_period
from apps.api.importing import natural_key
from apps.api.lineage import row_digest
from apps.api.migrations import migrate
from apps.api.security import token_hash


DAY = '2026-10-01'
BEFORE = '2026-09-30T18:00:00+00:00'  # before Oct 1 midnight in Asia/Qyzylorda (UTC+5)
LATE = '2026-09-30T19:00:01+00:00'


class ForecastReviewTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='.cache', prefix='forecast-review-')
        self.addCleanup(self.temp.cleanup)
        self.engine = make_engine('sqlite:///' + (Path(self.temp.name).resolve() / 'review.sqlite').as_posix())
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.db.add(Organization(id='one', name='Review fixture', timezone='Asia/Qyzylorda',
                                 currency='KZT', status='active', data_policy='real_only', provenance='test_fixture'))
        self.db.add(OrganizationSource(organization_id='one', source_id='fixture', mapping_version='1',
            branch_id='1', authorization_reference='private-test-reference', purpose='pilot', actor_id='fixture'))
        self.db.flush()
        for meal in ('1', '2'):
            data = {'meal_id': meal, 'meal_name': 'Meal ' + meal, 'base_price_kzt': '1000', 'data_origin': 'REAL'}
            self.db.add(Record(organization_id='one', kind='meals', natural_key=natural_key('meals', data), data=data))
        self.db.commit()

    def forecast(self, identifier='forecast', created=BEFORE, finished=BEFORE, point=(10, 20), intervals=True,
                 branch='1', origin='REAL', usage='PILOT', day=DAY):
        result = {'branch_id': branch, 'data_origin': origin, 'target_date': day,
                  'origin': (date.fromisoformat(day) - timedelta(days=1)).isoformat(),
                  'execution_context': {'timezone': 'Asia/Qyzylorda', 'usage_mode': usage, 'target_date': day},
                  'predictions': [{'meal_id': str(index + 1), 'point_forecast': value,
                      'p10': value - 2 if intervals else None, 'p90': value + 2 if intervals else None}
                      for index, value in enumerate(point)]}
        row = Forecast(id=identifier, organization_id='one', branch_id=branch, result=result, created_at=finished)
        self.db.add(row)
        self.db.add(Job(id=identifier, organization_id='one', branch_id=branch, actor_id='fixture', kind='forecast',
            status='succeeded', payload={}, snapshot={}, result_id=identifier, created_at=created, finished_at=finished))
        self.db.commit()
        return row

    def close(self, actual=(12, 16), *, origin='REAL', day=DAY, stockout=False, not_offered=(), status='closed'):
        lines = []
        for index, value in enumerate(actual):
            meal = str(index + 1)
            if meal in not_offered:
                lines.append({'meal_id': meal, 'state': 'not_offered'})
                continue
            data = {'date': day, 'branch_id': '1', 'meal_id': meal, 'units_sold': value,
                'available_portions': value + 5, 'stockout_flag': int(stockout and index == 0), 'promo': 0,
                'price_kzt': '1000', 'is_open': 1, 'data_origin': origin}
            self.db.add(Record(organization_id='one', kind='daily_sales', branch_id='1',
                               natural_key=natural_key('daily_sales', data), data=data))
            lines.append({'meal_id': meal, 'state': 'sold', **{key: data[key] for key in
                ('units_sold', 'available_portions', 'stockout_flag', 'promo', 'price_kzt')}})
        row = DayClosure(organization_id='one', branch_id='1', business_date=day, status=status, version=2,
            is_open=1, lines=lines, data_origin=origin, created_by='fixture', updated_by='fixture',
            closed_by='fixture', closed_at='2026-10-02T05:00:00+00:00', batch_ids=[])
        self.db.add(row)
        self.db.commit()
        return row

    def working(self, forecast, portions=(12, 16), selected=BEFORE, version=1):
        identifier = 'plan-' + str(version)
        document = {'name': 'Working variant', 'portions': [{'meal_id': str(i + 1), 'portions': value}
                                                            for i, value in enumerate(portions)]}
        self.db.add(ProductionPlan(id=identifier, organization_id='one', branch_id='1', forecast_id=forecast.id,
            target_date=DAY, actor_id='fixture', document=document, input_lineage={}, forecast_sha256='0' * 64, created_at=BEFORE))
        self.db.flush()
        self.db.add(WorkingPlanSelection(id='choice-' + str(version), organization_id='one', branch_id='1',
            target_date=DAY, production_plan_id=identifier, forecast_id=forecast.id, actor_id='fixture',
            selected_at=selected, reason_code='manager_experience', reason='Fixture reason', version=version,
            data_origin='REAL', usage_mode='PILOT'))
        self.db.commit()

    def http_client(self, role='manager', organization='one', branches=None):
        # Importing main has a global application side effect; fence it to this isolated DB.
        url = 'sqlite:///' + (Path(self.temp.name).resolve() / 'review.sqlite').as_posix()
        first_import = 'apps.api.main' not in sys.modules
        with patch.dict(os.environ, {'DATABASE_URL': url, 'ASBOLJAM_ENV': 'local'}):
            from apps.api.main import app as bootstrap_app, create_app
            if first_import:
                # This test created the bootstrap app on its own fixture; release its pool
                # before Windows removes that temporary file. Existing applications are untouched.
                bootstrap_app.state.engine.dispose()
            app = create_app(url)
        self.addCleanup(app.state.engine.dispose)
        identifier, token = uuid.uuid4().hex, uuid.uuid4().hex
        self.db.add(User(id=identifier, organization_id=organization, email=identifier + '@review.test',
                         password_hash='not-used-by-this-auth-session-fixture', role=role, branch_ids=branches or ['1']))
        self.db.add(AuthSession(id=identifier, user_id=identifier, token_hash=token_hash(token), csrf_token='review-csrf',
                                kind='web', expires_at=time.time() + 3600, revoked=False))
        if not self.db.scalar(select(Record).where(Record.organization_id == organization, Record.kind == 'branches')):
            data = {'branch_id': '1', 'branch_name': 'Fixture', 'data_origin': 'REAL'}
            self.db.add(Record(organization_id=organization, kind='branches', branch_id='1',
                               natural_key=natural_key('branches', data), data=data))
        self.db.commit()
        client = TestClient(app);self.addCleanup(client.close)
        client.cookies.set('asboljam_session', token)
        client.headers.update({'Origin': 'http://localhost:3000', 'X-CSRF-Token': 'review-csrf'})
        return client

    def test_metrics_have_signed_error_wape_and_real_interval_denominator(self):
        self.forecast();self.close(stockout=True)
        result = review_period(self.db, 'one', '1', 1, date.fromisoformat(DAY))
        metrics = result['summary']['metrics']
        self.assertEqual((metrics['n'], metrics['mae'], metrics['bias']), (2, 3, 1))
        self.assertAlmostEqual(metrics['wape'], 6 / 28)
        self.assertEqual((metrics['interval_n'], metrics['interval_coverage'], metrics['nominal_coverage']), (2, .5, .8))
        self.assertEqual(result['summary']['stockout_metrics']['n'], 1)
        self.assertEqual(result['summary']['without_stockout_metrics']['n'], 1)
        self.assertEqual(result['latest_closed_day']['date'], DAY)
        self.assertEqual(result['days'][0]['forecast_kind'], 'prospective')
        self.assertNotIn('private-test-reference', str(result))

    def test_latest_early_creation_wins_not_best_accuracy_or_late_result(self):
        self.forecast('earlier', point=(12, 16))
        self.forecast('chosen', created='2026-09-30T18:30:00+00:00', finished='2026-09-30T18:40:00+00:00')
        self.forecast('late-result', created='2026-09-30T18:50:00+00:00', finished=LATE, point=(12, 16))
        self.forecast('retrospective', created=LATE, finished=LATE, point=(12, 16))
        self.close()
        result = reconcile_day(self.db, 'one', '1', DAY)
        self.assertEqual(result['forecast_id'], 'chosen')
        self.assertEqual(result['metrics']['mae'], 3)

    def test_late_or_missing_job_never_enters_prospective_performance(self):
        self.forecast(created=LATE, finished=LATE);self.close()
        result = reconcile_day(self.db, 'one', '1', DAY)
        self.assertEqual(result['forecast_kind'], 'historical')
        self.assertEqual(result['metrics']['n'], 0)
        self.assertEqual(result['demonstration_metrics']['n'], 2)
        self.db.delete(self.db.get(Job, 'forecast'));self.db.commit()
        self.assertEqual(reconcile_day(self.db, 'one', '1', DAY)['forecast_kind'], 'historical')

    def test_explicit_zero_is_not_missing_and_baselines_have_no_interval(self):
        self.forecast(intervals=False);closure = self.close(actual=(0, 0))
        result = reconcile_day(self.db, 'one', '1', DAY)
        self.assertEqual(result['metrics']['n'], 2)
        self.assertIsNone(result['metrics']['wape'])
        self.assertEqual(result['metrics']['wape_notice'], 'ZERO_ACTUAL_TOTAL')
        self.assertEqual(result['metrics']['interval_n'], 0)
        second = self.db.scalar(select(Record).where(Record.kind == 'daily_sales', Record.data['meal_id'].as_string() == '2'))
        self.db.delete(second);self.db.commit()
        missing = reconcile_day(self.db, 'one', '1', DAY)
        self.assertIsNone(missing['rows'][1]['actual_units'])
        self.assertEqual(missing['rows'][1]['fact_status'], 'missing')
        self.assertFalse(missing['complete'])
        self.assertEqual(missing['metrics']['n'], 0)

    def test_unclosed_facts_and_not_offered_are_not_assumed_zero(self):
        self.forecast();closure = self.close(not_offered=('2',), status='draft')
        result = reconcile_day(self.db, 'one', '1', DAY)
        self.assertEqual(result['metrics']['n'], 0)
        closure.status = 'closed';self.db.commit()
        result = reconcile_day(self.db, 'one', '1', DAY)
        self.assertEqual(result['metrics']['n'], 1)
        self.assertEqual(result['rows'][1]['fact_status'], 'not_offered')
        self.assertIsNone(result['rows'][1]['actual_units'])

    def test_synthetic_and_real_test_are_demonstrations_not_business_results(self):
        self.forecast();self.close()
        source = self.db.get(OrganizationSource, 'one');source.purpose = 'test_fixture'
        forecast = self.db.get(Forecast, 'forecast')
        result = deepcopy(forecast.result);result['execution_context']['usage_mode'] = 'TEST';forecast.result = result
        self.db.commit()
        review = review_period(self.db, 'one', '1', 1, date.fromisoformat(DAY))
        self.assertEqual((review['summary']['metrics']['n'], review['summary']['demonstration_metrics']['n']), (0, 2))
        org = self.db.get(Organization, 'one');org.data_policy = 'synthetic_only';self.db.commit()
        self.forecast('demo', origin='SYNTHETIC', usage='DEMO', day='2026-01-01')
        self.close(origin='SYNTHETIC', day='2026-01-01')
        # Explicit demo period never moves scenario dates to the machine clock.
        demo = review_period(self.db, 'one', '1', 1, date(2026, 1, 1))
        self.assertEqual(demo['days'][0]['forecast_kind'], 'synthetic_demo')
        self.assertEqual((demo['summary']['metrics']['n'], demo['summary']['demonstration_metrics']['n']), (0, 2))

    def test_correction_identity_keeps_old_snapshot_and_get_does_not_write(self):
        self.forecast();closure = self.close()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ReconciliationSnapshot)), 0)
        first = capture_day_snapshot(self.db, 'one', '1', DAY);self.db.commit()
        old_document = deepcopy(first.document)
        self.assertEqual(capture_day_snapshot(self.db, 'one', '1', DAY).id, first.id)
        record = self.db.scalar(select(Record).where(Record.kind == 'daily_sales', Record.data['meal_id'].as_string() == '1'))
        before = deepcopy(record.data);after = dict(before, units_sold=13)
        record.data = after
        self.db.add(RecordRevision(id=uuid.uuid4().hex, organization_id='one', kind='daily_sales',
            natural_key=record.natural_key, branch_id='1', revision=1, record_id=record.id, before_data=before,
            after_data=after, before_sha256=row_digest(before), after_sha256=row_digest(after),
            batch_id='fixture', actor_id='fixture', reason='Corrected receipt'))
        self.db.commit()
        changed = reconcile_day(self.db, 'one', '1', DAY)
        self.assertEqual(changed['rows'][0]['fact_status'], 'changed_after_closure')
        self.assertEqual(changed['metrics']['n'], 0)
        lines = deepcopy(closure.lines);lines[0]['units_sold'] = 13
        closure.lines = lines;closure.version += 3;self.db.commit()
        second = capture_day_snapshot(self.db, 'one', '1', DAY);self.db.commit()
        self.assertEqual(second.version, 2)
        self.assertNotEqual(first.input_sha256, second.input_sha256)
        self.assertEqual(first.document, old_document)
        self.assertEqual(second.document['rows'][0]['fact_identity']['revision'], 1)
        review_period(self.db, 'one', '1', 1, date.fromisoformat(DAY))
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ReconciliationSnapshot)), 2)

    def test_working_plan_compares_its_own_baseline_and_late_choice_cannot_replace_early(self):
        earlier = self.forecast('plan-source', point=(10, 20))
        self.forecast('day-source', created='2026-09-30T18:30:00+00:00', finished='2026-09-30T18:40:00+00:00', point=(50, 60))
        self.working(earlier)
        self.working(earlier, portions=(0, 0), selected=LATE, version=2)
        self.close()
        result = review_period(self.db, 'one', '1', 1, date.fromisoformat(DAY))
        self.assertEqual(result['days'][0]['working_plan']['id'], 'choice-1')
        self.assertEqual(result['summary']['adjustment'], {'n': 2, 'forecast_mae': 3, 'plan_mae': 0, 'closer': 2, 'same': 0, 'worse': 0})
        self.assertEqual(result['rows'][0]['forecast_point'], 50)
        self.assertEqual(result['rows'][0]['plan_forecast_point'], 10)

    def test_other_branch_is_not_used_and_latest_closed_day_sets_default(self):
        self.forecast(branch='2');self.close()
        result = review_period(self.db, 'one', '1', 2)
        self.assertEqual(result['date_to'], DAY)
        self.assertEqual(result['latest_closed_day']['forecast_kind'], 'none')
        self.assertEqual(result['summary']['metrics']['n'], 0)

    def test_late_working_choice_is_only_descriptive_and_snapshot_rolls_back_with_caller(self):
        forecast = self.forecast();self.working(forecast, selected=LATE);self.close()
        result = review_period(self.db, 'one', '1', 1, date.fromisoformat(DAY))
        self.assertEqual(result['summary']['adjustment']['n'], 0)
        self.assertEqual(result['summary']['demonstration_adjustment']['n'], 2)
        self.assertFalse(result['days'][0]['working_plan']['prospective'])
        capture_day_snapshot(self.db, 'one', '1', DAY)
        self.db.rollback()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ReconciliationSnapshot)), 0)

    def test_timezone_change_or_unknown_timestamp_does_not_invent_prospective_evidence(self):
        forecast = self.forecast();self.close()
        result = deepcopy(forecast.result);result['execution_context']['timezone'] = 'UTC';forecast.result = result
        self.db.commit()
        self.assertEqual(reconcile_day(self.db, 'one', '1', DAY)['forecast_kind'], 'historical')
        result = deepcopy(forecast.result);result['execution_context']['timezone'] = 'Asia/Qyzylorda';forecast.result = result
        job = self.db.get(Job, 'forecast');job.created_at = '2026-09-30T18:00:00';self.db.commit()
        self.assertEqual(reconcile_day(self.db, 'one', '1', DAY)['forecast_kind'], 'historical')

    def test_http_read_only_get_explicit_refresh_exact_retry_and_history(self):
        self.forecast();self.close();client = self.http_client()
        params = {'branch_id': '1', 'days': 1, 'end_date': DAY}
        read = client.get('/api/v1/forecast-review', params=params)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(ReconciliationSnapshot)), 0)
        key = uuid.uuid4().hex
        saved = client.post('/api/v1/forecast-review/refresh', json=params, headers={'Idempotency-Key': key})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(len(saved.json()['snapshots']), 1)
        snapshot = saved.json()['snapshots'][0]
        self.assertEqual(snapshot['version'], 1)
        self.assertEqual(client.post('/api/v1/forecast-review/refresh', json=params,
                                    headers={'Idempotency-Key': key}).json(), saved.json())
        duplicate = client.post('/api/v1/forecast-review/refresh', json=params, headers={'Idempotency-Key': uuid.uuid4().hex})
        self.assertEqual(duplicate.json()['snapshots'][0]['id'], snapshot['id'])
        conflict = client.post('/api/v1/forecast-review/refresh', json={**params, 'days': 2}, headers={'Idempotency-Key': key})
        self.assertEqual(conflict.status_code, 409)
        history = client.get('/api/v1/forecast-review/history/' + snapshot['id'])
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(history.json()['rows'][0]['actual_units'], 12)
        self.assertEqual(history.json()['snapshot'], snapshot)
        self.assertEqual(client.get('/api/v1/forecast-review', params={**params, 'days': 90, 'end_date': '0001-01-01'}).status_code, 422)
        self.assertEqual(client.get('/api/v1/forecast-review', params={**params, 'days': 1, 'end_date': '0001-01-01'}).status_code, 422)

    def test_http_scope_roles_and_csrf_are_preserved(self):
        self.forecast();self.close();manager = self.http_client()
        params = {'branch_id': '1', 'days': 1, 'end_date': DAY}
        saved = manager.post('/api/v1/forecast-review/refresh', json=params, headers={'Idempotency-Key': uuid.uuid4().hex}).json()
        snapshot_id = saved['snapshots'][0]['id']
        self.assertEqual(manager.get('/api/v1/forecast-review', params={**params, 'branch_id': '2'}).status_code, 403)
        analyst = self.http_client('analyst')
        self.assertEqual(analyst.get('/api/v1/forecast-review', params=params).status_code, 200)
        self.assertEqual(analyst.post('/api/v1/forecast-review/refresh', json=params,
                                     headers={'Idempotency-Key': uuid.uuid4().hex}).status_code, 403)
        warehouse = self.http_client('warehouse')
        self.assertEqual(warehouse.get('/api/v1/forecast-review', params=params).status_code, 403)
        self.assertEqual(manager.post('/api/v1/forecast-review/refresh', json=params,
            headers={'Idempotency-Key': uuid.uuid4().hex, 'X-CSRF-Token': 'wrong'}).status_code, 403)
        self.db.add(Organization(id='other', name='Other', timezone='Asia/Qyzylorda', currency='KZT',
                                 status='active', data_policy='synthetic_only', provenance='test_fixture'))
        self.db.commit()
        other = self.http_client(organization='other')
        self.assertEqual(other.get('/api/v1/forecast-review/history/' + snapshot_id).status_code, 404)

    def test_http_close_reopen_correct_close_preserves_previous_reconciliation(self):
        self.forecast();client = self.http_client()
        lines = [{'meal_id': str(index + 1), 'state': 'sold', 'units_sold': units, 'available_portions': 20,
                  'stockout_flag': 0, 'promo': 0, 'price_kzt': '1000'} for index, units in enumerate((12, 16))]
        def request(method, path, body):
            response = client.request(method, '/api/v1/day-close' + path, json=body,
                                       headers={'Idempotency-Key': uuid.uuid4().hex})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        base = {'branch_id': '1', 'business_date': DAY}
        draft = request('PUT', '', {**base, 'expected_version': 0, 'is_open': 1, 'lines': lines})
        closed = request('POST', '/close', {**base, 'expected_version': draft['version']})
        first = client.get('/api/v1/forecast-review', params={'branch_id': '1', 'days': 1}).json()
        self.assertEqual(len(first['history']), 1)
        identifier = first['history'][0]['id']
        opened = request('POST', '/reopen', {**base, 'expected_version': closed['version'], 'reason': 'Receipt correction'})
        during = client.get('/api/v1/forecast-review', params={'branch_id': '1', 'days': 1, 'end_date': DAY}).json()
        self.assertEqual(during['summary']['metrics']['n'], 0)
        self.assertEqual(during['days'][0]['closure_status'], 'draft')
        lines[0]['units_sold'] = 13
        corrected = request('PUT', '', {**base, 'expected_version': opened['version'], 'is_open': 1, 'lines': lines})
        request('POST', '/close', {**base, 'expected_version': corrected['version'], 'correction_reason': 'Corrected receipt total'})
        latest = client.get('/api/v1/forecast-review', params={'branch_id': '1', 'days': 1}).json()
        self.assertEqual(len(latest['history']), 2)
        self.assertEqual(latest['rows'][0]['actual_units'], 13)
        frozen = client.get('/api/v1/forecast-review/history/' + identifier).json()
        self.assertEqual(frozen['rows'][0]['actual_units'], 12)
        self.assertEqual(frozen['closure_version'], closed['version'])


if __name__ == '__main__':
    unittest.main()
