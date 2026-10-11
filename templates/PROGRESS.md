# AsBoljam — журнал прогресса

## 11.10.2026 — казахстанская адаптация demo: набор Кызылорды и требования запуска в РК

**DONE:** воспроизводимый SYNTHETIC-набор `data/kz` (генератор `scripts/generate_kz_demo.py`, только stdlib, seed 2025): 3 филиала Кызылорды (асхана у вокзала, кафе бизнес-центра, семейный ресторан), 12 казахских блюд, 14 ингредиентов с KK/RU названиями, цены 2025 года в тенге по уровням БНС, 5 поставщиков (один с доставкой на следующий день), официальные праздники и переносы РК 2024–2025 (`reference_rk_days_off.csv` с правовым основанием), Рамазан, климат; два просроченных лота на срезе 2026-01-01. Те же девять схем и даты. `scripts/seed_demo.py` по умолчанию загружает `kz` (`--dataset`/`DEMO_DATASET`, `raw` — исходный набор диплома); `seed()` для тестов/fixtures и `run_research.py` остаются на `data/raw`; база с уже загруженным demo сохраняет свой набор (предупреждение, без удаления). Docker-образ копирует `data/kz`; `.gitattributes` хранит байты `data/kz`; manifest получил раздел `demo_datasets`. Документы: [data/kz/README.md](../data/kz/README.md), [KAZAKHSTAN_LAUNCH_RU.md](../docs/commercial/KAZAKHSTAN_LAUNCH_RU.md) (язык, UTC+5, ст. 12 Закона № 94-V о хранении персональных данных в РК, домен `.kz`, НДС 16% с 2026, ограничение прогноза по праздникам), DEPLOYMENT_VPS §9, backlog №9–10, DECISIONS.

**TESTED:** `tests/test_kz_demo_data.py` 6/6 (9.2 с): побайтное пересоздание всех файлов, полная сетка дат без пропусков, kg/L, origin, точное совпадение флагов календаря с официальным списком, продажи = min(скрытый спрос, порции), seed → импорт всех 9 файлов → HGB-прогноз → закупка 150000 ₸ (`optimal`, 0 дефицитов, исключены просроченный лот и предложение со сроком 1 день). Связанные suites (import parser, engine, tenant CLI, security settings, package release) — 57/57. `run_research.py --data-dir data/kz`: HGB WAPE 16.94/21.43/18.94%, лучший baseline 16.99/29.18/24.73%, покрытие p10–p90 78.3/81.0/74.7% при номинальных 80%; бюджеты 75000/200000 ₸ дают ожидаемые дефициты/их отсутствие. `start.ps1` на новой SQLite загрузил `kz`; `verify_runtime.py` через web-proxy — **87/87** ([отчёт](../artifacts/verification/kz-demo-runtime-20261011.json)), HTTP 500 нет. Часовой пояс: в `tzdata 2025.3` Asia/Almaty, Qyzylorda, Qostanay, Aqtobe, Oral = +05:00 на 2026-01-01. Полная Python-регрессия: 502 случая за 248.2 с: 501 PASS + 1 POSIX skip, 0 failures/errors (новый `tests/test_check_secrets.py` — отдельно 1/1). [Свидетельство](../artifacts/verification/kz-demo-20261011.json).

**NOT TESTED:** Docker-образ с `data/kz` не пересобирался (Docker остановлен из-за памяти), seed `kz` на PostgreSQL, browser-suite на казахстанском наборе (e2e по замыслу использует `data/raw`), mobile, новый архив выпуска (v3 этого изменения не содержит). Признак праздников РК в прогнозе не реализован — ждёт решения владельца.

## 11.10.2026 — финальный архив v3 (137a17d) проверен полностью

**DONE / TESTED:** `releases/2026-10-11-final-3/AsBoljam_Final.zip` из чистого commit `137a17d`: 334 файла, 1974209 байт, SHA256 `4afdeb480d94a222e790855c93a14efc21b58f462dbe38f7ad6d74e094532bf5`; упаковщик CRC/хеши/secret scan PASS; независимо CRC, sidecar, 334/334 = manifest = дерево commit = Git-blob. Чистая установка в новую папку: venv из lockfile, `npm ci` 0 уязвимостей, миграции 0001–0008, seed; HTTP `verify_runtime.py` 87/87; полный browser-suite 89 passed + 2 skip (5.8 мин), затем складские live 1/1 и 1/1 (REAL/TEST) — итого 91/91; SQLite restore drill 14/14 (23 таблицы, 58337 операционных строк, integrity OK); `npm run build` PASS. По логам API за browser-suite: `/dashboard` p50 0.57 с, max 2.3 с; без HTTP 500. Включает диагностику неполной истории и остатков, KK/RU для всех видимых отказов, пакет развёртывания и исправление `STALE_VERSION`. Полная Python-регрессия на тех же исходниках приложения (`fcb06d2`): 495 PASS + 1 POSIX skip. [Свидетельство](../artifacts/verification/release-20261011-final-3.json).

**История попыток:** v1 `releases/2026-10-11-final` (`fc0af29`) — проверен 88/88, затем дополнен улучшениями; v2 `releases/2026-10-11-final-2` (`ae88c64`) — 87 passed, 2 failed (регрессия текста `STALE_VERSION`, исправлена в `137a17d`; HGB-задание 125.6 с при таймауте 120 с на перегруженной машине). Старые архивы сохранены.

**NOT TESTED:** production deployment на сервере (нужны решения владельца), PostgreSQL для изменений после `813dab4` (затронуты только пути ошибок без SQL-особенностей), APK текущего кода и устройство, реальный пилот. Этот commit добавляет только документы/свидетельство.

## 11.10.2026 — архив v2 (ae88c64): найдена и исправлена регрессия текста устаревшего плана

**TESTED (v2, ae88c64):** `releases/2026-10-11-final-2/AsBoljam_Final.zip` — 334 файла, SHA256 `a676d450cf8c9ad0843f04acda04d1217250cd4ddf1a254e412f69e8feda3886`, CRC/manifest/Git-blob 334/334; чистая установка: `npm ci` 0 уязвимостей, HTTP 87/87; полный browser-suite: 87 passed, **2 failed**, 2 skipped (15.7 мин, CPU 100%, ~0.3 ГБ свободной RAM); складские live 1/1 и 1/1. Падение 1 — **регрессия из `a816d1d`**: новый перевод `error_STALE_VERSION` заменил прежний текст «План обновлён. Проверьте последнюю версию.», который ожидает live-тест устаревшего утверждения; после изменения переводов я прогнал только mock-спецификации — live-проверку пропустил. Падение 2 — HGB-прогноз завершился успешно, но за 125.6 с при таймауте теста 120 с (на v1 — 10–30 с; причина — нагрузка машины).

**DONE:** `error_STALE_VERSION` возвращён к прежней формулировке. Повтор обоих тестов на настоящем API v2 с web из репозитория: 2/2 PASS (29.9 с и 19.8 с). Архив v2 содержит регрессию и не является финальным; будет новый архив.

## 11.10.2026 — понятные отказы закупки при неполном срезе остатков (REAL)

**DONE:** `INVENTORY_COVERAGE_REQUIRED` и `STALE_INVENTORY` раньше не говорили, какого ингредиента нет в срезе и на какую дату нужен срез. Теперь (правила проверки прежние) отказ содержит требуемую дату среза, даты имеющихся срезов (до 10 последних) или список ингредиентов без строки остатка с названием, единицей и блюдами, которым они нужны (до 100, плюс общее число). Страница закупки показывает это на KK/RU с подсказкой: добавить посчитанный остаток, а при реальном отсутствии — явный ноль; отсутствующая строка не считается нулём.

**TESTED:** полная Python-регрессия на `fcb06d2`: 496 тестов — 495 PASS + 1 POSIX skip, 0 failures/errors, 480.8 с. REAL API: недостающий `required-extra` назван с единицей и блюдом; новый тест `STALE_INVENTORY` — без срезов `[]`, после импорта более раннего среза `['2026-03-31']`, задание не создаётся; `test_real_api`, `test_api`, `test_ui_copy`, `test_import_lineage`, `test_stock_api` — 59/59; браузер `real_data_context` 9/9 (новый тест: оба отказа, KK→RU, без текста API, ровно 2 запроса); визуальная проверка 1440 и 390 px без горизонтальной прокрутки; web build PASS; OpenAPI без изменений; контракты UI-copy регенерированы.

## 11.10.2026 — отказы API и предупреждения на выбранном языке (KK/RU)

**DONE:** сообщения API написаны по-казахски; в web переводы были лишь у нескольких кодов, поэтому русский интерфейс для большинства отказов (импорт, даты, ключи запроса, пароль, утверждение и др.) показывал казахский текст API, а складские страницы для 34 кодов — только «операция не выполнена (КОД)». Добавлены KK/RU тексты для 77 общих кодов (`error_*` в `shared.tsx`, используются `ErrorBox`) и 34 складских (`stockCopy.ts`); таблица ошибок строк импорта и предупреждения dashboard (`INVENTORY_UNKNOWN`) берут текст по коду и выбранному языку, при отсутствии перевода остаётся прежний текст. Новый тест `tests/test_ui_copy.py` сканирует коды в исходниках API и требует для каждого видимого в web кода непустые различающиеся KK и RU тексты без казахских букв в русском; операторские/настроечные/native-коды исключены явным списком.

**TESTED:** `test_ui_copy` 2/2 (77 общих + 59 складских кодов; первый прогон выявил, что 5 складских кодов переводятся в общем словаре, — правило теста уточнено); браузер с подменой API: `real_data_context` 8/8 и `import_history` 8/8 (новые проверки KK→RU для `ORIGIN_NOT_CLOSED`, `INVENTORY_UNKNOWN`, строки импорта `INVALID_VALUE`, без исходного текста API), остальные mock-спецификации 63/63; web build PASS; контракты UI-copy регенерированы. Python-код API не менялся.

**NOT TESTED:** live-прогон браузера этих экранов на настоящем API в этом шаге; mobile использует собственные тексты.

## 11.10.2026 — понятный отказ при неполной истории продаж (REAL)

**DONE:** раньше REAL-прогноз при неполной истории отвечал общим `DATA_HISTORY_INCOMPLETE` без указания блюда и даты; ресторан со сменой меню не мог понять, что исправлять. Теперь отказ (правило допуска не изменено — решает по-прежнему `validate_forecast_history`) содержит диагностику по каждому блюду: `ready`, `too_short` (новое блюдо), `gap` (первый пропущенный день), `ended` (нет строк до выбранной даты), дни подряд до origin, период данных, название блюда. Web показывает таблицу только проблемных блюд на KK/RU с подсказкой: нулевую строку добавлять только для реально закрытого дня или дня без продаж, иначе ждать накопления истории; пропуск не превращается в ноль. Общий клиент `ApiError` сохраняет структурированные детали (`details`, необязательно, совместимо с mobile). Перевод `error_DATA_HISTORY_INCOMPLETE` добавлен: в RU-интерфейсе больше не показывается казахское сообщение API для этой ошибки. Контракты UI-copy и `data_manifest` регенерированы (`importer_sha256` отражает изменение `importing.py` из `01850dc`).

