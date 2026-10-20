// Real UI rehearsal on an explicitly confirmed disposable stand. Never opens a database.
// See docs/BATTLE_DEMO_RU.md before running. Importing this module does not start a demo.
import { chromium, expect as playwrightExpect } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { parseArgs } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const loginFile = path.join(root, '.cache/battle-demo-login.json');
const expect = playwrightExpect.configure({ timeout: 60000 });
export const demoDate = '01.01.2026';

// The public readiness endpoint deliberately does not disclose the server's DB path.
// PREDAS_DEMO_ISOLATED is an operator attestation, NOT automatic server DB discovery.
// The operator must start API + worker with this exact DATABASE_URL before attesting.
export function assertDisposableStand(url) {
  let stand;
  try { stand = new URL(url); } catch { throw new Error('Invalid demo URL. Use a local HTTP origin, e.g. http://localhost:3000.'); }
  if (stand.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(stand.hostname)
      || stand.username || stand.password || stand.pathname !== '/' || stand.search || stand.hash) {
    throw new Error('Demo URL must be a local HTTP origin, e.g. http://localhost:3000.');
  }
  if ((process.env.ASBOLJAM_ENV || 'local') !== 'local' || process.env.PREDAS_DEMO_ISOLATED !== '1') {
    throw new Error('Isolation not confirmed. Start a separate disposable API/worker/web stand as described in docs/BATTLE_DEMO_RU.md, then set PREDAS_DEMO_ISOLATED=1 in that shell.');
  }
  const databaseUrl = process.env.DATABASE_URL || '';
  if (!/^sqlite(?:\+pysqlite)?:\/\/\//.test(databaseUrl) || /[?#]/.test(databaseUrl)) {
    throw new Error('DATABASE_URL must explicitly select an existing disposable SQLite file inside this checkout\'s .cache. No default or remote database is permitted.');
  }
  const selected = path.resolve(databaseUrl.replace(/^sqlite(?:\+pysqlite)?:\/\/\//, ''));
  const cache = path.join(root, '.cache');
  const inside = (parent, child) => {
    const relative = path.relative(parent, child);
    return relative !== '' && !relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative);
  };
  if (!inside(cache, selected) || path.basename(selected).toLowerCase() === 'asboljam-kz.sqlite'
      || !fs.existsSync(selected) || !fs.statSync(selected).isFile() || fs.statSync(selected).nlink !== 1
      || fs.lstatSync(cache).isSymbolicLink()
      || path.relative(path.join(fs.realpathSync(root), '.cache'), fs.realpathSync(cache)) !== ''
      || !inside(fs.realpathSync(cache), fs.realpathSync(selected))) {
    throw new Error('Unsafe database selection. Use a fresh, separate SQLite file under .cache; never data/asboljam-kz.sqlite, a linked working database or a default database.');
  }
  // Follow neither a credential-file symlink nor an unexpected tracked/visible cache.
  let credentialStat;
  try { credentialStat = fs.lstatSync(loginFile); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (credentialStat && (credentialStat.isSymbolicLink() || !credentialStat.isFile() || credentialStat.nlink !== 1)) {
    throw new Error('Credential destination must be a regular, unlinked ignored file.');
  }
  try {
    execFileSync('git', ['check-ignore', '-q', '--', '.cache/battle-demo-login.json'], { cwd: root, stdio: 'ignore' });
    execFileSync('git', ['check-ignore', '-q', '--', path.relative(root, selected)], { cwd: root, stdio: 'ignore' });
    const tracked = execFileSync('git', ['ls-files', '--', '.cache/battle-demo-login.json', path.relative(root, selected)], { cwd: root, encoding: 'utf8' });
    if (tracked.trim()) throw new Error('Tracked demo cache');
  } catch {
    throw new Error('Demo database and .cache/battle-demo-login.json must be ignored and untracked by Git.');
  }
  return stand.origin;
}

export async function launchDemoBrowser() {
  try {
    return await chromium.launch({ channel: 'chrome', headless: true });
  } catch {
    console.info('Google Chrome unavailable; trying Playwright Chromium.');
    try {
      return await chromium.launch({ headless: true });
    } catch {
      throw new Error('Browser launch failed. Install Google Chrome or run npx playwright install chromium (and ffmpeg for video).');
    }
  }
}

// Match real mutation responses; never route, fulfill, or fabricate application data.
export async function waitForSuccessfulResponse(page, pathname, action, timeout = 120000) {
  const [response] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === pathname && response.request().method() !== 'GET', { timeout }),
    action(),
  ]);
  if (!response.ok()) {
    const body = await response.json().catch(() => null);
    const code = String(body?.detail?.code || 'REQUEST_FAILED').replace(/[^A-Z0-9_]/g, '').slice(0, 80);
    throw new Error(`${pathname}: HTTP ${response.status()} ${code}. Inspect the visible validation message; no success was assumed.`);
  }
  return response;
}

