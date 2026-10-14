import {test,expect,type Page} from '@playwright/test';

// Artificial fixtures prove navigation/permissions, not data quality or forecast accuracy.
async function install(page:Page,role='manager',lang='ru'){
 await page.addInitScript(value=>localStorage.setItem('asboljam-language',value),lang);
 await page.route('**/api/v1/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname.replace('/api/v1','');
  const branch=url.searchParams.get('branch_id');
  let json:any={items:[],total:0,next_cursor:null};
  if(path==='/session/me')json={user:{id:'ux-user',organization_id:'ux',email:'ux@example.invalid',role,branch_ids:['one','two']},csrf_token:'artificial-ux-fixture'};
  if(path==='/settings')json={organization:{id:'ux',name:'SYNTHETIC UX fixture',timezone:'Asia/Qyzylorda',currency:'KZT',status:'active',data_policy:'synthetic_only'},onboarding:{branch_count:2,data_policy:'synthetic_only',can_import_branches:role==='admin'},data_context:{version:1,mode:'synthetic_fixed',data_origin:'SYNTHETIC',usage_mode:'DEMO',timezone:'Asia/Qyzylorda',currency:'KZT',branch_id:branch,history_start:'2025-09-01',history_end:'2025-12-31',forecast_origin:'2025-12-31',target_date:'2026-01-01',inventory_date:'2026-01-01',inventory_dates:['2026-01-01'],dates_editable:false,operations_enabled:true}};
  if(path==='/branches')json={items:[{branch_id:'one',branch_name:'Первый филиал'},{branch_id:'two',branch_name:'Второй филиал'}],total:2};
  if(path==='/dashboard')json={as_of:null,history:[],top_meals:[],warnings:[],latest_forecast:null,latest_plans:[],inventory_known:false};
  await route.fulfill({json});
 });
}

test('five daily sections group existing routes and preserve branch',async({page})=>{
 await install(page);await page.goto('/data');
 const nav=page.getByRole('navigation',{name:'Рабочий день',exact:true});
 await expect(nav.getByRole('button')).toHaveText(['Сегодня','План дня','Остатки','Закупки','Данные и анализ']);
 await page.getByLabel('Филиал',{exact:true}).selectOption('two');
 await expect(page.locator('.data-workspace-context')).toContainText('Второй филиал');
 await nav.getByRole('button',{name:'План дня',exact:true}).click();
 await page.getByRole('navigation',{name:'Навигация раздела'}).getByRole('link',{name:'Блюда и рецепты'}).click();
 await expect(page).toHaveURL(/\/recipes$/);await expect(nav.getByRole('button',{name:'План дня',exact:true})).toHaveAttribute('aria-current','page');
 await expect(page.getByLabel('Филиал',{exact:true})).toHaveValue('two');
 await nav.getByRole('button',{name:'Закупки',exact:true}).click();
 await page.getByRole('link',{name:'Поставщики и цены'}).click();
 await expect(page).toHaveURL(/\/suppliers$/);await expect(nav.getByRole('button',{name:'Закупки',exact:true})).toHaveAttribute('aria-current','page');
 await page.getByRole('button',{name:'Настройки и управление',exact:true}).click();
 await page.getByRole('link',{name:'Журнал действий',exact:true}).click();await expect(page).toHaveURL(/\/audit$/);
});

test('data tasks open specific schemas and explicit correction mode',async({page})=>{
 await install(page);await page.goto('/data');
 await page.getByRole('link',{name:/Добавить продажи/}).click();
 await expect(page.getByLabel('Данные',{exact:true})).toHaveValue('daily_sales');
 await page.goto('/data');await page.getByRole('link',{name:/Добавить посчитанные остатки/}).click();
 await expect(page.getByLabel('Данные',{exact:true})).toHaveValue('inventory_lots');
 await page.goto('/data');await page.getByRole('link',{name:/Исправить данные/}).click();
 await expect(page.getByLabel('Режим импорта',{exact:true})).toHaveValue('correction');
});

test('reference detours preserve the chosen calculation only within the same branch',async({page})=>{
 await install(page);await page.goto('/procurement?forecast=older-forecast');
 await page.getByRole('link',{name:'Поставщики и цены'}).click();
 await page.getByRole('link',{name:'План закупки',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement\?forecast=older-forecast$/);
 await page.getByRole('link',{name:'Поставщики и цены'}).click();
 await page.getByLabel('Филиал',{exact:true}).selectOption('two');
 await page.getByRole('link',{name:'План закупки',exact:true}).click();
 await expect(page).toHaveURL(/\/procurement$/);
 await page.goto('/forecasts/saved-day');
 await page.getByRole('link',{name:'Блюда и рецепты'}).click();
 await page.getByRole('link',{name:'Прогноз и приготовление',exact:true}).click();
 await expect(page).toHaveURL(/\/forecasts\/saved-day$/);
});

test('warehouse gets stock tasks while analyst gets reading routes',async({page})=>{
 await install(page,'warehouse');await page.goto('/data');
 await expect(page.getByRole('link',{name:/Добавить продажи/})).toHaveCount(0);
 await expect(page.getByRole('link',{name:/Добавить посчитанные остатки/})).toBeVisible();
 await page.getByRole('link',{name:/Исправить данные/}).click();
 await expect(page.getByLabel('Данные',{exact:true})).toHaveValue('inventory_lots');
 await page.unrouteAll({behavior:'wait'});await install(page,'analyst');await page.goto('/data');
 await expect(page.locator('.data-task')).toHaveCount(0);
 await expect(page.getByRole('link',{name:/Проверить продажи/})).toBeVisible();
 await expect(page.getByText('Вам доступен просмотр данных.',{exact:false})).toBeVisible();
});

test('nested deep links keep correct group after browser back and narrow screens',async({page})=>{
 await install(page,'admin');await page.goto('/reports');
 await expect(page.getByRole('navigation',{name:'Рабочий день',exact:true}).getByRole('button',{name:'Данные и анализ'})).toHaveAttribute('aria-current','page');
 await page.getByRole('link',{name:'Подготовка данных'}).click();
 await page.getByRole('link',{name:/Добавить продажи/}).click();await page.goBack();await expect(page.locator('main h1')).toHaveText('Данные и анализ');
 for(const width of [1440,768,390,360]){
  await page.setViewportSize({width,height:900});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await expect(page.getByRole('link',{name:/Добавить продажи/})).toBeVisible();
 }
 await page.getByRole('button',{name:'Открыть меню',exact:true}).click();
 await page.getByRole('dialog').getByRole('button',{name:'Остатки',exact:true}).click();
 await expect(page).toHaveURL(/\/inventory$/);await expect(page.getByRole('dialog')).toHaveCount(0);
});
