# AsBoljam — передача проекта для продолжения разработки

## 10.10.2026 — арифметика складских движений

**DONE (расчётный модуль):** явные партии, receipt/waste/adjustment/recipe_usage/reversal, gross decimal quantities, запрет отрицательного остатка и смены kg/L/expiry; неизвестная партия не выдаётся за ноль. Opening-сверка использует движения D..E−1 и сохраняет missing/mismatch. Рецептурный yield применяется один раз, дроби суммируются точно и округляются вверх до1e−9 только после агрегации.

**TESTED:** `python -X utf8 -m unittest discover -s tests -p test_stock_math.py -v` —15/15 PASS (2.697s). Review выявил несовместимость меток recipe_version с точками/пробелами; исправлено с проверкой реально принимаемого CSV. Первый прогон обнаружил Decimal Overflow при1E1000000; исправлена проверка через copy_abs, повтор прошёл. Проверены границы дат/сроков, рецептура, откат набора при плохой строке и различие нуля/неизвестного. [Отчёт](artifacts/verification/stock-math.json).

**IN PROGRESS / NOT TESTED:** это основа, не готовый складской продукт. API/UI/posting, датированная активация рецепта, интеграция procurement/lineage и live приёмка ещё не выполнены. Полные критерии сохранены в [плане складского контура](docs/commercial/STOCK_LEDGER_DESIGN_RU.md); цель выхода на рынок не завершена.

## 04.10.2026 — история и повторное открытие расчётов

**DONE:** история прогноза/закупки берётся с сервера, с фильтром выбранного филиала и типа, стабильным порядком created_at/id и страницами по20. После reload можно открыть выполняющуюся или сохранённую задачу без нового POST. Ошибка загрузки не маскируется пустой историей; есть повтор GET. `/runs` сохраняет role/org/branch isolation, лимит максимум50, no-store и безопасную проекцию без snapshot/payload.

**TESTED:** новые API7/7 SQLite (3.315s) и7/7 PostgreSQL; прежние API19/19 (20.683s), включая настоящий worker/forecast/procurement/export. Chrome9/9 (30.7s) с API-fixtures: reload для обоих типов, готовый результат, пагинация, ошибка истории и прежний polling. Web build PASS; screenshot desktop1440/mobile390 просмотрены, overflow отсутствует. До этого блока полный Python330 PASS+1 POSIX skip; после добавления истории повторены релевантные API/browser suites, а не весь неизменённый engine. [Отчёт](artifacts/verification/job-history.json).

**NOT TESTED:** новая live browser приёмка истории, production data/load/deployment, новый APK/ZIP. Stock ledger, CPU deadline/cancellation и бизнес-пилот остаются незавершёнными.

## 04.10.2026 — понятный статус расчёта и восстановление связи

**DONE:** web показывает очередь/выполнение/ошибку на KK/RU, возраст последнего heartbeat по серверным часам и предупреждение после90 секунд без ответа. Это не процент готовности и не доказательство прогресса CPU. Ошибка получения статуса позволяет повторить GET той же задачи без нового POST; failed прекращает polling и возвращает к параметрам только по кнопке. API сохраняет роль/org/branch scope, не раскрывает snapshot/payload и отдаёт no-store; OpenAPI/shared Run обновлены.

**TESTED:** SQLite4/4 и PostgreSQL4/4 для API статуса; Chrome5/5 для queue/heartbeat/KK/RU/offline retry/failed/missing result ID, без повторного POST. Desktop1440 и mobile390 проверены визуально и на отсутствие горизонтального overflow. Web build и mobile typecheck PASS. Финальная Python-регрессия331 случаев:330 PASS,1 POSIX skip,64.760s; реальный SIGTERM отдельно проверен в Linux ранее. [Отчёт](artifacts/verification/job-status.json).

**NOT TESTED / TODO:** браузерные новые сценарии используют детерминированные API-fixtures; новая единая live browser приёмка не запускалась. Сохранение выбора задачи после reload ещё не реализовано. Новый APK/ZIP не собраны; бизнес-пилот и deployment не подтверждены.

## 04.10.2026 — корректная остановка worker

**DONE:** первый SIGINT/SIGTERM останавливает получение новых задач, текущая завершается с heartbeat и публикацией. Захват на границе остановки возвращается в очередь с проверкой прежнего started_at; отменённые/новые захваты не затрагиваются. Ожидание SQLite claim-lock прерывается без нового вычисления; исходные signal handlers восстанавливаются, engine освобождается. Compose даёт120s на остановку.

