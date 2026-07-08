export const PREDICTION_SIGNAL_EXPLANATIONS_PATH =
  '/operator_runtime/v2_prediction_signal_explanations/latest/prediction_signal_explanations.json';

export interface ExplanationDataFamily {
  family: string;
  status: string;
  sample_values: string;
  present_field_count: number;
  missing_fields?: string[];
  stale_fields?: string[];
  why_useful_plain_english: string;
}

export interface PredictionSignalExplanation {
  symbol: string;
  timeframe: string;
  prediction_id?: string | null;
  signal_id?: string | null;
  risk_decision_id?: string | null;
  orchestrator_decision_id?: string | null;
  selected_action?: string | null;
  confidence_calibrated?: number | null;
  confidence_raw?: number | null;
  expected_move_bps?: number | null;
  expected_move_after_cost_bps?: number | null;
  paper_intent_id?: string | null;
  paper_fill_intent_id?: string | null;
  price_target?: number | null;
  price_target_raw?: number | null;
  price_target_after_cost?: number | null;
  price_target_validation_status?: string | null;
  last_price?: number | null;
  trainer_source?: string | null;
  model_source?: string | null;
  checkpoint_id?: string | null;
  feature_snapshot_id?: string | null;
  feature_source?: string | null;
  feature_source_keys?: string[];
  prediction_source_key?: string | null;
  target_source_keys?: string[];
  runtime_source_paths?: {
    prediction_payload?: string;
    feature_sources?: string[];
    risk_decisions?: string;
    paper_ledger?: string;
    price_targets?: string;
  };
  data_coverage_percent?: number | null;
  missing_feature_count?: number | null;
  stale_feature_count?: number | null;
  missing_feature_names?: string[];
  stale_feature_names?: string[];
  optional_missing_features_masked?: boolean;
  feature_value_count?: number | null;
  feature_value_samples?: Array<{ feature: string; value: unknown }>;
  action_probabilities?: Record<string, number>;
  top_action_probabilities?: Array<{ action: string; probability: number }>;
  confidence_explanation?: {
    raw_confidence?: number | null;
    calibrated_confidence?: number | null;
    confidence_delta?: number | null;
    calibration_direction?: string | null;
    selected_action_probability?: number | null;
    action_probability_margin?: number | null;
    driver_counts?: Record<string, number>;
    drivers?: Array<{
      name: string;
      direction: 'UP' | 'DOWN' | 'NEUTRAL' | string;
      evidence_value?: unknown;
      source_key?: string | null;
      plain_english: string;
    }>;
    confidence_calculation_plain_english?: string;
  };
  market_state?: {
    market_state_id?: string | null;
    market_state_integrity_score?: number | null;
    market_state_score_components?: Record<string, number>;
    market_state_reject_reasons?: string[];
    source_lineage?: Record<string, unknown>;
    source_event_time_est?: string | null;
    source_received_time_est?: string | null;
    decision_cutoff_time_est?: string | null;
    feature_cutoff?: string | null;
    freshness_seconds?: number | null;
  };
  risk_gate?: {
    pre_trade_allowed?: boolean;
    fee_gate_allowed?: boolean;
    churn_blocked?: boolean;
    risk_action?: string | null;
    risk_result?: string | null;
    risk_reason_code?: string | null;
    risk_blockers?: string[];
  };
  orchestrator_gate?: {
    orchestrator_decision_id?: string | null;
    orchestrator_action?: string | null;
    orchestrator_reason?: string | null;
    routes_to_orchestrator?: boolean | null;
  };
  paper_gate?: {
    paper_fill_allowed?: boolean;
    paper_fill_gate_status?: string | null;
    paper_fill_gate_block_reasons?: string[];
  };
  data_families?: ExplanationDataFamily[];
  natural_language_summary?: string;
  strategy_plain_english: string;
  prediction_plain_english: string;
  risk_plain_english: string;
  paper_plain_english: string;
  truth_policy_plain_english?: string;
  why_this_data_is_useful_plain_english?: string[];
  improvement_suggestions?: string[];
}

export interface PredictionSignalExplanationsPayload {
  schema_version: string;
  generated_est: string;
  generated_utc: string;
  source: string;
  explanation_count?: number;
  unique_symbols?: number;
  unique_timeframes?: string[];
  symbols_explained?: string[];
  timeframes_explained?: string[];
  top_paper_block_reasons?: Record<string, number>;
  top_prediction_paper_gate_block_reasons?: Record<string, number>;
  summary: {
    prediction_rows?: number;
    explanation_rows?: number;
    explanation_count?: number;
    unique_symbols?: number;
    unique_timeframes?: string[];
    symbols_explained?: string[];
    timeframes_explained?: string[];
    action_counts?: Record<string, number>;
    data_family_present_counts?: Record<string, number>;
    paper_accepted_count?: number;
    paper_blocked_count?: number;
    prediction_paper_fill_allowed_count?: number;
    prediction_routes_to_orchestrator_count?: number;
    top_paper_block_reasons?: Record<string, number>;
    top_prediction_paper_gate_block_reasons?: Record<string, number>;
    live_gate?: string | null;
    trader_state?: string | null;
    live_submit_blocker?: string | null;
  };
  plain_english_overview?: string[];
  task_descriptions?: Record<string, string>;
  explanations?: PredictionSignalExplanation[];
  issues_and_next_fixes?: string[];
}

export function formatExplainerPercent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'Connecting stream';
}

export function formatExplainerBps(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value / 100).toFixed(2)}%` : 'Connecting stream';
}

export function formatExplainerPrice(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Connecting stream';
  if (Math.abs(value) >= 100) return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  return `$${value.toPrecision(6)}`;
}

export function explainerTone(status: string | null | undefined): 'ok' | 'warn' | 'block' | 'neutral' {
  const upper = String(status ?? '').toUpperCase();
  if (upper.includes('PRESENT') || upper.includes('CURRENT') || upper.includes('READY')) return 'ok';
  if (upper.includes('MISSING') || upper.includes('BLOCK')) return 'block';
  if (upper.includes('STALE') || upper.includes('PARTIAL')) return 'warn';
  return 'neutral';
}
