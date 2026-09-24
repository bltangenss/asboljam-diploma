# AsBoljam — передача проекта для продолжения разработки

Снимок состояния: 24.09.2026. Продолжать существующий код; не начинать проект заново. Этот файл описывает выполненную работу и воспроизводимые команды. Создание файла не означает подключения Codex Cloud или успешного deployment. Последующие результаты фиксируются в [PROGRESS](templates/PROGRESS.md).

## 1. Название проекта

**AsBoljam** — дипломная система планирования продаж, ингредиентов и закупок для общественного питания.

## 2. Цель проекта

Довести до проверяемого рабочего состояния цепочку: CSV → предварительная валидация → транзакционный импорт → продажи → однодневный прогноз → рецептуры → потребность → годный запас → предложения → MILP → план → решение менеджера → аудит → экспорт. Основной язык UI — казахский; русский переключатель уже реализован. Перенос в облачную среду нужен для продолжения разработки, а не подменяет готовность продукта.

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
- Исходники native-клиента, SecureStore и проверки сессий; наличие исходников не означает установленный APK/IPA.

## 5. Что только специфицировано или ещё отсутствует

Реальные данные предприятия и live-интеграция POS/ERP, подтверждённая экономия, прогнозы 7/14/30 дней, полноценный журнал движения запасов, автоматическая отправка заказов, production-наблюдаемость и SLA, подписанные магазинные сборки. UI организации сейчас преимущественно только для чтения. Offline CSV mapping реализован для sales/inventory: [POS_ADAPTER_RU.md](docs/POS_ADAPTER_RU.md). Он сохраняет происхождение REAL/SYNTHETIC; приложение пока намеренно не принимает REAL. Нет заявлений об интервью, внедрении или доступе к внешним аккаунтам.

## 6. Какие проверки действительно проходили

Подробная итоговая матрица команд и фактических длительностей находится в [FINAL_REPORT.md](FINAL_REPORT.md), текущее состояние итерации — в [PROGRESS](templates/PROGRESS.md). Машиночитаемые отчёты — `artifacts/verification`; это результаты выполненных команд, а не описание будущих проверок.

На момент этой записи подтверждены: Python API/engine/backup (36 тестов одним прогоном), POS adapter (19 тестов отдельно), research-origin guard (3 теста отдельно), mobile session (13 тестов), web TypeScript/Vite и Android Metro/Hermes JS export. Первый полный браузерный workflow и четыре дополнительных сценария проходили; окончательный связанный browser run фиксируется в итоговом отчёте после последних исправлений.

PostgreSQL **17.11** реально подключён к API через psycopg; seed загрузил 26316 продаж и остальные восемь CSV. **18/18 API tests PASS за 33.274 s** на новой изолированной PostgreSQL test DB. Linux-образы собраны, API/PostgreSQL healthy, web/worker запущены. Evidence: `artifacts/verification/postgres.json`. HTTP через nginx, pg_dump/restore и финальная пересборка web имеют отдельные отчёты по мере выполнения.

Исследование действительно рассчитывает 9 прогнозов и 36 сценариев. PowerShell start/stop и Bash cloud/start/stop прошли синтаксическую проверку; полный запуск launcher отмечается отдельно. Не складывать разные наборы тестов в один якобы выполненный прогон.

## 7. Какие проверки падали или пока не подтверждены

Ранние browser assertions с неоднозначными label/текстом исправлены. При одновременной Docker-сборке повторный browser run упал на пятисекундном ожидании dashboard; тест остановлен и не считается PASS. Тяжёлые проверки переведены на последовательный запуск, ожидание UI — 15 секунд. Для первых PostgreSQL tests исправлен Origin только тестового контейнера: он должен соответствовать развёртыванию.

APK/устройство, iOS/Store signing, Windows launcher целиком, итоговые browser regressions и cloud-run отмечаются по факту в FINAL_REPORT. Наличие исходников, JS bundle, Git или Docker configuration само по себе ничего из этого не подтверждает. Внешняя авторизация GitHub/Cloud остаётся действием владельца.
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

