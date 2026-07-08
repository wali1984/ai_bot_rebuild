import SwiftUI

private func runtimeText(_ value: String?) -> String {
    guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        return "not reported"
    }
    return nervyxPublicRuntimeText(value)
}

private func runtimeMoney(_ value: Double?) -> String {
    guard let value else { return "not reported" }
    return String(format: "$%.2f", value)
}

private func runtimeNumber(_ value: Double?, digits: Int = 2) -> String {
    guard let value else { return "not reported" }
    return String(format: "%.\(digits)f", value)
}

private func runtimeInt(_ value: Int?) -> String {
    guard let value else { return "0" }
    return "\(value)"
}

private func runtimeBool(_ value: Bool?, trueText: String, falseText: String) -> String {
    guard let value else { return "not reported" }
    return value ? trueText : falseText
}

private func providerActualText(color: String?, actual: Bool?, status: String?) -> String {
    let marker = color ?? status
    let actualText = runtimeBool(actual, trueText: "actual", falseText: "no actual")
    return "\(runtimeText(marker))/\(actualText)"
}

private func runtimePercent(_ value: Double?) -> String {
    guard let value else { return "not reported" }
    let percent = abs(value) <= 1 ? value * 100 : value
    return String(format: "%.1f%%", percent)
}

struct RuntimeTruthDisplay {
    let paperSessionId: String?
    let equity: Double?
    let newEntriesAllowed: Bool?
    let governorState: String?
    let profitFactor: Double?
    let expectancyUsd: Double?
    let realizedPnlUsd: Double?
    let expectancyBps: Double?
    let winRate: Double?
    let finalAPlusRows: Int?
    let evaluatedAPlusRows: Int?
    let reduceSizeRows: Int?
    let reduceSizeCountsAsFinalAPlus: Bool?
    let trainerState: String?
    let feedbackRows: Int?
    let marketFreshnessState: String?
    let marketSource: String?
    let microstructureTrustBlockedRows: Int?
    let advancedIndicatorStatus: String?
    let advancedIndicatorFvgPresentCount: Int?
    let advancedIndicatorBlockCount: Int?
    let advancedIndicatorFvgAloneAllowsTrade: Bool?
    let advancedIndicatorSweepRiskCanBlock: Bool?
    let preemptiveDecisionId: String?
    let preemptiveAction: String?
    let preTradeLossProbability: Double?
    let confidenceOverstatementRisk: Double?
    let regimeCompatibilityScore: Double?
    let exitFeasibilityScore: Double?
    let bucketProfitFactor: Double?
    let hedgeState: String?
    let netDeltaUsd: Double?
    let grossExposureUsd: Double?
    let crossMarginSafe: Bool?
    let marginCallRisk: String?
    let leverageDistribution: [Double]
    let notionalDistributionUsd: [Double]
    let coinglassStatus: String?
    let moralisStatus: String?
    let preemptivePreventedCount: Int?
    let positiveEdgeProbationSupplyState: String?
    let positiveEdgeProbationCandidates: Int?
    let positiveEdgeProbationAccepted: Int?
    let closedProbationTradeCount: Int?
    let probation5TradeGateStatus: String?
    let probationCountsAsFinalAPlus: Bool?
    let probationCountsAsLiveReady: Bool?
    let whyTradeWasPrevented: [String]
    let governorAutoAction: String?
    let nextRemediation: String?
    let liveGate: String?
    let liveReady: Bool?
    let topBlockers: [String]

