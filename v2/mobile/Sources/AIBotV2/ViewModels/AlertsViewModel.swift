import Foundation
import Observation

@Observable
public final class AlertsViewModel {

    public private(set) var response: MobileAlertsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?

    public var alerts: [MobileAlert] { response?.alerts ?? [] }
    public var criticalAlerts: [MobileAlert] { alerts.filter { $0.severity == "critical" } }

    public func load(token: String?, baseURL: String, limit: Int = 30) async {
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

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        refreshTask = Task {
            while !Task.isCancelled {
                await load(token: token, baseURL: baseURL)
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
