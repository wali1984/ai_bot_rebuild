import Foundation
import Observation

/// Fetches `/api/v2/self-healing/status` (per-service auto-heal status + banner)
/// over HTTP with a lightweight refresh loop. Read-only.
@MainActor
@Observable
public final class SelfHealingViewModel {

    public private(set) var status: SelfHealingStatus?
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?
    private let refreshIntervalNs: UInt64 = 20_000_000_000  // 20s

    public init() {}

    public var services: [SelfHealingService] {
        (status?.decisions ?? []).sorted { a, b in
            let rank = ["error": 0, "warn": 1, "ok": 2]
            let ra = rank[a.tone] ?? 2
            let rb = rank[b.tone] ?? 2
            if ra != rb { return ra < rb }
            return (a.name ?? "") < (b.name ?? "")
        }
    }

    /// The red banner: services still down after auto-heal (or supervisor stale).
    public var banner: SelfHealingBanner? {
        guard let b = status?.banner, b.show, b.severity != "ok" else { return nil }
        return b
    }

    public var healthyCount: Int { status?.healthy_count ?? services.filter { $0.tone == "ok" }.count }
    public var totalCount: Int { status?.component_count ?? services.count }
    public var downCount: Int { status?.unhealthy_count ?? services.filter { $0.tone == "error" }.count }

    public func load(token: String?, baseURL: String) async {
        await fetch(token: token, baseURL: baseURL)
    }

    /// Fetch once, then keep refreshing until the view goes away.
    public func startAutoRefresh(token: String?, baseURL: String) {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.fetch(token: token, baseURL: baseURL)
                try? await Task.sleep(nanoseconds: self?.refreshIntervalNs ?? 20_000_000_000)
            }
        }
    }

    public func stop() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    private func fetch(token: String?, baseURL: String) async {
        if status == nil { isLoading = true }
        do {
            let result: SelfHealingStatus = try await APIClient.shared.get(
                path: APIEndpoints.selfHealingStatus,
                token: token,
                baseURL: baseURL
            )
            status = result
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }
}
