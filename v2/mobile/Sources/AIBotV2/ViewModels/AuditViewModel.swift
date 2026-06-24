import Foundation
import Observation

@MainActor
@Observable
public final class AuditViewModel {

    public private(set) var summary: AuditLedgerSummary?
    public private(set) var entries: [AuditLedgerEntry] = []
    public private(set) var isLoading = false
    public private(set) var error: String?

    private var refreshTask: Task<Void, Never>?

    public func load(token: String?, baseURL: String) async {
        isLoading = true
        error = nil
        async let summaryResult: AuditLedgerSummary = APIClient.shared.get(
            path: APIEndpoints.auditLedgerSummary,
            token: token,
            baseURL: baseURL
        )
        async let entriesResult: [AuditLedgerEntry] = APIClient.shared.get(
            path: APIEndpoints.auditLedgerTail,
            queryItems: [URLQueryItem(name: "limit", value: "50")],
            token: token,
            baseURL: baseURL
        )
        do {
            summary = try await summaryResult
        } catch {
            if summary == nil { self.error = error.localizedDescription }
        }
        do {
            entries = try await entriesResult
        } catch {
            if entries.isEmpty && self.error == nil {
                self.error = error.localizedDescription
            }
        }
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !Task.isCancelled {
                    await load(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }
}
