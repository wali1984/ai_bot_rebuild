import Foundation

public enum APIEndpoints {
    public static let login              = "/api/auth/login"
    public static let logout             = "/api/auth/logout"
    public static let me                 = "/api/auth/me"

    public static let mobileDashboard    = "/api/v2/mobile/dashboard"
    public static let mobilePositions    = "/api/v2/mobile/positions"
    public static let mobileSignals      = "/api/v2/mobile/signals"
    public static let mobileAlerts       = "/api/v2/mobile/alerts"
    public static let mobileHealth       = "/api/v2/mobile/health"
    public static let mobileRiskStatus   = "/api/v2/mobile/risk-status"
    public static let mobilePaperSummary = "/api/v2/mobile/paper-summary"
    public static let mobileAdminSummary = "/api/v2/mobile/admin/summary"
    public static let mobilePushRegister = "/api/v2/mobile/push/register"
    public static let orderbookRuntimeTruth = "/operator_runtime/v2_zero_budget_orderbook/latest/ios_orderbook_runtime_truth_status.json"
    public static let microstructureTruth = "/operator_runtime/v2_microstructure_trust/latest/ios_trust_semantics_truth_status.json"

    public static let health             = "/health"
    public static let publicStatus       = "/api/v2/public/status"
    public static let trainerStatus      = "/api/v2/status"
    public static let auditLedger        = "/api/v2/audit-ledger"
    public static let liveGateStatus     = "/api/v2/live-gate/status"
    public static let paperActivity      = "/api/v2/paper/activity"
    public static let signalMatrix       = "/api/v2/signals/matrix"

    public static let realtimeBootstrap  = "/api/v2/realtime/bootstrap"
    public static let realtimeResources  = "/api/v2/realtime/resources"
    public static let realtimeHealth     = "/api/v2/realtime/health"

    public static let wsResource         = "/api/v2/ws/resource"
    public static let wsRealtime         = "/api/v2/realtime/ws"
    public static let wsMarketData       = "/ws/market-data"
    public static let wsPaperActivity    = "/ws/paper-activity"

    public static func pushUnregister(token: String) -> String {
        "/api/v2/mobile/push/\(token)"
    }

    public static func wsRealtimeURL(
        baseURL: String,
        resources: [String] = [],
        intervalMs: Int = 2_000
    ) -> String? {
        var baseWS = baseURL
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
        if baseWS.hasSuffix("/") {
            baseWS.removeLast()
        }
        var components = URLComponents(string: baseWS + wsRealtime)
        var items = [URLQueryItem(name: "interval_ms", value: String(intervalMs))]
        if !resources.isEmpty {
            items.append(URLQueryItem(name: "resources", value: resources.joined(separator: ",")))
        }
        components?.queryItems = items
        return components?.string
    }
}
