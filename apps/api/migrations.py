"""Explicit, transactional schema history for SQLite and PostgreSQL.

0001 retains its original table allowlist. Later models never silently enter that
migration. 0002 materializes tenant metadata once from pre-existing scoped rows;
normal startup never invents organizations for subsequently orphaned records.
0003 adds import evidence, revisions and receipts without fabricating legacy provenance.
"""
from sqlalchemy import case, literal, select, text, union

from .db import Base, Organization, now


VERSIONS = ('0001', '0002', '0003')
LEGACY_TABLE_NAMES = (
    'users', 'auth_sessions', 'refresh_tokens', 'login_attempts',
    'operational_records', 'import_batches', 'jobs', 'forecasts',
    'plans', 'audit_events', 'idempotency_keys',
)
ORGANIZATION_TABLE_NAMES = (
    'users', 'operational_records', 'import_batches', 'jobs',
    'forecasts', 'plans', 'audit_events', 'idempotency_keys',
)
IMPORT_TABLE_NAMES = ('import_evidence', 'record_revisions', 'import_receipts')
# Stable per-database PostgreSQL transaction lock shared by API/worker/migration CLI.
_MIGRATION_LOCK = 0x4153424F4C4A414D


class MigrationError(RuntimeError):
    """Migration history cannot safely be applied by this application version."""


def _initial_schema(connection):
    Base.metadata.create_all(connection, tables=[Base.metadata.tables[name] for name in LEGACY_TABLE_NAMES])


def _backfill_organizations(connection):
    legacy_ids = union(*[
        select(Base.metadata.tables[name].c.organization_id)
        for name in ORGANIZATION_TABLE_NAMES
    ]).subquery()
    identifier = legacy_ids.c.organization_id
    statement = Organization.__table__.insert().from_select(
        ['id', 'name', 'timezone', 'currency', 'status', 'data_policy', 'provenance', 'created_at'],
        select(identifier,
               case((identifier == 'demo', literal('AsBoljam Demo')), else_=None),
               case((identifier == 'demo', literal('Asia/Qyzylorda')), else_=None),
               literal('KZT'), literal('active'), literal('synthetic_only'),
               literal('legacy_migration'), literal(now())),
    )
    connection.execute(statement)


def _tenant_schema(connection):
    # An unexpected pre-existing table is an error; never stamp an unknown shape.
    Organization.__table__.create(connection, checkfirst=False)
    _backfill_organizations(connection)


def _import_schema(connection):
    # Old operational rows/batches remain untouched; their missing source evidence is unknown.
    for name in IMPORT_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def migrate(engine):
    if engine.dialect.name not in {'sqlite', 'postgresql'}:
        raise MigrationError('Unsupported database backend for schema migrations')
    with engine.connect() as connection:
        try:
            if engine.dialect.name == 'sqlite':
                # sqlite3 legacy transaction mode does not begin a transaction for DDL.
                # An explicit write transaction both serializes runners and rolls DDL back.
                connection.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                connection.begin()
                connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': _MIGRATION_LOCK})
            connection.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(32) PRIMARY KEY)'))
            applied = tuple(connection.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())
            if applied != VERSIONS[:len(applied)]:
                raise MigrationError('Unsupported or incomplete migration history; use a compatible application version')
            completed = []
            for version, operation in zip(VERSIONS, (_initial_schema, _tenant_schema, _import_schema)):
                if version not in applied:
                    operation(connection)
                    connection.execute(text('INSERT INTO schema_migrations (version) VALUES (:version)'), {'version': version})
                    completed.append(version)
            connection.commit()
            return tuple(completed)
        except Exception:
            connection.rollback()
            raise
