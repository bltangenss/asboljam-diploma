import {test,expect,type Page} from '@playwright/test';

// Browser behavior only: deterministic API replies, no enterprise data or live calculation.
async function install(page:Page,language='kk',kind='forecast') {
 await page.addInitScript(lang=>localStorage.setItem('asboljam-language',lang),language);
 const state={status:'queued',heartbeat_at:null as number|null,started_at:null as number|null,
  observed_at:1000,result_id:null as string|null,error:null as string|null,fail:false,gets:0,posts:0};
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace('/api/v1','');
  if(path==='/session/me')return route.fulfill({json:{user:{id:'status-user',organization_id:'status-org',email:'status@example.invalid',role:'manager',branch_ids:['1']},csrf_token:'fake-status-csrf'}});
  if(path==='/settings')return route.fulfill({json:{organization:{id:'status-org',name:'SYNTHETIC fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'test_fixture'},onboarding:{branch_count:1,data_policy:'synthetic_only'}}});
  if(path==='/branches')return route.fulfill({json:{items:[{branch_id:'1',branch_name:'Test branch'}],total:1}});
  if((path==='/forecasts'||path==='/procurement')&&route.request().method()==='POST') {
   state.posts++;return route.fulfill({status:202,json:{run_id:'job-status-fixture',status:'queued'}});
  }
  if(path==='/runs/job-status-fixture') {
   state.gets++;
   if(state.fail)return route.abort('failed');
   return route.fulfill({json:{id:'job-status-fixture',run_id:'job-status-fixture',kind,...state}});
  }
  if(path==='/forecasts'&&kind==='procurement')return route.fulfill({json:{items:[{id:'input-forecast',model:'seasonal_naive_7',target_date:'2026-01-01'}],total:1}});
  if(path==='/forecasts/saved-result')return route.fulfill({json:{id:'saved-result',branch_id:'1',model:'seasonal_naive_7',target_date:'2026-01-01',predictions:[],data_origin:'SYNTHETIC'}});
  return route.fulfill({json:{items:[],total:0,next_cursor:null}});
 });
 await page.goto(kind==='forecast'?'/forecasts':'/procurement');
 await page.getByRole('button',{name:language==='kk'?'Есептеу':'Рассчитать',exact:true}).click();
 return state;
}

test('queue and delayed heartbeat are translated, accessible and never claim percentage progress',async({page})=>{
 const state=await install(page);
 const panel=page.getByRole('region',{name:'Есептеу күйі'});
 await expect(panel.getByRole('status')).toHaveText('Кезекте күтіп тұр');
 await expect(page.getByRole('button',{name:'Есептеу',exact:true})).toBeDisabled();
 state.status='running';state.started_at=800;state.heartbeat_at=850;
 await expect(panel.getByRole('status')).toHaveText('Есептелуде');
 await expect(panel).toContainText('150 секунд болды');
 await expect(panel).toContainText('Өңдеушіден жауап кешігуде');
 await expect(panel).not.toContainText('%');
 expect(state.posts).toBe(1);
 await page.screenshot({path:'.cache/job-status-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await expect(panel).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'.cache/job-status-mobile.png',fullPage:true});
});

test('Russian status handles missing pulse and uses server time rather than client clock',async({page})=>{
 const state=await install(page,'ru');
 const panel=page.getByRole('region',{name:'Состояние расчёта'});
 state.status='running';state.started_at=900;
 await expect(panel).toContainText('Нет данных о последнем ответе обработчика');
 state.heartbeat_at=998;
 await expect(panel).toContainText('2 сек. назад');
 await expect(panel).not.toContainText('Ответ обработчика задерживается');
 expect(state.posts).toBe(1);
});

test('lost polling response retries the same run and navigates to its saved result without a second POST',async({page})=>{
 const state=await install(page,'ru');
 state.fail=true;
 const panel=page.getByRole('region',{name:'Состояние расчёта'});
 await expect(panel).toContainText('Не удалось проверить состояние расчёта');
 const stoppedAt=state.gets;
 await page.waitForTimeout(1500);expect(state.gets).toBe(stoppedAt);
 await expect(page.getByRole('button',{name:'Рассчитать',exact:true})).toBeDisabled();
 state.fail=false;state.status='succeeded';state.result_id='saved-result';
 await panel.getByRole('button',{name:'Проверить состояние задачи'}).click();
 await expect(page).toHaveURL(/\/forecasts\/saved-result$/);
 expect(state.posts).toBe(1);
});

test('failed procurement stops polling and returns to parameters only on explicit dismissal',async({page})=>{
 const state=await install(page,'ru','procurement');
 state.status='failed';state.error='SOURCE_CONTEXT_CHANGED';
 const panel=page.getByRole('region',{name:'Состояние расчёта'});
 await expect(panel.getByRole('status')).toHaveText('Расчёт не выполнен');
 await expect(panel).toContainText('SOURCE_CONTEXT_CHANGED');
 const stoppedAt=state.gets;
 await page.waitForTimeout(1500);expect(state.gets).toBe(stoppedAt);
 await panel.getByRole('button',{name:'Вернуться к параметрам'}).click();
 await expect(panel).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Рассчитать',exact:true})).toBeEnabled();
 expect(state.posts).toBe(1);
});

test('success without a result id is recoverable and never opens a null result',async({page})=>{
 const state=await install(page,'ru');state.status='succeeded';
 const panel=page.getByRole('region',{name:'Состояние расчёта'});
 await expect(panel).toContainText('Не удалось проверить состояние расчёта');
 await expect(page).toHaveURL(/\/forecasts$/);
 state.result_id='saved-result';
 await panel.getByRole('button',{name:'Проверить состояние задачи'}).click();
 await expect(page).toHaveURL(/\/forecasts\/saved-result$/);
 expect(state.posts).toBe(1);
});
