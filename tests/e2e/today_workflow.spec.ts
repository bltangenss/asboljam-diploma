import {test,expect,type Page} from '@playwright/test';

type Scenario={source?:'REAL'|'SYNTHETIC';sales?:boolean;forecast?:boolean;stale?:boolean;stock?:boolean;plan?:boolean;deficit?:number;forecastDate?:string;role?:'admin'|'analyst';planStatus?:'ready'|'rejected';planStale?:boolean;manual?:boolean;invalidManual?:'missing'|'foreign'};
// UI-only fixtures. The historical date must stay visible even when the computer date changes.
async function install(page:Page,scenario:Scenario={}){
 const synthetic=scenario.source!=='REAL';
 const context={version:1,mode:synthetic?'synthetic_fixed':'real_business',data_origin:synthetic?'SYNTHETIC':'REAL',usage_mode:synthetic?'DEMO':'TEST',timezone:'Asia/Almaty',currency:'KZT',branch_id:'test',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2025-12-30',inventory_dates:scenario.stock===false?['2025-12-30']:['2025-12-30','2026-01-01'],dates_editable:!synthetic,operations_enabled:true,business_date:'2026-10-14',source:null};
 const forecast={id:'day-forecast',branch_id:'test',target_date:scenario.forecastDate||'2026-01-01',input_freshness:scenario.stale?'changed':'unchanged',predictions:[{meal_id:'meal',point_forecast:123,p10:null,p50:null,p90:null}]};
 const production={id:'saved-cooking',branch_id:scenario.invalidManual==='foreign'?'another-branch':'test',forecast_id:forecast.id,target_date:forecast.target_date,basis:'manual_portions',name:'Ручной обед',reason:'Порции выбраны управляющим',input_freshness:'unchanged',portions:[{meal_id:'meal',forecast_point:123,portions:70}],data_origin:context.data_origin,usage_mode:context.usage_mode};
 const plan={id:'day-purchase',branch_id:'test',forecast_id:forecast.id,target_date:forecast.target_date,status:scenario.planStatus||'ready',version:1,input_freshness:scenario.planStale?'changed':'unchanged',total_cost:'45000',budget:'50000',shortage_count:scenario.deficit||0,...(scenario.manual?{demand_basis:'production_plan',production_plan_id:production.id,production_plan_evidence:scenario.invalidManual==='missing'?null:production}:{})};
 const stockRow={branch_id:'test',ingredient_id:'flour',lot_id:'COUNT-1',snapshot_date:'2026-01-01',expiry_date:'2026-01-31',on_hand_qty:'3',unit:'kg',data_origin:context.data_origin};
 const importReceipt={id:'today-stock-batch',status:'committed',row_count:1,inserted_rows:1,updated_rows:0,unchanged_rows:0};
 const importBatch:any={id:'today-stock-batch',kind:'inventory_lots',row_count:1,valid:true,status:'preview',mode:'append',can_commit:true,branch_ids:['test'],counts:{rows_seen:1,rows_checked:1,parsed:1,new:1,unchanged:0,updated:0,conflicting:0},scan_complete:true,errors:[],preview:[stockRow],changes:[{key:'synthetic-stock',operation:'insert',before:null,after:stockRow}],source:{source_id:'manual_csv',mapping_version:'canonical-v1',currency:'KZT',data_origin:context.data_origin},receipt:null};
 const requests:{path:string;method:string;body:any}[]=[];
 await page.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname.replace('/api/v1','');
  requests.push({path,method:route.request().method(),body:route.request().postData()?route.request().postDataJSON():null});
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'fixture',email:'fixture@example.invalid',organization_id:'today',role:scenario.role||'admin',branch_ids:['test']},csrf_token:'fixture-only'};
  if(path==='/settings')json={organization:{id:'today',name:'Тестовая столовая',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:synthetic?'synthetic_only':'real_only',provenance:'fixture'},onboarding:{branch_count:1,can_import_branches:true,data_policy:synthetic?'synthetic_only':'real_only'},data_context:{...context,branch_id:url.searchParams.has('branch_id')?'test':null}};
  if(path==='/branches')json={items:[{branch_id:'test',branch_name:'Столовая · Алматы'}],total:1};
  if(path==='/dashboard')json={as_of:scenario.sales===false?null:'2025-12-31',sold_portions:186,revenue:'325500',data_origin:context.data_origin,inventory_known:true,inventory_date:'2025-12-30',warnings:[{code:'EXPIRING_LOTS',count:2}],history:[],top_meals:[],latest_forecast:scenario.forecast?forecast:null,latest_plans:scenario.plan?[plan]:[],total_shortages:scenario.plan?plan.shortage_count:null,procurement_cost:scenario.plan?plan.total_cost:null};
  if(path==='/forecasts')json={items:[forecast],total:1};
  if(path==='/forecasts/day-forecast')json=forecast;
  if(path==='/production-plans')json={items:scenario.manual?[production]:[],total:scenario.manual?1:0};
  if(path==='/production-plans/saved-cooking')json=production;
  if(path==='/stock/ledger')json={ledger:null,version:null,baseline_freshness:'unknown',context_freshness:'unchanged',public_context:context};
  if(path==='/stock/catalog')json={ingredients:[{ingredient_id:'flour',ingredient_name:'Мука',unit:'kg'}],meals:[],...context};
  if(path==='/imports/preview')json=importBatch;
  if(path==='/imports/today-stock-batch')json=importBatch;
  if(path==='/imports/today-stock-batch/commit'){Object.assign(importBatch,{status:'committed',can_commit:false,receipt:importReceipt});if(!context.inventory_dates.includes('2026-01-01'))context.inventory_dates.push('2026-01-01');json=importReceipt;}
  if(path==='/inventory')json={items:importBatch.status==='committed'?[stockRow]:[],total:importBatch.status==='committed'?1:0};
  if(path==='/plans/day-purchase')json={...plan,result:{...plan,requirements:[],lines:[],constraints_valid:true}};
  await route.fulfill({json});
 });
 await page.goto('/');
 await expect(page.locator('.today-page')).toBeVisible();
 if(await page.locator('.today-page h1').innerText()!=='Сегодня')await page.locator('.language').click();
 await expect(page.locator('.today-page h1')).toHaveText('Сегодня');
 return {requests,importBatch,stockRow};
}