**TESTED:** Windows worker suite35 случаев:34 PASS,1 POSIX skip. Linux/PostgreSQL25/25 PASS, включая настоящий SIGTERM дочернему процессу во время вычисления: результат сохранён, heartbeat работал, следующая задача осталась queued. Первый PG-отчёт оказался непарсируемым из-за stdout теста; runner теперь сохраняет stdout/stderr в результат suite, повтор25/25 прошёл. [Отчёт](artifacts/verification/worker-shutdown.json).

**NOT TESTED:** фактический Compose stop/redeploy, production failover/load. Второй сигнал/Windows force stop/SIGKILL могут оставить аренду для последующего восстановления; CPU cancellation и deadline не реализованы.

## 04.10.2026 — готовность БД и актуальная HTTP-приёмка

**DONE:** `/api/v1/health` сообщает только liveness, новый `/api/v1/ready` проверяет доступ к БД и точный набор миграций. При несовместимости/недоступности —503 с безопасным кодом, без строк подключения или tenant metadata; ответы no-store, проба не чинит схему. Compose healthcheck и ожидание cloud_verify используют ready. OpenAPI обновлён. HTTP-verifier теперь проверяет идемпотентный повтор commit, неизменённую повторную строку и отдельный запрет дублей внутри CSV; tenant SYNTHETIC подтверждается после login.

**TESTED:** readiness SQLite5/5 PASS; PostgreSQL5/5 PASS; API19/19 PASS, включая OpenAPI. Настоящие HTTP API+отдельный heartbeat worker на искусственной организации —87 checks PASS: login, scope/roles/CSRF, forecast, закупка, версия/причина/idempotency утверждения, аудит, CSV и атомарный повтор импорта. [Отчёт](artifacts/verification/readiness.json), [HTTP](artifacts/verification/runtime-current.json).

**NOT TESTED:** новый Docker/Cloud deployment, HTTPS/нагрузка, native/бизнес-эффект. Readiness не доказывает наличие worker или прогресс модели. Неизменённый web не пересобирался.

## 04.10.2026 — heartbeat длительных расчётов

**DONE:** migration0005 добавляет nullable jobs.heartbeat_at, сохраняя исходный started_at как идентификатор захвата. Worker продлевает текущую running-задачу каждые30 секунд отдельной короткой транзакцией; повторный захват использует heartbeat или старый started_at. Старый/отменённый обработчик не может продлить новый захват или опубликовать результат. Ошибки heartbeat обезличены. [Правила обновления и ограничения](docs/commercial/WORKER_OPERATIONS_RU.md).

**TESTED:** focused worker29/29 PASS, полный Python316/316 PASS (66.805s), PostgreSQL runner102/102 PASS (87 PG bodies,13 pure engine,2 SQLite backup;89 PG fixture schemas). Проверены фоновые heartbeat, конкуренция с reclaimer, утрата аренды, отказ старой публикации, rollback/concurrent migration и прежняя изоляция. Основная SQLite обновлена0005 после backup SHA256 e4f173286774e9e7e3428c3ee9b5ce5d0bbf01c88dceb0674c8a277034261701: прежние counts совпали, старые job columns совпали, выдуманных heartbeat0, integrity/FK PASS. [Отчёт](artifacts/verification/worker-heartbeat.json).

**NOT TESTED / TODO:** production kill/failover/load, ожидание30 минут реального времени, graceful drain/CPU cancellation и наблюдаемость. Expiry проверяется управляемыми часами. Web/API контракты не менялись, успешные browser/build/mobile без причины не повторялись. APK/ZIP не обновлены. Общая коммерческая цель не завершена: stock ledger, эксплуатация и бизнес-пилот остаются.

## Возобновление 04.10.2026 — проверки checkpoint закрыты

**TESTED:** сохранённый commit `569ae904ace910c1164cd376310ee7bb947e1573`: Python304/304 PASS (139.282s); ранее упавший live correction/recompute/approval/export —1/1 PASS (43.7s) на настоящих API/worker и отдельной SYNTHETIC-базе. PostgreSQL worker/REAL execution/API —42/42 PASS:29 PG bodies и13 pure engine tests;29 PG fixture schemas. Исходники во время проверки не менялись. [Команды и границы](artifacts/verification/resume-2026-10-04.json). Непроверенные в checkpoint последние worker/engine/API исправления теперь покрыты этими прогонами; единый новый прогон всех browser-сценариев не запускался.

**IN PROGRESS:** улучшение надёжности длительных фоновых расчётов. **NOT TESTED:** реальный бизнес/эффект, production deployment, свежий APK/ZIP. Неизменённые build/mock/mobile и независимые старые PG suites без причины не повторялись. Ниже сохранена история остановки; её pending-пункты читать с учётом этого обновления.

## Текущий этап — REAL-контракт и даты, 29.09.2026

