import {useId,useState} from 'react';
import {type Row,useData,items,name,fmt,date,shiftDate,DataState,Empty} from './shared';

type Props={result:any;branch:string;t:(key:string)=>string;lang:'kk'|'ru';meals:Row[]};
const DAY=86400000;
const time=(value:string)=>Date.parse(value+'T00:00:00Z');
const iso=(value:number)=>new Date(value).toISOString().slice(0,10);
const number=(value:unknown):number|null=>value===null||value===undefined||value===''?null:Number.isFinite(Number(value))&&Number(value)>=0?Number(value):null;

/** Actual dates/amounts are loaded from the sales API; intervals come only from the stored forecast. */
export default function ForecastChart({result,branch,t,lang,meals}:Props){
  const[selection,setSelection]=useState('');
  const predictions:Row[]=Array.isArray(result.predictions)?result.predictions:[];
  const chosen=predictions.find(row=>String(row.meal_id)===selection)||predictions[0];
  const origin=String(result.forecast_origin||result.origin||result.metadata?.forecast_origin||result.metadata?.history_end||'');
  const knownDates=Boolean(origin&&result.target_date&&shiftDate(origin,0)===origin&&shiftDate(String(result.target_date),0)===String(result.target_date));
  const mealName=(id:string)=>name(meals.find(row=>String(row.meal_id)===id)?.meal_name||predictions.find(row=>String(row.meal_id)===id)?.meal_name||id);
  return <section className="panel forecast-history-panel">
    <div className="panel-heading" style={{flexWrap:'wrap'}}><div><h2>{lang==='kk'?'Сатылым тарихы және келесі күн':'История продаж и следующий день'}</h2><p>{lang==='kk'?'Күн бойынша · порция':'По датам · порции'}</p></div>
      {chosen&&<label style={{minWidth:190,maxWidth:'100%'}}>{t('meal')}<select aria-label={lang==='kk'?'Графиктегі тағам':'Блюдо на графике'} value={String(chosen.meal_id)} onChange={event=>setSelection(event.target.value)}>{predictions.map(row=><option key={row.meal_id} value={String(row.meal_id)}>{mealName(String(row.meal_id))}</option>)}</select></label>}
    </div>
    {chosen?knownDates?<Series key={`${result.id||result.model}-${result.target_date}-${chosen.meal_id}-${branch}`} result={result} branch={branch} prediction={chosen} mealName={mealName(String(chosen.meal_id))} t={t} lang={lang}/>:<div className="alert info">{t('forecastOriginUnknown')}</div>:<Empty t={t}/>}
  </section>;
}