    static func paperSummary(_ summary: MobilePaperSummary) -> RuntimeTruthDisplay {
        RuntimeTruthDisplay(
            paperSessionId: summary.paper_session_id,
            equity: summary.effectiveEquity,
            newEntriesAllowed: summary.entry_freeze?.new_entries_allowed,
            governorState: summary.performance?.governor_state,
            profitFactor: summary.performance?.profit_factor,
            expectancyUsd: summary.performance?.expectancy_usd,
            realizedPnlUsd: summary.performance?.realized_pnl_usd,
            expectancyBps: summary.performance?.notional_weighted_expectancy_bps,
            winRate: summary.performance?.win_rate,
            finalAPlusRows: summary.reduced_size_bootstrap?.final_a_plus_candidates ?? summary.a_plus_gate?.a_plus_candidates,
            evaluatedAPlusRows: summary.a_plus_gate?.evaluated_candidates,
            reduceSizeRows: summary.reduced_size_bootstrap?.reduced_size_bootstrap_candidates ?? summary.reduced_size_bootstrap?.closed_rows,
            reduceSizeCountsAsFinalAPlus: summary.reduced_size_bootstrap?.counts_as_final_a_plus,
            trainerState: summary.trainer_learning?.online_learning_status,
            feedbackRows: summary.trainer_feedback.consumable_rows,
            marketFreshnessState: summary.market_data_freshness?.freshness_state,
            marketSource: summary.market_data_freshness?.source,
            microstructureTrustBlockedRows: summary.a_plus_gate?.rejected_reason_matrix?["microstructure_trust_confirms"],
            advancedIndicatorStatus: summary.preemptive_edge_control?.advanced_indicators?.status ?? summary.preemptive_edge_control?.advanced_indicator_status,
            advancedIndicatorFvgPresentCount: summary.preemptive_edge_control?.advanced_indicators?.fvg_present_count,
            advancedIndicatorBlockCount: summary.preemptive_edge_control?.advanced_indicators?.accepted_advanced_indicator_block_count,
            advancedIndicatorFvgAloneAllowsTrade: summary.preemptive_edge_control?.advanced_indicators?.fvg_alone_can_approve_trade,
            advancedIndicatorSweepRiskCanBlock: summary.preemptive_edge_control?.advanced_indicators?.sweep_risk_can_block_or_reduce,
            preemptiveDecisionId: summary.preemptive_edge_control?.preemptive_decision_id,
            preemptiveAction: summary.preemptive_edge_control?.preemptive_action,
            preTradeLossProbability: summary.preemptive_edge_control?.pre_trade_loss_probability,
            confidenceOverstatementRisk: summary.preemptive_edge_control?.confidence_overstatement_risk,
            regimeCompatibilityScore: summary.preemptive_edge_control?.regime_compatibility_score,
            exitFeasibilityScore: summary.preemptive_edge_control?.exit_feasibility_score,
            bucketProfitFactor: summary.preemptive_edge_control?.bucket_profit_factor,
            hedgeState: summary.adaptive_hedge_cross_margin?.hedge_state,
            netDeltaUsd: summary.adaptive_hedge_cross_margin?.net_delta_usd,
            grossExposureUsd: summary.adaptive_hedge_cross_margin?.gross_exposure_usd,
            crossMarginSafe: summary.adaptive_hedge_cross_margin?.cross_margin_safe,
            marginCallRisk: summary.adaptive_hedge_cross_margin?.margin_call_risk,
            leverageDistribution: summary.adaptive_hedge_cross_margin?.recommended_leverage_distribution ?? [],
            notionalDistributionUsd: summary.adaptive_hedge_cross_margin?.current_notional_distribution_usd ?? [],
            coinglassStatus: providerActualText(
                color: summary.provider_readiness?.coinglass_dashboard_color,
                actual: summary.provider_readiness?.coinglass_actual_payload_present,
                status: summary.provider_readiness?.coinglass_status
            ),
            moralisStatus: providerActualText(
                color: summary.provider_readiness?.moralis_dashboard_color,
                actual: summary.provider_readiness?.moralis_actual_payload_present,
                status: summary.provider_readiness?.moralis_status
            ),
            preemptivePreventedCount: summary.preemptive_edge_control?.preventedCount,
            positiveEdgeProbationSupplyState: summary.preemptive_edge_control?.positive_edge_probation_supply_state,
            positiveEdgeProbationCandidates: summary.preemptive_edge_control?.positive_edge_probation_candidates,
            positiveEdgeProbationAccepted: summary.preemptive_edge_control?.positive_edge_probation_accepted,
            closedProbationTradeCount: summary.preemptive_edge_control?.closed_probation_trade_count,
            probation5TradeGateStatus: summary.preemptive_edge_control?.probation_5_trade_gate_status,
            probationCountsAsFinalAPlus: summary.preemptive_edge_control?.probation_counts_as_final_a_plus,
            probationCountsAsLiveReady: summary.preemptive_edge_control?.probation_counts_as_live_ready,
            whyTradeWasPrevented: summary.preemptive_edge_control?.why_trade_was_prevented ?? [],
            governorAutoAction: summary.preemptive_edge_control?.governor_auto_action,
            nextRemediation: summary.preemptive_edge_control?.next_remediation,
            liveGate: summary.real_trader_readiness?.live_gate ?? summary.live_gate,
            liveReady: summary.real_trader_readiness?.live_ready,
            topBlockers: summary.top_blockers ?? summary.entry_freeze?.halt_reasons ?? []
        )
    }

