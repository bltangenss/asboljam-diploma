# AsBoljam — журнал прогресса

## Актуальное продолжение — 29.09.2026

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
