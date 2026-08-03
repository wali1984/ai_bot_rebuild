import Foundation
import Observation

/// Signal Matrix (Predictions / Explainability) view model.
///
/// Owns the screen's full data path end-to-end (no cross-screen view models):
///   - rich per-signal rows        GET /api/v2/mobile/signals        (WS stream @5s + 10s poll fallback)
///   - compact full-universe grid  GET /api/v2/mobile/signal-matrix  (WS stream @10s + HTTP fallback)
///   - compact backtest summary    GET /api/v2/replay/backtest       (poll — explicitly NOT A+/live evidence)
///   - degraded-input alert        GET /api/v2/predictions/explain   (sampled from the current
///     top-executable-confidence signal — never a hardcoded symbol)
///
/// Read-only telemetry. Live trading stays operator-gated (live_gate=blocked_human_only).
@MainActor
@Observable
public final class PredictionsViewModel {

    // MARK: - Published state

    /// Rich signal rows (flat list fallback + detail tap-through source).
    public private(set) var signals: [SignalMatrixRow] = []
    /// Compact symbol × timeframe grid (slim cells).
    public private(set) var matrix: MobileSignalMatrix?
    /// Grid grouped per symbol, ordered actionable-first then by confidence.
    public private(set) var matrixRows: [MatrixSymbolRow] = []
    /// Compact backtest + generalization summary (owned here, not by the Backtest screen).
    public private(set) var backtest: BacktestResults?
    /// Degraded-input (missing/stale feature) alert for the sampled signal.
    public private(set) var featureAlert: AIPredictionMissingFeatureAlert?
    /// "SYMBOL · tf" the feature alert was sampled from (market-driven, not hardcoded).
    public private(set) var featureAlertSource: String?

    public private(set) var isLoading = false
    public private(set) var error: String?
    public private(set) var streamLabel = "Connecting"
    public private(set) var lastUpdated: String?

    // Envelope / payload freshness truth (feeds the StalenessChip).
    public private(set) var envelopeStale = false
    public private(set) var envelopeLagMs: Double?
    public private(set) var envelopeTransport: String?

    public var actionableOnly = false
    public var searchText = ""

    // MARK: - Grid row type

    public struct MatrixSymbolRow: Identifiable, Equatable {
        public let symbol: String
        /// One slot per timeframe column (nil = no cell published for that slot).
        public let cells: [SignalMatrixCell?]

        public var id: String { symbol }
        public var hasActionable: Bool { cells.contains { $0?.act == true } }
        public var maxConfidence: Double { cells.compactMap { $0?.c }.max() ?? 0 }
        public var displaySymbol: String {
            symbol.hasSuffix("USDT") ? String(symbol.dropLast(4)) : symbol
        }
    }

    // MARK: - Private

    private let signalStream = WebSocketClient()
    private let matrixStream = WebSocketClient()
    private var refreshTask: Task<Void, Never>?
    private var auxTick = 0

    // MARK: - Derived

    public var displayed: [SignalMatrixRow] {
        actionableOnly ? signals.filter { $0.actionable == true } : signals
    }

    public var actionableCount: Int {
        matrix?.actionable_count ?? signals.filter { $0.actionable == true }.count
    }

    public var avgConfidence: Double {
        if let cells = matrix?.cells, !cells.isEmpty {
            let vals = cells.compactMap(\.c)
            guard !vals.isEmpty else { return 0 }
            return vals.reduce(0, +) / Double(vals.count)
        }
        let vals = signals.map(\.executableConfidence)
        guard !vals.isEmpty else { return 0 }
        return vals.reduce(0, +) / Double(vals.count)
    }

    /// Timeframe column order straight from the payload — never hardcoded.
    public var matrixTimeframes: [String] {
        if let tfs = matrix?.timeframes, !tfs.isEmpty { return tfs }
        var seen: [String] = []
        for cell in matrix?.cells ?? [] where !seen.contains(cell.tf) {
            seen.append(cell.tf)
        }
        return seen
    }

    /// Grid rows after actionable-only + symbol search filters.
    public var displayedMatrixRows: [MatrixSymbolRow] {
        var rows = matrixRows
        if actionableOnly {
            rows = rows.filter(\.hasActionable)
        }
        let query = searchText.trimmingCharacters(in: .whitespaces).uppercased()
        if !query.isEmpty {
            rows = rows.filter { $0.symbol.uppercased().contains(query) }
        }
        return rows
    }

