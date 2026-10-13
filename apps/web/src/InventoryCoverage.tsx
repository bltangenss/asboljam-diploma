import {ArrowRight,PackageSearch} from 'lucide-react';
import {Table,date,type Row,type Lang} from './shared';
import './import-ui.css';

type Inventory={required_snapshot_date?:string;available_snapshot_dates?:string[];missing_count?:number;missing_ingredients?:Row[]};
type Props={code?:string;details?:Record<string,unknown>;t:(key:string)=>string;lang?:Lang;go?:(path:string)=>void};

// Explains STALE_INVENTORY and INVENTORY_COVERAGE_REQUIRED refusals. An absent count row is
// never shown as zero; the operator is asked for an explicit counted value instead.
export default function InventoryCoverage({code,details,t,lang,go}:Props){
 const kk=lang?lang==='kk':t('date')==='Күн';
 const inventory=details?.inventory as Inventory|undefined;
 if(!inventory?.required_snapshot_date)return null;
 const fill=(key:string,values:Record<string,string>)=>Object.entries(values).reduce((text,[name,value])=>text.split('{'+name+'}').join(value),t(key));
 const required=date(inventory.required_snapshot_date);
 const nextStep=<div className="coverage-next-step"><p>{kk?'Нақты саналған мәнді енгізіңіз. Ингредиент жоқ болса, оның қалдығын 0 деп анық көрсетіңіз.':'Укажите фактически пересчитанные значения. Если ингредиента нет, явно запишите остаток 0.'}</p><a className="button secondary" href="/imports?kind=inventory_lots" onClick={event=>{if(go){event.preventDefault();go('/imports?kind=inventory_lots')}}}>{kk?'Қалдықтар CSV файлына өту':'Перейти к CSV остатков'}<ArrowRight size={16}/></a></div>;
 if(code==='STALE_INVENTORY'){
  const dates=Array.isArray(inventory.available_snapshot_dates)?inventory.available_snapshot_dates:[];
  return <section className="panel coverage-guide" aria-label={t('inventoryCoverageTitle')}>
   <div className="panel-heading"><PackageSearch size={25} aria-hidden="true"/><div><h2>{t('inventoryCoverageTitle')}</h2><p>{fill('inventorySnapshotNeeded',{date:required})}</p></div></div>
   <p className="coverage-summary">{dates.length?fill('inventorySnapshotAvailable',{dates:dates.map(date).join(', ')}):t('inventorySnapshotNone')}</p>
   {nextStep}
  </section>;
 }
 const missing=Array.isArray(inventory.missing_ingredients)?inventory.missing_ingredients:[];
 if(code!=='INVENTORY_COVERAGE_REQUIRED'||!missing.length)return null;
 return <section className="panel coverage-guide" aria-label={t('inventoryCoverageTitle')}>
  <div className="panel-heading"><PackageSearch size={25} aria-hidden="true"/><div><h2>{t('inventoryCoverageTitle')}</h2><p>{fill('inventoryMissingHint',{date:required})}</p></div></div>
  {(inventory.missing_count||0)>missing.length&&<p className="form-note">{fill('inventoryMissingMore',{shown:String(missing.length),total:String(inventory.missing_count)})}</p>}
  <Table t={t} rows={missing} columns={[
   {key:'ingredient',label:t('ingredient'),render:row=>row.ingredient_name?`${row.ingredient_name} (${row.ingredient_id})`:String(row.ingredient_id)},
   {key:'unit',label:t('unit'),render:row=>row.unit||'—'},
   {key:'meals',label:t('inventoryNeededFor'),render:row=>(Array.isArray(row.meals)?row.meals:[]).map((meal:Row)=>meal.meal_name||meal.meal_id).join(', ')||'—'},
  ]}/>
  {nextStep}
 </section>;
}
