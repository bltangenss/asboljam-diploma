"""Immutable, explicit cooking variants. Saving never posts stock or approves purchases."""
from copy import deepcopy
import hashlib
import json
from typing import Annotated
import uuid

from fastapi import Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .data_policy import execution_context, metadata, policy_context, validate_execution_context
from .db import Audit, Forecast, ProductionPlan, ProductionPlanReceipt, now
from .lineage import input_freshness, input_provenance


SourceId = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')]


class ProductionPortion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    meal_id: SourceId
    portions: Annotated[int, Field(strict=True, ge=0, le=1000000000)]


class ProductionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: SourceId
    forecast_id: SourceId
    name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=3, max_length=1000)
    portions: list[ProductionPortion] = Field(min_length=1, max_length=1000)

    @field_validator('name', 'reason', mode='before')
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


def reject(code, message, status=422):
    raise HTTPException(status, {'code': code, 'message': message})


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def require_fresh(db, organization_id, lineage):
    state = input_freshness(db, organization_id, lineage)
    if state == 'unknown':
        reject('INPUTS_UNVERIFIED', 'Дерек көзі тексерілмеген. Болжамды қайта есептеңіз.', 409)
    if state != 'unchanged':
        reject('INPUTS_CHANGED', 'Кіріс деректері өзгерген. Болжамды қайта есептеңіз.', 409)


def forecast_context(db, organization_id, forecast):
    from .engine import validate_calculation_context
    context = forecast.result.get('execution_context')
    if context is None:
        if policy_context(db, organization_id)['data_origin'] != 'SYNTHETIC':
            reject('EXECUTION_CONTEXT_INVALID', 'Болжамның дерек көзі белгісіз.', 409)
        context = execution_context(db, organization_id, forecast.branch_id, forecast.result.get('origin'))
    validate_execution_context(db, organization_id, context)
    try:
        validate_calculation_context(context, forecast.branch_id, target_date=forecast.result.get('target_date'))
    except ValueError:
        reject('EXECUTION_CONTEXT_INVALID', 'Болжамның күні немесе дерек контексті жарамсыз.', 409)
    if forecast.result.get('branch_id') != forecast.branch_id or forecast.result.get('data_origin') != context['data_origin']:
        reject('DATA_ORIGIN_MISMATCH', 'Болжамның дерек көзі немесе бөлімшесі сәйкес емес.', 409)
    return context


def production_view(db, row, cache=None):
    return {**public_document(row.document),
            'input_freshness': input_freshness(db, row.organization_id, row.input_lineage, state_cache=cache),
            'input_provenance': input_provenance(row.organization_id, row.input_lineage)}


def public_document(document):
    result = deepcopy(document)
    source = result.get('execution_context', {}).get('source')
    if isinstance(source, dict):
        source.pop('authorization_reference', None)
    return result


def validate_production_binding(row, forecast, branch_id):
    """Reject a corrupted/mismatched document without replacing its forecast evidence."""
    document = row.document
    if (row.branch_id != branch_id or row.organization_id != forecast.organization_id
            or row.forecast_id != forecast.id or row.target_date != forecast.result.get('target_date')
            or row.forecast_sha256 != digest(forecast.result)
            or document.get('id') != row.id or document.get('branch_id') != branch_id
            or document.get('forecast_id') != forecast.id or document.get('target_date') != row.target_date
            or document.get('basis') != 'manual_portions'):
        reject('PRODUCTION_PLAN_MISMATCH', 'Дайындау жоспары болжамға, күнге немесе бөлімшеге сәйкес емес.', 409)
    validate_portions(document.get('portions'), forecast.result.get('predictions'))


def validate_portions(portions, predictions):
    if not isinstance(portions, list) or not isinstance(predictions, list) or not predictions:
        reject('PRODUCTION_MEALS_MISMATCH', 'Болжамдағы әр тағамды дәл бір рет көрсетіңіз.')
    expected = [row.get('meal_id') for row in predictions if isinstance(row, dict)]
    actual = [row.get('meal_id') for row in portions if isinstance(row, dict)]
    if (len(expected) != len(predictions) or len(actual) != len(portions)
            or any(not isinstance(meal, str) for meal in expected + actual)
            or len(set(expected)) != len(expected) or len(set(actual)) != len(actual)
            or set(actual) != set(expected)):
        reject('PRODUCTION_MEALS_MISMATCH', 'Болжамдағы әр тағамды дәл бір рет көрсетіңіз. Нөлді ашық енгізіңіз.')
    if any(type(row.get('portions')) is not int or not 0 <= row['portions'] <= 1000000000 for row in portions):
        reject('PRODUCTION_PORTIONS_INVALID', 'Порция саны нөлден бастап бүтін сан болуы керек.')


