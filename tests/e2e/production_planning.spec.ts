import {test,expect,type Page} from '@playwright/test';

// Browser contract fixtures: real validation/transactions are covered by API and live tests.
const forecastId='cooking-forecast';
const baseForecast={id:forecastId,branch_id:'1',model:'rolling_mean_28',target_date:'2026-01-01',forecast_origin:'2025-12-31',input_freshness:'unchanged',data_origin:'SYNTHETIC',predictions:[{meal_id:'meal-a',meal_name:'Бауырдақ',point_forecast:10.2,p10:null,p50:null,p90:null},{meal_id:'meal-b',meal_name:'Сорпа',point_forecast:0,p10:null,p50:null,p90:null}]};
const origin={data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',source:null};
const saved=(id='cooking-one')=>({id,branch_id:'1',forecast_id:forecastId,target_date:'2026-01-01',name:'Утренний план',reason:'Проверено управляющим',actor_id:'manager',created_at:'2026-10-14T18:00:00Z',basis:'manual_portions',input_freshness:'unchanged',...origin,execution_context:origin,portions:[{meal_id:'meal-a',meal_name:'Бауырдақ',forecast_point:10.2,portions:15},{meal_id:'meal-b',meal_name:'Сорпа',forecast_point:0,portions:0}]});
type FixtureOptions={role?:string;freshness?:string;existing?:boolean;foreign?:boolean;lost?:boolean};
async function install(page:Page,options:FixtureOptions={}){
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 const forecast={...baseForecast,input_freshness:options.freshness||'unchanged'};
 const docs:any[]=options.existing?[{...saved(),branch_id:options.foreign?'2':'1',input_freshness:forecast.input_freshness}]:[];
 const mutations:{path:string;body:any;key:string|undefined}[]=[];
 const receipts=new Map<string,any>();let lost=false;
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  let json:any={items:[],total:0,next_cursor:null};
  if(request.method()==='POST'){
   const body=request.postDataJSON(),key=request.headers()['idempotency-key'];mutations.push({path,body,key});
   if(path==='/production-plans'){
    if(!key)return route.fulfill({status:400,json:{detail:{code:'IDEMPOTENCY_REQUIRED'}}});
    if(!receipts.has(key)){
     const document={...saved('cooking-'+(docs.length+1)),name:body.name,reason:body.reason,portions:body.portions.map((p:any)=>({...p,meal_name:baseForecast.predictions.find(row=>row.meal_id===p.meal_id)?.meal_name,forecast_point:baseForecast.predictions.find(row=>row.meal_id===p.meal_id)?.point_forecast}))};
     docs.unshift(document);receipts.set(key,document);
    }
    if(options.lost&&!lost){lost=true;return route.abort('failed')}
    return route.fulfill({status:201,json:receipts.get(key)});
   }
   return route.fulfill({status:422,json:{detail:{code:'BUDGET_INVALID',message:'Artificial refusal after request capture'}}});
  }
  if(path==='/session/me')json={user:{id:'manager',organization_id:'production-fixture',email:'manager@example.invalid',role:options.role||'manager',branch_ids:['1','2']},csrf_token:'artificial-production-csrf'};
  if(path==='/settings')json={organization:{id:'production-fixture',name:'Artificial cooking fixture',status:'active',data_policy:'synthetic_only',timezone:origin.timezone,currency:'KZT'},onboarding:{branch_count:2,data_policy:'synthetic_only'},data_context:{version:1,mode:'synthetic_fixed',...origin,branch_id:url.searchParams.get('branch_id')||'1',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:null}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'SYNTHETIC one'},{branch_id:'2',branch_name:'SYNTHETIC two'}],total:2};
  if(path==='/meals')json={items:baseForecast.predictions.map(row=>({meal_id:row.meal_id,meal_name:row.meal_name})),total:2};
  if(path==='/forecasts')json={items:[forecast],total:1,next_cursor:null};
  if(path==='/forecasts/'+forecastId)json=forecast;
  if(path==='/production-plans')json={items:docs.filter(row=>row.branch_id===(url.searchParams.get('branch_id')||'1')),total:docs.length,next_cursor:null};
  if(path.startsWith('/production-plans/')){
   const document=docs.find(row=>row.id===path.split('/').at(-1));
   if(!document)return route.fulfill({status:404,json:{detail:{code:'NOT_FOUND'}}});
   json=document;
  }
  if(path==='/stock/ledger')json={ledger:null,version:null,baseline_freshness:'unknown',context_freshness:'unchanged',public_context:origin};
  if(path==='/stock/catalog')json={ingredients:[],meals:[],...origin};
  await route.fulfill({json});
 });
 return {docs,mutations,receipts};
}
const editor=(page:Page)=>page.getByTestId('production-editor');
const area=(page:Page)=>page.getByTestId('production-planning');
async function describe(page:Page){await editor(page).getByLabel('Название варианта',{exact:true}).fill('Обед без супа');await editor(page).getByLabel('Почему выбраны эти порции',{exact:true}).fill('Ожидаем заказ группы, суп сегодня не готовим');}

