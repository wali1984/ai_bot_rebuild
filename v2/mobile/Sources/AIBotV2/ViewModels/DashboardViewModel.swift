import Foundation
import Observation

@MainActor
@Observable
public final class DashboardViewModel {

    public private(set) var dashboard: MobileDashboard?
    public private(set) var health: MobileHealth?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var dashboardStreamLabel = "Connecting"
    public private(set) var healthStreamLabel = "Connecting"
    public private(set) var lastStreamMessageAt: Date?

    private let dashboardSocket = WebSocketClient()
    private let healthSocket = WebSocketClient()
    private let streamIntervalMs = 1_000

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
    }

    public func connect(token: String?, baseURL: String) {
        isLoading = true
        error = nil
        dashboardStreamLabel = "Connecting"
        healthStreamLabel = "Connecting"

        guard let dashboardURL = resourceWebSocketURL(baseURL: baseURL, path: APIEndpoints.mobileDashboard),
              let healthURL = resourceWebSocketURL(baseURL: baseURL, path: APIEndpoints.mobileHealth) else {
            isLoading = false
            error = "Invalid WebSocket resource URL"
            dashboardStreamLabel = "Offline"
            healthStreamLabel = "Offline"
            return
        }

        dashboardSocket.connect(urlString: dashboardURL, token: token) { [weak self] message in
            self?.applyDashboardMessage(message)
        }
        healthSocket.connect(urlString: healthURL, token: token) { [weak self] message in
            self?.applyHealthMessage(message)
        }
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        connect(token: token, baseURL: baseURL)
    }

    public func stopAutoRefresh() {
        stopStreams()
    }

    public func stopStreams() {
        dashboardSocket.disconnect()
        healthSocket.disconnect()
        dashboardStreamLabel = "Disconnected"
        healthStreamLabel = "Disconnected"
    }

    public var streamSummary: String {
        "Dashboard \(dashboardStreamLabel) · Health \(healthStreamLabel)"
    }

    private func applyDashboardMessage(_ message: String) {
        do {
            dashboard = try decodeResourceMessage(MobileDashboard.self, from: message)
            dashboardStreamLabel = "Live"
            lastStreamMessageAt = Date()
            isLoading = false
            error = nil
        } catch {
            dashboardStreamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }

    private func applyHealthMessage(_ message: String) {
        do {
            health = try decodeResourceMessage(MobileHealth.self, from: message)
            healthStreamLabel = "Live"
            lastStreamMessageAt = Date()
            isLoading = false
            error = nil
        } catch {
            healthStreamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }

    private func resourceWebSocketURL(baseURL: String, path: String) -> String? {
        var baseWS = baseURL
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
        if baseWS.hasSuffix("/") {
            baseWS.removeLast()
        }
        var components = URLComponents(string: baseWS + APIEndpoints.wsResource)
        components?.queryItems = [
            URLQueryItem(name: "path", value: path),
            URLQueryItem(name: "interval_ms", value: String(streamIntervalMs)),
        ]
        return components?.string
    }

    private func decodeResourceMessage<T: Decodable>(_ type: T.Type, from message: String) throws -> T {
        let data = Data(message.utf8)
        let decoder = JSONDecoder()
        if let envelope = try? decoder.decode(ResourceEnvelope<T>.self, from: data),
           let payload = envelope.data {
            return payload
        }
        return try decoder.decode(T.self, from: data)
    }
}

private struct ResourceEnvelope<T: Decodable>: Decodable {
    let data: T?
    let stale: Bool?
}
