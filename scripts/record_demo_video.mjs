// Records the Predas client demo as a WebM video with on-screen captions and a visible cursor:
// sign-up → demo data → forecast → stock → purchase → human approval → establishment profile.
// It registers a NEW test-mode cabinet, so run it only against a disposable demo copy, never
// against working data. Requires the web, API and worker servers to be running.
//   node scripts/record_demo_video.mjs [--lang ru|kk] [--url http://localhost:3000] [--out .cache/demo-video]
import { chromium } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const args = {};
process.argv.slice(2).forEach((value, index, all) => { if (value.startsWith('--')) args[value.slice(2)] = all[index + 1]; });
const lang = args.lang === 'kk' ? 'kk' : 'ru';
const base = (args.url || 'http://localhost:3000').replace(/\/$/, '');
const out = path.resolve(args.out || '.cache/demo-video');
const W = 1280, H = 720;
fs.mkdirSync(out, { recursive: true });

const ru = lang === 'ru';
const say = {
  title: ru ? 'Знайте завтрашний спрос сегодня' : 'Ертеңгі сұранысты бүгін біліңіз',
  subtitle: ru ? 'Прогноз продаж и закупок для столовых, кафе и ресторанов Казахстана' : 'Қазақстандағы асхана, кафе және мейрамханаларға арналған сатылым мен сатып алу болжамы',
  signup: ru ? 'Заведение регистрируется само — за минуту' : 'Мекеме бір минутта өзі тіркеледі',
  form: ru ? 'Тип заведения и город: праздники, Рамадан, закат и погода считаются для него' : 'Мекеме түрі мен қаласы: мерекелер, Ораза, күн бату мен ауа райы сол бойынша есептеледі',
  empty: ru ? 'Новый кабинет пуст — попробуйте на демо-данных похожего заведения' : 'Жаңа кабинет бос — ұқсас мекеменің демо-деректерімен көріңіз',
  home: ru ? 'Главная подсказывает следующий шаг дня' : 'Басты бет күннің келесі қадамын көрсетеді',
  forecast: ru ? 'Прогноз на завтра — одной кнопкой' : 'Ертеңгі болжам — бір батырмамен',
  dishes: ru ? 'Сколько порций каждого блюда продастся завтра' : 'Ертең әр тағамнан қанша порция сатылады',
  stock: ru ? 'Склад: что есть, что просрочено и что скоро истечёт' : 'Қойма: не бар, не өтіп кетті, не жақында бітеді',
  purchase: ru ? 'Закупка: прогноз × рецепты − остатки → упаковки поставщиков в бюджете' : 'Сатып алу: болжам × рецепт − қалдық → бюджет ішіндегі қаптамалар',
  lines: ru ? 'Что купить, у кого и сколько это стоит' : 'Не сатып алу керек, кімнен және қанша тұрады',
  approve: ru ? 'Решение принимает человек. Заказ поставщику не уходит автоматически' : 'Шешімді адам қабылдайды. Тапсырыс жеткізушіге өздігінен жіберілмейді',
  reason: ru ? 'Проверил цены и остатки' : 'Бағалар мен қалдықтар тексерілді',
  profile: ru ? 'Профиль заведения: город, тип, меню и команда' : 'Мекеме профилі: қала, түрі, мәзір және команда',
  factors: ru ? 'Праздники, Рамадан, каникулы, закат и погода — автоматически' : 'Мерекелер, Ораза, демалыс, күн бату және ауа райы — автоматты түрде',
  end: ru ? 'Регистрация → демо-данные → прогноз и закупка за две минуты' : 'Тіркелу → демо-деректер → екі минутта болжам мен сатып алу',
  demoNote: ru ? 'Демонстрация на синтетических данных' : 'Синтетикалық деректердегі көрсетілім',
};
const label = {
  register: ru ? 'Регистрация' : 'Тіркелу', name: ru ? 'Название заведения' : 'Мекеме атауы', type: ru ? 'Тип заведения' : 'Мекеме түрі',
  city: ru ? 'Город' : 'Қала', email: ru ? 'Электронная почта' : 'Электрондық пошта', repeat: ru ? 'Повторите пароль' : 'Құпиясөзді қайталаңыз',
  open: ru ? /Открыть кабинет/ : /Кабинетті ашу/, demo: ru ? 'Загрузить демо-данные' : 'Демо-деректерді жүктеу',
  stock: ru ? 'Склад' : 'Қойма', purchase: ru ? 'Закупки' : 'Сатып алу', confirm: ru ? 'Утвердить план' : 'Жоспарды бекіту', profile: 'Профиль',
  cafe: ru ? 'Кафе «Достар»' : 'Достар кафесі',
};

