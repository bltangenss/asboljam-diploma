import {test,expect,type Page} from '@playwright/test';

type Options={lang?:'kk'|'ru';source?:'SYNTHETIC'|'REAL'|null;usage?:'DEMO'|'TEST';freshness?:'unchanged'|'changed'|null;mode?:'afterprint'|'noevent'|'throws';frozenZone?:string;organizationZone?:string};
const forecastId='print-forecast',productionId='print-cooking';
const fixture={id:productionId,branch_id:'1',forecast_id:forecastId,target_date:'2026-01-01',basis:'manual_portions',name:'Обед для первой смены',reason:'Группа придёт к 12:00. Суп сегодня не готовим.',actor_id:'saved-manager',created_at:'2026-10-14T17:00:00Z',portions:[{meal_id:'meal-a',meal_name:'Бауырдақ',forecast_point:10.2,portions:15},{meal_id:'meal-b',meal_name:'Сорпа',forecast_point:6.1,portions:0}]};
const buttonName=(lang='ru')=>lang==='kk'?'Дайындау жоспарын басып шығару':'Распечатать план приготовления';

async function install(page:Page,options:Options={}){
 const lang=options.lang||'ru',mode=options.mode||'afterprint';
 await page.addInitScript(({lang,mode})=>{
  localStorage.setItem('asboljam-language',lang);
  const state=window as typeof window&{printCaptures:any[]};state.printCaptures=[];
  window.print=()=>{
   const sheet=document.querySelector<HTMLElement>('[data-testid="production-print-sheet"]')!;
   const table=sheet.querySelector('table')!,app=document.querySelector('#root')!;
   state.printCaptures.push({text:sheet.innerText,rows:Array.from(table.querySelectorAll('tbody tr')).map(row=>Array.from(row.querySelectorAll('th,td')).map(cell=>cell.textContent)),sheetDisplay:getComputedStyle(sheet).display,appDisplay:getComputedStyle(app).display,page:getComputedStyle(sheet).getPropertyValue('page'),headerDisplay:getComputedStyle(table.querySelector('thead')!).display,rowBreak:getComputedStyle(table.querySelector('tbody tr')!).breakInside});
   if(mode==='throws')throw new Error('Artificial browser print failure');
   if(mode==='afterprint')window.dispatchEvent(new Event('afterprint'));
  };
 },{lang,mode});
 const source=options.source===undefined?'SYNTHETIC':options.source,usage=options.usage||'DEMO';
 const saved={...fixture,data_origin:source,usage_mode:usage,input_freshness:options.freshness===undefined?'unchanged':options.freshness,execution_context:{timezone:options.frozenZone||'Asia/Qyzylorda'}};
 const forecast={id:forecastId,branch_id:'1',model:'rolling_mean_28',target_date:'2026-01-01',forecast_origin:'2025-12-31',input_freshness:'unchanged',data_origin:'SYNTHETIC',predictions:fixture.portions.map(row=>({meal_id:row.meal_id,meal_name:row.meal_name,point_forecast:row.forecast_point,p10:null,p50:null,p90:null}))};
 const mutations:string[]=[];
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');if(request.method()!=='GET')mutations.push(path);
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'print-reader',organization_id:'print-org',email:'print@example.invalid',role:'analyst',branch_ids:['1']},csrf_token:'artificial-print-token'};
  if(path==='/settings')json={organization:{id:'print-org',name:'Print fixture',status:'active',data_policy:'synthetic_only',timezone:options.organizationZone||'Asia/Qyzylorda',currency:'KZT'},onboarding:{branch_count:1,data_policy:'synthetic_only'},data_context:{version:1,mode:'synthetic_fixed',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',branch_id:url.searchParams.get('branch_id')||'1',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:null,source:null}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Бауырдак · филиал 1'}],total:1};
  if(path==='/meals')json={items:fixture.portions,total:2};
  if(path==='/forecasts/'+forecastId)json=forecast;
  if(path==='/production-plans')json={items:[saved],total:1};
  if(path==='/production-plans/'+productionId)json=saved;
  await route.fulfill({json});
 });
 await page.goto('/forecasts/'+forecastId+'?production_plan_id='+productionId);
 await expect(page.getByTestId('production-saved')).toContainText(fixture.name);
 return {mutations};
}
async function captures(page:Page){return page.evaluate(()=>(window as typeof window&{printCaptures:any[]}).printCaptures)}
async function cleaned(page:Page){await expect(page.getByTestId('production-print-sheet')).toHaveCount(0);await expect(page.locator('body')).not.toHaveClass(/production-print-active/)}

test('saved cooking print preserves frozen meal names, integer zero, reason, date and source without mutations',async({page})=>{
 const state=await install(page);await page.emulateMedia({media:'print'});
 // The action remains in the normal app until its own print snapshot is mounted.
 await page.getByRole('button',{name:buttonName(),exact:true}).click();
 await expect.poll(async()=>(await captures(page)).length).toBe(1);const printed=(await captures(page))[0];
 expect(printed.text).toContain('Бауырдак · филиал 1');expect(printed.text).toContain('01.01.2026');expect(printed.text).toContain(fixture.name);expect(printed.text).toContain(fixture.reason);expect(printed.text).toContain('saved-manager');expect(printed.text).toContain('SYNTHETIC');expect(printed.text).toContain('намерение, а не факт выполнения');expect(printed.text).toContain('не списывает склад');expect(printed.text).toContain(forecastId);
 expect(printed.rows).toEqual([['Бауырдақ','15'],['Сорпа','0']]);expect(printed.text).toContain('Asia/Qyzylorda');expect(printed.sheetDisplay).toBe('block');expect(printed.appDisplay).toBe('none');expect(printed.page).toBe('production-cooking');expect(printed.headerDisplay).toBe('table-header-group');expect(printed.rowBreak).toBe('avoid');
 await cleaned(page);expect(state.mutations).toEqual([]);
});

