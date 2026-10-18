import type {Page} from '@playwright/test';

// Navigate through the task groups instead of depending on the former entity sidebar.
export async function navigateTo(page:Page,section:'sales'|'imports'|'audit'){
 const group=section==='audit'?'Баптаулар және басқару':'Деректер және талдау';
 await page.locator('.app-header').getByRole('button',{name:group,exact:true}).click();
 await page.locator('.section-navigation').getByRole('link',{name:section==='sales'?'Сатылым':section==='imports'?'CSV және түзетулер':'Әрекеттер журналы',exact:true}).click();
}

// Sign out from the account menu in the header; on compact screens the drawer keeps the button.
export async function logout(page:Page,label='Шығу'){
 const trigger=page.locator('.user-menu-trigger');
 if(await trigger.isVisible()){
  if(await trigger.getAttribute('aria-expanded')!=='true')await trigger.click();
  await page.locator('.user-menu-panel').getByTitle(label,{exact:true}).click();
 }else await page.locator('.sidebar').getByTitle(label,{exact:true}).click();
}
