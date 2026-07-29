import Foundation
import Observation

/// Signals ("NERVYX SENSE") screen view model.
///
/// Owns the screen's full data path end-to-end (read-only telemetry):
///   - rich per-signal rows   GET /api/v2/mobile/signals        (WS stream @5s + HTTP fallback)
///   - symbols × timeframes    GET /api/v2/mobile/signal-matrix  (WS stream @10s + HTTP fallback)
///   - prediction accuracy +   GET /api/v2/mobile/dashboard      (poll — paper.signal_prediction_accuracy
///     runtime mode                                               + trainer.effective_trainer_mode)
///
/// Direction-mix and routing counts are derived from the current published
/// signals/cells (honest tallies of what is on screen). Prediction accuracy is
/// NEVER computed client-side — it is read straight from the backend paper
/// block (winner-flag accuracy, same definition as adaptive-capital).
///
/// Live trading stays operator-gated (live_gate=blocked_human_only).
@MainActor
@Observable
public final class SignalsViewModel {

    // MARK: - Published state

    /// Rich signal rows (full runtime-truth detail + tap-through source).
    public private(set) var response: MobileSignalsResponse?
    /// Compact symbols × timeframes grid (slim cells, full universe coverage).
    public private(set) var matrix: MobileSignalMatrix?
    /// Grid grouped per symbol, actionable-first then by confidence.
    public private(set) var groups: [SymbolGroup] = []
    /// Backend prediction accuracy (winner-flag; never computed on device).
    public private(set) var accuracy: SignalPredictionAccuracy?
    /// Actual trainer runtime mode string (drives the empty-state copy).
    public private(set) var runtimeMode: String?

    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdated: String?

    // Envelope / payload freshness truth (feeds the StalenessChip).
    public private(set) var envelopeStale = false
    public private(set) var envelopeLagMs: Double?
    public private(set) var envelopeTransport: String?

    public var actionableOnly: Bool = false
    public var searchText: String = ""

    // MARK: - Symbol group

    public struct SymbolGroup: Identifiable, Equatable {
        public let symbol: String
        /// Rich signals published for this symbol (full detail available).
        public let signals: [MobileSignal]
        /// Matrix cells for timeframes NOT already covered by a rich signal.
        public let extraCells: [SignalMatrixCell]

        public var id: String { symbol }
        public var displaySymbol: String {
            symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
        }
        public var hasActionable: Bool {
            signals.contains { $0.actionable } || extraCells.contains { $0.act == true }
        }
        public var maxConfidence: Double {
            let a = signals.map(\.executableConfidence).max() ?? 0
            let b = extraCells.compactMap(\.c).max() ?? 0
            return max(a, b)
        }
        public var cellCount: Int { signals.count + extraCells.count }
        /// Directional summary badge action for the strongest signal/cell.
        public var topAction: String {
            if let sig = signals.max(by: { $0.executableConfidence < $1.executableConfidence }) {
                return sig.action
            }
            if let cell = extraCells.max(by: { ($0.c ?? 0) < ($1.c ?? 0) }) {
                return cell.a ?? "hold"
            }
            return "hold"
        }
    }

    // MARK: - Private

    private let signalStream = WebSocketClient()
    private let matrixStream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?
    private var lastToken: String?
    private var lastBaseURL: String = ""
    private var auxTick = 0

    // MARK: - Derived

    public var signals: [MobileSignal] { response?.signals ?? [] }

    public var hasAnyData: Bool { !signals.isEmpty || matrix != nil }

    /// Symbols on screen after the actionable + search filters.
    public var displayedGroups: [SymbolGroup] {
        var rows = groups
        if actionableOnly {
            rows = rows.compactMap { group in
                let sigs = group.signals.filter { $0.actionable }
                let cells = group.extraCells.filter { $0.act == true }
                if sigs.isEmpty && cells.isEmpty { return nil }
                return SymbolGroup(symbol: group.symbol, signals: sigs, extraCells: cells)
            }
        }
        let query = searchText.trimmingCharacters(in: .whitespaces).uppercased()
        if !query.isEmpty {
            rows = rows.filter {
                $0.symbol.uppercased().contains(query) || $0.displaySymbol.uppercased().contains(query)
            }
        }
        return rows
    }

    public var totalCellCount: Int {
        matrix?.cell_count ?? matrix?.cells.count ?? signals.count
    }

    public var actionableCount: Int {
        if let count = matrix?.actionable_count { return count }
        return signals.filter { $0.actionable }.count
    }

    /// Direction mix across the widest available set (matrix cells → else signals).
    public var directionMix: (long: Int, short: Int, hold: Int) {
        if let cells = matrix?.cells, !cells.isEmpty {
            return Self.tallyDirection(cells.map { $0.a })
        }
        return Self.tallyDirection(signals.map { $0.action })
    }

