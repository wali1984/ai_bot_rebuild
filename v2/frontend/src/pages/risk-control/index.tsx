import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { DangerousControlPanel } from '../../components/controls/DangerousControlPanel';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types (matched to actual /api/v2/risk/status response) ──────────────────

interface RiskProfileFields {
  cooldown_seconds?: number;
  kill_switch_conditions?: string[];
  max_daily_loss?: number;
  max_drawdown?: number;
  max_leverage?: number;
  max_notional_per_trade?: number;
  max_open_positions?: number;
  max_slippage_bps?: number;
  max_spread_bps?: number;
  max_symbol_exposure?: number;
  max_total_exposure?: number;
  min_confidence_calibrated?: number;
  min_expected_move_after_cost_bps?: number;
}

interface ActiveProfile {
  profile_id?: string;
  profile_name?: string;
  fields?: RiskProfileFields;
}

interface GatewayResult {
  decision_id?: string;
  feature_snapshot_id?: string;
  input_decision_action?: string;
  input_decision_reason_code?: string;
  live_blocked?: boolean;
  prediction_id?: string;
  risk_action?: string;
  risk_decision_id?: string;
  risk_decision_ts_ms?: number;
  risk_reason_code?: string;
  symbol?: string;
}

interface RiskHeartbeat {
  worker_id?: string;
  started_at?: string;
  finished_at?: string;
  decisions_processed_total?: number;
  live_gate?: string;
  live_blocked?: boolean;
  classification?: string;
  fail_closed?: boolean;
  approves_live?: boolean;
  places_real_order?: boolean;
}

interface RecentDecision {
  risk_decision_id?: string;
  prediction_id?: string;
  signal_id?: string;
  symbol?: string;
  side?: string;
  risk_action?: string;
  risk_result?: string;
  risk_reason_code?: string;
  live_blocked?: boolean;
  pre_trade_allowed?: boolean;
  fee_gate_allowed?: boolean;
  fee_gate_reason?: string;
  churn_blocked?: boolean;
  churn_reason?: string;
  strategy_selected_mode?: string;
  strategy_allowed_actions?: string[];
  strategy_size_multiplier?: number;
  strategy_router_confidence?: number;
  strategy_regime_labels?: string[];
  required_blocks_checked?: string[];
  generated_at?: string;
}

interface HighConfidenceLossClusterStatus {
  status?: string | null;
  active?: boolean | null;
  cluster_detected?: boolean | null;
  cluster_count?: number | null;
  high_confidence_loss_count?: number | null;
  affected_symbols?: string[] | null;
  affected_buckets?: {
    sides?: string[] | null;
    timeframes?: string[] | null;
    strategy_modes?: string[] | null;
    blocked_bucket_keys?: string[] | null;
  } | null;
  guardian_state?: string | null;
  guardian_new_entries_allowed?: boolean | null;
  REDUCE_SIZE_allowed?: boolean | null;
  reduce_size_bootstrap_allowed?: boolean | null;
  why_reduce_size_blocked?: string | null;
  post_patch_recovery_status?: string | null;
}

interface PreemptiveEdgeControlSummary {
  status?: string | null;
  candidate_count?: number | null;
  accepted_count?: number | null;
  decision_counts?: Record<string, number | null> | null;
  action_counts?: Record<string, number | null> | null;
  preemptive_action?: string | null;
  preemptive_allowed?: boolean | null;
  preemptive_block_reasons?: string[] | null;
  pre_trade_expected_net_pnl_usd?: number | null;
  pre_trade_loss_probability?: number | null;
  confidence_overstatement_risk?: number | null;
  regime_compatibility_score?: number | null;
  exit_feasibility_score?: number | null;
  bucket_profit_factor?: number | null;
  positive_edge_probation_status?: string | null;
  positive_edge_probation_supply_state?: string | null;
  positive_edge_probation_candidates?: number | null;
  positive_edge_probation_accepted?: number | null;
  closed_probation_trade_count?: number | null;
  probation_5_trade_gate_status?: string | null;
  probation_counts_as_final_a_plus?: boolean | null;
  probation_counts_as_live_ready?: boolean | null;
  why_trade_was_prevented?: string[] | null;
  governor_auto_action?: string | null;
  next_remediation?: string | null;
  hard_fail?: boolean | null;
  advanced_indicators?: AdvancedIndicatorSummary | null;
  advanced_indicator_status?: string | null;
  advanced_indicator_block_reason_counts?: Record<string, number | null> | null;
  advanced_indicator_caution_reason_counts?: Record<string, number | null> | null;
}

