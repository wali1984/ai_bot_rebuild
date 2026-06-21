import Foundation
import Observation

@Observable
public final class PaperViewModel {

    public private(set) var summary: MobilePaperSummary?
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            summary = try await APIClient.shared.get(
                path: APIEndpoints.mobilePaperSummary,
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
                try? await Task.sleep(for: .seconds(12))
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
