import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from 'recharts';
import { EquityAreaChart, PnLBars, Donut, DonutLegend, RadialGauge, ChartFrame } from '../../components/charts/NervyxCharts';
import { fmtUsd as chartUsd } from '../../components/charts/nervyxChartTheme';
import { usePaperActivityStream } from '../../hooks/usePaperActivityStream';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useAuth } from '../../hooks/useAuth';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { canSee, normalizeRole } from '../../auth/rbac';
import { MissionControlReadinessBanner } from '../../components/banners/MissionControlReadinessBanner';
import { SelfHealingBanner } from '../../components/banners/SelfHealingBanner';
import { StaleStateAlertsPanel } from '../../components/dashboard/StaleStateAlertsPanel';
import { CanonicalMetricValue } from '../../components/data/CanonicalMetric';
import { healthStatusTone } from '../../components/system/healthStatus';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  adaptiveStatusColor,
  formatAdaptiveBps,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  pnlWindow,
  type CapitalProductivityRuntimeStatus,
  type PnlHistoryStatus,
  type SignalPredictionAccuracyStatus,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import { NERVYX_BRAND } from '../../brand/nervyxBrand';
import type { ValidatedDataEnvelope } from '../../types/dataContract';
import { selectAccountMetric, selectSectionMetric, type CanonicalMetric } from '../../selectors/accountSelectors';
import { selectActiveSignal, selectSignalMetric } from '../../selectors/signalSelectors';
import { selectRiskStatus } from '../../selectors/riskSelectors';
import meta from './meta';

// ─── types ───────────────────────────────────────────────────────────────────

interface PortfolioData {
  equity?: number | null;
  paper_equity?: number | null;
  paper_balance?: number | null;
  paper_equity_usd?: number | null;
  initial_capital?: number | null;
  paper_initial_capital?: number | null;
  starting_equity_usd?: number | null;
  paper_realized_pnl_usd?: number | null;
  paper_unrealized_pnl_usd?: number | null;
  paper_total_pnl_usd?: number | null;
  realized_net_pnl_usd?: number | null;
  realized_gross_pnl_usd?: number | null;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  total_pnl_usd?: number | null;
  clean_session_valid_realized_pnl_usd?: number | null;
  clean_session_valid_unrealized_pnl_usd?: number | null;
  realized_pnl?: number | null;
  unrealized_pnl?: number | null;
  paper_session_id?: string | null;
  data_source?: string | null;
  staleness_seconds?: number | null;
  freshness_status?: string | null;
  pnl_source_key?: string | null;
  pnl_source_route?: string | null;
  pnl_source_type?: string | null;
  pnl_conflict_detected?: boolean | null;
  open_positions?: unknown[];
  account_mode?: string | null;
}

interface ReadonlyContract<T> {
  schema_version?: string;
  data?: T | null;
  source?: string | null;
  staleness_seconds?: number | null;
  freshness_status?: string | null;
  data_quality_status?: string | null;
  live_gate?: unknown;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
}

interface LiveCanaryStatusData {
  why_none?: string | null;
  dry_run?: boolean | null;
  operator_approval_required?: boolean | null;
  selected_a_plus_candidate?: unknown;
  no_mutation_flags?: Record<string, unknown> | null;
  status_payload?: Record<string, unknown> | null;
}

interface APlusInventoryData {
  evaluated_candidates?: number | null;
  a_plus_candidates?: number | null;
  live_ready_rows?: number | null;
  counts_as_final_a_plus?: boolean | null;
  probation_counts_as_final_a_plus?: boolean | null;
  paper_session_id?: string | null;
  rejected_reason_matrix?: Record<string, unknown> | null;
}

interface GoalTrajectoryBindingConstraint {
  constraint?: string | null;
  detail?: string | null;
  evidence?: Record<string, unknown> | null;
}

interface GoalTrajectory1000xData {
  objective?: string | null;
  paper_session_id?: string | null;
  session_started_utc?: string | null;
  days_elapsed?: number | null;
  starting_equity_usd?: number | null;
  equity_usd?: number | null;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  multiple_now?: number | null;
  target_multiple?: number | null;
  target_days?: number | null;
  required_daily_rate_pct?: number | null;
  actual_daily_rate_pct?: number | null;
  on_track?: boolean | null;
  required_equity_today_usd?: number | null;
  equity_gap_vs_required_usd?: number | null;
  days_to_target_at_required_rate_from_here?: number | null;
  binding_constraint?: GoalTrajectoryBindingConstraint | null;
  open_position_count?: number | null;
  closed_trade_count?: number | null;
  generated_utc?: string | null;
  age_seconds?: number | null;
  stale_after_seconds?: number | null;
  is_stale?: boolean | null;
  source_key_present?: boolean | null;
  missing_reason?: string | null;
}

interface MobileRiskStatusData {
  live_gate?: unknown;
  risk_state?: string | null;
  risk_classification?: string | null;
  kill_switch_active?: boolean | null;
  fail_closed?: boolean | null;
  top_blockers?: string[] | null;
  probation_5_trade_gate?: Record<string, unknown> | null;
  positive_edge_probation_runtime_status?: Record<string, unknown> | null;
  real_trader_readiness?: Record<string, unknown> | null;
  adaptive_hedge_cross_margin?: Record<string, unknown> | null;
  preemptive_edge_control?: Record<string, unknown> | null;
  advanced_indicators?: Record<string, unknown> | null;
  provider_readiness?: Record<string, unknown> | null;
  market_data_freshness?: Record<string, unknown> | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
  staleness_seconds?: number | null;
  freshness_status?: string | null;
}

interface TickerRow {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
  volume_24h?: number | null;
  high_24h?: number | null;
  low_24h?: number | null;
}

interface PaperSummary {
  open_position_count?: number;
  realized_pnl_usd?: number;
  unrealized_pnl_usd?: number;
  total_open_notional?: number;
  paper_signals_seen?: number;
  intents_accepted?: number;
  intents_blocked?: number;
  persistent_accepted_fill_count?: number;
  mark_to_market_live?: boolean;
}

interface PaperFill {
  execution_id: string | null;
  symbol: string;
  side: string;
  fill_price: number | null;
  confidence: number | null;
  strategy_id: string | null;
  market_regime: string | null;
  filled_at: string | null;
  notional_usd: number | null;
}

interface ActiveSignal {
  symbol?: string;
  side?: string;
  confidence?: number | null;
  confidence_calibrated?: number | null;
  confidence_executable_trade?: number | null;
  confidence_selected_action?: number | null;
  confidence_display_label?: string | null;
  confidence_tradeability_block_reasons?: string[] | null;
  paper_exploration_tier?: string | null;
  exploration_tier?: string | null;
  paper_exploration_current_blocker?: string | null;
  paper_exploration_paper_fill_allowed?: boolean | null;
  paper_exploration_risk_controller_decision?: string | null;
  paper_exploration_orchestrator_decision?: string | null;
  paper_exploration_allocator_decision?: string | null;
  expected_net_pnl_usd?: number | null;
  expected_max_loss_usd?: number | null;
  why_not_a_plus?: string[] | null;
  why_not_live_ready?: string[] | null;
  risk_controller_decision?: string | null;
  allocator_decision?: string | null;
  trainer_feedback_status?: string | null;
  target_1?: number | null;
  expected_move_after_cost_bps?: number | null;
  data_coverage_percent?: number | null;
  market_state_integrity_score?: number | null;
  market_age_seconds?: number | null;
  source_freshness?: string | null;
  model_version?: string | null;
  risk_result?: string | null;
  paper_fill_allowed?: boolean | null;
  live_gate?: string | null;
}

interface OrchestratorProposal {
  proposal_id?: string;
  symbol?: string;
  side?: string;
  confidence_calibrated?: number | null;
  expected_move_after_cost_bps?: number | null;
  freshness_seconds?: number | null;
  model_version?: string | null;
  generated_utc?: string | null;
}

interface OrchestratorHeartbeat {
  worker_id?: string;
  predictions_seen?: number;
  proposals_arbitrated?: number;
  classification?: string;
  live_gate?: string;
}

interface RiskProfile {
  profile_id?: string;
  fields?: {
    max_leverage?: number;
    max_notional_per_trade?: number;
    max_open_positions?: number;
    max_daily_loss?: number;
    max_drawdown?: number;
    min_confidence_calibrated?: number;
    min_expected_move_after_cost_bps?: number;
    cooldown_seconds?: number;
  };
}

interface RiskGatewayResult {
  symbol?: string;
  side?: string;
  risk_action?: string;
  risk_reason_code?: string;
  live_blocked?: boolean;
}

interface RiskHeartbeat {
  decisions_processed_total?: number;
  live_gate?: string;
  live_blocked?: boolean;
  classification?: string;
  fail_closed?: boolean;
}

interface HealthSurface {
  name: string;
  endpoint: string;
  status: 'ok' | 'partial' | 'pending' | 'error' | string;
  description: string;
}

// ─── helpers ─────────────────────────────────────────────────────────────────

function f$(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—';
  if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(digits) + 'M';
  if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(digits) + 'K';
  return '$' + n.toFixed(digits);
}
function fPct(n: number | null | undefined, signed = false): string {
  if (n == null) return '—';
  const raw = Math.abs(n) <= 1 ? n * 100 : n;
  const s = raw.toFixed(1) + '%';
  return signed ? (raw >= 0 ? '+' + s : s) : s;
}
function fBpsAsPct(n: number | null | undefined): string {
  if (n == null) return '—';
  const pct = n / 100;
  return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
}
function fAge(sec: number | null | undefined): string {
  if (sec == null) return '—';
  if (sec < 60) return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}
function fTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
function pnlColor(n: number | null | undefined): string {
  if (n == null || n === 0) return 'var(--text-secondary)';
  return n > 0 ? 'var(--buy, #10b981)' : 'var(--sell, #ef4444)';
}
function chgColor(n: number | null | undefined): string {
  if (n == null) return 'var(--text-muted)';
  const v = Math.abs(n) <= 1 ? n * 100 : n;
  return v >= 0 ? 'var(--buy, #10b981)' : 'var(--sell, #ef4444)';
}
function sideColor(s: string | null | undefined): string {
  const lo = (s ?? '').toLowerCase();
  if (lo === 'long' || lo === 'buy') return 'var(--buy, #10b981)';
  if (lo === 'short' || lo === 'sell') return 'var(--sell, #ef4444)';
  return 'var(--text-secondary)';
}
function publicDashboardText(value: string | null | undefined): string {
  const raw = (value ?? '—').trim();
  const upper = raw.toUpperCase();
  if (!raw || raw === '—') return '—';
  if (upper.includes('INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE')) return 'Needs productivity evidence';
  if (upper.includes('DYNAMIC_A_GRADE') && upper.includes('DEPLOYMENT_VALIDATED')) return 'A-grade runtime validated';
  if (upper.includes('NO_DIRECTIONAL_ACTION_EVIDENCE')) return 'Needs directional evidence';
  if (upper.includes('NO_EVALUATED_OUTCOMES') || upper.includes('MISSING_EVALUATED_OUTCOMES')) return 'Needs evaluated outcomes';
  if (upper === 'NO_GO' || upper.startsWith('NO_GO_')) return 'Needs review';
  const cleaned = raw
    .replace(/paper/gi, 'runtime')
    .replace(/no data/gi, 'Connecting stream')
    .replace(/data[_\s-]*coverage/gi, 'data quality')
    .replace(/\bcoverage\b/gi, 'quality')
    .replace(/blocked[_\s-]*human[_\s-]*only/gi, 'approval gated')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (/^[A-Z0-9]{1,4}$/.test(cleaned)) return cleaned;
  if (raw.includes('_')) {
    return cleaned
      .toLowerCase()
      .replace(/\b[a-z0-9]/g, (char) => char.toUpperCase())
      .replace(/\bApi\b/g, 'API')
      .replace(/\bAi\b/g, 'AI')
      .replace(/\bPnl\b/g, 'PnL')
      .replace(/\bUsd\b/g, 'USD');
  }
  return cleaned;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function firstDashboardNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function firstDashboardText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}
function firstDashboardReason(value: string[] | null | undefined, fallback: string): string {
  return value?.find(reason => typeof reason === 'string' && reason.trim()) ?? fallback;
}

function firstDashboardBool(...values: unknown[]): boolean | null {
  for (const value of values) {
    if (typeof value === 'boolean') return value;
  }
  return null;
}

function liveGateText(value: unknown): string {
  const record = asRecord(value);
  const raw = record
    ? firstDashboardText(record.gate, record.label, record.status, record.live_gate)
    : firstDashboardText(value);
  return raw ?? 'blocked_human_only';
}

function flagText(value: unknown): string {
  const bool = firstDashboardBool(value);
  if (bool === true) return 'YES';
  if (bool === false) return 'NO';
  return '—';
}

// ─── WebSocket resource hook ─────────────────────────────────────────────────

function useDashboardStream<T>(url: string, intervalMs: number, unwrapEnvelopeData: boolean | 'contract' = true): {
  data: T | null;
  envelope: ValidatedDataEnvelope<T>;
  loading: boolean;
  error: string | null;
} {
  const { envelope, loading, error } = useRealtimeResource<T>({
    url,
    source: `websocket:${url}`,
    source_type: 'websocket',
    pollIntervalMs: intervalMs,
    staleThresholdMs: intervalMs * 3,
    mode: 'read_only',
    initialFetch: true,
    httpFallback: true,
    unwrapEnvelopeData,
  });
  return { data: envelope.data ?? null, envelope, loading, error };
}

function useBrowserStatus(): { online: boolean; visibility: DocumentVisibilityState } {
  const readStatus = () => ({
    online: typeof navigator === 'undefined' ? true : navigator.onLine,
    visibility: typeof document === 'undefined' ? 'visible' as DocumentVisibilityState : document.visibilityState,
  });
  const [status, setStatus] = useState(readStatus);

  useEffect(() => {
    const update = () => setStatus(readStatus());
    window.addEventListener('online', update);
    window.addEventListener('offline', update);
    document.addEventListener('visibilitychange', update);
    return () => {
      window.removeEventListener('online', update);
      window.removeEventListener('offline', update);
      document.removeEventListener('visibilitychange', update);
    };
  }, []);

  return status;
}

// ─── sub-components ───────────────────────────────────────────────────────────

function Panel({ children, style }: { children: ReactNode; style?: CSSProperties }): JSX.Element {
  return (
    <div className="nervyx-dashboard-panel" style={style}>
      {children}
    </div>
  );
}