    static func dashboardPaper(_ paper: PaperState) -> RuntimeTruthDisplay {
        RuntimeTruthDisplay(
            paperSessionId: paper.paper_session_id,
            equity: paper.effectiveEquity,
            newEntriesAllowed: paper.entry_freeze?.new_entries_allowed ?? paper.new_entries_allowed,
            governorState: paper.performance?.governor_state,
            profitFactor: paper.performance?.profit_factor,
            expectancyUsd: paper.performance?.expectancy_usd,
            realizedPnlUsd: paper.performance?.realized_pnl_usd,
            expectancyBps: paper.performance?.notional_weighted_expectancy_bps,
            winRate: paper.performance?.win_rate,
            finalAPlusRows: paper.reduced_size_bootstrap?.final_a_plus_candidates ?? paper.a_plus_gate?.a_plus_candidates,
            evaluatedAPlusRows: paper.a_plus_gate?.evaluated_candidates,
            reduceSizeRows: paper.reduced_size_bootstrap?.reduced_size_bootstrap_candidates ?? paper.reduced_size_bootstrap?.closed_rows,
            reduceSizeCountsAsFinalAPlus: paper.reduced_size_bootstrap?.counts_as_final_a_plus,
            trainerState: paper.trainer_learning?.online_learning_status,
            feedbackRows: nil,
            marketFreshnessState: paper.market_data_freshness?.freshness_state,
            marketSource: paper.market_data_freshness?.source,
            microstructureTrustBlockedRows: paper.a_plus_gate?.rejected_reason_matrix?["microstructure_trust_confirms"],
            advancedIndicatorStatus: paper.preemptive_edge_control?.advanced_indicators?.status ?? paper.preemptive_edge_control?.advanced_indicator_status,
            advancedIndicatorFvgPresentCount: paper.preemptive_edge_control?.advanced_indicators?.fvg_present_count,
            advancedIndicatorBlockCount: paper.preemptive_edge_control?.advanced_indicators?.accepted_advanced_indicator_block_count,
            advancedIndicatorFvgAloneAllowsTrade: paper.preemptive_edge_control?.advanced_indicators?.fvg_alone_can_approve_trade,
            advancedIndicatorSweepRiskCanBlock: paper.preemptive_edge_control?.advanced_indicators?.sweep_risk_can_block_or_reduce,
            preemptiveDecisionId: paper.preemptive_edge_control?.preemptive_decision_id,
            preemptiveAction: paper.preemptive_edge_control?.preemptive_action,
            preTradeLossProbability: paper.preemptive_edge_control?.pre_trade_loss_probability,
            confidenceOverstatementRisk: paper.preemptive_edge_control?.confidence_overstatement_risk,
            regimeCompatibilityScore: paper.preemptive_edge_control?.regime_compatibility_score,
            exitFeasibilityScore: paper.preemptive_edge_control?.exit_feasibility_score,
            bucketProfitFactor: paper.preemptive_edge_control?.bucket_profit_factor,
            hedgeState: paper.adaptive_hedge_cross_margin?.hedge_state,
            netDeltaUsd: paper.adaptive_hedge_cross_margin?.net_delta_usd,
            grossExposureUsd: paper.adaptive_hedge_cross_margin?.gross_exposure_usd,
            crossMarginSafe: paper.adaptive_hedge_cross_margin?.cross_margin_safe,
            marginCallRisk: paper.adaptive_hedge_cross_margin?.margin_call_risk,
            leverageDistribution: paper.adaptive_hedge_cross_margin?.recommended_leverage_distribution ?? [],
            notionalDistributionUsd: paper.adaptive_hedge_cross_margin?.current_notional_distribution_usd ?? [],
            coinglassStatus: providerActualText(
                color: paper.provider_readiness?.coinglass_dashboard_color,
                actual: paper.provider_readiness?.coinglass_actual_payload_present,
                status: paper.provider_readiness?.coinglass_status
            ),
            moralisStatus: providerActualText(
                color: paper.provider_readiness?.moralis_dashboard_color,
                actual: paper.provider_readiness?.moralis_actual_payload_present,
                status: paper.provider_readiness?.moralis_status
            ),
            preemptivePreventedCount: paper.preemptive_edge_control?.preventedCount,
            positiveEdgeProbationSupplyState: paper.preemptive_edge_control?.positive_edge_probation_supply_state,
            positiveEdgeProbationCandidates: paper.preemptive_edge_control?.positive_edge_probation_candidates,
            positiveEdgeProbationAccepted: paper.preemptive_edge_control?.positive_edge_probation_accepted,
            closedProbationTradeCount: paper.preemptive_edge_control?.closed_probation_trade_count,
            probation5TradeGateStatus: paper.preemptive_edge_control?.probation_5_trade_gate_status,
            probationCountsAsFinalAPlus: paper.preemptive_edge_control?.probation_counts_as_final_a_plus,
            probationCountsAsLiveReady: paper.preemptive_edge_control?.probation_counts_as_live_ready,
            whyTradeWasPrevented: paper.preemptive_edge_control?.why_trade_was_prevented ?? [],
            governorAutoAction: paper.preemptive_edge_control?.governor_auto_action,
            nextRemediation: paper.preemptive_edge_control?.next_remediation,
            liveGate: paper.real_trader_readiness?.live_gate,
            liveReady: paper.real_trader_readiness?.live_ready,
            topBlockers: paper.top_blockers ?? paper.entry_freeze?.halt_reasons ?? []
        )
    }

