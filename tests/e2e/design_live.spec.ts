import {test,expect} from '@playwright/test';
import fs from 'node:fs';
const login=JSON.parse(fs.readFileSync('.cache/e2e-login.json','utf8'));
const directory='.cache/design-visual';fs.mkdirSync(directory,{recursive:true});

test('operational pages retain readable layout in KK and RU with live local data',async({page})=>{
 test.setTimeout(180000);
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('/');await page.getByLabel('Электрондық пошта',{exact:true}).fill(login.email);await page.getByLabel('Құпиясөз',{exact:true}).fill(login.password);await page.getByRole('button',{name:'Жүйеге кіру',exact:true}).click();
 await expect(page.locator('.next-action')).toBeVisible();
 for(const lang of ['kk','ru']){
  if(lang==='ru')await page.getByRole('button',{name:'ҚАЗ',exact:true}).click();
  for(const section of ['imports','forecasts','procurement','inventory','recipes','suppliers','reports','settings','audit','sales']){
   await page.goto('/'+section);await expect(page.locator('main h1')).toBeVisible();
   await expect(page.locator('main .skeleton-grid')).toHaveCount(0);
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:1000});
    await expect(page.locator('main h1')).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),`${section} ${lang} ${width}: no page-level horizontal overflow`).toBeTruthy();
    await page.screenshot({path:`${directory}/${section}-${lang}-${width}.png`,animations:'disabled'});
   }
  }
 }
 expect(errors).toEqual([]);
});
