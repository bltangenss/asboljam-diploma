import type {Page} from '@playwright/test';

// Navigate through the header sections; the profile and its audit journal live in the account menu.
export async function navigateTo(page:Page,section:'sales'|'imports'|'audit'){
 if(section==='audit'){
  await openProfile(page);
  await page.locator('.section-navigation').getByRole('link',{name:'Әрекеттер журналы',exact:true}).click();
  return;
 }
 await page.locator('.app-header').getByRole('button',{name:'Деректер',exact:true}).click();
 await page.locator('.section-navigation').getByRole('link',{name:section==='sales'?'Сатылым':'CSV және түзетулер',exact:true}).click();
}

// The establishment profile (formerly settings) opens from the account menu.
export async function openProfile(page:Page){
 await page.locator('.user-menu-trigger').click();
 await page.locator('.user-menu-panel').getByRole('menuitem',{name:'Профиль',exact:true}).click();
}

// Sign out from the account menu in the header; on compact screens the drawer keeps the button.
export async function logout(page:Page,label='Шығу'){
 const trigger=page.locator('.user-menu-trigger');
 if(await trigger.isVisible()){
  if(await trigger.getAttribute('aria-expanded')!=='true')await trigger.click();
  await page.locator('.user-menu-panel').getByTitle(label,{exact:true}).click();
 }else await page.locator('.sidebar').getByTitle(label,{exact:true}).click();
}
