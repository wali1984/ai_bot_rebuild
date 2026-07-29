import Foundation

public func acceptsCurrentPaperSessionFrame(
    incomingSessionId: String?,
    incomingEpoch: Int?,
    activeSessionId: String?,
    activeEpoch: Int?
) -> Bool {
    guard activeSessionId != nil || activeEpoch != nil else { return true }
    if activeSessionId != nil && incomingSessionId == nil { return false }
    if let activeEpoch {
        guard let incomingEpoch else { return false }
        if incomingEpoch < activeEpoch { return false }
        if incomingEpoch == activeEpoch,
           let activeSessionId,
           let incomingSessionId,
           incomingSessionId != activeSessionId {
            return false
        }
    }
    return true
}

// MARK: - Dashboard

public struct MobileDashboard: Decodable, Sendable {
    public let generated_utc: String
    public let live_gate: LiveGateState
    public let paper: PaperState
    public let trainer: TrainerState
    public let gpu: GPUState
    public let alerts_preview: [MobileAlert]
    public let redis_connected: Bool
}

public struct LiveGateState: Decodable, Sendable {
    public let live_trading_enabled: Bool
    public let places_real_order: Bool
    public let gate: String
    public let label: String
}

public struct PaperState: Decodable, Sendable {
    public let paper_session_id: String?
    public let paper_account_epoch: Int?
    public let scope: String?
    public let historical_rows_excluded_from_current_view: Int?
    public let historical_evidence_preserved: Bool?
    public let equity: Double?
    public let paper_equity: Double?
    public let paper_equity_usd: Double?
    public let paper_balance: Double?
    public let initial_capital: Double?
    public let starting_equity_usd: Double?
    public let new_entries_allowed: Bool?
    public let performance: MobileRuntimePerformance?
    public let entry_freeze: MobileRuntimeEntryFreeze?
    public let a_plus_gate: MobileRuntimeAPlusGate?
    public let reduced_size_bootstrap: MobileRuntimeReducedSizeBootstrap?
    public let trainer_learning: MobileRuntimeTrainerLearning?
    public let real_trader_readiness: MobileRuntimeReadiness?
    public let market_data_freshness: MobileMarketDataFreshness?
    public let preemptive_edge_control: MobilePreemptiveEdgeControl?
    public let adaptive_hedge_cross_margin: MobileHedgeCrossMargin?
    public let provider_readiness: MobileProviderReadiness?
    public let top_blockers: [String]?
    public let open_positions: Int
    public let closed_trades: Int
    public let realized_pnl_usd: Double
    public let paper_realized_pnl_usd: Double?
    public let unrealized_pnl_usd: Double
    public let paper_unrealized_pnl_usd: Double?
    public let paper_total_pnl_usd: Double?
    public let data_source: String?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let signals_seen: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
    public let classification: String
    public let places_real_order: Bool
    public var total_pnl: Double { paper_total_pnl_usd ?? realized_pnl_usd + unrealized_pnl_usd }
    public var effectiveEquity: Double? { paper_equity_usd ?? paper_equity ?? equity ?? paper_balance }
}

public struct MobileRuntimePerformance: Decodable, Sendable {
    public let profit_factor: Double?
    public let expectancy_usd: Double?
    public let realized_pnl_usd: Double?
    public let notional_weighted_expectancy_bps: Double?
    public let win_rate: Double?
    public let closed_outcome_count: Int?
    public let governor_state: String?
}

public struct MobileRuntimeEntryFreeze: Decodable, Sendable {
    public let new_entries_allowed: Bool?
    public let halt_reasons: [String]?
    public let future_gate_blockers: [String]?
    public let allow_close: Bool?
    public let allow_reduce: Bool?
}

public struct MobileRuntimeAPlusGate: Decodable, Sendable {
    public let evaluated_candidates: Int?
    public let a_plus_candidates: Int?
    public let rejected_reason_matrix: [String: Int]?
    public let gate_is_hard_entry_condition: Bool?
}

public struct MobileRuntimeReducedSizeBootstrap: Decodable, Sendable {
    public let final_a_plus_candidates: Int?
    public let reduced_size_bootstrap_candidates: Int?
    public let closed_rows: Int?
    public let counts_as_final_a_plus: Bool?
    public let b_grade_counts_as_final_a_plus: Bool?
    public let routes_to_live: Bool?
    public let paper_only: Bool?
    public let generated_at: String?
}

public struct MobileRuntimeTrainerLearning: Decodable, Sendable {
    public let effective_trainer_mode: String?
    public let online_learning_status: String?
    public let last_successful_weight_update_at: String?
    public let checkpoint_id: String?
}

public struct MobileRuntimeReadiness: Decodable, Sendable {
    public let live_gate: String?
    public let operator_flip_required: Bool?
    public let order_submitted: Bool?
    public let test_order_submitted: Bool?
    public let leverage_mutated: Bool?
    public let margin_mutated: Bool?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?
    public let live_submit_allowed: Bool?
    public let live_ready: Bool?
    public let exact_no_live_reason: String?
    public let readiness_blockers: [String]?
}

public struct MobileMarketDataFreshness: Decodable, Sendable {
    public let source: String?
    public let generated_at: String?
    public let age_seconds: Int?
    public let freshness_state: String?
}

public struct MobileAdvancedIndicators: Decodable, Sendable {
    public let status: String?
    public let candidate_count: Int?
    public let fvg_present_count: Int?
    public let fvg_side_aligned_count: Int?
    public let accepted_advanced_indicator_block_count: Int?
    public let fvg_standalone_allows_trade: Bool?
    public let fvg_alone_can_approve_trade: Bool?
    public let sweep_risk_can_block_or_reduce: Bool?
    public let block_reason_counts: [String: Int]?
    public let caution_reason_counts: [String: Int]?
}

public struct MobilePreemptiveEdgeControl: Decodable, Sendable {
    public let preemptive_decision_id: String?
    public let status: String?
    public let candidate_count: Int?
    public let accepted_count: Int?
    public let decision_counts: [String: Int]?
    public let action_counts: [String: Int]?
    public let preemptive_action: String?
    public let preemptive_allowed: Bool?
    public let preemptive_block_reasons: [String]?
    public let pre_trade_expected_net_pnl_usd: Double?
    public let pre_trade_loss_probability: Double?
    public let confidence_overstatement_risk: Double?
    public let regime_compatibility_score: Double?
    public let exit_feasibility_score: Double?
    public let bucket_profit_factor: Double?
    public let positive_edge_probation_status: String?
    public let positive_edge_probation_supply_state: String?
    public let positive_edge_probation_candidates: Int?
    public let positive_edge_probation_accepted: Int?
    public let closed_probation_trade_count: Int?
    public let probation_5_trade_gate_status: String?
    public let probation_counts_as_final_a_plus: Bool?
    public let probation_counts_as_live_ready: Bool?
    public let why_trade_was_prevented: [String]?
    public let governor_auto_action: String?
    public let next_remediation: String?
    public let hard_fail: Bool?
    public let advanced_indicators: MobileAdvancedIndicators?
    public let advanced_indicator_status: String?
    public let advanced_indicator_block_reason_counts: [String: Int]?
    public let advanced_indicator_caution_reason_counts: [String: Int]?
    public let paper_only: Bool?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?

