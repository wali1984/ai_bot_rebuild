import SwiftUI

struct MonitorView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DashboardViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.health == nil {
                    LoadingView()
                } else if let err = vm.error, vm.health == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    monitorContent
                }
            }
            .navigationTitle("Monitor")
            .toolbar { refreshButton }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var monitorContent: some View {
        ScrollView {
            VStack(spacing: 16) {
                if let health = vm.health {
                    overallStatus(health)
                    trainerHealth(health.trainer)
                    gpuHealth(health.gpu)
                    paperHealth(health.paper)
                }
            }
            .padding()
        }
    }

    private func overallStatus(_ h: MobileHealth) -> some View {
        HStack(spacing: 16) {
            Circle()
                .fill(overallColor(h.overall))
                .frame(width: 16, height: 16)
            VStack(alignment: .leading) {
                Text("System: \(h.overall.capitalized)")
                    .font(.headline)
                Text("Redis: \(h.redis_connected ? "Connected" : "Offline")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Text(h.live_gate.uppercased())
                .font(.caption2.weight(.bold))
                .foregroundStyle(.red)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(Color.red.opacity(0.1))
                .clipShape(Capsule())
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func trainerHealth(_ t: HealthTrainer) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Trainer", systemImage: "brain").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 8) {
                MetricRow(label: "State", value: t.state, valueColor: t.training_active ? .green : .orange)
                MetricRow(label: "CUDA", value: t.cuda_active ? "Active" : "Inactive", valueColor: t.cuda_active ? .green : .red)
                MetricRow(label: "Training", value: t.training_active ? "Active" : "Inactive", valueColor: t.training_active ? .green : .orange)
                if !t.checkpoint.isEmpty {
                    MetricRow(label: "Checkpoint", value: String(t.checkpoint.prefix(20)) + "…")
                }
            }
            .padding()
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func gpuHealth(_ g: HealthGPU) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("GPU — \(g.name.isEmpty ? "Unknown" : g.name)", systemImage: "cpu.fill")
                .font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 8) {
                GaugeCard(title: "Utilization", value: g.utilization_pct, max: 100, unit: "%",
                          color: g.utilization_pct > 90 ? .orange : .blue)
                GaugeCard(title: "VRAM", value: Double(g.vram_used_mb) / 1024,
                          max: Double(g.vram_total_mb) / 1024, unit: " GB",
                          color: Double(g.vram_used_mb) / Double(max(g.vram_total_mb, 1)) > 0.9 ? .orange : .purple)
                if g.temperature_c > 0 {
                    MetricRow(label: "Temperature",
                              value: "\(Int(g.temperature_c))°C",
                              valueColor: g.temperature_c > 80 ? .red : g.temperature_c > 70 ? .orange : .green)
                }
            }
        }
    }

    private func paperHealth(_ p: HealthPaper) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Paper Loop", systemImage: "doc.plaintext").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 8) {
                MetricRow(label: "Open Positions", value: "\(p.open_positions)")
                MetricRow(label: "Intents Accepted", value: "\(p.intents_accepted)", valueColor: .green)
                MetricRow(label: "Intents Blocked", value: "\(p.intents_blocked)", valueColor: .red)
                MetricRow(label: "Classification", value: p.classification)
            }
            .padding()
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func overallColor(_ s: String) -> Color {
        switch s { case "healthy": return .green; case "degraded": return .yellow; default: return .red }
    }

    private var refreshButton: some ToolbarContent {
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }) {
                Image(systemName: "arrow.clockwise")
            }
        }
    }
}
