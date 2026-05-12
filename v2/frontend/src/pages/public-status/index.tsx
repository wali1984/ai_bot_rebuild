import meta from './meta';
import { Metric, Panel } from '../cockpitComponents';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload, useTonightReadinessPayload } from '../operatorTruthData';

export default function PublicStatusPage(): JSX.Element {
  const { payload: truthPayload } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  const { payload: tonightReadiness } = useTonightReadinessPayload();
  const publicFailures = tonightReadiness?.public_route_failed_count ?? null;
  const statusText = publicFailures === null ? 'loading route crawl' : publicFailures === 0 ? 'public routes passing' : `${publicFailures} public route issues`;
  return (
    <article className="production-public-page grid-bg" data-testid="page-public-status" data-page-id={meta.id}>
      <header className="public-page-header panel bracketed">
        <span className="br-bl" aria-hidden="true" />
        <span className="br-br" aria-hidden="true" />
        <p className="eyebrow">Public status / non-sensitive summary</p>
        <h1>{meta.title}</h1>
        <p>High-level website and paper/shadow status. Internal IDs and live controls are not exposed on this public route.</p>
      </header>
      <section className="public-market-strip" aria-label="Public status summary">
        <Metric label="Live gate" value={truthPayload?.live_gate_status ?? 'blocked_human_only'} detail="Human-only approval required before any canary." />
        <Metric label="Paper runtime" value={paperRuntime?.runtime_state ?? 'loading'} detail={paperRuntime?.freshness?.status ?? 'current payload loading'} />
        <Metric label="Legacy bridge" value={tonightReadiness?.legacy_bridge_status ?? 'loading'} detail="Read-only observer path." />
        <Metric label="Website routes" value={statusText} detail={`${tonightReadiness?.local_route_failed_count ?? 0} local failures in latest crawl.`} />
      </section>
      <Panel id="public-status-safety" title="Public Safety Contract" right={<span className="chip solid-block">No live controls</span>}>
        <div className="public-feature-grid">
          <div className="public-feature-card">
            <h3>Execution</h3>
            <p>Public status cannot place orders, cancel orders, change leverage, alter margin mode, or enable live trading.</p>
            <span>Control surface: none</span>
          </div>
          <div className="public-feature-card">
            <h3>Data</h3>
            <p>Current paper/shadow state is derived from V2 runtime artifacts. Static proof is kept out of the status summary.</p>
            <span>Source: V2 public payloads</span>
          </div>
          <div className="public-feature-card">
            <h3>Readiness</h3>
            <p>Remaining blockers are visible in Mission Control and Live Readiness; public status stays concise.</p>
            <span>Route: /admin/live-readiness</span>
          </div>
        </div>
      </Panel>
    </article>
  );
}
