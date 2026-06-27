import SwiftUI

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

struct PaperTradingView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = PaperViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.summary == nil {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting execution runtime…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.summary == nil {
                        VStack(spacing: 12) {
                            Image(systemName: "exclamationmark.triangle").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
                            Text(err).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
                            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                                .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else if let s = vm.summary {
                        paperContent(s)
                    }
                }
            }
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
                pnlCard(s.pnl)
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

    private var streamStatusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                LivePulse(color: vm.isStale ? NerVyx.warning : NerVyx.signal)
                Text("Execution stream")
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
        .nerVyxCard(accent: (vm.isStale ? NerVyx.warning : NerVyx.signal).opacity(0.3))
    }

    // MARK: - PnL

    private func pnlCard(_ pnl: PaperPnL) -> some View {
        VStack(spacing: 12) {
            SectionHeader(title: "PnL Summary", accent: NerVyx.buy)
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("TOTAL PnL")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text(String(format: "%@$%.2f", pnl.total_usd >= 0 ? "+" : "", pnl.total_usd))
                        .font(.system(size: 28, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.total_usd))
                }
                Spacer()
                if let wr = pnl.win_rate_pct {
                    VStack(alignment: .trailing, spacing: 4) {
                        Text("WIN RATE")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(NerVyx.textMuted)
                            .tracking(0.6)
                        Text(String(format: "%.1f%%", wr))
                            .font(.system(size: 24, weight: .bold, design: .monospaced))
                            .foregroundStyle(wr >= 60 ? NerVyx.validation : wr >= 50 ? NerVyx.buy : NerVyx.warning)
                    }
                }
            }
            NerVyxDivider()
            HStack(spacing: 0) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Realized").font(.system(size: 11)).foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", pnl.realized_usd))
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.realized_usd))
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 3) {
                    Text("Unrealized").font(.system(size: 11)).foregroundStyle(NerVyx.textMuted)
                    Text(String(format: "$%.2f", pnl.unrealized_usd))
                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                        .foregroundStyle(NerVyx.pnlColor(pnl.unrealized_usd))
                }
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.buy)
    }

    // MARK: - Loop

    private func loopCard(_ loop: PaperLoop) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Runtime Loop", accent: NerVyx.paper)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                NerVyxStatCard(
                    label: "SEEN",
                    value: "\(loop.signals_seen)",
                    accent: NerVyx.signal
                )
                NerVyxStatCard(
                    label: "ACCEPTED",
                    value: "\(loop.intents_accepted)",
                    valueColor: NerVyx.buy,
                    accent: NerVyx.buy
                )
                NerVyxStatCard(
                    label: "BLOCKED",
                    value: "\(loop.intents_blocked)",
                    valueColor: NerVyx.sell,
                    accent: NerVyx.sell
                )
            }
            NerVyxDivider()
            DataRow(label: "Intents built", value: "\(loop.intents_built)")
            DataRow(label: "Block rate", value: String(format: "%.1f%%", loop.blockRate),
                    valueColor: loop.blockRate > 80 ? NerVyx.warning : NerVyx.textSecondary)
            DataRow(label: "Cycle", value: nervyxPublicRuntimeText(loop.cycle_state ?? "UNKNOWN"), valueColor: NerVyx.textSecondary)
            DataRow(label: "Heartbeat TTL", value: loop.heartbeat_ttl_seconds.map { "\($0)s" } ?? "—", mono: true)
            DataRow(label: "Owner", value: nervyxPublicRuntimeText(loop.paper_policy_owner ?? "UNKNOWN"), valueColor: NerVyx.paper)
            DataRow(label: "Route", value: loop.runtimeRouteLabel, valueColor: loop.routes_to_live == true ? NerVyx.sell : NerVyx.signal)
            if let model = loop.model_source, !model.isEmpty {
                DataRow(label: "Model", value: model, mono: true)
            }
            DataRow(label: "Classification", value: loop.classification, valueColor: NerVyx.paper)
        }
        .nerVyxCard(accent: NerVyx.paper.opacity(0.3))
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
        .nerVyxCard()
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
        .nerVyxCard(accent: NerVyx.signal.opacity(0.3))
    }

    // MARK: - Trainer Feedback

    private func feedbackCard(_ fb: TrainerFeedback) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Trainer Feedback Loop", accent: NerVyx.primary)
            DataRow(label: "Outcome labels", value: "\(fb.outcome_labels)")
            DataRow(
                label: "Consumable rows",
                value: "\(fb.consumable_rows)",
                valueColor: fb.consumable_rows > 0 ? NerVyx.validation : NerVyx.textMuted
            )
            DataRow(
                label: "Quarantined rows",
                value: "\(fb.quarantined_rows)",
                valueColor: fb.quarantined_rows > 0 ? NerVyx.warning : NerVyx.textMuted
            )
        }
        .nerVyxCard(accent: NerVyx.primary.opacity(0.25))
    }
}
