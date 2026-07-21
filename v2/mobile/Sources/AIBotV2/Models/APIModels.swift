import Foundation

public func nervyxPublicRuntimeText(_ value: String) -> String {
    let cleaned = value
        .replacingOccurrences(of: "blocked_human_only", with: "operator gated", options: .caseInsensitive)
        .replacingOccurrences(of: "LIVE TRADING BLOCKED", with: "OPERATOR GATED", options: .caseInsensitive)
        .replacingOccurrences(of: "PAPER_FILL_GATE_", with: "", options: .caseInsensitive)
        .replacingOccurrences(of: "PAPER_LEDGER_", with: "", options: .caseInsensitive)
        .replacingOccurrences(of: "PAPER_SHADOW_", with: "", options: .caseInsensitive)
        .replacingOccurrences(of: "paper account", with: "account", options: .caseInsensitive)
        .replacingOccurrences(of: "paper fill", with: "execution fill", options: .caseInsensitive)
        .replacingOccurrences(of: "paper", with: "runtime", options: .caseInsensitive)
        .replacingOccurrences(of: "_", with: " ")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    return cleaned.isEmpty ? "—" : cleaned
}

// MARK: - Dashboard

public struct MobileDashboard: Decodable, Equatable {
    public let generated_utc: String
    public let live_gate: LiveGateState
    public let paper: PaperState
    public let trainer: TrainerState
    public let gpu: GPUState
    public let alerts_preview: [MobileAlert]
    public let redis_connected: Bool
    public let active_signal_count: Int?
}

public struct LiveGateState: Decodable, Equatable {
    public let live_trading_enabled: Bool
    public let places_real_order: Bool
    public let gate: String
    public let label: String

    public var publicLabel: String { nervyxPublicRuntimeText(label).uppercased() }
    public var publicGate: String { nervyxPublicRuntimeText(gate).uppercased() }
    public var exchangeRouteLabel: String { places_real_order ? "EXCHANGE LIVE" : "OPERATOR GATED" }
}

public struct EquityPoint: Decodable, Equatable {
    public let t: String?
    public let cumulative_pnl: Double?
    public let pnl: Double?
}

public struct PaperState: Decodable, Equatable {
    public let paper_session_id: String?
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
    // Chart series (emitted by the mobile dashboard from v2:paper:closed_trades).
    public let equity_curve: [EquityPoint]?
    public let win_rate: Double?
    public let win_count: Int?
    public let loss_count: Int?

    public var total_pnl: Double { paper_total_pnl_usd ?? realized_pnl_usd + unrealized_pnl_usd }
    /// Cumulative-equity values (starting capital + running realized PnL) for the trend chart.
    public var equityTrend: [Double] {
        guard let curve = equity_curve, !curve.isEmpty else { return [] }
        let base = starting_equity_usd ?? initial_capital ?? ((effectiveEquity ?? 0) - (curve.last?.cumulative_pnl ?? 0))
        return [base] + curve.map { base + ($0.cumulative_pnl ?? 0) }
    }
    public var perTradePnl: [Double] { (equity_curve ?? []).map { $0.pnl ?? 0 } }
    public var effectiveEquity: Double? { paper_equity_usd ?? paper_equity ?? equity ?? paper_balance }
    public var acceptanceRate: Double {
        let total = intents_accepted + intents_blocked
        guard total > 0 else { return 0 }
        return Double(intents_accepted) / Double(total) * 100
    }
}

public struct MobileRuntimePerformance: Decodable, Equatable {
    public let profit_factor: Double?
    public let expectancy_usd: Double?
    public let realized_pnl_usd: Double?
    public let notional_weighted_expectancy_bps: Double?
    public let win_rate: Double?
    public let closed_outcome_count: Int?
    public let governor_state: String?
}

public struct MobileRuntimeEntryFreeze: Decodable, Equatable {
    public let new_entries_allowed: Bool?
    public let halt_reasons: [String]?
    public let future_gate_blockers: [String]?
    public let allow_close: Bool?
    public let allow_reduce: Bool?
}

public struct MobileRuntimeAPlusGate: Decodable, Equatable {
    public let evaluated_candidates: Int?
    public let a_plus_candidates: Int?
    public let rejected_reason_matrix: [String: Int]?
    public let gate_is_hard_entry_condition: Bool?
}

public struct MobileRuntimeReducedSizeBootstrap: Decodable, Equatable {
    public let final_a_plus_candidates: Int?
    public let reduced_size_bootstrap_candidates: Int?
    public let closed_rows: Int?
    public let counts_as_final_a_plus: Bool?
    public let b_grade_counts_as_final_a_plus: Bool?
    public let routes_to_live: Bool?
    public let paper_only: Bool?
    public let generated_at: String?
}

public struct MobileRuntimeTrainerLearning: Decodable, Equatable {
    public let effective_trainer_mode: String?
    public let online_learning_status: String?
    public let last_successful_weight_update_at: String?
    public let checkpoint_id: String?
}

