import {useEffect,useRef,useState} from 'react';
import {Check,ClipboardCheck} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,fmt} from './shared';
import type {NavigationPhase} from './navigationGuard';
import {useWorkdayData} from './workdayData';
import './forecast-review.css';

const reasons:Record<string,[string,string]>={
 confirmed_order:['Расталған тапсырыс','Подтверждённый заказ'],
 expected_attendance:['Күтілетін келушілер саны','Ожидаемая посещаемость'],
 ingredient_shortage:['Шикізаттың жетіспеуі','Нехватка сырья'],
 kitchen_capacity:['Асүй мүмкіндігінің шегі','Ограничение кухни'],
 manager_experience:['Басқарушы тәжірибесі','Опыт управляющего'],
 other:['Басқа себеп','Другое'],
};

export function useWorkingPlan(c:Context,plan:Row|null,targetDate:string){
 const scope=JSON.stringify([c.user?.organization_id,c.user?.id,c.user?.role,c.branch,targetDate]);
 const [revision,reload]=useState(0),[reasonCode,setReasonCode]=useState(''),[reason,setReason]=useState('');
 const [phase,setPhase]=useState<NavigationPhase>('clean'),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const live=useRef({phase:'clean' as NavigationPhase,scope}),mounted=useRef(true);
 live.current.scope=scope;
 const command=useRef<{key:string;body:Row}|null>(null);
 const state=useWorkdayData(c,c.branch&&targetDate?'/working-plan?branch_id='+encodeURIComponent(c.branch)+'&target_date='+encodeURIComponent(targetDate):null,revision);
 const valid=!!state.data&&Number.isSafeInteger(state.data.version)&&state.data.version>=0&&Array.isArray(state.data.history)&&(state.data.selection===null||state.data.selection?.target_date===targetDate);
 const data=valid?state.data:null;
 const canWrite=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user?.role);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 const changePhase=(value:NavigationPhase)=>{live.current.phase=value;setPhase(value)};
 const hard=()=>live.current.phase==='pending'||live.current.phase==='uncertain';
 function change(field:'code'|'reason',value:string){
  if(hard())return;command.current=null;setError('');setNotice('');
  if(field==='code')setReasonCode(value);else setReason(value);
  changePhase((field==='code'?value:reasonCode)||(field==='reason'?value:reason)?'dirty':'clean');
 }
 function discard(){
  if(hard())return false;
  command.current=null;setReasonCode('');setReason('');setError('');setNotice('');changePhase('clean');return true;
 }
 async function select(){
  if(live.current.phase==='pending'||!canWrite||!c.online)return;
  if(!command.current){
   if(!data||!plan||plan.target_date!==targetDate||String(plan.branch_id)!==c.branch||plan.input_freshness!=='unchanged'||!reasons[reasonCode]||reason.trim().length<3||reason.trim().length>1000)return;
   command.current={key:crypto.randomUUID(),body:{branch_id:c.branch,production_plan_id:plan.id,expected_version:data.version,reason_code:reasonCode,reason:reason.trim()}};
  }
  const attempt=command.current,requestScope=scope,csrf=api.csrf;
  const current=()=>mounted.current&&live.current.scope===requestScope&&api.csrf===csrf;
  changePhase('pending');setError('');setNotice('');
  try{
   const result=await api.post('/working-plan',attempt.body,{'Idempotency-Key':attempt.key});
   if(!current())return;
   if(result?.selection?.production_plan_id!==attempt.body.production_plan_id||result.selection.target_date!==targetDate||!Number.isSafeInteger(result.version)||result.version!==attempt.body.expected_version+1)throw new Error('Unconfirmed working plan receipt');
   command.current=null;setReasonCode('');setReason('');changePhase('clean');reload(value=>value+1);
   setNotice(c.lang==='kk'?'Жұмыс нұсқасы таңдалды. Бұрынғы сатып алулар өзгерген жоқ.':'Рабочий вариант выбран. Прежние закупки не изменены.');
  }catch(problem){if(current()){
   const unknown=!(problem instanceof ApiError)||problem.status===0||problem.status>=500||problem.code==='WORKING_PLAN_CONCURRENT_RETRY';
   changePhase(unknown?'uncertain':'dirty');
   const code=problem instanceof ApiError?problem.code:'';
   const messages:Record<string,[string,string]>={
    WORKING_PLAN_VERSION_CONFLICT:['Жұмыс жоспарын басқа адам өзгертті. Төмендегі ағымдағы таңдауды тексеріп, шешімді қайта растаңыз.','Другой пользователь изменил рабочий план. Проверьте текущий выбор ниже и подтвердите решение заново.'],
    INPUTS_CHANGED:['Бастапқы деректер өзгерген. Жаңа болжам мен нұсқаны дайындаңыз.','Исходные данные изменились. Подготовьте новый прогноз и вариант.'],
    INPUTS_UNVERIFIED:['Бастапқы деректердің өзектілігі расталмаған.','Актуальность исходных данных не подтверждена.'],
   };
   setError(messages[code]?.[c.lang==='kk'?0:1]||(unknown?(c.lang==='kk'?'Таңдау нәтижесі белгісіз. Сол сұрауды қайталап тексеріңіз.':'Результат выбора неизвестен. Повторите тот же запрос для проверки.'):(c.lang==='kk'?'Жұмыс нұсқасы таңдалмады. Деректер мен рұқсатты тексеріңіз.':'Рабочий вариант не выбран. Проверьте данные и доступ.')));
   if(!unknown){command.current=null;reload(value=>value+1)}
  }}
 }
 return {state,data,phase,reasonCode,reason,error,notice,canWrite,change,discard,select,read:()=>live.current.phase,retry:()=>reload(value=>value+1)};
}

