import SwiftUI

// MARK: - Signals ("NERVYX SENSE") screen
//
// Website Signals-page parity on mobile:
//   - header analytics band: direction-mix donut, routing split (actionable /
//     gated / hold) mini bars, and a backend prediction-accuracy ring
//   - symbols × timeframes matrix feel: rows grouped per symbol with the rich
//     per-signal confidence bar + paper-exploration tier preserved, plus a
//     matrix-cell chip strip for extra timeframes
//   - freshness truth via the shared StalenessChip (envelope + matrix staleness)
//   - full runtime-truth detail (live_gate / actionable / paper_fill, expected
//     net & max loss, why-not-A+/why-not-live) in glass cards with a confidence gauge
//
// Read-only telemetry. Live trading stays operator-gated (blocked_human_only).

struct SignalsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = SignalsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && !vm.hasAnyData {
                    loadingSkeleton
                } else if let err = vm.error, !vm.hasAnyData {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    content
                }
            }
            .nerVyxScreen()
            .navigationTitle("NERVYX SENSE")
            .navigationBarTitleDisplayMode(.large)
            .searchable(text: $vm.searchText, prompt: "Filter by symbol")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) { actionableToggle }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                    }
                    .disabled(vm.isLoading)
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Toolbar

    private var actionableToggle: some View {
        Button {
            vm.actionableOnly.toggle()
        } label: {
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

    // MARK: - Freshness truth

    private var freshnessChip: StalenessChip {
        guard vm.hasAnyData else { return .offline() }
        return StalenessChip.from(
            stale: vm.isStale,
            lagMs: vm.envelopeLagMs,
            transport: vm.envelopeTransport,
            ageSeconds: vm.stalenessAgeSeconds
        )
    }

    // MARK: - Loading skeleton (redacted replica)

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 14) {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel).frame(height: 210)
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel).frame(height: 120)
                ForEach(0..<5, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(NerVyx.panel).frame(height: 96)
                }
            }
            .padding(16)
            .redacted(reason: .placeholder)
        }
        .scrollDisabled(true)
    }

    // MARK: - Content

    @ViewBuilder
    private var content: some View {
        ScrollView {
            LazyVStack(spacing: 14) {
                analyticsBand
                    .padding(.top, 4)

                RuntimeTruthLiveCard(title: "Runtime Truth")

                if vm.displayedGroups.isEmpty {
                    emptyState
                } else {
                    ForEach(vm.displayedGroups) { group in
                        SymbolGroupCard(group: group, liveGate: vm.liveGateLabel)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Analytics band

    private var analyticsBand: some View {
        let mix = vm.directionMix
        let route = vm.routing
        return VStack(alignment: .leading, spacing: 14) {
            HStack {
                SectionHeader(title: "Signal Intelligence", accent: NerVyx.signal)
                Spacer()
                freshnessChip
            }

            HStack(alignment: .center, spacing: 18) {
                DonutChart(
                    slices: [
                        .init(label: "Long", value: Double(mix.long), color: NerVyx.buy),
                        .init(label: "Short", value: Double(mix.short), color: NerVyx.sell),
                        .init(label: "Hold", value: Double(mix.hold), color: NerVyx.neutral),
                    ],
                    centerText: "\(vm.totalCellCount)",
                    centerLabel: "SIGNALS"
                )
                Spacer(minLength: 8)
                RingGauge(
                    value: vm.predictionAccuracy ?? 0,
                    label: "PRED ACCURACY",
                    centerText: accuracyCenterText,
                    color: accuracyColor,
                    size: 88
                )
            }

            VStack(alignment: .leading, spacing: 6) {
                MicroLabel(text: "ROUTING")
                MiniBarChart(entries: [
                    .init(label: "ACTIONABLE", value: Double(route.actionable), color: NerVyx.validation),
                    .init(label: "GATED", value: Double(route.gated), color: NerVyx.warning),
                    .init(label: "HOLD", value: Double(route.hold), color: NerVyx.neutral),
                ])
            }

            NerVyxDivider()

            HStack(spacing: 8) {
                StatChip(label: "LIVE GATE", value: vm.liveGateLabel, color: NerVyx.liveBlocked, accent: NerVyx.liveBlocked)
                StatChip(label: "ACTIONABLE", value: "\(vm.actionableCount)", color: NerVyx.validation, accent: NerVyx.validation)
                Spacer()
                Text(accuracyFootnote)
                    .font(.system(size: 9))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    private var accuracyCenterText: String {
        guard let acc = vm.predictionAccuracy else { return "—" }
        return "\(Int((acc * 100).rounded()))%"
    }

    private var accuracyColor: Color {
        guard let acc = vm.predictionAccuracy else { return NerVyx.textMuted }
        return NerVyx.confidenceColor(acc)
    }

    private var accuracyFootnote: String {
        guard let evaluated = vm.accuracy?.evaluated_row_count, evaluated > 0 else {
            return "winner-flag · awaiting closed trades"
        }
        return "winner-flag · \(evaluated) evaluated"
    }

    // MARK: - Empty state

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "antenna.radiowaves.left.and.right.slash")
                .font(.system(size: 34))
                .foregroundStyle(NerVyx.textMuted)
            Text(vm.actionableOnly ? "No actionable signals right now" : "No signals in the current stream")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(NerVyx.textSecondary)
            Text(emptyStateDetail)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40)
        .padding(.horizontal, 24)
        .nerVyxGlassCard(accent: NerVyx.borderSubtle)
    }

    private var emptyStateDetail: String {
        if let mode = vm.runtimeModeLabel {
            return "Trainer runtime mode: \(mode).\nSignals publish continuously as market data is processed."
        }
        return "Signals publish continuously as market data is processed."
    }
}

// MARK: - Symbol group card

struct SymbolGroupCard: View {
    let group: SignalsViewModel.SymbolGroup
    let liveGate: String

    private var actionColor: Color { NerVyx.actionColor(group.topAction) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header

            ForEach(group.signals) { sig in
                NavigationLink(destination: SignalDetailView(signal: sig)) {
                    SignalRowView(signal: sig)
                }
                .buttonStyle(.plain)
            }

            if !group.extraCells.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    MicroLabel(text: "Other timeframes")
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 62), spacing: 6)],
                        alignment: .leading,
                        spacing: 6
                    ) {
                        ForEach(group.extraCells) { cell in
                            NavigationLink(destination: SignalCellDetailView(cell: cell, liveGateLabel: liveGate)) {
                                MatrixCellChip(cell: cell)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
                .padding(.top, 2)
            }
        }
        .nerVyxGlassCard(accent: actionColor)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text(group.displaySymbol)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(NerVyx.textPrimary)
            NerVyxBadge(text: group.topAction.uppercased(), color: actionColor, small: true)
            Spacer()
            if group.hasActionable {
                HStack(spacing: 3) {
                    Image(systemName: "checkmark.seal.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.validation)
                    Text("READY")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(NerVyx.validation)
                        .tracking(0.5)
                }
            }
            Text("\(group.cellCount) TF")
                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
        }
    }
}

// MARK: - Signal row (rich per-signal cell)

struct SignalRowView: View {
    let signal: MobileSignal

    var body: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 3)
                .fill(NerVyx.actionColor(signal.action))
                .frame(width: 3, height: 40)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(signal.timeframe)
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(NerVyx.panel.opacity(0.6))
                        .clipShape(Capsule())
                    NerVyxBadge(text: signal.action.uppercased(), color: NerVyx.actionColor(signal.action), small: true)
                    Spacer()
                    Text(signal.executableConfidencePct)
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.confidenceColor(signal.executableConfidence))
                }
                HStack(spacing: 8) {
                    ConfidenceBar(value: signal.executableConfidence)
                        .frame(width: 78)
                    if signal.paperExplorationTier != "NONE" {
                        Text(signal.paperExplorationTier)
                            .font(.system(size: 9, design: .monospaced))
                            .foregroundStyle(NerVyx.signal)
                            .lineLimit(1)
                    }
                    Spacer()
                    if signal.actionable {
                        HStack(spacing: 3) {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(NerVyx.validation)
                            Text("actionable")
                                .font(.system(size: 10))
                                .foregroundStyle(NerVyx.validation)
                        }
                    } else {
                        Text(signal.shortFillStatus)
                            .font(.system(size: 10))
                            .foregroundStyle(NerVyx.textMuted)
                            .lineLimit(1)
                    }
                    Image(systemName: "chevron.right")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                }
            }
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
    }
}

