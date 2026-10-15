import {test,expect,type Page} from '@playwright/test';

const forecastId='guard-forecast',detail='/forecasts/'+forecastId;
const forecast={id:forecastId,branch_id:'1',model:'rolling_mean_28',target_date:'2026-01-01',forecast_origin:'2025-12-31',input_freshness:'unchanged',data_origin:'SYNTHETIC',predictions:[{meal_id:'one',meal_name:'Сорпа',point_forecast:10.2,p10:null,p50:null,p90:null}]};
const origin={data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',source:null};
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(done=>{resolve=done});return{promise,resolve}}
async function install(page:Page,mode:'success'|'lost'|'pending'='success',lang:'ru'|'kk'='ru'){
 await page.addInitScript(value=>localStorage.setItem('asboljam-language',value),lang);
 const state={posts:[] as {path:string;body:any;key?:string}[],docs:[] as any[],release:deferred(),started:deferred(),revoke:false,account:'guard-user'};
 const receipts=new Map<string,any>();let failed=false;
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  const user=()=>({id:state.account,organization_id:'guard-org',email:state.account+'@example.invalid',role:'manager',branch_ids:['1','2']});
  if(state.revoke&&path!=='/session/login')return route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED'}}});
  if(request.method()==='POST'){
   const body=request.postDataJSON(),key=request.headers()['idempotency-key'];state.posts.push({path,body,key});
   if(path==='/session/logout')return route.fulfill({status:204});
   if(path==='/session/login'){state.revoke=false;state.account='different-user';return route.fulfill({json:{user:user(),csrf_token:'different-artificial-csrf'}})}
   if(path==='/production-plans'){
    state.started.resolve();
    if(!key)throw new Error('Missing idempotency key');
    if(!receipts.has(key)){
     const document={...origin,id:'saved-guard',branch_id:'1',forecast_id:forecastId,target_date:'2026-01-01',name:body.name,reason:body.reason,created_at:'2026-10-15T01:00:00Z',actor_id:state.account,basis:'manual_portions',input_freshness:'unchanged',portions:body.portions.map((row:any)=>({...row,meal_name:'Сорпа',forecast_point:10.2}))};
     receipts.set(key,document);state.docs.push(document);
    }
    if(mode==='pending')await state.release.promise;
    if(state.revoke)return route.fulfill({status:401,json:{detail:{code:'AUTH_REQUIRED'}}});
    if(mode==='lost'&&!failed){failed=true;return route.abort('failed')}
    return route.fulfill({status:201,json:receipts.get(key)});
   }
   return route.fulfill({status:422,json:{detail:{code:'VALIDATION_ERROR'}}});
  }
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:user(),csrf_token:'artificial-guard-csrf'};
  if(path==='/settings')json={organization:{id:'guard-org',name:'Artificial guard fixture',status:'active',data_policy:'synthetic_only',timezone:origin.timezone,currency:'KZT'},onboarding:{branch_count:2,data_policy:'synthetic_only'},data_context:{version:1,mode:'synthetic_fixed',...origin,branch_id:url.searchParams.get('branch_id')||'1',history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:null}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Fixture one'},{branch_id:'2',branch_name:'Fixture two'}],total:2};
  if(path==='/meals')json={items:[{meal_id:'one',meal_name:'Сорпа'}],total:1};
  if(path==='/forecasts')json={items:[forecast],total:1};
  if(path==='/forecasts/'+forecastId)json=forecast;
  if(path==='/production-plans')json={items:state.docs,total:state.docs.length};
  if(path==='/production-plans/saved-guard')json=state.docs[0];
  if(path==='/stock/ledger')json={ledger:null,version:null,baseline_freshness:'unknown',context_freshness:'unchanged',public_context:origin};
  if(path==='/stock/catalog')json={ingredients:[],meals:[],...origin};
  await route.fulfill({json});
 });
 return state;
}
const editor=(page:Page)=>page.getByTestId('production-editor');
const guard=(page:Page)=>page.getByRole('dialog',{name:/Несохранённые изменения|Проверьте результат сохранения|Сақталмаған өзгерістер/});
const stay=(page:Page)=>guard(page).getByRole('button',{name:'Остаться в плане',exact:true});
const discard=(page:Page)=>guard(page).getByRole('button',{name:'Отменить изменения и перейти',exact:true});
const today=(page:Page)=>page.locator('.sidebar .nav-item').first();
const branch=(page:Page)=>page.getByLabel('Филиал',{exact:true});
const save=(page:Page)=>editor(page).getByRole('button',{name:'Сохранить новый вариант',exact:true});
const retry=(page:Page)=>editor(page).getByRole('button',{name:'Повторить и проверить сохранение',exact:true});
async function fill(page:Page){await page.getByTestId('production-planning').getByRole('spinbutton').fill('25');await editor(page).getByLabel('Название варианта',{exact:true}).fill('Сохранить этот черновик');await editor(page).getByLabel('Почему выбраны эти порции',{exact:true}).fill('Проверка защиты от потери команды');}
async function enterFromList(page:Page){await page.goto('/forecasts');await page.getByRole('button',{name:'Открыть прогноз дня',exact:true}).click();await expect(page).toHaveURL(new RegExp(detail+'$'));await expect(editor(page)).toBeVisible()}
async function hardGuard(page:Page){await expect(guard(page)).toBeVisible();await expect(discard(page)).toHaveCount(0);await stay(page).click();await expect(page).toHaveURL(new RegExp(detail+'$'))}

