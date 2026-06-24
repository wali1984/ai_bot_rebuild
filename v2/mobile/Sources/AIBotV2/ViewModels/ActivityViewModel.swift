import Foundation
import Observation

@MainActor
@Observable
public final class ActivityViewModel {

    public private(set) var events: [PaperActivityEvent] = []
    public private(set) var closedTrades: [MobilePosition] = []
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var lastUpdated: String?
    public private(set) var streamLabel = "Connecting"

    private let stream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?

    public var totalRealizedPnL: Double {
        closedTrades.reduce(0) { $0 + $1.realized_pnl }
    }

    public var winRate: Double {
        let winners = closedTrades.filter { $0.realized_pnl > 0 }.count
        guard !closedTrades.isEmpty else { return 0 }
        return Double(winners) / Double(closedTrades.count) * 100
    }

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            let response: MobilePositionsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobilePositions,
                token: token,
                baseURL: baseURL
            )
            closedTrades = response.closed_positions ?? []
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } catch {
            if closedTrades.isEmpty {
                self.error = error.localizedDescription
            }
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connectStream(token: token, baseURL: baseURL)
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                if !Task.isCancelled {
                    if case .connected = stream.state {} else {
                        connectStream(token: token, baseURL: baseURL)
                    }
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
    }

    private func connectStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobilePositions,
            intervalMs: 8_000
        ) else { return }
        streamLabel = "Connecting"
        stream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStream(message)
        }
    }

    private func applyStream(_ message: String) {
        do {
            let response = try decodeMobileResourceMessage(MobilePositionsResponse.self, from: message)
            closedTrades = response.closed_positions ?? []
            streamLabel = "Realtime"
            isLoading = false
            error = nil
            lastUpdated = ISO8601DateFormatter().string(from: Date())
        } catch {
            streamLabel = "Invalid"
        }
    }
}
