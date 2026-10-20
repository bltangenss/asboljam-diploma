import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {ArrowRight,BarChart3,Save} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,fmt,name,Table} from './shared';
import {useWorkdayData} from './workdayData';
import './forecast-review.css';

const known=(value:any)=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
const percent=(value:any)=>known(value)?fmt(Number(value)*100,1)+'%':'—';
const kinds:Record<string,[string,string]>={prospective:['Алдын ала жасалған болжам','Заблаговременный прогноз'],historical:['Кейінгі тарихи қайта есептеу','Поздний исторический пересчёт'],synthetic_demo:['Жасанды сценарий','Синтетический сценарий'],none:['Болжам жоқ','Нет прогноза']};
const statuses:Record<string,[string,string]>={closed:['Күн жабық','День закрыт'],missing:['Сатылым жолы жоқ','Нет строки продаж'],not_offered:['Ұсынылмады','Не предлагалось'],unclosed:['Күн жабылмаған','День не закрыт'],changed_after_closure:['Жабылғаннан кейін өзгерген','Изменено после закрытия']};

export default function ForecastReview(c:Context){
 if(!['admin','manager','analyst'].includes(c.user.role))return null;
 return <ReviewWorkspace key={JSON.stringify([c.user.organization_id,c.user.id,c.user.role,c.branch])} context={c}/>;
}

