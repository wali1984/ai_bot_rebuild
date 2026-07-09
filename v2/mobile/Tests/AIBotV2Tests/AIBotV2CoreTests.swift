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
                                  qty: 0.1, entry_price: 60000,
                                  entry_price_source: "avg_entry_price",
                                  exit_price: nil, exit_price_source: nil,
                                  mark_price: 61000,
                                  mark_price_source: "unit", mark_price_generated_at: nil,
                                  mark_price_age_seconds: 1, mark_price_stale: false,
                                  unrealized_pnl: 100, realized_pnl: 0,
                                  opened_at: "2026-06-18T00:00:00Z",
                                  closed_at: nil, close_reason: nil,
                                  status: "open",
                                  signal_id: "sig-1", prediction_id: "pred-1",
                                  decision_reasoning: nil,
                                  account_scope: "PAPER_SIM_ACCOUNT",
                                  source_type: "unit_test",
                                  paper_or_live: "paper",
                                  contains_simulated_positions: true,
                                  contains_live_positions: false,
                                  contains_quarantined_positions: false,
                                  equity_trusted: true,
                                  pnl_trusted: true,
                                  reason_if_untrusted: nil,
                                  routes_to_live: false)
        XCTAssertTrue(pos.isBuy)
    }

    func testMobilePositionsDecodeOpenClosedHistoryAndReasoning() throws {
        let json = """
        {
          "generated_utc": "2026-06-18T00:00:00Z",
          "positions": [{
            "id": "open-1",
            "symbol": "BTCUSDT",
            "side": "LONG",
            "qty": 0.01,
            "entry_price": 60000.0,
            "entry_price_source": "avg_entry_price",
            "mark_price": 62000.0,
            "mark_price_source": "v2:market:coinapi:wsds:BTCUSDT.mid_px",
            "mark_price_generated_at": "2026-06-18T00:00:01Z",
            "mark_price_age_seconds": 1.5,
            "mark_price_stale": false,
            "unrealized_pnl": 20.0,
            "realized_pnl": 0.0,
            "opened_at": "2026-06-18T00:00:00Z",
            "status": "open",
            "signal_id": "sig-open",
            "prediction_id": "pred-open",
            "decision_reasoning": {
              "source": "v2:signals:latest:BTCUSDT",
              "signal_id": "sig-open",
              "prediction_id": "pred-open",
              "action": "LONG",
              "confidence": 0.81,
              "reason": "fresh_features_positive_edge"
            }
          }],
          "closed_positions": [{
            "id": "closed-1",
            "symbol": "ETHUSDT",
            "side": "SHORT",
            "qty": 0.5,
            "entry_price": 2500.0,
            "entry_price_source": "entry_price",
            "exit_price": 2400.0,
            "exit_price_source": "paper_exit_price",
            "unrealized_pnl": null,
            "realized_pnl": 50.0,
            "opened_at": "2026-06-17T00:00:00Z",
            "closed_at": "2026-06-18T00:00:00Z",
            "close_reason": "TIER_2_TAKE_PROFIT",
            "status": "closed",
            "signal_id": "sig-close",
            "prediction_id": "pred-close",
            "decision_reasoning": {
              "source": "v2:paper:closed_trades",
              "signal_id": "sig-close",
              "prediction_id": "pred-close",
              "action": "SHORT",
              "confidence": 0.74,
              "reason": "TIER_2_TAKE_PROFIT"
            }
          }],
          "historical_positions": [],
          "position_pricing": {
            "unrealized_pnl_usd": 20.0,
            "total_open_notional": 620.0,
            "mark_to_market_live": true,
            "live_mark_price_count": 1,
            "stale_mark_price_count": 0,
            "missing_mark_price_count": 0
          },
          "warnings": [],
          "summary": {
            "open_count": 1,
            "closed_count": 1,
            "total_pnl_usd": 70.0,
            "realized_pnl_usd": 50.0,
            "unrealized_pnl_usd": 20.0
          },
          "mode": "paper",
          "live_gate": "blocked_human_only",
          "places_real_order": false
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(MobilePositionsResponse.self, from: json)
        XCTAssertEqual(response.positions.first?.mark_price, 62000.0)
        XCTAssertEqual(response.positions.first?.mark_price_stale, false)
        XCTAssertEqual(response.positions.first?.decision_reasoning?.reason, "fresh_features_positive_edge")
        XCTAssertEqual(response.closed_positions?.first?.exit_price, 2400.0)
        XCTAssertEqual(response.closed_positions?.first?.exit_price_source, "paper_exit_price")
        XCTAssertEqual(response.closed_positions?.first?.decision_reasoning?.signal_id, "sig-close")
        XCTAssertEqual(response.summary.closed_count, 1)
        XCTAssertEqual(response.position_pricing?.live_mark_price_count, 1)
    }

    func testMobilePaperSummaryDecodesPositionPricingAndReasoningPreview() throws {
        let json = """
        {
          "generated_utc": "2026-06-18T00:00:00Z",
          "mode": "paper",
          "places_real_order": false,
          "live_gate": "blocked_human_only",
          "loop": {
            "signals_seen": 4,
            "intents_built": 2,
            "intents_accepted": 1,
            "intents_blocked": 1,
            "classification": "RUNNING",
            "cycle_state": "COMPLETED_CYCLE",
            "heartbeat_ttl_seconds": 3600,
            "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
            "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
            "paper_policy_owner": "challenger_v2",
            "policy_fingerprint": "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630",
            "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
            "paper_only": true,
            "routes_to_live": false,
            "places_real_order": false
          },
          "positions": {
            "open_count": 1,
            "closed_count": 3,
            "positions_preview": [{
              "id": "pos-btc",
              "symbol": "BTCUSDT",
              "side": "LONG",
              "qty": 0.01,
              "entry_price": 60000.0,
              "entry_price_source": "avg_entry_price",
              "mark_price": 62000.0,
              "mark_price_source": "v2:market:coinapi:wsds:BTCUSDT.mid_px",
              "mark_price_generated_at": "2026-06-18T00:00:01Z",
              "mark_price_age_seconds": 1.5,
              "mark_price_stale": false,
              "unrealized_pnl": 20.0,
              "realized_pnl": 0.0,
              "opened_at": "2026-06-18T00:00:00Z",
              "status": "open",
              "signal_id": "sig-BTC",
              "prediction_id": "pred-BTC",
              "decision_reasoning": {
                "source": "v2:signals:latest:BTCUSDT",
                "signal_id": "sig-BTC",
                "prediction_id": "pred-BTC",
                "action": "LONG",
                "confidence": 0.81,
                "reason": "fresh_features_positive_edge"
              }
            }]
          },
          "position_pricing": {
            "unrealized_pnl_usd": 20.0,
            "total_open_notional": 620.0,
            "mark_to_market_live": true,
            "live_mark_price_count": 1,
            "stale_mark_price_count": 0,
            "missing_mark_price_count": 0
          },
          "pnl": {
            "realized_usd": 12.5,
            "unrealized_usd": 20.0,
            "total_usd": 32.5,
            "win_rate_pct": 66.7
          },
          "provider_readiness": {
            "moralis_status": "CONFIGURED_NO_WATCHLIST",
            "moralis_dashboard_color": "GRAY",
            "moralis_actual_payload_present": false,
            "moralis_heartbeat_only": true,
            "moralis_feature_bridge_ready": false,
            "moralis_feature_count": 0,
            "moralis_required_feature_count": 15,
            "moralis_missing_feature_flags": ["moralis_whale_buy_usd"],
            "moralis_stale_feature_flags": [],
            "moralis_missing_mask_true": true,
            "moralis_stale_mask_true": false,
            "moralis_token_map_count": 9,
            "moralis_wallet_watchlist_count": 0,
            "heartbeat_only_green_allowed": false
          },
          "trainer_feedback": {
            "outcome_labels": 3,
            "consumable_rows": 2,
            "quarantined_rows": 1
          }
        }
        """.data(using: .utf8)!

        let summary = try JSONDecoder().decode(MobilePaperSummary.self, from: json)
        XCTAssertEqual(summary.position_pricing?.live_mark_price_count, 1)
        XCTAssertEqual(summary.position_pricing?.missing_mark_price_count, 0)
        XCTAssertEqual(summary.positions.positions_preview.first?.mark_price, 62000.0)
        XCTAssertEqual(summary.positions.positions_preview.first?.decision_reasoning?.reason, "fresh_features_positive_edge")
        XCTAssertEqual(summary.pnl.unrealized_usd, 20.0)
        XCTAssertEqual(summary.loop.cycle_state, "COMPLETED_CYCLE")
        XCTAssertEqual(summary.loop.heartbeat_ttl_seconds, 3600)
        XCTAssertEqual(summary.loop.candidate_id, "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e")
        XCTAssertEqual(summary.loop.policy_id, "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e")
        XCTAssertEqual(summary.loop.paper_policy_owner, "challenger_v2")
        XCTAssertEqual(summary.loop.policy_fingerprint, "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630")
        XCTAssertEqual(summary.loop.model_source, "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA")
        XCTAssertEqual(summary.loop.paper_only, true)
        XCTAssertEqual(summary.loop.routes_to_live, false)
        XCTAssertEqual(summary.loop.places_real_order, false)
        XCTAssertEqual(summary.provider_readiness?.moralis_feature_bridge_ready, false)
        XCTAssertEqual(summary.provider_readiness?.moralis_feature_count, 0)
        XCTAssertEqual(summary.provider_readiness?.moralis_required_feature_count, 15)
        XCTAssertEqual(summary.provider_readiness?.moralis_missing_feature_flags?.first, "moralis_whale_buy_usd")
        XCTAssertEqual(summary.provider_readiness?.moralis_missing_mask_true, true)
        XCTAssertEqual(summary.provider_readiness?.moralis_wallet_watchlist_count, 0)
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
                "decodeMobileResourceSnapshot",
                "sourceType = snapshot.sourceType",
                "lastUpdatedAt = snapshot.timestamp",
                "missingFields = snapshot.missingFields",
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
                "decodeMobileResourceSnapshot",
                "sourceType = snapshot.sourceType",
                "lastUpdatedAt = snapshot.timestamp",
                "missingFields = snapshot.missingFields",
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

    func testIOSResourceStreamsExposeAsyncAndEnvelopeMetadata() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let sourceRoot = packageRoot.appendingPathComponent("Sources/AIBotV2")
        let socket = try String(
            contentsOf: sourceRoot.appendingPathComponent("Networking/WebSocketClient.swift"),
            encoding: .utf8
        )
        let stream = try String(
            contentsOf: sourceRoot.appendingPathComponent("Networking/MobileResourceStream.swift"),
            encoding: .utf8
        )
        let positionsVM = try String(
            contentsOf: sourceRoot.appendingPathComponent("ViewModels/PositionsViewModel.swift"),
            encoding: .utf8
        )
        let paperVM = try String(
            contentsOf: sourceRoot.appendingPathComponent("ViewModels/PaperViewModel.swift"),
            encoding: .utf8
        )
        let positionsView = try String(
            contentsOf: sourceRoot.appendingPathComponent("Views/Positions/PositionsView.swift"),
            encoding: .utf8
        )
        let paperView = try String(
            contentsOf: sourceRoot.appendingPathComponent("Views/Paper/PaperTradingView.swift"),
            encoding: .utf8
        )

        for snippet in [
            "AsyncThrowingStream<String, Error>",
            "try await task.receive()",
            "continuation.onTermination",
        ] {
            XCTAssertTrue(socket.contains(snippet), "WebSocketClient must expose async/await stream support: \(snippet)")
        }

        for snippet in [
            "struct MobileResourceSnapshot<T>",
            "let sourceType: String?",
            "let missingFields: [String]",
            "let warnings: [String]",
            "func decodeMobileResourceSnapshot",
            "decodeMobileResourceMessage",
        ] {
            XCTAssertTrue(stream.contains(snippet), "Mobile resource stream decoder must preserve envelope metadata: \(snippet)")
        }

        for text in [positionsVM, paperVM] {
            for snippet in [
                "public private(set) var sourceType: String?",
                "public private(set) var lastUpdatedAt: String?",
                "public private(set) var isStale = false",
                "public private(set) var streamWarnings: [String] = []",
                "public private(set) var missingFields: [String] = []",
                "sourceType = \"api\"",
                "decodeMobileResourceSnapshot",
            ] {
                XCTAssertTrue(text.contains(snippet), "Mobile view models must preserve stream freshness metadata: \(snippet)")
            }
        }

        for snippet in [
            "private var streamStatusCard: some View",
            "positionStreamStatusText",
            "Position stream",
            "missingFields: vm.missingFields",
            "warnings: vm.streamWarnings",
        ] {
            XCTAssertTrue(positionsView.contains(snippet), "Positions view must render stream metadata: \(snippet)")
        }

        for snippet in [
            "private var streamStatusCard: some View",
            "executionStreamStatusText",
            "Execution stream",
            "missingFields: vm.missingFields",
            "warnings: vm.streamWarnings",
        ] {
            XCTAssertTrue(paperView.contains(snippet), "Execution view must render stream metadata: \(snippet)")
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

    func testEnterpriseRealtimeEndpointsAndModelsDecode() throws {
        XCTAssertEqual(APIEndpoints.realtimeBootstrap, "/api/v2/realtime/bootstrap")
        XCTAssertEqual(APIEndpoints.realtimeResources, "/api/v2/realtime/resources")
        XCTAssertEqual(APIEndpoints.realtimeHealth, "/api/v2/realtime/health")
        XCTAssertEqual(APIEndpoints.wsRealtime, "/api/v2/realtime/ws")
        XCTAssertTrue(
            APIEndpoints.wsRealtimeURL(baseURL: "https://dashboard.example", resources: ["dashboard", "providers"])?
                .contains("/api/v2/realtime/ws") == true
        )

        let bootstrapJSON = """
        {
          "schema_version": "enterprise_realtime_bootstrap_v1",
          "generated_utc": "2026-07-09T00:00:00Z",
          "display_time_et": "2026-07-08T20:00:00-04:00",
          "display_timezone": "America/New_York",
          "source": "redis_materialized_or_compact_fallback",
          "auth": {"required_for_controls": true},
          "portfolio": {"schema_version": "canonical_pnl_v1"},
          "paper": {},
          "risk": {},
          "trainer": {},
          "signals": {},
          "providers": {},
          "ingestors": {},
          "markets": {},
          "live_canary": {},
          "alerts": {},
          "ui_hints": {"default_pnl_display": "usd_and_percent"},
          "resources": {
            "portfolio": {
              "schema_version": "enterprise_ui_snapshot_v1",
              "resource": "portfolio",
              "generated_utc": "2026-07-09T00:00:00Z",
              "display_time_et": "2026-07-08T20:00:00-04:00",
              "source_timezone": "UTC",
              "display_timezone": "America/New_York",
              "source": "v2:ui:snapshot:portfolio",
              "source_type": "redis_materialized",
              "source_keys": ["v2:ui:snapshot:portfolio"],
              "staleness_seconds": 1.0,
              "data_quality": "valid",
              "missing_sections": [],
              "error_sections": [],
              "last_good_payload_used": false,
              "payload": {"schema_version": "canonical_pnl_v1", "equity_usd": 3000.68},
              "live_gate": "blocked_human_only",
              "paper_only": true,
              "routes_to_live": false,
              "places_real_order": false
            }
          },
          "live_gate": "blocked_human_only",
          "paper_only": true,
          "routes_to_live": false,
          "places_real_order": false
        }
        """.data(using: .utf8)!
        let bootstrap = try JSONDecoder().decode(EnterpriseRealtimeBootstrap.self, from: bootstrapJSON)
        XCTAssertEqual(bootstrap.schema_version, "enterprise_realtime_bootstrap_v1")
        XCTAssertEqual(bootstrap.resources["portfolio"]?.resource, "portfolio")
        XCTAssertFalse(bootstrap.routes_to_live)
        XCTAssertFalse(bootstrap.places_real_order)

        let pnlJSON = """
        {
          "schema_version": "canonical_pnl_v1",
          "generated_utc": "2026-07-09T00:00:00Z",
          "display_time_et": "2026-07-08T20:00:00-04:00",
          "source_timezone": "UTC",
          "display_timezone": "America/New_York",
          "paper_session_id": "session-a",
          "account_scope": "paper",
          "equity_usd": 3000.68,
          "starting_equity_usd": 3000.0,
          "realized_net_pnl_usd": 0.68,
          "unrealized_pnl_usd": 0.0,
          "fees_usd": 0.0,
          "slippage_usd": 0.0,
          "funding_usd": 0.0,
          "gross_pnl_usd": 0.68,
          "net_pnl_usd": 0.68,
          "closed_trade_count": 1,
          "source": "v2:portfolio:state",
          "source_lag_seconds": 1.0,
          "reconciliation_status": "PASS",
          "reconciliation_delta_usd": 0.0,
          "missing_fields": [],
          "warnings": [],
          "paper_only": true,
          "routes_to_live": false,
          "places_real_order": false
        }
        """.data(using: .utf8)!
        let pnl = try JSONDecoder().decode(CanonicalPnL.self, from: pnlJSON)
        XCTAssertEqual(pnl.equity_usd, 3000.68)
        XCTAssertEqual(pnl.reconciliation_status, "PASS")
        XCTAssertFalse(pnl.places_real_order)

        let providersJSON = """
        {
          "schema_version": "enterprise_provider_cards_v1",
          "providers": [
            {
              "provider": "coinglass",
              "display_name": "CoinGlass",
              "status": "PARTIAL",
              "dashboard_color": "yellow",
              "dashboard_color_reason": "feature_bridge_partial",
              "actual_payload_count": 3,
              "keys_published": ["v2:provider:coinglass:health"],
              "feature_count": 10,
              "consumer_count": 4,
              "heartbeat_only": false,
              "actual_payload_present": true,
              "raw_key_exposed": false,
              "routes_to_live": false,
              "places_real_order": false
            }
          ],
          "provider_count": 1,
          "heartbeat_only_green_count": 0,
          "live_gate": "blocked_human_only",
          "paper_only": true,
          "routes_to_live": false,
          "places_real_order": false
        }
        """.data(using: .utf8)!
        let providers = try JSONDecoder().decode(EnterpriseProviderCards.self, from: providersJSON)
        XCTAssertEqual(providers.providers.first?.provider, "coinglass")
        XCTAssertEqual(providers.providers.first?.dashboard_color, "yellow")
        XCTAssertFalse(providers.providers.first?.raw_key_exposed ?? true)
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

    func testNervyxGeneratedThemeManifestCarriesRoleGatedThemeParity() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let manifestURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Brand/Generated/NervyxThemeManifest.swift")
        let brandURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Brand/NervyxBrand.swift")
        let manifest = try String(contentsOf: manifestURL, encoding: .utf8)
        let brand = try String(contentsOf: brandURL, encoding: .utf8)

        for snippet in [
            "public static let themes: [String: [String: String]]",
            "\"midnightNeural\": [",
            "\"polarSignal\": [",
            "\"opsTerminal\": [",
            "\"midnightNeural\": [\"public\", \"trader\"]",
            "\"polarSignal\": [\"public\", \"trader\"]",
            "\"opsTerminal\": [\"admin\", \"superadmin\"]",
            "public static let modules: [String: [String: String]]",
            "\"execute\": [",
            "\"displayName\": \"NERVYX EXECUTE\"",
            "\"description\": \"Execution order lifecycle\"",
        ] {
            XCTAssertTrue(
                manifest.contains(snippet),
                "Generated Swift theme manifest must contain \(snippet)"
            )
        }

        XCTAssertFalse(
            manifest.contains("Paper/live"),
            "Generated Swift presentation manifest must not expose paper/live wording"
        )
        XCTAssertTrue(
            brand.contains("NervyxGeneratedThemeManifest.modules[rawValue]"),
            "Swift brand adapter must read generated module metadata"
        )
        XCTAssertTrue(
            brand.contains("NervyxGeneratedThemeManifest.themes[rawValue]"),
            "Swift brand adapter must read generated theme metadata"
        )
        XCTAssertTrue(
            brand.contains("theme == .opsTerminal && !backendConfirmedAdmin"),
            "Ops Terminal theme must stay role-gated by backend-confirmed admin state"
        )
    }

    func testNativeAppleValidationLaneDefinesWatchTargetWithoutSigningMutation() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let projectURL = packageRoot.appendingPathComponent("project.yml")
        let workflowURL = packageRoot
            .deletingLastPathComponent()
            .appendingPathComponent(".github/workflows/nervyx-ios-macos-validation.yml")
        let rootWorkflowURL = packageRoot
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".github/workflows/nervyx-ios-macos-validation.yml")
        let project = try String(contentsOf: projectURL, encoding: .utf8)
        let workflow = try String(contentsOf: workflowURL, encoding: .utf8)
        let rootWorkflow = try String(contentsOf: rootWorkflowURL, encoding: .utf8)

        for snippet in [
            "watchOS: \"10.0\"",
            "AIBotV2Watch:",
            "platform: watchOS",
            "PRODUCT_BUNDLE_IDENTIFIER: com.wali1984.aibot-v2.watch",
            "GENERATE_INFOPLIST_FILE: YES",
            "INFOPLIST_KEY_CFBundleDisplayName: NERVYX ONE",
            "INFOPLIST_KEY_WKWatchOnly: YES",
        ] {
            XCTAssertTrue(project.contains(snippet), "project.yml must define watch target snippet: \(snippet)")
        }

        for snippet in [
            "runs-on: macos-15",
            "WATCH_XCODEGEN_SCHEME: AIBotV2Watch",
            "xcodegen generate --spec project.yml",
            "-scheme \"$WATCH_XCODEGEN_SCHEME\"",
            "-destination \"generic/platform=watchOS Simulator\"",
            "CODE_SIGNING_ALLOWED=NO",
        ] {
            XCTAssertTrue(workflow.contains(snippet), "native workflow must contain \(snippet)")
            XCTAssertTrue(rootWorkflow.contains(snippet), "root native workflow must contain \(snippet)")
        }

        XCTAssertFalse(workflow.contains("DEVELOPMENT_TEAM"), "workflow must not alter signing team")
        XCTAssertFalse(workflow.contains("fastlane pilot"), "workflow must not upload to TestFlight")
        XCTAssertFalse(workflow.contains("altool"), "workflow must not use App Store upload tooling")
        XCTAssertFalse(workflow.contains("notarytool"), "workflow must not use Apple upload tooling")
        XCTAssertTrue(rootWorkflow.contains("v2/mobile/**"), "root workflow must be triggerable for mobile changes")
        XCTAssertFalse(rootWorkflow.contains("DEVELOPMENT_TEAM"), "root workflow must not alter signing team")
        XCTAssertFalse(rootWorkflow.contains("fastlane pilot"), "root workflow must not upload to TestFlight")
        XCTAssertFalse(rootWorkflow.contains("altool"), "root workflow must not use App Store upload tooling")
        XCTAssertFalse(rootWorkflow.contains("notarytool"), "root workflow must not use Apple upload tooling")
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

    func testPositionsViewDoesNotDisplayZeroPricesAsAvailable() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let viewURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Views/Positions/PositionsView.swift")
        let text = try String(contentsOf: viewURL, encoding: .utf8)
        XCTAssertTrue(
            text.contains("guard let value, value > 0 else { return \"Unavailable\" }"),
            "PositionsView must render non-positive entry, exit, and mark prices as unavailable"
        )
    }

    func testPositionsViewExposesOpenClosedHistoricalReasoningDetails() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let viewURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Views/Positions/PositionsView.swift")
        let text = try String(contentsOf: viewURL, encoding: .utf8)

        for snippet in [
            "case open = \"Open\"",
            "case closed = \"Closed\"",
            "case historical = \"Historical\"",
            "case .historical: return vm.historicalPositions",
            "NavigationLink(destination: PositionDetailView(position: pos))",
            "SectionHeader(title: \"AI Reasoning\", accent: NerVyx.primary)",
            "DataRow(label: \"Signal\", value: reasoning.signal_id ?? position.signal_id ?? \"Unavailable\", mono: true)",
            "DataRow(label: \"Prediction\", value: reasoning.prediction_id ?? position.prediction_id ?? \"Unavailable\", mono: true)",
            "DataRow(label: \"Entry Price\", value: positionPriceText(position.entry_price), mono: true)",
            "DataRow(label: \"Exit Price\", value: positionPriceText(position.exit_price), mono: true)",
            "label: \"Mark Price\"",
            "DataRow(label: \"Mark Source\", value: position.mark_price_source ?? \"Unavailable\", mono: true)",
        ] {
            XCTAssertTrue(
                text.contains(snippet),
                "PositionsView must keep open/closed/historical position detail evidence snippet: \(snippet)"
            )
        }
    }

    func testPaperPositionPreviewUsesUnavailableZeroPriceAndLinksReasoningDetail() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let viewURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Views/Paper/PaperTradingView.swift")
        let text = try String(contentsOf: viewURL, encoding: .utf8)
        XCTAssertTrue(
            text.contains("guard let value, value > 0 else { return \"Unavailable\" }"),
            "Paper position preview must render non-positive mark prices as unavailable"
        )
        XCTAssertTrue(
            text.contains("paperPositionPriceText(pos.mark_price)"),
            "Paper position preview must use the positive-price formatter for mark prices"
        )
        XCTAssertTrue(
            text.contains("paperPositionPriceText(pos.entry_price)"),
            "Paper position preview must show real entry price beside realtime mark price"
        )
        XCTAssertTrue(
            text.contains("paperPositionAgeText(pos.mark_price_age_seconds)"),
            "Paper position preview must show realtime mark freshness"
        )
        XCTAssertTrue(
            text.contains("paperPositionSourceText(pos.mark_price_source)"),
            "Paper position preview must show mark source evidence"
        )
        XCTAssertFalse(
            text.contains("pos.mark_price.map { String(format: \"%.4f\", $0) }"),
            "Paper position preview must not format zero mark prices as available values"
        )
        XCTAssertTrue(
            text.contains("NavigationLink(destination: PositionDetailView(position: pos))"),
            "Paper position preview rows must open the position detail view that renders AI reasoning"
        )
        XCTAssertTrue(
            text.contains("paperPositionReasoningText(pos)"),
            "Paper position preview must surface available signal/prediction reasoning"
        )
        XCTAssertTrue(
            text.contains("if let pricing = s.position_pricing"),
            "Paper execution screen must surface optional realtime mark-pricing metrics"
        )
        XCTAssertTrue(
            text.contains("positionPricingCard(pricing)"),
            "Paper execution screen must render the compact mark-pricing card"
        )
        XCTAssertTrue(
            text.contains("paperPositionMoneyText(pricing.total_open_notional)"),
            "Paper execution screen must render open notional from backend pricing metrics"
        )
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
