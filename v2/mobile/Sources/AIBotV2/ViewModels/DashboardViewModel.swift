import Foundation
import Observation

// MARK: - Supplemental dashboard payload models (owned by the Dashboard screen)
//
// The shared `MobileDashboard` model does not yet decode the account KPI
// fields (`available_balance_usd`, `used_balance`) or the additive
// `signal_prediction_accuracy` parity block that /api/v2/mobile/dashboard
// already emits. Decode them here from the same payload in the same pass —
// one HTTP request / one WS message, no duplicate fetch.

public struct DashboardPredictionAccuracy: Decodable, Equatable {
    public let accuracy_definition: String?
    public let overall_accuracy: Double?
    public let evaluated_row_count: Int?
    public let correct_count: Int?
    public let incorrect_count: Int?
}

public struct DashboardPaperExtras: Decodable, Equatable {
    public let available_balance_usd: Double?
    public let used_balance: Double?
    public let signal_prediction_accuracy: DashboardPredictionAccuracy?
}

struct DashboardExtrasEnvelope: Decodable, Equatable {
    let paper: DashboardPaperExtras?
}

/// Single-pass combined decode: the shared typed model plus the supplemental
/// extras, both read from the same top-level JSON object.
struct DashboardPayload: Decodable {
    let core: MobileDashboard
    let extras: DashboardExtrasEnvelope

    init(from decoder: Decoder) throws {
        core = try MobileDashboard(from: decoder)
        extras = try DashboardExtrasEnvelope(from: decoder)
    }
}

@MainActor
@Observable
public final class DashboardViewModel {

    public private(set) var dashboard: MobileDashboard?
    public private(set) var paperExtras: DashboardPaperExtras?
    public private(set) var health: MobileHealth?
    public private(set) var goal: GoalTrajectoryData?
    public private(set) var goalStale = false
    public private(set) var goalError: String?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var dashboardStreamLabel = "Connecting"
    public private(set) var healthStreamLabel = "Connecting"
    public private(set) var lastStreamMessageAt: Date?

    // Envelope truth (stale / lag / transport) surfaced to the StalenessChip.
    // Hardcoded "LIVE" labels are forbidden — the view derives freshness from
    // these fields only.
    public private(set) var dashboardStale = false
    public private(set) var dashboardLagMs: Double?
    public private(set) var dashboardTransport: String?
    public private(set) var lastUpdatedAt: Date?

    private let dashboardSocket = WebSocketClient()
    private let healthSocket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 1_000
    private let staleAfterSeconds: Double = 90

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        async let dashboardLoad: Void = loadFallback(token: token, baseURL: baseURL)
        async let goalLoad: Void = loadGoal(token: token, baseURL: baseURL)
        _ = await (dashboardLoad, goalLoad)
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
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            await loadGoal(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !dashboardStreamIsConnected || !healthStreamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    await loadFallback(token: token, baseURL: baseURL)
                }
                await loadGoal(token: token, baseURL: baseURL)
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
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

    /// Seconds since the last successful payload from any transport.
    public var dataAgeSeconds: Double? {
        lastUpdatedAt.map { Date().timeIntervalSince($0) }
    }

    /// Honest staleness: envelope stale flag, payload freshness_status, or a
    /// payload older than `staleAfterSeconds` all count as stale.
    public var isEffectivelyStale: Bool {
        if dashboardStale { return true }
        if let age = dataAgeSeconds, age > staleAfterSeconds { return true }
        if let status = dashboard?.paper.freshness_status?.lowercased(),
           status == "stale" || status == "unavailable" {
            return true
        }
        return false
    }

    private var dashboardStreamIsConnected: Bool {
        if case .connected = dashboardSocket.state { return true }
        return false
    }

    private var healthStreamIsConnected: Bool {
        if case .connected = healthSocket.state { return true }
        return false
    }

    private func loadFallback(token: String?, baseURL: String) async {
        do {
            async let dashboardFallback: DashboardPayload = APIClient.shared.get(
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
            dashboard = d.core
            paperExtras = d.extras.paper
            health = h
            dashboardStale = false
            dashboardLagMs = nil
            dashboardTransport = "http"
            lastUpdatedAt = Date()
            WatchSyncCenter.shared.updateDashboard(dashboard, health: health)
            isLoading = false
            error = nil
        } catch {
            if dashboard == nil && health == nil {
                self.error = error.localizedDescription
                isLoading = false
            }
        }
    }

    public func loadGoal(token: String?, baseURL: String) async {
        do {
            let response: GoalTrajectoryResponse = try await APIClient.shared.get(
                path: APIEndpoints.goalTrajectory1000x,
                token: token,
                baseURL: baseURL
            )
            goal = response.data
            let responseStale = (response.freshness_status ?? "").lowercased() == "stale"
            goalStale = (response.data.is_stale == true) || responseStale
            goalError = nil
        } catch {
            // Goal card renders an honest absent state; a goal fetch failure
            // must not clobber the core dashboard error surface.
            if goal == nil { goalError = error.localizedDescription }
        }
    }

    private func applyDashboardMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(DashboardPayload.self, from: message)
            dashboard = snapshot.payload.core
            paperExtras = snapshot.payload.extras.paper
            dashboardStale = snapshot.stale
            dashboardLagMs = snapshot.lagMs
            dashboardTransport = snapshot.transport ?? "websocket"
            dashboardStreamLabel = "Realtime"
            lastStreamMessageAt = Date()
            lastUpdatedAt = Date()
            WatchSyncCenter.shared.updateDashboard(dashboard, health: health)
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
            healthStreamLabel = "Realtime"
            lastStreamMessageAt = Date()
            WatchSyncCenter.shared.updateDashboard(dashboard, health: health)
            isLoading = false
            error = nil
        } catch {
            healthStreamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }

}
