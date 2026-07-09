import { useEffect, useState } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import type { PageMeta } from '../../types/page';
import { Panel, Metric } from '../cockpitComponents';
import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';
import { usePaperAccountTruth } from '../../hooks/usePaperAccountTruth';
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ProfitTargetMonitorPanel } from '../../components/trading/ProfitTargetMonitorPanel';
import { MajorMoveReplayStatusPanel } from '../../components/trading/MajorMoveReplayStatusPanel';
import { RuntimeAlphaDynamicReadinessPanel } from '../../components/trading/RuntimeAlphaDynamicReadinessPanel';
import { useEnterpriseRealtimeResource } from '../../lib/realtime/RealtimeProvider';
import {
  CUDA_TRAINER_ACTIONABILITY_PATH,
  CUDA_TRAINER_LIVE_GATE_PATH,
  type CudaTrainerActionabilityPayload,
  type CudaTrainerLiveGatePayload,
  cudaActionabilityBlockers,
  cudaBpsText,
  cudaCountMapText,
} from '../../data/cudaTrainerLiveGate';
import { RealtimeSignalVisibilityPanel } from '../../components/realtimeSignals/RealtimeSignalVisibilityPanel';
import { PredictionSignalExplanationPanel } from '../../components/realtimeSignals/PredictionSignalExplanationPanel';

const TRAINER_PATH = '/operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';
const RUNTIME_ALPHA_SOAK_PATH = '/v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest/operator_dashboard_payload.json';
const AI_BRAIN_LINEAGE_PREVIEW = 8;
const AI_BRAIN_COVERAGE_PREVIEW = 18;
const AI_BRAIN_PREDICTION_PREVIEW = 120;

interface LiveGateRuntimePayload {
  live_gate?: string;
  execution_live_symbols?: string[];
  live_symbols?: string[];
  live_order_submit_allowed?: boolean;
  live_blocked?: boolean;
  live_blocker?: string;
  places_real_order?: boolean;
}

function resolveGateChipClass(p: LiveGateRuntimePayload | null | undefined): string {
  if (!p) return 'chip solid-warn';
  const submitOk = p.live_order_submit_allowed === true && p.live_blocked !== true && p.places_real_order !== false;
  return submitOk ? 'chip solid-live' : 'chip solid-warn';
}

function resolveGateLabel(p: LiveGateRuntimePayload | null | undefined): string {
  if (!p) return 'BLOCKED';
  if (p.live_order_submit_allowed === false || p.live_blocked === true) {
    return p.live_blocker ?? 'BLOCKED';
  }
  return p.live_gate ?? 'operator gated';
}

interface TrainingMetrics {
  status?: string;
  device?: string;
  cuda_active?: boolean;
  cuda_claim_verified?: boolean;
  gpu_name?: string | null;
  vram_allocated_mb?: number | null;
  training_steps?: number;
  train_rows?: number;
  validation_rows?: number;
  loss_before?: number | null;
  loss_after?: number | null;
  metrics?: {
    batch_covers_available_examples?: boolean;
    available_examples?: number;
    selected_examples?: number;
    uses_amp?: boolean;
    trusted_rows_loaded?: number;
    optimizer_steps_this_cycle?: number;
    parameter_hash_before?: string | null;
    parameter_hash_after?: string | null;
    weight_delta_norm?: number | null;
    checkpoint_weight_blob_written?: boolean;
    checkpoint_reload_verified?: boolean;
  };
}

interface ParallelRollout {
  status?: string;
  backend?: string;
  envs_instantiated?: number;
  envs_requested?: number;
  worker_count?: number;
  rollout_n_steps?: number;
  covers_all_loaded_examples?: boolean;
  unique_symbols?: number;
  unique_timeframes?: number;
  reward_avg_bps?: number | null;
}

interface TrainerStatus {
  trainer_source?: string;
  model_source?: string;
  checkpoint_id?: string;
  cuda_active?: boolean;
  model_device?: string;
  model_tensors_device_verified?: boolean;
  examples_built?: number;
  input_dim?: number;
  live_gate?: string;
  live_symbols?: string[];
  trainer_process_status?: string;
  cuda_inference_status?: string;
  prediction_publication_status?: string;
  online_learning_status?: string;
  effective_trainer_mode?: string;
  last_successful_weight_update_at?: string | null;
  legacy_hybrid_parity_claim?: string;
  training_batch_policy?: {
    batch_covers_available_examples?: boolean;
    available_examples?: number;
    selected_examples?: number;
  };
  model_architecture?: {
    hidden_size?: number;
    residual_block_count?: number;
  };
  parallel_environment_rollout?: ParallelRollout;
}

interface PredictionRow {
  prediction_id?: string;
  symbol?: string;
  timeframe?: string;
  selected_action?: string;
  expected_move_after_cost_bps?: number;
  confidence_calibrated?: number;
  data_coverage_percent?: number;
  missing_feature_count?: number;
  stale_feature_count?: number;
  paper_fill_gate_status?: string;
}

interface ReasonCountRow {
  reason?: string;
  count?: number;
}

interface RuntimeAlphaSoakPayload {
  generated_utc?: string;
  proof_status?: string;
  completion_window_elapsed_seconds?: number;
  observation_density_status?: string;
  last_observation_freshness_status?: string;
  high_severity_alerts?: unknown[];
  root_cause?: string;
  paper_equity?: number | null;
  paper_equity_source?: string | null;
  forward_paper_intent_rows?: number;
  forward_paper_symbol_count?: number;
  forward_paper_timeframe_count?: number;
  forward_paper_symbol_counts?: ReasonCountRow[];
  forward_paper_timeframe_counts?: ReasonCountRow[];
  forward_paper_accepted_candidate_rows?: number;
  trainer_feedback_row_count?: number;
  trainer_feedback_quarantined_row_count?: number;
}

interface LineageSample {
  trainer_prediction_record?: { prediction_id?: string; symbol?: string };
  risk_decision_record?: { risk_decision_id?: string; risk_reason_code?: string; risk_action?: string };
  orchestrator_decision_record?: { decision_id?: string; decision_action?: string; decision_reason_code?: string };
  paper_execution_ledger_entry?: { paper_trade_id?: string; ledger_action?: string; ledger_reason_code?: string };
}

