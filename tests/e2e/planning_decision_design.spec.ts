import {test,expect,type Page} from '@playwright/test';

// Artificial browser fixtures for the existing scoped audit contract. No business data.
const plan={id:'approved-design-plan',branch_id:'1',forecast_id:'source-forecast',version:2,status:'approved',created_at:'2026-01-01T07:00:00+00:00',target_date:'2026-01-01',strategy:'point',budget:'150000',total_cost:'14000',remaining_budget:'136000',shortage_count:0,constraints_valid:true,solver_status:'optimal',requirements:[],lines:[],input_freshness:'unchanged',data_origin:'SYNTHETIC'};
const approvedEvent={id:'approval-event',branch_id:'1',entity_id:plan.id,action:'plan.approved',actor_id:'other-actor-id',created_at:'2026-01-02T10:15:00+00:00',details:{version:2,reason:'Artificial fixture reviewed'}};

async function install(page:Page,language:'kk'|'ru'){
 await page.addInitScript(lang=>localStorage.setItem('asboljam-language',lang),language);
 const state={fail:false,pages:{'0':{items:[approvedEvent],next_cursor:null as string|null}} as Record<string,{items:any[];next_cursor:string|null}>,requests:[] as {path:string;method:string;query:string}[]};
 await page.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname.replace('/api/v1','');
  state.requests.push({path,method:route.request().method(),query:url.search});
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'decision-viewer',organization_id:'design-organization',email:'viewer@example.invalid',role:'analyst',branch_ids:['1','2']},csrf_token:'fixture-only'};
  if(path==='/settings')json={organization:{id:'design-organization',name:'SYNTHETIC design fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:2,data_policy:'synthetic_only'}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'First fixture branch'},{branch_id:'2',branch_name:'Second fixture branch'}],total:2};
  if(path==='/plans/'+plan.id)json=plan;
  if(path==='/plans')json={items:url.searchParams.get('branch_id')==='2'?[]:[plan],total:1};
  if(path==='/forecasts')json={items:url.searchParams.get('branch_id')==='2'?[]:[{id:'source-forecast',target_date:'2026-01-01',model:'seasonal_naive_7',data_origin:'SYNTHETIC'}],total:1};
  if(path==='/forecasts/source-forecast')json={id:'source-forecast',branch_id:'1',target_date:'2026-01-01',forecast_origin:'2025-12-31',model:'seasonal_naive_7',predictions:[],input_freshness:'unchanged',data_origin:'SYNTHETIC'};
  if(path==='/audit'){
   if(state.fail)return route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE',message:'Fixture unavailable'}}});
   const part=state.pages[url.searchParams.get('cursor')||'0']||{items:[],next_cursor:null};json={...part,total:part.items.length};
  }
  await route.fulfill({json});
 });
 return state;
}

