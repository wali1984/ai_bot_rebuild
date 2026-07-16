import React, { useState, useMemo, useCallback } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { CanonicalMetricCard } from '../../components/data/CanonicalMetric';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { selectActiveSignal, selectSignalMetric } from '../../selectors/signalSelectors';
import {
  publicRuntimeId,
  publicRuntimeLabel,
  runtimeAgeSeconds,
  runtimeBoolean,
  runtimeNumber,
  runtimeRecord,
  runtimeText,
  type CurrentRuntimeLineagePayload,
  useCurrentRuntimeLineage,
} from '../../data/currentRuntimeLineage';
import {
  accuracyCell as lookupAccuracyCell,
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  type SignalPredictionAccuracyCell,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types ─────────────────────────────────────────────────────────────────

interface SignalRow {
  symbol: string;
  timeframe: string;
  action: string | null;
  side: string | null;
  confidence: number | null;
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
  live_gate: string | null;
  actionable: boolean;
  risk_state: string | null;
  orchestrator_state: string | null;
  paper_fill_status: string | null;
  paper_fill_gate_status: string | null;
  data_coverage_percent: number | null;
  market_state_integrity_score: number | null;
  generated_at: string | null;
  age_seconds: number | null;
  signal_id: string | null;
  prediction_id: string | null;
  price_target: number | null;
  price_target_after_cost: number | null;
  expected_move_bps: number | null;
}

interface SignalMatrixData {
  rows: SignalRow[];
  count: number;
  symbols: string[];
  symbol_count: number;
  timeframes: string[];
  missing: string[];
}

interface SignalExplanation {
  summary: string;
  signal_strength: string;
  confidence_narrative: string;
  data_quality_narrative: string;
  market_integrity_narrative: string;
  technical_drivers: string;
  price_target_narrative: string;
  risk_gate_narrative: string;
  pipeline_state_narrative: string;
  full_text: string;
}

interface ExplainData {
  symbol: string;
  timeframe: string;
  generated_at: string | null;
  explanation: SignalExplanation;
  key_numbers: {
    action: string;
    confidence_calibrated: number;
    confidence_raw: number;
    confidence_selected_action?: number | null;
    confidence_executable_trade?: number | null;
    confidence_display_label?: string | null;
    confidence_tradeability_block_reasons?: string[] | null;
    dominant_prob: number;
    expected_move_bps: number;
    price_target: number | null;
    data_coverage_pct: number;
    integrity_score: number;
    masa_signal: number | null;
    policy_value: number | null;
    missing_feature_count: number;
  };
}

interface SignalCurrentActive {
  symbol?: string | null;
  timeframe?: string | null;
  action?: string | null;
  side?: string | null;
  proposed_action?: string | null;
  actionable?: boolean | null;
  actionable_reason_code?: string | null;
  live_gate?: string | null;
  generated_at?: string | null;
  signal_id?: string | null;
  prediction_id?: string | null;
  source_freshness?: string | null;
  market_age_seconds?: number | null;
  exchange_action_taken?: boolean | null;
  exchange_call_invariant?: string | null;
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
  price_target?: number | null;
  price_target_after_cost?: number | null;
  expected_move_after_cost_bps?: number | null;
  data_coverage_percent?: number | null;
  market_state_integrity_score?: number | null;
  paper_fill_allowed?: boolean | null;
  risk_result?: string | null;
  blocked_reason?: string | null;
  explanation?: string | null;
}

interface SignalCurrentContract {
  schema_version?: string;
  source?: string | null;
  source_type?: string | null;
  endpoint?: string | null;
  staleness_seconds?: number | null;
  freshness_status?: string | null;
  data_quality_status?: string | null;
  live_gate?: string | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
  data?: {
    active_signal?: SignalCurrentActive | null;
    account_scope?: string | null;
    account_specific?: boolean | null;
    public_paper_signal?: boolean | null;
  } | null;
}

interface APlusInventoryContract {
  source?: string | null;
  staleness_seconds?: number | null;
  freshness_status?: string | null;
  live_gate?: string | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
  data?: {
    evaluated_candidates?: number | null;
    a_plus_candidates?: number | null;
    live_ready_rows?: number | null;
    counts_as_final_a_plus?: boolean | null;
    paper_session_id?: string | null;
  } | null;
}

interface ProviderStatusCard {
  provider?: string | null;
  display_name?: string | null;
  dashboard_color?: string | null;
  status?: string | null;
  actual_payload_count?: number | null;
  feature_count?: number | null;
  consumer_count?: number | null;
  heartbeat_only?: boolean | null;
}

interface ProviderStatusContract {
  providers?: ProviderStatusCard[];
  live_gate?: string | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
}

// ─── Constants ─────────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'] as const;
type TF = typeof TIMEFRAMES[number];
const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT', 'ADAUSDT'];
const LIQ_HEATMAP_URL = '/api/v2/liquidation/levels-heatmap';

// ─── Liquidation Heatmap Types ─────────────────────────────────────────────

interface LiqHeatmapRow {
  symbol: string;
  timeframe: string;
  long_strength: number;
  short_strength: number;
  total_strength: number;
  long_pct: number;
  short_pct: number;
  volume: number;
  cascade_risk: number | null;
  pressure_direction: number | null;
  current_price: number | null;
  sweep_target_long: number | null;
  sweep_target_short: number | null;
  sweep_long_dist_bps: number | null;
  sweep_short_dist_bps: number | null;
  nearest_above: number | null;
  nearest_below: number | null;
  zones_long: number;
  zones_short: number;
  count_5m: number;
  stale: boolean;
  stale_age_s: number | null;
  last_liq_bps: number | null;
  long_distance_pct: number | null;
  short_distance_pct: number | null;
}

interface LiqHeatmapData {
  rows: LiqHeatmapRow[];
  count: number;
  symbols: string[];
  symbol_count: number;
  timeframes: string[];
  top_by_volume: string[];
  pinned_defaults: string[];
  volume_by_symbol: Record<string, number>;
  stale_count: number;
  current_count: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function actionColor(a: string | null | undefined): string {
  if (!a) return 'var(--text-muted)';
  const l = a.toLowerCase();
  if (l.includes('long') || l.includes('buy')) return '#26c281';
  if (l.includes('short') || l.includes('sell')) return '#ef5350';
  if (l.includes('hold')) return '#f59e0b';
  return 'var(--text-muted)';
}
function gateColor(g: string | null | undefined): string {
  if (!g) return 'var(--text-muted)';
  const l = g.toLowerCase();
  if (l.includes('allow') || l.includes('pass') || l.includes('open')) return '#26c281';
  if (l.includes('block') || l.includes('human_only')) return '#ef5350';
  return '#f59e0b';
}
function confColor(c: number | null | undefined): string {
  if (c == null) return 'var(--text-muted)';
  const v = Math.abs(c) <= 1 ? c : c / 100;
  if (v >= 0.75) return '#26c281';
  if (v >= 0.55) return '#f59e0b';
  return '#ef5350';
}
function fmtConf(c: number | null | undefined): string {
  if (c == null) return '—';
  const v = Math.abs(c) <= 1 ? c * 100 : c;
  return `${v.toFixed(1)}%`;
}
function fmtAge(s: number | null | undefined): string {
  if (s == null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
function fmtPrice(p: number | null | undefined): string {
  if (p == null) return '—';
  return `$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtBps(bps: number | null | undefined): string {
  if (bps == null) return '—';
  const pct = bps / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}
function fmtUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return `${value < 0 ? '-' : ''}$${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

function signalText(value: unknown, fallback = '—'): string {
  if (typeof value === 'string' && value.trim()) {
    return value
      .replace(/blocked_human_only/gi, 'LIVE BLOCKED')
      .replace(/_/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b[a-z0-9]/g, (char) => char.toUpperCase())
      .replace(/\bPnl\b/g, 'PnL')
      .replace(/\bUsd\b/g, 'USD');
  }
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'boolean') return value ? 'YES' : 'NO';
  return fallback;
}
function firstReason(reasons: string[] | null | undefined, fallback: string): string {
  return reasons?.find(reason => typeof reason === 'string' && reason.trim()) ?? fallback;
}

function signalNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function providerLookup(providers: ProviderStatusCard[] | undefined): Map<string, ProviderStatusCard> {
  const map = new Map<string, ProviderStatusCard>();
  for (const row of providers ?? []) {
    const key = String(row.provider ?? row.display_name ?? '').toLowerCase();
    if (key) map.set(key, row);
  }
  return map;
}

function SignalTruthMetric({
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
      <span style={{ display: 'block', fontSize: 14, fontWeight: 800, color: color ?? 'var(--text-primary)', fontFamily: 'var(--font-mono)', overflowWrap: 'anywhere' }}>{value}</span>
      {sub ? <span style={{ display: 'block', marginTop: 2, fontSize: 10, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>{sub}</span> : null}
    </div>
  );
}

function signalRowFromLineage(payload: CurrentRuntimeLineagePayload | null | undefined): SignalRow | null {
  if (!payload) return null;
  const signal = runtimeRecord(payload.signal);
  const trainer = runtimeRecord(payload.trainer_prediction);
  const risk = runtimeRecord(payload.risk_decision);
  const orch = runtimeRecord(payload.orchestrator_decision);
  const rawOutput = runtimeRecord(trainer.raw_output);
  const drivers = runtimeRecord(trainer.reasoning_drivers);
  const canary = runtimeRecord(risk.canary_profile_tightening);
  const edgeGate = runtimeRecord(risk.paper_edge_gate);
  const generatedAt = runtimeText(signal.generated_at, trainer.generated_at, risk.generated_at, payload.generated_at);
  const symbol = runtimeText(signal.symbol, trainer.symbol);
  if (!symbol) return null;
  const fillAllowed = runtimeBoolean(edgeGate.fill_allowed) ?? runtimeBoolean(canary.safe_for_live);
  const fillStatus = fillAllowed === true ? 'ready' : fillAllowed === false ? 'gated' : null;
  const liveGate = runtimeText(signal.live_gate, edgeGate.live_gate, canary.live_gate_status);
  return {
    symbol,
    timeframe: runtimeText(trainer.timeframe) ?? '1m',
    action: runtimeText(signal.proposed_action, rawOutput.side, trainer.direction),
    side: runtimeText(signal.side, rawOutput.side, trainer.direction),
    confidence: runtimeNumber(signal.confidence_calibrated, trainer.confidence_calibrated, drivers.confidence_calibrated),
    confidence_executable_trade: runtimeNumber(signal.confidence_executable_trade, trainer.confidence_executable_trade),
    confidence_selected_action: runtimeNumber(signal.confidence_selected_action, trainer.confidence_selected_action),
    confidence_display_label: runtimeText(signal.confidence_display_label, trainer.confidence_display_label),
    confidence_tradeability_block_reasons: Array.isArray(signal.confidence_tradeability_block_reasons)
      ? signal.confidence_tradeability_block_reasons.map(String)
      : null,
    paper_exploration_tier: runtimeText(signal.paper_exploration_tier, signal.exploration_tier),
    exploration_tier: runtimeText(signal.exploration_tier, signal.paper_exploration_tier),
    paper_exploration_current_blocker: runtimeText(signal.paper_exploration_current_blocker),
    paper_exploration_paper_fill_allowed: runtimeBoolean(signal.paper_exploration_paper_fill_allowed),
    paper_exploration_risk_controller_decision: runtimeText(signal.paper_exploration_risk_controller_decision),
    paper_exploration_orchestrator_decision: runtimeText(signal.paper_exploration_orchestrator_decision),
    paper_exploration_allocator_decision: runtimeText(signal.paper_exploration_allocator_decision),
    expected_net_pnl_usd: runtimeNumber(signal.expected_net_pnl_usd, risk.expected_net_pnl_usd),
    expected_max_loss_usd: runtimeNumber(signal.expected_max_loss_usd, risk.expected_max_loss_usd),
    why_not_a_plus: Array.isArray(signal.why_not_a_plus) ? signal.why_not_a_plus.map(String) : null,
    why_not_live_ready: Array.isArray(signal.why_not_live_ready) ? signal.why_not_live_ready.map(String) : null,
    risk_controller_decision: runtimeText(signal.risk_controller_decision, risk.risk_decision, risk.risk_result),
    allocator_decision: runtimeText(signal.allocator_decision),
    trainer_feedback_status: runtimeText(signal.trainer_feedback_status),
    live_gate: liveGate,
    actionable: runtimeBoolean(signal.actionable) ?? true,
    risk_state: runtimeText(risk.risk_result, risk.risk_action, risk.risk_reason_code),
    orchestrator_state: runtimeText(orch.decision_action, orch.decision_reason),
    paper_fill_status: fillStatus,
    paper_fill_gate_status: fillStatus,
    data_coverage_percent: runtimeNumber(trainer.data_coverage_pct, drivers.data_coverage_pct),
    market_state_integrity_score: runtimeNumber(drivers.market_state_integrity_score),
    generated_at: generatedAt,
    age_seconds: runtimeNumber(signal.market_age_seconds, trainer.market_age_seconds, runtimeAgeSeconds(generatedAt)),
    signal_id: runtimeText(signal.signal_id),
    prediction_id: runtimeText(signal.prediction_id, trainer.prediction_id),
    price_target: null,
    price_target_after_cost: null,
    expected_move_bps: runtimeNumber(risk.expected_move_after_cost_bps, risk.expected_move_bps, trainer.expected_move_bps),
  };
}

// ─── Routing badge ─────────────────────────────────────────────────────────

function RoutingBadge({ gateStatus, paperFill }: { gateStatus: string | null | undefined; paperFill: string | null | undefined }): JSX.Element {
  const isLive = (gateStatus ?? '').toLowerCase().includes('open') && !(gateStatus ?? '').toLowerCase().includes('blocked');
  const isReady = ['open', 'allow', 'allowed', 'ready', 'routed'].some((token) => (paperFill ?? '').toLowerCase().includes(token));
  const isBlocked = (gateStatus ?? '').toLowerCase().includes('blocked');

  if (isLive) return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(38,194,129,0.15)', color: '#26c281', border: '1px solid #26c28130', fontFamily: 'var(--font-mono)' }}>
      LIVE ROUTED
    </span>
  );
  if (isReady) return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(59,130,246,0.12)', color: '#3b82f6', border: '1px solid #3b82f630', fontFamily: 'var(--font-mono)' }}>
      EXECUTION READY
    </span>
  );
  if (isBlocked) return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(239,83,80,0.1)', color: '#ef5350', border: '1px solid #ef535030', fontFamily: 'var(--font-mono)' }}>
      GATED
    </span>
  );
  return <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, color: 'var(--text-muted)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}>Pending</span>;
}

// ─── Action badge ─────────────────────────────────────────────────────────

function ActionBadge({ action }: { action: string | null | undefined }): JSX.Element {
  const color = actionColor(action);
  if (!action) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  const label = action.replace(/_/g, ' ').toUpperCase();
  return (
    <span style={{ padding: '3px 10px', borderRadius: 5, fontSize: 12, fontWeight: 800, fontFamily: 'var(--font-mono)', color, background: `${color}15`, border: `1px solid ${color}30`, letterSpacing: '0.05em' }}>
      {label.includes('SHORT') ? '▼ ' : label.includes('LONG') ? '▲ ' : '● '}{label}
    </span>
  );
}

// ─── Confidence bar ────────────────────────────────────────────────────────

function ConfBar({ value, width = 64 }: { value: number | null | undefined; width?: number }): JSX.Element {
  const pct = value != null ? Math.min(100, Math.max(0, (Math.abs(value) <= 1 ? value : value / 100) * 100)) : 0;
  const color = confColor(value);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color, fontWeight: 700, minWidth: 40 }}>{fmtConf(value)}</span>
    </div>
  );
}

// ─── Price target cell ────────────────────────────────────────────────────

function PriceTargetCell({ target, moveBps, action }: { target: number | null | undefined; moveBps: number | null | undefined; action: string | null | undefined }): JSX.Element {
  if (!target) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  const color = actionColor(action);
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12, color }}>{fmtPrice(target)}</div>
      {moveBps != null && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>{fmtBps(moveBps)}</div>}
    </div>
  );
}

