"""Current workday conditions and per-user read receipts, never business approvals.

GET has no side effects. Stable keys include the condition's evidence, so refreshing a
page cannot create duplicates. Resolved conditions disappear; a changed condition is
new evidence, not a previously dismissed warning. Demo dates never follow the clock.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .data_policy import DEMO_ORIGIN, DEMO_TARGET, business_clock, policy_context
from .day_close import completeness, sales_rows
from .db import DayClosure, Forecast, NotificationReceipt, Plan, RecipeActivation, now
from .engine import history_coverage
from .importing import rows_for
from .lineage import canonical_row, input_freshness
from .stock import StockError
from .stock_recipes import resolve_recipes


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def workday_tasks(db, user, branch_id):
    context = policy_context(db, user.organization_id)
    synthetic = context['data_origin'] == 'SYNTHETIC'
    business_day = date.fromisoformat(DEMO_TARGET) if synthetic else business_clock(context)[1]
    close_day = business_day if synthetic else business_day - timedelta(days=1)
    target = business_day.isoformat()
    origin = DEMO_ORIGIN if synthetic else close_day.isoformat()
    expires_at = None if synthetic else datetime.combine(business_day + timedelta(days=1), time.min,
        ZoneInfo(context['timezone'])).astimezone(timezone.utc).isoformat()
    org = user.organization_id
    menu = rows_for(db, org, 'meals')
    meal_ids = {str(row['meal_id']) for row in menu}
    sales = rows_for(db, org, 'daily_sales', branch_id)
    facts = {str(row['meal_id']): row for row in sales if row['date'] == close_day.isoformat()}
    closure = db.get(DayClosure, (org, branch_id, close_day.isoformat()))
    closure_status = closure.status if closure else 'missing'
    if closure and closure.status == 'closed':
        complete = completeness(closure, menu)
        expected = sales_rows(closure, menu, context['data_origin']) if complete['complete'] else []
        # Extra rows (for example a POS correction of "not offered") also require review.
        if closure.is_open == 0:
            # Current menu prices are not evidence that a closed day's zero sales changed.
            expected = [{key: value for key, value in row.items() if key != 'price_kzt'} for row in expected]
            compared = {meal: {key: value for key, value in row.items() if key != 'price_kzt'} for meal, row in facts.items()}
        else:
            compared = facts
        if not complete['complete'] or {str(row['meal_id']): canonical_row(row) for row in expected} != {
                meal: canonical_row(row) for meal, row in compared.items()}:
            closure_status = 'changed'
    coverage = history_coverage(sales, branch_id, origin)
    observed = {item['meal_id'] for item in coverage['meals']}
    history_ready = bool(meal_ids) and meal_ids <= observed and all(item['status'] == 'ready' for item in coverage['meals'])
    forecast = db.scalar(select(Forecast).where(Forecast.organization_id == org,
        Forecast.branch_id == branch_id, Forecast.result['target_date'].as_string() == target)
        .order_by(Forecast.created_at.desc(), Forecast.id.desc()).limit(1))
    fresh = input_freshness(db, org, forecast.result.get('input_lineage')) if forecast else 'missing'
    plans = list(db.scalars(select(Plan).where(Plan.organization_id == org, Plan.branch_id == branch_id,
        Plan.result['target_date'].as_string() == target).order_by(Plan.created_at.desc(), Plan.id.desc())))
    recipes = rows_for(db, org, 'recipes')
    recipe_status = 'available'
    active = db.scalar(select(RecipeActivation.id).where(RecipeActivation.organization_id == org,
        RecipeActivation.branch_id == branch_id, RecipeActivation.effective_date <= target).limit(1))
    if active and meal_ids:
        try:
            recipes = resolve_recipes(db, org, branch_id, target, meal_ids)['recipes']
        except StockError:
            recipe_status = 'incomplete'
            recipes = []
    grouped = {meal: {row['recipe_version'] for row in recipes if str(row['meal_id']) == meal} for meal in meal_ids}
    missing_recipes = sorted(meal for meal, versions in grouped.items() if len(versions) != 1)
    if not meal_ids or missing_recipes:
        recipe_status = 'incomplete'
    required = {str(row['ingredient_id']) for row in recipes if str(row['meal_id']) in meal_ids}
    lots = [row for row in rows_for(db, org, 'inventory_lots', branch_id) if row['snapshot_date'] == target]
    missing_stock = sorted(required - {str(row['ingredient_id']) for row in lots})
    stock_status = 'available' if lots and not missing_stock else 'incomplete'
    readiness = {
        'sales': {'status': 'complete' if closure_status == 'closed' else 'unconfirmed', 'date': close_day.isoformat(), 'rows': len(facts)},
        'closure': {'status': closure_status, 'date': close_day.isoformat(), 'version': closure.version if closure else 0},
        'history': {'status': 'available' if history_ready else 'incomplete', **coverage, 'missing_meal_ids': sorted(meal_ids - observed)},
        'recipes': {'status': recipe_status, 'date': target, 'missing_meal_ids': missing_recipes},
        'inventory': {'status': stock_status, 'date': target, 'missing_ingredient_ids': missing_stock},
        'forecast': {'status': fresh, 'id': forecast.id if forecast else None, 'date': target},
    }
    items = []

    def add(code, priority, url, details, evidence=None, day=target):
        key = _hash([org, branch_id, day, code, evidence if evidence is not None else details])
        items.append({'id': key, 'code': code, 'priority': priority, 'branch_id': branch_id,
                      'business_date': day, 'action_url': url, 'details': details,
                      'viewed': False, 'expires_at': expires_at})

    if closure_status != 'closed':
        add('DAY_NEEDS_CLOSE', 1, '/day-close?date=' + close_day.isoformat(), readiness['closure'],
            [readiness['closure'], _hash(facts)], close_day.isoformat())
    if not history_ready:
        add('HISTORY_INCOMPLETE', 1, '/sales', {'required_days': coverage['required_days'],
            'ready_meals': coverage['ready_meals'], 'total_meals': len(meal_ids)}, readiness['history'])
    if recipe_status != 'available':
        add('RECIPES_INCOMPLETE', 1, '/recipes', readiness['recipes'])
    if stock_status != 'available':
        add('INVENTORY_INCOMPLETE', 1, '/inventory', readiness['inventory'])
    if forecast and fresh != 'unchanged':
        add('FORECAST_STALE', 1, '/forecasts/' + forecast.id, {'freshness': fresh}, [forecast.id, fresh])
    for plan in plans:
        plan_freshness = input_freshness(db, org, plan.result.get('input_lineage'))
        if plan.status == 'ready':
            add('PROCUREMENT_NEEDS_DECISION', 2, '/procurement/' + plan.id,
                {'plan_id': plan.id, 'freshness': plan_freshness}, [plan.id, plan.version, plan_freshness])
        if plan.status != 'rejected' and plan.result.get('shortage_count', 0) > 0:
            add('PROCUREMENT_SHORTAGE', 3, '/procurement/' + plan.id,
                {'count': plan.result['shortage_count'], 'freshness': plan_freshness}, [plan.id, plan.version, plan_freshness])
    expiring = [row for row in lots if row['expiry_date'] <= (business_day + timedelta(days=2)).isoformat()
                and Decimal(row['on_hand_qty']) > 0]
    if expiring:
        add('LOTS_EXPIRING', 4, '/inventory', {'count': len(expiring), 'snapshot_date': target},
            sorted((row['ingredient_id'], row['lot_id'], row['expiry_date'], row['on_hand_qty']) for row in expiring))
    if forecast and fresh == 'unchanged':
        add('FORECAST_READY', 5, '/forecasts/' + forecast.id, {'forecast_id': forecast.id}, forecast.id)
    viewed = set(db.scalars(select(NotificationReceipt.notification_key).where(
        NotificationReceipt.organization_id == org, NotificationReceipt.branch_id == branch_id,
        NotificationReceipt.user_id == user.id)))
    for item in items:
        item['viewed'] = item['id'] in viewed
    return {'branch_id': branch_id, 'business_date': target, 'data_origin': context['data_origin'],
            'usage_mode': context['usage_mode'], 'items': sorted(items, key=lambda item: (item['priority'], item['code'])),
            'readiness': readiness, 'readiness_notice': 'Data availability is not model confidence or permission to approve procurement.'}


class ViewedInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: str = Field(min_length=1, max_length=64)


def register_workday_task_routes(app, *, current, get_db, roles, branch_access, fail):
    @app.get('/api/v1/workday-tasks')
    def task_list(branch_id: str, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst');branch_access(db, user, branch_id)
        return workday_tasks(db, user, branch_id)

    @app.post('/api/v1/workday-tasks/{notification_id}/view')
    def mark_viewed(notification_id: str, data: ViewedInput, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst');branch_access(db, user, data.branch_id)
        if not any(item['id'] == notification_id for item in workday_tasks(db, user, data.branch_id)['items']):
            fail('NOT_FOUND', 'Тапсырма өзекті емес немесе табылмады.', 404)
        conditions = (NotificationReceipt.organization_id == user.organization_id,
            NotificationReceipt.branch_id == data.branch_id, NotificationReceipt.user_id == user.id,
            NotificationReceipt.notification_key == notification_id)
        old = db.scalar(select(NotificationReceipt).where(*conditions))
        if not old:
            db.add(NotificationReceipt(id=uuid.uuid4().hex, organization_id=user.organization_id,
                branch_id=data.branch_id, user_id=user.id, notification_key=notification_id, viewed_at=now()))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if db.scalar(select(NotificationReceipt).where(*conditions)) is None:
                    raise
        return {'id': notification_id, 'viewed': True}
