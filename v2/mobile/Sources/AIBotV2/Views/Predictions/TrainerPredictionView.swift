import Foundation
import SwiftUI

// MARK: - Signal Matrix (Predictions / Explainability)
//
// Owns its full data path through PredictionsViewModel (no cross-screen view
// models): rich signal rows + compact symbol×timeframe grid + backtest summary
// + degraded-input alert. Live trading stays operator-gated (BLOCKED) — every
// runtime label is derived from the real payload, never hardcoded to "LIVE".

struct TrainerPredictionView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PredictionsViewModel()
    @State private var showFlatList = false

    var body: some View {
        NavigationStack {
            ScrollView {
                content
                    .padding(16)
                    .padding(.bottom, 32)
            }
            .nerVyxScreen()
            .navigationTitle("Signal Matrix")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) { actionableToggle }
                ToolbarItem(placement: .navigationBarTrailing) { refreshButton }
            }
            .refreshable {
                await vm.load(token: auth.currentToken(), baseURL: appState.baseURL)
            }
        }
        .task {
            await vm.load(token: auth.currentToken(), baseURL: appState.baseURL)
        }
        .onAppear {
            vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
        }
        .onDisappear {
            vm.stopAutoRefresh()
        }
    }

    // MARK: Toolbar

    private var actionableToggle: some View {
        Button { vm.actionableOnly.toggle() } label: {
            HStack(spacing: 4) {
                Image(systemName: vm.actionableOnly ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(vm.actionableOnly ? NerVyx.signal : NerVyx.textMuted)
                Text("Actionable")
                    .font(.system(size: 13))
                    .foregroundStyle(vm.actionableOnly ? NerVyx.signal : NerVyx.textMuted)
            }
        }
        .buttonStyle(.plain)
    }

    private var refreshButton: some View {
        Button {
            Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        } label: {
            Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
        }
    }

    // MARK: State machine

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.signals.isEmpty && vm.matrix == nil {
            loadingSkeleton
        } else if let err = vm.error, vm.signals.isEmpty, vm.matrix == nil {
            ErrorStateView(message: err) {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }
            .frame(minHeight: 420)
        } else if !hasData {
            emptyState
                .frame(minHeight: 420)
        } else {
            dashboard
        }
    }

    private var dashboard: some View {
        VStack(spacing: 12) {
            heroCard
            streamCard
            featureAlertCard
            backtestCard
            if hasGrid { matrixCard }
            flatListCard
            RuntimeTruthLiveCard(title: "Runtime Truth")
        }
    }

    // MARK: Derived

    private var hasGrid: Bool { !(vm.matrix?.cells.isEmpty ?? true) }
    private var hasData: Bool { !vm.signals.isEmpty || hasGrid }

    private var symbolCountValue: Int {
        if hasGrid { return vm.matrix?.symbol_count ?? vm.matrixRows.count }
        return Set(vm.signals.compactMap { $0.symbol }).count
    }

    private var universeCountValue: Int {
        if hasGrid { return vm.matrix?.cell_count ?? (vm.matrix?.cells.count ?? 0) }
        return vm.signals.count
    }

    private var universeLabel: String { hasGrid ? "CELLS" : "SIGNALS" }

    private var effectiveMix: (long: Int, short: Int, hold: Int) {
        if hasGrid { return vm.directionMix }
        var long = 0, short = 0, hold = 0
        for sig in vm.signals {
            let a = (sig.action ?? "").lowercased()
            if a.contains("long") || a.contains("buy") { long += 1 }
            else if a.contains("short") || a.contains("sell") { short += 1 }
            else { hold += 1 }
        }
        return (long, short, hold)
    }

    private var stalenessChip: StalenessChip {
        if vm.matrix == nil && vm.signals.isEmpty {
            return StalenessChip.offline()
        }
        return StalenessChip.from(
            stale: vm.isStale,
            lagMs: vm.envelopeLagMs,
            transport: vm.envelopeTransport,
            ageSeconds: vm.stalenessAgeSeconds
        )
    }

    private var streamLabelColor: Color {
        switch vm.streamLabel.lowercased() {
        case "realtime": return NerVyx.validation
        case "stale": return NerVyx.warning
        case "disconnected", "invalid": return NerVyx.sell
        default: return NerVyx.inference
        }
    }

    // MARK: Hero (avg-confidence ring + direction donut + KPIs)

    private var heroCard: some View {
        let mix = effectiveMix
        return VStack(spacing: 14) {
            HStack {
                MicroLabel(text: "SIGNAL UNIVERSE")
                Spacer()
                NerVyxBadge(text: "OPERATOR GATED", color: NerVyx.liveBlocked, small: true)
            }
            HStack(spacing: 18) {
                RingGauge(
                    value: vm.avgConfidence,
                    label: "AVG EXEC",
                    centerText: hasData ? "\(Int(vm.avgConfidence * 100))%" : "—",
                    color: NerVyx.confidenceColor(vm.avgConfidence),
                    size: 94
                )
                DonutChart(
                    slices: [
                        DonutChart.Slice(label: "L", value: Double(mix.long), color: NerVyx.buy),
                        DonutChart.Slice(label: "S", value: Double(mix.short), color: NerVyx.sell),
                        DonutChart.Slice(label: "H", value: Double(mix.hold), color: NerVyx.neutral),
                    ],
                    centerText: "\(universeCountValue)",
                    centerLabel: universeLabel,
                    size: 98
                )
            }
            HStack(spacing: 8) {
                StatChip(label: "SYMBOLS", value: "\(symbolCountValue)", accent: NerVyx.primary)
                StatChip(label: "ACTIONABLE", value: "\(vm.actionableCount)", color: NerVyx.validation, accent: NerVyx.validation)
                StatChip(label: "LIVE GATE", value: "BLOCKED", color: NerVyx.liveBlocked, accent: NerVyx.liveBlocked)
            }
        }
        .frame(maxWidth: .infinity)
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: Stream truth

    private var streamCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                LivePulse(color: vm.isStale ? NerVyx.warning : NerVyx.signal)
                Text("Signal stream")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                Spacer()
                stalenessChip
            }
            HStack(spacing: 8) {
                StatChip(label: "TRANSPORT", value: (vm.envelopeTransport ?? "http").uppercased(), color: NerVyx.textSecondary)
                StatChip(label: "STREAM", value: vm.streamLabel.uppercased(), color: streamLabelColor)
            }
            DataRow(label: "Live gate", value: vm.liveGateLabel, valueColor: NerVyx.sell)
            if let ts = vm.lastUpdated {
                DataRow(label: "Updated", value: String(ts.prefix(19)), mono: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: vm.isStale ? NerVyx.warning : NerVyx.signal)
    }

    // MARK: Degraded inputs (owned via PredictionsViewModel)

    @ViewBuilder
    private var featureAlertCard: some View {
        if let alert = vm.featureAlert, alert.active {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    SectionHeader(title: "Degraded Inputs · \(alert.severity.uppercased())", accent: alertAccent(alert.severity))
                    Spacer()
                    if let src = vm.featureAlertSource {
                        Text(src)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                }
                Text("Prediction still produced — operating on masked inputs")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(NerVyx.validation)
                    .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 8) {
                    StatChip(
                        label: "COVERAGE",
                        value: alert.data_coverage_pct.map { String(format: "%.1f%%", $0) } ?? "—",
                        color: coverageColor(alert.data_coverage_pct),
                        accent: alertAccent(alert.severity)
                    )
                    StatChip(label: "MISSING", value: "\(alert.missing_feature_count)", color: NerVyx.warning, accent: NerVyx.warning)
                    StatChip(label: "STALE", value: "\(alert.stale_feature_count)", color: NerVyx.textSecondary)
                }
                if !alert.missing_by_category.isEmpty {
                    Text(alert.missing_by_category.map { "\($0.key.replacingOccurrences(of: "_", with: " ")): \($0.value)" }.joined(separator: " · "))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .nerVyxGlassCard(accent: alertAccent(alert.severity))
        }
    }

    // MARK: Backtest & generalization (owned via PredictionsViewModel)

    @ViewBuilder
    private var backtestCard: some View {
        if let bt = vm.backtest, bt.available, let pb = bt.policy_backtest {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    SectionHeader(title: "Backtest & Generalization", accent: NerVyx.inference)
                    Spacer()
                    if bt.continuous_replay_active == true {
                        HStack(spacing: 4) {
                            LivePulse(color: NerVyx.validation).frame(width: 8, height: 8)
                            Text("REPLAY LIVE")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(NerVyx.validation)
                                .tracking(0.5)
                        }
                    }
                }
                if let wr = pb.win_rate {
                    HBarRow(label: "WIN RATE", value: wr, maxAbsValue: 1.0, valueText: String(format: "%.1f%%", wr * 100), color: NerVyx.validation)
                }
                if let pf = pb.profit_factor_proxy {
                    HBarRow(label: "PF PROXY", value: pf, maxAbsValue: max(pf, 2.0), valueText: String(format: "%.2f", pf), color: NerVyx.inference)
                }
                if let exp = pb.expectancy_after_cost_bps {
                    HBarRow(label: "EXPECTANCY", value: exp, maxAbsValue: max(abs(exp), 10), valueText: String(format: "%+.1f bps", exp), signed: true)
                }
                NerVyxDivider()
                if let gen = bt.generalization {
                    DataRow(label: "Train Loss", value: NerVyxFormat.number(gen.loss_after), mono: true)
                    DataRow(label: "Val Loss (OOS)", value: NerVyxFormat.number(gen.validation_supervised_loss), mono: true)
                    DataRow(
                        label: "Overfit Gap",
                        value: NerVyxFormat.number(gen.train_val_generalization_gap),
                        valueColor: (gen.overfit_gap_warning == true) ? NerVyx.warning : NerVyx.validation,
                        mono: true
                    )
                }
                if let rf = bt.replay_feedback {
                    DataRow(label: "Replay→Trainer", value: "\(rf.existing_counterfactual_rows ?? 0) rows", mono: true)
                }
                Text("\(pb.evidence_class ?? "BACKTEST_ONLY") — not A+/live evidence")
                    .font(.system(size: 9))
                    .foregroundStyle(NerVyx.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .nerVyxGlassCard(accent: NerVyx.inference)
        }
    }

    // MARK: True matrix (symbol rows × timeframe columns)

    private var matrixCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                SectionHeader(title: "Signal Matrix", accent: NerVyx.primary)
                Spacer()
                stalenessChip
            }
            searchField
            matrixColumnHeader
            if vm.displayedMatrixRows.isEmpty {
                Text(vm.actionableOnly ? "No actionable cells in the grid." : "No grid cells match your filter.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 12)
            } else {
                LazyVStack(spacing: 6) {
                    ForEach(vm.displayedMatrixRows) { row in
                        matrixRowView(row)
                    }
                }
            }
            matrixLegend
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
            TextField(
                "Filter symbol",
                text: Binding(get: { vm.searchText }, set: { vm.searchText = $0 })
            )
            .font(.system(size: 13, design: .monospaced))
            .foregroundStyle(NerVyx.textPrimary)
            .autocorrectionDisabled()
            .textInputAutocapitalization(.characters)
            if !vm.searchText.isEmpty {
                Button { vm.searchText = "" } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 13))
                        .foregroundStyle(NerVyx.textMuted)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(NerVyx.panel.opacity(0.6))
        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
    }

    private var matrixColumnHeader: some View {
        HStack(spacing: 6) {
            Color.clear.frame(width: 56, height: 1)
            ForEach(vm.matrixTimeframes, id: \.self) { tf in
                Text(tf.uppercased())
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity)
            }
        }
    }

    private func matrixRowView(_ row: PredictionsViewModel.MatrixSymbolRow) -> some View {
        HStack(spacing: 6) {
            Text(row.displaySymbol)
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(row.hasActionable ? NerVyx.validation : NerVyx.textSecondary)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
                .frame(width: 56, alignment: .leading)
            ForEach(Array(row.cells.enumerated()), id: \.offset) { _, cell in
                matrixCell(cell)
            }
        }
    }

    @ViewBuilder
    private func matrixCell(_ cell: SignalMatrixCell?) -> some View {
        if let cell {
            NavigationLink(destination: PredictionDetailView(row: vm.richRow(for: cell))) {
                matrixCellContent(cell)
            }
            .buttonStyle(.plain)
            .frame(maxWidth: .infinity)
        } else {
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(NerVyx.panel.opacity(0.35))
                .frame(height: 42)
                .overlay(
                    Text("·")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted.opacity(0.5))
                )
                .frame(maxWidth: .infinity)
        }
    }

    private func matrixCellContent(_ cell: SignalMatrixCell) -> some View {
        let action = cell.a ?? "hold"
        let color = NerVyx.actionColor(action)
        let conf = min(max(cell.c ?? 0, 0), 1)
        let fillOpacity = 0.16 + conf * 0.5
        return VStack(spacing: 2) {
            Image(systemName: directionIcon(action))
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(color)
            Text(conf > 0 ? "\(Int(conf * 100))" : "—")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(NerVyx.textPrimary)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 42)
        .background(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .fill(color.opacity(fillOpacity))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .stroke(
                    cell.act == true ? NerVyx.validation : color.opacity(0.35),
                    lineWidth: cell.act == true ? 1.5 : 1
                )
        )
        .contentShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
    }

    private func directionIcon(_ action: String) -> String {
        switch action.lowercased() {
        case "long", "buy": return "arrow.up.right"
        case "short", "sell": return "arrow.down.right"
        default: return "minus"
        }
    }

    private var matrixLegend: some View {
        HStack(spacing: 12) {
            legendDot(NerVyx.buy, "Long")
            legendDot(NerVyx.sell, "Short")
            legendDot(NerVyx.neutral, "Hold")
            Spacer()
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 3, style: .continuous)
                    .stroke(NerVyx.validation, lineWidth: 1.5)
                    .frame(width: 12, height: 12)
                Text("actionable")
                    .font(.system(size: 9))
                    .foregroundStyle(NerVyx.textMuted)
            }
        }
    }

    private func legendDot(_ color: Color, _ label: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label)
                .font(.system(size: 9))
                .foregroundStyle(NerVyx.textMuted)
        }
    }

    // MARK: Flat list (accessibility fallback)

    private var flatListCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            flatListHeader
            if showFlatList || !hasGrid {
                if vm.displayed.isEmpty {
                    Text("No signals match the current filter.")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted)
                        .padding(.top, 10)
                } else {
                    LazyVStack(spacing: 0) {
                        ForEach(vm.displayed) { row in
                            NavigationLink(destination: PredictionDetailView(row: row)) {
                                PredictionRowView(row: row)
                            }
                            .buttonStyle(.plain)
                            if row.id != vm.displayed.last?.id {
                                NerVyxDivider()
                            }
                        }
                    }
                    .padding(.top, 6)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    @ViewBuilder
    private var flatListHeader: some View {
        if hasGrid {
            Button {
                SwiftUI.withAnimation(.default) { showFlatList.toggle() }
            } label: {
                HStack {
                    SectionHeader(title: "All Signals · list", accent: NerVyx.signal)
                    Spacer()
                    Text("\(vm.displayed.count)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Image(systemName: showFlatList ? "chevron.up" : "chevron.down")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(NerVyx.textMuted)
                }
            }
            .buttonStyle(.plain)
        } else {
            HStack {
                SectionHeader(title: "All Signals · list", accent: NerVyx.signal)
                Spacer()
                Text("\(vm.displayed.count)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
            }
        }
    }

    // MARK: Empty + redacted loading

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "waveform")
                .font(.system(size: 36))
                .foregroundStyle(NerVyx.textMuted)
            Text(vm.actionableOnly ? "No actionable signals" : "No signals in matrix")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(NerVyx.textSecondary)
            Text("The signal matrix publishes continuously as the trainer runs inference.")
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
            if vm.actionableOnly {
                Button("Show all signals") { vm.actionableOnly = false }
                    .foregroundStyle(NerVyx.signal)
            }
        }
        .padding(32)
        .frame(maxWidth: .infinity)
    }

    private var loadingSkeleton: some View {
        VStack(spacing: 12) {
            VStack(spacing: 14) {
                HStack {
                    MicroLabel(text: "SIGNAL UNIVERSE")
                    Spacer()
                    NerVyxBadge(text: "OPERATOR GATED", color: NerVyx.liveBlocked, small: true)
                }
                HStack(spacing: 18) {
                    RingGauge(value: 0.66, label: "AVG EXEC", centerText: "—", color: NerVyx.signal, size: 94)
                    DonutChart(
                        slices: [
                            DonutChart.Slice(label: "L", value: 3, color: NerVyx.buy),
                            DonutChart.Slice(label: "S", value: 2, color: NerVyx.sell),
                            DonutChart.Slice(label: "H", value: 1, color: NerVyx.neutral),
                        ],
                        centerText: "—",
                        centerLabel: "CELLS",
                        size: 98
                    )
                }
                HStack(spacing: 8) {
                    StatChip(label: "SYMBOLS", value: "—")
                    StatChip(label: "ACTIONABLE", value: "—")
                    StatChip(label: "LIVE GATE", value: "—")
                }
            }
            .frame(maxWidth: .infinity)
            .nerVyxGlassCard(accent: NerVyx.primary)

            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(title: "Signal Matrix", accent: NerVyx.primary)
                ForEach(0..<6, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 7, style: .continuous)
                        .fill(NerVyx.borderSubtle.opacity(0.5))
                        .frame(height: 42)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .nerVyxGlassCard()
        }
        .redacted(reason: .placeholder)
    }

    // MARK: Small helpers

    private func alertAccent(_ severity: String) -> Color {
        switch severity.lowercased() {
        case "critical": return NerVyx.sell
        case "warn": return NerVyx.warning
        case "info": return NerVyx.inference
        default: return NerVyx.validation
        }
    }

    private func coverageColor(_ pct: Double?) -> Color {
        guard let pct else { return NerVyx.textMuted }
        return pct > 80 ? NerVyx.validation : NerVyx.warning
    }
}