**Остановлено с сохранением по просьбе пользователя.** Это checkpoint, не окончательно проверенный release. Python295 и PG158 прошли до последних исправлений; mock37 PASS; live8/9, один correction-сценарий требует повтора после исправления SQLite worker. Последние точечные проверки: contention6, worker security11, REAL execution19, REAL API12 PASS. Финальный общий/PG/browser повтор не выполнен. Запущенные тестовые сервисы остановлены, базы/volumes сохранены.

Работа выполнена локально в существующем проекте. Миграция0004 добавляет явную регистрацию источника для пустой организации; SYNTHETIC-демо и его даты сохранены. Web/API/worker/import/approval/export передают согласованные источник, timezone, origin и target. REAL требует законченный день, полную историю и точный известный остаток. Сгенерированный набор отмечен TEST; он не является данными предприятия. Native REAL пока возвращает явный403.

Исправлена остановка worker при временной блокировке SQLite: повтор транзакции сохраняет вычисленный результат и защиту от двойной публикации. Предыдущие строки основной БД после0004 сохранены; private backup проверен. Проверки и ограничения: [актуальный PROGRESS](templates/PROGRESS.md), [real-platform.json](artifacts/verification/real-platform.json), [runbook REAL](docs/commercial/REAL_DATA_OPERATIONS_RU.md).

Следующие участки — stock ledger, heartbeat и эксплуатационные gates; бизнес-пилот требует предприятия. Общая коммерческая цель не завершена. APK/ZIP/research этим блоком не обновлялись. Не повторять успешные тяжёлые проверки без изменения их исходников или конкретного сбоя. Ниже — история; старые утверждения о закрытом REAL относятся к прежним версиям.

## Текущий этап — история импорта и проверяемость расчётов, 29.09.2026

Работа продолжается локально. Миграция0003 добавляет provenance/receipts/revisions без переписывания прежних данных. Идентичные строки повторно не вставляются; sales/calendar/inventory исправляются явно, с причиной, версиями и атомарным commit. История следует текущим tenant/branch/role правам. Forecast/procurement сохраняют входные версии и ссылки на загрузки; перед утверждением изменённых данных нужен пересчёт. Старые утверждённые решения и экспорт сохраняются. [Runbook](docs/commercial/IMPORT_OPERATIONS_RU.md).

**Проверено:** Python242 PASS; PostgreSQL runner109 PASS (108 PG + один SQLite backup case); web build; mock browser31 PASS. Live — семь успешных сценариев в общем прогоне и успешный отдельный повтор восьмого после уточнения селектора preview. Настоящие API/worker проверили correction/stale/recompute/approval/export и HGB; [точные результаты](artifacts/verification/import-platform.json). Устранены неполная CSV-validation без предупреждения и сброс введённого пароля при обновлении metadata.

Основная SQLite0003 обновлена после private backup; прежние table counts совпали. Тестовые процессы остановлены, базы/volumes сохранены. Цель рынка остаётся активной: следующие участки — REAL/date policy, stock ledger, heartbeat и эксплуатация. REAL-импорт пока закрыт; APK/ZIP/research не обновлялись. Исторические результаты ниже не подменяют актуальный [PROGRESS](templates/PROGRESS.md).

## Текущий этап — организации и onboarding, 29.09.2026

Миграция0002 добавляет Organization и сохраняет прежние данные; реализованы bootstrap пустой организации/первого admin и suspend/resume. API/worker запрещают доступ отсутствующей или suspended организации, unconfigured оставляет настройку аккаунта. CLI требует явной БД, поддерживаемой схемы, preflight/apply и скрытого пароля. [Runbook](docs/commercial/TENANT_OPERATIONS_RU.md).

Web показывает реальные metadata и пустые состояния, обновляет доступ к первому филиалу без logout, не выдаёт демо-даты за отсутствующую историю. **Проверено:** полный Python196 PASS плюс финальный CLI10 PASS; PostgreSQL runner64 PASS (63 PG + один SQLite backup case); build, mock browser22 и live browser7 PASS. Команды и ограничения: [PROGRESS](templates/PROGRESS.md), [tenant-platform.json](artifacts/verification/tenant-platform.json), [PG](artifacts/verification/postgres-tenant-platform.json).

Тестовые процессы остановлены, базы/volumes сохранены. Основная SQLite обновлена после backup: прежние table counts совпали, backfill7 организаций. Следующие задачи — REAL/provenance, повторяемый импорт, stock ledger/эксплуатация. Цель рынка активна; REAL-импорт/deployment/экономия не подтверждены. APK/ZIP этим блоком не обновлялись. Ниже — история.

## Текущий этап — пароли и реальная PostgreSQL-проверка, 29.09.2026

