import SwiftUI

struct AdminDashboardView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AdminViewModel()
    @State private var showLogoutConfirm = false

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                Group {
                    if vm.isLoading && vm.summary == nil {
                        VStack(spacing: 12) {
                            ProgressView().tint(NerVyx.primary)
                            Text("Connecting ops stream…").font(.system(size: 14)).foregroundStyle(NerVyx.textMuted)
                        }
                    } else if let err = vm.error {
                        if err.contains("admin") {
                            adminAccessRequired
                        } else {
                            ErrorStateView(message: err) {
                                Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                            }
                        }
                    } else if let summary = vm.summary {
                        adminContent(summary)
                    }
                }
            }
            .navigationTitle("Ops Terminal")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button("Refresh", systemImage: "arrow.clockwise") {
                            Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                        }
                        Button("Sign Out", systemImage: "rectangle.portrait.and.arrow.right", role: .destructive) {
                            showLogoutConfirm = true
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle").foregroundStyle(NerVyx.signal)
                    }
                }
            }
            .confirmationDialog("Sign Out?", isPresented: $showLogoutConfirm) {
                Button("Sign Out", role: .destructive) {
                    Task { await auth.logout(baseURL: appState.baseURL) }
                }
                Button("Cancel", role: .cancel) {}
            }
            .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private func adminContent(_ s: MobileAdminSummary) -> some View {
        ScrollView {
            VStack(spacing: 14) {
                actorCard(s.actor)
                liveGateCard(s.live_gate)
                trainerCard(s.trainer)
                gpuCard(s.gpu)
                paperCard(s.paper)
                riskCard(s.risk)
                dangerousControlsNote(s)
                adminNavLinks()
            }
            .padding(16)
            .padding(.bottom, 24)
        }
    }

    // MARK: - Cards

    private func actorCard(_ actor: AdminActor) -> some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(NerVyx.primary.opacity(0.15))
                    .frame(width: 48, height: 48)
                Image(systemName: "person.fill")
                    .font(.system(size: 20))
                    .foregroundStyle(NerVyx.primary)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(actor.email)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(NerVyx.textPrimary)
                NerVyxBadge(text: actor.role.uppercased(), color: NerVyx.primary)
            }
            Spacer()
            NerVyxBadge(text: "ADMIN", color: NerVyx.validation, small: true)
        }
        .nerVyxElevatedCard(accent: NerVyx.primary)
    }

    private func liveGateCard(_ gate: LiveGateState) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "lock.shield.fill")
                .font(.system(size: 22))
                .foregroundStyle(NerVyx.sell)
            VStack(alignment: .leading, spacing: 4) {
                Text(gate.publicLabel)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(NerVyx.sell)
                Text("Exchange route: \(gate.exchangeRouteLabel)")
                    .font(.system(size: 12))
                    .foregroundStyle(NerVyx.textMuted)
            }
            Spacer()
        }
        .padding(14)
        .background(NerVyx.sell.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.sell.opacity(0.3), lineWidth: 1))
    }

    private func trainerCard(_ t: AdminTrainer) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Trainer · NERVYX CORE", accent: NerVyx.primary)
            DataRow(
                label: "State",
                value: t.state,
                valueColor: t.state.hasPrefix("ACTIVE") ? NerVyx.validation : NerVyx.warning
            )
            DataRow(
                label: "Device",
                value: t.device ?? (t.cuda_active ? "cuda:0" : "cpu"),
                valueColor: t.cuda_active ? NerVyx.signal : NerVyx.textMuted,
                mono: true
            )
            DataRow(
                label: "GPU",
                value: t.gpu_name ?? (t.cuda_active ? "Active" : "—"),
                valueColor: t.cuda_active ? NerVyx.validation : NerVyx.textMuted
            )
            DataRow(label: "Steps/hr", value: "\(t.training_steps_last_hour.formatted())", mono: true)
            DataRow(label: "Steps total", value: "\(t.training_steps_total.formatted())", mono: true)
            DataRow(
                label: "Model input",
                value: t.input_dim != nil ? "\(t.input_dim!.formatted()) dims · \(t.feature_count.map { "\($0) feats" } ?? "—")" : "—",
                mono: true
            )
            DataRow(
                label: "Temporal",
                value: (t.temporal_encoder_enabled == true) ? (t.temporal_encoder ?? "on").uppercased() : "SINGLE-FRAME",
                valueColor: (t.temporal_encoder_enabled == true) ? NerVyx.validation : NerVyx.textMuted
            )
        }
        .nerVyxCard()
    }

    private func gpuCard(_ gpu: AdminGPU) -> some View {
        let vramUsedGB = Double(gpu.vram_used_mb) / 1024
        let vramTotalGB = Double(gpu.vram_total_mb) / 1024
        let vramFraction = gpu.vram_total_mb > 0 ? Double(gpu.vram_used_mb) / Double(gpu.vram_total_mb) : 0

        return VStack(spacing: 10) {
            SectionHeader(title: "GPU · \(gpu.displayName)", accent: NerVyx.inference)
            VStack(spacing: 6) {
                DataRow(
                    label: "Utilization",
                    value: "\(Int(gpu.utilization_pct))%",
                    valueColor: gpu.utilization_pct > 85 ? NerVyx.warning : NerVyx.inference,
                    mono: true
                )
                ConfidenceBar(value: gpu.utilization_pct / 100)
            }
            VStack(spacing: 6) {
                DataRow(
                    label: "VRAM",
                    value: String(format: "%.1f / %.1f GB", vramUsedGB, vramTotalGB),
                    valueColor: vramFraction > 0.9 ? NerVyx.warning : NerVyx.signal,
                    mono: true
                )
                ConfidenceBar(value: vramFraction)
            }
        }
        .nerVyxCard(accent: NerVyx.inference.opacity(0.3))
    }

    private func paperCard(_ p: AdminPaper) -> some View {
        VStack(spacing: 10) {
            SectionHeader(title: "Runtime · NERVYX EXECUTE", accent: NerVyx.paper)
            HStack(spacing: 10) {
                NerVyxStatCard(label: "OPEN", value: "\(p.open_positions)", accent: NerVyx.paper)
                NerVyxStatCard(label: "CLOSED", value: "\(p.closed_trades)", accent: NerVyx.borderStrong)
            }
            DataRow(
                label: "Realized PnL",
                value: String(format: "$%.2f", p.realized_pnl_usd),
                valueColor: NerVyx.pnlColor(p.realized_pnl_usd),
                mono: true
            )
            DataRow(
                label: "Unrealized PnL",
                value: String(format: "$%.2f", p.unrealized_pnl_usd),
                valueColor: NerVyx.pnlColor(p.unrealized_pnl_usd),
                mono: true
            )
            DataRow(label: "Accepted", value: "\(p.intents_accepted)", valueColor: NerVyx.buy)
            DataRow(label: "Blocked", value: "\(p.intents_blocked)", valueColor: NerVyx.sell)
        }
        .nerVyxCard()
    }

    private func riskCard(_ r: AdminRisk) -> some View {
        HStack(spacing: 12) {
            Image(
                systemName: r.kill_switch_active ? "exclamationmark.shield.fill" : "shield.checkmark.fill"
            )
            .font(.system(size: 18))
            .foregroundStyle(r.kill_switch_active ? NerVyx.sell : NerVyx.validation)
            VStack(alignment: .leading, spacing: 3) {
                Text("NERVYX GUARD · Risk")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(NerVyx.textSecondary)
                Text(r.state)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(NerVyx.textMuted)
                if let cls = r.classification {
                    Text(cls).font(.system(size: 11)).foregroundStyle(NerVyx.paper)
                }
            }
            Spacer()
            if r.kill_switch_active {
                NerVyxBadge(text: "KILL SWITCH", color: NerVyx.sell)
            }
        }
        .nerVyxCard(accent: r.kill_switch_active ? NerVyx.sell.opacity(0.4) : NerVyx.borderSubtle)
    }

    private func dangerousControlsNote(_ s: MobileAdminSummary) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(NerVyx.warning)
                Text("Dangerous Controls")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(NerVyx.warning)
            }
            Text("Live order routing, leverage, and kill switch controls require explicit human approval via web admin. These actions are blocked on mobile.")
                .font(.system(size: 12))
                .foregroundStyle(NerVyx.textMuted)
            if s.mobile_live_trading_blocked {
                HStack(spacing: 4) {
                    Image(systemName: "lock.fill").font(.system(size: 10)).foregroundStyle(NerVyx.sell)
                    Text("Mobile exchange execution: OPERATOR GATED")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(NerVyx.sell)
                }
            }
        }
        .padding(14)
        .background(NerVyx.warning.opacity(0.07))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.warning.opacity(0.3), lineWidth: 1))
    }

    private func adminNavLinks() -> some View {
        VStack(spacing: 10) {
            NavigationLink(destination: AuditLedgerView()) {
                HStack {
                    Image(systemName: "list.clipboard").foregroundStyle(NerVyx.signal)
                    Text("Audit Ledger")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(NerVyx.textPrimary)
                    Spacer()
                    Image(systemName: "chevron.right").foregroundStyle(NerVyx.textMuted)
                }
                .padding(14)
                .background(NerVyx.panel)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.borderSubtle, lineWidth: 1))
            }
            .buttonStyle(.plain)

            if let webAdminURL = URL(string: appState.baseURL + "/admin") {
                Link(destination: webAdminURL) {
                    HStack {
                        Image(systemName: "safari").foregroundStyle(NerVyx.signal)
                        Text("Open Web Admin")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(NerVyx.signal)
                        Spacer()
                        Image(systemName: "arrow.up.right").foregroundStyle(NerVyx.signal)
                    }
                    .padding(14)
                    .background(NerVyx.signal.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.signal.opacity(0.3), lineWidth: 1))
                }
            }
        }
    }

    private var adminAccessRequired: some View {
        VStack(spacing: 16) {
            Image(systemName: "person.badge.key.fill")
                .font(.system(size: 48))
                .foregroundStyle(NerVyx.warning)
            Text("Admin Access Required")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(NerVyx.textPrimary)
            Text("Your account role does not have admin access.")
                .font(.system(size: 13))
                .foregroundStyle(NerVyx.textMuted)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}

// MARK: - Audit Ledger (live data)

struct AuditLedgerView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AuditViewModel()

    var body: some View {
        ZStack {
            NerVyx.bg.ignoresSafeArea()
            Group {
                if vm.isLoading && vm.entries.isEmpty && vm.summary == nil {
                    VStack(spacing: 12) {
                        ProgressView().tint(NerVyx.primary)
                        Text("Loading audit ledger…")
                            .font(.system(size: 14))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                } else if let err = vm.error, vm.entries.isEmpty {
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
                    auditContent
                }
            }
        }
        .navigationTitle("Audit Ledger")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                HStack(spacing: 12) {
                    Button {
                        Task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
                    } label: {
                        Image(systemName: "arrow.clockwise").foregroundStyle(NerVyx.signal)
                    }
                    if let auditWebURL = URL(string: appState.baseURL + "/audit-ledger") {
                        Link("Web ↗", destination: auditWebURL)
                            .foregroundStyle(NerVyx.signal)
                            .font(.system(size: 13, weight: .medium))
                    }
                }
            }
        }
        .refreshable { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .task { await vm.load(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onAppear { vm.startAutoRefresh(token: auth.currentToken(), baseURL: appState.baseURL) }
        .onDisappear { vm.stopAutoRefresh() }
    }

    private var auditContent: some View {
        ScrollView {
            VStack(spacing: 12) {
                if let s = vm.summary { summaryCard(s) }
                entriesSection
            }
            .padding(16)
            .padding(.bottom, 32)
        }
    }

    private func summaryCard(_ s: AuditLedgerSummary) -> some View {
        // Tri-state chain health: OK (green), BROKEN (red), EMPTY/UNKNOWN (muted).
        let chainColor: Color = {
            if let ok = s.chain_ok { return ok ? NerVyx.validation : NerVyx.sell }
            return NerVyx.textMuted
        }()
        let chainIcon: String = {
            if let ok = s.chain_ok { return ok ? "link" : "link.badge.plus" }
            return s.isKnownEmpty ? "tray" : "questionmark.circle"
        }()
        return HStack(spacing: 12) {
            Circle()
                .fill(chainColor.opacity(0.15))
                .frame(width: 44, height: 44)
                .overlay(
                    Image(systemName: chainIcon)
                        .font(.system(size: 18))
                        .foregroundStyle(chainColor)
                )
            VStack(alignment: .leading, spacing: 4) {
                Text("Chain: \(s.chainLabel)")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(chainColor)
                HStack(spacing: 10) {
                    Text(s.isKnownEmpty ? "No audit events recorded yet" : "Last event \(s.ageLabel)")
                        .font(.system(size: 12))
                        .foregroundStyle(NerVyx.textMuted)
                    if let ts = s.last_event_ts {
                        Text(String(ts.prefix(19)))
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(NerVyx.textMuted)
                    }
                }
            }
            Spacer()
            NerVyxBadge(
                text: s.chainLabel,
                color: chainColor,
                small: true
            )
        }
        .padding(14)
        .background(chainColor.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(chainColor.opacity(0.25), lineWidth: 1)
        )
    }

    private var entriesSection: some View {
        VStack(spacing: 0) {
            SectionHeader(title: "Recent Events (\(vm.entries.count))", accent: NerVyx.signal)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)

            if vm.entries.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "list.clipboard")
                        .font(.system(size: 28))
                        .foregroundStyle(NerVyx.textMuted)
                    Text("No audit events in ledger")
                        .font(.system(size: 13))
                        .foregroundStyle(NerVyx.textMuted)
                }
                .padding(32)
                .frame(maxWidth: .infinity)
            } else {
                ForEach(vm.entries) { entry in
                    AuditEntryRow(entry: entry)
                    if entry.id != vm.entries.last?.id {
                        NerVyxDivider().padding(.horizontal, 16)
                    }
                }
            }
        }
        .background(NerVyx.panel)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(NerVyx.borderSubtle, lineWidth: 1))
    }
}

