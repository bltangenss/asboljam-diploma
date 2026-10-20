# Predas · Idea Battle

## Открыть и показать

Откройте [deck/index.html](deck/index.html) двойным щелчком в Chrome, Edge или другом современном браузере. Это автономный HTML: CSS, JS, четыре поднабора Onest и снимки встроены, CDN и сервер для презентации не нужны. Один `index.html` можно перенести на другой компьютер. Исходные WOFF2 и лицензия SIL OFL 1.1 также лежат в `deck/fonts/`.

- `→`, `↓`, `PageDown`, пробел или клик по слайду — вперёд.
- `←`, `↑`, `PageUp`, `Shift+Space` — назад; `Home` / `End` — первый / последний.
- `F` — полный экран; `Esc` выходит из полноэкранного режима браузера.
- `S` — показать / скрыть заметки спикера. **Перед показом аудитории выключите заметки.**
- Ссылка с `#5` открывает пятый слайд. Масштаб подстраивается под окно, слайды всегда 16:9.
- [PDF](predas-pitch.pdf) — десять страниц 16:9 без заметок.

[Речь на три минуты](speech_ru.md) содержит отметки переключения в живое демо и запасной сценарий без стенда. [Вопросы жюри](qa_ru.md) содержат короткие ответы и ссылки на основания в репозитории.

## Что показываем

Все продуктовые изображения получены через настоящий интерфейс локального приложения и API/worker. `login.png` — экран до ввода учётных данных. Остальные пять снимков — кабинет нового тестового кафе в Алматы. Данные **SYNTHETIC**, дата прогноза **01.01.2026**, конец истории **31.12.2025**. Для воспроизводимости снимок прогноза использует `seasonal_naive_7`, а не модель с факторами. Бюджет расчёта закупки — демонстрационные 150 000 ₸, не показатель бизнеса.

Скрипт оставляет закупку без утверждения, а форму закрытия дня — с выбранным «Да, работало», без сохранения и подтверждения. Пароль генерируется случайно, не печатается, не сохраняется в файл и не попадает в снимки. Приложение сохраняет штатный хеш пароля в **временной** БД. Сессии, трассы, HAR и видео скрипт не записывает.

Бизнес-модель обозначена гипотезой. Подтверждённых клиентов, пилотов, выручки, экономии или «процента точности» в питче нет. Числа 20 и 31 описывают функциональность из репозитория, не размер рынка. Источники продуктовых фактов — [README](../../README.md), [AGENTS.md](../../AGENTS.md), [решения](../../templates/DECISIONS.md), [план развития](../PRODUCT_IDEAS_RU.md). Команда и её роли даны в задании на питч.

## Заново снять продукт

Требуются Node.js 22+, зависимости `npm ci`, Python 3.12+ с зависимостями проекта (`python -m pip install -r requirements.txt`) и установленный Chrome. Если Chrome недоступен, скрипт попробует Chromium от Playwright; установите его командой `npx playwright install chromium`.

Запускайте **только на новом изолированном стенде**. Не используйте существующий сервер, подключённый к рабочей БД. Скрипт разрешает только loopback URL, требует явные `PITCH_FRESH_DB` и `DATABASE_URL`, отказывает для `data/` и имени `asboljam-kz.sqlite`, проверяет пустоту таблиц в SQLite в режиме `mode=ro` до регистрации. После регистрации он проверяет, что новый пользователь появился именно в указанной базе. Соответствие БД работающему API до первого запроса обеспечивает запуск ниже: три процесса наследуют один `DATABASE_URL`. Другие базы скрипт не ищет и не открывает.

Пример PowerShell из корня репозитория, после установки зависимостей. Порты 3000 и 8000 должны быть свободны. `python` здесь — Python из подготовленного окружения проекта:

