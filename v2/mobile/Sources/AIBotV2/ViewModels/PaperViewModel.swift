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

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 1_500

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

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(PaperSummaryPayload.self, from: message)
            summary = snapshot.payload.summary
            pnlWindows = snapshot.payload.pnlWindows
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
