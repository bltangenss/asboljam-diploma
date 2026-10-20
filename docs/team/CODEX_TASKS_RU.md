# Задачи для Codex на спринт к Idea Battle

Пять задач с кодом (E — продолжение задачи B, пока ждём слияния). Их можно запустить в Codex параллельно: каждая трогает только свои файлы и заканчивается своим Pull Request. Общий план команды — [SPRINT_BATTLE_RU.md](SPRINT_BATTLE_RU.md).

| Задача | Кто запускает | Ветка / PR | Срок |
|---|---|---|---|
| A. Стабилизация этапа 2 | Карабек Дамир | `team/damir-stage2` | T+1:45 |
| B. Демо-стенд, сценарий показа, видео с закрытием дня | Жорабек Бекзат | `team/bekzat-demo` | T+1:45 |
| C. Тексты KK/RU на четырёх экранах | Болат Танирберген | `team/bolat-copy` | T+1:30 |
| D. Питч: веб-презентация, скриншоты продукта, PDF | Сарсенбаева Айдана | `team/aidana-pitch` | T+1:45 |
| E. Проверка и «разогрев» стенда перед показом (локальный и облачный) | Жорабек Бекзат | `team/bekzat-stand-check` | 45 минут |

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

## Задача D — питч-презентация как веб-слайды, скриншоты продукта и PDF (для Codex)

