import meta from './meta';
import rbac from './rbac';
import route from './route';
import type { PageMeta } from '../../types/page';
import { AutonomousGovernorPanel, ChartPanel, CockpitLoading, ConfigTable, DecisionDrawers, ExchangeManager, FreshnessBadge, MarketPulse, MonitorTable, Panel, Phase3cRuntimeMonitorPanel, QuarantinePanel, RedisExportCapacityPanel, RedisFullExportPanel, RedisHumanApprovalPanel, RedisMemoryPressurePanel, RedisSafeTrimPacketPanel, SafetyTopBar, SystemAtlasGapRemediationPanel, SystemAtlasPanel } from '../cockpitComponents';
import type { AutonomousGovernorPayload, CockpitPayload } from '../cockpitData';
import { statusClass, useCockpitPayload, valueText } from '../cockpitData';
import { MissionControlReadinessBanner } from '../../components/banners/MissionControlReadinessBanner';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { LegacyRuntimeMonitorPanel, MissingEvidencePanel, OperatorTruthLoading, PayloadFreshnessPanel, SignalLineageTruthPanel, TrainerPredictionTruthPanel, TruthStatusStrip, WhatIsWorkingPanel } from '../operatorTruthComponents';

const EVIDENCE_MISSING = 'Evidence missing - cannot explain without guessing.';

