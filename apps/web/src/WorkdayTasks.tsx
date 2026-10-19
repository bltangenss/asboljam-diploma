import {useEffect,useRef,useState} from 'react';
import {ArrowRight,Check,Eye} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api,type Context,type Row,date,fmt} from './shared';
import {useWorkdayData} from './workdayData';
import './forecast-review.css';

const texts:Record<string,[string,string,string,string]>={
 DAY_NEEDS_CLOSE:['Күн жабылмаған немесе түзетілген','День не закрыт или изменён','Күнді жабу','Закрыть день'],
 HISTORY_INCOMPLETE:['Сатылым тарихы толық емес','История продаж неполна','Сатылымды толықтыру','Дополнить продажи'],
 RECIPES_INCOMPLETE:['Рецепттерді толықтыру қажет','Нужно дополнить рецептуры','Рецепттерді ашу','Открыть рецепты'],
 INVENTORY_INCOMPLETE:['Есептеу күніне қалдықтар толық емес','Остатки на день расчёта неполны','Қалдықтарды жаңарту','Обновить остатки'],
 FORECAST_STALE:['Болжамның бастапқы деректерін тексеріңіз','Проверьте исходные данные прогноза','Болжамды ашу','Открыть прогноз'],
 PROCUREMENT_NEEDS_DECISION:['Сатып алу шешімді күтеді','Закупка ждёт решения','Жоспарды тексеру','Проверить план'],
 PROCUREMENT_SHORTAGE:['Сатып алу қажеттілікті толық жаппайды','Закупка не покрывает всю потребность','Тапшылықты қарау','Посмотреть дефицит'],
 LOTS_EXPIRING:['Партиялардың жарамдылық мерзімін тексеріңіз','Проверьте сроки годности партий','Қойманы ашу','Открыть склад'],
 FORECAST_READY:['Болжам дайын','Прогноз готов','Порцияларды қарау','Посмотреть порции'],
};
const readinessLabels:Record<string,[string,string,string]>={sales:['Сатылым','Продажи','/sales'],closure:['Күнді жабу','Закрытие дня','/day-close'],history:['Тарих','История','/sales'],recipes:['Рецепттер','Рецептуры','/recipes'],inventory:['Қалдықтар','Остатки','/inventory'],forecast:['Болжам','Прогноз','/forecasts']};
const statusLabels:Record<string,[string,string]>={complete:['Толық','Полные'],available:['Бар','Есть'],closed:['Жабық','Закрыт'],unchanged:['Өзгермеген','Не изменились'],unconfirmed:['Расталмаған','Не подтверждены'],incomplete:['Толық емес','Неполные'],missing:['Жоқ','Нет'],draft:['Жоба','Черновик'],reopened:['Қайта ашылған','Открыт повторно'],changed:['Өзгерген','Изменились'],unknown:['Белгісіз','Неизвестно']};

export default function WorkdayTasks(c:Context){
 return <TaskWorkspace key={JSON.stringify([c.user.organization_id,c.user.id,c.user.role,c.branch])} context={c}/>;
}