def register_production_routes(app, *, current, get_db, roles, branch_access, scoped):
    @app.post('/api/v1/production-plans', status_code=201)
    def save_production(data: ProductionInput, idempotency_key: str | None = Header(None),
                        user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager')
        branch_access(db, user, data.branch_id)
        forecast = scoped(db, Forecast, user, data.forecast_id)
        if forecast.branch_id != data.branch_id:
            reject('BRANCH_MISMATCH', 'Болжам бөлімшесі сәйкес емес.')
        if not idempotency_key or not 8 <= len(idempotency_key) <= 128 or idempotency_key != idempotency_key.strip():
            reject('IDEMPOTENCY_REQUIRED', 'Idempotency-Key тақырыбы 8–128 таңбадан тұруы керек.')
        payload = data.model_dump()
        payload['portions'] = sorted(payload['portions'], key=lambda row: row['meal_id'])
        payload_hash = digest(payload)
        scope = (ProductionPlanReceipt.organization_id == user.organization_id,
                 ProductionPlanReceipt.actor_id == user.id, ProductionPlanReceipt.key == idempotency_key)
        old = db.scalar(select(ProductionPlanReceipt).where(*scope))
        if old:
            if old.payload_hash != payload_hash:
                reject('IDEMPOTENCY_CONFLICT', 'Кілт басқа сұрауға қолданылған.', 409)
            # Current permissions were revalidated above; historical receipt remains exact.
            scoped(db, ProductionPlan, user, old.production_plan_id)
            return old.response
        context = forecast_context(db, user.organization_id, forecast)
        require_fresh(db, user.organization_id, forecast.result.get('input_lineage'))
        validate_portions(payload['portions'], forecast.result.get('predictions'))
        predictions = {row['meal_id']: row for row in forecast.result['predictions']}
        identifier, created = uuid.uuid4().hex, now()
        document = dict(id=identifier, branch_id=data.branch_id, forecast_id=forecast.id,
            target_date=forecast.result['target_date'], name=data.name, reason=data.reason,
            actor_id=user.id, created_at=created, basis='manual_portions',
            data_origin=context['data_origin'], usage_mode=context['usage_mode'],
            scenario_date=context['target_date'] if context['data_origin'] == 'SYNTHETIC' else None,
            execution_context=deepcopy(context),
            portions=[dict(row, meal_name=predictions[row['meal_id']].get('meal_name', row['meal_id']),
                           forecast_point=predictions[row['meal_id']].get('point_forecast')) for row in payload['portions']])
        row = ProductionPlan(id=identifier, organization_id=user.organization_id, branch_id=data.branch_id,
            forecast_id=forecast.id, target_date=forecast.result['target_date'], actor_id=user.id,
            document=document, input_lineage=deepcopy(forecast.result['input_lineage']),
            forecast_sha256=digest(forecast.result), created_at=created)
        try:
            db.add(row)
            db.flush()
            result = production_view(db, row)
            db.add(ProductionPlanReceipt(id=uuid.uuid4().hex, organization_id=user.organization_id,
                actor_id=user.id, key=idempotency_key, payload_hash=payload_hash,
                production_plan_id=identifier, response=result))
            db.add(Audit(id=uuid.uuid4().hex, organization_id=user.organization_id, branch_id=data.branch_id,
                actor_id=user.id, action='production_plan.saved', entity_id=identifier,
                details={'forecast_id': forecast.id, 'target_date': row.target_date, 'name': data.name,
                         'reason': data.reason, 'portions_total': sum(r['portions'] for r in payload['portions'])}))
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            # A competing command must be retried through current() again.
            reject('PRODUCTION_CONCURRENT_RETRY', 'Сұрауды сол кілтпен қайталаңыз.', 409)

    @app.get('/api/v1/production-plans')
    def production_list(branch_id: str, forecast_id: str | None = None,
                        limit: int = Query(50, ge=1, le=200), cursor: int = Query(0, ge=0),
                        user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst', 'warehouse')
        branch_access(db, user, branch_id)
        scope = [ProductionPlan.organization_id == user.organization_id, ProductionPlan.branch_id == branch_id]
        if forecast_id is not None:
            forecast = scoped(db, Forecast, user, forecast_id)
            if forecast.branch_id != branch_id:
                reject('BRANCH_MISMATCH', 'Болжам бөлімшесі сәйкес емес.')
            scope.append(ProductionPlan.forecast_id == forecast_id)
        total = db.scalar(select(func.count()).select_from(ProductionPlan).where(*scope))
        rows = db.scalars(select(ProductionPlan).where(*scope)
            .order_by(ProductionPlan.created_at.desc(), ProductionPlan.id.desc()).offset(cursor).limit(limit))
        cache = {}
        return {'items': [production_view(db, row, cache) for row in rows], 'total': total,
                'next_cursor': str(cursor + limit) if cursor + limit < total else None, **metadata(db, user.organization_id)}

    @app.get('/api/v1/production-plans/{production_plan_id}')
    def production_detail(production_plan_id: str, user=Depends(current), db=Depends(get_db)):
        roles(user, 'admin', 'manager', 'analyst', 'warehouse')
        return production_view(db, scoped(db, ProductionPlan, user, production_plan_id))