export default function MissionControlPage(): JSX.Element {
  const { payload, quarantine, systemAtlas, systemAtlasGapRemediation, phase3cRuntimeMonitor, redisMemoryPressure, redisHumanApproval, redisExportCapacity, redisFullExport, redisSafeTrimPacket, autonomousGovernor, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();

  if (!payload) {
    return (
      <article className="enterprise-cockpit-page" data-testid="page-mission-control" data-page-id={(meta as PageMeta).id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
        <MissionControlReadinessBanner />
        <CockpitLoading error={error} />
      </article>
    );
  }
  const marketFeedSource = payload.analytics_cards.find((card) => card.label === 'Market Feed')?.value;

  return (
    <article className="enterprise-cockpit-page mission-control-design-page grid-bg" data-testid="page-mission-control" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}>
      <MissionControlReadinessBanner />
      {truthPayload ? <TruthStatusStrip payload={truthPayload} /> : <OperatorTruthLoading error={truthError} />}
      <MissionCommandHero payload={payload} marketFeedSource={marketFeedSource} />
      {truthPayload ? (
        <section className="mission-system-grid" aria-label="Current operator truth and runtime evidence">
          <LegacyRuntimeMonitorPanel payload={truthPayload} />
          <TrainerPredictionTruthPanel payload={truthPayload} />
          <SignalLineageTruthPanel payload={truthPayload} />
        </section>
      ) : null}
      {truthPayload ? <WhatIsWorkingPanel payload={truthPayload} /> : null}
      <SafetyTopBar payload={payload} />
      <SubsystemStrip payload={payload} autonomousGovernor={autonomousGovernor} marketFeedSource={marketFeedSource} />
      <div className="mission-command-layout">
        <div className="mission-command-main">
          <ChartPanel candles={payload.candles} decisions={payload.decisions} sourceType={marketFeedSource} />
          <DecisionDrawers rows={payload.decisions} />
          <MarketPulse payload={payload} />
        </div>
        <aside className="mission-command-side">
          <RiskBoundaryPanel payload={payload} />
          <AutonomousGovernorPanel payload={autonomousGovernor} />
          <MonitorTable rows={payload.monitors} />
        </aside>
      </div>
      <section className="mission-system-grid" aria-label="V2 online-readiness evidence surfaces">
        <div className="mission-system-column">
          <ConfigTable rows={payload.settings} />
          <ExchangeManager rows={payload.exchanges} />
          <Phase3cRuntimeMonitorPanel payload={phase3cRuntimeMonitor} />
        </div>
        <div className="mission-system-column">
          <QuarantinePanel payload={quarantine} />
          <SystemAtlasPanel payload={systemAtlas} />
          <SystemAtlasGapRemediationPanel payload={systemAtlasGapRemediation} />
        </div>
        <div className="mission-system-column">
          <RedisMemoryPressurePanel payload={redisMemoryPressure} />
          <RedisHumanApprovalPanel payload={redisHumanApproval} />
          <RedisExportCapacityPanel payload={redisExportCapacity} />
          <RedisFullExportPanel payload={redisFullExport} />
          <RedisSafeTrimPacketPanel payload={redisSafeTrimPacket} />
        </div>
      </section>
      {truthPayload ? <PayloadFreshnessPanel payload={truthPayload} /> : null}
      {truthPayload ? <MissingEvidencePanel payload={truthPayload} /> : null}
      <FreshnessAndBlockersPanel payload={payload} />
      <footer className="modern-dashboard-marker" data-testid="modern-dashboard-loaded">
        AI BOT V2 Modern Dashboard Loaded
      </footer>
    </article>
  );
}

function MissionCommandHero({ payload, marketFeedSource }: { payload: CockpitPayload; marketFeedSource?: string }): JSX.Element {
  const marketFeed = payload.analytics_cards.find((card) => card.label === 'Market Feed');
  const blockerCount = payload.blockers.length + payload.evidence_gaps.length;
  return (
    <header className="mission-command-hero panel bracketed hatch" data-testid="mission-command-hero">
      <span className="br-bl" aria-hidden="true" />
      <span className="br-br" aria-hidden="true" />
      <div className="mission-command-hero__copy">
        <p className="eyebrow">AI BOT V2 Mission Control</p>
        <h1>{meta.title}</h1>
        <p>{meta.description}</p>
        <div className="mission-command-hero__chips" aria-label="Mission Control source and safety state">
          <span className="chip solid-block">LIVE TRADING: {payload.live_gate_status}</span>
          <span className="chip solid-paper">Operator route: /admin/mission-control</span>
          <span className="chip">Chart source: {valueText(marketFeedSource ?? 'MISSING')}</span>
        </div>
      </div>
      <div className="mission-command-stats" aria-label="Mission Control live-readiness summary">
        <HeroStat label="Account mode" value={payload.account_mode} />
        <HeroStat label="Selected symbol" value={payload.selected_symbol} />
        <HeroStat label="Market feed" value={marketFeed?.value ?? 'MISSING'} detail={marketFeed?.detail ?? EVIDENCE_MISSING} />
        <HeroStat label="Blockers / gaps" value={blockerCount ? String(blockerCount) : '0'} detail={blockerCount ? 'Requires evidence remediation' : 'No listed readiness gaps'} />
      </div>
    </header>
  );
}

function HeroStat({ label, value, detail }: { label: string; value: unknown; detail?: string }): JSX.Element {
  return (
    <div className="mission-command-stat">
      <span className="label-mono">{label}</span>
      <strong className={statusClass(value)}>{valueText(value)}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function SubsystemStrip({ payload, autonomousGovernor, marketFeedSource }: { payload: CockpitPayload; autonomousGovernor: AutonomousGovernorPayload | null; marketFeedSource?: string }): JSX.Element {
  const firstDecision = payload.decisions[0];
  const marketFeed = payload.analytics_cards.find((card) => card.label === 'Market Feed');
  const codexStatus = autonomousGovernor?.codex_auto_governor_working
    ? 'CODEX_AUTO_GOVERNOR_WORKING'
    : autonomousGovernor?.go_no_go ?? 'MISSING';
  const items = [
    {
      label: 'Market feed',
      value: marketFeedSource ?? marketFeed?.value ?? 'MISSING',
      detail: marketFeed?.detail ?? EVIDENCE_MISSING,
      tone: marketFeedSource === 'READONLY_MARKET_FEED' ? 'ok' : 'warn',
    },
    {
      label: 'Orchestrator',
      value: firstDecision?.orchestrator_decision_id ?? 'MISSING',
      detail: firstDecision?.orchestrator_reason ?? EVIDENCE_MISSING,
      tone: firstDecision?.orchestrator_decision_id ? 'paper' : 'warn',
    },
    {
      label: 'Risk Gateway',
      value: firstDecision?.risk_decision_id ?? payload.live_gate_status,
      detail: 'Final authority before execution intent.',
      tone: 'block',
    },
    {
      label: 'Execution',
      value: firstDecision?.execution_intent_id ?? 'LIVE BLOCKED',
      detail: firstDecision?.result ?? 'Trader executes only approved non-live intents.',
      tone: 'block',
    },
    {
      label: 'Monitor Center',
      value: `${payload.monitors.length} monitor rows`,
      detail: 'Runtime evidence is read-only and surfaced below.',
      tone: payload.monitors.length ? 'ok' : 'warn',
    },
    {
      label: 'Codex review',
      value: codexStatus,
      detail: 'Parallel auditor; cannot approve live capital.',
      tone: 'paper',
    },
  ];

  return (
    <section className="mission-subsystem-strip" aria-label="Primary V2 subsystem status">
      {items.map((item) => (
        <div className="mission-subsystem-card panel bracketed" key={item.label}>
          <span className="br-bl" aria-hidden="true" />
          <span className="br-br" aria-hidden="true" />
          <span className="mission-subsystem-card__label">
            <span className={`dot ${item.tone} ${item.tone === 'block' ? 'pulse' : ''}`} aria-hidden="true" />
            {item.label}
          </span>
          <strong className={statusClass(item.value)}>{valueText(item.value)}</strong>
          <small>{item.detail}</small>
        </div>
      ))}
    </section>
  );
}

function RiskBoundaryPanel({ payload }: { payload: CockpitPayload }): JSX.Element {
  const firstDecision = payload.decisions[0];
  return (
    <Panel
      id="orchestrator-risk-boundary"
      title="Orchestrator -> Risk Gateway Boundary"
      right={<span className="chip solid-block">Risk final authority</span>}
    >
      <div className="mission-boundary-flow" aria-label="Decision authority chain">
        <span>Trainer/model proposal</span>
        <span>Orchestrator enriches/ranks</span>
        <span>Risk Gateway approves or blocks</span>
        <span>Execution intent only after approval</span>
        <span>Audit ledger records chain</span>
      </div>
      {firstDecision ? (
        <div className="cockpit-lineage-grid">
          {([
            ['prediction_id', firstDecision.prediction_id],
            ['signal_id', firstDecision.signal_id],
            ['orchestrator_decision_id', firstDecision.orchestrator_decision_id],
            ['risk_decision_id', firstDecision.risk_decision_id],
            ['execution_intent_id', firstDecision.execution_intent_id],
            ['risk result', firstDecision.risk_reason],
          ] satisfies Array<[string, unknown]>).map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{valueText(value)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="cockpit-evidence-gap">Decision chain sample missing. {EVIDENCE_MISSING}</p>
      )}
      <p className="cockpit-evidence-note">
        V2_PROOF_ARTIFACT / RUNTIME_MONITOR_PAYLOAD: the orchestrator can propose, coordinate, enrich, and deconflict. It cannot bypass Risk Gateway approval or enable live execution.
      </p>
    </Panel>
  );
}

function FreshnessAndBlockersPanel({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
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
        {payload.evidence_gaps.length === 0 ? (
          <div className="cockpit-evidence-gap">No Mission Control evidence gaps listed in the cockpit payload.</div>
        ) : null}
      </div>
      <div className="mission-source-contract">
        {payload.analytics_cards.map((card) => (
          <span key={card.label}>
            {card.label}: <FreshnessBadge freshness={card.freshness} />
          </span>
        ))}
      </div>
    </Panel>
  );
}
