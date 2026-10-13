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
async function settleBrowser(page:Page) {
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
}
async function installApi(page:Page, intercept?:(route:Route,path:string)=>Promise<boolean>) {
  const auth = {authenticated:true, generation:1, user};
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1','');
    const reply = (json:unknown,status=200) => route.fulfill({status,json});
    if (intercept && await intercept(route,path)) return;
    if (path === '/session/login') {
      auth.authenticated=true; auth.generation++;
      await reply({user:auth.user,csrf_token:'fake-browser-csrf-'+auth.generation}); return;
    }
    if (!auth.authenticated) {
      await reply({detail:{code:'AUTH_REQUIRED',message:'Please sign in'}},401); return;
    }
    if (path === '/session/me') {await reply({user:auth.user,csrf_token:'fake-browser-csrf-'+auth.generation}); return}
    if (path === '/session/logout') {auth.authenticated=false; await reply({status:'logged_out'}); return}
    if (path === '/settings') {
      await reply({organization:{id:auth.user.organization_id,name:'Test organization',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'test_fixture'},
        timezone:'Asia/Qyzylorda',currency:'KZT',onboarding:{branch_count:auth.user.branch_ids.length,can_import_branches:auth.user.role==='admin',data_policy:'synthetic_only'}});return;
    }
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

// Pages may show more than one status (e.g. run-history loading); assert the specific message.
test('analyst can read saved plans and templates but cannot submit writes',async({page})=>{
  const writes:string[]=[];
  const auth=await installApi(page,async(route,path)=>{
    if(route.request().method()!=='GET') {
      writes.push(path);
      await route.fulfill({status:403,json:{detail:{code:'FORBIDDEN',message:'Read only'}}});
      return true;
    }
    if(path==='/forecasts') {
      await route.fulfill({json:{...pageData,items:[{id:'stored-forecast',model:'seasonal_naive_7',target_date:'2026-01-01'}],total:1}});
      return true;
    }
    if(path==='/plans/stored-plan') {
      await route.fulfill({json:{id:'stored-plan',branch_id:'1',forecast_id:'stored-forecast',version:1,status:'ready',
        result:{target_date:'2026-01-01',strategy:'point',budget:'1000',total_cost:'0',remaining_budget:'1000',
          shortage_count:0,requirements:[],lines:[],constraints_valid:true,solver_status:'optimal'}}});
      return true;
    }
    return false;
  });
  auth.user={...user,role:'analyst'};
  await page.goto('/forecasts');
  await expect(page.getByRole('status').filter({hasText:'Сіз дайын болжамдар мен сатып алу жоспарларын қарай аласыз.'})).toBeVisible();
  await expect(page.getByRole('button',{name:'01.01.2026 күніне болжам',exact:true})).toBeVisible();
  await expect(page.getByLabel('Модель',{exact:true})).toBeDisabled();
  const forecastButton=page.getByRole('button',{name:'Есептеу',exact:true});
  await expect(forecastButton).toBeDisabled();
  await forecastButton.evaluate((button:HTMLButtonElement)=>button.click());
  await page.goto('/procurement');
  await expect(page.getByLabel('Болжам',{exact:true})).toHaveValue('stored-forecast');
  await expect(page.getByLabel('Болжам',{exact:true})).toBeDisabled();
  const planButton=page.getByRole('button',{name:'Есептеу',exact:true});
  await expect(planButton).toBeDisabled();
  await planButton.evaluate((button:HTMLButtonElement)=>button.click());
  await page.goto('/procurement/stored-plan');
  await expect(page.getByRole('button',{name:'Жоспарды бекіту',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Қабылдамау',exact:true})).toBeDisabled();
  await expect(page.getByRole('link',{name:'CSV жүктеу',exact:true})).toHaveAttribute('href','/api/v1/plans/stored-plan/export');
  await page.goto('/imports');
  await expect(page.getByRole('status').filter({hasText:'Сіз CSV үлгілерін жүктей аласыз.'})).toBeVisible();
  await expect(page.getByLabel('Деректер',{exact:true}).locator('option')).toHaveText(['Күнделікті сатылым','Қойма қалдықтары','Жұмыс күнтізбесі']);
  const input=page.getByLabel('CSV файлын таңдаңыз');
  await expect(input).toBeDisabled();
  // Even a programmatic file selection must not enable a forbidden submission.
  await input.setInputFiles({name:'blocked.csv',mimeType:'text/csv',buffer:Buffer.from('marker\nblocked\n')});
  const previewButton=page.getByRole('button',{name:'Алдын ала қарау',exact:true});
  await expect(previewButton).toBeDisabled();
  await previewButton.evaluate((button:HTMLButtonElement)=>button.click());
  await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toHaveCount(0);
  await page.getByLabel('Деректер',{exact:true}).selectOption('calendar');
  await expect(page.locator('a[href="/api/v1/imports/template/calendar"]')).toBeVisible();
  await page.locator('.language').click();
  await expect(page.getByRole('status').filter({hasText:'Вы можете скачивать шаблоны CSV.'})).toBeVisible();
  await page.goto('/forecasts');
  await expect(page.getByRole('status').filter({hasText:'Вам доступен просмотр готовых прогнозов и планов закупки.'})).toBeVisible();
  await settleBrowser(page);
  expect(writes).toEqual([]);
});

test('manager and warehouse import selectors expose only authorized schemas',async({page})=>{
  const payloads:{kind:string;csv_text:string}[]=[];
  const auth=await installApi(page,async(route,path)=>{
    if(path!=='/imports/preview')return false;
    const body=route.request().postDataJSON();payloads.push(body);
    await route.fulfill({json:{id:'allowed-preview',kind:body.kind,valid:true,row_count:1,errors:[],preview:[{marker:body.kind}]}});
    return true;
  });
  for(const role of ['manager','warehouse']) {
    auth.user={...user,role};
    await page.goto('/imports');
    const selector=page.getByLabel('Деректер',{exact:true});
    await expect(selector.locator('option')).toHaveText(role==='manager'?['Күнделікті сатылым','Қойма қалдықтары','Жұмыс күнтізбесі']:['Қойма қалдықтары']);
    await page.getByLabel('CSV файлын таңдаңыз').setInputFiles({name:'allowed.csv',mimeType:'text/csv',buffer:Buffer.from('marker\nallowed\n')});
    await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
    await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeEnabled();
  }
  expect(payloads.map(payload=>payload.kind)).toEqual(['daily_sales','inventory_lots']);
});

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
  release.resolve(); await completed; await settleBrowser(page);
  await expectDashboard(page);
  await expect(page).toHaveURL(/\/dashboard$/);
});

test('a delayed branch lookup cannot replace branches after signing in again',async({page})=>{
  const started=deferred(),release=deferred();
  let newSession=false,oldCompleted=0;
  const auth=await installApi(page,async(route,path)=>{
    if(path!=='/branches')return false;
    if(!newSession) {
      started.resolve();await release.promise;
      await route.fulfill({json:{...pageData,items:[{branch_id:'1',branch_name:'OLD_BRANCH'}],total:1}});
      oldCompleted++;return true;
    }
    await route.fulfill({json:{...pageData,items:[{branch_id:'2',branch_name:'NEW_BRANCH'}],total:1}});
    return true;
  });
  await page.goto('/');await started.promise;
  auth.authenticated=false;
  // Branch views now wait for an actual branch; settings still verifies the session.
  await page.locator('.sidebar').getByRole('button',{name:'Баптаулар',exact:true}).click();
  await expect(page.getByRole('button',{name:'Жүйеге кіру',exact:true})).toBeVisible();
  auth.user={...user,branch_ids:['2']};newSession=true;
  await signInAgain(page);
  const branch=page.getByLabel('Бөлімше',{exact:true});
  await expect(branch).toHaveValue('2');
  release.resolve();await expect.poll(()=>oldCompleted).toBeGreaterThan(0);await settleBrowser(page);
  await expect(branch).toHaveValue('2');
  await expect(branch.locator('option')).toHaveText(['NEW_BRANCH']);
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
    const input=page.getByLabel('CSV файлын таңдаңыз');
    await input.setInputFiles({name:'first.csv',mimeType:'text/csv',buffer:Buffer.from('marker\nfirst\n')});
    await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
    await started.promise;
    if(change==='file') await input.setInputFiles({name:'second.csv',mimeType:'text/csv',buffer:Buffer.from('marker\nsecond\n')});
    else await page.getByLabel('Деректер',{exact:true}).selectOption('inventory_lots');
    await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
    await expect(page.locator('tbody')).toContainText('NEW_PREVIEW');
    const oldFinished=page.waitForEvent('requestfinished',request=>new URL(request.url()).pathname==='/api/v1/imports/preview');
    release.resolve(); await oldFinished; await settleBrowser(page);
    await expect(page.locator('tbody')).toContainText('NEW_PREVIEW');
    await expect(page.getByText('OLD_PREVIEW',{exact:true})).toHaveCount(0);
    await page.getByRole('button',{name:'Импорттау',exact:true}).click();
    await expect(page.getByText('Деректер транзакциямен импортталды')).toBeVisible();
    expect(committed).toEqual(['/imports/new-batch/commit']);
    if(change==='file') expect(payloads[1].csv_text).toContain('second');
    else expect(payloads[1].kind).toBe('inventory_lots');
  });
}