public struct MobileRuntimeReadiness: Decodable, Equatable {
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

public struct MobileMarketDataFreshness: Decodable, Equatable {
    public let source: String?
    public let generated_at: String?
    public let age_seconds: Int?
    public let freshness_state: String?
}

public struct MobileAdvancedIndicators: Decodable, Equatable {
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

public struct MobilePreemptiveEdgeControl: Decodable, Equatable {
    public let status: String?
    public let preemptive_decision_id: String?
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

public struct MobileHedgeCrossMargin: Decodable, Equatable {
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

public struct MobileHedgeCandidate: Decodable, Equatable {
    public let symbol: String?
    public let side: String?
    public let unrealized_pnl_usd: Double?
}

public struct MobileHedgeSnapshot: Decodable, Equatable {
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

public struct MobileIngestorRollup: Decodable, Equatable {
    public let schema_version: String?
    public let overall_status: String?
    public let stream_present: [String: Bool]?
    public let all_core_streams_present: Bool?
    public let provider_count: Int?
    public let active_provider_count: Int?
    public let stale_provider_count: Int?
    public let stale_providers: [String]?
}

public struct MobileProviderReadiness: Decodable, Equatable {
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

public struct TrainerState: Decodable, Equatable {
    public let state: String
    public let checkpoint: String
    public let model_source: String
    public let champion_challenger_status: ChampionChallengerStatus?
    public let cuda_active: Bool
    public let data_coverage: Double
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
    public let device: String?
    public let gpu_name: String?
    // Model-identity truths (temporal-era backend fields; optional so older
    // backend payloads still decode).
    public let model_id: String?
    public let input_dim: Int?
    public let feature_count: Int?
    public let temporal_encoder: String?
    public let temporal_encoder_enabled: Bool?
    // Online-learning + model-edge + GPU throughput truths (optional so older
    // backend payloads still decode).
    public let effective_trainer_mode: String?
    public let online_learning_status: String?
    public let weights_updating: Bool?
    public let trainer_process_status: String?
    public let backtest_win_rate: Double?
    public let backtest_expectancy_bps: Double?
    public let backtest_profit_factor: Double?
    public let throughput_predictions_per_second: Double?
    public let vram_used_mb: Double?
    public let generalization_gap: Double?
    public let validation_loss_delta: Double?

    public var isActive: Bool {
        state.uppercased().contains("ACTIVE")
            || (online_learning_status?.uppercased() == "WEIGHTS_UPDATING")
            || (trainer_process_status?.uppercased() == "ACTIVE")
    }
    public var learningLabel: String {
        if weights_updating == true || online_learning_status?.uppercased() == "WEIGHTS_UPDATING" { return "WEIGHTS UPDATING" }
        guard let s = online_learning_status, !s.isEmpty else { return "—" }
        return s.replacingOccurrences(of: "_", with: " ")
    }
    public var temporalLabel: String {
        guard temporal_encoder_enabled == true else { return "single-frame" }
        let name = (temporal_encoder ?? "").isEmpty ? "ON" : temporal_encoder!.uppercased()
        return name
    }
    public var shortState: String {
        let s = state.replacingOccurrences(of: "_", with: " ")
        return s.count > 20 ? String(s.prefix(20)) + "…" : s
    }
    public var shortCheckpoint: String {
        guard !checkpoint.isEmpty else { return "—" }
        let parts = checkpoint.split(separator: "_")
        if parts.count >= 2 { return parts.suffix(2).joined(separator: "_") }
        return String(checkpoint.suffix(16))
    }
}

public struct ChampionChallengerStatus: Decodable, Equatable {
    public let status: String?
    public let result_status: String?
    public let best_challenger_id: String?
    public let promotion_allowed: Bool?
    public let promotion_reason: String?
    public let paper_challenger_enabled: Bool?
    public let replay_windows_processed: Int?
    public let replay_snapshots_scanned: Int?
    /// Exact runtime blocker chain (additive; absent on older payloads).
    public let blocker_reasons: [String]?
    public let evaluated_at_utc: String?

    public var displayStatus: String {
        (status ?? "MISSING_RUNTIME_EVIDENCE").replacingOccurrences(of: "_", with: " ")
    }

    /// True when the champion/challenger evaluation has real runtime evidence
    /// (the publisher ran and wrote the Redis key).
    public var hasEvidence: Bool {
        guard let value = status?.uppercased() else { return false }
        return !value.isEmpty && value != "MISSING_RUNTIME_EVIDENCE" && value != "INVALID_RUNTIME_EVIDENCE"
    }

    /// True when the challenger passed its untouched-holdout gate and is running
    /// as a paper (B-grade) challenger. Live/A-grade promotion is a SEPARATE,
    /// human-gated step — being paper-ready is the healthy operating state.
    public var isPaperReady: Bool {
        let s = (status ?? "").uppercased()
        let r = (result_status ?? "").uppercased()
        return paper_challenger_enabled == true
            || r.contains("PASSED")
            || s.contains("PAPER_READY")
    }

    /// Compact, honest challenger label for the dashboard.
    public var challengerLabel: String {
        if !hasEvidence { return "AWAITING EVIDENCE" }
        if isPaperReady { return "PAPER-READY" }
        return displayStatus.uppercased()
    }

    /// Honest promotion label. Live/A-grade promotion stays operator-gated by
    /// design, so a paper-ready challenger reads as "OPERATOR-GATED", not a
    /// scary "BLOCKED".
    public var promotionLabel: String {
        if promotion_allowed == true { return "ALLOWED" }
        if !hasEvidence { return "AWAITING EVIDENCE" }
        if isPaperReady { return "OPERATOR-GATED" }
        return "EDGE NOT PROVEN"
    }
}

public struct GPUState: Decodable, Equatable {
    public let name: String
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public let device: String?

