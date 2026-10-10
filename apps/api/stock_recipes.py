"""Dated complete recipe decisions, independent of the nine canonical CSVs.

Services never commit. The caller commits success or rolls back every error.
Only explicit activation creates a version; a CSV import is never an activation.
Snapshots and receipts are append-only, and consumed history cannot be rewritten.
"""
from copy import deepcopy
import re
import uuid

from sqlalchemy import func, select

from .accounts import lock_user
from .data_policy import ensure_rows, policy_context
from .db import Audit, Organization, RecipeActivation, RecipeCommandReceipt, StockMovement, User
from .importing import rows_for
from .stock import MAX_LINES, day, decimal_text, fingerprint, identifier, quantity, reject


def _scope(db, user, branch_id, *, writing=False):
    identifier(branch_id)
    original_org, actor_id = user.organization_id, user.id
    current = (lock_user(db, actor_id, original_org) if writing else
               db.get(User, actor_id, populate_existing=True))
    org = db.get(Organization, original_org, populate_existing=True)
    if (current is None or current.organization_id != original_org or not current.active
            or org is None or org.status != 'active'):
        reject('STOCK_ACCESS_REVOKED', 'Current organization and actor access is required.', 403)
    allowed_roles = {'admin', 'manager'} if writing else {'admin', 'manager', 'warehouse', 'analyst'}
    if current.role not in allowed_roles or branch_id not in current.branch_ids:
        reject('STOCK_FORBIDDEN', 'This action requires the current role and branch access.', 403)
    context = policy_context(db, current.organization_id)
    ensure_rows(context, [{'branch_id': branch_id, 'data_origin': context['data_origin']}])
    branch = [row for row in rows_for(db, current.organization_id, 'branches') if row.get('branch_id') == branch_id]
    if len(branch) != 1:
        reject('STOCK_BRANCH_UNKNOWN', 'The branch must exist in the scoped catalog.', 404)
    ensure_rows(context, branch)
    return current, context


def _latest(db, organization_id, branch_id, meal_id):
    return db.scalar(select(RecipeActivation).where(
        RecipeActivation.organization_id == organization_id, RecipeActivation.branch_id == branch_id,
        RecipeActivation.meal_id == meal_id).order_by(RecipeActivation.sequence.desc()).limit(1))


def _public_context(context):
    result = deepcopy(context)
    if result.get('source'):
        result['source'].pop('authorization_reference', None)
    return result


def _parameters(*, branch_id, meal_id, recipe_version, effective_date, rows, expected_version, reason):
    identifier(branch_id); identifier(meal_id); day(effective_date)
    if (not isinstance(recipe_version, str) or not recipe_version.strip()
            or len(recipe_version) > 255 or any(ord(char) < 32 for char in recipe_version)):
        reject('STOCK_RECIPE_VERSION_INVALID', 'Use a nonempty unchanged version label of at most 255 characters.')
    if type(expected_version) is not int or not 0 <= expected_version <= 2147483646:
        reject('STOCK_VERSION_INVALID', 'An explicit nonnegative expected version is required.')
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        reject('STOCK_REASON_REQUIRED', 'An operator reason of 3–1000 characters is required.')
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_LINES:
        reject('STOCK_RECIPE_REQUIRED', 'Provide the complete recipe with 1–500 ingredient rows.')
    normalized, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'ingredient_id', 'net_qty_per_portion'}:
            reject('STOCK_RECIPE_ROWS_INVALID', 'Recipe input contains only ingredient_id and net_qty_per_portion.')
        ingredient = identifier(row['ingredient_id'])
        if ingredient in seen:
            reject('STOCK_RECIPE_AMBIGUOUS', 'Each ingredient must occur once in the complete recipe.')
        seen.add(ingredient)
        net = quantity(row['net_qty_per_portion'], positive=True, allow_zero=False)
        normalized.append({'ingredient_id': ingredient, 'net_qty_per_portion': decimal_text(net)})
    return dict(branch_id=branch_id, meal_id=meal_id, recipe_version=recipe_version,
                effective_date=effective_date, rows=sorted(normalized, key=lambda row: row['ingredient_id']),
                expected_version=expected_version, reason=reason.strip())


