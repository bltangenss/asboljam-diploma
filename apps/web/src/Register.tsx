import {type FormEvent,useEffect,useMemo,useState} from 'react';
import {ArrowLeft,ArrowRight,Eye,EyeOff,FlaskConical,MapPin} from 'lucide-react';
import {api,type Lang} from './shared';

type City={code:string;name:{kk:string;ru:string};region:{kk:string;ru:string}};

// Self-registration opens a cabinet in test mode for one establishment in a chosen city.
// Real (REAL) data still needs an operator-registered source, as before.
export default function Register({t,lang,onRegistered,onBack}:{t:(key:string)=>string;lang:Lang;onRegistered:(user:any)=>void;onBack:()=>void}){
 const kk=lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru,key=kk?'kk':'ru';
 const[cities,setCities]=useState<City[]>([]),[types,setTypes]=useState<Record<string,{kk:string;ru:string}>>({}),[enabled,setEnabled]=useState<boolean|null>(null);
 const[name,setName]=useState(''),[kind,setKind]=useState('cafe'),[city,setCity]=useState(''),[email,setEmail]=useState('');
 const[password,setPassword]=useState(''),[repeat,setRepeat]=useState(''),[show,setShow]=useState(false),[accept,setAccept]=useState(false);
 const[busy,setBusy]=useState(false),[error,setError]=useState<any>(null);
 useEffect(()=>{let active=true;
  Promise.all([api.request('/registration'),api.request('/cities')]).then(([status,catalogue]:any[])=>{if(!active)return;setEnabled(Boolean(status?.enabled));setCities(catalogue?.items||[]);setTypes(catalogue?.establishment_types||{})}).catch(problem=>{if(active){setEnabled(false);setError(problem)}});
  return()=>{active=false}},[]);
 const sorted=useMemo(()=>[...cities].sort((a,b)=>a.name[key].localeCompare(b.name[key],key)),[cities,key]);
 const mismatch=repeat.length>0&&repeat!==password;
 const message=(problem:any)=>problem?(t('error_'+problem.code)!=='error_'+problem.code?t('error_'+problem.code):problem.message):'';
 async function submit(event:FormEvent){
  event.preventDefault();if(mismatch||!accept)return;
  setBusy(true);setError(null);
  try{onRegistered(await api.register({establishment_name:name.trim(),establishment_type:kind,city_code:city,email:email.trim(),password,accept_test_mode:true}))}
  catch(problem){setError(problem)}finally{setBusy(false)}
 }
 return <form onSubmit={submit} className="login-form register-form" aria-labelledby="register-title">
  <button type="button" className="text-button register-back" onClick={onBack}><ArrowLeft size={15}/>{copy('Кіруге оралу','Вернуться ко входу')}</button>
  <span className="eyebrow">{copy('ЖАҢА КАБИНЕТ','НОВЫЙ КАБИНЕТ')}</span><h2 id="register-title">{copy('Тіркелу','Регистрация')}</h2>
  <p>{copy('Мекемеңіздің қаласын таңдаңыз — мерекелер, Ораза, күн бату мен ауа райы сол қала бойынша ескеріледі.','Выберите город заведения — праздники, Рамадан, закат и погоду учтём именно для него.')}</p>
  {enabled===false&&<div role="alert" className="alert danger">{error?message(error):copy('Қазір тіркелу жабық. Кабинет ашу үшін оператормен байланысыңыз.','Регистрация сейчас закрыта. Чтобы открыть кабинет, свяжитесь с оператором.')}</div>}
  {error&&enabled!==false&&<div role="alert" className="alert danger">{message(error)}</div>}
  <label>{copy('Мекеме атауы','Название заведения')}<input required minLength={2} maxLength={120} value={name} onChange={e=>setName(e.target.value)} placeholder={copy('Мысалы: Достар асханасы','Например: Столовая «Достар»')}/></label>
  <div className="register-row">
   <label>{copy('Мекеме түрі','Тип заведения')}<select value={kind} onChange={e=>setKind(e.target.value)}>{Object.entries(types).map(([code,label])=><option key={code} value={code}>{label[key]}</option>)}</select></label>
   <label>{copy('Қала','Город')}<select required value={city} onChange={e=>setCity(e.target.value)}><option value="">{copy('Қаланы таңдаңыз','Выберите город')}</option>{sorted.map(item=><option key={item.code} value={item.code}>{item.name[key]} · {item.region[key]}</option>)}</select></label>
  </div>
  <label>{t('email')}<input type="email" autoComplete="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="name@example.com"/></label>
  <div className="register-row">
   <div className="login-password-field"><label htmlFor="register-password">{t('password')}</label><span className="password-wrap"><input id="register-password" type={show?'text':'password'} autoComplete="new-password" required minLength={12} maxLength={1024} value={password} onChange={e=>setPassword(e.target.value)}/><button type="button" className="icon-button" title={show?copy('Құпиясөзді жасыру','Скрыть пароль'):copy('Құпиясөзді көрсету','Показать пароль')} aria-label={show?copy('Құпиясөзді жасыру','Скрыть пароль'):copy('Құпиясөзді көрсету','Показать пароль')} onClick={()=>setShow(value=>!value)}>{show?<EyeOff size={17}/>:<Eye size={17}/>}</button></span></div>
   <label>{copy('Құпиясөзді қайталаңыз','Повторите пароль')}<input type={show?'text':'password'} autoComplete="new-password" required value={repeat} onChange={e=>setRepeat(e.target.value)} aria-invalid={mismatch}/></label>
  </div>
  <small className="register-note">{copy('Кемінде 12 таңба. Поштаны немесе мекеме атауын қолданбаңыз.','Не меньше 12 символов. Не используйте почту или название заведения.')}{mismatch&&<strong> {copy('Құпиясөздер сәйкес емес.','Пароли не совпадают.')}</strong>}</small>
  <label className="register-consent"><input type="checkbox" checked={accept} onChange={e=>setAccept(e.target.checked)}/><span><FlaskConical size={15}/>{copy('Түсінемін: кабинет сынақ режимінде ашылады, барлық дерек жасанды деп белгіленеді. Нақты деректерге тек оператордың растауымен өтуге болады.','Понимаю: кабинет откроется в тестовом режиме, все данные будут помечены как синтетические. Перейти на реальные данные можно только с подтверждением оператора.')}</span></label>
  <button className="button primary wide" disabled={busy||!accept||mismatch||!city||enabled===false}>{busy?<><span className="spinner"/>{copy('Ашылуда…','Открываем…')}</>:<><MapPin size={16}/>{copy('Кабинетті ашу','Открыть кабинет')}</>}<ArrowRight size={17}/></button>
 </form>;
}
