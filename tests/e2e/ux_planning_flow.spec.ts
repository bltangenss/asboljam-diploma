import {test,expect,type Page} from '@playwright/test';

// Synthetic browser contracts. These assertions exercise navigation and explicit
// decisions; they are not evidence of forecast quality or backend validation.
async function install(page:Page,language:'kk'|'ru'='ru',freshness='unchanged'){
 await page.addInitScript(lang=>localStorage.setItem('asboljam-language',lang),language);
 const context={version:1,mode:'synthetic_demo',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',branch_id:'1',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:true,operations_enabled:true,business_date:'2026-01-01',source:null};
 const forecast={id:'day-forecast',branch_id:'1',model:'seasonal_naive_7',target_date:'2026-01-01',forecast_origin:'2025-12-31',created_at:'2026-01-01T05:00:00Z',data_origin:'SYNTHETIC',input_freshness:freshness,predictions:[{meal_id:'meal-1',meal_name:'Бауырдақ',point_forecast:240,p10:null,p50:null,p90:null}]};
 const plan:any={id:'day-purchase',branch_id:'1',forecast_id:forecast.id,status:'ready',version:7,input_freshness:freshness,data_origin:'SYNTHETIC',target_date:'2026-01-01',total_cost:'1200',shortage_count:1,result:{target_date:'2026-01-01',strategy:'point',total_cost:'1200',budget:'2000',remaining_budget:'800',shortage_count:1,constraints_valid:true,solver_status:'optimal',lines:[{ingredient_id:'ingredient-1',ingredient_name:'Мука',supplier_id:'supplier-1',supplier_name:'Учебный поставщик',packs:2,pack_qty:'5',purchased_qty:'10',unit:'kg',line_cost_kzt:'1200'}],requirements:[{ingredient_id:'ingredient-1',ingredient_name:'Мука',unit:'kg',gross_required:'15',usable_stock:'2',purchased_qty:'10',shortage_qty:'3',excess_qty:'0'}],stock_evidence:{source:'counted_snapshot',target_date:'2026-01-01'},recipe_evidence:{source:'csv',recipe_versions:['fixture-v1']}}};
 const mutations:{path:string;body:any;idempotency:string|undefined}[]=[];
 const fixture={forecasts:[forecast] as any[],details:{[forecast.id]:forecast} as Record<string,any>,lookups:[] as string[]};
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  if(request.method()!=='GET'){
   mutations.push({path,body:request.postDataJSON(),idempotency:request.headers()['idempotency-key']});
   if(path==='/plans/day-purchase/approve'){plan.status='approved';plan.version=8;return route.fulfill({json:plan});}
   return route.fulfill({status:400,json:{detail:{code:'FIXTURE_UNEXPECTED_MUTATION'}}});
  }
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'manager',organization_id:'ux-planning',email:'manager@example.invalid',role:'admin',branch_ids:['1','2']},csrf_token:'synthetic-test-only'};
  if(path==='/settings')json={organization:{id:'ux-planning',name:'Учебная столовая',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:2,data_policy:'synthetic_only'},data_context:{...context,branch_id:url.searchParams.get('branch_id')||'1'}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Бауырдақ · SYNTHETIC'},{branch_id:'2',branch_name:'Second SYNTHETIC branch'}],total:2};
  if(path==='/forecasts')json={items:fixture.forecasts.filter(row=>row.branch_id===(url.searchParams.get('branch_id')||'1')),total:fixture.forecasts.length};
  if(path.startsWith('/forecasts/')){
   const key=decodeURIComponent(path.slice('/forecasts/'.length));fixture.lookups.push(key);
   if(!fixture.details[key])return route.fulfill({status:404,json:{detail:{code:'NOT_FOUND',message:'Synthetic unavailable forecast'}}});
   json=fixture.details[key];
  }
  if(path==='/plans')json={items:[plan],total:1};
  if(path==='/plans/'+plan.id)json=plan;
  if(path==='/meals')json={items:[{meal_id:'meal-1',meal_name:'Бауырдақ'}],total:1};
  if(path==='/audit')json={items:[{id:'decision',branch_id:'1',entity_id:plan.id,action:'plan.approved',actor_id:'manager',created_at:'2026-01-01T06:00:00Z',details:{version:8,reason:'Проверено управляющим'}}],total:1,next_cursor:null};
  await route.fulfill({json});
 });
 return {mutations,...fixture};
}

