import SwiftUI

// MARK: - Trainer Telemetry / AI
//
// Renders GET /api/v2/trainer/status (TrainerDeepStatus): trainer state,
// runtime mode, champion/challenger evaluation, offline pretrain, GPU runtime,
// model-edge backtest and readiness blockers.
//
// Honesty rules:
//   • Freshness comes from backend fields only (freshness_status /
//     staleness_seconds) — a held trainer lane must read STALE, never LIVE.
//   • Extended blocks are conditionally emitted — an absent block renders an
//     honest "not published" note and an absent field renders "—", never 0.
//   • Win rates and metrics come from backend fields only — no client-side
//     recomputation.

// MARK: - Local formatting helpers (nil-honest)

private func tText(_ value: String?) -> String {
    guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return "—" }
    return nervyxPublicRuntimeText(value)
}

private func tNumber(_ value: Double?, decimals: Int = 2) -> String {
    NerVyxFormat.number(value, decimals: decimals)
}

private func tCount(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "—" }
    return String(Int(value))
}

private func tCountInt(_ value: Int?) -> String {
    NerVyxFormat.count(value)
}

private func tBool(_ value: Bool?) -> String {
    guard let value else { return "—" }
    return value ? "true" : "false"
}

/// Percent truth: backend emits some fields as 0–100 (data_coverage) and some
/// as 0–1 fractions. Same heuristic the RuntimeTruthCard uses: a magnitude
/// <= 1 is treated as a fraction.
private func tPercentValue(_ value: Double?) -> String {
    guard let value, value.isFinite else { return "—" }
    let percent = abs(value) <= 1 ? value * 100 : value
    return String(format: "%.1f%%", percent)
}

// MARK: - Screen