struct AuditEntryRow: View {
    let entry: AuditLedgerEntry

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(entry.chainOk ? NerVyx.validation.opacity(0.15) : NerVyx.sell.opacity(0.15))
                .frame(width: 8, height: 8)
                .padding(.top, 6)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(entry.displayAct.uppercased())
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(entry.chainOk ? NerVyx.textPrimary : NerVyx.sell)
                    Text("·")
                        .foregroundStyle(NerVyx.textMuted)
                    Text(entry.displaySource)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                    Spacer()
                    Text(entry.ageLabel)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(NerVyx.textMuted)
                }
                Text(entry.displayReason)
                    .font(.system(size: 11))
                    .foregroundStyle(NerVyx.textMuted)
                    .lineLimit(2)
                if let chain = entry.chain_status, !chain.isEmpty {
                    NerVyxBadge(text: chain.uppercased(), color: entry.chainOk ? NerVyx.validation : NerVyx.sell, small: true)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
    }
}

// MARK: - Settings

struct SettingsView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var serverURL = ""
    @State private var showLogoutConfirm = false

    var body: some View {
        NavigationStack {
            ZStack {
                NerVyx.bg.ignoresSafeArea()
                ScrollView {
                    VStack(spacing: 14) {
                        if let session = auth.currentSession {
                            VStack(spacing: 10) {
                                SectionHeader(title: "Account", accent: NerVyx.primary)
                                DataRow(label: "Email", value: session.email)
                                DataRow(label: "Role", value: session.role.uppercased(), valueColor: NerVyx.primary)
                            }
                            .nerVyxCard()
                        }

                        RuntimeTruthLiveCard(title: "Runtime Truth")

                        VStack(spacing: 10) {
                            SectionHeader(title: "Server", accent: NerVyx.signal)
                            VStack(alignment: .leading, spacing: 6) {
                                Text("BACKEND URL")
                                    .font(.system(size: 10, weight: .semibold))
                                    .foregroundStyle(NerVyx.textMuted)
                                    .tracking(0.8)
                                TextField("https://dashboard.wajidali.us", text: $serverURL)
                                    .autocapitalization(.none)
                                    .keyboardType(.URL)
                                    .foregroundStyle(NerVyx.textPrimary)
                                    .font(.system(size: 13, design: .monospaced))
                                    .padding(10)
                                    .background(NerVyx.panelElevated)
                                    .clipShape(RoundedRectangle(cornerRadius: 8))
                                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(NerVyx.borderSubtle, lineWidth: 1))
                                Button("Save URL") {
                                    appState.setBaseURL(serverURL.isEmpty ? "https://dashboard.wajidali.us" : serverURL)
                                }
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(NerVyx.signal)
                            }
                        }
                        .nerVyxCard()

                        Button(role: .destructive) {
                            showLogoutConfirm = true
                        } label: {
                            HStack {
                                Image(systemName: "rectangle.portrait.and.arrow.right")
                                    .foregroundStyle(NerVyx.sell)
                                Text("Sign Out")
                                    .font(.system(size: 15, weight: .medium))
                                    .foregroundStyle(NerVyx.sell)
                                Spacer()
                            }
                            .padding(14)
                            .background(NerVyx.sell.opacity(0.08))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(NerVyx.sell.opacity(0.3), lineWidth: 1))
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(16)
                    .padding(.bottom, 24)
                }
            }
            .navigationTitle("Settings")
            .onAppear { serverURL = appState.baseURL }
            .confirmationDialog("Sign Out?", isPresented: $showLogoutConfirm) {
                Button("Sign Out", role: .destructive) {
                    Task { await auth.logout(baseURL: appState.baseURL) }
                }
                Button("Cancel", role: .cancel) {}
            }
        }
    }
}
