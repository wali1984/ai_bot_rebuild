import Foundation
#if canImport(Glibc)
import Glibc
#endif
import AIBotV2Core

// MARK: - ANSI colours

private enum C {
    static let reset  = "\u{001B}[0m"
    static let bold   = "\u{001B}[1m"
    static let red    = "\u{001B}[31m"
    static let green  = "\u{001B}[32m"
    static let yellow = "\u{001B}[33m"
    static let blue   = "\u{001B}[34m"
    static let cyan   = "\u{001B}[36m"
    static let dimmed = "\u{001B}[2m"
}

private func b(_ s: String)  -> String { "\(C.bold)\(s)\(C.reset)" }
private func g(_ s: String)  -> String { "\(C.green)\(s)\(C.reset)" }
private func r(_ s: String)  -> String { "\(C.red)\(s)\(C.reset)" }
private func y(_ s: String)  -> String { "\(C.yellow)\(s)\(C.reset)" }
private func cy(_ s: String) -> String { "\(C.cyan)\(s)\(C.reset)" }
private func dim(_ s: String)-> String { "\(C.dimmed)\(s)\(C.reset)" }

private func pnlStr(_ v: Double) -> String {
    v >= 0 ? g(String(format: "+$%.2f", v)) : r(String(format: "-$%.2f", abs(v)))
}

private func bar(_ frac: Double, width: Int = 20, color: String = C.blue) -> String {
    let filled = max(0, min(width, Int(frac * Double(width))))
    let empty  = width - filled
    return color + String(repeating: "█", count: filled) + C.dimmed
           + String(repeating: "░", count: empty) + C.reset
}

private func separator(_ char: String = "─", width: Int = 60) -> String {
    String(repeating: char, count: width)
}

// Cross-platform stty helper (disables/restores terminal echo for password entry)
private func runStty(_ arg: String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: "/bin/stty")
    p.arguments = [arg]
    try? p.run()
    p.waitUntilExit()
}

// MARK: - CLI help

func printHelp() {
    print("""
    \(b("NERVYX ONE — CLI"))  Swift 6 on Linux
    \(separator())
    Usage: aibot <command> [options]

    Commands:
      status            System dashboard (default)
      positions         Open execution positions
      signals           Latest signals
      alerts            Recent market alerts
      execute           Execution runtime summary
      risk              Risk gate status
      health            System health check
      admin             Admin summary (requires admin role)
      login             Sign in and save credentials
      logout            Sign out
      config            Show / set server URL
      watch             Live-refresh dashboard every N seconds

    Options:
      --server <url>    Override server URL for this call
      --token  <jwt>    Override token for this call
      --limit  <n>      Number of rows (signals / alerts)
      --interval <n>    Refresh interval in seconds (watch command)
      --help            Show this help

    Examples:
      aibot                          # show dashboard
      aibot login                    # interactive login
      aibot config --server http://192.168.1.100:5173
      aibot watch --interval 5       # live dashboard, refresh every 5s
      aibot positions
      aibot signals --limit 10
      aibot admin

    Server URL default: http://127.0.0.1:5173
    Credentials stored: ~/.config/aibot/credentials.json
    """)
}

func printHeader(_ title: String) {
    print("")
    print(b(separator("═")))
    print(b("  NERVYX ONE  ·  \(title)"))
    print(b(separator("─")))
}

// MARK: - Dashboard

