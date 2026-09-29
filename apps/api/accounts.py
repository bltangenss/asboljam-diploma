"""Credential changes in the caller's transaction; never print or return secrets.

Callers must commit success and roll back failures. The User row lock is also
used by login, refresh, access updates and worker publication so revocation
cannot race with issuance of a new session based on stale credentials.
"""
import time
import uuid

from sqlalchemy import update

from .db import Audit, AuthSession, Job, RefreshToken, User, now
from .security import password_hash, verify_password


class CredentialError(ValueError):
    def __init__(self, code, message, status=422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def lock_user(db, user_id, organization_id=None):
    """Acquire a real write lock on SQLite/PostgreSQL, then discard cached data."""
    statement = update(User).where(User.id == user_id)
    if organization_id is not None:
        statement = statement.where(User.organization_id == organization_id)
    found = db.execute(statement.values(active=User.active)).rowcount
    return db.get(User, user_id, populate_existing=True) if found else None


def revoke_user_access(db, user, *, actor_id):
    """Revoke sessions/jobs atomically; caller holds this user's row lock."""
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id).values(revoked=True))
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked=True))
    cancelled = db.execute(update(Job).where(
        Job.actor_id == user.id, Job.organization_id == user.organization_id,
        Job.status.in_(['queued', 'running'])
    ).values(status='failed', result_id=None, finished_at=now(),
             error='JOB_ACCESS_REVOKED: Есептеуге рұқсат өзгерген. Менеджерге хабарласыңыз.')
        .returning(Job.id, Job.branch_id)).all()
    for job_id, branch_id in cancelled:
        db.add(Audit(id=uuid.uuid4().hex, organization_id=user.organization_id,
                     branch_id=branch_id, actor_id=actor_id, action='job.cancelled',
                     entity_id=job_id, details={'code': 'JOB_ACCESS_REVOKED'}))


def _validate_new_password(new_password):
    if not isinstance(new_password, str) or not 12 <= len(new_password) <= 1024:
        raise CredentialError('PASSWORD_INVALID', 'Жаңа құпиясөз 12–1024 таңба болуы керек.')


def _replace_password(db, user, new_password, *, actor_id, action, details):
    if verify_password(new_password, user.password_hash):
        raise CredentialError('PASSWORD_UNCHANGED', 'Жаңа құпиясөз бұрынғыдан өзгеше болуы керек.')
    user.password_hash = password_hash(new_password)
    revoke_user_access(db, user, actor_id=actor_id)
    db.add(Audit(id=uuid.uuid4().hex, organization_id=user.organization_id,
                 branch_id=None, actor_id=actor_id, action=action,
                 entity_id=user.id, details=details))
    return {'status': 'password_changed', 'reauth_required': True}


def change_password(db, *, organization_id, user_id, current_password, new_password, session_id):
    _validate_new_password(new_password)
    if not isinstance(current_password, str) or not 1 <= len(current_password) <= 1024:
        raise CredentialError('CURRENT_PASSWORD_INVALID', 'Қазіргі құпиясөз сәйкес емес.', 400)
    user = lock_user(db, user_id, organization_id)
    auth = db.get(AuthSession, session_id, populate_existing=True)
    if (user is None or not user.active or auth is None or auth.user_id != user_id
            or auth.revoked or auth.expires_at < time.time()):
        raise CredentialError('AUTH_REQUIRED', 'Қайта кіріңіз.', 401)
    if not verify_password(current_password, user.password_hash):
        raise CredentialError('CURRENT_PASSWORD_INVALID', 'Қазіргі құпиясөз сәйкес емес.', 400)
    return _replace_password(db, user, new_password, actor_id=user.id,
                             action='account.password_changed', details={})


def reset_password(db, *, organization_id, user_id, new_password, operator_id, reason):
    """Local operator recovery for an exact account, without activating it.

    operator_id is an operator label, not an application user impersonation.
    The caller obtains the password interactively and owns the commit/rollback.
    """
    _validate_new_password(new_password)
    if not isinstance(operator_id, str) or not operator_id.strip() or len(operator_id) > 55:
        raise CredentialError('OPERATOR_INVALID', 'Operator ID must contain 1–55 characters.')
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 1000:
        raise CredentialError('REASON_REQUIRED', 'Recovery reason must contain 3–1000 characters.')
    if new_password in reason or new_password in operator_id:
        raise CredentialError('RECOVERY_METADATA_INVALID', 'Recovery metadata must not contain the new password.')
    if not isinstance(organization_id, str) or not organization_id or not isinstance(user_id, str) or not user_id:
        raise CredentialError('ACCOUNT_NOT_FOUND', 'Account not found in the selected organization.', 404)
    user = lock_user(db, user_id, organization_id)
    if user is None:
        raise CredentialError('ACCOUNT_NOT_FOUND', 'Account not found in the selected organization.', 404)
    return _replace_password(db, user, new_password, actor_id='operator:' + operator_id.strip(),
                             action='account.password_reset',
                             details={'operator_id': operator_id.strip(), 'reason': reason.strip()})
