import Foundation
import Observation

@MainActor
@Observable
public final class PositionsViewModel {

    public private(set) var response: MobilePositionsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var sourceType: String?
    public private(set) var lastUpdatedAt: String?
    public private(set) var isStale = false
    public private(set) var streamWarnings: [String] = []
    public private(set) var missingFields: [String] = []

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 1_500

    public var positions: [MobilePosition] { response?.positions ?? [] }
    public var closedPositions: [MobilePosition] { response?.closed_positions ?? [] }
    public var historicalPositions: [MobilePosition] { response?.historical_positions ?? response?.closed_positions ?? [] }
    public var summary: PositionSummary? { response?.summary }

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
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
                path: APIEndpoints.mobilePositions,
                token: token,
                baseURL: baseURL
            )
            sourceType = "api"
            lastUpdatedAt = response?.generated_utc
            isStale = false
            streamWarnings = response?.warnings ?? []
            missingFields = []
            WatchSyncCenter.shared.updatePositions(response)
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobilePositionsResponse.self, from: message)
            response = snapshot.payload
            streamLabel = "Realtime"
            sourceType = snapshot.sourceType ?? snapshot.transport ?? "websocket"
            lastUpdatedAt = snapshot.timestamp ?? snapshot.receivedAt ?? snapshot.payload.generated_utc
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
}
