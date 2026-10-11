# AsBoljam — установка, обновление, резервное копирование и выпуск

Runbook оператора. Описывает только то, что реализовано в коде; результаты проверок
каждой версии — в [PROGRESS](../../templates/PROGRESS.md) и `artifacts/verification`.
Локальная установка или Docker на компьютере разработчика **не являются** production
deployment: для него нужны сервер, домен, TLS и решение владельца (см.
[LAUNCH_BACKLOG_RU](LAUNCH_BACKLOG_RU.md), пункт 4).

## 1. Что такое выпуск

- `AsBoljam_Final.zip` — исходники ровно одного commit (`RELEASE_MANIFEST.json`:
  `source_commit`, SHA256 и размер каждого файла) и рядом `AsBoljam_Final.zip.sha256`.
- В архив не входят: `.env`, пароли, БД, backup, `.cache`, `node_modules`, `.venv`,
  APK, отчёты браузерных трасс. Зависимости ставятся из `requirements.lock` и
  `package-lock.json`.
- Создание: `python scripts/package_release.py --output releases/<новая-папка>/AsBoljam_Final.zip`
  только из чистого дерева; существующие архивы не перезаписываются.

## 2. Проверка архива перед установкой

1. Сравнить SHA256 архива с файлом `.sha256` (PowerShell: `Get-FileHash -Algorithm SHA256`;
   Linux: `sha256sum -c AsBoljam_Final.zip.sha256` из папки архива).
2. Распаковать в **новую пустую** папку. Не распаковывать поверх рабочей установки.
3. `AsBoljam/RELEASE_MANIFEST.json` содержит commit; при наличии репозитория сверить
   его с `git log`. Упаковщик уже проверяет CRC и хеши; независимая проверка — повторное
   чтение архива и сравнение каждого файла с manifest.

## 3. Установка: Windows, SQLite (локальная демонстрация или один пилотный компьютер)

Требования: Python 3.13, Node.js (проверено 24.x) с npm, свободные порты 8000/3000.

```powershell
cd <новая-папка>\AsBoljam
Copy-Item .env.example .env      # затем задать значения, см. ниже
.\scripts\start.ps1 -Install     # venv + pip из lockfile + npm ci + migrate + seed demo + запуск
```

- `.env`: `ASBOLJAM_ENV=local`; `DEMO_PASSWORD` — только для SYNTHETIC demo (12+ символов,
  либо пусто: пароль будет показан один раз). Для REAL-организации demo seed не нужен:
  организацию создаёт оператор (`scripts/manage_tenant.py`, см. TENANT_OPERATIONS_RU).
- Проверка: `http://127.0.0.1:8000/api/v1/ready` → `{"status":"ready"}`; web
  `http://localhost:3000`; полная HTTP-приёмка demo:
  `.venv\Scripts\python scripts\verify_runtime.py --api-url http://127.0.0.1:3000/api/v1 --web-origin http://localhost:3000 --env-file .env --report <новый-путь>.json`.
- Остановка: `.\scripts\stop.ps1`. Логи: `.cache/logs` (JSON-события, см. WORKER_OPERATIONS_RU).
- `start.ps1` запускает web в режиме разработки Vite. Для постоянной работы предпочтителен
  вариант B (статическая сборка за Nginx).

## 4. Установка: Docker Compose + PostgreSQL (целевая схема)

```sh
cp .env.example .env   # POSTGRES_PASSWORD = secrets.token_urlsafe(32), ALLOWED_ORIGINS, COOKIE_SECURE
docker compose up --build -d
docker compose ps      # postgres/api healthy, worker и web running
```

- Production: `ASBOLJAM_ENV=production`, `COOKIE_SECURE=true`, точные HTTPS origins; demo seed
  запрещён. TLS терминирует внешний reverse proxy перед `web` (порт 3000 опубликован только
  на 127.0.0.1) — его конфигурация зависит от домена и сервера.
- Не использовать `docker compose down -v`: это удаляет volume с данными.

## 5. Обновление существующей установки

1. Объявить окно работ; убедиться, что нет выполняющихся заданий (история расчётов в web).
2. Сделать backup (раздел 6) и проверить его restore-учением.
3. Остановить worker, затем API (`stop.ps1` / `docker compose stop worker api`).
4. Распаковать новую версию в новую папку (или собрать новые образы). Перенести только
   `.env` и путь к БД; не копировать старые `.venv`/`node_modules`.
5. `python database/migrate.py` с тем же `DATABASE_URL` (миграции явные и версионные;
   маркеры вручную не править). Compose применяет их при старте API.
