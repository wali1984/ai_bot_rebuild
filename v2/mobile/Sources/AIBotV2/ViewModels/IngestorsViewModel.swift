import Foundation
import Observation

/// Streams `/api/v2/ingestors/status` over the shared `/api/v2/ws/resource`
/// WebSocket (with HTTP fallback), mirroring `ProviderStatusViewModel`. Read-only.
@MainActor
@Observable
public final class IngestorsViewModel {

    public private(set) var statusResponse: IngestorStatusResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdatedAt: String?
    public private(set) var sourceType: String?
    public private(set) var isStale = false
    /// Envelope transport truth for the StalenessChip: "websocket" while the
    /// resource stream delivers, "http" when the poll fallback served the last
    /// good snapshot. Never hardcoded — derived from real snapshot metadata.
    public private(set) var transport: String?

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000

    public var ingestors: [IngestorRowModel] {
        statusResponse?.data.ingestors ?? []
    }

    public var liveCount: Int { statusResponse?.data.counts?.live ?? ingestors.filter { $0.status == "live" }.count }
    public var totalCount: Int { statusResponse?.data.counts?.total ?? ingestors.count }

    /// Per-status-class counts computed from the real rows (the backend counts
    /// block omits `upstream_error`, so rows are the honest source of truth).
    public var statusCounts: [String: Int] {
        ingestors.reduce(into: [:]) { acc, row in
            acc[row.status.lowercased(), default: 0] += 1
        }
    }

    /// Canonical delivery-status classes in operator-priority order. Drives the
    /// summary donut and the per-class count chips so every class is always
    /// surfaced (including zero counts the backend `counts` block omits).
    public static let canonicalStatusOrder = ["live", "stale", "upstream_error", "offline", "not_started"]

    /// Full status breakdown in canonical order with real counts (0 when a class
    /// is absent), followed by any non-canonical status the feed actually emits.
    /// No class is invented — extras come only from live rows.
    public var orderedStatusBreakdown: [(status: String, count: Int)] {
        let counts = statusCounts
        var out: [(status: String, count: Int)] = Self.canonicalStatusOrder.map { (status: $0, count: counts[$0] ?? 0) }
        let extras = counts.keys
            .filter { !Self.canonicalStatusOrder.contains($0) }
            .sorted()
        for key in extras { out.append((status: key, count: counts[key] ?? 0)) }
        return out
    }

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func connect(token: String?, baseURL: String) {
        isLoading = statusResponse == nil
        error = nil
        streamLabel = "Connecting"

        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.ingestorsStatus,
            intervalMs: streamIntervalMs
        ) else {
            isLoading = false
            error = "Invalid ingestor WebSocket resource URL"
            streamLabel = "Offline"
            return
        }

        socket.connect(urlString: url, token: token) { [weak self] message in
            self?.applyMessage(message)
        }
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    await loadFallback(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        socket.disconnect()
        streamLabel = "Disconnected"
    }

    private var streamIsConnected: Bool {
        if case .connected = socket.state { return true }
        return false
    }

    private func loadFallback(token: String?, baseURL: String) async {
        do {
            let status: IngestorStatusResponse = try await APIClient.shared.get(
                path: APIEndpoints.ingestorsStatus,
                token: token,
                baseURL: baseURL
            )
            statusResponse = status
            sourceType = status.source_type ?? "api"
            lastUpdatedAt = status.generated_at_utc
            isStale = status.stale ?? (status.freshness_status?.lowercased() == "stale")
            if !streamIsConnected { transport = "http" }
            isLoading = false
            error = nil
        } catch {
            if statusResponse == nil {
                self.error = error.localizedDescription
                isLoading = false
            } else {
                streamLabel = "Last good"
                self.error = nil
            }
        }
    }

