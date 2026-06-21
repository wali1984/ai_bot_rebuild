import Foundation

/// Compact models for watchOS — minimal data to fit watch screen.

struct WatchDashboardData {
    let overallStatus: String
    let trainerActive: Bool
    let gpuUtilization: Double
    let openPositions: Int
    let totalPnL: Double
    let realizedPnL: Double
    let unrealizedPnL: Double
    let signalsSeen: Int
    let intentsAccepted: Int
    let intentsBlocked: Int
    let liveBlocked: Bool
    let lastUpdated: String

    init(from dict: [String: Any]) {
        overallStatus = dict["overall"] as? String ?? "unknown"
        trainerActive = dict["trainer_active"] as? Bool ?? false
        gpuUtilization = dict["gpu_utilization"] as? Double ?? 0
        openPositions = dict["open_positions"] as? Int ?? 0
        totalPnL = dict["total_pnl"] as? Double ?? 0
        realizedPnL = dict["realized_pnl"] as? Double ?? 0
        unrealizedPnL = dict["unrealized_pnl"] as? Double ?? 0
        signalsSeen = dict["signals_seen"] as? Int ?? 0
        intentsAccepted = dict["intents_accepted"] as? Int ?? 0
        intentsBlocked = dict["intents_blocked"] as? Int ?? 0
        liveBlocked = dict["live_blocked"] as? Bool ?? true
        lastUpdated = dict["last_updated"] as? String ?? ""
    }

    var pnlColor: WatchColor { totalPnL >= 0 ? .green : .red }
    var statusColor: WatchColor {
        switch overallStatus {
        case "healthy": return .green
        case "degraded": return .yellow
        default: return .red
        }
    }
}

struct WatchPosition: Identifiable {
    let id: String
    let symbol: String
    let side: String
    let unrealizedPnL: Double
    let entryPrice: Double
    let markPrice: Double

    init?(from dict: [String: Any]) {
        guard let sym = dict["symbol"] as? String, !sym.isEmpty else { return nil }
        id = dict["id"] as? String ?? UUID().uuidString
        symbol = sym
        side = dict["side"] as? String ?? ""
        unrealizedPnL = dict["unrealized_pnl"] as? Double ?? 0
        entryPrice = dict["entry_price"] as? Double ?? 0
        markPrice = dict["mark_price"] as? Double ?? 0
    }

    var isBuy: Bool { side.lowercased().contains("long") || side.lowercased().contains("buy") }
    var pnlColor: WatchColor { unrealizedPnL >= 0 ? .green : .red }
}

struct WatchAlert: Identifiable {
    let id: String
    let symbol: String
    let type: String
    let severity: String
    let message: String

    init?(from dict: [String: Any]) {
        id = dict["id"] as? String ?? UUID().uuidString
        symbol = dict["symbol"] as? String ?? ""
        type = dict["type"] as? String ?? ""
        severity = dict["severity"] as? String ?? "info"
        message = dict["message"] as? String ?? ""
        if message.isEmpty { return nil }
    }

    var severityColor: WatchColor {
        switch severity {
        case "critical": return .red
        case "warning": return .orange
        default: return .blue
        }
    }
}

enum WatchColor {
    case green, yellow, red, orange, blue
}
