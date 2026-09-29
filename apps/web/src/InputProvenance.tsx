import {Button, type Context} from './shared';

export default function InputProvenance({data, context}:{data:any;context:Context}) {
 const {lang,go}=context,kk=lang==='kk';
 const state=data.input_freshness??'unknown',summary=data.input_provenance;
 return <section className="panel detail-panel" data-testid="input-provenance">
  <h2>{kk?'Есептің бастапқы деректері':'Исходные данные расчёта'}</h2>
  <p role={state==='changed'?'alert':'status'}>{state==='unchanged'
   ?(kk?'Есепке кірген деректер өзгермеген.':'Использованные в расчёте данные не изменились.')
   :state==='changed'
   ?(kk?'Бастапқы деректер өзгерді. Бекітуден бұрын болжам мен сатып алуды қайта есептеңіз.':'Исходные данные изменились. Перед утверждением пересчитайте прогноз и закупку.')
   :(kk?'Бұл есептің бастапқы деректерін тексеру мүмкін емес. Бекітуден бұрын қайта есептеңіз.':'Происхождение этого расчёта нельзя проверить. Перед утверждением выполните новый расчёт.')}</p>
  <p className="muted">{kk?'Сақталған есеп пен бұрынғы шешім өзгермейді.':'Сохранённый расчёт и ранее принятое решение остаются неизменными.'}</p>
  {summary&&<details><summary>{kk?'Жүктемелер мен қамту':'Загрузки и охват'} · {summary.record_count??'—'}</summary>
   {(summary.kinds??[]).map((kind:any)=><div key={kind.kind}>
    <h3>{kind.kind} · {kind.record_count}</h3>
    {!!kind.legacy_record_count&&<p className="muted">{kk?'Жүктеме көзі тіркелмеген жолдар':'Строки без зарегистрированной исходной загрузки'}: {kind.legacy_record_count}</p>}
    <ul>{(kind.batches??[]).map((batch:any)=><li key={batch.batch_id}>
     <button type="button" className="text-button" onClick={()=>go('/imports?batch='+encodeURIComponent(batch.batch_id))}>
      {kk?'Импорт':'Импорт'} {String(batch.batch_id).slice(0,8)} · {batch.record_count}
     </button>
    </li>)}</ul>
   </div>)}
  </details>}
  {state!=='unchanged'&&<Button secondary onClick={()=>go('/forecasts')}>{kk?'Жаңа болжамға өту':'Перейти к новому прогнозу'}</Button>}
 </section>;
}
