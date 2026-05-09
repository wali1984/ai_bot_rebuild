import { useEffect, useMemo, useState, type ReactNode } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import type { PageMeta } from '../../types/page';

type Primitive = string | number | boolean;

interface CockpitPayload {
  generated_at: string;
  git_head: string;
  live_gate_status: string;
  status: {
    go_no_go: string;
    queue_gate: string;
    current_task: string;
    human_attention_required_count: Primitive;
    stale_running_count: Primitive;
    automation_assessment?: string;
    last_event_timestamp?: string;
    last_artifact_update?: string;
    legacy_trader_disabled_non_blocking?: boolean;
    proof_marker: string;
    historical_marker: string;
  };
  mission_control: {
    remaining_blockers: Array<{ id: string; status: string; detail: string }>;
  };
  trainer_prediction_monitor: { rows: LineageRow[] };
  signal_explainability: { rows: LineageRow[] };
  feature_attribution: { rows: FeatureRow[] };
  symbol_universe: { rows: SymbolRow[] };
  orchestrator_decisions: { rows: OrchestratorRow[] };
  risk_gateway: { rows: RiskRow[] };
  trader_fleet_paper_shadow: { paper_rows: PaperRow[]; shadow_rows: ShadowRow[] };
  monitor_center: { rows: MonitorRow[] };
  script_registry_system_atlas: { rows: Array<{ path: string; owner: string; classification: string }> };
  config_admin: { settings: SettingRow[] };
  audit_ledger: { rows: Array<{ artifact: string; exists: boolean; classification: string }> };
  replay_historical_proof: { summary?: Record<string, Primitive>; limitations?: string[] };
  live_readiness: {
    live_gate_status: string;
    approval_required: boolean;
    dangerous_controls_enabled: boolean;
    live_blockers: Array<{ id: string; status: string; detail: string }>;
  };
  automation_status: {
    stale_running_tasks: string[];
    liveness?: AutomationLiveness;
  };
  remaining_blockers_before_live: Array<{ id: string; status: string; detail: string }>;
  data_gaps: string[];
}

interface AutomationLiveness {
  marker: string;
  automation_assessment: string;
  dashboard_summary: {
    claude_planner_running: boolean;
    codex_watchdog_running: boolean;
    scheduler_running: boolean;
    current_task_id: string;
    last_event_timestamp: string;
    last_artifact_update: string;
    last_commit: string;
    stale_running_count: Primitive;
    human_attention_count: Primitive;
    legacy_trader_disabled_non_blocking: boolean;
    next_runnable_task: string;
    latest_blocker_reason: string;
  };
  task_liveness: {
    status: string;
    run_pid: Primitive;
    supervisor_task_process_present: boolean;
    claude_codex_child_present: boolean;
    warnings: string[];
  };
  legacy_trader_policy: {
    legacy_trader_status: string;
    legacy_trader_required_for_v2_build: boolean;
    legacy_trader_down_should_not_block_non_live_rebuild: boolean;
    operator_note: string;
  };
}

interface LineageRow {
  id: string;
  source: string;
  symbol: string;
  raw_source_data: string;
  feature_snapshot_id: string;
  feature_freshness: string;
  stale_flags: string[];
  missing_flags: string[];
  unused_flags: string[];
  prediction_id: string;
  old_confidence: Primitive;
  new_confidence: Primitive;
  confidence_delta: Primitive;
  confidence_calibration: string;
  model_checkpoint: string;
  top_positive_contributors: string[];
  top_negative_contributors: string[];
  source_freshness_by_ingestor: Record<string, string>;
  signal_id: string;
  orchestrator_decision: string;
  risk_gateway_decision: string;
  risk_decision_id: string;
  execution_intent_id: string;
  paper_shadow_live_blocked_action: string;
  result_pnl_attribution: string;
  evidence_links: string[];
  warnings: string[];
}

interface FeatureRow {
  id: string;
  symbol: string;
  feature_snapshot_id: string;
  freshness: string;
  positive: string[];
  negative: string[];
  stale: string[];
  missing: string[];
  unused: string[];
  source_freshness_by_ingestor: Record<string, string>;
}

interface SymbolRow {
  symbol: string;
  discovery_source: string;
  binance_evidence: string;
  coinank_evidence: string;
  coinapi_evidence: string;
  kucoin_evidence: string;
  liquidity_score: string;
  volume_score: string;
  volatility_score: string;
  open_interest_score: string;
  feature_completeness_score: string;
  risk_score: string;
  universe_state: string;
  why_state: string;
}

