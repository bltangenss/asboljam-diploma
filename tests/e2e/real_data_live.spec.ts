import {navigateTo} from './navigation';
import {test,expect,type Page} from '@playwright/test';
import fs from 'node:fs';

// This source is explicitly registered as test_fixture / TEST. It is not business evidence.
// prepare_real_e2e.py creates a fresh empty organization; credentials/artifacts stay in .cache.
const fixturePath='.cache/real-e2e-login.json',directory='.cache/e2e-live';
const kinds=['branches','meals','ingredients','recipes','suppliers','supplier_offers','calendar','daily_sales','inventory_lots'] as const;
type Fixture={email:string;password:string;organization_id:string;branch_id:string;origin:string;target_date:string;source:{source_id:string;mapping_version:string};csvs:Record<typeof kinds[number],string>};
const displayDate=(value:string)=>value.split('-').reverse().join('.');

async function getJson(page:Page,path:string) {
 const response=await page.request.get('/api/v1'+path);expect(response.status()).toBe(200);return response.json();
}
async function completedJob(page:Page,runId:string) {
 let resultId='';
 await expect.poll(async()=>{
  const run=await getJson(page,'/runs/'+runId);
  expect(run.status,'The actual worker must finish the artificial TEST fixture job').not.toBe('failed');
  resultId=run.result_id;return run.status;
 },{timeout:120000,intervals:[500,1000]}).toBe('succeeded');
 expect(Boolean(resultId)).toBe(true);return resultId;
}
async function assertSource(page:Page,fixture:Fixture) {
 const source=page.getByLabel('Дерек көзінің коды',{exact:true});
 await expect(source).toHaveValue(fixture.source.source_id);await expect(source).toHaveAttribute('readonly','');
 await expect(page.getByLabel('Сәйкестендіру нұсқасы',{exact:true})).toHaveValue(fixture.source.mapping_version);
 await expect(page.getByLabel('Сәйкестендіру нұсқасы',{exact:true})).toHaveAttribute('readonly','');
}

