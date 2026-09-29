import {test,expect,type Page} from '@playwright/test';
import fs from 'node:fs';
const login=JSON.parse(fs.readFileSync('.cache/e2e-login.json','utf8'));
const artifactDirectory='.cache/e2e-live';
fs.mkdirSync(artifactDirectory,{recursive:true});

async function expectClosedMobileDrawer(page:Page) {
 const sidebar=page.locator('.sidebar');
 await expect(sidebar).not.toHaveClass(/\bopen\b/);
 await expect(page.getByRole('button',{name:'Close navigation',exact:true})).toHaveCount(0);
 // Visibility alone does not detect an offscreen element or an unfinished CSS transition.
 await expect.poll(()=>sidebar.evaluate(element=>element.getBoundingClientRect().right)).toBeLessThanOrEqual(0.5);
}

async function checkMobileDrawer(page:Page,width:number) {
 await expect(page.locator('.bottom-nav')).toBeVisible();
 await expectClosedMobileDrawer(page);
 await page.getByRole('button',{name:'Navigation',exact:true}).click();
 await expect(page.locator('.sidebar')).toHaveClass(/\bopen\b/);
 await expect.poll(()=>page.locator('.sidebar').evaluate(element=>Math.abs(element.getBoundingClientRect().left))).toBeLessThanOrEqual(0.5);
 const overlay=page.getByRole('button',{name:'Close navigation',exact:true});
 await expect(overlay).toBeVisible();
 // Click the exposed backdrop, not the sidebar layered above its centre.
 await overlay.click({position:{x:width-12,y:90}});
 await expectClosedMobileDrawer(page);
 await page.locator('.bottom-nav').getByRole('button',{name:'Тағы',exact:true}).click();
 await expect(page.locator('.sidebar')).toHaveClass(/\bopen\b/);
 await page.locator('.sidebar').getByRole('button',{name:'Шолу',exact:true}).click();
 await expectClosedMobileDrawer(page);
 await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы',exact:true})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
}