    public var vramPercent: Double {
        guard vram_total_mb > 0 else { return 0 }
        return Double(vram_used_mb) / Double(vram_total_mb) * 100
    }
    public var vramUsedGB: Double { Double(vram_used_mb) / 1024 }
    public var vramTotalGB: Double { Double(vram_total_mb) / 1024 }
    public var displayName: String {
        if !name.isEmpty { return name }
        if let d = device, !d.isEmpty { return d }
        return "No GPU"
    }
}

// MARK: - Position

public struct MobilePosition: Decodable, Identifiable, Equatable {
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
    public var isBuy: Bool { side.lowercased() == "long" || side.lowercased() == "buy" }
    public var pnlSign: String { total_pnl >= 0 ? "+" : "" }
    public var shortSymbol: String {
        symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
    }
}

public struct PositionDecisionReasoning: Decodable, Equatable {
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

public struct MobilePositionsResponse: Decodable {
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

public struct PositionPricing: Decodable, Equatable {
    public let unrealized_pnl_usd: Double?
    public let total_open_notional: Double?
    public let mark_to_market_live: Bool?
    public let live_mark_price_count: Int?
    public let stale_mark_price_count: Int?
    public let missing_mark_price_count: Int?
}

public struct PositionSummary: Decodable, Equatable {
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

public struct MobileSignal: Decodable, Identifiable, Equatable {
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
    public let last_price: Double?
    public let expected_move_bps: Double?
    public let data_coverage: Double?
    public let model_version: String?
    public let checkpoint_id: String?

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
    public var isDirectional: Bool { action.lowercased() != "hold" }
    public var shortSymbol: String {
        symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
    }
    public var shortFillStatus: String {
        nervyxPublicRuntimeText(paper_fill_status).uppercased()
    }
}

public struct MobileSignalsResponse: Decodable {
    public let generated_utc: String
    public let signals: [MobileSignal]
    public let total_returned: Int
    public let actionable_only: Bool
}

// MARK: - Alert

public struct MobileAlert: Decodable, Identifiable, Equatable {
    public let id: String
    public let symbol: String
    public let type: String
    public let message: String
    public let severity: String
    public let triggered_at: String
}

public struct MobileAlertsResponse: Decodable {
    public let generated_utc: String
    public let alerts: [MobileAlert]
    public let total_returned: Int
}

// MARK: - Enterprise Control Center Status

public struct EnterpriseProviderCard: Decodable, Equatable {
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
            .replacingOccurrences(of: " ", with: "_")
        guard !value.isEmpty else { return nil }

        if value.contains("not_ready") || value.contains("blocked") {
            return "yellow"
        }
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

public struct EnterpriseProviderCards: Decodable, Equatable {
    public let schema_version: String
    public let providers: [EnterpriseProviderCard]
    public let provider_count: Int?
    public let heartbeat_only_green_count: Int?
    public let live_gate: String?
    public let paper_only: Bool?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?
}

public struct ControlCenterProviderStatus: Decodable, Equatable {
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

// MARK: - Ingestor status (/api/v2/ingestors/status)

public struct IngestorRowModel: Decodable, Equatable, Identifiable {
    public let name: String
    public let title: String?
    public let redis_pattern: String?
    public let key_count: Int?
    public let sampled_payloads: Int?
    public let upstream_error_payloads: Int?
    public let newest_event_age_seconds: Double?
    public let live_within_seconds: Double?
    public let status: String
    public let provider_current: Bool?
    public let provider_usable: Bool?
    public let provider_unusable_reason: String?

    public var id: String { name }
    public var displayTitle: String { title ?? name }
}

public struct IngestorCounts: Decodable, Equatable {
    public let total: Int?
    public let live: Int?
    public let stale: Int?
    public let offline: Int?
    public let not_started: Int?
}

public struct IngestorStatusData: Decodable, Equatable {
    public let ingestors: [IngestorRowModel]
    public let counts: IngestorCounts?
}

public struct IngestorStatusResponse: Decodable, Equatable {
    public let schema_version: String?
    public let data: IngestorStatusData
    public let source: String?
    public let source_type: String?
    public let generated_at_utc: String?
    public let freshness_status: String?
    public let stale: Bool?
    public let live_gate: String?
}

// MARK: - Self-healing supervisor (/api/v2/self-healing/status)

public struct SelfHealingService: Decodable, Equatable, Identifiable {
    public let name: String?
    public let unit: String?
    public let category: String?
    public let criticality: String?
    public let action: String?
    public let active_state: String?
    public let reason: String?
    public let heartbeat_age_seconds: Double?
    public let max_staleness_seconds: Double?

    public var id: String { unit ?? name ?? UUID().uuidString }

    /// Traffic-light tone derived from the supervisor's heal action.
    public var tone: String {
        let a = (action ?? "").uppercased()
        if a == "OK" || a.hasPrefix("SKIP_DELIBERATELY") || a == "SKIP_NOT_ENABLED"
            || a == "SKIP_NOT_INSTALLED" || a == "SKIP_DENYLISTED" { return "ok" }
        if a == "RESTART_DEAD" || a == "RESTART_STALE" || a == "STALE_PENDING" { return "warn" }
        if a == "SKIP_RATE_LIMITED" || a.hasPrefix("ALERT") { return "error" }
        let s = (active_state ?? "").lowercased()
        return (s == "active" || s == "activating" || s == "reloading") ? "ok" : "error"
    }
}

public struct SelfHealingBanner: Decodable, Equatable {
    public let show: Bool
    public let severity: String
    public let count: Int
    public let services: [SelfHealingService]
    public let message: String
}

public struct SelfHealingStatus: Decodable, Equatable {
    public let available: Bool
    public let generated_utc: String?
    public let supervisor_stale: Bool?
    public let supervisor_age_seconds: Double?
    public let component_count: Int?
    public let healthy_count: Int?
    public let unhealthy_count: Int?
    public let restarted_units: [String]?
    public let decisions: [SelfHealingService]?
    public let banner: SelfHealingBanner