    public var preventedCount: Int {
        (decision_counts?["NO_TRADE"] ?? 0) + (decision_counts?["SHADOW_ONLY"] ?? 0)
    }
}

public struct MobileHedgeCrossMargin: Decodable, Sendable {
    public let status: String?
    public let recommended_leverage_distribution: [Double]?
    public let recommended_margin_mode_distribution: [String]?
    public let current_notional_distribution_usd: [Double]?
    public let hedge_state: String?
    public let hedge_rows: Int?
    public let cross_margin_state: String?
    public let cross_margin_safe: Bool?
    public let net_delta_usd: Double?
    public let gross_exposure_usd: Double?
    public let portfolio_liquidation_buffer_usd: Double?
    public let worst_case_portfolio_loss_usd: Double?
    public let margin_call_risk: String?
    public let operator_display_currency: String?
    public let operator_display_timezone: String?
}

public struct MobileHedgeCandidate: Decodable, Sendable {
    public let symbol: String?
    public let side: String?
    public let unrealized_pnl_usd: Double?
}

public struct MobileHedgeSnapshot: Decodable, Sendable {
    public let schema_version: String?
    public let hedge_engine_active: Bool?
    public let hedge_evaluation_mode: String?
    public let open_position_count: Int?
    public let negative_position_count: Int?
    public let hedge_required_candidates: [MobileHedgeCandidate]?
    public let portfolio_liquidation_buffer_usd: Double?
    public let hedge_basket: [String]?
    public let cross_margin_model: String?
    public let places_real_order: Bool?
    public let routes_to_live: Bool?
}

public struct MobileIngestorRollup: Decodable, Sendable {
    public let schema_version: String?
    public let overall_status: String?
    public let stream_present: [String: Bool]?
    public let all_core_streams_present: Bool?
    public let provider_count: Int?
    public let active_provider_count: Int?
    public let stale_provider_count: Int?
    public let stale_providers: [String]?
}

public struct MobileProviderReadiness: Decodable, Sendable {
    public let status: String?
    public let coinglass_status: String?
    public let moralis_status: String?
    public let coinglass_dashboard_color: String?
    public let moralis_dashboard_color: String?
    public let coinglass_actual_payload_present: Bool?
    public let moralis_actual_payload_present: Bool?
    public let coinglass_heartbeat_only: Bool?
    public let moralis_heartbeat_only: Bool?
    public let moralis_feature_bridge_ready: Bool?
    public let moralis_feature_count: Int?
    public let moralis_required_feature_count: Int?
    public let moralis_missing_feature_flags: [String]?
    public let moralis_stale_feature_flags: [String]?
    public let moralis_missing_mask_true: Bool?
    public let moralis_stale_mask_true: Bool?
    public let moralis_token_map_count: Int?
    public let moralis_wallet_watchlist_count: Int?
    public let provider_tensor_consumption: Bool?
    public let provider_risk_consumption: Bool?
    public let provider_orchestrator_consumption: Bool?
    public let provider_allocator_consumption: Bool?
    public let provider_paper_consumption: Bool?
    public let provider_live_dryrun_consumption: Bool?
    public let provider_feedback_attribution: Bool?
    public let ppo_provider_feature_count: Int?
    public let masa_provider_feature_count: Int?
    public let confluence_trade_block_score: Double?
    public let confluence_reduce_size_score: Double?
    public let confluence_hedge_required_score: Double?
    public let altdata_single_provider_can_approve: Bool?
    public let heartbeat_only_green_allowed: Bool?
    public let raw_keys_exposed: Bool?
    public let invalid_subscription_blocks_core_system: Bool?
}

public struct TrainerState: Decodable, Sendable {
    public let state: String
    public let checkpoint: String
    public let model_source: String
    public let champion_challenger_status: ChampionChallengerStatus?
    public let cuda_active: Bool
    public let data_coverage: Double
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
    public var isActive: Bool { state.hasPrefix("ACTIVE") }
}

public struct ChampionChallengerStatus: Decodable, Sendable {
    public let status: String?
    public let result_status: String?
    public let best_challenger_id: String?
    public let promotion_allowed: Bool?
    public let promotion_reason: String?
    public let paper_challenger_enabled: Bool?
    public let replay_windows_processed: Int?
    public let replay_snapshots_scanned: Int?
}

public struct GPUState: Decodable, Sendable {
    public let name: String
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public var vramPercent: Double {
        guard vram_total_mb > 0 else { return 0 }
        return Double(vram_used_mb) / Double(vram_total_mb) * 100
    }
    public var vramUsedGB:  Double { Double(vram_used_mb)  / 1024 }
    public var vramTotalGB: Double { Double(vram_total_mb) / 1024 }
}

// MARK: - Position

public struct MobilePosition: Decodable, Sendable {
    public let id: String
    public let paper_session_id: String?
    public let paper_account_epoch: Int?
    public let symbol: String
    public let side: String
    public let qty: Double
    public let entry_price: Double?
    public let entry_price_source: String?
    public let exit_price: Double?
    public let exit_price_source: String?
    public let mark_price: Double?
    public let mark_price_source: String?
    public let mark_price_generated_at: String?
    public let mark_price_age_seconds: Double?
    public let mark_price_stale: Bool?
    public let unrealized_pnl: Double?
    public let realized_pnl: Double
    public let opened_at: String
    public let closed_at: String?
    public let close_reason: String?
    public let status: String
    public let signal_id: String?
    public let prediction_id: String?
    public let decision_reasoning: PositionDecisionReasoning?
    public let account_scope: String?
    public let source_type: String?
    public let paper_or_live: String?
    public let contains_simulated_positions: Bool?
    public let contains_live_positions: Bool?
    public let contains_quarantined_positions: Bool?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let reason_if_untrusted: String?
    public let routes_to_live: Bool?
    public var total_pnl: Double { (unrealized_pnl ?? 0) + realized_pnl }
    public var isBuy: Bool { side.lowercased().contains("long") || side.lowercased() == "buy" }
}

public struct PositionDecisionReasoning: Decodable, Sendable {
    public let source: String?
    public let signal_id: String?
    public let prediction_id: String?
    public let timeframe: String?
    public let action: String?
    public let confidence: Double?
    public let risk_state: String?
    public let paper_fill_status: String?
    public let market_regime: String?
    public let expected_move_bps: Double?
    public let data_coverage: Double?
    public let reason: String?
    public let available_at: String?
    public let decision_time: String?
    public let generated_at: String?
    public let model_version: String?
}

