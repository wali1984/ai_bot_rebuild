import SwiftUI

// MARK: - Alerts screen
//
// Market alerts from `v2:market:alerts` (backend `/api/v2/mobile/alerts`,
// streamed over the shared resource WebSocket, HTTP fallback). Every visual is
// derived from the real payload — severity counts, symbol grouping, and the
// freshness chip all come from `AlertsViewModel`, never hardcoded.

struct AlertsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AlertsViewModel()
    @State private var filter: AlertSeverityBucket? = nil

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && !hasData {
                    loadingSkeleton
                } else if let err = vm.error, !hasData {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    alertContent
                }
            }
            .nerVyxScreen()
            .navigationTitle("Alerts")
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

    // MARK: Derived state

    private var hasData: Bool { vm.response != nil }
    private var total: Int { vm.alerts.count }

    private func count(for bucket: AlertSeverityBucket) -> Int {
        vm.severityCounts[bucket] ?? 0
    }

    /// Most severe bucket that actually has alerts (drives header/accent color).
    private var worstPresent: AlertSeverityBucket? {
        AlertSeverityBucket.allCases.first { count(for: $0) > 0 }
    }

    private var headerAccent: Color {
        worstPresent.map(AlertSeverityStyle.color) ?? NerVyx.validation
    }

    private var presentBuckets: [AlertSeverityBucket] {
        AlertSeverityBucket.allCases.filter { count(for: $0) > 0 }
    }

    private var donutSlices: [DonutChart.Slice] {
        presentBuckets.map { bucket in
            DonutChart.Slice(
                label: AlertSeverityStyle.shortLabel(bucket),
                value: Double(count(for: bucket)),
                color: AlertSeverityStyle.color(bucket)
            )
        }
    }

    private var filteredGroups: [AlertsViewModel.SymbolGroup] {
        vm.groups(filter: filter)
    }

    // MARK: Content

    private var alertContent: some View {
        ScrollView {
            VStack(spacing: 12) {
                summaryHeader
                filterBar
                if filteredGroups.isEmpty {
                    emptyState
                } else {
                    ForEach(filteredGroups) { group in
                        SymbolAlertSection(group: group)
                    }
                }
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: Summary header (severity donut + counts + freshness truth)

    private var summaryHeader: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                MicroLabel(text: "MARKET ALERTS")
                Spacer()
                StalenessChip(mode: vm.freshnessMode, ageText: vm.freshnessAgeText)
            }

            if total > 0 {
                HStack(alignment: .center, spacing: 18) {
                    DonutChart(
                        slices: donutSlices,
                        centerText: "\(total)",
                        centerLabel: "ALERTS",
                        size: 96,
                        lineWidth: 13
                    )
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(AlertSeverityBucket.allCases) { bucket in
                            severityLegendRow(bucket)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            } else {
                HStack(spacing: 12) {
                    Image(systemName: "checkmark.shield.fill")
                        .font(.system(size: 30))
                        .foregroundStyle(NerVyx.validation)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("All clear")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(NerVyx.textPrimary)
                        Text("No active market alerts in the runtime stream.")
                            .font(.system(size: 12))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                    Spacer()
                }
            }

            streamTruthLine
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: headerAccent)
    }

    private func severityLegendRow(_ bucket: AlertSeverityBucket) -> some View {
        let value = count(for: bucket)
        return HStack(spacing: 8) {
            Circle()
                .fill(AlertSeverityStyle.color(bucket))
                .frame(width: 8, height: 8)
                .opacity(value > 0 ? 1 : 0.35)
            Text(bucket.label)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(value > 0 ? NerVyx.textSecondary : NerVyx.textMuted)
                .tracking(0.4)
            Spacer()
            Text("\(value)")
                .font(.system(size: 14, weight: .bold, design: .monospaced))
                .foregroundStyle(value > 0 ? AlertSeverityStyle.color(bucket) : NerVyx.textMuted)
                .contentTransition(.numericText())
        }
    }

    private var streamTruthLine: some View {
        HStack(spacing: 6) {
            Text(streamStatusText)
                .font(.system(size: 10, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Spacer()
        }
    }

    private var streamStatusText: String {
        var parts: [String] = [vm.streamLabel.uppercased()]
        if let age = vm.freshnessAgeText { parts.append("age \(age)") }
        parts.append("\(total) active")
        return parts.joined(separator: " · ")
    }

    // MARK: Severity filter chips

    private var filterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                filterChip(title: "ALL", count: total, bucket: nil)
                ForEach(AlertSeverityBucket.allCases) { bucket in
                    filterChip(title: bucket.label, count: count(for: bucket), bucket: bucket)
                }
            }
            .padding(.horizontal, 2)
            .padding(.vertical, 1)
        }
    }

    private func filterChip(title: String, count: Int, bucket: AlertSeverityBucket?) -> some View {
        let isSelected = filter == bucket
        let accent = bucket.map(AlertSeverityStyle.color) ?? NerVyx.primary
        let dim = count == 0 && bucket != nil
        return Button {
            withAnimation(.easeInOut(duration: 0.15)) { filter = bucket }
        } label: {
            HStack(spacing: 6) {
                if let bucket {
                    Circle()
                        .fill(AlertSeverityStyle.color(bucket))
                        .frame(width: 6, height: 6)
                }
                Text(title)
                    .font(.system(size: 11, weight: .bold))
                    .tracking(0.4)
                    .foregroundStyle(isSelected ? NerVyx.textPrimary : NerVyx.textSecondary)
                Text("\(count)")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(accent)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(isSelected ? accent.opacity(0.20) : NerVyx.panel.opacity(0.55))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(accent.opacity(isSelected ? 0.8 : 0.3), lineWidth: 1))
            .opacity(dim ? 0.55 : 1)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("alert-filter-\(bucket?.rawValue ?? "all")")
    }

    // MARK: Honest empty state

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: total == 0 ? "bell.slash.fill" : "line.3.horizontal.decrease.circle")
                .font(.system(size: 34))
                .foregroundStyle(NerVyx.textMuted)
            Text(emptyTitle)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(NerVyx.textSecondary)
            Text(emptySubtitle)
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
            if filter != nil {
                Button("Show all alerts") {
                    withAnimation(.easeInOut(duration: 0.15)) { filter = nil }
                }
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(NerVyx.signal)
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity)
        .nerVyxGlassCard()
    }

    private var emptyTitle: String {
        if total == 0 { return "No active alerts" }
        if let f = filter { return "No \(f.label) alerts" }
        return "No alerts match this filter"
    }

    private var emptySubtitle: String {
        if total == 0 {
            return "Market alerts from v2:market:alerts appear here as the runtime publishes them."
        }
        return "\(total) active alert\(total == 1 ? "" : "s") across other severities."
    }

    // MARK: Redacted-replica loading skeleton

    private var loadingSkeleton: some View {
        ScrollView {
            VStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        MicroLabel(text: "MARKET ALERTS")
                        Spacer()
                        StalenessChip(mode: .poll)
                    }
                    HStack(alignment: .center, spacing: 18) {
                        Circle()
                            .stroke(NerVyx.borderSubtle, lineWidth: 13)
                            .frame(width: 96, height: 96)
                            .padding(6)
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(0..<4, id: \.self) { _ in
                                HStack(spacing: 8) {
                                    Circle().fill(NerVyx.borderSubtle).frame(width: 8, height: 8)
                                    Text("SEVERITY")
                                        .font(.system(size: 11, weight: .semibold))
                                        .foregroundStyle(NerVyx.textMuted)
                                    Spacer()
                                    Text("0")
                                        .font(.system(size: 14, weight: .bold, design: .monospaced))
                                        .foregroundStyle(NerVyx.textMuted)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .nerVyxGlassCard()

                HStack(spacing: 8) {
                    ForEach(0..<4, id: \.self) { _ in
                        Text("FILTER 0")
                            .font(.system(size: 11, weight: .bold))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .background(NerVyx.panel.opacity(0.55))
                            .clipShape(Capsule())
                    }
                    Spacer()
                }

                ForEach(0..<2, id: \.self) { _ in
                    VStack(alignment: .leading, spacing: 10) {
                        SectionHeader(title: "SYMBOL (0)", accent: NerVyx.primary)
                        ForEach(0..<2, id: \.self) { _ in
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Alert type placeholder")
                                    .font(.system(size: 13, weight: .semibold))
                                    .foregroundStyle(NerVyx.textPrimary)
                                Text("Alert message placeholder spanning a line or two of runtime text.")
                                    .font(.system(size: 12))
                                    .foregroundStyle(NerVyx.textSecondary)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .nerVyxGlassCard()
                }
            }
            .padding(16)
            .redacted(reason: .placeholder)
        }
        .scrollDisabled(true)
    }
}

// MARK: - Symbol-grouped alert section (glass container, edge-to-edge rows)

struct SymbolAlertSection: View {
    let group: AlertsViewModel.SymbolGroup

    private var accent: Color { AlertSeverityStyle.color(group.worst) }

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: 16, style: .continuous)
        VStack(spacing: 0) {
            HStack {
                SectionHeader(title: "\(group.symbol) (\(group.alerts.count))", accent: accent)
                Spacer()
                NerVyxBadge(text: group.worst.label, color: accent, small: true)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 8)

            ForEach(Array(group.alerts.enumerated()), id: \.offset) { index, alert in
                AlertRowView(alert: alert, bucket: AlertSeverityBucket(raw: alert.severity))
                if index < group.alerts.count - 1 {
                    NerVyxDivider().padding(.horizontal, 16)
                }
            }
        }
        .padding(.bottom, 4)
        .background(.ultraThinMaterial, in: shape)
        .clipShape(shape)
        .overlay(
            shape.stroke(
                LinearGradient(
                    colors: [Color.white.opacity(0.14), Color.white.opacity(0.03)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ),
                lineWidth: 1
            )
        )
        .overlay(shape.stroke(accent.opacity(0.3), lineWidth: 1))
        .shadow(color: .black.opacity(0.3), radius: 18, y: 8)
    }
}

// MARK: - Alert row (severity-tinted glass row with a left accent strip)

struct AlertRowView: View {
    let alert: MobileAlert
    let bucket: AlertSeverityBucket

    private var accent: Color { AlertSeverityStyle.color(bucket) }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: AlertSeverityStyle.icon(bucket))
                .font(.system(size: 13))
                .foregroundStyle(accent)
                .padding(.top, 1)

            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 8) {
                    Text(alert.type.isEmpty ? "ALERT" : alert.type)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(NerVyx.textPrimary)
                        .lineLimit(1)
                    Spacer()
                    Text(AlertsFormat.time(alert.triggered_at))
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(1)
                }
                if !alert.message.isEmpty {
                    Text(nervyxPublicRuntimeText(alert.message))
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textSecondary)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                HStack(spacing: 8) {
                    NerVyxBadge(text: bucket.label, color: accent, small: true)
                    Spacer()
                }
            }
        }
        .padding(.vertical, 12)
        .padding(.horizontal, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent.opacity(0.05))
        .overlay(alignment: .leading) {
            Rectangle().fill(accent).frame(width: 3)
        }
        .contentShape(Rectangle())
    }
}

