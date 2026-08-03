import Foundation
import Observation

@MainActor
@Observable
public final class ProviderStatusViewModel {

    public private(set) var providerStatus: ControlCenterProviderStatus?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdatedAt: String?
    public private(set) var sourceType: String?
    public private(set) var transport: String?
    public private(set) var lagMs: Double?
    public private(set) var isStale = false
    public private(set) var streamWarnings: [String] = []
    public private(set) var missingFields: [String] = []

    private let providerSocket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000

    public var providers: [EnterpriseProviderCard] {
        providerStatus?.data.providers ?? []
    }

    public var activeProviderCount: Int {
        providerStatus?.data.provider_count ?? providers.count
    }

    // MARK: - Coverage rollups (derived from providerDashboardTone truth)

    public var toneCounts: [String: Int] {
        providers.reduce(into: [:]) { counts, provider in
            counts[provider.providerDashboardTone, default: 0] += 1
        }
    }

    public var greenProviderCount: Int { toneCounts["green"] ?? 0 }
    public var yellowProviderCount: Int { toneCounts["yellow"] ?? 0 }
    public var redProviderCount: Int { toneCounts["red"] ?? 0 }
    public var grayProviderCount: Int { (toneCounts["gray"] ?? 0) + (toneCounts["grey"] ?? 0) }

    /// Severity-first display order (red -> yellow -> gray -> green), then by
    /// payload richness (desc), then provider id. Surfaces degraded providers at
    /// the top without mutating the canonical `providers` list used for rollups.
    public var sortedProviders: [EnterpriseProviderCard] {
        func rank(_ tone: String) -> Int {
            switch tone {
            case "red": return 0
            case "yellow": return 1
            case "gray", "grey": return 2
            default: return 3
            }
        }
        return providers.sorted { lhs, rhs in
            let lr = rank(lhs.providerDashboardTone)
            let rr = rank(rhs.providerDashboardTone)
            if lr != rr { return lr < rr }
            let lp = lhs.actual_payload_count ?? 0
            let rp = rhs.actual_payload_count ?? 0
            if lp != rp { return lp > rp }
            return lhs.provider < rhs.provider
        }
    }

    /// Providers that are not fully green (red/yellow/gray), severity-ordered,
    /// for the attention callout. Honest empty when every provider is green.
    public var degradedProviders: [EnterpriseProviderCard] {
        sortedProviders.filter { $0.providerDashboardTone != "green" }
    }

    public var totalPayloadCount: Int {
        providers.compactMap(\.actual_payload_count).reduce(0, +)
    }

    public var heartbeatOnlyGreenCount: Int {
        providerStatus?.data.heartbeat_only_green_count ?? 0
    }

    /// Freshness age in seconds for the staleness chip: envelope lag wins,
    /// then the canonical publisher staleness field. Nil when unknown.
    public var freshnessAgeSeconds: Double? {
        if let lagMs { return lagMs / 1000 }
        return providerStatus?.staleness_seconds
    }

    public var requiredAltDataProvidersVisible: Bool {
        let ids = Set(providers.map { $0.provider.lowercased() })
        return ids.contains("coinglass") && ids.contains("moralis")
    }

    public var retiredActiveProviders: [String] {
        let retired = Set(["alpha_vantage", "alphavantage"])
        return providers.map(\.provider).filter { retired.contains($0.lowercased()) }
    }

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func connect(token: String?, baseURL: String) {
        isLoading = providerStatus == nil
        error = nil
        streamLabel = "Connecting"

        guard let providerURL = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.providersStatus,
            intervalMs: streamIntervalMs
        ) else {
            isLoading = false
            error = "Invalid provider WebSocket resource URL"
            streamLabel = "Offline"
            return
        }

        providerSocket.connect(urlString: providerURL, token: token) { [weak self] message in
            self?.applyProviderMessage(message)
        }
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !providerStreamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    await loadFallback(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        providerSocket.disconnect()
        streamLabel = "Disconnected"
    }

    private var providerStreamIsConnected: Bool {
        if case .connected = providerSocket.state { return true }
        return false
    }

    private func loadFallback(token: String?, baseURL: String) async {
        do {
            let status: ControlCenterProviderStatus = try await APIClient.shared.get(
                path: APIEndpoints.providersStatus,
                token: token,
                baseURL: baseURL
            )
            providerStatus = status
            sourceType = "api"
            transport = nil
            lagMs = nil
            lastUpdatedAt = status.generated_at_utc
            isStale = status.freshness_status?.lowercased() == "stale"
            streamWarnings = []
            missingFields = []
            isLoading = false
            error = nil
            if streamLabel != "Realtime" {
                streamLabel = isStale ? "Stale" : "Poll"
            }
        } catch {
            if providerStatus == nil {
                self.error = error.localizedDescription
                isLoading = false
                streamLabel = "Offline"
            } else {
                streamLabel = "Last good"
                self.error = nil
            }
        }
    }

    private func applyProviderMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(ControlCenterProviderStatus.self, from: message)
            providerStatus = snapshot.payload
            sourceType = snapshot.sourceType ?? snapshot.source
            transport = snapshot.transport ?? "websocket"
            lagMs = snapshot.lagMs
            lastUpdatedAt = snapshot.timestamp ?? snapshot.payload.generated_at_utc
            isStale = snapshot.stale || snapshot.payload.freshness_status?.lowercased() == "stale"
            streamWarnings = snapshot.warnings
            missingFields = snapshot.missingFields
            streamLabel = isStale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if providerStatus == nil {
                self.error = error.localizedDescription
                isLoading = false
            }
        }
    }
}