for(const language of ['kk','ru'] as const)test(`${language}: approved plan identifies the actual audit actor and time and offers its stored export`,async({page})=>{
 const state=await install(page,language);await page.goto('/procurement/'+plan.id);
 const receipt=page.getByRole('region',{name:language==='kk'?'Жоспар бойынша шешім':'Решение по плану'});
 await expect(receipt).toContainText('other-actor-id');
 await expect(receipt.locator('time')).toHaveAttribute('datetime',approvedEvent.created_at);
 await expect(receipt.locator('time')).toContainText('15:15');await expect(receipt.locator('time')).toContainText('Asia/Qyzylorda');
 await expect(receipt).toContainText('Artificial fixture reviewed');
 await expect(receipt).not.toContainText('viewer@example.invalid');
 await expect(receipt.getByRole('link',{name:language==='kk'?'Сатып алу тізімін жүктеу':'Скачать список закупки',exact:true})).toHaveAttribute('href','/api/v1/plans/'+plan.id+'/export');
 expect(state.requests.filter(row=>row.path==='/audit')).toHaveLength(1);
 expect(state.requests.find(row=>row.path==='/audit')!.query).toContain('branch_id=1');
 expect(state.requests.filter(row=>row.path==='/users'||row.method!=='GET')).toEqual([]);
 await page.setViewportSize({width:390,height:844});await expect(receipt).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('receipt checks entity branch action and version, and continues older audit pages explicitly',async({page})=>{
 const state=await install(page,'ru');
 state.pages={'0':{items:[{...approvedEvent,entity_id:'unrelated-plan'},{...approvedEvent,branch_id:'2'},{...approvedEvent,action:'plan.rejected'},{...approvedEvent,details:{version:1}}],next_cursor:'200'},'200':{items:[approvedEvent],next_cursor:null}};
 await page.goto('/procurement/'+plan.id);const receipt=page.getByRole('region',{name:'Решение по плану'});
 await expect(receipt).toContainText('запись утверждения этой версии пока не найдена');
 await expect(receipt.locator('time')).toHaveCount(0);
 expect(state.requests.filter(row=>row.path==='/audit')).toHaveLength(1);
 await receipt.getByRole('button',{name:'Продолжить поиск в журнале',exact:true}).click();
 await expect(receipt).toContainText('other-actor-id');await expect(receipt.locator('time')).toHaveAttribute('datetime',approvedEvent.created_at);
 expect(state.requests.filter(row=>row.path==='/audit').map(row=>new URLSearchParams(row.query).get('cursor'))).toEqual(['0','200']);
});

test('unavailable or missing audit remains unknown and never substitutes calculation time',async({page})=>{
 const state=await install(page,'ru');state.fail=true;
 await page.goto('/procurement/'+plan.id);const receipt=page.getByRole('region',{name:'Решение по плану'});
 await expect(receipt).toContainText('Сейчас не удалось загрузить автора и время из журнала');
 await expect(receipt.locator('time')).toHaveCount(0);
 await expect(receipt.getByRole('link',{name:'Скачать список закупки',exact:true})).toBeVisible();
 state.fail=false;state.pages['0']={items:[],next_cursor:null};
 await receipt.getByRole('button',{name:'Повторить загрузку сведений',exact:true}).click();
 await expect(receipt).toContainText('не удалось установить автора и время этой версии');
 await expect(receipt.locator('time')).toHaveCount(0);
 await expect(receipt).not.toContainText('01.01.2026');
 await expect(page.locator('.context-line')).toContainText('Утверждён');
 expect(state.requests.filter(row=>row.method!=='GET')).toEqual([]);
});

test('own decision uses authenticated identity and a missing timestamp stays unavailable',async({page})=>{
 const state=await install(page,'ru');state.pages['0']={items:[{...approvedEvent,actor_id:'decision-viewer',created_at:null}],next_cursor:null};
 await page.goto('/procurement/'+plan.id);const receipt=page.getByRole('region',{name:'Решение по плану'});
 await expect(receipt).toContainText('Вы · viewer@example.invalid');
 await expect(receipt).toContainText('Код пользователя: decision-viewer');
 await expect(receipt).toContainText('Сведения о времени недоступны');
 await expect(receipt.locator('time')).toHaveCount(0);
 expect(state.requests.filter(row=>row.path==='/users')).toEqual([]);
});

test('planning list filters survive list detail back and reset when the branch changes',async({page})=>{
 await install(page,'ru');await page.goto('/forecasts');
 await page.locator('.planning-history-disclosure>summary').click();
 await page.getByLabel('По дате прогноза',{exact:true}).fill('2026-01-01');
 await page.getByRole('button',{name:'Прогноз на 01.01.2026',exact:true}).click();
 await page.getByRole('button',{name:'Посмотреть всё',exact:true}).click();
 await expect(page.getByLabel('По дате прогноза',{exact:true})).toHaveValue('2026-01-01');
 await page.getByLabel('Филиал',{exact:true}).selectOption('2');
 await expect(page.getByLabel('По дате прогноза',{exact:true})).toHaveValue('');
 await page.getByLabel('Филиал',{exact:true}).selectOption('1');
 await page.locator('.sidebar').getByRole('button',{name:'Закупки',exact:true}).click();
 await page.locator('.planning-history-disclosure>summary').click();
 await page.getByRole('combobox',{name:'Статус',exact:true}).selectOption('approved');
 await page.getByRole('button',{name:'Закупка на 01.01.2026',exact:true}).click();
 await page.goBack();
 await expect(page.getByRole('combobox',{name:'Статус',exact:true})).toHaveValue('approved');
 await page.getByLabel('Филиал',{exact:true}).selectOption('2');
 await expect(page.locator('.planning-history select')).toHaveValue('');
 await expect(page.locator('.planning-history-disclosure')).not.toHaveAttribute('open','');
});
