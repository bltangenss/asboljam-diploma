# Отдельная браузерная проверка склада

Проверка использует новую SQLite в `.cache`, искусственную организацию SYNTHETIC,
настоящие API и worker. Она не открывает основную базу. Продажи заканчиваются
31.12.2025, прогноз относится к 01.01.2026. Дополнительный посчитанный остаток
02.01.2026 проверяет движения первого дня и не меняет границу истории продаж.

`tests/e2e/stock_ledger.spec.ts` проверяет интерфейс с искусственными API-ответами.
`stock_ledger_live.spec.ts` выполняет реальные HTTP-запросы без моков и по умолчанию
пропускается: нужен явный `ASBOLJAM_STOCK_E2E=1` и новая отдельная база.
Повторный полный прогон требует нового имени SQLite; скрипт не перезаписывает
существующие файлы и не удаляет предыдущие результаты.

## Подготовка из корня проекта

Убедитесь, что порты 8012 и 3013 свободны. Не останавливайте чужие процессы,
если порт занят. Используйте установленное Python/npm-окружение проекта.

```powershell
python -X utf8 scripts/prepare_stock_e2e.py --database .cache/stock-browser-new.sqlite
$fixtureDatabase = (Resolve-Path .cache/stock-browser-new.sqlite).Path.Replace('\','/')
$env:DATABASE_URL = 'sqlite:///' + $fixtureDatabase
$env:ASBOLJAM_ENV = 'local'
$env:COOKIE_SECURE = 'false'
$env:ALLOWED_ORIGINS = 'http://127.0.0.1:3013'
$env:LOKY_MAX_CPU_COUNT = '1'
```

Скрипт сохраняет случайные учётные данные в ignored `.cache/stock-e2e-login.json`.
Не публикуйте этот файл, базы, браузерные traces или рабочие cookies. Это не
данные для входа в основную организацию.

В отдельных терминалах с теми же переменными среды запустите:

```powershell
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8012
```

```powershell
python -m apps.worker.main
```

Создайте **тестовую** конфигурацию Vite в ignored `.cache`:

```typescript
// .cache/vite-stock-live.config.ts
import {defineConfig, mergeConfig} from '../node_modules/vite';
import base from '../vite.config';
export default mergeConfig(base, defineConfig({server:{
  port:3013, strictPort:true, proxy:{'/api':'http://127.0.0.1:8012'}
}}));
```

В третьем терминале:

```powershell
npx vite --config .cache/vite-stock-live.config.ts --host 127.0.0.1 --port 3013 --strictPort
```

Основная конфигурация Vite и обычный порт 3000 при этом не меняются.

Создайте конфигурацию Playwright в `.cache`:

```typescript
// .cache/stock-live-playwright.config.ts
import {defineConfig} from '../node_modules/@playwright/test';
export default defineConfig({
  testDir:'../tests/e2e', timeout:240000, expect:{timeout:15000}, workers:1,
  reporter:[['list'],['json',{outputFile:'stock-live-browser.json'}]],
  outputDir:'./stock-live-browser-output',
  use:{baseURL:'http://127.0.0.1:3013', channel:'chrome', headless:true,
    viewport:{width:1440,height:1100}, screenshot:'only-on-failure', trace:'retain-on-failure'}
});
```

После ответа `/api/v1/ready` со статусом 200 выполните:

```powershell
$env:ASBOLJAM_STOCK_E2E = '1'
npx playwright test --config .cache/stock-live-playwright.config.ts stock_ledger_live.spec.ts
Remove-Item Env:ASBOLJAM_STOCK_E2E
```

Тест проверяет вход, открытие журнала из посчитанного среза, активацию полной
рецептуры с сохранённым выходом, приход, расход по рецепту, обратную запись,
раздельные остатки на начало двух дней, совпадающую сверку, настоящий прогноз и
закупку через worker, сохранённое основание плана, человеческое утверждение,
аудит и CSV. Успешный тест пишет `.cache/stock-live-result.json`.

После завершения остановите **только эти три запущенных процесса** через Ctrl+C.
Сохраните базу и приватные свидетельства для разбора; не удаляйте Docker volumes
или основную базу. Факт успешного выполнения фиксируется отдельно от этой
инструкции: её наличие само по себе не доказывает PASS, production или бизнес-пилот.

## Приём нового посчитанного остатка: отдельный REAL/TEST fixture

Дополнительный сценарий использует **полностью сгенерированные** строки,
зарегистрированные через контракт `REAL` с `purpose=test_fixture` и видимой
меткой `TEST`. Это не наблюдения реального бизнеса и не подтверждение разрешения
предприятия. Обычный запуск скрипта сохраняет SYNTHETIC и прежние даты.

После остановки предыдущих трёх проверочных процессов создайте новую базу:

```powershell
python -X utf8 scripts/prepare_stock_e2e.py --database .cache/stock-anchor-new.sqlite --real-test
```

Установите `DATABASE_URL` на **этот новый файл** и запустите API, worker и web
по инструкциям выше. Настройки Origin, COOKIE_SECURE и порты те же.
Фиксированные даты artificial TEST: исходная инвентаризация 01.09.2026,
следующая 02.09.2026, 85 дней истории продаж заканчиваются 01.09.2026.
Так для обоих расчётных origins остаётся не менее 84 дней. Обычный SYNTHETIC
fixture по-прежнему содержит 84 дня и не меняет свою границу истории.
Учётные данные снова остаются только в `.cache/stock-e2e-login.json`.

```powershell
$env:ASBOLJAM_STOCK_ANCHOR_E2E = '1'
npx playwright test --config .cache/stock-live-playwright.config.ts stock_count_anchors_live.spec.ts
Remove-Item Env:ASBOLJAM_STOCK_ANCHOR_E2E
```

Сценарий проверяет открытие журнала, исходный утверждённый план, настоящую
транзакционную CSV-коррекцию через HTTP, блокирование движений, явное принятие
исправленного исходного остатка, приход, принятие следующего посчитанного
остатка, продолжение нумерации движений отдельно от версии журнала, старую
дату, сверку, новый план через настоящий worker, подтверждение в интерфейсе,
историю, аудит и CSV с сохранённым основанием. Старый утверждённый CSV должен
остаться побайтно прежним. CSV preview/commit и постановка расчётов в очередь
выполняются через HTTP из браузерного контекста; приём остатков, движения и
утверждения выполняются через web-формы. Новый полный прогон требует новой базы.

Результат: ignored `.cache/stock-anchor-live-result.json`. После проверки
остановите только запущенные для неё процессы. Не публикуйте базы, пароли,
cookies или traces. Искусственные UI-fixtures проверяются отдельно:

```powershell
npx playwright test --config .cache/stock-playwright.config.ts stock_count_anchors.spec.ts stock_ledger.spec.ts
```

Этот последний пример использует отдельную локальную Playwright-конфигурацию
с `baseURL=http://127.0.0.1:3013`, `testDir=../tests/e2e`, Chrome, workers=1,
timeout=45000 и expect timeout=10000. API-ответы подменены самим spec; это не
live-проверка сервера. Фактические исходы записываются в verification отдельно.
