import XCTest
@testable import AIBotV2Core

final class AIBotV2CoreTests: XCTestCase {

    func testAPIEndpointsNotEmpty() {
        XCTAssertFalse(APIEndpoints.mobileDashboard.isEmpty)
        XCTAssertTrue(APIEndpoints.mobileDashboard.hasPrefix("/"))
        XCTAssertEqual(APIEndpoints.authHealth, "/api/auth/health")
        XCTAssertEqual(APIEndpoints.trainerStatus, "/api/v2/trainer/status")
        XCTAssertEqual(APIEndpoints.providersStatus, "/api/v2/providers/status")
        XCTAssertEqual(APIEndpoints.liveCanaryStatus, "/api/v2/live-canary/status")
        XCTAssertEqual(APIEndpoints.aPlusInventory, "/api/v2/a-plus/inventory")
        XCTAssertEqual(APIEndpoints.currentSignal, "/api/v2/signals/current")
    }

    func testAPIErrorMessages() {
        XCTAssertTrue(APIError.unauthorized.isUnauthorized)
        XCTAssertTrue(APIError.http(statusCode: 401, message: "").isUnauthorized)
        XCTAssertFalse(APIError.http(statusCode: 403, message: "").isUnauthorized)
    }

    func testAuthHealthDecodingKeepsLoginAndLiveSafetyTruth() throws {
        let json = """
        {
          "schema_version": "auth_health_v1",
          "generated_at_utc": "2026-07-09T12:00:00Z",
          "generated_at_et": "2026-07-09 08:00:00 EDT",
          "source": "auth_user_store_status",
          "status": "ok",
          "staleness_seconds": 0,
          "freshness_status": "fresh",
          "canonical_owner": "/api/auth/health",
          "data_quality_status": "degraded",
          "login_endpoint_available": true,
          "auth_store_backend": "local_file",
          "durable_user_store_configured": false,
          "production_ready": false,
          "contains_secret_values": false,
          "raw_credential_value_exposed": false,
          "live_gate": "blocked_human_only",
          "places_real_order": false,
          "routes_to_live": false,
          "exchange_mutation_enabled": false,
          "session_security": {
            "cookie_name": "access_token",
            "token_type": "bearer",
            "http_only_cookie": true,
            "secure_cookie": true,
            "same_site": "lax"
          },
          "warnings": ["durable_user_store_not_configured"]
        }
        """.data(using: .utf8)!

        let health = try JSONDecoder().decode(AuthHealth.self, from: json)
        XCTAssertEqual(health.schema_version, "auth_health_v1")
        XCTAssertTrue(health.isLoginReachable)
        XCTAssertTrue(health.isLiveBlocked)
        XCTAssertEqual(health.data_quality_status, "degraded")
        XCTAssertEqual(health.auth_store_backend, "local_file")
        XCTAssertEqual(health.production_ready, false)
        XCTAssertFalse(health.contains_secret_values)
        XCTAssertFalse(health.raw_credential_value_exposed)
        XCTAssertFalse(health.exchange_mutation_enabled ?? true)
        XCTAssertTrue(health.hasNoLiveRoutingOrSecretExposure)
        XCTAssertEqual(health.accountRuntimeSafetyStatus, "NO_LIVE_ROUTING_OR_SECRET_EXPOSURE")
        XCTAssertEqual(health.accountSettingsCanonicalSource, "/api/auth/health")
        XCTAssertEqual(health.session_security?.cookie_name, "access_token")
    }

    func testAuthHealthFlagsSettingsSafetyReviewWhenLiveRoutingOrSecretsAppear() throws {
        let json = """
        {
          "schema_version": "auth_health_v1",
          "status": "ok",
          "canonical_owner": "/api/auth/health",
          "login_endpoint_available": true,
          "contains_secret_values": true,
          "raw_credential_value_exposed": false,
          "live_gate": "blocked_human_only",
          "places_real_order": false,
          "routes_to_live": false,
          "exchange_mutation_enabled": false
        }
        """.data(using: .utf8)!

        let health = try JSONDecoder().decode(AuthHealth.self, from: json)
        XCTAssertTrue(health.isLiveBlocked)
        XCTAssertFalse(health.hasNoLiveRoutingOrSecretExposure)
        XCTAssertEqual(health.accountRuntimeSafetyStatus, "REVIEW_REQUIRED")
    }

