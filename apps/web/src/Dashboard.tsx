import {useEffect,useRef,useState} from 'react';
import {AlertTriangle,ArrowRight,ArrowUpRight,BookOpen,CalendarDays,ClipboardCheck,Database,Package,ShoppingBasket,TrendingUp} from 'lucide-react';
import {type Context,type Row,useData,fmt,money,date,name,shiftDate,Heading,Button,Badge,Metric,Empty,DataState,Table} from './shared';

export default function Dashboard(c:Context){
 const {t,branch,branchName,go,revision,refresh,lang}=c;
 const copy=(kk:string,ru:string)=>lang==='kk'?kk:ru;
 const state=useData(`/dashboard?branch_id=${encodeURIComponent(branch)}${c.inventoryDate?'&inventory_date='+c.inventoryDate:''}`,revision);
 const d=state.data||{},hasSales=Boolean(d.as_of),history:Row[]=d.history||[],forecast=d.latest_forecast;
 const target=shiftDate(c.forecastOrigin,1),plans:Row[]=d.latest_plans||[];
 const plan=plans.find(p=>p.target_date===target&&p.forecast_id===forecast?.id);
 const forecastCurrent=Boolean(target&&forecast?.target_date===target&&forecast?.input_freshness==='unchanged');
 const planCurrent=Boolean(forecastCurrent&&plan?.input_freshness==='unchanged');
 const stockMatches=Boolean(target&&(c.dataContext?.inventory_dates.includes(target)||(d.inventory_known&&d.inventory_date===target)));
 const canOperate=['admin','manager'].includes(c.user.role);
 const salesCaption=hasSales?date(d.as_of)+' · '+t('lastdata'):t('noSalesHistory');
 let next={step:'01',title:copy('Сатылым тарихын қосыңыз','Начните с истории продаж'),body:t('salesHistoryNeeded'),label:t('imports'),url:'/imports',icon:Database};
 if(hasSales)next={step:'02',title:copy('Қанша сатылатынын есептеңіз','Узнайте, сколько продастся'),body:copy('Кезеңді тексеріп, болжамды іске қосыңыз. Жүйе әр тағамға қатарынан кемінде 84 күн барын тексереді.','Проверьте период и запустите прогноз. Система проверит наличие хотя бы 84 дней подряд для каждого блюда.'),label:t('newForecast'),url:'/forecasts',icon:TrendingUp};
 if(forecastCurrent&&!stockMatches)next={step:'03',title:copy('Болжам күніне қор қажет','Нужны остатки на дату прогноза'),body:copy(`${date(target)} күнгі қор кесіндісін қосыңыз. Басқа күнгі қалдық сатып алуға қолданылмайды.`,`Добавьте срез на ${date(target)}. Остатки за другую дату не используются для этой закупки.`),label:copy('Қор деректерін қосу','Добавить остатки'),url:'/imports?kind=inventory_lots',icon:Package};
 if(forecastCurrent&&stockMatches)next={step:'03',title:copy('Қажетті сатып алуды есептеңіз','Рассчитайте закупку'),body:copy('Болжамды рецепттермен және қормен салыстырыңыз. Бюджет пен қаптама шарттары есептеуде ескеріледі.','Сопоставьте прогноз с рецептами и остатками. Расчёт учитывает бюджет и условия упаковки.'),label:copy('Сатып алуға өту','Перейти к закупке'),url:'/procurement?forecast='+encodeURIComponent(forecast.id),icon:ShoppingBasket};
 if(planCurrent)next={step:'04',title:plan!.status==='approved'?copy('Жоспар бекітілді','План утверждён'):copy('Жоспарды қарап, шешім қабылдаңыз','Проверьте план и примите решение'),body:plan!.status==='approved'?t('internalOnly'):copy('Құнын, жеткізушілерді және тапшылықты тексеріңіз. Бекіту шешімі өзіңізде.','Проверьте стоимость, поставщиков и дефицит. Решение об утверждении принимаете вы.'),label:copy('Жоспарды ашу','Открыть план'),url:'/procurement/'+plan!.id,icon:ClipboardCheck};
 if(planCurrent&&plan!.status==='rejected')next={step:'03',title:copy('Алдыңғы жоспар қабылданбады','Предыдущий план отклонён'),body:copy('Шарттарды өзгертіп, жаңа есептеу жасаңыз. Алдыңғы шешім тарихта сақталады.','Измените условия и создайте новый расчёт. Прежнее решение останется в истории.'),label:copy('Жаңа жоспарды есептеу','Рассчитать новый план'),url:'/procurement?forecast='+encodeURIComponent(forecast.id),icon:ShoppingBasket};
 if(!canOperate)next={step:'↗',title:copy('Бөлімшенің нәтижелерін қараңыз','Посмотрите результаты филиала'),body:t('readOnlyPlanning'),label:t('forecasts'),url:'/forecasts',icon:TrendingUp};
 const NextIcon=next.icon,warnings:Row[]=d.warnings||[];
 const warningText=(w:Row)=>typeof w==='string'?w:w.code==='EXPIRED_LOTS'?`${t('expired')}: ${w.count}`:w.code==='EXPIRING_LOTS'?`${t('soon')}: ${w.count}`:t('error_'+w.code)!=='error_'+w.code?t('error_'+w.code):w.message||w.code;
 return <>
  <Heading title={t('overview')} sub={copy('Не болып жатыр. Келесі қадам қандай.','Что происходит. Что делать дальше.')} action={c.dataContext?.dates_editable&&<label className="dashboard-date">{t('inventoryDate')}<select value={c.inventoryDate} onChange={event=>c.setInventoryDate(event.target.value)}>{!c.inventoryDate&&<option value="">{t('snapshotMissing')}</option>}{c.dataContext.inventory_dates.map(value=><option key={value} value={value}>{date(value)}</option>)}</select></label>}/>
  <div className="context-line"><span><CalendarDays size={15}/>{t('targetDate')}: {date(target)}</span><span className="context-tag">{branchName||t('branch')+' '+branch} · {d.data_origin??c.dataContext?.data_origin??'—'}</span></div>
  <DataState state={state} t={t} retry={refresh}>
   <div className="dashboard-lead">
    <section className="next-action" aria-labelledby="next-action-title">
     <div className="next-action-top"><span className="eyebrow">{copy('КЕЛЕСІ ҚАДАМ','СЛЕДУЮЩИЙ ШАГ')}</span><span className="step-number">{next.step}</span></div>
     <h2 id="next-action-title">{next.title}</h2><p>{next.body}</p>
     <Button onClick={()=>go(next.url)}><NextIcon size={19}/>{next.label}<ArrowRight size={18}/></Button>
     <div className="next-action-foot">{copy('Соңғы шешімді адам қабылдайды.','Последнее решение принимает человек.')}</div>
    </section>
    <section className="readiness-journal" aria-labelledby="readiness-title">
     <span className="eyebrow">{copy('ЕСЕПТЕУГЕ НЕ БАР','НА ЧЁМ СТРОИТСЯ РАСЧЁТ')}</span><h2 id="readiness-title">{copy('Деректер жағдайы','Состояние данных')}</h2>
     {[
      {key:'sales',title:t('sales'),detail:hasSales?t('lastdata')+': '+date(d.as_of):t('noSalesHistory')},
      {key:'forecasts',title:t('forecast'),detail:forecast?date(forecast.target_date)+(forecast.input_freshness==='changed'?' · '+copy('деректер өзгерді','данные изменились'):forecast.input_freshness==='unchanged'?'':' · '+copy('өзектілігін тексеріңіз','проверьте актуальность')):copy('Әлі есептелмеген','Ещё не рассчитан')},
      {key:'inventory',title:t('inventory'),detail:d.inventory_known?t('snapshot')+': '+date(d.inventory_date):t('snapshotMissing')},
     ].map(row=><button className="readiness-row" key={row.key} onClick={()=>go('/'+row.key)}><span><strong>{row.title}</strong><small>{row.detail}</small></span><ArrowUpRight size={17}/></button>)}
     <p>{copy('Кесіндінің болуы барлық ингредиенттің толық екенін білдірмейді.','Наличие среза ещё не означает, что в нём есть все ингредиенты.')}</p>
    </section>
   </div>
   <div className="metrics metric-strip" aria-label={copy('Соңғы белгілі көрсеткіштер','Последние известные показатели')}>
    <Metric label={t('portions')} value={fmt(hasSales?d.sold_portions:null)} caption={salesCaption} icon={ShoppingBasket}/>
    <Metric label={t('revenue')} value={money(hasSales?d.revenue:null)} caption={salesCaption} icon={TrendingUp}/>
    <Metric label={t('shortages')} value={fmt(d.total_shortages)} caption={d.total_shortages==null?t('planAbsent'):date(plans[0]?.target_date)+' · '+t('requirements')} icon={AlertTriangle} tone="amber"/>
    <Metric label={t('purchaseCost')} value={money(d.procurement_cost)} caption={d.procurement_cost==null?t('planAbsent'):copy('Соңғы жоспар','Последний план')+' · '+date(plans[0]?.target_date)} icon={Package}/>
   </div>
   <div className="dashboard-grid">
    <section className="panel chart-panel"><div className="panel-heading"><div><h2>{t('salesDynamics')}</h2><p>{copy('Деректері бар соңғы 28 күн · порция','Последние 28 дней с данными · порции')}</p></div><button className="text-button" onClick={()=>go('/sales')}>{t('sales')}<ArrowUpRight size={16}/></button></div>{history.length?<SalesChart history={history} t={t}/>:<Empty t={t}/>}</section>
    <section className="attention-panel"><div className="panel-heading"><h2>{t('attention')}</h2><span className="count-badge">{warnings.length}</span></div><div className="attention-list">
     {warnings.map((w,i)=><div className="attention-item" key={i}><AlertTriangle size={19}/><div><strong>{warningText(w)}</strong><button className="text-button" onClick={()=>go('/inventory')}>{t('inventory')}<ArrowRight size={15}/></button></div></div>)}
     {!warnings.length&&<p className="attention-empty">{copy('Қор кесіндісі бойынша ескертулер жоқ. Деректердің толықтығы есептеу кезінде бөлек тексеріледі.','По срезу остатков предупреждений нет. Полнота данных проверяется отдельно при расчёте.')}</p>}
     <p className="attention-date">{t('inventoryDate')}: <strong>{date(d.inventory_date)}</strong></p>
    </div></section>
   </div>
   <div className="dashboard-grid lower">
    <section className="panel"><div className="panel-heading"><div><h2>{t('topMeals')}</h2><p>{salesCaption}</p></div><button className="text-button" onClick={()=>go('/sales')}>{t('viewAll')}<ArrowUpRight size={16}/></button></div><Table t={t} rows={(d.top_meals||[]).slice(0,5)} columns={[{key:'meal_name',label:t('meal'),render:r=><span className="meal-cell"><BookOpen size={16}/><strong>{name(r.meal_name||r.meal_id)}</strong></span>},{key:'units_sold',label:t('sold'),numeric:true,render:r=><strong>{fmt(r.units_sold)}</strong>},{key:'revenue',label:t('revenue'),numeric:true,render:r=>money(r.revenue)}]}/></section>
    <section className="plans-journal"><div className="panel-heading"><h2>{t('recentPlans')}</h2><button className="icon-button" title={t('purchase')} onClick={()=>go('/procurement')}><ArrowUpRight size={18}/></button></div>{plans.length?<div className="plan-cards">{plans.slice(0,3).map(p=><button key={p.id} className="mini-plan" onClick={()=>go('/procurement/'+p.id)}><span><strong>{date(p.target_date)}</strong><small>{t('version')} {p.version}</small></span><span className="mini-plan-right"><strong>{money(p.total_cost)}</strong><Badge tone={p.status==='approved'?'green':p.status==='rejected'?'red':'amber'}>{t(p.status)}</Badge></span><ArrowUpRight size={16}/></button>)}</div>:<div className="plan-empty"><ClipboardCheck size={28}/><strong>{t('planAbsent')}</strong><p>{copy('Жоспар осында сақталады: болжам → қажеттілік → сіздің шешіміңіз.','Здесь будет сохранён план: прогноз → потребность → ваше решение.')}</p></div>}</section>
   </div>
  </DataState>
 </>;
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
