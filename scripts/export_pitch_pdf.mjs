import { chromium } from '@playwright/test';
import { readFile, stat, writeFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { parseArgs } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const deck = path.join(root, 'docs/pitch/deck/index.html');
const pdf = path.join(root, 'docs/pitch/predas-pitch.pdf');
const { values } = parseArgs({ options: { 'refresh-assets': { type: 'boolean' } } });

// Explicitly refresh the embedded copies after recapturing screenshots or replacing fonts.
// The delivered HTML also retains relative font URLs as fallbacks, and works by itself.
if (values['refresh-assets']) {
  let html = await readFile(deck, 'utf8');
  html = await replaceAsync(html, /data-asset="([a-z-]+\.png)" src="[^"]*"/g, async (_, name) =>
    `data-asset="${name}" src="data:image/png;base64,${(await readFile(path.join(root, 'docs/pitch/assets', name))).toString('base64')}"`);
  html = await replaceAsync(html, /\/\* embed:([a-z-]+\.woff2) \*\/ url\("[^"]*"\)/g, async (_, name) =>
    `/* embed:${name} */ url("data:font/woff2;base64,${(await readFile(path.join(root, 'docs/pitch/deck/fonts', name))).toString('base64')}")`);
  const license = await readFile(path.join(root, 'docs/pitch/deck/fonts/LICENSE'), 'utf8');
  html = html.replace(/<!-- ONEST-LICENSE-START[\s\S]*?ONEST-LICENSE-END -->/,
    `<!-- ONEST-LICENSE-START\n${license}\nONEST-LICENSE-END -->`);
  await writeFile(deck, html);
}
async function replaceAsync(text, regex, replacer) {
  const matches = [...text.matchAll(regex)], replacements = await Promise.all(matches.map(m => replacer(...m)));
  let index = 0;
  return text.replace(regex, () => replacements[index++]);
}
let browser;
try {
  try { browser = await chromium.launch({ channel: 'chrome', headless: true }); }
  catch { browser = await chromium.launch({ headless: true }); }
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  const failures = [];
  page.on('pageerror', error => failures.push(error.message));
  // Rendering may only read local/data URLs. Export never needs the internet.
  await page.route(/^https?:\/\//, route => { failures.push('External resource requested'); return route.abort(); });
  await page.goto(pathToFileURL(deck).href);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(img => img.decode()));
  });
  if (await page.locator('.slide').count() !== 10) throw new Error('Expected ten slides');
  await page.emulateMedia({ media: 'print' });
  await page.pdf({ path: pdf, width: '1600px', height: '900px', printBackground: true,
    preferCSSPageSize: true, margin: { top: 0, bottom: 0, left: 0, right: 0 }, displayHeaderFooter: false });
  if (failures.length) throw new Error(failures.join('; '));
  const size = (await stat(pdf)).size;
  if (size > 10 * 1024 * 1024) throw new Error('PDF exceeds 10 MB');
  console.log(`Exported docs/pitch/predas-pitch.pdf (${(size / 1024 / 1024).toFixed(2)} MB).`);
} finally { await browser?.close(); }
