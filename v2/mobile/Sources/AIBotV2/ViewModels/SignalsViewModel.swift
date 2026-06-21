import Foundation
import Observation

@Observable
public final class SignalsViewModel {

    public private(set) var response: MobileSignalsResponse?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public var actionableOnly: Bool = false {
        didSet { lastToken.map { startAutoRefresh(token: $0, baseURL: lastBaseURL) } }
    }

    private var refreshTask: Task<Void, Never>?
    private var lastToken: String?
    private var lastBaseURL: String = ""

    public var signals: [MobileSignal] { response?.signals ?? [] }

    public func load(token: String?, baseURL: String, limit: Int = 30) async {
        lastToken = token
        lastBaseURL = baseURL
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

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        lastToken = token
        lastBaseURL = baseURL
        refreshTask = Task {
            while !Task.isCancelled {
                await load(token: token, baseURL: baseURL)
                try? await Task.sleep(for: .seconds(15))
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
