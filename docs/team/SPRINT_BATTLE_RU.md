# Predas — спринт к Startup / Idea Battle (3 часа)

Цель: за 3 часа стабилизировать продукт, подготовить живую демонстрацию, видео и питч. Новых больших функций не начинаем — доводим и показываем то, что есть.

## Состояние на старте (20.10.2026)

- `main` = `5dbe9d4`. Работают: регистрация заведения и демо-данные одним нажатием, прогноз на завтра (4 модели, 20 факторов дня, 31 город, погода), склад, закупка с утверждением человеком, печать плана приготовления, закрытие дня с телефона.
- Этап 2 (сверка «прогноз против факта», рабочий вариант плана, задачи «Сегодня», объяснения прогноза) **в коде есть, но не доведён**: 2 браузерных сценария падают, полная регрессия не запускалась, миграция `0012` на демо-базу не применена. См. `docs/commercial/WORKDAY_REVIEW_RU.md`.

## Распределение

| Кто | Роль | Результат к T+1:45 | Файлы (только свои!) |
|---|---|---|---|
| Болат Танирберген | Лидер, интегратор, спикер | Слитый и проверенный `main`, стенд для живого демо, тег релиза | `templates/*`, `README.md`, `FINAL_REPORT.md`, `CLOUD_HANDOFF.md`; слияние PR |
| Карабек Дамир | Стабилизация этапа 2 | Зелёные тесты этапа 2 и полная регрессия | `apps/api/{forecast_review,forecast_explanation,workday_tasks,working_plan}.py`, `apps/web/src/{ForecastReview,ForecastExplanation,WorkdayTasks,WorkingPlan}.tsx`, `workdayData.ts`, `forecast-review.css`, их тесты, `tests/e2e/workday_review.spec.ts` |
| Жорабек Бекзат | Демо-стенд и QA пути | Скрипт подготовки демо-кабинета, сценарий живого показа, исправления вёрстки | `scripts/prepare_battle_demo.mjs` (новый), `docs/BATTLE_DEMO_RU.md` (новый), `apps/web/src/predas.css` |
| Сарсенбаева Айдана | Питч | Презентация 8–10 слайдов, текст на 3 минуты, ответы на вопросы, one-pager | `docs/pitch/*` (новая папка) |
| Махсут Гулнур | Тексты, руководство, видео | Исправленные KK/RU тексты, руководство под Predas, новое демо-видео | `docs/user-guide/USER_GUIDE_KK.md`, строки в `apps/web/src/{DayClose,GetStarted,Profile,Register}.tsx`, `scripts/record_demo_video.mjs` |

Чужие файлы не трогать. Нужна правка в чужом файле — напиши владельцу.

## График (T = старт)

- **T+0:00–0:20** — клонировать репозиторий, создать свою ветку, у кого есть код — запустить проект.
- **T+0:20–1:45** — работа, маленькие коммиты, push своей ветки каждые 20–30 минут.
- **T+1:45** — открыть Pull Request в `main`. Порядок слияния у Болата: Дамир → Гулнур → Бекзат → Айдана.
- **T+2:00** — заморозка кода. После неё только исправления, которые Болат явно разрешил.
- **T+2:00–2:30** — Болат прогоняет проверки на слитом `main` и готовит стенд; Гулнур записывает видео на слитом `main`; Бекзат проходит живой сценарий.
- **T+2:30–3:00** — репетиция питча с живым демо и запасным видео.

## Общие правила для всех

- Ветка: `team/<имя>-<тема>` от свежего `origin/main`. В `main` напрямую не пушит никто, кроме Болата.
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

Сайт: http://localhost:3000 · вход `admin@asboljam.local` с вашим `DEMO_PASSWORD` · остановка `.\scripts\stop.ps1`.

---

## Промпт 1 — Болат Танирберген (лидер, интеграция, стенд, спикер)

