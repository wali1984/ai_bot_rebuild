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
}
