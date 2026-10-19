import {test,expect,type Page} from '@playwright/test';

// Synthetic browser contract: registration lists every city and opens a test-mode cabinet;
// the profile fills day factors for the branch city through a reviewable import and shows
// the week's weather. Backend rules are covered by tests/test_places.py.
const cities=[{code:'astana',name:{kk:'Астана',ru:'Астана'},region:{kk:'Астана қаласы',ru:'г. Астана'}},
 {code:'shymkent',name:{kk:'Шымкент',ru:'Шымкент'},region:{kk:'Шымкент қаласы',ru:'г. Шымкент'}},
 {code:'aktau',name:{kk:'Ақтау',ru:'Актау'},region:{kk:'Маңғыстау облысы',ru:'Мангистауская область'}}];
const types={cafe:{kk:'Кафе',ru:'Кафе'},canteen:{kk:'Асхана',ru:'Столовая'}};

async function install(page:Page){
 const state={registered:false,posted:[] as {path:string;body:any}[]};
 const context={version:1,mode:'synthetic_demo',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Almaty',currency:'KZT',branch_id:'1',history_start:null,history_end:null,forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:[],dates_editable:false,operations_enabled:true,business_date:'2026-01-01',source:null};
 const user={id:'owner',organization_id:'org-new',email:'owner@example.invalid',role:'admin',branch_ids:['1']};
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  if(request.method()!=='GET'){
   state.posted.push({path,body:request.postDataJSON()});
   if(path==='/register'){state.registered=true;return route.fulfill({json:{user,csrf_token:'synthetic-csrf'}});}
   if(path==='/factors/fill')return route.fulfill({json:{batch:{id:'fill-batch',kind:'day_factors',status:'preview'},summary:{new_rows:732}}});
   return route.fulfill({status:400,json:{detail:{code:'FIXTURE_UNEXPECTED_MUTATION'}}});
  }
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me'){if(!state.registered)return route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED'}}});json={user,csrf_token:'synthetic-csrf'};}
  if(path==='/registration')json={enabled:true,mode:'synthetic_only'};
  if(path==='/cities')json={items:cities,establishment_types:types};
  if(path==='/settings')json={organization:{id:'org-new',name:'Астана кофе',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:1,data_policy:'synthetic_only'},data_context:context};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Астана кофе'}],total:1};
  if(path==='/branch-profiles')json={items:[{branch_id:'1',city_code:'astana',city:{...cities[0],timezone:'Asia/Almaty'},establishment_type:'cafe'}]};
  if(path==='/weather')json={city:cities[0],source:'Open-Meteo',items:Array.from({length:7},(_,index)=>({date:`2026-10-${19+index}`,temperature_mean:8-index,temperature_max:14-index,precipitation:index/2}))};
  await route.fulfill({json});
 });
 return state;
}

test('registration lists Kazakhstan cities and opens a test-mode cabinet',async({page})=>{
 const state=await install(page);
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','kk'));
 await page.goto('/');
 await page.getByRole('button',{name:'Тіркелу'}).click();
 const form=page.getByRole('form',{name:'Тіркелу'});
 await expect(form.getByLabel('Қала').locator('option')).toHaveText(['Қаланы таңдаңыз','Ақтау · Маңғыстау облысы','Астана · Астана қаласы','Шымкент · Шымкент қаласы']);
 await form.getByLabel('Мекеме атауы').fill('Астана кофе');
 await form.getByLabel('Мекеме түрі').selectOption('cafe');
 await form.getByLabel('Қала').selectOption('astana');
 await form.getByLabel('Электрондық пошта').fill('owner@example.invalid');
 await form.locator('#register-password').fill('Synthetic-registration-2026');
 await form.getByLabel('Құпиясөзді қайталаңыз').fill('Synthetic-registration-2025');
 const submit=form.getByRole('button',{name:/Кабинетті ашу/});
 await expect(form).toContainText('Құпиясөздер сәйкес емес.');await expect(submit).toBeDisabled();
 await form.getByLabel('Құпиясөзді қайталаңыз').fill('Synthetic-registration-2026');
 await expect(submit).toBeDisabled();  // the test-mode consent is required
 await form.locator('.register-consent input').check();
 await submit.click();
 await expect(page).toHaveURL(/\/dashboard$/);
 await expect(page.locator('.cabinet-name')).toHaveText('Астана кофе');
 expect(state.posted[0]).toEqual({path:'/register',body:{establishment_name:'Астана кофе',establishment_type:'cafe',city_code:'astana',email:'owner@example.invalid',password:'Synthetic-registration-2026',accept_test_mode:true}});
});

test('the profile fills factors for the branch city through an import preview and shows the weather',async({page})=>{
 const state=await install(page);state.registered=true;
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 await page.goto('/profile');
 await page.locator('.profile-factors>summary').click();
 const autofill=page.locator('.factor-autofill');
 await expect(autofill).toContainText('Астана · г. Астана');
 await expect(page.locator('.city-weather li')).toHaveCount(7);
 await expect(page.locator('.city-weather h3')).toContainText('Прогноз погоды · Астана · 7 дней');
 // Without sales history the range starts two years before the forecast day.
 await expect(autofill.getByLabel('С',{exact:true})).toHaveValue('2024-01-01');
 await expect(autofill.getByLabel('По',{exact:true})).toHaveValue('2026-01-01');
 await autofill.getByRole('button',{name:'Заполнить факторы'}).click();
 await expect(page).toHaveURL(/\/imports\?batch=fill-batch$/);
 expect(state.posted).toEqual([{path:'/factors/fill',body:{branch_id:'1',date_from:'2024-01-01',date_to:'2026-01-01',weather:true}}]);
});
