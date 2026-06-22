import XCTest
@testable import AIBotV2Core

final class AIBotV2CoreTests: XCTestCase {

    func testAPIEndpointsNotEmpty() {
        XCTAssertFalse(APIEndpoints.mobileDashboard.isEmpty)
        XCTAssertTrue(APIEndpoints.mobileDashboard.hasPrefix("/"))
    }

    func testAPIErrorMessages() {
        XCTAssertTrue(APIError.unauthorized.isUnauthorized)
        XCTAssertTrue(APIError.http(statusCode: 401, message: "").isUnauthorized)
        XCTAssertFalse(APIError.http(statusCode: 403, message: "").isUnauthorized)
    }

    func testTokenStoreRoundTrip() {
        let store = TokenStore()
        store.saveToken("test_token_123")
        XCTAssertEqual(store.loadToken(), "test_token_123")
        store.deleteToken()
        XCTAssertNil(store.loadToken())
    }

    func testAppConfigBaseURL() {
        let original = AppConfig.baseURL
        AppConfig.baseURL = "http://192.168.1.1:5173"
        XCTAssertEqual(AppConfig.baseURL, "http://192.168.1.1:5173")
        AppConfig.baseURL = original
    }

    func testMobileDashboardDecoding() throws {
        let json = """
        {
          "generated_utc": "2026-06-18T00:00:00Z",
          "live_gate": { "live_trading_enabled": false, "places_real_order": false,
                         "gate": "blocked_human_only", "label": "BLOCKED" },
          "paper": { "open_positions": 2, "closed_trades": 10,
                     "realized_pnl_usd": 50.0, "unrealized_pnl_usd": 25.0,
                     "signals_seen": 100, "intents_accepted": 8, "intents_blocked": 5,
                     "classification": "PAPER_OK", "places_real_order": false },
          "trainer": { "state": "ACTIVE", "checkpoint": "ckpt_v1",
                       "model_source": "local", "cuda_active": true,
                       "data_coverage": 87.5, "training_steps_total": 50000,
                       "training_steps_last_hour": 1200 },
          "gpu": { "name": "RTX 3090", "utilization_pct": 72.0,
                   "vram_used_mb": 8192, "vram_total_mb": 24576 },
          "alerts_preview": [],
          "redis_connected": true
        }
        """.data(using: .utf8)!
        let d = try JSONDecoder().decode(MobileDashboard.self, from: json)
        XCTAssertEqual(d.paper.open_positions, 2)
        XCTAssertEqual(d.paper.total_pnl, 75.0, accuracy: 0.01)
        XCTAssertFalse(d.live_gate.places_real_order)
        XCTAssertTrue(d.trainer.isActive)
        XCTAssertEqual(d.gpu.vramPercent, 100.0 / 3.0, accuracy: 0.1)
    }

    func testMobilePositionIsBuy() {
        let pos = MobilePosition(id: "1", symbol: "BTC", side: "LONG",
                                  qty: 0.1, entry_price: 60000, mark_price: 61000,
                                  unrealized_pnl: 100, realized_pnl: 0,
                                  opened_at: "2026-06-18T00:00:00Z", status: "open")
        XCTAssertTrue(pos.isBuy)
    }

