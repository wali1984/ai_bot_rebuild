import meta from './meta';
import rbac from './rbac';
import route from './route';
import type { PageMeta } from '../../types/page';
import { ChartPanel, CockpitLoading, ConfigTable, DecisionDrawers, ExchangeManager, MarketPulse, MonitorTable, Panel, QuarantinePanel, SafetyTopBar, SystemAtlasPanel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';

export default function MissionControlPage(): JSX.Element {
  const { payload, quarantine, systemAtlas, error } = useCockpitPayload();

  if (!payload) {
    return (
      <article className="enterprise-cockpit-page" data-testid="page-mission-control" data-page-id={(meta as PageMeta).id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
        <CockpitLoading error={error} />
      </article>
    );
  }
  const marketFeedSource = payload.analytics_cards.find((card) => card.label === 'Market Feed')?.value;

  return (
    <article className="enterprise-cockpit-page" data-testid="page-mission-control" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">AI BOT V2 Mission Control</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="cockpit-live-block">LIVE TRADING: {payload.live_gate_status}</div>
      </header>
      <SafetyTopBar payload={payload} />
      <div className="enterprise-cockpit-grid">
        <div className="enterprise-cockpit-main">
          <ChartPanel candles={payload.candles} decisions={payload.decisions} sourceType={marketFeedSource} />
          <MarketPulse payload={payload} />
          <DecisionDrawers rows={payload.decisions} />
          <QuarantinePanel payload={quarantine} />
          <SystemAtlasPanel payload={systemAtlas} />
          <Panel id="freshness-and-live-readiness-blockers" title="Freshness, Sync, And Live-Readiness Blockers">
            <div className="cockpit-card-grid">
              {payload.proof_freshness.map((row) => (
                <div className="cockpit-exchange-card" key={row.artifact}>
                  <h3>{row.artifact}</h3>
                  <p>Source generated: {row.source_generated_at}</p>
                  <p>Public copied: {row.public_copied_at}</p>
                  <strong>{row.state}</strong>
                </div>
              ))}
              {payload.blockers.map((row) => (
                <div className="cockpit-exchange-card" key={row.id}>
                  <h3>{row.id}</h3>
                  <strong>{row.status}</strong>
                  <p>{row.detail}</p>
                </div>
              ))}
              {payload.evidence_gaps.map((gap) => (
                <div className="cockpit-evidence-gap" key={gap}>{gap}</div>
              ))}
            </div>
          </Panel>
        </div>
        <aside className="enterprise-cockpit-side">
          <MonitorTable rows={payload.monitors} />
          <ConfigTable rows={payload.settings} />
          <ExchangeManager rows={payload.exchanges} />
        </aside>
      </div>
    </article>
  );
}
