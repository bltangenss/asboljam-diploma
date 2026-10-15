import {useCallback,useEffect,useRef,useState} from 'react';
import {X} from 'lucide-react';

export type NavigationPhase='clean'|'dirty'|'pending'|'uncertain';
export type NavigationBlocker={read:()=>NavigationPhase;discard:()=>boolean};
export type RegisterNavigationBlocker=(blocker:NavigationBlocker)=>()=>void;
type Marker={session:string;index:number};
type Position={marker:Marker|null;native:number|null;url:string};
type Owner={token:symbol;blocker:NavigationBlocker};
type Prompt={owner:Owner;phase:Exclude<NavigationPhase,'clean'>;proceed:()=>void;historyFallback?:boolean};
const stateKey='asboljamNavigation';
const routeUrl=()=>location.pathname+location.search;
function marker():Marker|null {
 const value=history.state?.[stateKey];
 return value&&typeof value.session==='string'&&Number.isSafeInteger(value.index)?value:null;
}
function nativeIndex():number|null {
 // Feature detection supplies exact distances for older/unmanaged same-document
 // entries too. Managed entries retain their own index in browsers without it.
 const value=(window as Window&{navigation?:{currentEntry?:{index?:number}}}).navigation?.currentEntry?.index;
 return typeof value==='number'&&Number.isSafeInteger(value)?value:null;
}
function position():Position{return {marker:marker(),native:nativeIndex(),url:routeUrl()}}
function distance(from:Position,to:Position):number|null {
 if(from.native!==null&&to.native!==null)return to.native-from.native;
 if(from.marker&&to.marker&&from.marker.session===to.marker.session)return to.marker.index-from.marker.index;
 return null;
}
function stamp(value:Marker){history.replaceState({...history.state,[stateKey]:value},'',location.href)}

/** One owner registers a live, synchronous command/draft state. No payload or
 * credential leaves component memory. Indexed traversals retain Forward entries. */
export function useGuardedNavigation(onNavigate:(url:string,traversal:boolean)=>void,onBlocked:()=>void){
 const callbacks=useRef({onNavigate,onBlocked});callbacks.current={onNavigate,onBlocked};
 const active=useRef<Owner|null>(null),current=useRef<Position|null>(null);
 const restoring=useRef<{origin:Position;after:()=>void;completed?:Array<()=>void>}|null>(null);
 const [prompt,setPrompt]=useState<Prompt|null>(null);
 if(current.current===null){if(!marker())stamp({session:crypto.randomUUID(),index:0});current.current=position()}
 const close=useCallback(()=>setPrompt(null),[]);
 const register=useCallback<RegisterNavigationBlocker>((blocker)=>{
  const owner={token:Symbol('navigation-owner'),blocker};active.current=owner;
  return()=>{if(active.current?.token===owner.token)active.current=null};
 },[]);
 const ask=useCallback((owner:Owner,phase:Exclude<NavigationPhase,'clean'>,proceed:()=>void,historyFallback=false)=>{
  callbacks.current.onBlocked();setPrompt({owner,phase,proceed,historyFallback});
 },[]);
 const request=useCallback(<T,>(action:()=>T):T|undefined=>{
  const owner=active.current,phase=owner?.blocker.read()||'clean';
  if(restoring.current){
   if(phase==='clean'){
    const bounce=restoring.current;
    (bounce.completed??=[]).push(()=>{action()});
    bounce.after=()=>{setPrompt(null);for(const finish of bounce.completed||[])finish()};
   }
   return;
  }
  if(owner&&phase!=='clean'){ask(owner,phase,()=>{action()});return}
  setPrompt(null);return action();
 },[ask]);
 const commitPush=useCallback((url:string)=>{
  const previous=current.current!;
  if(url===previous.url){setPrompt(null);return}
  const previousMarker=previous.marker||{session:crypto.randomUUID(),index:0};
  history.pushState({...history.state,[stateKey]:{session:previousMarker.session,index:previousMarker.index+1}},'',url);
  current.current=position();callbacks.current.onNavigate(url,false);setPrompt(null);
 },[]);
 const go=useCallback((url:string)=>{if(url!==current.current!.url)request(()=>commitPush(url))},[request,commitPush]);
 const force=useCallback((url:string)=>{
  active.current=null;setPrompt(null);
  if(restoring.current){restoring.current.completed=undefined;restoring.current.after=()=>commitPush(url);callbacks.current.onNavigate(url,false)}
  else commitPush(url);
 },[commitPush]);
 const clear=useCallback(()=>{active.current=null;setPrompt(null)},[]);
 const discard=useCallback(()=>{
  if(!prompt)return;
  const owner=active.current;
  if(owner?.token!==prompt.owner.token){setPrompt(null);return}
  const phase=owner.blocker.read();
  if(phase==='pending'||phase==='uncertain'){setPrompt({...prompt,phase});return}
  if(phase==='dirty'&&!owner.blocker.discard())return;
  setPrompt(null);prompt.proceed();
 },[prompt]);
 useEffect(()=>{
  const pop=()=>{
   const target=position(),bounce=restoring.current;
   if(bounce){
    const delta=distance(target,bounce.origin);
    if(delta!==null&&delta!==0){history.go(delta);return}
    restoring.current=null;current.current=bounce.origin;bounce.after();return;
   }
   const origin=current.current!;
   if(target.url===origin.url){current.current=target;return}
   const owner=active.current,phase=owner?.blocker.read()||'clean';
   if(owner&&phase!=='clean'){
    const delta=distance(target,origin);
    if(delta!==null&&delta!==0){
     restoring.current={origin,after:()=>{
      const actual=active.current?.token===owner.token?owner.blocker.read():'clean';
      if(actual==='clean'){setPrompt(null);return}
      ask(owner,actual,()=>history.go(-delta));
     }};
     history.go(delta);return;
    }
    // An old unindexed entry on a browser without native indexes has no exact
    // inverse traversal. Preserve the live command and URL consistency first.
    // This exceptional replacement is disclosed; managed history never uses it.
    const targetState=history.state;
    history.replaceState({...targetState,[stateKey]:{session:crypto.randomUUID(),index:0}},'',origin.url);
    current.current=position();
    ask(owner,phase,()=>{
     history.replaceState(targetState,'',target.url);
     if(!marker())stamp({session:crypto.randomUUID(),index:0});
     current.current=position();callbacks.current.onNavigate(target.url,true);
    },true);return;
   }
   current.current=target;
   if(!target.marker){stamp({session:crypto.randomUUID(),index:0});current.current=position()}
   callbacks.current.onNavigate(target.url,true);setPrompt(null);
  };
  const unload=(event:BeforeUnloadEvent)=>{if(active.current&&active.current.blocker.read()!=='clean'){event.preventDefault();event.returnValue=''}};
  window.addEventListener('popstate',pop);window.addEventListener('beforeunload',unload);
  return()=>{window.removeEventListener('popstate',pop);window.removeEventListener('beforeunload',unload)};
 },[ask]);
 return {go,force,request,register,clear,prompt,close,discard};
}

