import SwiftUI

// MARK: - Risk Control screen (NERVYX GUARD)
//
// Streams /api/v2/mobile/risk-status through the dedicated RiskViewModel
// (WebSocket resource socket + 30s HTTP fallback). It no longer borrows
// AdminViewModel — that view model is freed back to the Admin screen.
//
// Safety invariant: the live-gate and kill-switch banners keep their
// sell-red fills and are NEVER softened. Every risk number is decoded from
// the real payload; anything the backend does not publish renders an honest
// em-dash with a "not published" footnote — no invented values.

struct RiskControlView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = RiskViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.riskStatus == nil {
                    loadingReplica
                } else if let err = vm.error, vm.riskStatus == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else if let risk = vm.riskStatus {
                    riskContent(risk)
                } else {
                    loadingReplica
                }
            }
            .nerVyxScreen()
            .navigationTitle("NERVYX GUARD")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                    }
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Content

    private func riskContent(_ risk: MobileRiskStatus) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                headerStrip
                safetyBanners(risk)
                budgetBlock(risk)
                marginBlock(risk)
                if let hedge = risk.hedge {
                    hedgeCard(hedge)
                }
                dangerousActionsNote(risk)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Header + freshness truth

    private var headerStrip: some View {
        HStack(spacing: 10) {
            Image(systemName: "shield.lefthalf.filled")
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.signal)
            MicroLabel(text: "Risk Gateway")
            Spacer()
            freshnessChip
        }
    }

    private var freshnessChip: StalenessChip {
        if vm.riskStatus == nil || vm.payloadUnavailable { return .offline() }
        return .from(
            stale: vm.lastSnapshotStale,
            lagMs: vm.lastSnapshotLagMs,
            transport: vm.lastSnapshotTransport,
            ageSeconds: vm.extras?.staleness_seconds
        )
    }

    // MARK: - Section blocks (kept ≤10 children each for the SwiftUI type-checker)

    private func safetyBanners(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 14) {
            liveGateCard(risk.live_gate)
            liveReadinessCard(risk.real_trader_readiness, gate: risk.live_gate)
            killSwitchCard(risk)
        }
    }

    private func budgetBlock(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 14) {
            gaugesCard(risk)
            RuntimeTruthCard(title: "Runtime Truth", truth: .risk(risk))
            riskClassificationCard(risk)
            limitsCard(risk)
        }
    }

    private func marginBlock(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 14) {
            crossMarginCard(risk)
            protectionsCard(risk)
            gateStatsCard(risk)
        }
    }

    // MARK: - Live gate banner (SELL-RED — never softened)

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

    // MARK: - Live readiness banner (operator approval BLOCKED — mirrors website)

    private func liveReadinessCard(_ readiness: MobileRuntimeReadiness?, gate: LiveGateState) -> some View {
        let ready = readiness?.live_ready ?? false
        let flipRequired = readiness?.operator_flip_required ?? true
        let submitAllowed = readiness?.live_submit_allowed ?? false
        let reason = readiness?.exact_no_live_reason
        let blockers = readiness?.readiness_blockers ?? []
        let accent = ready ? NerVyx.validation : NerVyx.sell
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                Image(systemName: ready ? "checkmark.seal.fill" : "lock.trianglebadge.exclamationmark.fill")
                    .font(.system(size: 20))
                    .foregroundStyle(accent)
                VStack(alignment: .leading, spacing: 2) {
                    MicroLabel(text: "Live Readiness")
                    Text(ready ? "READY — OPERATOR FLIP STILL REQUIRED" : "NOT LIVE-READY")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(accent)
                        .lineLimit(2)
                        .minimumScaleFactor(0.7)
                }
                Spacer()
            }
            operatorApprovalChip(gate: gate)
            DataRow(
                label: "Live-ready",
                value: ready ? "YES" : "NO",
                valueColor: accent
            )
            DataRow(
                label: "Operator flip required",
                value: flipRequired ? "YES" : "NO",
                valueColor: flipRequired ? NerVyx.warning : NerVyx.validation
            )
            DataRow(
                label: "Live submit allowed",
                value: submitAllowed ? "YES" : "NO",
                valueColor: submitAllowed ? NerVyx.sell : NerVyx.validation
            )
            if let reason, !reason.isEmpty {
                DataRow(
                    label: "Exact reason",
                    value: nervyxPublicRuntimeText(reason),
                    valueColor: NerVyx.warning,
                    mono: true
                )
            }
            if !blockers.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(Array(blockers.prefix(6).enumerated()), id: \.offset) { _, blocker in
                        HStack(alignment: .top, spacing: 6) {
                            Image(systemName: "circle.fill")
                                .font(.system(size: 4))
                                .foregroundStyle(NerVyx.sell)
                                .padding(.top, 6)
                            Text(nervyxPublicRuntimeText(blocker))
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(NerVyx.textSecondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.top, 2)
            }
        }
        .padding(14)
        .background(accent.opacity(ready ? 0.06 : 0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(accent.opacity(0.3), lineWidth: 1))
    }

    private func operatorApprovalChip(gate: LiveGateState) -> some View {
        // Live trading is human-gated (blocked_human_only). We never render an
        // "enabled" state — only BLOCKED, mirroring the website wording.
        let blocked = !gate.live_trading_enabled
        let text = blocked ? "OPERATOR APPROVAL: BLOCKED" : "OPERATOR APPROVAL: RECORDED"
        let color = blocked ? NerVyx.sell : NerVyx.warning
        return HStack(spacing: 5) {
            Image(systemName: "person.badge.shield.checkmark.fill")
                .font(.system(size: 10))
            Text(text)
                .font(.system(size: 10, weight: .bold))
                .tracking(0.4)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.15))
        .clipShape(Capsule())
        .overlay(Capsule().stroke(color.opacity(0.4), lineWidth: 1))
    }

    // MARK: - Kill switch banner (SELL-RED — never softened)

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

    // MARK: - Risk budget gauges (daily-loss consumed + liquidation buffer at risk)

    private func gaugesCard(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 12) {
            SectionHeader(title: "Risk Budget", accent: NerVyx.warning)
            HStack(alignment: .top, spacing: 18) {
                dailyLossGauge(risk)
                liqBufferGauge(risk)
            }
            .frame(maxWidth: .infinity)
            positionHeadroomRow(risk)
        }
        .nerVyxGlassCard(accent: NerVyx.warning.opacity(0.35))
    }

    private func dailyLossGauge(_ risk: MobileRiskStatus) -> some View {
        let limit = risk.daily_loss_limit_usd
        let used = risk.current_daily_loss_usd
        let hasLimit = limit > 0
        let frac: Double = hasLimit ? min(max(used / limit, 0), 1) : 0
        return VStack(spacing: 6) {
            RingGauge(
                value: frac,
                label: "DAILY LOSS",
                centerText: hasLimit ? "\(Int((frac * 100).rounded()))%" : "—",
                color: hasLimit ? gaugeSeverity(frac) : NerVyx.textMuted
            )
            Text(hasLimit ? "\(NerVyxFormat.money(used)) / \(NerVyxFormat.money(limit))" : "no limit set")
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
    }

    private func liqBufferGauge(_ risk: MobileRiskStatus) -> some View {
        let cm = risk.adaptive_hedge_cross_margin
        let worst = cm?.worst_case_portfolio_loss_usd
        let buffer = cm?.portfolio_liquidation_buffer_usd
        let hasData = (worst != nil) && (buffer ?? 0) > 0
        let frac: Double = hasData ? min(max((worst ?? 0) / (buffer ?? 1), 0), 1) : 0
        return VStack(spacing: 6) {
            RingGauge(
                value: frac,
                label: "LIQ BUFFER AT RISK",
                centerText: hasData ? NerVyxFormat.percent(frac, decimals: frac < 0.1 ? 2 : 1) : "—",
                color: hasData ? gaugeSeverity(frac) : NerVyx.textMuted
            )
            Text(hasData ? "\(NerVyxFormat.money(worst)) at risk" : "not published")
                .font(.system(size: 9, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
    }

    private func positionHeadroomRow(_ risk: MobileRiskStatus) -> some View {
        let maxSize = risk.max_position_size_usd
        let gross = risk.adaptive_hedge_cross_margin?.gross_exposure_usd
        let hasLimit = maxSize > 0
        let headroom: Double? = hasLimit ? max(0, 1 - min((gross ?? 0) / maxSize, 1)) : nil
        return VStack(spacing: 6) {
            HBarRow(
                label: "HEADROOM",
                value: headroom ?? 0,
                maxAbsValue: 1,
                valueText: headroom.map { NerVyxFormat.percent($0) } ?? "—",
                color: NerVyx.paper
            )
            if !hasLimit {
                notPublishedFootnote("Max position size not published — headroom unavailable")
            }
        }
    }

    // MARK: - Risk gateway state

    private func riskClassificationCard(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Risk Gateway State", accent: NerVyx.validation)
            DataRow(
                label: "State",
                value: risk.risk_state,
                valueColor: NerVyx.statusColor(risk.risk_state)
            )
            if let classification = risk.risk_classification {
                DataRow(label: "Classification", value: nervyxPublicRuntimeText(classification), valueColor: NerVyx.paper)
            }
            if let failClosed = risk.fail_closed {
                DataRow(
                    label: "Fail closed",
                    value: failClosed ? "YES" : "NO",
                    valueColor: failClosed ? NerVyx.validation : NerVyx.warning
                )
            }
            if let decisions = risk.decisions_processed_total {
                DataRow(label: "Decisions processed", value: "\(decisions)", mono: true)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.validation.opacity(0.3))
    }

    // MARK: - Risk limits

    private func limitsCard(_ risk: MobileRiskStatus) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Risk Limits", accent: NerVyx.warning)
            DataRow(
                label: "Max position size",
                value: risk.max_position_size_usd > 0 ? NerVyxFormat.money(risk.max_position_size_usd) : "—",
                mono: true
            )
            DataRow(
                label: "Daily loss limit",
                value: risk.daily_loss_limit_usd > 0 ? NerVyxFormat.money(risk.daily_loss_limit_usd) : "—",
                mono: true
            )
            DataRow(
                label: "Current daily loss",
                value: NerVyxFormat.money(risk.current_daily_loss_usd),
                valueColor: risk.current_daily_loss_usd > 0 ? NerVyx.sell : NerVyx.validation,
                mono: true
            )
            if risk.max_position_size_usd <= 0 && risk.daily_loss_limit_usd <= 0 {
                notPublishedFootnote("Limits report 0 while the gateway is halted / paper-only")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.warning.opacity(0.3))
    }

    // MARK: - Cross-margin & liquidation (stress, buffer, maintenance, margin-call)

    private func crossMarginCard(_ risk: MobileRiskStatus) -> some View {
        let cm = risk.adaptive_hedge_cross_margin
        let stress = vm.extras?.adaptive_hedge_cross_margin
        let published = cm != nil || stress != nil
        return VStack(spacing: 10) {
            SectionHeader(
                title: "Cross-Margin & Liquidation",
                accent: NerVyx.inference,
                trailing: cm?.cross_margin_state.map { nervyxPublicRuntimeText($0) }
            )
            Group {
                DataRow(
                    label: "Margin-call risk",
                value: (cm?.margin_call_risk).map { $0.uppercased() } ?? "—",
                valueColor: marginRiskColor(cm?.margin_call_risk),
                mono: true
            )
            DataRow(
                label: "Cross-margin safe",
                value: cm?.cross_margin_safe.map { $0 ? "YES" : "NO" } ?? "—",
                valueColor: (cm?.cross_margin_safe == true) ? NerVyx.validation : NerVyx.warning
            )
            DataRow(
                label: "Maintenance margin",
                value: NerVyxFormat.money(stress?.maintenance_margin_estimate_usd),
                mono: true
            )
            DataRow(
                label: "Cross-margin stress used",
                value: NerVyxFormat.money(stress?.cross_margin_stress_used_usd),
                valueColor: NerVyx.warning,
                mono: true
            )
            DataRow(
                label: "Available buffer",
                value: NerVyxFormat.money(stress?.cross_margin_available_buffer_usd ?? cm?.portfolio_liquidation_buffer_usd),
                valueColor: NerVyx.validation,
                mono: true
            )
            }
            Group {
            DataRow(
                label: "Worst-case loss",
                value: NerVyxFormat.money(cm?.worst_case_portfolio_loss_usd),
                valueColor: NerVyx.sell,
                mono: true
            )
            DataRow(label: "Net delta", value: NerVyxFormat.money(cm?.net_delta_usd), mono: true)
            DataRow(label: "Gross exposure", value: NerVyxFormat.money(cm?.gross_exposure_usd), mono: true)
            longShortSplit(stress)
            DataRow(
                label: "Recommended mode",
                value: (stress?.recommended_margin_mode ?? cm?.cross_margin_state).map { nervyxPublicRuntimeText($0) } ?? "—",
                mono: true
            )
            }
            if !published {
                notPublishedFootnote("Cross-margin model not published by backend")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference.opacity(0.4))
    }

    @ViewBuilder
    private func longShortSplit(_ stress: RiskCrossMarginStressDetail?) -> some View {
        if let long = stress?.long_exposure_usd, let short = stress?.short_exposure_usd, (long + short) > 0 {
            SplitBar(leftValue: long, rightValue: short, leftLabel: "LONG", rightLabel: "SHORT")
        }
    }

    // MARK: - Microstructure protections (sweep risk)

    private func protectionsCard(_ risk: MobileRiskStatus) -> some View {
        let adv = risk.preemptive_edge_control?.advanced_indicators
        let sweep = adv?.sweep_risk_can_block_or_reduce
        let fvgAlone = adv?.fvg_alone_can_approve_trade
        return VStack(spacing: 10) {
            SectionHeader(title: "Microstructure Protections", accent: NerVyx.primary)
            DataRow(
                label: "Sweep risk can block / reduce",
                value: enabledText(sweep),
                valueColor: (sweep == true) ? NerVyx.validation : NerVyx.warning
            )
            DataRow(
                label: "FVG alone can approve trade",
                value: enabledText(fvgAlone),
                valueColor: (fvgAlone == true) ? NerVyx.warning : NerVyx.validation
            )
            DataRow(
                label: "Advanced indicator status",
                value: (adv?.status).map { nervyxPublicRuntimeText($0) } ?? "—",
                mono: true
            )
            if adv == nil {
                notPublishedFootnote("Advanced indicator matrix not published")
            }
        }
        .nerVyxGlassCard()
    }

    // MARK: - Gate activity

    private func gateStatsCard(_ risk: MobileRiskStatus) -> some View {
        let accepted = Double(risk.paper_accepted_count)
        let blocked = Double(risk.paper_blocked_count)
        return VStack(spacing: 12) {
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
            if accepted + blocked > 0 {
                MiniBarChart(entries: [
                    MiniBarChart.Entry(label: "ACCEPT", value: accepted, color: NerVyx.buy),
                    MiniBarChart.Entry(label: "BLOCK", value: blocked, color: NerVyx.sell),
                ])
            }
        }
        .nerVyxGlassCard()
    }

    // MARK: - Hedge engine posture

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
            DataRow(
                label: "Liq. buffer",
                value: NerVyxFormat.money(hedge.portfolio_liquidation_buffer_usd),
                mono: true
            )
            DataRow(
                label: "Cross-margin",
                value: (hedge.cross_margin_model ?? "portfolio_level").replacingOccurrences(of: "_", with: " ")
            )
            ForEach(Array((hedge.hedge_required_candidates ?? []).prefix(5).enumerated()), id: \.offset) { _, candidate in
                DataRow(
                    label: "\(candidate.symbol ?? "—") \((candidate.side ?? "").uppercased())",
                    value: NerVyxFormat.money(candidate.unrealized_pnl_usd, signed: true),
                    valueColor: (candidate.unrealized_pnl_usd ?? 0) < 0 ? NerVyx.sell : NerVyx.validation,
                    mono: true
                )
            }
            DataRow(
                label: "Exchange route",
                value: (hedge.places_real_order ?? false) ? "PLACES ORDER" : "no live order",
                valueColor: (hedge.places_real_order ?? false) ? NerVyx.sell : NerVyx.validation
            )
        }
        .nerVyxGlassCard(accent: accent.opacity(0.3))
    }

    // MARK: - Dangerous controls note

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
            if let adminURL = URL(string: appState.baseURL + "/admin") {
                Link("Open Web Admin ↗", destination: adminURL)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(NerVyx.signal)
            }
        }
        .padding(14)
        .background(NerVyx.warning.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.warning.opacity(0.3), lineWidth: 1))
    }

    // MARK: - Shared helpers

    private func notPublishedFootnote(_ text: String) -> some View {
        HStack(spacing: 5) {
            Image(systemName: "info.circle")
                .font(.system(size: 9))
                .foregroundStyle(NerVyx.textMuted)
            Text(text)
                .font(.system(size: 10))
                .foregroundStyle(NerVyx.textMuted)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func enabledText(_ value: Bool?) -> String {
        guard let value else { return "—" }
        return value ? "ENABLED" : "DISABLED"
    }

    private func gaugeSeverity(_ fraction: Double) -> Color {
        if fraction < 0.5 { return NerVyx.validation }
        if fraction < 0.8 { return NerVyx.warning }
        return NerVyx.sell
    }

    private func marginRiskColor(_ level: String?) -> Color {
        switch (level ?? "").uppercased() {
        case "LOW": return NerVyx.validation
        case "MEDIUM", "MODERATE", "ELEVATED": return NerVyx.warning
        case "HIGH", "CRITICAL", "SEVERE": return NerVyx.sell
        default: return NerVyx.textMuted
        }
    }

    // MARK: - Loading (redacted replica of the real layout)

    private var loadingReplica: some View {
        ScrollView {
            VStack(spacing: 14) {
                HStack {
                    Capsule().fill(NerVyx.panel).frame(width: 120, height: 18)
                    Spacer()
                    Capsule().fill(NerVyx.panel).frame(width: 72, height: 18)
                }
                RoundedRectangle(cornerRadius: 12).fill(NerVyx.panel).frame(height: 74)
                RoundedRectangle(cornerRadius: 12).fill(NerVyx.panel).frame(height: 116)
                HStack(spacing: 18) {
                    Circle().fill(NerVyx.panel).frame(width: 82, height: 82)
                    Circle().fill(NerVyx.panel).frame(width: 82, height: 82)
                }
                .frame(maxWidth: .infinity)
                .nerVyxGlassCard(accent: NerVyx.warning)
                ForEach(0..<3, id: \.self) { _ in
                    VStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 8).fill(NerVyx.panel).frame(height: 18)
                        RoundedRectangle(cornerRadius: 8).fill(NerVyx.panel).frame(height: 90)
                    }
                    .nerVyxGlassCard()
                }
            }
            .padding(16)
        }
        .redacted(reason: .placeholder)
    }
}