function TaskWorkspace({context:c}:{context:Context}){
 const kk=c.lang==='kk',w=(kz:string,ru:string)=>kk?kz:ru;
 const [revision,reload]=useState(0),[busy,setBusy]=useState(''),[error,setError]=useState(''),[viewed,setViewed]=useState<Set<string>>(new Set());
 const mounted=useRef(true),pending=useRef(false);
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 const state=useWorkdayData(c,c.branch?'/workday-tasks?branch_id='+encodeURIComponent(c.branch):null,revision);
 const data=state.data?.branch_id===c.branch&&Array.isArray(state.data.items)?state.data:null;
 async function acknowledge(id:string){
  if(pending.current||!c.online)return;pending.current=true;setBusy(id);setError('');const csrf=api.csrf;
  try{
   const receipt=await api.post('/workday-tasks/'+encodeURIComponent(id)+'/view',{branch_id:c.branch});
   if(!mounted.current||api.csrf!==csrf)return;
   if(receipt?.id!==id||receipt.viewed!==true)throw new Error('Unconfirmed read receipt');
   setViewed(previous=>new Set([...previous,id]));
  }catch(problem){if(mounted.current&&api.csrf===csrf){
   if(problem instanceof ApiError&&problem.status===404){reload(value=>value+1);setError(w('Бұл ескерту енді өзекті емес. Тізім жаңартылды.','Предупреждение уже неактуально. Список обновлён.'))}
   else setError(w('Қаралғаны расталмады. Қайталап көріңіз.','Не удалось подтвердить просмотр. Попробуйте ещё раз.'));
  }}finally{if(mounted.current&&api.csrf===csrf){pending.current=false;setBusy('')}}
 }
 if(state.loading)return <p role="status">{w('Күн міндеттерін тексереміз…','Проверяем задачи дня…')}</p>;
 if(state.error||!data)return <p className="alert warning" role="alert">{w('Күн міндеттері жүктелмеді. Ескерту жоқ деп қорытынды жасамаңыз.','Задачи дня не загрузились. Это не означает отсутствия предупреждений.')} <button className="text-button" onClick={()=>reload(value=>value+1)}>{c.t('retry')}</button></p>;
 const list:Row[]=data.items;
 function detail(item:Row){
  const d=item.details||{};
  if(item.code==='HISTORY_INCOMPLETE')return `${w('Тарихы дайын тағамдар','Блюд с готовой историей')}: ${fmt(d.ready_meals)} / ${fmt(d.total_meals)} · ${w('кемінде','нужно не менее')} ${fmt(d.required_days)} ${w('күн','дней')}.`;
  if(item.code==='PROCUREMENT_SHORTAGE'||item.code==='LOTS_EXPIRING')return `${w('Позиция саны','Позиций')}: ${fmt(d.count)}.`;
  if(item.code==='FORECAST_STALE')return w('Бастапқы деректер өзгерген немесе өзектілігі белгісіз.','Источники изменились или их актуальность неизвестна.');
  if(item.code==='DAY_NEEDS_CLOSE')return w('Барлық тағамның нақты сатылымын тексеріңіз. Бос мән нөл емес.','Проверьте фактические продажи всех блюд. Пустое значение не равно нулю.');
  if(item.code==='PROCUREMENT_NEEDS_DECISION')return w('Бекіту — адамның бөлек шешімі.','Утверждение остаётся отдельным решением человека.');
  return '';
 }
 return <div className="workday-tasks" data-testid="workday-tasks">
  <div className="workday-task-heading"><h2>{w('Өзекті міндеттер','Актуальные задачи')} · {list.length}</h2><button className="text-button" disabled={!!busy} onClick={()=>reload(value=>value+1)}>{w('Жаңарту','Обновить')}</button></div>
  {list.length?<ul className="workday-task-list">{list.map(item=>{const text=texts[item.code],read=item.viewed||viewed.has(item.id);return <li key={item.id} className="workday-task" data-testid={'task-'+item.code}><div><h3>{text?.[kk?0:1]||w('Деректерді тексеру қажет','Нужно проверить данные')}</h3><p>{c.branchName||c.branch} · {date(item.business_date)}{detail(item)&&<> · {detail(item)}</>}</p><p>{item.expires_at?w('Өзекті мерзімі','Актуально до')+': '+new Date(item.expires_at).toLocaleString(kk?'kk-KZ':'ru-RU'):w('Оқу сценарийі: себеп жойылғанша өзекті.','Учебный сценарий: актуально до устранения причины.')}{item.details?.freshness&&<> · {w('Есеп деректері','Данные расчёта')}: {statusLabels[item.details.freshness]?.[kk?0:1]||w('Белгісіз','Неизвестно')}</>}</p></div><div className="workday-task-actions"><button className="text-button" onClick={()=>c.go(item.action_url)}>{text?.[kk?2:3]||w('Ашу','Открыть')}<ArrowRight size={14}/></button>{read?<small><Check size={13}/>{w('Қаралды, себеп әлі бар','Просмотрено, причина ещё есть')}</small>:<button className="text-button" disabled={!!busy||!c.online} onClick={()=>void acknowledge(item.id)}><Eye size={14}/>{w('Қаралды деп белгілеу','Отметить просмотренным')}</button>}</div></li>})}</ul>:<p className="muted">{w('Қазір белгілі міндет жоқ. Бұл модель дәлдігіне кепілдік бермейді.','Сейчас известных задач нет. Это не гарантирует точность модели.')}</p>}
  {error&&<p className="alert warning" role="alert">{error}</p>}
  <details className="review-details workday-readiness"><summary>{w('Деректердің дайындығы','Готовность данных')}</summary><p className="muted">{w('Бұл — деректердің күйі, модель сенімділігі немесе сатып алуды бекіту рұқсаты емес.','Это состояние данных, а не уверенность модели или разрешение утвердить закупку.')}</p><ul>{Object.entries(readinessLabels).map(([key,label])=>{const entry=data.readiness?.[key];return <li key={key}><strong>{label[kk?0:1]}</strong> {statusLabels[entry?.status]?.[kk?0:1]||w('Белгісіз','Неизвестно')}{entry?.date&&<> · {date(entry.date)}</>}{key==='history'&&<> · {w('дайын тағам','готовых блюд')}: {fmt(entry?.ready_meals)} · {w('қажет','нужно')} {fmt(entry?.required_days)} {w('күн','дней')}</>} <button className="text-button" onClick={()=>c.go(key==='closure'&&entry?.date?'/day-close?date='+encodeURIComponent(entry.date):label[2])}>{w('Тексеру','Проверить')}<ArrowRight size={13}/></button></li>})}</ul></details>
 </div>;
}
