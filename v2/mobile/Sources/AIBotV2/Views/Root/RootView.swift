import SwiftUI

/// Root view — shows login if not authenticated, main app otherwise.
/// Adapts layout for iPhone (TabView) vs iPad (NavigationSplitView).
struct ContentView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState

    var body: some View {
        switch auth.state {
        case .loggedOut:
            LoginView()
        case .loading:
            LoadingView(message: "Restoring session...")
        case .loggedIn:
            AdaptiveLayout()
        case .error:
            LoginView()
        }
    }
}

struct AdaptiveLayout: View {
    @Environment(\.horizontalSizeClass) private var hSizeClass

    var body: some View {
        if hSizeClass == .regular {
            iPadLayout()
        } else {
            iPhoneLayout()
        }
    }
}

// MARK: - iPhone Layout (TabView)

struct iPhoneLayout: View {
    @Environment(AppState.self) private var appState
    @Environment(AuthManager.self) private var auth

    var body: some View {
        @Bindable var state = appState
        TabView(selection: $state.selectedTab) {
            DashboardView()
                .tabItem { Label("Dashboard", systemImage: "gauge.high") }
                .tag(AppTab.dashboard)

            PositionsView()
                .tabItem { Label("Portfolio", systemImage: "chart.line.uptrend.xyaxis") }
                .tag(AppTab.positions)

            SignalsView()
                .tabItem { Label("Signals", systemImage: "antenna.radiowaves.left.and.right") }
                .tag(AppTab.signals)

            PaperTradingView()
                .tabItem { Label("Execute", systemImage: "bolt.horizontal.circle") }
                .tag(AppTab.paper)

            MoreView()
                .tabItem { Label("More", systemImage: "ellipsis.circle") }
                .tag(AppTab.monitor)
        }
    }
}

// MARK: - iPad Layout (NavigationSplitView)

struct iPadLayout: View {
    @Environment(AppState.self) private var appState
    @Environment(AuthManager.self) private var auth

    var body: some View {
        NavigationSplitView {
            List {
                Section("NERVYX EXECUTE") {
                    sidebarRow(.dashboard,  "Dashboard",     "gauge.high")
                    sidebarRow(.positions,  "Positions",     "chart.line.uptrend.xyaxis")
                    sidebarRow(.signals,    "Signals",       "antenna.radiowaves.left.and.right")
                    sidebarRow(.paper,      "Execute",       "bolt.horizontal.circle")
                    sidebarRow(.alerts,     "Alerts",        "bell.badge")
                }
                Section("NERVYX GUARD") {
                    sidebarRow(.risk,    "Risk Control", "shield.lefthalf.filled")
                }
                Section("NERVYX OBSERVE") {
                    sidebarRow(.monitor, "Monitor",      "server.rack")
                }
                if auth.currentSession?.isAdmin == true {
                    Section("Ops Terminal") {
                        sidebarRow(.admin, "Admin", "person.badge.key")
                    }
                }
                Section("Account") {
                    sidebarRow(.settings, "Settings", "gear")
                }
            }
            .navigationTitle("NERVYX ONE")
            .listStyle(.sidebar)
        } detail: {
            detailView(for: appState.selectedTab)
        }
    }

    @ViewBuilder
    private func sidebarRow(_ tab: AppTab, _ title: String, _ icon: String) -> some View {
        Button(action: { appState.selectedTab = tab }) {
            Label(title, systemImage: icon)
        }
        .listRowBackground(
            appState.selectedTab == tab ? Color.accentColor.opacity(0.15) : Color.clear
        )
        .foregroundStyle(appState.selectedTab == tab ? Color.accentColor : Color.primary)
    }

    @ViewBuilder
    private func detailView(for tab: AppTab) -> some View {
        switch tab {
        case .dashboard: DashboardView()
        case .positions: PositionsView()
        case .signals:   SignalsView()
        case .paper:     PaperTradingView()
        case .alerts:    AlertsView()
        case .risk:      RiskControlView()
        case .monitor:   MonitorView()
        case .admin:     AdminDashboardView()
        case .settings:  SettingsView()
        }
    }
}

// MARK: - More (iPhone overflow menu)

struct MoreView: View {
    @Environment(AuthManager.self) private var auth
    @Environment(AppState.self) private var appState

    var body: some View {
        NavigationStack {
            List {
                Section("NERVYX OBSERVE") {
                    NavigationLink("Alerts") { AlertsView() }
                    NavigationLink("Risk Control") { RiskControlView() }
                    NavigationLink("Monitor") { MonitorView() }
                }
                if auth.currentSession?.isAdmin == true {
                    Section("Ops Terminal") {
                        NavigationLink("Admin Dashboard") { AdminDashboardView() }
                    }
                }
                Section("Account") {
                    NavigationLink("Settings") { SettingsView() }
                }
            }
            .navigationTitle("More")
        }
    }
}