func renderDashboard(_ d: MobileDashboard, health: MobileHealth?) {
    printHeader("SYSTEM DASHBOARD")
    print("  \(r("🔒 LIVE TRADING: BLOCKED"))  \(dim("places_real_order=false"))")
    print("  Redis: \(d.redis_connected ? g("Connected") : r("Offline"))")
    if let h = health {
        let sc = h.overall == "healthy" ? g(h.overall) : h.overall == "degraded" ? y(h.overall) : r(h.overall)
        print("  System: \(sc)")
    }

    print("")
    print(b("  EXECUTION RUNTIME"))
    print("  ├─ Open positions : \(cy("\(d.paper.open_positions)"))")
    print("  ├─ Closed trades  : \(d.paper.closed_trades)")
    print("  ├─ Signals seen   : \(d.paper.signals_seen)")
    print("  ├─ Accepted       : \(g("\(d.paper.intents_accepted)"))")
    print("  ├─ Blocked        : \(r("\(d.paper.intents_blocked)"))")
    print("  ├─ Realized PnL   : \(pnlStr(d.paper.realized_pnl_usd))")
    print("  ├─ Unrealized PnL : \(pnlStr(d.paper.unrealized_pnl_usd))")
    print("  └─ Total PnL      : \(pnlStr(d.paper.total_pnl))")

    print("")
    print(b("  TRAINER"))
    let ts = d.trainer.isActive ? g(d.trainer.state) : y(d.trainer.state)
    print("  ├─ State        : \(ts)")
    print("  ├─ CUDA         : \(d.trainer.cuda_active ? g("Active") : r("Off"))")
    print("  ├─ Steps total  : \(d.trainer.training_steps_total)")
    print("  ├─ Steps/hr     : \(d.trainer.training_steps_last_hour)")
    print("  ├─ Coverage     : \(String(format: "%.1f%%", d.trainer.data_coverage))")
    let ckpt = d.trainer.checkpoint.isEmpty ? dim("none") : dim(String(d.trainer.checkpoint.prefix(20)) + "…")
    print("  └─ Checkpoint   : \(ckpt)")

    print("")
    print(b("  GPU  \(dim(d.gpu.name))"))
    let gpuColor  = d.gpu.utilization_pct > 90 ? C.yellow : C.blue
    let vramColor = d.gpu.vramPercent > 90 ? C.yellow : C.blue
    print("  ├─ Utilization  : \(bar(d.gpu.utilization_pct / 100, color: gpuColor)) \(String(format: "%.0f%%", d.gpu.utilization_pct))")
    print("  └─ VRAM         : \(bar(d.gpu.vramPercent / 100, color: vramColor)) \(String(format: "%.1f / %.1f GB", d.gpu.vramUsedGB, d.gpu.vramTotalGB))")

    if !d.alerts_preview.isEmpty {
        print("")
        print(b("  RECENT ALERTS"))
        for a in d.alerts_preview.prefix(3) {
            let sv = a.severity == "critical" ? r("[!]") : a.severity == "warning" ? y("[~]") : dim("[i]")
            print("  \(sv) [\(a.symbol)] \(a.type)  \(dim(a.message))")
        }
    }

    print("")
    print(dim("  Updated: \(d.generated_utc)"))
    print(b(separator("═")))
}

// MARK: - Positions

func renderPositions(_ resp: MobilePositionsResponse) {
    printHeader("EXECUTION POSITIONS")
    print("  Mode: \(cy("RUNTIME"))  |  Live gate: \(C.red)BLOCKED\(C.reset)")
    print("")

    let s = resp.summary
    print("  Total PnL   : \(pnlStr(s.total_pnl_usd))")
    print("  Realized    : \(pnlStr(s.realized_pnl_usd))")
    print("  Unrealized  : \(pnlStr(s.unrealized_pnl_usd))")
    print("  Open count  : \(cy("\(s.open_count)"))")
    print("")

    if resp.positions.isEmpty {
        print(dim("  No open positions."))
    } else {
        let hdr = String(format: "  %-12s %-6s %10s %12s %12s", "SYMBOL", "SIDE", "QTY", "ENTRY", "UNRL PnL")
        print(b(hdr))
        print("  " + separator("─", width: 56))
        for p in resp.positions {
            let sideStr = p.isBuy ? g(p.side.uppercased()) : C.red + p.side.uppercased() + C.reset
            let upnl    = pnlStr(p.unrealized_pnl)
            print(String(format: "  %-12s %-15s %10.4f %12.4f  %s",
                          p.symbol, sideStr, p.qty, p.entry_price, upnl))
        }
    }
    print("")
    print(b(separator("═")))
}

