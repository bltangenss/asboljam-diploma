import {test,expect,type Page} from '@playwright/test';

type Scenario={source?:'REAL'|'SYNTHETIC';sales?:boolean;forecast?:boolean;stale?:boolean;stock?:boolean;plan?:boolean;deficit?:number;forecastDate?:string;role?:'admin'|'analyst'};
// UI-only fixtures. The historical date must stay visible even when the computer date changes.
async function install(page:Page,scenario:Scenario={}){
 const synthetic=scenario.source!=='REAL';
 const context={version:1,mode:synthetic?'synthetic_fixed':'real_business',data_origin:synthetic?'SYNTHETIC':'REAL',usage_mode:synthetic?'DEMO':'TEST',timezone:'Asia/Almaty',currency:'KZT',branch_id:'test',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2025-12-30',inventory_dates:scenario.stock===false?['2025-12-30']:['2025-12-30','2026-01-01'],dates_editable:!synthetic,operations_enabled:true,business_date:'2026-10-14',source:null};
 const forecast={id:'day-forecast',branch_id:'test',target_date:scenario.forecastDate||'2026-01-01',input_freshness:scenario.stale?'changed':'unchanged',predictions:[{meal_id:'meal',point_forecast:123,p10:null,p50:null,p90:null}]};
 const plan={id:'day-purchase',branch_id:'test',forecast_id:forecast.id,target_date:forecast.target_date,status:'ready',version:1,input_freshness:'unchanged',total_cost:'45000',budget:'50000',shortage_count:scenario.deficit||0};
 await page.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname.replace('/api/v1','');
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'fixture',email:'fixture@example.invalid',organization_id:'today',role:scenario.role||'admin',branch_ids:['test']},csrf_token:'fixture-only'};
  if(path==='/settings')json={organization:{id:'today',name:'Тестовая столовая',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:synthetic?'synthetic_only':'real_only',provenance:'fixture'},onboarding:{branch_count:1,can_import_branches:true,data_policy:synthetic?'synthetic_only':'real_only'},data_context:{...context,branch_id:url.searchParams.has('branch_id')?'test':null}};
  if(path==='/branches')json={items:[{branch_id:'test',branch_name:'Столовая · Алматы'}],total:1};
  if(path==='/dashboard')json={as_of:scenario.sales===false?null:'2025-12-31',sold_portions:186,revenue:'325500',data_origin:context.data_origin,inventory_known:true,inventory_date:'2025-12-30',warnings:[{code:'EXPIRING_LOTS',count:2}],history:[],top_meals:[],latest_forecast:scenario.forecast?forecast:null,latest_plans:scenario.plan?[plan]:[],total_shortages:scenario.plan?plan.shortage_count:null,procurement_cost:scenario.plan?plan.total_cost:null};
  if(path==='/forecasts')json={items:[forecast],total:1};
  if(path==='/forecasts/day-forecast')json=forecast;
  if(path==='/plans/day-purchase')json={...plan,result:{...plan,requirements:[],lines:[],constraints_valid:true}};
  await route.fulfill({json});
 });
 await page.goto('/');
 await expect(page.locator('.today-page')).toBeVisible();
 if(await page.locator('.today-page h1').innerText()!=='Сегодня')await page.locator('.language').click();
 await expect(page.locator('.today-page h1')).toHaveText('Сегодня');
}

test('Today prioritizes actionable risks before daily work and analytics without approving a purchase',async({page})=>{
 const mutations:string[]=[];page.on('request',request=>{if(request.method()==='POST')mutations.push(request.url())});
 await install(page,{forecast:true,plan:true,deficit:2});
 const tasks=page.locator('.today-tasks');
 await expect(tasks).toContainText('Есть дефицит: 2 позиций');
 await expect(tasks).toContainText('Закупка ждёт решения');
 await expect(tasks).toContainText('По срезу на 30.12.2025');
 const order=await page.locator('.today-page').evaluate(element=>{
  const tasks=element.querySelector('.today-tasks')!,work=element.querySelector('.today-work')!,analytics=element.querySelector('.today-analytics')!;
  return Boolean(tasks.compareDocumentPosition(work)&Node.DOCUMENT_POSITION_FOLLOWING)&&Boolean(work.compareDocumentPosition(analytics)&Node.DOCUMENT_POSITION_FOLLOWING);
 });
 expect(order).toBeTruthy();
 await expect(page.locator('.today-stages')).toContainText('123 порций ожидается');
 await expect(page.locator('.today-stages')).toContainText('Наличие среза ещё не означает');
 await expect(page.locator('.today-purchase')).toContainText('45');
 await page.locator('.next-action').getByRole('button',{name:'Открыть план'}).click();
 await expect(page).toHaveURL(/\/procurement\/day-purchase$/);
 expect(mutations).toEqual([]);
});

