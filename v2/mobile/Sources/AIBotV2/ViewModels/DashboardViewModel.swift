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
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func connect(token: String?, baseURL: String) {
        isLoading = true
        error = nil
        dashboardStreamLabel = "Connecting"
        healthStreamLabel = "Connecting"

        guard let dashboardURL = APIEndpoints.wsResourceURL(baseURL: baseURL, path: APIEndpoints.mobileDashboard, intervalMs: streamIntervalMs),
              let healthURL = APIEndpoints.wsResourceURL(baseURL: baseURL, path: APIEndpoints.mobileHealth, intervalMs: streamIntervalMs) else {
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

    private func loadFallback(token: String?, baseURL: String) async {
        do {
            async let dashboardFallback: MobileDashboard = APIClient.shared.get(
                path: APIEndpoints.mobileDashboard,
                token: token,
                baseURL: baseURL
            )
            async let healthFallback: MobileHealth = APIClient.shared.get(
                path: APIEndpoints.mobileHealth,
                token: token,
                baseURL: baseURL
            )
            let (d, h) = try await (dashboardFallback, healthFallback)
            dashboard = d
            health = h
            isLoading = false
            error = nil
        } catch {
            if dashboard == nil && health == nil {
                self.error = error.localizedDescription
                isLoading = false
            }
        }
    }

    private func applyDashboardMessage(_ message: String) {
        do {
            dashboard = try decodeMobileResourceMessage(MobileDashboard.self, from: message)
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
            health = try decodeMobileResourceMessage(MobileHealth.self, from: message)
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

}
