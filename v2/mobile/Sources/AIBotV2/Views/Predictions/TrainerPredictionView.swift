import Foundation
import SwiftUI

struct TrainerPredictionView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PredictionsViewModel()
    @State private var backtestVM = BacktestReplayViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                content
            }
            .navigationTitle("Signal Matrix")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    actionableToggle
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                    }
                }
            }
            .refreshable {
                await vm.load(token: auth.currentToken(), baseURL: appState.baseURL)
                await backtestVM.load(token: auth.currentToken(), baseURL: appState.baseURL)
            }
        }
        .task {
            await vm.load(token: auth.currentToken(), baseURL: appState.baseURL)
            await backtestVM.load(token: auth.currentToken(), baseURL: appState.baseURL)
        }
        .onAppear {
            vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
            backtestVM.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
        }
        .onDisappear {
            vm.stopAutoRefresh()
            backtestVM.stopAutoRefresh()
        }
    }

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

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.signals.isEmpty {
            VStack(spacing: 16) {
                ProgressView().tint(NerVyx.primary)
                Text("Loading signal matrix…")
                    .font(.system(size: 14))
                    .foregroundStyle(NerVyx.textMuted)
            }
        } else if let err = vm.error, vm.signals.isEmpty {
            VStack(spacing: 16) {
                Image(systemName: "waveform.path.ecg.rectangle")
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
        } else if vm.signals.isEmpty {
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
            }.padding(32)
        } else {
            signalMatrixList
        }
    }

    private var signalMatrixList: some View {
        ScrollView {
            VStack(spacing: 12) {
                RuntimeTruthLiveCard(title: "Runtime Truth")
                featureAlertCard
                backtestCard
                metricsRow
                matrixList
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    @ViewBuilder
    private var featureAlertCard: some View {
        if let alert = backtestVM.featureAlert, alert.active {
            VStack(spacing: 8) {
                HStack {
                    SectionHeader(title: "Degraded Inputs · \(alert.severity.uppercased())", accent: alertAccent(alert.severity))
                    Spacer()
                }
                Text("Prediction still produced — operating on masked inputs")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(NerVyx.validation)
                    .frame(maxWidth: .infinity, alignment: .leading)
                DataRow(label: "Coverage", value: alert.data_coverage_pct.map { String(format: "%.1f%%", $0) } ?? "—", mono: true)
                DataRow(label: "Missing", value: "\(alert.missing_feature_count)", valueColor: NerVyx.warning, mono: true)
                DataRow(label: "Stale", value: "\(alert.stale_feature_count)", mono: true)
                if !alert.missing_by_category.isEmpty {
                    Text(alert.missing_by_category.map { "\($0.key.replacingOccurrences(of: "_", with: " ")): \($0.value)" }.joined(separator: " · "))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .nerVyxCard(accent: alertAccent(alert.severity).opacity(0.4))
        }
    }

    @ViewBuilder
    private var backtestCard: some View {
        if let bt = backtestVM.backtest, bt.available, let pb = bt.policy_backtest {
            VStack(spacing: 8) {
                HStack {
                    SectionHeader(title: "Backtest & Generalization", accent: NerVyx.inference)
                    Spacer()
                    if bt.continuous_replay_active == true {
                        NerVyxBadge(text: "REPLAY LIVE", color: NerVyx.validation, small: true)
                    }
                }
                DataRow(label: "Backtest Win", value: pb.win_rate.map { String(format: "%.1f%%", $0 * 100) } ?? "—", valueColor: NerVyx.validation, mono: true)
                DataRow(label: "Profit Factor", value: pb.profit_factor_proxy.map { String(format: "%.2f", $0) } ?? "—", mono: true)
                DataRow(label: "Expectancy", value: pb.expectancy_after_cost_bps.map { String(format: "%+.1f bps", $0) } ?? "—", mono: true)
                if let gen = bt.generalization {
                    DataRow(label: "Train Loss", value: gen.loss_after.map { String(format: "%.2f", $0) } ?? "—", mono: true)
                    DataRow(label: "Val Loss (OOS)", value: gen.validation_supervised_loss.map { String(format: "%.2f", $0) } ?? "—", mono: true)
                    DataRow(label: "Overfit Gap", value: gen.train_val_generalization_gap.map { String(format: "%.2f", $0) } ?? "—", valueColor: (gen.overfit_gap_warning == true) ? NerVyx.warning : NerVyx.validation, mono: true)
                }
                if let rf = bt.replay_feedback {
                    DataRow(label: "Replay→Trainer", value: "\(rf.existing_counterfactual_rows ?? 0) rows", mono: true)
                }
                Text("\(pb.evidence_class ?? "BACKTEST_ONLY") — not A+/live evidence")
                    .font(.system(size: 9))
                    .foregroundStyle(NerVyx.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .nerVyxCard(accent: NerVyx.inference.opacity(0.3))
        }
    }

    private func alertAccent(_ severity: String) -> Color {
        switch severity {
        case "critical": return NerVyx.sell
        case "warn": return NerVyx.warning
        case "info": return NerVyx.inference
        default: return NerVyx.validation
        }
    }

    private var metricsRow: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            NerVyxStatCard(
                label: "TOTAL",
                value: "\(vm.signals.count)",
                accent: NerVyx.primary
            )
            NerVyxStatCard(
                label: "ACTIONABLE",
                value: "\(vm.actionableCount)",
                valueColor: NerVyx.validation,
                accent: NerVyx.validation
            )
            NerVyxStatCard(
                label: "AVG EXEC",
                value: String(format: "%.0f%%", vm.avgConfidence * 100),
                valueColor: NerVyx.confidenceColor(vm.avgConfidence),
                sublabel: vm.streamLabel,
                accent: NerVyx.signal
            )
        }
    }

    private var matrixList: some View {
        VStack(spacing: 0) {
            HStack {
                SectionHeader(
                    title: "\(vm.displayed.count) signals\(vm.actionableOnly ? " · actionable" : "")",
                    accent: NerVyx.primary
                )
                Spacer()
                if let ts = vm.lastUpdated {
                    Text(String(ts.prefix(19)))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            ForEach(vm.displayed) { row in
                NavigationLink(destination: PredictionDetailView(row: row)) {
                    PredictionRowView(row: row)
                }
                .buttonStyle(.plain)
                if row.id != vm.displayed.last?.id {
                    NerVyxDivider().padding(.horizontal, 16)
                }
            }
        }
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }
}

// MARK: - Prediction Row

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
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(NerVyx.bg)
        .contentShape(Rectangle())
    }
}

// MARK: - Prediction Detail (Signal Explainability)

struct PredictionDetailView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    let row: SignalMatrixRow
    @State private var explanation: AIPredictionExplanation?

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 12) {
                    headerCard
                    aiReasoningCard
                    confidenceCard
                    executionCard
                    coverageCard
                    metaCard
                }
                .padding(16)
                .padding(.bottom, 32)
            }
        }
        .navigationTitle(row.displaySymbol)
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadReasoning() }
    }

    private struct ReasoningSection: Identifiable {
        var id: String { title }
        let title: String
        let text: String
    }

    private func reasoningSections(_ exp: AIPredictionExplanation) -> [ReasoningSection] {
        var out: [ReasoningSection] = []
        func add(_ title: String, _ text: String?) {
            if let t = text, !t.isEmpty { out.append(ReasoningSection(title: title, text: t)) }
        }
        add("What the model sees", exp.summary)
        add("Signal strength", exp.signal_strength)
        add("Confidence", exp.confidence_narrative)
        add("Data quality", exp.data_quality_narrative)
        add("Market integrity", exp.market_integrity_narrative)
        add("Technical drivers", exp.technical_drivers)
        add("Price target", exp.price_target_narrative)
        add("Risk gate", exp.risk_gate_narrative)
        add("Pipeline state", exp.pipeline_state_narrative)
        return out
    }

    @ViewBuilder
    private var aiReasoningCard: some View {
        if let exp = explanation {
            VStack(spacing: 10) {
                SectionHeader(title: "AI Reasoning", accent: NerVyx.inference)
                ForEach(reasoningSections(exp)) { section in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(section.title.uppercased())
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(NerVyx.textMuted)
                        Text(section.text)
                            .font(.system(size: 12))
                            .foregroundStyle(NerVyx.textSecondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .nerVyxCard(accent: NerVyx.inference.opacity(0.3))
        }
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
        } catch {
            // reasoning is best-effort; the structured detail cards remain.
        }
    }

    private var headerCard: some View {
        VStack(spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.displaySymbol)
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    HStack(spacing: 6) {
                        Text(row.symbol ?? "—")
                            .font(.system(size: 13))
                            .foregroundStyle(NerVyx.textMuted)
                        if let tf = row.timeframe {
                            Text("· \(tf)")
                                .font(.system(size: 13))
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
        }
        .nerVyxElevatedCard(accent: NerVyx.actionColor(row.action ?? "hold"))
    }

    private var confidenceCard: some View {
        VStack(spacing: 10) {
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
                DataRow(
                    label: "Expected Move",
                    value: String(format: "%+.2f%%", move / 100.0),
                    mono: true
                )
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.primary)
    }

    private var executionCard: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Execution Status", accent: NerVyx.signal)
            DataRow(
                label: "Actionable",
                value: row.actionable == true ? "YES" : "NO",
                valueColor: row.actionable == true ? NerVyx.validation : NerVyx.warning
            )
            if let risk = row.risk_state {
                DataRow(
                    label: "Risk State",
                    value: nervyxPublicRuntimeText(risk),
                    valueColor: NerVyx.statusColor(risk)
                )
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
                DataRow(
                    label: "Fill Status",
                    value: nervyxPublicRuntimeText(fill).uppercased(),
                    valueColor: NerVyx.textSecondary
                )
            }
            if let orch = row.orchestrator_state {
                DataRow(label: "Orchestrator", value: nervyxPublicRuntimeText(orch))
            }
            if let gate = row.live_gate {
                DataRow(label: "Live Gate", value: nervyxPublicRuntimeText(gate), valueColor: NerVyx.sell)
            }
        }
        .nerVyxCard()
    }

    private var coverageCard: some View {
        VStack(spacing: 10) {
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
        }
        .nerVyxCard(accent: NerVyx.inference.opacity(0.3))
    }

    private var metaCard: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Signal Meta", accent: NerVyx.textMuted)
            if let sid = row.signal_id {
                DataRow(label: "Signal ID", value: String(sid.prefix(24)), mono: true)
            }
            if let gen = row.generated_at {
                DataRow(label: "Generated", value: String(gen.prefix(19)), mono: true)
            }
        }
        .nerVyxCard(accent: NerVyx.borderSubtle)
    }
}
