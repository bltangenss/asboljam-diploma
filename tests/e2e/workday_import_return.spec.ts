import {test,expect,type Page} from '@playwright/test';

// Synthetic route fixtures exercise confirmed receipts and navigation, not CSV parser or DB atomicity.
type Kind='inventory_lots'|'daily_sales';
type Reply='saved'|'lost-saved'|'unconfirmed';
const forecastId='day-forecast';
const stockRow={branch_id:'001',ingredient_id:'flour',lot_id:'LOT-1',snapshot_date:'2026-01-01',expiry_date:'2026-01-31',on_hand_qty:'3.000000001',unit:'kg',data_origin:'SYNTHETIC'};
const salesRow={date:'2025-12-31',branch_id:'001',meal_id:'meal',units_sold:2,available_portions:5,stockout_flag:0,is_open:1,promo:0,price_kzt:'100',data_origin:'SYNTHETIC'};
const csv=(kind:Kind)=>{const row=kind==='inventory_lots'?stockRow:salesRow;return Object.keys(row).join(',')+'\n'+Object.values(row).join(',')+'\n'};
const returnButton=(page:Page)=>page.getByRole('button',{name:'Күннің жоспарына оралу',exact:true});

async function install(page:Page,kind:Kind,reply:Reply='saved'){
 const row=kind==='inventory_lots'?stockRow:salesRow;
 const receipt={id:'workday-batch',status:'committed',row_count:1,inserted_rows:1,updated_rows:0,unchanged_rows:0};
 const batch={id:'workday-batch',kind,row_count:1,valid:true,status:'preview',mode:'append',reason:null,
  created_at:'2026-10-14T10:00:00Z',committed_at:null as string|null,can_commit:true,branch_ids:['001'],
  counts:{rows_seen:1,rows_checked:1,parsed:1,new:1,unchanged:0,updated:0,conflicting:0},
  scan_complete:true,stop_reason:null,errors_truncated:false,preview_limit:10,errors:[],preview:[row],
  changes:[{key:'synthetic-workday-key',operation:'insert',before:null,after:row}],
  source:{source_id:'manual_csv',mapping_version:'canonical-v1',timezone:'Asia/Qyzylorda',currency:'KZT',data_origin:'SYNTHETIC',provenance:'operator_bootstrap'},
  received_text_sha256:'a'.repeat(64),canonical_rows_sha256:'b'.repeat(64),receipt:null as typeof receipt|null};
 const requests:{path:string;method:string;body:any;key:string|undefined}[]=[];
 const origin={data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',source:null};
 const forecast={id:forecastId,branch_id:'001',target_date:'2026-01-01',model:'seasonal_naive_7',input_freshness:'unchanged',result:{target_date:'2026-01-01'}};
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  const body=request.postData()?request.postDataJSON():null,branch=url.searchParams.get('branch_id');
  requests.push({path,method:request.method(),body,key:request.headers()['idempotency-key']});
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'return-user',organization_id:'return-fixture',email:'return@example.invalid',role:'manager',branch_ids:['001','002']},csrf_token:'synthetic-return-csrf'};
  if(path==='/settings')json={organization:{id:'return-fixture',name:'SYNTHETIC receipt fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'operator_bootstrap'},onboarding:{branch_count:2,can_import_branches:false,data_policy:'synthetic_only'},data_context:{version:1,mode:'synthetic_fixed',...origin,branch_id:branch,history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:null}};
  if(path==='/branches')json={items:[{branch_id:'001',branch_name:'First artificial branch'},{branch_id:'002',branch_name:'Second artificial branch'}],total:2,next_cursor:null};
  if(path==='/imports')json={items:batch.status==='committed'?[batch]:[],total:batch.status==='committed'?1:0,next_cursor:null};
  if(path==='/imports/preview')json=batch;
  if(path==='/imports/workday-batch')json=batch;
  if(path==='/imports/workday-batch/commit'){
   if(reply==='unconfirmed'){await route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE',message:'Artificial unavailable response'}}});return}
   Object.assign(batch,{status:'committed',can_commit:false,committed_at:'2026-10-14T10:01:00Z',receipt});
   if(reply==='lost-saved'){await route.abort('failed');return}
   json=receipt;
  }
  if(path==='/inventory')json={items:batch.status==='committed'?[{...stockRow,ingredient_name:'Artificial flour'}]:[],total:batch.status==='committed'?1:0,next_cursor:null};
  if(path==='/stock/ledger')json={ledger:null,version:null,baseline_freshness:'unknown',context_freshness:'unchanged',public_context:origin};
  if(path==='/stock/catalog')json={ingredients:[{ingredient_id:'flour',ingredient_name:'Artificial flour',unit:'kg'}],meals:[],...origin};
  if(path==='/forecasts')json={items:[forecast],total:1,next_cursor:null};
  if(path==='/forecasts/'+forecastId)json=forecast;
  await route.fulfill({json});
 });
 return {requests,batch};
}

