import {test,expect,type Page,type Route} from '@playwright/test';

const csv='date,branch_id,meal_id,units_sold,available_portions,stockout_flag,is_open,promo,price_kzt,data_origin\n2025-12-31,001,meal,2,5,0,1,0,100,SYNTHETIC\n';
const row={date:'2025-12-31',branch_id:'001',meal_id:'meal',units_sold:2,available_portions:5,stockout_flag:0,is_open:1,promo:0,price_kzt:'100',data_origin:'SYNTHETIC'};
function batch(id='batch-1',overrides:Record<string,unknown>={}) {
 return {id,kind:'daily_sales',row_count:1,valid:true,status:'preview',mode:'append',reason:null,
  created_at:'2026-09-29T10:00:00Z',committed_at:null,can_commit:true,
  counts:{rows_seen:1,rows_checked:1,parsed:1,new:1,unchanged:0,updated:0,conflicting:0},
  scan_complete:true,stop_reason:null,errors_truncated:false,preview_limit:10,errors:[],preview:[row],
  changes:[{key:'["2025-12-31","001","meal"]',operation:'insert',before:null,after:row}],
  source:{source_id:'manual_csv',mapping_version:'canonical-v1',declared_original_sha256:null,timezone:'Asia/Almaty',currency:'KZT',data_origin:'SYNTHETIC',provenance:'operator_bootstrap'},
  received_text_sha256:'a'.repeat(64),canonical_rows_sha256:'b'.repeat(64),receipt:null,...overrides};
}
type Batch=ReturnType<typeof batch>;
function receipt(id:string,updated=0,unchanged=0) {return {id,status:'committed',row_count:1,inserted_rows:updated||unchanged?0:1,updated_rows:updated,unchanged_rows:unchanged}}
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(done=>{resolve=done});return {promise,resolve}}
async function install(page:Page,options:{role?:string;history?:Batch[];intercept?:(route:Route,path:string)=>Promise<boolean>}={}) {
 const user={id:'fixture-user',email:'fixture@example.invalid',role:options.role||'admin',organization_id:'fixture-org',branch_ids:['001','002']};
 const requests:{path:string;method:string;body:any;key:string|undefined}[]=[];
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname.replace('/api/v1','');
  requests.push({path,method:request.method(),body:request.postData()?request.postDataJSON():null,key:request.headers()['idempotency-key']});
  if(options.intercept&&await options.intercept(route,path))return;
  if(path==='/session/me'){await route.fulfill({json:{user,csrf_token:'fixture-import-csrf'}});return}
  if(path==='/settings'){await route.fulfill({json:{organization:{id:user.organization_id,name:'Synthetic import fixture',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'operator_bootstrap'},onboarding:{branch_count:2,can_import_branches:user.role==='admin',data_policy:'synthetic_only'}}});return}
  if(path==='/branches'){await route.fulfill({json:{items:[{branch_id:'001',branch_name:'One'},{branch_id:'002',branch_name:'Two'}],total:2,next_cursor:null}});return}
  if(path==='/imports'){const history=options.history||[];await route.fulfill({json:{items:history,total:history.length,next_cursor:null}});return}
  if(path==='/imports/preview'){await route.fulfill({json:batch()});return}
  await route.fulfill({json:{items:[],total:0,next_cursor:null}});
 });
 return requests;
}
async function upload(page:Page){await page.getByLabel('CSV файлды таңдаңыз').setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:Buffer.from(csv)})}
async function preview(page:Page){await upload(page);await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click()}

