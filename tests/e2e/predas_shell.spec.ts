import {test,expect,type Page} from '@playwright/test';
import {openProfile} from './navigation';

// Synthetic browser contract for the Predas shell: a light sign-in, five plain sections,
// the establishment profile in the account menu and the demo data offer of an empty cabinet.
const almaty={code:'almaty',name:{kk:'Алматы',ru:'Алматы'},region:{kk:'Алматы қаласы',ru:'г. Алматы'},timezone:'Asia/Almaty'};
const types={cafe:{kk:'Кафе',ru:'Кафе'},canteen:{kk:'Асхана',ru:'Столовая'}};

async function install(page:Page,{empty=false}:{empty?:boolean}={}){
 const state={loaded:!empty,posted:[] as {path:string;body:any}[]};
 const user={id:'owner',organization_id:'org-new',email:'owner@example.invalid',role:'admin',branch_ids:['1']};
 const context=()=>({version:1,mode:'synthetic_fixed',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Almaty',currency:'KZT',branch_id:'1',
  history_start:state.loaded?'2024-01-01':null,history_end:state.loaded?'2025-12-31':null,forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',
  inventory_dates:state.loaded?['2026-01-01']:[],dates_editable:false,operations_enabled:true,business_date:null,source:null});
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  if(request.method()!=='GET'){
   state.posted.push({path,body:request.postDataJSON()});
   if(path==='/demo-data'){state.loaded=true;return route.fulfill({json:{source_branch:'2',city_code:'almaty',rows:{daily_sales:8772},history_start:'2024-01-01',history_end:'2025-12-31',target_date:'2026-01-01'}});}
   return route.fulfill({status:400,json:{detail:{code:'FIXTURE_UNEXPECTED_MUTATION'}}});
  }
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user,csrf_token:'synthetic-csrf'};
  if(path==='/settings')json={organization:{id:'org-new',name:'Алматы кофе',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'self_registration'},onboarding:{branch_count:1,data_policy:'synthetic_only'},data_context:url.searchParams.has('branch_id')?context():{...context(),branch_id:null}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Алматы кофе'}],total:1};
  if(path==='/branch-profiles')json={items:[{branch_id:'1',city_code:'almaty',city:almaty,establishment_type:'cafe'}]};
  if(path==='/cities')json={items:[almaty],establishment_types:types};
  if(path==='/meals')json={items:[],total:state.loaded?12:0,next_cursor:null};
  if(path==='/dashboard')json={as_of:state.loaded?'2025-12-31':null,sold_portions:state.loaded?186:null,revenue:state.loaded?'325500':null,data_origin:'SYNTHETIC',inventory_known:state.loaded,inventory_date:state.loaded?'2026-01-01':null,warnings:[],history:[],top_meals:[],latest_plans:[]};
  await route.fulfill({json});
 });
 return state;
}

test('sign-in is light, bilingual and offers registration without horizontal scroll',async({page})=>{
 await page.route('**/api/v1/session/me',route=>route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED'}}}));
 await page.goto('/');
 await expect(page).toHaveTitle(/Predas/);
 await expect(page.locator('.login-top .logo-word')).toHaveText('predas');
 await expect(page.getByRole('heading',{name:'Жүйеге кіру'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Тіркелу'})).toBeVisible();
 expect(await page.locator('.login-page').evaluate(element=>getComputedStyle(element).backgroundColor)).toBe('rgb(255, 255, 255)');
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.getByRole('button',{name:'Тілді ауыстыру'}).click();
 await expect(page.getByRole('heading',{name:'Войти в систему'})).toBeVisible();
});

test('five sections in the header and the establishment profile in the account menu',async({page})=>{
 await install(page);
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 await page.goto('/dashboard');
 await expect(page.getByRole('navigation',{name:'Рабочий день',exact:true}).getByRole('button')).toHaveText(['Сегодня','Прогноз','Склад','Закупки','Данные']);
 await expect(page.locator('.cabinet-name')).toHaveText('Алматы кофе');
 await expect(page.locator('.cabinet-city')).toHaveText('Алматы');
 await openProfile(page);
 await expect(page).toHaveURL(/\/profile$/);
 await expect(page.locator('.profile-hero h1')).toHaveText('Алматы кофе');
 await expect(page.locator('.profile-hero')).toContainText('Кафе');
 await expect(page.locator('.settings-row').filter({has:page.getByRole('heading',{name:'Город',exact:true})}).locator('span')).toHaveText('Алматы · г. Алматы');
 // The automatic day factors are background information: folded until asked for.
 const factors=page.locator('.profile-factors');
 await expect(factors).toBeVisible();await expect(factors).not.toHaveAttribute('open','');
 await factors.locator('summary').click();await expect(factors.locator('.factor-catalogue')).toBeVisible();
 await page.getByRole('navigation',{name:'Навигация раздела'}).getByRole('link',{name:'Журнал действий',exact:true}).click();
 await expect(page).toHaveURL(/\/audit$/);
});

test('an empty cabinet loads demo data in one click and continues with the forecast',async({page})=>{
 const state=await install(page,{empty:true});
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 await page.goto('/dashboard');
 const start=page.getByTestId('get-started');
 await expect(start.getByRole('heading',{level:1})).toHaveText('Добро пожаловать, Алматы кофе!');
 await start.getByRole('button',{name:'Загрузить демо-данные'}).click();
 await expect(start).toHaveCount(0);
 await expect(page.locator('.next-action')).toBeVisible();
 expect(state.posted).toEqual([{path:'/demo-data',body:{branch_id:'1'}}]);
});
