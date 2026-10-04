import {test,expect,type Page} from '@playwright/test';

// Browser behavior only: deterministic API replies, no enterprise data or live calculation.
async function install(page:Page,language='kk',kind='forecast') {
 await page.addInitScript(lang=>localStorage.setItem('asboljam-language',lang),language);
 const state={status:'queued',heartbeat_at:null as number|null,started_at:null as number|null,
  observed_at:1000,result_id:null as string|null,error:null as string|null,fail:false,gets:0,posts:0,
  history:[] as Record<string,unknown>[],historyFail:false,listQueries:[] as string[]};
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace('/api/v1','');
  if(path==='/session/me')return route.fulfill({json:{user:{id:'status-user',organization_id:'status-org',email:'status@example.invalid',role:'manager',branch_ids:['1']},csrf_token:'fake-status-csrf'}});
  if(path==='/settings')return route.fulfill({json:{organization:{id:'status-org',name:'SYNTHETIC fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'test_fixture'},onboarding:{branch_count:1,data_policy:'synthetic_only'}}});
  if(path==='/branches')return route.fulfill({json:{items:[{branch_id:'1',branch_name:'Test branch'}],total:1}});
  if(path==='/runs') {
   const query=new URL(route.request().url()).searchParams;state.listQueries.push(query.toString());
   if(state.historyFail)return route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE',message:'Unavailable'}}});
   const cursor=Number(query.get('cursor')||0),limit=Number(query.get('limit')||20);
   return route.fulfill({json:{items:state.history.slice(cursor,cursor+limit),total:state.history.length,
    next_cursor:cursor+limit<state.history.length?String(cursor+limit):null}});
  }
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

for(const kind of ['forecast','procurement'])test(`reload restores access to an existing ${kind} without creating another job`,async({page})=>{
 const state=await install(page,'ru',kind);state.status='running';state.heartbeat_at=990;
 state.history=[{id:'job-status-fixture',status:'running',created_at:'2026-01-01T10:00:00Z'}];
 await page.reload();
 const history=page.getByRole('region',{name:'История расчётов'});
 await expect(history).toContainText('Выполняется расчёт');
 await history.getByRole('button',{name:'Открыть задачу job-status-fixture'}).click();
 await expect(page.getByRole('region',{name:'Состояние расчёта'})).toContainText('10 сек. назад');
 await expect(page.getByRole('button',{name:'Рассчитать',exact:true})).toBeDisabled();
 expect(state.posts).toBe(1);
 expect(state.listQueries.every(query=>query.includes('branch_id=1')&&query.includes('kind='+kind))).toBe(true);
});

test('history paginates and refreshes errors without pretending the history is empty',async({page})=>{
 const state=await install(page,'ru');
 state.history=Array.from({length:21},(_,index)=>({id:'history-'+index,status:'succeeded',created_at:'2026-01-01T10:00:00Z'}));
 await page.reload();
 const history=page.getByRole('region',{name:'История расчётов'});
 await expect(history.getByRole('button',{name:'Открыть задачу',exact:false})).toHaveCount(20);
 await history.getByRole('button',{name:'Следующая страница'}).click();
 await expect(history.getByRole('button',{name:'Открыть задачу history-20',exact:true})).toBeVisible();
 await expect(history.getByRole('button',{name:'Следующая страница'})).toBeDisabled();
 state.historyFail=true;
 await history.getByRole('button',{name:'Обновить список'}).click();
 await expect(history.getByRole('alert')).toContainText('Не удалось получить список расчётов');
 await expect(history).not.toContainText('пока нет расчётов');
 state.historyFail=false;
 await history.getByRole('button',{name:'Обновить список'}).click();
 await expect(history.getByRole('button',{name:'Открыть задачу history-20',exact:true})).toBeVisible();
 await history.getByRole('button',{name:'Предыдущая страница'}).click();
 await expect(history.getByRole('button',{name:'Открыть задачу',exact:false})).toHaveCount(20);
 expect(state.posts).toBe(1);
});

test('saved successful forecast opens from history after reload',async({page})=>{
 const state=await install(page,'ru');
 state.history=[{id:'job-status-fixture',status:'succeeded',created_at:'2026-01-01T10:00:00Z'}];
 state.status='succeeded';state.result_id='saved-result';
 await page.reload();
 await page.getByRole('region',{name:'История расчётов'}).getByRole('button',{name:'Открыть задачу job-status-fixture'}).click();
 await expect(page).toHaveURL(/\/forecasts\/saved-result$/);
 expect(state.posts).toBe(1);
});
