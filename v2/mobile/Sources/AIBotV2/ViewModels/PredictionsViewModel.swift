import Foundation
import Observation

@MainActor
@Observable
public final class PredictionsViewModel {

    public private(set) var signals: [SignalMatrixRow] = []
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdated: String?
    public var actionableOnly = false

    private let stream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?

    public var displayed: [SignalMatrixRow] {
        actionableOnly ? signals.filter { $0.actionable == true } : signals
    }

    public var actionableCount: Int { signals.filter { $0.actionable == true }.count }
    public var avgConfidence: Double {
        let vals = signals.compactMap(\.confidence)
        guard !vals.isEmpty else { return 0 }
        return vals.reduce(0, +) / Double(vals.count)
    }

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            let response: MobileSignalsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignals,
                token: token,
                baseURL: baseURL
            )
            signals = response.signals.map { sig in
                SignalMatrixRow(
                    signal_id: sig.id,
                    symbol: sig.symbol,
                    timeframe: sig.timeframe,
                    action: sig.action,
                    confidence: sig.confidence,
                    actionable: sig.actionable,
                    live_gate: nil,
                    risk_state: sig.risk_state,
                    paper_fill_status: sig.paper_fill_status,
                    data_coverage_percent: sig.data_coverage,
                    market_state_integrity_score: nil,
                    generated_at: sig.published_at,
                    age_seconds: nil,
                    model_version: nil,
                    checkpoint_id: nil,
                    expected_move_bps: sig.expected_move_bps,
                    feature_coverage_pct: sig.data_coverage,
                    orchestrator_state: nil
                )
            }
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } catch {
            if signals.isEmpty { self.error = error.localizedDescription }
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connectStream(token: token, baseURL: baseURL)
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                if !Task.isCancelled {
                    if case .connected = stream.state {} else {
                        connectStream(token: token, baseURL: baseURL)
                    }
                }
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
        stream.disconnect()
        streamLabel = "Disconnected"
    }

    private func connectStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileSignals,
            intervalMs: 5_000
        ) else { return }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStream(message)
        }
    }

    private func applyStream(_ message: String) {
        do {
            let response = try decodeMobileResourceMessage(MobileSignalsResponse.self, from: message)
            signals = response.signals.map { sig in
                SignalMatrixRow(
                    signal_id: sig.id,
                    symbol: sig.symbol,
                    timeframe: sig.timeframe,
                    action: sig.action,
                    confidence: sig.confidence,
                    actionable: sig.actionable,
                    live_gate: nil,
                    risk_state: sig.risk_state,
                    paper_fill_status: sig.paper_fill_status,
                    data_coverage_percent: sig.data_coverage,
                    market_state_integrity_score: nil,
                    generated_at: sig.published_at,
                    age_seconds: nil,
                    model_version: nil,
                    checkpoint_id: nil,
                    expected_move_bps: sig.expected_move_bps,
                    feature_coverage_pct: sig.data_coverage,
                    orchestrator_state: nil
                )
            }
            streamLabel = "Realtime"
            isLoading = false
            error = nil
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } catch {
            streamLabel = "Invalid"
        }
    }
}