// MARK: - Prediction Row (flat-list fallback cell)

struct PredictionRowView: View {
    let row: SignalMatrixRow

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 3)
                .fill(NerVyx.actionColor(row.action ?? "hold"))
                .frame(width: 4, height: 48)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(row.displaySymbol)
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    if let tf = row.timeframe {
                        Text(tf)
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                    Spacer()
                    NerVyxBadge(
                        text: (row.action ?? "hold").uppercased(),
                        color: NerVyx.actionColor(row.action ?? "hold"),
                        small: true
                    )
                }
                HStack(spacing: 8) {
                    ConfidenceBar(value: row.executableConfidence)
                        .frame(width: 70)
                    Text(row.executableConfidencePct)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.confidenceColor(row.executableConfidence))
                    Text(row.paperExplorationTier)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(row.paperExplorationTier == "NONE" ? NerVyx.textMuted : NerVyx.signal)
                        .lineLimit(1)
                    Spacer()
                    if row.actionable == true {
                        HStack(spacing: 3) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(NerVyx.validation)
                            Text("actionable")
                                .font(.system(size: 10))
                                .foregroundStyle(NerVyx.validation)
                        }
                    } else {
                        Text(row.ageLabel)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                }
            }
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}

// MARK: - Prediction Detail (Signal Explainability)