test('Today prioritizes actionable risks before daily work and analytics without approving a purchase',async({page})=>{
 const mutations:string[]=[];page.on('request',request=>{if(request.method()==='POST')mutations.push(request.url())});
 await install(page,{forecast:true,plan:true,deficit:2});
 const tasks=page.locator('.day-attention');
 await expect(tasks).toContainText('Есть дефицит: 2 позиций');
 await expect(tasks).toContainText('Закупка ждёт решения');
 await expect(tasks).toContainText('По срезу на 30.12.2025');
 const order=await page.locator('.today-page').evaluate(element=>{
  const tasks=element.querySelector('.day-attention')!,work=element.querySelector('.day-work')!,analytics=element.querySelector('.day-recap')!;
  return Boolean(tasks.compareDocumentPosition(work)&Node.DOCUMENT_POSITION_FOLLOWING)&&Boolean(work.compareDocumentPosition(analytics)&Node.DOCUMENT_POSITION_FOLLOWING);
 });
 expect(order).toBeTruthy();
 await expect(page.locator('.day-pipeline')).toContainText('123 порций ожидается');
 await expect(page.locator('.day-pipeline')).toContainText('Наличие среза ещё не означает');
 await expect(page.locator('.day-step-purchase')).toContainText('45');
 await page.locator('.next-action').getByRole('button',{name:'Открыть план'}).click();
 await expect(page).toHaveURL(/\/procurement\/day-purchase$/);
 expect(mutations).toEqual([]);
});

test('missing target stock blocks purchase preparation but keeps forecast separate and unknown sales visible',async({page})=>{
 await install(page,{sales:false,stock:false});
 await expect(page.locator('.day-attention')).toContainText('Нет остатков на день расчёта');
 await expect(page.locator('.day-attention')).toContainText('прогноз можно подготовить отдельно');
 await expect(page.locator('.metric-value').first()).toHaveText('—');
 await expect(page.locator('.day-pipeline')).toContainText('Нет среза на нужную дату');
 await expect(page.locator('.day-step-purchase')).toContainText('Актуального плана закупки на этот день нет');
 await page.locator('.day-attention').getByRole('button',{name:'Добавить остатки'}).click();
 await expect(page).toHaveURL(/\/imports\?kind=inventory_lots$/);
});

