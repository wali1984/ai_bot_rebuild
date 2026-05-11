import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, MonitorTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';

export default function MonitorCenterPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Monitor Center" source="RUNTIME_MONITOR_PAYLOAD / V2_PROOF_ARTIFACT">
      <SourceRibbon labels={['runtime monitor rows', 'read-only status', 'freshness required', 'no service restart']} />
      {payload ? <MonitorTable rows={payload.monitors} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
