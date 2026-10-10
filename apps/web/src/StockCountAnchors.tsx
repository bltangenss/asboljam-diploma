import {useEffect,useRef,useState} from 'react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,name} from './shared';
import {stockText} from './stockCopy';

type Props={context:Context;position:Row|null;catalog:Row;disabled:boolean;revision:string;onChanged:()=>void;onLockChange:(value:boolean)=>void};
type Preview={body:Row;response:Row;key:string;contextKey:string};
const validDay=/^\d{4}-\d{2}-\d{2}$/;

export default function StockCountAnchors({context:c,position,catalog,disabled,revision,onChanged,onLockChange}:Props){
 const s=stockText(c.lang),t=c.t;
 const canWrite=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user?.role);
 const [countDate,setCountDate]=useState(c.inventoryDate||c.dataContext?.inventory_date||c.dataContext?.target_date||''),[reason,setReason]=useState('');
 const [history,setHistory]=useState<Row|null>(null),[cursor,setCursor]=useState(''),[refresh,setRefresh]=useState(0),[loading,setLoading]=useState(true),[readError,setReadError]=useState('');
 const [preview,setPreview]=useState<Preview|null>(null),[reviewed,setReviewed]=useState(false),[uncertain,setUncertain]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[done,setDone]=useState(false);
 const mounted=useRef(true),generation=useRef(0),pending=useRef(false),attempted=useRef(false),seenLedger=useRef(false);
 const contextKey=JSON.stringify([c.user?.role,c.dataContext?.source,c.dataContext?.data_origin,c.dataContext?.usage_mode]);
 const locked=disabled||busy||uncertain,contextChanged=position?.context_freshness==='changed';
 const available=Boolean(position?.ledger),sourceAllowed=available&&position?.context_freshness==='unchanged';
 const ingredients:Row[]=catalog.ingredients||[];
 const ingredientName=(id:string)=>name(ingredients.find(row=>row.ingredient_id===id)?.ingredient_name||id);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++generation.current}},[]);
 useEffect(()=>{onLockChange(busy||uncertain);return()=>onLockChange(false)},[busy,uncertain,onLockChange]);
 useEffect(()=>{
  ++generation.current;pending.current=false;setBusy(false);
  if(!attempted.current){setPreview(null);setReviewed(false)}else setUncertain(true);
 },[contextKey,revision,c.revision]);
 useEffect(()=>{
  let active=true;const csrf=api.csrf;setLoading(true);setReadError('');setHistory(null);
  api.request(`/stock/count-anchors?branch_id=${encodeURIComponent(c.branch)}&limit=20&cursor=${encodeURIComponent(cursor||'0')}`)
   .then(data=>{if(active&&mounted.current&&csrf===api.csrf)setHistory(data)})
   .catch(error=>{if(active&&mounted.current&&csrf===api.csrf)setReadError(explain(error))})
   .finally(()=>{if(active&&mounted.current&&csrf===api.csrf)setLoading(false)});
  return()=>{active=false};
 },[c.branch,cursor,refresh,revision,c.revision,contextKey]);
 useEffect(()=>{
  if(!uncertain)return;
  const prevent=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};
  window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent);
 },[uncertain]);
 function explain(value:unknown){
  if(value instanceof ApiError){const known=s(value.code);if(known!==value.code)return known;if(value.status===409)return s('conflict');if(value.status===403)return s('forbidden');if(value.status===0)return t('offline');return `${s('failed')} (${value.code})`}
  return s('failed');
 }
 function reset(){++generation.current;setPreview(null);setReviewed(false);setError('');setDone(false)}
 function edit(change:()=>void){if(locked)return;reset();change()}
 function begin(){pending.current=true;setBusy(true);const sequence=++generation.current,csrf=api.csrf;return()=>mounted.current&&sequence===generation.current&&csrf===api.csrf}
 function finish(current:()=>boolean){if(current()){pending.current=false;setBusy(false)}}
 async function validate(){
  if(locked||pending.current||!canWrite||!c.online||!sourceAllowed||loading||readError)return;
  reset();if(!validDay.test(countDate)||reason.trim().length<3){setError(s('anchorRequired'));return}
  const body={branch_id:c.branch,count_date:countDate,reason:reason.trim(),expected_version:position!.version},current=begin();
  try{const response=await api.post('/stock/count-anchors/preview',body);if(current())setPreview({body,response,key:crypto.randomUUID(),contextKey})}
  catch(error){if(current()){setError(explain(error));if(error instanceof ApiError&&error.status===409)onChanged()}}
  finally{finish(current)}
 }
 async function post(){
  if(!preview||!reviewed||pending.current||disabled||!canWrite||!c.online||preview.contextKey!==contextKey||contextChanged)return;
  const frozen=preview,current=begin();attempted.current=true;setError('');
  try{
   await api.post('/stock/count-anchors',{...frozen.body,expected_fingerprint:frozen.response.preview_fingerprint,acknowledge_differences:true},{'Idempotency-Key':frozen.key});
   if(current()){attempted.current=false;setUncertain(false);setPreview(null);setReviewed(false);setDone(true);setReason('');setCursor('');setRefresh(value=>value+1);onChanged()}
  }catch(error){if(current()){
   if(!(error instanceof ApiError)||error.status===0||error.status>=500){setUncertain(true);setError(s('uncertain'))}
   else{attempted.current=false;setUncertain(false);setPreview(null);setReviewed(false);setError(explain(error));if(error.status===409)onChanged()}
  }}finally{finish(current)}
 }
 function lotDetails(row:Row|null|undefined){return row?<><strong>{row.on_hand_qty} {row.unit}</strong><small>{t('expiry')}: {date(row.expiry_date)}</small></>:s('unknown')}
 function differences(rows:Row[]){
  return <div className="stock-table stock-anchor-differences" tabIndex={0} role="region" aria-label={s('anchorDifferences')}><table><thead><tr>{[t('ingredient'),t('lot'),s('anchorBefore'),s('anchorCounted'),s('difference'),t('status')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map((row,index)=><tr key={`${row.ingredient_id}:${row.lot_id}:${index}`}><td>{ingredientName(row.ingredient_id)}</td><td>{row.lot_id}</td><td>{lotDetails(row.ledger)}</td><td>{lotDetails(row.counted)}</td><td>{row.difference??s('unknown')}</td><td>{s(row.status)}</td></tr>)}</tbody></table></div>;
 }
 // Keep the component mounted during parent refresh, including an uncertain POST.
 if(available)seenLedger.current=true;
 if(!seenLedger.current&&!history?.total&&!preview&&!done)return null;
 return <details className="panel stock-body stock-count-anchors" id="stock-count-anchors"><summary>{s('anchors')}</summary>
  <p className="stock-help">{s('anchorHint')}</p><p className="stock-help">{s('anchorDateRule')}</p>
  {!canWrite&&<p className="alert info">{s('anchorReadOnly')}</p>}
  {contextChanged&&<p className="alert warning" role="alert">{s('STOCK_CONTEXT_CHANGED')}</p>}
  {readError&&<p className="stock-error" role="alert">{readError}<button className="text-button" disabled={locked} onClick={()=>setRefresh(value=>value+1)}>{s('refresh')}</button></p>}
  {error&&<div className="alert danger" role="alert">{error}</div>}{busy&&<p role="status">{s('busy')}</p>}{done&&<div className="alert success" role="status">{s('anchorDone')}</div>}
  {canWrite&&<form className="stock-form" onSubmit={event=>{event.preventDefault();void validate()}}><fieldset disabled={locked||!sourceAllowed||loading||Boolean(readError)}><div className="stock-fields">
   <label>{s('anchorCountDate')}<input type="date" value={countDate} onChange={event=>edit(()=>setCountDate(event.target.value))}/></label>
   <label>{s('anchorReason')}<input value={reason} minLength={3} maxLength={1000} onChange={event=>edit(()=>setReason(event.target.value))}/></label>
  </div><button className="button secondary" disabled={!c.online}>{s('anchorPreview')}</button></fieldset></form>}
  {preview&&<section className="panel stock-body stock-preview" aria-label={s('anchorPreview')}><h3>{s('anchorPreview')}</h3>
   <p className="stock-meta">{date(preview.body.count_date)} · {preview.body.reason} · {t('version')}: {preview.body.expected_version}</p>
   <p className="stock-help">{s('anchorThrough')}: {preview.response.through_movement_sequence}</p>
   {differences(preview.response.differences||[])}
   <p className="stock-help">{s('anchorEffect')}</p>
   <label className="checkbox-label"><input type="checkbox" checked={reviewed} disabled={locked} onChange={event=>setReviewed(event.target.checked)}/>{s('anchorReviewed')}</label>
   <div className="stock-actions"><button className="button primary" disabled={!reviewed||busy||disabled||!canWrite||!c.online||preview.contextKey!==contextKey||contextChanged} onClick={()=>void post()}>{s(uncertain?'retryPost':'anchorPost')}</button>{!uncertain&&<button className="button secondary" disabled={locked} onClick={reset}>{s('cancelPreview')}</button>}</div>
  </section>}
  <h3>{s('anchorHistory')}</h3>{loading?<p role="status">{s('loading')}</p>:history?.items?.length?<>
   {history.items.map((item:Row)=><details key={item.id}><summary>{date(item.count_date)} · {s('sequence')}: {item.sequence} · {t('version')}: {item.ledger_version}</summary><p className="stock-help">{item.reason}</p><p className="stock-meta">{s('anchorActor')}: {item.actor_id} · {item.recorded_at}</p><p className="stock-help">{s('anchorThrough')}: {item.through_movement_sequence}</p>{differences(item.differences||[])}</details>)}
   <p className="stock-help">{history.items.length} / {history.total}</p>
  </>:<p className="stock-empty">{s('anchorEmpty')}</p>}
  <div className="stock-actions"><button className="button secondary" disabled={!cursor||locked} onClick={()=>edit(()=>setCursor(''))}>{s('previous')}</button><button className="button secondary" disabled={!history?.next_cursor||locked} onClick={()=>edit(()=>setCursor(history?.next_cursor||''))}>{s('next')}</button></div>
 </details>;
}
