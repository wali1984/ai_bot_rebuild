import SwiftUI

// MARK: - Executions (History) screen
//
// Website History parity: 1D/1W/30D/ALL PnL windows, per-bucket PnL bars +
// cumulative realized curve (labelled derived from closed-trade rows),
// backend NET window rollups with winner-flag win rate, side/PnL filter
// chips, and glass-card trade rows pushing the shared PositionDetailView.

private func activityPriceText(_ value: Double?) -> String {
    guard let v = value, v > 0 else { return "—" }
    return String(format: "%.4f", v)
}

private func activityMoneyText(_ value: Double?) -> String {
    guard let v = value, v.isFinite else { return "—" }
    return String(format: "%@$%.4f", v >= 0 ? "+" : "", v)
}

private func activityAgeText(_ value: String?) -> String {
    guard let v = value, !v.isEmpty else { return "—" }
    return String(v.prefix(19))
}

struct ActivityView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = ActivityViewModel()
    @State private var searchText = ""
    @State private var selectedWindow: ActivityWindow = .oneWeek
    @State private var selectedFilter: ActivityFilter = .all

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && !vm.hasAnyData {
                    loadingSkeleton
                } else if let err = vm.error, !vm.hasAnyData {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    activityContent
                }
            }
            .nerVyxScreen()
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
                    .disabled(vm.isLoading)
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Loading skeleton (redacted replica)

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 14) {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel)
                    .frame(height: 150)
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel)
                    .frame(height: 220)
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel)
                    .frame(height: 130)
                ForEach(0..<4, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(NerVyx.panel)
                        .frame(height: 72)
                }
            }
            .padding(16)
            .redacted(reason: .placeholder)
        }
        .scrollDisabled(true)
    }

    // MARK: - Content

    private var activityContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                heroCard
                windowSelector
                chartsCard
                backendWindowsCard
                filterChips
                tradesSection
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Freshness truth

    private var freshnessChip: StalenessChip {
        if !vm.hasAnyData {
            return .offline()
        }
        let age = vm.ageSeconds
        let stale = vm.envelopeStale || (age ?? 0) > 90
        return StalenessChip.from(
            stale: stale,
            lagMs: vm.envelopeLagMs,
            transport: vm.envelopeTransport,
            ageSeconds: age
        )
    }

    // MARK: - Hero summary

    private var backendSelected: PnLWindow? { vm.backendWindow(for: selectedWindow) }

    private var derivedSelected: ActivityWindowStats { vm.stats(for: selectedWindow) }

    /// Backend NET realized PnL when the rollup exists; derived row sum otherwise.
    private var heroValue: Double? {
        if let backend = backendSelected, let realized = backend.realized_pnl_usd {
            return realized
        }
        if selectedWindow == .all, let allRealized = vm.backendRealizedAllUsd {
            return allRealized
        }
        let derived = derivedSelected
        return derived.tradeCount > 0 ? derived.realizedSum : nil
    }

    private var heroIsBackend: Bool {
        if backendSelected?.realized_pnl_usd != nil { return true }
        if selectedWindow == .all && vm.backendRealizedAllUsd != nil { return true }
        return false
    }

    private var heroTradeCount: Int? {
        if let backend = backendSelected, let count = backend.closed_trade_count {
            return count
        }
        let derived = derivedSelected
        return derived.tradeCount > 0 || selectedWindow == .all ? derived.tradeCount : nil
    }

    /// Winner-flag win rate only — never recomputed from sign(pnl).
    private var winRateText: String {
        if let backend = backendSelected, let rate = backend.win_rate {
            return NerVyxFormat.percent(rate)
        }
        if selectedWindow == .all, let pct = vm.backendWinRatePct {
            return String(format: "%.1f%%", pct)
        }
        return "—"
    }

    private var winRateValue: Double? {
        if let backend = backendSelected, let rate = backend.win_rate { return rate }
        if selectedWindow == .all, let pct = vm.backendWinRatePct { return pct / 100 }
        return nil
    }

    private var profitFactorText: String {
        NerVyxFormat.number(backendSelected?.profit_factor)
    }

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                MicroLabel(text: "REALIZED PNL · \(selectedWindow.rawValue)")
                Spacer()
                freshnessChip
                NerVyxBadge(
                    text: NervyxBrand.liveBlockedLabel.uppercased(),
                    color: NerVyx.sell,
                    small: true
                )
            }
            HeroMetricText(
                text: NerVyxFormat.money(heroValue, decimals: 2, signed: true),
                color: heroValue.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted
            )
            MicroLabel(
                text: heroIsBackend
                    ? "BACKEND NET · WINNER-FLAG WIN RATE"
                    : "DERIVED FROM CLOSED-TRADE ROWS",
                size: 9
            )
            HStack(spacing: 8) {
                StatChip(
                    label: "TRADES",
                    value: NerVyxFormat.count(heroTradeCount),
                    color: NerVyx.textPrimary
                )
                StatChip(
                    label: "WIN RATE",
                    value: winRateText,
                    color: winRateValue.map { $0 >= 0.5 ? NerVyx.validation : NerVyx.warning } ?? NerVyx.textMuted,
                    accent: NerVyx.inference
                )
                StatChip(
                    label: "PF",
                    value: profitFactorText,
                    color: (backendSelected?.profit_factor ?? 0) >= 1 && backendSelected?.profit_factor != nil
                        ? NerVyx.validation
                        : NerVyx.textSecondary,
                    accent: NerVyx.primary
                )
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: heroValue.map { NerVyx.pnlColor($0) } ?? NerVyx.borderSubtle)
    }

    // MARK: - Window selector

    private var windowSelector: some View {
        HStack(spacing: 8) {
            ForEach(ActivityWindow.allCases) { window in
                Button {
                    withAnimation(.default) { selectedWindow = window }
                } label: {
                    Text(window.rawValue)
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .foregroundStyle(selectedWindow == window ? NerVyx.bg : NerVyx.textSecondary)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 7)
                        .background(selectedWindow == window ? NerVyx.signal : NerVyx.panel.opacity(0.6))
                        .clipShape(Capsule())
                        .overlay(
                            Capsule().stroke(
                                selectedWindow == window ? NerVyx.signal : NerVyx.borderSubtle,
                                lineWidth: 1
                            )
                        )
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
    }

    // MARK: - Charts (derived from closed-trade rows)

    private var chartsCard: some View {
        let stats = derivedSelected
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionHeader(
                    title: stats.bucketUnit == "HOUR" ? "PnL by Hour" : "PnL by Day",
                    accent: NerVyx.primary
                )
                Spacer()
                MicroLabel(text: "DERIVED · CLOSED-TRADE ROWS", size: 9)
            }
            if stats.tradeCount == 0 {
                Text("No closed trades in the \(selectedWindow.rawValue) window.")
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 20)
            } else {
                DivergingBars(values: stats.buckets, height: 84)
                NerVyxDivider()
                MicroLabel(text: "CUMULATIVE REALIZED · \(selectedWindow.rawValue)")
                AxisSparkline(
                    values: stats.cumulative,
                    color: (stats.cumulative.last ?? 0) >= 0 ? NerVyx.buy : NerVyx.sell,
                    height: 80,
                    valueFormatter: { NerVyxFormat.money($0, decimals: 2, signed: true) }
                )
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: - Backend NET window rollups

    private var backendWindowsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                SectionHeader(title: "PnL Windows", accent: NerVyx.inference)
                Spacer()
                MicroLabel(text: "BACKEND NET · WINNER-FLAG", size: 9)
            }
            if vm.pnlWindows.isEmpty {
                Text("Backend window rollups unavailable.")
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.vertical, 10)
            } else {
                ForEach(Array(vm.pnlWindows.enumerated()), id: \.element.id) { index, window in
                    backendWindowRow(window)
                    if index < vm.pnlWindows.count - 1 {
                        NerVyxDivider()
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    private func backendWindowRow(_ window: PnLWindow) -> some View {
        HStack(spacing: 10) {
            Text(window.window.uppercased())
                .font(.system(size: 12, weight: .heavy, design: .monospaced))
                .foregroundStyle(NerVyx.textSecondary)
                .frame(width: 36, alignment: .leading)
            Text(NerVyxFormat.money(window.realized_pnl_usd, decimals: 2, signed: true))
                .font(.system(size: 13, weight: .bold, design: .monospaced))
                .foregroundStyle(
                    window.realized_pnl_usd.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted
                )
                .lineLimit(1)
            Spacer()
            MicroLabel(text: "WIN", size: 9)
            Text(NerVyxFormat.percent(window.win_rate))
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(
                    window.win_rate.map { $0 >= 0.5 ? NerVyx.validation : NerVyx.warning } ?? NerVyx.textMuted
                )
            MicroLabel(text: "PF", size: 9)
            Text(NerVyxFormat.number(window.profit_factor))
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(NerVyx.textSecondary)
            MicroLabel(text: "N", size: 9)
            Text(NerVyxFormat.count(window.closed_trade_count))
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(NerVyx.textSecondary)
        }
    }

    // MARK: - Filter chips (PnL-sign labels — winner flags not in row payload)

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(ActivityFilter.allCases) { filter in
                    Button {
                        withAnimation(.default) { selectedFilter = filter }
                    } label: {
                        Text(filter.rawValue)
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(selectedFilter == filter ? NerVyx.bg : NerVyx.textSecondary)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(chipBackground(for: filter))
                            .clipShape(Capsule())
                            .overlay(
                                Capsule().stroke(
                                    selectedFilter == filter ? chipAccent(for: filter) : NerVyx.borderSubtle,
                                    lineWidth: 1
                                )
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 2)
        }
    }

    private func chipAccent(for filter: ActivityFilter) -> Color {
        switch filter {
        case .all:         return NerVyx.primary
        case .long:        return NerVyx.buy
        case .short:       return NerVyx.sell
        case .pnlPositive: return NerVyx.buy
        case .pnlNegative: return NerVyx.sell
        }
    }

    private func chipBackground(for filter: ActivityFilter) -> Color {
        selectedFilter == filter ? chipAccent(for: filter) : NerVyx.panel.opacity(0.6)
    }

    // MARK: - Trades list

    private var visibleTrades: [MobilePosition] {
        var rows = vm.trades(in: selectedWindow)
        switch selectedFilter {
        case .all:         break
        case .long:        rows = rows.filter { $0.isBuy }
        case .short:       rows = rows.filter { !$0.isBuy }
        case .pnlPositive: rows = rows.filter { $0.realized_pnl > 0 }
        case .pnlNegative: rows = rows.filter { $0.realized_pnl < 0 }
        }
        if !searchText.isEmpty {
            rows = rows.filter { $0.symbol.localizedCaseInsensitiveContains(searchText) }
        }
        return rows
    }

    @ViewBuilder
    private var tradesSection: some View {
        if vm.closedTrades.isEmpty {
            emptyState
        } else if visibleTrades.isEmpty {
            VStack(spacing: 8) {
                Image(systemName: "line.3.horizontal.decrease.circle")
                    .font(.system(size: 28))
                    .foregroundStyle(NerVyx.textMuted)
                Text("No closed trades match the current window and filters.")
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textMuted)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 24)
            .nerVyxGlassCard()
        } else {
            tradesList
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
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .nerVyxGlassCard()
    }

    private var tradesList: some View {
        VStack(spacing: 0) {
            HStack {
                SectionHeader(
                    title: "Closed Trades (\(visibleTrades.count))",
                    accent: NerVyx.primary
                )
                Spacer()
                Text(vm.streamLabel.uppercased())
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
            }
            .padding(.bottom, 6)

            ForEach(visibleTrades) { trade in
                NavigationLink(destination: PositionDetailView(position: trade)) {
                    ActivityTradeRow(trade: trade)
                }
                .buttonStyle(.plain)
                if trade.id != visibleTrades.last?.id {
                    NerVyxDivider()
                }
            }
        }
        .nerVyxGlassCard()
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
                        .contentTransition(.numericText())
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
        .padding(.vertical, 10)
        .contentShape(Rectangle())
    }
}
