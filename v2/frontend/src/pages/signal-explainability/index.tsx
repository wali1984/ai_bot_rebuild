import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, DecisionDrawers, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, SignalLineageTruthPanel } from '../operatorTruthComponents';

export default function SignalExplainabilityPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Signal Explainability" source="V2_PROOF_ARTIFACT / no-guessing contract">
      <SourceRibbon labels={['feature attribution', 'source freshness', 'risk reason', 'orchestrator reason', 'no guessing']} />
      <Panel id="signal-explainability-no-guessing" title="No-Guessing Rule" right={<span className="chip solid-warn">MISSING_EVIDENCE</span>}>
        <p className="cockpit-evidence-gap">Evidence missing — cannot explain without guessing.</p>
      </Panel>
      {truthPayload ? <SignalLineageTruthPanel payload={truthPayload} /> : <OperatorTruthLoading error={truthError} />}
      {payload ? <DecisionDrawers rows={payload.decisions} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
