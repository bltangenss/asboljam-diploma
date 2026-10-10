"""Canonical row fingerprints and immutable calculation input provenance.

Decimal representation is normalized only for comparison, never in stored rows.
Freshness is derived from current data and revision history; saved computations
remain immutable. Collection selectors also detect newly added relevant rows.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json

from sqlalchemy import and_, func, or_, select

from .db import Record
from .importing import DECIMAL_FIELDS, SCHEMAS, natural_key


VERSION = 'canonical-v1'


def canonical_row(data):
    if not isinstance(data, dict):
        raise ValueError('A canonical operational row must be an object')
    canonical = dict(data)
    for field in DECIMAL_FIELDS & canonical.keys():
        try:
            number = Decimal(str(canonical[field]))
            if not number.is_finite():
                raise ValueError()
            if number == 0:
                value = '0'
            else:
                # Avoid context rounding and huge strings for e.g. 1e-1000000.
                sign, digits, exponent = number.as_tuple()
                digits = list(digits)
                while digits[-1] == 0:
                    digits.pop()
                    exponent += 1
                coefficient = ''.join(str(digit) for digit in digits)
                value = ('-' if sign else '') + coefficient + 'e' + str(exponent)
            canonical[field] = value
        except (InvalidOperation, ValueError):
            raise ValueError('Invalid decimal in canonical operational row') from None
    return canonical


def row_digest(data):
    payload = json.dumps(canonical_row(data), sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _state(db, organization_id, selectors, cache=None):
    # Lazy import permits consumers of row_digest to load without schema coupling.
    from .db import RecordRevision
    filters = [{key: selector[key] for key in ('kind', 'branch_id', 'date_lte', 'snapshot_date')
                if key in selector} for selector in selectors]
    cache_key = (organization_id, json.dumps(filters, sort_keys=True))
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    clauses = []
    for selector in filters:
        clause = [Record.kind == selector['kind']]
        if selector.get('branch_id') is not None:
            clause.append(Record.branch_id == selector['branch_id'])
        if selector.get('date_lte') is not None:
            clause.append(Record.data['date'].as_string() <= selector['date_lte'])
        if selector.get('snapshot_date') is not None:
            clause.append(Record.data['snapshot_date'].as_string() == selector['snapshot_date'])
        clauses.append(and_(*clause))
    if not clauses:
        return {}
    latest = select(func.max(RecordRevision.revision)).where(
        RecordRevision.organization_id == Record.organization_id,
        RecordRevision.kind == Record.kind,
        RecordRevision.natural_key == Record.natural_key).correlate(Record).scalar_subquery()
    # The indexed correlated lookup reads only latest metadata. Historical
    # before/after JSON and unrelated branches/future dates are never loaded.
    rows = db.execute(select(Record, RecordRevision.revision, RecordRevision.batch_id).outerjoin(
        RecordRevision, and_(RecordRevision.organization_id == Record.organization_id,
            RecordRevision.kind == Record.kind, RecordRevision.natural_key == Record.natural_key,
            RecordRevision.revision == latest)).where(
        Record.organization_id == organization_id, or_(*clauses)))
    result = {}
    for row, revision, batch_id in rows:
        result[(row.kind, row.natural_key)] = {
            'row': row,
            'entry': {'kind': row.kind, 'natural_key': row.natural_key,
                      'branch_id': row.branch_id, 'row_sha256': row_digest(row.data),
                      'record_id': row.id,
                      'revision': revision if revision is not None else 0,
                      'batch_id': batch_id},
        }
    if cache is not None:
        cache[cache_key] = result
    return result


def _selected(row, selector):
    if row.kind != selector['kind']:
        return False
    branch = selector.get('branch_id')
    if branch is not None and row.branch_id != branch:
        return False
    if selector.get('date_lte') is not None and row.data.get('date', '') > selector['date_lte']:
        return False
    if selector.get('snapshot_date') is not None and row.data.get('snapshot_date') != selector['snapshot_date']:
        return False
    return True


def capture_lineage(db, organization_id, collections, *, inherited=None, stock_dependencies=None):
    """collections contain kind/rows and the same selection filters as the snapshot.

    inherited is an earlier forecast lineage. A missing legacy forecast lineage
    is represented by callers as an incomplete parent; it cannot become verified
    just because today's procurement inputs have a complete lineage.
    """
    state = _state(db, organization_id, collections)
    result = {'version': VERSION, 'organization_id': organization_id,
              'complete': True, 'records': [], 'selectors': []}
    if inherited is not None:
        if not isinstance(inherited, dict) or inherited.get('organization_id') != organization_id or inherited.get('version') != VERSION:
            result['complete'] = False
        else:
            result['complete'] = inherited.get('complete') is True
            result['records'] = deepcopy(inherited.get('records', []))
            result['selectors'] = deepcopy(inherited.get('selectors', []))
    for collection in collections:
        kind = collection['kind']
        selector = {key: collection[key] for key in ('kind', 'branch_id', 'date_lte', 'snapshot_date') if key in collection}
        keys = []
        for row in collection['rows']:
            key = natural_key(kind, row)
            current = state.get((kind, key))
            if current is None or current['entry']['row_sha256'] != row_digest(row):
                raise ValueError('Calculation input does not match its scoped operational source')
            keys.append(key)
            result['records'].append(deepcopy(current['entry']))
        selector['natural_keys'] = sorted(keys)
        result['selectors'].append(selector)
    result['records'].sort(key=lambda entry: (entry['kind'], entry['natural_key']))
    if stock_dependencies is not None:
        result['stock_dependencies'] = deepcopy(stock_dependencies)
    return result


def input_freshness(db, organization_id, lineage, *, state_cache=None):
    """Return unchanged, changed or unknown without changing any persisted result."""
    if (db is None or not isinstance(lineage, dict) or lineage.get('version') != VERSION
            or lineage.get('organization_id') != organization_id
            or lineage.get('complete') is not True
            or not isinstance(lineage.get('records'), list)
            or not isinstance(lineage.get('selectors'), list)
            or not lineage['selectors']):
        return 'unknown'
    try:
        records, selectors = lineage['records'], lineage['selectors']
        kinds = {entry['kind'] for entry in records} | {selector['kind'] for selector in selectors}
        if not kinds <= SCHEMAS.keys():
            return 'unknown'
        expected = {}
        for entry in records:
            key = (entry['kind'], entry['natural_key'])
            if key in expected or not isinstance(entry['revision'], int) or entry['revision'] < 0:
                return 'unknown'
            expected[key] = entry
        covered = set()
        for selector in selectors:
            if not isinstance(selector['natural_keys'], list):
                return 'unknown'
            covered.update((selector['kind'], key) for key in selector['natural_keys'])
        if covered != set(expected):
            return 'unknown'
        state = _state(db, organization_id, selectors, state_cache)
        for selector in selectors:
            actual_keys = sorted(key for (kind, key), item in state.items() if _selected(item['row'], selector))
            if actual_keys != selector['natural_keys']:
                return 'changed'
        for key, entry in expected.items():
            current = state.get(key)
            if current is None or any(current['entry'].get(field) != entry.get(field) for field in (
                    'row_sha256', 'revision', 'batch_id', 'record_id', 'branch_id')):
                return 'changed'
    except (KeyError, TypeError, ValueError):
        return 'unknown'
    from .stock_dependencies import dependency_freshness, legacy_dependencies_present
    if 'stock_dependencies' in lineage:
        return dependency_freshness(db, organization_id, lineage['stock_dependencies'])
    # Baseline snapshot evidence is also canonical lineage, but must not recurse
    # into a check of its own journal. Only procurement lineage includes a sales
    # selector inherited from a forecast as well as the target stock selector.
    if any(selector.get('kind') == 'daily_sales' for selector in selectors):
        if legacy_dependencies_present(db, organization_id, selectors):
            return 'changed'
    return 'unchanged'


def input_provenance(organization_id, lineage):
    """Compact public evidence; full row hashes remain in the immutable result."""
    if (not isinstance(lineage, dict) or lineage.get('organization_id') != organization_id
            or lineage.get('version') != VERSION or not isinstance(lineage.get('records'), list)):
        return None
    try:
        kinds = {}
        for entry in lineage['records']:
            kind = entry['kind']
            if kind not in SCHEMAS:
                return None
            item = kinds.setdefault(kind, {'kind': kind, 'record_count': 0,
                                         'legacy_record_count': 0, 'batches': {}})
            item['record_count'] += 1
            batch_id = entry['batch_id']
            if batch_id is None:
                item['legacy_record_count'] += 1
            else:
                batch = item['batches'].setdefault(batch_id, {'batch_id': batch_id,
                    'record_count': 0, 'href': '/api/v1/imports/' + batch_id})
                batch['record_count'] += 1
        entries = []
        for kind in sorted(kinds):
            item = kinds[kind]
            item['batches'] = [item['batches'][key] for key in sorted(item['batches'])]
            entries.append(item)
        digest = hashlib.sha256(json.dumps(lineage, sort_keys=True, separators=(',', ':'),
                                          ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
        return {'version': VERSION, 'sha256': digest, 'complete': lineage.get('complete') is True,
                'record_count': len(lineage['records']),
                'legacy_record_count': sum(item['legacy_record_count'] for item in entries),
                'kinds': entries}
    except (KeyError, TypeError, ValueError):
        return None
