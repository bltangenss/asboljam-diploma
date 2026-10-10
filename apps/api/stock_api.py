"""HTTP adapters for explicit stock documents; services own invariants, caller commits."""
from typing import Annotated, Literal

from fastapi import Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from .data_policy import ensure_rows, metadata, policy_context
from .importing import rows_for
from .stock import StockError


SourceId = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')]
BusinessDate = Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')]
Fingerprint = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Version = Annotated[int, Field(strict=True, ge=0)]
Portions = Annotated[int, Field(strict=True, ge=1, le=1000000000)]


class StockInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StockOpen(StockInput):
    branch_id: SourceId
    baseline_date: BusinessDate
    reason: str = Field(min_length=3, max_length=1000)


class StockOpenCommit(StockOpen):
    expected_fingerprint: Fingerprint


class StockCountAnchorInput(StockInput):
    branch_id: SourceId
    count_date: BusinessDate
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    reason: str = Field(min_length=3, max_length=1000)


class StockCountAnchorCommit(StockCountAnchorInput):
    expected_fingerprint: Fingerprint
    acknowledge_differences: Annotated[bool, Field(strict=True)]


class StockLine(StockInput):
    ingredient_id: SourceId
    lot_id: SourceId
    unit: Literal['kg', 'L']
    expiry_date: BusinessDate
    quantity: str = Field(min_length=1, max_length=128)


class RecipeUsage(StockInput):
    portions: dict[SourceId, Portions] = Field(min_length=1, max_length=200)


class StockMovementInput(StockInput):
    branch_id: SourceId
    expected_version: Annotated[int, Field(strict=True, ge=1)]
    kind: Literal['receipt', 'waste', 'adjustment', 'reversal', 'recipe_usage']
    business_date: BusinessDate
    source_reference: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=1000)
    lines: list[StockLine] | None = Field(default=None, min_length=1, max_length=500)
    reverses_id: SourceId | None = None
    recipe_usage: RecipeUsage | None = None


class StockMovementCommit(StockMovementInput):
    expected_fingerprint: Fingerprint


class RecipeRequirementsInput(RecipeUsage):
    branch_id: SourceId
    business_date: BusinessDate


class RecipeRow(StockInput):
    ingredient_id: SourceId
    net_qty_per_portion: str = Field(min_length=1, max_length=128)


class RecipeActivationInput(StockInput):
    branch_id: SourceId
    meal_id: SourceId
    recipe_version: str = Field(min_length=1, max_length=255)
    effective_date: BusinessDate
    expected_version: Version
    reason: str = Field(min_length=3, max_length=1000)
    rows: list[RecipeRow] = Field(min_length=1, max_length=500)


class RecipeActivationCommit(RecipeActivationInput):
    expected_fingerprint: Fingerprint


