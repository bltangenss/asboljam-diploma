import {useEffect,useRef,useState} from 'react';
import {AlertTriangle} from 'lucide-react';
import type {Run} from '../../../packages/api-client';
import {api} from './shared';

type Props={runId:string;t:(key:string)=>string;onDone:(id:string)=>void;onDismiss:()=>void};
export default function JobPanel({runId,t,onDone,onDismiss}:Props) {
 const [run,setRun]=useState<Run|null>(null),[error,setError]=useState(false),[attempt,setAttempt]=useState(0);
 const done=useRef(onDone);done.current=onDone;
 useEffect(()=>{
  let active=true;let timer:ReturnType<typeof setTimeout>|undefined;
  const controller=new AbortController();setError(false);
  const poll=async()=>{
   try {
    const next=await api.request<Run>('/runs/'+encodeURIComponent(runId),{signal:controller.signal});
    if(!active)return;
    setRun(next);setError(false);
    if(next.status==='succeeded') {
     if(next.result_id)done.current(next.result_id);else setError(true);
     return;
    }
    if(next.status==='queued'||next.status==='running')timer=setTimeout(poll,1200);
   } catch {if(active)setError(true)}
  };
  void poll();return()=>{active=false;controller.abort();clearTimeout(timer)};
 },[runId,attempt]);
 const failed=run?.status==='failed';
 const status=run?.status||'queued';
 const heartbeat=run?.heartbeat_at;
 const age=typeof heartbeat==='number'&&typeof run?.observed_at==='number'
  ?Math.max(0,Math.floor(run.observed_at-heartbeat)):null;
 const stale=status==='running'&&age!==null&&age>=90;
 return <section className={`alert job-status ${failed?'danger':error||stale?'warning':'info'}`} aria-label={t('jobStatus')}>
  {failed||error||stale?<AlertTriangle size={20}/>:<span className="spinner" aria-hidden="true"/>}
  <div>
   <strong role="status">{error?t('jobConnectionLost'):t('job_'+status)}</strong>
   <p className="job-id">{t('jobId')}: {runId}</p>
   {!error&&!failed&&<p>{t(status==='queued'?'jobQueueHint':'jobRunningHint')}</p>}
   {!error&&status==='running'&&<p>{age===null?t('jobHeartbeatUnknown'):`${t('jobHeartbeatAge')}: ${age} ${t('jobSeconds')}`}</p>}
   {stale&&!error&&<p>{t('jobHeartbeatStale')}</p>}
   {failed&&<p>{run.error||t('jobFailedHint')}</p>}
   {error&&<><p>{t('jobRetryHint')}</p><button className="text-button" onClick={()=>setAttempt(value=>value+1)}>{t('jobCheckStatus')}</button></>}
   {failed&&<button className="text-button" onClick={onDismiss}>{t('jobDismiss')}</button>}
  </div>
 </section>;
}
