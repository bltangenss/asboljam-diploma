import {Building2, FileUp, Settings} from 'lucide-react';
import {Button, Heading, type Context} from './shared';

export default function Onboarding({t, user, organization, workspace, go, online}:Context) {
  const unconfigured=organization?.data_policy!=='synthetic_only';
  const canAddBranch=!unconfigured && user?.role==='admin' && workspace?.onboarding.can_import_branches===true;
  return <section aria-labelledby="onboarding-heading" data-testid="workspace-onboarding">
    <Heading title={t(unconfigured?'dataSetupTitle':'emptyWorkspaceTitle')} sub={organization?.name??'—'}/>
    <div className="panel detail-panel">
      <Building2 size={30}/>
      <h2 id="onboarding-heading">{t(unconfigured?'dataSetupPending':canAddBranch?'firstBranchTitle':'noBranchAccessTitle')}</h2>
      <p>{t(unconfigured?'dataSetupBody':canAddBranch?'firstBranchBody':'noBranchAccessBody')}</p>
      {canAddBranch&&<p className="muted">{t('syntheticImportNotice')}</p>}
      <div className="panel-actions" style={{flexWrap:'wrap',gap:12,padding:'20px 0 0'}}>
        <Button secondary onClick={()=>go('/settings')}><Settings size={16}/>{t('settings')}</Button>
        {canAddBranch&&<Button disabled={!online} onClick={()=>go('/imports?kind=branches')}><FileUp size={16}/>{t('addFirstBranch')}</Button>}
      </div>
    </div>
  </section>;
}
