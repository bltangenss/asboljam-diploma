"""Operator recovery for an existing account. No email, seed or schema changes.

DATABASE_URL must explicitly select the existing store. The default is a read-only
preflight; --apply reads a replacement password twice from a non-echoing terminal.
Passwords are never accepted in command arguments or environment variables.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from apps.api.accounts import CredentialError, reset_password
from apps.api.config import ConfigurationError, load_settings
from apps.api.db import AuthSession, Job, RefreshToken, User, make_engine, sessions


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error echoes unknown arguments, possibly a password.
        self.exit(2, 'Invalid arguments. Use --help; passwords must never be command arguments.\n')


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise argparse.ArgumentTypeError('Use an existing ASCII identifier.')
    return value


def preflight(db, organization_id, user_id):
    user = db.scalar(select(User).where(User.id == user_id, User.organization_id == organization_id))
    if user is None:
        return None
    return {
        'status': 'found', 'organization_id': organization_id, 'user_id': user_id,
        'active': user.active, 'role': user.role,
        'unrevoked_sessions': db.scalar(select(func.count()).select_from(AuthSession).where(
            AuthSession.user_id == user.id, AuthSession.revoked == False)),
        'unrevoked_refresh_tokens': db.scalar(select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.revoked == False)),
        'pending_jobs': db.scalar(select(func.count()).select_from(Job).where(
            Job.organization_id == organization_id, Job.actor_id == user.id, Job.status.in_(['queued', 'running']))),
    }


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--organization-id', type=identifier, required=True)
    parser.add_argument('--user-id', type=identifier, required=True)
    parser.add_argument('--operator-id', type=identifier, help='Named operator identifier, at most 55 characters')
    parser.add_argument('--reason', help='Audit reason, 3..1000 characters; do not enter secrets here')
    parser.add_argument('--apply', action='store_true', help='Replace password and revoke sessions/jobs after hidden prompts')
    args = parser.parse_args(argv)
    if args.apply and (not args.operator_id or len(args.operator_id) > 55
                       or not args.reason or not 3 <= len(args.reason.strip()) <= 1000):
        parser.error('An operator and reason are required.')
    if not os.environ.get('DATABASE_URL', '').strip():
        print('DATABASE_URL must explicitly select an existing database.', file=sys.stderr)
        return 2
    engine = None
    try:
        settings = load_settings()
        url = make_url(settings.database_url)
        if url.get_backend_name() == 'sqlite' and (
                not url.database or url.database == ':memory:' or url.query
                or not Path(url.database).is_file()):
            print('Recovery requires an existing SQLite database file.', file=sys.stderr)
            return 2
        if args.apply and not sys.stdin.isatty():
            print('Recovery requires an interactive terminal with hidden password input.', file=sys.stderr)
            return 2
        engine = make_engine(settings.database_url)
        factory = sessions(engine)
        with factory() as db:
            report = preflight(db, args.organization_id, args.user_id)
        if report is None:
            print('ACCOUNT_NOT_FOUND: check the organization and user identifiers.', file=sys.stderr)
            return 2
        print(json.dumps(report, ensure_ascii=False))
        if not args.apply:
            print('Preflight only. No account changes made.')
            return 0
        # Never hold the target row lock while an operator is entering a password.
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('New password (hidden): ')
            repeated = getpass.getpass('Repeat new password (hidden): ')
        if password != repeated:
            print('PASSWORD_MISMATCH: no account changes made.', file=sys.stderr)
            return 2
        with factory() as db:
            reset_password(db, organization_id=args.organization_id, user_id=args.user_id,
                           new_password=password, operator_id=args.operator_id, reason=args.reason)
            db.commit()
        print('Password replaced. Sessions revoked and pending jobs cancelled; audit recorded.')
        return 0
    except ConfigurationError:
        print('Invalid environment configuration. Check the operator runbook.', file=sys.stderr)
        return 2
    except CredentialError as exc:
        # Only server-defined machine codes; never echo exception input or values.
        print(f'{exc.code}: no account changes made.', file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print('Recovery cancelled: hidden input was not completed.', file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError):
        # DB exceptions can include SQL-bound values or the connection string.
        print('DATABASE_ERROR: verify connectivity and schema, then inspect account status before retrying.', file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
