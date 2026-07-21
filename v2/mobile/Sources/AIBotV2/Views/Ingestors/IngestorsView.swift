import SwiftUI

// MARK: - Status color + freshness helpers (nil-honest, real fields only)

/// One color per delivery-status class, shared by the donut, the count chips
/// and the per-row badge so a status always reads the same across the screen.
/// Distinct categorical hues: mint = live, amber = stale (degraded),
/// red = upstream_error (active failure), slate = offline (silent),
/// blue = not_started (never initialized).
private func ingestorStatusColor(_ status: String) -> Color {
    switch status.lowercased() {
    case "live": return NerVyx.validation
    case "stale", "unknown_freshness": return NerVyx.warning
    case "upstream_error": return NerVyx.sell
    case "offline": return NerVyx.neutral
    case "not_started": return NerVyx.inference
    default: return NerVyx.textMuted
    }
}

/// Short uppercase label for a status class (chips / badges).
private func ingestorStatusLabel(_ status: String) -> String {
    status.replacingOccurrences(of: "_", with: " ").uppercased()
}

/// Freshness color graded against the feed's own liveness threshold (backend
/// live_within_seconds; moralis polls every 300s so 660s is still live). Falls
/// back to the streaming-feed defaults of 60s/300s when no threshold is given.
private func ingestorFreshnessColor(_ seconds: Double?, liveWithin: Double? = nil) -> Color {
    guard let seconds else { return NerVyx.textMuted }
    let fresh = liveWithin ?? 60
    let warming = max(300, fresh * 2)
    if seconds <= fresh { return NerVyx.validation }
    if seconds <= warming { return NerVyx.warning }
    return NerVyx.sell
}

/// Compact price text: fewer decimals for large prices, more for sub-dollar.
private func ingestorPriceText(_ price: Double) -> String {
    if abs(price) >= 1_000 { return String(format: "%.2f", price) }
    if abs(price) >= 1 { return String(format: "%.4f", price) }
    return String(format: "%.6f", price)
}

// MARK: - List

