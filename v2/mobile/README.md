# NERVYX ONE — iOS / iPadOS / watchOS Native App

**Platform:** iOS 17+ / iPadOS 17+ / watchOS 10+  
**Language:** Swift 5.9 / SwiftUI  
**Backend:** NERVYX ONE FastAPI backend at `http://127.0.0.1:5173`

---

## Features

### iPhone
| Tab | Description |
|-----|-------------|
| Dashboard | System overview — GPU, trainer, paper loop, PnL, alerts preview |
| Positions | Live paper positions with PnL, entry/mark price, side |
| Signals | Active signal feed with confidence, actionability, risk state |
| Paper | Paper trading loop metrics, feedback, win rate |
| More → Alerts | Market alerts with severity filter |
| More → Risk Control | Risk gate, kill switch, limits, paper gate stats |
| More → Monitor | System health — trainer, GPU, Redis, paper loop |
| More → Admin | Admin dashboard (admin/superadmin role required) |
| More → Settings | Server URL, account info, sign out |

### iPad (NavigationSplitView sidebar)
Same content as iPhone but in a full sidebar + detail panel layout. All tabs are visible simultaneously.

### Apple Watch (TabView)
| Page | Description |
|------|-------------|
| Dashboard | Status dot, total PnL, positions, loop stats |
| Positions | Compact position list with per-position PnL |
| Alerts | Recent alerts with severity |
| System | Trainer, GPU bar, signals count, phone connection |

---

## Safety
- **Live trading is permanently blocked** — this app only reads data and controls paper trading state
- All dangerous actions (enable live trading, leverage changes, kill switch) require web admin approval
- Push notifications are informational only — no trade execution from push
- Bearer token stored in iOS Keychain (not in UserDefaults or files)

---

## Setup in Xcode

### Requirements
- macOS 14+ (Sonoma or later)
- Xcode 15.4+
- Apple Developer account (free tier works for simulator; paid for device + Watch)
- iPhone and Apple Watch on same Apple ID for WatchConnectivity

---

### Step 1: Create the Xcode Project

1. Open **Xcode**
2. File → New → Project
3. Select **iOS → App**, click Next
4. Fill in:
   - Product Name: `AIBotV2`
   - Team: your Apple Developer team
   - Organization ID: `com.yourname`
   - Bundle Identifier: `com.yourname.aibot-v2`
   - Interface: **SwiftUI**
   - Language: **Swift**
   - ✅ Include Tests
5. Save to: `/home/wali/Desktop/AI BOT REBUILD/v2/mobile/AIBotV2.xcodeproj` (or any convenient location)

---

### Step 2: Add watchOS Target

1. File → New → Target
2. Choose **watchOS → Watch App**
3. Product Name: `AIBotV2Watch`
4. Ensure "Watch App for iOS App" is checked and iOS target is `AIBotV2`
5. Xcode creates both `AIBotV2Watch` target and `AIBotV2Watch Extension` (watchOS 7 style) or just `AIBotV2Watch` (watchOS 10 style)

---

### Step 3: Add Source Files

**For the iOS target (`AIBotV2`):**

Delete the auto-generated `ContentView.swift` and `AIBotV2App.swift` that Xcode created, then drag in all files from:
```
Sources/AIBotV2/
├── App/        → AIBotV2App.swift, AppState.swift
├── Auth/       → AuthManager.swift, KeychainHelper.swift
├── Models/     → APIModels.swift
├── Networking/ → APIClient.swift, APIEndpoints.swift, WebSocketClient.swift
├── Notifications/ → NotificationManager.swift
├── ViewModels/ → DashboardViewModel.swift, PositionsViewModel.swift,
│                 SignalsViewModel.swift, PaperViewModel.swift,
│                 AlertsViewModel.swift, AdminViewModel.swift
└── Views/      → (all view files recursively)
```

When adding files, in the "Add to targets" dialog: check **AIBotV2** only (not the watch target).