    private func applyMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(IngestorStatusResponse.self, from: message)
            statusResponse = snapshot.payload
            sourceType = snapshot.sourceType ?? snapshot.source
            lastUpdatedAt = snapshot.timestamp ?? snapshot.payload.generated_at_utc
            isStale = snapshot.stale || snapshot.payload.stale == true
            transport = snapshot.transport ?? "websocket"
            streamLabel = isStale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if statusResponse == nil {
                self.error = error.localizedDescription
                isLoading = false
            }
        }
    }
}

/// Streams `/api/v2/ingestors/{name}/metrics` for one ingestor's detail page,
/// recording a client-side rolling trend series per symbol so each row can
/// render a real sparkline of its primary numeric (price where available).
@MainActor
@Observable
public final class IngestorDetailViewModel {

    public let name: String
    public private(set) var metrics: IngestorMetricsData?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var transport: String?
    public private(set) var isStale = false

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private var trendSeries: [String: RollingSeries] = [:]

    public init(name: String) { self.name = name }

    public var rows: [IngestorMetricRow] { metrics?.rows ?? [] }

    /// Rolling history of the row's primary numeric (deduped by RollingSeries).
    /// Empty or single-point histories mean "not enough live ticks yet" — the
    /// view must skip the sparkline rather than fake a trend.
    func trendValues(for rowID: String) -> [Double] {
        trendSeries[rowID]?.values ?? []
    }

    public func start(token: String?, baseURL: String) {
        stop()
        isLoading = metrics == nil
        let path = APIEndpoints.ingestorMetrics(name: name)
        if let url = APIEndpoints.wsResourceURL(baseURL: baseURL, path: path, intervalMs: 2_000) {
            socket.connect(urlString: url, token: token) { [weak self] message in
                self?.apply(message)
            }
        }
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if case .connected = socket.state { continue }
                await loadFallback(token: token, baseURL: baseURL)
            }
        }
    }

    public func stop() {
        fallbackTask?.cancel()
        fallbackTask = nil
        socket.disconnect()
    }

    private func loadFallback(token: String?, baseURL: String) async {
        do {
            let resp: IngestorMetricsResponse = try await APIClient.shared.get(
                path: APIEndpoints.ingestorMetrics(name: name),
                token: token,
                baseURL: baseURL
            )
            if let data = resp.data {
                metrics = data
                recordTrends(data.rows)
            }
            isStale = resp.stale ?? false
            if socketConnected == false { transport = "http" }
            streamLabel = "Live"
            isLoading = false
            error = nil
        } catch {
            if metrics == nil { self.error = error.localizedDescription; isLoading = false }
        }
    }

    private func apply(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(IngestorMetricsResponse.self, from: message)
            if let data = snapshot.payload.data {
                metrics = data
                recordTrends(data.rows)
            }
            isStale = snapshot.stale || snapshot.payload.stale == true
            transport = snapshot.transport ?? "websocket"
            streamLabel = isStale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            if metrics == nil { self.error = error.localizedDescription }
        }
    }

    private var socketConnected: Bool {
        if case .connected = socket.state { return true }
        return false
    }

    private func recordTrends(_ rows: [IngestorMetricRow]) {
        for row in rows {
            guard let value = row.primaryTrendValue else { continue }
            var series = trendSeries[row.id] ?? RollingSeries(capacity: 40)
            series.append(value)
            trendSeries[row.id] = series
        }
    }
}

// MARK: - Primary trend metric selection (real payload fields only)

extension IngestorMetricRow {
    /// The row's primary numeric for trend charting: last price when the feed
    /// publishes one, otherwise the first (alphabetical, deterministic) generic
    /// numeric field. Nil when the payload carries no numeric — no fake data.
    var primaryTrendValue: Double? {
        if let last_price { return last_price }
        return numeric_fields?.sorted(by: { $0.key < $1.key }).first?.value
    }

    var primaryTrendLabel: String? {
        if last_price != nil { return "price" }
        return numeric_fields?.sorted(by: { $0.key < $1.key }).first?.key
    }
}