function ReviewWorkspace({context:c}:{context:Context}){
 const kk=c.lang==='kk',w=(kz:string,ru:string)=>kk?kz:ru;
 const [revision,reload]=useState(0),[day,setDay]=useState(''),[snapshotId,setSnapshotId]=useState('');
 const [busy,setBusy]=useState(false),[uncertain,setUncertain]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const pending=useRef(false),unconfirmed=useRef(false),mounted=useRef(true),command=useRef<{key:string;body:Row}|null>(null);
 const state=useWorkdayData(c,c.branch?'/forecast-review?branch_id='+encodeURIComponent(c.branch)+'&days=28':null,revision);
 const history=useWorkdayData(c,snapshotId?'/forecast-review/history/'+encodeURIComponent(snapshotId):null);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useLayoutEffect(()=>c.registerNavigationBlocker?.({read:()=>pending.current?'pending':unconfirmed.current?'uncertain':'clean',discard:()=>!pending.current&&!unconfirmed.current}),[c.registerNavigationBlocker]);
 const review=state.data?.branch_id===c.branch&&state.data?.summary&&Array.isArray(state.data?.days)?state.data:null;
 const canSave=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user.role);
 async function saveReview(){
  if(pending.current||!canSave||!c.online||(!command.current&&!review))return;
  if(!command.current)command.current={key:crypto.randomUUID(),body:{branch_id:c.branch,days:28,...(review?.date_to?{end_date:review.date_to}:{})}};
  const attempt=command.current,csrf=api.csrf;pending.current=true;setBusy(true);setError('');setNotice('');
  try{
   const result=await api.post('/forecast-review/refresh',attempt.body,{'Idempotency-Key':attempt.key});
   if(!mounted.current||api.csrf!==csrf)return;
   if(!Array.isArray(result?.snapshots)||result.review?.branch_id!==c.branch)throw new Error('Unconfirmed review receipt');
   command.current=null;unconfirmed.current=false;setUncertain(false);reload(value=>value+1);
   setNotice(w('Сверка сақталды. Алдыңғы нұсқалар тарихта қалды.','Сверка сохранена. Прежние версии остались в истории.'));
  }catch(problem){if(mounted.current&&api.csrf===csrf){
   const unknown=!(problem instanceof ApiError)||problem.status===0||problem.status>=500||problem.code==='REVIEW_CONCURRENT_RETRY';
   unconfirmed.current=unknown;setUncertain(unknown);if(!unknown)command.current=null;
   setError(unknown?w('Сақтау жауабы алынбады. Сол сұрауды қайталап тексеріңіз.','Ответ о сохранении не получен. Повторите тот же запрос для проверки.'):w('Сверканы сақтау мүмкін болмады. Деректер мен рұқсатты тексеріңіз.','Не удалось сохранить сверку. Проверьте данные и доступ.'));
  }}finally{if(mounted.current&&api.csrf===csrf){pending.current=false;setBusy(false)}}
 }
 if(state.loading)return <section className="forecast-review" aria-busy="true"><p role="status">{w('Болжам мен нақты сатылым салыстырылуда…','Сопоставляем прогноз и фактические продажи…')}</p></section>;
 if(state.error||!review)return <section className="forecast-review"><h2>{w('Болжам және нақты сатылым','Прогноз и фактические продажи')}</h2><p className="alert warning" role="alert">{w('Сверка жүктелмеді. Бұл нөлдік қате дегенді білдірмейді.','Сверка не загрузилась. Это не означает нулевую ошибку.')} <button className="text-button" onClick={()=>reload(value=>value+1)}>{c.t('retry')}</button></p></section>;
 const summary=review.summary,latest=review.latest_closed_day;
 const chosen=review.days.find((entry:Row)=>entry.date===day)||latest||review.days[review.days.length-1];
 const selected=snapshotId?history.data:chosen;
 const rows:Row[]=selected?.rows||review.rows?.filter((row:Row)=>row.date===selected?.date)||[];
 const metrics=summary.metrics||{},demo=summary.demonstration_metrics||{},adjustment=summary.adjustment||{};
 const nonBusiness=review.data_origin==='SYNTHETIC'||review.usage_mode==='TEST';
 return <section className="forecast-review" aria-labelledby="forecast-review-title" data-testid="forecast-review">
  <div className="review-heading"><div><span className="planning-eyebrow">{w('Жабылған күннің қорытындысы','Итог закрытого дня')}</span><h2 id="forecast-review-title">{w('Болжам және нақты сатылым','Прогноз и фактические продажи')}</h2></div><BarChart3 size={21}/></div>
  {latest?<p className="review-summary"><strong>{date(latest.date)}</strong> · {w('жабылу нұсқасы','версия закрытия')} {fmt(latest.closure_version)} · {w('салыстырылған тағамдар','сопоставлено блюд')}: {fmt(latest.matched_observations)} · {w('жетіспейтін жолдар','неполных строк')}: {fmt(latest.missing_observations)}</p>:<p className="review-summary">{w('Жабылған күн жоқ. Сатылымның толықтығын растау үшін күнді жабыңыз.','Нет закрытого дня. Закройте день, чтобы подтвердить полноту продаж.')} <button className="text-button" onClick={()=>c.go('/day-close')}>{w('Күнді жабу','Закрыть день')}<ArrowRight size={14}/></button></p>}
  <p className="review-caveat">{nonBusiness?w('SYNTHETIC / TEST: төмендегі оқу салыстыруы нақты бизнестегі болжам сапасын дәлелдемейді.','SYNTHETIC / TEST: учебное сравнение ниже не подтверждает качество прогнозов для реального бизнеса.'):Number(metrics.n)>0?w('Тек күн басталғанға дейін сақталған болжамдар өнімділік көрсеткішіне кіреді.','В показатели входят только прогнозы, сохранённые до начала целевого дня.'):w('Алдын ала жасалған болжамдар әзірге жоқ. Кейінгі тарихи есептеулер көрсеткішке кірмейді.','Заблаговременных прогнозов пока нет. Исторические пересчёты не входят в показатели.')}</p>
  <details className="review-details"><summary>{w('Тағамдар мен кезеңді салыстыру','Сравнить блюда и период')} · {date(review.date_from)} — {date(review.date_to)}</summary>
   <MetricSummary metrics={metrics} context={c}/>
   <p className="muted">{w('Толық емес күндер','Неполных дней')}: {fmt(summary.incomplete_days)} · {w('Есептен шығарылған күндер','Исключено дней')}: {fmt(summary.excluded_days)} · {w('Тағам біткен бақылаулар','Наблюдений с окончанием блюда')}: {fmt(summary.stockout_observations)}.</p>
   {Number(demo.n)>0&&<details className="review-details review-demo"><summary>{w('Оқу / тестілік салыстыруды бөлек көру','Посмотреть учебное / тестовое сравнение отдельно')}</summary><MetricSummary metrics={demo} context={c}/><p className="muted">{w('Бұл нақты бизнестің болжам сапасы емес.','Это не показатели качества прогнозов реального бизнеса.')}</p></details>}
   <div className="review-day-controls"><label>{w('Салыстыру күні','День сравнения')}<select aria-label={w('Салыстыру күні','День сравнения')} value={chosen?.date||''} onChange={event=>{setDay(event.target.value);setSnapshotId('')}}>{review.days.map((entry:Row)=><option key={entry.date} value={entry.date}>{date(entry.date)} · {entry.closure_status==='closed'?w('жабық','закрыт'):w('толық емес','неполный')}</option>)}</select></label><label>{w('Сверка нұсқасы','Версия сверки')}<select aria-label={w('Сверка нұсқасы','Версия сверки')} value={snapshotId} onChange={event=>setSnapshotId(event.target.value)}><option value="">{w('Ағымдағы деректер','Текущие данные')}</option>{(review.history||[]).filter((entry:Row)=>entry.target_date===chosen?.date).map((entry:Row)=><option key={entry.id} value={entry.id}>{w('Сақталған нұсқа','Сохранённая версия')} {entry.version} · {entry.created_at?new Date(entry.created_at).toLocaleString(kk?'kk-KZ':'ru-RU'):'—'}</option>)}</select></label></div>
   {snapshotId&&history.loading?<p role="status">{c.t('loading')}</p>:snapshotId&&history.error?<p role="alert">{w('Сақталған сверка жүктелмеді.','Сохранённая сверка не загрузилась.')}</p>:selected?<>
    <p className="review-day-kind"><strong>{kinds[selected.forecast_kind]?.[kk?0:1]||w('Болжам түрі белгісіз','Тип прогноза неизвестен')}</strong> · {w('Жабылу нұсқасы','Версия закрытия')}: {fmt(selected.closure_version)}.</p>
    {!selected.eligible_for_performance&&<p className="review-caveat">{w('Бұл күн нақты болашақ болжамының көрсеткішіне кірмейді.','Этот день не входит в показатели реального прогноза будущего.')}</p>}
    <Table t={c.t} rows={rows} columns={[{key:'meal',label:c.t('meal'),render:row=>name(row.meal_name||row.meal_id)},{key:'forecast_point',label:w('Күн болжамы','Прогноз дня'),numeric:true,render:row=>fmt(row.forecast_point,1)},{key:'planned_portions',label:w('Жұмыс жоспары','Рабочий план'),numeric:true,render:row=>fmt(row.planned_portions)},{key:'actual_units',label:w('Сатылды','Продано'),numeric:true,render:row=>fmt(row.actual_units)},{key:'delta',label:w('Болжам − факт','Прогноз − факт'),numeric:true,render:row=>fmt(row.delta,1)},{key:'stockout',label:w('Бітті ме','Закончилось'),render:row=>row.stockout===null||row.stockout===undefined?'—':row.stockout?w('Иә','Да')+(row.stockout_time?' · '+row.stockout_time:''):w('Жоқ','Нет')},{key:'fact_status',label:w('Фактінің толықтығы','Полнота факта'),render:row=>statuses[row.fact_status]?.[kk?0:1]||w('Белгісіз','Неизвестно')},...(rows.some(row=>known(row.plan_forecast_point))?[{key:'plan_forecast_point',label:w('Жоспардың бастапқы болжамы','Исходный прогноз варианта'),numeric:true,render:(row:Row)=>fmt(row.plan_forecast_point,1)}]:[])]}/>
    <p className="muted">{w('Сатылым жолы жоқ болса — мән белгісіз, нөл емес. Тағам біткен күннің сатылымы жасырын сұранысты көрсетпейді.','Нет строки продаж — значение неизвестно, а не ноль. Продажи в день окончания блюда не показывают скрытый спрос.')}</p>
    {selected.working_plan&&<p className="muted">{w('Жұмыс нұсқасын таңдаған','Рабочий вариант выбрал')}: {selected.working_plan.actor_id} · {selected.working_plan.reason}. {w('Факт пайда болғаннан кейінгі таңдау алдын ала шешімдердің салыстыруына кірмейді.','Выбор после появления факта не входит в сравнение заблаговременных решений.')}</p>}
    <details className="review-details"><summary>{w('Дерек нұсқасы мен таңдау ережесі','Версия данных и правило выбора')}</summary><p>{w('Жұмыс болжамы — күн басталғанға дейін жасалған соңғы есептеу. Демо күндер оқу сценарийі ретінде бөлек қаралады.','Рабочий прогноз — последний расчёт до начала целевого дня. Демо-дни рассматриваются отдельно как учебный сценарий.')}</p><p className="review-fingerprint">{w('Факт ізі','Отпечаток факта')}: {selected.fact_fingerprint||'—'}</p><p className="review-fingerprint">{w('Шығарылу кодтары','Коды исключения')}: {(selected.exclusion_reasons||[]).join(', ')||'—'}</p></details>
   </>:null}
   <section className="review-adjustment"><h3>{w('Басқарушының түзетуі','Поправка управляющего')}</h3>{Number(adjustment.n)>0?<><p>{w('Бірдей бақылаулар','Одинаковых наблюдений')}: {fmt(adjustment.n)} · MAE {w('болжам / жоспар','прогноз / план')}: {fmt(adjustment.forecast_mae,1)} / {fmt(adjustment.plan_mae,1)} {w('порция','порций')}.</p><p>{w('Бақыланған сатылымға түзету жақынырақ болған','Поправка оказалась ближе к наблюдаемым продажам')}: {fmt(adjustment.closer)}; {w('бірдей','одинаково')}: {fmt(adjustment.same)}; {w('алысырақ','дальше')}: {fmt(adjustment.worse)}.</p></>:<p>{w('Алдын ала таңдалған түзетулерді салыстыруға бақылаулар жеткіліксіз.','Пока недостаточно наблюдений для сравнения заблаговременных поправок.')}</p>}<p className="muted">{w('Жақынырақ қате пайда немесе үнем артқанын дәлелдемейді. Қолмен енгізілген порциялар модельдің сұраныс нысанасы емес.','Меньшая ошибка не доказывает роста прибыли или экономии. Ручные порции не используются как спрос при обучении.')}</p></section>
   {Number(summary.demonstration_adjustment?.n)>0&&<details className="review-details"><summary>{w('Түзетулерді тарихи / оқу салыстыруы','Историческое / учебное сравнение поправок')}</summary><p>{w('Бұл алдын ала қабылданған бизнес шешімдерінің рейтингі емес. Нұсқаның өз бастапқы болжамымен бірдей бақылауларда салыстырылады.','Это не рейтинг заблаговременных бизнес-решений. Вариант сравнивается со своим исходным прогнозом на одинаковых наблюдениях.')}</p><p>{w('Бақылаулар','Наблюдений')}: {fmt(summary.demonstration_adjustment.n)} · MAE {w('бастапқы болжам / жоспар','исходный прогноз / план')}: {fmt(summary.demonstration_adjustment.forecast_mae,1)} / {fmt(summary.demonstration_adjustment.plan_mae,1)}.</p><p>{w('Түзету бақыланған сатылымға жақынырақ болған','Поправка оказалась ближе к наблюдаемым продажам')}: {fmt(summary.demonstration_adjustment.closer)} · {w('бірдей','одинаково')}: {fmt(summary.demonstration_adjustment.same)} · {w('алысырақ','дальше')}: {fmt(summary.demonstration_adjustment.worse)}.</p></details>}
   {canSave&&<div className="review-save"><button className="button secondary" disabled={busy||!c.online} onClick={()=>void saveReview()}><Save size={16}/>{uncertain?w('Сол сақтауды қайта тексеру','Повторить и проверить сохранение'):w('Ағымдағы сверканы сақтау','Сохранить текущую сверку')}</button><p className="muted">{w('Тек осы әрекет тарихқа нұсқа сақтайды. Бетті ашу сатылымды өзгертпейді.','Только это действие сохраняет версию в историю. Открытие страницы не меняет продажи.')}</p></div>}
   {error&&<p className="alert warning" role="alert">{error}</p>}{notice&&<p className="alert success" role="status">{notice}</p>}
  </details>
 </section>;
}