    /// Routing split: actionable (paper-fill allowed) vs gated (directional but
    /// blocked) vs hold (non-directional / no route).
    public var routing: (actionable: Int, gated: Int, hold: Int) {
        if let cells = matrix?.cells, !cells.isEmpty {
            var actionable = 0, gated = 0, hold = 0
            for cell in cells {
                let directional = Self.isDirectional(cell.a)
                if cell.act == true { actionable += 1 }
                else if directional { gated += 1 }
                else { hold += 1 }
            }
            return (actionable, gated, hold)
        }
        var actionable = 0, gated = 0, hold = 0
        for sig in signals {
            if sig.actionable { actionable += 1 }
            else if sig.isDirectional { gated += 1 }
            else { hold += 1 }
        }
        return (actionable, gated, hold)
    }

    /// Backend prediction accuracy (winner-flag). Nil when no evidence yet.
    public var predictionAccuracy: Double? {
        guard let value = accuracy?.overall_accuracy, value.isFinite else { return nil }
        return value
    }

    /// Combined envelope + matrix freshness truth.
    public var isStale: Bool {
        if envelopeStale { return true }
        let status = (matrix?.freshness_status ?? "").lowercased()
        if status == "stale" || status == "unavailable" { return true }
        if let age = matrix?.staleness_seconds, age > 240 { return true }
        return false
    }

    public var stalenessAgeSeconds: Double? {
        matrix?.staleness_seconds ?? envelopeLagMs.map { $0 / 1000 }
    }

    public var liveGateLabel: String {
        nervyxPublicRuntimeText(matrix?.live_gate ?? "blocked_human_only")
    }

    /// Real trainer runtime mode string for the empty-state copy (no hardcoding).
    public var runtimeModeLabel: String? {
        guard let mode = runtimeMode, !mode.isEmpty else { return nil }
        return nervyxPublicRuntimeText(mode)
    }

    /// Rich signal for a matrix cell when one is published (full-detail tap-through).
    public func richSignal(for cell: SignalMatrixCell) -> MobileSignal? {
        signals.first { $0.symbol == cell.s && $0.timeframe == cell.tf }
    }

    // MARK: - Loading