**For the watchOS target (`AIBotV2Watch`):**

Add files from:
```
Sources/AIBotV2Watch/
├── App/           → WatchApp.swift
├── Connectivity/  → WatchConnectivityManager.swift
└── Views/         → WatchModels.swift, WatchRootView.swift,
                     WatchDashboardView.swift, WatchPositionsView.swift,
                     WatchAlertsView.swift, WatchSystemView.swift
```

When adding, check **AIBotV2Watch** target only.

**Files shared between both targets:**  
`WatchConnectivityManager.swift` must also be added to the **iOS target** (`AIBotV2`) for the iPhone-side connectivity to work. In the File Inspector (right panel), add `AIBotV2` to its Target Membership.

---

### Step 4: Configure Capabilities

**iOS target (`AIBotV2`):**
1. Target → Signing & Capabilities
2. Click `+ Capability` → add:
   - **Push Notifications** (for APNS)
   - **Background Modes** → check "Remote notifications"
   - **Keychain Sharing** (for token storage)

**watchOS target (`AIBotV2Watch`):**
1. Target → Signing & Capabilities  
2. No extra capabilities needed — WatchConnectivity works by default

---

### Step 5: Configure App Groups (for shared data)

If you want the iOS app to push data updates directly to the Watch widget:

1. iOS target → Capabilities → **App Groups** → add `group.com.yourname.aibot-v2`
2. watchOS target → Capabilities → **App Groups** → add the same group

---

### Step 6: Set Server URL

The app defaults to `http://127.0.0.1:5173`. To connect to your server:

**Option A: Change default in AppState.swift**
```swift
// Sources/AIBotV2/Models/APIModels.swift line ~174
public static var baseURL: String {
    get { KeychainHelper.shared.loadBaseURL() ?? "http://YOUR.SERVER.IP:5173" }
```

**Option B: Change it in-app**  
Login screen → Server Settings → enter your server IP → Save

**For LAN access from iPhone:** Use your Mac's LAN IP (e.g., `http://192.168.1.100:5173`)  
**For internet access:** Set up a reverse proxy with HTTPS. The app supports `https://` URLs natively.

---

### Step 7: Build and Run

**Simulator (no signing needed):**
1. Select scheme `AIBotV2` → Any iPhone Simulator
2. Cmd+R to build and run
3. For Watch: select scheme `AIBotV2Watch` → Apple Watch Ultra 2 (49mm) simulator

**Real Device:**
1. Connect iPhone via USB
2. Select your iPhone in the scheme picker
3. Cmd+R — Xcode will sign and install

**For Watch on device:**
- Pair your Apple Watch in Xcode (Devices & Simulators)
- Build the watchOS scheme alongside the iOS scheme
- The watch app installs automatically via iPhone

---

### Step 8: Network (for LAN testing)

The V2 backend runs on `127.0.0.1:5173` which is only accessible from localhost. To test on a real iPhone:

**Option 1: ngrok tunnel**
```bash
ngrok http 5173
# Use the https://xxx.ngrok.io URL in the app
```

**Option 2: Local network binding**  
Edit the backend startup to bind to `0.0.0.0:5173` instead of `127.0.0.1:5173`, then use your Mac's LAN IP.

Add to `Info.plist` for HTTP (non-HTTPS) LAN access:
```xml
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
    <key>NSExceptionDomains</key>
    <dict>
        <key>192.168.1.100</key>  <!-- your server LAN IP -->
        <dict>
            <key>NSExceptionAllowsInsecureHTTPLoads</key>
            <true/>
        </dict>
    </dict>
</dict>
```

---

## Authentication

The app uses JWT Bearer token auth — the same tokens as the web interface.

**Login:** email + password → `POST /api/auth/login` → token stored in Keychain  
**Subsequent requests:** `Authorization: Bearer <token>` header on all API calls  
**Roles:**
- `viewer` — read-only (dashboard, positions, signals)
- `trader` — same as viewer
- `admin` — adds Admin Dashboard tab
- `superadmin` — full audit access

