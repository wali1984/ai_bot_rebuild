import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, QuarantinePanel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';

export default function ExternalManualPositionQuarantinePage(): JSX.Element {
  const { quarantine, error } = useCockpitPayload();
  return (
    <article className="enterprise-cockpit-page" data-testid="page-external-manual-position-quarantine" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole} style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">2X Quarantine</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="cockpit-live-block">monitor-only; no auto-close</div>
      </header>
      {quarantine ? <QuarantinePanel payload={quarantine} /> : <CockpitLoading error={error} />}
    </article>
  );
}