/** Allow decision/role scenarios to run alone against seeded sales and a real worker. */
async function ensureForecast(page:Page,headers:Record<string,string>,branch='1') {
 const listed=await page.request.get('/api/v1/forecasts?branch_id='+encodeURIComponent(branch));
 expect(listed.status()).toBe(200);
 const forecasts=await listed.json();
 if(forecasts.items.length)return forecasts.items[0];
 const queued=await page.request.post('/api/v1/forecasts',{headers,data:{branch_id:branch,origin:'2025-12-31',model:'seasonal_naive_7'}});
 expect(queued.status()).toBe(202);
 const run=await queued.json();let forecastId='';
 await expect.poll(async()=>{
  const response=await page.request.get('/api/v1/runs/'+run.run_id);expect(response.status()).toBe(200);
  const result=await response.json();forecastId=result.result_id;return result.status;
 },{timeout:120000}).toBe('succeeded');
 const completed=await page.request.get('/api/v1/forecasts/'+forecastId);expect(completed.status()).toBe(200);
 return completed.json();
}
test('login → CSV validation/commit → sales → forecast → procurement → approval → export',async({page})=>{
 // Two real worker jobs each allow 120 seconds; include UI and screenshot overhead.
 test.setTimeout(360000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы'})).toBeVisible();
 await expect(page.locator('.metric-value').first()).not.toHaveText('—');
 await page.locator('.sidebar').getByRole('button',{name:'Дерек импорттау',exact:true}).click();
 await page.getByLabel('CSV файлды таңдаңыз').setInputFiles({name:'invalid.csv',mimeType:'text/csv',buffer:Buffer.from('date,branch_id,meal_id,units_sold\nwrong,1,1,-1\n')});
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();await expect(page.getByText('Қате жолдар бар: импорт орындалмайды')).toBeVisible();await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeDisabled();
 const keys=Object.keys(login.sale);const csv=keys.join(',')+'\n'+keys.map(k=>login.sale[k]).join(',')+'\n';
 await page.getByLabel('CSV файлды таңдаңыз').setInputFiles({name:'sales.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeEnabled();await page.getByRole('button',{name:'Импорттау',exact:true}).click();await expect(page.getByText('Деректер транзакциямен импортталды')).toBeVisible();
 await page.locator('.sidebar').getByRole('button',{name:'Сатылым',exact:true}).click();await expect(page.locator('tbody tr')).toHaveCount(50);
 await page.getByLabel('Тағам',{exact:true}).selectOption('1');await expect(page.locator('tbody tr')).toHaveCount(28);
 await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();await page.getByRole('button',{name:'Есептеу',exact:true}).click();await expect(page).toHaveURL(/\/forecasts\/[a-f0-9]+$/,{timeout:120000});await expect(page.locator('.alert.info')).toContainText('Аралық есептелмеген');await expect(page.getByTestId('forecast-interval')).toHaveCount(0);
 await page.locator('.panel-heading').getByRole('button',{name:'Сатып алу',exact:true}).click();await page.getByLabel('Бюджет, ₸').fill('150000');await page.getByRole('button',{name:'Есептеу',exact:true}).click();await expect(page).toHaveURL(/\/procurement\/[a-f0-9]+$/,{timeout:120000});
 await expect(page.locator('tbody tr')).toHaveCount(10);await expect(page.locator('tbody td').filter({hasText:'NaN'})).toHaveCount(0);
 await page.getByRole('button',{name:'Жоспарды бекіту',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByLabel('Шешімнің себебі').fill('E2E: reviewed synthetic daily plan');const ack=page.getByLabel('Тапшылықты қарап, растаймын');if(await ack.count())await ack.check();await page.getByRole('dialog').getByRole('button',{name:'Жоспарды бекіту',exact:true}).click();await expect(page.locator('.context-line').getByText('Бекітілді',{exact:true})).toBeVisible();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'CSV жүктеу'}).click();const download=await downloadPromise;expect(download.suggestedFilename()).toMatch(/\.csv$/);await download.saveAs(artifactDirectory+'/approved-plan.csv');
 await page.screenshot({path:artifactDirectory+'/procurement-desktop.png',fullPage:true,animations:'disabled'});await page.locator('.sidebar').getByRole('button',{name:'Шолу',exact:true}).click();await expect(page.locator('.metric-value').first()).not.toHaveText('—');await page.screenshot({path:artifactDirectory+'/dashboard-desktop.png',fullPage:true,animations:'disabled'});
 await page.setViewportSize({width:390,height:844});await checkMobileDrawer(page,390);await page.screenshot({path:artifactDirectory+'/dashboard-mobile.png',fullPage:true,animations:'disabled'});
 await page.setViewportSize({width:360,height:800});await checkMobileDrawer(page,360);await page.screenshot({path:artifactDirectory+'/dashboard-mobile-360.png',fullPage:true,animations:'disabled'});
 await page.locator('.bottom-nav').getByRole('button',{name:'Қойма',exact:true}).click();await expect(page.locator('tbody tr')).toHaveCount(20);
 await page.context().setOffline(true);await expect(page.getByText('Байланыс жоқ. Өзгерістерді сақтау мүмкін емес.',{exact:true}).first()).toBeVisible();await page.context().setOffline(false);
 await page.setViewportSize({width:1440,height:1100});await page.getByTitle('Шығу',{exact:true}).click();await expect(page.getByRole('button',{name:'Жүйеге кіру',exact:true})).toBeVisible();expect(errors).toEqual([]);
});

test('branch context, Russian labels, empty result and recoverable network failure',async({page})=>{
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.locator('.metric-value').first()).not.toHaveText('—');const first=await page.locator('.metric-value').first().innerText();
 await page.getByLabel('Бөлімше',{exact:true}).selectOption('2');await expect(page.locator('.context-line')).toContainText('Бөлімше 2');await expect(page.locator('.metric-value').first()).not.toHaveText('—');await expect(page.locator('.metric-value').first()).not.toHaveText(first);await expect(page.locator('.plan-empty')).toBeVisible();
 await page.getByRole('button',{name:'ҚАЗ',exact:true}).click();await expect(page.getByRole('heading',{name:'Обзор работы филиала'})).toBeVisible();await page.getByRole('button',{name:'РУС',exact:true}).click();
 await page.locator('.sidebar').getByRole('button',{name:'Сатылым',exact:true}).click();await page.getByLabel('Бастап',{exact:true}).fill('2020-01-01');await page.getByLabel('Дейін',{exact:true}).fill('2020-01-02');await expect(page.getByRole('heading',{name:'Бұл жерде әзірше дерек жоқ'})).toBeVisible();
 await page.route('**/api/v1/dashboard*',route=>route.abort('failed'));await page.locator('.sidebar').getByRole('button',{name:'Шолу',exact:true}).click();await expect(page.getByRole('alert')).toContainText('Сервермен байланыс жоқ');await page.unroute('**/api/v1/dashboard*');await page.getByRole('button',{name:'Қайта жүктеу',exact:true}).click();await expect(page.locator('.metric-value').first()).not.toHaveText('—');
 for(const width of [1280,768,390,360]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();}
});

test('stale plan approval forces review and audit records the winning decision',async({page})=>{
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы'})).toBeVisible();
 const session=await (await page.request.get('/api/v1/session/me')).json();const headers={'Origin':'http://127.0.0.1:3000','X-CSRF-Token':session.csrf_token};
 const forecast=await ensureForecast(page,headers);
 const queued=await page.request.post('/api/v1/procurement',{headers,data:{branch_id:'1',forecast_id:forecast.id,budget:'0',strategy:'point'}});expect(queued.status()).toBe(202);const run=await queued.json();let planId='';
 await expect.poll(async()=>{const r=await (await page.request.get('/api/v1/runs/'+run.run_id)).json();planId=r.result_id;return r.status},{timeout:90000}).toBe('succeeded');
 await page.goto('/procurement/'+planId);await expect(page.getByRole('button',{name:'Жоспарды бекіту',exact:true})).toBeVisible();const plan=await (await page.request.get('/api/v1/plans/'+planId)).json();
 const approved=await page.request.post('/api/v1/plans/'+planId+'/approve',{headers:{...headers,'Idempotency-Key':'e2e-winning-'+planId},data:{expected_version:plan.version,reason:'E2E concurrent reviewer confirmed shortage',acknowledge_shortage:true}});expect(approved.status()).toBe(200);
 await page.getByRole('button',{name:'Жоспарды бекіту',exact:true}).click();await page.getByLabel('Шешімнің себебі').fill('E2E stale reviewer');await page.getByLabel('Тапшылықты қарап, растаймын').check();await page.getByRole('dialog').getByRole('button',{name:'Жоспарды бекіту',exact:true}).click();await expect(page.getByRole('alert').first()).toContainText('Жоспар жаңартылған');
 await page.getByRole('button',{name:'Қайта жүктеу',exact:true}).click();await expect(page.locator('.context-line')).toContainText('Бекітілді');
 await page.locator('.sidebar').getByRole('button',{name:'Аудит журналы',exact:true}).click();await expect(page.locator('tbody')).toContainText('E2E concurrent reviewer confirmed shortage');
});

test('quantile chart uses observed history and exposes the measured model card',async({page})=>{
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();
 await page.getByLabel('Модель',{exact:true}).selectOption('hist_gradient_boosting');await page.getByRole('button',{name:'Есептеу',exact:true}).click();await expect(page).toHaveURL(/\/forecasts\/[a-f0-9]+$/,{timeout:120000});
 await expect(page.getByTestId('forecast-time-chart')).toBeVisible();await expect(page.locator('[data-series="observed"]')).toHaveCount(28);await expect(page.getByTestId('forecast-interval')).toBeVisible();await expect(page.getByTestId('forecast-target-point')).toHaveAttribute('data-date','2026-01-01');
 await expect(page.locator('.metrics-panel tbody tr')).toHaveCount(3);await expect(page.locator('.metrics-panel tbody')).toContainText('336');
 await page.getByLabel('Графиктегі тағам',{exact:true}).selectOption('2');await expect(page.locator('[data-series="observed"]')).toHaveCount(28);await page.screenshot({path:artifactDirectory+'/forecast-quantiles.png',fullPage:true,animations:'disabled'});
 await page.setViewportSize({width:360,height:800});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});

test('admin manages access and analyst reads saved results without write permissions',async({page})=>{
 test.setTimeout(360000);
 const email='e2e-analyst-'+Date.now()+'@asboljam.local',password='Test-only-'+crypto.randomUUID();
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы'})).toBeVisible();
 const origin=new URL(page.url()).origin;
 const adminSession=await(await page.request.get('/api/v1/session/me')).json();
 const adminHeaders={Origin:origin,'X-CSRF-Token':adminSession.csrf_token};
 const forecast=await ensureForecast(page,adminHeaders);
 const queued=await page.request.post('/api/v1/procurement',{headers:adminHeaders,data:{branch_id:'1',forecast_id:forecast.id,budget:'150000',strategy:'point'}});
 expect(queued.status()).toBe(202);const run=await queued.json();let planId='';
 await expect.poll(async()=>{
  const response=await page.request.get('/api/v1/runs/'+run.run_id);expect(response.status()).toBe(200);
  const result=await response.json();planId=result.result_id;return result.status;
 },{timeout:120000}).toBe('succeeded');
 await page.locator('.sidebar').getByRole('button',{name:'Баптаулар',exact:true}).click();
 const userAdmin=page.locator('.user-admin').filter({has:page.getByRole('heading',{name:'Пайдаланушылар мен рұқсаттар',exact:true})});
 await userAdmin.getByRole('button',{name:'Пайдаланушы қосу',exact:true}).click();
 await userAdmin.getByLabel('Электрондық пошта',{exact:true}).fill(email);await userAdmin.getByLabel('Құпиясөз',{exact:true}).fill(password);await userAdmin.getByLabel('Role',{exact:true}).selectOption('analyst');await userAdmin.getByLabel('Demo_Canteen_A',{exact:true}).check();await userAdmin.getByRole('button',{name:'Сақтау',exact:true}).click();await expect(userAdmin).toContainText('Өзгеріс сақталды және аудитке жазылды.');await expect(userAdmin.locator('tbody')).toContainText(email);
 await page.getByTitle('Шығу',{exact:true}).click();await page.getByLabel('Электрондық пошта').fill(email);await page.getByLabel('Құпиясөз').fill(password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();await expect(page.getByLabel('Бөлімше').locator('option')).toHaveCount(1);expect((await page.request.get('/api/v1/dashboard?branch_id=2')).status()).toBe(403);
 await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();await expect(page.getByRole('button',{name:'Есептеу',exact:true})).toBeDisabled();
 expect((await page.request.get('/api/v1/forecasts/'+forecast.id)).status()).toBe(200);
 await page.locator('.sidebar').getByRole('button',{name:'Сатып алу',exact:true}).click();await expect(page.getByRole('button',{name:'Есептеу',exact:true})).toBeDisabled();
 await page.goto('/procurement/'+planId);await expect(page.getByRole('button',{name:'Жоспарды бекіту',exact:true})).toBeDisabled();await expect(page.getByText('Бұл әрекетке рұқсатыңыз жоқ.',{exact:true})).toBeVisible();
 const stored=await page.request.get('/api/v1/plans/'+planId);expect(stored.status()).toBe(200);const plan=await stored.json();
 const session=await(await page.request.get('/api/v1/session/me')).json(),headers={Origin:origin,'X-CSRF-Token':session.csrf_token};
 expect((await page.request.post('/api/v1/forecasts',{headers,data:{branch_id:'1',origin:'2025-12-31',model:'seasonal_naive_7'}})).status()).toBe(403);
 expect((await page.request.post('/api/v1/procurement',{headers,data:{branch_id:'1',forecast_id:forecast.id,budget:'150000',strategy:'point'}})).status()).toBe(403);
 expect((await page.request.post('/api/v1/imports/preview',{headers,data:{kind:'daily_sales',csv_text:'date\n2026-01-01\n'}})).status()).toBe(403);
 const response=await page.request.post('/api/v1/plans/'+planId+'/approve',{headers:{...headers,'Idempotency-Key':'forbidden-'+planId},data:{expected_version:plan.version,reason:'E2E unauthorized approval',acknowledge_shortage:true}});expect(response.status()).toBe(403);
});

test('real password change revokes existing sessions and requires the new password',async({page,playwright})=>{
 const email='e2e-password-'+crypto.randomUUID()+'@asboljam.local';
 const original='Test-only-'+crypto.randomUUID(),replacement='Test-only-new-'+crypto.randomUUID();
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы'})).toBeVisible();
 const origin=new URL(page.url()).origin;
 const adminSession=await(await page.request.get('/api/v1/session/me')).json();
 const created=await page.request.post('/api/v1/users',{headers:{Origin:origin,'X-CSRF-Token':adminSession.csrf_token},data:{email,password:original,role:'manager',branch_ids:['1']}});
 expect(created.status()).toBe(201);
 const existing=await playwright.request.newContext({baseURL:origin});
 try {
  const existingLogin=await existing.post('/api/v1/session/login',{headers:{Origin:origin},data:{email,password:original}});expect(existingLogin.status()).toBe(200);
  expect((await existing.get('/api/v1/session/me')).status()).toBe(200);
  const nativeLogin=await existing.post('/api/v1/auth/token',{data:{email,password:original}});expect(nativeLogin.status()).toBe(200);const native=await nativeLogin.json();
  await page.getByTitle('Шығу',{exact:true}).click();await page.getByLabel('Электрондық пошта').fill(email);await page.getByLabel('Құпиясөз').fill(original);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
  await page.locator('.sidebar').getByRole('button',{name:'Баптаулар',exact:true}).click();
  await page.getByLabel('Қазіргі құпиясөз',{exact:true}).fill(original);await page.getByLabel('Жаңа құпиясөз',{exact:true}).fill(replacement);await page.getByLabel('Жаңа құпиясөзді қайталаңыз',{exact:true}).fill(replacement);
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
  await expect(page).toHaveURL(/\/login$/);await expect(page.getByRole('status')).toHaveText('Құпиясөз өзгертілді. Қайта кіріңіз.');
  expect((await existing.get('/api/v1/session/me')).status()).toBe(401);
  expect((await existing.get('/api/v1/session/me',{headers:{Authorization:'Bearer '+native.access_token}})).status()).toBe(401);
  expect((await existing.post('/api/v1/auth/refresh',{data:{refresh_token:native.refresh_token}})).status()).toBe(401);
  await page.getByLabel('Электрондық пошта').fill(email);await page.getByLabel('Құпиясөз').fill(original);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('Кіру деректерін тексеріңіз');
  await page.getByLabel('Құпиясөз').fill(replacement);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы'})).toBeVisible();
  const restored=await page.request.get('/api/v1/session/me');expect(restored.status()).toBe(200);expect((await restored.json()).user.email).toBe(email);
 } finally {await existing.dispose()}
});
