import {useEffect,useRef,useState} from 'react';
import {AlertTriangle,ArrowRight,ArrowUpRight,CalendarDays,Check,ClipboardCheck,Database,Package,ShoppingBasket,TrendingUp} from 'lucide-react';
import {type Context,type Row,useData,fmt,money,date,name,shiftDate,Badge,Button,DataState,Empty} from './shared';
import './dashboard-today.css';

export default function Dashboard(c:Context){
 const {t,branch,branchName,go,revision,refresh,lang}=c;
 const copy=(kk:string,ru:string)=>lang==='kk'?kk:ru;
 const state=useData(`/dashboard?branch_id=${encodeURIComponent(branch)}${c.inventoryDate?'&inventory_date='+c.inventoryDate:''}`,revision);
 const d=state.data||{},hasSales=Boolean(d.as_of),history:Row[]=d.history||[],forecast=d.latest_forecast;
 const target=shiftDate(c.forecastOrigin,1),plans:Row[]=d.latest_plans||[];
 const plan=plans.find(p=>p.target_date===target&&p.forecast_id===forecast?.id);
 const forecastCurrent=Boolean(target&&forecast?.target_date===target&&forecast?.input_freshness==='unchanged');
 const planCurrent=forecastCurrent&&plan&&plan.input_freshness==='unchanged';
 // A stale purchase may still have a valid, immutable cooking basis. Preserve it
 // for recalculation, but never infer a missing/foreign basis from the forecast.
 const manualBasis=Boolean(plan&&(plan.demand_basis==='production_plan'||plan.production_plan_id||plan.production_plan_evidence));
 const evidence=plan?.production_plan_evidence;
 const production=manualBasis&&plan?.demand_basis==='production_plan'&&typeof plan.production_plan_id==='string'&&plan.production_plan_id&&evidence?.id===plan.production_plan_id&&evidence.basis==='manual_portions'&&String(plan.branch_id)===branch&&String(forecast?.branch_id)===branch&&String(evidence.branch_id)===branch&&evidence.forecast_id===forecast?.id&&evidence.target_date===target?evidence:null;
 const invalidProduction=manualBasis&&!production;
 const productionSuffix=production?'&production_plan_id='+encodeURIComponent(production.id):'';
 const procurementUrl=invalidProduction?'/procurement/'+encodeURIComponent(plan!.id):'/procurement?forecast='+encodeURIComponent(forecast?.id||'')+productionSuffix;
 const stockMatches=Boolean(target&&(c.dataContext?.inventory_dates.includes(target)||(d.inventory_known&&d.inventory_date===target)));
 const canOperate=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user.role);
 const source=d.data_origin??c.dataContext?.data_origin,synthetic=source==='SYNTHETIC',usage=c.dataContext?.usage_mode;
 const stockUrl=invalidProduction?procurementUrl:forecastCurrent?'/inventory?forecast='+encodeURIComponent(forecast.id)+productionSuffix:'/inventory';
 const stockImportUrl=invalidProduction?procurementUrl:forecastCurrent?'/imports?kind=inventory_lots&return=inventory&return_branch='+encodeURIComponent(branch)+'&forecast='+encodeURIComponent(forecast.id)+productionSuffix:'/imports?kind=inventory_lots';
 const predictions:Row[]=forecastCurrent&&Array.isArray(forecast?.predictions)?forecast.predictions:[];
 const portionTotal=predictions.length&&predictions.every(row=>row.point_forecast!==null&&row.point_forecast!==undefined&&row.point_forecast!==''&&Number.isFinite(Number(row.point_forecast)))?predictions.reduce((sum,row)=>sum+Number(row.point_forecast),0):null;
 const salesCaption=hasSales?date(d.as_of)+' · '+t('lastdata'):t('noSalesHistory');
 let next={step:'01',title:copy('Сатылым тарихын қосыңыз','Начните с истории продаж'),body:t('salesHistoryNeeded'),label:t('imports'),url:'/imports',icon:Database};
 if(hasSales)next={step:'02',title:copy('Қанша сатылатынын есептеңіз','Узнайте, сколько продастся'),body:copy('Кезеңді тексеріп, болжамды іске қосыңыз. Жүйе әр тағамға қатарынан кемінде 84 күн барын тексереді.','Проверьте период и запустите прогноз. Система проверит наличие хотя бы 84 дней подряд для каждого блюда.'),label:t('newForecast'),url:'/forecasts',icon:TrendingUp};
 if(forecastCurrent&&!stockMatches)next={step:'03',title:copy('Болжам күніне қор қажет','Нужны остатки на дату прогноза'),body:copy(`${date(target)} күнгі қор кесіндісін қосыңыз. Басқа күнгі қалдық сатып алуға қолданылмайды.`,`Добавьте срез на ${date(target)}. Остатки за другую дату не используются для этой закупки.`),label:copy('Қор деректерін қосу','Добавить остатки'),url:stockImportUrl,icon:Package};
 if(forecastCurrent&&stockMatches)next={step:'03',title:copy('Қажетті сатып алуды есептеңіз','Рассчитайте закупку'),body:copy('Болжамды рецепттермен және қормен салыстырыңыз. Бюджет пен қаптама шарттары есептеуде ескеріледі.','Сопоставьте прогноз с рецептами и остатками. Расчёт учитывает бюджет и условия упаковки.'),label:copy('Сатып алуға өту','Перейти к закупке'),url:procurementUrl,icon:ShoppingBasket};
 if(planCurrent)next={step:'04',title:plan!.status==='approved'?copy('Жоспар бекітілді','План утверждён'):copy('Жоспарды қарап, шешім қабылдаңыз','Проверьте план и примите решение'),body:plan!.status==='approved'?t('internalOnly'):copy('Құнын, жеткізушілерді және тапшылықты тексеріңіз. Бекіту шешімі өзіңізде.','Проверьте стоимость, поставщиков и дефицит. Решение об утверждении принимаете вы.'),label:copy('Жоспарды ашу','Открыть план'),url:'/procurement/'+plan!.id,icon:ClipboardCheck};
 if(planCurrent&&plan!.status==='rejected')next={step:'03',title:copy('Алдыңғы жоспар қабылданбады','Предыдущий план отклонён'),body:copy('Шарттарды өзгертіп, жаңа есептеу жасаңыз. Алдыңғы шешім тарихта сақталады.','Измените условия и создайте новый расчёт. Прежнее решение останется в истории.'),label:copy('Жаңа жоспарды есептеу','Рассчитать новый план'),url:procurementUrl,icon:ShoppingBasket};
 if(forecastCurrent&&invalidProduction)next={step:'03',title:copy('Дайындау негізін тексеріңіз','Проверьте основание приготовления'),body:copy('Сатып алу жоспарындағы дайындау нұсқасы расталмады. Болжамға автоматты ауыстыру жасалмайды. Алдыңғы сатып алу есебін ашып, негізін тексеріңіз.','Вариант приготовления в закупке не подтверждён. Автоматической замены прогнозом нет. Откройте исходную закупку и проверьте основание.'),label:copy('Бастапқы сатып алуды тексеру','Проверить исходную закупку'),url:procurementUrl,icon:ShoppingBasket};
 if(!canOperate)next={step:'↗',title:copy('Бөлімшенің нәтижелерін қараңыз','Посмотрите результаты филиала'),body:t('readOnlyPlanning'),label:t('forecasts'),url:'/forecasts',icon:TrendingUp};
 const NextIcon=next.icon,warnings:Row[]=d.warnings||[];
 const warningText=(w:Row)=>typeof w==='string'?w:w.code==='EXPIRED_LOTS'?`${t('expired')}: ${w.count}`:w.code==='EXPIRING_LOTS'?`${t('soon')}: ${w.count}`:t('error_'+w.code)!=='error_'+w.code?t('error_'+w.code):w.message||w.code;
 type Task={key:string;title:string;body:string;label:string;url:string;warning?:boolean};
 const tasks:Task[]=[];
 if(!hasSales)tasks.push({key:'sales',title:copy('Сатылым тарихын қосыңыз','Добавьте историю продаж'),body:t('salesHistoryNeeded'),label:copy('Деректерді қосу','Добавить данные'),url:'/imports',warning:true});
 if(hasSales&&!target)tasks.push({key:'date',title:copy('Есептеу күнін таңдаңыз','Выберите день для расчёта'),body:copy('Күн жоспары үшін аяқталған сатылым күнін көрсетіңіз.','Для плана дня укажите завершённый день продаж.'),label:copy('Күн жоспарын ашу','Открыть план дня'),url:'/forecasts',warning:true});
 if(hasSales&&target&&!forecastCurrent)tasks.push({key:'forecast',title:forecast?.target_date===target?copy('Болжамның өзектілігін тексеріңіз','Проверьте актуальность прогноза'):copy('Осы күнге болжам қажет','Нужен прогноз на этот день'),body:forecast?.target_date===target?copy('Бастапқы деректер өзгерген немесе олардың өзектілігі белгісіз. Сатып алуға дейін болжамды қайта есептеңіз.','Исходные данные изменились или их актуальность неизвестна. Пересчитайте прогноз перед закупкой.'):copy(`${date(target)} күніне порция болжамын есептеңіз.`, `Рассчитайте прогноз порций на ${date(target)}.`),label:copy('Болжамға өту','Перейти к прогнозу'),url:'/forecasts',warning:Boolean(forecast)});
 if(target&&!stockMatches)tasks.push({key:'stock',title:copy('Есептеу күніне қалдықтар жоқ','Нет остатков на день расчёта'),body:copy(`${date(target)} күніне саналған қор қажет. Бұл болжамға емес, сатып алуды есептеуге керек.`,`Нужен посчитанный срез на ${date(target)}. Это необходимо для расчёта закупки; прогноз можно подготовить отдельно.`),label:copy('Қалдықтарды қосу','Добавить остатки'),url:stockImportUrl,warning:true});
 warnings.forEach((warning,index)=>tasks.push({key:'warning-'+index,title:warningText(warning),body:copy(`${date(d.inventory_date)} күнгі қор кесіндісі бойынша. Партияларды қарап, жарамдылық мерзімін тексеріңіз.`,`По срезу на ${date(d.inventory_date)}. Проверьте партии и сроки годности.`),label:copy('Қалдықтарды тексеру','Проверить остатки'),url:stockUrl,warning:true}));
 if(plan&&forecastCurrent&&!planCurrent)tasks.push({key:'plan-stale',title:copy('Сатып алу есебін жаңарту қажет','Расчёт закупки нужно обновить'),body:copy('Жоспар деректері өзгерген немесе өзектілігі белгісіз. Бекіту алдында жаңа есептеу қажет.','Данные плана изменились или их актуальность неизвестна. Перед утверждением нужен новый расчёт.'),label:copy('Қайта есептеу','Пересчитать закупку'),url:procurementUrl,warning:true});
 if(forecastCurrent&&invalidProduction)tasks.push({key:'production-basis',title:copy('Дайындау негізі расталмады','Основание приготовления не подтверждено'),body:copy('Сақталған нұсқа жоқ немесе бөлімше, болжам не күн сәйкес емес. Болжам бойынша есептеуге үнсіз ауыспаймыз.','Сохранённый вариант отсутствует либо не совпадают филиал, прогноз или дата. Расчёт не будет незаметно переключён на прогноз.'),label:copy('Бастапқы сатып алуды ашу','Открыть исходную закупку'),url:procurementUrl,warning:true});
 if(planCurrent&&Number(plan.shortage_count)>0)tasks.push({key:'shortage',title:copy(`Тапшылық бар: ${fmt(plan.shortage_count)} позиция`,`Есть дефицит: ${fmt(plan.shortage_count)} позиций`),body:copy('Есептеу барлық қажеттілікті жаппайды. Себептерін қарап, шешім қабылдаңыз.','Расчёт не покрывает всю потребность. Проверьте причины перед решением.'),label:copy('Тапшылықты қарау','Посмотреть дефицит'),url:'/procurement/'+plan.id,warning:true});
 if(planCurrent&&plan.status==='ready')tasks.push({key:'decision',title:copy('Сатып алу шешімді күтеді','Закупка ждёт решения'),body:copy('Құны, жеткізушілер мен тапшылықты тексеріңіз. Жоспар автоматты түрде бекітілмейді.','Проверьте стоимость, поставщиков и дефицит. План не утверждается автоматически.'),label:copy('Жоспарды тексеру','Проверить план'),url:'/procurement/'+plan.id});
 // Order of the page: what needs attention now (one focus step plus the remaining tasks),
 // then the day as four steps with their state, then the last known day.
 const steps=[
  {key:'forecast',title:copy('Қанша дайындау керек','Сколько готовить'),value:forecastCurrent?portionTotal===null?copy('Болжам есептелген','Прогноз рассчитан'):fmt(portionTotal,1)+' '+copy('порция күтіледі','порций ожидается'):copy('Болжам қажет','Нужен прогноз'),note:copy('Болжам — өндіріс тапсырмасы емес.','Прогноз не является производственным заданием.'),action:forecastCurrent?copy('Тағамдар бойынша қарау','Посмотреть по блюдам'):copy('Болжамды дайындау','Подготовить прогноз'),url:forecastCurrent?'/forecasts/'+forecast.id:'/forecasts',done:forecastCurrent,warning:false},
  {key:'stock',title:copy('Қоймада не бар','Что есть в запасе'),value:stockMatches?copy('Күнге арналған кесінді бар','Срез на нужную дату есть'):copy('Күнге арналған кесінді жоқ','Нет среза на нужную дату'),note:copy('Кесіндінің болуы барлық ингредиенттің толық екенін білдірмейді.','Наличие среза ещё не означает, что в нём есть все ингредиенты.'),action:copy('Қалдықтарды тексеру','Проверить остатки'),url:stockUrl,done:stockMatches,warning:false},
  {key:'purchase',title:copy('Не сатып алу керек','Что нужно закупить'),value:planCurrent?money(plan!.total_cost):copy('Өзекті есептеу қажет','Нужен актуальный расчёт'),note:planCurrent?t('budget')+' '+money(plan!.budget)+' · '+t('shortages')+': '+fmt(plan!.shortage_count):copy('Осы күнге өзекті сатып алу жоспары жоқ.','Актуального плана закупки на этот день нет.'),action:planCurrent?copy('Сатып алуды қарау','Посмотреть закупку'):copy('Сатып алуға өту','Перейти к закупке'),url:planCurrent?'/procurement/'+plan!.id:forecastCurrent?procurementUrl:'/procurement',done:Boolean(planCurrent&&plan!.status!=='rejected'&&!invalidProduction),warning:Boolean(planCurrent&&Number(plan!.shortage_count)>0)},
  {key:'decision',title:copy('Шешім','Решение'),value:planCurrent?t(plan!.status):'—',note:t('internalOnly'),action:'',url:'',done:Boolean(planCurrent&&plan!.status==='approved'),warning:false},
 ];
 const current=!canOperate?0:!forecastCurrent?1:!stockMatches?2:(!planCurrent||plan!.status==='rejected'||invalidProduction)?3:plan!.status==='approved'?5:4;
 // The focus block already carries its own action; the list holds everything else.
 const listed=tasks.filter(task=>!(task.url===next.url&&task.label===next.label));
 const recap=(d.top_meals||[]).slice(0,4) as Row[];
 return <div className="today-page">
  <header className="day-header">
   <div><h1>{copy('Бүгін','Сегодня')}</h1><p className="day-context"><CalendarDays size={15}/><strong>{synthetic?copy('Оқу күні','Учебный день'):copy('Есептеу күні','День расчёта')} · {date(target)}</strong><span>{branchName||t('branch')+' '+branch}</span><span>{source??copy('Дерек көзі белгісіз','Источник неизвестен')}{usage?' · '+usage:''}</span></p></div>
   {c.dataContext?.dates_editable&&<label className="dashboard-date">{copy('Қаралатын қор кесіндісі','Просматриваемый срез остатков')}<select value={c.inventoryDate} onChange={event=>c.setInventoryDate(event.target.value)}>{!c.inventoryDate&&<option value="">{t('snapshotMissing')}</option>}{c.dataContext.inventory_dates.map(value=><option key={value} value={value}>{date(value)}</option>)}</select></label>}
  </header>
  {synthetic&&<p className="today-source-note" role="note"><Database size={15}/>{copy('Бұл — жасанды деректердегі оқу сценарийі. Күндер нақты күнтізбелік бүгінге ауыстырылмайды.','Это учебный сценарий на синтетических данных. Даты не переносятся на сегодняшнее число.')}</p>}
  {!synthetic&&usage==='TEST'&&<p className="today-source-note" role="note"><Database size={15}/>{copy('TEST — сынақ режимі. Нәтижелер нақты бизнестің тиімділігін дәлелдемейді.','TEST — тестовый режим. Результаты не подтверждают эффективность в реальном бизнесе.')}</p>}
  <DataState state={state} t={t} retry={refresh}>
   <section className="day-attention" aria-labelledby="day-attention-title">
    <h2 id="day-attention-title" className="day-section-title">{copy('Назар аударуды қажет етеді','Требует внимания')}<span>{tasks.length?copy(tasks.length+' мәселе',tasks.length+' задач'):copy('Белгілі ескертулер жоқ','Известных предупреждений нет')}</span></h2>
    <section className="next-action day-focus" aria-labelledby="next-action-title">
     <div className="day-focus-copy"><span className="eyebrow">{current===5?copy('КҮН ДАЙЫН','ДЕНЬ ГОТОВ'):copy('КЕЛЕСІ ҚАДАМ','СЛЕДУЮЩИЙ ШАГ')} · {next.step}</span><h2 id="next-action-title">{next.title}</h2><p>{next.body}</p>
      {planCurrent&&production&&<p className="day-basis" data-testid="today-production-basis">{copy('Дайындау жоспары бойынша','По плану приготовления')}: <strong>{production.name||'—'}</strong>. {copy('Мөлшерді басқарушы таңдаған.','Объёмы выбраны управляющим.')} <button className="text-button" onClick={()=>go('/forecasts/'+encodeURIComponent(production.forecast_id)+'?production_plan_id='+encodeURIComponent(production.id))}>{copy('Порцияларды қарау','Посмотреть порции')}<ArrowRight size={15}/></button></p>}
     </div>
     <div className="day-focus-action"><Button onClick={()=>go(next.url)}><NextIcon size={18}/>{next.label}<ArrowRight size={17}/></Button><span className="next-action-foot">{copy('Соңғы шешімді адам қабылдайды.','Последнее решение принимает человек.')}</span></div>
    </section>
    {listed.length>0&&<ul className="day-task-list">{listed.map(task=><li key={task.key} className={task.warning?'day-task is-warning':'day-task'}><span className="day-task-icon" aria-hidden="true">{task.warning?<AlertTriangle size={16}/>:<ClipboardCheck size={16}/>}</span><div><h3>{task.title}</h3><p>{task.body}</p></div><button className="text-button" onClick={()=>go(task.url)}>{task.label}<ArrowRight size={15}/></button></li>)}</ul>}
    {!tasks.length&&<p className="day-clear-note">{copy('Деректердің толықтығы есептеу кезінде бөлек тексеріледі. Ескертулердің болмауы барлық деректің толық екенін білдірмейді.','Полнота данных проверяется отдельно при расчёте. Отсутствие предупреждений не означает, что все данные полны.')}</p>}
   </section>
   <section className="day-work" aria-labelledby="day-work-title">
    <h2 id="day-work-title" className="day-section-title">{copy('Дайындаудан сатып алуға дейін','От приготовления к закупке')}<span>{date(target)}</span></h2>
    <ol className="day-pipeline">
     {steps.map((step,index)=>{const number=index+1,state=step.done?'done':number===current?'current':'waiting';return <li key={step.key} className={'day-step day-step-'+step.key+' is-'+state+(step.warning?' has-warning':'')} aria-current={number===current?'step':undefined}>
      <span className="day-step-mark" aria-hidden="true">{step.done?<Check size={14}/>:number}</span><span className="day-step-title">{step.title}</span>
      <strong>{step.key==='decision'&&planCurrent?<Badge tone={plan!.status==='approved'?'green':plan!.status==='rejected'?'red':'amber'}>{step.value}</Badge>:step.value}</strong>
      <small className={step.key==='purchase'&&!planCurrent?'day-purchase-empty':undefined}>{step.note}</small>
      {step.action&&<button className="text-button" onClick={()=>go(step.url)}>{step.action}<ArrowRight size={14}/></button>}
     </li>})}
    </ol>
    <dl className="day-data-dates"><div><dt>{copy('Соңғы сатылым','Последние продажи')}</dt><dd>{hasSales?date(d.as_of):t('noSalesHistory')}</dd></div><div><dt>{copy('Қаралатын қор кесіндісі','Просматриваемый срез остатков')}</dt><dd>{d.inventory_known?date(d.inventory_date):t('snapshotMissing')}</dd></div><div><dt>{copy('Соңғы болжам күні','Дата последнего прогноза')}</dt><dd>{date(forecast?.target_date)}</dd></div></dl>
   </section>
   <section className="day-recap" aria-labelledby="today-analytics-title">
    <div className="day-recap-head"><h2 id="today-analytics-title">{copy('Соңғы белгілі күн','Последний известный день')}</h2><span>{salesCaption}</span><button className="text-button" onClick={()=>go('/sales')}>{copy('Талдау','Анализ')}<ArrowUpRight size={15}/></button></div>
    <div className="day-recap-body">
     <dl className="day-recap-figures"><div><dt>{t('portions')}</dt><dd className="metric-value">{fmt(hasSales?d.sold_portions:null)}</dd></div><div><dt>{t('revenue')}</dt><dd className="metric-value">{money(hasSales?d.revenue:null)}</dd></div></dl>
     <div className="day-recap-chart">{history.length?<SalesChart history={history} t={t} compact/>:<Empty t={t}/>}</div>
     {recap.length>0&&<ol className="day-recap-meals" aria-label={t('topMeals')}>{recap.map(r=><li key={String(r.meal_id)}><span>{name(r.meal_name||r.meal_id)}</span><strong>{fmt(r.units_sold)}</strong></li>)}</ol>}
    </div>
    <button className="text-button day-recap-plans" onClick={()=>go('/procurement')}>{t('recentPlans')}: {plans.length?plans.length:t('planAbsent')}<ArrowRight size={15}/></button>
   </section>
  </DataState>
 </div>;
}

