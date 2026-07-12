import SwiftUI

private func ingestorStatusColor(_ status: String) -> Color {
    switch status.lowercased() {
    case "live": return NerVyx.validation
    case "stale", "unknown_freshness": return NerVyx.warning
    case "offline", "upstream_error": return NerVyx.sell
    case "not_started": return NerVyx.textMuted
    default: return NerVyx.textMuted
    }
}

private func ingestorAgeText(_ seconds: Double?) -> String {
    guard let seconds else { return "—" }
    if seconds < 90 { return "\(Int(seconds.rounded()))s" }
    if seconds < 5_400 { return "\(Int((seconds / 60).rounded()))m" }
    return String(format: "%.1fh", seconds / 3_600)
}

// MARK: - List

struct IngestorsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = IngestorsViewModel()

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            Group {
                if vm.isLoading && vm.statusResponse == nil {
                    ProgressView().tint(NerVyx.primary)
                } else if let err = vm.error, vm.statusResponse == nil {
                    errorView(err)
                } else {
                    content
                }
            }
        }
        .navigationTitle("Ingestors")
        .navigationBarTitleDisplayMode(.large)
        .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var content: some View {
        ScrollView {
            VStack(spacing: 14) {
                summaryCard
                ForEach(vm.ingestors) { ingestor in
                    NavigationLink {
                        IngestorDetailView(name: ingestor.name, title: ingestor.displayTitle)
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

    private var summaryCard: some View {
        VStack(spacing: 12) {
            SectionHeader(title: "Live Ingestor Truth", accent: NerVyx.signal)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                NerVyxStatCard(label: "LIVE", value: "\(vm.liveCount)/\(vm.totalCount)",
                               valueColor: vm.liveCount > 0 ? NerVyx.validation : NerVyx.warning, accent: NerVyx.signal)
                NerVyxStatCard(label: "STREAM", value: vm.streamLabel,
                               valueColor: vm.isStale ? NerVyx.warning : NerVyx.validation,
                               sublabel: vm.sourceType ?? "—", accent: vm.isStale ? NerVyx.warning : NerVyx.validation)
            }
        }
        .nerVyxCard(accent: NerVyx.signal.opacity(0.3))
    }

    private func ingestorRow(_ ingestor: IngestorRowModel) -> some View {
        let color = ingestorStatusColor(ingestor.status)
        return VStack(spacing: 8) {
            HStack {
                Text(ingestor.displayTitle)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                Spacer()
                StatusBadge(label: ingestor.status.replacingOccurrences(of: "_", with: " ").uppercased(), color: color)
            }
            DataRow(label: "Freshness", value: ingestorAgeText(ingestor.newest_event_age_seconds), valueColor: color, mono: true)
            DataRow(label: "Redis keys", value: "\(ingestor.key_count ?? 0)", mono: true)
            HStack {
                Text(ingestor.redis_pattern ?? "")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(1)
                Spacer()
                Text("View stream →").font(.system(size: 11, weight: .semibold)).foregroundStyle(NerVyx.signal)
            }
        }
        .nerVyxCard(accent: color.opacity(0.3))
    }

    private func errorView(_ msg: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle").font(.system(size: 32)).foregroundStyle(NerVyx.warning)
            Text(msg).font(.system(size: 14)).foregroundStyle(NerVyx.textSecondary).multilineTextAlignment(.center)
            Button("Retry") { Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) } }
                .foregroundStyle(NerVyx.signal)
        }
        .padding(32)
    }
}

// MARK: - Detail

struct IngestorDetailView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    let name: String
    let title: String
    @State private var vm: IngestorDetailViewModel

    init(name: String, title: String) {
        self.name = name
        self.title = title
        _vm = State(initialValue: IngestorDetailViewModel(name: name))
    }

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 14) {
                    header
                    if vm.rows.isEmpty {
                        Text(vm.isLoading ? "Connecting live data stream…" : "No live rows for this ingestor yet.")
                            .font(.system(size: 13)).foregroundStyle(NerVyx.textMuted).padding(24)
                    } else {
                        ForEach(vm.rows.prefix(60)) { row in
                            rowCard(row)
                        }
                    }
                }
                .padding(16)
                .padding(.bottom, 32)
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { vm.start(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stop() }
    }

    private var header: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Live Stream", accent: NerVyx.signal, trailing: vm.streamLabel)
            HStack(spacing: 10) {
                NerVyxStatCard(label: "SYMBOLS", value: "\(vm.rows.count)", accent: NerVyx.signal)
                NerVyxStatCard(label: "SOURCE", value: "redis", sublabel: vm.metrics?.redis_pattern ?? "—", accent: NerVyx.inference)
            }
        }
        .nerVyxCard(accent: NerVyx.signal.opacity(0.3))
    }

    private func rowCard(_ row: IngestorMetricRow) -> some View {
        VStack(spacing: 6) {
            HStack {
                Text(row.symbol).font(.system(size: 13, weight: .semibold)).foregroundStyle(NerVyx.textPrimary)
                Spacer()
                Text(ingestorAgeText(row.age_seconds))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle((row.age_seconds ?? 999) <= 60 ? NerVyx.validation : NerVyx.warning)
            }
            if let price = row.last_price {
                DataRow(label: "Price", value: String(format: "%.4f", price), mono: true)
            }
            if let change = row.price_change_pct {
                DataRow(label: "24h change", value: String(format: "%+.2f%%", change),
                        valueColor: change >= 0 ? NerVyx.validation : NerVyx.sell, mono: true)
            }
            if let vol = row.volume_24h_quote {
                DataRow(label: "24h volume", value: String(format: "$%.1fM", vol / 1_000_000), mono: true)
            }
            ForEach((row.numeric_fields ?? [:]).sorted(by: { $0.key < $1.key }).prefix(6), id: \.key) { key, value in
                DataRow(label: key, value: String(format: "%.4g", value), mono: true)
            }
        }
        .nerVyxCard(accent: NerVyx.borderSubtle)
    }
}
