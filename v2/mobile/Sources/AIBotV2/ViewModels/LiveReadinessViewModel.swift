import Foundation
import Observation

// MARK: - Live Readiness stream models
//
// `/api/v2/live-readiness/gates` returns a bare list where every gate row is
// merged with the shared blocker context (live_gate, exact_no_live_reason,
// readiness_blockers, a_grade_blocker_truth, ...). The route is allow-listed
// on the shared `/api/v2/ws/resource` WebSocket, so the same rows stream in
// an envelope with `data`/`stale`/`transport` truth fields.

public struct LiveReadinessGateRow: Decodable, Identifiable, Equatable {
    public let id: String
    public let name: String
    public let sub: String
    public let source_route_or_key: String
    public let state: String

    // Shared blocker context merged into every row by the backend route.
    public let live_gate: String?
    public let live_ready: Bool?
    public let live_submit_allowed: Bool?
    public let exact_no_live_reason: String?
    public let readiness_blockers: [String]?
    public let top_blockers: [String]?
    public let a_grade_blocker_truth: LiveReadinessBlockerTruth?
    public let routes_to_live: Bool?
    public let places_real_order: Bool?

    public var isPassed: Bool { state == "passed" }
    public var isBlocked: Bool { state == "blocked" }
    public var isLocked: Bool { state == "locked" }
    public var isPending: Bool { !isPassed && !isBlocked && !isLocked }
    public var displayState: String { state.uppercased() }
    public var stateEmoji: String {
        switch state {
        case "passed": return "✓"
        case "blocked": return "✗"
        case "locked": return "⊘"
        default: return "…"
        }
    }
}

public struct LiveReadinessBlockerTruth: Decodable, Equatable {
    public let status: String?
    public let primary_blocker: String?
    public let finding_ids: [String]?
    public let findings: [LiveReadinessBlockerFinding]?
    public let generated_utc: String?
    public let available: Bool?
}

public struct LiveReadinessBlockerFinding: Decodable, Identifiable, Equatable {
    public let id: String
    public let severity: String?
    public let code_defect: Bool?
}

// MARK: - ViewModel
//
// Streams the gate matrix over the shared resource WebSocket with an HTTP
// poll fallback (mirrors IngestorsViewModel), and polls the canonical
// live-canary + A+ inventory contracts over HTTP. Read-only; nothing here
// can flip any gate — live trading stays operator-gated.

@MainActor
@Observable
public final class LiveReadinessViewModel {

    public private(set) var gates: [LiveReadinessGateRow] = []
    public private(set) var liveCanaryStatus: ControlCenterLiveCanaryStatus?
    public private(set) var aPlusInventoryStatus: ControlCenterAPlusInventoryStatus?
    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var transport: String?
    public private(set) var isStale = false
    public private(set) var lagMs: Double?
    public private(set) var lastUpdatedAt: String?
    public private(set) var lastUpdatedDate: Date?

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private var lastToken: String?
    private var lastBaseURL = ""
    private let streamIntervalMs = 5_000

    // MARK: Derived counts / grouping

    public var passedCount: Int { gates.filter(\.isPassed).count }
    public var blockedCount: Int { gates.filter(\.isBlocked).count }
    public var lockedCount: Int { gates.filter(\.isLocked).count }
    public var pendingCount: Int { gates.filter(\.isPending).count }
    public var totalCount: Int { gates.count }
    public var allPassed: Bool { !gates.isEmpty && gates.allSatisfy(\.isPassed) }

    public var progressFraction: Double {
        guard totalCount > 0 else { return 0 }
        return Double(passedCount) / Double(totalCount)
    }

    public var overallStatus: String {
        if gates.isEmpty { return "Loading" }
        if blockedCount > 0 || lockedCount > 0 { return "BLOCKED" }
        if allPassed { return "READY" }
        return "PENDING"
    }

    public var blockedGates: [LiveReadinessGateRow] { gates.filter(\.isBlocked) }
    public var lockedGates: [LiveReadinessGateRow] { gates.filter(\.isLocked) }
    public var pendingGates: [LiveReadinessGateRow] { gates.filter(\.isPending) }
    public var passedGates: [LiveReadinessGateRow] { gates.filter(\.isPassed) }

    // MARK: Blocker context (identical on every merged row; first row wins)