function PanelHead({ title, sub, to, badge, badgeTone }: {
  title: string; sub?: string; to?: string; badge?: string; badgeTone?: 'ok' | 'warn' | 'block';
}): JSX.Element {
  const badgeColors = {
    ok: { bg: 'color-mix(in oklch, var(--buy,#10b981) 15%, transparent)', color: 'var(--buy,#10b981)' },
    warn: { bg: 'color-mix(in oklch, #f59e0b 15%, transparent)', color: '#f59e0b' },
    block: { bg: 'color-mix(in oklch, var(--sell,#ef4444) 15%, transparent)', color: 'var(--sell,#ef4444)' },
  };
  const bc = badgeTone ? badgeColors[badgeTone] : null;
  return (
    <div className="nervyx-dashboard-panel__head">
      <div>
        <span className="nervyx-dashboard-panel__title">{title}</span>
        {sub && <span className="nervyx-dashboard-panel__subtitle">{sub}</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {badge && bc && (
          <span className="nervyx-dashboard-pill" style={{ background: bc.bg, color: bc.color }}>{publicDashboardText(badge)}</span>
        )}
        {to && <Link to={to} className="nervyx-dashboard-link">→</Link>}
      </div>
    </div>
  );
}

function KPITile({ label, value, metric, sub, valueColor, to, emptyText }: {
  label: string;
  value?: string;
  metric?: CanonicalMetric;
  sub?: string;
  valueColor?: string;
  to?: string;
  emptyText?: string;
}): JSX.Element {
  const inner = (
    <div className="nervyx-dashboard-kpi" data-clickable={to ? 'true' : 'false'}>
      <span className="nervyx-dashboard-kpi__label">{label}</span>
      <span className="nervyx-dashboard-kpi__value" style={{ color: valueColor ?? 'var(--text-primary)' }}>
        {metric ? <CanonicalMetricValue metric={metric} emptyText={emptyText} /> : value}
      </span>
      {sub && <span className="nervyx-dashboard-kpi__sub">{sub}</span>}
    </div>
  );
  return to ? <Link to={to} style={{ display: 'block', minWidth: 0, textDecoration: 'none' }}>{inner}</Link> : inner;
}

function ConfBar({ pct, color = 'var(--accent,#3b82f6)' }: { pct: number; color?: string }): JSX.Element {
  return (
    <div style={{ height: 4, background: 'var(--bg-elevated)', borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${Math.min(100, pct * 100)}%`, background: color, borderRadius: 2, transition: 'width 0.4s' }} />
    </div>
  );
}

// ─── Top Status Bar ───────────────────────────────────────────────────────────

function StatusBar({ orch, risk }: {
  orch: { heartbeat?: OrchestratorHeartbeat } | null;
  risk: { heartbeat?: RiskHeartbeat } | null;
}): JSX.Element {
  const pills: Array<{ label: string; value: string; tone: 'ok' | 'warn' | 'block' }> = [
    { label: 'Execution', value: 'RESTRICTED', tone: 'warn' },
    { label: 'Automation', value: orch?.heartbeat ? 'ACTIVE' : 'UNKNOWN', tone: orch?.heartbeat ? 'ok' : 'warn' },
    {
      label: 'Orchestrator',
      value: orch?.heartbeat?.classification?.includes('OK') ? 'OK' : '—',
      tone: orch?.heartbeat?.classification?.includes('OK') ? 'ok' : 'warn',
    },
    {
      label: 'Risk Gateway',
      value: risk?.heartbeat?.classification?.includes('OK') ? 'OK' : '—',
      tone: risk?.heartbeat?.classification?.includes('OK') ? 'ok' : 'warn',
    },
    {
      label: 'Fail Closed',
      value: risk?.heartbeat?.fail_closed ? 'YES' : '—',
      tone: risk?.heartbeat?.fail_closed ? 'ok' : 'warn',
    },
  ];
  const colors = {
    ok: { bg: 'color-mix(in oklch,var(--buy,#10b981) 13%,transparent)', color: 'var(--buy,#10b981)', border: 'color-mix(in oklch,var(--buy,#10b981) 30%,transparent)' },
    warn: { bg: 'color-mix(in oklch,#f59e0b 13%,transparent)', color: '#f59e0b', border: 'color-mix(in oklch,#f59e0b 30%,transparent)' },
    block: { bg: 'color-mix(in oklch,var(--sell,#ef4444) 13%,transparent)', color: 'var(--sell,#ef4444)', border: 'color-mix(in oklch,var(--sell,#ef4444) 30%,transparent)' },
  };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {pills.map(p => {
        const c = colors[p.tone];
        return (
          <span key={p.label} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 999, background: c.bg, border: `1px solid ${c.border}` }}>
            <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{p.label}</span>
            <span style={{ fontSize: 10, fontWeight: 700, color: c.color, fontFamily: 'var(--font-mono)' }}>{p.value}</span>
          </span>
        );
      })}
    </div>
  );
}

function streamTone(env: ValidatedDataEnvelope<unknown> | null | undefined, loading: boolean, error?: string | null): 'ok' | 'warn' | 'block' {
  if (error || env?.freshness_status === 'offline' || env?.freshness_status === 'unavailable') return 'block';
  if (loading || env?.freshness_status === 'delayed' || env?.freshness_status === 'stale') return 'warn';
  return env?.data ? 'ok' : 'warn';
}

function streamLabel(env: ValidatedDataEnvelope<unknown> | null | undefined, loading: boolean, error?: string | null): string {
  if (error) return 'OFFLINE';
  if (loading && !env?.data) return 'Pending';
  if (env?.freshness_status === 'fresh') return 'LIVE';
  if (env?.freshness_status === 'delayed') return 'DELAYED';
  if (env?.freshness_status === 'stale') return 'STALE';
  return env?.data ? 'CURRENT' : 'WAITING';
}

function DashboardStreamStatus({ items, browser }: {
  items: Array<{ label: string; envelope: ValidatedDataEnvelope<unknown> | null; loading: boolean; error?: string | null }>;
  browser: { online: boolean; visibility: DocumentVisibilityState };
}): JSX.Element {
  const browserTone = browser.online && browser.visibility === 'visible' ? 'ok' : browser.online ? 'warn' : 'block';
  const tones = {
    ok: 'solid-ok',
    warn: 'solid-warn',
    block: 'solid-block',
  };
  return (
    <Panel>
      <div className="nervyx-dashboard-streams" data-testid="dashboard-websocket-status">
        <span className={`chip ${tones[browserTone]}`}>
          Browser {browser.online ? browser.visibility.toUpperCase() : 'OFFLINE'}
        </span>
        {items.map((item) => {
          const tone = streamTone(item.envelope, item.loading, item.error);
          return (
            <span className={`chip ${tones[tone]}`} key={item.label}>
              {item.label} {streamLabel(item.envelope, item.loading, item.error)}
            </span>
          );
        })}
      </div>
    </Panel>
  );
}

function ControlCenterMetric({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
}): JSX.Element {
  return (
    <div style={{ minWidth: 0 }}>
      <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span style={{ display: 'block', fontSize: 15, fontWeight: 800, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', overflowWrap: 'anywhere' }}>{value}</span>
      {sub ? <span style={{ display: 'block', marginTop: 2, fontSize: 10, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>{sub}</span> : null}
    </div>
  );
}

function DashboardControlCenterTruthPanel({
  portfolio,
  portfolioEnvelope,
  liveCanaryContract,
  liveCanaryEnvelope,
  aPlusContract,
  aPlusEnvelope,
  riskTruth,
  riskEnvelope,
  exchangeAccounts,
}: {
  portfolio: PortfolioData | null;
  portfolioEnvelope: ValidatedDataEnvelope<PortfolioData>;
  liveCanaryContract: ReadonlyContract<LiveCanaryStatusData> | null;
  liveCanaryEnvelope: ValidatedDataEnvelope<ReadonlyContract<LiveCanaryStatusData>>;
  aPlusContract: ReadonlyContract<APlusInventoryData> | null;
  aPlusEnvelope: ValidatedDataEnvelope<ReadonlyContract<APlusInventoryData>>;
  riskTruth: MobileRiskStatusData | null;
  riskEnvelope: ValidatedDataEnvelope<MobileRiskStatusData>;
  exchangeAccounts: unknown[];
}): JSX.Element {
  const liveCanary = liveCanaryContract?.data ?? null;
  const aPlus = aPlusContract?.data ?? null;
  const statusPayload = asRecord(liveCanary?.status_payload) ?? {};
  const noMutationFlags = asRecord(liveCanary?.no_mutation_flags) ?? {};
  const hedge = asRecord(riskTruth?.adaptive_hedge_cross_margin) ?? {};
  const preemptive = asRecord(riskTruth?.preemptive_edge_control) ?? {};
  const preemptiveAdvanced = asRecord(preemptive.advanced_indicators) ?? {};
  const providerReadiness = asRecord(riskTruth?.provider_readiness) ?? {};
  const realReadiness = asRecord(riskTruth?.real_trader_readiness) ?? {};
  const probation = asRecord(riskTruth?.probation_5_trade_gate) ?? {};
  const probationRuntime = asRecord(riskTruth?.positive_edge_probation_runtime_status) ?? {};
  const marketFreshness = asRecord(riskTruth?.market_data_freshness) ?? {};

  const liveGate = liveGateText(riskTruth?.live_gate ?? liveCanaryContract?.live_gate ?? statusPayload.live_gate);
  const liveBlocked = liveGate.toLowerCase().includes('blocked') || liveGate.toLowerCase().includes('operator gated');
  const placesRealOrder = firstDashboardBool(
    riskTruth?.places_real_order,
    liveCanaryContract?.places_real_order,
    statusPayload.places_real_order,
    noMutationFlags.places_real_order,
  ) === true;
  const routesToLive = firstDashboardBool(
    riskTruth?.routes_to_live,
    liveCanaryContract?.routes_to_live,
    statusPayload.routes_to_live,
  ) === true;
  const orderMutated = [
    statusPayload.real_order_attempted,
    statusPayload.real_order_submitted,
    statusPayload.test_order_submitted,
    statusPayload.leverage_changed,
    statusPayload.margin_mode_changed,
    noMutationFlags.real_order_attempted,
    noMutationFlags.real_order_submitted,
    noMutationFlags.test_order_submitted,
    noMutationFlags.leverage_changed,
    noMutationFlags.margin_mode_changed,
  ].some((value) => value === true);

  const blockers = Array.isArray(statusPayload.fail_blockers)
    ? statusPayload.fail_blockers.map(String)
    : Array.isArray(riskTruth?.top_blockers)
      ? riskTruth.top_blockers
      : [];
  const canaryBlocker = firstDashboardText(liveCanary?.why_none, blockers[0], statusPayload.go_no_go, riskTruth?.risk_state) ?? 'No current canary candidate';
  const paperGate = firstDashboardText(
    probationRuntime.status,
    probation.status,
    preemptive.positive_edge_probation_status,
    riskTruth?.risk_state,
  ) ?? 'Probation gate unavailable';
  const signedReadConfigured = exchangeAccounts.some((account) => {
    const row = asRecord(account);
    const credential = asRecord(row?.credential_status);
    return row?.read_only === true || credential?.configured === true || credential?.status === 'configured';
  });
  const signedRead = signedReadConfigured
    ? 'SIGNED READ PRESENT'
    : firstDashboardBool(realReadiness.live_ready) === true
      ? 'REAL READINESS PRESENT'
      : 'SIGNED READ PENDING';
  const equity = firstDashboardNumber(portfolio?.paper_equity_usd, portfolio?.equity, portfolio?.paper_equity, portfolio?.paper_balance);
  const totalPnl = firstDashboardNumber(portfolio?.paper_total_pnl_usd, portfolio?.total_pnl_usd);
  const liquidationBuffer = firstDashboardNumber(hedge.portfolio_liquidation_buffer_usd, hedge.cross_margin_available_buffer_usd);
  const hedgeState = firstDashboardText(hedge.hedge_state, hedge.status) ?? 'Hedge state unavailable';
  const topLevelAdvanced = asRecord(riskTruth?.advanced_indicators) ?? {};
  const squeezeGuard = firstDashboardBool(
    preemptiveAdvanced.sweep_risk_can_block_or_reduce,
    preemptiveAdvanced.squeeze_risk_can_block_or_reduce,
    topLevelAdvanced.sweep_risk_can_block_or_reduce,
  );
  const providerSummary = [
    ['CoinGlass', providerReadiness.coinglass_dashboard_color ?? providerReadiness.coinglass_status],
    ['Moralis', providerReadiness.moralis_dashboard_color ?? providerReadiness.moralis_status],
  ]
    .map(([name, value]) => `${name}:${publicDashboardText(firstDashboardText(value) ?? '—')}`)
    .join(' · ');
  const stalenessValues = [
    firstDashboardNumber(portfolio?.staleness_seconds),
    firstDashboardNumber(liveCanaryContract?.staleness_seconds),
    firstDashboardNumber(aPlusContract?.staleness_seconds),
    firstDashboardNumber(riskTruth?.staleness_seconds),
  ].filter((value): value is number => value !== null);
  const maxStaleness = stalenessValues.length ? Math.max(...stalenessValues) : null;
  const freshness = [
    portfolioEnvelope.freshness_status,
    liveCanaryContract?.freshness_status ?? liveCanaryEnvelope.freshness_status,
    aPlusContract?.freshness_status ?? aPlusEnvelope.freshness_status,
    riskTruth?.freshness_status ?? riskEnvelope.freshness_status,
    firstDashboardText(marketFreshness.freshness_state),
  ].filter(Boolean).join(' · ');

  return (
    <Panel>
      <section data-testid="dashboard-control-center-truth" style={{ padding: '14px 16px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 14 }}>
          <div>
            <span style={{ display: 'block', fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Runtime Control Center Truth</span>
            <h2 style={{ margin: '3px 0 0', fontSize: 18, color: 'var(--text-primary)' }}>Live status: {liveBlocked || !placesRealOrder ? 'LIVE BLOCKED' : 'DRY RUN REVIEW REQUIRED'}</h2>
          </div>
          <span className="nervyx-dashboard-pill" style={{
            background: routesToLive || placesRealOrder || orderMutated ? 'color-mix(in oklch,var(--sell,#ef4444) 15%,transparent)' : 'color-mix(in oklch,#f59e0b 15%,transparent)',
            color: routesToLive || placesRealOrder || orderMutated ? 'var(--sell,#ef4444)' : '#f59e0b',
            border: '1px solid color-mix(in oklch,currentColor 28%,transparent)',
          }}>
            {routesToLive || placesRealOrder || orderMutated ? 'MUTATION RISK' : 'NO ORDER / TEST / LEVERAGE / MARGIN MUTATION'}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12 }}>
          <ControlCenterMetric label="A+ candidates" value={String(aPlus?.a_plus_candidates ?? 0)} sub={`${aPlus?.evaluated_candidates ?? 0} evaluated · ${aPlus?.live_ready_rows ?? 0} live-ready rows`} color={(aPlus?.a_plus_candidates ?? 0) > 0 ? 'var(--buy,#10b981)' : '#f59e0b'} />
          <ControlCenterMetric label="Live canary blocker" value={publicDashboardText(canaryBlocker)} sub={firstDashboardText(statusPayload.go_no_go) ?? '/api/v2/live-canary/status'} color="var(--sell,#ef4444)" />
          <ControlCenterMetric label="Paper/probation gate" value={publicDashboardText(paperGate)} sub={firstDashboardText(probation.source, aPlus?.paper_session_id) ?? '/api/v2/a-plus/inventory'} color="#f59e0b" />
          <ControlCenterMetric label="Signed-read status" value={signedRead} sub="Exchange metadata only; live remains blocked" color={signedReadConfigured ? 'var(--buy,#10b981)' : '#f59e0b'} />
          <ControlCenterMetric label="paper_equity_usd" value={f$(equity)} sub={portfolio?.pnl_source_key ?? portfolioEnvelope.source} />
          <ControlCenterMetric label="paper_total_pnl_usd" value={f$(totalPnl)} sub={portfolio?.pnl_source_route ?? '/api/v2/portfolio'} color={pnlColor(totalPnl)} />
          <ControlCenterMetric label="Liquidation buffer" value={f$(liquidationBuffer)} sub="portfolio_liquidation_buffer_usd" color="var(--buy,#10b981)" />
          <ControlCenterMetric label="Hedge status" value={publicDashboardText(hedgeState)} sub={`hedge_required_score=${firstDashboardNumber(providerReadiness.confluence_hedge_required_score)?.toFixed(2) ?? '—'}`} />
          <ControlCenterMetric label="Squeeze risk" value={squeezeGuard === true ? 'SWEEP GUARD ACTIVE' : squeezeGuard === false ? 'No active sweep guard' : 'Squeeze guard unavailable'} sub="sweep risk can block or reduce" color={squeezeGuard === true ? '#f59e0b' : 'var(--text-primary)'} />
          <ControlCenterMetric label="Data freshness" value={maxStaleness !== null ? `${Math.round(maxStaleness)}s max` : 'fresh'} sub={freshness || 'freshness pending'} />
        </div>
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          <span>live_gate={publicDashboardText(liveGate)}</span>
          <span>places_real_order={flagText(placesRealOrder)}</span>
          <span>routes_to_live={flagText(routesToLive)}</span>
          <span>providers={providerSummary}</span>
        </div>
      </section>
    </Panel>
  );
}

// ─── Active Signal panel ──────────────────────────────────────────────────────

function ActiveSignalPanel({
  signal,
  signalIdMetric,
  signalConfidenceMetric,
}: {
  signal: ActiveSignal | null;
  signalIdMetric: CanonicalMetric;
  signalConfidenceMetric: CanonicalMetric;
}): JSX.Element {
  if (!signal) {
    return (
      <Panel style={{ padding: 16, minHeight: 180 }}>
        <PanelHead title="Active Signal" to="/signals" />
        <div style={{ padding: '16px 0 0', fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', display: 'grid', gap: 8 }}>
          <div>
            <span style={{ display: 'block', fontSize: 10, textTransform: 'uppercase' }}>Signal ID</span>
            <CanonicalMetricValue metric={signalIdMetric} />
          </div>
          <div>
            <span style={{ display: 'block', fontSize: 10, textTransform: 'uppercase' }}>Executable Confidence</span>
            <CanonicalMetricValue metric={signalConfidenceMetric} />
          </div>
        </div>
      </Panel>
    );
  }
  const selectedConf = signal.confidence_selected_action ?? signal.confidence_calibrated ?? signal.confidence ?? null;
  const executableConf = signal.confidence_executable_trade ?? null;
  const confidenceLabel = signal.confidence_display_label ?? 'Unproven confidence';
  const explorationTier = signal.paper_exploration_tier ?? signal.exploration_tier ?? null;
  const explorationBlocker = signal.paper_exploration_current_blocker ?? 'not above floor';
  const paperFillTruth = signal.paper_exploration_paper_fill_allowed === true
    ? 'PAPER_FILL_ALLOWED'
    : signal.paper_exploration_paper_fill_allowed === false
      ? 'BLOCKED'
      : (signal.paper_fill_allowed === true ? 'PAPER_FILL_ALLOWED' : signal.paper_fill_allowed === false ? 'BLOCKED' : 'PENDING');
  const side = signal.side ?? '—';
  const sc = sideColor(side);
  const freshBadge = signal.source_freshness === 'CURRENT' ? 'LIVE' : signal.source_freshness === 'STALE' ? 'STALE' : null;
  const freshTone: 'ok' | 'warn' | 'block' = signal.source_freshness === 'CURRENT' ? 'ok' : 'warn';

  return (
    <Panel>
      <PanelHead title="Active Signal" to="/signals" badge={freshBadge ?? undefined} badgeTone={freshTone} />
      <div style={{ padding: '12px 16px 16px' }}>
        {/* Symbol + direction */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{signal.symbol ?? '—'}</span>
          <span style={{ fontSize: 14, fontWeight: 700, color: sc, fontFamily: 'var(--font-mono)' }}>{side.toUpperCase()}</span>
          {signal.market_age_seconds != null && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>{fAge(signal.market_age_seconds)}</span>
          )}
        </div>

        {/* Confidence bar */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{confidenceLabel}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: executableConf != null && executableConf >= 0.66 ? 'var(--buy,#10b981)' : '#f59e0b', fontFamily: 'var(--font-mono)' }}>
              {executableConf != null ? fPct(executableConf) : '—'}
            </span>
          </div>
          <ConfBar pct={executableConf ?? 0} color={executableConf != null && executableConf >= 0.66 ? 'var(--buy,#10b981)' : '#f59e0b'} />
          <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            selected-action confidence {fPct(selectedConf)}
          </div>
        </div>

        {/* Key metrics grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
          {[
            ['Target', signal.target_1 != null ? '$' + signal.target_1.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'],
            ['Exp. Move', fBpsAsPct(signal.expected_move_after_cost_bps)],
            ['Confidence Type', confidenceLabel],
            ['Paper Tier', explorationTier ?? 'NONE'],
            ['Exploration Blocker', explorationBlocker],
            ['Paper Fill', paperFillTruth],
            ['Expected Net', f$(signal.expected_net_pnl_usd)],
            ['Max Loss', f$(signal.expected_max_loss_usd)],
            ['Why Not A+', firstDashboardReason(signal.why_not_a_plus, 'A+ evidence not matured')],
            ['Why Not Live', firstDashboardReason(signal.why_not_live_ready, 'blocked_human_only')],
            ['Data Quality', signal.data_coverage_percent != null ? signal.data_coverage_percent.toFixed(1) + '%' : '—'],
            ['State Score', signal.market_state_integrity_score != null ? signal.market_state_integrity_score.toFixed(1) + '%' : '—'],
            ['Risk Result', signal.paper_exploration_risk_controller_decision ?? signal.risk_controller_decision ?? signal.risk_result ?? '—'],
            ['Orchestrator', signal.paper_exploration_orchestrator_decision ?? '—'],
            ['Allocator', signal.paper_exploration_allocator_decision ?? signal.allocator_decision ?? '—'],
            ['Trainer', signal.trainer_feedback_status ?? '—'],
            ['Fill Allowed', signal.paper_fill_allowed ? 'YES' : 'NO'],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border)', paddingBottom: 3 }}>
              <span style={{ color: 'var(--text-muted)' }}>{k}</span>
              <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{publicDashboardText(String(v))}</span>
            </div>
          ))}
        </div>

        {/* Model version */}
        {signal.model_version && (
          <div style={{ marginTop: 8, fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            Model: {signal.model_version}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Orchestrator Feed ────────────────────────────────────────────────────────

function OrchestratorPanel({ proposals, heartbeat }: {
  proposals: OrchestratorProposal[];
  heartbeat: OrchestratorHeartbeat | null;
}): JSX.Element {
  return (
    <Panel>
      <PanelHead
        title="Orchestrator"
        sub={heartbeat ? `${heartbeat.predictions_seen ?? 0} predictions seen` : undefined}
        to="/trade"
        badge={heartbeat?.classification?.includes('OK') ? 'LIVE' : undefined}
        badgeTone="ok"
      />
      <div style={{ padding: '10px 16px 14px' }}>
        {proposals.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>No current proposals</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {proposals.slice(0, 6).map((p, i) => {
              const sc = sideColor(p.side);
              const conf = p.confidence_calibrated ?? null;
              return (
                <div key={p.proposal_id ?? i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                  <span style={{ fontWeight: 700, color: 'var(--text-primary)', minWidth: 90 }}>{p.symbol ?? '—'}</span>
                  <span style={{ fontWeight: 700, color: sc, minWidth: 38 }}>{(p.side ?? '').toUpperCase()}</span>
                  <span style={{ color: conf != null && conf >= 0.66 ? 'var(--buy,#10b981)' : '#f59e0b', minWidth: 44 }}>{fPct(conf)}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 10, flex: 1, textAlign: 'right' }}>
                    {p.freshness_seconds != null ? p.freshness_seconds.toFixed(0) + 's' : '—'}
                  </span>
                </div>
              );
            })}
          </div>
        )}
        {heartbeat && (
          <div style={{ marginTop: 10, paddingTop: 8, borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', display: 'flex', justifyContent: 'space-between' }}>
            <span>{heartbeat.proposals_arbitrated ?? 0} arbitrated</span>
          <span style={{ color: 'var(--buy,#10b981)' }}>Realtime data</span>
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── Risk Profile Panel ───────────────────────────────────────────────────────

function RiskPanel({ profile, latestResult, heartbeat }: {
  profile: RiskProfile | null;
  latestResult: RiskGatewayResult | null;
  heartbeat: RiskHeartbeat | null;
}): JSX.Element {
  const fields = profile?.fields;
  return (
    <Panel>
      <PanelHead
        title="Risk Gateway"
        sub={profile?.profile_id ?? undefined}
        to="/admin/risk"
        badge={heartbeat?.classification?.includes('OK') ? 'OK' : undefined}
        badgeTone="ok"
      />
      <div style={{ padding: '10px 16px 14px', fontSize: 11, fontFamily: 'var(--font-mono)', display: 'flex', flexDirection: 'column', gap: 5 }}>
        {fields ? (
          <>
            {[
              ['Max Leverage', fields.max_leverage != null ? fields.max_leverage + 'x' : '—'],
              ['Max Notional/Trade', fields.max_notional_per_trade != null ? '$' + fields.max_notional_per_trade.toFixed(2) : '—'],
              ['Max Open Positions', fields.max_open_positions != null ? String(fields.max_open_positions) : '—'],
              ['Min Confidence', fields.min_confidence_calibrated != null ? fPct(fields.min_confidence_calibrated) : '—'],
              ['Min Move', fields.min_expected_move_after_cost_bps != null ? fBpsAsPct(fields.min_expected_move_after_cost_bps) : '—'],
              ['Max Daily Loss', fields.max_daily_loss != null ? fPct(fields.max_daily_loss / 100) : '—'],
              ['Max Drawdown', fields.max_drawdown != null ? fPct(fields.max_drawdown / 100) : '—'],
              ['Cooldown', fields.cooldown_seconds != null ? Math.round(fields.cooldown_seconds / 60) + 'm' : '—'],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--border)', paddingBottom: 3 }}>
                <span style={{ color: 'var(--text-muted)' }}>{k}</span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{v}</span>
              </div>
            ))}
          </>
        ) : (
          <span style={{ color: 'var(--text-muted)' }}>Loading risk profile…</span>
        )}
        {latestResult && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--border)', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            <span style={{ color: 'var(--text-muted)' }}>Last decision:</span>
            <span style={{ fontWeight: 700, color: sideColor(latestResult.side) }}>{latestResult.symbol ?? '—'} {(latestResult.side ?? '').toUpperCase()}</span>
            <span style={{ color: latestResult.risk_action === 'allow' ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)' }}>→ {latestResult.risk_action?.toUpperCase() ?? '—'}</span>
          </div>
        )}
        {heartbeat && (
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
            {heartbeat.decisions_processed_total ?? 0} decisions · Fail-closed: {heartbeat.fail_closed ? 'YES' : 'NO'}
          </div>
        )}
      </div>
    </Panel>
  );
}

// ─── 1000x Trajectory Panel ───────────────────────────────────────────────────

function fUsdFull(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const sign = n < 0 ? '-' : '';
  return sign + '$' + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Rates from the tracker are ALREADY in percent units (e.g. 7.978 = 7.978%/day,
// 0.0401 = 0.0401%/day) — never re-scale them the way fPct does.
function fRatePct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const digits = Math.abs(n) < 1 ? 3 : 2;
  return n.toFixed(digits) + '%';
}

function fMultiple(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n.toFixed(Math.abs(n) < 10 ? 4 : 1) + 'x';
}

const GOAL_STALE_AFTER_SECONDS = 900;

function GoalTrajectoryPanel({ contract }: {
  contract: ReadonlyContract<GoalTrajectory1000xData> | null;
}): JSX.Element {
  const goal = contract?.data ?? null;
  const hasPayload = goal != null && goal.source_key_present !== false;

  // Honest freshness: recompute age from generated_utc at render time,
  // fall back to the server-computed age_seconds.
  const parsedGenerated = goal?.generated_utc ? Date.parse(goal.generated_utc) : NaN;
  const ageSec = Number.isFinite(parsedGenerated)
    ? Math.max(0, (Date.now() - parsedGenerated) / 1000)
    : (goal?.age_seconds ?? null);
  const staleAfter = goal?.stale_after_seconds ?? GOAL_STALE_AFTER_SECONDS;
  const isStale = !hasPayload || ageSec == null || ageSec > staleAfter;
  const amber = '#f59e0b';

  const onTrack = goal?.on_track === true;
  const badge = !hasPayload ? 'NO DATA' : (isStale ? 'STALE' : (onTrack ? 'ON TRACK' : 'OFF TRACK'));
  const badgeTone: 'ok' | 'warn' | 'block' = !hasPayload || isStale ? 'warn' : (onTrack ? 'ok' : 'block');

  const gap = goal?.equity_gap_vs_required_usd ?? null;
  const gapColor = gap == null ? 'var(--text-muted)' : (gap >= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)');
  const actualRate = goal?.actual_daily_rate_pct ?? null;
  const requiredRate = goal?.required_daily_rate_pct ?? null;
  const rateBehind = actualRate != null && requiredRate != null && actualRate < requiredRate;
  const constraint = goal?.binding_constraint ?? null;
  const constraintTone = onTrack && !isStale ? amber : 'var(--sell,#ef4444)';

  const tiles: Array<{ label: string; value: string; valueColor?: string; sub?: string; subColor?: string }> = [
    {
      label: 'Equity Now',
      value: fUsdFull(goal?.equity_usd),
      sub: `start ${fUsdFull(goal?.starting_equity_usd)}`,
    },
    {
      label: 'Required Today',
      value: fUsdFull(goal?.required_equity_today_usd),
      sub: `gap ${fUsdFull(gap)}`,
      subColor: gapColor,
    },
    {
      label: 'Multiple',
      value: fMultiple(goal?.multiple_now),
      sub: `target ${goal?.target_multiple != null ? goal.target_multiple.toFixed(0) : '1000'}x`,
    },
    {
      label: 'Daily Rate',
      value: fRatePct(actualRate),
      valueColor: rateBehind ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)',
      sub: `req ${fRatePct(requiredRate)}/day`,
    },
    {
      label: 'Days',
      value: `${goal?.days_elapsed != null ? goal.days_elapsed.toFixed(1) : '—'} / ${goal?.target_days != null ? goal.target_days.toFixed(0) : '90'}`,
      sub: goal?.days_to_target_at_required_rate_from_here != null
        ? `${goal.days_to_target_at_required_rate_from_here.toFixed(0)}d left at req rate`
        : undefined,
    },
    {
      label: 'Trades',
      value: `${goal?.closed_trade_count ?? '—'}`,
      sub: `${goal?.open_position_count ?? '—'} open`,
    },
  ];

  return (
    <div data-testid="dashboard-goal-trajectory-panel">
    <Panel>
      <PanelHead
        title="1000x Trajectory"
        sub="Research objective, not a promise · paper-only"
        badge={badge}
        badgeTone={badgeTone}
      />
      {!hasPayload ? (
        <div style={{ padding: '12px 16px 14px', fontSize: 12, color: 'var(--text-muted)' }}>
          Trajectory telemetry unavailable — {publicDashboardText(goal?.missing_reason ?? 'tracker key missing or expired')}.
        </div>
      ) : (
        <>
          {/* BINDING CONSTRAINT — the single thing currently blocking the trajectory */}
          <div style={{
            margin: '10px 16px 0',
            padding: '10px 12px',
            borderRadius: 8,
            border: `1px solid color-mix(in oklch, ${constraintTone} 45%, transparent)`,
            background: `color-mix(in oklch, ${constraintTone} 8%, transparent)`,
          }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>
              Binding Constraint
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: constraintTone }}>
              {constraint?.constraint ? publicDashboardText(constraint.constraint) : 'No binding constraint reported'}
            </div>
            {constraint?.detail && (
              <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 3 }}>
                {publicDashboardText(constraint.detail)}
              </div>
            )}
          </div>

          {/* KPI row */}
          <div style={{ display: 'flex', gap: 18, padding: '10px 16px 4px', fontSize: 11, fontFamily: 'var(--font-mono)', flexWrap: 'wrap' }}>
            {tiles.map(t => (
              <div key={t.label} style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 88 }}>
                <span style={{ color: 'var(--text-muted)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{t.label}</span>
                <span style={{ color: t.valueColor ?? 'var(--text-primary)', fontWeight: 700, fontSize: 13 }}>{t.value}</span>
                {t.sub && <span style={{ color: t.subColor ?? 'var(--text-muted)', fontSize: 10 }}>{t.sub}</span>}
              </div>
            ))}
          </div>

          {/* Freshness footer */}
          <div style={{ padding: '8px 16px 12px', marginTop: 4, borderTop: '1px solid var(--border)', fontSize: 10, fontFamily: 'var(--font-mono)', display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ color: isStale ? amber : 'var(--text-muted)', fontWeight: isStale ? 700 : 400 }}>
              {isStale ? 'STALE · ' : ''}Generated {fTime(goal?.generated_utc)} · {fAge(ageSec)}
            </span>
            <span style={{ color: 'var(--text-muted)' }}>
              Session {goal?.paper_session_id ?? '—'}
            </span>
          </div>
        </>
      )}
    </Panel>
    </div>
  );
}

// ─── Execution Fills Table ────────────────────────────────────────────────────

function PaperFillsPanel({ fills, summary }: { fills: PaperFill[]; summary: PaperSummary | null }): JSX.Element {
  const longs = fills.filter(f => f.side === 'LONG').length;
  const shorts = fills.filter(f => f.side === 'SHORT').length;
  const confs = fills.map(f => f.confidence).filter((c): c is number => c != null);
  const avgConf = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null;

  return (
    <Panel>
      <PanelHead
        title="Execution Fills"
        sub={`${fills.length} total · L:${longs} / S:${shorts} · avg conf ${fPct(avgConf)}`}
        to="/executions"
      />
      {/* Summary row */}
      {summary && (
        <div style={{ display: 'flex', gap: 16, padding: '8px 16px', borderBottom: '1px solid var(--border)', fontSize: 11, fontFamily: 'var(--font-mono)', flexWrap: 'wrap' }}>
          {[
            ['Positions', String(summary.open_position_count ?? 0)],
            ['Notional', f$(summary.total_open_notional)],
            ['Signals Seen', String(summary.paper_signals_seen ?? 0)],
            ['Accepted', String(summary.persistent_accepted_fill_count ?? 0)],
            ['Blocked', String(summary.intents_blocked ?? 0)],
          ].map(([k, v]) => (
            <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <span style={{ color: 'var(--text-muted)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{k}</span>
              <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{v}</span>
            </div>
          ))}
        </div>
      )}
      {/* Table */}
      <div style={{ overflowX: 'hidden', maxWidth: '100%' }}>
        <table style={{ width: '100%', tableLayout: 'fixed', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Time', 'Symbol', 'Side', 'Price', 'Notional', 'Conf', 'Regime'].map(h => (
                <th key={h} style={{ padding: '6px 6px', textAlign: 'left', fontWeight: 600, color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fills.slice(0, 20).map((f, i) => (
              <tr key={f.execution_id ?? i} style={{ borderBottom: '1px solid var(--border)', opacity: 0.9 }}>
                <td style={{ padding: '5px 6px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{fTime(f.filled_at)}</td>
                <td style={{ padding: '5px 6px', fontWeight: 700, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.symbol}</td>
                <td style={{ padding: '5px 6px', fontWeight: 700, color: sideColor(f.side), overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.side}</td>
                <td style={{ padding: '5px 6px', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.fill_price != null ? f.fill_price.toLocaleString('en-US', { maximumFractionDigits: 6 }) : '—'}</td>
                <td style={{ padding: '5px 6px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f$(f.notional_usd)}</td>
                <td style={{ padding: '5px 6px', color: f.confidence != null && f.confidence >= 0.66 ? 'var(--buy,#10b981)' : '#f59e0b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{fPct(f.confidence)}</td>
                <td style={{ padding: '5px 6px', color: 'var(--text-muted)', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{publicDashboardText(f.market_regime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {fills.length === 0 && (
          <div style={{ padding: '16px 16px', color: 'var(--text-muted)', fontSize: 12 }}>No fills yet.</div>
        )}
      </div>
      {fills.length > 20 && (
        <div style={{ padding: '8px 16px', fontSize: 10, color: 'var(--text-muted)', borderTop: '1px solid var(--border)' }}>
          Showing 20 of {fills.length} fills · <Link to="/executions" style={{ color: 'var(--accent,#3b82f6)', textDecoration: 'none' }}>View all →</Link>
        </div>
      )}
    </Panel>
  );
}

// ─── Market Pulse Panel ───────────────────────────────────────────────────────

const ANCHOR_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT'];

function MarketPulsePanel({ tickers }: { tickers: TickerRow[] }): JSX.Element {
  const top = ANCHOR_SYMBOLS.map(s => tickers.find(t => t.symbol === s) ?? { symbol: s, last_price: null, change_24h: null });
  const topMovers = [...tickers]
    .filter(t => t.last_price != null && t.change_24h != null)
    .sort((a, b) => Math.abs(b.change_24h ?? 0) - Math.abs(a.change_24h ?? 0))
    .slice(0, 6);

  return (
    <Panel>
      <PanelHead title="Market Pulse" sub={`${tickers.length} tickers`} to="/markets" />
      <div style={{ padding: '10px 16px 14px' }}>
        {/* Anchors */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginBottom: 14 }}>
          {top.map(t => (
            <Link
              key={t.symbol}
              to={`/market/${t.symbol}`}
              style={{
                display: 'flex', flexDirection: 'column', gap: 2, padding: '8px 10px',
                borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)',
                textDecoration: 'none',
              }}
            >
              <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {t.symbol.replace('USDT', '')}
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                {t.last_price != null ? t.last_price.toLocaleString('en-US', { maximumSignificantDigits: 6 }) : '—'}
              </span>
              <span style={{ fontSize: 11, fontWeight: 600, color: chgColor(t.change_24h), fontFamily: 'var(--font-mono)' }}>
                {fPct(t.change_24h, true)}
              </span>
            </Link>
          ))}
        </div>

        {/* Top movers */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 6 }}>
            Top Movers 24h
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {topMovers.map(t => {
              const chgPct = Math.abs(t.change_24h ?? 0) <= 1 ? (t.change_24h ?? 0) * 100 : (t.change_24h ?? 0);
              return (
                <div key={t.symbol} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)', minWidth: 80 }}>{t.symbol.replace('USDT', '/USDT')}</span>
                  <span style={{ color: chgColor(t.change_24h), fontWeight: 700, minWidth: 52 }}>{(chgPct >= 0 ? '+' : '') + chgPct.toFixed(2)}%</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 10, marginLeft: 'auto' }}>
                    {t.volume_24h != null ? (t.volume_24h >= 1e6 ? (t.volume_24h / 1e6).toFixed(1) + 'M' : (t.volume_24h / 1e3).toFixed(0) + 'K') : ''}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Panel>
  );
}

// ─── Equity + Runtime Stats Mini-chart ───────────────────────────────────────

function EquityPanel({ equity, realized, unrealized, startingCapital, pnlHistory }: {
  equity: number | null;
  realized: number | null;
  unrealized: number | null;
  startingCapital: number | null;
  pnlHistory?: PnlHistoryStatus | null;
}): JSX.Element {
  const startValue = startingCapital ?? equity;
  const chartData = equity == null
    ? []
    : [
      { t: 'Start', value: startValue ?? equity },
      { t: 'Now', value: equity },
    ];
  const pnlTotal = (realized ?? 0) + (unrealized ?? 0);
  const windows = [
    { label: '1D', row: pnlWindow(pnlHistory, '1d') },
    { label: '1W', row: pnlWindow(pnlHistory, '7d') },
    { label: '30D', row: pnlWindow(pnlHistory, '30d') },
  ];

  return (
    <Panel>
      <PanelHead title="Account Equity" to="/portfolio" />
      <div style={{ padding: '10px 16px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
          <span style={{ fontSize: 28, fontWeight: 800, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {equity == null ? '—' : '$' + equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>equity</span>
        </div>
        <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 12, fontFamily: 'var(--font-mono)' }}>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: 10, display: 'block' }}>REALIZED PNL</span>
            <span style={{ color: pnlColor(realized), fontWeight: 700 }}>{f$(realized)}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: 10, display: 'block' }}>UNREALIZED PNL</span>
            <span style={{ color: pnlColor(unrealized), fontWeight: 700 }}>{f$(unrealized)}</span>
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)', fontSize: 10, display: 'block' }}>TOTAL PNL</span>
            <span style={{ color: pnlColor(pnlTotal), fontWeight: 700 }}>{pnlTotal >= 0 ? '+' : ''}{f$(pnlTotal)}</span>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 10 }}>
          {windows.map(({ label, row }) => (
            <div key={label} style={{ padding: '7px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
              <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>{label} PNL</span>
              <span style={{ display: 'block', fontSize: 12, fontWeight: 800, fontFamily: 'var(--font-mono)', color: pnlColor(row?.realized_pnl_usd) }}>
                {formatAdaptiveMoney(row?.realized_pnl_usd)}
              </span>
              <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>
                {row ? `${row.closed_trade_count} closes` : 'No window'}
              </span>
            </div>
          ))}
        </div>
        {chartData.length ? (
          <div data-chart-mode="FALLBACK_STATIC_CHART" aria-label="Execution-restricted account equity chart">
            <ResponsiveContainer width="100%" height={60}>
              <AreaChart data={chartData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent,#3b82f6)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--accent,#3b82f6)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <Area type="monotone" dataKey="value" stroke="var(--accent,#3b82f6)" strokeWidth={2} fill="url(#eqGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="nervyx-dashboard-chart-empty" data-chart-mode="FALLBACK_STATIC_CHART">Awaiting account stream…</div>
        )}
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>
          Starting capital: {startingCapital == null ? 'not reported' : f$(startingCapital)} · Execution-restricted telemetry
        </div>
      </div>
    </Panel>
  );
}

function CapitalProductivityPanel({ capital }: { capital: CapitalProductivityRuntimeStatus | null | undefined }): JSX.Element {
  const blockers = capital?.capital_productivity_blocker_reasons ?? [];
  const diagnostics = capital?.positive_edge_non_a_grade_diagnostics;
  return (
    <Panel>
      <PanelHead
        title="Capital Productivity"
        badge={capital?.status ?? 'Pending'}
        badgeTone={capital?.status === 'PASSED' ? 'ok' : 'block'}
      />
      <div style={{ padding: '10px 16px 14px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 10 }}>
          {[
            ['Class', publicDashboardText(capital?.capital_utilization_classification), adaptiveStatusColor(capital?.status)],
            ['Allocated', formatAdaptiveMoney(capital?.allocated_margin_usd), 'var(--text-primary)'],
            ['Open Notional', formatAdaptiveMoney(capital?.gross_open_notional_usd), 'var(--text-primary)'],
            ['Utilization', formatAdaptivePercent(capital?.capital_utilization_pct), 'var(--text-primary)'],
            ['Deployed Return', formatAdaptivePercent(capital?.return_on_deployed_margin), pnlColor(capital?.return_on_deployed_margin)],
            ['After Cost Edge', formatAdaptiveBps(capital?.after_cost_expectancy_bps), adaptiveStatusColor(capital?.status)],
            ['Positive Edge Idle', String(capital?.positive_edge_non_a_grade_opportunity_count ?? 0), (capital?.positive_edge_non_a_grade_opportunity_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'],
            ['Near A-grade', String(diagnostics?.near_a_grade_positive_edge_count ?? 0), (diagnostics?.near_a_grade_positive_edge_count ?? 0) > 0 ? '#f59e0b' : 'var(--text-secondary)'],
          ].map(([label, value, color]) => (
            <div key={label} style={{ minWidth: 0 }}>
              <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label}</span>
              <span style={{ display: 'block', fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color, overflowWrap: 'anywhere', wordBreak: 'break-word' }}>{value}</span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 10, color: blockers.length ? 'var(--sell,#ef4444)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {blockers.length ? blockers.slice(0, 3).map(publicDashboardText).join(' · ') : 'No capital productivity blockers reported'}
        </div>
      </div>
    </Panel>
  );
}

function AccuracySummaryPanel({ accuracy }: { accuracy: SignalPredictionAccuracyStatus | null | undefined }): JSX.Element {
  const evaluatedCells = accuracy?.evaluated_symbol_timeframe_cell_count;
  const totalCells = accuracy?.symbol_timeframe_cell_count ?? accuracy?.required_symbol_timeframe_cell_count;
  const missingCells = missingAccuracyCellCount(accuracy);
  return (
    <Panel>
      <PanelHead
        title="Signal Accuracy"
        to="/signals"
        badge={accuracy?.status ?? 'Pending'}
        badgeTone={accuracy?.status === 'READY' ? 'ok' : 'warn'}
      />
      <div style={{ padding: '10px 16px 14px', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        {[
          ['Accuracy', formatAdaptivePercent(accuracy?.overall_accuracy), adaptiveStatusColor(accuracy?.status)],
          ['Evaluated', String(accuracy?.evaluated_row_count ?? 0), 'var(--text-primary)'],
          ['Correct', String(accuracy?.correct_count ?? 0), 'var(--buy,#10b981)'],
          ['Incorrect', String(accuracy?.incorrect_count ?? 0), 'var(--sell,#ef4444)'],
          ['Universe', String(accuracy?.symbol_universe_count ?? 0), 'var(--text-primary)'],
          ['TF Cells', `${evaluatedCells ?? 0}/${totalCells ?? 0}`, 'var(--text-primary)'],
          ['Missing Cells', String(missingCells ?? 0), (missingCells ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'],
          ['Unevaluated', String(accuracy?.unevaluated_row_count ?? 0), '#f59e0b'],
        ].map(([label, value, color]) => (
          <div key={label} style={{ minWidth: 0 }}>
            <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label}</span>
            <span style={{ display: 'block', fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color }}>{value}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

// ─── System Health Panel ──────────────────────────────────────────────────────

function SystemHealthPanel({ surfaces }: { surfaces: HealthSurface[] }): JSX.Element {
  return (
    <Panel>
      <PanelHead title="System Health" to="/system-health" />
      <div style={{ padding: '10px 16px 14px', display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {surfaces.map(s => {
          const t = healthStatusTone(s.status);
          return (
            <div key={s.name} title={s.description} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', borderRadius: 6, background: t.bg, border: `1px solid color-mix(in oklch,${t.color} 25%,transparent)` }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: t.color, flexShrink: 0 }} />
              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)' }}>{s.name}</span>
              <span style={{ fontSize: 10, color: t.color, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{t.label}</span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

// ─── Quick Nav ────────────────────────────────────────────────────────────────

const NAV_TILES: Array<{ label: string; desc: string; to: string }> = [
  { label: 'Trade', desc: 'Chart + signal + order ticket', to: '/trade' },
  { label: 'Markets', desc: '627 symbols · full screener', to: '/markets' },
  { label: 'Signals', desc: 'AI signal stream · history', to: '/signals' },
  { label: 'Portfolio', desc: 'Equity · PnL · positions', to: '/portfolio' },
  { label: 'Trainer', desc: 'Model · predictions · health', to: '/ai-predictions' },
  { label: 'Risk Control', desc: 'Profile · limits · kill switch', to: '/admin/risk' },
  { label: 'Audit Ledger', desc: 'Immutable execution trail', to: '/audit-ledger' },
  { label: 'System Health', desc: 'Services · monitors · Redis', to: '/system-health' },
];

function QuickNav(): JSX.Element {
  return (
    <Panel>
      <PanelHead title="Quick Nav" />
      <div style={{ padding: '10px 16px 14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
        {NAV_TILES.map(t => (
          <Link
            key={t.to}
            to={t.to}
            style={{
              display: 'flex', flexDirection: 'column', gap: 3, padding: '10px 12px',
              borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)',
              textDecoration: 'none', transition: 'border-color 0.12s',
            }}
          >
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{t.label}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{t.desc}</span>
          </Link>
        ))}
      </div>
    </Panel>
  );
}

// ─── Main dashboard ───────────────────────────────────────────────────────────

function StatChip({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ padding: '6px 10px', borderRadius: 8, background: 'var(--bg-base)', border: '1px solid var(--border)', minWidth: 0 }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 800, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

function PerformancePanel({ equitySeries, perTradePnl, winLossData, directionData, accuracy, equity, realized, unrealized, totalPnl }: {
  equitySeries: Array<{ label: string; value: number }>;
  perTradePnl: Array<{ label: string; value: number }>;
  winLossData: Array<{ name: string; value: number; color?: string }>;
  directionData: Array<{ name: string; value: number; color?: string }>;
  accuracy: number | null | undefined;
  equity: number | null; realized: number | null; unrealized: number | null; totalPnl: number | null;
}): JSX.Element {
  const trades = perTradePnl.length;
  const wins = perTradePnl.filter((p) => p.value > 0).length;
  const winRate = trades ? (wins / trades) * 100 : null;
  const posColor = '#22c55e', negColor = '#ef4444';
  const pnlColor = (totalPnl ?? 0) >= 0 ? posColor : negColor;
  return (
    <section
      data-testid="dashboard-performance"
      style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 16px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 16 }}>📈</span>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Performance &amp; Capital</h2>
          <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 9.5, fontWeight: 700, fontFamily: 'var(--font-mono)', background: 'rgba(124,92,255,0.12)', color: '#a78bfa', border: '1px solid rgba(124,92,255,0.3)' }}>PAPER · LIVE BLOCKED</span>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <StatChip label="Equity" value={chartUsd(equity)} />
          <StatChip label="Total PnL" value={chartUsd(totalPnl)} color={pnlColor} />
          <StatChip label="Realized" value={chartUsd(realized)} color={(realized ?? 0) >= 0 ? posColor : negColor} />
          <StatChip label="Unrealized" value={chartUsd(unrealized)} color={(unrealized ?? 0) >= 0 ? posColor : negColor} />
          <StatChip label="Win Rate" value={winRate != null ? `${winRate.toFixed(0)}%` : '—'} color={winRate != null ? (winRate >= 50 ? posColor : negColor) : undefined} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)', gap: 14, alignItems: 'stretch' }}>
        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
          <ChartFrame title="Equity curve" subtitle={`${trades} closed paper trades · cumulative`} height={196}>
            {equitySeries.length >= 2
              ? <EquityAreaChart data={equitySeries} height={196} color="#7c5cff" />
              : <EmptyChart label="Awaiting closed trades" />}
          </ChartFrame>
        </div>
        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <ChartFrame title="Prediction accuracy" subtitle="evaluated outcomes" height={150}>
            <RadialGauge value={accuracy} height={150} label="accuracy" />
          </ChartFrame>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginTop: 14 }}>
        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
          <ChartFrame title="Per-trade PnL" subtitle="realized, each closed trade" height={160}>
            {perTradePnl.length ? <PnLBars data={perTradePnl} height={160} /> : <EmptyChart label="No closed trades yet" />}
          </ChartFrame>
        </div>
        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
          <ChartFrame title="Win / loss split" height={150}>
            {winLossData.length
              ? <><Donut data={winLossData} height={150} centerValue={winRate != null ? `${winRate.toFixed(0)}%` : '—'} centerLabel="win rate" /><DonutLegend data={winLossData} /></>
              : <EmptyChart label="No outcomes yet" />}
          </ChartFrame>
        </div>
        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
          <ChartFrame title="Signal direction" subtitle="paper fills bias" height={150}>
            {directionData.length
              ? <><Donut data={directionData} height={150} centerValue={String(directionData.reduce((s, d) => s + d.value, 0))} centerLabel="fills" /><DonutLegend data={directionData} /></>
              : <EmptyChart label="No fills yet" />}
          </ChartFrame>
        </div>
      </div>
    </section>
  );
}

function EmptyChart({ label }: { label: string }): JSX.Element {
  return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12, border: '1px dashed var(--border)', borderRadius: 8 }}>
      {label}
    </div>
  );
}

export default function DashboardPage(): JSX.Element {
  const { user } = useAuth();
  const traderSnapshot = useTraderSnapshot();
  const browserStatus = useBrowserStatus();
  const paperActivity = usePaperActivityStream(1000);
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const portfolioStream = useDashboardStream<PortfolioData>('/api/v2/portfolio', 15_000);
  const liveCanaryStream = useDashboardStream<ReadonlyContract<LiveCanaryStatusData>>('/api/v2/live-canary/status', 10_000, false);
  const aPlusStream = useDashboardStream<ReadonlyContract<APlusInventoryData>>('/api/v2/a-plus/inventory', 10_000, false);
  const goalTrajectoryStream = useDashboardStream<ReadonlyContract<GoalTrajectory1000xData>>('/api/v2/goal/trajectory-1000x', 30_000, false);
  const mobileRiskStream = useDashboardStream<MobileRiskStatusData>('/api/v2/mobile/risk-status', 15_000);
  const signalStream = useDashboardStream<{ active_signal?: ActiveSignal }>('/api/v2/signals', 10_000);
  const orchStream = useDashboardStream<{ heartbeat?: OrchestratorHeartbeat; last_proposals?: OrchestratorProposal[] }>('/api/v2/orchestrator/status', 10_000);
  const riskStream = useDashboardStream<{ active_profile?: RiskProfile; latest_gateway_result?: RiskGatewayResult; heartbeat?: RiskHeartbeat }>('/api/v2/risk/status', 15_000);
  const marketStream = useDashboardStream<{ tickers?: TickerRow[] }>('/api/v2/market/overview', 20_000);
  const healthStream = useDashboardStream<{ overall?: string; surfaces?: HealthSurface[] }>('/api/v2/data-health', 30_000);
  const paperStatusStream = useDashboardStream<{ equity_curve?: Array<{ t?: string; pnl?: number; winner?: boolean }>; closed_trades?: Array<Record<string, unknown>> }>('/api/v2/paper/status', 15_000);

  // Derived
  const portfolioData = portfolioStream.data;
  const signalData = signalStream.data;
  const orchData = orchStream.data;
  const riskData = riskStream.data;
  const marketData = marketStream.data;
  const healthData = healthStream.data;
  const streamSummary = (paperActivity.data.summary ?? {}) as PaperSummary;
  const streamFills = (paperActivity.data.fills ?? []) as unknown as PaperFill[];
  const fills = streamFills;
  const paperSummary = Object.keys(streamSummary).length ? streamSummary : null;
  const hasRuntimeAccount =
    portfolioData?.paper_equity_usd != null
    || portfolioData?.equity != null
    || portfolioData?.paper_equity != null
    || portfolioData?.paper_balance != null
    || portfolioData?.paper_realized_pnl_usd != null
    || portfolioData?.paper_unrealized_pnl_usd != null
    || portfolioData?.paper_total_pnl_usd != null
    || portfolioData?.realized_net_pnl_usd != null
    || portfolioData?.realized_pnl_usd != null
    || portfolioData?.unrealized_pnl_usd != null;
  const realized =
    portfolioData?.paper_realized_pnl_usd
    ?? portfolioData?.realized_net_pnl_usd
    ?? portfolioData?.clean_session_valid_realized_pnl_usd
    ?? portfolioData?.realized_pnl_usd
    ?? portfolioData?.realized_pnl
    ?? null;
  const unrealized =
    portfolioData?.paper_unrealized_pnl_usd
    ?? portfolioData?.unrealized_pnl_usd
    ?? portfolioData?.clean_session_valid_unrealized_pnl_usd
    ?? portfolioData?.unrealized_pnl
    ?? null;
  const startingCapital =
    portfolioData?.initial_capital
    ?? portfolioData?.paper_initial_capital
    ?? portfolioData?.starting_equity_usd
    ?? null;
  const reportedEquity = portfolioData?.paper_equity_usd ?? portfolioData?.equity ?? portfolioData?.paper_equity ?? portfolioData?.paper_balance;
  const totalPnl = portfolioData?.paper_total_pnl_usd ?? portfolioData?.total_pnl_usd ?? (realized != null && unrealized != null ? realized + unrealized : null);
  const equity = reportedEquity ?? (hasRuntimeAccount && startingCapital != null ? startingCapital + (totalPnl ?? (realized ?? 0) + (unrealized ?? 0)) : null);
  const activeSignal = signalData?.active_signal ?? null;
  const proposals = orchData?.last_proposals ?? [];
  const orchHeartbeat = orchData?.heartbeat ?? null;
  const riskProfile = riskData?.active_profile ?? null;
  const latestRiskResult = riskData?.latest_gateway_result ?? null;
  const riskHeartbeat = riskData?.heartbeat ?? null;
  const tickers = marketData?.tickers ?? [];
  const surfaces = healthData?.surfaces ?? [];
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status ?? null;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status ?? capitalStatus?.signal_prediction_accuracy_status ?? null;

  // ── Chart-ready derivations (real closed-trade equity curve) ──────────────
  const equityCurveRaw = paperStatusStream.data?.equity_curve ?? [];
  const perTradePnl = useMemo(
    () => equityCurveRaw
      .map((p, i) => ({ label: `#${i + 1}`, value: Number(p?.pnl ?? 0), winner: p?.winner === true }))
      .filter((p) => Number.isFinite(p.value)),
    [equityCurveRaw],
  );
  const equitySeries = useMemo(() => {
    if (perTradePnl.length === 0) return [] as Array<{ label: string; value: number }>;
    // Anchor on real capital only — never a fabricated baseline. If neither a
    // starting capital nor a live equity is known, render no curve rather than lie.
    const base = startingCapital ?? (equity != null && totalPnl != null ? equity - totalPnl : equity);
    if (base == null) return [] as Array<{ label: string; value: number }>;
    let run = base;
    const pts = [{ label: 'Start', value: base }];
    perTradePnl.forEach((p, i) => { run += p.value; pts.push({ label: `#${i + 1}`, value: run }); });
    return pts;
  }, [perTradePnl, startingCapital, equity, totalPnl]);
  const winCount = perTradePnl.filter((p) => p.value > 0).length;
  const lossCount = perTradePnl.filter((p) => p.value < 0).length;
  const flatCount = perTradePnl.length - winCount - lossCount;
  const winLossData = useMemo(() => ([
    { name: 'Wins', value: winCount, color: '#22c55e' },
    { name: 'Losses', value: lossCount, color: '#ef4444' },
    ...(flatCount > 0 ? [{ name: 'Flat', value: flatCount, color: '#f59e0b' }] : []),
  ]).filter((d) => d.value > 0), [winCount, lossCount, flatCount]);
  const directionData = useMemo(() => {
    let long = 0, short = 0, hold = 0;
    for (const f of fills) {
      const side = String((f as { side?: string }).side ?? '').toLowerCase();
      if (side.includes('long') || side.includes('buy')) long += 1;
      else if (side.includes('short') || side.includes('sell')) short += 1;
      else hold += 1;
    }
    return ([
      { name: 'Long', value: long, color: '#22c55e' },
      { name: 'Short', value: short, color: '#ef4444' },
      ...(hold > 0 ? [{ name: 'Hold', value: hold, color: '#f59e0b' }] : []),
    ]).filter((d) => d.value > 0);
  }, [fills]);
  const showAdminDiagnostics = user?.role ? canSee(normalizeRole(user.role), 'admin') : false;
  const accountMetric = (fieldId: string) => selectAccountMetric(traderSnapshot, fieldId);
  const canonicalSignal = selectActiveSignal(traderSnapshot, activeSignal?.symbol);
  const signalMetric = (fieldId: string) => selectSignalMetric(traderSnapshot, canonicalSignal ?? {}, fieldId);
  const riskMetric = selectSectionMetric(
    traderSnapshot,
    'risk',
    'position.risk_status',
    selectRiskStatus(traderSnapshot),
  );

  // Source status strip.
  const dashboardStreamItems = useMemo(() => ([
    { label: 'Activity', envelope: paperActivity.envelope as ValidatedDataEnvelope<unknown> | null, loading: paperActivity.loading, error: paperActivity.error },
    { label: 'Portfolio', envelope: portfolioStream.envelope as ValidatedDataEnvelope<unknown>, loading: portfolioStream.loading, error: portfolioStream.error },
    { label: 'Live Canary', envelope: liveCanaryStream.envelope as ValidatedDataEnvelope<unknown>, loading: liveCanaryStream.loading, error: liveCanaryStream.error },
    { label: 'A+', envelope: aPlusStream.envelope as ValidatedDataEnvelope<unknown>, loading: aPlusStream.loading, error: aPlusStream.error },
    { label: '1000x', envelope: goalTrajectoryStream.envelope as ValidatedDataEnvelope<unknown>, loading: goalTrajectoryStream.loading, error: goalTrajectoryStream.error },
    { label: 'Risk Truth', envelope: mobileRiskStream.envelope as ValidatedDataEnvelope<unknown>, loading: mobileRiskStream.loading, error: mobileRiskStream.error },
    { label: 'Signals', envelope: signalStream.envelope as ValidatedDataEnvelope<unknown>, loading: signalStream.loading, error: signalStream.error },
    { label: 'Risk', envelope: riskStream.envelope as ValidatedDataEnvelope<unknown>, loading: riskStream.loading, error: riskStream.error },
    { label: 'Market', envelope: marketStream.envelope as ValidatedDataEnvelope<unknown>, loading: marketStream.loading, error: marketStream.error },
  ]), [
    aPlusStream.envelope,
    aPlusStream.error,
    aPlusStream.loading,
    goalTrajectoryStream.envelope,
    goalTrajectoryStream.error,
    goalTrajectoryStream.loading,
    liveCanaryStream.envelope,
    liveCanaryStream.error,
    liveCanaryStream.loading,
    marketStream.envelope,
    marketStream.error,
    marketStream.loading,
    mobileRiskStream.envelope,
    mobileRiskStream.error,
    mobileRiskStream.loading,
    paperActivity.envelope,
    paperActivity.error,
    paperActivity.loading,
    portfolioStream.envelope,
    portfolioStream.error,
    portfolioStream.loading,
    riskStream.envelope,
    riskStream.error,
    riskStream.loading,
    signalStream.envelope,
    signalStream.error,
    signalStream.loading,
  ]);

  return (
    <div
      data-testid="page-dashboard"
      data-page-id={meta.id}
      className="nervyx-dashboard"
    >
      {/* Global service-down alert (auto-heal exhausted / supervisor stale) */}
      <SelfHealingBanner />

      {/* Header */}
      <div className="nervyx-dashboard__header">
        <div className="nervyx-dashboard__brand">
          <img src={NERVYX_BRAND.assets.symbolGradient} alt="" aria-hidden="true" className="nervyx-dashboard__mark" />
          <div>
            <h1>NERVYX EXECUTE</h1>
            <p>
              {NERVYX_BRAND.descriptor} · Realtime data and execution-gate telemetry · {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
            </p>
          </div>
        </div>
        <StatusBar orch={orchData} risk={riskData} />
      </div>

      <DashboardStreamStatus items={dashboardStreamItems} browser={browserStatus} />

      <DashboardControlCenterTruthPanel
        portfolio={portfolioData}
        portfolioEnvelope={portfolioStream.envelope}
        liveCanaryContract={liveCanaryStream.data}
        liveCanaryEnvelope={liveCanaryStream.envelope}
        aPlusContract={aPlusStream.data}
        aPlusEnvelope={aPlusStream.envelope}
        riskTruth={mobileRiskStream.data}
        riskEnvelope={mobileRiskStream.envelope}
        exchangeAccounts={Array.isArray(user?.exchange_accounts) ? user.exchange_accounts : []}
      />

      {/* KPI strip */}
      <div className="nervyx-dashboard__kpis">
        <KPITile label="Account Equity" metric={accountMetric('account.equity')} sub="Trader snapshot" to="/portfolio" />
        <KPITile
          label="Available Balance"
          metric={accountMetric('account.available_balance')}
          sub="Paper sim balance, not live signed account"
          emptyText="Paper balance unavailable; live signed account not read"
          to="/portfolio"
        />
        <KPITile label="Unrealized PnL" metric={accountMetric('account.unrealized_pnl')} sub="Open position PnL" valueColor={pnlColor(accountMetric('account.unrealized_pnl').value as number | null)} to="/portfolio" />
        <KPITile label="Open Positions" metric={accountMetric('account.open_position_count')} sub="Scoped account count" to="/portfolio" />
        <KPITile label="Active Signal" metric={signalMetric('signal.id')} sub="Stable signal ID" to="/signals" />
        <KPITile
          label="Risk Status"
          metric={riskMetric}
          sub="Execution remains restricted"
          emptyText="Fail-closed: no current risk record"
          to="/portfolio"
        />
      </div>

      {/* 1000x goal trajectory — equity vs required, binding constraint, honest freshness */}
      <GoalTrajectoryPanel contract={goalTrajectoryStream.data} />

      {/* Performance & capital — real closed-trade charts (equity / PnL / win-loss / accuracy) */}
      <PerformancePanel
        equitySeries={equitySeries}
        perTradePnl={perTradePnl}
        winLossData={winLossData}
        directionData={directionData}
        accuracy={accuracyStatus?.overall_accuracy}
        equity={equity}
        realized={realized}
        unrealized={unrealized}
        totalPnl={totalPnl}
      />

      <AdaptiveCapitalTelemetryPanel
        payload={adaptiveCapital.data}
        title="Capital Productivity + PnL + Accuracy"
        compact
        showMatrix
        maxMatrixHeight={220}
      />

      {showAdminDiagnostics ? (
        <section
          aria-label="Admin runtime diagnostics"
          className="nervyx-dashboard__admin-diagnostics"
          data-testid="dashboard-admin-diagnostics"
        >
          <MissionControlReadinessBanner />
          <StaleStateAlertsPanel />
        </section>
      ) : null}

      {/* Row 2: Signal + Orchestrator + Risk (3 columns) */}
      <div className="nervyx-dashboard__grid nervyx-dashboard__grid--tri">
        <ActiveSignalPanel
          signal={activeSignal}
          signalIdMetric={signalMetric('signal.id')}
          signalConfidenceMetric={signalMetric('signal.confidence')}
        />
        <OrchestratorPanel proposals={proposals} heartbeat={orchHeartbeat} />
        <RiskPanel profile={riskProfile} latestResult={latestRiskResult} heartbeat={riskHeartbeat} />
      </div>

      {/* Row 3: execution fills + market pulse (2 columns) */}
      <div className="nervyx-dashboard__grid nervyx-dashboard__grid--main">
        <PaperFillsPanel fills={fills} summary={paperSummary} />
        <div className="nervyx-dashboard__side-stack">
          <CapitalProductivityPanel capital={capitalStatus} />
          <MarketPulsePanel tickers={tickers} />
        </div>
      </div>

      {/* Row 4: System health */}
      {surfaces.length > 0 && <SystemHealthPanel surfaces={surfaces} />}

      {/* Row 5: Quick Nav */}
      <QuickNav />
    </div>
  );
}
