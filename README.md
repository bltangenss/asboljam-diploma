# AsBoljam

Рабочая дипломная система для асхан/кафе: продажи → прогноз → рецептуры → потребность в ингредиентах → годный запас → закупка упаковками → решение менеджера → аудит и CSV.

**Демо: синтетические данные.** Продажи заканчиваются 31.12.2025; прогноз и срез запасов относятся к 01.01.2026. Основной UI — казахский, доступен русский. Система не утверждает реальную экономию и не отправляет заказы поставщикам.

## Быстрый локальный запуск

Нужны Python 3.13, Node.js 24/npm и свободные порты 3000/8000. Docker для локального SQLite-демо не требуется.

Windows PowerShell, из корня проекта:

```powershell
.\scripts\start.ps1 -Install
```

Linux/macOS:

```sh
bash scripts/start.sh --install
```

Запуск установит зависимости, применит миграцию, загрузит разрешённые demo CSV и поднимет API, worker и web. Откройте `http://localhost:3000`; документация API — `http://127.0.0.1:8000/docs`. Email первоначального администратора — `admin@asboljam.local`. Seed показывает случайный пароль один раз. Его можно заранее задать переменной `DEMO_PASSWORD` (минимум 12 символов); повторный seed существующий пароль сохраняет. Пароль не зашит в UI или репозиторий.

Без `-Install`/`--install` launchers используют уже установленное окружение. Логи находятся в `.cache/logs`. Остановка: `.\scripts\stop.ps1` или `bash scripts/stop.sh`. Если порты заняты, сначала остановите предыдущий запуск. Подтверждённые платформы и ограничения launchers записаны в [PROGRESS](templates/PROGRESS.md).

## Запуск вручную

```sh
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
npm ci
python database/migrate.py
python scripts/seed_demo.py
```

В трёх терминалах с тем же окружением:

```sh
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
python -m apps.worker.main
npm run dev
```

Это три отдельные команды/процесса. Данные по умолчанию — `data/asboljam.sqlite`. При ручном запуске установить переменные окружения самостоятельно; `.env` читает launcher, а не Python автоматически. Безопасные имена переменных — в [.env.example](.env.example). Не перезаписывайте существующий `.env` и не публикуйте его.

## Демонстрационный сценарий

1. Войти, выбрать филиал и проверить дату/маркировку SYNTHETIC.
2. Открыть продажи, склад, рецептуры и предложения поставщиков. Исходные CSV уже загружены seed; повторный импорт тех же ключей отклоняется.
3. В разделе импорта выбрать CSV, изучить preview и ошибки; только валидный файл подтверждать отдельным commit.
4. Создать однодневный прогноз. Дождаться настоящего worker; открыть таблицу, историю выбранного блюда, метрики и model card.
5. Рассчитать закупку с бюджетом. У baselines доступен point; HGB также даёт p50 и p90_stress.
6. Проверить потребности и упаковки. Нулевой бюджет разрешён и показывает дефицит. `optimal` не означает отсутствие дефицита.
7. Менеджер/администратор указывает причину и отдельно подтверждает дефицит при утверждении. Проверить аудит и скачать CSV.

## Структура

| Путь | Назначение |
|---|---|
| `apps/web` | React/TypeScript/Vite web |
| `apps/api` | FastAPI, импорт, auth, ML и закупки |
| `apps/worker` | Долговечная очередь задач в БД |
| `apps/mobile` | Expo native-клиент и session tests |
| `packages/api-client`, `packages/design-tokens` | Общий клиент и design handoff |
| `database`, `infra`, `docker-compose.yml` | Миграция, SQL и deployment configuration |
| `data/raw`, `research_only` | Операционные synthetic CSV и отдельно изолированный oracle |
| `contracts`, `design` | OpenAPI, manifest, tokens, карта экранов, UI copy |
| `tests`, `scripts`, `artifacts` | Проверки, команды воспроизведения и измеренные результаты |
| `docs`, `templates` | Аудит материалов, решения, журнал прогресса |

План перехода к коммерческому пилоту и последовательные промпты для дальнейшей разработки находятся в [docs/commercial_prompts/README_RU.md](docs/commercial_prompts/README_RU.md). Это план работ, а не заявление о production-ready статусе или подключении реального бизнеса.

