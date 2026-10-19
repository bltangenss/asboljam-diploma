# Predas (бывший AsBoljam) — передача проекта для продолжения разработки

## Актуальное состояние на 19.10.2026

Продукт переименован в **Predas** (технические имена `ASBOLJAM_*`, cookie, demo-почты и файлы БД прежние). `main` = рабочая ветка `forecast-factors`; актуальный ход работ и результаты проверок — в верхних записях [templates/PROGRESS.md](templates/PROGRESS.md), решения — в [templates/DECISIONS.md](templates/DECISIONS.md).

- **Печать плана приготовления подключена:** сохранённый вариант печатается из плана дня (`apps/web/src/ProductionPrint.tsx`). 19.10.2026 на объединённом коде прошли 10 сценариев печати и связанные наборы плана — 74 PASS, 1 skipped. Записи ниже от 15.10 о «неподключённом черновике» устарели и оставлены как история.
- 19.10.2026: регистрация одного email двумя запросами одновременно даёт `409 EMAIL_EXISTS` без частично созданной организации; факторы для строки метрик модели с факторами выбираются только по обучающим дням (итоговый прогноз — по всей истории до даты начала прогноза); миграция `0011` добавила пустую таблицу закрытий дня.

## 15.10.2026 — черновик и незавершённое сохранение защищены от переходов

**DONE:** единая проверка меню, смены филиала, добровольного выхода и назад/вперёд. Черновик можно отменить только явно; выполняющееся или неопределённое сохранение сохраняет исходную команду и ключ повтора. Успешная квитанция снимает защиту, включая ответ во время возврата истории. Принудительный401 очищает сессию и имеет приоритет над отложенным переходом. Экраны читают параметры принятого маршрута, поэтому временный адрес во время отклонённого Back не подменяет выбранный вариант. Диалог KK/RU доступен с клавиатуры и на узком экране.

**TESTED:** focused guard **15/15 PASS**, связанные production/list-scroll/workday/CSV-return **29/29 PASS**; финальный TypeScript и генерация контрактов PASS. Сборка до последней правки возврата на `/` — PASS; повтор после этой правки не выполнялся: пользователь попросил остановиться, автоматическая проверка отклонила запуск. Последняя правка покрыта focused browser и TypeScript. Четыре снимка диалогов; desktop dirty и mobile uncertain просмотрены. [Команды, история отказов и границы](artifacts/verification/production-navigation-20261015.json).

**ОСТАНОВЛЕНО ПО ПРОСЬБЕ ПОЛЬЗОВАТЕЛЯ:** дальнейшие работы и локальные API/worker/web остановлены. Печатный лист сохранён как неподключённый черновик в `docs/drafts/production-print`; его девять подготовленных сценариев не запускались и не входят в обычный test discovery. Следующий шаг при явном возобновлении — прочитать README черновика, подключить и проверить печать.

**ОГРАНИЧЕНИЯ / NOT TESTED:** защита относится к редактору приготовления; принудительное закрытие/перезапуск/выключение может потерять команду из памяти. Для старой записи без доступного индекса предусмотрена явно обозначенная замена адреса; неизменная история в этой исключительной ветке не обещается. Другие браузерные движки, production, реальные предприятия, native/APK и PostgreSQL этим этапом не проверены; backend/schema не менялись, полный Python-набор не повторялся. Финальная повторная сборка и печать не проверены из-за остановки.

## 15.10.2026 — «Сегодня» сохраняет выбранные порции при продолжении работы

**DONE:** повтор отклонённой и пересчёт устаревшей закупки, переход к остаткам и загрузка складского CSV сохраняют проверенный `production_plan_id`. Проверяются ID, филиал, дата и исходный прогноз. Если ручное основание отсутствует или не совпадает, показывается предупреждение с переходом к исходной закупке; незаметной подмены прогнозом нет.

**TESTED:** focused browser **16/16 PASS**, включая прежние сценарии «Сегодня», прямые и складские переходы, отсутствующее/чужое основание; TypeScript PASS. Сборка прямого исправления PASS (JS591.97kB/gzip171.94); финальное расширение ссылок дополнительно проверено TypeScript и browser. Генерация контрактов PASS. [Свидетельство и точные границы проверок](artifacts/verification/production-today-basis-20261015.json). Полная Python/browser-регрессия предыдущего этапа не повторялась: изменение только в формировании веб-переходов.

**IN PROGRESS:** отдельная защита несохранённого/неопределённого сохранения при глобальной навигации. **NOT TESTED:** production, реальный бизнес, APK и PostgreSQL; предыдущие ограничения сохраняются.

## 14.10.2026 — сохраняемый план приготовления реализован и проверен

**DONE:** управляющий сравнивает прогноз и собственные целые порции, сохраняет именованный вариант с причиной, затем переносит его через проверку остатков в закупку. Вариант неизменяемый: исправление создаёт новый документ, исходный прогноз и прежние утверждённые выгрузки сохраняются. Несохранённые изменения блокируют прямое продолжение, переключение варианта и локальный переход к рецептам до сохранения/явной отмены; общего guard для всей навигации нет. Закупка показывает выбранное человеком основание и сохраняет явное утверждение. Сам план приготовления не списывает склад и не отправляет заказ поставщику. API: роли/организация/филиал, свежесть, идемпотентность, worker fencing; migration0009 добавляет две таблицы. [Контракт и сценарий](docs/commercial/PRODUCTION_PLANS_RU.md).