Добавлены web/API смена своего пароля и `scripts/manage_password.py` для операторского восстановления. Пароли не принимаются CLI-аргументами и не возвращаются в validation errors; сессии и pending jobs отзываются атомарно. Login/refresh сериализованы с reset. [Runbook](docs/commercial/SECURITY_RUNBOOK_RU.md) содержит preflight/apply и ограничения; публичного email reset нет.

Текущие результаты: **157/157 Python PASS**, **39/39 real PostgreSQL security checks PASS**, web build PASS; **14/14 mock browser** и **6/6 live browser workflow PASS**, включая реальную смену пароля и HGB. PostgreSQL-блокировка из предыдущего блока снята запуском установленного Docker Desktop; новых образов не скачивали, существующие базы сохранялись. Проверки использовали новые тестовые БД/организации; реального клиента нет. Итоговые команды и уточнения responsive-повтора: [PROGRESS](templates/PROGRESS.md), [account-security.json](artifacts/verification/account-security.json).

Цель рынка остаётся активной. Следующий участок: tenant model/bootstrap, затем отдельная REAL/provenance граница и stock ledger. [Полная матрица незавершённых условий](docs/commercial/RELEASE_GATES_RU.md) не позволяет принять локальное демо за готовый коммерческий выпуск. Ниже — история предыдущих блоков, её старые BLOCKED/NOT TESTED читать с учётом этого обновления.

## Обновление 29.09.2026 — локальная коммерческая основа

Продолжена существующая `main` от `f0b8354`, без реального предприятия и без Cloud. API/web теперь соблюдают read-only роль analyst; worker не публикует результат после отмены/отзыва доступа или потери своей аренды. Добавлены проверки среды до подключения к БД, запрет production demo seed, безопасные ошибки и устойчивость CSV-парсера/quality summary. Организации с одинаковыми branch/entity IDs проверены раздельно. Публичной регистрации tenant и REAL импорта пока нет.

Текущая проверка: **131/131 Python PASS (28.061 s)**; web build PASS (9.61 s); **8/8 Chrome session/import/role tests PASS (10.0 s)** на production web bundle с mock API. Первые browser попытки были заблокированы/провалены из-за Vite dev `spawn EPERM`; финальный preview run прошёл. Настоящие API/SQLite/worker вычисления проверены Python API suite. Старые PostgreSQL/runtime/CUA отчёты ниже относятся к предыдущему коду и не доказывают новые изменения на этих средах.

Следующий технический шаг: проверить отзыв/публикацию на PostgreSQL и полный browser workflow обновлённого API/worker. Docker Desktop сейчас не запущен (Linux engine pipe отсутствует). Затем — проверяемое создание организации/первого администратора, reset password, heartbeat долгих задач. Реальные данные не нужны для этих локальных работ; пилотные метрики требуют бизнеса.

Команды, ограничения и результаты: [актуальный PROGRESS](templates/PROGRESS.md), [отчёт проверки](artifacts/verification/commercial-hardening.json), [runbook среды и доступа](docs/commercial/SECURITY_RUNBOOK_RU.md). APK и ZIP не пересобирались в этом блоке. Следующий текст — исторический снимок с уточнениями последующих этапов.

Снимок состояния: 24.09.2026. Продолжать существующий код; не начинать проект заново. Этот файл описывает выполненную работу и воспроизводимые команды. Создание файла не означает подключения Codex Cloud или успешного deployment. Последующие результаты фиксируются в [PROGRESS](templates/PROGRESS.md).

## 1. Название проекта

**AsBoljam** — дипломная система планирования продаж, ингредиентов и закупок для общественного питания.

## 2. Цель проекта

Довести до проверяемого рабочего состояния цепочку: CSV → предварительная валидация → транзакционный импорт → продажи → однодневный прогноз → рецептуры → потребность → годный запас → предложения → MILP → план → решение менеджера → аудит → экспорт. Основной язык UI — казахский; русский переключатель уже реализован. По актуальному решению пользователя разработка и проверки выполняются локально; Codex Cloud отменён.

## 3. Текущая архитектура

| Часть | Реализация | Расположение |
|---|---|---|
| Web | React 19, TypeScript, Vite, CSS, lucide | `apps/web`, порт 3000 |
| API | FastAPI, Pydantic, SQLAlchemy | `apps/api`, порт 8000, `/api/v1` |
| Worker | Отдельный процесс, долговечная очередь в БД | `apps/worker` |
| Forecast + optimization | NumPy, scikit-learn HistGradientBoosting, SciPy MILP | `apps/api/engine.py` |
| Хранилище | SQLite локально; PostgreSQL 17 в Compose | `apps/api/db.py`, `database` |
| Native | Expo 55 / React Native, общий API | `apps/mobile` |
| Контракты | OpenAPI и восстановленный manifest исходных CSV | `contracts` |
| Исследование | Реальные расчёты на синтетическом наборе | `artifacts/research` |

