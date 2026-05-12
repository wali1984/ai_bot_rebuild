import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, MonitorTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, PayloadFreshnessPanel } from '../operatorTruthComponents';

export default function MonitorCenterPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Monitor Center" source="RUNTIME_MONITOR_PAYLOAD / V2_PROOF_ARTIFACT">
      <SourceRibbon labels={['runtime monitor rows', 'read-only status', 'freshness required', 'no service restart']} />
      {truthPayload ? <PayloadFreshnessPanel payload={truthPayload} /> : <OperatorTruthLoading error={truthError} />}
      {payload ? <MonitorTable rows={payload.monitors} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
