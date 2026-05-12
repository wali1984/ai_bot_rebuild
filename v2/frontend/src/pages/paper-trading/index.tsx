import { useEffect, useState } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Metric, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

interface PaperRuntimeStatus {
  continuous_loop_available?: boolean;
  exchange_orders?: boolean;
  generated_at?: string;
  last_paper_event_count?: number;
  last_risk_block_count?: number;
  last_shadow_decision_count?: number;
  legacy_redis_writes?: boolean;
  live_gate_status?: string;
  runtime?: string;
  writes_only_local_v2_artifacts?: boolean;
}

interface PaperPositions {
  generated_at?: string;
  live_gate_status?: string;
  mode?: string;
  paper_pnl?: number;
  position_count?: number;
  open_positions?: unknown[];
}

function usePaperRuntime(): { status: PaperRuntimeStatus | null; positions: PaperPositions | null } {
  const [status, setStatus] = useState<PaperRuntimeStatus | null>(null);
  const [positions, setPositions] = useState<PaperPositions | null>(null);
  useEffect(() => {
    let active = true;
    fetch('/continuous_paper_shadow_runtime/latest/paper_runtime_status.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<PaperRuntimeStatus> : null)
      .then((next) => { if (active) setStatus(next); })
      .catch(() => { if (active) setStatus(null); });
    fetch('/continuous_paper_shadow_runtime/latest/paper_positions.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<PaperPositions> : null)
      .then((next) => { if (active) setPositions(next); })
      .catch(() => { if (active) setPositions(null); });
    return () => { active = false; };
  }, []);
  return { status, positions };
}

export default function PaperTradingPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { status, positions } = usePaperRuntime();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Paper / Shadow Runtime" source="CONTINUOUS_NON_LIVE / V2_PROOF_ARTIFACT" status="NOT VALID FOR LIVE READINESS WITHOUT CURRENT RUNTIME">
      <SourceRibbon labels={['paper only', 'shadow only', 'no exchange orders', 'no legacy Redis writes', 'live gate blocked']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Paper Trading" /> : <OperatorTruthLoading error={truthError} />}
      <Panel id="paper-runtime-current-status" title="Current Paper / Shadow Runtime" right={<span className="chip solid-block">No live execution</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Runtime" value={status?.runtime ?? 'MISSING_EVIDENCE'} />
          <Metric label="Continuous loop" value={String(status?.continuous_loop_available ?? false)} />
          <Metric label="Paper events" value={status?.last_paper_event_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Shadow decisions" value={status?.last_shadow_decision_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Risk blocks" value={status?.last_risk_block_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Exchange orders" value={String(status?.exchange_orders ?? false)} />
          <Metric label="Paper PnL" value={positions?.paper_pnl ?? 'MISSING_EVIDENCE'} />
          <Metric label="Open positions" value={positions?.position_count ?? 'MISSING_EVIDENCE'} />
        </div>
        <p className="cockpit-evidence-gap">
          {status
            ? `Source generated: ${status.generated_at}. This is non-live proof/runtime status and cannot satisfy live readiness by itself.`
            : 'Evidence missing — cannot explain without guessing. Missing source: continuous paper/shadow runtime payload.'}
        </p>
      </Panel>
      {payload ? (
        <Panel id="paper-signal-risk-context" title="Paper Signal And Risk Context">
          <div className="cockpit-card-grid">
            {payload.decisions.slice(0, 3).map((row) => (
              <div className="cockpit-exchange-card" key={row.id}>
                <h3>{row.symbol}</h3>
                <Metric label="signal_id" value={row.signal_id} />
                <Metric label="risk" value={row.risk_reason} />
                <Metric label="result" value={row.result} />
              </div>
            ))}
          </div>
        </Panel>
      ) : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