    public var blockerContext: LiveReadinessGateRow? { gates.first }
    public var exactNoLiveReason: String? { blockerContext?.exact_no_live_reason }
    public var readinessBlockers: [String] {
        blockerContext?.readiness_blockers ?? blockerContext?.top_blockers ?? []
    }
    public var blockerTruth: LiveReadinessBlockerTruth? {
        blockerContext?.a_grade_blocker_truth
    }
    public var liveGateRaw: String? { blockerContext?.live_gate }

    public func severity(forBlocker blockerID: String) -> String? {
        blockerTruth?.findings?.first { $0.id == blockerID }?.severity
    }

    // MARK: Freshness truth

    public var ageSeconds: Double? {
        lastUpdatedDate.map { max(Date().timeIntervalSince($0), 0) }
    }

    public var isEffectivelyStale: Bool {
        isStale || (ageSeconds ?? 0) > 90
    }

    // MARK: Lifecycle

    public func load(token: String?, baseURL: String) async {
        lastToken = token
        lastBaseURL = baseURL
        connectIfNeeded(token: token, baseURL: baseURL)
        await loadGatesFallback(token: token, baseURL: baseURL)
        await loadSideStatus(token: token, baseURL: baseURL)
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        lastToken = token
        lastBaseURL = baseURL
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadGatesFallback(token: token, baseURL: baseURL)
            await loadSideStatus(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if Task.isCancelled { break }
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    await loadGatesFallback(token: token, baseURL: baseURL)
                }
                await loadSideStatus(token: token, baseURL: baseURL)
            }
        }
    }

    public func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        socket.disconnect()
        streamLabel = "Disconnected"
    }

    // MARK: Stream

    private var streamIsConnected: Bool {
        if case .connected = socket.state { return true }
        return false
    }

    private func connectIfNeeded(token: String?, baseURL: String) {
        guard !streamIsConnected else { return }
        connect(token: token, baseURL: baseURL)
    }

    private func connect(token: String?, baseURL: String) {
        isLoading = gates.isEmpty
        streamLabel = "Connecting"
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.liveReadinessGates,
            intervalMs: streamIntervalMs
        ) else {
            streamLabel = "Offline"
            if gates.isEmpty {
                error = "Invalid live-readiness WebSocket resource URL"
                isLoading = false
            }
            return
        }
        socket.connect(urlString: url, token: token) { [weak self] message in
            self?.applyStream(message)
        }
    }

    private func applyStream(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot([LiveReadinessGateRow].self, from: message)
            gates = snapshot.payload
            transport = snapshot.transport ?? "websocket"
            isStale = snapshot.stale
            lagMs = snapshot.lagMs
            lastUpdatedAt = snapshot.timestamp ?? snapshot.receivedAt
            lastUpdatedDate = Self.parseISO(lastUpdatedAt) ?? Date()
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if gates.isEmpty {
                self.error = error.localizedDescription
                isLoading = false
            }
        }
    }

    // MARK: HTTP fallback

    private func loadGatesFallback(token: String?, baseURL: String) async {
        do {
            let rows: [LiveReadinessGateRow] = try await APIClient.shared.get(
                path: APIEndpoints.liveReadinessGates,
                token: token,
                baseURL: baseURL
            )
            gates = rows
            if !streamIsConnected {
                transport = "http"
                isStale = false
                lagMs = nil
                let now = Date()
                lastUpdatedDate = now
                lastUpdatedAt = ISO8601DateFormatter().string(from: now)
                streamLabel = "Poll"
            }
            isLoading = false
            error = nil
        } catch {
            if gates.isEmpty {
                self.error = error.localizedDescription
                isLoading = false
            } else {
                streamLabel = streamIsConnected ? streamLabel : "Last good"
            }
        }
    }

    private func loadSideStatus(token: String?, baseURL: String) async {
        do {
            liveCanaryStatus = try await APIClient.shared.get(
                path: APIEndpoints.liveCanaryStatus,
                token: token,
                baseURL: baseURL
            )
        } catch {
            if gates.isEmpty && liveCanaryStatus == nil {
                self.error = error.localizedDescription
            }
        }

        do {
            aPlusInventoryStatus = try await APIClient.shared.get(
                path: APIEndpoints.aPlusInventory,
                token: token,
                baseURL: baseURL
            )
        } catch {
            if gates.isEmpty && aPlusInventoryStatus == nil {
                self.error = error.localizedDescription
            }
        }
    }

    // MARK: Helpers

    private static func parseISO(_ value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) { return date }
        let plain = ISO8601DateFormatter()
        return plain.date(from: value)
    }
}