interface TrainerPayload {
  generated_est?: string;
  generated_at?: string;
  payload_age_seconds?: number;
  go_no_go?: string;
  trainer_source?: string;
  model_source?: string;
  checkpoint_id?: string;
  live_gate?: string;
  trader_state?: string;
  live_order_submit_blocker?: string;
  prediction_count?: number;
  prediction_rows?: number;
  prediction_grid_rows?: number;
  prediction_grid_expected_rows?: number;
  prediction_grid_current?: boolean;
  current_prediction_count?: number;
  missing_prediction_rows_count?: number;
  stale_prediction_rows_count?: number;
  non_current_prediction_rows_count?: number;
  prediction_coverage_status?: string;
  prediction_actionability_status?: string;
  missing_prediction_symbols?: string[];
  paper_actionability_allowed_rows_count?: number;
  paper_actionability_blocked_rows_count?: number;
  paper_actionability_block_reason_counts?: Record<string, number>;
  blocked_prediction_rows?: number;
  valid_symbol_count?: number;
  timeframes?: string[];
  training_steps_total?: number;
  training_steps_last_hour?: number;
  trainer_process_status?: string;
  cuda_inference_status?: string;
  prediction_publication_status?: string;
  online_learning_status?: string;
  effective_trainer_mode?: string;
  last_successful_weight_update_at?: string | null;
  trusted_rows_loaded?: number;
  optimizer_steps_this_cycle?: number;
  parameter_hash_before?: string | null;
  parameter_hash_after?: string | null;
  weight_delta_norm?: number | null;
  checkpoint_weight_blob_written?: boolean;
  checkpoint_reload_verified?: boolean;
  persistent_trainer_service_active?: boolean;
  persistent_trainer_pid?: number | null;
  persistent_trainer_uptime_seconds?: number | null;
  samples_per_second?: number | null;
  predictions_per_second?: number | null;
  training_steps_per_minute?: number | null;
  batch_size?: number | null;
  target_batch_size?: number | null;
  dataloader_workers?: number | null;
  pinned_memory?: boolean;
  amp_enabled?: boolean;
  train_rows?: number | null;
  validation_rows?: number | null;
  gpu_name?: string | null;
  gpu_utilization_percent?: number | null;
  vram_used_mb?: number | null;
  vram_total_mb?: number | null;
  cpu_utilization_percent?: number | null;
  ram_used_gb?: number | null;
  ram_total_gb?: number | null;
  checkpoint_count?: number | null;
  checkpoint_total_size_gb?: number | null;
  checkpoint_rollover_status?: string;
  trainer_bridge_active?: boolean;
  trainer_bridge_masked?: boolean;
  rl_core_primary_overwrites?: number;
  rl_core_sidecar_rows?: number;
  parity_status?: string;
  hybrid_trainer_methods_inventoried?: number;
  required_missing_parity_methods?: number;
  paper_accepted_fills?: number | null;
  paper_open_positions?: number | null;
  paper_confidence_trial_guard_status?: string;
  paper_confidence_trial_guard_reason?: string;
  paper_confidence_trial_guard_trial_enabled?: boolean;
  resource_bottleneck_reason?: string;
  lineage_count?: number;
  trainer?: TrainerStatus;
  metrics?: {
    training?: TrainingMetrics;
    parallel_environment_rollout?: ParallelRollout;
    data_coverage_avg?: number;
    missing_feature_count_total?: number;
    stale_feature_count_total?: number;
  };
  predictions_by_symbol?: PredictionRow[];
  lineage_samples?: LineageSample[];
  live_switch?: {
    visible?: boolean;
    enabled?: boolean;
    disabled_reason?: string;
    backend_live_enable_callable?: boolean;
  };
}

interface EnterpriseAiPageContract {
  ppo_tensor_provider_features?: boolean;
  masa_tensor_provider_features?: boolean;
  provider_feature_count_by_provider?: Record<string, number>;
  provider_features_in_tensor?: unknown;
  provider_contribution_last_50?: { status?: string; sample_count?: number } | Record<string, unknown>;
  altdata_actionability?: {
    blocked?: number | null;
    reduced?: number | null;
    hedged?: number | null;
    trade_block_score?: number | null;
    reduce_size_score?: number | null;
    hedge_required_score?: number | null;
  };
  next_replay_or_backtest?: string;
  live_gate?: string;
  routes_to_live?: boolean;
  places_real_order?: boolean;
}

interface EnterpriseAiBrainSnapshot {
  ai_page_contract?: EnterpriseAiPageContract;
  provider_feature_counts?: Record<string, number>;
  provider_confluence_available?: boolean;
}

function pct(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—';
}