// MARK: - Signals

func renderSignals(_ resp: MobileSignalsResponse) {
    printHeader("SIGNALS  (\(resp.total_returned) rows)")
    print("")

    if resp.signals.isEmpty {
        print(dim("  No signals."))
    } else {
        let hdr = String(format: "  %-12s %-6s %-7s %8s  %-10s", "SYMBOL", "TF", "ACTION", "CONF", "ACTIONABLE")
        print(b(hdr))
        print("  " + separator("─", width: 56))
        for s in resp.signals {
            let act = s.action.lowercased().contains("buy") || s.action.lowercased().contains("long")
                      ? g(s.action.uppercased()) : C.red + s.action.uppercased() + C.reset
            let abl = s.actionable ? g("YES") : dim("no")
            print(String(format: "  %-12s %-6s %-16s %6.0f%%  %s",
                          s.symbol, s.timeframe, act, s.confidence * 100, abl))
        }
    }
    print("")
    print(b(separator("═")))
}

// MARK: - Alerts

func renderAlerts(_ resp: MobileAlertsResponse) {
    printHeader("ALERTS  (\(resp.total_returned))")
    print("")
    if resp.alerts.isEmpty {
        print(dim("  No alerts."))
    } else {
        for a in resp.alerts {
            let ic = a.severity == "critical" ? C.red + "●" + C.reset
                   : a.severity == "warning"  ? C.yellow + "●" + C.reset
                   : C.blue + "●" + C.reset
            print("  \(ic) [\(a.symbol)] \(b(a.type))  \(dim(String(a.triggered_at.prefix(10))))")
            print("     \(a.message)")
        }
    }
    print("")
    print(b(separator("═")))
}

// MARK: - Health

func renderHealth(_ h: MobileHealth) {
    printHeader("SYSTEM HEALTH")
    let sc = h.overall == "healthy" ? g(h.overall.uppercased()) : h.overall == "degraded" ? y(h.overall.uppercased()) : r(h.overall.uppercased())
    print("  Overall  : \(sc)")
    print("  Redis    : \(h.redis_connected ? g("Connected") : r("Offline"))")
    print("  Live gate: \(r("blocked_human_only"))")
    print("")
    print(b("  TRAINER"))
    print("  ├─ State    : \(h.trainer.training_active ? g(h.trainer.state) : y(h.trainer.state))")
    print("  ├─ CUDA     : \(h.trainer.cuda_active ? g("Active") : r("Off"))")
    let ckptLabel = h.trainer.checkpoint.isEmpty ? "none" : String(h.trainer.checkpoint.prefix(20)) + "…"
    print("  └─ Ckpt     : \(dim(ckptLabel))")
    print("")
    print(b("  GPU — \(h.gpu.name)"))
    let vramPct = h.gpu.vram_total_mb > 0 ? Double(h.gpu.vram_used_mb) / Double(h.gpu.vram_total_mb) : 0.0
    print("  ├─ Util : \(bar(h.gpu.utilization_pct / 100, color: h.gpu.utilization_pct > 90 ? C.yellow : C.blue)) \(String(format: "%.0f%%", h.gpu.utilization_pct))")
    print("  └─ VRAM : \(bar(vramPct, color: vramPct > 0.9 ? C.yellow : C.blue)) \(String(format: "%.1f / %.1f GB", Double(h.gpu.vram_used_mb)/1024, Double(h.gpu.vram_total_mb)/1024))")
    if h.gpu.temperature_c > 0 {
        let tempStr = h.gpu.temperature_c > 80 ? r(String(format: "%.0f°C", h.gpu.temperature_c)) : String(format: "%.0f°C", h.gpu.temperature_c)
        print("     Temp : \(tempStr)")
    }
    print("")
    print(b("  RUNTIME"))
    print("  ├─ Open positions : \(h.paper.open_positions)")
    print("  ├─ Accepted       : \(g("\(h.paper.intents_accepted)"))")
    print("  └─ Blocked        : \(r("\(h.paper.intents_blocked)"))")
    print("")
    print(b(separator("═")))
}

