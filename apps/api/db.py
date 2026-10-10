"""Persistent SQLAlchemy store shared by API and a separate worker process."""
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
def now():
    return datetime.now(timezone.utc).isoformat()
class Base(DeclarativeBase):
    pass
class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default='KZT', server_default='KZT')
    status: Mapped[str] = mapped_column(String(16), default='active', server_default='active')
    data_policy: Mapped[str] = mapped_column(String(32), default='unconfigured', server_default='unconfigured')
    provenance: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name='ck_organization_status'),
        CheckConstraint("data_policy IN ('synthetic_only', 'unconfigured', 'real_only')", name='ck_organization_data_policy'),
    )
class OrganizationSource(Base):
    __tablename__ = 'organization_sources'
    organization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64))
    mapping_version: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[str] = mapped_column(String(64))
    authorization_reference: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    actor_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint("purpose IN ('pilot', 'test_fixture')", name='ck_organization_source_purpose'),
        CheckConstraint('version >= 1', name='ck_organization_source_version'),
    )
class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32))
    branch_ids: Mapped[list] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default='web')
    family_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    expires_at: Mapped[float] = mapped_column(Float)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
class RefreshToken(Base):
    __tablename__ = 'refresh_tokens'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64))
    family_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    identity: Mapped[str] = mapped_column(String(255), index=True)
    timestamp: Mapped[float] = mapped_column(Float, index=True)
class Record(Base):
    __tablename__ = 'operational_records'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    natural_key: Mapped[str] = mapped_column(String(255))
    branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('organization_id', 'kind', 'natural_key', name='uq_record_natural_key'), Index('ix_record_scope', 'organization_id', 'kind', 'branch_id'))
class ImportBatch(Base):
    __tablename__ = 'import_batches'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    rows: Mapped[list] = mapped_column(JSON)
    errors: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default='preview')
    created_at: Mapped[str] = mapped_column(String(64), default=now)
class ImportEvidence(Base):
    __tablename__ = 'import_evidence'
    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    contract_version: Mapped[str] = mapped_column(String(32), default='app-import-v1', server_default='app-import-v1')
    source: Mapped[dict] = mapped_column(JSON)
    received_text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_rows_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON)
    expected_state: Mapped[dict] = mapped_column(JSON)
    mode: Mapped[str] = mapped_column(String(16), default='append', server_default='append')
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrects_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    committed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    __table_args__ = (CheckConstraint("mode IN ('append', 'correction')", name='ck_import_evidence_mode'),)
class RecordRevision(Base):
    __tablename__ = 'record_revisions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    natural_key: Mapped[str] = mapped_column(String(255))
    branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    before_data: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    after_data: Mapped[dict] = mapped_column(JSON)
    before_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha256: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint('revision >= 1', name='ck_record_revision_positive'),
        UniqueConstraint('organization_id', 'kind', 'natural_key', 'revision', name='uq_record_revision'),
        Index('ix_record_revision_scope', 'organization_id', 'kind', 'branch_id'),
        Index('ix_record_revision_batch', 'organization_id', 'batch_id'),
    )
class ImportReceipt(Base):
    __tablename__ = 'import_receipts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (UniqueConstraint('organization_id', 'actor_id', 'key', name='uq_import_receipt_key'),)
class StockLedger(Base):
    """Explicitly opened stock journal; migration never fabricates a baseline."""
    __tablename__ = 'stock_ledgers'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[str] = mapped_column(String(64))
    baseline_date: Mapped[str] = mapped_column(String(10))
    baseline_rows: Mapped[list] = mapped_column(JSON)
    baseline_lineage: Mapped[dict] = mapped_column(JSON)
    data_context: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint('version >= 1', name='ck_stock_ledger_version'),
        UniqueConstraint('organization_id', 'branch_id', name='uq_stock_ledger_scope'),
    )
class StockMovement(Base):
    __tablename__ = 'stock_movements'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey('stock_ledgers.id'))
    organization_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    business_date: Mapped[str] = mapped_column(String(10))
    reason: Mapped[str] = mapped_column(Text)
    source_reference: Mapped[str] = mapped_column(String(128))
    entries: Mapped[list] = mapped_column(JSON)
    recipe_evidence: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    reverses_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint('sequence >= 1', name='ck_stock_movement_sequence'),
        CheckConstraint("kind IN ('receipt', 'recipe_usage', 'waste', 'adjustment', 'reversal')", name='ck_stock_movement_kind'),
        UniqueConstraint('ledger_id', 'sequence', name='uq_stock_movement_sequence'),
        UniqueConstraint('ledger_id', 'source_reference', name='uq_stock_movement_source'),
        UniqueConstraint('ledger_id', 'reverses_id', name='uq_stock_movement_reversal'),
        Index('ix_stock_movement_scope', 'organization_id', 'branch_id', 'business_date'),
    )
