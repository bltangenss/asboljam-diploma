import {useEffect,useRef,useState} from 'react';
import {ArrowDownToLine,ArrowRight,Check,CheckCircle2,ChevronRight,Database,FileUp} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type ImportBatchView,type ImportReceipt,type Row,useData,items,fmt,date,Heading,Button,Badge,DataState,Table,Pagination} from './shared';

const correctionKinds=['daily_sales','inventory_lots','calendar'];
const sourceCode=/^[A-Za-z0-9_.:-]{1,64}$/;
const timestamp=(value?:string|null)=>value?value.slice(0,19).replace('T',' '):'—';

export default function Imports(c:Context) {
 const {t,lang,branch,user,online}=c;
 const real=c.dataContext?.mode==='real_business',configuredSource=c.dataContext?.source;
 const canImport=c.dataContext?.operations_enabled===true&&['admin','manager','warehouse'].includes(user?.role||'');
 const types=user?.role==='admin'?['daily_sales','inventory_lots','branches','meals','ingredients','recipes','suppliers','supplier_offers','calendar']
  :user?.role==='warehouse'?['inventory_lots']:['manager','analyst'].includes(user?.role||'')?correctionKinds:[];
 const [kind,setKind]=useState(user?.role==='admin'&&(!branch||new URLSearchParams(location.search).get('kind')==='branches')?'branches':user?.role==='warehouse'?'inventory_lots':'daily_sales');
 const [mode,setMode]=useState<'append'|'correction'>('append'),[reason,setReason]=useState(''),[correctsBatch,setCorrectsBatch]=useState('');
 const [sourceId,setSourceId]=useState('manual_csv'),[mappingVersion,setMappingVersion]=useState('canonical-v1'),[declaredHash,setDeclaredHash]=useState('');
 const [filename,setFilename]=useState(''),[text,setText]=useState(''),[preview,setPreview]=useState<ImportBatchView|null>(null);
 const [error,setError]=useState(''),[action,setAction]=useState(''),[done,setDone]=useState(false),[reviewed,setReviewed]=useState(false),[uncertain,setUncertain]=useState(false);
 const [cursor,setCursor]=useState(''),[historyRevision,setHistoryRevision]=useState(0);
 const history=useData(`/imports?limit=20&cursor=${cursor||'0'}`,historyRevision+c.revision);
 const version=useRef(0),pending=useRef(false),mounted=useRef(true);
 const commitKeys=useRef(new Map<string,string>());
 const busy=Boolean(action),locked=action==='commit'||action==='recover';
 const requestedBatch=new URLSearchParams(location.search).get('batch')||'';
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++version.current}},[]);
 useEffect(()=>{if(!done)resetPreview()},[branch]);
 useEffect(()=>{resetPreview()},[user?.role]);
 useEffect(()=>{if(real&&configuredSource){resetPreview();setSourceId(configuredSource.source_id);setMappingVersion(configuredSource.mapping_version)}},[real,configuredSource?.source_id,configuredSource?.mapping_version]);
 useEffect(()=>{if(requestedBatch)void openBatch(requestedBatch)},[requestedBatch,user?.id,user?.organization_id]);

 function resetPreview() {
  const next=++version.current;pending.current=false;
  setPreview(null);setDone(false);setReviewed(false);setUncertain(false);setError('');setAction('');return next;
 }
 function begin(next=version.current) {
  const session=api.csrf;pending.current=true;
  return ()=>mounted.current&&next===version.current&&session===api.csrf;
 }
 function finish(current:()=>boolean) {if(current()){pending.current=false;setAction('')}}
 function explain(error:unknown) {
  const code=error instanceof ApiError?error.code:'';
  if(['STALE_IMPORT','DUPLICATE_CONFLICT','IMPORT_PREVIEW_REQUIRED','IMPORT_STALE','STALE_PREVIEW','IMPORT_CONFLICT','DUPLICATE_KEY'].includes(code))return t('importStale');
  if(code==='IMPORT_INVALID')return t('noImport');
  if(error instanceof ApiError&&error.status===403)return t('forbidden');
  if(error instanceof ApiError&&error.status===404)return t('importUnavailable');
  return error instanceof Error?error.message:t('importFailed');
 }
 function selectKind(value:string) {
  resetPreview();setKind(value);setCorrectsBatch('');
  if(!correctionKinds.includes(value))setMode('append');
 }
 async function validate() {
  if(!canImport||!types.includes(kind)||!text||pending.current||!online)return;
  if(!sourceCode.test(sourceId)||!sourceCode.test(mappingVersion)||(declaredHash&&!/^[a-fA-F0-9]{64}$/.test(declaredHash))){setError(t('importSourceInvalid'));return}
  if(real&&(!configuredSource||sourceId!==configuredSource.source_id||mappingVersion!==configuredSource.mapping_version)){setError(t('importSourceInvalid'));return}
  if(mode==='correction'&&(!correctionKinds.includes(kind)||reason.trim().length<3)){setError(t('importReasonRequired'));return}
  const current=begin(resetPreview());setAction('preview');
  try {
   const result=await api.post<ImportBatchView>('/imports/preview',{kind,csv_text:text,mode,
    ...(mode==='correction'?{reason:reason.trim(),...(correctsBatch?{corrects_batch_id:correctsBatch}:{})}:{}),
    source:{source_id:sourceId,mapping_version:mappingVersion,...(declaredHash?{declared_original_sha256:declaredHash}:{})}});
   if(current()){setPreview(result);setDone(result.status==='committed');setHistoryRevision(n=>n+1)}
  } catch(error) {if(current())setError(explain(error))}
  finally {finish(current)}
 }
 async function accepted(batch:ImportBatchView,receipt:ImportReceipt,current:()=>boolean) {
  if(!current())return;
  setPreview({...batch,status:'committed',can_commit:false,receipt});setDone(true);setUncertain(false);setError('');setHistoryRevision(n=>n+1);
  await c.refreshWorkspace();
 }
 async function recover(batch:ImportBatchView,current:()=>boolean) {
  if(!current())return;
  setAction('recover');setUncertain(true);
  try {
   const result=await api.request<ImportBatchView>(`/imports/${encodeURIComponent(batch.id)}`);
   if(!current())return;
   if(result.status==='committed')await accepted(result,result.receipt||{id:result.id,status:'committed',row_count:result.row_count},current);
   else {setPreview(result);setError(t('importNotConfirmed'))}
  } catch(error) {if(current())setError(explain(error))}
 }
 async function commit() {
  if(!preview||!canImport||!types.includes(preview.kind)||!(preview.can_commit??preview.valid)||done||pending.current||!online)return;
  if(preview.mode==='correction'&&!reviewed)return;
  const batch=preview,current=begin();setAction('commit');setError('');
  let key=commitKeys.current.get(batch.id);
  if(!key){key=crypto.randomUUID();commitKeys.current.set(batch.id,key)}
  try {
   const receipt=await api.post<ImportReceipt>(`/imports/${encodeURIComponent(batch.id)}/commit`,{}, {'Idempotency-Key':key});
   if(receipt.status!=='committed')throw new Error(t('importNotConfirmed'));
   await accepted(batch,receipt,current);
  } catch(error) {
   if(current()) {
    if(!(error instanceof ApiError)||error.status===0||error.status>=500||error.code==='ALREADY_COMMITTED')await recover(batch,current);
    else {setError(explain(error));if(error.status===409)setPreview({...batch,can_commit:false})}
   }
  } finally {finish(current)}
 }
 async function checkStatus() {
  if(!preview||pending.current||!online)return;
  const current=begin();await recover(preview,current);finish(current);
 }
 async function openBatch(id:string) {
  if(locked)return;
  const current=begin(resetPreview());setAction('detail');setText('');setFilename('');
  try {
   const result=await api.request<ImportBatchView>(`/imports/${encodeURIComponent(id)}`);
   if(current()){setPreview(result);setDone(result.status==='committed')}
  }catch(error){if(current())setError(explain(error))}
  finally{finish(current)}
 }
 function startCorrection(batch:ImportBatchView) {
  resetPreview();setKind(batch.kind);setMode('correction');setCorrectsBatch(batch.id);setReason('');setText('');setFilename('');
  setSourceId((real?configuredSource?.source_id:batch.source?.source_id)||'manual_csv');setMappingVersion((real?configuredSource?.mapping_version:batch.source?.mapping_version)||'canonical-v1');setDeclaredHash('');
 }
 const countLabels=['rows_seen','rows_checked','parsed','new','unchanged','updated','conflicting'] as const;
 const previewMode=preview?.mode||'append';
 const noChanges=preview?.counts&&preview.counts.new===0&&preview.counts.updated===0&&(preview.counts.unchanged??0)>0;
 const source=preview?.source;
 return <>
  <Heading title={t('imports')} sub={lang==='kk'?'Тексеру → алдын ала қарау → транзакциялық импорт':'Проверка → предпросмотр → транзакционный импорт'}/>
  {!canImport&&<div className="alert info" role="status">{t('readOnlyImports')}</div>}
  <div className="alert info">{t(real?'realImportNotice':'syntheticImportNotice')}{real&&configuredSource&&<span> · {t('branch')}: {configuredSource.branch_id}</span>}</div>
  <div className="import-steps">{['file','validate','preview','commit'].map((key,index)=><div key={key} className={(done?3:preview?2:text?1:0)>=index?'current':''}><span>{done||preview&&index<2?<Check size={15}/>:index+1}</span>{t(key)}{index<3&&<ChevronRight size={16}/>}</div>)}</div>
  {error&&<div className="alert danger" role="alert">{error}</div>}
  {busy&&<div className="alert info" role="status">{t(action==='recover'?'importRecovering':action==='commit'?'importSaving':'importLoading')}</div>}
  <section className="panel import-panel">
   <div className="filters">
    <label>{t('data')}<select aria-label={t('data')} value={kind} disabled={locked} onChange={event=>selectKind(event.target.value)}>{types.map(value=><option key={value}>{value}</option>)}</select></label>
    {canImport&&<label>{t('importMode')}<select aria-label={t('importMode')} value={mode} disabled={locked} onChange={event=>{resetPreview();setMode(event.target.value as 'append'|'correction');setCorrectsBatch('')}}><option value="append">{t('importAppend')}</option>{correctionKinds.includes(kind)&&<option value="correction">{t('importCorrection')}</option>}</select></label>}
   </div>
   <a className="button secondary" href={`/api/v1/imports/template/${kind}`}><ArrowDownToLine size={16}/>{lang==='kk'?'CSV үлгісі':'Шаблон CSV'}</a>
   {canImport&&<>
    <details><summary>{t('importSourceSettings')}</summary><div className="filters" style={{paddingTop:12}}>
     <label>{t('importSourceId')}<input aria-label={t('importSourceId')} maxLength={64} value={sourceId} disabled={locked} readOnly={real} onChange={event=>{resetPreview();setSourceId(event.target.value)}}/></label>
     <label>{t('importMappingVersion')}<input aria-label={t('importMappingVersion')} maxLength={64} value={mappingVersion} disabled={locked} readOnly={real} onChange={event=>{resetPreview();setMappingVersion(event.target.value)}}/></label>
     <label className="grow">{t('importDeclaredHash')}<input aria-label={t('importDeclaredHash')} maxLength={64} value={declaredHash} disabled={locked} onChange={event=>{resetPreview();setDeclaredHash(event.target.value)}}/></label>
    </div><p className="muted">{t('importSourceHint')}</p></details>
    {mode==='correction'&&<><div className="alert info">{t('importCorrectionHint')}{correctsBatch&&<span> · {t('importCorrects')}: {correctsBatch}</span>}</div><label>{t('importCorrectionReason')}<input aria-label={t('importCorrectionReason')} minLength={3} maxLength={1000} value={reason} disabled={locked} onChange={event=>{resetPreview();setReason(event.target.value)}}/></label></>}
   </>}
   <label className="file-zone"><span className="upload-icon"><FileUp size={27}/></span><strong>{filename||t('chooseFile')}</strong><span>{t('fileHint')}</span><input type="file" disabled={!canImport||locked} accept=".csv,text/csv" aria-label={t('chooseFile')} onChange={async event=>{
    if(!canImport||locked)return;const file=event.target.files?.[0];event.target.value='';if(!file)return;
    const next=resetPreview(),session=api.csrf;setText('');setFilename(file.name);
    if(file.size>20*1024*1024||!file.name.toLowerCase().endsWith('.csv')){setError(t('fileHint'));return}
    try{const value=await file.text();if(mounted.current&&next===version.current&&session===api.csrf)setText(value)}catch(error){if(mounted.current&&next===version.current)setError(explain(error))}
   }}/></label>
   <div className="import-actions"><span>{t('importDuplicateHint')}</span><Button disabled={!canImport||!types.includes(kind)||!text||busy||!online||mode==='correction'&&reason.trim().length<3} onClick={validate}>{t('preview')}<ArrowRight size={16}/></Button></div>
  </section>
  {preview&&<section className="panel" aria-label={t('importResult')}>
   <div className="panel-heading"><div><h2>{t('preview')} · {preview.kind}</h2><p>{previewMode==='correction'?t('importCorrection'):t('importAppend')} · {timestamp(preview.created_at)}</p></div><Badge tone={done||preview.valid?'green':'amber'}>{done?t('importCommitted'):preview.valid?t('valid'):t('noImport')}</Badge></div>
   <div style={{padding:'0 24px 16px'}}>
    {preview.branch_ids&&<p>{t('branch')}: {preview.branch_ids.join(', ')||'—'}</p>}
    {preview.period&&<p>{t('from')}: {date(preview.period.from)} · {t('to')}: {date(preview.period.to)}</p>}
    <div className="filters">{preview.counts?countLabels.map(key=><div key={key}><small>{t('importCount_'+key)}</small><p><strong>{fmt(preview.counts?.[key])}</strong></p></div>):<p>{t('importCount_parsed')}: {fmt(preview.row_count)}</p>}</div>
    {preview.validation_rows_checked!=null&&<p className="muted">{t('importValidationChecked')}: {fmt(preview.validation_rows_checked)}</p>}
    {typeof preview.scan_complete==='boolean'&&<p className="muted">{t(preview.scan_complete?'importScanComplete':'importScanPartial')}{preview.stop_reason?' · '+preview.stop_reason:''}</p>}
    {noChanges&&<div className="alert info">{t('importNoChanges')}</div>}
    {source&&<details><summary>{t('importSourceEvidence')}</summary>{[[t('importSourceId'),source.source_id],[t('importMappingVersion'),source.mapping_version],[t('data'),source.data_origin],['Timezone',source.timezone],['Currency',source.currency],[t('importProvenance'),source.provenance],[t('importReceivedHash'),preview.received_text_sha256],[t('importCanonicalHash'),preview.canonical_rows_sha256],[t('importDeclaredHash'),source.declared_original_sha256]].map(([label,value])=><div className="settings-row" key={label}><h3>{label}</h3><span style={{overflowWrap:'anywhere',minWidth:0}}>{value??'—'}</span></div>)}</details>}
    {preview.reason&&<p><strong>{t('importCorrectionReason')}: </strong>{preview.reason}</p>}
    <p className="muted">{t('importSample')}{preview.preview_limit!==undefined?' · '+fmt(preview.preview_limit):''}</p>
   </div>
   {Boolean(preview.errors?.length)&&<><Table t={t} rows={preview.errors||[]} columns={[{key:'row_number',label:t('row')},{key:'field',label:t('field')},{key:'code',label:'Code'},{key:'message',label:t('error'),render:(row:Row)=>{const key='error_'+row.code,text=t(key);return text!==key?text:row.message}}]}/>{preview.errors_truncated&&<p className="alert info">{t('importErrorsTruncated')}</p>}</>}
   {previewMode==='correction'&&Boolean(preview.changes?.length)?<div style={{padding:'0 24px'}}>{preview.changes!.map((change,index)=><details key={index} open><summary>{String(change.key)} · {t('importOperation_'+change.operation)}</summary><Table t={t} rows={Array.from(new Set([...Object.keys(change.before||{}),...Object.keys(change.after||{})])).map(field=>({field,before:change.before?.[field]??'—',after:change.after?.[field]??'—'}))} columns={[{key:'field',label:t('field')},{key:'before',label:t('importBefore')},{key:'after',label:t('importAfter')}]}/></details>)}</div>:!preview.errors?.length&&<Table t={t} rows={preview.preview||[]} columns={Object.keys(preview.preview?.[0]||{}).map(key=>({key,label:key}))}/>}
   <div className="panel-actions" style={{flexWrap:'wrap'}}>
    {done?<><div className="alert success"><CheckCircle2 size={20}/>{t('importDone')}</div>{preview.receipt&&<p>{t('importReceipt')}: {t('importCount_new')} {fmt(preview.receipt.inserted_rows)} · {t('importCount_updated')} {fmt(preview.receipt.updated_rows)} · {t('importCount_unchanged')} {fmt(preview.receipt.unchanged_rows)}</p>}{canImport&&correctionKinds.includes(preview.kind)&&types.includes(preview.kind)&&<Button secondary onClick={()=>startCorrection(preview)}>{t('importCorrectBatch')}</Button>}</>:<>
     {previewMode==='correction'&&<label style={{display:'flex',flexDirection:'row',gap:8,alignItems:'center'}}><input type="checkbox" checked={reviewed} disabled={busy} onChange={event=>setReviewed(event.target.checked)}/>{t('importCorrectionReviewed')}</label>}
     {uncertain&&<Button secondary disabled={busy||!online} onClick={checkStatus}>{t('importCheckStatus')}</Button>}
     {canImport&&<Button disabled={!types.includes(preview.kind)||!(preview.can_commit??preview.valid)||busy||!online||previewMode==='correction'&&!reviewed} onClick={commit}><Database size={16}/>{t('commit')}</Button>}
    </>}
   </div>
  </section>}
  <section className="panel" aria-label={t('importHistory')}>
   <div className="panel-heading"><h2>{t('importHistory')}</h2><Button secondary disabled={busy} onClick={()=>setHistoryRevision(n=>n+1)}>{t('retry')}</Button></div>
   <DataState state={history} t={t} retry={()=>setHistoryRevision(n=>n+1)}>
    {items(history.data).length?<div className="plan-cards">{items(history.data).map((batch:Row)=><button className="mini-plan" key={batch.id} disabled={locked} onClick={()=>openBatch(batch.id)} aria-label={t('importOpen')+' '+batch.id}><span><strong>{batch.kind} · {timestamp(batch.created_at)}</strong><small>{batch.source?.source_id??'—'} · {t('importCount_parsed')}: {fmt(batch.counts?.parsed??batch.row_count)}</small></span><Badge tone={batch.status==='committed'?'green':'amber'}>{batch.status==='committed'?t('importCommitted'):batch.valid?t('preview'):t('noImport')}</Badge></button>)}</div>:<p style={{padding:'0 24px'}}>{t('importHistoryEmpty')}</p>}
    <Pagination data={history.data} cursor={cursor} setCursor={setCursor}/>
   </DataState>
  </section>
 </>;
}
