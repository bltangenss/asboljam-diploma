import {ArrowRight,CalendarDays,CloudSun,Footprints,GraduationCap,Moon,Store,Wallet} from 'lucide-react';
import {type Context,type Row,DataState,date,fmt,items,useData} from './shared';
import {CityWeather,FactorAutofill,useBranchCity} from './FactorAutofill';

// The twenty day factors: what each branch has imported, and what a forecast actually used.
const groups:Record<string,{icon:any;name:[string,string]}>={
 calendar:{icon:CalendarDays,name:['Күнтізбе','Календарь']},
 culture:{icon:Moon,name:['Мереке және дін','Праздники и религия']},
 school:{icon:GraduationCap,name:['Мектеп','Школа']},
 economy:{icon:Wallet,name:['Экономика','Экономика']},
 weather:{icon:CloudSun,name:['Ауа райы','Погода']},
 traffic:{icon:Footprints,name:['Адам ағыны','Поток людей']},
 operations:{icon:Store,name:['Бөлімше жұмысы','Работа филиала']},
};
const reasons:Record<string,[string,string]>={
 no_data:['Дерек жүктелмеген','Данные не загружены'],
 no_target_value:['Болжам күніне мән жоқ','Нет значения на день прогноза'],
 low_coverage:['Оқу күндерінің 90%-ынан азы қамтылған','Покрыто меньше 90% дней обучения'],
 no_training_values:['Оқу кезеңінде мән жоқ','Нет значений в периоде обучения'],
};
const assumptions:Record<string,[string,string]>={
 TARGET_PRICE_LAST_KNOWN:['Болжам күнінің мәзір бағасы — соңғы белгілі баға.','Цена в меню на день прогноза — последняя известная.'],
 TARGET_PROMO_ASSUMED_NONE:['Болжам күніне акция жоспары жүктелмеген, сондықтан акциясыз күн деп алынды.','План акций на день прогноза не загружен, поэтому день считается без акции.'],
};

export function factorValue(factor:Row|undefined,value:unknown,kk:boolean){
 if(value===null||value===undefined||value==='')return '—';
 const number=Number(value);
 if(factor?.kind==='flag')return number?(kk?'Иә':'Да'):(kk?'Жоқ':'Нет');
 if(factor?.code?.endsWith('_minutes'))return `${String(Math.floor(number/60)).padStart(2,'0')}:${String(Math.round(number%60)).padStart(2,'0')}`;
 if(factor?.code==='temperature_forecast_c')return `${fmt(number,1)} °C`;
 if(factor?.code==='office_occupancy_pct')return `${fmt(number,0)}%`;
 return fmt(number,2);
}

export function useFactorCatalogue(c:Context){
 const target=c.dataContext?.target_date;
 return useData(c.branch?`/factors?branch_id=${encodeURIComponent(c.branch)}${target?'&target_date='+encodeURIComponent(target):''}`:null,c.revision);
}

