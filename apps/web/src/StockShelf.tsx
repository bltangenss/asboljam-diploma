import {useState} from 'react';
import {LayoutGrid,Table2} from 'lucide-react';
import {type Lang,type Row,Badge,Empty,date,name,shiftDate,Table} from './shared';

type Status='expired'|'soon'|'unknown'|'valid';
const order:Record<Status,number>={expired:0,soon:1,unknown:2,valid:3};
const tones:Record<Status,string>={expired:'red',soon:'amber',unknown:'neutral',valid:'green'};
const filters:Record<Status|'all',[string,string]>={all:['Барлығы','Все'],expired:['Өткен','Истёк срок'],soon:['Жақын','Скоро истекает'],unknown:['Мерзімсіз','Без срока'],valid:['Қалыпты','В норме']};
const viewKey='asboljam-stock-view';

// Same rule as the table: a lot expiring on the snapshot day is still usable (demo contract).
export function lotStatus(expiry:unknown,day:string):Status{
 if(!expiry||!/^\d{4}-\d{2}-\d{2}$/.test(day))return 'unknown';const value=String(expiry);
 return value<day?'expired':value<=shiftDate(day,2)?'soon':'valid';
}

// Quantities are decimal strings; add them exactly instead of through binary floats.
export function decimalSum(values:unknown[]):string|null{
 let total=0n,scale=0;
 for(const value of values){
  const match=/^\+?(\d+)(?:\.(\d+))?$/.exec(String(value??''));if(!match)return null;
  const fraction=match[2]||'';
  if(fraction.length>scale){total*=10n**BigInt(fraction.length-scale);scale=fraction.length}
  total+=BigInt(match[1]+fraction)*10n**BigInt(scale-fraction.length);
 }
 const digits=total.toString().padStart(scale+1,'0');
 return (scale?digits.slice(0,-scale)+'.'+digits.slice(-scale):digits).replace(/(\.\d*?[1-9])0+$|\.0+$/,'$1');
}

function readView(){try{return localStorage.getItem(viewKey)==='table'?'table':'shelf'}catch{return 'shelf'}}

// Counted stock as a shelf: one card per ingredient and unit (kg and L never merge), lots as
// chips ordered by expiry. The raw lot table stays one click away.
export default function StockShelf({rows,columns,day,t,lang}:{rows:Row[];columns:any[];day:string;t:(key:string)=>string;lang:Lang}){
 const kk=lang==='kk';
 const[view,setView]=useState<'shelf'|'table'>(readView);
 const[filter,setFilter]=useState<Status|'all'>('all');
 const choose=(next:'shelf'|'table')=>{setView(next);try{localStorage.setItem(viewKey,next)}catch{}};
 const groups=new Map<string,Row[]>();
 rows.forEach(row=>{const key=String(row.ingredient_id)+'\0'+String(row.unit??'');groups.set(key,[...(groups.get(key)||[]),row])});
 const cards=[...groups.entries()].map(([key,lots])=>{
  const sorted=[...lots].sort((a,b)=>String(a.expiry_date||'9999').localeCompare(String(b.expiry_date||'9999')));
  const status=sorted.map(lot=>lotStatus(lot.expiry_date,day)).sort((a,b)=>order[a]-order[b])[0]||'unknown';
  // Expired lots are not usable stock for planning, so they are shown but not counted.
  const usable=lots.filter(lot=>lotStatus(lot.expiry_date,day)!=='expired'),expired=lots.filter(lot=>lotStatus(lot.expiry_date,day)==='expired');
  const sum=(part:Row[])=>!part.length?null:part.length===1?(part[0].on_hand_qty??null):decimalSum(part.map(lot=>lot.on_hand_qty));
  return {key,lots:sorted,status,total:sum(usable),expired:sum(expired),unit:lots[0].unit,label:name(lots[0].ingredient_name||lots[0].ingredient_id)};
 }).sort((a,b)=>order[a.status]-order[b.status]||a.label.localeCompare(b.label));
 const counts=cards.reduce((all,card)=>({...all,[card.status]:(all[card.status]||0)+1}),{} as Record<string,number>);
 // A filter whose status disappeared (another day or branch) falls back to all cards.
 const effective=filter==='all'||counts[filter]?filter:'all';
 const visible=effective==='all'?cards:cards.filter(card=>card.status===effective);
 return <div className="stock-shelf">
  <div className="stock-shelf-bar">
   {view==='shelf'&&<div className="stock-shelf-filters" role="group" aria-label={kk?'Жарамдылық мерзімі бойынша сүзу':'Фильтр по сроку годности'}>
    {(['all','expired','soon','unknown','valid'] as const).filter(key=>key==='all'||counts[key]).map(key=><button type="button" key={key} className={'stock-shelf-filter is-'+key+(effective===key?' active':'')} aria-pressed={effective===key} onClick={()=>setFilter(key)}>{filters[key][kk?0:1]}<span>{key==='all'?cards.length:counts[key]}</span></button>)}
   </div>}
   <span className="stock-shelf-meta">{date(day)} · {rows.length} {kk?'партия':'партий'}</span>
   <div className="stock-shelf-views" role="group" aria-label={kk?'Көрініс':'Вид'}>
    <button type="button" aria-pressed={view==='shelf'} className={view==='shelf'?'active':''} onClick={()=>choose('shelf')}><LayoutGrid size={15}/>{kk?'Карточкалар':'Карточки'}</button>
    <button type="button" aria-pressed={view==='table'} className={view==='table'?'active':''} onClick={()=>choose('table')}><Table2 size={15}/>{kk?'Кесте':'Таблица'}</button>
   </div>
  </div>
  {view==='table'?<Table t={t} rows={rows} columns={columns}/>:!rows.length?<Empty t={t}/>:<ul className="stock-shelf-grid">
   {visible.map(card=><li key={card.key} className={'stock-shelf-item is-'+card.status}>
    <div className="stock-shelf-head"><strong>{card.label}</strong>{card.status!=='valid'&&<Badge tone={tones[card.status]}>{card.status==='unknown'?(kk?'Мерзімі белгісіз':'Срок неизвестен'):t(card.status)}</Badge>}</div>
    <p className="stock-shelf-qty"><span>{card.total??'—'}</span> {card.unit||''} <em>{kk?'жарамды':'годный остаток'}</em></p>
    {card.expired&&<p className="stock-shelf-expired">{card.expired} {card.unit||''} · {kk?'мерзімі өтіп кеткен, есепке алынбайды':'просрочено, не учитывается'}</p>}
    <ul className="stock-shelf-lots" aria-label={kk?'Партиялар':'Партии'}>{card.lots.map(lot=>{const status=lotStatus(lot.expiry_date,day);return <li key={String(lot.lot_id)} className={'is-'+status}>
     <span className="stock-shelf-lot-qty">{lot.on_hand_qty??'—'} {lot.unit||''}</span>
     <span className="stock-shelf-lot-date">{lot.expiry_date?(kk?date(lot.expiry_date)+' дейін':'до '+date(lot.expiry_date)):(kk?'мерзімсіз':'без срока')}</span>
     <small>{lot.lot_id}</small>
    </li>})}</ul>
   </li>)}
  </ul>}
 </div>;
}
