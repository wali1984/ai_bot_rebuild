import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, ConfigTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';

export default function ConfigAdminPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  return (
    <article className="enterprise-cockpit-page" data-testid="page-config-admin" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Config Admin</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="cockpit-live-block">live-impacting changes require human approval</div>
      </header>
      {payload ? <ConfigTable rows={payload.settings} /> : <CockpitLoading error={error} />}
    </article>
  );
}