    static func risk(_ risk: MobileRiskStatus) -> RuntimeTruthDisplay {
        RuntimeTruthDisplay(
            paperSessionId: nil,
            equity: nil,
            newEntriesAllowed: risk.entry_freeze?.new_entries_allowed,
            governorState: risk.performance?.governor_state,
            profitFactor: risk.performance?.profit_factor,
            expectancyUsd: risk.performance?.expectancy_usd,
            realizedPnlUsd: risk.performance?.realized_pnl_usd,
            expectancyBps: risk.performance?.notional_weighted_expectancy_bps,
            winRate: risk.performance?.win_rate,
            finalAPlusRows: risk.reduced_size_bootstrap?.final_a_plus_candidates ?? risk.a_plus_gate?.a_plus_candidates,
            evaluatedAPlusRows: risk.a_plus_gate?.evaluated_candidates,
            reduceSizeRows: risk.reduced_size_bootstrap?.reduced_size_bootstrap_candidates ?? risk.reduced_size_bootstrap?.closed_rows,
            reduceSizeCountsAsFinalAPlus: risk.reduced_size_bootstrap?.counts_as_final_a_plus,
            trainerState: risk.trainer_learning?.online_learning_status,
            feedbackRows: nil,
            marketFreshnessState: risk.market_data_freshness?.freshness_state,
            marketSource: risk.market_data_freshness?.source,
            microstructureTrustBlockedRows: risk.a_plus_gate?.rejected_reason_matrix?["microstructure_trust_confirms"],
            advancedIndicatorStatus: risk.preemptive_edge_control?.advanced_indicators?.status ?? risk.preemptive_edge_control?.advanced_indicator_status,
            advancedIndicatorFvgPresentCount: risk.preemptive_edge_control?.advanced_indicators?.fvg_present_count,
            advancedIndicatorBlockCount: risk.preemptive_edge_control?.advanced_indicators?.accepted_advanced_indicator_block_count,
            advancedIndicatorFvgAloneAllowsTrade: risk.preemptive_edge_control?.advanced_indicators?.fvg_alone_can_approve_trade,
            advancedIndicatorSweepRiskCanBlock: risk.preemptive_edge_control?.advanced_indicators?.sweep_risk_can_block_or_reduce,
            preemptiveDecisionId: risk.preemptive_edge_control?.preemptive_decision_id,
            preemptiveAction: risk.preemptive_edge_control?.preemptive_action,
            preTradeLossProbability: risk.preemptive_edge_control?.pre_trade_loss_probability,
            confidenceOverstatementRisk: risk.preemptive_edge_control?.confidence_overstatement_risk,
            regimeCompatibilityScore: risk.preemptive_edge_control?.regime_compatibility_score,
            exitFeasibilityScore: risk.preemptive_edge_control?.exit_feasibility_score,
            bucketProfitFactor: risk.preemptive_edge_control?.bucket_profit_factor,
            hedgeState: risk.adaptive_hedge_cross_margin?.hedge_state,
            netDeltaUsd: risk.adaptive_hedge_cross_margin?.net_delta_usd,
            grossExposureUsd: risk.adaptive_hedge_cross_margin?.gross_exposure_usd,
            crossMarginSafe: risk.adaptive_hedge_cross_margin?.cross_margin_safe,
            marginCallRisk: risk.adaptive_hedge_cross_margin?.margin_call_risk,
            leverageDistribution: risk.adaptive_hedge_cross_margin?.recommended_leverage_distribution ?? [],
            notionalDistributionUsd: risk.adaptive_hedge_cross_margin?.current_notional_distribution_usd ?? [],
            coinglassStatus: providerActualText(
                color: risk.provider_readiness?.coinglass_dashboard_color,
                actual: risk.provider_readiness?.coinglass_actual_payload_present,
                status: risk.provider_readiness?.coinglass_status
            ),
            moralisStatus: providerActualText(
                color: risk.provider_readiness?.moralis_dashboard_color,
                actual: risk.provider_readiness?.moralis_actual_payload_present,
                status: risk.provider_readiness?.moralis_status
            ),
            preemptivePreventedCount: risk.preemptive_edge_control?.preventedCount,
            positiveEdgeProbationSupplyState: risk.preemptive_edge_control?.positive_edge_probation_supply_state,
            positiveEdgeProbationCandidates: risk.preemptive_edge_control?.positive_edge_probation_candidates,
            positiveEdgeProbationAccepted: risk.preemptive_edge_control?.positive_edge_probation_accepted,
            closedProbationTradeCount: risk.preemptive_edge_control?.closed_probation_trade_count,
            probation5TradeGateStatus: risk.preemptive_edge_control?.probation_5_trade_gate_status,
            probationCountsAsFinalAPlus: risk.preemptive_edge_control?.probation_counts_as_final_a_plus,
            probationCountsAsLiveReady: risk.preemptive_edge_control?.probation_counts_as_live_ready,
            whyTradeWasPrevented: risk.preemptive_edge_control?.why_trade_was_prevented ?? [],
            governorAutoAction: risk.preemptive_edge_control?.governor_auto_action,
            nextRemediation: risk.preemptive_edge_control?.next_remediation,
            liveGate: risk.real_trader_readiness?.live_gate ?? risk.live_gate.gate,
            liveReady: risk.real_trader_readiness?.live_ready,
            topBlockers: risk.top_blockers ?? risk.entry_freeze?.halt_reasons ?? []
        )
    }
}