test('missing target stock blocks purchase preparation but keeps forecast separate and unknown sales visible',async({page})=>{
 await install(page,{sales:false,stock:false});
 await expect(page.locator('.today-tasks')).toContainText('Нет остатков на день расчёта');
 await expect(page.locator('.today-tasks')).toContainText('прогноз можно подготовить отдельно');
 await expect(page.locator('.metric-value').first()).toHaveText('—');
 await expect(page.locator('.today-stages')).toContainText('Нет среза на нужную дату');
 await expect(page.locator('.today-purchase')).toContainText('Актуального плана закупки на этот день нет');
 await page.locator('.today-tasks').getByRole('button',{name:'Добавить остатки'}).click();
 await expect(page).toHaveURL(/\/imports\?kind=inventory_lots$/);
});

test('current forecast carries its identity into the stock check',async({page})=>{
 await install(page,{forecast:true});
 await page.locator('.today-stages').getByRole('button',{name:'Проверить остатки'}).click();
 await expect(page).toHaveURL(/\/inventory\?forecast=day-forecast$/);
});

test('missing stock import retains the branch and forecast for the return to stock',async({page})=>{
 await install(page,{forecast:true,stock:false});
 await expect(page.locator('.today-data-dates')).toContainText('Последние продажи31.12.2025');
 await expect(page.locator('.today-data-dates')).toContainText('Просматриваемый срез остатков30.12.2025');
 await page.locator('.next-action').getByRole('button',{name:'Добавить остатки'}).click();
 const url=new URL(page.url());
 expect(url.pathname).toBe('/imports');
 expect(url.searchParams.get('kind')).toBe('inventory_lots');
 expect(url.searchParams.get('return')).toBe('inventory');
 expect(url.searchParams.get('return_branch')).toBe('test');
 expect(url.searchParams.get('forecast')).toBe('day-forecast');
});

test('changed or other-date forecasts never present saved purchases as the current day plan',async({page})=>{
 await install(page,{forecast:true,plan:true,stale:true});
 await expect(page.locator('.today-tasks')).toContainText('Проверьте актуальность прогноза');
 await expect(page.locator('.today-stages')).toContainText('Нужен прогноз');
 await expect(page.locator('.today-purchase')).toContainText('Актуального плана закупки на этот день нет');
 await expect(page.locator('.today-purchase')).not.toContainText('Утверждён');
 await page.unrouteAll({behavior:'wait'});
 await install(page,{forecast:true,plan:true,forecastDate:'2025-12-31'});
 await expect(page.locator('.today-tasks')).toContainText('Нужен прогноз на этот день');
 await expect(page.locator('.today-stages')).not.toContainText('123');
 await expect(page.locator('.today-purchase')).toContainText('Актуального плана закупки на этот день нет');
});

test('synthetic and real historical day labels remain honest on a narrow screen',async({page})=>{
 await page.setViewportSize({width:360,height:850});
 await install(page,{forecast:true,plan:true});
 await expect(page.locator('.today-context')).toContainText('Учебный день · 01.01.2026');
 await expect(page.locator('.today-source-note')).toContainText('синтетических данных');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.unrouteAll({behavior:'wait'});
 await install(page,{source:'REAL',forecast:true});
 await expect(page.locator('.today-context')).toContainText('День расчёта · 01.01.2026');
 await expect(page.locator('.today-context')).not.toContainText('Учебный день');
 await expect(page.locator('.today-source-note')).toContainText('TEST — тестовый режим');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('read-only users get a viewing action rather than an approval or run command',async({page})=>{
 await install(page,{forecast:true,plan:true,role:'analyst'});
 await expect(page.locator('.next-action')).toContainText('Посмотрите результаты филиала');
 await expect(page.locator('.today-page').getByRole('button',{name:'Утвердить',exact:true})).toHaveCount(0);
});