export function SalesChart({history,t,compact=false}:any){
 const chartRef=useRef<HTMLDivElement>(null),[width,setWidth]=useState(780);
 useEffect(()=>{const el=chartRef.current;if(!el)return;const resize=()=>setWidth(Math.max(compact?160:280,el.clientWidth));const observer=new ResizeObserver(resize);observer.observe(el);resize();return()=>observer.disconnect()},[]);
 if(compact)return <SalesSparkline history={history} t={t} chartRef={chartRef} width={width}/>;
 const height=240,pad=55;
 const points:(number|null)[]=history.map((r:Row)=>{const v=r.units_sold??r.portions??r.total_units;return v===null||v===undefined||!Number.isFinite(Number(v))?null:Number(v)});
 const max=Math.max(...points.filter((v):v is number=>v!==null),1)*1.15;
 const x=(i:number)=>pad+i*(width-pad-24)/Math.max(points.length-1,1),y=(v:number)=>height-30-v*(height-55)/max;
 let previous=-2;
 const line=points.map((v,i)=>{if(v===null)return '';const gap=i>0&&shiftDate(history[i-1].date,1)!==String(history[i].date).slice(0,10);const command=previous===i-1&&!gap?'L':'M';previous=i;return `${command} ${x(i)} ${y(v)}`}).join(' ');
 return <div className="chart-wrap"><div className="chart-legend"><span/><span>{t('sold')}</span><small>{date(history[0]?.date)} — {date(history[history.length-1]?.date)}</small></div><div ref={chartRef}>
  <svg className="sales-chart" viewBox={`0 0 ${width} ${height+18}`} role="img" aria-label={t('salesDynamics')}>
   <title>{t('salesDynamics')}: {date(history[0]?.date)} — {date(history[history.length-1]?.date)}</title>
   {[0,1,2,3].map(i=><g key={i}><line x1={pad} y1={y(max*i/3)} x2={width-18} y2={y(max*i/3)} stroke="var(--border)"/><text x={pad-10} y={y(max*i/3)+4} textAnchor="end">{fmt(max*i/3)}</text></g>)}
   <path d={line} fill="none" stroke="var(--action)" strokeWidth="3" strokeLinejoin="round"/>
   {history.map((r:Row,i:number)=>points[i]===null?null:<circle key={i} cx={x(i)} cy={y(points[i]!)} r="3.5" fill="var(--action)" className="chart-point"><title>{date(r.date)}: {fmt(points[i])}</title></circle>)}
   {history.filter((_:Row,i:number)=>i%Math.max(1,Math.ceil(history.length/(width<500?3:6)))===0).map((r:Row)=>{const i=history.indexOf(r);return <text key={i} x={x(i)} y={height+4} textAnchor="middle">{date(r.date).slice(0,5)}</text>})}
  </svg>
 </div></div>;
}

