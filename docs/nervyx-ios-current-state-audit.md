# NERVYX iOS Current State Audit

- Project path: `v2/mobile`
- Package: `v2/mobile/Package.swift`
- Xcode project/workspace: not present in repository; Swift Package targets are the discoverable build units.
- App target: `AIBotV2` on non-Linux platforms
- Core target: `AIBotV2Core`
- Test target: `AIBotV2Tests`
- Watch target: `AIBotV2Watch` on non-Linux platforms
- SwiftUI/UIKit: SwiftUI
- Bundle identifier/signing: preserved; no signing files changed by this lane
- API base URL handling: `AppState` / existing API client; no production localhost introduced
- Auth handling: existing backend auth manager and Keychain helper; backend remains role authority
- Realtime handling: `WebSocketClient.swift` exists; parity matrix records current categories

## Swift Sources

- `v2/mobile/Package.swift`
- `v2/mobile/Sources/AIBotV2/App/AIBotV2App.swift`
- `v2/mobile/Sources/AIBotV2/App/AppState.swift`
- `v2/mobile/Sources/AIBotV2/Auth/AuthManager.swift`
- `v2/mobile/Sources/AIBotV2/Auth/KeychainHelper.swift`
- `v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift`
- `v2/mobile/Sources/AIBotV2/Brand/Generated/NervyxTokens.swift`
- `v2/mobile/Sources/AIBotV2/Brand/NervyxBrand.swift`
- `v2/mobile/Sources/AIBotV2/Models/APIModels.swift`
- `v2/mobile/Sources/AIBotV2/Networking/APIClient.swift`
- `v2/mobile/Sources/AIBotV2/Networking/APIEndpoints.swift`
- `v2/mobile/Sources/AIBotV2/Networking/WebSocketClient.swift`
- `v2/mobile/Sources/AIBotV2/Notifications/NotificationManager.swift`
- `v2/mobile/Sources/AIBotV2/ViewModels/AdminViewModel.swift`
- `v2/mobile/Sources/AIBotV2/ViewModels/AlertsViewModel.swift`
- `v2/mobile/Sources/AIBotV2/ViewModels/DashboardViewModel.swift`
- `v2/mobile/Sources/AIBotV2/ViewModels/PaperViewModel.swift`
- `v2/mobile/Sources/AIBotV2/ViewModels/PositionsViewModel.swift`
- `v2/mobile/Sources/AIBotV2/ViewModels/SignalsViewModel.swift`
- `v2/mobile/Sources/AIBotV2/Views/Admin/AdminDashboardView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Alerts/AlertsView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Auth/LoginView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Components/ErrorStateView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Components/LiveBlockBanner.swift`
- `v2/mobile/Sources/AIBotV2/Views/Components/MetricRow.swift`
- `v2/mobile/Sources/AIBotV2/Views/Components/StatusBadge.swift`
- `v2/mobile/Sources/AIBotV2/Views/Dashboard/DashboardView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Monitor/MonitorView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Paper/PaperTradingView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Positions/PositionsView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Risk/RiskControlView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Root/RootView.swift`
- `v2/mobile/Sources/AIBotV2/Views/Signals/SignalsView.swift`
- `v2/mobile/Sources/AIBotV2CLI/main.swift`
- `v2/mobile/Sources/AIBotV2Core/APIClient.swift`
- `v2/mobile/Sources/AIBotV2Core/APIEndpoints.swift`
- `v2/mobile/Sources/AIBotV2Core/APIError.swift`
- `v2/mobile/Sources/AIBotV2Core/AuthManager.swift`
- `v2/mobile/Sources/AIBotV2Core/Models.swift`
- `v2/mobile/Sources/AIBotV2Core/TokenStore.swift`
- `v2/mobile/Sources/AIBotV2Watch/App/WatchApp.swift`
- `v2/mobile/Sources/AIBotV2Watch/Connectivity/WatchConnectivityManager.swift`
- `v2/mobile/Sources/AIBotV2Watch/Views/WatchAlertsView.swift`
- `v2/mobile/Sources/AIBotV2Watch/Views/WatchDashboardView.swift`
- `v2/mobile/Sources/AIBotV2Watch/Views/WatchModels.swift`
- `v2/mobile/Sources/AIBotV2Watch/Views/WatchPositionsView.swift`
- `v2/mobile/Sources/AIBotV2Watch/Views/WatchRootView.swift`
- `v2/mobile/Sources/AIBotV2Watch/Views/WatchSystemView.swift`
- `v2/mobile/Tests/AIBotV2Tests/AIBotV2CoreTests.swift`

## Current Rebrand Actions

- App display name visible in Info.plist/Login/Root views is NERVYX ONE.
- Native screens keep existing typed data models and API calls while adding NERVYX module labels.
- Ops Terminal remains gated by backend-confirmed admin state.

## TestFlight Blockers

- App Store Connect credentials and macOS/Xcode archive environment are not available in this Linux workspace.
- Upload is BLOCKED until existing signing/App Store workflow is used.
