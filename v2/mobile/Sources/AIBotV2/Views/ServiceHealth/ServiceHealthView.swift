import SwiftUI

// SelfHealingBannerView lives in Views/Components/SelfHealingBanner.swift (shared, Infra-owned).

/// Full-screen self-healing monitor for every non-ingestor component the
/// supervisor watches (`/api/v2/self-healing/status`, 20s poll via
/// `SelfHealingViewModel`). Summary tone stat cards + composition donut,
/// restarted-this-cycle evidence, and per-service glass rows with heartbeat
/// freshness bars. Supervisor freshness is surfaced honestly through
/// `StalenessChip` — never a hardcoded LIVE label.
struct ServiceHealthView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = SelfHealingViewModel()

    // MARK: - Derived groups
    //
    // Tone comes from `SelfHealingService.tone` (the supervisor's current
    // action), but the banner's `services` list is the authoritative
    // "still down after auto-heal" truth — a service being RESTART_DEAD-ed
    // every cycle without recovering must count as DOWN, not HEALING,
    // so the header never contradicts the red banner above it.

    /// Services the backend banner reports as still down after auto-heal.
    private var downSet: Set<String> {
        Set((vm.status?.banner.services ?? []).map(\.id))
    }

    private func effectiveTone(_ svc: SelfHealingService) -> String {
        if downSet.contains(svc.id) { return "error" }
        return svc.tone
    }

    private var okServices: [SelfHealingService] { vm.services.filter { effectiveTone($0) == "ok" } }
    private var healingServices: [SelfHealingService] { vm.services.filter { effectiveTone($0) == "warn" } }
    private var downServices: [SelfHealingService] { vm.services.filter { effectiveTone($0) == "error" } }

    /// Components flagged critical by the supervisor, and the subset still down
    /// after auto-heal. "Any critical still down" is the single most important
    /// operator fact on this screen, so it is elevated to the summary — not
    /// buried in the per-row list.
    private var criticalServices: [SelfHealingService] { vm.services.filter { $0.criticality == "critical" } }
    private var criticalDownCount: Int { criticalServices.filter { effectiveTone($0) == "error" }.count }

    /// Units the supervisor restarted in its latest cycle (auto-heal evidence).
    private var restartedSet: Set<String> { Set(vm.status?.restarted_units ?? []) }

    private func tone(_ t: String) -> Color {
        switch t {
        case "ok": return NerVyx.validation
        case "warn": return NerVyx.warning
        default: return NerVyx.sell
        }
    }

    private func toneLabel(_ t: String) -> String {
        switch t {
        case "ok": return "OK"
        case "warn": return "HEALING"
        default: return "DOWN"
        }
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
                    supervisorBar
                    if let banner = vm.banner {
                        SelfHealingBannerView(banner: banner)
                    }
                    if vm.isLoading && vm.status == nil {
                        loadingReplica
                    } else if let err = vm.error, vm.status == nil {
                        ErrorStateView(message: err) {
                            Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                        }
                        .nerVyxGlassCard(accent: NerVyx.warning)
                    } else if vm.status?.available == false {
                        unavailableCard
                    } else {
                        if !vm.services.isEmpty {
                            summarySection
                        }
                        restartedSection
                        servicesSection
                    }
                }
                .padding(16)
                .padding(.bottom, 24)
            }
            .nerVyxScreen()
            .navigationTitle("SERVICE HEALTH")
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
        }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stop() }
    }

    // MARK: - Supervisor freshness bar

    private var supervisorBar: some View {
        HStack(spacing: 8) {
            supervisorChip
            MicroLabel(text: "SELF-HEALING SUPERVISOR", size: 9)
            Spacer()
            NerVyxBadge(text: NervyxBrand.liveBlockedLabel.uppercased(), color: NerVyx.signal, small: true)
        }
        .padding(.horizontal, 2)
    }

    /// Honest freshness: derived from the supervisor payload's own age —
    /// POLL when fresh (20s HTTP poll), STALE + age when the supervisor's
    /// status is old, OFFLINE when the payload/backend is unavailable.
    @ViewBuilder
    private var supervisorChip: some View {
        if let s = vm.status {
            if s.available {
                StalenessChip.from(
                    stale: s.supervisor_stale ?? true,
                    ageSeconds: s.supervisor_age_seconds
                )
            } else {
                StalenessChip.offline()
            }
        } else if vm.error != nil {
            StalenessChip.offline()
        } else {
            ProgressView()
                .tint(NerVyx.textMuted)
                .scaleEffect(0.7)
        }
    }

    // MARK: - Loading replica (redacted)

    private var loadingReplica: some View {
        VStack(spacing: 14) {
            HStack(spacing: 10) {
                ForEach(0..<3, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(NerVyx.panel)
                        .frame(height: 84)
                }
            }
            ForEach(0..<6, id: \.self) { _ in
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(NerVyx.panel)
                    .frame(height: 68)
            }
        }
        .redacted(reason: .placeholder)
    }

    // MARK: - Unavailable / empty (honest states)

    private var unavailableCard: some View {
        VStack(spacing: 10) {
            Image(systemName: "bolt.heart")
                .font(.system(size: 28))
                .foregroundStyle(NerVyx.warning)
            Text("Supervisor status unavailable")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(NerVyx.textPrimary)
            Text("The self-healing supervisor has not published a status payload. The banner above carries the reason reported by the backend.")
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .nerVyxGlassCard(accent: NerVyx.warning)
    }

    private var emptyCard: some View {
        VStack(spacing: 8) {
            Image(systemName: "tray")
                .font(.system(size: 24))
                .foregroundStyle(NerVyx.textMuted)
            Text("No component decisions in the latest supervisor cycle.")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .nerVyxGlassCard()
    }

    // MARK: - Summary (stat cards + donut)

    private var summarySection: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                toneStatCard(count: okServices.count, label: "OK", color: NerVyx.validation)
                toneStatCard(count: healingServices.count, label: "HEALING", color: NerVyx.warning)
                toneStatCard(count: downServices.count, label: "DOWN", color: NerVyx.sell)
            }
            donutCard
        }
    }

    private func toneStatCard(count: Int, label: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            MicroLabel(text: label, color: color)
            HeroMetricText(text: String(count), size: 32, color: count > 0 ? color : NerVyx.textMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: color)
        .accessibilityIdentifier("service-health-stat-\(label.lowercased())")
    }

    private var donutSlices: [DonutChart.Slice] {
        [
            DonutChart.Slice(label: "OK", value: Double(okServices.count), color: NerVyx.validation),
            DonutChart.Slice(label: "HEALING", value: Double(healingServices.count), color: NerVyx.warning),
            DonutChart.Slice(label: "DOWN", value: Double(downServices.count), color: NerVyx.sell),
        ].filter { $0.value > 0 }
    }

    private var donutCard: some View {
        HStack(spacing: 18) {
            DonutChart(
                slices: donutSlices,
                centerText: "\(okServices.count)/\(vm.services.count)",
                centerLabel: "OK",
                size: 104
            )
            VStack(alignment: .leading, spacing: 8) {
                StatChip(
                    label: "COMPONENTS",
                    value: NerVyxFormat.count(vm.status?.component_count ?? vm.services.count),
                    accent: NerVyx.primary
                )
                StatChip(
                    label: "CRITICAL",
                    value: criticalDownCount > 0
                        ? "\(criticalDownCount)/\(criticalServices.count) DOWN"
                        : "\(criticalServices.count) OK",
                    color: criticalDownCount > 0 ? NerVyx.sell : NerVyx.textSecondary,
                    accent: criticalDownCount > 0 ? NerVyx.sell : NerVyx.borderSubtle
                )
                StatChip(
                    label: "RESTARTED",
                    value: "\(restartedSet.count)",
                    color: restartedSet.isEmpty ? NerVyx.textSecondary : NerVyx.signal,
                    accent: restartedSet.isEmpty ? NerVyx.borderSubtle : NerVyx.signal
                )
                StatChip(
                    label: "SUP AGE",
                    value: NerVyxFormat.age(vm.status?.supervisor_age_seconds),
                    color: vm.status?.supervisor_stale == true ? NerVyx.warning : NerVyx.textSecondary,
                    accent: vm.status?.supervisor_stale == true ? NerVyx.warning : NerVyx.borderSubtle
                )
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: NerVyx.primary)
    }

    // MARK: - Restarted this cycle

    @ViewBuilder
    private var restartedSection: some View {
        if let units = vm.status?.restarted_units, !units.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(title: "Restarted This Cycle", accent: NerVyx.signal, trailing: "\(units.count)")
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 6)], alignment: .leading, spacing: 6) {
                    ForEach(units, id: \.self) { unit in
                        Text(unit)
                            .font(.system(size: 10, weight: .medium, design: .monospaced))
                            .foregroundStyle(NerVyx.signal)
                            .lineLimit(1)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(NerVyx.signal.opacity(0.1))
                            .clipShape(Capsule())
                            .overlay(Capsule().stroke(NerVyx.signal.opacity(0.4), lineWidth: 1))
                    }
                }
                Text("Units the supervisor restarted in its latest cycle (auto-heal evidence).")
                    .font(.system(size: 10))
                    .foregroundStyle(NerVyx.textMuted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .nerVyxGlassCard(accent: NerVyx.signal)
        }
    }

    // MARK: - Component rows

    private var servicesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Components", accent: NerVyx.primary, trailing: "\(vm.services.count)")
            if vm.services.isEmpty {
                emptyCard
            } else {
                ForEach(vm.services) { svc in
                    serviceRow(svc)
                }
            }
        }
    }

    private func serviceRow(_ svc: SelfHealingService) -> some View {
        let effective = effectiveTone(svc)
        let c = tone(effective)
        let wasRestarted = restartedSet.contains(svc.unit ?? "")
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Circle()
                    .fill(c)
                    .frame(width: 9, height: 9)
                    .shadow(color: c.opacity(0.6), radius: 4)
                VStack(alignment: .leading, spacing: 3) {
                    Text(svc.name ?? svc.unit ?? "unknown")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(NerVyx.textPrimary)
                        .lineLimit(1)
                    HStack(spacing: 6) {
                        if let cat = svc.category, !cat.isEmpty {
                            MicroLabel(text: cat, size: 9)
                        }
                        if svc.criticality == "critical" {
                            MicroLabel(text: "CRITICAL", color: NerVyx.sell, size: 9)
                        }
                    }
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 4) {
                    Text(toneLabel(effective))
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(c)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(c.opacity(0.12))
                        .clipShape(Capsule())
                        .overlay(Capsule().stroke(c.opacity(0.5), lineWidth: 1))
                    if wasRestarted {
                        MicroLabel(text: "RESTARTED", color: NerVyx.signal, size: 9)
                    }
                }
            }
            if let age = svc.heartbeat_age_seconds, let maxAge = svc.max_staleness_seconds, maxAge > 0 {
                heartbeatBar(age: age, maxAge: maxAge)
            }
            if effective != "ok", let action = svc.action, !action.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    Text(action)
                        .font(.system(size: 9, weight: .bold, design: .monospaced))
                        .foregroundStyle(c)
                    if let reason = svc.reason, !reason.isEmpty {
                        Text(reason)
                            .font(.system(size: 10))
                            .foregroundStyle(NerVyx.textMuted)
                            .fixedSize(horizontal: false, vertical: true)
                            .lineLimit(3)
                    }
                }
            }
            if let unit = svc.unit, !unit.isEmpty {
                Text(unit)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted.opacity(0.8))
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .nerVyxGlassCard(accent: c, cornerRadius: 14)
        .accessibilityIdentifier("service-health-row-\(svc.name ?? "unknown")")
    }

    /// Heartbeat freshness bar: age vs the component's max allowed staleness.
    private func heartbeatBar(age: Double, maxAge: Double) -> some View {
        let ratio = age / max(maxAge, 1)
        let frac = min(max(ratio, 0), 1)
        let barColor: Color = ratio >= 1 ? NerVyx.sell : (ratio >= 0.7 ? NerVyx.warning : NerVyx.validation)
        return VStack(alignment: .leading, spacing: 3) {
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(NerVyx.borderSubtle.opacity(0.6))
                    Capsule()
                        .fill(barColor.opacity(0.85))
                        .frame(width: max(CGFloat(frac) * geo.size.width, 2))
                }
            }
            .frame(height: 4)
            Text("heartbeat \(NerVyxFormat.age(age)) · max \(NerVyxFormat.age(maxAge))")
                .font(.system(size: 9, weight: .medium, design: .monospaced))
                .foregroundStyle(NerVyx.textMuted)
        }
    }
}
