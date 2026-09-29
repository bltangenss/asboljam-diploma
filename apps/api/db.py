"""Persistent SQLAlchemy store shared by API and a separate worker process."""
import os
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Boolean, CheckConstraint, Float, Index, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
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
        CheckConstraint("data_policy IN ('synthetic_only', 'unconfigured')", name='ck_organization_data_policy'),
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
