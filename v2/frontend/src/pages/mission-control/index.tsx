import meta from './meta';
import rbac from './rbac';
import route from './route';
import { PageShell } from '../../components/layout/PageShell';
import { AgentHealthPanel } from '../../components/dashboard/AgentHealthPanel';
import { QueueStatusPanel } from '../../components/dashboard/QueueStatusPanel';
import { StaleStateAlertsPanel } from '../../components/dashboard/StaleStateAlertsPanel';
import { BuildValidationPanel } from '../../components/dashboard/BuildValidationPanel';

export default function MissionControlPage(): JSX.Element {
  return (
    <>
      <PageShell meta={meta} rbac={rbac} route={route} />
      <div
        className="mission-control-dashboard"
        data-testid="mission-control-dashboard"
      >
        <AgentHealthPanel />
        <QueueStatusPanel />
        <StaleStateAlertsPanel />
        <BuildValidationPanel />
      </div>
    </>
  );
}
