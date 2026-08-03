import Foundation
import Observation

/// Realtime backtest + replay-feedback + missing-feature-alert for the AI pages.
/// Streams over the read-only WebSocket resource proxy (last-good retained, so there
/// is no refresh or loading gap after first paint) with a 15s REST poll fallback.
/// Read-only. Backtest is explicitly NOT A+/live evidence.
///
/// NOTE: TrainerPredictionView also instantiates this view model — the existing
/// public surface (`backtest`, `featureAlert`, `load`, `startAutoRefresh`,
/// `stopAutoRefresh`, `streamLabel`, …) must stay stable until that screen
/// drops the dependency. New members below are strictly additive.
@MainActor
@Observable
public final class BacktestReplayViewModel {

    public private(set) var backtest: BacktestResults?
    public private(set) var featureAlert: AIPredictionMissingFeatureAlert?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastUpdatedAt: String?
    public private(set) var streamLabel = "Connecting"

    // Envelope truth (additive): drives the shared StalenessChip honestly.
    public private(set) var envelopeStale = false
    public private(set) var lagMs: Double?
    public private(set) var lastTransport: String?
    public private(set) var lastReceivedAt: Date?

    // Client-side trend of the headline backtest win-rate across cycles.
    // RollingSeries dedupes unchanged values, so each point is a genuinely new
    // backtest number (not a stream re-tick). Strictly additive — does not
    // change the existing public surface; drives the win-rate trend sparkline.
    public private(set) var winRateTrend: [Double] = []
    private var winRateSeries = RollingSeries(capacity: 48)

    // Symbol/timeframe the summary alert is sampled from (a liquid major).
    public var alertSymbol = "BTCUSDT"
    public var alertTimeframe = "1h"

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000
    private let pollSeconds: Double = 15
    private let staleAfterSeconds: Double = 45

    /// Client-side age of the last accepted snapshot (either transport).
    var ageSeconds: Double? {
        lastReceivedAt.map { Date().timeIntervalSince($0) }
    }

    /// Freshness truth for the shared StalenessChip — derived from real
    /// snapshot metadata, never hardcoded (REALTIME only while the socket
    /// is actually connected and the envelope is fresh).
    var freshnessMode: FreshnessMode {
        guard backtest != nil else { return .offline }
        if envelopeStale { return .stale }
        if let age = ageSeconds, age > staleAfterSeconds { return .stale }
        let transport = (lastTransport ?? "").lowercased()
        if streamIsConnected, transport.contains("ws") || transport.contains("stream") {
            return .realtime
        }
        return .poll
    }

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadBacktestREST(token: token, baseURL: baseURL)
        await loadAlert(token: token, baseURL: baseURL)
    }

    public func connect(token: String?, baseURL: String) {
        isLoading = backtest == nil
        error = nil
        streamLabel = "Connecting"
        guard let streamURL = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.replayBacktest,
            intervalMs: streamIntervalMs
        ) else {
            streamLabel = "Offline"
            return
        }
        socket.connect(urlString: streamURL, token: token) { [weak self] message in
            self?.applyMessage(message)
        }
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadBacktestREST(token: token, baseURL: baseURL)
            await loadAlert(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(pollSeconds))
                if Task.isCancelled { break }
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    // Socket is down — keep the payload honest via the REST poll
                    // so the chip truthfully reads POLL instead of a frozen card.
                    await loadBacktestREST(token: token, baseURL: baseURL)
                }
                // The alert endpoint is per-symbol and not on the stream; refresh
                // it on the slow cadence. Backtest itself arrives over the socket.
                await loadAlert(token: token, baseURL: baseURL)
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        socket.disconnect()
        streamLabel = "Disconnected"
    }

    private var streamIsConnected: Bool {
        if case .connected = socket.state { return true }
        return false
    }

    /// Record the headline win-rate into the rolling trend series. RollingSeries
    /// dedupe means only genuinely new backtest cycles add a point (stream
    /// re-ticks of the same number are ignored).
    private func recordTrend(_ results: BacktestResults) {
        guard let winRate = results.policy_backtest?.win_rate, winRate.isFinite else { return }
        winRateSeries.append(winRate)
        winRateTrend = winRateSeries.values
    }

    private func applyMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(BacktestResults.self, from: message)
            backtest = snapshot.payload
            recordTrend(snapshot.payload)
            lastUpdatedAt = snapshot.timestamp ?? snapshot.payload.generated_utc
            envelopeStale = snapshot.stale
            lagMs = snapshot.lagMs
            lastTransport = snapshot.transport ?? "websocket"
            lastReceivedAt = Date()
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if backtest == nil { self.error = error.localizedDescription }
        }
    }

    private func loadBacktestREST(token: String?, baseURL: String) async {
        do {
            let results: BacktestResults = try await APIClient.shared.get(
                path: APIEndpoints.replayBacktest,
                token: token,
                baseURL: baseURL
            )
            backtest = results
            recordTrend(results)
            lastUpdatedAt = results.generated_utc
            envelopeStale = false
            lagMs = nil
            lastTransport = "http"
            lastReceivedAt = Date()
            isLoading = false
            error = nil
        } catch {
            if backtest == nil { self.error = error.localizedDescription; isLoading = false }
        }
    }

    private func loadAlert(token: String?, baseURL: String) async {
        do {
            let explain: AIPredictionExplainResponse = try await APIClient.shared.get(
                path: APIEndpoints.predictionsExplain,
                queryItems: [
                    URLQueryItem(name: "symbol", value: alertSymbol),
                    URLQueryItem(name: "timeframe", value: alertTimeframe),
                ],
                token: token,
                baseURL: baseURL
            )
            featureAlert = explain.data?.missing_feature_alert
        } catch {
            // best-effort; leave prior alert in place
        }
    }
}
