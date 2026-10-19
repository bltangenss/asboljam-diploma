"""Explicit, versioned daily choices; forecasts, cooking variants and purchases stay immutable."""
from datetime import date
from typing import Annotated, Literal
import uuid

from fastapi import Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import Audit, Forecast, Idempotency, ProductionPlan, WorkingPlanSelection, now
from .production import SourceId, digest, forecast_context, reject, require_fresh, validate_production_binding


ReasonCode = Literal['confirmed_order', 'expected_attendance', 'ingredient_shortage',
                     'kitchen_capacity', 'manager_experience', 'other']


class WorkingPlanInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: SourceId
    production_plan_id: SourceId
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    reason_code: ReasonCode
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator('reason', mode='before')
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


def working_plan_history(db, organization_id, branch_id, target_date):
    """Latest version first. Reading history never creates a selection or a snapshot."""
    return list(db.scalars(select(WorkingPlanSelection).where(
        WorkingPlanSelection.organization_id == organization_id,
        WorkingPlanSelection.branch_id == branch_id,
        WorkingPlanSelection.target_date == target_date,
    ).order_by(WorkingPlanSelection.version.desc())))


def serialize_selection(row):
    return {name: getattr(row, name) for name in (
        'id', 'production_plan_id', 'forecast_id', 'target_date', 'selected_at', 'actor_id',
        'reason_code', 'reason', 'version', 'data_origin', 'usage_mode')}


def working_plan_view(db, organization_id, branch_id, target_date):
    history = [serialize_selection(row) for row in working_plan_history(db, organization_id, branch_id, target_date)]
    return {'version': history[0]['version'] if history else 0,
            'selection': history[0] if history else None, 'history': history}


def register_working_plan_routes(app, *, current, get_db, roles, branch_access, scoped):
    @app.get('/api/v1/working-plan')
    def get_working_plan(branch_id: str, target_date: date, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst', 'warehouse')
        branch_access(db, user, branch_id)
        return working_plan_view(db, user.organization_id, branch_id, target_date.isoformat())

    @app.post('/api/v1/working-plan', status_code=201)
    def select_working_plan(data: WorkingPlanInput, idempotency_key: str | None = Header(None),
                            user=Depends(current), db=Depends(get_db)):
        # current() serializes tenant mutations and rechecks session/Origin/CSRF.
        # Replays must still pass the current role and document scope checks.
        roles(user, 'admin', 'manager')
        branch_access(db, user, data.branch_id)
        production = scoped(db, ProductionPlan, user, data.production_plan_id)
        if production.branch_id != data.branch_id:
            reject('BRANCH_MISMATCH', 'Дайындау жоспарының бөлімшесі сәйкес емес.')
        forecast = scoped(db, Forecast, user, production.forecast_id)
        if not idempotency_key or not 8 <= len(idempotency_key) <= 128 or idempotency_key != idempotency_key.strip():
            reject('IDEMPOTENCY_REQUIRED', 'Idempotency-Key тақырыбы 8–128 таңбадан тұруы керек.')
        payload_hash = digest({'action': 'working-plan.select.v1', 'payload': data.model_dump()})
        old = db.scalar(select(Idempotency).where(Idempotency.organization_id == user.organization_id,
            Idempotency.actor_id == user.id, Idempotency.key == idempotency_key))
        if old:
            if old.payload_hash != payload_hash:
                reject('IDEMPOTENCY_CONFLICT', 'Кілт басқа сұрауға қолданылған.', 409)
            return old.response
        validate_production_binding(production, forecast, data.branch_id)
        context = forecast_context(db, user.organization_id, forecast)
        require_fresh(db, user.organization_id, forecast.result.get('input_lineage'))
        require_fresh(db, user.organization_id, production.input_lineage)
        history = working_plan_history(db, user.organization_id, data.branch_id, production.target_date)
        version = history[0].version if history else 0
        if data.expected_version != version:
            reject('WORKING_PLAN_VERSION_CONFLICT', 'Жұмыс нұсқасы өзгерді. Жаңартып, таңдауды тексеріңіз.', 409)
        row = WorkingPlanSelection(id=uuid.uuid4().hex, organization_id=user.organization_id,
            branch_id=data.branch_id, target_date=production.target_date, production_plan_id=production.id,
            forecast_id=forecast.id, actor_id=user.id, selected_at=now(), reason_code=data.reason_code,
            reason=data.reason, version=version + 1, data_origin=context['data_origin'], usage_mode=context['usage_mode'])
        try:
            db.add(row)
            db.flush()
            result = {'version': row.version, 'selection': serialize_selection(row),
                      'history': [serialize_selection(row), *[serialize_selection(item) for item in history]]}
            db.add(Idempotency(id=uuid.uuid4().hex, organization_id=user.organization_id,
                actor_id=user.id, key=idempotency_key, payload_hash=payload_hash, response=result))
            db.add(Audit(id=uuid.uuid4().hex, organization_id=user.organization_id, branch_id=data.branch_id,
                actor_id=user.id, action='working_plan.selected', entity_id=row.id,
                details={'production_plan_id': production.id, 'forecast_id': forecast.id,
                         'target_date': row.target_date, 'version': row.version,
                         'reason_code': row.reason_code, 'reason': row.reason}))
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            # The same immutable command can be retried through current() safely.
            reject('WORKING_PLAN_CONCURRENT_RETRY', 'Сұрауды сол кілтпен қайталаңыз.', 409)