**TESTED:** `HistoryCoverageTests` 2/2 (все статусы, чужой филиал и будущие дни игнорируются, согласованность с правилом допуска); REAL API: отказ на 30.03 сообщает `too_short` 83/84 для `test-meal`; связанные suites `test_engine`, `test_real_api`, `test_real_execution`, `test_api`, `test_run_status` — 73/73; браузер `real_data_context.spec.ts` 7/7, включая новый тест KK→RU (только проблемные блюда, ID без названия, отсутствие казахского текста API в RU, без повторной отправки); web build PASS; mobile typecheck PASS, tests 13/13; OpenAPI без изменений.

**Найдено, не исправлено:** из ~90 кодов ошибок API переводы в web есть лишь для нескольких; для 403/409 есть общие формулировки, остальные отказы в RU-интерфейсе показываются на казахском. Следующий пункт backlog №5.

## 11.10.2026 — пакет развёртывания на одном сервере с HTTPS (проверен локально)

**DONE:** `infra/compose.prod.yml` (Caddy с автоматическим HTTPS для домена; API, web и PostgreSQL без опубликованных портов; ротация docker-логов 10 МБ × 5 у всех сервисов), `infra/Caddyfile` (без admin endpoint и без access log, HSTS, без `Server`), `infra/production.env.example` (только имена и заглушки), `scripts/backup_postgres.sh` (pg_dump custom, проверка `pg_restore --list`, SHA256, без перезаписи, удаление старых копий только по явному `BACKUP_RETENTION_DAYS`), `scripts/verify_tls_deployment.py`, runbook [DEPLOYMENT_VPS_RU](../docs/commercial/DEPLOYMENT_VPS_RU.md) со списком решений владельца.

**TESTED (локально, не deployment):** стек с `ASBOLJAM_ENV=production`, `localhost` и внутренним CA Caddy (`caddy:2.10.2-alpine`, digest записан): compose config валиден; API healthy после production-валидации; demo seed отклонён; `verify_tls_deployment.py` 15/15 (доверенный сертификат по корню CA, HSTS, нет `Server`, HTTP→HTTPS, readiness, `X-Request-ID`, порты 8000/3000 закрыты, чужой Origin 403, cookie Secure/HttpOnly/SameSite, вход/выход, отзыв сессии); логи без запросов Caddy, секретов и сырых URL; backup: 3 копии, `sha256sum -c` OK, неверное `BACKUP_RETENTION_DAYS` теперь отклоняется до создания копии (первая версия создавала лишнюю копию — исправлено и перепроверено), восстановление копии в новую базу с совпадающими количествами строк. [Отчёт](../artifacts/verification/deployment-config-20261011.json).

**NOT TESTED / BLOCKED:** публичный сертификат (ACME), DNS, реальный сервер, firewall, нагрузка, внешнее хранение копий, интерактивный `manage_tenant bootstrap --apply` через TTY. Для запуска нужны решения владельца (DEPLOYMENT_VPS_RU §9).

## 11.10.2026 — финальный ZIP проверен чистой установкой, браузером и восстановлением

**DONE / TESTED:** `releases/2026-10-11-final/AsBoljam_Final.zip` создан из чистого commit `fc0af29`: 323 файла, 1930862 байт, SHA256 `da5abe1b0dc6e0e5005e82b583b02302634825ee58c9e6cc4d8d36764036ee1f`. Упаковщик: CRC/хеши/secret scan PASS; независимо: CRC, sidecar SHA256, 323/323 = manifest = дерево commit, 323/323 побайтно равны Git-blob. Чистая установка в новую папку вне репозитория через `start.ps1 -Install`: venv из lockfile (anyio 4.14.2), `npm ci` — 0 уязвимостей, миграции 0001–0008, seed; `verify_runtime.py` через web-прокси 87/87. Browser: полный suite 86 PASS + 2 skip (складские live требуют отдельных баз) за 9.2 мин, затем оба складских live-сценария на новых фикстурах — 1/1 и 1/1 (REAL/TEST); итого 88/88, включая REAL/TEST workflow и три live-сценария, падавшие на RC. По JSON-логам API: `/dashboard` p50 1.5 с, max 4.3 с (на RC 7.7/22.2 с), без HTTP 500. SQLite restore drill на установке: 14/14, integrity/FK OK, 23 таблицы (58337 операционных строк) совпадают. `npm run build` PASS; mobile typecheck PASS, tests 13/13. [Свидетельство](../artifacts/verification/release-20261011-final.json).

**NOT TESTED:** production deployment (сервер, домен, TLS, нагрузка, failover), APK текущего кода и устройство, реальный пилот, POSIX SIGTERM в этом этапе. Этот commit добавляет только документы/свидетельство; архив соответствует `source_commit` из manifest.

## 11.10.2026 — PostgreSQL, Docker/Nginx и восстановление PostgreSQL на финальном коде

**DONE / TESTED:** свежие образы из `81a550b` (Python 3.13.16, anyio 4.14.2, PostgreSQL 17.11) в новом изолированном compose-проекте: `verify_runtime.py` через Nginx 87/87 PASS; после исправления производительности на PostgreSQL `/dashboard` 0.16–0.73 с, `/plans/{id}` 0.29 с. Логи Nginx/API/worker: только allowlisted поля, секретов и access-строк нет, ID прокси совпадают с API, цепочки forecast/procurement до worker прослежены. Учение по восстановлению PostgreSQL: `pg_dump` → новая база → `pg_restore --exit-on-error` → `verify_restore.py --restored-from-environment`: 13/13 проверок, совпадают количества строк ключевых таблиц, планы, CSV утверждённого плана, история расчётов, импорты, 9 CSV и audit (кроме двух записей входа самого учения — правило уточнено в `b984fa5`). PostgreSQL suites (`test_import_lineage`, `test_run_status`, `test_tenant_isolation`, `test_real_api`, `test_stock_service`, `test_request_logging`): первый прогон — 77 тестов без failures/errors/skips, но статус failed из-за учёта схем (раннер ждал схему на каждый тест, `test_request_logging` использует одну фикстуру на класс: 68 вместо 77); отчёт сохранён. Раннер исправлен (`813dab4`), повтор — PASS: 77 тестов, 68/68 фикстур, 77 тел на PostgreSQL, чистое дерево. [Сводное свидетельство](../artifacts/verification/launch-readiness-20261011.json).

**NOT TESTED:** финальный ZIP после этих коммитов, его чистая установка, полный browser-suite с REAL/складскими фикстурами и SQLite-учение по восстановлению — следующий шаг. Шаг `docker compose cp` дампа наружу не выполнялся. Production, нагрузка, mobile, пилот — без изменений.

## 11.10.2026 — anyio 4.14.2 и проверка в venv строго из lockfile

**DONE:** `requirements.lock`: `anyio` 4.11.0 → 4.14.2 (PYSEC-2026-4024/4025). Новый venv из lockfile совпадает с ним полностью (`pip freeze` = lock), `pip-audit` по lockfile: 28 пакетов, 0 уязвимостей. Тест готовности дочернего процесса больше не сравнивает `Popen.pid` с PID интерпретатора: в Windows venv `python.exe` — лаунчер, настоящий интерпретатор имеет другой PID (проверено экспериментом: 2720 ≠ 30492; в глобальном Python совпадают). Тот же эксперимент показал, что завершение лаунчера останавливает и настоящий расчёт (через 1 с процесса нет), то есть `JOB_TIMEOUT` в установке через `.venv` работает.

**TESTED:** полная регрессия в venv из lockfile: 491 тест — 489 PASS, 1 FAIL, 1 POSIX skip, 261.7 с. Единственный FAIL — `test_real_hung_child_is_terminated_and_private_files_removed`: фикстура ждала совпадения PID и через 10 с сообщала «не стартовал». После исправления проверки готовности `test_worker_process` 13/13 PASS в venv и 13/13 в глобальном Python. Mobile `npm audit` проанализирован (28; закрываются только мажорным обновлением Expo SDK/React Native, в основном инструменты сборки) — внесено в backlog, не исправлено.

**NOT TESTED:** полный повтор всей регрессии после правки теста (исправлен только тест, приложение не менялось); PostgreSQL, новый RC, browser-suite и restore-учение — следующие шаги.

## 11.10.2026 — проверка RC из ZIP: найден и исправлен медленный dashboard (IN PROGRESS, остановлено по просьбе владельца)

**DONE:** RC `releases/2026-10-11-rc/AsBoljam_Final.zip` из `347d90d`: 316 файлов, 1854657 байт, SHA256 `a7a451d894adf47882a8a000377a2d89ee25b0a451ecd5496728c55c934b4716`; упаковщик CRC/хеши PASS; независимо: CRC, sidecar SHA256, 316/316 файлов = manifest = blob'ы commit. Чистая установка в новую папку вне репозитория (`C:\Users\ASUS\AsBoljam-install-check\rc-20261011-347d90d`) через `start.ps1 -Install`: новый venv, pip из lockfile, `npm ci`, миграции 0001–0008, seed; API ready, web 200, worker работает. `verify_runtime.py` через web-прокси установленной копии: 87/87 PASS. `npm run build` установленной копии PASS.

**Найдено browser-suite установленной копии:** 80 passed, 6 failed, 2 skipped (16.0 мин). Разбор: `real_data_live` — не подготовлена фикстура `prepare_real_e2e.py` (предусловие, не дефект); `sessions_imports` analyst — строгий `getByRole('status')` ловит одновременно инфо-блок и индикатор загрузки `RecentRuns` (детерминированно, dev и production build); `tenant_onboarding:72` — в dev StrictMode стартовое чтение `/session/me` выполняется дважды (на production build тест проходит); три live `workflow.spec` — страницы не успевали за 15 с: JSON-логи API показали `/dashboard` медиана 7.7 с, максимум 22 с, `/forecasts` до 24 с, `/plans/{id}` p95 8 с. Профилирование: каждая проверка свежести заново читала ORM-объекты и канонически хешировала ~9–18 тыс. строк, dashboard делал это до 6 раз за запрос.

**DONE (исправление):** freshness lineage читает колонки вместо ORM, кэширует канонический хеш по сохранённому JSON-тексту (контент-адресно, изменение строки даёт новый текст) и делит состояние по селекторам в пределах одного запроса; dashboard использует общий кэш для планов и прогноза; `rows_for`/`workspace_context` читают только колонку `data`. Сравнение полей свежести (row_sha256, revision, batch_id, record_id, branch_id) и правила отбора не менялись. На копии БД установленной версии: dashboard 8.5 → 1.4 с (медиана), план 3.1 → 0.7 с, список прогнозов 3.9 → 0.5 с (CPU машины 90–100%, значения ориентировочные). 63/63 ответа (2 организации, все филиалы, планы, прогнозы, CSV) побайтно равны прежнему коду. E2E: локаторы `role=status` сужены до проверяемого сообщения; счётчик чтений сессии считается от стартовой базы. Lockfile: `source-map-js` 1.2.1 → 1.2.2 (GHSA-68fv-2mgg-jv7q, dev/build-only). Добавлены `scripts/verify_restore.py` (учение по восстановлению: SQLite или восстановленная оператором БД) и [INSTALL_UPDATE_BACKUP_RU](../docs/commercial/INSTALL_UPDATE_BACKUP_RU.md).