async function confirmImport(page:Page,kind:Kind){
 await expect(returnButton(page)).toHaveCount(0);
 await expect(page.getByLabel('Деректер',{exact:true})).toHaveValue(kind);
 await page.getByLabel('CSV файлын таңдаңыз').setInputFiles({name:'synthetic-workday.csv',mimeType:'text/csv',buffer:Buffer.from(csv(kind))});
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
 await expect(returnButton(page)).toHaveCount(0);
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
}

for(const reply of ['saved','lost-saved'] as const)test(`confirmed ${reply} inventory receipt returns with the same branch and forecast`,async({page})=>{
 const state=await install(page,'inventory_lots',reply);
 await page.goto('/imports?kind=inventory_lots&return=inventory&return_branch=001&forecast='+forecastId);
 await confirmImport(page,'inventory_lots');
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 expect(state.batch.receipt).toMatchObject({inserted_rows:1,status:'committed'});
 const commits=state.requests.filter(request=>request.path.endsWith('/commit'));expect(commits).toHaveLength(1);expect(commits[0].key).toBeTruthy();
 expect(state.requests.find(request=>request.path==='/imports/preview')?.body).toMatchObject({kind:'inventory_lots',csv_text:csv('inventory_lots'),mode:'append'});
 if(reply==='lost-saved')expect(state.requests.filter(request=>request.path==='/imports/workday-batch'&&request.method==='GET')).toHaveLength(1);
 await returnButton(page).click();await expect(page).toHaveURL(/\/inventory\?forecast=day-forecast$/);
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('001');
 const flow=page.getByRole('region',{name:'Жоспарды жалғастыру',exact:true});await expect(flow).toContainText('01.01.2026');
 await expect(flow.getByRole('button',{name:'Сатып алуды есептеуге',exact:true})).toBeVisible();
 expect(state.requests.some(request=>request.method==='POST'&&['/forecasts','/procurement'].includes(request.path))).toBe(false);
});

test('confirmed sales receipt returns to planning without creating a forecast',async({page})=>{
 const state=await install(page,'daily_sales');
 await page.goto('/imports?kind=daily_sales&return=forecasts&return_branch=001');
 await confirmImport(page,'daily_sales');await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await returnButton(page).click();await expect(page).toHaveURL(/\/forecasts$/);await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('001');
 expect(state.requests.filter(request=>request.path.endsWith('/commit'))).toHaveLength(1);
 expect(state.requests.some(request=>request.path==='/forecasts'&&request.method==='POST')).toBe(false);
});

test('changing branch after a confirmed receipt drops the former forecast return',async({page})=>{
 const state=await install(page,'inventory_lots');
 await page.goto('/imports?kind=inventory_lots&return=inventory&return_branch=001&forecast='+forecastId);
 await confirmImport(page,'inventory_lots');await expect(returnButton(page)).toBeVisible();
 await page.getByLabel('Бөлімше',{exact:true}).selectOption('002');
 await expect(returnButton(page)).toHaveCount(0);await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Қалдықтарды қарау',exact:true}).click();await expect(page).toHaveURL(/\/inventory$/);
 await expect(page.getByLabel('Бөлімше',{exact:true})).toHaveValue('002');
 await expect(page.getByRole('region',{name:'Жоспарды жалғастыру',exact:true})).toHaveCount(0);
 expect(state.requests.some(request=>request.path==='/forecasts/'+forecastId)).toBe(false);
});

test('an unconfirmed commit never offers the planning return as a saved result',async({page})=>{
 const state=await install(page,'inventory_lots','unconfirmed');
 await page.goto('/imports?kind=inventory_lots&return=inventory&return_branch=001&forecast='+forecastId);
 await confirmImport(page,'inventory_lots');
 await expect(page.getByRole('alert')).toContainText('Импорттың сақталғаны расталмады.');
 await expect(returnButton(page)).toHaveCount(0);await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toHaveCount(0);
 expect(state.batch.status).toBe('preview');expect(state.batch.receipt).toBeNull();
 expect(state.requests.filter(request=>request.path.endsWith('/commit'))).toHaveLength(1);
});
