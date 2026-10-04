# AsBoljam — итоговый технический отчёт

## 04.10.2026 — heartbeat длительных расчётов

**DONE:** migration0005 добавляет nullable jobs.heartbeat_at, сохраняя исходный started_at как идентификатор захвата. Worker продлевает текущую running-задачу каждые30 секунд отдельной короткой транзакцией; повторный захват использует heartbeat или старый started_at. Старый/отменённый обработчик не может продлить новый захват или опубликовать результат. Ошибки heartbeat обезличены. [Правила обновления и ограничения](docs/commercial/WORKER_OPERATIONS_RU.md).

**TESTED:** focused worker29/29 PASS, полный Python316/316 PASS (66.805s), PostgreSQL runner102/102 PASS (87 PG bodies,13 pure engine,2 SQLite backup;89 PG fixture schemas). Проверены фоновые heartbeat, конкуренция с reclaimer, утрата аренды, отказ старой публикации, rollback/concurrent migration и прежняя изоляция. Основная SQLite обновлена0005 после backup SHA256 e4f173286774e9e7e3428c3ee9b5ce5d0bbf01c88dceb0674c8a277034261701: прежние counts совпали, старые job columns совпали, выдуманных heartbeat0, integrity/FK PASS. [Отчёт](artifacts/verification/worker-heartbeat.json).

**NOT TESTED / TODO:** production kill/failover/load, ожидание30 минут реального времени, graceful drain/CPU cancellation и наблюдаемость. Expiry проверяется управляемыми часами. Web/API контракты не менялись, успешные browser/build/mobile без причины не повторялись. APK/ZIP не обновлены. Общая коммерческая цель не завершена: stock ledger, эксплуатация и бизнес-пилот остаются.

## Возобновление 04.10.2026 — проверки checkpoint закрыты

**TESTED:** сохранённый commit `569ae904ace910c1164cd376310ee7bb947e1573`: Python304/304 PASS (139.282s); ранее упавший live correction/recompute/approval/export —1/1 PASS (43.7s) на настоящих API/worker и отдельной SYNTHETIC-базе. PostgreSQL worker/REAL execution/API —42/42 PASS:29 PG bodies и13 pure engine tests;29 PG fixture schemas. Исходники во время проверки не менялись. [Команды и границы](artifacts/verification/resume-2026-10-04.json). Непроверенные в checkpoint последние worker/engine/API исправления теперь покрыты этими прогонами; единый новый прогон всех browser-сценариев не запускался.

**IN PROGRESS:** улучшение надёжности длительных фоновых расчётов. **NOT TESTED:** реальный бизнес/эффект, production deployment, свежий APK/ZIP. Неизменённые build/mock/mobile и независимые старые PG suites без причины не повторялись. Ниже сохранена история остановки; её pending-пункты читать с учётом этого обновления.

## Текущее дополнение — REAL-контракт и бизнес-даты, 29.09.2026

**Статус: сохранённая точка остановки по просьбе пользователя, не финальный release.** Python295/295 и PostgreSQL158/158 прошли до последних исправлений. Web build и mock37/37 PASS; live8/9, один сценарий требует повтора после исправления worker. Последние точечные проверки: contention6/6, worker security11/11, REAL execution19/19, REAL API12/12 PASS. Общая регрессия и PG/browser после последних изменений не повторялись.

**DONE:** migration0004 и однократная операторская регистрация источника на пустой организации; строгая отдельная политика REAL/SYNTHETIC. Preview/commit, расчёты, решение и экспорт сохраняют происхождение, источник, TEST/PILOT и даты. Web использует фактическую историю и snapshot; недостающие данные не заменяются нулём или демо. Исправлено восстановление worker после SQLite BUSY/LOCKED с сохранением результата и защиты от дублей. Основная SQLite обновлена после private backup с сохранением прежних counts и metadata организаций.

