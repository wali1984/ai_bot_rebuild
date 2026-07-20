import Foundation
import Observation

// MARK: - Additive payload decoding
//
// /api/v2/mobile/paper-summary carries an additive `pnl_windows` block
// (1d/7d/30d realized NET PnL) alongside the typed MobilePaperSummary
// fields. Both are decoded from the same JSON object in a single
// request / stream message — no second fetch.

private struct PaperSummaryExtras: Decodable {
    let pnl_windows: [PnLWindow]?
}

struct PaperSummaryPayload: Decodable {
    let summary: MobilePaperSummary
    let pnlWindows: [PnLWindow]

    init(from decoder: Decoder) throws {
        summary = try MobilePaperSummary(from: decoder)
        pnlWindows = ((try? PaperSummaryExtras(from: decoder))?.pnl_windows) ?? []
    }
}

@MainActor
@Observable
public final class PaperViewModel {

    public private(set) var summary: MobilePaperSummary?
    public private(set) var pnlWindows: [PnLWindow] = []
    /// Session-local observed path of total PnL, accumulated across stream /
    /// poll snapshots. The API carries no server-side PnL history, so this is
    /// the only honest trend the Execute screen can chart — it is always
    /// labelled "SESSION" in the UI and reset when the paper session rotates.
    public private(set) var pnlSeries: [Double] = []
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var sourceType: String?
    public private(set) var transport: String?
    public private(set) var lastUpdatedAt: String?
    public private(set) var lagMs: Double?
    public private(set) var isStale = false
    public private(set) var streamWarnings: [String] = []
    public private(set) var missingFields: [String] = []

    /// Canonical win-rate window for the RingGauge: the populated window with
    /// the most closed trades (matches the website's 7d/30d win-rate source).
    public var primaryWinRateWindow: PnLWindow? {
        pnlWindows
            .filter { ($0.closed_trade_count ?? 0) > 0 && ($0.win_rate ?? .nan).isFinite }
            .max { ($0.closed_trade_count ?? 0) < ($1.closed_trade_count ?? 0) }
    }

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 1_500
    private var pnlRolling = RollingSeries(capacity: 90)
    private var lastSessionId: String?

    public func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
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

    private var streamIsConnected: Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connect(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobilePaperSummary,
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

    private func loadFallback(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            let payload: PaperSummaryPayload = try await APIClient.shared.get(
                path: APIEndpoints.mobilePaperSummary,
                token: token,
                baseURL: baseURL
            )
            summary = payload.summary
            pnlWindows = payload.pnlWindows
            recordPnL(payload.summary)
            sourceType = "api"
            transport = "http"
            lastUpdatedAt = payload.summary.generated_utc
            lagMs = nil
            isStale = false
            streamWarnings = []
            missingFields = []
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    /// Append the observed total PnL to the session path, resetting when the
    /// paper session id rotates so two sessions never share one curve.
    private func recordPnL(_ summary: MobilePaperSummary) {
        if summary.paper_session_id != lastSessionId {
            pnlRolling = RollingSeries(capacity: 90)
            lastSessionId = summary.paper_session_id
        }
        pnlRolling.append(summary.pnl.total_usd)
        pnlSeries = pnlRolling.values
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(PaperSummaryPayload.self, from: message)
            summary = snapshot.payload.summary
            pnlWindows = snapshot.payload.pnlWindows
            recordPnL(snapshot.payload.summary)
            streamLabel = "Realtime"
            sourceType = snapshot.sourceType ?? snapshot.transport ?? "websocket"
            transport = snapshot.transport ?? "websocket"
            lastUpdatedAt = snapshot.timestamp ?? snapshot.receivedAt ?? snapshot.payload.summary.generated_utc
            lagMs = snapshot.lagMs
            isStale = snapshot.stale
            streamWarnings = snapshot.warnings
            missingFields = snapshot.missingFields
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }
}
