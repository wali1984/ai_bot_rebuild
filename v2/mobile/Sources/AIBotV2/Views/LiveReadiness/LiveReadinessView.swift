import SwiftUI

// MARK: - Formatting helpers (nil-honest: absent runtime data renders as em-dash)

private func readinessText(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "—" }
    return nervyxPublicRuntimeText(value)
}

private func readinessIntText(_ value: Int?) -> String {
    guard let value else { return "—" }
    return "\(value)"
}

private func readinessBoolText(_ value: Bool?) -> String {
    guard let value else { return "—" }
    return value ? "true" : "false"
}

// MARK: - Live Readiness screen
//
// Streams `/api/v2/live-readiness/gates` over the shared resource WebSocket
// (poll fallback), surfacing envelope staleness. The gate matrix is grouped
// into collapsible glass sections (blocked / locked / pending / passed) with a
// pass/block progress visualization and per-gate blocker chains. Live trading
// stays OPERATOR-GATED; nothing on this screen can flip a gate.

struct LiveReadinessView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = LiveReadinessViewModel()
    @State private var expandedSections: Set<String> = ["blocked", "locked", "pending"]
    @State private var expandedGates: Set<String> = []

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.gates.isEmpty {
                    loadingReplica
                } else if let err = vm.error, vm.gates.isEmpty {
                    ErrorStateView(message: err) {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    }
                } else {
                    gatesContent
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .nerVyxScreen()
            .navigationTitle("Live Readiness")
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
                VStack(spacing: 12) {
                    RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 60)
                    RoundedRectangle(cornerRadius: 8).fill(NerVyx.panel).frame(height: 10)
                    RoundedRectangle(cornerRadius: 8).fill(NerVyx.panel).frame(height: 18)
                }
                .nerVyxGlassCard(accent: NerVyx.sell)
                ForEach(0..<3, id: \.self) { _ in
                    VStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 34)
                        RoundedRectangle(cornerRadius: 10).fill(NerVyx.panel).frame(height: 84)
                    }
                    .nerVyxGlassCard()
                }
            }
            .padding(16)
        }
        .redacted(reason: .placeholder)
    }

    // MARK: - Content

    private var gatesContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                statusCard
                blockerSummaryCard
                gateGroupSection(
                    key: "blocked",
                    title: "Blocked gates",
                    icon: "xmark.shield.fill",
                    color: NerVyx.sell,
                    gates: vm.blockedGates
                )
                gateGroupSection(
                    key: "locked",
                    title: "Locked gates",
                    icon: "lock.fill",
                    color: NerVyx.warning,
                    gates: vm.lockedGates
                )
                gateGroupSection(
                    key: "pending",
                    title: "Pending gates",
                    icon: "clock.badge.exclamationmark.fill",
                    color: NerVyx.inference,
                    gates: vm.pendingGates
                )
                gateGroupSection(
                    key: "passed",
                    title: "Passed gates",
                    icon: "checkmark.shield.fill",
                    color: NerVyx.validation,
                    gates: vm.passedGates
                )
                RuntimeTruthLiveCard(title: "Runtime Truth")
                liveCanaryRuntimeCard
                liveBlockedNote
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Status + progress card (pass/block visualization)

    private var statusCard: some View {
        VStack(spacing: 14) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(overallColor.opacity(0.15))
                        .frame(width: 52, height: 52)
                    Image(systemName: overallIcon)
                        .font(.system(size: 22))
                        .foregroundStyle(overallColor)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(vm.overallStatus)
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(overallColor)
                    Text("\(vm.passedCount) of \(vm.totalCount) gates passed")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted)
                }
                Spacer(minLength: 6)
                VStack(alignment: .trailing, spacing: 6) {
                    freshnessChip
                    HeroMetricText(
                        text: "\(Int((vm.progressFraction * 100).rounded()))%",
                        size: 32,
                        color: overallColor
                    )
                }
            }

            GeometryReader { geo in
                progressSegments(width: geo.size.width)
            }
            .frame(height: 10)
            .background(NerVyx.borderSubtle.opacity(0.4))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(NerVyx.borderSubtle, lineWidth: 1))
            .animation(SwiftUI.Animation.default, value: vm.passedCount)
            .animation(SwiftUI.Animation.default, value: vm.blockedCount)

            HStack(spacing: 12) {
                legendDot(label: "Passed", count: vm.passedCount, color: NerVyx.validation)
                legendDot(label: "Blocked", count: vm.blockedCount, color: NerVyx.sell)
                legendDot(label: "Pending", count: vm.pendingCount, color: NerVyx.inference)
                if vm.lockedCount > 0 {
                    legendDot(label: "Locked", count: vm.lockedCount, color: NerVyx.warning)
                }
                Spacer(minLength: 0)
            }
        }
        .nerVyxGlassCard(accent: overallColor)
    }

    private func progressSegments(width: CGFloat) -> some View {
        let total = CGFloat(max(vm.totalCount, 1))
        func seg(_ count: Int) -> CGFloat { width * CGFloat(count) / total }
        return HStack(spacing: 0) {
            Rectangle().fill(NerVyx.validation).frame(width: seg(vm.passedCount))
            Rectangle().fill(NerVyx.sell).frame(width: seg(vm.blockedCount))
            Rectangle().fill(NerVyx.warning).frame(width: seg(vm.lockedCount))
            Rectangle().fill(NerVyx.inference.opacity(0.75)).frame(width: seg(vm.pendingCount))
            Spacer(minLength: 0)
        }
    }

    private func legendDot(label: String, count: Int, color: Color) -> some View {
        HStack(spacing: 5) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text("\(count)")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
                .contentTransition(.numericText())
            Text(label)
                .font(.system(size: 10))
                .foregroundStyle(NerVyx.textMuted)
        }
    }

    private var freshnessChip: StalenessChip {
        guard !vm.gates.isEmpty else { return .offline() }
        return .from(
            stale: vm.isEffectivelyStale,
            lagMs: vm.lagMs,
            transport: vm.transport,
            ageSeconds: vm.ageSeconds
        )
    }

    // MARK: - Readiness blocker summary (blocked reasons as severity-colored chips)

    @ViewBuilder
    private var blockerSummaryCard: some View {
        if !vm.readinessBlockers.isEmpty || (vm.exactNoLiveReason?.isEmpty == false) {
            VStack(alignment: .leading, spacing: 12) {
                SectionHeader(
                    title: "Readiness Blockers",
                    accent: NerVyx.sell,
                    trailing: readinessText(vm.blockerTruth?.status)
                )
                if let reason = vm.exactNoLiveReason, !reason.isEmpty {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "exclamationmark.octagon.fill")
                            .foregroundStyle(NerVyx.sell)
                        VStack(alignment: .leading, spacing: 2) {
                            MicroLabel(text: "Exact no-live reason")
                            Text(reason)
                                .font(.system(size: 13, weight: .bold, design: .monospaced))
                                .foregroundStyle(NerVyx.sell)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                    }
                }
                BlockerChipFlow(blockers: vm.readinessBlockers, colorFor: summaryBlockerColor)
                if let truth = vm.blockerTruth, truth.available == true {
                    NerVyxDivider()
                    DataRow(label: "A-grade truth", value: readinessText(truth.status), valueColor: NerVyx.warning, mono: true)
                    if let primary = truth.primary_blocker {
                        DataRow(label: "Primary blocker", value: primary, valueColor: NerVyx.sell, mono: true)
                    }
                    if let generated = truth.generated_utc {
                        DataRow(label: "Generated", value: generated, mono: true)
                    }
                }
            }
            .nerVyxGlassCard(accent: NerVyx.sell)
        }
    }

    private func summaryBlockerColor(_ id: String) -> Color {
        blockerColor(id: id, severity: vm.severity(forBlocker: id))
    }

    // MARK: - Grouped gate sections (collapsible glass cards)

    @ViewBuilder
    private func gateGroupSection(
        key: String,
        title: String,
        icon: String,
        color: Color,
        gates: [LiveReadinessGateRow]
    ) -> some View {
        if !gates.isEmpty {
            VStack(spacing: 8) {
                Button {
                    SwiftUI.withAnimation(.default) { toggleSection(key) }
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: icon)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(color)
                            .frame(width: 28, height: 28)
                            .background(color.opacity(0.14))
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        Text(title)
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(NerVyx.textPrimary)
                        NerVyxBadge(text: "\(gates.count)", color: color, small: true)
                        Spacer()
                        Image(systemName: "chevron.down")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(NerVyx.textMuted)
                            .rotationEffect(.degrees(expandedSections.contains(key) ? 180 : 0))
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                if expandedSections.contains(key) {
                    VStack(spacing: 0) {
                        ForEach(gates) { gate in
                            GateRowView(
                                gate: gate,
                                isExpanded: expandedGates.contains(gate.id)
                            ) {
                                SwiftUI.withAnimation(.default) { toggleGate(gate.id) }
                            }
                            if gate.id != gates.last?.id {
                                NerVyxDivider().padding(.leading, 46)
                            }
                        }
                    }
                    .transition(.opacity)
                }
            }
            .nerVyxGlassCard(accent: color)
        }
    }

    // MARK: - Live Canary (wording kept verbatim — safety copy)

    private var liveCanaryRuntimeCard: some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Live Canary", accent: NerVyx.signal)

            if let canary = vm.liveCanaryStatus {
                let noMutation = canary.data.no_mutation_flags?.hasNoExchangeMutation
                DataRow(
                    label: "Selected A+ candidate",
                    value: readinessText(canary.data.selected_a_plus_candidate ?? "none"),
                    valueColor: canary.data.selected_a_plus_candidate == nil ? NerVyx.warning : NerVyx.validation,
                    mono: true
                )
                DataRow(label: "Why none", value: readinessText(canary.data.why_none), mono: true)
                DataRow(label: "Dry run", value: readinessBoolText(canary.data.dry_run), valueColor: canary.data.dry_run == true ? NerVyx.validation : NerVyx.warning, mono: true)
                DataRow(label: "Operator approval", value: readinessBoolText(canary.data.operator_approval_required), valueColor: canary.data.operator_approval_required == true ? NerVyx.warning : NerVyx.textSecondary, mono: true)
                DataRow(label: "No mutation flags", value: readinessBoolText(noMutation), valueColor: noMutation == true ? NerVyx.validation : NerVyx.sell, mono: true)
                DataRow(label: "Live gate", value: readinessText(canary.live_gate), valueColor: NerVyx.sell, mono: true)
                DataRow(label: "Source", value: readinessText(canary.canonical_owner), mono: true)
            } else {
                DataRow(label: "Live canary", value: "not loaded", valueColor: NerVyx.warning)
            }

            NerVyxDivider()

            if let inventory = vm.aPlusInventoryStatus {
                DataRow(label: "A+ candidates", value: readinessIntText(inventory.data.verifiedAPlusCount), valueColor: inventory.data.verifiedAPlusCount > 0 ? NerVyx.validation : NerVyx.warning, mono: true)
                DataRow(label: "Live-ready rows", value: readinessIntText(inventory.data.live_ready_rows), valueColor: (inventory.data.live_ready_rows ?? 0) > 0 ? NerVyx.validation : NerVyx.warning, mono: true)
                DataRow(label: "Evaluated candidates", value: readinessIntText(inventory.data.evaluated_candidates), mono: true)
                DataRow(label: "Final A+ counted", value: readinessBoolText(inventory.data.counts_as_final_a_plus), valueColor: inventory.data.counts_as_final_a_plus == true ? NerVyx.validation : NerVyx.warning, mono: true)
                DataRow(label: "Inventory source", value: readinessText(inventory.canonical_owner), mono: true)
            } else {
                DataRow(label: "A+ inventory", value: "not loaded", valueColor: NerVyx.warning)
            }
        }
        .nerVyxGlassCard(accent: NerVyx.signal)
    }

    // MARK: - LIVE BLOCKED note (safety copy kept verbatim — never migrate to glass)

    private var liveBlockedNote: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "lock.shield.fill").foregroundStyle(NerVyx.sell)
                Text("LIVE TRADING: OPERATOR GATED")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(NerVyx.sell)
            }
            Text("All gates must pass AND operator approval recorded before live trading can be enabled. Dangerous controls require web admin authorization.")
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(NerVyx.sell.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.sell.opacity(0.2), lineWidth: 1))
    }

    // MARK: - Toggle helpers

    private func toggleSection(_ key: String) {
        if expandedSections.contains(key) {
            expandedSections.remove(key)
        } else {
            expandedSections.insert(key)
        }
    }

    private func toggleGate(_ id: String) {
        if expandedGates.contains(id) {
            expandedGates.remove(id)
        } else {
            expandedGates.insert(id)
        }
    }

    // MARK: - Overall status helpers

    private var overallColor: Color {
        if vm.blockedCount > 0 || vm.lockedCount > 0 { return NerVyx.sell }
        if vm.allPassed { return NerVyx.validation }
        return NerVyx.warning
    }

    private var overallIcon: String {
        if vm.blockedCount > 0 || vm.lockedCount > 0 { return "xmark.shield.fill" }
        if vm.allPassed { return "checkmark.shield.fill" }
        return "clock.badge.exclamationmark.fill"
    }
}

