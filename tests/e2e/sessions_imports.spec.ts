import {test, expect, type Page, type Route} from '@playwright/test';

// Deterministic browser race tests. No real credentials, worker jobs or database mutations.
const user = {id:'browser-regression', email:'browser@example.invalid', role:'admin', organization_id:'test', branch_ids:['1']};
const pageData = {items:[], total:0, next_cursor:null, data_origin:'SYNTHETIC', scenario_date:'2026-01-01'};
const dashboard = {as_of:'2025-12-31', sold_portions:2, revenue:'4000', history:[], warnings:[], top_meals:[], latest_plans:[]};
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => {resolve=done});
  return {promise, resolve};
}
async function installApi(page:Page, intercept?:(route:Route,path:string)=>Promise<boolean>) {
  const auth = {authenticated:true, generation:1};
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1','');
    const reply = (json:unknown,status=200) => route.fulfill({status,json});
    if (intercept && await intercept(route,path)) return;
    if (path === '/session/login') {
      auth.authenticated=true; auth.generation++;
      await reply({user,csrf_token:'fake-browser-csrf-'+auth.generation}); return;
    }
    if (!auth.authenticated) {
      await reply({detail:{code:'AUTH_REQUIRED',message:'Please sign in'}},401); return;
    }
    if (path === '/session/me') {await reply({user,csrf_token:'fake-browser-csrf-'+auth.generation}); return}
    if (path === '/session/logout') {auth.authenticated=false; await reply({status:'logged_out'}); return}
    if (path === '/branches') {await reply({...pageData,items:[{branch_id:'1',branch_name:'Test branch'}],total:1}); return}
    if (path === '/dashboard') {await reply(dashboard); return}
    await reply(pageData);
  });
  return auth;
}
async function expectDashboard(page:Page) {
  await expect(page.getByRole('heading',{name:'Бөлімшенің жұмыс шолуы'})).toBeVisible();
  await expect(page.locator('.metric-value').first()).toHaveText('2');
}
async function signInAgain(page:Page) {
  await expect(page.getByRole('button',{name:'Жүйеге кіру',exact:true})).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Сессия аяқталды');
  await page.getByLabel('Электрондық пошта').fill(user.email);
  await page.getByLabel('Құпиясөз').fill('Fake-browser-test-password');
  await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
  await expectDashboard(page);
}

for (const trigger of ['protected read','logout'] as const) {
  test(`expired browser session recovers through login after ${trigger}`,async({page})=>{
    const auth=await installApi(page);
    await page.goto('/'); await expectDashboard(page);
    auth.authenticated=false;
    if (trigger==='logout') await page.getByTitle('Шығу',{exact:true}).click();
    else await page.locator('.sidebar').getByRole('button',{name:'Сатылым',exact:true}).click();
    await expect(page).toHaveURL(/\/login$/);
    await signInAgain(page);
  });
}

test('a delayed 401 from an old session cannot sign out the new login',async({page})=>{
  const started=deferred(), release=deferred();
  let held=false;
  const auth=await installApi(page,async(route,path)=>{
    if(path!=='/sales'||held)return false;
    held=true; started.resolve(); await release.promise;
    await route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED',message:'Expired old session'}}});
    return true;
  });
  await page.goto('/'); await expectDashboard(page);
  await page.locator('.sidebar').getByRole('button',{name:'Сатылым',exact:true}).click();
  await started.promise; auth.authenticated=false;
  await page.locator('.sidebar').getByRole('button',{name:'Қойма',exact:true}).click();
  await signInAgain(page);
  const completed=page.waitForEvent('requestfinished',request=>new URL(request.url()).pathname==='/api/v1/sales');
  release.resolve(); await completed;
  await expectDashboard(page);
  await expect(page).toHaveURL(/\/dashboard$/);
});

for (const change of ['file','schema'] as const) {
  test(`late CSV preview cannot replace a newer ${change} selection`,async({page})=>{
    const started=deferred(),release=deferred();
    let previews=0;
    const committed:string[]=[];
    const payloads:{kind:string;csv_text:string}[]=[];
    await installApi(page,async(route,path)=>{
      if(path==='/imports/preview') {
        const index=++previews; payloads.push(route.request().postDataJSON());
        if(index===1) {started.resolve(); await release.promise}
        await route.fulfill({json:{id:index===1?'old-batch':'new-batch',kind:payloads[index-1].kind,
          valid:true,row_count:1,errors:[],preview:[{marker:index===1?'OLD_PREVIEW':'NEW_PREVIEW'}]}});
        return true;
      }
      if(path.startsWith('/imports/')&&path.endsWith('/commit')) {
        committed.push(path); await route.fulfill({json:{status:'committed'}}); return true;
      }
      return false;
    });
    await page.goto('/imports');
    const input=page.getByLabel('CSV файлды таңдаңыз');
    await input.setInputFiles({name:'first.csv',mimeType:'text/csv',buffer:Buffer.from('marker\nfirst\n')});
    await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
    await started.promise;
    if(change==='file') await input.setInputFiles({name:'second.csv',mimeType:'text/csv',buffer:Buffer.from('marker\nsecond\n')});
    else await page.getByLabel('Деректер',{exact:true}).selectOption('inventory_lots');
    await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
    await expect(page.locator('tbody')).toContainText('NEW_PREVIEW');
    const oldFinished=page.waitForEvent('requestfinished',request=>new URL(request.url()).pathname==='/api/v1/imports/preview');
    release.resolve(); await oldFinished;
    await expect(page.locator('tbody')).toContainText('NEW_PREVIEW');
    await expect(page.getByText('OLD_PREVIEW',{exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'Импорттау',exact:true}).click();
    await expect(page.getByText('Деректер транзакциямен импортталды')).toBeVisible();
    expect(committed).toEqual(['/imports/new-batch/commit']);
    if(change==='file') expect(payloads[1].csv_text).toContain('second');
    else expect(payloads[1].kind).toBe('inventory_lots');
  });
}
