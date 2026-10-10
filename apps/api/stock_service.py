"""Scoped stock journal commands in the caller's transaction.

Public entry points take ``db, user`` plus keyword arguments. The caller commits
success and rolls back every failure; this module never commits. Every command
and preview revalidates Organization -> User locks independently of HTTP auth.
Reads revalidate identity/scope without claiming an active HTTP session.

Opening and movement commands require their preview's ``expected_fingerprint``
and an org/actor-scoped ``idempotency_key``. Previews write no business records.
Post responses are stored verbatim for exact replay. Dates are business dates:
opening(E) excludes operations on E; latest is a separate after-operation state.
No snapshot, approved purchase or CSV import automatically posts a movement.
"""
from copy import deepcopy
from datetime import date, timedelta
import re
import uuid

from sqlalchemy import func, or_, select, update

from .accounts import lock_user
from .data_policy import (DEMO_TARGET, business_clock, ensure_rows, policy_context)
from .db import Audit, StockCommandReceipt, StockLedger, StockMovement, User
from .importing import rows_for
from .lineage import capture_lineage, input_freshness
from .stock import (StockError, apply_document, check_recipe_allocation, day,
                    fingerprint, identifier, opening_state, recipe_requirements,
                    reconciliation, reject, replay, reverse_entries)
from .tenants import organization_active


READ_ROLES = {'admin', 'manager', 'warehouse', 'analyst'}
WRITE_ROLES = {'admin', 'manager', 'warehouse'}


def public_context(context):
    """Source attestation references stay private; origin/purpose stay explicit."""
    result = deepcopy(context)
    if result.get('source'):
        result['source'].pop('authorization_reference', None)
    return result