export async function assertSyntheticForecast(page) {
  const origin = page.locator('.planning-form .composer-row input[type=date]');
  await expect(origin).toHaveValue('2025-12-31');
  await expect(origin).toBeDisabled();
  await expect(page.locator('.planning-preview .planning-date')).toHaveValue(demoDate);
}

export async function closeDemoDay(page, lang, options = {}) {
  const kk = lang === 'kk';
  const click = options.click || (locator => locator.click());
  const fill = options.fill || ((locator, value) => locator.fill(value));
  const today = () => page.locator('.app-nav').getByRole('button', { name: kk ? 'Бүгін' : 'Сегодня', exact: true });
  await click(today());
  await click(page.locator('.day-close-entry'));
  await expect(page.locator('.day-close-context strong')).toHaveText(demoDate);
  await click(page.getByRole('button', { name: kk ? 'Иә, жұмыс істеді' : 'Да, работало', exact: true }));
  for (const text of kk
    ? ['Барлығы ұсынылды', 'Ешбірі бітпеді', 'Акция болмады', 'Бағалар мәзір бойынша']
    : ['Все блюда были в меню', 'Ничего не закончилось', 'Акций не было', 'Цены по меню']) {
    await click(page.locator('.day-close-quick').getByRole('button', { name: text, exact: true }));
  }
  const meals = page.locator('.day-close-meal');
  await expect(meals.first()).toBeVisible();
  const count = await meals.count();
  if (!count) throw new Error('Day-close menu is empty; demo data did not load.');
  for (let index = 0; index < count; index++) {
    // The form's available_portions is the total prepared, NOT the unsold remainder.
    const sold = 20 + (index * 7) % 36;
    const available = sold + 5 + index % 4;
    const meal = meals.nth(index);
    await fill(meal.getByLabel(kk ? 'Сатылды, порция' : 'Продано, порций', { exact: true }), String(sold));
    await fill(meal.getByLabel(kk ? 'Дайын болды, порция' : 'Было готово, порций', { exact: true }), String(available));
  }
  await click(page.locator('.day-close-bar').getByRole('button', { name: kk ? 'Тексеру' : 'Проверить', exact: true }));
  const review = page.locator('.day-close-review');
  const close = review.getByRole('button', { name: kk ? 'Күнді жабу' : 'Закрыть день', exact: true });
  await expect(review).toBeVisible();
  await expect(close).toBeEnabled();
  await waitForSuccessfulResponse(page, '/api/v1/day-close/close', () => click(close));
  await expect(page.locator('.day-close-card.is-closed')).toBeVisible({ timeout: 120000 });
  await options.onClosed?.();
  await click(today());
  await expect(page.locator('.day-header h1')).toHaveText(kk ? 'Бүгін' : 'Сегодня');
}

