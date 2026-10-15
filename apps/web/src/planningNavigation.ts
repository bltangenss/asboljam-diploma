import {useCallback,useEffect,useRef} from 'react';

const isList=(path:string)=>path==='/forecasts'||path==='/procurement';
const noOp=()=>{};
type NavigationContext={path:string;scope:string;enabled:boolean};
type PendingPosition={path:string;scope:string;y:number};

/** Restore only a same-session, same-branch planning list after viewing its detail.
 * Positions never leave memory. Slow responses cannot pull the user back after
 * they begin scrolling, typing or clicking; restoration expires after four seconds.
 */
export function usePlanningScrollRestoration(path:string,scope:string,enabled:boolean) {
 const current=useRef<NavigationContext>({path,scope,enabled});
 const positions=useRef(new Map<string,number>());
 const pending=useRef<PendingPosition|null>(null);
 const cancel=useRef<()=>void>(noOp);

 const reset=useCallback(()=>{
  cancel.current();cancel.current=noOp;positions.current.clear();pending.current=null;
  current.current.enabled=false;
 },[]);

 const beforeNavigate=useCallback((destination:string)=>{
  cancel.current();cancel.current=noOp;pending.current=null;
  const previous=current.current;
  if(!previous.enabled)return;
  if(isList(previous.path))positions.current.set(previous.path,Math.max(0,window.scrollY));
  if(!isList(destination)||!previous.path.startsWith(destination+'/'))return;
  const y=positions.current.get(destination);
  if(y===undefined)return;
  pending.current={path:destination,scope:previous.scope,y};
  // Browser Back also restores scroll. Temporarily own this one restoration so
  // the browser cannot race the asynchronous list load. Other routes stay native.
  const previousMode=history.scrollRestoration;
  history.scrollRestoration='manual';
  cancel.current=()=>{history.scrollRestoration=previousMode};
 },[]);

 useEffect(()=>{
  const previous=current.current;
  if(previous.scope!==scope||!enabled){
   reset();
   if(previous.scope&&previous.scope!==scope&&isList(path))window.scrollTo(0,0);
  }
  current.current={path,scope,enabled};
  const target=pending.current;
  if(!enabled||!target||target.path!==path||target.scope!==scope)return;
  pending.current=null;
  const releaseHistory=cancel.current;
  let active=true,frame=0,settled=false;
  let observer:MutationObserver|undefined,resize:ResizeObserver|undefined,timer:number|undefined;
  const stop=()=>{
   if(!active)return;
   active=false;cancelAnimationFrame(frame);observer?.disconnect();resize?.disconnect();
   if(timer!==undefined)window.clearTimeout(timer);
   for(const event of ['wheel','touchstart','pointerdown','keydown'])window.removeEventListener(event,stop,true);
   releaseHistory();if(cancel.current===stop)cancel.current=noOp;
  };
  const attempt=()=>{
   frame=0;
   if(!active||!settled)return;
   const now=current.current;
   if(now.scope!==target.scope||now.path!==target.path||!now.enabled){stop();return}
   // DataState renders this section only after the list request has resolved.
   if(!document.querySelector('#main .planning-history'))return;
   const maxY=Math.max(0,document.documentElement.scrollHeight-window.innerHeight);
   if(maxY+1<target.y)return;
   window.scrollTo(0,target.y);stop();
  };
  const queue=()=>{if(active&&settled&&!frame)frame=requestAnimationFrame(attempt)};
  cancel.current=stop;
  for(const event of ['wheel','touchstart','pointerdown','keydown'])window.addEventListener(event,stop,{capture:true,passive:true});
  observer=new MutationObserver(queue);observer.observe(document.getElementById('main')||document.body,{childList:true,subtree:true});
  resize=new ResizeObserver(queue);resize.observe(document.body);
  // Let the route's useData effect clear the old detail before measuring its list.
  frame=requestAnimationFrame(()=>{frame=requestAnimationFrame(()=>{settled=true;attempt()})});
  timer=window.setTimeout(stop,4000);
  return stop;
 },[path,scope,enabled,reset]);

 // App calls beforeNavigate only when its guarded router accepts a transition.
 // A rejected Back/Forward and its restitution must never change saved positions.
 useEffect(()=>()=>reset(),[reset]);

 return {beforeNavigate,reset};
}
