import meta from './meta';
import rbac from './rbac';
import route from './route';
import { DesignPageShell } from '../designShell';
import { usePayloadFile } from '../../hooks/usePayloadFile';
import { publicRuntimeCopy } from '../../lib/tradeCopy';

const REPORT_INDEX_PATH = '/v2_report_center/latest/report_index.json';
const REPORT_DASHBOARD_PATH = '/v2_report_center/latest/operator_dashboard_payload.json';
const REPORT_CODEX_FAILS_PATH = '/v2_report_center/latest/latest_codex_failures.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface LiveGateRuntimePayload {
  execution_live_symbols?: string[];
  live_gate?: string;
}

interface LaneEntry {
  report_id: string;
  title: string;
  owner: string;
  source_type: string;
  status: string;
  go_no_go: string | null;
  generated_at: string | null;
  freshness_seconds: number | null;
  stale: boolean;
  codex_passed: boolean | null;
  blocks_live: boolean;
  blocks_shutdown: boolean;
  blocks_production_equivalence: boolean;
  blocks_recovery: boolean;
  current_blockers: string[];
  next_action: string | null;
  public_payload_path: string | null;
  safe_report_path: string;
  frontend_visible: boolean;
  live_gate: string;
  live_symbols: string[];
  approves_live: boolean;
  approves_canary: boolean;
  approves_legacy_shutdown: boolean;
  approves_redis_trim: boolean;
  redaction_applied: boolean;
}

interface ReportIndexPayload {
  generated_at?: string;
  lanes?: LaneEntry[];
  report_count?: number;
  stale_report_count?: number;
  fail_count?: number;
  blocked_count?: number;
  codex_pass_count?: number;
  codex_fail_count?: number;
  operator_decision_required_count?: number;
  live_gate?: string;
  live_symbols?: string[];
}

interface ExecutiveBigStateEntry {
  key: string;
  value: 'YES' | 'NO' | string;
  plain_english: string;
  evidence?: Record<string, unknown>;
}

interface ExecutiveSummaryEmbedded {
  schema_version?: string;
  headline?: string;
  big_state_banner?: ExecutiveBigStateEntry[];
  plain_english_truth?: string;
  top_blockers_plain?: Array<{ key: string; plain_english: string }>;
  next_required_actions?: Array<{ key: string; owner: string; plain_english: string }>;
}

interface OperatorDashboardPayload {
  generated_at?: string;
  executive_summary?: ExecutiveSummaryEmbedded;
  report_count?: number;
  stale_report_count?: number;
  fail_count?: number;
  blocked_count?: number;
  codex_pass_count?: number;
  codex_fail_count?: number;
  operator_decision_required_count?: number;
  live_blocked?: boolean;
  shutdown_blocked?: boolean;
  production_equivalence_blocked?: boolean;
  live_gate?: string;
  live_symbols?: string[];
  approves_live?: boolean;
  approves_canary?: boolean;
  approves_legacy_shutdown?: boolean;
  approves_redis_trim?: boolean;
  top_blockers?: Array<{
    report_id: string;
    title: string;
    status: string;
    next_action: string | null;
    blocks_live: boolean;
    blocks_shutdown: boolean;
    owner: string;
  }>;
  next_automatable_actions?: Array<{
    report_id: string;
    title: string;
    owner: string;
    next_action: string | null;
    status: string;
  }>;
  next_operator_decisions?: Array<{
    report_id: string;
    title: string;
    owner: string;
    next_action: string | null;
  }>;
  current_scorecard?: {
    overall_score?: number;
    categories?: Record<string, { score?: number; blockers?: string[]; next_action?: string }>;
  };
  current_pending_tasks?: { claude?: number; codex?: number };
  current_stalled_tasks?: { claude?: number; codex?: number };
  current_codex_failures?: number;
  current_autonomous_controller_state?: {
    go_no_go?: string;
    selector_status?: string;
    selected_work?: { category?: string; severity?: string; source?: string; remediation?: string };
    automatable_issue_count?: number;
    operator_owned_issue_count?: number;
  };
  required_visible_text?: string[];
}

interface CodexFailuresPayload {
  codex_failures?: Array<{
    report_id: string;
    title: string;
    go_no_go: string | null;
    next_action: string | null;
  }>;
  count?: number;
}

function pct(value: number, total: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((value / total) * 100)));
}

