import meta from './meta';
import rbac from './rbac';
import route from './route';
import { PageShell } from '../../components/layout/PageShell';
import { SystemResourcesPanel } from '../../components/system/SystemResourcesPanel';

export default function SystemHealthPage(): JSX.Element {
  return (
    <div>
      <div style={{ padding: '20px 24px 0' }}>
        <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
          System Resources
        </h2>
        <SystemResourcesPanel />
      </div>
      <PageShell meta={meta} rbac={rbac} route={route} />
    </div>
  );
}