    /// Direction mix across all published cells (long / short / hold-or-none).
    public var directionMix: (long: Int, short: Int, hold: Int) {
        var long = 0, short = 0, hold = 0
        for cell in matrix?.cells ?? [] {
            let a = (cell.a ?? "").lowercased()
            if a.contains("long") || a.contains("buy") { long += 1 }
            else if a.contains("short") || a.contains("sell") { short += 1 }
            else { hold += 1 }
        }
        return (long, short, hold)
    }

    /// Combined envelope + payload staleness truth.
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

    /// Rich row for a slim grid cell: real signal row when published, otherwise
    /// an honest partial row built only from fields the matrix actually carries.
    public func richRow(for cell: SignalMatrixCell) -> SignalMatrixRow {
        if let match = signals.first(where: { $0.symbol == cell.s && $0.timeframe == cell.tf }) {
            return match
        }
        return SignalMatrixRow(
            signal_id: "matrix:\(cell.s):\(cell.tf)",
            symbol: cell.s,
            timeframe: cell.tf,
            action: cell.a,
            confidence: nil,
            confidence_selected_action: nil,
            confidence_executable_trade: cell.c,
            confidence_display_label: nil,
            confidence_type: nil,
            confidence_a_plus_eligible: nil,
            confidence_tradeability_block_reasons: nil,
            paper_exploration_tier: nil,
            exploration_tier: nil,
            paper_exploration_current_blocker: cell.g,
            paper_exploration_paper_fill_allowed: cell.act,
            paper_exploration_risk_controller_decision: nil,
            paper_exploration_orchestrator_decision: nil,
            paper_exploration_allocator_decision: nil,
            expected_net_pnl_usd: nil,
            expected_max_loss_usd: nil,
            why_not_a_plus: cell.g.map { [$0] },
            why_not_live_ready: nil,
            risk_controller_decision: nil,
            allocator_decision: nil,
            trainer_feedback_status: nil,
            actionable: cell.act,
            live_gate: matrix?.live_gate,
            risk_state: nil,
            paper_fill_status: nil,
            data_coverage_percent: nil,
            market_state_integrity_score: nil,
            generated_at: matrix?.payload_generated_utc,
            age_seconds: matrix?.staleness_seconds,
            model_version: nil,
            checkpoint_id: nil,
            expected_move_bps: nil,
            feature_coverage_pct: nil,
            orchestrator_state: nil
        )
    }

    // MARK: - Loading

    public func load(token: String?, baseURL: String) async {
        isLoading = signals.isEmpty && matrix == nil
        error = nil
        await loadSignals(token: token, baseURL: baseURL)
        await loadMatrix(token: token, baseURL: baseURL)
        await loadAuxiliary(token: token, baseURL: baseURL)
        // Honest empty (endpoints reachable but no rows) is NOT an error;
        // error is only set by the individual loaders on transport failure.
        isLoading = false
    }

    public func startAutoRefresh(token: String?, baseURL: String) {
        stopAutoRefresh()
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
                // Backtest + degraded-input alert are HTTP-only; slow cadence.
                auxTick += 1
                if auxTick % 2 == 0 {
                    await loadAuxiliary(token: token, baseURL: baseURL)
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

    // MARK: - HTTP loaders

    private func loadSignals(token: String?, baseURL: String) async {
        do {
            let response: MobileSignalsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignals,
                token: token,
                baseURL: baseURL
            )
            signals = response.signals.map(Self.mapRow)
            lastUpdated = ISO8601DateFormatter().string(from: Date())
            error = nil
        } catch {
            if signals.isEmpty && matrix == nil { self.error = error.localizedDescription }
        }
    }

    private func loadMatrix(token: String?, baseURL: String) async {
        do {
            let response: MobileSignalMatrix = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignalMatrix,
                token: token,
                baseURL: baseURL
            )
            applyMatrix(response, transport: "http", stale: nil, lagMs: nil)
        } catch {
            if signals.isEmpty && matrix == nil { self.error = error.localizedDescription }
        }
    }

    private func loadAuxiliary(token: String?, baseURL: String) async {
        do {
            let results: BacktestResults = try await APIClient.shared.get(
                path: APIEndpoints.replayBacktest,
                token: token,
                baseURL: baseURL
            )
            backtest = results
        } catch {
            // best-effort card; leave the previous summary in place
        }
        await loadFeatureAlert(token: token, baseURL: baseURL)
    }

