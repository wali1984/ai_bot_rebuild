import SwiftUI

struct DashboardView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DashboardViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 16) {
                        streamBar
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
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopStreams() }
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
        VStack(spacing: 0) {
            SectionHeader(title: "PnL Summary", accent: NerVyx.buy, trailing: "LIVE")
                .padding(.bottom, 12)
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("TOTAL PnL")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text(String(format: "%@$%.2f", paper.total_pnl >= 0 ? "+" : "", paper.total_pnl))
                        .font(.system(size: 28, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(paper.total_pnl))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 6) {
                    DataRow(
                        label: "Realized",
                        value: String(format: "$%.2f", paper.realized_pnl_usd),
                        valueColor: NerVyx.pnlColor(paper.realized_pnl_usd),
                        mono: true
                    )
                    DataRow(
                        label: "Unrealized",
                        value: String(format: "$%.2f", paper.unrealized_pnl_usd),
                        valueColor: NerVyx.pnlColor(paper.unrealized_pnl_usd),
                        mono: true
                    )
                }
                .frame(width: 160)
            }
        }
        .nerVyxCard(accent: NerVyx.borderSubtle)
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
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    DataRow(label: "Signals seen", value: "\(paper.signals_seen)")
                    DataRow(label: "Accepted", value: "\(paper.intents_accepted)", valueColor: NerVyx.buy)
                    DataRow(label: "Blocked", value: "\(paper.intents_blocked)", valueColor: NerVyx.sell)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text("Acceptance")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "%.0f%%", paper.acceptanceRate))
                        .font(.system(size: 20, weight: .bold, design: .monospaced))
                        .foregroundStyle(paper.acceptanceRate > 50 ? NerVyx.buy : NerVyx.warning)
                }
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
        VStack(spacing: 10) {
            SectionHeader(title: "GPU · \(gpu.displayName)", accent: NerVyx.inference)
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("UTILIZATION")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text("\(Int(gpu.utilization_pct))%")
                        .font(.system(size: 22, weight: .bold, design: .monospaced))
                        .foregroundStyle(gpu.utilization_pct > 80 ? NerVyx.warning : NerVyx.inference)
                    ConfidenceBar(value: gpu.utilization_pct / 100)
                }
                .frame(maxWidth: .infinity)
                Divider().background(NerVyx.borderSubtle)
                VStack(alignment: .leading, spacing: 4) {
                    Text("VRAM")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text(String(format: "%.1f / %.1f GB", gpu.vramUsedGB, gpu.vramTotalGB))
                        .font(.system(size: 15, weight: .bold, design: .monospaced))
                        .foregroundStyle(gpu.vramPercent > 85 ? NerVyx.warning : NerVyx.signal)
                    ConfidenceBar(value: gpu.vramPercent / 100)
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