class StockCountAnchor(Base):
    """An explicitly accepted counted opening; previous stock history is retained."""
    __tablename__ = 'stock_count_anchors'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ledger_id: Mapped[str] = mapped_column(String(64), ForeignKey('stock_ledgers.id'))
    organization_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    ledger_version: Mapped[int] = mapped_column(Integer)
    through_movement_sequence: Mapped[int] = mapped_column(Integer)
    count_date: Mapped[str] = mapped_column(String(10))
    counted_rows: Mapped[list] = mapped_column(JSON)
    count_lineage: Mapped[dict] = mapped_column(JSON)
    data_context: Mapped[dict] = mapped_column(JSON)
    differences: Mapped[list] = mapped_column(JSON)
    previous_fingerprint: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint('sequence >= 1', name='ck_stock_count_anchor_sequence'),
        CheckConstraint('ledger_version >= 2', name='ck_stock_count_anchor_version'),
        CheckConstraint('through_movement_sequence >= 0', name='ck_stock_count_anchor_watermark'),
        CheckConstraint('ledger_version = sequence + through_movement_sequence + 1', name='ck_stock_count_anchor_counters'),
        UniqueConstraint('ledger_id', 'sequence', name='uq_stock_count_anchor_sequence'),
        UniqueConstraint('ledger_id', 'ledger_version', name='uq_stock_count_anchor_version'),
        UniqueConstraint('ledger_id', 'count_date', name='uq_stock_count_anchor_date'),
        Index('ix_stock_count_anchor_scope', 'organization_id', 'branch_id', 'count_date'),
    )
class StockCommandReceipt(Base):
    __tablename__ = 'stock_command_receipts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    ledger_id: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        UniqueConstraint('organization_id', 'actor_id', 'key', name='uq_stock_command_receipt_key'),
        Index('ix_stock_command_receipt_ledger', 'organization_id', 'ledger_id'),
    )
class RecipeActivation(Base):
    """Immutable complete recipe effective from a business date in one branch."""
    __tablename__ = 'recipe_activations'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[str] = mapped_column(String(64))
    meal_id: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    recipe_version: Mapped[str] = mapped_column(String(255))
    effective_date: Mapped[str] = mapped_column(String(10))
    rows: Mapped[list] = mapped_column(JSON)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    data_context: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (
        CheckConstraint('sequence >= 1', name='ck_recipe_activation_sequence'),
        UniqueConstraint('organization_id', 'branch_id', 'meal_id', 'sequence', name='uq_recipe_activation_sequence'),
        UniqueConstraint('organization_id', 'branch_id', 'meal_id', 'effective_date', name='uq_recipe_activation_date'),
        UniqueConstraint('organization_id', 'branch_id', 'meal_id', 'recipe_version', name='uq_recipe_activation_label'),
        Index('ix_recipe_activation_scope', 'organization_id', 'branch_id', 'effective_date'),
    )
class RecipeCommandReceipt(Base):
    __tablename__ = 'recipe_command_receipts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    activation_id: Mapped[str] = mapped_column(String(64), ForeignKey('recipe_activations.id'))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    __table_args__ = (UniqueConstraint('organization_id', 'actor_id', 'key', name='uq_recipe_command_receipt_key'),)
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    branch_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    result_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    heartbeat_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
class Forecast(Base):
    __tablename__ = 'forecasts'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    branch_id: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
class Plan(Base):
    __tablename__ = 'plans'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    branch_id: Mapped[str] = mapped_column(String(64))
    forecast_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default='ready')
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
class Audit(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True)
    branch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(64), default=now)
class Idempotency(Base):
    __tablename__ = 'idempotency_keys'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint('organization_id', 'actor_id', 'key', name='uq_idempotency'),)
def make_engine(url=None):
    ROOT.joinpath('data').mkdir(exist_ok=True)
    url = url or os.environ.get('DATABASE_URL', 'sqlite:///' + (ROOT / 'data/asboljam.sqlite').as_posix())
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30} if url.startswith('sqlite') else {}, pool_pre_ping=True)
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def sqlite_config(connection, _):
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
    return engine
def sessions(engine):
    return sessionmaker(engine, expire_on_commit=False)
def migrate(engine):
    """Apply explicit migrations under a database-level transaction lock."""
    from .migrations import migrate as apply_migrations
    return apply_migrations(engine)
