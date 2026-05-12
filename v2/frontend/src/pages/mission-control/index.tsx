import meta from './meta';
import rbac from './rbac';
import route from './route';
import type { PageMeta } from '../../types/page';
import { AutonomousGovernorPanel, ChartPanel, CockpitLoading, ConfigTable, DecisionDrawers, ExchangeManager, FreshnessBadge, MarketPulse, MonitorTable, Panel, Phase3cRuntimeMonitorPanel, QuarantinePanel, RedisExportCapacityPanel, RedisFullExportPanel, RedisHumanApprovalPanel, RedisMemoryPressurePanel, RedisSafeTrimPacketPanel, SafetyTopBar, SystemAtlasGapRemediationPanel, SystemAtlasPanel } from '../cockpitComponents';
import type { AutonomousGovernorPayload, CockpitPayload } from '../cockpitData';
import { statusClass, useCockpitPayload, valueText } from '../cockpitData';
import { MissionControlReadinessBanner } from '../../components/banners/MissionControlReadinessBanner';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload, type PaperOnlineRuntimePayload } from '../operatorTruthData';
import { ActualRuntimeNowPanel, LegacyRuntimeMonitorPanel, MissingEvidencePanel, OperatorTruthCommandDeck, OperatorTruthLoading, PaperOnlineRuntimeStatusPanel, PayloadFreshnessPanel, RuntimeTruthMatrix, SignalLineageTruthPanel, TrainerPredictionTruthPanel, WhatIsWorkingPanel } from '../operatorTruthComponents';

const EVIDENCE_MISSING = 'Evidence missing - cannot explain without guessing.';

export default function MissionControlPage(): JSX.Element {
  const { payload, quarantine, systemAtlas, systemAtlasGapRemediation, phase3cRuntimeMonitor, redisMemoryPressure, redisHumanApproval, redisExportCapacity, redisFullExport, redisSafeTrimPacket, autonomousGovernor, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();

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
      {truthPayload ? <OperatorTruthCommandDeck payload={truthPayload} /> : <OperatorTruthLoading error={truthError} />}
      {truthPayload ? <ActualRuntimeNowPanel payload={truthPayload} /> : null}
      {truthPayload ? <RuntimeTruthMatrix payload={truthPayload} /> : null}
      <PaperOnlineRuntimeStatusPanel payload={paperRuntime} />
      {truthPayload ? <MissionCriticalSystemsGrid payload={payload} truthPayload={truthPayload} paperRuntime={paperRuntime} /> : null}
      <OperatorDetailLinksPanel />
      <div className="mission-command-layout">
        <div className="mission-command-main">
          <ChartPanel candles={payload.candles} decisions={payload.decisions} sourceType={marketFeedSource} />
          {truthPayload ? <SignalRuntimeStatusPanel truthPayload={truthPayload} /> : null}
        </div>
        <aside className="mission-command-side">
          {truthPayload ? <RiskGatewayRuntimePanel truthPayload={truthPayload} /> : null}
          <MonitorTable rows={payload.monitors} />
        </aside>
      </div>
      <Panel id="mission-control-proof-offload" title="Proof Archive Offloaded" right={<span className="chip solid-paper">Not primary workflow</span>}>
        <p className="cockpit-evidence-note">
          Historical proofs, Redis remediation packets, system atlas inventories, and static decision examples are no longer rendered on the Mission Control first screen. Use Operator Proof Dashboard, Build/Validation, System Atlas, Risk Control, and Signal Explainability for archive detail.
        </p>
      </Panel>
      <footer className="modern-dashboard-marker" data-testid="modern-dashboard-loaded">
        AI BOT V2 Modern Dashboard Loaded
      </footer>
    </article>
  );
}

function OperatorDetailLinksPanel(): JSX.Element {
  const links = [
    ['/admin/monitor-center?role=admin', 'Monitor Center', 'Scripts, monitors, process watchers, and freshness evidence.'],
    ['/admin/trainer-prediction-monitor?role=admin', 'Trainer Monitor', 'Current trainer runtime evidence first; fixtures collapsed.'],
    ['/admin/signal-explainability?role=admin', 'Signal Explainability', 'Current lineage, missing evidence, and no-guessing status.'],
    ['/admin/build-validation-status?role=admin', 'Build Validation', 'GO/NO-GO markers, stale payloads, and proof freshness.'],
    ['/admin/operator-proof-dashboard?role=admin', 'Proof Dashboard', 'Historical and static proof artifacts only.'],
    ['/admin/risk-control?role=admin', 'Risk Control', 'Risk Gateway authority and fail-closed blockers.'],
  ] satisfies Array<[string, string, string]>;
  return (
    <Panel id="operator-detail-links" title="Detail Pages">
      <div className="operator-detail-links">
        {links.map(([href, label, detail]) => (
          <a href={href} key={href} className="operator-detail-link">
            <strong>{label}</strong>
            <span>{detail}</span>
          </a>
        ))}
      </div>
    </Panel>
  );
}