def _preview(db, user, context, values):
    organization_id, branch_id, meal_id = user.organization_id, values['branch_id'], values['meal_id']
    meal = [row for row in rows_for(db, organization_id, 'meals') if row.get('meal_id') == meal_id]
    if len(meal) != 1:
        reject('STOCK_MEAL_UNKNOWN', 'The meal must exist in the scoped catalog.', 404)
    ensure_rows(context, meal)
    latest = _latest(db, organization_id, branch_id, meal_id)
    current_version = latest.sequence if latest else 0
    if current_version != values['expected_version']:
        reject('STOCK_VERSION_CONFLICT', 'Recipe history changed; preview the current version.', 409)
    if latest and values['effective_date'] <= latest.effective_date:
        reject('STOCK_RECIPE_DATE_ORDER', 'A new activation must follow the latest activation date.', 409)
    if db.scalar(select(RecipeActivation.id).where(RecipeActivation.organization_id == organization_id,
            RecipeActivation.branch_id == branch_id, RecipeActivation.meal_id == meal_id,
            RecipeActivation.recipe_version == values['recipe_version']).limit(1)):
        reject('STOCK_RECIPE_VERSION_EXISTS', 'A version label already identifies an immutable recipe.', 409)
    # Conservatively fence the whole branch: a new activation cannot change any
    # already posted recipe usage, even if its original document was reversed.
    last_usage = db.scalar(select(func.max(StockMovement.business_date)).where(
        StockMovement.organization_id == organization_id, StockMovement.branch_id == branch_id,
        StockMovement.kind == 'recipe_usage'))
    if last_usage and values['effective_date'] <= last_usage:
        reject('STOCK_RECIPE_HISTORY_CLOSED', 'Activate after the latest posted recipe usage date.', 409)
    ingredients = {row['ingredient_id']: row for row in rows_for(db, organization_id, 'ingredients')}
    frozen_rows = []
    for row in values['rows']:
        catalog = ingredients.get(row['ingredient_id'])
        if catalog is None:
            reject('STOCK_INGREDIENT_UNKNOWN', 'An ingredient is absent from the scoped catalog.')
        ensure_rows(context, [catalog])
        if catalog.get('unit') not in {'kg', 'L'}:
            reject('STOCK_UNIT_MISMATCH', 'Recipes require explicit kg or L catalog units.')
        captured_yield = quantity(catalog.get('yield_factor'), positive=True, allow_zero=False)
        if captured_yield > 1:
            reject('STOCK_YIELD_INVALID', 'Yield must be greater than zero and at most one.')
        frozen_rows.append({**row, 'unit': catalog['unit'], 'captured_yield_factor': decimal_text(captured_yield),
                            'ingredient_catalog': deepcopy(catalog)})
    result = {**values, 'organization_id': organization_id, 'version': current_version,
              'next_version': current_version + 1, 'rows': frozen_rows,
              'snapshot_sha256': fingerprint(frozen_rows), 'data_context': deepcopy(context)}
    result['preview_fingerprint'] = fingerprint(result)
    return result


def preview_activation(db, user, *, branch_id, meal_id, recipe_version, effective_date, rows, expected_version, reason):
    values = _parameters(branch_id=branch_id, meal_id=meal_id, recipe_version=recipe_version,
                         effective_date=effective_date, rows=rows, expected_version=expected_version, reason=reason)
    # Preview uses write authorization but never persists a decision.
    user, context = _scope(db, user, branch_id, writing=True)
    preview = _preview(db, user, context, values)
    preview['data_context'] = _public_context(preview['data_context'])
    return preview


def activation_json(row):
    result = {**{field: deepcopy(getattr(row, field)) for field in (
        'id', 'branch_id', 'meal_id', 'recipe_version', 'effective_date', 'rows', 'snapshot_sha256',
        'data_context', 'reason', 'actor_id', 'created_at')}, 'version': row.sequence, 'sequence': row.sequence}
    result['data_context'] = _public_context(result['data_context'])
    return result


