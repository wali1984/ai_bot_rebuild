import Foundation
import Observation

// MARK: - Supplemental typed decode of /api/v2/mobile/risk-status
//
// The shared MobileRiskStatus model does not yet expose every field the
// backend emits inside adaptive_hedge_cross_margin (maintenance margin,
// stress-used, available buffer, long/short exposure) nor the payload-level
// freshness fields. These structs decode the SAME payload/stream message —
// nothing here is computed or invented client-side. If the backend does not
// emit a field it stays nil and the view renders an honest em-dash.

public struct RiskCrossMarginStressDetail: Decodable, Equatable {
    public let maintenance_margin_estimate_usd: Double?
    public let cross_margin_stress_used_usd: Double?
    public let cross_margin_available_buffer_usd: Double?
    public let isolated_margin_required_usd: Double?
    public let long_exposure_usd: Double?
    public let short_exposure_usd: Double?
    public let recommended_margin_mode: String?
    public let why_cross_margin_or_isolated: String?
    public let exchange_margin_mode_mutation_allowed: Bool?
    public let paper_only: Bool?
}

public struct RiskStatusExtras: Decodable, Equatable {
    public let freshness_status: String?
    public let staleness_seconds: Double?
    public let adaptive_hedge_cross_margin: RiskCrossMarginStressDetail?
}

// MARK: - RiskViewModel
//
// Dedicated view model for the Risk Control screen. Streams
// /api/v2/mobile/risk-status over the shared WS resource socket with a 30s
// HTTP fallback/reconnect loop (same lifecycle contract as
// DashboardViewModel/AdminViewModel: startAutoRefresh in onAppear,
// stopAutoRefresh in onDisappear). This frees AdminViewModel back to the
// Admin screen — Risk no longer borrows it.

@MainActor
@Observable
public final class RiskViewModel {

    public private(set) var riskStatus: MobileRiskStatus?
    public private(set) var extras: RiskStatusExtras?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdatedAt: Date?

    /// Envelope truth from the last stream snapshot (drives StalenessChip).
    public private(set) var lastSnapshotStale = false
    public private(set) var lastSnapshotLagMs: Double?
    public private(set) var lastSnapshotTransport: String?

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000

    public init() {}

    public var isStreamLive: Bool {
        guard case .connected = stream.state else { return false }
        return streamLabel == "Realtime"
    }

    /// Payload-level freshness truth ("unavailable" when Redis was down).
    public var payloadUnavailable: Bool {
        extras?.freshness_status == "unavailable"
    }

    // MARK: Lifecycle

    public func load(token: String?, baseURL: String) async {
        connectStream(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connectStream(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !streamIsConnected {
                    connectStream(token: token, baseURL: baseURL)
                    await loadFallback(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        stream.disconnect()
        streamLabel = "Disconnected"
    }

    // MARK: Stream

    private var streamIsConnected: Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connectStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileRiskStatus,
            intervalMs: streamIntervalMs
        ) else {
            streamLabel = "Offline"
            return
        }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStream(message)
        }
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobileRiskStatus.self, from: message)
            riskStatus = snapshot.payload
            extras = try? decodeMobileResourceMessage(RiskStatusExtras.self, from: message)
            lastSnapshotStale = snapshot.stale
            lastSnapshotLagMs = snapshot.lagMs
            lastSnapshotTransport = snapshot.transport ?? "websocket"
            lastUpdatedAt = Date()
            streamLabel = "Realtime"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if riskStatus == nil {
                self.error = error.localizedDescription
            }
            isLoading = false
        }
    }

    // MARK: HTTP fallback

    private func loadFallback(token: String?, baseURL: String) async {
        isLoading = riskStatus == nil
        do {
            let status: MobileRiskStatus = try await APIClient.shared.get(
                path: APIEndpoints.mobileRiskStatus,
                token: token,
                baseURL: baseURL
            )
            riskStatus = status
            lastSnapshotStale = false
            lastSnapshotLagMs = nil
            lastSnapshotTransport = "http"
            lastUpdatedAt = Date()
            error = nil
        } catch {
            if riskStatus == nil {
                self.error = error.localizedDescription
            }
        }
        do {
            let detail: RiskStatusExtras = try await APIClient.shared.get(
                path: APIEndpoints.mobileRiskStatus,
                token: token,
                baseURL: baseURL
            )
            extras = detail
        } catch {
            // Extras are additive truth — absence renders honest em-dashes.
        }
        isLoading = false
    }
}