**TESTED:** полная Python-регрессия — **528 PASS +1 POSIX skip** (529 случаев,271.506с); новые API/worker/solver/migration20/20, прежние migration/worker/lineage111/111. Полный browser — **156 PASS +3 opt-in skip**,0failed/flaky; три пропущенных live-сценария прошли отдельно на свежих базах, новый production дополнительно проверен в SYNTHETIC/DEMO и искусственном REAL/TEST. Это159 уникальных сценариев в совокупности запусков, не единый159/159. Финальные focused browser30/30, copy2/2, генерация контрактов и build PASS. Для200 порций проверены20kg потребности и закупки10000/8000₸ в двух фикстурах; новый вариант0 не меняет предыдущий прогноз/утверждённый CSV и не проводит склад. Шесть снимков1440/390px без overflow/pageerror; просмотрены desktop-редактор, mobile-вариант и mobile-утверждённая закупка. [Команды, длительности, хеши и история попыток](artifacts/verification/production-planning-20261014.json).

**DONE / TESTED (локальная установка):** рабочая `data/asboljam-kz.sqlite` обновлена0008→0009 после резервной копии и успешной репетиции на копии: все23 прежние таблицы совпали по содержимому, новые таблицы пусты, integrity/FK OK. Копия: `backups/pre-production-0009-20261014T182205946369Z.sqlite`, в Git не добавлена. Сайт `http://localhost:3000` и API работают; прежний пароль сохранён. Проверочные сервисы остановлены. [Свидетельство миграции](artifacts/verification/production-main-migration-20261014.json). Исходники сохранены и отправлены в `origin/main`: backend`c64d401`, web`9592c52`; итоговый коммит этапа добавляет отчёты.

**BLOCKED:** проверка нового контракта на PostgreSQL — Docker daemon недоступен, тесты не запустились. **NOT TESTED:** production, реальный бизнес/UX-пилот, native/APK/устройства, новый ZIP. Полный research не повторялся: обучение/прогнозирование не менялись. Vite предупреждает о JS590.12kB (gzip171.50), CSS94.07kB (gzip17.45). **TODO:** отдельный сценарий исполнения кухней, общий guard навигации и проверка PostgreSQL; это не заявления о production-ready продукте.

**ЗАМЕЧАНИЕ О СРЕДЕ:** ранний тестовый импорт `apps.api.main` без явного `DATABASE_URL` применил0009 к отдельной прежней `data/asboljam.sqlite`; новые таблицы пусты. Непосредственной pre0009 копии для неё нет, полное сравнение старого содержимого не заявляется. Это произошло до описанного выше безопасного обновления действующей `asboljam-kz.sqlite`. Последующие тесты/OpenAPI выполнялись с явными изолированными базами. Ранние sandbox-ошибки и неудачный селектор кнопки входа не засчитываются как PASS. Работы локальные; Cloud не запускался.

## 14.10.2026 — UX ежедневной работы реализован и проверен

**DONE:** пять разделов — Сегодня, План дня, Остатки, Закупки, Данные и анализ. Главная ставит задачи/предупреждения перед планом и аналитикой; прогноз → проверка остатков → закупка связаны одним сценарием с сохранением контекста филиала. CSV после подтверждённого сохранения возвращает к нужному шагу. Склад разделён по действиям; таблицы и явное решение человека сохранены. Технические детали/история раскрываются по запросу, предупреждения об источнике/неполноте остаются видимыми. [Карта, сценарий и границы](docs/design/TASK_WORKFLOW_RU.md).

**TESTED:** build, генерация контрактов, 2/2 copy tests; общий browser 134 PASS / 6 старых селекторов FAIL / 2 opt-in skip. Исправленный повтор 31/31 PASS (все шесть отказов и пять новых CSV-return сценариев), складские live на отдельных свежих базах 1/1 + 1/1 PASS. Все 147 уникальных сценариев прошли в совокупности прогонов; единого чистого 147/147 не было. Код приложения между общим запуском и повторами не менялся. Проверены локальные HTTP/worker-потоки, роли, утверждение, аудит/экспорт, свежесть и неизменность старого утверждённого экспорта. 40 общих и 10 финальных screenshots, основные desktop/mobile экраны просмотрены. [Команды, результаты и история попыток](artifacts/verification/ux-workday-20261014.json), [журнал](templates/PROGRESS.md).

**NOT TESTED:** production, реальный бизнес/UX-пилот, APK/устройства, новый ZIP. Backend/research/PostgreSQL/native-набор не повторялся для этого веб-этапа. «План дня» пока является прогнозом порций, а не редактируемым производственным документом. Предупреждение Vite о размере JS 568.28 kB сохраняется. **BLOCKED:** локальных блокеров нет. Проверочные сервисы остановлены, пользовательская БД не менялась. Исходники интерфейса сохранены в `ed5a778`; дальнейший коммит этого этапа добавляет тесты и отчёт. Работы продолжаются локально; Cloud не запускался.

## 13.10.2026 — веб-редизайн проверен и сохранён