interface AdvancedIndicatorSummary {
  status?: string | null;
  candidate_count?: number | null;
  fvg_present_count?: number | null;
  fvg_side_aligned_count?: number | null;
  accepted_advanced_indicator_block_count?: number | null;
  fvg_standalone_allows_trade?: boolean | null;
  fvg_alone_can_approve_trade?: boolean | null;
  sweep_risk_can_block_or_reduce?: boolean | null;
  block_reason_counts?: Record<string, number | null> | null;
  caution_reason_counts?: Record<string, number | null> | null;
}

interface PreemptiveDecisionMatrix {
  rows?: Array<{
    preemptive_decision_id?: string | null;
    preemptive_decision?: string | null;
    preemptive_action?: string | null;
    preemptive_allowed?: boolean | null;
    preemptive_block_reasons?: string[] | null;
    preemptive_decision_reasons?: string[] | null;
    pre_trade_expected_net_pnl_usd?: number | null;
    pre_trade_loss_probability?: number | null;
    confidence_overstatement_risk?: number | null;
    expected_edge_after_cost_bps?: number | null;
    bucket_profit_factor?: number | null;
    regime_compatibility_score?: number | null;
    exit_feasibility_score?: number | null;
    advanced_indicator_status?: string | null;
    advanced_indicator_block_reasons?: string[] | null;
    advanced_indicator_caution_reasons?: string[] | null;
    fvg_present?: boolean | null;
  }> | null;
}

interface CanaryTightening {
  classification?: string;
  symbol?: string;
  action?: string;
  confidence?: number;
  min_confidence?: number;
  blockers?: string[];
}

