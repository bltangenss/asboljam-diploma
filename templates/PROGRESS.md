# AsBoljam — журнал прогресса

## Актуальное продолжение — организации и первый запуск, 29.09.2026

Продолжена `main` от `129f140c4bc8e2de002a8fb0f0e6ef0decbda6e1`, без реального предприятия.

**DONE:** Organization и явная миграция0002; metadata/status/timezone/data policy; операторский bootstrap первого admin без демо-записей; suspend/resume с атомарным отзывом сессий, refresh и queued/running jobs. Возобновление их не восстанавливает. API/пароли/worker соблюдают порядок Organization → User → session/job. CLI требует явной существующей БД с поддерживаемой схемой, preflight по умолчанию, `--apply`, скрытый пароль и operator/reason/audit. Migration CLI проверяет конфигурацию до открытия БД.

**DONE UI:** пустая организация получает настройку без branch=1 и чужого имени. После branches CSV обновляются сессия и филиалы без logout; старые ответы прежнего аккаунта игнорируются. Unconfigured не запрашивает операционные данные. Metadata берётся из БД; без истории продажи/выручка — `—`, подтверждённые нулевые продажи — `0`. Даты графика/планов берутся из API, диапазон продаж обозначен как фильтр. OpenAPI/design contracts и [runbook](../docs/commercial/TENANT_OPERATIONS_RU.md) обновлены.

**TESTED:** полный `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` — **196/196 PASS, 44.788 s**. После финального guard версии схемы повторён только затронутый `test_tenant_cli.py` — **10/10 PASS, 0.986 s**; полный suite после этой CLI-правки не повторялся. PostgreSQL runner пяти suites — **64/64 PASS, 50.21 s**: 63 тела тестов PostgreSQL17.11, один backup/restore case намеренно SQLite; все64 fixture setups создали отдельные PG-схемы. Backend не менялся во время PG-прогона. [PG report](../artifacts/verification/postgres-tenant-platform.json).

`npm.cmd run build` — **PASS**,1751 modules,Vite3.32 s. Mock Chrome sessions/imports/account/tenant — **22/22 PASS,28.6 s**. Live Chrome workflow6 + первый tenant1 — **7/7 PASS,48.6 s**, настоящие API/worker и `.cache/tenant-live.sqlite`. Проверены шаблон → CSV → новый branch scope, пустая история, полный synthetic workflow до approval/export, HGB, роли/сессии и responsive. Mobile audit screenshot просмотрен, таблица остаётся внутри scroll region. [Все команды и границы](../artifacts/verification/tenant-platform.json).

До0002 создан приватный online backup основной SQLite: `backups/pre-tenant-0002-c8157ef272ee49aeb1b3a14f88536c25.sqlite`, SHA256 `cc0acff19e2c00d322bc7716d23670c4685ff5c1058ed8d8b97ccdfcf10643fe`; integrity/FK PASS. После upgrade версии0001/0002, backfill7 организаций, количества строк во всех прежних таблицах совпали. Migration fixtures отдельно проверяют точное сохранение строк, rollback DDL/данных/версии, конкурентный запуск и backup → restore в новый путь → upgrade.

Начальная сборка нашла пропущенную JSX-скобку logout — исправлено. Sandbox затем запретил esbuild (`spawn EPERM`); разрешённая локальная сборка прошла. Review исправил запрос запрещённых branches у unconfigured до browser-прогона. API/worker/preview и PostgreSQL-контейнер остановлены; порты3000/8000 свободны, базы/volumes сохранены. `.cache` и backups не входят в Git/ZIP.

**IN PROGRESS:** общая коммерческая подготовка. **TODO:** REAL/provenance, повторяемый импорт/corrections/reconciliation, далее stock ledger, heartbeat и эксплуатационные gates. [Матрица](../docs/commercial/RELEASE_GATES_RU.md) сохраняет полный незавершённый объём.

**BLOCKED:** реальные пилотные метрики требуют бизнеса; локальная разработка доступна. **NOT TESTED:** production HTTPS/deployment, нагрузка/SLA, независимый аудит, интерактивный CLI человеком, бизнес/экономия, device runtime/APK. Research benchmark и финальный ZIP не пересобирались. PostgreSQL backup verifier сравнивает полный набор migration markers, но pg_dump/restore повторно не запускался. REAL-импорт запрещён; production-ready не заявляется.

