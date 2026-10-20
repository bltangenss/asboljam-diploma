import {useState} from 'react';
import {Check,FileUp,MapPin,Sparkles} from 'lucide-react';
import {type Context,type Row,api,Button,items,useData} from './shared';

// An empty cabinet: try the product on demo data in one click, or bring your own files.
export function cabinetIsEmpty(c:Context){
 return Boolean(c.dataContext&&c.dataContext.operations_enabled&&!c.dataContext.history_start&&!(c.dataContext.inventory_dates||[]).length);
}

export default function GetStarted(c:Context){
 const kk=c.lang==='kk',copy=(kz:string,ru:string)=>kk?kz:ru;
 const[busy,setBusy]=useState(false),[error,setError]=useState<any>(null);
 const synthetic=c.dataContext?.data_origin==='SYNTHETIC',canDemo=synthetic&&c.user.role==='admin';
 const title=c.branchName||c.organization?.name||'';
 // Demo calendar and sunset are built for the branch city, so a branch without one picks it first.
 const profiles=useData(canDemo?'/branch-profiles':null,c.revision);
 const hasCity=items(profiles.data).some((row:Row)=>String(row.branch_id)===String(c.branch)&&row.city);
 async function loadDemo(){
  setBusy(true);setError(null);
  try{await api.request('/demo-data',{method:'POST',body:JSON.stringify({branch_id:c.branch})});await c.refreshWorkspace()}
  catch(problem){setError(problem)}finally{setBusy(false)}
 }
 const message=(problem:any)=>c.t('error_'+problem.code)!=='error_'+problem.code?c.t('error_'+problem.code):problem.message;
 return <section className="get-started" aria-labelledby="get-started-title" data-testid="get-started">
  <div className="get-started-head"><h1 id="get-started-title">{title?copy(`Қош келдіңіз, ${title}!`,`Добро пожаловать, ${title}!`):copy('Қош келдіңіз!','Добро пожаловать!')}</h1>
   <p>{copy('Predas ертең әр тағамнан қанша порция сатылатынын болжап, не сатып алу керегін есептейді. Бастау үшін сатылым мен мәзір керек.','Predas подсказывает, сколько порций каждого блюда продастся завтра и что для этого закупить. Для начала нужны продажи и меню.')}</p></div>
  <ol className="get-started-steps" aria-label={copy('Бұл қалай жұмыс істейді','Как это работает')}><li><b>1</b>{copy('Деректер','Данные')}</li><li><b>2</b>{copy('Болжам','Прогноз')}</li><li><b>3</b>{copy('Сатып алу','Закупка')}</li></ol>
  {error&&<div className="alert danger" role="alert">{message(error)}</div>}
  <div className="get-started-options">
   {canDemo&&<div className="get-started-option is-recommended">
    <span className="get-started-tag">{copy('Бір минутта','За минуту')}</span><Sparkles size={26} aria-hidden="true"/>
    <h2>{copy('Демо-деректермен көру','Попробовать на демо-данных')}</h2>
    <p>{copy('Сізге ұқсас мекеменің екі жылдық сатылымы, мәзірі, рецепттері мен қоймасы жүктеледі. Мерекелер мен күн бату — өз қалаңыз бойынша.','Загрузим два года продаж, меню, рецепты и склад похожего заведения. Праздники и закат — для вашего города.')}</p>
    <ul><li><Check size={15} aria-hidden="true"/>{copy('Бірден болжам мен сатып алуды көресіз','Сразу увидите прогноз и закупку')}</li><li><Check size={15} aria-hidden="true"/>{copy('Барлық дерек жасанды деп белгіленеді','Все данные помечены как синтетические')}</li></ul>
    {profiles.loading||hasCity?<Button disabled={busy||!c.online||profiles.loading} onClick={loadDemo}>{busy?<><span className="spinner"/>{copy('Жүктелуде…','Загружаем…')}</>:<><Sparkles size={16}/>{copy('Демо-деректерді жүктеу','Загрузить демо-данные')}</>}</Button>
     :<><p className="get-started-note">{copy('Демо мерекелер мен күн батуды қалаңыз бойынша есептейді, сондықтан алдымен профильде бөлімшенің қаласын таңдаңыз.','Демо учитывает праздники и закат вашего города, поэтому сначала выберите город филиала в профиле.')}</p><Button secondary onClick={()=>c.go('/profile')}><MapPin size={16}/>{copy('Қаланы таңдау','Выбрать город')}</Button></>}
   </div>}
   <div className="get-started-option">
    <FileUp size={26} aria-hidden="true"/>
    <h2>{copy('Өз деректеріңізді жүктеу','Загрузить свои данные')}</h2>
    <p>{copy('Мәзір, рецепттер, сатылым және қойма — дайын CSV үлгілері бойынша. Әр файл сақталмас бұрын тексеріледі.','Меню, рецепты, продажи и склад — по готовым шаблонам CSV. Каждый файл проверяется до сохранения.')}</p>
    <ul><li><Check size={15} aria-hidden="true"/>{copy('Болжам үшін кемінде 84 күндік сатылым керек','Для прогноза нужно не меньше 84 дней продаж')}</li><li><Check size={15} aria-hidden="true"/>{synthetic?copy('Сынақ режимінде файлдар жасанды деп белгіленеді; нақты деректерді оператор қосады','В тестовом режиме файлы помечаются как синтетические; реальные данные подключает оператор'):copy('Қатесі бар файл деректерді өзгертпейді','Файл с ошибками ничего не изменит в данных')}</li></ul>
    <Button secondary onClick={()=>c.go('/imports')}><FileUp size={16}/>{copy('Деректерді жүктеу','Загрузить данные')}</Button>
   </div>
  </div>
 </section>;
}
