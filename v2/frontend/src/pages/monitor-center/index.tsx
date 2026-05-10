import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, MonitorTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';

export default function MonitorCenterPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  return (
    <article className="enterprise-cockpit-page" data-testid="page-monitor-center" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Monitor Center</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
      </header>
      {payload ? <MonitorTable rows={payload.monitors} /> : <CockpitLoading error={error} />}
    </article>
  );
}
