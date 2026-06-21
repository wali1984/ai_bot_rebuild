import SwiftUI

struct DashboardView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DashboardViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    LiveBlockBanner()
                    content
                }
            }
            .navigationTitle("Dashboard")
            .toolbar { refreshButton }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    @ViewBuilder
    private var content: some View {
        if vm.isLoading && vm.dashboard == nil {
            LoadingView()
        } else if let err = vm.error, vm.dashboard == nil {
            ErrorStateView(message: err) {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }
        } else {
            VStack(spacing: 16) {
                if let d = vm.dashboard {
                    systemStatusSection(d)
                    paperSection(d.paper)
                    trainerSection(d.trainer)
                    gpuSection(d.gpu)
                    if !d.alerts_preview.isEmpty {
                        alertsPreviewSection(d.alerts_preview)
                    }
                }
                if let h = vm.health {
                    healthIndicator(h)
                }
            }
            .padding(.horizontal)
        }
    }

    private func systemStatusSection(_ d: MobileDashboard) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("System Status", icon: "checkmark.shield")
            HStack(spacing: 12) {
                MetricCard(
                    title: "Redis",
                    value: d.redis_connected ? "Connected" : "Offline",
                    valueColor: d.redis_connected ? .green : .red,
                    icon: "server.rack"
                )
                MetricCard(
                    title: "Live Gate",
                    value: "BLOCKED",
                    valueColor: .red,
                    icon: "lock.shield"
                )
            }
        }
    }

    private func paperSection(_ paper: PaperState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Paper Trading", icon: "doc.plaintext")
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                MetricCard(
                    title: "Open Positions",
                    value: "\(paper.open_positions)",
                    icon: "chart.line.uptrend.xyaxis"
                )
                MetricCard(
                    title: "Closed Trades",
                    value: "\(paper.closed_trades)",
                    icon: "checkmark.circle"
                )
                MetricCard(
                    title: "Realized PnL",
                    value: String(format: "$%.2f", paper.realized_pnl_usd),
                    valueColor: paper.realized_pnl_usd >= 0 ? .green : .red,
                    icon: "dollarsign.circle"
                )
                MetricCard(
                    title: "Unrealized PnL",
                    value: String(format: "$%.2f", paper.unrealized_pnl_usd),
                    valueColor: paper.unrealized_pnl_usd >= 0 ? .green : .red,
                    icon: "chart.xyaxis.line"
                )
            }
            MetricRow(
                label: "Signals seen",
                value: "\(paper.signals_seen)",
                systemImage: "antenna.radiowaves.left.and.right"
            )
            MetricRow(
                label: "Intents accepted / blocked",
                value: "\(paper.intents_accepted) / \(paper.intents_blocked)"
            )
        }
    }

    private func trainerSection(_ trainer: TrainerState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("Trainer", icon: "brain")
            HStack(spacing: 12) {
                MetricCard(
                    title: "State",
                    value: trainer.isActive ? "Active" : trainer.state,
                    valueColor: trainer.isActive ? .green : .orange,
                    icon: "brain"
                )
                MetricCard(
                    title: "CUDA",
                    value: trainer.cuda_active ? "Active" : "Off",
                    valueColor: trainer.cuda_active ? .green : .secondary,
                    icon: "cpu"
                )
            }
            MetricRow(label: "Steps total", value: "\(trainer.training_steps_total.formatted())")
            MetricRow(label: "Steps/hr", value: "\(trainer.training_steps_last_hour.formatted())")
            MetricRow(label: "Data coverage", value: String(format: "%.1f%%", trainer.data_coverage))
            if !trainer.checkpoint.isEmpty {
                MetricRow(label: "Checkpoint", value: String(trainer.checkpoint.prefix(16)) + "…")
            }
        }
    }

    private func gpuSection(_ gpu: GPUState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionHeader("GPU — \(gpu.name.isEmpty ? "Unknown" : gpu.name)", icon: "cpu.fill")
            HStack(spacing: 12) {
                GaugeCard(
                    title: "Utilization",
                    value: gpu.utilization_pct,
                    max: 100,
                    unit: "%",
                    color: gpu.utilization_pct > 90 ? .orange : .blue
                )
                GaugeCard(
                    title: "VRAM",
                    value: gpu.vramUsedGB,
                    max: gpu.vramTotalGB,
                    unit: " GB",
                    color: gpu.vramPercent > 90 ? .orange : .purple
                )
            }
        }
    }

    private func alertsPreviewSection(_ alerts: [MobileAlert]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("Recent Alerts", icon: "bell.badge")
            ForEach(alerts.prefix(3)) { alert in
                HStack(alignment: .top, spacing: 8) {
                    Circle()
                        .fill(alertColor(alert.severity))
                        .frame(width: 8, height: 8)
                        .padding(.top, 4)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("[\(alert.symbol)] \(alert.type)")
                            .font(.caption.weight(.medium))
                        Text(alert.message)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(2)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func healthIndicator(_ h: MobileHealth) -> some View {
        HStack {
            Circle()
                .fill(healthColor(h.overall))
                .frame(width: 10, height: 10)
            Text("System: \(h.overall.capitalized)")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
            if let ts = vm.dashboard?.generated_utc {
                Text("Updated \(formattedTime(ts))")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal)
        .padding(.bottom, 8)
    }

    private func sectionHeader(_ title: String, icon: String) -> some View {
        Label(title, systemImage: icon)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.secondary)
    }

    private var refreshButton: some ToolbarContent {
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }) {
                Image(systemName: "arrow.clockwise")
            }
            .disabled(vm.isLoading)
        }
    }

    private func alertColor(_ severity: String) -> Color {
        switch severity { case "critical": return .red; case "warning": return .orange; default: return .blue }
    }

    private func healthColor(_ overall: String) -> Color {
        switch overall { case "healthy": return .green; case "degraded": return .yellow; default: return .red }
    }

    private func formattedTime(_ iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: iso) {
            let rel = RelativeDateTimeFormatter()
            rel.unitsStyle = .abbreviated
            return rel.localizedString(for: date, relativeTo: .now)
        }
        return iso
    }
}
