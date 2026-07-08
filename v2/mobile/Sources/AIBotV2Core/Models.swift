import Foundation

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
    public let equity: Double?
    public let paper_equity: Double?
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
    public let unrealized_pnl_usd: Double
    public let signals_seen: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
    public let classification: String
    public let places_real_order: Bool
    public var total_pnl: Double { realized_pnl_usd + unrealized_pnl_usd }
    public var effectiveEquity: Double? { paper_equity ?? equity ?? paper_balance }
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
    public let live_ready: Bool?
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
    public let actionable: Bool
    public let risk_state: String
    public let paper_fill_status: String
    public let published_at: String
    public var confidencePct: String { "\(Int(confidence * 100))%" }
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

// MARK: - Health

public struct MobileHealth: Decodable, Sendable {
    public let generated_utc: String
    public let overall: String
    public let redis_connected: Bool
    public let trainer: HealthTrainer
    public let gpu: HealthGPU
    public let paper: HealthPaper
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
