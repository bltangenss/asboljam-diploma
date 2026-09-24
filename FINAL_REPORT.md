# AsBoljam — итоговый технический отчёт

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

Последний единый Python-прогон: **36/36 PASS**, 93.152 s (18 API + 14 engine + 4 backup). Команда: `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v`.

Research: `python scripts/run_research.py` — 9 прогнозов, 36 сценариев, 32.547 s, 36/36 independently constraints_valid.

Mobile: `npm run typecheck` и `npm test` — PASS, 13/13 session tests; проверены refresh races, storage, idempotency/401 retry, отсутствие повторов 403/409, logout/revocation. HTTP/SecureStore в этих тестах имитируются; это не проверка ОС.

Браузерная финальная регрессия после последних исправлений выполняется. Первый полный путь проходил за 36.5 s; четыре расширенных сценария также проходили отдельно. После параллельной Docker-сборки один повтор упал на timeout dashboard; этот прогон не объявляется успешным. Финальное состояние будет записано сюда после последовательного прогона.

Docker: образы построены, PostgreSQL/API healthy, web/worker запущены. PostgreSQL API-регрессия, HTTP acceptance и pg_dump/restore выполняются отдельно; результаты ожидаются.

## Build results

`npm run build` — TypeScript и Vite 7.3.6 PASS после добавления CSV template link: 1749 модулей, JS 267.09 kB / gzip 84.63 kB, CSS 28.98 kB / gzip 7.08 kB. Docker Linux web build также прошёл. После последних auth/preview исправлений предусмотрен ещё один build.

`cd apps/mobile; npm run export:android` — Metro/Hermes PASS, 588 модулей, 1.8 MB, 61.139 s. Это экспорт JS, **не APK/IPA**. Web/mobile зависимости после точечных overrides показали 0 npm vulnerabilities. Baseline Docker images используют ветки тегов; воспроизводимость образов не гарантируется неизменяемыми digest.

## Known limitations — NOT TESTED

Реальное предприятие и live POS/ERP, доказанная экономия, прогноз на 7/14/30 дней, складской ledger и смена активных рецептурных версий, автоматическая отправка заказов, платежи/налоги, production TLS/нагрузка/мониторинг/SLA и независимый security audit. Worker lease после аварии — 30 минут; длительным jobs потребуется heartbeat.

Не проверены APK/IPA, Android/iOS-устройство и OS SecureStore, магазинная публикация и code signing. Cloud setup/verify подготовлены, но в Codex Cloud не выполнялись. Linux контейнеры не доказывают работу всех desktop launchers. Некоторые технические labels остаются английскими; полного WCAG-аудита нет.

## Что осталось сделать — BLOCKED / TODO

GitHub CLI установлен, но вход отсутствует. Владелец выполняет `& 'C:\Program Files\GitHub CLI\gh.exe' auth login`; после этого разрешено создать PRIVATE `asboljam`/`asboljam-diploma`, добавить origin и запушить main. Remote/push/Cloud не объявлены выполненными. Пароль или токен в чат не требуется.

Для реального предприятия нужны обезличенный экспорт, договор схемы, единиц/валюты и процедуры доступа. Offline adapter может подготовить данные, но текущий operational importer намеренно SYNTHETIC-only. Для native release нужны целевые платформы, SDK, устройство и при signing — аккаунты владельца.

## Передача и архив

`python scripts/package_release.py` упаковывает только проверенный чистый Git checkout в `releases/AsBoljam_Final.zip`. Внутри — исходники, документы, миграции, тесты, scripts, безопасные demo данные, prompts, lockfiles и Docker configuration. `RELEASE_MANIFEST.json` содержит source commit и SHA256 каждого файла; упаковщик проверяет CRC и все SHA256 после записи. Снаружи создаётся `.zip.sha256`. `.git`, `.env`, реальные credentials, БД, node_modules, .venv и caches не включаются.

Актуальный рабочий журнал: [PROGRESS.md](PROGRESS.md). Архитектурные решения: [DECISIONS.md](DECISIONS.md).
