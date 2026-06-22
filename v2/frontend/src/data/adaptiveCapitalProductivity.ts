import { useMemo } from 'react';
import { usePayloadFile } from '../hooks/usePayloadFile';

export const ADAPTIVE_CAPITAL_DASHBOARD_PATH =
  '/operator_runtime/v2_adaptive_capital_productivity/latest/operator_dashboard_payload.json';
export const ADAPTIVE_CAPITAL_DASHBOARD_STREAM_PATH =
  '/api/v2/adaptive-capital/dashboard';
const ADAPTIVE_CAPITAL_BASE_PATH = '/operator_runtime/v2_adaptive_capital_productivity/latest';

export interface PnlHistoryWindow {
  window: '1d' | '7d' | '30d' | string;
  lookback_seconds?: number;
  realized_pnl_usd: number | null;
  closed_trade_count: number;
  winning_trade_count?: number;
  losing_trade_count?: number;
  win_rate?: number | null;
  profit_factor?: number | string | null;
  first_event_time?: string | null;
  last_event_time?: string | null;
}

export interface PnlHistoryStatus {
  status?: string;
  source?: string;
  closed_trade_count?: number;
  timestamped_closed_trade_count?: number;
  untimestamped_or_future_closed_trade_count?: number;
  timestamp_coverage?: number | null;
  windows?: PnlHistoryWindow[];
}

export interface SignalPredictionAccuracyCell {
  symbol: string;
  timeframe: string;
  signal_count?: number;
  prediction_count?: number;
  evaluated_count?: number;
  correct_count?: number;
  incorrect_count?: number;
  flat_count?: number;
  realized_pnl_usd?: number | null;
  accuracy?: number | null;
  status?: string;
}

export interface SignalPredictionTimeframeSummary {
  timeframe: string;
  symbol_timeframe_cell_count?: number;
  source_symbol_timeframe_cell_count?: number;
  evaluated_symbol_timeframe_cell_count?: number;
  signal_count?: number;
  prediction_count?: number;
  evaluated_count?: number;
  correct_count?: number;
  incorrect_count?: number;
  flat_count?: number;
  realized_pnl_usd?: number | null;
  accuracy?: number | null;
  status?: string;
}

export interface SignalPredictionSymbolSummary {
  symbol: string;
  symbol_timeframe_cell_count?: number;
  source_symbol_timeframe_cell_count?: number;
  evaluated_symbol_timeframe_cell_count?: number;
  signal_count?: number;
  prediction_count?: number;
  evaluated_count?: number;
  correct_count?: number;
  incorrect_count?: number;
  flat_count?: number;
  realized_pnl_usd?: number | null;
  accuracy?: number | null;
  status?: string;
}

export interface SignalPredictionAccuracyStatus {
  status?: string;
  source?: string;
  accuracy_definition?: string;
  required_timeframes?: string[];
  timeframes?: string[];
  timeframe_count?: number;
  symbol_universe?: string[];
  symbol_universe_count?: number;
  required_symbol_timeframe_cell_count?: number;
  symbol_timeframe_cell_count?: number;
  evaluated_symbol_timeframe_cell_count?: number;
  required_symbol_timeframe_cells_without_evaluated_outcomes_count?: number;
  missing_evaluated_symbol_timeframe_cell_count?: number;
  source_row_count?: number;
  evaluated_row_count?: number;
  unevaluated_row_count?: number;
  non_directional_row_count?: number;
  correct_count?: number;
  incorrect_count?: number;
  flat_count?: number;
  overall_accuracy?: number | null;
  evaluated_realized_pnl_usd?: number | null;
  latest_evaluated_event_time?: string | null;
  by_timeframe?: SignalPredictionTimeframeSummary[];
  by_symbol?: SignalPredictionSymbolSummary[];
  by_symbol_timeframe?: SignalPredictionAccuracyCell[];
}

