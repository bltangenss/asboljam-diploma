"""Explicit, transactional schema history for SQLite and PostgreSQL.

0001 retains its original table allowlist. Later models never silently enter that
migration. 0002 materializes tenant metadata once from pre-existing scoped rows;
normal startup never invents organizations for subsequently orphaned records.
0003 adds import evidence, revisions and receipts without fabricating legacy provenance.
0004 explicitly adds a real-only policy and operator source registration, without activation.
0005 adds a nullable job heartbeat; started_at remains the immutable claim fence.
0006 adds empty stock journal tables, without asserting existing stock or movements.
0007 adds empty dated recipe activations; imported CSV recipes are never activated implicitly.
0008 adds empty counted stock anchors; neither baseline nor movement history is changed.
0009 adds empty immutable cooking variants and receipts; forecasts remain unchanged.
0010 adds empty branch profiles (city, establishment type); no branch gets a city implicitly.
0011 adds empty day closures; no day is closed or sales row written implicitly.
"""
from sqlalchemy import CheckConstraint, Column, Float, JSON, MetaData, String, Table, Text, case, inspect, literal, select, text, union

from .db import Base, now


VERSIONS = ('0001', '0002', '0003', '0004', '0005', '0006', '0007', '0008', '0009', '0010', '0011')
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
SOURCE_TABLE_NAMES = ('organization_sources',)
STOCK_TABLE_NAMES = ('stock_ledgers', 'stock_movements', 'stock_command_receipts')
RECIPE_TABLE_NAMES = ('recipe_activations', 'recipe_command_receipts')
COUNT_ANCHOR_TABLE_NAMES = ('stock_count_anchors',)
PRODUCTION_TABLE_NAMES = ('production_plans', 'production_plan_receipts')
PROFILE_TABLE_NAMES = ('branch_profiles',)
CLOSURE_TABLE_NAMES = ('day_closures',)
# Stable per-database PostgreSQL transaction lock shared by API/worker/migration CLI.
_MIGRATION_LOCK = 0x4153424F4C4A414D


class MigrationError(RuntimeError):
    """Migration history cannot safely be applied by this application version."""


def _organization_definition(name, *, allow_real=False):
    """Freeze the original eight columns instead of using the evolving ORM model."""
    policy = "data_policy IN ('synthetic_only', 'unconfigured'" + (", 'real_only')" if allow_real else ")")
    return Table(name, MetaData(),
        Column('id', String(64), primary_key=True),
        Column('name', String(200), nullable=True),
        Column('timezone', String(64), nullable=True),
        Column('currency', String(3), nullable=False, server_default='KZT'),
        Column('status', String(16), nullable=False, server_default='active'),
        Column('data_policy', String(32), nullable=False, server_default='unconfigured'),
        Column('provenance', String(32), nullable=False),
        Column('created_at', String(64), nullable=False),
        CheckConstraint("status IN ('active', 'suspended')", name='ck_organization_status'),
        CheckConstraint(policy, name='ck_organization_data_policy'))


_ORGANIZATION_V2 = _organization_definition('organizations')

# Preserve the original job columns even when the current ORM gains lease fields.
_JOB_V1 = Table('jobs', MetaData(),
    Column('id', String(64), primary_key=True),
    Column('organization_id', String(64), nullable=False, index=True),
    Column('branch_id', String(64), nullable=False),
    Column('actor_id', String(64), nullable=False),
    Column('kind', String(32), nullable=False),
    Column('status', String(32), nullable=False, index=True),
    Column('payload', JSON, nullable=False), Column('snapshot', JSON, nullable=False),
    Column('result_id', String(64), nullable=True), Column('error', Text, nullable=True),
    Column('created_at', String(64), nullable=False),
    Column('started_at', Float, nullable=True), Column('finished_at', String(64), nullable=True))


def _initial_schema(connection):
    Base.metadata.create_all(connection, tables=[Base.metadata.tables[name] for name in LEGACY_TABLE_NAMES if name != 'jobs'])
    _JOB_V1.create(connection)


