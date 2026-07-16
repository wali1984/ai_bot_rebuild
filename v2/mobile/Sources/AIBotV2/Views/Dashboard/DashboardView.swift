import SwiftUI

struct DashboardView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DashboardViewModel()
    @State private var healthVM = SelfHealingViewModel()
    @State private var pnlSeries = RollingSeries(capacity: 80)
    @State private var gpuSeries = RollingSeries(capacity: 80)

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 16) {
                        if let banner = healthVM.banner {
                            SelfHealingBannerView(banner: banner)
                        }
                        streamBar
                        RuntimeTruthLiveCard(title: "Runtime Truth")
                        if vm.isLoading && vm.dashboard == nil {
                            loadingContent
                        } else if let err = vm.error, vm.dashboard == nil {
                            nerVyxError(err)
                        } else {
                            mainContent
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
                }
            }
            .navigationTitle("Mission Control")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } } label: {
                        Image(systemName: "arrow.clockwise")
                            .foregroundStyle(NerVyx.signal)
                    }
                    .disabled(vm.isLoading)
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .onAppear {
            vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
            healthVM.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
        }
        .onDisappear {
            vm.stopAutoRefresh()
            healthVM.stop()
        }
        .onChange(of: vm.dashboard?.paper.total_pnl) { _, newValue in
            if let newValue { pnlSeries.append(newValue) }
        }
        .onChange(of: vm.dashboard?.gpu.utilization_pct) { _, newValue in
            if let newValue { gpuSeries.append(newValue) }
        }
    }

    // MARK: - Stream bar

    private var streamBar: some View {
        HStack(spacing: 8) {
            LivePulse(color: vm.dashboard != nil ? NerVyx.validation : NerVyx.textMuted)
            Text(vm.streamSummary)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
            Spacer()
            NerVyxBadge(text: NervyxBrand.liveBlockedLabel.uppercased(), color: NerVyx.signal, small: true)
        }
        .padding(.horizontal, 4)
        .padding(.top, 4)
    }

    // MARK: - Loading / Error

    private var loadingContent: some View {
        VStack(spacing: 16) {
            ForEach(0..<4, id: \.self) { _ in
                RoundedRectangle(cornerRadius: 10)
                    .fill(NerVyx.panel)
                    .frame(height: 80)
            }
        }
        .redacted(reason: .placeholder)
    }

    private func nerVyxError(_ msg: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36))
                .foregroundStyle(NerVyx.warning)
            Text(msg)
                .font(.system(size: 14))
                .foregroundStyle(NerVyx.textSecondary)
                .multilineTextAlignment(.center)
            Button("Retry") {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }
            .foregroundStyle(NerVyx.signal)
        }
        .padding(24)
        .nerVyxCard(accent: NerVyx.warning)
    }

    // MARK: - Main content

    @ViewBuilder
    private var mainContent: some View {
        if let d = vm.dashboard {
            // Gate status banner
            gateStatusBanner(d.live_gate)
            // Key stats row
            signalTrainerStatsRow(d)
            // PnL summary
            pnlSection(d.paper)
            // Capital productivity quick stats
            capitalQuickStats(d.paper)
            // Paper loop
            paperLoopSection(d.paper)
            // Trainer
            trainerSection(d.trainer)
            // GPU
            gpuSection(d.gpu)
            // Alerts preview
            if !d.alerts_preview.isEmpty {
                alertsPreview(d.alerts_preview)
            }
        }
        if let h = vm.health {
            healthFooter(h)
        }
    }

    // MARK: - Sections

    private func gateStatusBanner(_ gate: LiveGateState) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "lock.shield.fill")
                .font(.system(size: 18))
                .foregroundStyle(NerVyx.sell)
            VStack(alignment: .leading, spacing: 2) {
                Text(gate.publicLabel)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(NerVyx.sell)
                Text("Exchange route: \(gate.exchangeRouteLabel)")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
            }
            Spacer()
            Text(gate.publicGate)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(NerVyx.sell)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(NerVyx.sell.opacity(0.15))
                .clipShape(Capsule())
                .overlay(Capsule().stroke(NerVyx.sell.opacity(0.3), lineWidth: 1))
        }
        .padding(14)
        .background(NerVyx.sell.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.sell.opacity(0.25), lineWidth: 1))
    }

    private func signalTrainerStatsRow(_ d: MobileDashboard) -> some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            NerVyxStatCard(
                label: "SIGNALS",
                value: "\(d.active_signal_count ?? 0)",
                valueColor: NerVyx.signal,
                sublabel: "active now",
                accent: NerVyx.signal
            )
            NerVyxStatCard(
                label: "TRAINER",
                value: d.trainer.shortState,
                valueColor: NerVyx.statusColor(d.trainer.state),
                sublabel: d.trainer.cuda_active ? "CUDA on" : "CPU mode",
                accent: NerVyx.primary
            )
            NerVyxStatCard(
                label: "GPU UTIL",
                value: "\(Int(d.gpu.utilization_pct))%",
                valueColor: d.gpu.utilization_pct > 80 ? NerVyx.warning : NerVyx.validation,
                sublabel: d.gpu.displayName,
                accent: NerVyx.inference
            )
        }
    }

    private func pnlSection(_ paper: PaperState) -> some View {
        let pnlColor = NerVyx.pnlColor(paper.total_pnl)
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionHeader(title: "Portfolio PnL", accent: pnlColor, trailing: nil)
                Spacer()
                HStack(spacing: 5) {
                    LivePulse(color: pnlColor)
                    Text("LIVE")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(pnlColor)
                        .tracking(1.0)
                }
            }
            Text(String(format: "%@$%.2f", paper.total_pnl >= 0 ? "+" : "", paper.total_pnl))
                .font(.system(size: 38, weight: .heavy, design: .monospaced))
                .foregroundStyle(pnlColor)
                .contentTransition(.numericText())
            HStack(spacing: 8) {
                NerVyxBadge(
                    text: String(format: "REALIZED %@$%.2f", paper.realized_pnl_usd >= 0 ? "+" : "", paper.realized_pnl_usd),
                    color: NerVyx.pnlColor(paper.realized_pnl_usd),
                    small: true
                )
                NerVyxBadge(
                    text: String(format: "UNREALIZED %@$%.2f", paper.unrealized_pnl_usd >= 0 ? "+" : "", paper.unrealized_pnl_usd),
                    color: NerVyx.pnlColor(paper.unrealized_pnl_usd),
                    small: true
                )
                Spacer()
            }
            if pnlSeries.values.count > 1 {
                Sparkline(values: pnlSeries.values, color: pnlColor)
                    .frame(height: 56)
            }
        }
        .padding(16)
        .background(
            LinearGradient(
                colors: [NerVyx.panelElevated, NerVyx.panel],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(pnlColor.opacity(0.35), lineWidth: 1))
    }

    private func capitalQuickStats(_ paper: PaperState) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Capital Snapshot", accent: NerVyx.inference, trailing: "\(paper.closed_trades) closed")
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                NerVyxStatCard(
                    label: "OPEN",
                    value: "\(paper.open_positions)",
                    accent: NerVyx.paper
                )
                NerVyxStatCard(
                    label: "CLOSED",
                    value: "\(paper.closed_trades)",
                    accent: NerVyx.borderStrong
                )
                NerVyxStatCard(
                    label: "ACCEPT %",
                    value: String(format: "%.0f%%", paper.acceptanceRate),
                    valueColor: paper.acceptanceRate > 50 ? NerVyx.validation : NerVyx.warning,
                    accent: NerVyx.signal
                )
            }
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Realized")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", paper.realized_pnl_usd))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(paper.realized_pnl_usd))
                }
                Spacer()
                VStack(alignment: .center, spacing: 3) {
                    Text("Unrealized")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", paper.unrealized_pnl_usd))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(paper.unrealized_pnl_usd))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 3) {
                    Text("Classification")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(nervyxPublicRuntimeText(paper.classification).uppercased())
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(NerVyx.paper)
                        .lineLimit(1)
                }
            }
        }
        .nerVyxCard(accent: NerVyx.inference.opacity(0.25))
    }

    private func paperLoopSection(_ paper: PaperState) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Runtime Loop", accent: NerVyx.paper, trailing: "\(paper.open_positions) open")
                .padding(.bottom, 2)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                NerVyxStatCard(
                    label: "OPEN",
                    value: "\(paper.open_positions)",
                    accent: NerVyx.paper
                )
                NerVyxStatCard(
                    label: "CLOSED",
                    value: "\(paper.closed_trades)",
                    accent: NerVyx.borderStrong
                )
            }
            HStack(spacing: 16) {
                MiniBarChart(entries: [
                    .init(label: "SEEN", value: Double(paper.signals_seen), color: NerVyx.paper),
                    .init(label: "ACCEPTED", value: Double(paper.intents_accepted), color: NerVyx.buy),
                    .init(label: "BLOCKED", value: Double(paper.intents_blocked), color: NerVyx.sell),
                ])
                .frame(maxWidth: .infinity)
                RingGauge(
                    value: paper.acceptanceRate / 100,
                    label: "ACCEPTANCE",
                    centerText: String(format: "%.0f%%", paper.acceptanceRate),
                    color: paper.acceptanceRate > 50 ? NerVyx.buy : NerVyx.warning,
                    size: 74
                )
            }
        }
        .nerVyxCard(accent: NerVyx.paper.opacity(0.3))
    }

    private func trainerSection(_ trainer: TrainerState) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Trainer · NERVYX CORE", accent: NerVyx.primary)
            DataRow(
                label: "State",
                value: trainer.shortState.uppercased(),
                valueColor: NerVyx.statusColor(trainer.state)
            )
            DataRow(
                label: "Device",
                value: trainer.device ?? (trainer.cuda_active ? "cuda:0" : "cpu"),
                valueColor: trainer.cuda_active ? NerVyx.signal : NerVyx.textMuted,
                mono: true
            )
            DataRow(
                label: "GPU",
                value: trainer.gpu_name ?? (trainer.cuda_active ? "Active" : "—"),
                valueColor: trainer.cuda_active ? NerVyx.validation : NerVyx.textMuted
            )
            DataRow(
                label: "Steps total",
                value: "\(trainer.training_steps_total.formatted())",
                mono: true
            )
            DataRow(
                label: "Steps / hr",
                value: "\(trainer.training_steps_last_hour.formatted())",
                mono: true
            )
            DataRow(
                label: "Model input",
                value: trainer.input_dim != nil ? "\(trainer.input_dim!.formatted()) dims · \(trainer.feature_count.map { "\($0) feats" } ?? "—")" : "—",
                mono: true
            )
            DataRow(
                label: "Temporal",
                value: trainer.temporalLabel.uppercased(),
                valueColor: (trainer.temporal_encoder_enabled == true) ? NerVyx.validation : NerVyx.textMuted
            )
            if let mode = trainer.effective_trainer_mode, !mode.isEmpty {
                DataRow(
                    label: "Mode",
                    value: mode.replacingOccurrences(of: "_", with: " "),
                    valueColor: NerVyx.primary
                )
            }
            if trainer.online_learning_status != nil || trainer.weights_updating != nil {
                DataRow(
                    label: "Online learning",
                    value: trainer.learningLabel,
                    valueColor: (trainer.weights_updating == true || trainer.online_learning_status?.uppercased() == "WEIGHTS_UPDATING") ? NerVyx.validation : NerVyx.warning
                )
            }
            if let win = trainer.backtest_win_rate {
                DataRow(
                    label: "Model win rate",
                    value: String(format: "%.1f%%", win * 100) + (trainer.backtest_expectancy_bps.map { String(format: " · %+.1f bps", $0) } ?? ""),
                    valueColor: win >= 0.55 ? NerVyx.validation : (win >= 0.5 ? NerVyx.warning : NerVyx.sell),
                    mono: true
                )
            }
            if let tput = trainer.throughput_predictions_per_second {
                DataRow(
                    label: "Throughput",
                    value: String(format: "%.1f pred/s", tput) + (trainer.vram_used_mb.map { String(format: " · %.1f GB VRAM", $0 / 1024) } ?? ""),
                    mono: true
                )
            }
            if let gap = trainer.generalization_gap {
                DataRow(
                    label: "Overfit gap",
                    value: String(format: "%.2f", gap) + (trainer.validation_loss_delta.map { String(format: " · Δval %+.3f", $0) } ?? ""),
                    valueColor: gap > 5 ? NerVyx.warning : NerVyx.validation,
                    mono: true
                )
            }
            DataRow(
                label: "Challenger",
                value: trainer.champion_challenger_status?.challengerLabel ?? "AWAITING EVIDENCE",
                valueColor: {
                    guard let cc = trainer.champion_challenger_status else { return NerVyx.textMuted }
                    if !cc.hasEvidence { return NerVyx.textMuted }
                    return cc.isPaperReady ? NerVyx.validation : NerVyx.warning
                }()
            )
            DataRow(
                label: "Promotion",
                value: trainer.champion_challenger_status?.promotionLabel ?? "AWAITING EVIDENCE",
                valueColor: {
                    guard let cc = trainer.champion_challenger_status else { return NerVyx.textMuted }
                    if cc.promotion_allowed == true { return NerVyx.validation }
                    if !cc.hasEvidence { return NerVyx.textMuted }
                    // Paper-ready but live/A-grade is operator-gated by design: informational, not an error.
                    return cc.isPaperReady ? NerVyx.primary : NerVyx.warning
                }()
            )
            NerVyxDivider()
            HStack {
                Text("Checkpoint")
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textMuted)
                Spacer()
                Text(trainer.shortCheckpoint)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(NerVyx.primary)
                    .lineLimit(1)
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.primary)
    }

    private func gpuSection(_ gpu: GPUState) -> some View {
        VStack(spacing: 12) {
            SectionHeader(title: "GPU · \(gpu.displayName)", accent: NerVyx.inference)
            HStack(spacing: 18) {
                RingGauge(
                    value: gpu.utilization_pct / 100,
                    label: "UTILIZATION",
                    centerText: "\(Int(gpu.utilization_pct))%",
                    color: gpu.utilization_pct > 80 ? NerVyx.warning : NerVyx.inference
                )
                RingGauge(
                    value: gpu.vramPercent / 100,
                    label: "VRAM",
                    centerText: String(format: "%.1fG", gpu.vramUsedGB),
                    color: gpu.vramPercent > 85 ? NerVyx.warning : NerVyx.signal
                )
                VStack(alignment: .leading, spacing: 6) {
                    Text("UTIL TREND")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    if gpuSeries.values.count > 1 {
                        Sparkline(values: gpuSeries.values, color: NerVyx.inference)
                            .frame(height: 52)
                    } else {
                        Text("collecting…")
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                            .frame(maxWidth: .infinity, minHeight: 52)
                    }
                    Text(String(format: "%.1f / %.1f GB VRAM", gpu.vramUsedGB, gpu.vramTotalGB))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .nerVyxCard(accent: NerVyx.inference.opacity(0.3))
    }

    private func alertsPreview(_ alerts: [MobileAlert]) -> some View {
        VStack(spacing: 8) {
            SectionHeader(title: "Recent Alerts", accent: NerVyx.warning, trailing: "\(alerts.count) total")
            ForEach(alerts.prefix(3)) { alert in
                HStack(alignment: .top, spacing: 10) {
                    Circle()
                        .fill(alertSeverityColor(alert.severity))
                        .frame(width: 7, height: 7)
                        .padding(.top, 5)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("[\(alert.symbol)] \(alert.type)")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(NerVyx.textPrimary)
                        Text(alert.message)
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                            .lineLimit(2)
                    }
                    Spacer()
                    NerVyxBadge(text: alert.severity.uppercased(), color: alertSeverityColor(alert.severity), small: true)
                }
            }
        }
        .nerVyxCard(accent: NerVyx.warning.opacity(0.3))
    }

    private func healthFooter(_ h: MobileHealth) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(h.isHealthy ? NerVyx.validation : NerVyx.warning)
                .frame(width: 8, height: 8)
            Text("System: \(h.overall)")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
            Spacer()
            Text("Redis: \(h.redis_connected ? "connected" : "offline")")
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(h.redis_connected ? NerVyx.validation : NerVyx.sell)
        }
        .padding(.horizontal, 4)
    }

    private func alertSeverityColor(_ s: String) -> Color {
        switch s.lowercased() {
        case "critical": return NerVyx.sell
        case "warning": return NerVyx.warning
        default: return NerVyx.inference
        }
    }
}
