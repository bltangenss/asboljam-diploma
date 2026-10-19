import {useEffect,useState} from 'react';
import {MapPin,Save} from 'lucide-react';
import {type Context,type Row,api,items,useData} from './shared';

// Administrators choose each branch's city (solar times, weather) and establishment type.
export default function BranchProfiles(c:Context){
 const kk=c.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru,key=kk?'kk':'ru';
 const branches=useData('/branches?limit=200',c.revision),profiles=useData('/branch-profiles',c.revision),catalogue=useData('/cities',0);
 const[draft,setDraft]=useState<Record<string,{city_code:string;establishment_type:string}>>({});
 const[saved,setSaved]=useState(''),[error,setError]=useState<any>(null),[busy,setBusy]=useState('');
 useEffect(()=>{const next:Record<string,{city_code:string;establishment_type:string}>={};
  items(profiles.data).forEach((row:Row)=>{next[row.branch_id]={city_code:row.city_code,establishment_type:row.establishment_type||''}});setDraft(next)},[profiles.data]);
 const cities=[...items(catalogue.data)].sort((a:Row,b:Row)=>a.name[key].localeCompare(b.name[key],key));
 const types=Object.entries((catalogue.data as any)?.establishment_types||{}) as [string,{kk:string;ru:string}][];
 async function save(branch:string){
  const value=draft[branch];if(!value?.city_code)return;
  setBusy(branch);setError(null);setSaved('');
  try{await api.request(`/branches/${encodeURIComponent(branch)}/profile`,{method:'PUT',body:JSON.stringify({city_code:value.city_code,establishment_type:value.establishment_type||null})});setSaved(branch);c.refresh()}
  catch(problem){setError(problem)}finally{setBusy('')}
 }
 return <section className="branch-profiles" aria-labelledby="branch-profiles-title">
  <h2 id="branch-profiles-title"><MapPin size={18}/>{copy('Бөлімшелердің қаласы','Города филиалов')}</h2>
  <p className="reference-footnote">{copy('Қала күн бату мен ауызашар уақытын, ауа райы болжамын және сағат белдеуін анықтайды. Мерекелер мен мектеп демалысы бүкіл ел бойынша бірдей.','Город задаёт время заката и ауызашара, прогноз погоды и часовой пояс. Праздники и каникулы общие для всей страны.')}</p>
  {error&&<div role="alert" className="alert danger">{c.t('error_'+error.code)!=='error_'+error.code?c.t('error_'+error.code):error.message}</div>}
  <ul>{items(branches.data).map((branch:Row)=>{const id=String(branch.branch_id),value=draft[id]||{city_code:'',establishment_type:''};return <li key={id}>
   <strong>{branch.branch_name}</strong>
   <label>{copy('Қала','Город')}<select aria-label={copy('Қала','Город')+': '+branch.branch_name} value={value.city_code} onChange={e=>setDraft({...draft,[id]:{...value,city_code:e.target.value}})}><option value="">{copy('Таңдалмаған','Не выбран')}</option>{cities.map((city:Row)=><option key={city.code} value={city.code}>{city.name[key]} · {city.region[key]}</option>)}</select></label>
   <label>{copy('Түрі','Тип')}<select aria-label={copy('Түрі','Тип')+': '+branch.branch_name} value={value.establishment_type} onChange={e=>setDraft({...draft,[id]:{...value,establishment_type:e.target.value}})}><option value="">—</option>{types.map(([code,label])=><option key={code} value={code}>{label[key]}</option>)}</select></label>
   <button className="button secondary" disabled={!value.city_code||busy===id} onClick={()=>save(id)}><Save size={15}/>{saved===id?copy('Сақталды','Сохранено'):copy('Сақтау','Сохранить')}</button>
  </li>})}</ul>
 </section>;
}