test('Kazakh sheet keeps TEST and unknown freshness explicit',async({page})=>{
 const state=await install(page,{lang:'kk',source:'REAL',usage:'TEST',freshness:null});await page.emulateMedia({media:'print'});
 await page.getByRole('button',{name:buttonName('kk'),exact:true}).click();await expect.poll(async()=>(await captures(page)).length).toBe(1);
 const printed=(await captures(page))[0];expect(printed.text).toContain('Сақталған дайындау жоспары');expect(printed.text).toContain('Дайындау, порция');expect(printed.text).toContain('REAL / TEST');expect(printed.text).toContain('өзектілігі белгісіз');expect(printed.text).toContain('орындалу есебі емес');expect(printed.rows[1][1]).toBe('0');await cleaned(page);expect(state.mutations).toEqual([]);
});

test('omitted afterprint keeps the snapshot until explicit close and allows another print',async({page})=>{
 const state=await install(page,{mode:'noevent',source:null,freshness:'changed'});await page.emulateMedia({media:'print'});
 const button=page.getByRole('button',{name:buttonName(),exact:true});await button.click();await expect.poll(async()=>(await captures(page)).length).toBe(1);
 await expect(page.getByTestId('production-print-sheet')).toHaveCount(1);await page.emulateMedia({media:'screen'});await expect(button).toBeDisabled();
 await page.getByRole('button',{name:'Закрыть печатную копию',exact:true}).click();await cleaned(page);await expect(button).toBeEnabled();
 await page.emulateMedia({media:'print'});await button.click();await expect.poll(async()=>(await captures(page)).length).toBe(2);await page.emulateMedia({media:'screen'});await page.getByRole('button',{name:'Закрыть печатную копию',exact:true}).click();await cleaned(page);
 const printed=(await captures(page))[1];expect(printed.text).toContain('Источник данных неизвестен');expect(printed.text).toContain('Исходные данные изменились');expect(state.mutations).toEqual([]);
});

test('asynchronous print return retains the saved snapshot until delayed afterprint',async({page})=>{
 const state=await install(page,{mode:'noevent'});await page.emulateMedia({media:'print'});
 await page.getByRole('button',{name:buttonName(),exact:true}).click();await expect.poll(async()=>(await captures(page)).length).toBe(1);
 await expect(page.getByTestId('production-print-sheet')).toContainText(fixture.name);await expect(page.getByTestId('production-print-sheet')).toContainText(fixture.reason);
 await page.evaluate(()=>window.dispatchEvent(new Event('afterprint')));await cleaned(page);await expect(page.getByRole('button',{name:buttonName(),exact:true})).toBeEnabled();expect(state.mutations).toEqual([]);
});

test('print dialog error is visible and does not lock later attempts',async({page})=>{
 await install(page,{mode:'throws'});await page.emulateMedia({media:'print'});const button=page.getByRole('button',{name:buttonName(),exact:true});await button.click();await expect.poll(async()=>(await captures(page)).length).toBe(1);await cleaned(page);
 await expect(page.getByRole('alert')).toContainText('Не удалось открыть окно печати');await expect(button).toBeEnabled();await button.click();await expect.poll(async()=>(await captures(page)).length).toBe(2);await cleaned(page);
});

test('unsaved forecast has no cooking print action',async({page})=>{
 await install(page);await page.goto('/forecasts/'+forecastId);await expect(page.getByTestId('production-planning')).toBeVisible();await expect(page.getByRole('button',{name:buttonName(),exact:true})).toHaveCount(0);expect(await captures(page)).toEqual([]);
});

test('printed time uses the frozen time zone before organization or browser time zone',async({page})=>{
 await install(page,{frozenZone:'UTC',organizationZone:'Asia/Tokyo'});await page.emulateMedia({media:'print'});await page.getByRole('button',{name:buttonName(),exact:true}).click();await expect.poll(async()=>(await captures(page)).length).toBe(1);const printed=(await captures(page))[0];expect(printed.text).toContain('17:00:00 · UTC');expect(printed.text).not.toContain('Asia/Tokyo');await cleaned(page);
});

for(const zones of [{frozenZone:'Invalid/Zone',organizationZone:'Asia/Tokyo',expected:'02:00:00 · Asia/Tokyo'},{frozenZone:'Invalid/Zone',organizationZone:'Invalid/Other',expected:'17:00:00 · UTC'}])test('invalid frozen time zone falls back explicitly to '+zones.organizationZone,async({page})=>{
 await install(page,zones);await page.emulateMedia({media:'print'});await page.getByRole('button',{name:buttonName(),exact:true}).click();await expect.poll(async()=>(await captures(page)).length).toBe(1);expect((await captures(page))[0].text).toContain(zones.expected);await cleaned(page);
});

test('snapshot copy failure releases print ownership for a later attempt',async({page})=>{
 await install(page);await page.emulateMedia({media:'print'});
 await page.evaluate(()=>{const original=JSON.parse;JSON.parse=()=>{throw new Error('Artificial snapshot failure')};try{const button=Array.from(document.querySelectorAll<HTMLButtonElement>('button')).find(node=>node.textContent?.includes('Распечатать план приготовления'))!;button.click()}finally{JSON.parse=original}});
 await expect(page.getByRole('alert')).toContainText('Не удалось открыть окно печати');await cleaned(page);expect(await captures(page)).toEqual([]);
 await page.getByRole('button',{name:buttonName(),exact:true}).click();await expect.poll(async()=>(await captures(page)).length).toBe(1);await cleaned(page);
});