public struct MobilePositionsResponse: Decodable, Sendable {
    public let generated_utc: String
    public let paper_session_id: String?
    public let paper_account_epoch: Int?
    public let scope: String?
    public let starting_equity_usd: Double?
    public let historical_rows_excluded_from_current_view: Int?
    public let historical_evidence_preserved: Bool?
    public let positions: [MobilePosition]
    public let closed_positions: [MobilePosition]?
    public let historical_positions: [MobilePosition]?
    public let position_pricing: PositionPricing?
    public let warnings: [String]?
    public let summary: PositionSummary
    public let mode: String
    public let live_gate: String
    public let places_real_order: Bool
    public let account_scope: String?
    public let source_type: String?
    public let paper_or_live: String?
    public let contains_simulated_positions: Bool?
    public let contains_live_positions: Bool?
    public let contains_quarantined_positions: Bool?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let reason_if_untrusted: String?
    public let routes_to_live: Bool?
}

public struct PositionPricing: Decodable, Sendable {
    public let unrealized_pnl_usd: Double?
    public let total_open_notional: Double?
    public let mark_to_market_live: Bool?
    public let live_mark_price_count: Int?
    public let stale_mark_price_count: Int?
    public let missing_mark_price_count: Int?
}

public struct PositionSummary: Decodable, Sendable {
    public let open_count: Int
    public let closed_count: Int?
    public let total_pnl_usd: Double
    public let realized_pnl_usd: Double
    public let unrealized_pnl_usd: Double
    public let account_scope: String?
    public let source_type: String?
    public let paper_or_live: String?
    public let contains_simulated_positions: Bool?
    public let contains_live_positions: Bool?
    public let contains_quarantined_positions: Bool?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let reason_if_untrusted: String?
    public let routes_to_live: Bool?
}

// MARK: - Signal

public struct MobileSignal: Decodable, Sendable {
    public let id: String
    public let symbol: String
    public let timeframe: String
    public let action: String
    public let confidence: Double
    public let confidence_selected_action: Double?
    public let confidence_executable_trade: Double?
    public let confidence_display_label: String?
    public let confidence_type: String?
    public let confidence_a_plus_eligible: Bool?
    public let confidence_tradeability_block_reasons: [String]?
    public let paper_exploration_tier: String?
    public let exploration_tier: String?
    public let paper_exploration_current_blocker: String?
    public let paper_exploration_paper_fill_allowed: Bool?
    public let paper_exploration_risk_controller_decision: String?
    public let paper_exploration_orchestrator_decision: String?
    public let paper_exploration_allocator_decision: String?
    public let expected_net_pnl_usd: Double?
    public let expected_max_loss_usd: Double?
    public let why_not_a_plus: [String]?
    public let why_not_live_ready: [String]?
    public let risk_controller_decision: String?
    public let allocator_decision: String?
    public let trainer_feedback_status: String?
    public let actionable: Bool
    public let risk_state: String
    public let paper_fill_status: String
    public let published_at: String
    public var confidencePct: String { "\(Int(confidence * 100))%" }
    public var selectedConfidence: Double { confidence_selected_action ?? confidence }
    public var executableConfidence: Double { confidence_executable_trade ?? 0 }
    public var selectedConfidencePct: String { "\(Int(selectedConfidence * 100))%" }
    public var executableConfidencePct: String { "\(Int(executableConfidence * 100))%" }
    public var confidenceDisplayLabel: String { confidence_display_label ?? "Unproven confidence" }
    public var paperExplorationTier: String { paper_exploration_tier ?? exploration_tier ?? "NONE" }
    public var paperExplorationCurrentBlocker: String { paper_exploration_current_blocker ?? "not above floor" }
    public var whyNotAPlus: String { why_not_a_plus?.first ?? "A+ evidence not matured" }
    public var whyNotLiveReady: String { why_not_live_ready?.first ?? "blocked_human_only" }
}

public struct MobileSignalsResponse: Decodable, Sendable {
    public let generated_utc: String
    public let signals: [MobileSignal]
    public let total_returned: Int
    public let actionable_only: Bool
}

// MARK: - Alert

public struct MobileAlert: Decodable, Sendable {
    public let id: String
    public let symbol: String
    public let type: String
    public let message: String
    public let severity: String
    public let triggered_at: String
}

public struct MobileAlertsResponse: Decodable, Sendable {
    public let generated_utc: String
    public let alerts: [MobileAlert]
    public let total_returned: Int
}

// MARK: - Auth Health

public struct AuthHealth: Decodable, Sendable {
    public let schema_version: String
    public let generated_at_utc: String?
    public let generated_at_et: String?
    public let source: String?
    public let status: String
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let canonical_owner: String?
    public let data_quality_status: String?
    public let login_endpoint_available: Bool
    public let auth_store_backend: String?
    public let durable_user_store_configured: Bool?
    public let production_ready: Bool?
    public let contains_secret_values: Bool
    public let raw_credential_value_exposed: Bool
    public let live_gate: String
    public let places_real_order: Bool
    public let routes_to_live: Bool
    public let exchange_mutation_enabled: Bool?
    public let session_security: AuthHealthSessionSecurity?
    public let warnings: [String]?

    public var isLoginReachable: Bool {
        login_endpoint_available && status.lowercased() == "ok"
    }

    public var isLiveBlocked: Bool {
        live_gate == "blocked_human_only" && !places_real_order && !routes_to_live
    }

    public var hasNoLiveRoutingOrSecretExposure: Bool {
        !places_real_order
            && !routes_to_live
            && !(exchange_mutation_enabled ?? false)
            && !raw_credential_value_exposed
            && !contains_secret_values
    }

    public var accountRuntimeSafetyStatus: String {
        isLiveBlocked && hasNoLiveRoutingOrSecretExposure
            ? "NO_LIVE_ROUTING_OR_SECRET_EXPOSURE"
            : "REVIEW_REQUIRED"
    }

    public var accountSettingsCanonicalSource: String {
        canonical_owner ?? "/api/auth/health"
    }
}

public struct AuthHealthSessionSecurity: Decodable, Sendable {
    public let cookie_name: String?
    public let token_type: String?
    public let http_only_cookie: Bool?
    public let secure_cookie: Bool?
    public let same_site: String?
}

// MARK: - Health

public struct MobileHealth: Decodable, Sendable {
    public let generated_utc: String
    public let overall: String
    public let redis_connected: Bool
    public let trainer: HealthTrainer
    public let gpu: HealthGPU
    public let paper: HealthPaper
    public let ingestors: MobileIngestorRollup?
    public let live_gate: String
    public let places_real_order: Bool
    public var isHealthy: Bool { overall == "healthy" }
}

public struct HealthTrainer: Decodable, Sendable {
    public let state: String
    public let cuda_active: Bool
    public let training_active: Bool
    public let checkpoint: String
    public let champion_challenger_status: ChampionChallengerStatus?
}

public struct HealthGPU: Decodable, Sendable {
    public let name: String
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public let temperature_c: Double
}

