/**
 * Typed fetch hooks for the V2 realtime user/admin website.
 *
 * Every hook reads ONE real V2 public payload at a known path under
 * /. There are no fallbacks, no mock fixtures, and no static
 * "current truth" stand-ins; when a payload is absent or malformed,
 * the hook returns {payload: null, error: '...'} and the consuming
 * component MUST render a PayloadMissingCard with the path.
 */
import { useMemo } from 'react';
import { useRealtimeResource } from '../hooks/useRealtimeResource';

// ---------------------------------------------------------------------------
// Common shape: every payload we render carries the live_gate / approvals
// safety envelope. We surface those fields verbatim — never coerce to true.
// ---------------------------------------------------------------------------

export interface SafetyEnvelope {
  live_gate?: string;
  live_symbols?: unknown[];
  approves_live?: boolean;
  approves_real?: boolean;
  approves_canary?: boolean;
  approves_legacy_shutdown?: boolean;
  approves_redis_trim?: boolean;
  writes_legacy_redis?: boolean;
  writes_exchange_orders?: boolean;
}

export interface RealtimePayloadResult<T> {
  payload: T | null;
  error: string | null;
  loading: boolean;
  source_path: string;
  fetched_at: string | null;
}

function useJsonPayload<T>(path: string, pollMs = 30_000): RealtimePayloadResult<T> {
  const { envelope, loading, error } = useRealtimeResource<T>({
    url: path,
    source: path,
    pollIntervalMs: pollMs,
    staleThresholdMs: Math.max(pollMs * 3, 30_000),
    mode: 'read_only',
  });
  const fetchedAt = useMemo(() => (
    envelope.received_at ? new Date(envelope.received_at).toISOString() : null
  ), [envelope.received_at]);

  return {
    payload: envelope.data,
    error: error ?? envelope.errors[0] ?? null,
    loading,
    source_path: path,
    fetched_at: fetchedAt,
  };
}

// ---------------------------------------------------------------------------
// Payload paths (16 sources).
// ---------------------------------------------------------------------------

export const PAYLOAD_PATHS = {
  frontend_truth: '/operator_runtime/frontend_truth/latest/frontend_truth_payload.json',
  war_room_dashboard: '/v2_8h_war_room/latest/operator_dashboard_payload.json',
  war_room_codex_5m: '/v2_8h_war_room/latest/codex_5m_review_payload.json',
  top10_dashboards:
    '/v2_top10_dashboards/latest/dashboard_payload.json',
  alt_data_candidate_publisher:
    '/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json',
  alt_data_candidate_publisher_operator_runtime:
    '/operator_runtime/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json',
  live_canary_bringup_dashboard:
    '/v2_24h_live_canary_bringup/latest/operator_dashboard_payload.json',
  live_canary_executor_status:
    '/operator_runtime/v2_live_canary/latest/live_canary_executor_status.json',
  live_canary_permission_probe:
    '/operator_runtime/v2_live_canary/latest/permission_probe_status.json',
  war_room_gap_matrix: '/v2_8h_war_room/latest/model_signal_gap_matrix.json',
  war_room_actions: '/v2_8h_war_room/latest/actions_applied.json',
  war_room_codex_queue: '/v2_8h_war_room/latest/codex_review_queue.json',
  war_room_runtime_cycle: '/v2_8h_war_room/latest/runtime_cycle_status.json',
  war_room_alt_provider: '/v2_8h_war_room/latest/alt_data_provider_runtime_status.json',
  war_room_alt_universe: '/v2_8h_war_room/latest/alt_data_symbol_universe_gap_matrix.json',
  production_equivalence:
    '/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json',
  legacy_log_enriched:
    '/v2_runtime_soak_and_production_equivalence/latest/legacy_log_enriched_comparison.json',
  legacy_log_intelligence:
    '/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json',
  full_observation_builder:
    '/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json',
  liquidation_wss_client:
    '/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json',
  alt_data_symbol_universe_scoring:
    '/operator_runtime/v2_alt_data_symbol_universe_scoring/latest/alt_data_symbol_universe_scoring_status.json',
  alternative_data:
    '/operator_runtime/v2_alternative_data/latest/v2_alternative_data_status.json',
  top10_binance:
    '/operator_runtime/v2_top10_binance_dashboard_feed/latest/v2_top10_binance_dashboard_feed_status.json',
  native_cuda_trainer:
    '/operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json',
  orchestrator_arbitration_live:
    '/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json',
  trade_management_paper_live:
    '/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json',
  paper_online:
    '/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json',
  stop_line_recovery:
    '/operator_runtime/v2_stop_the_line_trainer_feedback_actionability_and_major_move_recovery/latest/operator_dashboard_payload.json',
  parallel_spark_automation: '/v2_parallel_spark_automation/latest/parallel_automation_status.json',
} as const;