function Series({result,branch,prediction,mealName,t,lang}:Omit<Props,'meals'>&{prediction:Row;mealName:string}){
  const id=useId(),[revision,setRevision]=useState(0),[description,setDescription]=useState('');
  const origin=String(result.forecast_origin||result.origin||result.metadata?.forecast_origin||result.metadata?.history_end),end=time(origin),start=end-27*DAY;
  const targetDate=String(result.target_date),target=time(targetDate),branchId=String(result.branch_id||branch),mealId=String(prediction.meal_id);
  const query=new URLSearchParams({branch_id:branchId,date_from:iso(start),date_to:origin,meal_id:mealId,limit:'200',cursor:'0'});
  const state=useData('/sales?'+query.toString(),revision);
  const actual=items(state.data).filter(row=>String(row.branch_id)===branchId&&String(row.meal_id)===mealId&&number(row.units_sold)!==null&&time(String(row.date))>=start&&time(String(row.date))<=end).map(row=>({date:String(row.date),value:number(row.units_sold)!})).sort((a,b)=>a.date.localeCompare(b.date));
  const p10=number(prediction.p10),p50=number(prediction.p50),p90=number(prediction.p90),point=number(prediction.point_forecast);
  const interval=p10!==null&&p50!==null&&p90!==null&&p10<=p50&&p50<=p90;
  const predicted=interval?p50:point,observedLabel=lang==='kk'?'Бақыланған сатылым':'Наблюдаемые продажи';
  const forecastLabel=interval?`${t('forecast')} · p50`:t('point'),units=lang==='kk'?'порция':'порций';
  const forecastDescription=`${date(targetDate)} · ${mealName} · ${result.model} · ${forecastLabel}: ${fmt(predicted,2)} ${units}`+(interval?` · p10: ${fmt(p10,2)}, p90: ${fmt(p90,2)} ${units} · ${t('point')}: ${fmt(point,2)} ${units}`:` · ${t('noInterval')}`);
  const width=920,height=330,left=62,right=34,top=34,bottom=274;
  const ceiling=Math.ceil(Math.max(1,...actual.map(row=>row.value),predicted||0,interval?p90!:0)/5)*5;
  const x=(day:number)=>left+(day-start)/Math.max(DAY,target+DAY*.65-start)*(width-left-right);
  const y=(value:number)=>bottom-value/ceiling*(bottom-top);
  let previous:number|null=null;
  const path=actual.map(row=>{const day=time(row.date),command=previous!==null&&day-previous===DAY?'L':'M';previous=day;return`${command}${x(day)},${y(row.value)}`}).join(' ');
  const boundary=x(end+DAY/2),ticks=[start,start+7*DAY,start+14*DAY,start+21*DAY,target];
  return <DataState state={state} t={t} retry={()=>setRevision(value=>value+1)}>
    <div style={{display:'flex',gap:20,flexWrap:'wrap',padding:'0 23px 16px',fontSize:12,color:'#435e4d'}}>
      <span>● ━ {observedLabel}</span><span style={{color:'#916722'}}>◆ {forecastLabel}</span>{interval&&<span>▥ p10–p90 · 80%</span>}
    </div>
    <div className="table-scroll" role="region" tabIndex={0} aria-label={lang==='kk'?'Күндік болжам графигі, көлденең айналдыруға болады':'График дневного прогноза, доступна горизонтальная прокрутка'}>
      <svg data-testid="forecast-time-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${id}-title ${id}-description`} style={{display:'block',width:'100%',minWidth:740,fontSize:12,color:'#637367'}}>
        <title id={`${id}-title`}>{mealName}: {observedLabel} · {date(iso(start))}–{date(origin)}; {forecastLabel} · {date(targetDate)}</title>
        <desc id={`${id}-description`}>{lang==='kk'?'Жасыл сызық — сатылым. Жеке ромб — келесі күн болжамы. Осьтер: күн және порция. Тарих пен болжам сызықпен қосылмайды.':'Зелёная линия — продажи. Отдельный ромб — прогноз следующего дня. Оси: дата и порции. История и прогноз не соединены линией.'}</desc>
        <rect x={boundary} y={top} width={Math.max(0,width-right-boundary)} height={bottom-top} fill="#faf5e9"/>
        {Array.from({length:6},(_,index)=>{const value=ceiling*index/5;return<g key={index}><line x1={left} x2={width-right} y1={y(value)} y2={y(value)} stroke="#e3e9e5"/><text x={left-12} y={y(value)+4} textAnchor="end" fill="currentColor">{fmt(value)}</text></g>})}
        <text x={left} y="18" fill="currentColor">{units}</text><line x1={boundary} x2={boundary} y1={top} y2={bottom} stroke="#9b8457" strokeDasharray="4 5"/>
        <path d={path} fill="none" stroke="#245b47" strokeWidth="2" strokeLinejoin="round"/>
        {actual.map(row=>{const text=`${date(row.date)} · ${mealName} · ${observedLabel}: ${fmt(row.value)} ${units}`;return<circle key={row.date} data-series="observed" data-date={row.date} cx={x(time(row.date))} cy={y(row.value)} r="4" fill="#245b47" stroke="white" strokeWidth="1.2" tabIndex={0} aria-label={text} onFocus={()=>setDescription(text)} onMouseEnter={()=>setDescription(text)} onClick={()=>setDescription(text)}><title>{text}</title></circle>})}
        {interval&&<g data-testid="forecast-interval" aria-label={`${date(targetDate)} · p10–p90: ${fmt(p10,2)}–${fmt(p90,2)} ${units}`}><rect x={x(target)-9} y={y(p90!)} width="18" height={Math.max(1,y(p10!)-y(p90!))} fill="#f2dfb7"/><line x1={x(target)} x2={x(target)} y1={y(p90!)} y2={y(p10!)} stroke="#916722" strokeWidth="2"/>{[p10!,p90!].map((value,index)=><line key={index} x1={x(target)-9} x2={x(target)+9} y1={y(value)} y2={y(value)} stroke="#916722" strokeWidth="2"/>)}<title>{forecastDescription} · {t('interval')}</title></g>}
        {predicted!==null&&<path data-testid="forecast-target-point" data-date={targetDate} d={`M${x(target)} ${y(predicted)-7}l7 7-7 7-7-7Z`} fill="#916722" stroke="white" strokeWidth="1.4" tabIndex={0} aria-label={forecastDescription} onFocus={()=>setDescription(forecastDescription)} onMouseEnter={()=>setDescription(forecastDescription)} onClick={()=>setDescription(forecastDescription)}><title>{forecastDescription}</title></path>}
        {ticks.map(day=><text key={day} x={x(day)} y={bottom+26} textAnchor="middle" fill="currentColor">{date(iso(day)).slice(0,5)}</text>)}<text x={width-right} y={height-6} textAnchor="end" fill="currentColor">{t('date')}</text>
      </svg>
    </div>
    <div style={{padding:'4px 23px 20px',fontSize:12,lineHeight:1.7,color:'#526359'}}><p role="status" aria-live="polite" style={{minHeight:42}}>{description||forecastDescription}</p><p>{interval?t('interval'):t('noInterval')}. {lang==='kk'?'Тарих пен болжам бөлек көрсетілген.':'История и прогноз показаны отдельно.'}</p>{actual.length!==28&&<p>{lang==='kk'?`Тарихта ${actual.length}/28 күн бар. Жоқ жазбалар нөлмен алмастырылмайды.`:`В истории ${actual.length}/28 дней. Пропущенные записи не заменяются нулями.`}</p>}</div>
  </DataState>;
}
