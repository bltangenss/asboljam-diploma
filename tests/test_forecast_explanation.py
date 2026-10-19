"""Explanations use saved input only, without training or causal attribution."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from sqlalchemy.orm import sessionmaker

from apps.api.db import Forecast, Job, make_engine
from apps.api.engine import _hash, _normalize_sales
from apps.api.forecast_explanation import explain_forecast
from apps.api.migrations import migrate


class ExplanationTests(unittest.TestCase):
    def setUp(self):
        Path('.cache').mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir='.cache', prefix='explanation-')
        self.addCleanup(temp.cleanup)
        self.engine = make_engine('sqlite:///' + (Path(temp.name).resolve() / 'explanation.sqlite').as_posix())
        self.addCleanup(self.engine.dispose)
        migrate(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.sales = [dict(date=(date(2025, 10, 9) + timedelta(days=i)).isoformat(), branch_id='1', meal_id='01',
            units_sold=i, price_kzt='1200', promo=0, stockout_flag=0, data_origin='SYNTHETIC', oracle_do_not_train='private') for i in range(84)]
        history = _normalize_sales(self.sales, '1', date(2025, 12, 31))
        self.result = dict(origin='2025-12-31', target_date='2026-01-01', model='seasonal_naive_7',
            predictions=[dict(meal_id='01', point_forecast=77)], metadata={'data_hash': _hash(history)})

    def explain(self, *, result=None, snapshot=None, with_job=True, job_org='A'):
        with self.sessions.begin() as db:
            f = Forecast(id='f', organization_id='A', branch_id='1', result=result or self.result)
            db.add(f)
            if with_job:
                db.add(Job(id='job', organization_id=job_org, branch_id='1', actor_id='actor', kind='forecast',
                    status='succeeded', payload={}, snapshot={'sales': self.sales} if snapshot is None else snapshot, result_id='f'))
            db.flush()
            return explain_forecast(db, f)

    def test_seasonal_basis_is_the_exact_saved_date_and_not_current_sales(self):
        result = self.explain()
        self.assertEqual(result['source'], 'saved_job_snapshot')
        self.assertEqual(result['rows'][0]['basis'], {'method': 'seasonal_naive_7', 'from': '2025-12-25', 'to': '2025-12-25', 'value': 77.0})
        self.assertEqual(result['rows'][0]['features']['lag_1'], 83)
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('oracle', json.dumps(result))

    def test_rolling_basis_uses_only_the_saved_28_days(self):
        result = deepcopy(self.result);result['model'] = 'rolling_mean_28';result['predictions'][0]['point_forecast'] = 69.5
        explanation = self.explain(result=result)['rows'][0]['basis']
        self.assertEqual((explanation['from'], explanation['to'], explanation['value']), ('2025-12-04', '2025-12-31', 69.5))

    def test_missing_snapshot_is_explicitly_unavailable(self):
        self.assertEqual(self.explain(with_job=False)['source'], 'unavailable')

    def test_snapshot_from_another_organization_is_never_used(self):
        self.assertEqual(self.explain(job_org='B')['source'], 'unavailable')

    def test_changed_snapshot_and_inconsistent_point_are_not_explained(self):
        changed = deepcopy(self.sales);changed[-1]['units_sold'] = 999
        self.assertEqual(self.explain(snapshot={'sales': changed})['reason'], 'SAVED_INPUT_MISMATCH')

    def test_unverifiable_point_returns_mismatch(self):
        result = deepcopy(self.result);result['predictions'][0]['point_forecast'] = 900
        self.assertEqual(self.explain(result=result)['reason'], 'SAVED_RESULT_MISMATCH')

    def test_factor_inputs_include_saved_assumptions_without_causal_claims(self):
        result = deepcopy(self.result);result['model'] = 'hist_gradient_boosting_factors'
        result['metadata']['factor_model'] = {'features': ['lag_1', 'menu_price_ratio', 'promo', 'stockout_recent', 'rainfall_mm'],
            'used': [{'code': 'rainfall_mm', 'target_value': 4}]}
        explanation = self.explain(result=result)
        self.assertEqual(explanation['rows'][0]['features'], {'lag_1': 83.0, 'menu_price_ratio': 1.0, 'promo': 0.0, 'stockout_recent': 0.0, 'rainfall_mm': 4.0})
        self.assertEqual(explanation['interpretation'], 'reconstructed_inputs_not_causal_contributions')
