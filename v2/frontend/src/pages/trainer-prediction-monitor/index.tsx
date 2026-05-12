import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, DecisionDrawers } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary, TrainerPredictionTruthPanel } from '../operatorTruthComponents';

export default function TrainerPredictionMonitorPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Trainer Prediction Monitor" source="V2_PROOF_ARTIFACT / lineage payload">
      <SourceRibbon labels={['prediction_id', 'feature_snapshot_id', 'model checkpoint', 'confidence calibration', 'missing evidence warnings']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Trainer Prediction Monitor" /> : <OperatorTruthLoading error={truthError} />}
      {truthPayload ? <TrainerPredictionTruthPanel payload={truthPayload} /> : null}
      {payload ? <DecisionDrawers rows={payload.decisions} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
