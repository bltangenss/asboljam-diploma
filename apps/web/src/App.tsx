import {useEffect,useRef,useState,type FormEvent} from 'react';
import {CalendarDays,ChevronDown,Eye,EyeOff,FlaskConical,LogOut,MapPin,Menu,Search,ShieldCheck,ShoppingBasket,TrendingUp,UserRound,WifiOff,ArrowRight,X,Store} from 'lucide-react';
import {CommandPalette} from './CommandPalette';
import Register from './Register';
import Profile from './Profile';
import DayClose from './DayClose';
import {BRAND,Logo} from './Logo';
import {api,words,items,date,shiftDate,workspaceData,ErrorBox,type Lang,type Row,type Context,type WorkspaceSettings,type WorkspaceDataContext} from './shared';
import Dashboard from './Dashboard';
import DataWorkspace from './DataWorkspace';
import {workdaySections,managementSection,sectionGroup,SectionNavigation} from './WorkdayNavigation';
import Onboarding from './Onboarding';
import {Sales,Imports,Reference,Reports} from './DataPages';
import {Forecasts,Procurement} from './Planning';
import {usePlanningScrollRestoration} from './planningNavigation';
import {NavigationGuardDialog,useGuardedNavigation} from './navigationGuard';
import type {User} from '../../../packages/api-client';

