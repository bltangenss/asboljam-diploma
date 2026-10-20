// HTTP-only readiness client. No database access, configuration changes or stored logins.
import { parseArgs } from 'node:util';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

class StandError extends Error {}

const help = `Predas stand check
Usage: node scripts/check_stand.mjs [--url http://localhost:3000] [--lang ru|kk] [--full] [--timeout 120]
Quick: public HTTP checks only; the required anonymous POST must be refused.
Warm-up: GET /api/v1/health every 5 seconds, up to 120 seconds by default.
--timeout: positive seconds (up to 120), useful for testing an unused local port.
--full: AFTER quick checks, create ONE SYNTHETIC test cabinet through the real UI.
Run full mode at most once before the pitch. Limit: 5 registrations/hour/address,
potentially shared behind Render. Choose a target appropriate for test data.
Full mode requires Playwright and Chrome or bundled Chromium. Password stays in memory.
An unsuccessful browser run saves one masked screenshot under ignored .cache/stand-check/.
Only HTTP(S) origins are accepted; plain HTTP is restricted to loopback hosts.
Cloud checks become meaningful after Cloudflare Pages, Render and Supabase are deployed.`;

export function validateOrigin(value) {
  let url;
  try { url = new URL(value); } catch { throw new StandError('Invalid URL. Supply only an HTTP(S) origin, without credentials, path, query or fragment.'); }
  // Check the original spelling too: URL parsing normalizes dot paths, empty ?/#,
  // backslashes and whitespace, which must not silently become an accepted origin.
  const authority = value.match(/^https?:\/\/([^/?#\\\s]+)\/?$/i)?.[1];
  const spelling = Boolean(authority) && !authority.includes('@') && !authority.endsWith(':');
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (!spelling || url.username || url.password || url.pathname !== '/' || url.search || url.hash
      || !url.hostname
      || !['https:', 'http:'].includes(url.protocol) || url.protocol === 'http:' && !local) {
    throw new StandError('Unsafe URL. Supply an HTTPS origin (or HTTP loopback), without credentials, path, query or fragment.');
  }
  return url.origin;
}

function options(argv) {
  let values;
  try { ({ values } = parseArgs({ args: argv, options: {
    url: { type: 'string', default: 'http://localhost:3000' }, lang: { type: 'string', default: 'ru' },
    full: { type: 'boolean', default: false }, timeout: { type: 'string', default: '120' }, help: { type: 'boolean', short: 'h' },
  } })); } catch { throw new StandError('Invalid arguments. Run node scripts/check_stand.mjs --help.'); }
  if (values.help) return { help: true };
  if (!['ru', 'kk'].includes(values.lang)) throw new StandError('--lang must be ru or kk.');
  const timeout = Number(values.timeout);
  if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 120) throw new StandError('--timeout must be a positive number of seconds, no greater than 120.');
  return { origin: validateOrigin(values.url), lang: values.lang, full: values.full, timeout: timeout * 1000 };
}

const guidance = {
  API_NOT_CONFIGURED: 'API_NOT_CONFIGURED: set API_ORIGIN in Cloudflare Pages and redeploy the site.',
  ORIGIN_FORBIDDEN: 'ORIGIN_FORBIDDEN: check the exact site origin in ALLOWED_ORIGINS on Render.',
  RATE_LIMITED: 'RATE_LIMITED: stop repeating full mode; registration is limited to 5/hour/address, shared behind Render.',
  SELF_REGISTRATION_DISABLED: 'Self-registration is disabled. Check ASBOLJAM_SELF_REGISTRATION on the approved demo target.',
};

function errorCode(body) {
  const code = body?.detail?.code;
  return typeof code === 'string' && /^[A-Z][A-Z0-9_]{0,79}$/.test(code) ? code : '';
}

// Node fetch has no cookie jar. Explicit omit/manual prevent credentials or redirects
// from changing the meaning of anonymous checks. Never print arbitrary response bodies.
async function request(origin, pathname, { timeout = 15000, method = 'GET', json } = {}) {
  const headers = { Accept: pathname === '/' ? 'text/html' : 'application/json' };
  if (method === 'POST') { headers['Content-Type'] = 'application/json'; headers.Origin = origin; }
  try {
    const response = await fetch(origin + pathname, {
      method, headers, body: json === undefined ? undefined : JSON.stringify(json),
      redirect: 'manual', credentials: 'omit', signal: AbortSignal.timeout(Math.max(1, Math.ceil(timeout))),
    });
    const text = await response.text();
    let body;
    try { body = JSON.parse(text); } catch { body = null; }
    return { response, text, body };
  } catch {
    throw new StandError(`Cannot reach ${pathname}. Check the frontend/proxy and API service; allow Render to finish waking up.`);
  }
}

function requireStatus(result, expected, endpoint) {
  const code = errorCode(result.body);
  if (result.response.status !== expected) throw new StandError(guidance[code]
    || `${endpoint}: HTTP ${result.response.status}${code ? ' ' + code : ''}. Check the service logs and /api proxy.`);
}

export async function warmUp(origin, timeout) {
  const deadline = performance.now() + timeout;
  let last = 'No HTTP 200 received.';
  do {
    const attempt = performance.now();
    try {
      const result = await request(origin, '/api/v1/health', { timeout: Math.min(5000, Math.max(1, deadline - attempt)) });
      const code = errorCode(result.body);
      if (guidance[code]) throw Object.assign(new StandError(guidance[code]), { permanent: true });
      if (result.response.status === 200) {
        if (result.body?.status !== 'ok') throw Object.assign(new StandError('Health returned HTTP 200 without the real API JSON. Check /api reverse proxy routing.'), { permanent: true });
        return 'HTTP 200';
      }
      last = `Last health response: HTTP ${result.response.status}.`;
    } catch (error) {
      if (error.permanent) throw error;
      last = error.message;
    }
    const remaining = deadline - performance.now();
    if (remaining <= 0) break;
    await delay(Math.min(Math.max(0, 5000 - (performance.now() - attempt)), remaining));
  } while (performance.now() < deadline);
  throw new StandError(`No healthy API within ${(timeout / 1000).toFixed(1)} s. ${last} Check Render/API logs, then repeat quick mode.`);
}

export function applicationHtml(contentType, html) {
  return /\btext\/html\b/i.test(contentType || '')
    && /<div\b[^>]*\sid\s*=\s*["']root["'][^>]*>/i.test(html)
    && [...html.matchAll(/<script\b[^>]*>/gi)].some(([tag]) =>
      /\stype\s*=\s*["']module["']/i.test(tag) && /\ssrc\s*=/i.test(tag));
}

async function frontend(origin) {
  const result = await request(origin, '/');
  requireStatus(result, 200, 'frontend');
  const html = applicationHtml(result.response.headers.get('content-type'), result.text);
  if (!html) throw new StandError('Frontend is not the Predas HTML application (root/module entry missing). Check the deployed web build.');
  const required = { 'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff' };
  let valid = true;
  for (const [header, expected] of Object.entries(required)) {
    const actual = result.response.headers.get(header);
    const matches = actual?.trim().toLowerCase() === expected.toLowerCase();
    valid &&= matches;
    // Only print known values, never reflect arbitrary untrusted header content.
    console.log(`  ${header}: ${matches ? expected : actual === null ? '<missing>' : '<unexpected>'} (expected ${expected})`);
  }
  if (!valid) throw new StandError('Frontend security headers are missing or wrong. Check the web reverse proxy; bare Vite does not provide these headers.');
}

async function registration(origin) {
  const result = await request(origin, '/api/v1/registration');
  requireStatus(result, 200, 'registration');
  if (typeof result.body?.enabled !== 'boolean' || result.body.mode !== 'synthetic_only') throw new StandError('Registration API schema is invalid. Check /api routing and deployed backend version.');
  console.log(`  self-registration: ${result.body.enabled ? 'enabled' : 'disabled'}; mode: synthetic_only`);
  if (!result.body.enabled) throw new StandError(guidance.SELF_REGISTRATION_DISABLED);
}

async function unauthorized(origin) {
  const result = await request(origin, '/api/v1/demo-data', { method: 'POST', json: { branch_id: '1' } });
  const code = errorCode(result.body);
  if (code === 'ORIGIN_FORBIDDEN') throw new StandError(guidance[code]);
  if (![401, 403].includes(result.response.status)) throw new StandError(`Anonymous demo-data returned HTTP ${result.response.status}; expected 401 or 403. Check API authentication immediately.`);
  return `HTTP ${result.response.status} (no cookie, CSRF or Authorization)`;
}

async function runFull(config, step) {
  let browser, context, page;
  // These constants are copied from record_demo_video.mjs; it is never imported.
  const ru = config.lang === 'ru';
  const label = {
    register: ru ? 'Регистрация' : 'Тіркелу', name: ru ? 'Название заведения' : 'Мекеме атауы',
    type: ru ? 'Тип заведения' : 'Мекеме түрі', city: ru ? 'Город' : 'Қала',
    email: ru ? 'Электронная почта' : 'Электрондық пошта', repeat: ru ? 'Повторите пароль' : 'Құпиясөзді қайталаңыз',
    open: ru ? /Открыть кабинет/ : /Кабинетті ашу/, demo: ru ? 'Загрузить демо-данные' : 'Демо-деректерді жүктеу',
    purchase: ru ? 'Закупки' : 'Сатып алу', profile: 'Профиль', today: ru ? 'Сегодня' : 'Бүгін',
    close: ru ? 'Закрыть день' : 'Күнді жабу', operated: ru ? 'Да, работало' : 'Иә, жұмыс істеді',
    discard: ru ? 'Отменить изменения и перейти' : 'Өзгерістерді болдырмау және өту',
  };
  const email = `stand-check-${randomBytes(12).toString('hex')}@example.invalid`;
  const password = 'Aa9!' + randomBytes(24).toString('base64url');
  try {
    let expect;
    await step('browser', async () => {
      let chromium, playwrightExpect;
      try { ({ chromium, expect: playwrightExpect } = await import('@playwright/test')); }
      catch { throw new StandError('Playwright is missing. Run npm ci and npx playwright install chromium.'); }
      expect = playwrightExpect.configure({ timeout: 60000 });
      try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
      catch {
        console.log('  Chrome unavailable; trying bundled Chromium.');
        try { browser = await chromium.launch({ headless: true }); }
        catch { throw new StandError('No usable browser. Install Chrome or run npx playwright install chromium.'); }
      }
      context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await context.addInitScript(language => localStorage.setItem('asboljam-language', language), config.lang);
      page = await context.newPage();
      page.setDefaultTimeout(60000);
    });
    const mutation = async (pathname, action) => {
      const [response] = await Promise.all([
        page.waitForResponse(r => new URL(r.url()).pathname === pathname && r.request().method() === 'POST', { timeout: 120000 }), action(),
      ]);
      if (!response.ok()) {
        const body = await response.json().catch(() => null);
        const code = errorCode(body);
        throw new StandError(guidance[code] || `API operation failed: HTTP ${response.status()}${code ? ' ' + code : ''}. Check the visible validation and service logs.`);
      }
    };
    await step('register cafe', async () => {
      await page.goto(config.origin + '/', { waitUntil: 'domcontentloaded' });
      await page.getByRole('button', { name: label.register, exact: true }).click();
      await page.getByLabel(label.name).fill('Stand check — Кафе «Достар»');
      await page.getByLabel(label.type).selectOption('cafe');
      await page.getByLabel(label.city).selectOption('almaty');
      await page.getByLabel(label.email).fill(email);
      await page.locator('#register-password').fill(password);
      await page.getByLabel(label.repeat).fill(password);
      await page.locator('.register-consent input').check();
      // Exactly one registration submission. A lost reply is a failure, never an automatic retry.
      await mutation('/api/v1/register', () => page.getByRole('button', { name: label.open }).click());
      await expect(page.getByTestId('get-started')).toBeVisible();
    });
    await step('load demo data', async () => {
      await mutation('/api/v1/demo-data', () => page.getByRole('button', { name: label.demo, exact: true }).click());
      await expect(page.locator('.next-action')).toBeVisible({ timeout: 120000 });
    });
    await step('forecast', async () => {
      await page.locator('.app-nav').getByRole('button', { name: ru ? 'Прогноз' : 'Болжам', exact: true }).click();
      await expect(page.locator('.planning-preview .planning-date')).toHaveValue('01.01.2026');
      await mutation('/api/v1/forecasts', () => page.locator('.planning-form-actions .primary').click());
      await page.waitForURL(/\/forecasts\/[^/?]+/, { timeout: 300000 });
      await expect(page.locator('.forecast-result-hero')).toBeVisible();
      await expect(page.locator('.forecast-result-context strong')).toHaveText('01.01.2026');
    });
    await step('purchases', async () => {
      await page.locator('.app-nav').getByRole('button', { name: label.purchase, exact: true }).click();
      await expect(page).toHaveURL(/\/procurement(?:\?|$)/);
      await expect(page.locator('.planning-form-actions .primary')).toBeEnabled();
    });
    await step('day-close form', async () => {
      await page.locator('.app-nav').getByRole('button', { name: label.today, exact: true }).click();
      await page.locator('.day-close-entry').click();
      await expect(page.locator('.day-close-head h1')).toHaveText(label.close);
      const operated = page.getByRole('button', { name: label.operated, exact: true });
      await operated.click();
      await expect(operated).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator('.day-close-meal').first()).toBeVisible();
      // No save, review or final close action is submitted.
    });
    await step('profile', async () => {
      await page.locator('.user-menu-trigger').click();
      await page.locator('.user-menu-panel').getByRole('menuitem', { name: label.profile, exact: true }).click();
      const guard = page.locator('.navigation-guard-dialog');
      await expect(guard).toBeVisible();
      await guard.getByRole('button', { name: label.discard, exact: true }).click();
      await expect(page).toHaveURL(/\/profile$/);
      await expect(page.locator('.profile-hero h1')).toHaveText('Stand check — Кафе «Достар»');
    });
  } catch (error) {
    if (page && !page.isClosed()) {
      try {
        const cache = fileURLToPath(new URL('../.cache/', import.meta.url));
        const directory = path.join(cache, 'stand-check');
        for (const target of [cache, directory]) {
          try { if (fs.lstatSync(target).isSymbolicLink()) throw new StandError('Linked screenshot destination'); }
          catch (problem) { if (problem.code !== 'ENOENT') throw problem; }
        }
        fs.mkdirSync(directory, { recursive: true });
        const filename = `failure-${Date.now()}-${randomBytes(4).toString('hex')}.png`;
        await page.screenshot({ path: path.join(directory, filename), timeout: 15000, mask: [
          page.locator('.register-form, input, textarea, [contenteditable=true]'), page.getByText(email, { exact: false }),
        ] });
        console.log(`  Masked screenshot: .cache/stand-check/${filename}`);
      } catch { console.log('  Screenshot unavailable; check permissions for ignored .cache/stand-check/.'); }
    }
    throw error;
  } finally {
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
  }
}

export async function main(argv = process.argv.slice(2)) {
  let current = 'arguments';
  let failure;
  const step = async (name, action) => {
    current = name;
    const started = performance.now();
    try {
      const detail = await action();
      console.log(`OK ${(performance.now() - started) / 1000 < 0.05 ? '0.0' : ((performance.now() - started) / 1000).toFixed(1)} s ${name}${typeof detail === 'string' ? ' — ' + detail : ''}`);
    } catch (error) {
      failure ||= name;
      // Playwright call logs can contain passwords; only our own messages are safe.
      const known = error instanceof StandError;
      const reason = known && error.name === 'Error' ? error.message.split('\n')[0] : 'Browser/UI operation failed or timed out. Check the visible screen and API/worker logs; do not repeat full mode blindly.';
      console.error(`FAIL ${((performance.now() - started) / 1000).toFixed(1)} s ${name} — ${reason}`);
      throw error;
    }
  };
  try {
    const config = options(argv);
    if (config.help) { console.log(help); return 0; }
    if (config.full) console.log('WARNING: --full creates ONE SYNTHETIC test cabinet on the selected target. Run at most once before the pitch; limit 5 registrations/hour/address, potentially shared behind Render. Password stays in memory.');
    await step('warm-up', () => warmUp(config.origin, config.timeout));
    for (const [name, action] of [['frontend', frontend], ['registration', registration], ['unauthorized demo-data', unauthorized]]) {
      try { await step(name, () => action(config.origin)); } catch { /* Report remaining independent quick checks too. */ }
    }
    if (failure) { console.error(`STAND FAILED at ${failure}`); return 1; }
    if (config.full) await runFull(config, step);
    console.log('STAND OK');
    return 0;
  } catch (error) {
    if (!failure) console.error('FAIL — ' + (current === 'arguments' ? error.message : 'Check browser dependencies and target service logs.'));
    console.error(`STAND FAILED at ${failure || current}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  process.exitCode = await main();
}