// MARK: - Matrix cell chip (extra timeframe with no rich signal)

struct MatrixCellChip: View {
    let cell: SignalMatrixCell

    private var color: Color { NerVyx.actionColor(cell.a ?? "hold") }

    var body: some View {
        VStack(spacing: 3) {
            HStack(spacing: 4) {
                Circle().fill(color).frame(width: 5, height: 5)
                Text(cell.tf)
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(NerVyx.textSecondary)
            }
            ConfidenceBar(value: cell.c ?? 0).frame(width: 42)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity)
        .background(color.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(color.opacity(cell.act == true ? 0.6 : 0.22), lineWidth: 1)
        )
    }
}

// MARK: - Signal detail (full runtime truth)

struct SignalDetailView: View {
    let signal: MobileSignal

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                heroCard
                statusCard
                metaCard
            }
            .padding(16)
            .padding(.bottom, 24)
        }
        .nerVyxScreen()
        .navigationTitle(signal.shortSymbol)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var heroCard: some View {
        VStack(spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(signal.shortSymbol)
                        .font(.system(size: 26, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Text(signal.symbol + " · " + signal.timeframe)
                        .font(.system(size: 13))
                        .foregroundStyle(NerVyx.textMuted)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    NerVyxBadge(text: signal.action.uppercased(), color: NerVyx.actionColor(signal.action))
                    if let price = signal.last_price, price > 0 {
                        Text(String(format: "$%.4f", price))
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(NerVyx.textSecondary)
                    }
                }
            }
            HStack(alignment: .center, spacing: 18) {
                RingGauge(
                    value: signal.executableConfidence,
                    label: "EXECUTABLE",
                    centerText: signal.executableConfidencePct,
                    color: NerVyx.confidenceColor(signal.executableConfidence),
                    size: 92
                )
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        MicroLabel(text: "Selected action")
                        Spacer()
                        Text(signal.selectedConfidencePct)
                            .font(.system(size: 13, weight: .bold, design: .monospaced))
                            .foregroundStyle(NerVyx.textSecondary)
                    }
                    ConfidenceBar(value: signal.selectedConfidence)
                    Text(signal.confidenceDisplayLabel)
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.actionColor(signal.action))
    }

    private var statusCard: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Execution Status", accent: NerVyx.signal)
            DataRow(
                label: "Actionable",
                value: signal.actionable ? "YES" : "NO",
                valueColor: signal.actionable ? NerVyx.validation : NerVyx.warning
            )
            DataRow(label: "Risk State", value: signal.risk_state)
            DataRow(
                label: "Paper Exploration",
                value: signal.paperExplorationTier,
                valueColor: signal.paperExplorationTier == "NONE" ? NerVyx.textSecondary : NerVyx.signal
            )
            DataRow(
                label: "Exploration Blocker",
                value: nervyxPublicRuntimeText(signal.paperExplorationCurrentBlocker),
                valueColor: signal.paperExplorationCurrentBlocker == "PAPER_FILL_ALLOWED" ? NerVyx.validation : NerVyx.warning
            )
            if let fillAllowed = signal.paper_exploration_paper_fill_allowed {
                DataRow(
                    label: "Paper Fill",
                    value: fillAllowed ? "PAPER_FILL_ALLOWED" : "BLOCKED",
                    valueColor: fillAllowed ? NerVyx.validation : NerVyx.warning
                )
            }
            if let expectedNet = signal.expected_net_pnl_usd {
                DataRow(
                    label: "Expected Net USD",
                    value: String(format: "$%.2f", expectedNet),
                    valueColor: expectedNet > 0 ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
            }
            if let maxLoss = signal.expected_max_loss_usd {
                DataRow(label: "Max Loss USD", value: String(format: "$%.2f", maxLoss), valueColor: NerVyx.warning, mono: true)
            }
            DataRow(label: "Why Not A+", value: signal.whyNotAPlus)
            DataRow(label: "Why Not Live", value: signal.whyNotLiveReady, valueColor: NerVyx.sell)
            if let risk = signal.paper_exploration_risk_controller_decision ?? signal.risk_controller_decision {
                DataRow(label: "Risk Controller", value: nervyxPublicRuntimeText(risk))
            }
            if let orchestrator = signal.paper_exploration_orchestrator_decision {
                DataRow(label: "Orchestrator", value: nervyxPublicRuntimeText(orchestrator))
            }
            if let allocator = signal.paper_exploration_allocator_decision ?? signal.allocator_decision {
                DataRow(label: "Allocator", value: nervyxPublicRuntimeText(allocator))
            }
            if let trainer = signal.trainer_feedback_status {
                DataRow(label: "Trainer Feedback", value: nervyxPublicRuntimeText(trainer))
            }
            DataRow(label: "Fill Status", value: signal.shortFillStatus, valueColor: NerVyx.textSecondary)
            if let coverage = signal.data_coverage {
                DataRow(
                    label: "Data Coverage",
                    value: String(format: "%.1f%%", coverage),
                    valueColor: coverage > 80 ? NerVyx.validation : NerVyx.warning
                )
            }
            if let move = signal.expected_move_bps {
                DataRow(
                    label: "Expected Move",
                    value: String(format: "%+.2f%%", move / 100.0),
                    valueColor: NerVyx.textSecondary,
                    mono: true
                )
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    private var metaCard: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Signal Meta", accent: NerVyx.textMuted)
            DataRow(label: "Signal ID", value: String(signal.id.prefix(20)) + "…", mono: true)
            DataRow(label: "Published", value: signal.published_at, mono: true)
            if let model = signal.model_version, !model.isEmpty {
                DataRow(label: "Model", value: model, mono: true)
            }
            if let checkpoint = signal.checkpoint_id, !checkpoint.isEmpty {
                DataRow(label: "Checkpoint", value: checkpoint, mono: true)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.borderSubtle)
    }
}

