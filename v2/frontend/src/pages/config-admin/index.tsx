import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, ConfigTable } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

export default function ConfigAdminPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Config Admin" source="V2_PROOF_ARTIFACT / classified settings" status="LIVE-IMPACTING CHANGES REQUIRE APPROVAL">
      <SourceRibbon labels={['safe_to_edit', 'requires_validation', 'requires_explicit_human_approval', 'read_only', 'remove_or_replace']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Config Admin" /> : <OperatorTruthLoading error={truthError} />}
      {payload ? <ConfigTable rows={payload.settings} /> : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