function formatFreshness(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'no payload';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 60 * 60) return `${Math.round(seconds / 60)}m`;
  if (seconds < 60 * 60 * 24) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function payloadAge(generatedAt?: string): number | null {
  if (!generatedAt) return null;
  const ms = new Date(generatedAt).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.round((Date.now() - ms) / 1000));
}

function toneForStatus(status?: string): 'ok' | 'warn' | 'block' | 'paper' {
  if (status === 'PASS' || status === 'READY') return 'ok';
  if (status === 'FAIL' || status === 'BLOCKED') return 'block';
  if (status === 'OPERATOR_DECISION_REQUIRED' || status === 'MISSING_PAYLOAD') return 'warn';
  return 'paper';
}

function MetricCard({
  label,
  value,
  detail,
  tone = 'paper',
}: {
  label: string;
  value: string | number;
  detail: string;
  tone?: 'ok' | 'warn' | 'block' | 'paper';
}): JSX.Element {
  return (
    <div className={`report-metric-card report-metric-card--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function RingChart({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: 'ok' | 'warn' | 'block' | 'paper';
}): JSX.Element {
  const percent = pct(value, total);
  return (
    <div className="report-ring-card">
      <div className={`report-ring report-ring--${tone}`} style={{ ['--report-ring-value' as string]: `${percent}%` }}>
        <span>{percent}%</span>
      </div>
      <div>
        <strong>{label}</strong>
        <small>{value} of {total || 0}</small>
      </div>
    </div>
  );
}

function BarMeter({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: 'ok' | 'warn' | 'block' | 'paper';
}): JSX.Element {
  return (
    <div className="report-bar-meter">
      <div className="report-bar-meter__head">
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className="report-bar-meter__track">
        <span className={`report-bar-meter__fill report-bar-meter__fill--${tone}`} style={{ width: `${pct(value, total)}%` }} />
      </div>
    </div>
  );
}

function executiveTone(value: string | undefined): 'ok' | 'block' | 'warn' | 'paper' {
  if (value === 'YES') return 'ok';
  if (value === 'NO') return 'block';
  return 'warn';
}

function ExecutiveBigStateBanner({
  dashboard,
}: {
  dashboard: OperatorDashboardPayload | null;
}): JSX.Element {
  const exec = dashboard?.executive_summary;
  const entries = exec?.big_state_banner ?? [];
  return (
    <section
      className="report-overview-grid"
      aria-label="Executive big state banner"
      data-testid="report-center-executive-banner"
    >
      {entries.length === 0 ? (
        <div className="report-callout report-callout--warn">
          <strong>Executive summary missing from dashboard payload.</strong>
          <span>Defaults apply: nothing is migrated, ready, or approved.</span>
        </div>
      ) : (
        entries.map((e) => (
          <div
            key={e.key}
            className={`report-metric-card report-metric-card--${executiveTone(e.value)}`}
            data-testid={`report-center-exec-state-${e.key}`}
          >
            <span>{publicRuntimeCopy(e.key.replace(/_/g, ' '))}</span>
            <strong>{e.value}</strong>
            <small>{publicRuntimeCopy(e.plain_english)}</small>
          </div>
        ))
      )}
    </section>
  );
}

function ExecutiveTruthCallout({
  dashboard,
}: {
  dashboard: OperatorDashboardPayload | null;
}): JSX.Element | null {
  const exec = dashboard?.executive_summary;
  if (!exec?.plain_english_truth) return null;
  return (
    <section
      className="report-callout report-callout--warn"
      aria-label="Plain-English current truth"
    >
      <strong>Plain-English truth</strong>
      <span>{publicRuntimeCopy(exec.plain_english_truth)}</span>
      <a href="/system/executive-summary">Open Executive Summary</a>
    </section>
  );
}

function SafetyStateBanner({ dashboard }: { dashboard: OperatorDashboardPayload | null }): JSX.Element {
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const live = liveGateRuntime?.live_gate ?? dashboard?.live_gate ?? 'loading';
  const liveBlocked = dashboard?.live_blocked !== false;
  const shutdownBlocked = dashboard?.shutdown_blocked !== false;
  const peBlocked = dashboard?.production_equivalence_blocked !== false;
  return (
    <section className="report-safety-banner" role="status" aria-label="Safety state">
      <div>
        <strong>Live runtime: {live}.</strong>
        <strong>Legacy shutdown is blocked.</strong>
        <span>Candidate symbols are not adopted automatically.</span>
        <span>Recovery requires proof of edge before scaling.</span>
        <span>No fake readiness.</span>
      </div>
      <div className="report-safety-banner__facts">
        <code>live_gate={live}</code>
        <code>execution_live_symbols={(liveGateRuntime?.execution_live_symbols ?? dashboard?.live_symbols ?? []).join(', ') || 'none'}</code>
        <code>live_blocked={String(liveBlocked)}</code>
        <code>shutdown_blocked={String(shutdownBlocked)}</code>
        <code>production_equivalence_blocked={String(peBlocked)}</code>
      </div>
    </section>
  );
}

function LiveRefreshStrip({
  index,
  dashboard,
  fetching,
}: {
  index: ReportIndexPayload | null;
  dashboard: OperatorDashboardPayload | null;
  fetching: boolean;
}): JSX.Element {
  return (
    <section className="report-refresh-strip" aria-label="Realtime refresh status">
      <span className={fetching ? 'report-pulse report-pulse--active' : 'report-pulse'} />
      <div>
        <strong>{fetching ? 'Streaming live payloads' : 'Live resource stream active'}</strong>
        <small>WebSocket resource stream · API fallback enabled</small>
      </div>
      <code>index {formatFreshness(payloadAge(index?.generated_at))}</code>
      <code>dashboard {formatFreshness(payloadAge(dashboard?.generated_at))}</code>
    </section>
  );
}

function OverviewPanel({
  index,
  dashboard,
}: {
  index: ReportIndexPayload | null;
  dashboard: OperatorDashboardPayload | null;
}): JSX.Element {
  const total = dashboard?.report_count ?? index?.report_count ?? index?.lanes?.length ?? 0;
  const stale = dashboard?.stale_report_count ?? index?.stale_report_count ?? 0;
  const blocked = dashboard?.blocked_count ?? index?.blocked_count ?? 0;
  const codexFails = dashboard?.codex_fail_count ?? index?.codex_fail_count ?? 0;
  const codexPass = dashboard?.codex_pass_count ?? index?.codex_pass_count ?? 0;
  return (
    <section className="report-overview-grid" aria-label="Report center overview">
      <MetricCard label="Visible Lanes" value={total} detail="all registered lanes stay visible" tone="ok" />
      <MetricCard label="Stale Lanes" value={stale} detail="shown, never hidden" tone={stale ? 'warn' : 'ok'} />
      <MetricCard label="Blocked Lanes" value={blocked} detail="production/live blockers surfaced" tone={blocked ? 'block' : 'ok'} />
      <MetricCard label="Codex Failures" value={codexFails} detail={`${codexPass} Codex passes in index`} tone={codexFails ? 'block' : 'ok'} />
      <MetricCard
        label="Pending Tasks"
        value={(dashboard?.current_pending_tasks?.claude ?? 0) + (dashboard?.current_pending_tasks?.codex ?? 0)}
        detail="Claude + Codex pending descriptors"
        tone="paper"
      />
      <MetricCard
        label="Operator Decisions"
        value={dashboard?.operator_decision_required_count ?? index?.operator_decision_required_count ?? 0}
        detail="human-held, not automated"
        tone={(dashboard?.operator_decision_required_count ?? 0) ? 'warn' : 'ok'}
      />
    </section>
  );
}

function LaneHealthPanel({ index }: { index: ReportIndexPayload | null }): JSX.Element {
  const lanes = index?.lanes ?? [];
  const total = lanes.length || index?.report_count || 0;
  const ready = lanes.filter((l) => l.status === 'READY' || l.status === 'PASS').length;
  const stale = lanes.filter((l) => l.stale).length;
  const blocked = lanes.filter((l) => l.status === 'BLOCKED' || l.status === 'FAIL').length;
  const missing = lanes.filter((l) => l.status === 'MISSING_PAYLOAD').length;
  return (
    <section className="report-panel report-panel--span" aria-label="Lane health charts">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Lane Health</p>
          <h2>Report visibility and freshness</h2>
        </div>
        <span className="chip">{total} lanes</span>
      </div>
      <div className="report-chart-grid">
        <RingChart label="Ready/Pass" value={ready} total={total} tone="ok" />
        <RingChart label="Fresh" value={Math.max(0, total - stale)} total={total} tone={stale ? 'warn' : 'ok'} />
        <RingChart label="Blocked/Fail" value={blocked} total={total} tone={blocked ? 'block' : 'ok'} />
        <RingChart label="Missing Payload" value={missing} total={total} tone={missing ? 'warn' : 'ok'} />
      </div>
      <div className="report-meter-stack">
        <BarMeter label="Stale lanes" value={stale} total={total} tone={stale ? 'warn' : 'ok'} />
        <BarMeter label="Blocked lanes" value={blocked} total={total} tone={blocked ? 'block' : 'ok'} />
        <BarMeter label="Missing payload lanes" value={missing} total={total} tone={missing ? 'warn' : 'ok'} />
      </div>
    </section>
  );
}

function ExecutiveScorecardPanel({ dashboard }: { dashboard: OperatorDashboardPayload | null }): JSX.Element {
  const score = dashboard?.current_scorecard?.overall_score;
  const categories = Object.entries(dashboard?.current_scorecard?.categories ?? {});
  return (
    <section className="report-panel" aria-label="Production readiness scorecard">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Readiness</p>
          <h2>Production scorecard</h2>
        </div>
        <span className={`chip solid-${score && score >= 80 ? 'ok' : 'warn'}`}>{score === undefined ? 'n/a' : `${score}/100`}</span>
      </div>
      {categories.length === 0 ? (
        <p className="report-empty">Scorecard categories are not present in the latest payload.</p>
      ) : (
        <div className="report-meter-stack">
          {categories.map(([name, body]) => (
            <BarMeter key={name} label={publicRuntimeCopy(name).replace(/_/g, ' ')} value={body.score ?? 0} total={100} tone={(body.score ?? 0) >= 80 ? 'ok' : 'warn'} />
          ))}
        </div>
      )}
    </section>
  );
}

function ControllerStatePanel({ dashboard }: { dashboard: OperatorDashboardPayload | null }): JSX.Element {
  const state = dashboard?.current_autonomous_controller_state;
  const work = state?.selected_work;
  return (
    <section className="report-panel" aria-label="Autonomous controller state">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Automation</p>
          <h2>Controller state</h2>
        </div>
        <span className="chip solid-paper">{publicRuntimeCopy(state?.selector_status, 'n/a')}</span>
      </div>
      <div className="report-fact-grid">
        <div><span>Automatable</span><strong>{state?.automatable_issue_count ?? 0}</strong></div>
        <div><span>Operator-held</span><strong>{state?.operator_owned_issue_count ?? 0}</strong></div>
        <div><span>GO/NO-GO</span><code>{publicRuntimeCopy(state?.go_no_go, 'n/a')}</code></div>
      </div>
      {work ? (
        <div className="report-callout report-callout--warn">
          <strong>{publicRuntimeCopy(work.category, 'selected work')}</strong>
          <span>{publicRuntimeCopy(work.remediation ?? work.source, 'No remediation text in payload.')}</span>
        </div>
      ) : (
        <div className="report-callout report-callout--ok">
          <strong>No selected work this cycle.</strong>
          <span>The controller is waiting for new automatable evidence or operator-held gates.</span>
        </div>
      )}
    </section>
  );
}

function PendingAndStalledTasksPanel({ dashboard }: { dashboard: OperatorDashboardPayload | null }): JSX.Element {
  const pending = dashboard?.current_pending_tasks ?? {};
  const stalled = dashboard?.current_stalled_tasks ?? {};
  const codexFails = dashboard?.current_codex_failures ?? 0;
  return (
    <section className="report-panel" aria-label="Pending and stalled tasks">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Task Flow</p>
          <h2>Pending and stalled</h2>
        </div>
        <span className={codexFails ? 'chip solid-block' : 'chip solid-ok'}>Codex fails {codexFails}</span>
      </div>
      <div className="report-fact-grid">
        <div><span>Pending Claude</span><strong>{pending.claude ?? 0}</strong></div>
        <div><span>Pending Codex</span><strong>{pending.codex ?? 0}</strong></div>
        <div><span>Stalled Claude</span><strong>{stalled.claude ?? 0}</strong></div>
        <div><span>Stalled Codex</span><strong>{stalled.codex ?? 0}</strong></div>
      </div>
    </section>
  );
}

function BlockerMatrixPanel({ dashboard }: { dashboard: OperatorDashboardPayload | null }): JSX.Element {
  const blockers = dashboard?.top_blockers ?? [];
  return (
    <section className="report-panel report-panel--span" aria-label="Top blockers">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Blocker Matrix</p>
          <h2>Current blockers</h2>
        </div>
        <span className={blockers.length ? 'chip solid-block' : 'chip solid-ok'}>{blockers.length} blockers</span>
      </div>
      {blockers.length === 0 ? (
        <p className="report-empty">No active blockers in the latest payload.</p>
      ) : (
        <div className="report-card-list">
          {blockers.map((b) => (
            <article className="report-work-card report-work-card--block" key={b.report_id}>
              <div>
                <strong>{publicRuntimeCopy(b.title)}</strong>
                <span>{publicRuntimeCopy(b.report_id)}</span>
              </div>
              <p>{publicRuntimeCopy(b.next_action, 'No next action provided.')}</p>
              <div className="report-chip-row">
                <span className="chip">{publicRuntimeCopy(b.status)}</span>
                {b.blocks_live ? <span className="chip solid-block">blocks live</span> : null}
                {b.blocks_shutdown ? <span className="chip solid-block">blocks shutdown</span> : null}
                <span className="chip solid-paper">owner {publicRuntimeCopy(b.owner)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function NextActionsPanel({ dashboard }: { dashboard: OperatorDashboardPayload | null }): JSX.Element {
  const auto = dashboard?.next_automatable_actions ?? [];
  const op = dashboard?.next_operator_decisions ?? [];
  return (
    <section className="report-panel" aria-label="Next actions">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Next Actions</p>
          <h2>Automation queue</h2>
        </div>
        <span className="chip">{auto.length + op.length} actions</span>
      </div>
      <div className="report-card-list">
        {auto.length === 0 ? (
          <div className="report-callout report-callout--ok">
            <strong>No automatable action selected.</strong>
            <span>Automation is monitor-only until new eligible work appears.</span>
          </div>
        ) : auto.map((a) => (
          <article className="report-work-card" key={a.report_id}>
            <strong>{publicRuntimeCopy(a.title)}</strong>
            <p>{publicRuntimeCopy(a.next_action ?? '')}</p>
            <span className="chip solid-paper">{publicRuntimeCopy(a.status)} / {publicRuntimeCopy(a.owner)}</span>
          </article>
        ))}
        {op.map((a) => (
          <article className="report-work-card report-work-card--warn" key={a.report_id}>
            <strong>{publicRuntimeCopy(a.title)}</strong>
            <p>{publicRuntimeCopy(a.next_action ?? '')}</p>
            <span className="chip solid-warn">operator decision / {publicRuntimeCopy(a.owner)}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function LatestCodexFailuresPanel(): JSX.Element {
  const codexFails = usePayloadFile<CodexFailuresPayload>(REPORT_CODEX_FAILS_PATH, 15_000);
  const fails = codexFails.data?.codex_failures ?? [];
  return (
    <section className="report-panel" aria-label="Latest Codex failures">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Codex Review</p>
          <h2>Latest failures</h2>
        </div>
        <span className={fails.length ? 'chip solid-block' : 'chip solid-ok'}>{codexFails.data?.count ?? 0}</span>
      </div>
      {fails.length === 0 ? (
        <p className="report-empty">No active Codex failures in the latest payload.</p>
      ) : (
        <div className="report-card-list">
          {fails.map((f) => (
            <article className="report-work-card report-work-card--block" key={f.report_id}>
              <strong>{publicRuntimeCopy(f.title)}</strong>
              <code>{publicRuntimeCopy(f.go_no_go ?? '')}</code>
              <p>{publicRuntimeCopy(f.next_action ?? '')}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function StaleReportsPanel({ index }: { index: ReportIndexPayload | null }): JSX.Element {
  const stale = (index?.lanes ?? []).filter((l) => l.stale);
  return (
    <section className="report-panel" aria-label="Stale reports">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Freshness</p>
          <h2>Stale reports</h2>
        </div>
        <span className={stale.length ? 'chip solid-warn' : 'chip solid-ok'}>{stale.length}</span>
      </div>
      {stale.length === 0 ? (
        <p className="report-empty">All report lanes are fresh.</p>
      ) : (
        <div className="report-card-list report-card-list--compact">
          {stale.slice(0, 10).map((l) => (
            <article className="report-work-card report-work-card--warn" key={l.report_id}>
              <strong>{publicRuntimeCopy(l.title)}</strong>
              <span>{formatFreshness(l.freshness_seconds)} / {publicRuntimeCopy(l.status)}</span>
              <p>{publicRuntimeCopy(l.next_action, 'No next action in lane payload.')}</p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function ReportStatusTable({ index }: { index: ReportIndexPayload | null }): JSX.Element {
  const lanes = index?.lanes ?? [];
  return (
    <section className="report-panel report-panel--span" aria-label="Report lanes">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">All Lanes</p>
          <h2>Report lane matrix</h2>
        </div>
        <span className="chip">{lanes.length} visible</span>
      </div>
      <div className="report-lane-table" role="table">
        <div className="report-lane-row report-lane-row--head" role="row">
          <span>Lane</span>
          <span>Status</span>
          <span>Owner</span>
          <span>Freshness</span>
          <span>GO/NO-GO</span>
          <span>Next action</span>
        </div>
        {lanes.map((lane) => (
          <div className={lane.stale ? 'report-lane-row report-lane-row--stale' : 'report-lane-row'} role="row" key={lane.report_id}>
            <span>
              <strong>{publicRuntimeCopy(lane.title)}</strong>
              <small>{publicRuntimeCopy(lane.report_id)}</small>
            </span>
            <span>
              <em className={`report-status-pill report-status-pill--${toneForStatus(lane.status)}`}>{publicRuntimeCopy(lane.status)}</em>
              {lane.stale ? <small>stale</small> : null}
            </span>
            <span>{publicRuntimeCopy(lane.owner)}</span>
            <span>{formatFreshness(lane.freshness_seconds)}</span>
            <code>{publicRuntimeCopy(lane.go_no_go ?? '')}</code>
            <span>{publicRuntimeCopy(lane.next_action ?? '')}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function ReportCenterPage(): JSX.Element {
  const indexQ = usePayloadFile<ReportIndexPayload>(REPORT_INDEX_PATH, 30_000);
  const dashboardQ = usePayloadFile<OperatorDashboardPayload>(REPORT_DASHBOARD_PATH, 15_000);

  const payloadFailed = indexQ.error || dashboardQ.error;
  const fetching = indexQ.loading || dashboardQ.loading;

  return (
    <DesignPageShell
      meta={meta}
      rbac={rbac}
      route={route}
      eyebrow="Report Center"
      source="V2_REPORT_CENTER_PUBLIC_PAYLOAD"
      status="REALTIME TRUTH LAYER"
    >
      <SafetyStateBanner dashboard={dashboardQ.data} />

      <ExecutiveBigStateBanner dashboard={dashboardQ.data} />
      <ExecutiveTruthCallout dashboard={dashboardQ.data} />

      {payloadFailed ? (
        <section className="report-error-banner" role="alert" aria-label="Report center stale or unavailable">
          <strong>REPORT_CENTER_STALE_OR_UNAVAILABLE</strong>
          <span>One or more report payloads failed to load. Blockers remain visible and no ready state is inferred.</span>
        </section>
      ) : null}

      <section className="report-title-band" aria-label="Current objective">
        <div>
          <p className="eyebrow">Executive Runtime</p>
          <h1>Realtime report center</h1>
          <p>
            Production-equivalence, capital recovery, and automation health in one live view.
            Stale and missing lanes stay visible; live and shutdown remain blocked.
          </p>
        </div>
        <LiveRefreshStrip index={indexQ.data} dashboard={dashboardQ.data} fetching={fetching} />
      </section>

      <OverviewPanel index={indexQ.data} dashboard={dashboardQ.data} />

      <div className="report-dashboard-grid">
        <LaneHealthPanel index={indexQ.data} />
        <ExecutiveScorecardPanel dashboard={dashboardQ.data} />
        <ControllerStatePanel dashboard={dashboardQ.data} />
        <PendingAndStalledTasksPanel dashboard={dashboardQ.data} />
        <NextActionsPanel dashboard={dashboardQ.data} />
        <LatestCodexFailuresPanel />
        <StaleReportsPanel index={indexQ.data} />
        <BlockerMatrixPanel dashboard={dashboardQ.data} />
        <ReportStatusTable index={indexQ.data} />
      </div>
    </DesignPageShell>
  );
}