test('current forecast carries its identity into the stock check',async({page})=>{
 await install(page,{forecast:true});
 await page.locator('.day-pipeline').getByRole('button',{name:'Проверить остатки'}).click();
 await expect(page).toHaveURL(/\/inventory\?forecast=day-forecast$/);
});

test('missing stock import retains the branch and forecast for the return to stock',async({page})=>{
 await install(page,{forecast:true,stock:false});
 await expect(page.locator('.day-data-dates')).toContainText('Последние продажи31.12.2025');
 await expect(page.locator('.day-data-dates')).toContainText('Просматриваемый срез остатков30.12.2025');
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
 await expect(page.locator('.day-attention')).toContainText('Проверьте актуальность прогноза');
 await expect(page.locator('.day-pipeline')).toContainText('Нужен прогноз');
 await expect(page.locator('.day-step-purchase')).toContainText('Актуального плана закупки на этот день нет');
 await expect(page.locator('.day-step-purchase')).not.toContainText('Утверждён');
 await page.unrouteAll({behavior:'wait'});
 await install(page,{forecast:true,plan:true,forecastDate:'2025-12-31'});
 await expect(page.locator('.day-attention')).toContainText('Нужен прогноз на этот день');
 await expect(page.locator('.day-pipeline')).not.toContainText('123');
 await expect(page.locator('.day-step-purchase')).toContainText('Актуального плана закупки на этот день нет');
});