    public var isHealthy: Bool { !(banner.show) || banner.severity == "ok" }
}

// MARK: - Per-ingestor metrics (/api/v2/ingestors/{name}/metrics)

public struct IngestorMetricRow: Decodable, Equatable, Identifiable {
    public let key: String?
    public let symbol: String
    public let age_seconds: Double?
    public let last_price: Double?
    public let volume_24h_quote: Double?
    public let price_change_pct: Double?
    public let numeric_fields: [String: Double]?

    public var id: String { key ?? symbol }
}

public struct IngestorMetricsData: Decodable, Equatable {
    public let ingestor: String
    public let title: String?
    public let redis_pattern: String?
    public let rows: [IngestorMetricRow]
}

public struct IngestorMetricsResponse: Decodable, Equatable {
    public let data: IngestorMetricsData?
    public let source: String?
    public let source_type: String?
    public let timestamp: String?
    public let stale: Bool?
}

public struct ControlCenterLiveCanaryStatus: Decodable, Equatable {
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

public struct ControlCenterLiveCanaryData: Decodable, Equatable {
    public let selected_a_plus_candidate: String?
    public let why_none: String?
    public let dry_run: Bool?
    public let operator_approval_required: Bool?
    public let no_mutation_flags: ControlCenterNoMutationFlags?
}

public struct ControlCenterNoMutationFlags: Decodable, Equatable {
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

public struct ControlCenterAPlusInventoryStatus: Decodable, Equatable {
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

public struct ControlCenterAPlusInventoryData: Decodable, Equatable {
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

public struct ControlCenterAPlusCandidatePreview: Decodable, Equatable {
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

public struct ControlCenterCurrentSignalStatus: Decodable, Equatable {
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

public struct ControlCenterCurrentSignalData: Decodable, Equatable {
    public let active_signal: ControlCenterCurrentSignal?
    public let trader_id: String?
    public let paper_account_id: String?
    public let account_scope: String?
    public let account_specific: Bool?
    public let public_paper_signal: Bool?
}

public struct ControlCenterCurrentSignal: Decodable, Equatable {
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

// MARK: - Auth Health

public struct AuthHealth: Decodable, Equatable {
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

public struct AuthHealthSessionSecurity: Decodable, Equatable {
    public let cookie_name: String?
    public let token_type: String?
    public let http_only_cookie: Bool?
    public let secure_cookie: Bool?
    public let same_site: String?
}

// MARK: - Health

public struct MobileHealth: Decodable, Equatable {
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

public struct HealthTrainer: Decodable, Equatable {
    public let state: String
    public let cuda_active: Bool
    public let training_active: Bool
    public let checkpoint: String
    public let champion_challenger_status: ChampionChallengerStatus?
    public let device: String?
    public let gpu_name: String?
    public let model_id: String?
    public let input_dim: Int?
    public let feature_count: Int?
    public let temporal_encoder: String?
    public let temporal_encoder_enabled: Bool?

    public var shortState: String {
        let s = state.replacingOccurrences(of: "_", with: " ")
        return s.count > 22 ? String(s.prefix(22)) + "…" : s
    }
    public var shortCheckpoint: String {
        guard !checkpoint.isEmpty else { return "—" }
        return String(checkpoint.suffix(16))
    }
}

public struct HealthGPU: Decodable, Equatable {
    public let name: String
    public let device: String?
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public let temperature_c: Double
    public var displayName: String {
        if !name.isEmpty { return name }
        if let d = device, !d.isEmpty { return d }
        return "cuda:0"
    }
}

public struct HealthPaper: Decodable, Equatable {
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

public struct OrderbookRuntimeTruth: Decodable, Equatable {
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

public struct OrderbookDirectFeedCoverage: Decodable, Equatable {
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

public struct OrderbookConfiguredSymbolCoverage: Decodable, Equatable {
    public let configured_symbol_count: Int?
    public let complete_symbols: [String]?
    public let incomplete_symbols: [String]?
    public let all_configured_symbols_have_required_direct_feed_coverage: Bool?
}

// MARK: - Microstructure Truth

public struct MicrostructureTruth: Decodable, Equatable {
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

public struct MobileRiskStatus: Decodable, Equatable {
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
    public let risk_classification: String?
    public let paper_blocked_count: Int
    public let paper_accepted_count: Int
    public let kill_switch_active: Bool
    public let fail_closed: Bool?
    public let decisions_processed_total: Int?
    public let max_position_size_usd: Double
    public let daily_loss_limit_usd: Double
    public let current_daily_loss_usd: Double
    public let dangerous_actions_require_human_approval: Bool
    public let mobile_can_approve_dangerous_actions: Bool
}

// MARK: - Paper Summary

public struct MobilePaperSummary: Decodable, Equatable {
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

public struct PaperLoop: Decodable, Equatable {
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

    public var blockRate: Double {
        let total = intents_accepted + intents_blocked
        guard total > 0 else { return 0 }
        return Double(intents_blocked) / Double(total) * 100
    }

