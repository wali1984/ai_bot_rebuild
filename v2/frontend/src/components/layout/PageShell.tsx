import type { PageMeta, PageRbac, PageRoute } from '../../types/page';
import { DangerousControlPanel } from '../controls/DangerousControlPanel';
import { Metric, Panel } from '../../pages/cockpitComponents';
import { valueText } from '../../pages/cockpitData';
import { useCoinankMarketIntelligencePayload, useOperatorTruthPayload, usePaperOnlineRuntimePayload, useTonightReadinessPayload } from '../../pages/operatorTruthData';
import { TradingPlatformRoutePanel } from '../../pages/tradingPlatformPanels';

interface Props {
  meta: PageMeta;
  rbac: PageRbac;
  route: PageRoute;
}

const ROUTE_PROFILES: Record<string, { source: string; status: string; next: string; data: string[] }> = {
  symbols: {
    source: 'READONLY_MARKET_FEED / symbol universe registry',
    status: 'needs current symbol universe payload',
    next: 'Wire V2 symbol universe payload with exchange/source freshness and selection status.',
    data: ['symbol', 'exchange', 'status', 'market feed freshness', 'enabled for paper/shadow'],
  },
  signals: {
    source: 'RUNTIME_MONITOR_PAYLOAD / signal lineage',
    status: 'current runtime signal lineage required',
    next: 'Connect current signal stream with prediction_id, signal_id, confidence, and risk result.',
    data: ['signal_id', 'prediction_id', 'confidence', 'feature freshness', 'risk gate result'],
  },
  executions: {
    source: 'V2_PROOF_ARTIFACT / paper execution ledger',
    status: 'paper only; live execution blocked',
    next: 'Wire current paper execution ledger and execution_intent_id evidence.',
    data: ['execution_intent_id', 'risk_decision_id', 'paper fill state', 'PnL', 'blocked live reason'],
  },
  positions: {
    source: 'READONLY_ACCOUNT_FEED / paper position payload',
    status: 'paper/read-only positions only',
    next: 'Wire paper/shadow positions and external/manual quarantine state.',
    data: ['symbol', 'side', 'size', 'source', 'quarantine status', 'live-block status'],
  },
  'strategy-admin': {
    source: 'V2 strategy registry',
    status: 'dangerous strategy toggles approval-gated',
    next: 'Expose strategy registry with validation, rollback, and approval classification.',
    data: ['strategy id', 'state', 'risk class', 'enabled for paper', 'approval requirement'],
  },
  'trainer-admin': {
    source: 'TRAINER_RUNTIME_EVIDENCE / trainer config',
    status: 'trainer runtime monitor missing until proven current',
    next: 'Run TRAINER_RUNTIME_MONITOR_REPAIR_OR_STARTUP_DECISION before treating trainer as current.',
    data: ['trainer process', 'monitor process', 'checkpoint', 'latest prediction', 'feature snapshot'],
  },
  'orchestrator-admin': {
    source: 'RUNTIME_MONITOR_PAYLOAD / orchestrator evidence',
    status: 'orchestrator proposes only',
    next: 'Wire current orchestrator decisions to Risk Gateway decision evidence.',
    data: ['decision_id', 'reason', 'deconflict status', 'risk_decision_id', 'audit event'],
  },
  'execution-admin': {
    source: 'V2 execution adapter registry',
    status: 'paper/shadow only; live methods disabled',
    next: 'Expose execution adapter status and blocked live method inventory.',
    data: ['adapter', 'mode', 'paper capability', 'live blocked method', 'approval requirement'],
  },
  'audit-ledger': {
    source: 'V2 audit ledger',
    status: 'append-only audit proof required',
    next: 'Wire durable audit ledger tail and chain integrity checks.',
    data: ['event id', 'source', 'decision_id', 'risk_decision_id', 'chain status'],
  },
  'system-health': {
    source: 'operator truth payload / monitor center',
    status: 'current/stale/conflicting surfaced',
    next: 'Keep build:operator-truth fresh and repair stale control-plane daemons separately.',
    data: ['supervisor', 'market ingest', 'feature pipeline', 'orchestrator', 'trainer'],
  },
  'codex-review-center': {
    source: 'Codex review artifacts',
    status: 'parallel auditor only',
    next: 'Wire latest Codex PASS/FAIL matrix and remediation links.',
    data: ['review id', 'result', 'blocker', 'source paths', 'next remediation'],
  },
  'ollama-local-assistant': {
    source: 'Ollama draft-only evidence helper',
    status: 'draft-only; never final truth',
    next: 'Show Ollama helper availability and verification requirements.',
    data: ['model', 'task', 'draft packet', 'Claude/Codex verification state'],
  },
  login: {
    source: 'local session role',
    status: 'local role selector only',
    next: 'Use admin role query for local development; production auth remains separate.',
    data: ['role', 'session', 'RBAC minimum', 'dangerous control visibility'],
  },
  'public-status': {
    source: 'public status summary',
    status: 'high-level only',
    next: 'Expose only non-sensitive health once production status policy exists.',
    data: ['live gate', 'frontend health', 'public uptime', 'no internal IDs'],
  },
};

