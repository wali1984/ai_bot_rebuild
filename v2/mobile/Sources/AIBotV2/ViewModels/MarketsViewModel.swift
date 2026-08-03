import Foundation
import Observation

/// Markets screen view model.
///
/// Owns the compact enriched markets list end-to-end (read-only telemetry):
///   GET /api/v2/mobile/markets  (WS stream @10s via wsResourceURL + HTTP fallback)
///
/// Derived state is honest client-side bookkeeping over the published rows:
/// tab filters (overview / gainers / losers / watchlist), symbol search, sort
/// (default turnover_24h_usd desc) and a locally persisted watchlist
/// (UserDefaults key "markets.watchlist.symbols"). Nothing is computed that
/// pretends to be backend truth — gainers/losers are simple change_24h signs.
///
/// Live trading stays operator-gated (live_gate=blocked_human_only).
@MainActor
@Observable
public final class MarketsViewModel {

    // MARK: - Tabs / sort

    public enum MarketsTab: String, CaseIterable {
        case overview = "All"
        case gainers = "Gainers"
        case losers = "Losers"
        case watchlist = "Watchlist"
    }

    public enum SortKey: String, CaseIterable {
        case turnover = "Turnover"
        case change24h = "24h %"
        case cascadeRisk = "Cascade"
        case score = "Score"
        case symbol = "Symbol"
    }

    // MARK: - Published state

    public private(set) var response: MobileMarketsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdated: String?

    // Envelope / payload freshness truth (feeds the StalenessChip).
    public private(set) var envelopeStale = false
    public private(set) var envelopeLagMs: Double?
    public private(set) var envelopeTransport: String?

    public var tab: MarketsTab = .overview
    public var sortKey: SortKey = .turnover
    public var sortDescending = true
    public var searchText: String = ""

    /// Locally persisted watchlist (device preference, not backend state).
    public private(set) var watchlist: Set<String>

    // MARK: - Private

    private static let watchlistDefaultsKey = "markets.watchlist.symbols"
    private let stream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?
    private var lastToken: String?
    private var lastBaseURL: String = ""

    public init() {
        let saved = UserDefaults.standard.stringArray(forKey: Self.watchlistDefaultsKey) ?? []
        watchlist = Set(saved)
    }

    // MARK: - Derived

    public var rows: [MobileMarketRow] { response?.markets ?? [] }

    public var hasAnyData: Bool { !rows.isEmpty }

    public var symbolCount: Int { response?.count ?? rows.count }

    public var gainerCount: Int {
        rows.filter { ($0.change_24h ?? 0) > 0 && $0.change_24h != nil }.count
    }

    public var loserCount: Int {
        rows.filter { ($0.change_24h ?? 0) < 0 }.count
    }

    public var watchlistCount: Int {
        rows.filter { watchlist.contains($0.symbol) }.count
    }

    /// Rows after the tab + search filters, in the current sort order.
    public var displayedRows: [MobileMarketRow] {
        var out = rows
        switch tab {
        case .overview:
            break
        case .gainers:
            out = out.filter { ($0.change_24h ?? 0) > 0 && $0.change_24h != nil }
        case .losers:
            out = out.filter { ($0.change_24h ?? 0) < 0 }
        case .watchlist:
            out = out.filter { watchlist.contains($0.symbol) }
        }
        let query = searchText.trimmingCharacters(in: .whitespaces).uppercased()
        if !query.isEmpty {
            out = out.filter {
                $0.symbol.uppercased().contains(query) || $0.shortSymbol.uppercased().contains(query)
            }
        }
        return sorted(out)
    }

    public var liveGateLabel: String {
        nervyxPublicRuntimeText(response?.live_gate ?? "blocked_human_only")
    }

    /// Combined envelope + payload freshness truth.
    public var isStale: Bool {
        if envelopeStale { return true }
        let status = (response?.freshness_status ?? "").lowercased()
        if status == "stale" || status == "unavailable" { return true }
        if let age = response?.staleness_seconds, age > 180 { return true }
        return false
    }

