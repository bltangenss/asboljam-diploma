# AsBoljam — итоговый технический отчёт

## 11.10.2026 — финальный ZIP проверен чистой установкой, браузером и восстановлением

**DONE / TESTED:** `releases/2026-10-11-final/AsBoljam_Final.zip` создан из чистого commit `fc0af29`: 323 файла, 1930862 байт, SHA256 `da5abe1b0dc6e0e5005e82b583b02302634825ee58c9e6cc4d8d36764036ee1f`. Упаковщик: CRC/хеши/secret scan PASS; независимо: CRC, sidecar SHA256, 323/323 = manifest = дерево commit, 323/323 побайтно равны Git-blob. Чистая установка в новую папку вне репозитория через `start.ps1 -Install`: venv из lockfile (anyio 4.14.2), `npm ci` — 0 уязвимостей, миграции 0001–0008, seed; `verify_runtime.py` через web-прокси 87/87. Browser: полный suite 86 PASS + 2 skip (складские live требуют отдельных баз) за 9.2 мин, затем оба складских live-сценария на новых фикстурах — 1/1 и 1/1 (REAL/TEST); итого 88/88, включая REAL/TEST workflow и три live-сценария, падавшие на RC. По JSON-логам API: `/dashboard` p50 1.5 с, max 4.3 с (на RC 7.7/22.2 с), без HTTP 500. SQLite restore drill на установке: 14/14, integrity/FK OK, 23 таблицы (58337 операционных строк) совпадают. `npm run build` PASS; mobile typecheck PASS, tests 13/13. [Свидетельство](artifacts/verification/release-20261011-final.json).

**NOT TESTED:** production deployment (сервер, домен, TLS, нагрузка, failover), APK текущего кода и устройство, реальный пилот, POSIX SIGTERM в этом этапе. Этот commit добавляет только документы/свидетельство; архив соответствует `source_commit` из manifest.

## 11.10.2026 — PostgreSQL, Docker/Nginx и восстановление PostgreSQL на финальном коде

**DONE / TESTED:** свежие образы из `81a550b` (Python 3.13.16, anyio 4.14.2, PostgreSQL 17.11) в новом изолированном compose-проекте: `verify_runtime.py` через Nginx 87/87 PASS; после исправления производительности на PostgreSQL `/dashboard` 0.16–0.73 с, `/plans/{id}` 0.29 с. Логи Nginx/API/worker: только allowlisted поля, секретов и access-строк нет, ID прокси совпадают с API, цепочки forecast/procurement до worker прослежены. Учение по восстановлению PostgreSQL: `pg_dump` → новая база → `pg_restore --exit-on-error` → `verify_restore.py --restored-from-environment`: 13/13 проверок, совпадают количества строк ключевых таблиц, планы, CSV утверждённого плана, история расчётов, импорты, 9 CSV и audit (кроме двух записей входа самого учения — правило уточнено в `b984fa5`). PostgreSQL suites (`test_import_lineage`, `test_run_status`, `test_tenant_isolation`, `test_real_api`, `test_stock_service`, `test_request_logging`): первый прогон — 77 тестов без failures/errors/skips, но статус failed из-за учёта схем (раннер ждал схему на каждый тест, `test_request_logging` использует одну фикстуру на класс: 68 вместо 77); отчёт сохранён. Раннер исправлен (`813dab4`), повтор — PASS: 77 тестов, 68/68 фикстур, 77 тел на PostgreSQL, чистое дерево. [Сводное свидетельство](artifacts/verification/launch-readiness-20261011.json).

**NOT TESTED:** финальный ZIP после этих коммитов, его чистая установка, полный browser-suite с REAL/складскими фикстурами и SQLite-учение по восстановлению — следующий шаг. Шаг `docker compose cp` дампа наружу не выполнялся. Production, нагрузка, mobile, пилот — без изменений.

## 11.10.2026 — диагностика request → job завершена

