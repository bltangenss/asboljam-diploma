import {AlertTriangle,ArrowRight,ArrowUpRight,Package,ShoppingBasket,TrendingUp} from 'lucide-react';
import {type Context,type Row,useData,fmt,money,date,name,shiftDate,Badge} from './shared';
import './overview.css';

// Today's numbers at a glance. Unknown stays "—": a missing day, value or snapshot is never shown as zero.
type Kpis={c:Context;d:Row;target:string;forecastCurrent:boolean;portionTotal:number|null;plan:Row|null|undefined;planCurrent:boolean;
 urls:{forecast:string;stock:string;purchase:string}};

const units=(r:Row)=>{const v=r.units_sold;return v===null||v===undefined||!Number.isFinite(Number(v))?null:Number(v)};

// Sum of a calendar window; null when any day of the window is absent from the history.
function windowSum(history:Row[],last:string,days:number){
 const byDate=new Map(history.map(r=>[String(r.date).slice(0,10),units(r)]));let sum=0;
 for(let i=0;i<days;i++){const v=byDate.get(shiftDate(last,-i));if(v===null||v===undefined)return null;sum+=v}
 return sum;
}

export function useStockSummary(c:Context,inventoryDate:string|null,known:boolean){
 const state=useData(known&&inventoryDate?`/inventory?branch_id=${encodeURIComponent(c.branch)}&date_from=${inventoryDate}&date_to=${inventoryDate}&limit=200`:null,c.revision);
 const rows:Row[]=(state.data?.items||[]).filter((r:Row)=>r.snapshot_date===inventoryDate);
 const limit=inventoryDate?shiftDate(inventoryDate,2):'';
 const items=new Map<string,{id:string;name:string;unit:string;qty:number;expired:number;soonest:string|null}>();
 for(const r of rows){
  const id=String(r.ingredient_id),qty=Number(r.on_hand_qty),item=items.get(id)||{id,name:String(r.ingredient_name||id),unit:String(r.unit||''),qty:0,expired:0,soonest:null};
  if(r.expiry_date<r.snapshot_date)item.expired+=1;
  else if(Number.isFinite(qty)){item.qty+=qty;if(!item.soonest||r.expiry_date<item.soonest)item.soonest=r.expiry_date}
  items.set(id,item);
 }
 const list=[...items.values()].map(item=>({...item,soon:Boolean(item.soonest&&item.soonest<=limit)}));
 const total=Number(state.data?.total),truncated=Number.isFinite(total)&&total>rows.length;
 return {loading:state.loading,error:state.error,complete:Boolean(state.data)&&!truncated,truncated,list,count:list.length,soon:list.filter(i=>i.soon).length,expired:list.filter(i=>i.expired>0).length};
}

