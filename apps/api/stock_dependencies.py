"""Period-scoped stock/recipe evidence for immutable procurement results."""
from copy import deepcopy

from sqlalchemy import select

from .db import RecipeActivation, StockLedger, StockMovement
from .stock import day, fingerprint, identifier, reject


def capture_dependencies(db, organization_id, branch_id, target_date, meal_ids):
    identifier(branch_id); day(target_date)
    meals = sorted({identifier(meal) for meal in meal_ids})
    ledger = db.scalar(select(StockLedger).where(StockLedger.organization_id == organization_id,
        StockLedger.branch_id == branch_id, StockLedger.baseline_date <= target_date))
    stock = None
    if ledger is not None:
        from .lineage import input_freshness
        movements = list(db.scalars(select(StockMovement).where(
            StockMovement.ledger_id == ledger.id, StockMovement.business_date < target_date)
            .order_by(StockMovement.sequence)))
        if any(row.organization_id != organization_id or row.branch_id != branch_id for row in movements):
            reject('STOCK_HISTORY_INVALID', 'Journal scope is inconsistent.', 409)
        stock = dict(id=ledger.id, baseline_date=ledger.baseline_date,
            baseline_sha256=fingerprint(ledger.baseline_rows),
            baseline_lineage_sha256=fingerprint(ledger.baseline_lineage),
            baseline_freshness=input_freshness(db, organization_id, ledger.baseline_lineage),
            context_sha256=fingerprint(ledger.data_context),
            movements=[dict(id=row.id, sequence=row.sequence, business_date=row.business_date,
                sha256=fingerprint(dict(kind=row.kind, entries=row.entries,
                    recipe_evidence=row.recipe_evidence, reverses_id=row.reverses_id))) for row in movements])
    recipes = []
    for meal_id in meals:
        row = db.scalar(select(RecipeActivation).where(RecipeActivation.organization_id == organization_id,
            RecipeActivation.branch_id == branch_id, RecipeActivation.meal_id == meal_id,
            RecipeActivation.effective_date <= target_date).order_by(RecipeActivation.effective_date.desc()).limit(1))
        recipes.append(dict(meal_id=meal_id, activation=None if row is None else dict(id=row.id,
            sequence=row.sequence, effective_date=row.effective_date, recipe_version=row.recipe_version,
            rows_sha256=fingerprint(row.rows), context_sha256=fingerprint(row.data_context))))
    return dict(version='stock-dependencies-v1', organization_id=organization_id,
                branch_id=branch_id, target_date=target_date, meal_ids=meals, stock=stock, recipes=recipes)


def dependency_freshness(db, organization_id, evidence):
    if (not isinstance(evidence, dict) or evidence.get('version') != 'stock-dependencies-v1'
            or evidence.get('organization_id') != organization_id):
        return 'unknown'
    try:
        actual = capture_dependencies(db, organization_id, evidence['branch_id'],
                                      evidence['target_date'], evidence['meal_ids'])
        return 'unchanged' if actual == evidence else 'changed'
    except (KeyError, TypeError, ValueError):
        return 'unknown'


def legacy_dependencies_present(db, organization_id, selectors):
    """A legacy snapshot plan predating a now-active journal needs recomputation."""
    for selector in selectors:
        if selector.get('kind') != 'inventory_lots' or not selector.get('branch_id') or not selector.get('snapshot_date'):
            continue
        branch, target = selector['branch_id'], selector['snapshot_date']
        if db.scalar(select(StockLedger.id).where(StockLedger.organization_id == organization_id,
                StockLedger.branch_id == branch, StockLedger.baseline_date <= target).limit(1)):
            return True
        if db.scalar(select(RecipeActivation.id).where(RecipeActivation.organization_id == organization_id,
                RecipeActivation.branch_id == branch, RecipeActivation.effective_date <= target).limit(1)):
            return True
    return False


def prepare_procurement_stock(db, user, snapshot):
    """Use exact counted target stock; an opened journal must independently agree.

    Never relabel an older opening balance as a newly counted target snapshot.
    Active recipes replace legacy CSV recipes as a complete selection for meals.
    """
    from . import stock_service, stock_recipes
    branch = snapshot['forecast_result']['branch_id']
    target = snapshot['forecast_result']['target_date']
    meals = [row['meal_id'] for row in snapshot['forecast_result']['predictions']]
    dependency = capture_dependencies(db, user.organization_id, branch, target, meals)
    snapshot['stock_dependencies'] = dependency
    active = any(item['activation'] is not None for item in dependency['recipes'])
    if active:
        selection = stock_recipes.resolve_recipes(db, user.organization_id, branch, target, meals)
        snapshot['recipes'] = selection['recipes']
        evidence = deepcopy(selection['evidence'])
        evidence['data_context'] = stock_service.public_context(evidence['data_context'])
        snapshot['recipe_evidence'] = dict(source='dated_activations', **evidence,
                                          fingerprint=selection['fingerprint'])
    else:
        snapshot['recipe_evidence'] = dict(source='canonical_csv', effective_date=target,
            recipe_versions=sorted({row['recipe_version'] for row in snapshot['recipes']}))
    if dependency['stock'] is not None:
        checked = stock_service.reconcile(db, user, branch_id=branch, count_date=target)
        if checked['status'] != 'matched':
            reject('STOCK_RECONCILIATION_REQUIRED', 'Reconcile the journal with the exact target-date count before procurement.', 409)
        snapshot['stock_evidence'] = dict(source='reconciled_counted_snapshot', target_date=target,
            ledger_id=checked['ledger_id'], baseline_date=checked['baseline_date'],
            reconciliation_status='matched', fingerprint=checked['stock_fingerprint'],
            movement_count=len(checked['stock_evidence']['movements']))
        # Preserve complete reconciliation as private enqueue-time evidence.
        snapshot['stock_reconciliation'] = checked['stock_evidence']
    else:
        snapshot['stock_evidence'] = dict(source='counted_snapshot', target_date=target)
    return active
