# Predas — спринт к Startup / Idea Battle (3 часа, 4 человека)

Цель: за 3 часа стабилизировать продукт, подготовить живую демонстрацию, видео и питч. Новых больших функций не начинаем — доводим и показываем то, что есть.

## Состояние на старте (20.10.2026)

- `main` = `69008ae`. Работают: регистрация заведения и демо-данные одним нажатием, прогноз на завтра (4 модели, 20 факторов дня, 31 город, погода), склад, закупка с утверждением человеком, печать плана приготовления, закрытие дня с телефона.
- Этап 2 (сверка «прогноз против факта», рабочий вариант плана, задачи «Сегодня», объяснения прогноза) **в коде есть, но не доведён**: 2 браузерных сценария падают, полная регрессия не запускалась, миграция `0012` на демо-базу не применена. См. `docs/commercial/WORKDAY_REVIEW_RU.md`.

## Распределение

| Кто | Роль | Результат | Файлы (только свои!) |
|---|---|---|---|
| Болат Танирберген | Лидер, интегратор, спикер; тексты KK/RU | Исправленные тексты (до T+1:30), слитый и проверенный `main`, стенд для живого демо, тег релиза | строки в `apps/web/src/{DayClose,GetStarted,Profile,Register}.tsx`; `templates/*`, `README.md`, `FINAL_REPORT.md`, `CLOUD_HANDOFF.md`; слияние PR |
| Карабек Дамир | Стабилизация этапа 2 | Зелёные тесты этапа 2 и полная регрессия (PR к T+1:45) | `apps/api/{forecast_review,forecast_explanation,workday_tasks,working_plan}.py`, `apps/web/src/{ForecastReview,ForecastExplanation,WorkdayTasks,WorkingPlan}.tsx`, `workdayData.ts`, `forecast-review.css`, их тесты, `tests/e2e/workday_review.spec.ts` |
| Жорабек Бекзат | Демо-стенд, сценарий показа, видео | Скрипт подготовки демо-кабинета, сценарий живого показа (PR к T+1:45), демо-видео RU/KK (T+2:00–2:30) | `scripts/prepare_battle_demo.mjs` (новый), `docs/BATTLE_DEMO_RU.md` (новый), `scripts/record_demo_video.mjs`, `apps/web/src/predas.css` |
| Сарсенбаева Айдана | Питч (через Codex) | Веб-презентация с заметками спикера, автоматические скриншоты продукта, PDF, речь на 3 минуты, ответы на вопросы (PR к T+1:45) — задача D в `CODEX_TASKS_RU.md` | `docs/pitch/**`, `scripts/capture_pitch_screens.mjs`, `scripts/export_pitch_pdf.mjs` (новые) |

Чужие файлы не трогать. Нужна правка в чужом файле — напиши владельцу. Отложено на после баттла: обновление `docs/user-guide/USER_GUIDE_KK.md` под интерфейс Predas.

## График (T = старт)

- **T+0:00–0:20** — клонировать репозиторий, создать свою ветку, у кого есть код — запустить проект.
- **T+0:20–1:45** — работа, маленькие коммиты, push своей ветки каждые 20–30 минут. Болат правит тексты и коммитит их в `main` до T+1:30.
- **T+1:45** — Pull Request в `main`. Порядок слияния у Болата: Дамир → Бекзат → Айдана.
- **T+2:00** — заморозка кода. После неё только исправления, которые Болат явно разрешил.
- **T+2:00–2:30** — Болат прогоняет проверки на слитом `main` и готовит стенд; Бекзат записывает видео на слитом `main` и проходит живой сценарий.
- **T+2:30–3:00** — репетиция питча с живым демо и запасным видео.

## Общие правила для всех

