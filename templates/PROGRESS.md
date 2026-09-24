# AsBoljam — progress ledger

Updated: 2026-09-24. This ledger records executed checks, not inferred completion.

| Area | Actual status | Evidence |
|---|---|---|
| Source-file audit | Read and compared all supplied formats; duplicates identified | docs/SOURCE_REVIEW_RU.md |
| Data ingest | Nine explicitly allowed CSVs; generator fields removed; oracle excluded | apps/api/importing.py, scripts/seed_demo.py |
| Persistence/migration | SQLAlchemy + versioned initial migration; SQLite exercised | database/README.md, database/postgres_schema.sql |
| API/auth/approval | 16 integration tests PASS, 46.301s in final backend run | python -X utf8 -m unittest discover -s tests -p test_api.py -v |
| Forecast/procurement engine | 14 tests PASS, actual source-data calculations included | tests/test_engine.py |
| SQLite backup/restore | 4 tests PASS; live WAL, fidelity, corruption/tamper, no overwrite | tests/test_backup.py |
| Research reproduction | 9 forecasts and 36 scenarios actually computed | artifacts/research/provenance.json, artifacts/research/README_KK.md |
| Compose | Static config PASS: docker compose config --no-interpolate --quiet | docker-compose.yml |
| Docker/PostgreSQL runtime | NOT VERIFIED: Docker Desktop Linux daemon named pipe unavailable | docker info failed to connect |
| Windows launcher | PowerShell parser accepted start.ps1/stop.ps1; full launcher not executed during active manual-server work | scripts/start.ps1, scripts/stop.ps1 |
| Linux/macOS launcher | Git Bash -n PASS for both scripts; actual Linux/macOS launch pending | scripts/start.sh, scripts/stop.sh |
| Web build and browser workflow | Root agent is verifying; record exact outcomes before final delivery | package.json, tests, artifacts |
| Native mobile | Source implementation exists; dependency/type/unit/device checks tracked by mobile agent | apps/mobile |

API coverage includes login Origin/CSRF, roles, organization/branch restrictions on data/runs/exports, CSV atomic rejection, duplicate import, oracle exclusion, valid commit, actual queued worker forecast/procurement, approval with deficit acknowledgement, same-key replay, concurrent different-key conflict, one audit transaction, native refresh reuse revocation, logout revocation, CSV formula protection, filtered whole-scope export, recipe yield factor and OpenAPI path parity.

Executed tests used the installed Windows/Python 3.13 dependency set. Integration test temporary SQLite directories required execution outside the Windows tool sandbox because that sandbox denied their generated directory ACLs; this was an environment restriction, not a passing sandbox run.

Still requiring independent deployment verification: PostgreSQL driver/database runtime, Docker image builds/startup, HTTPS reverse proxy setup, native device builds and signed artifacts. Do not mark these complete solely because configuration/source files exist.
