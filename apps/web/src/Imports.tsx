import {useEffect,useRef,useState} from 'react';
import {ArrowDownToLine,ArrowRight,Check,CheckCircle2,CircleAlert,Database,FileUp,Files,ShieldCheck} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type ImportBatchView,type ImportReceipt,type Row,useData,items,fmt,date,Heading,Button,Badge,DataState,Table,Pagination} from './shared';
import './import-ui.css';

const correctionKinds=['daily_sales','inventory_lots','calendar'];
const sourceCode=/^[A-Za-z0-9_.:-]{1,64}$/;
const timestamp=(value?:string|null)=>value?value.slice(0,19).replace('T',' '):'—';
const schemaCopy:Record<string,{name:[string,string];purpose:[string,string];columns:string}>={
 branches:{name:['Бөлімшелер','Филиалы'],purpose:['Деректер қай бөлімшеге тиесілі екенін анықтайды. Алдымен осы анықтамалықты жүктеңіз.','Определяют, к какой точке относятся данные. Этот справочник загружается первым.'],columns:'branch_id branch_name data_origin'},
 meals:{name:['Тағамдар','Блюда'],purpose:['Мәзірдегі тағамдарды сатылым мен рецепттерге байланыстырады.','Связывают блюда из меню с продажами и рецептами.'],columns:'meal_id meal_name base_price_kzt data_origin'},
 ingredients:{name:['Ингредиенттер','Ингредиенты'],purpose:['Шикізат атауын, өлшем бірлігін және шығым коэффициентін сақтайды.','Описывают сырьё, единицы измерения и коэффициент выхода.'],columns:'ingredient_id ingredient_name unit reference_cost_kzt shelf_life_days yield_factor storage_capacity data_origin'},
 recipes:{name:['Рецепттер','Рецепты'],purpose:['Бір порцияға қажетті ингредиенттер арқылы болжамды шикізат қажеттілігіне айналдырады. Алдымен тағамдар мен ингредиенттерді жүктеңіз.','Переводят порции в потребность в сырье. Сначала загрузите блюда и ингредиенты.'],columns:'meal_id ingredient_id net_qty_per_portion recipe_version data_origin'},
 suppliers:{name:['Жеткізушілер','Поставщики'],purpose:['Сатып алуда қолданылатын жеткізушілерді анықтайды.','Справочник поставщиков для расчёта закупки.'],columns:'supplier_id supplier_name lead_time_days data_origin'},
 supplier_offers:{name:['Жеткізуші ұсыныстары','Предложения поставщиков'],purpose:['Қаптама көлемін, бағасын және тапсырыс шектерін береді. Алдымен жеткізушілер мен ингредиенттерді жүктеңіз.','Задают упаковки, цены и ограничения заказа. Сначала загрузите поставщиков и ингредиенты.'],columns:'supplier_id ingredient_id pack_qty unit_cost_kzt min_packs max_packs lead_time_days data_origin'},
 calendar:{name:['Жұмыс күнтізбесі','Календарь работы'],purpose:['Бөлімшенің жұмыс күндері туралы жазбалар. Ағымдағы болжам ауа райы мен оқиғаларды белгі ретінде қолданбайды.','Записи о днях работы филиала. Текущая модель не использует погоду и события как признаки.'],columns:'date branch_id weekday temperature_forecast_c synthetic_event is_open data_origin'},
 daily_sales:{name:['Күнделікті сатылым','Продажи по дням'],purpose:['Қанша порция сатылғанын көрсетеді. Болжам үшін әр тағамға кемінде 84 күндік үздіксіз тарих қажет. Алдымен бөлімшелер мен тағамдарды жүктеңіз.','Показывают, сколько порций продано. Для прогноза нужно минимум 84 дня непрерывной истории по блюду. Сначала загрузите филиалы и блюда.'],columns:'date branch_id meal_id units_sold available_portions stockout_flag is_open promo price_kzt data_origin'},
 inventory_lots:{name:['Қойма қалдықтары','Остатки на складе'],purpose:['Нақты күнге саналған партия қалдықтары. Жоқ жол нөлдік қалдықты білдірмейді. Алдымен бөлімшелер мен ингредиенттерді жүктеңіз.','Пересчитанные остатки партий на конкретную дату. Отсутствие строки не означает ноль. Сначала загрузите филиалы и ингредиенты.'],columns:'branch_id ingredient_id lot_id snapshot_date expiry_date on_hand_qty unit data_origin'},
};
const schemaPurpose:Record<string,[string,string]>={
 branches:['Деректерді нақты бөлімшеге байланыстырады.','Связывают данные с конкретной точкой.'],
 meals:['Мәзірдегі тағамдарды сатылым мен рецепттерге байланыстырады.','Связывают блюда из меню с продажами и рецептами.'],
 ingredients:['Шикізат пен оның өлшем бірліктерін анықтайды.','Определяют сырьё и его единицы измерения.'],
 recipes:['Порцияларды шикізат қажеттілігіне айналдырады.','Переводят порции в потребность в сырье.'],
 suppliers:['Сатып алу үшін жеткізушілерді анықтайды.','Определяют поставщиков для закупки.'],
 supplier_offers:['Қаптамаларды, бағаларды және тапсырыс шектерін береді.','Задают упаковки, цены и ограничения заказа.'],
 calendar:['Бөлімшенің жұмыс күндері туралы жазбалар.','Записи о днях работы филиала.'],
 daily_sales:['Күн сайын қанша порция сатылғанын көрсетеді.','Показывают, сколько порций продано за каждый день.'],
 inventory_lots:['Нақты күнге саналған партия қалдықтары.','Пересчитанные остатки партий на конкретную дату.'],
};
const fieldCopy:Record<string,[string,string]>={
 branch_id:['Бөлімше коды','Код филиала'],branch_name:['Бөлімше атауы','Название филиала'],meal_id:['Тағам коды','Код блюда'],meal_name:['Тағам атауы','Название блюда'],ingredient_id:['Ингредиент коды','Код ингредиента'],ingredient_name:['Ингредиент атауы','Название ингредиента'],supplier_id:['Жеткізуші коды','Код поставщика'],supplier_name:['Жеткізуші атауы','Название поставщика'],data_origin:['Деректер режимі','Происхождение данных'],date:['Күн','Дата'],snapshot_date:['Қор кесіндісінің күні','Дата среза остатков'],expiry_date:['Жарамдылық мерзімі','Срок годности'],units_sold:['Сатылған порция','Продано порций'],available_portions:['Қолжетімді порция','Доступно порций'],stockout_flag:['Сатылымда қалмады','Признак нехватки'],is_open:['Жұмыс күні','Открыто'],promo:['Акция белгісі','Признак акции'],price_kzt:['Баға, ₸','Цена, ₸'],base_price_kzt:['Негізгі баға, ₸','Базовая цена, ₸'],reference_cost_kzt:['Анықтамалық баға, ₸','Справочная цена, ₸'],unit_cost_kzt:['Бірлік бағасы, ₸','Цена единицы, ₸'],unit:['Өлшем бірлігі','Единица'],on_hand_qty:['Саналған қалдық','Пересчитанный остаток'],lot_id:['Партия коды','Код партии'],net_qty_per_portion:['Нетто бір порцияға','Нетто на порцию'],yield_factor:['Шығым коэффициенті','Коэффициент выхода'],recipe_version:['Рецепт нұсқасы','Версия рецепта'],shelf_life_days:['Сақтау мерзімі, күн','Срок хранения, дней'],storage_capacity:['Сақтау сыйымдылығы','Вместимость хранения'],pack_qty:['Қаптама көлемі','Размер упаковки'],min_packs:['Ең аз қаптама саны','Минимум упаковок'],max_packs:['Ең көп қаптама саны','Максимум упаковок'],lead_time_days:['Жеткізу, күн','Доставка, дней'],weekday:['Апта күні','День недели'],temperature_forecast_c:['Температура, °C','Температура, °C'],synthetic_event:['Жасанды оқиға белгісі','Признак синтетического события'],header:['Файл бағандары','Колонки файла'],file:['Файл','Файл'],row:['Жол','Строка'],key:['Жазба кілті','Ключ записи']
};

