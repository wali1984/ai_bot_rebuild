import SwiftUI

private func positionPriceText(_ value: Double?) -> String {
    guard let value, value > 0 else { return "Unavailable" }
    return String(format: "%.6f", value)
}

private func positionMoneyText(_ value: Double?) -> String {
    guard let value else { return "Unavailable" }
    return String(format: "%@$%.4f", value >= 0 ? "+" : "", value)
}

private func positionAgeText(_ value: Double?) -> String {
    guard let value else { return "Age unavailable" }
    if value < 60 { return "\(Int(value.rounded()))s" }
    if value < 3_600 { return "\(Int(value / 60))m" }
    return "\(Int(value / 3_600))h"
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

struct PositionsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PositionsViewModel()
    @State private var selectedLane: PositionLane = .open

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && !hasPositionRows {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting positions stream…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, !hasPositionRows {
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

    private var hasPositionRows: Bool {
        !vm.positions.isEmpty || !vm.closedPositions.isEmpty || !vm.historicalPositions.isEmpty
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

    private var positionsList: some View {
        ScrollView {
            VStack(spacing: 12) {
                streamStatusCard
                if let s = vm.summary {
                    summaryCard(s)
                }
                if let pricing = vm.response?.position_pricing {
                    pricingCard(pricing)
                }

                lanePicker
                positionsSection(rows: selectedRows)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
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
                    text: vm.isStale ? "STALE" : vm.streamLabel.uppercased(),
                    color: vm.isStale ? NerVyx.warning : NerVyx.signal,
                    small: true
                )
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
        .nerVyxCard(accent: (vm.isStale ? NerVyx.warning : NerVyx.signal).opacity(0.3))
    }

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
                .padding(32)
                .frame(maxWidth: .infinity)
                .background(NerVyx.panel)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
            } else {
                VStack(spacing: 0) {
                    SectionHeader(title: "\(selectedLane.rawValue) Positions (\(rows.count))", accent: selectedLane == .open ? NerVyx.buy : NerVyx.primary)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)

                    ForEach(rows) { pos in
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
            }
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
                    Text("OPEN / CLOSED")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text("\(s.open_count) / \(s.closed_count ?? vm.closedPositions.count)")
                        .font(.system(size: 24, weight: .bold, design: .monospaced))
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
                    NerVyxBadge(text: "MARKS LIVE", color: NerVyx.signal)
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.pnlColor(s.total_pnl_usd))
    }

    private func pricingCard(_ pricing: PositionPricing) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Realtime Mark Pricing", accent: NerVyx.signal)
            DataRow(label: "Realtime marks", value: "\(pricing.live_mark_price_count ?? 0)", mono: true)
            DataRow(label: "Stale marks", value: "\(pricing.stale_mark_price_count ?? 0)", valueColor: (pricing.stale_mark_price_count ?? 0) > 0 ? NerVyx.warning : NerVyx.textSecondary, mono: true)
            DataRow(label: "Missing marks", value: "\(pricing.missing_mark_price_count ?? 0)", valueColor: (pricing.missing_mark_price_count ?? 0) > 0 ? NerVyx.sell : NerVyx.textSecondary, mono: true)
            DataRow(label: "Open notional", value: positionMoneyText(pricing.total_open_notional), mono: true)
        }
        .nerVyxCard(accent: NerVyx.signal.opacity(0.35))
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
                .fill(position.isBuy ? NerVyx.buy : NerVyx.sell)
                .frame(width: 4, height: 58)

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
                            value: positionMoneyText(position.unrealized_pnl),
                            valueColor: NerVyx.pnlColor(position.unrealized_pnl ?? 0),
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

                    VStack(spacing: 10) {
                        SectionHeader(title: "Prices", accent: NerVyx.inference)
                        DataRow(label: "Quantity", value: String(format: "%.6f", position.qty), mono: true)
                        DataRow(label: "Entry Price", value: positionPriceText(position.entry_price), mono: true)
                        DataRow(label: "Entry Source", value: position.entry_price_source ?? "Unavailable", mono: true)
                        if position.exit_price != nil || position.status.lowercased().contains("closed") {
                            DataRow(label: "Exit Price", value: positionPriceText(position.exit_price), mono: true)
                            DataRow(label: "Exit Source", value: position.exit_price_source ?? "Unavailable", mono: true)
                        }
                        DataRow(
                            label: "Mark Price",
                            value: positionPriceText(position.mark_price),
                            valueColor: position.mark_price_stale == true ? NerVyx.warning : NerVyx.textPrimary,
                            mono: true
                        )
                        DataRow(label: "Mark Age", value: positionAgeText(position.mark_price_age_seconds), mono: true)
                        DataRow(label: "Mark Source", value: position.mark_price_source ?? "Unavailable", mono: true)
                    }
                    .nerVyxCard()

                    if let reasoning = position.decision_reasoning {
                        VStack(spacing: 10) {
                            SectionHeader(title: "AI Reasoning", accent: NerVyx.primary)
                            DataRow(label: "Action", value: reasoning.action ?? "Unavailable", mono: true)
                            DataRow(label: "Confidence", value: reasoning.confidence.map { "\(Int(($0 * 100).rounded()))%" } ?? "Unavailable", mono: true)
                            DataRow(label: "Reason", value: nervyxPublicRuntimeText(reasoning.reason ?? "Unavailable"), mono: false)
                            DataRow(label: "Risk", value: nervyxPublicRuntimeText(reasoning.risk_state ?? "Unavailable"), mono: true)
                            DataRow(label: "Regime", value: nervyxPublicRuntimeText(reasoning.market_regime ?? "Unavailable"), mono: true)
                            DataRow(label: "Signal", value: reasoning.signal_id ?? position.signal_id ?? "Unavailable", mono: true)
                            DataRow(label: "Prediction", value: reasoning.prediction_id ?? position.prediction_id ?? "Unavailable", mono: true)
                            DataRow(label: "Source", value: reasoning.source ?? "Unavailable", mono: true)
                        }
                        .nerVyxCard(accent: NerVyx.primary.opacity(0.35))
                    }

                    VStack(spacing: 10) {
                        SectionHeader(title: "Meta", accent: NerVyx.textMuted)
                        DataRow(label: "ID", value: String(position.id.prefix(20)) + "…", mono: true)
                        DataRow(label: "Opened", value: String(position.opened_at.prefix(19)), mono: true)
                        if let closedAt = position.closed_at, !closedAt.isEmpty {
                            DataRow(label: "Closed", value: String(closedAt.prefix(19)), mono: true)
                        }
                        if let reason = position.close_reason, !reason.isEmpty {
                            DataRow(label: "Close Reason", value: nervyxPublicRuntimeText(reason), mono: false)
                        }
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
