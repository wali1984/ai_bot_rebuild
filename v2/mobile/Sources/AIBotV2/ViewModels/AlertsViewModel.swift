import Foundation
import Observation

@MainActor
@Observable
public final class AlertsViewModel {

    public private(set) var response: MobileAlertsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 5_000

    public var alerts: [MobileAlert] { response?.alerts ?? [] }
    public var criticalAlerts: [MobileAlert] { alerts.filter { $0.severity == "critical" } }

    public func load(token: String?, baseURL: String, limit: Int = 30) async {
        connect(token: token, baseURL: baseURL, limit: limit)
        await loadFallback(token: token, baseURL: baseURL, limit: limit)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(45))
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

    private func connect(token: String?, baseURL: String, limit: Int = 30) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileAlerts,
            queryItems: [URLQueryItem(name: "limit", value: "\(limit)")],
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

    private func loadFallback(token: String?, baseURL: String, limit: Int = 30) async {
        isLoading = true
        error = nil
        do {
            response = try await APIClient.shared.get(
                path: APIEndpoints.mobileAlerts,
                queryItems: [URLQueryItem(name: "limit", value: "\(limit)")],
                token: token,
                baseURL: baseURL
            )
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func applyStream(_ message: String) {
        do {
            response = try decodeMobileResourceMessage(MobileAlertsResponse.self, from: message)
            streamLabel = "Live"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }
}