**TESTED:** `test_import_lineage` 12/12 PASS (2 теста адаптированы к контент-адресному кэшу с сохранением смысла, 1 новый тест dashboard); `sessions_imports` + `tenant_onboarding` 16/16 PASS на dev-сервере установленной копии; `npm audit` 0 после обновления lockfile.

**TESTED после commit `01850dc`:** полная Python-регрессия на тех же исходниках приложения завершилась: 491 тест — 490 PASS + 1 POSIX SIGTERM skip, 0 failures/errors, 400.2 с (на момент первого commit было выполнено 313/491).

**NOT TESTED / IN PROGRESS:** не проверены: PostgreSQL для `CAST(data AS TEXT)`/колонок; `verify_restore.py` не запускался; новый RC с исправлением, повторная установка и полный browser-suite не выполнены; `npm ci`/build с `source-map-js` 1.2.2. Не исправлено: `anyio` 4.11.0 (PYSEC-2026-4024/4025, исправление 4.14.2) в `requirements.lock`; mobile lockfile — 28 уязвимостей npm audit (1 critical `shell-quote`, в основном Metro/Jest/Expo CLI), требует обновления Expo SDK. Установленная RC-копия и её БД остаются вне Git.

**Следующие шаги:** полная регрессия; PostgreSQL suites (`test_import_lineage`, `test_real_api`, `test_stock_service`, `test_request_logging`) через `verify_postgres_security.py --report-name postgres-lineage-observability-20261011.json`; `anyio` 4.14.2 + регрессия; новый RC ZIP → установка → browser-suite (с `prepare_real_e2e.py`) → `verify_runtime.py` → `verify_restore.py`; финальный ZIP и документы.

## 11.10.2026 — диагностика request → job завершена

**DONE:** server-generated `X-Request-ID` (32 hex) на каждом ответе, включая ранние 400/413, preflight и middleware 500; входящий и выставленный маршрутом ID игнорируются. JSON `http.request` содержит только method, шаблон маршрута или `unmatched`, status, duration и фиксированный `code` (`HTTP_REQUEST_FAILED` / `HTTP_REQUEST_CANCELLED`). `job.queued` пишется только после commit с request_id; worker пишет `job.claimed`, `job.finished`, `job.discarded` (CAS loser/missing), `job.released`, `job.lease_expired`, `job.publication_error` только по фактическому исходу транзакции. Необработанное исключение до заголовков даёт один безопасный 500 с security headers и CORS для разрешённого origin; после заголовков второй ответ не отправляется. Серверу передаётся только `RuntimeError: HTTP_REQUEST_FAILED` без исходной цепочки. Порядок middleware: correlation → CORS → protection. `--no-access-log` в start.ps1/start.sh/cloud_verify.sh/Dockerfile.api, Nginx пишет JSON `proxy.request` (status, время, X-Request-ID API). Runbook: [WORKER_OPERATIONS_RU](../docs/commercial/WORKER_OPERATIONS_RU.md). Приоритетный [backlog запуска](../docs/commercial/LAUNCH_BACKLOG_RU.md) составлен.

**TESTED:** первый focused прогон 36 тестов — 35 PASS, 1 FAIL из-за ошибки в самом тесте (строка `inner-` входит в шаблон `/test/inner-header`); исправлена только проверка теста, повтор `test_request_logging` 10/10 PASS. Полная Python-регрессия 490 тестов: 489 PASS + 1 POSIX SIGTERM skip, 0 failures/errors, 346.5 s. Настоящий uvicorn с `--no-access-log`: 10/10 проверок; контроль без флага подтвердил запись сырого query в access log Uvicorn. Свежие Docker-образы из текущего дерева + PostgreSQL 17.11 + Nginx 1.30.5: `verify_runtime.py` через Nginx 87/87 PASS (login → роли/CSRF → forecast → procurement → approval → audit → export → CSV import/replay); логи Nginx/API/worker без паролей, маркеров, сырых путей и access-строк; цепочка request → job → worker прослежена. OpenAPI идентичен контракту. [Отчёт](../artifacts/verification/request-logging-20261011.json).

**NOT TESTED:** focused-тесты диагностики на PostgreSQL (код проверен на PostgreSQL через Docker HTTP workflow), POSIX SIGTERM, error log Nginx при отказе upstream, доставка/ротация/хранение логов, production TLS/нагрузка. Web/mobile/research не менялись и не перезапускались. **Следующий пункт:** backlog №2 — чистая установка из нового ZIP и проверенный backup/restore.

## 11.10.2026 — подробный README для продолжения в Claude Code

**DONE:** README расширен до 18 разделов: продукт/сценарий фастфуда, точные девять CSV, реальные признаки и обучение моделей, закупка/Decimal/yield, склад/рецепты/count anchors, роли/изоляция, архитектура/миграции0001–0008, запуск, фактические проверки, ZIP/APK, незавершённая диагностика и готовый стартовый промпт. Исторические устаревшие TODO отмечены явно. Код приложения и локальный незавершённый diff не изменялись этим обновлением документации.

**TESTED документация:** read-only сверка с кодом и JSON evidence; Python AST/path check без импорта API: 73 Markdown-ссылки,19 явных anchors,9 CSV-схем совпадают с SCHEMAS, fences сбалансированы. Проверка staged diff и secret scan перед commit. **NOT TESTED:** приложение заново не запускалось, тяжёлые suites/build/research/native не повторялись ради README. Запуск новых worker logging tests был начат в предыдущем сеансе, но его итог недоступен — PASS не подтверждён; API logging suite пока отсутствует.

**IN PROGRESS:** локальная интеграция request→job в API/worker/infra остаётся незакоммиченной; базовый emitter c9b288a уже проверен и отправлен. Следующему исполнителю: сначала git status/diff и README§15.1, затем завершение согласованного scope и его проверки. **BLOCKED внешними данными:** реальный бизнес-пилот и измеренная экономия требуют согласованного предприятия.

## 10.10.2026 — безопасный JSON-вывод диагностики

**DONE:** отдельный allowlisted emitter: только известные события/поля, допустимые server IDs/коды, конечные числа; неизвестные поля не сериализуются. Ошибка вывода не меняет результат транзакции. **TESTED:** `python -X utf8 -m unittest discover -s tests -p test_observability.py -v` —5/5 PASS,0.022s; секретные sentinels,100 конкурентных строк, закрытый/неисправный stream. [Отчёт](../artifacts/verification/observability-emitter-20261010.json). **IN PROGRESS / NOT TESTED:** интеграция HTTP/requestID и worker lifecycle, production logging/retention.

## 10.10.2026 — проверенный исходный архив пересчётов

**DONE / TESTED:** `releases/2026-10-10-count-anchor/AsBoljam_Final.zip` создан из чистого commit `a3d5038fde409a913dd48d45f2dc4570fb19d1e7`: 303 исходных файла, 1791761 байт. CRC, состав архива, размеры и SHA256 каждого файла проверены упаковщиком и независимым повторным чтением. SHA256 ZIP: `45da77922c55e19a66048e8dc4c9b112e7ea7ffa59028891c3c62b3bc5066e01`. [Свидетельство упаковки](../artifacts/verification/release-20261010-count-anchor.json). Следующий commit фиксирует только документацию и результат упаковки; код приложения совпадает с source_commit архива. Старые ZIP и приватные backup сохранены. **NOT TESTED:** новая установка из распакованного ZIP, production, реальный пилот и новый APK/device.

## 10.10.2026 — web пересчётов и сквозная приёмка

**DONE:** KK/RU интерфейс принятия полного нового остатка, разницы по партиям, обязательное подтверждение, история, точный повтор при потерянном ответе, права/филиал/источник и защита от устаревших ответов. Основа чтения и плана видна по дате. Отмена движений прежнего периода недоступна; дата нового движения начинается с действующей основы. README, контракты UI/OpenAPI, runbook и release gates обновлены.

**TESTED:** финальные29/29 Chrome API-fixture проверок (76.553513s), TypeScript/Vite PASS (4.17s),390px RU screenshot просмотрен. Live1/1 PASS с первой попытки (48.000971s suite) на новой generated REAL/TEST SQLite: login → открытие → старый approved plan → HTTP CSV correction → блокировка → два UI-пересчёта и прихода → старый день → сверка → настоящие forecast/procurement worker → UI approval → audit/export. Журналversion5/movementsequence2, два anchor-audit, старый approved CSV побайтно прежний,0 pageerrors. Исходники стабильны. [Отчёт](../artifacts/verification/stock-count-anchor-web-20261010.json).

После полного Python изменён только standalone browser-fixture helper:85 REAL/TEST дней для двух последовательных origin, SYNTHETIC84 и фиксированный cutoff сохранены. Код приложения не менялся. Созданные API8012/worker/web3013 остановлены, данные и старые backups сохранены. **IN PROGRESS:** общая коммерческая подготовка; следующий локальный участок — безопасная связь request→job в логах. **NOT TESTED:** production/load/TLS, бизнес-пилот, свежий APK/device. **BLOCKED внешними данными:** измеренный эффект/POS требуют реального согласованного источника.

## 10.10.2026 — общая регрессия после пересчётов

**TESTED:** `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` —454 случая за512.179s:453 PASS,0 failures/errors,1 POSIX-only SIGTERM skip на Windows. Все API/worker/test/script исходники неизменны в течение прогона, временный global API import направлен в `.cache/count-anchor-full-regression-import.sqlite`. [Отчёт](../artifacts/verification/count-anchor-regression-20261010.json). Это новый фактический полный прогон; прежние неуспешные отчёты сохранены как история.

**IN PROGRESS:** новая live browser приёмка на отдельном generated REAL/TEST fixture; она не подтверждает бизнес-пилот. **NOT TESTED:** production/load/device; научные расчётные алгоритмы не менялись, research без причины не повторялся.

## 10.10.2026 — API подтверждённого пересчёта и PostgreSQL

**DONE:** preview → явное подтверждение полного пересчёта → неизменяемый документ/аудит/receipt. Раздельные sequence движений и version журнала, чтение по датам, запрет обратной записи через принятый срез, строгая полнота партий и неизменность источника. Закупка сохраняет выбранный срез своего периода; поздние пересчёты не устаревают прежний план, утверждённая выгрузка сохраняется.

**TESTED:** SQLite anchor16/16 (5.911s), arithmetic16/16 (0.518s), service20/20 (2.484s), HTTP6/6 (15.955s). Первоначальный service19/20 FAIL из-за ожидания целого объекта после добавления source_freshness сохранён; уточнены проверки неизменных rows/date/anchor и изменившейся свежести. [Focused отчёт](../artifacts/verification/count-anchor-service-20261010.json). PostgreSQL80/80 PASS (122.146s):79 реальных PG bodies и1 pure engine, стабильные исходники, без skips/errors/failures. [PG отчёт](../artifacts/verification/postgres-count-anchor-20261010.json).

**DONE / TESTED:** основная SQLite0007→0008 после verified backup `backups/pre-count-anchor-0008-20261010T083943699092Z.sqlite`. Хеши и количество строк всех21 старых таблиц совпали, новая таблица пуста, integrity/FK PASS. [Отчёт миграции](../artifacts/verification/count-anchor-main-migration-20261010.json). Контейнер PostgreSQL остановлен, прежние БД/volumes сохранены.

**IN PROGRESS:** финальная Python-регрессия и новая live browser приёмка. **NOT TESTED:** production/реальный пилот/device. Численные forecast/procurement алгоритмы не менялись; успешный research без причины не повторялся.

