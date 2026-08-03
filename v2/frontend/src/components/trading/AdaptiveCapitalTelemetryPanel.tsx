import { Link } from 'react-router-dom';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import {
  adaptiveStatusColor,
  formatAdaptiveBps,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  pnlWindow,
  type AdaptiveCapitalAGradeReadiness,
  type AdaptiveCapitalAGradeSourceReadiness,
  type AdaptiveCapitalCounterfactualStatus,
  type AdaptiveCapitalPolicyStatus,
  type AdaptiveCapitalOperatorGoReadiness,
  type AdaptiveCapitalPassConditionStatus,
  type AdaptiveCapitalDashboardPayload,
  type CapitalProductivityRuntimeStatus,
  type ContinuousEdgeGuardianStatus,
  type PnlHistoryStatus,
  type PnlHistoryWindow,
  type SignalPredictionAccuracyCell,
  type SignalPredictionAccuracyStatus,
  type SignalPredictionSymbolSummary,
  type SignalPredictionTimeframeSummary,
} from '../../data/adaptiveCapitalProductivity';

const TIMEFRAME_ORDER = ['1m', '5m', '15m', '1h', '4h'];

interface TelemetryViewModel {
  generatedUtc: string | null;
  overallStatus: string | null;
  capital: CapitalProductivityRuntimeStatus | null;
  counterfactual: AdaptiveCapitalCounterfactualStatus | null;
  policy: AdaptiveCapitalPolicyStatus | null;
  aGradeReadiness: AdaptiveCapitalAGradeReadiness | null;
  readiness: AdaptiveCapitalOperatorGoReadiness | null;
  passConditions: AdaptiveCapitalPassConditionStatus | null;
  guardian: ContinuousEdgeGuardianStatus | null;
  pnlHistory: PnlHistoryStatus | null;
  accuracy: SignalPredictionAccuracyStatus | null;
  windows: Array<{ label: '1D' | '1W' | '30D'; row: PnlHistoryWindow | null }>;
  timeframeRows: SignalPredictionTimeframeSummary[];
  symbolRows: SignalPredictionSymbolSummary[];
  matrixRows: SignalPredictionAccuracyCell[];
}

interface AdaptiveCapitalTelemetryPanelProps {
  payload: AdaptiveCapitalDashboardPayload | null | undefined;
  title?: string;
  compact?: boolean;
  showCapital?: boolean;
  showMatrix?: boolean;
  maxMatrixHeight?: number;
}

interface PaperRuntimeBlocker {
  id?: string | null;
  severity?: string | null;
  detail?: string | null;
  status?: string | null;
  trajectory_status?: string | null;
  blocker?: string | null;
  valid_forward_canary_economic_outcomes?: number | null;
  post_cutover_valid_forward_canary_economic_outcomes?: number | null;
  required_forward_canary_economic_outcomes?: number | null;
  valid_symbol_count?: number | null;
  required_symbol_count?: number | null;
  required_initial_symbols?: number | null;
  forward_canary_shortfalls?: Record<string, number> | null;
  A_grade_rows?: number | null;
  a_grade_rows?: number | null;
  near_A_grade_rows?: number | null;
  near_a_grade_rows?: number | null;
  closest_gap_reason?: string | null;
  predicate_counts?: Record<string, number> | null;
  root_cause_counts?: Record<string, number> | null;
  dominant_current_runtime_reasons?: Record<string, number> | null;
  guardian_status?: string | null;
  guardian_new_entries_allowed?: boolean | null;
  guardian_block_all_new_a_grade_entries?: boolean | null;
  guardian_failure_reason_count?: number | null;
  source_tier_a_grade_execution_rows?: number | null;
  pass_conditions?: Record<string, boolean> | null;
  target_multiple?: number | null;
  target_horizon_days?: number | null;
  required_daily_return_pct?: number | null;
  required_daily_geometric_return?: number | null;
  required_monthly_geometric_return?: number | null;
  actual_1d_return?: number | null;
  actual_7d_return?: number | null;
  actual_30d_return?: number | null;
  drawdown_adjusted_growth_rate?: number | null;
  lower_confidence_bound_growth_rate?: number | null;
  days_ahead_or_behind_target?: number | null;
  projection_days?: number | null;
  A_plus_rows?: number | null;
  B_grade_rows?: number | null;
  current_A_plus_daily_return_pct?: number | null;
  current_B_grade_daily_return_pct?: number | null;
  current_actual_daily_return_pct?: number | null;
  required_operator_text?: string[] | null;
  required_edge?: number | null;
  required_capital?: number | null;
  missing_trajectory_evidence_fields?: string[] | null;
  guaranteed_profit_claim?: boolean | null;
  leverage_increase_allowed_because_behind?: boolean | null;
}

interface PaperTrainerModelQualityStatus {
  status?: string | null;
  weights_update?: boolean | null;
  quality_metrics_current?: boolean | null;
  trusted_rows_loaded?: number | null;
  optimizer_steps_last_hour?: number | null;
  parameter_hash_changed?: boolean | null;
  checkpoint_written?: boolean | null;
  checkpoint_reload_verified?: boolean | null;
  directional_accuracy?: number | null;
  directional_baseline?: number | null;
  after_cost_expectancy_bps?: number | null;
  a_grade_promotion_allowed?: boolean | null;
  routes_to_live?: boolean | null;
  places_real_order?: boolean | null;
}

interface OneThousandXTrajectoryStatus {
  status?: string | null;
  current_status?: string | null;
  trajectory_status?: string | null;
  blocker?: string | null;
  trajectory_status_detail?: string | null;
  calibration_status?: string | null;
  target_multiple?: number | null;
  target_horizon_days?: number | null;
  required_daily_return_pct?: number | null;
  required_daily_geometric_return?: number | null;
  required_monthly_geometric_return?: number | null;
  actual_1d_return?: number | null;
  actual_7d_return?: number | null;
  actual_30d_return?: number | null;
  drawdown_adjusted_growth_rate?: number | null;
  lower_confidence_bound_growth_rate?: number | null;
  days_ahead_or_behind_target?: number | null;
  projection_days?: number | null;
  A_plus_rows?: number | null;
  B_grade_rows?: number | null;
  current_A_plus_daily_return_pct?: number | null;
  current_B_grade_daily_return_pct?: number | null;
  current_actual_daily_return_pct?: number | null;
  B_grade_counts_as_1000x_proof?: boolean | null;
  required_operator_text?: string[] | null;
  required_edge?: number | null;
  required_capital?: number | null;
  missing_trajectory_evidence_fields?: string[] | null;
  guaranteed_profit_claim?: boolean | null;
  leverage_increase_allowed_because_behind?: boolean | null;
}

interface PaperRuntimeStatusPayload {
  runtime?: string | null;
  runtime_state?: string | null;
  live_gate_status?: string | null;
  performance?: {
    governor_state?: string | null;
    state?: string | null;
    status?: string | null;
    new_entries_allowed?: boolean | null;
  } | null;
  blockers?: PaperRuntimeBlocker[] | null;
  paper_loop?: {
    candidate_id?: string | null;
    policy_id?: string | null;
    paper_policy_owner?: string | null;
    current_allowed_paper_owner?: string | null;
    policy_fingerprint?: string | null;
    model_source?: string | null;
    intents_built?: number | null;
    intents_accepted?: number | null;
    intents_blocked?: number | null;
    order_cost_applicable_rows?: number | null;
    production_grade_cost_rows?: number | null;
    production_grade_cost_order_applicable_rows?: number | null;
    production_grade_cost_coverage?: number | null;
    production_grade_cost_coverage_basis?: string | null;
    no_order_explained_rows?: number | null;
    unexplained_missing_cost_rows?: number | null;
    paper_fill_allowed_rows?: number | null;
    routes_to_live_rows?: number | null;
    places_real_order_rows?: number | null;
    paper_churn_equity_bleed_governor_status?: {
      status?: string | null;
      state?: string | null;
      duplicate_new_entries?: number | null;
      same_candle_reentry_unexplained?: number | null;
      cost_drag_within_envelope?: boolean | null;
      economic_trade_count_reconciles?: boolean | null;
      compacted_economic_trades?: number | null;
      raw_close_records?: number | null;
      cost_drag_pct?: number | null;
      sample_compacted_economic_trades_count?: number | null;
      pass_conditions?: Record<string, boolean>;
    } | null;
    paper_forward_canary_evidence_status?: {
      status?: string | null;
      valid_forward_canary_economic_outcomes?: number | null;
      required_forward_canary_economic_outcomes?: number | null;
      valid_symbol_count?: number | null;
      required_symbol_count?: number | null;
      side_counts?: Record<string, number>;
      production_grade_cost_coverage?: number | null;
      forward_canary_shortfalls?: {
        valid_forward_canary_economic_outcomes?: number | null;
        valid_symbol_count?: number | null;
        long_outcomes?: number | null;
        short_outcomes?: number | null;
        production_grade_cost_coverage_bps?: number | null;
        accounting_mismatch_rows?: number | null;
        liquidation_rows?: number | null;
        point_in_time_invalid_rows?: number | null;
        unsafe_live_route_rows?: number | null;
      } | null;
    } | null;
    paper_a_grade_gate_burndown_status?: {
      status?: string | null;
      closest_gap_reason?: string | null;
      A_grade_rows?: number | null;
      a_grade_rows?: number | null;
      near_A_grade_rows?: number | null;
      near_a_grade_rows?: number | null;
      predicate_counts?: Record<string, number> | null;
      root_cause_counts?: Record<string, number> | null;
      dominant_current_runtime_reasons?: Record<string, number> | null;
      source_tier_a_grade_execution_rows?: number | null;
      guardian_status?: string | null;
      guardian_new_entries_allowed?: boolean | null;
      guardian_block_all_new_a_grade_entries?: boolean | null;
      pass_conditions?: Record<string, boolean> | null;
    } | null;
    paper_trainer_model_quality_runtime_status?: PaperTrainerModelQualityStatus | null;
    trainer_model_quality_runtime_status?: PaperTrainerModelQualityStatus | null;
    one_thousand_x_trajectory_runtime_status?: OneThousandXTrajectoryStatus | null;
  } | null;
}

