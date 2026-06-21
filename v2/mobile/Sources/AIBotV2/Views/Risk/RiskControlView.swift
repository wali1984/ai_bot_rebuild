import SwiftUI

struct RiskControlView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AdminViewModel()
    @State private var showApprovalNote = false

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.riskStatus == nil {
                    LoadingView()
                } else if let err = vm.error, vm.riskStatus == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else if let risk = vm.riskStatus {
                    riskContent(risk)
                }
            }
            .navigationTitle("Risk Control")
            .safeAreaInset(edge: .top) { LiveBlockBanner() }
            .toolbar { refreshButton }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
    }

    private func riskContent(_ risk: MobileRiskStatus) -> some View {
        ScrollView {
            VStack(spacing: 16) {
                // Live gate status
                liveGateCard(risk.live_gate)

                // Kill switch
                killSwitchCard(risk.kill_switch_active)

                // Risk limits
                limitsSection(risk)

                // Paper stats
                paperStatsSection(risk)

                // Mobile approval note
                approvalNote()
            }
            .padding()
        }
    }

    private func liveGateCard(_ gate: LiveGateState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Live Gate", systemImage: "lock.shield.fill").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(gate.label)
                        .font(.headline.weight(.bold))
                        .foregroundStyle(.red)
                    Text("Places real order: \(gate.places_real_order ? "YES" : "NO")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "lock.fill")
                    .font(.title)
                    .foregroundStyle(.red)
            }
            .padding()
            .background(Color.red.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.red.opacity(0.3)))
        }
    }

    private func killSwitchCard(_ active: Bool) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Label("Kill Switch", systemImage: active ? "exclamationmark.shield.fill" : "shield.fill")
                    .font(.subheadline.weight(.semibold))
                Text(active ? "ACTIVE — All trading halted" : "Inactive — System running normally")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Circle()
                .fill(active ? Color.red : Color.green)
                .frame(width: 14, height: 14)
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func limitsSection(_ risk: MobileRiskStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Risk Limits", systemImage: "slider.horizontal.3").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 8) {
                MetricRow(label: "Max Position Size", value: risk.max_position_size_usd > 0 ? "$\(Int(risk.max_position_size_usd))" : "N/A")
                MetricRow(label: "Daily Loss Limit", value: risk.daily_loss_limit_usd > 0 ? "$\(Int(risk.daily_loss_limit_usd))" : "N/A")
                MetricRow(
                    label: "Current Daily Loss",
                    value: String(format: "$%.2f", risk.current_daily_loss_usd),
                    valueColor: risk.current_daily_loss_usd > 0 ? .red : .green
                )
            }
            .padding()
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func paperStatsSection(_ risk: MobileRiskStatus) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Paper Gate Activity", systemImage: "chart.bar").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                MetricCard(
                    title: "Accepted",
                    value: "\(risk.paper_accepted_count)",
                    valueColor: .green,
                    icon: "checkmark.circle"
                )
                MetricCard(
                    title: "Blocked",
                    value: "\(risk.paper_blocked_count)",
                    valueColor: .red,
                    icon: "xmark.circle"
                )
            }
        }
    }

    private func approvalNote() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Dangerous Controls", systemImage: "exclamationmark.triangle.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.orange)
            Text("Dangerous controls (enable live trading, change leverage, disable kill switch, etc.) require explicit human approval through the web admin interface. These actions CANNOT be approved from mobile.")
                .font(.caption)
                .foregroundStyle(.secondary)
            Link("Open Web Admin ↗", destination: URL(string: appState.baseURL + "/admin")!)
                .font(.caption.weight(.medium))
        }
        .padding()
        .background(Color.orange.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.orange.opacity(0.3)))
    }

    private var refreshButton: some ToolbarContent {
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }) {
                Image(systemName: "arrow.clockwise")
            }
        }
    }
}
