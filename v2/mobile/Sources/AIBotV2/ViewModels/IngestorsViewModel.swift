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

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000

    public var ingestors: [IngestorRowModel] {
        statusResponse?.data.ingestors ?? []
    }

    public var liveCount: Int { statusResponse?.data.counts?.live ?? ingestors.filter { $0.status == "live" }.count }
    public var totalCount: Int { statusResponse?.data.counts?.total ?? ingestors.count }

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

/// Streams `/api/v2/ingestors/{name}/metrics` for one ingestor's detail page.
@MainActor
@Observable
public final class IngestorDetailViewModel {

    public let name: String
    public private(set) var metrics: IngestorMetricsData?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?

    public init(name: String) { self.name = name }

    public var rows: [IngestorMetricRow] { metrics?.rows ?? [] }

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
            if let data = resp.data { metrics = data }
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
            if let data = snapshot.payload.data { metrics = data }
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            if metrics == nil { self.error = error.localizedDescription }
        }
    }
}
