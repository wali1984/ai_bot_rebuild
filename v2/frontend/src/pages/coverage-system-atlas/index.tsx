import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Metric, Panel, SystemAtlasGapRemediationPanel } from '../cockpitComponents';
import type { SystemAtlasGapRemediationPayload, SystemAtlasPayload } from '../cockpitData';
import { usePayloadFile } from '../../hooks/usePayloadFile';

export default function CoverageSystemAtlasPage(): JSX.Element {
  const { data: payload, error } = usePayloadFile<SystemAtlasPayload>(
    '/system_atlas_runtime_coverage/latest/operator_dashboard_payload.json',
    30_000,
  );
  const { data: gapPayload } = usePayloadFile<SystemAtlasGapRemediationPayload>(
    '/system_atlas_gap_remediation/latest/operator_dashboard_payload.json',
    30_000,
  );

  return (
    <article className="enterprise-cockpit-page" data-testid="page-coverage-system-atlas" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Coverage System Atlas</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
      </header>
      {!payload ? (
        <p className="cockpit-evidence-gap">{error ?? 'Connecting system atlas evidence stream...'}</p>
      ) : (
        <>
          <Panel id="system-atlas-summary" title="System Atlas Runtime Coverage Gate">
            <div className="cockpit-analytics-grid">
              <Metric label="GO/NO-GO" value={payload.go_no_go} />
              <Metric label="Files" value={payload.counts.files} />
              <Metric label="Scripts" value={payload.counts.scripts} />
              <Metric label="Unsafe unknown" value={payload.counts.unsafe_unknown} />
              <Metric label="Exchange action paths" value={payload.counts.unmapped_exchange_action_paths} />
              <Metric label="Redis writer paths" value={payload.counts.redis_writer_paths} />
              <Metric label="Runtime unmapped" value={payload.counts.unmapped_runtime_processes} />
              <Metric label="12h monitor" value={payload.runtime_monitor.status} />
            </div>
            <div className="cockpit-card-grid">
              {payload.top_gaps.slice(0, 24).map((gap) => (
                <div className="cockpit-evidence-gap" key={gap}>{gap}</div>
              ))}
            </div>
          </Panel>
          <SystemAtlasGapRemediationPanel payload={gapPayload} />
        </>
      )}
    </article>
  );
}
