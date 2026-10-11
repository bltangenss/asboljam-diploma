import {Table,date,type Row} from './shared';

type Coverage={origin?:string;required_days?:number;ready_meals?:number;meals?:Row[]};
type Props={details?:Record<string,unknown>;t:(key:string)=>string};

// Explains a DATA_HISTORY_INCOMPLETE refusal per meal. Missing days are shown as missing;
// the page never offers to fill them with zero or to exclude a meal silently.
export default function HistoryCoverage({details,t}:Props){
 const coverage=details?.coverage as Coverage|undefined;
 const meals=Array.isArray(coverage?.meals)?coverage!.meals:[];
 const blocked=meals.filter(meal=>meal.status!=='ready');
 if(!coverage||!blocked.length)return null;
 const required=String(coverage.required_days??84);
 const fill=(key:string,values:Record<string,string>)=>Object.entries(values).reduce((text,[name,value])=>text.split('{'+name+'}').join(value),t(key));
 return <section className="panel" aria-label={t('historyCoverageTitle')}>
  <div className="panel-heading"><div><h2>{t('historyCoverageTitle')}</h2>
   <p>{fill('historyCoverageHint',{days:required,origin:date(coverage.origin)})}</p></div></div>
  <p className="form-note">{fill('historyCoverageReady',{ready:String(coverage.ready_meals??0),total:String(meals.length)})}</p>
  <Table t={t} rows={blocked} columns={[
   {key:'meal',label:t('historyMeal'),render:row=>row.meal_name?`${row.meal_name} (${row.meal_id})`:String(row.meal_id)},
   {key:'status',label:t('historyProblem'),render:row=>t('historyStatus_'+row.status)},
   {key:'continuous',label:t('historyContinuous'),numeric:true,render:row=>`${row.continuous_days_through_origin} / ${required}`},
   {key:'first_missing_date',label:t('historyFirstMissing'),render:row=>row.first_missing_date?date(row.first_missing_date):'—'},
   {key:'range',label:t('historyObserved'),render:row=>`${date(row.first_date)} — ${date(row.last_date)}`},
  ]}/>
 </section>;
}