function AccuracyBadge({ cell }: { cell: SignalPredictionAccuracyCell | null }): JSX.Element {
  if (!cell || !cell.evaluated_count) {
    return (
      <div style={{ fontFamily: 'var(--font-mono)' }}>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)' }}>—</span>
        <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)' }}>no outcomes</span>
      </div>
    );
  }
  return (
    <div style={{ fontFamily: 'var(--font-mono)' }}>
      <span style={{ display: 'block', fontSize: 12, fontWeight: 800, color: adaptiveStatusColor(cell.status) }}>
        {formatAdaptivePercent(cell.accuracy)}
      </span>
      <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)' }}>
        {cell.correct_count ?? 0}/{cell.evaluated_count} hits
      </span>
      <span style={{ display: 'block', fontSize: 9, color: (cell.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
        {formatAdaptiveMoney(cell.realized_pnl_usd)} pnl
      </span>
    </div>
  );
}

function SignalRuntimeTruthPanel({
  current,
  currentEnvelope,
  aPlus,
  providers,
}: {
  current: SignalCurrentContract | null;
  currentEnvelope: { freshness_status: string; lag_ms: number | null; source: string; endpoint?: string };
  aPlus: APlusInventoryContract | null;
  providers: ProviderStatusContract | null;
}): JSX.Element {
  const active = current?.data?.active_signal ?? null;
  const providerMap = providerLookup(providers?.providers);
  const providerSummary = [
    providerMap.get('coinglass'),
    providerMap.get('moralis'),
    providerMap.get('santiment') ?? providerMap.get('sanbase'),
  ].map((provider) => {
    const name = provider?.display_name ?? provider?.provider ?? 'provider';
    const color = provider?.dashboard_color ?? provider?.status ?? 'gray';
    const payloads = provider?.actual_payload_count ?? 0;
    const heartbeat = provider?.heartbeat_only ? 'heartbeat-only' : 'actual';
    return `${name}:${String(color).toUpperCase()}/${payloads} ${heartbeat}`;
  }).join(' · ');
  const liveGate = active?.live_gate ?? current?.live_gate ?? providers?.live_gate ?? 'blocked_human_only';
  const liveBlocked = /blocked|human/i.test(liveGate);
  const action = active?.side ?? active?.proposed_action ?? active?.action ?? null;
  const confidence = signalNumber(active?.confidence_calibrated, active?.confidence);
  const executableConfidence = signalNumber(active?.confidence_executable_trade);
  const confidenceLabel = active?.confidence_display_label ?? 'Unproven confidence';
  const explorationTier = active?.paper_exploration_tier ?? active?.exploration_tier ?? null;
  const expectedMove = signalNumber(active?.expected_move_after_cost_bps);
  const actionable = active?.actionable === true && active?.paper_fill_allowed === true && !liveBlocked;
  const mutationSafe = current?.places_real_order !== true
    && current?.routes_to_live !== true
    && providers?.places_real_order !== true
    && providers?.routes_to_live !== true
    && active?.exchange_action_taken !== true;
  const blocker = active?.blocked_reason
    ?? active?.risk_result
    ?? active?.actionable_reason_code
    ?? active?.explanation
    ?? (liveBlocked ? 'blocked_human_only' : null);

  return (
    <section data-testid="signals-runtime-truth-panel" style={{ margin: '12px 16px 0', padding: 16, borderRadius: 12, border: '1px solid var(--border)', background: 'var(--bg-panel)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <span style={{ display: 'block', fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Current Signal Runtime Truth</span>
          <h2 style={{ margin: '3px 0 0', fontSize: 17, color: 'var(--text-primary)' }}>
            {active?.symbol ?? 'No signal'} {active?.timeframe ?? ''} · {signalText(action, 'No action')}
          </h2>
        </div>
        <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 800, fontFamily: 'var(--font-mono)', border: `1px solid ${actionable ? 'rgba(38,194,129,0.35)' : 'rgba(239,83,80,0.35)'}`, color: actionable ? '#26c281' : '#ef5350', background: actionable ? 'rgba(38,194,129,0.1)' : 'rgba(239,83,80,0.08)' }}>
          {actionable ? 'ACTIONABLE REVIEW' : 'NO LIVE TRADE'}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(165px, 1fr))', gap: 12 }}>
        <SignalTruthMetric label="canonical source" value="/api/v2/signals/current" sub={current?.source ?? currentEnvelope.source} />
        <SignalTruthMetric label="live_gate" value={signalText(liveGate)} sub={`places_real_order=${current?.places_real_order === true ? 'YES' : 'NO'} · routes_to_live=${current?.routes_to_live === true ? 'YES' : 'NO'}`} color={liveBlocked ? '#ef5350' : '#f59e0b'} />
        <SignalTruthMetric label="actionable" value={active?.actionable === true ? 'YES' : 'NO'} sub={signalText(active?.actionable_reason_code, 'actionable_reason_code pending')} color={active?.actionable === true ? '#26c281' : '#ef5350'} />
        <SignalTruthMetric label="paper_fill_allowed" value={active?.paper_fill_allowed === true ? 'YES' : 'NO'} sub={signalText(active?.exchange_call_invariant, 'LIVE_TRADING_BLOCKED')} color={active?.paper_fill_allowed === true ? '#3b82f6' : '#ef5350'} />
        <SignalTruthMetric
          label="executable confidence"
          value={fmtConf(executableConfidence)}
          sub={`${confidenceLabel} · selected ${fmtConf(confidence)}`}
          color={confColor(executableConfidence)}
        />
        <SignalTruthMetric
          label="paper exploration"
          value={signalText(explorationTier, 'NONE')}
          sub={`net ${fmtUsd(active?.expected_net_pnl_usd)} · max loss ${fmtUsd(active?.expected_max_loss_usd)}`}
          color={explorationTier ? '#3b82f6' : 'var(--text-muted)'}
        />
        <SignalTruthMetric
          label="risk / allocator"
          value={signalText(active?.risk_controller_decision ?? active?.risk_result, 'PENDING')}
          sub={`allocator ${signalText(active?.allocator_decision, 'PENDING')} · trainer ${signalText(active?.trainer_feedback_status, 'PENDING')}`}
          color="#3b82f6"
        />
        <SignalTruthMetric label="expected_after_cost" value={fmtBps(expectedMove)} sub={active?.price_target_after_cost != null ? `target ${fmtPrice(active.price_target_after_cost)}` : 'target pending'} color={expectedMove != null && expectedMove > 0 ? '#26c281' : '#ef5350'} />
        <SignalTruthMetric label="A+ candidates" value={String(aPlus?.data?.a_plus_candidates ?? 0)} sub={`${aPlus?.data?.evaluated_candidates ?? 0} evaluated · ${aPlus?.data?.live_ready_rows ?? 0} live-ready`} color={(aPlus?.data?.a_plus_candidates ?? 0) > 0 ? '#26c281' : '#f59e0b'} />
        <SignalTruthMetric label="data freshness" value={current?.staleness_seconds != null ? `${Math.round(current.staleness_seconds)}s` : currentEnvelope.freshness_status} sub={`lag ${currentEnvelope.lag_ms ?? '—'}ms · ${current?.freshness_status ?? currentEnvelope.freshness_status}`} />
      </div>
      <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)', display: 'grid', gap: 6, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        <span>why_no_trade={signalText(blocker, 'No live trade until all gates pass')}</span>
        <span>why_not_A_plus={signalText(firstReason(active?.why_not_a_plus, 'A+ evidence not matured'))}</span>
        <span>why_not_live_ready={signalText(firstReason(active?.why_not_live_ready, 'Live remains blocked_human_only'))}</span>
        <span>provider_context={providerSummary || 'provider status pending'}</span>
        <span>safety={mutationSafe ? 'NO ORDER / TEST / LEVERAGE / MARGIN MUTATION' : 'MUTATION RISK DETECTED'}</span>
      </div>
    </section>
  );
}