export interface PositiveEdgeNonAGradeDiagnosticRow {
  symbol?: string | null;
  timeframe?: string | null;
  side?: string | null;
  confidence?: number | null;
  confidence_gap_to_a_grade?: number | null;
  after_cost_edge_bps?: number | null;
  edge_gap_to_positive_bps?: number | null;
  allocator_decision?: string | null;
  reasons?: string[];
}

export interface PositiveEdgeNonAGradeDiagnostics {
  row_count?: number;
  confidence_threshold?: number;
  near_a_grade_confidence_threshold?: number;
  near_a_grade_positive_edge_count?: number;
  reason_counts?: Record<string, number>;
  side_counts?: Record<string, number>;
  timeframe_counts?: Record<string, number>;
  max_confidence?: number | null;
  max_after_cost_edge_bps?: number | null;
  min_confidence_gap_to_a_grade?: number | null;
  closest_positive_edge_to_a_grade?: PositiveEdgeNonAGradeDiagnosticRow | null;
  top_after_cost_edge_not_a_grade?: PositiveEdgeNonAGradeDiagnosticRow | null;
  sample?: PositiveEdgeNonAGradeDiagnosticRow[];
}

export interface CapitalProductivityRuntimeStatus {
  status?: string;
  capital_utilization_classification?: string;
  capital_productivity_blocker_reasons?: string[];
  capital_productivity_progress?: {
    current_closed_outcome_count?: number;
    minimum_required_closed_outcomes?: number;
    long_closed_outcome_count?: number;
    short_closed_outcome_count?: number;
    both_long_short_evidence?: boolean;
    current_symbol_count?: number;
    minimum_required_symbol_count?: number;
    symbol_diversity_deficit?: number;
    capital_utilization_classification?: string;
    allocated_margin_usd?: number | null;
    gross_open_notional_usd?: number | null;
    effective_portfolio_leverage?: number | null;
    capital_utilization_pct?: number | null;
    return_on_deployed_margin?: number | null;
    after_cost_expectancy_bps?: number | null;
    positive_edge_non_a_grade_opportunity_count?: number;
    near_a_grade_positive_edge_count?: number;
    closest_positive_edge_confidence_gap_to_a_grade?: number | null;
  };
  paper_equity_usd?: number | null;
  available_margin_usd?: number | null;
  allocated_margin_usd?: number | null;
  gross_open_notional_usd?: number | null;
  effective_portfolio_leverage?: number | null;
  capital_utilization_pct?: number | null;
  return_on_deployed_margin?: number | null;
  capital_turnover?: number | null;
  after_cost_expectancy_bps?: number | null;
  positive_edge_non_a_grade_opportunity_count?: number;
  positive_edge_non_a_grade_diagnostics?: PositiveEdgeNonAGradeDiagnostics;
  pnl_history?: PnlHistoryStatus;
  signal_prediction_accuracy_status?: SignalPredictionAccuracyStatus;
}

export interface AdaptiveCapitalDashboardWebSurface {
  surface_id: string;
  route: string;
  shows_capital_productivity_status?: boolean;
  shows_pnl_history_windows?: boolean;
  shows_signal_prediction_accuracy?: boolean;
  shows_all_symbol_timeframe_accuracy_matrix?: boolean;
  row_level_accuracy_pnl?: boolean;
}

export interface AdaptiveCapitalDashboardWebStatus {
  status?: string;
  source?: string;
  blocker_reasons?: string[];
  required_pnl_windows?: string[];
  published_pnl_windows?: string[];
  missing_pnl_windows?: string[];
  all_required_pnl_windows_published?: boolean;
  required_accuracy_timeframes?: string[];
  published_accuracy_timeframes?: string[];
  missing_accuracy_timeframes?: string[];
  symbol_universe_count?: number;
  required_symbol_timeframe_cell_count?: number;
  published_symbol_timeframe_cell_count?: number;
  published_symbol_timeframe_matrix_row_count?: number;
  evaluated_symbol_timeframe_cell_count?: number;
  missing_evaluated_symbol_timeframe_cell_count?: number;
  all_symbol_timeframe_accuracy_cells_published?: boolean;
  all_symbol_timeframe_accuracy_cells_evaluated?: boolean;
  web_surface_count?: number;
  surfaces?: AdaptiveCapitalDashboardWebSurface[];
}

