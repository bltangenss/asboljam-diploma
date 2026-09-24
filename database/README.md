# Backend persistence and migration

Local demo: `python database/migrate.py`, `python scripts/seed_demo.py`, `python -m uvicorn apps.api.main:app --port 8000`, and in another terminal `python -m apps.worker.main`.

`DATABASE_URL` defaults to `sqlite:///.../data/asboljam.sqlite`. To use PostgreSQL, install `requirements.lock` and set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/asboljam` before migration, seed, API, and worker. Never commit a real connection string. `database/postgres_schema.sql` is generated from the actual ORM models. PostgreSQL runtime requires a separately available server; the development verification used SQLite.

The initial versioned migration (`0001`, recorded in `schema_migrations`) uses SQLAlchemy DDL, with one transaction. Repeated execution preserves data. There is no Alembic dependency in this implementation. Before future schema changes, add an explicit new migration and a backup/restore test; changing the model does not upgrade an existing database.

The nine operational source schemas are validated at import and persisted as typed JSON payloads with organization, kind, branch and canonical source key columns. Database uniqueness prevents duplicate source keys even under concurrent commits. References, units and ranges are checked transactionally by the importer; these JSON source references are not PostgreSQL foreign-key columns. This is a demo persistence design, not a complete stock-movement or accounting ledger.

Auth sessions contain only hashed opaque tokens. Passwords use salted scrypt. Web mutation requests need an allowed `Origin` and `X-CSRF-Token`; native requests use short-lived bearer access tokens plus one-use rotating refresh tokens. Reuse revokes the whole refresh family. `COOKIE_SECURE=true` is required behind HTTPS. Development defaults accept only `http://localhost:3000` and `http://127.0.0.1:3000`; configure `ALLOWED_ORIGINS` explicitly for deployment. No wildcard credentialed CORS is accepted.

The worker atomically claims queued rows, stores immutable input snapshots, and writes results, job state and audit together. A crashed worker's running job becomes eligible for retry after 30 minutes. The run ID is the result ID. Each run is side-effect free until persistence; workers never send supplier orders. Do not run tasks longer than the 30-minute lease without implementing worker heartbeats.

Backups: `python scripts/backup_db.py backup --database data/asboljam.sqlite --output backups/demo.sqlite`. Restore to a new path with `python scripts/backup_db.py restore --backup backups/demo.sqlite --destination data/restored.sqlite`. PostgreSQL uses `pg_dump` / `pg_restore` supplied with PostgreSQL, which must be verified in its deployment environment.

No seed runs at startup. The seed CLI accepts an optional `DEMO_PASSWORD` (minimum 12 characters) or prints one generated password exactly once. Re-running the seed preserves credentials. It allowlists nine CSV basenames; research-only oracle data and generator fields are excluded from storage and APIs.