    public var runtimeRouteLabel: String {
        routes_to_live == true ? "LIVE ROUTE" : "OPERATOR GATED"
    }
}

public struct PaperPositions: Decodable, Equatable {
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

public struct PaperPnL: Decodable, Equatable {
    public let realized_usd: Double
    public let unrealized_usd: Double
    public let total_usd: Double
    public let win_rate_pct: Double?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let reason_if_untrusted: String?
}

public struct TrainerFeedback: Decodable, Equatable {
    public let outcome_labels: Int
    public let consumable_rows: Int
    public let quarantined_rows: Int
}

// MARK: - Admin Summary

public struct MobileAdminSummary: Decodable, Equatable {
    public let generated_utc: String
    public let actor: AdminActor
    public let live_gate: LiveGateState
    public let trainer: AdminTrainer
    public let gpu: AdminGPU
    public let paper: AdminPaper
    public let risk: AdminRisk
    public let dangerous_controls_require_web_approval: Bool
    public let mobile_live_trading_blocked: Bool
}

public struct AdminActor: Decodable, Equatable {
    public let user_id: String
    public let email: String
    public let role: String
}

public struct AdminTrainer: Decodable, Equatable {
    public let state: String
    public let checkpoint: String
    public let champion_challenger_status: ChampionChallengerStatus?
    public let device: String?
    public let gpu_name: String?
    public let cuda_active: Bool
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
    public let model_id: String?
    public let input_dim: Int?
    public let feature_count: Int?
    public let temporal_encoder: String?
    public let temporal_encoder_enabled: Bool?
}

public struct AdminGPU: Decodable, Equatable {
    public let name: String
    public let device: String?
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public var displayName: String {
        if !name.isEmpty { return name }
        if let d = device, !d.isEmpty { return d }
        return "cuda:0"
    }
}

public struct AdminPaper: Decodable, Equatable {
    public let classification: String
    public let open_positions: Int
    public let closed_trades: Int
    public let realized_pnl_usd: Double
    public let unrealized_pnl_usd: Double
    public let intents_accepted: Int
    public let intents_blocked: Int
}

public struct AdminRisk: Decodable, Equatable {
    public let state: String
    public let classification: String?
    public let kill_switch_active: Bool
}

// MARK: - Audit Ledger

public struct AuditLedgerSummary: Decodable, Equatable {
    /// nil when the ledger has no events yet (API sends chain_ok=null with chain_state=EMPTY).
    public let chain_ok: Bool?
    public let chain_state: String?
    public let event_count_known_empty: Bool?
    public let tail_age_ms: Int?
    public let last_event_id: String?
    public let last_event_ts: String?

    /// True when the API verifiably reports an empty ledger (honest-empty, not an error).
    public var isKnownEmpty: Bool {
        chain_state?.uppercased() == "EMPTY" || event_count_known_empty == true
    }
    public var chainLabel: String {
        if let chain_ok { return chain_ok ? "OK" : "BROKEN" }
        return isKnownEmpty ? "EMPTY" : "UNKNOWN"
    }
    public var ageLabel: String {
        guard let ms = tail_age_ms else { return "—" }
        let s = ms / 1000
        if s < 60 { return "\(s)s ago" }
        if s < 3600 { return "\(s / 60)m ago" }
        return "\(s / 3600)h ago"
    }
}

public struct AuditLedgerEntry: Decodable, Identifiable, Equatable {
    public let evt_id: String
    public let source: String?
    public let act: String?
    public let decision_id: String?
    public let reason: String?
    public let chain_status: String?
    public let age_seconds: Double?

    public var id: String { evt_id }
    public var displaySource: String { source ?? "unknown" }
    public var displayAct: String { act ?? "event" }
    public var displayReason: String { reason ?? "—" }
    public var ageLabel: String {
        guard let s = age_seconds else { return "—" }
        if s < 60 { return "\(Int(s))s ago" }
        if s < 3600 { return "\(Int(s / 60))m ago" }
        return "\(Int(s / 3600))h ago"
    }
    public var chainOk: Bool {
        guard let c = chain_status?.lowercased() else { return true }
        return !["broken", "mismatch", "false"].contains(c)
    }
}

// MARK: - Signal Matrix (for Predictions/Explainability)

public struct SignalMatrixRow: Decodable, Identifiable, Equatable {
    public let signal_id: String?
    public let symbol: String?
    public let timeframe: String?
    public let action: String?
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
    public let actionable: Bool?
    public let live_gate: String?
    public let risk_state: String?
    public let paper_fill_status: String?
    public let data_coverage_percent: Double?
    public let market_state_integrity_score: Double?
    public let generated_at: String?
    public let age_seconds: Double?
    public let model_version: String?
    public let checkpoint_id: String?
    public let expected_move_bps: Double?
    public let feature_coverage_pct: Double?
    public let orchestrator_state: String?

    public var id: String { signal_id ?? UUID().uuidString }
    public var displaySymbol: String {
        guard let s = symbol else { return "—" }
        return s.hasSuffix("USDT") ? String(s.dropLast(4)) : s
    }
    public var confidencePct: String {
        guard let c = confidence else { return "—" }
        return "\(Int(c * 100))%"
    }
    public var selectedConfidence: Double? { confidence_selected_action ?? confidence }
    public var executableConfidence: Double { confidence_executable_trade ?? 0 }
    public var selectedConfidencePct: String {
        guard let c = selectedConfidence else { return "—" }
        return "\(Int(c * 100))%"
    }
    public var executableConfidencePct: String { "\(Int(executableConfidence * 100))%" }
    public var confidenceDisplayLabel: String { confidence_display_label ?? "Unproven confidence" }
    public var paperExplorationTier: String { paper_exploration_tier ?? exploration_tier ?? "NONE" }
    public var paperExplorationCurrentBlocker: String { paper_exploration_current_blocker ?? "not above floor" }
    public var whyNotAPlus: String { why_not_a_plus?.first ?? "A+ evidence not matured" }
    public var whyNotLiveReady: String { why_not_live_ready?.first ?? "blocked_human_only" }
    public var ageLabel: String {
        guard let s = age_seconds else { return "—" }
        if s < 60 { return "\(Int(s))s" }
        if s < 3600 { return "\(Int(s / 60))m" }
        return "\(Int(s / 3600))h"
    }
    public var isBuy: Bool { (action ?? "").lowercased().contains("long") || (action ?? "").lowercased().contains("buy") }
}

public struct SignalMatrixResponse: Decodable {
    public let generated_utc: String?
    public let signals: [SignalMatrixRow]
    public let total_returned: Int?
    public let actionable_count: Int?
}

// MARK: - App Configuration

public struct AppConfiguration {
    public static var baseURL: String {
        get { KeychainHelper.shared.loadBaseURL() ?? "https://dashboard.wajidali.us" }
        set { KeychainHelper.shared.saveBaseURL(newValue) }
    }

