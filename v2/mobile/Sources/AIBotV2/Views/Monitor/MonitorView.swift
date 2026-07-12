import SwiftUI

struct MonitorView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = DashboardViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.health == nil {
                        loadingView
                    } else if let err = vm.error, vm.health == nil {
                        errorView(err)
                    } else {
                        monitorContent
                    }
                }
            }
            .navigationTitle("NERVYX OBSERVE")
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

    private var loadingView: some View {
        VStack(spacing: 12) {
            ProgressView().tint(NerVyx.primary)
            Text("Connecting monitor stream…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
        }
    }

    private func errorView(_ msg: String) -> some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
            Text(msg).font(.system(size: 14)).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                .foregroundStyle(NerVyx.signal)
        }.padding(32)
    }

    private var monitorContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                if let h = vm.health {
                    systemOverviewCard(h)
                    RuntimeTruthLiveCard(title: "Runtime Truth")
                    if let ingestors = h.ingestors {
                        ingestorsCard(ingestors)
                    }
                    trainerHealthCard(h.trainer)
                    gpuHealthCard(h.gpu)
                    paperHealthCard(h.paper)
                }
                // Stream status
                HStack(spacing: 8) {
                    LivePulse(color: vm.health != nil ? NerVyx.validation : NerVyx.textMuted)
                    Text(vm.streamSummary)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                }
                .padding(.horizontal, 4)
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Cards

    private func systemOverviewCard(_ h: MobileHealth) -> some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(h.isHealthy ? NerVyx.validation.opacity(0.15) : NerVyx.warning.opacity(0.15))
                    .frame(width: 48, height: 48)
                Image(systemName: h.isHealthy ? "checkmark.shield.fill" : "exclamationmark.shield.fill")
                    .font(.system(size: 22))
                    .foregroundStyle(h.isHealthy ? NerVyx.validation : NerVyx.warning)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text("System \(h.overall.uppercased())")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(h.isHealthy ? NerVyx.validation : NerVyx.warning)
                HStack(spacing: 10) {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(h.redis_connected ? NerVyx.validation : NerVyx.sell)
                            .frame(width: 6, height: 6)
                        Text("Redis \(h.redis_connected ? "connected" : "offline")")
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                    NerVyxBadge(text: nervyxPublicRuntimeText(h.live_gate).uppercased(), color: NerVyx.sell, small: true)
                }
            }
            Spacer()
            NerVyxBadge(
                text: h.places_real_order ? "LIVE" : "GATED",
                color: h.places_real_order ? NerVyx.sell : NerVyx.signal
            )
        }
        .padding(14)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(
            h.isHealthy ? NerVyx.validation.opacity(0.3) : NerVyx.warning.opacity(0.3), lineWidth: 1
        ))
    }

    private func ingestorsCard(_ ing: MobileIngestorRollup) -> some View {
        let streams: [(String, String)] = [
            ("candles", "Candles / OHLCV"),
            ("orderbook_features", "Orderbook features"),
            ("trade_tape", "Trade tape"),
            ("funding_oi", "Funding / OI"),
            ("liquidation_levels", "Liquidation levels"),
            ("ta_full", "TA-Lib (full)"),
            ("feature_snapshots", "Feature snapshots"),
        ]
        let overall = ing.overall_status ?? "UNKNOWN"
        let accent: Color = overall == "HEALTHY" ? NerVyx.validation
            : overall == "SOME_PROVIDERS_STALE" ? NerVyx.warning : NerVyx.sell
        return VStack(spacing: 10) {
            SectionHeader(title: "Ingestors & Providers", accent: accent)
            DataRow(
                label: "Overall",
                value: overall.replacingOccurrences(of: "_", with: " "),
                valueColor: accent
            )
            HStack(spacing: 10) {
                NerVyxStatCard(
                    label: "ACTIVE PROV",
                    value: "\(ing.active_provider_count ?? 0)",
                    valueColor: (ing.active_provider_count ?? 0) > 0 ? NerVyx.validation : NerVyx.warning,
                    accent: NerVyx.signal
                )
                NerVyxStatCard(
                    label: "STALE PROV",
                    value: "\(ing.stale_provider_count ?? 0)",
                    valueColor: (ing.stale_provider_count ?? 0) > 0 ? NerVyx.warning : NerVyx.validation,
                    accent: (ing.stale_provider_count ?? 0) > 0 ? NerVyx.warning : NerVyx.validation
                )
            }
            ForEach(streams, id: \.0) { key, label in
                let present = ing.stream_present?[key] ?? false
                DataRow(
                    label: label,
                    value: present ? "flowing" : "absent",
                    valueColor: present ? NerVyx.validation : NerVyx.sell
                )
            }
        }
        .nerVyxCard(accent: accent.opacity(0.3))
    }

    private func trainerHealthCard(_ t: HealthTrainer) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Trainer · NERVYX CORE", accent: NerVyx.primary)
            DataRow(
                label: "State",
                value: t.shortState.uppercased(),
                valueColor: NerVyx.statusColor(t.state)
            )
            DataRow(
                label: "Device",
                value: t.device ?? (t.cuda_active ? "cuda:0" : "cpu"),
                valueColor: t.cuda_active ? NerVyx.signal : NerVyx.textMuted,
                mono: true
            )
            DataRow(
                label: "GPU",
                value: t.gpu_name ?? (t.cuda_active ? "Active" : "—"),
                valueColor: t.cuda_active ? NerVyx.validation : NerVyx.textMuted
            )
            DataRow(
                label: "CUDA",
                value: t.cuda_active ? "Active" : "Inactive",
                valueColor: t.cuda_active ? NerVyx.validation : NerVyx.warning
            )
            DataRow(
                label: "Training",
                value: t.training_active ? "Active" : "Inference only",
                valueColor: t.training_active ? NerVyx.buy : NerVyx.paper
            )
            NerVyxDivider()
            HStack {
                Text("Checkpoint")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                Spacer()
                Text(t.shortCheckpoint)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(NerVyx.primary)
                    .lineLimit(1)
            }
        }
        .nerVyxElevatedCard(accent: NerVyx.primary)
    }

    private func gpuHealthCard(_ g: HealthGPU) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "GPU · \(g.displayName)", accent: NerVyx.inference)
            HStack(spacing: 16) {
                // Utilization
                VStack(alignment: .leading, spacing: 6) {
                    Text("UTILIZATION")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text("\(Int(g.utilization_pct))%")
                        .font(.system(size: 24, weight: .bold, design: .monospaced))
                        .foregroundStyle(g.utilization_pct > 85 ? NerVyx.warning : NerVyx.inference)
                    ConfidenceBar(value: g.utilization_pct / 100)
                }
                .frame(maxWidth: .infinity)
                // VRAM
                VStack(alignment: .leading, spacing: 6) {
                    Text("VRAM")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                        .tracking(0.6)
                    Text(String(format: "%.1f GB", Double(g.vram_used_mb) / 1024))
                        .font(.system(size: 24, weight: .bold, design: .monospaced))
                        .foregroundStyle(Double(g.vram_used_mb) / Double(max(g.vram_total_mb, 1)) > 0.9 ? NerVyx.warning : NerVyx.signal)
                    ConfidenceBar(value: Double(g.vram_used_mb) / Double(max(g.vram_total_mb, 1)))
                }
                .frame(maxWidth: .infinity)
            }
            if g.temperature_c > 0 {
                DataRow(
                    label: "Temperature",
                    value: "\(Int(g.temperature_c))°C",
                    valueColor: g.temperature_c > 80 ? NerVyx.sell : g.temperature_c > 70 ? NerVyx.warning : NerVyx.validation,
                    mono: true
                )
            }
            DataRow(
                label: "Total VRAM",
                value: String(format: "%.1f GB", Double(g.vram_total_mb) / 1024),
                mono: true
            )
        }
        .nerVyxCard(accent: NerVyx.inference.opacity(0.3))
    }

    private func paperHealthCard(_ p: HealthPaper) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Runtime Loop · NERVYX EXECUTE", accent: NerVyx.paper)
            DataRow(label: "Classification", value: p.classification, valueColor: NerVyx.paper)
            DataRow(label: "Open Positions", value: "\(p.open_positions)")
            DataRow(label: "Intents Accepted", value: "\(p.intents_accepted)", valueColor: NerVyx.buy)
            DataRow(label: "Intents Blocked", value: "\(p.intents_blocked)", valueColor: NerVyx.sell)
        }
        .nerVyxCard(accent: NerVyx.paper.opacity(0.3))
    }
}