function MetricSummary({metrics:m,context:c}:{metrics:Row;context:Context}){
 const w=(kk:string,ru:string)=>c.lang==='kk'?kk:ru,n=Number(m.n)||0;
 return <div className="review-metrics"><dl><div><dt>MAE · {w('порция','порций')}</dt><dd>{n?fmt(m.mae,1):'—'}</dd></div><div><dt>WAPE</dt><dd>{n?percent(m.wape):'—'}</dd></div><div><dt>{w('Орташа қате','Средняя ошибка')} · ±</dt><dd>{n?fmt(m.bias,1):'—'}</dd></div><div><dt>{w('Бақылау саны','Число наблюдений')}</dt><dd>{fmt(m.n)}</dd></div></dl><p className="muted">{w('Қате = болжам − факт. Оң мән — артық болжам. WAPE факт сомасы нөл болса есептелмейді.','Ошибка = прогноз − факт. Плюс означает завышение. WAPE не рассчитывается при нулевой сумме факта.')}</p>{n<30&&<p className="review-caveat">{w('Әзірге бақылау аз: сапаны бағалау түсімен белгілемейміз. 30 бақылаудан аз болғанда көрсеткіштер алдын ала ғана.','Пока мало наблюдений: качество не оцениваем цветом. При менее 30 наблюдениях показатели предварительные.')}</p>}<p className="muted">{Number(m.interval_n)>0?`${w('p10–p90 қамтуы','Покрытие p10–p90')}: ${percent(m.interval_coverage)} · ${fmt(m.interval_n)} ${w('бақылау','наблюдений')}. ${w('Номинал 80%, кепілдік емес.','Номинал 80%, это не гарантия.')}`:w('Интервал қамтуын есептеуге бақылау жоқ. Қарапайым модельдер интервал бермейді.','Нет наблюдений для покрытия интервала. Простые модели не предоставляют интервалы.')}</p></div>;
}
