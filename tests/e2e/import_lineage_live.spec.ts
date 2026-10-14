import {test,expect,type Page} from '@playwright/test';
import fs from 'node:fs';

// Only the dedicated, fully synthetic fixture is changed. Credentials stay in ignored .cache.
const fixture=JSON.parse(fs.readFileSync('.cache/e2e-login.json','utf8')).imports;
const directory='.cache/e2e-live';
fs.mkdirSync(directory,{recursive:true});
const fields=['date','branch_id','meal_id','units_sold','available_portions','stockout_flag','is_open','promo','price_kzt','data_origin'];
type Sale=Record<string,string|number>;
function csvFor(sale:Sale) {
 const quote=(value:string|number)=>'"'+String(value).replaceAll('"','""')+'"';
 return fields.join(',')+'\n'+fields.map(field=>quote(sale[field])).join(',')+'\n';
}
function savedResult(result:Record<string,unknown>) {
 // Freshness is derived from today's stored rows; the saved calculation must be immutable.
 const {input_freshness,...saved}=result;return saved;
}
async function getJson(page:Page,path:string) {
 const response=await page.request.get('/api/v1'+path);expect(response.status()).toBe(200);return response.json();
}
async function exportPlan(page:Page,id:string) {
 const response=await page.request.get('/api/v1/plans/'+id+'/export');expect(response.status()).toBe(200);return response.body();
}
async function calculate(page:Page,headers:Record<string,string>,path:string,payload:Record<string,unknown>,resultPath:string) {
 const response=await page.request.post('/api/v1'+path,{headers,data:payload});expect(response.status()).toBe(202);
 const queued=await response.json();let resultId='';
 await expect.poll(async()=>{
  const run=await getJson(page,'/runs/'+queued.run_id);
  expect(run.status,'The actual worker must finish this job successfully').not.toBe('failed');
  resultId=run.result_id;return run.status;
 },{timeout:120000,intervals:[250,500,1000]}).toBe('succeeded');
 return getJson(page,resultPath+'/'+resultId);
}
async function forecastAndPlan(page:Page,headers:Record<string,string>) {
 const forecast=await calculate(page,headers,'/forecasts',{branch_id:'1',origin:'2025-12-31',model:'seasonal_naive_7'},'/forecasts');
 const plan=await calculate(page,headers,'/procurement',{branch_id:'1',forecast_id:forecast.id,budget:'150000',strategy:'point'},'/plans');
 expect(forecast.input_freshness).toBe('unchanged');expect(plan.input_freshness).toBe('unchanged');
 expect(plan.status).toBe('ready');return {forecast,plan};
}
async function uploadAndCommit(page:Page,sale:Sale,mode:'append'|'correction',reason='') {
 await page.goto('/imports');
 await expect(page.getByLabel('Деректер',{exact:true})).toHaveValue('daily_sales');
 await page.getByLabel('Импорт режимі',{exact:true}).selectOption(mode);
 if(mode==='correction')await page.getByLabel('Түзету себебі',{exact:true}).fill(reason);
 await page.getByLabel('CSV файлын таңдаңыз').setInputFiles({name:'synthetic-lineage-sales.csv',mimeType:'text/csv',buffer:Buffer.from(csvFor(sale))});
 const previewRequest=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/imports/preview'&&response.request().method()==='POST');
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
 const previewResponse=await previewRequest;expect(previewResponse.status()).toBe(200);const preview=await previewResponse.json();
 expect(preview.valid).toBe(true);expect(preview.scan_complete).toBe(true);
 expect(preview.counts.parsed).toBe(1);expect(preview.counts.new).toBe(0);
 if(mode==='correction') {
  expect(preview.counts.updated).toBe(1);expect(preview.changes[0].operation).toBe('update');
  const result=page.getByRole('region',{name:'Импорт нәтижесі',exact:true});
  await expect(result.getByRole('columnheader',{name:'Бұрын',exact:true})).toBeVisible();
  await expect(result.getByRole('row').filter({has:page.getByRole('cell',{name:/^Сатылған порция\s*units_sold$/})}).getByRole('cell')).toHaveText([/^Сатылған порция\s*units_sold$/,String(preview.changes[0].before.units_sold),String(sale.units_sold)]);
  await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeDisabled();
  await page.getByRole('checkbox',{name:'Өзгерістер үлгісін, санын және түзету себебін тексердім.',exact:true}).check();
 } else {
  expect(preview.counts.unchanged).toBe(1);expect(preview.counts.updated).toBe(0);
  await expect(page.getByText('Бұл жолдар бұрын сақталған. Қайта импорттау деректерді көбейтпейді.',{exact:true})).toBeVisible();
 }
 const committedRequest=page.waitForResponse(response=>new URL(response.url()).pathname===`/api/v1/imports/${preview.id}/commit`&&response.request().method()==='POST');
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 const committedResponse=await committedRequest;expect(committedResponse.status()).toBe(200);const receipt=await committedResponse.json();
 expect(receipt.status).toBe('committed');expect(receipt.inserted_rows).toBe(0);
 expect(receipt.updated_rows).toBe(mode==='correction'?1:0);expect(receipt.unchanged_rows).toBe(mode==='append'?1:0);
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 return {preview,receipt};
}