    public func load(token: String?, baseURL: String) async {
        lastToken = token
        lastBaseURL = baseURL
        isLoading = !hasAnyData
        await loadSignals(token: token, baseURL: baseURL)
        await loadMatrix(token: token, baseURL: baseURL)
        await loadDashboardAux(token: token, baseURL: baseURL)
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
        lastToken = token
        lastBaseURL = baseURL
        connectSignalStream(token: token, baseURL: baseURL)
        connectMatrixStream(token: token, baseURL: baseURL)
        refreshTask = Task {
            await load(token: token, baseURL: baseURL)
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(10))
                guard !Task.isCancelled else { break }
                if !isConnected(signalStream) {
                    connectSignalStream(token: token, baseURL: baseURL)
                    await loadSignals(token: token, baseURL: baseURL)
                }
                if !isConnected(matrixStream) {
                    connectMatrixStream(token: token, baseURL: baseURL)
                    await loadMatrix(token: token, baseURL: baseURL)
                }
                // Accuracy + runtime mode are HTTP-only; slower cadence (~30s).
                auxTick += 1
                if auxTick % 3 == 0 {
                    await loadDashboardAux(token: token, baseURL: baseURL)
                }
            }
        }
    }

    public func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
        signalStream.disconnect()
        matrixStream.disconnect()
        streamLabel = "Disconnected"
        envelopeTransport = nil
    }

    public func refresh() async {
        await load(token: lastToken, baseURL: lastBaseURL)
    }

    // MARK: - HTTP loaders

    private func loadSignals(token: String?, baseURL: String) async {
        do {
            let resp: MobileSignalsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignals,
                queryItems: [URLQueryItem(name: "limit", value: "200")],
                token: token,
                baseURL: baseURL
            )
            response = resp
            error = nil
            lastUpdated = resp.generated_utc
            rebuildGroups()
        } catch {
            if !hasAnyData { self.error = error.localizedDescription }
        }
    }

    private func loadMatrix(token: String?, baseURL: String) async {
        do {
            let resp: MobileSignalMatrix = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignalMatrix,
                token: token,
                baseURL: baseURL
            )
            applyMatrix(resp, transport: "http", stale: nil, lagMs: nil)
        } catch {
            if !hasAnyData { self.error = error.localizedDescription }
        }
    }

    private func loadDashboardAux(token: String?, baseURL: String) async {
        do {
            let probe: SignalsDashboardProbe = try await APIClient.shared.get(
                path: APIEndpoints.mobileDashboardCurrentSession,
                token: token,
                baseURL: baseURL
            )
            if let acc = probe.paper?.signal_prediction_accuracy {
                accuracy = acc
            }
            let mode = probe.trainer?.effective_trainer_mode.flatMap { $0.isEmpty ? nil : $0 }
                ?? probe.trainer?.state.flatMap { $0.isEmpty ? nil : $0 }
            if let mode { runtimeMode = mode }
        } catch {
            // best-effort supplementary card; keep the previous values
        }
    }

    // MARK: - WebSocket streams

    private func isConnected(_ stream: WebSocketClient) -> Bool {
        if case .connected = stream.state { return true }
        return false
    }

    private func connectSignalStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileSignals,
            queryItems: [URLQueryItem(name: "limit", value: "200")],
            intervalMs: 5_000
        ) else {
            streamLabel = "Offline"
            return
        }
        streamLabel = "Connecting"
        signalStream.connect(urlString: url, token: token) { [weak self] message in
            self?.applySignalMessage(message)
        }
    }

    private func connectMatrixStream(token: String?, baseURL: String) {
        guard let url = APIEndpoints.wsResourceURL(
            baseURL: baseURL,
            path: APIEndpoints.mobileSignalMatrix,
            intervalMs: 10_000
        ) else { return }
        matrixStream.connect(urlString: url, token: token) { [weak self] message in
            self?.applyMatrixMessage(message)
        }
    }

    private func applySignalMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobileSignalsResponse.self, from: message)
            response = snapshot.payload
            envelopeStale = snapshot.stale
            envelopeLagMs = snapshot.lagMs
            envelopeTransport = snapshot.transport ?? "websocket"
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            lastUpdated = snapshot.timestamp ?? snapshot.payload.generated_utc
            isLoading = false
            error = nil
            rebuildGroups()
        } catch {
            streamLabel = "Invalid"
        }
    }

    private func applyMatrixMessage(_ message: String) {
        do {
            let snapshot = try decodeMobileResourceSnapshot(MobileSignalMatrix.self, from: message)
            applyMatrix(
                snapshot.payload,
                transport: snapshot.transport ?? "websocket",
                stale: snapshot.stale,
                lagMs: snapshot.lagMs
            )
            isLoading = false
            error = nil
        } catch {
            // keep last-good grid; the 10s poll fallback still refreshes it
        }
    }

    private func applyMatrix(_ payload: MobileSignalMatrix, transport: String, stale: Bool?, lagMs: Double?) {
        matrix = payload
        if let stale { envelopeStale = envelopeStale || stale }
        if let lagMs { envelopeLagMs = lagMs }
        envelopeTransport = envelopeTransport ?? transport
        rebuildGroups()
    }

    // MARK: - Grouping

    private func rebuildGroups() {
        var signalsBySymbol: [String: [MobileSignal]] = [:]
        var timeframesBySymbol: [String: Set<String>] = [:]
        for sig in signals {
            signalsBySymbol[sig.symbol, default: []].append(sig)
            timeframesBySymbol[sig.symbol, default: []].insert(sig.timeframe)
        }

        var extraBySymbol: [String: [SignalMatrixCell]] = [:]
        for cell in matrix?.cells ?? [] {
            let covered = timeframesBySymbol[cell.s] ?? []
            if !covered.contains(cell.tf) {
                extraBySymbol[cell.s, default: []].append(cell)
            }
        }

        var symbols = Set(signalsBySymbol.keys)
        symbols.formUnion(extraBySymbol.keys)

        groups = symbols.map { symbol in
            let sigs = (signalsBySymbol[symbol] ?? [])
                .sorted { $0.executableConfidence > $1.executableConfidence }
            let cells = (extraBySymbol[symbol] ?? [])
                .sorted { ($0.c ?? 0) > ($1.c ?? 0) }
            return SymbolGroup(symbol: symbol, signals: sigs, extraCells: cells)
        }
        .sorted { lhs, rhs in
            if lhs.hasActionable != rhs.hasActionable { return lhs.hasActionable }
            if lhs.maxConfidence != rhs.maxConfidence { return lhs.maxConfidence > rhs.maxConfidence }
            return lhs.symbol < rhs.symbol
        }
    }

    // MARK: - Helpers

    private static func isDirectional(_ action: String?) -> Bool {
        let value = (action ?? "").lowercased()
        return value.contains("long") || value.contains("short")
            || value.contains("buy") || value.contains("sell")
    }

    private static func tallyDirection(_ actions: [String?]) -> (long: Int, short: Int, hold: Int) {
        var long = 0, short = 0, hold = 0
        for action in actions {
            let value = (action ?? "").lowercased()
            if value.contains("long") || value.contains("buy") { long += 1 }
            else if value.contains("short") || value.contains("sell") { short += 1 }
            else { hold += 1 }
        }
        return (long, short, hold)
    }
}

// MARK: - Dashboard probe (minimal decode of the fields the Signals screen needs)
//
// The mobile dashboard payload is large; JSONDecoder ignores unknown keys, so
// this slim probe pulls only the additive prediction-accuracy block and the
// real trainer runtime mode without depending on the full DashboardPayload.

private struct SignalsDashboardProbe: Decodable {
    let paper: SignalsPaperProbe?
    let trainer: SignalsTrainerProbe?
}

private struct SignalsPaperProbe: Decodable {
    let signal_prediction_accuracy: SignalPredictionAccuracy?
}

private struct SignalsTrainerProbe: Decodable {
    let state: String?
    let effective_trainer_mode: String?
}
