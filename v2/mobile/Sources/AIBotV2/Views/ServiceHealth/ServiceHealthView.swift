import SwiftUI

/// Reusable red/amber banner: renders only when a service is still down after
/// the self-healing supervisor's auto-recovery, or the supervisor is stale.
/// Naming the affected services. Drop into any screen; renders nothing if healthy.
struct SelfHealingBannerView: View {
    let banner: SelfHealingBanner

    private var accent: Color { banner.severity == "critical" ? NerVyx.sell : NerVyx.warning }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "exclamationmark.shield.fill")
                    .font(.system(size: 18))
                    .foregroundStyle(accent)
                Text(banner.severity == "critical" ? "SERVICE DOWN" : "DEGRADED")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(accent)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .overlay(Capsule().stroke(accent.opacity(0.5), lineWidth: 1))
                Spacer()
            }
            Text(banner.message)
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            if !banner.services.isEmpty {
                FlowChips(services: banner.services, accent: accent)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(accent.opacity(0.3), lineWidth: 1))
        .accessibilityIdentifier("self-healing-banner")
    }

    private struct FlowChips: View {
        let services: [SelfHealingService]
        let accent: Color
        var body: some View {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 6)], alignment: .leading, spacing: 6) {
                ForEach(services) { svc in
                    Text("\(svc.name ?? "?") · \(svc.action ?? svc.active_state ?? "")")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(NerVyx.textPrimary)
                        .lineLimit(1)
                        .padding(.horizontal, 8).padding(.vertical, 3)
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(accent.opacity(0.4), lineWidth: 1))
                        .accessibilityIdentifier("self-healing-down-\(svc.name ?? "unknown")")
                }
            }
        }
    }
}

/// Full-screen self-healing monitor: every non-ingestor service with a
/// traffic-light status (green OK / amber HEALING / red DOWN).
struct ServiceHealthView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = SelfHealingViewModel()

    private func tone(_ t: String) -> Color {
        switch t {
        case "ok": return NerVyx.validation
        case "warn": return NerVyx.warning
        default: return NerVyx.sell
        }
    }

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        if let banner = vm.banner {
                            SelfHealingBannerView(banner: banner)
                        }
                        summaryCard
                        ForEach(vm.services) { svc in
                            serviceRow(svc)
                        }
                    }
                    .padding(14)
                }
            }
            .navigationTitle("SERVICE HEALTH")
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
        .onDisappear { vm.stop() }
    }

    private var summaryCard: some View {
        HStack(spacing: 16) {
            stat("\(vm.healthyCount)/\(vm.totalCount)", "HEALTHY", NerVyx.validation)
            if vm.downCount > 0 { stat("\(vm.downCount)", "DOWN", NerVyx.sell) }
            if vm.status?.supervisor_stale == true { stat("STALE", "SUPERVISOR", NerVyx.warning) }
            Spacer()
        }
        .padding(14)
        .nerVyxCard()
    }

    private func stat(_ value: String, _ label: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(.system(size: 17, weight: .bold)).foregroundStyle(color)
            Text(label).font(.system(size: 9, weight: .semibold)).foregroundStyle(NerVyx.textMuted)
        }
    }

    private func serviceRow(_ svc: SelfHealingService) -> some View {
        let c = tone(svc.tone)
        return HStack(spacing: 10) {
            Circle().fill(c).frame(width: 9, height: 9)
            VStack(alignment: .leading, spacing: 1) {
                Text(svc.name ?? svc.unit ?? "?")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                Text("\(svc.category ?? "")\(svc.criticality == "critical" ? " · critical" : "")\(svc.heartbeat_age_seconds != nil ? " · \(Int(svc.heartbeat_age_seconds!))s" : "")")
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.textMuted)
            }
            Spacer()
            Text(svc.tone == "ok" ? "OK" : svc.tone == "warn" ? "HEALING" : "DOWN")
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(c)
                .padding(.horizontal, 8).padding(.vertical, 3)
                .overlay(Capsule().stroke(c.opacity(0.5), lineWidth: 1))
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(c.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .accessibilityIdentifier("service-health-row-\(svc.name ?? "unknown")")
    }
}