public struct HealthPaper: Decodable, Sendable {
    public let paper_session_id: String?
    public let equity: Double?
    public let paper_equity: Double?
    public let performance: MobileRuntimePerformance?
    public let entry_freeze: MobileRuntimeEntryFreeze?
    public let a_plus_gate: MobileRuntimeAPlusGate?
    public let reduced_size_bootstrap: MobileRuntimeReducedSizeBootstrap?
    public let trainer_learning: MobileRuntimeTrainerLearning?
    public let real_trader_readiness: MobileRuntimeReadiness?
    public let market_data_freshness: MobileMarketDataFreshness?
    public let preemptive_edge_control: MobilePreemptiveEdgeControl?
    public let adaptive_hedge_cross_margin: MobileHedgeCrossMargin?
    public let provider_readiness: MobileProviderReadiness?
    public let top_blockers: [String]?
    public let classification: String
    public let open_positions: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
}

// MARK: - Orderbook Runtime Truth

public struct OrderbookRuntimeTruth: Decodable, Sendable {
    public let generated_at: String?
    public let coinapi_expired_or_not_required: Bool
    public let direct_binance_active: Bool?
    public let direct_kucoin_active: Bool?
    public let direct_binance_kucoin_active: Bool
    public let symbols_covered: Int
    public let stale_symbols: [String]
    public let sequence_gaps: [String]
    public let direct_feed_coverage: OrderbookDirectFeedCoverage?
    public let configured_symbol_coverage: OrderbookConfiguredSymbolCoverage?
    public let trainer_consumes_orderbook: Bool
    public let risk_consumes_orderbook: Bool
    public let allocator_consumes_orderbook: Bool
    public let paper_fills_consume_orderbook: Bool
}

public struct OrderbookDirectFeedCoverage: Decodable, Sendable {
    public let binance_book_ticker_persisted: Bool?
    public let binance_partial_depth_5_10_20_persisted: Bool?
    public let binance_diff_depth_persisted: Bool?
    public let binance_100ms_depth_persisted: Bool?
    public let binance_250ms_depth_persisted: Bool?
    public let kucoin_best_5_50_persisted: Bool?
    public let kucoin_increment_best_500_persisted: Bool?
    public let kucoin_100ms_depth_persisted: Bool?
    public let kucoin_10ms_increment_persisted: Bool?
}

public struct OrderbookConfiguredSymbolCoverage: Decodable, Sendable {
    public let configured_symbol_count: Int?
    public let complete_symbols: [String]?
    public let incomplete_symbols: [String]?
    public let all_configured_symbols_have_required_direct_feed_coverage: Bool?
}

// MARK: - Microstructure Truth

public struct MicrostructureTruth: Decodable, Sendable {
    public let generated_at: String?
    public let live_gate: String
    public let coinapi_expired_or_not_required: Bool
    public let coinapi_not_required_to_solve_book_trust: Bool
    public let public_book_default_trust: String
    public let public_orderbook_default_trust_cap: Double?
    public let public_book_trust_live_ready: Bool?
    public let public_book_can_approve_trade_alone: Bool
    public let composite_microstructure_trust_required: Bool?
    public let final_a_plus_min_composite_trust: Double?
    public let final_a_plus_candidates: Int?
    public let reduced_size_bootstrap_tier: String?
    public let reduced_size_bootstrap_candidates: Int?
    public let reduced_size_bootstrap_paper_only: Bool?
    public let reduced_size_counts_as_final_a_plus: Bool?
    public let reduced_size_routes_to_live: Bool?
    public let direct_binance_kucoin_active: Bool
    public let symbols_covered: Int
    public let stale_symbols: [String]
    public let sequence_gaps: [String]
    public let trainer_consumes_microstructure: Bool
    public let risk_consumes_microstructure: Bool
    public let orchestrator_consumes_microstructure: Bool
    public let allocator_consumes_microstructure: Bool
    public let paper_fills_consume_microstructure: Bool
    public let why_candidate_blocked_visible: Bool
    public let why_candidate_is_not_final_a_plus_visible: Bool?
}

// MARK: - Risk

public struct MobileRiskStatus: Decodable, Sendable {
    public let generated_utc: String
    public let live_gate: LiveGateState
    public let performance: MobileRuntimePerformance?
    public let entry_freeze: MobileRuntimeEntryFreeze?
    public let a_plus_gate: MobileRuntimeAPlusGate?
    public let reduced_size_bootstrap: MobileRuntimeReducedSizeBootstrap?
    public let trainer_learning: MobileRuntimeTrainerLearning?
    public let real_trader_readiness: MobileRuntimeReadiness?
    public let market_data_freshness: MobileMarketDataFreshness?
    public let preemptive_edge_control: MobilePreemptiveEdgeControl?
    public let adaptive_hedge_cross_margin: MobileHedgeCrossMargin?
    public let provider_readiness: MobileProviderReadiness?
    public let top_blockers: [String]?
    public let hedge: MobileHedgeSnapshot?
    public let risk_state: String
    public let paper_blocked_count: Int
    public let paper_accepted_count: Int
    public let kill_switch_active: Bool
    public let max_position_size_usd: Double
    public let daily_loss_limit_usd: Double
    public let current_daily_loss_usd: Double
    public let dangerous_actions_require_human_approval: Bool
    public let mobile_can_approve_dangerous_actions: Bool
}

// MARK: - Paper Summary

public struct MobilePaperSummary: Decodable, Sendable {
    public let generated_utc: String
    public let mode: String
    public let places_real_order: Bool
    public let live_gate: String
    public let paper_session_id: String?
    public let paper_account_epoch: Int?
    public let scope: String?
    public let historical_rows_excluded_from_current_view: Int?
    public let historical_evidence_preserved: Bool?
    public let equity: Double?
    public let paper_equity: Double?
    public let paper_balance: Double?
    public let initial_capital: Double?
    public let starting_equity_usd: Double?
    public let performance: MobileRuntimePerformance?
    public let entry_freeze: MobileRuntimeEntryFreeze?
    public let a_plus_gate: MobileRuntimeAPlusGate?
    public let reduced_size_bootstrap: MobileRuntimeReducedSizeBootstrap?
    public let trainer_learning: MobileRuntimeTrainerLearning?
    public let real_trader_readiness: MobileRuntimeReadiness?
    public let market_data_freshness: MobileMarketDataFreshness?
    public let preemptive_edge_control: MobilePreemptiveEdgeControl?
    public let adaptive_hedge_cross_margin: MobileHedgeCrossMargin?
    public let provider_readiness: MobileProviderReadiness?
    public let top_blockers: [String]?
    public let loop: PaperLoop
    public let positions: PaperPositions
    public let position_pricing: PositionPricing?
    public let pnl: PaperPnL
    public let trainer_feedback: TrainerFeedback
    public var effectiveEquity: Double? { paper_equity ?? equity ?? paper_balance }
}

public struct PaperLoop: Decodable, Sendable {
    public let signals_seen: Int
    public let intents_built: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
    public let classification: String
    public let cycle_state: String?
    public let heartbeat_ttl_seconds: Int?
    public let candidate_id: String?
    public let policy_id: String?
    public let paper_policy_owner: String?
    public let policy_fingerprint: String?
    public let model_source: String?
    public let preemptive_edge_control: MobilePreemptiveEdgeControl?
    public let paper_only: Bool?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?
}