// ---------------------------------------------------------------------------
// Concrete typed shapes (only the fields the website renders).
// All fields are optional because real payloads from the runtime are
// allowed to be missing; the UI must render PayloadMissingCard or the
// per-field MISSING chip rather than fabricating values.
// ---------------------------------------------------------------------------

export interface FrontendTruthPayload extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  plain_english_summary?: string;
  current_goal?: string;
  shutdown_recommendation?: string;
  paper_edge_status?: string;
  blockers_simple?: string[];
  blockers_technical?: Array<{ id?: string; category?: string; remediation_task_id?: string; source?: string; evidence?: string }>;
  stale_payloads?: string[];
  missing_payloads?: string[];
}

export interface WarRoomCycle {
  cycle_id?: string;
  started_at?: string;
  finished_at?: string;
  tier_5m_executed?: boolean;
  tier_15m_executed?: boolean;
  tier_30m_executed?: boolean;
  tier_60m_executed?: boolean;
  cycle_count?: number;
}

export interface WarRoomDashboardPayload extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  go_no_go?: string;
  cycle_mode?: string;
  cycle?: WarRoomCycle;
  state?: { cycle_count?: number; started_at?: string; no_action_streak?: number; codex_reviews_queued_total?: number };
  lane_a_runtime_health?: {
    continuous_remediation_governor?: { go_no_go?: string; fail_blockers?: string[]; v2_processes_running?: number; v2_processes_required?: number };
    full_observation_state?: string;
    full_observation_target_dim?: number;
    per_symbol_generated_dim?: Record<string, number>;
    liquidation_wss_heartbeat_ttl_seconds?: number;
  };
  lane_b_gap_matrix?: {
    symbols?: string[];
    per_symbol?: Array<{ symbol?: string; classifications?: string[] }>;
    aggregated_classification_counts?: Record<string, number>;
  };
  lane_g_narrow_fixes?: {
    no_action_required_with_evidence?: boolean;
    fixes_applied?: unknown[];
    codex_review_queue?: { pending_codex_reviews?: unknown[]; pre_existing_blockers_not_eligible_for_new_task_creation?: unknown[] };
  };
  safety_invariants?: SafetyEnvelope & { checkpoint_compatibility_claimed?: boolean; policy_architecture_parity_claimed?: boolean };
}

export interface WarRoomGapMatrix extends SafetyEnvelope {
  symbols?: string[];
  per_symbol?: Array<{
    symbol?: string;
    classifications?: string[];
    v2_prediction_present?: boolean;
    feature_freshness_state?: string;
    price_track_missing_flags?: string[];
    nansen_payload_present?: boolean;
    lunarcrush_payload_present?: boolean;
    held_by_paper_fill_gate?: boolean;
  }>;
  aggregated_classification_counts?: Record<string, number>;
}

