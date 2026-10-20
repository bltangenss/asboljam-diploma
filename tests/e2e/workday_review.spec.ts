import {test,expect,type Page} from '@playwright/test';

const target='2026-01-01',forecastId='review-forecast',productionId='review-cooking';
const origin={data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',source:null};
const forecast={id:forecastId,branch_id:'1',origin:'2025-12-31',forecast_origin:'2025-12-31',target_date:target,model:'seasonal_naive_7',input_freshness:'unchanged',...origin,predictions:[{meal_id:'meal-a',meal_name:'Бауырдақ, ұзын атауы бар тағам',point_forecast:15,p10:null,p50:null,p90:null}],metadata:{history_start:'2025-09-01',history_end:'2025-12-31',test_start:'2025-12-04',test_end:'2025-12-31',features:[]}};
const production={id:productionId,branch_id:'1',forecast_id:forecastId,target_date:target,name:'Рабочее утро',reason:'Проверено управляющим',basis:'manual_portions',created_at:'2025-12-31T10:00:00Z',actor_id:'review-user',input_freshness:'unchanged',...origin,portions:[{meal_id:'meal-a',meal_name:'Бауырдақ, ұзын атауы бар тағам',forecast_point:15,portions:18}]};
const none={n:0,mae:null,wape:null,bias:null,interval_n:0,interval_coverage:null,nominal_coverage:0.8};
const fact={date:target,meal_id:'meal-a',meal_name:'Бауырдақ, ұзын атауы бар тағам',forecast_point:15,planned_portions:18,actual_units:null,delta:null,absolute_error:null,interval_hit:null,stockout:null,stockout_time:null,fact_status:'missing',eligible_for_performance:false,plan_comparison_eligible:false,plan_absolute_error:null};
async function install(page:Page,options:{mode?:'lost'|'conflict';role?:string;lang?:string}={}){
 await page.addInitScript(lang=>localStorage.setItem('asboljam-language',lang),options.lang||'ru');
 const state={posts:[] as {path:string;body:any;key?:string}[],version:0,selection:null as any,viewed:false};let failed=false;
 const receipts=new Map<string,any>();
 const user={id:'review-user',organization_id:'review-org',email:'review@example.invalid',role:options.role||'manager',branch_ids:['1','2']};
 const day={date:target,branch_id:'1',closure_status:'closed',closure_version:2,closed_at:'2026-01-02T01:00:00Z',fact_fingerprint:'current-facts-fingerprint',forecast_id:forecastId,forecast_kind:'synthetic_demo',eligible_for_performance:false,exclusion_reasons:['DEMONSTRATION_DATA','FACTS_INCOMPLETE_OR_CHANGED'],working_plan:null,matched_observations:0,missing_observations:1,stockout_observations:0,rows:[fact]};
 const review={branch_id:'1',date_from:'2025-12-05',date_to:target,...origin,summary:{closed_days:1,incomplete_days:1,excluded_days:1,matched_observations:0,stockout_observations:0,metrics:none,demonstration_metrics:none,adjustment:{n:0}},latest_closed_day:day,days:[day],rows:[fact],history:[{id:'old-review',target_date:target,version:1,created_at:'2026-01-02T00:00:00Z',input_sha256:'old-fingerprint'}]};
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  if(request.method()==='POST'){
   const body=request.postDataJSON(),key=request.headers()['idempotency-key'];state.posts.push({path,body,key});
   if(path==='/working-plan'){
    if(options.mode==='conflict'&&!failed){failed=true;state.version=1;state.selection={id:'concurrent-selection',production_plan_id:'other-variant',forecast_id:forecastId,target_date:target,selected_at:'2026-01-01T01:00:00Z',actor_id:'another-manager',reason_code:'manager_experience',reason:'Другой управляющий выбрал другую порцию',version:1,...origin};return route.fulfill({status:409,json:{detail:{code:'WORKING_PLAN_VERSION_CONFLICT',message:'Concurrent selection'}}})}
    if(!key)throw new Error('Missing key');
    if(!receipts.has(key)){state.version++;state.selection={id:'selection-'+state.version,production_plan_id:body.production_plan_id,forecast_id:forecastId,target_date:target,selected_at:'2026-01-01T02:00:00Z',actor_id:user.id,reason_code:body.reason_code,reason:body.reason,version:state.version,...origin};receipts.set(key,{version:state.version,selection:state.selection,history:[state.selection]})}
    if(options.mode==='lost'&&!failed){failed=true;return route.abort('failed')}
    return route.fulfill({status:201,json:receipts.get(key)});
   }
   if(path==='/workday-tasks/close-task/view'){state.viewed=true;return route.fulfill({json:{id:'close-task',viewed:true}})}
   if(path==='/forecast-review/refresh')return route.fulfill({json:{snapshots:[{id:'saved-review'}],review}});
   return route.fulfill({status:422,json:{detail:{code:'VALIDATION_ERROR'}}});
  }
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user,csrf_token:'artificial-review-csrf'};
  if(path==='/settings')json={organization:{id:user.organization_id,name:'Artificial review fixture',status:'active',data_policy:'synthetic_only',timezone:origin.timezone,currency:'KZT'},onboarding:{branch_count:2,data_policy:'synthetic_only'},data_context:{version:1,mode:'synthetic_fixed',...origin,branch_id:url.searchParams.get('branch_id')||'1',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:target,inventory_date:target,inventory_dates:[target],dates_editable:false,operations_enabled:true,business_date:null}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Бауырдақ'},{branch_id:'2',branch_name:'Другой филиал'}],total:2};
  if(path==='/meals')json={items:[{meal_id:'meal-a',meal_name:'Бауырдақ, ұзын атауы бар тағам'}],total:1};
  if(path==='/forecasts')json={items:[forecast],total:1};
  if(path==='/forecasts/'+forecastId)json=forecast;
  if(path==='/production-plans')json={items:[production],total:1};
  if(path==='/production-plans/'+productionId)json=production;
  if(path==='/working-plan')json={version:state.version,selection:state.selection,history:state.selection?[state.selection]:[]};
  if(path==='/dashboard')json={as_of:'2025-12-31',data_origin:'SYNTHETIC',inventory_known:true,inventory_date:target,latest_forecast:forecast,latest_plans:[],warnings:[],history:[],top_meals:[],sold_portions:15,revenue:10000};
  if(path==='/forecast-review')json=review;
  if(path==='/forecast-review/history/old-review')json={...day,closure_version:1,fact_fingerprint:'old-fingerprint',rows:[{...fact,actual_units:0,delta:15,fact_status:'closed'}],snapshot:{id:'old-review',version:1}};
  if(path==='/workday-tasks')json={branch_id:'1',business_date:target,...origin,items:[{id:'close-task',code:'DAY_NEEDS_CLOSE',priority:1,branch_id:'1',business_date:target,action_url:'/day-close?date='+target,details:{status:'missing',date:target,version:0},viewed:state.viewed,expires_at:null}],readiness:{sales:{status:'unconfirmed',date:target},closure:{status:'missing',date:target,version:0},history:{status:'available',ready_meals:1,required_days:84},recipes:{status:'available',date:target},inventory:{status:'available',date:target},forecast:{status:'unchanged',date:target}}};
  await route.fulfill({json});
 });
 return state;
}
const planUrl='/forecasts/'+forecastId+'?production_plan_id='+productionId;
const working=(page:Page)=>page.getByTestId('working-plan');
async function explainSelection(page:Page){await working(page).getByLabel('Причина выбора',{exact:true}).selectOption('expected_attendance');await working(page).getByLabel('Поясните решение',{exact:true}).fill('Ожидаем гостей по предварительной записи')}
test('working selection lost reply keeps exact command through global navigation and never changes procurement',async({page})=>{
 const state=await install(page,{mode:'lost'});await page.goto(planUrl);await explainSelection(page);
 await working(page).getByRole('button',{name:'Этот вариант используем в работе',exact:true}).click();
 await expect(working(page).getByRole('button',{name:'Повторить и проверить выбор',exact:true})).toBeVisible();
 await page.locator('.app-nav .app-nav-item').first().click();await expect(page.getByRole('dialog')).toBeVisible();await expect(page.getByRole('dialog').getByRole('button',{name:'Отменить изменения и перейти',exact:true})).toHaveCount(0);await page.getByRole('button',{name:'Остаться в плане',exact:true}).click();
 await working(page).getByRole('button',{name:'Повторить и проверить выбор',exact:true}).click();await expect(working(page)).toContainText('Этот вариант используется в работе');
 expect(state.posts).toHaveLength(2);expect(state.posts[1]).toEqual(state.posts[0]);expect(state.posts.every(post=>post.path==='/working-plan')).toBe(true);
});
test('concurrent working selection reloads version and requires a new explicit decision',async({page})=>{
 const state=await install(page,{mode:'conflict'});await page.goto(planUrl);await explainSelection(page);await working(page).getByRole('button',{name:'Этот вариант используем в работе',exact:true}).click();
 await expect(working(page)).toContainText('Другой пользователь изменил рабочий план');await expect(working(page).getByLabel('Поясните решение',{exact:true})).toHaveValue('Ожидаем гостей по предварительной записи');
 await working(page).getByRole('button',{name:'Этот вариант используем в работе',exact:true}).click();await expect(working(page)).toContainText('Этот вариант используется в работе');
 expect(state.posts).toHaveLength(2);expect(state.posts[0].body.expected_version).toBe(0);expect(state.posts[1].body.expected_version).toBe(1);expect(state.posts[1].key).not.toBe(state.posts[0].key);
});
test('analyst sees working selection state without a write form',async({page})=>{
 const state=await install(page,{role:'analyst'});await page.goto(planUrl);await expect(working(page)).toContainText('Рабочий вариант на этот день ещё не выбран');await expect(working(page).getByLabel('Причина выбора',{exact:true})).toHaveCount(0);expect(state.posts).toEqual([]);
});
test('review keeps missing fact unknown, separates demo and exposes old correction snapshot',async({page})=>{
 const state=await install(page);await page.goto('/dashboard');const review=page.getByTestId('forecast-review');await expect(review).toContainText('SYNTHETIC / TEST');await review.locator('summary').filter({hasText:'Сравнить блюда и период'}).click();
 await expect(review).toContainText('Нет строки продаж');const table=review.locator('table').first();await expect(table.locator('tbody tr').first().locator('td').nth(3)).toHaveText('—');
 await review.getByLabel('Версия сверки',{exact:true}).selectOption('old-review');await expect(review).toContainText('Версия закрытия: 1');await expect(table.locator('tbody tr').first().locator('td').nth(3)).toHaveText('0');expect(state.posts).toEqual([]);
 await review.getByRole('button',{name:'Сохранить текущую сверку',exact:true}).click();await expect(review).toContainText('Сверка сохранена');expect(state.posts).toHaveLength(1);expect(state.posts[0].path).toBe('/forecast-review/refresh');
});
test('task read receipt is explicit, survives refresh and does not resolve the cause',async({page})=>{
 const state=await install(page);await page.goto('/dashboard');const tasks=page.getByTestId('workday-tasks');await expect(tasks.getByTestId('task-DAY_NEEDS_CLOSE')).toHaveCount(1);expect(state.posts).toEqual([]);
 await tasks.getByRole('button',{name:'Отметить просмотренным',exact:true}).click();await expect(tasks).toContainText('Просмотрено, причина ещё есть');await tasks.getByRole('button',{name:'Обновить',exact:true}).click();await expect(tasks.getByTestId('task-DAY_NEEDS_CLOSE')).toHaveCount(1);await expect(tasks).toContainText('Просмотрено, причина ещё есть');expect(state.posts).toHaveLength(1);
});
test('failed task read retains known dashboard risks until an explicit successful retry',async({page})=>{
 const state=await install(page);let unavailable=true;
 await page.route('**/api/v1/dashboard?**',route=>route.fulfill({json:{as_of:'2025-12-31',data_origin:'SYNTHETIC',inventory_known:true,inventory_date:target,latest_forecast:forecast,latest_plans:[{id:'known-purchase',forecast_id:forecastId,target_date:target,status:'ready',input_freshness:'unchanged',shortage_count:2,total_cost:'10000'}],warnings:[],history:[],top_meals:[]}}));
 await page.route('**/api/v1/workday-tasks?**',route=>unavailable?route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE'}}}):route.fallback());
 await page.goto('/dashboard');const attention=page.locator('.day-attention');
 await expect(attention.getByRole('alert')).toContainText('Задачи дня не загрузились');
 await expect(attention).toContainText('Есть дефицит: 2 позиций');await expect(attention).toContainText('Закупка ждёт решения');
 await expect(attention.getByRole('button',{name:'Посмотреть дефицит',exact:true})).toBeEnabled();
 await expect(page.getByTestId('workday-tasks')).toHaveCount(0);expect(state.posts).toEqual([]);
 unavailable=false;await attention.getByRole('button',{name:'Повторить',exact:true}).click();
 await expect(page.getByTestId('task-DAY_NEEDS_CLOSE')).toHaveCount(1);
 await expect(attention.getByRole('alert')).toHaveCount(0);await expect(attention.locator('.day-task-list')).toHaveCount(0);expect(state.posts).toEqual([]);
});
test('saved baseline explanation uses original dates and mobile KK layout has no page overflow',async({page})=>{
 await install(page,{lang:'kk'});await page.setViewportSize({width:390,height:844});await page.goto(planUrl);await page.getByTestId('forecast-explanation').locator('summary').first().click();await expect(page.getByTestId('forecast-explanation')).toContainText('25.12.2025');
 await expect(working(page)).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.goto('/dashboard');await expect(page.getByTestId('workday-tasks')).toContainText('Өзекті міндеттер');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
test('HGB explanation keeps saved zero and missing features independent of current sales',async({page})=>{
 await install(page);const salesReads:string[]=[];page.on('request',request=>{if(new URL(request.url()).pathname==='/api/v1/sales')salesReads.push(request.url())});
 // The separate history chart reads current sales. Those values must not become
 // the saved inputs of the explanation, and opening it must not fetch sales again.
 await page.route('**/api/v1/sales?**',route=>route.fulfill({json:{items:[{branch_id:'1',meal_id:'meal-a',date:'2025-12-31',units_sold:999}],total:1,next_cursor:null}}));
 await page.route('**/api/v1/forecasts/'+forecastId,route=>route.fulfill({json:{...forecast,model:'hist_gradient_boosting',metadata:{...forecast.metadata,features:['lag_1','promo','temperature_forecast_c']},explanation:{source:'saved_job_snapshot',model:'hist_gradient_boosting',origin:'2025-12-31',target_date:target,rows:[{meal_id:'meal-a',basis:null,history:[{date:'2025-12-31',units_sold:0}],features:{lag_1:0,promo:0,temperature_forecast_c:null}}]}}}));
 await page.goto(planUrl);await expect(page.getByTestId('forecast-time-chart').locator('[data-series="observed"]')).toHaveAttribute('aria-label',/999/);
 const readsBeforeExplanation=salesReads.length;expect(readsBeforeExplanation).toBeGreaterThan(0);
 const explanation=page.getByTestId('forecast-explanation');await explanation.locator('summary').first().click();await explanation.getByText('Сохранённые значения, использованные в расчёте',{exact:true}).click();
 await expect(explanation.getByLabel('Блюдо для объяснения',{exact:true})).toHaveValue('meal-a');
 const table=explanation.locator('table').first();await expect(table.getByRole('row').filter({hasText:'Продажи 1 день назад'}).locator('td').nth(1)).toHaveText('0');await expect(table.getByRole('row').filter({hasText:'temperature_forecast_c'}).locator('td').nth(1)).toHaveText('—');
 await expect(explanation.locator('table').last().locator('tbody tr td').last()).toHaveText('0');await expect(explanation).not.toContainText('999');expect(salesReads).toHaveLength(readsBeforeExplanation);await expect(explanation).toContainText('не доказывает его причинное влияние');
});
test('working reason draft can only be discarded explicitly before leaving the saved variant',async({page})=>{
 const state=await install(page);await page.goto(planUrl);await explainSelection(page);await page.locator('.app-nav .app-nav-item').first().click();await expect(page.getByRole('dialog')).toContainText('Несохранённые изменения');await page.getByRole('button',{name:'Остаться в плане',exact:true}).click();await expect(working(page).getByLabel('Поясните решение',{exact:true})).toHaveValue('Ожидаем гостей по предварительной записи');
 await page.locator('.app-nav .app-nav-item').first().click();await page.getByRole('button',{name:'Отменить изменения и перейти',exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/);expect(state.posts).toEqual([]);
});