    public static var baseWSURL: String {
        baseURL
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
    }
}

// MARK: - AI prediction missing-feature alert (/api/v2/predictions/explain)
// The prediction is always produced (absent features are masked, not zero-filled);
// this surfaces exactly what is degraded and how severe, without blocking anything.
public struct AIPredictionMissingFeatureAlert: Decodable, Equatable {
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

public struct AIPredictionExplanation: Decodable, Equatable {
    public let summary: String?
    public let signal_strength: String?
    public let confidence_narrative: String?
    public let data_quality_narrative: String?
    public let market_integrity_narrative: String?
    public let technical_drivers: String?
    public let price_target_narrative: String?
    public let risk_gate_narrative: String?
    public let pipeline_state_narrative: String?
    public let full_text: String?
}

public struct AIPredictionExplainData: Decodable, Equatable {
    public let symbol: String?
    public let timeframe: String?
    public let explanation: AIPredictionExplanation?
    public let missing_feature_alert: AIPredictionMissingFeatureAlert?
}

public struct AIPredictionExplainResponse: Decodable, Equatable {
    public let data: AIPredictionExplainData?
}

// MARK: - Backtest + replay-feedback results (/api/v2/replay/backtest)
public struct PolicyBacktest: Decodable, Equatable {
    public let win_rate: Double?
    public let profit_factor_proxy: Double?
    public let expectancy_after_cost_bps: Double?
    public let rows_evaluated: Int?
    public let status: String?
    public let evidence_class: String?
}

public struct BacktestGeneralization: Decodable, Equatable {
    public let validation_supervised_loss: Double?
    public let validation_rows_evaluated: Int?
    public let train_val_generalization_gap: Double?
    public let overfit_gap_warning: Bool?
    public let loss_before: Double?
    public let loss_after: Double?
}

public struct ReplayFeedback: Decodable, Equatable {
    public let existing_counterfactual_rows: Int?
    public let new_matured_rows: Int?
    public let pending_rows: Int?
    public let trainer_loader_consumes: Bool?
}

public struct BacktestResults: Decodable, Equatable {
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

// MARK: - Markets overview (/api/v2/market/overview)
// Same canonical source the website Markets page uses (redis v2:market:kline_current).

public struct MarketTicker: Decodable, Equatable, Identifiable {
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

    public var id: String { symbol }
    public var shortSymbol: String {
        symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
    }
}

public struct MarketOverviewData: Decodable, Equatable {
    public let symbols: [String]?
    public let count: Int?
    public let timeframes: [String]?
    public let tickers: [MarketTicker]
    public let canonical_runtime_source: String?
}

public struct MarketOverviewResponse: Decodable, Equatable {
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

// MARK: - Mobile markets list (/api/v2/mobile/markets)
// Compact enriched per-symbol rows (~8.6KB for the full universe slice).
// Shares the /api/v2/market/overview enrichment pipeline; change_* fields
// are fractions (0.01 = +1%), funding_rate is the raw funding fraction.

public struct MobileMarketRow: Decodable, Equatable, Identifiable {
    public let symbol: String
    public let last_price: Double?
    public let change_24h: Double?
    public let change_1h: Double?
    public let change_7d: Double?
    public let funding_rate: Double?
    public let next_funding_time: String?
    public let open_interest: Double?
    public let open_interest_delta_1h_usd: Double?
    public let long_short_ratio: Double?
    public let turnover_24h_usd: Double?
    public let spread_bps: Double?
    public let liquidation_cascade_risk: Double?
    public let liq_direction_bias_1h: Double?
    public let rsi_1m: Double?
    public let htf_trend: String?
    public let altdata_symbol_score: Double?
    public let market_cap_rank: Int?

