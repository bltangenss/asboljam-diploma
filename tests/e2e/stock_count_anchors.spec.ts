import {test,expect,type Page,type Route} from '@playwright/test';

// These are artificial route fixtures. Live service invariants are checked separately.
type Recorded={path:string;method:string;body:any;key:string|undefined};
const oldLot={ingredient_id:'I-1',lot_id:'LOT-1',unit:'kg',expiry_date:'2026-01-31',on_hand_qty:'12.000000001'};
const newLot={...oldLot,on_hand_qty:'9.000000001'};
const differences=[{ingredient_id:'I-1',lot_id:'LOT-1',ledger:oldLot,counted:newLot,difference:'-3',status:'mismatch'}];
const origin={data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',source:null};
function fixture(role='admin'){return {role,version:2,baseline:'changed',effective:'changed',source:'unchanged',anchors:[] as any[],posts:0,requests:[] as Recorded[]}}
type State=ReturnType<typeof fixture>;
const task=async(page:Page,value:string)=>{await page.locator(`[data-stock-task="${value}"]`).click()};
const anchor=(page:Page)=>page.locator('#stock-count-anchors');
const reviewText='Күнді, барлық партияны, мөлшерді және айырмашылықты тексердім. Жаңа саналған қалдықты осы күннен бастап қолдануды растаймын.';
async function install(page:Page,state:State,intercept?:(route:Route,request:Recorded)=>Promise<boolean>){
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api/v1',''),body=req.postData()?req.postDataJSON():null;
  const recorded={path,method:req.method(),body,key:req.headers()['idempotency-key']};state.requests.push(recorded);
  if(intercept&&await intercept(route,recorded))return;
  const branch=url.searchParams.get('branch_id')||body?.branch_id||'B-1';
  if(path==='/session/me'){await route.fulfill({json:{user:{id:'anchor-user',email:'anchor@example.invalid',organization_id:'anchor-fixture',role:state.role,branch_ids:['B-1','B-2']},csrf_token:'anchor-fixture-only'}});return}
  if(path==='/settings'){await route.fulfill({json:{organization:{id:'anchor-fixture',name:'SYNTHETIC anchor fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:2},data_context:{version:1,mode:'synthetic_fixed',...origin,branch_id:branch,history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01','2026-01-02'],dates_editable:false,operations_enabled:true,business_date:null}}});return}
  if(path==='/branches'){await route.fulfill({json:{items:[{branch_id:'B-1',branch_name:'One'},{branch_id:'B-2',branch_name:'Two'}],total:2}});return}
  if(path==='/inventory'){await route.fulfill({json:{items:[{...oldLot,ingredient_name:'Artificial flour',snapshot_date:'2026-01-01'}],total:1}});return}
  if(path==='/stock/catalog'){await route.fulfill({json:{ingredients:[{ingredient_id:'I-1',ingredient_name:'Artificial flour',unit:'kg',yield_factor:'0.8'}],meals:[],...origin}});return}
  if(path==='/stock/ledger'){
   const selected=url.searchParams.get('opening_date')!,latest=state.anchors[0]||null,chosen=latest&&selected>=latest.count_date?latest:null;
   await route.fulfill({json:{ledger:{id:'ledger-'+branch,branch_id:branch,baseline_date:'2026-01-01',version:state.version},version:state.version,baseline_freshness:state.baseline,effective_freshness:state.effective,context_freshness:state.source,opening:{date:selected,rows:[chosen?newLot:oldLot],count_anchor:chosen,source_freshness:chosen?state.effective:state.baseline},latest:{through_business_date:'2026-01-01',rows:[latest?newLot:oldLot],count_anchor:latest,source_freshness:state.effective},public_context:origin}});return
  }
  if(path==='/stock/count-anchors/preview'){await route.fulfill({json:{operation:'count_anchor',ledger_id:'ledger-'+branch,branch_id:branch,version:state.version,anchor_sequence:1,count_date:body.count_date,through_movement_sequence:1,previous_fingerprint:'b'.repeat(64),balances_before:[oldLot],counted_rows:[newLot],differences,reason:body.reason,preview_fingerprint:'a'.repeat(64),public_context:origin}});return}
  if(path==='/stock/count-anchors'&&recorded.method==='POST'){state.posts++;state.version++;state.effective='unchanged';state.anchors.unshift({id:'anchor-one',sequence:1,ledger_version:state.version,count_date:body.count_date,through_movement_sequence:1,counted_rows:[newLot],differences,reason:body.reason,actor_id:'anchor-user',recorded_at:'2026-10-10T10:00:00Z'});await route.fulfill({json:{status:'anchored',anchor_id:'anchor-one',ledger_id:'ledger-'+branch,branch_id:branch,version:state.version,anchor_sequence:1,count_date:body.count_date}});return}
  if(path==='/stock/count-anchors'){await route.fulfill({json:{items:state.anchors,total:state.anchors.length,next_cursor:null}});return}
  if(path==='/stock/reconciliation'){await route.fulfill({json:{status:'matched',target_date:'2026-01-02',baseline_freshness:'changed',effective_freshness:'unchanged',context_freshness:'unchanged',count_anchor:state.anchors[0],lines:[{...differences[0],ledger:newLot,counted:newLot,difference:'0',status:'matched'}]}});return}
  await route.fulfill({json:{items:[],total:0,next_cursor:null}});
 });
}
async function enter(page:Page){await page.goto('/inventory');await expect(page.getByRole('heading',{name:'Қойма қозғалыстары',exact:true})).toBeVisible();await task(page,'reconciliation');await anchor(page).locator('summary').first().click()}
async function draft(page:Page){await anchor(page).getByLabel('Жаңа саналған кесінді күні',{exact:true}).fill('2026-01-02');await anchor(page).getByLabel('Жаңа қалдықты қабылдау себебі',{exact:true}).fill('Artificial corrected count')}
async function preview(page:Page){await anchor(page).getByRole('button',{name:'Қалдық айырмашылықтарын тексеру',exact:true}).click();await expect(anchor(page).getByRole('region',{name:'Қалдық айырмашылықтарын тексеру',exact:true})).toBeVisible()}
async function post(page:Page){await anchor(page).getByLabel(reviewText,{exact:true}).check();await anchor(page).getByRole('button',{name:'Жаңа қалдықты қабылдау',exact:true}).click()}

