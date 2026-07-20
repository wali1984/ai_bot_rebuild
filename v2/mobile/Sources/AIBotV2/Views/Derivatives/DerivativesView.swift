import SwiftUI

// MARK: - Derivatives ("NERVYX CORE > Derivatives")
//
// Website Derivatives-page parity on mobile, backed by the compact rollup:
//   GET /api/v2/mobile/derivatives-summary  (WS stream @10s + HTTP fallback)
//   -> MobileDerivativesSummary (aggregate, global_regime, top symbols by OI)
//
//   - aggregate band: total OI hero, 24h liquidations, avg funding,
//     aggregate long-vs-short SplitBar, funding +/- symbol counts
//   - global regime card: market sentiment gauge, volume, data status + age
//   - per-symbol rows (top by OI): mark price, signed funding HBarRow,
//     OI, long/short ratio, basis bps, cascade risk
//
// Funding sign colors are NerVyx.buy/sell only. Freshness truth via the
// shared StalenessChip. Live trading stays operator-gated (blocked_human_only).

struct DerivativesView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DerivativesViewModel()

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
            .navigationTitle("DERIVATIVES")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.inference)
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
            LazyVStack(spacing: 14) {
                statStrip
                aggregateCard
                regimeCard
                symbolsCard
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private var statStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                freshnessChip
                StatChip(
                    label: "Symbols",
                    value: "\(vm.response?.symbol_count ?? vm.topSymbols.count)",
                    color: NerVyx.textSecondary,
                    accent: NerVyx.inference
                )
                if let updated = vm.lastUpdated {
                    StatChip(label: "As of", value: updated, color: NerVyx.textMuted, accent: NerVyx.borderStrong)
                }
                NerVyxBadge(text: vm.liveGateLabel, color: NerVyx.sell, small: true)
            }
            .padding(.horizontal, 2)
        }
    }

    // MARK: - Aggregate

    private var aggregateCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Aggregate Derivatives", accent: NerVyx.inference)
            HStack(alignment: .top, spacing: 14) {
                VStack(alignment: .leading, spacing: 3) {
                    MicroLabel(text: "Total open interest", size: 9)
                    HeroMetricText(text: NerVyxFormat.compactUSD(vm.aggregate?.total_oi_usd), size: 32)
                }
                Spacer(minLength: 0)
            }
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                MetricCard(
                    title: "Liquidations 24h",
                    value: NerVyxFormat.compactUSD(vm.aggregate?.total_liq_24h),
                    icon: "flame"
                )
                MetricCard(
                    title: "Avg funding",
                    value: signedPercentText(vm.aggregate?.avg_funding, decimals: 4),
                    valueColor: fundingColor(vm.aggregate?.avg_funding),
                    icon: "percent"
                )
            }
            if let ratio = vm.aggregate?.aggregate_long_short_ratio, ratio > 0 {
                VStack(alignment: .leading, spacing: 6) {
                    MicroLabel(text: "Aggregate long vs short (ratio \(NerVyxFormat.number(ratio, decimals: 2)))", size: 9)
                    SplitBar(leftValue: ratio, rightValue: 1)
                }
            }
            if let pos = vm.aggregate?.funding_positive_count, let neg = vm.aggregate?.funding_negative_count {
                MiniBarChart(entries: [
                    .init(label: "FND +", value: Double(pos), color: NerVyx.buy),
                    .init(label: "FND −", value: Double(neg), color: NerVyx.sell),
                ], height: 54)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: - Global regime

    @ViewBuilder
    private var regimeCard: some View {
        if let regime = vm.regime {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    title: "Global Regime",
                    accent: NerVyx.primary,
                    trailing: regime.data_status.map { nervyxPublicRuntimeText($0) }
                )
                HStack(alignment: .center, spacing: 16) {
                    RingGauge(
                        value: min(max(regime.market_sentiment ?? 0, 0), 1),
                        label: "SENTIMENT",
                        centerText: NerVyxFormat.percent(regime.market_sentiment, decimals: 0),
                        color: NerVyx.primary,
                        size: 88
                    )
                    VStack(alignment: .leading, spacing: 6) {
                        DataRow(label: "Volume", value: NerVyxFormat.compactUSD(regime.total_volume_usd), mono: true)
                        DataRow(label: "Liquidations", value: NerVyxFormat.compactUSD(regime.total_liquidations_usd), mono: true)
                        DataRow(
                            label: "Avg funding",
                            value: signedPercentText(regime.avg_funding_rate, decimals: 4),
                            valueColor: fundingColor(regime.avg_funding_rate),
                            mono: true
                        )
                        DataRow(label: "Feed age", value: NerVyxFormat.age(regime.age_seconds), mono: true)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .nerVyxGlassCard(accent: NerVyx.primary)
        }
    }

    // MARK: - Top symbols

    private var symbolsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(
                title: "Top Symbols by Open Interest",
                accent: NerVyx.signal,
                trailing: "\(vm.topSymbols.count)"
            )
            if vm.topSymbols.isEmpty {
                Text("No per-symbol derivatives rows published yet.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
            } else {
                ForEach(vm.topSymbols) { row in
                    symbolRow(row)
                    if row.id != vm.topSymbols.last?.id {
                        NerVyxDivider()
                    }
                }
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    private func symbolRow(_ row: DerivativesSymbolRow) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(row.shortSymbol)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(NerVyx.textPrimary)
                if let risk = row.cascade_risk {
                    NerVyxBadge(
                        text: "CASCADE \(NerVyxFormat.percent(risk, decimals: 0))",
                        color: cascadeColor(risk),
                        small: true
                    )
                }
                Spacer(minLength: 6)
                Text(marketPriceText(row.mark_price))
                    .font(.system(size: 13, weight: .bold, design: .monospaced))
                    .foregroundStyle(NerVyx.textPrimary)
            }
            if let funding = row.funding_rate {
                HBarRow(
                    label: "funding",
                    value: funding,
                    maxAbsValue: vm.maxAbsFunding,
                    valueText: signedPercentText(funding, decimals: 4),
                    signed: true,
                    labelWidth: 58,
                    barHeight: 6
                )
            }
            HStack(spacing: 12) {
                inlineStat("OI", NerVyxFormat.compactUSD(row.oi_usd))
                inlineStat("L/S", NerVyxFormat.number(row.long_short_ratio, decimals: 2))
                inlineStat("BASIS", row.basis_bps.map { String(format: "%+.1f bps", $0) } ?? "—")
                Spacer(minLength: 0)
            }
        }
        .padding(.vertical, 2)
    }

    private func inlineStat(_ label: String, _ value: String) -> some View {
        HStack(spacing: 4) {
            MicroLabel(text: label, size: 9)
            Text(value)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(NerVyx.textSecondary)
                .lineLimit(1)
        }
    }

    // MARK: - Loading skeleton

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 14) {
                HStack(spacing: 8) {
                    ForEach(0..<3, id: \.self) { _ in
                        Capsule().fill(NerVyx.panel).frame(width: 84, height: 24)
                    }
                    Spacer()
                }
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel).frame(height: 250)
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel).frame(height: 150)
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel).frame(height: 320)
            }
            .padding(16)
            .redacted(reason: .placeholder)
        }
        .scrollDisabled(true)
    }
}