interface OrchestratorRow {
  decision_id: string;
  symbol: string;
  signal_id: string;
  orchestrator_decision: string;
  risk_decision_id: string;
  execution_intent_id: string;
  lineage_complete: boolean;
}

interface RiskRow {
  id: string;
  symbol: string;
  signal_reason: string;
  stale_signal_check: string;
  duplicate_signal_check: string;
  exposure_check: string;
  drawdown_check: string;
  sizing_reason: string;
  stop_policy_status: string;
  live_gate_status: string;
  final_decision: string;
  final_reason: string;
  execution_mode: string;
}

interface PaperRow {
  id: string;
  type: string;
  symbol: string;
  risk_decision_id: string;
  execution_intent_id: string;
  pnl: string;
  mode: string;
  live_gate_status: string;
}

interface ShadowRow {
  id: string;
  symbol: string;
  legacy_action: string;
  v2_action: string;
  diverged: boolean;
  reason: string;
}

interface MonitorRow {
  id: string;
  script_path: string;
  owner: string;
  status: string;
  last_run: string;
  last_success: string;
  last_failure: string;
  metrics_emitted: string[];
  redis_keys_watched: string[];
  logs_watched: string[];
  processes_watched: string[];
  alerts: string[];
  classification: string;
}

interface SettingRow {
  name: string;
  value: string;
  classification: string;
}

const cockpitPath = '/operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json';

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

function statusClass(value: Primitive): string {
  const normalized = String(value).toLowerCase();
  if (normalized.includes('ready') || normalized.includes('pass') || normalized === 'allow' || normalized === 'true') return 'proof-pill proof-pill--ok';
  if (normalized.includes('deny') || normalized.includes('block') || normalized.includes('missing') || normalized.includes('stale')) return 'proof-pill proof-pill--blocked';
  return 'proof-pill';
}

function valueText(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  if (value === undefined || value === '') return 'evidence_missing';
  if (typeof value === 'object' && value !== null) return JSON.stringify(value);
  return String(value);
}

function TopStatusBar({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <section className="operator-topbar" data-testid="operator-top-status-bar">
      <div>
        <span>Generated</span>
        <strong>{payload.generated_at}</strong>
      </div>
      <div>
        <span>Git</span>
        <strong>{payload.git_head}</strong>
      </div>
      <div>
        <span>Queue</span>
        <strong>{payload.status.queue_gate}</strong>
      </div>
      <div>
        <span>Current Task</span>
        <strong>{payload.status.current_task}</strong>
      </div>
      <div>
        <span>Live Gate</span>
        <strong className="proof-pill proof-pill--blocked">{payload.live_gate_status}</strong>
      </div>
    </section>
  );
}

