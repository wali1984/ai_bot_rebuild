import Foundation
import Observation

// MARK: - Slim winner-flag performance overlay (/api/v2/mobile/dashboard)
//
// Only the chart + accuracy fields this screen needs are declared — Decodable
// ignores the rest of the dashboard payload. The server curve is ordered and
// NET (after-cost) so the Portfolio screen never recomputes win/loss locally
// from sign(realized_pnl), which miscounts fee-eaten trades.
public struct PortfolioPerformanceOverlay: Decodable, Equatable {
    public struct WinnerAccuracy: Decodable, Equatable {
        public let source: String?
        public let accuracy_definition: String?
        public let overall_accuracy: Double?
        public let evaluated_row_count: Int?
        public let correct_count: Int?
        public let incorrect_count: Int?
    }

    public struct Paper: Decodable, Equatable {
        public let equity_curve: [EquityPoint]?
        public let win_rate: Double?
        public let win_count: Int?
        public let loss_count: Int?
        public let signal_prediction_accuracy: WinnerAccuracy?
    }

    public let generated_utc: String?
    public let paper: Paper?
}

@MainActor
@Observable
public final class PositionsViewModel {

    public private(set) var response: MobilePositionsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var sourceType: String?
    public private(set) var transport: String?
    public private(set) var lastUpdatedAt: String?
    public private(set) var lagMs: Double?
    public private(set) var isStale = false
    public private(set) var streamWarnings: [String] = []
    public private(set) var missingFields: [String] = []

    // Canonical paper portfolio (/api/v2/portfolio) — website Portfolio parity.
    public private(set) var portfolio: PortfolioCanonicalResponse?
    public private(set) var portfolioError: String?

    // Winner-flag performance overlay (server-ordered curve + donut truth).
    public private(set) var performance: PortfolioPerformanceOverlay?
    public private(set) var performanceError: String?

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 1_500
    private var lastSessionId: String?
    private var lastEpoch: Int?

    public var positions: [MobilePosition] { response?.positions ?? [] }
    public var closedPositions: [MobilePosition] { response?.closed_positions ?? [] }
    public var historicalPositions: [MobilePosition] { response?.historical_positions ?? response?.closed_positions ?? [] }
    public var summary: PositionSummary? { response?.summary }

    // MARK: Canonical equity + divergence truth

    public var canonicalEquity: Double? {
        portfolio?.data.equity ?? portfolio?.data.paper_equity_usd
    }

    public var canonicalAvailableBalance: Double? { portfolio?.data.available_balance_usd }
    public var canonicalStartingEquity: Double? {
        portfolio?.data.starting_equity_usd ?? portfolio?.data.initial_capital
    }
    public var canonicalTotalPnl: Double? { portfolio?.data.total_pnl_usd }
    public var canonicalRealizedNetPnl: Double? {
        portfolio?.data.realized_net_pnl_usd ?? portfolio?.data.realized_pnl_usd
    }
    public var canonicalUnrealizedPnl: Double? { portfolio?.data.unrealized_pnl_usd }
    public var portfolioStale: Bool { portfolio?.stale == true }
    public var portfolioStalenessSeconds: Double? { portfolio?.data.staleness_seconds }
    public var equityTrusted: Bool? { portfolio?.data.equity_trusted }
    public var pnlTrusted: Bool? { portfolio?.data.pnl_trusted }

    /// Mobile summary total PnL minus canonical portfolio total PnL.
    /// Non-nil only when both sources are present.
    public var pnlDivergenceUSD: Double? {
        guard let canonical = canonicalTotalPnl, let mobile = summary?.total_pnl_usd else { return nil }
        return mobile - canonical
    }

    /// Flag divergence beyond the known non-atomic write skew (~$0.02–0.03).
    public var pnlDiverges: Bool {
        guard let delta = pnlDivergenceUSD else { return false }
        return abs(delta) > 0.05
    }

    // MARK: Server performance series (winner-flag truth, never local recompute)

    public var equityCurve: [EquityPoint] { performance?.paper?.equity_curve ?? [] }
    public var cumulativePnlSeries: [Double] { equityCurve.compactMap { $0.cumulative_pnl } }
    public var perTradePnlSeries: [Double] { equityCurve.compactMap { $0.pnl } }

    public var winnerAccuracy: PortfolioPerformanceOverlay.WinnerAccuracy? {
        performance?.paper?.signal_prediction_accuracy
    }