function MissionCriticalSystemsGrid({ payload, truthPayload, paperRuntime }: { payload: CockpitPayload; truthPayload: NonNullable<ReturnType<typeof useOperatorTruthPayload>['payload']>; paperRuntime: PaperOnlineRuntimePayload | null }): JSX.Element {
  const decision = payload.decisions[0];
  const cards = [
    {
      label: 'Paper / shadow equity',
      value: paperRuntime?.paper_account?.equity ?? payload.account_mode,
      detail: paperRuntime
        ? `Runtime ${paperRuntime.runtime_state}; last tick ${paperRuntime.paper_loop.last_tick_at}; no exchange execution.`
        : 'No live exchange execution. Paper/shadow state is missing until V2 paper online runtime is started.',
      source: paperRuntime ? 'REALTIME_RUNTIME_EVIDENCE / V2_PAPER_RUNTIME' : 'MISSING_EVIDENCE',
    },
    {
      label: 'Trainer state',
      value: truthPayload.trainer_monitor_status.status,
      detail: 'Current trainer runtime evidence must exist before predictions are treated as current.',
      source: 'REALTIME_RUNTIME_EVIDENCE',
    },
    {
      label: 'Orchestrator',
      value: truthPayload.runtime_monitor_status.orchestrator_status,
      detail: 'Observed read-only process evidence only; orchestrator cannot approve execution.',
      source: 'READONLY_PROCESS_LIST',
    },
    {
      label: 'Risk Gateway',
      value: decision?.risk_reason ?? 'MISSING_EVIDENCE',
      detail: `risk_decision_id: ${valueText(decision?.risk_decision_id)}`,
      source: 'V2_PROOF_ARTIFACT',
    },
    {
      label: 'Execution / paper',
      value: paperRuntime?.runtime_state ?? truthPayload.runtime_monitor_status.paper_online_runtime_status?.status ?? 'PAPER_ONLINE_RUNTIME_MISSING',
      detail: paperRuntime
        ? `${paperRuntime.last_paper_event.paper_action}; risk ${paperRuntime.last_paper_event.risk_gateway_result}`
        : 'Current paper runtime must be fresh before this supports paper readiness.',
      source: paperRuntime ? 'REALTIME_RUNTIME_EVIDENCE' : 'MISSING_EVIDENCE',
    },
    {
      label: 'Redis / V2 data plane',
      value: truthPayload.redis_trim_status,
      detail: 'Legacy trim remains deferred; V2 bounded data plane remains the safer strategic path.',
      source: 'RUNTIME_MONITOR_PAYLOAD',
    },
    {
      label: 'Postgres / audit ledger',
      value: payload.proof_freshness.some((row) => row.artifact.toLowerCase().includes('audit')) ? 'V2_PROOF_ARTIFACT' : 'MISSING_EVIDENCE',
      detail: 'Audit durability must be proven before live readiness.',
      source: 'V2_PROOF_ARTIFACT',
    },
    {
      label: 'Kill switch / live block',
      value: payload.live_gate_status,
      detail: 'Final live/capital approval is human-only.',
      source: 'LIVE_GATE_POLICY',
    },
  ];
  return (
    <section className="mission-critical-grid" aria-label="Primary cockpit system cards">
      {cards.map((card) => (
        <div className="mission-critical-card" key={card.label}>
          <span>{card.label}</span>
          <strong className={statusClass(card.value)}>{valueText(card.value)}</strong>
          <p>{card.detail}</p>
          <small>{card.source}</small>
        </div>
      ))}
    </section>
  );
}

function RiskGatewayRuntimePanel({ truthPayload }: { truthPayload: NonNullable<ReturnType<typeof useOperatorTruthPayload>['payload']> }): JSX.Element {
  return (
    <Panel id="risk-gateway-runtime" title="Risk Gateway Runtime Boundary" right={<span className="chip solid-block">Fail-closed</span>}>
      <div className="cockpit-lineage-grid">
        <div><span>Final authority</span><strong>Risk Gateway</strong></div>
        <div><span>Live gate</span><strong>{truthPayload.live_gate_status}</strong></div>
        <div><span>Current signal lineage</span><strong>{truthPayload.signal_lineage_status.status}</strong></div>
        <div><span>Current task</span><strong>{truthPayload.supervisor_status.current_running_task ?? 'none'}</strong></div>
        <div><span>Next task</span><strong>{truthPayload.current_next_task ?? 'MISSING_EVIDENCE'}</strong></div>
        <div><span>Missing evidence</span><strong>{truthPayload.missing_evidence.length}</strong></div>
      </div>
      <p className="cockpit-evidence-note">
        Orchestrator may propose, enrich, and deconflict. Risk Gateway remains final authority before any execution intent. No historical proof IDs are shown as current runtime decisions on Mission Control.
      </p>
    </Panel>
  );
}