function SidebarNav(): JSX.Element {
  const sections = [
    'Mission Control',
    'Monitor Center',
    'System Atlas',
    'Trainer Prediction Monitor',
    'Signal Explainability',
    'Feature Attribution',
    'Symbol Universe',
    'Orchestrator Decisions',
    'Risk Gateway',
    'Trader Fleet',
    'Config Admin',
    'Audit Ledger',
    'Replay / Historical Proof',
    'Live Readiness',
    'Automation Status',
    'Remaining Blockers',
  ];
  return (
    <aside className="operator-cockpit-sidebar" aria-label="Operator cockpit sections">
      {sections.map((section) => (
        <a href={`#${section.toLowerCase().replaceAll(' ', '-').replace('/', '')}`} key={section}>
          {section}
        </a>
      ))}
    </aside>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="operator-cockpit-section" id={id} data-testid={`cockpit-${id}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: Primitive; detail?: string }): JSX.Element {
  return (
    <div className="operator-proof-metric">
      <span>{label}</span>
      <strong>{valueText(value)}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function MissionControl({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <Section id="mission-control" title="Mission Control">
      <div className="operator-proof-grid">
        <Metric label="Human Attention" value={payload.status.human_attention_required_count} />
        <Metric label="Stale Running" value={payload.status.stale_running_count} />
        <Metric label="Automation" value={payload.status.automation_assessment ?? 'evidence_missing'} detail={payload.status.last_event_timestamp} />
        <Metric label="Legacy Trader" value={payload.status.legacy_trader_disabled_non_blocking ? 'disabled_non_blocking' : 'evidence_missing'} />
        <Metric label="Proof Marker" value={payload.status.proof_marker} />
        <Metric label="Historical Marker" value={payload.status.historical_marker} />
      </div>
      <DataList title="Current blockers" rows={payload.mission_control.remaining_blockers} empty="No blocker evidence in current queue." />
    </Section>
  );
}

function DataList({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: object[];
  empty: string;
}): JSX.Element {
  return (
    <div className="operator-proof-detail">
      <h3>{title}</h3>
      {rows.length ? (
        <div className="operator-key-list">
          {rows.map((row, index) => (
            <dl key={`${title}-${index}`}>
              {Object.entries(row as Record<string, unknown>).map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{valueText(value)}</dd>
                </div>
              ))}
            </dl>
          ))}
        </div>
      ) : (
        <p className="operator-empty-state">{empty}</p>
      )}
    </div>
  );
}

function LineageSection({ rows }: { rows: LineageRow[] }): JSX.Element {
  return (
    <Section id="signal-explainability" title="Signal Explainability And Full Decision Lineage">
      <LineageCards rows={rows} />
    </Section>
  );
}

function LineageCards({ rows }: { rows: LineageRow[] }): JSX.Element {
  const [query, setQuery] = useState('');
  const filtered = rows.filter((row) => `${row.symbol} ${row.id} ${row.source}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <>
      <div className="operator-toolbar">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter by symbol, id, or source" aria-label="Filter lineage" />
        <span>{filtered.length} decisions</span>
      </div>
      <div className="operator-card-grid">
        {filtered.map((row) => (
          <details className="operator-drawer" key={row.id} open={row.symbol === 'LABUSDT'}>
            <summary>
              <span>{row.symbol}</span>
              <span>{row.id}</span>
              <span className={statusClass(row.risk_gateway_decision)}>{row.risk_gateway_decision}</span>
            </summary>
            <div className="operator-lineage-chain">
              {[
                ['raw source data', row.raw_source_data],
                ['feature snapshot', row.feature_snapshot_id],
                ['feature freshness', row.feature_freshness],
                ['trainer prediction', row.prediction_id],
                ['confidence old/new/delta', `${row.old_confidence} / ${row.new_confidence} / ${row.confidence_delta}`],
                ['model/checkpoint', row.model_checkpoint],
                ['signal', row.signal_id],
                ['orchestrator decision', row.orchestrator_decision],
                ['risk gateway decision', `${row.risk_gateway_decision} (${row.risk_decision_id})`],
                ['execution intent', row.execution_intent_id],
                ['paper/shadow/live-blocked action', row.paper_shadow_live_blocked_action],
                ['result/PnL attribution', row.result_pnl_attribution],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <div className="operator-split">
              <MiniList title="Top positive contributors" items={row.top_positive_contributors} />
              <MiniList title="Top negative contributors" items={row.top_negative_contributors} />
              <MiniList title="Stale flags" items={row.stale_flags} />
              <MiniList title="Missing flags" items={row.missing_flags} />
              <MiniList title="Unused flags" items={row.unused_flags} />
              <MiniList title="Warnings" items={row.warnings} />
            </div>
          </details>
        ))}
      </div>
    </>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }): JSX.Element {
  return (
    <div className="operator-mini-list">
      <h4>{title}</h4>
      {items.length ? items.map((item) => <span key={item}>{item}</span>) : <span>none</span>}
    </div>
  );
}

function FeatureAttribution({ rows }: { rows: FeatureRow[] }): JSX.Element {
  return (
    <Section id="feature-attribution" title="Feature Attribution">
      <div className="operator-proof-table operator-proof-table--feature" role="table">
        <div role="row" className="operator-proof-table__header">
          <span>Symbol</span><span>Snapshot</span><span>Freshness</span><span>Positive</span><span>Negative/Missing</span>
        </div>
        {rows.map((row) => (
          <div role="row" key={row.id}>
            <span>{row.symbol}</span>
            <span>{row.feature_snapshot_id}</span>
            <span className={statusClass(row.freshness)}>{row.freshness}</span>
            <span>{valueText(row.positive)}</span>
            <span>{valueText([...row.negative, ...row.missing])}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function SymbolUniverse({ rows }: { rows: SymbolRow[] }): JSX.Element {
  return (
    <Section id="symbol-universe" title="Symbol Universe">
      <div className="operator-proof-table operator-proof-table--symbols" role="table">
        <div role="row" className="operator-proof-table__header">
          <span>Symbol</span><span>Source</span><span>Liquidity</span><span>Volume/OI</span><span>State</span><span>Reason</span>
        </div>
        {rows.map((row) => (
          <div role="row" key={row.symbol}>
            <span>{row.symbol}</span>
            <span>{row.discovery_source}</span>
            <span>{row.liquidity_score}</span>
            <span>{row.volume_score} / {row.open_interest_score}</span>
            <span>{row.universe_state}</span>
            <span>{row.why_state}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function RiskGateway({ rows }: { rows: RiskRow[] }): JSX.Element {
  return (
    <Section id="risk-gateway" title="Risk Gateway">
      <div className="operator-proof-table operator-proof-table--risk" role="table">
        <div role="row" className="operator-proof-table__header">
          <span>Symbol</span><span>Final</span><span>Stale</span><span>Duplicate</span><span>Exposure</span><span>Reason</span>
        </div>
        {rows.map((row) => (
          <div role="row" key={row.id}>
            <span>{row.symbol}</span>
            <span className={statusClass(row.final_decision)}>{row.final_decision}</span>
            <span>{row.stale_signal_check}</span>
            <span>{row.duplicate_signal_check}</span>
            <span>{row.exposure_check}</span>
            <span>{row.final_reason}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function MonitorCenter({ rows }: { rows: MonitorRow[] }): JSX.Element {
  return (
    <Section id="monitor-center" title="Monitor Center">
      <div className="operator-proof-table operator-proof-table--monitor" role="table">
        <div role="row" className="operator-proof-table__header">
          <span>Monitor</span><span>Status</span><span>Last Run</span><span>Processes</span><span>Alerts</span>
        </div>
        {rows.map((row) => (
          <div role="row" key={row.id}>
            <span>{row.script_path}</span>
            <span className={statusClass(row.status)}>{row.classification} / {row.status}</span>
            <span>{row.last_run}</span>
            <span>{valueText(row.processes_watched)}</span>
            <span>{valueText(row.alerts)}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function ConfigAdmin({ rows }: { rows: SettingRow[] }): JSX.Element {
  return (
    <Section id="config-admin" title="Config Admin">
      <div className="operator-proof-table operator-proof-table--config" role="table">
        <div role="row" className="operator-proof-table__header">
          <span>Setting</span><span>Value</span><span>Classification</span>
        </div>
        {rows.map((row) => (
          <div role="row" key={row.name}>
            <span>{row.name}</span>
            <span>{row.value}</span>
            <span className={statusClass(row.classification)}>{row.classification}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function TraderFleet({ paper, shadow }: { paper: PaperRow[]; shadow: ShadowRow[] }): JSX.Element {
  return (
    <Section id="trader-fleet" title="Trader Fleet / Paper-Shadow Actions">
      <div className="operator-split">
        <DataList title="Paper ledger actions" rows={paper} empty="No paper ledger evidence." />
        <DataList title="Shadow comparisons" rows={shadow} empty="No shadow comparison evidence." />
      </div>
    </Section>
  );
}

function SimpleCoverageSections({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <>
      <Section id="system-atlas" title="Script Registry / System Atlas">
        <DataList title="Registered scripts" rows={payload.script_registry_system_atlas.rows} empty="No script registry evidence." />
      </Section>
      <Section id="orchestrator-decisions" title="Orchestrator Decisions">
        <DataList title="Decision handoffs" rows={payload.orchestrator_decisions.rows} empty="No orchestrator decisions." />
      </Section>
      <Section id="audit-ledger" title="Audit Ledger">
        <DataList title="Evidence artifacts" rows={payload.audit_ledger.rows} empty="No audit artifacts." />
      </Section>
      <Section id="replay--historical-proof" title="Replay / Historical Proof">
        <div className="operator-proof-grid">
          {Object.entries(payload.replay_historical_proof.summary ?? {}).map(([key, value]) => (
            <Metric key={key} label={key} value={value} />
          ))}
        </div>
        <MiniList title="Data gaps" items={payload.replay_historical_proof.limitations ?? []} />
      </Section>
      <Section id="live-readiness" title="Live Readiness">
        <div className="operator-proof-grid">
          <Metric label="Live gate" value={payload.live_readiness.live_gate_status} />
          <Metric label="Approval required" value={String(payload.live_readiness.approval_required)} />
          <Metric label="Dangerous controls enabled" value={String(payload.live_readiness.dangerous_controls_enabled)} />
        </div>
        <DataList title="Live blockers" rows={payload.live_readiness.live_blockers} empty="No live blockers." />
      </Section>
      <Section id="automation-status" title="Claude/Codex/Ollama Automation Status">
        {payload.automation_status.liveness ? (
          <>
            <div className="operator-proof-grid">
              <Metric label="Assessment" value={payload.automation_status.liveness.automation_assessment} />
              <Metric label="Planner" value={String(payload.automation_status.liveness.dashboard_summary.claude_planner_running)} />
              <Metric label="Codex Watchdog" value={String(payload.automation_status.liveness.dashboard_summary.codex_watchdog_running)} />
              <Metric label="Scheduler" value={String(payload.automation_status.liveness.dashboard_summary.scheduler_running)} />
              <Metric label="Task Run PID" value={payload.automation_status.liveness.task_liveness.run_pid ?? 'none'} />
              <Metric label="Last Event" value={payload.automation_status.liveness.dashboard_summary.last_event_timestamp} />
              <Metric label="Last Artifact" value={payload.automation_status.liveness.dashboard_summary.last_artifact_update} />
              <Metric label="Next Task" value={payload.automation_status.liveness.dashboard_summary.next_runnable_task} />
            </div>
            <DataList
              title="Liveness warnings"
              rows={payload.automation_status.liveness.task_liveness.warnings.map((warning) => ({ warning }))}
              empty="No liveness warnings."
            />
            <DataList
              title="Legacy trader down tolerance"
              rows={[
                {
                  status: payload.automation_status.liveness.legacy_trader_policy.legacy_trader_status,
                  required_for_v2_build: String(payload.automation_status.liveness.legacy_trader_policy.legacy_trader_required_for_v2_build),
                  non_blocking: String(payload.automation_status.liveness.legacy_trader_policy.legacy_trader_down_should_not_block_non_live_rebuild),
                  note: payload.automation_status.liveness.legacy_trader_policy.operator_note,
                },
              ]}
              empty="No legacy trader policy evidence."
            />
          </>
        ) : null}
        <DataList title="Stale cleanup status" rows={payload.remaining_blockers_before_live} empty="No stale cleanup blockers." />
      </Section>
      <Section id="remaining-blockers" title="Remaining Blockers Before Live">
        <DataList title="Blockers" rows={payload.remaining_blockers_before_live} empty="No blocker evidence." />
        <MiniList title="Evidence gaps" items={payload.data_gaps} />
      </Section>
    </>
  );
}

export default function OperatorProofDashboardPage(): JSX.Element {
  const [payload, setPayload] = useState<CockpitPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchJson<CockpitPayload>(cockpitPath)
      .then((next) => {
        if (active) setPayload(next);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'operator cockpit payload unavailable');
      });
    return () => {
      active = false;
    };
  }, []);

  const pageAttrs = useMemo(
    () => ({
      className: 'operator-proof-page operator-cockpit-page',
      'data-testid': 'operator-proof-dashboard',
      'data-page-id': (meta as PageMeta).id,
      'data-page-surface': meta.surface,
      'data-page-min-role': rbac.minRole,
      'data-page-path': route.path,
    }),
    [],
  );

  if (error) {
    return (
      <article {...pageAttrs}>
        <h1>{meta.title}</h1>
        <p role="alert">Operator cockpit evidence unavailable: {error}</p>
      </article>
    );
  }

  if (!payload) {
    return (
      <article {...pageAttrs}>
        <h1>{meta.title}</h1>
        <p>Loading operator cockpit evidence...</p>
      </article>
    );
  }

  return (
    <article {...pageAttrs}>
      <section className="operator-proof-hero operator-cockpit-hero" data-testid="operator-proof-hero">
        <div>
          <p className="operator-proof-kicker">Professional non-live operator cockpit</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="operator-proof-status">
          <span className={statusClass(payload.status.go_no_go)} data-testid="operator-gui-marker">{payload.status.go_no_go}</span>
          <span className="proof-pill proof-pill--blocked" data-testid="operator-live-gate">{payload.live_gate_status}</span>
        </div>
      </section>
      <TopStatusBar payload={payload} />
      <div className="operator-cockpit-layout">
        <SidebarNav />
        <div className="operator-cockpit-content">
          <MissionControl payload={payload} />
          <MonitorCenter rows={payload.monitor_center.rows} />
          <SimpleCoverageSections payload={payload} />
          <Section id="trainer-prediction-monitor" title="Trainer Prediction Monitor">
            <LineageCards rows={payload.trainer_prediction_monitor.rows} />
          </Section>
          <LineageSection rows={payload.signal_explainability.rows} />
          <FeatureAttribution rows={payload.feature_attribution.rows} />
          <SymbolUniverse rows={payload.symbol_universe.rows} />
          <RiskGateway rows={payload.risk_gateway.rows} />
          <TraderFleet paper={payload.trader_fleet_paper_shadow.paper_rows} shadow={payload.trader_fleet_paper_shadow.shadow_rows} />
          <ConfigAdmin rows={payload.config_admin.settings} />
        </div>
      </div>
    </article>
  );
}
