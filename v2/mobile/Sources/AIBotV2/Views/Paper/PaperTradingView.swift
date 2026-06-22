import SwiftUI

struct PaperTradingView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PaperViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.summary == nil {
                    LoadingView()
                } else if let err = vm.error, vm.summary == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else if let summary = vm.summary {
                    paperContent(summary)
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

    private func paperContent(_ s: MobilePaperSummary) -> some View {
        ScrollView {
            VStack(spacing: 16) {
                pnlSection(s.pnl)
                loopSection(s.loop)
                positionsSection(s.positions)
                feedbackSection(s.trainer_feedback)
            }
            .padding()
        }
    }

    private func pnlSection(_ pnl: PaperPnL) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("NERVYX EXECUTE · PnL Summary", systemImage: "dollarsign.circle").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                MetricCard(
                    title: "Total PnL",
                    value: String(format: "$%.2f", pnl.total_usd),
                    valueColor: pnl.total_usd >= 0 ? .green : .red,
                    icon: "chart.line.uptrend.xyaxis"
                )
                if let wr = pnl.win_rate_pct {
                    MetricCard(
                        title: "Win Rate",
                        value: String(format: "%.1f%%", wr),
                        valueColor: wr >= 50 ? .green : .orange,
                        icon: "percent"
                    )
                }
            }
            HStack(spacing: 12) {
                MetricCard(
                    title: "Realized",
                    value: String(format: "$%.2f", pnl.realized_usd),
                    valueColor: pnl.realized_usd >= 0 ? .green : .red,
                    icon: "checkmark.circle"
                )
                MetricCard(
                    title: "Unrealized",
                    value: String(format: "$%.2f", pnl.unrealized_usd),
                    valueColor: pnl.unrealized_usd >= 0 ? .green : .red,
                    icon: "clock.arrow.circlepath"
                )
            }
        }
    }

    private func loopSection(_ loop: PaperLoop) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("NERVYX EXECUTE · Runtime Loop", systemImage: "arrow.clockwise.circle").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 8) {
                MetricRow(label: "Signals seen", value: "\(loop.signals_seen)", systemImage: "antenna.radiowaves.left.and.right")
                MetricRow(label: "Intents built", value: "\(loop.intents_built)", systemImage: "list.bullet")
                MetricRow(label: "Intents accepted", value: "\(loop.intents_accepted)", valueColor: .green, systemImage: "checkmark.circle")
                MetricRow(label: "Intents blocked", value: "\(loop.intents_blocked)", valueColor: .red, systemImage: "xmark.circle")
                Divider()
                HStack {
                    Text("Classification")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text(loop.classification)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
                .font(.subheadline)
            }
            .padding()
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private func positionsSection(_ positions: PaperPositions) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("NERVYX EXECUTE · Positions", systemImage: "chart.line.uptrend.xyaxis").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                MetricCard(title: "Open", value: "\(positions.open_count)", icon: "chart.line.uptrend.xyaxis")
                MetricCard(title: "Closed", value: "\(positions.closed_count)", icon: "checkmark.circle.fill")
            }
            if !positions.positions_preview.isEmpty {
                VStack(spacing: 0) {
                    ForEach(positions.positions_preview) { pos in
                        PositionRowView(position: pos)
                            .padding(.horizontal)
                            .padding(.vertical, 8)
                        if pos.id != positions.positions_preview.last?.id {
                            Divider().padding(.horizontal)
                        }
                    }
                }
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    private func feedbackSection(_ fb: TrainerFeedback) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("NERVYX CORE · Trainer Feedback", systemImage: "brain").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            VStack(spacing: 8) {
                MetricRow(label: "Outcome labels", value: "\(fb.outcome_labels)")
                MetricRow(label: "Consumable rows", value: "\(fb.consumable_rows)", valueColor: fb.consumable_rows > 0 ? .green : .secondary)
                MetricRow(label: "Quarantined rows", value: "\(fb.quarantined_rows)", valueColor: fb.quarantined_rows > 0 ? .orange : .secondary)
            }
            .padding()
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private var refreshButton: some ToolbarContent {
        ToolbarItem(placement: .navigationBarTrailing) {
            Button(action: { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }) {
                Image(systemName: "arrow.clockwise")
            }
        }
    }
}