function bps(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value / 100).toFixed(2)}%` : '—';
}

function loss(value?: number | null): string {
  return value === undefined || value === null ? '—' : value.toFixed(4);
}

function runtimeLabel(value: unknown, fallback = 'current runtime pending'): string {
  if (value === null || value === undefined || value === '') return fallback;
  const text = String(value);
  const sanitized = text
    .replace(/payload/gi, 'source')
    .replace(/operator_dashboard/gi, 'operator monitor')
    .replace(/operator_runtime/gi, 'runtime source')
    .replace(/paper/gi, 'runtime');
  const labels: Record<string, string> = {
    enabled_operator_approved: 'gate approved',
    LIVE_ARMED_BALANCE_HOLD: 'armed, balance hold',
    INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER: 'orders held until available margin covers the minimum order',
    FULL_FUNCTION_PARITY_BY_V2_OWNERSHIP_MODEL: 'full function parity by V2 ownership model',
    SCHEDULED_ONESHOT_TRAINING_TIMER_ACTIVE_SERVICE_NOT_PERSISTENT: 'scheduled trainer timer active; service runs as oneshot cycles',
    DATASET_TOO_SMALL: 'approved dataset is smaller than target batch',
    GPU_TRAINING_ACTIVE_LOW_UTILIZATION: 'GPU training active with low utilization',
    MODEL_TOO_SMALL_TO_SATURATE_GPU_OR_BATCH_LIMITED: 'model or batch size does not saturate GPU',
    MODEL_TOO_SMALL_TO_SATURATE_GPU: 'model is too small to saturate GPU',
    PERSISTENT_TRAINING_RESOURCE_TELEMETRY_CURRENT: 'persistent trainer resource telemetry current',
    TRIAL_PAUSED_DRAWDOWN_GUARD: 'runtime trial paused by drawdown guard',
    TRIAL_BLOCKED_INSUFFICIENT_OUTCOME_SAMPLE: 'runtime trial blocked pending outcome evidence',
    TRIAL_ACTIVE_NO_DRAWDOWN: 'runtime trial active with no drawdown breach',
  };
  return labels[text] ?? sanitized.replaceAll('_', ' ').toLowerCase();
}

function runtimeSourceLabel(value: unknown, fallback = 'current runtime source'): string {
  if (value === null || value === undefined || value === '') return fallback;
  const text = String(value).trim();
  if (!text) return fallback;
  const lower = text.toLowerCase();
  if (lower.includes('cuda') && lower.includes('trainer')) return 'CUDA trainer live-gate source';
  if (lower.includes('native_trainer') || lower.includes('trainer')) return 'native trainer runtime source';
  if (
    lower.includes('operator_dashboard') ||
    lower.includes('operator_runtime') ||
    lower.includes('payload') ||
    lower.includes('.json') ||
    lower.startsWith('/')
  ) {
    return fallback;
  }
  return runtimeLabel(text, fallback);
}

function reasonCountsLabel(value: Record<string, number> | undefined, limit = 3): string {
  const entries = Object.entries(value ?? {})
    .filter(([, count]) => Number.isFinite(count) && count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
  if (!entries.length) return 'block reasons pending';
  return entries.map(([reason, count]) => `${runtimeLabel(reason)}: ${count}`).join(' · ');
}

function numberMetric(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'current runtime pending';
}

function predictionAction(action: unknown): 'BUY' | 'SELL' | 'HOLD' {
  const raw = String(action ?? '').toUpperCase();
  if (raw.includes('LONG') || raw.includes('BUY')) return 'BUY';
  if (raw.includes('SHORT') || raw.includes('SELL')) return 'SELL';
  return 'HOLD';
}

type ActionBucketKey = ReturnType<typeof predictionAction>;

interface ActionBucket {
  key: ActionBucketKey;
  label: string;
  count: number;
  color: string;
}

interface ActionablePredictionSummary {
  totalRows: number;
  actionableRows: number;
  paperReadyRows: number;
  avgConfidence: number | null;
  avgCoverage: number | null;
  dominantAction: ActionBucket;
  buckets: ActionBucket[];
  topActionSignals: {
    symbol: string;
    timeframe: string;
    action: ActionBucketKey;
    edgeBps: number | null;
    confidence: number | null;
    coverage: number | null;
    paperStatus: string;
  }[];
}

function fin(value: unknown): number | null {
  const asNumber = typeof value === 'number' ? value : null;
  return asNumber != null && Number.isFinite(asNumber) ? asNumber : null;
}

function formatConfidence(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function paperReady(status: unknown): boolean {
  const normalized = String(status ?? '').toLowerCase();
  return normalized.includes('allow') || normalized.includes('ready') || normalized === 'true' || normalized.includes('pass');
}

function signalTone(action: ActionBucketKey): 'long' | 'short' | 'hold' {
  if (action === 'BUY') return 'long';
  if (action === 'SELL') return 'short';
  return 'hold';
}

function signalArrow(action: ActionBucketKey): string {
  return action === 'BUY' ? '↗' : action === 'SELL' ? '↘' : '→';
}

function bpsOrDash(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || !Number.isFinite(value)) return '—';
  const pct = value / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function ActionablePredictionCard({
  signal,
}: {
  signal: ActionablePredictionSummary['topActionSignals'][number];
}): JSX.Element {
  const tone = signalTone(signal.action);
  const confPct = signal.confidence == null ? null : signal.confidence * 100;
  const confTxt = confPct == null ? 'confidence pending' : `${confPct.toFixed(1)}%`;
  const coverageTxt = signal.coverage == null ? 'coverage pending' : `${signal.coverage.toFixed(1)}%`;
  const edgeTxt = bpsOrDash(signal.edgeBps);
  const executionReady = paperReady(signal.paperStatus);

  return (
    <div className={`pred-card pred-card--${tone}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div className="pred-card__symbol">{signal.symbol}</div>
          <small style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{signal.timeframe}</small>
        </div>
        <span className={`chip solid-${executionReady ? 'ok' : 'warn'}`}>{executionReady ? 'execution-ready' : 'execution-held'}</span>
      </div>
      <div className={`pred-card__direction pred-card__direction--${tone}`}>
        {signalArrow(signal.action)} {signal.action}
      </div>
      <div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '0.72rem',
            color: 'var(--text-secondary)',
            marginBottom: 3,
          }}
        >
          <span>Edge</span>
          <strong style={{ color: 'var(--text-primary)' }}>{edgeTxt}</strong>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
          <span>Confidence</span>
          <strong style={{ color: 'var(--text-primary)' }}>{confTxt}</strong>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
          <span>Coverage</span>
          <strong style={{ color: 'var(--text-primary)' }}>{coverageTxt}</strong>
        </div>
      </div>
      <div className="pred-card__meta">
        <span style={{ color: tone === 'long' ? 'var(--buy, #00d4a3)' : tone === 'short' ? 'var(--sell, #f6465d)' : 'var(--text-secondary)' }}>
          {confTxt}
        </span>
        <span className="pred-card__target">
          <strong>{coverageTxt}</strong>
        </span>
      </div>
    </div>
  );
}

