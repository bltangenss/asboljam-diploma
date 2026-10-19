import {test,expect,type Page} from '@playwright/test';

// Synthetic browser contract for closing a day: unknowns stay empty, the review lists what is
// missing, a retry after a lost answer reuses its Idempotency-Key, and a conflict needs a reason.
// Backend rules (atomic write, no double counting, roles) are covered by tests/test_day_close.py.
const meals=[{meal_id:'1',meal_name:'Бешбармақ',base_price_kzt:'2600'},{meal_id:'2',meal_name:'Лағман',base_price_kzt:'1900'}];

async function install(page:Page,{role='manager',conflict=false,loseFirstClose=false}:{role?:string;conflict?:boolean;loseFirstClose?:boolean}={}){
 const state={version:0,status:'none',is_open:null as number|null,lines:[] as any[],requests:[] as {method:string;path:string;key:string|null;body:any}[],closeCalls:0};
 const context={version:1,mode:'synthetic_fixed',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Almaty',currency:'KZT',branch_id:'1',history_start:'2024-01-01',history_end:'2025-12-31',
  forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true,business_date:null,source:null};
 const view=()=>({branch_id:'1',business_date:'2026-01-01',default_date:'2026-01-01',data_origin:'SYNTHETIC',closable:true,status:state.status,version:state.version,is_open:state.is_open,
  meals:meals.map(meal=>({...meal,entry:state.lines.find(line=>line.meal_id===meal.meal_id)||null,recorded:null,reference:{previous_day_units_sold:meal.meal_id==='1'?40:null,planned_portions:null}})),
  completeness:{complete:false,missing:[],unmarked:[],invalid:[],counts:{meals:2}},closed_by:state.status==='closed'?'owner@example.invalid':null,closed_at:state.status==='closed'?'2026-01-01T18:00:00Z':null,reason:null,batch_ids:[]});
 await page.route('**/api/v1/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace('/api/v1','');
  if(request.method()!=='GET'){
   const body=request.postDataJSON();state.requests.push({method:request.method(),path,key:request.headers()['idempotency-key']||null,body});
   if(path==='/day-close'){state.version+=1;state.status='draft';state.is_open=body.is_open;state.lines=body.lines;return route.fulfill({json:view()})}
   if(path==='/day-close/close'){
    state.closeCalls+=1;
    if(loseFirstClose&&state.closeCalls===1)return route.abort('failed');
    if(conflict&&!body.correction_reason)return route.fulfill({status:409,json:{detail:{code:'DAY_CONFLICT',message:'conflict',details:[{meal_id:'1',recorded:{units_sold:30},entered:{units_sold:31}}]}}});
    state.version+=1;state.status='closed';return route.fulfill({json:{...view(),recorded_counts:{inserted:2,updated:0,unchanged:0}}});
   }
   return route.fulfill({status:400,json:{detail:{code:'FIXTURE_UNEXPECTED_MUTATION'}}});
  }
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'owner',organization_id:'cafe',email:'owner@example.invalid',role,branch_ids:['1']},csrf_token:'synthetic-csrf'};
  if(path==='/settings')json={organization:{id:'cafe',name:'Алматы кофе',timezone:'Asia/Almaty',currency:'KZT',status:'active',data_policy:'synthetic_only',provenance:'self_registration'},onboarding:{branch_count:1,data_policy:'synthetic_only'},data_context:url.searchParams.has('branch_id')?context:{...context,branch_id:null}};
  if(path==='/branches')json={items:[{branch_id:'1',branch_name:'Алматы кофе'}],total:1};
  if(path==='/day-close')json=view();
  await route.fulfill({json});
 });
 await page.addInitScript(()=>localStorage.setItem('asboljam-language','ru'));
 return state;
}
const card=(page:Page,meal:string)=>page.locator('.day-close-meal').filter({hasText:meal});

