import SwiftUI

struct PaperTradingView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PaperViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.summary == nil {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting execution runtime…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.summary == nil {
                        VStack(spacing: 12) {
                            Image(systemName: "exclamationmark.triangle").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
                            Text(err).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
                            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                                .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else if let s = vm.summary {
                        paperContent(s)
                    }
                }
            }
            .navigationTitle("NERVYX EXECUTE")
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

    private func paperContent(_ s: MobilePaperSummary) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                // Mode banner
                HStack(spacing: 8) {
                    LivePulse(color: NerVyx.paper)
                    Text("Execution runtime · \(nervyxPublicRuntimeText(s.live_gate))")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    NerVyxBadge(text: s.places_real_order ? "LIVE" : "GATED", color: s.places_real_order ? NerVyx.sell : NerVyx.signal, small: true)
                }
                .padding(.horizontal, 4)

                pnlCard(s.pnl)
                loopCard(s.loop)
                positionsCard(s.positions)
                feedbackCard(s.trainer_feedback)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - PnL

    private func pnlCard(_ pnl: PaperPnL) -> some View {
        VStack(spacing: 12) {
            SectionHeader(title: "PnL Summary", accent: NerVyx.buy)
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("TOTAL PnL")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text(String(format: "%@$%.2f", pnl.total_usd >= 0 ? "+" : "", pnl.total_usd))
                        .font(.system(size: 28, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.total_usd))
                }
                Spacer()
                if let wr = pnl.win_rate_pct {
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("WIN RATE")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(NerVyx.textMuted)
                            .tracking(0.6)
                        Text(String(format: "%.1f%%", wr))
                            .font(.system(size: 24, weight: .bold, design: .monospaced))
                            .foregroundStyle(wr >= 60 ? NerVyx.validation : wr >= 50 ? NerVyx.buy : NerVyx.warning)
                    }
                }
            }
            NerVyxDivider()
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Realized").font(.system(size: 11)).foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", pnl.realized_usd))
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.realized_usd))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 3) {
                    Text("Unrealized").font(.system(size: 11)).foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", pnl.unrealized_usd))
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.unrealized_usd))
                }
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.buy)
    }

    // MARK: - Loop

    private func loopCard(_ loop: PaperLoop) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Runtime Loop", accent: NerVyx.paper)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                NerVyxStatCard(
                    label: "SEEN",
                    value: "\(loop.signals_seen)",
                    accent: NerVyx.signal
                )
                NerVyxStatCard(
                    label: "ACCEPTED",
                    value: "\(loop.intents_accepted)",
                    valueColor: NerVyx.buy,
                    accent: NerVyx.buy
                )
                NerVyxStatCard(
                    label: "BLOCKED",
                    value: "\(loop.intents_blocked)",
                    valueColor: NerVyx.sell,
                    accent: NerVyx.sell
                )
            }
            NerVyxDivider()
            DataRow(label: "Intents built", value: "\(loop.intents_built)")
            DataRow(label: "Block rate", value: String(format: "%.1f%%", loop.blockRate),
                    valueColor: loop.blockRate > 80 ? NerVyx.warning : NerVyx.textSecondary)
            DataRow(label: "Classification", value: loop.classification, valueColor: NerVyx.paper)
        }
        .nerVyxCard(accent: NerVyx.paper.opacity(0.3))
    }

    // MARK: - Positions

    private func positionsCard(_ positions: PaperPositions) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Positions", accent: NerVyx.inference, trailing: "\(positions.closed_count) closed")
            HStack(spacing: 10) {
                NerVyxStatCard(label: "OPEN", value: "\(positions.open_count)", accent: NerVyx.paper)
                NerVyxStatCard(label: "CLOSED", value: "\(positions.closed_count)", accent: NerVyx.borderStrong)
            }
            if !positions.positions_preview.isEmpty {
                NerVyxDivider()
                ForEach(positions.positions_preview.prefix(3)) { pos in
                    HStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 2)
                            .fill(pos.isBuy ? NerVyx.buy : NerVyx.sell)
                            .frame(width: 3, height: 32)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(pos.shortSymbol)
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(NerVyx.textPrimary)
                            Text("Mark \(String(format: "%.4f", pos.mark_price))")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(NerVyx.textMuted)
                        }
                        Spacer()
                        Text(String(format: "%@$%.2f", pos.unrealized_pnl >= 0 ? "+" : "", pos.unrealized_pnl))
                            .font(.system(size: 13, weight: .bold, design: .monospaced))
                            .foregroundStyle(NerVyx.pnlColor(pos.unrealized_pnl))
                    }
                }
            }
        }
        .nerVyxCard()
    }

    // MARK: - Trainer Feedback

    private func feedbackCard(_ fb: TrainerFeedback) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Trainer Feedback Loop", accent: NerVyx.primary)
            DataRow(label: "Outcome labels", value: "\(fb.outcome_labels)")
            DataRow(
                label: "Consumable rows",
                value: "\(fb.consumable_rows)",
                valueColor: fb.consumable_rows > 0 ? NerVyx.validation : NerVyx.textMuted
            )
            DataRow(
                label: "Quarantined rows",
                value: "\(fb.quarantined_rows)",
                valueColor: fb.quarantined_rows > 0 ? NerVyx.warning : NerVyx.textMuted
            )
        }
        .nerVyxCard(accent: NerVyx.primary.opacity(0.25))
    }
}