    public var id: String { symbol }
    public var shortSymbol: String {
        symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
    }
}

public struct MobileMarketsResponse: Decodable, Equatable {
    public let schema_version: String?
    public let generated_utc: String?
    public let payload_generated_utc: String?
    public let source: String?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let live_gate: String?
    public let places_real_order: Bool?
    public let routes_to_live: Bool?
    public let markets: [MobileMarketRow]
    public let count: Int?
}

// MARK: - Market symbol detail (/api/v2/market/{symbol})
// Rich Redis enrichment blocks. JSONDecoder ignores unknown keys, so heavy
// blocks (ta_1m 216-indicator dict, ladder) are intentionally NOT decoded.

public struct MarketDetailLongShort: Decodable, Equatable {
    public let long_short_ratio: Double?
    public let long_account_ratio: Double?
    public let short_account_ratio: Double?
    public let period: String?
    public let fetched_utc: String?
}

public struct MarketDetailFunding: Decodable, Equatable {
    public let funding_rate: Double?
    public let mark_price: Double?
    public let index_price: Double?
    public let basis_bps: Double?
    public let next_funding_time: String?
    public let estimated_settle_price: Double?
    public let generated_at: String?
}

public struct MarketDetailOrderbook: Decodable, Equatable {
    public let best_bid: Double?
    public let best_bid_size: Double?
    public let best_ask: Double?
    public let best_ask_size: Double?
    public let mid: Double?
    public let spread_bps: Double?
    public let depth_imbalance: Double?
    public let depth_20_bid_usd: Double?
    public let depth_20_ask_usd: Double?
    public let estimated_price_impact_bps: Double?
    public let source_latency_ms: Double?
    public let generated_at: String?
}

public struct MarketDetailLiqFlow: Decodable, Equatable {
    public let notional_1h: Double?
    public let count_1h: Int?
    public let long_count_1h: Int?
    public let short_count_1h: Int?
    public let direction_bias_1h: Double?
    public let notional_24h: Double?
    public let count_24h: Int?
    public let as_of: String?
}

public struct MarketDetailLiqLevels: Decodable, Equatable {
    public let distance_to_long_liq_bps: Double?
    public let distance_to_short_liq_bps: Double?
    public let liquidation_cascade_risk: Double?
    public let cascade_risk_semantics: String?
    public let levels_count_long: Int?
    public let levels_count_short: Int?
    public let nearest_level_above: Double?
    public let nearest_level_below: Double?
    public let sweep_target_short: Double?
    public let sweep_target_short_distance_bps: Double?
    public let sweep_target_long: Double?
    public let sweep_target_long_distance_bps: Double?
}

public struct MarketDetailLiqEnhanced: Decodable, Equatable {
    public let cascade_probability: Double?
    public let predicted_long_liq_zone: Double?
    public let predicted_short_liq_zone: Double?
    public let market_stress_indicator: Double?
    public let synthetic_data: Bool?
    public let generated_utc: String?
}

public struct MarketDetailRegime: Decodable, Equatable {
    public let regime: String?
    public let confidence: Double?
    public let htf_trend: String?
    public let rsi_zone: String?
    public let macd_direction: String?
    public let market_risk_state: String?
    public let generated_utc: String?
}

public struct MarketDetailCoinglass: Decodable, Equatable {
    public let open_interest_usd: Double?
    public let open_interest_delta_1h_usd: Double?
    public let funding_rate: Double?
    public let funding_rate_zscore: Double?
    public let next_funding_minutes: Double?
}

public struct MarketSymbolDetailData: Decodable, Equatable {
    public let symbol: String?
    public let last_price: Double?
    public let mark_price: Double?
    public let index_price: Double?
    public let change_1h: Double?
    public let change_4h: Double?
    public let change_24h: Double?
    public let change_7d: Double?
    public let high_24h: Double?
    public let low_24h: Double?
    public let volume_24h: Double?
    public let turnover_24h: Double?
    public let funding_rate: Double?
    public let next_funding_time: String?
    public let basis_bps: Double?
    public let open_interest: Double?
    public let open_interest_delta_1h_usd: Double?
    public let coinglass_open_interest_usd: Double?
    public let spread_bps: Double?
    public let orderbook_imbalance: Double?
    public let estimated_price_impact_bps: Double?
    public let market_cap_rank: Int?
    public let market_cap_usd: Double?
    public let liquidation_cascade_risk: Double?
    public let distance_to_long_liq_bps: Double?
    public let distance_to_short_liq_bps: Double?
    public let distance_to_nearest_liq_bps: Double?
    public let liq_notional_1h: Double?
    public let liq_count_1h: Int?
    public let liq_direction_bias_1h: Double?
    public let rsi_1m: Double?
    public let atr_1m: Double?
    public let adx_1m: Double?
    public let htf_trend: String?
    public let rsi_zone: String?
    public let macd_direction: String?
    public let altdata_symbol_score: Double?
    public let altdata_symbol_rank: Int?
    public let coinank_derivatives_score: Double?
    public let taker_buy_ratio: Double?
    public let taker_flow_trade_count: Int?
    public let long_short: MarketDetailLongShort?
    public let funding_detail: MarketDetailFunding?
    public let orderbook: MarketDetailOrderbook?
    public let liquidation_flow: MarketDetailLiqFlow?
    public let liquidation_levels: MarketDetailLiqLevels?
    public let liquidation_enhanced: MarketDetailLiqEnhanced?
    public let regime_1m: MarketDetailRegime?
    public let coinglass: MarketDetailCoinglass?
}

public struct MarketSymbolDetailResponse: Decodable, Equatable {
    public let schema_version: String?
    public let data: MarketSymbolDetailData
    public let source: String?
    public let timestamp: String?
    public let generated_at_utc: String?
    public let lag_ms: Double?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let data_quality_status: String?
    public let stale: Bool?
    public let missing_fields: [String]?
    public let warnings: [String]?
    public let live_gate: String?
    public let places_real_order: Bool?
    public let routes_to_live: Bool?
    public let symbol: String?
    public let exchange: String?
    public let mode: String?
}

// MARK: - Goal / 1000x trajectory (/api/v2/goal/trajectory-1000x)

public struct GoalGrowthStage: Decodable, Equatable {
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

public struct GoalBindingConstraint: Decodable, Equatable {
    public let constraint: String?
    public let detail: String?
}

public struct GoalTrajectoryData: Decodable, Equatable {
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

public struct GoalTrajectoryResponse: Decodable, Equatable {
    public let schema_version: String?
    public let data: GoalTrajectoryData
    public let source: String?
    public let generated_at_utc: String?
    public let staleness_seconds: Double?
    public let freshness_status: String?
    public let live_gate: String?
    public let places_real_order: Bool?
}

// MARK: - Canonical paper portfolio PnL (/api/v2/portfolio)

public struct PortfolioCanonicalData: Decodable, Equatable {
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
    public let mode: String?
    public let paper_or_live: String?
    public let equity_trusted: Bool?
    public let pnl_trusted: Bool?
    public let pnl_conflict_detected: Bool?
    public let freshness_status: String?
    public let staleness_seconds: Double?
    public let source_generated_utc: String?
}

public struct PortfolioCanonicalResponse: Decodable, Equatable {
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

// MARK: - Trainer deep telemetry (/api/v2/trainer/status)
// Extended blocks (gpu_runtime, model_edge_backtest, learning_metrics_extra)
// are emitted conditionally by the backend — all optionals; absent renders "—".

public struct TrainerGPURuntime: Decodable, Equatable {
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

public struct TrainerModelEdgeBacktest: Decodable, Equatable {
    public let win_rate: Double?
    public let expectancy_after_cost_bps: Double?
    public let profit_factor_proxy: Double?
    public let rows_evaluated: Double?
    public let a_plus_readiness_signal: String?
    public let evidence_class: String?
    public let status: String?
}

public struct TrainerRuntimeMode: Decodable, Equatable {
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

public struct TrainerLearningMetricsExtra: Decodable, Equatable {
    public let train_val_generalization_gap: Double?
    public let validation_loss_delta: Double?
    public let validation_supervised_loss: Double?
    public let validation_supervised_loss_before: Double?
    public let validation_supervised_loss_after: Double?
    public let loss_after: Double?
    public let overfit_gap_warning: Bool?
}

public struct TrainerOfflinePretrainStatus: Decodable, Equatable {
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

public struct TrainerDeepStatus: Decodable, Equatable {
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

// MARK: - Mobile derivatives summary (/api/v2/mobile/derivatives-summary)

public struct DerivativesAggregate: Decodable, Equatable {
    public let total_oi_usd: Double?
    public let total_liq_24h: Double?
    public let avg_funding: Double?
    public let aggregate_long_short_ratio: Double?
    public let funding_positive_count: Int?
    public let funding_negative_count: Int?
}

public struct DerivativesGlobalRegime: Decodable, Equatable {
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

public struct DerivativesSymbolRow: Decodable, Equatable, Identifiable {
    public let symbol: String
    public let funding_rate: Double?
    public let oi_usd: Double?
    public let long_short_ratio: Double?
    public let basis_bps: Double?
    public let cascade_risk: Double?
    public let mark_price: Double?

