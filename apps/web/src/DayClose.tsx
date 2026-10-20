import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {ArrowLeft,CheckCircle2,ClipboardCheck,Lock,RotateCcw,Save,Store} from 'lucide-react';
import {type Context,type Row,api,date,fmt,name,Badge,DataState,useData} from './shared';

// Closing the day on a phone: every dish is explicitly sold or not offered, an empty field stays
// unknown, and the server records the day's sales once, in one transaction, on confirmation.
type Entry={meal_id:string;state:'sold'|'not_offered'|null;units_sold:number|null;available_portions:number|null;stockout_flag:0|1|null;
 stockout_time:string|null;replenished_time:string|null;promo:0|1|null;price_kzt:string|null};
const FIELDS=['units_sold','available_portions','stockout_flag','promo','price_kzt'] as const;
const blank=(meal_id:string):Entry=>({meal_id,state:null,units_sold:null,available_portions:null,stockout_flag:null,stockout_time:null,replenished_time:null,promo:null,price_kzt:null});
const count=(value:string)=>{const digits=value.replace(/\D/g,'').slice(0,10);return digits===''?null:Number(digits)};

function Choice<T extends string|number>({label,value,options,onChange,disabled}:{label:string;value:T|null;options:[T,string][];onChange:(value:T)=>void;disabled?:boolean}){
 return <div className="day-choice" role="group" aria-label={label}>{options.map(([option,text])=><button key={String(option)} type="button" aria-pressed={value===option} disabled={disabled} onClick={()=>onChange(option)}>{text}</button>)}</div>;
}