## 10.10.2026 — хранилище подтверждённых пересчётов

**DONE:** migration0008 добавляет пустую таблицу stock_count_anchors с зафиксированными строками, происхождением, расхождениями, причиной и границей прежних движений. Исходный baseline и движения не переписываются. Ограничения базы связывают версию журнала с отдельными последовательностями пересчётов и движений; tenant/orphan guards учитывают новую историю.

**TESTED:** новые миграционные тесты7/7 PASS (0.748s); затронутые ожидания схемы и guards10/10 PASS (0.974s), изолированная SQLite. Команды и ограничения: [отчёт](../artifacts/verification/count-anchor-migration-20261010.json). **IN PROGRESS:** service/API/UI и PostgreSQL. **NOT TESTED:** основная база0007 ещё не обновлена; полный workflow, production и пилот этим коммитом не подтверждены.

## 10.10.2026 — архив складского этапа

**DONE / TESTED:** `releases/2026-10-10-stock/AsBoljam_Final.zip`, source commit `3c642defa09638aa844ef316b8fe22493bc542c9`,290 файлов,1730125 байт; CRC и хеши всех файлов PASS. SHA256 ZIP `25f83dda0acfbf2dab900b06fc5fa00bc764a0810e4c0816952dfbf91a5ab66f`. [Отчёт](../artifacts/verification/release-20261010-stock.json). Архив создан из чистого Git без баз/секретов/dependencies; старые выпуски сохранены. **NOT TESTED:** новая установка из распакованного архива, новый APK, enterprise/production. Следующий commit фиксирует только свидетельство упаковки и документацию.

## 10.10.2026 — складской интерфейс и настоящая браузерная приёмка

**DONE:** web KK/RU открывает журнал и проводит складские документы через явный preview/подтверждение; активирует полные датированные рецепты, показывает историю/обратную запись/сверку и основания плана. При смене даты прежние остатки убираются; устаревший ответ игнорируется. Совпавшие числа при изменённом исходном срезе не получают зелёный статус. Ошибки сверки и активного рецепта объясняют следующий шаг на KK/RU. Генератор manifest/design-copy/screens/tokens обновлён.

**TESTED:** финальный web TypeScript/Vite build PASS (Vite4.00s); Chrome23/23 с API-fixtures (41.2s):17 новых stock и6 REAL-context. Отдельный live1/1 (37.8s тест,40.3s suite) на свежей SYNTHETIC SQLite с настоящими API/worker: login → opening → recipe → receipt → recipe usage → reversal → reconciliation → forecast/procurement → approval → audit/export. Ширина390px и точные decimal strings проверены. [Отчёт](../artifacts/verification/stock-web-20261010.json). Предыдущие harness failures сохранены в отчёте отдельно; полный backend/research без новых изменений не повторялся.

**DONE cleanup:** остановлены только созданные проверочные процессы, основная БД и искусственные fixtures сохранены; PostgreSQL возвращён в исходное остановленное состояние без удаления volumes. [Инструкция повторения](../docs/commercial/STOCK_BROWSER_TEST_RU.md).

**TODO / NOT TESTED:** неизменяемое разрешение исправленного baseline, реальный пилот/POS, production/load/TLS и новый APK. Коммерческая готовность целиком не заявлена.

## 10.10.2026 — PostgreSQL для складского HTTP и рецептур

**TESTED:** последовательный повтор31/31 PASS (54.965s): API13/13 (36.206s), рецептуры18/18 (7.472s), включая защиту исходной организации.30 PG test bodies и1 чистый engine test; исходники стабильны. [Повторный отчёт](../artifacts/verification/postgres-stock-api-20261010-retry.json).

Первый параллельный запуск истёк по общему лимиту300s без итогов тестов; он сохранён как FAIL, а не заменён успешным результатом. [Исходный timeout](../artifacts/verification/postgres-stock-api-20261010.json). Проверочный runner получил явную ограниченную настройку30–900s, по умолчанию300; повтор использовал600s и завершился раньше55s. Production timeouts не менялись. Тестовые БД/volumes сохранены; production не проверен.

## 10.10.2026 — общая регрессия и исправление гонки в тесте worker

**TESTED:** общий Python-прогон425 случаев (470.640s), неизменные исходники:423 PASS,1 FAIL,1 POSIX SKIP на Windows. Единственный FAIL — тест зависшего child требовал маркер вычисления за0.5s, включая запуск интерпретатора. Рабочий supervisor корректно завершил ещё не стартовавший расчёт по deadline. [Исходный отчёт](../artifacts/verification/stock-regression-20261010.json).

**DONE / TESTED:** только тестовая fixture ждёт готовности реального child/PID с отдельной границей10s; затем проверяет прежний timeout0.5s, отсутствие преждевременной остановки, завершение процесса и удаление файлов. Production-код не менялся. Повтор всего связанного worker-process suite13/13 PASS (22.419s), стабильные исходники. [Повтор](../artifacts/verification/stock-worker-regression-20261010.json). Общий425-прогон не объявляется полностью зелёным задним числом и без причины не повторяется.

## 10.10.2026 — HTTP склад, актуальность закупки и сохранённые основания

**DONE:** web-session API для складских команд и активаций; закупка использует точный посчитанный срез и требует его сверки с открытым журналом. Эффективные рецепты выбираются полностью на дату, каждый yield применяется один раз. Относящиеся к периоду новые данные делают план устаревшим, будущие движения/версии не меняют старую целевую дату. Результат и CSV сохраняют основания, версии и отпечатки. OpenAPI обновлён.

**TESTED:** новые API/engine13/13 SQLite PASS (36.145s), включая реальные транзакции, конфликт версий, scope/CSRF/native denial, queue/worker, устаревшее утверждение, неизменные утверждённые CSV и повтор решения после реальной CSV-коррекции. Повтор research:9 прогнозов/36 закупок (11.759934s); все пять численных CSV совпали с сохранёнными, исключая elapsed_seconds. [Research evidence](../artifacts/verification/stock-research-20261010.json). Основная SQLite0006→0007: проверенная резервная копия, все19 прежних таблиц неизменны, новые таблицы пусты, integrity/FK PASS. [Migration evidence](../artifacts/verification/recipe-migration-20261010.json).

**IN PROGRESS:** общая регрессия, PostgreSQL для HTTP и browser-приёмка; их результаты будут записаны после завершения. **TODO / NOT TESTED:** восстановление после исправленного исходного среза, реальный пилот, production, новая native-сборка.

## 10.10.2026 — проводки склада и датированные рецептуры

**DONE:** транзакционные сервисы открытия журнала, прихода, списания, корректировки, рецептурного расхода и обратной записи; полные неизменяемые версии рецептов по филиалу/блюду/дате. Migration0007 добавляет recipe_activations и recipe_command_receipts. Preview/fingerprint/version/idempotency, повторная проверка прав, источник документа и аудит защищают каждое проведение. Исправление исходного среза блокирует новые проводки, сохраняя историю. Закрыта регистрация организации/REAL-источника поверх осиротевших новых таблиц.

**TESTED:** SQLite: stock service20/20 (10.102s), stock math16/16 (1.378s), recipe activation17/17 (6.334s), migration45/45 (10.204s), REAL source11/11 (4.631s), tenant CLI15/15 (3.007s). PostgreSQL93/93 (60.922s):91 PG test bodies и2 SQLite backup bodies, стабильные исходники. См. [отчёт](../artifacts/verification/postgres-stock-service-20261010.json).

После review добавлена проверка исходной организации при обновлении ORM-пользователя: recipe suite18/18 SQLite PASS (1.661s); эта дополнительная проверка ещё ожидает PostgreSQL-прогона.

**IN PROGRESS:** HTTP/API, procurement, web и live-приёмка интегрируются отдельно; этот commit сам по себе их не подтверждает. **TODO:** явное разрешение исправленного начального среза отдельным неизменяемым документом. **NOT TESTED:** основная БД ещё не обновлена до0007, production/pilot/device.

## 10.10.2026 — язык ошибок расчёта

**DONE:** пять известных JOB-ошибок показываются на выбранном KK/RU, включая тайм-аут. Раньше русский интерфейс показывал казахское сообщение worker. Неизвестные ошибки сохраняют прежний fallback; повторный расчёт автоматически не создаётся.

**TESTED:** контракты UI-copy обновлены; web build PASS; Chrome11/11 PASS (50.4s) с API-fixtures, включая два языка тайм-аута, отсутствие повторного POST, историю/повтор polling и ширину390px. Скриншоты обоих языков просмотрены. [Отчёт](../artifacts/verification/job-error-localization.json). **NOT TESTED:** новый live browser/backend/device прогон; сервер не менялся, его успешные проверки без причины не повторялись. Прежний ZIP остаётся снимком своего manifest commit.

## 10.10.2026 — проверенный архив текущих исходников

**DONE / TESTED:** `releases/2026-10-10/AsBoljam_Final.zip` создан из чистого commit `1e49912fe2985eb518971fdd24251766eb21a7d4`:264 файла,1612448 байт. CRC и SHA256 каждого файла проверены упаковщиком и повторным чтением; секретов по правилам сканера не обнаружено. SHA256 ZIP: `bc2ee5e7097bac7fed857aa274d9567133a9ca7f9907a57be4d931ed2036546a`. Старые архивы сохранены. [Отчёт](../artifacts/verification/release-20261010.json).

**NOT TESTED:** новая установка из распакованного ZIP, production и свежая native-сборка. ZIP содержит исходники и известные ограничения, а не подтверждение коммерческого запуска. Следующий commit фиксирует только свидетельство упаковки; точный source commit указан в RELEASE_MANIFEST.json внутри ZIP. Пилот, полный складской workflow и эксплуатационная приёмка остаются незавершёнными.

## 10.10.2026 — HTTP-приёмка worker с дочерним расчётом

**TESTED:** commit02c6cd1 —87/87 HTTP checks PASS на отдельной новой SYNTHETIC SQLite: вход, readiness, scope/role/CSRF, реальный forecast и procurement через отдельный worker, утверждение с версией/причиной/idempotency, audit/export и CSV preview/commit/replay. API запущен на127.0.0.1:8011, расчёт использовал новый subprocess worker. [HTTP-отчёт](../artifacts/verification/runtime-worker-process.json), [контекст запуска и ограничения](../artifacts/verification/worker-process-isolation.json).

Только созданные для проверки процессы API/worker остановлены, искусственная база сохранена в ignored .cache; основная база не изменялась этим прогоном. Новый browser/device/production-пилот не проверялся. Это подтверждает серверный workflow, а не готовность коммерческого запуска.

## 10.10.2026 — отдельный процесс расчёта и ограничение времени

**DONE:** worker выполняет расчёт в дочернем процессе без переменных паролей/БД. Настраиваемый срок1–3600s (по умолчанию900s), остановка при утрате захвата/доступа, heartbeat и проверка права публикации сохранены. Приватные JSON-файлы с атомарным результатом не блокируют заполненную pipe. Запрос наблюдения не перечитывает весь snapshot. Первый сигнал завершает текущую работу; manual cancel API/UI не добавлены.