    public var id: String { symbol }
    public var shortSymbol: String {
        symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
    }
}

public struct MobileDerivativesSummary: Decodable, Equatable {
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

// MARK: - Mobile compact signal matrix (/api/v2/mobile/signal-matrix)
// One slim cell per symbol × timeframe (~156 × 5). Keys are single letters
// to keep the full-universe payload cellular-friendly.

public struct SignalMatrixCell: Decodable, Equatable, Identifiable {
    /// Symbol
    public let s: String
    /// Timeframe (1m/5m/15m/1h/4h)
    public let tf: String
    /// Action (long/short/hold)
    public let a: String?
    /// Executable-trade confidence
    public let c: Double?
    /// Actionable for paper fill
    public let act: Bool?
    /// Gate reason code when blocked (nil when actionable)
    public let g: String?

    public var id: String { "\(s):\(tf)" }
}

public struct MobileSignalMatrix: Decodable, Equatable {
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

// MARK: - Signal prediction accuracy (additive block in /api/v2/mobile/dashboard paper)

public struct PredictionAccuracyTimeframe: Decodable, Equatable, Identifiable {
    public let timeframe: String
    public let evaluated_count: Int?
    public let correct_count: Int?
    public let incorrect_count: Int?
    public let accuracy: Double?

    public var id: String { timeframe }
}

public struct SignalPredictionAccuracy: Decodable, Equatable {
    public let accuracy_definition: String?
    public let overall_accuracy: Double?
    public let evaluated_row_count: Int?
    public let correct_count: Int?
    public let incorrect_count: Int?
    public let by_timeframe: [PredictionAccuracyTimeframe]?
}

// MARK: - PnL windows (additive block in /api/v2/mobile/paper-summary)

public struct PnLWindow: Decodable, Equatable, Identifiable {
    public let window: String
    public let realized_pnl_usd: Double?
    public let closed_trade_count: Int?
    public let winning_trade_count: Int?
    public let losing_trade_count: Int?
    public let win_rate: Double?
    public let profit_factor: Double?

    public var id: String { window }
}

// MARK: - Data health (/api/v2/data-health)

public struct DataFeedSurface: Decodable, Equatable, Identifiable {
    public let name: String
    public let endpoint: String?
    public let status: String?
    public let description: String?
    public let actual_payload_count: Int?
    public let source_type: String?
    public let stale: Bool?
    public let lag_ms: Double?
    public let last_success: String?

    public var id: String { name }
}

public struct DataHealthData: Decodable, Equatable {
    public let overall: String?
    public let surfaces: [DataFeedSurface]?
    public let count: Int?
}

public struct DataHealthResponse: Decodable, Equatable {
    public let schema_version: String?
    public let data: DataHealthData
    public let generated_at_utc: String?
    public let stale: Bool?
    public let live_gate: String?
}
