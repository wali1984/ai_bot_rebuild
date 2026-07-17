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
            lastUpdatedAt = status.generated_at_utc
            isStale = status.freshness_status?.lowercased() == "stale"
            streamWarnings = []
            missingFields = []
            isLoading = false
            error = nil
        } catch {
            if providerStatus == nil {
                self.error = error.localizedDescription
                isLoading = false
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