export interface AdaptiveCapitalPolicyStatus {
  status?: string;
  generated_utc?: string;
  policy_evidence_blocker_reasons?: string[];
  post_allocator_closed_outcome_count?: number;
  minimum_required_closed_outcomes?: number;
  long_closed_outcome_count?: number;
  short_closed_outcome_count?: number;
  both_long_short_evidence?: boolean;
  missing_directional_sides?: string[];
  symbol_count?: number;
  minimum_required_symbol_count?: number;
  minimum_required_symbols?: number;
  symbol_diversity_deficit?: number;
  adaptive_field_selection_evidence?: AdaptiveCapitalFieldSelectionEvidence;
  adaptive_selection_attribution_status?: AdaptiveCapitalSelectionAttributionStatus;
  pre_submit_adaptive_field_selection_evidence?: AdaptiveCapitalFieldSelectionEvidence;
}

export interface AdaptiveCapitalPassCondition {
  id: string;
  label?: string;
  status?: string;
  blocker_reasons?: string[];
  evidence?: Record<string, unknown>;
}

export interface AdaptiveCapitalPassConditionStatus {
  status?: string;
  condition_status_counts?: Record<string, number>;
  failed_conditions?: string[];
  conditions?: AdaptiveCapitalPassCondition[];
}

export interface AdaptiveCapitalEvidenceToGo {
  closed_outcomes_needed?: number;
  closed_outcomes_needed_after_current_open_positions_close?: number;
  additional_symbols_needed?: number;
  a_grade_replay_evidence_needed?: number;
  counterfactual_best_configurations_needed?: number;
  selection_attribution_rows_needed?: number;
  leverage_selection_attribution_rows_needed?: number;
  margin_mode_selection_attribution_rows_needed?: number;
  hedge_budget_selection_attribution_rows_needed?: number;
}

export interface AdaptiveCapitalFieldSelectionEvidence {
  row_count?: number;
  required_selection_field_coverage?: number | null;
  gross_notional_unique_count?: number;
  allocated_margin_unique_count?: number;
  recommended_leverage_values?: number[];
  effective_leverage_values?: number[];
  recommended_margin_modes?: string[];
  hedge_budget_unique_count?: number;
  positive_hedge_budget_count?: number;
  leverage_selection_model_input_count?: number;
  leverage_selection_model_input_coverage?: number | null;
  margin_mode_selection_model_input_coverage?: number | null;
  hedge_budget_selection_model_input_coverage?: number | null;
  margin_mode_selection_model_input_count?: number;
  hedge_budget_selection_model_input_count?: number;
  complete_selection_model_input_count?: number;
  complete_selection_model_input_coverage?: number | null;
  selection_model_input_missing_counts?: Record<string, number>;
  missing_selection_attribution_sample?: Array<Record<string, unknown>>;
  leverage_selection_reason_counts?: Record<string, number>;
  margin_mode_selection_reason_counts?: Record<string, number>;
  hedge_budget_selection_reason_counts?: Record<string, number>;
}

export interface AdaptiveCapitalSelectionAttributionStatus {
  status?: string;
  blocker_reasons?: string[];
  row_count?: number;
  required_selection_field_coverage?: number | null;
  leverage_selection_model_input_coverage?: number | null;
  margin_mode_selection_model_input_coverage?: number | null;
  hedge_budget_selection_model_input_coverage?: number | null;
  complete_selection_model_input_count?: number;
  complete_selection_model_input_coverage?: number | null;
  selection_model_input_missing_counts?: Record<string, number>;
  missing_selection_attribution_sample?: Array<Record<string, unknown>>;
  required_runtime_selection_model_input_coverage?: number | null;
  selection_scope?: string;
}