```text
Repository: bltangenss/asboljam-diploma (Predas, formerly AsBoljam). Read AGENTS.md first and
follow it. Work on branch team/aidana-pitch created from the latest main. Time box: about
90 minutes, then a Pull Request to main. This is a code task: build the pitch deck for a
startup Idea Battle as a self-contained HTML presentation, capture real product screenshots
automatically, and export a PDF.

Files you may create or change (nothing else — other people own the rest):
- docs/pitch/** (new folder)
- scripts/capture_pitch_screens.mjs (new)
- scripts/export_pitch_pdf.mjs (new)

Deliverables:
1. docs/pitch/deck/index.html — one self-contained file (inline CSS and JS, no CDN, works
   offline when opened from disk): 9–10 slides, 16:9, arrow keys / space / click to navigate,
   slide counter, F for fullscreen, S toggles speaker notes. Brand Predas: white background,
   warm greys, one orange accent #FF5A1F, text #1C1917, font Onest. Copy the Onest variable
   woff2 files (latin, latin-ext, cyrillic, cyrillic-ext) from
   node_modules/@fontsource-variable/onest/files/ into docs/pitch/deck/fonts/ together with
   its LICENSE (SIL OFL 1.1) and use them via @font-face. Logo: inline the SVG from
   apps/web/public/favicon.svg next to the word «predas». Russian text; Kazakh letters must
   render correctly.
2. Slides (facts only from the repository, see the list below; never invent customers,
   revenue, savings, accuracy or pilots; market numbers only with a source link in the
   speaker notes, otherwise leave them out):
   1) Title: Predas — «Знайте завтрашний спрос сегодня»; прогноз продаж и закупок для
      столовых, кафе и ресторанов Казахстана.
   2) Problem: every day a canteen or cafe guesses how much to cook and what to buy →
      leftovers and write-offs or dishes run out; purchases by eye.
   3) Solution: forecast of portions per dish for tomorrow → ingredients → supplier packs
      within budget → a person approves.
   4) How it works in 3 steps: data (sales, menu, recipes, stock; demo data in one click) →
      forecast → purchase and decision; plus «закрыть день с телефона».
   5) Product screens: 3–4 screenshots from docs/pitch/assets (see deliverable 3).
   6) Why Kazakhstan: 20 day factors — RK holidays and transfers, Nauryz, Ramadan and iftar
      time, aits, school holidays, sunset, internet weather for 31 cities; KK/RU interface.
   7) Competitors and difference: accounting/POS systems iiko, r_keeper, Poster; foreign
      forecasting tools Winnow, Tenzo, 5-Out. Our difference: local calendar and languages,
      forecast → purchase → human decision in one place.
   8) Business model (mark it as «гипотеза»): subscription per branch; free test mode with
      demo data.
   9) Roadmap (from docs/PRODUCT_IDEAS_RU.md): close a shift via Telegram, Poster/iiko sales
      import, forecast vs actual, write-offs and supplier prices.
   10) Team and ask: Болат Танирберген — лидер, разработка, спикер; Карабек Дамир —
      разработка (сверка прогноза с фактом); Жорабек Бекзат — разработка, демо и видео;
      Сарсенбаева Айдана — продукт и питч. Ask: pilot establishments, mentorship,
      and if relevant funding. Footer: «Данные в демо — синтетические».
   Every slide gets speaker notes (2–4 sentences); total speech about 3 minutes.
3. scripts/capture_pitch_screens.mjs — Playwright script against a running local stand
   (--url default http://localhost:3000, --lang ru). It registers a test cafe (email
   pitch-<random>@example.invalid, random password, city Almaty, type cafe), loads demo data
   («Загрузить демо-данные»), computes the forecast for 01.01.2026, and saves 1440×900 PNG
   screenshots to docs/pitch/assets/: login.png, today.png, forecast.png, day-close.png (open
   «Закрыть день», mark «Да, работало» — do not close), purchase.png, profile.png. It must
   never print or save the password, never touch data/asboljam-kz.sqlite, and should be run
   on a fresh database only. Use Chrome if available (channel 'chrome'), otherwise bundled
   Chromium. The UI labels it needs: «Регистрация», «Название заведения», «Тип заведения»,
   «Город», «Электронная почта», password field #register-password, «Повторите пароль»,
   consent checkbox .register-consent input, «Открыть кабинет», «Загрузить демо-данные»,
   header buttons «Прогноз», «Закупки», account menu .user-menu-trigger → «Профиль».
4. scripts/export_pitch_pdf.mjs — opens docs/pitch/deck/index.html with Playwright and
   writes docs/pitch/predas-pitch.pdf (one slide per page, 16:9, notes hidden).
5. docs/pitch/speech_ru.md (3-minute speech with marks where to switch to the live demo),
   docs/pitch/qa_ru.md (10 likely jury questions with short honest answers: how accuracy is
   checked, where data comes from, what already works and what does not, competitors,
   monetization), docs/pitch/README.md (how to open the deck, regenerate screenshots and PDF).

Verified product facts you may use:
- Forecast of how many portions of each dish will sell tomorrow; 4 models (same day last
  week, 28-day mean, gradient boosting on history, gradient boosting with 20 day factors);
  p10–p90 is a nominal 80% interval, not a guarantee.
- Day factors: RK holidays and transfers, pre-holiday days, Nauryz, Ramadan and iftar time,
  Oraza and Kurban ait, school holidays, sunset, weather forecasts from the internet
  (Open-Meteo) for 31 cities of Kazakhstan, paydays, opening days, price, promotions,
  stockouts.
- Purchase: portions → ingredients (yield) → supplier packs with minimum/maximum orders,
  budget and expiry of stock; shortages are shown; a person approves; approval never sends an
  order to a supplier automatically. Audit of decisions, CSV export.
- Stock with expiry dates, printable cooking plan for the kitchen, close the day from a phone
  (empty means unknown, zero is a confirmed zero), registration of an establishment with demo
  data in one click, Kazakh and Russian interface, roles (admin, manager, warehouse,
  analyst), each establishment has its own cabinet.
- All demo data are SYNTHETIC; no measured savings on a real establishment exist yet.

Checks:
- Open the deck locally and check every slide at 1920×1080 and 1366×768 (no overflow, no
  missing glyphs). Run node scripts/capture_pitch_screens.mjs on a fresh local database and
  node scripts/export_pitch_pdf.mjs; confirm 6 PNG files and the PDF exist and look right.
- Keep committed assets small (PNG screenshots under ~400 KB each; PDF under ~10 MB).
- Before each commit: git diff --cached --stat; python scripts/check_secrets.py --staged;
  git checkout -- artifacts/security-scan.json. Never commit .env, *.sqlite, .cache/,
  passwords, videos, node_modules/, .claude/. No force push.

Open a PR to main titled "Pitch: Predas web deck, product screenshots and PDF". In the
description (Russian is fine): what was built, how to open and present it, which checks were
run, and anything not verified.
```

## Задача E — проверка и «разогрев» стенда перед показом (для Codex)

