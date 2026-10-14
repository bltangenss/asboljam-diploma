import {test,expect,type Page} from '@playwright/test';
import fs from 'node:fs';

// Opt-in: prepare_stock_e2e.py creates a NEW ignored DB. Copy its login fixture to
// .cache/production-e2e-login.json. Run API/worker/web against that DB only.
// REAL/TEST fixtures are generated contract records, never observations of a business.
test.skip(process.env.ASBOLJAM_PRODUCTION_E2E!=='1','Requires a new isolated production fixture and explicit opt-in.');
async function get(page:Page,path:string){const response=await page.request.get('/api/v1'+path);expect(response.status()).toBe(200);return response.json()}
async function approve(page:Page){
 await page.locator('.approval-panel').getByRole('button',{name:'Утвердить план',exact:true}).click();
 const dialog=page.getByRole('dialog');await dialog.getByLabel('Причина решения',{exact:true}).fill('Проверены порции, остатки, упаковки и бюджет');
 const ack=dialog.getByRole('checkbox');if(await ack.count())await ack.check();
 const response=page.waitForResponse(r=>r.url().includes('/approve')&&r.request().method()==='POST');
 await dialog.getByRole('button',{name:'Утвердить план',exact:true}).click();expect((await response).status()).toBe(200);await expect(page.locator('.decision-receipt')).toBeVisible();
}
async function saveVariant(page:Page,name:string,quantity:string){
 const area=page.getByTestId('production-planning'),editor=page.getByTestId('production-editor');
 await area.getByRole('spinbutton').fill(quantity);await editor.getByLabel('Название варианта',{exact:true}).fill(name);await editor.getByLabel('Почему выбраны эти порции',{exact:true}).fill('Искусственный тест: решение управляющего о приготовлении');
 const saved=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/production-plans'&&r.request().method()==='POST');
 await editor.getByRole('button',{name:'Сохранить новый вариант',exact:true}).click();const response=await saved;expect(response.status()).toBe(201);const document=await response.json();
 await expect(page.getByTestId('production-saved')).toContainText(name);return document;
}
async function calculate(page:Page){
 await page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true}).click();await expect(page).toHaveURL(/\/procurement\/[a-f0-9]+$/,{timeout:120000});
 return get(page,'/plans/'+new URL(page.url()).pathname.split('/').at(-1));
}

test('live manual cooking variants drive exact procurement, retain approval and preserve old exports',async({page})=>{
 test.setTimeout(300000);const fixture=JSON.parse(fs.readFileSync('.cache/production-e2e-login.json','utf8'));expect(['SYNTHETIC','REAL']).toContain(fixture.data_origin);
 if(fixture.data_origin==='REAL')expect(fixture.usage_mode).toBe('TEST');
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 await page.goto('/');await page.locator('input[type=email]').fill(fixture.email);await page.locator('input[type=password]').fill(fixture.password);await page.getByRole('button',{name:'Войти в систему',exact:true}).click();await expect(page.getByRole('heading',{name:'Сегодня',exact:true})).toBeVisible();
 await page.goto('/forecasts');await page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true}).click();await expect(page).toHaveURL(/\/forecasts\/[a-f0-9]+$/,{timeout:120000});
 const forecastId=new URL(page.url()).pathname.split('/').at(-1)!,original=await get(page,'/forecasts/'+forecastId);
 const baselineLedger=await get(page,'/stock/ledger?branch_id='+fixture.branch_id+'&opening_date='+original.target_date);expect(baselineLedger.ledger).toBeNull();
 const first=await saveVariant(page,'Обед: 200 порций','200');expect(first).toMatchObject({forecast_id:forecastId,branch_id:fixture.branch_id,basis:'manual_portions',portions:[{meal_id:fixture.meal_id,portions:200}]});
 await page.getByRole('button',{name:'Проверить остатки',exact:true}).click();await expect(page).toHaveURL(new RegExp('/inventory\\?forecast='+forecastId+'&production_plan_id='+first.id+'$'));
 const flow=page.getByRole('region',{name:'Продолжение планирования',exact:true});
 await flow.getByRole('button',{name:'К расчёту закупки',exact:true}).click();await expect(page.getByLabel('Основание потребности',{exact:true})).toHaveValue(first.id);
 const plan=await calculate(page);expect(plan.demand_basis).toBe('production_plan');expect(plan.production_plan_id).toBe(first.id);expect(plan.production_plan_evidence.portions[0].portions).toBe(200);
 const needed=20,stock=fixture.data_origin==='REAL'?12:10,required=plan.requirements.find((r:any)=>r.ingredient_id===fixture.ingredient_id);
 expect(Number(required.gross_required)).toBe(needed);expect(Number(required.usable_stock)).toBe(stock);expect(Number(plan.total_cost)).toBe((needed-stock)*1000);expect(plan.lines[0].packs).toBe(needed-stock);expect(Number(plan.lines[0].line_cost_kzt)).toBe((needed-stock)*1000);expect(plan.shortage_count).toBe(0);expect(plan.constraints_valid).toBe(true);
 await expect(page.getByRole('region',{name:'Основание плана приготовления',exact:true})).toContainText('Обед: 200 порций');await approve(page);
 const exported=await page.request.get('/api/v1/plans/'+plan.id+'/export');expect(exported.status()).toBe(200);const oldBytes=await exported.body();expect(oldBytes.toString('utf8')).toContain(first.id);expect(oldBytes.toString('utf8')).toContain('Обед: 200 порций');
 await page.goto('/forecasts/'+forecastId+'?production_plan_id='+first.id);await page.getByRole('button',{name:'Изменить и сохранить новым вариантом',exact:true}).click();const second=await saveVariant(page,'Сегодня не готовим','0');expect(second.id).not.toBe(first.id);
 expect((await get(page,'/production-plans/'+first.id)).portions[0].portions).toBe(200);expect((await get(page,'/forecasts/'+forecastId)).predictions).toEqual(original.predictions);
 expect((await get(page,'/plans/'+plan.id)).input_freshness).toBe('unchanged');expect(await(await page.request.get('/api/v1/plans/'+plan.id+'/export')).body()).toEqual(oldBytes);
 await page.getByRole('button',{name:'Остатки готовы — перейти к закупке',exact:true}).click();const zero=await calculate(page);expect(zero.production_plan_id).toBe(second.id);expect(Number(zero.total_cost)).toBe(0);expect(zero.lines).toEqual([]);expect(zero.shortage_count).toBe(0);expect(zero.constraints_valid).toBe(true);
 const ledger=await get(page,'/stock/ledger?branch_id='+fixture.branch_id+'&opening_date='+original.target_date);expect(ledger.ledger).toBeNull();
 const audit=await get(page,'/audit?branch_id='+fixture.branch_id+'&limit=100');expect(audit.items.filter((r:any)=>r.entity_id===first.id||r.entity_id===second.id)).toHaveLength(2);
 expect(errors).toEqual([]);
 fs.writeFileSync('.cache/production-live-'+fixture.data_origin.toLowerCase()+'-result.json',JSON.stringify({data_origin:fixture.data_origin,usage_mode:fixture.usage_mode,generated_fixture_only:true,target_date:original.target_date,forecast_unchanged:true,first_portions:200,second_portions:0,gross_required:needed,usable_stock:stock,total_cost:plan.total_cost,old_export_byte_identical:true,stock_posted:false,browser_errors:errors},null,2));
});