for(const lang of ['kk','ru'] as const)test(`${lang}: meal portions precede optional analysis and continue to exact forecast stock context`,async({page})=>{
 const state=await install(page,lang);await page.goto('/forecasts/day-forecast');
 await expect(page.getByText(lang==='ru'?'Прогноз порций — ориентир для приготовления. Это не утверждённый производственный план.':'Порция болжамы — дайындауға арналған бағдар. Бұл бекітілген өндірістік жоспар емес.',{exact:true})).toBeVisible();
 await expect(page.getByRole('cell',{name:'Бауырдақ',exact:true})).toBeVisible();
 const chart=page.locator('.planning-chart-disclosure');await expect(chart).not.toHaveAttribute('open','');
 await expect(page.getByTestId('input-provenance')).toBeVisible();
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('button',{name:lang==='ru'?'Проверить остатки':'Қалдықтарды тексеру',exact:true}).click();
 await expect(page).toHaveURL(/\/inventory\?forecast=day-forecast$/);
 expect(state.mutations).toEqual([]);
});

test('day planning offers an existing result while method and calculation history are on demand',async({page})=>{
 const state=await install(page);await page.goto('/forecasts');
 await expect(page.getByRole('button',{name:'Открыть прогноз дня',exact:true})).toBeVisible();
 await expect(page.getByLabel('Модель',{exact:true})).toBeHidden();
 await expect(page.locator('.planning-history-disclosure')).not.toHaveAttribute('open','');
 await expect(page.locator('.planning-runs-disclosure')).not.toHaveAttribute('open','');
 await page.locator('.planning-options>summary').click();
 await page.getByLabel('Модель',{exact:true}).selectOption('rolling_mean_28');
 await page.locator('.planning-history-disclosure>summary').click();
 await expect(page.getByLabel('По дате прогноза',{exact:true})).toBeVisible();
 expect(state.mutations).toEqual([]);
});

test('shortage and human decision stay visible while derivation is optional; approval retains version reason and acknowledgement',async({page})=>{
 const state=await install(page);await page.goto('/procurement/day-purchase');
 await expect(page.getByRole('region',{name:'Чего не хватит',exact:true})).toContainText('Мука');
 await expect(page.locator('.procurement-result').getByRole('cell',{name:'Мука',exact:true})).toBeVisible();
 const evidence=page.locator('.procurement-evidence');await expect(evidence).not.toHaveAttribute('open','');
 await expect(evidence.getByRole('cell',{name:'Мука',exact:true})).toBeHidden();
 await evidence.locator('summary').click();await expect(evidence.getByRole('cell',{name:'Мука',exact:true})).toBeVisible();
 await expect(evidence).toContainText('fixture-v1');
 await page.locator('.approval-panel').getByRole('button',{name:'Утвердить план',exact:true}).click();
 const dialog=page.getByRole('dialog');const confirm=dialog.getByRole('button',{name:'Утвердить план',exact:true});
 await expect(confirm).toBeDisabled();
 await dialog.locator('textarea').fill('Проверено управляющим');await expect(confirm).toBeDisabled();
 await dialog.getByRole('checkbox').check();await expect(confirm).toBeEnabled();
 expect(state.mutations).toEqual([]);
 await confirm.click();await expect(page.locator('.decision-receipt')).toBeVisible();
 expect(state.mutations).toHaveLength(1);
 expect(state.mutations[0].path).toBe('/plans/day-purchase/approve');
 expect(state.mutations[0].body).toEqual({expected_version:7,reason:'Проверено управляющим',acknowledge_shortage:true});
 expect(state.mutations[0].idempotency).toMatch(/^[a-f0-9-]{36}$/);
 await expect(page.locator('.decision-receipt')).toContainText('Заказ поставщику не отправлен');
});

