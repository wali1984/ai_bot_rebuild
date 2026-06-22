import SwiftUI

struct AdminDashboardView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState
    @State private var vm = AdminViewModel()
    @State private var showLogoutConfirm = false

    var body: some View {
        NavigationStack {
            Group {
                if vm.isLoading && vm.summary == nil {
                    LoadingView()
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
            .navigationTitle("NERVYX OBSERVE")
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
                        Image(systemName: "ellipsis.circle")
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
            VStack(spacing: 16) {
                // Actor info
                actorCard(s.actor)

                // Live gate
                liveGateCard(s.live_gate)

                // Trainer
                trainerCard(s.trainer)

                // GPU
                gpuCard(s.gpu)

                // Paper
                paperCard(s.paper)

                // Risk
                riskCard(s.risk)

                // Warning
                dangerousControlsNote()

                // Navigation
                adminNavLinks()
            }
            .padding()
        }
    }

    private func actorCard(_ actor: AdminActor) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "person.circle.fill")
                .font(.largeTitle)
                .foregroundStyle(.blue)
            VStack(alignment: .leading) {
                Text(actor.email).font(.subheadline.weight(.semibold))
                StatusBadge(label: actor.role.uppercased(), color: .blue)
            }
            Spacer()
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func liveGateCard(_ gate: LiveGateState) -> some View {
        HStack {
            Image(systemName: "lock.shield.fill").foregroundStyle(.red)
            VStack(alignment: .leading) {
                Text(gate.label).font(.subheadline.weight(.bold)).foregroundStyle(.red)
                Text("Places real order: \(gate.places_real_order ? "YES ⚠️" : "NO ✓")")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding()
        .background(Color.red.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func trainerCard(_ t: AdminTrainer) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("NERVYX CORE · Trainer", systemImage: "brain").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            MetricRow(label: "State", value: t.state, valueColor: t.state.hasPrefix("ACTIVE") ? .green : .orange)
            MetricRow(label: "CUDA", value: t.cuda_active ? "Active" : "Off", valueColor: t.cuda_active ? .green : .red)
            MetricRow(label: "Steps/hr", value: "\(t.training_steps_last_hour.formatted())")
            MetricRow(label: "Steps total", value: "\(t.training_steps_total.formatted())")
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func gpuCard(_ gpu: GPUState) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("NERVYX CORE · GPU — \(gpu.name.isEmpty ? "Unknown" : gpu.name)", systemImage: "cpu.fill")
                .font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            GaugeCard(title: "Utilization", value: gpu.utilization_pct, max: 100, unit: "%",
                      color: gpu.utilization_pct > 90 ? .orange : .blue)
            GaugeCard(title: "VRAM", value: gpu.vramUsedGB, max: gpu.vramTotalGB, unit: " GB",
                      color: gpu.vramPercent > 90 ? .orange : .purple)
        }
    }

    private func paperCard(_ p: AdminPaper) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("NERVYX EXECUTE · Runtime", systemImage: "bolt.horizontal.circle").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            HStack(spacing: 12) {
                MetricCard(title: "Open", value: "\(p.open_positions)", icon: "chart.line.uptrend.xyaxis")
                MetricCard(title: "Closed", value: "\(p.closed_trades)", icon: "checkmark.circle")
            }
            MetricRow(label: "Realized PnL", value: String(format: "$%.2f", p.realized_pnl_usd),
                      valueColor: p.realized_pnl_usd >= 0 ? .green : .red)
            MetricRow(label: "Unrealized PnL", value: String(format: "$%.2f", p.unrealized_pnl_usd),
                      valueColor: p.unrealized_pnl_usd >= 0 ? .green : .red)
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func riskCard(_ r: AdminRisk) -> some View {
        HStack {
            Label("NERVYX GUARD · Risk", systemImage: r.kill_switch_active ? "exclamationmark.shield.fill" : "shield.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(r.kill_switch_active ? .red : .secondary)
            Spacer()
            Text(r.state)
                .font(.caption.weight(.semibold))
                .foregroundStyle(r.state == "UNKNOWN" ? .secondary : .primary)
            if r.kill_switch_active {
                StatusBadge(label: "KILL SWITCH", color: .red)
            }
        }
        .padding()
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func dangerousControlsNote() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("NERVYX GUARD · Dangerous Controls", systemImage: "exclamationmark.triangle.fill")
                .font(.subheadline.weight(.semibold)).foregroundStyle(.orange)
            Text("Live trading, leverage changes, and kill switch controls require explicit human approval via the web admin interface. These actions are NOT available from mobile for safety.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding()
        .background(Color.orange.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    private func adminNavLinks() -> some View {
        VStack(spacing: 12) {
            NavigationLink(destination: AuditLedgerView()) {
                Label("NERVYX REPLAY · Audit Ledger", systemImage: "list.clipboard")
            }
            .buttonStyle(.borderedProminent)
            .tint(.secondary)

            Link("Open Web Admin ↗", destination: URL(string: appState.baseURL + "/admin")!)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.blue.opacity(0.1))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private var adminAccessRequired: some View {
        VStack(spacing: 16) {
            Image(systemName: "person.badge.key.fill")
                .font(.system(size: 52))
                .foregroundStyle(.orange)
            Text("Admin Access Required")
                .font(.headline)
            Text("Your account role does not have admin access. Contact your administrator.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Audit Ledger

struct AuditLedgerView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        Text("Audit Ledger — Open in Web Admin for full details")
            .foregroundStyle(.secondary)
            .navigationTitle("Audit Ledger")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Link("Web ↗", destination: URL(string: appState.baseURL + "/audit-ledger")!)
                }
            }
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
            Form {
                if let session = auth.currentSession {
                    Section("Account") {
                        MetricRow(label: "Email", value: session.email)
                        MetricRow(label: "Role", value: session.role.uppercased())
                    }
                }
                Section("Server") {
                    TextField("Server URL", text: $serverURL)
                        .autocapitalization(.none)
                        .keyboardType(.URL)
                    Button("Save Server URL") {
                        appState.setBaseURL(serverURL.isEmpty ? "http://127.0.0.1:5173" : serverURL)
                    }
                }
                Section {
                    Button("Sign Out", role: .destructive) {
                        showLogoutConfirm = true
                    }
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
