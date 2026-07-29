import Foundation
import Observation

// MARK: - Executions (History) view model
//
// Data sources (all real):
//   /api/v2/mobile/positions      — closed/historical trade rows (WS stream + poll)
//   /api/v2/mobile/paper-summary  — pnl_windows[1d/7d/30d] backend NET rollups
//                                   (winner-flag win rate — never sign(pnl))
//
// Honesty rules honored here:
//   - Win rate is NEVER recomputed from realized_pnl sign. Backend winner-flag
//     values are shown when present; otherwise the UI renders "—".
//   - Client-side window charts are explicitly labelled as derived from
//     closed-trade rows (per-bucket realized PnL sums + cumulative curve).

// MARK: Window selection

public enum ActivityWindow: String, CaseIterable, Identifiable {
    case oneDay = "1D"
    case oneWeek = "1W"
    case thirtyDays = "30D"
    case all = "ALL"

    public var id: String { rawValue }

    /// Lookback horizon in seconds (nil = unbounded / ALL).
    public var horizonSeconds: Double? {
        switch self {
        case .oneDay:     return 86_400
        case .oneWeek:    return 7 * 86_400
        case .thirtyDays: return 30 * 86_400
        case .all:        return nil
        }
    }

    /// Matching backend pnl_windows key (nil = no backend rollup for ALL).
    public var backendKey: String? {
        switch self {
        case .oneDay:     return "1d"
        case .oneWeek:    return "7d"
        case .thirtyDays: return "30d"
        case .all:        return nil
        }
    }
}

// MARK: Row filters

/// Win/loss chips are labelled by realized-PnL sign on purpose: per-row winner
/// flags are not part of the mobile positions payload, and the honesty rule
/// forbids presenting sign(pnl) as winner truth.
public enum ActivityFilter: String, CaseIterable, Identifiable {
    case all = "ALL"
    case long = "LONG"
    case short = "SHORT"
    case pnlPositive = "PNL +"
    case pnlNegative = "PNL −"

    public var id: String { rawValue }
}

// MARK: Derived window stats (client-side, from closed-trade rows)

public struct ActivityWindowStats: Equatable {
    public let window: ActivityWindow
    public let tradeCount: Int
    public let realizedSum: Double
    /// Per-bucket realized PnL sums, oldest → newest, zero-filled.
    public let buckets: [Double]
    /// "HOUR" for 1D, "DAY" otherwise.
    public let bucketUnit: String
    /// Cumulative realized PnL over trades in window (starts at 0).
    public let cumulative: [Double]
}

// MARK: - Slim paper-summary envelope
// MobilePaperSummary does not yet expose pnl_windows; decode only what this
// screen needs (Decodable ignores the rest of the payload).

private struct ActivityPaperWindowsEnvelope: Decodable {
    struct PnLBlock: Decodable {
        let realized_usd: Double?
        let win_rate_pct: Double?
        let pnl_trusted: Bool?
    }

    let generated_utc: String?
    let live_gate: String?
    let pnl: PnLBlock?
    let pnl_windows: [PnLWindow]?
}

// MARK: - View model

@MainActor
@Observable
public final class ActivityViewModel {

    public private(set) var closedTrades: [MobilePosition] = []
    public private(set) var pnlWindows: [PnLWindow] = []
    /// Backend all-time realized NET PnL (paper-summary pnl.realized_usd).
    public private(set) var backendRealizedAllUsd: Double?
    /// Backend all-time win rate percentage (heartbeat winner count; nil = unevaluated).
    public private(set) var backendWinRatePct: Double?
    public private(set) var pnlTrusted: Bool?
    public private(set) var liveGate: String?

    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastUpdated: String?
    public private(set) var streamLabel = "Connecting"

    // Envelope freshness truth for StalenessChip.
    public private(set) var envelopeStale = false
    public private(set) var envelopeLagMs: Double?
    public private(set) var envelopeTransport: String?
    public private(set) var lastSuccessAt: Date?

    private let stream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?
    private var lastSessionId: String?
    private var lastEpoch: Int?

    public var ageSeconds: Double? {
        lastSuccessAt.map { Date().timeIntervalSince($0) }
    }

    public var hasAnyData: Bool {
        !closedTrades.isEmpty || !pnlWindows.isEmpty
    }

    // MARK: Loading

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        async let positionsCall: MobilePositionsResponse? = fetchPositions(token: token, baseURL: baseURL)
        async let windowsCall: ActivityPaperWindowsEnvelope? = fetchWindows(token: token, baseURL: baseURL)
        let (positions, windows) = await (positionsCall, windowsCall)

