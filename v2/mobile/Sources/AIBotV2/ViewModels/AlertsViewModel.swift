import Foundation
import Observation

// MARK: - Severity taxonomy

/// Normalized severity buckets for market alerts. Raw severities come from the
/// backend `_compact_alert` contract (`critical` / `error` / `warning`, with
/// `info` as the default); unknown values honestly map to `.info`.
public enum AlertSeverityBucket: String, CaseIterable, Identifiable, Comparable {
    case critical
    case error
    case warning
    case info

    public var id: String { rawValue }

    public init(raw: String) {
        switch raw.trimmingCharacters(in: .whitespaces).lowercased() {
        case "critical", "fatal":  self = .critical
        case "error", "failure":   self = .error
        case "warning", "warn":    self = .warning
        default:                   self = .info
        }
    }

    public var label: String { rawValue.uppercased() }

    /// Lower rank = more severe.
    public var rank: Int {
        switch self {
        case .critical: return 0
        case .error:    return 1
        case .warning:  return 2
        case .info:     return 3
        }
    }

    public static func < (lhs: AlertSeverityBucket, rhs: AlertSeverityBucket) -> Bool {
        lhs.rank < rhs.rank
    }
}

// MARK: - ViewModel

@MainActor
@Observable
public final class AlertsViewModel {

    // MARK: Published state

    public private(set) var response: MobileAlertsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"

    // Envelope truth fields from the shared WS resource stream / HTTP poll.
    public private(set) var snapshotStale = false
    public private(set) var snapshotLagMs: Double?
    public private(set) var snapshotTransport: String?
    public private(set) var lastUpdatedAt: Date?

    /// Ticks periodically so age/staleness re-derive without new payloads.
    public private(set) var freshnessTick = Date()

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 5_000
    private let alertLimit = 50
    private let tickSeconds = 15
    private let pollAfterSeconds = 30
    private let staleAfterSeconds: Double = 90

    // MARK: Derived collections

    public var alerts: [MobileAlert] { response?.alerts ?? [] }

    public func bucket(for alert: MobileAlert) -> AlertSeverityBucket {
        AlertSeverityBucket(raw: alert.severity)
    }

    public var severityCounts: [AlertSeverityBucket: Int] {
        var counts: [AlertSeverityBucket: Int] = [:]
        for alert in alerts {
            counts[bucket(for: alert), default: 0] += 1
        }
        return counts
    }

    public var criticalAlerts: [MobileAlert] {
        alerts.filter { bucket(for: $0) == .critical }
    }

    public struct SymbolGroup: Identifiable {
        public let symbol: String
        public let alerts: [MobileAlert]
        public let worst: AlertSeverityBucket
        public var id: String { symbol }
    }

    /// Alerts grouped by symbol. The backend list is newest-first (LPUSH
    /// order), so groups are ordered by each symbol's newest alert and rows
    /// inside a group stay newest-first. Alerts without a symbol group under
    /// "SYSTEM".
    public func groups(filter: AlertSeverityBucket?) -> [SymbolGroup] {
        let source: [MobileAlert]
        if let filter {
            source = alerts.filter { bucket(for: $0) == filter }
        } else {
            source = alerts
        }
        var order: [String] = []
        var grouped: [String: [MobileAlert]] = [:]
        for alert in source {
            let key = alert.symbol.isEmpty ? "SYSTEM" : alert.symbol
            if grouped[key] == nil { order.append(key) }
            grouped[key, default: []].append(alert)
        }
        return order.map { symbol in
            let items = grouped[symbol] ?? []
            let worst = items.map { bucket(for: $0) }.min() ?? .info
            return SymbolGroup(symbol: symbol, alerts: items, worst: worst)
        }
    }

    // MARK: Freshness truth

    public var ageSeconds: Double? {
        guard let lastUpdatedAt else { return nil }
        return max(freshnessTick.timeIntervalSince(lastUpdatedAt), 0)
    }

    /// Derived freshness for the StalenessChip — never a hardcoded "LIVE".
    var freshnessMode: FreshnessMode {
        if response == nil { return error == nil ? .poll : .offline }
        if snapshotStale { return .stale }
        if let age = ageSeconds, age > staleAfterSeconds { return .stale }
        if streamIsConnected, streamLabel == "Realtime" { return .realtime }
        return .poll
    }

    var freshnessAgeText: String? {
        guard let age = ageSeconds else { return nil }
        return NerVyxFormat.age(age)
    }

    // MARK: Lifecycle

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            var secondsSincePoll = 0
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(tickSeconds))
                if Task.isCancelled { break }
                freshnessTick = Date()
                if streamIsConnected {
                    secondsSincePoll = 0
                } else {
                    secondsSincePoll += tickSeconds
                    if secondsSincePoll >= pollAfterSeconds {
                        secondsSincePoll = 0
                        connect(token: token, baseURL: baseURL)
                        await loadFallback(token: token, baseURL: baseURL)
                    }
                }
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        stream.disconnect()
        streamLabel = "Disconnected"
    }

    // MARK: Internals

    private var streamIsConnected: Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connect(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileAlerts,
            queryItems: [URLQueryItem(name: "limit", value: "\(alertLimit)")],
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
            response = try await APIClient.shared.get(
                path: APIEndpoints.mobileAlerts,
                queryItems: [URLQueryItem(name: "limit", value: "\(alertLimit)")],
                token: token,
                baseURL: baseURL
            )
            snapshotStale = false
            snapshotLagMs = nil
            snapshotTransport = "http"
            lastUpdatedAt = Date()
            freshnessTick = Date()
            WatchSyncCenter.shared.updateAlerts(response)
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobileAlertsResponse.self, from: message)
            response = snapshot.payload
            snapshotStale = snapshot.stale
            snapshotLagMs = snapshot.lagMs
            snapshotTransport = snapshot.transport ?? "websocket"
            lastUpdatedAt = Date()
            freshnessTick = Date()
            streamLabel = "Realtime"
            WatchSyncCenter.shared.updateAlerts(response)
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }
}
