import {test,expect,type Page,type Route} from '@playwright/test';

// These REAL-contract responses and rows are artificial TEST fixtures, never business evidence.
function fixture(id='real-test',branch='real-001') {
 return {id,branch,authenticated:true,session:1,
  context:{version:1,mode:'real_business',data_origin:'REAL',usage_mode:'TEST',timezone:'Asia/Almaty',currency:'KZT',branch_id:branch,
   history_start:'2026-08-01',history_end:'2026-09-21',forecast_origin:'2026-09-21',target_date:'2026-09-22',inventory_date:'2026-09-21',inventory_dates:['2026-09-20','2026-09-21'],dates_editable:true,operations_enabled:true,business_date:'2026-09-22',source:{source_id:'registered_test_pos',mapping_version:'test-v2',branch_id:branch,purpose:'TEST',version:1}},
  requests:[] as {path:string;query:URLSearchParams;body:any}[]};
}
type Fixture=ReturnType<typeof fixture>;
function settings(state:Fixture,branch:string|null) {
 return {organization:{id:state.id,name:'Artificial REAL contract fixture',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'real_only',provenance:'operator_bootstrap'},onboarding:{branch_count:1,can_import_branches:true,data_policy:'real_only'},
  data_context:branch?{...state.context,branch_id:branch}:{...state.context,branch_id:null,history_start:null,history_end:null,forecast_origin:null,target_date:null,inventory_date:null,inventory_dates:[]}};
}
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(done=>{resolve=done});return {promise,resolve}}
async function install(page:Page,state:Fixture,intercept?:(route:Route,path:string,query:URLSearchParams)=>Promise<boolean>) {
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  state.requests.push({path,query:url.searchParams,body:request.postData()?request.postDataJSON():null});
  if(intercept&&await intercept(route,path,url.searchParams))return;
  const user={id:'user-'+state.id,email:'fixture@example.invalid',organization_id:state.id,role:'admin',branch_ids:[state.branch]};
  if(path==='/session/login'){state.authenticated=true;state.session++;await route.fulfill({json:{user,csrf_token:'fixture-context-'+state.session}});return}
  if(!state.authenticated){await route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED',message:'Sign in'}}});return}
  if(path==='/session/me'){await route.fulfill({json:{user,csrf_token:'fixture-context-'+state.session}});return}
  if(path==='/session/logout'){state.authenticated=false;await route.fulfill({json:{status:'logged_out'}});return}
  if(path==='/settings'){await route.fulfill({json:settings(state,url.searchParams.get('branch_id'))});return}
  if(path==='/branches'){await route.fulfill({json:{items:[{branch_id:state.branch,branch_name:'Configured test branch'}],total:1,next_cursor:null}});return}
  if(path==='/dashboard'){await route.fulfill({json:{data_origin:'REAL',as_of:'2026-09-21',sold_portions:1,revenue:'100',history:[],warnings:[],top_meals:[],latest_plans:[]}});return}
  if(path==='/inventory'){await route.fulfill({json:{items:[{ingredient_id:'test-ingredient',ingredient_name:'Test ingredient',lot_id:'test-lot',snapshot_date:url.searchParams.get('date_from'),expiry_date:'2026-09-20',on_hand_qty:'2',unit:'kg'}],total:1,next_cursor:null,data_origin:'REAL'}});return}
  if(path==='/forecasts'&&request.method()==='POST'){await route.fulfill({json:{run_id:'pending-forecast',status:'queued'},status:202});return}
  if(path==='/runs/pending-forecast'){await route.fulfill({json:{run_id:'pending-forecast',kind:'forecast',status:'queued',result_id:null,error:null}});return}
  await route.fulfill({json:{items:[],total:0,next_cursor:null,data_origin:'REAL',scenario_date:null}});
 });
}

