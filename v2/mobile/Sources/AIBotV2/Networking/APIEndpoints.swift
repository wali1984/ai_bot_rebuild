import Foundation

/// All backend API endpoint paths for the AIBotV2 mobile app.
/// Base URL is configured at startup via AppConfiguration.
public enum APIEndpoints {

    // MARK: - Auth
    public static let login = "/api/auth/login"
    public static let logout = "/api/auth/logout"
    public static let authHealth = "/api/auth/health"
    public static let refresh = "/api/auth/refresh"
    public static let me = "/api/auth/me"

    // MARK: - Mobile compact (v2/mobile)
    public static let mobileDashboard = "/api/v2/mobile/dashboard"
    public static let mobilePositions = "/api/v2/mobile/positions"
    public static let mobileSignals = "/api/v2/mobile/signals"
    public static let mobileAlerts = "/api/v2/mobile/alerts"
    public static let mobileHealth = "/api/v2/mobile/health"
    public static let mobileRiskStatus = "/api/v2/mobile/risk-status"
    public static let selfHealingStatus = "/api/v2/self-healing/status"
    public static let mobilePaperSummary = "/api/v2/mobile/paper-summary"
    public static let mobileAdminSummary = "/api/v2/mobile/admin/summary"
    public static let mobilePushRegister = "/api/v2/mobile/push/register"
    public static let orderbookRuntimeTruth = "/operator_runtime/v2_zero_budget_orderbook/latest/ios_orderbook_runtime_truth_status.json"
    public static let microstructureTruth = "/operator_runtime/v2_microstructure_trust/latest/ios_trust_semantics_truth_status.json"

    // MARK: - WebSocket streams
    public static let wsResource = "/api/v2/ws/resource"
    public static let wsMarketData = "/ws/market-data"
    public static let wsPaperActivity = "/ws/paper-activity"

    // MARK: - System health
    public static let health = "/health"
    public static let publicStatus = "/api/v2/public/status"

    // MARK: - Trainer (v2)
    public static let trainerStatus = "/api/v2/trainer/status"
    public static let replayBacktest = "/api/v2/replay/backtest"
    public static let predictionsExplain = "/api/v2/predictions/explain"
    public static let providersStatus = "/api/v2/providers/status"
    public static let ingestorsStatus = "/api/v2/ingestors/status"
    public static let liveCanaryStatus = "/api/v2/live-canary/status"
    public static let aPlusInventory = "/api/v2/a-plus/inventory"
    public static let currentSignal = "/api/v2/signals/current"

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
    public static let realtimeBootstrap = "/api/v2/realtime/bootstrap"
    public static let realtimeResources = "/api/v2/realtime/resources"
    public static let realtimeHealth = "/api/v2/realtime/health"
    public static let wsRealtime = "/api/v2/realtime/ws"

    // MARK: - Website-parity surfaces (same endpoints the web pages consume)
    /// Per-symbol tickers — canonical Markets source (~10.5KB).
    public static let marketOverview = "/api/v2/market/overview"
    /// Full derivatives payload (~102KB — prefer mobileDerivativesSummary on cellular).
    public static let derivatives = "/api/v2/derivatives"
    /// Compact mobile derivatives rollup (aggregate + regime + top symbols).
    public static let mobileDerivativesSummary = "/api/v2/mobile/derivatives-summary"
    /// Compact iOS markets list (~8.6KB) — enriched per-symbol rows
    /// (price/24h/funding/OI-delta/cascade-risk/RSI/score, shares the
    /// /api/v2/market/overview enrichment pipeline).
    public static let mobileMarkets = "/api/v2/mobile/markets"
    /// Compact full-universe signal matrix (one slim cell per symbol × timeframe).
    public static let mobileSignalMatrix = "/api/v2/mobile/signal-matrix"
    /// Goal / 1000x trajectory (compact, carries live_gate safety fields).
    public static let goalTrajectory1000x = "/api/v2/goal/trajectory-1000x"
    /// Canonical paper portfolio PnL (realized/unrealized/total/equity).
    public static let portfolio = "/api/v2/portfolio"
    public static let mobileDashboardCurrentSession = "\(mobileDashboard)?scope=current_session"
    public static let mobilePositionsCurrentSession = "\(mobilePositions)?scope=current_session"
    public static let mobilePaperSummaryCurrentSession = "\(mobilePaperSummary)?scope=current_session"
    public static let portfolioCurrentSession = "\(portfolio)?scope=current_session"
    public static let currentPaperScopeQueryItems = [
        URLQueryItem(name: "scope", value: "current_session")
    ]
    /// Per-surface data-feed health with lag (System Health page source).
    public static let dataHealth = "/api/v2/data-health"
    /// Backend service health (small).
    public static let systemHealth = "/api/v2/system/health"
    /// CPU/mem/disk/network runtime internals (small).
    public static let systemMetrics = "/api/v2/system/metrics"
    /// Trainer deep telemetry — same payload the website AI page consumes.
    public static let trainerSummary = "/api/v2/trainer/summary"
    /// Account-scoped execution surfaces (all small).
    public static let executionExecutions = "/api/v2/execution/executions"
    public static let executionOrders = "/api/v2/execution/orders"

    // MARK: - Helpers
    public static func pushUnregister(token: String) -> String {
        "/api/v2/mobile/push/\(token)"
    }

    /// Per-ingestor chart-ready metrics (streamable via wsResourceURL(path:)).
    /// No query string so the path stays clean for both HTTP and the WS resource
    /// helper; the backend defaults to a sensible row limit.
    public static func ingestorMetrics(name: String) -> String {
        "/api/v2/ingestors/\(name)/metrics"
    }

    /// Rich per-symbol market detail (Redis enrichment blocks: funding_detail,
    /// long_short, orderbook, liquidation levels/enhanced/flow, regime_1m).
    public static func marketDetail(symbol: String) -> String {
        "/api/v2/market/\(symbol)"
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