**TESTED:** точные команды, прогоны, повторные проверки найденных ошибок и source hashes — в [real-platform.json](artifacts/verification/real-platform.json), [PROGRESS](templates/PROGRESS.md). Использованы SYNTHETIC-демо и отдельно сгенерированный TEST-набор для REAL-контракта, а не данные предприятия.

**NOT TESTED:** бизнес-пилот/эффект, целевое HTTPS deployment, нагрузка/SLA, независимый аудит и новый device runtime. Native REAL намеренно недоступен до обновления клиента; APK/ZIP/research benchmark и полный PostgreSQL dump/restore после0004 не повторялись. **BLOCKED:** полевой пилот требует предприятия; оставшаяся техническая разработка доступна.

Общая коммерческая цель не завершена: нужны stock movement ledger, heartbeat/эксплуатация и остальные [release gates](docs/commercial/RELEASE_GATES_RU.md). Правила и ограничения текущего REAL-протокола: [runbook](docs/commercial/REAL_DATA_OPERATIONS_RU.md). Ниже сохранена история предыдущих блоков.

## Текущее дополнение — импорт, исправления и входные версии, 29.09.2026

**DONE:** migration0003, история источников и полученных хешей, идемпотентные квитанции, одинаковые строки без дубликатов, явные correction для продаж/календаря/остатков с причинами и версиями. Forecast/procurement сохраняют происхождение входов; изменившиеся данные блокируют новое утверждение до пересчёта. Ранее утверждённые планы, CSV и повтор ответа по тому же ключу неизменны. Web KK/RU показывает историю/изменения/ссылки на загрузку. Исправлен сброс формы пароля при фоновом обновлении settings.

**TESTED:** Python242/242 PASS; PostgreSQL runner109/109 PASS, из них108 PG и один SQLite backup/restore test. Build PASS; mock browser31/31 PASS. Live:7/8 прошли сразу; единственный тест с неоднозначным селектором preview исправлен и прошёл отдельным повтором1/1. Таким образом, проверены все8 разных live-сценариев, но единый финальный прогон8/8 не запускался. Основная SQLite обновлена с сохранением counts всех прежних таблиц после online backup. Новый mobile browser screenshot просмотрен. [Команды, изменения и ограничения](artifacts/verification/import-platform.json), [PostgreSQL](artifacts/verification/postgres-import-platform.json).

**NOT TESTED:** целевой HTTPS deployment, нагрузка/SLA, независимый аудит, реальные бизнес-данные/эффект и обновлённое устройство. APK/ZIP/research benchmark и pg_dump/restore после0003 не выполнялись. **BLOCKED:** полевой пилот требует предприятия; техническая разработка доступна.

Общая цель коммерческого выхода не завершена. Остаются REAL/date policy, полноценные складские движения и эксплуатационные [release gates](docs/commercial/RELEASE_GATES_RU.md). Коррекция snapshot не заменяет stock ledger. [Правила импорта](docs/commercial/IMPORT_OPERATIONS_RU.md). Ниже сохранена история предыдущих блоков.

## Текущее дополнение — организации и первый запуск, 29.09.2026

**DONE:** Organization с миграцией0002, сохранением прежних данных и metadata/status/policy; bootstrap пустой организации/первого admin без demo seed; suspend/resume с отзывом сессий/задач и аудитом. CLI проверяет конфигурацию/схему, использует preflight и скрытый пароль. Web показывает настройку без выдуманного филиала/истории; первый CSV обновляет доступ без logout. Подтверждённые нулевые продажи отличаются от отсутствующей истории.

**TESTED:** Python regression196/196 PASS, затем10/10 CLI после guard версии схемы; PostgreSQL runner64/64 PASS (63 PostgreSQL, один SQLite backup/restore case). Build PASS,22/22 mocked browser и7/7 live browser PASS, включая первый филиал и полный workflow настоящих API/worker. Основная SQLite обновлена после backup; количества строк прежних таблиц совпали. [Подробности](artifacts/verification/tenant-platform.json), [PG](artifacts/verification/postgres-tenant-platform.json).

