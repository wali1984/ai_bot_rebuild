import SwiftUI

/// Dedicated realtime Backtest & Replay screen.
/// Shows the trainer's in-cycle backtest, the out-of-sample generalization signal
/// (validation loss + overfit gap), the continuous replay -> trainer feedback, and
/// the missing-feature alert. Backtest is explicitly NOT A+/live evidence.
struct BacktestReplayScreen: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = BacktestReplayViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                content
            }
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
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.backtest == nil {
            VStack(spacing: 16) {
                ProgressView().tint(NerVyx.primary)
                Text("Loading backtest & replay truth…")
                    .font(.system(size: 14))
                    .foregroundStyle(NerVyx.textMuted)
            }
        } else if let err = vm.error, vm.backtest == nil {
            VStack(spacing: 16) {
                Image(systemName: "chart.xyaxis.line")
                    .font(.system(size: 36))
                    .foregroundStyle(NerVyx.warning)
                Text(err)
                    .font(.system(size: 14))
                    .foregroundStyle(NerVyx.textSecondary)
                    .multilineTextAlignment(.center)
                Button("Retry") {
                    Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                }
                .foregroundStyle(NerVyx.signal)
            }.padding(32)
        } else {
            ScrollView {
                VStack(spacing: 12) {
                    performanceCard
                    generalizationCard
                    replayFeedbackCard
                    alertCard
                }
                .padding(16)
                .padding(.bottom, 32)
            }
        }
    }

    @ViewBuilder
    private var performanceCard: some View {
        if let bt = vm.backtest, let pb = bt.policy_backtest {
            VStack(spacing: 10) {
                HStack {
                    SectionHeader(title: "Backtest Performance", accent: NerVyx.inference)
                    Spacer()
                    if bt.continuous_replay_active == true {
                        NerVyxBadge(text: "REPLAY LIVE", color: NerVyx.validation, small: true)
                    }
                }
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                    NerVyxStatCard(label: "WIN", value: pb.win_rate.map { String(format: "%.1f%%", $0 * 100) } ?? "—", valueColor: NerVyx.validation, accent: NerVyx.validation)
                    NerVyxStatCard(label: "PF", value: pb.profit_factor_proxy.map { String(format: "%.1f", $0) } ?? "—", accent: NerVyx.primary)
                    NerVyxStatCard(label: "EXP bps", value: pb.expectancy_after_cost_bps.map { String(format: "%+.1f", $0) } ?? "—", accent: NerVyx.signal)
                }
                DataRow(label: "Rows Evaluated", value: pb.rows_evaluated.map(String.init) ?? "—", mono: true)
                DataRow(label: "Status", value: pb.status ?? "—", mono: true)
                DataRow(label: "Trainer Mode", value: bt.effective_trainer_mode ?? "—", mono: true)
                Text("\(pb.evidence_class ?? "BACKTEST_ONLY") — not A+/live evidence")
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .nerVyxElevatedCard(accent: NerVyx.inference)
        } else {
            VStack(spacing: 8) {
                SectionHeader(title: "Backtest Performance", accent: NerVyx.inference)
                Text("No backtest cycle reported yet.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .nerVyxCard()
        }
    }

    @ViewBuilder
    private var generalizationCard: some View {
        if let gen = vm.backtest?.generalization {
            VStack(spacing: 10) {
                SectionHeader(title: "Out-of-Sample Generalization", accent: NerVyx.primary)
                DataRow(label: "Train Loss", value: gen.loss_after.map { String(format: "%.3f", $0) } ?? "—", mono: true)
                DataRow(label: "Validation Loss (OOS)", value: gen.validation_supervised_loss.map { String(format: "%.3f", $0) } ?? "—", mono: true)
                DataRow(label: "Rows Held Out", value: gen.validation_rows_evaluated.map(String.init) ?? "—", mono: true)
                DataRow(
                    label: "Overfit Gap",
                    value: gen.train_val_generalization_gap.map { String(format: "%.3f", $0) } ?? "—",
                    valueColor: (gen.overfit_gap_warning == true) ? NerVyx.warning : NerVyx.validation,
                    mono: true
                )
                Text(gen.overfit_gap_warning == true
                     ? "Overfit gap elevated — edge may not fully generalize this cycle."
                     : "Edge is generalizing to held-out data.")
                    .font(.system(size: 11))
                    .foregroundStyle((gen.overfit_gap_warning == true) ? NerVyx.warning : NerVyx.validation)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .nerVyxCard(accent: NerVyx.primary.opacity(0.3))
        }
    }

    @ViewBuilder
    private var replayFeedbackCard: some View {
        if let bt = vm.backtest {
            VStack(spacing: 10) {
                SectionHeader(title: "Replay → Trainer Feedback", accent: NerVyx.signal)
                DataRow(label: "Continuous Replay", value: bt.continuous_replay_active == true ? "ACTIVE" : "—", valueColor: bt.continuous_replay_active == true ? NerVyx.validation : NerVyx.textMuted)
                DataRow(label: "Replay Examples Built", value: bt.replay_examples_built.map(String.init) ?? "—", mono: true)
                if let rf = bt.replay_feedback {
                    DataRow(label: "Counterfactual Rows", value: rf.existing_counterfactual_rows.map(String.init) ?? "—", mono: true)
                    DataRow(label: "Newly Matured", value: rf.new_matured_rows.map(String.init) ?? "—", mono: true)
                    DataRow(label: "Pending Labels", value: rf.pending_rows.map(String.init) ?? "—", mono: true)
                    DataRow(label: "Trainer Consumes", value: rf.trainer_loader_consumes == true ? "YES" : "—", valueColor: rf.trainer_loader_consumes == true ? NerVyx.validation : NerVyx.textMuted)
                }
            }
            .nerVyxCard(accent: NerVyx.signal.opacity(0.3))
        }
    }

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
            .nerVyxCard(accent: severityColor(alert.severity).opacity(0.4))
        }
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