function timeframeSortValue(timeframe: string): number {
  const known = TIMEFRAME_ORDER.indexOf(timeframe);
  return known >= 0 ? known : TIMEFRAME_ORDER.length + timeframe.localeCompare('zzzz');
}

function sortAccuracyCells(rows: SignalPredictionAccuracyCell[] | null | undefined): SignalPredictionAccuracyCell[] {
  return [...(rows ?? [])].sort((a, b) => {
    const symbolCompare = String(a.symbol ?? '').localeCompare(String(b.symbol ?? ''));
    if (symbolCompare !== 0) return symbolCompare;
    return timeframeSortValue(String(a.timeframe ?? '')) - timeframeSortValue(String(b.timeframe ?? ''));
  });
}

function completeAccuracyCells(
  accuracy: SignalPredictionAccuracyStatus | null | undefined,
): SignalPredictionAccuracyCell[] {
  const explicitRows = accuracy?.by_symbol_timeframe ?? [];
  const symbols = new Set<string>();
  const timeframes = new Set<string>();

  for (const symbol of accuracy?.symbol_universe ?? []) {
    if (symbol) symbols.add(String(symbol).toUpperCase());
  }
  for (const timeframe of accuracy?.required_timeframes ?? accuracy?.timeframes ?? []) {
    if (timeframe) timeframes.add(String(timeframe));
  }
  for (const row of explicitRows) {
    if (row.symbol) symbols.add(String(row.symbol).toUpperCase());
    if (row.timeframe) timeframes.add(String(row.timeframe));
  }

  if (!symbols.size || !timeframes.size) return sortAccuracyCells(explicitRows);

  const byKey = new Map<string, SignalPredictionAccuracyCell>();
  for (const row of explicitRows) {
    const symbol = String(row.symbol ?? '').toUpperCase();
    const timeframe = String(row.timeframe ?? '');
    if (!symbol || !timeframe) continue;
    byKey.set(`${symbol}:${timeframe}`, { ...row, symbol });
  }

  for (const symbol of symbols) {
    for (const timeframe of timeframes) {
      const key = `${symbol}:${timeframe}`;
      if (!byKey.has(key)) {
        byKey.set(key, {
          symbol,
          timeframe,
          signal_count: 0,
          prediction_count: 0,
          evaluated_count: 0,
          correct_count: 0,
          incorrect_count: 0,
          flat_count: 0,
          realized_pnl_usd: 0,
          accuracy: null,
          status: 'MISSING_EVALUATED_OUTCOMES',
        });
      }
    }
  }

  return sortAccuracyCells([...byKey.values()]);
}

function sortTimeframeRows(rows: SignalPredictionTimeframeSummary[] | null | undefined): SignalPredictionTimeframeSummary[] {
  return [...(rows ?? [])].sort(
    (a, b) => timeframeSortValue(String(a.timeframe ?? '')) - timeframeSortValue(String(b.timeframe ?? '')),
  );
}

function sortSymbolRows(rows: SignalPredictionSymbolSummary[] | null | undefined): SignalPredictionSymbolSummary[] {
  return [...(rows ?? [])].sort((a, b) => {
    const evaluatedDelta = (b.evaluated_count ?? 0) - (a.evaluated_count ?? 0);
    if (evaluatedDelta !== 0) return evaluatedDelta;
    return String(a.symbol ?? '').localeCompare(String(b.symbol ?? ''));
  });
}

function resolveTelemetry(payload: AdaptiveCapitalDashboardPayload | null | undefined): TelemetryViewModel {
  const rawCapital = payload?.capital_productivity_runtime_status ?? null;
  const progress = rawCapital?.capital_productivity_progress ?? payload?.operator_go_readiness?.capital_productivity_progress;
  const capital = rawCapital
    ? {
        ...rawCapital,
        capital_utilization_classification: rawCapital.capital_utilization_classification ?? progress?.capital_utilization_classification,
        allocated_margin_usd: rawCapital.allocated_margin_usd ?? progress?.allocated_margin_usd,
        gross_open_notional_usd: rawCapital.gross_open_notional_usd ?? progress?.gross_open_notional_usd,
        effective_portfolio_leverage: rawCapital.effective_portfolio_leverage ?? progress?.effective_portfolio_leverage,
        capital_utilization_pct: rawCapital.capital_utilization_pct ?? progress?.capital_utilization_pct,
        return_on_deployed_margin: rawCapital.return_on_deployed_margin ?? progress?.return_on_deployed_margin,
        after_cost_expectancy_bps: rawCapital.after_cost_expectancy_bps ?? progress?.after_cost_expectancy_bps,
        positive_edge_non_a_grade_opportunity_count: rawCapital.positive_edge_non_a_grade_opportunity_count ?? progress?.positive_edge_non_a_grade_opportunity_count,
        positive_edge_non_a_grade_diagnostics: rawCapital.positive_edge_non_a_grade_diagnostics ?? {
          near_a_grade_positive_edge_count: progress?.near_a_grade_positive_edge_count,
          min_confidence_gap_to_a_grade: progress?.closest_positive_edge_confidence_gap_to_a_grade,
        },
      }
    : null;
  const counterfactual = payload?.counterfactual_capital_sweep_status ?? null;
  const rawPolicy = payload?.adaptive_capital_policy_status ?? null;
  const policy = rawPolicy || progress
    ? {
        ...(rawPolicy ?? {}),
        post_allocator_closed_outcome_count: rawPolicy?.post_allocator_closed_outcome_count ?? progress?.current_closed_outcome_count,
        minimum_required_closed_outcomes: rawPolicy?.minimum_required_closed_outcomes ?? progress?.minimum_required_closed_outcomes,
        long_closed_outcome_count: rawPolicy?.long_closed_outcome_count ?? progress?.long_closed_outcome_count,
        short_closed_outcome_count: rawPolicy?.short_closed_outcome_count ?? progress?.short_closed_outcome_count,
        both_long_short_evidence: rawPolicy?.both_long_short_evidence ?? progress?.both_long_short_evidence,
        symbol_count: rawPolicy?.symbol_count ?? progress?.current_symbol_count,
        minimum_required_symbol_count: rawPolicy?.minimum_required_symbol_count ?? progress?.minimum_required_symbol_count,
        symbol_diversity_deficit: rawPolicy?.symbol_diversity_deficit ?? progress?.symbol_diversity_deficit,
      }
    : null;
  const readiness = payload?.operator_go_readiness ?? null;
  const passConditions = payload?.pass_condition_status
    ?? (readiness?.pass_condition_status_counts || readiness?.failed_conditions
      ? {
          status: readiness.status,
          condition_status_counts: readiness.pass_condition_status_counts,
          failed_conditions: readiness.failed_conditions,
          conditions: [],
        }
      : null);
  const pnlHistory = payload?.pnl_history_status ?? capital?.pnl_history ?? null;
  const accuracy = payload?.signal_prediction_accuracy_status ?? capital?.signal_prediction_accuracy_status ?? null;
  const guardian = payload?.continuous_edge_guardian_status ?? null;
  return {
    generatedUtc: payload?.generated_utc ?? null,
    overallStatus: payload?.overall_status ?? null,
    capital,
    counterfactual,
    policy,
    aGradeReadiness: counterfactual?.a_grade_readiness ?? null,
    readiness,
    passConditions,
    guardian,
    pnlHistory,
    accuracy,
    windows: [
      { label: '1D', row: pnlWindow(pnlHistory, '1d') },
      { label: '1W', row: pnlWindow(pnlHistory, '7d') },
      { label: '30D', row: pnlWindow(pnlHistory, '30d') },
    ],
    timeframeRows: sortTimeframeRows(accuracy?.by_timeframe),
    symbolRows: sortSymbolRows(accuracy?.by_symbol),
    matrixRows: completeAccuracyCells(accuracy),
  };
}

function pnlColor(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return 'var(--text-secondary)';
  return value > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)';
}

function countText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString('en-US');
}

function compactPercent(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const safe = Math.abs(value) < 0.0000005 ? 0 : value;
  const prefix = safe > 0 ? '+' : '';
  return `${prefix}${(safe * 100).toFixed(digits)}%`;
}