// MARK: - Blocker severity color (shared)

private func blockerColor(id: String, severity: String?) -> Color {
    switch severity ?? "" {
    case "a_grade_blocker": return NerVyx.sell
    case "learning_data_blocker": return NerVyx.warning
    default:
        if id.contains("LIVE") || id.contains("GUARDIAN") { return NerVyx.sell }
        if id.contains("STARVED") || id.contains("BLOCKED") { return NerVyx.warning }
        return NerVyx.textSecondary
    }
}

// MARK: - Blocker chip flow (adaptive severity-colored chips)

struct BlockerChipFlow: View {
    let blockers: [String]
    var colorFor: (String) -> Color = { _ in NerVyx.textSecondary }
    var limit: Int = 8

    private var visible: [String] { Array(blockers.prefix(limit)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            MicroLabel(text: "Blocker chain")
            if visible.isEmpty {
                Text("no blocker reported")
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 140), spacing: 6)], alignment: .leading, spacing: 6) {
                    ForEach(visible, id: \.self) { blocker in
                        Text(blocker)
                            .font(.system(size: 10, weight: .semibold, design: .monospaced))
                            .foregroundStyle(colorFor(blocker))
                            .lineLimit(3)
                            .minimumScaleFactor(0.8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 6)
                            .background(colorFor(blocker).opacity(0.10))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            .overlay(RoundedRectangle(cornerRadius: 8).stroke(colorFor(blocker).opacity(0.30), lineWidth: 1))
                    }
                }
                if blockers.count > visible.count {
                    Text("+\(blockers.count - visible.count) more")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(NerVyx.textMuted)
                }
            }
        }
    }
}