```text
Ты — ведущий разработчик и интегратор проекта Predas (бывший AsBoljam), репозиторий
bltangenss/asboljam-diploma, моя папка C:\Users\ASUS\Desktop\Diplomwork (ветка main).
У нас 3 часа до Startup/Idea Battle. Команда из пяти человек работает параллельно в
ветках team/*; план и владение файлами — в docs/team/SPRINT_BATTLE_RU.md. Прочитай его,
AGENTS.md и верхние записи templates/PROGRESS.md.

Твои задачи по времени:
1. T+0:00 — git fetch; git status; git pull --ff-only origin main. Убедись, что рабочая
   копия чистая (папку .claude/ не коммитить). Сделай резервную копию демо-базы:
   python scripts/backup_db.py backup --database data/asboljam-kz.sqlite
   --output backups/asboljam-kz-before-battle-20261020.sqlite
2. T+0:20–1:45 — следи за PR от Дамира, Гулнур, Бекзата, Айданы. Каждый PR проверяй:
   только свои файлы по таблице, нет секретов, БД, видео, .cache; описание PR перечисляет,
   какие проверки реально прошли.
3. T+1:45–2:00 — сливай PR по порядку: Дамир → Гулнур → Бекзат → Айдана. После каждого
   слияния: git pull --ff-only, npm run build. При конфликте сначала решай его в ветке
   автора вместе с ним, а не в main.
4. T+2:00 — заморозка. На слитом main (с изолированным DATABASE_URL):
   python -X utf8 -m unittest discover -s tests -p "test_*.py"
   npm run build
   браузер — хотя бы tests/e2e/workday_review, day_close, today_workflow,
   predas_shell, workflow (полный набор идёт около 25 минут — запускай, только если есть
   время). Запиши точные числа.
5. Стенд для живого демо: останови превью, затем .\scripts\start.ps1 (миграция 0012
   применится к демо-базе — резервная копия уже есть). Проверь /api/v1/ready. Запусти
   скрипт Бекзата scripts/prepare_battle_demo.mjs на копии базы, если он готов.
   Держи открытыми: готовый демо-кабинет, запасное видео от Гулнур, скриншоты.
6. Документы: добавь в templates/PROGRESS.md запись «20.10.2026 — спринт к Idea Battle»
   (DONE / TESTED с точными числами / NOT TESTED / BLOCKED), сверху FINAL_REPORT.md и
   CLOUD_HANDOFF.md — актуальное состояние. Коммит, проверка секретов, push в main.
   Поставь тег: git tag battle-2026-10-20 && git push origin battle-2026-10-20.
7. T+2:30 — репетиция питча с Айданой: 3 минуты, живое демо по docs/BATTLE_DEMO_RU.md,
   при любом сбое — сразу видео.

Правила: никакого force-push, reset --hard, удаления веток; не используй рабочую базу
как тестовую; не выдумывай метрики. В конце отчёт по-русски: что слито (хеши), что
проверено (числа), что не проверено, хеш тега, результат push.
```

## Промпт 2 — Карабек Дамир (стабилизация этапа 2)

```text
Ты — разработчик проекта Predas (бывший AsBoljam): FastAPI+SQLAlchemy (apps/api),
React+TypeScript+Vite (apps/web), worker с очередью в БД. Репозиторий
bltangenss/asboljam-diploma. Работай в ветке team/damir-stage2 от свежего origin/main.
Срок — 1 час 45 минут, потом Pull Request в main. Новых функций не начинай.

Контекст: этап 2 (сверка прогноза с фактом, рабочий вариант плана, задачи «Сегодня»,
объяснения прогноза) лежит в коммите 5dbe9d4, но не доведён. Прочитай
docs/commercial/WORKDAY_REVIEW_RU.md, верхнюю запись templates/PROGRESS.md, AGENTS.md
и файлы: apps/api/forecast_review.py, forecast_explanation.py, workday_tasks.py,
working_plan.py; apps/web/src/ForecastReview.tsx, ForecastExplanation.tsx,
WorkdayTasks.tsx, WorkingPlan.tsx, workdayData.ts; tests/e2e/workday_review.spec.ts.

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

Правила: трогай только файлы этапа 2 и их тесты (Dashboard.tsx — только места виджетов
этапа 2). Пустое значение не превращать в ноль; данные SYNTHETIC; не используй рабочую
базу data/asboljam-kz.sqlite. Перед каждым коммитом: проверка секретов
(python scripts/check_secrets.py --staged), затем git checkout --
artifacts/security-scan.json. Маленькие коммиты, push своей ветки, без --force.
В описании PR: что исправлено, точные команды и числа тестов, что не проверено.
```

## Промпт 3 — Жорабек Бекзат (демо-стенд, сценарий показа, QA вёрстки)

```text
Ты — разработчик проекта Predas (бывший AsBoljam): веб-сервис прогноза продаж и закупок
для столовых и кафе Казахстана. Репозиторий bltangenss/asboljam-diploma, ветка
team/bekzat-demo от свежего origin/main. Срок — 1 час 45 минут, потом Pull Request в main.

Цель: живое демо на Idea Battle должно идти гладко за 3 минуты и не зависеть от удачи.

Задачи:
1. Установка: copy .env.example .env, свой DEMO_PASSWORD, .\scripts\start.ps1 -Install.
   Работай на копии базы, не на рабочей. Для чистой копии задай в .env
   DATABASE_URL=sqlite:///./data/battle-demo.sqlite и запусти .\scripts\start.ps1.
2. Напиши scripts/prepare_battle_demo.mjs (Playwright, по образцу
   scripts/record_demo_video.mjs, без записи видео). Скрипт на запущенном локальном
   стенде регистрирует кафе «Достар» (Алматы, тип «Кафе», email вида
   demo-<случайное>@example.invalid, случайный пароль), загружает демо-данные, считает
   прогноз на 01.01.2026, закрывает день 01.01.2026 с правдоподобными тестовыми
   продажами (все строки помечены SYNTHETIC), считает закупку. Email и пароль пишет
   только в игнорируемый файл .cache/battle-demo-login.json и в консоль — не в git.
   Скрипт не должен трогать data/asboljam-kz.sqlite.
3. Напиши docs/BATTLE_DEMO_RU.md: точный путь кликов живого демо на 3 минуты
   (вход → «Сегодня» → прогноз → «Закрыть день» → сверка «прогноз против факта», если
   этап 2 слит → закупка → утверждение → профиль), что говорить на каждом шаге одной
   фразой, и запасной план (видео, скриншоты). Явно напиши, что данные учебные (SYNTHETIC).
4. QA: пройди весь путь на 1440 px и на телефоне 390 px (Chrome DevTools). Ошибки вёрстки
   исправляй только в apps/web/src/predas.css. Ошибки логики и текстов не чини сам —
   запиши списком в PR и сообщи Дамиру (этап 2) или Гулнур (тексты).
5. Проверки: npm run build; npx playwright test tests/e2e/predas_shell.spec.ts
   tests/e2e/day_close.spec.ts (на отдельной базе, см. README «Проверки»).
   Если менял CSS — python scripts/generate_contracts.py и привести JSON к LF.

Правила: только свои файлы (scripts/prepare_battle_demo.mjs, docs/BATTLE_DEMO_RU.md,
apps/web/src/predas.css). Не коммить .env, базы, .cache, логины, видео. Перед каждым
коммитом: python scripts/check_secrets.py --staged, затем git checkout --
artifacts/security-scan.json. Без --force. В PR: что сделано, что проверено, список
найденных ошибок.
```