    func testControlCenterStatusContractsDecodeForIOSParity() throws {
        let providerJSON = """
        {
          "schema_version": "control_center_provider_status_v1",
          "generated_at_utc": "2026-07-09T12:00:00Z",
          "generated_at_et": "2026-07-09T08:00:00-04:00",
          "source": "compact_live_fallback",
          "staleness_seconds": 0,
          "freshness_status": "fresh",
          "canonical_owner": "/api/v2/providers/status",
          "live_gate": "blocked_human_only",
          "places_real_order": false,
          "routes_to_live": false,
          "data_quality_status": "fresh",
          "data": {
            "schema_version": "enterprise_provider_cards_v1",
            "providers": [
              {
                "provider": "coinglass",
                "display_name": "CoinGlass",
                "dashboard_color": "yellow",
                "actual_payload_count": 3,
                "feature_count": 12,
                "consumer_roles": ["trainer", "risk", "UI"],
                "heartbeat_only": false,
                "actual_payload_present": true,
                "raw_key_exposed": false,
                "routes_to_live": false,
                "places_real_order": false
              },
              {
                "provider": "moralis",
                "display_name": "Moralis",
                "dashboard_color": "yellow",
                "actual_payload_count": 2,
                "watchlist_count": 250,
                "smart_wallet_candidate_count": 250,
                "raw_key_exposed": false,
                "routes_to_live": false,
                "places_real_order": false
              }
            ],
            "provider_count": 2,
            "heartbeat_only_green_count": 0,
            "live_gate": "blocked_human_only",
            "paper_only": true,
            "routes_to_live": false,
            "places_real_order": false
          }
        }
        """.data(using: .utf8)!
        let providers = try JSONDecoder().decode(ControlCenterProviderStatus.self, from: providerJSON)
        XCTAssertTrue(providers.isReadOnlyBlockedLive)
        XCTAssertEqual(providers.data.provider_count, 2)
        XCTAssertEqual(providers.data.providers.map(\.provider), ["coinglass", "moralis"])
        XCTAssertEqual(providers.data.providers.first?.raw_key_exposed, false)

        let liveCanaryJSON = """
        {
          "schema_version": "control_center_live_canary_status_v1",
          "generated_at_utc": "2026-07-09T12:00:00Z",
          "generated_at_et": "2026-07-09T08:00:00-04:00",
          "source": "redis:v2:live_canary:status",
          "staleness_seconds": 12.5,
          "freshness_status": "fresh",
          "canonical_owner": "/api/v2/live-canary/status",
          "live_gate": "blocked_human_only",
          "places_real_order": false,
          "routes_to_live": false,
          "data_quality_status": "fresh",
          "data": {
            "selected_a_plus_candidate": null,
            "why_none": "NO_A_PLUS_CANDIDATE",
            "dry_run": true,
            "operator_approval_required": true,
            "no_mutation_flags": {
              "real_order_attempted": false,
              "real_order_submitted": false,
              "test_order_submitted": false,
              "leverage_changed": false,
              "margin_mode_changed": false,
              "places_real_order": false,
              "routes_to_live": false
            }
          }
        }
        """.data(using: .utf8)!
        let liveCanary = try JSONDecoder().decode(ControlCenterLiveCanaryStatus.self, from: liveCanaryJSON)
        XCTAssertTrue(liveCanary.isReadOnlyBlockedLive)
        XCTAssertEqual(liveCanary.data.why_none, "NO_A_PLUS_CANDIDATE")
        XCTAssertEqual(liveCanary.data.no_mutation_flags?.hasNoExchangeMutation, true)

        let aPlusJSON = """
        {
          "schema_version": "control_center_a_plus_inventory_v1",
          "generated_at_utc": "2026-07-09T12:00:00Z",
          "generated_at_et": "2026-07-09T08:00:00-04:00",
          "source": "redis:v2:paper:a_plus_gate:status",
          "staleness_seconds": 22,
          "freshness_status": "fresh",
          "canonical_owner": "/api/v2/a-plus/inventory",
          "live_gate": "blocked_human_only",
          "places_real_order": false,
          "routes_to_live": false,
          "data_quality_status": "fresh",
          "data": {
            "schema_version": "v2_paper_a_plus_gate_status_v1",
            "generated_utc": "2026-07-09T12:00:00Z",
            "paper_session_id": "paper-session",
            "evaluated_candidates": 430,
            "a_plus_candidates": 0,
            "live_ready_rows": 0,
            "counts_as_final_a_plus": false,
            "b_grade_counts_as_final_a_plus": false,
            "probation_counts_as_final_a_plus": false,
            "full_candidate_count": 430,
            "payload_compacted": true,
            "candidate_matrix_preview": [
              {
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "side": "hold",
                "strategy_id": "no_trade_mode",
                "a_plus": false,
                "failed_checks": ["allocator_allows"],
                "missing_evidence_checks": [],
                "passed_check_count": 5,
                "check_count": 13
              }
            ],
            "a_plus_preview": []
          }
        }
        """.data(using: .utf8)!
        let aPlus = try JSONDecoder().decode(ControlCenterAPlusInventoryStatus.self, from: aPlusJSON)
        XCTAssertTrue(aPlus.isReadOnlyBlockedLive)
        XCTAssertEqual(aPlus.data.verifiedAPlusCount, 0)
        XCTAssertEqual(aPlus.data.counts_as_final_a_plus, false)
        XCTAssertEqual(aPlus.data.candidate_matrix_preview?.first?.symbol, "BTCUSDT")

        let signalJSON = """
        {
          "schema_version": "api_v2_readonly_envelope_v1",
          "generated_at_utc": "2026-07-09T12:00:00Z",
          "generated_at_et": "2026-07-09T08:00:00-04:00",
          "source": "Redis paper signal publisher v2:signals:paper:BTCUSDT:5m",
          "staleness_seconds": 0,
          "freshness_status": "fresh",
          "canonical_owner": "/api/v2/signals/current",
          "live_gate": "blocked_human_only",
          "places_real_order": false,
          "routes_to_live": false,
          "data_quality_status": "fresh",
          "data": {
            "active_signal": {
              "symbol": "BTCUSDT",
              "timeframe": "5m",
              "action": "long",
              "side": "Long",
              "proposed_action": "LONG",
              "actionable": false,
              "signal_id": "sig-1",
              "prediction_id": "pred-1",
              "confidence": 0.72,
              "confidence_selected_action": 0.72,
              "confidence_executable_trade": 0.0,
              "confidence_display_label": "Unproven confidence",
              "confidence_type": "selected_action_probability_not_post_cost_edge",
              "confidence_a_plus_eligible": false,
              "confidence_tradeability_block_reasons": ["operator_gated"],
              "live_gate": "blocked_human_only",
              "exchange_action_taken": false,
              "exchange_call_invariant": "LIVE_TRADING_BLOCKED",
              "market_age_seconds": 4,
              "risk_result": "Risk Blocked",
              "blocked_reason": "operator gated"
            },
            "account_scope": "public_read_only",
            "account_specific": false,
            "public_paper_signal": true
          }
        }
        """.data(using: .utf8)!
        let signal = try JSONDecoder().decode(ControlCenterCurrentSignalStatus.self, from: signalJSON)
        XCTAssertTrue(signal.isReadOnlyBlockedLive)
        XCTAssertEqual(signal.data.active_signal?.symbol, "BTCUSDT")
        XCTAssertEqual(signal.data.active_signal?.exchange_action_taken, false)
        XCTAssertEqual(signal.data.active_signal?.confidence_selected_action, 0.72)
        XCTAssertEqual(signal.data.active_signal?.confidence_executable_trade, 0.0)
        XCTAssertEqual(signal.data.active_signal?.confidence_a_plus_eligible, false)
        XCTAssertEqual(signal.data.active_signal?.exchange_call_invariant, "LIVE_TRADING_BLOCKED")
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

    func testRuntimeTruthCardDisplaysProviderTruth() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let source = try String(contentsOf: packageRoot.appendingPathComponent("Sources/AIBotV2/Views/Components/RuntimeTruthCard.swift"))

        XCTAssertTrue(source.contains("heartbeatOnly: summary.provider_readiness?.coinglass_heartbeat_only"))
        XCTAssertTrue(source.contains("marker = status ?? color ?? \"actual payload\""))
    }

