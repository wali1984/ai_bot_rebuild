import Foundation

/// All backend API endpoint paths for the AIBotV2 mobile app.
/// Base URL is configured at startup via AppConfiguration.
public enum APIEndpoints {

    // MARK: - Auth
    public static let login = "/api/auth/login"
    public static let logout = "/api/auth/logout"
    public static let refresh = "/api/auth/refresh"
    public static let me = "/api/auth/me"

    // MARK: - Mobile compact (v2/mobile)
    public static let mobileDashboard = "/api/v2/mobile/dashboard"
    public static let mobilePositions = "/api/v2/mobile/positions"
    public static let mobileSignals = "/api/v2/mobile/signals"
    public static let mobileAlerts = "/api/v2/mobile/alerts"
    public static let mobileHealth = "/api/v2/mobile/health"
    public static let mobileRiskStatus = "/api/v2/mobile/risk-status"
    public static let mobilePaperSummary = "/api/v2/mobile/paper-summary"
    public static let mobileAdminSummary = "/api/v2/mobile/admin/summary"
    public static let mobilePushRegister = "/api/v2/mobile/push/register"
    public static let orderbookRuntimeTruth = "/operator_runtime/v2_zero_budget_orderbook/latest/ios_orderbook_runtime_truth_status.json"
    public static let microstructureTruth = "/operator_runtime/v2_microstructure_trust/latest/ios_microstructure_truth_status.json"

    // MARK: - WebSocket streams
    public static let wsResource = "/api/v2/ws/resource"
    public static let wsMarketData = "/ws/market-data"
    public static let wsPaperActivity = "/ws/paper-activity"

    // MARK: - System health
    public static let health = "/health"
    public static let publicStatus = "/api/v2/public/status"

    // MARK: - Trainer (v2)
    public static let trainerStatus = "/api/v2/status"

    // MARK: - Audit
    public static let auditLedger = "/api/v2/audit-ledger"
    public static let auditLedgerSummary = "/api/v2/audit-ledger/summary"
    public static let auditLedgerTail = "/api/v2/audit-ledger/tail"
    public static let auditEvents = "/api/v2/execution/audit-events"

    // MARK: - Live gate + readiness
    public static let liveGateStatus = "/api/v2/live-gate/status"
    public static let liveReadinessGates = "/api/v2/live-readiness/gates"

    // MARK: - Paper activity
    public static let paperActivity = "/api/v2/paper/activity"
    public static let paperStatus = "/api/v2/paper/status"

    // MARK: - Signals / predictions / explainability
    public static let signalMatrix = "/api/v2/signals/matrix"
    public static let predictionMatrix = "/api/v2/predictions/matrix"

    // MARK: - Helpers
    public static func pushUnregister(token: String) -> String {
        "/api/v2/mobile/push/\(token)"
    }

    public static func wsMarketDataURL(baseWS: String, symbol: String, timeframe: String) -> URL? {
        URL(string: "\(baseWS)\(wsMarketData)?symbol=\(symbol)&timeframe=\(timeframe)")
    }

    public static func wsResourceURL(
        baseURL: String,
        path: String,
        queryItems: [URLQueryItem] = [],
        intervalMs: Int = 1_000
    ) -> String? {
        var baseWS = baseURL
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
        if baseWS.hasSuffix("/") {
            baseWS.removeLast()
        }

        var target = URLComponents()
        target.path = path
        target.queryItems = queryItems.isEmpty ? nil : queryItems

        var components = URLComponents(string: baseWS + wsResource)
        components?.queryItems = [
            URLQueryItem(name: "path", value: target.string ?? path),
            URLQueryItem(name: "interval_ms", value: String(intervalMs)),
        ]
        return components?.string
    }
}
