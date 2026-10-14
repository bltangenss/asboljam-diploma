import {CalendarDays,ChartNoAxesCombined,ClipboardList,Package,Settings,ShoppingBasket} from 'lucide-react';
import {useRef} from 'react';
import type {Context,Lang} from './shared';
import './workday-ui.css';

// Routes remain stable; the navigation groups them by a manager's daily tasks.
export const workdaySections=[
 {key:'dashboard',label:['Бүгін','Сегодня'],icon:CalendarDays,routes:['dashboard']},
 {key:'forecasts',label:['Күн жоспары','План дня'],icon:ClipboardList,routes:['forecasts','recipes']},
 {key:'inventory',label:['Қалдықтар','Остатки'],icon:Package,routes:['inventory']},
 {key:'procurement',label:['Сатып алу','Закупки'],icon:ShoppingBasket,routes:['procurement','suppliers']},
 {key:'data',label:['Деректер және талдау','Данные и анализ'],icon:ChartNoAxesCombined,routes:['data','sales','imports','reports']},
];
export const managementSection={key:'settings',label:['Баптаулар және басқару','Настройки и управление'],icon:Settings,routes:['settings','audit']};
export function sectionGroup(section:string){return [...workdaySections,managementSection].find(group=>group.routes.includes(section));}
export function sectionLabel(section:string,lang:Lang){const group=sectionGroup(section);return group?.label[lang==='kk'?0:1];}

export function SectionNavigation({context:c,section}:{context:Context;section:string}){
 const kk=c.lang==='kk',group=sectionGroup(section);
 const scope=JSON.stringify([c.user.organization_id,c.user.id,c.user.role,c.branch]);
 const saved=useRef<{scope:string;routes:Record<string,string>}>({scope,routes:{}});
 if(saved.current.scope!==scope)saved.current={scope,routes:{}};
 if(['forecasts','procurement'].includes(section))saved.current.routes[section]=location.pathname+location.search;
 const links:Record<string,[string,string,string][]>= {
  forecasts:[['forecasts','Болжам және дайындау','Прогноз и приготовление'],['recipes','Тағамдар мен рецепттер','Блюда и рецепты']],
  procurement:[['procurement','Сатып алу жоспары','План закупки'],['suppliers','Жеткізушілер және бағалар','Поставщики и цены']],
  data:[['data','Деректерді дайындау','Подготовка данных'],['sales','Сатылым','Продажи'],['imports','CSV және түзетулер','CSV и исправления'],['reports','Нәтижелерді талдау','Анализ результатов']],
  settings:[['settings','Ұйым және рұқсаттар','Организация и доступ'],['audit','Әрекеттер журналы','Журнал действий']],
 };
 const children=group&&links[group.key];
 if(!children)return null;
 return <nav className="section-navigation" aria-label={kk?'Бөлім ішіндегі навигация':'Навигация раздела'}>{children.map(([route,kz,ru])=>{const destination=saved.current.routes[route]||'/'+route;return <a key={route} href={destination} aria-current={section===route?'page':undefined} onClick={event=>{if(!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey){event.preventDefault();c.go(destination)}}}>{kk?kz:ru}</a>})}</nav>;
}
