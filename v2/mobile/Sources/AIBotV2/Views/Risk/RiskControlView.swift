import SwiftUI

struct RiskControlView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AdminViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.riskStatus == nil {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting risk gateway stream…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.riskStatus == nil {
                        VStack(spacing: 12) {
                            Image(systemName: "exclamationmark.triangle").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
                            Text(err).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
                            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                                .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else if let risk = vm.riskStatus {
                        riskContent(risk)
                    }
                }
            }
            .navigationTitle("NERVYX GUARD")
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
    }

    private func riskContent(_ risk: MobileRiskStatus) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                liveGateCard(risk.live_gate)
                RuntimeTruthCard(title: "Runtime Truth", truth: .risk(risk))
                killSwitchCard(risk)
                riskClassificationCard(risk)
                limitsCard(risk)
                gateStatsCard(risk)
                if let hedge = risk.hedge {
                    hedgeCard(hedge)
                }
                dangerousActionsNote(risk)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Cards

    private func liveGateCard(_ gate: LiveGateState) -> some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(NerVyx.sell.opacity(0.15))
                    .frame(width: 52, height: 52)
                Image(systemName: "lock.shield.fill")
                    .font(.system(size: 24))
                    .foregroundStyle(NerVyx.sell)
            }
            VStack(alignment: .leading, spacing: 5) {
                Text(gate.publicLabel)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(NerVyx.sell)
                DataRow(
                    label: "Gate state",
                    value: gate.publicGate,
                    valueColor: NerVyx.sell
                )
                DataRow(
                    label: "Exchange route",
                    value: gate.exchangeRouteLabel,
                    valueColor: gate.places_real_order ? NerVyx.warning : NerVyx.validation
                )
            }
        }
        .padding(14)
        .background(NerVyx.sell.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.sell.opacity(0.3), lineWidth: 1))
    }

    private func killSwitchCard(_ risk: MobileRiskStatus) -> some View {
        HStack(spacing: 12) {
            Image(
                systemName: risk.kill_switch_active ? "exclamationmark.shield.fill" : "shield.checkmark.fill"
            )
            .font(.system(size: 20))
            .foregroundStyle(risk.kill_switch_active ? NerVyx.sell : NerVyx.validation)
            VStack(alignment: .leading, spacing: 3) {
                Text("Kill Switch")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(NerVyx.textPrimary)
                Text(risk.kill_switch_active ? "ACTIVE — All trading halted" : "Inactive — System operational")
                    .font(.system(size: 12))
                    .foregroundStyle(risk.kill_switch_active ? NerVyx.sell : NerVyx.validation)
            }
            Spacer()
            Circle()
                .fill(risk.kill_switch_active ? NerVyx.sell : NerVyx.validation)
                .frame(width: 12, height: 12)
        }
        .nerVyxCard(accent: risk.kill_switch_active ? NerVyx.sell.opacity(0.4) : NerVyx.validation.opacity(0.3))
    }

    private func riskClassificationCard(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Risk Gateway State", accent: NerVyx.validation)
            DataRow(
                label: "State",
                value: risk.risk_state,
                valueColor: NerVyx.statusColor(risk.risk_state)
            )
            if let classification = risk.risk_classification {
                DataRow(label: "Classification", value: classification, valueColor: NerVyx.paper)
            }
            if let failClosed = risk.fail_closed {
                DataRow(
                    label: "Fail Closed",
                    value: failClosed ? "YES" : "NO",
                    valueColor: failClosed ? NerVyx.warning : NerVyx.validation
                )
            }
            if let decisions = risk.decisions_processed_total {
                DataRow(
                    label: "Decisions processed",
                    value: "\(decisions.formatted())",
                    mono: true
                )
            }
        }
        .nerVyxCard()
    }

    private func limitsCard(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Risk Limits", accent: NerVyx.warning)
            DataRow(
                label: "Max Position Size",
                value: risk.max_position_size_usd > 0 ? String(format: "$%g", risk.max_position_size_usd) : "N/A",
                mono: true
            )
            DataRow(
                label: "Daily Loss Limit",
                value: risk.daily_loss_limit_usd > 0 ? String(format: "$%g", risk.daily_loss_limit_usd) : "N/A",
                mono: true
            )
            DataRow(
                label: "Current Daily Loss",
                value: String(format: "$%.2f", risk.current_daily_loss_usd),
                valueColor: risk.current_daily_loss_usd > 0 ? NerVyx.sell : NerVyx.validation,
                mono: true
            )
        }
        .nerVyxCard(accent: NerVyx.warning.opacity(0.3))
    }

    private func gateStatsCard(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Gate Activity", accent: NerVyx.signal)
            HStack(spacing: 10) {
                NerVyxStatCard(
                    label: "ACCEPTED",
                    value: "\(risk.paper_accepted_count)",
                    valueColor: NerVyx.buy,
                    accent: NerVyx.buy
                )
                NerVyxStatCard(
                    label: "BLOCKED",
                    value: "\(risk.paper_blocked_count)",
                    valueColor: NerVyx.sell,
                    accent: NerVyx.sell
                )
            }
        }
        .nerVyxCard()
    }

    private func hedgeCard(_ hedge: MobileHedgeSnapshot) -> some View {
        let needsHedge = (hedge.negative_position_count ?? 0) > 0
        let accent = needsHedge ? NerVyx.warning : NerVyx.validation
        return VStack(spacing: 10) {
            SectionHeader(title: "Hedge Engine Posture", accent: accent)
            HStack(spacing: 10) {
                NerVyxStatCard(
                    label: "OPEN",
                    value: "\(hedge.open_position_count ?? 0)",
                    valueColor: NerVyx.textPrimary,
                    accent: NerVyx.signal
                )
                NerVyxStatCard(
                    label: "NEED HEDGE",
                    value: "\(hedge.negative_position_count ?? 0)",
                    valueColor: needsHedge ? NerVyx.warning : NerVyx.validation,
                    accent: accent
                )
            }
            DataRow(
                label: "Engine",
                value: hedge.hedge_engine_active == false ? "INACTIVE" : "ACTIVE",
                valueColor: hedge.hedge_engine_active == false ? NerVyx.sell : NerVyx.validation
            )
            DataRow(
                label: "Eval mode",
                value: (hedge.hedge_evaluation_mode ?? "on_demand").replacingOccurrences(of: "_", with: " ")
            )
            if let buffer = hedge.portfolio_liquidation_buffer_usd {
                DataRow(label: "Liq. buffer", value: String(format: "$%g", buffer), mono: true)
            }
            DataRow(
                label: "Cross-margin",
                value: (hedge.cross_margin_model ?? "portfolio_level").replacingOccurrences(of: "_", with: " ")
            )
            ForEach(Array((hedge.hedge_required_candidates ?? []).prefix(5).enumerated()), id: \.offset) { _, c in
                DataRow(
                    label: "\(c.symbol ?? "—") \((c.side ?? "").uppercased())",
                    value: c.unrealized_pnl_usd.map { String(format: "$%.2f", $0) } ?? "—",
                    valueColor: (c.unrealized_pnl_usd ?? 0) < 0 ? NerVyx.sell : NerVyx.validation,
                    mono: true
                )
            }
            DataRow(
                label: "Exchange route",
                value: (hedge.places_real_order ?? false) ? "PLACES ORDER" : "no live order",
                valueColor: (hedge.places_real_order ?? false) ? NerVyx.sell : NerVyx.validation
            )
        }
        .nerVyxCard(accent: accent.opacity(0.3))
    }

    private func dangerousActionsNote(_ risk: MobileRiskStatus) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(NerVyx.warning)
                Text("Dangerous Controls")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(NerVyx.warning)
            }
            Text("Enabling live order routing, changing leverage, disabling the kill switch, and other dangerous actions require explicit human approval through the web admin interface. These actions CANNOT be approved from this app.")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
                .fixedSize(horizontal: false, vertical: true)
            if risk.mobile_can_approve_dangerous_actions == false {
                HStack(spacing: 4) {
                    Image(systemName: "lock.fill").font(.system(size: 10)).foregroundStyle(NerVyx.textMuted)
                    Text("Mobile approval: disabled")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(NerVyx.textMuted)
                }
            }
            Link("Open Web Admin ↗", destination: URL(string: appState.baseURL + "/admin")!)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(NerVyx.signal)
        }
        .padding(14)
        .background(NerVyx.warning.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.warning.opacity(0.3), lineWidth: 1))
    }
}
