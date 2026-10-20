# Задачи для Codex на спринт к Idea Battle

Три независимые задачи с кодом. Их можно запустить в Codex параллельно: каждая трогает только свои файлы и заканчивается своим Pull Request. Общий план команды — [SPRINT_BATTLE_RU.md](SPRINT_BATTLE_RU.md).

| Задача | Кто запускает | Ветка / PR | Срок |
|---|---|---|---|
| A. Стабилизация этапа 2 | Карабек Дамир | `team/damir-stage2` | T+1:45 |
| B. Демо-стенд, сценарий показа, видео с закрытием дня | Жорабек Бекзат | `team/bekzat-demo` | T+1:45 |
| C. Тексты KK/RU на четырёх экранах | Болат Танирберген | `team/bolat-copy` | T+1:30 |

Как запускать:
- **Codex в облаке** (Linux): в настройках окружения выберите Python 3.13 и Node.js 24, setup-скрипт — `bash scripts/cloud_setup.sh`. Каждую задачу запускайте отдельным заданием в ветке `main`.
- **Codex CLI на своём Windows-ноутбуке:** клонировать репозиторий, `copy .env.example .env`, вписать свой `DEMO_PASSWORD`, выполнить `.\scripts\start.ps1 -Install`, затем запустить `codex` в папке проекта и вставить промпт.

---

## Задача A — стабилизация этапа 2 (для Codex)

```text
Repository: bltangenss/asboljam-diploma (Predas, formerly AsBoljam). Read AGENTS.md first and
follow it strictly. Work on branch team/damir-stage2 created from the latest main. Time box:
about 90 minutes. Goal: make the already written stage 2 code pass its tests. Do NOT add new
features.

Context:
- Stage 2 (forecast vs actual review, working cooking variant, Today tasks, forecast
  explanation) was committed in 5dbe9d4 but is unfinished. Read
  docs/commercial/WORKDAY_REVIEW_RU.md and the top entries of templates/PROGRESS.md.
- Stage 2 files: apps/api/forecast_review.py, forecast_explanation.py, workday_tasks.py,
  working_plan.py; apps/web/src/ForecastReview.tsx, ForecastExplanation.tsx, WorkdayTasks.tsx,
  WorkingPlan.tsx, workdayData.ts, forecast-review.css; their tests in tests/ and
  tests/e2e/workday_review.spec.ts; migration 0012 in apps/api/migrations.py.

Environment:
- Cloud: bash scripts/cloud_setup.sh, then verification commands below.
- Before importing apps.api.main (tests, OpenAPI) always set DATABASE_URL to a fresh temporary
  SQLite file. Never use data/asboljam-kz.sqlite.

Steps:
1. Run focused Python tests with an isolated database:
   PYTHONPATH="tests:." python -X utf8 -m unittest test_working_plan test_day_close
   test_workday_migration test_forecast_review test_workday_tasks test_forecast_explanation -v
   (on Windows use PYTHONPATH="tests;."). Fix real failures.
2. Browser: start API, worker and web against a fresh database (see README «Проверки» and
   scripts/cloud_verify.sh), run python scripts/prepare_e2e.py, then
   npx playwright test tests/e2e/workday_review.spec.ts.
   Two scenarios are known to fail:
   - "working selection lost reply keeps exact command through global navigation and never
     changes procurement"
   - "concurrent working selection reloads version and requires a new explicit decision"
   Find the root cause from the trace/error context. Fix the product code. Change a test only
   when its expectation is provably wrong, and explain why in the PR.
3. Then run: npx playwright test tests/e2e/day_close.spec.ts tests/e2e/today_workflow.spec.ts
   tests/e2e/production_planning.spec.ts tests/e2e/predas_shell.spec.ts; npm run build;
   full Python suite: python -X utf8 -m unittest discover -s tests -p "test_*.py".
4. If API schemas changed, regenerate contracts/openapi.json from create_app().openapi() with
   an isolated DATABASE_URL (json.dumps(spec, ensure_ascii=False, indent=2) + "\n"). If UI
   text or CSS changed, run python scripts/generate_contracts.py and keep generated JSON with
   LF line endings.

Rules:
- Touch only stage 2 files and their tests; in apps/web/src/Dashboard.tsx only the stage 2
  widget lines. Do not touch DayClose.tsx, GetStarted.tsx, Profile.tsx, Register.tsx,
  predas.css or scripts/* (other people own them).
- Empty values stay unknown (never coerce null to 0). Data is SYNTHETIC. Keep org/branch/role
  checks, Origin/CSRF, idempotency, expected versions and audit.
- Before each commit: git diff --cached --stat; python scripts/check_secrets.py --staged;
  git checkout -- artifacts/security-scan.json. Never commit .env, *.sqlite, backups/,
  .cache/, node_modules/, .claude/. No force push, no reset --hard.
- Small commits. Open a PR to main titled "Stage 2: fix workday review browser failures".

PR description (Russian is fine): root cause of each failure, what changed, exact commands with
pass/fail counts, what was NOT run.
```

## Задача B — демо-стенд, сценарий показа и видео (для Codex)