def _public_evidence(value):
    if isinstance(value, dict):
        return {key: (public_context(item) if key == 'data_context' else _public_evidence(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [_public_evidence(item) for item in value]
    return deepcopy(value)


def _actor(db, user, branch_id, *, write=False, kind=None):
    identifier(branch_id)
    original_org, actor_id = user.organization_id, user.id
    actor = (lock_user(db, actor_id, original_org) if write
             else db.get(User, actor_id, populate_existing=True))
    if (actor is None or actor.organization_id != original_org or not actor.active
            or not organization_active(db, original_org)):
        reject('AUTH_REQUIRED', 'The account or organization is unavailable.', 401)
    allowed = {'admin', 'manager'} if kind in {'adjustment', 'reversal'} else WRITE_ROLES if write else READ_ROLES
    if actor.role not in allowed:
        reject('ROLE_FORBIDDEN', 'This role cannot perform the stock operation.', 403)
    if branch_id not in actor.branch_ids:
        reject('BRANCH_FORBIDDEN', 'The branch is outside current access.', 403)
    context = policy_context(db, original_org)
    branches = [row for row in rows_for(db, original_org, 'branches') if row['branch_id'] == branch_id]
    if not branches:
        reject('BRANCH_NOT_FOUND', 'The branch is unavailable.', 404)
    ensure_rows(context, branches)
    return actor, context


def _reason(value):
    if not isinstance(value, str) or not 3 <= len(value.strip()) <= 1000:
        reject('STOCK_REASON_REQUIRED', 'Supply a reason of 3–1000 characters.')
    return value.strip()


def _reference(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.strip()
            or any(ord(char) < 32 for char in value)):
        reject('STOCK_SOURCE_REFERENCE_REQUIRED', 'Supply a nonempty source document reference of up to 128 characters.')
    return value.strip()


def _expected_fingerprint(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        reject('STOCK_PREVIEW_REQUIRED', 'Review the stock preview before posting.', 409)
    return value


def _key(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) is None:
        reject('IDEMPOTENCY_KEY_REQUIRED', 'Supply a stable stock command idempotency key.')
    return value


def _business_date(context, value, *, baseline=False):
    day(value)
    if value == date.max.isoformat():
        reject('STOCK_DATE_INVALID', 'The following opening-stock date must be representable.')
    if context['data_origin'] == 'REAL' and value > business_clock(context)[1].isoformat():
        reject('STOCK_FUTURE_DATE', 'A counted snapshot or completed operation cannot be in the future.')
    if baseline and context['data_origin'] == 'SYNTHETIC' and value != DEMO_TARGET:
        reject('DEMO_DATE_FIXED', 'The synthetic starting snapshot remains 2026-01-01.')
    return value


def _ingredients(db, organization_id, context):
    rows = rows_for(db, organization_id, 'ingredients')
    ensure_rows(context, rows)
    return {row['ingredient_id']: row for row in rows}


def _ledger(db, organization_id, branch_id, *, required=True):
    row = db.scalar(select(StockLedger).where(StockLedger.organization_id == organization_id,
                                             StockLedger.branch_id == branch_id).execution_options(populate_existing=True))
    if row is None and required:
        reject('STOCK_LEDGER_REQUIRED', 'Open a journal from an explicit counted snapshot first.', 409)
    return row


def _ledger_view(ledger):
    return {name: getattr(ledger, name) for name in
            ('id', 'branch_id', 'baseline_date', 'version', 'created_by', 'created_at')}


def _freshness(db, ledger, context):
    return dict(baseline_freshness=input_freshness(db, ledger.organization_id, ledger.baseline_lineage),
                context_freshness='unchanged' if ledger.data_context == context else 'changed')


def _require_fresh(db, ledger, context):
    freshness = _freshness(db, ledger, context)
    if freshness['context_freshness'] != 'unchanged':
        reject('STOCK_CONTEXT_CHANGED', 'The journal source policy changed; explicit reconciliation is required.', 409)
    if freshness['baseline_freshness'] != 'unchanged':
        reject('STOCK_BASELINE_CHANGED', 'The counted baseline changed; its frozen opening stock cannot be replaced silently.', 409)
    return freshness


def _movement_view(row):
    return {name: deepcopy(getattr(row, name)) for name in
            ('id', 'ledger_id', 'sequence', 'kind', 'business_date', 'reason', 'source_reference',
             'entries', 'recipe_evidence', 'reverses_id', 'actor_id', 'recorded_at')}


def _history(db, ledger):
    rows = list(db.scalars(select(StockMovement).where(StockMovement.ledger_id == ledger.id)
                          .order_by(StockMovement.sequence)))
    if any(row.organization_id != ledger.organization_id or row.branch_id != ledger.branch_id for row in rows):
        reject('STOCK_HISTORY_INVALID', 'Stored journal scope is inconsistent.', 409)
    if ledger.version != len(rows) + 1:
        reject('STOCK_HISTORY_INVALID', 'Journal version and movement history disagree.', 409)
    return [_movement_view(row) for row in rows]


def _frozen_catalog(ledger, history):
    # Historical reading uses the units actually captured in its stock evidence.
    # A later catalog edit must not rewrite or prevent reading that history.
    result = {}
    for row in [*ledger.baseline_rows, *(entry for movement in history for entry in movement['entries'])]:
        ingredient, unit = row['ingredient_id'], row['unit']
        if ingredient in result and result[ingredient]['unit'] != unit:
            reject('STOCK_HISTORY_INVALID', 'A journal ingredient has conflicting units.', 409)
        result[ingredient] = {'unit': unit}
    return result


def _position(ledger, history, opening_date):
    catalog = _frozen_catalog(ledger, history)
    baseline = opening_state(ledger.baseline_rows, branch_id=ledger.branch_id,
        snapshot_date=ledger.baseline_date, data_origin=ledger.data_context['data_origin'], ingredients=catalog)
    state, selected = replay(baseline, history, baseline_date=ledger.baseline_date,
                             target_date=opening_date, ingredients=catalog)
    return state, selected


def _rows(state):
    return [deepcopy(state[key]) for key in sorted(state)]


def _latest(ledger, history):
    last_day = history[-1]['business_date'] if history else ledger.baseline_date
    through = (date.fromisoformat(last_day) + timedelta(days=1)).isoformat()
    return _position(ledger, history, through)[0], history[-1]['business_date'] if history else None


def _snapshot(db, organization_id, branch_id, snapshot_date, context, ingredients):
    rows = [row for row in rows_for(db, organization_id, 'inventory_lots', branch_id)
            if row['snapshot_date'] == snapshot_date]
    ensure_rows(context, rows)
    state = opening_state(rows, branch_id=branch_id, snapshot_date=snapshot_date,
                          data_origin=context['data_origin'], ingredients=ingredients)
    lineage = capture_lineage(db, organization_id, [dict(kind='inventory_lots', rows=rows,
                              branch_id=branch_id, snapshot_date=snapshot_date)])
    return rows, state, lineage


def _receipt(db, actor, key, payload_hash, branch_id):
    existing = db.scalar(select(StockCommandReceipt).where(
        StockCommandReceipt.organization_id == actor.organization_id,
        StockCommandReceipt.actor_id == actor.id, StockCommandReceipt.key == key))
    if existing:
        if existing.payload_hash != payload_hash:
            reject('IDEMPOTENCY_CONFLICT', 'This command key already belongs to different input.', 409)
        ledger = _ledger(db, actor.organization_id, branch_id)
        if existing.ledger_id != ledger.id:
            reject('IDEMPOTENCY_CONFLICT', 'This command key belongs to another stock journal.', 409)
        return deepcopy(existing.response)
    return None


def _save(db, actor, ledger, key, payload_hash, response, *, action, entity_id, details):
    db.add(StockCommandReceipt(id=uuid.uuid4().hex, organization_id=actor.organization_id,
        actor_id=actor.id, key=key, payload_hash=payload_hash, ledger_id=ledger.id, response=deepcopy(response)))
    db.add(Audit(id=uuid.uuid4().hex, organization_id=actor.organization_id, branch_id=ledger.branch_id,
        actor_id=actor.id, action=action, entity_id=entity_id, details=deepcopy(details)))
    db.flush()
    return response


def preview_open(db, user, *, branch_id, baseline_date, reason):
    """Return exact counted rows and a fingerprint bound to source, actor and reason."""
    actor, context = _actor(db, user, branch_id, write=True)
    reason = _reason(reason); _business_date(context, baseline_date, baseline=True)
    if _ledger(db, actor.organization_id, branch_id, required=False):
        reject('STOCK_LEDGER_EXISTS', 'A journal already exists for this branch.', 409)
    rows, _, lineage = _snapshot(db, actor.organization_id, branch_id, baseline_date, context,
                                 _ingredients(db, actor.organization_id, context))
    evidence = dict(operation='open', organization_id=actor.organization_id, actor_id=actor.id,
        branch_id=branch_id, baseline_date=baseline_date, reason=reason,
        baseline_rows=sorted(rows, key=lambda row: (row['ingredient_id'], row['lot_id'])),
        baseline_lineage=lineage, data_context=context)
    return dict(operation='open', preview_fingerprint=fingerprint(evidence), branch_id=branch_id,
        baseline_date=baseline_date, baseline_rows=deepcopy(evidence['baseline_rows']),
        baseline_lineage=deepcopy(lineage), reason=reason, public_context=public_context(context))


def open_ledger(db, user, *, branch_id, baseline_date, reason, expected_fingerprint, idempotency_key):
    """Open once; retrying the same key returns the immutable original response."""
    actor, context = _actor(db, user, branch_id, write=True)
    key = _key(idempotency_key); expected = _expected_fingerprint(expected_fingerprint)
    reason = _reason(reason)
    payload_hash = fingerprint(dict(operation='open', branch_id=branch_id, baseline_date=baseline_date,
                                    reason=reason, expected_fingerprint=expected))
    prior = _receipt(db, actor, key, payload_hash, branch_id)
    if prior is not None:
        return prior
    preview = preview_open(db, actor, branch_id=branch_id, baseline_date=baseline_date, reason=reason)
    if preview['preview_fingerprint'] != expected:
        reject('STOCK_PREVIEW_STALE', 'The source snapshot changed; review a new preview.', 409)
    ledger = StockLedger(id=uuid.uuid4().hex, organization_id=actor.organization_id,
        branch_id=branch_id, baseline_date=baseline_date, baseline_rows=deepcopy(preview['baseline_rows']),
        baseline_lineage=deepcopy(preview['baseline_lineage']), data_context=deepcopy(context),
        version=1, created_by=actor.id)
    db.add(ledger); db.flush()
    response = dict(ledger_id=ledger.id, branch_id=branch_id, version=1, baseline_date=baseline_date,
                    status='opened', public_context=public_context(context))
    return _save(db, actor, ledger, key, payload_hash, response, action='stock.opened', entity_id=ledger.id,
                 details={'reason': reason, 'baseline_date': baseline_date, 'preview_fingerprint': expected})


def recipe_requirements_view(db, user, *, branch_id, business_date, portions):
    """Resolve dated recipe versions; this helper never posts or assumes lot allocation."""
    from .stock_recipes import resolve_recipes
    actor, context = _actor(db, user, branch_id)
    _business_date(context, business_date)
    if not isinstance(portions, dict) or not portions:
        reject('STOCK_RECIPE_REQUIRED', 'Supply explicit meal portions.')
    resolved = resolve_recipes(db, actor.organization_id, branch_id, business_date, list(portions))
    requirements, arithmetic = recipe_requirements(resolved['recipes'], resolved['ingredients'],
                                                   portions, resolved['versions'])
    return dict(branch_id=branch_id, business_date=business_date, portions=deepcopy(portions),
        requirements=requirements, versions=resolved['versions'], recipe_evidence={
            **arithmetic, 'dated_recipes': _public_evidence(resolved['evidence']), 'dated_fingerprint': resolved['fingerprint']},
        public_context=public_context(context))


def preview_movement(db, user, *, branch_id, expected_version, kind, business_date,
                     source_reference, reason, lines=None, reverses_id=None, recipe_usage=None):
    """Return signed entries and before/after balances, without persisting them."""
    actor, context = _actor(db, user, branch_id, write=True, kind=kind)
    reason = _reason(reason); source_reference = _reference(source_reference)
    _business_date(context, business_date)
    ledger = _ledger(db, actor.organization_id, branch_id)
    if type(expected_version) is not int or expected_version < 1 or ledger.version != expected_version:
        reject('STOCK_VERSION_CONFLICT', 'Stock changed; reload and review a new movement preview.', 409)
    _require_fresh(db, ledger, context)
    history = _history(db, ledger)
    latest, last_day = _latest(ledger, history)
    if business_date < (last_day or ledger.baseline_date):
        reject('STOCK_BACKDATED', 'Post a later correcting operation instead of changing prior stock history.', 409)
    if any(row['source_reference'] == source_reference for row in history):
        reject('STOCK_SOURCE_DUPLICATE', 'This business document already appears in the journal.', 409)
    ingredients = _ingredients(db, actor.organization_id, context)
    recipe_evidence = None
    if kind == 'reversal':
        if lines is not None or recipe_usage is not None:
            reject('STOCK_REVERSAL_INPUT', 'Reversal quantities are derived only from the original movement.')
        identifier(reverses_id)
        original = next((row for row in history if row['id'] == reverses_id), None)
        if original is None:
            reject('STOCK_MOVEMENT_NOT_FOUND', 'The original scoped movement does not exist.', 404)
        if original['kind'] == 'reversal' or any(row['reverses_id'] == reverses_id for row in history):
            reject('STOCK_REVERSAL_INVALID', 'A reversal cannot be reversed or applied twice.', 409)
        effective_lines = reverse_entries(original['entries'])
    else:
        if reverses_id is not None:
            reject('STOCK_REVERSAL_INPUT', 'Only a reversal may reference a previous movement.')
        effective_lines = lines
    if kind == 'recipe_usage':
        if not isinstance(recipe_usage, dict) or set(recipe_usage) != {'portions'}:
            reject('STOCK_RECIPE_REQUIRED', 'Recipe usage requires portions; versions come from dated activation.')
        recipe = recipe_requirements_view(db, actor, branch_id=branch_id, business_date=business_date,
                                         portions=recipe_usage['portions'])
        recipe_evidence = recipe['recipe_evidence']
    elif recipe_usage is not None:
        reject('STOCK_RECIPE_INPUT', 'Recipe portions belong only to recipe usage.')
    after, entries = apply_document(latest, effective_lines, kind=kind, business_date=business_date,
                                    ingredients=ingredients, reversal=kind == 'reversal')
    if kind == 'recipe_usage':
        check_recipe_allocation(entries, recipe['requirements'])
    evidence = dict(operation='movement', organization_id=actor.organization_id, actor_id=actor.id,
        ledger_id=ledger.id, branch_id=branch_id, version=ledger.version, kind=kind,
        business_date=business_date, source_reference=source_reference, reason=reason,
        reverses_id=reverses_id, entries=entries, recipe_evidence=recipe_evidence,
        baseline_lineage=ledger.baseline_lineage, data_context=context,
        balances_before=_rows(latest), balances_after=_rows(after))
    return {name: deepcopy(evidence[name]) for name in ('operation', 'ledger_id', 'branch_id', 'version',
            'kind', 'business_date', 'source_reference', 'reason', 'reverses_id', 'entries',
            'recipe_evidence', 'balances_before', 'balances_after')} | {
                'preview_fingerprint': fingerprint(evidence), 'public_context': public_context(context)}


def post_movement(db, user, *, branch_id, expected_version, kind, business_date,
                  source_reference, reason, expected_fingerprint, idempotency_key,
                  lines=None, reverses_id=None, recipe_usage=None):
    actor, context = _actor(db, user, branch_id, write=True, kind=kind)
    key = _key(idempotency_key); expected = _expected_fingerprint(expected_fingerprint)
    reason = _reason(reason); source_reference = _reference(source_reference)
    options = dict(branch_id=branch_id, expected_version=expected_version, kind=kind,
        business_date=business_date, source_reference=source_reference, reason=reason,
        lines=lines, reverses_id=reverses_id, recipe_usage=recipe_usage)
    payload_hash = fingerprint(dict(operation='movement', **options, expected_fingerprint=expected))
    prior = _receipt(db, actor, key, payload_hash, branch_id)
    if prior is not None:
        return prior
    preview = preview_movement(db, actor, **options)
    if preview['preview_fingerprint'] != expected:
        reject('STOCK_PREVIEW_STALE', 'Movement inputs changed; review the current calculation.', 409)
    ledger = _ledger(db, actor.organization_id, branch_id)
    updated = db.execute(update(StockLedger).where(StockLedger.id == ledger.id,
        StockLedger.organization_id == actor.organization_id, StockLedger.branch_id == branch_id,
        StockLedger.version == expected_version).values(version=expected_version + 1)).rowcount
    if updated != 1:
        reject('STOCK_VERSION_CONFLICT', 'Another movement was posted; review a new preview.', 409)
    movement = StockMovement(id=uuid.uuid4().hex, ledger_id=ledger.id, organization_id=actor.organization_id,
        branch_id=branch_id, sequence=expected_version, kind=kind, business_date=business_date,
        reason=reason, source_reference=source_reference, entries=deepcopy(preview['entries']),
        recipe_evidence=deepcopy(preview['recipe_evidence']), reverses_id=reverses_id, actor_id=actor.id)
    db.add(movement); db.flush()
    response = dict(ledger_id=ledger.id, movement_id=movement.id, branch_id=branch_id,
        version=expected_version + 1, sequence=expected_version, status='posted',
        entries=deepcopy(movement.entries), public_context=public_context(context))
    return _save(db, actor, ledger, key, payload_hash, response, action='stock.movement_posted',
        entity_id=movement.id, details=dict(ledger_id=ledger.id, sequence=expected_version, kind=kind,
            business_date=business_date, reason=reason, source_reference=source_reference,
            reverses_id=reverses_id, preview_fingerprint=expected))


def get_position(db, user, *, branch_id, opening_date):
    day(opening_date)
    actor, context = _actor(db, user, branch_id)
    ledger = _ledger(db, actor.organization_id, branch_id, required=False)
    if ledger is None:
        return dict(ledger=None, version=None, baseline_freshness='unknown', context_freshness='unknown',
            opening={'date': opening_date, 'rows': None}, latest={'through_business_date': None, 'rows': None},
            public_context=public_context(context))
    history = _history(db, ledger)
    opening, _ = _position(ledger, history, opening_date)
    latest, through = _latest(ledger, history)
    return dict(ledger=_ledger_view(ledger), version=ledger.version, **_freshness(db, ledger, context),
        opening={'date': opening_date, 'rows': _rows(opening)},
        latest={'through_business_date': through, 'rows': _rows(latest)},
        public_context=public_context(ledger.data_context))


def list_movements(db, user, *, branch_id, limit=50, cursor=0):
    if type(limit) is not int or not 1 <= limit <= 200 or type(cursor) is not int or cursor < 0:
        reject('STOCK_PAGE_INVALID', 'Use a nonnegative cursor and a limit of 1–200.')
    actor, context = _actor(db, user, branch_id)
    ledger = _ledger(db, actor.organization_id, branch_id, required=False)
    total, history = 0, []
    if ledger:
        scope = (StockMovement.ledger_id == ledger.id,
                 StockMovement.organization_id == actor.organization_id, StockMovement.branch_id == branch_id)
        invalid = db.scalar(select(StockMovement.id).where(StockMovement.ledger_id == ledger.id,
            or_(StockMovement.organization_id != actor.organization_id, StockMovement.branch_id != branch_id)).limit(1))
        total = db.scalar(select(func.count()).select_from(StockMovement).where(*scope))
        if invalid or ledger.version != total + 1:
            reject('STOCK_HISTORY_INVALID', 'Stored journal scope or version is inconsistent.', 409)
        history = [_movement_view(row) for row in db.scalars(select(StockMovement).where(*scope)
            .order_by(StockMovement.sequence.desc()).offset(cursor).limit(limit))]
        reversal_links = dict(db.execute(select(StockMovement.reverses_id, StockMovement.id).where(
            *scope, StockMovement.reverses_id.in_([row['id'] for row in history]))).all()) if history else {}
        for row in history:
            row['reversed_by_id'] = reversal_links.get(row['id'])
    return dict(ledger_id=ledger.id if ledger else None, items=history, total=total,
        next_cursor=str(cursor + limit) if cursor + limit < total else None,
        public_context=public_context(ledger.data_context if ledger else context))


def reconcile(db, user, *, branch_id, count_date):
    """Compare independent counted stock with opening(count_date), never adjust either."""
    actor, context = _actor(db, user, branch_id)
    day(count_date)
    ledger = _ledger(db, actor.organization_id, branch_id)
    history = _history(db, ledger)
    calculated, selected = _position(ledger, history, count_date)
    counted_rows = sorted((row for row in rows_for(db, actor.organization_id, 'inventory_lots', branch_id)
                           if row['snapshot_date'] == count_date),
                          key=lambda row: (row['ingredient_id'], row['lot_id']))
    ensure_rows(context, counted_rows)
    counted = opening_state(counted_rows, branch_id=branch_id, snapshot_date=count_date,
        data_origin=context['data_origin'], ingredients=_ingredients(db, actor.organization_id, context)) if counted_rows else {}
    count_lineage = capture_lineage(db, actor.organization_id, [dict(kind='inventory_lots', rows=counted_rows,
                                      branch_id=branch_id, snapshot_date=count_date)])
    freshness = _freshness(db, ledger, context)
    result = reconciliation(calculated, counted, baseline_date=ledger.baseline_date, target_date=count_date)
    if any(value != 'unchanged' for value in freshness.values()):
        result['status'] = 'unresolved'
    evidence = dict(ledger_id=ledger.id, baseline_date=ledger.baseline_date, baseline_rows=ledger.baseline_rows,
        baseline_lineage=ledger.baseline_lineage, data_context=ledger.data_context, target_date=count_date,
        movements=selected, counted_lineage=count_lineage, counted_rows=counted_rows, **freshness)
    return dict(result, ledger_id=ledger.id, schema_version=result['version'], version=ledger.version, **freshness,
        stock_fingerprint=fingerprint(evidence), stock_evidence=_public_evidence(evidence),
        public_context=public_context(ledger.data_context))
