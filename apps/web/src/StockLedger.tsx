import {useEffect,useRef,useState} from 'react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,name} from './shared';
import {stockText} from './stockCopy';
import StockRecipes from './StockRecipes';
import './stock-ledger.css';

type Line={ingredient_id:string;lot_id:string;unit:string;expiry_date:string;quantity:string};
type Portion={meal_id:string;quantity:string};
type Preview={response:Row;body:Row;path:string;key:string};
const blankLine=():Line=>({ingredient_id:'',lot_id:'',unit:'',expiry_date:'',quantity:''});
const decimal=/^-?\d+(?:\.\d{1,9})?$/;
const day=/^\d{4}-\d{2}-\d{2}$/;

export default function StockLedger(c:Context) {
 // Remount on account/branch changes. A late response is also fenced by CSRF and generation.
 return <StockWorkspace key={[c.user?.organization_id,c.user?.id,c.branch].join(':')} {...c}/>;
}
function StockWorkspace(c:Context) {
 const s=stockText(c.lang),t=c.t,scope=encodeURIComponent(c.branch);
 const canWrite=c.dataContext?.operations_enabled===true&&['admin','manager','warehouse'].includes(c.user?.role);
 const canAdjust=['admin','manager'].includes(c.user?.role);
 const initialDate=c.inventoryDate||c.dataContext?.inventory_date||c.dataContext?.target_date||'';
 const [openingDate,setOpeningDate]=useState(initialDate),[baselineDate,setBaselineDate]=useState(initialDate);
 const [position,setPosition]=useState<Row|null>(null),[catalog,setCatalog]=useState<Row>({ingredients:[],meals:[]});
 const [history,setHistory]=useState<Row|null>(null),[cursor,setCursor]=useState(''),[refresh,setRefresh]=useState(0);
 const [loading,setLoading]=useState(true),[loadError,setLoadError]=useState('');
 const [kind,setKind]=useState('receipt'),[businessDate,setBusinessDate]=useState(initialDate),[reference,setReference]=useState(''),[reason,setReason]=useState('');
 const [lines,setLines]=useState<Line[]>([blankLine()]),[portions,setPortions]=useState<Portion[]>([{meal_id:'',quantity:''}]);
 const [reverseId,setReverseId]=useState(''),[requirements,setRequirements]=useState<Row|null>(null);
 const [preview,setPreview]=useState<Preview|null>(null),[reviewed,setReviewed]=useState(false),[uncertain,setUncertain]=useState(false);
 const [action,setAction]=useState(''),[error,setError]=useState(''),[done,setDone]=useState(false),[rowErrors,setRowErrors]=useState<number[]>([]);
 const [countDate,setCountDate]=useState(initialDate),[reconciliation,setReconciliation]=useState<Row|null>(null),[countError,setCountError]=useState('');
 const [recipeLocked,setRecipeLocked]=useState(false);
 const mounted=useRef(true),generation=useRef(0),pending=useRef(false),reading=useRef(0),postAttempted=useRef(false);
 const busy=Boolean(action),locked=busy||uncertain||recipeLocked,stale=position?.ledger&&(position.baseline_freshness!=='unchanged'||position.context_freshness!=='unchanged');
 const ingredients:Row[]=catalog.ingredients||[],meals:Row[]=catalog.meals||[];
 const ingredientName=(id:string)=>name(ingredients.find(item=>item.ingredient_id===id)?.ingredient_name||id);
 const contextKey=JSON.stringify([c.user?.role,c.dataContext?.source,c.dataContext?.data_origin,c.dataContext?.usage_mode]);
 const previousContext=useRef(contextKey);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++generation.current;++reading.current}},[]);
 useEffect(()=>{
  if(previousContext.current===contextKey)return;
  previousContext.current=contextKey;++generation.current;pending.current=false;setAction('');setRequirements(null);setReconciliation(null);
  // Keep an uncertain command frozen for an exact idempotent retry; changed access still blocks POST.
  if(!postAttempted.current){setPreview(null);setReviewed(false)}else setUncertain(true);
  setRefresh(value=>value+1);
 },[contextKey]);
 useEffect(()=>{
  const read=++reading.current,csrf=api.csrf;let active=true;
  const current=()=>active&&mounted.current&&read===reading.current&&csrf===api.csrf;
  setLoading(true);setLoadError('');setPosition(null);setHistory(null);
  if(!day.test(openingDate)){setLoading(false);setPosition(null);return()=>{active=false}}
  Promise.all([
   api.request(`/stock/ledger?branch_id=${scope}${openingDate?'&opening_date='+openingDate:''}`),
   api.request(`/stock/catalog?branch_id=${scope}`),
   api.request(`/stock/movements?branch_id=${scope}&limit=20&cursor=${cursor||'0'}`),
  ]).then(([ledger,catalog,history])=>{if(current()){setPosition(ledger);setCatalog(catalog);setHistory(history)}})
   .catch(error=>{if(current())setLoadError(explain(error,'unavailable'))}).finally(()=>{if(current())setLoading(false)});
  return()=>{active=false};
 },[scope,openingDate,cursor,refresh,c.revision]);
 useEffect(()=>{if(!postAttempted.current){invalidate();setRequirements(null);setReconciliation(null)}},[c.revision]);
 useEffect(()=>{
  if(!uncertain)return;
  const prevent=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};
  window.addEventListener('beforeunload',prevent);return()=>window.removeEventListener('beforeunload',prevent);
 },[uncertain]);

 function explain(value:unknown,fallback='failed') {
  if(value instanceof ApiError){
   if(value.status===403)return s('forbidden');
   const known=s(value.code);if(known!==value.code)return known;
   if(value.status===409)return s('conflict');
   if(value.status===0)return c.t('offline');
   return `${s(fallback)} (${value.code})`;
  }
  return s(fallback);
 }
 function invalidate(){++generation.current;pending.current=false;setAction('');setPreview(null);setReviewed(false);setError('');setDone(false);setRowErrors([]);postAttempted.current=false}
 function edit(change:()=>void){if(locked)return;invalidate();change()}
 function begin(){pending.current=true;const version=++generation.current,csrf=api.csrf;return()=>mounted.current&&version===generation.current&&csrf===api.csrf}
 function finish(current:()=>boolean){if(current()){pending.current=false;setAction('')}}
 function refreshData(){if(locked)return;invalidate();setReconciliation(null);setRequirements(null);setRefresh(value=>value+1)}
 function changeLine(index:number,patch:Partial<Line>){edit(()=>setLines(current=>current.map((line,i)=>i===index?{...line,...patch}:line)))}
 function portionsBody(){
  const result:Record<string,number>={};
  for(const item of portions){if(!item.meal_id||!/^[1-9]\d*$/.test(item.quantity)||Number(item.quantity)>1e9||item.meal_id in result)return null;result[item.meal_id]=Number(item.quantity)}
  return result;
 }
 async function calculateRecipe(){
  if(locked||!c.online)return;invalidate();const portionMap=portionsBody();
  if(!portionMap||!day.test(businessDate)){setError(s('recipeUnavailable'));return}
  const current=begin();setAction('requirements');
  try{const data=await api.post('/stock/recipe-requirements',{branch_id:c.branch,business_date:businessDate,portions:portionMap});if(current())setRequirements(data)}catch(error){if(current())setError(explain(error,'recipeUnavailable'))}finally{finish(current)}
 }
 function documentBody():Row|null {
  if(!day.test(businessDate)||!reference.trim()||reference.length>128||reason.trim().length<3){setError(s('required'));return null}
  const body:Row={branch_id:c.branch,expected_version:position?.version,kind,business_date:businessDate,source_reference:reference,reason:reason.trim()};
  if(kind==='reversal'){if(!reverseId){setError(s('required'));return null}return {...body,reverses_id:reverseId}}
  const invalid=lines.flatMap((line,index)=>!line.ingredient_id||!line.lot_id||!day.test(line.expiry_date)||!decimal.test(line.quantity)||!/[1-9]/.test(line.quantity)||(kind!=='adjustment'&&line.quantity.startsWith('-'))?[index]:[]);
  setRowErrors(invalid);if(invalid.length){setError(s('required'));return null}
  body.lines=lines;
  if(kind==='recipe_usage'){const portionMap=portionsBody();if(!portionMap){setError(s('recipeUnavailable'));return null}body.recipe_usage={portions:portionMap}}
  return body;
 }
 async function validate(open=false){
  if(!canWrite||locked||pending.current||!c.online||loading||loadError||stale)return;
  invalidate();
  if(open&&(!day.test(baselineDate)||reason.trim().length<3)){setError(s('required'));return}
  const body=open?{branch_id:c.branch,baseline_date:baselineDate,reason:reason.trim()}:documentBody();if(!body)return;
  const path=open?'/stock/open':'/stock/movements',current=begin();setAction('preview');
  try{const response=await api.post(path+'/preview',body);if(current())setPreview({response,body,path,key:crypto.randomUUID()})}
  catch(error){if(current()){setError(explain(error));if(error instanceof ApiError&&error.status===409)setRefresh(value=>value+1)}}finally{finish(current)}
 }
 async function post(){
  if(!preview||!canWrite||!reviewed||pending.current||recipeLocked||!c.online)return;
  if(['adjustment','reversal'].includes(preview.body.kind)&&!canAdjust)return;
  const frozen=preview,current=begin();postAttempted.current=true;setAction('post');setError('');
  try{
   await api.post(frozen.path,{...frozen.body,expected_fingerprint:frozen.response.preview_fingerprint},{'Idempotency-Key':frozen.key});
   if(current()){setUncertain(false);setPreview(null);setReviewed(false);setDone(true);setReason('');setReference('');setReverseId('');setKind('receipt');setLines([blankLine()]);setRequirements(null);setReconciliation(null);setCursor('');postAttempted.current=false;setRefresh(value=>value+1)}
  }catch(error){if(current()){
   if(!(error instanceof ApiError)||error.status===0||error.status>=500){setUncertain(true);setError(s('uncertain'))}
   else{setUncertain(false);setError(explain(error));setPreview(null);setReviewed(false);postAttempted.current=false;if(error.status===409)setRefresh(value=>value+1)}
  }}finally{finish(current)}
 }
 async function reconcile(){
  if(locked||!c.online||!day.test(countDate))return;
  const current=begin();setAction('reconcile');setCountError('');setReconciliation(null);
  try{const result=await api.request(`/stock/reconciliation?branch_id=${scope}&count_date=${countDate}`);if(current())setReconciliation(result)}catch(error){if(current())setCountError(explain(error))}finally{finish(current)}
 }
 function reverse(row:Row){edit(()=>{setKind('reversal');setReverseId(row.id||row.movement_id);setReference('');setReason('')});document.getElementById('stock-document')?.scrollIntoView({behavior:'smooth',block:'start'})}
 function lotTable(rows:Row[]|null|undefined,quantityKey='on_hand_qty'){
  return !rows?.length?<p className="stock-empty">{s('noRows')}</p>:<div className="stock-table" tabIndex={0} role="region" aria-label={s(quantityKey==='quantity_delta'?'delta':'balance')}><table><thead><tr>{[t('ingredient'),t('lot'),t('unit'),t('expiry'),s(quantityKey==='quantity_delta'?'delta':'balance')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{rows.map((row,index)=><tr key={[row.ingredient_id,row.lot_id,index].join(':')}><td>{ingredientName(row.ingredient_id)}</td><td>{row.lot_id}</td><td>{row.unit}</td><td>{date(row.expiry_date)}</td><td>{row[quantityKey]??s('unknown')}</td></tr>)}</tbody></table></div>;
 }
 const reversed=new Set((history?.items||[]).map((row:Row)=>row.reverses_id).filter(Boolean));
 const publicContext=position?.public_context||c.dataContext;
 const reconciliationStale=Boolean(reconciliation&&((reconciliation.baseline_freshness&&reconciliation.baseline_freshness!=='unchanged')||(reconciliation.context_freshness&&reconciliation.context_freshness!=='unchanged')));
 return <section className="stock-ledger" aria-label={s('title')}>
  <div className="stock-toolbar"><h2>{s('title')}</h2><button className="button secondary" disabled={locked} onClick={refreshData}>{s('refresh')}</button></div>
  <p className="stock-intro">{s('intro')}</p>
  <div className="stock-context"><strong>{publicContext?.data_origin??s('unknown')}</strong><span>{publicContext?.usage_mode??s('unknown')}</span><span>{c.branch}</span></div>
  <div className="stock-fields"><label>{s('openingDate')}<input type="date" value={openingDate} disabled={locked} onChange={event=>{invalidate();setOpeningDate(event.target.value);setReconciliation(null)}}/></label></div>
  {!canWrite&&<p className="alert info">{s('readOnly')}</p>}
  {loading&&<p role="status">{s('loading')}</p>}
  {loadError&&<div className="alert danger" role="alert">{loadError}</div>}
  {error&&<div className="alert danger" role="alert">{error}</div>}
  {busy&&<div className="alert info" role="status">{s('busy')}</div>}
  {done&&<div className="alert success" role="status">{s('done')}</div>}
  {stale&&<div className="alert warning" role="alert">{s('baselineStale')}</div>}
  <StockRecipes context={c} catalog={catalog} disabled={busy||uncertain} revision={refresh} onLockChange={setRecipeLocked} onChanged={()=>{invalidate();setRequirements(null);setRefresh(value=>value+1)}}/>
  {!loadError&&position&&!position.ledger&&<section className="panel stock-body"><h3>{s('empty')}</h3><p className="stock-help">{s('baselineHint')}</p>{canWrite&&<form className="stock-form" onSubmit={event=>{event.preventDefault();void validate(true)}}><fieldset disabled={locked||loading}><div className="stock-fields"><label>{s('baseline')}<input type="date" value={baselineDate} onChange={event=>edit(()=>setBaselineDate(event.target.value))}/></label><label>{s('reason')}<input value={reason} minLength={3} maxLength={1000} onChange={event=>edit(()=>setReason(event.target.value))}/></label></div><button className="button primary" disabled={!c.online}>{s('previewOpen')}</button></fieldset></form>}</section>}
  {position?.ledger&&<>
   <section className="panel stock-body"><div className="stock-toolbar"><h3>{s('opening')}</h3><span>{t('version')}: {position.version}</span></div><p className="stock-help">{s('openingHint')}</p>{lotTable(position.opening?.rows)}<details><summary>{s('latest')}</summary><p className="stock-help">{s('through')}: {date(position.latest?.through_business_date)}</p>{lotTable(position.latest?.rows)}</details></section>
   {canWrite&&<section className="panel stock-body" id="stock-document"><h3>{s('document')}</h3><form className="stock-form" onSubmit={event=>{event.preventDefault();void validate()}}><fieldset disabled={locked||Boolean(stale)||loading||Boolean(loadError)}>
    <div className="stock-fields"><label>{s('kind')}<select aria-label={s('kind')} value={kind} onChange={event=>edit(()=>{setKind(event.target.value);setReverseId('');setRequirements(null)})}>{['receipt','waste','recipe_usage',...(canAdjust?['adjustment']:[])].map(value=><option key={value} value={value}>{s(value)}</option>)}{kind==='reversal'&&<option value="reversal">{s('reversal')}</option>}</select></label><label>{s('businessDate')}<input type="date" value={businessDate} min={position.ledger.baseline_date} onChange={event=>edit(()=>{setBusinessDate(event.target.value);setRequirements(null)})}/></label><label>{s('sourceReference')}<input value={reference} maxLength={128} onChange={event=>edit(()=>setReference(event.target.value))}/></label><label>{s('reason')}<input value={reason} minLength={3} maxLength={1000} onChange={event=>edit(()=>setReason(event.target.value))}/></label></div>
    <p className="stock-help">{s('sourceHint')}</p>
    {kind==='adjustment'&&<p className="alert info">{s('adjustmentHint')}</p>}
    {kind==='reversal'?<><p className="alert info">{s('reverseHint')}</p><p className="stock-meta">{s('reversalOf')}: {reverseId}</p></>:<>
     {kind==='recipe_usage'&&<div><h3>{s('portions')}</h3><p className="stock-help">{s('recipeHint')}</p>{portions.map((portion,index)=><div className="stock-portion" key={index}><label>{t('meal')} {index+1}<select aria-label={`${t('meal')} ${index+1}`} value={portion.meal_id} onChange={event=>edit(()=>{setRequirements(null);setPortions(current=>current.map((row,i)=>i===index?{...row,meal_id:event.target.value}:row))})}><option value="">{s('chooseMeal')}</option>{meals.map(meal=><option key={meal.meal_id} value={meal.meal_id}>{name(meal.meal_name||meal.meal_id)}</option>)}</select></label><label>{s('portions')} {index+1}<input inputMode="numeric" value={portion.quantity} onChange={event=>edit(()=>{setRequirements(null);setPortions(current=>current.map((row,i)=>i===index?{...row,quantity:event.target.value}:row))})}/></label>{portions.length>1&&<button type="button" className="text-button" onClick={()=>edit(()=>{setRequirements(null);setPortions(current=>current.filter((_,i)=>i!==index))})}>{s('removeLine')} {index+1}</button>}</div>)}<div className="stock-actions"><button type="button" className="button secondary" onClick={()=>edit(()=>{setRequirements(null);setPortions(current=>[...current,{meal_id:'',quantity:''}])})}>{s('addMeal')}</button><button type="button" className="button secondary" disabled={!c.online} onClick={()=>void calculateRecipe()}>{s('calculateRecipe')}</button></div>{requirements&&<div><h3>{s('requirements')}</h3><div className="stock-table"><table><thead><tr><th>{t('ingredient')}</th><th>{t('unit')}</th><th>{s('quantity')}</th></tr></thead><tbody>{(requirements.requirements||[]).map((row:Row)=><tr key={row.ingredient_id}><td>{ingredientName(row.ingredient_id)}</td><td>{row.unit}</td><td>{row.gross_required}</td></tr>)}</tbody></table></div></div>}</div>}
     <h3>{s('lines')}</h3><p className="stock-help">{s('decimalHint')}</p>{lines.map((line,index)=><fieldset key={index} className="stock-line"><legend>{s('row')} {index+1}</legend><div className="stock-fields"><label>{t('ingredient')} {index+1}<select aria-label={`${t('ingredient')} ${index+1}`} value={line.ingredient_id} onChange={event=>changeLine(index,{ingredient_id:event.target.value,unit:ingredients.find(item=>item.ingredient_id===event.target.value)?.unit||''})}><option value="">{s('chooseIngredient')}</option>{ingredients.map(ingredient=><option key={ingredient.ingredient_id} value={ingredient.ingredient_id}>{name(ingredient.ingredient_name||ingredient.ingredient_id)}</option>)}</select></label><label>{t('lot')} {index+1}<input value={line.lot_id} maxLength={64} onChange={event=>changeLine(index,{lot_id:event.target.value})}/></label><label>{t('unit')} {index+1}<input value={line.unit} readOnly/></label><label>{t('expiry')} {index+1}<input type="date" value={line.expiry_date} onChange={event=>changeLine(index,{expiry_date:event.target.value})}/></label><label>{s('quantity')} {index+1}<input inputMode="decimal" value={line.quantity} maxLength={32} aria-invalid={rowErrors.includes(index)} onChange={event=>changeLine(index,{quantity:event.target.value})}/></label></div>{rowErrors.includes(index)&&<p className="stock-error" role="alert">{s('row')} {index+1}: {s('badLine')}</p>}{lines.length>1&&<button type="button" className="text-button" onClick={()=>edit(()=>setLines(current=>current.filter((_,i)=>i!==index)))}>{s('removeLine')} {index+1}</button>}</fieldset>)}<button type="button" className="button secondary" disabled={lines.length>=500} onClick={()=>edit(()=>setLines(current=>[...current,blankLine()]))}>{s('addLine')}</button>
    </>}
    <p className="stock-help">{s('noSupplier')}</p><div className="stock-actions"><button className="button primary" disabled={!c.online}>{s('preview')}</button></div>
   </fieldset></form></section>}
  </>}
  {preview&&<section className="panel stock-body stock-preview" aria-label={s('previewTitle')}><h3>{s('previewTitle')}</h3><p className="stock-help">{s('previewHint')}</p><div className="stock-meta"><span>{s(preview.response.operation==='open'?'baseline':'businessDate')}: {date(preview.body.baseline_date||preview.body.business_date)}</span><span>{s('reason')}: {preview.body.reason}</span>{preview.body.source_reference&&<span>{s('sourceReference')}: {preview.body.source_reference}</span>}</div>{preview.response.operation==='open'?lotTable(preview.response.baseline_rows):<><h3>{s('delta')}</h3>{lotTable(preview.response.entries,'quantity_delta')}<details><summary>{s('before')}</summary>{lotTable(preview.response.balances_before)}</details><h3>{s('after')}</h3>{lotTable(preview.response.balances_after)}</>}{preview.response.recipe_evidence&&<details><summary>{s('evidence')}</summary><div className="stock-table"><table><thead><tr>{[t('meal'),t('version'),t('ingredient'),t('net'),t('yield')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{(preview.response.recipe_evidence.rows||[]).map((row:Row,index:number)=><tr key={index}><td>{row.meal_id}</td><td>{row.recipe_version}</td><td>{ingredientName(row.ingredient_id)}</td><td>{row.net_qty_per_portion}</td><td>{row.yield_factor}</td></tr>)}</tbody></table></div></details>}<label className="checkbox-label"><input type="checkbox" checked={reviewed} disabled={locked} onChange={event=>setReviewed(event.target.checked)}/>{s('reviewed')}</label><div className="stock-actions"><button className="button primary" disabled={!reviewed||busy||recipeLocked||!c.online||!canWrite} onClick={()=>void post()}>{s(uncertain?'retryPost':preview.response.operation==='open'?'open':'post')}</button>{!uncertain&&<button className="button secondary" disabled={busy} onClick={invalidate}>{s('cancelPreview')}</button>}</div></section>}
  {position?.ledger&&<>
   <section className="panel stock-body"><h3>{s('history')}</h3>{history?.items?.length?<div className="stock-table" tabIndex={0} role="region" aria-label={s('history')}><table><thead><tr>{[s('sequence'),s('businessDate'),s('kind'),s('sourceReference'),s('reason'),s('lines')].map(label=><th key={label}>{label}</th>)}{canAdjust&&<th>{s('reverse')}</th>}</tr></thead><tbody>{history.items.map((row:Row)=><tr key={row.id||row.movement_id}><td>{row.sequence}</td><td>{date(row.business_date)}</td><td>{s(row.kind)}{row.reverses_id&&<small>{' · '+row.reverses_id}</small>}</td><td>{row.source_reference}</td><td>{row.reason}</td><td>{(row.entries||[]).map((line:Row,index:number)=><p key={index}>{ingredientName(line.ingredient_id)} · {line.lot_id}: {line.quantity_delta} {line.unit}</p>)}</td>{canAdjust&&<td>{row.kind!=='reversal'&&!row.reversed_by_id&&!reversed.has(row.id||row.movement_id)&&<button className="text-button" disabled={locked||Boolean(stale)} onClick={()=>reverse(row)}>{s('reverse')}</button>}</td>}</tr>)}</tbody></table></div>:<p className="stock-empty">{s('historyEmpty')}</p>}<div className="stock-actions"><button className="button secondary" disabled={!cursor||locked} onClick={()=>setCursor('')}>{s('previous')}</button><button className="button secondary" disabled={!history?.next_cursor||locked} onClick={()=>setCursor(history?.next_cursor||'')}>{s('next')}</button></div></section>
   <section className="panel stock-body"><h3>{s('reconciliation')}</h3><p className="stock-help">{s('reconciliationHint')}</p><div className="stock-fields"><label>{s('countDate')}<input type="date" value={countDate} min={position.ledger.baseline_date} disabled={locked} onChange={event=>{setCountDate(event.target.value);setReconciliation(null);setCountError('')}}/></label></div><button className="button secondary" disabled={locked||!c.online||!countDate} onClick={()=>void reconcile()}>{s('reconcile')}</button>{countError&&<p className="stock-error" role="alert">{countError}</p>}{reconciliation&&<><p className={`alert ${reconciliation.status==='matched'&&!reconciliationStale?'success':'warning'}`} role="status">{reconciliationStale?s('baselineStale'):s(reconciliation.status)} · {date(reconciliation.target_date)}</p><div className="stock-table" tabIndex={0} role="region" aria-label={s('reconciliation')}><table><thead><tr>{[t('ingredient'),t('lot'),s('calculated'),s('actualCount'),s('difference'),t('status')].map(label=><th key={label}>{label}</th>)}</tr></thead><tbody>{(reconciliation.lines||[]).map((row:Row,index:number)=><tr key={index}><td>{ingredientName(row.ingredient_id)}</td><td>{row.lot_id}</td><td>{row.ledger?`${row.ledger.on_hand_qty} ${row.ledger.unit}`:s('unknown')}</td><td>{row.counted?`${row.counted.on_hand_qty} ${row.counted.unit}`:s('unknown')}</td><td>{row.difference??'—'}</td><td>{s(row.status)}</td></tr>)}</tbody></table></div></>}</section>
  </>}
 </section>;
}