Next.js, Tailwind, Alembic, Redis и Celery не используются. Рабочий стек сохраняется: SPA, собственная версионированная миграция и очередь в базе — осознанные решения, а не отсутствующие импорты. Python 3.13; Node.js 24. Python lock: `requirements.lock`; npm lockfiles находятся в корне и `apps/mobile`.

## 4. Что реально реализовано

- Cookie-сессии web с Origin/CSRF, хеширование паролей, роли и ограничения организации/филиала; короткие native access tokens, ротация refresh и отзыв семейства.
- Девять разрешённых типов CSV, типы/диапазоны/ссылки/единицы, preview, атомарный commit, запрет дублей и лишних колонок; защита CSV-экспорта от формул.
- Продажи с фильтрами, рецепты, складские партии, предложения поставщиков; web-страницы основных маршрутов и состояния загрузки/ошибки/пустых данных.
- Все три модели; общий временной тест, настоящие метрики и provenance; отдельный worker сохраняет снимок входных данных и результат.
- MILP с целочисленными упаковками, MOQ, верхними пределами, бюджетом, вместимостью и доставкой в день сценария; повторная проверка решения через Decimal.
- Версионированные решения менеджера, явное подтверждение дефицита, идемпотентность, конкурентное утверждение, аудит, экспорт потребностей и строк закупки.
- SQLite online backup/restore с контрольной суммой и проверкой целостности; воспроизводимый исследовательский скрипт.
- Компонент `ForecastChart.tsx`: выбор блюда, 28 датированных фактических продаж, отдельная точка следующего дня и только реальные квантильные интервалы.
- Исходники native-клиента, SecureStore и проверки сессий; локальные Android x86 и arm64-v8a debug development APK собраны. Это не подписанный release APK/IPA и не проверка устройства.

## 5. Что только специфицировано или ещё отсутствует

Реальные данные предприятия и live-интеграция POS/ERP, подтверждённая экономия, прогнозы 7/14/30 дней, полноценный журнал движения запасов, автоматическая отправка заказов, production-наблюдаемость и SLA, подписанные магазинные сборки. UI организации сейчас преимущественно только для чтения. Offline CSV mapping реализован для sales/inventory: [POS_ADAPTER_RU.md](docs/POS_ADAPTER_RU.md). Он сохраняет происхождение REAL/SYNTHETIC; приложение пока намеренно не принимает REAL. Нет заявлений об интервью, внедрении или доступе к внешним аккаунтам.

## 6. Какие проверки действительно проходили

Подтверждённые отчёты находятся в `artifacts/verification`, итоговая матрица — в [FINAL_REPORT.md](FINAL_REPORT.md).

- Python: 59/59 PASS за 20.364 s (19 API, 14 engine, 4 backup, 19 POS adapter, 3 research-origin guards).
- PostgreSQL 17.11: 19/19 API tests PASS за 24.341 s на отдельной новой тестовой БД. Все девять операционных CSV загружены; дополнительная строка smoke-import объясняет 26317 продаж в runtime при 26316 в исходнике.
- Внешний HTTP через nginx и отдельный worker: 77 проверок PASS. Это отдельное свидетельство от проверки фактического PostgreSQL dialect.
- pg_dump/pg_restore: восстановление в новую БД PASS; совпали количества всех таблиц, password hashes и marker миграции. Полный хеш содержимого всех таблиц не сравнивался.
- Linux Docker images построены; проверены API/PostgreSQL health, web/worker и HTTP 200 для SPA fallback/API proxy. После проверки контейнеры остановлены без удаления volumes.
- Web TypeScript/Vite build PASS: 1749 modules, 8.19 s. Mobile typecheck и 13 session tests PASS; Metro/Hermes Android JS export PASS (588 modules, 20.831 s). После решения пользователя продолжить APK собраны Android debug development APK: x86 — 60911179 bytes, SHA256 `73a0e4c3a56fe7d2c95ea830771f8c4b4f9dc820502a4953f404d4af220e82b2`; arm64-v8a — 59830847 bytes, SHA256 `fd9e925e090e05e2285351c02e86564bc2aa5b23bde47887af27b51e85f0f82d`.
- Research: 9 прогнозов и 36 закупочных сценариев, 35.085184 s, сохранены provenance и SHA256.
- Windows start/stop реально выполнены: API/web 200, после остановки порты закрыты. Ветка `-Install` launcher отдельно не запускалась; зависимости устанавливались самостоятельными командами.
- После возобновления: отдельные 10/10 packaging tests PASS, 3.052 s; общий Python suite из 69 тестов повторно не запускался. Проверены временные fixture-архивы, финальный ZIP не создан. [Отчёт](artifacts/verification/packaging-tests.json).
- Реальный браузерный сценарий через Codex in-app browser / CUA PASS в перечисленном объёме: login, CSV validation/commit, sales, baseline forecast через отдельный worker, procurement, approval, audit/download event, recipes/inventory, второй филиал, RU, dashboard 360 px и logout. Использованы собранный Vite preview с `--configLoader native` и отдельная ignored SQLite DB; mock API нет. [Результат и ограничения](artifacts/verification/browser-cua.json).

