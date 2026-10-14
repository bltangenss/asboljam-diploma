import {useEffect,useRef,useState,type ReactNode} from 'react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,name,useData} from './shared';
import {stockText} from './stockCopy';
import StockRecipes from './StockRecipes';
import {productionQuery,useProductionPlan,ProductionEvidence} from './ProductionPlanning';
import StockCountAnchors from './StockCountAnchors';
import './stock-ledger.css';
import './stock-tasks.css';

type Line={ingredient_id:string;lot_id:string;unit:string;expiry_date:string;quantity:string};
type Portion={meal_id:string;quantity:string};
type Preview={response:Row;body:Row;path:string;key:string};
const blankLine=():Line=>({ingredient_id:'',lot_id:'',unit:'',expiry_date:'',quantity:''});
const decimal=/^-?\d+(?:\.\d{1,9})?$/;
const day=/^\d{4}-\d{2}-\d{2}$/;
type StockTask='balance'|'receipt'|'consumption'|'reconciliation'|'history'|'recipes';
type StockProps=Context&{countedStock?:ReactNode};
const stockTasks:StockTask[]=['balance','receipt','consumption','reconciliation','history','recipes'];
const taskFromUrl=():StockTask=>{const value=new URLSearchParams(window.location.search).get('task');return stockTasks.includes(value as StockTask)?value as StockTask:'balance'};

