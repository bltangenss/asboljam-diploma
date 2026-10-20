/**
 * Capture a real, isolated SYNTHETIC cabinet. No mocks, credentials, traces or videos.
 * Start API + worker with the SAME fresh DATABASE_URL before running this script.
 * PITCH_FRESH_DB must be the absolute SQLite filename (outside the repository's data/).
 * PITCH_PYTHON optionally selects Python; its stdlib is used for read-only DB checks.
 */
import { chromium, expect } from '@playwright/test';
import { randomBytes } from 'node:crypto';
import { mkdir, realpath, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { parseArgs } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = path.join(root, 'docs/pitch/assets');
const { values } = parseArgs({
  options: { url: { type: 'string', default: 'http://localhost:3000' },
    lang: { type: 'string', default: 'ru' }, help: { type: 'boolean' } },
});
if (values.help) {
  console.log('PITCH_FRESH_DB=<absolute fresh sqlite> DATABASE_URL=sqlite:///<same file> node scripts/capture_pitch_screens.mjs [--url http://localhost:3000] [--lang ru|kk]');
  process.exit(0);
}
let stage = 'preflight', browser;
const python = process.env.PITCH_PYTHON || 'python';
function checkDatabase(filename, email = '') {
  // Neither passwords nor session material enter child-process arguments or output.
  const code = `
import pathlib, sqlite3, sys
p = pathlib.Path(sys.argv[1]).resolve()
with sqlite3.connect(p.as_uri() + '?mode=ro', uri=True) as db:
    if len(sys.argv) == 2:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'organizations', 'users', 'operational_records'} <= tables
        for name in ('organizations', 'users', 'operational_records', 'jobs'):
            assert db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] == 0
    else:
        assert db.execute('SELECT COUNT(*) FROM users WHERE email=?', (sys.argv[2],)).fetchone()[0] == 1
`;
  const result = spawnSync(python, ['-c', code, filename, ...(email ? [email] : [])], { stdio: 'pipe' });
  if (result.status !== 0) throw new Error('Fresh database check failed');
}
try {
  const url = new URL(values.url);
  if (!['http:', 'https:'].includes(url.protocol) ||
      !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ||
      url.username || url.password || url.pathname !== '/' || url.search || url.hash)
    throw new Error('Only a loopback origin is allowed');
  if (!['ru', 'kk'].includes(values.lang)) throw new Error('Unsupported language');
  const fresh = process.env.PITCH_FRESH_DB;
  if (!fresh || !path.isAbsolute(fresh)) throw new Error('PITCH_FRESH_DB is required');
  const filename = await realpath(fresh);
  const dataRoot = await realpath(path.join(root, 'data'));
  const relative = path.relative(dataRoot, filename);
  if (!relative.startsWith('..') && !path.isAbsolute(relative))
    throw new Error('Never use a database inside data/');
  if (path.basename(filename).toLowerCase() === 'asboljam-kz.sqlite')
    throw new Error('Protected database');
  const configured = process.env.DATABASE_URL;
  if (!configured?.startsWith('sqlite:///') ||
      await realpath(configured.slice('sqlite:///'.length)) !== filename)
    throw new Error('DATABASE_URL must match PITCH_FRESH_DB');
  checkDatabase(filename);
  await mkdir(output, { recursive: true });
  try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
  catch { browser = await chromium.launch({ headless: true }); }
  const context = await browser.newContext({ baseURL: url.origin, viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1, locale: values.lang === 'ru' ? 'ru-RU' : 'kk-KZ',
    timezoneId: 'Asia/Almaty', reducedMotion: 'reduce' });
  await context.addInitScript(lang => localStorage.setItem('asboljam-language', lang), values.lang);
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);
  const kk = values.lang === 'kk', copy = (ru, kz) => kk ? kz : ru;
  const button = (ru, kz) => page.getByRole('button', { name: copy(ru, kz), exact: true });
  const header = (ru, kz) => page.locator('.app-header').getByRole('button', { name: copy(ru, kz), exact: true });
  const screenshot = async (name, scrollY = 0) => {
    await page.waitForLoadState('networkidle', { timeout: 60_000 });
    await expect(page.locator('.skeleton-grid:visible')).toHaveCount(0);
    await expect(page.getByText(copy('Проверяем задачи дня…', 'Күн міндеттерін тексереміз…'), { exact: true })).toHaveCount(0);
    await page.evaluate(async y => {
      await document.fonts.ready;
      await Promise.all([...document.images].map(img => img.decode().catch(() => {})));
      window.scrollTo(0, y);
    }, scrollY);
    await page.screenshot({ path: path.join(output, name), animations: 'disabled', fullPage: false });
    // Lossless PNG from Chromium; fail rather than silently committing oversized assets.
    if ((await stat(path.join(output, name))).size > 400 * 1024)
      throw new Error('Screenshot exceeds the asset budget');
    console.log(`Saved ${name}`);
  };

  stage = 'login';
  await page.goto(url.href);
  await button('Регистрация', 'Тіркелу').waitFor();
  await screenshot('login.png'); // Empty login screen, before generating any credential.
  stage = 'registration';
  await button('Регистрация', 'Тіркелу').click();
  const form = page.getByRole('form', { name: copy('Регистрация', 'Тіркелу') });
  const email = `pitch-${randomBytes(8).toString('hex')}@example.invalid`;
  // Random credential exists only in this process and in the transient browser form.
  let password = randomBytes(30).toString('base64url');
  stage = 'registration: establishment';
  await form.getByLabel(copy('Название заведения', 'Мекеме атауы')).fill('Алматы кафе · демо');
  stage = 'registration: type';
  await form.getByLabel(copy('Тип заведения', 'Мекеме түрі')).selectOption('cafe');
  stage = 'registration: city';
  await form.getByLabel(copy('Город', 'Қала')).selectOption('almaty');
  stage = 'registration: credentials';
  await form.getByLabel(copy('Электронная почта', 'Электрондық пошта')).fill(email);
  await form.locator('#register-password').fill(password);
  await form.getByLabel(copy('Повторите пароль', 'Құпиясөзді қайталаңыз')).fill(password);
  await form.locator('.register-consent input').check();
  stage = 'registration: submit';
  await button('Открыть кабинет', 'Кабинетті ашу').click();
  password = '';
  await expect(page).toHaveURL(/\/dashboard$/);
  checkDatabase(filename, email); // The stand must actually use the declared DB.
  stage = 'demo data';
  await button('Загрузить демо-данные', 'Демо-деректерді жүктеу').click();
  await expect(page.getByTestId('get-started')).toHaveCount(0, { timeout: 120_000 });
  await page.locator('.next-action').waitFor();
  stage = 'forecast';
  await header('Прогноз', 'Болжам').click();
  await expect(page.locator('.planning-preview input')).toHaveValue('01.01.2026');
  // Use the reproducible baseline; the deck does not pass it off as the factor model.
  await button('Рассчитать', 'Есептеу').click();
  await expect(page).toHaveURL(/\/forecasts\/[a-f0-9]+$/, { timeout: 180_000 });
  await page.locator('.forecast-result-number').waitFor();
  const forecast = await (await page.request.get('/api/v1' + new URL(page.url()).pathname)).json();
  if (forecast.result?.target_date !== '2026-01-01' && forecast.target_date !== '2026-01-01')
    throw new Error('Unexpected forecast date');
  await screenshot('forecast.png', 260);
  stage = 'purchase';
  await button('Остатки готовы — перейти к закупке', 'Қалдықтар дайын — сатып алуға өту').click();
  await page.getByLabel(copy('Бюджет, ₸', 'Бюджет, ₸'), { exact: true }).fill('150000');
  await button('Рассчитать', 'Есептеу').click();
  await expect(page).toHaveURL(/\/procurement\/[a-f0-9]+$/, { timeout: 180_000 });
  await page.locator('.procurement-result').waitFor();
  await screenshot('purchase.png', 260); // Calculated, never approved or sent.
  await header('Закупки', 'Сатып алу').click();
  stage = 'today';
  await header('Сегодня', 'Бүгін').click();
  await page.locator('.next-action').waitFor();
  await screenshot('today.png');
  stage = 'profile';
  await page.locator('.user-menu-trigger').click();
  await page.locator('.user-menu-panel').getByRole('menuitem', { name: 'Профиль', exact: true }).click();
  await page.locator('.profile-hero').waitFor();
  await screenshot('profile.png');
  stage = 'day close';
  await header('Сегодня', 'Бүгін').click();
  await button('Закрыть день', 'Күнді жабу').click();
  await button('Да, работало', 'Иә, жұмыс істеді').click();
  await expect(button('Да, работало', 'Иә, жұмыс істеді')).toHaveAttribute('aria-pressed', 'true');
  await screenshot('day-close.png'); // Leave unsaved, never confirm or close the day.
  console.log('Captured 6 real product screens, 1440×900; all data are SYNTHETIC.');
} catch {
  // Playwright errors can contain the argument to fill(), including a password.
  // Do not print the raw error, stack, request/response body or browser logs.
  console.error(`Pitch capture failed at: ${stage}. Check the isolated stand and README. No credentials logged.`);
  process.exitCode = 1;
} finally { await browser?.close(); }