```powershell
$pitchRoot = (Get-Location).Path
$pitchPython = (Get-Command python).Source
$pitchNode = (Get-Command node).Source
$env:PITCH_PYTHON = $pitchPython
$env:PITCH_FRESH_DB = Join-Path $env:TEMP ("predas-pitch-" + [guid]::NewGuid().ToString("N") + ".sqlite")
$env:DATABASE_URL = "sqlite:///" + $env:PITCH_FRESH_DB.Replace("\", "/")
$env:ASBOLJAM_ENV = "local"
$env:ASBOLJAM_SELF_REGISTRATION = "on"
$env:PYTHONDONTWRITEBYTECODE = "1"

$pitchApi = Start-Process -FilePath $pitchPython -ArgumentList "-m","uvicorn","apps.api.main:app","--host","127.0.0.1","--port","8000","--no-access-log" -WorkingDirectory $pitchRoot -WindowStyle Hidden -PassThru
# Дождитесь HTTP 200: http://127.0.0.1:8000/api/v1/registration
# API создаёт схему новой базы; seed_demo / prepare_e2e не запускать.
$pitchWorker = Start-Process -FilePath $pitchPython -ArgumentList "-m","apps.worker.main" -WorkingDirectory $pitchRoot -WindowStyle Hidden -PassThru
$pitchWeb = Start-Process -FilePath $pitchNode -ArgumentList "node_modules/vite/bin/vite.js","--host","127.0.0.1","--port","3000","--strictPort" -WorkingDirectory $pitchRoot -WindowStyle Hidden -PassThru
# Дождитесь открытия http://localhost:3000
node scripts/capture_pitch_screens.mjs --url http://localhost:3000 --lang ru
```

Результат: шесть PNG 1440×900 в `docs/pitch/assets/`: `login`, `today`, `forecast`, `day-close`, `purchase`, `profile`. По умолчанию используются `http://localhost:3000` и `ru`; `--lang kk` предусмотрен для казахского интерфейса. Сценарий требует работающий worker: расчёты асинхронные.

После регистрации база уже не пустая. Для повторного запуска остановите **только свои** API/worker/web, создайте новое случайное имя БД и перезапустите их с ним. Не очищайте рабочую БД и не пытайтесь обходить проверку пустоты. При ошибке скрипт сообщает безопасное название этапа, не выводя содержимое Playwright-ошибки: такое содержимое может включать пароль из `fill()`. Незавершённый запуск не считается проверкой всех шести снимков.

## Обновить HTML и PDF

Из корня репозитория:

```powershell
# Перенести новые PNG и WOFF2 внутрь HTML и сразу экспортировать PDF:
node scripts/export_pitch_pdf.mjs --refresh-assets

# Только заново экспортировать текущую автономную презентацию:
node scripts/export_pitch_pdf.mjs
```

Экспорт открывает локальный `index.html`, ждёт шрифты и декодирование всех изображений, запрещает сетевые ресурсы и печатает десять слайдов. Размер страницы 1600×900 CSS px (1200×675 pt), без полей, заметок и панели управления. Сначала используется Chrome, затем bundled Chromium.

При обновлении Onest скопируйте четыре файла `onest-{latin,latin-ext,cyrillic,cyrillic-ext}-wght-normal.woff2` из `node_modules/@fontsource-variable/onest/files/` и `node_modules/@fontsource-variable/onest/LICENSE` в `deck/fonts/`, затем выполните `--refresh-assets`. Исходный знак встроен из `apps/web/public/favicon.svg`.

## Проверки и границы

Фактические команды и результаты записываются в [PROGRESS.md](PROGRESS.md). В этом задании разрешены изменения только `docs/pitch/**` и двух новых скриптов; поэтому журнал ведётся здесь, а не в общем `templates/PROGRESS.md`.

```powershell
node docs/pitch/verify_deck.mjs
```

Эта проверка копирует **только HTML** во временную папку, отключает сеть и проверяет 10 слайдов при 1920×1080 и 1366×768, границы текста, навигацию, `F`, `S`, печатную вёрстку и Onest для всех казахских букв. Снимки проверки и JSON остаются в системной временной папке, путь выводится в конце. После автоматических проверок нужно просмотреть снимки и страницы итогового PDF: одна проверка числа страниц не доказывает правильную вёрстку.

Перед коммитом:

```powershell
git diff --cached --stat
python scripts/check_secrets.py --staged
git checkout -- artifacts/security-scan.json
```

Не добавляйте `.env`, SQLite, `.cache`, `node_modules`, `.claude`, пароли, видео и браузерные сессии. Ветка — `team/aidana-pitch`; PR направляется в `main`, без изменения или принудительной отправки `main`.
