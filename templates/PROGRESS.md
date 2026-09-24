# AsBoljam — журнал проверяемого прогресса

Обновлено: 24.09.2026. Здесь фиксируются выполненные проверки. Файл дополняется после каждой итерации; документация сама по себе не является результатом теста.

## DONE

- Прочитаны и сопоставлены все 14 переданных файлов: TXT, DOCX, XLSX, PDF и ZIP; дубликаты и противоречия зафиксированы в `docs/SOURCE_REVIEW_RU.md`.
- Созданы FastAPI, долговечная очередь/worker, SQLite/PostgreSQL-модели и миграция 0001; роли, сессии, ограничения организации и филиала.
- Девять CSV-схем, preview, атомарный commit, шаблоны CSV, продажи и справочники, безопасный экспорт.
- Три модели, общий временной holdout, реальные квантили HGB, метрики и provenance. Рассчитаны 9 прогнозов и 36 закупочных сценариев.
- Потребности по рецептам, годные остатки, MILP с целыми упаковками и независимым Decimal-контролем ограничений.
- Версионное утверждение/отклонение, идемпотентность, явное принятие дефицита и аудит.
- Web KK/RU, responsive dashboard, данные, прогнозы и закупки, график истории/квантилей, управление доступом пользователей.
- Expo-клиент, secure refresh storage, защита конкурентных сессий; Android JS bundle собран.
- Локальный Git main, gitignore, проверка секретов, отдельные коммиты; GitHub CLI установлен.
- README, AGENTS, CLOUD_HANDOFF из 20 пунктов, cloud setup/verify scripts, резервирование SQLite.

## IN PROGRESS

- Docker Compose: Linux API-образ построен; выполняется проверка отдельного PostgreSQL/API/worker/web окружения на 3010/8010.
- Финальная браузерная регрессия после исправления возврата к login при 401 и смены файла во время CSV preview.
- Подготовка offline enterprise CSV adapter, окончательного отчёта и проверенного ZIP.

## TODO

| Этап | Реализация и следующий шаг |
|---|---|
| A — repository/environment/DB/auth | Реализовано; осталось подтвердить private remote/push после входа владельца |
| B — CSV/sales/references | Реализовано и проверено API; повторить UI после последних исправлений |
| C — forecast | Реализовано и проверено; расширение горизонта выходит за однодневный MVP |
| D — requirements/inventory/procurement | Реализовано и проверено; настоящий складской ledger — отдельное расширение |
| E — approval/audit/export | Реализовано и проверено, включая конкуренцию и повтор запроса |
| F — frontend | Основные страницы реализованы; финальная регрессия текущей версии выполняется |
| G — integration/E2E/security | 36 Python PASS; отдельные UI-сценарии проходили, финальный связанный прогон ожидается |
| H — Docker/deployment | Образы и реальный PostgreSQL проверяются; TLS/нагрузка/production backup отдельно |
| I — real enterprise adapter | Offline mapping готовится; реальные данные/правила POS от предприятия не предоставлены |
| J — mobile after API | Исходники, typecheck, 13 session tests, Metro export PASS; устройство/APK/IPA не проверены |

## BLOCKED

- GitHub не авторизован: `gh auth status` сообщил отсутствие входа. Для PRIVATE репозитория/push владелец выполняет `& 'C:\Program Files\GitHub CLI\gh.exe' auth login`. Токены в проекте не сохраняются. Локальная работа продолжается.
- Реального набора предприятия и договора схемы POS нет. Нельзя подтвердить совместимость с настоящим источником или экономию.
- Подписанный iOS/Store release требует внешнего аккаунта/подписей и целевого устройства. Они не предоставлены.

## TESTED

| Команда/проверка | Выполненный результат |
|---|---|
| `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` | 36/36 PASS, 93.152 s: 18 API + 14 engine + 4 backup |
| `python scripts/run_research.py` | 9 прогнозов + 36 сценариев, 32.547 s; 36/36 constraints_valid |
| `npm run build` | TypeScript + Vite 7.3.6 PASS после CSV-template link; 1749 модулей, 30.77 s |
| Первый полный Playwright workflow | PASS 36.5 s: login/import/sales/forecast/procurement/approval/export, responsive/offline/logout |
| Дополнительные Playwright сценарии | Branch/RU/empty/error; stale approval/audit; HGB chart; analyst restrictions — отдельные PASS |
| `cd apps/mobile; npm run typecheck; npm test` | PASS; 13/13 session tests |
| `cd apps/mobile; npm run export:android` | PASS, 588 modules, Hermes 1.8 MB, 61.139 s; это JS bundle, не APK |
| npm dependency install/audit | Web и mobile: 0 vulnerabilities после закреплённых исправлений; не полный security audit |
| `docker compose config --no-interpolate --quiet` | PASS; Docker daemon 29.8.0 реально запущен |
| PowerShell Parser / `bash -n` | start/stop и cloud Bash syntax PASS |
| `python scripts/check_secrets.py --staged` | Последний mobile commit: 14 файлов, 0 находок |

Повторный браузерный прогон при одновременной Docker-сборке дошёл до approval/export, затем упал на пятисекундном ожидании dashboard. Прогон остановлен; PASS всему набору не приписывается. На компьютере 8 GB RAM было около 216 MB свободно. Тяжёлые проверки далее выполняются последовательно; ожидание UI увеличено до 15 секунд.

## NOT TESTED

- Полный cloud setup/verify именно в Codex Cloud; private GitHub push.
- Установка APK/IPA, реальные Android/iOS, OS SecureStore, полный мобильный пользовательский путь.
- Production TLS, нагрузка, восстановление PostgreSQL, SLA/мониторинг и независимый security audit.
- Реальные данные предприятия, подтверждённая экономия, интервью и регламент конкретного вуза.

Python checks выполнены на Windows/Python 3.13; временные SQLite-файлы потребовали запуска за пределами Windows sandbox из-за ACL. Это не выдаётся за успешный sandbox-run. Данные остаются SYNTHETIC, история до 31.12.2025 и сценарий 01.01.2026.