export default function Imports(c:Context) {
 const {t,lang,branch,user,online}=c;
 const kk=lang==='kk',copy=(kkText:string,ruText:string)=>kk?kkText:ruText;
 const returnQuery=new URLSearchParams(location.search),returnSection=returnQuery.get('return');
 const returnAllowed=returnQuery.get('return_branch')===branch&&['inventory','forecasts'].includes(returnSection||'');
 const returnForecast=returnQuery.get('forecast')||'';
 const returnProduction=returnQuery.get('production_plan_id')||'';
 const validReturnForecast=/^[A-Za-z0-9_-]{1,128}$/.test(returnForecast);
 const returnPlanQuery=validReturnForecast&&/^[A-Za-z0-9_-]{1,128}$/.test(returnProduction)?'&production_plan_id='+encodeURIComponent(returnProduction):'';
 const returnPath=returnAllowed?'/'+returnSection+(returnSection==='inventory'&&validReturnForecast?'?forecast='+encodeURIComponent(returnForecast)+returnPlanQuery:''):null;
 const kindName=(value:string)=>schemaCopy[value]?.name[kk?0:1]||value;
 const fieldName=(value:string)=>fieldCopy[value]?.[kk?0:1]||value;
 const real=c.dataContext?.mode==='real_business',configuredSource=c.dataContext?.source;
 const canImport=c.dataContext?.operations_enabled===true&&['admin','manager','warehouse'].includes(user?.role||'');
 const types=user?.role==='admin'?['daily_sales','inventory_lots','branches','meals','ingredients','recipes','suppliers','supplier_offers','calendar']
  :user?.role==='warehouse'?['inventory_lots']:['manager','analyst'].includes(user?.role||'')?correctionKinds:[];
 const [kind,setKind]=useState(()=>{const requested=new URLSearchParams(location.search).get('kind');return requested&&types.includes(requested)?requested:user?.role==='admin'&&!branch?'branches':user?.role==='warehouse'?'inventory_lots':'daily_sales'});
 const [mode,setMode]=useState<'append'|'correction'>(()=>new URLSearchParams(location.search).get('mode')==='correction'&&correctionKinds.includes(kind)?'correction':'append'),[reason,setReason]=useState(''),[correctsBatch,setCorrectsBatch]=useState('');
 const [sourceId,setSourceId]=useState('manual_csv'),[mappingVersion,setMappingVersion]=useState('canonical-v1'),[declaredHash,setDeclaredHash]=useState('');
 const [filename,setFilename]=useState(''),[fileSize,setFileSize]=useState<number|null>(null),[dragging,setDragging]=useState(false),[text,setText]=useState(''),[preview,setPreview]=useState<ImportBatchView|null>(null);
 const [error,setError]=useState(''),[action,setAction]=useState(''),[done,setDone]=useState(false),[reviewed,setReviewed]=useState(false),[uncertain,setUncertain]=useState(false);
 const [cursor,setCursor]=useState(''),[historyRevision,setHistoryRevision]=useState(0);
 const [errorPage,setErrorPage]=useState(0);
 const history=useData(`/imports?limit=20&cursor=${cursor||'0'}`,historyRevision+c.revision);
 const version=useRef(0),pending=useRef(false),mounted=useRef(true);
 const commitKeys=useRef(new Map<string,string>());
 const busy=Boolean(action),locked=action==='commit'||action==='recover';
 const requestedBatch=new URLSearchParams(location.search).get('batch')||'';
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++version.current}},[]);
 useEffect(()=>{if(!done)resetPreview()},[branch]);
 useEffect(()=>{resetPreview()},[user?.role]);
 useEffect(()=>{if(real&&configuredSource){resetPreview();setSourceId(configuredSource.source_id);setMappingVersion(configuredSource.mapping_version)}},[real,configuredSource?.source_id,configuredSource?.mapping_version]);
 useEffect(()=>{if(requestedBatch)void openBatch(requestedBatch)},[requestedBatch,user?.id,user?.organization_id]);

 function resetPreview() {
  const next=++version.current;pending.current=false;
  setPreview(null);setDone(false);setReviewed(false);setUncertain(false);setError('');setAction('');setErrorPage(0);return next;
 }
 function begin(next=version.current) {
  const session=api.csrf;pending.current=true;
  return ()=>mounted.current&&next===version.current&&session===api.csrf;
 }
 function finish(current:()=>boolean) {if(current()){pending.current=false;setAction('')}}
 function explain(error:unknown) {
  const code=error instanceof ApiError?error.code:'';
  if(['STALE_IMPORT','DUPLICATE_CONFLICT','IMPORT_PREVIEW_REQUIRED','IMPORT_STALE','STALE_PREVIEW','IMPORT_CONFLICT','DUPLICATE_KEY'].includes(code))return t('importStale');
  if(code==='IMPORT_INVALID')return t('noImport');
  if(error instanceof ApiError&&error.status===403)return t('forbidden');
  if(error instanceof ApiError&&error.status===404)return t('importUnavailable');
  if(error instanceof ApiError&&error.status===0)return copy('Сервермен байланыс жоқ. Байланысты қалпына келтіріп, әрекетті қайталаңыз.','Нет связи с сервером. Восстановите соединение и повторите действие.');
  if(error instanceof ApiError&&error.status>=500)return copy('Сервер жауап бере алмады. Біраздан кейін қайта тексеріңіз. Сақтау басталса, импорт күйін тексеріңіз.','Сервер не смог ответить. Повторите проверку немного позже. Если сохранение уже началось, проверьте статус импорта.');
  return error instanceof Error?error.message:t('importFailed');
 }
 function selectKind(value:string) {
  resetPreview();setKind(value);setCorrectsBatch('');
  if(!correctionKinds.includes(value))setMode('append');
 }
 async function selectFile(file:File|undefined) {
  if(!file||!canImport||locked)return;
  const next=resetPreview(),session=api.csrf;setText('');setFilename(file.name);setFileSize(file.size);
  if(file.size>20*1024*1024||!file.name.toLowerCase().endsWith('.csv')){setError(copy('20 MiB-тен аспайтын .csv файлын таңдаңыз. Excel файлын CSV UTF-8 форматында сақтаңыз.','Выберите файл .csv размером до 20 MiB. Файл Excel сначала сохраните в формате CSV UTF-8.'));return}
  try{const value=await file.text();if(mounted.current&&next===version.current&&session===api.csrf)setText(value)}catch(error){if(mounted.current&&next===version.current)setError(explain(error))}
 }
 function errorGuidance(row:Row) {
  if(row.code==='UNKNOWN_REFERENCE')return copy('Кодты тиісті анықтамалықтан тексеріңіз. Қажетті жазбаны алдымен импорттаңыз.','Проверьте код в соответствующем справочнике. Сначала импортируйте недостающую запись.');
  if(row.code==='INVALID_COLUMNS'||row.code==='EXTRA_COLUMNS')return copy('Осы дерек түрінің CSV үлгісін жүктеп, барлық баған атауын дәл сақтаңыз.','Скачайте шаблон выбранного типа данных и сохраните точные названия всех колонок.');
  if(row.code==='DUPLICATE_KEY'||row.code==='DUPLICATE_CONFLICT')return copy('Бір кілті бар қайталанған жолдарды тексеріңіз. Бар мәнді өзгерту үшін түзету режимін қолданыңыз.','Проверьте строки с одинаковым ключом. Для изменения сохранённых значений используйте режим исправления.');
  if(row.code==='UNIT_MISMATCH')return copy('Өлшем бірлігі ингредиент анықтамалығымен дәл сәйкес болуы керек: kg немесе L.','Единица должна совпадать со справочником ингредиентов: kg или L.');
  if(row.code==='SALES_EXCEED_AVAILABLE')return copy('Сатылған порция саны қолжетімді порциядан аспауы керек.','Проданных порций не может быть больше доступных.');
  if(row.code==='BRANCH_FORBIDDEN')return copy('Осы бөлімшеге рұқсатты әкімшіден сұраңыз.','Запросите у администратора доступ к этому филиалу.');
  if(row.code==='MISSING_VALUE')return copy('Бұл ұяшық міндетті. Бастапқы деректен нақты мәнін енгізіңіз.','Обязательная ячейка пуста. Заполните её фактическим значением из источника.');
  if(row.code==='INVALID_VALUE') {
   if(['date','snapshot_date','expiry_date'].includes(row.field))return copy('Күнді YYYY-MM-DD форматында жазыңыз, мысалы 2025-12-31.','Укажите дату в формате YYYY-MM-DD, например 2025-12-31.');
   if(row.field==='units_sold'||row.field==='available_portions')return copy('0-ден 1 000 000 000-ға дейінгі бүтін сан қажет. Теріс сан мен бөлшек қабылданбайды.','Нужно целое число от 0 до 1 000 000 000. Отрицательные и дробные значения не принимаются.');
   if(['stockout_flag','is_open','promo','synthetic_event'].includes(row.field))return copy('Тек 0 немесе 1 енгізіңіз.','Укажите только 0 или 1.');
   if(String(row.field).endsWith('_id'))return copy('1–64 латын әрпі, сан, _ немесе - қолданыңыз. Бастапқы нөлдерді сақтаңыз.','Используйте 1–64 латинские буквы, цифры, _ или -. Сохраняйте ведущие нули.');
   if(row.field==='data_origin')return copy('Мән жұмыс кеңістігінің деректер режиміне сәйкес болуы керек. Деректің шығу тегін өзгертпеңіз.','Значение должно соответствовать режиму рабочего пространства. Не меняйте реальное происхождение данных.');
  }
  return copy('Осы бағанның мәнін CSV үлгісімен және бастапқы дерекпен салыстырыңыз. Түзеткен соң файлды қайта тексеріңіз.','Сверьте значение колонки с шаблоном CSV и исходными данными. После исправления проверьте файл снова.');
 }
 async function validate() {
  if(!canImport||!types.includes(kind)||!text||pending.current||!online)return;
  if(!sourceCode.test(sourceId)||!sourceCode.test(mappingVersion)||(declaredHash&&!/^[a-fA-F0-9]{64}$/.test(declaredHash))){setError(t('importSourceInvalid'));return}
  if(real&&(!configuredSource||sourceId!==configuredSource.source_id||mappingVersion!==configuredSource.mapping_version)){setError(t('importSourceInvalid'));return}
  if(mode==='correction'&&(!correctionKinds.includes(kind)||reason.trim().length<3)){setError(t('importReasonRequired'));return}
  const current=begin(resetPreview());setAction('preview');
  try {
   const result=await api.post<ImportBatchView>('/imports/preview',{kind,csv_text:text,mode,
    ...(mode==='correction'?{reason:reason.trim(),...(correctsBatch?{corrects_batch_id:correctsBatch}:{})}:{}),
    source:{source_id:sourceId,mapping_version:mappingVersion,...(declaredHash?{declared_original_sha256:declaredHash}:{})}});
   if(current()){setPreview(result);setDone(result.status==='committed');setHistoryRevision(n=>n+1)}
  } catch(error) {if(current())setError(explain(error))}
  finally {finish(current)}
 }
 async function accepted(batch:ImportBatchView,receipt:ImportReceipt,current:()=>boolean) {
  if(!current())return;
  setPreview({...batch,status:'committed',can_commit:false,receipt});setDone(true);setUncertain(false);setError('');setHistoryRevision(n=>n+1);
  await c.refreshWorkspace();
 }
 async function recover(batch:ImportBatchView,current:()=>boolean) {
  if(!current())return;
  setAction('recover');setUncertain(true);
  try {
   const result=await api.request<ImportBatchView>(`/imports/${encodeURIComponent(batch.id)}`);
   if(!current())return;
   if(result.status==='committed')await accepted(result,result.receipt||{id:result.id,status:'committed',row_count:result.row_count},current);
   else {setPreview(result);setError(t('importNotConfirmed'))}
  } catch(error) {if(current())setError(explain(error))}
 }
 async function commit() {
  if(!preview||!canImport||!types.includes(preview.kind)||!(preview.can_commit??preview.valid)||done||pending.current||!online)return;
  if(preview.mode==='correction'&&!reviewed)return;
  const batch=preview,current=begin();setAction('commit');setError('');
  let key=commitKeys.current.get(batch.id);
  if(!key){key=crypto.randomUUID();commitKeys.current.set(batch.id,key)}
  try {
   const receipt=await api.post<ImportReceipt>(`/imports/${encodeURIComponent(batch.id)}/commit`,{}, {'Idempotency-Key':key});
   if(receipt.status!=='committed')throw new Error(t('importNotConfirmed'));
   await accepted(batch,receipt,current);
  } catch(error) {
   if(current()) {
    if(!(error instanceof ApiError)||error.status===0||error.status>=500||error.code==='ALREADY_COMMITTED')await recover(batch,current);
    else {setError(explain(error));if(error.status===409)setPreview({...batch,can_commit:false})}
   }
  } finally {finish(current)}
 }
 async function checkStatus() {
  if(!preview||pending.current||!online)return;
  const current=begin();await recover(preview,current);finish(current);
 }
 async function openBatch(id:string) {
  if(locked)return;
  const current=begin(resetPreview());setAction('detail');setText('');setFilename('');setFileSize(null);
  try {
   const result=await api.request<ImportBatchView>(`/imports/${encodeURIComponent(id)}`);
   if(current()){setPreview(result);setDone(result.status==='committed')}
  }catch(error){if(current())setError(explain(error))}
  finally{finish(current)}
 }
 function startCorrection(batch:ImportBatchView) {
  resetPreview();setKind(batch.kind);setMode('correction');setCorrectsBatch(batch.id);setReason('');setText('');setFilename('');setFileSize(null);
  setSourceId((real?configuredSource?.source_id:batch.source?.source_id)||'manual_csv');setMappingVersion((real?configuredSource?.mapping_version:batch.source?.mapping_version)||'canonical-v1');setDeclaredHash('');
 }
 const countLabels=['rows_seen','rows_checked','parsed','new','unchanged','updated','conflicting'] as const;
 const previewMode=preview?.mode||'append';
 const noChanges=preview?.counts&&preview.counts.new===0&&preview.counts.updated===0&&(preview.counts.unchanged??0)>0;
 const source=preview?.source;
 const readyToSave=Boolean(preview&&(preview.can_commit??preview.valid)&&!uncertain);
 const steps=[copy('Дерек түрі','Тип данных'),copy('CSV файлы','Файл CSV'),copy('Тексеру','Проверка'),copy('Сақтау','Сохранение')];
 const currentStep=done?4:readyToSave?3:preview?2:text?2:1;
 const nextRoute:Record<string,string>={daily_sales:'/sales',inventory_lots:'/inventory',recipes:'/recipes',supplier_offers:'/suppliers',suppliers:'/suppliers',branches:'/dashboard',meals:'/sales',ingredients:'/inventory',calendar:'/dashboard'};
 const nextLabel:Record<string,string>={daily_sales:copy('Сатылымды қарау','Посмотреть продажи'),inventory_lots:copy('Қалдықтарды қарау','Посмотреть остатки'),recipes:copy('Рецепттерді қарау','Посмотреть рецепты'),supplier_offers:copy('Ұсыныстарды қарау','Посмотреть предложения'),suppliers:copy('Жеткізушілерді қарау','Посмотреть поставщиков')};
 return <div className="import-workspace">
  <Heading title={t('imports')} sub={copy('Файлды қосыңыз. Жолдарын тексеріңіз. Содан кейін ғана сақтаңыз.','Добавьте файл. Проверьте строки. Затем сохраните данные.')}/>
  {!canImport&&<div className="alert info" role="status">{t('readOnlyImports')}</div>}
  <div className="import-context"><ShieldCheck size={20} aria-hidden="true"/><p>{t(real?'realImportNotice':'syntheticImportNotice')}{c.dataContext?.usage_mode==='TEST'&&<strong> · {t('testDataContext')}</strong>}{real&&configuredSource&&<span> · {t('branch')}: {configuredSource.branch_id}</span>}</p></div>
  <ol className="import-progress" aria-label={copy('Импорт қадамдары','Этапы импорта')}>{steps.map((label,index)=><li key={label} className={index<currentStep?'is-complete':index===currentStep?'is-current':''} aria-current={index===currentStep?'step':undefined}><span aria-hidden="true">{index<currentStep?<Check size={17}/>:index+1}</span><strong>{label}</strong></li>)}</ol>
  {error&&<div className="alert danger" role="alert">{error}</div>}
  {busy&&<div className="alert info" role="status">{t(action==='recover'?'importRecovering':action==='commit'?'importSaving':'importLoading')}</div>}
  <section className="panel import-panel import-builder">
   <div className="import-section-heading"><span className="import-section-number">01</span><div><h2>{copy('Қандай дерек қосасыз?','Какие данные добавляем?')}</h2></div></div>
   <div className="filters">
    <label className="grow">{t('data')}<select aria-label={t('data')} value={kind} disabled={locked} onChange={event=>selectKind(event.target.value)}>{types.map(value=><option key={value} value={value}>{kindName(value)}</option>)}</select></label>
    {canImport&&<label>{t('importMode')}<select aria-label={t('importMode')} value={mode} disabled={locked} onChange={event=>{resetPreview();setMode(event.target.value as 'append'|'correction');setCorrectsBatch('')}}><option value="append">{t('importAppend')}</option>{correctionKinds.includes(kind)&&<option value="correction">{t('importCorrection')}</option>}</select></label>}
   </div>
   <div className="import-schema-guide"><div><p>{schemaPurpose[kind]?.[kk?0:1]}</p><code>{kind}.csv</code></div><a className="import-template-link" href={`/api/v1/imports/template/${kind}`}><ArrowDownToLine size={16}/>{copy('CSV үлгісі','Шаблон CSV')}</a></div>
   {canImport&&mode==='correction'&&<><div className="alert info">{t('importCorrectionHint')}{correctsBatch&&<span> · {t('importCorrects')}: {correctsBatch}</span>}</div><label>{t('importCorrectionReason')}<input aria-label={t('importCorrectionReason')} minLength={3} maxLength={1000} value={reason} disabled={locked} onChange={event=>{resetPreview();setReason(event.target.value)}}/></label>{reason.trim().length<3&&<p className="muted">{t('importReasonRequired')}</p>}</>}
   <div className="import-section-heading"><span className="import-section-number">02</span><div><h2>{copy('Файлды таңдаңыз','Выберите файл')}</h2><p>{copy('Тексеру деректерді сақтамайды. Нәтижесін алдымен көресіз.','Проверка ещё не сохраняет данные. Сначала вы увидите результат.')}</p></div></div>
   <label className={`file-zone import-file-zone ${dragging?'is-dragging':''}`} onDragOver={event=>{event.preventDefault();if(canImport&&!locked)setDragging(true)}} onDragLeave={()=>setDragging(false)} onDrop={event=>{event.preventDefault();setDragging(false);if(event.dataTransfer.files.length>1){setError(copy('Бір уақытта бір CSV файлын таңдаңыз.','Выберите один файл CSV за раз.'));return}void selectFile(event.dataTransfer.files[0])}}><span className="upload-icon"><FileUp size={27}/></span><strong>{filename||t('chooseFile')}</strong><span>{filename&&fileSize!=null?`${fmt(fileSize/1024,1)} KiB · ${copy('Басқа файлды таңдау үшін басыңыз','Нажмите, чтобы выбрать другой файл')}`:copy('Осында әкеліңіз немесе таңдау үшін басыңыз','Перетащите сюда или нажмите для выбора')}</span><span>{t('fileHint')}</span><input type="file" disabled={!canImport||locked} accept=".csv,text/csv" aria-label={t('chooseFile')} onChange={event=>{const file=event.target.files?.[0];event.target.value='';void selectFile(file)}}/></label>
   <div className="import-actions"><span>{!online?t('offline'):t('importDuplicateHint')}</span><Button disabled={!canImport||!types.includes(kind)||!text||busy||!online||mode==='correction'&&reason.trim().length<3} onClick={validate}>{t('preview')}<ArrowRight size={16}/></Button></div>
   <div className="import-preparation-details">
    <details className="import-format-guide"><summary>{copy('CSV дайындау: бағандар, формат және жүктеу реті','Подготовка CSV: колонки, формат и порядок загрузки')}</summary><p>{schemaCopy[kind]?.purpose[kk?0:1]}</p><p>{copy('Барлық баған міндетті. Бірінші жол — баған атаулары, келесі жолдар — деректер.','Все колонки обязательны. Первая строка — названия колонок, следующие — данные.')}</p><div className="import-column-list">{schemaCopy[kind]?.columns.split(' ').map(field=><span key={field}><strong>{fieldName(field)}</strong><code>{field}</code></span>)}</div><p>{copy('CSV UTF-8 · бөлгіш — үтір · күн — YYYY-MM-DD · ондық белгі — нүкте · өлшем бірлігі — kg немесе L. ID кодтарының бастапқы нөлдерін сақтаңыз.','CSV UTF-8 · разделитель — запятая · дата — YYYY-MM-DD · десятичная точка · единицы — kg или L. Сохраняйте ведущие нули в кодах ID.')}</p><p>{copy('Бос күнді өздігінен нөлге ауыстырмаңыз. Нөлдік сатылым немесе қалдық бөлек нақты жазба болуы керек.','Не заменяйте пропущенный день нулём. Нулевые продажи или остатки должны быть отдельной подтверждённой записью.')}</p></details>
    {canImport&&<details><summary>{t('importSourceSettings')}</summary><div className="filters" style={{paddingTop:12}}>
     <label>{t('importSourceId')}<input aria-label={t('importSourceId')} maxLength={64} value={sourceId} disabled={locked} readOnly={real} onChange={event=>{resetPreview();setSourceId(event.target.value)}}/></label>
     <label>{t('importMappingVersion')}<input aria-label={t('importMappingVersion')} maxLength={64} value={mappingVersion} disabled={locked} readOnly={real} onChange={event=>{resetPreview();setMappingVersion(event.target.value)}}/></label>
     <label className="grow">{t('importDeclaredHash')}<input aria-label={t('importDeclaredHash')} maxLength={64} value={declaredHash} disabled={locked} onChange={event=>{resetPreview();setDeclaredHash(event.target.value)}}/></label>
    </div><p className="muted">{t('importSourceHint')}</p></details>}
   </div>
  </section>
  {preview&&<section className="panel import-review" aria-label={t('importResult')}>
   <div className={`import-review-lead ${done?'is-saved':readyToSave?'is-valid':'needs-fix'}`}><span aria-hidden="true">{done?<CheckCircle2 size={28}/>:readyToSave?<ShieldCheck size={28}/>:<CircleAlert size={28}/>}</span><div><small>{copy('03 / 04 · Тексеру және сақтау','03 / 04 · Проверка и сохранение')}</small><h2>{done?copy('Деректер сақталды','Данные сохранены'):uncertain?copy('Сақтау нәтижесін тексеру керек','Нужно проверить результат сохранения'):readyToSave?copy('Тексерілді. Сақтауға дайын.','Проверено. Можно сохранить.'):preview.valid?copy('Файлды қайта тексеріңіз','Проверьте файл повторно'):copy('Алдымен қателерді түзетіңіз','Сначала исправьте ошибки')}</h2><p>{done?copy('Нәтиже төменде. Келесі қадамға өтуге болады.','Результат ниже. Можно перейти к следующему шагу.'):uncertain?copy('Жауап алынбады. Жаңа импорт бастамай, осы импорттың күйін тексеріңіз.','Ответ не получен. Проверьте статус этого импорта, прежде чем начинать новую загрузку.'):readyToSave?copy('Жолдарды қарап, импортты бөлек батырмамен растаңыз.','Просмотрите строки и подтвердите импорт отдельной кнопкой.'):copy('Осы тексеру бойынша сақтау қолжетімсіз. CSV файлын қарап, қайта тексеріңіз.','Сохранение по этой проверке недоступно. Просмотрите CSV и проверьте его снова.')}</p></div></div>
   <div className="panel-heading"><div><h3>{kindName(preview.kind)}</h3><p>{previewMode==='correction'?t('importCorrection'):t('importAppend')} · {timestamp(preview.created_at)}</p></div><Badge tone={done||readyToSave?'green':'amber'}>{done?t('importCommitted'):uncertain?copy('Нәтиже расталмады','Результат не подтверждён'):readyToSave?t('valid'):preview.valid?t('preview'):t('noImport')}</Badge></div>
   <div style={{padding:'0 24px 16px'}}>
    {preview.branch_ids&&<p>{t('branch')}: {preview.branch_ids.join(', ')||'—'}</p>}
    {preview.period&&<p>{t('from')}: {date(preview.period.from)} · {t('to')}: {date(preview.period.to)}</p>}
    <dl className="import-count-strip"><div><dt>{t('importCount_parsed')}</dt><dd>{fmt(preview.counts?.parsed??preview.row_count)}</dd></div><div><dt>{t('importCount_new')}</dt><dd>{fmt(preview.counts?.new)}</dd></div><div><dt>{t('importCount_updated')}</dt><dd>{fmt(preview.counts?.updated)}</dd></div><div className={preview.errors?.length?'text-danger':''}><dt>{copy('Көрсетілген қателер','Показано ошибок')}</dt><dd>{fmt(preview.errors?.length??0)}{preview.errors_truncated?'+':''}</dd></div></dl>
    {preview.counts&&<details className="import-count-details"><summary>{copy('Барлық тексеру көрсеткіштері','Все счётчики проверки')}</summary><dl className="import-count-strip">{countLabels.map(key=><div key={key}><dt>{t('importCount_'+key)}</dt><dd>{fmt(preview.counts?.[key])}</dd></div>)}</dl></details>}
    {preview.validation_rows_checked!=null&&<p className="muted">{t('importValidationChecked')}: {fmt(preview.validation_rows_checked)}</p>}
    {typeof preview.scan_complete==='boolean'&&<p className="muted">{t(preview.scan_complete?'importScanComplete':'importScanPartial')}{preview.stop_reason?' · '+preview.stop_reason:''}</p>}
    {noChanges&&<div className="alert info">{t('importNoChanges')}</div>}
    {source&&<details><summary>{t('importSourceEvidence')}</summary>{[[t('importSourceId'),source.source_id],[t('importMappingVersion'),source.mapping_version],[t('data'),source.data_origin],[copy('Уақыт белдеуі','Часовой пояс'),source.timezone],[copy('Валюта','Валюта'),source.currency],[t('importProvenance'),source.provenance],[t('importReceivedHash'),preview.received_text_sha256],[t('importCanonicalHash'),preview.canonical_rows_sha256],[t('importDeclaredHash'),source.declared_original_sha256]].map(([label,value])=><div className="settings-row" key={label}><h3>{label}</h3><span style={{overflowWrap:'anywhere',minWidth:0}}>{value??'—'}</span></div>)}</details>}
    {preview.reason&&<p><strong>{t('importCorrectionReason')}: </strong>{preview.reason}</p>}
    <p className="muted">{t('importSample')}{preview.preview_limit!==undefined?' · '+fmt(preview.preview_limit):''}</p>
   </div>
   {Boolean(preview.errors?.length)&&<><div className="import-error-summary"><strong>{copy('Ешбір қате жол ішінара сақталмайды.','Ошибочный файл не сохраняется частично.')}</strong><details><summary>{copy('Мәселелердің топтары','Группы проблем')}</summary><ul>{Object.entries((preview.errors||[]).reduce<Record<string,number>>((groups,row)=>({...groups,[row.code]:(groups[row.code]||0)+1}),{})).map(([code,count])=><li key={code}>{t('error_'+code)==='error_'+code?code:t('error_'+code)} — {fmt(count)}</li>)}</ul></details></div><Table t={t} rows={(preview.errors||[]).slice(errorPage*50,(errorPage+1)*50)} columns={[{key:'row_number',label:t('row')},{key:'field',label:t('field'),render:row=><span className="import-field-name">{fieldName(row.field)}<code>{row.field}</code></span>},{key:'message',label:t('error'),render:(row:Row)=>{const key='error_'+row.code,text=t(key);return text!==key?text:row.message}},{key:'guidance',label:copy('Қалай түзетуге болады','Как исправить'),render:errorGuidance}]}/>{(preview.errors?.length||0)>50&&<div className="import-error-pages"><Button secondary disabled={errorPage===0} onClick={()=>setErrorPage(n=>n-1)}>{copy('Алдыңғы','Назад')}</Button><span>{errorPage*50+1}–{Math.min((errorPage+1)*50,preview.errors!.length)} / {preview.errors!.length}</span><Button secondary disabled={(errorPage+1)*50>=preview.errors!.length} onClick={()=>setErrorPage(n=>n+1)}>{copy('Келесі','Далее')}</Button></div>}{preview.errors_truncated&&<p className="alert info">{t('importErrorsTruncated')}</p>}</>}
   {previewMode==='correction'&&Boolean(preview.changes?.length)?<div className="import-change-list">{preview.changes!.map((change,index)=><details key={index} open><summary>{t('importOperation_'+change.operation)} · <span className="import-change-key">{String(change.key)}</span></summary><Table t={t} rows={Array.from(new Set([...Object.keys(change.before||{}),...Object.keys(change.after||{})])).map(field=>({field,before:change.before?.[field]??'—',after:change.after?.[field]??'—'}))} columns={[{key:'field',label:t('field'),render:row=><span className="import-field-name">{fieldName(row.field)}<code>{row.field}</code></span>},{key:'before',label:t('importBefore')},{key:'after',label:t('importAfter')}]}/></details>)}</div>:!preview.errors?.length&&<Table t={t} rows={preview.preview||[]} columns={Object.keys(preview.preview?.[0]||{}).map(key=>({key,label:fieldName(key)===key?key:`${fieldName(key)} · ${key}`}))}/>}
   <div className="panel-actions" style={{flexWrap:'wrap'}}>
    {done?<><div className="alert success"><CheckCircle2 size={20}/>{t('importDone')}</div>{preview.receipt&&<p>{t('importReceipt')}: {t('importCount_new')} {fmt(preview.receipt.inserted_rows)} · {t('importCount_updated')} {fmt(preview.receipt.updated_rows)} · {t('importCount_unchanged')} {fmt(preview.receipt.unchanged_rows)}</p>}<Button onClick={()=>c.go(returnPath||nextRoute[preview.kind]||'/dashboard')}>{returnPath?copy('Күннің жоспарына оралу','Вернуться к работе над планом'):nextLabel[preview.kind]||copy('Шолуға өту','Перейти к обзору')}<ArrowRight size={16}/></Button>{canImport&&correctionKinds.includes(preview.kind)&&types.includes(preview.kind)&&<Button secondary onClick={()=>startCorrection(preview)}>{t('importCorrectBatch')}</Button>}</>:<>
     <p className="import-save-note">{copy('Сақтау үшін бөлек растау керек. Бірдей жолдар қайталанбайды.','Для сохранения нужно отдельное подтверждение. Одинаковые строки не добавятся повторно.')}</p>
     {preview.counts&&<p><strong>{t('importCount_new')}: {fmt(preview.counts.new)} · {t('importCount_updated')}: {fmt(preview.counts.updated)} · {t('importCount_unchanged')}: {fmt(preview.counts.unchanged)}</strong></p>}
     {previewMode==='correction'&&<label style={{display:'flex',flexDirection:'row',gap:8,alignItems:'center'}}><input type="checkbox" checked={reviewed} disabled={busy} onChange={event=>setReviewed(event.target.checked)}/>{t('importCorrectionReviewed')}</label>}
     {uncertain&&<Button secondary disabled={busy||!online} onClick={checkStatus}>{t('importCheckStatus')}</Button>}
     {canImport&&<Button disabled={!types.includes(preview.kind)||!(preview.can_commit??preview.valid)||busy||!online||previewMode==='correction'&&!reviewed} onClick={commit}><Database size={16}/>{t('commit')}</Button>}
    </>}
   </div>
  </section>}
  <section className="panel import-history" aria-label={t('importHistory')}>
   <div className="panel-heading"><div><h2>{t('importHistory')}</h2><p>{copy('Сақталған және тексерілген файлдарға қайта оралыңыз.','Вернитесь к сохранённым и проверенным файлам.')}</p></div><Button secondary disabled={busy} onClick={()=>setHistoryRevision(n=>n+1)}>{t('retry')}</Button></div>
   <DataState state={history} t={t} retry={()=>setHistoryRevision(n=>n+1)}>
    {items(history.data).length?<div className="import-history-list">{items(history.data).map((batch:Row)=><button className="import-history-row" key={batch.id} disabled={locked} onClick={()=>openBatch(batch.id)} aria-label={t('importOpen')+' '+batch.id}><Files size={21} aria-hidden="true"/><span><strong>{kindName(batch.kind)}</strong><small>{timestamp(batch.created_at)} · {t('importCount_parsed')}: {fmt(batch.counts?.parsed??batch.row_count)}</small></span><Badge tone={batch.status==='committed'?'green':'amber'}>{batch.status==='committed'?t('importCommitted'):batch.valid?t('preview'):t('noImport')}</Badge><ArrowRight size={17} aria-hidden="true"/></button>)}</div>:<p className="import-history-empty">{t('importHistoryEmpty')}</p>}
    <Pagination data={history.data} cursor={cursor} setCursor={setCursor}/>
   </DataState>
  </section>
 </div>;
}
