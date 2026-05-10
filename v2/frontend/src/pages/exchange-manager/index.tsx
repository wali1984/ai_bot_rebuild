import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, ExchangeManager } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';

export default function ExchangeManagerPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  return (
    <article className="enterprise-cockpit-page" data-testid="page-exchange-manager" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Exchange Manager</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="cockpit-live-block">order methods disabled</div>
      </header>
      {payload ? <ExchangeManager rows={payload.exchanges} /> : <CockpitLoading error={error} />}
    </article>
  );
}
