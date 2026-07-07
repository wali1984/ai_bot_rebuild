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

public struct PaperState: Decodable, Equatable {
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
    public var acceptanceRate: Double {
        let total = intents_accepted + intents_blocked
        guard total > 0 else { return 0 }
        return Double(intents_accepted) / Double(total) * 100
    }
}

public struct TrainerState: Decodable, Equatable {
    public let state: String
    public let checkpoint: String
    public let model_source: String
    public let cuda_active: Bool
    public let data_coverage: Double
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
    public let device: String?
    public let gpu_name: String?

    public var isActive: Bool { state.uppercased().contains("ACTIVE") }
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
    public let actionable: Bool
    public let risk_state: String
    public let paper_fill_status: String
    public let published_at: String
    public let last_price: Double?
    public let expected_move_bps: Double?
    public let data_coverage: Double?

    public var confidencePct: String { "\(Int(confidence * 100))%" }
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

// MARK: - Health

public struct MobileHealth: Decodable, Equatable {
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

public struct HealthTrainer: Decodable, Equatable {
    public let state: String
    public let cuda_active: Bool
    public let training_active: Bool
    public let checkpoint: String
    public let device: String?
    public let gpu_name: String?

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
    public let public_book_can_approve_trade_alone: Bool
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
}

// MARK: - Risk

public struct MobileRiskStatus: Decodable, Equatable {
    public let generated_utc: String
    public let live_gate: LiveGateState
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
    public let loop: PaperLoop
    public let positions: PaperPositions
    public let position_pricing: PositionPricing?
    public let pnl: PaperPnL
    public let trainer_feedback: TrainerFeedback
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
    public let device: String?
    public let gpu_name: String?
    public let cuda_active: Bool
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
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
    public let chain_ok: Bool
    public let tail_age_ms: Int?
    public let last_event_id: String?
    public let last_event_ts: String?

    public var chainLabel: String { chain_ok ? "OK" : "BROKEN" }
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

// MARK: - Live Readiness

public struct LiveReadinessGate: Decodable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public let sub: String
    public let source_route_or_key: String
    public let state: String

    public var isPassed: Bool { state == "passed" }
    public var isBlocked: Bool { state == "blocked" }
    public var isLocked: Bool { state == "locked" }
    public var displayState: String { state.uppercased() }
    public var stateEmoji: String {
        switch state {
        case "passed": return "✓"
        case "blocked": return "✗"
        case "locked": return "⊘"
        default: return "…"
        }
    }
}

// MARK: - Paper Activity / Executions

public struct PaperActivityEvent: Decodable, Identifiable, Equatable {
    public let event_id: String?
    public let event_type: String?
    public let symbol: String?
    public let side: String?
    public let action: String?
    public let realized_pnl_usd: Double?
    public let entry_price: Double?
    public let exit_price: Double?
    public let quantity: Double?
    public let timestamp: String?
    public let reason: String?
    public let strategy_id: String?

    public var id: String { event_id ?? UUID().uuidString }
    public var displayType: String { event_type?.uppercased() ?? "EVENT" }
    public var displaySymbol: String {
        guard let s = symbol else { return "—" }
        return s.hasSuffix("USDT") ? String(s.dropLast(4)) : s
    }
    public var isBuy: Bool { (side ?? action ?? "").lowercased().contains("long") || (side ?? action ?? "").lowercased().contains("buy") }
    public var pnlSign: String { (realized_pnl_usd ?? 0) >= 0 ? "+" : "" }
}

public struct PaperActivityResponse: Decodable {
    public let generated_utc: String
    public let events: [PaperActivityEvent]
    public let total_returned: Int?
    public let mode: String?
}

// MARK: - Capital Productivity (extended from paper summary)

public struct MobileCapitalProductivity: Decodable, Equatable {
    public let generated_utc: String
    public let win_rate_pct: Double?
    public let profit_factor: Double?
    public let mean_pnl_bps: Double?
    public let max_drawdown_pct: Double?
    public let total_trades: Int?
    public let winning_trades: Int?
    public let losing_trades: Int?
    public let avg_win_usd: Double?
    public let avg_loss_usd: Double?
    public let expectancy_usd: Double?
}

// MARK: - Signal Matrix (for Predictions/Explainability)

public struct SignalMatrixRow: Decodable, Identifiable, Equatable {
    public let signal_id: String?
    public let symbol: String?
    public let timeframe: String?
    public let action: String?
    public let confidence: Double?
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
