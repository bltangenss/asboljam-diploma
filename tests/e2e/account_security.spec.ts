import {navigateTo} from './navigation';
import {test, expect, type Page, type Route} from '@playwright/test';

// All credentials and responses are fabricated. These tests do not contact a real account.
const user={id:'account-test',email:'account@example.invalid',role:'analyst',organization_id:'fixture',branch_ids:['1']};
const current='Fixture-current-passphrase';
const replacement='Fixture-replacement-passphrase';
const empty={items:[],total:0,next_cursor:null,data_origin:'SYNTHETIC',scenario_date:'2026-01-01'};
function deferred() {
  let resolve!:()=>void;
  const promise=new Promise<void>(done=>{resolve=done});
  return {promise,resolve};
}
async function installApi(page:Page, intercept?:(route:Route,path:string)=>Promise<boolean>) {
  const auth={authenticated:true,generation:1,user:{...user}};
  await page.route('**/api/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname.replace('/api/v1','');
    if(intercept&&await intercept(route,path))return;
    if(path==='/session/login') {
      auth.authenticated=true;auth.generation++;
      await route.fulfill({json:{user:auth.user,csrf_token:'fake-account-csrf-'+auth.generation}});return;
    }
    if(!auth.authenticated) {
      await route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED',message:'Expired session'}}});return;
    }
    if(path==='/session/me') {
      await route.fulfill({json:{user:auth.user,csrf_token:'fake-account-csrf-'+auth.generation}});return;
    }
    if(path==='/branches') {
      await route.fulfill({json:{...empty,items:[{branch_id:'1',branch_name:'Fixture branch'}],total:1}});return;
    }
    if(path==='/settings') {
      await route.fulfill({json:{organization:{id:auth.user.organization_id,name:'Fixture organization',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'test_fixture'},
        timezone:'Asia/Qyzylorda',currency:'KZT',onboarding:{branch_count:1,can_import_branches:false,data_policy:'synthetic_only'}}});return;
    }
    if(path==='/dashboard') {
      await route.fulfill({json:{as_of:'2025-12-31',sold_portions:2,revenue:'4000',history:[],warnings:[],top_meals:[],latest_plans:[]}});return;
    }
    await route.fulfill({json:empty});
  });
  return auth;
}
async function fillPasswords(page:Page,next=replacement,confirm=next) {
  await page.getByLabel('Қазіргі құпиясөз',{exact:true}).fill(current);
  await page.getByLabel('Жаңа құпиясөз',{exact:true}).fill(next);
  await page.getByLabel('Жаңа құпиясөзді қайталаңыз',{exact:true}).fill(confirm);
}
async function expectLogin(page:Page,message:string) {
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('button',{name:'Жүйеге кіру',exact:true})).toBeVisible();
  await expect(page.getByText(message,{exact:true})).toBeVisible();
  await expect(page.getByLabel('Құпиясөз',{exact:true})).toHaveValue('');
}