**NOT TESTED:** целевой HTTPS deployment, нагрузка, независимый аудит, human-interactive CLI, device runtime, реальные данные/экономия. APK/ZIP/research не пересобраны; pg_dump/restore повторно не запускался после корректировки verifier под0002. **BLOCKED:** полевой пилот требует предприятия; локальная разработка продолжается.

Цель коммерческого выхода ещё не выполнена: остаются REAL/provenance, повторяемый импорт, stock ledger и другие [release gates](docs/commercial/RELEASE_GATES_RU.md). [Tenant runbook](docs/commercial/TENANT_OPERATIONS_RU.md) описывает фактические команды. Ниже — история предыдущих блоков.

## Текущее дополнение — пароли и завершённая локальная проверка, 29.09.2026

Реализована смена своего пароля в web KK/RU и API; добавлена операторская recovery CLI с точным tenant/user scope, скрытым вводом, причиной и отдельным audit actor. В одной транзакции меняется хеш и отзываются сессии/refresh/незавершённые задачи. Login/refresh блокируются согласованно с reset; credential validation не раскрывает значения. Схема БД не менялась.

**TESTED:** 157/157 Python PASS (27.926 s), web build PASS (3.51 s), 39/39 проверок на настоящем PostgreSQL17.11, 14/14 browser с mock API и 6/6 browser с настоящими API/worker. Live-сценарии охватили основной путь от CSV до approval/export, HGB, stale approval, роли/филиалы, сеть/локализацию и смену пароля с отказом старых сессий. Скачанный CSV проверен отдельно по содержимому и арифметике. [Отчёт и границы](artifacts/verification/account-security.json); [PostgreSQL isolation/worker](artifacts/verification/postgres-security.json), [PostgreSQL credentials](artifacts/verification/postgres-password-security.json).

**NOT TESTED:** целевое HTTPS deployment, реальные данные/эффект, нагрузка/SLA, независимый аудит, human-interactive recovery CLI и device runtime. Эти результаты относятся к локальным synthetic fixtures. Общая цель коммерческого выхода не завершена: остаются tenant bootstrap, REAL/import provenance, складские движения, эксплуатация, тарифный контур и пилотная приёмка. [Release gates](docs/commercial/RELEASE_GATES_RU.md) фиксируют полный оставшийся объём. APK/ZIP в этом блоке не обновлялись.

Предыдущие разделы ниже — история проверок, включая уже снятую блокировку PostgreSQL и прежнюю неполную browser проверку.

## Дополнение — 29.09.2026

По поручению улучшать проект без реального бизнеса укреплены API/web права, изоляция данных и выполнение фоновых задач. Analyst читает результаты, manager/admin создают расчёты; импорт ограничен ролью. Отзыв доступа отменяет незавершённые задания с аудитом, а worker не сохраняет результат отозванного/устаревшего запуска. Небезопасная production-конфигурация отклоняется до открытия БД; demo seed в этом режиме запрещён. Исправлены повреждённые CSV-заголовки, частичные отчёты проверки данных и утечка текста внутренних исключений worker. Добавлен [операторский runbook](docs/commercial/SECURITY_RUNBOOK_RU.md).

**TESTED:** финальный Python regression **131/131 PASS, 28.061 s**, web build PASS, **8/8 Chrome checks PASS, 10.0 s**. Браузерные тесты проверяют роли/сессии/гонки импорта на собранном сайте с mock API. Python API suite включает настоящий расчёт forecast/procurement/export; изоляция и конкурентная публикация проверены на SQLite. Начальные browser failures из-за sandbox `spawn EPERM` устранены переходом на built preview и разрешённым запуском Chrome. [Команды и границы проверки](artifacts/verification/commercial-hardening.json).

**NOT TESTED / BLOCKED:** новые изменения не проверены на PostgreSQL (Docker Desktop Linux engine недоступен), на реальном HTTPS deployment и через полный browser workflow с настоящим API. Независимый аудит, реальный пилот и device runtime отсутствуют. Production mode — проверка конфигурации, не разрешение REAL импорта и не статус коммерческой готовности. APK, ZIP и research benchmark в этом блоке не обновлялись.

