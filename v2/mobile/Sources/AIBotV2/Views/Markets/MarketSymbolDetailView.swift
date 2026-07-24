import SwiftUI
import Observation

// MARK: - Market symbol detail (/api/v2/market/{symbol})
//
// Compact tap-through sheet for one symbol: price/funding/orderbook/long-short/
// liquidation/regime/altdata blocks straight from the enriched detail endpoint.
// HTTP poll @10s (honest POLL chip); heavy blocks (216-indicator ta_1m, raw
// liquidation ladder) are intentionally not decoded on mobile.
//
// Read-only telemetry. Live trading stays operator-gated (blocked_human_only).

@MainActor
@Observable
final class MarketSymbolDetailViewModel {
    let symbol: String

    private(set) var response: MarketSymbolDetailResponse?
    private(set) var isLoading = false
    private(set) var error: String?
    private var pollTask: Task<Void, Never>?

    init(symbol: String) {
        self.symbol = symbol
    }

    var detail: MarketSymbolDetailData? { response?.data }

    var isStale: Bool {
        if response?.stale == true { return true }
        let status = (response?.freshness_status ?? "").lowercased()
        if status == "stale" || status == "unavailable" { return true }
        return false
    }

    var liveGateLabel: String {
        nervyxPublicRuntimeText(response?.live_gate ?? "blocked_human_only")
    }

    func start(token: String?, baseURL: String) {
        stop()
        pollTask = Task {
            while !Task.isCancelled {
                await load(token: token, baseURL: baseURL)
                try? await Task.sleep(for: .seconds(10))
            }
        }
    }

    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    func load(token: String?, baseURL: String) async {
        isLoading = response == nil
        do {
            let resp: MarketSymbolDetailResponse = try await APIClient.shared.get(
                path: APIEndpoints.marketDetail(symbol: symbol),
                token: token,
                baseURL: baseURL
            )
            response = resp
            error = nil
        } catch {
            if response == nil { self.error = error.localizedDescription }
        }
        isLoading = false
    }
}

