import SwiftUI

// MARK: - Honesty helpers
// Non-positive prices are NOT real prices and must render "Unavailable", never $0.

private func paperPositionPriceText(_ value: Double?) -> String {
    guard let value, value > 0 else { return "Unavailable" }
    return String(format: "%.4f", value)
}

private func paperPositionMoneyText(_ value: Double?) -> String {
    guard let value else { return "Unavailable" }
    return String(format: "%@$%.2f", value >= 0 ? "+" : "", value)
}

private func paperPositionAgeText(_ value: Double?) -> String {
    guard let value else { return "age unavailable" }
    if value < 60 { return "\(Int(value.rounded()))s" }
    if value < 3_600 { return "\(Int(value / 60))m" }
    return "\(Int(value / 3_600))h"
}

private func paperPositionSourceText(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "source unavailable" }
    return nervyxPublicRuntimeText(value)
}

private func paperPositionReasoningText(_ position: MobilePosition) -> String? {
    if let reason = position.decision_reasoning?.reason, !reason.isEmpty {
        return nervyxPublicRuntimeText(reason)
    }
    if let risk = position.decision_reasoning?.risk_state, !risk.isEmpty {
        return nervyxPublicRuntimeText(risk)
    }
    if let signal = position.signal_id, !signal.isEmpty {
        return "Signal \(signal)"
    }
    return nil
}

private func executionStreamStatusText(
    sourceType: String?,
    lastUpdatedAt: String?,
    isStale: Bool,
    missingFields: [String],
    warnings: [String]
) -> String {
    var parts = [sourceType?.uppercased() ?? "CONNECTING"]
    if let lastUpdatedAt, !lastUpdatedAt.isEmpty {
        parts.append(String(lastUpdatedAt.prefix(19)))
    }
    if isStale {
        parts.append("stale")
    }
    if !missingFields.isEmpty {
        parts.append("missing \(missingFields.count)")
    }
    if !warnings.isEmpty {
        parts.append("warnings \(warnings.count)")
    }
    return parts.joined(separator: " · ")
}

private func paperWinRateColor(_ fraction: Double) -> Color {
    if fraction >= 0.60 { return NerVyx.validation }
    if fraction >= 0.50 { return NerVyx.buy }
    return NerVyx.warning
}