function compactMoney(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';  // lead with minus (-$1.50M), never $-1.50M
  if (abs >= 1_000_000_000) return `${sign}$${(abs / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(2)}K`;
  return formatAdaptiveMoney(value);
}

function signedDays(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const rounded = Math.round(value);
  return `${rounded > 0 ? '+' : ''}${rounded.toLocaleString('en-US')}d`;
}

function publicTelemetryText(value: string | null | undefined): string {
  const raw = (value ?? '—').trim();
  const upper = raw.toUpperCase();
  if (!raw || raw === '—') return '—';
  // Formatted numeric output ('-$11.26', '+1.23%', '-$1.50M', '-3d') must pass through
  // untouched — the [_-] cleanup below used to strip the leading minus from losses,
  // rendering '-$11.26' as '$11.26'.
  if (/^[+-]?\$?[\d,]+(?:\.\d+)?\s*[%KMBdx]?$/.test(raw)) return raw;
  if (upper.includes('INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE')) return 'Needs productivity evidence';
  if (upper.includes('DYNAMIC_A_GRADE') && upper.includes('DEPLOYMENT_VALIDATED')) return 'A-grade runtime validated';
  if (upper.includes('NO_DIRECTIONAL_ACTION_EVIDENCE')) return 'Needs directional evidence';
  if (upper.includes('NO_EVALUATED_OUTCOMES') || upper.includes('MISSING_EVALUATED_OUTCOMES')) return 'Needs evaluated outcomes';
  if (upper === 'NO_GO' || upper.startsWith('NO_GO_')) return 'Needs review';
  const cleaned = raw
    .replace(/\bproof\b/gi, 'validation')
    .replace(/\bpaper\s*only\.?\s*/gi, '')
    .replace(/\blive orders? and exchange mutation remain disabled\.?/gi, 'approval-gated execution controls')
    .replace(/\blive orders? remain disabled\.?/gi, 'approval-gated execution controls')
    .replace(/\bexchange mutation\b/gi, 'execution control')
    .replace(/\bpaper[_\s-]*signal\b/gi, 'runtime signal')
    .replace(/\bpaper\b/gi, 'runtime')
    .replace(/no[_\s-]*data/gi, 'Pending')
    .replace(/operator/gi, 'approval')
    .replace(/blocked[_\s-]*human[_\s-]*only/gi, 'approval required')
    .replace(/\bno[_\s-]*directional[_\s-]*action[_\s-]*evidence\b/gi, 'Needs directional evidence')
    .replace(/\bno[_\s-]*evaluated[_\s-]*outcomes\b/gi, 'Needs evaluated outcomes')
    .replace(/\bmissing[_\s-]*evaluated[_\s-]*outcomes\b/gi, 'Needs evaluated outcomes')
    .replace(/\bevaluated\b/gi, 'Evaluated')
    .replace(/_+/g, ' ')
    // Kebab-case words become spaces, but a minus sign attached to a number or money
    // value (-$11.26, -1.2%) is a sign, not a separator — keep it.
    .replace(/-+(?![$\d])/g, ' ')
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

function compactReasons(value: Record<string, number> | null | undefined): string {
  const entries = Object.entries(value ?? {}).filter(([key]) => key !== '__missing__');
  if (entries.length === 0) return '—';
  return entries.slice(0, 2).map(([key, count]) => `${publicTelemetryText(key)}: ${countText(count)}`).join(' · ');
}

function compactTopReasons(value: Record<string, number> | null | undefined): string {
  const entries = Object.entries(value ?? {})
    .filter(([key, count]) => key !== '__missing__' && typeof count === 'number' && Number.isFinite(count))
    .sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return '—';
  return entries.slice(0, 2).map(([key, count]) => `${publicTelemetryText(key)}: ${countText(count)}`).join(' · ');
}

function blockerById(
  blockers: PaperRuntimeBlocker[] | null | undefined,
  id: string,
): PaperRuntimeBlocker | null {
  return blockers?.find((blocker) => blocker.id === id) ?? null;
}

function sourceReadiness(
  readiness: AdaptiveCapitalAGradeReadiness | null | undefined,
  progress: AdaptiveCapitalOperatorGoReadiness['counterfactual_replay_progress'] | null | undefined,
  sourceKind: string,
): AdaptiveCapitalAGradeSourceReadiness | null {
  return progress?.a_grade_source_kind_readiness?.[sourceKind]
    ?? readiness?.source_kind_readiness?.[sourceKind]
    ?? null;
}

function closestSourceKindLabel(value: string | null | undefined): string | null {
  const raw = String(value ?? '').trim().toLowerCase();
  if (!raw) return null;
  if (raw === 'paper_signal') return 'signal';
  if (raw === 'paper_intent') return 'intent';
  if (raw === 'paper_ledger' || raw === 'paper_ledger_accepted') return 'ledger';
  if (raw === 'prediction') return 'prediction';
  if (raw.includes('replay')) return 'replay';
  return raw.replace(/[_-]+/g, ' ');
}

function rowAgeLabel(value: string | null | undefined): string | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return null;
  const ageMs = Date.now() - parsed;
  if (!Number.isFinite(ageMs) || ageMs < 0) return null;
  const ageMinutes = ageMs / 60_000;
  if (ageMinutes < 60) return `${Math.max(1, Math.round(ageMinutes))}m old`;
  const ageHours = ageMinutes / 60;
  if (ageHours < 48) return `${Math.round(ageHours)}h old`;
  return `${Math.round(ageHours / 24)}d old`;
}

function HeaderMetric({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ minWidth: 0 }}>
      <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </span>
      <span style={{
        display: 'block',
        marginTop: 2,
        fontSize: 13,
        lineHeight: 1.2,
        fontWeight: 800,
        fontFamily: 'var(--font-mono)',
        color: color ?? 'var(--text-primary)',
        whiteSpace: 'normal',
        overflowWrap: 'anywhere',
        wordBreak: 'break-word',
      }}>
        {publicTelemetryText(value)}
      </span>
    </div>
  );
}

function accuracyPercent(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, pct));
}

function accuracyVisualColor(value: number | null | undefined, status?: string): string {
  const normalizedStatus = String(status ?? '').toUpperCase();
  if (normalizedStatus.includes('MISSING') || normalizedStatus.includes('NO_GO')) return 'var(--sell,#ef4444)';
  const pct = accuracyPercent(value);
  if (pct == null) return 'var(--text-muted)';
  if (pct >= 55) return 'var(--buy,#10b981)';
  if (pct >= 45) return '#f59e0b';
  return 'var(--sell,#ef4444)';
}

function accuracyTrack(value: number | null | undefined, status?: string): JSX.Element {
  const pct = accuracyPercent(value);
  const width = pct == null ? 0 : pct;
  const color = accuracyVisualColor(value, status);
  return (
    <div style={{
      height: 5,
      width: '100%',
      overflow: 'hidden',
      borderRadius: 999,
      background: 'color-mix(in oklch, var(--bg-base,#020617) 82%, var(--border,#1f2937) 18%)',
    }}>
      <div style={{
        width: `${width}%`,
        height: '100%',
        borderRadius: 999,
        background: color,
        transition: 'width 180ms ease',
      }} />
    </div>
  );
}

function TelemetrySection({ title, meta, children }: { title: string; meta?: string; children: JSX.Element }): JSX.Element {
  return (
    <div style={{ padding: '0 0 12px' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        marginBottom: 8,
      }}>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0, fontWeight: 800 }}>
          {title}
        </span>
        {meta && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {meta}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function TelemetryEmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div style={{
      display: 'grid',
      minHeight: 72,
      placeItems: 'center',
      border: '1px dashed var(--border,#1f2937)',
      borderRadius: 8,
      background: 'color-mix(in oklch, var(--bg-elevated,#0f172a) 72%, transparent)',
      color: 'var(--text-muted)',
      fontSize: 11,
      lineHeight: 1.4,
      padding: 14,
      textAlign: 'center',
    }}>
      {message}
    </div>
  );
}

function TimeframeAccuracyCards({ rows, compact }: {
  rows: SignalPredictionTimeframeSummary[];
  compact: boolean;
}): JSX.Element {
  return (
    <TelemetrySection title="Timeframe Accuracy" meta={`${countText(rows.length)} timeframes`}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(118px, 1fr))' : 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: compact ? 8 : 10,
      }}>
        {rows.map((row) => (
          <div key={row.timeframe} style={{
            minWidth: 0,
            padding: compact ? 10 : 12,
            borderRadius: 8,
            border: '1px solid var(--border,#1f2937)',
            background: 'linear-gradient(180deg, color-mix(in oklch, var(--bg-elevated,#0f172a) 92%, transparent), var(--bg-panel,#111827))',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: compact ? 13 : 15 }}>{row.timeframe}</strong>
              <span style={{ color: accuracyVisualColor(row.accuracy, row.status), fontFamily: 'var(--font-mono)', fontSize: compact ? 12 : 14, fontWeight: 800 }}>
                {formatAdaptivePercent(row.accuracy)}
              </span>
            </div>
            <div style={{ marginTop: 8 }}>{accuracyTrack(row.accuracy, row.status)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8, marginTop: 10 }}>
              <HeaderMetric label="Cells" value={`${countText(row.evaluated_symbol_timeframe_cell_count)}/${countText(row.symbol_timeframe_cell_count)}`} />
              <HeaderMetric label="Evaluated" value={countText(row.evaluated_count)} />
              <HeaderMetric label="Signals" value={countText(row.signal_count)} />
              <HeaderMetric label="PnL" value={formatAdaptiveMoney(row.realized_pnl_usd)} color={pnlColor(row.realized_pnl_usd)} />
            </div>
          </div>
        ))}
      </div>
    </TelemetrySection>
  );
}

