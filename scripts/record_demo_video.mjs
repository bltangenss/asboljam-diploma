// Records the Predas client demo as a WebM video with on-screen captions and a visible cursor:
// sign-up → demo data → forecast → close day → forecast vs actual → stock → purchase → approval → profile.
// It registers a NEW test-mode cabinet, so run it only against a disposable demo copy, never
// against working data. Requires the web, API and worker servers to be running.
//   node scripts/record_demo_video.mjs [--lang ru|kk] [--url http://localhost:3000] [--out .cache/demo-video]
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { parseArgs } from 'node:util';
import {
  assertDisposableStand, launchDemoBrowser, closeDemoDay,
  assertSyntheticForecast, waitForSuccessfulResponse,
} from './prepare_battle_demo.mjs';

async function recordDemo() {
let args;
try {
  ({ values: args } = parseArgs({ options: {
    lang: { type: 'string', default: 'ru' },
    url: { type: 'string', default: 'http://localhost:3000' },
    out: { type: 'string', default: '.cache/demo-video' },
  } }));
} catch {
  throw new Error('Invalid recording arguments. Use --lang ru|kk, --url http://localhost:3000 and optionally --out .cache/demo-video.');
}
if (!['ru', 'kk'].includes(args.lang)) throw new Error('--lang must be ru or kk');
const lang = args.lang;
const base = (args.url || 'http://localhost:3000').replace(/\/$/, '');
const out = path.resolve(args.out || '.cache/demo-video');
const W = 1280, H = 720;
assertDisposableStand(base);
try { fs.mkdirSync(out, { recursive: true }); }
catch { throw new Error('Cannot create the video output directory. Check --out and its permissions.'); }

const ru = lang === 'ru';
const say = {
  title: ru ? 'Знайте завтрашний спрос сегодня' : 'Ертеңгі сұранысты бүгін біліңіз',
  subtitle: ru ? 'Прогноз продаж и закупок для столовых, кафе и ресторанов Казахстана' : 'Қазақстандағы асхана, кафе және мейрамханаларға арналған сатылым мен сатып алу болжамы',
  signup: ru ? 'Заведение регистрируется само — за минуту' : 'Мекеме бір минутта өзі тіркеледі',
  form: ru ? 'Тип заведения и город: праздники, Рамадан, закат и погода считаются для него' : 'Мекеме түрі мен қаласы: мерекелер, Ораза, күн бату мен ауа райы сол бойынша есептеледі',
  empty: ru ? 'Новый кабинет пуст — попробуйте на демо-данных похожего заведения' : 'Жаңа кабинет бос — ұқсас мекеменің демо-деректерімен көріңіз',
  home: ru ? 'Главная подсказывает следующий шаг дня' : 'Басты бет күннің келесі қадамын көрсетеді',
  forecast: ru ? 'Учебный прогноз на 01.01.2026 — одной кнопкой' : '01.01.2026 күніне оқу болжамы — бір батырмамен',
  dishes: ru ? 'Ожидаемые порции каждого блюда на 01.01.2026' : '01.01.2026 күніне әр тағамның күтілетін порциялары',
  closeDay: ru ? 'Закрываем день: отмечаем меню и вводим проданные и готовые порции' : 'Күнді жабамыз: мәзірді белгілеп, сатылған және дайын порцияларды енгіземіз',
  comparison: ru ? 'Прогноз и факт: учебное сравнение синтетических данных, не оценка реального бизнеса' : 'Болжам мен нақты сатылым: синтетикалық деректерді оқу үшін салыстыру, нақты бизнесті бағалау емес',
  stock: ru ? 'Склад: что есть, что просрочено и что скоро истечёт' : 'Қойма: не бар, не өтіп кетті, не жақында бітеді',
  purchase: ru ? 'Закупка: прогноз × рецепты − остатки → упаковки поставщиков в бюджете' : 'Сатып алу: болжам × рецепт − қалдық → бюджет ішіндегі қаптамалар',
  lines: ru ? 'Что купить, у кого и сколько это стоит' : 'Не сатып алу керек, кімнен және қанша тұрады',
  approve: ru ? 'Решение принимает человек. Заказ поставщику не уходит автоматически' : 'Шешімді адам қабылдайды. Тапсырыс жеткізушіге өздігінен жіберілмейді',
  reason: ru ? 'Проверил цены и остатки' : 'Бағалар мен қалдықтар тексерілді',
  profile: ru ? 'Профиль заведения: город, тип, меню и команда' : 'Мекеме профилі: қала, түрі, мәзір және команда',
  factors: ru ? 'Праздники, Рамадан, каникулы, закат и погода — автоматически' : 'Мерекелер, Ораза, демалыс, күн бату және ауа райы — автоматты түрде',
  end: ru ? 'Прогноз → закрытие дня → сравнение → закупка → решение управляющего' : 'Болжам → күнді жабу → салыстыру → сатып алу → басқарушының шешімі',
  demoNote: ru ? 'Демонстрация на синтетических данных' : 'Синтетикалық деректердегі көрсетілім',
};
const label = {
  register: ru ? 'Регистрация' : 'Тіркелу', name: ru ? 'Название заведения' : 'Мекеме атауы', type: ru ? 'Тип заведения' : 'Мекеме түрі',
  city: ru ? 'Город' : 'Қала', email: ru ? 'Электронная почта' : 'Электрондық пошта', repeat: ru ? 'Повторите пароль' : 'Құпиясөзді қайталаңыз',
  open: ru ? /Открыть кабинет/ : /Кабинетті ашу/, demo: ru ? 'Загрузить демо-данные' : 'Демо-деректерді жүктеу',
  stock: ru ? 'Склад' : 'Қойма', purchase: ru ? 'Закупки' : 'Сатып алу', confirm: ru ? 'Утвердить план' : 'Жоспарды бекіту', profile: 'Профиль',
  cafe: 'Кафе «Достар»',
};

function overlay() {
  const install = () => {
    if (document.getElementById('demo-caption')) return;
    const style = document.createElement('style');
    style.textContent = `#demo-caption{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:2147483647;max-width:min(900px,88vw);padding:13px 22px;border-radius:16px;background:rgba(28,25,23,.9);color:#fff;font:600 20px/1.4 "Onest Variable",system-ui,sans-serif;letter-spacing:-.01em;text-align:center;box-shadow:0 14px 40px rgba(0,0,0,.25);transition:opacity .3s;pointer-events:none}
#demo-caption:empty{opacity:0}
#demo-cursor{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.35))}
#demo-cursor.down svg{transform:scale(.86)}
#demo-card{position:fixed;inset:0;z-index:2147483646;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;background:#fff;color:#1c1917;font-family:"Onest Variable",system-ui,sans-serif;text-align:center;padding:40px}
#demo-card .mark{width:84px;height:84px}#demo-card h1{font-size:54px;letter-spacing:-.04em;margin:0;font-weight:720}#demo-card p{font-size:22px;color:#57534e;margin:0;max-width:760px;line-height:1.45}#demo-card small{font-size:14px;color:#a8a29e}`;
    document.head.appendChild(style);
    const caption = document.createElement('div'); caption.id = 'demo-caption'; document.body.appendChild(caption);
    const cursor = document.createElement('div'); cursor.id = 'demo-cursor';
    cursor.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M4 2l15 9.5-6.6 1.2 3.8 7.3-2.6 1.4-3.8-7.3L5 19z" fill="#1c1917" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(cursor);
    document.addEventListener('mousemove', event => { cursor.style.transform = `translate(${event.clientX - 4}px,${event.clientY - 2}px)`; }, true);
    document.addEventListener('mousedown', () => cursor.classList.add('down'), true);
    document.addEventListener('mouseup', () => cursor.classList.remove('down'), true);
    window.__caption = text => { caption.textContent = text || ''; };
    window.__card = (title, text, note) => {
      document.getElementById('demo-card')?.remove();
      if (!title) return;
      const card = document.createElement('div'); card.id = 'demo-card';
      card.innerHTML = `<svg class="mark" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#FF5A1F"/><g fill="none" stroke="#fff" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 8V25"/><path d="M10 8H25.5"/><path d="M24 8A7 7 0 0 1 17 15A7 7 0 0 1 10 8"/></g></svg><h1></h1><p></p><small></small>`;
      card.querySelector('h1').textContent = title; card.querySelector('p').textContent = text; card.querySelector('small').textContent = note || '';
      document.body.appendChild(card);
    };
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
}

// Redact credentials visually before the first video frame. Input values and the real
// authentication request remain intact; no session state or API response is substituted.
function redactLogin(email) {
  const install = () => {
    const style = document.createElement('style');
    style.textContent = 'input[type="email"]{color:transparent!important;caret-color:transparent!important;text-shadow:none!important}.user-info strong{visibility:hidden!important}';
    document.head.appendChild(style);
    const redactText = () => {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) if (walker.currentNode.nodeValue.includes(email)) nodes.push(walker.currentNode);
      for (const node of nodes) node.nodeValue = node.nodeValue.replaceAll(email, 'demo account');
    };
    new MutationObserver(redactText).observe(document.body, { subtree: true, childList: true, characterData: true });
    redactText();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
}

const started = Date.now();
const email = 'demo-' + crypto.randomBytes(12).toString('hex') + '@example.invalid';
const password = crypto.randomBytes(24).toString('base64url') + 'aA1!';
const browser = await launchDemoBrowser();
let context;
let page;
let stage = 'browser/video startup (check Playwright FFmpeg installation)';
try {
context = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, recordVideo: { dir: out, size: { width: W, height: H } } });
await context.addInitScript(language => localStorage.setItem('asboljam-language', language), lang);
await context.addInitScript(overlay);
await context.addInitScript(redactLogin, email);
page = await context.newPage();
page.setDefaultTimeout(60000);
// These pauses pace the presentation; operation readiness uses locators/API receipts.
const pause = ms => page.waitForTimeout(ms);
const caption = async text => { await page.evaluate(value => window.__caption?.(value), text); };
let pointer = { x: W / 2, y: H / 2 };
async function point(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error('The current demo control is not visible');
  const target = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(pointer.x, pointer.y);
  await page.mouse.move(target.x, target.y, { steps: 22 });
  pointer = target;
  await pause(250);
}
async function click(locator) { await point(locator); await locator.click(); }
async function type(locator, text) { await click(locator); await locator.pressSequentially(text, { delay: 55 }); }
async function scroll(distance, steps = 12) { for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, distance / steps); await pause(60); } }