test('real correction invalidates ready inputs, preserves approved history and links recalculated sources',async({page})=>{
 test.setTimeout(540000);
 expect(Boolean(fixture?.email&&fixture?.password&&fixture?.organization_id&&fixture?.sale)).toBe(true);
 const original:Sale={...fixture.sale};
 expect(original.date).toBe('2025-12-31');expect(String(original.branch_id)).toBe('1');expect(original.data_origin).toBe('SYNTHETIC');
 expect(Number(original.is_open)).toBe(1);expect(Number(original.available_portions)).toBeGreaterThan(0);
 const originalUnits=Number(original.units_sold),available=Number(original.available_portions);
 const corrected:Sale={...original,units_sold:originalUnits+(originalUnits<available?1:-1)};
 expect(Number(corrected.units_sold)).toBeGreaterThanOrEqual(0);expect(Number(corrected.units_sold)).toBeLessThanOrEqual(available);
 const pageErrors:string[]=[];page.on('pageerror',error=>pageErrors.push(error.message));
 await page.goto('/');await page.getByLabel('Электрондық пошта',{exact:true}).fill(fixture.email);
 await page.getByLabel('Құпиясөз',{exact:true}).fill(fixture.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Бүгін',exact:true})).toBeVisible();
 const session=await getJson(page,'/session/me');expect(session.user.organization_id).toBe(fixture.organization_id);
 const headers={Origin:new URL(page.url()).origin,'X-CSRF-Token':session.csrf_token};
 const salesPath='/sales?'+new URLSearchParams({branch_id:'1',date_from:String(original.date),date_to:String(original.date),meal_id:String(original.meal_id)});
 const salesBefore=await getJson(page,salesPath);expect(salesBefore.total).toBe(1);expect(salesBefore.items[0].units_sold).toBe(originalUnits);

 const old=await forecastAndPlan(page,headers),oldExport=await exportPlan(page,old.plan.id);
 await page.goto('/procurement/'+old.plan.id);
 await expect(page.getByTestId('input-provenance')).toContainText('Есепке кірген деректер өзгермеген.');
 await expect(page.getByRole('button',{name:'Жоспарды бекіту',exact:true})).toBeEnabled();
 const first=await uploadAndCommit(page,corrected,'correction','Synthetic live test: correct observed portion count');
 const salesAfter=await getJson(page,salesPath);expect(salesAfter.total).toBe(1);expect(salesAfter.items[0].units_sold).toBe(corrected.units_sold);
 const repeated=await uploadAndCommit(page,corrected,'append');
 expect((await getJson(page,salesPath)).items).toEqual(salesAfter.items);
 await page.reload();await page.getByRole('button',{name:'Импортты ашу '+repeated.preview.id,exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toHaveCount(0);

 await page.goto('/procurement/'+old.plan.id);
 await expect(page.getByTestId('input-provenance').getByRole('alert')).toContainText('Бастапқы деректер өзгерді.');
 await expect(page.getByRole('button',{name:'Жоспарды бекіту',exact:true})).toBeDisabled();
 const denied=await page.request.post('/api/v1/plans/'+old.plan.id+'/approve',{headers:{...headers,'Idempotency-Key':'stale-inputs-'+old.plan.id},data:{expected_version:old.plan.version,reason:'Synthetic live test: stale input rejection',acknowledge_shortage:true}});
 expect(denied.status()).toBe(409);expect((await denied.json()).detail.code).toBe('INPUTS_CHANGED');
 const oldForecastAfter=await getJson(page,'/forecasts/'+old.forecast.id),oldPlanAfter=await getJson(page,'/plans/'+old.plan.id);
 expect(oldForecastAfter.input_freshness).toBe('changed');expect(oldPlanAfter.input_freshness).toBe('changed');
 expect(savedResult(oldForecastAfter)).toEqual(savedResult(old.forecast));expect(savedResult(oldPlanAfter)).toEqual(savedResult(old.plan));
 expect((await exportPlan(page,old.plan.id)).equals(oldExport)).toBe(true);

 const fresh=await forecastAndPlan(page,headers);
 const sourceBatches=fresh.plan.input_provenance.kinds.flatMap((kind:any)=>kind.batches.map((batch:any)=>batch.batch_id));
 expect(sourceBatches).toContain(first.preview.id);
 await page.goto('/procurement/'+fresh.plan.id);
 const provenance=page.getByTestId('input-provenance');await expect(provenance).toContainText('Есепке кірген деректер өзгермеген.');
 await provenance.locator('summary').click();
 await provenance.getByRole('button',{name:new RegExp('^Импорт '+first.preview.id.slice(0,8)+' · ')}).click();
 await expect(page).toHaveURL(new RegExp('/imports\\?batch='+first.preview.id+'$'));
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await expect(page.getByText('Synthetic live test: correct observed portion count',{exact:false})).toBeVisible();

 const approvalHeaders={...headers,'Idempotency-Key':'approved-inputs-'+fresh.plan.id};
 const approvalPayload={expected_version:fresh.plan.version,reason:'Synthetic live test: reviewed current inputs and shortages',acknowledge_shortage:true};
 const approvedResponse=await page.request.post('/api/v1/plans/'+fresh.plan.id+'/approve',{headers:approvalHeaders,data:approvalPayload});
 expect(approvedResponse.status()).toBe(200);const approved=await approvedResponse.json();expect(approved.status).toBe('approved');
 const approvedExport=await exportPlan(page,fresh.plan.id);
 await uploadAndCommit(page,original,'correction','Synthetic live test: restore original observed portion count');
 const restored=await getJson(page,salesPath);expect(restored.total).toBe(1);expect(restored.items[0].units_sold).toBe(originalUnits);
 const historical=await getJson(page,'/plans/'+fresh.plan.id);
 expect(historical.input_freshness).toBe('changed');expect(historical.status).toBe('approved');
 expect(savedResult(historical)).toEqual(savedResult(approved));expect((await exportPlan(page,fresh.plan.id)).equals(approvedExport)).toBe(true);
 const replay=await page.request.post('/api/v1/plans/'+fresh.plan.id+'/approve',{headers:approvalHeaders,data:approvalPayload});
 expect(replay.status()).toBe(200);expect(await replay.json()).toEqual(approved);
 const audit=await getJson(page,'/audit?branch_id=1&limit=200');
 expect(audit.items.filter((event:any)=>event.action==='plan.approved'&&event.entity_id===fresh.plan.id)).toHaveLength(1);
 await page.goto('/procurement/'+fresh.plan.id);await expect(page.locator('.context-line')).toContainText('Бекітілді');
 await expect(page.getByTestId('input-provenance')).toContainText('Бастапқы деректер өзгерді.');
 await page.setViewportSize({width:390,height:844});
 await expect.poll(()=>page.locator('.sidebar').evaluate(element=>element.getBoundingClientRect().right)).toBeLessThanOrEqual(0.5);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:directory+'/import-lineage-approved-mobile.png',fullPage:true,animations:'disabled'});
 expect(pageErrors).toEqual([]);
});