Ниже сохранён исторический отчёт: его числа и PASS PostgreSQL/Docker/CUA относятся к указанным старым запускам. Актуальное состояние продолжения — в [PROGRESS](templates/PROGRESS.md).

Дата: 24.09.2026. Переданные пользователем материалы прочитаны и сверены; приложение создано в существующей рабочей папке без изменения оригиналов Downloads. Проект является работающим учебным MVP на **SYNTHETIC** данных. Проверки, ограничения и внешние зависимости перечислены явно; статус production ready не присваивается.

## Что реализовано — DONE

Полный путь данных: вход → CSV-шаблон/предварительная проверка → транзакционный импорт → продажи → фоновый прогноз → рецептуры и потребность → действительный запас → предложения → целочисленная закупка → просмотр → человеческое утверждение/отклонение → аудит → CSV.

Web поддерживает KK/RU, филиалы, responsive layout, загрузку/пустые результаты/ошибки, offline-индикацию, график истории и квантилей, метрики моделей, потребности и упаковки, пользовательские роли. Маршруты: `/login`, `/dashboard`, `/imports`, `/sales`, `/forecasts`, `/forecasts/:id`, `/recipes`, `/inventory`, `/suppliers`, `/procurement`, `/procurement/:id`, `/reports`, `/settings`, `/audit`.

Администратор создаёт пользователей, меняет роль, разрешённые филиалы и активность; изменения доступа отзывают серверные сессии. Организационные настройки преимущественно доступны только для чтения. Expo-клиент содержит вход, обзор, прогнозы, закупки, склад и профиль, онлайн-решения менеджера, offline/stale-состояния и refresh-token lifecycle. Импорт и создание вычислений выполняются через web.

## Архитектура

| Часть | Реализация |
|---|---|
| Web | React 19, TypeScript, Vite 7, собственный CSS |
| API | Python 3.13, FastAPI, Pydantic, SQLAlchemy, `/api/v1` |
| Worker | Отдельный Python-процесс, долговечная очередь, immutable input snapshot |
| БД | SQLite локально; PostgreSQL 17 + psycopg в Docker |
| Forecast | NumPy/scikit-learn, три модели, хронологическая проверка |
| Procurement | SciPy MILP, Decimal-проверка результата |
| Native | Expo 55, React Native 0.83, TypeScript, SecureStore |
| Deployment | PostgreSQL/API/worker/nginx, Docker Compose |

Сохранены выбранные React/Vite и очередь БД. Next.js, Alembic, Redis и Celery не требуются для запуска. Миграция 0001 собственная, версионированная. Операционные CSV хранятся валидированными JSON-записями; scope и натуральные ключи индексированы, ссылки проверяются импортом в транзакции. Это не полноценная ERP и не нормализованный бухгалтерский регистр.

## Структура проекта

- `apps/web`, `apps/api`, `apps/worker`, `apps/mobile` — приложения.
- `packages/api-client`, `packages/design-tokens` — общий клиент и токены оформления.
- `database`, `infra`, `docker-compose.yml` — миграции и контейнеры.
- `contracts`, `design` — OpenAPI, CSV manifest, словари интерфейса и карта экранов.
- `data/raw`, `research_only` — разрешённые synthetic CSV и отдельно изолированный oracle.
- `tests`, `scripts`, `artifacts` — воспроизведение, проверки, снимки интерфейса и результаты исследования.
- `docs/source_prompts`, `docs/SOURCE_REVIEW_RU.md` — исходные задания как материалы требований и аудит.
- `CLOUD_HANDOFF.md`, `AGENTS.md`, `templates` — продолжение разработки, решения, журнал ИИ и прогресса.

## Как запустить

