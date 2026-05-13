import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, DecisionDrawers, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useCoinankMarketIntelligencePayload, useOperatorTruthPayload, usePaperOnlineRuntimePayload } from '../operatorTruthData';
import { CoinankMarketIntelligencePanel, LiveObserverShadowTwinPanel, OperatorTruthLoading, PaperOnlineRuntimeStatusPanel, RouteTruthSummary, SignalLineageTruthPanel } from '../operatorTruthComponents';

export default function SignalExplainabilityPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  const { payload: coinankPayload, error: coinankError } = useCoinankMarketIntelligencePayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Signal Explainability" source="V2_PROOF_ARTIFACT / no-guessing contract">
      <SourceRibbon labels={['feature attribution', 'source freshness', 'risk reason', 'orchestrator reason', 'no guessing']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Signal Explainability" /> : <OperatorTruthLoading error={truthError} />}
      <PaperOnlineRuntimeStatusPanel payload={paperRuntime} />
      {truthPayload ? <SignalLineageTruthPanel payload={truthPayload} /> : null}
      <CoinankMarketIntelligencePanel payload={coinankPayload} error={coinankError} context="Signal Feature Evidence" />
      {truthPayload ? <LiveObserverShadowTwinPanel payload={truthPayload} /> : null}
      {truthPayload?.signal_lineage_status.status !== 'REALTIME_RUNTIME_EVIDENCE' ? (
        <Panel id="signal-explainability-no-guessing" title="No-Guessing Rule" right={<span className="chip solid-warn">MISSING_EVIDENCE</span>}>
          <p className="cockpit-evidence-gap">Evidence missing — cannot explain without guessing.</p>
        </Panel>
      ) : null}
      {payload ? (
        <details className="mission-evidence-details">
          <summary>
            <span>Static proof examples</span>
            <small>Historical decision examples are not current runtime signal lineage.</small>
          </summary>
          <div className="mission-evidence-details__body">
            <DecisionDrawers rows={payload.decisions} />
          </div>
        </details>
      ) : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