export interface FullObservationBuilderStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  generated_at?: string;
  state?: string;
  target_full_observation_dim?: number;
  per_symbol?: Array<{
    symbol?: string;
    timeframe?: string;
    generated_full_observation_dim?: number;
    missing_dim_count?: number;
    state?: string;
    subfamily_present_counts?: Record<string, number>;
    subfamily_target_counts?: Record<string, number>;
  }>;
  subfamily_present_counts_total?: Record<string, number>;
  subfamily_target_counts_total?: Record<string, number>;
  checkpoint_compatibility_claimed?: boolean;
  policy_architecture_parity_claimed?: boolean;
}

export interface LiquidationWssClientStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  generated_at?: string;
  heartbeat_at?: string;
  go_no_go?: string;
  process_mode?: string;
  service_active?: boolean;
  opt_in_enabled?: boolean;
  url?: string;
  symbols?: string[];
  session_count?: number;
  sessions?: number;
  reconnect_count?: number;
  events_received?: number;
  events_written?: number;
  last_event_utc?: string | null;
  no_synthetic_liquidation_events?: boolean;
}

export interface Top10BinanceDashboardFeedStatus extends SafetyEnvelope {
  generated_utc?: string;
  go_no_go?: string;
  spot_source_status?: string;
  futures_source_status?: string;
  quote_filter?: string;
  top_n?: number;
  dashboards?: Record<
    string,
    {
      title?: string;
      venue?: string;
      metric?: string;
      window_size_requested?: string;
      window_size_actual?: string;
      source_endpoint?: string;
      source_status?: string;
      rank_count?: number;
      top_symbol?: string | null;
      redis_key?: string;
    }
  >;
}

export interface AltDataNansenStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  provider?: string;
  go_no_go?: string;
  tier?: string;
  paid_endpoints_enabled?: boolean;
  key_present?: boolean;
  credential_in_payload?: string;
  auth_header_name_documented_only?: string;
  api_docs_url_documented?: string;
  rate_limit_state?: { daily_budget_internal?: number; daily_budget_remaining?: number; last_response_status?: string; consecutive_failures?: number };
  symbol_count?: number;
  successful_symbol_count?: number;
  source_status_counts?: Record<string, number>;
}

export interface AltDataLunarCrushStatus extends AltDataNansenStatus {
  auth_header_scheme_documented_only?: string;
}

export interface AltDataProviderRuntimeStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  providers?: {
    nansen?: AltDataNansenStatus & { status_present?: boolean };
    lunarcrush?: AltDataLunarCrushStatus & { status_present?: boolean };
    arkham_future?: { status_present?: boolean; future_only_no_integration_today?: boolean; credential_absent_until_operator_provides_it?: boolean };
  };
  do_not_daemonize_yet?: boolean;
  paid_endpoints_enabled?: boolean;
}

export interface AltDataSymbolUniverseGapMatrix extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  per_symbol_gap?: Record<
    string,
    {
      altdata_symbol_score?: number | null;
      smart_money_score?: number | null;
      social_momentum_score?: number | null;
      social_volume_velocity?: number | null;
      provider_availability_score?: number | null;
      altdata_freshness_score?: number | null;
      providers_consulted?: string[];
      missing_reasons?: string[];
      nansen_payload_present?: boolean;
      lunarcrush_payload_present?: boolean;
    }
  >;
  candidate_payload_state?: {
    paper_symbols_expanded?: boolean;
    paper_symbol_expansion_blocked_reason?: string;
    live_symbols_continued?: unknown[];
    may_not_override_strict_paper_fill_gate?: boolean;
    may_not_authorize_live_or_canary?: boolean;
  };
}

export interface AlternativeDataStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  providers?: Record<string, unknown>;
}

export interface NativeCudaTrainerStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_est?: string;
  generated_utc?: string;
  go_no_go?: string;
  trainer?: {
    trainer_source?: string;
    model_source?: string;
    checkpoint_id?: string;
    cuda_active?: boolean;
    model_device?: string;
  };
  trainer_state?: string;
  predictions_count?: number;
  prediction_count?: number;
  predictions_with_open_gate?: unknown[];
  predictions_by_symbol?: Array<{
    prediction_id?: string;
    symbol?: string;
    timeframe?: string;
    selected_action?: string;
    paper_fill_allowed?: boolean;
  }>;
}

export interface OrchestratorArbitrationLiveStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  considered_count?: number;
  bucket_winners?: unknown[];
  held_by_paper_fill_gate?: unknown[];
  stale_proposal_ids?: unknown[];
}

export interface TradeManagementPaperLiveStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  heartbeat_generated_at?: string;
  cycle_state?: string;
  heartbeat_ttl_seconds?: number;
  candidate_id?: string;
  policy_id?: string;
  paper_policy_owner?: string;
  policy_fingerprint?: string;
  selector_policy_fingerprint?: string;
  frozen_selector_fingerprint?: string;
  model_source?: string;
  current_allowed_paper_owner?: string;
  paper_only?: boolean;
  routes_to_live?: boolean;
  places_real_order?: boolean;
  writes_legacy_redis?: boolean;
  paper_loop_state?: string;
  intents_built?: number;
  intents_accepted?: number;
  intents_blocked?: number;
  intents_held_by_paper_fill_gate?: number;
}

export interface PaperOnlineStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  runtime_state?: string;
  freshness?: { status?: string };
}

export interface ParallelSparkAutomationLaneResult {
  lane?: string;
  command?: string;
  required?: boolean;
  returncode?: number;
  duration_seconds?: number;
  lane_ready?: boolean;
  lane_blocker?: string | null;
}

export interface ParallelSparkAutomationStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  ready?: boolean;
  go_no_go?: string;
  runner?: string;
  cycle?: number;
  runner_pid?: number;
  mode?: string;
  lane_count?: number;
  blockers?: string[];
  lane_results?: ParallelSparkAutomationLaneResult[];
}

export interface LegacyLogIntelligenceStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  go_no_go?: string;
  trainer_log_evidence_present?: boolean;
  orchestrator_log_evidence_present?: boolean;
  read_only_safety?: boolean;
}

export interface ProductionEquivalenceComparison extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  matched_count?: number;
  mismatched_count?: number;
  legacy_only_count?: number;
  v2_only_count?: number;
}

export interface LegacyLogEnrichedComparison extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  enrichment_rows?: unknown[];
}

// ---------------------------------------------------------------------------
// Hook bindings — one hook per source payload.
// ---------------------------------------------------------------------------

export const useFrontendTruth = (pollMs = 30_000) =>
  useJsonPayload<FrontendTruthPayload>(PAYLOAD_PATHS.frontend_truth, pollMs);

export const useWarRoomDashboard = (pollMs = 30_000) =>
  useJsonPayload<WarRoomDashboardPayload>(PAYLOAD_PATHS.war_room_dashboard, pollMs);

export const useWarRoomGapMatrix = (pollMs = 30_000) =>
  useJsonPayload<WarRoomGapMatrix>(PAYLOAD_PATHS.war_room_gap_matrix, pollMs);

export const useWarRoomActionsApplied = (pollMs = 30_000) =>
  useJsonPayload<{ actions?: unknown[]; no_action_required_with_evidence?: boolean }>(
    PAYLOAD_PATHS.war_room_actions,
    pollMs,
  );

export const useWarRoomCodexQueue = (pollMs = 30_000) =>
  useJsonPayload<{ pending_codex_reviews?: unknown[]; pre_existing_blockers_not_eligible_for_new_task_creation?: unknown[] }>(
    PAYLOAD_PATHS.war_room_codex_queue,
    pollMs,
  );

export const useWarRoomRuntimeCycle = (pollMs = 30_000) =>
  useJsonPayload<Record<string, unknown>>(PAYLOAD_PATHS.war_room_runtime_cycle, pollMs);

