import SwiftUI

/// Adaptive System — read-only view of the paper/shadow adaptive runtime exposed
/// by GET /api/v2/adaptive/status. Each section reports honest availability and
/// freshness (fresh / stale / idle producer); nothing is fabricated. Live gate
/// stays blocked (paper-only, no trade actions from this surface).
struct AdaptiveStatusView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AdaptiveStatusViewModel()

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            Group {
                if vm.isLoading && vm.status == nil {
                    VStack(spacing: 12) {
                        ProgressView().tint(NerVyx.signal)
                        Text("Loading adaptive status…")
                            .font(.system(size: 14))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                } else if let err = vm.error, vm.status == nil {
                    VStack(spacing: 14) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 30))
                            .foregroundStyle(NerVyx.warning)
                        Text(err)
                            .foregroundStyle(NerVyx.textMuted)
                            .multilineTextAlignment(.center)
                        Button("Retry") {
                            Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                        }
                        .foregroundStyle(NerVyx.signal)
                    }
                    .padding(28)
                } else {
                    content
                }
            }
        }
        .navigationTitle("Adaptive System")
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                summaryCard
                ForEach(vm.orderedSections, id: \.key) { entry in
                    sectionCard(key: entry.key, section: entry.section)
                }
                footer
            }
            .padding(16)
        }
    }

    private var summaryCard: some View {
        let s = vm.status?.summary
        return VStack(alignment: .leading, spacing: 10) {
            Text("Adaptive Subsystem")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(NerVyx.textPrimary)
            HStack(spacing: 18) {
                summaryStat("Fresh", s?.fresh_count, NerVyx.signal)
                summaryStat("Stale", s?.stale_count, NerVyx.warning)
                summaryStat("Idle", s?.absent_count, NerVyx.textMuted)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    private func summaryStat(_ label: String, _ value: Int?, _ color: Color) -> some View {
        VStack(spacing: 2) {
            Text(value.map { "\($0)" } ?? "—")
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(color)
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
        }
    }

    private func sectionCard(key: String, section: AdaptiveStatusSection) -> some View {
        let available = section.available ?? false
        let stale = section.stale ?? false
        let tone: Color = !available ? NerVyx.textMuted : (stale ? NerVyx.warning : NerVyx.signal)
        let statusText: String = !available ? (section.reason ?? "unavailable") : (stale ? "stale" : "fresh")
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(humanize(key))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                    .lineLimit(1)
                Spacer(minLength: 8)
                NerVyxBadge(text: statusText, color: tone, small: true)
            }
            HStack(spacing: 10) {
                if let age = section.age_seconds {
                    Text("age \(formatAge(age))")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                }
                if let src = section.source_key {
                    Text(src)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }

    private var footer: some View {
        HStack(spacing: 6) {
            Image(systemName: "lock.shield")
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
            Text("Live gate: \(vm.status?.live_gate ?? "blocked_human_only") · read-only · no trade actions")
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
        }
        .padding(.top, 4)
    }

    private func humanize(_ key: String) -> String {
        key.split(separator: "_")
            .map { $0.prefix(1).uppercased() + String($0.dropFirst()) }
            .joined(separator: " ")
    }

    private func formatAge(_ seconds: Double) -> String {
        if seconds < 90 { return "\(Int(seconds))s" }
        if seconds < 5400 { return "\(Int(seconds / 60))m" }
        return "\(Int(seconds / 3600))h"
    }
}