**DONE:** server-generated `X-Request-ID` (32 hex) на каждом ответе, включая ранние 400/413, preflight и middleware 500; входящий и выставленный маршрутом ID игнорируются. JSON `http.request` содержит только method, шаблон маршрута или `unmatched`, status, duration и фиксированный `code` (`HTTP_REQUEST_FAILED` / `HTTP_REQUEST_CANCELLED`). `job.queued` пишется только после commit с request_id; worker пишет `job.claimed`, `job.finished`, `job.discarded` (CAS loser/missing), `job.released`, `job.lease_expired`, `job.publication_error` только по фактическому исходу транзакции. Необработанное исключение до заголовков даёт один безопасный 500 с security headers и CORS для разрешённого origin; после заголовков второй ответ не отправляется. Серверу передаётся только `RuntimeError: HTTP_REQUEST_FAILED` без исходной цепочки. Порядок middleware: correlation → CORS → protection. `--no-access-log` в start.ps1/start.sh/cloud_verify.sh/Dockerfile.api, Nginx пишет JSON `proxy.request` (status, время, X-Request-ID API). Runbook: [WORKER_OPERATIONS_RU](docs/commercial/WORKER_OPERATIONS_RU.md). Приоритетный [backlog запуска](docs/commercial/LAUNCH_BACKLOG_RU.md) составлен.

**TESTED:** первый focused прогон 36 тестов — 35 PASS, 1 FAIL из-за ошибки в самом тесте (строка `inner-` входит в шаблон `/test/inner-header`); исправлена только проверка теста, повтор `test_request_logging` 10/10 PASS. Полная Python-регрессия 490 тестов: 489 PASS + 1 POSIX SIGTERM skip, 0 failures/errors, 346.5 s. Настоящий uvicorn с `--no-access-log`: 10/10 проверок; контроль без флага подтвердил запись сырого query в access log Uvicorn. Свежие Docker-образы из текущего дерева + PostgreSQL 17.11 + Nginx 1.30.5: `verify_runtime.py` через Nginx 87/87 PASS (login → роли/CSRF → forecast → procurement → approval → audit → export → CSV import/replay); логи Nginx/API/worker без паролей, маркеров, сырых путей и access-строк; цепочка request → job → worker прослежена. OpenAPI идентичен контракту. [Отчёт](artifacts/verification/request-logging-20261011.json).

**NOT TESTED:** focused-тесты диагностики на PostgreSQL (код проверен на PostgreSQL через Docker HTTP workflow), POSIX SIGTERM, error log Nginx при отказе upstream, доставка/ротация/хранение логов, production TLS/нагрузка. Web/mobile/research не менялись и не перезапускались. **Следующий пункт:** backlog №2 — чистая установка из нового ZIP и проверенный backup/restore.

## 10.10.2026 — проверенный исходный архив пересчётов

**DONE / TESTED:** `releases/2026-10-10-count-anchor/AsBoljam_Final.zip` создан из чистого commit `a3d5038fde409a913dd48d45f2dc4570fb19d1e7`: 303 исходных файла, 1791761 байт. CRC, состав архива, размеры и SHA256 каждого файла проверены упаковщиком и независимым повторным чтением. SHA256 ZIP: `45da77922c55e19a66048e8dc4c9b112e7ea7ffa59028891c3c62b3bc5066e01`. [Свидетельство упаковки](artifacts/verification/release-20261010-count-anchor.json). Следующий commit фиксирует только документацию и результат упаковки; код приложения совпадает с source_commit архива. Старые ZIP и приватные backup сохранены. **NOT TESTED:** новая установка из распакованного ZIP, production, реальный пилот и новый APK/device.

## 10.10.2026 — подтверждённые пересчёты без перезаписи истории

**DONE:** manager/admin принимает новый полный посчитанный остаток через preview, причину, раскрытые расхождения и обязательное подтверждение. Отдельная migration0008 сохраняет документ, происхождение, предыдущий fingerprint, автора, границу движений, idempotent receipt и аудит. Старый baseline и документы не редактируются. Kg/L и точные десятичные строки сохраняются; пропущенные партии не превращаются в нули. Смена источника остаётся заблокированной. Чтение, сверка и закупка используют основу выбранного периода; поздние пересчёты не устаревают ранний план. Старые утверждённые выгрузки неизменны. [Правила](docs/commercial/STOCK_LEDGER_DESIGN_RU.md).

**TESTED:** полный Python454:453 PASS,1 POSIX-only SIGTERM skip,0 failures/errors,512.179s; исходники стабильны. PostgreSQL80/80 PASS,122.146s (79PG bodies и1 pure engine). Новые focused service16/16, arithmetic16/16, прежние service20/20, HTTP6/6 SQLite. Первоначальное несовпадение ожидания source_freshness в одном service-тесте сохранено отдельно и исправлено явной проверкой неизменных строк и изменившейся свежести. [Полная регрессия](artifacts/verification/count-anchor-regression-20261010.json), [PG](artifacts/verification/postgres-count-anchor-20261010.json), [focused](artifacts/verification/count-anchor-service-20261010.json).