export const useFullObservationBuilder = (pollMs = 60_000) =>
  useJsonPayload<FullObservationBuilderStatus>(PAYLOAD_PATHS.full_observation_builder, pollMs);

export const useLiquidationWssClient = (pollMs = 30_000) =>
  useJsonPayload<LiquidationWssClientStatus>(PAYLOAD_PATHS.liquidation_wss_client, pollMs);

export const useTop10BinanceDashboards = (pollMs = 60_000) =>
  useJsonPayload<Top10BinanceDashboardFeedStatus>(PAYLOAD_PATHS.top10_binance, pollMs);

export const useAltDataProviderRuntime = (pollMs = 60_000) =>
  useJsonPayload<AltDataProviderRuntimeStatus>(PAYLOAD_PATHS.war_room_alt_provider, pollMs);

export const useAltDataSymbolUniverseGapMatrix = (pollMs = 60_000) =>
  useJsonPayload<AltDataSymbolUniverseGapMatrix>(PAYLOAD_PATHS.war_room_alt_universe, pollMs);

export const useAlternativeDataStatus = (pollMs = 60_000) =>
  useJsonPayload<AlternativeDataStatus>(PAYLOAD_PATHS.alternative_data, pollMs);

export const useAltDataSymbolUniverseScoringStatus = (pollMs = 60_000) =>
  useJsonPayload<AltDataSymbolUniverseGapMatrix>(
    PAYLOAD_PATHS.alt_data_symbol_universe_scoring,
    pollMs,
  );

export const useNativeCudaTrainer = (pollMs = 30_000) =>
  useJsonPayload<NativeCudaTrainerStatus>(PAYLOAD_PATHS.native_cuda_trainer, pollMs);

export const useOrchestratorArbitrationLive = (pollMs = 30_000) =>
  useJsonPayload<OrchestratorArbitrationLiveStatus>(
    PAYLOAD_PATHS.orchestrator_arbitration_live,
    pollMs,
  );

export const useTradeManagementPaperLive = (pollMs = 30_000) =>
  useJsonPayload<TradeManagementPaperLiveStatus>(
    PAYLOAD_PATHS.trade_management_paper_live,
    pollMs,
  );

export const usePaperOnlineStatus = (pollMs = 30_000) =>
  useJsonPayload<PaperOnlineStatus>(PAYLOAD_PATHS.paper_online, pollMs);

export const useParallelSparkAutomationStatus = (pollMs = 30_000) =>
  useJsonPayload<ParallelSparkAutomationStatus>(
    PAYLOAD_PATHS.parallel_spark_automation,
    pollMs,
  );

export const useLegacyLogIntelligence = (pollMs = 60_000) =>
  useJsonPayload<LegacyLogIntelligenceStatus>(PAYLOAD_PATHS.legacy_log_intelligence, pollMs);

export const useProductionEquivalence = (pollMs = 60_000) =>
  useJsonPayload<ProductionEquivalenceComparison>(PAYLOAD_PATHS.production_equivalence, pollMs);

export const useLegacyLogEnriched = (pollMs = 60_000) =>
  useJsonPayload<LegacyLogEnrichedComparison>(PAYLOAD_PATHS.legacy_log_enriched, pollMs);

export const useWarRoomCodex5m = (pollMs = 30_000) =>
  useJsonPayload<Record<string, unknown>>(PAYLOAD_PATHS.war_room_codex_5m, pollMs);

// ---------------------------------------------------------------------------
// Live-canary bring-up (DRY-RUN-ONLY scaffolding; live_gate must stay
// blocked_human_only; live_symbols must stay []; the operator dashboard
// renders status/blockers but exposes NO controls).
// ---------------------------------------------------------------------------