Windows: `powershell -File scripts/start.ps1 -Install`, затем открыть `http://localhost:3000`. Повторный запуск: `scripts/start.ps1`; остановка: `scripts/stop.ps1`. Перед запуском порты 3000/8000 должны быть свободны. Скрипты читают локальный `.env`, устанавливают зависимости при `-Install`, мигрируют, выполняют seed и запускают API/worker/web. `.env.local` автоматически не читается.

Вручную: установить `requirements.lock` и `npm ci`, выполнить `python database/migrate.py` и `python scripts/seed_demo.py`, затем в трёх отдельных терминалах запустить `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000`, `python -m apps.worker.main`, `npm run dev`. API docs: `http://127.0.0.1:8000/docs`.

Docker: подготовить приватный `.env` с собственным URL-safe `POSTGRES_PASSWORD`, выполнить `docker compose up --build -d`, затем `docker compose exec api python scripts/seed_demo.py`. Для остановки без удаления базы: `docker compose stop`. `.env.example` содержит только безопасные названия/заглушки. Для HTTPS требуется `COOKIE_SECURE=true` и точный список `ALLOWED_ORIGINS`.

Подробности: [README.md](README.md), [README_KK.md](README_KK.md), [mobile README](apps/mobile/README_RU.md), [CLOUD_HANDOFF](CLOUD_HANDOFF.md).

## Demo credentials creation procedure

Seed создаёт `admin@asboljam.local`. На новой базе случайный пароль показывается в терминале один раз. Можно передать `DEMO_PASSWORD` длиной от 12 символов через окружение. Повторный seed не заменяет существующий пароль. Пароли, cookies и токены в Git/ZIP не включаются. Для своей передачи запускайте seed в новой базе, а не извлекайте чужие локальные credentials.

`prepare_e2e.py` создаёт отдельную тестовую организацию; случайные credentials хранятся только в игнорируемом `.cache`. Дополнительные пользователи для проверок имеют синтетические адреса.

## Dataset

Проверены все 14 приложений, включая дубликаты. В исходном ZIP: 26316 продаж, 3 филиала, 12 блюд, 10 ингредиентов, 48 рецептурных строк, 3 поставщика, 30 предложений, 60 партий, 2193 строки календаря. История: 01.01.2024–31.12.2025. Срез запасов и целевая дата: **01.01.2026**. Время компьютера не сдвигает данные.

Операционный импорт принимает девять известных схем. Oracle и generator-only поля исключены. `contracts/data_manifest.json` восстановлен из реальных CSV и валидатора; он не выдаётся за отсутствовавший исходный файл. PDF ссылается на непереданный готовый ZIP и отсутствующий регламент вуза; их содержание не выдумывалось. Формулы XLSX проверены, но не объявлены результатом MILP.

## Forecasting

Модели: `seasonal_naive_7`, `rolling_mean_28`, `hist_gradient_boosting`. Цель — наблюдаемые `units_sold`; неудовлетворённый латентный спрос не восстанавливается. Запрещены oracle, multiplier/base demand, будущие факты и audit-only поля того же дня.

Общий test: 04.12.2025–31.12.2025, 336 наблюдений на филиал. HGB fit для теста использует данные до 03.12; прошлые дни теста допустимы как лаги в последовательной однодневной оценке. Финальная модель переобучается до origin. Сохраняются MAE, RMSE, WAPE, bias, coverage/crossing, даты, seed, features, версии среды и SHA256 данных/кода. WAPE при нулевой сумме actual — null.

Baselines имеют null p10/p50/p90; HGB обучает настоящие квантильные модели. p10–p90 — номинальный **80%** интервал. Измеренная coverage трёх филиалов: 81.55%, 77.38%, 76.79%. HGB WAPE: 22.50%, 25.65%, 24.46%; seasonal naive: 32.45%, 34.64%, 33.05%. Это измерения данного synthetic набора, не производственная гарантия.

## Procurement

Потребность: forecast × net quantity per portion / yield factor; yield применяется один раз. Далее учитывается только точный snapshot_date и непросроченные партии. В демо партия со сроком годности в целевую дату считается годной. kg и L не смешиваются.

