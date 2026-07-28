import Foundation
import Observation

/// Adaptive System screen data source.
///
/// Polls GET /api/v2/adaptive/status (read-only). Surfaces the paper/shadow
/// adaptive runtime — policy-shadow evaluator, candidate-outcome maturation,
/// candidate calibration, paper-policy authority, escalation supervisor, and
/// the data-utilization funnel. Freshness/availability are reported per section
/// exactly as the backend states them; nothing is fabricated. Live gate stays
/// blocked (paper-only).
@MainActor
@Observable
public final class AdaptiveStatusViewModel {

    public private(set) var status: AdaptiveStatusResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastFetchedAt: Date?

    private var refreshTask: Task<Void, Never>?
    private let refreshSeconds: Double = 30

    /// Stable display order matching the backend's section order; any unknown
    /// sections are appended so nothing is silently dropped.
    private let sectionOrder = [
        "policy_shadow_status",
        "policy_shadow_latest",
        "candidate_outcomes",
        "candidate_calibration",
        "paper_policy_authority",
        "escalation_supervisor",
        "data_utilization_funnel",
    ]

    public func load(token: String?, baseURL: String) async {
        isLoading = status == nil
        do {
            let payload: AdaptiveStatusResponse = try await APIClient.shared.get(
                path: "/api/v2/adaptive/status",
                token: token,
                baseURL: baseURL
            )
            status = payload
            lastFetchedAt = Date()
            error = nil
        } catch {
            // Keep the last good payload on transient failures; only surface a
            // blocking error when there is nothing at all to show.
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

    public var orderedSections: [(key: String, section: AdaptiveStatusSection)] {
        guard let secs = status?.sections else { return [] }
        var out: [(key: String, section: AdaptiveStatusSection)] = []
        for k in sectionOrder {
            if let s = secs[k] { out.append((key: k, section: s)) }
        }
        for (k, s) in secs where !sectionOrder.contains(k) {
            out.append((key: k, section: s))
        }
        return out
    }
}
