export const CUDA_TRAINER_LIVE_GATE_PATH =
  '/operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json';

export const CUDA_TRAINER_ACTIONABILITY_PATH =
  '/v2_native_ppo_masa_continuous_training_guard/latest/operator_dashboard_payload.json';

export interface CudaOutcomeRow {
  prediction_id?: string;
  symbol?: string;
  timeframe?: string;
  selected_action?: string;
  counterfactual_side?: string | null;
  expected_move_after_cost_bps?: number | null;
  confidence_calibrated?: number | null;
  realized_after_cost_return_bps?: number | null;
  classification?: string;
  false_positive?: boolean;
  false_negative?: boolean;
  risk_reason?: string | null;
  paper_ledger_reason?: string | null;
}

export interface CudaEdgeGroup {
  symbol?: string;
  selected_action?: string;
  confidence_bucket?: string;
  sample_count?: number;
  after_cost_expectancy_bps?: number | null;
  after_cost_ci_lower_bps?: number | null;
}

export interface CudaTrainerLiveGatePayload {
  generated_at?: string;
  generated_est?: string;
  payload_age_seconds?: number;
  go_no_go?: string;
  source_gate?: string;
  live_gate?: string;
  trader_state?: string;
  live_order_submit_blocker?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
  approves_live?: boolean;
  approves_canary?: boolean;
  next_automatic_action?: string;
  prediction_count?: number;
  prediction_rows?: number;
  prediction_grid_rows?: number;
  prediction_grid_expected_rows?: number;
  blocked_prediction_rows?: number;
  valid_symbol_count?: number;
  timeframes?: string[];
  training_steps_total?: number;
  training_steps_last_hour?: number;
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
  checkpoint_dir_size_bytes?: number | null;
  checkpoint_rollover_status?: string;
  trainer_bridge_active?: boolean;
  trainer_bridge_masked?: boolean;
  rl_core_primary_overwrites?: number;
  rl_core_sidecar_rows?: number;
  parity_status?: string;
  hybrid_trainer_methods_inventoried?: number;
  required_missing_parity_methods?: number;
  paper_current_session_equity?: number | null;
  paper_current_session_pnl?: number | null;
  paper_accepted_fills?: number | null;
  paper_open_positions?: number | null;
  paper_confidence_trial_guard_status?: string;
  paper_confidence_trial_guard_reason?: string;
  paper_confidence_trial_guard_trial_enabled?: boolean;
  resource_bottleneck_reason?: string;
  current_runtime_panel_source?: string;
  lineage_count?: number;
  trainer?: {
    trainer_source?: string;
    model_source?: string;
    checkpoint_id?: string;
    cuda_active?: boolean;
    model_device?: string;
    model_tensors_device_verified?: boolean;
    live_gate?: string;
    live_symbols?: string[];
    risk_caps_configured?: boolean;
  };
  metrics?: {
    training?: {
      gpu_name?: string | null;
      vram_allocated_mb?: number | null;
      training_steps?: number;
      train_rows?: number;
      validation_rows?: number;
      loss_before?: number | null;
      loss_after?: number | null;
      cuda_active?: boolean;
      cuda_claim_verified?: boolean;
    };
    data_coverage_avg?: number;
    missing_feature_count_total?: number;
    stale_feature_count_total?: number;
  };
  burn_in?: {
    status?: string;
    burn_in_complete?: boolean;
    cuda_active?: boolean;
    gpu_name?: string | null;
    prediction_count?: number;
    symbols_covered?: string[];
    symbols_covered_count?: number;
    outcome_windows_ready_counts?: Record<string, number>;
    fallback_wrapper_usage_count?: number;
  };
  prediction_contract?: {
    status?: string;
    contract_pass?: boolean;
    predictions_checked?: number;
  };
  risk_consumption?: {
    status?: string;
    consumption_pass?: boolean;
    lineage_count?: number;
    risk_caps_status?: string;
    rows?: {
      prediction_id_consumed?: string;
      risk_decision_id?: string;
      risk_action?: string;
      block_allow_reason?: string;
      confidence_calibrated?: number | null;
      expected_move_after_cost_bps?: number | null;
    }[];
  };
  orchestrator_consumption?: {
    status?: string;
    consumption_pass?: boolean;
    lineage_count?: number;
    risk_decision_pairing?: { status?: string; note?: string };
    strategy_fallback?: { status?: string };
    rows?: {
      orchestrator_decision_id?: string;
      trainer_prediction_id?: string;
      risk_decision_id?: string;
      action?: string;
      hold_block_reason?: string;
    }[];
  };
  paper_signal_lineage?: {
    status?: string;
    consumption_pass?: boolean;
    lineage_count?: number;
    rows?: {
      cuda_trainer_prediction_id?: string;
      paper_intent_id?: string;
      paper_ledger_row?: string;
      paper_ledger_id?: string;
      paper_ledger_outcome?: string;
      trainer_prediction_id?: string;
      risk_decision_id?: string;
      orchestrator_decision_id?: string;
      selected_action?: string;
      action?: string;
      fill_held_block_result?: string;
      classification?: string;
    }[];
  };
  outcome_mining?: {
    status?: string;
    prediction_count?: number;
    primary_outcome_window?: string;
    outcome_sample_count?: number;
    window_ready_counts?: Record<string, number>;
    classification_counts?: Record<string, number>;
    rows?: CudaOutcomeRow[];
    no_fabricated_outcomes?: boolean;
    pending_windows_are_null?: boolean;
  };
  confidence_calibration?: {
    status?: string;
    outcome_sample_count?: number;
    minimum_outcome_sample_guard?: number;
    minimum_outcome_sample_guard_passed?: boolean;
    calibration_error?: number | null;
    high_confidence_loser_count?: number;
    high_confidence_losers?: CudaOutcomeRow[];
    low_confidence_winner_count?: number;
    low_confidence_winners?: CudaOutcomeRow[];
    confidence_bucket_calibration?: {
      bucket?: string;
      sample_count?: number;
      success_count?: number;
      avg_confidence?: number | null;
      realized_success_rate?: number | null;
      calibration_error?: number | null;
    }[];
    paper_shadow_calibration_overlay?: {
      confidence_calibration_penalty?: number;
      expected_move_decay?: number;
      minimum_outcome_sample_guard?: number;
      high_confidence_loser_downrank?: boolean;
      applies_to_live?: boolean;
      applies_to_canary?: boolean;
    };
  };
  edge_recompute?: {
    status?: string;
    edge_proven?: boolean;
    primary_recommendation?: string;
    recommendations?: string[];
    new_cuda_trainer?: {
      sample_count?: number;
      after_cost_expectancy_bps?: number | null;
      after_cost_ci_lower_bps?: number | null;
    };
    outcome_sample_count?: number;
    false_positive_rate?: number | null;
    false_negative_rate?: number | null;
    false_positive_count?: number;
    false_negative_count?: number;
    drawdown?: { max_drawdown_bps?: number | null; observations?: number };
    by_symbol_edge?: CudaEdgeGroup[];
    by_action_edge?: CudaEdgeGroup[];
    by_confidence_bucket_edge?: CudaEdgeGroup[];
  };
  website_live_gate?: {
    status?: string;
    exact_live_blockers?: string[];
    must_show?: {
      current_after_cost_edge?: number | null;
      confidence_calibration?: string;
      high_confidence_losers?: number;
      outcome_sample_count?: number;
      false_positives?: number;
      false_negatives?: number;
      why_live_blocked?: string[];
      next_automatic_action?: string;
    };
    live_switch?: {
      visible?: boolean;
      enabled?: boolean;
      disabled_reason?: string;
      backend_live_enable_callable?: boolean;
    };
  };
  live_readiness?: {
    live_ready?: boolean;
    canary_ready?: boolean;
    primary_recommendation?: string;
    recommendations?: string[];
    live_gate?: string;
    live_symbols?: string[];
    execution_live_symbols?: string[];
    approves_live?: boolean;
    approves_canary?: boolean;
  };
  live_switch?: {
    visible?: boolean;
    enabled?: boolean;
    disabled_reason?: string;
    backend_live_enable_callable?: boolean;
  };
}

