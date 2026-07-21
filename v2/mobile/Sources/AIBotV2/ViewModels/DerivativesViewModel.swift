import Foundation
import Observation

/// Derivatives screen view model.
///
/// Owns the compact derivatives rollup end-to-end (read-only telemetry):
///   GET /api/v2/mobile/derivatives-summary  (WS stream @10s + HTTP fallback)
///   -> MobileDerivativesSummary (aggregate, global_regime, top symbols by OI)
///
/// The full /api/v2/derivatives payload (~102KB) is intentionally not fetched
/// on mobile — the backend rollup carries the aggregate truth.
///
/// Live trading stays operator-gated (live_gate=blocked_human_only).
@MainActor
@Observable
public final class DerivativesViewModel {

    // MARK: - Published state

    public private(set) var response: MobileDerivativesSummary?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdated: String?

    // Envelope / payload freshness truth (feeds the StalenessChip).
    public private(set) var envelopeStale = false
    public private(set) var envelopeLagMs: Double?
    public private(set) var envelopeTransport: String?

    // MARK: - Private

    private let stream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?
    private var lastToken: String?
    private var lastBaseURL: String = ""

    // MARK: - Derived

    public var hasAnyData: Bool { response != nil }

    public var aggregate: DerivativesAggregate? { response?.aggregate }

    public var regime: DerivativesGlobalRegime? { response?.global_regime }

    /// Top symbols by OI (backend pre-ranks; re-sort defensively, nil OI sinks).
    public var topSymbols: [DerivativesSymbolRow] {
        (response?.top_symbols ?? []).sorted {
            ($0.oi_usd ?? -1) > ($1.oi_usd ?? -1)
        }
    }

    /// Scale denominator for the per-symbol funding bars.
    public var maxAbsFunding: Double {
        topSymbols.compactMap { $0.funding_rate.map { abs($0) } }.max() ?? 0.0001
    }

    public var liveGateLabel: String {
        nervyxPublicRuntimeText(response?.live_gate ?? "blocked_human_only")
    }

    /// Combined envelope + payload freshness truth. The rollup regenerates
    /// roughly once a minute, so only flag stale beyond a 5-minute age.
    public var isStale: Bool {
        if envelopeStale { return true }
        let status = (response?.freshness_status ?? "").lowercased()
        if status == "stale" || status == "unavailable" { return true }
        if let age = response?.staleness_seconds, age > 300 { return true }
        return false
    }

    public var stalenessAgeSeconds: Double? {
        response?.staleness_seconds ?? envelopeLagMs.map { $0 / 1000 }
    }

    // MARK: - Loading

    public func load(token: String?, baseURL: String) async {
        lastToken = token
        lastBaseURL = baseURL
        isLoading = !hasAnyData
        do {
            let resp: MobileDerivativesSummary = try await APIClient.shared.get(
                path: APIEndpoints.mobileDerivativesSummary,
                token: token,
                baseURL: baseURL
            )
            apply(resp, transport: envelopeTransport ?? "http", stale: nil, lagMs: nil)
            error = nil
        } catch {
            if !hasAnyData { self.error = error.localizedDescription }
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        lastToken = token
        lastBaseURL = baseURL
        connectStream(token: token, baseURL: baseURL)
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                guard !Task.isCancelled else { break }
                if !isConnected {
                    connectStream(token: token, baseURL: baseURL)
                    await load(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
        stream.disconnect()
        streamLabel = "Disconnected"
        envelopeTransport = nil
    }

    public func refresh() async {
        await load(token: lastToken, baseURL: lastBaseURL)
    }

    // MARK: - WebSocket stream

    private var isConnected: Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connectStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileDerivativesSummary,
            intervalMs: 10_000
        ) else {
            streamLabel = "Offline"
            return
        }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStreamMessage(message)
        }
    }

    private func applyStreamMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobileDerivativesSummary.self, from: message)
            apply(
                snapshot.payload,
                transport: snapshot.transport ?? "websocket",
                stale: snapshot.stale,
                lagMs: snapshot.lagMs
            )
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
        }
    }

    private func apply(_ payload: MobileDerivativesSummary, transport: String, stale: Bool?, lagMs: Double?) {
        response = payload
        envelopeStale = stale ?? false
        envelopeLagMs = lagMs
        envelopeTransport = transport
        streamLabel = isStale ? "Stale" : (transport.lowercased().contains("ws") ? "Realtime" : "Poll")
        lastUpdated = payload.payload_generated_utc ?? payload.generated_utc
    }
}
