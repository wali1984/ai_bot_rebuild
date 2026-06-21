import SwiftUI

struct SignalsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = SignalsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.signals.isEmpty {
                    LoadingView()
                } else if let err = vm.error, vm.signals.isEmpty {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    signalsList
                }
            }
            .navigationTitle("Signals")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Toggle("Actionable", isOn: Binding(
                        get: { vm.actionableOnly },
                        set: { vm.actionableOnly = $0 }
                    ))
                    .toggleStyle(.button)
                    .font(.caption)
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }) {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable {
                await vm.load(token: auth.currentToken(), baseURL: appState.baseURL)
            }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var signalsList: some View {
        List {
            Section("Signals (\(vm.signals.count))") {
                if vm.signals.isEmpty {
                    ContentUnavailableView(
                        "No Signals",
                        systemImage: "antenna.radiowaves.left.and.right.slash",
                        description: Text("Signals will appear when the trainer is active")
                    )
                } else {
                    ForEach(vm.signals) { sig in
                        NavigationLink(destination: SignalDetailView(signal: sig)) {
                            SignalRowView(signal: sig)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }
}

struct SignalRowView: View {
    let signal: MobileSignal

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(signal.symbol)
                    .font(.headline)
                Text(signal.timeframe)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                StatusBadge(
                    label: signal.action.uppercased(),
                    color: actionColor(signal.action)
                )
            }
            HStack {
                HStack(spacing: 4) {
                    Image(systemName: "percent")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(signal.confidencePct)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if signal.actionable {
                    Label("Actionable", systemImage: "checkmark.circle.fill")
                        .font(.caption2)
                        .foregroundStyle(.green)
                } else {
                    Text(signal.risk_state)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func actionColor(_ action: String) -> Color {
        switch action.lowercased() {
        case "buy", "long": return .green
        case "sell", "short": return .red
        default: return .secondary
        }
    }
}

struct SignalDetailView: View {
    let signal: MobileSignal

    var body: some View {
        List {
            Section("Signal") {
                MetricRow(label: "Symbol", value: signal.symbol)
                MetricRow(label: "Timeframe", value: signal.timeframe)
                MetricRow(
                    label: "Action",
                    value: signal.action.uppercased(),
                    valueColor: signal.action.lowercased().contains("buy") || signal.action.lowercased().contains("long") ? .green : .red
                )
                MetricRow(label: "Confidence", value: signal.confidencePct)
            }
            Section("Status") {
                MetricRow(
                    label: "Actionable",
                    value: signal.actionable ? "YES" : "NO",
                    valueColor: signal.actionable ? .green : .orange
                )
                MetricRow(label: "Risk State", value: signal.risk_state)
                MetricRow(label: "Paper Fill", value: signal.paper_fill_status)
            }
            Section("Meta") {
                MetricRow(label: "Signal ID", value: String(signal.id.prefix(16)) + "…")
                MetricRow(label: "Published", value: signal.published_at)
            }
        }
        .navigationTitle(signal.symbol)
        .navigationBarTitleDisplayMode(.inline)
    }
}
