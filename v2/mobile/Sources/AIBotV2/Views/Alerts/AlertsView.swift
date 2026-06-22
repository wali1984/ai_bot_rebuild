import SwiftUI

struct AlertsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AlertsViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.alerts.isEmpty {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting alerts stream…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.alerts.isEmpty {
                        VStack(spacing: 12) {
                            Image(systemName: "bell.slash").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
                            Text(err).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
                            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                                .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else {
                        alertContent
                    }
                }
            }
            .navigationTitle("NERVYX OBSERVE")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } } label: {
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

    private var alertContent: some View {
        ScrollView {
            VStack(spacing: 0) {
                if vm.alerts.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "bell.badge.slash")
                            .font(.system(size: 36))
                            .foregroundStyle(NerVyx.textMuted)
                        Text("No alerts")
                            .font(.system(size: 15, weight: .medium))
                            .foregroundStyle(NerVyx.textSecondary)
                        Text("System alerts appear here when triggered.")
                            .font(.system(size: 13))
                            .foregroundStyle(NerVyx.textMuted)
                            .multilineTextAlignment(.center)
                    }
                    .padding(40)
                } else {
                    // Critical alerts section
                    if !vm.criticalAlerts.isEmpty {
                        criticalSection
                    }
                    // All alerts
                    allAlertsSection
                }
            }
            .padding(.bottom, 24)
        }
    }

    private var criticalSection: some View {
        VStack(spacing: 0) {
            SectionHeader(title: "Critical (\(vm.criticalAlerts.count))", accent: NerVyx.sell)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            ForEach(vm.criticalAlerts) { alert in
                AlertRowView(alert: alert)
                NerVyxDivider().padding(.horizontal, 16)
            }
        }
        .background(NerVyx.sell.opacity(0.06))
    }

    private var allAlertsSection: some View {
        VStack(spacing: 0) {
            SectionHeader(title: "All Alerts (\(vm.alerts.count))", accent: NerVyx.warning)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            ForEach(vm.alerts) { alert in
                AlertRowView(alert: alert)
                NerVyxDivider().padding(.horizontal, 16)
            }
        }
    }
}

// MARK: - Alert Row

struct AlertRowView: View {
    let alert: MobileAlert

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(severityColor)
                .frame(width: 8, height: 8)
                .padding(.top, 6)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("[\(alert.symbol)]")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                    Text(alert.type)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Spacer()
                    Text(String(alert.triggered_at.prefix(10)))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                }
                Text(alert.message)
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(2)
                NerVyxBadge(text: alert.severity.uppercased(), color: severityColor, small: true)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(NerVyx.bg)
        .contentShape(Rectangle())
    }

    private var severityColor: Color {
        switch alert.severity.lowercased() {
        case "critical": return NerVyx.sell
        case "warning": return NerVyx.warning
        case "error": return Color(hex: "FF2E55")
        default: return NerVyx.inference
        }
    }
}