Полный Playwright suite и device/native release имеют отдельные статусы ниже; CUA workflow не заменяет полный набор браузерных тестов. Успешные тяжёлые расчёты не повторяются без изменений связанных компонентов.
## 7. Какие проверки падали или пока не подтверждены

Повторный `npm.cmd run test:e2e` заблокирован средой до старта тестов: выполнено 0 из 11, `spawn EPERM` в `child_process.fork / WorkerHost.startRunner`. Расширенный повтор автоматически отклонён политикой `sandbox_approval=false`. [browser.json](artifacts/verification/browser.json) сохраняет результат; полного Playwright PASS нет.

Предыдущий связанный Playwright run был прерван по запросу пользователя: шесть session/import-race проверок PASS, сквозной workflow превысил общий timeout 180 s, ещё четыре сценария не завершены. Сохранённый trace подтверждает 119.09 s ожидания прогноза и 25.97 s ожидания закупки; approval/export выполнены, общий лимит исчерпан далее в UI. Для длинного теста выделено 360 s при сохранении отдельных job/assertion limits. [Старый прерванный прогон](artifacts/verification/browser-interrupted.json) не считается PASS.

CUA workflow имеет ограниченный объём: скачивание подтверждено download event и HTTP 200, но bytes отдельно не проверялись; offline injection, stale approval race, analyst role и HGB chart не повторялись. В рассчитанном плане нет дефицита, поэтому отдельный checkbox подтверждения дефицита не требовался. Нет полного visual regression/accessibility audit. После CUA проверки её browser/API/worker/preview остановлены.

Первая Android debug build после успешного Expo prebuild завершилась ошибкой foojay plugin `JvmVendorSpec.IBM_SEMERU` на JDK21/Gradle9; [исходный результат](artifacts/verification/android-build-initial-failed.json) сохранён. Resolver 1.0.0 устранил эту ошибку; следующая попытка дошла до CMake и ранее была остановлена пользователем. 25.09.2026 build возобновлён: `scripts/build_android_debug.ps1 -Architecture x86` завершился PASS за 4m04s, затем `scripts/build_android_debug.ps1 -Architecture arm64-v8a` завершился PASS за 4m54s. [android-build.json](artifacts/verification/android-build.json) фиксирует актуальный arm64-v8a result; x86 сохранён в [android-build-x86.json](artifacts/verification/android-build-x86.json). Копии для передачи: `releases/AsBoljam_Debug_arm64-v8a.apk` и `releases/AsBoljam_Debug_x86.apk`. Устройство не проверено.

Codex Cloud не запускался и теперь отменён пользователем. Android device runtime, release APK, production TLS/load/SLA и реальные данные предприятия требуют собственных результатов; их нельзя выводить из Python tests, Compose configuration, Metro export или debug APK.
## 8. Как запустить frontend

Из корня, Node.js 24:

```sh
npm ci
npm run dev
```

Открыть `http://localhost:3000`. Vite перенаправляет `/api` на локальный API. Для полного локального запуска есть `scripts/start.ps1 -Install` на Windows и `bash scripts/start.sh --install` на Linux/macOS. Они запускают API, worker и web отдельно; логи — `.cache/logs`. Не запускать второй набор процессов на занятых портах.

## 9. Как запустить backend

```sh
python -m venv .venv
# Linux: source .venv/bin/activate
# PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python database/migrate.py
python scripts/seed_demo.py
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

По умолчанию создаётся `data/asboljam.sqlite`; исходные CSV не изменяются. API docs: `http://127.0.0.1:8000/docs`. Seed создаёт `admin@asboljam.local` и показывает сгенерированный пароль один раз либо берёт `DEMO_PASSWORD` из окружения. Повторный seed сохраняет существующий пароль. Значения секретов не добавлять в документы/Git. При ручном запуске Python `.env` автоматически не исполняется: переменные должны быть установлены в окружении; штатные launchers читают безопасные присваивания из `.env`.

## 10. Как запустить worker

В отдельном терминале, с тем же Python и `DATABASE_URL`:

```sh
python -m apps.worker.main
```

Для обработки не более одной задачи: `python -m apps.worker.main --once`. Состояния queued/running/succeeded/failed хранятся в БД. Lease упавшей задачи — 30 минут; для более долгих вычислений нужны heartbeat/продление lease. Worker не отправляет сообщения или заказы поставщикам.