// A small line for the Today recap: the trend at a glance, the full chart lives in Sales.
function SalesSparkline({history,t,chartRef,width}:any){
 const height=64,values:(number|null)[]=history.map((r:Row)=>{const v=r.units_sold??r.portions??r.total_units;return v===null||v===undefined||!Number.isFinite(Number(v))?null:Number(v)});
 const known=values.filter((v):v is number=>v!==null),max=Math.max(...known,1),min=Math.min(...known,0);
 const x=(i:number)=>4+i*(width-8)/Math.max(values.length-1,1),y=(v:number)=>height-6-(v-min)*(height-12)/Math.max(max-min,1);
 // Same honesty rule as the full chart: a missing day or value breaks the line, never bridges it.
 const joined=(i:number)=>i>0&&values[i-1]!==null&&shiftDate(String(history[i-1].date).slice(0,10),1)===String(history[i].date).slice(0,10);
 const line=values.map((v,i)=>v===null?'':`${joined(i)?'L':'M'} ${x(i)} ${y(v)}`).join(' ');
 const lonely=values.map((v,i)=>v!==null&&!joined(i)&&!(i+1<values.length&&joined(i+1))?i:-1).filter(i=>i>=0);
 return <div ref={chartRef} className="sales-sparkline"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t('salesDynamics')}><title>{t('salesDynamics')}: {date(history[0]?.date)} — {date(history[history.length-1]?.date)}</title><path d={line} fill="none" stroke="var(--action)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"/>{lonely.map(i=><circle key={i} cx={x(i)} cy={y(values[i]!)} r="2.5" fill="var(--action)"/>)}</svg><small>{date(history[0]?.date)} — {date(history[history.length-1]?.date)}</small></div>;
}
