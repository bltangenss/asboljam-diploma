import {navigateTo} from './navigation';
import {test,expect,type Page,type Route} from '@playwright/test';

// Tenant fixtures are synthetic and entirely browser-mocked; no database is changed.
type Branch={branch_id:string;branch_name:string};
function fixture(id='empty',role='admin',branches:Branch[]=[],policy='synthetic_only') {
 return {authenticated:true,generation:1,
  user:{id:'user-'+id,email:id+'@example.invalid',role,organization_id:id,branch_ids:branches.map(item=>item.branch_id)},
  organization:{id,name:('Organization '+id) as string|null,timezone:null as string|null,currency:'KZT',status:'active',data_policy:policy,provenance:'operator_bootstrap'},
  branches,requests:[] as {path:string;method:string;branch:string|null}[],pending:[] as Branch[],sessionReads:0};
}
type Tenant=ReturnType<typeof fixture>;
function settings(state:Tenant) {
 return {organization:state.organization,timezone:state.organization.timezone,currency:state.organization.currency,
  data_origin:state.organization.data_policy==='synthetic_only'?'SYNTHETIC':null,scenario_date:state.organization.data_policy==='synthetic_only'?'2026-01-01':null,onboarding:{branch_count:state.branches.length,
   can_import_branches:state.user.role==='admin'&&state.organization.data_policy==='synthetic_only',data_policy:state.organization.data_policy}};
}
function deferred() {let resolve!:()=>void;const promise=new Promise<void>(done=>{resolve=done});return {promise,resolve}}
async function installApi(page:Page,state:Tenant,intercept?:(route:Route,path:string)=>Promise<boolean>) {
 await page.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname.replace('/api/v1','');
  state.requests.push({path,method:route.request().method(),branch:url.searchParams.get('branch_id')});
  if(path==='/session/me')state.sessionReads++;
  if(intercept&&await intercept(route,path))return;
  if(path==='/session/login') {
   state.authenticated=true;state.generation++;
   await route.fulfill({json:{user:state.user,csrf_token:'fixture-tenant-csrf-'+state.generation}});return;
  }
  if(!state.authenticated) {
   await route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED',message:'Sign in'}}});return;
  }
  if(path==='/session/me') {
   await route.fulfill({json:{user:state.user,csrf_token:'fixture-tenant-csrf-'+state.generation}});return;
  }
  if(path==='/session/logout') {state.authenticated=false;await route.fulfill({json:{status:'logged_out'}});return}
  if(path==='/settings') {await route.fulfill({json:settings(state)});return}
  if(path==='/branches') {
   if(state.organization.data_policy!=='synthetic_only') {
    await route.fulfill({status:403,json:{detail:{code:'DATA_POLICY_UNCONFIGURED',message:'Source not configured'}}});return;
   }
   const visible=state.branches.filter(item=>state.user.branch_ids.includes(item.branch_id));
   await route.fulfill({json:{items:visible,total:visible.length,next_cursor:null}});return;
  }
  if(path==='/imports/preview') {
   const input=route.request().postDataJSON();expect(input.kind).toBe('branches');
   state.pending=input.csv_text.trim().split('\n').slice(1).map((line:string)=>{
    const [branch_id,branch_name]=line.split(',');return {branch_id,branch_name};
   });
   await route.fulfill({json:{id:'branch-batch',kind:'branches',valid:true,row_count:state.pending.length,errors:[],preview:state.pending}});return;
  }
  if(path==='/imports/branch-batch/commit') {
   state.branches.push(...state.pending);state.user.branch_ids=state.branches.map(item=>item.branch_id);
   await route.fulfill({json:{status:'committed'}});return;
  }
  if(path==='/dashboard') {
   await route.fulfill({json:{as_of:null,sold_portions:0,revenue:'0',history:[],warnings:[],top_meals:[],latest_plans:[]}});return;
  }
  await route.fulfill({json:{items:[],total:0,next_cursor:null}});
 });
}
async function importBranch(page:Page,id:string,name:string) {
 await expect(page.getByLabel('Деректер',{exact:true})).toHaveValue('branches');
 await page.getByLabel('CSV файлын таңдаңыз').setInputFiles({name:'branches.csv',mimeType:'text/csv',
  buffer:Buffer.from('branch_id,branch_name,data_origin\n'+id+','+name+',SYNTHETIC\n')});
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
}
function operationalRequests(state:Tenant) {
 return state.requests.filter(item=>['/dashboard','/sales','/forecasts','/plans','/procurement','/inventory','/recipes','/suppliers'].includes(item.path));
}

