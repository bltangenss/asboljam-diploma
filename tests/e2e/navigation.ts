import type {Page} from '@playwright/test';

// Navigate through the task groups instead of depending on the former entity sidebar.
export async function navigateTo(page:Page,section:'sales'|'imports'|'audit'){
 const group=section==='audit'?'Баптаулар және басқару':'Деректер және талдау';
 await page.locator('.sidebar').getByRole('button',{name:group,exact:true}).click();
 await page.locator('.section-navigation').getByRole('link',{name:section==='sales'?'Сатылым':section==='imports'?'CSV және түзетулер':'Әрекеттер журналы',exact:true}).click();
}