    func testIOSProviderIngestorTruthScreenUsesCanonicalStatus() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let sourceRoot = packageRoot.appendingPathComponent("Sources/AIBotV2")
        let appState = try String(contentsOf: sourceRoot.appendingPathComponent("App/AppState.swift"), encoding: .utf8)
        let rootView = try String(contentsOf: sourceRoot.appendingPathComponent("Views/Root/RootView.swift"), encoding: .utf8)
        let viewModel = try String(contentsOf: sourceRoot.appendingPathComponent("ViewModels/ProviderStatusViewModel.swift"), encoding: .utf8)
        let providersView = try String(contentsOf: sourceRoot.appendingPathComponent("Views/Providers/ProvidersView.swift"), encoding: .utf8)
        let appModels = try String(contentsOf: sourceRoot.appendingPathComponent("Models/APIModels.swift"), encoding: .utf8)

        XCTAssertTrue(appState.contains("case providers"), "iOS app tabs must expose the providers and ingestors surface")
        XCTAssertTrue(rootView.contains("sidebarRow(.providers"))
        XCTAssertTrue(rootView.contains("Providers & Ingestors"))
        XCTAssertTrue(rootView.contains("ProvidersView()"))

        for snippet in [
            "APIEndpoints.providersStatus",
            "APIEndpoints.wsResourceURL",
            "decodeMobileResourceSnapshot(ControlCenterProviderStatus.self",
            "providerStatus == nil",
            "requiredAltDataProvidersVisible",
            "retiredActiveProviders",
        ] {
            XCTAssertTrue(
                viewModel.contains(snippet),
                "ProviderStatusViewModel.swift must keep provider truth on the canonical realtime/API contract: \(snippet)"
            )
        }

        for snippet in [
            "CoinGlass",
            "Moralis",
            "Provider and Ingestor Truth",
            "Heartbeat only",
            "Raw key exposed",
            "Disabled heatmap",
            "Smart wallet candidates",
            "providerDashboardTone",
            "providerDashboardBadgeText",
        ] {
            XCTAssertTrue(
                providersView.contains(snippet),
                "ProvidersView.swift must visibly render active provider truth: \(snippet)"
            )
        }

        for retiredName in ["Alpha Vantage"] {
            XCTAssertFalse(
                providersView.contains(retiredName),
                "ProvidersView.swift must not show retired providers as active panels: \(retiredName)"
            )
        }

