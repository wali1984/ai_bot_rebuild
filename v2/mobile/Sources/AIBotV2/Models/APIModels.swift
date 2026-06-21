import Foundation

// MARK: - Dashboard

public struct MobileDashboard: Decodable, Equatable {
    public let generated_utc: String
    public let live_gate: LiveGateState
    public let paper: PaperState
    public let trainer: TrainerState
    public let gpu: GPUState
    public let alerts_preview: [MobileAlert]
    public let redis_connected: Bool
}

public struct LiveGateState: Decodable, Equatable {
    public let live_trading_enabled: Bool
    public let places_real_order: Bool
    public let gate: String
    public let label: String
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

    public var isActive: Bool { state.hasPrefix("ACTIVE") }
}

public struct GPUState: Decodable, Equatable {
    public let name: String
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int

    public var vramPercent: Double {
        guard vram_total_mb > 0 else { return 0 }
        return Double(vram_used_mb) / Double(vram_total_mb) * 100
    }
    public var vramUsedGB: Double { Double(vram_used_mb) / 1024 }
    public var vramTotalGB: Double { Double(vram_total_mb) / 1024 }
}

// MARK: - Position

public struct MobilePosition: Decodable, Identifiable, Equatable {
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
    public var pnlColor: PnLColor { total_pnl >= 0 ? .green : .red }
    public var isBuy: Bool { side.lowercased() == "long" || side.lowercased() == "buy" }
}

public enum PnLColor { case green, red }

public struct MobilePositionsResponse: Decodable {
    public let generated_utc: String
    public let positions: [MobilePosition]
    public let summary: PositionSummary
    public let mode: String
    public let live_gate: String
    public let places_real_order: Bool
}

public struct PositionSummary: Decodable, Equatable {
    public let open_count: Int
    public let total_pnl_usd: Double
    public let realized_pnl_usd: Double
    public let unrealized_pnl_usd: Double
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

    public var confidencePct: String { "\(Int(confidence * 100))%" }
    public var isActionable: Bool { actionable }
    public var actionColor: ActionColor {
        switch action.lowercased() {
        case "buy", "long": return .green
        case "sell", "short": return .red
        default: return .neutral
        }
    }
}

public enum ActionColor { case green, red, neutral }

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

    public var severityLevel: AlertSeverity {
        switch severity.lowercased() {
        case "critical": return .critical
        case "warning": return .warning
        case "error": return .error
        default: return .info
        }
    }
}

public enum AlertSeverity { case critical, error, warning, info }

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
    public var overallColor: HealthColor {
        switch overall {
        case "healthy": return .green
        case "degraded": return .yellow
        default: return .red
        }
    }
}

public enum HealthColor { case green, yellow, red }

public struct HealthTrainer: Decodable, Equatable {
    public let state: String
    public let cuda_active: Bool
    public let training_active: Bool
    public let checkpoint: String
}

public struct HealthGPU: Decodable, Equatable {
    public let name: String
    public let utilization_pct: Double
    public let vram_used_mb: Int
    public let vram_total_mb: Int
    public let temperature_c: Double
}

public struct HealthPaper: Decodable, Equatable {
    public let classification: String
    public let open_positions: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
}

// MARK: - Risk

public struct MobileRiskStatus: Decodable, Equatable {
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

public struct MobilePaperSummary: Decodable, Equatable {
    public let generated_utc: String
    public let mode: String
    public let places_real_order: Bool
    public let live_gate: String
    public let loop: PaperLoop
    public let positions: PaperPositions
    public let pnl: PaperPnL
    public let trainer_feedback: TrainerFeedback
}

public struct PaperLoop: Decodable, Equatable {
    public let signals_seen: Int
    public let intents_built: Int
    public let intents_accepted: Int
    public let intents_blocked: Int
    public let classification: String
}

public struct PaperPositions: Decodable, Equatable {
    public let open_count: Int
    public let closed_count: Int
    public let positions_preview: [MobilePosition]
}

public struct PaperPnL: Decodable, Equatable {
    public let realized_usd: Double
    public let unrealized_usd: Double
    public let total_usd: Double
    public let win_rate_pct: Double?
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
    public let gpu: GPUState
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
    public let cuda_active: Bool
    public let training_steps_total: Int
    public let training_steps_last_hour: Int
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
    public let kill_switch_active: Bool
}

// MARK: - App Configuration

public struct AppConfiguration {
    public static var baseURL: String {
        get { KeychainHelper.shared.loadBaseURL() ?? "https://dashboard.wajidali.us" }
        set { KeychainHelper.shared.saveBaseURL(newValue) }
    }

    public static var baseWSURL: String {
        baseURL.replacingOccurrences(of: "http://", with: "ws://")
               .replacingOccurrences(of: "https://", with: "wss://")
    }
}
