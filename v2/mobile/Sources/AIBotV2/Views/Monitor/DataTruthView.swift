import SwiftUI

// MARK: - Runtime data truth (orderbook feed coverage + book-trust semantics)
//
// Renders the two operator-runtime truth files that back the web operator
// pages but previously had no iOS surface:
//   • OrderbookRuntimeTruth  — direct Binance/KuCoin feed coverage, stale
//     symbols, sequence gaps, per-feed persistence truth, and which runtime
//     components actually consume the orderbook.
//   • MicrostructureTruth    — public-book trust semantics (default LOW,
//     trust cap, composite requirement), REDUCED_SIZE bootstrap tier, and
//     final A+ candidate truth.
//
// Honesty rules: ages derive from each payload's own generated_at stamp; an
// old truth file reads STALE. Nil fields render "—". Live gate stays red.

private func dtText(_ value: String?) -> String {
    guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return "—" }
    return nervyxPublicRuntimeText(value)
}

private func dtBool(_ value: Bool?) -> String {
    guard let value else { return "—" }
    return value ? "true" : "false"
}

struct DataTruthView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DataTruthViewModel()

    var body: some View {
        Group {
            if vm.isLoading && vm.orderbook == nil && vm.microstructure == nil {
                loadingReplica
            } else if vm.orderbook == nil && vm.microstructure == nil,
                      let err = vm.orderbookError ?? vm.microstructureError {
                ErrorStateView(message: err) {
                    Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                }
            } else {
                content
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .nerVyxScreen()
        .navigationTitle("Data Truth")
        .navigationBarTitleDisplayMode(.large)
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
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Loading replica

    private var loadingReplica: some View {
        ScrollView {
            VStack(spacing: 14) {
                ForEach(0..<2, id: \.self) { _ in
                    VStack(alignment: .leading, spacing: 10) {
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 28)
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 180)
                    }
                    .nerVyxGlassCard(accent: NerVyx.borderSubtle)
                }
            }
            .padding(16)
        }
        .redacted(reason: .placeholder)
        .allowsHitTesting(false)
    }

    // MARK: - Content

    private var content: some View {
        ScrollView {
            VStack(spacing: 14) {
                if let ob = vm.orderbook {
                    orderbookCard(ob)
                } else {
                    missingCard(
                        title: "Orderbook runtime truth",
                        message: vm.orderbookError ?? "Truth file not available"
                    )
                }
                if let micro = vm.microstructure {
                    microstructureCard(micro)
                } else {
                    missingCard(
                        title: "Microstructure trust",
                        message: vm.microstructureError ?? "Truth file not available"
                    )
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private func missingCard(title: String, message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: title, accent: NerVyx.warning)
            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .nerVyxGlassCard(accent: NerVyx.warning)
    }

    // MARK: - Orderbook runtime truth

    private func orderbookCard(_ ob: OrderbookRuntimeTruth) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Group {
                HStack {
                    SectionHeader(title: "Orderbook runtime truth", accent: NerVyx.signal)
                    StalenessChip.from(stale: vm.orderbookIsStale, ageSeconds: vm.orderbookAgeSeconds)
                }
                DataRow(label: "Generated", value: dtText(ob.generated_at), mono: true)
                DataRow(
                    label: "Direct Binance + KuCoin",
                    value: ob.direct_binance_kucoin_active ? "active" : "inactive",
                    valueColor: ob.direct_binance_kucoin_active ? NerVyx.validation : NerVyx.sell,
                    mono: true
                )
                DataRow(
                    label: "Binance · KuCoin",
                    value: "\(dtBool(ob.direct_binance_active)) · \(dtBool(ob.direct_kucoin_active))",
                    mono: true
                )
                DataRow(
                    label: "CoinAPI",
                    value: ob.coinapi_expired_or_not_required ? "optional / not required" : "required",
                    valueColor: ob.coinapi_expired_or_not_required ? NerVyx.textSecondary : NerVyx.warning,
                    mono: true
                )
                DataRow(label: "Symbols covered", value: "\(ob.symbols_covered)", mono: true)
                DataRow(
                    label: "Stale symbols",
                    value: "\(ob.stale_symbols.count)",
                    valueColor: ob.stale_symbols.isEmpty ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
                symbolListNote(ob.stale_symbols)
                DataRow(
                    label: "Sequence gaps",
                    value: "\(ob.sequence_gaps.count)",
                    valueColor: ob.sequence_gaps.isEmpty ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
            }

            Group {
                NerVyxDivider()
                MicroLabel(text: "Consumed by", size: 9)
                consumerChips([
                    ("Trainer", ob.trainer_consumes_orderbook),
                    ("Risk", ob.risk_consumes_orderbook),
                    ("Allocator", ob.allocator_consumes_orderbook),
                    ("Paper fills", ob.paper_fills_consume_orderbook)
                ])
            }

            if let coverage = ob.direct_feed_coverage {
                NerVyxDivider()
                MicroLabel(text: "Direct feed persistence", size: 9)
                feedCoverageGrid(coverage)
            }

            if let symbols = ob.configured_symbol_coverage {
                NerVyxDivider()
                MicroLabel(text: "Configured symbol coverage", size: 9)
                DataRow(label: "Configured symbols", value: NerVyxFormat.count(symbols.configured_symbol_count), mono: true)
                DataRow(
                    label: "Complete · incomplete",
                    value: "\(NerVyxFormat.count(symbols.complete_symbols?.count)) · \(NerVyxFormat.count(symbols.incomplete_symbols?.count))",
                    mono: true
                )
                DataRow(
                    label: "All required coverage",
                    value: dtBool(symbols.all_configured_symbols_have_required_direct_feed_coverage),
                    valueColor: symbols.all_configured_symbols_have_required_direct_feed_coverage == true
                        ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
            }
        }
        .nerVyxGlassCard(accent: vm.orderbookIsStale ? NerVyx.warning : NerVyx.signal)
    }

    private func feedCoverageGrid(_ coverage: OrderbookDirectFeedCoverage) -> some View {
        let feeds: [(String, Bool?)] = [
            ("Binance bookTicker", coverage.binance_book_ticker_persisted),
            ("Binance depth 5/10/20", coverage.binance_partial_depth_5_10_20_persisted),
            ("Binance diff depth", coverage.binance_diff_depth_persisted),
            ("Binance 100ms depth", coverage.binance_100ms_depth_persisted),
            ("Binance 250ms depth", coverage.binance_250ms_depth_persisted),
            ("KuCoin best 5/50", coverage.kucoin_best_5_50_persisted),
            ("KuCoin incr best 500", coverage.kucoin_increment_best_500_persisted),
            ("KuCoin 100ms depth", coverage.kucoin_100ms_depth_persisted),
            ("KuCoin 10ms incr", coverage.kucoin_10ms_increment_persisted)
        ]
        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 6) {
            ForEach(feeds, id: \.0) { name, persisted in
                HStack(spacing: 6) {
                    Image(systemName: persisted == true ? "checkmark.circle.fill"
                        : persisted == false ? "xmark.circle.fill" : "questionmark.circle")
                        .font(.system(size: 11))
                        .foregroundStyle(persisted == true ? NerVyx.validation
                            : persisted == false ? NerVyx.sell : NerVyx.textMuted)
                    Text(name)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                    Spacer(minLength: 0)
                }
            }
        }
    }

    // MARK: - Microstructure trust

    private func microstructureCard(_ micro: MicrostructureTruth) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Group {
                HStack {
                    SectionHeader(title: "Microstructure trust", accent: NerVyx.primary)
                    StalenessChip.from(stale: vm.microstructureIsStale, ageSeconds: vm.microstructureAgeSeconds)
                }
                HStack(spacing: 8) {
                    NerVyxBadge(text: dtText(micro.live_gate).uppercased(), color: NerVyx.sell, small: true)
                    NerVyxBadge(
                        text: "BOOK TRUST \(dtText(micro.public_book_default_trust).uppercased())",
                        color: micro.public_book_trust_live_ready == true ? NerVyx.validation : NerVyx.warning,
                        small: true
                    )
                    Spacer()
                }
                DataRow(label: "Generated", value: dtText(micro.generated_at), mono: true)
                DataRow(
                    label: "Public book trust cap",
                    value: NerVyxFormat.number(micro.public_orderbook_default_trust_cap),
                    mono: true
                )
                DataRow(
                    label: "Public book approves alone",
                    value: dtBool(micro.public_book_can_approve_trade_alone),
                    valueColor: micro.public_book_can_approve_trade_alone ? NerVyx.sell : NerVyx.validation,
                    mono: true
                )
                DataRow(
                    label: "Composite trust required",
                    value: dtBool(micro.composite_microstructure_trust_required),
                    mono: true
                )
                DataRow(
                    label: "Final A+ min composite trust",
                    value: NerVyxFormat.number(micro.final_a_plus_min_composite_trust),
                    mono: true
                )
                DataRow(
                    label: "Final A+ candidates",
                    value: NerVyxFormat.count(micro.final_a_plus_candidates),
                    valueColor: (micro.final_a_plus_candidates ?? 0) > 0 ? NerVyx.validation : NerVyx.textSecondary,
                    mono: true
                )
            }

            Group {
                NerVyxDivider()
                MicroLabel(text: "Reduced-size bootstrap", size: 9)
                DataRow(label: "Tier", value: dtText(micro.reduced_size_bootstrap_tier), mono: true)
                DataRow(label: "Candidates", value: NerVyxFormat.count(micro.reduced_size_bootstrap_candidates), mono: true)
                DataRow(
                    label: "Paper only",
                    value: dtBool(micro.reduced_size_bootstrap_paper_only),
                    valueColor: micro.reduced_size_bootstrap_paper_only == true ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
                DataRow(
                    label: "Counts as final A+",
                    value: dtBool(micro.reduced_size_counts_as_final_a_plus),
                    valueColor: micro.reduced_size_counts_as_final_a_plus == true ? NerVyx.warning : NerVyx.validation,
                    mono: true
                )
                DataRow(
                    label: "Routes to live",
                    value: dtBool(micro.reduced_size_routes_to_live),
                    valueColor: micro.reduced_size_routes_to_live == true ? NerVyx.sell : NerVyx.validation,
                    mono: true
                )
            }

            Group {
                NerVyxDivider()
                DataRow(label: "Symbols covered", value: "\(micro.symbols_covered)", mono: true)
                DataRow(
                    label: "Stale symbols",
                    value: "\(micro.stale_symbols.count)",
                    valueColor: micro.stale_symbols.isEmpty ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
                symbolListNote(micro.stale_symbols)
                DataRow(
                    label: "Sequence gaps",
                    value: "\(micro.sequence_gaps.count)",
                    valueColor: micro.sequence_gaps.isEmpty ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
            }

            Group {
                NerVyxDivider()
                MicroLabel(text: "Consumed by", size: 9)
                consumerChips([
                    ("Trainer", micro.trainer_consumes_microstructure),
                    ("Risk", micro.risk_consumes_microstructure),
                    ("Orchestrator", micro.orchestrator_consumes_microstructure),
                    ("Allocator", micro.allocator_consumes_microstructure),
                    ("Paper fills", micro.paper_fills_consume_microstructure)
                ])
            }
        }
        .nerVyxGlassCard(accent: vm.microstructureIsStale ? NerVyx.warning : NerVyx.primary)
    }

    // MARK: - Shared pieces

    private func consumerChips(_ consumers: [(String, Bool)]) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: 6)], alignment: .leading, spacing: 6) {
            ForEach(consumers, id: \.0) { name, consumes in
                HStack(spacing: 5) {
                    Image(systemName: consumes ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(consumes ? NerVyx.validation : NerVyx.textMuted)
                    Text(name)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textSecondary)
                        .lineLimit(1)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(NerVyx.panel.opacity(0.6))
                .clipShape(Capsule())
            }
        }
    }

    @ViewBuilder
    private func symbolListNote(_ symbols: [String]) -> some View {
        if !symbols.isEmpty {
            Text(symbols.prefix(8).joined(separator: ", ") + (symbols.count > 8 ? " +\(symbols.count - 8)" : ""))
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(NerVyx.warning)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}