test('unknown facts stay empty, the review lists them and closing sends exactly the entered day',async({page})=>{
 const state=await install(page);
 await page.goto('/day-close');
 await expect(page.getByRole('heading',{name:'Закрыть день'})).toBeVisible();
 await expect(page.getByText('Учебный сценарий: дата остаётся 01.01.2026',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Да, работало'}).click();
 await card(page,'Бешбармақ').getByRole('button',{name:'Продавалось'}).click();
 await expect(card(page,'Бешбармақ')).toContainText('Вчера: 40');
 await card(page,'Бешбармақ').getByLabel('Продано, порций').fill('0');
 await page.getByRole('button',{name:'Проверить'}).click();
 const review=page.locator('.day-close-review');
 await expect(review).toContainText('Лағман: не отмечено, продавалось ли');
 await expect(review).toContainText('Бешбармақ: готово, закончилось ли, акция, цена');
 await expect(review.getByRole('button',{name:'Закрыть день'})).toBeDisabled();
 await review.getByRole('button',{name:'Назад'}).click();
 await card(page,'Лағман').getByRole('button',{name:'Не предлагалось'}).click();
 await card(page,'Бешбармақ').getByLabel('Было готово, порций').fill('4');
 await page.getByRole('button',{name:'Ничего не закончилось'}).click();
 await page.getByRole('button',{name:'Акций не было'}).click();
 await page.getByRole('button',{name:'Цены по меню'}).click();
 await page.getByRole('button',{name:'Проверить'}).click();
 await review.getByRole('button',{name:'Закрыть день'}).click();
 await expect(page.locator('.day-close-card.is-closed')).toContainText('День закрыт');
 const [saved,closed]=state.requests;
 expect(saved.body.lines).toEqual([
  {meal_id:'1',state:'sold',units_sold:0,available_portions:4,stockout_flag:0,stockout_time:null,replenished_time:null,promo:0,price_kzt:'2600'},
  {meal_id:'2',state:'not_offered',units_sold:null,available_portions:null,stockout_flag:null,stockout_time:null,replenished_time:null,promo:null,price_kzt:null}]);
 expect(closed.body).toEqual({branch_id:'1',business_date:'2026-01-01',expected_version:1});
 expect(saved.key).toBeTruthy();expect(closed.key).toBeTruthy();expect(closed.key).not.toBe(saved.key);
});

test('a retry after a lost answer reuses the key and a conflict asks for a reason',async({page})=>{
 const state=await install(page,{conflict:true,loseFirstClose:true});
 await page.goto('/day-close');
 await page.getByRole('button',{name:'Нет, было закрыто'}).click();
 await expect(page.getByText('это не «нет данных», а подтверждённый закрытый день',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Проверить'}).click();
 const review=page.locator('.day-close-review');
 await review.getByRole('button',{name:'Закрыть день'}).click();
 await expect(review.getByRole('alert')).toBeVisible();
 await review.getByRole('button',{name:'Закрыть день'}).click();
 await expect(review).toContainText('сохранено 30 → введено 31');
 const fix=review.getByRole('button',{name:'Исправить и закрыть'});
 await expect(fix).toBeDisabled();
 await review.getByLabel('Причина исправления').fill('Пересчитали по кассе');
 await fix.click();
 await expect(page.locator('.day-close-card.is-closed')).toBeVisible();
 const closes=state.requests.filter(item=>item.path==='/day-close/close');
 expect(closes).toHaveLength(3);
 expect(closes[1].key).toBe(closes[0].key);  // same request after a lost answer
 expect(closes[2].key).not.toBe(closes[1].key);
 expect(closes[2].body.correction_reason).toBe('Пересчитали по кассе');
});

test('an analyst reads the day without editing and Today offers the action to managers',async({page})=>{
 await install(page,{role:'analyst'});
 await page.goto('/day-close');
 await expect(page.getByRole('button',{name:'Да, работало'})).toBeDisabled();
 await expect(page.locator('.day-close-bar')).toHaveCount(0);
 await page.unrouteAll({behavior:'wait'});
 await install(page);
 await page.goto('/dashboard');
 await page.getByRole('button',{name:'Закрыть день'}).click();
 await expect(page).toHaveURL(/\/day-close$/);
 await expect(page.getByRole('navigation',{name:'Рабочий день',exact:true}).getByRole('button',{name:'Сегодня'})).toHaveAttribute('aria-current','page');
});
