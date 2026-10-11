"""Reproducible observed-sales forecasting and auditable procurement.

No file access, database access, oracle columns, or generator parameters are used.
All model features are explicitly constructed from dates and past observed sales.
Money and ingredient quantities leave the procurement API as decimal strings.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import importlib.metadata
import json
import math
import platform
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits


MODELS = ("seasonal_naive_7", "rolling_mean_28", "hist_gradient_boosting")
SEED = 42
TEST_DAYS = 28
FEATURES = [
    "meal_category", "day_of_week", "month", "lag_1", "lag_7", "lag_14",
    "lag_28", "rolling_mean_7", "rolling_mean_28", "rolling_std_7",
    "rolling_std_28",
]
ZERO = Decimal("0")
QUANTITY_TOLERANCE = Decimal("0.000001")


def _date(value: object, field: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
        if parsed.isoformat() != str(value):
            raise ValueError()
        return parsed
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO date YYYY-MM-DD") from exc


def validate_calculation_context(context: dict, branch_id: str, *,
                                 origin: str | None = None,
                                 target_date: str | None = None) -> None:
    """Validate the captured contract without a database or today's clock.

    Authorization and current source registration are checked by the worker.
    Unknown synthetic timezone is retained for migrated demo organizations.
    """
    try:
        if (not isinstance(context, dict) or context.get('version') != 'execution-v1'
                or not isinstance(context.get('organization_id'), str) or not context['organization_id']
                or context.get('branch_id') != branch_id or context.get('horizon_days') != 1
                or isinstance(context.get('horizon_days'), bool) or context.get('currency') != 'KZT'):
            raise ValueError()
        origin_day = _date(context['origin'], 'execution origin')
        target = _date(context['target_date'], 'execution target')
        if (target != origin_day + timedelta(days=1)
                or context.get('inventory_snapshot_date') != target.isoformat()
                or origin is not None and context['origin'] != origin
                or target_date is not None and context['target_date'] != target_date):
            raise ValueError()
        as_of = _date(context['as_of_date'], 'execution as_of')
        captured = datetime.fromisoformat(context['as_of_utc'].replace('Z', '+00:00'))
        zone = ZoneInfo(context['timezone']) if context.get('timezone') else timezone.utc
        if (captured.tzinfo is None or captured.utcoffset() != timedelta(0)
                or captured.astimezone(zone).date() != as_of):
            raise ValueError()
        source_origin = context.get('data_origin')
        if source_origin == 'SYNTHETIC':
            if (context.get('data_policy') != 'synthetic_only'
                    or context.get('date_policy') != 'synthetic_fixed'
                    or context.get('usage_mode') != 'DEMO' or context.get('source') is not None
                    or context.get('historical') is not False
                    or context['origin'] != '2025-12-31' or context['target_date'] != '2026-01-01'):
                raise ValueError()
        elif source_origin == 'REAL':
            source = context.get('source')
            if (context.get('data_policy') != 'real_only'
                    or context.get('date_policy') != 'explicit_closed_day'
                    or context.get('usage_mode') not in {'PILOT', 'TEST'}
                    or not isinstance(source, dict) or source.get('branch_id') != branch_id
                    or not context.get('timezone') or origin_day >= as_of
                    or context.get('historical') is not (target < as_of)):
                raise ValueError()
        else:
            raise ValueError()
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError, ZoneInfoNotFoundError):
        raise ValueError('Invalid calculation execution context') from None


def _validate_context_rows(context: dict, rows: list, *, branch_id: str | None = None) -> None:
    if not isinstance(rows, list):
        raise ValueError('Calculation inputs must be row collections')
    for row in rows:
        if not isinstance(row, dict) or row.get('data_origin') != context['data_origin']:
            raise ValueError('Calculation input origin does not match execution context')
        if branch_id is not None and row.get('branch_id') != branch_id:
            raise ValueError('Calculation input branch does not match execution context')


def _context_result(context: dict | None) -> dict:
    return {'execution_context': deepcopy(context), 'data_origin': context['data_origin']} if context is not None else {}


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"{field} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def _integer(value: object, field: str) -> int:
    parsed = _decimal(value, field)
    if parsed != parsed.to_integral_value():
        raise ValueError(f"{field} must be an integer")
    return int(parsed)


def _string(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _versions() -> dict:
    return {"python": platform.python_version(), **{
        name: importlib.metadata.version(name)
        for name in ("numpy", "scipy", "scikit-learn", "threadpoolctl")
    }}


def _normalize_sales(sales: list[dict], branch_id: str, origin: date) -> tuple:
    observed = {}
    for row in sales:
        if str(row["branch_id"]) != branch_id:
            continue
        day = _date(row["date"], "sales.date")
        if day > origin:
            continue  # A later import must never alter this historical run.
        meal = str(row["meal_id"])
        key = (meal, day.isoformat())
        if key in observed:
            raise ValueError(f"Duplicate sales key for branch {branch_id}, meal {meal}, {day}")
        amount = _decimal(row["units_sold"], "units_sold")
        if amount != amount.to_integral_value() or amount > 1_000_000_000:
            raise ValueError("units_sold must be an integer between 0 and 1000000000")
        observed[key] = float(amount)
    if not observed:
        raise ValueError("No observed sales for this branch on or before forecast origin")
    return tuple((meal, day, value) for (meal, day), value in sorted(observed.items()))


def _series(history: tuple, origin: date) -> dict:
    grouped = defaultdict(dict)
    for meal, day, value in history:
        grouped[meal][_date(day, "date")] = value
    result = {}
    for meal, values in grouped.items():
        start = min(values)
        count = (origin - start).days + 1
        if count < 84:
            raise ValueError(f"Meal {meal} needs at least 84 daily observations through origin")
        days = [start + timedelta(days=index) for index in range(count)]
        missing = next((day for day in days if day not in values), None)
        if missing:
            raise ValueError(f"Missing daily sales for meal {meal} on {missing}; missing is not zero")
        result[meal] = (days, np.asarray([values[day] for day in days], dtype=float))
    if len(result) > 255:
        raise ValueError("This model supports at most 255 meal categories per branch")
    return result


def history_coverage(sales: list[dict], branch_id: str, origin: str, *, required_days: int = 84) -> dict:
    """Per-meal diagnostics for an origin. It explains a refusal; it never decides one.

    validate_forecast_history remains the only eligibility rule. Missing days stay
    missing (never zero); statuses name the first thing an operator has to fix.
    """
    origin_day = _date(origin, 'origin')
    days_by_meal = defaultdict(set)
    for row in sales:
        if str(row.get('branch_id')) != str(branch_id):
            continue
        try:
            day = _date(row['date'], 'sales.date')
        except (KeyError, ValueError):
            continue  # Invalid rows are refused by validation, not described here.
        if day <= origin_day:
            days_by_meal[str(row['meal_id'])].add(day)
    meals = []
    for meal, days in sorted(days_by_meal.items()):
        first, last = min(days), max(days)
        span = (origin_day - first).days + 1
        missing = [first + timedelta(days=index) for index in range(span) if first + timedelta(days=index) not in days]
        continuous = 0
        while origin_day - timedelta(days=continuous) in days:
            continuous += 1
        status = ('ended' if last < origin_day else 'gap' if missing else
                  'too_short' if span < required_days else 'ready')
        meals.append({'meal_id': meal, 'status': status, 'first_date': first.isoformat(),
                      'last_date': last.isoformat(), 'observed_days': len(days), 'missing_days': len(missing),
                      'first_missing_date': missing[0].isoformat() if missing else None,
                      'continuous_days_through_origin': continuous})
    return {'origin': origin_day.isoformat(), 'required_days': required_days,
            'ready_meals': sum(item['status'] == 'ready' for item in meals), 'meals': meals}


def validate_forecast_history(sales: list[dict], branch_id: str, origin: str) -> dict:
    """Check completeness without fitting any model or starting a worker job."""
    origin_day = _date(origin, 'origin')
    history = _normalize_sales(sales, str(branch_id), origin_day)
    series = _series(history, origin_day)
    return {'history_start': min(day for _, day, _ in history), 'history_end': origin,
            'meal_count': len(series), 'observations': len(history)}


def _features(past: np.ndarray, target: date, category: int) -> list[float]:
    """The caller passes a strict prefix ending on target minus one day."""
    if len(past) < 28:
        raise ValueError("At least 28 past observations are needed for features")
    return [category, target.weekday(), target.month, past[-1], past[-7], past[-14],
            past[-28], float(np.mean(past[-7:])), float(np.mean(past[-28:])),
            float(np.std(past[-7:])), float(np.std(past[-28:]))]


def _fit_boosting(x: np.ndarray, y: np.ndarray) -> list:
    models = []
    for quantile in (None, 0.1, 0.5, 0.9):
        estimator = HistGradientBoostingRegressor(
            loss="squared_error" if quantile is None else "quantile",
            quantile=quantile, learning_rate=0.08, max_iter=70,
            max_leaf_nodes=15, min_samples_leaf=15,
            categorical_features=[0, 1, 2], early_stopping=False, random_state=SEED,
        )
        estimator.fit(x, y)
        models.append(estimator)
    return models


def _boost_predictions(models: list, x: np.ndarray) -> tuple:
    point = np.maximum(models[0].predict(x), 0)
    raw = np.column_stack([model.predict(x) for model in models[1:]])
    crossing = np.any(np.diff(raw, axis=1) < 0, axis=1)
    corrected = np.sort(np.maximum(raw, 0), axis=1)
    return point, corrected, crossing


def _metrics(model: str, actual: np.ndarray, point: np.ndarray,
             quantiles: np.ndarray | None, crossing: np.ndarray | None,
             test_start: str, test_end: str) -> dict:
    error = point - actual
    total_actual = float(np.sum(np.abs(actual)))
    return {
        "model": model, "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "wape": float(np.sum(np.abs(error)) / total_actual) if total_actual else None,
        "wape_notice": None if total_actual else "WAPE is undefined: total observed test sales is zero.",
        "bias": float(np.mean(error)),
        "bias_definition": "mean(predicted - observed), portions",
        "coverage": float(np.mean((actual >= quantiles[:, 0]) & (actual <= quantiles[:, 2])))
        if quantiles is not None else None,
        "nominal_coverage": 0.8 if quantiles is not None else None,
        "crossing_rate": float(np.mean(crossing)) if crossing is not None else None,
        "crossing_definition": "fraction of raw quantile triplets crossing before sorting",
        "n_observations": len(actual), "test_start": test_start, "test_end": test_end,
    }


@lru_cache(maxsize=8)
def _evaluate(history: tuple, origin_text: str) -> tuple:
    start_timer = time.perf_counter()
    origin = _date(origin_text, "origin")
    test_start = origin - timedelta(days=TEST_DAYS - 1)
    series = _series(history, origin)
    x_train, y_train, x_test, y_test = [], [], [], []
    seasonal, rolling = [], []
    train_dates = []
    for category, (_, (days, values)) in enumerate(sorted(series.items())):
        for index in range(28, len(values)):
            target = days[index]
            features = _features(values[:index], target, category)
            if target < test_start:
                x_train.append(features)
                y_train.append(values[index])
                train_dates.append(target)
            else:
                x_test.append(features)
                y_test.append(values[index])
                seasonal.append(values[index - 7])
                rolling.append(np.mean(values[index - 28:index]))
    if not y_train or len(y_test) != TEST_DAYS * len(series):
        raise ValueError("Insufficient daily data for a common 28-day temporal test")
    actual = np.asarray(y_test)
    with threadpool_limits(limits=1):
        boosted = _fit_boosting(np.asarray(x_train), np.asarray(y_train))
        point, quantiles, crossing = _boost_predictions(boosted, np.asarray(x_test))
    bounds = (test_start.isoformat(), origin.isoformat())
    metrics = [
        _metrics(MODELS[0], actual, np.asarray(seasonal), None, None, *bounds),
        _metrics(MODELS[1], actual, np.asarray(rolling), None, None, *bounds),
        _metrics(MODELS[2], actual, point, quantiles, crossing, *bounds),
    ]
    metadata = {
        "seed": SEED, "features": FEATURES[:], "target": "observed units_sold",
        "data_hash": _hash(history), "runtime_versions": _versions(),
        "history_start": min(day for _, day, _ in history), "history_end": origin_text,
        "train_start": min(train_dates).isoformat(), "train_end": max(train_dates).isoformat(),
        "test_start": bounds[0], "test_end": bounds[1], "test_days": TEST_DAYS,
        "training_observations": len(y_train), "test_observations": len(y_test),
        "evaluation": "One-step rolling origins; fit frozen before test, earlier test observations become past lags.",
        "target_notice": "Observed sales can be censored by stockouts; this is not unconstrained demand.",
        "quantile_correction": "Clamp at zero, then sort p10/p50/p90; raw crossing rate retained.",
        "evaluation_seconds": round(time.perf_counter() - start_timer, 6),
        "model_parameters": {"max_iter": 70, "max_leaf_nodes": 15, "learning_rate": 0.08,
                             "min_samples_leaf": 15, "early_stopping": False},
    }
    return metrics, metadata


def forecast(sales: list[dict], branch_id: str, origin: str = "2025-12-31",
             model: str = "seasonal_naive_7", *, execution_context: dict | None = None) -> dict:
    """Forecast origin+1; all three models share the same real temporal test.

    Only date, branch_id, meal_id and units_sold are read. Baselines deliberately
    have null quantiles. HGB is refitted through origin for its final prediction.
    """
    started = time.perf_counter()
    if model not in MODELS:
        raise ValueError(f"Unknown model; choose one of {', '.join(MODELS)}")
    branch_id = str(branch_id)
    if execution_context is not None:
        validate_calculation_context(execution_context, branch_id, origin=origin)
        _validate_context_rows(execution_context, sales, branch_id=branch_id)
    origin_day = _date(origin, "origin")
    history = _normalize_sales(sales, branch_id, origin_day)
    metrics, metadata = deepcopy(_evaluate(history, origin))
    series = _series(history, origin_day)
    target = origin_day + timedelta(days=1)
    meals = sorted(series)
    intervals = None
    if model == MODELS[2]:
        x_train, y_train, x_future, fit_dates = [], [], [], []
        for category, meal in enumerate(meals):
            days, values = series[meal]
            for index in range(28, len(values)):
                x_train.append(_features(values[:index], days[index], category))
                y_train.append(values[index])
                fit_dates.append(days[index])
            x_future.append(_features(values, target, category))
        with threadpool_limits(limits=1):
            estimators = _fit_boosting(np.asarray(x_train), np.asarray(y_train))
            points, intervals, raw_crossing = _boost_predictions(estimators, np.asarray(x_future))
        metadata["final_fit_start"] = min(fit_dates).isoformat()
        metadata["final_fit_end"] = origin
        metadata["prediction_raw_crossing_rate"] = float(np.mean(raw_crossing))
    else:
        points = np.asarray([series[meal][1][-7] if model == MODELS[0]
                             else np.mean(series[meal][1][-28:]) for meal in meals])
        metadata["final_fit_start"] = None
        metadata["final_fit_end"] = None
        metadata["prediction_raw_crossing_rate"] = None
    predictions = [{
        "meal_id": meal, "point_forecast": float(points[index]),
        **{name: float(intervals[index, column]) if intervals is not None else None
           for column, name in enumerate(("p10", "p50", "p90"))},
    } for index, meal in enumerate(meals)]
    metadata["elapsed_seconds"] = round(time.perf_counter() - started, 6)
    metadata["mode"] = "LIVE_COMPUTE"
    metadata["hash_fields"] = ["meal_id", "date", "units_sold"]
    metadata["branch_id"] = branch_id
    return {
        **_context_result(execution_context),
        "branch_id": branch_id, "origin": origin, "target_date": target.isoformat(),
        "model": model, "predictions": predictions, "metrics": metrics,
        "selected_model_metrics": next(item for item in metrics if item["model"] == model),
        "metadata": metadata,
    }


def _validate_solution(packs: list[int], offers: list[dict], requirements: list[dict],
                       budget: Decimal) -> tuple[bool, list[str]]:
    """Recompute feasibility using Decimal, independently of the solver matrix."""
    errors, purchases = [], defaultdict(lambda: ZERO)
    cost = ZERO
    if len(packs) != len(offers):
        return False, ["Wrong number of offer decisions"]
    for count, offer in zip(packs, offers):
        if not isinstance(count, int) or count < 0 or count > offer["max_packs"]:
            errors.append("Package count is not an integer within offer limits")
        if count and count < offer["min_packs"]:
            errors.append("An active offer violates MOQ")
        if count and offer["lead_time_days"] != 0:
            errors.append("An order cannot arrive on the target day")
        purchases[offer["ingredient_id"]] += count * offer["pack_qty"]
        cost += count * offer["pack_qty"] * offer["unit_cost_kzt"]
    if cost > budget:
        errors.append("Exact decimal total exceeds the budget")
    for row in requirements:
        if row["usable_stock"] + purchases[row["ingredient_id"]] > row["storage_capacity"] + QUANTITY_TOLERANCE:
            errors.append(f"Storage capacity exceeded for ingredient {row['ingredient_id']}")
    return not errors, errors


def _solve(offers: list[dict], requirements: list[dict], budget: Decimal) -> tuple:
    """Lexicographic MILP: relative shortages first, purchase cost second."""
    n, m = len(offers), len(requirements)
    zero_packs = [0] * n
    if not any(row["required_purchase"] > 0 for row in requirements):
        return zero_packs, "no_purchase_required", {"message": "Usable inventory covers the selected forecast."}
    if not offers:
        return [], "no_eligible_offers", {"message": "No offer can arrive on the target date."}
    size = 2 * n + m  # integer packs, binary offer activation, continuous shortage
    lower, upper = np.zeros(size), np.full(size, np.inf)
    integrality = np.zeros(size)
    upper[:n] = [offer["max_packs"] for offer in offers]
    upper[n:2*n] = 1
    integrality[:2*n] = 1
    objective = np.zeros(size)
    cost_objective = np.zeros(size)
    for index, offer in enumerate(offers):
        cost_objective[index] = float(offer["pack_qty"] * offer["unit_cost_kzt"])
    rows, lb, ub = [], [], []

    def constraint(coefficients: np.ndarray, low: float, high: float) -> None:
        rows.append(coefficients)
        lb.append(low)
        ub.append(high)

    for index, offer in enumerate(offers):
        maximum = np.zeros(size)
        maximum[index], maximum[n + index] = 1, -offer["max_packs"]
        constraint(maximum, -np.inf, 0)
        minimum = np.zeros(size)
        minimum[index], minimum[n + index] = -1, offer["min_packs"]
        constraint(minimum, -np.inf, 0)
    for index, requirement in enumerate(requirements):
        incoming = np.zeros(size)
        for j, offer in enumerate(offers):
            if offer["ingredient_id"] == requirement["ingredient_id"]:
                incoming[j] = float(offer["pack_qty"])
        constraint(incoming.copy(), -np.inf,
                   float(requirement["storage_capacity"] - requirement["usable_stock"]))
        incoming[2*n + index] = 1
        needed = float(requirement["required_purchase"])
        upper[2*n + index] = needed
        if needed > 0:
            objective[2*n + index] = 1 / needed
        constraint(incoming, needed, np.inf)
    constraint(cost_objective.copy(), -np.inf, float(budget))
    constraints = LinearConstraint(np.asarray(rows), np.asarray(lb), np.asarray(ub))
    options = {"time_limit": 8.0, "mip_rel_gap": 1e-8, "presolve": True}
    metadata = {"objective": "Minimize sum of ingredient shortage/required_purchase; then minimize exact pack cost.",
                "time_limit_seconds_per_phase": 8, "phases": []}

    def candidate(result: object) -> tuple[list[int] | None, list[str]]:
        vector = getattr(result, "x", None)
        if vector is None or len(vector) < n or not np.all(np.isfinite(vector[:n])):
            return None, ["Solver returned no finite incumbent"]
        rounded = np.rint(vector[:n])
        if np.any(np.abs(vector[:n] - rounded) > 0.00001):
            return None, ["Solver incumbent has fractional package counts"]
        proposed = [int(number) for number in rounded]
        valid, errors = _validate_solution(proposed, offers, requirements, budget)
        return (proposed if valid else None), errors

    try:
        first = milp(objective, integrality=integrality, bounds=Bounds(lower, upper),
                     constraints=constraints, options=options)
        chosen, errors = candidate(first)
        metadata["phases"].append({"phase": "shortage", "status": int(first.status),
                                   "message": str(first.message), "incumbent_valid": chosen is not None})
        metadata["incumbent_errors"] = errors
        if chosen is None:
            metadata["message"] = "No validated incumbent; a zero-purchase plan explicitly retains shortages."
            return zero_packs, "fallback_no_valid_incumbent", metadata
        if first.status != 0:
            return chosen, "feasible_time_limit" if first.status == 1 else "feasible_solver_stopped", metadata
        # Lock the best normalized shortage, then avoid unnecessary purchases.
        best_shortage = float(np.dot(objective, first.x))
        cost_constraints = LinearConstraint(np.vstack([rows, objective]),
                                           np.append(lb, -np.inf), np.append(ub, best_shortage + 1e-9))
        second = milp(cost_objective, integrality=integrality, bounds=Bounds(lower, upper),
                      constraints=cost_constraints, options=options)
        cheaper, errors = candidate(second)
        metadata["phases"].append({"phase": "cost", "status": int(second.status),
                                   "message": str(second.message), "incumbent_valid": cheaper is not None})
        if cheaper is not None:
            # Independently verify phase two did not sacrifice service to save cost.
            def shortage_score(counts: list[int]) -> float:
                purchases = defaultdict(lambda: ZERO)
                for count, offer in zip(counts, offers):
                    purchases[offer["ingredient_id"]] += count * offer["pack_qty"]
                return sum(float(max(ZERO, row["required_purchase"] - purchases[row["ingredient_id"]]) /
                                 row["required_purchase"])
                           for row in requirements if row["required_purchase"] > 0)
            if shortage_score(cheaper) <= shortage_score(chosen) + 1e-7:
                chosen = cheaper
            else:
                cheaper = None
                errors.append("Cost phase worsened independently recomputed shortages")
        metadata["incumbent_errors"] = errors
        status = "optimal" if second.status == 0 and cheaper is not None else "feasible_cost_phase_incomplete"
        if second.status == 1:
            status = "feasible_time_limit"
        return chosen, status, metadata
    except Exception as exc:
        metadata["message"] = f"MILP failed ({type(exc).__name__}); zero purchases retain explicit shortages."
        return zero_packs, "fallback_solver_error", metadata


def procurement(forecast_result: dict, ingredients: list, recipes: list,
                inventory: list, offers: list, suppliers: list, branch_id: str,
                target_date: str, budget: str, strategy: str = "point", *,
                execution_context: dict | None = None) -> dict:
    """Produce a validated same-day integer-package purchasing proposal.

    Snapshot date must equal target date. Expiry on target date is usable under
    this demo convention. Capacity applies before cooking: usable stock+delivery.
    Offer lead time is authoritative, regardless of supplier default lead time.
    """
    started = time.perf_counter()
    branch_id = str(branch_id)
    if execution_context is not None:
        validate_calculation_context(execution_context, branch_id, target_date=target_date)
        if (forecast_result.get('data_origin') != execution_context['data_origin']
                or (forecast_result.get('execution_context') != execution_context
                    and not (execution_context['data_origin'] == 'SYNTHETIC'
                             and forecast_result.get('execution_context') is None))):
            raise ValueError('Forecast execution context does not match procurement')
        for rows in (ingredients, recipes, offers, suppliers):
            _validate_context_rows(execution_context, rows)
        _validate_context_rows(execution_context, inventory, branch_id=branch_id)
    target = _date(target_date, "target_date")
    budget_amount = _decimal(budget, "budget")
    if budget_amount > Decimal("1000000000000"):
        raise ValueError("budget must not exceed 1000000000000 KZT")
    if str(forecast_result.get("branch_id")) != branch_id or forecast_result.get("target_date") != target_date:
        raise ValueError("Forecast branch and target date must match procurement")
    fields = {"point": "point_forecast", "p50": "p50", "p90_stress": "p90"}
    if strategy not in fields:
        raise ValueError("strategy must be point, p50, or p90_stress")
    selected = {}
    for row in forecast_result["predictions"]:
        meal = str(row["meal_id"])
        if meal in selected:
            raise ValueError(f"Duplicate meal prediction {meal}")
        value = row.get(fields[strategy])
        if value is None:
            raise ValueError(f"{strategy} requires available model quantiles; use point for baselines")
        selected[meal] = _decimal(value, fields[strategy])
    if not selected:
        raise ValueError("Forecast has no meal predictions")
    catalog = {}
    for row in ingredients:
        ingredient = str(row["ingredient_id"])
        if ingredient in catalog:
            raise ValueError(f"Duplicate ingredient {ingredient}")
        yield_factor = _decimal(row["yield_factor"], "yield_factor", positive=True)
        if yield_factor > 1:
            raise ValueError("yield_factor must be at most one")
        if row["unit"] not in ("kg", "L"):
            raise ValueError("Ingredient unit must be kg or L")
        catalog[ingredient] = {
            "ingredient_id": ingredient, "ingredient_name": row.get("ingredient_name", ingredient),
            "unit": row["unit"], "yield_factor": yield_factor,
            "storage_capacity": _decimal(row["storage_capacity"], "storage_capacity"),
        }
    net = defaultdict(lambda: ZERO)
    captured_net, captured_gross = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    recipe_keys, recipe_meals = set(), set()
    for row in recipes:
        meal, ingredient = str(row["meal_id"]), str(row["ingredient_id"])
        if meal not in selected:
            continue
        if ingredient not in catalog:
            raise ValueError(f"Recipe refers to unknown ingredient {ingredient}")
        if (meal, ingredient) in recipe_keys:
            raise ValueError("Multiple recipe rows/versions for one meal and ingredient are ambiguous")
        recipe_keys.add((meal, ingredient))
        recipe_meals.add(meal)
        needed = selected[meal] * _decimal(row["net_qty_per_portion"], "net_qty_per_portion", positive=True)
        net[ingredient] += needed
        if 'captured_yield_factor' in row:
            if not row.get('activation_id') or row.get('unit') != catalog[ingredient]['unit']:
                raise ValueError('Captured recipe yield requires activation evidence and matching units')
            factor = _decimal(row['captured_yield_factor'], 'captured_yield_factor', positive=True)
            if factor > 1:
                raise ValueError('Captured yield must be at most one')
            captured_net[ingredient] += needed
            captured_gross[ingredient] += needed / factor
    missing_recipes = sorted(set(selected) - recipe_meals)
    if missing_recipes:
        raise ValueError(f"Missing recipe for meals: {', '.join(missing_recipes)}")
    snapshot = [row for row in inventory if str(row["branch_id"]) == branch_id
                and row["snapshot_date"] == target_date]
    if not snapshot:
        raise ValueError(f"No inventory snapshot for branch {branch_id} on {target_date}; stale stock is not current stock")
    real_stock = execution_context is not None and execution_context['data_origin'] == 'REAL'
    supplied = {str(row['ingredient_id']) for row in snapshot}
    if real_stock:
        if set(net) - supplied:
            raise ValueError('Inventory snapshot is incomplete for required ingredients; unknown stock is not zero')
    stock = defaultdict(lambda: ZERO)
    lot_keys, expired_lots = set(), []
    for row in snapshot:
        ingredient, lot = str(row["ingredient_id"]), str(row["lot_id"])
        if ingredient not in catalog:
            raise ValueError(f"Inventory refers to unknown ingredient {ingredient}")
        if (ingredient, lot) in lot_keys:
            raise ValueError(f"Duplicate inventory lot {lot}")
        lot_keys.add((ingredient, lot))
        if row["unit"] != catalog[ingredient]["unit"]:
            raise ValueError(f"Inventory unit mismatch for ingredient {ingredient}")
        quantity = _decimal(row["on_hand_qty"], "on_hand_qty")
        if _date(row["expiry_date"], "expiry_date") < target:
            expired_lots.append(lot)
        else:
            stock[ingredient] += quantity
    requirements = []
    for ingredient, details in sorted(catalog.items()):
        # A catalog entry is not evidence of a counted zero balance. Required
        # ingredients were checked above; retain other rows only when counted.
        if real_stock and ingredient not in net and ingredient not in supplied:
            continue
        if stock[ingredient] > details["storage_capacity"] + QUANTITY_TOLERANCE:
            raise ValueError(f"Inventory already exceeds storage capacity for ingredient {ingredient}")
        # Keep legacy arithmetic unchanged. Dated recipe rows freeze their own
        # yield, which may differ between meals sharing the same ingredient.
        gross = ((net[ingredient] - captured_net[ingredient]) / details["yield_factor"]
                 + captured_gross[ingredient])
        yield_details = ({'yield_factor': None, 'yield_basis': 'captured_recipe_rows'}
                         if ingredient in captured_gross and captured_net[ingredient] else {})
        requirements.append({**details, **yield_details, "net_required": net[ingredient], "gross_required": gross,
                             "usable_stock": stock[ingredient],
                             "required_purchase": max(ZERO, gross - stock[ingredient])})
    planned_ingredients = {row['ingredient_id'] for row in requirements}
    supplier_map = {str(row["supplier_id"]): row for row in suppliers}
    eligible, excluded, offer_keys = [], [], set()
    for row in offers:
        supplier, ingredient = str(row["supplier_id"]), str(row["ingredient_id"])
        if ingredient not in catalog:
            raise ValueError(f"Offer refers to unknown ingredient {ingredient}")
        key = (supplier, ingredient)
        if key in offer_keys:
            raise ValueError("Duplicate supplier/ingredient offer")
        offer_keys.add(key)
        lead_time = _integer(row["lead_time_days"], "offers.lead_time_days")
        offer = {"supplier_id": supplier, "ingredient_id": ingredient,
                 "pack_qty": _decimal(row["pack_qty"], "pack_qty", positive=True),
                 "unit_cost_kzt": _decimal(row["unit_cost_kzt"], "unit_cost_kzt"),
                 "min_packs": _integer(row["min_packs"], "min_packs"),
                 "max_packs": _integer(row["max_packs"], "max_packs"),
                 "lead_time_days": lead_time}
        if offer["min_packs"] > offer["max_packs"]:
            raise ValueError("min_packs must not exceed max_packs")
        if ingredient not in planned_ingredients:
            excluded.append({"supplier_id": supplier, "ingredient_id": ingredient,
                             "reason": "unobserved_stock_not_required"})
            continue
        if supplier not in supplier_map or lead_time != 0 or offer["max_packs"] == 0:
            excluded.append({"supplier_id": supplier, "ingredient_id": ingredient,
                             "reason": "unknown_supplier" if supplier not in supplier_map
                             else "lead_time" if lead_time else "unavailable"})
        else:
            eligible.append(offer)
    eligible.sort(key=lambda row: (row["ingredient_id"], row["supplier_id"]))
    packs, status, solver = _solve(eligible, requirements, budget_amount)
    valid, errors = _validate_solution(packs, eligible, requirements, budget_amount)
    if not valid:
        raise RuntimeError(f"Internal feasibility check rejected the final plan: {'; '.join(errors)}")
    purchased, total_cost, lines = defaultdict(lambda: ZERO), ZERO, []
    for count, offer in zip(packs, eligible):
        if count == 0:
            continue
        quantity = count * offer["pack_qty"]
        cost = quantity * offer["unit_cost_kzt"]
        total_cost += cost
        purchased[offer["ingredient_id"]] += quantity
        lines.append({
            **{key: _string(value) if isinstance(value, Decimal) else value for key, value in offer.items()},
            "supplier_name": supplier_map[offer["supplier_id"]].get("supplier_name", offer["supplier_id"]),
            "packs": count, "purchased_qty": _string(quantity), "line_cost_kzt": _string(cost),
            "unit": catalog[offer["ingredient_id"]]["unit"],
        })
    rendered = []
    for row in requirements:
        quantity = purchased[row["ingredient_id"]]
        ending = row["usable_stock"] + quantity - row["gross_required"]
        result = {**row, "purchased_qty": quantity, "shortage_qty": max(ZERO, -ending),
                  "ending_stock": max(ZERO, ending), "excess_qty": max(ZERO, ending)}
        rendered.append({key: _string(value) if isinstance(value, Decimal) else value for key, value in result.items()})
    shortage_count = sum(Decimal(row["shortage_qty"]) > QUANTITY_TOLERANCE for row in rendered)
    warnings = []
    if shortage_count:
        warnings.append(f"{shortage_count} ingredients have shortages; the selected forecast cannot be fully served.")
    if budget_amount == 0:
        warnings.append("The budget is zero; only existing stock and zero-cost eligible offers can be used.")
    if status not in ("optimal", "no_purchase_required"):
        warnings.append(f"Solver status: {status}. Only independently validated package decisions are shown.")
    if strategy == "p90_stress":
        warnings.append("Summed marginal p90 is a stress heuristic, not a joint 90% service guarantee.")
    if expired_lots:
        warnings.append(f"{len(expired_lots)} expired inventory lots were excluded.")
    return {
        **_context_result(execution_context),
        "branch_id": branch_id, "target_date": target_date, "strategy": strategy,
        "requirements": rendered, "lines": lines, "total_cost": _string(total_cost),
        "budget": _string(budget_amount), "remaining_budget": _string(budget_amount - total_cost),
        "shortage_count": shortage_count, "solver_status": status, "constraints_valid": valid,
        "constraint_errors": errors, "warnings": warnings, "excluded_offers": excluded,
        "expired_lot_ids": expired_lots, "solver": solver,
        "metadata": {
            "input_hash": _hash({"forecast": forecast_result["predictions"], "ingredients": ingredients,
                                 "recipes": recipes, "inventory": snapshot, "offers": offers,
                                 "suppliers": suppliers, "budget": budget, "strategy": strategy,
                                 "branch_id": branch_id, "target_date": target_date}),
            "runtime_versions": _versions(), "elapsed_seconds": round(time.perf_counter() - started, 6),
            "mode": "LIVE_COMPUTE", "snapshot_date": target_date,
            "capacity_basis": "Usable beginning inventory plus received purchases, before preparation.",
            "cost_basis": "packs * pack_qty * unit_cost_kzt; delivery charges and taxes are absent from source data.",
            "shortage_tolerance": _string(QUANTITY_TOLERANCE),
            "inventory_convention": "Snapshot is before target-day operations; expiry_date >= target_date is usable.",
        },
    }
