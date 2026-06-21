import Foundation
import Observation

@Observable
public final class DashboardViewModel {

    public private(set) var dashboard: MobileDashboard?
    public private(set) var health: MobileHealth?
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?
    private let refreshInterval: TimeInterval = 10

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            async let dash: MobileDashboard = APIClient.shared.get(
                path: APIEndpoints.mobileDashboard,
                token: token,
                baseURL: baseURL
            )
            async let hlth: MobileHealth = APIClient.shared.get(
                path: APIEndpoints.mobileHealth,
                token: token,
                baseURL: baseURL
            )
            let (d, h) = try await (dash, hlth)
            dashboard = d
            health = h
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
                try? await Task.sleep(for: .seconds(refreshInterval))
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
