import SwiftUI

private func activityPriceText(_ value: Double?) -> String {
    guard let v = value, v > 0 else { return "—" }
    return String(format: "%.4f", v)
}

private func activityMoneyText(_ value: Double?) -> String {
    guard let v = value else { return "—" }
    return String(format: "%@$%.4f", v >= 0 ? "+" : "", v)
}

private func activityAgeText(_ value: String?) -> String {
    guard let v = value else { return "—" }
    return String(v.prefix(19))
}

struct ActivityView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = ActivityViewModel()
    @State private var searchText = ""

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.closedTrades.isEmpty {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Loading execution history…")
                                .font(.system(size: 14))
                                .foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.closedTrades.isEmpty {
                        VStack(spacing: 16) {
                            Image(systemName: "exclamationmark.triangle")
                                .font(.system(size: 32))
                                .foregroundStyle(NerVyx.warning)
                            Text(err)
                                .foregroundStyle(NerVyx.textSecondary)
                                .multilineTextAlignment(.center)
                            Button("Retry") {
                                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                            }
                            .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else {
                        activityContent
                    }
                }
            }
            .navigationTitle("Executions")
            .navigationBarTitleDisplayMode(.large)
            .searchable(text: $searchText, prompt: "Filter by symbol")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
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

    // MARK: - Content

    private var filteredTrades: [MobilePosition] {
        if searchText.isEmpty { return vm.closedTrades }
        return vm.closedTrades.filter {
            $0.symbol.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var activityContent: some View {
        ScrollView {
            VStack(spacing: 12) {
                summaryBar
                if vm.closedTrades.isEmpty {
                    emptyState
                } else {
                    tradesList
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private var summaryBar: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
            NerVyxStatCard(
                label: "CLOSED",
                value: "\(vm.closedTrades.count)",
                accent: NerVyx.borderStrong
            )
            NerVyxStatCard(
                label: "TOTAL PNL",
                value: activityMoneyText(vm.totalRealizedPnL),
                valueColor: NerVyx.pnlColor(vm.totalRealizedPnL),
                accent: NerVyx.pnlColor(vm.totalRealizedPnL)
            )
            NerVyxStatCard(
                label: "WIN RATE",
                value: vm.closedTrades.isEmpty ? "—" : String(format: "%.1f%%", vm.winRate),
                valueColor: vm.winRate >= 50 ? NerVyx.validation : NerVyx.warning,
                accent: NerVyx.inference
            )
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 36))
                .foregroundStyle(NerVyx.textMuted)
            Text("No execution history yet")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(NerVyx.textSecondary)
            Text("Closed trades appear here as the runtime processes and closes positions.")
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .padding(32)
        .frame(maxWidth: .infinity)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }

    private var tradesList: some View {
        VStack(spacing: 0) {
            HStack {
                SectionHeader(
                    title: "Closed Trades (\(filteredTrades.count))",
                    accent: NerVyx.primary
                )
                Spacer()
                Text(vm.streamLabel.uppercased())
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)

            ForEach(filteredTrades) { trade in
                NavigationLink(destination: PositionDetailView(position: trade)) {
                    ActivityTradeRow(trade: trade)
                }
                .buttonStyle(.plain)
                if trade.id != filteredTrades.last?.id {
                    NerVyxDivider().padding(.horizontal, 16)
                }
            }
        }
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }
}

// MARK: - Trade Row

struct ActivityTradeRow: View {
    let trade: MobilePosition

    private var closeReason: String {
        if let r = trade.close_reason, !r.isEmpty { return nervyxPublicRuntimeText(r) }
        if let r = trade.decision_reasoning?.reason, !r.isEmpty { return nervyxPublicRuntimeText(r) }
        return "exit executed"
    }

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 3)
                .fill(trade.isBuy ? NerVyx.buy : NerVyx.sell)
                .frame(width: 4, height: 56)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(trade.shortSymbol)
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    NerVyxBadge(
                        text: trade.side.uppercased(),
                        color: trade.isBuy ? NerVyx.buy : NerVyx.sell,
                        small: true
                    )
                    Spacer()
                    Text(activityMoneyText(trade.realized_pnl))
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(trade.realized_pnl))
                }
                HStack {
                    Text("Entry \(activityPriceText(trade.entry_price))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("→")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("Exit \(activityPriceText(trade.exit_price))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                    Spacer()
                    Text(activityAgeText(trade.closed_at ?? trade.opened_at))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                }
                Text(closeReason)
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(NerVyx.bg)
        .contentShape(Rectangle())
    }
}
