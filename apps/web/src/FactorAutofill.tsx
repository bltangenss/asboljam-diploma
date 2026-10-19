import {useEffect,useState} from 'react';
import {CloudSun,MapPin,Wand2} from 'lucide-react';
import {type Context,type Row,api,date,fmt,items,useData} from './shared';

// Calendar factors for the branch's city, plus weather forecasts from the internet, become a
// reviewable import: nothing is stored until the user confirms it on the import page.
// The catalogue reads the branch city once and passes it to both blocks.
export function useBranchCity(c:Context){
 const profiles=useData(c.branch?'/branch-profiles':null,c.revision);
 return items(profiles.data).find((row:Row)=>String(row.branch_id)===String(c.branch))?.city as Row|undefined;
}

// The same day two calendar years earlier; 29 February becomes 28 February.
function twoYearsBefore(day:string){const year=String(Number(day.slice(0,4))-2),rest=day.slice(4);return year+(rest==='-02-29'?'-02-28':rest)}

export function FactorAutofill({city,...c}:Context&{city?:Row}){
 const kk=c.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru,key=kk?'kk':'ru';
 // Default: the sales history through the forecast day; a new cabinet without sales gets two years.
 const target=c.dataContext?.target_date||'',start=c.dataContext?.history_start||(target?[twoYearsBefore(target),'2024-01-01'].sort()[1]:'');
 const[from,setFrom]=useState(start),[to,setTo]=useState(target);
 useEffect(()=>{setFrom(value=>value||start);setTo(value=>value||target)},[start,target]);
 const[weather,setWeather]=useState(true),[busy,setBusy]=useState(false),[result,setResult]=useState<any>(null),[error,setError]=useState<any>(null);
 const canWrite=c.dataContext?.operations_enabled===true&&['admin','manager'].includes(c.user.role);
 async function fill(){
  setBusy(true);setError(null);setResult(null);
  try{
   const response:any=await api.request('/factors/fill',{method:'POST',body:JSON.stringify({branch_id:c.branch,date_from:from,date_to:to,weather})});
   if(response.batch?.id)c.go('/imports?batch='+encodeURIComponent(response.batch.id));else setResult(response.summary);
  }catch(problem){setError(problem)}finally{setBusy(false)}
 }
 if(!canWrite)return null;
 return <div className="factor-autofill">
  <div className="factor-autofill-head"><Wand2 size={18}/><div><strong>{copy('Қала бойынша автоматты толтыру','Автозаполнение по городу')}</strong>
   <span>{city?<><MapPin size={13}/>{city.name[key]} · {city.region[key]}</>:copy('Бөлімшенің қаласы таңдалмаған','Город филиала не выбран')}</span></div></div>
  {!city?<p className="reference-footnote">{copy('«Баптаулар» бетінде бөлімшенің қаласын таңдаңыз — содан кейін мерекелер, Ораза, айттар, мектеп демалысы, күн бату және ауа райы автоматты есептеледі.','Выберите город филиала на странице «Настройки» — после этого праздники, Рамадан, айты, каникулы, закат и погода считаются автоматически.')} <button className="text-button" onClick={()=>c.go('/settings')}>{copy('Баптауларға өту','Открыть настройки')}</button></p>:<>
   <p className="reference-footnote">{copy('Мерекелер, ауыстырулар, Ораза мен айттар, мектеп демалысы ресми күнтізбеден, күн бату мен ауызашар — қаланың координатасынан есептеледі. Ауа райы — Open-Meteo болжамы: өткен күндерге мұрағаттағы болжам, алдағы 16 күнге жаңа болжам. Бар жолдар өзгертілмейді; алдымен импорт алдын ала қарауы ашылады.','Праздники, переносы, Рамадан и айты, каникулы берутся из официального календаря, закат и ауызашар считаются по координатам города. Погода — прогноз Open-Meteo: для прошлых дней архивный прогноз, на 16 дней вперёд — свежий. Существующие строки не меняются; сначала откроется предпросмотр импорта.')}</p>
   <div className="factor-autofill-form">
    <label>{c.t('from')}<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label>
    <label>{c.t('to')}<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label>
    <label className="factor-autofill-weather"><input type="checkbox" checked={weather} onChange={e=>setWeather(e.target.checked)}/>{copy('Ауа райын интернеттен алу','Погода из интернета')}</label>
    <button className="button primary" disabled={busy||!from||!to} onClick={fill}>{busy?<><span className="spinner"/>{copy('Есептелуде…','Считаем…')}</>:copy('Факторларды толтыру','Заполнить факторы')}</button>
   </div>
   {error&&<div role="alert" className="alert danger">{c.t('error_'+error.code)!=='error_'+error.code?c.t('error_'+error.code):error.message}</div>}
   {result&&<p role="status" className="alert info">{copy(`Жаңа жол жоқ: есептелген ${fmt(result.calculated_rows)} мәннің бәрі бұрыннан бар.`,`Новых строк нет: все ${fmt(result.calculated_rows)} рассчитанных значений уже есть.`)}{result.weather!=='loaded'&&result.weather!=='not_requested'&&<> {c.t('error_'+result.weather)}</>}</p>}
  </>}
 </div>;
}

export function CityWeather({city,...c}:Context&{city?:Row}){
 const kk=c.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru,key=kk?'kk':'ru';
 const state=useData(city&&c.branch?'/weather?branch_id='+encodeURIComponent(c.branch):null,c.revision);
 if(!city)return null;
 const days=items(state.data);
 return <section className="city-weather" aria-labelledby="city-weather-title">
  <h3 id="city-weather-title"><CloudSun size={17}/>{copy('Ауа райы болжамы','Прогноз погоды')} · {city.name[key]} · {copy('7 күн','7 дней')}</h3>
  {state.loading?<p className="reference-footnote">{c.t('loading')}</p>:state.error?<p className="reference-footnote">{c.t('error_'+state.error.code)!=='error_'+state.error.code?c.t('error_'+state.error.code):state.error.message}</p>:
   <ol>{days.map((day:Row)=><li key={day.date}><span>{date(day.date).slice(0,5)}</span><strong>{fmt(day.temperature_mean,0)}°</strong><small>{copy('ең жоғ.','макс.')} {fmt(day.temperature_max,0)}°</small><small>{fmt(day.precipitation,1)} {copy('мм','мм')}</small></li>)}</ol>}
  <p className="reference-footnote">{copy('Дереккөз: Open-Meteo, модельдік болжам — өлшем емес. Коммерциялық пайдалануға лицензия кілті қажет.','Источник: Open-Meteo, модельный прогноз, а не измерение. Для коммерческого использования нужен лицензионный ключ.')}</p>
 </section>;
}
