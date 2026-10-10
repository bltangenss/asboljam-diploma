import type {Context,Row} from './shared';
import {date} from './shared';

/** Show the immutable basis saved with this plan, not today's stock view. */
export default function StockPlanEvidence({result,lang}:{result:Row;lang:Context['lang']}) {
  const stock=result.stock_evidence, recipe=result.recipe_evidence, kk=lang==='kk';
  if(!stock&&!recipe)return null;
  return <section className="panel detail-panel" aria-label={kk?'Жоспардың қойма негізі':'Основание плана по складу'}>
    <h2>{kk?'Қор мен рецептураның негізі':'На каких остатках и рецептах рассчитан план'}</h2>
    {stock&&<p>{stock.source==='reconciled_counted_snapshot'
      ?(kk?'Саналған қор қойма журналымен салыстырылып, сәйкес келді.':'Посчитанный остаток сверили с журналом: расхождений нет.')
      :(kk?'Осы күнге импортталған саналған қор.':'Импортированный посчитанный остаток на указанную дату.')}
      {' '}{date(stock.target_date)}
      {stock.baseline_date&&<> · {kk?'Журнал басы':'Начало журнала'}: {date(stock.baseline_date)} · {kk?'Қозғалыстар':'Движений'}: {stock.movement_count}</>}
    </p>}
    {recipe?.source==='dated_activations'?<>
      <p>{kk?'Осы күнге бекітілген толық рецепттер. Шикізат шығымы әр нұсқада сақталған.':'Полные версии рецептов, действовавшие на дату расчёта. Выход сырья сохранён в каждой версии.'}</p>
      <ul>{(recipe.activations||[]).map((row:Row)=><li key={row.id}>{row.meal_id} · {row.recipe_version} · {date(row.effective_date)}</li>)}</ul>
    </>:recipe&&<p>{kk?'Импортталған CSV рецептурасы':'Импортированная рецептура CSV'}: {recipe.recipe_versions?.join(', ')||'—'}</p>}
  </section>;
}
