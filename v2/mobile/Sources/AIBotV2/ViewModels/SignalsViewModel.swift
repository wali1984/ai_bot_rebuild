import Foundation
import Observation

@MainActor
@Observable
public final class SignalsViewModel {

    public private(set) var response: MobileSignalsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public var actionableOnly: Bool = false {
        didSet { startAutoRefresh(token: lastToken, baseURL: lastBaseURL) }
    }

    private let stream = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private var lastToken: String?
    private var lastBaseURL: String = ""
    private let streamIntervalMs = 2_000

    public var signals: [MobileSignal] { response?.signals ?? [] }

    public func load(token: String?, baseURL: String, limit: Int = 150) async {
        lastToken = token
        lastBaseURL = baseURL
        connect(token: token, baseURL: baseURL, limit: limit)
        await loadFallback(token: token, baseURL: baseURL, limit: limit)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        lastToken = token
        lastBaseURL = baseURL
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

    private func connect(token: String?, baseURL: String, limit: Int = 150) {
        var query: [URLQueryItem] = [URLQueryItem(name: "limit", value: "\(limit)")]
        if actionableOnly { query.append(URLQueryItem(name: "actionable_only", value: "true")) }
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileSignals,
            queryItems: query,
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

    private func loadFallback(token: String?, baseURL: String, limit: Int = 150) async {
        isLoading = true
        error = nil
        var query: [URLQueryItem] = [URLQueryItem(name: "limit", value: "\(limit)")]
        if actionableOnly { query.append(URLQueryItem(name: "actionable_only", value: "true")) }
        do {
            response = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignals,
                queryItems: query,
                token: token,
                baseURL: baseURL
            )
        } catch {
            self.error = error.localizedDescription
        }
        isLoading = false
    }

    private func applyStream(_ message: String) {
        do {
            response = try decodeMobileResourceMessage(MobileSignalsResponse.self, from: message)
            streamLabel = "Live"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            self.error = error.localizedDescription
            isLoading = false
        }
    }
}