function overlay(cards) {
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

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, recordVideo: { dir: out, size: { width: W, height: H } } });
await context.addInitScript(language => localStorage.setItem('asboljam-language', language), lang);
await context.addInitScript(overlay);
const page = await context.newPage();
page.setDefaultTimeout(60000);
const pause = ms => page.waitForTimeout(ms);
const caption = async text => { await page.evaluate(value => window.__caption?.(value), text); };
let pointer = { x: W / 2, y: H / 2 };
async function point(locator) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  const target = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  await page.mouse.move(pointer.x, pointer.y);
  await page.mouse.move(target.x, target.y, { steps: 22 });
  pointer = target;
  await pause(250);
}
async function click(locator) { await point(locator); await locator.click(); }
async function type(locator, text) { await click(locator); await locator.pressSequentially(text, { delay: 55 }); }
async function scroll(distance, steps = 12) { for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, distance / steps); await pause(60); } }

try {
await page.goto(base + '/');
await page.evaluate(([title, text, note]) => window.__card(title, text, note), ['predas', say.title + '. ' + say.subtitle, say.demoNote]);
await pause(3800);
await page.evaluate(() => window.__card(''));
await caption(say.signup); await pause(1600);
await click(page.getByRole('button', { name: label.register }));
await caption(say.form); await pause(800);
await type(page.getByLabel(label.name), label.cafe);
await click(page.getByLabel(label.type)); await page.getByLabel(label.type).selectOption('cafe'); await pause(400);
await click(page.getByLabel(label.city)); await page.getByLabel(label.city).selectOption('almaty'); await pause(600);
await type(page.getByLabel(label.email), 'owner-' + crypto.randomBytes(3).toString('hex') + '@example.invalid');
const password = crypto.randomBytes(12).toString('base64url');
await type(page.locator('#register-password'), password);
await type(page.getByLabel(label.repeat), password);
await click(page.locator('.register-consent input')); await page.locator('.register-consent input').check();
await pause(700);
await click(page.getByRole('button', { name: label.open }));
await page.getByTestId('get-started').waitFor();
await caption(say.empty); await pause(2600);
await click(page.getByRole('button', { name: label.demo }));
await page.locator('.next-action').waitFor({ timeout: 120000 });
await caption(say.home); await pause(1800);
await point(page.locator('.day-pipeline')); await pause(1600);
await click(page.locator('.next-action').getByRole('button').first());
await page.locator('.planning-form-actions .primary').waitFor();
await caption(say.forecast); await pause(1500);
await click(page.locator('.planning-form-actions .primary'));
await page.waitForURL(/\/forecasts\/[^/?]+/, { timeout: 300000 });
await page.waitForLoadState('networkidle').catch(() => {});
await caption(say.dishes); await pause(1800);
await scroll(700); await pause(1800); await scroll(-700); await pause(500);
await click(page.locator('.app-nav').getByRole('button', { name: label.stock, exact: true }));
await page.waitForLoadState('networkidle').catch(() => {});
await caption(say.stock); await pause(1200); await scroll(560); await pause(2200); await scroll(-560);
await click(page.locator('.app-nav').getByRole('button', { name: label.purchase, exact: true }));
await page.locator('.planning-form-actions .primary').waitFor();
await caption(say.purchase); await pause(2200);
await click(page.locator('.planning-form-actions .primary'));
await page.waitForURL(/\/procurement\/[^/?]+/, { timeout: 300000 });
await page.waitForLoadState('networkidle').catch(() => {});
await caption(say.lines); await pause(1500); await scroll(650); await pause(2200);
const decide = page.locator('.decision-bar').getByRole('button', { name: label.confirm });
await caption(say.approve);
await click(decide);
const dialog = page.locator('dialog[open]');
await type(dialog.locator('textarea'), say.reason);
const acknowledge = dialog.locator('input[type=checkbox]');
if (await acknowledge.count()) { await click(acknowledge); await acknowledge.check(); }
await click(dialog.locator('.dialog-actions button').last());
await page.locator('.decision-receipt').waitFor({ timeout: 60000 }).catch(() => {});
await pause(2600);
await click(page.locator('.user-menu-trigger'));
await click(page.locator('.user-menu-panel').getByRole('menuitem', { name: label.profile }));
await page.waitForLoadState('networkidle').catch(() => {});
await caption(say.profile); await pause(2400);
await click(page.locator('.profile-factors>summary'));
await caption(say.factors); await pause(900); await scroll(520); await pause(2600);
await caption('');
await page.evaluate(([title, text, note]) => window.__card(title, text, note), ['predas', say.end, say.demoNote]);
await pause(3500);
} catch (error) {
  console.error('Recording failed at', page.url(), String(error).split('\n')[0]);
  await page.screenshot({ path: path.join(out, 'failure.png') }).catch(() => {});
  await context.close().catch(() => {});
  await browser.close().catch(() => {});
  process.exit(1);
}
const video = page.video();
await context.close();
await browser.close();
const target = path.join(out, `predas-demo-${lang}.webm`);
fs.renameSync(await video.path(), target);
console.log(target);