export interface LiveCanaryDashboardPayload extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  go_no_go?: string;
  dry_run?: boolean;
  live_enabled?: boolean;
  approval_file_present?: boolean;
  canary_mode_selected?: string;
  permission_probe_go_no_go?: string;
  permission_probe_fail_blockers?: string[];
  codex_live_canary_pass_marker_present?: boolean;
  intent_count?: number;
  real_order_attempted?: boolean;
  leverage_changed?: boolean;
  margin_mode_changed?: boolean;
  raw_credential_in_payload?: string;
  kill_switch_namespace?: string;
  allowed_redis_writes?: string[];
  checkpoint_compatibility_claimed?: boolean;
  policy_architecture_parity_claimed?: boolean;
  current_truth?: Record<string, unknown>;
}

export interface LiveCanaryExecutorStatus extends LiveCanaryDashboardPayload {
  intents?: Array<{
    cycle_id?: string;
    generated_utc?: string;
    candidate?: {
      symbol?: string;
      side?: string;
      requested_notional_usdt?: number;
      signal_source?: string;
      paper_fill_gate_open?: boolean;
      feature_freshness_state?: string;
      v2_prediction_present?: boolean;
    };
    fail_blockers?: string[];
    would_advance_to_live_submission?: boolean;
    real_order_submitted?: boolean;
    places_real_order?: boolean;
    dry_run?: boolean;
  }>;
}

export interface LiveCanaryPermissionProbeStatus extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  go_no_go?: string;
  canary_mode_selected?: string;
  secrets_file_present?: boolean;
  approval_file_present?: boolean;
  codex_pass_marker_present?: boolean;
  binance_api_key_env_present?: boolean;
  binance_api_secret_env_present?: boolean;
  raw_credential_in_payload?: string;
  test_order_endpoint_attempted?: boolean;
  test_order_endpoint_response?: string;
  real_order_attempted?: boolean;
  leverage_changed?: boolean;
  margin_mode_changed?: boolean;
  fail_blockers?: string[];
}

export const useLiveCanaryBringupDashboard = (pollMs = 30_000) =>
  useJsonPayload<LiveCanaryDashboardPayload>(
    PAYLOAD_PATHS.live_canary_bringup_dashboard,
    pollMs,
  );

export const useLiveCanaryExecutorStatus = (pollMs = 30_000) =>
  useJsonPayload<LiveCanaryExecutorStatus>(
    PAYLOAD_PATHS.live_canary_executor_status,
    pollMs,
  );

export const useLiveCanaryPermissionProbe = (pollMs = 60_000) =>
  useJsonPayload<LiveCanaryPermissionProbeStatus>(
    PAYLOAD_PATHS.live_canary_permission_probe,
    pollMs,
  );

// ---------------------------------------------------------------------------
// Top-10 market + alt-data dashboard rendering payload.
// ---------------------------------------------------------------------------

export type Top10PanelState =
  | 'OK_ROWS_PRESENT'
  | 'KEY_PRESENT_NO_CLIENT_YET'
  | 'KEY_MISSING'
  | 'STALE'
  | 'BUDGET_LIMITED';

export interface Top10PanelRow {
  rank: number;
  symbol: string;
  quote_volume?: number | null;
  trade_count?: number | null;
  price_change_percent?: number | null;
  last_price?: number | null;
  liquidated_notional_usdt?: number | null;
  long_count?: number | null;
  short_count?: number | null;
  last_funding_rate?: number | null;
  open_interest?: number | null;
  long_short_ratio?: number | null;
  funding_age_seconds?: number | null;
  open_interest_age_seconds?: number | null;
  long_short_age_seconds?: number | null;
  score?: number | null;
}

export interface Top10Panel {
  panel_id: string;
  title: string;
  metric?: string;
  state: Top10PanelState;
  age_seconds?: number | null;
  rank_count: number;
  rows: Top10PanelRow[];
  source_status?: string;
  window_size_requested?: string;
  window_size_actual?: string;
  key_present?: boolean;
  paid_endpoints_enabled?: boolean;
  source_status_counts?: Record<string, number>;
  tier?: string;
  credential_in_payload?: string;
  heartbeat_present?: boolean;
  heartbeat_age_seconds?: number | null;
  tracked_symbols?: string[];
  missing_symbols?: string[];
}