**TESTED:** Windows worker47 PASS+1 POSIX skip (16.980s). Общая Python-регрессия371 случай:370 PASS+1 POSIX skip (172.918s), исходники в ходе прогона не менялись. Linux/PostgreSQL: первоначально81/82 PASS; единственный сбой вызван путём тестового помощника относительно /tmp. Исправлены только два пути POSIX-теста; повтор связанных6/6 PASS, включая настоящий SIGTERM и публикацию после завершения child. Прежние успешные suites не повторялись. Проверены настоящий forecast/REAL procurement, timeout, отзыв доступа, смена захвата, гибель родителя, очистка файлов, большой ответ и следующая задача. Compose config PASS с временным паролем только для проверки синтаксиса; сервисы не развёртывались. [Подробные результаты и исходные отчёты](../artifacts/verification/worker-process-isolation.json).

**NOT TESTED / TODO:** production deployment/load/failover и пилот. Тайм-аут не ограничивает ожидание БД при публикации; OS hard-kill может оставить приватные temp-файлы. Поток наблюдения за родителем зависит от планировщика Python при долгом удержании GIL native-кодом. Browser/build/research/native без изменений повторно не запускались; новый APK/ZIP не создан. Полный складской API/UI, датированные рецепты, procurement lineage и коммерческая приёмка остаются в плане.

## 10.10.2026 — хранилище складского журнала

**DONE (хранилище):** migration0006 добавляет пустые stock_ledgers, stock_movements и stock_command_receipts. Ограничения защищают версию, порядок, номер исходного документа и повтор обратной записи. Старые снимки не превращаются в вымышленные движения.

**TESTED:** migration suites45/45 SQLite (8.208s),45/45 PostgreSQL (17.086s;43 PG bodies и2 SQLite backup tests). Проверены сохранение старых строк, rollback, повтор и конкуренция миграции, ограничения новых таблиц. Основная SQLite обновлена с0005 до0006 после проверенной резервной копии; SHA256 содержимого всех16 прежних таблиц совпали, integrity/FK PASS, новые таблицы пусты. См. [отчёт миграции](../artifacts/verification/stock-migration.json) и [PostgreSQL](../artifacts/verification/postgres-stock-journal.json).

**IN PROGRESS / NOT TESTED:** API/UI складских документов, датированные рецепты, сверка и связь с procurement ещё не реализованы. Миграция не доказывает готовность полного склада или production deployment.

## 10.10.2026 — арифметика складских движений

**DONE (расчётный модуль):** явные партии, receipt/waste/adjustment/recipe_usage/reversal, gross decimal quantities, запрет отрицательного остатка и смены kg/L/expiry; неизвестная партия не выдаётся за ноль. Opening-сверка использует движения D..E−1 и сохраняет missing/mismatch. Рецептурный yield применяется один раз, дроби суммируются точно и округляются вверх до1e−9 только после агрегации.

**TESTED:** `python -X utf8 -m unittest discover -s tests -p test_stock_math.py -v` —15/15 PASS (2.697s). Review выявил несовместимость меток recipe_version с точками/пробелами; исправлено с проверкой реально принимаемого CSV. Первый прогон обнаружил Decimal Overflow при1E1000000; исправлена проверка через copy_abs, повтор прошёл. Проверены границы дат/сроков, рецептура, откат набора при плохой строке и различие нуля/неизвестного. [Отчёт](../artifacts/verification/stock-math.json).

**IN PROGRESS / NOT TESTED:** это основа, не готовый складской продукт. API/UI/posting, датированная активация рецепта, интеграция procurement/lineage и live приёмка ещё не выполнены. Полные критерии сохранены в [плане складского контура](../docs/commercial/STOCK_LEDGER_DESIGN_RU.md); цель выхода на рынок не завершена.

## 04.10.2026 — история и повторное открытие расчётов

**DONE:** история прогноза/закупки берётся с сервера, с фильтром выбранного филиала и типа, стабильным порядком created_at/id и страницами по20. После reload можно открыть выполняющуюся или сохранённую задачу без нового POST. Ошибка загрузки не маскируется пустой историей; есть повтор GET. `/runs` сохраняет role/org/branch isolation, лимит максимум50, no-store и безопасную проекцию без snapshot/payload.

**TESTED:** новые API7/7 SQLite (3.315s) и7/7 PostgreSQL; прежние API19/19 (20.683s), включая настоящий worker/forecast/procurement/export. Chrome9/9 (30.7s) с API-fixtures: reload для обоих типов, готовый результат, пагинация, ошибка истории и прежний polling. Web build PASS; screenshot desktop1440/mobile390 просмотрены, overflow отсутствует. До этого блока полный Python330 PASS+1 POSIX skip; после добавления истории повторены релевантные API/browser suites, а не весь неизменённый engine. [Отчёт](../artifacts/verification/job-history.json).

**NOT TESTED:** новая live browser приёмка истории, production data/load/deployment, новый APK/ZIP. Stock ledger, CPU deadline/cancellation и бизнес-пилот остаются незавершёнными.

## 04.10.2026 — понятный статус расчёта и восстановление связи

**DONE:** web показывает очередь/выполнение/ошибку на KK/RU, возраст последнего heartbeat по серверным часам и предупреждение после90 секунд без ответа. Это не процент готовности и не доказательство прогресса CPU. Ошибка получения статуса позволяет повторить GET той же задачи без нового POST; failed прекращает polling и возвращает к параметрам только по кнопке. API сохраняет роль/org/branch scope, не раскрывает snapshot/payload и отдаёт no-store; OpenAPI/shared Run обновлены.

**TESTED:** SQLite4/4 и PostgreSQL4/4 для API статуса; Chrome5/5 для queue/heartbeat/KK/RU/offline retry/failed/missing result ID, без повторного POST. Desktop1440 и mobile390 проверены визуально и на отсутствие горизонтального overflow. Web build и mobile typecheck PASS. Финальная Python-регрессия331 случаев:330 PASS,1 POSIX skip,64.760s; реальный SIGTERM отдельно проверен в Linux ранее. [Отчёт](../artifacts/verification/job-status.json).

**NOT TESTED / TODO:** браузерные новые сценарии используют детерминированные API-fixtures; новая единая live browser приёмка не запускалась. Сохранение выбора задачи после reload ещё не реализовано. Новый APK/ZIP не собраны; бизнес-пилот и deployment не подтверждены.

## 04.10.2026 — корректная остановка worker

**DONE:** первый SIGINT/SIGTERM останавливает получение новых задач, текущая завершается с heartbeat и публикацией. Захват на границе остановки возвращается в очередь с проверкой прежнего started_at; отменённые/новые захваты не затрагиваются. Ожидание SQLite claim-lock прерывается без нового вычисления; исходные signal handlers восстанавливаются, engine освобождается. Compose даёт120s на остановку.

**TESTED:** Windows worker suite35 случаев:34 PASS,1 POSIX skip. Linux/PostgreSQL25/25 PASS, включая настоящий SIGTERM дочернему процессу во время вычисления: результат сохранён, heartbeat работал, следующая задача осталась queued. Первый PG-отчёт оказался непарсируемым из-за stdout теста; runner теперь сохраняет stdout/stderr в результат suite, повтор25/25 прошёл. [Отчёт](../artifacts/verification/worker-shutdown.json).

**NOT TESTED:** фактический Compose stop/redeploy, production failover/load. Второй сигнал/Windows force stop/SIGKILL могут оставить аренду для последующего восстановления; CPU cancellation и deadline не реализованы.

## 04.10.2026 — готовность БД и актуальная HTTP-приёмка

**DONE:** `/api/v1/health` сообщает только liveness, новый `/api/v1/ready` проверяет доступ к БД и точный набор миграций. При несовместимости/недоступности —503 с безопасным кодом, без строк подключения или tenant metadata; ответы no-store, проба не чинит схему. Compose healthcheck и ожидание cloud_verify используют ready. OpenAPI обновлён. HTTP-verifier теперь проверяет идемпотентный повтор commit, неизменённую повторную строку и отдельный запрет дублей внутри CSV; tenant SYNTHETIC подтверждается после login.

**TESTED:** readiness SQLite5/5 PASS; PostgreSQL5/5 PASS; API19/19 PASS, включая OpenAPI. Настоящие HTTP API+отдельный heartbeat worker на искусственной организации —87 checks PASS: login, scope/roles/CSRF, forecast, закупка, версия/причина/idempotency утверждения, аудит, CSV и атомарный повтор импорта. [Отчёт](../artifacts/verification/readiness.json), [HTTP](../artifacts/verification/runtime-current.json).

**NOT TESTED:** новый Docker/Cloud deployment, HTTPS/нагрузка, native/бизнес-эффект. Readiness не доказывает наличие worker или прогресс модели. Неизменённый web не пересобирался.

## 04.10.2026 — heartbeat длительных расчётов

**DONE:** migration0005 добавляет nullable jobs.heartbeat_at, сохраняя исходный started_at как идентификатор захвата. Worker продлевает текущую running-задачу каждые30 секунд отдельной короткой транзакцией; повторный захват использует heartbeat или старый started_at. Старый/отменённый обработчик не может продлить новый захват или опубликовать результат. Ошибки heartbeat обезличены. [Правила обновления и ограничения](../docs/commercial/WORKER_OPERATIONS_RU.md).

**TESTED:** focused worker29/29 PASS, полный Python316/316 PASS (66.805s), PostgreSQL runner102/102 PASS (87 PG bodies,13 pure engine,2 SQLite backup;89 PG fixture schemas). Проверены фоновые heartbeat, конкуренция с reclaimer, утрата аренды, отказ старой публикации, rollback/concurrent migration и прежняя изоляция. Основная SQLite обновлена0005 после backup SHA256 e4f173286774e9e7e3428c3ee9b5ce5d0bbf01c88dceb0674c8a277034261701: прежние counts совпали, старые job columns совпали, выдуманных heartbeat0, integrity/FK PASS. [Отчёт](../artifacts/verification/worker-heartbeat.json).

**NOT TESTED / TODO:** production kill/failover/load, ожидание30 минут реального времени, graceful drain/CPU cancellation и наблюдаемость. Expiry проверяется управляемыми часами. Web/API контракты не менялись, успешные browser/build/mobile без причины не повторялись. APK/ZIP не обновлены. Общая коммерческая цель не завершена: stock ledger, эксплуатация и бизнес-пилот остаются.

## Возобновление 04.10.2026 — проверки checkpoint закрыты

**TESTED:** сохранённый commit `569ae904ace910c1164cd376310ee7bb947e1573`: Python304/304 PASS (139.282s); ранее упавший live correction/recompute/approval/export —1/1 PASS (43.7s) на настоящих API/worker и отдельной SYNTHETIC-базе. PostgreSQL worker/REAL execution/API —42/42 PASS:29 PG bodies и13 pure engine tests;29 PG fixture schemas. Исходники во время проверки не менялись. [Команды и границы](../artifacts/verification/resume-2026-10-04.json). Непроверенные в checkpoint последние worker/engine/API исправления теперь покрыты этими прогонами; единый новый прогон всех browser-сценариев не запускался.

**IN PROGRESS:** улучшение надёжности длительных фоновых расчётов. **NOT TESTED:** реальный бизнес/эффект, production deployment, свежий APK/ZIP. Неизменённые build/mock/mobile и независимые старые PG suites без причины не повторялись. Ниже сохранена история остановки; её pending-пункты читать с учётом этого обновления.

