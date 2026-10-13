import {useEffect,useRef,useState} from 'react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,name} from './shared';
import {stockText} from './stockCopy';

type RecipeRow={ingredient_id:string;net_qty_per_portion:string};
type Props={context:Context;catalog:Row;disabled:boolean;revision:number;onChanged:()=>void;onLockChange:(value:boolean)=>void};
export default function StockRecipes({context:c,catalog,disabled,revision,onChanged,onLockChange}:Props){
 const s=stockText(c.lang),t=c.t,canWrite=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user?.role);
 const [meal,setMeal]=useState(''),[version,setVersion]=useState(''),[effective,setEffective]=useState(c.inventoryDate||c.dataContext?.target_date||''),[reason,setReason]=useState('');
 const [rows,setRows]=useState<RecipeRow[]>([{ingredient_id:'',net_qty_per_portion:''}]),[history,setHistory]=useState<Row|null>(null),[readError,setReadError]=useState(''),[refresh,setRefresh]=useState(0),[loading,setLoading]=useState(true),[offset,setOffset]=useState(0);
 const [preview,setPreview]=useState<{response:Row;body:Row;key:string}|null>(null),[reviewed,setReviewed]=useState(false),[uncertain,setUncertain]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[done,setDone]=useState(false);
 const generation=useRef(0),mounted=useRef(true),pending=useRef(false),attempted=useRef(false);
 const locked=disabled||busy||uncertain,ingredients:Row[]=catalog.ingredients||[],meals:Row[]=catalog.meals||[];
 const latest=(history?.items||[]).filter((row:Row)=>row.meal_id===meal).sort((a:Row,b:Row)=>b.version-a.version)[0];
 const contextKey=JSON.stringify([c.user?.role,c.dataContext?.source,c.dataContext?.data_origin,c.dataContext?.usage_mode]);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++generation.current}},[]);
 useEffect(()=>{onLockChange(busy||uncertain);return()=>onLockChange(false)},[busy,uncertain,onLockChange]);
 useEffect(()=>{++generation.current;pending.current=false;setBusy(false);if(!attempted.current){setPreview(null);setReviewed(false)}else setUncertain(true)},[contextKey,revision,c.revision]);
 useEffect(()=>{
  let current=true;const csrf=api.csrf;setLoading(true);setReadError('');
  // Filter the selected meal so the latest version is never inferred from a truncated branch page.
  api.request(`/stock/recipes?branch_id=${encodeURIComponent(c.branch)}&limit=20&offset=${offset}${meal?'&meal_id='+encodeURIComponent(meal):''}`)
   .then(data=>{if(current&&csrf===api.csrf)setHistory(data)}).catch(error=>{if(current&&csrf===api.csrf)setReadError(explain(error))})
   .finally(()=>{if(current&&csrf===api.csrf)setLoading(false)});
  return()=>{current=false};
 },[c.branch,meal,offset,refresh,revision,c.revision,contextKey]);
 useEffect(()=>{if(!uncertain)return;const prevent=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent)},[uncertain]);
 function explain(value:unknown){if(value instanceof ApiError){const known=s(value.code);if(known!==value.code)return known;if(value.status===409)return s('conflict');if(value.status===403)return s('forbidden');if(value.status===0)return t('offline');return `${s('failed')} (${value.code})`}return s('failed')}
 function reset(){++generation.current;setPreview(null);setReviewed(false);setError('');setDone(false)}
 function edit(change:()=>void){if(locked)return;reset();change()}
 function begin(){pending.current=true;setBusy(true);const id=++generation.current,csrf=api.csrf;return()=>mounted.current&&generation.current===id&&csrf===api.csrf}
 function finish(current:()=>boolean){if(current()){pending.current=false;setBusy(false)}}
 async function validate(){
  if(locked||pending.current||!canWrite||!c.online||loading||readError||offset)return;reset();
  if(!meal||!version.trim()||!/^\d{4}-\d{2}-\d{2}$/.test(effective)||reason.trim().length<3||rows.some(row=>!row.ingredient_id||!/^\d+(?:\.\d{1,9})?$/.test(row.net_qty_per_portion)||!/[1-9]/.test(row.net_qty_per_portion))||new Set(rows.map(row=>row.ingredient_id)).size!==rows.length){setError(s('required'));return}
  const body={branch_id:c.branch,meal_id:meal,recipe_version:version,effective_date:effective,expected_version:latest?.version||0,reason:reason.trim(),rows},current=begin();
  try{const response=await api.post('/stock/recipes/preview',body);if(current())setPreview({response,body,key:crypto.randomUUID()})}catch(error){if(current()){setError(explain(error));if(error instanceof ApiError&&error.status===409)setRefresh(value=>value+1)}}finally{finish(current)}
 }
 async function post(){
  if(!preview||!reviewed||pending.current||disabled||!canWrite||!c.online)return;
  const frozen=preview,current=begin();attempted.current=true;setError('');
  try{await api.post('/stock/recipes',{...frozen.body,expected_fingerprint:frozen.response.preview_fingerprint},{'Idempotency-Key':frozen.key});if(current()){attempted.current=false;setUncertain(false);setPreview(null);setReviewed(false);setDone(true);setVersion('');setReason('');setRefresh(value=>value+1);onChanged()}}
  catch(error){if(current()){if(!(error instanceof ApiError)||error.status===0||error.status>=500){setUncertain(true);setError(s('uncertain'))}else{attempted.current=false;setUncertain(false);setPreview(null);setReviewed(false);setError(explain(error));if(error.status===409)setRefresh(value=>value+1)}}}finally{finish(current)}
 }
 const recipeTable=(items:Row[])=><div className="stock-table"><table><thead><tr>{[t('ingredient'),s('netQuantity'),t('unit'),t('yield')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{items.map((row,index)=><tr key={index}><td>{name(ingredients.find(item=>item.ingredient_id===row.ingredient_id)?.ingredient_name||row.ingredient_id)}</td><td>{row.net_qty_per_portion}</td><td>{row.unit}</td><td>{row.captured_yield_factor}</td></tr>)}</tbody></table></div>;
 return <details className="panel stock-body stock-configuration" id="stock-active-recipes"><summary>{s('recipes')}</summary><p className="stock-help">{s('recipesHint')}</p>{!canWrite&&<p className="alert info">{s('recipeReadOnly')}</p>}{readError&&<div className="alert danger" role="alert">{readError}<button className="text-button" disabled={locked} onClick={()=>setRefresh(value=>value+1)}>{s('refresh')}</button></div>}{error&&<div className="alert danger" role="alert">{error}</div>}{done&&<div className="alert success" role="status">{s('recipeDone')}</div>}
  <div className="stock-fields"><label>{t('meal')}<select aria-label={t('meal')} value={meal} disabled={locked} onChange={event=>edit(()=>{setMeal(event.target.value);setOffset(0)})}><option value="">{s('chooseMeal')}</option>{meals.map(item=><option key={item.meal_id} value={item.meal_id}>{name(item.meal_name||item.meal_id)}</option>)}</select></label></div>
  {canWrite&&<form className="stock-form" onSubmit={event=>{event.preventDefault();void validate()}}><fieldset disabled={locked||loading||Boolean(readError)||offset>0}><p className="stock-help">{s('recipeCurrent')}: {latest?`${latest.recipe_version} · ${date(latest.effective_date)}`:'—'}</p><div className="stock-fields"><label>{s('recipeVersion')}<input maxLength={255} value={version} onChange={event=>edit(()=>setVersion(event.target.value))}/></label><label>{s('effectiveDate')}<input type="date" value={effective} onChange={event=>edit(()=>setEffective(event.target.value))}/></label><label className="stock-wide">{s('reason')}<input value={reason} minLength={3} maxLength={1000} onChange={event=>edit(()=>setReason(event.target.value))}/></label></div>
   {rows.map((row,index)=><fieldset className="stock-line" key={index}><legend>{s('row')} {index+1}</legend><div className="stock-fields"><label>{t('ingredient')} {index+1}<select aria-label={`${t('ingredient')} ${index+1}`} value={row.ingredient_id} onChange={event=>edit(()=>setRows(current=>current.map((value,i)=>i===index?{...value,ingredient_id:event.target.value}:value)))}><option value="">{s('chooseIngredient')}</option>{ingredients.map(item=><option key={item.ingredient_id} value={item.ingredient_id}>{name(item.ingredient_name||item.ingredient_id)}</option>)}</select></label><label>{s('netQuantity')} {index+1}<input inputMode="decimal" value={row.net_qty_per_portion} onChange={event=>edit(()=>setRows(current=>current.map((value,i)=>i===index?{...value,net_qty_per_portion:event.target.value}:value)))}/></label></div>{rows.length>1&&<button type="button" className="text-button" onClick={()=>edit(()=>setRows(current=>current.filter((_,i)=>i!==index)))}>{s('removeLine')} {index+1}</button>}</fieldset>)}<div className="stock-actions"><button type="button" className="button secondary" disabled={rows.length>=500} onClick={()=>edit(()=>setRows(current=>[...current,{ingredient_id:'',net_qty_per_portion:''}]))}>{s('addLine')}</button><button className="button primary" disabled={!c.online}>{s('recipePreview')}</button></div>
  </fieldset></form>}
  {preview&&<section className="panel stock-body stock-preview" aria-label={s('recipePreview')}><h3>{s('recipePreview')}</h3><p className="stock-meta">{preview.body.recipe_version} · {date(preview.body.effective_date)} · {preview.body.reason}</p>{recipeTable(preview.response.rows||[])}<label className="checkbox-label"><input type="checkbox" checked={reviewed} disabled={locked} onChange={event=>setReviewed(event.target.checked)}/>{s('recipeComplete')}</label><div className="stock-actions"><button className="button primary" disabled={!reviewed||busy||disabled||!canWrite||!c.online} onClick={()=>void post()}>{s(uncertain?'retryPost':'recipeActivate')}</button>{!uncertain&&<button className="button secondary" disabled={locked} onClick={reset}>{s('cancelPreview')}</button>}</div></section>}
  <h3>{s('recipeHistory')}</h3>{loading?<p role="status">{s('loading')}</p>:history?.items?.length?<>{history.items.map((item:Row)=><details key={item.id}><summary>{name(meals.find(meal=>meal.meal_id===item.meal_id)?.meal_name||item.meal_id)} · {item.recipe_version} · {date(item.effective_date)}</summary><p className="stock-help">{item.reason}</p>{recipeTable(item.rows||[])}</details>)}<p className="stock-help">{history.items.length} / {history.total}</p></>:<p className="stock-empty">{s('recipeEmpty')}</p>}
 <div className="stock-actions"><button className="button secondary" disabled={locked||!offset} onClick={()=>edit(()=>setOffset(0))}>{s('previous')}</button><button className="button secondary" disabled={locked||loading||!history||offset+(history.items?.length||0)>=history.total} onClick={()=>edit(()=>setOffset(offset+20))}>{s('next')}</button></div></details>;
}