## 11. Как поднять PostgreSQL/Redis

```sh
docker compose up -d postgres
docker compose exec postgres pg_isready -U asboljam -d asboljam
```

Сначала создать локальный `.env` из `.env.example`, не перезаписывая существующий, и задать собственный URL-safe `POSTGRES_PASSWORD`. В Compose PostgreSQL доступен внутри сети сервиса; порт 5432 наружу не опубликован. Для внешнего PostgreSQL установить одинаковый `DATABASE_URL=postgresql+psycopg://...` перед миграцией, API и worker. Redis не нужен и отсутствует: queue работает на транзакциях БД. PostgreSQL backup/restore выполняются его `pg_dump`/`pg_restore` и требуют отдельной проверки на целевом сервере.

## 12. Как запустить Docker Compose

После установки Docker с работающим Linux engine и подготовки приватного `.env`:

```sh
docker compose config --quiet
docker compose up --build -d
docker compose exec api python scripts/seed_demo.py
docker compose ps
docker compose logs --tail=100 api worker web
```

Web — `http://localhost:3000`, API — `http://127.0.0.1:8000`. Seed выведет пароль только в терминале оператора. Остановка без удаления данных: `docker compose stop`. Не использовать `down -v` для работающей базы. Для параллельной проверки предусмотрен `infra/compose.verify.yml` с 3010/8010; он требует версию Compose с `!override`. Успешное создание конфигурации не равно успешной сборке образов или проверке PostgreSQL.

## 13. Как запускать тесты

```sh
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
npm run build
cd apps/mobile
npm ci
npm run typecheck
npm test
```

Для браузера вернуться в корень, поднять API/worker/web, выполнить `python scripts/prepare_e2e.py`, затем `npm run test:e2e`. Подготовка создаёт отдельную синтетическую организацию; credentials только в игнорируемом `.cache/e2e-login.json`. По умолчанию локальный Playwright использует Chrome; в Linux установить Chromium и задать `PLAYWRIGHT_CHANNEL=chromium`. Трассы с сессиями не публиковать.

Для Linux cloud: `bash scripts/cloud_setup.sh`, затем `bash scripts/cloud_verify.sh`. Verify создаёт новую БД в `.cache/cloud`, выполняет Python-тесты, web build, mobile type/tests, research, отдельные процессы API/worker/web и Playwright; завершает только запущенные им процессы. Можно явно отключить отдельные группы переменными `ASBOLJAM_VERIFY_MOBILE=0`, `ASBOLJAM_VERIFY_RESEARCH=0`, `ASBOLJAM_VERIFY_E2E=0`; отключённое не считается PASS.

## 14. Как выполнить build

Web: `npm run build`, результат `dist/web`, preview: `npm run preview`. Native TypeScript check не создаёт APK/IPA. Локальный debug APK собирается командой `powershell -NoProfile -File scripts/build_android_debug.ps1 -JavaHome 'C:\Program Files\Java\jdk-21' -AndroidSdk '.cache/android-sdk' -Architecture arm64-v8a`; для x86-эмулятора заменить architecture на `x86`. Результат development build требует Metro для JavaScript. Android device или macOS/Xcode, release signing и Store publication проверяются отдельно. Docker image build: `docker compose build` после подготовки окружения. Нельзя объявлять native/cloud deployment по успешному web build.

## 15. Demo datasets

`data/raw`: branches (3), meals (12), ingredients (10), recipes (48), suppliers (3), supplier_offers (30), calendar (2193), daily_sales (26316), inventory_lots (60). Период продаж: 2024-01-01–2025-12-31; 3 филиала и 12 блюд. `metadata.json`/`data_dictionary.csv` описывают набор. `contracts/data_manifest.json` восстановлен из фактических файлов и importer; оригинального manifest в переданных материалах не было. Хеши, реальные метрики и закупочные сценарии — `artifacts/research/provenance.json` и CSV рядом.

## 16. Что является SYNTHETIC

Все исходные продажи, цены, рецептуры, остатки, сроки, события и контрагенты — искусственные демонстрационные записи, seed 42. Сценарий — 01.01.2026, не текущая дата компьютера. Исследовательские метрики действительно вычислены, но характеризуют только этот набор. Нельзя выводить из них реальные проценты экономии, производственную безопасность или фактические результаты предприятия.

## 17. Что запрещено в ML

