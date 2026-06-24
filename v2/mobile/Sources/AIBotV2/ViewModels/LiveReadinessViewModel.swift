import Foundation
import Observation

@MainActor
@Observable
public final class LiveReadinessViewModel {

    public private(set) var gates: [LiveReadinessGate] = []
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastUpdated: String?

    private var refreshTask: Task<Void, Never>?

    public var passedCount: Int { gates.filter(\.isPassed).count }
    public var blockedCount: Int { gates.filter(\.isBlocked).count }
    public var pendingCount: Int { gates.filter { $0.state == "pending" }.count }
    public var allPassed: Bool { !gates.isEmpty && gates.allSatisfy(\.isPassed) }

    public var overallStatus: String {
        if gates.isEmpty { return "Loading" }
        if blockedCount > 0 { return "BLOCKED" }
        if allPassed { return "READY" }
        return "PENDING"
    }

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            gates = try await APIClient.shared.get(
                path: APIEndpoints.liveReadinessGates,
                token: token,
                baseURL: baseURL
            )
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                if !Task.isCancelled {
                    await load(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