test('empty administrator imports the first branch without fabricated data or another login',async({page})=>{
 const state=fixture();await installApi(page,state);
 await page.goto('/');
 await expect(page.getByRole('heading',{name:'Алғашқы бөлімшені қосыңыз',exact:true})).toBeVisible();
 await expect(page.getByLabel('Бөлімше',{exact:true})).toBeDisabled();
 expect(operationalRequests(state)).toEqual([]);
 await expect(page.locator('.metric')).toHaveCount(0);
 await expect(page.locator('.sidebar-note')).not.toContainText('12');
 // Development StrictMode may repeat the startup read; the import must add exactly one refresh.
 const startupReads=state.sessionReads;
 await page.getByRole('button',{name:'Бөлімшелер CSV файлын импорттау',exact:true}).click();
 await importBranch(page,'007','First synthetic branch');
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('007');
 await expect(page.getByLabel('Бөлімше',{exact:true})).toBeEnabled();
 await expect.poll(()=>state.sessionReads).toBe(startupReads+1);
 expect(state.requests.filter(item=>item.path==='/session/login')).toEqual([]);
 await page.locator('.sidebar').getByRole('button',{name:'Бүгін',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Бүгін',exact:true})).toBeVisible();
 await expect.poll(()=>state.requests.some(item=>item.path==='/dashboard'&&item.branch==='007')).toBe(true);
 await expect(page.locator('.next-action')).toContainText('Бұл бөлімшеде сатылым деректері әлі жоқ.');
 await expect(page.locator('.metric-value').nth(0)).toHaveText('—');
 await expect(page.locator('.metric-value').nth(1)).toHaveText('—');
 await expect(page.locator('.today-data-dates').getByText('Сатылым тарихы жоқ',{exact:true})).toBeVisible();
 await expect(page.locator('.today-tasks')).not.toContainText('31.12.2025');
 expect(state.requests.some(item=>item.branch==='1')).toBe(false);
});

test('dated zero sales remain zero and actual history dates replace demo labels',async({page})=>{
 const state=fixture('zero','admin',[{branch_id:'ZERO',branch_name:'Zero sales branch'}]);
 await installApi(page,state,async(route,path)=>{
  if(path!=='/dashboard')return false;
  await route.fulfill({json:{as_of:'2025-11-20',sold_portions:0,revenue:'0',history:[{date:'2025-11-20',units_sold:0}],warnings:[],top_meals:[],latest_plans:[]}});return true;
 });
 await page.goto('/');
 await expect(page.locator('.metric-value').nth(0)).toHaveText('0');
 await expect(page.locator('.metric-value').nth(1)).toHaveText('0 ₸');
 await expect(page.locator('.chart-panel .chart-legend small')).toHaveText('20.11.2025 — 20.11.2025');
 await expect(page.locator('.today-data-dates').getByText('20.11.2025',{exact:true})).toBeVisible();
 await expect(page.getByRole('status')).toHaveCount(0);
});

test('branch import refreshes access while preserving an existing branch selection',async({page})=>{
 const state=fixture('selected','admin',[{branch_id:'A',branch_name:'Branch A'},{branch_id:'B',branch_name:'Branch B'}]);
 await installApi(page,state);await page.goto('/');
 await page.getByLabel('Бөлімше',{exact:true}).selectOption('B');
 await navigateTo(page,'imports');
 await page.getByLabel('Деректер',{exact:true}).selectOption('branches');
 await importBranch(page,'C','Branch C');
 await expect(page.getByLabel('Бөлімше',{exact:true}).locator('option')).toHaveText(['Branch A','Branch B','Branch C']);
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('B');
 await page.locator('.sidebar').getByRole('button',{name:'Баптаулар және басқару',exact:true}).click();
 await expect(page.locator('.settings-row').filter({has:page.getByRole('heading',{name:'Бөлімше',exact:true})})).toContainText('A, B, C');
});

test('a nonadmin without branches can use settings and unscoped audit without fake metadata',async({page})=>{
 const state=fixture('unknown','analyst');state.organization.name=null;
 await installApi(page,state);await page.goto('/');
 await expect(page.getByRole('heading',{name:'Қолжетімді бөлімше жоқ',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Бөлімшелер CSV файлын импорттау',exact:true})).toHaveCount(0);
 await page.locator('.sidebar').getByRole('button',{name:'Күн жоспары',exact:true}).click();
 await expect(page.getByTestId('workspace-onboarding')).toBeVisible();
 expect(operationalRequests(state)).toEqual([]);
 await page.locator('.sidebar').getByRole('button',{name:'Баптаулар және басқару',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Тіркелгі қауіпсіздігі',exact:true})).toBeVisible();
 await expect(page.locator('.settings-row').filter({has:page.getByRole('heading',{name:'Ұйым',exact:true})}).locator('span')).toHaveText('—');
 await expect(page.locator('.settings-row').filter({has:page.getByRole('heading',{name:'Уақыт белдеуі',exact:true})}).locator('span')).toHaveText('—');
 await expect(page.getByText('AsBoljam Demo',{exact:true})).toHaveCount(0);
 await expect(page.getByText('Asia/Qyzylorda',{exact:true})).toHaveCount(0);
 await navigateTo(page,'audit');
 await expect.poll(()=>state.requests.some(item=>item.path==='/audit')).toBe(true);
 expect(state.requests.filter(item=>item.path==='/audit').every(item=>item.branch===null)).toBe(true);
});

test('unconfigured organization sees its real metadata and cannot open operational imports',async({page})=>{
 const state=fixture('pending','admin',[],'unconfigured');state.organization.name='Pending Business';state.organization.timezone='Asia/Almaty';
 await installApi(page,state);await page.goto('/');
 await expect(page.getByRole('heading',{name:'Дерек көзін дайындау',exact:true})).toBeVisible();
 await expect(page.locator('.scenario-banner')).not.toContainText('01.01.2026');
 await expect(page.getByText('SYNTHETIC',{exact:true})).toHaveCount(0);
 await navigateTo(page,'imports');
 await expect(page.getByLabel('CSV файлын таңдаңыз')).toHaveCount(0);
 expect(operationalRequests(state)).toEqual([]);
 expect(state.requests.some(item=>item.path==='/branches')).toBe(false);
 await page.locator('.sidebar').getByRole('button',{name:'Баптаулар және басқару',exact:true}).click();
 await expect(page.locator('.settings-row').filter({has:page.getByRole('heading',{name:'Ұйым',exact:true})}).locator('span')).toHaveText('Pending Business');
 await expect(page.getByText('Asia/Almaty',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'ҚАЗ',exact:true}).click();
 await expect(page.locator('.scenario-banner')).toContainText('Источник данных не настроен');
});

for(const heldPath of ['/settings','/branches']) {
test(`delayed tenant ${heldPath} response cannot replace a new login`,async({page})=>{
 const state=fixture('old','admin',[{branch_id:'OLD',branch_name:'OLD_BRANCH'}]),started=deferred(),release=deferred();let completed=0;
 await installApi(page,state,async(route,path)=>{
  if(state.organization.id!=='old'||path!==heldPath)return false;
  const response=path==='/settings'?settings(state):{items:[...state.branches],total:1,next_cursor:null};
  started.resolve();await release.promise;
  await route.fulfill({json:response});completed++;return true;
 });
 await page.goto('/');await started.promise;
 await expect(page.getByLabel('Бөлімше',{exact:true})).toBeDisabled();
 expect(operationalRequests(state)).toEqual([]);
 await page.getByTitle('Шығу',{exact:true}).click();
 await expect(page.getByRole('button',{name:'Жүйеге кіру',exact:true})).toBeVisible();
 const next=fixture('new','admin',[{branch_id:'NEW',branch_name:'NEW_BRANCH'}]);state.user=next.user;state.organization=next.organization;state.branches=next.branches;
 await page.getByLabel('Электрондық пошта',{exact:true}).fill(state.user.email);await page.getByLabel('Құпиясөз',{exact:true}).fill('Fixture-only-passphrase');
 await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('NEW');
 release.resolve();await expect.poll(()=>completed).toBe(1);
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 await expect(page.getByLabel('Бөлімше',{exact:true}).locator('option')).toHaveText(['NEW_BRANCH']);
 await expect(page.locator('.sidebar-note')).toContainText('Organization new');
 await expect(page.getByText('Organization old',{exact:true})).toHaveCount(0);
 expect(state.requests.some(item=>item.path==='/dashboard'&&item.branch==='OLD')).toBe(false);
});
}

test('workspace loading failure is recoverable and never selects branch one',async({page})=>{
 const state=fixture('retry','admin',[{branch_id:'009',branch_name:'Actual branch'}]);let fail=true;
 await installApi(page,state,async(route,path)=>{
  if(path!=='/settings'||!fail)return false;
  await route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE',message:'Workspace unavailable'}}});return true;
 });
 await page.goto('/');await expect(page.getByRole('alert')).toContainText('Workspace unavailable');
 expect(operationalRequests(state)).toEqual([]);fail=false;
 await page.getByRole('button',{name:'Қайта жүктеу',exact:true}).click();
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('009');
 await expect(page.getByRole('heading',{name:'Бүгін',exact:true})).toBeVisible();
 expect(state.requests.some(item=>item.branch==='1')).toBe(false);
});