export function cudaBlockers(payload: CudaTrainerLiveGatePayload | null | undefined): string[] {
  return payload?.live_readiness?.recommendations
    ?? payload?.website_live_gate?.exact_live_blockers
    ?? payload?.edge_recompute?.recommendations
    ?? [];
}

export interface CudaActionabilitySimulation {
  simulation_id?: string;
  description?: string;
  paper_only?: boolean;
  runtime_config_changed?: boolean;
  thresholds_auto_accepted?: boolean;
  sample_count?: number;
  candidate_count?: number;
  recovered_false_negatives?: number;
  introduced_false_positives_estimate?: number;
  expected_after_cost_change?: number | null;
  candidate_after_cost_expectancy_bps?: number | null;
  candidate_after_cost_ci_lower_bps?: number | null;
  max_drawdown_estimate?: number | null;
  recommendation?: string;
  notes?: string;
}

export interface CudaFalseNegativeAttributionRow {
  prediction_id?: string;
  symbol?: string;
  timeframe?: string;
  trainer_action?: string;
  trainer_confidence?: number | null;
  expected_move_after_cost_bps?: number | null;
  realized_after_cost_bps?: number | null;
  missed_direction?: string | null;
  block_reason?: string | null;
  data_coverage_percent?: number | null;
  primary_root_cause?: string;
  root_causes?: string[];
  strategy_agreement_disagreement?: string;
  risk_decision?: { risk_decision_id?: string; risk_action?: string; risk_reason?: string };
  orchestrator_decision?: { orchestrator_decision_id?: string; orchestrator_action?: string; orchestrator_reason?: string };
  paper_outcome?: { paper_ledger_id?: string; paper_ledger_action?: string; paper_ledger_reason?: string; classification?: string };
}