// MARK: - Severity styling + formatting helpers

enum AlertSeverityStyle {
    static func color(_ bucket: AlertSeverityBucket) -> Color {
        switch bucket {
        case .critical: return Color(hex: "FF2E55")
        case .error:    return NerVyx.sell
        case .warning:  return NerVyx.warning
        case .info:     return NerVyx.inference
        }
    }

    static func icon(_ bucket: AlertSeverityBucket) -> String {
        switch bucket {
        case .critical: return "exclamationmark.octagon.fill"
        case .error:    return "xmark.octagon.fill"
        case .warning:  return "exclamationmark.triangle.fill"
        case .info:     return "info.circle.fill"
        }
    }

    static func shortLabel(_ bucket: AlertSeverityBucket) -> String {
        switch bucket {
        case .critical: return "Crit"
        case .error:    return "Err"
        case .warning:  return "Warn"
        case .info:     return "Info"
        }
    }
}

enum AlertsFormat {
    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    private static let isoPlain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    static func date(_ iso: String) -> Date? {
        guard !iso.isEmpty else { return nil }
        if let d = isoFractional.date(from: iso) { return d }
        if let d = isoPlain.date(from: iso) { return d }
        // Backend timestamps carry up to 6 fractional digits which some
        // ISO8601 parsers reject — strip the fraction and retry.
        if let dot = iso.firstIndex(of: ".") {
            let suffix = iso.hasSuffix("Z") ? "Z" : ""
            let trimmed = String(iso[iso.startIndex..<dot]) + suffix
            if let d = isoPlain.date(from: trimmed) { return d }
        }
        return nil
    }

    static func time(_ iso: String) -> String {
        guard !iso.isEmpty else { return "—" }
        if let d = date(iso) {
            let age = Date().timeIntervalSince(d)
            if age >= 0 { return "\(NerVyxFormat.age(age)) ago" }
            return NerVyxFormat.age(-age)
        }
        return String(iso.prefix(19)).replacingOccurrences(of: "T", with: " ")
    }
}
