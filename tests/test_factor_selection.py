"""Factor choice for the metrics row looks at training days only; the final refit sees every day."""
from datetime import timedelta
import math
import unittest

import numpy as np

from apps.api import engine, factors
from test_day_factors import LAST, START, history

TARGET = LAST + timedelta(days=1)
TEST_START = LAST - timedelta(days=engine.TEST_DAYS - 1)
ALL_DAYS = (LAST - START).days + 1 - 28  # days with 28 past observations, through the origin
TRAINING_DAYS = ALL_DAYS - engine.TEST_DAYS
TEST_DAYS = [TEST_START + timedelta(days=step) for step in range(engine.TEST_DAYS)]


def without(rows, code, days):
    """Drop one factor on the given days; nothing is filled in their place."""
    gone = {day.isoformat() for day in days}
    return [row for row in rows if not (row['factor'] == code and row['date'] in gone)]


def forecast(sales, rows, model=engine.FACTOR_MODEL):
    return engine.forecast(sales, '1', LAST.isoformat(), model, factors=rows)


def codes(items):
    return [item['code'] for item in items]


class FactorSelectionTests(unittest.TestCase):
    def test_test_day_gaps_do_not_change_the_evaluation_choice(self):
        sales, rows, _ = history()
        full = forecast(sales, rows, 'seasonal_naive_7')['metadata']['factor_model']
        trimmed = forecast(sales, without(rows, 'school_holiday', TEST_DAYS), 'seasonal_naive_7')['metadata']['factor_model']
        self.assertEqual(codes(full['evaluation']['used']), ['public_holiday', 'school_holiday'])
        self.assertEqual(trimmed['evaluation'], full['evaluation'])
        # The final refit does see the 28 missing days and says so instead of using the factor.
        self.assertEqual(codes(full['used']), ['public_holiday', 'school_holiday'])
        self.assertEqual(codes(trimmed['used']), ['public_holiday'])
        self.assertIn({'code': 'school_holiday', 'reason': 'low_coverage',
                       'coverage': round(TRAINING_DAYS / ALL_DAYS, 4)}, trimmed['skipped'])

    def test_training_coverage_cannot_be_borrowed_from_the_test_days(self):
        sales, rows, _ = history()
        gaps = [START + timedelta(days=step) for step in range(30, 45)]  # 15 training days after the warm-up
        meta = forecast(sales, without(rows, 'school_holiday', gaps))['metadata']['factor_model']
        training_coverage = round((TRAINING_DAYS - len(gaps)) / TRAINING_DAYS, 4)
        overall_coverage = round((ALL_DAYS - len(gaps)) / ALL_DAYS, 4)
        self.assertLess(training_coverage, factors.MIN_COVERAGE)
        self.assertGreaterEqual(overall_coverage, factors.MIN_COVERAGE)
        self.assertEqual(codes(meta['evaluation']['used']), ['public_holiday'])
        self.assertIn({'code': 'school_holiday', 'reason': 'low_coverage', 'coverage': training_coverage},
                      meta['evaluation']['skipped'])
        self.assertEqual(meta['evaluation']['features'], engine.FEATURES + ['public_holiday'] + list(factors.DERIVED))
        # Through the origin the same factor is covered enough, so only the final refit uses it.
        self.assertEqual({item['code']: item['coverage'] for item in meta['used']},
                         {'public_holiday': 1.0, 'school_holiday': overall_coverage})
        self.assertEqual(meta['features'], engine.FEATURES + ['public_holiday', 'school_holiday'] + list(factors.DERIVED))

    def test_training_coverage_survives_missing_test_days_without_filling(self):
        sales, rows, _ = history()
        rows = without(rows, 'school_holiday', TEST_DAYS)
        result = forecast(sales, rows)
        meta = result['metadata']['factor_model']
        self.assertEqual({item['code']: item['coverage'] for item in meta['evaluation']['used']},
                         {'public_holiday': 1.0, 'school_holiday': 1.0})
        row = next(item for item in result['metrics'] if item['model'] == engine.FACTOR_MODEL)
        self.assertEqual(row['n_observations'], 2 * engine.TEST_DAYS)
        self.assertTrue(math.isfinite(row['mae']) and math.isfinite(row['coverage']))
        self.assertTrue(all(math.isfinite(item['point_forecast']) for item in result['predictions']))
        self.assertEqual(codes(meta['used']), ['public_holiday'])
        data = engine._factor_matrices(engine._normalize_sales(sales, '1', LAST), LAST.isoformat(),
                                       engine._factor_rows(rows, '1', TARGET), engine._sales_extras(sales, '1', LAST),
                                       'evaluation')
        column = len(engine.FEATURES) + data['codes'].index('school_holiday')
        self.assertEqual(data['x_test'].shape[0], 2 * engine.TEST_DAYS)
        self.assertTrue(np.isnan(data['x_test'][:, column]).all())
        self.assertFalse(np.isnan(data['x_train'][:, column]).any())
        self.assertFalse(np.isnan(data['x_future'][:, column]).any())

    def test_both_choices_state_their_days_coverage_and_assumptions(self):
        sales, rows, _ = history()
        result = forecast(sales, rows)
        meta = result['metadata']['factor_model']
        self.assertEqual((meta['selection_days'], meta['days']), ('all_history_through_origin', ALL_DAYS))
        self.assertEqual((meta['evaluation']['selection_days'], meta['evaluation']['days']), ('training', TRAINING_DAYS))
        self.assertEqual(meta['days'] - meta['evaluation']['days'], engine.TEST_DAYS)
        for choice in (meta, meta['evaluation']):
            self.assertTrue(all('coverage' in item for item in choice['used'] + choice['skipped']))
            self.assertEqual(len(choice['used']) + len(choice['skipped']), len(factors.IMPORTED))
        self.assertEqual(meta['assumptions'], ['TARGET_PRICE_LAST_KNOWN', 'TARGET_PROMO_ASSUMED_NONE'])
        self.assertEqual((meta['min_coverage'], meta['derived']), (factors.MIN_COVERAGE, list(factors.DERIVED)))
        for key in ('known_in_advance', 'factors_hash', 'sales_extras_hash'):
            self.assertIn(key, meta)
        self.assertEqual(result['metadata']['features'], meta['features'])

    def test_empty_final_choice_is_refused_for_the_factor_model_and_reported_for_others(self):
        sales, rows, _ = history()
        for code in ('public_holiday', 'school_holiday'):
            rows = without(rows, code, TEST_DAYS)
        with self.assertRaisesRegex(ValueError, 'coverage through the origin'):
            forecast(sales, rows)
        result = forecast(sales, rows, 'seasonal_naive_7')
        meta = result['metadata']['factor_model']
        self.assertIn(engine.FACTOR_MODEL, {item['model'] for item in result['metrics']})
        self.assertEqual(codes(meta['evaluation']['used']), ['public_holiday', 'school_holiday'])
        self.assertEqual(meta['used'], [])
        self.assertEqual({item['code'] for item in meta['skipped'] if item['reason'] == 'low_coverage'},
                         {'public_holiday', 'school_holiday'})


if __name__ == '__main__':
    unittest.main()
