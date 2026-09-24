import {test,expect} from '@playwright/test';
import fs from 'node:fs';
const login=JSON.parse(fs.readFileSync('.cache/e2e-login.json','utf8'));
test('login → CSV validation/commit → sales → forecast → procurement → approval → export',async({page})=>{
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
 const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'CSV жүктеу'}).click();const download=await downloadPromise;expect(download.suggestedFilename()).toMatch(/\.csv$/);await download.saveAs('artifacts/e2e-approved-plan.csv');
 await page.screenshot({path:'artifacts/screenshots/procurement-desktop.png',fullPage:true});await page.locator('.sidebar').getByRole('button',{name:'Шолу',exact:true}).click();await expect(page.locator('.metric-value').first()).not.toHaveText('—');await page.screenshot({path:'artifacts/screenshots/dashboard-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await expect(page.locator('.bottom-nav')).toBeVisible();await page.screenshot({path:'artifacts/screenshots/dashboard-mobile.png',fullPage:true});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.setViewportSize({width:360,height:800});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
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
 const forecasts=await (await page.request.get('/api/v1/forecasts?branch_id=1')).json();expect(forecasts.items.length).toBeGreaterThan(0);
 const queued=await page.request.post('/api/v1/procurement',{headers,data:{branch_id:'1',forecast_id:forecasts.items[0].id,budget:'0',strategy:'point'}});expect(queued.status()).toBe(202);const run=await queued.json();let planId='';
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
 await page.getByLabel('Графиктегі тағам',{exact:true}).selectOption('2');await expect(page.locator('[data-series="observed"]')).toHaveCount(28);await page.screenshot({path:'artifacts/screenshots/forecast-quantiles.png',fullPage:true});
 await page.setViewportSize({width:360,height:800});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});

test('admin manages access and analyst cannot approve or read another branch',async({page})=>{
 const email='e2e-analyst-'+Date.now()+'@asboljam.local',password='Test-only-'+crypto.randomUUID();
 await page.goto('/');await page.getByLabel('Электрондық пошта').fill(login.email);await page.getByLabel('Құпиясөз').fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();await page.locator('.sidebar').getByRole('button',{name:'Баптаулар',exact:true}).click();await page.getByRole('button',{name:'Пайдаланушы қосу',exact:true}).click();
 await page.getByLabel('Электрондық пошта',{exact:true}).fill(email);await page.getByLabel('Құпиясөз',{exact:true}).fill(password);await page.getByLabel('Role',{exact:true}).selectOption('analyst');await page.getByLabel('Demo_Canteen_A',{exact:true}).check();await page.getByRole('button',{name:'Сақтау',exact:true}).click();await expect(page.locator('.user-admin')).toContainText('Өзгеріс сақталды және аудитке жазылды.');await expect(page.locator('.user-admin tbody')).toContainText(email);
 await page.getByTitle('Шығу',{exact:true}).click();await page.getByLabel('Электрондық пошта').fill(email);await page.getByLabel('Құпиясөз').fill(password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();await expect(page.getByLabel('Бөлімше').locator('option')).toHaveCount(1);expect((await page.request.get('/api/v1/dashboard?branch_id=2')).status()).toBe(403);
 await page.locator('.sidebar').getByRole('button',{name:'Сатып алу',exact:true}).click();await expect(page.getByRole('button',{name:'Есептеу',exact:true})).toBeEnabled();await page.getByRole('button',{name:'Есептеу',exact:true}).click();await expect(page).toHaveURL(/\/procurement\/[a-f0-9]+$/,{timeout:90000});await expect(page.getByRole('button',{name:'Жоспарды бекіту',exact:true})).toBeDisabled();await expect(page.getByText('Бұл әрекетке рұқсатыңыз жоқ.',{exact:true})).toBeVisible();
 const planId=page.url().split('/').pop(),session=await(await page.request.get('/api/v1/session/me')).json();const response=await page.request.post('/api/v1/plans/'+planId+'/approve',{headers:{Origin:'http://127.0.0.1:3000','X-CSRF-Token':session.csrf_token,'Idempotency-Key':'forbidden-'+planId},data:{expected_version:1,reason:'E2E unauthorized approval',acknowledge_shortage:true}});expect(response.status()).toBe(403);
});