- Ветка: `team/<имя>-<тема>` от свежего `origin/main`. В `main` напрямую пушит только Болат.
- Перед каждым коммитом: `git diff --cached --stat`, затем `python scripts/check_secrets.py --staged`, затем `git checkout -- artifacts/security-scan.json`.
- Никогда не коммитить: `.env`, базы `*.sqlite`, `backups/`, `.cache/`, `node_modules/`, `.claude/`, видео, пароли. `--force` не использовать.
- Данные проекта синтетические (SYNTHETIC). Не выдумывать клиентов, выручку, экономию и точность.
- Тесты и импорт `apps.api.main` — только с отдельной базой (`DATABASE_URL` на временный файл), не на рабочей.

## Установка (для тех, кто запускает код)

```powershell
git clone https://github.com/bltangenss/asboljam-diploma.git predas
cd predas
git checkout -b team/<имя>-<тема> origin/main
copy .env.example .env
# в .env впишите свой DEMO_PASSWORD (12+ символов, никому не отправлять)
.\scripts\start.ps1 -Install
```

Сайт: http://localhost:3000 · вход `admin@asboljam.local` с вашим `DEMO_PASSWORD` · остановка `.\scripts\stop.ps1`. Первый запуск с `-Install` может занять 10–20 минут — начните его сразу.

---

## Промпт 1 — Болат Танирберген (лидер, тексты, интеграция, стенд, спикер)

```text
Ты — ведущий разработчик и интегратор проекта Predas (бывший AsBoljam), репозиторий
bltangenss/asboljam-diploma, моя папка C:\Users\ASUS\Desktop\Diplomwork (ветка main).
У нас 3 часа до Startup/Idea Battle. Команда из четырёх человек работает параллельно в
ветках team/*; план и владение файлами — в docs/team/SPRINT_BATTLE_RU.md. Прочитай его,
AGENTS.md и верхние записи templates/PROGRESS.md.

Твои задачи по времени:
1. T+0:00 — git fetch; git status; git pull --ff-only origin main. Убедись, что рабочая
   копия чистая (папку .claude/ не коммитить). Сделай резервную копию демо-базы:
   python scripts/backup_db.py backup --database data/asboljam-kz.sqlite
   --output backups/asboljam-kz-before-battle-20261020.sqlite
2. T+0:20–1:30 — тексты KK/RU (пока ждёшь PR). Пройди экраны «Тіркелу / Регистрация»,
   «С чего начать» (пустой кабинет), «Профиль», «Закрыть день» на казахском и русском.
   Исправь опечатки, неестественные и слишком технические формулировки — только строки
   внутри apps/web/src/DayClose.tsx, GetStarted.tsx, Profile.tsx, Register.tsx. Логику и
   имена классов не меняй. Подписи, на которые опираются tests/e2e/day_close.spec.ts,
   predas_shell.spec.ts, registration_places.spec.ts: если меняешь — поправь и тест.
   Проверь: npm run build; python scripts/generate_contracts.py (затем JSON к LF);
   npx playwright test tests/e2e/day_close.spec.ts tests/e2e/predas_shell.spec.ts
   tests/e2e/registration_places.spec.ts на отдельной базе. Закоммить и запушь в main
   до T+1:30, чтобы остальные успели подтянуть.
3. Параллельно следи за PR от Дамира, Бекзата, Айданы. Каждый PR проверяй: только свои
   файлы по таблице, нет секретов, БД, видео, .cache; в описании перечислены реально
   прошедшие проверки.
4. T+1:45–2:00 — сливай PR по порядку: Дамир → Бекзат → Айдана. После каждого слияния:
   git pull --ff-only, npm run build. При конфликте решай его в ветке автора вместе с ним.
5. T+2:00 — заморозка. На слитом main (с изолированным DATABASE_URL):
   python -X utf8 -m unittest discover -s tests -p "test_*.py"
   npm run build
   браузер — хотя бы tests/e2e/workday_review, day_close, today_workflow, predas_shell,
   workflow (полный набор идёт около 25 минут — запускай, только если есть время).
   Запиши точные числа.
6. Стенд для живого демо: останови превью, затем .\scripts\start.ps1 (миграция 0012
   применится к демо-базе — резервная копия уже есть). Проверь /api/v1/ready. Вместе с
   Бекзатом запусти scripts/prepare_battle_demo.mjs на копии базы. Держи открытыми:
   готовый демо-кабинет, запасное видео от Бекзата, скриншоты.
7. Документы: добавь в templates/PROGRESS.md запись «20.10.2026 — спринт к Idea Battle»
   (DONE / TESTED с точными числами / NOT TESTED / BLOCKED), сверху FINAL_REPORT.md и
   CLOUD_HANDOFF.md — актуальное состояние. Коммит, проверка секретов, push в main.
   Тег: git tag battle-2026-10-20 && git push origin battle-2026-10-20.
8. T+2:30 — репетиция питча с Айданой: 3 минуты, живое демо по docs/BATTLE_DEMO_RU.md,
   при любом сбое — сразу видео.

Правила: никакого force-push, reset --hard, удаления веток; не используй рабочую базу как
тестовую; не выдумывай метрики. Перед каждым коммитом: python scripts/check_secrets.py
--staged, затем git checkout -- artifacts/security-scan.json. В конце отчёт по-русски:
что слито (хеши), что проверено (числа), что не проверено, хеш тега, результат push.
```