    public var serverWinRate: Double? {
        winnerAccuracy?.overall_accuracy ?? performance?.paper?.win_rate
    }

    public var serverWinCount: Int? {
        winnerAccuracy?.correct_count ?? performance?.paper?.win_count
    }

    public var serverLossCount: Int? {
        winnerAccuracy?.incorrect_count ?? performance?.paper?.loss_count
    }

    public var serverEvaluatedCount: Int? { winnerAccuracy?.evaluated_row_count }
    public var winRateDefinition: String { winnerAccuracy?.accuracy_definition ?? "winner_rate" }

    // MARK: Mark-price honesty (conditional MARKS LIVE badge inputs)

    public var staleMarkCount: Int { response?.position_pricing?.stale_mark_price_count ?? 0 }
    public var missingMarkCount: Int { response?.position_pricing?.missing_mark_price_count ?? 0 }
    public var degradedMarkCount: Int { staleMarkCount + missingMarkCount }
    public var markToMarketLive: Bool { response?.position_pricing?.mark_to_market_live == true }

    // MARK: Lifecycle

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        async let positionsLoad: Void = loadFallback(token: token, baseURL: baseURL)
        async let overlaysLoad: Void = loadOverlays(token: token, baseURL: baseURL)
        _ = await (positionsLoad, overlaysLoad)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if Task.isCancelled { break }
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    await loadFallback(token: token, baseURL: baseURL)
                }
                // Canonical portfolio + winner-flag overlays are HTTP-only —
                // refresh them on every cycle regardless of stream health.
                await loadOverlays(token: token, baseURL: baseURL)
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        stream.disconnect()
        streamLabel = "Disconnected"
    }

    private var streamIsConnected: Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connect(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobilePositions,
            queryItems: APIEndpoints.currentPaperScopeQueryItems,
            intervalMs: streamIntervalMs
        ) else {
            streamLabel = "Offline"
            return
        }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStream(message)
        }
    }

    private func loadFallback(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            let incoming: MobilePositionsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobilePositionsCurrentSession,
                token: token,
                baseURL: baseURL
            )
            guard applyCurrentSessionResponse(incoming) else {
                streamWarnings = ["Ignored stale paper-account epoch response"]
                isLoading = false
                return
            }
            sourceType = "api"
            transport = "http"
            lastUpdatedAt = response?.generated_utc
            lagMs = nil
            isStale = false
            streamWarnings = response?.warnings ?? []
            missingFields = []
            WatchSyncCenter.shared.updatePositions(response)
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func loadOverlays(token: String?, baseURL: String) async {
        do {
            let canonical: PortfolioCanonicalResponse = try await APIClient.shared.get(
                path: APIEndpoints.portfolioCurrentSession,
                token: token,
                baseURL: baseURL
            )
            portfolio = canonical
            portfolioError = nil
        } catch {
            portfolioError = error.localizedDescription
        }
        do {
            let overlay: PortfolioPerformanceOverlay = try await APIClient.shared.get(
                path: APIEndpoints.mobileDashboardCurrentSession,
                token: token,
                baseURL: baseURL
            )
            performance = overlay
            performanceError = nil
        } catch {
            performanceError = error.localizedDescription
        }
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobilePositionsResponse.self, from: message)
            guard applyCurrentSessionResponse(snapshot.payload) else {
                streamWarnings = ["Ignored stale paper-account epoch frame"]
                return
            }
            streamLabel = "Realtime"
            sourceType = snapshot.sourceType ?? snapshot.transport ?? "websocket"
            transport = snapshot.transport ?? "websocket"
            lastUpdatedAt = snapshot.timestamp ?? snapshot.receivedAt ?? snapshot.payload.generated_utc
            lagMs = snapshot.lagMs
            isStale = snapshot.stale
            streamWarnings = snapshot.warnings.isEmpty ? (snapshot.payload.warnings ?? []) : snapshot.warnings
            missingFields = snapshot.missingFields
            WatchSyncCenter.shared.updatePositions(response)
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }

    @discardableResult
    private func applyCurrentSessionResponse(_ incoming: MobilePositionsResponse) -> Bool {
        guard acceptsCurrentPaperSessionFrame(
            incomingSessionId: incoming.paper_session_id,
            incomingEpoch: incoming.paper_account_epoch,
            activeSessionId: lastSessionId,
            activeEpoch: lastEpoch
        ) else { return false }
        response = incoming
        lastSessionId = incoming.paper_session_id
        lastEpoch = incoming.paper_account_epoch
        return true
    }
}