function SymbolAccuracyCards({ rows, compact, maxHeight }: {
  rows: SignalPredictionSymbolSummary[];
  compact: boolean;
  maxHeight: number;
}): JSX.Element {
  return (
    <TelemetrySection title="Symbol Accuracy" meta={`${countText(rows.length)} symbols`}>
      <div style={{
        maxHeight,
        overflow: 'auto',
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(142px, 1fr))' : 'repeat(auto-fit, minmax(190px, 1fr))',
        gap: compact ? 8 : 10,
        paddingRight: 2,
      }}>
        {rows.map((row) => (
          <div key={row.symbol} style={{
            minWidth: 0,
            padding: compact ? 9 : 11,
            borderRadius: 8,
            border: '1px solid var(--border,#1f2937)',
            background: 'var(--bg-elevated,#0f172a)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <strong title={row.symbol} style={{ minWidth: 0, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: compact ? 12 : 13, overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>
                {row.symbol}
              </strong>
              <span style={{ flex: '0 0 auto', color: accuracyVisualColor(row.accuracy, row.status), fontFamily: 'var(--font-mono)', fontSize: compact ? 11 : 12, fontWeight: 800 }}>
                {formatAdaptivePercent(row.accuracy)}
              </span>
            </div>
            <div style={{ marginTop: 7 }}>{accuracyTrack(row.accuracy, row.status)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6, marginTop: 9 }}>
              <HeaderMetric label="Eval" value={countText(row.evaluated_count)} />
              <HeaderMetric label="Cells" value={`${countText(row.evaluated_symbol_timeframe_cell_count)}/${countText(row.symbol_timeframe_cell_count)}`} />
              <HeaderMetric label="PnL" value={formatAdaptiveMoney(row.realized_pnl_usd)} color={pnlColor(row.realized_pnl_usd)} />
            </div>
            <div style={{ marginTop: 7, color: 'var(--text-muted)', fontSize: 10, overflowWrap: 'anywhere' }}>
              {publicTelemetryText(row.status)}
            </div>
          </div>
        ))}
      </div>
    </TelemetrySection>
  );
}

function heatBackground(value: number | null | undefined, status?: string): string {
  const color = accuracyVisualColor(value, status);
  const pct = accuracyPercent(value);
  const mix = pct == null ? 10 : Math.max(14, Math.min(46, pct * 0.55));
  return `color-mix(in oklch, ${color} ${mix}%, var(--bg-elevated,#0f172a))`;
}

