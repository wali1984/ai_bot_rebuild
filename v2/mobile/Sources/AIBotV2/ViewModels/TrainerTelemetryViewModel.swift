import Foundation
import Observation

/// Trainer Telemetry screen data source.
///
/// Polls GET /api/v2/trainer/status (TrainerDeepStatus). The trainer lane can
/// be deliberately held — freshness truth (freshness_status/staleness_seconds)
/// must be surfaced honestly, and null extended blocks (gpu_runtime,
/// model_edge_backtest, learning_metrics_extra) render as honest-empty, never
/// as invented numbers.
@MainActor
@Observable
public final class TrainerTelemetryViewModel {

    public private(set) var status: TrainerDeepStatus?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastFetchedAt: Date?

    private var refreshTask: Task<Void, Never>?
    private let refreshSeconds: Double = 30

    // MARK: - Loading

    public func load(token: String?, baseURL: String) async {
        isLoading = status == nil
        do {
            let payload: TrainerDeepStatus = try await APIClient.shared.get(
                path: APIEndpoints.trainerStatus,
                token: token,
                baseURL: baseURL
            )
            status = payload
            lastFetchedAt = Date()
            error = nil
        } catch {
            // Keep last good payload on transient failures; only surface a
            // blocking error when we have nothing at all to show.
            if status == nil {
                self.error = error.localizedDescription
            }
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        refreshTask = Task { [refreshSeconds] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(refreshSeconds))
                if Task.isCancelled { break }
                await load(token: token, baseURL: baseURL)
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    // MARK: - Freshness truth (backend fields only — no client fabrication)

    /// Stale unless the backend explicitly says fresh.
    public var isStale: Bool {
        guard let f = status?.freshness_status, !f.isEmpty else { return true }
        return f.lowercased() != "fresh"
    }

    public var stalenessSeconds: Double? { status?.staleness_seconds }

    /// Combined blocker chain: trainer readiness blockers first, then the
    /// champion/challenger evaluation blockers (deduplicated, order-stable).
    public var blockerChain: [String] {
        var seen = Set<String>()
        var chain: [String] = []
        for blocker in (status?.readiness_blockers ?? []) + (status?.champion_challenger_status?.blocker_reasons ?? []) {
            if seen.insert(blocker).inserted { chain.append(blocker) }
        }
        return chain
    }
}
