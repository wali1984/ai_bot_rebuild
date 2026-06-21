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
}

public struct TrainerState: Decodable, Sendable {
    public let state: String
    public let checkpoint: String
    public let model_source: String
    public let cuda_active: Bool
    public let data_coverage: Double
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
    public var isActive: Bool { state.hasPrefix("ACTIVE") }
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
    public let entry_price: Double
    public let mark_price: Double
    public let unrealized_pnl: Double
    public let realized_pnl: Double
    public let opened_at: String
    public let status: String
    public var total_pnl: Double { unrealized_pnl + realized_pnl }
    public var isBuy: Bool { side.lowercased().contains("long") || side.lowercased() == "buy" }
}

public struct MobilePositionsResponse: Decodable, Sendable {
    public let generated_utc: String
    public let positions: [MobilePosition]
    public let summary: PositionSummary
    public let mode: String
    public let live_gate: String
    public let places_real_order: Bool
}

public struct PositionSummary: Decodable, Sendable {
    public let open_count: Int
    public let total_pnl_usd: Double
    public let realized_pnl_usd: Double
    public let unrealized_pnl_usd: Double
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
}

public struct HealthGPU: Decodable, Sendable {
    public let name: String
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public let temperature_c: Double
}

public struct HealthPaper: Decodable, Sendable {
    public let classification: String
    public let open_positions: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
}

// MARK: - Risk

public struct MobileRiskStatus: Decodable, Sendable {
    public let generated_utc: String
    public let live_gate: LiveGateState
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
    public let loop: PaperLoop
    public let positions: PaperPositions
    public let pnl: PaperPnL
    public let trainer_feedback: TrainerFeedback
}

public struct PaperLoop: Decodable, Sendable {
    public let signals_seen: Int
    public let intents_built: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
    public let classification: String
}

public struct PaperPositions: Decodable, Sendable {
    public let open_count: Int
    public let closed_count: Int
    public let positions_preview: [MobilePosition]
}

public struct PaperPnL: Decodable, Sendable {
    public let realized_usd: Double
    public let unrealized_usd: Double
    public let total_usd: Double
    public let win_rate_pct: Double?
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
