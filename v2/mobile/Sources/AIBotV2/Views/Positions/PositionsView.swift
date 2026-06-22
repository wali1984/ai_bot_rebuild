import SwiftUI

struct PositionsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PositionsViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.positions.isEmpty {
                    LoadingView()
                } else if let err = vm.error, vm.positions.isEmpty {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    positionsList
                }
            }
            .navigationTitle("NERVYX EXECUTE")
            .toolbar { refreshButton }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var positionsList: some View {
        List {
            if let summary = vm.summary {
                Section {
                    summaryHeader(summary)
                }
            }
            Section("NERVYX EXECUTE · Open Positions (\(vm.positions.count))") {
                if vm.positions.isEmpty {
                    ContentUnavailableView(
                        "No Open Positions",
                        systemImage: "chart.line.downtrend.xyaxis",
                        description: Text("Open positions will appear here")
                    )
                } else {
                    ForEach(vm.positions) { pos in
                        NavigationLink(destination: PositionDetailView(position: pos)) {
                            PositionRowView(position: pos)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    private func summaryHeader(_ s: PositionSummary) -> some View {
        VStack(spacing: 12) {
            HStack {
                VStack(alignment: .leading) {
                    Text("Total PnL")
                        .font(.caption).foregroundStyle(.secondary)
                    Text(String(format: "$%.2f", s.total_pnl_usd))
                        .font(.title2.weight(.bold))
                        .foregroundStyle(s.total_pnl_usd >= 0 ? .green : .red)
                }
                Spacer()
                VStack(alignment: .trailing) {
                    Text("Open")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("\(s.open_count)")
                        .font(.title2.weight(.bold))
                }
            }
            HStack(spacing: 20) {
                VStack {
                    Text("Realized").font(.caption2).foregroundStyle(.secondary)
                    Text(String(format: "$%.2f", s.realized_pnl_usd))
                        .font(.caption.weight(.medium))
                        .foregroundStyle(s.realized_pnl_usd >= 0 ? .green : .red)
                }
                Divider().frame(height: 30)
                VStack {
                    Text("Unrealized").font(.caption2).foregroundStyle(.secondary)
                    Text(String(format: "$%.2f", s.unrealized_pnl_usd))
                        .font(.caption.weight(.medium))
                        .foregroundStyle(s.unrealized_pnl_usd >= 0 ? .green : .red)
                }
                Spacer()
                Text("LIVE")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(.orange.opacity(0.1))
                    .clipShape(Capsule())
            }
        }
        .padding(.vertical, 8)
    }

    private var refreshButton: some ToolbarContent {
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }) {
                Image(systemName: "arrow.clockwise")
            }
        }
    }
}

struct PositionRowView: View {
    let position: MobilePosition

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(position.symbol)
                    .font(.headline)
                Spacer()
                StatusBadge(
                    label: position.side.uppercased(),
                    color: position.isBuy ? .green : .red
                )
            }
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Entry: \(String(format: "%.4f", position.entry_price))")
                        .font(.caption).foregroundStyle(.secondary)
                    Text("Mark: \(String(format: "%.4f", position.mark_price))")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("PnL")
                        .font(.caption2).foregroundStyle(.secondary)
                    Text(String(format: "$%.2f", position.unrealized_pnl))
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(position.unrealized_pnl >= 0 ? .green : .red)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

struct PositionDetailView: View {
    let position: MobilePosition

    var body: some View {
        List {
            Section("Position") {
                MetricRow(label: "Symbol", value: position.symbol)
                MetricRow(label: "Side", value: position.side.uppercased())
                MetricRow(label: "Status", value: position.status.uppercased())
                MetricRow(label: "Quantity", value: "\(position.qty)")
            }
            Section("Prices") {
                MetricRow(label: "Entry Price", value: String(format: "%.6f", position.entry_price))
                MetricRow(label: "Mark Price", value: String(format: "%.6f", position.mark_price))
            }
            Section("PnL") {
                MetricRow(
                    label: "Unrealized PnL",
                    value: String(format: "$%.2f", position.unrealized_pnl),
                    valueColor: position.unrealized_pnl >= 0 ? .green : .red
                )
                MetricRow(
                    label: "Realized PnL",
                    value: String(format: "$%.2f", position.realized_pnl),
                    valueColor: position.realized_pnl >= 0 ? .green : .red
                )
                MetricRow(
                    label: "Total PnL",
                    value: String(format: "$%.2f", position.total_pnl),
                    valueColor: position.total_pnl >= 0 ? .green : .red
                )
            }
            Section("Meta") {
                MetricRow(label: "Position ID", value: String(position.id.prefix(16)) + "…")
                MetricRow(label: "Opened", value: position.opened_at)
            }
        }
        .navigationTitle(position.symbol)
        .navigationBarTitleDisplayMode(.inline)
    }
}
