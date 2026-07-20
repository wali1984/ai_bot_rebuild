import SwiftUI

/// Dedicated realtime Backtest & Replay screen (NERVYX visual language v2).
/// Shows the trainer's in-cycle backtest (win-rate ring, profit-factor and
/// after-cost expectancy bars), the out-of-sample generalization signal
/// (train-vs-validation loss bars + overfit-gap badge), the continuous
/// replay -> trainer feedback, and the missing-feature alert.
/// Backtest is explicitly NOT A+/live evidence — every card says so.
struct BacktestReplayScreen: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = BacktestReplayViewModel()

    var body: some View {
        NavigationStack {
            content
                .nerVyxScreen()
                .navigationTitle("Backtest & Replay")
                .navigationBarTitleDisplayMode(.large)
                .toolbar {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        Button {
                            Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                        } label: {
                            Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                        }
                    }
                }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Content states

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.backtest == nil {
            ScrollView {
                loadingReplica
                    .padding(16)
            }
        } else if let err = vm.error, vm.backtest == nil {
            ErrorStateView(message: err) {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }
        } else {
            ScrollView {
                VStack(spacing: 14) {
                    truthBar
                    performanceCard
                    generalizationCard
                    replayFeedbackCard
                    alertCard
                }
                .padding(16)
                .padding(.bottom, 32)
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
    }

    /// Redacted replica of the real card layout while the first payload loads.
    private var loadingReplica: some View {
        VStack(spacing: 14) {
            ForEach(0..<3, id: \.self) { _ in
                VStack(alignment: .leading, spacing: 12) {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(NerVyx.panel)
                        .frame(width: 168, height: 12)
                    HStack(spacing: 16) {
                        Circle()
                            .fill(NerVyx.panel)
                            .frame(width: 88, height: 88)
                        VStack(spacing: 10) {
                            Capsule().fill(NerVyx.panel).frame(height: 9)
                            Capsule().fill(NerVyx.panel).frame(height: 9)
                            Capsule().fill(NerVyx.panel).frame(height: 9)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard()
            }
        }
        .redacted(reason: .placeholder)
    }

    // MARK: - Freshness + safety truth bar

    private var truthBar: some View {
        HStack(spacing: 8) {
            freshnessChip
            Spacer()
            NerVyxBadge(text: NervyxBrand.liveBlockedLabel.uppercased(), color: NerVyx.signal, small: true)
        }
        .padding(.horizontal, 2)
    }

    private var freshnessChip: StalenessChip {
        switch vm.freshnessMode {
        case .offline:
            return .offline()
        case .stale:
            return StalenessChip(mode: .stale, ageText: vm.ageSeconds.map { NerVyxFormat.age($0) })
        case .realtime:
            return StalenessChip(mode: .realtime)
        case .poll:
            return StalenessChip(mode: .poll)
        }
    }

    // MARK: - Backtest performance (win-rate ring + PF/expectancy bars)

    @ViewBuilder
    private var performanceCard: some View {
        VStack(spacing: 12) {
            HStack {
                SectionHeader(title: "Backtest Performance", accent: NerVyx.inference)
                Spacer()
                if vm.backtest?.continuous_replay_active == true {
                    NerVyxBadge(text: "REPLAY LIVE", color: NerVyx.validation, small: true)
                }
            }
            if let bt = vm.backtest, bt.available, let pb = bt.policy_backtest {
                HStack(alignment: .center, spacing: 18) {
                    RingGauge(
                        value: pb.win_rate ?? 0,
                        label: "WIN RATE",
                        centerText: NerVyxFormat.percent(pb.win_rate),
                        color: winRateColor(pb.win_rate),
                        size: 92
                    )
                    VStack(alignment: .leading, spacing: 12) {
                        HBarRow(
                            label: "PROFIT F",
                            value: pb.profit_factor_proxy ?? 0,
                            maxAbsValue: max(pb.profit_factor_proxy ?? 0, 2),
                            valueText: NerVyxFormat.number(pb.profit_factor_proxy),
                            color: profitFactorColor(pb.profit_factor_proxy),
                            labelWidth: 62
                        )
                        HBarRow(
                            label: "EXP bps",
                            value: pb.expectancy_after_cost_bps ?? 0,
                            maxAbsValue: max(abs(pb.expectancy_after_cost_bps ?? 0), 10),
                            valueText: pb.expectancy_after_cost_bps.map { String(format: "%+.1f", $0) } ?? "—",
                            signed: true,
                            labelWidth: 62
                        )
                        HStack(spacing: 8) {
                            StatChip(label: "ROWS", value: NerVyxFormat.count(pb.rows_evaluated), color: NerVyx.textSecondary, accent: NerVyx.inference)
                            StatChip(label: "STATUS", value: pb.status ?? "—", color: NerVyx.statusColor(pb.status ?? ""), accent: NerVyx.inference)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                DataRow(label: "Trainer Mode", value: vm.backtest?.effective_trainer_mode ?? "—", mono: true)
                disclaimer(pb.evidence_class)
            } else {
                Text("No backtest cycle reported yet.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                disclaimer(nil)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: - Out-of-sample generalization (train vs val loss bars)

    @ViewBuilder
    private var generalizationCard: some View {
        if let gen = vm.backtest?.generalization {
            let train = gen.loss_after
            let val = gen.validation_supervised_loss
            let overfit = gen.overfit_gap_warning == true
            let lossScale = max(train ?? 0, val ?? 0, 0.0001)
            VStack(spacing: 12) {
                HStack {
                    SectionHeader(title: "Out-of-Sample Generalization", accent: NerVyx.primary)
                    Spacer()
                    if let gap = gen.train_val_generalization_gap {
                        NerVyxBadge(
                            text: overfit
                                ? "OVERFIT GAP \(String(format: "%+.3f", gap))"
                                : "GAP \(String(format: "%+.3f", gap))",
                            color: overfit ? NerVyx.warning : NerVyx.validation,
                            small: true
                        )
                    }
                }
                VStack(spacing: 10) {
                    HBarRow(
                        label: "TRAIN",
                        value: train ?? 0,
                        maxAbsValue: lossScale,
                        valueText: NerVyxFormat.number(train, decimals: 3),
                        color: NerVyx.inference,
                        labelWidth: 70
                    )
                    HBarRow(
                        label: "VAL·OOS",
                        value: val ?? 0,
                        maxAbsValue: lossScale,
                        valueText: NerVyxFormat.number(val, decimals: 3),
                        color: overfit ? NerVyx.warning : NerVyx.validation,
                        labelWidth: 70
                    )
                }
                DataRow(label: "Rows Held Out", value: NerVyxFormat.count(gen.validation_rows_evaluated), mono: true)
                Text(overfit
                     ? "Overfit gap elevated — edge may not fully generalize this cycle."
                     : "Edge is generalizing to held-out data.")
                    .font(.system(size: 11))
                    .foregroundStyle(overfit ? NerVyx.warning : NerVyx.validation)
                    .frame(maxWidth: .infinity, alignment: .leading)
                disclaimer(nil)
            }
            .nerVyxGlassCard(accent: NerVyx.primary)
        }
    }

    // MARK: - Replay -> trainer feedback

    @ViewBuilder
    private var replayFeedbackCard: some View {
        if let bt = vm.backtest {
            VStack(spacing: 12) {
                HStack {
                    SectionHeader(title: "Replay → Trainer Feedback", accent: NerVyx.signal)
                    Spacer()
                    NerVyxBadge(
                        text: bt.continuous_replay_active == true ? "ACTIVE" : "IDLE",
                        color: bt.continuous_replay_active == true ? NerVyx.validation : NerVyx.textMuted,
                        small: true
                    )
                }
                if let rf = bt.replay_feedback {
                    let entries: [MiniBarChart.Entry] = [
                        rf.existing_counterfactual_rows.map {
                            MiniBarChart.Entry(label: "CF ROWS", value: Double($0), color: NerVyx.signal)
                        },
                        rf.new_matured_rows.map {
                            MiniBarChart.Entry(label: "MATURED", value: Double($0), color: NerVyx.validation)
                        },
                        rf.pending_rows.map {
                            MiniBarChart.Entry(label: "PENDING", value: Double($0), color: NerVyx.warning)
                        },
                    ].compactMap { $0 }
                    if !entries.isEmpty {
                        MiniBarChart(entries: entries, height: 64)
                    }
                    DataRow(
                        label: "Trainer Consumes",
                        value: rf.trainer_loader_consumes == true ? "YES" : "—",
                        valueColor: rf.trainer_loader_consumes == true ? NerVyx.validation : NerVyx.textMuted,
                        mono: true
                    )
                }
                DataRow(label: "Replay Examples Built", value: NerVyxFormat.count(bt.replay_examples_built), mono: true)
                disclaimer(nil)
            }
            .nerVyxGlassCard(accent: NerVyx.signal)
        }
    }

    // MARK: - Degraded inputs alert

    @ViewBuilder
    private var alertCard: some View {
        if let alert = vm.featureAlert, alert.active {
            VStack(spacing: 10) {
                SectionHeader(title: "Degraded Inputs · \(alert.severity.uppercased())", accent: severityColor(alert.severity))
                Text("Prediction still produced — operating on masked inputs")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(NerVyx.validation)
                    .frame(maxWidth: .infinity, alignment: .leading)
                DataRow(label: "Coverage", value: alert.data_coverage_pct.map { String(format: "%.1f%%", $0) } ?? "—", mono: true)
                DataRow(label: "Missing Features", value: "\(alert.missing_feature_count)", valueColor: NerVyx.warning, mono: true)
                DataRow(label: "Stale Features", value: "\(alert.stale_feature_count)", mono: true)
                if !alert.missing_by_category.isEmpty {
                    Text(alert.missing_by_category.map { "\($0.key.replacingOccurrences(of: "_", with: " ")): \($0.value)" }.joined(separator: " · "))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .nerVyxGlassCard(accent: severityColor(alert.severity))
        }
    }

    // MARK: - Helpers

    /// Honesty banner required on every card: this data is trainer backtest
    /// evidence only — never A+/live evidence, and live stays operator-gated.
    private func disclaimer(_ evidenceClass: String?) -> some View {
        HStack(spacing: 6) {
            Image(systemName: "exclamationmark.shield")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(NerVyx.warning)
            Text("\(evidenceClass ?? "BACKTEST_ONLY") — not A+/live evidence")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(NerVyx.warning)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func winRateColor(_ winRate: Double?) -> Color {
        guard let winRate else { return NerVyx.neutral }
        if winRate >= 0.55 { return NerVyx.validation }
        if winRate >= 0.45 { return NerVyx.warning }
        return NerVyx.sell
    }

    private func profitFactorColor(_ pf: Double?) -> Color {
        guard let pf else { return NerVyx.neutral }
        return pf >= 1 ? NerVyx.buy : NerVyx.sell
    }

    private func severityColor(_ severity: String) -> Color {
        switch severity {
        case "critical": return NerVyx.sell
        case "warn": return NerVyx.warning
        case "info": return NerVyx.inference
        default: return NerVyx.validation
        }
    }
}