async function prepare() {
  const { values } = parseArgs({ options: { url: { type: 'string', default: 'http://localhost:3000' }, lang: { type: 'string', default: 'ru' }, help: { type: 'boolean' } } });
  if (values.help) {
    console.log('node scripts/prepare_battle_demo.mjs [--url http://localhost:3000] [--lang ru|kk]\nFirst start a verified isolated stand: docs/BATTLE_DEMO_RU.md.');
    return;
  }
  if (!['ru', 'kk'].includes(values.lang)) throw new Error('--lang must be ru or kk.');
  const base = assertDisposableStand(values.url);
  const kk = values.lang === 'kk';
  const started = performance.now();
  let stage = 'browser startup';
  let browser;
  let password;
  try {
    browser = await launchDemoBrowser();
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    await context.addInitScript(language => localStorage.setItem('asboljam-language', language), values.lang);
    const page = await context.newPage();
    page.setDefaultTimeout(60000);
    stage = 'frontend/API readiness';
    const ready = await context.request.get(base + '/api/v1/ready', { timeout: 30000 });
    if (!ready.ok()) throw new Error('API is not ready. Check the isolated stand\'s API logs and migrations.');
    await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
    stage = 'real registration';
    await page.getByRole('button', { name: kk ? 'Тіркелу' : 'Регистрация', exact: true }).click();
    await page.getByLabel(kk ? 'Мекеме атауы' : 'Название заведения').fill('Кафе «Достар»');
    await page.getByLabel(kk ? 'Мекеме түрі' : 'Тип заведения').selectOption('cafe');
    await page.getByLabel(kk ? 'Қала' : 'Город').selectOption('almaty');
    const email = `demo-${crypto.randomBytes(10).toString('hex')}@example.invalid`;
    password = 'Aa9!' + crypto.randomBytes(24).toString('base64url');
    // Persist once, at the only permitted credential destination, even if a later UI step fails.
    fs.mkdirSync(path.dirname(loginFile), { recursive: true });
    const file = fs.openSync(loginFile, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_TRUNC | (fs.constants.O_NOFOLLOW || 0), 0o600);
    try { fs.writeFileSync(file, JSON.stringify({ email, password, url: base, lang: values.lang }, null, 2) + '\n'); }
    finally { fs.closeSync(file); }
    if (process.platform !== 'win32') fs.chmodSync(loginFile, 0o600);
    console.log(`Demo login: ${email}`);
    console.log('Credentials: .cache/battle-demo-login.json (ignored; password is never printed).');
    await page.getByLabel(kk ? 'Электрондық пошта' : 'Электронная почта').fill(email);
    await page.locator('#register-password').fill(password);
    await page.getByLabel(kk ? 'Құпиясөзді қайталаңыз' : 'Повторите пароль').fill(password);
    await page.locator('.register-consent input').check();
    await waitForSuccessfulResponse(page, '/api/v1/register', () => page.getByRole('button', { name: kk ? /Кабинетті ашу/ : /Открыть кабинет/ }).click());
    await expect(page.getByTestId('get-started')).toBeVisible();
    stage = 'synthetic demo data import';
    await waitForSuccessfulResponse(page, '/api/v1/demo-data', () => page.getByRole('button', { name: kk ? 'Демо-деректерді жүктеу' : 'Загрузить демо-данные', exact: true }).click());
    await expect(page.locator('.next-action')).toBeVisible({ timeout: 120000 });
    stage = 'forecast for 01.01.2026';
    await page.locator('.app-nav').getByRole('button', { name: kk ? 'Болжам' : 'Прогноз', exact: true }).click();
    await assertSyntheticForecast(page);
    await waitForSuccessfulResponse(page, '/api/v1/forecasts', () => page.locator('.planning-form-actions .primary').click());
    await page.waitForURL(/\/forecasts\/[^/?]+/, { timeout: 300000 });
    await expect(page.locator('.forecast-result-context strong')).toHaveText(demoDate, { timeout: 120000 });
    const forecastUrl = page.url();
    stage = 'day-close for 01.01.2026';
    await closeDemoDay(page, values.lang);
    stage = 'purchase calculation';
    await page.locator('.app-nav').getByRole('button', { name: kk ? 'Сатып алу' : 'Закупки', exact: true }).click();
    await expect(page.locator('.planning-preview .planning-date')).toHaveText(demoDate);
    await waitForSuccessfulResponse(page, '/api/v1/procurement', () => page.locator('.planning-form-actions .primary').click());
    await page.waitForURL(/\/procurement\/[^/?]+/, { timeout: 300000 });
    await expect(page.locator('.purchase-result-summary')).toBeVisible({ timeout: 120000 });
    await expect(page.locator('.decision-bar .primary')).toBeEnabled();
    console.log(`PASS: registration, SYNTHETIC data, forecast ${demoDate}, persisted day-close, purchase ready for human approval.`);
    console.log(`Forecast: ${forecastUrl}\nPurchase: ${page.url()}\nElapsed: ${((performance.now() - started) / 1000).toFixed(1)} s`);
  } catch (error) {
    // Playwright's complete call log can include filled password values. Do not print it.
    const firstLine = String(error.message || error).split('\n')[0];
    const safe = password ? firstLine.split(password).join('[redacted]') : firstLine;
    throw new Error(`Demo preparation failed during ${stage}: ${safe}. Check frontend/API/worker logs. No mock success or validation bypass was used.`);
  } finally {
    await browser?.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  prepare().catch(error => { console.error(error.message); process.exitCode = 1; });
}