function SignalRuntimeStatusPanel({ truthPayload }: { truthPayload: NonNullable<ReturnType<typeof useOperatorTruthPayload>['payload']> }): JSX.Element {
  const signal = truthPayload.signal_lineage_status;
  const isRealtime = signal.status === 'REALTIME_RUNTIME_EVIDENCE';
  const latest = isRealtime ? signal.latest_signal : null;
  return (
    <Panel
      id="current-signal-runtime"
      title="Current Signal Runtime"
      right={<span className={isRealtime ? 'chip solid-ok' : 'chip solid-warn'}>{isRealtime ? 'REALTIME_RUNTIME_EVIDENCE' : 'CURRENT_SIGNAL_LINEAGE_MISSING'}</span>}
    >
      {latest ? (
        <div className="cockpit-lineage-grid">
          <div><span>signal_id</span><strong>{valueText(latest.signal_id)}</strong></div>
          <div><span>prediction_id</span><strong>{valueText(latest.prediction_id)}</strong></div>
          <div><span>feature_snapshot_id</span><strong>{valueText(latest.feature_snapshot_id)}</strong></div>
          <div><span>orchestrator_decision_id</span><strong>{valueText(latest.orchestrator_decision_id)}</strong></div>
          <div><span>risk_decision_id</span><strong>{valueText(latest.risk_decision_id)}</strong></div>
          <div><span>execution_intent_id</span><strong>{valueText(latest.execution_intent_id)}</strong></div>
        </div>
      ) : (
        <div className="cockpit-evidence-gap">
          <strong>CURRENT_SIGNAL_LINEAGE_MISSING</strong>
          <p>Evidence missing — cannot explain without guessing. Historical proof rows are kept in Signal Explainability and Operator Proof Dashboard, not as the current stream.</p>
        </div>
      )}
    </Panel>
  );
}

function SignalStreamCompactPanel({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <Panel id="signal-stream-current-proof" title="Signal Stream - Current Truth View" right={<span className="chip solid-warn">Fixture rows are not live runtime</span>}>
      <div className="signal-stream-table" role="table" aria-label="Compact signal stream">
        <div className="signal-stream-row signal-stream-row--head" role="row">
          <span>Signal</span><span>Prediction</span><span>Symbol</span><span>Action</span><span>Confidence</span><span>Freshness</span><span>Risk</span><span>Flags</span>
        </div>
        {payload.decisions.slice(0, 5).map((row) => (
          <div className="signal-stream-row" role="row" key={row.id}>
            <span>{valueText(row.signal_id)}</span>
            <span>{valueText(row.prediction_id)}</span>
            <span>{row.symbol}</span>
            <span>{row.result}</span>
            <span>{row.confidence_raw} / {row.confidence_calibrated}</span>
            <span>{valueText(row.source_freshness_by_ingestor)}</span>
            <span className={statusClass(row.risk_reason)}>{row.risk_reason}</span>
            <span>{[...row.stale_flags, ...row.missing_flags].join(', ') || 'none'}</span>
          </div>
        ))}
      </div>
      <p className="cockpit-evidence-note">Rows are V2 proof artifacts unless the operator truth payload marks current runtime lineage as realtime.</p>
    </Panel>
  );
}

function MissionCommandHero({ payload, marketFeedSource, truthPayloadReady }: { payload: CockpitPayload; marketFeedSource?: string; truthPayloadReady: boolean }): JSX.Element {
  const marketFeed = payload.analytics_cards.find((card) => card.label === 'Market Feed');
  const blockerCount = payload.blockers.length + payload.evidence_gaps.length;
  return (
    <header className="mission-command-hero panel bracketed hatch" data-testid="mission-command-hero">
      <span className="br-bl" aria-hidden="true" />
      <span className="br-br" aria-hidden="true" />
      <div className="mission-command-hero__copy">
        <p className="eyebrow">AI BOT V2 verified market context</p>
        <h1>Market, Chart, And V2 Proof Context</h1>
        <p>{meta.description} This section remains a proof and market context surface; the truth deck above is the current operator source of truth.</p>
        <div className="mission-command-hero__chips" aria-label="Mission Control source and safety state">
          <span className="chip solid-block">LIVE TRADING: {payload.live_gate_status}</span>
          <span className="chip solid-paper">Operator route: /admin/mission-control</span>
          <span className="chip">Chart source: {valueText(marketFeedSource ?? 'MISSING')}</span>
          <span className={truthPayloadReady ? 'chip solid-ok' : 'chip solid-warn'}>Operator truth payload: {truthPayloadReady ? 'loaded' : 'missing'}</span>
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