export interface Top10DashboardPayload extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  go_no_go?: string;
  panels_total?: number;
  panels_with_rows?: number;
  panels_ok_rows_present?: number;
  panels_key_missing?: number;
  panels_stale?: number;
  panels_budget_limited?: number;
  panels_key_present_no_client_yet?: number;
  panels?: Top10Panel[];
  panel_state_legend?: Record<string, string>;
  raw_credential_in_payload?: string;
  no_provider_network_calls_from_frontend?: boolean;
  no_provider_network_calls_from_renderer?: boolean;
  no_live_buttons?: boolean;
  no_order_buttons?: boolean;
  no_shutdown_claim?: boolean;
  display_only?: boolean;
}

export const useTop10Dashboards = (pollMs = 60_000) =>
  useJsonPayload<Top10DashboardPayload>(PAYLOAD_PATHS.top10_dashboards, pollMs);

// ---------------------------------------------------------------------------
// Alt-data Symbol Universe candidate publisher.
// Display-only. Candidates are recommendations; they are NOT automatically
// adopted into live_symbols / paper_symbols / training_symbols. The
// publisher writes ONLY v2:symbol_universe:altdata_candidates +
// v2:altdata:candidate_publisher:status.
// ---------------------------------------------------------------------------

export type AltDataCandidateState =
  | 'CANDIDATE_READY'
  | 'MISSING_PROVIDER_DATA'
  | 'STALE_PROVIDER_DATA'
  | 'BUDGET_LIMITED'
  | 'BELOW_THRESHOLD'
  | 'SYMBOL_NOT_TRADABLE_ON_BINANCE'
  | 'SYMBOL_UNIVERSE_GATE_REQUIRED';

export interface AltDataCandidateSummaryRow {
  symbol: string;
  candidate_state: AltDataCandidateState;
  candidate_publisher_rank?: number | null;
  altdata_symbol_rank?: number | null;
  altdata_symbol_score?: number | null;
  proposed_use?: string[];
  missing_provider_flags?: string[];
  stale_provider_flags?: string[];
  candidate_reason?: string;
  candidate_only_not_adopted?: boolean;
  live_symbol_candidate?: boolean;
  paper_symbol_candidate?: boolean;
  training_symbol_candidate?: boolean;
  watchlist_candidate?: boolean;
}

export interface AltDataCandidatePublisherDashboard extends SafetyEnvelope {
  schema_version?: string;
  generated_utc?: string;
  go_no_go?: string;
  publisher_payload_path?: string;
  publisher_payload_generated_utc?: string;
  candidate_count?: number;
  candidate_state_counts?: Record<string, number>;
  // `candidates` is the canonical key produced by the publisher CLI
  // and is the source of truth for the candidate-row table. The
  // legacy `candidate_summary` alias is preserved for backward
  // compatibility only; the renderer must prefer `candidates`.
  candidates?: AltDataCandidateSummaryRow[];
  candidate_summary?: AltDataCandidateSummaryRow[];
  allowed_inputs?: string[];
  forbidden_input_namespaces?: string[];
  allowed_writes?: string[];
  watchlist_threshold?: number;
  paper_threshold?: number;
  training_threshold?: number;
  live_symbols_expanded?: boolean;
  paper_symbols_expanded?: boolean;
  training_symbols_expanded?: boolean;
  candidate_only_not_adopted?: boolean;
  may_not_override_strict_paper_fill_gate?: boolean;
  may_not_authorize_live_or_canary?: boolean;
  may_not_place_orders?: boolean;
  raw_credential_in_payload?: string;
}

export const useAltDataCandidatePublisher = (pollMs = 60_000) =>
  useJsonPayload<AltDataCandidatePublisherDashboard>(
    PAYLOAD_PATHS.alt_data_candidate_publisher,
    pollMs,
  );
