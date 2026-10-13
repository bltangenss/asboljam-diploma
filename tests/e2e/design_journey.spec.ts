import {test,expect,type Page} from '@playwright/test';
import fs from 'node:fs';
const screenshots='.cache/design-visual';fs.mkdirSync(screenshots,{recursive:true});
// Artificial UI fixtures; visual references are not evidence of business savings.
async function install(page:Page,options:{sales?:boolean;forecast?:boolean;rejected?:boolean;stale?:boolean}={}){
 const context={version:1,mode:'real_business',data_origin:'REAL',usage_mode:'TEST',timezone:'Asia/Almaty',currency:'KZT',branch_id:'test',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2025-12-30',inventory_dates:['2025-12-30','2026-01-01'],dates_editable:true,operations_enabled:true,business_date:'2026-01-01',source:null};
 const forecast={id:'saved-forecast',target_date:'2026-01-01',input_freshness:options.stale?'changed':'unchanged'};
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace('/api/v1','');
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'fixture',email:'fixture@example.invalid',organization_id:'design',role:'admin',branch_ids:['test']},csrf_token:'fixture-only'};
  if(path==='/settings')json={organization:{id:'design',name:'Бауырдақ · тест',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'real_only',provenance:'fixture'},onboarding:{branch_count:1,can_import_branches:true,data_policy:'real_only'},data_context:{...context,branch_id:new URL(route.request().url()).searchParams.has('branch_id')?'test':null}};
  if(path==='/branches')json={items:[{branch_id:'test',branch_name:'Бауырдақ · Алматы'}],total:1};
  if(path==='/dashboard')json={as_of:options.sales===false?null:'2025-12-31',sold_portions:186,revenue:'325500',data_origin:'REAL',inventory_known:true,inventory_date:'2025-12-30',history:options.sales===false?[]:Array.from({length:28},(_,i)=>({date:'2025-12-'+String(i+4).padStart(2,'0'),units_sold:130+(i*17)%80})),top_meals:[{meal_name:'Бауырдақ',units_sold:98,revenue:'196000'},{meal_name:'Донер',units_sold:88,revenue:'129500'}],warnings:[{code:'EXPIRING_LOTS',count:2}],latest_forecast:options.forecast?forecast:null,latest_plans:options.rejected?[{id:'rejected-plan',forecast_id:forecast.id,target_date:forecast.target_date,status:'rejected',version:2,input_freshness:'unchanged',total_cost:'45000'}]:[]};
  if(path==='/forecasts')json={items:[{...forecast,model:'seasonal_naive_7'}],total:1};
  await route.fulfill({json});
 });
}

test('next action uses existing target snapshot even when another inventory date is selected',async({page})=>{
 await install(page,{forecast:true});await page.goto('/');
 const next=page.locator('.next-action');await expect(next).toContainText('Қажетті сатып алуды есептеңіз');
 await next.getByRole('button').click();await expect(page).toHaveURL(/\/procurement\?forecast=saved-forecast$/);
 await expect(page.getByLabel('Болжам',{exact:true})).toHaveValue('saved-forecast');
});

test('changed forecast and rejected plan lead to new calculations, not a false ready state',async({page})=>{
 await install(page,{forecast:true,stale:true});await page.goto('/');
 await expect(page.locator('.next-action')).toContainText('Қанша сатылатынын есептеңіз');
 await page.unrouteAll({behavior:'wait'});await install(page,{forecast:true,rejected:true});await page.reload();
 await expect(page.locator('.next-action')).toContainText('Алдыңғы жоспар қабылданбады');
 await page.locator('.next-action').getByRole('button').click();await expect(page).toHaveURL(/\/procurement\?forecast=/);
});

test('missing sales remains unknown instead of zero and offers a concrete import step',async({page})=>{
 await install(page,{sales:false});await page.goto('/');
 await expect(page.locator('.metric-value').first()).toHaveText('—');
 await expect(page.locator('.next-action')).toContainText('Сатылым тарихын қосыңыз');
 await page.locator('.next-action').getByRole('button').click();await expect(page).toHaveURL(/\/imports$/);
});

test('responsive dashboard keeps text action and context; mobile navigation traps and restores focus',async({page})=>{
 await install(page);await page.goto('/');
 for(const width of [1440,1024,768,390,360]){
  await page.setViewportSize({width,height:900});
  await expect(page.locator('.next-action').getByRole('button')).toBeVisible();
  await expect(page.locator('.context-tag')).toContainText('Бауырдақ · Алматы');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.screenshot({path:`${screenshots}/dashboard-${width}.png`,fullPage:true,animations:'disabled'});
 }
 const menu=page.getByRole('button',{name:'Мәзірді ашу',exact:true});
 await expect(page.locator('.sidebar')).toHaveAttribute('inert','');
 await menu.focus();await page.keyboard.press('Enter');
 const drawer=page.getByRole('dialog',{name:'Жұмыс мәзірі'});await expect(drawer).toBeVisible();
 const close=drawer.getByRole('button',{name:'Мәзірді жабу'});await expect(close).toBeFocused();
 await page.keyboard.press('Shift+Tab');await expect(drawer.getByRole('button',{name:'Шығу'})).toBeFocused();
 await page.keyboard.press('Tab');await expect(close).toBeFocused();
 await page.keyboard.press('Escape');await expect(menu).toBeFocused();await expect(page.locator('.sidebar')).toHaveAttribute('inert','');
 await page.locator('.language').click();await expect(page.locator('.next-action')).toContainText('Узнайте, сколько продастся');
 await page.screenshot({path:`${screenshots}/dashboard-ru-360.png`,fullPage:true,animations:'disabled'});
});

test('login remains readable in both languages at desktop and mobile widths',async({page})=>{
 await page.route('**/api/v1/session/me',route=>route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED'}}}));
 await page.goto('/login');
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:900});
  await expect(page.getByLabel('Электрондық пошта')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
  await page.screenshot({path:`${screenshots}/login-${width}.png`,fullPage:true,animations:'disabled'});
 }
 await page.getByRole('button',{name:'Тілді ауыстыру'}).click();await expect(page.getByRole('heading',{name:'Войти в систему'})).toBeVisible();
 await page.getByLabel('Пароль',{exact:true}).fill('fixture-not-a-secret');
 await page.getByRole('button',{name:'Показать пароль'}).click();await expect(page.getByLabel('Пароль',{exact:true})).toHaveAttribute('type','text');
 await page.getByRole('button',{name:'Скрыть пароль'}).click();await expect(page.getByLabel('Пароль',{exact:true})).toHaveAttribute('type','password');
});
