import SwiftUI

// MARK: - Markets ("NERVYX CORE > Markets")
//
// Website Markets-page parity on mobile, backed by the compact enriched list:
//   GET /api/v2/mobile/markets  (WS stream @10s + HTTP fallback)
//   -> MobileMarketsResponse.markets: [MobileMarketRow]
//
//   - stat strip: symbols / gainers / losers / watchlist counts + freshness
//     truth (StalenessChip) + OPERATOR GATED live-gate badge
//   - 4 segmented tabs (All / Gainers / Losers / Watchlist), symbol search,
//     sort menu (turnover default, 24h %, cascade risk, altdata score, symbol)
//   - per-symbol rows: price, 24h/1h change, funding, OI delta, cascade risk,
//     RSI, HTF trend, altdata score, star watchlist toggle (device-local)
//   - tap-through to MarketSymbolDetailView (/api/v2/market/{symbol})
//
// Read-only telemetry. Live trading stays operator-gated (blocked_human_only).

struct MarketsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = MarketsViewModel()

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
                    content
                }
            }
            .nerVyxScreen()
            .navigationTitle("MARKETS")
            .navigationBarTitleDisplayMode(.large)
            .searchable(text: $vm.searchText, prompt: "Filter by symbol")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) { sortMenu }
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

    // MARK: - Toolbar sort menu

    private var sortMenu: some View {
        Menu {
            ForEach(MarketsViewModel.SortKey.allCases, id: \.rawValue) { key in
                Button {
                    if vm.sortKey == key {
                        vm.sortDescending.toggle()
                    } else {
                        vm.sortKey = key
                        // Numeric metrics read best descending; symbol reads A→Z.
                        vm.sortDescending = key != .symbol
                    }
                } label: {
                    if vm.sortKey == key {
                        Label(key.rawValue, systemImage: vm.sortDescending ? "chevron.down" : "chevron.up")
                    } else {
                        Text(key.rawValue)
                    }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.up.arrow.down")
                Text(vm.sortKey.rawValue)
                    .font(.system(size: 12, weight: .semibold))
            }
            .foregroundStyle(NerVyx.signal)
        }
    }

    // MARK: - Freshness truth

    private var freshnessChip: StalenessChip {
        guard vm.hasAnyData else { return .offline() }
        return StalenessChip.from(
            stale: vm.isStale,
            lagMs: vm.envelopeLagMs,
            transport: vm.envelopeTransport,
            ageSeconds: vm.stalenessAgeSeconds
        )
    }

    // MARK: - Content

    private var content: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                statStrip
                tabPicker
                if vm.displayedRows.isEmpty {
                    emptyState
                } else {
                    ForEach(vm.displayedRows) { row in
                        NavigationLink {
                            MarketSymbolDetailView(symbol: row.symbol)
                        } label: {
                            marketRow(row)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private var statStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                freshnessChip
                StatChip(label: "Symbols", value: "\(vm.symbolCount)", color: NerVyx.textSecondary, accent: NerVyx.signal)
                StatChip(label: "Gainers", value: "\(vm.gainerCount)", color: NerVyx.buy, accent: NerVyx.buy)
                StatChip(label: "Losers", value: "\(vm.loserCount)", color: NerVyx.sell, accent: NerVyx.sell)
                StatChip(label: "Watch", value: "\(vm.watchlistCount)", color: NerVyx.warning, accent: NerVyx.warning)
                NerVyxBadge(text: vm.liveGateLabel, color: NerVyx.sell, small: true)
            }
            .padding(.horizontal, 2)
        }
    }

    private var tabPicker: some View {
        Picker("Tab", selection: $vm.tab) {
            ForEach(MarketsViewModel.MarketsTab.allCases, id: \.rawValue) { tab in
                Text(tab.rawValue).tag(tab)
            }
        }
        .pickerStyle(.segmented)
    }

    // MARK: - Row

    private func marketRow(_ row: MobileMarketRow) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(row.shortSymbol)
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(NerVyx.textPrimary)
                        if let rank = row.market_cap_rank {
                            Text("#\(rank)")
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                                .foregroundStyle(NerVyx.textMuted)
                        }
                        if let trend = row.htf_trend, !trend.isEmpty {
                            NerVyxBadge(text: trend, color: trendColor(trend), small: true)
                        }
                    }
                    Text(fundingText(row.funding_rate))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(fundingColor(row.funding_rate))
                }
                Spacer(minLength: 6)
                VStack(alignment: .trailing, spacing: 4) {
                    Text(marketPriceText(row.last_price))
                        .font(.system(size: 15, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.textPrimary)
                    HStack(spacing: 6) {
                        changeText("1h", row.change_1h)
                        changeText("24h", row.change_24h)
                    }
                }
                Button {
                    vm.toggleWatchlist(row.symbol)
                } label: {
                    Image(systemName: vm.isWatched(row.symbol) ? "star.fill" : "star")
                        .font(.system(size: 15))
                        .foregroundStyle(vm.isWatched(row.symbol) ? NerVyx.warning : NerVyx.textMuted)
                }
                .buttonStyle(.borderless)
            }

            HStack(spacing: 8) {
                metricChip("TURNOVER", NerVyxFormat.compactUSD(row.turnover_24h_usd), NerVyx.textSecondary)
                metricChip("OI Δ1H", NerVyxFormat.compactUSD(row.open_interest_delta_1h_usd),
                           row.open_interest_delta_1h_usd.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted)
                metricChip("CASCADE", NerVyxFormat.percent(row.liquidation_cascade_risk, decimals: 0),
                           cascadeColor(row.liquidation_cascade_risk))
                metricChip("RSI 1M", NerVyxFormat.number(row.rsi_1m, decimals: 0), NerVyx.textSecondary)
                metricChip("SCORE", NerVyxFormat.number(row.altdata_symbol_score, decimals: 2), NerVyx.paper)
                Spacer(minLength: 0)
            }
        }
        .nerVyxGlassCard(accent: rowAccent(row))
    }

    private func metricChip(_ label: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            MicroLabel(text: label, size: 9)
            Text(value)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
                .lineLimit(1)
        }
    }

    private func changeText(_ label: String, _ fraction: Double?) -> some View {
        HStack(spacing: 2) {
            Text(label)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(NerVyx.textMuted)
            Text(signedPercentText(fraction))
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(fraction.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted)
        }
    }

    private func rowAccent(_ row: MobileMarketRow) -> Color {
        guard let change = row.change_24h else { return NerVyx.borderSubtle }
        return NerVyx.pnlColor(change).opacity(0.7)
    }

    // MARK: - Empty state

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: vm.tab == .watchlist ? "star" : "chart.bar.xaxis")
                .font(.system(size: 26))
                .foregroundStyle(NerVyx.textMuted)
            Text(emptyStateText)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(28)
        .nerVyxGlassCard()
    }

    private var emptyStateText: String {
        if !vm.searchText.trimmingCharacters(in: .whitespaces).isEmpty {
            return "No symbols match the current filter."
        }
        switch vm.tab {
        case .watchlist: return "No watched symbols yet — tap the star on any row to pin it here."
        case .gainers: return "No symbols with a positive 24h change right now."
        case .losers: return "No symbols with a negative 24h change right now."
        case .overview: return "No market rows published yet."
        }
    }

    // MARK: - Loading skeleton

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 12) {
                HStack(spacing: 8) {
                    ForEach(0..<4, id: \.self) { _ in
                        Capsule().fill(NerVyx.panel).frame(width: 76, height: 24)
                    }
                    Spacer()
                }
                RoundedRectangle(cornerRadius: 8).fill(NerVyx.panel).frame(height: 32)
                ForEach(0..<6, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(NerVyx.panel).frame(height: 104)
                }
            }
            .padding(16)
            .redacted(reason: .placeholder)
        }
        .scrollDisabled(true)
    }
}

