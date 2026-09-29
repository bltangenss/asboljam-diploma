import {useEffect,useRef,useState,type FormEvent} from 'react';
import {Activity,BarChart3,BookOpen,ChevronDown,ChevronRight,ClipboardCheck,Database,Eye,EyeOff,FileUp,FlaskConical,LayoutDashboard,Leaf,LogOut,Menu,Package,Settings,ShieldCheck,ShoppingBasket,TrendingUp,Truck,WifiOff,ArrowRight} from 'lucide-react';
import {api,words,items,date,ErrorBox,type Lang,type Row,type Context,type WorkspaceSettings} from './shared';
import Dashboard from './Dashboard';
import Onboarding from './Onboarding';
import {Sales,Imports,Reference,Reports} from './DataPages';
import {Forecasts,Procurement} from './Planning';
import type {User} from '../../../packages/api-client';
const nav=[['dashboard',LayoutDashboard],['sales',BarChart3],['forecasts',TrendingUp],['procurement',ShoppingBasket],['inventory',Package],['recipes',BookOpen],['suppliers',Truck],['reports',ClipboardCheck],['imports',FileUp]] as const;
export default function App() {
 const [lang,setLang]=useState<Lang>(localStorage.getItem('asboljam-language')==='ru'?'ru':'kk');
 const t=(key:string)=>words[key]?.[lang==='kk'?0:1]||key;
 const [user,setUser]=useState<User|null>(null),[authLoading,setAuthLoading]=useState(true),[authError,setAuthError]=useState<any>(null);
 const [path,setPath]=useState(location.pathname==='/'?'/dashboard':location.pathname),[branch,setBranch]=useState(''),[branches,setBranches]=useState<Row[]>([]);
 const [workspace,setWorkspace]=useState<WorkspaceSettings|null>(null),[workspaceLoading,setWorkspaceLoading]=useState(false),[workspaceError,setWorkspaceError]=useState<any>(null);
 const [drawer,setDrawer]=useState(false),[online,setOnline]=useState(navigator.onLine),[revision,setRevision]=useState(0);
 const userRef=useRef<User|null>(null),loadEpoch=useRef(0),mounted=useRef(true);
 const go=(destination:string)=>{history.pushState({},'',destination);setPath(destination.split('?')[0]);setDrawer(false);window.scrollTo(0,0)};
 function clearWorkspace() {
  ++loadEpoch.current;setWorkspace(null);setBranches([]);setBranch('');setWorkspaceError(null);setWorkspaceLoading(false);
 }
 function acceptUser(next:User) {
  clearWorkspace();userRef.current=next;setUser(next);setAuthError(null);
 }
 function resetSession(error:any=null) {
  api.csrf='';clearWorkspace();userRef.current=null;setUser(null);setAuthError(error);go('/login');
 }
 async function refreshWorkspace(reloadSession=true) {
  const identity=userRef.current,csrf=api.csrf;
  if(!identity||!csrf)return;
  const epoch=++loadEpoch.current;
  const current=()=>mounted.current&&loadEpoch.current===epoch&&api.csrf===csrf&&userRef.current?.id===identity.id&&userRef.current?.organization_id===identity.organization_id;
  setWorkspaceLoading(true);setWorkspaceError(null);
  try {
   const [settings,session]=await Promise.all([
    api.request<WorkspaceSettings>('/settings'),
    reloadSession?api.request<{user:User;csrf_token:string}>('/session/me'):Promise.resolve({user:identity,csrf_token:csrf}),
   ]);
   if(!current())return;
   if(settings.organization?.id!==identity.organization_id||!['synthetic_only','unconfigured'].includes(settings.organization?.data_policy)
      ||!settings.onboarding||session.user?.id!==identity.id||session.user.organization_id!==identity.organization_id) {
    throw new Error(t('workspaceUnavailable'));
   }
   const branchData=settings.organization.data_policy==='synthetic_only'?await api.request('/branches?limit=200'):{items:[]};
   if(!current())return;
   const allowed=new Set(session.user.branch_ids);
   const visible=items(branchData).filter(item=>allowed.has(String(item.branch_id)));
   userRef.current=session.user;setUser(session.user);
   api.csrf=session.csrf_token;
   setWorkspace(settings);setBranches(visible);
   setBranch(previous=>visible.some(item=>String(item.branch_id)===previous)?previous:visible.length?String(visible[0].branch_id):'');
   setRevision(value=>value+1);
  } catch(error) {
   if(current())setWorkspaceError(error);
  } finally {
   if(mounted.current&&loadEpoch.current===epoch)setWorkspaceLoading(false);
  }
 }
 useEffect(()=>{
  let active=true;mounted.current=true;
  api.onUnauthorized=resetSession;
  api.session().then(next=>{if(active)acceptUser(next)}).catch(error=>{if(active&&error.status!==401)setAuthError(error)}).finally(()=>{if(active)setAuthLoading(false)});
  const pop=()=>setPath(location.pathname),on=()=>setOnline(true),off=()=>setOnline(false);
  window.addEventListener('popstate',pop);window.addEventListener('online',on);window.addEventListener('offline',off);
  return()=>{active=false;mounted.current=false;++loadEpoch.current;api.onUnauthorized=undefined;window.removeEventListener('popstate',pop);window.removeEventListener('online',on);window.removeEventListener('offline',off)};
 },[]);
 useEffect(()=>{localStorage.setItem('asboljam-language',lang);document.documentElement.lang=lang},[lang]);
 useEffect(()=>{if(user)void refreshWorkspace(false)},[user?.id,user?.organization_id]);
 const [section,id]=path.slice(1).split('/');
 const organization=workspace?.organization;
 const synthetic=organization?.data_policy==='synthetic_only';
 const ctx:Context={t,lang,user,branch,go,revision,refresh:()=>setRevision(value=>value+1),online,
  setBranch:value=>{if(branches.some(item=>String(item.branch_id)===value))setBranch(value)},
  organization,workspace:workspace??undefined,refreshWorkspace:()=>refreshWorkspace()};
 if(authLoading)return <div className="full-loading"><Leaf size={36}/><div className="spinner"/><span>AsBoljam</span></div>;
 if(!user)return <Login t={t} lang={lang} setLang={setLang} error={authError} onLogin={(next:User)=>{acceptUser(next);go('/dashboard')}}/>;
 const unscoped=section==='settings'||section==='audit';
 const canBootstrap=synthetic&&user.role==='admin'&&workspace?.onboarding.can_import_branches===true;
 let content;
 if(unscoped)content=<Reference {...ctx} section={section}/>;
 else if(!workspace&&(workspaceLoading||!workspaceError))content=<div className="alert info" role="status"><span className="spinner"/>{t('workspaceLoading')}</div>;
 else if(workspaceError)content=<ErrorBox error={workspaceError} t={t} retry={()=>void refreshWorkspace()}/>;
 else if(!synthetic||(!branch&&!(section==='imports'&&canBootstrap)))content=<Onboarding {...ctx}/>;
 else content=section==='dashboard'?<Dashboard {...ctx}/>:section==='sales'?<Sales {...ctx}/>:section==='forecasts'?<Forecasts {...ctx} id={id}/>:section==='procurement'?<Procurement {...ctx} id={id}/>:section==='imports'?<Imports {...ctx}/>:section==='reports'?<Reports {...ctx}/>:<Reference {...ctx} section={section}/>;
 return <div className="app" key={user.organization_id+':'+user.id}>
  {drawer&&<button className="drawer-overlay" aria-label="Close navigation" onClick={()=>setDrawer(false)}/>}
  <aside className={'sidebar '+(drawer?'open':'')}>
   <a className="brand" href="/dashboard" onClick={event=>{event.preventDefault();go('/dashboard')}}><span className="brand-symbol"><Leaf size={24}/></span><span>AsBoljam<span className="brand-dot">.</span></span></a>
   <div className="workspace-label">{t('workspace')}</div>
   <nav aria-label="Main navigation">{nav.map(([key,Icon])=><button key={key} className={'nav-item '+(section===key?'active':'')} onClick={()=>go('/'+key)}><Icon size={19}/><span>{t(key)}</span>{section===key&&<span className="nav-marker"/>}</button>)}</nav>
   <div className="workspace-label manage-label">{t('management')}</div>
   <nav>{[['settings',Settings],['audit',ShieldCheck]].map(([key,Icon]:any)=><button key={key} className={'nav-item '+(section===key?'active':'')} onClick={()=>go('/'+key)}><Icon size={19}/>{t(key)}</button>)}</nav>
   <div className="sidebar-bottom">
    <div className="sidebar-note"><div className="note-icon"><Leaf size={21}/></div><strong>{organization?.name??'—'}</strong><span>{workspace?t('availableBranches')+': '+branches.length:t('workspaceLoading')}</span><div className="note-line"/></div>
    <div className="user"><span className="avatar">{user.email[0].toUpperCase()}</span><span className="user-info"><strong>{user.email.split('@')[0]}</strong><small>{user.role}</small></span>
     <button className="icon-button" title={t('logout')} onClick={async()=>{const csrf=api.csrf;try{await api.post('/session/logout',{});if(api.csrf===csrf)resetSession()}catch(error){if(api.csrf===csrf)setAuthError(error)}}}><LogOut size={17}/></button>
    </div>
   </div>
  </aside>
  <div className="main-shell">
   <header className="topbar">
    <div className="top-left"><button className="icon-button mobile-menu" aria-label="Navigation" onClick={()=>setDrawer(true)}><Menu/></button><div className="breadcrumb">{t('workspace')}<ChevronRight size={13}/><strong>{t(section)}</strong></div></div>
    <div className="top-right"><label className="branch-select"><span className="branch-dot"/><select aria-label={t('branch')} value={branch} disabled={workspaceLoading||!branches.length} onChange={event=>{setBranch(event.target.value);if(id)go('/'+section)}}>
     {!branches.length&&<option value="">{t('noBranches')}</option>}
     {branches.map(item=><option key={item.branch_id} value={item.branch_id}>{String(item.branch_name)}</option>)}
    </select><ChevronDown size={14}/></label><span className="top-divider"/><button className="language" onClick={()=>setLang(lang==='kk'?'ru':'kk')}>{lang==='kk'?'ҚАЗ':'РУС'}<ChevronDown size={12}/></button><span className="avatar small">{user.email[0].toUpperCase()}</span></div>
   </header>
   <div className="scenario-banner"><div><FlaskConical size={15}/><strong>{workspace?t(synthetic?'syntheticOnly':'dataSetupPending'):t('workspaceLoading')}</strong>{synthetic&&organization?.provenance==='demo_seed'&&workspace?.scenario_date&&<><span className="banner-divider">/</span><span>{t('scenario')}: <b>{date(workspace.scenario_date)}</b></span></>}</div></div>
   <main className="content" id="main">
    {!online&&<div className="alert danger"><WifiOff size={18}/>{t('offline')}</div>}
    {authError&&<ErrorBox error={authError} t={t} retry={()=>{setAuthError(null);ctx.refresh()}}/>}
    {content}
    <footer><span>AsBoljam <span className="footer-dot">·</span>{t('greeting')}</span><span><span className={'connection-dot '+(online?'':'off')}/>{online?'API':'Offline'}<span className="footer-dot">·</span>{workspace?(synthetic?'SYNTHETIC':t('dataSetupPending')):'—'}</span></footer>
   </main>
   <nav className="bottom-nav">{nav.filter(([key])=>['dashboard','forecasts','procurement','inventory'].includes(key)).map(([key,Icon])=><button className={section===key?'active':''} key={key} onClick={()=>go('/'+key)}><Icon size={20}/><span>{t(key)}</span></button>)}<button onClick={()=>setDrawer(true)}><Menu size={20}/><span>{lang==='kk'?'Тағы':'Ещё'}</span></button></nav>
  </div>
 </div>;
}
function Login({t,lang,setLang,error,onLogin}:any){const[email,setEmail]=useState(''),[password,setPassword]=useState(''),[show,setShow]=useState(false),[busy,setBusy]=useState(false),[err,setErr]=useState<any>(error);async function submit(e:FormEvent){e.preventDefault();setBusy(true);setErr(null);try{onLogin(await api.login(email,password))}catch(e){setErr(e)}finally{setBusy(false)}}return <div className="login-page"><div className="login-story"><a className="brand"><span className="brand-symbol"><Leaf size={25}/></span>AsBoljam.</a><div className="story-main"><span className="eyebrow">{t('workspace')}</span><h1>{lang==='kk'?<>Ертеңгі сұраныс.<br/>Бүгінгі сенімді<br/><em>шешім.</em></>:<>Завтрашний спрос.<br/>Уверенное решение<br/><em>сегодня.</em></>}</h1><p>{t('loginSub')}</p><div className="story-flow"><Database/><span/><TrendingUp/><span/><ShoppingBasket/><span/><ShieldCheck/></div></div><span className="story-foot">AsBoljam</span></div><div className="login-panel"><button className="language login-language" onClick={()=>setLang(lang==='kk'?'ru':'kk')}>ҚАЗ / РУС</button><form onSubmit={submit} className="login-form"><span className="login-icon"><Leaf size={27}/></span><h2>{t('login')}</h2><p>{t('loginSub')}</p>{err&&<div role={err.code==='PASSWORD_CHANGED'?'status':'alert'} className={`alert ${err.code==='PASSWORD_CHANGED'?'success':'danger'}`}>{err.code==='PASSWORD_CHANGED'?t('passwordChangedLogin'):err.code==='AUTH_REQUIRED'?(lang==='kk'?'Сессия аяқталды. Қайта кіріңіз.':'Сессия завершена. Войдите снова.'):err.status===401?t('loginError'):err.message}</div>}<label>{t('email')}<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@example.com"/></label><label>{t('password')}<span className="password-wrap"><input type={show?'text':'password'} autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/><button type="button" className="icon-button" aria-label={show?'Hide password':'Show password'} onClick={()=>setShow(!show)}>{show?<EyeOff size={19}/>:<Eye size={19}/>}</button></span></label><button className="button primary wide" disabled={busy}>{busy?<span className="spinner"/>:t('login')}<ArrowRight size={17}/></button><p className="login-hint"><ShieldCheck size={16}/>{t('workspaceLoginHint')}</p><div className="login-demo"><ShieldCheck size={17}/>{t('workspaceLoginNotice')}</div></form></div></div>}
