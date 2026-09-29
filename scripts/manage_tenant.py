"""Local operator bootstrap/suspension. Default is preflight; never seeds or migrates.

DATABASE_URL must select an existing, migrated store. bootstrap --apply obtains
the first administrator password twice from a hidden interactive prompt.
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

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from apps.api.config import ConfigurationError, load_settings
from apps.api.db import Organization, make_engine, sessions
from apps.api.migrations import VERSIONS
from apps.api.tenants import (TenantError, bootstrap_tenant, configure_real_source, organization_json,
                             preflight_bootstrap, preflight_configure_real_source, set_tenant_status)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Invalid arguments. Use --help; passwords must never be command arguments.\n')


def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise argparse.ArgumentTypeError('Use an ASCII identifier.')
    return value


def main(argv=None):
    parser = SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=SafeParser)
    bootstrap = commands.add_parser('bootstrap', help='Create empty organization and first administrator')
    bootstrap.add_argument('--name', required=True)
    bootstrap.add_argument('--timezone', required=True)
    bootstrap.add_argument('--currency', default='KZT')
    bootstrap.add_argument('--data-policy', default='unconfigured', choices=['unconfigured', 'synthetic_only'])
    bootstrap.add_argument('--admin-email', required=True)
    status = commands.add_parser('status', help='Suspend or resume one organization')
    status.add_argument('--status', required=True, choices=['active', 'suspended'])
    status.add_argument('--expected-status', required=True, choices=['active', 'suspended'])
    configure = commands.add_parser('configure-real', help='Register one source on an empty unconfigured organization')
    configure.add_argument('--source-id', required=True)
    configure.add_argument('--mapping-version', required=True)
    configure.add_argument('--branch-id', required=True, type=identifier)
    configure.add_argument('--authorization-reference', required=True,
                           help='Opaque reference held by the operator; no document contents, paths or personal data')
    configure.add_argument('--purpose', required=True, choices=['pilot', 'test_fixture'])
    for command in (bootstrap, status, configure):
        command.add_argument('--organization-id', required=True, type=identifier)
        command.add_argument('--operator-id', required=True, type=identifier)
        command.add_argument('--reason', required=True, help='Audit reason, 3..1000 characters; no passwords or secrets')
        command.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if len(args.operator_id) > 55 or not 3 <= len(args.reason.strip()) <= 1000:
        parser.error('Operator ID or reason is invalid.')
    if not os.environ.get('DATABASE_URL', '').strip():
        print('DATABASE_URL must explicitly select an existing migrated database.', file=sys.stderr)
        return 2
    engine = None
    try:
        settings = load_settings()
        url = make_url(settings.database_url)
        if url.get_backend_name() == 'sqlite' and (
                not url.database or url.database == ':memory:' or url.query
                or not Path(url.database).is_file()):
            print('Tenant management requires an existing SQLite database file.', file=sys.stderr)
            return 2
        engine = make_engine(settings.database_url)
        with engine.connect() as connection:
            applied = tuple(connection.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())
        if applied != VERSIONS:
            print('MIGRATION_REQUIRED: supported migration state is required; no tenant changes made.', file=sys.stderr)
            return 2
        factory = sessions(engine)
        common = {'organization_id': args.organization_id, 'operator_id': args.operator_id, 'reason': args.reason}
        if args.command == 'bootstrap':
            metadata = dict(common, name=args.name, timezone=args.timezone, currency=args.currency,
                            data_policy=args.data_policy, email=args.admin_email)
            with factory() as db:
                preflight_bootstrap(db, **metadata)
            report = {'status': 'ready', 'organization_id': args.organization_id,
                      'data_policy': args.data_policy, 'branch_count': 0}
        elif args.command == 'configure-real':
            metadata = dict(common, source_id=args.source_id, mapping_version=args.mapping_version,
                            branch_id=args.branch_id, authorization_reference=args.authorization_reference,
                            purpose=args.purpose)
            with factory() as db:
                preflight_configure_real_source(db, **metadata)
            report = {'status': 'ready', 'organization_id': args.organization_id,
                      'requested_data_policy': 'real_only', 'source_id': args.source_id,
                      'mapping_version': args.mapping_version, 'branch_id': args.branch_id,
                      'purpose': args.purpose, 'branch_count': 0}
        else:
            with factory() as db:
                organization = db.get(Organization, args.organization_id)
                if organization is None:
                    raise TenantError('ORGANIZATION_NOT_FOUND', 'Organization not found.', 404)
                if organization.status != args.expected_status:
                    raise TenantError('STALE_STATUS', 'Status changed; inspect before retrying.', 409)
                if organization.status == args.status:
                    raise TenantError('STATUS_UNCHANGED', 'Status is already selected.', 409)
                report = {'status': 'ready', 'organization': organization_json(organization),
                          'requested_status': args.status}
        print(json.dumps(report, ensure_ascii=False))
        if not args.apply:
            print('Preflight only. No tenant changes made.')
            return 0
        if args.command == 'bootstrap':
            if not sys.stdin.isatty():
                print('Bootstrap requires an interactive terminal with hidden password input.', file=sys.stderr)
                return 2
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = getpass.getpass('First administrator password (hidden): ')
                repeated = getpass.getpass('Repeat password (hidden): ')
            if password != repeated:
                print('PASSWORD_MISMATCH: no tenant changes made.', file=sys.stderr)
                return 2
            with factory() as db:
                result = bootstrap_tenant(db, password=password, **metadata)
                db.commit()
            print(json.dumps({'status': 'created', 'organization_id': args.organization_id,
                              'admin_user_id': result['admin_user_id'], 'branch_count': 0}))
        elif args.command == 'configure-real':
            with factory() as db:
                configure_real_source(db, **metadata)
                db.commit()
            print(json.dumps({'status': 'configured', 'organization_id': args.organization_id,
                              'data_policy': 'real_only', 'reauth_required': True}))
        else:
            with factory() as db:
                set_tenant_status(db, status=args.status, expected_status=args.expected_status, **common)
                db.commit()
            print(json.dumps({'status': args.status, 'organization_id': args.organization_id}))
        return 0
    except ConfigurationError:
        print('Invalid environment configuration. Check the operator runbook.', file=sys.stderr)
        return 2
    except TenantError as exc:
        print(f'{exc.code}: no tenant changes made.', file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print('Bootstrap cancelled: hidden input was not completed.', file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError):
        print('DATABASE_ERROR: verify connectivity and migration state before retrying.', file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