test('REAL TEST workspace uses server dates and explicitly selected forecast origin',async({page})=>{
 const state=fixture();await install(page,state);await page.goto('/');
 await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы',exact:true})).toBeVisible();
 await expect(page.locator('.scenario-banner')).toContainText('TEST · жасанды тексеру мысалы');
 await expect(page.locator('.scenario-banner')).toContainText('REAL');
 await expect(page.locator('body')).not.toContainText('SYNTHETIC');await expect(page.locator('body')).not.toContainText('01.01.2026');
 expect(state.requests.find(item=>item.path==='/dashboard')!.query.get('inventory_date')).toBe('2026-09-21');
 await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();
 await expect(page.getByLabel('Тарихтың шекті күні',{exact:true})).toHaveValue('2026-09-21');
 await page.getByLabel('Тарихтың шекті күні',{exact:true}).fill('2026-09-20');
 await expect(page.getByLabel('Болжам күні',{exact:true})).toHaveValue('21.09.2026');
 await page.getByRole('button',{name:'Есептеу',exact:true}).click();
 await expect.poll(()=>state.requests.filter(item=>item.path==='/forecasts'&&item.body).length).toBe(1);
 expect(state.requests.find(item=>item.path==='/forecasts'&&item.body)!.body.origin).toBe('2026-09-20');
 expect(state.requests.some(item=>JSON.stringify(item.body).includes('2025-12-31'))).toBe(false);
});

test('inventory and sales export follow actual selected dates, including expiry boundaries',async({page})=>{
 const state=fixture();await install(page,state);await page.goto('/inventory');
 await expect(page.getByLabel('Қор кесіндісінің күні',{exact:true})).toHaveValue('2026-09-21');
 await expect(page.getByText('Мерзімі өткен',{exact:true})).toBeVisible();
 await page.getByLabel('Қор кесіндісінің күні',{exact:true}).selectOption('2026-09-20');
 await expect(page.getByText('Мерзімі жақын',{exact:true})).toBeVisible();
 const latest=state.requests.filter(item=>item.path==='/inventory').at(-1)!;
 expect(latest.query.get('date_from')).toBe('2026-09-20');expect(latest.query.get('date_to')).toBe('2026-09-20');
 await page.locator('.sidebar').getByRole('button',{name:'Сатылым',exact:true}).click();
 await expect(page.getByLabel('Дейін',{exact:true})).toHaveValue('2026-09-21');
 await page.getByLabel('Бастап',{exact:true}).fill('2026-09-10');await page.getByLabel('Дейін',{exact:true}).fill('2026-09-19');
 const href=await page.getByRole('link',{name:'CSV жүктеу',exact:true}).getAttribute('href');
 const exported=new URL(href!,'http://fixture.invalid');expect(exported.searchParams.get('date_from')).toBe('2026-09-10');expect(exported.searchParams.get('date_to')).toBe('2026-09-19');
 await page.getByRole('button',{name:'Сүзгіні тазалау',exact:true}).click();
 await expect(page.getByLabel('Бастап',{exact:true})).toHaveValue('2026-08-25');await expect(page.getByLabel('Дейін',{exact:true})).toHaveValue('2026-09-21');
});

test('REAL imports use configured source and coverage refresh preserves selected dates',async({page})=>{
 const state=fixture();let sessionReads=0;
 await install(page,state,async(route,path)=>{
  if(path==='/session/me')sessionReads++;
  if(path==='/imports/preview'){await route.fulfill({json:{id:'test-real-batch',kind:'daily_sales',valid:true,can_commit:true,status:'preview',row_count:1,preview:[{data_origin:'REAL'}],errors:[]}});return true}
  if(path==='/imports/test-real-batch/commit'){await route.fulfill({json:{id:'test-real-batch',status:'committed',row_count:1,inserted_rows:1,updated_rows:0,unchanged_rows:0}});return true}
  return false;
 });
 await page.goto('/inventory');await page.getByLabel('Қор кесіндісінің күні',{exact:true}).selectOption('2026-09-20');
 await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();await page.getByLabel('Тарихтың шекті күні',{exact:true}).fill('2026-09-20');
 await page.locator('.sidebar').getByRole('button',{name:'Дерек импорттау',exact:true}).click();
 await expect(page.getByText('Тек бапталған дерек көзі мен бөлімшеге тиесілі REAL деректері қабылданады.',{exact:false})).toBeVisible();
 await page.getByText('Дерек көзі туралы мәлімет',{exact:true}).click();
 await expect(page.getByLabel('Дерек көзінің коды',{exact:true})).toHaveValue('registered_test_pos');
 await expect(page.getByLabel('Дерек көзінің коды',{exact:true})).toHaveAttribute('readonly','');
 await expect(page.getByLabel('Сәйкестендіру нұсқасы',{exact:true})).toHaveValue('test-v2');
 await page.getByLabel('CSV файлды таңдаңыз').setInputFiles({name:'artificial-real-contract.csv',mimeType:'text/csv',buffer:Buffer.from('data_origin\nREAL\n')});
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();const readsBeforeCommit=sessionReads;await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();await expect.poll(()=>sessionReads).toBe(readsBeforeCommit+1);
 const preview=state.requests.find(item=>item.path==='/imports/preview')!;expect(preview.body.source).toEqual({source_id:'registered_test_pos',mapping_version:'test-v2'});
 await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();await expect(page.getByLabel('Тарихтың шекті күні',{exact:true})).toHaveValue('2026-09-20');
 await page.locator('.sidebar').getByRole('button',{name:'Қойма',exact:true}).click();await expect(page.getByLabel('Қор кесіндісінің күні',{exact:true})).toHaveValue('2026-09-20');
});