struct IngestorsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = IngestorsViewModel()

    var body: some View {
        Group {
            if vm.isLoading && vm.statusResponse == nil {
                loadingReplica
            } else if let err = vm.error, vm.statusResponse == nil {
                ErrorStateView(message: err) {
                    Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                }
            } else {
                content
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .nerVyxScreen()
        .navigationTitle("Ingestors")
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
        .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    // MARK: Content

    private var content: some View {
        ScrollView {
            VStack(spacing: 14) {
                statusStrip
                summaryCard
                ForEach(vm.ingestors) { ingestor in
                    NavigationLink {
                        IngestorDetailView(row: ingestor)
                    } label: {
                        ingestorRow(ingestor)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    // MARK: Status strip (freshness truth + per-class counts + live gate)

    private var statusStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                freshnessChip
                ForEach(vm.orderedStatusBreakdown, id: \.status) { item in
                    StatChip(
                        label: ingestorStatusLabel(item.status),
                        value: "\(item.count)",
                        color: item.count > 0 ? ingestorStatusColor(item.status) : NerVyx.textMuted,
                        accent: ingestorStatusColor(item.status)
                    )
                }
                NerVyxBadge(
                    text: liveGateLabel,
                    color: NerVyx.sell,
                    small: true
                )
            }
            .padding(.horizontal, 2)
        }
    }

    private var freshnessChip: StalenessChip {
        guard vm.statusResponse != nil else { return .offline() }
        return .from(stale: vm.isStale, transport: vm.transport)
    }

    private var liveGateLabel: String {
        let gate = vm.statusResponse?.live_gate ?? "blocked_human_only"
        return gate.replacingOccurrences(of: "_", with: " ").uppercased()
    }

    // MARK: Summary card (5-class donut + truth rows)

    private var summaryCard: some View {
        VStack(spacing: 12) {
            SectionHeader(
                title: "Ingestor Delivery Status",
                accent: NerVyx.signal,
                trailing: vm.statusResponse?.freshness_status ?? "—"
            )
            HStack(alignment: .center, spacing: 16) {
                DonutChart(
                    slices: donutSlices,
                    centerText: "\(vm.liveCount)/\(vm.totalCount)",
                    centerLabel: "LIVE",
                    size: 108,
                    lineWidth: 15
                )
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(vm.orderedStatusBreakdown, id: \.status) { item in
                        breakdownRow(item.status, count: item.count)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            NerVyxDivider()
            DataRow(label: "Source", value: vm.sourceType ?? vm.statusResponse?.source ?? "—", mono: true)
            DataRow(label: "Generated", value: vm.lastUpdatedAt ?? vm.statusResponse?.generated_at_utc ?? "—", mono: true)
            DataRow(
                label: "Live gate",
                value: liveGateLabel,
                valueColor: NerVyx.sell,
                mono: true
            )
        }
        .nerVyxGlassCard(accent: vm.isStale ? NerVyx.warning : NerVyx.signal)
    }

    private var donutSlices: [DonutChart.Slice] {
        vm.orderedStatusBreakdown
            .filter { $0.count > 0 }
            .map { .init(label: ingestorStatusLabel($0.status), value: Double($0.count), color: ingestorStatusColor($0.status)) }
    }

    private func breakdownRow(_ status: String, count: Int) -> some View {
        HStack(spacing: 8) {
            RoundedRectangle(cornerRadius: 2)
                .fill(ingestorStatusColor(status))
                .frame(width: 8, height: 8)
            Text(ingestorStatusLabel(status))
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(NerVyx.textSecondary)
                .lineLimit(1)
            Spacer(minLength: 4)
            Text("\(count)")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(count > 0 ? ingestorStatusColor(status) : NerVyx.textMuted)
        }
    }

    // MARK: Ingestor row (glass, new payload fields)

    private func ingestorRow(_ ingestor: IngestorRowModel) -> some View {
        let color = ingestorStatusColor(ingestor.status)
        let errorPayloads = ingestor.upstream_error_payloads ?? 0
        return VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(ingestor.displayTitle)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: 6)
                StatusBadge(label: ingestorStatusLabel(ingestor.status), color: color)
            }

            providerChips(ingestor)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 8) {
                MetricCard(
                    title: "Freshness",
                    value: NerVyxFormat.age(ingestor.newest_event_age_seconds),
                    valueColor: ingestorFreshnessColor(ingestor.newest_event_age_seconds, liveWithin: ingestor.live_within_seconds),
                    icon: "clock"
                )
                MetricCard(
                    title: "Redis keys",
                    value: NerVyxFormat.count(ingestor.key_count),
                    icon: "key"
                )
                MetricCard(
                    title: "Sampled payloads",
                    value: NerVyxFormat.count(ingestor.sampled_payloads),
                    icon: "tray.full"
                )
                MetricCard(
                    title: "Error payloads",
                    value: NerVyxFormat.count(ingestor.upstream_error_payloads),
                    valueColor: errorPayloads > 0 ? NerVyx.sell : NerVyx.validation,
                    icon: errorPayloads > 0 ? "exclamationmark.triangle.fill" : "checkmark.shield"
                )
            }

            if let reason = ingestor.provider_unusable_reason, !reason.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.octagon.fill")
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.sell)
                    Text(reason)
                        .font(.system(size: 10))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(2)
                    Spacer(minLength: 0)
                }
            }

            HStack {
                Text(ingestor.redis_pattern ?? "—")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
                Spacer()
                Text("View stream →")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(NerVyx.signal)
            }
        }
        .nerVyxGlassCard(accent: color)
    }

    @ViewBuilder
    private func providerChips(_ ingestor: IngestorRowModel) -> some View {
        if ingestor.provider_current != nil || ingestor.provider_usable != nil {
            HStack(spacing: 8) {
                if let current = ingestor.provider_current {
                    StatChip(
                        label: "Source",
                        value: current ? "CURRENT" : "STANDBY",
                        color: current ? NerVyx.validation : NerVyx.textMuted,
                        accent: current ? NerVyx.validation : NerVyx.borderStrong
                    )
                }
                if let usable = ingestor.provider_usable {
                    StatChip(
                        label: "Provider",
                        value: usable ? "USABLE" : "UNUSABLE",
                        color: usable ? NerVyx.validation : NerVyx.sell,
                        accent: usable ? NerVyx.validation : NerVyx.sell
                    )
                }
                Spacer(minLength: 0)
            }
        }
    }

    // MARK: Loading replica (redacted skeleton of the real layout)

    private var loadingReplica: some View {
        ScrollView {
            VStack(spacing: 14) {
                HStack(spacing: 8) {
                    ForEach(0..<4, id: \.self) { _ in
                        Capsule().fill(NerVyx.panel).frame(width: 74, height: 24)
                    }
                    Spacer()
                }
                VStack(spacing: 12) {
                    RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 120)
                    RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 60)
                }
                .nerVyxGlassCard(accent: NerVyx.signal)
                ForEach(0..<4, id: \.self) { _ in
                    VStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 30)
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 96)
                    }
                    .nerVyxGlassCard()
                }
            }
            .padding(16)
        }
        .redacted(reason: .placeholder)
    }
}