export default function App() {
 const [lang,setLang]=useState<Lang>(localStorage.getItem('asboljam-language')==='ru'?'ru':'kk');
 const t=(key:string)=>words[key]?.[lang==='kk'?0:1]||key;
 const [user,setUser]=useState<User|null>(null),[authLoading,setAuthLoading]=useState(true),[authError,setAuthError]=useState<any>(null);
 const [route,setRoute]=useState((location.pathname==='/'?'/dashboard':location.pathname)+location.search),[branch,setBranch]=useState(''),[branches,setBranches]=useState<Row[]>([]);
 const path=route.split('?')[0];
 const [workspace,setWorkspace]=useState<WorkspaceSettings|null>(null),[workspaceLoading,setWorkspaceLoading]=useState(false),[workspaceError,setWorkspaceError]=useState<any>(null);
 const [dataContext,setDataContext]=useState<WorkspaceDataContext>(),[contextError,setContextError]=useState<any>(null);
 const [inventoryDate,setInventoryDate]=useState(''),[forecastOrigin,setForecastOrigin]=useState('');
 const contextEpoch=useRef(0),chosenDates=useRef({branch:'',inventory:'',origin:'',inventoryExplicit:false,originExplicit:false});
 const [drawer,setDrawer]=useState(false),[online,setOnline]=useState(navigator.onLine),[revision,setRevision]=useState(0);
 const [palette,setPalette]=useState(false),[userMenu,setUserMenu]=useState(false),[cities,setCities]=useState<Record<string,Row>>({});
 useEffect(()=>{const key=(event:KeyboardEvent)=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();setPalette(open=>!open)}};document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key)},[]);
 useEffect(()=>{if(!userMenu)return;const close=(event:MouseEvent|KeyboardEvent)=>{if(event instanceof KeyboardEvent?event.key==='Escape':!(event.target as HTMLElement).closest('.user-menu'))setUserMenu(false)};document.addEventListener('mousedown',close);document.addEventListener('keydown',close);return()=>{document.removeEventListener('mousedown',close);document.removeEventListener('keydown',close)}},[userMenu]);
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
 const planningScroll=usePlanningScrollRestoration(path,JSON.stringify([user?.organization_id,user?.id,user?.role,branch]),Boolean(user&&branch));
 const navigation=useGuardedNavigation((destination,traversal)=>{const accepted=destination==='/'||destination.startsWith('/?')?'/dashboard'+destination.slice(1):destination;planningScroll.beforeNavigate(accepted.split('?')[0]);setRoute(accepted);setDrawer(false);if(!traversal)window.scrollTo(0,0)},()=>setDrawer(false));
 const go=navigation.go;
 // Choosing the page that is already open from the drawer only closes the drawer.
 const drawerGo=(url:string)=>{if(url===location.pathname+location.search)setDrawer(false);else go(url)};
 function clearWorkspace() {
  planningScroll.reset();
  ++loadEpoch.current;setWorkspace(null);setBranches([]);setBranch('');setWorkspaceError(null);setWorkspaceLoading(false);
  ++contextEpoch.current;setDataContext(undefined);setContextError(null);setInventoryDate('');setForecastOrigin('');
  chosenDates.current={branch:'',inventory:'',origin:'',inventoryExplicit:false,originExplicit:false};
 }
 function acceptUser(next:User) {
  navigation.clear();clearWorkspace();userRef.current=next;setUser(next);setAuthError(null);
 }
 function resetSession(error:any=null) {
  api.csrf='';navigation.clear();clearWorkspace();userRef.current=null;setUser(null);setAuthError(error);navigation.force('/login');
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
  const on=()=>setOnline(true),off=()=>setOnline(false);
  window.addEventListener('online',on);window.addEventListener('offline',off);
  return()=>{active=false;mounted.current=false;++loadEpoch.current;api.onUnauthorized=undefined;window.removeEventListener('online',on);window.removeEventListener('offline',off)};
 },[]);
 useEffect(()=>{localStorage.setItem('asboljam-language',lang);document.documentElement.lang=lang},[lang]);
 useEffect(()=>{if(user)void refreshWorkspace(false)},[user?.id,user?.organization_id]);
 // The establishment's city is shown next to its name; a missing profile simply shows no city.
 useEffect(()=>{if(!workspace||workspace.organization.data_policy==='unconfigured'){setCities({});return}let active=true;api.request('/branch-profiles').then((data:any)=>{if(active)setCities(Object.fromEntries(items(data).map((row:Row)=>[String(row.branch_id),row.city])))}).catch(()=>{if(active)setCities({})});return()=>{active=false}},[workspace]);
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
 const logout=()=>navigation.request(async()=>{const csrf=api.csrf;try{await api.post('/session/logout',{});if(api.csrf===csrf)resetSession()}catch(error){if(api.csrf===csrf)setAuthError(error)}});
 const changeBranch=(value:string,leaveDetail=false)=>{if(value!==branch&&branches.some(item=>String(item.branch_id)===value))navigation.request(()=>{setBranch(value);if(leaveDetail&&id)go('/'+section)})};
 const branchName=branches.find(item=>String(item.branch_id)===branch)?.branch_name;
 const ctx:Context={route,t,lang,user,branch,branchName:branches.find(item=>String(item.branch_id)===branch)?.branch_name,go,revision,refresh:()=>navigation.request(()=>setRevision(value=>value+1)),online,
  setBranch:value=>changeBranch(value),registerNavigationBlocker:navigation.register,
  organization,workspace:workspace??undefined,refreshWorkspace:async()=>{await navigation.request(()=>refreshWorkspace())},dataContext:currentContext,
  inventoryDate,forecastOrigin,setInventoryDate:value=>{if(currentContext?.inventory_dates.includes(value)){chosenDates.current={...chosenDates.current,inventory:value,inventoryExplicit:true};setInventoryDate(value)}},
  setForecastOrigin:value=>{chosenDates.current={...chosenDates.current,origin:value,originExplicit:true};setForecastOrigin(value)}};
 if(authLoading)return <div className="full-loading"><Logo size={40}/><div className="spinner"/></div>;
 if(!user)return <Login t={t} lang={lang} setLang={setLang} error={authError} onLogin={(next:User)=>{acceptUser(next);go('/dashboard')}}/>;
 const kk=lang==='kk';
 const unscoped=section==='settings'||section==='profile'||section==='audit';
 const canBootstrap=operations&&user.role==='admin'&&workspace?.onboarding.can_import_branches===true;
 let content;
 if(section==='settings'||section==='profile')content=<Profile {...ctx} cities={cities}/>;
 else if(unscoped)content=<Reference {...ctx} section={section}/>;
 else if(!workspace&&(workspaceLoading||!workspaceError))content=<div className="alert info" role="status"><span className="spinner"/>{t('workspaceLoading')}</div>;
 else if(workspaceError)content=<ErrorBox error={workspaceError} t={t} retry={()=>void refreshWorkspace()}/>;
 else if(!operations||(!branch&&!(section==='imports'&&canBootstrap)))content=<Onboarding {...ctx}/>;
 else if(contextError&&section!=='imports')content=<ErrorBox error={contextError} t={t} retry={()=>void refreshWorkspace()}/>;
 else if(branch&&dataContext?.branch_id!==branch&&section!=='imports')content=<div className="alert info" role="status">{t('workspaceLoading')}</div>;
 else content=section==='dashboard'?<Dashboard {...ctx}/>:section==='day-close'?<DayClose {...ctx}/>:section==='data'?<DataWorkspace {...ctx}/>:section==='sales'?<Sales {...ctx}/>:section==='forecasts'?<Forecasts {...ctx} id={id}/>:section==='procurement'?<Procurement {...ctx} id={id}/>:section==='imports'?<Imports {...ctx}/>:section==='reports'?<Reports {...ctx}/>:<Reference {...ctx} section={section}/>;
 const city=cities[branch],cityName=city?.name?.[kk?'kk':'ru'];
 const modeText=workspace?t(globalContext?.usage_mode==='TEST'?'testDataContext':globalContext?.usage_mode==='PILOT'?'pilotDataContext':synthetic?'syntheticOnly':globalContext?.data_origin==='REAL'?'realOnly':'dataSetupPending'):t('workspaceLoading');
 const activeGroup=sectionGroup(section)?.key;
 const profileLabel=managementSection.label[kk?0:1];
 return <div className="app" key={user.organization_id+':'+user.id}>
  <a className="skip-link" href="#main">{kk?'Негізгі мазмұнға өту':'Перейти к содержимому'}</a>
  {drawer&&<button className="drawer-overlay" aria-label={kk?'Мәзірді жабу':'Закрыть меню'} tabIndex={-1} onClick={()=>setDrawer(false)}/>}
  {/* Compact screens: the same five sections and the profile in a drawer. */}
  <aside ref={drawerRef} id="workspace-navigation" inert={compact&&!drawer?true:undefined} aria-hidden={compact&&!drawer?true:undefined} role={drawer?'dialog':undefined} aria-modal={drawer?true:undefined} aria-label={kk?'Жұмыс мәзірі':'Рабочее меню'} className={'sidebar '+(drawer?'open':'')}>
   {drawer&&<button className="icon-button drawer-close" aria-label={kk?'Мәзірді жабу':'Закрыть меню'} onClick={()=>setDrawer(false)}><X/></button>}
   <a className="brand" href="/dashboard" aria-label={BRAND} onClick={event=>{event.preventDefault();drawerGo('/dashboard')}}><Logo size={30}/></a>
   <nav aria-label={kk?'Бөлімдер':'Разделы'}>{workdaySections.map(({key,label,icon:Icon})=><button key={key} aria-current={activeGroup===key?'page':undefined} className={'nav-item '+(activeGroup===key?'active':'')} onClick={()=>drawerGo('/'+key)}><Icon size={19}/><span>{label[kk?0:1]}</span></button>)}
    <button aria-current={activeGroup==='settings'?'page':undefined} className={'nav-item '+(activeGroup==='settings'?'active':'')} onClick={()=>drawerGo('/profile')}><UserRound size={19}/><span>{profileLabel}</span></button></nav>
   <div className="sidebar-bottom">
    <div className="sidebar-note"><strong>{branchName||organization?.name||'—'}</strong><span>{cityName||organization?.name||t('workspaceLoading')}</span></div>
    <div className="user"><span className="avatar">{user.email[0].toUpperCase()}</span><span className="user-info"><strong>{user.email.split('@')[0]}</strong><small>{t('role_'+user.role)}</small></span>
     <button className="icon-button" title={t('logout')} onClick={logout}><LogOut size={17}/></button>
    </div>
   </div>
  </aside>
  <div className="main-shell" inert={drawer?true:undefined}>
   <header className="app-header">
    <button className="icon-button mobile-menu" aria-label={kk?'Мәзірді ашу':'Открыть меню'} aria-expanded={drawer} aria-controls="workspace-navigation" onClick={()=>setDrawer(true)}><Menu/></button>
    <a className="brand header-brand" href="/dashboard" aria-label={BRAND} onClick={event=>{event.preventDefault();go('/dashboard')}}><Logo size={28}/></a>
    {/* Five plain sections in the order of the working day. */}
    <nav className="app-nav" aria-label={kk?'Жұмыс күні':'Рабочий день'}>{workdaySections.map(({key,label,icon:Icon})=>{const active=activeGroup===key;return <button key={key} aria-current={active?'page':undefined} className={'app-nav-item'+(active?' active':'')} onClick={()=>go('/'+key)}><Icon size={17} aria-hidden="true"/><span>{label[kk?0:1]}</span></button>})}</nav>
    <div className="app-tools">
     <button className="command-trigger" aria-label={kk?'Іздеу және командалар':'Поиск и команды'} title="Ctrl K" onClick={()=>setPalette(true)}><Search size={17}/></button>
     {/* Each establishment works in its own cabinet. Its account sees only its name here;
         only an organization account with several branches can switch between cabinets. */}
     <div className="cabinet">{branches.length>1
      ?<label className="cabinet-switch" title={kk?'Кабинетті ауыстыру':'Сменить кабинет'}><Store size={16} aria-hidden="true"/><select aria-label={t('branch')} value={branch} disabled={workspaceLoading} onChange={event=>changeBranch(event.target.value,true)}>
       {branches.map(item=><option key={item.branch_id} value={item.branch_id}>{String(item.branch_name)}</option>)}
      </select><ChevronDown size={14} aria-hidden="true"/></label>
      :<span className="cabinet-name"><Store size={16} aria-hidden="true"/><strong>{branches.length?String(branches[0].branch_name):workspaceLoading?t('workspaceLoading'):t('noBranches')}</strong></span>}
      {cityName&&<span className="cabinet-city"><MapPin size={13} aria-hidden="true"/>{cityName}</span>}
     </div>
     <button className="language" title={kk?'Тілді ауыстыру':'Переключить язык'} onClick={()=>setLang(kk?'ru':'kk')}>{kk?'ҚАЗ':'РУС'}</button>
     <div className="user-menu"><button className="avatar small user-menu-trigger" aria-haspopup="menu" aria-expanded={userMenu} aria-label={user.email} onClick={()=>setUserMenu(open=>!open)}>{user.email[0].toUpperCase()}</button>
      {userMenu&&<div className="user-menu-panel" role="menu"><div className="user-menu-identity"><strong>{user.email}</strong><small>{t('role_'+user.role)}</small></div><div className="user-menu-org"><span>{kk?'Кабинет':'Кабинет'}</span><strong>{branchName||'—'}</strong><span>{organization?.name??'—'}{branches.length>1?' · '+t('availableBranches')+': '+branches.length:''}</span></div>
       <button role="menuitem" className="user-menu-item" onClick={()=>{setUserMenu(false);go('/profile')}}><UserRound size={16}/>{profileLabel}</button>
       <button role="menuitem" className="user-menu-item" title={t('logout')} onClick={()=>{setUserMenu(false);logout()}}><LogOut size={16}/>{t('logout')}</button></div>}
     </div>
    </div>
   </header>
   <div className="scenario-banner" role="note"><div><span className="mode-dot" aria-hidden="true"/><strong>{modeText}</strong>{globalContext?.data_origin==='REAL'&&<span> · REAL</span>}{synthetic&&organization?.provenance==='demo_seed'&&currentContext?.target_date&&<><span className="banner-divider">·</span><span>{t('scenario')}: <b>{date(currentContext.target_date)}</b></span></>}</div></div>
   <main className="content" id="main" tabIndex={-1}>
    {!online&&<div className="alert danger"><WifiOff size={18}/>{t('offline')}</div>}
    {authError&&<ErrorBox error={authError} t={t} retry={()=>{setAuthError(null);ctx.refresh()}}/>}
    {currentContext?.dates_editable&&dataContext?.branch_id===branch&&section==='inventory'&&<div className="filters"><label>{t('inventoryDate')}<select aria-label={t('inventoryDate')} value={inventoryDate} onChange={event=>ctx.setInventoryDate(event.target.value)}>{!inventoryDate&&<option value="">{t('snapshotMissing')}</option>}{currentContext.inventory_dates.map(value=><option key={value} value={value}>{date(value)}</option>)}</select></label></div>}
    <SectionNavigation context={ctx} section={section}/>
    {content}
    <footer><span>{BRAND}<span className="footer-dot">·</span>{kk?'Ертеңгі сұранысты бүгін біліңіз':'Знайте завтрашний спрос сегодня'}</span><span>{!online&&<><WifiOff size={14}/>{kk?'Желі жоқ':'Нет сети'}<span className="footer-dot">·</span></>}{globalContext?.data_origin??'—'}</span></footer>
   </main>
   <nav className="bottom-nav" aria-label={kk?'Жылдам навигация':'Быстрая навигация'}>{workdaySections.filter(({key})=>key!=='data').map(({key,label,icon:Icon})=><button aria-current={activeGroup===key?'page':undefined} className={activeGroup===key?'active':''} key={key} onClick={()=>go('/'+key)}><Icon size={20}/><span>{label[kk?0:1]}</span></button>)}<button onClick={()=>setDrawer(true)}><Menu size={20}/><span>{kk?'Тағы':'Ещё'}</span></button></nav>
  </div>
  <CommandPalette open={palette} close={()=>setPalette(false)} go={go} lang={lang} setLang={setLang}/>
  {navigation.prompt&&<NavigationGuardDialog prompt={navigation.prompt} lang={lang} close={navigation.close} discard={navigation.discard}/>}
  </div>;
}