**DONE / TESTED:** основная SQLite0007→0008 после verified backup `backups/pre-count-anchor-0008-20261010T083943699092Z.sqlite`. Все21 прежние таблицы сохранили хеши и количество строк; новая stock_count_anchors пуста; integrity/FK PASS. [Миграция](artifacts/verification/count-anchor-main-migration-20261010.json).

**TESTED web:** финальные29/29 Chrome API-fixture сценариев (76.553513s), TypeScript/Vite PASS (4.17s), KK/RU и390px. Отдельный live1/1 PASS с первой попытки (44.2s тест,48.0s suite): настоящий CSV correction через HTTP → блокировка → два подтверждённых пересчёта → новые приходы → worker forecast/procurement → UI approval → audit/export. Версия журнала5, последовательность движения2, прежний утверждённый CSV побайтно неизменен, ошибок браузера нет. Это generated REAL/TEST contract fixture, не данные предприятия. После полной регрессии изменён только самостоятельный browser fixture:85 дней для двух origin вместо84; обычный SYNTHETIC сохраняет84 дня. Код приложения не менялся. API/worker/web остановлены, данные сохранены. [Browser evidence](artifacts/verification/stock-count-anchor-web-20261010.json).

**NOT TESTED:** production/TLS/load, реальный POS/бизнес-пилот и измеренная экономия, новый APK/device и новая установка из ZIP. Научные forecast/procurement алгоритмы не менялись, прежний успешный research без причины не повторялся. **BLOCKED внешними данными:** выводы о реальном бизнесе требуют согласованного источника и пилота. Общая коммерческая цель остаётся незавершённой; следующий локальный участок — безопасные логи request→job без секретов и ложного success при rollback/CAS-конфликте.

## 10.10.2026 — исходный архив складского этапа

**DONE / TESTED:** локальный `releases/2026-10-10-stock/AsBoljam_Final.zip` создан из чистого commit `3c642defa09638aa844ef316b8fe22493bc542c9`:290 исходных файлов,1730125 байт. CRC и SHA256 всех файлов PASS; scanner не нашёл секретов по своим правилам. SHA256 ZIP: `25f83dda0acfbf2dab900b06fc5fa00bc764a0810e4c0816952dfbf91a5ab66f`. [Свидетельство упаковки](artifacts/verification/release-20261010-stock.json). Следующий commit сохраняет только это свидетельство и документацию, поэтому отличается от source_commit архива. Старые ZIP сохранены. Новая установка из распакованного архива и новый APK не проверялись.

## 10.10.2026 — складской web/API контур

**DONE:** явное открытие по посчитанному срезу; приход, списание, корректировка, рецептурный расход по партиям и обратная запись; полные датированные версии рецептов с сохранённым выходом; сверка, связь с закупкой, устаревание новых решений и неизменность утверждённых результатов/CSV. Web KK/RU показывает preview, историю и основания плана; нет автоматического списания из продаж или отправки заказов. [Порядок работы](docs/commercial/STOCK_LEDGER_DESIGN_RU.md).

**TESTED:** API/engine13/13 SQLite; PostgreSQL93/93 для сервисов/миграций и31/31 для HTTP/рецептур. Первый параллельный PostgreSQL-прогон истёк по300s, последовательный повтор прошёл за54.965s; оба отчёта сохранены. Общий Python425:423 PASS,1 ошибка тестовой гонки запуска child,1 POSIX SKIP; исправлена только fixture, связанный worker-process suite повторён13/13 PASS. Это не переименование исходного FAIL в полностью зелёный полный прогон. Research9 прогнозов/36 закупок: численные CSV совпадают с сохранённой версией, кроме elapsed_seconds. Основная SQLite обновлена до0007 после проверенного backup, все19 прежних таблиц неизменны. Свидетельства: [регрессия](artifacts/verification/stock-regression-20261010.json), [исправленный тест](artifacts/verification/stock-worker-regression-20261010.json), [PostgreSQL](artifacts/verification/postgres-stock-api-20261010-retry.json), [research](artifacts/verification/stock-research-20261010.json), [миграция](artifacts/verification/recipe-migration-20261010.json).