test('dirty sidebar navigation requires explicit discard, stay retains every field',async({page})=>{
 const state=await install(page);await page.setViewportSize({width:1440,height:1000});await page.goto(detail);await fill(page);await today(page).click();await expect(guard(page)).toBeVisible();await page.screenshot({path:'.cache/navigation-guard-visual/desktop-dirty.png'});await stay(page).click();await expect(editor(page).getByLabel('Название варианта',{exact:true})).toHaveValue('Сохранить этот черновик');
 await today(page).click();await discard(page).click();await expect(page).toHaveURL(/\/dashboard$/);expect(state.posts).toEqual([]);
 await page.goBack();await expect(editor(page)).toBeVisible();await expect(page.getByTestId('production-planning').getByRole('spinbutton')).toHaveValue('');
});

test('dirty branch change is atomic and applies only after discard',async({page})=>{
 await install(page);await page.goto(detail);await fill(page);await branch(page).selectOption('2');await expect(guard(page)).toBeVisible();await expect(branch(page)).toHaveValue('1');await stay(page).click();await expect(page).toHaveURL(new RegExp(detail+'$'));
 await branch(page).selectOption('2');await discard(page).click();await expect(branch(page)).toHaveValue('2');await expect(page).toHaveURL(/\/forecasts$/);
});

test('dirty logout does not send a mutation before explicit discard',async({page})=>{
 const state=await install(page);await page.goto(detail);await fill(page);await page.getByTitle('Выйти',{exact:true}).click();await expect(guard(page)).toBeVisible();expect(state.posts).toEqual([]);await stay(page).click();
 await page.getByTitle('Выйти',{exact:true}).click();await discard(page).click();await expect(page).toHaveURL(/\/login$/);expect(state.posts.filter(row=>row.path==='/session/logout')).toHaveLength(1);
});

test('lost reply survives menu, branch, Back and logout attempts; retry uses exact original key/body',async({page})=>{
 const state=await install(page,'lost');await page.setViewportSize({width:1440,height:1000});await enterFromList(page);await fill(page);await save(page).click();await expect(retry(page)).toBeVisible();
 await today(page).click();await expect(guard(page)).toBeVisible();await page.screenshot({path:'.cache/navigation-guard-visual/desktop-uncertain.png'});await hardGuard(page);
 await branch(page).selectOption('2');await hardGuard(page);await expect(branch(page)).toHaveValue('1');
 await page.goBack();await hardGuard(page);
 await page.getByTitle('Выйти',{exact:true}).click();await hardGuard(page);
 expect(state.posts).toHaveLength(1);await retry(page).click();await expect(page.getByTestId('production-saved')).toBeVisible();expect(state.posts).toHaveLength(2);expect(state.posts[1]).toEqual(state.posts[0]);expect(state.docs).toHaveLength(1);
 await page.getByRole('button',{name:'Проверить остатки',exact:true}).click();await expect(page).toHaveURL(/\/inventory\?forecast=guard-forecast&production_plan_id=saved-guard$/);await expect(guard(page)).toHaveCount(0);
});

test('pending save cannot unmount through any global path; receipt clears guard synchronously',async({page})=>{
 const state=await install(page,'pending');await enterFromList(page);await fill(page);await save(page).click();await state.started.promise;
 await today(page).click();await hardGuard(page);await branch(page).selectOption('2');await hardGuard(page);await page.goBack();await hardGuard(page);await page.getByTitle('Выйти',{exact:true}).click();await hardGuard(page);expect(state.posts).toHaveLength(1);
 state.release.resolve();await expect(page.getByTestId('production-saved')).toBeVisible();await expect(page).toHaveURL(/production_plan_id=saved-guard$/);await today(page).click();await expect(page).toHaveURL(/\/dashboard$/);await expect(guard(page)).toHaveCount(0);
});

