import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, MonitorTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, PayloadFreshnessPanel, RouteTruthSummary } from '../operatorTruthComponents';

export default function MonitorCenterPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Monitor Center" source="RUNTIME_MONITOR_PAYLOAD / V2_PROOF_ARTIFACT">
      <SourceRibbon labels={['runtime monitor rows', 'read-only status', 'freshness required', 'no service restart']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Monitor Center" /> : <OperatorTruthLoading error={truthError} />}
      {truthPayload ? <PayloadFreshnessPanel payload={truthPayload} /> : null}
      {payload ? <MonitorTable rows={payload.monitors} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