// Sign-in: a plain form on white next to a light preview of what the product gives.
function Login({t,lang,setLang,error,onLogin}:any){
 const[mode,setMode]=useState<'login'|'register'>(()=>location.pathname==='/register'?'register':'login');
 const[email,setEmail]=useState(''),[password,setPassword]=useState(''),[show,setShow]=useState(false),[busy,setBusy]=useState(false),[err,setErr]=useState<any>(error);
 const copy=(kk:string,ru:string)=>lang==='kk'?kk:ru;
 async function submit(e:FormEvent){e.preventDefault();setBusy(true);setErr(null);try{onLogin(await api.login(email,password))}catch(e){setErr(e)}finally{setBusy(false)}}
 const sample:[string,number][]=[[copy('Бешбармақ','Бешбармак'),42],[copy('Лағман','Лагман'),35],[copy('Палау','Плов'),28],[copy('Манты','Манты'),19]];
 return <div className="login-page">
  <div className="login-panel">
   <div className="login-top"><span className="login-logo"><Logo size={30}/></span><button className="language login-language" aria-label={copy('Тілді ауыстыру','Переключить язык')} onClick={()=>setLang(lang==='kk'?'ru':'kk')}>{lang==='kk'?'Русский':'Қазақша'}</button></div>
   <div className="login-body">
   {mode==='register'?<Register t={t} lang={lang} onRegistered={onLogin} onBack={()=>{setMode('login');if(location.pathname==='/register')history.replaceState(history.state,'','/')}}/>:<form onSubmit={submit} className="login-form">
    <h1>{t('login')}</h1><p>{copy('Мекемеңіздің кабинетін ашыңыз.','Откройте кабинет вашего заведения.')}</p>
    {err&&<div role={err.code==='PASSWORD_CHANGED'?'status':'alert'} className={`alert ${err.code==='PASSWORD_CHANGED'?'success':'danger'}`}>{err.code==='PASSWORD_CHANGED'?t('passwordChangedLogin'):err.code==='AUTH_REQUIRED'?copy('Сессия аяқталды. Қайта кіріңіз.','Сессия завершена. Войдите снова.'):err.status===401?t('loginError'):err.message}</div>}
    <label>{t('email')}<input type="email" autoComplete="username" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@example.com"/></label>
    <div className="login-password-field"><label htmlFor="login-password">{t('password')}</label><span className="password-wrap"><input id="login-password" type={show?'text':'password'} autoComplete="current-password" required value={password} onChange={e=>setPassword(e.target.value)}/><button type="button" className="icon-button" title={show?copy('Құпиясөзді жасыру','Скрыть пароль'):copy('Құпиясөзді көрсету','Показать пароль')} aria-pressed={show} onClick={()=>setShow(!show)}>{show?<EyeOff size={19}/>:<Eye size={19}/>}</button></span></div>
    <button className="button primary wide" disabled={busy}>{busy?<><span className="spinner"/>{copy('Кіру…','Входим…')}</>:t('login')}<ArrowRight size={17}/></button>
    <div className="login-divider" aria-hidden="true"><span>{copy('немесе','или')}</span></div>
    <p className="login-register">{copy('Мекемеңіз әлі тіркелмеген бе?','Ваше заведение ещё не зарегистрировано?')}</p>
    <button type="button" className="button secondary wide login-register-button" onClick={()=>setMode('register')}>{copy('Тіркелу','Регистрация')}<ArrowRight size={15}/></button>
    <p className="login-hint"><ShieldCheck size={16}/>{t('workspaceLoginHint')}</p>
   </form>}
   </div>
   <p className="login-foot">{copy('Есептеу — жүйеде. Соңғы шешім — сізде.','Расчёт — в системе. Последнее слово — за вами.')}</p>
  </div>
  <aside className="login-showcase" aria-hidden="true">
   <div className="showcase-copy"><div className="showcase-title">{copy('Ертеңгі сұранысты бүгін біліңіз','Знайте завтрашний спрос сегодня')}</div><p>{copy('Қанша порция дайындау керек және не сатып алу керек — сатылымыңыз, мерекелер мен ауа райы бойынша.','Сколько порций готовить и что закупить — по вашим продажам, праздникам и погоде.')}</p></div>
   <div className="showcase-card">
    <div className="showcase-card-head"><span><TrendingUp size={16}/>{copy('Ертеңге болжам','Прогноз на завтра')}</span><small>{copy('Мысал','Пример')}</small></div>
    <ul>{sample.map(([dish,portions])=><li key={dish}><span>{dish}</span><span className="showcase-bar"><i style={{width:portions*2+'%'}}/></span><strong>{portions}</strong></li>)}</ul>
    <div className="showcase-total"><span><ShoppingBasket size={16}/>{copy('Сатып алу','Закупка')}</span><strong>83 622 ₸</strong></div>
   </div>
   <ul className="showcase-points"><li><TrendingUp size={17}/>{copy('Әр тағамға порция болжамы','Прогноз порций по каждому блюду')}</li><li><ShoppingBasket size={17}/>{copy('Не сатып алу керек — бір батырмамен','Что закупить — одной кнопкой')}</li><li><CalendarDays size={17}/>{copy('Мерекелер, Ораза, ауа райы ескеріледі','Учтены праздники, Рамадан и погода')}</li><li><FlaskConical size={17}/>{copy('Демо-деректермен бірден көріңіз','Попробуйте сразу на демо-данных')}</li></ul>
  </aside>
 </div>
}