export function DayKpis({c,d,target,forecastCurrent,portionTotal,plan,planCurrent,urls,stock}:Kpis&{stock:ReturnType<typeof useStockSummary>}){
 const {go,lang,t}=c,copy=(kk:string,ru:string)=>lang==='kk'?kk:ru,history:Row[]=d.history||[],asOf=d.as_of;
 const week=asOf?windowSum(history,asOf,7):null,previous=asOf?windowSum(history,shiftDate(asOf,-7),7):null;
 const change=week!==null&&previous?Math.round((week-previous)/previous*100):null;
 const lastWeek=asOf?history.find(r=>String(r.date).slice(0,10)===shiftDate(asOf,-7)):null,lastWeekUnits=lastWeek?units(lastWeek):null;
 const dayChange=asOf&&lastWeekUnits&&d.sold_portions!==null&&d.sold_portions!==undefined?Math.round((Number(d.sold_portions)-lastWeekUnits)/lastWeekUnits*100):null;
 const trend=(value:number|null,label:string)=>value===null?null:<span className={'kpi-trend '+(value>0?'is-up':value<0?'is-down':'')}>{value>0?'+':''}{value}% {label}</span>;
 const stockValue=d.inventory_known&&!stock.loading&&stock.complete&&stock.count>0?fmt(stock.count):'—';
 return <section className="day-kpis" aria-label={copy('Негізгі көрсеткіштер','Главные цифры')}>
  <article className="kpi"><span className="kpi-label">{t('portions')} · {date(asOf)}</span><strong className="metric-value">{fmt(asOf?d.sold_portions:null)}</strong>{trend(dayChange,copy('апта бұрынғыдан','к прошлой неделе'))}</article>
  <article className="kpi"><span className="kpi-label">{t('revenue')} · {date(asOf)}</span><strong className="metric-value">{money(asOf?d.revenue:null)}</strong></article>
  <article className="kpi"><span className="kpi-label">{copy('7 күнде сатылды, порция','Продано за 7 дней, порций')}</span><strong className="metric-value">{fmt(week)}</strong>{trend(change,copy('алдыңғы 7 күнге','к прошлым 7 дням'))}</article>
  <button className="kpi kpi-link" onClick={()=>go(urls.forecast)}><span className="kpi-label"><TrendingUp size={14}/>{copy('Болжам','Прогноз')} · {date(target)}</span>
   <strong className="metric-value">{forecastCurrent&&portionTotal!==null?fmt(portionTotal,0):'—'}</strong><span className="kpi-note">{forecastCurrent?copy('порция күтіледі','порций ожидается'):copy('Болжам әлі жоқ','Прогноза пока нет')}<ArrowRight size={13}/></span></button>
  <button className="kpi kpi-link" onClick={()=>go(urls.stock)}><span className="kpi-label"><Package size={14}/>{copy('Қойма','Склад')} · {date(d.inventory_date)}</span>
   <strong className="metric-value">{stockValue}</strong>
   <span className="kpi-note">{!d.inventory_known?copy('Қалдық белгісіз','Остатки неизвестны'):stock.soon||stock.expired?<>{stock.soon>0&&<span className="kpi-chip is-warn">{copy('мерзімі жақын','скоро истекает')}: {stock.soon}</span>}{stock.expired>0&&<span className="kpi-chip is-bad">{t('expired')}: {stock.expired}</span>}</>:copy('өнім қоймада','продуктов на складе')}</span></button>
  <button className="kpi kpi-link" onClick={()=>go(urls.purchase)}><span className="kpi-label"><ShoppingBasket size={14}/>{copy('Сатып алу','Закупка')} · {date(target)}</span>
   <strong className="metric-value">{planCurrent?money(plan!.total_cost):'—'}</strong>
   <span className="kpi-note">{planCurrent?<>{Number(plan!.shortage_count)>0?<span className="kpi-chip is-bad">{copy('тапшылық','дефицит')}: {fmt(plan!.shortage_count)}</span>:null}<Badge tone={plan!.status==='approved'?'green':plan!.status==='rejected'?'red':'amber'}>{t(plan!.status)}</Badge></>:copy('Әлі есептелмеген','Ещё не рассчитана')}</span></button>
 </section>;
}

function DailyBars({history,lang}:{history:Row[];lang:string}){
 if(!history.length)return <p className="chart-empty">—</p>;
 const first=String(history[0].date).slice(0,10),last=String(history[history.length-1].date).slice(0,10),days:string[]=[];
 for(let day=first;day<=last&&days.length<60;day=shiftDate(day,1))days.push(day);
 const byDate=new Map(history.map(r=>[String(r.date).slice(0,10),units(r)])),max=Math.max(1,...days.map(day=>byDate.get(day)??0));
 const width=Math.max(days.length*14,140),height=120,bar=width/days.length;
 const weekday=(day:string)=>new Date(day+'T00:00:00Z').getUTCDay();
 return <div className="sales-bars"><svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={lang==='kk'?'Күн сайынғы сатылым':'Продажи по дням'}>
  {days.map((day,i)=>{const v=byDate.get(day);if(v===null||v===undefined)return <rect key={day} className="bar-missing" x={i*bar+bar*.2} y={height-3} width={bar*.6} height={3}><title>{date(day)}: —</title></rect>;
   const h=Math.max(2,v/max*(height-8));return <rect key={day} className={day===last?'bar is-last':weekday(day)===0||weekday(day)===6?'bar is-weekend':'bar'} x={i*bar+bar*.15} y={height-h} width={bar*.7} height={h} rx={2}><title>{date(day)}: {fmt(v)}</title></rect>})}
 </svg><small>{date(first)} — {date(last)}</small></div>;
}

