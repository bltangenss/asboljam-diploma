import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {ArrowRight,Save} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,Button,ErrorBox,Table,Badge,date,fmt,items,name} from './shared';
import './production-planning.css';
import ProductionPrint from './ProductionPrint';
import WorkingPlan,{useWorkingPlan} from './WorkingPlan';

export const productionQuery=(id:string)=>id?'&production_plan_id='+encodeURIComponent(id):'';
export const productionScope=(c:Context,forecastId:string)=>JSON.stringify([c.user?.organization_id,c.user?.id,c.user?.role,c.branch,forecastId,c.dataContext?.source,c.dataContext?.data_origin,c.dataContext?.usage_mode]);

// Never expose a previous account, branch, forecast or URL selection while a new read starts.
function useProductionRead(c:Context,forecastId:string,path:string|null){
 const scope=productionScope(c,forecastId)+'\0'+path+'\0'+c.revision;
 const[state,setState]=useState<{scope:string;data:Row|null;error:any;loading:boolean}>({scope:'',data:null,error:null,loading:!!path});
 useEffect(()=>{let active=true;const controller=new AbortController();setState({scope,data:null,error:null,loading:!!path});
  if(path)void api.request(path,{signal:controller.signal}).then(data=>{if(active)setState({scope,data,error:null,loading:false})}).catch(error=>{if(active)setState({scope,data:null,error,loading:false})});
  return()=>{active=false;controller.abort()};
 },[scope,path]);
 return state.scope===scope?state:{scope,data:null,error:null,loading:!!path};
}
export function useProductionPlan(c:Context,forecastId:string,id:string){
 const state=useProductionRead(c,forecastId,id?'/production-plans/'+encodeURIComponent(id):null);
 const valid=!!id&&state.data?.id===id&&String(state.data?.branch_id)===c.branch&&String(state.data?.forecast_id)===forecastId;
 return {...state,data:valid?state.data:null,invalid:!!id&&!state.loading&&(!valid||!!state.error),ready:valid&&state.data?.input_freshness==='unchanged'};
}
function useProductionList(c:Context,forecastId:string){
 return useProductionRead(c,forecastId,forecastId?'/production-plans?branch_id='+encodeURIComponent(c.branch)+'&forecast_id='+encodeURIComponent(forecastId)+'&limit=200':null);
}
const mealTitle=(row:Row,meals:Row[])=>name(row.meal_name||meals.find(meal=>String(meal.meal_id)===String(row.meal_id))?.meal_name||row.meal_id);
const integer=(value:string)=>/^\d+$/.test(value)&&Number.isSafeInteger(Number(value))&&Number(value)<=1e9;

export function ProductionEvidence({plan,context:c,meals=[],compact=false}:{plan:Row;context:Context;meals?:Row[];compact?:boolean}){
 const w=(kk:string,ru:string)=>c.lang==='kk'?kk:ru;
 return <section data-testid="production-saved" className="production-evidence" aria-label={w('Дайындау жоспарының негізі','Основание плана приготовления')}>
  <div className="production-evidence-heading"><div><span className="planning-eyebrow">{w('Адам таңдаған порциялар','Порции выбраны человеком')}</span><h3>{plan.name||w('Сақталған дайындау жоспары','Сохранённый план приготовления')}</h3></div><Badge>{plan.data_origin??'—'}</Badge></div>
  <p className="production-reason"><strong>{w('Себеп','Причина')}: </strong>{plan.reason||'—'}</p>
  <p className="muted">{date(plan.target_date)} · {w('Сақталған уақыт','Сохранено')}: {plan.created_at?new Date(plan.created_at).toLocaleString(c.lang==='kk'?'kk-KZ':'ru-RU'):'—'} · {plan.usage_mode??'—'}</p>
  {!compact&&<Table t={c.t} rows={plan.portions||[]} columns={[{key:'meal_id',label:c.t('meal'),render:row=>mealTitle(row,meals)},{key:'forecast_point',label:w('Болжам · порция','Прогноз · порции'),numeric:true,render:row=>fmt(row.forecast_point,1)},{key:'portions',label:w('Дайындау · порция','Приготовить · порции'),numeric:true,render:row=>fmt(row.portions)}]}/>}
  <p className="production-help">{w('Бұл сақталған нұсқа қоймадан шығыс жасамайды және сатып алуды бекітпейді.','Этот сохранённый вариант не списывает склад и не утверждает закупку.')}</p>
  <ProductionPrint plan={plan} context={c}/>
 </section>;
}