Web: `npm run build`, результат `dist/web`, preview: `npm run preview`. Native TypeScript check не создаёт APK/IPA. `apps/mobile/package.json` содержит команды Expo development build; Android SDK/device или macOS/Xcode и подписи проверяются отдельно. Docker image build: `docker compose build` после подготовки окружения. Нельзя объявлять native/cloud deployment по успешному web build.

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
- GitHub/private remote и действующая cloud environment не подтверждаются наличием Git или скриптов. На момент подготовки handoff `main` существует, `origin` ещё не настроен; авторизацию выполняет владелец. Не записывать токены в проект.
- Windows-проверки не доказывают Linux/macOS/Android/iOS совместимость. Подробный перечень NOT TESTED сохранять в progress.

## 19. Следующий этап разработки и перенос в облако

1. Сохранить текущую историю; проверить актуальные `git status`, `git log -5 --oneline`, `git remote -v`, `gh auth status`. Если вход нужен, владелец выполняет `gh auth login`; агент не обходит вход и не запрашивает пароль. Пользователь разрешил только PRIVATE `asboljam` либо `asboljam-diploma`; push без force, после проверки секретов.
2. После подтверждённого push выбрать этот приватный репозиторий в cloud environment, runtime Python 3.13 и Node.js 24. Setup command: `bash scripts/cloud_setup.sh`. В настройках задать `LOKY_MAX_CPU_COUNT=1`, `PLAYWRIGHT_CHANNEL=chromium`; приложение не использует OpenAI API, API key не требуется. Настройки runtime и custom setup поддержаны официальной [документацией cloud environments](https://learn.chatgpt.com/docs/environments/cloud-environment).
3. Setup устанавливает зависимости и Chromium. Он запускается отдельно: его временные `export` не считаются настройками agent phase. При необходимости отключить mobile install: `ASBOLJAM_SETUP_MOBILE=0`; одновременно отключить его verify. Secrets cloud доступны setup, а не agent phase; сеть agent по умолчанию выключена. Не рассчитывать на сохранение API ключей или на доступ к локальному Windows-диску. [Официальные правила среды и approvals](https://learn.chatgpt.com/docs/agent-approvals-security).
4. Первая cloud-задача: прочитать AGENTS/handoff/progress, выполнить `bash scripts/cloud_verify.sh`, записать фактический результат и продолжить незаконченный пункт. Скрипты сейчас подготовлены; фактическая cloud connection/checkout/verification должна быть подтверждена отдельным запуском.
5. Сверить итоговые runtime/UI/native результаты с FINAL_REPORT, продолжить непроверенные платформы и эксплуатационные сценарии. Offline adapter уже готов; live REAL ingestion требует реальных правил provenance/доступа и данных предприятия. Не переименовывать synthetic в real и не менять весь стек ради переноса.

## 20. Условия полной готовности

Для демонстрационного выпуска: чистый checkout устанавливается, миграция/seed воспроизводимы, API и настоящий worker проходят полную пользовательскую цепочку, роли/изоляция/CSRF/идемпотентность/конкурентное утверждение проверены, график/метрики/дефицит/единицы корректны, backups восстанавливаются, web build и нужные native проверки подтверждены. После изменения кода связанные проверки повторены, статусы честны, безопасный финальный ZIP читается и включает исходники/контракты/данные/lockfiles.

Для cloud handoff: приватный remote и push реально подтверждены, владелец дал доступ cloud к репозиторию, setup и verify выполнены именно в cloud, результат/ссылка на задачу записаны. Для production дополнительно нужны реальный адаптер, эксплуатационные ограничения, HTTPS, нагрузочные/security проверки, мониторинг и восстановление PostgreSQL. Эти условия не считаются выполненными только потому, что создан локальный Git.