public struct PaperPositions: Decodable, Sendable {
    public let open_count: Int
    public let closed_count: Int
    public let positions_preview: [MobilePosition]
    public let account_scope: String?
    public let source_type: String?
    public let paper_or_live: String?
    public let contains_simulated_positions: Bool?
    public let contains_live_positions: Bool?
    public let contains_quarantined_positions: Bool?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let reason_if_untrusted: String?
    public let routes_to_live: Bool?
}

public struct PaperPnL: Decodable, Sendable {
    public let realized_usd: Double
    public let unrealized_usd: Double
    public let total_usd: Double
    public let win_rate_pct: Double?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let reason_if_untrusted: String?
}

public struct TrainerFeedback: Decodable, Sendable {
    public let outcome_labels: Int
    public let consumable_rows: Int
    public let quarantined_rows: Int
}

// MARK: - Admin

public struct MobileAdminSummary: Decodable, Sendable {
    public let generated_utc: String
    public let actor: AdminActor
    public let live_gate: LiveGateState
    public let trainer: AdminTrainer
    public let gpu: GPUState
    public let paper: AdminPaper
    public let risk: AdminRisk
    public let dangerous_controls_require_web_approval: Bool
    public let mobile_live_trading_blocked: Bool
}

public struct AdminActor:   Decodable, Sendable { public let user_id, email, role: String }
public struct AdminTrainer: Decodable, Sendable {
    public let state, checkpoint: String
    public let champion_challenger_status: ChampionChallengerStatus?
    public let cuda_active: Bool
    public let training_steps_total, training_steps_last_hour: Int
}
public struct AdminPaper: Decodable, Sendable {
    public let classification: String
    public let open_positions, closed_trades: Int
    public let realized_pnl_usd, unrealized_pnl_usd: Double
    public let intents_accepted, intents_blocked: Int
}
public struct AdminRisk: Decodable, Sendable { public let state: String; public let kill_switch_active: Bool }

// MARK: - Enterprise Realtime / UI Snapshots

public enum JSONValue: Decodable, Sendable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([String: JSONValue].self) {
            self = .object(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .null
        }
    }
}

public struct CanonicalPnL: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let generated_utc: String?
    public let display_time_et: String?
    public let source_timezone: String?
    public let display_timezone: String?
    public let paper_session_id: String?
    public let paper_account_epoch: Int?
    public let account_scope: String
    public let paper_equity_usd: Double?
    public let paper_realized_pnl_usd: Double?
    public let paper_unrealized_pnl_usd: Double?
    public let paper_total_pnl_usd: Double?
    public let equity_usd: Double?
    public let starting_equity_usd: Double?
    public let realized_net_pnl_usd: Double?
    public let unrealized_pnl_usd: Double?
    public let fees_usd: Double?
    public let slippage_usd: Double?
    public let funding_usd: Double?
    public let gross_pnl_usd: Double?
    public let net_pnl_usd: Double?
    public let closed_trade_count: Int?
    public let source: String?
    public let data_source: String?
    public let source_lag_seconds: Double?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let reconciliation_status: String
    public let reconciliation_delta_usd: Double?
    public let missing_fields: [String]?
    public let warnings: [String]?
    public let paper_only: Bool
    public let routes_to_live: Bool
    public let places_real_order: Bool
}

public struct EnterpriseProviderCard: Decodable, Sendable, Equatable {
    public let provider: String
    public let display_name: String?
    public let subscription_tier: String?
    public let status: String?
    public let dashboard_color: String?
    public let dashboard_color_reason: String?
    public let freshness_status: String?
    public let data_quality_status: String?
    public let actual_payload_count: Int?
    public let last_success_utc: String?
    public let last_error_utc: String?
    public let source_lag_seconds: Double?
    public let keys_published: [String]?
    public let feature_count: Int?
    public let consumer_count: Int?
    public let consumer_roles: [String]?
    public let symbols_covered: [String]?
    public let endpoints_active: [String]?
    public let endpoints_disabled: [String]?
    public let rate_limit_used: Double?
    public let rate_limit_remaining: Double?
    public let daily_quota_used: Double?
    public let monthly_quota_used: Double?
    public let heartbeat_only: Bool?
    public let actual_payload_present: Bool?
    public let raw_key_exposed: Bool?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?
    public let watchlist_count: Int?
    public let smart_wallet_candidate_count: Int?
    public let verified_smart_wallet_count: Int?
    public let token_map_count: Int?
    public let disabled_heatmap_endpoint: Bool?

    public var providerDashboardTone: String {
        let hasActualPayload = actual_payload_present == true || (actual_payload_count ?? 0) > 0 || (feature_count ?? 0) > 0
        let dashboardTone = Self.normalizedProviderTone(dashboard_color)
        let runtimeTone = Self.normalizedProviderTone(status)
            ?? Self.normalizedProviderTone(subscription_tier)
            ?? Self.normalizedProviderTone(data_quality_status)
            ?? Self.normalizedProviderTone(freshness_status)

        if dashboardTone == "red" || runtimeTone == "red" {
            return "red"
        }
        if heartbeat_only == true {
            return "yellow"
        }
        if hasActualPayload {
            if dashboardTone == "yellow" || runtimeTone == "yellow" {
                return "yellow"
            }
            if dashboardTone == "green" || runtimeTone == "green" {
                return "green"
            }
            return "yellow"
        }
        if dashboardTone == "green" || runtimeTone == "green" {
            return "yellow"
        }
        return dashboardTone ?? runtimeTone ?? "gray"
    }

    public var providerDashboardBadgeText: String {
        providerDashboardTone.uppercased()
    }

    private static func normalizedProviderTone(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let value = raw
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "-", with: "_")
        guard !value.isEmpty else { return nil }

        if ["green", "ready", "healthy", "ok", "online", "connected", "active", "fresh", "pass", "passing"].contains(value) {
            return "green"
        }
        if ["yellow", "partial", "degraded", "warning", "warn", "limited", "stale", "delayed", "pending", "recovering", "configured_no_watchlist", "partial_required_features_missing", "feature_bridge_partial"].contains(value) {
            return "yellow"
        }
        if ["red", "error", "failed", "failure", "down", "offline", "invalid", "critical"].contains(value) {
            return "red"
        }
        if ["gray", "grey", "unknown", "unavailable", "disabled", "not_configured", "unsupported", "plan_blocked", "no_key", "no_data"].contains(value) {
            return "gray"
        }
        if value.contains("fail") || value.contains("error") || value.contains("invalid") || value.contains("critical") {
            return "red"
        }
        if value.contains("partial") || value.contains("degraded") || value.contains("stale") || value.contains("pending") || value.contains("configured") {
            return "yellow"
        }
        if value.contains("ready") || value.contains("healthy") || value.contains("connected") {
            return "green"
        }
        if value.contains("disabled") || value.contains("unsupported") || value.contains("unknown") {
            return "gray"
        }
        return nil
    }
}

public struct EnterpriseProviderCards: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let providers: [EnterpriseProviderCard]
    public let provider_count: Int?
    public let heartbeat_only_green_count: Int?
    public let live_gate: String?
    public let paper_only: Bool?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?
}