export interface AdaptiveCapitalNearAGrade {
  symbol?: string | null;
  timeframe?: string | null;
  side?: string | null;
  confidence?: number | null;
  confidence_threshold?: number | null;
  confidence_gap_to_a_grade?: number | null;
  after_cost_edge_bps?: number | null;
  minimum_after_cost_edge_bps?: number | null;
  edge_gap_to_positive_bps?: number | null;
  allocator_decision?: string | null;
  allocator_blocked?: boolean;
  reasons?: string[];
  eligibility_gap_score?: number | null;
}

export interface AdaptiveCapitalAGradeSourceReadiness {
  row_count?: number;
  directional_row_count?: number;
  confidence_present_count?: number;
  confidence_at_or_above_threshold_count?: number;
  edge_present_count?: number;
  positive_after_cost_edge_count?: number;
  positive_edge_below_confidence_count?: number;
  positive_edge_but_below_confidence_count?: number;
  a_grade_before_temporal_count?: number;
  event_time_valid_candidate_count?: number;
  best_configuration_count?: number;
  no_feasible_configuration_count?: number;
  temporal_invalid_count?: number;
  not_a_grade_reason_counts?: Record<string, number>;
  max_confidence?: number | null;
  max_after_cost_edge_bps?: number | null;
  closest_near_a_grade?: AdaptiveCapitalNearAGrade | null;
  confidence_threshold?: number | null;
  after_cost_edge_bps_min_exclusive?: number | null;
  confidence_gap_to_threshold?: number | null;
}

export interface AdaptiveCapitalAGradeReadiness {
  confidence_threshold?: number | null;
  after_cost_edge_bps_min_exclusive?: number | null;
  source_row_count?: number;
  source_kind_counts?: Record<string, number>;
  source_kind_readiness?: Record<string, AdaptiveCapitalAGradeSourceReadiness>;
  closest_near_a_grade_by_source_kind?: Record<string, AdaptiveCapitalNearAGrade>;
  a_grade_before_temporal_count?: number;
  event_time_valid_candidate_count?: number;
  best_configuration_count?: number;
  readiness_blocker_reasons?: string[];
}

export interface AdaptiveCapitalCounterfactualReplayProgress {
  a_grade_replay_evidence_deficit?: number;
  a_grade_replay_progress_pct?: number | null;
  a_grade_source_kind_counts?: Record<string, number>;
  a_grade_source_kind_readiness?: Record<string, AdaptiveCapitalAGradeSourceReadiness>;
  best_configuration_deficit_to_frontier?: number;
  closest_confidence_gap_to_a_grade?: number | null;
  closest_edge_gap_to_positive_bps?: number | null;
  closest_near_a_grade?: AdaptiveCapitalNearAGrade | null;
  closest_near_a_grade_by_source_kind?: Record<string, AdaptiveCapitalNearAGrade>;
  configuration_count_reconciled?: boolean;
  configurations_considered_count?: number;
  theoretical_configuration_count?: number;
  prediction_a_grade_readiness?: AdaptiveCapitalAGradeReadiness;
  prediction_counterfactual_probe?: AdaptiveCapitalPredictionCounterfactualProbe;
  near_a_grade_counterfactual_probe?: AdaptiveCapitalPredictionCounterfactualProbe;
}

export interface AdaptiveCapitalOperatorGoReadiness {
  generated_utc?: string;
  status?: string;
  overall_status?: string;
  pass_condition_status_counts?: Record<string, number>;
  capital_productivity_progress?: CapitalProductivityRuntimeStatus['capital_productivity_progress'];
  remaining_blockers?: string[];
  failed_conditions?: string[];
  evidence_to_go?: AdaptiveCapitalEvidenceToGo;
  adaptive_field_selection_evidence?: AdaptiveCapitalFieldSelectionEvidence;
  adaptive_selection_attribution_status?: AdaptiveCapitalSelectionAttributionStatus;
  pre_submit_adaptive_field_selection_evidence?: AdaptiveCapitalFieldSelectionEvidence;
  counterfactual_replay_progress?: AdaptiveCapitalCounterfactualReplayProgress;
}