struct RuntimeTruthCard: View {
    let title: String
    let truth: RuntimeTruthDisplay

    var body: some View {
        VStack(spacing: 10) {
            SectionHeader(title: title, accent: NerVyx.signal)
            DataRow(label: "paper_session_id", value: runtimeText(truth.paperSessionId), mono: true)
            DataRow(label: "Paper equity", value: runtimeMoney(truth.equity), mono: true)
            DataRow(
                label: "new_entries_allowed",
                value: runtimeBool(truth.newEntriesAllowed, trueText: "true", falseText: "false halted"),
                valueColor: truth.newEntriesAllowed == true ? NerVyx.validation : NerVyx.sell
            )
            DataRow(label: "Governor", value: runtimeText(truth.governorState), valueColor: NerVyx.warning)
            DataRow(label: "PF", value: runtimeNumber(truth.profitFactor, digits: 3), valueColor: (truth.profitFactor ?? 0) >= 1 ? NerVyx.validation : NerVyx.sell, mono: true)
            DataRow(label: "Expectancy", value: "\(runtimeMoney(truth.expectancyUsd)) avg/trade", valueColor: (truth.expectancyUsd ?? -1) > 0 ? NerVyx.validation : NerVyx.sell, mono: true)
            DataRow(label: "Realized PnL", value: runtimeMoney(truth.realizedPnlUsd), valueColor: (truth.realizedPnlUsd ?? 0) >= 0 ? NerVyx.validation : NerVyx.sell, mono: true)
            DataRow(label: "Win rate", value: runtimePercent(truth.winRate), mono: true)
            DataRow(label: "A+ final rows", value: "\(runtimeInt(truth.finalAPlusRows)) / evaluated \(runtimeInt(truth.evaluatedAPlusRows))", valueColor: (truth.finalAPlusRows ?? 0) > 0 ? NerVyx.validation : NerVyx.warning, mono: true)
            DataRow(
                label: "REDUCE_SIZE bootstrap rows",
                value: "\(runtimeInt(truth.reduceSizeRows)) · paper-only · final A+ \(runtimeBool(truth.reduceSizeCountsAsFinalAPlus, trueText: "true", falseText: "false"))",
                valueColor: truth.reduceSizeCountsAsFinalAPlus == true ? NerVyx.sell : NerVyx.warning,
                mono: true
            )
            DataRow(label: "Trainer", value: "\(runtimeText(truth.trainerState)) · feedback rows \(runtimeInt(truth.feedbackRows))")
            DataRow(label: "Market data freshness", value: "\(runtimeText(truth.marketFreshnessState)) · source \(runtimeText(truth.marketSource))")
            DataRow(label: "Microstructure trust", value: "blocked rows \(runtimeInt(truth.microstructureTrustBlockedRows)) · public book alone not final A+")
            DataRow(
                label: "Advanced Market Structure",
                value: "\(runtimeText(truth.advancedIndicatorStatus)) · FVG \(runtimeInt(truth.advancedIndicatorFvgPresentCount))",
                valueColor: runtimeText(truth.advancedIndicatorStatus).contains("BLOCK") ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Liquidity Sweep Risk",
                value: "can block/reduce \(runtimeBool(truth.advancedIndicatorSweepRiskCanBlock, trueText: "true", falseText: "false")) · accepted blocks \(runtimeInt(truth.advancedIndicatorBlockCount))",
                valueColor: (truth.advancedIndicatorBlockCount ?? 0) > 0 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "FVG Zones",
                value: "standalone approval \(runtimeBool(truth.advancedIndicatorFvgAloneAllowsTrade, trueText: "true", falseText: "false"))",
                valueColor: truth.advancedIndicatorFvgAloneAllowsTrade == true ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Preemptive Action",
                value: runtimeText(truth.preemptiveAction),
                valueColor: (truth.preemptiveAction ?? "").hasPrefix("ALLOW_A_PLUS") ? NerVyx.buy : NerVyx.sell,
                mono: true
            )
            DataRow(
                label: "Pre-Trade Loss Risk",
                value: "\(runtimeNumber(truth.preTradeLossProbability, digits: 3)) · prevented \(runtimeInt(truth.preemptivePreventedCount)) · \(truth.preemptiveDecisionId.map { String($0.prefix(18)) } ?? "no decision")",
                valueColor: (truth.preTradeLossProbability ?? 0) >= 0.8 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Confidence Overstatement Risk",
                value: runtimeNumber(truth.confidenceOverstatementRisk, digits: 3),
                valueColor: (truth.confidenceOverstatementRisk ?? 0) >= 0.75 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Regime Compatibility",
                value: runtimeNumber(truth.regimeCompatibilityScore, digits: 3),
                valueColor: (truth.regimeCompatibilityScore ?? 1) < 0.45 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Exit Feasibility",
                value: runtimeNumber(truth.exitFeasibilityScore, digits: 3),
                valueColor: (truth.exitFeasibilityScore ?? 1) < 0.55 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Bucket Health",
                value: "PF \(runtimeNumber(truth.bucketProfitFactor, digits: 3))",
                valueColor: (truth.bucketProfitFactor ?? 1) < 1 ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Adaptive leverage",
                value: "\(truth.leverageDistribution.map { runtimeNumber($0, digits: 2) }.joined(separator: ", "))x · notional \(runtimeMoney(truth.notionalDistributionUsd.first))",
                valueColor: truth.leverageDistribution.contains(where: { $0 > 1 }) ? NerVyx.warning : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Hedge / delta",
                value: "\(runtimeText(truth.hedgeState)) · net \(runtimeMoney(truth.netDeltaUsd)) · gross \(runtimeMoney(truth.grossExposureUsd))",
                valueColor: runtimeText(truth.hedgeState) == "NO HEDGE" ? NerVyx.textSecondary : NerVyx.warning,
                mono: true
            )
            DataRow(
                label: "Cross-margin simulation",
                value: "\(runtimeBool(truth.crossMarginSafe, trueText: "safe", falseText: "isolated/no trade")) · \(runtimeText(truth.marginCallRisk)) risk",
                valueColor: truth.crossMarginSafe == true ? NerVyx.warning : NerVyx.textSecondary,
                mono: true
            )
            DataRow(
                label: "Provider actual data",
                value: "CoinGlass \(runtimeText(truth.coinglassStatus)) · Moralis \(runtimeText(truth.moralisStatus))",
                mono: true
            )
            DataRow(
                label: "Why Trade Was Prevented",
                value: truth.whyTradeWasPrevented.prefix(3).joined(separator: ", ").isEmpty ? "no prevented trade reason reported" : nervyxPublicRuntimeText(truth.whyTradeWasPrevented.prefix(3).joined(separator: ", "))
            )
            DataRow(
                label: "Positive-Edge Probation",
                value: "\(runtimeText(truth.positiveEdgeProbationSupplyState)) · candidates \(runtimeInt(truth.positiveEdgeProbationCandidates)) · accepted \(runtimeInt(truth.positiveEdgeProbationAccepted))",
                valueColor: (truth.positiveEdgeProbationCandidates ?? 0) > 0 ? NerVyx.warning : NerVyx.sell,
                mono: true
            )
            DataRow(
                label: "Probation 5-Trade Gate",
                value: "\(runtimeText(truth.probation5TradeGateStatus)) · closes \(runtimeInt(truth.closedProbationTradeCount))",
                valueColor: NerVyx.warning,
                mono: true
            )
            DataRow(
                label: "Probation Proof Flags",
                value: "final A+ \(runtimeBool(truth.probationCountsAsFinalAPlus, trueText: "true", falseText: "false")) · live \(runtimeBool(truth.probationCountsAsLiveReady, trueText: "true", falseText: "false"))",
                valueColor: (truth.probationCountsAsFinalAPlus == true || truth.probationCountsAsLiveReady == true) ? NerVyx.sell : NerVyx.textSecondary,
                mono: true
            )
            DataRow(label: "Governor Auto-Action", value: runtimeText(truth.governorAutoAction), valueColor: runtimeText(truth.governorAutoAction).contains("halt") ? NerVyx.sell : NerVyx.textSecondary)
            DataRow(label: "Next Remediation", value: runtimeText(truth.nextRemediation))
            DataRow(label: "Live gate", value: runtimeText(truth.liveGate), valueColor: NerVyx.sell)
            DataRow(label: "Real trader readiness", value: runtimeBool(truth.liveReady, trueText: "live_ready true", falseText: "live_ready false"), valueColor: truth.liveReady == true ? NerVyx.warning : NerVyx.sell)
            DataRow(label: "Top blockers", value: truth.topBlockers.prefix(3).joined(separator: ", ").isEmpty ? "no blocker reported" : truth.topBlockers.prefix(3).joined(separator: ", "))
            DataRow(label: "Why blocked", value: truth.topBlockers.prefix(3).joined(separator: ", ").isEmpty ? "no blocker reported" : truth.topBlockers.prefix(3).joined(separator: ", "))
        }
        .nerVyxCard(accent: NerVyx.signal.opacity(0.25))
    }
}

struct RuntimeTruthLiveCard: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    let title: String
    @State private var summary: MobilePaperSummary?
    @State private var error: String?

    var body: some View {
        Group {
            if let summary {
                RuntimeTruthCard(title: title, truth: .paperSummary(summary))
            } else {
                VStack(spacing: 10) {
                    SectionHeader(title: title, accent: NerVyx.signal)
                    DataRow(label: "paper_session_id", value: "loading current API", mono: true)
                    DataRow(label: "Runtime truth", value: error ?? "loading /api/v2/mobile/paper-summary")
                }
                .nerVyxCard(accent: NerVyx.signal.opacity(0.25))
            }
        }
        .task { await load() }
    }

    private func load() async {
        do {
            summary = try await APIClient.shared.get(
                path: APIEndpoints.mobilePaperSummary,
                token: auth.currentToken(),
                baseURL: appState.baseURL
            )
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
