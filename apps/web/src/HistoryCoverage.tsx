import {ArrowRight,CalendarClock} from 'lucide-react';
import {Table,date,type Row,type Lang} from './shared';
import './import-ui.css';

type Coverage={origin?:string;required_days?:number;ready_meals?:number;meals?:Row[]};
type Props={details?:Record<string,unknown>;t:(key:string)=>string;lang?:Lang;go?:(path:string)=>void;importUrl?:string};

// Explains a DATA_HISTORY_INCOMPLETE refusal per meal. Missing days are shown as missing;
// the page never offers to fill them with zero or to exclude a meal silently.
export default function HistoryCoverage({details,t,lang,go,importUrl}:Props){
 const destination=importUrl||'/imports?kind=daily_sales';
 const kk=lang?lang==='kk':t('date')==='Күн';
 const coverage=details?.coverage as Coverage|undefined;
 const meals=Array.isArray(coverage?.meals)?coverage!.meals:[];
 const blocked=meals.filter(meal=>meal.status!=='ready');
 if(!coverage||!blocked.length)return null;
 const required=String(coverage.required_days??84);
 const fill=(key:string,values:Record<string,string>)=>Object.entries(values).reduce((text,[name,value])=>text.split('{'+name+'}').join(value),t(key));
 return <section className="panel coverage-guide" aria-label={t('historyCoverageTitle')}>
  <div className="panel-heading"><CalendarClock size={25} aria-hidden="true"/><div><h2>{t('historyCoverageTitle')}</h2>
   <p>{fill('historyCoverageHint',{days:required,origin:date(coverage.origin)})}</p></div></div>
  <div className="coverage-summary"><strong>{fill('historyCoverageReady',{ready:String(coverage.ready_meals??0),total:String(meals.length)})}</strong><p>{kk?'Төмендегі күндерді бастапқы сатылым дерегімен толықтырыңыз. Жоқ күндер нөлге ауыстырылмайды.':'Дополните указанные дни по исходным данным продаж. Пропущенные дни не заменяются нулями.'}</p></div>
  <Table t={t} rows={blocked} columns={[
   {key:'meal',label:t('historyMeal'),render:row=>row.meal_name?`${row.meal_name} (${row.meal_id})`:String(row.meal_id)},
   {key:'status',label:t('historyProblem'),render:row=>t('historyStatus_'+row.status)},
   {key:'continuous',label:t('historyContinuous'),numeric:true,render:row=>`${row.continuous_days_through_origin} / ${required}`},
   {key:'first_missing_date',label:t('historyFirstMissing'),render:row=>row.first_missing_date?date(row.first_missing_date):'—'},
   {key:'range',label:t('historyObserved'),render:row=>`${date(row.first_date)} — ${date(row.last_date)}`},
  ]}/>
  <div className="coverage-next-step"><p>{kk?'Сатылым тарихын түзеткен соң болжамды қайта іске қосыңыз.':'После исправления истории продаж запустите прогноз повторно.'}</p><a className="button secondary" href={destination} onClick={event=>{if(go){event.preventDefault();go(destination)}}}>{kk?'Сатылым CSV файлына өту':'Перейти к CSV продаж'}<ArrowRight size={16}/></a></div>
 </section>;
}