function Bars({items,unit,empty}:{items:{key:string;label:string;value:number;note?:any;tone?:string}[];unit?:string;empty:string}){
 if(!items.length)return <p className="chart-empty">{empty}</p>;
 const max=Math.max(1,...items.map(i=>i.value));
 return <ol className="hbars">{items.map(i=><li key={i.key} className={i.tone?'is-'+i.tone:undefined}><span className="hbar-label">{i.label}</span>
  <span className="hbar-track"><span style={{width:Math.max(2,i.value/max*100)+'%'}}/></span><strong>{fmt(i.value,1)}{unit?' '+unit:''}</strong>{i.note&&<small>{i.note}</small>}</li>)}</ol>;
}

export function DayCharts({c,d,forecastCurrent,predictions,stock,urls}:{c:Context;d:Row;forecastCurrent:boolean;predictions:Row[];stock:ReturnType<typeof useStockSummary>;urls:{forecast:string;stock:string}}){
 const {go,lang}=c,copy=(kk:string,ru:string)=>lang==='kk'?kk:ru,history:Row[]=d.history||[];
 const names=new Map<string,string>((d.top_meals||[]).map((r:Row)=>[String(r.meal_id),String(r.meal_name||r.meal_id)]));
 const top=(d.top_meals||[]).slice(0,6).map((r:Row)=>({key:String(r.meal_id),label:name(r.meal_name||r.meal_id),value:Number(r.units_sold)})).filter((i:any)=>Number.isFinite(i.value));
 const planned=forecastCurrent?predictions.filter(r=>r.point_forecast!==null&&r.point_forecast!==undefined&&Number.isFinite(Number(r.point_forecast)))
  .map(r=>({key:String(r.meal_id),label:name(r.meal_name||names.get(String(r.meal_id))||r.meal_id),value:Number(r.point_forecast),note:r.p10!==null&&r.p10!==undefined&&r.p90!==null&&r.p90!==undefined?`${fmt(r.p10,0)}–${fmt(r.p90,0)}`:undefined}))
  .sort((a,b)=>b.value-a.value).slice(0,8):[];
 return <section className="day-recap day-charts" aria-labelledby="today-analytics-title">
  <div className="day-recap-head"><h2 id="today-analytics-title">{copy('Сатылым және қойма','Продажи и склад')}</h2><button className="text-button" onClick={()=>go('/sales')}>{copy('Толық талдау','Подробный анализ')}<ArrowUpRight size={15}/></button></div>
  <div className="charts-grid">
   <article className="chart-card chart-wide"><h3>{copy('Күн сайынғы сатылым, порция','Продажи по дням, порций')}</h3><DailyBars history={history} lang={lang}/></article>
   <article className="chart-card"><h3>{copy('Ең көп сатылғаны','Топ блюд')} · {date(d.as_of)}</h3><Bars items={top} empty={copy('Сатылым жоқ','Продаж нет')}/></article>
   <article className="chart-card"><h3>{copy('Болжам тағамдар бойынша','Прогноз по блюдам')}</h3>
    {forecastCurrent?<Bars items={planned} empty="—"/>:<p className="chart-empty"><button className="text-button" onClick={()=>go(urls.forecast)}>{copy('Болжам жасау','Сделать прогноз')}<ArrowRight size={14}/></button></p>}
    {planned.some(i=>i.note)&&<p className="chart-foot">{copy('Жақшада — 80% номиналды аралық (p10–p90), кепілдік емес.','Справа — номинальный интервал 80% (p10–p90), не гарантия.')}</p>}</article>
   <article className="chart-card chart-wide"><h3>{copy('Қоймада қанша бар','Сколько есть на складе')} · {date(d.inventory_date)}</h3>
    {!d.inventory_known?<p className="chart-empty">{copy('Бұл күнге қалдық белгісіз','Остатки на эту дату неизвестны')}</p>:<StockBars c={c} stock={stock} limit={12}/>}
    {stock.list.length>12&&<button className="text-button" onClick={()=>go(urls.stock)}>{copy('Барлық қойма','Весь склад')} ({fmt(stock.list.length)})<ArrowRight size={14}/></button>}
    {d.inventory_known&&stock.truncated&&<p className="chart-foot">{copy('Алғашқы 200 партия көрсетілді.','Показаны первые 200 партий.')}</p>}</article>
  </div>
 </section>;
}

