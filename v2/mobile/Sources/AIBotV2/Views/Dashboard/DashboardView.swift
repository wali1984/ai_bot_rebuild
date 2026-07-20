import Foundation
import SwiftUI

// MARK: - Mission Control (Dashboard)
//
// Premium glass rebuild on the NERVYX MOBILE VISUAL LANGUAGE v2 design system.
// Every freshness signal is derived from real envelope metadata via the
// StalenessChip — no hardcoded "LIVE" labels. Account KPIs (equity / available /
// exposure / open positions / realized / risk) read the fields the backend
// /api/v2/mobile/dashboard already emits (paper.equity, paper.available_balance_usd,
// paper.used_balance). The 1000x goal card reads /api/v2/goal/trajectory-1000x.
// Win rate is the backend winner-flag rate ONLY — never recomputed from
// cumulative PnL. Live trading is BLOCKED and rendered as OPERATOR GATED.

struct DashboardView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DashboardViewModel()
    @State private var healthVM = SelfHealingViewModel()
    @State private var gpuSeries = RollingSeries(capacity: 80)

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyxScreenBackground()
                ScrollView {
                    VStack(spacing: 16) {
                        if let banner = healthVM.banner {
                            SelfHealingBannerView(banner: banner)
                        }
                        streamBar
                        RuntimeTruthLiveCard(title: "Runtime Truth")
                        if vm.isLoading && vm.dashboard == nil {
                            loadingContent
                        } else if let err = vm.error, vm.dashboard == nil {
                            nerVyxError(err)
                        } else {
                            mainContent
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
                }
            }
            .navigationTitle("Mission Control")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } } label: {
                        Image(systemName: "arrow.clockwise")
                            .foregroundStyle(NerVyx.signal)
                    }
                    .disabled(vm.isLoading)
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .onAppear {
            vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
            healthVM.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL)
        }
        .onDisappear {
            vm.stopAutoRefresh()
            healthVM.stop()
        }
        .onChange(of: vm.dashboard?.gpu.utilization_pct) { _, newValue in
            if let newValue { gpuSeries.append(newValue) }
        }
    }

    // MARK: - Freshness truth

    /// Single source of freshness truth for the whole screen. Derived from the
    /// decoded envelope (stale flag / lag_ms / transport) plus payload age —
    /// never a hardcoded label.
    private var freshnessChip: StalenessChip {
        if vm.dashboard == nil { return StalenessChip.offline() }
        return StalenessChip.from(
            stale: vm.isEffectivelyStale,
            lagMs: vm.dashboardLagMs,
            transport: vm.dashboardTransport,
            ageSeconds: vm.dataAgeSeconds
        )
    }

    // MARK: - Stream bar

    private var streamBar: some View {
        HStack(spacing: 8) {
            freshnessChip
            Text(vm.streamSummary)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer()
            NerVyxBadge(text: NervyxBrand.liveBlockedLabel.uppercased(), color: NerVyx.sell, small: true)
        }
        .padding(.horizontal, 4)
        .padding(.top, 4)
    }

    // MARK: - Loading / Error

    /// Redacted replica of the real layout (KPI grid + PnL hero + a chart card)
    /// so the skeleton matches what resolves — not generic gray blocks.
    private var loadingContent: some View {
        VStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader(title: "Account", accent: NerVyx.primary)
                LazyVGrid(columns: kpiColumns, spacing: 16) {
                    KPICell(label: "Equity", value: "$1,000.00")
                    KPICell(label: "Available", value: "$1,000.00", color: NerVyx.paper)
                    KPICell(label: "Exposure", value: "$0.00", color: NerVyx.inference)
                    KPICell(label: "Open Pos", value: "0", color: NerVyx.paper)
                    KPICell(label: "Realized", value: "+$0.00", color: NerVyx.buy)
                    KPICell(label: "Risk", value: "NORMAL", color: NerVyx.validation)
                }
            }
            .nerVyxGlassCard(accent: NerVyx.primary)

            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(title: "Portfolio PnL", accent: NerVyx.buy)
                HeroMetricText(text: "+$0.00", size: 36, color: NerVyx.buy)
                HStack(spacing: 8) {
                    NerVyxBadge(text: "REALIZED +$0.00", color: NerVyx.buy, small: true)
                    NerVyxBadge(text: "UNREALIZED +$0.00", color: NerVyx.buy, small: true)
                    Spacer()
                }
            }
            .nerVyxGlassCard(accent: NerVyx.buy)

            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(title: "Performance", accent: NerVyx.primary, trailing: "0 closed")
                RoundedRectangle(cornerRadius: 8)
                    .fill(NerVyx.panel)
                    .frame(height: 96)
            }
            .nerVyxGlassCard(accent: NerVyx.primary)
        }
        .redacted(reason: .placeholder)
    }

    private func nerVyxError(_ msg: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36))
                .foregroundStyle(NerVyx.warning)
            Text(msg)
                .font(.system(size: 14))
                .foregroundStyle(NerVyx.textSecondary)
                .multilineTextAlignment(.center)
            Button("Retry") {
                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
            }
            .foregroundStyle(NerVyx.signal)
        }
        .padding(24)
        .nerVyxGlassCard(accent: NerVyx.warning)
    }

    // MARK: - Main content

    @ViewBuilder
    private var mainContent: some View {
        if let d = vm.dashboard {
            gateStatusBanner(d.live_gate)
            kpiGrid(d, extras: vm.paperExtras)
            runtimeChips(d)
            pnlSection(d.paper)
            if let goal = vm.goal {
                goalTrajectorySection(goal)
            } else if let gErr = vm.goalError {
                goalAbsentCard(gErr)
            }
            performanceChartsSection(d.paper, extras: vm.paperExtras)
            paperLoopSection(d.paper)
            trainerSection(d.trainer)
            gpuSection(d.gpu)
            if !d.alerts_preview.isEmpty {
                alertsPreview(d.alerts_preview)
            }
        }
        if let h = vm.health {
            healthFooter(h)
        }
    }

    // MARK: - Gate banner (keeps sell-red safety styling — never glass)

    private func gateStatusBanner(_ gate: LiveGateState) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "lock.shield.fill")
                .font(.system(size: 18))
                .foregroundStyle(NerVyx.sell)
            VStack(alignment: .leading, spacing: 2) {
                Text(gate.publicLabel)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(NerVyx.sell)
                Text("Exchange route: \(gate.exchangeRouteLabel)")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
            }
            Spacer()
            Text(gate.publicGate)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(NerVyx.sell)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(NerVyx.sell.opacity(0.15))
                .clipShape(Capsule())
                .overlay(Capsule().stroke(NerVyx.sell.opacity(0.3), lineWidth: 1))
        }
        .padding(14)
        .background(NerVyx.sell.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.sell.opacity(0.25), lineWidth: 1))
    }

    // MARK: - Account KPI grid (2x3)

    private var kpiColumns: [GridItem] {
        [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())]
    }

    private func kpiGrid(_ d: MobileDashboard, extras: DashboardPaperExtras?) -> some View {
        let paper = d.paper
        let equity = paper.effectiveEquity
        let available = extras?.available_balance_usd
        let exposure = extras?.used_balance
        let realized = paper.realized_pnl_usd
        let risk = riskStatus(paper)
        return VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Account", accent: NerVyx.primary, trailing: "PAPER SIM")
            LazyVGrid(columns: kpiColumns, spacing: 16) {
                KPICell(label: "Equity", value: NerVyxFormat.money(equity))
                KPICell(label: "Available", value: NerVyxFormat.money(available), color: NerVyx.paper)
                KPICell(
                    label: "Exposure",
                    value: NerVyxFormat.money(exposure),
                    color: (exposure ?? 0) > 0 ? NerVyx.inference : NerVyx.textMuted
                )
                KPICell(
                    label: "Open Pos",
                    value: "\(paper.open_positions)",
                    color: paper.open_positions > 0 ? NerVyx.paper : NerVyx.textMuted
                )
                KPICell(
                    label: "Realized",
                    value: NerVyxFormat.money(realized, signed: true),
                    color: NerVyx.pnlColor(realized)
                )
                KPICell(label: "Risk", value: risk.text, color: risk.color)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    /// Risk-gate truth from the paper runtime's entry-freeze state. Distinct from
    /// the live-execution gate (which is always BLOCKED); this reflects whether
    /// the risk layer currently permits new paper entries.
    private func riskStatus(_ paper: PaperState) -> (text: String, color: Color) {
        if let allowed = paper.new_entries_allowed {
            return allowed ? ("NORMAL", NerVyx.validation) : ("HALTED", NerVyx.warning)
        }
        return ("—", NerVyx.textMuted)
    }

    // MARK: - Runtime quick chips

    private func runtimeChips(_ d: MobileDashboard) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                StatChip(label: "Signals", value: "\(d.active_signal_count ?? 0)", color: NerVyx.signal, accent: NerVyx.signal)
                StatChip(label: "Trainer", value: d.trainer.shortState.uppercased(), color: NerVyx.statusColor(d.trainer.state), accent: NerVyx.primary)
                StatChip(label: "GPU", value: "\(Int(d.gpu.utilization_pct))%", color: NerVyx.inference, accent: NerVyx.inference)
                StatChip(label: "Redis", value: d.redis_connected ? "OK" : "OFF", color: d.redis_connected ? NerVyx.validation : NerVyx.sell, accent: NerVyx.borderStrong)
            }
            .padding(.horizontal, 2)
        }
    }

    // MARK: - Portfolio PnL (hero + honest freshness)

    private func pnlSection(_ paper: PaperState) -> some View {
        let pnlColor = NerVyx.pnlColor(paper.total_pnl)
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionHeader(title: "Portfolio PnL", accent: pnlColor)
                Spacer()
                freshnessChip
            }
            HeroMetricText(text: NerVyxFormat.money(paper.total_pnl, signed: true), size: 36, color: pnlColor)
            HStack(spacing: 8) {
                NerVyxBadge(
                    text: "REALIZED \(NerVyxFormat.money(paper.realized_pnl_usd, signed: true))",
                    color: NerVyx.pnlColor(paper.realized_pnl_usd),
                    small: true
                )
                NerVyxBadge(
                    text: "UNREALIZED \(NerVyxFormat.money(paper.unrealized_pnl_usd, signed: true))",
                    color: NerVyx.pnlColor(paper.unrealized_pnl_usd),
                    small: true
                )
                Spacer()
                StatChip(
                    label: "Mode",
                    value: nervyxPublicRuntimeText(paper.classification).uppercased(),
                    color: NerVyx.paper,
                    accent: NerVyx.paper
                )
            }
        }
        .nerVyxGlassCard(accent: pnlColor)
    }

    // MARK: - Goal / 1000x trajectory

    private func goalTrajectorySection(_ goal: GoalTrajectoryData) -> some View {
        let target = goal.target_multiple ?? 1000
        let mult = goal.multiple_now
        let logProgress: Double = {
            guard let m = mult, m > 0, target > 1 else { return 0 }
            return max(0, min(1, log(m) / log(target)))
        }()
        let onTrack = goal.on_track == true
        let ringColor = onTrack ? NerVyx.validation : NerVyx.warning
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                SectionHeader(title: "Goal · \(Int(target))x Trajectory", accent: NerVyx.validation)
                Spacer()
                StalenessChip.from(stale: vm.goalStale, transport: "http", ageSeconds: goal.age_seconds)
            }
            HStack(alignment: .top, spacing: 18) {
                RingGauge(
                    value: logProgress,
                    label: "OF \(Int(target))x",
                    centerText: mult.map { String(format: "%.2fx", $0) } ?? "—",
                    color: ringColor,
                    size: 96
                )
                VStack(alignment: .leading, spacing: 8) {
                    DataRow(label: "Equity", value: NerVyxFormat.money(goal.equity_usd), mono: true)
                    DataRow(label: "Start", value: NerVyxFormat.money(goal.starting_equity_usd), mono: true)
                    DataRow(
                        label: "Daily rate",
                        value: "\(NerVyxFormat.number(goal.actual_daily_rate_pct, decimals: 2))% / \(NerVyxFormat.number(goal.required_daily_rate_pct, decimals: 2))% req",
                        valueColor: onTrack ? NerVyx.validation : NerVyx.warning,
                        mono: true
                    )
                    if let stage = goal.growth_stage?.stage, !stage.isEmpty {
                        DataRow(label: "Stage", value: stage.uppercased(), valueColor: NerVyx.primary)
                    }
                    if let constraint = goal.binding_constraint?.constraint, !constraint.isEmpty {
                        DataRow(label: "Binding", value: constraint.replacingOccurrences(of: "_", with: " ").uppercased(), valueColor: NerVyx.warning)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack(spacing: 8) {
                NerVyxBadge(text: onTrack ? "ON TRACK" : "BEHIND PACE", color: ringColor, small: true)
                if let days = goal.days_elapsed {
                    NerVyxBadge(text: "DAY \(Int(days))", color: NerVyx.primary, small: true)
                }
                Spacer()
            }
            Text("Research objective, not a promise. 1000x is a long-horizon target gated by evidence and survival-first risk controls.")
                .font(.system(size: 10))
                .foregroundStyle(NerVyx.textMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .nerVyxGlassCard(accent: NerVyx.validation)
    }

    private func goalAbsentCard(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Goal · 1000x Trajectory", accent: NerVyx.textMuted)
            Text("Trajectory evidence unavailable")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(NerVyx.textSecondary)
            Text(message)
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
                .lineLimit(2)
        }
        .nerVyxGlassCard(accent: NerVyx.borderStrong)
    }

    // MARK: - Performance charts

    @ViewBuilder
    private func performanceChartsSection(_ paper: PaperState, extras: DashboardPaperExtras?) -> some View {
        let trend = paper.equityTrend
        let perTrade = paper.perTradePnl
        let accuracy = extras?.signal_prediction_accuracy
        if trend.count > 1 || !perTrade.isEmpty || paper.win_count != nil || accuracy?.overall_accuracy != nil {
            VStack(alignment: .leading, spacing: 14) {
                SectionHeader(title: "Performance", accent: NerVyx.primary, trailing: "\(paper.closed_trades) closed")
                if trend.count > 1 {
                    VStack(alignment: .leading, spacing: 6) {
                        MicroLabel(text: "Equity Curve")
                        AxisSparkline(
                            values: trend,
                            color: NerVyx.primary,
                            height: 96,
                            valueFormatter: { NerVyxFormat.compactUSD($0) }
                        )
                    }
                }
                HStack(alignment: .top, spacing: 16) {
                    winLossDonut(paper)
                    if !perTrade.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            MicroLabel(text: "Per-Trade PnL")
                            DivergingBars(values: perTrade)
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                if let accuracy, let overall = accuracy.overall_accuracy {
                    predictionAccuracy(accuracy, overall: overall)
                }
            }
            .nerVyxGlassCard(accent: NerVyx.primary)
        }
    }

    /// Win/loss donut using backend winner-flag counts VERBATIM. Never recompute
    /// the rate from cumulative PnL — the true win rate (~37%) is the winner-flag
    /// rate and must be trusted as-is; absent counts render "—".
    @ViewBuilder
    private func winLossDonut(_ paper: PaperState) -> some View {
        if let wins = paper.win_count, let losses = paper.loss_count, (wins + losses) > 0 {
            DonutChart(
                slices: [
                    .init(label: "Wins", value: Double(wins), color: NerVyx.buy),
                    .init(label: "Losses", value: Double(losses), color: NerVyx.sell),
                ],
                centerText: NerVyxFormat.percent(paper.win_rate),
                centerLabel: "WIN RATE"
            )
        } else {
            VStack(spacing: 6) {
                Text("—")
                    .font(.system(size: 22, weight: .bold, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                MicroLabel(text: "Win Rate")
            }
            .frame(width: 96, height: 118)
        }
    }

    private func predictionAccuracy(_ accuracy: DashboardPredictionAccuracy, overall: Double) -> some View {
        let rows = (accuracy.by_timeframe ?? [])
            .filter { $0.accuracy != nil }
            .prefix(3)
        return VStack(alignment: .leading, spacing: 8) {
            NerVyxDivider()
            HStack {
                MicroLabel(text: "Prediction Accuracy")
                Spacer()
                Text(NerVyxFormat.percent(overall))
                    .font(.system(size: 13, weight: .bold, design: .monospaced))
                    .foregroundStyle(overall >= 0.5 ? NerVyx.validation : NerVyx.warning)
            }
            ForEach(Array(rows)) { row in
                HBarRow(
                    label: (row.timeframe ?? "—").uppercased(),
                    value: row.accuracy ?? 0,
                    maxAbsValue: 1,
                    valueText: NerVyxFormat.percent(row.accuracy),
                    color: (row.accuracy ?? 0) >= 0.5 ? NerVyx.validation : NerVyx.warning
                )
            }
        }
    }

    // MARK: - Signal runtime loop

    private func paperLoopSection(_ paper: PaperState) -> some View {
        VStack(spacing: 12) {
            SectionHeader(title: "Signal Runtime Loop", accent: NerVyx.paper, trailing: "\(paper.closed_trades) closed")
            HStack(spacing: 16) {
                MiniBarChart(entries: [
                    .init(label: "SEEN", value: Double(paper.signals_seen), color: NerVyx.paper),
                    .init(label: "ACCEPTED", value: Double(paper.intents_accepted), color: NerVyx.buy),
                    .init(label: "BLOCKED", value: Double(paper.intents_blocked), color: NerVyx.sell),
                ])
                .frame(maxWidth: .infinity)
                RingGauge(
                    value: paper.acceptanceRate / 100,
                    label: "ACCEPTANCE",
                    centerText: String(format: "%.0f%%", paper.acceptanceRate),
                    color: paper.acceptanceRate > 50 ? NerVyx.buy : NerVyx.warning,
                    size: 74
                )
            }
        }
        .nerVyxGlassCard(accent: NerVyx.paper)
    }

    // MARK: - Trainer

    private func trainerSection(_ trainer: TrainerState) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Trainer · NERVYX CORE", accent: NerVyx.primary)
            DataRow(
                label: "State",
                value: trainer.shortState.uppercased(),
                valueColor: NerVyx.statusColor(trainer.state)
            )
            DataRow(
                label: "Device",
                value: trainer.device ?? (trainer.cuda_active ? "cuda:0" : "cpu"),
                valueColor: trainer.cuda_active ? NerVyx.signal : NerVyx.textMuted,
                mono: true
            )
            DataRow(
                label: "GPU",
                value: trainer.gpu_name ?? (trainer.cuda_active ? "Active" : "—"),
                valueColor: trainer.cuda_active ? NerVyx.validation : NerVyx.textMuted
            )
            DataRow(
                label: "Steps total",
                value: "\(trainer.training_steps_total.formatted())",
                mono: true
            )
            DataRow(
                label: "Steps / hr",
                value: "\(trainer.training_steps_last_hour.formatted())",
                mono: true
            )
            DataRow(
                label: "Model input",
                value: trainer.input_dim != nil ? "\(trainer.input_dim!.formatted()) dims · \(trainer.feature_count.map { "\($0) feats" } ?? "—")" : "—",
                mono: true
            )
            DataRow(
                label: "Temporal",
                value: trainer.temporalLabel.uppercased(),
                valueColor: (trainer.temporal_encoder_enabled == true) ? NerVyx.validation : NerVyx.textMuted
            )
            if let mode = trainer.effective_trainer_mode, !mode.isEmpty {
                DataRow(
                    label: "Mode",
                    value: mode.replacingOccurrences(of: "_", with: " "),
                    valueColor: NerVyx.primary
                )
            }
            if trainer.online_learning_status != nil || trainer.weights_updating != nil {
                DataRow(
                    label: "Online learning",
                    value: trainer.learningLabel,
                    valueColor: (trainer.weights_updating == true || trainer.online_learning_status?.uppercased() == "WEIGHTS_UPDATING") ? NerVyx.validation : NerVyx.warning
                )
            }
            if let win = trainer.backtest_win_rate {
                DataRow(
                    label: "Model win rate",
                    value: String(format: "%.1f%%", win * 100) + (trainer.backtest_expectancy_bps.map { String(format: " · %+.1f bps", $0) } ?? ""),
                    valueColor: win >= 0.55 ? NerVyx.validation : (win >= 0.5 ? NerVyx.warning : NerVyx.sell),
                    mono: true
                )
            }
            if let tput = trainer.throughput_predictions_per_second {
                DataRow(
                    label: "Throughput",
                    value: String(format: "%.1f pred/s", tput) + (trainer.vram_used_mb.map { String(format: " · %.1f GB VRAM", $0 / 1024) } ?? ""),
                    mono: true
                )
            }
            if let gap = trainer.generalization_gap {
                DataRow(
                    label: "Overfit gap",
                    value: String(format: "%.2f", gap) + (trainer.validation_loss_delta.map { String(format: " · Δval %+.3f", $0) } ?? ""),
                    valueColor: gap > 5 ? NerVyx.warning : NerVyx.validation,
                    mono: true
                )
            }
            DataRow(
                label: "Challenger",
                value: trainer.champion_challenger_status?.challengerLabel ?? "AWAITING EVIDENCE",
                valueColor: {
                    guard let cc = trainer.champion_challenger_status else { return NerVyx.textMuted }
                    if !cc.hasEvidence { return NerVyx.textMuted }
                    return cc.isPaperReady ? NerVyx.validation : NerVyx.warning
                }()
            )
            DataRow(
                label: "Promotion",
                value: trainer.champion_challenger_status?.promotionLabel ?? "AWAITING EVIDENCE",
                valueColor: {
                    guard let cc = trainer.champion_challenger_status else { return NerVyx.textMuted }
                    if cc.promotion_allowed == true { return NerVyx.validation }
                    if !cc.hasEvidence { return NerVyx.textMuted }
                    // Paper-ready but live/A-grade is operator-gated by design: informational, not an error.
                    return cc.isPaperReady ? NerVyx.primary : NerVyx.warning
                }()
            )
            NerVyxDivider()
            HStack {
                Text("Checkpoint")
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textMuted)
                Spacer()
                Text(trainer.shortCheckpoint)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(NerVyx.primary)
                    .lineLimit(1)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: - GPU

    private func gpuSection(_ gpu: GPUState) -> some View {
        VStack(spacing: 12) {
            SectionHeader(title: "GPU · \(gpu.displayName)", accent: NerVyx.inference)
            HStack(spacing: 18) {
                RingGauge(
                    value: gpu.utilization_pct / 100,
                    label: "UTILIZATION",
                    centerText: "\(Int(gpu.utilization_pct))%",
                    color: gpu.utilization_pct > 80 ? NerVyx.warning : NerVyx.inference
                )
                RingGauge(
                    value: gpu.vramPercent / 100,
                    label: "VRAM",
                    centerText: String(format: "%.1fG", gpu.vramUsedGB),
                    color: gpu.vramPercent > 85 ? NerVyx.warning : NerVyx.signal
                )
                VStack(alignment: .leading, spacing: 6) {
                    MicroLabel(text: "Util Trend")
                    if gpuSeries.values.count > 1 {
                        Sparkline(values: gpuSeries.values, color: NerVyx.inference)
                            .frame(height: 52)
                    } else {
                        Text("collecting…")
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                            .frame(maxWidth: .infinity, minHeight: 52)
                    }
                    Text(String(format: "%.1f / %.1f GB VRAM", gpu.vramUsedGB, gpu.vramTotalGB))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: - Alerts

    private func alertsPreview(_ alerts: [MobileAlert]) -> some View {
        VStack(spacing: 8) {
            SectionHeader(title: "Recent Alerts", accent: NerVyx.warning, trailing: "\(alerts.count) total")
            ForEach(alerts.prefix(3)) { alert in
                HStack(alignment: .top, spacing: 10) {
                    Circle()
                        .fill(alertSeverityColor(alert.severity))
                        .frame(width: 7, height: 7)
                        .padding(.top, 5)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("[\(alert.symbol)] \(alert.type)")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(NerVyx.textPrimary)
                        Text(alert.message)
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                            .lineLimit(2)
                    }
                    Spacer()
                    NerVyxBadge(text: alert.severity.uppercased(), color: alertSeverityColor(alert.severity), small: true)
                }
            }
        }
        .nerVyxGlassCard(accent: NerVyx.warning)
    }

    // MARK: - Health footer

    private func healthFooter(_ h: MobileHealth) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(h.isHealthy ? NerVyx.validation : NerVyx.warning)
                .frame(width: 8, height: 8)
            Text("System: \(h.overall)")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
            Spacer()
            Text("Redis: \(h.redis_connected ? "connected" : "offline")")
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(h.redis_connected ? NerVyx.validation : NerVyx.sell)
        }
        .padding(.horizontal, 4)
    }

    private func alertSeverityColor(_ s: String) -> Color {
        switch s.lowercased() {
        case "critical": return NerVyx.sell
        case "warning": return NerVyx.warning
        default: return NerVyx.inference
        }
    }
}

// MARK: - KPI cell

/// Compact account KPI tile: micro-label + mono hero value with numeric
/// count-up transition. Absent values arrive pre-rendered as "—".
private struct KPICell: View {
    let label: String
    let value: String
    var color: Color = NerVyx.textPrimary
    var sub: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            MicroLabel(text: label)
            Text(value)
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
                .contentTransition(.numericText())
            if let sub {
                Text(sub)
                    .font(.system(size: 9))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