public struct ControlCenterProviderStatus: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let generated_at_utc: String
    public let generated_at_et: String?
    public let source: String
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let canonical_owner: String
    public let live_gate: String
    public let places_real_order: Bool
    public let routes_to_live: Bool
    public let data_quality_status: String
    public let data: EnterpriseProviderCards

    public var isReadOnlyBlockedLive: Bool {
        live_gate == "blocked_human_only" && !places_real_order && !routes_to_live
    }
}

public struct ControlCenterLiveCanaryStatus: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let generated_at_utc: String
    public let generated_at_et: String?
    public let source: String
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let canonical_owner: String
    public let live_gate: String
    public let places_real_order: Bool
    public let routes_to_live: Bool
    public let data_quality_status: String
    public let data: ControlCenterLiveCanaryData

    public var isReadOnlyBlockedLive: Bool {
        live_gate == "blocked_human_only" && !places_real_order && !routes_to_live
    }
}

public struct ControlCenterLiveCanaryData: Decodable, Sendable, Equatable {
    public let selected_a_plus_candidate: String?
    public let why_none: String?
    public let dry_run: Bool?
    public let operator_approval_required: Bool?
    public let no_mutation_flags: ControlCenterNoMutationFlags?
}

public struct ControlCenterNoMutationFlags: Decodable, Sendable, Equatable {
    public let real_order_attempted: Bool?
    public let real_order_submitted: Bool?
    public let test_order_submitted: Bool?
    public let leverage_changed: Bool?
    public let margin_mode_changed: Bool?
    public let places_real_order: Bool?
    public let routes_to_live: Bool?

    public var hasNoExchangeMutation: Bool {
        !(real_order_attempted ?? false)
            && !(real_order_submitted ?? false)
            && !(test_order_submitted ?? false)
            && !(leverage_changed ?? false)
            && !(margin_mode_changed ?? false)
            && !(places_real_order ?? false)
            && !(routes_to_live ?? false)
    }
}

public struct ControlCenterAPlusInventoryStatus: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let generated_at_utc: String
    public let generated_at_et: String?
    public let source: String
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let canonical_owner: String
    public let live_gate: String
    public let places_real_order: Bool
    public let routes_to_live: Bool
    public let data_quality_status: String
    public let data: ControlCenterAPlusInventoryData

    public var isReadOnlyBlockedLive: Bool {
        live_gate == "blocked_human_only" && !places_real_order && !routes_to_live
    }
}

public struct ControlCenterAPlusInventoryData: Decodable, Sendable, Equatable {
    public let schema_version: String?
    public let generated_utc: String?
    public let paper_session_id: String?
    public let evaluated_candidates: Int?
    public let a_plus_candidates: Int?
    public let live_ready_rows: Int?
    public let counts_as_final_a_plus: Bool?
    public let b_grade_counts_as_final_a_plus: Bool?
    public let probation_counts_as_final_a_plus: Bool?
    public let full_candidate_count: Int?
    public let payload_compacted: Bool?
    public let candidate_matrix_preview: [ControlCenterAPlusCandidatePreview]?
    public let a_plus_preview: [ControlCenterAPlusCandidatePreview]?

    public var verifiedAPlusCount: Int {
        a_plus_candidates ?? a_plus_preview?.count ?? 0
    }
}

public struct ControlCenterAPlusCandidatePreview: Decodable, Sendable, Equatable {
    public let symbol: String?
    public let timeframe: String?
    public let side: String?
    public let strategy_id: String?
    public let bucket_key: String?
    public let a_plus: Bool?
    public let failed_checks: [String]?
    public let missing_evidence_checks: [String]?
    public let passed_check_count: Int?
    public let check_count: Int?
    public let generated_utc: String?
}

public struct ControlCenterCurrentSignalStatus: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let generated_at_utc: String
    public let generated_at_et: String?
    public let source: String
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let canonical_owner: String
    public let live_gate: String
    public let places_real_order: Bool
    public let routes_to_live: Bool
    public let data_quality_status: String
    public let data: ControlCenterCurrentSignalData

    public var isReadOnlyBlockedLive: Bool {
        live_gate == "blocked_human_only" && !places_real_order && !routes_to_live
    }
}

public struct ControlCenterCurrentSignalData: Decodable, Sendable, Equatable {
    public let active_signal: ControlCenterCurrentSignal?
    public let trader_id: String?
    public let paper_account_id: String?
    public let account_scope: String?
    public let account_specific: Bool?
    public let public_paper_signal: Bool?
}

public struct ControlCenterCurrentSignal: Decodable, Sendable, Equatable {
    public let symbol: String?
    public let timeframe: String?
    public let action: String?
    public let side: String?
    public let proposed_action: String?
    public let actionable: Bool?
    public let signal_id: String?
    public let prediction_id: String?
    public let confidence: Double?
    public let confidence_selected_action: Double?
    public let confidence_executable_trade: Double?
    public let confidence_display_label: String?
    public let confidence_type: String?
    public let confidence_a_plus_eligible: Bool?
    public let confidence_tradeability_block_reasons: [String]?
    public let paper_exploration_tier: String?
    public let exploration_tier: String?
    public let paper_exploration_current_blocker: String?
    public let paper_exploration_paper_fill_allowed: Bool?
    public let paper_exploration_risk_controller_decision: String?
    public let paper_exploration_orchestrator_decision: String?
    public let paper_exploration_allocator_decision: String?
    public let expected_net_pnl_usd: Double?
    public let expected_max_loss_usd: Double?
    public let why_not_a_plus: [String]?
    public let why_not_live_ready: [String]?
    public let risk_controller_decision: String?
    public let allocator_decision: String?
    public let trainer_feedback_status: String?
    public let live_gate: String?
    public let exchange_action_taken: Bool?
    public let exchange_call_invariant: String?
    public let market_age_seconds: Double?
    public let risk_result: String?
    public let blocked_reason: String?
}

public struct EnterpriseUiSnapshot: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let resource: String
    public let generated_utc: String
    public let display_time_et: String?
    public let source_timezone: String?
    public let display_timezone: String?
    public let source: String
    public let source_type: String
    public let source_keys: [String]
    public let staleness_seconds: Double?
    public let data_quality: String
    public let missing_sections: [String]
    public let error_sections: [String]
    public let last_good_payload_used: Bool
    public let payload: JSONValue?
    public let live_gate: String?
    public let paper_only: Bool?
    public let routes_to_live: Bool
    public let places_real_order: Bool
}

public struct EnterpriseRealtimeBootstrap: Decodable, Sendable, Equatable {
    public let schema_version: String
    public let generated_utc: String
    public let display_time_et: String?
    public let display_timezone: String?
    public let source: String?
    public let auth: [String: JSONValue]?
    public let portfolio: JSONValue?
    public let paper: JSONValue?
    public let risk: JSONValue?
    public let trainer: JSONValue?
    public let signals: JSONValue?
    public let providers: JSONValue?
    public let ingestors: JSONValue?
    public let markets: JSONValue?
    public let live_canary: JSONValue?
    public let alerts: JSONValue?
    public let ui_hints: [String: JSONValue]?
    public let resources: [String: EnterpriseUiSnapshot]
    public let live_gate: String?
    public let paper_only: Bool?
    public let routes_to_live: Bool
    public let places_real_order: Bool
}

