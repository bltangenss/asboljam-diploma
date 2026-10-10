"""Operator-owned tenant lifecycle. Caller commits or rolls back every change.

Bootstrap creates identity metadata and the first administrator only. It never
invents branches, operational records, source consent or permission for REAL data.
All access-changing transactions lock Organization before User/session/job rows.
"""
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .db import (Audit, Forecast, Idempotency, ImportBatch, ImportEvidence, ImportReceipt,
                 Job, Organization, OrganizationSource, Plan, RecipeActivation, RecipeCommandReceipt,
                 Record, RecordRevision, StockCommandReceipt, StockCountAnchor, StockLedger, StockMovement, User, now)
from .security import password_hash


class TenantError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def organization_json(organization):
    return {key: getattr(organization, key) for key in (
        'id', 'name', 'timezone', 'currency', 'status', 'data_policy', 'provenance')}


def lock_organization(db, organization_id):
    found = db.execute(update(Organization).where(Organization.id == organization_id)
                       .values(status=Organization.status)).rowcount
    return db.get(Organization, organization_id, populate_existing=True) if found else None


def organization_active(db, organization_id):
    organization = db.get(Organization, organization_id, populate_existing=True)
    return organization is not None and organization.status == 'active'


def _operator(operator_id, reason):
    if not isinstance(operator_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,55}', operator_id):
        raise TenantError('OPERATOR_INVALID', 'Operator ID must be an ASCII identifier of 1–55 characters.')
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise TenantError('REASON_REQUIRED', 'An audit reason of 3–1000 characters is required.')
    return 'operator:' + operator_id, reason.strip()