stage = 'opening the stand';
const ready = await context.request.get(base + '/api/v1/ready', { timeout: 30000 });
if (!ready.ok()) throw new Error('API is not ready; inspect the isolated stand logs and migrations');
await page.goto(base + '/');
await page.evaluate(([title, text, note]) => window.__card(title, text, note), ['predas', say.title + '. ' + say.subtitle, say.demoNote]);
await pause(3800);
await page.evaluate(() => window.__card(''));
await caption(say.signup); await pause(1600);
stage = 'registration';
await click(page.getByRole('button', { name: label.register }));
await caption(say.form); await pause(800);
await type(page.getByLabel(label.name), label.cafe);
await click(page.getByLabel(label.type)); await page.getByLabel(label.type).selectOption('cafe'); await pause(400);
await click(page.getByLabel(label.city)); await page.getByLabel(label.city).selectOption('almaty'); await pause(600);
await type(page.getByLabel(label.email), email);
await type(page.locator('#register-password'), password);
await type(page.getByLabel(label.repeat), password);
await click(page.locator('.register-consent input')); await page.locator('.register-consent input').check();
await pause(700);
await waitForSuccessfulResponse(page, '/api/v1/register', () => click(page.getByRole('button', { name: label.open })));
await page.getByTestId('get-started').waitFor();
stage = 'loading synthetic demo data';
await caption(say.empty); await pause(2600);
await waitForSuccessfulResponse(page, '/api/v1/demo-data', () => click(page.getByRole('button', { name: label.demo })));
await page.locator('.next-action').waitFor({ timeout: 120000 });
await caption(say.home); await pause(1800);
await point(page.locator('.day-pipeline')); await pause(1600);
await click(page.locator('.next-action').getByRole('button').first());
await page.locator('.planning-form-actions .primary').waitFor();
stage = 'forecast for 01.01.2026';
await assertSyntheticForecast(page);
await caption(say.forecast); await pause(1500);
await waitForSuccessfulResponse(page, '/api/v1/forecasts', () => click(page.locator('.planning-form-actions .primary')));
await page.waitForURL(/\/forecasts\/[^/?]+/, { timeout: 300000 });
await page.locator('.forecast-result-context').waitFor({ timeout: 60000 });
if ((await page.locator('.forecast-result-context strong').textContent())?.trim() !== '01.01.2026') {
  throw new Error('The completed forecast is not for the fixed synthetic target 01.01.2026');
}
await caption(say.dishes); await pause(1800);
await scroll(700); await pause(1800); await scroll(-700); await pause(500);
stage = 'closing the day';
await caption(say.closeDay); await pause(1800);
// Start observing before navigating: a fast comparison response must not be missed.
let reviewResponse = Promise.resolve(null);
await closeDemoDay(page, lang, {
  click,
  fill: async (locator, value) => { await locator.fill(''); await type(locator, value); },
  onClosed: async () => {
    await pause(2200);
    reviewResponse = page.waitForResponse(response =>
      new URL(response.url()).pathname === '/api/v1/forecast-review' &&
      response.request().method() === 'GET', { timeout: 20000 }).catch(() => null);
  },
});
stage = 'optional forecast and actual comparison';
// Stage 2 is optional. An older stand or an unavailable comparison must not lose the video.
try {
  const review = page.getByTestId('forecast-review');
  // Today can have been visited before closing. Wait for its current, post-close card.
  const response = await reviewResponse;
  if (response?.ok()) {
    await review.waitFor({ timeout: 15000 });
    await caption(say.comparison);
    const details = review.locator('details').first();
    if ((await details.getAttribute('open')) === null) await click(details.locator(':scope > summary'));
    await review.locator('.review-day-kind').waitFor({ timeout: 15000 });
    // Synthetic summary metrics are deliberately folded separately from business metrics.
    const demoMetrics = review.locator('.review-demo');
    if (await demoMetrics.count()) {
      if ((await demoMetrics.getAttribute('open')) === null) await click(demoMetrics.locator(':scope > summary'));
      await point(demoMetrics.locator('.review-metrics'));
      await pause(2500);
    }
    // The dish rows belong to the OUTER disclosure. Bring the actual table header into
    // view explicitly instead of assuming a fixed scroll exposes forecast and sales.
    const comparison = review.getByRole('table');
    await comparison.locator('tbody tr').first().waitFor({ timeout: 15000 });
    await point(comparison.getByRole('columnheader', { name: ru ? 'Прогноз дня' : 'Күн болжамы', exact: true }));
    await pause(6000);
    await scroll(200); await pause(2200);
  } else {
    console.log('Optional forecast-vs-actual card unavailable; continuing the recording.');
  }
} catch {
  console.log('Optional forecast-vs-actual card could not be displayed; continuing the recording.');
}
stage = 'stock';
await click(page.locator('.app-nav').getByRole('button', { name: label.stock, exact: true }));
await page.waitForURL(/\/inventory(?:[/?]|$)/);
await caption(say.stock); await pause(1200); await scroll(560); await pause(2200); await scroll(-560);
await click(page.locator('.app-nav').getByRole('button', { name: label.purchase, exact: true }));
await page.locator('.planning-form-actions .primary').waitFor();
stage = 'purchase calculation';
await caption(say.purchase); await pause(2200);
await waitForSuccessfulResponse(page, '/api/v1/procurement', () => click(page.locator('.planning-form-actions .primary')));
await page.waitForURL(/\/procurement\/[^/?]+/, { timeout: 300000 });
await page.locator('.decision-bar').waitFor({ timeout: 60000 });
await caption(say.lines); await pause(1500); await scroll(650); await pause(2200);
const decide = page.locator('.decision-bar').getByRole('button', { name: label.confirm });
stage = 'human approval';
await caption(say.approve);
await click(decide);
const dialog = page.locator('dialog[open]');
await type(dialog.locator('textarea'), say.reason);
const acknowledge = dialog.locator('input[type=checkbox]');
if (await acknowledge.count()) { await click(acknowledge); await acknowledge.check(); }
const planId = new URL(page.url()).pathname.split('/').filter(Boolean).at(-1);
await waitForSuccessfulResponse(page, '/api/v1/plans/' + encodeURIComponent(planId) + '/approve', () => click(dialog.locator('.dialog-actions button').last()));
await page.locator('.decision-receipt').waitFor({ timeout: 60000 });
await pause(2600);
stage = 'establishment profile';
await click(page.locator('.user-menu-trigger'));
await click(page.locator('.user-menu-panel').getByRole('menuitem', { name: label.profile }));
await page.locator('.profile-hero').waitFor();
await caption(say.profile); await pause(2400);
await click(page.locator('.profile-factors>summary'));
await caption(say.factors); await pause(900); await scroll(520); await pause(2600);
await caption('');
await page.evaluate(([title, text, note]) => window.__card(title, text, note), ['predas', say.end, say.demoNote]);
await pause(3500);
stage = 'saving the recorded video';
const video = page.video();
await context.close();
await browser.close();
const target = path.join(out, `predas-demo-${lang}.webm`);
fs.renameSync(await video.path(), target);
console.log(target);
console.log(`Recording completed in ${((Date.now() - started) / 1000).toFixed(1)} s.`);
} catch (error) {
  // Playwright call logs may contain fill arguments. Keep credentials out of diagnostics.
  console.error(`Recording failed during ${stage} (${error.name || 'Error'}). Check the stand and .cache/logs.`);
  if (page) await page.screenshot({ path: path.join(out, 'failure.png'), mask: [page.locator('input[type="email"], input[type="password"], #register-password'), page.getByText(email, { exact: false })] }).catch(() => {});
  process.exitCode = 1;
} finally {
  await context?.close().catch(() => {});
  await browser.close().catch(() => {});
}
}

recordDemo().catch(error => {
  // Startup/argument errors have no browser screenshot and must not dump Error objects
  // (Node's invalid-URL errors can carry an .input property containing credentials).
  console.error(String(error.message || 'Recording startup failed.').split('\n')[0]);
  process.exitCode = 1;
});
