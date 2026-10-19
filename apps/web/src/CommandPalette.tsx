import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowRight,CornerDownLeft,Search} from 'lucide-react';
import type {Lang} from './shared';

type Command={id:string;group:[string,string];label:[string,string];hint?:[string,string];url?:string;run?:()=>void};

// Every page and frequent action is one search away, so the screen does not need a button for each.
export function commandList(setLang:(lang:Lang)=>void,lang:Lang):Command[]{
 const go=(id:string,label:[string,string],url:string,hint?:[string,string]):Command=>({id,group:['Бөлімдер','Разделы'],label,url,hint});
 const act=(id:string,label:[string,string],url:string,hint:[string,string]):Command=>({id,group:['Әрекеттер','Действия'],label,url,hint});
 return [
  act('forecast',['Болжам жасау','Сделать прогноз'],'/forecasts',['Келесі күнге порциялар','Порции на следующий день']),
  act('purchase',['Сатып алуды есептеу','Рассчитать закупку'],'/procurement',['Бюджет пен қаптамалар','Бюджет и упаковки']),
  act('sales-csv',['Сатылым CSV жүктеу','Загрузить CSV продаж'],'/imports?kind=daily_sales',['Күнделікті сатылым','Ежедневные продажи']),
  act('stock-csv',['Қалдық CSV жүктеу','Загрузить CSV остатков'],'/imports?kind=inventory_lots',['Саналған партиялар','Посчитанные партии']),
  go('dashboard',['Бүгін','Сегодня'],'/dashboard'),
  go('forecasts',['Болжам және дайындау','Прогноз и приготовление'],'/forecasts'),
  go('recipes',['Тағамдар мен рецепттер','Блюда и рецепты'],'/recipes'),
  go('inventory',['Қойма','Склад'],'/inventory'),
  go('procurement',['Сатып алу жоспары','План закупки'],'/procurement'),
  go('suppliers',['Жеткізушілер және бағалар','Поставщики и цены'],'/suppliers'),
  go('data',['Деректерді қосу','Добавить данные'],'/data'),
  go('sales',['Сатылым','Продажи'],'/sales'),
  go('imports',['CSV және түзетулер','CSV и исправления'],'/imports'),
  go('reports',['Болжам дәлдігі','Точность прогноза'],'/reports'),
  go('profile',['Мекеме профилі','Профиль заведения'],'/profile'),
  {id:'language',group:['Әрекеттер','Действия'],label:lang==='kk'?['Тілді орысшаға ауыстыру','Переключить на русский']:['Тілді қазақшаға ауыстыру','Переключить на казахский'],run:()=>setLang(lang==='kk'?'ru':'kk')},
 ];
}

export function CommandPalette({open,close,go,lang,setLang}:{open:boolean;close:()=>void;go:(url:string)=>void;lang:Lang;setLang:(lang:Lang)=>void}){
 const [query,setQuery]=useState(''),[active,setActive]=useState(0);
 const input=useRef<HTMLInputElement>(null),k=lang==='kk'?0:1;
 const commands=useMemo(()=>commandList(setLang,lang),[lang,setLang]);
 const found=useMemo(()=>{const q=query.trim().toLocaleLowerCase();return q?commands.filter(c=>[...c.label,...(c.hint||[])].some(text=>text.toLocaleLowerCase().includes(q))):commands},[query,commands]);
 // Focus the search on open and hand focus back to whatever opened the palette on close.
 useEffect(()=>{if(!open)return;const previous=document.activeElement as HTMLElement|null;setQuery('');setActive(0);const timer=setTimeout(()=>input.current?.focus(),0);return()=>{clearTimeout(timer);if(previous?.isConnected)previous.focus({preventScroll:true})}},[open]);
 useEffect(()=>setActive(0),[query]);
 if(!open)return null;
 const run=(command:Command|undefined)=>{if(!command)return;close();if(command.run)command.run();else if(command.url)go(command.url)};
 const key=(event:React.KeyboardEvent)=>{
  if(event.key==='Escape'){event.preventDefault();close()}
  else if(event.key==='ArrowDown'){event.preventDefault();setActive(i=>Math.max(0,Math.min(i+1,found.length-1)))}
  else if(event.key==='ArrowUp'){event.preventDefault();setActive(i=>Math.max(i-1,0))}
  else if(event.key==='Enter'){event.preventDefault();run(found[active])}
 };
 let group='';
 return <div className="command-layer" onMouseDown={event=>{if(event.target===event.currentTarget)close()}}>
  <div className="command-palette" tabIndex={-1} role="dialog" aria-modal="true" aria-label={lang==='kk'?'Іздеу және командалар':'Поиск и команды'} onKeyDown={key}>
   <label className="command-search"><Search size={18}/><input ref={input} role="combobox" aria-expanded="true" aria-controls="command-results" aria-activedescendant={found[active]?'command-'+found[active].id:undefined} placeholder={lang==='kk'?'Бөлім немесе әрекет іздеу…':'Найти раздел или действие…'} value={query} onChange={event=>setQuery(event.target.value)}/><kbd>Esc</kbd></label>
   <ul id="command-results" role="listbox" className="command-results">
    {found.length?found.map((command,index)=>{const heading=command.group[k]!==group?(group=command.group[k]):null;return <li key={command.id} role="presentation">
     {heading&&<span className="command-group">{heading}</span>}
     <button type="button" role="option" id={'command-'+command.id} aria-selected={index===active} className={index===active?'command-item active':'command-item'} onMouseEnter={()=>setActive(index)} onFocus={()=>setActive(index)} onClick={()=>run(command)}>
      <span><strong>{command.label[k]}</strong>{command.hint&&<small>{command.hint[k]}</small>}</span>{index===active?<CornerDownLeft size={15}/>:<ArrowRight size={15}/>}
     </button></li>}):<li className="command-empty">{lang==='kk'?'Ештеңе табылмады':'Ничего не найдено'}</li>}
   </ul>
  </div>
 </div>;
}