export function ProductionBasisSelector({context:c,forecastId,selectedId,onSelect}:{context:Context;forecastId:string;selectedId:string;onSelect:(id:string)=>void}){
 const list=useProductionList(c,forecastId),selected=useProductionPlan(c,forecastId,selectedId),w=(kk:string,ru:string)=>c.lang==='kk'?kk:ru;
 const variants=items(list.data).filter(row=>String(row.branch_id)===c.branch&&String(row.forecast_id)===forecastId);
 if(selected.data&&!variants.some(row=>row.id===selectedId))variants.unshift(selected.data);
 return <div className="production-basis-selector"><label>{w('Қажеттілік негізі','Основание потребности')}<select aria-label={w('Қажеттілік негізі','Основание потребности')} value={selectedId} onChange={event=>onSelect(event.target.value)}><option value="">{w('Болжам бойынша','По прогнозу')}</option>{selectedId&&!variants.some(row=>row.id===selectedId)&&<option value={selectedId}>{w('Сілтемедегі нұсқаны тексеру…','Проверка варианта по ссылке…')}</option>}{variants.map(row=><option key={row.id} value={row.id}>{row.name} · {date(row.target_date)}</option>)}</select></label>
  {list.error&&<p className="alert warning">{w('Сақталған дайындау нұсқалары жүктелмеді.','Сохранённые варианты приготовления не загрузились.')} <button className="text-button" onClick={c.refresh}>{c.t('retry')}</button></p>}
  {selectedId&&(selected.loading?<p role="status">{c.t('loading')}</p>:selected.invalid?<p className="alert warning" role="alert">{w('Дайындау нұсқасы осы болжам мен бөлімше үшін расталмады. Қолдағы нұсқаны таңдаңыз немесе болжам бойынша есептеуді нақты таңдаңыз.','Вариант приготовления не подтверждён для этого прогноза и филиала. Выберите доступный вариант либо явно выберите расчёт по прогнозу.')} <button className="text-button" onClick={c.refresh}>{c.t('retry')}</button></p>:selected.data?<><ProductionEvidence plan={selected.data} context={c}/>{!selected.ready&&<p className="alert warning" role="alert">{w('Осы нұсқаның бастапқы деректері өзгерген немесе тексерілмеген. Болжамды жаңартып, жаңа дайындау нұсқасын сақтаңыз.','Исходные данные этого варианта изменились или не проверены. Обновите прогноз и сохраните новый вариант приготовления.')}</p>}<p className="production-help">{w('Сатып алу тек сақталған бүтін порциялардан есептеледі. p50/p90 сценарийлері қолданылмайды.','Закупка рассчитывается по сохранённым целым порциям. Сценарии p50/p90 не применяются.')}</p></>:null)}
 </div>;
}

