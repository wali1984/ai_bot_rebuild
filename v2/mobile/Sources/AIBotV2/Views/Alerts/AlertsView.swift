import SwiftUI

struct AlertsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AlertsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.alerts.isEmpty {
                    LoadingView()
                } else if let err = vm.error, vm.alerts.isEmpty {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    alertList
                }
            }
            .navigationTitle("NERVYX OBSERVE")
            .toolbar { refreshButton }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var alertList: some View {
        List {
            if !vm.criticalAlerts.isEmpty {
                Section("NERVYX OBSERVE · Critical (\(vm.criticalAlerts.count))") {
                    ForEach(vm.criticalAlerts) { alert in AlertRowView(alert: alert) }
                }
            }
            Section("NERVYX OBSERVE · All Alerts (\(vm.alerts.count))") {
                if vm.alerts.isEmpty {
                    ContentUnavailableView(
                        "No Alerts",
                        systemImage: "bell.slash",
                        description: Text("Market alerts will appear here")
                    )
                } else {
                    ForEach(vm.alerts) { alert in AlertRowView(alert: alert) }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private var refreshButton: some ToolbarContent {
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }) {
                Image(systemName: "arrow.clockwise")
            }
        }
    }
}

struct AlertRowView: View {
    let alert: MobileAlert

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Circle()
                    .fill(severityColor)
                    .frame(width: 8, height: 8)
                Text("[\(alert.symbol)] \(alert.type)")
                    .font(.subheadline.weight(.medium))
                Spacer()
                Text(alert.triggered_at.prefix(10))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            Text(alert.message)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            StatusBadge(label: alert.severity.uppercased(), color: severityColor)
        }
        .padding(.vertical, 4)
    }

    private var severityColor: Color {
        switch alert.severity.lowercased() {
        case "critical": return .red
        case "warning": return .orange
        case "error": return .pink
        default: return .blue
        }
    }
}
