import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Printer} from 'lucide-react';
import {type Context,type Lang,type Row,date,name} from './shared';
import './production-print.css';

type PrintSnapshot={plan:Row;branchName:string;lang:Lang;timeZone:string};
let printOwner:string|null=null;
function printTimeZone(plan:Row,c:Context){
 for(const value of [plan.execution_context?.timezone,c.organization?.timezone,'UTC']){
  if(typeof value!=='string'||!value)continue;
  try{new Intl.DateTimeFormat('en',{timeZone:value}).format(new Date(0));return value}catch{/* Try the next explicit fallback. */}
 }
 return 'UTC';
}
const validSavedPlan=(plan:Row,branch:string)=>Boolean(
 typeof plan.id==='string'&&plan.id&&plan.basis==='manual_portions'&&
 typeof plan.forecast_id==='string'&&plan.forecast_id&&String(plan.branch_id)===branch&&
 typeof plan.target_date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(plan.target_date)&&
 Array.isArray(plan.portions)&&plan.portions.length&&
 plan.portions.every((row:Row)=>typeof row.meal_id==='string'&&row.meal_id&&Number.isSafeInteger(row.portions)&&row.portions>=0&&row.portions<=1e9)
);

/** Prints a frozen saved document; no draft, stock operation, order, or API request. */
export default function ProductionPrint({plan,context:c}:{plan:Row;context:Context}){
 const id=useId(),mounted=useRef(false),pending=useRef(false),closeSnapshot=useRef<()=>void>(()=>{}),[snapshot,setSnapshot]=useState<PrintSnapshot|null>(null),[failed,setFailed]=useState(false);
 const eligible=validSavedPlan(plan,c.branch),w=(kk:string,ru:string)=>c.lang==='kk'?kk:ru;
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{
  if(!snapshot)return;
  let finished=false,firstFrame=0,secondFrame=0;
  document.body.classList.add('production-print-active');
  const finish=()=>{
   if(finished)return;finished=true;pending.current=false;
   if(printOwner===id){printOwner=null;document.body.classList.remove('production-print-active')}
   if(mounted.current)setSnapshot(null);
  };
  closeSnapshot.current=finish;
  window.addEventListener('afterprint',finish);
  // Allow the portal and its table to commit before the browser takes the print snapshot.
  firstFrame=requestAnimationFrame(()=>{secondFrame=requestAnimationFrame(()=>{
   if(finished||!mounted.current)return;
   // Returning does not prove that every browser has finished taking its snapshot.
   // Keep the document until afterprint or an explicit user close, including cancel.
   try{window.print()}catch{if(mounted.current)setFailed(true);finish()}
  })});
  return()=>{cancelAnimationFrame(firstFrame);cancelAnimationFrame(secondFrame);window.removeEventListener('afterprint',finish);if(closeSnapshot.current===finish)closeSnapshot.current=()=>{};finish()};
 },[snapshot,id]);
 function print(){
  if(!eligible||pending.current||printOwner!==null)return;
  pending.current=true;printOwner=id;setFailed(false);
  try{
   // Copy only public JSON already shown to this user, before opening the dialog.
   const saved=JSON.parse(JSON.stringify(plan));
   setSnapshot({plan:saved,branchName:c.branchName||String(saved.branch_id),lang:c.lang,timeZone:printTimeZone(saved,c)});
  }catch{
   pending.current=false;if(printOwner===id)printOwner=null;setFailed(true);
  }
 }
 return <div className="production-print-action">
  <button type="button" className="button secondary" disabled={!eligible||!!snapshot} onClick={print}><Printer size={17}/>{w('Дайындау жоспарын басып шығару','Распечатать план приготовления')}</button>
  {snapshot&&<div className="production-print-prepared"><p role="status">{w('Баспа көшірмесі дайын. Басып шығару терезесі жабылғаннан кейін көшірмені жабуға болады.','Печатная копия подготовлена. После закрытия окна печати её можно закрыть.')}</p><button type="button" className="text-button" onClick={()=>closeSnapshot.current()}>{w('Баспа көшірмесін жабу','Закрыть печатную копию')}</button></div>}
  {failed&&<p className="alert warning" role="alert">{w('Басып шығару терезесін ашу мүмкін болмады. Қайта көріңіз.','Не удалось открыть окно печати. Попробуйте ещё раз.')}</p>}
  {snapshot&&createPortal(<CookingSheet snapshot={snapshot}/>,document.body)}
 </div>;
}