test('lost commit reply recovers the saved receipt and history survives reload',async({page})=>{
 const saved:Batch[]=[],current=batch();let details=0;
 const requests=await install(page,{history:saved,intercept:async(route,path)=>{
  if(path==='/imports/batch-1/commit') {
   Object.assign(current,{status:'committed',can_commit:false,committed_at:'2026-09-29T10:01:00Z',receipt:receipt('batch-1')});saved.push(current);
   await route.abort('failed');return true;
  }
  if(path==='/imports/batch-1'){details++;await route.fulfill({json:current});return true}
  return false;
 }});
 await page.goto('/imports');await preview(page);
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 expect(details).toBe(1);expect(requests.filter(item=>item.path.endsWith('/commit'))).toHaveLength(1);
 await page.reload();await page.getByRole('button',{name:'Импортты ашу batch-1',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toHaveCount(0);
 await page.getByText('Импорттың дерек көзі',{exact:true}).click();
 await expect(page.getByText('Сервер алған CSV мәтінінің SHA256 хэші',{exact:true})).toBeVisible();
 await expect(page.getByText('a'.repeat(64),{exact:true})).toBeVisible();
 expect(requests.filter(item=>item.path.endsWith('/commit'))).toHaveLength(1);
});

test('retrying an unconfirmed commit reuses its idempotency key',async({page})=>{
 let attempts=0;
 const requests=await install(page,{intercept:async(route,path)=>{
  if(path==='/imports/batch-1/commit') {
   if(++attempts===1)await route.fulfill({status:503,json:{detail:{code:'UNAVAILABLE',message:'Unavailable'}}});
   else await route.fulfill({json:receipt('batch-1')});return true;
  }
  if(path==='/imports/batch-1'){await route.fulfill({json:batch()});return true}
  return false;
 }});
 await page.goto('/imports');await preview(page);await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByRole('button',{name:'Импорт күйін тексеру',exact:true})).toBeVisible();
 await expect(page.getByRole('alert')).toContainText('Импорттың сақталғаны расталмады.');
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 const commits=requests.filter(item=>item.path.endsWith('/commit'));
 expect(commits).toHaveLength(2);expect(commits[0].key).toBeTruthy();expect(commits[1].key).toBe(commits[0].key);
});

test('correction requires reason, before-after review and explicit confirmation',async({page})=>{
 const original=batch('original',{status:'committed',can_commit:false,receipt:receipt('original')});
 const revised={...row,units_sold:3};
 const correction=batch('correction',{mode:'correction',reason:'Corrected fixture count',counts:{rows_seen:1,rows_checked:1,parsed:1,new:0,unchanged:0,updated:1,conflicting:0},preview:[revised],changes:[{key:'["2025-12-31","001","meal"]',operation:'update',before:row,after:revised}]});
 const requests=await install(page,{history:[original],intercept:async(route,path)=>{
  if(path==='/imports/original'){await route.fulfill({json:original});return true}
  if(path==='/imports/preview'){await route.fulfill({json:correction});return true}
  if(path==='/imports/correction/commit'){await route.fulfill({json:receipt('correction',1)});return true}
  return false;
 }});
 await page.goto('/imports');await page.getByRole('button',{name:'Импортты ашу original',exact:true}).click();
 await page.getByRole('button',{name:'Осы импортты түзету',exact:true}).click();
 await expect(page.getByLabel('Импорт режимі',{exact:true})).toHaveValue('correction');
 await upload(page);await expect(page.getByRole('button',{name:'Алдын ала қарау',exact:true})).toBeDisabled();
 await page.getByLabel('Түзету себебі',{exact:true}).fill('Corrected fixture count');
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
 const result=page.getByRole('region',{name:'Импорт нәтижесі',exact:true});
 await expect(result.getByRole('columnheader',{name:'Бұрын',exact:true})).toBeVisible();
 await expect(result.getByRole('row').filter({has:page.getByRole('cell',{name:'units_sold',exact:true})}).getByRole('cell')).toHaveText(['units_sold','2','3']);
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeDisabled();
 expect(requests.filter(item=>item.path.endsWith('/commit'))).toHaveLength(0);
 await page.getByRole('checkbox',{name:'Өзгерістер үлгісін, санын және түзету себебін тексердім.',exact:true}).check();
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 const body=requests.find(item=>item.path==='/imports/preview')!.body;
 expect(body.mode).toBe('correction');expect(body.reason).toBe('Corrected fixture count');expect(body.corrects_batch_id).toBe('original');
});

test('duplicate counts, source metadata and incomplete scans are explained without invented totals',async({page})=>{
 let count=0;
 const requests=await install(page,{intercept:async(route,path)=>{
  if(path!=='/imports/preview')return false;
  const current=++count===1?batch('duplicate',{counts:{rows_seen:1,rows_checked:1,parsed:1,new:0,unchanged:1,updated:0,conflicting:0}})
   :batch('partial',{valid:false,can_commit:false,scan_complete:false,stop_reason:'ERROR_LIMIT',errors_truncated:true,counts:{rows_seen:4,rows_checked:4,parsed:1,new:1,unchanged:0,updated:0,conflicting:0},errors:[{row_number:3,field:'units_sold',code:'INVALID_VALUE',message:'Invalid quantity'}]});
  await route.fulfill({json:current});return true;
 }});
 await page.goto('/imports');await page.getByText('Дерек көзі туралы мәлімет',{exact:true}).click();
 await page.getByLabel('Дерек көзінің коды',{exact:true}).fill('synthetic_pos');
 await page.getByLabel('Сәйкестендіру нұсқасы',{exact:true}).fill('fixture-v1');
 await preview(page);
 await expect(page.getByText('Бұл жолдар бұрын сақталған. Қайта импорттау деректерді көбейтпейді.',{exact:true})).toBeVisible();
 expect(requests.find(item=>item.path==='/imports/preview')!.body.source).toEqual({source_id:'synthetic_pos',mapping_version:'fixture-v1'});
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
 await expect(page.getByText('Файлды тексеру аяқталмады. Сандар тек орындалған тексерулерді көрсетеді.',{exact:false})).toBeVisible();
 await expect(page.getByText('Қателер тізімі қысқартылған. Қателерді түзетіп, файлды қайта тексеріңіз.',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'ҚАЗ',exact:true}).click();
 await expect(page.getByRole('heading',{name:'История импортов',exact:true})).toBeVisible();
 await expect(page.getByText('Проверка файла не завершена. Счётчики отражают только выполненные проверки.',{exact:false})).toBeVisible();
});

test('analyst can read an owned batch but has no correction or commit controls',async({page})=>{
 const owned=batch('owned',{status:'committed',can_commit:false,receipt:receipt('owned')});
 const requests=await install(page,{role:'analyst',history:[owned],intercept:async(route,path)=>{
  if(path==='/imports/owned'){await route.fulfill({json:owned});return true}return false;
 }});
 await page.goto('/imports');await page.getByRole('button',{name:'Импортты ашу owned',exact:true}).click();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Осы импортты түзету',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toHaveCount(0);
 await expect(page.getByLabel('CSV файлды таңдаңыз')).toBeDisabled();
 expect(requests.filter(item=>item.method==='POST')).toHaveLength(0);
});

test('a stale correction cannot be committed again without another preview',async({page})=>{
 const correction=batch('stale',{mode:'correction',reason:'Corrected fixture count',counts:{rows_seen:1,rows_checked:1,parsed:1,new:0,unchanged:0,updated:1,conflicting:0},changes:[{key:'fixture-key',operation:'update',before:row,after:{...row,units_sold:3}}]});
 const requests=await install(page,{intercept:async(route,path)=>{
  if(path==='/imports/preview'){await route.fulfill({json:correction});return true}
  if(path==='/imports/stale/commit'){await route.fulfill({status:409,json:{detail:{code:'STALE_IMPORT',message:'Changed'}}});return true}
  return false;
 }});
 await page.goto('/imports');await page.getByLabel('Импорт режимі',{exact:true}).selectOption('correction');
 await page.getByLabel('Түзету себебі',{exact:true}).fill('Corrected fixture count');await preview(page);
 await page.getByRole('checkbox',{name:'Өзгерістер үлгісін, санын және түзету себебін тексердім.',exact:true}).check();
 await page.getByRole('button',{name:'Импорттау',exact:true}).click();
 await expect(page.getByRole('alert')).toHaveText('Деректер тексеруден кейін өзгерді. Файлды қайта тексеріңіз.');
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'Алдын ала қарау',exact:true}).click();
 await expect(page.getByRole('checkbox')).not.toBeChecked();
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toBeDisabled();
 expect(requests.filter(item=>item.path.endsWith('/commit'))).toHaveLength(1);
 expect(requests.filter(item=>item.path==='/imports/preview')).toHaveLength(2);
});

