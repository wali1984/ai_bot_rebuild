import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { CanonicalMetricCard } from '../../components/data/CanonicalMetric';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { Donut, DonutLegend, MetricBars, RadialGauge, ChartFrame, pctThresholdColor } from '../../components/charts/NervyxCharts';
import { selectActiveSignal, selectSignalMetric } from '../../selectors/signalSelectors';
import type { CanonicalMetric } from '../../selectors/accountSelectors';
import {
  publicRuntimeId,
  runtimeAgeSeconds,
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

interface PredRow {
  symbol: string;
  timeframe: string;
  action: string | null;
  confidence_calibrated: number | null;
  confidence_raw: number | null;
  data_coverage_percent: number | null;
  market_state_integrity_score: number | null;
  missing_feature_count: number | null;
  top_action: string | null;
  top_prob: number | null;
  second_action: string | null;
  second_prob: number | null;
  cuda_available: boolean | null;
  checkpoint_id: string | null;
  generated_at: string | null;
  age_seconds: number | null;
  action_probs: Record<string, number> | null;
  masa_signal: number | null;
  policy_value: number | null;
  temperature: number | null;
  coverage_factor: number | null;
  price_target: number | null;
  expected_move_bps: number | null;
}

interface PredMatrixData {
  rows: PredRow[];
  count: number;
  symbols: string[];
  symbol_count: number;
  timeframes: string[];
  missing: string[];
}

interface ExplainData {
  symbol: string;
  timeframe: string;
  generated_at: string | null;
  explanation: {
    summary: string;
    signal_strength: string;
    decision_narrative?: string;
    market_context_narrative?: string;
    confidence_narrative: string;
    data_quality_narrative: string;
    market_integrity_narrative: string;
    technical_drivers: string;
    price_target_narrative: string;
    risk_gate_narrative: string;
    pipeline_state_narrative: string;
    full_text: string;
  };
  key_numbers: {
    action: string;
    confidence_calibrated: number;
    confidence_raw: number;
    dominant_prob: number;
    expected_move_bps: number;
    price_target: number | null;
    data_coverage_pct: number;
    integrity_score: number;
    masa_signal: number | null;
    policy_value: number | null;
    missing_feature_count: number;
  };
  missing_feature_alert?: {
    active: boolean;
    severity: 'none' | 'info' | 'warn' | 'critical' | 'unknown';
    operational: boolean;
    prediction_still_produced: boolean;
    data_coverage_pct: number | null;
    missing_feature_count: number;
    stale_feature_count: number;
    missing_by_category: Record<string, number>;
    missing_provider_names: string[];
    message: string;
  };
}

interface TrainerSummary {
  state: string;
  checkpoint_id?: string | null;
  uptime_days?: number | null;
  win_rate_30d?: number | null;
  episodes_total?: number | null;
  drift_watch_count?: number | null;
  drift_alarm_count?: number | null;
}

interface TrainerLearningStatus {
  learning_active?: boolean | null;
  weights_updating?: boolean | null;
  learning_update_lane?: string | null;
  loss_before?: number | null;
  loss_after?: number | null;
  optimizer_steps_this_cycle?: number | null;
  optimizer_steps_total?: number | null;
  weight_delta_norm?: number | null;
  last_successful_weight_update_at?: string | null;
  feedback_rows_consumed?: number | null;
  trusted_replay_rows_loaded?: number | null;
  checkpoint_reload_verified?: boolean | null;
}
interface PpoRuntimeStatus {
  ppo_objective_used?: boolean | null;
  ppo_value_entropy_active?: boolean | null;
  ppo_value_loss?: number | null;
  ppo_policy_loss?: number | null;
  ppo_entropy?: number | null;
  ppo_on_policy_rows?: number | null;
  exact_blocker?: string | null;
}
interface GpuRuntime {
  gpu_name?: string | null;
  cuda_available?: boolean | null;
  model_device?: string | null;
  current_vram_used_mb?: number | null;
  vram_reserved_mb?: number | null;
  vram_cap_mb?: number | null;
  gpu_train_time_ms?: number | null;
  data_loader_time_ms?: number | null;
  backtest_rows_per_second?: number | null;
  throughput_predictions_per_second?: number | null;
  training_steps_per_minute?: number | null;
  mixed_precision_enabled?: boolean | null;
  oom_count?: number | null;
  target_batch_size?: number | null;
  actual_batch_size?: number | null;
  cpu_prep_bottleneck?: boolean | null;
}
interface ModelEdgeBacktest {
  win_rate?: number | null;
  expectancy_after_cost_bps?: number | null;
  profit_factor_proxy?: number | null;
  rows_evaluated?: number | null;
  a_plus_readiness_signal?: boolean | null;
  evidence_class?: string | null;
  status?: string | null;
}
interface RuntimeMode {
  effective_trainer_mode?: string | null;
  online_learning_status?: string | null;
  cuda_inference_status?: string | null;
  trainer_process_status?: string | null;
  prediction_publication_status?: string | null;
  prediction_examples_built?: number | null;
  prediction_failure_count?: number | null;
  replay_buffer_size?: number | null;
  replay_buffer_limit?: number | null;
  symbols_count?: number | null;
  timeframes?: string[] | null;
  examples_built?: number | null;
  paper_shadow_only?: boolean | null;
  checkpoint_promoted_this_cycle?: boolean | null;
  checkpoint_promotion_reason?: string | null;
}
interface LearningMetricsExtra {
  train_val_generalization_gap?: number | null;
  validation_loss_delta?: number | null;
  validation_supervised_loss?: number | null;
  validation_improved?: boolean | null;
  overfit_gap_warning?: boolean | null;
  expected_move_loss?: number | null;
  masa_loss?: number | null;
  confidence_loss?: number | null;
  entropy_coefficient?: number | null;
}
interface ModelArchitecture {
  hidden_size?: number | null;
  residual_block_count?: number | null;
  action_count?: number | null;
  dropout?: number | null;
  value_head?: boolean | null;
  confidence_head?: boolean | null;
  expected_move_head?: boolean | null;
  masa_auxiliary_head?: boolean | null;
  ppo_policy_head?: boolean | null;
  masa_adapter_blend?: boolean | null;
  temporal_encoder?: string | null;
  temporal_encoder_enabled?: boolean | null;
  temporal_seq_len?: number | null;
}
interface ChampionChallengerHoldout {
  directional_accuracy?: number | null;
  after_cost_expectancy_bps?: number | null;
  trade_count?: number | null;
  false_positive_rate?: number | null;
}
interface ChampionChallengerStatus {
  status?: string | null;
  result_status?: string | null;
  best_challenger_id?: string | null;
  promotion_allowed?: boolean | null;
  promotion_reason?: string | null;
  paper_challenger_enabled?: boolean | null;
  holdout_metrics?: ChampionChallengerHoldout | null;
}
interface AGradeTrainer {
  online_learning_status?: string | null;
  effective_trainer_mode?: string | null;
  checkpoint_promotion_reason?: string | null;
  validation_loss_delta?: number | null;
  train_val_generalization_gap?: number | null;
}
interface AGradeSection {
  A_grade_rows?: number | null;
  near_A_grade_rows?: number | null;
  status?: string | null;
  guardian_status?: string | null;
  guardian_new_entries_allowed?: boolean | null;
}
interface AGradeBlockerTruth {
  status?: string | null;
  primary_blocker?: string | null;
  trainer?: AGradeTrainer | null;
  a_grade?: AGradeSection | null;
}
interface RealTraderReadiness {
  live_ready?: boolean | null;
  live_submit_allowed?: boolean | null;
  exact_no_live_reason?: string | null;
  readiness_blockers?: string[] | null;
  operator_flip_required?: boolean | null;
}

interface TrainerStatusContract {
  state?: string | null;
  checkpoint_id?: string | null;
  model_source?: string | null;
  model_id?: string | null;
  cuda_active?: boolean | null;
  data_coverage?: number | null;
  live_gate?: string | null;
  routes_to_live?: boolean | null;
  places_real_order?: boolean | null;
  freshness_status?: string | null;
  staleness_seconds?: number | null;
  source?: string | null;
  input_dim?: number | null;
  feature_count?: number | null;
  feature_schema_status?: string | null;
  temporal_encoder?: string | null;
  temporal_encoder_enabled?: boolean | null;
  temporal_seq_len?: number | null;
  learning_active?: boolean | null;
  weights_updating?: boolean | null;
  last_training_step?: string | null;
  trainer_learning_status?: TrainerLearningStatus | null;
  ppo_runtime_status?: PpoRuntimeStatus | null;
  gpu_runtime?: GpuRuntime | null;
  model_edge_backtest?: ModelEdgeBacktest | null;
  runtime_mode?: RuntimeMode | null;
  learning_metrics_extra?: LearningMetricsExtra | null;
  model_architecture?: ModelArchitecture | null;
  champion_challenger_status?: ChampionChallengerStatus | null;
  a_grade_blocker_truth?: AGradeBlockerTruth | null;
  real_trader_readiness?: RealTraderReadiness | null;
  live_ready?: boolean | null;
  exact_no_live_reason?: string | null;
  readiness_blockers?: string[] | null;
}

interface ProviderStatusCard {
  provider: string;
  dashboard_color?: string | null;
  actual_payload_count?: number | null;
  feature_count?: number | null;
  actual_payload_present?: boolean | null;
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
// BTC/ETH/SOL are always pinned; additional symbols come from liquidation volume ranking
const PINNED_CORE = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'] as const;
const ACTION_COLORS: Record<string, string> = {
  long: '#26c281', long_strong: '#0fa86a', long_scaled: '#4ade80',
  short: '#ef5350', short_strong: '#d32f2f', short_scaled: '#ff7875',
  close_long: '#f59e0b', close_short: '#f59e0b', reduce: '#f59e0b',
  hold: '#f59e0b', hedge_reserved_fail_closed: 'var(--text-muted)',
};

// ─── Helpers ──────────────────────────────────────────────────────────────

function actionColor(a: string | null | undefined): string {
  if (!a) return 'var(--text-muted)';
  const key = a.toLowerCase();
  if (key.includes('short')) return ACTION_COLORS.short;
  if (key.includes('long_strong')) return ACTION_COLORS.long_strong;
  if (key.includes('long_scaled')) return ACTION_COLORS.long_scaled;
  if (key.includes('long')) return ACTION_COLORS.long;
  if (key.includes('hold')) return ACTION_COLORS.hold;
  if (key.includes('close') || key.includes('reduce')) return ACTION_COLORS.close_long;
  return ACTION_COLORS[key] ?? 'var(--text-muted)';
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

function predictionRowFromLineage(payload: CurrentRuntimeLineagePayload | null | undefined): PredRow | null {
  if (!payload) return null;
  const trainer = runtimeRecord(payload.trainer_prediction);
  const signal = runtimeRecord(payload.signal);
  const risk = runtimeRecord(payload.risk_decision);
  const rawOutput = runtimeRecord(trainer.raw_output);
  const drivers = runtimeRecord(trainer.reasoning_drivers);
  const generatedAt = runtimeText(trainer.generated_at, signal.generated_at, risk.generated_at, payload.generated_at);
  const symbol = runtimeText(trainer.symbol, signal.symbol);
  if (!symbol) return null;
  const topAction = runtimeText(rawOutput.side, signal.side, trainer.direction);
  const topProb = runtimeNumber(trainer.confidence_raw, drivers.confidence_raw);
  return {
    symbol,
    timeframe: runtimeText(trainer.timeframe) ?? '1m',
    action: runtimeText(rawOutput.side, signal.side, trainer.direction),
    confidence_calibrated: runtimeNumber(trainer.confidence_calibrated, signal.confidence_calibrated, drivers.confidence_calibrated),
    confidence_raw: topProb,
    data_coverage_percent: runtimeNumber(trainer.data_coverage_pct, drivers.data_coverage_pct),
    market_state_integrity_score: runtimeNumber(drivers.market_state_integrity_score),
    missing_feature_count: runtimeNumber(drivers.missing_feature_count),
    top_action: topAction,
    top_prob: topProb,
    second_action: null,
    second_prob: null,
    cuda_available: null,
    checkpoint_id: runtimeText(trainer.model_checkpoint, trainer.model_version),
    generated_at: generatedAt,
    age_seconds: runtimeNumber(trainer.market_age_seconds, signal.market_age_seconds, runtimeAgeSeconds(generatedAt)),
    action_probs: null,
    masa_signal: runtimeNumber(drivers.masa_signal),
    policy_value: runtimeNumber(drivers.policy_value),
    temperature: null,
    coverage_factor: null,
    price_target: null,
    expected_move_bps: runtimeNumber(risk.expected_move_after_cost_bps, risk.expected_move_bps, trainer.expected_move_bps),
  };
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

// ─── Prob bars ────────────────────────────────────────────────────────────

function ProbBar({ label, prob, maxProb = 1 }: { label: string; prob: number; maxProb?: number }): JSX.Element {
  const color = actionColor(label);
  const pct = (prob / Math.max(maxProb, 0.01)) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <div style={{ minWidth: 130, fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{label.replace(/_/g, ' ')}</div>
      <div style={{ flex: 1, height: 10, background: 'rgba(255,255,255,0.05)', borderRadius: 5, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 5 }} />
      </div>
      <div style={{ minWidth: 46, textAlign: 'right', fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700, color }}>{(prob * 100).toFixed(2)}%</div>
    </div>
  );
}

// ─── Calibration gauge ────────────────────────────────────────────────────

function CalibGauge({ raw, calibrated, temperature, coverageFactor }: { raw: number | null; calibrated: number | null; temperature: number | null; coverageFactor: number | null }): JSX.Element {
  const rawPct = raw != null ? Math.min(100, (Math.abs(raw) <= 1 ? raw : raw / 100) * 100) : 0;
  const calPct = calibrated != null ? Math.min(100, (Math.abs(calibrated) <= 1 ? calibrated : calibrated / 100) * 100) : 0;
  const calColor = confColor(calibrated);
  return (
    <div style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '10px 14px' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Confidence Calibration</div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>Raw</div>
          <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{fmtConf(raw)}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', color: 'var(--text-muted)', fontSize: 14, alignSelf: 'center' }}>→</div>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 2 }}>Calibrated</div>
          <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: calColor }}>{fmtConf(calibrated)}</div>
        </div>
      </div>
      <div style={{ position: 'relative', height: 14, background: 'rgba(255,255,255,0.05)', borderRadius: 7, overflow: 'hidden', marginBottom: 8 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: `${rawPct}%`, background: 'rgba(255,255,255,0.15)', borderRadius: 7 }} />
        <div style={{ position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)', height: 6, width: `${calPct}%`, background: calColor, borderRadius: 3 }} />
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {[
          ['Temp', temperature?.toFixed(2) ?? '—'],
          ['Cov. Factor', coverageFactor?.toFixed(3) ?? '—'],
          ['Delta', raw != null && calibrated != null ? `${((calibrated - raw) * 100).toFixed(1)}pp` : '—'],
        ].map(([l, v]) => (
          <div key={l}>
            <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: 4 }}>{l}</span>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── AI Reasoning panel ────────────────────────────────────────────────────

function ReasoningPanel({ symbol, timeframe }: { symbol: string; timeframe: string }): JSX.Element {
  const { envelope, loading } = useRealtimeResource<ExplainData>({
    url: `/api/v2/predictions/explain?symbol=${symbol}&timeframe=${timeframe}`,
    source: 'ai_explain',
    pollIntervalMs: 120_000,
    mode: 'read_only',
  });
  const exp = envelope.data?.explanation;
  const nums = envelope.data?.key_numbers;
  const featureAlert = envelope.data?.missing_feature_alert;
  const alertColor = (sev: string): string =>
    sev === 'critical' ? '#ef5350' : sev === 'warn' ? '#f59e0b' : sev === 'info' ? '#38bdf8' : '#26c281';

  if (loading && !exp) {
    return (
      <div style={{ padding: '14px 18px', background: 'rgba(99,102,241,0.04)', borderRadius: 8, border: '1px solid rgba(99,102,241,0.15)' }}>
        <span style={{ fontSize: 12, color: '#6366f1' }}>Loading AI analysis from live model data…</span>
      </div>
    );
  }
  if (!exp) {
    return (
      <div style={{ padding: '12px 16px', background: 'rgba(0,0,0,0.15)', borderRadius: 8 }}>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>AI reasoning not yet available — backend explain endpoint may need deploying.</p>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {featureAlert && featureAlert.active && (
        <div
          data-testid="missing-feature-alert"
          style={{
            padding: '10px 14px',
            background: `${alertColor(featureAlert.severity)}18`,
            border: `1px solid ${alertColor(featureAlert.severity)}55`,
            borderRadius: 8,
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: alertColor(featureAlert.severity) }}>
              ⚠ Degraded inputs — {featureAlert.severity}
            </span>
            <span style={{ fontSize: 11, color: '#26c281', fontWeight: 700 }}>
              ✓ prediction still produced (operating on masked inputs)
            </span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>Coverage: <b>{featureAlert.data_coverage_pct != null ? `${featureAlert.data_coverage_pct.toFixed(1)}%` : '—'}</b></span>
            <span>Missing: <b>{featureAlert.missing_feature_count}</b></span>
            <span>Stale: <b>{featureAlert.stale_feature_count}</b></span>
          </div>
          {Object.keys(featureAlert.missing_by_category || {}).length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {Object.entries(featureAlert.missing_by_category).map(([cat, n]) => (
                <span key={cat} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 10, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>
                  {cat.replace(/_/g, ' ')}: {n}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {nums && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
          {[
            { label: 'MASA Signal', value: nums.masa_signal?.toFixed(3) ?? '—', color: nums.masa_signal != null ? (nums.masa_signal < -0.5 ? '#ef5350' : nums.masa_signal > 0.5 ? '#26c281' : '#f59e0b') : 'var(--text-muted)', note: 'momentum alignment score' },
            { label: 'Policy Value', value: nums.policy_value?.toFixed(3) ?? '—', color: nums.policy_value != null ? (nums.policy_value < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)', note: 'RL policy head output' },
            { label: 'Dominant Prob', value: `${(nums.dominant_prob * 100).toFixed(1)}%`, color: nums.dominant_prob > 0.9 ? '#26c281' : '#f59e0b', note: 'top action certainty' },
            { label: 'Missing Features', value: String(nums.missing_feature_count), color: nums.missing_feature_count > 30 ? '#ef5350' : nums.missing_feature_count > 15 ? '#f59e0b' : '#26c281', note: 'imputed via backfill' },
          ].map(kpi => (
            <div key={kpi.label} style={{ minWidth: 100 }}>
              <div style={{ fontSize: 14, fontWeight: 800, fontFamily: 'var(--font-mono)', color: kpi.color }}>{kpi.value}</div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{kpi.label}</div>
              <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.2)', fontStyle: 'italic' }}>{kpi.note}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10 }}>
        {[
          { icon: '📊', title: 'What the model decided', text: exp.summary },
          { icon: '💪', title: 'Conviction', text: exp.signal_strength },
          { icon: '🧮', title: 'Why this action — edge vs cost', text: exp.decision_narrative },
          { icon: '⚡', title: 'Model heads (MASA + PPO policy)', text: exp.technical_drivers },
          { icon: '🌊', title: 'Live market drivers', text: exp.market_context_narrative },
          { icon: '🎯', title: 'How confidence was calibrated', text: exp.confidence_narrative },
          { icon: '📉', title: 'Data quality impact', text: exp.data_quality_narrative },
          { icon: '🏗️', title: 'Market state integrity', text: exp.market_integrity_narrative },
          { icon: '💰', title: 'Price target & expected move', text: exp.price_target_narrative },
          { icon: '🚦', title: 'Tradeability & gating', text: exp.risk_gate_narrative },
        ].filter(s => s.text).map(section => (
          <div key={section.title} style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.025)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>{section.icon} {section.title}</div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{section.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Expanded row ─────────────────────────────────────────────────────────

function PredExpandedRow({ row }: { row: PredRow }): JSX.Element {
  const [tab, setTab] = useState<'probs' | 'calibration' | 'reasoning'>('probs');
  const probs = row.action_probs ?? {};
  const maxProb = Math.max(...Object.values(probs), 0.01);
  return (
    <tr>
      <td colSpan={11} style={{ padding: 0 }}>
        <div style={{ background: 'rgba(10,10,18,0.95)', borderBottom: '2px solid var(--border)', padding: '16px 20px' }}>
          <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: 12 }}>
            {([['probs', '📊 Action Probs'], ['calibration', '🎯 Calibration'], ['reasoning', '🧠 AI Reasoning']] as const).map(([t, label]) => (
              <button key={t} onClick={() => setTab(t)} style={{
                padding: '5px 14px', borderRadius: 6, fontSize: 11, fontWeight: tab === t ? 700 : 400, cursor: 'pointer',
                border: `1px solid ${tab === t ? '#6366f1' : 'rgba(255,255,255,0.1)'}`,
                background: tab === t ? 'rgba(99,102,241,0.12)' : 'transparent',
                color: tab === t ? '#6366f1' : 'var(--text-secondary)',
              }}>{label}</button>
            ))}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>
              {row.checkpoint_id && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>ckpt: {publicRuntimeId(row.checkpoint_id)?.slice(0, 16)}…</span>}
              {row.cuda_available != null && <span style={{ fontSize: 10, padding: '2px 7px', borderRadius: 4, border: `1px solid ${row.cuda_available ? '#26c28140' : 'var(--border)'}`, color: row.cuda_available ? '#26c281' : 'var(--text-muted)' }}>{row.cuda_available ? '⚡ CUDA' : '🖥 CPU'}</span>}
            </div>
          </div>
          {tab === 'probs' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 20 }}>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>All Action Probabilities (raw softmax output)</div>
                {Object.keys(probs).length > 0
                  ? Object.entries(probs)
                      .sort((a, b) => b[1] - a[1])
                      .map(([action, prob]) => <ProbBar key={action} label={action} prob={prob} maxProb={maxProb} />)
                  : <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>Probability stream connecting</p>
                }
              </div>
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Signal Metadata</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {([
                    ['MASA Signal', row.masa_signal?.toFixed(4) ?? '—', row.masa_signal != null ? (row.masa_signal < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)'],
                    ['Policy Value', row.policy_value?.toFixed(4) ?? '—', row.policy_value != null ? (row.policy_value < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)'],
                    ['Coverage', row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(1)}%` : '—', (row.data_coverage_percent ?? 0) >= 80 ? '#26c281' : '#f59e0b'],
                    ['Missing Feats', row.missing_feature_count != null ? `${row.missing_feature_count}` : '—', (row.missing_feature_count ?? 0) > 20 ? '#f59e0b' : '#26c281'],
                    ['Price Target', fmtPrice(row.price_target), actionColor(row.action)],
                    ['Expected Move', row.expected_move_bps != null ? `${(row.expected_move_bps / 100).toFixed(2)}%` : '—', actionColor(row.action)],
                    ['Integrity', row.market_state_integrity_score != null ? `${row.market_state_integrity_score.toFixed(0)}/100` : '—', (row.market_state_integrity_score ?? 0) >= 90 ? '#26c281' : '#f59e0b'],
                    ['Generated', row.generated_at ? new Date(row.generated_at).toLocaleString() : '—', 'var(--text-muted)'],
                  ] as const).map(([l, v, color]) => (
                    <div key={String(l)} style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6 }}>
                      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>{l}</div>
                      <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: String(color) }}>{v}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          {tab === 'calibration' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
              <CalibGauge raw={row.confidence_raw} calibrated={row.confidence_calibrated} temperature={row.temperature} coverageFactor={row.coverage_factor} />
              <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>What this means</div>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.65 }}>
                  Raw confidence ({fmtConf(row.confidence_raw)}) is the model's softmax output directly.
                  Temperature {row.temperature?.toFixed(2) ?? '?'} smooths overconfident predictions — values &gt; 1.0 reduce confidence.
                  Coverage factor ({row.coverage_factor?.toFixed(3) ?? '?'}) penalizes {row.missing_feature_count ?? '?'} imputed features.
                  Final calibrated confidence: {fmtConf(row.confidence_calibrated)}.
                  {(row.confidence_raw ?? 0) - (row.confidence_calibrated ?? 0) > 0.05
                    ? ' Significant downward calibration — model was overconfident before adjustment.'
                    : ' Calibration was modest — data coverage was adequate.'}
                </p>
              </div>
            </div>
          )}
          {tab === 'reasoning' && <ReasoningPanel symbol={row.symbol} timeframe={row.timeframe} />}
        </div>
      </td>
    </tr>
  );
}

// ─── Trainer card ─────────────────────────────────────────────────────────

function TrainerCard(): JSX.Element {
  const { envelope } = useRealtimeResource<TrainerStatusContract>({
    url: '/api/v2/trainer/summary',
    source: '/api/v2/trainer/summary',
    pollIntervalMs: 30_000,
    mode: 'read_only',
  });
  const t = envelope.data;
  const state = t?.state ?? 'LOADING';
  const active = (state ?? '').toUpperCase().includes('ACTIVE');
  const stateColor = state === 'MISSING_EVIDENCE' ? '#f59e0b' : (active || state === 'OK') ? '#26c281' : state === 'LOADING' ? 'var(--text-muted)' : '#ef5350';
  // Real, populated fields (the legacy uptime/win_rate_30d/episodes/drift fields
  // are null in the contract, so surface live runtime truths instead).
  const mode = t?.runtime_mode?.effective_trainer_mode ?? null;
  const weights = t?.weights_updating ?? t?.trainer_learning_status?.weights_updating ?? null;
  const winRate = t?.model_edge_backtest?.win_rate ?? null;
  const coverage = t?.data_coverage ?? null;
  const gpu = t?.gpu_runtime?.gpu_name ?? (t?.cuda_active ? 'CUDA' : null);
  const cell = (label: string, value: React.ReactNode, color?: string) => (
    <div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 12.5, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-secondary)' }}>{value}</div>
    </div>
  );
  return (
    <div style={{ background: 'rgba(99,102,241,0.04)', border: '1px solid rgba(99,102,241,0.15)', borderRadius: 10, padding: '12px 16px', display: 'flex', flexWrap: 'wrap', gap: 20, alignItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>🧠</span>
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Trainer</div>
          <div style={{ fontSize: 13, fontWeight: 800, fontFamily: 'var(--font-mono)', color: stateColor }}>{(state ?? '').replace(/_/g, ' ')}</div>
        </div>
      </div>
      {mode && cell('Mode', mode.replace(/_/g, ' '), '#8bd6ff')}
      {weights != null && cell('Learning', weights ? 'WEIGHTS UPDATING' : 'IDLE', weights ? '#26c281' : '#f59e0b')}
      {winRate != null && cell('Model Win Rate', `${(winRate * 100).toFixed(1)}%`, winRate >= 0.55 ? '#26c281' : winRate >= 0.5 ? '#f59e0b' : '#ef5350')}
      {coverage != null && cell('Data Coverage', `${coverage.toFixed(1)}%`, coverage >= 80 ? '#26c281' : '#f59e0b')}
      {gpu && cell('Compute', gpu, '#26c281')}
      {t?.checkpoint_id && cell('Checkpoint', `${publicRuntimeId(t.checkpoint_id)?.slice(0, 18) ?? t.checkpoint_id.slice(0, 18)}…`)}
      <div style={{ marginLeft: 'auto' }}>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>
    </div>
  );
}

const AI_PROVIDER_LANES = [
  ['coinglass', 'CoinGlass'],
  ['moralis', 'Moralis'],
  ['santiment', 'Santiment / Sanbase'],
] as const;

function providerStatusById(providers: ProviderStatusCard[] | undefined): Map<string, ProviderStatusCard> {
  const out = new Map<string, ProviderStatusCard>();
  for (const provider of providers ?? []) {
    out.set(provider.provider.toLowerCase(), provider);
  }
  return out;
}

function countText(value: number | null | undefined): string {
  if (value == null) return 'pending';
  return value.toLocaleString('en-US');
}

function TrainerBrainSummary(): JSX.Element {
  const trainer = useRealtimeResource<TrainerStatusContract>({
    url: '/api/v2/trainer/status',
    source: '/api/v2/trainer/status',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const providers = useRealtimeResource<ProviderStatusContract>({
    url: '/api/v2/providers/status',
    source: '/api/v2/providers/status',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
    unwrapEnvelopeData: 'contract',
  });
  const trainerData = trainer.envelope.data;
  const providerMap = useMemo(() => providerStatusById(providers.envelope.data?.providers), [providers.envelope.data?.providers]);
  const liveBlocked = trainerData?.routes_to_live !== true && trainerData?.places_real_order !== true;

  return (
    <section
      data-testid="ai-trainer-brain-summary"
      style={{
        marginBottom: 12,
        padding: '12px 14px',
        borderRadius: 10,
        border: '1px solid rgba(99,102,241,0.18)',
        background: 'rgba(99,102,241,0.045)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <strong style={{ display: 'block', fontSize: 12, color: 'var(--text-primary)' }}>Trainer brain summary</strong>
          <span style={{ display: 'block', marginTop: 3, fontSize: 11, color: 'var(--text-muted)' }}>
            PPO and MASA read provider features through the masked tensor feed; this panel is read-only and cannot approve trades.
          </span>
        </div>
        <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: liveBlocked ? '#f59e0b' : '#ef5350' }}>
          Trading approval {trainerData?.live_gate ?? providers.envelope.data?.live_gate ?? 'blocked_human_only'}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8 }}>
        {[
          ['PPO status', trainerData?.state ?? trainerData?.freshness_status ?? 'connecting'],
          ['MASA model source', trainerData?.model_source ?? 'pending'],
          ['Checkpoint ID', publicRuntimeId(trainerData?.checkpoint_id)?.slice(0, 24) ?? 'pending'],
          ['Tensor input dim', countText(trainerData?.input_dim)],
          ['Feature count', countText(trainerData?.feature_count)],
          ['Temporal encoder', trainerData?.temporal_encoder_enabled ? `${trainerData?.temporal_encoder ?? 'on'} × ${trainerData?.temporal_seq_len ?? '—'} frames` : 'single-frame'],
        ].map(([label, value]) => (
          <div key={label} style={{ padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-base)' }}>
            <div style={{ fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
            <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 8 }}>
        {AI_PROVIDER_LANES.map(([id, label]) => {
          const provider = providerMap.get(id);
          const actual = provider?.actual_payload_present === true && provider?.heartbeat_only !== true;
          return (
            <div key={id} data-testid={`ai-provider-feature-${id}`} style={{ padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-base)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 3 }}>
                <strong style={{ fontSize: 11, color: 'var(--text-primary)' }}>{label}</strong>
                <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: actual ? '#26c281' : 'var(--text-muted)' }}>
                  {String(provider?.dashboard_color ?? 'connecting').toUpperCase()}
                </span>
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                provider features {countText(provider?.feature_count)} · samples {countText(provider?.actual_payload_count)} · actual data {actual ? 'yes' : 'no'}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ─── Trainer deep telemetry ───────────────────────────────────────────────

function TCell({ label, value, color, note }: { label: string; value: React.ReactNode; color?: string; note?: string }): JSX.Element {
  return (
    <div style={{ padding: '7px 10px', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-base)', minWidth: 0 }}>
      <div style={{ fontSize: 8.5, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</div>
      <div style={{ fontSize: 12.5, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-secondary)', overflowWrap: 'anywhere' }}>{value}</div>
      {note && <div style={{ fontSize: 8.5, color: 'rgba(255,255,255,0.22)', fontStyle: 'italic', marginTop: 1 }}>{note}</div>}
    </div>
  );
}

function TSection({ title, accent, children }: { title: string; accent?: string; children: React.ReactNode }): JSX.Element {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 9.5, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.07em', color: accent ?? '#8b8fdb', marginBottom: 6 }}>{title}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(128px, 1fr))', gap: 7 }}>{children}</div>
    </div>
  );
}

function fmtNum(n: number | null | undefined, d = 2): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function boolCell(v: boolean | null | undefined, onLabel = 'YES', offLabel = 'NO'): { text: string; color: string } {
  if (v == null) return { text: '—', color: 'var(--text-muted)' };
  return v ? { text: onLabel, color: '#26c281' } : { text: offLabel, color: '#f59e0b' };
}

function TrainerDeepTelemetry(): JSX.Element | null {
  const { envelope } = useRealtimeResource<TrainerStatusContract>({
    url: '/api/v2/trainer/status',
    source: '/api/v2/trainer/status',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const d = envelope.data;
  if (!d) return null;
  const learn = d.trainer_learning_status ?? {};
  const gpu = d.gpu_runtime ?? {};
  const edge = d.model_edge_backtest ?? {};
  const mode = d.runtime_mode ?? {};
  const lm = d.learning_metrics_extra ?? {};
  const arch = d.model_architecture ?? {};
  const ppo = d.ppo_runtime_status ?? {};
  const cc = d.champion_challenger_status ?? {};
  const holdout = cc.holdout_metrics ?? {};
  const readiness = d.real_trader_readiness ?? {};
  const agt = d.a_grade_blocker_truth ?? {};
  const agrade = agt.a_grade ?? {};
  const blockers = d.readiness_blockers ?? readiness.readiness_blockers ?? [];

  const lossBefore = learn.loss_before;
  const lossAfter = learn.loss_after;
  const lossImproving = lossBefore != null && lossAfter != null ? lossAfter <= lossBefore : null;
  const heads: Array<[string, boolean | null | undefined]> = [
    ['value', arch.value_head], ['confidence', arch.confidence_head], ['expected-move', arch.expected_move_head],
    ['masa-aux', arch.masa_auxiliary_head], ['ppo-policy', arch.ppo_policy_head],
  ];
  const activeHeads = heads.filter(([, on]) => on).map(([n]) => n);
  const learningStr = boolCell(learn.weights_updating ?? d.weights_updating, 'UPDATING', 'IDLE');
  const winRate = edge.win_rate;
  const dirAcc = holdout.directional_accuracy;

  return (
    <section
      data-testid="ai-trainer-deep-telemetry"
      style={{ marginBottom: 12, padding: '12px 14px', borderRadius: 10, border: '1px solid rgba(99,102,241,0.18)', background: 'rgba(99,102,241,0.03)' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
        <div>
          <strong style={{ fontSize: 12, color: 'var(--text-primary)' }}>Trainer deep telemetry</strong>
          <span style={{ display: 'block', marginTop: 2, fontSize: 10.5, color: 'var(--text-muted)' }}>
            Live RTX runtime, online-learning, model edge, architecture and live-readiness — read-only from v2:trainer:hybrid_cuda:status.
          </span>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      <TSection title="Runtime & online learning" accent="#26c281">
        <TCell label="Trainer mode" value={(mode.effective_trainer_mode ?? '—').replace(/_/g, ' ')} color="#8bd6ff" />
        <TCell label="Online learning" value={(mode.online_learning_status ?? '—').replace(/_/g, ' ')} color={learningStr.color} />
        <TCell label="Weights" value={learningStr.text} color={learningStr.color} />
        <TCell label="Process" value={(mode.trainer_process_status ?? '—')} color={mode.trainer_process_status === 'ACTIVE' ? '#26c281' : '#f59e0b'} />
        <TCell label="Update lane" value={(learn.learning_update_lane ?? '—').replace(/_/g, ' ')} />
        <TCell label="Loss before→after" value={`${fmtNum(lossBefore, 4)}→${fmtNum(lossAfter, 4)}`} color={lossImproving == null ? undefined : lossImproving ? '#26c281' : '#f59e0b'} note="lower is better" />
        <TCell label="Optimizer steps" value={learn.optimizer_steps_this_cycle ?? '—'} note="this cycle" />
        <TCell label="Weight Δ norm" value={fmtNum(learn.weight_delta_norm, 3)} color={(learn.weight_delta_norm ?? 0) > 0 ? '#26c281' : 'var(--text-muted)'} note="params moved" />
        <TCell label="Last weight update" value={fmtAge(learn.last_successful_weight_update_at ? runtimeAgeSeconds(learn.last_successful_weight_update_at) : null)} />
        <TCell label="Feedback rows" value={countText(learn.feedback_rows_consumed)} note="consumed" />
        <TCell label="Replay rows" value={countText(learn.trusted_replay_rows_loaded)} note="trusted replay" />
        <TCell label="Predictions" value={countText(mode.prediction_examples_built)} color={mode.prediction_publication_status === 'ACTIVE' ? '#26c281' : '#f59e0b'} note={String(mode.prediction_publication_status ?? '').toLowerCase() || undefined} />
      </TSection>

      <TSection title="Model edge (holdout backtest + challenger)" accent="#f0b429">
        <TCell label="Backtest win rate" value={winRate != null ? `${(winRate * 100).toFixed(1)}%` : '—'} color={winRate != null ? (winRate >= 0.55 ? '#26c281' : winRate >= 0.5 ? '#f59e0b' : '#ef5350') : 'var(--text-muted)'} />
        <TCell label="After-cost expectancy" value={edge.expectancy_after_cost_bps != null ? `${edge.expectancy_after_cost_bps.toFixed(1)} bps` : '—'} color={(edge.expectancy_after_cost_bps ?? 0) > 0 ? '#26c281' : '#ef5350'} />
        <TCell label="Profit factor" value={fmtNum(edge.profit_factor_proxy, 2)} color={(edge.profit_factor_proxy ?? 0) >= 1.2 ? '#26c281' : (edge.profit_factor_proxy ?? 0) >= 1 ? '#f59e0b' : '#ef5350'} />
        <TCell label="Rows evaluated" value={countText(edge.rows_evaluated)} />
        <TCell label="Challenger" value={(cc.result_status ?? cc.status ?? '—').replace(/_/g, ' ')} color={cc.paper_challenger_enabled ? '#26c281' : '#f59e0b'} />
        <TCell label="Challenger dir. acc" value={dirAcc != null ? `${(dirAcc * 100).toFixed(1)}%` : '—'} color={dirAcc != null ? (dirAcc >= 0.55 ? '#26c281' : '#f59e0b') : 'var(--text-muted)'} />
        <TCell label="Challenger expectancy" value={holdout.after_cost_expectancy_bps != null ? `${holdout.after_cost_expectancy_bps.toFixed(1)} bps` : '—'} color={(holdout.after_cost_expectancy_bps ?? 0) > 0 ? '#26c281' : '#ef5350'} />
        <TCell label="Challenger trades" value={countText(holdout.trade_count)} note="holdout" />
        <TCell label="Evidence class" value={(edge.evidence_class ?? '—').replace(/_/g, ' ').toLowerCase()} note="not A+ until forward-canary" />
      </TSection>

      <TSection title="GPU / throughput" accent="#8b5cf6">
        <TCell label="GPU" value={gpu.gpu_name ?? '—'} color="#26c281" note={gpu.model_device ?? undefined} />
        <TCell label="VRAM used" value={gpu.current_vram_used_mb != null ? `${(gpu.current_vram_used_mb / 1024).toFixed(2)} GB` : '—'} note={gpu.vram_cap_mb != null ? `cap ${(gpu.vram_cap_mb / 1024).toFixed(0)}GB` : undefined} />
        <TCell label="Throughput" value={gpu.throughput_predictions_per_second != null ? `${gpu.throughput_predictions_per_second.toFixed(1)}/s` : '—'} note="predictions" />
        <TCell label="Steps / min" value={fmtNum(gpu.training_steps_per_minute, 1)} />
        <TCell label="Backtest rows/s" value={gpu.backtest_rows_per_second != null ? countText(Math.round(gpu.backtest_rows_per_second)) : '—'} />
        <TCell label="Batch" value={`${gpu.actual_batch_size ?? '—'} / ${gpu.target_batch_size ?? '—'}`} note="actual / target" />
        <TCell label="GPU train time" value={gpu.gpu_train_time_ms != null ? `${(gpu.gpu_train_time_ms / 1000).toFixed(1)}s` : '—'} note={gpu.data_loader_time_ms != null ? `loader ${(gpu.data_loader_time_ms / 1000).toFixed(1)}s` : undefined} />
        <TCell label="Mixed precision" value={boolCell(gpu.mixed_precision_enabled).text} color={boolCell(gpu.mixed_precision_enabled).color} />
        <TCell label="OOM count" value={gpu.oom_count ?? '—'} color={(gpu.oom_count ?? 0) > 0 ? '#ef5350' : '#26c281'} />
      </TSection>

      <TSection title="Architecture & PPO" accent="#38bdf8">
        <TCell label="Hidden size" value={countText(arch.hidden_size)} />
        <TCell label="Residual blocks" value={arch.residual_block_count ?? '—'} />
        <TCell label="Action count" value={arch.action_count ?? '—'} />
        <TCell label="Active heads" value={activeHeads.length ? activeHeads.join(', ') : '—'} note="output heads" />
        <TCell label="MASA blend" value={boolCell(arch.masa_adapter_blend).text} color={boolCell(arch.masa_adapter_blend).color} />
        <TCell label="PPO objective" value={boolCell(ppo.ppo_objective_used, 'ON', 'OFF').text} color={boolCell(ppo.ppo_objective_used, 'ON', 'OFF').color} note="on-policy" />
        <TCell label="PPO value loss" value={fmtNum(ppo.ppo_value_loss, 4)} />
        <TCell label="PPO entropy" value={fmtNum(ppo.ppo_entropy, 4)} />
        {ppo.exact_blocker && <TCell label="PPO note" value={ppo.exact_blocker.replace(/_/g, ' ').toLowerCase()} note="outcome-supervised active" />}
      </TSection>

      <TSection title="Validation & promotion" accent="#f59e0b">
        <TCell label="Generalization gap" value={fmtNum(lm.train_val_generalization_gap, 2)} color={(lm.train_val_generalization_gap ?? 0) > 5 ? '#ef5350' : '#26c281'} note="train vs val" />
        <TCell label="Val loss delta" value={fmtNum(lm.validation_loss_delta, 3)} color={(lm.validation_loss_delta ?? 0) < 0 ? '#26c281' : '#f59e0b'} note="negative = improving" />
        <TCell label="Val improved" value={boolCell(lm.validation_improved).text} color={boolCell(lm.validation_improved).color} />
        <TCell label="Overfit warning" value={boolCell(lm.overfit_gap_warning, 'ACTIVE', 'CLEAR').text} color={lm.overfit_gap_warning ? '#f59e0b' : '#26c281'} />
        <TCell label="Promoted (cycle)" value={boolCell(mode.checkpoint_promoted_this_cycle).text} color={boolCell(mode.checkpoint_promoted_this_cycle).color} />
        <TCell label="Promotion reason" value={(mode.checkpoint_promotion_reason ?? '—').replace(/_/g, ' ').toLowerCase()} />
      </TSection>

      <TSection title="Live readiness (operator-gated)" accent="#ef5350">
        <TCell label="Live ready" value={boolCell(d.live_ready ?? readiness.live_ready, 'READY', 'NOT READY').text} color={(d.live_ready ?? readiness.live_ready) ? '#26c281' : '#f59e0b'} />
        <TCell label="Exact reason" value={(d.exact_no_live_reason ?? readiness.exact_no_live_reason ?? '—').replace(/_/g, ' ').toLowerCase()} />
        <TCell label="A-grade rows" value={`${agrade.A_grade_rows ?? 0}`} note={`${agrade.near_A_grade_rows ?? 0} near`} color={(agrade.A_grade_rows ?? 0) > 0 ? '#26c281' : '#f59e0b'} />
        <TCell label="Guardian" value={(agrade.guardian_status ?? '—').replace(/_/g, ' ').toLowerCase()} color={agrade.guardian_new_entries_allowed ? '#26c281' : '#f59e0b'} />
        <TCell label="Adaptation" value={(agt.status ?? '—').replace(/_/g, ' ').toLowerCase()} />
      </TSection>

      {blockers.length > 0 && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 2 }}>
          {blockers.slice(0, 8).map((b) => (
            <span key={b} style={{ fontSize: 9, padding: '2px 7px', borderRadius: 10, background: 'rgba(239,83,80,0.1)', border: '1px solid rgba(239,83,80,0.25)', color: '#ef8b88', fontFamily: 'var(--font-mono)' }}>
              {b.replace(/_/g, ' ').toLowerCase()}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

// ─── Sort header ──────────────────────────────────────────────────────────

type SortKey = 'symbol' | 'timeframe' | 'action' | 'confidence_calibrated' | 'age_seconds' | 'data_coverage_percent' | 'missing_feature_count';
type SortDir = 'asc' | 'desc';

function SortTh({ label, col, current, dir, onSort }: { label: string; col: SortKey; current: SortKey; dir: SortDir; onSort: (c: SortKey) => void }): JSX.Element {
  const active = current === col;
  return (
    <th onClick={() => onSort(col)} style={{ padding: '8px 12px', textAlign: 'left', cursor: 'pointer', userSelect: 'none', borderBottom: '1px solid var(--border)', color: active ? '#6366f1' : 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, whiteSpace: 'nowrap', background: 'var(--bg-panel)' }}>
      {label}{active ? (dir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────

function EmptyChartAI({ label }: { label: string }): JSX.Element {
  return (
    <div style={{ height: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12, border: '1px dashed var(--border)', borderRadius: 8 }}>
      {label}
    </div>
  );
}

export default function AIPredictionsPage(): JSX.Element {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set(DEFAULT_SYMBOLS));
  const [selectedTFs, setSelectedTFs] = useState<Set<TF>>(new Set(TIMEFRAMES));
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [showAllSymbols, setShowAllSymbols] = useState(false);
  const [symbolSearch, setSymbolSearch] = useState('');
  const traderSnapshot = useTraderSnapshot();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const currentLineage = useCurrentRuntimeLineage(10_000);

  const symbolsParam = Array.from(selectedSymbols).join(',');
  const tfsParam = Array.from(selectedTFs).join(',');
  const url = `/api/v2/predictions/matrix?symbols=${symbolsParam}&timeframes=${tfsParam}`;

  const { envelope, loading, refetch } = useRealtimeResource<PredMatrixData>({
    url, source: '/api/v2/predictions/matrix', source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 20_000, mode: 'read_only',
  });
  const { envelope: allEnv } = useRealtimeResource<PredMatrixData>({
    url: '/api/v2/predictions/matrix', source: '/api/v2/predictions/matrix', source_type: 'websocket', pollIntervalMs: 60_000, mode: 'read_only',
  });

  // Keep top-liquidity defaults attached to the shared liquidation resource stream.
  const { envelope: liqHeatmapEnv } = useRealtimeResource<{ pinned_defaults?: string[] }>({
    url: '/api/v2/liquidation/levels-heatmap', source: '/api/v2/liquidation/levels-heatmap',
    source_type: 'websocket', pollIntervalMs: 10_000, staleThresholdMs: 30_000, mode: 'read_only', initialFetch: true,
  });
  useEffect(() => {
    const pinned = liqHeatmapEnv.data?.pinned_defaults;
    if (!pinned || pinned.length === 0) return;
    // Only auto-select if user hasn't deviated from core defaults
    setSelectedSymbols(prev => {
      const hasCustom = Array.from(prev).some(s => !DEFAULT_SYMBOLS.includes(s));
      if (hasCustom) return prev;
      const next = new Set([...PINNED_CORE, ...pinned.slice(0, 5)]);
      return next;
    });
  }, [liqHeatmapEnv.data?.pinned_defaults?.join(',')]);

  const lineagePredictionRow = useMemo(() => predictionRowFromLineage(currentLineage.envelope.data), [currentLineage.envelope.data]);
  const matrixRows = envelope.data?.rows ?? [];
  const rows = useMemo(
    () => matrixRows.length ? matrixRows : lineagePredictionRow ? [lineagePredictionRow] : [],
    [lineagePredictionRow, matrixRows],
  );
  const usingLineageFallback = matrixRows.length === 0 && rows.length > 0;
  const allSymbols = useMemo(() => {
    const next = new Set(allEnv.data?.symbols ?? []);
    if (lineagePredictionRow?.symbol) next.add(lineagePredictionRow.symbol);
    return Array.from(next);
  }, [allEnv.data?.symbols, lineagePredictionRow?.symbol]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      let av: string | number = 0, bv: string | number = 0;
      if (sortKey === 'symbol') { av = a.symbol; bv = b.symbol; }
      else if (sortKey === 'timeframe') { const o: Record<string, number> = { '1m': 0, '5m': 1, '15m': 2, '1h': 3, '4h': 4 }; av = o[a.timeframe] ?? 99; bv = o[b.timeframe] ?? 99; }
      else if (sortKey === 'action') { av = a.action ?? ''; bv = b.action ?? ''; }
      else if (sortKey === 'confidence_calibrated') { av = a.confidence_calibrated ?? -1; bv = b.confidence_calibrated ?? -1; }
      else if (sortKey === 'age_seconds') { av = a.age_seconds ?? 999999; bv = b.age_seconds ?? 999999; }
      else if (sortKey === 'data_coverage_percent') { av = a.data_coverage_percent ?? -1; bv = b.data_coverage_percent ?? -1; }
      else if (sortKey === 'missing_feature_count') { av = a.missing_feature_count ?? 999; bv = b.missing_feature_count ?? 999; }
      if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const handleSort = useCallback((col: SortKey) => {
    if (col === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortKey(col); setSortDir('asc'); }
  }, [sortKey]);

  const displayedSymbols = useMemo(() => {
    const filter = symbolSearch.trim().toUpperCase();
    const pool = showAllSymbols ? allSymbols : DEFAULT_SYMBOLS;
    return filter ? pool.filter(s => s.includes(filter)) : pool;
  }, [showAllSymbols, allSymbols, symbolSearch]);

  const avgCal = rows.length > 0 ? rows.reduce((s, r) => s + (r.confidence_calibrated ?? 0), 0) / rows.length : null;
  const coverageAvg = rows.length > 0 ? rows.reduce((s, r) => s + (r.data_coverage_percent ?? 0), 0) / rows.length : null;
  const predictionFeedReady = rows.length > 0;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.signal_prediction_accuracy_status
    ?? null;
  const evaluatedAccuracyCells = accuracyStatus?.evaluated_symbol_timeframe_cell_count;
  const totalAccuracyCells = accuracyStatus?.symbol_timeframe_cell_count
    ?? accuracyStatus?.required_symbol_timeframe_cell_count;
  const missingAccuracyCells = missingAccuracyCellCount(accuracyStatus);

  // ── Chart derivations from the live prediction matrix + accuracy status ──
  const actionDist = useMemo(() => {
    let long = 0, short = 0, hold = 0;
    for (const r of rows) {
      const a = (r.action ?? '').toLowerCase();
      if (a.includes('long')) long += 1; else if (a.includes('short')) short += 1; else hold += 1;
    }
    return [
      { name: 'Long', value: long, color: '#22c55e' },
      { name: 'Short', value: short, color: '#ef4444' },
      { name: 'Hold', value: hold, color: '#f59e0b' },
    ].filter((d) => d.value > 0);
  }, [rows]);
  const confByTf = useMemo(() => {
    const order = ['1m', '5m', '15m', '1h', '4h'];
    const agg: Record<string, { sum: number; n: number }> = {};
    for (const r of rows) {
      const tf = r.timeframe;
      if (r.confidence_calibrated == null) continue;
      (agg[tf] ??= { sum: 0, n: 0 });
      agg[tf].sum += r.confidence_calibrated; agg[tf].n += 1;
    }
    return order.filter((tf) => agg[tf]?.n).map((tf) => ({ label: tf, value: (agg[tf].sum / agg[tf].n) * 100 }));
  }, [rows]);
  const accByTf = useMemo(() => {
    const bt = (accuracyStatus?.by_timeframe ?? {}) as Record<string, { accuracy?: number; overall_accuracy?: number }>;
    const order = ['1m', '5m', '15m', '1h', '4h'];
    return order
      .filter((tf) => bt[tf] != null)
      .map((tf) => {
        const raw = bt[tf].accuracy ?? bt[tf].overall_accuracy ?? 0;
        return { label: tf, value: (Math.abs(raw) <= 1 ? raw * 100 : raw) };
      })
      .filter((d) => Number.isFinite(d.value));
  }, [accuracyStatus]);

  const canonicalSignal = selectActiveSignal(traderSnapshot);
  // Public fallback: the trader signal snapshot is 401-gated, so for logged-out
  // viewers surface the strongest CURRENT model prediction (highest-confidence
  // directional row, else highest overall) from the public matrix stream.
  const publicTopSignal = useMemo(() => {
    if (rows.length === 0) return null;
    const directional = rows.filter((r) => (r.action ?? '').includes('long') || (r.action ?? '').includes('short'));
    const pool = directional.length ? directional : rows;
    return [...pool].sort((a, b) => (b.confidence_calibrated ?? 0) - (a.confidence_calibrated ?? 0))[0] ?? null;
  }, [rows]);
  const signalMetric = (fieldId: string): CanonicalMetric => {
    const authed = selectSignalMetric(traderSnapshot, canonicalSignal ?? {}, fieldId);
    if (authed.value != null) return authed;
    if (!publicTopSignal) return authed;
    const publicValue = fieldId === 'signal.id'
      ? `${publicTopSignal.symbol}:${publicTopSignal.timeframe} · ${(publicTopSignal.action ?? '—').toUpperCase()}`
      : fieldId === 'signal.confidence'
        ? publicTopSignal.confidence_calibrated
        : null;
    if (publicValue == null) return authed;
    return {
      ...authed,
      value: publicValue,
      source: '/api/v2/predictions/matrix',
      sourceType: envelope.source_type ?? 'websocket',
      timestamp: envelope.timestamp != null ? new Date(envelope.timestamp).toISOString() : null,
      ageMs: envelope.lag_ms ?? null,
      quality: 'valid',
    };
  };

  return (
    <div data-testid="page-ai-predictions" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>

      {/* Header — distinct purple/indigo theme vs signals blue */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '2px solid rgba(99,102,241,0.2)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>🧠</span>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>AI Predictions</h1>
              <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(99,102,241,0.12)', color: '#6366f1', border: '1px solid rgba(99,102,241,0.3)', fontFamily: 'var(--font-mono)' }}>RAW MODEL OUTPUT</span>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              Action probability distributions · Softmax output · Confidence calibration (temperature + coverage) · MASA/policy signals · {predictionFeedReady ? rows.length : '—'} active predictions
              {usingLineageFallback ? ' · current runtime lineage' : ''}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid rgba(99,102,241,0.3)', background: 'rgba(99,102,241,0.08)', color: '#6366f1', fontSize: 11, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>

        <div style={{ marginBottom: 12 }}><TrainerCard /></div>
        <TrainerBrainSummary />
        <TrainerDeepTelemetry />

        {/* KPI strip */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          {[
            { label: 'Total Predictions', value: predictionFeedReady ? rows.length : '—', color: 'var(--text-primary)' },
            { label: 'Avg Calibrated Conf', value: avgCal != null ? fmtConf(avgCal) : '—', color: confColor(avgCal) },
            { label: 'Avg Feature Coverage', value: coverageAvg != null ? `${coverageAvg.toFixed(1)}%` : '—', color: (coverageAvg ?? 0) >= 80 ? '#26c281' : '#f59e0b' },
            { label: 'Long Bias', value: predictionFeedReady ? rows.filter(r => (r.action ?? '').includes('long')).length : '—', color: '#26c281' },
            { label: 'Short Bias', value: predictionFeedReady ? rows.filter(r => (r.action ?? '').includes('short')).length : '—', color: '#ef5350' },
            { label: 'Hold', value: predictionFeedReady ? rows.filter(r => r.action === 'hold').length : '—', color: '#f59e0b' },
            { label: 'Accuracy', value: formatAdaptivePercent(accuracyStatus?.overall_accuracy), color: adaptiveStatusColor(accuracyStatus?.status) },
            { label: 'Evaluated', value: accuracyStatus?.evaluated_row_count ?? '—', color: 'var(--text-primary)' },
            { label: 'In Universe', value: allSymbols.length || '—', color: 'var(--text-muted)' },
            { label: 'TF Cells', value: evaluatedAccuracyCells != null || totalAccuracyCells != null ? `${evaluatedAccuracyCells ?? 0}/${totalAccuracyCells ?? 0}` : '—', color: 'var(--text-primary)' },
            { label: 'Missing Cells', value: missingAccuracyCells ?? '—', color: (missingAccuracyCells ?? 0) > 0 ? '#ef5350' : '#26c281' },
          ].map(k => (
            <div key={k.label} style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 6, padding: '5px 10px', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k.label}</span>
              <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: k.color }}>{k.value}</span>
            </div>
          ))}
        </div>

        <div className="trader-metric-grid" style={{ marginBottom: 12 }}>
          <CanonicalMetricCard label="Active Signal ID" metric={signalMetric('signal.id')} />
          <CanonicalMetricCard label="Signal Confidence" metric={signalMetric('signal.confidence')} />
        </div>

        {/* Symbol selector */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Symbols</span>
            <input value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)} placeholder="Filter..." style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 11, width: 90, outline: 'none' }} />
            <button onClick={() => setShowAllSymbols(s => !s)} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>
              {showAllSymbols ? `Default (${DEFAULT_SYMBOLS.length})` : `All (${allSymbols.length || '—'})`}
            </button>
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxHeight: 64, overflowY: 'auto' }}>
            {displayedSymbols.map(s => (
              <button key={s} onClick={() => {
                setSelectedSymbols(prev => { const n = new Set(prev); if (n.has(s)) { if (n.size > 1) n.delete(s); } else n.add(s); return n; });
              }} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 10, fontWeight: selectedSymbols.has(s) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedSymbols.has(s) ? '#6366f1' : 'var(--border)'}`, background: selectedSymbols.has(s) ? 'rgba(99,102,241,0.12)' : 'transparent', color: selectedSymbols.has(s) ? '#6366f1' : 'var(--text-secondary)' }}>
                {s.replace('USDT', '')}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: 4 }}>Timeframes</span>
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => {
              setSelectedTFs(prev => { const n = new Set(prev); if (n.has(tf)) { if (n.size > 1) n.delete(tf); } else n.add(tf); return n; });
            }} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 11, fontWeight: selectedTFs.has(tf) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedTFs.has(tf) ? '#6366f1' : 'var(--border)'}`, background: selectedTFs.has(tf) ? 'rgba(99,102,241,0.12)' : 'transparent', color: selectedTFs.has(tf) ? '#6366f1' : 'var(--text-secondary)' }}>
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Prediction analytics charts — action mix, confidence & accuracy by timeframe */}
      <div style={{ padding: '12px 16px 0' }}>
        <section style={{ background: 'var(--bg-panel)', border: '1px solid rgba(99,102,241,0.18)', borderRadius: 12, padding: '14px 16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 16 }}>🧠</span>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Prediction Analytics</h2>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{rows.length} live predictions</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 14 }}>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
              <ChartFrame title="Action mix" subtitle="long / short / hold" height={150}>
                {actionDist.length
                  ? <><Donut data={actionDist} height={150} centerValue={String(actionDist.reduce((s, d) => s + d.value, 0))} centerLabel="preds" /><DonutLegend data={actionDist} /></>
                  : <EmptyChartAI label="No predictions yet" />}
              </ChartFrame>
            </div>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
              <ChartFrame title="Avg calibrated confidence" subtitle="by timeframe" height={150}>
                {confByTf.length
                  ? <MetricBars data={confByTf} height={150} suffix="%" domainMax={100} colorFn={pctThresholdColor} />
                  : <EmptyChartAI label="No confidence data" />}
              </ChartFrame>
            </div>
            <div style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
              <ChartFrame title="Accuracy by timeframe" subtitle="evaluated outcomes" height={150}>
                {accByTf.length
                  ? <MetricBars data={accByTf} height={150} suffix="%" domainMax={100} colorFn={pctThresholdColor} />
                  : <div style={{ height: 150, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                      <RadialGauge value={accuracyStatus?.overall_accuracy} height={130} label="overall" />
                    </div>}
              </ChartFrame>
            </div>
          </div>
        </section>
      </div>

      <div style={{ padding: '12px 16px 0' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Prediction Accuracy + Capital Productivity"
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
            <div style={{ fontSize: 32, marginBottom: 10 }}>🧠</div>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>Prediction stream connecting. Existing panels stay mounted while WebSocket and HTTP fallback connect.</p>
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
                    <SortTh label="Prediction" col="action" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Conf Cal." col="confidence_calibrated" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Accuracy / PnL</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Top Probs</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Price Target</th>
                    <SortTh label="Coverage" col="data_coverage_percent" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Missing" col="missing_feature_count" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Age" col="age_seconds" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(row => {
                    const rowKey = `${row.symbol}:${row.timeframe}`;
                    const expanded = expandedRow === rowKey;
                    const topColor = actionColor(row.top_action);
                    const secondColor = actionColor(row.second_action);
                    const accuracy = lookupAccuracyCell(accuracyStatus, row.symbol, row.timeframe);
                    return (
                      <React.Fragment key={rowKey}>
                        <tr onClick={() => setExpandedRow(expanded ? null : rowKey)}
                          style={{ cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.04)', background: expanded ? 'rgba(99,102,241,0.04)' : 'transparent' }}
                          onMouseEnter={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'; }}
                          onMouseLeave={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>
                            {row.symbol.replace('USDT', '')}<span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 10, marginLeft: 2 }}>USDT</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#6366f1', padding: '2px 6px', background: 'rgba(99,102,241,0.06)', borderRadius: 4, border: '1px solid rgba(99,102,241,0.15)' }}>{row.timeframe}</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            {row.action ? (
                              <span style={{ padding: '3px 10px', borderRadius: 5, fontSize: 11, fontWeight: 800, fontFamily: 'var(--font-mono)', color: actionColor(row.action), background: `${actionColor(row.action)}15`, border: `1px solid ${actionColor(row.action)}30` }}>
                                {row.action.replace(/_/g, ' ').toUpperCase()}
                              </span>
                            ) : <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>}
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{ width: 56, height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                                <div style={{ height: '100%', width: `${Math.min(100, (row.confidence_calibrated ?? 0) * 100)}%`, background: confColor(row.confidence_calibrated), borderRadius: 3 }} />
                              </div>
                              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: confColor(row.confidence_calibrated), fontWeight: 700 }}>{fmtConf(row.confidence_calibrated)}</span>
                              <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>/{fmtConf(row.confidence_raw)}</span>
                            </div>
                          </td>
                          <td style={{ padding: '10px 12px' }}><AccuracyBadge cell={accuracy} /></td>
                          <td style={{ padding: '10px 12px' }}>
                            <div style={{ display: 'flex', gap: 4 }}>
                              {row.top_action && <span style={{ padding: '2px 7px', borderRadius: 4, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', color: topColor, background: `${topColor}18`, border: `1px solid ${topColor}30` }}>{row.top_action.replace(/_/g, ' ')} {row.top_prob != null ? `${(row.top_prob * 100).toFixed(0)}%` : ''}</span>}
                              {row.second_action && row.second_prob != null && row.second_prob >= 0.05 && <span style={{ padding: '2px 6px', borderRadius: 4, fontSize: 9, fontFamily: 'var(--font-mono)', color: secondColor, opacity: 0.7 }}>{row.second_action.replace(/_/g, ' ')} {(row.second_prob * 100).toFixed(0)}%</span>}
                            </div>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            {row.price_target ? (
                              <div>
                                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12, color: actionColor(row.action) }}>{fmtPrice(row.price_target)}</div>
                                {row.expected_move_bps != null && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{(row.expected_move_bps / 100).toFixed(2)}%</div>}
                              </div>
                            ) : <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: (row.data_coverage_percent ?? 0) >= 80 ? '#26c281' : '#f59e0b' }}>
                            {row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(0)}%` : '—'}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: (row.missing_feature_count ?? 0) > 20 ? '#f59e0b' : '#26c281' }}>
                            {row.missing_feature_count ?? '—'}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: (row.age_seconds ?? 0) < 3600 ? 'var(--text-secondary)' : '#ef5350' }}>
                            {fmtAge(row.age_seconds)}
                          </td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{expanded ? '▲' : '▶'}</td>
                        </tr>
                        {expanded && <PredExpandedRow row={row} />}
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
            Prediction source: Redis v2:prediction:* · Raw model output · {sorted.length} rows
          </p>
        </div>
      </div>
    </div>
  );
}
