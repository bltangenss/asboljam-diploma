"""Day factors: strict import, known-in-advance use only, and the factor model end to end."""
from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from apps.api import engine, factors
from apps.api.db import Job, Record
from apps.api.importing import SCHEMAS, parse_csv
from apps.api.main import create_app
from apps.worker.main import run_once
from scripts import seed_demo

PASSWORD = 'Day-factor-fixture-2026!'
ORIGIN = {'Origin': 'http://localhost:3000'}
START, LAST = date(2025, 1, 1), date(2025, 6, 30)


def csv_text(rows):
    return 'date,branch_id,factor,value,data_origin\n' + ''.join(f'{d},{b},{f},{v},SYNTHETIC\n' for d, b, f, v in rows)


def history(holiday_lift=3.0):
    """Two meals; a known holiday flag multiplies sales, nothing else explains it."""
    holidays = {START + timedelta(days=step) for step in range(9, 181, 11)}
    sales, rows, day = [], [], START
    while day <= LAST + timedelta(days=1):
        flag = int(day in holidays)
        rows += [(day.isoformat(), '1', 'public_holiday', flag), (day.isoformat(), '1', 'school_holiday', 0)]
        if day <= LAST:
            for meal, base in (('1', 20), ('2', 9)):
                units = round(base * (holiday_lift if flag else 1.0) + (day.weekday() == 4) * 2)
                sales.append({'date': day.isoformat(), 'branch_id': '1', 'meal_id': meal, 'units_sold': units,
                              'price_kzt': '1000', 'promo': 0, 'stockout_flag': 0})
        day += timedelta(days=1)
    return sales, [{'date': d, 'branch_id': b, 'factor': f, 'value': str(v)} for d, b, f, v in rows], holidays


class ImportTests(unittest.TestCase):
    def test_day_factors_is_an_optional_known_schema(self):
        self.assertEqual(SCHEMAS['day_factors'].split(), ['date', 'branch_id', 'factor', 'value', 'data_origin'])
        self.assertEqual(len(factors.ORDER), 20)
        self.assertEqual(len(factors.IMPORTED) + len(factors.DERIVED), 20)

    def test_values_are_checked_against_the_factor_registry(self):
        rows, errors = parse_csv('day_factors', csv_text([
            ('2025-01-01', '1', 'public_holiday', '1'), ('2025-01-01', '1', 'temperature_forecast_c', '-21.5'),
            ('2025-01-02', '1', 'iftar_minutes', '1124')]))
        self.assertEqual(errors, [])
        self.assertEqual([row['value'] for row in rows], ['1', '-21.5', '1124'])
        for code, value, expected in (('unknown_code', '1', 'UNKNOWN_FACTOR'), ('public_holiday', '0.5', 'FACTOR_NOT_FLAG'),
                                      ('public_holiday', '2', 'FACTOR_OUT_OF_RANGE'), ('payday', '-1', 'FACTOR_OUT_OF_RANGE'),
                                      ('office_occupancy_pct', '101', 'FACTOR_OUT_OF_RANGE')):
            with self.subTest(code=code, value=value):
                _, errors = parse_csv('day_factors', csv_text([('2025-01-01', '1', code, value)]))
                self.assertEqual([error['code'] for error in errors], [expected])