```text
Repository: bltangenss/asboljam-diploma (Predas, formerly AsBoljam). Read AGENTS.md first and
follow it strictly. Work on branch team/bekzat-stand-check created from the latest main. Time
box: about 45 minutes, then a Pull Request to main. Your PR #2 (team/bekzat-demo) is reviewed
and waits for merge: do not change that branch.

Goal: one command that tells us, minutes before the pitch, whether a stand really works, and
wakes up the free Render service (it sleeps after 15 minutes; the first request takes 30–60 s).
The same command must work on the local stand now and on the cloud stand later:
Cloudflare Pages https://<project>.pages.dev → /api/* proxied to Render → Supabase
(see render.yaml, apps/web/public/_worker.js, docs/commercial/DEPLOYMENT_CLOUD_RU.md).

Files you may create (nothing else — other people own the rest):
- scripts/check_stand.mjs (new)
- docs/STAND_CHECK_RU.md (new)

scripts/check_stand.mjs:
  node scripts/check_stand.mjs --url <origin> [--lang ru|kk] [--full]
1. Accept only an origin: https://host, or http:// only for localhost/127.0.0.1; no path,
   query, credentials. Default --url http://localhost:3000.
2. Quick mode (default, creates nothing):
   - warm-up: GET /api/v1/health, retry every 5 s for up to 120 s; print the time to the
     first 200;
   - GET / returns HTML with the app root; print whether X-Frame-Options: DENY and
     X-Content-Type-Options: nosniff are present;
   - GET /api/v1/registration: print whether self-registration is enabled;
   - a POST to /api/v1/demo-data without a session must be refused (401/403) — print the code.
3. --full mode (creates one SYNTHETIC test cabinet on the target):
   Playwright (channel 'chrome' if available, otherwise bundled Chromium), 1440×900. Register
   a cafe with email stand-check-<random>@example.invalid, a random password and city Almaty,
   load demo data («Загрузить демо-данные»), compute a forecast, open «Закупки», open
   «Закрыть день» and mark «Да, работало» but do NOT close the day, open «Профиль». Reuse the
   label constants from scripts/record_demo_video.mjs by copying them; do not edit that file.
   Print the time of every step.
4. Output: one line per step («OK 12.3 s warm-up» / «FAIL forecast: <short reason>») and a
   final line «STAND OK» or «STAND FAILED at <step>»; exit code 0 / 1. On failure in --full,
   save one screenshot with masked email/password inputs to .cache/stand-check/.
5. Never print, save or pass on the command line: passwords, cookies, CSRF tokens, session
   data or full connection strings. It is an HTTP client only: never open data/*.sqlite and
   never set DATABASE_URL.
6. Warn in --help and in the doc: every --full run creates a test cabinet, and registration
   is limited to 5 per hour per address (behind the Render proxy this limit is shared by
   everyone), so run --full at most once before the pitch; quick mode can run any time.

docs/STAND_CHECK_RU.md (Russian, short): what the check does, commands for the local stand
and for the cloud stand, what to do when a step fails (Render sleeping → wait and repeat;
API_NOT_CONFIGURED → API_ORIGIN in Cloudflare; ORIGIN_FORBIDDEN → ALLOWED_ORIGINS in Render),
and a 5-minute pre-pitch checklist: quick check → open the site → live demo tab ready →
backup video open.

Checks:
- Start a local stand on a fresh isolated database (DATABASE_URL to a new SQLite file under
  .cache, never data/asboljam-kz.sqlite), then run quick mode and --full against
  http://localhost:3000; both must print STAND OK. Stop the stand.
- Quick mode against a URL that is not running must end with STAND FAILED at warm-up after
  the retry window (use --timeout to shorten it in this check if you add such a flag).
- npm run build. Before each commit: git diff --cached --stat; python scripts/check_secrets.py
  --staged; git checkout -- artifacts/security-scan.json. Never commit .env, *.sqlite, .cache/,
  videos, node_modules/, .claude/. No force push.

Open a PR to main titled "Stand check: warm-up and click-path check for local and cloud
stands". In the description: the commands, the real output of both local runs, and what was
not verified (the cloud stand is not deployed yet).

After Bolat writes «main слит» (texts, stage 2 and your PR #2 merged): git switch main;
git pull --ff-only; start a fresh isolated stand, run scripts/prepare_battle_demo.mjs and
re-record the 3-minute RU video with scripts/record_demo_video.mjs (the screen texts changed).
Send the videos to Bolat outside Git. Report bugs: stage 2 → Damir, everything else → Bolat.
```