`research_only`, `oracle_do_not_train.csv`, `latent_demand_ORACLE_ONLY`, `branches.demand_multiplier`, `meals.base_daily_demand`, будущие actual и признаки того же дня вроде available_portions/stockout. Реальные features перечислены в metadata. Общий тест: 04.12.2025–31.12.2025, 336 наблюдений на филиал. Параметры HGB в тесте обучены до 03.12; предыдущие тестовые дни доступны как прошлые лаги при однодневной оценке. Финальный HGB переобучается до forecast origin. Baselines не имеют искусственных интервалов; p10–p90 — номинальные 80%.

## 18. Известные ограничения

- MVP прогнозирует observed sales на один день; не восстанавливает неудовлетворённый спрос.
- Операционные данные хранятся валидированными JSON-строками с indexed scope/natural keys; это не нормализованная бухгалтерская/складская ERP. Миграция сейчас только 0001.
- Фиксированный синтетический сценарий; свежий реальный план требует реального адаптера и актуальных снимков. Нет оплаты, налогов, доставки, единиц кроме поддержанных kg/L в procurement.
- p90_stress не даёт совместной гарантии 90%. В измеренном stress-сценарии филиала 3 при 200000 ₸ остаётся один дефицитный ингредиент.
- Web cookie secure=false допустим только локально; для HTTPS задать COOKIE_SECURE=true и конкретные ALLOWED_ORIGINS. TLS, мониторинг, нагрузка и production-backup проверяются отдельно.
- PRIVATE origin подтверждён: `https://github.com/bltangenss/asboljam-diploma`; push main до `24d2dde` прошёл. Cloud environment не подтверждается наличием remote или скриптов. Не записывать токены в проект.
- Историческая блокировка `.git/index.lock` снята пользователем через полный доступ к рабочей среде; локальные коммиты снова создаются. Итоговый hash и push фиксируются после завершения доставки.
- Windows-проверки не доказывают Linux/macOS/Android/iOS совместимость. Подробный перечень NOT TESTED сохранять в progress.

## 19. Следующий этап разработки и статус Cloud

Пользователь отменил Codex Cloud и возобновил полностью локальную разработку. Продолжать существующий PRIVATE repository `bltangenss/asboljam-diploma`, branch `main`; актуальный список выполненного и оставшегося — [PROGRESS](templates/PROGRESS.md). Основной CUA workflow уже проверен; полный Playwright suite требует снятия ограничения на subprocess. Android x86 и arm64-v8a debug APK собраны; следующий native шаг — установка на устройство/эмулятор или отдельная release-сборка, если потребуется. Не повторять успешные тяжёлые проверки без связанных изменений.

Финальный `releases/AsBoljam_Final.zip` создаётся после финального commit из чистого Git checkout. `python scripts/package_release.py` по умолчанию требует чистый checkout и упаковывает точные committed blobs. Явный `--working-tree` проверяет снимок tracked/untracked nonignored файлов и фиксирует `source_commit: null`, `base_commit: HEAD`, `includes_uncommitted_changes: true`; это не commit/push. Оба режима проверяют CRC и SHA256 исходных файлов после записи, исключают секреты/БД/dependencies/caches и не перезаписывают существующие ZIP/sidecar. Фактические число файлов и SHA256 фиксируются выводом упаковщика и sidecar.
Cloud task не создан: штатный CLI при обращении к этому репозиторию вернул `environment_repo_access_failed`. Поскольку Cloud отменён, это не блокирует локальную разработку и не требует авторизации пользователя сейчас.

Скрипты для возможного будущего Linux Cloud сохранены, но там не выполнялись: Python 3.13, Node.js 24, setup `bash scripts/cloud_setup.sh`, переменные `LOKY_MAX_CPU_COUNT=1`, `PLAYWRIGHT_CHANNEL=chromium`; приложение не требует OpenAI API key. Проверки этого варианта запускаются командой `bash scripts/cloud_verify.sh` только при отдельном решении использовать соответствующую среду. [Официальная документация среды](https://learn.chatgpt.com/docs/environments/cloud-environment).
## 20. Условия полной готовности

Для демонстрационного выпуска: чистый checkout устанавливается, миграция/seed воспроизводимы, API и настоящий worker проходят полную пользовательскую цепочку, роли/изоляция/CSRF/идемпотентность/конкурентное утверждение проверены, график/метрики/дефицит/единицы корректны, backups восстанавливаются, web build и нужные native проверки подтверждены. После изменения кода связанные проверки повторены, статусы честны, безопасный финальный ZIP читается и включает исходники/контракты/данные/lockfiles.

Для cloud handoff: приватный remote и push реально подтверждены, владелец дал доступ cloud к репозиторию, setup и verify выполнены именно в cloud, результат/ссылка на задачу записаны. Для production дополнительно нужны реальный адаптер, эксплуатационные ограничения, HTTPS, нагрузочные/security проверки, мониторинг и восстановление PostgreSQL. Эти условия не считаются выполненными только потому, что создан локальный Git.

