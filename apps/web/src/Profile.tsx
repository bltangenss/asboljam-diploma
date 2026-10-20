import {ArrowRight,BookOpen,ChefHat,History,MapPin,Package,ShieldCheck,Sparkles,Truck} from 'lucide-react';
import {type Context,type Row,DataState,date,fmt,items,useData} from './shared';
import AccountSecurity from './AccountSecurity';
import BranchProfiles from './BranchProfiles';
import UserAdmin from './UserAdmin';
import {FactorCatalogue} from './ForecastFactors';

// Everything about the establishment in one place: who it is, where it is, what data it
// holds, who works in it and, folded away, the automatic day factors behind the forecast.
export default function Profile(c:Context&{cities:Record<string,Row>}){
 const {t,lang,user,branch,branchName,go,revision}=c;
 const kk=lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru,key=kk?'kk':'ru';
 const settings=useData('/settings',revision);
 const org=settings.data?.organization??c.organization;
 const operations=c.dataContext?.operations_enabled===true;
 const profiles=useData(operations?'/branch-profiles':null,revision),catalogue=useData('/cities',0);
 const profile=items(profiles.data).find((row:Row)=>String(row.branch_id)===String(branch));
 const types=(catalogue.data as any)?.establishment_types||{};
 const city=c.cities[branch]||profile?.city;
 const typeLabel=profile?.establishment_type?types[profile.establishment_type]?.[key]||profile.establishment_type:'';
 const reads=operations&&user.role!=='warehouse';
 const meals=useData(reads?'/meals?limit=1':null,revision),suppliers=useData(reads?'/suppliers?limit=1':null,revision),recipes=useData(reads?'/recipes?limit=1':null,revision);
 const policy=org?.data_policy?t(org.data_policy==='synthetic_only'?'syntheticOnly':org.data_policy==='real_only'?'realOnly':'dataSetupPending'):'—';
 const title=branchName||org?.name||'—';
 const about:[string,string][]=[[copy('Ұйым','Организация'),org?.name??'—'],[copy('Мекеме түрі','Тип заведения'),typeLabel||'—'],[copy('Қала','Город'),city?city.name[key]+' · '+city.region[key]:'—'],[copy('Уақыт белдеуі','Часовой пояс'),org?.timezone??settings.data?.timezone??'—'],[copy('Валюта','Валюта'),org?.currency??settings.data?.currency??'—'],[t('dataPolicy'),policy],[t('organizationStatus'),org?.status?t('organization_'+org.status):'—']];
 const access:[string,string][]=[[t('email'),user.email],[copy('Рөл','Роль'),t('role_'+user.role)],[t('branch'),user.branch_ids.join(', ')||'—']];
 const tiles=[
  {label:copy('Мәзірдегі тағамдар','Блюда в меню'),value:fmt(meals.data?.total),icon:ChefHat,url:'/recipes',show:reads},
  {label:copy('Рецепттердегі позициялар','Позиции в рецептах'),value:fmt(recipes.data?.total),icon:BookOpen,url:'/recipes',show:reads},
  {label:copy('Жеткізушілер','Поставщики'),value:fmt(suppliers.data?.total),icon:Truck,url:'/suppliers',show:reads},
  {label:copy('Сатылым тарихы','История продаж'),value:c.dataContext?.history_start?date(c.dataContext.history_start)+' — '+date(c.dataContext.history_end):copy('Әлі жоқ','Пока нет'),icon:History,url:'/sales',show:reads&&Boolean(branch)},
  {label:copy('Қойма қалдығының күні','Остатки на дату'),value:c.dataContext?.inventory_date?date(c.dataContext.inventory_date):copy('Әлі жоқ','Пока нет'),icon:Package,url:'/inventory',show:operations&&Boolean(branch)},
 ].filter(tile=>tile.show);
 return <div className="profile-page">
  <header className="profile-hero">
   <span className="profile-avatar" aria-hidden="true">{title.trim()[0]?.toUpperCase()||'P'}</span>
   <div><h1>{title}</h1><p>{typeLabel&&<span>{typeLabel}</span>}{city&&<span><MapPin size={14} aria-hidden="true"/>{city.name[key]} · {city.region[key]}</span>}{org?.name&&org.name!==title&&<span>{org.name}</span>}</p></div>
  </header>
  {tiles.length>0&&<section className="profile-tiles" aria-label={copy('Мекеме деректері','Данные заведения')}>{tiles.map(({label,value,icon:Icon,url})=><button key={label} className="profile-tile" onClick={()=>go(url)}><Icon size={18} aria-hidden="true"/><span>{label}</span><strong>{value}</strong><ArrowRight size={15} aria-hidden="true"/></button>)}</section>}
  <DataState state={settings} t={t} retry={c.refresh}>
   <div className="profile-grid">
    <section className="panel settings-panel profile-card"><h2>{copy('Мекеме туралы','О заведении')}</h2>{about.map(([k,v])=><div className="settings-row" key={k}><h3>{k}</h3><span>{v}</span></div>)}<p className="reference-footnote">{user.role==='admin'?copy('Қала мен түрін төменде, «Бөлімшелердің қаласы» бөлімінде өзгертуге болады.','Город и тип можно изменить ниже, в разделе «Города филиалов».'):copy('Өзгерту үшін ұйым әкімшісіне хабарласыңыз.','Чтобы что-то изменить, обратитесь к администратору организации.')}</p></section>
    <section className="panel settings-panel profile-card"><h2>{copy('Сіздің рұқсатыңыз','Ваш доступ')}</h2>{access.map(([k,v])=><div className="settings-row" key={k}><h3>{k}</h3><span>{v}</span></div>)}<p className="reference-footnote">{copy('Сіз тек өз ұйымыңыз бен бөлімшелеріңіздің деректерін көресіз.','Вы видите данные только своей организации и своих филиалов.')}</p></section>
   </div>
  </DataState>
  {user.role==='admin'&&operations&&<section className="panel reference-profiles"><BranchProfiles {...c}/></section>}
  <section className="panel reference-security"><AccountSecurity {...c}/></section>
  {user.role==='admin'&&<section className="panel reference-access"><UserAdmin {...c}/></section>}
  {operations&&branch&&user.role!=='warehouse'&&<details className="profile-factors">
   <summary><Sparkles size={18} aria-hidden="true"/><span><strong>{copy('Болжам нені ескереді','Что учитывает прогноз')}</strong><small>{copy('Мерекелер, Ораза, мектеп демалысы, күн бату мен ауа райы автоматты түрде ескеріледі. Барлық факторды көру үшін басыңыз.','Праздники, Рамадан, школьные каникулы, закат и погода учитываются автоматически. Нажмите, чтобы увидеть все факторы.')}</small></span></summary>
   <FactorCatalogue {...c}/>
  </details>}
  <p className="profile-audit"><ShieldCheck size={16} aria-hidden="true"/>{copy('Барлық шешімдер мен өзгерістер журналда сақталады.','Все решения и изменения сохраняются в журнале.')} <button className="text-button" onClick={()=>go('/audit')}>{copy('Әрекеттер журналы','Журнал действий')}<ArrowRight size={14}/></button></p>
 </div>;
}
