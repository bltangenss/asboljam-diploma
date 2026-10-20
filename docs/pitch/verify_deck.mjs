// Reproducible offline/layout/navigation checks. QA PNGs stay in the OS temp directory.
import { chromium, expect } from '@playwright/test';
import { copyFile, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const dir = fileURLToPath(new URL('./', import.meta.url));
const output = await mkdtemp(path.join(tmpdir(), 'predas-deck-qa-'));
const isolated = path.join(output, 'index.html');
await copyFile(path.join(dir, 'deck/index.html'), isolated);
let browser;
try {
  try { browser = await chromium.launch({ channel: 'chrome' }); }
  catch { browser = await chromium.launch(); }
  const context = await browser.newContext({ offline: true, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push(request.url()));
  await page.goto(pathToFileURL(isolated).href);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(img => img.decode()));
  });
  assert.equal(await page.locator('.slide').count(), 10);
  const report = { slides: 10, viewports: [], navigation: [], standaloneOffline: true };
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }]) {
    await page.setViewportSize(viewport);
    for (let slide = 1; slide <= 10; slide++) {
      await page.evaluate(i => { location.hash = String(i); }, slide);
      await expect(page.locator('#counter')).toHaveText(`${slide} / 10`);
      const problems = await page.evaluate(() => {
        const s = document.querySelector('.slide.active'), box = s.getBoundingClientRect();
        const footer = s.querySelector('.footer').getBoundingClientRect();
        const issues = [];
        if (box.left < -1 || box.top < -1 || box.right > innerWidth + 1 || box.bottom > innerHeight - 45)
          issues.push('slide outside viewport');
        for (const el of s.querySelectorAll('h1,h2,h3,p,article,figure,li,.brand,.big-number,.languages,.footer')) {
          const r = el.getBoundingClientRect();
          if (!r.width || !r.height) continue;
          if (r.left < box.left - 1 || r.right > box.right + 1 || r.top < box.top - 1 || r.bottom > box.bottom + 1)
            issues.push(`outside slide: ${el.tagName} ${el.textContent.slice(0,50)}`);
          if (el.closest('.content') && r.bottom > footer.top - 5)
            issues.push(`overlaps footer: ${el.tagName} ${el.textContent.slice(0,50)}`);
          if (el.scrollWidth > el.clientWidth + 2)
            issues.push(`horizontal text overflow: ${el.tagName} ${el.textContent.slice(0,50)}`);
        }
        return issues;
      });
      assert.deepEqual(problems, [], `${viewport.width} slide ${slide}`);
      await page.screenshot({ path: path.join(output, `${viewport.width}-${String(slide).padStart(2,'0')}.png`) });
    }
    report.viewports.push({ ...viewport, slidesPassed: 10 });
  }
  await page.keyboard.press('Home');
  await expect(page.locator('#counter')).toHaveText('1 / 10');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Space');
  await expect(page.locator('#counter')).toHaveText('3 / 10');
  await page.keyboard.press('ArrowLeft');
  await page.locator('.slide.active h2').click();
  await expect(page.locator('#counter')).toHaveText('3 / 10');
  await page.keyboard.press('KeyS');
  await expect(page.locator('#notes')).toBeVisible();
  await expect(page.locator('#notes-text')).toContainText('Predas связывает');
  await page.keyboard.press('KeyS');
  await expect(page.locator('#notes')).toBeHidden();
  await page.keyboard.press('KeyF');
  assert(await page.evaluate(() => Boolean(document.fullscreenElement)));
  await page.evaluate(() => document.exitFullscreen());
  await page.keyboard.press('End');
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('#counter')).toHaveText('10 / 10');
  report.navigation = ['arrows', 'space', 'click', 'home/end', 'bounds', 'speaker notes', 'fullscreen'];

  // All Kazakh letters in a visible sample, plus proof that Chromium uses Onest.
  await page.evaluate(() => {
    const sample = document.createElement('div');
    sample.id = 'glyph-check';
    sample.textContent = 'Ә ә Ғ ғ Қ қ Ң ң Ө ө Ұ ұ Ү ү Һ һ І і — Қазақша · Қазақстан · ₸';
    sample.style.cssText = 'position:fixed;inset:0;background:white;padding:50px;font:48px Onest;z-index:10';
    document.body.append(sample);
  });
  await page.evaluate(() => document.fonts.ready);
  const cdp = await context.newCDPSession(page);
  await cdp.send('DOM.enable');
  await cdp.send('CSS.enable');
  const { root } = await cdp.send('DOM.getDocument');
  const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: '#glyph-check' });
  const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
  assert(fonts.length > 0 && fonts.every(font => font.isCustomFont && /Onest/i.test(font.familyName)));
  report.kazakhGlyphFonts = fonts.map(({ familyName, glyphCount }) => ({ familyName, glyphCount }));
  await page.screenshot({ path: path.join(output, 'kazakh-glyphs.png') });
  await page.locator('#glyph-check').evaluate(el => el.remove());
  await page.keyboard.press('KeyS');
  await page.emulateMedia({ media: 'print' });
  assert.equal(await page.locator('.slide:visible').count(), 10);
  const printProblems = await page.locator('.slide').evaluateAll(slides => slides.flatMap((slide, i) => {
    const issues = [];
    if (getComputedStyle(slide).flexDirection !== 'column') issues.push(`slide ${i + 1}: print flow`);
    const box = slide.getBoundingClientRect(), footer = slide.querySelector('.footer').getBoundingClientRect();
    for (const el of slide.querySelectorAll('.content h3,.content p,.content figure,.content li')) {
      const r = el.getBoundingClientRect();
      if (r.left < box.left - 1 || r.right > box.right + 1 || r.bottom > footer.top - 5)
        issues.push(`slide ${i + 1}: print overflow`);
    }
    return issues;
  }));
  assert.deepEqual(printProblems, []);
  await expect(page.locator('#notes')).toBeHidden();
  await expect(page.locator('#controls')).toBeHidden();
  assert.deepEqual(errors, []);
  assert(requests.every(url => url === pathToFileURL(isolated).href || url.startsWith('data:')),
    'Standalone HTML requested an external file');
  report.pageErrors = errors;
  report.print = '10 visible slides, notes and controls hidden';
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ ...report, visualReviewDirectory: output }, null, 2));
} finally { await browser?.close(); }
