import {test,expect,type Page,type Route} from '@playwright/test';

// Browser-mocked fixtures: no enterprise sales or credentials, no database writes.
type Sale={date:string;branch_id:string;meal_id:string;meal_name:string;units_sold:string;available_portions:string;price_kzt:string;is_open:string;stockout_flag:string};
const mealIds=['01','1','2','3','4','5','6','7','8'];
function sales(ids=mealIds,branch='001'):Sale[]{
 return Array.from({length:28},(_,i)=>new Date(Date.UTC(2025,11,4+i)).toISOString().slice(0,10)).flatMap(date=>ids.map(meal_id=>({date,branch_id:branch,meal_id,meal_name:'Dish '+meal_id,units_sold:date==='2025-12-31'?'0':'1',available_portions:'10',price_kzt:'1200',is_open:'1',stockout_flag:'0'})));
}
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(done=>{resolve=done});return {promise,resolve}}
async function install(page:Page,rows:Sale[],intercept?:(route:Route,url:URL)=>Promise<boolean>){
 const reads:URL[]=[];
 await page.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname.replace('/api/v1','');
  const empty={items:[],total:0,next_cursor:null,data_origin:'SYNTHETIC',scenario_date:'2026-01-01'};
  if(path==='/sales'){reads.push(url);if(intercept&&await intercept(route,url))return}
  if(path==='/session/me'){await route.fulfill({json:{user:{id:'sales-review',email:'sales@example.invalid',organization_id:'sales-fixture',role:'analyst',branch_ids:['001','002']},csrf_token:'fabricated-sales-csrf'}});return}
  if(path==='/settings'){await route.fulfill({json:{organization:{id:'sales-fixture',name:'Synthetic sales fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:2,can_import_branches:false,data_policy:'synthetic_only'}}});return}
  if(path==='/branches'){await route.fulfill({json:{...empty,items:[{branch_id:'001',branch_name:'First branch'},{branch_id:'002',branch_name:'Second branch'}],total:2}});return}
  if(path==='/meals'){await route.fulfill({json:{...empty,items:mealIds.map(meal_id=>({meal_id,meal_name:'Dish '+meal_id})),total:mealIds.length}});return}
  if(path==='/sales'){
   const params=url.searchParams,limit=Number(params.get('limit')),cursor=Number(params.get('cursor'));
   const selected=rows.filter(row=>row.branch_id===params.get('branch_id')&&(!params.get('meal_id')||row.meal_id===params.get('meal_id'))&&row.date>=(params.get('date_from')||'')&&row.date<=(params.get('date_to')||'9999-12-31')).sort((a,b)=>b.date.localeCompare(a.date)||b.meal_id.localeCompare(a.meal_id));
   await route.fulfill({json:{...empty,items:selected.slice(cursor,cursor+limit),total:selected.length,next_cursor:cursor+limit<selected.length?String(cursor+limit):null}});return;
  }
  await route.fulfill({json:empty});
 });
 return reads;
}
const overview=(page:Page)=>page.getByRole('region',{name:'Сатылым шолуы',exact:true});

test('period summary reads all pages, keeps exact meal IDs, and day mode includes true zeros',async({page})=>{
 const second=deferred(),entered=deferred();
 const reads=await install(page,sales(),async(route,url)=>{
  if(url.searchParams.get('limit')==='200'&&url.searchParams.get('cursor')==='200'){entered.resolve();await second.promise}
  return false;
 });
 await page.goto('/sales');await entered.promise;
 await expect(page.locator('tbody tr')).toHaveCount(50);
 await expect(overview(page)).toHaveAttribute('aria-busy','true');
 await expect(page.getByTestId('sales-period-total')).toHaveCount(0);
 second.resolve();
 await expect(page.getByTestId('sales-period-total')).toHaveText('243');
 await expect(page.getByTestId('sales-days-coverage')).toHaveText('28 / 28');
 await expect(overview(page)).toContainText('252 жол, барлық бет жүктелді');
 await expect(overview(page).locator('.sales-chart-point')).toHaveCount(28);
 expect(reads.some(url=>url.searchParams.get('cursor')==='200'&&url.searchParams.get('limit')==='200')).toBeTruthy();
 await page.getByLabel('Тағам',{exact:true}).selectOption('01');
 await expect(page.getByTestId('sales-period-total')).toHaveText('27');
 await expect(page.locator('tbody tr')).toHaveCount(28);
 await expect(page.getByRole('link',{name:'CSV жүктеу',exact:true})).toHaveAttribute('href',/meal_id=01/);
 await page.getByRole('button',{name:'Бір күн',exact:true}).click();
 await expect(page.getByLabel('Күн',{exact:true})).toHaveValue('2025-12-31');
 await expect(overview(page).getByRole('heading',{name:'Бір күнде не сатылды?',exact:true})).toBeVisible();
 await expect(page.getByTestId('sales-period-total')).toHaveText('0');
 await expect(page.getByTestId('sales-days-coverage')).toHaveText('1 / 1');
 await expect(overview(page).locator('.sales-chart-point')).toHaveCount(1);
 await expect(overview(page).locator('.sales-chart-point')).toHaveAttribute('cy','184');
 await expect(page.locator('tbody tr')).toHaveCount(1);
 await page.getByRole('button',{name:'Кезең',exact:true}).click();
 await expect(page.getByLabel('Бастап',{exact:true})).toHaveValue('2025-12-04');
 await expect(page.getByLabel('Дейін',{exact:true})).toHaveValue('2025-12-31');
 await expect(page.getByTestId('sales-period-total')).toHaveText('27');
 await expect(overview(page)).toContainText('Бұл 84 күндік болжамға дайындық кепілдігі емес');
});

test('missing rows stay unknown, partial days break the chart, and Russian mobile overview fits',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 const rows=sales(['01','1']).filter(row=>row.date!=='2025-12-04'&&!(row.date==='2025-12-05'&&row.meal_id==='01'));
 await install(page,rows);await page.goto('/sales');
 await expect(page.getByTestId('sales-period-total')).toHaveText('—');
 await expect(page.getByTestId('sales-days-coverage')).toHaveText('26 / 28');
 await expect(overview(page)).toContainText('Бар жолдарда: 51 порция. Толық жиынтық белгісіз.');
 await expect(overview(page).locator('.sales-chart-point')).toHaveCount(26);
 await expect(overview(page).locator('.sales-chart-missing')).toHaveCount(2);
 await overview(page).getByText('Тағамдар және жоқ күндер',{exact:true}).click();
 await expect(overview(page).locator('.sales-coverage-row').filter({hasText:'Dish 01'})).toContainText('2 күн жоқ. Біріншісі: 04.12.2025');
 await overview(page).getByText('График мәндерін оқу',{exact:true}).click();
 await expect(overview(page).locator('.sales-chart-values')).toContainText('Жолдар жоқ; сатылым белгісіз');
 await expect(overview(page).locator('.sales-chart-values')).toContainText('Күн толық емес; бар жолдарда 1 порция');
 await expect.poll(()=>overview(page).locator('.sales-history-chart').evaluate(element=>Math.abs(Number(element.getAttribute('viewBox')?.split(' ')[2])-element.getBoundingClientRect().width))).toBeLessThan(1);
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
 await page.evaluate(()=>{localStorage.setItem('asboljam-language','ru')});await page.reload();
 const ru=page.getByRole('region',{name:'Обзор продаж',exact:true});
 await expect(ru).toContainText('В имеющихся строках: 51 порций. Полный итог неизвестен.');
 await expect(ru).toContainText('Блюда без единой строки в периоде не проверены');
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();
});

test('oversized periods keep the table but never present the first page as a full summary',async({page})=>{
 const reads=await install(page,sales(),async(route,url)=>{
  if(url.searchParams.get('limit')!=='200')return false;
  await route.fulfill({json:{items:sales().slice(0,200),total:10001,next_cursor:'200'}});return true;
 });
 await page.goto('/sales');
 await expect(overview(page)).toContainText('Шолу шегі');
 await expect(page.getByTestId('sales-period-total')).toHaveCount(0);
 await expect(overview(page).locator('svg.sales-history-chart')).toHaveCount(0);
 await expect(page.locator('tbody tr')).toHaveCount(50);
 expect(reads.some(url=>url.searchParams.get('limit')==='200'&&url.searchParams.get('cursor')!=='0')).toBeFalsy();
 await page.getByLabel('Бастап',{exact:true}).fill('2024-01-01');
 await expect(overview(page)).toContainText('1–366 күн');
 await expect(page.getByTestId('sales-period-total')).toHaveCount(0);
});

for(const badPage of ['changed-total','duplicate-row','request-failed'] as const)test('rejects '+badPage+' and recovers with a fresh full read',async({page})=>{
 let broken=true;
 await install(page,sales(),async(route,url)=>{
  if(!broken||url.searchParams.get('limit')!=='200'||url.searchParams.get('cursor')!=='200')return false;
  if(badPage==='request-failed'){await route.fulfill({status:503,json:{detail:'Fixture unavailable'}});return true}
  const sorted=sales().sort((a,b)=>b.date.localeCompare(a.date)||b.meal_id.localeCompare(a.meal_id));
  await route.fulfill({json:{items:badPage==='duplicate-row'?[sorted[0],...sorted.slice(201)]:sorted.slice(200),total:badPage==='changed-total'?253:252,next_cursor:null}});return true;
 });
 await page.goto('/sales');
 await expect(overview(page)).toContainText(badPage==='request-failed'?'Кезеңді толық жүктеу мүмкін болмады':'Беттердегі деректер сәйкес келмеді');
 await expect(page.getByTestId('sales-period-total')).toHaveCount(0);
 await expect(overview(page).locator('svg.sales-history-chart')).toHaveCount(0);
 broken=false;await overview(page).getByRole('button',{name:'Қайта жүктеу',exact:true}).click();
 await expect(page.getByTestId('sales-period-total')).toHaveText('243');
});

test('late pages from the previous branch cannot populate the new branch overview',async({page})=>{
 const gate=deferred(),entered=deferred();
 await install(page,[...sales(),...sales(['01'],'002')],async(route,url)=>{
  if(url.searchParams.get('limit')==='200'&&url.searchParams.get('cursor')==='200'&&url.searchParams.get('branch_id')==='001'){entered.resolve();await gate.promise}
  return false;
 });
 await page.goto('/sales');await entered.promise;
 await page.getByLabel('Бөлімше',{exact:true}).selectOption('002');
 await expect(overview(page)).toContainText('Second branch');
 await expect(page.getByTestId('sales-period-total')).toHaveText('27');
 gate.resolve();
 await expect(page.getByTestId('sales-period-total')).toHaveText('27');
 await expect(overview(page)).toContainText('28 жол, барлық бет жүктелді');
 await expect(page.locator('tbody tr')).toHaveCount(28);
});
