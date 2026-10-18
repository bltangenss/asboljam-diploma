import {test,expect,type Page} from '@playwright/test';

// Artificial browser fixtures: navigation must never replay requests or retain
// a position from another branch. No real API, database or business data is used.
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(done=>{resolve=done});return {promise,resolve}}

async function install(page:Page,section:'forecasts'|'procurement'){
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 const state={holdList:false,listStarted:deferred(),releaseList:deferred(),requests:[] as {path:string;method:string}[]};
 const rows=(branch:string)=>Array.from({length:40},(_,index)=>({id:`${section}-${branch}-${index}`,branch_id:branch,model:'seasonal_naive_7',target_date:'2026-01-01',created_at:'2026-01-01T08:00:00Z',data_origin:'SYNTHETIC',total_cost:'1000',shortage_count:0,version:1,status:'ready'}));
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  state.requests.push({path,method:request.method()});
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'navigation-user',organization_id:'navigation-organization',email:'navigation@example.invalid',role:'admin',branch_ids:['1','2']},csrf_token:'synthetic-navigation-only'};
  if(path==='/settings')json={organization:{id:'navigation-organization',name:'SYNTHETIC navigation fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:2,data_policy:'synthetic_only',can_import_branches:true}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Fixture branch one'},{branch_id:'2',branch_name:'Fixture branch two'}],total:2};
  if(path==='/forecasts'||path==='/plans'){
   const relevant=path===(section==='forecasts'?'/forecasts':'/plans');
   if(relevant&&state.holdList){state.listStarted.resolve();await state.releaseList.promise}
   const list=rows(url.searchParams.get('branch_id')||'1');json={items:list,total:list.length,next_cursor:null};
  }
  if(path.startsWith('/forecasts/'))json={id:path.split('/').at(-1),branch_id:'1',target_date:'2026-01-01',forecast_origin:'2025-12-31',model:'seasonal_naive_7',predictions:[],input_freshness:'unchanged',data_origin:'SYNTHETIC'};
  if(path.startsWith('/plans/'))json={id:path.split('/').at(-1),branch_id:'1',forecast_id:'source',status:'ready',version:1,input_freshness:'unchanged',result:{target_date:'2026-01-01',strategy:'point',budget:'1000',total_cost:'1000',remaining_budget:'0',shortage_count:0,requirements:[],lines:[],constraints_valid:true,solver_status:'optimal'}};
  await route.fulfill({json});
 });
 return state;
}

async function selectFilter(page:Page,section:'forecasts'|'procurement'){
 const filter=section==='forecasts'?page.getByLabel('По дате прогноза',{exact:true}):page.locator('.planning-history').getByRole('combobox',{name:'Статус',exact:true});
 if(section==='forecasts')await filter.fill('2026-01-01');else await filter.selectOption('ready');
 return filter;
}

const sheetScroll=(page:Page)=>page.locator('.planning-history-disclosure>.sheet').evaluate(element=>element.scrollTop);

async function openScrolledDetail(page:Page,section:'forecasts'|'procurement'){
 await page.goto('/'+section);
 await page.locator('.planning-history-disclosure>summary').click();
 await expect(page.locator('.planning-history tbody .row-link')).toHaveCount(40);
 await selectFilter(page,section);
 const link=page.locator('.planning-history tbody .row-link').nth(20);
 await link.scrollIntoViewIfNeeded();
 // The history opens as a sheet, so the list position is the sheet's own scroll offset.
 const y=await sheetScroll(page);expect(y).toBeGreaterThan(300);
 await link.click();await expect(page).toHaveURL(new RegExp('/'+section+'/'+section+'-1-20$'));
 await expect(page.getByTestId('input-provenance')).toBeVisible();
 return y;
}

for(const section of ['forecasts','procurement'] as const){
 for(const navigation of ['button','browser'] as const)test(`${section}: ${navigation} return restores the same-branch filter and list position`,async({page})=>{
  const state=await install(page,section),initialMode=await page.evaluate(()=>history.scrollRestoration);
  const y=await openScrolledDetail(page,section);
  if(navigation==='button')await page.locator('.page-heading').getByRole('button',{name:'Посмотреть всё',exact:true}).click();else await page.goBack();
  await expect(page.locator('.planning-history tbody .row-link')).toHaveCount(40);
  const filter=section==='forecasts'?page.getByLabel('По дате прогноза',{exact:true}):page.locator('.planning-history').getByRole('combobox',{name:'Статус',exact:true});
  await expect(filter).toHaveValue(section==='forecasts'?'2026-01-01':'ready');
  await expect.poll(()=>sheetScroll(page)).toBeGreaterThan(y-3);
  expect(await sheetScroll(page)).toBeLessThan(y+3);
  expect(await page.evaluate(()=>history.scrollRestoration)).toBe(initialMode);
  expect(state.requests.filter(request=>request.method!=='GET')).toEqual([]);
 });

 test(`${section}: changing branch from detail clears the old list position and filter`,async({page})=>{
  await install(page,section);await openScrolledDetail(page,section);
  await page.getByLabel('Филиал',{exact:true}).selectOption('2');
  await expect(page).toHaveURL(new RegExp('/'+section+'$'));
  await expect(page.locator('.planning-history tbody .row-link')).toHaveCount(40);
  const filter=section==='forecasts'?page.getByLabel('По дате прогноза',{exact:true}):page.locator('.planning-history').getByRole('combobox',{name:'Статус',exact:true});
  await expect(section==='forecasts'?filter:page.locator('.planning-history select')).toHaveValue('');
  await expect(page.locator('.planning-history-disclosure')).not.toHaveAttribute('open','');
  await expect.poll(()=>page.evaluate(()=>window.scrollY)).toBeLessThan(3);
 });
}

for(const interaction of ['wheel','key'] as const)test(`pending restoration stops when the user uses ${interaction} before a delayed list response`,async({page})=>{
 const state=await install(page,'forecasts');const y=await openScrolledDetail(page,'forecasts');
 state.holdList=true;
 await page.locator('.page-heading').getByRole('button',{name:'Посмотреть всё',exact:true}).click();
 await state.listStarted.promise;
 if(interaction==='wheel')await page.mouse.wheel(0,100);else await page.keyboard.press('Home');
 state.releaseList.resolve();
 await expect(page.locator('.planning-history tbody .row-link')).toHaveCount(40);
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 expect(await sheetScroll(page)).toBeLessThan(y-100);
 expect(await page.evaluate(()=>history.scrollRestoration)).toBe('auto');
});