---

## Backend Mobile Endpoints

All mobile endpoints are at `/api/v2/mobile/`:

| Endpoint | Auth | Description |
|----------|------|-------------|
| GET `/api/v2/mobile/dashboard` | Optional | Compact system overview |
| GET `/api/v2/mobile/positions` | Optional | Paper positions + PnL |
| GET `/api/v2/mobile/signals` | Optional | Top signals feed |
| GET `/api/v2/mobile/alerts` | Optional | Market alerts |
| GET `/api/v2/mobile/health` | Optional | System health |
| GET `/api/v2/mobile/risk-status` | Optional | Risk gate status |
| GET `/api/v2/mobile/paper-summary` | Optional | Paper trading summary |
| GET `/api/v2/mobile/admin/summary` | Required (admin) | Admin overview |
| POST `/api/v2/mobile/push/register` | Required | Register APNS token |
| DELETE `/api/v2/mobile/push/{token}` | Required | Unregister push |

---

## WebSocket Streams

The iOS app can use real-time WebSocket streams for live market data:

| Endpoint | Description |
|----------|-------------|
| `ws://host/ws/market-data?symbol=BTCUSDT&timeframe=1m` | Real-time OHLCV + indicators |
| `ws://host/ws/paper-activity` | Paper fills, positions, audit events |

To connect from the iOS app (example):
```swift
// In a ViewModel
let ws = WebSocketClient()
ws.connect(
    urlString: AppConfiguration.baseWSURL + "/ws/market-data?symbol=BTCUSDT&timeframe=1m",
    token: authManager.currentToken()
) { message in
    // handle JSON message
}
```

---

## WatchConnectivity

The iPhone app sends compact system state to the Watch every time it refreshes (every 10 seconds).

**Data sent to Watch:**
```json
{
  "dashboard": {
    "overall": "healthy",
    "trainer_active": true,
    "gpu_utilization": 99.0,
    "open_positions": 27,
    "total_pnl": 33.79,
    "realized_pnl": 11.29,
    "unrealized_pnl": 22.50,
    "signals_seen": 801,
    "intents_accepted": 70,
    "intents_blocked": 731,
    "live_blocked": true,
    "last_updated": "2026-06-18T09:35:00Z"
  },
  "positions": [...],
  "alerts": [...]
}
```

**To enable Watch data sync**, add this to `DashboardViewModel.load()` after successful data load:
```swift
// In DashboardViewModel.swift, after loading dashboard:
WatchConnectivityManager.shared.sendSystemState([
    "dashboard": [
        "overall": health?.overall ?? "unknown",
        "trainer_active": dashboard?.trainer.isActive ?? false,
        "gpu_utilization": dashboard?.gpu.utilization_pct ?? 0,
        "open_positions": dashboard?.paper.open_positions ?? 0,
        "total_pnl": dashboard?.paper.total_pnl ?? 0,
        "realized_pnl": dashboard?.paper.realized_pnl_usd ?? 0,
        "unrealized_pnl": dashboard?.paper.unrealized_pnl_usd ?? 0,
        "signals_seen": dashboard?.paper.signals_seen ?? 0,
        "intents_accepted": dashboard?.paper.intents_accepted ?? 0,
        "intents_blocked": dashboard?.paper.intents_blocked ?? 0,
        "live_blocked": true,
        "last_updated": dashboard?.generated_utc ?? ""
    ],
    "positions": positions?.positions.prefix(10).map { [
        "id": $0.id,
        "symbol": $0.symbol,
        "side": $0.side,
        "unrealized_pnl": $0.unrealized_pnl,
        "entry_price": $0.entry_price,
        "mark_price": $0.mark_price
    ]} ?? [],
    "alerts": alerts?.alerts.prefix(5).map { [
        "id": $0.id,
        "symbol": $0.symbol,
        "type": $0.type,
        "severity": $0.severity,
        "message": $0.message
    ]} ?? []
])
```