test('a late history detail cannot replace a newly selected branch workspace',async({page})=>{
 const started=deferred(),release=deferred();let finished=false;
 await install(page,{history:[batch('old')],intercept:async(route,path)=>{
  if(path!=='/imports/old')return false;started.resolve();await release.promise;
  await route.fulfill({json:batch('old',{preview:[{marker:'STALE_BATCH_ROWS'}]})});finished=true;return true;
 }});
 await page.goto('/imports');await page.getByRole('button',{name:'Импортты ашу old',exact:true}).click();
 await started.promise;await page.getByLabel('Бөлімше',{exact:true}).selectOption('002');
 release.resolve();await expect.poll(()=>finished).toBe(true);
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 await expect(page.getByText('STALE_BATCH_ROWS',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toHaveCount(0);
});

test('input-source deep link loads its batch and a forbidden link replaces it with a clear error',async({page})=>{
 const linked=batch('linked',{status:'committed',can_commit:false,receipt:receipt('linked'),preview:[{marker:'AUTHORIZED_SOURCE_ROW'}]});
 const requests=await install(page,{role:'analyst',intercept:async(route,path)=>{
  if(path==='/imports/linked'){await route.fulfill({json:linked});return true}
  if(path==='/imports/unavailable'){await route.fulfill({status:404,json:{detail:{code:'NOT_FOUND',message:'Unavailable'}}});return true}
  return false;
 }});
 await page.goto('/imports?batch=linked');
 await expect(page.getByText('AUTHORIZED_SOURCE_ROW',{exact:true})).toBeVisible();
 await expect(page.getByText('Деректер транзакциямен импортталды',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Импорттау',exact:true})).toHaveCount(0);
 await page.goto('/imports?batch=unavailable');
 await expect(page.getByRole('alert')).toHaveText('Импорт табылмады немесе оған қолжетімділік өзгерді.');
 await expect(page.getByText('AUTHORIZED_SOURCE_ROW',{exact:true})).toHaveCount(0);
 expect(requests.filter(item=>item.method==='POST')).toHaveLength(0);
});