export default function DayClose(c:Context){
 const kk=c.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru;
 const [day,setDay]=useState(()=>new URLSearchParams(c.route.split('?')[1]||'').get('date')||'');
 const state=useData(c.branch?`/day-close?branch_id=${encodeURIComponent(c.branch)}${day?'&business_date='+day:''}`:null,c.revision);
 const data=state.data as Row|null;
 const [isOpen,setIsOpen]=useState<0|1|null>(null),[lines,setLines]=useState<Record<string,Entry>>({}),[dirty,setDirty]=useState(false);
 const [busy,setBusy]=useState(''),[error,setError]=useState<any>(null),[notice,setNotice]=useState('');
 const [review,setReview]=useState(false),[conflict,setConflict]=useState<Row[]|null>(null),[reason,setReason]=useState(''),[reopening,setReopening]=useState(false);
 const keys=useRef<Record<string,{body:string;key:string}>>({}),dirtyRef=useRef(false),pending=useRef(false);
 const meals:Row[]=data?.meals||[],closed=data?.status==='closed';
 const canWrite=['admin','manager'].includes(c.user.role)&&c.dataContext?.operations_enabled===true;
 // Server state fills the form only while nothing local is unsaved.
 useEffect(()=>{if(!data||dirtyRef.current)return;setIsOpen(data.is_open??null);setLines(Object.fromEntries(meals.map(meal=>[meal.meal_id,{...blank(meal.meal_id),...(meal.entry||{})}])))},[data]);
 useLayoutEffect(()=>c.registerNavigationBlocker?.({read:()=>pending.current?'pending':dirtyRef.current?'dirty':'clean',
  discard:()=>{if(pending.current)return false;dirtyRef.current=false;setDirty(false);return true}}),[c.registerNavigationBlocker]);
 const touch=()=>{dirtyRef.current=true;setDirty(true);setNotice('');setConflict(null)};
 const setLine=(id:string,patch:Partial<Entry>)=>{setLines(all=>({...all,[id]:{...(all[id]||blank(id)),...patch}}));touch()};
 const bulk=(apply:(entry:Entry,meal:Row)=>Partial<Entry>|null)=>{setLines(all=>Object.fromEntries(meals.map(meal=>{const entry=all[meal.meal_id]||blank(meal.meal_id),patch=apply(entry,meal);return [meal.meal_id,patch?{...entry,...patch}:entry]})));touch()};
 // Mirrors the server rule for live progress; the server decides when the day is closed.
 const progress=useMemo(()=>{
  const missing:{meal:Row;fields:string[]}[]=[],invalid:Row[]=[],unmarked:Row[]=[];let sold=0,off=0,portions=0;const ran:Row[]=[];
  if(isOpen===1)meals.forEach(meal=>{const entry=lines[meal.meal_id]||blank(meal.meal_id);
   if(entry.state==='not_offered')off++;
   else if(entry.state==='sold'){sold++;const fields=FIELDS.filter(field=>entry[field]===null);if(fields.length)missing.push({meal,fields});
    else if((entry.units_sold??0)>(entry.available_portions??0))invalid.push(meal);portions+=entry.units_sold??0;if(entry.stockout_flag===1)ran.push(meal)}
   else unmarked.push(meal)});
  return {missing,invalid,unmarked,sold,off,portions,ran,complete:isOpen===0||(isOpen===1&&!missing.length&&!invalid.length&&!unmarked.length)};
 },[lines,isOpen,meals]);
 const label:Record<string,[string,string]>={units_sold:['сатылғаны','продано'],available_portions:['дайыны','готово'],stockout_flag:['бітті ме','закончилось ли'],promo:['акция','акция'],price_kzt:['бағасы','цена']};
 const messages:Record<string,[string,string]>={DAY_INCOMPLETE:['Күнді жабу үшін жетіспейтін деректерді толтырыңыз.','Чтобы закрыть день, заполните недостающие данные.'],
  DAY_CONFLICT:['Бұл күнге басқа мәндер сақталған. Түзету себебін көрсетіңіз.','На этот день сохранены другие значения. Укажите причину исправления.'],
  DAY_CLOSED:['Күн жабылған. Өзгерту үшін алдымен қайта ашыңыз.','День закрыт. Чтобы изменить, сначала откройте его снова.'],
  STALE_VERSION:['Жобаны басқа адам өзгерткен. Бетті жаңартып, қайта тексеріңіз.','Черновик изменил другой пользователь. Обновите страницу и проверьте снова.'],
  BUSINESS_DATE_NOT_CLOSED:['Бұл күн әлі аяқталмады: жоба ретінде сақтаңыз, ал күнді ол аяқталғаннан кейін жабасыз.','День ещё не закончился: сохраните черновик, а закрыть день можно будет после его окончания.'],
  BUSINESS_DATE_IN_FUTURE:['Бұл күн әлі келген жоқ.','Этот день ещё не наступил.'],DAY_LINES_INVALID:['Кейбір тағамдар қате толтырылған.','Некоторые блюда заполнены с ошибками.'],
  RECORDED_SALES_NOT_LISTED:['Сатылымы сақталған тағам «ұсынылмады» деп белгіленген.','Блюдо с сохранёнными продажами отмечено как «не предлагалось».'],
  CONCURRENT_CLOSE:['Күнді бір уақытта басқа адам жапты. Бетті жаңартыңыз.','День одновременно закрыл другой пользователь. Обновите страницу.']};
 const message=(problem:any)=>messages[problem?.code]?.[kk?0:1]||(c.t('error_'+problem?.code)!=='error_'+problem?.code?c.t('error_'+problem?.code):problem?.message);
 async function call(kind:string,method:string,path:string,payload:object){
  const body=JSON.stringify(payload),previous=keys.current[kind];
  // A retry of the same request after a lost answer reuses its key, so it is applied once.
  const key=previous&&previous.body===body?previous.key:crypto.randomUUID();keys.current[kind]={body,key};
  pending.current=true;setBusy(kind);setError(null);
  try{const result=await api.request<Row>(path,{method,body,headers:{'Idempotency-Key':key}});delete keys.current[kind];return result}
  finally{pending.current=false;setBusy('')}
 }
 const entries=()=>meals.map(meal=>lines[meal.meal_id]).filter(entry=>entry&&(entry.state||FIELDS.some(field=>entry[field]!==null)));
 async function save(){
  try{const saved=await call('save','PUT','/day-close',{branch_id:c.branch,business_date:data!.business_date,expected_version:data!.version,is_open:isOpen,lines:entries()});
   dirtyRef.current=false;setDirty(false);setNotice(copy('Жоба сақталды','Черновик сохранён'));c.refresh();return saved}
  catch(problem){setError(problem);return null}
 }
 async function closeDay(){
  let version=data!.version;
  if(dirtyRef.current||!version){const saved=await save();if(!saved)return;version=saved.version}
  try{await call('close','POST','/day-close/close',{branch_id:c.branch,business_date:data!.business_date,expected_version:version,...(conflict?{correction_reason:reason.trim()}:{})});
   setReview(false);setConflict(null);setReason('');setNotice(copy('Күн жабылды. Сатылым сақталды.','День закрыт. Продажи сохранены.'));c.refresh()}
  catch(problem:any){if(problem?.code==='DAY_CONFLICT')setConflict((problem.details?.details as Row[])||[]);setError(problem)}
 }
 async function reopen(){
  try{await call('reopen','POST','/day-close/reopen',{branch_id:c.branch,business_date:data!.business_date,expected_version:data!.version,reason:reason.trim()});
   setReopening(false);setReason('');setNotice(copy('Күн түзету үшін ашылды.','День открыт для исправления.'));c.refresh()}
  catch(problem){setError(problem)}
 }
 const names=Object.fromEntries(meals.map(meal=>[meal.meal_id,name(meal.meal_name||meal.meal_id)]));
 return <div className="day-close-page">
  <button className="text-button day-close-back" onClick={()=>c.go('/dashboard')}><ArrowLeft size={15}/>{copy('Бүгін','Сегодня')}</button>
  <DataState state={state} t={c.t} retry={c.refresh}>{data&&<>
   <header className="day-close-head">
    <h1>{copy('Күнді жабу','Закрыть день')}</h1>
    <p className="day-close-context"><Store size={15} aria-hidden="true"/><span>{c.branchName||c.branch}</span><strong>{date(data.business_date)}</strong>
     <Badge tone={closed?'green':dirty||data.status==='draft'?'amber':'neutral'}>{closed?copy('Жабылды','Закрыт'):dirty?copy('Сақталмаған','Не сохранено'):data.status==='draft'?copy('Жоба сақталған','Черновик сохранён'):copy('Басталмаған','Не начат')}</Badge></p>
    {data.data_origin==='REAL'?<label className="day-close-date">{copy('Күн','Дата')}<input type="date" value={day||data.business_date} max={data.default_date>data.business_date?data.default_date:data.business_date}
      onChange={event=>{if(!dirtyRef.current&&event.target.value)setDay(event.target.value)}}/></label>
     :<p className="day-close-note">{copy('Оқу сценарийі: күн 01.01.2026 болып қалады, компьютердегі күнге байланысты емес.','Учебный сценарий: дата остаётся 01.01.2026 и не зависит от даты на компьютере.')}</p>}
   </header>
   {notice&&<p className="alert success" role="status"><CheckCircle2 size={17}/>{notice}</p>}
   {error&&!review&&<p className="alert danger" role="alert">{message(error)}</p>}
   {!data.closable&&!closed&&<p className="alert info">{copy('Бұл күн әлі аяқталмады: деректерді жоба ретінде сақтай аласыз, ал күнді ол аяқталғаннан кейін жабасыз.','День ещё не закончился: данные можно сохранить черновиком, а закрыть день — после его окончания.')}</p>}
   {closed?<section className="day-close-card is-closed" aria-labelledby="day-closed-title">
     <Lock size={20} aria-hidden="true"/><h2 id="day-closed-title">{copy('Күн жабылды','День закрыт')}</h2>
     <p>{data.closed_at?new Date(data.closed_at).toLocaleString(kk?'kk-KZ':'ru-RU'):'—'} · {data.closed_by||'—'}</p>
     <dl className="day-close-totals"><div><dt>{copy('Сатылды','Продано')}</dt><dd>{data.is_open===0?copy('Мекеме жабық','Заведение закрыто'):fmt(progress.portions)+' '+copy('порция','порций')}</dd></div>
      <div><dt>{copy('Ұсынылмады','Не предлагалось')}</dt><dd>{fmt(progress.off)}</dd></div><div><dt>{copy('Бітіп қалды','Закончилось')}</dt><dd>{progress.ran.length?progress.ran.map(meal=>names[meal.meal_id]).join(', '):'—'}</dd></div></dl>
     {data.reason&&<p className="day-close-note">{copy('Себебі','Причина')}: {data.reason}</p>}
     {canWrite&&!reopening&&<button className="button secondary" onClick={()=>{setReopening(true);setReason('')}}><RotateCcw size={16}/>{copy('Түзету үшін ашу','Открыть для исправления')}</button>}
     {reopening&&<div className="day-close-reopen"><label>{copy('Неге қайта ашасыз?','Почему открываете снова?')}<textarea value={reason} maxLength={1000} onChange={event=>setReason(event.target.value)}/></label>
      <div className="day-close-actions"><button className="button secondary" onClick={()=>setReopening(false)}>{copy('Бас тарту','Отмена')}</button>
       <button className="button primary" disabled={reason.trim().length<3||Boolean(busy)} onClick={reopen}>{copy('Қайта ашу','Открыть снова')}</button></div></div>}
    </section>
   :review?<section className="day-close-card day-close-review" aria-labelledby="day-review-title">
     <ClipboardCheck size={20} aria-hidden="true"/><h2 id="day-review-title">{copy('Жабар алдында тексеріңіз','Проверьте перед закрытием')}</h2>
     <dl className="day-close-totals">{isOpen===0?<div><dt>{copy('Күн','День')}</dt><dd>{copy('Мекеме жабық болды — барлық тағамға нөлдік сатылым','Заведение было закрыто — нулевые продажи по всем блюдам')}</dd></div>:<>
      <div><dt>{copy('Сатылды','Продано')}</dt><dd>{fmt(progress.portions)} {copy('порция','порций')} · {progress.sold} {copy('тағам','блюд')}</dd></div>
      <div><dt>{copy('Ұсынылмады','Не предлагалось')}</dt><dd>{progress.off}</dd></div>
      <div><dt>{copy('Бітіп қалды','Закончилось')}</dt><dd>{progress.ran.length?progress.ran.map(meal=>names[meal.meal_id]).join(', '):'—'}</dd></div></>}</dl>
     {!progress.complete&&<div className="alert warning" role="status"><div><strong>{copy('Жабу үшін жетіспейді','Для закрытия не хватает')}</strong><ul>
      {isOpen===null&&<li>{copy('Мекеме жұмыс істеді ме — белгіленбеген','Не отмечено, работало ли заведение')}</li>}
      {progress.unmarked.map(meal=><li key={meal.meal_id}>{names[meal.meal_id]}: {copy('сатылды ма, ұсынылмады ма — белгіленбеген','не отмечено, продавалось ли')}</li>)}
      {progress.missing.map(({meal,fields})=><li key={meal.meal_id}>{names[meal.meal_id]}: {fields.map(field=>label[field][kk?0:1]).join(', ')}</li>)}
      {progress.invalid.map(meal=><li key={meal.meal_id}>{names[meal.meal_id]}: {copy('сатылғаны дайынынан көп','продано больше, чем было готово')}</li>)}</ul></div></div>}
     {conflict&&<div className="alert warning"><div><strong>{copy('Бұл күнге басқа мәндер сақталған','На этот день уже сохранены другие значения')}</strong>
      <ul>{conflict.map(row=><li key={row.meal_id}>{names[row.meal_id]||row.meal_id}: {copy('сақталған','сохранено')} {fmt(row.recorded?.units_sold)} → {copy('енгізілген','введено')} {fmt(row.entered?.units_sold)}</li>)}</ul>
      <label>{copy('Түзету себебі','Причина исправления')}<textarea value={reason} maxLength={1000} onChange={event=>setReason(event.target.value)}/></label></div></div>}
     {error&&<p className="alert danger" role="alert">{message(error)}</p>}
     <div className="day-close-actions"><button className="button secondary" onClick={()=>{setReview(false);setConflict(null);setError(null)}}>{copy('Артқа','Назад')}</button>
      <button className="button primary" disabled={!progress.complete||!data.closable||Boolean(busy)||Boolean(conflict&&reason.trim().length<3)} onClick={closeDay}>
       {busy==='close'||busy==='save'?<span className="spinner"/>:<Lock size={16}/>}{conflict?copy('Түзетіп жабу','Исправить и закрыть'):copy('Күнді жабу','Закрыть день')}</button></div>
    </section>
   :<>
    <section className="day-close-card"><h2>{copy('Мекеме осы күні жұмыс істеді ме?','Заведение в этот день работало?')}</h2>
     <Choice label={copy('Мекеме жұмыс істеді ме?','Заведение работало?')} value={isOpen} disabled={!canWrite} options={[[1,copy('Иә, жұмыс істеді','Да, работало')],[0,copy('Жоқ, жабық болды','Нет, было закрыто')]]} onChange={value=>{setIsOpen(value);touch()}}/>
     {isOpen===0&&<p className="day-close-note">{copy('Барлық тағамға нөлдік сатылым жазылады — бұл «дерек жоқ» емес, расталған жабық күн.','Для всех блюд запишутся нулевые продажи — это не «нет данных», а подтверждённый закрытый день.')}</p>}
    </section>
    {isOpen===1&&<>
     {canWrite&&<div className="day-close-quick" aria-label={copy('Жылдам белгілеу','Быстрая отметка')}>
      <button className="button secondary" onClick={()=>bulk(entry=>entry.state?null:{state:'sold'})}>{copy('Барлығы ұсынылды','Все блюда были в меню')}</button>
      <button className="button secondary" onClick={()=>bulk(entry=>entry.state==='sold'&&entry.stockout_flag===null?{stockout_flag:0}:null)}>{copy('Ешбірі бітпеді','Ничего не закончилось')}</button>
      <button className="button secondary" onClick={()=>bulk(entry=>entry.state==='sold'&&entry.promo===null?{promo:0}:null)}>{copy('Акция болмады','Акций не было')}</button>
      <button className="button secondary" onClick={()=>bulk((entry,meal)=>entry.state==='sold'&&entry.price_kzt===null?{price_kzt:String(meal.base_price_kzt)}:null)}>{copy('Бағалар мәзір бойынша','Цены по меню')}</button>
     </div>}
     <ul className="day-close-meals">{meals.map(meal=>{const id=meal.meal_id,entry=lines[id]||blank(id),ref=meal.reference||{};
      const missing=entry.state==='sold'?FIELDS.filter(field=>entry[field]===null):[];
      return <li key={id} className={'day-close-meal'+(entry.state==='not_offered'?' is-off':'')+(entry.state===null?' is-unmarked':'')}>
       <div className="day-close-meal-head"><strong>{names[id]}</strong><small>{[ref.previous_day_units_sold!=null?copy('Кеше','Вчера')+': '+fmt(ref.previous_day_units_sold):'',ref.planned_portions!=null?copy('Жоспар','План')+': '+fmt(ref.planned_portions):''].filter(Boolean).join(' · ')||copy('Кешегі дерек пен жоспар жоқ','Нет данных за вчера и плана')}</small></div>
       <Choice label={names[id]} value={entry.state} disabled={!canWrite} options={[['sold',copy('Сатылды','Продавалось')],['not_offered',copy('Ұсынылмады','Не предлагалось')]]}
        onChange={value=>setLine(id,value==='not_offered'?{...blank(id),state:'not_offered'}:{state:value})}/>
       {entry.state==='sold'&&<div className="day-close-fields">
        <label>{copy('Сатылды, порция','Продано, порций')}<input inputMode="numeric" value={entry.units_sold??''} disabled={!canWrite} onChange={event=>setLine(id,{units_sold:count(event.target.value)})}/></label>
        <label>{copy('Дайын болды, порция','Было готово, порций')}<input inputMode="numeric" value={entry.available_portions??''} disabled={!canWrite} onChange={event=>setLine(id,{available_portions:count(event.target.value)})}/></label>
        <div className="day-close-flag"><span>{copy('Бітіп қалды ма?','Закончилось?')}</span><Choice label={copy('Бітіп қалды ма?','Закончилось?')} value={entry.stockout_flag} disabled={!canWrite} options={[[1,copy('Иә','Да')],[0,copy('Жоқ','Нет')]]}
         onChange={value=>setLine(id,value===0?{stockout_flag:0,stockout_time:null,replenished_time:null}:{stockout_flag:1})}/></div>
        {entry.stockout_flag===1&&<div className="day-close-times">
         <label>{copy('Қашан бітті','Когда закончилось')}<input type="time" value={entry.stockout_time??''} disabled={!canWrite} onChange={event=>setLine(id,{stockout_time:event.target.value||null})}/></label>
         <label>{copy('Қашан толықтырылды','Когда пополнили')}<input type="time" value={entry.replenished_time??''} disabled={!canWrite} onChange={event=>setLine(id,{replenished_time:event.target.value||null})}/></label></div>}
        <div className="day-close-flag"><span>{copy('Акция болды ма?','Была акция?')}</span><Choice label={copy('Акция болды ма?','Была акция?')} value={entry.promo} disabled={!canWrite} options={[[1,copy('Иә','Да')],[0,copy('Жоқ','Нет')]]} onChange={value=>setLine(id,{promo:value})}/></div>
        <label>{copy('Бағасы, ₸','Цена, ₸')}<input inputMode="decimal" value={entry.price_kzt??''} placeholder={copy('мәзірде','в меню')+' '+fmt(meal.base_price_kzt)} disabled={!canWrite}
         onChange={event=>{const text=event.target.value.replace(',','.').replace(/[^\d.]/g,'');setLine(id,{price_kzt:text===''?null:text})}}/></label>
       </div>}
       {missing.length>0&&<p className="day-close-missing">{copy('Толтырылмаған','Не заполнено')}: {missing.map(field=>label[field][kk?0:1]).join(', ')}</p>}
      </li>})}</ul>
    </>}
    {canWrite&&<div className="day-close-bar">
     <span>{isOpen===null?copy('Мекеме жұмыс істеді ме — белгіленбеген','Не отмечено, работало ли заведение'):isOpen===0?copy('Жабық күн','Закрытый день')
      :copy(`${meals.length-progress.unmarked.length-progress.missing.length-progress.invalid.length} / ${meals.length} тағам дайын`,`Готово ${meals.length-progress.unmarked.length-progress.missing.length-progress.invalid.length} из ${meals.length} блюд`)}</span>
     <button className="button secondary" disabled={!dirty||Boolean(busy)} onClick={save}>{busy==='save'?<span className="spinner"/>:<Save size={16}/>}{copy('Сақтау','Сохранить')}</button>
     <button className="button primary" disabled={Boolean(busy)} onClick={()=>{setReview(true);setError(null)}}><ClipboardCheck size={16}/>{copy('Тексеру','Проверить')}</button>
    </div>}
   </>}
  </>}</DataState>
 </div>;
}