## Актуальное продолжение — источник REAL, даты и устойчивость worker, 29.09.2026

**STOP / SAVED CHECKPOINT:** пользователь попросил «стоп остановись с сохранениями». Новые проверки и разработка остановлены. API/worker/web preview и тестовый PostgreSQL остановлены, данные и volumes сохранены. Итоговая общая регрессия после последних исправлений не запускалась. При продолжении сначала повторить упавший `import_lineage_live.spec.ts` на уже подготовленной свежей small fixture в `.cache/real-live.sqlite`, затем соответствующие Python/PG проверки worker/engine/API; не считать предыдущие зелёные прогоны проверкой последних изменений.

Продолжена существующая `main` от `6d60ac491b893f0148ee072e2c765d83adb78991`. Предприятие не подключалось. Новый сгенерированный набор использует REAL-контракт только с назначением `test_fixture` и маркировкой **TEST**; это проверка программы, не бизнес-пилот.

**DONE:** явная миграция0004 сохраняет прежние организации и добавляет `real_only`/OrganizationSource. Оператор может зарегистрировать один источник, mapping и филиал только на пустой активной `unconfigured`-организации; по умолчанию CLI выполняет preflight, применение отзывает прежние сессии атомарно. Ссылка на разрешение — декларация оператора, не проверенное согласие предприятия. Старое SYNTHETIC-демо не переключается в REAL. Импорт проверяет источник, происхождение, филиал, timezone и даты до preview/commit; генераторные поля REAL запрещены. Изменившийся контракт блокирует commit/новое утверждение, сохранённые решения и их точный replay остаются неизменными.

**DONE расчёты/UI:** REAL требует явно выбранный завершённый день в timezone организации и не менее84 непрерывных дней продаж каждого прогнозируемого блюда. Горизонт остаётся один день; точный snapshot должен покрывать каждый нужный ингредиент. Неизвестный остаток не выдаётся за ноль, включая неиспользуемые позиции каталога. Источник, назначение TEST/PILOT и даты сохраняются в задаче/результате; worker проверяет контракт до публикации. Web KK/RU выбирает фактические периоды, даты прогноза и остатка, обновляет покрытие после commit и не подставляет демо-даты в REAL. Экспорт отчёта сохраняет TEST/PILOT/source metadata; он не является каноническим CSV для повторного импорта. Native REAL явно ограничен403 до поддержки этого контракта клиентом.

**DONE исправления по проверкам:** worker больше не завершается из-за SQLite BUSY/LOCKED при захвате задания. Claim/publication повторяются свежими транзакциями с задержкой; результат не вычисляется повторно при блокировке публикации, отмена и claim-time fence сохранены. Другие DB faults не скрываются под retry и завершаются безопасным сообщением. Устранены найденные при регрессии ошибка зависимости `/session/me`, переполнение крайней даты dashboard и устаревший запрет REAL в отчёте offline-адаптера.

**TESTED:** до последних исправлений Python295/295 PASS (89.648s), PostgreSQL runner158/158 PASS (145 PG bodies +2 SQLite backup +11 pure engine;115.55s). Web build PASS, mock Chrome37/37 PASS (2.3min), mobile typecheck и13/13 tests PASS. Live Chrome8/9 PASS (6.3min): correction-сценарий завис после падения worker на SQLite lock. После его перезапуска остальные8 прошли, включая новый TEST→import9CSV→forecast→procurement→approval→export; снимки desktop/mobile просмотрены. После исправлений точечно прошли SQLite contention6/6, worker security11/11, REAL execution19/19 и REAL API12/12. Упавший live-сценарий, финальная общая Python-регрессия и PG после последних worker/engine/API правок **NOT TESTED** из-за остановки пользователем. Команды/границы: [real-platform.json](../artifacts/verification/real-platform.json). Старые результаты не подменяют проверку checkpoint.

До0004 создан private online backup `backups/pre-real-0004-c38b7679800b4d48979a5cfac5419ace.sqlite`, SHA256 `d788f09cd3b37d8d2739866ed513222e0595f572b15554d2d85d91a221d44c79`. После обновления0001–0004 counts всех прежних таблиц, кроме migration marker, совпали;200725 operational rows сохранены, строки7 организаций совпали полностью, зарегистрированных REAL-источников0. Integrity/FK PASS. Новые тесты отдельно проверяют rollback, concurrent startup, SQLite backup/restore и PostgreSQL миграцию. Основная БД не использовалась для браузерных мутаций.

**IN PROGRESS:** коммерческая подготовка остаётся незавершённой. **TODO:** stock movement ledger, heartbeat и восстановление длительных задач, наблюдаемость, эксплуатация и остальные [release gates](../docs/commercial/RELEASE_GATES_RU.md). [Операторская инструкция REAL](../docs/commercial/REAL_DATA_OPERATIONS_RU.md) описывает фактические ограничения, включая однодневную поставку/lead time0 и исторический расчёт на текущих импортированных данных.

**BLOCKED:** полевой пилот и измерение эффекта требуют предприятия; это не мешает дальнейшей технической разработке. **NOT TESTED:** бизнес-данные/экономия, целевой HTTPS deployment, нагрузка/SLA, независимый аудит, native REAL/device runtime. APK/ZIP/research benchmark не пересобраны; полный pg_dump/restore после0004 не повторялся. Конфигурация production и регистрация источника не означают production-ready.

Ниже — история предыдущих блоков; их старые запреты REAL и TODO читать с учётом этого обновления.

## Актуальное продолжение — история импорта и версии данных, 29.09.2026

Продолжена `main` от `5b2468122d59eeeb4832484612ad24210983644b`, без реального предприятия.

**DONE:** явная additive-миграция0003 добавляет ImportEvidence, RecordRevision и ImportReceipt. Preview хранит источник/версию сопоставления, хеш полученного UTF-8 текста, хеш разобранных canonical rows, период, филиалы, счётчики и полноту проверки. Заявленный исходный SHA256 не считается проверенным. Старым загрузкам не приписано вымышленное происхождение. Commit атомарен и идемпотентен; повтор одинаковых строк не создаёт дублей. Изменённые значения требуют режима correction, существующих ключей и причины; поддержаны только daily_sales/calendar/inventory_lots. Версии «было → стало», аудит и квитанция сохраняются вместе. Изменение между preview/commit, включая ABA, блокирует устаревшую коррекцию. Повтор branches не выдаёт доступ к чужому филиалу.

**DONE расчёты/UI:** forecast/procurement сохраняют хеши, версии и выборки входных строк; новый релевантный ряд тоже делает старый расчёт неактуальным. Готовый план с изменённым/непроверяемым источником нельзя утвердить до пересчёта. Прежние результаты, утверждённые решения, CSV и точный idempotent replay не переписываются. В web KK/RU есть история, ссылки из расчёта на загрузку, подтверждение исправления и восстановление результата после потерянного ответа commit. Исходные даты SYNTHETIC сохранены. Исправлен независимый сброс полей пароля при фоновой загрузке settings: формы больше не размонтируются вместе с metadata.

**TESTED:** финальный `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` — **242/242 PASS, 60.489 s**. PostgreSQL runner восьми suites — **109/109 PASS, 73.648 s**: 108 тел тестов PostgreSQL17.11 и один намеренный SQLite backup/restore case; 109 отдельных PG fixture schemas, исходники во время прогона не менялись. [PG report](../artifacts/verification/postgres-import-platform.json). Полные команды и source hashes: [import-platform.json](../artifacts/verification/import-platform.json).

`npm.cmd run build` — **PASS**, 1753 modules, Vite4.72 s. Mock Chrome sessions/imports/account/tenant — **31/31 PASS, 1.3 min**. Live Chrome: **7/8 PASS** в первом прогоне2.6 min; единственный failure — неоднозначный старый селектор сообщения, которое теперь также есть в истории импорта. Селектор ограничен областью результата preview; повторён только `workflow.spec.ts --grep "login → CSV"` — **1/1 PASS,37.1 s**. Все8 различных live-сценариев получили успешный результат; общий live suite после этой правки теста не повторялся. Новый live-сценарий выполняет четыре настоящих worker jobs и проверяет correction → stale approval refusal → replay без дублей → recompute → approve → correction → неизменность старого CSV/решения/idempotent reply. Existing live suite также проверил HGB, роли, onboarding, пароль и responsive. Снимок approved mobile с сообщением об изменившихся входных данных просмотрен; горизонтального overflow страницы нет.

До0003 создан private online backup основной SQLite: `backups/pre-import-0003-ac122a6caab544e0b8fdb691cfae8ed2.sqlite`, SHA256 `e4eba28735e171eb871a01f653dfe5a2d31dca8c5835670894a78e303ae36467`. Integrity/FK PASS. После миграции версии0001/0002/0003; количества строк всех12 прежних таблиц, кроме migration marker table, совпали, в том числе200725 operational rows. Новые sidecars пусты: исторический source не выдуман. Tests отдельно проверяют точное сохранение строк, rollback, concurrent migration и backup/restore.

В ходе проверки исправлены: неполная reference-validation после500 ошибок без признака усечения; возможность расширения branch scope через повтор справочника; password-form initialization race. После backend-исправления повторены Python/PG, после UI-исправления — build/mock browser. API/worker/preview и PG-контейнер остановлены, порты3000/8000 свободны; базы и volumes сохранены. Тестовые credentials, DB, screenshots/traces и backup не входят в Git/ZIP.

**IN PROGRESS:** общая коммерческая подготовка. **TODO:** законченная REAL/date policy по всей цепочке, stock movement ledger, heartbeat/recovery, эксплуатационные gates. [Матрица](../docs/commercial/RELEASE_GATES_RU.md) сохраняет полный объём цели; [runbook импорта](../docs/commercial/IMPORT_OPERATIONS_RU.md) описывает текущие правила.

**BLOCKED:** полевой пилот и измерение эффекта требуют предприятия; это не блокирует локальную разработку. **NOT TESTED:** REAL-импорт по-прежнему запрещён; целевой HTTPS deployment, нагрузка/SLA, независимый аудит, реальная экономия и обновлённый device runtime. APK/ZIP/research benchmark не пересобраны; pg_dump/restore на0003 отдельно не выполнялся. Массовый rollback/удаление, коррекции справочников и журнал складских движений ещё не реализованы. Production-ready не заявляется.

Ниже — история предыдущих блоков; старые TODO/BLOCKED читать с учётом этого обновления.

## Актуальное продолжение — организации и первый запуск, 29.09.2026

Продолжена `main` от `129f140c4bc8e2de002a8fb0f0e6ef0decbda6e1`, без реального предприятия.

**DONE:** Organization и явная миграция0002; metadata/status/timezone/data policy; операторский bootstrap первого admin без демо-записей; suspend/resume с атомарным отзывом сессий, refresh и queued/running jobs. Возобновление их не восстанавливает. API/пароли/worker соблюдают порядок Organization → User → session/job. CLI требует явной существующей БД с поддерживаемой схемой, preflight по умолчанию, `--apply`, скрытый пароль и operator/reason/audit. Migration CLI проверяет конфигурацию до открытия БД.