export default function ProductionPlanning(props:{context:Context;forecast:Row;forecastId:string;meals:Row[];selectedId:string;onSelect:(id:string)=>void;onLocked?:(locked:boolean)=>void}){
 return <ProductionWorkspace key={productionScope(props.context,props.forecastId)} {...props}/>;
}
function ProductionWorkspace({context:c,forecast,forecastId,meals,selectedId,onSelect,onLocked}:{context:Context;forecast:Row;forecastId:string;meals:Row[];selectedId:string;onSelect:(id:string)=>void;onLocked?:(locked:boolean)=>void}){
 const w=(kk:string,ru:string)=>c.lang==='kk'?kk:ru,result=forecast.result||forecast,predictions:Row[]=result.predictions||[];
 const canWrite=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user?.role),sourceReady=forecast.input_freshness==='unchanged';
 const selected=useProductionPlan(c,forecastId,selectedId),list=useProductionList(c,forecastId);
 const working=useWorkingPlan(c,selected.data,String(result.target_date||''));
 const[draft,setDraft]=useState(false),[values,setValues]=useState<Record<string,string>>({}),[title,setTitle]=useState(''),[reason,setReason]=useState(''),[busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState<any>(null);
 const command=useRef<{key:string;body:Row}|null>(null),mounted=useRef(true),pending=useRef(false),scope=productionScope(c,forecastId),currentScope=useRef(scope);
 currentScope.current=scope;
 const locked=busy||uncertain||working.phase!=='clean',editing=!selectedId||draft;
 const dirty=editing&&(draft||Object.values(values).some(value=>value!=='')||title!==''||reason!=='');
 const protection=useRef({dirty,uncertain});
 useLayoutEffect(()=>{protection.current={dirty,uncertain}},[dirty,uncertain]);
 function discardDraft(){
  if(pending.current||protection.current.uncertain||!working.discard())return false;
  protection.current.dirty=false;command.current=null;setDraft(false);setValues({});setTitle('');setReason('');setError(null);return true;
 }
 useLayoutEffect(()=>c.registerNavigationBlocker?.({
  read:()=>pending.current||working.read()==='pending'?'pending':protection.current.uncertain||working.read()==='uncertain'?'uncertain':protection.current.dirty||working.read()==='dirty'?'dirty':'clean',
  discard:discardDraft,
 }),[c.registerNavigationBlocker]);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{onLocked?.(locked||dirty);return()=>onLocked?.(false)},[locked,dirty,onLocked]);
 useEffect(()=>{if(!locked){setDraft(false);setValues({});setTitle('');setReason('');setError(null);command.current=null}},[selectedId]);
 const complete=predictions.length>0&&predictions.every(row=>integer(values[String(row.meal_id)]??''));
 const valid=complete&&title.trim().length>=1&&title.trim().length<=120&&reason.trim().length>=3&&reason.trim().length<=1000;
 const canSuggest=predictions.length>0&&predictions.every(row=>row.point_forecast!==null&&row.point_forecast!==undefined&&Number.isFinite(Number(row.point_forecast))&&Number(row.point_forecast)>=0&&Math.ceil(Number(row.point_forecast))<=1e9);
 const variants=items(list.data).filter(row=>String(row.branch_id)===c.branch&&String(row.forecast_id)===forecastId);
 if(selected.data&&!variants.some(row=>row.id===selectedId))variants.unshift(selected.data);
 function edit(action:()=>void){if(pending.current||protection.current.uncertain||working.read()!=='clean')return;protection.current.dirty=true;command.current=null;setError(null);action()}
 async function save(){
  if(pending.current||working.read()!=='clean'||!canWrite||!c.online||(!command.current&&(!valid||!sourceReady)))return;
  if(!command.current)command.current={key:crypto.randomUUID(),body:{branch_id:c.branch,forecast_id:forecastId,name:title.trim(),reason:reason.trim(),portions:predictions.map(row=>({meal_id:String(row.meal_id),portions:Number(values[String(row.meal_id)])}))}};
  const attempt=command.current,csrf=api.csrf,requestScope=scope;pending.current=true;setBusy(true);setError(null);
  const current=()=>mounted.current&&requestScope===currentScope.current&&csrf===api.csrf;
  try{const saved=await api.post('/production-plans',attempt.body,{'Idempotency-Key':attempt.key});if(!current())return;
   if(!saved?.id||String(saved.branch_id)!==c.branch||String(saved.forecast_id)!==forecastId)throw new Error('Invalid production plan receipt');
   command.current=null;pending.current=false;protection.current={dirty:false,uncertain:false};setUncertain(false);setDraft(false);setValues({});setTitle('');setReason('');c.refresh();onSelect(String(saved.id));
  }catch(error){if(current()){
   const known=error instanceof ApiError&&c.t('error_'+error.code)!=='error_'+error.code;
   setError(known?error:{message:w('Сақтау нәтижесі расталмады. Деректерді және сервермен байланысты тексеріңіз.','Результат сохранения не подтверждён. Проверьте данные и соединение с сервером.')});
   const unknown=!(error instanceof ApiError)||error.status===0||error.status>=500||error.code==='PRODUCTION_CONCURRENT_RETRY';protection.current.uncertain=unknown;setUncertain(unknown);if(!unknown)command.current=null;
  }}
  finally{if(current()){pending.current=false;setBusy(false)}}
 }
 const displayRows=predictions.map(row=>({...row,saved_portions:selected.data?.portions?.find((part:Row)=>String(part.meal_id)===String(row.meal_id))?.portions}));
 return <section data-testid="production-planning" className="panel production-planning" aria-label={w('Дайындау жоспары','План приготовления')}>
  <div className="panel-heading"><div><span className="planning-eyebrow">{w('Дайындауды жоспарлау','Планирование приготовления')}</span><h2>{w('Әр тағамға қанша порция','Сколько порций каждого блюда')}</h2><p>{w('Болжамды салыстырыңыз және қанша дайындауды өзіңіз таңдаңыз. Нөлді де нақты көрсетуге болады.','Сравните прогноз и выберите, сколько приготовить. Ноль тоже нужно указать явно.')}</p></div><button className="text-button" disabled={locked||dirty} onClick={()=>c.go('/recipes')}>{w('Рецепттерді қарау','Посмотреть рецепты')}<ArrowRight size={14}/></button></div>
  <div className="production-variant"><label>{w('Сақталған нұсқа','Сохранённый вариант')}<select aria-label={w('Сақталған нұсқа','Сохранённый вариант')} value={selectedId} disabled={locked||dirty} onChange={event=>onSelect(event.target.value)}><option value="">{w('Жаңа нұсқа / тек болжам','Новый вариант / только прогноз')}</option>{selectedId&&!variants.some(row=>row.id===selectedId)&&<option value={selectedId}>{w('Нұсқаны тексеру…','Проверка варианта…')}</option>}{variants.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>{list.error&&<p className="alert warning">{w('Нұсқалар тарихын жүктеу мүмкін болмады.','Не удалось загрузить историю вариантов.')} <button className="text-button" disabled={locked||dirty} onClick={c.refresh}>{c.t('retry')}</button></p>}</div>
  {selectedId&&(selected.loading?<p role="status">{c.t('loading')}</p>:selected.invalid?<p className="alert warning" role="alert">{w('Бұл нұсқа осы болжам мен бөлімше үшін расталмады.','Этот вариант не подтверждён для данного прогноза и филиала.')} <button className="text-button" disabled={locked} onClick={c.refresh}>{c.t('retry')}</button></p>:selected.data?<ProductionEvidence plan={selected.data} context={c} compact/>:null)}
  {selectedId&&selected.data&&!selected.ready&&<p className="alert warning" role="alert">{w('Нұсқаның өзектілігі расталмаған. Жаңа болжам мен дайындау нұсқасын жасаңыз.','Актуальность варианта не подтверждена. Создайте новый прогноз и вариант приготовления.')}</p>}
  <Table t={c.t} rows={displayRows} columns={[{key:'meal_id',label:c.t('meal'),render:row=>mealTitle(row,meals)},{key:'point_forecast',label:w('Нүктелік болжам · порция','Точечный прогноз · порции'),numeric:true,render:row=>fmt(row.point_forecast,1)},{key:'portions',label:w('Дайындау · порция','Приготовить · порции'),numeric:true,render:row=>canWrite&&editing?<input className="production-portions" type="number" min="0" max="1000000000" step="1" inputMode="numeric" aria-label={w('Дайындау','Приготовить')+' · '+mealTitle(row,meals)} disabled={locked||!sourceReady} value={values[String(row.meal_id)]??''} onChange={event=>edit(()=>setValues(previous=>({...previous,[String(row.meal_id)]:event.target.value})))} placeholder="—"/>:selected.data?fmt(row.saved_portions):'—'},...(predictions.some(row=>row.p10!=null)?['p10','p50','p90'].map(key=>({key,label:key,numeric:true,render:(row:Row)=>fmt(row[key],1)})):[])]}/>
  {canWrite&&editing?<div data-testid="production-editor" className="production-editor"><div className="production-draft-actions"><Button secondary disabled={locked||!sourceReady||!canSuggest} onClick={()=>edit(()=>setValues(Object.fromEntries(predictions.map(row=>[String(row.meal_id),String(Math.ceil(Number(row.point_forecast)))]))))}>{w('Болжамды жоғарыға дөңгелектеп толтыру','Заполнить прогнозом с округлением вверх')}</Button>{dirty&&<button className="text-button" disabled={locked} onClick={discardDraft}>{w('Сақталмаған өзгерістерді болдырмау','Отменить несохранённые изменения')}</button>}</div><p className="production-help">{w('Толтыру батырмасы әр болжамды келесі бүтін санға дейін арттырады. Сақтауға дейін порцияларды тексеріп өзгертіңіз.','Кнопка заполнения округляет каждый прогноз вверх до целого. Проверьте и измените порции перед сохранением.')}</p>
   {dirty&&!locked&&<p className="alert warning" role="status">{w('Қалдыққа не сатып алуға өту алдында жаңа нұсқаны сақтаңыз немесе сақталмаған өзгерістерді болдырмаңыз.','Перед переходом к остаткам или закупке сохраните новый вариант либо отмените несохранённые изменения.')}</p>}
   <div className="production-form"><label>{w('Нұсқа атауы','Название варианта')}<input maxLength={120} disabled={locked||!sourceReady} value={title} onChange={event=>edit(()=>setTitle(event.target.value))}/></label><label>{w('Неліктен осы порциялар таңдалды','Почему выбраны эти порции')}<textarea minLength={3} maxLength={1000} rows={3} disabled={locked||!sourceReady} value={reason} onChange={event=>edit(()=>setReason(event.target.value))}/></label></div>
   {!sourceReady&&<p className="alert warning">{w('Бастапқы деректердің өзектілігі расталмаған. Алдымен болжамды қайта есептеңіз.','Актуальность исходных данных не подтверждена. Сначала пересчитайте прогноз.')}</p>}
   {!complete&&<p className="production-help">{w('Әр тағамға 0-ден 1 000 000 000-ға дейін бүтін сан енгізіңіз. Бос жол нөл емес.','Введите целое число от 0 до 1 000 000 000 для каждого блюда. Пустое поле не равно нулю.')}</p>}
   {uncertain&&<p className="alert warning" role="alert">{w('Сақтау жауабы алынбады. Өрістер уақытша жабық: сол сұрауды қайталап, нәтижені тексеріңіз.','Ответ о сохранении не получен. Поля временно заблокированы: повторите тот же запрос, чтобы проверить результат.')}</p>}
   {error&&<ErrorBox error={error} t={c.t}/>}
   <Button disabled={busy||!c.online||(!uncertain&&(!valid||!sourceReady))} onClick={save}><Save size={17}/>{uncertain?w('Сол сақтауды қайта тексеру','Повторить и проверить сохранение'):w('Жаңа нұсқаны сақтау','Сохранить новый вариант')}</Button>
  </div>:canWrite&&selected.data?<div className="production-draft-actions"><Button secondary disabled={locked||!sourceReady} onClick={()=>edit(()=>{setValues(Object.fromEntries(selected.data!.portions.map((row:Row)=>[String(row.meal_id),String(row.portions)])));setTitle('');setReason('');setDraft(true)})}>{w('Негізге алып жаңа нұсқа жасау','Изменить и сохранить новым вариантом')}</Button></div>:null}
  <WorkingPlan context={c} plan={selected.data} controller={working} disabled={busy||uncertain||dirty}/>
  <p className="production-help">{w('Сақтау жаңа, өзгермейтін нұсқа жасайды. Сатып алуға тек сақталған нұсқа беріледі. Нақты дайындау мен қойма шығысы бөлек тіркеледі.','Сохранение создаёт новый неизменяемый вариант. В закупку передаётся только сохранённый вариант. Фактическое приготовление и расход склада регистрируются отдельно.')}</p>
 </section>;
}