def _backfill_organizations(connection):
    legacy_ids = union(*[
        select(Base.metadata.tables[name].c.organization_id)
        for name in ORGANIZATION_TABLE_NAMES
    ]).subquery()
    identifier = legacy_ids.c.organization_id
    statement = _ORGANIZATION_V2.insert().from_select(
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
    _ORGANIZATION_V2.create(connection, checkfirst=False)
    _backfill_organizations(connection)


def _import_schema(connection):
    # Old operational rows/batches remain untouched; their missing source evidence is unknown.
    for name in IMPORT_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _real_source_schema(connection):
    if connection.dialect.name == 'sqlite':
        # SQLite cannot replace a CHECK in place. Its enclosing BEGIN IMMEDIATE
        # makes the copy, replacement, new table and marker one reversible unit.
        schema = inspect(connection)
        triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='organizations'")).first()
        inbound_keys = any(key.get('referred_table') == 'organizations'
                           for table in schema.get_table_names() for key in schema.get_foreign_keys(table))
        if schema.get_indexes('organizations') or triggers or inbound_keys:
            raise MigrationError('Unsupported organization schema extensions; preserve and reconcile them before migration')
        replacement = _organization_definition('organizations_v0004', allow_real=True)
        replacement.create(connection, checkfirst=False)
        columns = list(_ORGANIZATION_V2.c.keys())
        connection.execute(replacement.insert().from_select(
            columns, select(*[_ORGANIZATION_V2.c[name] for name in columns])))
        connection.exec_driver_sql('DROP TABLE organizations')
        connection.exec_driver_sql('ALTER TABLE organizations_v0004 RENAME TO organizations')
    else:
        connection.exec_driver_sql('ALTER TABLE organizations DROP CONSTRAINT ck_organization_data_policy')
        connection.exec_driver_sql("ALTER TABLE organizations ADD CONSTRAINT ck_organization_data_policy "
                                   "CHECK (data_policy IN ('synthetic_only', 'unconfigured', 'real_only'))")
    for name in SOURCE_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _job_heartbeat_schema(connection):
    # Existing runs keep a null heartbeat; no worker activity is invented.
    connection.exec_driver_sql('ALTER TABLE jobs ADD COLUMN heartbeat_at FLOAT')


def _stock_journal_schema(connection):
    # Foundation only: existing snapshots, calculations and approvals stay intact.
    # An operator must explicitly open a ledger from evidenced stock later.
    for name in STOCK_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _dated_recipes_schema(connection):
    # An imported label is not an operator's dated activation decision.
    for name in RECIPE_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _stock_count_anchor_schema(connection):
    # An anchor is an explicit operator decision, not an inferred correction.
    for name in COUNT_ANCHOR_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _production_plan_schema(connection):
    # No forecast is implicitly accepted as a cooking decision.
    for name in PRODUCTION_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _branch_profile_schema(connection):
    # A city is chosen by an administrator or at registration, never inferred from names.
    for name in PROFILE_TABLE_NAMES:
        Base.metadata.tables[name].create(connection, checkfirst=False)


def _day_closure_schema(connection):
    # A day is closed only by an explicit person; existing sales stay as imported.
    for name in CLOSURE_TABLE_NAMES:
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
            for version, operation in zip(VERSIONS, (_initial_schema, _tenant_schema, _import_schema, _real_source_schema, _job_heartbeat_schema, _stock_journal_schema, _dated_recipes_schema, _stock_count_anchor_schema, _production_plan_schema, _branch_profile_schema, _day_closure_schema)):
                if version not in applied:
                    operation(connection)
                    connection.execute(text('INSERT INTO schema_migrations (version) VALUES (:version)'), {'version': version})
                    completed.append(version)
            connection.commit()
            return tuple(completed)
        except Exception:
            connection.rollback()
            raise
