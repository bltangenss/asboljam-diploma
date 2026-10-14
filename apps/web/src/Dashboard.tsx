import {useEffect,useRef,useState} from 'react';
import {AlertTriangle,ArrowRight,ArrowUpRight,BookOpen,CalendarDays,ClipboardCheck,Database,Package,ShoppingBasket,TrendingUp} from 'lucide-react';
import {type Context,type Row,useData,fmt,money,date,name,shiftDate,Heading,Button,Badge,Metric,Empty,DataState,Table} from './shared';
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
 const stockMatches=Boolean(target&&(c.dataContext?.inventory_dates.includes(target)||(d.inventory_known&&d.inventory_date===target)));
 const canOperate=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user.role);
 const source=d.data_origin??c.dataContext?.data_origin,synthetic=source==='SYNTHETIC',usage=c.dataContext?.usage_mode;
 const stockUrl=forecastCurrent?'/inventory?forecast='+encodeURIComponent(forecast.id):'/inventory';
 const stockImportUrl=forecastCurrent?'/imports?kind=inventory_lots&return=inventory&return_branch='+encodeURIComponent(branch)+'&forecast='+encodeURIComponent(forecast.id):'/imports?kind=inventory_lots';
 const predictions:Row[]=forecastCurrent&&Array.isArray(forecast?.predictions)?forecast.predictions:[];
 const portionTotal=predictions.length&&predictions.every(row=>row.point_forecast!==null&&row.point_forecast!==undefined&&row.point_forecast!==''&&Number.isFinite(Number(row.point_forecast)))?predictions.reduce((sum,row)=>sum+Number(row.point_forecast),0):null;
 const salesCaption=hasSales?date(d.as_of)+' · '+t('lastdata'):t('noSalesHistory');
 let next={step:'01',title:copy('Сатылым тарихын қосыңыз','Начните с истории продаж'),body:t('salesHistoryNeeded'),label:t('imports'),url:'/imports',icon:Database};
 if(hasSales)next={step:'02',title:copy('Қанша сатылатынын есептеңіз','Узнайте, сколько продастся'),body:copy('Кезеңді тексеріп, болжамды іске қосыңыз. Жүйе әр тағамға қатарынан кемінде 84 күн барын тексереді.','Проверьте период и запустите прогноз. Система проверит наличие хотя бы 84 дней подряд для каждого блюда.'),label:t('newForecast'),url:'/forecasts',icon:TrendingUp};
 if(forecastCurrent&&!stockMatches)next={step:'03',title:copy('Болжам күніне қор қажет','Нужны остатки на дату прогноза'),body:copy(`${date(target)} күнгі қор кесіндісін қосыңыз. Басқа күнгі қалдық сатып алуға қолданылмайды.`,`Добавьте срез на ${date(target)}. Остатки за другую дату не используются для этой закупки.`),label:copy('Қор деректерін қосу','Добавить остатки'),url:stockImportUrl,icon:Package};
 if(forecastCurrent&&stockMatches)next={step:'03',title:copy('Қажетті сатып алуды есептеңіз','Рассчитайте закупку'),body:copy('Болжамды рецепттермен және қормен салыстырыңыз. Бюджет пен қаптама шарттары есептеуде ескеріледі.','Сопоставьте прогноз с рецептами и остатками. Расчёт учитывает бюджет и условия упаковки.'),label:copy('Сатып алуға өту','Перейти к закупке'),url:'/procurement?forecast='+encodeURIComponent(forecast.id),icon:ShoppingBasket};
 if(planCurrent)next={step:'04',title:plan!.status==='approved'?copy('Жоспар бекітілді','План утверждён'):copy('Жоспарды қарап, шешім қабылдаңыз','Проверьте план и примите решение'),body:plan!.status==='approved'?t('internalOnly'):copy('Құнын, жеткізушілерді және тапшылықты тексеріңіз. Бекіту шешімі өзіңізде.','Проверьте стоимость, поставщиков и дефицит. Решение об утверждении принимаете вы.'),label:copy('Жоспарды ашу','Открыть план'),url:'/procurement/'+plan!.id,icon:ClipboardCheck};
 if(planCurrent&&plan!.status==='rejected')next={step:'03',title:copy('Алдыңғы жоспар қабылданбады','Предыдущий план отклонён'),body:copy('Шарттарды өзгертіп, жаңа есептеу жасаңыз. Алдыңғы шешім тарихта сақталады.','Измените условия и создайте новый расчёт. Прежнее решение останется в истории.'),label:copy('Жаңа жоспарды есептеу','Рассчитать новый план'),url:'/procurement?forecast='+encodeURIComponent(forecast.id),icon:ShoppingBasket};
 if(!canOperate)next={step:'↗',title:copy('Бөлімшенің нәтижелерін қараңыз','Посмотрите результаты филиала'),body:t('readOnlyPlanning'),label:t('forecasts'),url:'/forecasts',icon:TrendingUp};
 const NextIcon=next.icon,warnings:Row[]=d.warnings||[];
 const warningText=(w:Row)=>typeof w==='string'?w:w.code==='EXPIRED_LOTS'?`${t('expired')}: ${w.count}`:w.code==='EXPIRING_LOTS'?`${t('soon')}: ${w.count}`:t('error_'+w.code)!=='error_'+w.code?t('error_'+w.code):w.message||w.code;
 type Task={key:string;title:string;body:string;label:string;url:string;warning?:boolean};
 const tasks:Task[]=[];
 if(!hasSales)tasks.push({key:'sales',title:copy('Сатылым тарихын қосыңыз','Добавьте историю продаж'),body:t('salesHistoryNeeded'),label:copy('Деректерді қосу','Добавить данные'),url:'/imports',warning:true});
 if(hasSales&&!target)tasks.push({key:'date',title:copy('Есептеу күнін таңдаңыз','Выберите день для расчёта'),body:copy('Күн жоспары үшін аяқталған сатылым күнін көрсетіңіз.','Для плана дня укажите завершённый день продаж.'),label:copy('Күн жоспарын ашу','Открыть план дня'),url:'/forecasts',warning:true});
 if(hasSales&&target&&!forecastCurrent)tasks.push({key:'forecast',title:forecast?.target_date===target?copy('Болжамның өзектілігін тексеріңіз','Проверьте актуальность прогноза'):copy('Осы күнге болжам қажет','Нужен прогноз на этот день'),body:forecast?.target_date===target?copy('Бастапқы деректер өзгерген немесе олардың өзектілігі белгісіз. Сатып алуға дейін болжамды қайта есептеңіз.','Исходные данные изменились или их актуальность неизвестна. Пересчитайте прогноз перед закупкой.'):copy(`${date(target)} күніне порция болжамын есептеңіз.`, `Рассчитайте прогноз порций на ${date(target)}.`),label:copy('Болжамға өту','Перейти к прогнозу'),url:'/forecasts',warning:Boolean(forecast)});
 if(target&&!stockMatches)tasks.push({key:'stock',title:copy('Есептеу күніне қалдықтар жоқ','Нет остатков на день расчёта'),body:copy(`${date(target)} күніне саналған қор қажет. Бұл болжамға емес, сатып алуды есептеуге керек.`,`Нужен посчитанный срез на ${date(target)}. Это необходимо для расчёта закупки; прогноз можно подготовить отдельно.`),label:copy('Қалдықтарды қосу','Добавить остатки'),url:stockImportUrl,warning:true});
 warnings.forEach((warning,index)=>tasks.push({key:'warning-'+index,title:warningText(warning),body:copy(`${date(d.inventory_date)} күнгі қор кесіндісі бойынша. Партияларды қарап, жарамдылық мерзімін тексеріңіз.`,`По срезу на ${date(d.inventory_date)}. Проверьте партии и сроки годности.`),label:copy('Қалдықтарды тексеру','Проверить остатки'),url:'/inventory',warning:true}));
 if(plan&&forecastCurrent&&!planCurrent)tasks.push({key:'plan-stale',title:copy('Сатып алу есебін жаңарту қажет','Расчёт закупки нужно обновить'),body:copy('Жоспар деректері өзгерген немесе өзектілігі белгісіз. Бекіту алдында жаңа есептеу қажет.','Данные плана изменились или их актуальность неизвестна. Перед утверждением нужен новый расчёт.'),label:copy('Қайта есептеу','Пересчитать закупку'),url:'/procurement?forecast='+encodeURIComponent(forecast.id),warning:true});
 if(planCurrent&&Number(plan.shortage_count)>0)tasks.push({key:'shortage',title:copy(`Тапшылық бар: ${fmt(plan.shortage_count)} позиция`,`Есть дефицит: ${fmt(plan.shortage_count)} позиций`),body:copy('Есептеу барлық қажеттілікті жаппайды. Себептерін қарап, шешім қабылдаңыз.','Расчёт не покрывает всю потребность. Проверьте причины перед решением.'),label:copy('Тапшылықты қарау','Посмотреть дефицит'),url:'/procurement/'+plan.id,warning:true});
 if(planCurrent&&plan.status==='ready')tasks.push({key:'decision',title:copy('Сатып алу шешімді күтеді','Закупка ждёт решения'),body:copy('Құны, жеткізушілер мен тапшылықты тексеріңіз. Жоспар автоматты түрде бекітілмейді.','Проверьте стоимость, поставщиков и дефицит. План не утверждается автоматически.'),label:copy('Жоспарды тексеру','Проверить план'),url:'/procurement/'+plan.id});
 return <div className="today-page">
  <Heading title={copy('Бүгін','Сегодня')} sub={copy('Бір бөлімше. Бір жұмыс күні. Келесі нақты қадам.','Один филиал. Один рабочий день. Следующий конкретный шаг.')} action={c.dataContext?.dates_editable&&<label className="dashboard-date">{copy('Қаралатын қор кесіндісі','Просматриваемый срез остатков')}<select value={c.inventoryDate} onChange={event=>c.setInventoryDate(event.target.value)}>{!c.inventoryDate&&<option value="">{t('snapshotMissing')}</option>}{c.dataContext.inventory_dates.map(value=><option key={value} value={value}>{date(value)}</option>)}</select></label>}/>
  <div className="context-line today-context"><span><CalendarDays size={15}/><strong>{synthetic?copy('Оқу күні','Учебный день'):copy('Есептеу күні','День расчёта')} · {date(target)}</strong></span><span className="context-tag">{branchName||t('branch')+' '+branch} · {source??copy('Дерек көзі белгісіз','Источник неизвестен')}{usage?' · '+usage:''}</span></div>
  {synthetic&&<p className="today-source-note" role="note"><Database size={17}/>{copy('Бұл — жасанды деректердегі оқу сценарийі. Күндер нақты күнтізбелік бүгінге ауыстырылмайды.','Это учебный сценарий на синтетических данных. Даты не переносятся на сегодняшнее число.')}</p>}
  {!synthetic&&usage==='TEST'&&<p className="today-source-note" role="note"><Database size={17}/>{copy('TEST — сынақ режимі. Нәтижелер нақты бизнестің тиімділігін дәлелдемейді.','TEST — тестовый режим. Результаты не подтверждают эффективность в реальном бизнесе.')}</p>}
  <DataState state={state} t={t} retry={refresh}>
   <dl className="today-data-dates"><div><dt>{copy('Соңғы сатылым','Последние продажи')}</dt><dd>{hasSales?date(d.as_of):t('noSalesHistory')}</dd></div><div><dt>{copy('Қаралатын қор кесіндісі','Просматриваемый срез остатков')}</dt><dd>{d.inventory_known?date(d.inventory_date):t('snapshotMissing')}</dd></div></dl>
   <section className="today-tasks" aria-labelledby="today-tasks-title">
    <div className="today-section-heading"><div><span className="eyebrow">01 / {copy('АЛДЫМЕН','СНАЧАЛА')}</span><h2 id="today-tasks-title">{copy('Назар аударуды қажет етеді','Требует внимания')}</h2></div><span className="today-task-count">{tasks.length?copy(`${tasks.length} мәселе`,`${tasks.length} задач`):copy('Белгілі ескертулер жоқ','Известных предупреждений нет')}</span></div>
    {tasks.length?<ul className="today-task-list">{tasks.map(task=><li key={task.key} className={task.warning?'today-task is-warning':'today-task'}><span className="today-task-icon">{task.warning?<AlertTriangle size={20}/>:<ClipboardCheck size={20}/>}</span><div><h3>{task.title}</h3><p>{task.body}</p></div><button className="text-button" onClick={()=>go(task.url)}>{task.label}<ArrowRight size={16}/></button></li>)}</ul>:<p className="today-clear-note">{copy('Деректердің толықтығы есептеу кезінде бөлек тексеріледі. Ескертулердің болмауы барлық деректің толық екенін білдірмейді.','Полнота данных проверяется отдельно при расчёте. Отсутствие предупреждений не означает, что все данные полны.')}</p>}
   </section>
   <section className="today-work" aria-labelledby="today-work-title">
    <div className="today-section-heading"><div><span className="eyebrow">02 / {copy('КҮН ЖОСПАРЫ','ПЛАН НА ДЕНЬ')}</span><h2 id="today-work-title">{copy('Дайындаудан сатып алуға дейін','От приготовления к закупке')}</h2><p>{copy('Порция болжамы — дайындауға арналған бағдар. Соңғы көлемді өзіңіз анықтайсыз.','Прогноз порций — ориентир для приготовления. Окончательный объём определяете вы.')}</p></div><span className="today-work-date">{date(target)}</span></div>
    <ol className="today-stages">
     <li><span className="today-stage-number">1</span><div><h3>{copy('Қанша дайындау керек','Сколько готовить')}</h3><strong>{forecastCurrent?portionTotal===null?copy('Болжам есептелген','Прогноз рассчитан'):fmt(portionTotal,1)+' '+copy('порция күтіледі','порций ожидается'):copy('Болжам қажет','Нужен прогноз')}</strong><p>{copy('Болжам — өндіріс тапсырмасы емес.','Прогноз не является производственным заданием.')}</p><button className="text-button" onClick={()=>go(forecastCurrent?'/forecasts/'+forecast.id:'/forecasts')}>{forecastCurrent?copy('Тағамдар бойынша қарау','Посмотреть по блюдам'):copy('Болжамды дайындау','Подготовить прогноз')}<ArrowRight size={15}/></button></div></li>
     <li><span className="today-stage-number">2</span><div><h3>{copy('Қоймада не бар','Что есть в запасе')}</h3><strong>{stockMatches?copy('Күнге арналған кесінді бар','Срез на нужную дату есть'):copy('Күнге арналған кесінді жоқ','Нет среза на нужную дату')}</strong><p>{copy('Кесіндінің болуы барлық ингредиенттің толық екенін білдірмейді.','Наличие среза ещё не означает, что в нём есть все ингредиенты.')}</p><button className="text-button" onClick={()=>go(stockUrl)}>{copy('Қалдықтарды тексеру','Проверить остатки')}<ArrowRight size={15}/></button></div></li>
     <li><span className="today-stage-number">3</span><div><h3>{copy('Не сатып алу керек','Что нужно закупить')}</h3><strong>{planCurrent?t(plan.status):copy('Өзекті есептеу қажет','Нужен актуальный расчёт')}</strong><p>{copy('Бюджет, тапшылық және сіздің шешіміңіз.','Бюджет, дефицит и ваше решение.')}</p><button className="text-button" onClick={()=>go(planCurrent?'/procurement/'+plan.id:forecastCurrent?'/procurement?forecast='+encodeURIComponent(forecast.id):'/procurement')}>{planCurrent?copy('Сатып алуды қарау','Посмотреть закупку'):copy('Сатып алуға өту','Перейти к закупке')}<ArrowRight size={15}/></button></div></li>
    </ol>
   <div className="today-action-grid">
    <section className="next-action" aria-labelledby="next-action-title">
     <div className="next-action-top"><span className="eyebrow">{copy('КЕЛЕСІ ҚАДАМ','СЛЕДУЮЩИЙ ШАГ')}</span><span className="step-number">{next.step}</span></div>
     <h2 id="next-action-title">{next.title}</h2><p>{next.body}</p>
     <Button onClick={()=>go(next.url)}><NextIcon size={19}/>{next.label}<ArrowRight size={18}/></Button>
     <div className="next-action-foot">{copy('Соңғы шешімді адам қабылдайды.','Последнее решение принимает человек.')}</div>
    </section>
    <section className="today-purchase" aria-labelledby="today-purchase-title">
     <div className="today-purchase-heading"><ShoppingBasket size={23}/><h2 id="today-purchase-title">{copy('Осы күнге сатып алу','Закупка на этот день')}</h2>{planCurrent&&<Badge tone={plan.status==='approved'?'green':plan.status==='rejected'?'red':'amber'}>{t(plan.status)}</Badge>}</div>
     {planCurrent?<><dl><div><dt>{t('purchaseCost')}</dt><dd>{money(plan.total_cost)}</dd></div><div><dt>{t('budget')}</dt><dd>{money(plan.budget)}</dd></div><div className={Number(plan.shortage_count)>0?'today-deficit':''}><dt>{t('shortages')}</dt><dd>{fmt(plan.shortage_count)}</dd></div></dl><button className="text-button" onClick={()=>go('/procurement/'+plan.id)}>{copy('Позициялар мен шешімді қарау','Посмотреть позиции и решение')}<ArrowRight size={16}/></button><p>{t('internalOnly')}</p></>:<p className="today-purchase-empty">{copy('Осы күнге өзекті сатып алу жоспары жоқ. Болжам мен қорды тексеріп, есептеуді жалғастырыңыз.','Актуального плана закупки на этот день нет. Проверьте прогноз и остатки, затем продолжите расчёт.')}</p>}
     <details className="today-evidence"><summary>{copy('Қандай деректер бар','Какие данные доступны')}</summary><dl><div><dt>{copy('Соңғы сатылым','Последние продажи')}</dt><dd>{hasSales?date(d.as_of):t('noSalesHistory')}</dd></div><div><dt>{copy('Соңғы болжам күні','Дата последнего прогноза')}</dt><dd>{date(forecast?.target_date)}</dd></div><div><dt>{copy('Қаралатын қор кесіндісі','Просматриваемый срез остатков')}</dt><dd>{d.inventory_known?date(d.inventory_date):t('snapshotMissing')}</dd></div></dl><button className="text-button" onClick={()=>go('/imports')}>{copy('Деректерді толықтыру','Дополнить данные')}<ArrowRight size={15}/></button></details>
    </section>
   </div>
   </section>
   <section className="today-analytics" aria-labelledby="today-analytics-title">
   <div className="today-section-heading"><div><span className="eyebrow">03 / {copy('ҚОСЫМША','ДОПОЛНИТЕЛЬНО')}</span><h2 id="today-analytics-title">{copy('Өткен күндердің нәтижелері','Результаты прошлых дней')}</h2><p>{copy('Соңғы белгілі деректер. Бұл көрсеткіштер бүгінгі нәтижелер деп көрсетілмейді.','Последние известные данные. Эти показатели не выдаются за результаты сегодняшнего дня.')}</p></div><button className="text-button" onClick={()=>go('/data')}>{copy('Деректер және талдау','Данные и анализ')}<ArrowUpRight size={16}/></button></div>
   <div className="metrics metric-strip" aria-label={copy('Соңғы белгілі көрсеткіштер','Последние известные показатели')}>
    <Metric label={t('portions')} value={fmt(hasSales?d.sold_portions:null)} caption={salesCaption} icon={ShoppingBasket}/>
    <Metric label={t('revenue')} value={money(hasSales?d.revenue:null)} caption={salesCaption} icon={TrendingUp}/>
    <Metric label={t('shortages')} value={fmt(d.total_shortages)} caption={d.total_shortages==null?t('planAbsent'):date(plans[0]?.target_date)+' · '+t('requirements')} icon={AlertTriangle} tone="amber"/>
    <Metric label={t('purchaseCost')} value={money(d.procurement_cost)} caption={d.procurement_cost==null?t('planAbsent'):copy('Соңғы жоспар','Последний план')+' · '+date(plans[0]?.target_date)} icon={Package}/>
   </div>
   <div className="today-analytics-grid">
    <section className="panel chart-panel"><div className="panel-heading"><div><h2>{t('salesDynamics')}</h2><p>{copy('Деректері бар соңғы 28 күн · порция','Последние 28 дней с данными · порции')}</p></div><button className="text-button" onClick={()=>go('/sales')}>{t('sales')}<ArrowUpRight size={16}/></button></div>{history.length?<SalesChart history={history} t={t}/>:<Empty t={t}/>}</section>
    <section className="panel"><div className="panel-heading"><div><h2>{t('topMeals')}</h2><p>{salesCaption}</p></div><button className="text-button" onClick={()=>go('/sales')}>{t('viewAll')}<ArrowUpRight size={16}/></button></div><Table t={t} rows={(d.top_meals||[]).slice(0,5)} columns={[{key:'meal_name',label:t('meal'),render:r=><span className="meal-cell"><BookOpen size={16}/><strong>{name(r.meal_name||r.meal_id)}</strong></span>},{key:'units_sold',label:t('sold'),numeric:true,render:r=><strong>{fmt(r.units_sold)}</strong>},{key:'revenue',label:t('revenue'),numeric:true,render:r=>money(r.revenue)}]}/></section>
   </div>
   <details className="today-history"><summary>{t('recentPlans')}</summary>{plans.length?<Table t={t} rows={plans.slice(0,3)} rowClick={p=>go('/procurement/'+p.id)} columns={[{key:'target_date',label:t('targetDate'),render:p=>date(p.target_date)},{key:'total_cost',label:t('purchaseCost'),numeric:true,render:p=>money(p.total_cost)},{key:'status',label:t('status'),render:p=><Badge tone={p.status==='approved'?'green':p.status==='rejected'?'red':'amber'}>{t(p.status)}</Badge>}]} />:<p>{t('planAbsent')}</p>}<button className="text-button" onClick={()=>go('/procurement')}>{t('viewAll')}<ArrowRight size={16}/></button></details>
   </section>
  </DataState>
 </div>;
}

export function SalesChart({history,t}:any){
 const chartRef=useRef<HTMLDivElement>(null),[width,setWidth]=useState(780);
 useEffect(()=>{const el=chartRef.current;if(!el)return;const resize=()=>setWidth(Math.max(280,el.clientWidth));const observer=new ResizeObserver(resize);observer.observe(el);resize();return()=>observer.disconnect()},[]);
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
