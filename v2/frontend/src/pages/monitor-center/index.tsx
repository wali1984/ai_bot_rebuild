import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, MonitorTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useCoinankMarketIntelligencePayload, useOperatorTruthPayload } from '../operatorTruthData';
import { CoinankMarketIntelligencePanel, OperatorTruthLoading, PayloadFreshnessPanel, RouteTruthSummary } from '../operatorTruthComponents';

export default function MonitorCenterPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: coinankPayload, error: coinankError } = useCoinankMarketIntelligencePayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Monitor Center" source="RUNTIME_MONITOR_PAYLOAD / V2_PROOF_ARTIFACT">
      <SourceRibbon labels={['runtime monitor rows', 'read-only status', 'freshness required', 'no service restart']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Monitor Center" /> : <OperatorTruthLoading error={truthError} />}
      <CoinankMarketIntelligencePanel payload={coinankPayload} error={coinankError} context="Monitor Center" />
      {payload ? <MonitorTable rows={payload.monitors} /> : <CockpitLoading error={error} />}
      {truthPayload ? (
        <details className="mission-evidence-details">
          <summary>
            <span>Payload freshness details</span>
            <small>Open stale/static public payload audit.</small>
          </summary>
          <div className="mission-evidence-details__body">
            <PayloadFreshnessPanel payload={truthPayload} />
          </div>
        </details>
      ) : null}
    </DesignPageShell>
  );
}