**TESTED web:** Chrome23/23 с API-fixtures (41.2s):17 складских и6 прежних REAL-context сценариев. Отдельный настоящий browser/API/worker workflow1/1 PASS (37.8s тест,40.3s suite) на новой SYNTHETIC SQLite: вход → открытие → рецепт → приход → расход → обратная запись → сверка → forecast/procurement → approval → audit/export. Финальный TypeScript/Vite build PASS (Vite4.00s). Проверены KK/RU, ширина390px, точные десятичные строки, повтор с тем же ключом, старые ответы/ошибки при смене даты и предупреждение об изменённом baseline. [Browser evidence](artifacts/verification/stock-web-20261010.json). Ранние ошибки тестового ожидания и selectors исправлены; они не выдаются за пройденные прогоны. Все созданные тестовые API/worker/web процессы остановлены, базы сохранены.

**TODO:** отдельный неизменяемый документ восстановления учёта после исправления исходного среза; закрытие периодов и реальные правила работы филиала. Сейчас исправленный baseline/источник блокирует новые проводки и закупку, сохраняя старую историю.

**NOT TESTED:** production/TLS/load, реальный бизнес-пилот и измеренная экономия; новая native-сборка/APK. **BLOCKED внешними данными:** подтверждение качества реального POS и результата на предприятии требует согласованного пилота. Коммерческая готовность целиком не заявляется. Новый исходный ZIP формируется после commit этого этапа; его точный source_commit фиксируется внутри RELEASE_MANIFEST.json.

## 10.10.2026 — язык ошибок расчёта

**DONE:** пять известных JOB-ошибок показываются на выбранном KK/RU, включая тайм-аут. Раньше русский интерфейс показывал казахское сообщение worker. Неизвестные ошибки сохраняют прежний fallback; повторный расчёт автоматически не создаётся.

**TESTED:** контракты UI-copy обновлены; web build PASS; Chrome11/11 PASS (50.4s) с API-fixtures, включая два языка тайм-аута, отсутствие повторного POST, историю/повтор polling и ширину390px. Скриншоты обоих языков просмотрены. [Отчёт](artifacts/verification/job-error-localization.json). **NOT TESTED:** новый live browser/backend/device прогон; сервер не менялся, его успешные проверки без причины не повторялись. Прежний ZIP остаётся снимком своего manifest commit.

## 10.10.2026 — проверенный архив текущих исходников

**DONE / TESTED:** `releases/2026-10-10/AsBoljam_Final.zip` создан из чистого commit `1e49912fe2985eb518971fdd24251766eb21a7d4`:264 файла,1612448 байт. CRC и SHA256 каждого файла проверены упаковщиком и повторным чтением; секретов по правилам сканера не обнаружено. SHA256 ZIP: `bc2ee5e7097bac7fed857aa274d9567133a9ca7f9907a57be4d931ed2036546a`. Старые архивы сохранены. [Отчёт](artifacts/verification/release-20261010.json).

**NOT TESTED:** новая установка из распакованного ZIP, production и свежая native-сборка. ZIP содержит исходники и известные ограничения, а не подтверждение коммерческого запуска. Следующий commit фиксирует только свидетельство упаковки; точный source commit указан в RELEASE_MANIFEST.json внутри ZIP. Пилот, полный складской workflow и эксплуатационная приёмка остаются незавершёнными.

## 10.10.2026 — HTTP-приёмка worker с дочерним расчётом

**TESTED:** commit02c6cd1 —87/87 HTTP checks PASS на отдельной новой SYNTHETIC SQLite: вход, readiness, scope/role/CSRF, реальный forecast и procurement через отдельный worker, утверждение с версией/причиной/idempotency, audit/export и CSV preview/commit/replay. API запущен на127.0.0.1:8011, расчёт использовал новый subprocess worker. [HTTP-отчёт](artifacts/verification/runtime-worker-process.json), [контекст запуска и ограничения](artifacts/verification/worker-process-isolation.json).

Только созданные для проверки процессы API/worker остановлены, искусственная база сохранена в ignored .cache; основная база не изменялась этим прогоном. Новый browser/device/production-пилот не проверялся. Это подтверждает серверный workflow, а не готовность коммерческого запуска.

## 10.10.2026 — отдельный процесс расчёта и ограничение времени

**DONE:** worker выполняет расчёт в дочернем процессе без переменных паролей/БД. Настраиваемый срок1–3600s (по умолчанию900s), остановка при утрате захвата/доступа, heartbeat и проверка права публикации сохранены. Приватные JSON-файлы с атомарным результатом не блокируют заполненную pipe. Запрос наблюдения не перечитывает весь snapshot. Первый сигнал завершает текущую работу; manual cancel API/UI не добавлены.