По [Word-промпту](docs/design/AsBoljam_Design_Prompt_RU.docx) внедрён веб-редизайн: сливовая оболочка, бумажное поле, следующий шаг, импорт, обзор продаж, прогноз, закупка, сведения об утверждении, склад и справочники. Фильтры и позиция списков сохраняются при возврате в том же филиале. [Карта реализации и адаптации](docs/design/IMPLEMENTATION_RU.md). Build PASS; итоговый browser **115 PASS / 1 timeout / 2 предусмотренных skip**, отдельный повтор timeout **1/1 PASS** без правок, складские live отдельно **1/1 + 1/1 PASS**. Это отдельные прогоны. История исправлений и границы проверки — [PROGRESS](templates/PROGRESS.md), [свидетельство](artifacts/verification/web-redesign-20261013.json). Проверочные сервисы остановлены, пользовательская база не менялась. APK, production и реальный бизнес-пилот в эту задачу не входят.

## 12.10.2026 — казахский текст вычитан; перед выпуском повторить браузерный набор

Тексты KK/RU выверены независимой вычиткой (67 правок, единая терминология). Python 503: 502 PASS + 1 skip, build PASS, складские live 1/1 + 1/1. Браузерный набор на перегруженной машине дал таймауты (каждый тест прошёл хотя бы раз, единого чистого прогона нет): перед следующим архивом выпуска повторить его, закрыв тяжёлые приложения. Детали — верхняя запись [PROGRESS](templates/PROGRESS.md).

## 11.10.2026 — demo по умолчанию казахстанский; дальше решение по праздникам или сервер

Новый demo-набор `data/kz` (Кызылорда) загружается `start.ps1`/`seed_demo.py` по умолчанию; исходный `data/raw` сохранён для исследования и тестов. Локальный `.env` (вне Git) указывает на `data/asboljam-kz.sqlite`; прежняя `data/asboljam.sqlite` не изменена. Проверки и границы — верхняя запись [PROGRESS](templates/PROGRESS.md), [требования РК](docs/commercial/KAZAKHSTAN_LAUNCH_RU.md). Открытые решения владельца: признак праздников РК в прогнозе (backlog №10), сервер/домен в РК (§9 DEPLOYMENT_VPS). Новый архив выпуска с этим изменением ещё не собран.

## 11.10.2026 — финальный архив v3 проверен; дальше сервер/домен или mobile

Последний проверенный архив: `releases/2026-10-11-final-3/AsBoljam_Final.zip` (commit `137a17d`, SHA256 `4afdeb480d94a222e790855c93a14efc21b58f462dbe38f7ad6d74e094532bf5`): чистая установка, HTTP 87/87, browser 91/91, SQLite restore 14/14. Детали — верхняя запись [PROGRESS](templates/PROGRESS.md), [свидетельство](artifacts/verification/release-20261011-final-3.json). Для production нужны решения владельца ([DEPLOYMENT_VPS_RU §9](docs/commercial/DEPLOYMENT_VPS_RU.md)). Независимо: backlog №5 (аудит живого onboarding), №6 (надёжность заданий), №7 (mobile: Expo update, APK, эмулятор). Проверочные установки остановлены и лежат вне Git в `C:\Users\ASUS\AsBoljam-install-check`.

## 11.10.2026 — готов вариант запуска на VPS; нужен сервер/домен

Production-overlay с HTTPS, backup PostgreSQL и проверка TLS готовы и проверены локально ([DEPLOYMENT_VPS_RU](docs/commercial/DEPLOYMENT_VPS_RU.md), [отчёт](artifacts/verification/deployment-config-20261011.json)). Реальный deploy ждёт решений владельца: хостинг/расположение данных, домен/DNS, оператор сервера, внешнее хранение копий, данные первой организации. Независимо можно продолжать backlog №5–7.

## 11.10.2026 — финальный ZIP проверен; дальше нужны сервер/домен или mobile

Финальный архив `releases/2026-10-11-final/AsBoljam_Final.zip` (commit `fc0af29`, SHA256 `da5abe1b0dc6e0e5005e82b583b02302634825ee58c9e6cc4d8d36764036ee1f`) установлен с нуля и прошёл HTTP 87/87, browser 88/88 (включая REAL/TEST и складские live), SQLite restore drill 14/14; ранее на том же коде — PostgreSQL suites 77/77, Docker/Nginx 87/87, PostgreSQL restore drill 13/13. Детали — верхняя запись [PROGRESS](templates/PROGRESS.md) и [свидетельство](artifacts/verification/release-20261011-final.json). Следующее по [backlog](docs/commercial/LAUNCH_BACKLOG_RU.md): пакет целевого развёртывания (нужны сервер/домен/решение владельца), onboarding/неполные данные, надёжность заданий, mobile (Expo update + APK + эмулятор). Проверочные установки лежат вне Git в `C:\Users\ASUS\AsBoljam-install-check`; процессы остановлены.

## 11.10.2026 — PostgreSQL и восстановление проверены, следующий шаг — финальный ZIP