// MARK: - Detail

struct IngestorDetailView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    let row: IngestorRowModel
    @State private var vm: IngestorDetailViewModel

    init(row: IngestorRowModel) {
        self.row = row
        _vm = State(initialValue: IngestorDetailViewModel(name: row.name))
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                header
                if vm.rows.isEmpty {
                    emptyState
                } else {
                    ForEach(vm.rows.prefix(60)) { metricRow in
                        rowCard(metricRow)
                    }
                }
            }
            .padding(16)
            .padding(.bottom, 32)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .nerVyxScreen()
        .navigationTitle(row.displayTitle)
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { vm.start(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stop() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                SectionHeader(title: "Live Stream", accent: NerVyx.signal)
                Spacer()
                detailFreshnessChip
            }
            HStack(spacing: 8) {
                if let current = row.provider_current {
                    StatChip(
                        label: "Source",
                        value: current ? "CURRENT" : "STANDBY",
                        color: current ? NerVyx.validation : NerVyx.textMuted,
                        accent: current ? NerVyx.validation : NerVyx.borderStrong
                    )
                }
                if let usable = row.provider_usable {
                    StatChip(
                        label: "Provider",
                        value: usable ? "USABLE" : "UNUSABLE",
                        color: usable ? NerVyx.validation : NerVyx.sell,
                        accent: usable ? NerVyx.validation : NerVyx.sell
                    )
                }
                StatChip(
                    label: "Status",
                    value: ingestorStatusLabel(row.status),
                    color: ingestorStatusColor(row.status),
                    accent: ingestorStatusColor(row.status)
                )
                Spacer(minLength: 0)
            }
            HStack(spacing: 10) {
                NerVyxStatCard(label: "SYMBOLS", value: "\(vm.rows.count)", accent: NerVyx.signal)
                NerVyxStatCard(
                    label: "PATTERN",
                    value: "redis",
                    sublabel: vm.metrics?.redis_pattern ?? row.redis_pattern ?? "—",
                    accent: NerVyx.inference
                )
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    private var detailFreshnessChip: StalenessChip {
        guard vm.metrics != nil else { return .offline() }
        return .from(stale: vm.isStale, transport: vm.transport)
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: vm.isLoading ? "dot.radiowaves.left.and.right" : "tray")
                .font(.system(size: 26))
                .foregroundStyle(NerVyx.textMuted)
            Text(vm.isLoading ? "Connecting live data stream…" : "No live rows for this ingestor yet.")
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(28)
        .nerVyxGlassCard()
    }

    private func rowCard(_ metricRow: IngestorMetricRow) -> some View {
        let trend = vm.trendValues(for: metricRow.id)
        let trendColor: Color = {
            guard let first = trend.first, let last = trend.last, trend.count > 1 else { return NerVyx.signal }
            return last >= first ? NerVyx.validation : NerVyx.sell
        }()
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(metricRow.symbol)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: 6)
                Text(NerVyxFormat.age(metricRow.age_seconds))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(ingestorFreshnessColor(metricRow.age_seconds))
            }

            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    if let price = metricRow.last_price {
                        DataRow(label: "Price", value: ingestorPriceText(price), mono: true)
                    }
                    if let change = metricRow.price_change_pct {
                        DataRow(
                            label: "24h change",
                            value: String(format: "%+.2f%%", change),
                            valueColor: change >= 0 ? NerVyx.validation : NerVyx.sell,
                            mono: true
                        )
                    }
                    if let vol = metricRow.volume_24h_quote {
                        DataRow(label: "24h volume", value: NerVyxFormat.compactUSD(vol), mono: true)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)

                if trend.count > 1 {
                    VStack(alignment: .trailing, spacing: 3) {
                        Sparkline(values: trend, color: trendColor)
                            .frame(width: 92, height: 34)
                        if let label = metricRow.primaryTrendLabel {
                            Text(label)
                                .font(.system(size: 9, weight: .semibold))
                                .foregroundStyle(NerVyx.textMuted)
                                .tracking(0.4)
                                .lineLimit(1)
                        }
                    }
                }
            }

            ForEach((metricRow.numeric_fields ?? [:]).sorted(by: { $0.key < $1.key }).prefix(6), id: \.key) { key, value in
                DataRow(label: key, value: String(format: "%.4g", value), mono: true)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.borderSubtle)
    }
}
