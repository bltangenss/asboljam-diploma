import {Table,date,type Row} from './shared';

type Inventory={required_snapshot_date?:string;available_snapshot_dates?:string[];missing_count?:number;missing_ingredients?:Row[]};
type Props={code?:string;details?:Record<string,unknown>;t:(key:string)=>string};

// Explains STALE_INVENTORY and INVENTORY_COVERAGE_REQUIRED refusals. An absent count row is
// never shown as zero; the operator is asked for an explicit counted value instead.
export default function InventoryCoverage({code,details,t}:Props){
 const inventory=details?.inventory as Inventory|undefined;
 if(!inventory?.required_snapshot_date)return null;
 const fill=(key:string,values:Record<string,string>)=>Object.entries(values).reduce((text,[name,value])=>text.split('{'+name+'}').join(value),t(key));
 const required=date(inventory.required_snapshot_date);
 if(code==='STALE_INVENTORY'){
  const dates=Array.isArray(inventory.available_snapshot_dates)?inventory.available_snapshot_dates:[];
  return <section className="panel" aria-label={t('inventoryCoverageTitle')}>
   <div className="panel-heading"><div><h2>{t('inventoryCoverageTitle')}</h2><p>{fill('inventorySnapshotNeeded',{date:required})}</p></div></div>
   <p className="form-note">{dates.length?fill('inventorySnapshotAvailable',{dates:dates.map(date).join(', ')}):t('inventorySnapshotNone')}</p>
  </section>;
 }
 const missing=Array.isArray(inventory.missing_ingredients)?inventory.missing_ingredients:[];
 if(code!=='INVENTORY_COVERAGE_REQUIRED'||!missing.length)return null;
 return <section className="panel" aria-label={t('inventoryCoverageTitle')}>
  <div className="panel-heading"><div><h2>{t('inventoryCoverageTitle')}</h2><p>{fill('inventoryMissingHint',{date:required})}</p></div></div>
  {(inventory.missing_count||0)>missing.length&&<p className="form-note">{fill('inventoryMissingMore',{shown:String(missing.length),total:String(inventory.missing_count)})}</p>}
  <Table t={t} rows={missing} columns={[
   {key:'ingredient',label:t('ingredient'),render:row=>row.ingredient_name?`${row.ingredient_name} (${row.ingredient_id})`:String(row.ingredient_id)},
   {key:'unit',label:t('unit'),render:row=>row.unit||'—'},
   {key:'meals',label:t('inventoryNeededFor'),render:row=>(Array.isArray(row.meals)?row.meals:[]).map((meal:Row)=>meal.meal_name||meal.meal_id).join(', ')||'—'},
  ]}/>
 </section>;
}