test('password change signs out the analyst locally and translates the login notice',async({page})=>{
  const writes:string[]=[];
  await installApi(page,async(route,path)=>{
    if(route.request().method()!=='GET')writes.push(path);
    if(path!=='/account/password')return false;
    expect(route.request().postDataJSON()).toEqual({current_password:current,new_password:replacement});
    expect(route.request().headers()['x-csrf-token']).toBe('fake-account-csrf-1');
    await route.fulfill({json:{status:'password_changed',reauth_required:true}});return true;
  });
  await page.goto('/settings');
  await expect(page.getByLabel('Қазіргі құпиясөз',{exact:true})).toHaveAttribute('autocomplete','current-password');
  await expect(page.getByLabel('Жаңа құпиясөз',{exact:true})).toHaveAttribute('autocomplete','new-password');
  await fillPasswords(page);
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
  await expectLogin(page,'Құпиясөз өзгертілді. Қайта кіріңіз.');
  await page.getByRole('button',{name:'Тілді ауыстыру',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('Пароль изменён. Войдите снова.');
  expect(writes).toEqual(['/account/password']);
  const storage=await page.evaluate(()=>JSON.stringify({local:{...localStorage},session:{...sessionStorage}}));
  expect(storage).not.toContain(current);expect(storage).not.toContain(replacement);
  expect(page.url()).not.toContain(current);expect(page.url()).not.toContain(replacement);
});

test('local length and confirmation checks prevent any password request',async({page})=>{
  let passwordRequests=0;
  await installApi(page,async(route,path)=>{
    if(path!=='/account/password')return false;
    passwordRequests++;await route.fulfill({status:500,json:{detail:'Unexpected request'}});return true;
  });
  await page.goto('/settings');
  await fillPasswords(page,'too-short');
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('Жаңа құпиясөз 12–1024 таңбадан тұруы керек.');
  await fillPasswords(page,replacement,'Different-confirmation');
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('Жаңа құпиясөздер сәйкес емес.');
  expect(passwordRequests).toBe(0);
});

test('wrong current or unchanged password keeps the session and clears sensitive fields',async({page})=>{
  const cases=[
    ['CURRENT_PASSWORD_INVALID','Қазіргі құпиясөз қате. Қайталап енгізіңіз.'],
    ['PASSWORD_UNCHANGED','Жаңа құпиясөз қазіргіден өзгеше болуы керек.'],
  ];
  let attempt=0;
  await installApi(page,async(route,path)=>{
    if(path!=='/account/password')return false;
    const code=cases[attempt++][0];
    await route.fulfill({status:code==='CURRENT_PASSWORD_INVALID'?400:422,
      json:{detail:{code,message:'DO_NOT_DISPLAY_SERVER_DETAIL'}}});return true;
  });
  await page.goto('/settings');
  for(const [,message] of cases) {
    await fillPasswords(page);
    await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
    await expect(page.getByRole('alert')).toHaveText(message);
    for(const label of ['Қазіргі құпиясөз','Жаңа құпиясөз','Жаңа құпиясөзді қайталаңыз']) {
      await expect(page.getByLabel(label,{exact:true})).toHaveValue('');
    }
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByText('DO_NOT_DISPLAY_SERVER_DETAIL')).toHaveCount(0);
  }
  expect(attempt).toBe(2);
});

test('finishing workspace initialization preserves a password form already being edited',async({page})=>{
  const branchesStarted=deferred(),releaseBranches=deferred();let requests=0;
  await installApi(page,async(route,path)=>{
    if(path==='/branches') {
      branchesStarted.resolve();await releaseBranches.promise;
      await route.fulfill({json:{...empty,items:[{branch_id:'1',branch_name:'Fixture branch'}],total:1}});return true;
    }
    if(path==='/account/password') {
      requests++;
      expect(route.request().postDataJSON()).toEqual({current_password:current,new_password:replacement});
      await route.fulfill({status:400,json:{detail:{code:'CURRENT_PASSWORD_INVALID',message:'Fixture failure'}}});return true;
    }
    return false;
  });
  await page.goto('/settings');await branchesStarted.promise;
  await expect(page.locator('.settings-row').filter({has:page.getByRole('heading',{name:'Ұйым',exact:true})})).toContainText('Fixture organization');
  await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveCount(0);await expect(page.locator('.cabinet-name')).toHaveText('Жұмыс кеңістігі жүктелуде…');
  await fillPasswords(page);
  const refreshed=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/v1/settings');
  releaseBranches.resolve();await refreshed;
  // A single-branch account sees its cabinet name; the form keeps its typed values.
  await expect(page.locator('.cabinet-name')).toHaveText('Fixture branch');await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveCount(0);
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  await expect(page.getByLabel('Қазіргі құпиясөз',{exact:true})).toHaveValue(current);
  await expect(page.getByLabel('Жаңа құпиясөз',{exact:true})).toHaveValue(replacement);
  await expect(page.getByLabel('Жаңа құпиясөзді қайталаңыз',{exact:true})).toHaveValue(replacement);
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
  await expect(page.getByRole('alert')).toHaveText('Қазіргі құпиясөз қате. Қайталап енгізіңіз.');
  expect(requests).toBe(1);
});

test('pending password submission is unique and its success signs out after navigation',async({page})=>{
  const started=deferred(),release=deferred();let requests=0;
  await installApi(page,async(route,path)=>{
    if(path!=='/account/password')return false;
    requests++;started.resolve();await release.promise;
    await route.fulfill({json:{status:'password_changed',reauth_required:true}});return true;
  });
  await page.goto('/settings');await fillPasswords(page);
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();await started.promise;
  await expect(page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true})).toBeDisabled();
  await expect(page.getByLabel('Қазіргі құпиясөз',{exact:true})).toBeDisabled();
  await page.getByRole('form',{name:'Құпиясөзді өзгерту',exact:true}).evaluate((form:HTMLFormElement)=>form.requestSubmit());
  await navigateTo(page,'sales');
  await expect(page.getByRole('heading',{name:'Сатылым',exact:true})).toBeVisible();
  release.resolve();
  await expectLogin(page,'Құпиясөз өзгертілді. Қайта кіріңіз.');
  expect(requests).toBe(1);
});

test('late password success cannot sign out a newer login',async({page})=>{
  const started=deferred(),release=deferred();
  const auth=await installApi(page,async(route,path)=>{
    if(path!=='/account/password')return false;
    started.resolve();await release.promise;
    await route.fulfill({json:{status:'password_changed',reauth_required:true}});return true;
  });
  await page.goto('/settings');await fillPasswords(page);
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();await started.promise;
  auth.authenticated=false;
  await navigateTo(page,'sales');
  await expectLogin(page,'Сессия аяқталды. Қайта кіріңіз.');
  await page.getByLabel('Электрондық пошта',{exact:true}).fill(user.email);
  await page.getByLabel('Құпиясөз',{exact:true}).fill(replacement);
  await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Бүгін',exact:true})).toBeVisible();
  const completed=page.waitForEvent('requestfinished',request=>new URL(request.url()).pathname==='/api/v1/account/password');
  release.resolve();await completed;
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading',{name:'Бүгін',exact:true})).toBeVisible();
});

test('session expiry during password submission uses the normal login recovery',async({page})=>{
  await installApi(page,async(route,path)=>{
    if(path!=='/account/password')return false;
    await route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED',message:'Expired session'}}});return true;
  });
  await page.goto('/settings');await fillPasswords(page);
  await page.getByRole('button',{name:'Құпиясөзді өзгерту',exact:true}).click();
  await expectLogin(page,'Сессия аяқталды. Қайта кіріңіз.');
});