// MARK: - Gate row (per-gate blocker chain on tap)

struct GateRowView: View {
    let gate: LiveReadinessGateRow
    var isExpanded: Bool = false
    var onTap: () -> Void = {}

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button(action: onTap) {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(stateColor.opacity(0.15))
                            .frame(width: 34, height: 34)
                        Text(gate.stateEmoji)
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(stateColor)
                    }
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(gate.id.uppercased())
                                .font(.system(size: 10, weight: .bold, design: .monospaced))
                                .foregroundStyle(NerVyx.textMuted)
                            Text(gate.name)
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(NerVyx.textPrimary)
                                .lineLimit(1)
                        }
                        Text(gate.sub)
                            .font(.system(size: 11))
                            .foregroundStyle(NerVyx.textMuted)
                            .lineLimit(2)
                    }
                    Spacer(minLength: 6)
                    NerVyxBadge(text: gate.displayState, color: stateColor, small: true)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(NerVyx.textMuted)
                        .rotationEffect(.degrees(isExpanded ? 180 : 0))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                gateDetail.transition(.opacity)
            }
        }
        .padding(.vertical, 10)
    }

    private var gateDetail: some View {
        VStack(alignment: .leading, spacing: 8) {
            DataRow(label: "Evidence", value: gate.source_route_or_key, mono: true)
            if gate.isPassed {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.seal.fill").foregroundStyle(NerVyx.validation)
                    Text("Gate condition satisfied — no blocker on this gate.")
                        .font(.system(size: 11))
                        .foregroundStyle(NerVyx.textSecondary)
                    Spacer(minLength: 0)
                }
            } else {
                BlockerChipFlow(blockers: gateBlockers, colorFor: chainColor)
            }
        }
        .padding(.leading, 46)
    }

    private var gateBlockers: [String] {
        gate.readiness_blockers ?? gate.top_blockers ?? []
    }

    private func chainColor(_ id: String) -> Color {
        let severity = gate.a_grade_blocker_truth?.findings?.first { $0.id == id }?.severity
        return blockerColor(id: id, severity: severity)
    }

    private var stateColor: Color {
        switch gate.state {
        case "passed": return NerVyx.validation
        case "blocked": return NerVyx.sell
        case "locked": return NerVyx.warning
        default: return NerVyx.inference
        }
    }
}