**TESTED:** Windows worker47 PASS+1 POSIX skip (16.980s). Общая Python-регрессия371 случай:370 PASS+1 POSIX skip (172.918s), исходники в ходе прогона не менялись. Linux/PostgreSQL: первоначально81/82 PASS; единственный сбой вызван путём тестового помощника относительно /tmp. Исправлены только два пути POSIX-теста; повтор связанных6/6 PASS, включая настоящий SIGTERM и публикацию после завершения child. Прежние успешные suites не повторялись. Проверены настоящий forecast/REAL procurement, timeout, отзыв доступа, смена захвата, гибель родителя, очистка файлов, большой ответ и следующая задача. Compose config PASS с временным паролем только для проверки синтаксиса; сервисы не развёртывались. [Подробные результаты и исходные отчёты](artifacts/verification/worker-process-isolation.json).

**NOT TESTED / TODO:** production deployment/load/failover и пилот. Тайм-аут не ограничивает ожидание БД при публикации; OS hard-kill может оставить приватные temp-файлы. Поток наблюдения за родителем зависит от планировщика Python при долгом удержании GIL native-кодом. Browser/build/research/native без изменений повторно не запускались; новый APK/ZIP не создан. Полный складской API/UI, датированные рецепты, procurement lineage и коммерческая приёмка остаются в плане.

## 10.10.2026 — хранилище складского журнала

**DONE (хранилище):** migration0006 добавляет пустые stock_ledgers, stock_movements и stock_command_receipts. Ограничения защищают версию, порядок, номер исходного документа и повтор обратной записи. Старые снимки не превращаются в вымышленные движения.

**TESTED:** migration suites45/45 SQLite (8.208s),45/45 PostgreSQL (17.086s;43 PG bodies и2 SQLite backup tests). Проверены сохранение старых строк, rollback, повтор и конкуренция миграции, ограничения новых таблиц. Основная SQLite обновлена с0005 до0006 после проверенной резервной копии; SHA256 содержимого всех16 прежних таблиц совпали, integrity/FK PASS, новые таблицы пусты. См. [отчёт миграции](artifacts/verification/stock-migration.json) и [PostgreSQL](artifacts/verification/postgres-stock-journal.json).

**IN PROGRESS / NOT TESTED:** API/UI складских документов, датированные рецепты, сверка и связь с procurement ещё не реализованы. Миграция не доказывает готовность полного склада или production deployment.

## 10.10.2026 — арифметика складских движений

**DONE (расчётный модуль):** явные партии, receipt/waste/adjustment/recipe_usage/reversal, gross decimal quantities, запрет отрицательного остатка и смены kg/L/expiry; неизвестная партия не выдаётся за ноль. Opening-сверка использует движения D..E−1 и сохраняет missing/mismatch. Рецептурный yield применяется один раз, дроби суммируются точно и округляются вверх до1e−9 только после агрегации.

**TESTED:** `python -X utf8 -m unittest discover -s tests -p test_stock_math.py -v` —15/15 PASS (2.697s). Review выявил несовместимость меток recipe_version с точками/пробелами; исправлено с проверкой реально принимаемого CSV. Первый прогон обнаружил Decimal Overflow при1E1000000; исправлена проверка через copy_abs, повтор прошёл. Проверены границы дат/сроков, рецептура, откат набора при плохой строке и различие нуля/неизвестного. [Отчёт](artifacts/verification/stock-math.json).

**IN PROGRESS / NOT TESTED:** это основа, не готовый складской продукт. API/UI/posting, датированная активация рецепта, интеграция procurement/lineage и live приёмка ещё не выполнены. Полные критерии сохранены в [плане складского контура](docs/commercial/STOCK_LEDGER_DESIGN_RU.md); цель выхода на рынок не завершена.

## 04.10.2026 — история и повторное открытие расчётов

**DONE:** история прогноза/закупки берётся с сервера, с фильтром выбранного филиала и типа, стабильным порядком created_at/id и страницами по20. После reload можно открыть выполняющуюся или сохранённую задачу без нового POST. Ошибка загрузки не маскируется пустой историей; есть повтор GET. `/runs` сохраняет role/org/branch isolation, лимит максимум50, no-store и безопасную проекцию без snapshot/payload.