class EngineTests(unittest.TestCase):
    def test_without_factors_the_three_history_models_are_unchanged(self):
        sales, _, _ = history()
        result = engine.forecast(sales, '1', LAST.isoformat(), 'hist_gradient_boosting')
        self.assertEqual([row['model'] for row in result['metrics']], list(engine.HISTORY_MODELS))
        self.assertNotIn('factor_model', result['metadata'])

    def test_factor_model_learns_a_known_holiday_and_reports_its_inputs(self):
        sales, rows, _ = history()
        result = engine.forecast(sales, '1', LAST.isoformat(), engine.FACTOR_MODEL, factors=rows)
        metrics = {row['model']: row for row in result['metrics']}
        self.assertEqual(list(metrics), list(engine.MODELS))
        self.assertLess(metrics[engine.FACTOR_MODEL]['mae'], metrics['hist_gradient_boosting']['mae'])
        meta = result['metadata']['factor_model']
        self.assertEqual([item['code'] for item in meta['used']], ['public_holiday', 'school_holiday'])
        self.assertIn({'code': 'precipitation_mm', 'reason': 'no_data', 'coverage': 0.0}, meta['skipped'])
        self.assertEqual(meta['assumptions'], ['TARGET_PRICE_LAST_KNOWN', 'TARGET_PROMO_ASSUMED_NONE'])
        self.assertEqual(result['metadata']['features'], meta['features'])

    def test_the_target_day_value_is_used_and_later_rows_are_ignored(self):
        sales, rows, _ = history()
        target = (LAST + timedelta(days=1)).isoformat()
        def predict(changed):
            result = engine.forecast(sales, '1', LAST.isoformat(), engine.FACTOR_MODEL, factors=changed)
            return [item['point_forecast'] for item in result['predictions']], result['metrics']
        holiday = [dict(row, value='1') if row['date'] == target and row['factor'] == 'public_holiday' else row
                   for row in rows]
        ordinary, _ = predict(rows)
        festive, _ = predict(holiday)
        self.assertGreater(festive[0], ordinary[0] * 1.5)
        after = rows + [{'date': (LAST + timedelta(days=5)).isoformat(), 'branch_id': '1', 'factor': 'public_holiday',
                         'value': '1'}]
        self.assertEqual(predict(after), predict(rows))

    def test_missing_target_value_or_low_coverage_skips_a_factor(self):
        sales, rows, _ = history()
        target = (LAST + timedelta(days=1)).isoformat()
        no_target = [row for row in rows if not (row['date'] == target and row['factor'] == 'school_holiday')]
        meta = engine.forecast(sales, '1', LAST.isoformat(), 'seasonal_naive_7', factors=no_target)['metadata']['factor_model']
        self.assertIn('school_holiday', {item['code'] for item in meta['skipped'] if item['reason'] == 'no_target_value'})
        sparse = [row for index, row in enumerate(rows) if row['factor'] != 'school_holiday' or index % 3 == 0 or row['date'] == target]
        meta = engine.forecast(sales, '1', LAST.isoformat(), 'seasonal_naive_7', factors=sparse)['metadata']['factor_model']
        self.assertIn('school_holiday', {item['code'] for item in meta['skipped'] if item['reason'] == 'low_coverage'})

    def test_factor_model_refuses_without_usable_factors_and_invalid_rows(self):
        sales, rows, _ = history()
        with self.assertRaisesRegex(ValueError, 'usable day factor'):
            engine.forecast(sales, '1', LAST.isoformat(), engine.FACTOR_MODEL, factors=[])
        with self.assertRaisesRegex(ValueError, 'Invalid day factor'):
            engine.forecast(sales, '1', LAST.isoformat(), engine.FACTOR_MODEL,
                            factors=rows + [{'date': '2025-02-01', 'branch_id': '1', 'factor': 'nauryz', 'value': '7'}])
        duplicate = rows + [dict(rows[0])]
        with self.assertRaisesRegex(ValueError, 'Duplicate day factor'):
            engine.forecast(sales, '1', LAST.isoformat(), engine.FACTOR_MODEL, factors=duplicate)


class SeedAndApiTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir='.cache', prefix='factor-tests-')
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {'ASBOLJAM_ENV': 'local'})
        environment.start()
        self.addCleanup(environment.stop)

    def app(self, dataset):
        url = 'sqlite:///' + (Path(self.temp.name).resolve() / (dataset + '.sqlite')).as_posix()
        app = create_app(url)
        self.addCleanup(app.state.engine.dispose)
        seed_demo.seed(app.state.sessions, PASSWORD, dataset=dataset)
        client = TestClient(app)
        self.addCleanup(client.close)
        response = client.post('/api/v1/session/login', json={'email': 'admin@asboljam.local', 'password': PASSWORD},
                               headers=ORIGIN)
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({**ORIGIN, 'X-CSRF-Token': response.json()['csrf_token']})
        return app, client

    def factor_count(self, app):
        with app.state.sessions() as db:
            return db.scalar(select(func.count()).select_from(Record).where(Record.kind == 'day_factors'))

    def test_raw_demo_has_no_factors_and_refuses_the_factor_model(self):
        app, client = self.app('raw')
        self.assertEqual(self.factor_count(app), 0)
        refused = client.post('/api/v1/forecasts', json={'branch_id': '1', 'origin': '2025-12-31',
                                                         'model': engine.FACTOR_MODEL})
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertEqual(refused.json()['detail']['code'], 'DAY_FACTORS_REQUIRED')
        queued = client.post('/api/v1/forecasts', json={'branch_id': '1', 'origin': '2025-12-31', 'model': 'seasonal_naive_7'})
        with app.state.sessions() as db:
            job = db.get(Job, queued.json()['run_id'])
            self.assertNotIn('day_factors', job.snapshot)
            self.assertNotIn('day_factors', {selector['kind'] for selector in job.snapshot['input_lineage']['selectors']})

    def test_kz_demo_forecast_uses_factors_through_the_worker_and_tracks_their_lineage(self):
        app, client = self.app('kz')
        self.assertGreater(self.factor_count(app), 20000)
        catalogue = client.get('/api/v1/factors', params={'branch_id': '2', 'target_date': '2026-01-01'}).json()
        items = {item['code']: item for item in catalogue['items']}
        self.assertEqual(list(items), factors.ORDER)
        self.assertEqual((items['public_holiday']['target_value'], items['public_holiday']['last_date']), ('1', '2026-01-01'))
        self.assertEqual((items['station_trains']['days'], items['station_trains']['first_date']), (0, None))
        self.assertEqual(items['promo']['origin'], 'daily_sales')
        queued = client.post('/api/v1/forecasts', json={'branch_id': '2', 'origin': '2025-12-31',
                                                        'model': engine.FACTOR_MODEL})
        self.assertEqual(queued.status_code, 202, queued.text)
        identifier = queued.json()['run_id']
        with app.state.sessions() as db:
            job = db.get(Job, identifier)
            history_days = {(date(2024, 1, 1) + timedelta(days=step)).isoformat() for step in range(731)}
            self.assertLessEqual({row['date'] for row in job.snapshot['day_factors']} - {'2026-01-01'}, history_days)
            self.assertEqual(max(row['date'] for row in job.snapshot['day_factors']), '2026-01-01')
            selectors = {selector['kind']: selector for selector in job.snapshot['input_lineage']['selectors']}
            self.assertEqual(selectors['day_factors']['date_lte'], '2026-01-01')
        self.assertTrue(run_once(app.state.sessions))
        forecast = client.get('/api/v1/forecasts/' + identifier).json()
        self.assertEqual(forecast['model'], engine.FACTOR_MODEL)
        self.assertEqual([row['model'] for row in forecast['metrics']], list(engine.MODELS))
        used = {item['code']: item['target_value'] for item in forecast['metadata']['factor_model']['used']}
        self.assertEqual(used['public_holiday'], 1.0)
        self.assertEqual(forecast['input_freshness'], 'unchanged')

    def test_existing_demo_gains_factors_once_and_a_raw_demo_never_does(self):
        app, _ = self.app('kz')
        with app.state.sessions() as db:
            db.query(Record).filter(Record.kind == 'day_factors').delete()
            db.commit()
        seed_demo.seed(app.state.sessions, PASSWORD, dataset='kz')
        count = self.factor_count(app)
        self.assertGreater(count, 20000)
        seed_demo.seed(app.state.sessions, PASSWORD, dataset='kz')
        self.assertEqual(self.factor_count(app), count)
        raw, _ = self.app('raw')
        seed_demo.seed(raw.state.sessions, PASSWORD, dataset='kz')
        self.assertEqual(self.factor_count(raw), 0)


if __name__ == '__main__':
    unittest.main()