**DONE UI:** пустая организация получает настройку без branch=1 и чужого имени. После branches CSV обновляются сессия и филиалы без logout; старые ответы прежнего аккаунта игнорируются. Unconfigured не запрашивает операционные данные. Metadata берётся из БД; без истории продажи/выручка — `—`, подтверждённые нулевые продажи — `0`. Даты графика/планов берутся из API, диапазон продаж обозначен как фильтр. OpenAPI/design contracts и [runbook](../docs/commercial/TENANT_OPERATIONS_RU.md) обновлены.

**TESTED:** полный `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` — **196/196 PASS, 44.788 s**. После финального guard версии схемы повторён только затронутый `test_tenant_cli.py` — **10/10 PASS, 0.986 s**; полный suite после этой CLI-правки не повторялся. PostgreSQL runner пяти suites — **64/64 PASS, 50.21 s**: 63 тела тестов PostgreSQL17.11, один backup/restore case намеренно SQLite; все64 fixture setups создали отдельные PG-схемы. Backend не менялся во время PG-прогона. [PG report](../artifacts/verification/postgres-tenant-platform.json).

`npm.cmd run build` — **PASS**,1751 modules,Vite3.32 s. Mock Chrome sessions/imports/account/tenant — **22/22 PASS,28.6 s**. Live Chrome workflow6 + первый tenant1 — **7/7 PASS,48.6 s**, настоящие API/worker и `.cache/tenant-live.sqlite`. Проверены шаблон → CSV → новый branch scope, пустая история, полный synthetic workflow до approval/export, HGB, роли/сессии и responsive. Mobile audit screenshot просмотрен, таблица остаётся внутри scroll region. [Все команды и границы](../artifacts/verification/tenant-platform.json).

До0002 создан приватный online backup основной SQLite: `backups/pre-tenant-0002-c8157ef272ee49aeb1b3a14f88536c25.sqlite`, SHA256 `cc0acff19e2c00d322bc7716d23670c4685ff5c1058ed8d8b97ccdfcf10643fe`; integrity/FK PASS. После upgrade версии0001/0002, backfill7 организаций, количества строк во всех прежних таблицах совпали. Migration fixtures отдельно проверяют точное сохранение строк, rollback DDL/данных/версии, конкурентный запуск и backup → restore в новый путь → upgrade.

Начальная сборка нашла пропущенную JSX-скобку logout — исправлено. Sandbox затем запретил esbuild (`spawn EPERM`); разрешённая локальная сборка прошла. Review исправил запрос запрещённых branches у unconfigured до browser-прогона. API/worker/preview и PostgreSQL-контейнер остановлены; порты3000/8000 свободны, базы/volumes сохранены. `.cache` и backups не входят в Git/ZIP.

**IN PROGRESS:** общая коммерческая подготовка. **TODO:** REAL/provenance, повторяемый импорт/corrections/reconciliation, далее stock ledger, heartbeat и эксплуатационные gates. [Матрица](../docs/commercial/RELEASE_GATES_RU.md) сохраняет полный незавершённый объём.

**BLOCKED:** реальные пилотные метрики требуют бизнеса; локальная разработка доступна. **NOT TESTED:** production HTTPS/deployment, нагрузка/SLA, независимый аудит, интерактивный CLI человеком, бизнес/экономия, device runtime/APK. Research benchmark и финальный ZIP не пересобирались. PostgreSQL backup verifier сравнивает полный набор migration markers, но pg_dump/restore повторно не запускался. REAL-импорт запрещён; production-ready не заявляется.

Ниже — история предыдущих блоков; её TODO/BLOCKED не заменяют актуальное состояние выше.

## Актуальное продолжение — пароли и PostgreSQL, 29.09.2026

Предыдущий блок классифицирован как **progress**: два коммита `e495268`, `1bba8ba` отправлены в origin/main, состояние проверено чистым. Общая цель выхода на рынок остаётся активной; [матрица коммерческих условий](../docs/commercial/RELEASE_GATES_RU.md) сохраняет её полный объём.

**DONE:** смена собственного пароля в web KK/RU для всех ролей и API `/account/password`; безопасная операторская CLI `scripts/manage_password.py` с dry preflight по умолчанию и скрытым двойным вводом при `--apply`. Замена пароля, отзыв web/native/refresh и отмена pending jobs атомарны; login/refresh берут ту же User-блокировку, чтобы старые credentials не пережили reset. Оператор указывает точную организацию/пользователя, свой ID и причину, не меняет active/role/branches. Ошибки валидации credential routes не возвращают входные секреты. API schema/OpenAPI и design map/copy обновлены; миграция не нужна.

**TESTED:** `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` — **157/157 PASS, 27.926 s**. `npm.cmd run build` — PASS, 1750 modules, 3.51 s после исправления accessible name. `npm.cmd run test:e2e -- tests/e2e/account_security.spec.ts tests/e2e/sessions_imports.spec.ts --reporter=line --output=.cache/account-security-e2e-final --timeout=30000` — **14/14 PASS, 21.8 s**, mock API. Реальный `workflow.spec.ts` на отдельной SQLite-базе/API/worker — **6/6 PASS, 33.3 s**, включая login → CSV validation/commit → sales → baseline/HGB forecast → procurement → approval/stale conflict → audit/export, branch scope, offline/network, KK/RU и смену пароля с отказом старого login/web/native/refresh. Скачанный CSV отдельно прочитан: 23 строки, approved version 2, SYNTHETIC, 12 purchase lines, целые packs, суммы строк соответствуют packs × pack_qty × unit_cost; итог 87513.2 при бюджете 150000.

Docker Desktop удалось запустить, использованы существующие образы без скачивания. `python -X utf8 scripts/verify_postgres_security.py` — **27/27 PASS** (tenant16 + worker11, 25.994 s), `python -X utf8 scripts/verify_postgres_security.py --suite test_password_security.py --report-name postgres-password-security.json` — **12/12 PASS, 11.585 s** на финальном password service. Реальный PostgreSQL **17.11**, новые тестовые базы и отдельная схема на тест; исходные operational DB/volumes не изменялись. Первоначальный PostgreSQL password12 прогон был повторён только после добавления защиты audit metadata. Это снимает предыдущую локальную Docker/PG блокировку. Артефакты: [postgres-security](../artifacts/verification/postgres-security.json), [postgres-password-security](../artifacts/verification/postgres-password-security.json).

Начальная browser-проверка новой формы выявила примешивание length hint к accessible name поля; исправлено `aria-labelledby`, повтор14 PASS. При просмотре mobile screenshot обнаружен кадр посередине CSS-перехода sidebar; capture и проверки закрытого/открытого меню уточнены. Результат отдельного responsive-повтора записывается в [account-security.json](../artifacts/verification/account-security.json). Трассы, screenshots с сессиями, credentials и тестовые БД остаются в `.cache`, вне Git/ZIP.

**IN PROGRESS:** коммерческая подготовка целиком, особенно tenant lifecycle, отдельная граница REAL/provenance, stock ledger и эксплуатация.

**TODO:** следующая конкретная часть — tenant model/bootstrap с миграцией, status/timezone/data policy и проверяемым первым доступом. Полный список неизменённых требований и evidence gaps — в release gates.

**BLOCKED:** бизнес-пилот и измерение эффекта требуют реального источника и согласований владельца; техническая разработка может продолжаться без них.

**NOT TESTED:** реальный HTTPS deployment, нагрузка/SLA, независимый security audit, email reset, интерактивный ввод recovery CLI человеком (в tests он имитируется), native экран смены пароля и device runtime, реальные бизнес-данные и эффект. APK, ZIP, research benchmark и production backup в этом блоке не пересобирались. REAL импорт по-прежнему запрещён.

## Предыдущий блок — локальная коммерческая основа, 29.09.2026

Пользователь поручил улучшать коммерческую основу без реального бизнеса. Работа продолжена от `f0b835496ae639149bd14adb7dddbddc1cf9f947` в существующей `main`. После сообщения о 15% недельного расхода пользователь разрешил текущий блок работ; прежняя остановка на 10% не означает отмену этого поручения.

**DONE:** права analyst приведены к чтению в API и web KK/RU; импорт ограничен ролью. Изменение доступа отзывает сессии и атомарно отменяет queued/running jobs с аудитом. Worker повторно проверяет организацию/филиал/роль и источник, не публикует отменённые или устаревшие вычисления, не раскрывает текст исключений. Добавлены проверки конфигурации до открытия БД, secure logout cookies, HSTS в production, безопасный отказ при некорректном Content-Length и запрет demo seed в production. Исправлены повреждённые CSV-заголовки и честность aggregate summary при частичном сканировании/дубликатах. Контракты обновлены; схема БД и модели прогнозирования не менялись.

**TESTED:** финальный `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` — **131/131 PASS, 28.061 s** (19 API, 14 engine, 4 backup, 16 config, 5 import parser, 10 packaging, 28 POS adapter, 3 research guards, 5 security settings, 16 tenant isolation, 11 worker security). `npm.cmd run build` — PASS, 1749 modules, 9.61 s. `npm.cmd run test:e2e -- tests/e2e/sessions_imports.spec.ts --reporter=line --output=.cache/commercial-e2e-rerun --timeout=30000` — **8/8 PASS, 10.0 s**, Chrome на собранном Vite preview, API замокан. Проверены роли, KK/RU read-only controls, session recovery и import/session races. Это не полный browser workflow с настоящим API. API suite содержит настоящий forecast → procurement → export; специальные worker race-тесты используют stub вычисления и реальные SQLite-транзакции. `python scripts/generate_contracts.py` и `git diff --check` — PASS. Проверка секретов без изменения старого отчёта: `python scripts/check_secrets.py --no-report` — 0 findings.

Первый CLI browser run не стартовал из-за `spawn EPERM`; расширенный запуск Chrome затем получил 8 failures из-за той же ошибки у sandbox Vite dev. Сервер заменён на уже собранный `npm.cmd run preview -- --strictPort --configLoader native`, повтор прошёл. Оба созданных для проверки web-процесса остановлены. В ходе разработки также исправлена коллизия имени settings с endpoint. Итоговые результаты относятся к исправленному коду. Подробности: [commercial-hardening.json](../artifacts/verification/commercial-hardening.json).

**IN PROGRESS:** коммерческая готовность в целом; текущий блок локальных исправлений закончен.

**TODO:** проверить новую сериализацию отзыва/публикации на PostgreSQL; полный browser workflow на обновлённых API/worker; отдельное создание tenant/первого администратора и сброс пароля; heartbeat для долгих задач. Следующие продуктовые этапы — multi-day forecast и журнал движения запасов с миграциями и отдельной проверкой научных допущений.

**BLOCKED:** текущий PostgreSQL runtime недоступен — Docker Desktop Linux engine pipe отсутствует. Реальный пилот требует предприятия и согласованных данных; их пока нет. Это не блокирует дальнейшую локальную разработку.

**NOT TESTED:** новые изменения на PostgreSQL, реальный HTTPS deployment, нагрузка и независимый аудит, полная browser цепочка с реальным API после этих изменений, обновлённый device runtime. APK, research benchmark и source ZIP в этом блоке не пересобирались; их старые артефакты не содержат текущие server/web изменения. REAL импорт по-прежнему запрещён.

## Исторический снимок — 25.09.2026

Следующие разделы сохранены как история. Их старые TODO, счётчики и ограничения запуска не заменяют актуальный статус выше. Android-отчёт и первый коммерческий data contract уже закоммичены до текущего блока.