// MARK: - Execution Runtime

func renderPaper(_ s: MobilePaperSummary) {
    printHeader("EXECUTION RUNTIME SUMMARY")
    print("  Mode: \(cy("RUNTIME"))  |  Gate: \(r("BLOCKED"))")
    print("")
    print(b("  PnL"))
    print("  ├─ Total      : \(pnlStr(s.pnl.total_usd))")
    print("  ├─ Realized   : \(pnlStr(s.pnl.realized_usd))")
    print("  ├─ Unrealized : \(pnlStr(s.pnl.unrealized_usd))")
    if let wr = s.pnl.win_rate_pct {
        print("  └─ Win rate   : \(wr >= 50 ? g(String(format: "%.1f%%", wr)) : y(String(format: "%.1f%%", wr)))")
    }
    print("")
    print(b("  LOOP"))
    print("  ├─ Signals seen   : \(s.loop.signals_seen)")
    print("  ├─ Intents built  : \(s.loop.intents_built)")
    print("  ├─ Accepted       : \(g("\(s.loop.intents_accepted)"))")
    print("  ├─ Blocked        : \(r("\(s.loop.intents_blocked)"))")
    print("  └─ Classification : \(dim(s.loop.classification))")
    print("")
    print(b("  POSITIONS"))
    print("  ├─ Open   : \(s.positions.open_count)")
    print("  └─ Closed : \(s.positions.closed_count)")
    print("")
    print(b("  TRAINER FEEDBACK"))
    print("  ├─ Outcome labels : \(s.trainer_feedback.outcome_labels)")
    print("  ├─ Consumable     : \(s.trainer_feedback.consumable_rows)")
    print("  └─ Quarantined    : \(s.trainer_feedback.quarantined_rows > 0 ? r("\(s.trainer_feedback.quarantined_rows)") : "0")")
    print("")
    print(b(separator("═")))
}

// MARK: - Risk

func renderRisk(_ risk: MobileRiskStatus) {
    printHeader("RISK STATUS")
    print("  \(r("🔒 LIVE TRADING BLOCKED"))")
    print("  Kill switch : \(risk.kill_switch_active ? r("ACTIVE") : g("Inactive"))")
    print("  Risk state  : \(risk.risk_state)")
    print("")
    print(b("  LIMITS"))
    print("  ├─ Max position  : \(risk.max_position_size_usd > 0 ? "$\(Int(risk.max_position_size_usd))" : dim("N/A"))")
    print("  ├─ Daily loss    : \(risk.daily_loss_limit_usd > 0 ? "$\(Int(risk.daily_loss_limit_usd))" : dim("N/A"))")
    print("  └─ Current loss  : \(pnlStr(-risk.current_daily_loss_usd))")
    print("")
    print(b("  EXECUTION GATE"))
    print("  ├─ Accepted : \(g("\(risk.paper_accepted_count)"))")
    print("  └─ Blocked  : \(r("\(risk.paper_blocked_count)"))")
    print("")
    print(y("  ⚠ Dangerous controls require web admin approval. Mobile cannot approve."))
    print(b(separator("═")))
}

// MARK: - Admin