6. Запустить API и worker одной версии; проверить `/ready`, вход, историю расчётов.
7. Откат: остановить новую версию, восстановить проверенный backup **в новый путь/БД**,
   направить на него прежнюю версию приложения. Новую схему старым кодом не открывать.

## 6. Резервное копирование и проверенное восстановление

**SQLite** (`data/asboljam.sqlite` по умолчанию):

```powershell
python scripts/backup_db.py backup --database data/asboljam.sqlite --output backups/<новое-имя>.sqlite
python scripts/backup_db.py restore --backup backups/<новое-имя>.sqlite --destination <новый-путь>.sqlite
```

Утилита использует online backup API SQLite (включая закоммиченный WAL), не перезаписывает
существующие файлы, проверяет integrity/foreign keys и пишет manifest с SHA256.

**Учение по восстановлению** (рекомендуется после каждого обновления и регулярно):

```powershell
python scripts/verify_restore.py --source-api http://127.0.0.1:8000/api/v1 --source-database data/asboljam.sqlite --env-file .env --report <новый-путь>.json
```

Скрипт входит администратором, читает планы, CSV утверждённых/отклонённых планов, историю
расчётов, audit, пользователей, импорты и операционные CSV; делает backup и восстановление
в новые файлы; повторно читает источник (он не должен меняться — остановите импорт, решения
и worker); поднимает временный API без worker на восстановленной копии и сравнивает те же
ответы. Допустимое отличие ровно одно: запись audit `session.login` проверочного входа. Проверено 11.10.2026 на
чистой установке финального ZIP: 14/14 проверок (23 таблицы, 58337 операционных строк).

**PostgreSQL** (проверено 11.10.2026 на Docker PostgreSQL 17.11): дамп и восстановление в **новую** базу
внутри контейнера `postgres`, затем HTTP-учение в одноразовом контейнере `api` той же сети:

```sh
C="docker compose --env-file .env"            # те же -p/-f, что у работающего стека
$C exec -T postgres pg_dump -U asboljam -d asboljam --format=custom -f /tmp/<имя>.dump
$C exec -T postgres sha256sum /tmp/<имя>.dump
$C exec -T postgres createdb -U asboljam asboljam_restore_<дата>
$C exec -T postgres pg_restore -U asboljam -d asboljam_restore_<дата> --exit-on-error /tmp/<имя>.dump
export RESTORED_DATABASE_URL="postgresql+psycopg://asboljam:<пароль>@postgres:5432/asboljam_restore_<дата>"
export DEMO_PASSWORD=...                       # пароль администратора проверяемой организации
$C run --rm --no-deps -T -e RESTORED_DATABASE_URL -e DEMO_PASSWORD -v "<папка-проекта>:/workspace:ro" -w /tmp   api python /workspace/scripts/verify_restore.py --restored-from-environment   --source-api http://api:8000/api/v1 --web-origin <разрешённый-origin> --work-dir /tmp/drill
$C cp postgres:/tmp/<имя>.dump backups/     # вынести копию с сервера; этот шаг в проверке 11.10 не выполнялся
```

URL восстановленной базы и пароли передаются только через переменные окружения (в Git Bash на
Windows для `-v`/путей контейнера задайте `MSYS_NO_PATHCONV=1`). В этом режиме дамп сделан до
учения, поэтому допускается ровно одна запись `session.login` источника, отсутствующая в копии,
и одна — в копии; всё остальное должно совпасть. Восстановленную базу после проверки оставьте для
разбора или удалите осознанно; рабочую базу не трогайте. Шифрование, ротация и срок хранения
копий — ответственность оператора.

## 7. Release checklist

| Шаг | Команда / критерий |
|---|---|
| Чистое дерево, нужный commit отправлен | `git status --short` пусто, `git log -1`, push без force |
| Python-регрессия | `python -X utf8 -m unittest discover -s tests -p "test_*.py"` с новым изолированным `DATABASE_URL` |
| Web | `npm run build`; browser-suite на изолированных fixtures при изменениях UI/API |
| Mobile (если менялся клиент/API) | `cd apps/mobile && npm run typecheck && npm test` |
| Секреты | `python scripts/check_secrets.py --staged` перед каждым commit |
| Зависимости | `npm audit`, аудит Python lockfile; известные уязвимости исправлены или описаны |
| Архив | `package_release.py` в новую папку; независимая проверка CRC/manifest/SHA256 |
| Чистая установка | распаковка в новую папку, `start.ps1 -Install` или Compose, `verify_runtime.py` |
| Восстановление | `verify_restore.py` на установленной версии |
| Документы | README, PROGRESS, CLOUD_HANDOFF, FINAL_REPORT с фактическими результатами |

Не объявлять production-ready без целевого сервера, TLS, мониторинга, проверенного backup на
целевой среде и согласованного пилота.