```text
Repository: bltangenss/asboljam-diploma (Predas, formerly AsBoljam). Read AGENTS.md first and
follow it strictly. Work on branch team/bekzat-demo created from the latest main. Time box:
about 90 minutes. Goal: a reliable 3-minute live demo for a startup pitch, plus a backup video.

Context:
- Web app at http://localhost:3000 (React/Vite), API at :8000, separate worker. Local start:
  scripts/start.ps1 (Windows) or scripts/start.sh; cloud: bash scripts/cloud_setup.sh.
- Existing reference: scripts/record_demo_video.mjs drives the UI with Playwright: register a
  cafe → load demo data → forecast → stock → purchase → approve → profile, with on-screen
  captions and a visible cursor, writes WebM.
- Product flows to use (real UI labels, RU / KK): «Регистрация» / «Тіркелу»;
  «Загрузить демо-данные» / «Демо-деректерді жүктеу»; Today button «Закрыть день» /
  «Күнді жабу»; on the day-close page «Да, работало» / «Иә, жұмыс істеді», quick buttons
  «Все блюда были в меню», «Ничего не закончилось», «Акций не было», «Цены по меню»,
  per dish inputs labelled «Продано, порций» and «Было готово, порций», then
  «Проверить» / «Тексеру» and «Закрыть день» / «Күнді жабу» inside the review card.
  Demo business date is the fixed scenario day 01.01.2026 (SYNTHETIC data).

Deliverables:
1. scripts/prepare_battle_demo.mjs — Playwright script against a running local stand
   (--url, default http://localhost:3000; --lang ru|kk). It registers «Кафе «Достар»»
   (city Almaty, type cafe, email demo-<random>@example.invalid, random password), loads demo
   data, runs the forecast for 01.01.2026, closes the day 01.01.2026 with plausible test
   numbers (sold ≤ available for every dish), computes the purchase. It prints the login and
   writes it ONLY to .cache/battle-demo-login.json (ignored by git). It must never touch
   data/asboljam-kz.sqlite; document that it is meant for a disposable demo copy.
2. scripts/record_demo_video.mjs — add a «close the day» segment after the forecast step
   (Today → «Закрыть день» → worked → quick buttons → fill portions → review → close), with a
   caption in both languages, and, if the stage 2 forecast-vs-actual card is present on Today,
   a short segment showing it (skip gracefully if absent). Use Chrome when available
   (channel: 'chrome'), otherwise fall back to the bundled Chromium so it also runs in Linux.
   Keep the existing failure handling (screenshot on error).
3. docs/BATTLE_DEMO_RU.md — exact 3-minute click path for the live demo (login → Today →
   forecast → close day → forecast vs actual if available → purchase → approve → profile),
   one sentence for the speaker per step, how to prepare the stand with
   prepare_battle_demo.mjs, and a fallback plan (video, screenshots). State clearly that the
   data are SYNTHETIC training data, not a real establishment.
4. Optional CSS fixes ONLY in apps/web/src/predas.css for layout bugs you find on 1440 px and
   390 px widths while running the flow.

Checks:
- Run both scripts against a fresh local database (never the working DB) and confirm they
  finish: node scripts/prepare_battle_demo.mjs --lang ru; node scripts/record_demo_video.mjs
  --lang ru (needs: npx playwright install ffmpeg). Do not commit the produced video or login.
- npm run build; npx playwright test tests/e2e/predas_shell.spec.ts tests/e2e/day_close.spec.ts.
- If predas.css changed: python scripts/generate_contracts.py, keep generated JSON with LF.

Rules:
- Touch only scripts/prepare_battle_demo.mjs, scripts/record_demo_video.mjs,
  docs/BATTLE_DEMO_RU.md and apps/web/src/predas.css. Report logic or text bugs in the PR
  instead of fixing them in other people's files.
- Before each commit: git diff --cached --stat; python scripts/check_secrets.py --staged;
  git checkout -- artifacts/security-scan.json. Never commit .env, *.sqlite, .cache/, videos,
  logins, node_modules/, .claude/. No force push.
- Open a PR to main titled "Demo: battle stand script, click path and video with day close".

PR description (Russian is fine): what each script does, how long each run took, exact checks
with results, bugs found but not fixed.
```

## Задача C — тексты KK/RU на четырёх экранах (для Codex)

```text
Repository: bltangenss/asboljam-diploma (Predas, formerly AsBoljam). Read AGENTS.md first.
Work on branch team/bolat-copy from the latest main. Time box: about 60 minutes.

Goal: make the Kazakh and Russian interface texts of four screens natural, short and free of
typos and jargon, without changing behaviour.

Files you may change (strings only): apps/web/src/DayClose.tsx, apps/web/src/GetStarted.tsx,
apps/web/src/Profile.tsx, apps/web/src/Register.tsx. Texts are written inline as
copy('kk text','ru text') or similar pairs; Kazakh is the default language.

Rules:
- Do not change logic, props, class names, routes, API calls or data handling.
- The UI must stay honest: keep the meaning of SYNTHETIC / test mode notes, «empty means
  unknown, zero is a confirmed zero», and that approval never sends an order.
- Browser tests depend on some labels. If you change a label used in
  tests/e2e/day_close.spec.ts, tests/e2e/predas_shell.spec.ts or
  tests/e2e/registration_places.spec.ts, update that test accordingly.
- Prefer plain words over technical terms (no «SYNTHETIC», «idempotency» etc. in visible text
  unless it is a required data-mode label).

Checks: npm run build; python scripts/generate_contracts.py (keep generated JSON with LF);
npx playwright test tests/e2e/day_close.spec.ts tests/e2e/predas_shell.spec.ts
tests/e2e/registration_places.spec.ts (servers on a fresh database, see README «Проверки»).
Before each commit: python scripts/check_secrets.py --staged; git checkout --
artifacts/security-scan.json. No force push.

Open a PR to main titled "Copy: polish KK/RU texts on registration, start, profile and day
close". In the description list each change as «было → стало» and the check results.
```
