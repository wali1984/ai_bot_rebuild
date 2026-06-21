import Foundation
import Observation

@Observable
public final class AdminViewModel {

    public private(set) var summary: MobileAdminSummary?
    public private(set) var riskStatus: MobileRiskStatus?
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            async let adminSummary: MobileAdminSummary = APIClient.shared.get(
                path: APIEndpoints.mobileAdminSummary,
                token: token,
                baseURL: baseURL
            )
            async let risk: MobileRiskStatus = APIClient.shared.get(
                path: APIEndpoints.mobileRiskStatus,
                token: token,
                baseURL: baseURL
            )
            let (a, r) = try await (adminSummary, risk)
            summary = a
            riskStatus = r
        } catch let err as APIError where err.isUnauthorized {
            self.error = "Admin access required"
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
                try? await Task.sleep(for: .seconds(15))
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
