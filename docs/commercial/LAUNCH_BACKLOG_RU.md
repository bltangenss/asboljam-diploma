# AsBoljam — приоритетный backlog запуска

Состояние на 11.10.2026. Порядок отражает приоритеты владельца: сначала ошибки, потеря
данных, права и расчёты; затем полный путь пользователя, onboarding, надёжность заданий,
KK/RU, воспроизводимая установка, backup/restore, эксплуатация целевой среды и mobile.
Пункт считается выполненным только с фактическими проверками в
[PROGRESS](../../templates/PROGRESS.md). Статус здесь — краткая сводка, не замена evidence.

| # | Пункт | Критерии готовности | Статус |
|---|---|---|---|
| 1 | Диагностика request → job | README §15.1: server X-Request-ID, allowlisted события, `job.queued`/terminal только после commit, CAS loser/timeout/revoke/missing/reclaim/contention с кодами, безопасный 500 до/после заголовков, CORS, `--no-access-log`, Nginx JSON access log; focused + полная регрессия + runtime uvicorn + Docker/Nginx | См. PROGRESS 11.10.2026 |
| 2 | Release candidate: чистая установка из нового ZIP | ZIP из чистого commit; распаковка в новую папку; новый venv из `requirements.lock`, `npm ci`; новая SQLite; migrate + seed с приватным паролем; API/worker/web из распакованного дерева; `verify_runtime.py`: login → scope/roles/CSRF → forecast → procurement → approval (version/reason/idempotency/deficit) → audit → export → CSV preview/commit/replay; web build | TODO |
| 3 | Проверенный backup/restore установки | Backup после workflow; restore в новый путь; API на восстановленной БД: login, тот же approved plan, побайтно тот же approved CSV, те же counts audit/jobs; PostgreSQL: dump/restore в новую БД с теми же проверками | TODO (прежние SQLite/PG проверки — для старых версий) |
| 4 | Пакет целевого развёртывания (один VPS, Compose) | `.env.production.example` без секретов; TLS reverse proxy; закреплённые digest образов; ротация docker-логов; healthcheck/restart; скрипт PostgreSQL backup + проверка restore; runbook update/rollback; локальная проверка config/TLS self-signed | TODO; реальный deploy BLOCKED: домен, сервер, DNS, решение владельца |
| 5 | Onboarding и неполные данные | Пустая организация → первый филиал → шаблоны → импорт с пропусками/ошибками → понятные KK/RU сообщения, без подстановки нулей; browser-проверка на изолированной fixture | TODO: аудит живого UI, исправлять подтверждённые проблемы |
| 6 | Надёжность заданий | Ограничение ожидания публикации в БД; ручная отмена job (API/UI) с fences claim/status/audit; метрики очереди | TODO |
| 7 | Mobile | Сборка APK текущего кода с указанием ABI; эмулятор/устройство: login/refresh/revocation/approval; без заявлений о store-release | TODO; Android SDK/эмулятор есть локально |
| 8 | Пилот | Источник данных, разрешение, филиал/timezone, 84+ дня, рецепты/yield, остатки, shadow mode, baseline | BLOCKED: нужно предприятие |

Не входит в первый запуск без отдельного решения: несколько REAL-филиалов, POS-коннекторы,
промо/погода как признаки, многодневные закупки, отправка заказов поставщику, биллинг.
