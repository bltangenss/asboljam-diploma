"""Stock journal arithmetic, separate from CSV import and purchasing decisions.

Counted snapshots describe opening stock. Operations on D change opening(D+1),
not opening(D). Quantities are gross kg/L decimal strings. A missing lot is
unknown; only an explicit receipt introduces a new lot with known zero before it.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import hashlib
import json
import re


MAX_QUANTITY = Decimal('1000000000000')
SCALE = 10**9
MAX_LINES = 500
KINDS = {'receipt', 'waste', 'adjustment', 'recipe_usage', 'reversal'}


class StockError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def reject(code, message, status=422):
    raise StockError(code, message, status)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        reject('STOCK_IDENTIFIER_INVALID', 'Use an unchanged source identifier of1–64 ASCII characters.')
    return value


def day(value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        reject('STOCK_DATE_INVALID', 'Use a complete YYYY-MM-DD business date.')
    return value


def quantity(value, *, positive=False, allow_zero=True):
    # No float input: conversion could silently change a physical quantity.
    if not isinstance(value, str) or len(value) > 128:
        reject('STOCK_QUANTITY_INVALID', 'Quantity must be a bounded decimal string.')
    try:
        number = Decimal(value)
    except InvalidOperation:
        reject('STOCK_QUANTITY_INVALID', 'Quantity must be a finite decimal string.')
    if not number.is_finite() or number.copy_abs() > MAX_QUANTITY:
        reject('STOCK_QUANTITY_INVALID', 'Quantity must be finite and within the supported range.')
    if number:
        _, digits, exponent = number.as_tuple()
        for digit in reversed(digits):
            if digit != 0:
                break
            exponent += 1
        if exponent < -9:
            reject('STOCK_PRECISION_UNSUPPORTED', 'Stock supports up to nine fractional decimal places.')
    if positive and number < 0 or not allow_zero and number == 0:
        reject('STOCK_QUANTITY_INVALID', 'Quantity has an invalid sign or is zero.')
    return number


def decimal_text(number):
    if number == 0:
        return '0'
    text = format(number, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def lot_key(row):
    return identifier(row.get('ingredient_id')), identifier(row.get('lot_id'))


def lot_metadata(row, ingredients):
    ingredient, lot = lot_key(row)
    unit = row.get('unit')
    if ingredient not in ingredients:
        reject('STOCK_INGREDIENT_UNKNOWN', 'An ingredient is absent from the scoped catalog.')
    if unit not in {'kg', 'L'} or unit != ingredients[ingredient].get('unit'):
        reject('STOCK_UNIT_MISMATCH', 'Stock and ingredient units must agree without conversion.')
    return dict(ingredient_id=ingredient, lot_id=lot, unit=unit, expiry_date=day(row.get('expiry_date')))


def opening_state(rows, *, branch_id, snapshot_date, data_origin, ingredients):
    day(snapshot_date);identifier(branch_id)
    if data_origin not in {'SYNTHETIC', 'REAL'} or not rows:
        reject('STOCK_BASELINE_REQUIRED', 'An explicit nonempty counted snapshot is required.')
    result = {}
    for row in rows:
        if (row.get('branch_id') != branch_id or row.get('snapshot_date') != snapshot_date
                or row.get('data_origin') != data_origin):
            reject('STOCK_BASELINE_SCOPE', 'All baseline rows must share branch, date and origin.')
        meta = lot_metadata(row, ingredients);key = lot_key(meta)
        if key in result:
            reject('STOCK_DUPLICATE_LOT', 'A lot appears twice in the counted snapshot.')
        result[key] = {**meta, 'on_hand_qty':decimal_text(quantity(row.get('on_hand_qty'), positive=True))}
    return result


def apply_document(state, lines, *, kind, business_date, ingredients, reversal=False):
    """Return a new state and immutable signed entries; never mutate inputs on error.

    reversal=True is internal: lines must come from reverse_entries on a stored
    document. API callers must not be permitted to supply arbitrary reversals.
    """
    day(business_date)
    if kind not in KINDS or (kind == 'reversal') != reversal:
        reject('STOCK_KIND_INVALID', 'Select an explicit supported movement kind.')
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        reject('STOCK_LINES_INVALID', 'A movement must contain1–500 explicit lot lines.')
    proposed, entries, seen = deepcopy(state), [], set()
    for line in lines:
        meta = lot_metadata(line, ingredients);key = lot_key(meta)
        if key in seen:
            reject('STOCK_DUPLICATE_LOT', 'A lot may occur once per movement document.')
        seen.add(key)
        value = quantity(line.get('quantity_delta' if reversal else 'quantity'),
                         positive=kind in {'receipt', 'waste', 'recipe_usage'}, allow_zero=False)
        delta = -value if kind in {'waste', 'recipe_usage'} else value
        previous = proposed.get(key)
        if previous is None:
            if kind != 'receipt':
                reject('STOCK_BALANCE_UNKNOWN', 'Only a receipt can introduce a previously unknown lot.')
            previous = {**meta, 'on_hand_qty':'0'}
        if any(previous[field] != meta[field] for field in ('unit', 'expiry_date')):
            reject('STOCK_LOT_METADATA_CHANGED', 'A lot cannot silently change expiry or unit.')
        if kind in {'receipt', 'recipe_usage'} and meta['expiry_date'] < business_date:
            reject('STOCK_LOT_EXPIRED', 'An expired lot cannot be received or consumed in a recipe.')
        with localcontext() as context:
            context.prec = 50
            balance = quantity(previous['on_hand_qty'], positive=True) + delta
        if balance < 0:
            reject('STOCK_INSUFFICIENT', 'Movement would create negative stock.')
        if balance > MAX_QUANTITY:
            reject('STOCK_QUANTITY_INVALID', 'Resulting lot stock exceeds the supported range.')
        proposed[key] = {**meta, 'on_hand_qty':decimal_text(balance)}
        entries.append({**meta, 'quantity_delta':decimal_text(delta)})
    return proposed, entries


def reverse_entries(stored_entries):
    return [{**entry, 'quantity_delta':decimal_text(-quantity(entry['quantity_delta']))}
            for entry in stored_entries]


def replay(baseline, movements, *, baseline_date, target_date, ingredients):
    """Build an opening stock position using D <= movement date < target date.

    Movement posting is chronological. A correction is a later linked operation,
    not an edit of an earlier entry. Sequence and date corruption fail closed.
    """
    day(baseline_date);day(target_date)
    if target_date < baseline_date:
        reject('STOCK_DATE_BEFORE_BASELINE', 'There is no journal position before its baseline.')
    state, selected, previous_day, sequence = deepcopy(baseline), [], baseline_date, 0
    for movement in movements:
        effective = day(movement['business_date'])
        if movement['sequence'] != sequence + 1 or effective < previous_day:
            reject('STOCK_HISTORY_INVALID', 'Journal sequence or effective-date order is invalid.', 409)
        previous_day, sequence = effective, movement['sequence']
        if effective >= target_date:
            continue
        # Revalidate stored signed entries, including receipts that introduce lots.
        kind = movement['kind']
        lines = [{**entry, 'quantity':decimal_text(-quantity(entry['quantity_delta'])
                  if kind in {'waste','recipe_usage'} else quantity(entry['quantity_delta']))}
                 for entry in movement['entries']]
        state, normalized = apply_document(state, lines, kind=kind,
                                          business_date=effective, ingredients=ingredients, reversal=kind=='reversal')
        if normalized != movement['entries']:
            reject('STOCK_HISTORY_INVALID', 'Stored movement entries are inconsistent.', 409)
        selected.append(deepcopy(movement))
    return state, selected


def recipe_requirements(recipes, ingredients, portions, versions):
    """Compute gross requirements once; caller resolves the dated active versions.

    Fraction arithmetic avoids intermediate rounding. Aggregate by ingredient,
    then round upward to one billionth kg/L once, with the rule in evidence.
    This does not itself implement dated recipe activation.
    """
    if not isinstance(portions, dict) or not portions or set(portions) != set(versions):
        reject('STOCK_RECIPE_REQUIRED', 'Explicit meal portions and selected versions are required.')
    totals, evidence = {}, []
    for meal, count in portions.items():
        identifier(meal)
        if not isinstance(versions[meal], str) or not 1 <= len(versions[meal].strip()) <= 255:
            reject('STOCK_RECIPE_REQUIRED', 'Preserve the nonempty canonical recipe version label.')
        if type(count) is not int or not 1 <= count <= 1000000000:
            reject('STOCK_PORTIONS_INVALID', 'Consumed portions must be positive bounded integers.')
        selected = [row for row in recipes if row.get('meal_id') == meal and row.get('recipe_version') == versions[meal]]
        if not selected:
            reject('STOCK_RECIPE_REQUIRED', 'The selected complete recipe version is missing.')
        seen = set()
        for row in selected:
            ingredient = identifier(row['ingredient_id'])
            if ingredient in seen or ingredient not in ingredients:
                reject('STOCK_RECIPE_AMBIGUOUS', 'Recipe ingredient is duplicate or missing from the catalog.')
            seen.add(ingredient)
            catalog = ingredients[ingredient]
            if catalog.get('unit') not in {'kg', 'L'}:
                reject('STOCK_UNIT_MISMATCH', 'Recipe stock unit is unsupported.')
            net = quantity(row.get('net_qty_per_portion'), positive=True, allow_zero=False)
            yield_factor = quantity(catalog.get('yield_factor'), positive=True, allow_zero=False)
            if yield_factor > 1:
                reject('STOCK_YIELD_INVALID', 'Yield must be greater than zero and at most one.')
            gross = Fraction(net) * count / Fraction(yield_factor)
            totals[ingredient] = totals.get(ingredient, Fraction(0)) + gross
            evidence.append(dict(meal_id=meal, recipe_version=versions[meal], ingredient_id=ingredient,
                                 portions=count, net_qty_per_portion=str(net), yield_factor=str(yield_factor), unit=catalog['unit']))
    requirements = []
    for ingredient, total in sorted(totals.items()):
        ticks = (total.numerator*SCALE + total.denominator-1)//total.denominator
        with localcontext() as context:
            context.prec = 50
            gross = quantity(decimal_text(Decimal(ticks)/SCALE), positive=True)
        requirements.append(dict(ingredient_id=ingredient, unit=ingredients[ingredient]['unit'],
                                 gross_required=decimal_text(gross)))
    return requirements, {'version':'recipe-stock-v1','rounding':'ceil_9_decimal_places_after_ingredient_aggregation',
                          'rows':evidence}


def check_recipe_allocation(entries, requirements):
    actual = {}
    for row in entries:
        delta = quantity(row['quantity_delta'])
        if delta >= 0:
            reject('STOCK_RECIPE_ALLOCATION', 'Recipe allocation must consume gross stock.')
        key = row['ingredient_id'], row['unit']
        actual[key] = actual.get(key, Decimal(0)) - delta
    expected = {(row['ingredient_id'], row['unit']):quantity(row['gross_required']) for row in requirements}
    if actual != expected:
        reject('STOCK_RECIPE_ALLOCATION', 'Allocated gross lot quantities must match recipe requirements exactly.')


def reconciliation(calculated, counted, *, baseline_date, target_date):
    day(baseline_date);day(target_date)
    if target_date < baseline_date:
        reject('STOCK_DATE_BEFORE_BASELINE', 'Count date must not precede the baseline.')
    lines = []
    for key in sorted(calculated.keys() | counted.keys()):
        ledger, count = calculated.get(key), counted.get(key)
        issue = ('missing_count' if count is None else 'missing_ledger_lot' if ledger is None else
                 'lot_metadata_changed' if any(ledger[field] != count[field] for field in ('unit','expiry_date')) else None)
        difference = quantity(count['on_hand_qty']) - quantity(ledger['on_hand_qty']) if not issue else None
        lines.append(dict(ingredient_id=key[0],lot_id=key[1],ledger=deepcopy(ledger),counted=deepcopy(count),
                          difference=decimal_text(difference) if difference is not None else None,
                          status=issue or ('matched' if difference == 0 else 'mismatch')))
    return dict(version='opening-stock-reconciliation-v1', baseline_date=baseline_date,
                target_date=target_date, interval='baseline_date <= operation_date < target_date',
                status='matched' if lines and all(row['status'] == 'matched' for row in lines) else 'unresolved',lines=lines)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()