// MARK: - Matrix-cell detail (honest partial — only fields the cell carries)

struct SignalCellDetailView: View {
    let cell: SignalMatrixCell
    let liveGateLabel: String

    private var displaySymbol: String {
        cell.s.hasSuffix("USDT") ? String(cell.s.dropLast(4)) : cell.s
    }
    private var actionColor: Color { NerVyx.actionColor(cell.a ?? "hold") }

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                VStack(spacing: 14) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(displaySymbol)
                                .font(.system(size: 26, weight: .bold))
                                .foregroundStyle(NerVyx.textPrimary)
                            Text(cell.s + " · " + cell.tf)
                                .font(.system(size: 13))
                                .foregroundStyle(NerVyx.textMuted)
                        }
                        Spacer()
                        NerVyxBadge(text: (cell.a ?? "hold").uppercased(), color: actionColor)
                    }
                    RingGauge(
                        value: cell.c ?? 0,
                        label: "EXECUTABLE",
                        centerText: cell.c.map { "\(Int(($0 * 100).rounded()))%" } ?? "—",
                        color: NerVyx.confidenceColor(cell.c ?? 0),
                        size: 92
                    )
                }
                .nerVyxGlassCard(accent: actionColor)

                VStack(spacing: 10) {
                    SectionHeader(title: "Grid Cell", accent: NerVyx.signal)
                    DataRow(
                        label: "Actionable",
                        value: cell.act == true ? "YES" : "NO",
                        valueColor: cell.act == true ? NerVyx.validation : NerVyx.warning
                    )
                    if let gate = cell.g, !gate.isEmpty {
                        DataRow(label: "Gate Reason", value: nervyxPublicRuntimeText(gate), valueColor: NerVyx.warning)
                    }
                    DataRow(label: "Live Gate", value: nervyxPublicRuntimeText(liveGateLabel), valueColor: NerVyx.sell)
                    Text("Matrix-cell view. Full runtime-truth detail publishes on the per-symbol signal feed.")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 2)
                }
                .nerVyxGlassCard(accent: NerVyx.inference)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
        .nerVyxScreen()
        .navigationTitle(displaySymbol)
        .navigationBarTitleDisplayMode(.inline)
    }
}
