import { Link } from 'react-router-dom';
import { Metric, Panel } from '../cockpitComponents';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload, useTonightReadinessPayload } from '../operatorTruthData';
import { valueText } from '../cockpitData';

function PublicKpi({ label, value, detail }: { label: string; value: unknown; detail: string }): JSX.Element {
  return (
    <div className="public-kpi">
      <span>{label}</span>
      <strong>{valueText(value)}</strong>
      <small>{detail}</small>
    </div>
  );
}

export default function PublicLandingPage(): JSX.Element {
  const { payload: truthPayload } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  const { payload: tonightReadiness } = useTonightReadinessPayload();
  const lineageIds = paperRuntime?.current_signal_lineage?.lineage_ids as Record<string, unknown> | undefined;
  const currentRisk = paperRuntime?.current_risk_decision as Record<string, unknown> | undefined;
  const routeScore = tonightReadiness
    ? `${(tonightReadiness.public_route_failed_count ?? 0) === 0 ? 'all public routes passing' : `${tonightReadiness.public_route_failed_count} public route issues`}`
    : 'route crawl loading';

  return (
    <article className="production-public-page grid-bg" data-testid="page-public-landing" data-page-id="public-landing">
      <section className="public-hero panel bracketed hatch">
        <span className="br-bl" aria-hidden="true" />
        <span className="br-br" aria-hidden="true" />
        <div className="public-hero__copy">
          <p className="eyebrow">Paper-shadow trading operations / public entry</p>
          <h1>AI BOT V2 Shadow Desk</h1>
          <p>
            A production-style operator website for observing the running legacy system, mirroring signals into V2 paper/shadow,
            and preparing canary preflight without enabling live execution.
          </p>
          <div className="public-hero__actions">
            <Link className="operator-detail-link" to="/admin/mission-control?role=admin">
              <strong>Open Mission Control</strong>
              <span>Current paper runtime, legacy bridge, risk, and blockers.</span>
            </Link>
            <Link className="operator-detail-link" to="/status">
              <strong>Public Status</strong>
              <span>High-level readiness and route health.</span>
            </Link>
          </div>
        </div>
        <div className="public-hero__metrics">
          <PublicKpi label="Live gate" value={truthPayload?.live_gate_status ?? 'blocked_human_only'} detail="No live/capital action is exposed." />
          <PublicKpi label="Paper runtime" value={paperRuntime?.runtime_state ?? 'loading current payload'} detail={`Last tick ${paperRuntime?.paper_loop?.last_tick_at ?? 'loading'}`} />
          <PublicKpi label="Legacy bridge" value={tonightReadiness?.legacy_bridge_status ?? 'loading'} detail="Read-only observer into V2 shadow twin." />
          <PublicKpi label="Public routes" value={routeScore} detail="Screenshots and crawl reports are archived." />
        </div>
      </section>

      <section className="public-market-strip" aria-label="Current paper market state">
        <Metric label="BTCUSDT price" value={paperRuntime?.market_feed?.price ?? 'loading'} detail={paperRuntime?.market_feed?.source_type ?? 'READONLY_MARKET_FEED'} />
        <Metric label="prediction_id" value={lineageIds?.prediction_id ?? 'loading'} />
        <Metric label="signal_id" value={lineageIds?.signal_id ?? 'loading'} />
        <Metric label="risk result" value={currentRisk?.risk_result ?? 'loading'} />
        <Metric label="paper equity" value={paperRuntime?.paper_account?.equity ?? 'loading'} />
      </section>

      <Panel id="public-workflow" title="Current Operating Workflow" right={<span className="chip solid-block">Live blocked</span>}>
        <div className="public-feature-grid">
          <div className="public-feature-card">
            <h3>Legacy Observer</h3>
            <p>Legacy runtime is observed through read-only evidence. V2 writes only to V2-owned public/runtime artifacts.</p>
            <span>Source: LEGACY_READONLY_BRIDGE</span>
          </div>
          <div className="public-feature-card">
            <h3>Paper / Shadow Twin</h3>
            <p>Current V2 paper runtime carries prediction, feature snapshot, signal, orchestrator, risk, and paper ledger records.</p>
            <span>Source: REALTIME_RUNTIME_EVIDENCE</span>
          </div>
          <div className="public-feature-card">
            <h3>Risk Gateway</h3>
            <p>Risk Gateway remains final authority. Canary is prepared as a packet only and still requires human approval.</p>
            <span>Source: LIVE_LIKE_RISK_PROFILE</span>
          </div>
        </div>
      </Panel>
    </article>
  );
}