def register_stock_routes(app, *, current, get_db, roles, branch_access):
    from . import stock_service as service
    from . import stock_recipes as recipes

    def access(request, db, user, branch_id, *, write=False, elevated=False):
        if request.state.auth.kind != 'web':
            raise StockError('NATIVE_STOCK_UNSUPPORTED', 'Use the web stock workflow.', 403)
        roles(user, *(['admin', 'manager'] if elevated else
                      ['admin', 'manager', 'warehouse'] if write else
                      ['admin', 'manager', 'warehouse', 'analyst']))
        branch_access(db, user, branch_id)

    def commit(db, function, user, body, key):
        try:
            result = function(db, user, **body.model_dump(), idempotency_key=key)
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            raise StockError('STOCK_CONCURRENT_WRITE', 'Reload stock and retry the same request key.', 409) from None

    @app.get('/api/v1/stock/catalog')
    def catalog(request: Request, branch_id: SourceId, user=Depends(current), db=Depends(get_db)):
        access(request, db, user, branch_id)
        context = policy_context(db, user.organization_id)
        ingredients = rows_for(db, user.organization_id, 'ingredients')
        meals = rows_for(db, user.organization_id, 'meals')
        ensure_rows(context, ingredients + meals)
        return {**metadata(db, user.organization_id), 'ingredients': ingredients, 'meals': meals}

    @app.get('/api/v1/stock/ledger')
    def position(request: Request, branch_id: SourceId, opening_date: BusinessDate,
                 user=Depends(current), db=Depends(get_db)):
        access(request, db, user, branch_id)
        return service.get_position(db, user, branch_id=branch_id, opening_date=opening_date)

    @app.post('/api/v1/stock/open/preview')
    def preview_open(data: StockOpen, request: Request, user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, write=True)
        return service.preview_open(db, user, **data.model_dump())

    @app.post('/api/v1/stock/open')
    def open_ledger(data: StockOpenCommit, request: Request,
                    key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128),
                    user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, write=True)
        return commit(db, service.open_ledger, user, data, key)

    @app.post('/api/v1/stock/movements/preview')
    def preview_movement(data: StockMovementInput, request: Request, user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, write=True, elevated=data.kind in {'adjustment', 'reversal'})
        return service.preview_movement(db, user, **data.model_dump())

    @app.post('/api/v1/stock/count-anchors/preview')
    def preview_count_anchor(data: StockCountAnchorInput, request: Request,
                             user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, elevated=True)
        return service.preview_count_anchor(db, user, **data.model_dump())

    @app.post('/api/v1/stock/count-anchors')
    def post_count_anchor(data: StockCountAnchorCommit, request: Request,
                          key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128),
                          user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, elevated=True)
        return commit(db, service.post_count_anchor, user, data, key)

    @app.get('/api/v1/stock/count-anchors')
    def count_anchors(request: Request, branch_id: SourceId, limit: int = Query(20, ge=1, le=100),
                      cursor: int = Query(0, ge=0), user=Depends(current), db=Depends(get_db)):
        access(request, db, user, branch_id)
        return service.list_count_anchors(db, user, branch_id=branch_id, limit=limit, cursor=cursor)

    @app.post('/api/v1/stock/movements')
    def post_movement(data: StockMovementCommit, request: Request,
                      key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128),
                      user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, write=True, elevated=data.kind in {'adjustment', 'reversal'})
        return commit(db, service.post_movement, user, data, key)

    @app.get('/api/v1/stock/movements')
    def movements(request: Request, branch_id: SourceId, limit: int = Query(20, ge=1, le=100),
                  cursor: int = Query(0, ge=0), user=Depends(current), db=Depends(get_db)):
        access(request, db, user, branch_id)
        return service.list_movements(db, user, branch_id=branch_id, limit=limit, cursor=cursor)

    @app.get('/api/v1/stock/reconciliation')
    def reconcile(request: Request, branch_id: SourceId, count_date: BusinessDate,
                  user=Depends(current), db=Depends(get_db)):
        access(request, db, user, branch_id)
        result = service.reconcile(db, user, branch_id=branch_id, count_date=count_date)
        return {key: value for key, value in result.items() if key != 'stock_evidence'}

    @app.post('/api/v1/stock/recipe-requirements')
    def requirements(data: RecipeRequirementsInput, request: Request, user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id)
        return service.recipe_requirements_view(db, user, **data.model_dump())

    @app.get('/api/v1/stock/recipes')
    def history(request: Request, branch_id: SourceId, meal_id: SourceId | None = None,
                limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                user=Depends(current), db=Depends(get_db)):
        access(request, db, user, branch_id)
        return recipes.list_activations(db, user, branch_id=branch_id, meal_id=meal_id, limit=limit, offset=offset)

    @app.post('/api/v1/stock/recipes/preview')
    def preview_recipe(data: RecipeActivationInput, request: Request, user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, elevated=True)
        return recipes.preview_activation(db, user, **data.model_dump())

    @app.post('/api/v1/stock/recipes')
    def activate_recipe(data: RecipeActivationCommit, request: Request,
                        key: str = Header(alias='Idempotency-Key', min_length=1, max_length=128),
                        user=Depends(current), db=Depends(get_db)):
        access(request, db, user, data.branch_id, elevated=True)
        return commit(db, recipes.activate_recipe, user, data, key)
