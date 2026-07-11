import Foundation
import Observation

/// Realtime backtest + replay-feedback + missing-feature-alert for the AI pages.
/// Streams over the read-only WebSocket resource proxy (last-good retained, so there
/// is no refresh or loading gap after first paint) with a REST fallback. Read-only.
/// Backtest is explicitly NOT A+/live evidence.
@MainActor
@Observable
public final class BacktestReplayViewModel {

    public private(set) var backtest: BacktestResults?
    public private(set) var featureAlert: AIPredictionMissingFeatureAlert?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastUpdatedAt: String?
    public private(set) var streamLabel = "Connecting"

    // Symbol/timeframe the summary alert is sampled from (a liquid major).
    public var alertSymbol = "BTCUSDT"
    public var alertTimeframe = "1h"

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
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
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(15))
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
                }
                // The alert endpoint is per-symbol and not on the stream; refresh
                // it on a slow cadence. Backtest itself arrives over the socket.
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

    private func applyMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(BacktestResults.self, from: message)
            backtest = snapshot.payload
            lastUpdatedAt = snapshot.timestamp ?? snapshot.payload.generated_utc
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if backtest == nil { self.error = error.localizedDescription }
        }
    }

    private func loadFallback(token: String?, baseURL: String) async {
        do {
            let results: BacktestResults = try await APIClient.shared.get(
                path: APIEndpoints.replayBacktest,
                token: token,
                baseURL: baseURL
            )
            backtest = results
            lastUpdatedAt = results.generated_utc
            isLoading = false
            error = nil
        } catch {
            if backtest == nil { self.error = error.localizedDescription; isLoading = false }
        }
        await loadAlert(token: token, baseURL: baseURL)
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
