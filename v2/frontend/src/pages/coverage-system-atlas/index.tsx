import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useEffect, useState } from 'react';
import { Metric, Panel } from '../cockpitComponents';
import type { SystemAtlasPayload } from '../cockpitData';

export default function CoverageSystemAtlasPage(): JSX.Element {
  const [payload, setPayload] = useState<SystemAtlasPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch('/system_atlas_runtime_coverage/latest/operator_dashboard_payload.json', { cache: 'no-store' })
      .then((res) => {
        if (!res.ok) throw new Error(`system atlas payload ${res.status}`);
        return res.json() as Promise<SystemAtlasPayload>;
      })
      .then((next) => {
        if (active) setPayload(next);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'system atlas payload unavailable');
      });
    return () => {
      active = false;
    };
  }, []);

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
        <p className="cockpit-evidence-gap">{error ?? 'Loading system atlas evidence...'}</p>
      ) : (
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
      )}
    </article>
  );
}