export function NavigationGuardDialog({prompt,lang,close,discard}:{prompt:Prompt;lang:'kk'|'ru';close:()=>void;discard:()=>void}){
 const ref=useRef<HTMLDialogElement>(null),stayRef=useRef<HTMLButtonElement>(null);
 const w=(kk:string,ru:string)=>lang==='kk'?kk:ru;
 useEffect(()=>{
  const element=ref.current,previous=document.activeElement as HTMLElement|null;
  element?.showModal();stayRef.current?.focus();
  return()=>{element?.close();if(previous?.isConnected)previous.focus()};
 },[]);
 const dirty=prompt.phase==='dirty';
 return <dialog ref={ref} className="planning-dialog navigation-guard-dialog" aria-labelledby="navigation-guard-title" aria-describedby="navigation-guard-description" onCancel={event=>{event.preventDefault();close()}}>
  <div className="dialog-head"><h2 id="navigation-guard-title">{dirty?w('Сақталмаған өзгерістер','Несохранённые изменения'):w('Сақтау нәтижесін тексеріңіз','Проверьте результат сохранения')}</h2><button className="icon-button" aria-label={w('Жабу','Закрыть')} onClick={close}><X size={20}/></button></div>
  <p id="navigation-guard-description">{dirty?w('Дайындау жоспарының өзгерістері сақталмаған. Жоспарда қалыңыз немесе өзгерістерді ашық түрде болдырмаңыз.','Изменения плана приготовления ещё не сохранены. Останьтесь в плане или явно отмените изменения.'):prompt.phase==='pending'?w('Сұрау орындалып жатыр. Нәтиже келгенше осы жоспарда қалыңыз.','Сохранение ещё выполняется. Дождитесь результата в этом плане.'):w('Сақтау жауабы алынбады. Осы жоспарда сол сұрауды қайталап, нәтижені тексеріңіз.','Ответ о сохранении не получен. Вернитесь в план и повторите тот же запрос, чтобы проверить результат.')}</p>
  {prompt.historyFallback&&<p className="alert warning">{w('Браузер тарихының ескі жазбасындағы мекенжай осы жоспарға ауыстырылды. Әрі қарай өту үшін қолданба мәзірін пайдаланыңыз.','Адрес старой записи истории браузера заменён на этот план. Для дальнейшего перехода используйте меню приложения.')}</p>}
  <div className="dialog-actions"><button ref={stayRef} autoFocus className="button secondary" onClick={close}>{w('Жоспарда қалу','Остаться в плане')}</button>{dirty&&<button className="button primary" onClick={discard}>{w('Өзгерістерді болдырмау және өту','Отменить изменения и перейти')}</button>}</div>
 </dialog>;
}
