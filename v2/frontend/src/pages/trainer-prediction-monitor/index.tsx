import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, DecisionDrawers } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';

export default function TrainerPredictionMonitorPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  return (
    <article className="enterprise-cockpit-page" data-testid="page-trainer-prediction-monitor" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Trainer Prediction Monitor</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
      </header>
      {payload ? <DecisionDrawers rows={payload.decisions} /> : <CockpitLoading error={error} />}
    </article>
  );
}