Целые упаковки, MOQ, max packs, стоимость базовой единицы, доступность поставщика по lead time, бюджет и складская вместимость входят в модель. Стоимость строки: packs × pack_qty × unit_cost_kzt. Двухэтапная оптимизация сначала минимизирует относительный дефицит, затем стоимость. Решение независимо проверяется через Decimal; при невозможном бюджете дефицит остаётся явным. `optimal` не равен «дефицита нет».

p90_stress — стресс-эвристика, не совместная вероятность обслуживания 90%. В 36 рассчитанных сценариях все ограничения соблюдены; в одном stress-сценарии филиала 3 при 200000 ₸ остаётся дефицит ингредиента. Источник: `artifacts/research`.

План утверждает/отклоняет manager/admin с expected_version, причиной, Idempotency-Key и отдельным подтверждением дефицита. Сравнение версии, запись решения и аудит атомарны. Утверждение не отправляет заказ поставщику.

## Security

HttpOnly web cookies, Origin/CSRF, ограничения частоты входа/изменений, хешированные пароли и токены; API контролирует организацию, филиал и роль. Native access хранится в памяти, refresh — в SecureStore, применяется ротация и отзыв семейства при повторном использовании. CSV export защищён от формул; импорт не меняет данные при ошибках. Секреты, БД, кэши, зависимости и browser traces исключены из Git/ZIP.

Проверка секретов ищет известные локальные значения и распространённые форматы ключей. Это не полноценный независимый security audit. Итоги npm audit относятся к проверенным web/mobile lockfiles и моменту проверки, не ко всем возможным уязвимостям.

## Tests — TESTED

| Команда / область | Подтверждённый результат |
|---|---|
| `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` | 59/59 PASS, 20.364 s: 19 API + 14 engine + 4 SQLite backup + 19 POS adapter + 3 research guards. [Отчёт](artifacts/verification/python.json). |
| `python scripts/verify_postgres.py` | PostgreSQL 17.11, реальный psycopg dialect; 19/19 API tests PASS, 24.341 s, отдельная новая БД. [Отчёт](artifacts/verification/postgres.json). |
| `python scripts/verify_runtime.py` | 77 HTTP checks PASS через nginx и отдельный worker. Собственные ограничения покрытия явно перечислены в [отчёте](artifacts/verification/runtime.json). |
| `python scripts/verify_postgres_backup.py` | pg_dump/restore в новую БД PASS; совпали количества всех таблиц, password hashes и marker миграции. [Отчёт](artifacts/verification/postgres-backup.json). |
| Docker Compose build/runtime | API/worker/web images собраны; PostgreSQL/API healthy; HTTP 200 для web, SPA fallback и API proxy. [Отчёт](artifacts/verification/docker-state.json). После проверки остановлено без удаления volumes. |
| `scripts/start.ps1`, `scripts/stop.ps1` | Реальный Windows launch/stop PASS, API/web 200, после остановки порты 3000/8000 закрыты. Ветка `-Install` отдельно не запускалась. [Отчёт](artifacts/verification/windows-launcher.json). |
| `python scripts/run_research.py` | 9 прогнозов + 36 закупочных сценариев, 35.085184 s, 36/36 constraints_valid; provenance и SHA256 сохранены. |
| Mobile `npm run typecheck`, `npm test` | PASS, 13/13 session tests, 455.844 ms. HTTP и SecureStore имитируются; OS encryption/device не проверены. [Отчёт](artifacts/verification/mobile-source.json). |
| `python -X utf8 -m unittest discover -s tests -p test_package_release.py -v` | Отдельные 10/10 packaging tests PASS, 3.052 s. Проверены временные fixture-архивы; финальный ZIP этим прогоном не создавался. [Отчёт](artifacts/verification/packaging-tests.json). |
| Браузерный сценарий через Codex in-app browser / CUA | PASS в указанном объёме на реальных локальных API и отдельном worker, без mock API. Проверены login, CSV validation/commit, sales, forecast, procurement, approval, audit, download event, KK/RU, второй филиал и dashboard 360 px. [Отчёт и ограничения](artifacts/verification/browser-cua.json). |

