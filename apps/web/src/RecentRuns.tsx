import {useState} from 'react';
import {api,Button,Table,type Lang,type Row} from './shared';
import {useEffect} from 'react';

type Props={branch:string;kind:'forecast'|'procurement';t:(key:string)=>string;lang:Lang;onSelect:(id:string)=>void};
export default function RecentRuns({branch,kind,t,lang,onSelect}:Props) {
 const [rows,setRows]=useState<Row[]>([]),[error,setError]=useState(false),[loading,setLoading]=useState(true);
 const [cursor,setCursor]=useState(0),[next,setNext]=useState<string|null>(null),[revision,setRevision]=useState(0);
 useEffect(()=>{
  let active=true;const controller=new AbortController();setLoading(true);setError(false);setRows([]);setNext(null);
  void api.request(`/runs?branch_id=${encodeURIComponent(branch)}&kind=${kind}&limit=20&cursor=${cursor}`,{signal:controller.signal})
   .then(data=>{if(active){setRows(data.items||[]);setNext(data.next_cursor??null)}})
   .catch(()=>{if(active)setError(true)}).finally(()=>{if(active)setLoading(false)});
  return()=>{active=false;controller.abort()};
 },[branch,kind,cursor,revision]);
 return <section className="panel" aria-label={t('jobHistory')}>
  <div className="panel-heading"><div><h2>{t('jobHistory')}</h2><p>{t('jobHistoryHint')}</p></div>
   <Button secondary disabled={loading} onClick={()=>setRevision(value=>value+1)}>{t('jobRefresh')}</Button></div>
  {loading?<p className="form-note" role="status">{t('jobHistoryLoading')}</p>:error?
   <p className="form-note" role="alert">{t('jobHistoryError')}</p>:rows.length===0?
   <p className="form-note">{t('jobHistoryEmpty')}</p>:
   <Table t={t} rows={rows} columns={[
    {key:'id',label:t('jobId'),render:row=><button className="row-link" onClick={()=>onSelect(row.id)} aria-label={`${t('jobOpen')} ${row.id}`}>{String(row.id).slice(0,12)}</button>},
    {key:'created_at',label:t('jobCreated'),render:row=>row.created_at?new Date(row.created_at).toLocaleString(lang==='kk'?'kk-KZ':'ru-RU'):'—'},
    {key:'status',label:t('status'),render:row=>t('job_'+row.status)},
   ]}/>}
  {(cursor>0||next!==null)&&<div className="job-pages">
   <Button secondary disabled={loading||cursor===0} onClick={()=>setCursor(Math.max(0,cursor-20))}>{t('jobPrevious')}</Button>
   <Button secondary disabled={loading||next===null} onClick={()=>{if(next!==null)setCursor(Number(next))}}>{t('jobNext')}</Button>
  </div>}
 </section>;
}
