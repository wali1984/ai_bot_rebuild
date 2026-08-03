import SwiftUI

// MARK: - Honesty helpers
// Non-positive prices are NOT real prices and must render "Unavailable", never $0.

private func positionPriceText(_ value: Double?) -> String {
    guard let value, value > 0 else { return "Unavailable" }
    return String(format: "%.6f", value)
}

private func positionMoneyText(_ value: Double?) -> String {
    guard let value else { return "Unavailable" }
    return String(format: "%@$%.4f", value >= 0 ? "+" : "", value)
}

private func positionStreamStatusText(
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

private enum PositionLane: String, CaseIterable, Identifiable {
    case open = "Open"
    case closed = "Closed"
    case historical = "Historical"

    var id: String { rawValue }
}

// MARK: - Portfolio (Positions) screen

struct PositionsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PositionsViewModel()
    @State private var selectedLane: PositionLane = .open

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && !hasAnyData {
                    loadingSkeleton
                } else if let err = vm.error, !hasAnyData {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    positionsList
                }
            }
            .nerVyxScreen()
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

    private var hasAnyData: Bool {
        vm.response != nil || vm.portfolio != nil
    }

    private var selectedRows: [MobilePosition] {
        switch selectedLane {
        case .open: return vm.positions
        case .closed: return vm.closedPositions
        case .historical: return vm.historicalPositions
        }
    }

    private var selectedEmptyTitle: String {
        switch selectedLane {
        case .open: return "No open positions"
        case .closed: return "No closed positions"
        case .historical: return "No historical positions"
        }
    }

    // MARK: List body

    private var positionsList: some View {
        ScrollView {
            VStack(spacing: 12) {
                streamStatusCard
                equityCard
                if let s = vm.summary {
                    summaryCard(s)
                }
                performanceCard
                if let pricing = vm.response?.position_pricing {
                    pricingCard(pricing)
                }
                RuntimeTruthLiveCard(title: "Runtime Truth")
                lanePicker
                positionsSection(rows: selectedRows)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: Stream truth

    private var streamFreshnessChip: StalenessChip {
        if vm.response == nil {
            return StalenessChip.offline()
        }
        return StalenessChip.from(stale: vm.isStale, lagMs: vm.lagMs, transport: vm.transport)
    }

    private var streamStatusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                LivePulse(color: vm.isStale ? NerVyx.warning : NerVyx.signal)
                Text("Position stream")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                Spacer()
                NerVyxBadge(
                    text: vm.response?.places_real_order == true ? "EXCHANGE LIVE" : "OPERATOR GATED",
                    color: NerVyx.liveBlocked,
                    small: true
                )
                streamFreshnessChip
            }
            Text(
                positionStreamStatusText(
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

    // MARK: Canonical equity headline (/api/v2/portfolio)

    private var equityCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                MicroLabel(text: "CANONICAL PAPER EQUITY")
                Spacer()
                if vm.portfolio == nil {
                    StalenessChip.offline()
                } else if vm.portfolioStale {
                    StalenessChip(mode: .stale, ageText: vm.portfolioStalenessSeconds.map { NerVyxFormat.age($0) })
                } else {
                    StalenessChip(mode: .poll)
                }
            }
            HeroMetricText(text: NerVyxFormat.money(vm.canonicalEquity))
            HStack(spacing: 8) {
                StatChip(
                    label: "START",
                    value: NerVyxFormat.money(vm.canonicalStartingEquity, decimals: 0)
                )
                StatChip(
                    label: "AVAILABLE",
                    value: NerVyxFormat.money(vm.canonicalAvailableBalance)
                )
                StatChip(
                    label: "TOTAL PNL",
                    value: NerVyxFormat.money(vm.canonicalTotalPnl, signed: true),
                    color: NerVyx.pnlColor(vm.canonicalTotalPnl ?? 0)
                )
            }
            reconcileRow
            if vm.portfolio == nil, let err = vm.portfolioError {
                Text("Canonical portfolio unavailable: \(err)")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.warning)
                    .lineLimit(2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    @ViewBuilder
    private var reconcileRow: some View {
        HStack(spacing: 6) {
            if vm.equityTrusted == false || vm.pnlTrusted == false {
                NerVyxBadge(text: "UNTRUSTED", color: NerVyx.warning, small: true)
            }
            if let delta = vm.pnlDivergenceUSD {
                if vm.pnlDiverges {
                    NerVyxBadge(
                        text: String(format: "MOBILE Δ %+.2f VS CANONICAL", delta),
                        color: NerVyx.warning,
                        small: true
                    )
                } else {
                    NerVyxBadge(text: "RECONCILED", color: NerVyx.validation, small: true)
                }
            }
            Spacer()
        }
    }

    // MARK: Mobile summary

    @ViewBuilder
    private func marksBadge(openCount: Int) -> some View {
        if vm.degradedMarkCount > 0 {
            NerVyxBadge(text: "\(vm.degradedMarkCount) STALE MARKS", color: NerVyx.warning)
        } else if vm.isStale {
            NerVyxBadge(text: "MARKS STALE", color: NerVyx.warning)
        } else if openCount == 0 {
            NerVyxBadge(text: "NO OPEN MARKS", color: NerVyx.neutral)
        } else if vm.markToMarketLive {
            NerVyxBadge(text: "MARKS LIVE", color: NerVyx.validation)
        } else {
            NerVyxBadge(text: "MARKS NOT LIVE", color: NerVyx.warning)
        }
    }

    private func summaryCard(_ s: PositionSummary) -> some View {
        VStack(spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    MicroLabel(text: "TOTAL PNL")
                    HeroMetricText(
                        text: NerVyxFormat.money(s.total_pnl_usd, signed: true),
                        size: 32,
                        color: NerVyx.pnlColor(s.total_pnl_usd)
                    )
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    MicroLabel(text: "OPEN / CLOSED")
                    Text("\(s.open_count) / \(s.closed_count ?? vm.closedPositions.count)")
                        .font(.system(size: 24, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.textPrimary)
                        .contentTransition(.numericText())
                }
            }
            NerVyxDivider()
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Realized")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(NerVyxFormat.money(s.realized_pnl_usd, signed: true))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(s.realized_pnl_usd))
                }
                Spacer()
                VStack(alignment: .center, spacing: 3) {
                    Text("Unrealized")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(NerVyxFormat.money(s.unrealized_pnl_usd, signed: true))
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(s.unrealized_pnl_usd))
                }
                Spacer()
                marksBadge(openCount: s.open_count)
            }
            if vm.cumulativePnlSeries.count > 1 {
                VStack(alignment: .leading, spacing: 4) {
                    MicroLabel(text: "CUMULATIVE NET PNL · SERVER LEDGER", size: 9)
                    AxisSparkline(
                        values: vm.cumulativePnlSeries,
                        color: NerVyx.pnlColor(s.total_pnl_usd),
                        height: 56,
                        valueFormatter: { String(format: "%+.2f", $0) }
                    )
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.pnlColor(s.total_pnl_usd))
    }

    // MARK: Performance (server winner-flag truth — never recomputed locally)

    @ViewBuilder
    private var performanceCard: some View {
        let curve = vm.cumulativePnlSeries
        let perTrade = vm.perTradePnlSeries
        let wins = vm.serverWinCount ?? 0
        let losses = vm.serverLossCount ?? 0
        if curve.count > 1 || (wins + losses) > 0 {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    title: "Performance",
                    accent: NerVyx.primary,
                    trailing: "\(vm.serverEvaluatedCount ?? (wins + losses)) evaluated"
                )
                if curve.count > 1 {
                    VStack(alignment: .leading, spacing: 4) {
                        MicroLabel(text: "CUMULATIVE NET PNL · LAST \(curve.count) CLOSED", size: 9)
                        AxisSparkline(
                            values: curve,
                            color: NerVyx.primary,
                            height: 90,
                            valueFormatter: { String(format: "%+.2f", $0) }
                        )
                    }
                }
                HStack(alignment: .top, spacing: 16) {
                    if (wins + losses) > 0 {
                        DonutChart(
                            slices: [
                                .init(label: "Wins", value: Double(wins), color: NerVyx.buy),
                                .init(label: "Losses", value: Double(losses), color: NerVyx.sell),
                            ],
                            centerText: vm.serverWinRate.map { "\(Int(($0 * 100).rounded()))%" } ?? "—",
                            centerLabel: "WIN RATE"
                        )
                    }
                    if !perTrade.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            MicroLabel(text: "PER-TRADE NET PNL", size: 9)
                            DivergingBars(values: perTrade)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                Text("Winner-flag truth · \(vm.winnerAccuracy?.source ?? "v2:paper:closed_trades") · \(vm.winRateDefinition)")
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .nerVyxGlassCard(accent: NerVyx.primary)
        } else if let err = vm.performanceError {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader(title: "Performance", accent: NerVyx.warning)
                Text("Server performance series unavailable: \(err)")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.warning)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .nerVyxGlassCard(accent: NerVyx.warning)
        } else if vm.performance != nil {
            VStack(alignment: .leading, spacing: 8) {
                SectionHeader(title: "Performance", accent: NerVyx.primary)
                Text("No evaluated closed trades in the server ledger yet.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .nerVyxGlassCard()
        }
    }

    // MARK: Mark pricing

    private func pricingCard(_ pricing: PositionPricing) -> some View {
        VStack(spacing: 10) {
            HStack {
                SectionHeader(title: "Realtime Mark Pricing", accent: NerVyx.signal)
                Spacer()
                marksBadge(openCount: vm.summary?.open_count ?? vm.positions.count)
            }
            DataRow(label: "Realtime marks", value: "\(pricing.live_mark_price_count ?? 0)", mono: true)
            DataRow(
                label: "Stale marks",
                value: "\(pricing.stale_mark_price_count ?? 0)",
                valueColor: (pricing.stale_mark_price_count ?? 0) > 0 ? NerVyx.warning : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Missing marks",
                value: "\(pricing.missing_mark_price_count ?? 0)",
                valueColor: (pricing.missing_mark_price_count ?? 0) > 0 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(label: "Open notional", value: positionMoneyText(pricing.total_open_notional), mono: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    // MARK: Lanes + rows

    private var lanePicker: some View {
        Picker("Position set", selection: $selectedLane) {
            ForEach(PositionLane.allCases) { lane in
                Text("\(lane.rawValue) \(laneCount(lane))").tag(lane)
            }
        }
        .pickerStyle(.segmented)
        .tint(NerVyx.primary)
        .padding(.vertical, 2)
    }

    private func laneCount(_ lane: PositionLane) -> Int {
        switch lane {
        case .open: return vm.positions.count
        case .closed: return vm.closedPositions.count
        case .historical: return vm.historicalPositions.count
        }
    }

    private func positionsSection(rows: [MobilePosition]) -> some View {
        Group {
            if rows.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: selectedLane == .open ? "chart.line.downtrend.xyaxis" : "clock.arrow.circlepath")
                        .font(.system(size: 36))
                        .foregroundStyle(NerVyx.textMuted)
                    Text(selectedEmptyTitle)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(NerVyx.textSecondary)
                    Text("Decision evidence appears here as the runtime publishes accepted and closed position rows.")
                        .font(.system(size: 13))
                        .foregroundStyle(NerVyx.textMuted)
                        .multilineTextAlignment(.center)
                }
                .padding(16)
                .frame(maxWidth: .infinity)
                .nerVyxGlassCard()
            } else {
                let shape = RoundedRectangle(cornerRadius: 16, style: .continuous)
                VStack(spacing: 0) {
                    SectionHeader(
                        title: "\(selectedLane.rawValue) Positions (\(rows.count))",
                        accent: selectedLane == .open ? NerVyx.buy : NerVyx.primary
                    )
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)

                    ForEach(rows) { pos in
                        NavigationLink(destination: PositionDetailView(position: pos)) {
                            PositionRowView(position: pos)
                        }
                        .buttonStyle(.plain)
                        if pos.id != rows.last?.id {
                            NerVyxDivider().padding(.horizontal, 16)
                        }
                    }
                }
                .background(.ultraThinMaterial, in: shape)
                .clipShape(shape)
                .overlay(
                    shape.stroke(
                        LinearGradient(
                            colors: [Color.white.opacity(0.14), Color.white.opacity(0.03)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: 1
                    )
                )
                .overlay(shape.stroke((selectedLane == .open ? NerVyx.buy : NerVyx.primary).opacity(0.3), lineWidth: 1))
                .shadow(color: .black.opacity(0.3), radius: 18, y: 8)
            }
        }
    }

    // MARK: Redacted-replica loading skeleton

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 10) {
                    MicroLabel(text: "CANONICAL PAPER EQUITY")
                    HeroMetricText(text: "—")
                    HStack(spacing: 8) {
                        StatChip(label: "START", value: "—")
                        StatChip(label: "AVAILABLE", value: "—")
                        StatChip(label: "TOTAL PNL", value: "—")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard(accent: NerVyx.primary)

                VStack(alignment: .leading, spacing: 12) {
                    MicroLabel(text: "TOTAL PNL")
                    HeroMetricText(text: "—", size: 32)
                    NerVyxDivider()
                    HStack {
                        Text("Realized —").font(.system(size: 13)).foregroundStyle(NerVyx.textMuted)
                        Spacer()
                        Text("Unrealized —").font(.system(size: 13)).foregroundStyle(NerVyx.textMuted)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard()

                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: "Performance", accent: NerVyx.primary)
                    RoundedRectangle(cornerRadius: 8)
                        .fill(NerVyx.borderSubtle.opacity(0.5))
                        .frame(height: 90)
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

// MARK: - Position Row

struct PositionRowView: View {
    let position: MobilePosition

    private var isClosed: Bool {
        position.status.lowercased().contains("closed") || position.exit_price != nil
    }

    private var terminalLabel: String { isClosed ? "Exit" : "Mark" }
    private var terminalPrice: Double? { isClosed ? position.exit_price : position.mark_price }
    private var rowPnl: Double? { isClosed ? position.realized_pnl : position.unrealized_pnl }
    private var sideColor: Color { position.isBuy ? NerVyx.buy : NerVyx.sell }
    private var reasoningSummary: String {
        if let reason = position.decision_reasoning?.reason, !reason.isEmpty {
            return nervyxPublicRuntimeText(reason)
        }
        if let risk = position.decision_reasoning?.risk_state, !risk.isEmpty {
            return nervyxPublicRuntimeText(risk)
        }
        if let signal = position.signal_id, !signal.isEmpty {
            return "Signal \(signal)"
        }
        return "Decision evidence connecting"
    }

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 3)
                .fill(
                    LinearGradient(
                        colors: [sideColor, sideColor.opacity(0.15)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .frame(width: 4, height: 62)

            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text(position.shortSymbol)
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Text("×\(String(format: "%.4f", position.qty))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    NerVyxBadge(text: position.side.uppercased(), color: sideColor)
                }
                HStack {
                    Text("Entry \(positionPriceText(position.entry_price))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("→")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("\(terminalLabel) \(positionPriceText(terminalPrice))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(position.mark_price_stale == true ? NerVyx.warning : NerVyx.textSecondary)
                    Spacer()
                    Text(positionMoneyText(rowPnl))
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(rowPnl ?? 0))
                }
                Text(reasoningSummary)
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textSecondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                if let confidence = position.decision_reasoning?.confidence {
                    HStack(spacing: 6) {
                        ConfidenceBar(value: confidence)
                            .frame(maxWidth: .infinity)
                        Text("\(Int((confidence * 100).rounded()))%")
                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                            .foregroundStyle(NerVyx.confidenceColor(confidence))
                        if let risk = position.decision_reasoning?.risk_state, !risk.isEmpty {
                            NerVyxBadge(
                                text: nervyxPublicRuntimeText(risk).uppercased(),
                                color: NerVyx.statusColor(risk),
                                small: true
                            )
                        }
                    }
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }
}

// PositionDetailView lives in Views/Components/PositionDetailView.swift (shared, Infra-owned).