---

## Project File Structure

```
v2/mobile/
├── Package.swift                          ← Swift Package (for IDE support)
├── README.md                              ← This file
├── Sources/
│   ├── AIBotV2/                           ← iOS/iPadOS app
│   │   ├── App/
│   │   │   ├── AIBotV2App.swift           ← @main entry point
│   │   │   └── AppState.swift             ← Global app state + tab selection
│   │   ├── Auth/
│   │   │   ├── AuthManager.swift          ← JWT auth, login/logout
│   │   │   └── KeychainHelper.swift       ← Secure token/URL storage
│   │   ├── Models/
│   │   │   └── APIModels.swift            ← All Decodable response types
│   │   ├── Networking/
│   │   │   ├── APIClient.swift            ← URLSession HTTP client (actor)
│   │   │   ├── APIEndpoints.swift         ← All endpoint path constants
│   │   │   └── WebSocketClient.swift      ← URLSession WebSocket client
│   │   ├── Notifications/
│   │   │   └── NotificationManager.swift  ← APNS + local notifications
│   │   ├── ViewModels/
│   │   │   ├── DashboardViewModel.swift
│   │   │   ├── PositionsViewModel.swift
│   │   │   ├── SignalsViewModel.swift
│   │   │   ├── PaperViewModel.swift
│   │   │   ├── AlertsViewModel.swift
│   │   │   └── AdminViewModel.swift
│   │   └── Views/
│   │       ├── Auth/          LoginView.swift
│   │       ├── Root/          RootView.swift (iPhone TabView + iPad Split)
│   │       ├── Dashboard/     DashboardView.swift
│   │       ├── Positions/     PositionsView.swift, PositionDetailView
│   │       ├── Signals/       SignalsView.swift, SignalDetailView
│   │       ├── Paper/         PaperTradingView.swift
│   │       ├── Risk/          RiskControlView.swift
│   │       ├── Alerts/        AlertsView.swift
│   │       ├── Monitor/       MonitorView.swift
│   │       ├── Admin/         AdminDashboardView.swift, SettingsView
│   │       └── Components/    LiveBlockBanner, StatusBadge, MetricRow,
│   │                          MetricCard, GaugeCard, ErrorStateView
│   └── AIBotV2Watch/                      ← watchOS companion
│       ├── App/
│       │   └── WatchApp.swift             ← @main, WatchAppDelegate, WatchAppState
│       ├── Connectivity/
│       │   └── WatchConnectivityManager.swift ← WCSession bridge
│       └── Views/
│           ├── WatchModels.swift          ← Watch-specific compact models
│           ├── WatchRootView.swift        ← TabView root
│           ├── WatchDashboardView.swift   ← Status, PnL, positions summary
│           ├── WatchPositionsView.swift   ← Compact positions list
│           ├── WatchAlertsView.swift      ← Alerts feed
│           └── WatchSystemView.swift      ← Trainer, GPU, connectivity
```

---

## Troubleshooting

**"App Transport Security" errors on iOS simulator:**  
Add to `Info.plist`:
```xml
<key>NSAppTransportSecurity</key>
<dict><key>NSAllowsArbitraryLoads</key><true/></dict>
```
(Remove before App Store submission — use HTTPS in production)

**401 Unauthorized from backend:**  
The session may have expired. Sign out and back in. The backend token TTL is configurable.

**Watch not receiving data:**  
- Ensure both app and watch app share the same Apple ID / team
- Check Xcode > Devices & Simulators that Watch is paired
- WatchConnectivity only works when both apps are installed and at least one is active

**Build error: `@Observable` not found:**  
Ensure deployment target is iOS 17+ in Build Settings → `IPHONEOS_DEPLOYMENT_TARGET = 17.0`

**`WCSession` not available on macOS:**  
The `WatchConnectivityManager` uses `#if os(iOS)` guards — it will not compile on macOS targets.