Проверено на финальном коде: PostgreSQL suites 77/77 (повтор после исправления учёта раннера), Docker/Nginx workflow 87/87, учение по восстановлению PostgreSQL 13/13, полная регрессия (490 PASS + 1 skip; в venv из lockfile после исправления теста `test_worker_process` 13/13). Детали — [PROGRESS](templates/PROGRESS.md), [свидетельство](artifacts/verification/launch-readiness-20261011.json). Следующее: финальный ZIP → установка → полный browser-suite с REAL/складскими фикстурами → SQLite restore drill. Compose-проекты `asboljam-logcheck-*` и `asboljam-final-*` остановлены, volume сохранены.

## 11.10.2026 — остановлено по просьбе владельца во время проверки RC

Диагностика request → job закрыта (commit `347d90d`). Затем начата приёмка выпуска: RC ZIP из `347d90d` установлен с нуля, HTTP workflow 87/87, но browser-suite выявил медленный dashboard (до 22 с). Исправление производительности freshness и e2e-тестов закоммичено; полная Python-регрессия после него: 491 тест, 490 PASS + 1 POSIX skip; PostgreSQL, новый RC, browser-suite и restore-учение ещё не выполнены. Точное состояние, проверки и следующие шаги — верхняя запись [PROGRESS](templates/PROGRESS.md), порядок работ — [LAUNCH_BACKLOG_RU](docs/commercial/LAUNCH_BACKLOG_RU.md). Новый финальный ZIP после исправления ещё не создан.

## 11.10.2026 — диагностика завершена, следующий шаг — установка из ZIP

**DONE / TESTED:** интеграция request → job из прошлого локального diff закончена, проверена и закоммичена (детали — [PROGRESS](templates/PROGRESS.md), [отчёт](artifacts/verification/request-logging-20261011.json)): полная регрессия 490 (489 PASS + 1 POSIX skip), настоящий uvicorn, Docker/Nginx/PostgreSQL workflow 87/87. Изолированный compose-проект `asboljam-logcheck-*` остановлен без удаления; старый `asboljam-verification` не тронут.

**Следующее:** [backlog запуска](docs/commercial/LAUNCH_BACKLOG_RU.md) №2 — новый ZIP из чистого commit, установка в отдельную папку, `verify_runtime.py`, затем №3 backup/restore. **BLOCKED внешне:** пилот (предприятие), production deploy (домен/сервер/решение владельца).

## 11.10.2026 — передача в новый чат / Claude Code

Основной подробный контекст теперь в [README.md](README.md): 18 разделов, полный продуктовый workflow, архитектура, данные/алгоритмы/права, фактические evidence и готовый промпт. Перед продолжением читать текущие git status/diff; старые записи ниже остаются историей этапов.