## Промпт 2 — Карабек Дамир (стабилизация этапа 2)

```text
Ты — разработчик проекта Predas (бывший AsBoljam): FastAPI+SQLAlchemy (apps/api),
React+TypeScript+Vite (apps/web), worker с очередью в БД. Репозиторий
bltangenss/asboljam-diploma. Работай в ветке team/damir-stage2 от свежего origin/main.
Срок — 1 час 45 минут, потом Pull Request в main. Новых функций не начинай.

Контекст: этап 2 (сверка прогноза с фактом, рабочий вариант плана, задачи «Сегодня»,
объяснения прогноза) лежит в коммите 5dbe9d4, но не доведён. Прочитай
docs/commercial/WORKDAY_REVIEW_RU.md, верхние записи templates/PROGRESS.md, AGENTS.md,
docs/team/SPRINT_BATTLE_RU.md и файлы: apps/api/forecast_review.py,
forecast_explanation.py, workday_tasks.py, working_plan.py; apps/web/src/ForecastReview.tsx,
ForecastExplanation.tsx, WorkdayTasks.tsx, WorkingPlan.tsx, workdayData.ts;
tests/e2e/workday_review.spec.ts.

Задачи по порядку:
1. Установка: copy .env.example .env, свой DEMO_PASSWORD (12+ символов),
   .\scripts\start.ps1 -Install, затем .\scripts\stop.ps1.
2. Focused Python (с изолированной базой, до импорта apps.api.main):
   $env:DATABASE_URL="sqlite:///<временная папка>/unit.sqlite"; $env:PYTHONPATH="tests;."
   python -X utf8 -m unittest test_working_plan test_day_close test_workday_migration
   test_forecast_review test_workday_tasks test_forecast_explanation -v
3. Браузер: подними API, worker и web на отдельной свежей базе
   (DATABASE_URL на новый файл, затем .\scripts\start.ps1), выполни
   python scripts/prepare_e2e.py, затем npx playwright test tests/e2e/workday_review.spec.ts.
   Два известных падения: «working selection lost reply keeps exact command through global
   navigation and never changes procurement» и «concurrent working selection reloads version
   and requires a new explicit decision». Найди настоящую причину по трассе
   (.cache/pw-results). Чини код; тест меняй, только если его ожидание действительно
   неверно, и объясни почему.
4. Затем: npx playwright test tests/e2e/day_close.spec.ts tests/e2e/today_workflow.spec.ts
   tests/e2e/production_planning.spec.ts tests/e2e/predas_shell.spec.ts; npm run build;
   полная Python-регрессия: python -X utf8 -m unittest discover -s tests -p "test_*.py".
5. Если менял API-схемы — пересобери contracts/openapi.json (create_app().openapi() с
   изолированной базой). Если менял тексты или CSS — python scripts/generate_contracts.py,
   затем приведи JSON к LF.
6. Около T+1:30 подтяни main (git pull --rebase origin main — там будут правки текстов от
   Болата), перепроверь свои тесты и открой PR.

Правила: трогай только файлы этапа 2 и их тесты (Dashboard.tsx — только места виджетов
этапа 2). Пустое значение не превращать в ноль; данные SYNTHETIC; не используй рабочую
базу data/asboljam-kz.sqlite. Перед каждым коммитом: python scripts/check_secrets.py
--staged, затем git checkout -- artifacts/security-scan.json. Маленькие коммиты, push
своей ветки, без --force. В описании PR: что исправлено, точные команды и числа тестов,
что не проверено. Найденные ошибки вне этапа 2 — списком Болату.
```

