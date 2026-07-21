import Foundation
import Observation

// MARK: - System Monitor payload models (owned by the System Monitor screen)
//
// The System Monitor screen is a system-health surface, not a dashboard clone.
// It streams `/api/v2/mobile/health` (overall/trainer/gpu + the ingestor rollup
// that carries per-provider health) and layers three supplemental reads:
//   • `/api/v2/data-health`  — per-surface data-feed lag (System Health source)
//   • `/api/v2/public/status`— runtime/supervisor status dimensions
//   • measured round-trips of `/api/auth/health` + `/api/v2/system/health`
//     for the auth / backend / redis latency triple (real client-side timing;
//     never hardcoded).
//
// The shared `MobileIngestorRollup` model does not decode `provider_health`,
// so the health payload is decoded here with an extended local model in the
// same single stream/poll pass — no duplicate fetch.

/// Per-provider health entry from the health ingestor rollup (`provider_health`).
struct MonitorProviderHealthEntry: Decodable, Equatable {
    let status: String?
    let age_seconds: Double?
    let freshness: String?
}

/// Ingestor rollup that additionally decodes `provider_health` (the shared
/// `MobileIngestorRollup` drops it).
struct MonitorIngestorRollup: Decodable, Equatable {
    let overall_status: String?
    let stream_present: [String: Bool]?
    let all_core_streams_present: Bool?
    let provider_health: [String: MonitorProviderHealthEntry]?
    let provider_count: Int?
    let active_provider_count: Int?
    let stale_provider_count: Int?
    let stale_providers: [String]?
}

/// System-health view of `/api/v2/mobile/health`. Trainer/GPU reuse the shared
/// public models; every field is optional so partial backend payloads decode.
struct MonitorHealth: Decodable, Equatable {
    let generated_utc: String?
    let overall: String?
    let redis_connected: Bool?
    let live_gate: String?
    let places_real_order: Bool?
    let trainer: HealthTrainer?
    let gpu: HealthGPU?
    let ingestors: MonitorIngestorRollup?

    var isHealthy: Bool { (overall ?? "").lowercased() == "healthy" }
    var overallLabel: String { (overall ?? "unknown").uppercased() }
}

// MARK: - Public runtime status (/api/v2/public/status)

struct PublicStatusDimensions: Decodable, Equatable {
    let market_data: String?
    let automation: String?
    let execution: String?
    let account: String?
    let live_trading_enabled: Bool?
    let order_submission_enabled: Bool?
    let places_real_order: Bool?
    let exchange_mutation_enabled: Bool?
    let updated_at: String?
}

struct PublicStatus: Decodable, Equatable {
    let live_gate_status: String?
    let runtime_state: String?
    let public_route_failed_count: Int?
    let supervisor_health: String?
    let status_dimensions: PublicStatusDimensions?
}

// MARK: - Backend health probe (/api/v2/system/health)

struct MonitorSystemHealthData: Decodable, Equatable {
    let status: String?
    let service: String?
    let redis_available: Bool?
    let live_gate: String?
}

struct MonitorSystemHealthResponse: Decodable, Equatable {
    let data: MonitorSystemHealthData?
}

// MARK: - Core-service probe (auth / backend / redis)

/// A single measured service probe. `latencyMs` is a real client-side
/// round-trip measurement — never a placeholder constant.
struct ServiceProbe: Equatable, Identifiable {
    let name: String
    let ok: Bool
    let latencyMs: Double?
    let detail: String

    var id: String { name }
    var latencyText: String {
        guard let latencyMs, latencyMs.isFinite else { return "—" }
        if latencyMs < 1 { return "<1ms" }
        return "\(Int(latencyMs.rounded()))ms"
    }
}

// MARK: - Derived view rows

/// One of the seven canonical ingest streams with its flowing/absent state and
/// a color-coded freshness age mapped from the provider health rollup.
struct DataFeedRow: Identifiable, Equatable {
    let id: String        // stream key
    let label: String
    let present: Bool
    let ageSeconds: Double?
    let freshness: String?
}