export function PageShell({ meta, rbac, route }: Props): JSX.Element {
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload(15_000);
  const { payload: coinankPayload } = useCoinankMarketIntelligencePayload(15_000);
  const { payload: tonightReadiness } = useTonightReadinessPayload(15_000);
  const profile = ROUTE_PROFILES[meta.id] ?? {
    source: 'V2 runtime payload / route production contract',
    status: 'production surface with current runtime context',
    next: `Keep ${meta.title} backed by current V2 paper/shadow, operator truth, and route-specific payloads.`,
    data: ['current data', 'freshness', 'source evidence', 'missing evidence', 'next task'],
  };
  const lineage = paperRuntime?.current_signal_lineage as Record<string, unknown> | undefined;
  const lineageIds = lineage?.lineage_ids as Record<string, unknown> | undefined;
  const signal = lineage?.signal as Record<string, unknown> | undefined;
  const executionIntent = lineage?.execution_intent as Record<string, unknown> | undefined;
  const currentRisk = paperRuntime?.current_risk_decision as Record<string, unknown> | undefined;
  const trainerPrediction = paperRuntime?.trainer_prediction as Record<string, unknown> | undefined;
  const latestPaperEvent = paperRuntime?.last_paper_event as Record<string, unknown> | undefined;
  const sourceRows = [
    ['live gate', truthPayload?.live_gate_status ?? 'blocked_human_only'],
    ['supervisor', truthPayload?.supervisor_status.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_OR_LOADING'],
    ['current task', truthPayload?.supervisor_status.current_running_task ?? 'none'],
    ['next task', truthPayload?.current_next_task ?? 'MISSING_EVIDENCE'],
    ['trainer runtime', truthPayload?.trainer_monitor_status.status ?? 'MISSING_EVIDENCE'],
    ['signal lineage', truthPayload?.signal_lineage_status.status ?? 'MISSING_EVIDENCE'],
    ['paper runtime', paperRuntime?.runtime_state ?? 'loading'],
    ['public route health', tonightReadiness ? `${tonightReadiness.public_route_failed_count ?? 0} failures` : 'loading'],
  ] satisfies Array<[string, unknown]>;
  return (
    <article
      className="enterprise-cockpit-page design-page-shell grid-bg"
      data-testid={`page-${meta.id}`}
      data-page-id={meta.id}
      data-page-surface={meta.surface}
      data-page-min-role={rbac.minRole}
      data-page-path={route.path}
    >
      <header className="design-page-hero panel bracketed hatch">
        <span className="br-bl" aria-hidden="true" />
        <span className="br-br" aria-hidden="true" />
        <div className="design-page-hero__copy">
          <p className="eyebrow">{meta.navCategory ?? 'admin'} / production route</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="design-page-hero__ribbons">
          <span className="chip solid-block">LIVE TRADING: blocked_human_only</span>
          <span className="chip solid-paper">{profile.status}</span>
          <span className="chip">{profile.source}</span>
        </div>
      </header>
      <DangerousControlPanel controlIds={meta.dangerousControlIds} />
      <Panel id={`${meta.id}-production-summary`} title={`${meta.title} Production Surface`}>
        <div className="cockpit-analytics-grid">
          {sourceRows.map(([label, value]) => <Metric key={label} label={label} value={value} />)}
        </div>
        <div className="cockpit-card-grid">
          <div className="cockpit-exchange-card">
            <h3>Purpose</h3>
            <p>{meta.description}</p>
            <p>Source: {profile.source}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Next source/task needed</strong>
            <p>{profile.next}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Runtime truth rule</strong>
            <p>Current V2 paper/shadow and legacy read-only bridge data are shown first. Static proof fixtures and historical examples remain archive-only.</p>
          </div>
        </div>
      </Panel>
      <Panel id={`${meta.id}-current-runtime-snapshot`} title="Current Runtime Snapshot" right={<span className="chip solid-ok">REALTIME_RUNTIME_EVIDENCE</span>}>
        <div className="cockpit-lineage-grid">
          <div><span>live gate</span><strong>{paperRuntime?.live_gate_status ?? truthPayload?.live_gate_status ?? 'blocked_human_only'}</strong></div>
          <div><span>BTCUSDT price</span><strong>{paperRuntime?.market_feed?.price ?? 'loading'}</strong></div>
          <div><span>prediction_id</span><strong>{valueText(lineageIds?.prediction_id ?? 'loading')}</strong></div>
          <div><span>feature_snapshot_id</span><strong>{valueText(lineageIds?.feature_snapshot_id ?? 'loading')}</strong></div>
          <div><span>signal_id</span><strong>{valueText(lineageIds?.signal_id ?? 'loading')}</strong></div>
          <div><span>risk_decision_id</span><strong>{valueText(lineageIds?.risk_decision_id ?? currentRisk?.risk_decision_id ?? 'loading')}</strong></div>
          <div><span>execution_intent_id</span><strong>{valueText(lineageIds?.execution_intent_id ?? executionIntent?.execution_intent_id ?? 'loading')}</strong></div>
          <div><span>trainer state</span><strong>{valueText(trainerPrediction?.trainer_state ?? 'loading')}</strong></div>
          <div><span>signal action</span><strong>{valueText(signal?.proposed_action ?? 'loading')}</strong></div>
          <div><span>confidence</span><strong>{valueText(signal?.confidence ?? trainerPrediction?.confidence_calibrated ?? 'loading')}</strong></div>
          <div><span>risk result</span><strong>{valueText(currentRisk?.risk_result ?? 'loading')}</strong></div>
          <div><span>paper ledger event</span><strong>{valueText(latestPaperEvent?.paper_ledger_entry_id ?? latestPaperEvent?.paper_event_id ?? 'loading')}</strong></div>
          <div><span>paper action</span><strong>{valueText(latestPaperEvent?.paper_action ?? executionIntent?.intent_action ?? 'loading')}</strong></div>
          <div><span>paper equity</span><strong>{valueText(paperRuntime?.paper_account?.equity ?? 'loading')}</strong></div>
        </div>
        <p className="cockpit-evidence-note">
          Current V2 paper/shadow lineage is rendered before archive evidence. Historical proof rows and static fixtures are not current runtime truth.
        </p>
      </Panel>
      <TradingPlatformRoutePanel routeId={meta.id} paperRuntime={paperRuntime} coinankPayload={coinankPayload} truthPayload={truthPayload} />
      <Panel id={`${meta.id}-required-data`} title="Required Production Data Contract" right={<span className="chip solid-warn">No placeholder-only route</span>}>
        <div className="cockpit-card-grid">
          {profile.data.map((item) => (
            <div className="cockpit-exchange-card" key={item}>
              <h3>{item}</h3>
              <p>Displayed with current source and freshness before this page can support live-readiness decisions.</p>
            </div>
          ))}
        </div>
      </Panel>
      {truthError ? (
        <p className="cockpit-evidence-gap" role="alert">Operator truth payload unavailable: {truthError}</p>
      ) : null}
    </article>
  );
}
