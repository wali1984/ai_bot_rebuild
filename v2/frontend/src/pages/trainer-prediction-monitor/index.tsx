import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, DecisionDrawers, Panel } from '../cockpitComponents';
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
      {truthPayload?.trainer_monitor_status.status !== 'REALTIME_RUNTIME_EVIDENCE' ? (
        <Panel id="trainer-current-missing-source" title="Current Trainer Runtime Source Missing" right={<span className="chip solid-warn">TRAINER_RUNTIME_EVIDENCE_MISSING</span>}>
          <p className="cockpit-evidence-gap">
            Evidence missing — cannot explain without guessing. Required source: current trainer process, monitor_trainer_predictions process, prediction stream/log row, and prediction_id plus feature_snapshot_id payload evidence.
          </p>
        </Panel>
      ) : null}
      {payload ? (
        <details className="mission-evidence-details">
          <summary>
            <span>Static proof examples</span>
            <small>Historical fixture decisions are not current trainer output.</small>
          </summary>
          <div className="mission-evidence-details__body">
            <DecisionDrawers rows={payload.decisions} />
          </div>
        </details>
      ) : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