## Промпт 4 — Сарсенбаева Айдана (питч для Idea Battle)

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
   Команда: Болат Танирберген — лидер, разработка; Карабек Дамир — разработка (сверка
   прогноза); Жорабек Бекзат — разработка и демо; Сарсенбаева Айдана — продукт и питч;
   Махсут Гулнур — контент, тексты и видео. Роли пусть каждый подтвердит.
2. Речь на 3 минуты (около 400 слов, русский; если просят — казахский вариант) с
   пометками, где переключиться на живое демо.
3. 10 вероятных вопросов жюри с короткими честными ответами (как проверяется точность,
   где данные, конкуренты, монетизация, что уже работает, что нет).
4. One-pager на одну страницу.
Сохрани тексты в docs/pitch/ (pitch_ru.md, speech_ru.md, qa_ru.md, onepager_ru.md) и,
если умеешь, файл презентации .pptx. Работай в ветке team/aidana-pitch, коммить только
docs/pitch/*, без --force, и открой Pull Request к T+1:45. Стиль — бренд Predas: белый
фон, оранжевый акцент #FF5A1F, шрифт Onest; логотип — apps/web/public/favicon.svg.
```

## Промпт 5 — Махсут Гулнур (тексты KK/RU, руководство, демо-видео)

```text
Ты — специалист по контенту и QA проекта Predas (бывший AsBoljam), репозиторий
bltangenss/asboljam-diploma, ветка team/gulnur-content от свежего origin/main. Срок —
1 час 45 минут до Pull Request; видео записываешь после слияния (T+2:00–2:30).

Задачи:
1. Установка: copy .env.example .env, свой DEMO_PASSWORD, .\scripts\start.ps1 -Install.
2. Тексты KK/RU: пройди экраны «Тіркелу / Регистрация», «С чего начать» (пустой кабинет),
   «Профиль», «Закрыть день» на казахском и русском. Исправь опечатки, неестественные
   или слишком технические формулировки — только строки внутри
   apps/web/src/DayClose.tsx, GetStarted.tsx, Profile.tsx, Register.tsx. Логику, имена
   классов и подписи, на которые опираются тесты (tests/e2e/day_close.spec.ts,
   predas_shell.spec.ts, registration_places.spec.ts), не меняй; если меняешь подпись из
   теста — поправь и тест. После правок: npm run build, python scripts/generate_contracts.py
   (затем JSON к LF), npx playwright test tests/e2e/day_close.spec.ts
   tests/e2e/predas_shell.spec.ts tests/e2e/registration_places.spec.ts на отдельной базе.
3. Руководство docs/user-guide/USER_GUIDE_KK.md: оно описывает старый интерфейс AsBoljam.
   Обнови название (Predas), пять разделов шапки (Бүгін · Болжам · Қойма · Сатып алу ·
   Деректер), профиль в меню аккаунта, регистрацию и демо-деректер, «Күнді жабу».
   Сверяй с реальным интерфейсом, ничего не выдумывай.
4. Видео: расширь scripts/record_demo_video.mjs шагом «Закрыть день» (после прогноза:
   «Сегодня» → «Закрыть день» → «Иә, жұмыс істеді» → быстрые кнопки → ввести порции →
   «Тексеру» → «Күнді жабу»), с подписью на экране. После того как Болат сольёт main
   (T+2:00), запусти на отдельной копии базы:
   node scripts/record_demo_video.mjs --lang ru и --lang kk.
   Готовые .webm передай Болату и Айдане; в git видео НЕ добавляй.

Правила: только свои файлы; не коммить .env, базы, .cache, видео, пароли. Перед каждым
коммитом: python scripts/check_secrets.py --staged, затем git checkout --
artifacts/security-scan.json. Без --force. В PR: список исправленных текстов (было → стало),
что проверено.
```
