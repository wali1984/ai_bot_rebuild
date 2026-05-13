import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useCoinankMarketIntelligencePayload, useOperatorTruthPayload } from '../operatorTruthData';
import { CoinankMarketIntelligencePanel, OperatorTruthLoading, PayloadFreshnessPanel, RouteTruthSummary } from '../operatorTruthComponents';

export default function BuildValidationStatusPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: coinankPayload, error: coinankError } = useCoinankMarketIntelligencePayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Build Validation Status" source="V2_PROOF_ARTIFACT / GO-NO-GO markers">
      <SourceRibbon labels={['proof freshness', 'GO_NO_GO markers', 'Codex review status', 'missing evidence gaps']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Build Validation Status" /> : <OperatorTruthLoading error={truthError} />}
      <CoinankMarketIntelligencePanel payload={coinankPayload} error={coinankError} context="Build Validation" />
      {truthPayload ? <PayloadFreshnessPanel payload={truthPayload} /> : null}
      {payload ? (
        <Panel id="build-validation-proof-freshness" title="Proof Freshness And Blockers" right={<span className="chip solid-paper">Evidence page summary</span>}>
          <div className="cockpit-card-grid">
            {payload.proof_freshness.map((row) => (
              <div className="cockpit-exchange-card" key={row.artifact}>
                <h3>{row.artifact}</h3>
                <p>Source generated: {row.source_generated_at}</p>
                <p>Public copied: {row.public_copied_at}</p>
                <strong>{row.state}</strong>
              </div>
            ))}
            {payload.blockers.map((row) => (
              <div className="cockpit-evidence-gap" key={row.id}>
                <strong>{row.id}</strong>
                <p>{row.status}: {row.detail}</p>
              </div>
            ))}
          </div>
        </Panel>
      ) : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