test('artificial REAL TEST source imports all schemas and completes actual forecast, approval and export',async({page})=>{
 test.setTimeout(540000);
 expect(fs.existsSync(fixturePath),'Run prepare_real_e2e.py for a fresh isolated fixture first').toBe(true);
 const fixture:Fixture=JSON.parse(fs.readFileSync(fixturePath,'utf8'));
 expect(Boolean(fixture.email&&fixture.password&&fixture.organization_id)).toBe(true);
 expect(Object.keys(fixture.csvs).sort()).toEqual([...kinds].sort());
 expect(fixture.branch_id).toBe('test-branch');expect(fixture.origin).toBe('2026-03-31');expect(fixture.target_date).toBe('2026-04-01');
 fs.mkdirSync(directory,{recursive:true});
 const pageErrors:string[]=[],consoleErrors:string[]=[];
 page.on('pageerror',error=>pageErrors.push(error.message));
 await page.goto('/');
 await page.getByLabel('Электрондық пошта',{exact:true}).fill(fixture.email);
 await page.getByLabel('Құпиясөз',{exact:true}).fill(fixture.password);
 await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Алғашқы бөлімшені қосыңыз',exact:true})).toBeVisible();
 // Initial unauthenticated session probing may return 401; collect console errors after login.
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text())});
 await expect(page.locator('.scenario-banner')).toContainText('TEST · жасанды тексеру мысалы');
 await expect(page.locator('.scenario-banner')).toContainText('REAL');
 await expect(page.locator('body')).not.toContainText('SYNTHETIC');
 await expect(page.locator('body')).not.toContainText('01.01.2026');
 await expect(page.getByLabel('Бөлімше',{exact:true})).toBeDisabled();
 const initial=await getJson(page,'/settings');expect(initial.organization.id).toBe(fixture.organization_id);
 expect(initial.organization.data_policy).toBe('real_only');expect(initial.onboarding.branch_count).toBe(0);
 expect(initial.data_context).toMatchObject({mode:'real_business',data_origin:'REAL',usage_mode:'TEST',branch_id:null,forecast_origin:null,target_date:null,inventory_date:null});

 await page.getByRole('button',{name:'Бөлімшелер CSV файлын импорттау',exact:true}).click();
 await page.getByText('Дерек көзі туралы мәлімет',{exact:true}).click();
 const batches:string[]=[];
 for(const kind of kinds) {
  await test.step('Import artificial TEST '+kind,async()=>{
   await page.getByLabel('Деректер',{exact:true}).selectOption(kind);await assertSource(page,fixture);
   await page.getByLabel('CSV файлын таңдаңыз').setInputFiles({name:'artificial-test-'+kind+'.csv',mimeType:'text/csv',buffer:Buffer.from(fixture.csvs[kind])});
   const previewResponse=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/imports/preview'&&response.request().method()==='POST');
   await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
   const response=await previewResponse;expect(response.status()).toBe(200);
   const request=response.request().postDataJSON();expect(request.source).toEqual(fixture.source);
   const preview=await response.json(),rowCount=kind==='daily_sales'?84:1;
   expect(preview.valid).toBe(true);expect(preview.can_commit).toBe(true);expect(preview.scan_complete).toBe(true);
   expect(preview.errors).toEqual([]);expect(preview.row_count).toBe(rowCount);
   expect(preview.counts).toMatchObject({parsed:rowCount,new:rowCount,unchanged:0,updated:0,conflicting:0});
   expect(preview.source).toMatchObject({...fixture.source,data_origin:'REAL'});
   const commitResponse=page.waitForResponse(result=>new URL(result.url()).pathname===`/api/v1/imports/${preview.id}/commit`&&result.request().method()==='POST');
   const scopedRefresh=page.waitForResponse(result=>{
    const url=new URL(result.url());return url.pathname==='/api/v1/settings'&&url.searchParams.get('branch_id')===fixture.branch_id;
   });
   await page.getByRole('button',{name:'Импорттау',exact:true}).click();
   const committed=await commitResponse;expect(committed.status()).toBe(200);const receipt=await committed.json();
   expect(receipt).toMatchObject({status:'committed',inserted_rows:rowCount,updated_rows:0,unchanged_rows:0,data_origin:'REAL',usage_mode:'TEST'});
   expect((await scopedRefresh).status()).toBe(200);
   await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
   await expect(page.getByLabel('Деректер',{exact:true})).toBeEnabled();await assertSource(page,fixture);
   batches.push(preview.id);
  });
 }
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue(fixture.branch_id);
 const context=(await getJson(page,'/settings?branch_id='+fixture.branch_id)).data_context;
 expect(context).toMatchObject({mode:'real_business',data_origin:'REAL',usage_mode:'TEST',branch_id:fixture.branch_id,forecast_origin:fixture.origin,target_date:fixture.target_date,inventory_date:fixture.target_date,inventory_dates:[fixture.target_date],dates_editable:true});
 expect(context.source).toMatchObject({...fixture.source,branch_id:fixture.branch_id,purpose:'test_fixture'});
 const history=await getJson(page,'/imports?limit=200');
 expect(history.items.filter((item:any)=>item.status==='committed').map((item:any)=>item.id).sort()).toEqual(batches.slice().sort());

 await navigateTo(page,'sales');
 await expect(page.getByLabel('Дейін',{exact:true})).toHaveValue(fixture.origin);
 await page.getByLabel('Бастап',{exact:true}).fill(fixture.origin);
 await expect(page.locator('tbody tr')).toHaveCount(1);await expect(page.locator('tbody')).toContainText(displayDate(fixture.origin));
 const salesExport=await page.getByRole('link',{name:'CSV жүктеу',exact:true}).getAttribute('href');
 expect(new URL(salesExport!,'http://fixture.invalid').searchParams.get('date_to')).toBe(fixture.origin);
 await page.locator('.app-header').getByRole('button',{name:'Қалдықтар',exact:true}).click();
 await expect(page.getByLabel('Қор кесіндісінің күні',{exact:true})).toHaveValue(fixture.target_date);
 await page.getByLabel('Қор кесіндісінің күні',{exact:true}).selectOption(fixture.target_date);
 await page.getByRole('button',{name:'Кесте',exact:true}).click();await expect(page.locator('.stock-counted-task tbody')).toContainText(displayDate(fixture.target_date));
 await expect(page.getByText('Мерзімі жақын',{exact:true})).toBeVisible();
 await expect(page.getByText('Мерзімі өткен',{exact:true})).toHaveCount(0);

 const session=await getJson(page,'/session/me'),headers={Origin:new URL(page.url()).origin,'X-CSRF-Token':session.csrf_token};
 const missingOrigin=await page.request.post('/api/v1/forecasts',{headers,data:{branch_id:fixture.branch_id,model:'seasonal_naive_7'}});
 expect(missingOrigin.status()).toBe(422);expect((await missingOrigin.json()).detail.code).toBe('ORIGIN_REQUIRED');
 await page.locator('.app-header').getByRole('button',{name:'Күн жоспары',exact:true}).click();
 await page.locator('.planning-options>summary').click();await page.getByLabel('Модель',{exact:true}).selectOption('seasonal_naive_7');
 await page.getByLabel('Тарихтың шекті күні',{exact:true}).fill(fixture.origin);
 await expect(page.getByLabel('Болжам күні',{exact:true})).toHaveValue(displayDate(fixture.target_date));
 const forecastQueued=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/forecasts'&&response.request().method()==='POST');
 await page.getByRole('button',{name:'Есептеу',exact:true}).click();
 const forecastResponse=await forecastQueued;expect(forecastResponse.status()).toBe(202);
 expect(forecastResponse.request().postDataJSON()).toMatchObject({branch_id:fixture.branch_id,origin:fixture.origin,model:'seasonal_naive_7'});
 const forecastId=await completedJob(page,(await forecastResponse.json()).run_id);
 await expect(page).toHaveURL(new RegExp('/forecasts/'+forecastId+'$'));
 const forecast=await getJson(page,'/forecasts/'+forecastId);
 expect(forecast).toMatchObject({data_origin:'REAL',target_date:fixture.target_date,input_freshness:'unchanged'});
 expect(forecast.execution_context.usage_mode).toBe('TEST');
 await expect(page.locator('.forecast-result-context')).toContainText('REAL');
 await page.locator('.planning-chart-disclosure>summary').click();await expect(page.getByTestId('forecast-time-chart')).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.locator('.planning-chart-disclosure')).not.toHaveAttribute('open','');

 await page.getByRole('button',{name:'Қалдықтарды тексеру',exact:true}).click();await page.getByRole('button',{name:'Сатып алуды есептеуге',exact:true}).click();
 await page.getByLabel('Бюджет, ₸',{exact:true}).fill('15000');
 const planQueued=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/procurement'&&response.request().method()==='POST');
 await page.getByRole('button',{name:'Есептеу',exact:true}).click();
 const planResponse=await planQueued;expect(planResponse.status()).toBe(202);
 const planId=await completedJob(page,(await planResponse.json()).run_id);
 await expect(page).toHaveURL(new RegExp('/procurement/'+planId+'$'));
 const plan=await getJson(page,'/plans/'+planId);
 expect(plan).toMatchObject({status:'ready',data_origin:'REAL',target_date:fixture.target_date,constraints_valid:true,input_freshness:'unchanged'});
 expect(plan.execution_context.usage_mode).toBe('TEST');
 await expect(page.getByTestId('input-provenance')).toContainText('Есепке кірген деректер өзгермеген.');
 await page.getByRole('button',{name:'Жоспарды бекіту',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.getByLabel('Шешімнің себебі',{exact:true}).fill('Artificial TEST fixture: reviewed inputs, constraints and shortages');
 if(Number(plan.shortage_count)>0)await dialog.getByRole('checkbox',{name:'Тапшылықты қарап, растаймын',exact:true}).check();
 const approvalResponse=page.waitForResponse(response=>new URL(response.url()).pathname===`/api/v1/plans/${planId}/approve`&&response.request().method()==='POST');
 await dialog.getByRole('button',{name:'Жоспарды бекіту',exact:true}).click();
 const approval=await approvalResponse;expect(approval.status()).toBe(200);expect((await approval.json()).status).toBe('approved');
 await expect(dialog).toHaveCount(0);await expect(page.locator('.context-line')).toContainText('Бекітілді');
 await expect(page.locator('.context-line')).toContainText(displayDate(fixture.target_date));

 const downloadEvent=page.waitForEvent('download');await page.getByRole('link',{name:'CSV жүктеу',exact:true}).click();
 const downloaded=await downloadEvent,exportPath=directory+'/artificial-real-test-plan.csv';await downloaded.saveAs(exportPath);
 const exported=fs.readFileSync(exportPath,'utf8');
 for(const value of ['REAL','TEST',fixture.target_date])expect(exported).toContain(value);
 for(const value of ['SYNTHETIC','2026-01-01'])expect(exported).not.toContain(value);
 const audit=await getJson(page,'/audit?limit=200');
 expect(audit.items.filter((item:any)=>item.action==='import.committed'&&batches.includes(item.entity_id))).toHaveLength(9);
 expect(audit.items.filter((item:any)=>item.action==='plan.approved'&&item.entity_id===planId)).toHaveLength(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:directory+'/artificial-real-test-plan-desktop.png',fullPage:true,animations:'disabled'});
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.locator('.sidebar').evaluate(element=>element.getBoundingClientRect().right)).toBeLessThanOrEqual(0.5);
 await expect(page.locator('.scenario-banner')).toContainText('TEST · жасанды тексеру мысалы');
 await expect(page.locator('.context-line')).toContainText(displayDate(fixture.target_date));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:directory+'/artificial-real-test-plan-mobile.png',fullPage:true,animations:'disabled'});
 expect(pageErrors).toEqual([]);expect(consoleErrors).toEqual([]);
});
