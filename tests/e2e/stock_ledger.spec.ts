import {test,expect,type Page,type Route} from '@playwright/test';

// Artificial browser fixtures only; server atomicity is verified by the Python/HTTP suites.
type RequestRecord={path:string;method:string;body:any;key:string|undefined};
function fixture(role='admin',opened=true){return {role,opened,version:1,postCount:0,requests:[] as RequestRecord[],movements:[] as any[],recipes:[] as any[]}}
type State=ReturnType<typeof fixture>;
const lot={ingredient_id:'I-1',lot_id:'LOT-1',unit:'kg',expiry_date:'2026-01-31',on_hand_qty:'10.000000001'};
const origin={data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Almaty',currency:'KZT',source:null};
async function install(page:Page,state:State,intercept?:(route:Route,request:RequestRecord)=>Promise<boolean>){
 await page.route('**/api/v1/**',async route=>{
  const r=route.request(),u=new URL(r.url()),path=u.pathname.replace('/api/v1',''),body=r.postData()?r.postDataJSON():null;
  const request={path,method:r.method(),body,key:r.headers()['idempotency-key']};state.requests.push(request);
  if(intercept&&await intercept(route,request))return;
  const branch=u.searchParams.get('branch_id')||body?.branch_id||'B-1';
  const user={id:'stock-user',email:'stock-fixture@example.invalid',organization_id:'stock-fixture',role:state.role,branch_ids:['B-1','B-2']};
  if(path==='/session/me'){await route.fulfill({json:{user,csrf_token:'stock-fixture-only'}});return}
  if(path==='/settings'){await route.fulfill({json:{organization:{id:user.organization_id,name:'Stock SYNTHETIC fixture',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'demo_seed'},onboarding:{branch_count:2},data_context:{version:1,mode:'synthetic_fixed',...origin,branch_id:branch,history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:null}}});return}
  if(path==='/branches'){await route.fulfill({json:{items:[{branch_id:'B-1',branch_name:'Branch one'},{branch_id:'B-2',branch_name:'Branch two'}],total:2,next_cursor:null}});return}
  if(path==='/inventory'){await route.fulfill({json:{items:[{...lot,ingredient_name:'Flour fixture',snapshot_date:'2026-01-01'}],total:1,next_cursor:null}});return}
  if(path==='/stock/catalog'){await route.fulfill({json:{ingredients:[{ingredient_id:'I-1',ingredient_name:'Flour fixture',unit:'kg',yield_factor:'0.8'},{ingredient_id:'I-2',ingredient_name:'Oil fixture',unit:'L',yield_factor:'1'}],meals:[{meal_id:'M-1',meal_name:'Meal fixture'}],...origin}});return}
  if(path==='/stock/ledger'){await route.fulfill({json:{ledger:state.opened?{id:'ledger-'+branch,branch_id:branch,baseline_date:'2026-01-01',version:state.version}:null,version:state.opened?state.version:null,baseline_freshness:state.opened?'unchanged':'unknown',context_freshness:'unchanged',opening:{date:u.searchParams.get('opening_date'),rows:state.opened?[lot]:null},latest:{through_business_date:'2026-01-01',rows:state.opened?[lot]:null},public_context:origin}});return}
  if(path==='/stock/open/preview'){await route.fulfill({json:{operation:'open',preview_fingerprint:'a'.repeat(64),baseline_date:body.baseline_date,baseline_rows:[lot],public_context:origin}});return}
  if(path==='/stock/open'){state.opened=true;state.postCount++;await route.fulfill({json:{ledger_id:'ledger-'+branch,branch_id:branch,version:1,baseline_date:body.baseline_date}});return}
  if(path==='/stock/movements/preview'){await route.fulfill({json:{operation:'movement',preview_fingerprint:'b'.repeat(64),version:state.version,entries:body.kind==='reversal'?[{...lot,quantity_delta:'-2'}]:(body.lines||[]).map((line:any)=>({...line,quantity_delta:['waste','recipe_usage'].includes(body.kind)?'-'+line.quantity:line.quantity})),balances_before:[lot],balances_after:[{...lot,on_hand_qty:'12.000000001'}],recipe_evidence:body.kind==='recipe_usage'?{rows:[{meal_id:'M-1',recipe_version:'v1',ingredient_id:'I-1',net_qty_per_portion:'0.08',yield_factor:'0.8'}]}:null,public_context:origin}});return}
  if(path==='/stock/movements'&&request.method==='POST'){state.version++;state.postCount++;state.movements.unshift({...body,id:'move-'+state.postCount,sequence:state.postCount,entries:body.lines?.map((line:any)=>({...line,quantity_delta:line.quantity}))||[]});await route.fulfill({json:{ledger_id:'ledger-'+branch,movement_id:'move-'+state.postCount,version:state.version,sequence:state.postCount}});return}
  if(path==='/stock/movements'){await route.fulfill({json:{items:state.movements,total:state.movements.length,next_cursor:null}});return}
  if(path==='/stock/recipes'&&request.method==='GET'){await route.fulfill({json:{items:state.recipes,total:state.recipes.length,limit:100,offset:0,data_context:origin}});return}
  if(path==='/stock/recipes/preview'){await route.fulfill({json:{...body,version:body.expected_version,next_version:body.expected_version+1,preview_fingerprint:'c'.repeat(64),rows:body.rows.map((row:any)=>({...row,unit:'kg',captured_yield_factor:'0.8'})),data_context:origin}});return}
  if(path==='/stock/recipes'&&request.method==='POST'){state.recipes.unshift({...body,id:'recipe-'+state.recipes.length,version:body.expected_version+1,rows:body.rows.map((row:any)=>({...row,unit:'kg',captured_yield_factor:'0.8'}))});await route.fulfill({json:state.recipes[0]});return}
  if(path==='/stock/recipe-requirements'){await route.fulfill({json:{requirements:[{ingredient_id:'I-1',unit:'kg',gross_required:'0.2'}],recipe_evidence:{rows:[]}}});return}
  if(path==='/stock/reconciliation'){await route.fulfill({json:{status:'unresolved',target_date:u.searchParams.get('count_date'),baseline_date:'2026-01-01',lines:[{ingredient_id:'I-1',lot_id:'LOT-1',ledger:lot,counted:null,difference:null,status:'missing_count'},{ingredient_id:'I-2',lot_id:'LOT-2',ledger:{unit:'L',on_hand_qty:'0'},counted:{unit:'L',on_hand_qty:'0'},difference:'0',status:'matched'}]}});return}
  await route.fulfill({json:{items:[],total:0,next_cursor:null}});
 });
}
async function task(page:Page,value:string){await page.locator(`[data-stock-task="${value}"]`).click()}
async function enter(page:Page){await page.goto('/inventory');await task(page,'receipt');await expect(page.getByRole('heading',{name:'Қойма қозғалыстары',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Құжатты алдын ала тексеру',exact:true})).toBeEnabled()}
const doc=(page:Page)=>page.locator('#stock-document');
async function receipt(page:Page){const form=doc(page);await form.getByLabel('Бастапқы құжат нөмірі',{exact:true}).fill('INVOICE-001');await form.getByLabel('Құжаттың себебі',{exact:true}).fill('Artificial receipt fixture');await form.getByLabel('Ингредиент 1',{exact:true}).selectOption('I-1');await form.getByLabel('Партия 1',{exact:true}).fill('LOT-1');await form.getByLabel('Жарамдылық мерзімі 1',{exact:true}).fill('2026-01-31');await form.getByLabel('Мөлшер 1',{exact:true}).fill('2.000000001')}
async function preview(page:Page){await doc(page).getByRole('button',{name:'Құжатты алдын ала тексеру',exact:true}).click();await expect(page.getByRole('region',{name:'Өткізер алдындағы тексеру',exact:true})).toBeVisible()}
async function confirm(page:Page){await page.getByLabel('Күнді, себебін, партиялар мен мөлшерлерді тексердім.',{exact:true}).check();await page.getByRole('button',{name:'Құжатты өткізу',exact:true}).click()}

test('explicit baseline preview keeps counted stock distinct and requires confirmation',async({page})=>{
 const state=fixture('admin',false);await install(page,state);await page.goto('/inventory');
 await expect(page.getByRole('heading',{name:'Саналған қор кесіндісі',exact:true})).toBeVisible();
 await page.getByLabel('Бастапқы саналған кесінді күні',{exact:true}).fill('2026-01-01');
 await page.getByLabel('Құжаттың себебі',{exact:true}).filter({visible:true}).fill('Baseline counted fixture');
 await page.getByRole('button',{name:'Журнал ашуды алдын ала тексеру',exact:true}).click();
 await expect(page.getByRole('button',{name:'Журналды ашу',exact:true})).toBeDisabled();expect(state.postCount).toBe(0);
 await expect(page.getByRole('region',{name:'Өткізер алдындағы тексеру',exact:true})).toContainText('10.000000001');
 await page.getByLabel('Күнді, себебін, партиялар мен мөлшерлерді тексердім.',{exact:true}).check();await page.getByRole('button',{name:'Журналды ашу',exact:true}).click();
 await expect(page.getByText('Құжат сақталды. Журнал жаңартылды.',{exact:true})).toBeVisible();expect(state.postCount).toBe(1);
 const post=state.requests.find(item=>item.path==='/stock/open')!;expect(post.body).toMatchObject({baseline_date:'2026-01-01',expected_fingerprint:'a'.repeat(64)});expect(post.key).toBeTruthy();
});

test('edited preview is invalidated; uncertain posting retries the identical command key and quantities',async({page})=>{
 const state=fixture();let dropped=false;
 await install(page,state,async(route,r)=>{if(r.path!=='/stock/movements'||r.method!=='POST')return false;if(!dropped){dropped=true;state.postCount++;state.version++;await route.abort('failed');return true}await route.fulfill({json:{ledger_id:'ledger-B-1',movement_id:'one',version:state.version,sequence:1}});return true});
 await enter(page);await receipt(page);await preview(page);
 await doc(page).getByLabel('Мөлшер 1',{exact:true}).fill('3.000000001');await expect(page.getByRole('region',{name:'Өткізер алдындағы тексеру',exact:true})).toHaveCount(0);
 await preview(page);await confirm(page);await expect(page.getByRole('button',{name:'Осы құжаттың нәтижесін растау',exact:true})).toBeEnabled();
 await expect(doc(page).getByLabel('Мөлшер 1',{exact:true})).toBeDisabled();await expect(page.locator('[data-stock-task="history"]')).toBeDisabled();await expect(doc(page)).toBeVisible();
 await page.getByRole('button',{name:'Осы құжаттың нәтижесін растау',exact:true}).click();await expect(page.getByText('Құжат сақталды. Журнал жаңартылды.',{exact:true})).toBeVisible();
 const posts=state.requests.filter(item=>item.path==='/stock/movements'&&item.method==='POST');expect(posts).toHaveLength(2);expect(posts[0].body).toEqual(posts[1].body);expect(posts[0].key).toBe(posts[1].key);expect(posts[0].body.lines[0].quantity).toBe('3.000000001');expect(state.postCount).toBe(1);
});

test('version conflict removes confirmation and reloads version before another preview',async({page})=>{
 const state=fixture();let reject=true;
 await install(page,state,async(route,r)=>{if(r.path==='/stock/movements'&&r.method==='POST'&&reject){reject=false;state.version=2;await route.fulfill({status:409,json:{detail:{code:'STOCK_VERSION_CONFLICT',message:'Changed'}}});return true}return false});
 await enter(page);await receipt(page);await preview(page);await confirm(page);
 await expect(page.getByRole('region',{name:'Өткізер алдындағы тексеру',exact:true})).toHaveCount(0);await expect(page.locator('.stock-ledger-technical')).toContainText('Нұсқа: 2');
 await preview(page);expect(state.requests.filter(item=>item.path==='/stock/movements/preview').at(-1)!.body.expected_version).toBe(2);expect(state.postCount).toBe(0);
});

test('analyst reads stock but has no document or recipe activation controls',async({page})=>{
 const state=fixture('analyst');await install(page,state);await page.goto('/inventory');await expect(page.getByText('Қойма деректері тек оқуға қолжетімді.',{exact:true})).toBeVisible();
 await expect(doc(page)).toHaveCount(0);await task(page,'recipes');await expect(page.getByRole('button',{name:'Толық рецептті тексеру',exact:true})).toHaveCount(0);
 expect(state.requests.some(item=>item.method==='POST')).toBe(false);
});

test('warehouse may receive and consume but cannot adjust, reverse or activate recipes',async({page})=>{
 const state=fixture('warehouse');state.movements=[{id:'old',sequence:1,kind:'receipt',business_date:'2026-01-01',source_reference:'OLD',reason:'Fixture',entries:[]}];await install(page,state);await enter(page);
 await expect(doc(page).getByLabel('Қозғалыс түрі',{exact:true}).locator('option')).toHaveCount(3);await expect(page.getByRole('button',{name:'Кері жазба жасау',exact:true})).toHaveCount(0);
 await task(page,'recipes');await expect(page.getByText('Рецептті тек әкімші не менеджер белсендіреді.',{exact:true})).toBeVisible();
});

test('reversal references the original document without caller supplied signed entries',async({page})=>{
 const state=fixture();state.movements=[{id:'original',sequence:1,kind:'receipt',business_date:'2026-01-01',source_reference:'OLD',reason:'Fixture',entries:[{...lot,quantity_delta:'2'}]}];await install(page,state);await enter(page);
 await task(page,'history');await page.getByRole('button',{name:'Кері жазба жасау',exact:true}).click();await doc(page).getByLabel('Бастапқы құжат нөмірі',{exact:true}).fill('REVERSE-001');await doc(page).getByLabel('Құжаттың себебі',{exact:true}).fill('Corrected original fixture');await preview(page);
 const body=state.requests.find(item=>item.path==='/stock/movements/preview')!.body;expect(body.kind).toBe('reversal');expect(body.reverses_id).toBe('original');expect(body.lines).toBeUndefined();
});

test('recipe activation previews frozen yield then consumption requests dated gross quantities',async({page})=>{
 const state=fixture();await install(page,state);await enter(page);await task(page,'recipes');const recipe=page.locator('details').filter({has:page.locator('summary',{hasText:'Күнге белсенді рецепттер'})}).first();
 await recipe.getByLabel('Тағам',{exact:true}).selectOption('M-1');await recipe.getByLabel('Жаңа рецепт нұсқасының атауы',{exact:true}).fill('v1.0 тест');await recipe.getByLabel('Қолданысқа енетін күн',{exact:true}).fill('2026-01-01');await recipe.getByLabel('Құжаттың себебі',{exact:true}).fill('Complete recipe fixture');await recipe.getByLabel('Ингредиент 1',{exact:true}).selectOption('I-1');await recipe.getByLabel('Бір порцияға нетто 1',{exact:true}).fill('0.08');await recipe.getByRole('button',{name:'Толық рецептті тексеру',exact:true}).click();
 const previewRegion=recipe.getByRole('region',{name:'Толық рецептті тексеру',exact:true});await expect(previewRegion).toContainText('0.8');await expect(recipe.getByRole('button',{name:'Рецептті белсендіру',exact:true})).toBeDisabled();
 await recipe.getByLabel('Рецепттің барлық ингредиенттерін, нетто мөлшерін, шығымын және күнін тексердім.',{exact:true}).check();await recipe.getByRole('button',{name:'Рецептті белсендіру',exact:true}).click();await expect(recipe.getByText('Рецепт нұсқасы сақталды. Бұрынғы құжаттар өзгерген жоқ.',{exact:true})).toBeVisible();
 expect(state.requests.find(item=>item.path==='/stock/recipes'&&item.method==='POST')!.body).toMatchObject({recipe_version:'v1.0 тест',expected_version:0,rows:[{ingredient_id:'I-1',net_qty_per_portion:'0.08'}]});
 await task(page,'consumption');await doc(page).getByLabel('Қозғалыс түрі',{exact:true}).selectOption('recipe_usage');await doc(page).getByLabel('Тағам 1',{exact:true}).selectOption('M-1');await doc(page).getByLabel('Шығысқа негіз болатын порциялар 1',{exact:true}).fill('2');await doc(page).getByRole('button',{name:'Күнге белсенді рецептті есептеу',exact:true}).click();await expect(doc(page).getByText('0.2',{exact:true})).toBeVisible();
 expect(state.requests.find(item=>item.path==='/stock/recipe-requirements')!.body).toEqual({branch_id:'B-1',business_date:'2026-01-01',portions:{'M-1':2}});
});

test('reconciliation keeps missing counts unknown and explicit zero visible',async({page})=>{
 const state=fixture();await install(page,state);await enter(page);await task(page,'reconciliation');await page.getByLabel('Түгендеу күні',{exact:true}).fill('2026-01-02');await page.getByRole('button',{name:'Салыстыру',exact:true}).click();
 const result=page.getByRole('region',{name:'Түгендеумен салыстыру',exact:true});await expect(result).toContainText('Саналған жол жоқ');await expect(result).toContainText('Белгісіз');await expect(result.getByText('0 L',{exact:true})).toHaveCount(2);expect(state.requests.find(item=>item.path==='/stock/reconciliation')!.method).toBe('GET');expect(state.postCount).toBe(0);
});

test('late preview from a former branch cannot arm a document in the new branch',async({page})=>{
 const state=fixture();let release!:()=>void,started!:()=>void;const waiting=new Promise<void>(done=>release=done),ready=new Promise<void>(done=>started=done);
 await install(page,state,async(route,r)=>{if(r.path!=='/stock/movements/preview')return false;started();await waiting;await route.fulfill({json:{operation:'movement',preview_fingerprint:'d'.repeat(64),entries:[],balances_after:[]}});return true});
 await enter(page);await receipt(page);await doc(page).getByRole('button',{name:'Құжатты алдын ала тексеру',exact:true}).click();await ready;await page.getByLabel('Бөлімше',{exact:true}).selectOption('B-2');await task(page,'receipt');await expect(doc(page).getByLabel('Бастапқы құжат нөмірі',{exact:true})).toHaveValue('');release();await expect(page.getByRole('region',{name:'Өткізер алдындағы тексеру',exact:true})).toHaveCount(0);expect(state.postCount).toBe(0);
});

test('matching quantities do not show healthy reconciliation after baseline evidence changed',async({page})=>{
 const state=fixture();await install(page,state,async(route,r)=>{if(r.path!=='/stock/reconciliation')return false;await route.fulfill({json:{status:'matched',target_date:'2026-01-02',baseline_freshness:'changed',context_freshness:'unchanged',lines:[{ingredient_id:'I-1',lot_id:'LOT-1',ledger:lot,counted:lot,difference:'0',status:'matched'}]}});return true});
 await enter(page);await task(page,'reconciliation');await page.getByLabel('Түгендеу күні',{exact:true}).fill('2026-01-02');await page.getByRole('button',{name:'Салыстыру',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'Бастапқы кесінді не дерек көзі өзгерген.'})).toHaveClass(/warning/);
});

test('failed new opening date never leaves the former date balance visible',async({page})=>{
 const state=fixture();await install(page,state,async(route,r)=>{if(r.path!=='/stock/ledger'||new URL(route.request().url()).searchParams.get('opening_date')!=='2026-01-02')return false;await route.fulfill({status:500,json:{detail:{code:'TEMPORARY',message:'Unavailable fixture'}}});return true});
 await enter(page);await task(page,'balance');const workspace=page.getByRole('region',{name:'Қойма қозғалыстары',exact:true});await expect(workspace.getByRole('heading',{name:'Күн басындағы есептелген қалдық',exact:true})).toBeVisible();await page.getByLabel('Есептелген қалдық күні',{exact:true}).fill('2026-01-02');await expect(workspace.getByRole('alert')).toContainText('Қойма журналын жүктеу мүмкін болмады.');await expect(workspace.getByRole('heading',{name:'Күн басындағы есептелген қалдық',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Саналған қор кесіндісі',exact:true})).toBeVisible();
});

test('a late opening-date reply cannot replace the newer selected balance',async({page})=>{
 const state=fixture();let release!:()=>void,started!:()=>void,delivered=false;const waiting=new Promise<void>(done=>release=done),ready=new Promise<void>(done=>started=done);
 await install(page,state,async(route,r)=>{if(r.path!=='/stock/ledger')return false;const selected=new URL(route.request().url()).searchParams.get('opening_date');if(selected==='2026-01-01')return false;if(selected==='2026-01-02'){started();await waiting}await route.fulfill({json:{ledger:{id:'ledger-B-1',branch_id:'B-1',baseline_date:'2026-01-01',version:1},version:1,baseline_freshness:'unchanged',context_freshness:'unchanged',opening:{date:selected,rows:[{...lot,on_hand_qty:selected==='2026-01-02'?'44':'99'}]},latest:{rows:[]},public_context:origin}});if(selected==='2026-01-02')delivered=true;return true});
 await enter(page);await task(page,'balance');await page.getByLabel('Есептелген қалдық күні',{exact:true}).fill('2026-01-02');await ready;await page.getByLabel('Есептелген қалдық күні',{exact:true}).fill('2026-01-03');const workspace=page.getByRole('region',{name:'Қойма қозғалыстары',exact:true});await expect(workspace.getByText('99',{exact:true})).toBeVisible();release();await expect.poll(()=>delivered).toBe(true);await expect(page.getByLabel('Есептелген қалдық күні',{exact:true})).toHaveValue('2026-01-03');await expect(workspace.getByText('99',{exact:true})).toBeVisible();await expect(workspace.getByText('44',{exact:true})).toHaveCount(0);
});

test('Russian stock forms stay within narrow viewport and preserve decimal strings',async({page})=>{
 const state=fixture();await install(page,state);await page.setViewportSize({width:390,height:844});await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));await page.goto('/inventory');await expect(page.getByRole('heading',{name:'Движения склада',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'Посчитанный срез остатков',exact:true})).toBeVisible();
 await expect(page.getByText('10.000000001',{exact:true}).first()).toBeVisible();await page.getByRole('button',{name:'Таблица',exact:true}).click();expect(await page.locator('.stock-counted-task table th').first().evaluate(element=>element.getBoundingClientRect().height)).toBeLessThan(100);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);await page.screenshot({path:'.cache/stock-ledger-ru-mobile.png',fullPage:true});
});

for(const language of ['kk','ru'])for(const code of ['STOCK_RECONCILIATION_REQUIRED','STOCK_RECIPE_NOT_ACTIVE'])test(`${language} procurement explains ${code} with the next stock action`,async({page})=>{
 const state=fixture();await page.addInitScript(value=>localStorage.setItem('asboljam-language',value),language);
 await install(page,state,async(route,r)=>{
  if(r.path==='/forecasts'){await route.fulfill({json:{items:[{id:'stock-forecast',model:'seasonal_naive_7',target_date:'2026-01-01'}],total:1}});return true}
  if(r.path==='/procurement'&&r.method==='POST'){await route.fulfill({status:409,json:{detail:{code,message:'Internal English service message'}}});return true}
  return false;
 });
 await page.goto('/procurement');await page.getByRole('button',{name:language==='kk'?'Есептеу':'Рассчитать',exact:true}).click();const alert=page.getByRole('alert');await expect(alert).toContainText(language==='kk'?'«Қойма»':'«Склад»');await expect(alert).toContainText(code==='STOCK_RECONCILIATION_REQUIRED'?(language==='kk'?'салыстырып':'сверьте'):(language==='kk'?'белсендіріңіз':'активируйте'));await expect(alert).not.toContainText('Internal English');expect(state.requests.filter(r=>r.path==='/procurement'&&r.method==='POST')).toHaveLength(1);
});


test('stock tasks show one workspace at a time and invalidate an unposted document preview',async({page})=>{
 const state=fixture();await install(page,state);await page.goto('/inventory');
 await expect(page.getByRole('heading',{name:'Саналған қор кесіндісі',exact:true})).toBeVisible();
 await expect(doc(page)).toBeHidden();await expect(page.locator('#stock-history')).toBeHidden();await expect(page.locator('#stock-reconciliation')).toBeHidden();
 await expect(page.locator('.stock-ledger-technical').locator('span')).toBeHidden();
 await task(page,'receipt');await expect(page.getByRole('heading',{name:'Саналған қор кесіндісі',exact:true})).toHaveCount(0);
 await receipt(page);await preview(page);await task(page,'history');
 await expect(doc(page)).toBeHidden();await expect(page.getByRole('region',{name:'Өткізер алдындағы тексеру',exact:true})).toHaveCount(0);
 await task(page,'receipt');await expect(doc(page).getByLabel('Бастапқы құжат нөмірі',{exact:true})).toHaveValue('INVOICE-001');
 await task(page,'consumption');await expect(doc(page).getByLabel('Қозғалыс түрі',{exact:true})).toHaveValue('recipe_usage');
 await expect(doc(page).getByLabel('Шығысқа негіз болатын порциялар 1',{exact:true})).toBeVisible();
 await task(page,'reconciliation');await expect(page.locator('#stock-reconciliation')).toBeVisible();await expect(doc(page)).toBeHidden();
 expect(state.postCount).toBe(0);
});

test('stock carries only a verified same-branch forecast to procurement and never claims readiness',async({page})=>{
 const state=fixture();await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 await install(page,state,async(route,r)=>{if(r.path!=='/forecasts/flow-forecast')return false;await route.fulfill({json:{id:'flow-forecast',branch_id:'B-1',target_date:'2026-01-01',input_freshness:'unchanged',result:{target_date:'2026-01-01'}}});return true});
 await page.goto('/inventory?forecast=flow-forecast');const flow=page.getByRole('region',{name:'Продолжение планирования'});
 await expect(flow).toContainText('День закупки: 01.01.2026');await expect(flow).toContainText('Наличие среза не подтверждает его полноту');
 await flow.getByRole('button',{name:'К расчёту закупки',exact:true}).click();await expect(page).toHaveURL(/\/procurement\?forecast=flow-forecast$/);
 expect(state.requests.some(r=>r.method==='POST')).toBe(false);
 await page.goto('/inventory?forecast=flow-forecast');await page.getByLabel('Филиал',{exact:true}).selectOption('B-2');
 await expect(flow).toContainText('Этот прогноз не подтверждён для выбранного филиала');await expect(flow.getByRole('button',{name:'К расчёту закупки',exact:true})).toHaveCount(0);
});

test('forecast target mismatch remains explicit and does not silently relabel the selected stock date',async({page})=>{
 const state=fixture();await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 await install(page,state,async(route,r)=>{if(r.path!=='/forecasts/other-day')return false;await route.fulfill({json:{id:'other-day',branch_id:'B-1',target_date:'2026-01-02',input_freshness:'changed'}});return true});
 await page.goto('/inventory?forecast=other-day');const flow=page.getByRole('region',{name:'Продолжение планирования'});
 await expect(flow).toContainText('Открыт срез на 01.01.2026. Для закупки нужен остаток на 02.01.2026.');await expect(flow).toContainText('Актуальность прогноза не подтверждена');
 await expect(page.getByLabel('Дата расчётного остатка',{exact:true})).toHaveValue('2026-01-01');
 await expect(flow.getByRole('button',{name:'Добавить посчитанный остаток',exact:true})).toBeVisible();
 expect(state.requests.some(r=>r.method==='POST')).toBe(false);
});