test('receipt arriving during Back restitution is selected after the bounce without a stale dialog',async({page})=>{
 const state=await install(page,'pending');await enterFromList(page);await fill(page);await save(page).click();await state.started.promise;
 await page.evaluate(()=>{
  const original=history.go.bind(history);
  (window as any).__releaseBounce=null;
  history.go=(delta?:number)=>{if(delta&&delta>0){(window as any).__releaseBounce=()=>original(delta)}else original(delta)};
 });
 await page.goBack();await expect.poll(()=>page.evaluate(()=>typeof (window as any).__releaseBounce)).toBe('function');
 state.release.resolve();await expect(editor(page).getByLabel('Название варианта',{exact:true})).toHaveValue('');
 await page.evaluate(()=>(window as any).__releaseBounce());
 await expect(page).toHaveURL(/production_plan_id=saved-guard$/);await expect(page.getByTestId('production-saved')).toBeVisible();await expect(guard(page)).toHaveCount(0);expect(state.posts).toHaveLength(1);
});

test('Back decline preserves history length and Forward entries',async({page})=>{
 await install(page);await enterFromList(page);await fill(page);const length=await page.evaluate(()=>history.length);
 for(let count=0;count<2;count++){await page.goBack();await expect(guard(page)).toBeVisible();await stay(page).click();await expect(page).toHaveURL(new RegExp(detail+'$'))}
 expect(await page.evaluate(()=>history.length)).toBe(length);
 await editor(page).getByRole('button',{name:'Отменить несохранённые изменения',exact:true}).click();await page.goBack();await expect(page).toHaveURL(/\/forecasts$/);await page.goForward();await expect(page).toHaveURL(new RegExp(detail+'$'));expect(await page.evaluate(()=>history.length)).toBe(length);await expect(guard(page)).toHaveCount(0);
});

test('forced 401 cleanup bypasses pending guard and a new account never sees the old draft',async({page})=>{
 const state=await install(page,'lost');await page.goto(detail);await fill(page);await save(page).click();await expect(retry(page)).toBeVisible();state.revoke=true;await retry(page).click();await expect(page).toHaveURL(/\/login$/);await expect(guard(page)).toHaveCount(0);await expect(editor(page)).toHaveCount(0);
 await page.locator('input[type=email]').fill('different@example.invalid');await page.locator('input[type=password]').fill('artificial-browser-password');await page.getByRole('button',{name:'Войти в систему',exact:true}).click();await expect(page).toHaveURL(/\/dashboard$/);await expect(page.locator('.user-info')).toContainText('different-user');expect(state.posts.filter(row=>row.path==='/production-plans')).toHaveLength(1);
});

test('mobile drawer hands focus to guard dialog and Escape keeps the draft',async({page})=>{
 await install(page,'lost');await page.setViewportSize({width:390,height:844});await page.goto(detail);await fill(page);const menu=page.getByRole('button',{name:'Открыть меню',exact:true});await menu.click();await today(page).click();await expect(guard(page)).toBeVisible();await expect(stay(page)).toBeFocused();await page.screenshot({path:'.cache/navigation-guard-visual/mobile-dirty.png'});await expect(page.locator('.sidebar')).not.toHaveClass(/open/);await page.keyboard.press('Escape');await expect(guard(page)).toHaveCount(0);await expect(editor(page).getByLabel('Название варианта',{exact:true})).toHaveValue('Сохранить этот черновик');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await save(page).click();await expect(retry(page)).toBeVisible();await menu.click();await today(page).click();await expect(guard(page)).toBeVisible();await expect(stay(page)).toBeFocused();await expect(discard(page)).toHaveCount(0);await page.screenshot({path:'.cache/navigation-guard-visual/mobile-uncertain.png'});
});

test('dirty beforeunload is protected and Kazakh dialog is readable',async({page})=>{
 await install(page,'success','kk');await page.goto(detail);await page.getByTestId('production-planning').getByRole('spinbutton').fill('12');
 expect(await page.evaluate(()=>{const event=new Event('beforeunload',{cancelable:true});window.dispatchEvent(event);return event.defaultPrevented})).toBe(true);
 await today(page).click();await expect(page.getByRole('dialog',{name:'Сақталмаған өзгерістер',exact:true})).toBeVisible();await page.getByRole('button',{name:'Жоспарда қалу',exact:true}).click();
});

test('legacy entry without router index is restored without overwriting its state',async({page})=>{
 await install(page);await page.addInitScript(path=>{history.replaceState({legacy:'keep-list'},'','/forecasts');history.pushState({legacy:'keep-detail'},'',path)},detail);await page.goto('/forecasts');await fill(page);const length=await page.evaluate(()=>history.length);
 await page.goBack();await expect(guard(page)).toBeVisible();await stay(page).click();await expect(page).toHaveURL(new RegExp(detail+'$'));expect(await page.evaluate(()=>history.state.legacy)).toBe('keep-detail');
 await page.goBack();await expect(guard(page)).toBeVisible();await discard(page).click();await expect(page).toHaveURL(/\/forecasts$/);expect(await page.evaluate(()=>history.state.legacy)).toBe('keep-list');expect(await page.evaluate(()=>history.length)).toBe(length);await page.goForward();await expect(page).toHaveURL(new RegExp(detail+'$'));
});

