import SwiftUI

struct TrainerPredictionView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PredictionsViewModel()

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
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
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
                metricsRow
                matrixList
            }
            .padding(16)
            .padding(.bottom, 32)
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
                label: "AVG CONF",
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
                    ConfidenceBar(value: row.confidence ?? 0)
                        .frame(width: 70)
                    Text(row.confidencePct)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.confidenceColor(row.confidence ?? 0))
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
    let row: SignalMatrixRow

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 12) {
                    headerCard
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
            SectionHeader(title: "Model Confidence", accent: NerVyx.primary)
            VStack(spacing: 6) {
                HStack {
                    Text("Confidence")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    Text(row.confidencePct)
                        .font(.system(size: 20, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.confidenceColor(row.confidence ?? 0))
                }
                ConfidenceBar(value: row.confidence ?? 0)
                    .frame(height: 8)
            }
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