function TrainerPredictionIntelligencePanel({ summary }: { summary: ActionablePredictionSummary }): JSX.Element {
  const totalRows = summary.totalRows;
  const bucketData = summary.buckets.map((bucket) => ({
    ...bucket,
    percent: totalRows > 0 ? (bucket.count / totalRows) * 100 : 0,
  }));
  const dominant = summary.dominantAction;
  const dominantTone = signalTone(dominant.key);
  const avgConfidence = summary.avgConfidence == null ? 'pending' : `${summary.avgConfidence.toFixed(1)}%`;
  const avgCoverage =
    summary.avgCoverage == null ? 'pending' : `${summary.avgCoverage.toFixed(1)}%`;
  const actionableRatio =
    totalRows > 0 ? `${summary.actionableRows}/${totalRows} actionable` : 'pending actionable set';

  return (
    <Panel id="trainer-prediction-intelligence" title="AI Trainer Decision Lens" right={<span className={`chip solid-${dominant.key === 'BUY' ? 'ok' : dominant.key === 'SELL' ? 'warn' : 'paper'}`}>{dominant.label}</span>}>
      <div className="ai-hero-grid">
        <div className="ai-hero-info">
          <div className={`ai-hero-direction ai-hero-direction--${dominantTone}`}>
            {dominantTone === 'long' ? '↗' : dominantTone === 'short' ? '↘' : '—'} {dominant.label}
          </div>
          <div className="ai-hero-summary">
            This training cycle currently has {actionableRatio} candidates.
            {summary.paperReadyRows > 0 ? ` ${summary.paperReadyRows} are execution-ready after gate checks.` : ''}
          </div>
          <div className="ai-hero-stats">
            <div className="ai-hero-stat">
              <div className="ai-hero-stat__val">{summary.totalRows}</div>
              <div className="ai-hero-stat__label">Total prediction rows</div>
            </div>
            <div className="ai-hero-stat">
              <div className="ai-hero-stat__val">{avgConfidence}</div>
              <div className="ai-hero-stat__label">Average confidence</div>
            </div>
            <div className="ai-hero-stat">
              <div className="ai-hero-stat__val">{avgCoverage}</div>
              <div className="ai-hero-stat__label">Average coverage</div>
            </div>
          </div>
        </div>
        <div style={{ display: 'grid', gap: 12 }}>
          <div>
            <ResponsiveContainer width="100%" height={150}>
              <PieChart>
                <Pie
                  data={bucketData.filter((item) => item.count > 0)}
                  dataKey="count"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  innerRadius="35%"
                  outerRadius="75%"
                  startAngle={90}
                  endAngle={-270}
                >
                  {bucketData.map((entry, index) => (
                    <Cell key={`${entry.key}-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => `${Number(value).toLocaleString('en-US')} rows`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div>
            <ResponsiveContainer width="100%" height={150}>
              <BarChart data={bucketData} margin={{ top: 5, right: 10, left: 0, bottom: 20 }}>
                <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                <YAxis tickFormatter={(value: number) => `${value}`} tick={{ fontSize: 10 }} />
                <Tooltip formatter={(value) => `${Number(value).toLocaleString('en-US')} rows`} />
                <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                  {bucketData.map((entry, index) => (
                    <Cell key={`${entry.key}-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
      {bucketData.length > 0 ? (
        <div className="cockpit-lineage-grid" style={{ marginTop: '12px' }}>
          {bucketData.map((bucket) => (
            <div key={bucket.key}>
              <span>{bucket.label}</span>
              <strong>{bucket.count.toLocaleString('en-US')}</strong>
              <small>{bucket.percent.toFixed(0)}% of this selection</small>
            </div>
          ))}
        </div>
      ) : (
        <p className="cockpit-evidence-note">No prediction rows are currently available for the decision lens.</p>
      )}
      {summary.topActionSignals.length > 0 ? (
        <div style={{ marginTop: '12px' }}>
          <p className="cockpit-evidence-note" style={{ marginBottom: '8px' }}>
            Top live opportunities by edge (non-hold rows first):
          </p>
          <div className="prediction-card-grid">
            {summary.topActionSignals.map((signal) => (
              <ActionablePredictionCard key={`${signal.symbol}-${signal.timeframe}-${signal.action}`} signal={signal} />
            ))}
          </div>
        </div>
      ) : (
        <p className="cockpit-evidence-note">No immediate non-hold candidates this cycle.</p>
      )}
    </Panel>
  );
}

function actionSummary(predictions: PredictionRow[]): ActionablePredictionSummary {
  const totalRows = predictions.length;
  const counts: Record<ActionBucketKey, number> = { BUY: 0, SELL: 0, HOLD: 0 };
  let confidenceTotal = 0;
  let coverageTotal = 0;
  let confidenceCount = 0;
  let coverageCount = 0;
  let paperReadyRows = 0;

  const topActionSignals = predictions
    .map((row) => {
      const action = predictionAction(row.selected_action);
      const confidence = fin(row.confidence_calibrated);
      const coverage = fin(row.data_coverage_percent);
      const edgeBps = fin(row.expected_move_after_cost_bps);
      const paperStatus = row.paper_fill_gate_status ?? 'pending';
      if (confidence != null) {
        confidenceTotal += confidence;
        confidenceCount += 1;
      }
      if (coverage != null) {
        coverageTotal += coverage;
        coverageCount += 1;
      }
      if (paperReady(paperStatus)) paperReadyRows += 1;
      counts[action] += 1;
      return {
        symbol: row.symbol ?? '—',
        timeframe: row.timeframe ?? '—',
        action,
        edgeBps,
        confidence,
        coverage,
        paperStatus,
      };
    })
    .filter((row) => row.action !== 'HOLD')
    .sort((a, b) => Math.abs(b.edgeBps ?? 0) - Math.abs(a.edgeBps ?? 0))
    .slice(0, 6);

  const actionBuckets = (
    [
      {
        key: 'BUY',
        label: 'Long',
        color: 'var(--buy, #00d4a3)',
        count: counts.BUY,
      },
      {
        key: 'SELL',
        label: 'Short',
        color: 'var(--sell, #f6465d)',
        count: counts.SELL,
      },
      {
        key: 'HOLD',
        label: 'Hold',
        color: 'var(--text-secondary, #6b7c93)',
        count: counts.HOLD,
      },
    ] as ActionBucket[]
  ).sort((a, b) => b.count - a.count);

  const dominantAction = actionBuckets[0] ?? { key: 'HOLD', label: 'Hold', count: totalRows, color: 'var(--text-secondary, #6b7c93)' };
  const avgConfidence = confidenceCount > 0 ? (confidenceTotal / confidenceCount) * 100 : null;
  const avgCoverage = coverageCount > 0 ? coverageTotal / coverageCount : null;

  return {
    totalRows,
    actionableRows: totalRows - counts.HOLD,
    paperReadyRows,
    avgConfidence,
    avgCoverage,
    dominantAction,
    buckets: actionBuckets,
    topActionSignals,
  };
}

export default function AiBrainPage(): JSX.Element {
  const [showAllLineageRows, setShowAllLineageRows] = useState(false);
  const [showAllCoverageSymbols, setShowAllCoverageSymbols] = useState(false);
  const [detailsHydrated, setDetailsHydrated] = useState(false);
  const {
    data: gatePayload,
    ageSeconds: gateAge,
    error: gateError,
  } = usePayloadFile<TrainerPayload & CudaTrainerLiveGatePayload>(CUDA_TRAINER_LIVE_GATE_PATH, 15_000);
  const {
    data: sourcePayload,
    ageSeconds: sourceAge,
    error: sourceError,
  } = usePayloadFile<TrainerPayload>(TRAINER_PATH, 15_000);
  const {
    data: actionabilityPayload,
    ageSeconds: actionabilityAge,
  } = usePayloadFile<CudaTrainerActionabilityPayload>(CUDA_TRAINER_ACTIONABILITY_PATH, 30_000);
  const {
    data: runtimeAlphaSoak,
    ageSeconds: runtimeAlphaAge,
  } = usePayloadFile<RuntimeAlphaSoakPayload>(RUNTIME_ALPHA_SOAK_PATH, 30_000);
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const { account: paperAccount } = usePaperAccountTruth(8_000, { requireTraderScope: true });
  const enterpriseAiSnapshot = useEnterpriseRealtimeResource<EnterpriseAiBrainSnapshot>('ai_brain');
  const payload = gatePayload ?? sourcePayload;
  const enterpriseAiPayload = enterpriseAiSnapshot?.payload;
  const aiPageContract = enterpriseAiPayload?.ai_page_contract;
  const aiProviderCounts = aiPageContract?.provider_feature_count_by_provider
    ?? enterpriseAiPayload?.provider_feature_counts
    ?? {};
  const aiProviderRows = ['coinglass', 'santiment', 'moralis'].map((provider) => ({
    provider,
    count: aiProviderCounts[provider] ?? 0,
  }));
  const aiPageContractReady = Boolean(aiPageContract)
    && aiPageContract?.routes_to_live === false
    && aiPageContract?.places_real_order === false;
  const ageSeconds = gatePayload ? gateAge : sourceAge;
  const error = gateError && !sourcePayload ? gateError : sourceError && !gatePayload ? sourceError : null;
  const trainer = payload?.trainer;
  const training = payload?.metrics?.training;
  const parallelRollout = payload?.metrics?.parallel_environment_rollout ?? trainer?.parallel_environment_rollout;
  const batchPolicy = trainer?.training_batch_policy ?? training?.metrics;
  const predictions = payload?.predictions_by_symbol ?? [];
  const predictionSummary = actionSummary(predictions);
  const lineage = payload?.lineage_samples ?? [];
  const visiblePredictions = predictions.slice(0, AI_BRAIN_PREDICTION_PREVIEW);
  const visibleLineage = showAllLineageRows ? lineage : lineage.slice(0, AI_BRAIN_LINEAGE_PREVIEW);
  const liveSwitch = payload?.live_switch;
  const actionabilityBlockers = cudaActionabilityBlockers(actionabilityPayload);
  const trainerLiveGate = liveGateRuntime?.live_gate ?? gatePayload?.live_gate ?? trainer?.live_gate ?? 'loading';
  const trainerLiveSymbols = liveGateRuntime?.live_symbols ?? gatePayload?.live_symbols ?? trainer?.live_symbols ?? [];
  const executionLiveSymbols = liveGateRuntime?.execution_live_symbols ?? gatePayload?.execution_live_symbols ?? gatePayload?.live_readiness?.execution_live_symbols ?? [];
  const falseNegativeAttribution = actionabilityPayload?.false_negative_attribution;
  const actionabilitySimulation = actionabilityPayload?.threshold_actionability_simulation;
  const actionabilityOverlay = actionabilityPayload?.paper_actionability_overlay;
  const actionabilityEdge = actionabilityPayload?.edge_after_actionability_overlay;
  const recommendedSimulation = actionabilitySimulation?.simulations?.find(
    (simulation) => simulation.simulation_id === actionabilitySimulation.recommended_simulation_id,
  );
  const coverageSymbols = runtimeAlphaSoak?.forward_paper_symbol_counts ?? [];
  const visibleCoverageSymbols = showAllCoverageSymbols
    ? coverageSymbols
    : coverageSymbols.slice(0, AI_BRAIN_COVERAGE_PREVIEW);
  const coverageTimeframes = runtimeAlphaSoak?.forward_paper_timeframe_counts ?? [];

  useEffect(() => {
    const handle = window.setTimeout(() => setDetailsHydrated(true), 750);
    return () => window.clearTimeout(handle);
  }, []);

  return (
    <article
      className="enterprise-cockpit-page"
      data-testid="page-ai-brain"
      data-page-id={(meta as PageMeta).id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Trainer Brain</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="enterprise-cockpit-hero-chips">
          <span className={trainer?.cuda_active ? 'chip solid-ok' : 'chip solid-warn'}>
            CUDA: {trainer?.cuda_active ? 'ACTIVE' : 'FALLBACK'}
          </span>
          <span className={resolveGateChipClass(liveGateRuntime)}>Live: {resolveGateLabel(liveGateRuntime)}</span>
          <span className={`chip ${ageClass(ageSeconds) === 'ok' ? 'solid-ok' : 'solid-warn'}`}>Age: {fmtAge(ageSeconds)}</span>
        </div>
      </header>

      {error ? <p className="cockpit-evidence-gap" role="alert">Trainer source reconnecting: {error}</p> : null}

      <ProfitTargetMonitorPanel />
      <MajorMoveReplayStatusPanel />
      <RuntimeAlphaDynamicReadinessPanel compact />
      {detailsHydrated ? (
        <>
      <RealtimeSignalVisibilityPanel surface="ai-brain" variant="admin" />
      <PredictionSignalExplanationPanel surface="ai-brain" />
      <Panel
        id="enterprise-ai-data-plane"
        title="Enterprise AI Data Plane"
        right={<span className={aiPageContractReady ? 'chip solid-ok' : 'chip solid-warn'}>{aiPageContractReady ? 'READY' : 'PARTIAL'}</span>}
      >
        <div className="cockpit-analytics-grid">
          <Metric label="PPO tensor" value={aiPageContract?.ppo_tensor_provider_features ? 'provider features visible' : 'pending'} />
          <Metric label="MASA tensor" value={aiPageContract?.masa_tensor_provider_features ? 'provider features visible' : 'pending'} />
          <Metric label="Confluence" value={enterpriseAiPayload?.provider_confluence_available ? 'available' : 'pending'} />
          <Metric label="Last 50 contribution" value={String((aiPageContract?.provider_contribution_last_50 as { status?: string } | undefined)?.status ?? 'not available')} />
          <Metric label="Blocked / reduced / hedged" value={`${aiPageContract?.altdata_actionability?.blocked ?? 0} / ${aiPageContract?.altdata_actionability?.reduced ?? 0} / ${aiPageContract?.altdata_actionability?.hedged ?? 0}`} />
          <Metric label="Replay" value={runtimeLabel(aiPageContract?.next_replay_or_backtest)} />
          <Metric label="Live gate" value={runtimeLabel(aiPageContract?.live_gate ?? 'blocked_human_only')} />
          <Metric label="Routes to live" value={String(aiPageContract?.routes_to_live === true)} />
        </div>
        <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--compact" role="region" aria-label="Scrollable provider tensor feature counts" style={{ marginTop: '1rem' }}>
          <div className="signal-stream-table" role="table">
            <div className="signal-stream-row signal-stream-row--head" role="row">
              <span>Provider</span>
              <span>Feature count</span>
              <span>Tensor channel</span>
            </div>
            {aiProviderRows.map((row) => (
              <div className="signal-stream-row" role="row" key={`ai-provider-${row.provider}`}>
                <span><strong>{row.provider}</strong></span>
                <span>{row.count}</span>
                <span>{aiPageContract?.provider_features_in_tensor ? 'present' : 'pending'}</span>
              </div>
            ))}
          </div>
        </div>
      </Panel>
      <TrainerPredictionIntelligencePanel summary={predictionSummary} />

      <Panel
        id="trainer-runtime-symbol-timeframe-coverage"
        title="Current Trainer Coverage"
        right={<span className={`chip solid-${ageClass(runtimeAlphaAge, 600)}`}>{fmtAge(runtimeAlphaAge)}</span>}
      >
        <div className="cockpit-analytics-grid">
          <Metric label="Execution intents" value={runtimeAlphaSoak?.forward_paper_intent_rows ?? 'current runtime pending'} />
          <Metric label="Symbols covered" value={runtimeAlphaSoak?.forward_paper_symbol_count ?? 'current runtime pending'} />
          <Metric label="Timeframes covered" value={runtimeAlphaSoak?.forward_paper_timeframe_count ?? 'current runtime pending'} />
          <Metric label="Executable candidates" value={runtimeAlphaSoak?.forward_paper_accepted_candidate_rows ?? 0} />
          <Metric label="Trainer-ready feedback" value={runtimeAlphaSoak?.trainer_feedback_row_count ?? 0} detail={`${runtimeAlphaSoak?.trainer_feedback_quarantined_row_count ?? 0} quarantined`} />
          <Metric label="Account equity" value={numberMetric(runtimeAlphaSoak?.paper_equity, 2)} detail={runtimeLabel(runtimeAlphaSoak?.paper_equity_source ?? 'Connecting stream')} />
        </div>
        <p className="cockpit-evidence-note" style={{ marginTop: '0.75rem' }}>
          {runtimeAlphaSoak?.root_cause ?? 'Current no-trade root cause pending from runtime-alpha soak monitor.'}
        </p>
        <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--compact" role="region" aria-label="Scrollable current trainer symbol and timeframe coverage">
          <div className="signal-stream-table" role="table">
            <div className="signal-stream-row signal-stream-row--head" role="row">
              <span>Symbol</span>
              <span>Rows</span>
              <span>Timeframes</span>
            </div>
            {visibleCoverageSymbols.map((row) => (
              <div className="signal-stream-row" role="row" key={`coverage-${row.reason ?? 'unknown'}`}>
                <span><strong>{row.reason ?? 'unknown'}</strong></span>
                <span>{row.count ?? 0}</span>
                <span>{coverageTimeframes.map((tf) => tf.reason).filter(Boolean).join(', ') || 'current runtime pending'}</span>
              </div>
            ))}
          </div>
        </div>
        {coverageTimeframes.length ? (
          <p className="cockpit-evidence-note" style={{ marginTop: '0.5rem' }}>
            Timeframe row counts: {coverageTimeframes.map((row) => `${row.reason}: ${row.count ?? 0}`).join(' · ')}
          </p>
        ) : null}
        {coverageSymbols.length > AI_BRAIN_COVERAGE_PREVIEW ? (
          <button
            className="lineage-raw-toggle"
            onClick={() => setShowAllCoverageSymbols((value) => !value)}
            style={{ marginTop: 8 }}
            type="button"
          >
            {showAllCoverageSymbols ? 'Show fewer symbols' : `Show all ${coverageSymbols.length} symbols`}
          </button>
        ) : null}
      </Panel>

      <Panel id="trainer-brain-runtime" title="Runtime">
        <div className="cockpit-analytics-grid">
          <Metric label="GO / NO-GO" value={payload?.go_no_go ?? '—'} />
          <Metric label="GPU" value={payload?.gpu_name ?? training?.gpu_name ?? trainer?.model_device ?? '—'} />
          <Metric label="GPU util" value={numberMetric(payload?.gpu_utilization_percent, 1)} detail="current nvidia-smi sample when available" />
          <Metric label="VRAM MB" value={payload?.vram_used_mb != null ? `${numberMetric(payload.vram_used_mb, 1)} / ${numberMetric(payload.vram_total_mb, 0)}` : training?.vram_allocated_mb?.toFixed(1) ?? '—'} />
          <Metric label="CPU / RAM" value={`${numberMetric(payload?.cpu_utilization_percent, 1)}% / ${numberMetric(payload?.ram_used_gb, 1)} GB`} detail={`${numberMetric(payload?.ram_total_gb, 1)} GB total`} />
          <Metric label="Persistent service" value={payload?.persistent_trainer_service_active ? 'active' : 'not active'} detail={`pid ${payload?.persistent_trainer_pid ?? 'pending'} · uptime ${numberMetric(payload?.persistent_trainer_uptime_seconds, 0)}s`} />
          <Metric label="Process status" value={runtimeLabel(payload?.trainer_process_status ?? trainer?.trainer_process_status)} detail={`inference ${runtimeLabel(payload?.cuda_inference_status ?? trainer?.cuda_inference_status)}`} />
          <Metric label="Publication status" value={runtimeLabel(payload?.prediction_publication_status ?? trainer?.prediction_publication_status)} />
          <Metric label="Online learning" value={runtimeLabel(payload?.online_learning_status ?? trainer?.online_learning_status)} detail={runtimeLabel(payload?.effective_trainer_mode ?? trainer?.effective_trainer_mode)} />
          <Metric label="Last weight update" value={payload?.last_successful_weight_update_at ?? trainer?.last_successful_weight_update_at ?? 'none'} />
          <Metric label="Trusted rows" value={payload?.trusted_rows_loaded ?? training?.metrics?.trusted_rows_loaded ?? 0} detail={`${payload?.optimizer_steps_this_cycle ?? training?.metrics?.optimizer_steps_this_cycle ?? 0} optimizer steps this cycle`} />
          <Metric label="Weight delta" value={numberMetric(payload?.weight_delta_norm ?? training?.metrics?.weight_delta_norm, 8)} detail={payload?.parameter_hash_before && payload?.parameter_hash_after ? `${payload.parameter_hash_before.slice(0, 8)} → ${payload.parameter_hash_after.slice(0, 8)}` : 'hash evidence pending'} />
          <Metric label="Training steps" value={payload?.training_steps_total ?? training?.training_steps ?? 0} detail={`${payload?.training_steps_last_hour ?? 0} last hour`} />
          <Metric label="Train rows" value={payload?.train_rows ?? training?.train_rows ?? 0} />
          <Metric label="Validation rows" value={payload?.validation_rows ?? training?.validation_rows ?? 0} />
          <Metric label="Batch full" value={String(batchPolicy?.batch_covers_available_examples ?? false)} />
          <Metric label="Batch / target" value={`${payload?.batch_size ?? batchPolicy?.selected_examples ?? training?.train_rows ?? 0} / ${payload?.target_batch_size ?? 'target pending'}`} />
          <Metric label="Samples/sec" value={numberMetric(payload?.samples_per_second, 2)} />
          <Metric label="Predictions/sec" value={numberMetric(payload?.predictions_per_second, 2)} />
          <Metric label="DataLoader" value={`${payload?.dataloader_workers ?? 'pending'} workers`} detail={`${payload?.pinned_memory ? 'pinned memory' : 'unpinned'} · ${payload?.amp_enabled ? 'AMP enabled' : 'AMP pending'}`} />
          <Metric label="Loss before" value={loss(training?.loss_before)} />
          <Metric label="Loss after" value={loss(training?.loss_after)} />
          <Metric label="Input dim" value={trainer?.input_dim ?? '—'} />
          <Metric label="Hidden / residual" value={`${trainer?.model_architecture?.hidden_size ?? '—'} / ${trainer?.model_architecture?.residual_block_count ?? '—'}`} />
          <Metric label="Predictions" value={`${payload?.prediction_grid_rows ?? payload?.prediction_count ?? 0} / ${payload?.prediction_grid_expected_rows ?? 'expected pending'}`} />
          <Metric label="Avg coverage" value={pct(payload?.metrics?.data_coverage_avg)} />
          <Metric
            label="Checkpoint"
            value={payload?.checkpoint_count != null ? `${payload.checkpoint_count} checkpoints ready` : 'checkpoint status pending'}
            detail={runtimeLabel(payload?.checkpoint_rollover_status)}
          />
          <Metric label="Checkpoint retention" value={`${payload?.checkpoint_count ?? 0} files`} detail={`${numberMetric(payload?.checkpoint_total_size_gb, 4)} GB · ${runtimeLabel(payload?.checkpoint_rollover_status)}`} />
          <Metric label="Bottleneck" value={runtimeLabel(payload?.resource_bottleneck_reason)} />
        </div>
      </Panel>

      <Panel id="trainer-legacy-parity" title="Legacy Hybrid Parity">
        <div className="cockpit-analytics-grid">
          <Metric label="Parity" value={runtimeLabel(payload?.parity_status ?? trainer?.legacy_hybrid_parity_claim)} />
          <Metric label="Methods inventoried" value={payload?.hybrid_trainer_methods_inventoried ?? 324} />
          <Metric label="Required missing" value={payload?.required_missing_parity_methods ?? 0} />
          <Metric label="Bridge" value={payload?.trainer_bridge_masked ? 'masked / inactive' : 'check bridge state'} />
          <Metric label="RL-core overwrite" value={payload?.rl_core_primary_overwrites ?? 0} />
          <Metric label="Parallel env status" value={parallelRollout?.status ?? '—'} />
          <Metric label="Backend" value={parallelRollout?.backend ?? '—'} />
          <Metric label="Env count" value={`${parallelRollout?.envs_instantiated ?? 0} / ${parallelRollout?.envs_requested ?? 0}`} />
          <Metric label="Workers" value={parallelRollout?.worker_count ?? 0} />
          <Metric label="Rollout steps" value={parallelRollout?.rollout_n_steps ?? 0} />
          <Metric label="Symbols / TFs" value={`${parallelRollout?.unique_symbols ?? 0} / ${parallelRollout?.unique_timeframes ?? 0}`} />
          <Metric label="Full loaded batch" value={String(parallelRollout?.covers_all_loaded_examples ?? false)} />
        </div>
        <p className="cockpit-evidence-note">
          This panel is sourced from the current CUDA trainer live-gate source; old burn-in reports are historical diagnostics only.
        </p>
      </Panel>

      <Panel
        id="trainer-live-switch"
        title="Live Control"
        right={<button type="button" className="chip solid-block" disabled>Live disabled</button>}
      >
        <div className="cockpit-lineage-grid">
          <div><span>Visible</span><strong>{liveSwitch?.visible ? 'YES' : '—'}</strong></div>
          <div><span>Enabled</span><strong className="status-block">{liveSwitch?.enabled ? 'YES' : 'NO'}</strong></div>
          <div><span>Backend callable</span><strong className="status-block">{liveSwitch?.backend_live_enable_callable ? 'YES' : 'NO'}</strong></div>
          <div><span>live_symbols</span><strong>{trainerLiveSymbols.length ? trainerLiveSymbols.join(', ') : 'none'}</strong></div>
        </div>
        <p className="cockpit-evidence-note">{liveSwitch?.disabled_reason ?? `Current runtime live state: ${runtimeLabel(trainerLiveGate)} · ${runtimeLabel(payload?.live_order_submit_blocker)}.`}</p>
      </Panel>

      <Panel id="trainer-runtime-burn-in-gate" title="Current Native Runtime Gate" right={<span className="chip solid-paper">CURRENT RUNTIME</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Trainer source" value={runtimeSourceLabel(payload?.trainer_source ?? trainer?.trainer_source, 'native trainer runtime source pending')} />
          <Metric label="Model source" value={runtimeSourceLabel(payload?.model_source ?? trainer?.model_source, 'model source pending')} />
          <Metric label="Grid rows" value={`${payload?.prediction_grid_rows ?? 0}/${payload?.prediction_grid_expected_rows ?? 0}`} />
          <Metric label="Current rows" value={`${payload?.current_prediction_count ?? 0}/${payload?.prediction_grid_expected_rows ?? 0}`} detail={payload?.prediction_grid_current ? 'full current grid' : runtimeLabel(payload?.prediction_coverage_status)} />
          <Metric label="Missing / stale" value={`${payload?.missing_prediction_rows_count ?? 0} / ${payload?.stale_prediction_rows_count ?? 0}`} detail={`${payload?.non_current_prediction_rows_count ?? 0} non-current`} />
          <Metric label="Execution actionability" value={`${payload?.paper_actionability_allowed_rows_count ?? 0}/${payload?.paper_actionability_blocked_rows_count ?? 0}`} detail={runtimeLabel(payload?.prediction_actionability_status)} />
          <Metric label="Actionability blockers" value={reasonCountsLabel(payload?.paper_actionability_block_reason_counts, 2)} detail={reasonCountsLabel(payload?.paper_actionability_block_reason_counts, 4)} />
          <Metric label="Symbols / TFs" value={`${payload?.valid_symbol_count ?? 0} / ${(payload?.timeframes ?? []).length}`} />
          <Metric label="Blocked rows" value={payload?.blocked_prediction_rows ?? 0} />
          <Metric label="Sidecar rows" value={payload?.rl_core_sidecar_rows ?? 0} />
          <Metric label="Account equity" value={numberMetric(paperAccount.equity, 2)} />
          <Metric label="Runtime PnL" value={numberMetric(paperAccount.totalPnl, 2)} />
          <Metric label="Runtime trial guard" value={runtimeLabel(payload?.paper_confidence_trial_guard_status)} detail={runtimeLabel(payload?.paper_confidence_trial_guard_reason)} />
        </div>
        <p className="cockpit-evidence-note">
          Source: {gatePayload ? 'CUDA trainer live-gate source' : 'native trainer runtime source'}. Current runtime panels fail semantic validation if they use stale burn-in sources as live state.
        </p>
        {(payload?.missing_prediction_symbols?.length ?? 0) > 0 ? (
          <p className="cockpit-evidence-gap">
            Missing current prediction symbols: {payload?.missing_prediction_symbols?.join(', ')}
          </p>
        ) : null}
      </Panel>

      <Panel id="trainer-edge-recompute" title="Execution Threshold Trial And Current Actionability">
        <div className="cockpit-analytics-grid">
          <Metric label="Prediction rows" value={actionabilityPayload?.summary?.prediction_rows ?? payload?.prediction_grid_rows ?? 0} />
          <Metric label="Execution allowed before" value={actionabilityPayload?.summary?.paper_allowed_before ?? 'current runtime pending'} />
          <Metric label="Trial candidates" value={actionabilityPayload?.summary?.trial_candidate_count ?? 'current runtime pending'} />
          <Metric label="Promoted execution signals" value={actionabilityPayload?.summary?.trial_promoted_signal_count ?? 'current runtime pending'} />
          <Metric label="Execution threshold" value={actionabilityPayload?.summary?.paper_confidence_threshold ?? 'current runtime pending'} />
          <Metric label="Runtime PnL at trial" value={numberMetric(actionabilityPayload?.paper?.current_session_pnl, 2)} />
          <Metric label="Drawdown guard" value={runtimeLabel(payload?.paper_confidence_trial_guard_status)} detail={runtimeLabel(payload?.paper_confidence_trial_guard_reason)} />
          <Metric label="Live threshold changed" value={String(actionabilityPayload?.live?.live_threshold_changed ?? false)} />
          <Metric label="Live blocker" value={runtimeLabel(actionabilityPayload?.live?.live_order_submit_blocker ?? payload?.live_order_submit_blocker)} />
        </div>
        <p className="cockpit-evidence-note">
          Current actionability is running under operator-governed execution. Live thresholds and live submit remain unchanged.
        </p>
      </Panel>

      <Panel id="trainer-false-negative-actionability" title="False Negative Actionability" right={<span className="chip solid-paper">RUNTIME SHADOW</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Actionability gate" value={actionabilityPayload?.go_no_go ?? 'Current actionability source pending'} />
          <Metric label="Source age" value={fmtAge(actionabilityAge)} />
          <Metric label="False negatives" value={falseNegativeAttribution?.false_negative_count ?? 0} />
          <Metric label="Lineage complete" value={String(falseNegativeAttribution?.lineage_complete ?? false)} />
          <Metric label="Root causes" value={cudaCountMapText(falseNegativeAttribution?.root_cause_counts)} />
          <Metric label="Scenario runs" value={actionabilitySimulation?.simulations?.length ?? 0} />
          <Metric label="Recommended scenario" value={actionabilitySimulation?.recommended_simulation_id ?? '—'} />
          <Metric label="Scenario recovered" value={recommendedSimulation?.recovered_false_negatives ?? 0} />
          <Metric label="Scenario FP estimate" value={recommendedSimulation?.introduced_false_positives_estimate ?? 0} />
          <Metric label="Overlay candidates" value={actionabilityOverlay?.overlay_candidate_count ?? 0} />
          <Metric label="Overlay recovered" value={actionabilityEdge?.simulated_overlay?.recovered_false_negatives ?? 0} />
          <Metric label="Candidate expectancy" value={cudaBpsText(actionabilityEdge?.simulated_overlay?.candidate_after_cost_expectancy_bps)} />
          <Metric label="Candidate CI lower" value={cudaBpsText(actionabilityEdge?.simulated_overlay?.candidate_after_cost_ci_lower_bps)} />
          <Metric label="Risk bypass" value={String(actionabilityOverlay?.risk_bypass ?? false)} />
          <Metric label="Thresholds auto accepted" value={String(actionabilitySimulation?.thresholds_auto_accepted ?? false)} />
          <Metric label="Primary blocker" value={runtimeLabel(actionabilityEdge?.primary_recommendation ?? 'BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN')} />
        </div>
        <div className="cockpit-card-grid">
          {(actionabilityBlockers.length ? actionabilityBlockers : ['BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN']).map((blocker) => (
            <div className="cockpit-evidence-gap" key={`actionability-${blocker}`}>{runtimeLabel(blocker)}</div>
          ))}
        </div>
        {(falseNegativeAttribution?.rows?.length ?? 0) > 0 ? (
          <div className="signal-stream-table" role="table" style={{ marginTop: '1rem' }}>
            <div className="signal-stream-row signal-stream-row--head" role="row">
              <span>Symbol</span><span>TF</span><span>Missed</span><span>Root cause</span><span>Risk</span><span>Orch</span><span>Realized</span>
            </div>
            {falseNegativeAttribution!.rows!.slice(0, 8).map((row) => (
              <div className="signal-stream-row" role="row" key={row.prediction_id}>
                <span><strong>{row.symbol ?? '—'}</strong></span>
                <span>{row.timeframe ?? '—'}</span>
                <span>{row.missed_direction ?? '—'}</span>
                <span>{row.primary_root_cause ?? '—'}</span>
                <span>{row.risk_decision?.risk_reason ?? row.block_reason ?? '—'}</span>
                <span>{row.orchestrator_decision?.orchestrator_reason ?? '—'}</span>
                <span>{cudaBpsText(row.realized_after_cost_bps)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="cockpit-evidence-gap">CUDA actionability source is missing false-negative attribution rows.</p>
        )}
        <p className="cockpit-evidence-note">
          Source: CUDA actionability monitor. Simulations and overlays are diagnostics only; runtime execution remains governed by the live-gate and balance-hold sources.
        </p>
      </Panel>

      <Panel id="trainer-predictions" title="Predictions">
        <p className="cockpit-evidence-note">
          Showing {visiblePredictions.length.toLocaleString('en-US')} of {predictions.length.toLocaleString('en-US')} trainer prediction rows in this scroll window, across every symbol and timeframe currently published by the trainer.
        </p>
        <div className="trainer-prediction-scroll-window" role="region" aria-label="Scrollable trainer predictions">
          <div className="signal-stream-table" role="table">
            <div className="signal-stream-row signal-stream-row--head" role="row">
              <span>Symbol</span>
              <span>TF</span>
              <span>Action</span>
              <span>Edge after cost</span>
              <span>Confidence</span>
              <span>Coverage</span>
              <span>Missing / Stale</span>
              <span>Signal Health</span>
            </div>
            {visiblePredictions.map((row) => (
              <div className="signal-stream-row" role="row" key={`${row.symbol ?? 'unknown'}-${row.timeframe ?? 'unknown'}-${row.prediction_id ?? 'no-id'}`}>
                <span><strong>{row.symbol ?? '—'}</strong></span>
                <span>{row.timeframe ?? '—'}</span>
                <span>{row.selected_action ?? '—'}</span>
                <span>{bps(row.expected_move_after_cost_bps)}</span>
                <span>{typeof row.confidence_calibrated === 'number' && Number.isFinite(row.confidence_calibrated) ? row.confidence_calibrated.toFixed(3) : '—'}</span>
                <span>{pct(row.data_coverage_percent)}</span>
                <span>{row.missing_feature_count ?? 0} / {row.stale_feature_count ?? 0}</span>
                <span>{runtimeLabel(row.paper_fill_gate_status) === 'current runtime pending' ? 'in review' : runtimeLabel(row.paper_fill_gate_status)}</span>
              </div>
            ))}
          </div>
        </div>
      </Panel>

      <Panel id="trainer-lineage" title="Trainer -> Risk -> Orchestrator -> Execution">
        {lineage.length > 0 ? (
          <>
            <p className="cockpit-evidence-note" style={{ marginTop: 0 }}>
              Showing {visibleLineage.length.toLocaleString('en-US')} of {lineage.length.toLocaleString('en-US')} decision-chain rows.
            </p>
            <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--compact" role="region" aria-label="Scrollable trainer lineage rows">
              {visibleLineage.map((row, index) => {
                const symbol = row.trainer_prediction_record?.symbol ?? '—';
                const riskDecision = row.risk_decision_record?.risk_action ?? 'pending';
                const riskReason = row.risk_decision_record?.risk_reason_code ?? 'risk reason pending';
                const orchAction = row.orchestrator_decision_record?.decision_action ?? 'pending';
                const paperAction = row.paper_execution_ledger_entry?.ledger_action ?? 'pending';
                const paperReason = row.paper_execution_ledger_entry?.ledger_reason_code ?? 'execution reason pending';
                return (
                  <details className="cockpit-decision-drawer" key={`${symbol}-${index}`}>
                    <summary>
                      <span>Symbol</span>
                      <span>{symbol}</span>
                      <span>Readiness: {row.trainer_prediction_record?.prediction_id ? 'published' : 'pending'}</span>
                    </summary>
                    <div className="cockpit-lineage-grid">
                      <div><span>Risk check</span><strong>{riskDecision}</strong></div>
                      <div><span>Risk outcome</span><strong>{riskReason}</strong></div>
                      <div><span>Orchestrator</span><strong>{orchAction}</strong></div>
                      <div><span>Execution order gate</span><strong>{runtimeLabel(paperAction)}</strong></div>
                      <div><span>Execution reason</span><strong>{runtimeLabel(paperReason)}</strong></div>
                    </div>
                  </details>
                );
              })}
            </div>
            {lineage.length > AI_BRAIN_LINEAGE_PREVIEW ? (
              <button
                className="lineage-raw-toggle"
                onClick={() => setShowAllLineageRows((value) => !value)}
                style={{ marginTop: 8 }}
                type="button"
              >
                {showAllLineageRows ? 'Show fewer lineage rows' : `Show all ${lineage.length} lineage rows`}
              </button>
            ) : null}
          </>
        ) : (
          <p className="cockpit-evidence-gap">Trainer lineage rows are not yet published in the current source.</p>
        )}
      </Panel>
        </>
      ) : (
        <Panel id="model-state-detail-hydration" title="Trainer Detail Panels">
          <p className="cockpit-evidence-note">
            Loading detailed prediction, lineage, and actionability grids after the top trainer truth panels render.
          </p>
        </Panel>
      )}
    </article>
  );
}