struct TrainerTelemetryView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = TrainerTelemetryViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.status == nil {
                    loadingReplica
                } else if let err = vm.error, vm.status == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else if let status = vm.status {
                    content(status)
                } else {
                    ErrorStateView(message: "Trainer status not available") {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .nerVyxScreen()
            .navigationTitle("AI")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.primary)
                    }
                    .disabled(vm.isLoading)
                }
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Loading replica

    private var loadingReplica: some View {
        ScrollView {
            VStack(spacing: 14) {
                ForEach(0..<4, id: \.self) { _ in
                    VStack(alignment: .leading, spacing: 10) {
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 26)
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 96)
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

    private func content(_ status: TrainerDeepStatus) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                headerCard(status)
                blockerCard(status)
                runtimeModeCard(status.runtime_mode)
                championChallengerCard(status.champion_challenger_status)
                offlinePretrainCard(status.offline_pretrain_status)
                gpuRuntimeCard(status.gpu_runtime)
                modelEdgeCard(status.model_edge_backtest)
                learningExtraCard(status.learning_metrics_extra)
                sourceFooter(status)
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Header (state / model / freshness truth)

    private func headerCard(_ status: TrainerDeepStatus) -> some View {
        let stateText = tText(status.state)
        let stateColor: Color = vm.isStale ? NerVyx.warning : NerVyx.validation
        return VStack(spacing: 12) {
            HStack(spacing: 12) {
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 26))
                    .foregroundStyle(NerVyx.primary)
                VStack(alignment: .leading, spacing: 3) {
                    Text(stateText.uppercased())
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(stateColor)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                    Text(tText(status.model_source))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                }
                Spacer(minLength: 6)
                StalenessChip.from(stale: vm.isStale, ageSeconds: vm.stalenessSeconds)
            }
            NerVyxDivider()
            HStack(spacing: 8) {
                NerVyxBadge(
                    text: tText(status.live_gate).uppercased(),
                    color: status.live_ready == true ? NerVyx.warning : NerVyx.sell,
                    small: true
                )
                NerVyxBadge(
                    text: status.cuda_active == true ? "CUDA ACTIVE" : "CUDA —",
                    color: status.cuda_active == true ? NerVyx.validation : NerVyx.textMuted,
                    small: true
                )
                Spacer()
            }
            DataRow(label: "Model", value: tText(status.model_id), mono: true)
            DataRow(label: "Checkpoint", value: tText(status.checkpoint_id), mono: true)
            DataRow(label: "Data coverage", value: tPercentValue(status.data_coverage), mono: true)
            DataRow(label: "Win rate 30d", value: tPercentValue(status.win_rate_30d), mono: true)
            DataRow(label: "Episodes total", value: tCountInt(status.episodes_total), mono: true)
            DataRow(
                label: "Drift watch · alarm",
                value: "\(tCountInt(status.drift_watch_count)) · \(tCountInt(status.drift_alarm_count))",
                mono: true
            )
        }
        .nerVyxGlassCard(accent: vm.isStale ? NerVyx.warning : NerVyx.primary)
    }

    // MARK: - Readiness blockers (exact backend reasons, no summarizing)

    @ViewBuilder
    private func blockerCard(_ status: TrainerDeepStatus) -> some View {
        let chain = vm.blockerChain
        if !chain.isEmpty || status.exact_no_live_reason != nil {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(
                    title: "Readiness blockers",
                    accent: NerVyx.warning,
                    trailing: "\(chain.count) active"
                )
                if let reason = status.exact_no_live_reason, !reason.isEmpty {
                    DataRow(label: "Exact no-live reason", value: tText(reason), valueColor: NerVyx.warning, mono: true)
                }
                if chain.isEmpty {
                    Text("No blocker chain reported")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted)
                } else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 6)], alignment: .leading, spacing: 6) {
                        ForEach(chain, id: \.self) { blocker in
                            Text(blocker)
                                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                                .foregroundStyle(NerVyx.warning)
                                .lineLimit(3)
                                .minimumScaleFactor(0.8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 6)
                                .background(NerVyx.warning.opacity(0.10))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(NerVyx.warning.opacity(0.30), lineWidth: 1)
                                )
                        }
                    }
                }
            }
            .nerVyxGlassCard(accent: NerVyx.warning)
        }
    }

    // MARK: - Runtime mode

    private func runtimeModeCard(_ mode: TrainerRuntimeMode?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Runtime mode", accent: NerVyx.inference)
            if let mode {
                Group {
                    DataRow(label: "Effective mode", value: tText(mode.effective_trainer_mode), mono: true)
                    DataRow(label: "Online learning", value: tText(mode.online_learning_status), mono: true)
                    DataRow(label: "CUDA inference", value: tText(mode.cuda_inference_status), mono: true)
                    DataRow(label: "Trainer process", value: tText(mode.trainer_process_status), mono: true)
                    DataRow(label: "Prediction publication", value: tText(mode.prediction_publication_status), mono: true)
                    DataRow(
                        label: "Examples built · failures",
                        value: "\(tCount(mode.prediction_examples_built)) · \(tCount(mode.prediction_failure_count))",
                        mono: true
                    )
                }
                Group {
                    DataRow(
                        label: "Replay buffer",
                        value: "\(tCount(mode.replay_buffer_size)) / \(tCount(mode.replay_buffer_limit))",
                        mono: true
                    )
                    DataRow(label: "Symbols", value: tCount(mode.symbols_count), mono: true)
                    DataRow(
                        label: "Timeframes",
                        value: (mode.timeframes?.isEmpty == false) ? mode.timeframes!.joined(separator: " ") : "—",
                        mono: true
                    )
                    DataRow(label: "Shadow only", value: tBool(mode.paper_shadow_only), mono: true)
                    DataRow(
                        label: "Checkpoint promoted this cycle",
                        value: tBool(mode.checkpoint_promoted_this_cycle),
                        valueColor: mode.checkpoint_promoted_this_cycle == true ? NerVyx.validation : NerVyx.textSecondary,
                        mono: true
                    )
                    if let reason = mode.checkpoint_promotion_reason, !reason.isEmpty {
                        DataRow(label: "Promotion reason", value: tText(reason), mono: true)
                    }
                }
            } else {
                honestEmpty("Runtime-mode block not published in the current status payload")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: - Champion / challenger

    private func championChallengerCard(_ cc: ChampionChallengerStatus?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Champion vs challenger", accent: NerVyx.primary)
            if let cc {
                HStack(spacing: 8) {
                    NerVyxBadge(
                        text: cc.challengerLabel,
                        color: cc.isPaperReady ? NerVyx.validation : (cc.hasEvidence ? NerVyx.warning : NerVyx.textMuted),
                        small: true
                    )
                    NerVyxBadge(
                        text: "PROMOTION \(cc.promotionLabel)",
                        color: cc.promotion_allowed == true ? NerVyx.validation : NerVyx.warning,
                        small: true
                    )
                    Spacer()
                }
                DataRow(label: "Result", value: tText(cc.result_status), mono: true)
                DataRow(label: "Best challenger", value: tText(cc.best_challenger_id), mono: true)
                DataRow(label: "Replay windows processed", value: tCountInt(cc.replay_windows_processed), mono: true)
                DataRow(label: "Replay snapshots scanned", value: tCountInt(cc.replay_snapshots_scanned), mono: true)
                DataRow(label: "Evaluated", value: tText(cc.evaluated_at_utc), mono: true)
                if let blockers = cc.blocker_reasons, !blockers.isEmpty {
                    Text("Evaluation blockers: \(blockers.joined(separator: ", "))")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.warning)
                        .lineLimit(4)
                        .minimumScaleFactor(0.8)
                }
            } else {
                honestEmpty("Champion/challenger block not published in the current status payload")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: - Offline pretrain

    private func offlinePretrainCard(_ pretrain: TrainerOfflinePretrainStatus?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Offline pretrain", accent: NerVyx.signal)
            if let pretrain {
                DataRow(
                    label: "Phase",
                    value: tText(pretrain.phase),
                    valueColor: (pretrain.phase ?? "").uppercased().contains("ABORT") ? NerVyx.warning : NerVyx.textPrimary,
                    mono: true
                )
                DataRow(label: "Generated", value: tText(pretrain.generated_utc), mono: true)
                DataRow(
                    label: "Promoted",
                    value: tBool(pretrain.promoted),
                    valueColor: pretrain.promoted == true ? NerVyx.validation : NerVyx.textSecondary,
                    mono: true
                )
                DataRow(label: "Auto promote", value: tBool(pretrain.auto_promote), mono: true)
                DataRow(label: "Risk gate required", value: tBool(pretrain.require_risk_gate), mono: true)
                DataRow(label: "Duration", value: NerVyxFormat.age(pretrain.duration_seconds), mono: true)
                DataRow(label: "H2L decision", value: tText(pretrain.h2l_decision), mono: true)
                DataRow(
                    label: "Sortino · CVaR (offline)",
                    value: "\(tNumber(pretrain.sortino_offline)) · \(tNumber(pretrain.cvar_offline))",
                    mono: true
                )
            } else {
                honestEmpty("Offline-pretrain block not published in the current status payload")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    // MARK: - GPU runtime

    private func gpuRuntimeCard(_ gpu: TrainerGPURuntime?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "GPU runtime", accent: NerVyx.inference)
            if let gpu {
                Group {
                    DataRow(label: "GPU", value: tText(gpu.gpu_name), mono: true)
                    DataRow(label: "CUDA available", value: tBool(gpu.cuda_available), mono: true)
                    DataRow(label: "Model device", value: tText(gpu.model_device), mono: true)
                    DataRow(
                        label: "VRAM used / cap",
                        value: "\(tNumber(gpu.current_vram_used_mb, decimals: 0)) / \(tNumber(gpu.vram_cap_mb, decimals: 0)) MB",
                        mono: true
                    )
                    DataRow(label: "GPU train time", value: gpu.gpu_train_time_ms.map { "\(tNumber($0, decimals: 0)) ms" } ?? "—", mono: true)
                    DataRow(label: "Data loader time", value: gpu.data_loader_time_ms.map { "\(tNumber($0, decimals: 0)) ms" } ?? "—", mono: true)
                }
                Group {
                    DataRow(label: "Backtest rows/s", value: tNumber(gpu.backtest_rows_per_second, decimals: 0), mono: true)
                    DataRow(label: "Predictions/s", value: tNumber(gpu.throughput_predictions_per_second, decimals: 0), mono: true)
                    DataRow(label: "Train steps/min", value: tNumber(gpu.training_steps_per_minute, decimals: 1), mono: true)
                    DataRow(label: "Mixed precision", value: tBool(gpu.mixed_precision_enabled), mono: true)
                    DataRow(label: "OOM count", value: tCount(gpu.oom_count), mono: true)
                    DataRow(
                        label: "Batch target / actual",
                        value: "\(tCount(gpu.target_batch_size)) / \(tCount(gpu.actual_batch_size))",
                        mono: true
                    )
                }
            } else {
                honestEmpty("GPU-runtime block not published in the current status payload")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.inference)
    }

    // MARK: - Model edge backtest

    private func modelEdgeCard(_ edge: TrainerModelEdgeBacktest?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Model edge backtest", accent: NerVyx.primary)
            if let edge {
                DataRow(label: "Status", value: tText(edge.status), mono: true)
                DataRow(label: "Win rate", value: tPercentValue(edge.win_rate), mono: true)
                DataRow(label: "Expectancy after cost", value: edge.expectancy_after_cost_bps.map { "\(tNumber($0)) bps" } ?? "—", mono: true)
                DataRow(label: "Profit factor proxy", value: tNumber(edge.profit_factor_proxy), mono: true)
                DataRow(label: "Rows evaluated", value: tCount(edge.rows_evaluated), mono: true)
                DataRow(label: "A+ readiness signal", value: tText(edge.a_plus_readiness_signal), mono: true)
                DataRow(label: "Evidence class", value: tText(edge.evidence_class), mono: true)
            } else {
                honestEmpty("Model-edge backtest block not published in the current status payload")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: - Learning metrics extra

    private func learningExtraCard(_ extra: TrainerLearningMetricsExtra?) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Learning metrics", accent: NerVyx.signal)
            if let extra {
                DataRow(label: "Train/val generalization gap", value: tNumber(extra.train_val_generalization_gap, decimals: 4), mono: true)
                DataRow(label: "Validation loss delta", value: tNumber(extra.validation_loss_delta, decimals: 4), mono: true)
                DataRow(label: "Validation supervised loss", value: tNumber(extra.validation_supervised_loss, decimals: 4), mono: true)
                DataRow(
                    label: "Val loss before → after",
                    value: "\(tNumber(extra.validation_supervised_loss_before, decimals: 4)) → \(tNumber(extra.validation_supervised_loss_after, decimals: 4))",
                    mono: true
                )
                DataRow(label: "Loss after", value: tNumber(extra.loss_after, decimals: 4), mono: true)
                DataRow(
                    label: "Overfit gap warning",
                    value: tBool(extra.overfit_gap_warning),
                    valueColor: extra.overfit_gap_warning == true ? NerVyx.warning : NerVyx.textSecondary,
                    mono: true
                )
            } else {
                honestEmpty("Learning-metrics block not published in the current status payload")
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    // MARK: - Source footer

    private func sourceFooter(_ status: TrainerDeepStatus) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            DataRow(label: "Status generated", value: tText(status.generated_at_utc), mono: true)
            DataRow(label: "Freshness", value: tText(status.freshness_status), valueColor: vm.isStale ? NerVyx.warning : NerVyx.validation, mono: true)
            DataRow(label: "Staleness age", value: NerVyxFormat.age(status.staleness_seconds), mono: true)
        }
        .padding(.horizontal, 4)
    }

    // MARK: - Honest-empty note

    private func honestEmpty(_ message: String) -> some View {
        Text(message)
            .font(.system(size: 12))
            .foregroundStyle(NerVyx.textMuted)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}
