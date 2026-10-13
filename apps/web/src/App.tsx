import {useEffect,useRef,useState,type FormEvent} from 'react';
import {BarChart3,BookOpen,ChevronDown,ChevronRight,ClipboardCheck,Database,Eye,EyeOff,FileUp,FlaskConical,LayoutDashboard,Leaf,LogOut,Menu,Package,Settings,ShieldCheck,ShoppingBasket,TrendingUp,Truck,WifiOff,ArrowRight,X} from 'lucide-react';
import {api,words,items,date,shiftDate,workspaceData,ErrorBox,type Lang,type Row,type Context,type WorkspaceSettings,type WorkspaceDataContext} from './shared';
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
 const [dataContext,setDataContext]=useState<WorkspaceDataContext>(),[contextError,setContextError]=useState<any>(null);
 const [inventoryDate,setInventoryDate]=useState(''),[forecastOrigin,setForecastOrigin]=useState('');
 const contextEpoch=useRef(0),chosenDates=useRef({branch:'',inventory:'',origin:'',inventoryExplicit:false,originExplicit:false});
 const [drawer,setDrawer]=useState(false),[online,setOnline]=useState(navigator.onLine),[revision,setRevision]=useState(0);
 const [compact,setCompact]=useState(()=>window.matchMedia('(max-width: 1023px)').matches);
 useEffect(()=>{const media=window.matchMedia('(max-width: 1023px)');const changed=()=>{setCompact(media.matches);if(!media.matches)setDrawer(false)};media.addEventListener('change',changed);return()=>media.removeEventListener('change',changed)},[]);
 const drawerRef=useRef<HTMLElement>(null);
 useEffect(()=>{
  if(!drawer)return;
  const previous=document.activeElement as HTMLElement|null;
  const overflow=document.body.style.overflow;
  document.body.style.overflow='hidden';
  const focusable=()=>Array.from(drawerRef.current?.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),select:not(:disabled)')||[]).filter(el=>el.getClientRects().length>0);
  focusable()[0]?.focus();
  const key=(event:KeyboardEvent)=>{
   if(event.key==='Escape'){event.preventDefault();setDrawer(false)}
   if(event.key==='Tab'){const nodes=focusable(),first=nodes[0],last=nodes[nodes.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}
  };
  document.addEventListener('keydown',key);
  return()=>{document.body.style.overflow=overflow;document.removeEventListener('keydown',key);previous?.focus()};
 },[drawer]);
 const userRef=useRef<User|null>(null),loadEpoch=useRef(0),mounted=useRef(true);
 const go=(destination:string)=>{history.pushState({},'',destination);setPath(destination.split('?')[0]);setDrawer(false);window.scrollTo(0,0)};
 function clearWorkspace() {
  ++loadEpoch.current;setWorkspace(null);setBranches([]);setBranch('');setWorkspaceError(null);setWorkspaceLoading(false);
  ++contextEpoch.current;setDataContext(undefined);setContextError(null);setInventoryDate('');setForecastOrigin('');
  chosenDates.current={branch:'',inventory:'',origin:'',inventoryExplicit:false,originExplicit:false};
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
   if(settings.organization?.id!==identity.organization_id||!['synthetic_only','real_only','unconfigured'].includes(settings.organization?.data_policy)
      ||!settings.onboarding||session.user?.id!==identity.id||session.user.organization_id!==identity.organization_id) {
    throw new Error(t('workspaceUnavailable'));
   }
   const configured=settings.organization.data_policy!=='unconfigured'&&(workspaceData(settings,null)?.operations_enabled===true);
   const branchData=configured?await api.request('/branches?limit=200'):{items:[]};
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
 useEffect(()=>{
  const epoch=++contextEpoch.current,identity=userRef.current,csrf=api.csrf;
  setContextError(null);
  if(!workspace||!identity)return;
  const globalContext=workspaceData(workspace,null);
  if(!branch){setDataContext(globalContext);setInventoryDate('');setForecastOrigin('');return}
  const current=()=>mounted.current&&contextEpoch.current===epoch&&api.csrf===csrf&&userRef.current?.id===identity.id&&userRef.current?.organization_id===identity.organization_id;
  (async()=>{try{
   const response=workspace.data_context?await api.request<WorkspaceSettings>('/settings?branch_id='+encodeURIComponent(branch)):workspace;
   const context=workspaceData(response,branch);
   if(!current())return;
   if(response.organization.id!==identity.organization_id||!context||context.branch_id!==branch||context.data_origin!==(workspace.organization.data_policy==='real_only'?'REAL':'SYNTHETIC'))throw new Error(t('workspaceUnavailable'));
   const previous=chosenDates.current,same=previous.branch===branch;
   const keepInventory=same&&previous.inventoryExplicit&&context.inventory_dates.includes(previous.inventory);
   const maxOrigin=context.business_date?shiftDate(context.business_date,-1):context.history_end;
   const keepOrigin=same&&previous.originExplicit&&/^\d{4}-\d{2}-\d{2}$/.test(previous.origin)&&(!context.history_start||previous.origin>=context.history_start)&&(!maxOrigin||previous.origin<=maxOrigin);
   const inventory=keepInventory?previous.inventory:context.inventory_date||'',origin=keepOrigin?previous.origin:context.forecast_origin||'';
   chosenDates.current={branch,inventory,origin,inventoryExplicit:keepInventory,originExplicit:keepOrigin};
   setDataContext(context);setInventoryDate(inventory);setForecastOrigin(origin);
  }catch(error){if(current()){setDataContext(undefined);setContextError(error)}}})();
  return()=>{++contextEpoch.current};
 },[workspace,branch,user?.id,user?.organization_id]);
 const [section,id]=path.slice(1).split('/');
 const organization=workspace?.organization;
 const synthetic=organization?.data_policy==='synthetic_only';
 const globalContext=workspace?workspaceData(workspace,null):undefined;
 const currentContext=dataContext?.branch_id===(branch||null)?dataContext:globalContext;
 const operations=globalContext?.operations_enabled===true;
 const ctx:Context={t,lang,user,branch,branchName:branches.find(item=>String(item.branch_id)===branch)?.branch_name,go,revision,refresh:()=>setRevision(value=>value+1),online,
  setBranch:value=>{if(branches.some(item=>String(item.branch_id)===value))setBranch(value)},
  organization,workspace:workspace??undefined,refreshWorkspace:()=>refreshWorkspace(),dataContext:currentContext,
  inventoryDate,forecastOrigin,setInventoryDate:value=>{if(currentContext?.inventory_dates.includes(value)){chosenDates.current={...chosenDates.current,inventory:value,inventoryExplicit:true};setInventoryDate(value)}},
  setForecastOrigin:value=>{chosenDates.current={...chosenDates.current,origin:value,originExplicit:true};setForecastOrigin(value)}};
 if(authLoading)return <div className="full-loading"><Leaf size={36}/><div className="spinner"/><span>AsBoljam</span></div>;
 if(!user)return <Login t={t} lang={lang} setLang={setLang} error={authError} onLogin={(next:User)=>{acceptUser(next);go('/dashboard')}}/>;
 const unscoped=section==='settings'||section==='audit';
 const canBootstrap=operations&&user.role==='admin'&&workspace?.onboarding.can_import_branches===true;
 let content;
 if(unscoped)content=<Reference {...ctx} section={section}/>;
 else if(!workspace&&(workspaceLoading||!workspaceError))content=<div className="alert info" role="status"><span className="spinner"/>{t('workspaceLoading')}</div>;
 else if(workspaceError)content=<ErrorBox error={workspaceError} t={t} retry={()=>void refreshWorkspace()}/>;
 else if(!operations||(!branch&&!(section==='imports'&&canBootstrap)))content=<Onboarding {...ctx}/>;
 else if(contextError&&section!=='imports')content=<ErrorBox error={contextError} t={t} retry={()=>void refreshWorkspace()}/>;
 else if(branch&&dataContext?.branch_id!==branch&&section!=='imports')content=<div className="alert info" role="status">{t('workspaceLoading')}</div>;
 else content=section==='dashboard'?<Dashboard {...ctx}/>:section==='sales'?<Sales {...ctx}/>:section==='forecasts'?<Forecasts {...ctx} id={id}/>:section==='procurement'?<Procurement {...ctx} id={id}/>:section==='imports'?<Imports {...ctx}/>:section==='reports'?<Reports {...ctx}/>:<Reference {...ctx} section={section}/>;
 return <div className="app" key={user.organization_id+':'+user.id}>
  <a className="skip-link" href="#main">{lang==='kk'?'Негізгі мазмұнға өту':'Перейти к содержимому'}</a>
  {drawer&&<button className="drawer-overlay" aria-label={lang==='kk'?'Мәзірді жабу':'Закрыть меню'} tabIndex={-1} onClick={()=>setDrawer(false)}/>}
  <aside ref={drawerRef} id="workspace-navigation" inert={compact&&!drawer?true:undefined} aria-hidden={compact&&!drawer?true:undefined} role={drawer?'dialog':undefined} aria-modal={drawer?true:undefined} aria-label={lang==='kk'?'Жұмыс мәзірі':'Рабочее меню'} className={'sidebar '+(drawer?'open':'')}>
   {drawer&&<button className="icon-button drawer-close" aria-label={lang==='kk'?'Мәзірді жабу':'Закрыть меню'} onClick={()=>setDrawer(false)}><X/></button>}
   <a className="brand" href="/dashboard" onClick={event=>{event.preventDefault();go('/dashboard')}}><span className="brand-symbol"><Leaf size={24}/></span><span>AsBoljam<span className="brand-dot">.</span></span></a>
   {[[lang==='kk'?'ЖҰМЫС КҮНІ':'РАБОЧИЙ ДЕНЬ',['dashboard','sales','forecasts','procurement']],[lang==='kk'?'ДЕРЕКТЕР МЕН ҚОР':'ДАННЫЕ И ЗАПАСЫ',['inventory','recipes','suppliers','imports','reports']]].map(([label,keys])=><div className="nav-group" key={String(label)}><div className="workspace-label">{label}</div><nav aria-label={String(label)}>{nav.filter(([key])=>keys.includes(key)).map(([key,Icon])=><button key={key} aria-current={section===key?'page':undefined} className={'nav-item '+(section===key?'active':'')} onClick={()=>go('/'+key)}><Icon size={19}/><span>{t(key)}</span>{section===key&&<span className="nav-marker"/>}</button>)}</nav></div>)}
   <div className="workspace-label manage-label">{t('management')}</div>
   <nav aria-label={t('management')}>{[['settings',Settings],['audit',ShieldCheck]].map(([key,Icon]:any)=><button key={key} aria-current={section===key?'page':undefined} className={'nav-item '+(section===key?'active':'')} onClick={()=>go('/'+key)}><Icon size={19}/>{t(key)}</button>)}</nav>
   <div className="sidebar-bottom">
    <div className="sidebar-note"><strong>{organization?.name??'—'}</strong><span>{workspace?t('availableBranches')+': '+branches.length:t('workspaceLoading')}</span></div>
    <div className="user"><span className="avatar">{user.email[0].toUpperCase()}</span><span className="user-info"><strong>{user.email.split('@')[0]}</strong><small>{t('role_'+user.role)}</small></span>
     <button className="icon-button" title={t('logout')} onClick={async()=>{const csrf=api.csrf;try{await api.post('/session/logout',{});if(api.csrf===csrf)resetSession()}catch(error){if(api.csrf===csrf)setAuthError(error)}}}><LogOut size={17}/></button>
    </div>
   </div>
  </aside>
  <div className="main-shell" inert={drawer?true:undefined}>
   <header className="topbar">
    <div className="top-left"><button className="icon-button mobile-menu" aria-label={lang==='kk'?'Мәзірді ашу':'Открыть меню'} aria-expanded={drawer} aria-controls="workspace-navigation" onClick={()=>setDrawer(true)}><Menu/></button><div className="breadcrumb">AsBoljam<ChevronRight size={13}/><strong>{t(section)}</strong></div></div>
    <div className="top-right"><label className="branch-select"><span className="branch-dot"/><select aria-label={t('branch')} value={branch} disabled={workspaceLoading||!branches.length} onChange={event=>{setBranch(event.target.value);if(id)go('/'+section)}}>
     {!branches.length&&<option value="">{t('noBranches')}</option>}
     {branches.map(item=><option key={item.branch_id} value={item.branch_id}>{String(item.branch_name)}</option>)}
    </select><ChevronDown size={14}/></label><span className="top-divider"/><button className="language" onClick={()=>setLang(lang==='kk'?'ru':'kk')}>{lang==='kk'?'ҚАЗ':'РУС'}<ChevronDown size={12}/></button><span className="avatar small">{user.email[0].toUpperCase()}</span></div>
   </header>
   <div className="scenario-banner"><div><FlaskConical size={15}/><strong>{workspace?t(globalContext?.usage_mode==='TEST'?'testDataContext':globalContext?.usage_mode==='PILOT'?'pilotDataContext':synthetic?'syntheticOnly':globalContext?.data_origin==='REAL'?'realOnly':'dataSetupPending'):t('workspaceLoading')}</strong>{globalContext?.data_origin==='REAL'&&<span> · REAL</span>}{synthetic&&organization?.provenance==='demo_seed'&&currentContext?.target_date&&<><span className="banner-divider">/</span><span>{t('scenario')}: <b>{date(currentContext.target_date)}</b></span></>}</div></div>
   <main className="content" id="main" tabIndex={-1}>
    {!online&&<div className="alert danger"><WifiOff size={18}/>{t('offline')}</div>}
    {authError&&<ErrorBox error={authError} t={t} retry={()=>{setAuthError(null);ctx.refresh()}}/>}
    {currentContext?.dates_editable&&dataContext?.branch_id===branch&&section==='inventory'&&<div className="filters"><label>{t('inventoryDate')}<select aria-label={t('inventoryDate')} value={inventoryDate} onChange={event=>ctx.setInventoryDate(event.target.value)}>{!inventoryDate&&<option value="">{t('snapshotMissing')}</option>}{currentContext.inventory_dates.map(value=><option key={value} value={value}>{date(value)}</option>)}</select></label></div>}
    {content}
    <footer><span>AsBoljam <span className="footer-dot">·</span>{lang==='kk'?'Дерекке сүйенген шешім':'Решения на основе данных'}</span><span>{!online&&<><WifiOff size={14}/>{lang==='kk'?'Желі жоқ':'Нет сети'}<span className="footer-dot">·</span></>}{globalContext?.data_origin??'—'}</span></footer>
   </main>
   <nav className="bottom-nav">{nav.filter(([key])=>['dashboard','forecasts','procurement','inventory'].includes(key)).map(([key,Icon])=><button className={section===key?'active':''} key={key} onClick={()=>go('/'+key)}><Icon size={20}/><span>{t(key)}</span></button>)}<button onClick={()=>setDrawer(true)}><Menu size={20}/><span>{lang==='kk'?'Тағы':'Ещё'}</span></button></nav>
  </div>
 </div>;
}
function Login({t,lang,setLang,error,onLogin}:any){
 const[email,setEmail]=useState(''),[password,setPassword]=useState(''),[show,setShow]=useState(false),[busy,setBusy]=useState(false),[err,setErr]=useState<any>(error);
 const copy=(kk:string,ru:string)=>lang==='kk'?kk:ru;
 async function submit(e:FormEvent){e.preventDefault();setBusy(true);setErr(null);try{onLogin(await api.login(email,password))}catch(e){setErr(e)}finally{setBusy(false)}}
 return <div className="login-page">
  <div className="login-story">
   <div className="brand"><span className="brand-symbol"><Leaf size={25}/></span>AsBoljam<span className="brand-dot">.</span></div>
   <div className="story-main">
    <span className="eyebrow">{copy('АСҮЙДІ ЖОСПАРЛАУ, ТҮСІНІКТІ ТІЛДЕ','ПЛАНИРОВАНИЕ КУХНИ, ПОНЯТНЫМ ЯЗЫКОМ')}</span>
    <h1>{copy('Сұранысты біліңіз.','Понимайте спрос.')}<br/><em>{copy('Сатып алуды жоспарлаңыз.','Планируйте закупки.')}</em></h1>
    <p>{copy('Сатылым, рецепт және қор — бір жұмыс кеңістігінде. Қанша керек екенін есептеп, шешімді өзіңіз қабылдаңыз.','Продажи, рецептуры и остатки — в одном рабочем пространстве. Рассчитайте потребность и примите решение сами.')}</p>
    <div className="story-workflow" aria-label={copy('Жұмыс тәртібі','Порядок работы')}>
     <div><span>01</span><Database size={22}/><strong>{copy('Деректерді қосыңыз','Загрузите данные')}</strong></div>
     <div><span>02</span><TrendingUp size={22}/><strong>{copy('Болжамды тексеріңіз','Проверьте прогноз')}</strong></div>
     <div><span>03</span><ShoppingBasket size={22}/><strong>{copy('Сатып алуды шешіңіз','Решите, что закупать')}</strong></div>
    </div>
   </div>
   <span className="story-foot">{copy('Есептеу — жүйеде. Соңғы шешім — сізде.','Расчёт — в системе. Последнее слово — за вами.')}</span>
  </div>
  <div className="login-panel">
   <button className="language login-language" aria-label={copy('Тілді ауыстыру','Переключить язык')} onClick={()=>setLang(lang==='kk'?'ru':'kk')}>ҚАЗ / РУС</button>
   <form onSubmit={submit} className="login-form">
    <span className="eyebrow">{copy('ҚАЙТА ҚОШ КЕЛДІҢІЗ','С ВОЗВРАЩЕНИЕМ')}</span><h2>{t('login')}</h2><p>{copy('Филиалыңыздың жұмыс кеңістігін ашыңыз.','Откройте рабочее пространство вашего филиала.')}</p>
    {err&&<div role={err.code==='PASSWORD_CHANGED'?'status':'alert'} className={`alert ${err.code==='PASSWORD_CHANGED'?'success':'danger'}`}>{err.code==='PASSWORD_CHANGED'?t('passwordChangedLogin'):err.code==='AUTH_REQUIRED'?copy('Сессия аяқталды. Қайта кіріңіз.','Сессия завершена. Войдите снова.'):err.status===401?t('loginError'):err.message}</div>}
    <label>{t('email')}<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@example.com"/></label>
    <div className="login-password-field"><label htmlFor="login-password">{t('password')}</label><span className="password-wrap"><input id="login-password" type={show?'text':'password'} autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/><button type="button" className="icon-button" title={show?copy('Құпиясөзді жасыру','Скрыть пароль'):copy('Құпиясөзді көрсету','Показать пароль')} aria-pressed={show} onClick={()=>setShow(!show)}>{show?<EyeOff size={19}/>:<Eye size={19}/>}</button></span></div>
    <button className="button primary wide" disabled={busy}>{busy?<><span className="spinner"/>{copy('Кіру…','Входим…')}</>:t('login')}<ArrowRight size={17}/></button>
    <p className="login-hint"><ShieldCheck size={16}/>{t('workspaceLoginHint')}</p><div className="login-demo">{t('workspaceLoginNotice')}</div>
   </form>
  </div>
 </div>
}