Успешные тяжёлые Python/API, Docker и research проверки выполнены до последней паузы и не повторяются без изменений связанных компонентов. Исправление `db.refresh(user, with_for_update=True)` уже входит в Python59 и PostgreSQL19 результаты. После возобновления отдельно выполнены 10 packaging tests и браузерный сценарий CUA; общий Python suite из 69 тестов заново не запускался.

Повторный `npm.cmd run test:e2e` заблокирован средой до запуска тестов: выполнено 0 из 11, `spawn EPERM` в `child_process.fork / WorkerHost.startRunner`. Расширенный повтор автоматически отклонён политикой `sandbox_approval=false`. Полного PASS набора Playwright нет; [browser.json](artifacts/verification/browser.json) сохраняет этот результат.

Отдельная проверка через CUA прошла на собранном Vite preview с `--configLoader native` и новой изолированной SQLite DB. Реальный worker создал baseline-прогноз с 28 историческими точками и без выдуманных интервалов, затем закупку с 10 ингредиентами: стоимость 87513.2 ₸ при бюджете 150000 ₸, дефицит 0. Подтверждены причина и статус утверждения, запись аудита, событие скачивания CSV, рецептуры/остатки, смена филиала, русский заголовок и отсутствие горизонтального переполнения dashboard при 360 px. Скачанные байты отдельно не исследовались; offline injection, stale approval race, analyst role, HGB chart и подтверждение дефицита в этом сценарии не проверялись. CUA не заменяет полный набор Playwright. После проверки её browser/API/worker/preview остановлены.

Исторический прерванный run: 6 session/import-race tests PASS, общий workflow timeout 180 s после вычислений/approval/export; ещё 4 сценария не завершены. Trace: ожидание прогноза 119.09 s, закупки 25.97 s. Для длинного сценария общий бюджет исправлен на 360 s; отдельные job и assertion limits сохранены. [Предыдущий результат](artifacts/verification/browser-interrupted.json) остаётся FAILED/interrupted.
## Build results

`npm run build` — TypeScript/Vite 7.3.6 PASS, 1749 modules, 8.19 s. JS 267880 bytes, CSS 28979 bytes; точные SHA256 output files — в [web-build.json](artifacts/verification/web-build.json). После этого web source не менялся; последняя правка касается только timeout теста.

`cd apps/mobile; npm run export:android` — Metro/Hermes PASS, 588 modules, 1.8 MB, 20.831 s. Это JS export, не APK. Expo prebuild прошёл без изменения package.json. Первоначальная Android debug build с JDK21/Gradle9 завершилась ошибкой совместимости foojay plugin: отсутствует `JvmVendorSpec.IBM_SEMERU`; [исходный результат](artifacts/verification/android-build-initial-failed.json) сохранён. Исправление resolver 1.0.0 прошло прежнюю точку отказа; следующая попытка дошла до CMake и ранее была остановлена пользователем.

После решения пользователя продолжить APK, `powershell -NoProfile -File scripts/build_android_debug.ps1 -JavaHome 'C:\Program Files\Java\jdk-21' -AndroidSdk '.cache/android-sdk' -Architecture x86` завершился PASS; Gradle `:app:assembleDebug` выполнился за 4m04s. Затем `-Architecture arm64-v8a` завершился PASS за 4m54s. Актуальный [android-build.json](artifacts/verification/android-build.json) фиксирует arm64-v8a: `releases/AsBoljam_Debug_arm64-v8a.apk`, 59830847 bytes, SHA256 `fd9e925e090e05e2285351c02e86564bc2aa5b23bde47887af27b51e85f0f82d`. x86-вариант сохранён как `releases/AsBoljam_Debug_x86.apk`, 60911179 bytes, SHA256 `73a0e4c3a56fe7d2c95ea830771f8c4b4f9dc820502a4953f404d4af220e82b2`, отчёт — [android-build-x86.json](artifacts/verification/android-build-x86.json). Для обоих APK: ZIP CRC PASS, `AndroidManifest.xml` есть, 8 dex files, `apksigner verify --verbose --print-certs` PASS по APK Signature Scheme v2 с debug certificate. Устройство не подключено и не проверялось.