Состояние: 25.09.2026, локальная работа возобновлена по прямому запросу пользователя. Codex Cloud отменён. Проект и Git history сохранены; текущее продолжение идёт в `main`, origin — PRIVATE `bltangenss/asboljam-diploma`.

## DONE

Прочитаны и сверены все 14 исходных приложений, включая дубликаты. Реализована цепочка login → CSV preview/validation/commit → sales → forecast worker → recipes/requirements/inventory → procurement MILP → manager decision → audit/export. Данные остаются SYNTHETIC, история до 31.12.2025, целевой день и snapshot 01.01.2026. Исходники Downloads не менялись.

| Этап | Реальное состояние |
|---|---|
| A — repository/environment/DB/auth | Git/private origin; SQLite и PostgreSQL17; migration0001; web/native auth, роли и scope реализованы |
| B — CSV/sales/references | Девять строгих схем, templates, preview/transaction/duplicates/oracle guards; продажи и справочники |
| C — forecast | Две baseline модели и HGB/quantiles; общий test, реальные метрики/provenance, отдельный worker |
| D — ingredients/inventory/procurement | Yield один раз, годные партии, integer packs/MOQ/budget/storage/lead time, Decimal recheck и явный дефицит |
| E — approval/audit/export | Причина/version/deficit acknowledgement; атомарное решение, idempotency и audit |
| F — frontend | Web KK/RU, responsive, loading/empty/error/offline/stale; графики, users/roles UI |
| G — regression/security | Python59, PostgreSQL19 и отдельные packaging10 PASS; реальный CUA workflow PASS в описанном объёме; CLI Playwright 0/11 заблокирован средой |
| H — Docker/deployment | Linux images и четыре сервиса проверены, 77 HTTP checks и отдельный pg_dump/restore PASS; production rollout не заявлен |
| I — enterprise adapter | Offline POS CSV mapping и 19 tests готовы; реальные данные/договор источника отсутствуют, importer SYNTHETIC-only |
| J — native | Expo55 client, typecheck, 13 session tests, Android JS export, локальные x86 и arm64-v8a debug APK PASS; устройство/Store release не проверялись |

## IN PROGRESS

- При текущем возобновлении пользователь установил порог: остановить работу и спросить о продолжении при **10% использованного лимита Codex** (90% остаётся). Перед Android-сборкой расход составлял 2%. Это лимит аккаунта, а не оценка готовности проекта.
- Создан пакет промптов для коммерческого развития в `docs/commercial_prompts/`: главный контекст и пять этапов от discovery/data contract до пилота и коммерческой приёмки. Это план следующей работы; реальные данные, multi-tenant production rollout и платный пилот ещё не выполнены.
- Этап 1 коммерческого плана начат локально: добавлены [договор данных](../docs/commercial/DATA_CONTRACT_RU.md), discovery-чеклист, пример POS mapping и безопасная aggregate quality summary в offline dry-run адаптера. Реальный источник, ссылки на справочники и application commit для `REAL` остаются вне текущей границы.
- После решения пользователя продолжить APK выполнены `scripts/build_android_debug.ps1 -Architecture x86` и `scripts/build_android_debug.ps1 -Architecture arm64-v8a`. [Текущий статус](../artifacts/verification/android-build.json): `passed` для arm64-v8a; APK скопирован в `releases/AsBoljam_Debug_arm64-v8a.apk`. x86-вариант сохранён как `releases/AsBoljam_Debug_x86.apk`.
- Синхронизация документации после Android APK. Финальный source ZIP остаётся `releases/AsBoljam_Final.zip`; APK не включается в source ZIP.

## TODO

Сделать commit и обычный push обновлённого Android-отчёта. Повторить полный Playwright suite после устранения запрета запуска его subprocess. При необходимости собрать release APK или `x86_64`; текущие APK — debug development builds под `x86` и `arm64-v8a`. Не повторять уже прошедшие тяжёлые проверки без изменений соответствующего кода.

Упаковщик по умолчанию берёт точные blobs чистого Git checkout. Явный `--working-tree` проверяет снимок tracked/untracked nonignored файлов и записывает `source_commit: null`, `base_commit: HEAD`, `includes_uncommitted_changes: true`; он не создаёт commit и не доказывает push. Фактические количество файлов и SHA256 финального архива фиксируются выводом упаковщика и sidecar после финального commit.

## BLOCKED

- Историческая блокировка `.git/index.lock` снята пользователем через полный доступ к рабочей среде. `git add` и новые локальные коммиты успешно создаются; итоговый hash и push фиксируются после документального коммита.
- `npm.cmd run test:e2e`: 0 из 11 тестов выполнено; `spawn EPERM` в `child_process.fork / WorkerHost.startRunner`. Расширенный повтор автоматически отклонён политикой `sandbox_approval=false`. [Результат](../artifacts/verification/browser.json). Отдельный успешный CUA workflow не является PASS полного Playwright suite.
- Для live enterprise/POS необходимы реальные обезличенные данные, контракт единиц/валюты и доступ к источнику; их не предоставляли. Offline adapter не является внедрением.
- iOS/Store release/signing требует целевой платформы и внешних аккаунтов. Эти действия не выполнялись.

## TESTED

| Команда / проверка | Подтверждённый результат |
|---|---|
| `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` | 59/59 PASS, 20.364 s; [python.json](../artifacts/verification/python.json) |
| `python scripts/verify_postgres.py` | PostgreSQL17.11, 19/19 API PASS, 24.341 s; [postgres.json](../artifacts/verification/postgres.json) |
| `python scripts/verify_runtime.py` | 77 HTTP checks PASS, nginx и отдельный worker; [runtime.json](../artifacts/verification/runtime.json) |
| `python scripts/verify_postgres_backup.py` | Новая restored DB, table counts/password hashes/migration marker совпали; [postgres-backup.json](../artifacts/verification/postgres-backup.json) |
| Docker Compose builds/runtime | PASS, services/health/API proxy/SPA fallback; [docker-state.json](../artifacts/verification/docker-state.json) |
| Windows `scripts/start.ps1`, `scripts/stop.ps1` | PASS, API/web200 и закрытые после stop порты; `-Install` отдельно не запускался |
| `npm run build` | TypeScript/Vite7.3.6 PASS, 1749 modules, 8.19 s; [web-build.json](../artifacts/verification/web-build.json) |
| `python scripts/run_research.py` | 9 forecasts/36 plans, 35.085184 s, все constraints_valid; код/данные SHA сохранены |
| Mobile `npm run typecheck`, `npm test` | PASS, 13/13, 455.844 ms; [mobile-source.json](../artifacts/verification/mobile-source.json) |
| Mobile `npm run export:android` | Metro/Hermes PASS, 588 modules, 20.831 s; это JS export, не APK |
| `scripts/build_android_debug.ps1 -Architecture x86` | PASS, Gradle `:app:assembleDebug` за 4m04s, APK 60911179 bytes, SHA256 `73a0e4c3a56fe7d2c95ea830771f8c4b4f9dc820502a4953f404d4af220e82b2`; [android-build-x86.json](../artifacts/verification/android-build-x86.json) |
| `scripts/build_android_debug.ps1 -Architecture arm64-v8a` | PASS, Gradle `:app:assembleDebug` за 4m54s, APK 59830847 bytes, SHA256 `fd9e925e090e05e2285351c02e86564bc2aa5b23bde47887af27b51e85f0f82d`; [android-build.json](../artifacts/verification/android-build.json) |
| APK integrity/signature | Для обоих APK ZIP CRC PASS, AndroidManifest present, 8 dex files; `apksigner verify --verbose --print-certs` PASS via APK Signature Scheme v2, debug certificate |
| `python -X utf8 -m unittest discover -s tests -p test_package_release.py -v` | Отдельные 10/10 PASS, 3.052 s; временные fixture-архивы, финальный ZIP не создан; [packaging-tests.json](../artifacts/verification/packaging-tests.json) |
| Codex in-app browser / CUA с реальным API и отдельным worker | PASS в перечисленном объёме: login → CSV validation/commit → sales → baseline forecast → procurement → approval → audit/download event; recipes/inventory, второй филиал, RU, dashboard 360 px, logout; [browser-cua.json](../artifacts/verification/browser-cua.json) |
| `python -X utf8 -m unittest discover -s tests -p test_pos_adapter.py -v` | 21/21 PASS после добавления aggregate quality summary; [commercial-stage1.json](../artifacts/verification/commercial-stage1.json) |
| Offline dry-run sales/inventory fixtures | Оба synthetic fixture PASS, диапазон дат, origin, units и `database_write=false` зафиксированы в [commercial-stage1.json](../artifacts/verification/commercial-stage1.json) |
| `python scripts/generate_contracts.py` | Manifest/design contracts синхронизированы с фактическим кодом |
| `python scripts/check_secrets.py` | Последняя проверка 154 candidate files, 0 findings; финальная проверка перед ZIP отдельно |

59 Python tests = 19 API + 14 engine + 4 backup + 19 POS adapter + 3 research-origin guards. Последнее исправление row lock при предоставлении доступа к импортированному филиалу уже включено в Python59/PostgreSQL19. После этих проверок соответствующий API/ML code не менялся, повторный тяжёлый прогон без причины не выполняется. Новые 10 packaging tests выполнены отдельно; общий набор из 69 тестов повторно не запускался.

CUA использовал собранный Vite preview с `--configLoader native`, новую ignored SQLite DB и настоящий worker, без mock API. Прогноз показал 28 исторических точек и 0 baseline-интервалов. План: 10 ингредиентов, 87513.2 ₸ при бюджете 150000 ₸, 0 дефицитных ингредиентов; причина решения видна в аудите. После проверки её browser/API/worker/preview остановлены; demo база не менялась.

## NOT TESTED

Полный текущий Playwright suite не выполнен из-за ограничения среды. В CUA не повторялись offline/network injection, stale approval race, analyst role и HGB chart; при нулевом дефиците не требовался deficit acknowledgement. Наблюдались download event и HTTP 200, но скачанные CSV bytes отдельно не проверялись. Снимок dashboard 360 px не является полным visual regression или accessibility audit. APK installation на устройство, Android/iOS device runtime, OS SecureStore, IPA/release signing/Store publishing, production TLS/load/SLA/monitoring и независимый security audit не проверены. `adb devices` не показал подключённых устройств. Cloud setup/verify именно в Codex Cloud не запускались; Cloud отменён. Windows launcher install branch и Linux desktop launchers целиком не проверялись. Production PostgreSQL restore отдельно от выполненного локального Docker restore не заявляется.

## История последней остановки и возобновления

Перед паузой шесть browser session/import-race checks прошли; workflow превысил 180 s, остальные четыре сценария не завершены. Пользователь остановил работу; серверы были выключены. При возобновлении trace показал 119.09 s ожидания прогноза и 25.97 s закупки; approval/export состоялись, общий timeout исчерпан при последующих UI/screenshots. Этот run остаётся FAILED/interrupted, а не PASS. Подробности: [browser-interrupted.json](../artifacts/verification/browser-interrupted.json).

Cloud handoff был подготовлен, но task не создан: штатный CLI сообщил `environment_repo_access_failed`. Пользователь затем отменил Cloud и явно возобновил локальный план. Эта облачная зависимость больше не является условием завершения локальной работы.