// MARK: - Shared market formatting helpers (markets + detail)

/// Adaptive decimals: fewer for large prices, more for sub-dollar.
func marketPriceText(_ price: Double?) -> String {
    guard let price, price.isFinite else { return "—" }
    if abs(price) >= 1_000 { return String(format: "%.2f", price) }
    if abs(price) >= 1 { return String(format: "%.4f", price) }
    return String(format: "%.6f", price)
}

/// Signed percent from a fraction (0.0123 -> "+1.23%").
func signedPercentText(_ fraction: Double?, decimals: Int = 2) -> String {
    guard let fraction, fraction.isFinite else { return "—" }
    return String(format: "%+.\(decimals)f%%", fraction * 100)
}

/// Funding fraction rendered at funding precision (2.9e-05 -> "FND +0.0029%").
func fundingText(_ rate: Double?) -> String {
    guard let rate, rate.isFinite else { return "FND —" }
    return String(format: "FND %+.4f%%", rate * 100)
}

func fundingColor(_ rate: Double?) -> Color {
    guard let rate else { return NerVyx.textMuted }
    return rate >= 0 ? NerVyx.buy : NerVyx.sell
}

/// Cascade-risk intensity percentile: amber above 0.7, red above 0.9.
func cascadeColor(_ risk: Double?) -> Color {
    guard let risk else { return NerVyx.textMuted }
    if risk >= 0.9 { return NerVyx.sell }
    if risk >= 0.7 { return NerVyx.warning }
    return NerVyx.textSecondary
}

func trendColor(_ trend: String) -> Color {
    switch trend.uppercased() {
    case "UP": return NerVyx.buy
    case "DOWN": return NerVyx.sell
    default: return NerVyx.neutral
    }
}