export function FactorCatalogue(c:Context){
 const kk=c.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru;
 const state=useFactorCatalogue(c),rows=items(state.data),city=useBranchCity(c);
 const loaded=rows.filter(item=>item.origin==='day_factors'&&item.days>0).length;
 const derived=rows.filter(item=>item.origin==='daily_sales').length;
 const missing=rows.filter(item=>item.origin==='day_factors'&&!item.days).length;
 const canImport=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user.role);
 return <section className="factor-catalogue" aria-labelledby="factor-catalogue-title">
  <div className="factor-catalogue-head">
   <div><h2 id="factor-catalogue-title">{copy('Болжам факторлары · 20 датасет','Факторы прогноза · 20 датасетов')}</h2>
    <p>{copy('Сатылымнан бөлек болжамға әсер ететін, алдын ала белгілі деректер. Факторлы модель болжам күніне мәні бар және оқу күндерінің кемінде 90%-ын қамтитын факторды ғана қолданады.','Заранее известные данные, которые влияют на продажи помимо их истории. Модель с факторами берёт фактор, только если у него есть значение на день прогноза и покрыто не меньше 90% дней обучения.')}</p></div>
   {canImport&&<button className="button secondary" onClick={()=>c.go('/imports?kind=day_factors')}>{copy('Факторлар CSV жүктеу','Загрузить CSV факторов')}<ArrowRight size={16}/></button>}
  </div>
  <FactorAutofill {...c} city={city}/>
  <CityWeather {...c} city={city}/>
  <DataState state={state} t={c.t} retry={c.refresh}>
   <p className="factor-summary"><strong>{loaded}</strong> {copy('жүктелген','загружено')} · <strong>{derived}</strong> {copy('сатылым тарихынан','из истории продаж')} · <strong>{missing}</strong> {copy('деректі күтеді','ждут данных')}{state.data?.target_date&&<> · {copy('болжам күні','день прогноза')} {date(state.data.target_date)}</>}</p>
   <div className="factor-groups">{Object.entries(groups).map(([key,group])=>{const list=rows.filter(item=>item.group===key);if(!list.length)return null;const Icon=group.icon;return <section className="factor-group" key={key}>
    <h3><Icon size={16}/>{group.name[kk?0:1]}</h3>
    <ul>{list.map(item=>{const derivedItem=item.origin==='daily_sales',ready=derivedItem||item.days>0;return <li key={item.code} className={ready?'is-ready':'is-missing'}>
     <div><strong>{item.name?.[kk?'kk':'ru']}</strong><small>{item.source_hint}</small></div>
     <span className="factor-status">{derivedItem?copy('Сатылымнан','Из продаж'):item.days?<>{fmt(item.days)} {copy('күн','дн.')} · {date(item.first_date)} — {date(item.last_date)}{state.data?.target_date&&<em>{copy('Болжам күні','День прогноза')}: {factorValue(item,item.target_value,kk)}</em>}</>:copy('Дерек жоқ','Нет данных')}</span>
    </li>})}</ul>
   </section>})}</div>
  </DataState>
 </section>;
}

export function ForecastFactorDetails({meta,context}:{meta:Row;context:Context}){
 const kk=context.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru;
 const catalogue=useFactorCatalogue(context);
 const named=new Map(items(catalogue.data).map(item=>[item.code,item]));
 const label=(code:string)=>named.get(code)?.name?.[kk?'kk':'ru']||code;
 return <div className="forecast-factors">
  <h2>{copy('Болжам факторлары','Факторы прогноза')}</h2>
  <p className="reference-footnote">{copy('Факторлы модель тарихтағы сатылымға қоса осы күні алдын ала белгілі деректерді қолданады. Әр фактор оқу кезеңінде де, болжам күнінде де сол күннің мәнімен алынады.','Модель с факторами использует, кроме истории продаж, данные, известные заранее на этот день. Каждый фактор берётся со значением того же дня и в обучении, и в день прогноза.')}</p>
  <h3>{copy('Қолданылды','Использованы')} · {(meta.used||[]).length}</h3>
  <table className="factor-table"><thead><tr><th>{copy('Фактор','Фактор')}</th><th className="numeric">{copy('Болжам күні','День прогноза')}</th><th className="numeric">{copy('Қамту','Покрытие')}</th></tr></thead>
   <tbody>{(meta.used||[]).map((item:Row)=><tr key={item.code}><td>{label(item.code)}</td><td className="numeric">{factorValue(named.get(item.code),item.target_value,kk)}</td><td className="numeric">{fmt(Number(item.coverage)*100,0)}%</td></tr>)}
    {(meta.derived||[]).map((code:string)=><tr key={code}><td>{label(code)}</td><td className="numeric" colSpan={2}>{copy('сатылым тарихынан','из истории продаж')}</td></tr>)}</tbody></table>
  {!!(meta.skipped||[]).length&&<><h3>{copy('Қолданылмады','Не использованы')} · {meta.skipped.length}</h3>
   <ul className="factor-skipped">{meta.skipped.map((item:Row)=><li key={item.code}><strong>{label(item.code)}</strong><span>{reasons[item.reason]?.[kk?0:1]||item.reason}{item.reason==='low_coverage'?` · ${fmt(Number(item.coverage)*100,0)}%`:''}</span></li>)}</ul></>}
  <h3>{copy('Болжам күнінің жорамалдары','Допущения для дня прогноза')}</h3>
  <ul className="factor-assumptions">{(meta.assumptions||[]).map((code:string)=><li key={code}>{assumptions[code]?.[kk?0:1]||code}</li>)}</ul>
 </div>;
}
