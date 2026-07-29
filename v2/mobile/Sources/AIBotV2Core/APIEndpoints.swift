import Foundation

public enum APIEndpoints {
    public static let login              = "/api/auth/login"
    public static let logout             = "/api/auth/logout"
    public static let authHealth         = "/api/auth/health"
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
    public static let trainerStatus      = "/api/v2/trainer/status"
    public static let providersStatus    = "/api/v2/providers/status"
    public static let liveCanaryStatus   = "/api/v2/live-canary/status"
    public static let aPlusInventory     = "/api/v2/a-plus/inventory"
    public static let currentSignal      = "/api/v2/signals/current"
    public static let auditLedger        = "/api/v2/audit-ledger"
    public static let liveGateStatus     = "/api/v2/live-gate/status"
    public static let paperActivity      = "/api/v2/paper/activity"
    public static let signalMatrix       = "/api/v2/signals/matrix"

    public static let realtimeBootstrap  = "/api/v2/realtime/bootstrap"
    public static let realtimeResources  = "/api/v2/realtime/resources"
    public static let realtimeHealth     = "/api/v2/realtime/health"

    // Website-parity surfaces (same endpoints the web pages consume)
    public static let marketOverview     = "/api/v2/market/overview"
    public static let derivatives        = "/api/v2/derivatives"
    public static let mobileDerivativesSummary = "/api/v2/mobile/derivatives-summary"
    public static let mobileSignalMatrix = "/api/v2/mobile/signal-matrix"
    public static let goalTrajectory1000x = "/api/v2/goal/trajectory-1000x"
    public static let portfolio          = "/api/v2/portfolio"
    public static let mobileDashboardCurrentSession = "\(mobileDashboard)?scope=current_session"
    public static let mobilePositionsCurrentSession = "\(mobilePositions)?scope=current_session"
    public static let mobilePaperSummaryCurrentSession = "\(mobilePaperSummary)?scope=current_session"
    public static let portfolioCurrentSession = "\(portfolio)?scope=current_session"
    public static let dataHealth         = "/api/v2/data-health"
    public static let systemHealth       = "/api/v2/system/health"
    public static let systemMetrics      = "/api/v2/system/metrics"
    public static let trainerSummary     = "/api/v2/trainer/summary"
    public static let ingestorsStatus    = "/api/v2/ingestors/status"
    public static let executionExecutions = "/api/v2/execution/executions"
    public static let executionOrders    = "/api/v2/execution/orders"

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