export interface AdaptiveCapitalCounterfactualStatus {
  status?: string;
  generated_utc?: string;
  a_grade_readiness?: AdaptiveCapitalAGradeReadiness;
  counterfactual_replay_progress?: AdaptiveCapitalCounterfactualReplayProgress;
  prediction_row_count?: number;
  prediction_counterfactual_probe?: AdaptiveCapitalPredictionCounterfactualProbe;
  near_a_grade_counterfactual_probe?: AdaptiveCapitalPredictionCounterfactualProbe;
}

export interface AdaptiveCapitalPredictionCounterfactualProbe {
  status?: string;
  prediction_row_count?: number;
  probe_participates_in_counterfactual_pass_gate?: boolean;
  source_coverage_required_for_pass?: boolean;
  a_grade_before_temporal_count?: number;
  event_time_valid_candidate_count?: number;
  best_configuration_count?: number;
  skipped_not_a_grade_count?: number;
  skipped_not_a_grade_reason_counts?: Record<string, number>;
  skipped_temporal_invalid_count?: number;
  skipped_no_feasible_configuration_count?: number;
  skipped_no_feasible_configuration_reason_counts?: Record<string, number>;
  skipped_no_feasible_configuration_sample?: Array<Record<string, unknown>>;
  sweep_result_count?: number;
  efficient_frontier_ready?: boolean;
  total_expected_log_growth?: number | null;
  a_grade_readiness?: AdaptiveCapitalAGradeReadiness;
  notes?: string;
}

export interface AdaptiveCapitalDashboardPayload {
  generated_utc?: string;
  overall_status?: string;
  remaining_blockers?: string[];
  operator_go_readiness?: AdaptiveCapitalOperatorGoReadiness;
  capital_productivity_runtime_status?: CapitalProductivityRuntimeStatus;
  counterfactual_capital_sweep_status?: AdaptiveCapitalCounterfactualStatus;
  adaptive_capital_policy_status?: AdaptiveCapitalPolicyStatus;
  pass_condition_status?: AdaptiveCapitalPassConditionStatus;
  pnl_history_status?: PnlHistoryStatus;
  signal_prediction_accuracy_status?: SignalPredictionAccuracyStatus;
  dashboard_web_status?: AdaptiveCapitalDashboardWebStatus;
}

export function shouldEnableAdaptiveCapitalFallback(
  dashboardData: AdaptiveCapitalDashboardPayload | null | undefined,
  dashboardLoading: boolean,
  dashboardError: string | null | undefined,
): boolean {
  return !dashboardData && !dashboardLoading && Boolean(dashboardError);
}