**DONE:** складской count-anchor этап и проверенный ZIP; базовый allowlisted emitter c9b288a (5/5 на сохранённой версии). **IN PROGRESS:** локальный diff apps/api/main.py, apps/worker/main.py, новый request_logging.py и18 worker logging tests, infra/launchers/access logging, добавление flush test. Итог начатого worker-test запуска недоступен, поэтому PASS не подтверждён; tests/test_request_logging.py отсутствует. Эти изменения не отправлялись как завершённая интеграция. В новом clone их может не быть. Ближайший scope и конкретные критерии — [README§15.1](README.md#observability-next); сначала закончить и проверить его, без повторного scaffold или ненужного повторения прежних тяжёлых проверок.

**TESTED этого обновления:** статическая сверка README с кодом/evidence,73 ссылки,19 anchors,9 точных CSV-схем, Markdown fences. **NOT TESTED:** новые runtime/build/research/APK/production прогоны; ради документации не запускались. Локальный app diff сохранён. Последний source ZIP ниже соответствует своему manifest commit, не новому README/диагностике.

Последний локальный source ZIP: `releases/2026-10-10-count-anchor/AsBoljam_Final.zip`, source commit `a3d5038fde409a913dd48d45f2dc4570fb19d1e7`, 303 файла, 1791761 байт. CRC/все хеши и независимая проверка PASS. SHA256: `45da77922c55e19a66048e8dc4c9b112e7ea7ffa59028891c3c62b3bc5066e01`. [Манифест результата упаковки](artifacts/verification/release-20261010-count-anchor.json). Последующий commit содержит свидетельство упаковки, не новую функциональность. Продолжать с текущего Git HEAD, сохраняя исходные ZIP и приватные backup. Установка из архива, production и новый APK не проверялись.

## 10.10.2026 — текущее продолжение полностью локально

Репозиторий `bltangenss/asboljam-diploma`, ветка `main`. Cloud отменён пользователем. Ограничение по расходу лимита снято. Не пересоздавать проект и не повторять прошедшие тяжёлые проверки без причины.

**DONE:** migration0008 и неизменяемые документы принятия нового посчитанного остатка: admin/manager, причина, раскрытые разницы, обязательное подтверждение, версия/fingerprint/idempotency и аудит. Старый baseline не перезаписывается. Даты и движения выбирают основу своего периода; версия журнала и последовательность движений раздельны. Обратная запись через принятый пересчёт запрещена. Изменение REAL/source identity этим документом не разрешается. API и migration commits63ca259/ea5e7b0 отправлены в origin/main.

**TESTED:** полный Python454:453PASS+1POSIXskip,0failures/errors,512.179s, стабильные исходники; [регрессия](artifacts/verification/count-anchor-regression-20261010.json). PostgreSQL80/80 (79PG+1pure engine), source stable; [отчёт](artifacts/verification/postgres-count-anchor-20261010.json). Основная SQLite0007→0008 после verified backup,21 прежняя таблица без изменений, новая пустая; [миграция](artifacts/verification/count-anchor-main-migration-20261010.json). Browser mocks29/29 + отдельный live1/1 с первой попытки на generated REAL/TEST fixture, настоящие API/worker, старый approved CSV побайтно неизменен; web build PASS. [Browser evidence](artifacts/verification/stock-count-anchor-web-20261010.json). После полного Python изменён только browser-fixture helper:85 REAL/TEST дней для двух origin; SYNTHETIC84 сохранены, приложение неизменно. PG и созданные API/worker/web остановлены; старые БД/volumes сохранены. Тестовые credentials, базы, traces и backup остаются ignored; не включать их в Git/ZIP. [Runbook](docs/commercial/STOCK_BROWSER_TEST_RU.md).

**Следующая конкретная разработка после закрытия текущих проверок:** безопасная связь HTTP-запроса с жизненным циклом задания. Сейчас нет server-generated request ID, а timeout и часть штатных отказов worker не видны в логах. Добавить allowlisted JSON events: request method/route-template/status/duration, enqueue после commit, claimed и committed-terminal/discarded с job_id. Исключить payload/query/raw path/credentials/user reason/exception repr/DB URL. Нужны проверки параллельных request IDs, sentinels на утечки, timeout/отзыв доступа, rollback и CAS-loser без ложного success. Основные файлы main.py API/worker и новый observability helper; новая БД/провайдер telemetry не требуются. Это локальный следующий участок, не подтверждение production/pilot.

**NOT TESTED / внешний BLOCKED:** реальный POS/пилот, production и новая native-сборка. Не объявлять весь коммерческий запуск завершённым по этому локальному этапу.

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

## Текущий этап — REAL-контракт и даты, 29.09.2026

**Остановлено с сохранением по просьбе пользователя.** Это checkpoint, не окончательно проверенный release. Python295 и PG158 прошли до последних исправлений; mock37 PASS; live8/9, один correction-сценарий требует повтора после исправления SQLite worker. Последние точечные проверки: contention6, worker security11, REAL execution19, REAL API12 PASS. Финальный общий/PG/browser повтор не выполнен. Запущенные тестовые сервисы остановлены, базы/volumes сохранены.

Работа выполнена локально в существующем проекте. Миграция0004 добавляет явную регистрацию источника для пустой организации; SYNTHETIC-демо и его даты сохранены. Web/API/worker/import/approval/export передают согласованные источник, timezone, origin и target. REAL требует законченный день, полную историю и точный известный остаток. Сгенерированный набор отмечен TEST; он не является данными предприятия. Native REAL пока возвращает явный403.

Исправлена остановка worker при временной блокировке SQLite: повтор транзакции сохраняет вычисленный результат и защиту от двойной публикации. Предыдущие строки основной БД после0004 сохранены; private backup проверен. Проверки и ограничения: [актуальный PROGRESS](templates/PROGRESS.md), [real-platform.json](artifacts/verification/real-platform.json), [runbook REAL](docs/commercial/REAL_DATA_OPERATIONS_RU.md).

Следующие участки — stock ledger, heartbeat и эксплуатационные gates; бизнес-пилот требует предприятия. Общая коммерческая цель не завершена. APK/ZIP/research этим блоком не обновлялись. Не повторять успешные тяжёлые проверки без изменения их исходников или конкретного сбоя. Ниже — история; старые утверждения о закрытом REAL относятся к прежним версиям.

## Текущий этап — история импорта и проверяемость расчётов, 29.09.2026

Работа продолжается локально. Миграция0003 добавляет provenance/receipts/revisions без переписывания прежних данных. Идентичные строки повторно не вставляются; sales/calendar/inventory исправляются явно, с причиной, версиями и атомарным commit. История следует текущим tenant/branch/role правам. Forecast/procurement сохраняют входные версии и ссылки на загрузки; перед утверждением изменённых данных нужен пересчёт. Старые утверждённые решения и экспорт сохраняются. [Runbook](docs/commercial/IMPORT_OPERATIONS_RU.md).

**Проверено:** Python242 PASS; PostgreSQL runner109 PASS (108 PG + один SQLite backup case); web build; mock browser31 PASS. Live — семь успешных сценариев в общем прогоне и успешный отдельный повтор восьмого после уточнения селектора preview. Настоящие API/worker проверили correction/stale/recompute/approval/export и HGB; [точные результаты](artifacts/verification/import-platform.json). Устранены неполная CSV-validation без предупреждения и сброс введённого пароля при обновлении metadata.

Основная SQLite0003 обновлена после private backup; прежние table counts совпали. Тестовые процессы остановлены, базы/volumes сохранены. Цель рынка остаётся активной: следующие участки — REAL/date policy, stock ledger, heartbeat и эксплуатация. REAL-импорт пока закрыт; APK/ZIP/research не обновлялись. Исторические результаты ниже не подменяют актуальный [PROGRESS](templates/PROGRESS.md).

## Текущий этап — организации и onboarding, 29.09.2026

Миграция0002 добавляет Organization и сохраняет прежние данные; реализованы bootstrap пустой организации/первого admin и suspend/resume. API/worker запрещают доступ отсутствующей или suspended организации, unconfigured оставляет настройку аккаунта. CLI требует явной БД, поддерживаемой схемы, preflight/apply и скрытого пароля. [Runbook](docs/commercial/TENANT_OPERATIONS_RU.md).

Web показывает реальные metadata и пустые состояния, обновляет доступ к первому филиалу без logout, не выдаёт демо-даты за отсутствующую историю. **Проверено:** полный Python196 PASS плюс финальный CLI10 PASS; PostgreSQL runner64 PASS (63 PG + один SQLite backup case); build, mock browser22 и live browser7 PASS. Команды и ограничения: [PROGRESS](templates/PROGRESS.md), [tenant-platform.json](artifacts/verification/tenant-platform.json), [PG](artifacts/verification/postgres-tenant-platform.json).

Тестовые процессы остановлены, базы/volumes сохранены. Основная SQLite обновлена после backup: прежние table counts совпали, backfill7 организаций. Следующие задачи — REAL/provenance, повторяемый импорт, stock ledger/эксплуатация. Цель рынка активна; REAL-импорт/deployment/экономия не подтверждены. APK/ZIP этим блоком не обновлялись. Ниже — история.

## Текущий этап — пароли и реальная PostgreSQL-проверка, 29.09.2026

Добавлены web/API смена своего пароля и `scripts/manage_password.py` для операторского восстановления. Пароли не принимаются CLI-аргументами и не возвращаются в validation errors; сессии и pending jobs отзываются атомарно. Login/refresh сериализованы с reset. [Runbook](docs/commercial/SECURITY_RUNBOOK_RU.md) содержит preflight/apply и ограничения; публичного email reset нет.

Текущие результаты: **157/157 Python PASS**, **39/39 real PostgreSQL security checks PASS**, web build PASS; **14/14 mock browser** и **6/6 live browser workflow PASS**, включая реальную смену пароля и HGB. PostgreSQL-блокировка из предыдущего блока снята запуском установленного Docker Desktop; новых образов не скачивали, существующие базы сохранялись. Проверки использовали новые тестовые БД/организации; реального клиента нет. Итоговые команды и уточнения responsive-повтора: [PROGRESS](templates/PROGRESS.md), [account-security.json](artifacts/verification/account-security.json).

Цель рынка остаётся активной. Следующий участок: tenant model/bootstrap, затем отдельная REAL/provenance граница и stock ledger. [Полная матрица незавершённых условий](docs/commercial/RELEASE_GATES_RU.md) не позволяет принять локальное демо за готовый коммерческий выпуск. Ниже — история предыдущих блоков, её старые BLOCKED/NOT TESTED читать с учётом этого обновления.

## Обновление 29.09.2026 — локальная коммерческая основа

Продолжена существующая `main` от `f0b8354`, без реального предприятия и без Cloud. API/web теперь соблюдают read-only роль analyst; worker не публикует результат после отмены/отзыва доступа или потери своей аренды. Добавлены проверки среды до подключения к БД, запрет production demo seed, безопасные ошибки и устойчивость CSV-парсера/quality summary. Организации с одинаковыми branch/entity IDs проверены раздельно. Публичной регистрации tenant и REAL импорта пока нет.

Текущая проверка: **131/131 Python PASS (28.061 s)**; web build PASS (9.61 s); **8/8 Chrome session/import/role tests PASS (10.0 s)** на production web bundle с mock API. Первые browser попытки были заблокированы/провалены из-за Vite dev `spawn EPERM`; финальный preview run прошёл. Настоящие API/SQLite/worker вычисления проверены Python API suite. Старые PostgreSQL/runtime/CUA отчёты ниже относятся к предыдущему коду и не доказывают новые изменения на этих средах.

Следующий технический шаг: проверить отзыв/публикацию на PostgreSQL и полный browser workflow обновлённого API/worker. Docker Desktop сейчас не запущен (Linux engine pipe отсутствует). Затем — проверяемое создание организации/первого администратора, reset password, heartbeat долгих задач. Реальные данные не нужны для этих локальных работ; пилотные метрики требуют бизнеса.

Команды, ограничения и результаты: [актуальный PROGRESS](templates/PROGRESS.md), [отчёт проверки](artifacts/verification/commercial-hardening.json), [runbook среды и доступа](docs/commercial/SECURITY_RUNBOOK_RU.md). APK и ZIP не пересобирались в этом блоке. Следующий текст — исторический снимок с уточнениями последующих этапов.

Снимок состояния: 24.09.2026. Продолжать существующий код; не начинать проект заново. Этот файл описывает выполненную работу и воспроизводимые команды. Создание файла не означает подключения Codex Cloud или успешного deployment. Последующие результаты фиксируются в [PROGRESS](templates/PROGRESS.md).

## 1. Название проекта

**AsBoljam** — дипломная система планирования продаж, ингредиентов и закупок для общественного питания.

## 2. Цель проекта

Довести до проверяемого рабочего состояния цепочку: CSV → предварительная валидация → транзакционный импорт → продажи → однодневный прогноз → рецептуры → потребность → годный запас → предложения → MILP → план → решение менеджера → аудит → экспорт. Основной язык UI — казахский; русский переключатель уже реализован. По актуальному решению пользователя разработка и проверки выполняются локально; Codex Cloud отменён.

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
- Исходники native-клиента, SecureStore и проверки сессий; локальные Android x86 и arm64-v8a debug development APK собраны. Это не подписанный release APK/IPA и не проверка устройства.

## 5. Что только специфицировано или ещё отсутствует

Реальные данные предприятия и live-интеграция POS/ERP, подтверждённая экономия, прогнозы 7/14/30 дней, полноценный журнал движения запасов, автоматическая отправка заказов, production-наблюдаемость и SLA, подписанные магазинные сборки. UI организации сейчас преимущественно только для чтения. Offline CSV mapping реализован для sales/inventory: [POS_ADAPTER_RU.md](docs/POS_ADAPTER_RU.md). Он сохраняет происхождение REAL/SYNTHETIC; приложение пока намеренно не принимает REAL. Нет заявлений об интервью, внедрении или доступе к внешним аккаунтам.

## 6. Какие проверки действительно проходили

Подтверждённые отчёты находятся в `artifacts/verification`, итоговая матрица — в [FINAL_REPORT.md](FINAL_REPORT.md).

- Python: 59/59 PASS за 20.364 s (19 API, 14 engine, 4 backup, 19 POS adapter, 3 research-origin guards).
- PostgreSQL 17.11: 19/19 API tests PASS за 24.341 s на отдельной новой тестовой БД. Все девять операционных CSV загружены; дополнительная строка smoke-import объясняет 26317 продаж в runtime при 26316 в исходнике.
- Внешний HTTP через nginx и отдельный worker: 77 проверок PASS. Это отдельное свидетельство от проверки фактического PostgreSQL dialect.
- pg_dump/pg_restore: восстановление в новую БД PASS; совпали количества всех таблиц, password hashes и marker миграции. Полный хеш содержимого всех таблиц не сравнивался.
- Linux Docker images построены; проверены API/PostgreSQL health, web/worker и HTTP 200 для SPA fallback/API proxy. После проверки контейнеры остановлены без удаления volumes.
- Web TypeScript/Vite build PASS: 1749 modules, 8.19 s. Mobile typecheck и 13 session tests PASS; Metro/Hermes Android JS export PASS (588 modules, 20.831 s). После решения пользователя продолжить APK собраны Android debug development APK: x86 — 60911179 bytes, SHA256 `73a0e4c3a56fe7d2c95ea830771f8c4b4f9dc820502a4953f404d4af220e82b2`; arm64-v8a — 59830847 bytes, SHA256 `fd9e925e090e05e2285351c02e86564bc2aa5b23bde47887af27b51e85f0f82d`.
- Research: 9 прогнозов и 36 закупочных сценариев, 35.085184 s, сохранены provenance и SHA256.
- Windows start/stop реально выполнены: API/web 200, после остановки порты закрыты. Ветка `-Install` launcher отдельно не запускалась; зависимости устанавливались самостоятельными командами.
- После возобновления: отдельные 10/10 packaging tests PASS, 3.052 s; общий Python suite из 69 тестов повторно не запускался. Проверены временные fixture-архивы, финальный ZIP не создан. [Отчёт](artifacts/verification/packaging-tests.json).
- Реальный браузерный сценарий через Codex in-app browser / CUA PASS в перечисленном объёме: login, CSV validation/commit, sales, baseline forecast через отдельный worker, procurement, approval, audit/download event, recipes/inventory, второй филиал, RU, dashboard 360 px и logout. Использованы собранный Vite preview с `--configLoader native` и отдельная ignored SQLite DB; mock API нет. [Результат и ограничения](artifacts/verification/browser-cua.json).

Полный Playwright suite и device/native release имеют отдельные статусы ниже; CUA workflow не заменяет полный набор браузерных тестов. Успешные тяжёлые расчёты не повторяются без изменений связанных компонентов.
## 7. Какие проверки падали или пока не подтверждены

Повторный `npm.cmd run test:e2e` заблокирован средой до старта тестов: выполнено 0 из 11, `spawn EPERM` в `child_process.fork / WorkerHost.startRunner`. Расширенный повтор автоматически отклонён политикой `sandbox_approval=false`. [browser.json](artifacts/verification/browser.json) сохраняет результат; полного Playwright PASS нет.

Предыдущий связанный Playwright run был прерван по запросу пользователя: шесть session/import-race проверок PASS, сквозной workflow превысил общий timeout 180 s, ещё четыре сценария не завершены. Сохранённый trace подтверждает 119.09 s ожидания прогноза и 25.97 s ожидания закупки; approval/export выполнены, общий лимит исчерпан далее в UI. Для длинного теста выделено 360 s при сохранении отдельных job/assertion limits. [Старый прерванный прогон](artifacts/verification/browser-interrupted.json) не считается PASS.

CUA workflow имеет ограниченный объём: скачивание подтверждено download event и HTTP 200, но bytes отдельно не проверялись; offline injection, stale approval race, analyst role и HGB chart не повторялись. В рассчитанном плане нет дефицита, поэтому отдельный checkbox подтверждения дефицита не требовался. Нет полного visual regression/accessibility audit. После CUA проверки её browser/API/worker/preview остановлены.

Первая Android debug build после успешного Expo prebuild завершилась ошибкой foojay plugin `JvmVendorSpec.IBM_SEMERU` на JDK21/Gradle9; [исходный результат](artifacts/verification/android-build-initial-failed.json) сохранён. Resolver 1.0.0 устранил эту ошибку; следующая попытка дошла до CMake и ранее была остановлена пользователем. 25.09.2026 build возобновлён: `scripts/build_android_debug.ps1 -Architecture x86` завершился PASS за 4m04s, затем `scripts/build_android_debug.ps1 -Architecture arm64-v8a` завершился PASS за 4m54s. [android-build.json](artifacts/verification/android-build.json) фиксирует актуальный arm64-v8a result; x86 сохранён в [android-build-x86.json](artifacts/verification/android-build-x86.json). Копии для передачи: `releases/AsBoljam_Debug_arm64-v8a.apk` и `releases/AsBoljam_Debug_x86.apk`. Устройство не проверено.

Codex Cloud не запускался и теперь отменён пользователем. Android device runtime, release APK, production TLS/load/SLA и реальные данные предприятия требуют собственных результатов; их нельзя выводить из Python tests, Compose configuration, Metro export или debug APK.
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

Web: `npm run build`, результат `dist/web`, preview: `npm run preview`. Native TypeScript check не создаёт APK/IPA. Локальный debug APK собирается командой `powershell -NoProfile -File scripts/build_android_debug.ps1 -JavaHome 'C:\Program Files\Java\jdk-21' -AndroidSdk '.cache/android-sdk' -Architecture arm64-v8a`; для x86-эмулятора заменить architecture на `x86`. Результат development build требует Metro для JavaScript. Android device или macOS/Xcode, release signing и Store publication проверяются отдельно. Docker image build: `docker compose build` после подготовки окружения. Нельзя объявлять native/cloud deployment по успешному web build.

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
- PRIVATE origin подтверждён: `https://github.com/bltangenss/asboljam-diploma`; push main до `24d2dde` прошёл. Cloud environment не подтверждается наличием remote или скриптов. Не записывать токены в проект.
- Историческая блокировка `.git/index.lock` снята пользователем через полный доступ к рабочей среде; локальные коммиты снова создаются. Итоговый hash и push фиксируются после завершения доставки.
- Windows-проверки не доказывают Linux/macOS/Android/iOS совместимость. Подробный перечень NOT TESTED сохранять в progress.

## 19. Следующий этап разработки и статус Cloud

Пользователь отменил Codex Cloud и возобновил полностью локальную разработку. Продолжать существующий PRIVATE repository `bltangenss/asboljam-diploma`, branch `main`; актуальный список выполненного и оставшегося — [PROGRESS](templates/PROGRESS.md). Основной CUA workflow уже проверен; полный Playwright suite требует снятия ограничения на subprocess. Android x86 и arm64-v8a debug APK собраны; следующий native шаг — установка на устройство/эмулятор или отдельная release-сборка, если потребуется. Не повторять успешные тяжёлые проверки без связанных изменений.

Финальный `releases/AsBoljam_Final.zip` создаётся после финального commit из чистого Git checkout. `python scripts/package_release.py` по умолчанию требует чистый checkout и упаковывает точные committed blobs. Явный `--working-tree` проверяет снимок tracked/untracked nonignored файлов и фиксирует `source_commit: null`, `base_commit: HEAD`, `includes_uncommitted_changes: true`; это не commit/push. Оба режима проверяют CRC и SHA256 исходных файлов после записи, исключают секреты/БД/dependencies/caches и не перезаписывают существующие ZIP/sidecar. Фактические число файлов и SHA256 фиксируются выводом упаковщика и sidecar.
Cloud task не создан: штатный CLI при обращении к этому репозиторию вернул `environment_repo_access_failed`. Поскольку Cloud отменён, это не блокирует локальную разработку и не требует авторизации пользователя сейчас.

Скрипты для возможного будущего Linux Cloud сохранены, но там не выполнялись: Python 3.13, Node.js 24, setup `bash scripts/cloud_setup.sh`, переменные `LOKY_MAX_CPU_COUNT=1`, `PLAYWRIGHT_CHANNEL=chromium`; приложение не требует OpenAI API key. Проверки этого варианта запускаются командой `bash scripts/cloud_verify.sh` только при отдельном решении использовать соответствующую среду. [Официальная документация среды](https://learn.chatgpt.com/docs/environments/cloud-environment).
## 20. Условия полной готовности

Для демонстрационного выпуска: чистый checkout устанавливается, миграция/seed воспроизводимы, API и настоящий worker проходят полную пользовательскую цепочку, роли/изоляция/CSRF/идемпотентность/конкурентное утверждение проверены, график/метрики/дефицит/единицы корректны, backups восстанавливаются, web build и нужные native проверки подтверждены. После изменения кода связанные проверки повторены, статусы честны, безопасный финальный ZIP читается и включает исходники/контракты/данные/lockfiles.

Для cloud handoff: приватный remote и push реально подтверждены, владелец дал доступ cloud к репозиторию, setup и verify выполнены именно в cloud, результат/ссылка на задачу записаны. Для production дополнительно нужны реальный адаптер, эксплуатационные ограничения, HTTPS, нагрузочные/security проверки, мониторинг и восстановление PostgreSQL. Эти условия не считаются выполненными только потому, что создан локальный Git.

