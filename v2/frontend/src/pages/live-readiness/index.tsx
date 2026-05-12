import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Metric, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

export default function LiveReadinessPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Live Readiness" source="GO_NO_GO / final live gate policy" status="FINAL LIVE CAPITAL APPROVAL REQUIRED">
      <SourceRibbon labels={['live blocked', 'human-only final gate', 'dangerous controls disabled', 'paper/shadow first']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Live Readiness" /> : <OperatorTruthLoading error={truthError} />}
      {payload ? (
        <Panel id="live-readiness-hard-stop" title="Live Readiness Hard Stop" right={<span className="chip solid-block">LIVE BLOCKED</span>}>
          <div className="cockpit-analytics-grid">
            <Metric label="Live gate" value={payload.live_gate_status} />
            <Metric label="Account mode" value={payload.account_mode} />
            <Metric label="Supervisor truth" value={truthPayload?.supervisor_status.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'} />
            <Metric label="Trainer runtime" value={truthPayload?.trainer_monitor_status.status ?? 'MISSING_EVIDENCE'} />
            <Metric label="Stale payloads" value={truthPayload?.dashboard_freshness_status.stale_payload_count ?? 'MISSING_EVIDENCE'} />
            <Metric label="Missing evidence" value={truthPayload?.dashboard_freshness_status.missing_evidence_count ?? 'MISSING_EVIDENCE'} />
          </div>
          <div className="cockpit-card-grid">
            {payload.blockers.map((row) => (
              <div className="cockpit-evidence-gap" key={row.id}>
                <strong>{row.id}</strong>
                <p>{row.status}: {row.detail}</p>
              </div>
            ))}
            <div className="cockpit-evidence-gap">
              Final live/capital approval is not reached. Real orders, cancels, live keys, leverage, margin mode, and live deployment remain blocked.
            </div>
          </div>
        </Panel>
      ) : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