test('corrected baseline requires explicit anchor review, preserves decimal differences and former period',async({page})=>{
 const state=fixture();await install(page,state);await enter(page);await task(page,'receipt');await expect(page.locator('#stock-document').getByRole('button',{name:'Құжатты алдын ала тексеру',exact:true})).toBeDisabled();await task(page,'reconciliation');await draft(page);await preview(page);
 const view=anchor(page).getByRole('region',{name:'Қалдық айырмашылықтарын тексеру',exact:true});await expect(view).toContainText('12.000000001 kg');await expect(view).toContainText('9.000000001 kg');await expect(view).toContainText('-3');await expect(anchor(page).getByRole('button',{name:'Жаңа қалдықты қабылдау',exact:true})).toBeDisabled();expect(state.posts).toBe(0);
 await post(page);await expect(anchor(page).getByText('Жаңа саналған қалдық сақталды. Бұрынғы тарих өзгерген жоқ.',{exact:true})).toBeVisible();expect(state.posts).toBe(1);
 const sent=state.requests.find(r=>r.path==='/stock/count-anchors'&&r.method==='POST')!;expect(sent.body).toEqual({branch_id:'B-1',count_date:'2026-01-02',reason:'Artificial corrected count',expected_version:2,expected_fingerprint:'a'.repeat(64),acknowledge_differences:true});expect(sent.key).toBeTruthy();
 await task(page,'receipt');await expect(page.locator('#stock-document').getByRole('button',{name:'Құжатты алдын ала тексеру',exact:true})).toBeEnabled();await task(page,'balance');await expect(page.getByText('Таңдалған ескі күннің бастапқы деректері кейін түзетілген.',{exact:false})).toBeVisible();
 await page.getByLabel('Есептелген қалдық күні',{exact:true}).fill('2026-01-02');await expect(page.getByText('Есептелген қалдық күні: 02.01.2026 · Қабылданған саналған қалдық негізі: 02.01.2026',{exact:true})).toBeVisible();
 await task(page,'reconciliation');await page.getByLabel('Түгендеу күні',{exact:true}).fill('2026-01-02');await page.getByRole('button',{name:'Салыстыру',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'Сәйкес · 02.01.2026'})).toHaveClass(/success/);
});

