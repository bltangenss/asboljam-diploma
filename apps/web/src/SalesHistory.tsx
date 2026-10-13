import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowRight,RefreshCw} from 'lucide-react';
import {api,date,fmt,name,type Context,type Row} from './shared';

// The list API has no aggregate endpoint or snapshot token. Read every page before
// making a period summary, bound the work, and discard responses from old filters.
const PAGE_SIZE=200,MAX_ROWS=10000,MAX_DAYS=366,DAY_MS=86400000;
type Loaded={status:'loading'|'ready'|'limit'|'changed'|'error';rows:Row[];total:number|null};
function dayNumber(value:string){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return NaN;
 const valueMs=Date.parse(value+'T00:00:00Z');
 return Number.isFinite(valueMs)&&new Date(valueMs).toISOString().slice(0,10)===value?valueMs/DAY_MS:NaN;
}
type Props={context:Context;from:string;to:string;meal:string;meals:Row[];mode:'day'|'period'};
export default function SalesHistory({context:c,from,to,meal,meals,mode}:Props){
 const kk=c.lang==='kk',start=dayNumber(from),end=dayNumber(to),span=end-start+1;
 const valid=!!c.branch&&Number.isInteger(span)&&span>0&&span<=MAX_DAYS;
 const [attempt,setAttempt]=useState(0),[loaded,setLoaded]=useState<Loaded>({status:'loading',rows:[],total:null});
 const chartRef=useRef<HTMLDivElement>(null),[chartWidth,setChartWidth]=useState(780);
 useEffect(()=>{
  const element=chartRef.current;if(!element)return;
  const measure=()=>setChartWidth(Math.max(180,Math.round(element.getBoundingClientRect().width)));
  measure();const observer=new ResizeObserver(measure);observer.observe(element);
  return()=>observer.disconnect();
 },[loaded.status,valid]);
 useEffect(()=>{
  const controller=new AbortController();let active=true;
  setLoaded({status:'loading',rows:[],total:null});
  if(!valid)return()=>{active=false;controller.abort()};
  async function collect(){
   let cursor=0,total:number|null=null;const rows:Row[]=[],keys=new Set<string>();
   const finish=(status:Loaded['status'])=>{if(active)setLoaded({status,rows:status==='ready'?rows:[],total})};
   try{
    while(active){
     const params=new URLSearchParams({branch_id:c.branch,date_from:from,date_to:to,limit:String(PAGE_SIZE),cursor:String(cursor)});
     if(meal)params.set('meal_id',meal);
     const page=await api.request<{items:Row[];total:number;next_cursor:string|null}>('/sales?'+params,{signal:controller.signal});
     if(!active)return;
     if(!Number.isSafeInteger(page.total)||page.total<0||!Array.isArray(page.items)||page.items.length>PAGE_SIZE||total!==null&&page.total!==total){finish('changed');return}
     total=page.total;
     if(total>MAX_ROWS){finish('limit');return}
     for(const row of page.items){
      const rowDay=dayNumber(row.date),sold=row.units_sold;
      const key=JSON.stringify([row.date,row.meal_id]);
      if(String(row.branch_id)!==c.branch||typeof row.meal_id!=='string'||!row.meal_id||meal&&row.meal_id!==meal||!Number.isFinite(rowDay)||rowDay<start||rowDay>end||sold==null||!['string','number'].includes(typeof sold)||String(sold).trim()===''||!Number.isSafeInteger(Number(sold))||Number(sold)<0||keys.has(key)){finish('changed');return}
      keys.add(key);rows.push(row);
     }
     if(rows.length>MAX_ROWS||rows.length>total){finish('changed');return}
     if(page.next_cursor===null){finish(rows.length===total?'ready':'changed');return}
     const next=Number(page.next_cursor);
     if(!page.items.length||!Number.isSafeInteger(next)||next!==cursor+PAGE_SIZE||rows.length>=MAX_ROWS){finish('changed');return}
     cursor=next;
    }
   }catch{if(active)finish('error')}
  }
  void collect();
  return()=>{active=false;controller.abort()};
 },[c.branch,c.revision,from,to,meal,valid,start,end,attempt]);
 const overview=useMemo(()=>{
  if(loaded.status!=='ready'||!valid)return null;
  const names=new Map(meals.map(row=>[String(row.meal_id),row.meal_name]));
  const dishes=new Map<string,{id:string;label:string;days:Set<string>;sold:number}>();
  if(meal)dishes.set(meal,{id:meal,label:name(names.get(meal)||meal),days:new Set(),sold:0});
  const byDate=new Map<string,{sold:number;meals:Set<string>}>();let sold=0;
  for(const row of loaded.rows){
   const dish=dishes.get(row.meal_id)||{id:row.meal_id,label:name(row.meal_name||names.get(row.meal_id)||row.meal_id),days:new Set<string>(),sold:0};
   if(row.meal_name) dish.label=name(row.meal_name);
   dish.days.add(row.date);dish.sold+=Number(row.units_sold);dishes.set(row.meal_id,dish);
   const day=byDate.get(row.date)||{sold:0,meals:new Set<string>()};day.sold+=Number(row.units_sold);day.meals.add(row.meal_id);byDate.set(row.date,day);sold+=Number(row.units_sold);
  }
  if(!Number.isSafeInteger(sold))return null;
  const days=Array.from({length:span},(_,index)=>{
   const key=new Date((start+index)*DAY_MS).toISOString().slice(0,10),entry=byDate.get(key);
   return {date:key,sold:entry?.sold??null,complete:dishes.size>0&&entry?.meals.size===dishes.size};
  });
  const fullDays=days.filter(day=>day.complete).length;
  return {dishes:[...dishes.values()].sort((a,b)=>b.sold-a.sold||a.id.localeCompare(b.id)),days,sold,fullDays,complete:dishes.size>0&&fullDays===span};
 },[loaded,valid,meal,meals,span,start]);
 const retry=<button className="text-button" onClick={()=>setAttempt(value=>value+1)}><RefreshCw size={15}/>{kk?'Қайта жүктеу':'Загрузить заново'}</button>;
 if(!valid)return <section className="sales-overview sales-overview-message" aria-label={kk?'Сатылым шолуы':'Обзор продаж'}><h2>{kk?'График кезеңін таңдаңыз':'Выберите период графика'}</h2><p>{kk?'Басталу және аяқталу күнін көрсетіңіз: шолу 1–366 күн аралығын қамтиды. Кесте мен экспорт өз сүзгілерін сақтайды.':'Укажите начало и конец: обзор поддерживает от 1 до 366 дней. Таблица и экспорт сохраняют свои фильтры.'}</p></section>;
 if(loaded.status!=='ready')return <section className="sales-overview sales-overview-message" aria-label={kk?'Сатылым шолуы':'Обзор продаж'} aria-busy={loaded.status==='loading'}><h2>{kk?'Кезеңдегі сатылым':'Продажи за период'}</h2><p role="status">{loaded.status==='loading'?(kk?'Кезеңнің барлық жолы жүктеліп жатыр…':'Загружаем все строки выбранного периода…'):loaded.status==='limit'?(kk?`Кезеңде ${fmt(loaded.total)} жол бар. Шолу шегі — ${fmt(MAX_ROWS)} жол: кезеңді қысқартыңыз немесе бір тағамды таңдаңыз.`:`В периоде ${fmt(loaded.total)} строк. Предел обзора — ${fmt(MAX_ROWS)} строк: сократите период или выберите одно блюдо.`):loaded.status==='changed'?(kk?'Беттердегі деректер сәйкес келмеді. Толық емес жиынтық көрсетілмейді; шолуды қайта жүктеңіз.':'Данные между страницами не совпали. Неполный итог не показан; загрузите обзор заново.'):(kk?'Кезеңді толық жүктеу мүмкін болмады. Кестедегі бір беттен жалпы қорытынды жасалмайды.':'Не удалось загрузить весь период. По одной странице таблицы общий итог не рассчитывается.')}</p>{loaded.status!=='loading'&&loaded.status!=='limit'&&retry}</section>;
 if(!overview)return <section className="sales-overview sales-overview-message"><p role="status">{kk?'Порция санын қауіпсіз қосу мүмкін болмады. CSV деректерін тексеріңіз.':'Не удалось безопасно сложить число порций. Проверьте данные CSV.'}</p></section>;
 const present=overview.days.filter(day=>day.sold!==null),max=Math.max(1,...overview.days.filter(day=>day.complete).map(day=>day.sold??0));
 const left=Math.max(48,Math.min(140,fmt(max).length*6+12)),right=chartWidth-14;
 const chartX=(index:number)=>span===1?(left+right)/2:left+index/(span-1)*(right-left),chartY=(value:number)=>184-value/max*150;
 const segments:string[][]=[];
 overview.days.forEach((day,index)=>{if(!day.complete){segments.push([]);return}if(!segments.length)segments.push([]);segments[segments.length-1].push(`${chartX(index)},${chartY(day.sold??0)}`)});
 const tickIndexes=[...new Set(chartWidth<480?[0,span-1]:[0,Math.floor((span-1)/2),span-1])];
 const heading=mode==='day'?(kk?'Бір күнде не сатылды?':'Что продано за день?'):(kk?'Күндер бойынша нақты сатылым':'Фактические продажи по дням');
 return <section className="sales-overview" aria-label={kk?'Сатылым шолуы':'Обзор продаж'}>
  <div className="sales-overview-top"><div><span className="reference-kicker">{c.branchName||c.branch} · {kk?'Таңдалған деректер':'Выбранные данные'}</span><h2>{heading}</h2></div>{retry}</div>
  <dl className="sales-period-facts">
   <div><dt>{mode==='day'?(kk?'Күндегі порциялар':'Порции за день'):(kk?'Кезеңдегі порциялар':'Порции за период')}</dt><dd data-testid="sales-period-total">{overview.complete?fmt(overview.sold):'—'}</dd><small>{overview.complete?(kk?'Көрсетілген тағамдар бойынша':'По представленным блюдам'):(kk?`Бар жолдарда: ${fmt(overview.sold)} порция. Толық жиынтық белгісіз.`:`В имеющихся строках: ${fmt(overview.sold)} порций. Полный итог неизвестен.`)}</small></div>
   <div><dt>{kk?'Жолдары бар күндер':'Даты с записями'}</dt><dd className="sales-date-range">{present.length?date(present[0].date):'—'}{present.length>1&&<><span> — </span>{date(present[present.length-1].date)}</>}</dd><small>{kk?`Таңдалған кезең: ${span} күн`:`Выбранный период: ${span} дн.`}</small></div>
   <div><dt>{kk?'Тарихта көрінген тағамдар':'Блюда в истории'}</dt><dd>{fmt(overview.dishes.filter(dish=>dish.days.size).length)}</dd><small>{kk?`${fmt(loaded.rows.length)} жол, барлық бет жүктелді`:`${fmt(loaded.rows.length)} строк, все страницы загружены`}</small></div>
   <div><dt>{kk?'Барлық осы тағамы бар күндер':'Дни со всеми этими блюдами'}</dt><dd data-testid="sales-days-coverage">{overview.fullDays}<span> / {span}</span></dd><small>{overview.complete?(kk?'Таңдалған кезеңде жолдар үзілмейді':'В выбранном периоде нет пропусков строк'):(kk?'Жоқ жолдар нөлге ауыстырылмайды':'Пропуски не заменены нулями')}</small></div>
  </dl>
  {present.length>0&&<>
   <div className="sales-chart-caption"><span><i/>{kk?'Порциялар / күн':'Порции / день'}</span>{!overview.complete&&<span className="sales-chart-gap"><i/>{kk?'Толық емес күн — график үзіледі':'Неполный день — разрыв графика'}</span>}</div>
   <div ref={chartRef}><svg className="sales-history-chart" viewBox={`0 0 ${chartWidth} 240`} role="img" aria-label={heading+'; '+(kk?'Күндер мәндері төмендегі тізімде.':'Значения по датам доступны в списке ниже.')}>
    <title>{heading}</title><desc>{kk?'Жоқ немесе толық емес күндер сызықпен қосылмайды. Нақты нөлдік сатылым нөл деңгейінде көрсетіледі.':'Дни без данных или с неполными данными не соединены линией. Зафиксированные нулевые продажи показаны на нулевом уровне.'}</desc>
    {[0,.5,1].map(factor=><g key={factor}><line x1={left} x2={right} y1={chartY(max*factor)} y2={chartY(max*factor)} className="sales-chart-grid"/><text x={left-10} y={chartY(max*factor)+4} textAnchor="end">{fmt(max*factor,max<10?1:0)}</text></g>)}
    {segments.filter(segment=>segment.length>1).map((segment,index)=><polyline key={index} points={segment.join(' ')} className="sales-chart-line"/>)}
    {overview.days.map((day,index)=>day.complete?<circle key={day.date} cx={chartX(index)} cy={chartY(day.sold??0)} r={span<=31?4:2} className="sales-chart-point"><title>{date(day.date)}: {fmt(day.sold)} {kk?'порция':'порций'}</title></circle>:<path key={day.date} d={`M${chartX(index)-3},199 l6,6 m-6,0 l6,-6`} className="sales-chart-missing"><title>{date(day.date)}: {kk?'толық емес күн':'неполный день'}</title></path>)}
    {tickIndexes.map(index=><text key={index} x={chartX(index)} y="229" textAnchor={span===1?'middle':index===0?'start':index===span-1?'end':'middle'}>{date(overview.days[index].date)}</text>)}
   </svg></div>
  </>}
  {!present.length&&<p className="sales-history-notice">{kk?'Таңдалған күндерде сатылым жолдары жоқ. Жалпы сатылым мен толықтық белгісіз.':'В выбранные даты нет строк продаж. Общий объём продаж и полнота неизвестны.'}</p>}
  <p className="sales-history-notice">{kk?'Шолу тек осы бөлімше, кезең және тарихта көрінген тағамдар үшін жасалды. Кезеңде мүлде кездеспеген тағамдар тексерілмейді. Бұл 84 күндік болжамға дайындық кепілдігі емес — оны есептеу тексереді.':'Обзор относится только к этому филиалу, периоду и блюдам, встречающимся в истории. Блюда без единой строки в периоде не проверены. Это не гарантия готовности к прогнозу на основе 84 дней — её проверяет расчёт.'}</p>
  {!!overview.dishes.length&&<details className="sales-history-details"><summary>{kk?'Тағамдар және жоқ күндер':'Блюда и пропущенные дни'}<ArrowRight size={16}/></summary><div className="sales-coverage-list">{overview.dishes.slice(0,50).map(dish=>{
   const missing=overview.days.filter(day=>!dish.days.has(day.date));
   return <div className="sales-coverage-row" key={dish.id}><strong>{dish.label}<small className="reference-code">ID: {dish.id}</small></strong><span>{dish.days.size} / {span} {kk?'күн':'дн.'}</span><span>{fmt(dish.sold)} {kk?'тіркелген порция':'зафиксированных порций'}</span><small>{missing.length?(kk?`${missing.length} күн жоқ. Біріншісі: ${date(missing[0].date)}`:`Нет ${missing.length} дн. Первый: ${date(missing[0].date)}`):(kk?'Жолдарда үзіліс жоқ':'Нет пропусков строк')}</small></div>
  })}</div>{overview.dishes.length>50&&<p>{kk?'Алғашқы 50 тағам көрсетілген. Қалған жолдар кесте мен экспортта бар; шолу барлық жүктелген жолға есептелді.':'Показаны первые 50 блюд. Остальные строки доступны в таблице и экспорте; обзор рассчитан по всем загруженным строкам.'}</p>}</details>}
  {present.length>0&&<details className="sales-history-details"><summary>{kk?'График мәндерін оқу':'Прочитать значения графика'}<ArrowRight size={16}/></summary><dl className="sales-chart-values">{overview.days.map(day=><div key={day.date}><dt>{date(day.date)}</dt><dd>{day.complete?`${fmt(day.sold)} ${kk?'порция':'порций'}`:day.sold===null?(kk?'Жолдар жоқ; сатылым белгісіз':'Нет строк; продажи неизвестны'):(kk?`Күн толық емес; бар жолдарда ${fmt(day.sold)} порция`:`День неполный; в имеющихся строках ${fmt(day.sold)} порций`)}</dd></div>)}</dl></details>}
  <p className="sales-read-note">{kk?'Бұл — жүктелген жолдардың шолуы, тұрақты live-сурет емес. Қатар импорт жасалса, қайта жүктеңіз. Сатылған порциялар жасырын сұранысты өлшемейді.':'Это обзор загруженных строк, а не непрерывно обновляемый или атомарный снимок. При параллельном импорте загрузите его заново. Проданные порции не измеряют скрытый спрос.'}</p>
 </section>;
}