test('legacy entry without native indexes restores a consistent URL and retains the uncertain receipt key',async({page})=>{
 const state=await install(page,'lost');await page.addInitScript(path=>{
  Object.defineProperty(window,'navigation',{value:undefined,configurable:true});
  history.replaceState({legacy:'keep-list'},'','/forecasts');history.pushState({legacy:'keep-detail'},'',path);
 },detail);await page.goto('/forecasts');await fill(page);await save(page).click();await expect(retry(page)).toBeVisible();
 await page.goBack();await expect(guard(page)).toContainText('Адрес старой записи истории браузера заменён');await expect(page).toHaveURL(new RegExp(detail+'$'));expect(await page.evaluate(()=>history.state.legacy)).toBe('keep-list');await stay(page).click();
 await expect(editor(page).getByLabel('Название варианта',{exact:true})).toHaveValue('Сохранить этот черновик');await retry(page).click();await expect(page.getByTestId('production-saved')).toBeVisible();expect(state.posts).toHaveLength(2);expect(state.posts[1]).toEqual(state.posts[0]);expect(state.docs).toHaveLength(1);
});

test('transient Back query cannot replace a copied draft during an unrelated rerender',async({page})=>{
 await install(page);await enterFromList(page);await fill(page);await save(page).click();await expect(page.getByTestId('production-saved')).toBeVisible();await page.getByRole('button',{name:'Изменить и сохранить новым вариантом',exact:true}).click();await fill(page);
 await page.evaluate(()=>{const original=history.go.bind(history);(window as any).__releaseBounce=null;history.go=(delta?:number)=>{if(delta&&delta>0)(window as any).__releaseBounce=()=>original(delta);else original(delta)}});
 await page.goBack();await expect.poll(()=>page.evaluate(()=>typeof (window as any).__releaseBounce)).toBe('function');await expect(page).toHaveURL(new RegExp(detail+'$'));await page.locator('.topbar .language').click();
 await expect(page.getByLabel('Сақталған нұсқа',{exact:true})).toHaveValue('saved-guard');await expect(editor(page).getByLabel('Нұсқа атауы',{exact:true})).toHaveValue('Сохранить этот черновик');await expect(page.getByTestId('production-planning').getByRole('spinbutton')).toHaveValue('25');
 await page.evaluate(()=>(window as any).__releaseBounce());await expect(page).toHaveURL(/production_plan_id=saved-guard$/);await expect(page.getByRole('dialog',{name:'Сақталмаған өзгерістер',exact:true})).toBeVisible();await page.getByRole('button',{name:'Жоспарда қалу',exact:true}).click();await expect(editor(page).getByLabel('Нұсқа атауы',{exact:true})).toHaveValue('Сохранить этот черновик');
});

test('forced session cleanup during Back restitution clears the editor before restoring the address',async({page})=>{
 const state=await install(page,'pending');await enterFromList(page);await fill(page);await save(page).click();await state.started.promise;
 await page.evaluate(()=>{const original=history.go.bind(history);(window as any).__releaseBounce=null;history.go=(delta?:number)=>{if(delta&&delta>0)(window as any).__releaseBounce=()=>original(delta);else original(delta)}});
 await page.goBack();await expect.poll(()=>page.evaluate(()=>typeof (window as any).__releaseBounce)).toBe('function');state.revoke=true;state.release.resolve();await expect(page.getByRole('button',{name:'Войти в систему',exact:true})).toBeVisible();await expect(editor(page)).toHaveCount(0);await expect(guard(page)).toHaveCount(0);
 await page.evaluate(()=>(window as any).__releaseBounce());await expect(page).toHaveURL(/\/login$/);await expect(page.getByTestId('production-saved')).toHaveCount(0);await expect(guard(page)).toHaveCount(0);
});

test('Back to the root address still opens Today and Forward keeps the accepted section',async({page})=>{
 await install(page);await page.goto('/');await expect(today(page)).toHaveAttribute('aria-current','page');await page.locator('.sidebar .nav-item').nth(1).click();await expect(page).toHaveURL(/\/forecasts$/);await page.goBack();await expect(page).toHaveURL(/\/$/);await expect(today(page)).toHaveAttribute('aria-current','page');await expect(page.locator('.breadcrumb strong')).toHaveText('Сегодня');await page.goForward();await expect(page).toHaveURL(/\/forecasts$/);
});
