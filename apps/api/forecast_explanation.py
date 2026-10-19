"""Non-causal explanations reconstructed from a run's immutable, scoped input.

No current sales, weather or menu values are used. An archived result without a
matching job snapshot is explicitly unavailable rather than explained with today's data.
No fitting or prediction is performed here.
"""
from datetime import date, timedelta
import math
import numpy as np
from sqlalchemy import select

from .db import Job
from .engine import FEATURES, FACTOR_MODEL, _features, _hash, _normalize_sales, _series


def explain_forecast(db, forecast):
    result = forecast.result
    unavailable = {'source': 'unavailable', 'reason': 'SAVED_INPUT_UNAVAILABLE', 'rows': []}
    job = db.scalar(select(Job).where(Job.organization_id == forecast.organization_id,
        Job.branch_id == forecast.branch_id, Job.kind == 'forecast', Job.status == 'succeeded',
        Job.result_id == forecast.id).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
    if not job or not isinstance(job.snapshot, dict):
        return unavailable
    try:
        origin = date.fromisoformat(result['origin'])
        target = date.fromisoformat(result['target_date'])
        if target != origin + timedelta(days=1):
            return unavailable
        history = _normalize_sales(job.snapshot.get('sales', []), forecast.branch_id, origin)
        if _hash(history) != result.get('metadata', {}).get('data_hash'):
            return {**unavailable, 'reason': 'SAVED_INPUT_MISMATCH'}
        series = _series(history, origin)
    except (KeyError, TypeError, ValueError):
        return unavailable
    model = result.get('model')
    points = {str(row['meal_id']): row['point_forecast'] for row in result.get('predictions', [])}
    factor_metadata = result.get('metadata', {}).get('factor_model') or {}
    rows = []
    for category, meal in enumerate(sorted(series)):
        days, values = series[meal]
        features = dict(zip(FEATURES, [float(value) for value in _features(values, target, category)]))
        basis = None
        if model == 'seasonal_naive_7':
            when = (target - timedelta(days=7)).isoformat()
            basis = {'method': model, 'from': when, 'to': when, 'value': float(values[-7])}
        elif model == 'rolling_mean_28':
            basis = {'method': model, 'from': (target - timedelta(days=28)).isoformat(),
                     'to': origin.isoformat(), 'value': float(np.mean(values[-28:]))}
        if basis and not math.isclose(basis['value'], points.get(meal, float('nan')), rel_tol=1e-9, abs_tol=1e-9):
            return {**unavailable, 'reason': 'SAVED_RESULT_MISMATCH'}
        if model == FACTOR_MODEL:
            for item in factor_metadata.get('used', []):
                features[item['code']] = item.get('target_value')
            past = {row['date']: row for row in job.snapshot.get('sales', [])
                    if str(row.get('branch_id')) == forecast.branch_id and str(row.get('meal_id')) == meal and row['date'] <= origin.isoformat()}
            prices = [float(past[day.isoformat()]['price_kzt']) for day in days[-28:] if day.isoformat() in past]
            known = past.get(origin.isoformat(), {}).get('price_kzt')
            features['menu_price_ratio'] = float(known) / float(np.mean(prices)) if known is not None and prices and np.mean(prices) > 0 else None
            features['promo'] = 0
            recent = [past[day.isoformat()].get('stockout_flag') for day in days[-7:] if day.isoformat() in past]
            features['stockout_recent'] = float(np.mean(recent)) if recent and all(value is not None for value in recent) else None
            # Stored feature names are authoritative for what this run actually used.
            features = {key: value for key, value in features.items() if key in factor_metadata.get('features', [])}
        rows.append({'meal_id': meal, 'basis': basis,
            'history': [{'date': day.isoformat(), 'units_sold': float(value)} for day, value in zip(days[-28:], values[-28:])],
            'features': {key: float(value) if value is not None and math.isfinite(float(value)) else None for key, value in features.items()}})
    return {'source': 'saved_job_snapshot', 'origin': origin.isoformat(), 'target_date': target.isoformat(),
            'model': model, 'rows': rows, 'interpretation': 'reconstructed_inputs_not_causal_contributions'}
