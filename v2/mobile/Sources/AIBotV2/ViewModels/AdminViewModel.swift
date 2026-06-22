import Foundation
import Observation

@MainActor
@Observable
public final class AdminViewModel {

    public private(set) var summary: MobileAdminSummary?
    public private(set) var riskStatus: MobileRiskStatus?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var summaryStreamLabel = "Connecting"
    public private(set) var riskStreamLabel = "Connecting"

    private let summaryStream = WebSocketClient()
    private let riskStream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let summaryStreamIntervalMs = 5_000
    private let riskStreamIntervalMs = 2_000

    public func load(token: String?, baseURL: String) async {
        connectSummaryStream(token: token, baseURL: baseURL)
        connectRiskStream(token: token, baseURL: baseURL)
        await loadFallback(token: token, baseURL: baseURL)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connectSummaryStream(token: token, baseURL: baseURL)
        connectRiskStream(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadFallback(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !summaryStreamIsConnected || !riskStreamIsConnected {
                    connectSummaryStream(token: token, baseURL: baseURL)
                    connectRiskStream(token: token, baseURL: baseURL)
                    await loadFallback(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        summaryStream.disconnect()
        riskStream.disconnect()
        summaryStreamLabel = "Disconnected"
        riskStreamLabel = "Disconnected"
    }

    private var summaryStreamIsConnected: Bool {
        if case .connected = summaryStream.state { return true }
        return false
    }

    private var riskStreamIsConnected: Bool {
        if case .connected = riskStream.state { return true }
        return false
    }

    private func connectSummaryStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileAdminSummary,
            intervalMs: summaryStreamIntervalMs
        ) else {
            summaryStreamLabel = "Offline"
            return
        }
        summaryStreamLabel = "Connecting"
        summaryStream.connect(urlString: url, token: token) { [weak self] message in
            self?.applySummaryStream(message)
        }
    }

    private func connectRiskStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileRiskStatus,
            intervalMs: riskStreamIntervalMs
        ) else {
            riskStreamLabel = "Offline"
            return
        }
        riskStreamLabel = "Connecting"
        riskStream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyRiskStream(message)
        }
    }

    private func loadFallback(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        do {
            riskStatus = try await APIClient.shared.get(
                path: APIEndpoints.mobileRiskStatus,
                token: token,
                baseURL: baseURL
            )
        } catch {
            if riskStatus == nil {
                self.error = error.localizedDescription
            }
        }
        do {
            summary = try await APIClient.shared.get(
                path: APIEndpoints.mobileAdminSummary,
                token: token,
                baseURL: baseURL
            )
        } catch let err as APIError where err.isUnauthorized {
            if summary == nil {
                self.error = "Admin access required"
            }
        } catch {
            if summary == nil {
                self.error = error.localizedDescription
            }
        }
        isLoading = false
    }

    private func applySummaryStream(_ message: String) {
        do {
            summary = try decodeMobileResourceMessage(MobileAdminSummary.self, from: message)
            summaryStreamLabel = "Live"
            isLoading = false
            error = nil
        } catch let err as APIError where err.isUnauthorized {
            summaryStreamLabel = "Access required"
            if summary == nil {
                self.error = "Admin access required"
            }
            isLoading = false
        } catch {
            summaryStreamLabel = "Invalid"
            if summary == nil {
                self.error = error.localizedDescription
            }
            isLoading = false
        }
    }

    private func applyRiskStream(_ message: String) {
        do {
            riskStatus = try decodeMobileResourceMessage(MobileRiskStatus.self, from: message)
            riskStreamLabel = "Live"
            isLoading = false
            if summary != nil {
                error = nil
            }
        } catch {
            riskStreamLabel = "Invalid"
            if riskStatus == nil {
                self.error = error.localizedDescription
            }
            isLoading = false
        }
    }
}