struct PredictionDetailView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    let row: SignalMatrixRow
    @State private var explanation: AIPredictionExplanation?
    @State private var missingAlert: AIPredictionMissingFeatureAlert?

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                heroCard
                degradedCard
                aiReasoningCard
                confidenceCard
                executionCard
                coverageCard
                metaCard
            }
            .padding(16)
            .padding(.bottom, 32)
        }
        .nerVyxScreen()
        .navigationTitle(row.displaySymbol)
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadReasoning() }
    }

    // MARK: Hero (confidence ring)

    private var heroCard: some View {
        VStack(spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.displaySymbol)
                        .font(.system(size: 26, weight: .heavy))
                        .foregroundStyle(NerVyx.textPrimary)
                    HStack(spacing: 6) {
                        Text(row.symbol ?? "—")
                            .font(.system(size: 12))
                            .foregroundStyle(NerVyx.textMuted)
                        if let tf = row.timeframe {
                            Text("· \(tf)")
                                .font(.system(size: 12))
                                .foregroundStyle(NerVyx.textMuted)
                        }
                    }
                }
                Spacer()
                NerVyxBadge(
                    text: (row.action ?? "hold").uppercased(),
                    color: NerVyx.actionColor(row.action ?? "hold")
                )
            }
            HStack(spacing: 18) {
                RingGauge(
                    value: row.executableConfidence,
                    label: "EXECUTABLE",
                    centerText: row.executableConfidencePct,
                    color: NerVyx.confidenceColor(row.executableConfidence),
                    size: 104,
                    lineWidth: 9
                )
                VStack(alignment: .leading, spacing: 9) {
                    miniStat("SELECTED", row.selectedConfidencePct, NerVyx.textPrimary)
                    miniStat("RAW MODEL", row.confidencePct, NerVyx.textSecondary)
                    miniStat("PAPER TIER", row.paperExplorationTier, row.paperExplorationTier == "NONE" ? NerVyx.textMuted : NerVyx.signal)
                    HStack(spacing: 6) {
                        Image(systemName: row.actionable == true ? "checkmark.seal.fill" : "hourglass")
                            .font(.system(size: 11))
                            .foregroundStyle(row.actionable == true ? NerVyx.validation : NerVyx.warning)
                        Text(row.actionable == true ? "ACTIONABLE" : "GATED")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(row.actionable == true ? NerVyx.validation : NerVyx.warning)
                            .tracking(0.5)
                    }
                }
                Spacer()
            }
        }
        .frame(maxWidth: .infinity)
        .nerVyxGlassCard(accent: NerVyx.actionColor(row.action ?? "hold"))
    }

    private func miniStat(_ label: String, _ value: String, _ color: Color) -> some View {
        HStack(spacing: 6) {
            MicroLabel(text: label, size: 9)
            Text(value)
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
        }
    }

    // MARK: Degraded inputs (per-signal, from the same explain payload)

    @ViewBuilder
    private var degradedCard: some View {
        if let alert = missingAlert, alert.active {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    SectionHeader(title: "Degraded Inputs · \(alert.severity.uppercased())", accent: alertAccent(alert.severity))
                    Spacer()
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(alertAccent(alert.severity))
                }
                Text(alert.message)
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 8) {
                    StatChip(
                        label: "COVERAGE",
                        value: alert.data_coverage_pct.map { String(format: "%.1f%%", $0) } ?? "—",
                        color: (alert.data_coverage_pct ?? 0) > 80 ? NerVyx.validation : NerVyx.warning,
                        accent: alertAccent(alert.severity)
                    )
                    StatChip(label: "MISSING", value: "\(alert.missing_feature_count)", color: NerVyx.warning, accent: NerVyx.warning)
                    StatChip(label: "STALE", value: "\(alert.stale_feature_count)", color: NerVyx.textSecondary)
                }
            }
            .nerVyxGlassCard(accent: alertAccent(alert.severity))
        }
    }

    // MARK: AI reasoning (glass sub-cards + SF Symbol per section)

    private struct ReasoningSection: Identifiable {
        var id: String { title }
        let title: String
        let text: String
        let icon: String
        let color: Color
    }

    private func reasoningSections(_ exp: AIPredictionExplanation) -> [ReasoningSection] {
        var out: [ReasoningSection] = []
        func add(_ title: String, _ text: String?, _ icon: String, _ color: Color) {
            if let t = text, !t.isEmpty {
                out.append(ReasoningSection(title: title, text: t, icon: icon, color: color))
            }
        }
        add("What the model sees", exp.summary, "eye.fill", NerVyx.inference)
        add("Signal strength", exp.signal_strength, "waveform.path.ecg", NerVyx.signal)
        add("Confidence", exp.confidence_narrative, "gauge.medium", NerVyx.primary)
        add("Data quality", exp.data_quality_narrative, "checkmark.seal.fill", NerVyx.validation)
        add("Market integrity", exp.market_integrity_narrative, "shield.lefthalf.filled", NerVyx.paper)
        add("Technical drivers", exp.technical_drivers, "chart.xyaxis.line", NerVyx.signal)
        add("Price target", exp.price_target_narrative, "target", NerVyx.inference)
        add("Risk gate", exp.risk_gate_narrative, "lock.shield.fill", NerVyx.warning)
        add("Pipeline state", exp.pipeline_state_narrative, "flowchart.fill", NerVyx.primary)
        return out
    }

    @ViewBuilder
    private var aiReasoningCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "AI Reasoning", accent: NerVyx.inference)
            if let exp = explanation, !reasoningSections(exp).isEmpty {
                ForEach(reasoningSections(exp)) { section in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: section.icon)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(section.color)
                            .frame(width: 24, height: 24)
                            .background(section.color.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
                        VStack(alignment: .leading, spacing: 3) {
                            Text(section.title.uppercased())
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(NerVyx.textMuted)
                                .tracking(0.5)
                            Text(section.text)
                                .font(.system(size: 12))
                                .foregroundStyle(NerVyx.textSecondary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
                    .background(NerVyx.panel.opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
            } else {
                Text("Narrative explainability not published for this signal yet.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    private func loadReasoning() async {
        guard let sym = row.symbol, let tf = row.timeframe else { return }
        do {
            let resp: AIPredictionExplainResponse = try await APIClient.shared.get(
                path: APIEndpoints.predictionsExplain,
                queryItems: [
                    URLQueryItem(name: "symbol", value: sym),
                    URLQueryItem(name: "timeframe", value: tf),
                ],
                token: auth.currentToken(),
                baseURL: appState.baseURL
            )
            explanation = resp.data?.explanation
            missingAlert = resp.data?.missing_feature_alert
        } catch {
            // reasoning is best-effort; the structured detail cards remain.
        }
    }

    // MARK: Confidence truth

    private var confidenceCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Confidence Truth", accent: NerVyx.primary)
            VStack(spacing: 6) {
                HStack {
                    Text("Executable confidence")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    Text(row.executableConfidencePct)
                        .font(.system(size: 20, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.confidenceColor(row.executableConfidence))
                }
                ConfidenceBar(value: row.executableConfidence)
                    .frame(height: 8)
            }
            DataRow(label: "Selected Confidence", value: row.selectedConfidencePct, mono: true)
            DataRow(label: "Raw Model Confidence", value: row.confidencePct, mono: true)
            DataRow(label: "Confidence Type", value: row.confidenceDisplayLabel, mono: false)
            DataRow(label: "Paper Exploration", value: row.paperExplorationTier, valueColor: row.paperExplorationTier == "NONE" ? NerVyx.textSecondary : NerVyx.signal)
            if let expectedNet = row.expected_net_pnl_usd {
                DataRow(label: "Expected Net USD", value: String(format: "$%.2f", expectedNet), valueColor: expectedNet > 0 ? NerVyx.validation : NerVyx.warning, mono: true)
            }
            if let maxLoss = row.expected_max_loss_usd {
                DataRow(label: "Max Loss USD", value: String(format: "$%.2f", maxLoss), valueColor: NerVyx.warning, mono: true)
            }
            DataRow(label: "Why Not A+", value: row.whyNotAPlus)
            DataRow(label: "Why Not Live", value: row.whyNotLiveReady, valueColor: NerVyx.sell)
            if let model = row.model_version {
                DataRow(label: "Model", value: model, mono: true)
            }
            if let ckpt = row.checkpoint_id {
                DataRow(label: "Checkpoint", value: String(ckpt.suffix(20)), mono: true)
            }
            if let move = row.expected_move_bps {
                DataRow(label: "Expected Move", value: String(format: "%+.2f%%", move / 100.0), mono: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: Execution status

    private var executionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Execution Status", accent: NerVyx.signal)
            DataRow(
                label: "Actionable",
                value: row.actionable == true ? "YES" : "NO",
                valueColor: row.actionable == true ? NerVyx.validation : NerVyx.warning
            )
            if let risk = row.risk_state {
                DataRow(label: "Risk State", value: nervyxPublicRuntimeText(risk), valueColor: NerVyx.statusColor(risk))
            }
            if let riskController = row.risk_controller_decision {
                DataRow(label: "Risk Controller", value: nervyxPublicRuntimeText(riskController))
            }
            if let allocator = row.allocator_decision {
                DataRow(label: "Allocator", value: nervyxPublicRuntimeText(allocator))
            }
            if let trainer = row.trainer_feedback_status {
                DataRow(label: "Trainer Feedback", value: nervyxPublicRuntimeText(trainer))
            }
            if let fill = row.paper_fill_status {
                DataRow(label: "Fill Status", value: nervyxPublicRuntimeText(fill).uppercased(), valueColor: NerVyx.textSecondary)
            }
            if let orch = row.orchestrator_state {
                DataRow(label: "Orchestrator", value: nervyxPublicRuntimeText(orch))
            }
            if let gate = row.live_gate {
                DataRow(label: "Live Gate", value: nervyxPublicRuntimeText(gate), valueColor: NerVyx.sell)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    // MARK: Data coverage & integrity (ConfidenceBars kept)

    private var coverageCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Data Coverage & Integrity", accent: NerVyx.inference)
            if let coverage = row.data_coverage_percent {
                VStack(spacing: 6) {
                    HStack {
                        Text("Data Coverage")
                            .font(.system(size: 12))
                            .foregroundStyle(NerVyx.textMuted)
                        Spacer()
                        Text(String(format: "%.1f%%", coverage))
                            .font(.system(size: 14, weight: .bold, design: .monospaced))
                            .foregroundStyle(coverage > 80 ? NerVyx.validation : NerVyx.warning)
                    }
                    ConfidenceBar(value: coverage / 100)
                }
            }
            if let integrity = row.market_state_integrity_score {
                VStack(spacing: 6) {
                    HStack {
                        Text("Market Integrity Score")
                            .font(.system(size: 12))
                            .foregroundStyle(NerVyx.textMuted)
                        Spacer()
                        Text(String(format: "%.1f%%", integrity))
                            .font(.system(size: 14, weight: .bold, design: .monospaced))
                            .foregroundStyle(integrity > 80 ? NerVyx.validation : NerVyx.warning)
                    }
                    ConfidenceBar(value: integrity / 100)
                }
            }
            if let feat = row.feature_coverage_pct {
                DataRow(
                    label: "Feature Coverage",
                    value: String(format: "%.1f%%", feat),
                    valueColor: feat > 80 ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
            }
            if row.data_coverage_percent == nil && row.market_state_integrity_score == nil && row.feature_coverage_pct == nil {
                Text("Coverage telemetry not attached to this signal.")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: Signal meta

    private var metaCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Signal Meta", accent: NerVyx.textMuted)
            if let sid = row.signal_id {
                DataRow(label: "Signal ID", value: String(sid.prefix(24)), mono: true)
            }
            if let gen = row.generated_at {
                DataRow(label: "Generated", value: String(gen.prefix(19)), mono: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.borderSubtle)
    }

    private func alertAccent(_ severity: String) -> Color {
        switch severity.lowercased() {
        case "critical": return NerVyx.sell
        case "warn": return NerVyx.warning
        case "info": return NerVyx.inference
        default: return NerVyx.validation
        }
    }
}