def activate_recipe(db, user, *, branch_id, meal_id, recipe_version, effective_date, rows, expected_version,
                    reason, expected_fingerprint, idempotency_key):
    values = _parameters(branch_id=branch_id, meal_id=meal_id, recipe_version=recipe_version,
                         effective_date=effective_date, rows=rows, expected_version=expected_version, reason=reason)
    if not isinstance(expected_fingerprint, str) or not re.fullmatch('[0-9a-f]{64}', expected_fingerprint):
        reject('STOCK_PREVIEW_REQUIRED', 'A current preview fingerprint is required.')
    if not isinstance(idempotency_key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', idempotency_key):
        reject('STOCK_IDEMPOTENCY_INVALID', 'Use a bounded opaque idempotency key.')
    user, context = _scope(db, user, branch_id, writing=True)
    payload_hash = fingerprint({**values, 'expected_fingerprint': expected_fingerprint})
    receipt = db.scalar(select(RecipeCommandReceipt).where(
        RecipeCommandReceipt.organization_id == user.organization_id, RecipeCommandReceipt.actor_id == user.id,
        RecipeCommandReceipt.key == idempotency_key))
    if receipt:
        if receipt.payload_hash != payload_hash:
            reject('STOCK_IDEMPOTENCY_CONFLICT', 'This idempotency key belongs to another command.', 409)
        return deepcopy(receipt.response)
    preview = _preview(db, user, context, values)
    if preview['preview_fingerprint'] != expected_fingerprint:
        reject('STOCK_PREVIEW_STALE', 'Recipe inputs changed after preview; review them again.', 409)
    activation = RecipeActivation(id=uuid.uuid4().hex, organization_id=user.organization_id,
        branch_id=branch_id, meal_id=meal_id, sequence=preview['next_version'], recipe_version=recipe_version,
        effective_date=effective_date, rows=preview['rows'], snapshot_sha256=preview['snapshot_sha256'],
        data_context=preview['data_context'], reason=values['reason'], actor_id=user.id)
    db.add(activation)
    db.flush()
    result = activation_json(activation)
    db.add(RecipeCommandReceipt(id=uuid.uuid4().hex, organization_id=user.organization_id, actor_id=user.id,
        key=idempotency_key, payload_hash=payload_hash, activation_id=activation.id, response=deepcopy(result)))
    db.add(Audit(id=uuid.uuid4().hex, organization_id=user.organization_id, branch_id=branch_id,
        actor_id=user.id, action='recipe.activated', entity_id=activation.id,
        details={'meal_id': meal_id, 'recipe_version': recipe_version, 'effective_date': effective_date,
                 'version': activation.sequence, 'snapshot_sha256': activation.snapshot_sha256,
                 'reason': values['reason']}))
    db.flush()
    return result


def list_activations(db, user, branch_id, meal_id=None, *, limit=100, offset=0):
    user, context = _scope(db, user, branch_id)
    if meal_id is not None:
        identifier(meal_id)
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        reject('STOCK_PAGE_INVALID', 'Use a page size of 1–200 and a nonnegative offset.')
    where = [RecipeActivation.organization_id == user.organization_id, RecipeActivation.branch_id == branch_id]
    if meal_id is not None:
        where.append(RecipeActivation.meal_id == meal_id)
    total = db.scalar(select(func.count()).select_from(RecipeActivation).where(*where))
    items = db.scalars(select(RecipeActivation).where(*where).order_by(
        RecipeActivation.effective_date.desc(), RecipeActivation.meal_id, RecipeActivation.sequence.desc())
        .limit(limit).offset(offset))
    return {'items': [activation_json(item) for item in items], 'total': total,
            'limit': limit, 'offset': offset, 'data_context': _public_context(context)}


def resolve_recipes(db, organization_id, branch_id, effective_date, meal_ids):
    """Internal scoped resolver; the caller must authorize the actor/branch.

    Current catalog describes receiving capacity and price; per-row frozen yield
    describes the activated recipe. Never collapse different meal yields into a
    single ingredient yield. Missing dated activations fail, without CSV fallback.
    """
    identifier(branch_id); day(effective_date)
    if not isinstance(meal_ids, (list, tuple, set)) or not meal_ids or len(meal_ids) > 1000:
        reject('STOCK_RECIPE_REQUIRED', 'An explicit nonempty set of meals is required.')
    meals = sorted({identifier(meal) for meal in meal_ids})
    context = policy_context(db, organization_id)
    ensure_rows(context, [{'branch_id': branch_id, 'data_origin': context['data_origin']}])
    catalog = {row['ingredient_id']: row for row in rows_for(db, organization_id, 'ingredients')}
    activations, recipes, ingredients, versions = [], [], {}, {}
    for meal_id in meals:
        active = db.scalar(select(RecipeActivation).where(RecipeActivation.organization_id == organization_id,
            RecipeActivation.branch_id == branch_id, RecipeActivation.meal_id == meal_id,
            RecipeActivation.effective_date <= effective_date).order_by(RecipeActivation.effective_date.desc()).limit(1))
        if active is None:
            reject('STOCK_RECIPE_NOT_ACTIVE', 'A complete recipe must be explicitly activated for every meal and date.', 409)
        if active.data_context != context or active.snapshot_sha256 != fingerprint(active.rows):
            reject('STOCK_RECIPE_CONTEXT_CHANGED', 'The activated recipe evidence no longer matches its source.', 409)
        for row in active.rows:
            ingredient = row['ingredient_id']
            current = catalog.get(ingredient)
            if current is None or current.get('unit') != row['unit']:
                reject('STOCK_UNIT_MISMATCH', 'The active recipe requires the original ingredient unit.', 409)
            ensure_rows(context, [current])
            captured_yield = quantity(row['captured_yield_factor'], positive=True, allow_zero=False)
            if captured_yield > 1:
                reject('STOCK_YIELD_INVALID', 'Captured yield must be greater than zero and at most one.', 409)
            recipes.append(dict(meal_id=meal_id, ingredient_id=ingredient,
                net_qty_per_portion=row['net_qty_per_portion'], recipe_version=active.recipe_version,
                data_origin=context['data_origin'], unit=row['unit'], captured_yield_factor=row['captured_yield_factor'],
                activation_id=active.id))
            ingredients[ingredient] = deepcopy(current)
        versions[meal_id] = active.recipe_version
        activations.append(dict(id=active.id, meal_id=meal_id, sequence=active.sequence,
            recipe_version=active.recipe_version, effective_date=active.effective_date,
            rows=deepcopy(active.rows), snapshot_sha256=active.snapshot_sha256))
    evidence = dict(version='dated-recipes-v1', organization_id=organization_id, branch_id=branch_id,
                    effective_date=effective_date, activations=activations, data_context=deepcopy(context))
    return dict(recipes=recipes, ingredients=ingredients, versions=versions,
                evidence=evidence, fingerprint=fingerprint(evidence))