export default function WorkingPlan({context:c,plan,controller:x,disabled=false}:{context:Context;plan:Row|null;controller:ReturnType<typeof useWorkingPlan>;disabled?:boolean}){
 const kk=c.lang==='kk',w=(kz:string,ru:string)=>kk?kz:ru,hard=x.phase==='pending'||x.phase==='uncertain';
 const selection=x.data?.selection,current=!!plan&&selection?.production_plan_id===plan.id;
 return <section className="working-plan" aria-label={w('Жұмыс нұсқасы','Рабочий вариант')} data-testid="working-plan">
  <div className="working-plan-heading"><ClipboardCheck size={19}/><h3>{w('Жұмыста қай нұсқаны қолданамыз','Какой вариант используем в работе')}</h3></div>
  <p className="muted">{w('Таңдау — дайындау ниеті. Ол орындалу фактісі емес, бұрынғы сатып алуды қайта байланыстырмайды және бекітпейді.','Выбор фиксирует намерение приготовить. Он не подтверждает выполнение, не меняет основание прежних закупок и не утверждает их.')}</p>
  {x.state.loading?<p role="status">{c.t('loading')}</p>:x.state.error||!x.data?<p className="alert warning" role="alert">{w('Ағымдағы жұмыс нұсқасын тексеру мүмкін болмады.','Не удалось проверить текущий рабочий вариант.')} <button className="text-button" disabled={hard} onClick={x.retry}>{c.t('retry')}</button></p>:<>
   <p className="working-plan-current">{selection?<><Check size={16}/>{current?w('Осы нұсқа жұмыста','Этот вариант используется в работе'):w('Басқа сақталған нұсқа жұмыста','В работе другой сохранённый вариант')} · {w('нұсқа','версия')} {fmt(x.data.version)} <button className="text-button" disabled={disabled||x.phase!=='clean'} onClick={()=>c.go('/forecasts/'+encodeURIComponent(selection.forecast_id)+'?production_plan_id='+encodeURIComponent(selection.production_plan_id))}>{w('Ашу','Открыть')}</button></>:w('Бұл күнге жұмыс нұсқасы әлі таңдалмаған.','Рабочий вариант на этот день ещё не выбран.')}</p>
   {selection&&<p className="muted">{reasons[selection.reason_code]?.[kk?0:1]||selection.reason_code}: {selection.reason} · {selection.selected_at?new Date(selection.selected_at).toLocaleString(kk?'kk-KZ':'ru-RU'):'—'} · {selection.actor_id}</p>}
   {x.canWrite&&plan&&(!current||x.phase!=='clean')&&<div className="working-plan-form">
    <label>{w('Таңдау себебі','Причина выбора')}<select aria-label={w('Таңдау себебі','Причина выбора')} value={x.reasonCode} disabled={hard||disabled||plan.input_freshness!=='unchanged'} onChange={event=>x.change('code',event.target.value)}><option value="">{w('Себепті таңдаңыз','Выберите причину')}</option>{Object.entries(reasons).map(([code,label])=><option key={code} value={code}>{label[kk?0:1]}</option>)}</select></label>
    <label>{w('Шешімді түсіндіріңіз','Поясните решение')}<textarea aria-label={w('Шешімді түсіндіріңіз','Поясните решение')} rows={2} minLength={3} maxLength={1000} value={x.reason} disabled={hard||disabled||plan.input_freshness!=='unchanged'} onChange={event=>x.change('reason',event.target.value)}/></label>
    <div className="working-plan-actions"><button className="button primary" disabled={disabled||!c.online||x.phase==='pending'||(x.phase!=='uncertain'&&(!x.reasonCode||x.reason.trim().length<3||plan.input_freshness!=='unchanged'))} onClick={()=>void x.select()}>{x.phase==='uncertain'?w('Сол таңдауды қайта тексеру','Повторить и проверить выбор'):w('Осы нұсқаны жұмыста қолдану','Этот вариант используем в работе')}</button>{x.phase==='dirty'&&<button className="text-button" onClick={x.discard}>{w('Таңдауды болдырмау','Отменить выбор')}</button>}</div>
   </div>}
   {!plan&&<p className="muted">{w('Жұмысқа таңдау үшін алдымен дайындау нұсқасын сақтаңыз.','Чтобы выбрать рабочий вариант, сначала сохраните план приготовления.')}</p>}
   {!!x.data.history.length&&<details className="review-details"><summary>{w('Таңдау тарихы','История выбора')} · {x.data.history.length}</summary><ol className="working-plan-history">{x.data.history.map((entry:Row)=><li key={entry.id}><strong>{w('Нұсқа','Версия')} {entry.version} · {date(entry.target_date)}</strong><span>{reasons[entry.reason_code]?.[kk?0:1]||entry.reason_code}: {entry.reason}</span><small>{entry.actor_id} · {entry.selected_at?new Date(entry.selected_at).toLocaleString(kk?'kk-KZ':'ru-RU'):'—'}</small><button className="text-button" disabled={disabled||x.phase!=='clean'} onClick={()=>c.go('/forecasts/'+encodeURIComponent(entry.forecast_id)+'?production_plan_id='+encodeURIComponent(entry.production_plan_id))}>{w('Осы нұсқаны ашу','Открыть этот вариант')}</button></li>)}</ol></details>}
  </>}
  {x.error&&<p className="alert warning" role="alert">{x.error}</p>}
  {x.notice&&<p className="alert success" role="status">{x.notice}</p>}
 </section>;
}
