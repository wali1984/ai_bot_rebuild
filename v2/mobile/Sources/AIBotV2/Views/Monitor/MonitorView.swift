import SwiftUI

// MARK: - System Monitor
//
// A focused system-health surface (not a dashboard clone). It streams
// `/api/v2/mobile/health` for overall/redis/ingestor health and layers three
// supplemental reads through `MonitorViewModel`:
//   • CORE SERVICES  — auth / backend / redis with real measured latency
//   • DATA FEEDS     — the seven canonical ingest streams with color-coded age
//   • PROVIDER HEALTH— the per-provider data-plane rollup
//   • BACKEND SURFACES — per-surface data-feed lag (System Health page source)
// Trainer/GPU are compressed into two compact health rows that link into the
// dedicated Trainer Telemetry screen (no dashboard duplication).

struct MonitorView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = MonitorViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.health == nil {
                    loadingView
                } else if let err = vm.error, vm.health == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    monitorContent
                }
            }
            .nerVyxScreen()
            .navigationTitle("NERVYX OBSERVE")
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
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - States

    private var loadingView: some View {
        ScrollView {
            VStack(spacing: 14) {
                ForEach(0..<4, id: \.self) { _ in
                    VStack(alignment: .leading, spacing: 10) {
                        SectionHeader(title: "Loading system health", accent: NerVyx.signal)
                        ForEach(0..<3, id: \.self) { _ in
                            DataRow(label: "Placeholder metric", value: "000ms")
                        }
                    }
                    .nerVyxGlassCard(accent: NerVyx.borderSubtle)
                }
            }
            .padding(16)
        }
        .redacted(reason: .placeholder)
        .allowsHitTesting(false)
    }

    private var monitorContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                if let h = vm.health {
                    systemOverviewCard(h)
                }
                coreServicesSection
                dataFeedsSection
                providerHealthSection
                backendSurfacesSection
                if let h = vm.health {
                    runtimeCompute(h)
                }
                streamFooter
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Freshness chip

    private var freshnessChip: StalenessChip {
        if vm.health == nil { return .offline() }
        return .from(
            stale: vm.isEffectivelyStale,
            lagMs: vm.lagMs,
            transport: vm.transport,
            ageSeconds: vm.dataAgeSeconds
        )
    }

    // MARK: - System overview

    private func systemOverviewCard(_ h: MonitorHealth) -> some View {
        let healthy = h.isHealthy
        let accent = healthy ? NerVyx.validation : NerVyx.warning
        return VStack(spacing: 12) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(accent.opacity(0.15))
                        .frame(width: 48, height: 48)
                    Image(systemName: healthy ? "checkmark.shield.fill" : "exclamationmark.shield.fill")
                        .font(.system(size: 22))
                        .foregroundStyle(accent)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("System \(h.overallLabel)")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(accent)
                    HStack(spacing: 8) {
                        Circle()
                            .fill((h.redis_connected ?? false) ? NerVyx.validation : NerVyx.sell)
                            .frame(width: 6, height: 6)
                        Text("Redis \((h.redis_connected ?? false) ? "connected" : "offline")")
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                }
                Spacer()
                freshnessChip
            }
            NerVyxDivider()
            HStack(spacing: 8) {
                NerVyxBadge(
                    text: nervyxPublicRuntimeText(h.live_gate ?? "blocked_human_only").uppercased(),
                    color: NerVyx.sell,
                    small: true
                )
                NerVyxBadge(
                    text: (h.places_real_order ?? false) ? "EXCHANGE LIVE" : "OPERATOR GATED",
                    color: (h.places_real_order ?? false) ? NerVyx.sell : NerVyx.signal,
                    small: true
                )
                Spacer()
            }
            if let ps = vm.publicStatus {
                DataRow(
                    label: "Runtime state",
                    value: nervyxPublicRuntimeText(ps.runtime_state ?? "—"),
                    valueColor: (ps.runtime_state ?? "").contains("ACTIVE") ? NerVyx.validation : NerVyx.warning,
                    mono: true
                )
                DataRow(
                    label: "Supervisor health",
                    value: nervyxPublicRuntimeText(ps.supervisor_health ?? "—"),
                    valueColor: (ps.supervisor_health ?? "").contains("MISSING") ? NerVyx.warning : NerVyx.textSecondary,
                    mono: true
                )
                if let dims = ps.status_dimensions {
                    DataRow(
                        label: "Market data",
                        value: (dims.market_data ?? "—").capitalized,
                        valueColor: (dims.market_data ?? "").uppercased() == "STALE" ? NerVyx.warning : NerVyx.validation,
                        mono: true
                    )
                    DataRow(
                        label: "Automation · Execution",
                        value: "\((dims.automation ?? "—").capitalized) · \((dims.execution ?? "—").capitalized)",
                        mono: true
                    )
                }
            }
        }
        .nerVyxGlassCard(accent: accent)
    }

    // MARK: - Core services (auth / backend / redis)

    private var coreServicesSection: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Core services", accent: NerVyx.inference, trailing: "measured latency")
            HStack(spacing: 10) {
                serviceCard(vm.authProbe, fallbackName: "AUTH")
                serviceCard(vm.backendProbe, fallbackName: "BACKEND")
                serviceCard(vm.redisProbe, fallbackName: "REDIS")
            }
        }
    }

    private func serviceCard(_ probe: ServiceProbe?, fallbackName: String) -> some View {
        let color: Color = probe == nil ? NerVyx.textMuted : (probe!.ok ? NerVyx.validation : NerVyx.sell)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 5) {
                Circle().fill(color).frame(width: 7, height: 7)
                MicroLabel(text: probe?.name ?? fallbackName, size: 9)
                Spacer(minLength: 0)
            }
            Text(probe?.latencyText ?? "—")
                .font(.system(size: 20, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
                .contentTransition(.numericText())
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(probe?.detail ?? "PROBING")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(NerVyx.textMuted)
                .tracking(0.4)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: color, cornerRadius: 14)
    }

    // MARK: - Data feeds (seven canonical ingest streams)

    private var dataFeedsSection: some View {
        let rows = vm.dataFeedRows
        let allFlowing = rows.allSatisfy { $0.present }
        let accent: Color = allFlowing ? NerVyx.validation : NerVyx.warning
        return VStack(spacing: 8) {
            SectionHeader(title: "Data feeds", accent: accent, trailing: allFlowing ? "all flowing" : "check streams")
            ForEach(rows) { row in
                NavigationLink { IngestorsView() } label: { dataFeedRowView(row) }
                    .buttonStyle(.plain)
            }
            NavigationLink {
                IngestorsView()
            } label: {
                HStack {
                    Text("Open live ingestor streams")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(NerVyx.signal)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(NerVyx.signal)
                }
                .padding(.top, 2)
            }
            .buttonStyle(.plain)
        }
        .nerVyxGlassCard(accent: accent.opacity(0.6))
    }

    private func dataFeedRowView(_ row: DataFeedRow) -> some View {
        let ageColor = feedAgeColor(row)
        return HStack(spacing: 10) {
            Circle()
                .fill(row.present ? ageColor : NerVyx.sell)
                .frame(width: 7, height: 7)
            Text(row.label)
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textSecondary)
            Spacer(minLength: 8)
            if !row.present {
                Text("absent")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(NerVyx.sell)
            } else {
                Text(NerVyxFormat.age(row.ageSeconds))
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(ageColor)
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(NerVyx.textMuted)
        }
        .padding(.vertical, 3)
        .contentShape(Rectangle())
    }

    private func feedAgeColor(_ row: DataFeedRow) -> Color {
        if !row.present { return NerVyx.sell }
        let f = (row.freshness ?? "").lowercased()
        if f.contains("stale") || f.contains("delayed") { return NerVyx.warning }
        if f == "unknown" { return NerVyx.textMuted }
        if let age = row.ageSeconds {
            if age > 180 { return NerVyx.warning }
            if age > 90 { return NerVyx.paper }
            return NerVyx.validation
        }
        return f == "fresh" ? NerVyx.validation : NerVyx.textMuted
    }

    // MARK: - Provider health rollup

    private var providerHealthSection: some View {
        let rows = vm.providerRows
        return VStack(spacing: 8) {
            SectionHeader(title: "Provider health", accent: NerVyx.signal, trailing: vm.providerCountLabel)
            if rows.isEmpty {
                Text("Provider rollup not reported yet")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ForEach(rows) { row in
                    providerRowView(row)
                }
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal.opacity(0.5))
    }

    private func providerRowView(_ row: ProviderHealthRow) -> some View {
        let color = providerColor(row)
        return HStack(spacing: 10) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(row.id)
                .font(.system(size: 13, design: .monospaced))
                .foregroundStyle(NerVyx.textSecondary)
                .lineLimit(1)
            Spacer(minLength: 8)
            Text((row.status ?? "unknown").replacingOccurrences(of: "_", with: " "))
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(color)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(NerVyxFormat.age(row.ageSeconds))
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
                .frame(minWidth: 40, alignment: .trailing)
        }
        .padding(.vertical, 2)
    }

    private func providerColor(_ row: ProviderHealthRow) -> Color {
        switch MonitorViewModel.freshnessRank(row.freshness, status: row.status) {
        case 0:  return NerVyx.validation
        case 2:  return NerVyx.warning
        case 3:  return NerVyx.sell
        default: return NerVyx.paper
        }
    }

    // MARK: - Backend surfaces (data-feed lag)

    private var backendSurfacesSection: some View {
        let surfaces = vm.dataFeedSurfaces
        let overall = (vm.dataHealth?.data.overall ?? "unknown")
        let accent: Color = overall.lowercased() == "ok" ? NerVyx.validation
            : overall.lowercased() == "partial" ? NerVyx.warning : NerVyx.sell
        return VStack(spacing: 8) {
            SectionHeader(title: "Backend surfaces", accent: accent, trailing: overall.uppercased())
            if surfaces.isEmpty {
                Text("Surface lag not reported yet")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ForEach(surfaces) { surface in
                    surfaceRowView(surface)
                }
            }
        }
        .nerVyxGlassCard(accent: accent.opacity(0.5))
    }

    private func surfaceRowView(_ surface: DataFeedSurface) -> some View {
        let color = surfaceColor(surface)
        return HStack(spacing: 10) {
            Circle().fill(color).frame(width: 7, height: 7)
            VStack(alignment: .leading, spacing: 1) {
                Text(surface.name)
                    .font(.system(size: 13))
                    .foregroundStyle(NerVyx.textSecondary)
                    .lineLimit(1)
                if let endpoint = surface.endpoint {
                    Text(endpoint)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
            }
            Spacer(minLength: 8)
            Text((surface.status ?? "—").uppercased())
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(color)
                .lineLimit(1)
            Text(lagText(surface.lag_ms))
                .font(.system(size: 12, weight: .semibold, design: .monospaced))
                .foregroundStyle(lagColor(surface.lag_ms))
                .frame(minWidth: 48, alignment: .trailing)
        }
        .padding(.vertical, 2)
    }

    private func surfaceColor(_ surface: DataFeedSurface) -> Color {
        if surface.stale == true { return NerVyx.warning }
        switch (surface.status ?? "").lowercased() {
        case "ok":      return NerVyx.validation
        case "pending": return NerVyx.warning
        case "error", "down", "unavailable": return NerVyx.sell
        default:        return NerVyx.textMuted
        }
    }

    private func lagText(_ lagMs: Double?) -> String {
        guard let lagMs, lagMs.isFinite, lagMs >= 0 else { return "—" }
        if lagMs < 1000 { return "\(Int(lagMs.rounded()))ms" }
        return String(format: "%.1fs", lagMs / 1000)
    }

    private func lagColor(_ lagMs: Double?) -> Color {
        guard let lagMs, lagMs.isFinite else { return NerVyx.textMuted }
        if lagMs > 5000 { return NerVyx.warning }
        if lagMs > 15000 { return NerVyx.sell }
        return NerVyx.textSecondary
    }

    // MARK: - Trainer / GPU compact (links to Trainer Telemetry)

    private func runtimeCompute(_ h: MonitorHealth) -> some View {
        VStack(spacing: 8) {
            SectionHeader(title: "Compute health", accent: NerVyx.primary, trailing: "trainer + GPU")
            if let t = h.trainer {
                HStack(spacing: 10) {
                    Circle()
                        .fill(t.cuda_active ? NerVyx.validation : NerVyx.warning)
                        .frame(width: 7, height: 7)
                    Text("Trainer")
                        .font(.system(size: 13))
                        .foregroundStyle(NerVyx.textSecondary)
                    Spacer(minLength: 8)
                    Text(t.shortState.uppercased())
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(NerVyx.statusColor(t.state))
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                    Text(t.training_active ? "TRAINING" : "INFERENCE")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(t.training_active ? NerVyx.buy : NerVyx.paper)
                }
                .padding(.vertical, 2)
            }
            if let g = h.gpu {
                HStack(spacing: 10) {
                    Circle()
                        .fill(g.utilization_pct > 85 ? NerVyx.warning : NerVyx.validation)
                        .frame(width: 7, height: 7)
                    Text(g.displayName)
                        .font(.system(size: 13, design: .monospaced))
                        .foregroundStyle(NerVyx.textSecondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                    Spacer(minLength: 8)
                    Text("\(Int(g.utilization_pct))% util")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(g.utilization_pct > 85 ? NerVyx.warning : NerVyx.inference)
                    Text(String(format: "%.1f/%.0fGB", Double(g.vram_used_mb) / 1024, Double(g.vram_total_mb) / 1024))
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundStyle(NerVyx.signal)
                    if g.temperature_c > 0 {
                        Text("\(Int(g.temperature_c))°C")
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(g.temperature_c > 80 ? NerVyx.sell : g.temperature_c > 70 ? NerVyx.warning : NerVyx.textMuted)
                    }
                }
                .padding(.vertical, 2)
            }
            NavigationLink {
                TrainerTelemetryView()
            } label: {
                HStack {
                    Text("Open trainer telemetry")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(NerVyx.primary)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(NerVyx.primary)
                }
                .padding(.top, 2)
            }
            .buttonStyle(.plain)
        }
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: - Footer

    private var streamFooter: some View {
        HStack(spacing: 8) {
            LivePulse(color: vm.health != nil ? NerVyx.validation : NerVyx.textMuted)
            Text(vm.streamSummary)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
            Spacer()
        }
        .padding(.horizontal, 4)
    }
}
