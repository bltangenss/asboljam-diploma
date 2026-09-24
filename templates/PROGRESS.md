# AsBoljam — журнал прогресса

Состояние: 24.09.2026, локальная работа возобновлена по прямому запросу пользователя. Codex Cloud отменён. Проект и Git history сохранены; текущее продолжение начинается с `24d2dde` в `main`, origin — PRIVATE `bltangenss/asboljam-diploma`.

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
| J — native | Expo55 client, typecheck, 13 session tests и Android JS export PASS; debug APK отложен пользователем, APK не создан |

## IN PROGRESS

- При текущем возобновлении пользователь установил порог: остановить работу и спросить о продолжении при **10% использованного лимита Codex** (90% остаётся). Перед началом расход составлял 0%; после проверки состояния — 1%. Это лимит аккаунта, а не оценка готовности проекта.
- Предыдущая длительная Android-попытка завершилась с кодом `1073807364` (`0x40010004`) без APK; отчёт сохранён в `artifacts/verification/android-build-interrupted.json`. SDK36, NDK27.1 и CMake3.22.1 уже находятся в кэше. Повторный запуск дошёл до `configureCMakeDebug[x86]` и остановлен по прямому решению пользователя; мобильное приложение оставлено на потом. [Текущий статус](../artifacts/verification/android-build.json): `deferred_by_user`, APK отсутствует.
- Синхронизация документации и подготовка проверяемого ZIP. Финальный `releases/AsBoljam_Final.zip` создаётся после финального commit из чистого Git checkout; секреты не включаются.

## TODO

Выполнить финальную проверку секретов, создать ZIP и проверить release manifest/CRC/SHA256. Сделать commit и обычный push. Повторить полный Playwright suite после устранения запрета запуска его subprocess. Android debug APK возобновлять только по новому решению пользователя. Не повторять уже прошедшие тяжёлые проверки без изменений соответствующего кода.

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
| `python -X utf8 -m unittest discover -s tests -p test_package_release.py -v` | Отдельные 10/10 PASS, 3.052 s; временные fixture-архивы, финальный ZIP не создан; [packaging-tests.json](../artifacts/verification/packaging-tests.json) |
| Codex in-app browser / CUA с реальным API и отдельным worker | PASS в перечисленном объёме: login → CSV validation/commit → sales → baseline forecast → procurement → approval → audit/download event; recipes/inventory, второй филиал, RU, dashboard 360 px, logout; [browser-cua.json](../artifacts/verification/browser-cua.json) |
| `python scripts/generate_contracts.py` | Manifest/design contracts синхронизированы с фактическим кодом |
| `python scripts/check_secrets.py` | Последняя проверка 154 candidate files, 0 findings; финальная проверка перед ZIP отдельно |

59 Python tests = 19 API + 14 engine + 4 backup + 19 POS adapter + 3 research-origin guards. Последнее исправление row lock при предоставлении доступа к импортированному филиалу уже включено в Python59/PostgreSQL19. После этих проверок соответствующий API/ML code не менялся, повторный тяжёлый прогон без причины не выполняется. Новые 10 packaging tests выполнены отдельно; общий набор из 69 тестов повторно не запускался.

CUA использовал собранный Vite preview с `--configLoader native`, новую ignored SQLite DB и настоящий worker, без mock API. Прогноз показал 28 исторических точек и 0 baseline-интервалов. План: 10 ингредиентов, 87513.2 ₸ при бюджете 150000 ₸, 0 дефицитных ингредиентов; причина решения видна в аудите. После проверки её browser/API/worker/preview остановлены; demo база не менялась.

## NOT TESTED

Полный текущий Playwright suite не выполнен из-за ограничения среды. В CUA не повторялись offline/network injection, stale approval race, analyst role и HGB chart; при нулевом дефиците не требовался deficit acknowledgement. Наблюдались download event и HTTP 200, но скачанные CSV bytes отдельно не проверялись. Снимок dashboard 360 px не является полным visual regression или accessibility audit. APK installation/Android/iOS device/OS SecureStore, IPA/release signing/Store publishing, production TLS/load/SLA/monitoring и независимый security audit не проверены. Cloud setup/verify именно в Codex Cloud не запускались; Cloud отменён. Windows launcher install branch и Linux desktop launchers целиком не проверялись. Production PostgreSQL restore отдельно от выполненного локального Docker restore не заявляется.

## История последней остановки и возобновления

Перед паузой шесть browser session/import-race checks прошли; workflow превысил 180 s, остальные четыре сценария не завершены. Пользователь остановил работу; серверы были выключены. При возобновлении trace показал 119.09 s ожидания прогноза и 25.97 s закупки; approval/export состоялись, общий timeout исчерпан при последующих UI/screenshots. Этот run остаётся FAILED/interrupted, а не PASS. Подробности: [browser-interrupted.json](../artifacts/verification/browser-interrupted.json).

Cloud handoff был подготовлен, но task не создан: штатный CLI сообщил `environment_repo_access_failed`. Пользователь затем отменил Cloud и явно возобновил локальный план. Эта облачная зависимость больше не является условием завершения локальной работы.
