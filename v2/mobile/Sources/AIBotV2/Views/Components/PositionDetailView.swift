import SwiftUI

// MARK: - Position Detail (shared component)
//
// Extracted from PositionsView so Portfolio, Execute, and Executions screens
// can all push the same evidence-grade detail view. Owned by iOS Infra —
// screen agents must not fork this.

// Same honesty semantics as the PositionsView list helpers: non-positive
// prices are NOT real prices and must render "Unavailable", never $0.
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

struct PositionDetailView: View {
    let position: MobilePosition

    var body: some View {
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
                .nerVyxGlassCard(accent: position.isBuy ? NerVyx.buy : NerVyx.sell)

                VStack(spacing: 10) {
                    SectionHeader(title: "PnL", accent: NerVyx.pnlColor(position.total_pnl))
                    HStack {
                        MicroLabel(text: "TOTAL")
                        Spacer()
                        Text(String(format: "%@$%.4f", position.total_pnl >= 0 ? "+" : "", position.total_pnl))
                            .font(.system(size: 22, weight: .bold, design: .monospaced))
                            .foregroundStyle(NerVyx.pnlColor(position.total_pnl))
                            .contentTransition(.numericText())
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
                .nerVyxGlassCard()

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
                .nerVyxGlassCard(accent: NerVyx.inference)

                if let reasoning = position.decision_reasoning {
                    VStack(spacing: 10) {
                        SectionHeader(title: "AI Reasoning", accent: NerVyx.primary)
                        DataRow(label: "Action", value: reasoning.action ?? "Unavailable", mono: true)
                        DataRow(label: "Decision Confidence", value: reasoning.confidence.map { "\(Int(($0 * 100).rounded()))%" } ?? "Unavailable", mono: true)
                        DataRow(label: "Reason", value: nervyxPublicRuntimeText(reasoning.reason ?? "Unavailable"), mono: false)
                        DataRow(label: "Risk", value: nervyxPublicRuntimeText(reasoning.risk_state ?? "Unavailable"), mono: true)
                        DataRow(label: "Regime", value: nervyxPublicRuntimeText(reasoning.market_regime ?? "Unavailable"), mono: true)
                        DataRow(label: "Signal", value: reasoning.signal_id ?? position.signal_id ?? "Unavailable", mono: true)
                        DataRow(label: "Prediction", value: reasoning.prediction_id ?? position.prediction_id ?? "Unavailable", mono: true)
                        DataRow(label: "Source", value: reasoning.source ?? "Unavailable", mono: true)
                    }
                    .nerVyxGlassCard(accent: NerVyx.primary)
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
                .nerVyxGlassCard()
            }
            .padding(16)
            .padding(.bottom, 24)
        }
        .nerVyxScreen()
        .navigationTitle(position.shortSymbol)
        .navigationBarTitleDisplayMode(.inline)
    }
}