    func testIOSViewModelsUseResourceWebSocketStreams() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let sourceRoot = packageRoot.appendingPathComponent("Sources/AIBotV2")
        let expectations: [String: [String]] = [
            "ViewModels/DashboardViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobileDashboard",
                "APIEndpoints.mobileHealth",
                "decodeMobileResourceMessage",
                "WatchSyncCenter.shared.updateDashboard",
                "fallbackTask",
                "!dashboardStreamIsConnected || !healthStreamIsConnected",
            ],
            "ViewModels/PositionsViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobilePositions",
                "decodeMobileResourceMessage",
                "WatchSyncCenter.shared.updatePositions",
            ],
            "ViewModels/SignalsViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobileSignals",
                "decodeMobileResourceMessage",
            ],
            "ViewModels/AlertsViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobileAlerts",
                "decodeMobileResourceMessage",
                "WatchSyncCenter.shared.updateAlerts",
            ],
            "ViewModels/PaperViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobilePaperSummary",
                "decodeMobileResourceMessage",
            ],
            "ViewModels/AdminViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobileAdminSummary",
                "APIEndpoints.mobileRiskStatus",
                "decodeMobileResourceMessage",
            ],
        ]

        for (relativePath, requiredSnippets) in expectations {
            let url = sourceRoot.appendingPathComponent(relativePath)
            let text = try String(contentsOf: url, encoding: .utf8)
            for snippet in requiredSnippets {
                XCTAssertTrue(
                    text.contains(snippet),
                    "\(relativePath) must contain \(snippet) so the iPhone app stays on resource WebSocket streams"
                )
            }
        }
    }

    func testIOSResourceWebSocketUsesVersionedBackendRoute() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let endpointsURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Networking/APIEndpoints.swift")
        let text = try String(contentsOf: endpointsURL, encoding: .utf8)

        XCTAssertTrue(
            text.contains("public static let wsResource = \"/api/v2/ws/resource\""),
            "iPhone resource streams must use the same versioned WebSocket route as the website"
        )
        XCTAssertTrue(
            text.contains("URLQueryItem(name: \"path\", value: target.string ?? path)"),
            "iPhone resource streams must preserve the API path and query string inside the WebSocket resource wrapper"
        )
    }

    func testIOSWatchCompanionReceivesLiveResourceState() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let watchSyncURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Watch/WatchSyncCenter.swift")
        let watchAppURL = packageRoot.appendingPathComponent("Sources/AIBotV2Watch/App/WatchApp.swift")
        let watchSyncText = try String(contentsOf: watchSyncURL, encoding: .utf8)
        let watchAppText = try String(contentsOf: watchAppURL, encoding: .utf8)

        for snippet in [
            "WCSession.default",
            "sendMessage(payload",
            "updateApplicationContext(payload)",
            "didReceiveApplicationContext",
            "sessionReachabilityDidChange",
            "\"dashboard\"",
            "\"positions\"",
            "\"alerts\"",
            "\"action\"",
            "\"refresh\"",
        ] {
            XCTAssertTrue(
                watchSyncText.contains(snippet),
                "WatchSyncCenter.swift must include \(snippet) so watchOS gets live iPhone WebSocket state"
            )
        }
        XCTAssertTrue(
            watchAppText.contains("WatchConnectivityManager.shared.sendMessage([\"action\": \"refresh\"])"),
            "Watch app must request fresh state from the iPhone companion"
        )
    }

    func testIOSVisibleCopyDoesNotExposePaperOrSimulatedStates() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let sourceRoot = packageRoot.appendingPathComponent("Sources/AIBotV2")
        let visibleRoots = [
            sourceRoot.appendingPathComponent("Views"),
            sourceRoot.appendingPathComponent("Models"),
            packageRoot.appendingPathComponent("Sources/AIBotV2Watch/Views"),
        ]
        let forbidden = [
            "Paper only",
            "PAPER ONLY",
            "Paper mode",
            "Paper account",
            "Paper Fill Blocked",
            "Live trading platform",
            "simulated",
            "Simulated",
            "NO DATA",
            "DATA UNAVAILABLE",
            "Loading paper",
        ]

        for root in visibleRoots {
            let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)
            while let fileURL = enumerator?.nextObject() as? URL {
                guard fileURL.pathExtension == "swift" else { continue }
                let text = try String(contentsOf: fileURL, encoding: .utf8)
                for literal in swiftStringLiterals(in: text) {
                    for needle in forbidden {
                        XCTAssertFalse(
                            literal.contains(needle),
                            "\(fileURL.lastPathComponent) visible string literal exposes \(needle): \(literal)"
                        )
                    }
                }
            }
        }
    }

    private func swiftStringLiterals(in text: String) -> [String] {
        let pattern = #""(?:\\.|[^"\\])*""#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        return regex.matches(in: text, range: range).compactMap { match in
            guard let swiftRange = Range(match.range, in: text) else { return nil }
            return String(text[swiftRange])
        }
    }
}