public struct EnterpriseRealtimeFrame: Decodable, Sendable, Equatable {
    public let type: String
    public let resource: String?
    public let sequence: Int
    public let generated_utc: String
    public let display_time_et: String?
    public let payload: JSONValue?
}

// MARK: - AI prediction missing-feature alert (from /api/v2/predictions/explain)
// The prediction is always produced (absent features are masked, not zero-filled).
// This surfaces exactly what is degraded and how severe, without blocking anything.
public struct AIPredictionMissingFeatureAlert: Decodable, Sendable, Equatable {
    public let active: Bool
    public let severity: String
    public let operational: Bool
    public let prediction_still_produced: Bool
    public let data_coverage_pct: Double?
    public let missing_feature_count: Int
    public let stale_feature_count: Int
    public let missing_by_category: [String: Int]
    public let missing_provider_names: [String]
    public let message: String
}

// MARK: - Backtest + replay-feedback results (from /api/v2/replay/backtest)
public struct PolicyBacktest: Decodable, Sendable, Equatable {
    public let win_rate: Double?
    public let profit_factor_proxy: Double?
    public let expectancy_after_cost_bps: Double?
    public let rows_evaluated: Int?
    public let status: String?
    public let evidence_class: String?
}

public struct BacktestGeneralization: Decodable, Sendable, Equatable {
    public let validation_supervised_loss: Double?
    public let validation_rows_evaluated: Int?
    public let train_val_generalization_gap: Double?
    public let overfit_gap_warning: Bool?
    public let loss_before: Double?
    public let loss_after: Double?
}

public struct ReplayFeedback: Decodable, Sendable, Equatable {
    public let existing_counterfactual_rows: Int?
    public let new_matured_rows: Int?
    public let pending_rows: Int?
    public let trainer_loader_consumes: Bool?
}

public struct BacktestResults: Decodable, Sendable, Equatable {
    public let available: Bool
    public let generated_utc: String?
    public let effective_trainer_mode: String?
    public let replay_examples_built: Int?
    public let backtest_is_a_plus_evidence: Bool
    public let continuous_replay_active: Bool?
    public let policy_backtest: PolicyBacktest?
    public let generalization: BacktestGeneralization?
    public let replay_feedback: ReplayFeedback?
}

// MARK: - Website-parity models (Markets / Goal / Portfolio / Trainer deep / Derivatives / Matrix)
// Same shapes as the AIBotV2 app target; kept in Core so the Linux CLI and
// tests can decode the parity surfaces and validate the contracts.

public struct MarketTicker: Decodable, Sendable {
    public let symbol: String
    public let last_price: Double?
    public let mark_price: Double?
    public let index_price: Double?
    public let change_24h: Double?
    public let high_24h: Double?
    public let low_24h: Double?
    public let volume_24h: Double?
    public let turnover_24h: Double?
    public let funding_rate: Double?
    public let open_interest: Double?
    public let long_short_ratio: Double?
    public let source: String?
    public let event_time: String?
    public let candle_closed_confirmed: Bool?
    public let display_only_current_candle: Bool?
}

public struct MarketOverviewData: Decodable, Sendable {
    public let symbols: [String]?
    public let count: Int?
    public let timeframes: [String]?
    public let tickers: [MarketTicker]
    public let canonical_runtime_source: String?
}

public struct MarketOverviewResponse: Decodable, Sendable {
    public let schema_version: String?
    public let data: MarketOverviewData
    public let source: String?
    public let source_type: String?
    public let generated_at_utc: String?
    public let lag_ms: Double?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let stale: Bool?
    public let live_gate: String?
}

public struct GoalGrowthStage: Decodable, Sendable {
    public let stage: String?
    public let stage_order: [String]?
    public let closes_24h: Int?
    public let rolling_25_pf: Double?
    public let rolling_25_weighted_bps: Double?
    public let rate_formula: String?
    public let edge_repair_exit: String?
    public let throughput_exit: String?
    public let scale_exit: String?
}

public struct GoalBindingConstraint: Decodable, Sendable {
    public let constraint: String?
    public let detail: String?
}

public struct GoalTrajectoryData: Decodable, Sendable {
    public let objective: String?
    public let multiple_now: Double?
    public let target_multiple: Double?
    public let target_days: Double?
    public let days_elapsed: Double?
    public let required_daily_rate_pct: Double?
    public let actual_daily_rate_pct: Double?
    public let on_track: Bool?
    public let growth_stage: GoalGrowthStage?
    public let binding_constraint: GoalBindingConstraint?
    public let equity_gap_vs_required_usd: Double?
    public let days_to_target_at_required_rate_from_here: Double?
    public let required_equity_today_usd: Double?
    public let equity_usd: Double?
    public let starting_equity_usd: Double?
    public let realized_pnl_usd: Double?
    public let unrealized_pnl_usd: Double?
    public let closed_trade_count: Int?
    public let open_position_count: Int?
    public let paper_session_id: String?
    public let session_started_utc: String?
    public let generated_utc: String?
    public let live_gate: String?
    public let paper_only: Bool?
    public let places_real_order: Bool?
    public let is_stale: Bool?
    public let age_seconds: Double?
}

public struct GoalTrajectoryResponse: Decodable, Sendable {
    public let schema_version: String?
    public let data: GoalTrajectoryData
    public let source: String?
    public let generated_at_utc: String?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let live_gate: String?
    public let places_real_order: Bool?
}

public struct PortfolioCanonicalData: Decodable, Sendable {
    public let pnl_source_key: String?
    public let pnl_source_type: String?
    public let equity: Double?
    public let paper_equity_usd: Double?
    public let available_balance_usd: Double?
    public let starting_equity_usd: Double?
    public let initial_capital: Double?
    public let realized_net_pnl_usd: Double?
    public let realized_gross_pnl_usd: Double?
    public let realized_pnl_usd: Double?
    public let unrealized_pnl_usd: Double?
    public let total_pnl_usd: Double?
    public let open_position_count: Int?
    public let closed_trade_count: Int?
    public let total_open_notional: Double?
    public let paper_session_id: String?
    public let paper_account_epoch: Int?
    public let scope: String?
    public let historical_rows_excluded_from_current_view: Int?
    public let historical_evidence_preserved: Bool?
    public let mode: String?
    public let paper_or_live: String?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let pnl_conflict_detected: Bool?
    public let freshness_status: String?
    public let staleness_seconds: Double?
    public let source_generated_utc: String?
}

public struct PortfolioCanonicalResponse: Decodable, Sendable {
    public let schema_version: String?
    public let data: PortfolioCanonicalData
    public let source: String?
    public let source_type: String?
    public let generated_at_utc: String?
    public let lag_ms: Double?
    public let stale: Bool?
    public let live_gate: String?
    public let mode: String?
}

