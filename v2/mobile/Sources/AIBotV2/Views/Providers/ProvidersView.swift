import SwiftUI

// MARK: - Formatting helpers (nil-honest: absent data renders as em-dash)

private func providerRuntimeText(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "—" }
    return nervyxPublicRuntimeText(value)
}

private func providerIntText(_ value: Int?) -> String {
    NerVyxFormat.count(value)
}

private func providerDoubleText(_ value: Double?) -> String {
    NerVyxFormat.number(value, decimals: 1)
}

private func providerListText(_ values: [String]?, limit: Int = 4) -> String {
    guard let values, !values.isEmpty else { return "—" }
    let prefix = values.prefix(limit).map(providerRuntimeText).joined(separator: ", ")
    let remainder = values.count - min(values.count, limit)
    return remainder > 0 ? "\(prefix) +\(remainder)" : prefix
}

private func providerBoolText(_ value: Bool?) -> String {
    guard let value else { return "—" }
    return value ? "true" : "false"
}

// MARK: - Providers screen

struct ProvidersView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = ProviderStatusViewModel()
    @State private var expandedProviders: Set<String> = []

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.providerStatus == nil {
                    loadingReplica
                } else if let err = vm.error, vm.providerStatus == nil {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    providersContent
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .nerVyxScreen()
            .navigationTitle("Providers")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                    }
                    .disabled(vm.isLoading)
                }
            }
            .refreshable {
                await vm.load(token: auth.currentToken(), baseURL: appState.baseURL)
            }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: - Loading (redacted replica of the real layout)

    private var loadingReplica: some View {
        ScrollView {
            VStack(spacing: 14) {
                HStack(spacing: 8) {
                    ForEach(0..<3, id: \.self) { _ in
                        Capsule().fill(NerVyx.panel).frame(width: 84, height: 24)
                    }
                    Spacer()
                }
                VStack(spacing: 12) {
                    RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 110)
                    RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 150)
                }
                .nerVyxGlassCard(accent: NerVyx.signal)
                ForEach(0..<3, id: \.self) { _ in
                    VStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 34)
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 120)
                    }
                    .nerVyxGlassCard()
                }
            }
            .padding(16)
        }
        .redacted(reason: .placeholder)
    }

    // MARK: - Content

    private var providersContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                coverageStrip
                ingestorCensusLink
                summaryCard
                if !vm.degradedProviders.isEmpty {
                    degradedAttentionCard
                }
                if !vm.retiredActiveProviders.isEmpty {
                    retiredProviderWarning
                }
                if !vm.requiredAltDataProvidersVisible {
                    missingAltDataWarning
                }
                ForEach(vm.sortedProviders, id: \.provider) { provider in
                    providerCard(provider)
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Coverage strip (GREEN / YELLOW / RED rollup + freshness truth)

    private var coverageStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                freshnessChip
                StatChip(
                    label: "Green",
                    value: "\(vm.greenProviderCount)",
                    color: NerVyx.validation,
                    accent: NerVyx.validation
                )
                StatChip(
                    label: "Yellow",
                    value: "\(vm.yellowProviderCount)",
                    color: NerVyx.warning,
                    accent: NerVyx.warning
                )
                StatChip(
                    label: "Red",
                    value: "\(vm.redProviderCount)",
                    color: NerVyx.sell,
                    accent: NerVyx.sell
                )
                if vm.grayProviderCount > 0 {
                    StatChip(
                        label: "Gray",
                        value: "\(vm.grayProviderCount)",
                        color: NerVyx.textMuted,
                        accent: NerVyx.borderStrong
                    )
                }
                StatChip(
                    label: "Payloads",
                    value: "\(vm.totalPayloadCount)",
                    color: NerVyx.signal,
                    accent: NerVyx.signal
                )
                NerVyxBadge(
                    text: providerRuntimeText(vm.providerStatus?.live_gate).uppercased(),
                    color: NerVyx.sell,
                    small: true
                )
            }
            .padding(.horizontal, 2)
        }
    }

    private var freshnessChip: StalenessChip {
        guard vm.providerStatus != nil else { return .offline() }
        return .from(
            stale: vm.isStale,
            lagMs: vm.lagMs,
            transport: vm.transport,
            ageSeconds: vm.freshnessAgeSeconds
        )
    }

    // MARK: - Ingestor census link (the More-menu row is "Providers & Ingestors" —
    // the per-stream ingestor census must be reachable from here, not only via
    // System Monitor data-feed rows)

    private var ingestorCensusLink: some View {
        NavigationLink {
            IngestorsView()
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "dot.radiowaves.up.forward")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(NerVyx.signal)
                    .frame(width: 30, height: 30)
                    .background(NerVyx.signal.opacity(0.14))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Ingestor census")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Text("Per-stream ingest truth: current provider, usability, unusable reasons")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                }
                Spacer(minLength: 6)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(NerVyx.signal)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .nerVyxGlassCard(accent: NerVyx.signal.opacity(0.5))
    }

    // MARK: - Summary card

    private var summaryCard: some View {
        VStack(spacing: 12) {
            SectionHeader(
                title: "Provider and Ingestor Truth",
                accent: NerVyx.signal,
                trailing: providerRuntimeText(vm.providerStatus?.freshness_status)
            )

            HStack(alignment: .center, spacing: 16) {
                DonutChart(
                    slices: coverageSlices,
                    centerText: "\(vm.activeProviderCount)",
                    centerLabel: "PROVIDERS",
                    size: 104
                )
                VStack(alignment: .leading, spacing: 8) {
                    coverageLegendRow(
                        label: "Heartbeat green",
                        value: "\(vm.heartbeatOnlyGreenCount)",
                        color: vm.heartbeatOnlyGreenCount == 0 ? NerVyx.validation : NerVyx.sell,
                        note: "must stay zero"
                    )
                    coverageLegendRow(
                        label: "Stream",
                        value: vm.streamLabel,
                        color: vm.isStale ? NerVyx.warning : NerVyx.validation,
                        note: providerRuntimeText(vm.sourceType)
                    )
                    coverageLegendRow(
                        label: "Live gate",
                        value: providerRuntimeText(vm.providerStatus?.live_gate),
                        color: NerVyx.sell,
                        note: "operator-gated"
                    )
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            NerVyxDivider()
            DataRow(label: "Canonical owner", value: providerRuntimeText(vm.providerStatus?.canonical_owner), mono: true)
            DataRow(label: "Generated", value: providerRuntimeText(vm.lastUpdatedAt ?? vm.providerStatus?.generated_at_utc), mono: true)
            DataRow(
                label: "Routes to live",
                value: (vm.providerStatus?.routes_to_live ?? false) ? "true" : "false",
                valueColor: (vm.providerStatus?.routes_to_live ?? false) ? NerVyx.sell : NerVyx.validation,
                mono: true
            )
            DataRow(
                label: "Places real order",
                value: (vm.providerStatus?.places_real_order ?? false) ? "true" : "false",
                valueColor: (vm.providerStatus?.places_real_order ?? false) ? NerVyx.sell : NerVyx.validation,
                mono: true
            )
        }
        .nerVyxGlassCard(accent: vm.isStale ? NerVyx.warning : NerVyx.signal)
    }

    private var coverageSlices: [DonutChart.Slice] {
        var slices: [DonutChart.Slice] = []
        if vm.greenProviderCount > 0 {
            slices.append(.init(label: "GREEN", value: Double(vm.greenProviderCount), color: NerVyx.validation))
        }
        if vm.yellowProviderCount > 0 {
            slices.append(.init(label: "YELLOW", value: Double(vm.yellowProviderCount), color: NerVyx.warning))
        }
        if vm.redProviderCount > 0 {
            slices.append(.init(label: "RED", value: Double(vm.redProviderCount), color: NerVyx.sell))
        }
        if vm.grayProviderCount > 0 {
            slices.append(.init(label: "GRAY", value: Double(vm.grayProviderCount), color: NerVyx.textMuted))
        }
        return slices
    }

    private func coverageLegendRow(label: String, value: String, color: Color, note: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            MicroLabel(text: label, size: 9)
            HStack(spacing: 6) {
                Text(value)
                    .font(.system(size: 13, weight: .bold, design: .monospaced))
                    .foregroundStyle(color)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                Text(note)
                    .font(.system(size: 9))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
            }
        }
    }

    // MARK: - Attention callout (degraded providers surfaced at a glance)

    private var degradedAttentionCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(
                title: "Providers needing attention",
                accent: NerVyx.warning,
                trailing: "\(vm.degradedProviders.count) of \(vm.activeProviderCount)"
            )
            ForEach(vm.degradedProviders, id: \.provider) { provider in
                degradedProviderRow(provider)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.warning)
    }

    // Extracted so the row's leading `let color` lives in a function body rather
    // than directly inside the ForEach @ViewBuilder closure. Under the Xcode 16.4
    // SDK a closure that opens with a `let` declaration makes `ForEach.init(_:id:content:)`
    // ambiguous between SwiftUI (ViewBuilder) and SwiftUICore
    // (AccessibilityRotorContentBuilder), which broke the iOS-target compile.
    @ViewBuilder
    private func degradedProviderRow(_ provider: EnterpriseProviderCard) -> some View {
        let color = providerColor(provider.providerDashboardTone)
        Button {
            SwiftUI.withAnimation(.default) {
                _ = expandedProviders.insert(provider.provider)
            }
        } label: {
            HStack(spacing: 10) {
                Circle().fill(color).frame(width: 8, height: 8)
                Text(provider.display_name ?? provider.provider.uppercased())
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: 6)
                Text(providerRuntimeText(provider.status))
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(color)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                NerVyxBadge(text: provider.providerDashboardBadgeText, color: color, small: true)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    // MARK: - Safety warnings (kept verbatim)

    private var retiredProviderWarning: some View {
        HStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(NerVyx.sell)
            Text("Retired providers still active: \(providerListText(vm.retiredActiveProviders))")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textSecondary)
            Spacer()
        }
        .padding(12)
        .background(NerVyx.sell.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.sell.opacity(0.25), lineWidth: 1))
    }

    private var missingAltDataWarning: some View {
        HStack(spacing: 8) {
            Image(systemName: "eye.slash.fill").foregroundStyle(NerVyx.warning)
            Text("CoinGlass and Moralis must both be visible before operator review.")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textSecondary)
            Spacer()
        }
        .padding(12)
        .background(NerVyx.warning.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.warning.opacity(0.25), lineWidth: 1))
    }

    // MARK: - Provider glass card (collapsed by default, details on tap)

    private func providerCard(_ provider: EnterpriseProviderCard) -> some View {
        let color = providerColor(provider.providerDashboardTone)
        let isExpanded = expandedProviders.contains(provider.provider)
        return VStack(alignment: .leading, spacing: 10) {
            Button {
                SwiftUI.withAnimation(.default) {
                    if isExpanded {
                        _ = expandedProviders.remove(provider.provider)
                    } else {
                        _ = expandedProviders.insert(provider.provider)
                    }
                }
            } label: {
                providerHeader(provider, color: color, isExpanded: isExpanded)
            }
            .buttonStyle(.plain)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                MetricCard(
                    title: "Payloads",
                    value: providerIntText(provider.actual_payload_count),
                    valueColor: (provider.actual_payload_count ?? 0) == 0 ? NerVyx.sell : NerVyx.textPrimary,
                    icon: "tray.full"
                )
                MetricCard(title: "Features", value: providerIntText(provider.feature_count), icon: "slider.horizontal.3")
                MetricCard(title: "Consumers", value: providerIntText(provider.consumer_count), icon: "arrow.triangle.branch")
                MetricCard(title: "Symbols", value: providerIntText(provider.symbols_covered?.count), icon: "bitcoinsign.circle")
            }

            providerSafetyRow(provider)

            if isExpanded {
                providerDetails(provider, color: color)
                    .transition(.opacity)
            }
        }
        .nerVyxGlassCard(accent: color)
    }

    private func providerHeader(_ provider: EnterpriseProviderCard, color: Color, isExpanded: Bool) -> some View {
        HStack(spacing: 10) {
            Image(systemName: providerIcon(provider.provider))
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(color)
                .frame(width: 30, height: 30)
                .background(color.opacity(0.14))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(provider.display_name ?? provider.provider.uppercased())
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(NerVyx.textPrimary)
                    .lineLimit(1)
                Text(providerRuntimeText(provider.status))
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            Spacer(minLength: 6)
            NerVyxBadge(text: provider.providerDashboardBadgeText, color: color, small: true)
            Image(systemName: "chevron.down")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(NerVyx.textMuted)
                .rotationEffect(.degrees(isExpanded ? 180 : 0))
        }
        .contentShape(Rectangle())
    }

    private func providerDetails(_ provider: EnterpriseProviderCard, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            NerVyxDivider()
            DataRow(label: "Status", value: providerRuntimeText(provider.status), valueColor: color)
            DataRow(label: "Census source", value: providerRuntimeText(provider.dashboard_color_reason), mono: true)
            DataRow(label: "Tier", value: providerRuntimeText(provider.subscription_tier))
            DataRow(label: "Freshness", value: providerRuntimeText(provider.freshness_status))
            DataRow(label: "Source lag", value: NerVyxFormat.age(provider.source_lag_seconds), mono: true)
            DataRow(label: "Actual payload", value: providerBoolText(provider.actual_payload_present), valueColor: provider.actual_payload_present == true ? NerVyx.validation : NerVyx.warning)
            DataRow(label: "Heartbeat only", value: providerBoolText(provider.heartbeat_only), valueColor: provider.heartbeat_only == true ? NerVyx.warning : NerVyx.validation)
            DataRow(label: "Raw key exposed", value: providerBoolText(provider.raw_key_exposed), valueColor: provider.raw_key_exposed == true ? NerVyx.sell : NerVyx.validation)
            DataRow(label: "Keys published", value: providerIntText(provider.keys_published?.count), mono: true)
            DataRow(label: "Consumer roles", value: providerListText(provider.consumer_roles), mono: true)
            DataRow(label: "Active endpoints", value: providerListText(provider.endpoints_active), mono: true)
            DataRow(label: "Disabled endpoints", value: providerListText(provider.endpoints_disabled), mono: true)
            DataRow(label: "Rate limit", value: "\(providerDoubleText(provider.rate_limit_used)) used / \(providerDoubleText(provider.rate_limit_remaining)) remaining", mono: true)
            DataRow(label: "Quota", value: "daily \(providerDoubleText(provider.daily_quota_used)) / monthly \(providerDoubleText(provider.monthly_quota_used))", mono: true)
            providerFamilyDetails(provider)
        }
    }

    @ViewBuilder
    private func providerFamilyDetails(_ provider: EnterpriseProviderCard) -> some View {
        let id = provider.provider.lowercased()
        if id.contains("coinglass") {
            NerVyxDivider()
            DataRow(label: "Disabled heatmap", value: providerBoolText(provider.disabled_heatmap_endpoint), valueColor: provider.disabled_heatmap_endpoint == true ? NerVyx.warning : NerVyx.textSecondary)
        } else if id.contains("moralis") {
            NerVyxDivider()
            DataRow(label: "Token map", value: providerIntText(provider.token_map_count), mono: true)
            DataRow(label: "Watchlist", value: providerIntText(provider.watchlist_count), mono: true)
            DataRow(label: "Smart wallet candidates", value: providerIntText(provider.smart_wallet_candidate_count), mono: true)
            DataRow(label: "Verified smart wallets", value: providerIntText(provider.verified_smart_wallet_count), mono: true)
        }
    }

    private func providerSafetyRow(_ provider: EnterpriseProviderCard) -> some View {
        let mutationRisk = provider.places_real_order == true || provider.routes_to_live == true
        return HStack(spacing: 8) {
            Image(systemName: mutationRisk ? "xmark.shield.fill" : "lock.shield.fill")
                .foregroundStyle(mutationRisk ? NerVyx.sell : NerVyx.validation)
            Text(mutationRisk ? "Exchange mutation risk" : "Read-only provider path")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(NerVyx.textSecondary)
            Spacer()
            Text(providerRuntimeText(provider.last_success_utc ?? provider.last_error_utc))
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
                .lineLimit(1)
        }
        .padding(.top, 2)
    }

    // MARK: - Tone helpers (providerDashboardTone / providerDashboardBadgeText)

    private func providerColor(_ tone: String) -> Color {
        switch tone.lowercased() {
        case "green": return NerVyx.validation
        case "yellow": return NerVyx.warning
        case "red": return NerVyx.sell
        case "gray", "grey": return NerVyx.textMuted
        default: return NerVyx.statusColor(tone)
        }
    }

    private func providerIcon(_ provider: String) -> String {
        let id = provider.lowercased()
        if id.contains("coinglass") { return "chart.xyaxis.line" }
        if id.contains("moralis") { return "wallet.pass" }
        if id.contains("binance") || id.contains("kucoin") { return "building.columns" }
        return "antenna.radiowaves.left.and.right"
    }
}