## Промпт 3 — Жорабек Бекзат (демо-стенд, сценарий показа, видео)

```text
Ты — разработчик проекта Predas (бывший AsBoljam): веб-сервис прогноза продаж и закупок
для столовых и кафе Казахстана. Репозиторий bltangenss/asboljam-diploma, ветка
team/bekzat-demo от свежего origin/main. Срок — 1 час 45 минут до Pull Request; видео
записываешь после слияния (T+2:00–2:30). Прочитай docs/team/SPRINT_BATTLE_RU.md и AGENTS.md.

Цель: живое демо на Idea Battle должно идти гладко за 3 минуты, а запасное видео —
показывать всё то же самое.

Задачи:
1. Установка: copy .env.example .env, свой DEMO_PASSWORD, .\scripts\start.ps1 -Install.
   Работай на копии базы, не на рабочей: задай в .env
   DATABASE_URL=sqlite:///./data/battle-demo.sqlite и запусти .\scripts\start.ps1.
2. Напиши scripts/prepare_battle_demo.mjs (Playwright, по образцу
   scripts/record_demo_video.mjs, без записи видео). На запущенном локальном стенде
   скрипт регистрирует кафе «Достар» (Алматы, тип «Кафе», email вида
   demo-<случайное>@example.invalid, случайный пароль), загружает демо-данные, считает
   прогноз на 01.01.2026, закрывает день 01.01.2026 с правдоподобными тестовыми продажами
   (все строки помечены SYNTHETIC) и считает закупку. Email и пароль пишет только в
   игнорируемый файл .cache/battle-demo-login.json и в консоль — не в git. Скрипт не
   трогает data/asboljam-kz.sqlite.
3. Напиши docs/BATTLE_DEMO_RU.md: точный путь кликов живого демо на 3 минуты (вход →
   «Сегодня» → прогноз → «Закрыть день» → сверка «прогноз против факта», если этап 2
   слит → закупка → утверждение → профиль), одна фраза для спикера на каждом шаге,
   запасной план (видео, скриншоты). Явно напиши, что данные учебные (SYNTHETIC).
4. Видео: расширь scripts/record_demo_video.mjs шагом «Закрыть день» (после прогноза:
   «Сегодня» → «Закрыть день» → «Да, работало» / «Иә, жұмыс істеді» → быстрые кнопки →
   ввести порции → «Проверить» / «Тексеру» → «Закрыть день» / «Күнді жабу») с подписью
   на экране, и сверкой «прогноз против факта», если этап 2 слит. Проверь скрипт на копии
   базы до T+1:45. После слияния main (T+2:00) запиши на отдельной копии базы:
   node scripts/record_demo_video.mjs --lang ru и --lang kk. Готовые .webm передай Болату
   и Айдане; в git видео НЕ добавляй. Скрипту нужен компонент Playwright ffmpeg:
   npx playwright install ffmpeg.
5. QA: пройди весь путь на 1440 px и на телефоне 390 px (Chrome DevTools). Ошибки вёрстки
   исправляй только в apps/web/src/predas.css; ошибки логики и текстов записывай списком
   и отправляй Дамиру (этап 2) или Болату (остальное).
6. Проверки: npm run build; npx playwright test tests/e2e/predas_shell.spec.ts
   tests/e2e/day_close.spec.ts на отдельной базе. Если менял CSS —
   python scripts/generate_contracts.py и привести JSON к LF.

Правила: только свои файлы (scripts/prepare_battle_demo.mjs, docs/BATTLE_DEMO_RU.md,
scripts/record_demo_video.mjs, apps/web/src/predas.css). Не коммить .env, базы, .cache,
логины, видео. Перед каждым коммитом: python scripts/check_secrets.py --staged, затем
git checkout -- artifacts/security-scan.json. Без --force. В PR: что сделано, что
проверено, список найденных ошибок.
```

