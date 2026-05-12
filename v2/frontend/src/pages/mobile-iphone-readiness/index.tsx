import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Panel } from '../cockpitComponents';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

export default function MobileIphoneReadinessPage(): JSX.Element {
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Mobile / iPhone Readiness" source="V2_PROOF_ARTIFACT / mobile readiness checklist" status="NO BACKGROUND TRADE ACTIONS">
      <SourceRibbon labels={['responsive cockpit', 'future PWA path', 'future iPhone bridge', 'live gate still human-only']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Mobile / iPhone Readiness" /> : <OperatorTruthLoading error={truthError} />}
      <Panel id="mobile-iphone-readiness-checklist" title="Mobile Readiness Contract" right={<span className="chip solid-paper">Non-live path</span>}>
        <div className="cockpit-card-grid">
          <div className="cockpit-exchange-card">
            <h3>Responsive cockpit</h3>
            <p>Mission Control and secondary admin pages use responsive grid collapse and stable panel dimensions.</p>
            <strong>READY_FOR_BROWSER_CHECK</strong>
          </div>
          <div className="cockpit-exchange-card">
            <h3>PWA / mobile route path</h3>
            <p>Local service worker policy remains cache-safe for dev, and mobile route work remains non-live.</p>
            <strong>V2_PROOF_ARTIFACT</strong>
          </div>
          <div className="cockpit-evidence-gap">
            Evidence missing - cannot explain without guessing. Missing source: native iPhone app bridge and mobile push/action policy.
          </div>
          <div className="cockpit-evidence-gap">
            No background trade action is allowed from mobile surfaces. Final live/capital gate remains human-only.
          </div>
        </div>
      </Panel>
    </DesignPageShell>
  );
}