test('synthetic and real historical day labels remain honest on a narrow screen',async({page})=>{
 await page.setViewportSize({width:360,height:850});
 await install(page,{forecast:true,plan:true});
 await expect(page.locator('.day-context')).toContainText('Учебный день · 01.01.2026');
 await expect(page.locator('.today-source-note')).toContainText('синтетических данных');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.unrouteAll({behavior:'wait'});
 await install(page,{source:'REAL',forecast:true});
 await expect(page.locator('.day-context')).toContainText('День расчёта · 01.01.2026');
 await expect(page.locator('.day-context')).not.toContainText('Учебный день');
 await expect(page.locator('.today-source-note')).toContainText('TEST — тестовый режим');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('read-only users get a viewing action rather than an approval or run command',async({page})=>{
 await install(page,{forecast:true,plan:true,role:'analyst'});
 await expect(page.locator('.next-action')).toContainText('Посмотрите результаты филиала');
 await expect(page.locator('.today-page').getByRole('button',{name:'Утвердить',exact:true})).toHaveCount(0);
});


test('rejected manual purchase keeps the saved cooking variant when calculating again',async({page})=>{
 await install(page,{forecast:true,plan:true,manual:true,planStatus:'rejected'});
 await expect(page.getByTestId('today-production-basis')).toContainText('Ручной обед');
 await page.locator('.next-action').getByRole('button',{name:'Рассчитать новый план',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=day-forecast&production_plan_id=saved-cooking$/);
 await expect(page.getByLabel('Основание потребности',{exact:true})).toHaveValue('saved-cooking');
 await expect(page.getByTestId('production-saved')).toContainText('70');
});

test('inventory-staled manual purchase preserves its cooking basis on task and next-step recalculation',async({page})=>{
 await install(page,{forecast:true,plan:true,manual:true,planStale:true});
 await expect(page.locator('.day-attention')).toContainText('Расчёт закупки нужно обновить');
 await expect(page.locator('.day-pipeline')).toContainText('123 порций ожидается');
 await page.locator('.day-attention').getByRole('button',{name:'Пересчитать закупку',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=day-forecast&production_plan_id=saved-cooking$/);
 await expect(page.getByLabel('Основание потребности',{exact:true})).toHaveValue('saved-cooking');
 await page.goto('/');await page.locator('.next-action').getByRole('button',{name:'Перейти к закупке',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=day-forecast&production_plan_id=saved-cooking$/);
});

for(const invalidManual of ['missing','foreign'] as const)test('manual basis '+invalidManual+' fails visibly instead of falling back to forecast',async({page})=>{
 await install(page,{forecast:true,plan:true,manual:true,planStatus:'rejected',invalidManual});
 await expect(page.locator('.day-attention')).toContainText('Основание приготовления не подтверждено');
 await page.locator('.next-action').getByRole('button',{name:'Проверить исходную закупку',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\/day-purchase$/);
});

test('rejected forecast-based purchase still opens normal forecast procurement',async({page})=>{
 await install(page,{forecast:true,plan:true,planStatus:'rejected'});
 await page.locator('.next-action').getByRole('button',{name:'Рассчитать новый план',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=day-forecast$/);
 await expect(page.getByLabel('Основание потребности',{exact:true})).toHaveValue('');
});


test('Today stock check and procurement preserve the verified manual cooking basis',async({page})=>{
 const state=await install(page,{forecast:true,plan:true,manual:true});
 await page.locator('.day-pipeline').getByRole('button',{name:'Проверить остатки',exact:true}).click();
 await expect(page).toHaveURL(/\/inventory\?forecast=day-forecast&production_plan_id=saved-cooking$/);
 const flow=page.getByRole('region',{name:'Продолжение планирования',exact:true});
 await expect(flow.getByTestId('production-saved')).toContainText('Ручной обед');
 await flow.getByRole('button',{name:'К расчёту закупки',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=day-forecast&production_plan_id=saved-cooking$/);
 await expect(page.getByLabel('Основание потребности',{exact:true})).toHaveValue('saved-cooking');
 expect(state.requests.filter(request=>request.method==='POST')).toEqual([]);
});

test('Today missing-stock CSV and confirmed return keep the manual cooking basis',async({page})=>{
 const state=await install(page,{forecast:true,plan:true,manual:true,stock:false,planStale:true});
 await page.locator('.day-attention').getByRole('button',{name:'Добавить остатки',exact:true}).click();
 const url=new URL(page.url());expect(url.pathname).toBe('/imports');expect(url.searchParams.get('kind')).toBe('inventory_lots');expect(url.searchParams.get('return')).toBe('inventory');expect(url.searchParams.get('return_branch')).toBe('test');expect(url.searchParams.get('forecast')).toBe('day-forecast');expect(url.searchParams.get('production_plan_id')).toBe('saved-cooking');
 const done=page.getByRole('button',{name:'Вернуться к работе над планом',exact:true});await expect(done).toHaveCount(0);
 const csv=Object.keys(state.stockRow).join(',')+'\n'+Object.values(state.stockRow).join(',')+'\n';
 await page.locator('input[type=file]').setInputFiles({name:'synthetic-today-stock.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.getByRole('button',{name:'Предпросмотр',exact:true}).click();await page.getByRole('button',{name:'Импортировать',exact:true}).click();
 await expect(done).toBeVisible();expect(state.importBatch.receipt).toMatchObject({status:'committed',inserted_rows:1});
 await done.click();await expect(page).toHaveURL(/\/inventory\?forecast=day-forecast&production_plan_id=saved-cooking$/);
 const flow=page.getByRole('region',{name:'Продолжение планирования',exact:true});await expect(flow.getByTestId('production-saved')).toContainText('Ручной обед');await flow.getByRole('button',{name:'К расчёту закупки',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=day-forecast&production_plan_id=saved-cooking$/);
 expect(state.requests.filter(request=>request.method==='POST').map(request=>request.path)).toEqual(['/imports/preview','/imports/today-stock-batch/commit']);
});

for(const invalidManual of ['missing','foreign'] as const)test('Today stock and CSV paths do not discard '+invalidManual+' manual basis',async({page})=>{
 const state=await install(page,{forecast:true,plan:true,manual:true,stock:false,invalidManual});
 await expect(page.locator('.day-attention')).toContainText('Основание приготовления не подтверждено');
 await page.locator('.day-pipeline').getByRole('button',{name:'Проверить остатки',exact:true}).click();await expect(page).toHaveURL(/\/procurement\/day-purchase$/);
 await page.goto('/');await page.locator('.day-attention').getByRole('button',{name:'Добавить остатки',exact:true}).click();await expect(page).toHaveURL(/\/procurement\/day-purchase$/);
 expect(state.requests.some(request=>['/imports/preview','/procurement'].includes(request.path)&&request.method==='POST')).toBe(false);
});
