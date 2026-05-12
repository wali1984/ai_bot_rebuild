import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Metric, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

export default function PaperTradingPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime, error: paperError } = usePaperOnlineRuntimePayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Paper / Shadow Runtime" source="CONTINUOUS_NON_LIVE / V2_PROOF_ARTIFACT" status="NOT VALID FOR LIVE READINESS WITHOUT CURRENT RUNTIME">
      <SourceRibbon labels={['paper only', 'shadow only', 'no exchange orders', 'no legacy Redis writes', 'live gate blocked']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Paper Trading" /> : <OperatorTruthLoading error={truthError} />}
      <Panel id="paper-runtime-current-status" title="Current V2 Paper Online Runtime" right={<span className="chip solid-block">No live execution</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Runtime" value={paperRuntime?.runtime_state ?? 'MISSING_EVIDENCE'} />
          <Metric label="Continuous loop" value={String(paperRuntime?.continuous_loop_available ?? false)} />
          <Metric label="Paper events" value={paperRuntime?.paper_loop?.paper_event_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Shadow decisions" value={paperRuntime?.paper_loop?.last_shadow_decision_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Risk blocks" value={paperRuntime?.paper_loop?.last_risk_block_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Exchange orders" value={String(paperRuntime?.exchange_orders ?? false)} />
          <Metric label="Paper equity" value={paperRuntime?.paper_account?.equity ?? 'MISSING_EVIDENCE'} />
          <Metric label="Open positions" value={paperRuntime?.paper_account?.open_position_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Observed price" value={paperRuntime?.market_feed?.price ?? 'MISSING_EVIDENCE'} />
          <Metric label="Market source" value={paperRuntime?.market_feed?.source_type ?? 'MISSING_EVIDENCE'} />
        </div>
        <p className="cockpit-evidence-gap">
          {paperRuntime
            ? `Source generated: ${paperRuntime.generated_at}. This is continuous V2 paper runtime, not live readiness. It fails closed and emits no paper order while current trainer/signal/risk evidence is missing.`
            : `Evidence missing — cannot explain without guessing. Missing source: operator_runtime/paper_online/latest/paper_runtime_status.json. ${paperError ?? ''}`}
        </p>
        {paperRuntime?.blockers?.length ? (
          <div className="missing-evidence-board">
            {paperRuntime.blockers.map((row) => (
              <div className="missing-evidence-card" key={row.id}>
                <strong>{row.id}</strong>
                <p>{row.severity}: {row.detail}</p>
              </div>
            ))}
          </div>
        ) : null}
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