function AccuracyHeatmap({ rows, compact, maxHeight }: {
  rows: SignalPredictionAccuracyCell[];
  compact: boolean;
  maxHeight: number;
}): JSX.Element {
  const timeframes = [
    ...TIMEFRAME_ORDER.filter((timeframe) => rows.some((row) => row.timeframe === timeframe)),
    ...Array.from(new Set(rows.map((row) => row.timeframe).filter(Boolean))).filter((timeframe) => !TIMEFRAME_ORDER.includes(timeframe)),
  ];
  const symbols = Array.from(new Set(rows.map((row) => row.symbol).filter(Boolean)));
  const byKey = new Map(rows.map((row) => [`${row.symbol}:${row.timeframe}`, row]));
  const gridTemplateColumns = compact
    ? `minmax(58px, 1.2fr) repeat(${timeframes.length}, minmax(38px, 1fr))`
    : `minmax(92px, 1.15fr) repeat(${timeframes.length}, minmax(62px, 1fr))`;

  return (
    <TelemetrySection title="All Symbol/TF Accuracy" meta={`${countText(rows.length)} cells`}>
      <div style={{
        maxHeight,
        overflow: 'auto',
        maxWidth: '100%',
        border: '1px solid var(--border,#1f2937)',
        borderRadius: 8,
        background: 'var(--bg-base,#020617)',
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns,
          gap: 1,
          minWidth: timeframes.length > 7 ? (compact ? 360 : 560) : '100%',
          fontSize: compact ? 10 : 11,
        }}>
          <span style={{ position: 'sticky', top: 0, zIndex: 1, padding: compact ? '7px 6px' : '8px 9px', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', textTransform: 'uppercase', fontWeight: 800 }}>
            Symbol
          </span>
          {timeframes.map((timeframe) => (
            <span key={timeframe} style={{ position: 'sticky', top: 0, zIndex: 1, padding: compact ? '7px 4px' : '8px 7px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', fontFamily: 'var(--font-mono)', fontWeight: 800 }}>
              {timeframe}
            </span>
          ))}
          {symbols.map((symbol) => (
            <div key={symbol} style={{ display: 'contents' }}>
              <strong title={symbol} style={{ minWidth: 0, padding: compact ? '7px 6px' : '8px 9px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)', overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>
                {symbol}
              </strong>
              {timeframes.map((timeframe) => {
                const row = byKey.get(`${symbol}:${timeframe}`);
                return (
                  <span
                    key={`${symbol}-${timeframe}`}
                    title={row ? `${symbol} ${timeframe} · ${formatAdaptivePercent(row.accuracy)} · ${countText(row.evaluated_count)} evaluated · ${formatAdaptiveMoney(row.realized_pnl_usd)} · ${publicTelemetryText(row.status)}` : `${symbol} ${timeframe} · connecting`}
                    style={{
                      minWidth: 0,
                      padding: compact ? '7px 3px' : '8px 6px',
                      textAlign: 'center',
                      color: row ? 'var(--text-primary)' : 'var(--text-muted)',
                      background: row ? heatBackground(row.accuracy, row.status) : 'var(--bg-elevated,#0f172a)',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 800,
                      overflowWrap: 'anywhere',
                      whiteSpace: 'normal',
                      wordBreak: 'break-word',
                    }}
                  >
                    {row ? formatAdaptivePercent(row.accuracy) : '—'}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </TelemetrySection>
  );
}

export function AdaptiveCapitalTelemetryPanel({
  payload,
  title = 'Capital Productivity',
  compact = false,
  showCapital = true,
  showMatrix = false,
  maxMatrixHeight,
}: AdaptiveCapitalTelemetryPanelProps): JSX.Element {
  const { envelope: paperRuntimeEnvelope } = useRealtimeResource<PaperRuntimeStatusPayload>({
    url: '/api/v2/paper/runtime-status',
    source: '/api/v2/paper/runtime-status',
    source_type: 'api',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'paper',
    unwrapEnvelopeData: false,
  });
  const paperRuntime = paperRuntimeEnvelope.data;
  const paperLoop = paperRuntime?.paper_loop ?? null;
  const paperRuntimeBlockers = paperRuntime?.blockers ?? [];
  const forwardCanaryBlocker = blockerById(paperRuntimeBlockers, 'FORWARD_CANARY_EVIDENCE_NOT_READY');
  const aGradeSupplyBlocker = blockerById(paperRuntimeBlockers, 'A_GRADE_SUPPLY_ZERO');
  const trajectoryBlocker = blockerById(paperRuntimeBlockers, 'ONE_THOUSAND_X_TRAJECTORY_NOT_READY');
  const paperChurn = paperLoop?.paper_churn_equity_bleed_governor_status ?? null;
  const paperForwardCanary = paperLoop?.paper_forward_canary_evidence_status ?? null;
  const paperAgrade = paperLoop?.paper_a_grade_gate_burndown_status ?? null;
  const paperTrainerQuality = paperLoop?.paper_trainer_model_quality_runtime_status
    ?? paperLoop?.trainer_model_quality_runtime_status
    ?? null;
  const paperTrajectory = paperLoop?.one_thousand_x_trajectory_runtime_status ?? null;
  const forwardOutcomes = forwardCanaryBlocker?.valid_forward_canary_economic_outcomes
    ?? paperForwardCanary?.valid_forward_canary_economic_outcomes;
  const requiredForwardOutcomes = forwardCanaryBlocker?.required_forward_canary_economic_outcomes
    ?? paperForwardCanary?.required_forward_canary_economic_outcomes;
  const forwardSymbols = forwardCanaryBlocker?.valid_symbol_count
    ?? paperForwardCanary?.valid_symbol_count;
  const requiredForwardSymbols = forwardCanaryBlocker?.required_symbol_count
    ?? forwardCanaryBlocker?.required_initial_symbols
    ?? paperForwardCanary?.required_symbol_count;
  const forwardOutcomeShortfall = forwardCanaryBlocker?.forward_canary_shortfalls?.valid_forward_canary_economic_outcomes
    ?? paperForwardCanary?.forward_canary_shortfalls?.valid_forward_canary_economic_outcomes;
  const forwardSymbolShortfall = forwardCanaryBlocker?.forward_canary_shortfalls?.valid_symbol_count
    ?? paperForwardCanary?.forward_canary_shortfalls?.valid_symbol_count;
  const forwardLongOutcomes = paperForwardCanary?.side_counts?.LONG
    ?? paperForwardCanary?.side_counts?.long
    ?? null;
  const forwardShortOutcomes = paperForwardCanary?.side_counts?.SHORT
    ?? paperForwardCanary?.side_counts?.short
    ?? null;
  const churnDuplicateNewEntries = paperChurn?.duplicate_new_entries;
  const churnSameCandleReentry = paperChurn?.same_candle_reentry_unexplained;
  const churnGovernorPassing = (paperChurn?.status ?? paperChurn?.state) === 'ACTIVE'
    && (churnDuplicateNewEntries ?? 1) === 0
    && (churnSameCandleReentry ?? 1) === 0
    && paperChurn?.cost_drag_within_envelope === true
    && paperChurn?.economic_trade_count_reconciles === true;
  const paperAgradeRows = aGradeSupplyBlocker?.A_grade_rows
    ?? aGradeSupplyBlocker?.a_grade_rows
    ?? paperAgrade?.A_grade_rows
    ?? paperAgrade?.a_grade_rows;
  const paperNearAgradeRows = aGradeSupplyBlocker?.near_A_grade_rows
    ?? aGradeSupplyBlocker?.near_a_grade_rows
    ?? paperAgrade?.near_A_grade_rows
    ?? paperAgrade?.near_a_grade_rows;
  const aGradeClosestGap = aGradeSupplyBlocker?.closest_gap_reason
    ?? paperAgrade?.closest_gap_reason
    ?? aGradeSupplyBlocker?.status
    ?? paperAgrade?.status;
  const aGradeRootCauses = aGradeSupplyBlocker?.root_cause_counts
    ?? paperAgrade?.root_cause_counts
    ?? null;
  const aGradePredicates = aGradeSupplyBlocker?.predicate_counts
    ?? paperAgrade?.predicate_counts
    ?? null;
  const aGradeDominantReasons = aGradeSupplyBlocker?.dominant_current_runtime_reasons
    ?? paperAgrade?.dominant_current_runtime_reasons
    ?? null;
  const aGradeGuardianStatus = aGradeSupplyBlocker?.guardian_status
    ?? paperAgrade?.guardian_status
    ?? null;
  const aGradeSourceTierRows = aGradeSupplyBlocker?.source_tier_a_grade_execution_rows
    ?? paperAgrade?.source_tier_a_grade_execution_rows
    ?? null;
  const trainerAccuracyBeatsBaseline = typeof paperTrainerQuality?.directional_accuracy === 'number'
    && typeof paperTrainerQuality?.directional_baseline === 'number'
    && paperTrainerQuality.directional_accuracy > paperTrainerQuality.directional_baseline;
  const trainerEdgePositive = (paperTrainerQuality?.after_cost_expectancy_bps ?? Number.NEGATIVE_INFINITY) > 0;
  const trainerQualityPassing = String(paperTrainerQuality?.status ?? '').startsWith('PASSED_')
    && paperTrainerQuality?.weights_update === true
    && paperTrainerQuality?.quality_metrics_current === true
    && paperTrainerQuality?.checkpoint_reload_verified === true
    && trainerAccuracyBeatsBaseline
    && trainerEdgePositive;
  const view = resolveTelemetry(payload);
  // Two-tier freshness: the headline account state (equity/PnL/utilization) is
  // real-time from Redis (v2:portfolio:state, ~30s); the analytics evidence
  // (counterfactual/A-grade/accuracy) is an inherently-batch ~10-min snapshot.
  const liveGeneratedUtc =
    (payload as { live_account_generated_utc?: string | null } | null | undefined)?.live_account_generated_utc
    ?? view.generatedUtc;
  const analyticsGeneratedUtc =
    (payload as { analytics_generated_utc?: string | null } | null | undefined)?.analytics_generated_utc
    ?? null;
  const liveAgeSec = liveGeneratedUtc ? Math.max(0, (Date.now() - Date.parse(liveGeneratedUtc)) / 1000) : null;
  const analyticsAgeMin = analyticsGeneratedUtc
    ? Math.max(0, (Date.now() - Date.parse(analyticsGeneratedUtc)) / 60000)
    : null;
  const liveTone = liveAgeSec == null
    ? 'var(--text-muted)'
    : liveAgeSec <= 90
      ? 'var(--buy,#10b981)'
      : liveAgeSec <= 300
        ? '#f59e0b'
        : 'var(--sell,#ef4444)';
  const liveAgeLabel = liveAgeSec == null
    ? 'connecting'
    : liveAgeSec < 90
      ? `live · ${Math.round(liveAgeSec)}s`
      : liveAgeSec < 3600
        ? `${Math.round(liveAgeSec / 60)}m ago`
        : `${Math.round(liveAgeSec / 3600)}h ago`;
  const capital = view.capital;
  const policy = view.policy;
  const readiness = view.readiness;
  const evidenceToGo = readiness?.evidence_to_go;
  const runtimeFieldEvidence = readiness?.adaptive_field_selection_evidence;
  const selectionAttribution = readiness?.adaptive_selection_attribution_status;
  const preSubmitFieldEvidence = readiness?.pre_submit_adaptive_field_selection_evidence;
  const replayProgress = readiness?.counterfactual_replay_progress;
  const aGradeReadiness = view.aGradeReadiness;
  const paperSignalAgrade = sourceReadiness(aGradeReadiness, replayProgress, 'paper_signal');
  const predictionProbe = view.counterfactual?.prediction_counterfactual_probe
    ?? replayProgress?.prediction_counterfactual_probe
    ?? null;
  const nearAgradeProbe = view.counterfactual?.near_a_grade_counterfactual_probe
    ?? replayProgress?.near_a_grade_counterfactual_probe
    ?? null;
  const predictionReadiness = predictionProbe?.a_grade_readiness
    ?? replayProgress?.prediction_a_grade_readiness
    ?? null;
  const predictionAgrade = sourceReadiness(predictionReadiness, null, 'prediction');
  // Runtime-first: prefer the paper_signal-scoped closest row so a frozen
  // replay dataset row can never masquerade as the live "closest signal".
  const closestAgrade = aGradeReadiness?.closest_near_a_grade_by_source_kind?.paper_signal
    ?? replayProgress?.closest_near_a_grade_by_source_kind?.paper_signal
    ?? paperSignalAgrade?.closest_near_a_grade
    ?? replayProgress?.closest_near_a_grade
    ?? null;
  const closestAgradeSourceKind = closestSourceKindLabel(closestAgrade?.source_kind);
  const closestAgradeAge = rowAgeLabel(
    closestAgrade?.available_at
    ?? closestAgrade?.generated_at
    ?? closestAgrade?.decision_time,
  );
  const closestAgradeIsReplay = closestAgradeSourceKind === 'replay';
  const paperSignalSourceCount = replayProgress?.a_grade_source_kind_counts?.paper_signal
    ?? aGradeReadiness?.source_kind_counts?.paper_signal
    ?? paperSignalAgrade?.row_count;
  const predictionSourceCount = predictionProbe?.prediction_row_count
    ?? predictionReadiness?.source_kind_counts?.prediction
    ?? predictionAgrade?.row_count;
  const passConditions = view.passConditions;
  const guardian = view.guardian;
  const guardianMetrics = guardian?.realtime_a_grade_metrics;
  const guardianTruth = guardian?.readiness_truth;
  const guardianGate = guardian?.a_grade_execution_gate;
  const trajectory = guardian?.trajectory_status;
  const runtimeTrajectoryStatusRaw = trajectoryBlocker?.trajectory_status
    ?? trajectoryBlocker?.status
    ?? paperTrajectory?.trajectory_status
    ?? paperTrajectory?.current_status
    ?? paperTrajectory?.status
    ?? trajectory?.trajectory_status
    ?? trajectory?.current_status
    ?? trajectory?.status;
  const runtimeTrajectoryRequiredDailyPct = trajectoryBlocker?.required_daily_return_pct
    ?? paperTrajectory?.required_daily_return_pct
    ?? trajectory?.required_daily_return_pct;
  const runtimeTrajectoryAPlusRows = trajectoryBlocker?.A_plus_rows
    ?? paperTrajectory?.A_plus_rows
    ?? trajectory?.A_plus_rows;
  const runtimeTrajectoryBGradeRows = trajectoryBlocker?.B_grade_rows
    ?? paperTrajectory?.B_grade_rows
    ?? trajectory?.B_grade_rows;
  const paperGovernorState =
    paperRuntime?.performance?.governor_state
    ?? paperRuntime?.performance?.state
    ?? paperRuntime?.performance?.status
    ?? paperChurn?.status
    ?? paperChurn?.state
    ?? null;
  const noFinalAPlusSupply =
    (runtimeTrajectoryAPlusRows ?? 0) <= 0
    || String(runtimeTrajectoryStatusRaw ?? '').includes('NO_A_PLUS');
  const runtimeTrajectoryStatus = noFinalAPlusSupply
    ? (String(paperGovernorState ?? '').includes('HALTED') ? 'NO_A_PLUS_SUPPLY / HALTED_PERFORMANCE' : 'NO_A_PLUS_SUPPLY')
    : runtimeTrajectoryStatusRaw ?? 'NO_A_PLUS_SUPPLY';
  const runtimeTrajectoryReady = !noFinalAPlusSupply && runtimeTrajectoryStatusRaw === 'ON_TRACK_90D_A_PLUS_EVIDENCE';
  const runtimeTrajectoryOperatorText = trajectoryBlocker?.required_operator_text
    ?? paperTrajectory?.required_operator_text
    ?? trajectory?.required_operator_text
    ?? [
      'Target requires ~7.98% compounded daily.',
      `Current A+ evidence: ${countText(runtimeTrajectoryAPlusRows)}.`,
      'B-grade exploration does not count as 1000x validation.',
    ];
  const runtimeTrajectoryActual1d = trajectoryBlocker?.actual_1d_return
    ?? paperTrajectory?.actual_1d_return
    ?? trajectory?.actual_1d_return;
  const runtimeTrajectoryActual7d = trajectoryBlocker?.actual_7d_return
    ?? paperTrajectory?.actual_7d_return
    ?? trajectory?.actual_7d_return;
  const runtimeTrajectoryActual30d = trajectoryBlocker?.actual_30d_return
    ?? paperTrajectory?.actual_30d_return
    ?? trajectory?.actual_30d_return;
  const runtimeTrajectoryRequiredEdge = trajectoryBlocker?.required_edge
    ?? paperTrajectory?.required_edge
    ?? trajectory?.required_edge;
  const runtimeTrajectoryRequiredCapital = trajectoryBlocker?.required_capital
    ?? paperTrajectory?.required_capital
    ?? trajectory?.required_capital;
  const runtimeTrajectoryLcb = trajectoryBlocker?.lower_confidence_bound_growth_rate
    ?? paperTrajectory?.lower_confidence_bound_growth_rate
    ?? trajectory?.lower_confidence_bound_growth_rate;
  const runtimeTrajectoryDrawdown = trajectoryBlocker?.drawdown_adjusted_growth_rate
    ?? paperTrajectory?.drawdown_adjusted_growth_rate
    ?? trajectory?.drawdown_adjusted_growth_rate;
  const runtimeTrajectoryDays = trajectoryBlocker?.days_ahead_or_behind_target
    ?? paperTrajectory?.days_ahead_or_behind_target
    ?? trajectory?.days_ahead_or_behind_target;
  const runtimeTrajectoryProjectionDays = trajectoryBlocker?.projection_days
    ?? paperTrajectory?.projection_days
    ?? trajectory?.projection_days;
  const runtimeTrajectoryProjectionText = noFinalAPlusSupply
    ? 'NO_A_PLUS_SUPPLY / HALTED_PERFORMANCE'
    : typeof runtimeTrajectoryProjectionDays === 'number'
      ? `${Math.round(runtimeTrajectoryProjectionDays)}d projection · ${signedDays(runtimeTrajectoryDays)}`
      : 'projection n/a';
  const accuracy = view.accuracy;
  const accuracyCellTotal = accuracy?.symbol_timeframe_cell_count ?? accuracy?.required_symbol_timeframe_cell_count;
  const positiveEdgeDiagnostics = capital?.positive_edge_non_a_grade_diagnostics;
  const matrixHeight = maxMatrixHeight ?? (compact ? 180 : 280);
  const symbolHeight = compact ? 160 : 220;
  return (
    <section
      data-testid="adaptive-capital-telemetry-panel"
      style={{
        background: 'var(--bg-panel,#111827)',
        border: '1px solid var(--border,#1f2937)',
        borderRadius: 'var(--radius,8px)',
        overflow: 'hidden',
      }}
    >
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 12,
        padding: compact ? '10px 12px' : '12px 16px',
        borderBottom: '1px solid var(--border,#1f2937)',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: compact ? 12 : 13, color: 'var(--text-primary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {title}
            </h3>
            <span style={{
              padding: '2px 7px',
              borderRadius: 999,
              fontSize: 10,
              fontWeight: 800,
              fontFamily: 'var(--font-mono)',
              background: 'color-mix(in oklch, var(--bg-elevated,#0f172a) 80%, transparent)',
              color: adaptiveStatusColor(capital?.status ?? view.overallStatus),
              border: '1px solid var(--border,#1f2937)',
            }}>
              {publicTelemetryText(capital?.status ?? view.overallStatus ?? 'Pending')}
            </span>
            <span
              data-testid="capital-telemetry-freshness"
              title={liveGeneratedUtc ? `Live account state generated ${liveGeneratedUtc}` : undefined}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: '2px 7px',
                borderRadius: 999,
                fontSize: 10,
                fontWeight: 800,
                fontFamily: 'var(--font-mono)',
                color: liveTone,
                border: `1px solid ${liveTone}`,
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: liveTone }} />
              {liveAgeLabel}
            </span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
            {'Equity, PnL & utilization are real-time (v2:portfolio:state). '}
            {analyticsAgeMin != null
              ? `Accuracy & A-grade evidence recompute on a batch cycle (${Math.round(analyticsAgeMin)}m ago).`
              : 'Accuracy & A-grade evidence recompute on a batch cycle.'}
          </p>
        </div>
        <Link to="/signals" style={{ color: 'var(--accent,#3b82f6)', textDecoration: 'none', fontSize: 11, fontWeight: 700 }}>
          Signals
        </Link>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(120px, 1fr))' : 'repeat(auto-fit, minmax(135px, 1fr))',
        gap: compact ? 8 : 10,
        padding: compact ? 12 : 16,
      }}>
        {view.windows.map(({ label, row }) => (
          <HeaderMetric
            key={label}
            label={`${label} PnL`}
            value={formatAdaptiveMoney(row?.realized_pnl_usd)}
            color={pnlColor(row?.realized_pnl_usd)}
          />
        ))}
        <HeaderMetric
          label="Accuracy"
          value={formatAdaptivePercent(accuracy?.overall_accuracy)}
          color={adaptiveStatusColor(accuracy?.status)}
        />
        <HeaderMetric label="Evaluated" value={countText(accuracy?.evaluated_row_count)} />
        <HeaderMetric label="Universe" value={`${countText(accuracy?.symbol_universe_count)} symbols`} />
        <HeaderMetric label="TF Cells" value={`${countText(accuracy?.evaluated_symbol_timeframe_cell_count)}/${countText(accuracyCellTotal)}`} />
        <HeaderMetric
          label="Missing Cells"
          value={countText(missingAccuracyCellCount(accuracy))}
          color={missingAccuracyCellCount(accuracy) ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
        />
        <HeaderMetric
          label="Pass Gates"
          value={`${countText(passConditions?.condition_status_counts?.PASSED)}/${countText(passConditions?.conditions?.length)}`}
          color={adaptiveStatusColor(passConditions?.status)}
        />
        <HeaderMetric label="Failed Gates" value={countText(passConditions?.failed_conditions?.length)} color={adaptiveStatusColor(passConditions?.status)} />
        <HeaderMetric
          label="Trainer Learning"
          value={guardianTruth?.online_learning_status ?? (guardianTruth?.WEIGHTS_UPDATING ? 'WEIGHTS_UPDATING' : 'Pending')}
          color={guardianTruth?.WEIGHTS_UPDATING ? 'var(--buy,#10b981)' : '#f59e0b'}
        />
        <HeaderMetric
          label="Trainer Quality"
          value={paperTrainerQuality?.status ?? 'Pending'}
          color={trainerQualityPassing ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Trainer Edge"
          value={formatAdaptiveBps(paperTrainerQuality?.after_cost_expectancy_bps)}
          color={trainerEdgePositive ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Trainer Acc/Base"
          value={`${formatAdaptivePercent(paperTrainerQuality?.directional_accuracy)} / ${formatAdaptivePercent(paperTrainerQuality?.directional_baseline)}`}
          color={trainerAccuracyBeatsBaseline ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Trainer Reload"
          value={`${paperTrainerQuality?.checkpoint_reload_verified ? 'VERIFIED' : 'BLOCKED'} / ${countText(paperTrainerQuality?.optimizer_steps_last_hour)} steps`}
          color={paperTrainerQuality?.checkpoint_reload_verified ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Gate"
          value={guardian?.guardian_status ?? guardianGate?.status ?? 'Pending'}
          color={guardianGate?.a_grade_new_entries_allowed ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Trades"
          value={countText(guardianMetrics?.closed_economic_trade_count)}
          color={(guardianMetrics?.closed_economic_trade_count ?? 0) >= 1000 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade 100/300/1000"
          value={`${formatAdaptivePercent(guardianMetrics?.rolling_100_trade_win_rate)} / ${formatAdaptivePercent(guardianMetrics?.rolling_300_trade_win_rate)} / ${formatAdaptivePercent(guardianMetrics?.rolling_1000_trade_win_rate)}`}
          color={guardianGate?.a_grade_new_entries_allowed ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Edge"
          value={`${formatAdaptiveBps(guardianMetrics?.after_cost_expectancy_bps)} · PF ${guardianMetrics?.profit_factor ?? '—'}`}
          color={guardianGate?.a_grade_new_entries_allowed ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Liquidations"
          value={countText(guardianMetrics?.liquidation_event_count)}
          color={(guardianMetrics?.liquidation_event_count ?? 0) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="1000x Trajectory"
          value={runtimeTrajectoryStatus ?? 'NO_A_PLUS_SUPPLY'}
          color={runtimeTrajectoryReady ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="1000x Target"
          value={runtimeTrajectoryOperatorText[0] ?? 'Target requires ~7.98% compounded daily.'}
          color="var(--text-secondary)"
        />
        <HeaderMetric
          label="1000x Evidence"
          value={noFinalAPlusSupply ? 'Current final A+ evidence: 0. REDUCE_SIZE and B-grade do not count.' : runtimeTrajectoryOperatorText[1] ?? `Current A+ evidence: ${countText(runtimeTrajectoryAPlusRows)}.`}
          color={(runtimeTrajectoryAPlusRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="1000x B-grade"
          value={publicTelemetryText(runtimeTrajectoryOperatorText[2] ?? 'B-grade exploration does not count as 1000x validation.')}
          color={(runtimeTrajectoryBGradeRows ?? 0) > 0 ? 'var(--text-secondary)' : 'var(--text-muted)'}
        />
        <HeaderMetric
          label="1000x 1/7/30"
          value={`${compactPercent(runtimeTrajectoryActual1d)} / ${compactPercent(runtimeTrajectoryActual7d)} / ${compactPercent(runtimeTrajectoryActual30d)}`}
          color={runtimeTrajectoryReady ? 'var(--buy,#10b981)' : 'var(--text-secondary)'}
        />
        <HeaderMetric
          label="1000x Edge"
          value={`${compactPercent(runtimeTrajectoryRequiredEdge)} · ${compactMoney(runtimeTrajectoryRequiredCapital)} · ${typeof runtimeTrajectoryRequiredDailyPct === 'number' ? `${runtimeTrajectoryRequiredDailyPct.toFixed(2)}% daily` : '7.98% daily'}`}
          color="var(--text-secondary)"
        />
        <HeaderMetric
          label="1000x LCB/DD"
          value={`${compactPercent(runtimeTrajectoryLcb, 3)} / ${compactPercent(runtimeTrajectoryDrawdown, 3)}`}
          color={runtimeTrajectoryReady ? 'var(--buy,#10b981)' : 'var(--text-secondary)'}
        />
        <HeaderMetric
          label="1000x Projection"
          value={runtimeTrajectoryProjectionText}
          color={runtimeTrajectoryReady ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Runtime Owner"
          value={publicTelemetryText(paperLoop?.paper_policy_owner ?? 'Pending')}
          color={paperLoop?.paper_policy_owner === 'challenger_v2' ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Cost Readiness"
          value={`${formatAdaptivePercent(paperLoop?.production_grade_cost_coverage)} · ${paperLoop?.production_grade_cost_coverage_basis ?? 'basis n/a'}`}
          color={(paperLoop?.production_grade_cost_coverage ?? 0) >= 0.95 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Cost Rows"
          value={`order ${countText(paperLoop?.production_grade_cost_order_applicable_rows)}/${countText(paperLoop?.order_cost_applicable_rows)} · all ${countText(paperLoop?.production_grade_cost_rows)}/${countText(paperLoop?.intents_built)}`}
          color={(paperLoop?.production_grade_cost_coverage ?? 0) >= 0.95 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="No-Order Explained"
          value={`${countText(paperLoop?.no_order_explained_rows)} explained · ${countText(paperLoop?.unexplained_missing_cost_rows)} unexplained`}
          color={(paperLoop?.unexplained_missing_cost_rows ?? 1) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Churn Governor"
          value={paperChurn?.status ?? paperChurn?.state ?? 'Pending'}
          color={churnGovernorPassing ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Churn Dup/Reentry"
          value={`${countText(churnDuplicateNewEntries)} / ${countText(churnSameCandleReentry)}`}
          color={(churnDuplicateNewEntries ?? 1) === 0 && (churnSameCandleReentry ?? 1) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Outcomes"
          value={`${countText(forwardOutcomes)}/${countText(requiredForwardOutcomes)}`}
          color={(forwardOutcomes ?? -1) >= (requiredForwardOutcomes ?? Number.POSITIVE_INFINITY) ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Symbols"
          value={`${countText(forwardSymbols)}/${countText(requiredForwardSymbols)}`}
          color={(forwardSymbols ?? -1) >= (requiredForwardSymbols ?? Number.POSITIVE_INFINITY) ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Shortfall"
          value={`${countText(forwardOutcomeShortfall)} outcomes / ${countText(forwardSymbolShortfall)} symbols`}
          color={(forwardOutcomeShortfall ?? 1) === 0 && (forwardSymbolShortfall ?? 1) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Long/Short"
          value={`${countText(forwardLongOutcomes)} / ${countText(forwardShortOutcomes)}`}
          color={(forwardLongOutcomes ?? 0) > 0 && (forwardShortOutcomes ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Rows"
          value={`${countText(paperAgradeRows)} / near ${countText(paperNearAgradeRows)}`}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Source"
          value={aGradeClosestGap ?? 'Pending'}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Roots"
          value={compactTopReasons(aGradeRootCauses)}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Dominant"
          value={compactTopReasons(aGradeDominantReasons)}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Predicates"
          value={`risk ${countText(aGradePredicates?.risk_pass_rows)} / strategy ${countText(aGradePredicates?.strategy_pass_rows)} / allocator ${countText(aGradePredicates?.allocator_pass_rows)}`}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Guardian"
          value={`${aGradeGuardianStatus ?? 'Pending'} / tier ${countText(aGradeSourceTierRows)}`}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Execution Guard"
          value={publicTelemetryText(paperRuntime?.live_gate_status ?? 'blocked_human_only')}
          color="var(--sell,#ef4444)"
        />
      </div>

      {guardianGate?.block_all_new_a_grade_entries && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <div style={{
            border: '1px solid color-mix(in oklch, var(--sell,#ef4444) 35%, transparent)',
            background: 'color-mix(in oklch, var(--sell,#ef4444) 10%, transparent)',
            borderRadius: 6,
            padding: '8px 10px',
            fontSize: 11,
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            overflowWrap: 'anywhere',
          }}>
            {publicTelemetryText(guardian?.guardian_status ?? guardianGate.status)} · new A-grade entries route to {publicTelemetryText(guardianGate.new_candidate_tier_override ?? 'SHADOW_ONLY')} · {publicTelemetryText(guardianGate.failure_reasons?.[0]?.reason)}
          </div>
        </div>
      )}

      {showCapital && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(130px, 1fr))' : 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: 10,
          padding: compact ? '0 12px 12px' : '0 16px 16px',
        }}>
          <HeaderMetric label="Capital Class" value={capital?.capital_utilization_classification ?? '-'} color={adaptiveStatusColor(capital?.status)} />
          <HeaderMetric label="Allocated" value={formatAdaptiveMoney(capital?.allocated_margin_usd)} />
          <HeaderMetric label="Open Notional" value={formatAdaptiveMoney(capital?.gross_open_notional_usd)} />
          <HeaderMetric label="Utilization" value={formatAdaptivePercent(capital?.capital_utilization_pct)} />
          <HeaderMetric label="Deployed Return" value={formatAdaptivePercent(capital?.return_on_deployed_margin)} color={pnlColor(capital?.return_on_deployed_margin)} />
          <HeaderMetric label="After Cost Edge" value={formatAdaptiveBps(capital?.after_cost_expectancy_bps)} color={adaptiveStatusColor(capital?.status)} />
          <HeaderMetric
            label="Positive Edge Idle"
            value={countText(capital?.positive_edge_non_a_grade_opportunity_count)}
            color={(capital?.positive_edge_non_a_grade_opportunity_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="Near A-grade Edge"
            value={countText(positiveEdgeDiagnostics?.near_a_grade_positive_edge_count)}
            color={(positiveEdgeDiagnostics?.near_a_grade_positive_edge_count ?? 0) > 0 ? '#f59e0b' : 'var(--text-secondary)'}
          />
          <HeaderMetric
            label="Closest Gap"
            value={formatAdaptivePercent(positiveEdgeDiagnostics?.min_confidence_gap_to_a_grade)}
            color={(positiveEdgeDiagnostics?.min_confidence_gap_to_a_grade ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Policy Outcomes"
            value={`${countText(policy?.post_allocator_closed_outcome_count)}/${countText(policy?.minimum_required_closed_outcomes)}`}
            color={adaptiveStatusColor(policy?.status)}
          />
          <HeaderMetric
            label="Long / Short"
            value={`${countText(policy?.long_closed_outcome_count)} / ${countText(policy?.short_closed_outcome_count)}`}
            color={policy?.both_long_short_evidence ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Policy Symbols"
            value={`${countText(policy?.symbol_count)}/${countText(policy?.minimum_required_symbol_count ?? policy?.minimum_required_symbols)}`}
            color={(policy?.symbol_diversity_deficit ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
        </div>
      )}

      <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Evidence To GO
          </span>
          <span style={{ fontSize: 10, color: adaptiveStatusColor(readiness?.status ?? readiness?.overall_status), fontFamily: 'var(--font-mono)' }}>
            {publicTelemetryText(readiness?.status ?? readiness?.overall_status ?? 'Pending')}
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Closed To GO"
            value={`${countText(evidenceToGo?.closed_outcomes_needed)} / ${countText(evidenceToGo?.closed_outcomes_needed_after_current_open_positions_close)}`}
            color={(evidenceToGo?.closed_outcomes_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Symbols To GO"
            value={countText(evidenceToGo?.additional_symbols_needed)}
            color={(evidenceToGo?.additional_symbols_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="A-grade Replay To GO"
            value={countText(evidenceToGo?.a_grade_replay_evidence_needed)}
            color={(evidenceToGo?.a_grade_replay_evidence_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Best Configs To GO"
            value={countText(evidenceToGo?.counterfactual_best_configurations_needed)}
            color={(evidenceToGo?.counterfactual_best_configurations_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Attribution To GO"
            value={countText(evidenceToGo?.selection_attribution_rows_needed)}
            color={(evidenceToGo?.selection_attribution_rows_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Counterfactual Configs"
            value={`${countText(replayProgress?.configurations_considered_count)}/${countText(replayProgress?.theoretical_configuration_count)}`}
            color={replayProgress?.configuration_count_reconciled ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="A-grade Progress"
            value={formatAdaptivePercent(replayProgress?.a_grade_replay_progress_pct)}
            color={(replayProgress?.a_grade_replay_evidence_deficit ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '10px 0 6px' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            A-grade Readiness
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {countText(paperSignalSourceCount)} signals · {countText(predictionSourceCount)} predictions
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Positive Edge"
            value={countText(paperSignalAgrade?.positive_after_cost_edge_count)}
            color={(paperSignalAgrade?.positive_after_cost_edge_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Below Conf"
            value={countText(paperSignalAgrade?.positive_edge_below_confidence_count ?? paperSignalAgrade?.positive_edge_but_below_confidence_count)}
            color={(paperSignalAgrade?.positive_edge_below_confidence_count ?? paperSignalAgrade?.positive_edge_but_below_confidence_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="A-grade Rows"
            value={countText(paperSignalAgrade?.a_grade_before_temporal_count)}
            color={(paperSignalAgrade?.a_grade_before_temporal_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Event-valid"
            value={countText(paperSignalAgrade?.event_time_valid_candidate_count)}
            color={(paperSignalAgrade?.event_time_valid_candidate_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Best Configs"
            value={countText(paperSignalAgrade?.best_configuration_count)}
            color={(paperSignalAgrade?.best_configuration_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Near Event-valid"
            value={countText(nearAgradeProbe?.event_time_valid_candidate_count)}
            color={(nearAgradeProbe?.event_time_valid_candidate_count ?? 0) > 0 ? '#f59e0b' : 'var(--text-secondary)'}
          />
          <HeaderMetric
            label="Near Best Configs"
            value={countText(nearAgradeProbe?.best_configuration_count)}
            color={(nearAgradeProbe?.best_configuration_count ?? 0) > 0 ? '#f59e0b' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Near No Config"
            value={countText(nearAgradeProbe?.skipped_no_feasible_configuration_count)}
            color={(nearAgradeProbe?.skipped_no_feasible_configuration_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="Closest Gap"
            value={formatAdaptivePercent(closestAgrade?.confidence_gap_to_a_grade)}
            color={(closestAgrade?.confidence_gap_to_a_grade ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Closest Edge"
            value={formatAdaptiveBps(closestAgrade?.after_cost_edge_bps)}
          />
          <HeaderMetric
            label="Closest Signal"
            value={closestAgrade?.symbol && closestAgrade?.timeframe
              ? [
                `${closestAgrade.symbol} ${closestAgrade.timeframe}`,
                closestAgradeSourceKind,
                closestAgradeAge,
              ].filter(Boolean).join(' · ')
              : '—'}
            color={closestAgradeIsReplay ? '#f59e0b' : undefined}
          />
          <HeaderMetric
            label="A-grade Reasons"
            value={compactReasons(paperSignalAgrade?.not_a_grade_reason_counts)}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '10px 0 6px' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Prediction Readiness Probe
          </span>
          <span style={{ fontSize: 10, color: adaptiveStatusColor(predictionProbe?.status), fontFamily: 'var(--font-mono)' }}>
            {predictionProbe ? (predictionProbe.probe_participates_in_counterfactual_pass_gate ? 'GATING' : 'NON-GATING') : 'Pending'}
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Prediction Rows"
            value={countText(predictionProbe?.prediction_row_count)}
            color={adaptiveStatusColor(predictionProbe?.status)}
          />
          <HeaderMetric
            label="Pred A-grade"
            value={countText(predictionProbe?.a_grade_before_temporal_count)}
            color={(predictionProbe?.a_grade_before_temporal_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Pred Event-valid"
            value={countText(predictionProbe?.event_time_valid_candidate_count)}
            color={(predictionProbe?.event_time_valid_candidate_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Pred Best Configs"
            value={countText(predictionProbe?.best_configuration_count)}
            color={(predictionProbe?.best_configuration_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Pred No Config"
            value={countText(predictionProbe?.skipped_no_feasible_configuration_count)}
            color={(predictionProbe?.skipped_no_feasible_configuration_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="Pred Reasons"
            value={compactReasons(
              predictionAgrade?.not_a_grade_reason_counts
                ?? predictionProbe?.skipped_not_a_grade_reason_counts,
            )}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '10px 0 6px' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Pre-submit Attribution
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {countText(preSubmitFieldEvidence?.row_count)} rows
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Selection Gate"
            value={selectionAttribution?.status ?? 'Pending'}
            color={adaptiveStatusColor(selectionAttribution?.status)}
          />
          <HeaderMetric
            label="Selection Complete"
            value={`${formatAdaptivePercent(selectionAttribution?.complete_selection_model_input_coverage)} / ${countText(selectionAttribution?.complete_selection_model_input_count)} rows`}
            color={adaptiveStatusColor(selectionAttribution?.complete_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Fields"
            value={`${formatAdaptivePercent(runtimeFieldEvidence?.required_selection_field_coverage)} / ${countText(runtimeFieldEvidence?.row_count)} rows`}
            color={adaptiveStatusColor(runtimeFieldEvidence?.required_selection_field_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Leverage"
            value={formatAdaptivePercent(runtimeFieldEvidence?.leverage_selection_model_input_coverage)}
            color={adaptiveStatusColor(runtimeFieldEvidence?.leverage_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Margin"
            value={formatAdaptivePercent(runtimeFieldEvidence?.margin_mode_selection_model_input_coverage)}
            color={adaptiveStatusColor(runtimeFieldEvidence?.margin_mode_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Hedge"
            value={formatAdaptivePercent(runtimeFieldEvidence?.hedge_budget_selection_model_input_coverage)}
            color={adaptiveStatusColor(runtimeFieldEvidence?.hedge_budget_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Pre-submit Fields"
            value={formatAdaptivePercent(preSubmitFieldEvidence?.required_selection_field_coverage)}
            color={adaptiveStatusColor(preSubmitFieldEvidence?.required_selection_field_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Pre-submit Margin"
            value={formatAdaptivePercent(preSubmitFieldEvidence?.margin_mode_selection_model_input_coverage)}
            color={adaptiveStatusColor(preSubmitFieldEvidence?.margin_mode_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Pre-submit Hedge"
            value={formatAdaptivePercent(preSubmitFieldEvidence?.hedge_budget_selection_model_input_coverage)}
            color={adaptiveStatusColor(preSubmitFieldEvidence?.hedge_budget_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Margin Reasons"
            value={compactReasons(preSubmitFieldEvidence?.margin_mode_selection_reason_counts)}
          />
          <HeaderMetric
            label="Hedge Reasons"
            value={compactReasons(preSubmitFieldEvidence?.hedge_budget_selection_reason_counts)}
          />
        </div>
      </div>

      {view.timeframeRows.length > 0 && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <TimeframeAccuracyCards rows={view.timeframeRows} compact={compact} />
        </div>
      )}

      {showMatrix && view.symbolRows.length > 0 && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <SymbolAccuracyCards rows={view.symbolRows} compact={compact} maxHeight={symbolHeight} />
        </div>
      )}

      {showMatrix && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          {view.matrixRows.length > 0 ? (
            <AccuracyHeatmap rows={view.matrixRows} compact={compact} maxHeight={matrixHeight} />
          ) : (
            <TelemetrySection title="All Symbol/TF Accuracy" meta="Pending">
              <TelemetryEmptyState message="Awaiting realtime symbol/timeframe accuracy cells. Missing values remain unavailable until a sourced frame arrives." />
            </TelemetrySection>
          )}
        </div>
      )}
    </section>
  );
}

export const adaptiveCapitalTelemetryTestHooks = {
  resolveTelemetry,
  sortAccuracyCells,
  sortTimeframeRows,
};