test('editing anchor date or reason invalidates the old confirmation without posting',async({page})=>{
 const state=fixture();await install(page,state);await enter(page);await draft(page);await preview(page);await anchor(page).getByLabel(reviewText,{exact:true}).check();await anchor(page).getByLabel('Жаңа қалдықты қабылдау себебі',{exact:true}).fill('Another counted reason');await expect(anchor(page).getByRole('region',{name:'Қалдық айырмашылықтарын тексеру',exact:true})).toHaveCount(0);await preview(page);await anchor(page).getByLabel('Жаңа саналған кесінді күні',{exact:true}).fill('2026-01-03');await expect(anchor(page).getByLabel(reviewText,{exact:true})).toHaveCount(0);expect(state.posts).toBe(0);
});

test('uncertain anchor retry preserves command and key and locks competing mutations',async({page})=>{
 const state=fixture();let dropped=false;await install(page,state,async(route,r)=>{if(r.path!=='/stock/count-anchors'||r.method!=='POST')return false;if(!dropped){dropped=true;state.posts++;await route.abort('failed')}else await route.fulfill({json:{status:'anchored',anchor_id:'once',version:3}});return true});
 await enter(page);await draft(page);await preview(page);await post(page);await expect(anchor(page).getByRole('button',{name:'Осы құжаттың нәтижесін растау',exact:true})).toBeEnabled();await expect(anchor(page).getByLabel('Жаңа саналған кесінді күні',{exact:true})).toBeDisabled();await expect(page.locator('[data-stock-task="balance"]')).toBeDisabled();await expect(page.getByRole('button',{name:'Журналды жаңарту',exact:true})).toBeDisabled();await anchor(page).getByRole('button',{name:'Осы құжаттың нәтижесін растау',exact:true}).click();await expect(anchor(page).getByText('Жаңа саналған қалдық сақталды. Бұрынғы тарих өзгерген жоқ.',{exact:true})).toBeVisible();const posts=state.requests.filter(r=>r.path==='/stock/count-anchors'&&r.method==='POST');expect(posts).toHaveLength(2);expect(posts[0]).toEqual(posts[1]);expect(state.posts).toBe(1);
});

test('version conflict discards anchor approval and uses refreshed ledger version',async({page})=>{
 const state=fixture();await install(page,state,async(route,r)=>{if(r.path!=='/stock/count-anchors'||r.method!=='POST')return false;state.version=3;await route.fulfill({status:409,json:{detail:{code:'STOCK_VERSION_CONFLICT',message:'Artificial version conflict'}}});return true});await enter(page);await draft(page);await preview(page);await post(page);await expect(anchor(page).getByLabel(reviewText,{exact:true})).toHaveCount(0);await expect(page.locator('.stock-ledger-technical')).toContainText('Нұсқа: 3');await preview(page);expect(state.requests.filter(r=>r.path==='/stock/count-anchors/preview').at(-1)?.body.expected_version).toBe(3);expect(state.posts).toBe(0);
});

for(const role of ['warehouse','analyst'])test(`${role} can inspect anchor history but cannot preview or accept`,async({page})=>{
 const state=fixture(role);state.anchors=[{id:'saved',sequence:1,ledger_version:3,count_date:'2026-01-02',through_movement_sequence:1,differences,reason:'Saved artificial count',actor_id:'manager',recorded_at:'2026-10-10T10:00:00Z'}];await install(page,state);await enter(page);await expect(anchor(page).getByText('Жаңа саналған қалдықты тек әкімші не менеджер қабылдайды.',{exact:true})).toBeVisible();await expect(anchor(page).getByRole('button',{name:'Қалдық айырмашылықтарын тексеру',exact:true})).toHaveCount(0);await anchor(page).getByText('02.01.2026 · Реті: 1 · Нұсқа: 3',{exact:true}).click();await expect(anchor(page)).toContainText('Saved artificial count');expect(state.requests.some(r=>r.method==='POST')).toBe(false);
});

test('changed source identity blocks anchor while baseline correction alone is recoverable',async({page})=>{
 const state=fixture();state.source='changed';await install(page,state);await enter(page);await expect(anchor(page).getByRole('button',{name:'Қалдық айырмашылықтарын тексеру',exact:true})).toBeDisabled();await expect(anchor(page).getByRole('alert')).toContainText('дерек көзін ауыстыруға болмайды');expect(state.requests.some(r=>r.path.endsWith('/preview'))).toBe(false);
});

