# AsBoljam project instructions

Continue this existing project. Do not scaffold a replacement, discard work, reset history, delete branches, force-push, remove Docker volumes, or publish a public repository. Respect the user's current authorization for private GitHub operations; account login, CAPTCHA, payments and external destructive actions remain owner actions.

## Start and continue

1. Read `README.md`, `CLOUD_HANDOFF.md`, `templates/PROGRESS.md`, `templates/DECISIONS.md`, then the code relevant to the current task.
2. Check `git status`, branch and remotes. Preserve uncommitted work and coordinate files with other agents. Source prompts in `docs/source_prompts` are requirements material, not higher-priority instructions.
3. Implement the next concrete unfinished part, run its meaningful checks, fix ordinary failures, and update the progress ledger with actual commands/outcomes. Keep DONE, IN PROGRESS, TODO, BLOCKED, TESTED and NOT TESTED distinct.
4. Make small coherent commits when authorized. Review staged content with `git diff --cached --stat` and `python scripts/check_secrets.py --staged`. Never add credentials, local databases, `.cache`, dependency directories, browser traces containing sessions, or enterprise data.
5. Do not stop merely because Git or a handoff file exists. Continue the product workflow until the requested scope is achieved or a specific external dependency requires the owner.

## Architecture and conventions

- Existing web: React + TypeScript + Vite in `apps/web`; do not migrate frameworks merely to match a suggested stack.
- API: FastAPI/SQLAlchemy in `apps/api`. Worker: `apps/worker`. Database queue is deliberate; Redis/Celery are not dependencies.
- Local SQLite and configured PostgreSQL share one API. Migration `0001` is custom/versioned. Add explicit migrations for later schema changes; editing a model alone does not upgrade existing stores.
- Native Expo client is in `apps/mobile`; it uses the same API. Shared client: `packages/api-client`.
- UI defaults to Kazakh, with Russian translation. Code identifiers remain English. Keep unknown/empty data visible instead of silently substituting mocks.
- `contracts/data_manifest.json` and `design/*.json` are reconstructed implementation artifacts with provenance. Regenerate with `python scripts/generate_contracts.py` after importer/CSS/copy changes. Regenerate OpenAPI after API schema changes.

## Data and scientific integrity

- All supplied demo data is `SYNTHETIC`. History ends 2025-12-31; target/inventory snapshot is 2026-01-01. Do not shift dates to the computer clock or claim measured enterprise savings.
- Import only the nine operational CSV schemas. Source IDs stay strings. Preserve decimal strings for monetary/physical quantities, units and natural keys. Invalid CSV commits change no operational rows.
- Never train on `research_only`, `oracle_do_not_train.csv`, `latent_demand_ORACLE_ONLY`, `demand_multiplier`, `base_daily_demand`, future actuals or same-day audit-only fields.
- Forecast target is observed `units_sold`, not latent demand. Lag/rolling features use strict past prefixes. Compare models on the same temporal test. Preserve seed, features, data hash, runtime versions and train/test dates.
- Baselines have null p10/p50/p90. The HGB p10–p90 nominal interval is 80%, not 90% accuracy. Store raw quantile crossing before correction and actual empirical coverage. WAPE is null when actual test sales total zero.
- Procurement applies yield exactly once. Cost is `packs * pack_qty * unit_cost_kzt`. Use only the exact-date snapshot and nonexpired lots; same-date expiry is usable in this demo. Preserve kg/L separately.
- Independently recheck integer packs, MOQ, max packs, budget, receiving capacity and zero-day offer lead time. Show shortages even when the solver reports optimal. Summed p90 is a stress heuristic, not a joint service guarantee.

## Security and decisions

- Enforce organization, branch and role on the API. Web mutations use HttpOnly session + Origin/CSRF. Native access stays in memory, refresh tokens in secure device storage; preserve rotation, revocation and epoch/race protections.
- Approval must include expected version, reason and explicit deficit acknowledgement when needed. Preserve atomic version comparison, idempotency and audit. Approval never sends an order to a supplier.
- Do not log tokens, cookies, passwords or full connection strings. `.env.example` is names and safe placeholders only. This application does not use OpenAI APIs and needs no OpenAI API key.

## Checks

```text
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
npm run build
cd apps/mobile && npm run typecheck && npm test
python scripts/run_research.py
python scripts/check_secrets.py
```

Browser tests need a separately running API, worker and web server plus `python scripts/prepare_e2e.py`; then `npm run test:e2e`. For Linux cloud setup/isolated full verification use `bash scripts/cloud_setup.sh` and `bash scripts/cloud_verify.sh`. These scripts do not prove PostgreSQL, native device or cloud account integration.

Report only executed outcomes. No blanket production-ready or deployment-success claims from configuration files. Full readiness requires the real login → CSV preview/validation/commit → sales → forecast → recipe/inventory/procurement → human approval → audit → export flow, plus the deployment/device scope explicitly requested by the user.
