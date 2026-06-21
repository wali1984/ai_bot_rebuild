import Foundation
import Observation

@Observable
public final class PositionsViewModel {

    public private(set) var response: MobilePositionsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?

    public var positions: [MobilePosition] { response?.positions ?? [] }
    public var summary: PositionSummary? { response?.summary }

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            response = try await APIClient.shared.get(
                path: APIEndpoints.mobilePositions,
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
                try? await Task.sleep(for: .seconds(8))
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