// ─── AI Reasoning drawer ──────────────────────────────────────────────────

function AIReasoningPanel({ symbol, timeframe }: { symbol: string; timeframe: string }): JSX.Element {
  const { envelope, loading } = useRealtimeResource<ExplainData>({
    url: `/api/v2/predictions/explain?symbol=${symbol}&timeframe=${timeframe}`,
    source: 'ai_explain',
    pollIntervalMs: 120_000,
    mode: 'read_only',
  });

  const exp = envelope.data?.explanation;
  const nums = envelope.data?.key_numbers;

  if (loading && !exp) return (
    <div style={{ padding: '16px 20px', background: 'var(--bg-elevated)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading AI reasoning…</span>
      </div>
    </div>
  );

  if (!exp) return (
    <div style={{ padding: '16px 20px', background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border)' }}>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
        AI reasoning not yet available for {symbol} {timeframe}. The explain endpoint may need the backend deployed.
      </p>
    </div>
  );

  return (
    <div style={{ background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border)', padding: '20px 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 14 }}>🧠</span>
        <h4 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>AI Signal Reasoning — {symbol} {timeframe}</h4>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>Based on real model data</span>
      </div>

      {/* Key numbers strip */}
      {nums && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16, padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
          {[
            { label: 'Action', value: nums.action, color: actionColor(nums.action) },
            { label: 'Executable Confidence', value: fmtConf(nums.confidence_executable_trade ?? null), color: confColor(nums.confidence_executable_trade ?? null) },
            { label: 'Selected Confidence', value: fmtConf(nums.confidence_selected_action ?? nums.confidence_calibrated), color: confColor(nums.confidence_selected_action ?? nums.confidence_calibrated) },
            { label: 'Raw Confidence', value: fmtConf(nums.confidence_raw), color: 'var(--text-muted)' },
            { label: 'Dominant Prob', value: `${(nums.dominant_prob * 100).toFixed(1)}%`, color: nums.dominant_prob > 0.9 ? '#26c281' : '#f59e0b' },
            { label: 'MASA Signal', value: nums.masa_signal != null ? nums.masa_signal.toFixed(3) : '—', color: nums.masa_signal != null ? (nums.masa_signal < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)' },
            { label: 'Missing Features', value: String(nums.missing_feature_count), color: nums.missing_feature_count > 20 ? '#f59e0b' : '#26c281' },
            { label: 'Integrity', value: `${nums.integrity_score?.toFixed(1) ?? '—'}/100`, color: (nums.integrity_score ?? 0) >= 90 ? '#26c281' : '#f59e0b' },
          ].map(kpi => (
            <div key={kpi.label} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{kpi.label}</span>
              <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: kpi.color }}>{kpi.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Explanation sections */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
        {[
          { icon: '📊', title: 'Signal Summary', text: exp.summary },
          { icon: '💪', title: 'Signal Strength', text: exp.signal_strength },
          { icon: '🎯', title: 'Confidence Calibration', text: exp.confidence_narrative },
          { icon: '📉', title: 'Data Quality', text: exp.data_quality_narrative },
          { icon: '🏗️', title: 'Market Integrity', text: exp.market_integrity_narrative },
          { icon: '⚡', title: 'Technical Drivers', text: exp.technical_drivers },
          { icon: '💰', title: 'Price Target', text: exp.price_target_narrative },
          { icon: '🔒', title: 'Risk Gate', text: exp.risk_gate_narrative },
          { icon: '🔄', title: 'Pipeline State', text: exp.pipeline_state_narrative },
        ].filter(s => s.text).map(section => (
          <div key={section.title} style={{ padding: '12px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
              {section.icon} {section.title}
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{section.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Signal card (expanded view) ───────────────────────────────────────────

function SignalCard({ row }: { row: SignalRow }): JSX.Element {
  const [showReasoning, setShowReasoning] = useState(false);
  const isShort = (row.action ?? '').toLowerCase().includes('short');
  const priceChange = row.expected_move_bps != null ? row.expected_move_bps / 100 : null;
  const executableConfidence = row.confidence_executable_trade ?? null;
  const selectedConfidence = row.confidence_selected_action ?? row.confidence ?? null;
  const confidenceLabel = row.confidence_display_label ?? 'Unproven confidence';
  const explorationTier = row.paper_exploration_tier ?? row.exploration_tier ?? null;
  const explorationBlocker = row.paper_exploration_current_blocker ?? 'not above floor';
  const paperFillTruth = row.paper_exploration_paper_fill_allowed === true ? 'PAPER_FILL_ALLOWED' : row.paper_exploration_paper_fill_allowed === false ? 'BLOCKED' : signalText(row.paper_fill_status, 'PENDING');

  return (
    <tr>
      <td colSpan={9} style={{ padding: 0 }}>
        <div style={{ background: 'var(--bg-elevated)', borderBottom: '2px solid var(--border)' }}>
          {/* Top info grid */}
          <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
            {/* Price target card */}
            <div style={{ gridColumn: 'span 2', padding: '12px 16px', background: isShort ? 'rgba(239,83,80,0.07)' : 'rgba(38,194,129,0.07)', borderRadius: 8, border: `1px solid ${isShort ? '#ef535030' : '#26c28130'}` }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Price Target</div>
              <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: actionColor(row.action) }}>{fmtPrice(row.price_target_after_cost ?? row.price_target)}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
                after cost · expected move {priceChange != null ? `${priceChange >= 0 ? '+' : ''}${priceChange.toFixed(2)}%` : '—'}
              </div>
            </div>
            {[
              ['Executable Confidence', fmtConf(executableConfidence), confColor(executableConfidence)],
              ['Confidence Type', confidenceLabel, executableConfidence != null && executableConfidence > 0 ? '#26c281' : '#f59e0b'],
              ['Paper Exploration', signalText(explorationTier, 'NONE'), explorationTier ? '#3b82f6' : 'var(--text-muted)'],
              ['Exploration Blocker', signalText(explorationBlocker), explorationBlocker === 'PAPER_FILL_ALLOWED' ? '#26c281' : '#f59e0b'],
              ['Paper Fill', paperFillTruth, row.paper_exploration_paper_fill_allowed ? '#26c281' : '#f59e0b'],
              ['Expected Net USD', fmtUsd(row.expected_net_pnl_usd), row.expected_net_pnl_usd != null && row.expected_net_pnl_usd > 0 ? '#26c281' : '#f59e0b'],
              ['Max Loss USD', fmtUsd(row.expected_max_loss_usd), '#f59e0b'],
              ['Why Not A+', signalText(firstReason(row.why_not_a_plus, 'A+ evidence not matured')), '#f59e0b'],
              ['Why Not Live', signalText(firstReason(row.why_not_live_ready, 'blocked_human_only')), '#ef5350'],
              ['Risk Controller', signalText(row.paper_exploration_risk_controller_decision ?? row.risk_controller_decision ?? row.risk_state), gateColor(row.risk_state)],
              ['Orchestrator', signalText(row.paper_exploration_orchestrator_decision ?? row.orchestrator_state, 'PENDING'), 'var(--text-muted)'],
              ['Allocator', signalText(row.paper_exploration_allocator_decision ?? row.allocator_decision, 'PENDING'), 'var(--text-muted)'],
              ['Trainer Feedback', signalText(row.trainer_feedback_status, 'PENDING'), 'var(--text-muted)'],
              ['Selected Confidence', fmtConf(selectedConfidence), 'var(--text-muted)'],
              ['Data Coverage', row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(1)}%` : '—', row.data_coverage_percent != null && row.data_coverage_percent >= 80 ? '#26c281' : '#f59e0b'],
              ['Integrity Score', row.market_state_integrity_score != null ? `${row.market_state_integrity_score.toFixed(1)}/100` : '—', (row.market_state_integrity_score ?? 0) >= 90 ? '#26c281' : '#f59e0b'],
              ['Risk State', publicRuntimeLabel(row.risk_state), gateColor(row.risk_state)],
              ['Execution State', publicRuntimeLabel(row.paper_fill_status), '#3b82f6'],
              ['Signal Age', fmtAge(row.age_seconds), row.age_seconds != null && row.age_seconds < 3600 ? 'var(--text-secondary)' : '#ef5350'],
              ['Generated', row.generated_at ? new Date(row.generated_at).toLocaleString() : '—', 'var(--text-muted)'],
            ].map(([label, value, color]) => (
              <div key={String(label)}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: String(color) }}>{value}</div>
              </div>
            ))}
          </div>

          {/* IDs */}
          <div style={{ padding: '8px 20px', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            {[['Signal ID', publicRuntimeId(row.signal_id)], ['Prediction ID', publicRuntimeId(row.prediction_id)]].map(([label, value]) => value ? (
              <div key={String(label)}>
                <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: 6 }}>{label}</span>
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{value}</span>
              </div>
            ) : null)}
          </div>

          {/* AI Reasoning toggle */}
          <div style={{ padding: '8px 20px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              style={{
                padding: '6px 14px', borderRadius: 6, border: `1px solid ${showReasoning ? 'var(--accent)' : 'rgba(255,255,255,0.1)'}`,
                background: showReasoning ? 'rgba(59,130,246,0.08)' : 'transparent',
                color: showReasoning ? 'var(--accent)' : 'var(--text-secondary)',
                fontSize: 11, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              🧠 {showReasoning ? 'Hide' : 'Show'} AI Reasoning & Evidence
            </button>
          </div>
          {showReasoning && <AIReasoningPanel symbol={row.symbol} timeframe={row.timeframe} />}
        </div>
      </td>
    </tr>
  );
}

// ─── Liquidation Heatmap Panel ────────────────────────────────────────────

const LIQ_TF_ORDER = ['1m', '5m', '15m', '1h', '4h'];

function fmtVol(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}k`;
  return `$${v.toFixed(0)}`;
}

function fmtBpsLiq(bps: number | null): string {
  if (bps == null) return '—';
  const pct = bps / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function cascadeColor(risk: number | null): string {
  if (risk == null) return 'var(--text-muted)';
  if (risk > 0.8) return '#ef5350';
  if (risk > 0.6) return '#f59e0b';
  return '#26c281';
}

function pressureLabel(p: number | null): string {
  if (p == null) return '—';
  if (p > 0.3) return 'LONG';
  if (p < -0.3) return 'SHORT';
  return 'NEUT';
}

function pressureColor(p: number | null): string {
  if (p == null) return 'var(--text-muted)';
  if (p > 0.3) return '#26c281';
  if (p < -0.3) return '#ef5350';
  return '#f59e0b';
}

function TFHeatCell({ row }: { row: LiqHeatmapRow }): JSX.Element {
  const [expanded, setExpanded] = React.useState(false);
  const longPct = row.long_pct ?? 50;
  const shortPct = row.short_pct ?? 50;
  const dominantIsLong = longPct >= shortPct;
  const dominantPct = Math.max(longPct, shortPct);
  const borderColor = dominantIsLong ? 'rgba(38,194,129,0.25)' : 'rgba(239,83,80,0.25)';
  return (
    <div
      onClick={() => setExpanded(e => !e)}
      style={{ cursor: 'pointer', background: 'var(--bg-base)', border: `1px solid ${borderColor}`, borderRadius: 6, padding: '5px 7px', minWidth: 72, position: 'relative' }}
    >
      {row.stale && <span style={{ position: 'absolute', top: 3, right: 4, fontSize: 8, color: '#f59e0b', fontWeight: 700 }}>STALE</span>}
      {/* Long/Short bar */}
      <div style={{ height: 5, borderRadius: 3, overflow: 'hidden', display: 'flex', marginBottom: 3 }}>
        <div style={{ width: `${longPct}%`, background: '#26c281', transition: 'width 0.3s' }} />
        <div style={{ width: `${shortPct}%`, background: '#ef5350', transition: 'width 0.3s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontFamily: 'var(--font-mono)' }}>
        <span style={{ color: '#26c281' }}>{longPct.toFixed(0)}%</span>
        <span style={{ color: 'var(--text-muted)', fontWeight: 700 }}>{row.timeframe}</span>
        <span style={{ color: '#ef5350' }}>{shortPct.toFixed(0)}%</span>
      </div>
      <div style={{ fontSize: 9, color: cascadeColor(row.cascade_risk), textAlign: 'center', marginTop: 1 }}>
        {row.cascade_risk != null ? `CR ${(row.cascade_risk * 100).toFixed(0)}%` : '—'}
      </div>
      {expanded && (
        <div style={{ marginTop: 5, paddingTop: 4, borderTop: '1px solid rgba(255,255,255,0.06)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 6px', fontSize: 9, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--text-muted)' }}>Sweep↓</span>
          <span style={{ color: '#ef5350' }}>{fmtBpsLiq(row.sweep_short_dist_bps)}</span>
          <span style={{ color: 'var(--text-muted)' }}>Sweep↑</span>
          <span style={{ color: '#26c281' }}>{fmtBpsLiq(row.sweep_long_dist_bps)}</span>
          <span style={{ color: 'var(--text-muted)' }}>Zones L</span>
          <span style={{ color: 'var(--text-primary)' }}>{row.zones_long}</span>
          <span style={{ color: 'var(--text-muted)' }}>Zones S</span>
          <span style={{ color: 'var(--text-primary)' }}>{row.zones_short}</span>
          <span style={{ color: 'var(--text-muted)' }}>5m evts</span>
          <span style={{ color: 'var(--text-primary)' }}>{row.count_5m}</span>
          <span style={{ color: 'var(--text-muted)' }}>Price</span>
          <span style={{ color: 'var(--text-secondary)' }}>{row.current_price != null ? `$${row.current_price.toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—'}</span>
          {row.sweep_target_short != null && (
            <>
              <span style={{ color: 'var(--text-muted)' }}>Short tgt</span>
              <span style={{ color: '#ef5350' }}>${row.sweep_target_short.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
            </>
          )}
          {row.sweep_target_long != null && (
            <>
              <span style={{ color: 'var(--text-muted)' }}>Long tgt</span>
              <span style={{ color: '#26c281' }}>${row.sweep_target_long.toLocaleString('en-US', { maximumFractionDigits: 0 })}</span>
            </>
          )}
          <span style={{ color: 'var(--text-muted)' }}>Pressure</span>
          <span style={{ color: pressureColor(row.pressure_direction), fontWeight: 700 }}>{pressureLabel(row.pressure_direction)}</span>
        </div>
      )}
    </div>
  );
}

interface LiquidationHeatmapPanelProps {
  pinnedDefaults?: string[];
}

function LiquidationHeatmapPanel({ pinnedDefaults }: LiquidationHeatmapPanelProps): JSX.Element {
  const initialSymbols = pinnedDefaults?.length
    ? new Set(pinnedDefaults.slice(0, 5))
    : new Set(['BTCUSDT', 'ETHUSDT', 'SOLUSDT']);

  const [selectedSyms, setSelectedSyms] = React.useState<Set<string>>(initialSymbols);
  const [showAll, setShowAll] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const [collapsed, setCollapsed] = React.useState(false);

  const { envelope, loading } = useRealtimeResource<LiqHeatmapData>({
    url: LIQ_HEATMAP_URL,
    source: LIQ_HEATMAP_URL,
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 12_000,
    mode: 'read_only',
    httpFallback: true,
    initialFetch: true,
  });

  const data = envelope.data;

  // Auto-update selection when pinned_defaults arrive from backend
  React.useEffect(() => {
    if (data?.pinned_defaults && data.pinned_defaults.length > 0) {
      setSelectedSyms(prev => {
        const hasNonDefault = Array.from(prev).some(s => !['BTCUSDT', 'ETHUSDT', 'SOLUSDT'].includes(s));
        if (hasNonDefault) return prev; // user customized — don't override
        return new Set(data.pinned_defaults.slice(0, 5));
      });
    }
  }, [data?.pinned_defaults?.join(',')]);

  const allSymbols = data?.symbols ?? [];
  const volBySymbol = data?.volume_by_symbol ?? {};

  const rowsBySymbol = React.useMemo(() => {
    const m: Record<string, Record<string, LiqHeatmapRow>> = {};
    for (const r of data?.rows ?? []) {
      if (!m[r.symbol]) m[r.symbol] = {};
      m[r.symbol][r.timeframe] = r;
    }
    return m;
  }, [data?.rows]);

  const displayedSymbols = React.useMemo(() => {
    const pool = showAll ? allSymbols : Array.from(selectedSyms);
    const q = search.trim().toUpperCase();
    return q ? pool.filter(s => s.includes(q)) : pool;
  }, [showAll, allSymbols, selectedSyms, search]);

  const toggleSym = (s: string) => setSelectedSyms(prev => {
    const n = new Set(prev);
    if (n.has(s)) { if (n.size > 1) n.delete(s); } else n.add(s);
    return n;
  });

  const topByVol = data?.top_by_volume ?? [];
  const staleCount = data?.stale_count ?? 0;
  const currentCount = data?.current_count ?? 0;

  return (
    <div style={{ margin: '16px 16px 0', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
      {/* Header */}
      <div
        onClick={() => setCollapsed(c => !c)}
        style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', borderBottom: collapsed ? 'none' : '1px solid var(--border)', userSelect: 'none' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 13, fontWeight: 700 }}>Liquidation Levels Heatmap</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', background: 'var(--bg-base)', padding: '2px 7px', borderRadius: 10, border: '1px solid var(--border)' }}>
            {data?.count ?? 0} cells · {data?.symbol_count ?? 0} symbols
          </span>
          {staleCount > 0 && (
            <span style={{ fontSize: 10, color: '#f59e0b', background: 'rgba(245,158,11,0.1)', padding: '2px 7px', borderRadius: 10, border: '1px solid rgba(245,158,11,0.3)' }}>
              {staleCount} stale
            </span>
          )}
          {currentCount > 0 && (
            <span style={{ fontSize: 10, color: '#26c281', background: 'rgba(38,194,129,0.08)', padding: '2px 7px', borderRadius: 10, border: '1px solid rgba(38,194,129,0.2)' }}>
              {currentCount} fresh
            </span>
          )}
          <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
          <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
        </div>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{collapsed ? '▶ Expand' : '▼ Collapse'}</span>
      </div>

      {!collapsed && (
        <div style={{ padding: '10px 14px' }}>
          {/* Legend */}
          <div style={{ display: 'flex', gap: 14, marginBottom: 10, fontSize: 10, color: 'var(--text-muted)', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 6, background: '#26c281', borderRadius: 2, display: 'inline-block' }} /> Long Liq
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 6, background: '#ef5350', borderRadius: 2, display: 'inline-block' }} /> Short Liq
            </span>
            <span>CR = Cascade Risk (bear pressure %) · Click cell for sweep targets</span>
            <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>WebSocket primary · API fallback</span>
          </div>

          {/* Symbol selector */}
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 5, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Symbols</span>
              <input
                value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter..."
                style={{ padding: '2px 7px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 10, width: 80, outline: 'none' }}
              />
              <button onClick={() => setShowAll(s => !s)} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>
                {showAll ? 'Pinned view' : `All (${allSymbols.length})`}
              </button>
              {topByVol.length > 0 && (
                <button onClick={() => setSelectedSyms(new Set(topByVol.slice(0, 5)))} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid rgba(245,158,11,0.4)', background: 'rgba(245,158,11,0.06)', color: '#f59e0b', fontSize: 10, cursor: 'pointer' }}>
                  Top 5 Liquidity
                </button>
              )}
              <button onClick={() => setSelectedSyms(new Set(['BTCUSDT', 'ETHUSDT', 'SOLUSDT']))} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>
                BTC/ETH/SOL
              </button>
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxHeight: 58, overflowY: 'auto' }}>
              {(showAll ? allSymbols : Array.from(new Set([...Array.from(selectedSyms), ...allSymbols]))).filter(s => !search || s.includes(search.toUpperCase())).slice(0, showAll ? 999 : 30).map(s => {
                const vol = volBySymbol[s];
                const isTop = topByVol.includes(s);
                return (
                  <button key={s} onClick={() => toggleSym(s)} style={{
                    padding: '2px 8px', borderRadius: 5, fontSize: 10, fontFamily: 'var(--font-mono)', cursor: 'pointer', fontWeight: selectedSyms.has(s) ? 700 : 400,
                    border: `1px solid ${selectedSyms.has(s) ? (isTop ? 'rgba(245,158,11,0.6)' : 'var(--accent)') : 'var(--border)'}`,
                    background: selectedSyms.has(s) ? (isTop ? 'rgba(245,158,11,0.1)' : 'rgba(59,130,246,0.1)') : 'transparent',
                    color: selectedSyms.has(s) ? (isTop ? '#f59e0b' : 'var(--accent)') : 'var(--text-secondary)',
                  }}>
                    {s.replace('USDT', '')}{vol && vol >= 100_000 ? ` ${fmtVol(vol)}` : ''}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Heatmap grid */}
          {loading && Object.keys(rowsBySymbol).length === 0 && (
            <LoadingSkeleton rows={3} />
          )}
          {!loading && Object.keys(rowsBySymbol).length === 0 && (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
              Liquidation stream connecting. Source status: {envelope.source_type} · {envelope.freshness_status}.
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {displayedSymbols.filter(s => rowsBySymbol[s]).map(sym => {
              const symRows = rowsBySymbol[sym] ?? {};
              const vol = volBySymbol[sym] ?? 0;
              const anyRow = Object.values(symRows)[0];
              const pressure = anyRow?.pressure_direction ?? null;
              const isTop = topByVol.slice(0, 5).includes(sym);
              return (
                <div key={sym} style={{ background: 'var(--bg-base)', border: `1px solid ${isTop ? 'rgba(245,158,11,0.2)' : 'var(--border)'}`, borderRadius: 8, padding: '8px 10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 7, flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>
                      {sym.replace('USDT', '')}<span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 10, marginLeft: 2 }}>USDT</span>
                    </span>
                    {vol > 0 && (
                      <span style={{ fontSize: 10, color: '#f59e0b', background: 'rgba(245,158,11,0.08)', padding: '1px 6px', borderRadius: 8, border: '1px solid rgba(245,158,11,0.2)' }}>
                        {fmtVol(vol)} total
                      </span>
                    )}
                    {isTop && (
                      <span style={{ fontSize: 9, color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>Top Liquidity</span>
                    )}
                    <span style={{ fontSize: 10, color: pressureColor(pressure), fontWeight: 700 }}>
                      {pressureLabel(pressure)}
                    </span>
                    {anyRow?.current_price != null && (
                      <span style={{ fontSize: 10, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginLeft: 'auto' }}>
                        ${anyRow.current_price.toLocaleString('en-US', { maximumFractionDigits: 2 })}
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                    {LIQ_TF_ORDER.map(tf => {
                      const row = symRows[tf];
                      if (!row) return (
                        <div key={tf} style={{ minWidth: 72, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)', borderRadius: 6, padding: '5px 7px', textAlign: 'center' }}>
                          <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.15)', fontFamily: 'var(--font-mono)' }}>{tf}</span>
                          <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.1)', marginTop: 4 }}>awaiting</div>
                        </div>
                      );
                      return <TFHeatCell key={tf} row={row} />;
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid rgba(255,255,255,0.04)', fontSize: 10, color: 'var(--text-muted)' }}>
            Source: {envelope.source_type === 'static_payload' ? 'runtime-status fallback' : 'Redis v2:liquidations:levels:{symbol}:{tf}'} · WebSocket interval 2s · Levels engine publishes every ~5s
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sort header ──────────────────────────────────────────────────────────

type SortKey = 'symbol' | 'timeframe' | 'action' | 'confidence' | 'age_seconds' | 'price_target';
type SortDir = 'asc' | 'desc';

function SortTh({ label, col, current, dir, onSort }: { label: string; col: SortKey; current: SortKey; dir: SortDir; onSort: (c: SortKey) => void }): JSX.Element {
  const active = current === col;
  return (
    <th onClick={() => onSort(col)} style={{ padding: '8px 12px', textAlign: 'left', cursor: 'pointer', userSelect: 'none', borderBottom: '1px solid var(--border)', color: active ? 'var(--accent)' : 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, whiteSpace: 'nowrap', background: 'var(--bg-panel)' }}>
      {label}{active ? (dir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────

export default function SignalsPage(): JSX.Element {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set(DEFAULT_SYMBOLS));
  const [selectedTFs, setSelectedTFs] = useState<Set<TF>>(new Set(TIMEFRAMES));
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [showAllSymbols, setShowAllSymbols] = useState(false);
  const [symbolSearch, setSymbolSearch] = useState('');
  const [routeFilter, setRouteFilter] = useState<'all' | 'ready' | 'live' | 'blocked'>('all');
  const traderSnapshot = useTraderSnapshot();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const currentLineage = useCurrentRuntimeLineage(10_000);

  const symbolsParam = Array.from(selectedSymbols).join(',');
  const tfsParam = Array.from(selectedTFs).join(',');
  const url = `/api/v2/signals/matrix?symbols=${symbolsParam}&timeframes=${tfsParam}`;

  const { envelope, loading, refetch } = useRealtimeResource<SignalMatrixData>({
    url, source: '/api/v2/signals/matrix', source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 20_000, mode: 'read_only',
  });
  const { envelope: allEnv } = useRealtimeResource<SignalMatrixData>({
    url: '/api/v2/signals/matrix', source: '/api/v2/signals/matrix', source_type: 'websocket', pollIntervalMs: 60_000, mode: 'read_only',
  });
  const { envelope: currentSignalEnvelope } = useRealtimeResource<SignalCurrentContract>({
    url: '/api/v2/signals/current',
    source: '/api/v2/signals/current',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 20_000,
    mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const { envelope: aPlusEnvelope } = useRealtimeResource<APlusInventoryContract>({
    url: '/api/v2/a-plus/inventory',
    source: '/api/v2/a-plus/inventory',
    source_type: 'websocket',
    pollIntervalMs: 15_000,
    staleThresholdMs: 45_000,
    mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const { envelope: providerEnvelope } = useRealtimeResource<ProviderStatusContract>({
    url: '/api/v2/providers/status',
    source: '/api/v2/providers/status',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const lineageSignalRow = useMemo(() => signalRowFromLineage(currentLineage.envelope.data), [currentLineage.envelope.data]);
  const matrixRows = envelope.data?.rows ?? [];
  const rows = useMemo(
    () => matrixRows.length ? matrixRows : lineageSignalRow ? [lineageSignalRow] : [],
    [lineageSignalRow, matrixRows],
  );
  const usingLineageFallback = matrixRows.length === 0 && rows.length > 0;
  const allSymbols = useMemo(() => {
    const next = new Set(allEnv.data?.symbols ?? []);
    if (lineageSignalRow?.symbol) next.add(lineageSignalRow.symbol);
    return Array.from(next);
  }, [allEnv.data?.symbols, lineageSignalRow?.symbol]);

  // Route filter
  const filteredRows = useMemo(() => {
    if (routeFilter === 'all') return rows;
    if (routeFilter === 'ready') return rows.filter(r => ['open', 'allow', 'allowed', 'ready', 'routed'].some((token) => ((r.paper_fill_gate_status ?? r.paper_fill_status) ?? '').toLowerCase().includes(token)));
    if (routeFilter === 'live') return rows.filter(r => (r.live_gate ?? '').toLowerCase().includes('open') && !(r.live_gate ?? '').toLowerCase().includes('blocked'));
    if (routeFilter === 'blocked') return rows.filter(r => (r.live_gate ?? '').toLowerCase().includes('blocked') && !['open', 'allow', 'allowed', 'ready', 'routed'].some((token) => ((r.paper_fill_gate_status ?? r.paper_fill_status) ?? '').toLowerCase().includes(token)));
    return rows;
  }, [rows, routeFilter]);

  const sorted = useMemo(() => {
    const copy = [...filteredRows];
    copy.sort((a, b) => {
      let av: string | number = 0, bv: string | number = 0;
      if (sortKey === 'symbol') { av = a.symbol; bv = b.symbol; }
      else if (sortKey === 'timeframe') { const o: Record<string, number> = { '1m': 0, '5m': 1, '15m': 2, '1h': 3, '4h': 4 }; av = o[a.timeframe] ?? 99; bv = o[b.timeframe] ?? 99; }
      else if (sortKey === 'action') { av = a.action ?? ''; bv = b.action ?? ''; }
      else if (sortKey === 'confidence') {
        av = a.confidence_executable_trade ?? a.confidence_selected_action ?? a.confidence ?? -1;
        bv = b.confidence_executable_trade ?? b.confidence_selected_action ?? b.confidence ?? -1;
      }
      else if (sortKey === 'age_seconds') { av = a.age_seconds ?? 999999; bv = b.age_seconds ?? 999999; }
      else if (sortKey === 'price_target') { av = a.price_target_after_cost ?? a.price_target ?? -1; bv = b.price_target_after_cost ?? b.price_target ?? -1; }
      if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av;
      return 0;
    });
    return copy;
  }, [filteredRows, sortKey, sortDir]);

  const handleSort = useCallback((col: SortKey) => {
    if (col === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortKey(col); setSortDir('asc'); }
  }, [sortKey]);

  const toggleSymbol = useCallback((s: string) => {
    setSelectedSymbols(prev => { const n = new Set(prev); if (n.has(s)) { if (n.size > 1) n.delete(s); } else n.add(s); return n; });
  }, []);

  const displayedSymbols = useMemo(() => {
    const filter = symbolSearch.trim().toUpperCase();
    const pool = showAllSymbols ? allSymbols : DEFAULT_SYMBOLS;
    return filter ? pool.filter(s => s.includes(filter)) : pool;
  }, [showAllSymbols, allSymbols, symbolSearch]);

  const readyCount = rows.filter(r => ['open', 'allow', 'allowed', 'ready', 'routed'].some((token) => ((r.paper_fill_gate_status ?? r.paper_fill_status) ?? '').toLowerCase().includes(token))).length;
  const liveCount = rows.filter(r => (r.live_gate ?? '').toLowerCase() === 'open').length;
  const avgConf = rows.length > 0
    ? rows.reduce((s, r) => s + (r.confidence_executable_trade ?? r.confidence_selected_action ?? r.confidence ?? 0), 0) / rows.length
    : null;
  const signalFeedReady = rows.length > 0;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.signal_prediction_accuracy_status
    ?? null;
  const evaluatedAccuracyCells = accuracyStatus?.evaluated_symbol_timeframe_cell_count;
  const totalAccuracyCells = accuracyStatus?.symbol_timeframe_cell_count
    ?? accuracyStatus?.required_symbol_timeframe_cell_count;
  const missingAccuracyCells = missingAccuracyCellCount(accuracyStatus);
  const canonicalSignal = selectActiveSignal(traderSnapshot);
  const signalMetric = (fieldId: string) => selectSignalMetric(traderSnapshot, canonicalSignal ?? {}, fieldId);

  return (
    <div data-testid="page-signals" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Signals</h1>
            <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
              Published signal routing · Trainer → Risk Gate → Execution Engine · {signalFeedReady ? rows.length : '—'} signals · {allSymbols.length || '—'} symbols in scope
              {usingLineageFallback ? ' · current runtime lineage' : ''}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>

        {/* KPI strip */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          {[
            { label: 'Total Signals', value: signalFeedReady ? rows.length : '—', color: 'var(--text-primary)' },
            { label: 'Execution Ready', value: signalFeedReady ? readyCount : '—', color: '#3b82f6' },
            { label: 'Live Routed', value: signalFeedReady ? liveCount : '—', color: liveCount > 0 ? '#26c281' : 'var(--text-muted)' },
            { label: 'Long', value: signalFeedReady ? rows.filter(r => (r.action ?? '').toLowerCase().includes('long')).length : '—', color: '#26c281' },
            { label: 'Short', value: signalFeedReady ? rows.filter(r => (r.action ?? '').toLowerCase().includes('short')).length : '—', color: '#ef5350' },
            { label: 'Avg Executable Confidence', value: avgConf != null ? fmtConf(avgConf) : '—', color: confColor(avgConf) },
            { label: 'Accuracy', value: formatAdaptivePercent(accuracyStatus?.overall_accuracy), color: adaptiveStatusColor(accuracyStatus?.status) },
            { label: 'Evaluated', value: accuracyStatus?.evaluated_row_count ?? '—', color: 'var(--text-primary)' },
            { label: 'TF Cells', value: evaluatedAccuracyCells != null || totalAccuracyCells != null ? `${evaluatedAccuracyCells ?? 0}/${totalAccuracyCells ?? 0}` : '—', color: 'var(--text-primary)' },
            { label: 'Missing Cells', value: missingAccuracyCells ?? '—', color: (missingAccuracyCells ?? 0) > 0 ? '#ef5350' : '#26c281' },
          ].map(k => (
            <div key={k.label} style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 12px', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k.label}</span>
              <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: k.color }}>{k.value}</span>
            </div>
          ))}
        </div>

        <div className="trader-metric-grid" style={{ marginBottom: 12 }}>
          <CanonicalMetricCard label="Active Signal ID" metric={signalMetric('signal.id')} />
          <CanonicalMetricCard label="Executable Signal Confidence" metric={signalMetric('signal.confidence')} />
        </div>

        {/* Route filter */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', alignSelf: 'center', marginRight: 4 }}>Filter by Routing</span>
          {(['all', 'ready', 'live', 'blocked'] as const).map(f => (
            <button key={f} onClick={() => setRouteFilter(f)} style={{
              padding: '4px 12px', borderRadius: 6, fontSize: 11, fontWeight: routeFilter === f ? 700 : 400, cursor: 'pointer',
              border: `1px solid ${routeFilter === f ? (f === 'ready' ? '#3b82f6' : f === 'live' ? '#26c281' : f === 'blocked' ? '#ef5350' : 'var(--accent)') : 'var(--border)'}`,
              background: routeFilter === f ? (f === 'ready' ? 'rgba(59,130,246,0.12)' : f === 'live' ? 'rgba(38,194,129,0.12)' : f === 'blocked' ? 'rgba(239,83,80,0.1)' : 'rgba(59,130,246,0.1)') : 'transparent',
              color: routeFilter === f ? (f === 'ready' ? '#3b82f6' : f === 'live' ? '#26c281' : f === 'blocked' ? '#ef5350' : 'var(--accent)') : 'var(--text-secondary)',
            }}>
              {f === 'all' ? 'All' : f === 'ready' ? 'Ready' : f === 'live' ? 'Live' : 'Gated'}
            </button>
          ))}
          <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center', marginLeft: 4 }}>{signalFeedReady ? sorted.length : '—'} shown</span>
        </div>

        {/* Symbol selector */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Symbols</span>
            <input value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)} placeholder="Filter..." style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 11, width: 90, outline: 'none' }} />
            <button onClick={() => setShowAllSymbols(s => !s)} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>
              {showAllSymbols ? `Default (${DEFAULT_SYMBOLS.length})` : `All (${allSymbols.length || '—'})`}
            </button>
            <button onClick={() => setSelectedSymbols(new Set(['BTCUSDT', 'ETHUSDT', 'SOLUSDT']))} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>BTC/ETH/SOL</button>
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxHeight: 64, overflowY: 'auto' }}>
            {displayedSymbols.map(s => (
              <button key={s} onClick={() => toggleSymbol(s)} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 10, fontWeight: selectedSymbols.has(s) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedSymbols.has(s) ? 'var(--accent)' : 'var(--border)'}`, background: selectedSymbols.has(s) ? 'rgba(59,130,246,0.12)' : 'transparent', color: selectedSymbols.has(s) ? 'var(--accent)' : 'var(--text-secondary)' }}>
                {s.replace('USDT', '')}
              </button>
            ))}
          </div>
        </div>

        {/* TF filter */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: 4 }}>Timeframes</span>
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => {
              setSelectedTFs(prev => { const n = new Set(prev); if (n.has(tf)) { if (n.size > 1) n.delete(tf); } else n.add(tf); return n; });
            }} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 11, fontWeight: selectedTFs.has(tf) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedTFs.has(tf) ? 'var(--accent)' : 'var(--border)'}`, background: selectedTFs.has(tf) ? 'rgba(59,130,246,0.12)' : 'transparent', color: selectedTFs.has(tf) ? 'var(--accent)' : 'var(--text-secondary)' }}>
              {tf}
            </button>
          ))}
        </div>
      </div>

      <SignalRuntimeTruthPanel
        current={currentSignalEnvelope.data}
        currentEnvelope={currentSignalEnvelope}
        aPlus={aPlusEnvelope.data}
        providers={providerEnvelope.data}
      />

      <div style={{ padding: '12px 16px 0' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Signal Accuracy + Capital Productivity"
          compact
          showMatrix
          maxMatrixHeight={260}
        />
      </div>

      {/* Table */}
      <div style={{ padding: 16 }}>
        {loading && sorted.length === 0 && <LoadingSkeleton rows={8} />}
        {!loading && sorted.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', background: 'var(--bg-panel)', borderRadius: 12, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>📡</div>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>Signal stream connecting. Existing panels stay mounted while WebSocket and HTTP fallback connect.</p>
          </div>
        )}
        {sorted.length > 0 && (
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    <SortTh label="Symbol" col="symbol" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="TF" col="timeframe" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Direction" col="action" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Executable Confidence" col="confidence" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Accuracy / PnL</th>
                    <SortTh label="Price Target" col="price_target" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Routing</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Coverage</th>
                    <SortTh label="Age" col="age_seconds" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(row => {
                    const rowKey = `${row.symbol}:${row.timeframe}`;
                    const expanded = expandedRow === rowKey;
                    const accuracy = lookupAccuracyCell(accuracyStatus, row.symbol, row.timeframe);
                    return (
                      <React.Fragment key={rowKey}>
                        <tr onClick={() => setExpandedRow(expanded ? null : rowKey)}
                          style={{ cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.04)', background: expanded ? 'var(--bg-elevated)' : 'transparent', transition: 'background 0.1s' }}
                          onMouseEnter={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'; }}
                          onMouseLeave={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>
                            {row.symbol.replace('USDT', '')}<span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 10, marginLeft: 2 }}>USDT</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', padding: '2px 6px', background: 'var(--bg-base)', borderRadius: 4, border: '1px solid var(--border)' }}>{row.timeframe}</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}><ActionBadge action={row.side ?? row.action} /></td>
                          <td style={{ padding: '10px 12px' }}><ConfBar value={row.confidence_executable_trade ?? null} /></td>
                          <td style={{ padding: '10px 12px' }}><AccuracyBadge cell={accuracy} /></td>
                          <td style={{ padding: '10px 12px' }}><PriceTargetCell target={row.price_target_after_cost ?? row.price_target} moveBps={row.expected_move_bps} action={row.action} /></td>
                          <td style={{ padding: '10px 12px' }}><RoutingBadge gateStatus={row.live_gate} paperFill={row.paper_fill_gate_status ?? row.paper_fill_status} /></td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: row.data_coverage_percent != null && row.data_coverage_percent >= 80 ? '#26c281' : '#f59e0b' }}>
                            {row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(0)}%` : '—'}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: row.age_seconds != null && row.age_seconds < 3600 ? 'var(--text-secondary)' : '#ef5350' }}>
                            {fmtAge(row.age_seconds)}
                          </td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{expanded ? '▲' : '▶'}</td>
                        </tr>
                        {expanded && <SignalCard row={row} />}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div style={{ marginTop: 12, padding: '8px 0', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
            Signal routing: Trainer → Redis signal stream → Risk Gateway → Live Trader · {sorted.length} rows shown
          </p>
        </div>
      </div>

      {/* Liquidation Levels Heatmap Panel */}
      <LiquidationHeatmapPanel />
      <div style={{ height: 24 }} />
    </div>
  );
}