def validate_bootstrap(*, organization_id, name, timezone, currency='KZT',
                       data_policy='unconfigured', email, operator_id, reason):
    if not isinstance(organization_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', organization_id):
        raise TenantError('ORGANIZATION_ID_INVALID', 'Use an ASCII organization identifier of 1–64 characters.')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise TenantError('ORGANIZATION_NAME_INVALID', 'Organization name must contain 1–200 characters.')
    if not isinstance(timezone, str) or not timezone or len(timezone) > 64:
        raise TenantError('TIMEZONE_INVALID', 'Select an explicit IANA timezone.')
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise TenantError('TIMEZONE_INVALID', 'Select an explicit IANA timezone.') from None
    if currency != 'KZT':
        raise TenantError('CURRENCY_UNSUPPORTED', 'This application currently supports KZT only.')
    if data_policy not in {'synthetic_only', 'unconfigured'}:
        raise TenantError('DATA_POLICY_INVALID', 'Only unconfigured or synthetic_only are supported.')
    if not isinstance(email, str) or len(email) > 255 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise TenantError('EMAIL_INVALID', 'Enter a valid administrator email.')
    actor, reason = _operator(operator_id, reason)
    return dict(organization_id=organization_id, name=name.strip(), timezone=timezone,
                currency=currency, data_policy=data_policy, email=email.lower(),
                actor_id=actor, reason=reason)


def preflight_bootstrap(db, **metadata):
    values = validate_bootstrap(**metadata)
    organization_id = values['organization_id']
    if db.get(Organization, organization_id) is not None:
        raise TenantError('ORGANIZATION_EXISTS', 'Organization identifier already exists.', 409)
    # Legacy/orphan objects must never silently acquire a new administrator.
    for model in (User, Record, ImportBatch, Job, Forecast, Plan, Audit, Idempotency,
                  ImportEvidence, RecordRevision, ImportReceipt, OrganizationSource,
                  StockLedger, StockMovement, StockCountAnchor, StockCommandReceipt, RecipeActivation, RecipeCommandReceipt):
        if db.scalar(select(model.organization_id).where(model.organization_id == organization_id).limit(1)) is not None:
            raise TenantError('ORGANIZATION_ORPHANED', 'Organization identifier is already referenced; reconcile the store first.', 409)
    if db.scalar(select(User.id).where(User.email == values['email'])) is not None:
        raise TenantError('EMAIL_EXISTS', 'Administrator email is already registered.', 409)
    return values


def bootstrap_tenant(db, *, password, **metadata):
    values = preflight_bootstrap(db, **metadata)
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise TenantError('PASSWORD_INVALID', 'Password must contain 12–1024 characters.')
    if any(password in str(value) for value in values.values()):
        raise TenantError('METADATA_SECRET_INVALID', 'Tenant metadata must not contain the password.')
    organization = Organization(id=values['organization_id'], name=values['name'],
        timezone=values['timezone'], currency=values['currency'], status='active',
        data_policy=values['data_policy'], provenance='operator_bootstrap')
    admin = User(id=uuid.uuid4().hex, organization_id=organization.id, email=values['email'],
                 password_hash=password_hash(password), role='admin', branch_ids=[], active=True)
    db.add(organization)
    db.add(admin)
    db.add(Audit(id=uuid.uuid4().hex, organization_id=organization.id, branch_id=None,
                 actor_id=values['actor_id'], action='tenant.created', entity_id=organization.id,
                 details={'reason': values['reason'], 'first_admin_id': admin.id,
                          'data_policy': values['data_policy']}))
    try:
        db.flush()
    except IntegrityError:
        raise TenantError('BOOTSTRAP_CONFLICT', 'Tenant or administrator was created concurrently; no bootstrap committed.', 409) from None
    return {'organization': organization_json(organization), 'admin_user_id': admin.id,
            'branch_count': 0}


def preflight_configure_real_source(db, *, organization_id, source_id, mapping_version,
                                   branch_id, authorization_reference, purpose, operator_id, reason):
    """Validate a single declared source without activating or creating data.

    The opaque authorization reference points to an operator-held record. This
    registration does not verify its contents, source authenticity or legal basis.
    """
    actor, reason = _operator(operator_id, reason)
    if not isinstance(organization_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', organization_id):
        raise TenantError('ORGANIZATION_ID_INVALID', 'Use an ASCII organization identifier.')
    for value, maximum in ((source_id, 64), (mapping_version, 64), (authorization_reference, 128)):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,' + str(maximum) + '}', value):
            raise TenantError('SOURCE_METADATA_INVALID', 'Use bounded opaque ASCII identifiers, without paths or personal data.')
    if not isinstance(branch_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', branch_id):
        raise TenantError('SOURCE_BRANCH_INVALID', 'Use an ASCII branch identifier.')
    if purpose not in {'pilot', 'test_fixture'}:
        raise TenantError('SOURCE_PURPOSE_INVALID', 'Source purpose must be pilot or test_fixture.')
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise TenantError('ORGANIZATION_NOT_FOUND', 'Organization not found.', 404)
    if organization.status != 'active':
        raise TenantError('TENANT_NOT_ACTIVE', 'Activate the organization before configuring its data source.', 409)
    if db.get(OrganizationSource, organization_id) is not None:
        raise TenantError('SOURCE_ALREADY_CONFIGURED', 'The source registration is immutable.', 409)
    if organization.data_policy != 'unconfigured':
        raise TenantError('DATA_POLICY_CONFLICT', 'Only an empty unconfigured organization may accept a real source.', 409)
    if (not organization.name or not organization.name.strip() or len(organization.name) > 200
            or not organization.timezone or len(organization.timezone) > 64 or organization.currency != 'KZT'):
        raise TenantError('TENANT_METADATA_REQUIRED', 'A known name, IANA timezone and KZT currency are required.')
    try:
        ZoneInfo(organization.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise TenantError('TENANT_METADATA_REQUIRED', 'A valid IANA timezone is required.') from None
    for model in (Record, ImportBatch, Job, Forecast, Plan, Idempotency,
                  ImportEvidence, RecordRevision, ImportReceipt,
                  StockLedger, StockMovement, StockCountAnchor, StockCommandReceipt, RecipeActivation, RecipeCommandReceipt):
        if db.scalar(select(model.organization_id).where(model.organization_id == organization_id).limit(1)) is not None:
            raise TenantError('TENANT_NOT_EMPTY', 'Operational data or history already exists; create a separate organization.', 409)
    # Identity and tenant administration are expected before configuration. Any
    # other audit history is an operational trace, even if its rows were removed.
    allowed_audit = ('tenant.created', 'tenant.suspended', 'tenant.resumed',
                     'session.login', 'native.login', 'account.password_changed',
                     'account.password_reset', 'user.created', 'user.access_changed')
    if db.scalar(select(Audit.id).where(Audit.organization_id == organization_id,
                                        Audit.action.not_in(allowed_audit)).limit(1)) is not None:
        raise TenantError('TENANT_NOT_EMPTY', 'Operational audit history already exists; create a separate organization.', 409)
    return dict(organization_id=organization_id, source_id=source_id, mapping_version=mapping_version,
                branch_id=branch_id, authorization_reference=authorization_reference,
                purpose=purpose, actor_id=actor, reason=reason)


def configure_real_source(db, *, organization_id, source_id, mapping_version, branch_id,
                          authorization_reference, purpose, operator_id, reason):
    """Activate and record one immutable source; caller commits the whole transaction."""
    if not isinstance(organization_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', organization_id):
        raise TenantError('ORGANIZATION_ID_INVALID', 'Use an ASCII organization identifier.')
    organization = lock_organization(db, organization_id)
    if organization is None:
        raise TenantError('ORGANIZATION_NOT_FOUND', 'Organization not found.', 404)
    values = preflight_configure_real_source(db, organization_id=organization_id,
        source_id=source_id, mapping_version=mapping_version, branch_id=branch_id,
        authorization_reference=authorization_reference, purpose=purpose,
        operator_id=operator_id, reason=reason)
    from .accounts import lock_user, revoke_user_access
    for identifier in db.scalars(select(User.id).where(User.organization_id == organization_id).order_by(User.id)):
        user = lock_user(db, identifier, organization_id)
        if user is not None:
            revoke_user_access(db, user, actor_id=values['actor_id'])
    source = OrganizationSource(**{key: value for key, value in values.items() if key != 'reason'}, version=1)
    organization.data_policy = 'real_only'
    db.add(source)
    db.add(Audit(id=uuid.uuid4().hex, organization_id=organization_id, branch_id=None,
                 actor_id=values['actor_id'], action='tenant.real_source_configured', entity_id=organization_id,
                 details={'previous_data_policy': 'unconfigured', 'data_policy': 'real_only',
                          'source_id': source_id, 'mapping_version': mapping_version, 'branch_id': branch_id,
                          'purpose': purpose, 'source_version': 1, 'reason': values['reason']}))
    db.flush()
    return {'organization': organization_json(organization),
            'source': {'source_id': source_id, 'mapping_version': mapping_version, 'branch_id': branch_id,
                       'purpose': purpose, 'version': 1}, 'reauth_required': True}


def set_tenant_status(db, *, organization_id, status, expected_status, operator_id, reason):
    actor, reason = _operator(operator_id, reason)
    if status not in {'active', 'suspended'} or expected_status not in {'active', 'suspended'}:
        raise TenantError('STATUS_INVALID', 'Tenant status must be active or suspended.')
    organization = lock_organization(db, organization_id)
    if organization is None:
        raise TenantError('ORGANIZATION_NOT_FOUND', 'Organization not found.', 404)
    if organization.status != expected_status:
        raise TenantError('STALE_STATUS', 'Organization status changed; run preflight again.', 409)
    if status == expected_status:
        raise TenantError('STATUS_UNCHANGED', 'The organization already has this status.', 409)
    organization.status = status
    if status == 'suspended':
        # Local import avoids a dependency cycle: credential locking uses this module.
        from .accounts import lock_user, revoke_user_access
        identifiers = list(db.scalars(select(User.id).where(User.organization_id == organization_id).order_by(User.id)))
        for identifier in identifiers:
            user = lock_user(db, identifier, organization_id)
            if user is not None:
                revoke_user_access(db, user, actor_id=actor)
        # Also fail closed for orphan jobs whose actor no longer exists.
        cancelled = db.execute(update(Job).where(
            Job.organization_id == organization_id, Job.status.in_(['queued', 'running'])
        ).values(status='failed', result_id=None, finished_at=now(),
                 error='JOB_ACCESS_REVOKED: Organization access revoked.')
            .returning(Job.id, Job.branch_id)).all()
        for job_id, branch_id in cancelled:
            db.add(Audit(id=uuid.uuid4().hex, organization_id=organization_id, branch_id=branch_id,
                         actor_id=actor, action='job.cancelled', entity_id=job_id,
                         details={'code': 'JOB_ACCESS_REVOKED'}))
    db.add(Audit(id=uuid.uuid4().hex, organization_id=organization_id, branch_id=None,
                 actor_id=actor, action='tenant.' + ('suspended' if status == 'suspended' else 'resumed'),
                 entity_id=organization_id, details={'reason': reason,
                 'previous_status': expected_status, 'status': status}))
    db.flush()
    return organization_json(organization)