**TESTED:** новые API7/7 SQLite (3.315s) и7/7 PostgreSQL; прежние API19/19 (20.683s), включая настоящий worker/forecast/procurement/export. Chrome9/9 (30.7s) с API-fixtures: reload для обоих типов, готовый результат, пагинация, ошибка истории и прежний polling. Web build PASS; screenshot desktop1440/mobile390 просмотрены, overflow отсутствует. До этого блока полный Python330 PASS+1 POSIX skip; после добавления истории повторены релевантные API/browser suites, а не весь неизменённый engine. [Отчёт](artifacts/verification/job-history.json).

**NOT TESTED:** новая live browser приёмка истории, production data/load/deployment, новый APK/ZIP. Stock ledger, CPU deadline/cancellation и бизнес-пилот остаются незавершёнными.

## 04.10.2026 — понятный статус расчёта и восстановление связи

**DONE:** web показывает очередь/выполнение/ошибку на KK/RU, возраст последнего heartbeat по серверным часам и предупреждение после90 секунд без ответа. Это не процент готовности и не доказательство прогресса CPU. Ошибка получения статуса позволяет повторить GET той же задачи без нового POST; failed прекращает polling и возвращает к параметрам только по кнопке. API сохраняет роль/org/branch scope, не раскрывает snapshot/payload и отдаёт no-store; OpenAPI/shared Run обновлены.

**TESTED:** SQLite4/4 и PostgreSQL4/4 для API статуса; Chrome5/5 для queue/heartbeat/KK/RU/offline retry/failed/missing result ID, без повторного POST. Desktop1440 и mobile390 проверены визуально и на отсутствие горизонтального overflow. Web build и mobile typecheck PASS. Финальная Python-регрессия331 случаев:330 PASS,1 POSIX skip,64.760s; реальный SIGTERM отдельно проверен в Linux ранее. [Отчёт](artifacts/verification/job-status.json).

**NOT TESTED / TODO:** браузерные новые сценарии используют детерминированные API-fixtures; новая единая live browser приёмка не запускалась. Сохранение выбора задачи после reload ещё не реализовано. Новый APK/ZIP не собраны; бизнес-пилот и deployment не подтверждены.

## 04.10.2026 — корректная остановка worker

**DONE:** первый SIGINT/SIGTERM останавливает получение новых задач, текущая завершается с heartbeat и публикацией. Захват на границе остановки возвращается в очередь с проверкой прежнего started_at; отменённые/новые захваты не затрагиваются. Ожидание SQLite claim-lock прерывается без нового вычисления; исходные signal handlers восстанавливаются, engine освобождается. Compose даёт120s на остановку.

**TESTED:** Windows worker suite35 случаев:34 PASS,1 POSIX skip. Linux/PostgreSQL25/25 PASS, включая настоящий SIGTERM дочернему процессу во время вычисления: результат сохранён, heartbeat работал, следующая задача осталась queued. Первый PG-отчёт оказался непарсируемым из-за stdout теста; runner теперь сохраняет stdout/stderr в результат suite, повтор25/25 прошёл. [Отчёт](artifacts/verification/worker-shutdown.json).

**NOT TESTED:** фактический Compose stop/redeploy, production failover/load. Второй сигнал/Windows force stop/SIGKILL могут оставить аренду для последующего восстановления; CPU cancellation и deadline не реализованы.

## 04.10.2026 — готовность БД и актуальная HTTP-приёмка

**DONE:** `/api/v1/health` сообщает только liveness, новый `/api/v1/ready` проверяет доступ к БД и точный набор миграций. При несовместимости/недоступности —503 с безопасным кодом, без строк подключения или tenant metadata; ответы no-store, проба не чинит схему. Compose healthcheck и ожидание cloud_verify используют ready. OpenAPI обновлён. HTTP-verifier теперь проверяет идемпотентный повтор commit, неизменённую повторную строку и отдельный запрет дублей внутри CSV; tenant SYNTHETIC подтверждается после login.

**TESTED:** readiness SQLite5/5 PASS; PostgreSQL5/5 PASS; API19/19 PASS, включая OpenAPI. Настоящие HTTP API+отдельный heartbeat worker на искусственной организации —87 checks PASS: login, scope/roles/CSRF, forecast, закупка, версия/причина/idempotency утверждения, аудит, CSV и атомарный повтор импорта. [Отчёт](artifacts/verification/readiness.json), [HTTP](artifacts/verification/runtime-current.json).

**NOT TESTED:** новый Docker/Cloud deployment, HTTPS/нагрузка, native/бизнес-эффект. Readiness не доказывает наличие worker или прогресс модели. Неизменённый web не пересобирался.

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