    private func loadFeatureAlert(token: String?, baseURL: String) async {
        // Sample the alert from the current top-executable-confidence signal,
        // falling back to the first directional grid cell. Market-driven —
        // no hardcoded symbol list, honest empty when nothing is published.
        var target: (symbol: String, timeframe: String)?
        if let top = signals.max(by: { $0.executableConfidence < $1.executableConfidence }),
           let sym = top.symbol, let tf = top.timeframe {
            target = (sym, tf)
        } else if let cell = matrix?.cells.first(where: { $0.a != nil }) {
            target = (cell.s, cell.tf)
        }
        guard let target else {
            featureAlert = nil
            featureAlertSource = nil
            return
        }
        do {
            let explain: AIPredictionExplainResponse = try await APIClient.shared.get(
                path: APIEndpoints.predictionsExplain,
                queryItems: [
                    URLQueryItem(name: "symbol", value: target.symbol),
                    URLQueryItem(name: "timeframe", value: target.timeframe),
                ],
                token: token,
                baseURL: baseURL
            )
            featureAlert = explain.data?.missing_feature_alert
            featureAlertSource = "\(target.symbol) · \(target.timeframe)"
        } catch {
            // best-effort; keep the prior alert
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
            intervalMs: 5_000
        ) else { return }
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
            signals = snapshot.payload.signals.map(Self.mapRow)
            streamLabel = snapshot.stale ? "Stale" : "Realtime"
            isLoading = false
            error = nil
            lastUpdated = snapshot.timestamp ?? ISO8601DateFormatter().string(from: Date())
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
        envelopeTransport = transport
        envelopeStale = stale ?? false
        envelopeLagMs = lagMs
        lastUpdated = ISO8601DateFormatter().string(from: Date())
        rebuildMatrixRows()
    }

    private func rebuildMatrixRows() {
        guard let matrix else {
            matrixRows = []
            return
        }
        let timeframes = matrixTimeframes
        var bySymbol: [String: [String: SignalMatrixCell]] = [:]
        for cell in matrix.cells {
            bySymbol[cell.s, default: [:]][cell.tf] = cell
        }
        matrixRows = bySymbol
            .map { symbol, cells in
                MatrixSymbolRow(symbol: symbol, cells: timeframes.map { cells[$0] })
            }
            .sorted { lhs, rhs in
                if lhs.hasActionable != rhs.hasActionable { return lhs.hasActionable }
                if lhs.maxConfidence != rhs.maxConfidence { return lhs.maxConfidence > rhs.maxConfidence }
                return lhs.symbol < rhs.symbol
            }
    }

    // MARK: - Mapping

    private static func mapRow(_ sig: MobileSignal) -> SignalMatrixRow {
        SignalMatrixRow(
            signal_id: sig.id,
            symbol: sig.symbol,
            timeframe: sig.timeframe,
            action: sig.action,
            confidence: sig.confidence,
            confidence_selected_action: sig.confidence_selected_action,
            confidence_executable_trade: sig.confidence_executable_trade,
            confidence_display_label: sig.confidence_display_label,
            confidence_type: sig.confidence_type,
            confidence_a_plus_eligible: sig.confidence_a_plus_eligible,
            confidence_tradeability_block_reasons: sig.confidence_tradeability_block_reasons,
            paper_exploration_tier: sig.paper_exploration_tier,
            exploration_tier: sig.exploration_tier,
            paper_exploration_current_blocker: sig.paper_exploration_current_blocker,
            paper_exploration_paper_fill_allowed: sig.paper_exploration_paper_fill_allowed,
            paper_exploration_risk_controller_decision: sig.paper_exploration_risk_controller_decision,
            paper_exploration_orchestrator_decision: sig.paper_exploration_orchestrator_decision,
            paper_exploration_allocator_decision: sig.paper_exploration_allocator_decision,
            expected_net_pnl_usd: sig.expected_net_pnl_usd,
            expected_max_loss_usd: sig.expected_max_loss_usd,
            why_not_a_plus: sig.why_not_a_plus,
            why_not_live_ready: sig.why_not_live_ready,
            risk_controller_decision: sig.risk_controller_decision,
            allocator_decision: sig.allocator_decision,
            trainer_feedback_status: sig.trainer_feedback_status,
            actionable: sig.actionable,
            live_gate: nil,
            risk_state: sig.risk_state,
            paper_fill_status: sig.paper_fill_status,
            data_coverage_percent: sig.data_coverage,
            market_state_integrity_score: nil,
            generated_at: sig.published_at,
            age_seconds: nil,
            model_version: sig.model_version,
            checkpoint_id: sig.checkpoint_id,
            expected_move_bps: sig.expected_move_bps,
            feature_coverage_pct: sig.data_coverage,
            orchestrator_state: nil
        )
    }
}