test('changed inputs remain prominent and prevent approval even with collapsed evidence',async({page})=>{
 const state=await install(page,'ru','changed');await page.goto('/procurement/day-purchase');
 await expect(page.getByTestId('input-provenance')).toContainText('Исходные данные изменились');
 await expect(page.getByTestId('input-provenance')).toBeVisible();
 await expect(page.locator('.procurement-evidence')).not.toHaveAttribute('open','');
 await expect(page.locator('.approval-panel').getByRole('button',{name:'Утвердить план',exact:true})).toBeDisabled();
 expect(state.mutations).toEqual([]);
});

test('a carried forecast older than the first 200 options is explicitly loaded and used',async({page})=>{
 const state=await install(page),original=state.details['day-forecast'];
 state.forecasts.splice(0,1,...Array.from({length:200},(_,index)=>({...original,id:'recent-'+index})));
 state.details['older-forecast']={...original,id:'older-forecast',target_date:'2025-12-30'};
 await page.goto('/procurement?forecast=older-forecast');
 await expect(page.getByLabel('Прогноз',{exact:true})).toHaveValue('older-forecast');
 await expect(page.locator('.planning-preview .planning-date')).toHaveText('30.12.2025');
 const calculate=page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true});
 await expect(calculate).toBeEnabled();
 expect(state.lookups).toEqual(['older-forecast']);
 await calculate.click();await expect.poll(()=>state.mutations.length).toBe(1);
 expect(state.mutations[0].body.forecast_id).toBe('older-forecast');
 expect(state.mutations[0].body.branch_id).toBe('1');
});

test('same-page query changes replace the carried forecast without a stale selection',async({page})=>{
 const state=await install(page),original=state.details['day-forecast'];
 state.details['second-forecast']={...original,id:'second-forecast',target_date:'2025-12-30'};
 await page.goto('/procurement?forecast=day-forecast');
 await expect(page.getByLabel('Прогноз',{exact:true})).toHaveValue('day-forecast');
 await page.evaluate(()=>{history.pushState({},'','/procurement?forecast=second-forecast');dispatchEvent(new PopStateEvent('popstate'));});
 await expect(page.getByLabel('Прогноз',{exact:true})).toHaveValue('second-forecast');
 await expect(page.locator('.planning-preview .planning-date')).toHaveText('30.12.2025');
 await expect(page.getByLabel('Филиал',{exact:true})).toHaveValue('1');
 expect(state.mutations).toEqual([]);
});

test('a carried forecast from another branch clears the choice and cannot calculate or switch branch',async({page})=>{
 const state=await install(page);
 state.details['foreign-forecast']={...state.details['day-forecast'],id:'foreign-forecast',branch_id:'2'};
 await page.goto('/procurement?forecast=foreign-forecast');
 await expect(page.locator('.planning-form [role=alert]')).toContainText('Прогноз по ссылке относится к другому филиалу');
 await expect(page.getByLabel('Прогноз',{exact:true})).toHaveValue('');
 await expect(page.getByLabel('Филиал',{exact:true})).toHaveValue('1');
 await expect(page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true})).toBeDisabled();
 expect(state.mutations).toEqual([]);
});

test('an unavailable carried forecast stays empty and can be explicitly retried',async({page})=>{
 const state=await install(page);await page.goto('/procurement?forecast=unavailable');
 const warning=page.locator('.planning-form [role=alert]');await expect(warning).toContainText('Не удалось проверить прогноз по ссылке');
 await expect(page.getByLabel('Прогноз',{exact:true})).toHaveValue('');
 await expect(page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true})).toBeDisabled();
 state.details.unavailable={...state.details['day-forecast'],id:'unavailable'};
 await warning.getByRole('button').click();
 await expect(page.getByLabel('Прогноз',{exact:true})).toHaveValue('unavailable');
 await expect(page.locator('.planning-form-actions').getByRole('button',{name:'Рассчитать',exact:true})).toBeEnabled();
 expect(state.mutations).toEqual([]);
});