Web/mobile npm audit после точечных overrides показал 0 vulnerabilities; это проверка lockfiles на момент запуска, не независимый security audit. Docker base image tags не закреплены immutable digest, поэтому будущий rebuild может получить другую patch-версию.
## Known limitations — NOT TESTED

Реальное предприятие и live POS/ERP, доказанная экономия, прогноз на 7/14/30 дней, складской ledger и смена активных рецептурных версий, автоматическая отправка заказов, платежи/налоги, production TLS/нагрузка/мониторинг/SLA и независимый security audit. Worker lease после аварии — 30 минут; длительным jobs потребуется heartbeat.

Полный текущий Playwright suite заблокирован средой; отдельный CUA сценарий имеет перечисленные выше ограничения. Android x86 и arm64-v8a debug APK собраны, но Android/iOS-устройство, OS SecureStore, release APK, IPA, магазинная публикация и release signing не проверены. `adb devices` не показал подключённых устройств. Codex Cloud отменён пользователем; cloud setup/verify сохранены, но там не выполнялись. Linux контейнеры не доказывают работу всех desktop launchers. Некоторые технические labels остаются английскими; полного WCAG-аудита нет.

## Что осталось сделать — BLOCKED / TODO

GitHub CLI авторизован в штатном Windows keyring. Подтверждён существующий PRIVATE origin [bltangenss/asboljam-diploma](https://github.com/bltangenss/asboljam-diploma); обычный `git push -u origin main` до `24d2dde` прошёл. История сохранена. Codex Cloud отменён. При последней попытке штатный Cloud CLI сообщил отсутствие доступа к репозиторию; Cloud task не создан. Это не блокирует локальные вычисления.

Историческая блокировка `.git/index.lock` снята пользователем через полный доступ к рабочей среде. `git add` и локальные коммиты снова работают. Итоговый commit и результат push фиксируются после завершения доставки; [git-delivery.json](artifacts/verification/git-delivery.json) разделяет исторический и текущий результаты.

Для реального предприятия нужны обезличенный экспорт, договор схемы, единиц/валюты и процедуры доступа. Offline adapter может подготовить данные, но текущий operational importer намеренно SYNTHETIC-only. Для native release нужны целевые платформы, устройство, release-сборка и при release signing — аккаунты владельца. Локальные debug APK не требуют Store account.

## Передача и архив

Финальный `releases/AsBoljam_Final.zip` создаётся после финального commit из чистого Git checkout. По умолчанию `python scripts/package_release.py` требует чистый checkout и упаковывает точные committed blobs. Явный `--working-tree` создаёт проверенный снимок tracked и untracked nonignored файлов с `source_commit: null`, `base_commit: HEAD` и `includes_uncommitted_changes: true`; такой архив не подтверждает commit или push. Перед записью упаковщик проверяет состав и неизменность байтов снимка и ищет секреты; существующие ZIP и sidecar не перезаписывает.

В ZIP включаются исходники, документы, миграции, тесты, scripts, безопасные demo данные, prompts, lockfiles и Docker configuration. `RELEASE_MANIFEST.json` фиксирует фактический режим и SHA256 каждого исходного файла; упаковщик проверяет CRC и все эти SHA256 после записи, создаёт `.zip.sha256`. `.git`, `.env`, credentials, БД/dumps, keystores, dependencies, caches и APK/IPA исключаются. 10 fixture-тестов упаковщика прошли; фактические количество файлов, SHA256 и результат проверки финального архива фиксируются выводом упаковщика и sidecar.
Актуальный рабочий журнал: [PROGRESS.md](PROGRESS.md). Архитектурные решения: [DECISIONS.md](DECISIONS.md).