interface RiskStatus {
  active_profile?: ActiveProfile;
  latest_gateway_result?: GatewayResult;
  heartbeat?: RiskHeartbeat;
  recent_decisions?: RecentDecision[];
  denials_breakdown?: Record<string, number>;
  recovery_high_confidence_loss_cluster_status?: HighConfidenceLossClusterStatus | null;
  preemptive_prevention?: PreemptiveEdgeControlSummary | null;
  preemptive_edge_control_status?: PreemptiveEdgeControlSummary | null;
  preemptive_candidate_decision_matrix?: PreemptiveDecisionMatrix | null;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function sideColor(s: string | null | undefined): string {
  const l = (s ?? '').toLowerCase();
  if (l === 'long' || l === 'buy') return '#26c281';
  if (l === 'short' || l === 'sell') return '#ef5350';
  return 'var(--text-muted)';
}

function actionTone(a: string | null | undefined): 'ok' | 'block' | 'warn' | 'neutral' {
  const l = (a ?? '').toLowerCase();
  if (l === 'allow' || l.includes('allow')) return 'ok';
  if (l === 'deny' || l.includes('deny') || l.includes('block')) return 'block';
  return 'warn';
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  return (Math.abs(n) <= 1 ? n * 100 : n).toFixed(1) + '%';
}

function fmtScore(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n.toFixed(3);
}

function fmtAge(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  const sec = (Date.now() - d.getTime()) / 1000;
  if (sec < 60) return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${(sec / 3600).toFixed(1)}h ago`;
}

function Chip({ label, tone }: { label: string; tone: 'ok' | 'warn' | 'block' | 'neutral' }): JSX.Element {
  const map = {
    ok: { bg: 'rgba(38,194,129,0.12)', color: '#26c281', border: 'rgba(38,194,129,0.3)' },
    warn: { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: 'rgba(245,158,11,0.3)' },
    block: { bg: 'rgba(239,83,80,0.12)', color: '#ef5350', border: 'rgba(239,83,80,0.3)' },
    neutral: { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', border: 'rgba(255,255,255,0.1)' },
  }[tone];
  return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, color: map.color, background: map.bg, border: `1px solid ${map.border}`, fontFamily: 'var(--font-mono)', display: 'inline-block' }}>
      {label.replace(/_/g, ' ')}
    </span>
  );
}

function KV({ label, value, valueColor }: { label: string; value: React.ReactNode; valueColor?: string }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: valueColor ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

function SectionHead({ title }: { title: string }): JSX.Element {
  return (
    <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>{title}</div>
  );
}

function Card({ children, accent }: { children: React.ReactNode; accent?: string }): JSX.Element {
  return (
    <div style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '12px 14px', border: `1px solid ${accent ?? 'rgba(255,255,255,0.06)'}`, marginBottom: 14 }}>
      {children}
    </div>
  );
}

function fmtBpsAsPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const pct = value / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

// ─── Profile limits display ───────────────────────────────────────────────────

function ProfileLimits({ fields }: { fields: RiskProfileFields }): JSX.Element {
  const limits = [
    { label: 'Max Leverage', value: fields.max_leverage != null ? `${fields.max_leverage}×` : '—', warn: (fields.max_leverage ?? 0) > 5 },
    { label: 'Max Notional / Trade', value: fields.max_notional_per_trade != null ? `$${fields.max_notional_per_trade.toFixed(2)}` : '—', warn: false },
    { label: 'Max Open Positions', value: fields.max_open_positions != null ? String(fields.max_open_positions) : '—', warn: false },
    { label: 'Max Symbol Exposure', value: fields.max_symbol_exposure != null ? `$${fields.max_symbol_exposure.toFixed(2)}` : '—', warn: false },
    { label: 'Max Total Exposure', value: fields.max_total_exposure != null ? `${fields.max_total_exposure.toFixed(0)}%` : '—', warn: false },
    { label: 'Min Confidence', value: fmtPct(fields.min_confidence_calibrated), warn: false },
    { label: 'Min Exp Move (after cost)', value: fmtBpsAsPct(fields.min_expected_move_after_cost_bps), warn: false },
    { label: 'Max Spread', value: fmtBpsAsPct(fields.max_spread_bps), warn: false },
    { label: 'Max Slippage', value: fmtBpsAsPct(fields.max_slippage_bps), warn: false },
    { label: 'Max Daily Loss', value: fields.max_daily_loss != null ? `$${fields.max_daily_loss.toFixed(2)}` : '—', warn: true },
    { label: 'Max Drawdown', value: fields.max_drawdown != null ? `${fields.max_drawdown.toFixed(0)}%` : '—', warn: true },
    { label: 'Cooldown', value: fields.cooldown_seconds != null ? `${Math.round(fields.cooldown_seconds / 60)}m` : '—', warn: false },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
      {limits.map(l => (
        <div key={l.label} style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6, border: l.warn ? '1px solid rgba(239,83,80,0.15)' : '1px solid rgba(255,255,255,0.04)' }}>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{l.label}</div>
          <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: l.warn ? '#ef5350' : 'var(--text-primary)' }}>{l.value}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Recent decisions table ───────────────────────────────────────────────────

function DecisionsTable({ decisions }: { decisions: RecentDecision[] }): JSX.Element {
  if (!decisions.length) {
    return <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No recent decisions.</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            {['Symbol', 'Side', 'Action', 'Reason Code', 'Pre-trade', 'Fee Gate', 'Churn', 'Strategy Mode', 'Regime', 'Age'].map(h => (
              <th key={h} style={{ padding: '5px 8px', textAlign: 'left', color: 'var(--text-muted)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {decisions.slice(0, 20).map((d, i) => {
            const tone = actionTone(d.risk_action);
            return (
              <tr key={d.risk_decision_id ?? i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                <td style={{ padding: '5px 8px', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{d.symbol ?? '—'}</td>
                <td style={{ padding: '5px 8px', fontWeight: 700, color: sideColor(d.side) }}>{(d.side ?? '—').toUpperCase()}</td>
                <td style={{ padding: '5px 8px', whiteSpace: 'nowrap' }}><Chip label={d.risk_action ?? '—'} tone={tone} /></td>
                <td style={{ padding: '5px 8px', color: 'var(--text-muted)', fontSize: 10, maxWidth: 220, overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>{(d.risk_reason_code ?? '—').replace(/_/g, ' ')}</td>
                <td style={{ padding: '5px 8px', color: d.pre_trade_allowed ? '#26c281' : '#ef5350' }}>{d.pre_trade_allowed == null ? '—' : d.pre_trade_allowed ? '✓' : '✗'}</td>
                <td style={{ padding: '5px 8px', color: d.fee_gate_allowed ? '#26c281' : '#ef5350' }}>{d.fee_gate_allowed == null ? '—' : d.fee_gate_allowed ? '✓' : '✗'}</td>
                <td style={{ padding: '5px 8px', color: d.churn_blocked ? '#f59e0b' : '#26c281' }}>{d.churn_blocked == null ? '—' : d.churn_blocked ? 'HOLD' : 'OK'}</td>
                <td style={{ padding: '5px 8px', color: 'var(--text-muted)', fontSize: 10, whiteSpace: 'nowrap' }}>{d.strategy_selected_mode ?? '—'}</td>
                <td style={{ padding: '5px 8px', color: 'var(--text-muted)', fontSize: 10 }}>{(d.strategy_regime_labels ?? []).join(', ') || '—'}</td>
                <td style={{ padding: '5px 8px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{fmtAge(d.generated_at)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Denial breakdown bar chart ───────────────────────────────────────────────

function DenialBreakdown({ breakdown }: { breakdown: Record<string, number> }): JSX.Element {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    return <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No denial breakdown data.</div>;
  }
  const maxCount = Math.max(...entries.map(([, c]) => c));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {entries.map(([reason, count]) => (
        <div key={reason} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flex: 1, height: 8, background: 'rgba(255,255,255,0.06)', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${Math.min(100, (count / maxCount) * 100)}%`, background: '#ef5350', borderRadius: 4, transition: 'width 0.4s' }} />
          </div>
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', minWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{reason.replace(/_/g, ' ')}</span>
          <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#ef5350', minWidth: 28, textAlign: 'right' }}>{count}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function RiskControlPage(): JSX.Element {
  const { envelope, loading, refetch } = useRealtimeResource<RiskStatus>({
    url: '/api/v2/risk/status',
    source: '/api/v2/risk/status',
    pollIntervalMs: 5_000,
    staleThresholdMs: 15_000,
    mode: 'read_only',
  });

  const d = envelope.data;
  const hb = d?.heartbeat;
  const profile = d?.active_profile;
  const fields = profile?.fields;
  const latest = d?.latest_gateway_result;
  const decisions = d?.recent_decisions ?? [];
  const breakdown = d?.denials_breakdown ?? {};
  const cluster = d?.recovery_high_confidence_loss_cluster_status;
  const preemptive = d?.preemptive_prevention ?? d?.preemptive_edge_control_status;
  const preemptiveSample = d?.preemptive_candidate_decision_matrix?.rows?.[0];
  const preemptiveDecisionId =
    preemptiveSample?.preemptive_decision_id ?? null;
  const preemptiveAction =
    preemptiveSample?.preemptive_action ?? preemptiveSample?.preemptive_decision ?? null;

  const classOk = (hb?.classification ?? '').toLowerCase().includes('ok');
  const totalDenials = Object.values(breakdown).reduce((a, b) => a + b, 0);
  const allowCount = decisions.filter(d => d.risk_action === 'allow').length;
  const denyCount = decisions.filter(d => d.risk_action === 'deny').length;
  const clusterActive = cluster?.active === true || cluster?.cluster_detected === true;
  const clusterCount = cluster?.cluster_count ?? cluster?.high_confidence_loss_count ?? 0;
  const reduceSizeAllowed = cluster?.reduce_size_bootstrap_allowed ?? cluster?.REDUCE_SIZE_allowed;
  const affectedBucketLabels = [
    ...(cluster?.affected_buckets?.sides ?? []).map(value => `side:${value}`),
    ...(cluster?.affected_buckets?.timeframes ?? []).map(value => `tf:${value}`),
    ...(cluster?.affected_buckets?.strategy_modes ?? []).map(value => `strategy:${value}`),
  ];
  const affectedBucketText = affectedBucketLabels.length
    ? affectedBucketLabels.slice(0, 6).join(', ')
    : (cluster?.affected_symbols ?? []).slice(0, 6).join(', ') || '—';
  const preemptiveDecisionCounts = preemptive?.decision_counts ?? {};
  const preemptiveBlocked =
    (preemptiveDecisionCounts['NO_TRADE'] ?? 0)
    + (preemptiveDecisionCounts['SHADOW_ONLY'] ?? 0);
  const preemptiveReasons =
    preemptive?.why_trade_was_prevented
    ?? preemptiveSample?.preemptive_decision_reasons
    ?? [];
  const preTradeLossProbability =
    preemptive?.pre_trade_loss_probability
    ?? preemptiveSample?.pre_trade_loss_probability;
  const confidenceOverstatementRisk =
    preemptive?.confidence_overstatement_risk
    ?? preemptiveSample?.confidence_overstatement_risk;
  const regimeCompatibility =
    preemptive?.regime_compatibility_score
    ?? preemptiveSample?.regime_compatibility_score;
  const exitFeasibility =
    preemptive?.exit_feasibility_score
    ?? preemptiveSample?.exit_feasibility_score;
  const bucketProfitFactor =
    preemptive?.bucket_profit_factor
    ?? preemptiveSample?.bucket_profit_factor;
  const probationCandidates = preemptive?.positive_edge_probation_candidates ?? 0;
  const probationAccepted = preemptive?.positive_edge_probation_accepted ?? 0;
  const probationClosed = preemptive?.closed_probation_trade_count ?? 0;
  const probationSupplyState = preemptive?.positive_edge_probation_supply_state ?? 'NO_SAFE_TRADE_SUPPLY';
  const advanced = preemptive?.advanced_indicators;
  const advancedStatus = advanced?.status ?? preemptive?.advanced_indicator_status ?? preemptiveSample?.advanced_indicator_status ?? 'ADVANCED_INDICATOR_NOT_REPORTED';
  const advancedFvgCount = advanced?.fvg_present_count ?? (preemptiveSample?.fvg_present ? 1 : 0);
  const advancedAcceptedBlocks = advanced?.accepted_advanced_indicator_block_count ?? 0;
  const advancedBlockCounts = advanced?.block_reason_counts ?? preemptive?.advanced_indicator_block_reason_counts ?? {};
  const advancedTopBlocker =
    Object.entries(advancedBlockCounts)
      .sort((a, b) => (Number(b[1] ?? 0)) - (Number(a[1] ?? 0)))[0]?.[0]
    ?? preemptiveSample?.advanced_indicator_block_reasons?.[0]
    ?? 'none';

  return (
    <div
      data-testid="page-risk-control"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}
    >
      {/* Header */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Risk Gateway</h1>
              <Chip label="MARKET PLATFORM" tone="ok" />
              <Chip label="OPERATOR GATED" tone="block" />
              {hb && <Chip label={classOk ? 'OK' : 'DEGRADED'} tone={classOk ? 'ok' : 'warn'} />}
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              Validates and blocks/allows all trade proposals · Final authority · Fail-closed · Auto-refresh 5s
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <button onClick={refetch} style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>↺ Refresh</button>
          </div>
        </div>
      </div>

      <div style={{ padding: '16px 20px' }}>
        <DangerousControlPanel controlIds={meta.dangerousControlIds} />

        {/* Top KPI strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 16 }}>
          {[
            { label: 'Trading Gate', value: 'Operator gated', color: '#ef5350', bg: 'rgba(239,83,80,0.08)', border: 'rgba(239,83,80,0.25)' },
            { label: 'Fail Closed', value: hb?.fail_closed ? 'YES' : '—', color: hb?.fail_closed ? '#26c281' : '#f59e0b', bg: 'rgba(0,0,0,0.2)', border: 'rgba(255,255,255,0.06)' },
            { label: 'Decisions Total', value: (hb?.decisions_processed_total ?? 0).toLocaleString(), color: 'var(--text-primary)', bg: 'rgba(0,0,0,0.2)', border: 'rgba(255,255,255,0.06)' },
            { label: 'Allow / Deny (recent)', value: `${allowCount} / ${denyCount}`, color: 'var(--text-primary)', bg: 'rgba(0,0,0,0.2)', border: 'rgba(255,255,255,0.06)' },
            { label: 'Denial Breakdown', value: totalDenials > 0 ? `${totalDenials} reasons` : 'None', color: totalDenials > 0 ? '#f59e0b' : '#26c281', bg: 'rgba(0,0,0,0.2)', border: 'rgba(255,255,255,0.06)' },
          ].map(item => (
            <div key={item.label} style={{ padding: '10px 14px', background: item.bg, border: `1px solid ${item.border}`, borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</span>
              <span style={{ fontSize: 16, fontWeight: 800, fontFamily: 'var(--font-mono)', color: item.color }}>{loading && !d ? '…' : item.value}</span>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
          {/* Left column */}
          <div>
            {/* Heartbeat */}
            <SectionHead title="Gateway Heartbeat" />
            <Card accent={classOk ? 'rgba(38,194,129,0.2)' : 'rgba(239,83,80,0.2)'}>
              {loading && !d ? (
                <div style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>
              ) : hb ? (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
                    <KV label="Classification" value={<Chip label={(hb.classification ?? '—').replace('V2_RISK_GATEWAY_', '')} tone={classOk ? 'ok' : 'warn'} />} />
                    <KV label="Live Gate" value={hb.live_gate ?? '—'} valueColor={hb.live_gate?.includes('blocked') ? '#ef5350' : '#26c281'} />
                    <KV label="Live Blocked" value={hb.live_blocked ? 'YES' : 'NO'} valueColor={hb.live_blocked ? '#26c281' : '#ef5350'} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
                    <KV label="Decisions Total" value={(hb.decisions_processed_total ?? 0).toLocaleString()} />
                    <KV label="Approves Live" value={hb.approves_live ? 'YES' : 'NO'} valueColor={hb.approves_live ? '#ef5350' : '#26c281'} />
                    <KV label="Places Real Order" value={hb.places_real_order ? 'YES' : 'NO'} valueColor={hb.places_real_order ? '#ef5350' : '#26c281'} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <KV label="Worker" value={(hb.worker_id ?? '—').replace('v2_risk_gateway_', '')} />
                    <KV label="Last Run" value={fmtAge(hb.finished_at)} valueColor="var(--text-muted)" />
                  </div>
                </>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No heartbeat data. Check Redis v2:risk:* keys.</div>
              )}
            </Card>

            {/* Latest gateway result */}
            {latest && (
              <>
                <SectionHead title="Latest Gateway Result" />
                <Card accent={`rgba(${latest.risk_action === 'allow' ? '38,194,129' : '239,83,80'},0.15)`}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 16, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{latest.symbol ?? '—'}</span>
                    <Chip label={latest.risk_action ?? '—'} tone={actionTone(latest.risk_action)} />
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{(latest.risk_reason_code ?? '—').replace(/_/g, ' ')}</span>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                    <KV label="Input Action" value={(latest.input_decision_action ?? '—').replace(/_/g, ' ')} />
                    <KV label="Input Reason" value={(latest.input_decision_reason_code ?? '—').replace(/_/g, ' ')} />
                    <KV label="Live Blocked" value={latest.live_blocked ? 'YES' : 'NO'} valueColor={latest.live_blocked ? '#26c281' : '#ef5350'} />
                    <KV label="Decision ID" value={(latest.risk_decision_id ?? '—').slice(-16)} valueColor="var(--text-muted)" />
                  </div>
                </Card>
              </>
            )}

            {/* Active profile */}
            {profile && (
              <>
                <SectionHead title={`Active Risk Profile — ${profile.profile_id ?? '—'}`} />
                <Card>
                  {fields ? <ProfileLimits fields={fields} /> : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No profile fields.</div>}
                  {fields?.kill_switch_conditions && (
                    <div style={{ marginTop: 10, padding: '8px 10px', background: 'rgba(239,83,80,0.06)', borderRadius: 6, border: '1px solid rgba(239,83,80,0.15)' }}>
                      <div style={{ fontSize: 9, color: '#ef5350', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Kill Switch Conditions</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {fields.kill_switch_conditions.map(c => (
                          <span key={c} style={{ fontSize: 10, fontFamily: 'var(--font-mono)', padding: '1px 6px', background: 'rgba(239,83,80,0.1)', borderRadius: 3, color: '#ef5350', border: '1px solid rgba(239,83,80,0.2)' }}>
                            {c.replace(/_/g, ' ')}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              </>
            )}
          </div>

          {/* Right column */}
          <div>
            <SectionHead title="High-Confidence Loss Cluster" />
            <Card accent={clusterActive ? 'rgba(239,83,80,0.22)' : 'rgba(38,194,129,0.18)'}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginBottom: 10 }}>
                <KV label="Cluster" value={<Chip label={clusterActive ? 'ACTIVE' : 'INACTIVE'} tone={clusterActive ? 'block' : 'ok'} />} />
                <KV label="Loss Count" value={clusterCount.toLocaleString()} valueColor={clusterActive ? '#ef5350' : '#26c281'} />
                <KV label="Guardian" value={(cluster?.guardian_state ?? '—').replace(/_/g, ' ')} valueColor={cluster?.guardian_new_entries_allowed ? '#26c281' : '#ef5350'} />
                <KV label="REDUCE_SIZE" value={reduceSizeAllowed ? 'ALLOWED' : 'BLOCKED'} valueColor={reduceSizeAllowed ? '#f59e0b' : '#ef5350'} />
              </div>
              <div style={{ display: 'grid', gap: 8 }}>
                <KV label="Affected buckets" value={affectedBucketText.replace(/_/g, ' ')} valueColor="var(--text-muted)" />
                <KV label="Why REDUCE_SIZE is not final A+" value={(cluster?.why_reduce_size_blocked ?? cluster?.status ?? 'paper-only bootstrap policy').replace(/_/g, ' ')} valueColor="var(--text-muted)" />
                <KV label="Post-patch recovery" value={(cluster?.post_patch_recovery_status ?? 'not reported').replace(/_/g, ' ')} valueColor={clusterActive ? '#ef5350' : '#f59e0b'} />
              </div>
            </Card>

            <SectionHead title="Preemptive Edge Control" />
            <Card accent={(preemptive?.hard_fail || preemptiveBlocked > 0) ? 'rgba(239,83,80,0.22)' : 'rgba(38,194,129,0.18)'}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12, marginBottom: 10 }}>
                <KV label="Candidates" value={(preemptive?.candidate_count ?? 0).toLocaleString()} />
                <KV label="Accepted" value={(preemptive?.accepted_count ?? 0).toLocaleString()} valueColor={(preemptive?.accepted_count ?? 0) > 0 ? '#26c281' : 'var(--text-muted)'} />
                <KV label="Prevented" value={preemptiveBlocked.toLocaleString()} valueColor={preemptiveBlocked > 0 ? '#ef5350' : '#26c281'} />
                <KV label="Pre-Trade Loss Risk" value={fmtScore(preTradeLossProbability)} valueColor={(preTradeLossProbability ?? 0) >= 0.8 ? '#ef5350' : 'var(--text-primary)'} />
                <KV label="Confidence Overstatement" value={fmtScore(confidenceOverstatementRisk)} valueColor={(confidenceOverstatementRisk ?? 0) >= 0.75 ? '#ef5350' : 'var(--text-primary)'} />
                <KV label="Bucket Health PF" value={fmtScore(bucketProfitFactor)} valueColor={(bucketProfitFactor ?? 1) < 1 ? '#ef5350' : 'var(--text-primary)'} />
                <KV label="Regime Compatibility" value={fmtScore(regimeCompatibility)} valueColor={(regimeCompatibility ?? 1) < 0.45 ? '#ef5350' : 'var(--text-primary)'} />
                <KV label="Exit Feasibility" value={fmtScore(exitFeasibility)} valueColor={(exitFeasibility ?? 1) < 0.55 ? '#ef5350' : 'var(--text-primary)'} />
                <KV label="Status" value={(preemptive?.status ?? 'not published').replace(/_/g, ' ')} valueColor={preemptive?.hard_fail ? '#ef5350' : 'var(--text-muted)'} />
                <KV label="Latest Decision" value={preemptiveDecisionId ? `${preemptiveDecisionId.slice(0, 22)} · ${String(preemptiveAction ?? '').replace(/_/g, ' ')}` : 'no decision yet'} valueColor={'var(--text-muted)'} />
                <KV label="Advanced Market Structure" value={`${advancedStatus.replace(/_/g, ' ')} · FVG ${advancedFvgCount}`} valueColor={advancedStatus.includes('BLOCK') ? '#ef5350' : 'var(--text-muted)'} />
                <KV label="Liquidity Sweep Risk" value={`can block/reduce ${advanced?.sweep_risk_can_block_or_reduce === false ? 'false' : 'true'} · accepted blocks ${advancedAcceptedBlocks}`} valueColor={advancedAcceptedBlocks > 0 ? '#ef5350' : 'var(--text-muted)'} />
                <KV label="FVG Standalone Approval" value={advanced?.fvg_alone_can_approve_trade || advanced?.fvg_standalone_allows_trade ? 'true' : 'false'} valueColor={(advanced?.fvg_alone_can_approve_trade || advanced?.fvg_standalone_allows_trade) ? '#ef5350' : 'var(--text-muted)'} />
                <KV label="Positive-Edge Probation" value={`${probationSupplyState.replace(/_/g, ' ')} · ${probationCandidates.toLocaleString()} candidates`} valueColor={probationCandidates > 0 ? '#f59e0b' : '#ef5350'} />
                <KV label="Probation Accepted" value={`${probationAccepted.toLocaleString()} · closes ${probationClosed.toLocaleString()}`} valueColor={probationAccepted > 0 ? '#f59e0b' : 'var(--text-muted)'} />
                <KV label="Probation 5-Trade Gate" value={(preemptive?.probation_5_trade_gate_status ?? 'waiting').replace(/_/g, ' ')} valueColor="var(--text-muted)" />
              </div>
              <div style={{ display: 'grid', gap: 8 }}>
                <KV label="Why Trade Was Prevented" value={(preemptiveReasons.slice(0, 4).join(', ') || '—').replace(/_/g, ' ')} valueColor="var(--text-muted)" />
                <KV label="Advanced Indicator Blocker" value={advancedTopBlocker.replace(/_/g, ' ')} valueColor={advancedTopBlocker === 'none' ? 'var(--text-muted)' : '#ef5350'} />
                <KV label="Probation Proof Policy" value={`final A+ ${preemptive?.probation_counts_as_final_a_plus === true ? 'true' : 'false'} · live ${preemptive?.probation_counts_as_live_ready === true ? 'true' : 'false'}`} valueColor={(preemptive?.probation_counts_as_final_a_plus || preemptive?.probation_counts_as_live_ready) ? '#ef5350' : 'var(--text-muted)'} />
                <KV label="Governor Auto-Action" value={(preemptive?.governor_auto_action ?? '—').replace(/_/g, ' ')} valueColor={preemptive?.governor_auto_action?.includes('halt') ? '#ef5350' : 'var(--text-muted)'} />
                <KV label="Next Remediation" value={preemptive?.next_remediation ?? '—'} valueColor="var(--text-muted)" />
              </div>
            </Card>

            {/* Denial breakdown */}
            {Object.keys(breakdown).length > 0 && (
              <>
                <SectionHead title="Denial Reason Breakdown" />
                <Card>
                  <DenialBreakdown breakdown={breakdown} />
                </Card>
              </>
            )}

            {/* Recent decisions */}
            <SectionHead title={`Recent Gateway Decisions — ${decisions.length} in window`} />
            <Card>
              {loading && !d ? (
                <div style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>
              ) : (
                <>
                  <DecisionsTable decisions={decisions} />
                  {decisions.length > 20 && (
                    <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      Showing 20 of {decisions.length} decisions
                    </div>
                  )}
                </>
              )}
            </Card>

            {/* Source */}
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', padding: '6px 0' }}>
              Source: {envelope.source ?? '/api/v2/risk/status'} · {envelope.source_type ?? 'redis_live'} · Poll: 5s
            </div>
          </div>
        </div>
      </div>

      {/* Safety footer */}
      <div style={{ margin: '0 20px 20px', padding: '10px 16px', background: 'rgba(239,83,80,0.05)', border: '1px solid rgba(239,83,80,0.15)', borderRadius: 8 }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          SAFETY: Risk Gateway is final authority. Orchestrator cannot override it. All dangerous settings (disable kill switch, increase leverage, enable exchange execution) require explicit human approval at L4/L5.
        </p>
      </div>
    </div>
  );
}