        for field in [
            "last_success_utc",
            "last_error_utc",
            "source_lag_seconds",
            "keys_published",
            "rate_limit_used",
            "rate_limit_remaining",
            "daily_quota_used",
            "monthly_quota_used",
            "providerDashboardTone",
            "providerDashboardBadgeText",
        ] {
            XCTAssertTrue(
                appModels.contains(field),
                "AIBotV2 app models must decode provider runtime field: \(field)"
            )
        }
    }

    func testIOSLiveReadinessShowsCanonicalLiveCanaryAndAPlusTruth() throws {
        let packageRoot = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let sourceRoot = packageRoot.appendingPathComponent("Sources/AIBotV2")
        let viewModel = try String(contentsOf: sourceRoot.appendingPathComponent("ViewModels/LiveReadinessViewModel.swift"), encoding: .utf8)
        let liveReadinessView = try String(contentsOf: sourceRoot.appendingPathComponent("Views/LiveReadiness/LiveReadinessView.swift"), encoding: .utf8)

        for snippet in [
            "ControlCenterLiveCanaryStatus",
            "ControlCenterAPlusInventoryStatus",
            "APIEndpoints.liveCanaryStatus",
            "APIEndpoints.aPlusInventory",
            "liveCanaryStatus",
            "aPlusInventoryStatus",
        ] {
            XCTAssertTrue(
                viewModel.contains(snippet),
                "LiveReadinessViewModel.swift must consume canonical live-canary/A+ contracts: \(snippet)"
            )
        }

        for snippet in [
            "Live Canary",
            "Selected A+ candidate",
            "Why none",
            "Dry run",
            "Operator approval",
            "No mutation flags",
            "A+ candidates",
            "Live-ready rows",
            "Inventory source",
        ] {
            XCTAssertTrue(
                liveReadinessView.contains(snippet),
                "LiveReadinessView.swift must expose live-canary and A+ runtime truth: \(snippet)"
            )
        }
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
                "decodeMobileResourceSnapshot",
            ],
            "ViewModels/AlertsViewModel.swift": [
                "APIEndpoints.wsResourceURL",
                "APIEndpoints.mobileAlerts",
                "decodeMobileResourceSnapshot",
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
            },
            {
              "provider": "coinank",
              "display_name": "CoinAnk",
              "status": "READY",
              "dashboard_color": "gray",
              "dashboard_color_reason": "provider_runtime_summary",
              "actual_payload_count": 1,
              "feature_count": 12,
              "consumer_count": 0,
              "heartbeat_only": false,
              "actual_payload_present": true,
              "raw_key_exposed": false,
              "routes_to_live": false,
              "places_real_order": false
            },
            {
              "provider": "moralis",
              "display_name": "Moralis",
              "status": "CONFIGURED_NO_WATCHLIST",
              "dashboard_color": "gray",
              "dashboard_color_reason": "provider_runtime_summary",
              "actual_payload_count": 1,
              "feature_count": 1,
              "consumer_count": 0,
              "heartbeat_only": false,
              "actual_payload_present": true,
              "raw_key_exposed": false,
              "routes_to_live": false,
              "places_real_order": false
            },
            {
              "provider": "binance",
              "display_name": "Binance",
              "status": "unknown",
              "dashboard_color": "gray",
              "dashboard_color_reason": "provider_runtime_summary",
              "actual_payload_count": 0,
              "feature_count": 0,
              "consumer_count": 0,
              "heartbeat_only": false,
              "actual_payload_present": false,
              "raw_key_exposed": false,
              "routes_to_live": false,
              "places_real_order": false
            },
            {
              "provider": "heartbeat_only",
              "display_name": "Heartbeat Only",
              "status": "READY",
              "dashboard_color": "green",
              "dashboard_color_reason": "heartbeat_not_payload",
              "actual_payload_count": 1,
              "feature_count": 1,
              "consumer_count": 0,
              "heartbeat_only": true,
              "actual_payload_present": true,
              "raw_key_exposed": false,
              "routes_to_live": false,
              "places_real_order": false
            }
          ],
          "provider_count": 5,
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
        XCTAssertEqual(providers.providers.first?.providerDashboardTone, "yellow")
        XCTAssertEqual(providers.providers.first?.providerDashboardBadgeText, "YELLOW")
        XCTAssertFalse(providers.providers.first?.raw_key_exposed ?? true)
        let tones = Dictionary(uniqueKeysWithValues: providers.providers.map { ($0.provider, $0.providerDashboardTone) })
        XCTAssertEqual(tones["coinank"], "green")
        XCTAssertEqual(tones["moralis"], "yellow")
        XCTAssertEqual(tones["binance"], "gray")
        XCTAssertEqual(tones["heartbeat_only"], "yellow")
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
        ] {
            XCTAssertTrue(
                text.contains(snippet),
                "PositionsView must keep open/closed/historical position list evidence snippet: \(snippet)"
            )
        }

        // Detail evidence moved to the shared Infra-owned component
        // (Views/Components/PositionDetailView.swift) so Portfolio, Execute and
        // Executions push the SAME evidence-grade detail view.
        let detailURL = packageRoot.appendingPathComponent("Sources/AIBotV2/Views/Components/PositionDetailView.swift")
        let detailText = try String(contentsOf: detailURL, encoding: .utf8)

        for snippet in [
            "guard let value, value > 0 else { return \"Unavailable\" }",
            "SectionHeader(title: \"AI Reasoning\", accent: NerVyx.primary)",
            "DataRow(label: \"Signal\", value: reasoning.signal_id ?? position.signal_id ?? \"Unavailable\", mono: true)",
            "DataRow(label: \"Prediction\", value: reasoning.prediction_id ?? position.prediction_id ?? \"Unavailable\", mono: true)",
            "DataRow(label: \"Entry Price\", value: positionPriceText(position.entry_price), mono: true)",
            "DataRow(label: \"Exit Price\", value: positionPriceText(position.exit_price), mono: true)",
            "label: \"Mark Price\"",
            "DataRow(label: \"Mark Source\", value: position.mark_price_source ?? \"Unavailable\", mono: true)",
        ] {
            XCTAssertTrue(
                detailText.contains(snippet),
                "PositionDetailView component must keep position detail evidence snippet: \(snippet)"
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

    func testMissingFeatureAlertDecodesAndStaysOperational() throws {
        let json = Data("""
        {"active":true,"severity":"critical","operational":true,"prediction_still_produced":true,
         "data_coverage_pct":53.8,"missing_feature_count":144,"stale_feature_count":3,
         "missing_by_category":{"alternative_data":12,"htf":4},
         "missing_provider_names":["coinglass_funding_rate"],
         "message":"Data coverage at inference: 53.8% (144 features missing)."}
        """.utf8)
        let alert = try JSONDecoder().decode(AIPredictionMissingFeatureAlert.self, from: json)
        XCTAssertTrue(alert.active)
        XCTAssertEqual(alert.severity, "critical")
        // System keeps operating end-to-end even under missing features.
        XCTAssertTrue(alert.operational)
        XCTAssertTrue(alert.prediction_still_produced)
        XCTAssertEqual(alert.data_coverage_pct, 53.8)
        XCTAssertEqual(alert.missing_feature_count, 144)
        XCTAssertEqual(alert.missing_by_category["alternative_data"], 12)
        XCTAssertEqual(alert.missing_provider_names.first, "coinglass_funding_rate")
    }

    func testBacktestResultsDecodeIncludeGeneralizationAndReplayFeedback() throws {
        let json = Data("""
        {"available":true,"generated_utc":"2026-07-11T21:00:00Z",
         "effective_trainer_mode":"REPLAY_AND_ONLINE_LEARNING","replay_examples_built":1328,
         "backtest_is_a_plus_evidence":false,"continuous_replay_active":true,
         "policy_backtest":{"win_rate":0.9895,"profit_factor_proxy":209.29,"expectancy_after_cost_bps":54.49,"rows_evaluated":16384,"status":"OK","evidence_class":"BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE"},
         "generalization":{"validation_supervised_loss":7.63,"validation_rows_evaluated":3276,"train_val_generalization_gap":3.98,"overfit_gap_warning":true,"loss_before":87.2,"loss_after":3.65},
         "replay_feedback":{"existing_counterfactual_rows":3198,"new_matured_rows":173,"pending_rows":1522,"trainer_loader_consumes":true}}
        """.utf8)
        let bt = try JSONDecoder().decode(BacktestResults.self, from: json)
        XCTAssertTrue(bt.available)
        // Backtest is never A+/live evidence.
        XCTAssertFalse(bt.backtest_is_a_plus_evidence)
        XCTAssertEqual(bt.policy_backtest?.win_rate, 0.9895)
        XCTAssertEqual(bt.policy_backtest?.evidence_class, "BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE")
        // Out-of-sample overfit signal is surfaced.
        XCTAssertEqual(bt.generalization?.overfit_gap_warning, true)
        XCTAssertEqual(bt.generalization?.train_val_generalization_gap, 3.98)
        XCTAssertEqual(bt.replay_feedback?.existing_counterfactual_rows, 3198)
        XCTAssertEqual(bt.continuous_replay_active, true)
    }

    func testMobileRiskStatusDecodesHedgeSnapshot() throws {
        let json = Data("""
        {"schema_version":"mobile_risk_status_v2","generated_utc":"2026-07-11T00:00:00Z",
         "generated_at_utc":"2026-07-11T00:00:00Z","generated_at_et":"2026-07-10T20:00:00-04:00",
         "live_gate":{"live_trading_enabled":false,"places_real_order":false,"gate":"blocked_human_only","label":"OPERATOR GATED"},
         "routes_to_live":false,"places_real_order":false,
         "hedge":{"schema_version":"enterprise_hedge_snapshot_v1","hedge_engine_active":true,
           "hedge_evaluation_mode":"on_demand_per_negative_position","open_position_count":2,
           "negative_position_count":1,
           "hedge_required_candidates":[{"symbol":"BTCUSDT","side":"long","unrealized_pnl_usd":-12.5}],
           "portfolio_liquidation_buffer_usd":1234.5,
           "hedge_basket":["same_symbol_opposite","BTC","cash"],"cross_margin_model":"portfolio_level",
           "places_real_order":false,"routes_to_live":false},
         "risk_state":"ACTIVE","paper_blocked_count":3,"paper_accepted_count":7,
         "kill_switch_active":true,"max_position_size_usd":100.0,"daily_loss_limit_usd":50.0,
         "current_daily_loss_usd":0.0,"dangerous_actions_require_human_approval":true,
         "mobile_can_approve_dangerous_actions":false}
        """.utf8)
        let risk = try JSONDecoder().decode(MobileRiskStatus.self, from: json)
        XCTAssertEqual(risk.hedge?.hedge_engine_active, true)
        XCTAssertEqual(risk.hedge?.open_position_count, 2)
        XCTAssertEqual(risk.hedge?.negative_position_count, 1)
        XCTAssertEqual(risk.hedge?.hedge_required_candidates?.first?.symbol, "BTCUSDT")
        XCTAssertEqual(risk.hedge?.hedge_required_candidates?.first?.unrealized_pnl_usd, -12.5)
        // Hedge posture is display-only; it never routes to live or places an order.
        XCTAssertEqual(risk.hedge?.places_real_order, false)
        XCTAssertEqual(risk.hedge?.routes_to_live, false)
    }

    func testMobileRiskStatusDecodesWithoutHedgeBlock() throws {
        let json = Data("""
        {"schema_version":"mobile_risk_status_v2","generated_utc":"2026-07-11T00:00:00Z",
         "generated_at_utc":"2026-07-11T00:00:00Z","generated_at_et":"2026-07-10T20:00:00-04:00",
         "live_gate":{"live_trading_enabled":false,"places_real_order":false,"gate":"blocked_human_only","label":"OPERATOR GATED"},
         "routes_to_live":false,"places_real_order":false,
         "risk_state":"ACTIVE","paper_blocked_count":0,"paper_accepted_count":0,
         "kill_switch_active":true,"max_position_size_usd":100.0,"daily_loss_limit_usd":50.0,
         "current_daily_loss_usd":0.0,"dangerous_actions_require_human_approval":true,
         "mobile_can_approve_dangerous_actions":false}
        """.utf8)
        let risk = try JSONDecoder().decode(MobileRiskStatus.self, from: json)
        XCTAssertNil(risk.hedge)  // optional -> absent block must not break decoding
    }

    func testMobileRiskStatusDecodesRealTraderReadinessBlockers() throws {
        let json = Data("""
        {"schema_version":"mobile_risk_status_v2","generated_utc":"2026-07-11T00:00:00Z",
         "generated_at_utc":"2026-07-11T00:00:00Z","generated_at_et":"2026-07-10T20:00:00-04:00",
         "live_gate":{"live_trading_enabled":false,"places_real_order":false,"gate":"blocked_human_only","label":"OPERATOR GATED"},
         "routes_to_live":false,"places_real_order":false,
         "real_trader_readiness":{"live_gate":"blocked_human_only","operator_flip_required":true,
           "order_submitted":false,"test_order_submitted":false,"leverage_mutated":false,
           "margin_mutated":false,"routes_to_live":false,"places_real_order":false,
           "live_submit_allowed":false,"live_ready":false,
           "exact_no_live_reason":"A_GRADE_SUPPLY_ZERO",
           "readiness_blockers":["A_GRADE_SUPPLY_ZERO","GUARDIAN_HALTED_PERFORMANCE"]},
         "risk_state":"ACTIVE","paper_blocked_count":0,"paper_accepted_count":0,
         "kill_switch_active":true,"max_position_size_usd":100.0,"daily_loss_limit_usd":50.0,
         "current_daily_loss_usd":0.0,"dangerous_actions_require_human_approval":true,
         "mobile_can_approve_dangerous_actions":false}
        """.utf8)
        let risk = try JSONDecoder().decode(MobileRiskStatus.self, from: json)
        XCTAssertEqual(risk.real_trader_readiness?.live_ready, false)
        XCTAssertEqual(risk.real_trader_readiness?.live_submit_allowed, false)
        XCTAssertEqual(risk.real_trader_readiness?.exact_no_live_reason, "A_GRADE_SUPPLY_ZERO")
        XCTAssertEqual(risk.real_trader_readiness?.readiness_blockers?.first, "A_GRADE_SUPPLY_ZERO")
        XCTAssertEqual(risk.real_trader_readiness?.routes_to_live, false)
        XCTAssertEqual(risk.real_trader_readiness?.places_real_order, false)
    }

    func testMobileHealthDecodesIngestorRollup() throws {
        let json = Data("""
        {"generated_utc":"2026-07-11T00:00:00Z","overall":"healthy","redis_connected":true,
         "trainer":{"state":"ACTIVE","cuda_active":true,"training_active":true,"checkpoint":"ckpt-9"},
         "gpu":{"name":"RTX 5080","utilization_pct":42.0,"vram_used_mb":8000,"vram_total_mb":16000,"temperature_c":55.0},
         "paper":{"classification":"ACTIVE","open_positions":2,"intents_accepted":7,"intents_blocked":3},
         "ingestors":{"schema_version":"enterprise_ingestors_rollup_v1","overall_status":"HEALTHY",
           "stream_present":{"candles":true,"orderbook_features":true,"trade_tape":true,"funding_oi":true,
             "liquidation_levels":true,"ta_full":true,"feature_snapshots":true},
           "all_core_streams_present":true,"provider_count":11,"active_provider_count":11,
           "stale_provider_count":0,"stale_providers":[]},
         "live_gate":"blocked_human_only","places_real_order":false}
        """.utf8)
        let health = try JSONDecoder().decode(MobileHealth.self, from: json)
        XCTAssertEqual(health.ingestors?.overall_status, "HEALTHY")
        XCTAssertEqual(health.ingestors?.all_core_streams_present, true)
        XCTAssertEqual(health.ingestors?.active_provider_count, 11)
        XCTAssertEqual(health.ingestors?.stale_provider_count, 0)
        XCTAssertEqual(health.ingestors?.stream_present?["ta_full"], true)
    }

    func testMobileHealthDecodesWithoutIngestorBlock() throws {
        let json = Data("""
        {"generated_utc":"2026-07-11T00:00:00Z","overall":"degraded","redis_connected":true,
         "trainer":{"state":"ACTIVE","cuda_active":true,"training_active":true,"checkpoint":"ckpt-9"},
         "gpu":{"name":"RTX 5080","utilization_pct":42.0,"vram_used_mb":8000,"vram_total_mb":16000,"temperature_c":55.0},
         "paper":{"classification":"ACTIVE","open_positions":0,"intents_accepted":0,"intents_blocked":0},
         "live_gate":"blocked_human_only","places_real_order":false}
        """.utf8)
        let health = try JSONDecoder().decode(MobileHealth.self, from: json)
        XCTAssertNil(health.ingestors)  // optional -> absent block must not break decoding
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

    // MARK: - Website-parity contract fixtures (shapes captured from the live backend 2026-07-19)

    func testMobileDerivativesSummaryDecodesLivePayloadShape() throws {
        let json = Data("""
        {"schema_version":"mobile_derivatives_summary_v1","generated_utc":"2026-07-19T23:41:00Z",
         "payload_generated_utc":"2026-07-19T23:40:49Z","source":"operator_runtime/v2_derivatives/latest/derivatives_payload.json",
         "staleness_seconds":4.19,"freshness_status":"fresh","live_gate":"blocked_human_only","places_real_order":false,
         "aggregate":{"total_oi_usd":38731715815.092,"total_liq_24h":780457.88,"avg_funding":0.000020225,
                      "aggregate_long_short_ratio":1.885,"funding_positive_count":33,"funding_negative_count":14},
         "global_regime":{"market_sentiment":-0.342,"avg_funding_rate":0.000020225,"aggregate_long_short_ratio":1.885,
                          "total_open_interest_usd":38731715815.092,"total_liquidations_usd":780457.88,
                          "total_volume_usd":92876147.89,"data_status":"CURRENT_OR_RECENT","is_fresh":true,"age_seconds":12.5},
         "top_symbols":[{"symbol":"BTCUSDT","funding_rate":0.00005055,"oi_usd":6617097182.21,"long_short_ratio":1.3798,
                         "basis_bps":-4.86,"cascade_risk":0.701,"mark_price":64632.63},
                        {"symbol":"XUSDT","funding_rate":null,"oi_usd":null,"long_short_ratio":null,
                         "basis_bps":null,"cascade_risk":null,"mark_price":null}],
         "symbol_count":48}
        """.utf8)
        let summary = try JSONDecoder().decode(MobileDerivativesSummary.self, from: json)
        XCTAssertEqual(summary.live_gate, "blocked_human_only")
        XCTAssertEqual(summary.places_real_order, false)
        XCTAssertEqual(summary.aggregate?.funding_positive_count, 33)
        XCTAssertEqual(summary.top_symbols?.first?.symbol, "BTCUSDT")
        // Absent per-symbol values decode as nil (rendered "—", never 0).
        XCTAssertNil(summary.top_symbols?.last?.funding_rate)
    }

    func testMobileSignalMatrixDecodesSlimCells() throws {
        let json = Data("""
        {"schema_version":"mobile_signal_matrix_v1","generated_utc":"2026-07-19T23:41:00Z",
         "payload_generated_utc":"2026-07-19T19:30:34-04:00","source":"operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
         "staleness_seconds":120.0,"freshness_status":"aging","live_gate":"blocked_human_only","places_real_order":false,
         "timeframes":["1m","5m","15m","1h","4h"],"symbol_count":156,"cell_count":780,"actionable_count":0,
         "cells":[{"s":"0GUSDT","tf":"1m","a":"short","c":0.5267,"act":false,"g":"MISSING_CRITICAL_FEATURE_FAMILY"},
                  {"s":"BTCUSDT","tf":"4h","a":"long","c":0.998,"act":true,"g":null}]}
        """.utf8)
        let matrix = try JSONDecoder().decode(MobileSignalMatrix.self, from: json)
        XCTAssertEqual(matrix.cells.count, 2)
        XCTAssertEqual(matrix.cells[0].g, "MISSING_CRITICAL_FEATURE_FAMILY")
        XCTAssertEqual(matrix.cells[1].act, true)
        XCTAssertNil(matrix.cells[1].g)  // actionable cells carry no gate reason
        XCTAssertEqual(matrix.timeframes?.count, 5)
    }

    func testSignalPredictionAccuracyAndPnLWindowsDecode() throws {
        let accuracyJSON = Data("""
        {"source":"v2:paper:closed_trades","accuracy_definition":"winner_rate","overall_accuracy":0.3696,
         "evaluated_row_count":92,"correct_count":34,"incorrect_count":58,
         "by_timeframe":[{"timeframe":"4h","evaluated_count":37,"correct_count":14,"incorrect_count":23,"accuracy":0.3784}]}
        """.utf8)
        let accuracy = try JSONDecoder().decode(SignalPredictionAccuracy.self, from: accuracyJSON)
        XCTAssertEqual(accuracy.accuracy_definition, "winner_rate")  // winner flag, never sign(pnl)
        XCTAssertEqual(accuracy.correct_count, 34)
        XCTAssertEqual(accuracy.by_timeframe?.first?.timeframe, "4h")

        let windowJSON = Data("""
        [{"window":"1d","realized_pnl_usd":0,"closed_trade_count":0,"winning_trade_count":0,
          "losing_trade_count":0,"win_rate":null,"profit_factor":null},
         {"window":"7d","realized_pnl_usd":-14.4053,"closed_trade_count":92,"winning_trade_count":34,
          "losing_trade_count":58,"win_rate":0.3696,"profit_factor":0.6362}]
        """.utf8)
        let windows = try JSONDecoder().decode([PnLWindow].self, from: windowJSON)
        XCTAssertEqual(windows.count, 2)
        XCTAssertNil(windows[0].win_rate)  // empty window is honest-null, not 0
        XCTAssertEqual(windows[1].realized_pnl_usd, -14.4053)
    }

    func testGoalTrajectoryAndMarketOverviewDecodeLiveShapes() throws {
        let goalJSON = Data("""
        {"schema_version":"goal_trajectory_1000x_contract_v1","source":"redis:v2:goal:trajectory_1000x",
         "generated_at_utc":"2026-07-19T23:30:04Z","staleness_seconds":172.3,"freshness_status":"fresh",
         "live_gate":"blocked_human_only","places_real_order":false,
         "data":{"objective":"1000x_in_90_days_research_objective_not_a_promise","multiple_now":0.995198,
                 "target_multiple":1000.0,"target_days":90.0,"days_elapsed":6.179,
                 "required_daily_rate_pct":7.978,"actual_daily_rate_pct":-0.0779,"on_track":false,
                 "growth_stage":{"stage":"EDGE_REPAIR","closes_24h":0,"rolling_25_pf":0.209,"rolling_25_weighted_bps":-103.152},
                 "binding_constraint":{"constraint":"PERFORMANCE_CIRCUIT_HALTED","detail":"entry circuit halted"},
                 "equity_gap_vs_required_usd":-1834.96,"days_to_target_at_required_rate_from_here":90.1,
                 "equity_usd":2985.59,"starting_equity_usd":3000.0,"closed_trade_count":92,"open_position_count":0,
                 "paper_session_id":"paper_3000_final_pre_live_20260713T190904Z","live_gate":"blocked_human_only",
                 "paper_only":true,"places_real_order":false,"is_stale":false,"age_seconds":172.3}}
        """.utf8)
        let goal = try JSONDecoder().decode(GoalTrajectoryResponse.self, from: goalJSON)
        XCTAssertEqual(goal.data.growth_stage?.stage, "EDGE_REPAIR")
        XCTAssertEqual(goal.data.on_track, false)
        XCTAssertEqual(goal.data.binding_constraint?.constraint, "PERFORMANCE_CIRCUIT_HALTED")

        let marketJSON = Data("""
        {"schema_version":"api_v2_readonly_envelope_v1","source_type":"redis_live","stale":false,
         "live_gate":"blocked_human_only","lag_ms":100,
         "data":{"symbols":["BTCUSDT"],"count":1,"timeframes":["1m"],
                 "canonical_runtime_source":"redis:v2:market:kline_current:binance:*:1m",
                 "tickers":[{"symbol":"BTCUSDT","last_price":64642.1,"change_24h":-0.00241,"high_24h":64948.8,
                             "low_24h":64259.5,"volume_24h":4058906144.59,"turnover_24h":50937.91,
                             "funding_rate":0.00005414,"mark_price":64642.72,"open_interest":null,
                             "long_short_ratio":1.3798,"source":"binance_wss","event_time":"2026-07-19T23:30:03.640000Z",
                             "candle_closed_confirmed":false,"display_only_current_candle":true,
                             "index_price":64675.80}]}}
        """.utf8)
        let market = try JSONDecoder().decode(MarketOverviewResponse.self, from: marketJSON)
        XCTAssertEqual(market.data.tickers.first?.symbol, "BTCUSDT")
        XCTAssertNil(market.data.tickers.first?.open_interest)
        XCTAssertEqual(market.data.tickers.first?.candle_closed_confirmed, false)
    }
}