Стек сохраняет React/Vite и custom DB worker. Next.js/Alembic/Redis/Celery не требуются. Операционные записи валидируются и хранятся JSON с ключами/изоляцией; это MVP, не полноценная ERP. Подробнее: [решения](templates/DECISIONS.md), [БД](database/README.md), [аудит источников](docs/SOURCE_REVIEW_RU.md).

## Данные и вычисления

Набор содержит 26316 продаж, 3 филиала, 12 блюд, 10 ингредиентов, 48 строк рецептов и 30 предложений. Источники и типы записаны в [manifest](contracts/data_manifest.json). Manifest и design JSON восстановлены из фактических материалов/кода и не выдаются за исходные приложенные файлы.

Модели: `seasonal_naive_7`, `rolling_mean_28`, `hist_gradient_boosting`. Цель — observed units_sold. Все модели оцениваются на одинаковых 28 днях; признаки используют прошлое, oracle/генераторные параметры исключены. Baselines не имеют выдуманных квантилей. p10–p90 — номинальный 80% интервал.

MILP учитывает целые упаковки, MOQ, max packs, бюджет, вместимость, действительные остатки и zero-day lead time предложения. Yield применяется один раз; unit_cost относится к базовой единице, стоимость строки = packs × pack_qty × unit_cost. Физические количества разных единиц не суммируются; дефицит остаётся видимым. Утверждение плана — внутреннее решение.

```sh
python scripts/run_research.py
```

[Измеренные результаты](artifacts/research/README_KK.md): 9 прогнозов и 36 закупочных сценариев; CSV, полные JSON, SHA256 кода/данных и версии среды. HGB WAPE на трёх synthetic филиалах: 22.50%, 25.65%, 24.46%. Это не доказательство экономии в реальной организации.

## Проверки и сборка

```sh
python -X utf8 -m unittest discover -s tests -p "test_*.py" -v
npm run build
```

Браузер при запущенных API/worker/web:

```sh
python scripts/prepare_e2e.py
npm run test:e2e
```

Этот seed создаёт отдельную тестовую организацию, пароль сохраняет только в игнорируемом `.cache`. Для native: `cd apps/mobile`, `npm ci`, `npm run typecheck`, `npm test`. Web build создаёт `dist/web`; native typecheck не создаёт APK/IPA. Фактические PASS/NOT TESTED см. [CLOUD_HANDOFF, пункты 6–7](CLOUD_HANDOFF.md) и [PROGRESS](templates/PROGRESS.md).

## Docker, резервирование и облако

После подготовки приватного `.env` с собственным POSTGRES_PASSWORD:

```sh
docker compose up --build -d
docker compose exec api python scripts/seed_demo.py
```

Compose содержит PostgreSQL/API/worker/web; Redis не используется. Для остановки без удаления базы: `docker compose stop`. PostgreSQL runtime проверяется отдельно от `docker compose config`.

SQLite backup/restore:

```sh
python scripts/backup_db.py backup --database data/asboljam.sqlite --output backups/demo.sqlite
python scripts/backup_db.py restore --backup backups/demo.sqlite --destination data/restored.sqlite
```

Утилита не перезаписывает существующий файл; проверяет целостность, foreign keys и SHA256. Для PostgreSQL нужны pg_dump/pg_restore целевой среды.

Инструкции передачи и 20 пунктов состояния — [CLOUD_HANDOFF.md](CLOUD_HANDOFF.md). Для Linux cloud подготовлены `bash scripts/cloud_setup.sh` и `bash scripts/cloud_verify.sh`; второй использует отдельную `.cache`-БД. Наличие скриптов не означает выполненный cloud-run. Приложению не нужен OpenAI API key. GitHub/Cloud авторизацию выполняет владелец через штатный вход; реальное подключение и push проверяются отдельно.

PostgreSQL/Docker проверяются реальным запуском, а не только конфигурацией; фактические результаты — в [FINAL_REPORT.md](FINAL_REPORT.md) и `artifacts/verification`. Подготовлен [офлайн POS-адаптер](docs/POS_ADAPTER_RU.md): он сохраняет REAL/SYNTHETIC, но не подключает реальное предприятие к demo importer. Не использовать synthetic сценарий как актуальный производственный план.

