import Foundation
import Observation

/// Runtime data-truth screen data source.
///
/// Fetches the two operator-runtime truth files that were previously declared
/// but unwired on iOS:
///   • APIEndpoints.orderbookRuntimeTruth  -> OrderbookRuntimeTruth
///   • APIEndpoints.microstructureTruth    -> MicrostructureTruth
///
/// Each side loads independently so one missing file never blanks the other.
/// Ages are computed from the payloads' own generated_at stamps — a truth
/// file that has not regenerated recently must read STALE, never fresh.
@MainActor
@Observable
public final class DataTruthViewModel {

    public private(set) var orderbook: OrderbookRuntimeTruth?
    public private(set) var microstructure: MicrostructureTruth?
    public private(set) var orderbookError: String?
    public private(set) var microstructureError: String?
    public private(set) var isLoading = false

    private var refreshTask: Task<Void, Never>?

    /// Truth files regenerate on service cycles; older than this is stale.
    public static let staleThresholdSeconds: Double = 3600

    // MARK: - Loading

    public func load(token: String?, baseURL: String) async {
        isLoading = orderbook == nil && microstructure == nil
        if let ob = await fetchOrderbook(token: token, baseURL: baseURL) { orderbook = ob }
        if let micro = await fetchMicrostructure(token: token, baseURL: baseURL) { microstructure = micro }
        isLoading = false
    }

    private func fetchOrderbook(token: String?, baseURL: String) async -> OrderbookRuntimeTruth? {
        do {
            let payload: OrderbookRuntimeTruth = try await APIClient.shared.get(
                path: APIEndpoints.orderbookRuntimeTruth,
                token: token,
                baseURL: baseURL
            )
            orderbookError = nil
            return payload
        } catch {
            if orderbook == nil { orderbookError = error.localizedDescription }
            return nil
        }
    }

    private func fetchMicrostructure(token: String?, baseURL: String) async -> MicrostructureTruth? {
        do {
            let payload: MicrostructureTruth = try await APIClient.shared.get(
                path: APIEndpoints.microstructureTruth,
                token: token,
                baseURL: baseURL
            )
            microstructureError = nil
            return payload
        } catch {
            if microstructure == nil { microstructureError = error.localizedDescription }
            return nil
        }
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        refreshTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                if Task.isCancelled { break }
                await load(token: token, baseURL: baseURL)
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    // MARK: - Freshness truth (derived from the payloads' generated_at)

    public var orderbookAgeSeconds: Double? {
        Self.ageSeconds(of: orderbook?.generated_at)
    }

    public var microstructureAgeSeconds: Double? {
        Self.ageSeconds(of: microstructure?.generated_at)
    }

    /// Stale when the stamp is missing/unparseable or older than the threshold.
    public var orderbookIsStale: Bool {
        guard let age = orderbookAgeSeconds else { return true }
        return age > Self.staleThresholdSeconds
    }

    public var microstructureIsStale: Bool {
        guard let age = microstructureAgeSeconds else { return true }
        return age > Self.staleThresholdSeconds
    }

    static func ageSeconds(of stamp: String?) -> Double? {
        guard let stamp, let date = parseISO8601(stamp) else { return nil }
        let age = Date().timeIntervalSince(date)
        return age >= 0 ? age : 0
    }

    static func parseISO8601(_ value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) { return date }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        return plain.date(from: value)
    }
}
