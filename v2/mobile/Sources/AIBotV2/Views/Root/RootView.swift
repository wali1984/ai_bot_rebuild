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
                .tabItem { Label("Positions", systemImage: "chart.line.uptrend.xyaxis") }
                .tag(AppTab.positions)

            SignalsView()
                .tabItem { Label("Signals", systemImage: "antenna.radiowaves.left.and.right") }
                .tag(AppTab.signals)

            PaperTradingView()
                .tabItem { Label("Paper", systemImage: "doc.plaintext") }
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
        @Bindable var state = appState
        NavigationSplitView {
            List(selection: $state.selectedTab) {
                Section("Trading") {
                    Label("Dashboard", systemImage: "gauge.high").tag(AppTab.dashboard)
                    Label("Positions", systemImage: "chart.line.uptrend.xyaxis").tag(AppTab.positions)
                    Label("Signals", systemImage: "antenna.radiowaves.left.and.right").tag(AppTab.signals)
                    Label("Paper Trading", systemImage: "doc.plaintext").tag(AppTab.paper)
                    Label("Alerts", systemImage: "bell.badge").tag(AppTab.alerts)
                }
                Section("Risk & Control") {
                    Label("Risk Control", systemImage: "shield.lefthalf.filled").tag(AppTab.risk)
                }
                Section("System") {
                    Label("Monitor", systemImage: "server.rack").tag(AppTab.monitor)
                }
                if auth.currentSession?.isAdmin == true {
                    Section("Admin") {
                        Label("Admin", systemImage: "person.badge.key").tag(AppTab.admin)
                    }
                }
                Section("Account") {
                    Label("Settings", systemImage: "gear").tag(AppTab.settings)
                }
            }
            .navigationTitle("AI BOT V2")
            .listStyle(.sidebar)
        } detail: {
            detailView(for: appState.selectedTab)
        }
    }

    @ViewBuilder
    private func detailView(for tab: AppTab) -> some View {
        switch tab {
        case .dashboard: DashboardView()
        case .positions: PositionsView()
        case .signals: SignalsView()
        case .paper: PaperTradingView()
        case .alerts: AlertsView()
        case .risk: RiskControlView()
        case .monitor: MonitorView()
        case .admin: AdminDashboardView()
        case .settings: SettingsView()
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
                Section("System") {
                    NavigationLink("Alerts") { AlertsView() }
                    NavigationLink("Risk Control") { RiskControlView() }
                    NavigationLink("Monitor") { MonitorView() }
                }
                if auth.currentSession?.isAdmin == true {
                    Section("Admin") {
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
