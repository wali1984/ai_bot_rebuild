import SwiftUI

private func providerRuntimeText(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "-" }
    return nervyxPublicRuntimeText(value)
}

private func providerIntText(_ value: Int?) -> String {
    guard let value else { return "-" }
    return "\(value)"
}

private func providerDoubleText(_ value: Double?) -> String {
    guard let value else { return "-" }
    return String(format: "%.1f", value)
}

private func providerListText(_ values: [String]?, limit: Int = 4) -> String {
    guard let values, !values.isEmpty else { return "-" }
    let prefix = values.prefix(limit).map(providerRuntimeText).joined(separator: ", ")
    let remainder = values.count - min(values.count, limit)
    return remainder > 0 ? "\(prefix) +\(remainder)" : prefix
}

struct ProvidersView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = ProviderStatusViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.providerStatus == nil {
                        loadingView
                    } else if let err = vm.error, vm.providerStatus == nil {
                        errorView(err)
                    } else {
                        providersContent
                    }
                }
            }
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

    private var loadingView: some View {
        VStack(spacing: 12) {
            ProgressView().tint(NerVyx.primary)
            Text("Connecting provider truth stream...")
                .font(.system(size: 14))
                .foregroundStyle(NerVyx.textMuted)
        }
    }

    private func errorView(_ msg: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 32))
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
        .padding(32)
    }

    private var providersContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                summaryCard
                if !vm.retiredActiveProviders.isEmpty {
                    retiredProviderWarning
                }
                if !vm.requiredAltDataProvidersVisible {
                    missingAltDataWarning
                }
                ForEach(vm.providers, id: \.provider) { provider in
                    providerCard(provider)
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private var summaryCard: some View {
        VStack(spacing: 12) {
            SectionHeader(title: "Provider and Ingestor Truth", accent: NerVyx.signal)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                NerVyxStatCard(
                    label: "ACTIVE",
                    value: "\(vm.activeProviderCount)",
                    sublabel: providerRuntimeText(vm.providerStatus?.freshness_status),
                    accent: NerVyx.signal
                )
                NerVyxStatCard(
                    label: "LIVE GATE",
                    value: providerRuntimeText(vm.providerStatus?.live_gate),
                    valueColor: NerVyx.sell,
                    sublabel: "read-only controls",
                    accent: NerVyx.sell
                )
                NerVyxStatCard(
                    label: "HEARTBEAT GREEN",
                    value: "\(vm.providerStatus?.data.heartbeat_only_green_count ?? 0)",
                    valueColor: (vm.providerStatus?.data.heartbeat_only_green_count ?? 0) == 0 ? NerVyx.validation : NerVyx.sell,
                    sublabel: "must stay zero",
                    accent: NerVyx.warning
                )
                NerVyxStatCard(
                    label: "STREAM",
                    value: vm.streamLabel,
                    valueColor: vm.isStale ? NerVyx.warning : NerVyx.validation,
                    sublabel: providerRuntimeText(vm.sourceType),
                    accent: vm.isStale ? NerVyx.warning : NerVyx.validation
                )
            }
            DataRow(label: "Canonical owner", value: providerRuntimeText(vm.providerStatus?.canonical_owner), mono: true)
            DataRow(label: "Generated", value: providerRuntimeText(vm.lastUpdatedAt ?? vm.providerStatus?.generated_at_utc), mono: true)
            DataRow(
                label: "Routes to live",
                value: (vm.providerStatus?.routes_to_live ?? false) ? "true" : "false",
                valueColor: (vm.providerStatus?.routes_to_live ?? false) ? NerVyx.sell : NerVyx.validation,
                mono: true
            )
        }
        .nerVyxElevatedCard(accent: vm.isStale ? NerVyx.warning : NerVyx.signal)
    }

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

    private func providerCard(_ provider: EnterpriseProviderCard) -> some View {
        let color = providerColor(provider.providerDashboardTone)
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: providerIcon(provider.provider))
                    .foregroundStyle(color)
                    .frame(width: 18)
                VStack(alignment: .leading, spacing: 2) {
                    Text(provider.display_name ?? provider.provider.uppercased())
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(NerVyx.textPrimary)
                    Text(providerRuntimeText(provider.dashboard_color_reason))
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.textMuted)
                }
                Spacer()
                NerVyxBadge(text: provider.providerDashboardBadgeText, color: color, small: true)
            }

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                MetricCard(title: "Payloads", value: providerIntText(provider.actual_payload_count), icon: "tray.full")
                MetricCard(title: "Features", value: providerIntText(provider.feature_count), icon: "slider.horizontal.3")
                MetricCard(title: "Consumers", value: providerIntText(provider.consumer_count), icon: "arrow.triangle.branch")
                MetricCard(title: "Symbols", value: providerIntText(provider.symbols_covered?.count), icon: "bitcoinsign.circle")
            }

            DataRow(label: "Status", value: providerRuntimeText(provider.status), valueColor: color)
            DataRow(label: "Tier", value: providerRuntimeText(provider.subscription_tier))
            DataRow(label: "Actual payload", value: providerBoolText(provider.actual_payload_present), valueColor: provider.actual_payload_present == true ? NerVyx.validation : NerVyx.warning)
            DataRow(label: "Heartbeat only", value: providerBoolText(provider.heartbeat_only), valueColor: provider.heartbeat_only == true ? NerVyx.warning : NerVyx.validation)
            DataRow(label: "Raw key exposed", value: providerBoolText(provider.raw_key_exposed), valueColor: provider.raw_key_exposed == true ? NerVyx.sell : NerVyx.validation)
            DataRow(label: "Consumer roles", value: providerListText(provider.consumer_roles), mono: true)
            DataRow(label: "Active endpoints", value: providerListText(provider.endpoints_active), mono: true)
            DataRow(label: "Disabled endpoints", value: providerListText(provider.endpoints_disabled), mono: true)
            DataRow(label: "Rate limit", value: "\(providerDoubleText(provider.rate_limit_used)) used / \(providerDoubleText(provider.rate_limit_remaining)) remaining", mono: true)
            DataRow(label: "Quota", value: "daily \(providerDoubleText(provider.daily_quota_used)) / monthly \(providerDoubleText(provider.monthly_quota_used))", mono: true)

            providerFamilyDetails(provider)
            providerSafetyRow(provider)
        }
        .nerVyxCard(accent: color.opacity(0.35))
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
        HStack(spacing: 8) {
            Image(systemName: provider.places_real_order == true || provider.routes_to_live == true ? "xmark.shield.fill" : "lock.shield.fill")
                .foregroundStyle(provider.places_real_order == true || provider.routes_to_live == true ? NerVyx.sell : NerVyx.validation)
            Text(provider.places_real_order == true || provider.routes_to_live == true ? "Exchange mutation risk" : "Read-only provider path")
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

    private func providerBoolText(_ value: Bool?) -> String {
        guard let value else { return "-" }
        return value ? "true" : "false"
    }

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