public struct TrainerGPURuntime: Decodable, Sendable {
    public let gpu_name: String?
    public let cuda_available: Bool?
    public let model_device: String?
    public let current_vram_used_mb: Double?
    public let vram_reserved_mb: Double?
    public let vram_cap_mb: Double?
    public let gpu_utilization_limit_percent: Double?
    public let gpu_train_time_ms: Double?
    public let data_loader_time_ms: Double?
    public let backtest_rows_per_second: Double?
    public let throughput_predictions_per_second: Double?
    public let training_steps_per_minute: Double?
    public let mixed_precision_enabled: Bool?
    public let oom_count: Double?
    public let target_batch_size: Double?
    public let actual_batch_size: Double?
}

public struct TrainerModelEdgeBacktest: Decodable, Sendable {
    public let win_rate: Double?
    public let expectancy_after_cost_bps: Double?
    public let profit_factor_proxy: Double?
    public let rows_evaluated: Double?
    public let a_plus_readiness_signal: String?
    public let evidence_class: String?
    public let status: String?
}

public struct TrainerRuntimeMode: Decodable, Sendable {
    public let effective_trainer_mode: String?
    public let online_learning_status: String?
    public let cuda_inference_status: String?
    public let trainer_process_status: String?
    public let prediction_publication_status: String?
    public let prediction_examples_built: Double?
    public let prediction_failure_count: Double?
    public let replay_buffer_size: Double?
    public let replay_buffer_limit: Double?
    public let symbols_count: Double?
    public let timeframes: [String]?
    public let examples_built: Double?
    public let paper_shadow_only: Bool?
    public let checkpoint_promoted_this_cycle: Bool?
    public let checkpoint_promotion_reason: String?
}

public struct TrainerLearningMetricsExtra: Decodable, Sendable {
    public let train_val_generalization_gap: Double?
    public let validation_loss_delta: Double?
    public let validation_supervised_loss: Double?
    public let validation_supervised_loss_before: Double?
    public let validation_supervised_loss_after: Double?
    public let loss_after: Double?
    public let overfit_gap_warning: Bool?
}

public struct TrainerOfflinePretrainStatus: Decodable, Sendable {
    public let generated_utc: String?
    public let phase: String?
    public let promoted: Bool?
    public let auto_promote: Bool?
    public let require_risk_gate: Bool?
    public let duration_seconds: Double?
    public let h2l_decision: String?
    public let sortino_offline: Double?
    public let cvar_offline: Double?
}

public struct TrainerDeepStatus: Decodable, Sendable {
    public let state: String?
    public let checkpoint_id: String?
    public let model_id: String?
    public let model_source: String?
    public let cuda_active: Bool?
    public let data_coverage: Double?
    public let uptime_days: Double?
    public let win_rate_30d: Double?
    public let episodes_total: Int?
    public let drift_watch_count: Int?
    public let drift_alarm_count: Int?
    public let runtime_mode: TrainerRuntimeMode?
    public let gpu_runtime: TrainerGPURuntime?
    public let model_edge_backtest: TrainerModelEdgeBacktest?
    public let learning_metrics_extra: TrainerLearningMetricsExtra?
    public let offline_pretrain_status: TrainerOfflinePretrainStatus?
    public let champion_challenger_status: ChampionChallengerStatus?
    public let generated_at_utc: String?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let live_gate: String?
    public let exact_no_live_reason: String?
    public let readiness_blockers: [String]?
    public let live_ready: Bool?
}

public struct DerivativesAggregate: Decodable, Sendable {
    public let total_oi_usd: Double?
    public let total_liq_24h: Double?
    public let avg_funding: Double?
    public let aggregate_long_short_ratio: Double?
    public let funding_positive_count: Int?
    public let funding_negative_count: Int?
}

public struct DerivativesGlobalRegime: Decodable, Sendable {
    public let market_sentiment: Double?
    public let avg_funding_rate: Double?
    public let aggregate_long_short_ratio: Double?
    public let total_open_interest_usd: Double?
    public let total_liquidations_usd: Double?
    public let total_volume_usd: Double?
    public let data_status: String?
    public let is_fresh: Bool?
    public let age_seconds: Double?
}

public struct DerivativesSymbolRow: Decodable, Sendable {
    public let symbol: String
    public let funding_rate: Double?
    public let oi_usd: Double?
    public let long_short_ratio: Double?
    public let basis_bps: Double?
    public let cascade_risk: Double?
    public let mark_price: Double?
}

public struct MobileDerivativesSummary: Decodable, Sendable {
    public let schema_version: String?
    public let generated_utc: String?
    public let payload_generated_utc: String?
    public let live_gate: String?
    public let places_real_order: Bool?
    public let aggregate: DerivativesAggregate?
    public let global_regime: DerivativesGlobalRegime?
    public let top_symbols: [DerivativesSymbolRow]?
    public let symbol_count: Int?
    public let source: String?
    public let freshness_status: String?
    public let staleness_seconds: Double?
}

public struct SignalMatrixCell: Decodable, Sendable {
    public let s: String
    public let tf: String
    public let a: String?
    public let c: Double?
    public let act: Bool?
    public let g: String?
}

public struct MobileSignalMatrix: Decodable, Sendable {
    public let schema_version: String?
    public let generated_utc: String?
    public let payload_generated_utc: String?
    public let live_gate: String?
    public let timeframes: [String]?
    public let symbol_count: Int?
    public let cell_count: Int?
    public let actionable_count: Int?
    public let cells: [SignalMatrixCell]
    public let source: String?
    public let freshness_status: String?
    public let staleness_seconds: Double?
}

public struct PredictionAccuracyTimeframe: Decodable, Sendable {
    public let timeframe: String
    public let evaluated_count: Int?
    public let correct_count: Int?
    public let incorrect_count: Int?
    public let accuracy: Double?
}

public struct SignalPredictionAccuracy: Decodable, Sendable {
    public let accuracy_definition: String?
    public let overall_accuracy: Double?
    public let evaluated_row_count: Int?
    public let correct_count: Int?
    public let incorrect_count: Int?
    public let by_timeframe: [PredictionAccuracyTimeframe]?
}

public struct PnLWindow: Decodable, Sendable {
    public let window: String
    public let realized_pnl_usd: Double?
    public let closed_trade_count: Int?
    public let winning_trade_count: Int?
    public let losing_trade_count: Int?
    public let win_rate: Double?
    public let profit_factor: Double?
}

public struct DataFeedSurface: Decodable, Sendable {
    public let name: String
    public let endpoint: String?
    public let status: String?
    public let description: String?
    public let actual_payload_count: Int?
    public let source_type: String?
    public let stale: Bool?
    public let lag_ms: Double?
    public let last_success: String?
}

public struct DataHealthData: Decodable, Sendable {
    public let overall: String?
    public let surfaces: [DataFeedSurface]?
    public let count: Int?
}

public struct DataHealthResponse: Decodable, Sendable {
    public let schema_version: String?
    public let data: DataHealthData
    public let generated_at_utc: String?
    public let stale: Bool?
    public let live_gate: String?
}