test('manual draft starts empty, explicit ceiling and zero are saved separately from the forecast',async({page})=>{
 const state=await install(page);await page.goto('/forecasts/'+forecastId);
 const portions=area(page).getByRole('spinbutton');await expect(portions).toHaveCount(2);await expect(portions.nth(0)).toHaveValue('');await expect(portions.nth(1)).toHaveValue('');
 await describe(page);await expect(editor(page).getByRole('button',{name:'Сохранить новый вариант',exact:true})).toBeDisabled();
 await editor(page).getByRole('button',{name:'Заполнить прогнозом с округлением вверх',exact:true}).click();await expect(portions.nth(0)).toHaveValue('11');await expect(portions.nth(1)).toHaveValue('0');
 await portions.nth(0).fill('15');await editor(page).getByRole('button',{name:'Сохранить новый вариант',exact:true}).click();
 await expect(page.getByTestId('production-saved')).toContainText('Обед без супа');
 expect(state.mutations).toHaveLength(1);expect(state.mutations[0]).toMatchObject({path:'/production-plans',body:{branch_id:'1',forecast_id:forecastId,name:'Обед без супа',reason:'Ожидаем заказ группы, суп сегодня не готовим',portions:[{meal_id:'meal-a',portions:15},{meal_id:'meal-b',portions:0}]}});expect(state.mutations[0].key).toBeTruthy();
 expect(baseForecast.predictions[0].point_forecast).toBe(10.2);
 await page.reload();await area(page).getByLabel('Сохранённый вариант',{exact:true}).selectOption(state.docs[0].id);await expect(page.getByTestId('production-saved')).toContainText('Обед без супа');
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('fractional and negative portions never submit; explicit all-zero plan is allowed',async({page})=>{
 const state=await install(page);await page.goto('/forecasts/'+forecastId);await describe(page);
 const portions=area(page).getByRole('spinbutton'),save=editor(page).getByRole('button',{name:'Сохранить новый вариант',exact:true});
 await portions.nth(0).fill('1.5');await portions.nth(1).fill('0');await expect(save).toBeDisabled();await portions.nth(0).fill('-1');await expect(save).toBeDisabled();expect(state.mutations).toEqual([]);
 await portions.nth(0).fill('0');await expect(save).toBeEnabled();await save.click();await expect(page.getByTestId('production-saved')).toBeVisible();expect(state.docs[0].portions.map((r:any)=>r.portions)).toEqual([0,0]);
});

test('lost save reply retains the same payload and idempotency key until confirmed',async({page})=>{
 const state=await install(page,{lost:true});await page.goto('/forecasts/'+forecastId);await describe(page);await editor(page).getByRole('button',{name:'Заполнить прогнозом с округлением вверх',exact:true}).click();await editor(page).getByRole('button',{name:'Сохранить новый вариант',exact:true}).click();
 const retry=area(page).getByRole('button',{name:'Повторить и проверить сохранение',exact:true});await expect(retry).toBeVisible();await expect(editor(page).getByLabel('Название варианта',{exact:true})).toBeDisabled();
 await retry.click();await expect(page.getByTestId('production-saved')).toBeVisible();expect(state.mutations).toHaveLength(2);expect(state.mutations[1]).toEqual(state.mutations[0]);expect(state.receipts.size).toBe(1);expect(state.docs).toHaveLength(1);
});

for(const options of [{role:'analyst'},{freshness:'changed'},{freshness:'unknown'}])test('saving is unavailable for '+JSON.stringify(options),async({page})=>{
 const state=await install(page,options);await page.goto('/forecasts/'+forecastId);await expect(area(page)).toBeVisible();
 const save=area(page).getByRole('button',{name:'Сохранить новый вариант',exact:true});if(await save.count())await expect(save).toBeDisabled();expect(state.mutations).toEqual([]);
});

test('manual procurement carries immutable variant and hides incompatible quantile choices',async({page})=>{
 const state=await install(page,{existing:true});await page.goto('/procurement?forecast='+forecastId+'&production_plan_id=cooking-one');
 await expect(page.getByRole('region',{name:'Основание плана приготовления',exact:true})).toContainText('Утренний план');
 await expect(page.getByLabel('Основание потребности',{exact:true})).toHaveValue('cooking-one');
 const strategy=page.getByLabel('Стратегия',{exact:true});if(await strategy.count())await expect(strategy).toBeHidden();
 await page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true}).click();
 await expect.poll(()=>state.mutations.length).toBe(1);expect(state.mutations[0]).toMatchObject({path:'/procurement',body:{branch_id:'1',forecast_id:forecastId,production_plan_id:'cooking-one',strategy:'point'}});
});

test('foreign carried variant cannot silently fall back to forecast procurement',async({page})=>{
 const state=await install(page,{existing:true,foreign:true});await page.goto('/procurement?forecast='+forecastId+'&production_plan_id=cooking-one');
 await expect(page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true})).toBeDisabled();expect(state.mutations).toEqual([]);await expect(page.getByLabel('Филиал',{exact:true})).toHaveValue('1');
});

for(const existing of [false,true])test(`unsaved ${existing?'copied variant':'new portions'} block continuation until explicit discard`,async({page})=>{
 const state=await install(page,{existing});await page.goto('/forecasts/'+forecastId+(existing?'?production_plan_id=cooking-one':''));
 const next=page.getByRole('button',{name:'Проверить остатки',exact:true});await expect(next).toBeEnabled();
 if(existing)await area(page).getByRole('button',{name:'Изменить и сохранить новым вариантом',exact:true}).click();
 await area(page).getByRole('spinbutton').first().fill('25');await expect(next).toBeDisabled();
 await expect(area(page).getByLabel('Сохранённый вариант',{exact:true})).toBeDisabled();
 await expect(area(page).getByRole('button',{name:'Посмотреть рецепты',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:'Остатки готовы — перейти к закупке',exact:true})).toBeDisabled();
 await area(page).getByRole('button',{name:'Отменить несохранённые изменения',exact:true}).click();await expect(next).toBeEnabled();expect(state.mutations).toEqual([]);
 if(existing){await expect(page.getByTestId('production-saved')).toContainText('Утренний план');expect(state.docs[0].portions[0].portions).toBe(15)}else await expect(area(page).getByRole('spinbutton').first()).toHaveValue('');
 await next.click();await expect(page).toHaveURL(new RegExp('/inventory\\?forecast='+forecastId+(existing?'&production_plan_id=cooking-one':'')+'$'));
});