function CookingSheet({snapshot}:{snapshot:PrintSnapshot}){
 const {plan,branchName,lang,timeZone}=snapshot,w=(kk:string,ru:string)=>lang==='kk'?kk:ru;
 const unknown=w('Белгісіз','Неизвестно'),source=plan.data_origin||unknown,usage=plan.usage_mode||plan.execution_context?.usage_mode||unknown;
 const created=typeof plan.created_at==='string'&&Number.isFinite(Date.parse(plan.created_at))?new Date(plan.created_at).toLocaleString(lang==='kk'?'kk-KZ':'ru-RU',{timeZone})+' · '+timeZone:unknown+' · '+timeZone;
 const freshness=plan.input_freshness==='unchanged'?w('Бастапқы деректер өзгермеген.','Исходные данные не изменились.'):plan.input_freshness==='changed'?w('Бастапқы деректер өзгерген. Қолданар алдында жоспарды тексеріңіз.','Исходные данные изменились. Проверьте план перед использованием.'):w('Бастапқы деректердің өзектілігі белгісіз. Бұл баспа нұсқасы оларды қайта тексермейді.','Актуальность исходных данных неизвестна. Печатная копия не выполняет их повторную проверку.');
 return <article className="production-print-root" data-testid="production-print-sheet" aria-label={w('Дайындау жоспарының баспа нұсқасы','Печатный план приготовления')}>
  <header className="production-print-heading"><span>AsBoljam</span><p>{w('Сақталған дайындау жоспары','Сохранённый план приготовления')}</p><h1>{plan.name||unknown}</h1></header>
  <dl className="production-print-meta"><div><dt>{w('Бөлімше','Филиал')}</dt><dd>{branchName} · {plan.branch_id}</dd></div><div><dt>{w('Дайындау күні','Дата приготовления')}</dt><dd>{date(plan.target_date)}</dd></div><div><dt>{w('Дерек көзі / режим','Источник / режим')}</dt><dd>{source} / {usage}</dd></div><div><dt>{w('Сақталды','Сохранено')}</dt><dd>{created}</dd></div>{plan.actor_id&&<div><dt>{w('Сақтаған (ID)','Сохранил (ID)')}</dt><dd>{plan.actor_id}</dd></div>}</dl>
  <div className="production-print-notices">
   {source==='SYNTHETIC'&&<p><strong>SYNTHETIC.</strong> {w('Жасанды оқу деректері. Күндер бастапқы сценарийден алынған.','Синтетические учебные данные. Даты сохранены из исходного сценария.')}</p>}
   {usage==='TEST'&&<p><strong>TEST.</strong> {w('Сынақ режимі; нақты бизнестің нәтижесі емес.','Тестовый режим; не результат работы реального бизнеса.')}</p>}
   {source===unknown&&<p><strong>{w('Дерек көзі белгісіз.','Источник данных неизвестен.')}</strong></p>}
   <p>{freshness}</p>
  </div>
  <section className="production-print-reason"><h2>{w('Жоспардың себебі','Причина плана')}</h2><p>{plan.reason||unknown}</p></section>
  <table className="production-print-table"><thead><tr><th scope="col">{w('Тағам','Блюдо')}</th><th scope="col">{w('Дайындау, порция','Приготовить, порций')}</th></tr></thead><tbody>{plan.portions.map((row:Row)=><tr key={row.meal_id}><th scope="row">{name(row.meal_name||row.meal_id)}</th><td>{String(row.portions)}</td></tr>)}</tbody></table>
  <footer className="production-print-footer"><p><strong>{w('Жоспар — ниет, орындалу есебі емес.','План отражает намерение, а не факт выполнения.')}</strong> {w('Нақты дайындалған порциялар бөлек тіркеледі. Басып шығару қоймадан есептен шығармайды, сатып алуды бекітпейді және жеткізушіге тапсырыс жібермейді.','Фактически приготовленные порции регистрируются отдельно. Печать не списывает склад, не утверждает закупку и не отправляет заказ поставщику.')}</p><p>{w('Нұсқа ID','ID варианта')}: {plan.id}<br/>{w('Бастапқы болжам ID','ID исходного прогноза')}: {plan.forecast_id}</p></footer>
 </article>;
}