export default function StockLedger(c:StockProps) {
 // Remount on account/branch changes. A late response is also fenced by CSRF and generation.
 return <StockWorkspace key={[c.user?.organization_id,c.user?.id,c.branch].join(':')} {...c}/>;
}
function StockWorkspace(c:StockProps) {
 const s=stockText(c.lang),t=c.t,scope=encodeURIComponent(c.branch);
 const canWrite=c.dataContext?.operations_enabled===true&&['admin','manager','warehouse'].includes(c.user?.role);
 const canAdjust=['admin','manager'].includes(c.user?.role);
 const initialDate=c.inventoryDate||c.dataContext?.inventory_date||c.dataContext?.target_date||'';
 const [openingDate,setOpeningDate]=useState(initialDate),[baselineDate,setBaselineDate]=useState(initialDate);
 const [position,setPosition]=useState<Row|null>(null),[catalog,setCatalog]=useState<Row>({ingredients:[],meals:[]});
 const [history,setHistory]=useState<Row|null>(null),[cursor,setCursor]=useState(''),[refresh,setRefresh]=useState(0);
 const [loading,setLoading]=useState(true),[loadError,setLoadError]=useState('');
 const [kind,setKind]=useState(taskFromUrl()==='consumption'?'recipe_usage':'receipt'),[businessDate,setBusinessDate]=useState(initialDate),[reference,setReference]=useState(''),[reason,setReason]=useState('');
 const [lines,setLines]=useState<Line[]>([blankLine()]),[portions,setPortions]=useState<Portion[]>([{meal_id:'',quantity:''}]);
 const [reverseId,setReverseId]=useState(''),[requirements,setRequirements]=useState<Row|null>(null);
 const [preview,setPreview]=useState<Preview|null>(null),[reviewed,setReviewed]=useState(false),[uncertain,setUncertain]=useState(false);
 const [action,setAction]=useState(''),[error,setError]=useState(''),[done,setDone]=useState(false),[rowErrors,setRowErrors]=useState<number[]>([]);
 const [countDate,setCountDate]=useState(initialDate),[reconciliation,setReconciliation]=useState<Row|null>(null),[countError,setCountError]=useState('');
 const [recipeLocked,setRecipeLocked]=useState(false),[anchorLocked,setAnchorLocked]=useState(false);
 const [task,setTask]=useState<StockTask>(taskFromUrl);
 const flowQuery=new URLSearchParams(window.location.search),forecastId=flowQuery.get('forecast')||'',productionId=flowQuery.get('production_plan_id')||'';
 const production=useProductionPlan(c,forecastId,productionId),productionSuffix=productionQuery(productionId),productionBlocked=!!productionId&&!production.ready;
 // A URL is only a request to recover context. Never use it as proof of branch/date/readiness.
 const forecast=useData(forecastId?`/forecasts/${encodeURIComponent(forecastId)}?branch_id=${scope}`:null,c.revision);
 const forecastMatches=Boolean(forecastId&&forecast.data?.id===forecastId&&String(forecast.data?.branch_id)===c.branch);
 const forecastTarget=forecastMatches?(forecast.data.result?.target_date||forecast.data.target_date||''):'';
 const flowReady=forecastMatches&&day.test(forecastTarget)&&!forecast.loading&&!forecast.error;
 const mounted=useRef(true),generation=useRef(0),pending=useRef(false),reading=useRef(0),postAttempted=useRef(false);
 const busy=Boolean(action),locked=busy||uncertain||recipeLocked||anchorLocked,stale=position?.ledger&&((position.effective_freshness??position.baseline_freshness)!=='unchanged'||position.context_freshness!=='unchanged');
 const ingredients:Row[]=catalog.ingredients||[],meals:Row[]=catalog.meals||[];
 const ingredientName=(id:string)=>name(ingredients.find(item=>item.ingredient_id===id)?.ingredient_name||id);
 const contextKey=JSON.stringify([c.user?.role,c.dataContext?.source,c.dataContext?.data_origin,c.dataContext?.usage_mode]);
 const previousContext=useRef(contextKey);
 const w=(kk:string,ru:string)=>c.lang==='kk'?kk:ru;
 const documentVisible=task==='receipt'||task==='consumption';
 const taskLabels:Record<StockTask,[string,string]>={balance:['Қалдықты тексеру','Проверить остатки'],receipt:['Кірісті енгізу','Записать приход'],consumption:['Шығыс пен есептен шығару','Расход и списание'],reconciliation:['Түгендеумен салыстыру','Сверка с пересчётом'],history:['Құжаттар тарихы','История документов'],recipes:['Күнге белсенді рецепттер','Рецепты с датой действия']};
 useEffect(()=>{selectTask(taskFromUrl())},[window.location.search]);
 useEffect(()=>{if(!canWrite&&documentVisible&&!locked)setTask('balance')},[canWrite,documentVisible,locked]);
 useEffect(()=>{if(task==='recipes'){const element=document.getElementById('stock-active-recipes');if(element instanceof HTMLDetailsElement)element.open=true}},[task]);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++generation.current;++reading.current}},[]);
 useEffect(()=>{
  if(previousContext.current===contextKey)return;
  previousContext.current=contextKey;++generation.current;pending.current=false;setAction('');setRequirements(null);setReconciliation(null);
  // Keep an uncertain command frozen for an exact idempotent retry; changed access still blocks POST.
  if(!postAttempted.current){setPreview(null);setReviewed(false)}else setUncertain(true);
  setRefresh(value=>value+1);
 },[contextKey]);
 useEffect(()=>{
  const read=++reading.current,csrf=api.csrf;let active=true;
  const current=()=>active&&mounted.current&&read===reading.current&&csrf===api.csrf;
  setLoading(true);setLoadError('');setPosition(null);setHistory(null);
  if(!day.test(openingDate)){setLoading(false);setPosition(null);return()=>{active=false}}
  Promise.all([
   api.request(`/stock/ledger?branch_id=${scope}${openingDate?'&opening_date='+openingDate:''}`),
   api.request(`/stock/catalog?branch_id=${scope}`),
   api.request(`/stock/movements?branch_id=${scope}&limit=20&cursor=${cursor||'0'}`),
  ]).then(([ledger,catalog,history])=>{if(current()){setPosition(ledger);setCatalog(catalog);setHistory(history)}})
   .catch(error=>{if(current())setLoadError(explain(error,'unavailable'))}).finally(()=>{if(current())setLoading(false)});
  return()=>{active=false};
 },[scope,openingDate,cursor,refresh,c.revision]);
 useEffect(()=>{if(!postAttempted.current){invalidate();setRequirements(null);setReconciliation(null)}},[c.revision]);
 useEffect(()=>{
  if(!uncertain)return;
  const prevent=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};
  window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent);
 },[uncertain]);

 function explain(value:unknown,fallback='failed') {
  if(value instanceof ApiError){
   if(value.status===403)return s('forbidden');
   const known=s(value.code);if(known!==value.code)return known;
   if(value.status===409)return s('conflict');
   if(value.status===0)return c.t('offline');
   return `${s(fallback)} (${value.code})`;
  }
  return s(fallback);
 }
 function invalidate(){++generation.current;pending.current=false;setAction('');setPreview(null);setReviewed(false);setError('');setDone(false);setRowErrors([]);postAttempted.current=false}
 function edit(change:()=>void){if(locked)return;invalidate();change()}
 function begin(){pending.current=true;const version=++generation.current,csrf=api.csrf;return()=>mounted.current&&version===generation.current&&csrf===api.csrf}
 function finish(current:()=>boolean){if(current()){pending.current=false;setAction('')}}
 function refreshData(){if(locked)return;invalidate();setReconciliation(null);setRequirements(null);setRefresh(value=>value+1)}
 function changeLine(index:number,patch:Partial<Line>){edit(()=>setLines(current=>current.map((line,i)=>i===index?{...line,...patch}:line)))}
 function portionsBody(){
  const result:Record<string,number>={};
  for(const item of portions){if(!item.meal_id||!/^[1-9]\d*$/.test(item.quantity)||Number(item.quantity)>1e9||item.meal_id in result)return null;result[item.meal_id]=Number(item.quantity)}
  return result;
 }
 async function calculateRecipe(){
  if(locked||!c.online)return;invalidate();const portionMap=portionsBody();
  if(!portionMap||!day.test(businessDate)){setError(s('recipeUnavailable'));return}
  const current=begin();setAction('requirements');
  try{const data=await api.post('/stock/recipe-requirements',{branch_id:c.branch,business_date:businessDate,portions:portionMap});if(current())setRequirements(data)}catch(error){if(current())setError(explain(error,'recipeUnavailable'))}finally{finish(current)}
 }
 function documentBody():Row|null {
  if(!day.test(businessDate)||!reference.trim()||reference.length>128||reason.trim().length<3){setError(s('required'));return null}
  const body:Row={branch_id:c.branch,expected_version:position?.version,kind,business_date:businessDate,source_reference:reference,reason:reason.trim()};
  if(kind==='reversal'){if(!reverseId){setError(s('required'));return null}return {...body,reverses_id:reverseId}}
  const invalid=lines.flatMap((line,index)=>!line.ingredient_id||!line.lot_id||!day.test(line.expiry_date)||!decimal.test(line.quantity)||!/[1-9]/.test(line.quantity)||(kind!=='adjustment'&&line.quantity.startsWith('-'))?[index]:[]);
  setRowErrors(invalid);if(invalid.length){setError(s('required'));return null}
  body.lines=lines;
  if(kind==='recipe_usage'){const portionMap=portionsBody();if(!portionMap){setError(s('recipeUnavailable'));return null}body.recipe_usage={portions:portionMap}}
  return body;
 }
 async function validate(open=false){
  if(!canWrite||locked||pending.current||!c.online||loading||loadError||stale)return;
  invalidate();
  if(open&&(!day.test(baselineDate)||reason.trim().length<3)){setError(s('required'));return}
  const body=open?{branch_id:c.branch,baseline_date:baselineDate,reason:reason.trim()}:documentBody();if(!body)return;
  const path=open?'/stock/open':'/stock/movements',current=begin();setAction('preview');
  try{const response=await api.post(path+'/preview',body);if(current())setPreview({response,body,path,key:crypto.randomUUID()})}
  catch(error){if(current()){setError(explain(error));if(error instanceof ApiError&&error.status===409)setRefresh(value=>value+1)}}finally{finish(current)}
 }
 async function post(){
  if(!preview||!canWrite||!reviewed||pending.current||recipeLocked||anchorLocked||!c.online)return;
  if(['adjustment','reversal'].includes(preview.body.kind)&&!canAdjust)return;
  const frozen=preview,current=begin();postAttempted.current=true;setAction('post');setError('');
  try{
   await api.post(frozen.path,{...frozen.body,expected_fingerprint:frozen.response.preview_fingerprint},{'Idempotency-Key':frozen.key});
   if(current()){setUncertain(false);setPreview(null);setReviewed(false);setDone(true);setReason('');setReference('');setReverseId('');setKind('receipt');setTask(frozen.path==='/stock/open'?'balance':'receipt');setLines([blankLine()]);setRequirements(null);setReconciliation(null);setCursor('');postAttempted.current=false;setRefresh(value=>value+1)}
  }catch(error){if(current()){
   if(!(error instanceof ApiError)||error.status===0||error.status>=500){setUncertain(true);setError(s('uncertain'))}
   else{setUncertain(false);setError(explain(error));setPreview(null);setReviewed(false);postAttempted.current=false;if(error.status===409)setRefresh(value=>value+1)}
  }}finally{finish(current)}
 }
 async function reconcile(){
  if(locked||!c.online||!day.test(countDate))return;
  const current=begin();setAction('reconcile');setCountError('');setReconciliation(null);
  try{const result=await api.request(`/stock/reconciliation?branch_id=${scope}&count_date=${countDate}`);if(current())setReconciliation(result)}catch(error){if(current())setCountError(explain(error))}finally{finish(current)}
 }
 function selectTask(next:StockTask){if(locked)return;const nextKind=next==='receipt'?'receipt':next==='consumption'?'recipe_usage':kind;if(nextKind!==kind){invalidate();setKind(nextKind);setReverseId('');setRequirements(null)}else if(preview)invalidate();setTask(next)}
 function reveal(id:string){const element=document.getElementById(id);if(element instanceof HTMLDetailsElement)element.open=true;element?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});element?.querySelector('summary')?.focus()}
 function reverse(row:Row){if(locked)return;edit(()=>{setTask('consumption');setKind('reversal');setReverseId(row.id||row.movement_id);setReference('');setReason('')});requestAnimationFrame(()=>reveal('stock-document'))}
 function lotTable(rows:Row[]|null|undefined,quantityKey='on_hand_qty'){
  return !rows?.length?<p className="stock-empty">{s('noRows')}</p>:<div className="stock-table" tabIndex={0} role="region" aria-label={s(quantityKey==='quantity_delta'?'delta':'balance')}><table><thead><tr>{[t('ingredient'),t('lot'),t('unit'),t('expiry'),s(quantityKey==='quantity_delta'?'delta':'balance')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map((row,index)=><tr key={[row.ingredient_id,row.lot_id,index].join(':')}><td>{ingredientName(row.ingredient_id)}</td><td>{row.lot_id}</td><td>{row.unit}</td><td>{date(row.expiry_date)}</td><td>{row[quantityKey]??s('unknown')}</td></tr>)}</tbody></table></div>;
 }
 const documentStart=[position?.ledger?.baseline_date,position?.latest?.through_business_date,position?.latest?.count_anchor?.count_date].filter(Boolean).sort().at(-1);
 const reversed=new Set((history?.items||[]).map((row:Row)=>row.reverses_id).filter(Boolean));
 const publicContext=position?.public_context||c.dataContext;
 const reconciliationFreshness=reconciliation?.effective_freshness??reconciliation?.baseline_freshness;
 const reconciliationStale=Boolean(reconciliation&&((reconciliationFreshness&&reconciliationFreshness!=='unchanged')||(reconciliation.context_freshness&&reconciliation.context_freshness!=='unchanged')));
 return <section className="stock-ledger" aria-label={s('title')}>
  <div className="stock-toolbar"><h2>{s('title')}</h2><button className="button secondary" disabled={locked} onClick={refreshData}>{s('refresh')}</button></div>
  <p className="stock-intro">{s('intro')}</p>
  <div className="stock-context"><strong>{publicContext?.data_origin??s('unknown')}</strong><span>{publicContext?.usage_mode??s('unknown')}</span><span>{t('branch')}: {c.branchName||c.branch}</span></div>
  {forecastId&&<section className="stock-planning-context" aria-label={w('Жоспарды жалғастыру','Продолжение планирования')}>
   <div><span className="stock-task-kicker">{w('02 · Қалдықты тексеру','02 · Проверка остатков')}</span><h3>{flowReady?w(`Сатып алу күні: ${date(forecastTarget)}`,`День закупки: ${date(forecastTarget)}`):w('Болжамды тексеру','Проверка прогноза')}</h3><p>{w('Саналған қорды, мерзімі өткен партияларды және журнал айырмашылықтарын тексеріңіз. Кесіндінің бар болуы оның толықтығын растамайды.','Проверьте посчитанный запас, сроки годности и расхождения журнала. Наличие среза не подтверждает его полноту.')}</p></div>
   {forecast.loading?<p role="status">{t('loading')}</p>:!flowReady?<p className="alert warning" role="status">{w('Бұл болжам таңдалған бөлімше үшін расталмады. Күн жоспарынан болжамды қайта таңдаңыз.','Этот прогноз не подтверждён для выбранного филиала. Выберите прогноз в плане дня.')}<button className="text-button" disabled={locked} onClick={()=>c.go('/forecasts')}>{w('Күн жоспарына','К плану дня')}</button></p>:<>
    {c.inventoryDate!==forecastTarget&&<p className="alert warning" role="status">{w(`Қазір ${date(c.inventoryDate)} күнінің кесіндісі ашық. Сатып алуға ${date(forecastTarget)} күнінің қалдығы қажет.`,`Открыт срез на ${date(c.inventoryDate)}. Для закупки нужен остаток на ${date(forecastTarget)}.`)}{c.dataContext?.inventory_dates?.includes(forecastTarget)?<button className="text-button" disabled={locked} onClick={()=>{invalidate();c.setInventoryDate(forecastTarget);setOpeningDate(forecastTarget);setCountDate(forecastTarget);setReconciliation(null);setTask('balance')}}>{w('Керек күннің қалдығын ашу','Открыть остаток на нужную дату')}</button>:<button className="text-button" disabled={locked} onClick={()=>c.go('/imports?kind=inventory_lots&return=inventory&return_branch='+encodeURIComponent(c.branch)+'&forecast='+encodeURIComponent(forecastId)+productionSuffix)}>{w('Саналған қалдықты қосу','Добавить посчитанный остаток')}</button>}</p>}
    {forecast.data?.input_freshness!=='unchanged'&&<p className="alert warning" role="status">{w('Болжамның өзектілігі расталмаған. Сатып алу алдында оны қайта есептеу қажет болуы мүмкін.','Актуальность прогноза не подтверждена. Перед закупкой может понадобиться пересчёт.')}</p>}
    {productionId&&(production.loading?<p role="status">{t('loading')}</p>:production.invalid?<p className="alert warning" role="alert">{w('Дайындау нұсқасы осы болжам мен бөлімше үшін расталмады. Күн жоспарына оралып, нұсқаны таңдаңыз.','Вариант приготовления не подтверждён для этого прогноза и филиала. Вернитесь в план дня и выберите вариант.')}</p>:production.data?<><ProductionEvidence plan={production.data} context={c} compact/>{!production.ready&&<p className="alert warning" role="alert">{w('Дайындау нұсқасының өзектілігі расталмаған. Сатып алуға дейін болжам мен нұсқаны жаңартыңыз.','Актуальность варианта приготовления не подтверждена. Обновите прогноз и вариант перед закупкой.')}</p>}</>:null)}
    <div className="stock-flow-actions"><button className="button secondary" disabled={locked} onClick={()=>c.go('/forecasts/'+encodeURIComponent(forecastId)+(productionId?'?production_plan_id='+encodeURIComponent(productionId):''))}>{w('Порциялар болжамына','К прогнозу порций')}</button>{['admin','manager'].includes(c.user?.role)&&<button className="button primary" disabled={locked||productionBlocked} onClick={()=>c.go('/procurement?forecast='+encodeURIComponent(forecastId)+productionSuffix)}>{w('Сатып алуды есептеуге','К расчёту закупки')}</button>}</div><p className="stock-help">{w('Қалдық, рецепт және ұсыныстардың толықтығын сатып алу есептеуі тексереді. Бұл қадам қорды өзгертпейді.','Полноту остатков, рецептур и предложений проверит расчёт закупки. Этот переход не меняет запас.')}</p>
   </>}
  </section>}
  <nav className="stock-workspace-tasks" aria-label={w('Қоймадағы әрекеттер','Задачи склада')}>
   {stockTasks.filter(value=>!['receipt','consumption'].includes(value)||canWrite).map(value=><button key={value} type="button" data-stock-task={value} aria-pressed={task===value} disabled={locked} onClick={()=>selectTask(value)}>{taskLabels[value][c.lang==='kk'?0:1]}</button>)}
  </nav>
  <div className="stock-task-description"><strong>{taskLabels[task][c.lang==='kk'?0:1]}</strong><p>{task==='balance'?w('Алдымен саналған қор, содан кейін өткізілген құжаттар бойынша есеп. Бұлар — бөлек дерек көздері.','Сначала посчитанный запас, затем расчёт по проведённым документам. Это разные источники.'):task==='receipt'?w('Тауарды алғаннан кейін ғана құжат енгізіңіз. Сатып алуды бекіту кіріс жасамайды.','Запишите документ после фактического получения товара. Утверждение закупки не создаёт приход.'):task==='consumption'?w('Дайындалған нақты порцияларды, есептен шығаруды немесе түзетуді енгізіңіз. Болжам қорды автоматты түрде азайтпайды.','Укажите фактически приготовленные порции, списание или корректировку. Прогноз не списывает склад автоматически.'):task==='reconciliation'?w('Журналды нақты саналған кесіндімен салыстырыңыз. Қажет болса, жаңа қалдықты бөлек растаңыз.','Сравните журнал с фактически посчитанным срезом. При необходимости отдельно подтвердите новую основу остатка.'):task==='history'?w('Өткізілген құжаттарды тексеріңіз. Қате құжатқа рұқсат болғанда кері жазба қосылады.','Проверьте проведённые документы. Для ошибочного документа при наличии права создаётся обратная запись.'):w('Нақты күннен бастап қолданылатын толық рецепттер. Өзгеріс бұрынғы құжаттарды қайта жазбайды.','Полные рецептуры, действующие с указанной даты. Изменение не переписывает прошлые документы.')}</p></div>
  <div hidden={task!=='balance'} className="stock-counted-task">{c.countedStock}</div>
  <div className="stock-fields" hidden={task!=='balance'}><label>{s('openingDate')}<input type="date" value={openingDate} disabled={locked} onChange={event=>{invalidate();setOpeningDate(event.target.value);setReconciliation(null)}}/></label></div>
  {!canWrite&&<p className="alert info">{s('readOnly')}</p>}
  {loading&&<p role="status">{s('loading')}</p>}
  {loadError&&<div className="alert danger" role="alert">{loadError}</div>}
  {error&&<div className="alert danger" role="alert">{error}</div>}
  {busy&&<div className="alert info" role="status">{s('busy')}</div>}
  {done&&<div className="alert success" role="status">{s('done')}</div>}
  {stale&&<div className="alert warning" role="alert">{s('baselineStale')}</div>}
  <div hidden={task!=='recipes'}><StockRecipes context={c} catalog={catalog} disabled={busy||uncertain||anchorLocked} revision={refresh} onLockChange={setRecipeLocked} onChanged={()=>{invalidate();setRequirements(null);setRefresh(value=>value+1)}}/></div>
  {!loadError&&position&&!position.ledger&&task!=='recipes'&&task!=='history'&&<section className="panel stock-body"><h3>{s('empty')}</h3><p className="stock-help">{s('baselineHint')}</p>{canWrite&&<form className="stock-form" onSubmit={event=>{event.preventDefault();void validate(true)}}><fieldset disabled={locked||loading}><div className="stock-fields"><label>{s('baseline')}<input type="date" value={baselineDate} onChange={event=>edit(()=>setBaselineDate(event.target.value))}/></label><label>{s('reason')}<input value={reason} minLength={3} maxLength={1000} onChange={event=>edit(()=>setReason(event.target.value))}/></label></div><button className="button primary" disabled={!c.online}>{s('previewOpen')}</button></fieldset></form>}</section>}
  {position?.ledger&&<>
   <section className="panel stock-body" id="stock-balance" hidden={task!=='balance'}><div className="stock-toolbar"><h3>{s('opening')}</h3><details className="stock-ledger-technical"><summary>{w('Есептеу деректері','Сведения расчёта')}</summary><span>{t('version')}: {position.version}</span></details></div><p className="stock-help">{s('openingHint')}</p><p className="stock-help">{s('openingDate')}: {date(position.opening?.date)} · {s(position.opening?.count_anchor?'anchorBasis':'baseline')}: {date(position.opening?.count_anchor?.count_date||position.ledger.baseline_date)}</p>{position.opening?.source_freshness==='changed'&&!stale&&<p className="alert warning" role="status">{s('historicalBasisChanged')}</p>}{lotTable(position.opening?.rows)}<details><summary>{s('latest')}</summary><p className="stock-help">{s('through')}: {date(position.latest?.through_business_date)}</p><p className="stock-help">{s(position.latest?.count_anchor?'anchorBasis':'baseline')}: {date(position.latest?.count_anchor?.count_date||position.ledger.baseline_date)}</p>{lotTable(position.latest?.rows)}</details></section>
   {canWrite&&<details className="panel stock-body stock-task" id="stock-document" open hidden={!documentVisible}><summary><h3>{s('document')}</h3><span>{c.lang==='kk'?'Алдымен тексеру, содан кейін өткізу':'Сначала проверка, затем проведение'}</span></summary><form className="stock-form" onSubmit={event=>{event.preventDefault();void validate()}}><fieldset disabled={locked||Boolean(stale)||loading||Boolean(loadError)}>
    <div className="stock-fields"><label>{s('kind')}<select aria-label={s('kind')} value={kind} onChange={event=>edit(()=>{setKind(event.target.value);setTask(event.target.value==='receipt'?'receipt':'consumption');setReverseId('');setRequirements(null)})}>{['receipt','waste','recipe_usage',...(canAdjust?['adjustment']:[])].map(value=><option key={value} value={value}>{s(value)}</option>)}{kind==='reversal'&&<option value="reversal">{s('reversal')}</option>}</select></label><label>{s('businessDate')}<input type="date" value={businessDate} min={documentStart} onChange={event=>edit(()=>{setBusinessDate(event.target.value);setRequirements(null)})}/></label><label>{s('sourceReference')}<input value={reference} maxLength={128} onChange={event=>edit(()=>setReference(event.target.value))}/></label><label>{s('reason')}<input value={reason} minLength={3} maxLength={1000} onChange={event=>edit(()=>setReason(event.target.value))}/></label></div>
    <p className="stock-help">{s('sourceHint')}</p>
    {kind==='adjustment'&&<p className="alert info">{s('adjustmentHint')}</p>}
    {kind==='reversal'?<><p className="alert info">{s('reverseHint')}</p><p className="stock-meta">{s('reversalOf')}: {reverseId}</p></>:<>
     {kind==='recipe_usage'&&<div><h3>{s('portions')}</h3><p className="stock-help">{s('recipeHint')}</p>{portions.map((portion,index)=><div className="stock-portion" key={index}><label>{t('meal')} {index+1}<select aria-label={`${t('meal')} ${index+1}`} value={portion.meal_id} onChange={event=>edit(()=>{setRequirements(null);setPortions(current=>current.map((row,i)=>i===index?{...row,meal_id:event.target.value}:row))})}><option value="">{s('chooseMeal')}</option>{meals.map(meal=><option key={meal.meal_id} value={meal.meal_id}>{name(meal.meal_name||meal.meal_id)}</option>)}</select></label><label>{s('portions')} {index+1}<input inputMode="numeric" value={portion.quantity} onChange={event=>edit(()=>{setRequirements(null);setPortions(current=>current.map((row,i)=>i===index?{...row,quantity:event.target.value}:row))})}/></label>{portions.length>1&&<button type="button" className="text-button" onClick={()=>edit(()=>{setRequirements(null);setPortions(current=>current.filter((_,i)=>i!==index))})}>{s('removeLine')} {index+1}</button>}</div>)}<div className="stock-actions"><button type="button" className="button secondary" onClick={()=>edit(()=>{setRequirements(null);setPortions(current=>[...current,{meal_id:'',quantity:''}])})}>{s('addMeal')}</button><button type="button" className="button secondary" disabled={!c.online} onClick={()=>void calculateRecipe()}>{s('calculateRecipe')}</button></div>{requirements&&<div><h3>{s('requirements')}</h3><div className="stock-table"><table><thead><tr><th>{t('ingredient')}</th><th>{t('unit')}</th><th>{s('quantity')}</th></tr></thead><tbody>{(requirements.requirements||[]).map((row:Row)=><tr key={row.ingredient_id}><td>{ingredientName(row.ingredient_id)}</td><td>{row.unit}</td><td>{row.gross_required}</td></tr>)}</tbody></table></div></div>}</div>}
     <h3>{s('lines')}</h3><p className="stock-help">{s('decimalHint')}</p>{lines.map((line,index)=><fieldset key={index} className="stock-line"><legend>{s('row')} {index+1}</legend><div className="stock-fields"><label>{t('ingredient')} {index+1}<select aria-label={`${t('ingredient')} ${index+1}`} value={line.ingredient_id} onChange={event=>changeLine(index,{ingredient_id:event.target.value,unit:ingredients.find(item=>item.ingredient_id===event.target.value)?.unit||''})}><option value="">{s('chooseIngredient')}</option>{ingredients.map(ingredient=><option key={ingredient.ingredient_id} value={ingredient.ingredient_id}>{name(ingredient.ingredient_name||ingredient.ingredient_id)}</option>)}</select></label><label>{t('lot')} {index+1}<input value={line.lot_id} maxLength={64} onChange={event=>changeLine(index,{lot_id:event.target.value})}/></label><label>{t('unit')} {index+1}<input value={line.unit} readOnly/></label><label>{t('expiry')} {index+1}<input type="date" value={line.expiry_date} onChange={event=>changeLine(index,{expiry_date:event.target.value})}/></label><label>{s('quantity')} {index+1}<input inputMode="decimal" value={line.quantity} maxLength={32} aria-invalid={rowErrors.includes(index)} onChange={event=>changeLine(index,{quantity:event.target.value})}/></label></div>{rowErrors.includes(index)&&<p className="stock-error" role="alert">{s('row')} {index+1}: {s('badLine')}</p>}{lines.length>1&&<button type="button" className="text-button" onClick={()=>edit(()=>setLines(current=>current.filter((_,i)=>i!==index)))}>{s('removeLine')} {index+1}</button>}</fieldset>)}<button type="button" className="button secondary" disabled={lines.length>=500} onClick={()=>edit(()=>setLines(current=>[...current,blankLine()]))}>{s('addLine')}</button>
    </>}
    <p className="stock-help">{s('noSupplier')}</p><div className="stock-actions"><button className="button primary" disabled={!c.online}>{s('preview')}</button></div>
   </fieldset></form></details>}
  </>}
  {preview&&<section className="panel stock-body stock-preview" aria-label={s('previewTitle')}><h3>{s('previewTitle')}</h3><p className="stock-help">{s('previewHint')}</p><div className="stock-meta"><span>{s(preview.response.operation==='open'?'baseline':'businessDate')}: {date(preview.body.baseline_date||preview.body.business_date)}</span><span>{s('reason')}: {preview.body.reason}</span>{preview.body.source_reference&&<span>{s('sourceReference')}: {preview.body.source_reference}</span>}</div>{preview.response.operation==='open'?lotTable(preview.response.baseline_rows):<><h3>{s('delta')}</h3>{lotTable(preview.response.entries,'quantity_delta')}<details><summary>{s('before')}</summary>{lotTable(preview.response.balances_before)}</details><h3>{s('after')}</h3>{lotTable(preview.response.balances_after)}</>}{preview.response.recipe_evidence&&<details><summary>{s('evidence')}</summary><div className="stock-table"><table><thead><tr>{[t('meal'),t('version'),t('ingredient'),t('net'),t('yield')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{(preview.response.recipe_evidence.rows||[]).map((row:Row,index:number)=><tr key={index}><td>{row.meal_id}</td><td>{row.recipe_version}</td><td>{ingredientName(row.ingredient_id)}</td><td>{row.net_qty_per_portion}</td><td>{row.yield_factor}</td></tr>)}</tbody></table></div></details>}<label className="checkbox-label"><input type="checkbox" checked={reviewed} disabled={locked} onChange={event=>setReviewed(event.target.checked)}/>{s('reviewed')}</label><div className="stock-actions"><button className="button primary" disabled={!reviewed||busy||recipeLocked||anchorLocked||!c.online||!canWrite} onClick={()=>void post()}>{s(uncertain?'retryPost':preview.response.operation==='open'?'open':'post')}</button>{!uncertain&&<button className="button secondary" disabled={locked} onClick={invalidate}>{s('cancelPreview')}</button>}</div></section>}
  {position?.ledger&&<>
   <details className="panel stock-body stock-task" id="stock-history" open hidden={task!=='history'}><summary><h3>{s('history')}</h3><span>{c.lang==='kk'?'Бұрынғы жазбалар өзгертілмейді':'История не редактируется'}</span></summary>{history?.items?.length?<div className="stock-table" tabIndex={0} role="region" aria-label={s('history')}><table><thead><tr>{[s('sequence'),s('businessDate'),s('kind'),s('sourceReference'),s('reason'),s('lines')].map(label=><th key={label}>{label}</th>)}{canAdjust&&<th>{s('reverse')}</th>}</tr></thead><tbody>{history.items.map((row:Row)=><tr key={row.id||row.movement_id}><td>{row.sequence}</td><td>{date(row.business_date)}</td><td>{s(row.kind)}{row.reverses_id&&<small>{' · '+row.reverses_id}</small>}</td><td>{row.source_reference}</td><td>{row.reason}</td><td>{(row.entries||[]).map((line:Row,index:number)=><p key={index}>{ingredientName(line.ingredient_id)} · {line.lot_id}: {line.quantity_delta} {line.unit}</p>)}</td>{canAdjust&&<td>{row.before_count_anchor||position.latest?.count_anchor&&row.sequence<=position.latest.count_anchor.through_movement_sequence?<span className="stock-help">{s('STOCK_REVERSAL_BEFORE_ANCHOR')}</span>:row.kind!=='reversal'&&!row.reversed_by_id&&!reversed.has(row.id||row.movement_id)&&<button className="text-button" disabled={locked||Boolean(stale)} onClick={()=>reverse(row)}>{s('reverse')}</button>}</td>}</tr>)}</tbody></table></div>:<p className="stock-empty">{s('historyEmpty')}</p>}<div className="stock-actions"><button className="button secondary" disabled={!cursor||locked} onClick={()=>setCursor('')}>{s('previous')}</button><button className="button secondary" disabled={!history?.next_cursor||locked} onClick={()=>setCursor(history?.next_cursor||'')}>{s('next')}</button></div></details>
   <details className="panel stock-body stock-task" id="stock-reconciliation" open hidden={task!=='reconciliation'}><summary><h3>{s('reconciliation')}</h3><span>{c.lang==='kk'?'Есептелген және саналған қалдық':'Расчётный и посчитанный остаток'}</span></summary><p className="stock-help">{s('reconciliationHint')}</p><div className="stock-fields"><label>{s('countDate')}<input type="date" value={countDate} min={position.ledger.baseline_date} disabled={locked} onChange={event=>{setCountDate(event.target.value);setReconciliation(null);setCountError('')}}/></label></div><button className="button secondary" disabled={locked||!c.online||!countDate} onClick={()=>void reconcile()}>{s('reconcile')}</button>{countError&&<p className="stock-error" role="alert">{countError}</p>}{reconciliation&&<><p className={`alert ${reconciliation.status==='matched'&&!reconciliationStale?'success':'warning'}`} role="status">{reconciliationStale?s('baselineStale'):s(reconciliation.status)} · {date(reconciliation.target_date)}</p><div className="stock-table" tabIndex={0} role="region" aria-label={s('reconciliation')}><table><thead><tr>{[t('ingredient'),t('lot'),s('calculated'),s('actualCount'),s('difference'),t('status')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{(reconciliation.lines||[]).map((row:Row,index:number)=><tr key={index}><td>{ingredientName(row.ingredient_id)}</td><td>{row.lot_id}</td><td>{row.ledger?`${row.ledger.on_hand_qty} ${row.ledger.unit}`:s('unknown')}</td><td>{row.counted?`${row.counted.on_hand_qty} ${row.counted.unit}`:s('unknown')}</td><td>{row.difference??'—'}</td><td>{s(row.status)}</td></tr>)}</tbody></table></div></>}</details>
  </>}
  <div hidden={task!=='reconciliation'}><StockCountAnchors context={c} position={position} catalog={catalog} disabled={busy||uncertain||recipeLocked} revision={`${refresh}:${openingDate}`} onLockChange={setAnchorLocked} onChanged={()=>{invalidate();setRequirements(null);setReconciliation(null);setRefresh(value=>value+1)}}/></div>
 </section>;
}