        if let positions {
            guard applyPositions(positions) else {
                self.error = "Ignored stale paper-account epoch response"
                isLoading = false
                return
            }
            envelopeTransport = "http"
            envelopeStale = false
            envelopeLagMs = nil
            lastSuccessAt = Date()
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } else if closedTrades.isEmpty && windows == nil {
            // Only surface a full-screen error when we have nothing to show.
            self.error = self.error ?? "Execution history unavailable"
        }
        if let windows {
            applyWindows(windows)
        }
        isLoading = false
    }

    private func fetchPositions(token: String?, baseURL: String) async -> MobilePositionsResponse? {
        do {
            return try await APIClient.shared.get(
                path: APIEndpoints.mobilePositionsCurrentSession,
                token: token,
                baseURL: baseURL
            )
        } catch {
            if closedTrades.isEmpty { self.error = error.localizedDescription }
            return nil
        }
    }

    private func fetchWindows(token: String?, baseURL: String) async -> ActivityPaperWindowsEnvelope? {
        do {
            return try await APIClient.shared.get(
                path: APIEndpoints.mobilePaperSummaryCurrentSession,
                token: token,
                baseURL: baseURL
            )
        } catch {
            // Window rollups are additive; keep last-known values on failure.
            return nil
        }
    }

    @discardableResult
    private func applyPositions(_ response: MobilePositionsResponse) -> Bool {
        guard acceptsCurrentPaperSessionFrame(
            incomingSessionId: response.paper_session_id,
            incomingEpoch: response.paper_account_epoch,
            activeSessionId: lastSessionId,
            activeEpoch: lastEpoch
        ) else { return false }
        lastSessionId = response.paper_session_id
        lastEpoch = response.paper_account_epoch
        // historical_positions is the deeper slice (up to 200 rows) of the same
        // v2:paper:closed_trades source; closed_positions is its first 50.
        closedTrades = response.historical_positions ?? response.closed_positions ?? []
        if (liveGate ?? "").isEmpty {
            liveGate = response.live_gate
        }
        error = nil
        return true
    }

    private func applyWindows(_ envelope: ActivityPaperWindowsEnvelope) {
        pnlWindows = envelope.pnl_windows ?? []
        backendRealizedAllUsd = envelope.pnl?.realized_usd
        backendWinRatePct = envelope.pnl?.win_rate_pct
        pnlTrusted = envelope.pnl?.pnl_trusted
        if let gate = envelope.live_gate, !gate.isEmpty {
            liveGate = gate
        }
    }

    // MARK: Auto refresh (20s poll + 8s WS stream, matching sibling screens)

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connectStream(token: token, baseURL: baseURL)
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                if !Task.isCancelled {
                    if case .connected = stream.state {} else {
                        connectStream(token: token, baseURL: baseURL)
                    }
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
    }

    private func connectStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobilePositions,
            queryItems: APIEndpoints.currentPaperScopeQueryItems,
            intervalMs: 8_000
        ) else { return }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStream(message)
        }
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobilePositionsResponse.self, from: message)
            guard applyPositions(snapshot.payload) else {
                streamLabel = "Stale epoch ignored"
                return
            }
            streamLabel = "Realtime"
            envelopeStale = snapshot.stale
            envelopeLagMs = snapshot.lagMs
            envelopeTransport = snapshot.transport ?? "websocket"
            lastSuccessAt = Date()
            isLoading = false
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } catch {
            streamLabel = "Invalid"
        }
    }

    // MARK: Backend window lookup

    public func backendWindow(for window: ActivityWindow) -> PnLWindow? {
        guard let key = window.backendKey else { return nil }
        return pnlWindows.first { $0.window.lowercased() == key }
    }

    // MARK: Window membership + derived stats

    public func trades(in window: ActivityWindow) -> [MobilePosition] {
        guard let horizon = window.horizonSeconds else { return closedTrades }
        let now = Date()
        return closedTrades.filter { trade in
            guard let closed = Self.parseISODate(trade.closed_at ?? trade.opened_at) else { return false }
            return now.timeIntervalSince(closed) <= horizon
        }
    }

    /// Per-bucket realized PnL + cumulative curve, derived from closed-trade
    /// rows (`closed_at` timestamps). Labelled as derived in the UI.
    public func stats(for window: ActivityWindow) -> ActivityWindowStats {
        let now = Date()
        let dated: [(date: Date, pnl: Double)] = closedTrades.compactMap { trade in
            guard let closed = Self.parseISODate(trade.closed_at ?? trade.opened_at) else { return nil }
            if let horizon = window.horizonSeconds, now.timeIntervalSince(closed) > horizon { return nil }
            return (closed, trade.realized_pnl)
        }
        let sorted = dated.sorted { $0.date < $1.date }

        var cumulative: [Double] = []
        if !sorted.isEmpty {
            cumulative.reserveCapacity(sorted.count + 1)
            cumulative.append(0)
            var running = 0.0
            for entry in sorted {
                running += entry.pnl
                cumulative.append(running)
            }
        }

        let bucketSeconds: Double = window == .oneDay ? 3_600 : 86_400
        let bucketCount: Int
        switch window {
        case .oneDay:     bucketCount = 24
        case .oneWeek:    bucketCount = 7
        case .thirtyDays: bucketCount = 30
        case .all:
            if let earliest = sorted.first?.date {
                let spanDays = Int(ceil(now.timeIntervalSince(earliest) / 86_400))
                bucketCount = min(max(spanDays, 1), 60)
            } else {
                bucketCount = 0
            }
        }

        var buckets = [Double](repeating: 0, count: bucketCount)
        if bucketCount > 0 {
            for entry in sorted {
                let age = max(now.timeIntervalSince(entry.date), 0)
                let offset = Int(age / bucketSeconds)
                let index = bucketCount - 1 - offset
                if index >= 0 && index < bucketCount {
                    buckets[index] += entry.pnl
                }
            }
        }

        return ActivityWindowStats(
            window: window,
            tradeCount: sorted.count,
            realizedSum: sorted.reduce(0) { $0 + $1.pnl },
            buckets: buckets,
            bucketUnit: window == .oneDay ? "HOUR" : "DAY",
            cumulative: cumulative
        )
    }

    // MARK: ISO date parsing (backend emits e.g. "2026-07-17T22:48:28.020Z")

    private static let isoFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoPlain: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let fallbackFormats = [
        "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX",
        "yyyy-MM-dd'T'HH:mm:ss.SSSSSS",
        "yyyy-MM-dd'T'HH:mm:ss",
        "yyyy-MM-dd HH:mm:ss",
    ]

    static func parseISODate(_ raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        let value = String(raw.prefix(40))
        if let date = isoFractional.date(from: value) { return date }
        if let date = isoPlain.date(from: value) { return date }
        for format in fallbackFormats {
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone(identifier: "UTC")
            formatter.dateFormat = format
            if let date = formatter.date(from: value) { return date }
        }
        return nil
    }
}