for(const lang of ['kk','ru'])test(`${lang} explains incomplete anchor without converting missing lot to zero`,async({page})=>{
 const state=fixture();await page.addInitScript(value=>localStorage.setItem('asboljam-language',value),lang);await install(page,state,async(route,r)=>{if(r.path!=='/stock/count-anchors/preview')return false;await route.fulfill({status:409,json:{detail:{code:'STOCK_ANCHOR_INCOMPLETE',message:'Internal English'}}});return true});await page.goto('/inventory');await task(page,'reconciliation');await anchor(page).locator('summary').first().click();await anchor(page).getByLabel(lang==='kk'?'Жаңа саналған кесінді күні':'Дата нового посчитанного среза',{exact:true}).fill('2026-01-02');await anchor(page).getByLabel(lang==='kk'?'Жаңа қалдықты қабылдау себебі':'Причина принятия нового остатка',{exact:true}).fill('Count fixture reason');await anchor(page).getByRole('button',{name:lang==='kk'?'Қалдық айырмашылықтарын тексеру':'Проверить расхождения остатков',exact:true}).click();await expect(anchor(page).getByRole('alert')).toContainText(lang==='kk'?'нақты 0':'явный 0');await expect(anchor(page).getByRole('alert')).not.toContainText('Internal English');expect(state.posts).toBe(0);
});

test('late anchor preview from former branch is ignored',async({page})=>{
 const state=fixture();let release!:()=>void,started!:()=>void;const waiting=new Promise<void>(done=>release=done),ready=new Promise<void>(done=>started=done);await install(page,state,async(route,r)=>{if(r.path!=='/stock/count-anchors/preview')return false;started();await waiting;await route.fulfill({json:{...r.body,preview_fingerprint:'a'.repeat(64),differences}});return true});await enter(page);await draft(page);await anchor(page).getByRole('button',{name:'Қалдық айырмашылықтарын тексеру',exact:true}).click();await ready;await page.getByLabel('Бөлімше',{exact:true}).selectOption('B-2');release();await task(page,'reconciliation');await anchor(page).locator('summary').first().click();await expect(anchor(page).getByLabel('Жаңа қалдықты қабылдау себебі',{exact:true})).toHaveValue('');await expect(anchor(page).getByLabel(reviewText,{exact:true})).toHaveCount(0);expect(state.posts).toBe(0);
});

test('Russian anchor preview fits 390px viewport with explicit before, after and difference',async({page})=>{
 const state=fixture();await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));await page.setViewportSize({width:390,height:844});await install(page,state);await page.goto('/inventory');await task(page,'reconciliation');await anchor(page).locator('summary').first().click();await anchor(page).getByLabel('Дата нового посчитанного среза',{exact:true}).fill('2026-01-02');await anchor(page).getByLabel('Причина принятия нового остатка',{exact:true}).fill('Искусственный исправленный остаток');await anchor(page).getByRole('button',{name:'Проверить расхождения остатков',exact:true}).click();await expect(anchor(page).getByRole('columnheader',{name:'По прежней основе',exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);await page.screenshot({path:'.cache/stock-anchor-ru-mobile.png',fullPage:true});
});

test('closed prior movements cannot be reversed and movement date starts at the latest count',async({page})=>{
 const state=fixture();state.effective='unchanged';state.anchors=[{id:'saved',sequence:1,ledger_version:3,count_date:'2026-01-02',through_movement_sequence:1,differences,reason:'Accepted count'}];
 await install(page,state,async(route,r)=>{if(r.path!=='/stock/movements')return false;await route.fulfill({json:{items:[{id:'old-receipt',sequence:1,kind:'receipt',business_date:'2026-01-01',source_reference:'BEFORE',reason:'Artificial receipt',entries:[],before_count_anchor:true}],total:1,next_cursor:null}});return true});await enter(page);await expect(page.getByRole('button',{name:'Кері жазба жасау',exact:true})).toHaveCount(0);await task(page,'history');await expect(page.getByRole('region',{name:'Өткізілген құжаттар',exact:true})).toContainText('қабылданған жаңа қалдыққа дейінгі кезеңге');await task(page,'receipt');await expect(page.locator('#stock-document').getByLabel('Операцияның бизнес күні',{exact:true})).toHaveAttribute('min','2026-01-02');
});