func renderAdmin(_ a: MobileAdminSummary) {
    printHeader("ADMIN SUMMARY")
    print("  Actor : \(b(a.actor.email))  [\(cy(a.actor.role))]")
    print("  \(r("🔒 LIVE TRADING BLOCKED"))")
    print("")
    print(b("  TRAINER"))
    let ts = a.trainer.state.hasPrefix("ACTIVE") ? g(a.trainer.state) : y(a.trainer.state)
    print("  ├─ State    : \(ts)")
    print("  ├─ CUDA     : \(a.trainer.cuda_active ? g("Active") : r("Off"))")
    print("  ├─ Steps/hr : \(a.trainer.training_steps_last_hour)")
    print("  └─ Total    : \(a.trainer.training_steps_total)")
    print("")
    print(b("  GPU — \(a.gpu.name)"))
    print("  ├─ Utilization : \(bar(a.gpu.utilization_pct/100)) \(String(format: "%.0f%%", a.gpu.utilization_pct))")
    print("  └─ VRAM        : \(bar(a.gpu.vramPercent/100)) \(String(format: "%.1f/%.1f GB", a.gpu.vramUsedGB, a.gpu.vramTotalGB))")
    print("")
    print(b("  RUNTIME"))
    print("  ├─ Open / Closed : \(a.paper.open_positions) / \(a.paper.closed_trades)")
    print("  ├─ Realized PnL  : \(pnlStr(a.paper.realized_pnl_usd))")
    print("  └─ Unrealized    : \(pnlStr(a.paper.unrealized_pnl_usd))")
    print("")
    print(b("  RISK"))
    print("  ├─ State        : \(a.risk.state)")
    print("  └─ Kill switch  : \(a.risk.kill_switch_active ? r("ACTIVE") : g("Inactive"))")
    print("")
    print(r("  ⚠  Dangerous controls require web admin approval."))
    print(b(separator("═")))
}

// MARK: - Interactive login

func interactiveLogin(auth: AuthManager, baseURL: String) async {
    print("Server: \(cy(baseURL))")
    print("Email: ", terminator: "")
    guard let email = readLine(strippingNewline: true), !email.isEmpty else {
        print(r("No email entered.")); return
    }
    print("Password: ", terminator: "")
    fflush(stdout)
    runStty("-echo")
    let password = readLine(strippingNewline: true) ?? ""
    runStty("echo")
    print("")

    guard !password.isEmpty else { print(r("No password entered.")); return }

    print(dim("Signing in…"))
    if let session = await auth.login(email: email, password: password, baseURL: baseURL) {
        print(g("✓ Signed in as \(session.email) [\(session.role)]"))
        print(dim("  Credentials saved to ~/.config/aibot/credentials.json"))
    } else {
        if case .error(let msg) = auth.state { print(r("✗ Login failed: \(msg)")) }
    }
}

// MARK: - Entry point

let cliArgs = CommandLine.arguments.dropFirst()
var command        = "status"
var serverOverride: String? = nil
var tokenOverride:  String? = nil
var limitArg  = 20
var interval  = 10

var argIt = cliArgs.makeIterator()
while let arg = argIt.next() {
    switch arg {
    case "--server":   serverOverride = argIt.next()
    case "--token":    tokenOverride  = argIt.next()
    case "--limit":    limitArg  = Int(argIt.next() ?? "20") ?? 20
    case "--interval": interval  = Int(argIt.next() ?? "10") ?? 10
    case "--help", "-h": printHelp(); exit(0)
    default:
        if !arg.hasPrefix("-") { command = arg }
    }
}

// Use DispatchSemaphore so we can block the main thread until the async task finishes.
let doneSema = DispatchSemaphore(value: 0)