struct PaperTradingView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PaperViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if let s = vm.summary {
                    paperContent(s)
                } else if let err = vm.error {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    loadingSkeleton
                }
            }
            .nerVyxScreen()
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
                HStack(spacing: 8) {
                    LivePulse(color: NerVyx.paper)
                    Text("Execution runtime · \(nervyxPublicRuntimeText(s.live_gate))")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    NerVyxBadge(text: s.places_real_order ? "LIVE" : "GATED", color: s.places_real_order ? NerVyx.sell : NerVyx.signal, small: true)
                }
                .padding(.horizontal, 4)

                streamStatusCard
                RuntimeTruthCard(title: "Runtime Truth", truth: .paperSummary(s))
                pnlCard(s)
                if !vm.pnlWindows.isEmpty {
                    pnlWindowsCard(vm.pnlWindows)
                }
                loopCard(s.loop)
                positionsCard(s.positions)
                if let pricing = s.position_pricing {
                    positionPricingCard(pricing)
                }
                feedbackCard(s.trainer_feedback)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Stream truth

    private var streamFreshnessChip: StalenessChip {
        if vm.summary == nil { return StalenessChip.offline() }
        return StalenessChip.from(stale: vm.isStale, lagMs: vm.lagMs, transport: vm.transport)
    }

    private var streamStatusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                LivePulse(color: vm.isStale ? NerVyx.warning : NerVyx.signal)
                Text("Execution stream")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                Spacer()
                streamFreshnessChip
            }
            Text(
                executionStreamStatusText(
                    sourceType: vm.sourceType,
                    lastUpdatedAt: vm.lastUpdatedAt,
                    isStale: vm.isStale,
                    missingFields: vm.missingFields,
                    warnings: vm.streamWarnings
                )
            )
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(vm.isStale ? NerVyx.warning : NerVyx.textMuted)
            if let warning = vm.streamWarnings.first, !warning.isEmpty {
                Text(nervyxPublicRuntimeText(warning))
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.warning)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: vm.isStale ? NerVyx.warning : NerVyx.signal)
    }

    // MARK: - PnL

    private func resolvedWinRate(_ s: MobilePaperSummary) -> (fraction: Double, winning: Int?, losing: Int?)? {
        if let pct = s.pnl.win_rate_pct, pct.isFinite {
            return (min(max(pct / 100, 0), 1), nil, nil)
        }
        if let window = vm.primaryWinRateWindow, let wr = window.win_rate, wr.isFinite {
            return (min(max(wr, 0), 1), window.winning_trade_count, window.losing_trade_count)
        }
        return nil
    }

    private func pnlCard(_ s: MobilePaperSummary) -> some View {
        let pnl = s.pnl
        let winRate = resolvedWinRate(s)
        return VStack(spacing: 12) {
            SectionHeader(title: "PnL Summary", accent: NerVyx.buy, trailing: "NET")
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 4) {
                    MicroLabel(text: "TOTAL PNL")
                    HeroMetricText(
                        text: NerVyxFormat.money(pnl.total_usd, signed: true),
                        size: 32,
                        color: NerVyx.pnlColor(pnl.total_usd)
                    )
                }
                Spacer()
                if let winRate {
                    RingGauge(
                        value: winRate.fraction,
                        label: "WIN RATE",
                        centerText: String(format: "%.1f%%", winRate.fraction * 100),
                        color: paperWinRateColor(winRate.fraction),
                        size: 76,
                        lineWidth: 7
                    )
                }
            }
            if let winRate, let winning = winRate.winning, let losing = winRate.losing {
                Text("\(winning) winners · \(losing) losers")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            NerVyxDivider()
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Realized").font(.system(size: 11)).foregroundStyle(NerVyx.textMuted)
                    Text(NerVyxFormat.money(pnl.realized_usd))
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.realized_usd))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 3) {
                    Text("Unrealized").font(.system(size: 11)).foregroundStyle(NerVyx.textMuted)
                    Text(NerVyxFormat.money(pnl.unrealized_usd))
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.unrealized_usd))
                }
            }
            if vm.pnlSeries.count > 1 {
                NerVyxDivider()
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        MicroLabel(text: "PNL PATH")
                        Spacer()
                        Text("SESSION")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(NerVyx.textMuted)
                            .tracking(0.6)
                    }
                    AxisSparkline(
                        values: vm.pnlSeries,
                        color: NerVyx.pnlColor(pnl.total_usd),
                        height: 72,
                        valueFormatter: { NerVyxFormat.money($0, signed: true) }
                    )
                }
            }
            if s.pnl.pnl_trusted == false, let reason = s.pnl.reason_if_untrusted, !reason.isEmpty {
                Text("PnL untrusted · \(nervyxPublicRuntimeText(reason))")
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.warning)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.buy)
    }

    private func pnlWindowsCard(_ windows: [PnLWindow]) -> some View {
        let maxAbs = max(windows.compactMap { $0.realized_pnl_usd.map { abs($0) } }.max() ?? 1, 0.0001)
        return VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Realized by Window", accent: NerVyx.inference, trailing: "NET")
            ForEach(windows) { window in
                VStack(alignment: .leading, spacing: 3) {
                    HBarRow(
                        label: window.window.uppercased(),
                        value: window.realized_pnl_usd ?? 0,
                        maxAbsValue: maxAbs,
                        valueText: NerVyxFormat.money(window.realized_pnl_usd, signed: true),
                        signed: true
                    )
                    Text(windowCaption(window))
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .padding(.leading, 84)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    private func windowCaption(_ window: PnLWindow) -> String {
        var parts: [String] = ["\(window.closed_trade_count ?? 0) trades"]
        if let wr = window.win_rate, wr.isFinite {
            parts.append(String(format: "win %.0f%%", wr * 100))
        }
        if let pf = window.profit_factor, pf.isFinite {
            parts.append(String(format: "PF %.2f", pf))
        }
        return parts.joined(separator: " · ")
    }

    // MARK: - Loop + Funnel

    private func loopCard(_ loop: PaperLoop) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(
                title: "Signal Funnel",
                accent: NerVyx.paper,
                trailing: String(format: "block %.0f%%", loop.blockRate)
            )
            if loop.signals_seen == 0 && loop.intents_built == 0 && loop.intents_accepted == 0 && loop.intents_blocked == 0 {
                Text("No signals this cycle · \(nervyxPublicRuntimeText(loop.classification))")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                funnelSection(loop)
            }
            NerVyxDivider()
            DataRow(label: "Cycle", value: nervyxPublicRuntimeText(loop.cycle_state ?? "UNKNOWN"), valueColor: NerVyx.textSecondary)
            DataRow(label: "Heartbeat TTL", value: loop.heartbeat_ttl_seconds.map { "\($0)s" } ?? "—", mono: true)
            DataRow(label: "Owner", value: nervyxPublicRuntimeText(loop.paper_policy_owner ?? "UNKNOWN"), valueColor: NerVyx.paper)
            DataRow(label: "Route", value: loop.runtimeRouteLabel, valueColor: loop.routes_to_live == true ? NerVyx.sell : NerVyx.signal)
            if let model = loop.model_source, !model.isEmpty {
                DataRow(label: "Model", value: model, mono: true)
            }
            DataRow(label: "Classification", value: nervyxPublicRuntimeText(loop.classification), valueColor: NerVyx.paper)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.paper)
    }

    private func funnelSection(_ loop: PaperLoop) -> some View {
        let maxV = Double(max(loop.signals_seen, loop.intents_built, loop.intents_accepted, loop.intents_blocked, 1))
        return VStack(alignment: .leading, spacing: 8) {
            HBarRow(label: "SEEN", value: Double(loop.signals_seen), maxAbsValue: maxV,
                    valueText: "\(loop.signals_seen)", color: NerVyx.signal)
            HBarRow(label: "BUILT", value: Double(loop.intents_built), maxAbsValue: maxV,
                    valueText: "\(loop.intents_built)", color: NerVyx.inference)
            HBarRow(label: "ACCEPTED", value: Double(loop.intents_accepted), maxAbsValue: maxV,
                    valueText: "\(loop.intents_accepted)", color: NerVyx.buy)
            HBarRow(label: "BLOCKED", value: Double(loop.intents_blocked), maxAbsValue: maxV,
                    valueText: "\(loop.intents_blocked)", color: NerVyx.sell)
            if loop.intents_built > 0 {
                NerVyxDivider()
                SplitBar(
                    leftValue: Double(loop.intents_accepted),
                    rightValue: Double(loop.intents_blocked),
                    leftLabel: "ACCEPTED",
                    rightLabel: "BLOCKED",
                    leftColor: NerVyx.buy,
                    rightColor: NerVyx.sell
                )
            }
        }
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
                    NavigationLink(destination: PositionDetailView(position: pos)) {
                        HStack(spacing: 10) {
                            RoundedRectangle(cornerRadius: 2)
                                .fill(pos.isBuy ? NerVyx.buy : NerVyx.sell)
                                .frame(width: 3, height: 42)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(pos.shortSymbol)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(NerVyx.textPrimary)
                                Text("Entry \(paperPositionPriceText(pos.entry_price)) -> Mark \(paperPositionPriceText(pos.mark_price))")
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(pos.mark_price_stale == true ? NerVyx.warning : NerVyx.textMuted)
                                    .lineLimit(1)
                                Text("\(paperPositionAgeText(pos.mark_price_age_seconds)) · \(paperPositionSourceText(pos.mark_price_source))")
                                    .font(.system(size: 10))
                                    .foregroundStyle(pos.mark_price_stale == true ? NerVyx.warning : NerVyx.textMuted)
                                    .lineLimit(1)
                                if let reasoning = paperPositionReasoningText(pos) {
                                    Text(reasoning)
                                        .font(.system(size: 10))
                                        .foregroundStyle(NerVyx.textSecondary)
                                        .lineLimit(2)
                                }
                            }
                            Spacer()
                            Text(pos.unrealized_pnl.map { String(format: "%@$%.2f", $0 >= 0 ? "+" : "", $0) } ?? "Unavailable")
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(NerVyx.pnlColor(pos.unrealized_pnl ?? 0))
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    private func positionPricingCard(_ pricing: PositionPricing) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Realtime Mark Pricing", accent: NerVyx.signal)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                NerVyxStatCard(label: "MARKS", value: "\(pricing.live_mark_price_count ?? 0)", accent: NerVyx.signal)
                NerVyxStatCard(
                    label: "STALE",
                    value: "\(pricing.stale_mark_price_count ?? 0)",
                    valueColor: (pricing.stale_mark_price_count ?? 0) > 0 ? NerVyx.warning : NerVyx.textPrimary,
                    accent: NerVyx.warning
                )
                NerVyxStatCard(
                    label: "MISSING",
                    value: "\(pricing.missing_mark_price_count ?? 0)",
                    valueColor: (pricing.missing_mark_price_count ?? 0) > 0 ? NerVyx.sell : NerVyx.textPrimary,
                    accent: NerVyx.sell
                )
            }
            NerVyxDivider()
            DataRow(label: "Open notional", value: paperPositionMoneyText(pricing.total_open_notional), mono: true)
            DataRow(label: "Unrealized PnL", value: paperPositionMoneyText(pricing.unrealized_pnl_usd), valueColor: NerVyx.pnlColor(pricing.unrealized_pnl_usd ?? 0), mono: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    // MARK: - Trainer Feedback

    private func feedbackCard(_ fb: TrainerFeedback) -> some View {
        let total = fb.consumable_rows + fb.quarantined_rows
        let hasQuarantine = fb.quarantined_rows > 0
        let accent = hasQuarantine ? NerVyx.warning : NerVyx.primary
        return VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Trainer Feedback Loop", accent: accent, trailing: "\(fb.outcome_labels) labels")
            if total > 0 {
                SplitBar(
                    leftValue: Double(fb.consumable_rows),
                    rightValue: Double(fb.quarantined_rows),
                    leftLabel: "CONSUMABLE",
                    rightLabel: "QUARANTINED",
                    leftColor: NerVyx.validation,
                    rightColor: NerVyx.warning
                )
                HStack {
                    StatChip(label: "CONSUMABLE", value: "\(fb.consumable_rows)", color: NerVyx.validation, accent: NerVyx.validation)
                    Spacer()
                    StatChip(
                        label: "QUARANTINED",
                        value: "\(fb.quarantined_rows)",
                        color: hasQuarantine ? NerVyx.warning : NerVyx.textMuted,
                        accent: NerVyx.warning
                    )
                }
                if hasQuarantine {
                    Text("\(fb.quarantined_rows) row\(fb.quarantined_rows == 1 ? "" : "s") withheld from training")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.warning)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                Text("No trainer feedback rows this cycle")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: accent)
    }

    // MARK: - Loading (redacted replica of the real layout)

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 14) {
                VStack(alignment: .leading, spacing: 10) {
                    MicroLabel(text: "TOTAL PNL")
                    HeroMetricText(text: "—", size: 32)
                    HStack(spacing: 8) {
                        StatChip(label: "REALIZED", value: "—")
                        StatChip(label: "UNREALIZED", value: "—")
                        StatChip(label: "WIN RATE", value: "—")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard(accent: NerVyx.buy)

                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: "Signal Funnel", accent: NerVyx.paper)
                    RoundedRectangle(cornerRadius: 8)
                        .fill(NerVyx.borderSubtle.opacity(0.5))
                        .frame(height: 120)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard()

                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: "Trainer Feedback Loop", accent: NerVyx.primary)
                    RoundedRectangle(cornerRadius: 8)
                        .fill(NerVyx.borderSubtle.opacity(0.5))
                        .frame(height: 60)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard()
            }
            .padding(16)
            .redacted(reason: .placeholder)
        }
        .scrollDisabled(true)
    }
}
