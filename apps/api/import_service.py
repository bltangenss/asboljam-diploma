"""Atomic imports with provenance, replay receipts and immutable row revisions.

The API holds Organization then User locks for each mutation. Callers own commit.
Each tenant accepts only its configured origin and immutable source contract.
"""
from copy import deepcopy
import hashlib
import json
import re
import uuid

from sqlalchemy import func, select

from .db import Audit, ImportBatch, ImportEvidence, ImportReceipt, Organization, Record, RecordRevision, now
from .importing import OPERATIONAL_KINDS, SCHEMAS, natural_key, parse_csv, validate_rows
from .lineage import row_digest
from .data_policy import DataPolicyError, business_clock, ensure_rows, metadata as origin_metadata, policy_context


OPERATIONAL = OPERATIONAL_KINDS


class ImportProblem(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def kind_allowed(user, kind, write=False):
    if not write:
        return kind in SCHEMAS and (user.role in {'admin', 'manager', 'analyst'}
            or user.role == 'warehouse' and kind in {'inventory_lots', 'ingredients', 'branches'})
    return (kind in SCHEMAS and (user.role == 'admin'
        or user.role == 'manager' and kind in OPERATIONAL
        or user.role == 'warehouse' and kind == 'inventory_lots'))


def _scope(user, batch, evidence=None):
    if batch.organization_id != user.organization_id or not kind_allowed(user, batch.kind):
        return False
    if batch.status != 'committed' and user.role != 'admin' and batch.actor_id != user.id:
        return False
    if batch.kind == 'branches' and batch.status == 'preview' and batch.actor_id == user.id and user.role == 'admin':
        return True
    branches = (evidence.summary.get('branch_ids', []) if evidence else
                {r['branch_id'] for r in batch.rows if r.get('branch_id') is not None})
    return set(branches) <= set(user.branch_ids)


def get_batch(db, user, batch_id):
    batch = db.get(ImportBatch, batch_id)
    evidence = db.get(ImportEvidence, batch_id) if batch else None
    if batch is None or not _scope(user, batch, evidence):
        raise ImportProblem('NOT_FOUND', 'Импорт табылмады.', 404)
    return batch, evidence


def _existing(db, organization_id, kind):
    return {r.natural_key: r for r in db.scalars(select(Record).where(
        Record.organization_id == organization_id, Record.kind == kind))}


def _versions(db, organization_id, kind):
    return dict(db.execute(select(RecordRevision.natural_key, func.max(RecordRevision.revision)).where(
        RecordRevision.organization_id == organization_id, RecordRevision.kind == kind
    ).group_by(RecordRevision.natural_key)).all())


def _check_stored_origins(db, organization_id, context, existing):
    ensure_rows(context, [record.data for record in existing.values()])
    for kind in ('branches', 'meals', 'ingredients', 'suppliers'):
        ensure_rows(context, [record.data for record in _existing(db, organization_id, kind).values()])


def _classify(rows, kind, mode, existing, versions):
    counts = dict(new=0, unchanged=0, updated=0, conflicting=0)
    changes, expected, errors = [], {}, []
    for index, row in enumerate(rows, 2):
        key = natural_key(kind, row)
        old = existing.get(key)
        old_hash = row_digest(old.data) if old else None
        expected[key] = {'sha256': old_hash, 'revision': versions.get(key, 0)}
        if old is None and mode == 'append':
            operation = 'insert'; counts['new'] += 1
        elif old is not None and old_hash == row_digest(row):
            operation = 'unchanged'; counts['unchanged'] += 1
        elif old is not None and mode == 'correction':
            operation = 'update'; counts['updated'] += 1
        else:
            operation = 'conflict'; counts['conflicting'] += 1
            errors.append({'row_number': index, 'field': 'key',
                'code': 'CORRECTION_REQUIRES_EXISTING_KEY' if old is None else 'DUPLICATE_CONFLICT',
                'message': 'Түзету үшін бұрынғы кілт қажет.' if old is None else 'Кілт бар, мәндер басқа. Түзету режимін қолданыңыз.'})
        if len(changes) < 10:
            changes.append({'key': key, 'operation': operation,
                            'before': deepcopy(old.data) if old else None, 'after': row})
    return counts, changes, expected, errors


def preview_import(db, user, *, kind, csv_text, mode='append', reason=None,
                   corrects_batch_id=None, source=None):
    if not kind_allowed(user, kind, write=True):
        raise ImportProblem('FORBIDDEN', 'Бұл импортқа рұқсат жоқ.', 403)
    if mode not in {'append', 'correction'}:
        raise ImportProblem('IMPORT_MODE_INVALID', 'Импорт режимі белгісіз.')
    if mode == 'correction' and (kind not in OPERATIONAL or not reason or not 3 <= len(reason.strip()) <= 1000):
        raise ImportProblem('CORRECTION_REASON_REQUIRED', 'Операциялық түзетуге 3–1000 таңбалық себеп қажет.')
    if mode != 'correction' and (reason or corrects_batch_id):
        raise ImportProblem('CORRECTION_MODE_REQUIRED', 'Түзету режимін таңдаңыз.')
    prior_keys = None
    if corrects_batch_id:
        prior, _ = get_batch(db, user, corrects_batch_id)
        if prior.status != 'committed' or prior.kind != kind:
            raise ImportProblem('CORRECTION_SOURCE_INVALID', 'Бастапқы импорттың түрі немесе күйі сәйкес емес.')
        prior_keys = {natural_key(kind, row) for row in prior.rows}
    organization = db.get(Organization, user.organization_id)
    if not organization or organization.status != 'active':
        raise ImportProblem('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимі қолжетімсіз.', 403)
    context = policy_context(db, user.organization_id)
    if context['data_origin'] is None:
        raise ImportProblem('TENANT_DATA_POLICY_REQUIRED', 'Деректер режимі қолжетімсіз.', 403)
    source = source or {}
    if context['source'] and any(source.get(key) != context['source'][key] for key in ('source_id', 'mapping_version')):
        raise ImportProblem('SOURCE_PROFILE_MISMATCH', 'Ұйымға тіркелген дерек көзі мен нұсқасын таңдаңыз.')
    report = {}
    rows, errors = parse_csv(kind, csv_text, report, expected_origin=context['data_origin'])
    try:
        ensure_rows(context, rows)
    except DataPolicyError as exc:
        errors.append({'row_number': 1, 'field': 'branch_id', 'code': exc.code, 'message': exc.message})
    if context['data_origin'] == 'REAL':
        today = business_clock(context)[1].isoformat()
        for index, row in enumerate(rows, 2):
            if kind == 'daily_sales' and row['date'] >= today or kind == 'inventory_lots' and row['snapshot_date'] > today:
                errors.append({'row_number': index, 'field': 'date', 'code': 'BUSINESS_DATE_NOT_CLOSED',
                               'message': 'Сатылым тек аяқталған күнге, ал қор кесіндісі бүгінге не өткен күнге тиесілі болуы керек.'})
    validation_report = dict(rows_checked=0, complete=False,
                             stop_reason='parser_errors', errors_truncated=False)
    if not errors:
        errors = validate_rows(db, user.organization_id, kind, rows,
            user.branch_ids if kind != 'branches' else None, allow_existing=True,
            report=validation_report)
    if not errors and prior_keys is not None and any(natural_key(kind, row) not in prior_keys for row in rows):
        errors = [{'row_number': 1, 'field': 'corrects_batch_id', 'code': 'CORRECTION_SOURCE_MISMATCH',
                   'message': 'Түзету кілттері көрсетілген импортқа жатпайды.'}]
    existing = _existing(db, user.organization_id, kind)
    _check_stored_origins(db, user.organization_id, context, existing)
    if kind == 'branches' and any(natural_key(kind, row) in existing
            and row['branch_id'] not in user.branch_ids for row in rows):
        errors = errors or [{'row_number': 1, 'field': 'branch_id', 'code': 'BRANCH_FORBIDDEN',
                            'message': 'Бұрынғы бөлімшеге рұқсат жоқ.'}]
    existing = {key: record for key, record in existing.items()
                if record.branch_id is None or record.branch_id in user.branch_ids}
    versions = _versions(db, user.organization_id, kind)
    counts, changes, expected, conflicts = _classify(rows, kind, mode, existing, versions)
    # Never reveal another branch's existing values in a rejected preview.
    for change in changes:
        if change['before'] and change['before'].get('branch_id') not in (None, *user.branch_ids):
            change['before'] = None
    if not errors:
        errors = conflicts
    metadata = {**source, 'source_id': source.get('source_id', 'manual_csv'),
        'mapping_version': source.get('mapping_version', 'canonical-v1'),
        'declared_original_sha256': source.get('declared_original_sha256'),
        'timezone': organization.timezone, 'currency': organization.currency,
        'data_origin': context['data_origin'], 'usage_mode': context['usage_mode'],
        'source_contract': context['source'], 'provenance': 'received_csv_text',
        'hash_version': 'canonical-v1', 'original_hash_verified': False}
    days = sorted({r.get('date', r.get('snapshot_date')) for r in rows if r.get('date', r.get('snapshot_date'))})
    summary = {**report, 'counts': {**counts, 'rows_seen': report['rows_seen'],
        'rows_checked': report['rows_checked'], 'parsed': len(rows)},
        'scan_complete': report['scan_complete'] and validation_report['complete'],
        'stop_reason': report['stop_reason'] or (
            'validation_error_limit' if validation_report['stop_reason'] == 'error_limit'
            else validation_report['stop_reason']),
        'validation_complete': validation_report['complete'],
        'validation_rows_checked': validation_report['rows_checked'],
        'validation_stop_reason': validation_report['stop_reason'],
        'branch_ids': sorted({r['branch_id'] for r in rows if r.get('branch_id') is not None}),
        'period': {'from': days[0] if days else None, 'to': days[-1] if days else None},
        'errors_truncated': report['errors_truncated'] or validation_report['errors_truncated'] or len(errors) > 500,
        'changes': changes}
    batch = ImportBatch(id=uuid.uuid4().hex, organization_id=user.organization_id,
        actor_id=user.id, kind=kind, rows=rows, errors=errors[:500], status='preview')
    canonical = sorted((natural_key(kind, row), row_digest(row)) for row in rows)
    evidence = ImportEvidence(batch_id=batch.id, organization_id=user.organization_id,
        actor_id=user.id, kind=kind, source=metadata, summary=summary, expected_state=expected,
        received_text_sha256=hashlib.sha256(csv_text.encode('utf-8')).hexdigest(),
        canonical_rows_sha256=hashlib.sha256(json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest(),
        mode=mode, reason=reason.strip() if reason else None, corrects_batch_id=corrects_batch_id)
    db.add_all([batch, evidence]); db.flush()
    return batch_view(db, user, batch, evidence)


def batch_view(db, user, batch, evidence=None, *, details=True):
    evidence = evidence or db.get(ImportEvidence, batch.id)
    summary = evidence.summary if evidence else {}
    result = {'id': batch.id, 'kind': batch.kind, 'status': batch.status,
        'actor_id': batch.actor_id, 'created_at': batch.created_at,
        'committed_at': evidence.committed_at if evidence else None,
        'row_count': len(batch.rows), 'valid': not batch.errors,
        'can_commit': batch.status == 'preview' and not batch.errors and kind_allowed(user, batch.kind, write=True)
            and batch.actor_id == user.id and evidence is not None,
        'mode': evidence.mode if evidence else 'append', 'reason': evidence.reason if evidence else None,
        'corrects_batch_id': evidence.corrects_batch_id if evidence else None,
        'source': evidence.source if evidence else {'provenance': 'legacy_unattributed'},
        'received_text_sha256': evidence.received_text_sha256 if evidence else None,
        'canonical_rows_sha256': evidence.canonical_rows_sha256 if evidence else None,
        'counts': summary.get('counts', {'parsed': len(batch.rows)}),
        'scan_complete': summary.get('scan_complete'), 'stop_reason': summary.get('stop_reason'),
        'validation_complete': summary.get('validation_complete'),
        'validation_rows_checked': summary.get('validation_rows_checked'),
        'validation_stop_reason': summary.get('validation_stop_reason'),
        'errors_truncated': summary.get('errors_truncated'),
        'branch_ids': summary.get('branch_ids', sorted({r['branch_id'] for r in batch.rows if r.get('branch_id') is not None})),
        'period': summary.get('period'), 'preview_limit': 10,
        'receipt': evidence.receipt if evidence else None,
        'data_origin': evidence.source.get('data_origin') if evidence else None,
        'usage_mode': evidence.source.get('usage_mode') if evidence else None,
        'scenario_date': '2026-01-01' if evidence and evidence.source.get('data_origin') == 'SYNTHETIC' else None}
    if details:
        result.update(errors=batch.errors, preview=batch.rows[:10], changes=summary.get('changes', []))
    return result


def list_batches(db, user, limit=50, cursor=0):
    # Streaming bounds memory for large stored preview payloads. All scopes are checked
    # before counting or returning a batch; a mixed batch is not partially disclosed.
    query = select(ImportBatch).where(ImportBatch.organization_id == user.organization_id)
    if user.role != 'admin':
        query = query.where((ImportBatch.actor_id == user.id) | (ImportBatch.status == 'committed'))
    query = query.order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())
    items, total = [], 0
    for batch in db.scalars(query.execution_options(yield_per=20)):
        evidence = db.get(ImportEvidence, batch.id)
        if _scope(user, batch, evidence):
            if cursor <= total < cursor + limit:
                items.append(batch_view(db, user, batch, evidence, details=False))
            total += 1
    return {'items': items, 'total': total, 'next_cursor': str(cursor + limit) if cursor + limit < total else None}


def commit_import(db, user, batch_id, idempotency_key=None):
    batch, evidence = get_batch(db, user, batch_id)
    if batch.actor_id != user.id:
        raise ImportProblem('NOT_FOUND', 'Импорт табылмады.', 404)
    if not kind_allowed(user, batch.kind, write=True):
        raise ImportProblem('FORBIDDEN', 'Өз импортыңызды ғана сақтай аласыз.', 403)
    if evidence is None:
        raise ImportProblem('IMPORT_PREVIEW_REQUIRED', 'Алдымен импортты қайта тексеріңіз.', 409)
    context = policy_context(db, user.organization_id)
    ensure_rows(context, batch.rows)
    if (evidence.source.get('data_origin') != context['data_origin']
            or evidence.source.get('source_contract') != context['source']
            or any(evidence.source.get(field) != context[field] for field in ('timezone', 'currency'))
            or context['data_origin'] == 'REAL' and evidence.source.get('usage_mode') != context['usage_mode']):
        raise ImportProblem('SOURCE_CONTEXT_CHANGED', 'Импорттың дерек көзі өзгерген. Қайта тексеріңіз.', 409)
    key = idempotency_key if idempotency_key is not None else 'batch:' + batch.id
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', key):
        raise ImportProblem('IDEMPOTENCY_INVALID', 'Idempotency-Key жарамсыз.')
    payload_hash = hashlib.sha256(('import.commit.v1:' + batch.id).encode()).hexdigest()
    old = db.scalar(select(ImportReceipt).where(ImportReceipt.organization_id == user.organization_id,
        ImportReceipt.actor_id == user.id, ImportReceipt.key == key))
    if old:
        if old.payload_hash != payload_hash:
            raise ImportProblem('IDEMPOTENCY_CONFLICT', 'Кілт басқа импортқа қолданылған.', 409)
        return old.response
    if batch.status == 'committed' and evidence.receipt:
        response = evidence.receipt
    else:
        if batch.status != 'preview' or batch.errors:
            raise ImportProblem('IMPORT_INVALID', 'Қателері бар импорт қабылданбайды.')
        errors = validate_rows(db, user.organization_id, batch.kind, batch.rows,
            user.branch_ids if batch.kind != 'branches' else None, allow_existing=True)
        if errors:
            raise ImportProblem('IMPORT_INVALID', 'Импортты қайта тексеріңіз.')
        existing, versions = _existing(db, user.organization_id, batch.kind), _versions(db, user.organization_id, batch.kind)
        _check_stored_origins(db, user.organization_id, context, existing)
        if batch.kind == 'branches' and any(natural_key(batch.kind, row) in existing
                and row['branch_id'] not in user.branch_ids for row in batch.rows):
            raise ImportProblem('BRANCH_FORBIDDEN', 'Бұрынғы бөлімшеге рұқсат жоқ.', 403)
        counts, _, expected_now, conflicts = _classify(batch.rows, batch.kind, evidence.mode, existing, versions)
        if evidence.mode == 'correction' and expected_now != evidence.expected_state:
            raise ImportProblem('STALE_IMPORT', 'Деректер өзгерді. Түзетуді қайта тексеріңіз.', 409)
        if conflicts:
            raise ImportProblem('DUPLICATE_CONFLICT', 'Сақталған мәндер басқа. Импортты қайта тексеріңіз.', 409)
        for row in batch.rows:
            natural = natural_key(batch.kind, row)
            record = existing.get(natural)
            before = deepcopy(record.data) if record else None
            digest = row_digest(row)
            if record and row_digest(record.data) == digest:
                continue
            if record is None:
                record = Record(organization_id=user.organization_id, kind=batch.kind,
                    natural_key=natural, branch_id=row.get('branch_id'), data=row)
                db.add(record); db.flush()
            else:
                record.data = deepcopy(row)
            db.add(RecordRevision(id=uuid.uuid4().hex, organization_id=user.organization_id,
                kind=batch.kind, natural_key=natural, branch_id=row.get('branch_id'),
                revision=versions.get(natural, 0) + 1, record_id=record.id,
                before_data=before, after_data=deepcopy(row),
                before_sha256=row_digest(before) if before is not None else None,
                after_sha256=digest, batch_id=batch.id, actor_id=user.id, reason=evidence.reason))
        if batch.kind == 'branches':
            user.branch_ids = sorted(set(user.branch_ids) | {r['branch_id'] for r in batch.rows})
        batch.status = 'committed'; evidence.committed_at = now()
        response = {'id': batch.id, 'status': 'committed', 'row_count': len(batch.rows),
            'inserted_rows': counts['new'], 'updated_rows': counts['updated'],
            'unchanged_rows': counts['unchanged'], **origin_metadata(db, user.organization_id)}
        evidence.receipt = deepcopy(response)
        for branch in {r.get('branch_id') for r in batch.rows}:
            db.add(Audit(id=uuid.uuid4().hex, organization_id=user.organization_id,
                branch_id=branch, actor_id=user.id,
                action='import.corrected' if evidence.mode == 'correction' else 'import.committed',
                entity_id=batch.id, details={'kind': batch.kind,
                    'row_count': sum(1 for row in batch.rows if row.get('branch_id') == branch),
                    'reason': evidence.reason, 'received_text_sha256': evidence.received_text_sha256,
                    'canonical_rows_sha256': evidence.canonical_rows_sha256}))
    db.add(ImportReceipt(id=uuid.uuid4().hex, organization_id=user.organization_id,
        actor_id=user.id, key=key, batch_id=batch.id, payload_hash=payload_hash, response=deepcopy(response)))
    db.flush()
    return response