    public var stalenessAgeSeconds: Double? {
        response?.staleness_seconds ?? envelopeLagMs.map { $0 / 1000 }
    }

    // MARK: - Watchlist

    public func isWatched(_ symbol: String) -> Bool {
        watchlist.contains(symbol)
    }

    public func toggleWatchlist(_ symbol: String) {
        if watchlist.contains(symbol) {
            watchlist.remove(symbol)
        } else {
            watchlist.insert(symbol)
        }
        UserDefaults.standard.set(Array(watchlist).sorted(), forKey: Self.watchlistDefaultsKey)
    }

    // MARK: - Loading

    public func load(token: String?, baseURL: String) async {
        lastToken = token
        lastBaseURL = baseURL
        isLoading = !hasAnyData
        do {
            let resp: MobileMarketsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobileMarkets,
                token: token,
                baseURL: baseURL
            )
            apply(resp, transport: envelopeTransport ?? "http", stale: nil, lagMs: nil)
            error = nil
        } catch {
            if !hasAnyData { self.error = error.localizedDescription }
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        lastToken = token
        lastBaseURL = baseURL
        connectStream(token: token, baseURL: baseURL)
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                guard !Task.isCancelled else { break }
                if !isConnected {
                    // WS down — reconnect and keep the screen honest via HTTP poll.
                    connectStream(token: token, baseURL: baseURL)
                    await load(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
        stream.disconnect()
        streamLabel = "Disconnected"
        envelopeTransport = nil
    }

    public func refresh() async {
        await load(token: lastToken, baseURL: lastBaseURL)
    }

    // MARK: - WebSocket stream

    private var isConnected: Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connectStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileMarkets,
            intervalMs: 10_000
        ) else {
            streamLabel = "Offline"
            return
        }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStreamMessage(message)
        }
    }

    private func applyStreamMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobileMarketsResponse.self, from: message)
            apply(
                snapshot.payload,
                transport: snapshot.transport ?? "websocket",
                stale: snapshot.stale,
                lagMs: snapshot.lagMs
            )
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
        }
    }

    private func apply(_ payload: MobileMarketsResponse, transport: String, stale: Bool?, lagMs: Double?) {
        response = payload
        envelopeStale = stale ?? false
        envelopeLagMs = lagMs
        envelopeTransport = transport
        streamLabel = isStale ? "Stale" : (transport.lowercased().contains("ws") ? "Realtime" : "Poll")
        lastUpdated = payload.payload_generated_utc ?? payload.generated_utc
    }

    // MARK: - Sorting

    private func sorted(_ input: [MobileMarketRow]) -> [MobileMarketRow] {
        let out = input.sorted { lhs, rhs in
            switch sortKey {
            case .turnover:
                return rank(lhs.turnover_24h_usd, lhs.symbol) > rank(rhs.turnover_24h_usd, rhs.symbol)
            case .change24h:
                return rank(lhs.change_24h, lhs.symbol) > rank(rhs.change_24h, rhs.symbol)
            case .cascadeRisk:
                return rank(lhs.liquidation_cascade_risk, lhs.symbol) > rank(rhs.liquidation_cascade_risk, rhs.symbol)
            case .score:
                return rank(lhs.altdata_symbol_score, lhs.symbol) > rank(rhs.altdata_symbol_score, rhs.symbol)
            case .symbol:
                return lhs.symbol > rhs.symbol
            }
        }
        return sortDescending ? out : out.reversed()
    }

    /// Rows missing the sort metric always sink to the bottom (honesty: absent
    /// data never outranks real data), with symbol as a stable tiebreak.
    private func rank(_ value: Double?, _ symbol: String) -> (Double, String) {
        ((value?.isFinite == true ? value! : -Double.greatestFiniteMagnitude), symbol)
    }
}
