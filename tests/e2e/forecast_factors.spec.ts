import {test,expect,type Page} from '@playwright/test';

// Synthetic browser contract for day factors: the twenty datasets are visible per branch,
// the factor model is selectable, and a forecast shows which factors it used and why others
// were skipped. It is not evidence of forecast quality.
const catalogue=[
 ['public_holiday','calendar','flag',730,'1'],['transferred_day_off','calendar','flag',730,'0'],['working_weekend','calendar','flag',730,'0'],
 ['pre_holiday','calendar','flag',730,'0'],['nauryz','culture','flag',730,'0'],['ramadan','culture','flag',730,'0'],
 ['iftar_minutes','culture','number',59,null],['ait','culture','flag',730,'0'],['school_holiday','school','flag',730,'1'],
 ['payday','economy','flag',730,'0'],['temperature_forecast_c','weather','number',730,'-9.9'],['precipitation_mm','weather','number',0,null],
 ['heat_alert','weather','flag',730,'0'],['sunset_minutes','weather','number',730,'1026'],['station_trains','traffic','number',0,null],
 ['office_occupancy_pct','traffic','number',0,null],['is_open','operations','flag',730,'1'],
].map(([code,group,kind,days,target])=>({code,group,kind,days,target_value:target,origin:'day_factors',sparse:code==='iftar_minutes',
 name:{kk:'KK '+code,ru:'Фактор '+code},source_hint:'Synthetic source note',first_date:days?'2024-01-01':null,last_date:days?'2026-01-01':null}))
 .concat(['menu_price_ratio','promo','stockout_recent'].map(code=>({code,group:'operations',kind:'number',days:0,target_value:null,origin:'daily_sales',
  sparse:false,name:{kk:'KK '+code,ru:'Фактор '+code},source_hint:'daily_sales',first_date:null,last_date:null})));

async function install(page:Page){
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 const context={version:1,mode:'synthetic_demo',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',branch_id:'1',history_start:'2024-01-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:'2026-01-01',source:null};
 const metadata={features:['meal_category','public_holiday'],factor_model:{
  used:catalogue.filter(item=>item.origin==='day_factors'&&item.days>=730).map(item=>({code:item.code,coverage:1,target_value:item.target_value===null?null:Number(item.target_value)})).concat([{code:'iftar_minutes',coverage:0.0807,target_value:null}]),
  skipped:[{code:'precipitation_mm',reason:'no_data',coverage:0},{code:'station_trains',reason:'no_data',coverage:0},{code:'office_occupancy_pct',reason:'no_data',coverage:0}],
  derived:['menu_price_ratio','promo','stockout_recent'],assumptions:['TARGET_PRICE_LAST_KNOWN','TARGET_PROMO_ASSUMED_NONE'],min_coverage:0.9}};
 const forecast={id:'factor-forecast',branch_id:'1',model:'hist_gradient_boosting_factors',target_date:'2026-01-01',forecast_origin:'2025-12-31',created_at:'2026-01-01T05:00:00Z',data_origin:'SYNTHETIC',input_freshness:'unchanged',
  predictions:[{meal_id:'meal-1',meal_name:'Бешбармак',point_forecast:42,p10:30,p50:41,p90:55}],
  metrics:[{model:'hist_gradient_boosting',mae:4.2,rmse:5,wape:0.21,bias:0.1,coverage:0.81,n_observations:336},{model:'hist_gradient_boosting_factors',mae:3.61,rmse:4.4,wape:0.18,bias:0.05,coverage:0.83,n_observations:336}],
  metadata};
 const requests:string[]=[];
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  requests.push(path+url.search);
  if(request.method()!=='GET')return route.fulfill({status:400,json:{detail:{code:'FIXTURE_UNEXPECTED_MUTATION'}}});
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'manager',organization_id:'factors',email:'manager@example.invalid',role:'manager',branch_ids:['1']},csrf_token:'synthetic-test-only'};
  if(path==='/settings')json={organization:{id:'factors',name:'Synthetic factors',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:1,data_policy:'synthetic_only'},data_context:context};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Вокзал · SYNTHETIC'}],total:1};
  if(path==='/factors')json={items:catalogue,branch_id:'1',target_date:url.searchParams.get('target_date'),min_coverage:0.9};
  if(path==='/forecasts')json={items:[forecast],total:1};
  if(path==='/forecasts/'+forecast.id)json=forecast;
  if(path==='/meals')json={items:[{meal_id:'meal-1',meal_name:'Бешбармак'}],total:1};
  await route.fulfill({json});
 });
 return requests;
}

test('data page lists the twenty datasets with branch coverage and empty ones stay visible',async({page})=>{
 const requests=await install(page);await page.goto('/data');
 const section=page.getByRole('region',{name:'Факторы прогноза · 20 датасетов',exact:true});
 await expect(section.locator('.factor-group li')).toHaveCount(20);
 await expect(section.locator('.factor-summary')).toContainText('14 загружено · 3 из истории продаж · 3 ждут данных');
 await expect(section.locator('li',{hasText:'Фактор station_trains'})).toContainText('Нет данных');
 await expect(section.locator('li',{hasText:'Фактор public_holiday'})).toContainText('День прогноза: Да');
 await expect(section.locator('li',{hasText:'Фактор temperature_forecast_c'})).toContainText(/-9[.,]9 °C/);
 expect(requests).toContain('/factors?branch_id=1&target_date=2026-01-01');
 await section.getByRole('button',{name:'Загрузить CSV факторов'}).click();
 await expect(page).toHaveURL(/\/imports\?kind=day_factors$/);
 await expect(page.getByLabel('Данные',{exact:true})).toHaveValue('day_factors');
});

test('forecast shows the factors it used, those it skipped and its target-day assumptions',async({page})=>{
 await install(page);await page.goto('/forecasts');
 await page.locator('.planning-options>summary').click();
 await expect(page.getByLabel('Модель',{exact:true}).locator('option')).toHaveText(['Такой же день прошлой недели','Среднее за последние 28 дней','Модель на истории продаж · HGB','Модель с факторами · HGB + 20 датасетов']);
 await page.keyboard.press('Escape');
 await page.goto('/forecasts/factor-forecast');
 const chip=page.locator('.forecast-factors-disclosure');
 await chip.locator('summary').click();
 const sheet=page.getByRole('dialog',{name:'Факторы прогноза',exact:true});
 await expect(sheet).toBeVisible();
 await expect(sheet.locator('.factor-table tbody tr')).toHaveCount(14+3);
 await expect(sheet.locator('.factor-table tbody tr',{hasText:'Фактор public_holiday'})).toContainText('Да');
 await expect(sheet.locator('.factor-skipped li')).toHaveText(['Фактор precipitation_mmДанные не загружены','Фактор station_trainsДанные не загружены','Фактор office_occupancy_pctДанные не загружены']);
 await expect(sheet.locator('.factor-assumptions')).toContainText('последняя известная');
 await expect(sheet.locator('.factor-assumptions')).toContainText('без акции');
 await page.keyboard.press('Escape');await expect(chip).not.toHaveAttribute('open','');
 await expect(chip.locator('summary')).toBeFocused();
});
