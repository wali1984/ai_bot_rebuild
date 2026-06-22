export const ALL_TIMEFRAME_PREDICTIONS_PATH =
  '/v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_prediction_publisher_status.json';

export const ALL_TIMEFRAME_PRICE_TARGETS_PATH =
  '/v2_all_timeframe_prediction_signal_price_target_publisher/latest/price_target_all_tf_status.json';

export const ALL_TIMEFRAME_DASHBOARD_PATH =
  '/v2_all_timeframe_prediction_signal_price_target_publisher/latest/operator_dashboard_payload.json';

export interface AllTimeframePredictionRow {
  action_probabilities?: Record<string, number> | null;
  confidence_calibrated?: number | null;
  confidence_raw?: number | null;
  data_coverage_percent?: number | null;
  expected_move_after_cost_bps?: number | null;
  expected_move_bps?: number | null;
  feature_snapshot_id?: string | null;
  freshness_seconds?: number | null;
  generated_est?: string | null;
  implementation_task?: string | null;
  last_price?: number | null;
  live_gate?: string;
  live_symbols?: string[];
  market_state_integrity_score?: number | null;
  missing_feature_count?: number | null;
  missing_stale_reason?: string | null;
  model_source?: string | null;
  paper_fill_allowed?: boolean;
  paper_fill_gate_block_reasons?: string[];
  paper_fill_gate_status?: string;
  prediction_id?: string | null;
  prediction_redis_key?: string | null;
  price_target?: number | null;
  price_target_after_cost?: number | null;
  price_target_validation_status?: string | null;
  selected_action?: string | null;
  source_lineage?: Record<string, unknown> | null;
  status?: string;
  symbol: string;
  timeframe: string;
  trainer_source?: string | null;
}

export interface AllTimeframePredictionStatus {
  blocker_count?: number;
  current_prediction_count?: number;
  execution_live_symbols?: string[];
  expected_move_missing_count?: number;
  generated_est?: string;
  implementation_tasks?: string[];
  live_gate?: string;
  live_symbols?: string[];
  missing_prediction_count?: number;
  prediction_rows?: AllTimeframePredictionRow[];
  prediction_rows_count?: number;
  required_timeframes?: string[];
  stale_prediction_count?: number;
  stale_threshold_seconds?: number;
  status?: string;
  symbols_covered?: string[];
  timeframes_covered?: string[];
}

export interface AllTimeframePriceTargetRow {
  expected_move_after_cost_bps?: number | null;
  expected_move_bps?: number | null;
  last_price?: number | null;
  prediction_id?: string | null;
  price_target?: number | null;
  price_target_after_cost?: number | null;
  selected_action?: string | null;
  source_prediction_key?: string | null;
  source_price_key?: string | null;
  symbol: string;
  timeframe: string;
  validation_status?: string;
}

export interface AllTimeframePriceTargetStatus {
  generated_est?: string;
  invalid_or_missing_count?: number;
  live_gate?: string;
  live_symbols?: string[];
  status?: string;
  target_rows?: AllTimeframePriceTargetRow[];
  target_rows_count?: number;
  valid_or_reference_count?: number;
}

export function formatCompactNumber(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Data source unavailable';
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(2)}K`;
  if (abs >= 1) return `$${value.toFixed(digits)}`;
  return `$${value.toPrecision(4)}`;
}

export function formatBps(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} bps` : 'Data source unavailable';
}

export function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'Data source unavailable';
}

export function predictionStatusTone(status: string | null | undefined): 'ok' | 'warn' | 'block' | 'neutral' {
  if (!status) return 'neutral';
  if (status.includes('PRESENT_CURRENT')) return 'ok';
  if (status.includes('STALE')) return 'warn';
  if (status.includes('MISSING')) return 'block';
  return 'neutral';
}