export interface CudaPaperOverlayRow {
  overlay_candidate_id?: string;
  prediction_id?: string;
  symbol?: string;
  timeframe?: string;
  candidate_direction?: string;
  source?: string;
  overlay_reason?: string;
  risk_bypass?: boolean;
  risk_decision_id?: string;
  risk_action?: string;
  realized_after_cost_bps?: number | null;
  confidence_calibrated?: number | null;
  data_coverage_percent?: number | null;
}

export interface CudaTrainerActionabilityPayload {
  generated_at?: string;
  generated_est?: string;
  generated_utc?: string;
  go_no_go?: string;
  gate?: string;
  source_gate?: string;
  blockers?: string[];
  actions?: unknown[];
  freshness?: {
    trainer_dashboard_age_seconds?: number;
    trainer_dashboard_max_age_seconds?: number;
    trainer_dashboard_stale?: boolean;
  };
  exploration?: { action_contract?: string[] };
  live_constraints?: {
    live_gate?: string;
    live_order_submit_allowed?: boolean;
    live_order_submit_blocker?: string;
  };
  safety?: {
    legacy_restart?: boolean;
    leverage_or_margin_mutation?: boolean;
    old_redis_write?: boolean;
    raw_credential_in_payload?: boolean;
  };
  summary?: {
    prediction_rows?: number;
    paper_allowed_before?: number;
    trial_candidate_count?: number;
    trial_promoted_signal_count?: number;
    paper_confidence_threshold?: number;
    paper_loop_run?: boolean;
  };
  paper?: {
    accepted_fill_total?: number;
    economic_fill_total?: number;
    open_positions_count?: number;
    current_session_equity?: number;
    current_session_pnl?: number;
    realized_pnl_usd?: number;
    unrealized_pnl_usd?: number;
    last_equity_update_est?: string;
  };
  live?: {
    live_gate?: string;
    trader_state?: string;
    live_order_submit_allowed?: boolean;
    live_order_submit_blocker?: string;
    live_threshold_changed?: boolean;
  };
  false_negative_attribution?: {
    status?: string;
    false_negative_count?: number;
    root_cause_counts?: Record<string, number>;
    lineage_complete?: boolean;
    rows?: CudaFalseNegativeAttributionRow[];
  };
  threshold_actionability_simulation?: {
    status?: string;
    paper_only?: boolean;
    runtime_thresholds_changed?: boolean;
    thresholds_auto_accepted?: boolean;
    recommended_simulation_id?: string;
    simulations?: CudaActionabilitySimulation[];
  };
  strategy_assisted_recovery?: {
    status?: string;
    false_negative_count?: number;
    strategy_agreement_count?: number;
    strategy_disagreement_or_insufficient_count?: number;
  };
  paper_actionability_overlay?: {
    status?: string;
    overlay_source?: string;
    overlay_candidate_count?: number;
    paper_shadow_only?: boolean;
    runtime_config_changed?: boolean;
    thresholds_auto_accepted?: boolean;
    risk_bypass?: boolean;
    risk_fail_closed_preserved?: boolean;
    can_bypass_risk?: boolean;
    rows?: CudaPaperOverlayRow[];
  };
  edge_after_actionability_overlay?: {
    status?: string;
    edge_proven?: boolean;
    primary_recommendation?: string;
    recommendations?: string[];
    before_overlay?: {
      after_cost_expectancy_bps?: number | null;
      after_cost_ci_lower_bps?: number | null;
      false_positive_count?: number;
      false_negative_count?: number;
      correct_no_trade_count?: number;
      candidate_count?: number;
    };
    simulated_overlay?: {
      overlay_candidate_count?: number;
      recovered_false_negatives?: number;
      introduced_false_positives_estimate?: number;
      candidate_after_cost_expectancy_bps?: number | null;
      candidate_after_cost_ci_lower_bps?: number | null;
      candidate_count?: number;
    };
    actual_paper_shadow_overlay_after_burn_in?: {
      available?: boolean;
      status?: string;
    };
    by_symbol_recovered_opportunities?: {
      symbol?: string;
      recovered_count?: number;
      candidate_after_cost_expectancy_bps?: number | null;
    }[];
  };
  website_sync?: {
    status?: string;
    surfaces_synced?: string[];
    must_show?: {
      false_negative_count?: number;
      false_negative_root_causes?: Record<string, number>;
      threshold_simulation_results?: number;
      paper_only_overlay_status?: string;
      recovered_opportunities?: number;
      why_live_remains_blocked?: string[];
    };
  };
  live_readiness?: {
    live_ready?: boolean;
    canary_ready?: boolean;
    primary_recommendation?: string;
    recommendations?: string[];
    live_gate?: string;
    live_symbols?: string[];
    execution_live_symbols?: string[];
    approves_live?: boolean;
    approves_canary?: boolean;
  };
  live_switch?: {
    visible?: boolean;
    enabled?: boolean;
    disabled_reason?: string;
    backend_live_enable_callable?: boolean;
  };
  safety_scoreboard?: {
    paper_shadow_only?: boolean;
    runtime_config_changed?: boolean;
    thresholds_auto_accepted?: boolean;
    risk_bypass?: boolean;
    approves_live?: boolean;
    approves_canary?: boolean;
  };
}

export function cudaActionabilityBlockers(payload: CudaTrainerActionabilityPayload | null | undefined): string[] {
  return payload?.live_readiness?.recommendations
    ?? payload?.edge_after_actionability_overlay?.recommendations
    ?? [];
}

export function cudaCountMapText(counts: Record<string, number> | null | undefined): string {
  const entries = Object.entries(counts ?? {});
  if (entries.length === 0) return '—';
  return entries.map(([key, value]) => `${key}: ${value}`).join(', ');
}

export function cudaBpsText(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} bps` : '—';
}
