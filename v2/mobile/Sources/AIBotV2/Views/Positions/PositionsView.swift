import SwiftUI

struct PositionsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PositionsViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.positions.isEmpty {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting positions stream…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.positions.isEmpty {
                        VStack(spacing: 12) {
                            Image(systemName: "exclamationmark.triangle").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
                            Text(err).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
                            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                                .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else {
                        positionsList
                    }
                }
            }
            .navigationTitle("Portfolio")
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

    private var positionsList: some View {
        ScrollView {
            VStack(spacing: 12) {
                // Summary card
                if let s = vm.summary {
                    summaryCard(s)
                }

                // Positions list
                if vm.positions.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "chart.line.downtrend.xyaxis")
                            .font(.system(size: 36))
                            .foregroundStyle(NerVyx.textMuted)
                        Text("No open positions")
                            .font(.system(size: 15, weight: .medium))
                            .foregroundStyle(NerVyx.textSecondary)
                        Text("Runtime positions open automatically\nwhen signals are accepted by the risk gateway.")
                            .font(.system(size: 13))
                            .foregroundStyle(NerVyx.textMuted)
                            .multilineTextAlignment(.center)
                    }
                    .padding(32)
                } else {
                    VStack(spacing: 0) {
                        SectionHeader(title: "Open Positions (\(vm.positions.count))", accent: NerVyx.buy)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 10)

                        ForEach(vm.positions) { pos in
                            NavigationLink(destination: PositionDetailView(position: pos)) {
                                PositionRowView(position: pos)
                            }
                            .buttonStyle(.plain)
                            NerVyxDivider().padding(.horizontal, 16)
                        }
                    }
                    .background(NerVyx.panel)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
                    .padding(.horizontal, 0)
                }
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    private func summaryCard(_ s: PositionSummary) -> some View {
        VStack(spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("TOTAL PnL")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text(String(format: "%@$%.2f", s.total_pnl_usd >= 0 ? "+" : "", s.total_pnl_usd))
                        .font(.system(size: 30, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(s.total_pnl_usd))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text("OPEN")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text("\(s.open_count)")
                        .font(.system(size: 30, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.textPrimary)
                }
            }
            NerVyxDivider()
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Realized")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", s.realized_pnl_usd))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(s.realized_pnl_usd))
                }
                Spacer()
                VStack(alignment: .center, spacing: 3) {
                    Text("Unrealized")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", s.unrealized_pnl_usd))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(s.unrealized_pnl_usd))
                }
                Spacer()
                    NerVyxBadge(text: "LIVE", color: NerVyx.signal)
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.pnlColor(s.total_pnl_usd))
    }
}

// MARK: - Position Row

struct PositionRowView: View {
    let position: MobilePosition

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 3)
                .fill(position.isBuy ? NerVyx.buy : NerVyx.sell)
                .frame(width: 4, height: 44)

            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text(position.shortSymbol)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Text("×\(String(format: "%.4f", position.qty))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    NerVyxBadge(
                        text: position.side.uppercased(),
                        color: position.isBuy ? NerVyx.buy : NerVyx.sell
                    )
                }
                HStack {
                    Text("Entry \(String(format: "%.4f", position.entry_price))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("→")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("Mark \(String(format: "%.4f", position.mark_price))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                    Spacer()
                    Text(String(format: "%@$%.2f", position.unrealized_pnl >= 0 ? "+" : "", position.unrealized_pnl))
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(position.unrealized_pnl))
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(NerVyx.panel)
        .contentShape(Rectangle())
    }
}

// MARK: - Position Detail

struct PositionDetailView: View {
    let position: MobilePosition

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 12) {
                    // Header
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(position.shortSymbol)
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(NerVyx.textPrimary)
                            Text(position.symbol).font(.system(size: 13)).foregroundStyle(NerVyx.textMuted)
                        }
                        Spacer()
                        VStack(alignment: .trailing, spacing: 6) {
                            NerVyxBadge(
                                text: position.side.uppercased(),
                                color: position.isBuy ? NerVyx.buy : NerVyx.sell
                            )
                            NerVyxBadge(text: position.status.uppercased(), color: NerVyx.paper, small: true)
                        }
                    }
                    .nerVyxElevatedCard(accent: position.isBuy ? NerVyx.buy : NerVyx.sell)

                    // PnL card
                    VStack(spacing: 10) {
                        SectionHeader(title: "PnL", accent: NerVyx.pnlColor(position.total_pnl))
                        HStack {
                            Text("TOTAL")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(NerVyx.textMuted)
                                .tracking(0.6)
                            Spacer()
                            Text(String(format: "%@$%.4f", position.total_pnl >= 0 ? "+" : "", position.total_pnl))
                                .font(.system(size: 22, weight: .bold, design: .monospaced))
                                .foregroundStyle(NerVyx.pnlColor(position.total_pnl))
                        }
                        NerVyxDivider()
                        DataRow(
                            label: "Unrealized",
                            value: String(format: "$%.4f", position.unrealized_pnl),
                            valueColor: NerVyx.pnlColor(position.unrealized_pnl),
                            mono: true
                        )
                        DataRow(
                            label: "Realized",
                            value: String(format: "$%.4f", position.realized_pnl),
                            valueColor: NerVyx.pnlColor(position.realized_pnl),
                            mono: true
                        )
                    }
                    .nerVyxCard()

                    // Prices card
                    VStack(spacing: 10) {
                        SectionHeader(title: "Prices", accent: NerVyx.inference)
                        DataRow(label: "Quantity", value: String(format: "%.6f", position.qty), mono: true)
                        DataRow(label: "Entry Price", value: String(format: "%.6f", position.entry_price), mono: true)
                        DataRow(label: "Mark Price", value: String(format: "%.6f", position.mark_price), mono: true)
                    }
                    .nerVyxCard()

                    // Meta card
                    VStack(spacing: 10) {
                        SectionHeader(title: "Meta", accent: NerVyx.textMuted)
                        DataRow(label: "ID", value: String(position.id.prefix(20)) + "…", mono: true)
                        DataRow(label: "Opened", value: String(position.opened_at.prefix(19)), mono: true)
                    }
                    .nerVyxCard(accent: NerVyx.borderSubtle)
                }
                .padding(16)
                .padding(.bottom, 24)
            }
        }
        .navigationTitle(position.shortSymbol)
        .navigationBarTitleDisplayMode(.inline)
    }
}
