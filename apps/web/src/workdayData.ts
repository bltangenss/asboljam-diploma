import {useEffect,useState} from 'react';
import {api,type Context,type Row} from './shared';

// Hide a previous branch/account immediately, before the replacement effect runs.
export function useWorkdayData(c:Context,path:string|null,revision=0){
 const scope=JSON.stringify([c.user?.organization_id,c.user?.id,c.user?.role,c.branch,path,c.revision,revision]);
 const [state,setState]=useState<{scope:string;data:Row|null;error:any;loading:boolean}>({scope:'',data:null,error:null,loading:!!path});
 useEffect(()=>{
  let active=true;const controller=new AbortController();
  setState({scope,data:null,error:null,loading:!!path});
  if(path)void api.request<Row>(path,{signal:controller.signal}).then(data=>{if(active)setState({scope,data,error:null,loading:false})}).catch(error=>{if(active)setState({scope,data:null,error,loading:false})});
  return()=>{active=false;controller.abort()};
 },[scope,path]);
 return state.scope===scope?state:{scope,data:null,error:null,loading:!!path};
}