/// One provider from the ingestor rollup's `provider_health` map.
struct ProviderHealthRow: Identifiable, Equatable {
    let id: String        // provider name
    let status: String?
    let ageSeconds: Double?
    let freshness: String?
}

@MainActor
@Observable
final class MonitorViewModel {

    // Streamed system health.
    private(set) var health: MonitorHealth?
    // Supplemental reads.
    private(set) var dataHealth: DataHealthResponse?
    private(set) var publicStatus: PublicStatus?
    // Core-service latency triple.
    private(set) var authProbe: ServiceProbe?
    private(set) var backendProbe: ServiceProbe?
    private(set) var redisProbe: ServiceProbe?

    private(set) var isLoading = false
    private(set) var error: String?

    // Envelope freshness truth surfaced to the StalenessChip.
    private(set) var streamLabel = "Connecting"
    private(set) var transport: String?
    private(set) var isStale = false
    private(set) var lagMs: Double?
    private(set) var lastUpdatedAt: Date?

    private let socket = WebSocketClient()
    private var fallbackTask: Task<Void, Never>?
    private let streamIntervalMs = 2_000
    private let staleAfterSeconds: Double = 90

    // Canonical ingest streams → representative provider_health source(s) for
    // their freshness age. Flowing/absent always comes from `stream_present`
    // (authoritative); the age is a real freshness proxy from the named
    // upstream provider(s), min-aged across the mapped set.
    private static let feedDefinitions: [(key: String, label: String, providers: [String])] = [
        ("candles", "Candles / OHLCV", ["binance", "kucoin"]),
        ("orderbook_features", "Orderbook features", ["orderbook", "microstructure"]),
        ("trade_tape", "Trade tape", ["binance", "kucoin"]),
        ("funding_oi", "Funding / OI", ["coinank", "coinglass"]),
        ("liquidation_levels", "Liquidation levels", ["liquidations"]),
        ("ta_full", "TA-Lib (full)", ["ta"]),
        ("feature_snapshots", "Feature snapshots", ["feature_snapshot_builder"]),
    ]

    // MARK: - Lifecycle

    func load(token: String?, baseURL: String) async {
        connect(token: token, baseURL: baseURL)
        async let healthLoad: Void = loadHealthFallback(token: token, baseURL: baseURL)
        async let supplemental: Void = loadSupplemental(token: token, baseURL: baseURL)
        _ = await (healthLoad, supplemental)
    }

    func connect(token: String?, baseURL: String) {
        isLoading = health == nil
        error = nil
        streamLabel = "Connecting"

        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileHealth,
            intervalMs: streamIntervalMs
        ) else {
            isLoading = false
            error = "Invalid monitor WebSocket resource URL"
            streamLabel = "Offline"
            return
        }

