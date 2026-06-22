import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Metric, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload, useTonightReadinessPayload } from '../operatorTruthData';
import { OperatorTruthLoading, PaperOnlineRuntimeStatusPanel, RouteTruthSummary } from '../operatorTruthComponents';

export default function LiveReadinessPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  const { payload: tonightPayload } = useTonightReadinessPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Live Readiness" source="GO_NO_GO / final live gate policy" status="FINAL LIVE CAPITAL APPROVAL REQUIRED">
      <SourceRibbon labels={['operator gated', 'human-only final gate', 'dangerous controls disabled', 'execution/shadow first']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Live Readiness" /> : <OperatorTruthLoading error={truthError} />}
      <PaperOnlineRuntimeStatusPanel payload={paperRuntime} />
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
      <Panel id="live-like-risk-profile" title="Live-Like Paper/Shadow Risk Profile" right={<span className="chip solid-block">CANARY BLOCKED</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Tonight status" value={tonightPayload?.status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Risk profile" value={tonightPayload?.risk_profile_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Canary preflight" value={tonightPayload?.canary_preflight_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="V2 paper runtime" value={tonightPayload?.v2_paper_runtime_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Legacy bridge" value={tonightPayload?.legacy_bridge_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Public route failures" value={tonightPayload?.public_route_failed_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Old Redis writes" value={String(tonightPayload?.old_redis_writes ?? false)} />
          <Metric label="Exchange actions" value={String(tonightPayload?.exchange_actions ?? false)} />
        </div>
        <p className="cockpit-evidence-gap">
          Live trading and canary activation remain blocked_human_only. This page displays the preflight/risk profile only; it cannot approve or execute live orders.
        </p>
        {tonightPayload?.remaining_blockers?.length ? (
          <div className="missing-evidence-board">
            {tonightPayload.remaining_blockers.slice(0, 8).map((blocker) => (
              <div className="missing-evidence-card" key={blocker}>
                <strong>{blocker}</strong>
                <p>Resolve before any final human canary approval packet is considered.</p>
              </div>
            ))}
          </div>
        ) : null}
      </Panel>
    </DesignPageShell>
  );
}
