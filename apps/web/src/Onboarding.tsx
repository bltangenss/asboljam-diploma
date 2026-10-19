import {ArrowRight,Building2,FileUp,Settings} from 'lucide-react';
import {Button, Heading, type Context} from './shared';
import './import-ui.css';

export default function Onboarding({t,lang,user,organization,workspace,dataContext,go,online}:Context) {
  const copy=(kk:string,ru:string)=>lang==='kk'?kk:ru;
  const unconfigured=dataContext?.operations_enabled!==true;
  const canAddBranch=!unconfigured && user?.role==='admin' && workspace?.onboarding.can_import_branches===true;
  return <section className="workspace-welcome" aria-labelledby="onboarding-heading" data-testid="workspace-onboarding">
    <Heading title={t(unconfigured?'dataSetupTitle':'emptyWorkspaceTitle')} sub={organization?.name??'—'}/>
    <div className="welcome-journey" aria-label={copy('Жұмыс жолы','Путь работы')}>{[copy('Деректер','Данные'),copy('Болжам','Прогноз'),copy('Сатып алу','Закупка'),copy('Шешім','Решение')].map((label,index)=><span className={index===0?'current':''} key={label}><b>{String(index+1).padStart(2,'0')}</b>{label}{index<3&&<ArrowRight size={17} aria-hidden="true"/>}</span>)}</div>
    <div className="welcome-next-step">
      <Building2 size={34} aria-hidden="true"/>
      <div className="welcome-next-copy"><p className="welcome-eyebrow">{copy('Алғашқы қадам','Первый шаг')}</p>
      <h2 id="onboarding-heading">{t(unconfigured?'dataSetupPending':canAddBranch?'firstBranchTitle':'noBranchAccessTitle')}</h2>
      <p>{t(unconfigured?'dataSetupBody':canAddBranch?'firstBranchBody':'noBranchAccessBody')}</p>
      {canAddBranch&&<p className="muted">{t(dataContext?.data_origin==='REAL'?'realImportNotice':'syntheticImportNotice')}</p>}
      <div className="welcome-actions">
        {canAddBranch&&<Button disabled={!online} onClick={()=>go('/imports?kind=branches')}><FileUp size={16}/>{t('addFirstBranch')}</Button>}
        <Button secondary={canAddBranch} onClick={()=>go('/settings')}><Settings size={16}/>{t('settings')}</Button>
      </div>
      {!online&&<p className="welcome-offline">{t('offline')}</p>}
      </div>
    </div>
    {unconfigured&&<section className="welcome-operator"><h2>{copy('Әкімшіге не дайындау керек','Что подготовить администратору')}</h2><p>{copy('Ұйым атауы, бөлімше, уақыт белдеуі, валюта және деректерді пайдалануға рұқсат туралы мәлімет. Дерек көзін тіркегеннен кейін ғана импорт ашылады.','Название организации, филиал, часовой пояс, валюта и основание для использования данных. Импорт станет доступен после регистрации источника.')}</p><p>{copy('Бизнес деректері мен жасанды мысалдар бөлек жұмыс кеңістіктерінде сақталады.','Данные бизнеса и искусственные примеры хранятся в отдельных рабочих пространствах.')}</p></section>}
    <section className="welcome-data-map" aria-labelledby="welcome-data-heading"><h2 id="welcome-data-heading">{copy('Predas-қа не қажет?','Что нужно Predas?')}</h2><p>{copy('Бұл дайындық тізімі. Нақты толықтық файлдарды жүктегеннен кейін тексеріледі.','Это список подготовки. Фактическая полнота проверяется после загрузки файлов.')}</p><div className="welcome-data-columns"><div><span className="welcome-eyebrow">{copy('Болжам үшін','Для прогноза')}</span><h3>{copy('Мәзір және сатылым тарихы','Меню и история продаж')}</h3><ol><li><strong>{copy('Бөлімшелер мен тағамдар','Филиалы и блюда')}</strong><span>branches.csv · meals.csv</span></li><li><strong>{copy('Күнделікті сатылған порциялар','Проданные порции по дням')}</strong><span>daily_sales.csv</span></li></ol><p>{copy('Әр тағамға кемінде 84 күндік үздіксіз бақылау қажет. Дерегі жоқ күн нөлдік сатылым емес.','Нужно минимум 84 дня непрерывных наблюдений по блюду. Пропуск не считается нулевой продажей.')}</p></div><div><span className="welcome-eyebrow">{copy('Сатып алу үшін қосымша','Дополнительно для закупки')}</span><h3>{copy('Құрам, қор және ұсыныстар','Состав, остатки и предложения')}</h3><ol><li><strong>{copy('Ингредиенттер мен рецепттер','Ингредиенты и рецепты')}</strong><span>ingredients.csv · recipes.csv</span></li><li><strong>{copy('Нақты күнге саналған қалдық','Пересчитанные остатки на нужную дату')}</strong><span>inventory_lots.csv</span></li><li><strong>{copy('Жеткізушілер және қаптама бағасы','Поставщики и цены упаковок')}</strong><span>suppliers.csv · supplier_offers.csv</span></li></ol></div></div><p className="welcome-calendar-note">{copy('Тоғызыншы файл — calendar.csv, жұмыс күнтізбесі. Қазіргі болжам ауа райы мен оқиғаларды белгі ретінде қолданбайды.','Девятый файл — calendar.csv, календарь работы. Текущая модель не использует погоду и события как признаки.')}</p></section>
  </section>;
}