        socket.connect(urlString: url, token: token) { [weak self] message in
            self?.applyHealthMessage(message)
        }
    }

    func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        connect(token: token, baseURL: baseURL)
        fallbackTask = Task {
            await loadHealthFallback(token: token, baseURL: baseURL)
            await loadSupplemental(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                if !streamIsConnected {
                    connect(token: token, baseURL: baseURL)
                    await loadHealthFallback(token: token, baseURL: baseURL)
                }
                // Supplemental reads have no stream — poll them on the interval.
                await loadSupplemental(token: token, baseURL: baseURL)
            }
        }
    }

    func stopAutoRefresh() {
        fallbackTask?.cancel()
        fallbackTask = nil
        socket.disconnect()
        streamLabel = "Disconnected"
    }

    private var streamIsConnected: Bool {
        if case .connected = socket.state { return true }
        return false
    }

    var streamSummary: String {
        "Health \(streamLabel) · feeds \(dataHealth == nil ? "poll pending" : "poll ok")"
    }

    /// Seconds since the last successful health payload from any transport.
    var dataAgeSeconds: Double? {
        lastUpdatedAt.map { Date().timeIntervalSince($0) }
    }

    /// Honest staleness: envelope stale flag or a payload older than the window.
    var isEffectivelyStale: Bool {
        if isStale { return true }
        if let age = dataAgeSeconds, age > staleAfterSeconds { return true }
        return false
    }

    // MARK: - Fetching

    private func loadHealthFallback(token: String?, baseURL: String) async {
        do {
            let h: MonitorHealth = try await APIClient.shared.get(
                path: APIEndpoints.mobileHealth,
                token: token,
                baseURL: baseURL
            )
            health = h
            isStale = false
            lagMs = nil
            if !streamIsConnected { transport = "http" }
            lastUpdatedAt = Date()
            isLoading = false
            error = nil
        } catch {
            if health == nil {
                self.error = error.localizedDescription
                isLoading = false
            } else {
                streamLabel = "Last good"
            }
        }
    }

    private func applyHealthMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MonitorHealth.self, from: message)
            health = snapshot.payload
            isStale = snapshot.stale
            lagMs = snapshot.lagMs
            transport = snapshot.transport ?? "websocket"
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            lastUpdatedAt = Date()
            isLoading = false
            error = nil
        } catch {
            streamLabel = "Invalid"
            if health == nil {
                self.error = error.localizedDescription
                isLoading = false
            }
        }
    }

    private func loadSupplemental(token: String?, baseURL: String) async {
        async let feeds: Void = loadDataHealth(token: token, baseURL: baseURL)
        async let status: Void = loadPublicStatus(token: token, baseURL: baseURL)
        async let auth: Void = probeAuth(token: token, baseURL: baseURL)
        async let backend: Void = probeBackend(token: token, baseURL: baseURL)
        _ = await (feeds, status, auth, backend)
    }

    private func loadDataHealth(token: String?, baseURL: String) async {
        do {
            let resp: DataHealthResponse = try await APIClient.shared.get(
                path: APIEndpoints.dataHealth,
                token: token,
                baseURL: baseURL
            )
            dataHealth = resp
        } catch {
            // Feeds render an honest absent state; a feed fetch failure must not
            // clobber the streamed health surface.
        }
    }

    private func loadPublicStatus(token: String?, baseURL: String) async {
        do {
            let resp: PublicStatus = try await APIClient.shared.get(
                path: APIEndpoints.publicStatus,
                token: token,
                baseURL: baseURL
            )
            publicStatus = resp
        } catch {
            // Public status is a secondary annotation — ignore fetch failures.
        }
    }

    private func probeAuth(token: String?, baseURL: String) async {
        let start = Date()
        do {
            let h: AuthHealth = try await APIClient.shared.get(
                path: APIEndpoints.authHealth,
                token: token,
                baseURL: baseURL
            )
            let ms = Date().timeIntervalSince(start) * 1000
            authProbe = ServiceProbe(
                name: "AUTH",
                ok: h.isLoginReachable,
                latencyMs: ms,
                detail: h.status.uppercased()
            )
        } catch {
            authProbe = ServiceProbe(
                name: "AUTH",
                ok: false,
                latencyMs: Date().timeIntervalSince(start) * 1000,
                detail: "UNREACHABLE"
            )
        }
    }

    private func probeBackend(token: String?, baseURL: String) async {
        let start = Date()
        do {
            let resp: MonitorSystemHealthResponse = try await APIClient.shared.get(
                path: APIEndpoints.systemHealth,
                token: token,
                baseURL: baseURL
            )
            let ms = Date().timeIntervalSince(start) * 1000
            let status = (resp.data?.status ?? "").lowercased()
            backendProbe = ServiceProbe(
                name: "BACKEND",
                ok: status == "ok",
                latencyMs: ms,
                detail: (resp.data?.status ?? "unknown").uppercased()
            )
            // The system-health probe performs a redis ping (source
            // "fastapi:system_health + redis:ping"), so its round-trip is a real
            // redis-reachability latency. Connection state prefers the explicit
            // redis_available flag, falling back to the streamed redis_connected.
            let redisUp = resp.data?.redis_available ?? health?.redis_connected ?? false
            redisProbe = ServiceProbe(
                name: "REDIS",
                ok: redisUp,
                latencyMs: ms,
                detail: redisUp ? "CONNECTED" : "OFFLINE"
            )
        } catch {
            let ms = Date().timeIntervalSince(start) * 1000
            backendProbe = ServiceProbe(name: "BACKEND", ok: false, latencyMs: ms, detail: "UNREACHABLE")
            let redisUp = health?.redis_connected ?? false
            redisProbe = ServiceProbe(
                name: "REDIS",
                ok: redisUp,
                latencyMs: nil,
                detail: redisUp ? "CONNECTED" : "OFFLINE"
            )
        }
    }

    // MARK: - Derived rows

    /// The seven canonical ingest streams with flowing/absent + freshness age.
    var dataFeedRows: [DataFeedRow] {
        let rollup = health?.ingestors
        let present = rollup?.stream_present ?? [:]
        let providerHealth = rollup?.provider_health ?? [:]
        return Self.feedDefinitions.map { def in
            let entries = def.providers.compactMap { providerHealth[$0] }
            let ages = entries.compactMap { $0.age_seconds }
            let age = ages.min()
            let freshness = Self.worstFreshness(entries.map { $0.freshness })
            return DataFeedRow(
                id: def.key,
                label: def.label,
                present: present[def.key] ?? false,
                ageSeconds: age,
                freshness: freshness
            )
        }
    }

    /// All named data-plane providers from the rollup, problems surfaced first.
    var providerRows: [ProviderHealthRow] {
        guard let map = health?.ingestors?.provider_health else { return [] }
        return map.map { name, entry in
            ProviderHealthRow(
                id: name,
                status: entry.status,
                ageSeconds: entry.age_seconds,
                freshness: entry.freshness
            )
        }
        .sorted { lhs, rhs in
            let lr = Self.freshnessRank(lhs.freshness, status: lhs.status)
            let rr = Self.freshnessRank(rhs.freshness, status: rhs.status)
            if lr != rr { return lr > rr }        // worst (higher rank) first
            return lhs.id < rhs.id
        }
    }

    var dataFeedSurfaces: [DataFeedSurface] {
        dataHealth?.data.surfaces ?? []
    }

    var providerCountLabel: String {
        let r = health?.ingestors
        let total = r?.provider_count ?? providerRows.count
        let active = r?.active_provider_count ?? 0
        let stale = r?.stale_provider_count ?? 0
        return "\(active)/\(total) active · \(stale) stale"
    }

    // MARK: - Freshness helpers

    /// Higher rank == worse. Used to sort/color providers and feeds.
    /// Policy-degraded statuses (ISOLATED_BY_POLICY / quarantined / heartbeat-only)
    /// must rank as degraded even when the heartbeat freshness is "fresh" —
    /// a quarantined provider is not healthy-green (matches the Providers
    /// screen's heartbeat_only yellow rule).
    static func freshnessRank(_ freshness: String?, status: String?) -> Int {
        let f = (freshness ?? "").lowercased()
        let s = (status ?? "").lowercased()
        if s.contains("down") || s.contains("error") || s.contains("fail") || s.isEmpty && f == "unknown" {
            return 3
        }
        if f == "unknown" || s.isEmpty { return 3 }
        if f.contains("stale") || f.contains("delayed") || s.contains("stale") { return 2 }
        if s.contains("isolated") || s.contains("quarantin") || s.contains("heartbeat") || s.contains("degraded")
            || f.contains("isolated") || f.contains("quarantin") || f.contains("degraded") {
            return 2
        }
        if f == "fresh" || s.contains("active") || s.contains("ready") { return 0 }
        return 1
    }

    /// Worst freshness across a set of provider entries (nil-safe).
    static func worstFreshness(_ values: [String?]) -> String? {
        let present = values.compactMap { $0 }
        guard !present.isEmpty else { return nil }
        if present.contains(where: { $0.lowercased() == "unknown" }) { return "unknown" }
        if present.contains(where: { $0.lowercased().contains("stale") || $0.lowercased().contains("delayed") }) {
            return "stale"
        }
        return present.first { $0.lowercased() == "fresh" } ?? present.first
    }
}
