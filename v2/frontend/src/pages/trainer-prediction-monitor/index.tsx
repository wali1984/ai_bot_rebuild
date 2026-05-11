import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, DecisionDrawers } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';

export default function TrainerPredictionMonitorPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Trainer Prediction Monitor" source="V2_PROOF_ARTIFACT / lineage payload">
      <SourceRibbon labels={['prediction_id', 'feature_snapshot_id', 'model checkpoint', 'confidence calibration', 'missing evidence warnings']} />
      {payload ? <DecisionDrawers rows={payload.decisions} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