type StockSummary=ReturnType<typeof useStockSummary>;

// Bars compare amounts only within one unit; kg and L are never put on one scale.
function StockBars({c,stock,limit}:{c:Context;stock:StockSummary;limit?:number}){
 const copy=(kk:string,ru:string)=>c.lang==='kk'?kk:ru;
 if(stock.loading)return <p className="chart-empty">…</p>;
 if(!stock.list.length)return <p className="chart-empty">{copy('Бұл күнге қалдық белгісіз','Остатки на эту дату неизвестны')}</p>;
 const byUnit=new Map<string,number>();stock.list.forEach(i=>byUnit.set(i.unit,Math.max(byUnit.get(i.unit)||0,i.qty)));
 const order=(i:{expired:number;soon:boolean})=>i.expired?0:i.soon?1:2;
 const rows=[...stock.list].sort((a,b)=>order(a)-order(b)||a.name.localeCompare(b.name)).slice(0,limit??stock.list.length);
 return <ol className="hbars stock-bars">{rows.map(i=><li key={i.id} className={i.expired?'is-bad':i.soon?'is-warn':undefined}><span className="hbar-label">{name(i.name)}</span>
  <span className="hbar-track"><span style={{width:Math.max(2,i.qty/Math.max(byUnit.get(i.unit)||1,0.0001)*100)+'%'}}/></span><strong>{fmt(i.qty,2)} {i.unit}</strong>
  <small>{i.expired?<><AlertTriangle size={12}/>{copy('мерзімі өткен партия бар','есть просроченная партия')}</>:i.soonest?copy('дейін ','до ')+date(i.soonest):''}</small></li>)}</ol>;
}

// The top of the stock page: how much there is on the selected snapshot date.
export function StockOverview({c}:{c:Context}){
 const copy=(kk:string,ru:string)=>c.lang==='kk'?kk:ru,day=c.inventoryDate||null;
 const stock=useStockSummary(c,day,Boolean(day)),known=Boolean(day)&&!stock.loading&&stock.complete&&stock.list.length>0;
 return <section className="stock-overview" aria-label={copy('Қойма қысқаша','Склад коротко')}>
  <div className="day-kpis stock-kpis">
   <article className="kpi"><span className="kpi-label"><Package size={14}/>{copy('Өнім түрлері','Продуктов на складе')} · {date(day)}</span><strong className="metric-value">{known?fmt(stock.count):'—'}</strong></article>
   <article className="kpi"><span className="kpi-label">{copy('Мерзімі 2 күнде бітеді','Истекает в ближайшие 2 дня')}</span><strong className="metric-value">{known?fmt(stock.soon):'—'}</strong>{known&&stock.soon>0&&<span className="kpi-chip is-warn">{copy('алдымен пайдаланыңыз','использовать в первую очередь')}</span>}</article>
   <article className="kpi"><span className="kpi-label">{t(c,'expired')}</span><strong className="metric-value">{known?fmt(stock.expired):'—'}</strong>{known&&stock.expired>0&&<span className="kpi-chip is-bad">{copy('сатып алуға есептелмейді','не учитывается в закупке')}</span>}</article>
  </div>
  <article className="chart-card"><h3>{copy('Қоймада қанша бар','Сколько есть на складе')} · {date(day)}</h3>{day?<StockBars c={c} stock={stock}/>:<p className="chart-empty">{copy('Қалдық күні таңдалмаған','Дата остатков не выбрана')}</p>}
   {stock.truncated&&<p className="chart-foot">{copy('Алғашқы 200 партия көрсетілді.','Показаны первые 200 партий.')}</p>}</article>
 </section>;
}

const t=(c:Context,key:string)=>c.t(key);