## Промпт 4 — Сарсенбаева Айдана (питч)

```text
Ты — помощник по питчу стартапа Predas (бывший AsBoljam). Нужна презентация для Startup /
Idea Battle, речь на 3 минуты и ответы на вопросы жюри. Срок — 1 час 45 минут.

Источник фактов — только репозиторий bltangenss/asboljam-diploma: README.md (начало и
разделы 2, 3, 5), docs/PRODUCT_IDEAS_RU.md, templates/DECISIONS.md, docs/commercial/*.
Не выдумывай клиентов, выручку, экономию, точность прогноза или пилоты. Данные в продукте
синтетические. Рыночные цифры приводи только с источником (ссылка на слайде или в
заметках); если надёжного источника нет — не приводи цифру.

Что есть в продукте (проверено):
- Прогноз на завтра, сколько порций каждого блюда продастся: 4 модели, 20 факторов дня —
  праздники РК, Наурыз, Рамадан и время ауызашара, айты, школьные каникулы, закат,
  погода из интернета для 31 города Казахстана.
- Закупка: порции → сырьё → упаковки поставщиков в рамках бюджета; дефицит виден;
  утверждает человек, заказ сам не уходит.
- Склад со сроками годности, печать плана для кухни, закрытие дня с телефона,
  регистрация заведения и демо-данные одним нажатием.
- Интерфейс на казахском и русском.

Сделай:
1. Презентацию на 8–10 слайдов: проблема (столовая/кафе каждый день гадает, сколько
   готовить и что купить → пересорт, списания, нехватка); решение; как работает (3 шага);
   демо (скриншот + ссылка на видео); почему сейчас и почему Казахстан (казахстанский
   календарь, Рамадан, города, KK/RU); бизнес-модель (подписка за филиал — подпиши
   «гипотеза»); конкуренты (iiko, r_keeper, Poster — учётные системы; Winnow, Tenzo,
   5-Out — зарубежные инструменты прогноза; наше отличие — локальный календарь и KK/RU,
   прогноз → закупка → решение человека); дорожная карта (из docs/PRODUCT_IDEAS_RU.md:
   закрытие смены через Telegram, подключение кассы Poster/iiko, «прогноз против факта»);
   команда; что просим (пилотные заведения, менторство, при необходимости — финансирование).
   Команда: Болат Танирберген — лидер, разработка, спикер; Карабек Дамир — разработка
   (сверка прогноза с фактом); Жорабек Бекзат — разработка, демо и видео; Сарсенбаева
   Айдана — продукт и питч. Роли пусть каждый подтвердит.
2. Речь на 3 минуты (около 400 слов, русский; если просят — казахский вариант) с
   пометками, где переключиться на живое демо.
3. 10 вероятных вопросов жюри с короткими честными ответами (как проверяется точность,
   где данные, конкуренты, монетизация, что уже работает, что нет).
4. One-pager на одну страницу.
Сохрани тексты в docs/pitch/ (pitch_ru.md, speech_ru.md, qa_ru.md, onepager_ru.md) и,
если умеешь, файл презентации .pptx. Работай в ветке team/aidana-pitch, коммить только
docs/pitch/*, без --force, и открой Pull Request к T+1:45. Стиль — бренд Predas: белый
фон, оранжевый акцент #FF5A1F, шрифт Onest; логотип — apps/web/public/favicon.svg.
В T+2:30 — репетиция с Болатом (живое демо + запасное видео от Бекзата).
```
