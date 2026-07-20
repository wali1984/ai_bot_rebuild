import SwiftUI

private func readinessText(_ value: String?) -> String {
    guard let value, !value.isEmpty else { return "-" }
    return nervyxPublicRuntimeText(value)
}

private func readinessIntText(_ value: Int?) -> String {
    guard let value else { return "-" }
    return "\(value)"
}

private func readinessBoolText(_ value: Bool?) -> String {
    guard let value else { return "-" }
    return value ? "true" : "false"
}

struct LiveReadinessView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = LiveReadinessViewModel()

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.gates.isEmpty {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Loading readiness gates…")
                                .font(.system(size: 14))
                                .foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error, vm.gates.isEmpty {
                        VStack(spacing: 16) {
                            Image(systemName: "exclamationmark.triangle")
                                .font(.system(size: 32))
                                .foregroundStyle(NerVyx.warning)
                            Text(err)
                                .foregroundStyle(NerVyx.textSecondary)
                                .multilineTextAlignment(.center)
                            Button("Retry") {
                                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                            }
                            .foregroundStyle(NerVyx.signal)
                        }.padding(32)
                    } else {
                        gatesContent
                    }
                }
            }
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

    // MARK: - Main content

    private var gatesContent: some View {
        ScrollView {
            VStack(spacing: 14) {
                overallStatusCard
                RuntimeTruthLiveCard(title: "Runtime Truth")
                liveCanaryRuntimeCard
                blockedNote
                gatesList
                liveBlockedNote
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private var overallStatusCard: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(overallColor.opacity(0.15))
                    .frame(width: 52, height: 52)
                Image(systemName: overallIcon)
                    .font(.system(size: 22))
                    .foregroundStyle(overallColor)
            }
            VStack(alignment: .leading, spacing: 5) {
                Text(vm.overallStatus)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(overallColor)
                HStack(spacing: 12) {
                    readinessChip(count: vm.passedCount, label: "passed", color: NerVyx.validation)
                    readinessChip(count: vm.blockedCount, label: "blocked", color: NerVyx.sell)
                    readinessChip(count: vm.pendingCount, label: "pending", color: NerVyx.warning)
                }
            }
            Spacer()
        }
        .padding(14)
        .background(overallColor.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(overallColor.opacity(0.3), lineWidth: 1))
    }

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
        .nerVyxElevatedCard(accent: NerVyx.signal)
    }

    private func readinessChip(count: Int, label: String, color: Color) -> some View {
        HStack(spacing: 4) {
            Text("\(count)")
                .font(.system(size: 12, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(NerVyx.textMuted)
        }
    }

    @ViewBuilder
    private var blockedNote: some View {
        if vm.blockedCount > 0 {
            HStack(spacing: 8) {
                Image(systemName: "xmark.shield.fill")
                    .foregroundStyle(NerVyx.sell)
                Text("\(vm.blockedCount) gate\(vm.blockedCount > 1 ? "s" : "") blocked — live trading is not permitted.")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textSecondary)
            }
            .padding(12)
            .background(NerVyx.sell.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.sell.opacity(0.25), lineWidth: 1))
        }
    }

    private var gatesList: some View {
        VStack(spacing: 0) {
            SectionHeader(title: "Gate Matrix (\(vm.gates.count) gates)", accent: NerVyx.primary)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            ForEach(vm.gates) { gate in
                GateRowView(gate: gate)
                if gate.id != vm.gates.last?.id {
                    NerVyxDivider().padding(.horizontal, 16)
                }
            }
        }
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }

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
        .background(NerVyx.sell.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.sell.opacity(0.2), lineWidth: 1))
    }

    // MARK: - Helpers

    private var overallColor: Color {
        if vm.blockedCount > 0 { return NerVyx.sell }
        if vm.allPassed { return NerVyx.validation }
        return NerVyx.warning
    }

    private var overallIcon: String {
        if vm.blockedCount > 0 { return "xmark.shield.fill" }
        if vm.allPassed { return "checkmark.shield.fill" }
        return "clock.badge.exclamationmark.fill"
    }
}

// MARK: - Gate Row

struct GateRowView: View {
    let gate: LiveReadinessGateRow

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(stateColor.opacity(0.15))
                    .frame(width: 36, height: 36)
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
            Spacer()
            NerVyxBadge(
                text: gate.displayState,
                color: stateColor,
                small: true
            )
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(gate.isBlocked ? NerVyx.sell.opacity(0.04) : Color.clear)
        .contentShape(Rectangle())
    }

    private var stateColor: Color {
        switch gate.state {
        case "passed": return NerVyx.validation
        case "blocked": return NerVyx.sell
        case "locked": return NerVyx.warning
        default: return NerVyx.textMuted
        }
    }
}