struct MarketSymbolDetailView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm: MarketSymbolDetailViewModel

    init(symbol: String) {
        _vm = State(initialValue: MarketSymbolDetailViewModel(symbol: symbol))
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                if vm.isLoading && vm.detail == nil {
                    loadingSkeleton
                } else if let err = vm.error, vm.detail == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else if let d = vm.detail {
                    headerCard(d)
                    fundingCard(d)
                    longShortCard(d)
                    orderbookCard(d)
                    liquidationCard(d)
                    taRegimeCard(d)
                    altdataCard(d)
                    provenanceCard(d)
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .nerVyxScreen()
        .navigationTitle(vm.symbol)
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { vm.start(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stop() }
    }

    // MARK: - Freshness truth

    private var freshnessChip: StalenessChip {
        guard vm.response != nil else { return .offline() }
        return StalenessChip.from(
            stale: vm.isStale,
            lagMs: vm.response?.lag_ms,
            transport: "http",
            ageSeconds: vm.response?.staleness_seconds
        )
    }

    // MARK: - Header (price + changes)

    private func headerCard(_ d: MarketSymbolDetailData) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                SectionHeader(title: "Price", accent: NerVyx.signal)
                Spacer()
                freshnessChip
                NerVyxBadge(text: vm.liveGateLabel, color: NerVyx.sell, small: true)
            }
            HeroMetricText(
                text: marketPriceText(d.last_price),
                color: d.change_24h.map { NerVyx.pnlColor($0) } ?? NerVyx.textPrimary
            )
            HStack(spacing: 10) {
                changeChip("1H", d.change_1h)
                changeChip("4H", d.change_4h)
                changeChip("24H", d.change_24h)
                changeChip("7D", d.change_7d)
                Spacer(minLength: 0)
            }
            NerVyxDivider()
            DataRow(label: "Mark / Index", value: "\(marketPriceText(d.mark_price)) / \(marketPriceText(d.index_price))", mono: true)
            DataRow(label: "24h high / low", value: "\(marketPriceText(d.high_24h)) / \(marketPriceText(d.low_24h))", mono: true)
            DataRow(label: "24h volume (base)", value: NerVyxFormat.number(d.volume_24h, decimals: 2), mono: true)
            DataRow(label: "24h turnover", value: NerVyxFormat.compactUSD(d.turnover_24h), mono: true)
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    private func changeChip(_ label: String, _ fraction: Double?) -> some View {
        VStack(spacing: 2) {
            MicroLabel(text: label, size: 9)
            Text(signedPercentText(fraction))
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(fraction.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted)
        }
    }

    // MARK: - Funding

    private func fundingCard(_ d: MarketSymbolDetailData) -> some View {
        let f = d.funding_detail
        return VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Funding & Basis", accent: NerVyx.inference)
            DataRow(
                label: "Funding rate",
                value: signedPercentText(f?.funding_rate ?? d.funding_rate, decimals: 4),
                valueColor: fundingColor(f?.funding_rate ?? d.funding_rate),
                mono: true
            )
            DataRow(label: "Next funding", value: f?.next_funding_time ?? d.next_funding_time ?? "—", mono: true)
            DataRow(
                label: "Basis (mark vs index)",
                value: bpsText(f?.basis_bps ?? d.basis_bps),
                valueColor: (f?.basis_bps ?? d.basis_bps).map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted,
                mono: true
            )
            DataRow(label: "Est. settle price", value: marketPriceText(f?.estimated_settle_price), mono: true)
            DataRow(label: "Open interest", value: NerVyxFormat.number(d.open_interest, decimals: 2), mono: true)
            DataRow(
                label: "OI Δ1h (USD)",
                value: NerVyxFormat.compactUSD(d.open_interest_delta_1h_usd),
                valueColor: d.open_interest_delta_1h_usd.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted,
                mono: true
            )
            if let cg = d.coinglass {
                DataRow(label: "Coinglass OI", value: NerVyxFormat.compactUSD(cg.open_interest_usd), mono: true)
                DataRow(label: "Funding z-score", value: NerVyxFormat.number(cg.funding_rate_zscore, decimals: 2), mono: true)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: - Long / short

    @ViewBuilder
    private func longShortCard(_ d: MarketSymbolDetailData) -> some View {
        if let ls = d.long_short {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(
                    title: "Long / Short Accounts",
                    accent: NerVyx.primary,
                    trailing: ls.period.map { "period \($0)" }
                )
                if let long = ls.long_account_ratio, let short = ls.short_account_ratio {
                    SplitBar(leftValue: long, rightValue: short)
                }
                DataRow(label: "Long/short ratio", value: NerVyxFormat.number(ls.long_short_ratio, decimals: 4), mono: true)
                if let fetched = ls.fetched_utc {
                    DataRow(label: "Upstream fetched", value: fetched, mono: true)
                }
            }
            .nerVyxGlassCard(accent: NerVyx.primary)
        }
    }

    // MARK: - Orderbook

    @ViewBuilder
    private func orderbookCard(_ d: MarketSymbolDetailData) -> some View {
        if let ob = d.orderbook {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader(title: "Orderbook", accent: NerVyx.paper)
                DataRow(label: "Best bid", value: marketPriceText(ob.best_bid), valueColor: NerVyx.buy, mono: true)
                DataRow(label: "Best ask", value: marketPriceText(ob.best_ask), valueColor: NerVyx.sell, mono: true)
                DataRow(label: "Spread", value: bpsText(ob.spread_bps ?? d.spread_bps), mono: true)
                DataRow(
                    label: "Depth imbalance",
                    value: NerVyxFormat.number(ob.depth_imbalance ?? d.orderbook_imbalance, decimals: 3),
                    valueColor: (ob.depth_imbalance ?? d.orderbook_imbalance).map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted,
                    mono: true
                )
                DataRow(label: "Depth20 bid / ask", value: "\(NerVyxFormat.compactUSD(ob.depth_20_bid_usd)) / \(NerVyxFormat.compactUSD(ob.depth_20_ask_usd))", mono: true)
                DataRow(label: "Est. price impact", value: bpsText(ob.estimated_price_impact_bps ?? d.estimated_price_impact_bps), mono: true)
            }
            .nerVyxGlassCard(accent: NerVyx.paper)
        }
    }

    // MARK: - Liquidations

    private func liquidationCard(_ d: MarketSymbolDetailData) -> some View {
        let risk = d.liquidation_levels?.liquidation_cascade_risk ?? d.liquidation_cascade_risk
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                SectionHeader(title: "Liquidations", accent: NerVyx.sell)
                Spacer()
                if let risk {
                    NerVyxBadge(
                        text: "CASCADE \(NerVyxFormat.percent(risk, decimals: 0))",
                        color: cascadeColor(risk),
                        small: true
                    )
                }
            }
            DataRow(label: "Dist. to long liq", value: bpsText(d.distance_to_long_liq_bps), mono: true)
            DataRow(label: "Dist. to short liq", value: bpsText(d.distance_to_short_liq_bps), mono: true)
            DataRow(label: "Dist. to nearest liq", value: bpsText(d.distance_to_nearest_liq_bps), mono: true)
            DataRow(label: "Liq notional 1h", value: NerVyxFormat.compactUSD(d.liq_notional_1h), mono: true)
            DataRow(label: "Liq count 1h", value: NerVyxFormat.count(d.liq_count_1h), mono: true)
            DataRow(
                label: "Direction bias 1h",
                value: NerVyxFormat.number(d.liq_direction_bias_1h, decimals: 2),
                valueColor: d.liq_direction_bias_1h.map { NerVyx.pnlColor($0) } ?? NerVyx.textMuted,
                mono: true
            )
            if let lv = d.liquidation_levels {
                DataRow(label: "Levels long / short", value: "\(NerVyxFormat.count(lv.levels_count_long)) / \(NerVyxFormat.count(lv.levels_count_short))", mono: true)
                DataRow(label: "Sweep target short", value: marketPriceText(lv.sweep_target_short), mono: true)
                DataRow(label: "Sweep target long", value: marketPriceText(lv.sweep_target_long), mono: true)
                if let semantics = lv.cascade_risk_semantics {
                    DataRow(label: "Risk semantics", value: semantics, mono: true)
                }
            }
            if let en = d.liquidation_enhanced {
                NerVyxDivider()
                DataRow(label: "Cascade probability", value: NerVyxFormat.percent(en.cascade_probability, decimals: 1), mono: true)
                DataRow(label: "Predicted long zone", value: marketPriceText(en.predicted_long_liq_zone), mono: true)
                DataRow(label: "Predicted short zone", value: marketPriceText(en.predicted_short_liq_zone), mono: true)
                DataRow(label: "Market stress", value: NerVyxFormat.percent(en.market_stress_indicator, decimals: 1), mono: true)
                if en.synthetic_data == true {
                    DataRow(label: "Synthetic data", value: "YES", valueColor: NerVyx.warning, mono: true)
                }
            }
        }
        .nerVyxGlassCard(accent: NerVyx.sell)
    }

    // MARK: - TA + regime

    private func taRegimeCard(_ d: MarketSymbolDetailData) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "TA & Regime (1m closed)", accent: NerVyx.validation)
            HStack(spacing: 10) {
                metricPill("RSI", NerVyxFormat.number(d.rsi_1m, decimals: 1))
                metricPill("ATR", NerVyxFormat.number(d.atr_1m, decimals: 4))
                metricPill("ADX", NerVyxFormat.number(d.adx_1m, decimals: 1))
                Spacer(minLength: 0)
            }
            if let trend = d.htf_trend {
                DataRow(label: "HTF trend", value: trend, valueColor: trendColor(trend), mono: true)
            }
            DataRow(label: "RSI zone", value: d.rsi_zone ?? "—", mono: true)
            DataRow(label: "MACD direction", value: d.macd_direction ?? "—", mono: true)
            if let regime = d.regime_1m {
                DataRow(label: "Regime", value: regime.regime ?? "—", mono: true)
                DataRow(label: "Regime confidence", value: NerVyxFormat.percent(regime.confidence, decimals: 0), mono: true)
                DataRow(label: "Risk state", value: nervyxPublicRuntimeText(regime.market_risk_state ?? "—"), mono: true)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.validation)
    }

    private func metricPill(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            MicroLabel(text: label, size: 9)
            Text(value)
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(NerVyx.textPrimary)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(NerVyx.panel.opacity(0.6))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }

    // MARK: - Altdata / flow

    private func altdataCard(_ d: MarketSymbolDetailData) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Altdata & Flow", accent: NerVyx.paper)
            DataRow(label: "Symbol score", value: NerVyxFormat.number(d.altdata_symbol_score, decimals: 3), mono: true)
            DataRow(label: "Symbol rank", value: NerVyxFormat.count(d.altdata_symbol_rank), mono: true)
            DataRow(label: "CoinAnk deriv score", value: NerVyxFormat.number(d.coinank_derivatives_score, decimals: 3), mono: true)
            DataRow(label: "Market cap rank", value: NerVyxFormat.count(d.market_cap_rank), mono: true)
            DataRow(label: "Market cap", value: NerVyxFormat.compactUSD(d.market_cap_usd), mono: true)
            if let taker = d.taker_buy_ratio {
                NerVyxDivider()
                MicroLabel(text: "Taker flow (quote-weighted)", size: 9)
                SplitBar(leftValue: taker, rightValue: max(1 - taker, 0), leftLabel: "BUY", rightLabel: "SELL")
                DataRow(label: "Taker flow trades", value: NerVyxFormat.count(d.taker_flow_trade_count), mono: true)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.paper)
    }

    // MARK: - Provenance (source honesty)

    private func provenanceCard(_ d: MarketSymbolDetailData) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Provenance", accent: NerVyx.borderStrong)
            DataRow(label: "Exchange", value: vm.response?.exchange ?? "—", mono: true)
            DataRow(label: "Mode", value: vm.response?.mode ?? "—", mono: true)
            DataRow(label: "Freshness", value: vm.response?.freshness_status ?? "—", mono: true)
            DataRow(label: "Data quality", value: vm.response?.data_quality_status ?? "—", mono: true)
            DataRow(label: "Generated", value: vm.response?.generated_at_utc ?? "—", mono: true)
            if let missing = vm.response?.missing_fields, !missing.isEmpty {
                Text("Missing: \(missing.joined(separator: ", "))")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(NerVyx.warning)
                    .lineLimit(3)
            }
            if let warnings = vm.response?.warnings, !warnings.isEmpty {
                ForEach(warnings.prefix(4), id: \.self) { warning in
                    Text("• \(warning)")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(2)
                }
            }
            if let source = vm.response?.source {
                Text(source)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(3)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.borderSubtle)
    }

    // MARK: - Helpers

    private func bpsText(_ value: Double?) -> String {
        guard let value, value.isFinite else { return "—" }
        return String(format: "%.2f bps", value)
    }

    private var loadingSkeleton: some View {
        VStack(spacing: 14) {
            ForEach(0..<5, id: \.self) { _ in
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(NerVyx.panel).frame(height: 140)
            }
        }
        .redacted(reason: .placeholder)
    }
}