Task {
    let store   = TokenStore.shared
    let auth    = AuthManager()
    let baseURL = serverOverride ?? AppConfig.baseURL
    let token   = tokenOverride  ?? store.loadToken()

    defer { doneSema.signal() }

    switch command {

    case "login":
        await interactiveLogin(auth: auth, baseURL: baseURL)

    case "logout":
        await auth.logout(baseURL: baseURL)
        print(g("Signed out."))

    case "config":
        if let s = serverOverride {
            AppConfig.baseURL = s
            print(g("Server URL saved: \(s)"))
        } else {
            print("Server URL : \(cy(AppConfig.baseURL))")
            print("Token      : \(token != nil ? g("Saved") : r("Not saved — run: aibot login"))")
        }

    case "status", "dashboard":
        if token == nil { print(y("Tip: run 'aibot login' to save credentials.")) }
        print(dim("Fetching dashboard…"))
        do {
            async let d: MobileDashboard = APIClient.shared.get(
                path: APIEndpoints.mobileDashboard, token: token, baseURL: baseURL)
            async let h: MobileHealth = APIClient.shared.get(
                path: APIEndpoints.mobileHealth, token: token, baseURL: baseURL)
            let (dash, health) = try await (d, h)
            renderDashboard(dash, health: health)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "positions":
        guard token != nil else { print(r("Requires authentication. Run: aibot login")); return }
        print(dim("Fetching positions…"))
        do {
            let resp: MobilePositionsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobilePositions, token: token, baseURL: baseURL)
            renderPositions(resp)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "signals":
        guard token != nil else { print(r("Requires authentication. Run: aibot login")); return }
        print(dim("Fetching signals…"))
        do {
            let resp: MobileSignalsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobileSignals,
                queryItems: [URLQueryItem(name: "limit", value: "\(limitArg)")],
                token: token, baseURL: baseURL)
            renderSignals(resp)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "alerts":
        guard token != nil else { print(r("Requires authentication. Run: aibot login")); return }
        print(dim("Fetching alerts…"))
        do {
            let resp: MobileAlertsResponse = try await APIClient.shared.get(
                path: APIEndpoints.mobileAlerts,
                queryItems: [URLQueryItem(name: "limit", value: "\(limitArg)")],
                token: token, baseURL: baseURL)
            renderAlerts(resp)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "health":
        print(dim("Checking health…"))
        do {
            let h: MobileHealth = try await APIClient.shared.get(
                path: APIEndpoints.mobileHealth, token: token, baseURL: baseURL)
            renderHealth(h)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "execute", "paper":
        guard token != nil else { print(r("Requires authentication. Run: aibot login")); return }
        print(dim("Fetching execution summary…"))
        do {
            let s: MobilePaperSummary = try await APIClient.shared.get(
                path: APIEndpoints.mobilePaperSummary, token: token, baseURL: baseURL)
            renderPaper(s)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "risk":
        guard token != nil else { print(r("Requires authentication. Run: aibot login")); return }
        print(dim("Fetching risk status…"))
        do {
            let rs: MobileRiskStatus = try await APIClient.shared.get(
                path: APIEndpoints.mobileRiskStatus, token: token, baseURL: baseURL)
            renderRisk(rs)
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "admin":
        guard token != nil else { print(r("Admin requires authentication. Run: aibot login")); return }
        print(dim("Fetching admin summary…"))
        do {
            let a: MobileAdminSummary = try await APIClient.shared.get(
                path: APIEndpoints.mobileAdminSummary, token: token, baseURL: baseURL)
            renderAdmin(a)
        } catch let err as APIError where err.isUnauthorized {
            print(r("Admin role required."))
        } catch { print(r("Error: \(error.localizedDescription)")) }

    case "watch":
        print(b("  NERVYX ONE  ·  LIVE WATCH  (Ctrl+C to stop, refresh: \(interval)s)"))
        // watch loops forever — semaphore never fires, Ctrl+C exits
        while true {
            print("\u{001B}[2J\u{001B}[H", terminator: "")
            do {
                async let d: MobileDashboard = APIClient.shared.get(
                    path: APIEndpoints.mobileDashboard, token: token, baseURL: baseURL)
                async let h: MobileHealth = APIClient.shared.get(
                    path: APIEndpoints.mobileHealth, token: token, baseURL: baseURL)
                let (dash, health) = try await (d, h)
                renderDashboard(dash, health: health)
                print(dim("  Next refresh in \(interval)s · Ctrl+C to exit"))
            } catch {
                print(r("  Fetch error: \(error.localizedDescription)"))
            }
            try? await Task.sleep(nanoseconds: UInt64(interval) * 1_000_000_000)
        }

    default:
        print(r("Unknown command: \(command)"))
        printHelp()
        exit(1)
    }
}

doneSema.wait()