Ниже — история предыдущих блоков; её TODO/BLOCKED не заменяют актуальное состояние выше.

## Актуальное продолжение — пароли и PostgreSQL, 29.09.2026

Предыдущий блок классифицирован как **progress**: два коммита `e495268`, `1bba8ba` отправлены в origin/main, состояние проверено чистым. Общая цель выхода на рынок остаётся активной; [матрица коммерческих условий](../docs/commercial/RELEASE_GATES_RU.md) сохраняет её полный объём.

**DONE:** смена собственного пароля в web KK/RU для всех ролей и API `/account/password`; безопасная операторская CLI `scripts/manage_password.py` с dry preflight по умолчанию и скрытым двойным вводом при `--apply`. Замена пароля, отзыв web/native/refresh и отмена pending jobs атомарны; login/refresh берут ту же User-блокировку, чтобы старые credentials не пережили reset. Оператор указывает точную организацию/пользователя, свой ID и причину, не меняет active/role/branches. Ошибки валидации credential routes не возвращают входные секреты. API schema/OpenAPI и design map/copy обновлены; миграция не нужна.

**TESTED:** `python -X utf8 -m unittest discover -s tests -p "test_*.py" -v` — **157/157 PASS, 27.926 s**. `npm.cmd run build` — PASS, 1750 modules, 3.51 s после исправления accessible name. `npm.cmd run test:e2e -- tests/e2e/account_security.spec.ts tests/e2e/sessions_imports.spec.ts --reporter=line --output=.cache/account-security-e2e-final --timeout=30000` — **14/14 PASS, 21.8 s**, mock API. Реальный `workflow.spec.ts` на отдельной SQLite-базе/API/worker — **6/6 PASS, 33.3 s**, включая login → CSV validation/commit → sales → baseline/HGB forecast → procurement → approval/stale conflict → audit/export, branch scope, offline/network, KK/RU и смену пароля с отказом старого login/web/native/refresh. Скачанный CSV отдельно прочитан: 23 строки, approved version 2, SYNTHETIC, 12 purchase lines, целые packs, суммы строк соответствуют packs × pack_qty × unit_cost; итог 87513.2 при бюджете 150000.

Docker Desktop удалось запустить, использованы существующие образы без скачивания. `python -X utf8 scripts/verify_postgres_security.py` — **27/27 PASS** (tenant16 + worker11, 25.994 s), `python -X utf8 scripts/verify_postgres_security.py --suite test_password_security.py --report-name postgres-password-security.json` — **12/12 PASS, 11.585 s** на финальном password service. Реальный PostgreSQL **17.11**, новые тестовые базы и отдельная схема на тест; исходные operational DB/volumes не изменялись. Первоначальный PostgreSQL password12 прогон был повторён только после добавления защиты audit metadata. Это снимает предыдущую локальную Docker/PG блокировку. Артефакты: [postgres-security](../artifacts/verification/postgres-security.json), [postgres-password-security](../artifacts/verification/postgres-password-security.json).

Начальная browser-проверка новой формы выявила примешивание length hint к accessible name поля; исправлено `aria-labelledby`, повтор14 PASS. При просмотре mobile screenshot обнаружен кадр посередине CSS-перехода sidebar; capture и проверки закрытого/открытого меню уточнены. Результат отдельного responsive-повтора записывается в [account-security.json](../artifacts/verification/account-security.json). Трассы, screenshots с сессиями, credentials и тестовые БД остаются в `.cache`, вне Git/ZIP.

**IN PROGRESS:** коммерческая подготовка целиком, особенно tenant lifecycle, отдельная граница REAL/provenance, stock ledger и эксплуатация.

**TODO:** следующая конкретная часть — tenant model/bootstrap с миграцией, status/timezone/data policy и проверяемым первым доступом. Полный список неизменённых требований и evidence gaps — в release gates.

**BLOCKED:** бизнес-пилот и измерение эффекта требуют реального источника и согласований владельца; техническая разработка может продолжаться без них.

**NOT TESTED:** реальный HTTPS deployment, нагрузка/SLA, независимый security audit, email reset, интерактивный ввод recovery CLI человеком (в tests он имитируется), native экран смены пароля и device runtime, реальные бизнес-данные и эффект. APK, ZIP, research benchmark и production backup в этом блоке не пересобирались. REAL импорт по-прежнему запрещён.

## Предыдущий блок — локальная коммерческая основа, 29.09.2026

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