test('missing REAL context cannot fall back to synthetic branch requests',async({page})=>{
 const state=fixture();await install(page,state,async(route,path)=>{
  if(path!=='/settings')return false;const response:any=settings(state,null);delete response.data_context;
  await route.fulfill({json:response});return true;
 });
 await page.goto('/');await expect(page.getByRole('heading',{name:'Деректер көзін дайындау',exact:true})).toBeVisible();
 expect(state.requests.some(item=>['/branches','/dashboard','/forecasts','/inventory'].includes(item.path))).toBe(false);
 await expect(page.locator('body')).not.toContainText('01.01.2026');
});

test('late branch data context cannot override the dates of a newer login',async({page})=>{
 const state=fixture('old','old-001'),started=deferred(),release=deferred();let completed=false;
 await install(page,state,async(route,path,query)=>{
  if(path!=='/settings'||query.get('branch_id')!=='old-001')return false;
  const response=settings(state,'old-001');started.resolve();await release.promise;
  await route.fulfill({json:response});completed=true;return true;
 });
 await page.goto('/');await started.promise;
 expect(state.requests.some(item=>item.path==='/dashboard')).toBe(false);
 await page.getByTitle('Шығу',{exact:true}).click();await expect(page.getByRole('button',{name:'Жүйеге кіру',exact:true})).toBeVisible();
 const next=fixture('new','new-002');state.id=next.id;state.branch=next.branch;state.context={...next.context,forecast_origin:'2026-09-18',target_date:'2026-09-19'};
 await page.getByLabel('Электрондық пошта',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('Құпиясөз',{exact:true}).fill('Fixture-only-passphrase');
 await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы',exact:true})).toBeVisible();
 release.resolve();await expect.poll(()=>completed).toBe(true);
 await page.locator('.sidebar').getByRole('button',{name:'Болжам',exact:true}).click();
 await expect(page.getByLabel('Тарихтың шекті күні',{exact:true})).toHaveValue('2026-09-18');
 expect(state.requests.some(item=>item.path==='/dashboard'&&item.query.get('branch_id')==='old-001')).toBe(false);
});

test('saved forecast without an origin makes no guessed history request',async({page})=>{
 const state=fixture();await install(page,state,async(route,path)=>{
  if(path!=='/forecasts/legacy')return false;
  await route.fulfill({json:{id:'legacy',branch_id:state.branch,data_origin:'REAL',model:'seasonal_naive_7',target_date:'2026-09-21',predictions:[{meal_id:'meal-test',point_forecast:2,p10:null,p50:null,p90:null}],metadata:{},input_freshness:'unknown'}});return true;
 });
 await page.goto('/forecasts/legacy');
 await expect(page.getByText('Есептің тарих күні белгісіз. График үшін деректер сұралмады.',{exact:true})).toBeVisible();
 expect(state.requests.some(item=>item.path==='/sales')).toBe(false);await expect(page.getByTestId('forecast-time-chart')).toHaveCount(0);
});
