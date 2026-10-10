-- Current SQLAlchemy schema after migrations 0001 + 0002 + 0003 + 0004 + 0005 + 0006. No external source schema was supplied.
-- Use database/migrate.py to upgrade existing data and backfill tenant metadata transactionally.


CREATE TABLE audit_events (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	branch_id VARCHAR(64), 
	actor_id VARCHAR(64) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	entity_id VARCHAR(64) NOT NULL, 
	details JSON NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_audit_events_organization_id ON audit_events (organization_id);


CREATE TABLE auth_sessions (
	id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	csrf_token VARCHAR(128) NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	family_id VARCHAR(64), 
	expires_at FLOAT NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (token_hash)
)

;

CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);

CREATE INDEX ix_auth_sessions_family_id ON auth_sessions (family_id);


CREATE TABLE forecasts (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	branch_id VARCHAR(64) NOT NULL, 
	result JSON NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_forecasts_organization_id ON forecasts (organization_id);


CREATE TABLE idempotency_keys (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	actor_id VARCHAR(64) NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	payload_hash VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_idempotency UNIQUE (organization_id, actor_id, key)
)

;


CREATE TABLE import_batches (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	actor_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	rows JSON NOT NULL, 
	errors JSON NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_import_batches_organization_id ON import_batches (organization_id);


CREATE TABLE jobs (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	branch_id VARCHAR(64) NOT NULL, 
	actor_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	payload JSON NOT NULL, 
	snapshot JSON NOT NULL, 
	result_id VARCHAR(64), 
	error TEXT, 
	created_at VARCHAR(64) NOT NULL, 
	started_at FLOAT, 
	heartbeat_at FLOAT,
	finished_at VARCHAR(64), 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_jobs_status ON jobs (status);

CREATE INDEX ix_jobs_organization_id ON jobs (organization_id);


CREATE TABLE login_attempts (
	id VARCHAR(64) NOT NULL, 
	identity VARCHAR(255) NOT NULL, 
	timestamp FLOAT NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_login_attempts_timestamp ON login_attempts (timestamp);

CREATE INDEX ix_login_attempts_identity ON login_attempts (identity);


CREATE TABLE operational_records (
	id SERIAL NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	natural_key VARCHAR(255) NOT NULL, 
	branch_id VARCHAR(64), 
	data JSON NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_record_natural_key UNIQUE (organization_id, kind, natural_key)
)

;

CREATE INDEX ix_record_scope ON operational_records (organization_id, kind, branch_id);

CREATE INDEX ix_operational_records_organization_id ON operational_records (organization_id);


CREATE TABLE plans (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	branch_id VARCHAR(64) NOT NULL, 
	forecast_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	result JSON NOT NULL, 
	created_at VARCHAR(64) NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_plans_organization_id ON plans (organization_id);


CREATE TABLE refresh_tokens (
	token_hash VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	family_id VARCHAR(64) NOT NULL, 
	expires_at FLOAT NOT NULL, 
	used BOOLEAN NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	PRIMARY KEY (token_hash)
)

;

CREATE INDEX ix_refresh_tokens_family_id ON refresh_tokens (family_id);


CREATE TABLE users (
	id VARCHAR(64) NOT NULL, 
	organization_id VARCHAR(64) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash TEXT NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	branch_ids JSON NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
)

;

CREATE INDEX ix_users_organization_id ON users (organization_id);

-- Added by migration 0002; migration 0001 retains its original table list.
CREATE TABLE organizations (
    id VARCHAR(64) NOT NULL,
    name VARCHAR(200),
    timezone VARCHAR(64),
    currency VARCHAR(3) DEFAULT 'KZT' NOT NULL,
    status VARCHAR(16) DEFAULT 'active' NOT NULL,
    data_policy VARCHAR(32) DEFAULT 'unconfigured' NOT NULL,
    provenance VARCHAR(32) NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_organization_status CHECK (status IN ('active', 'suspended')),
    CONSTRAINT ck_organization_data_policy CHECK (data_policy IN ('synthetic_only', 'unconfigured', 'real_only'))
);

-- Added by migration 0003. No legacy source evidence or revisions are invented.
CREATE TABLE import_evidence (
    batch_id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    contract_version VARCHAR(32) DEFAULT 'app-import-v1' NOT NULL,
    source JSON NOT NULL,
    received_text_sha256 VARCHAR(64),
    canonical_rows_sha256 VARCHAR(64),
    summary JSON NOT NULL,
    expected_state JSON NOT NULL,
    mode VARCHAR(16) DEFAULT 'append' NOT NULL,
    reason TEXT,
    corrects_batch_id VARCHAR(64),
    committed_at VARCHAR(64),
    receipt JSON,
    PRIMARY KEY (batch_id),
    CONSTRAINT ck_import_evidence_mode CHECK (mode IN ('append', 'correction'))
);
CREATE INDEX ix_import_evidence_organization_id ON import_evidence (organization_id);

CREATE TABLE record_revisions (
    id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    kind VARCHAR(32) NOT NULL,
    natural_key VARCHAR(255) NOT NULL,
    branch_id VARCHAR(64),
    revision INTEGER NOT NULL,
    record_id INTEGER,
    before_data JSON,
    after_data JSON NOT NULL,
    before_sha256 VARCHAR(64),
    after_sha256 VARCHAR(64) NOT NULL,
    batch_id VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    reason TEXT,
    recorded_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_record_revision_positive CHECK (revision >= 1),
    CONSTRAINT uq_record_revision UNIQUE (organization_id, kind, natural_key, revision)
);
CREATE INDEX ix_record_revision_scope ON record_revisions (organization_id, kind, branch_id);
CREATE INDEX ix_record_revision_batch ON record_revisions (organization_id, batch_id);

CREATE TABLE import_receipts (
    id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    key VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    batch_id VARCHAR(64) NOT NULL,
    response JSON NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_import_receipt_key UNIQUE (organization_id, actor_id, key)
);

-- Added by migration 0004. Sources are explicitly registered; none are backfilled.
CREATE TABLE organization_sources (
    organization_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    mapping_version VARCHAR(64) NOT NULL,
    branch_id VARCHAR(64) NOT NULL,
    authorization_reference VARCHAR(128) NOT NULL,
    purpose VARCHAR(32) NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (organization_id),
    CONSTRAINT ck_organization_source_purpose CHECK (purpose IN ('pilot', 'test_fixture')),
    CONSTRAINT ck_organization_source_version CHECK (version >= 1)
);

-- Added by migration 0006. Empty journal foundation; no stock or movements are invented.

CREATE TABLE stock_ledgers (
    id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    branch_id VARCHAR(64) NOT NULL,
    baseline_date VARCHAR(10) NOT NULL,
    baseline_rows JSON NOT NULL,
    baseline_lineage JSON NOT NULL,
    data_context JSON NOT NULL,
    version INTEGER DEFAULT '1' NOT NULL,
    created_by VARCHAR(64) NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_stock_ledger_version CHECK (version >= 1),
    CONSTRAINT uq_stock_ledger_scope UNIQUE (organization_id, branch_id)
);

CREATE TABLE stock_movements (
    id VARCHAR(64) NOT NULL,
    ledger_id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    branch_id VARCHAR(64) NOT NULL,
    sequence INTEGER NOT NULL,
    kind VARCHAR(32) NOT NULL,
    business_date VARCHAR(10) NOT NULL,
    reason TEXT NOT NULL,
    source_reference VARCHAR(128) NOT NULL,
    entries JSON NOT NULL,
    recipe_evidence JSON,
    reverses_id VARCHAR(64),
    actor_id VARCHAR(64) NOT NULL,
    recorded_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_stock_movement_sequence CHECK (sequence >= 1),
    CONSTRAINT ck_stock_movement_kind CHECK (kind IN ('receipt', 'recipe_usage', 'waste', 'adjustment', 'reversal')),
    CONSTRAINT uq_stock_movement_sequence UNIQUE (ledger_id, sequence),
    CONSTRAINT uq_stock_movement_source UNIQUE (ledger_id, source_reference),
    CONSTRAINT uq_stock_movement_reversal UNIQUE (ledger_id, reverses_id),
    FOREIGN KEY(ledger_id) REFERENCES stock_ledgers (id)
);
CREATE INDEX ix_stock_movement_scope ON stock_movements (organization_id, branch_id, business_date);

CREATE TABLE stock_command_receipts (
    id VARCHAR(64) NOT NULL,
    organization_id VARCHAR(64) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    key VARCHAR(128) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    ledger_id VARCHAR(64) NOT NULL,
    response JSON NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_stock_command_receipt_key UNIQUE (organization_id, actor_id, key)
);
CREATE INDEX ix_stock_command_receipt_ledger ON stock_command_receipts (organization_id, ledger_id);