export function useAdaptiveCapitalDashboard(pollMs = 2_000) {
  const streamMs = Math.min(pollMs, 2_000);
  const dashboard = usePayloadFile<AdaptiveCapitalDashboardPayload>(
    ADAPTIVE_CAPITAL_DASHBOARD_STREAM_PATH,
    streamMs,
  );
  const fallbackEnabled = shouldEnableAdaptiveCapitalFallback(
    dashboard.data,
    dashboard.loading,
    dashboard.error,
  );
  const capital = usePayloadFile<CapitalProductivityRuntimeStatus>(
    `${ADAPTIVE_CAPITAL_BASE_PATH}/capital_productivity_runtime_status.json`,
    Math.max(pollMs, 10_000),
    { enabled: fallbackEnabled },
  );
  const policy = usePayloadFile<AdaptiveCapitalPolicyStatus>(
    `${ADAPTIVE_CAPITAL_BASE_PATH}/adaptive_capital_policy_status.json`,
    Math.max(pollMs, 10_000),
    { enabled: fallbackEnabled },
  );
  const counterfactual = usePayloadFile<AdaptiveCapitalCounterfactualStatus>(
    `${ADAPTIVE_CAPITAL_BASE_PATH}/counterfactual_capital_sweep_status.json`,
    Math.max(pollMs, 10_000),
    { enabled: fallbackEnabled },
  );

  const fallbackData = useMemo<AdaptiveCapitalDashboardPayload | null>(() => {
    if (!capital.data && !policy.data && !counterfactual.data) return null;
    const generatedUtc = (capital.data as { generated_utc?: string } | null)?.generated_utc
      ?? (policy.data as { generated_utc?: string } | null)?.generated_utc
      ?? (counterfactual.data as { generated_utc?: string } | null)?.generated_utc;
    const overallStatus = policy.data?.status ?? capital.data?.status ?? counterfactual.data?.status;
    return {
      generated_utc: generatedUtc,
      overall_status: overallStatus,
      capital_productivity_runtime_status: capital.data ?? undefined,
      adaptive_capital_policy_status: policy.data ?? undefined,
      counterfactual_capital_sweep_status: counterfactual.data ?? undefined,
      pnl_history_status: capital.data?.pnl_history,
      signal_prediction_accuracy_status: capital.data?.signal_prediction_accuracy_status,
      operator_go_readiness: {
        generated_utc: generatedUtc,
        status: overallStatus,
        overall_status: overallStatus,
        adaptive_field_selection_evidence: policy.data?.adaptive_field_selection_evidence,
        adaptive_selection_attribution_status: policy.data?.adaptive_selection_attribution_status,
        pre_submit_adaptive_field_selection_evidence: policy.data?.pre_submit_adaptive_field_selection_evidence,
        counterfactual_replay_progress: counterfactual.data?.counterfactual_replay_progress,
        capital_productivity_progress: capital.data?.capital_productivity_progress,
      },
    };
  }, [capital.data, counterfactual.data, policy.data]);
  const data = useMemo(
    () => dashboard.data ?? fallbackData,
    [dashboard.data, fallbackData],
  );

  return {
    data,
    error: dashboard.error ?? capital.error ?? policy.error ?? counterfactual.error,
    ageSeconds: [dashboard.ageSeconds, capital.ageSeconds, policy.ageSeconds, counterfactual.ageSeconds]
      .filter((age): age is number => typeof age === 'number')
      .sort((a, b) => b - a)[0] ?? null,
    loading: !data && (dashboard.loading || capital.loading || policy.loading || counterfactual.loading),
  };
}

export function pnlWindow(
  history: PnlHistoryStatus | null | undefined,
  label: '1d' | '7d' | '30d' | string,
): PnlHistoryWindow | null {
  return history?.windows?.find((row) => row.window === label) ?? null;
}

export function accuracyCell(
  accuracy: SignalPredictionAccuracyStatus | null | undefined,
  symbol: string,
  timeframe: string,
): SignalPredictionAccuracyCell | null {
  const normalizedSymbol = symbol.toUpperCase();
  return accuracy?.by_symbol_timeframe?.find(
    (row) => row.symbol.toUpperCase() === normalizedSymbol && row.timeframe === timeframe,
  ) ?? null;
}

export function missingAccuracyCellCount(
  accuracy: SignalPredictionAccuracyStatus | null | undefined,
): number | undefined {
  const explicit = accuracy?.missing_evaluated_symbol_timeframe_cell_count
    ?? accuracy?.required_symbol_timeframe_cells_without_evaluated_outcomes_count;
  if (typeof explicit === 'number' && Number.isFinite(explicit)) return explicit;
  const required = accuracy?.required_symbol_timeframe_cell_count ?? accuracy?.symbol_timeframe_cell_count;
  const evaluated = accuracy?.evaluated_symbol_timeframe_cell_count;
  if (
    typeof required === 'number'
    && Number.isFinite(required)
    && typeof evaluated === 'number'
    && Number.isFinite(evaluated)
  ) {
    return Math.max(required - evaluated, 0);
  }
  return undefined;
}

export function formatAdaptiveMoney(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const safe = Math.abs(value) < 0.005 ? 0 : value;
  return `$${safe.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatAdaptivePercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

export function formatAdaptiveBps(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)} bps`;
}

export function adaptiveStatusColor(status: string | null | undefined): string {
  const upper = String(status ?? '').toUpperCase();
  if (upper === 'PASSED' || upper === 'READY') return 'var(--buy, #10b981)';
  if (upper.includes('NO_GO') || upper.includes('BLOCK') || upper.includes('MISSING')) return 'var(--sell, #ef4444)';
  return '#f59e0b';
}
