import json
import time

import pytest

from app.api.v2 import market_contracts


def _apply(state: dict, stream: str, data: dict) -> None:
    market_contracts._apply_native_stream_message(
        raw=json.dumps({"stream": stream, "data": data}),
        state=state,
        symbol="BTCUSDT",
        timeframe="1m",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/api/v2/risk/status", "/api/v2/risk/status"),
        ("/api/v2/market/overview?limit=30", "/api/v2/market/overview?limit=30"),
        ("%2Fapi%2Fv2%2Fpredictions%2Fmatrix%3Fsymbol%3DBTCUSDT", "/api/v2/predictions/matrix?symbol=BTCUSDT"),
        ("/api/v1/risk/live-readiness", "/api/v1/risk/live-readiness"),
        ("/api/v1/_meta/agent-health", "/api/v1/_meta/agent-health"),
        ("/api/v1/_meta/build-status?limit=10", "/api/v1/_meta/build-status?limit=10"),
        ("/api/v1/_meta/queue-status", "/api/v1/_meta/queue-status"),
        ("/api/v1/_meta/audit-chain?limit=50", "/api/v1/_meta/audit-chain?limit=50"),
        (
            "/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "/operator_runtime/paper_online/latest/paper_runtime_status.json",
        ),
        (
            "/v2_8h_war_room/latest/operator_dashboard_payload.json?_rt=123",
            "/v2_8h_war_room/latest/operator_dashboard_payload.json?_rt=123",
        ),
        (
            "/enterprise_trading_cockpit/latest/operator_cockpit_payload.json",
            "/enterprise_trading_cockpit/latest/operator_cockpit_payload.json",
        ),
        (
            "/operator_truth/latest/operator_truth_payload.json",
            "/operator_truth/latest/operator_truth_payload.json",
        ),
        (
            "/tonight_live_like_paper_shadow/latest/operator_dashboard_payload.json",
            "/tonight_live_like_paper_shadow/latest/operator_dashboard_payload.json",
        ),
    ],
)
def test_readonly_resource_websocket_target_allows_same_origin_get_paths(raw: str, expected: str) -> None:
    assert market_contracts._safe_readonly_resource_target(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "https://example.com/api/v2/risk/status",
        "/api/v2/../secret",
        "/api/v2/ws/paper-activity",
        "/ws/paper-activity",
        "/api/v2/orders",
        "/api/v2/orders/paper",
        "/api/v2/backtest/run",
        "/api/v2/account/leverage",
        "/api/v2/account/margin",
        "/api/v2/execution/submit",
        "/api/v2/position/cancel",
        "/api/v2/state/mutate",
        "/operator_runtime/paper_online/latest/not_json.txt",
        "/operator_truth/latest/not_json.txt",
        "/enterprise_trading_cockpit/latest/not_json.txt",
        "/assets/app.js",
        "/favicon.ico",
    ],
)
def test_readonly_resource_websocket_target_rejects_mutating_or_external_paths(raw: str | None) -> None:
    assert market_contracts._safe_readonly_resource_target(raw) is None


def test_readonly_resource_websocket_wraps_static_payload_as_envelope() -> None:
    payload = market_contracts._readonly_resource_ws_payload(
        "/operator_runtime/paper_online/latest/paper_runtime_status.json",
        {"cycle": {"status": "running"}},
        time.monotonic(),
    )

    assert payload["data"] == {"cycle": {"status": "running"}}
    assert payload["source_type"] == "static_payload"
    assert payload["transport"] == "websocket"
    assert payload["resource_path"] == "/operator_runtime/paper_online/latest/paper_runtime_status.json"
    assert payload["mode"] == "read_only"


def test_readonly_resource_websocket_preserves_contract_payload_envelope() -> None:
    payload = market_contracts._readonly_resource_ws_payload(
        "/api/v2/market/overview",
        {
            "data": {"count": 2},
            "source": "market_overview",
            "source_type": "api",
            "endpoint": "/api/v2/market/overview",
            "missing_fields": [],
            "warnings": [],
            "mode": "read_only",
        },
        time.monotonic(),
    )

    assert payload["data"] == {"count": 2}
    assert payload["source"] == "market_overview"
    assert payload["source_type"] == "api"
    assert payload["transport"] == "websocket"
    assert payload["resource_path"] == "/api/v2/market/overview"


@pytest.mark.asyncio
async def test_market_brain_redis_helpers_support_async_bytes_and_key_collections() -> None:
    class _Redis:
        async def get(self, key: str) -> bytes | None:
            if key == "v2:market_brain:overview":
                return b'{"classifications_computed": 2, "places_real_order": false}'
            return None

        async def keys(self, pattern: str) -> tuple[bytes, str]:
            assert pattern == "v2:market_brain:state:*"
            return (b"v2:market_brain:state:BTCUSDT:1m", "v2:market_brain:state:ETHUSDT:5m")

    assert await market_contracts._redis_get_json_object(_Redis(), "v2:market_brain:overview") == {
        "classifications_computed": 2,
        "places_real_order": False,
    }
    assert await market_contracts._redis_get_json_object(_Redis(), "v2:market_brain:missing") is None
    assert await market_contracts._redis_keys(_Redis(), "v2:market_brain:state:*") == [
        "v2:market_brain:state:BTCUSDT:1m",
        "v2:market_brain:state:ETHUSDT:5m",
    ]


@pytest.mark.asyncio
async def test_market_brain_overview_returns_connecting_envelope_when_redis_empty() -> None:
    payload = await market_contracts.get_market_brain_overview(actor={"role": "viewer"}, r=None)

    assert payload["data"]["classifications_computed"] == 0
    assert payload["data"]["note"] == "Market brain stream connecting"
    assert payload["data"]["places_real_order"] is False
    assert payload["missing_fields"] == []


def test_binance_public_json_uses_short_ttl_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class _Response:
        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'[{"symbol":"BTCUSDT","lastPrice":"100.0"}]'

    def fake_urlopen(_request: object, timeout: float) -> _Response:
        nonlocal calls
        assert timeout == market_contracts.BINANCE_HTTP_TIMEOUT_SECONDS
        calls += 1
        return _Response()

    monkeypatch.setattr(market_contracts, "BINANCE_PUBLIC_CACHE_TTL_SECONDS", 30.0)
    monkeypatch.setattr(market_contracts.urllib.request, "urlopen", fake_urlopen)
    with market_contracts.BINANCE_PUBLIC_JSON_CACHE_LOCK:
        market_contracts.BINANCE_PUBLIC_JSON_CACHE.clear()

    first, first_source, first_warning = market_contracts._binance_public_json(
        "/fapi/v1/ticker/24hr",
        {"symbol": "BTCUSDT"},
    )
    second, second_source, second_warning = market_contracts._binance_public_json(
        "/fapi/v1/ticker/24hr",
        {"symbol": "BTCUSDT"},
    )

    assert calls == 1
    assert first == second == [{"symbol": "BTCUSDT", "lastPrice": "100.0"}]
    assert first_source == second_source
    assert first_warning is None
    assert second_warning is None

    with market_contracts.BINANCE_PUBLIC_JSON_CACHE_LOCK:
        market_contracts.BINANCE_PUBLIC_JSON_CACHE.clear()


@pytest.mark.asyncio
async def test_readonly_resource_direct_payload_routes_market_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_market_detail(symbol: str) -> dict:
        return {
            "data": {"symbol": symbol, "last_price": 100.0},
            "source": "unit-test",
            "source_type": "api",
            "endpoint": f"/api/v2/market/{symbol}",
            "missing_fields": [],
            "warnings": [],
            "mode": "read_only",
        }

    monkeypatch.setattr(market_contracts, "get_market_detail", fake_market_detail)

    handled, payload = await market_contracts._readonly_resource_direct_payload("/api/v2/market/btcusdt")

    assert handled is True
    assert payload["data"] == {"symbol": "BTCUSDT", "last_price": 100.0}
    assert payload["endpoint"] == "/api/v2/market/BTCUSDT"


@pytest.mark.asyncio
async def test_readonly_resource_direct_payload_routes_adaptive_capital_dashboard(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_adaptive_dashboard() -> dict:
        return {
            "data": {"overall_status": "NO_GO", "signal_prediction_accuracy_status": {"evaluated_row_count": 1641}},
            "source": "unit-test",
            "source_type": "static_payload",
            "endpoint": "/api/v2/adaptive-capital/dashboard",
            "missing_fields": [],
            "warnings": [],
            "mode": "read_only",
        }

    monkeypatch.setattr(market_contracts, "get_adaptive_capital_dashboard", fake_adaptive_dashboard)

    handled, payload = await market_contracts._readonly_resource_direct_payload("/api/v2/adaptive-capital/dashboard")

    assert handled is True
    assert payload["data"]["signal_prediction_accuracy_status"]["evaluated_row_count"] == 1641
    assert payload["endpoint"] == "/api/v2/adaptive-capital/dashboard"


@pytest.mark.asyncio
async def test_readonly_resource_direct_payload_routes_paper_status_and_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_paper_status(actor=None) -> dict:
        return {
            "data": {"positions": [{"symbol": "BTCUSDT", "entry_price": 100.0}]},
            "source": "v2:paper:* Redis",
            "source_type": "redis_live",
            "endpoint": "/api/v2/paper/status",
            "missing_fields": [],
            "warnings": [],
            "mode": "paper",
        }

    async def fake_paper_activity(actor=None) -> dict:
        return {
            "data": {"positions": [{"symbol": "ETHUSDT", "mark_price": 200.0}]},
            "source": "v2:paper:* Redis",
            "source_type": "redis_live",
            "endpoint": "/api/v2/paper/activity",
            "missing_fields": [],
            "warnings": [],
            "mode": "paper",
        }

    monkeypatch.setattr(market_contracts, "get_paper_status", fake_paper_status)
    monkeypatch.setattr(market_contracts, "get_paper_activity", fake_paper_activity)

    status_handled, status_payload = await market_contracts._readonly_resource_direct_payload(
        "/api/v2/paper/status"
    )
    activity_handled, activity_payload = await market_contracts._readonly_resource_direct_payload(
        "/api/v2/paper/activity"
    )

    assert status_handled is True
    assert status_payload["endpoint"] == "/api/v2/paper/status"
    assert status_payload["data"]["positions"][0]["entry_price"] == 100.0
    assert activity_handled is True
    assert activity_payload["endpoint"] == "/api/v2/paper/activity"
    assert activity_payload["data"]["positions"][0]["mark_price"] == 200.0


def test_adaptive_capital_compact_payload_keeps_rendered_fields_and_drops_samples(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_root = tmp_path / "public"
    base = public_root / "operator_runtime/v2_adaptive_capital_productivity/latest"
    base.mkdir(parents=True)
    dashboard = {
        "generated_utc": "2026-06-21T23:11:51Z",
        "overall_status": "NO_GO",
        "operator_go_readiness": {
            "status": "NO_GO",
            "overall_status": "NO_GO",
            "evidence_to_go": {"closed_outcomes_needed": 0},
            "counterfactual_replay_progress": {
                "a_grade_replay_progress_pct": 1.0,
                "near_a_grade_counterfactual_probe": {
                    "status": "READY",
                    "prediction_row_count": 12,
                    "skipped_no_feasible_configuration_sample": [{"large": True}],
                },
            },
        },
        "capital_productivity_runtime_status": {
            "status": "NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE",
            "allocated_margin_usd": 100.0,
            "capital_productivity_progress": {
                "current_closed_outcome_count": 44,
                "evidence_acquisition_status": {"large": True},
            },
            "signal_prediction_accuracy_status": {
                "status": "READY",
                "evaluated_row_count": 1641,
                "symbol_universe_count": 151,
                "by_symbol_timeframe": [{"symbol": "BTCUSDT", "timeframe": "1m", "evaluated_count": 3}],
                "sample_evaluated_rows": [{"large": True}],
            },
        },
        "adaptive_capital_policy_status": {
            "status": "PASSED",
            "adaptive_field_selection_evidence": {
                "row_count": 4,
                "missing_selection_attribution_sample": [{"large": True}],
            },
        },
        "counterfactual_capital_sweep_status": {
            "status": "PASSED",
            "counterfactual_replay_progress": {"configurations_considered_count": 25},
        },
        "pass_condition_status": {
            "status": "NO_GO",
            "conditions": [{"id": "a", "label": "A", "status": "PASSED", "evidence": {"large": True}}],
        },
    }
    (base / "operator_dashboard_payload.json").write_text(json.dumps(dashboard), encoding="utf-8")
    monkeypatch.setattr(market_contracts, "_public_root", lambda: public_root)
    market_contracts.ADAPTIVE_CAPITAL_COMPACT_CACHE.update({"signature": None, "payload": None, "timestamp": None})

    payload, source, timestamp = market_contracts._adaptive_capital_compact_payload()

    assert payload is not None
    assert source == "operator_runtime/v2_adaptive_capital_productivity/latest/compact"
    assert timestamp == "2026-06-21T23:11:51Z"
    assert payload["operator_go_readiness"]["evidence_to_go"]["closed_outcomes_needed"] == 0
    assert payload["capital_productivity_runtime_status"]["capital_productivity_progress"]["current_closed_outcome_count"] == 44
    assert "evidence_acquisition_status" not in payload["capital_productivity_runtime_status"]["capital_productivity_progress"]
    accuracy = payload["signal_prediction_accuracy_status"]
    assert accuracy["evaluated_row_count"] == 1641
    assert accuracy["by_symbol_timeframe"] == [{"symbol": "BTCUSDT", "timeframe": "1m", "evaluated_count": 3}]
    assert "sample_evaluated_rows" not in accuracy
    assert "missing_selection_attribution_sample" not in payload["adaptive_capital_policy_status"]["adaptive_field_selection_evidence"]
    assert "evidence" not in payload["pass_condition_status"]["conditions"][0]


def test_adaptive_capital_compact_payload_uses_signal_rows_when_accuracy_collapses_to_zero(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_root = tmp_path / "public"
    adaptive_base = public_root / "operator_runtime/v2_adaptive_capital_productivity/latest"
    signal_base = public_root / "operator_runtime/v2_signals/latest"
    adaptive_base.mkdir(parents=True)
    signal_base.mkdir(parents=True)
    dashboard = {
        "generated_utc": "2026-06-21T23:51:37Z",
        "overall_status": "NO_GO",
        "capital_productivity_runtime_status": {
            "status": "NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE",
            "signal_prediction_accuracy_status": {
                "status": "NO_SIGNAL_OR_PREDICTION_ROWS",
                "source_row_count": 0,
                "evaluated_row_count": 0,
                "symbol_universe_count": 0,
                "by_symbol_timeframe": [],
            },
        },
        "adaptive_capital_policy_status": {"status": "PASSED"},
        "counterfactual_capital_sweep_status": {"status": "PASSED"},
    }
    signal_runtime = {
        "generated_utc": "2026-06-21T23:56:24Z",
        "status": "ALL_SYMBOL_ALL_TIMEFRAME_CUDA_PREDICTIONS_BLOCKED_OR_PARTIAL",
        "prediction_rows": [
            {"symbol": "BTCUSDT", "timeframe": "1m", "status": "STALE_TF_PREDICTION"},
            {"symbol": "ETHUSDT", "timeframe": "5m", "status": "STALE_TF_PREDICTION"},
        ],
    }
    (adaptive_base / "operator_dashboard_payload.json").write_text(json.dumps(dashboard), encoding="utf-8")
    (signal_base / "all_symbol_all_timeframe_cuda_prediction_status.json").write_text(json.dumps(signal_runtime), encoding="utf-8")
    monkeypatch.setattr(market_contracts, "_public_root", lambda: public_root)
    market_contracts.ADAPTIVE_CAPITAL_COMPACT_CACHE.update({"signature": None, "payload": None, "timestamp": None})

    payload, _, _ = market_contracts._adaptive_capital_compact_payload()

    assert payload is not None
    accuracy = payload["signal_prediction_accuracy_status"]
    assert accuracy["source_row_count"] == 2
    assert accuracy["prediction_rows_count"] == 2
    assert accuracy["evaluated_row_count"] == 0
    assert accuracy["symbol_universe_count"] == 2
    assert len(accuracy["by_symbol_timeframe"]) == 2
    assert payload["capital_productivity_runtime_status"]["signal_prediction_accuracy_status"]["source_row_count"] == 2


@pytest.mark.asyncio
async def test_readonly_resource_direct_payload_routes_liquidation_heatmap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_heatmap(symbols=None, timeframes=None, actor=None) -> dict:
        return {
            "data": {"rows": [{"symbol": "BTCUSDT", "timeframe": "5m"}]},
            "source": "unit-test",
            "source_type": "repository",
            "endpoint": "/api/v2/liquidation/levels-heatmap",
            "missing_fields": [],
            "warnings": [],
            "mode": "read_only",
        }

    monkeypatch.setattr(market_contracts, "get_liquidation_levels_heatmap", fake_heatmap)

    handled, payload = await market_contracts._readonly_resource_direct_payload(
        "/api/v2/liquidation/levels-heatmap?symbols=BTCUSDT&timeframes=5m"
    )

    assert handled is True
    assert payload["data"]["rows"] == [{"symbol": "BTCUSDT", "timeframe": "5m"}]
    assert payload["source_type"] == "repository"


@pytest.mark.asyncio
async def test_readonly_resource_direct_payload_reads_allowed_static_json(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    static_path = tmp_path / "v2" / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest"
    static_path.mkdir(parents=True)
    (static_path / "current_signal_lineage.json").write_text(json.dumps({"signal_id": "sig-1"}), encoding="utf-8")

    handled, payload = await market_contracts._readonly_resource_direct_payload(
        "/operator_runtime/paper_online/latest/current_signal_lineage.json"
    )

    assert handled is True
    assert payload == {"signal_id": "sig-1"}


@pytest.mark.asyncio
async def test_readonly_resource_direct_payload_preserves_auth_scoped_fallback() -> None:
    handled, payload = await market_contracts._readonly_resource_direct_payload(
        "/api/v2/portfolio",
        {"cookie": "session=abc"},
    )

    assert handled is False
    assert payload is None


@pytest.mark.asyncio
async def test_liquidation_heatmap_uses_runtime_status_fallback_when_redis_empty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(market_contracts, "get_redis", lambda: None)
    runtime_path = tmp_path / "v2" / "frontend" / "public" / "operator_runtime" / "v2_liquidation_runtime_status" / "latest"
    runtime_path.mkdir(parents=True)
    (runtime_path / "v2_liquidation_runtime_status.json").write_text(
        json.dumps(
            {
                "generated_utc": "2026-06-21T23:03:27Z",
                "btc_long_level": 63696.17931012,
                "btc_short_level": 63791.67583082,
                "btc_long_distance_pct": 0.0392,
                "btc_short_distance_pct": 0.1892,
                "liquidation_events_xlen": 10010,
            }
        ),
        encoding="utf-8",
    )

    payload = await market_contracts.get_liquidation_levels_heatmap(symbols="BTCUSDT", timeframes="5m", actor=None)

    assert payload["source_type"] == "static_payload"
    assert payload["mode"] == "read_only"
    assert payload["missing_fields"] == []
    assert payload["data"]["count"] == 1
    assert payload["data"]["rows"][0]["symbol"] == "BTCUSDT"
    assert payload["data"]["rows"][0]["nearest_above"] == pytest.approx(63791.67583082)
    assert "runtime-status fallback" in " ".join(payload["warnings"])


def _sample_paper_activity_payload() -> tuple[dict, list[str]]:
    return {
        "positions": [{"symbol": "BTCUSDT", "quantity": 1.0}],
        "orders": [{"symbol": "BTCUSDT", "status": "FILLED"}],
        "open_orders": [],
        "executions": [{"symbol": "BTCUSDT", "fill_price": 100.0}],
        "fills": [{"symbol": "BTCUSDT", "fill_price": 100.0}],
        "audit_events": [{"event_type": "PAPER_FILL_ACCEPTED", "tamper_evident": True, "event_hash": "abc"}],
        "summary": {"open_position_count": 1},
    }, ["sample warning"]


class _FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values
        self.get_calls: list[str] = []

    def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        value = self.values.get(key)
        return json.dumps(value) if value is not None else None

    def keys(self, pattern: str) -> list[str]:
        import fnmatch

        return [key for key in self.values if fnmatch.fnmatch(key, pattern)]


@pytest.mark.asyncio
async def test_paper_runtime_status_exposes_owner_and_cost_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "v2:paper:heartbeat": {
            "worker_id": "v2_trade_management_paper_loop",
            "heartbeat_generated_at": "2026-06-27T20:50:00Z",
            "cycle_state": "COMPLETED_CYCLE",
            "candidate_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
            "policy_id": "challenger_v2_cuda_exitless_83d35e31eea385da1a283b8e",
            "paper_policy_owner": "challenger_v2",
            "current_allowed_paper_owner": "challenger_v2",
            "policy_fingerprint": "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630",
            "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
            "intents_built": 3,
            "intents_accepted": 1,
            "intents_blocked": 2,
            "writes_legacy_redis": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "paper_owner_attribution_status": {
                "status": "PASS_CURRENT_RUNTIME_OWNER_ATTRIBUTION_NO_ACCEPTED_FILLS",
                "accepted_fill_status": "NO_CURRENT_ACCEPTED_ROWS_TO_VERIFY",
                "current_runtime_row_count": 3,
                "current_runtime_complete_count": 3,
                "current_runtime_incomplete_count": 0,
                "current_runtime_owner_contract_passed": True,
            },
        },
        "v2:paper:trade_management:status": {
            "paper_runtime_admission_status": {
                "intents_built": 3,
                "accepted_count": 1,
                "blocked_count": 2,
            },
            "paper_runtime_cost_capture_status": {
                "paper_intent_rows": 3,
                "order_cost_applicable_rows": 2,
                "production_grade_cost_rows": 1,
                "production_grade_cost_order_applicable_rows": 1,
                "production_grade_cost_coverage": 0.5,
                "production_grade_cost_total_row_coverage": 1 / 3,
                "no_order_explained_rows": 1,
                "no_order_missing_cost_rows": 1,
                "unexplained_missing_cost_rows": 1,
                "paper_fill_allowed_rows": 1,
                "routes_to_live": False,
                "places_real_order": False,
                "routes_to_live_rows": 0,
                "places_real_order_rows": 0,
            },
        },
        "v2:paper:b_grade_canary_supply_status": {
            "schema_version": "paper_b_grade_canary_supply_status_v1",
            "status": "BLOCKED_ZERO_B_GRADE_CANARY_SUPPLY",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "canary_candidates": 0,
            "canary_intents": 0,
            "canary_pending_rows": 0,
            "predicate_counts": {
                "production_grade_cost_rows": 3,
                "risk_gateway_decision_rows": 3,
                "risk_pass_rows": 0,
                "orchestrator_rows": 3,
                "strategy_entry_evidence_rows": 0,
                "paper_only_safety_rows": 3,
            },
            "root_cause_counts": {
                "risk_failed": 3,
                "strategy_failed": 3,
                "unsafe_live_route_flags": 0,
            },
            "sample_canary_candidates": [
                {"symbol": "BTCUSDT", "large_runtime_row": {"nested": ["omitted"] * 20}},
            ],
        },
        "v2:paper:forward_canary_evidence_status": {
            "schema_version": "paper_forward_canary_evidence_status_v1",
            "status": "BLOCKED_FORWARD_CANARY_EVIDENCE_INCOMPLETE",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "required_forward_canary_economic_outcomes": 100,
            "archived_b_grade_challenger_closed_outcome_rows": 1099,
            "b_grade_challenger_closed_outcome_rows": 20,
            "pre_cutover_b_grade_challenger_closed_outcome_rows": 1079,
            "valid_forward_canary_economic_outcomes": 20,
            "post_cutover_valid_forward_canary_economic_outcomes": 20,
            "valid_symbol_count": 11,
            "valid_side_counts": {"long": 2, "short": 18},
            "production_grade_cost_coverage": 1.0,
            "cutover_completed_at": "2026-06-29T03:57:38.333Z",
            "sample_valid_forward_canary_outcomes": [
                {"symbol": "BTCUSDT", "realized_pnl_bps": 12.5},
            ],
        },
        "v2:signals:latest:BTCUSDT:1m": {
            "signal_id": "sig-test",
            "prediction_id": "pred-test",
            "feature_snapshot_id": "feature-test",
            "action": "long",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "available_at": "2026-06-27T20:49:00Z",
        },
        "v2:risk:gateway:heartbeat": {
            "classification": "V2_RISK_GATEWAY_LIVE_OK",
            "profile_id": "paper-only",
        },
    }
    client = _FakeRedis(values)

    def fail_keys(_pattern: str) -> list[str]:
        raise AssertionError("paper runtime status must not use Redis KEYS")

    client.keys = fail_keys  # type: ignore[method-assign]
    monkeypatch.setattr(market_contracts, "get_redis", lambda: client)
    monkeypatch.setattr(market_contracts, "_utc_now", lambda: "2026-06-27T20:50:10Z")

    payload = await market_contracts.get_paper_runtime_status(actor=None)

    assert payload["runtime"] == "v2_trade_management_paper_loop"
    assert payload["legacy_redis_writes"] is False
    assert payload["exchange_orders"] is False
    loop = payload["paper_loop"]
    assert loop["paper_policy_owner"] == "challenger_v2"
    assert loop["policy_fingerprint"] == "83d35e31eea385da1a283b8efab3102ac292be2904724d11777f2b7a32e68630"
    assert loop["model_source"] == "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
    assert loop["paper_only"] is True
    assert loop["routes_to_live"] is False
    assert loop["places_real_order"] is False
    owner_status = loop["paper_owner_attribution_status"]
    assert owner_status["status"] == "PASS_CURRENT_RUNTIME_OWNER_ATTRIBUTION_NO_ACCEPTED_FILLS"
    assert owner_status["current_runtime_row_count"] == 3
    assert owner_status["current_runtime_owner_contract_passed"] is True
    assert loop["production_grade_cost_rows"] == 1
    assert loop["order_cost_applicable_rows"] == 2
    assert loop["production_grade_cost_order_applicable_rows"] == 1
    assert loop["production_grade_cost_coverage"] == pytest.approx(1 / 2)
    assert loop["production_grade_cost_coverage_basis"] == "order_applicable_rows"
    assert loop["production_grade_cost_total_row_coverage"] == pytest.approx(1 / 3)
    assert loop["no_order_explained_rows"] == 1
    assert loop["no_order_missing_cost_rows"] == 1
    assert loop["unexplained_missing_cost_rows"] == 1
    assert loop["paper_fill_allowed_rows"] == 1
    assert loop["routes_to_live_rows"] == 0
    assert loop["places_real_order_rows"] == 0
    canary_supply = loop["b_grade_canary_supply_status"]
    assert canary_supply["source"] == "redis:v2:paper:b_grade_canary_supply_status"
    assert canary_supply["available"] is True
    assert canary_supply["status"] == "BLOCKED_ZERO_B_GRADE_CANARY_SUPPLY"
    assert canary_supply["canary_candidates"] == 0
    assert canary_supply["canary_intents"] == 0
    assert canary_supply["canary_pending_rows"] == 0
    assert canary_supply["routes_to_live"] is False
    assert canary_supply["places_real_order"] is False
    assert canary_supply["counts_as_a_grade_evidence"] is False
    assert canary_supply["predicate_counts"]["production_grade_cost_rows"] == 3
    assert canary_supply["predicate_counts"]["risk_pass_rows"] == 0
    assert canary_supply["root_cause_counts"]["risk_failed"] == 3
    assert canary_supply["sample_rows_omitted_from_api"] is True
    assert canary_supply["sample_canary_candidates_count"] == 1
    assert "sample_canary_candidates" not in canary_supply
    forward_canary = loop["paper_forward_canary_evidence_status"]
    assert forward_canary["source"] == "redis:v2:paper:forward_canary_evidence_status"
    assert forward_canary["available"] is True
    assert forward_canary["status"] == "BLOCKED_FORWARD_CANARY_EVIDENCE_INCOMPLETE"
    assert forward_canary["archived_b_grade_challenger_closed_outcome_rows"] == 1099
    assert forward_canary["b_grade_challenger_closed_outcome_rows"] == 20
    assert forward_canary["pre_cutover_b_grade_challenger_closed_outcome_rows"] == 1079
    assert forward_canary["post_cutover_valid_forward_canary_economic_outcomes"] == 20
    assert forward_canary["valid_symbol_count"] == 11
    assert forward_canary["valid_side_counts"] == {"long": 2, "short": 18}
    assert forward_canary["production_grade_cost_coverage"] == 1.0
    assert forward_canary["cutover_completed_at"] == "2026-06-29T03:57:38.333Z"
    assert forward_canary["counts_as_a_grade_evidence"] is False
    assert forward_canary["sample_rows_omitted_from_api"] is True
    assert forward_canary["sample_valid_forward_canary_outcomes_count"] == 1
    assert "sample_valid_forward_canary_outcomes" not in forward_canary
    assert payload["current_signal_lineage"]["lineage_ids"]["prediction_id"] == "pred-test"
    assert payload["current_signal_lineage"]["lineage_ids"]["signal_id"] == "sig-test"
    assert any(blocker["id"] == "B_GRADE_CANARY_SUPPLY_ZERO" for blocker in payload["blockers"])
    assert any(blocker["id"] == "FORWARD_CANARY_EVIDENCE_NOT_READY" for blocker in payload["blockers"])
    assert "v2:paper:intents" not in client.get_calls


@pytest.mark.asyncio
async def test_paper_runtime_status_preserves_explicit_zero_cost_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "v2:paper:heartbeat": {
            "worker_id": "v2_trade_management_paper_loop",
            "heartbeat_generated_at": "2026-06-27T20:50:00Z",
            "cycle_state": "COMPLETED_CYCLE",
            "paper_policy_owner": "challenger_v2",
            "writes_legacy_redis": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "v2:paper:trade_management:status": {
            "paper_runtime_admission_status": {
                "intents_built": 3,
                "accepted_count": 2,
            },
            "paper_runtime_cost_capture_status": {
                "paper_intent_rows": 3,
                "order_cost_applicable_rows": 0,
                "production_grade_cost_rows": 0,
                "production_grade_cost_order_applicable_rows": 0,
                "production_grade_cost_coverage": 0.0,
                "production_grade_cost_total_row_coverage": 0.0,
                "no_order_explained_rows": 3,
                "no_order_missing_cost_rows": 3,
                "unexplained_missing_cost_rows": 0,
                "paper_fill_allowed_rows": 0,
                "routes_to_live_rows": 0,
                "places_real_order_rows": 0,
            },
            "paper_a_grade_gate_burndown_status": {
                "prediction_rows": 3,
                "production_grade_cost_rows": 3,
                "predicate_counts": {
                    "production_grade_cost_rows": 3,
                },
            },
        },
        "v2:paper:b_grade_canary_supply_status": {
            "schema_version": "paper_b_grade_canary_supply_status_v1",
            "status": "B_GRADE_CANARY_PENDING_SUPPLY_PRESENT",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "canary_candidates": 0,
            "canary_intents": 0,
            "canary_pending_rows": 0,
        },
    }
    client = _FakeRedis(values)
    monkeypatch.setattr(market_contracts, "get_redis", lambda: client)
    monkeypatch.setattr(market_contracts, "_utc_now", lambda: "2026-06-27T20:50:10Z")

    payload = await market_contracts.get_paper_runtime_status(actor=None)

    loop = payload["paper_loop"]
    assert loop["order_cost_applicable_rows"] == 0
    assert loop["production_grade_cost_rows"] == 0
    assert loop["production_grade_cost_order_applicable_rows"] == 0
    assert loop["production_grade_cost_coverage"] == 0.0
    assert loop["production_grade_cost_coverage_basis"] == (
        "all_intent_rows_no_order_applicable"
    )
    assert loop["production_grade_cost_total_row_coverage"] == 0.0
    assert loop["paper_fill_allowed_rows"] == 0
    assert loop["routes_to_live_rows"] == 0
    assert loop["places_real_order_rows"] == 0
    assert "v2:paper:intents" not in client.get_calls


@pytest.mark.asyncio
async def test_paper_runtime_status_repairs_zero_denominator_cost_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "v2:paper:heartbeat": {
            "worker_id": "v2_trade_management_paper_loop",
            "heartbeat_generated_at": "2026-06-27T20:50:00Z",
            "cycle_state": "COMPLETED_CYCLE",
            "paper_policy_owner": "challenger_v2",
            "writes_legacy_redis": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "v2:paper:trade_management:status": {
            "paper_runtime_admission_status": {
                "intents_built": 3,
                "accepted_count": 0,
            },
            "paper_runtime_cost_capture_status": {
                "paper_intent_rows": 3,
                "order_cost_applicable_rows": 0,
                "production_grade_cost_rows": 2,
                "production_grade_cost_order_applicable_rows": 0,
                "production_grade_cost_coverage": 0.0,
                "production_grade_cost_total_row_coverage": 2 / 3,
                "no_order_explained_rows": 3,
                "no_order_missing_cost_rows": 1,
                "unexplained_missing_cost_rows": 0,
                "paper_fill_allowed_rows": 0,
                "routes_to_live_rows": 0,
                "places_real_order_rows": 0,
            },
        },
        "v2:paper:b_grade_canary_supply_status": {
            "schema_version": "paper_b_grade_canary_supply_status_v1",
            "status": "B_GRADE_CANARY_PENDING_SUPPLY_PRESENT",
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
        },
    }
    client = _FakeRedis(values)
    monkeypatch.setattr(market_contracts, "get_redis", lambda: client)
    monkeypatch.setattr(market_contracts, "_utc_now", lambda: "2026-06-27T20:50:10Z")

    payload = await market_contracts.get_paper_runtime_status(actor=None)

    loop = payload["paper_loop"]
    assert loop["order_cost_applicable_rows"] == 0
    assert loop["production_grade_cost_rows"] == 2
    assert loop["production_grade_cost_coverage"] == pytest.approx(2 / 3)
    assert loop["production_grade_cost_coverage_basis"] == (
        "all_intent_rows_no_order_applicable_api_repaired"
    )
    assert loop["production_grade_cost_total_row_coverage"] == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_paper_runtime_status_exposes_mixed_case_a_grade_burndown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = {
        "v2:paper:heartbeat": {
            "worker_id": "v2_trade_management_paper_loop",
            "heartbeat_generated_at": "2026-06-27T20:50:00Z",
            "cycle_state": "COMPLETED_CYCLE",
            "paper_policy_owner": "challenger_v2",
            "writes_legacy_redis": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "v2:paper:trade_management:status": {
            "paper_runtime_admission_status": {
                "intents_built": 7,
                "accepted_count": 0,
            },
            "paper_runtime_cost_capture_status": {
                "paper_intent_rows": 7,
                "order_cost_applicable_rows": 7,
                "production_grade_cost_rows": 7,
                "production_grade_cost_order_applicable_rows": 7,
                "production_grade_cost_coverage": 1.0,
                "production_grade_cost_total_row_coverage": 1.0,
                "paper_fill_allowed_rows": 0,
                "routes_to_live_rows": 0,
                "places_real_order_rows": 0,
            },
            "paper_a_grade_gate_burndown_status": {
                "A_grade_rows": 9,
                "near_A_grade_rows": 9,
            },
        },
        "v2:paper:a_grade_gate_burndown_status": {
            "schema_version": "paper_a_grade_gate_burndown_status_v1",
            "candidate_rows": 7,
            "A_grade_rows": 0,
            "near_A_grade_rows": 2,
            "source_tier_a_grade_execution_rows": 0,
            "predicate_counts": {
                "allocator_pass_rows": 0,
                "production_grade_cost_rows": 7,
                "risk_pass_rows": 0,
            },
            "guardian_gate_status": {
                "status": "A_GRADE_HALTED_PERFORMANCE",
                "a_grade_new_entries_allowed": False,
                "block_all_new_a_grade_entries": True,
                "failure_reasons": [
                    {
                        "reason": "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES",
                        "observed": 0,
                        "required": 1000,
                    },
                ],
            },
            "sample_near_a_grade_rows": [{"prediction_id": "pred-near"}],
        },
    }
    client = _FakeRedis(values)
    monkeypatch.setattr(market_contracts, "get_redis", lambda: client)
    monkeypatch.setattr(market_contracts, "_utc_now", lambda: "2026-06-27T20:50:10Z")

    payload = await market_contracts.get_paper_runtime_status(actor=None)

    loop = payload["paper_loop"]
    assert loop["a_grade_rows"] == 0
    assert loop["near_a_grade_rows"] == 2
    assert loop["source_tier_a_grade_execution_rows"] == 0
    assert loop["guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert loop["guardian_new_entries_allowed"] is False
    assert loop["guardian_block_all_new_a_grade_entries"] is True
    assert loop["a_grade_predicate_counts"]["allocator_pass_rows"] == 0

    burndown = loop["paper_a_grade_gate_burndown_status"]
    assert burndown["source"] == "redis:v2:paper:a_grade_gate_burndown_status"
    assert burndown["available"] is True
    assert burndown["A_grade_rows"] == 0
    assert burndown["a_grade_rows"] == 0
    assert burndown["near_A_grade_rows"] == 2
    assert burndown["near_a_grade_rows"] == 2
    assert burndown["guardian_failure_reason_count"] == 1
    assert burndown["sample_near_a_grade_rows_count"] == 1
    assert "sample_near_a_grade_rows" not in burndown
    assert any(blocker["id"] == "A_GRADE_SUPPLY_ZERO" for blocker in payload["blockers"])
    assert "v2:paper:intents" not in client.get_calls


@pytest.mark.asyncio
async def test_filtered_signals_matrix_reads_exact_keys_without_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "v2:signals:paper:BTCUSDT:1m": {
            "action": "LONG",
            "confidence": 0.84,
            "generated_utc": "2026-06-22T01:00:00Z",
            "expected_move_after_cost_bps": 12.5,
        }
    }
    monkeypatch.setattr(market_contracts, "get_redis", lambda: _FakeRedis(values))
    monkeypatch.setattr(market_contracts, "SIGNALS_MATRIX_CACHE_TTL_SECONDS", 0.0)

    def fail_scan(_prefix: str, _match: str) -> list[str]:
        raise AssertionError("filtered matrix requests should not scan Redis")

    monkeypatch.setattr(market_contracts, "_scan_redis_prefix", fail_scan)
    with market_contracts.SIGNALS_MATRIX_CACHE_LOCK:
        market_contracts.SIGNALS_MATRIX_CACHE.clear()

    payload = await market_contracts.get_signals_matrix(
        symbols="BTCUSDT,ETHUSDT",
        timeframes="1m,5m",
        actor=None,
    )

    assert payload["source"] == "Redis signal publisher (matrix direct lookup/cache)"
    assert payload["data"]["count"] == 1
    assert payload["data"]["rows"][0]["symbol"] == "BTCUSDT"
    assert payload["data"]["rows"][0]["timeframe"] == "1m"
    assert "BTCUSDT:5m" in payload["data"]["missing"]
    assert "ETHUSDT:1m" in payload["data"]["missing"]


@pytest.mark.asyncio
async def test_filtered_predictions_matrix_reads_exact_keys_without_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "v2:prediction:BTCUSDT:1m": {
            "action_labels": ["hold", "long", "short"],
            "action_probabilities": [0.1, 0.82, 0.08],
            "confidence_calibrated": 0.82,
            "data_coverage_percent": 96.0,
            "generated_utc": "2026-06-22T01:00:00Z",
            "checkpoint_id": "ckpt-live-read",
        }
    }
    monkeypatch.setattr(market_contracts, "get_redis", lambda: _FakeRedis(values))
    monkeypatch.setattr(market_contracts, "PREDICTIONS_MATRIX_CACHE_TTL_SECONDS", 0.0)

    def fail_scan(_prefix: str, _match: str) -> list[str]:
        raise AssertionError("filtered prediction matrix requests should not scan Redis")

    monkeypatch.setattr(market_contracts, "_scan_redis_prefix", fail_scan)
    with market_contracts.PREDICTIONS_MATRIX_CACHE_LOCK:
        market_contracts.PREDICTIONS_MATRIX_CACHE.clear()

    payload = await market_contracts.get_predictions_matrix(
        symbols="BTCUSDT,ETHUSDT",
        timeframes="1m,5m",
        actor=None,
    )

    assert payload["source"] == "Redis trainer prediction publisher (matrix direct lookup/cache)"
    assert payload["data"]["count"] == 1
    assert payload["data"]["rows"][0]["symbol"] == "BTCUSDT"
    assert payload["data"]["rows"][0]["timeframe"] == "1m"
    assert payload["data"]["rows"][0]["top_action"] == "long"
    assert "BTCUSDT:5m" in payload["data"]["missing"]
    assert "ETHUSDT:1m" in payload["data"]["missing"]


@pytest.mark.asyncio
async def test_signals_matrix_uses_runtime_prediction_fallback_when_redis_empty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public_root = tmp_path / "public"
    runtime_dir = public_root / "operator_runtime" / "v2_signals" / "latest"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "all_symbol_all_timeframe_cuda_prediction_status.json").write_text(
        json.dumps(
            {
                "generated_est": "2026-06-22T01:00:00Z",
                "prediction_rows": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "selected_action": "long",
                        "confidence_calibrated": 0.72,
                        "data_coverage_percent": 91.0,
                        "market_state_integrity_score": 98.0,
                        "available_at": "2026-06-22T00:59:30Z",
                        "prediction_id": "pred-btc",
                        "price_target": 65000,
                        "price_target_after_cost": 64950,
                        "expected_move_after_cost_bps": 18.0,
                        "paper_fill_allowed": False,
                        "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
                        "live_gate": "blocked_human_only",
                    },
                    {
                        "symbol": "ETHUSDT",
                        "timeframe": "5m",
                        "selected_action": "hold",
                        "confidence_calibrated": 0.61,
                        "available_at": "2026-06-22T00:58:30Z",
                        "prediction_id": "pred-eth",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_contracts, "_public_root", lambda: public_root)
    monkeypatch.setattr(market_contracts, "get_redis", lambda: _FakeRedis({}))
    monkeypatch.setattr(market_contracts, "SIGNALS_MATRIX_CACHE_TTL_SECONDS", 0.0)
    with market_contracts.SIGNALS_MATRIX_CACHE_LOCK:
        market_contracts.SIGNALS_MATRIX_CACHE.clear()

    payload = await market_contracts.get_signals_matrix(
        symbols="BTCUSDT,ETHUSDT",
        timeframes="1m,5m",
        actor=None,
    )

    assert payload["source"] == "Runtime prediction signal matrix fallback"
    assert payload["source_type"] == "static_payload"
    assert payload["timestamp"] == "2026-06-22T01:00:00Z"
    assert payload["data"]["count"] == 2
    btc = next(row for row in payload["data"]["rows"] if row["symbol"] == "BTCUSDT")
    assert btc["confidence"] == pytest.approx(0.72)
    assert btc["price_target_after_cost"] == pytest.approx(64950)
    assert btc["paper_fill_status"] == "gated"
    assert "ETHUSDT:1m" in payload["data"]["missing"]


def test_paper_live_market_price_reads_direct_binance_funding_mark() -> None:
    now_ms = int(time.time() * 1000)
    client = _FakeRedis(
        {
            "v2:market:funding:ALLOUSDT": {
                "symbol": "ALLOUSDT",
                "markPrice": "0.39324493",
                "time": now_ms,
            }
        }
    )

    mark = market_contracts._paper_live_market_price(client, "ALLOUSDT")

    assert mark["price"] == pytest.approx(0.39324493)
    assert mark["source"] == "v2:market:funding:ALLOUSDT.markPrice"
    assert mark["source_key"] == "v2:market:funding:ALLOUSDT"


def test_paper_position_enrichment_prefers_fresher_stored_mark_over_stale_external_mark() -> None:
    stale_ms = int((time.time() - 120) * 1000)
    client = _FakeRedis(
        {
            "v2:market:orderbook:binance:ALLOUSDT": {
                "T": stale_ms,
                "bids": [["102.0", "1"]],
                "asks": [["102.2", "1"]],
            }
        }
    )

    positions, metrics = market_contracts._enrich_paper_positions(
        client,
        [
            {
                "symbol": "ALLOUSDT",
                "side": "LONG",
                "avg_entry_price": 100.0,
                "net_quantity": 1.0,
                "last_mark_price": 101.0,
                "last_mark_est": market_contracts._utc_now(),
            }
        ],
        max_leverage=1.0,
    )

    assert positions[0]["last_mark_price"] == 101.0
    assert positions[0]["mark_price_source"] == "v2:paper:positions.last_mark_price"
    assert positions[0]["unrealized_pnl"] == 1.0
    assert metrics["stale_mark_price_count"] == 0
    assert metrics["missing_mark_price_count"] == 0


def test_paper_activity_payload_returns_structured_empty_state_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(market_contracts, "get_redis", lambda: None)

    payload, warnings = market_contracts._load_paper_activity_payload()

    assert payload["positions"] == []
    assert payload["fills"] == []
    assert payload["orders"] == []
    assert payload["summary"]["position_source_status"] == "redis_unavailable"
    assert payload["summary"]["mark_to_market_live"] is False
    assert warnings == ["Redis unavailable for paper activity; returned structured empty paper state"]


@pytest.mark.asyncio
async def test_public_account_positions_use_live_paper_activity_fallback(monkeypatch) -> None:
    monkeypatch.setattr(market_contracts, "_load_paper_activity_payload", _sample_paper_activity_payload)

    payload = await market_contracts.get_account_positions(None)

    assert payload["source_type"] == "redis_live"
    assert payload["data"]["positions"] == [{"symbol": "BTCUSDT", "quantity": 1.0}]
    assert payload["data"]["account_scope"] == "public_read_only"
    assert payload["missing_fields"] == []
    assert "Live trading remains disabled" in payload["warnings"]


@pytest.mark.asyncio
async def test_public_execution_orders_use_live_paper_activity_fallback(monkeypatch) -> None:
    monkeypatch.setattr(market_contracts, "_load_paper_activity_payload", _sample_paper_activity_payload)

    payload = await market_contracts.get_execution_orders(None)

    assert payload["source_type"] == "redis_live"
    assert payload["data"]["orders"] == [{"symbol": "BTCUSDT", "status": "FILLED"}]
    assert payload["data"]["account_specific"] is False
    assert payload["missing_fields"] == []
    assert "Public paper activity order fallback; no exchange transport is enabled" in payload["warnings"]


@pytest.mark.asyncio
async def test_public_executions_use_live_paper_activity_fallback(monkeypatch) -> None:
    monkeypatch.setattr(market_contracts, "_load_paper_activity_payload", _sample_paper_activity_payload)

    payload = await market_contracts.get_execution_executions(None)

    assert payload["source_type"] == "redis_live"
    assert payload["data"]["executions"] == [{"symbol": "BTCUSDT", "fill_price": 100.0}]
    assert payload["data"]["fills"] == [{"symbol": "BTCUSDT", "fill_price": 100.0}]
    assert payload["missing_fields"] == []
    assert "Public paper activity execution fallback; paper fills are simulation only" in payload["warnings"]


@pytest.mark.asyncio
async def test_public_audit_events_use_live_paper_activity_fallback(monkeypatch) -> None:
    monkeypatch.setattr(market_contracts, "_load_paper_activity_payload", _sample_paper_activity_payload)

    payload = await market_contracts.get_execution_audit_events(None)

    assert payload["source_type"] == "redis_live"
    assert payload["data"]["audit_events"][0]["event_type"] == "PAPER_FILL_ACCEPTED"
    assert payload["data"]["audit_policy"]["live_trading_blocked"] is True
    assert payload["data"]["audit_ledger"]["live_mutation_prohibited"] is True
    assert payload["missing_fields"] == []
    assert "No exchange state is read or mutated" in payload["warnings"]


@pytest.mark.asyncio
async def test_risk_status_uses_current_runtime_artifact_fallback_when_redis_missing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(market_contracts, "get_redis", lambda: None)
    runtime_dir = tmp_path / "v2" / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest"
    runtime_dir.mkdir(parents=True)
    generated_at = market_contracts._utc_now()
    (runtime_dir / "paper_runtime_status.json").write_text(
        json.dumps({"generated_at": generated_at, "live_gate_status": "blocked_human_only"}),
        encoding="utf-8",
    )
    (runtime_dir / "risk_runtime_payload.json").write_text(
        json.dumps({
            "generated_at": generated_at,
            "risk_config_version": "risk-test-v1",
            "live_gate_status": "blocked_human_only",
            "daily_loss_limit_usdt": -75.0,
            "weekly_loss_limit_usdt": -250.0,
        }),
        encoding="utf-8",
    )
    (runtime_dir / "current_risk_decisions.json").write_text(
        json.dumps({
            "generated_at": generated_at,
            "decisions": [{
                "risk_decision_id": "risk-1",
                "signal_id": "sig-1",
                "risk_action": "deny",
                "risk_reason_code": "deny_canary_profile_tightening",
                "generated_at": generated_at,
                "canary_profile_tightening": {"symbol": "BTCUSDT", "action": "OPEN_LONG", "confidence": 0.81},
                "paper_edge_gate": {"fill_allowed": False, "classification": "EDGE_AFTER_COSTS_MISSING_BLOCK"},
                "live_blocked": True,
            }],
        }),
        encoding="utf-8",
    )

    payload = await market_contracts.get_risk_status()

    assert payload["source_type"] == "static_payload"
    assert payload["stale"] is False
    assert payload["missing_fields"] == []
    assert payload["data"]["heartbeat"]["worker_id"] == "paper_online_runtime"
    assert payload["data"]["latest_gateway_result"]["symbol"] == "BTCUSDT"
    assert payload["data"]["latest_gateway_result"]["side"] == "long"
    assert payload["data"]["denials_breakdown"] == {"deny_canary_profile_tightening": 1}


def test_native_public_market_stream_parser_emits_read_only_envelopes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_TELEMETRY_STORE",
        str(tmp_path / "market_stream_telemetry.json"),
    )
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE",
        str(tmp_path / "market_stream_alert_history.jsonl"),
    )
    market_contracts.MARKET_STREAM_TELEMETRY.clear()
    state: dict = {}

    _apply(
        state,
        "btcusdt@ticker",
        {
            "E": 1_700_000_000_000,
            "s": "BTCUSDT",
            "c": "65000.5",
            "P": "1.25",
            "h": "66000",
            "l": "64000",
            "v": "123.4",
            "q": "8010061.7",
            "b": "65000.0",
            "a": "65001.0",
        },
    )
    _apply(
        state,
        "btcusdt@depth20@100ms",
        {
            "E": 1_700_000_000_100,
            "b": [["65000.0", "0.5"]],
            "a": [["65001.0", "0.4"]],
        },
    )
    _apply(
        state,
        "btcusdt@aggTrade",
        {
            "E": 1_700_000_000_200,
            "T": 1_700_000_000_200,
            "p": "65000.5",
            "q": "0.01",
            "m": False,
        },
    )
    _apply(
        state,
        "btcusdt@kline_1m",
        {
            "E": 1_700_000_000_300,
            "k": {
                "t": 1_700_000_000_000,
                "T": 1_700_000_059_999,
                "o": "64900",
                "h": "65100",
                "l": "64800",
                "c": "65000.5",
                "v": "10",
                "q": "650005",
                "n": 12,
                "V": "5",
                "Q": "325002.5",
                "x": False,
            },
        },
    )

    snapshot = market_contracts._native_stream_snapshot("BTCUSDT", state)
    market_contracts._record_market_stream_event(
        "BTCUSDT",
        source="binance_usdm_public_websocket_adapter",
        event="native_frame",
    )
    telemetry = market_contracts._market_stream_telemetry("BTCUSDT")

    assert snapshot["source"] == "binance_usdm_public_websocket_adapter"
    assert snapshot["mode"] == "read_only"
    assert snapshot["ticker"]["mode"] == "read_only"
    assert snapshot["ticker"]["data"]["change_24h"] == 0.0125
    assert snapshot["depth"]["data"]["depth_type"] == "binance_public_depth20_stream"
    assert snapshot["trades"]["data"]["trades"][0]["side"] == "buy"
    assert snapshot["candles"]["data"]["candles"][0]["is_final"] is False
    assert any("no exchange mutation" in warning for warning in snapshot["warnings"])
    assert any("display-only" in warning for warning in snapshot["candles"]["warnings"])
    assert telemetry["source"] == "binance_usdm_public_websocket_adapter"
    assert telemetry["native_frames"] >= 1
    assert telemetry["stale"] is False
    alert_history = market_contracts.read_market_stream_alert_history("BTCUSDT")
    assert alert_history[0]["public_market_data_only"] is True
    assert alert_history[0]["contains_credentials"] is False
    assert alert_history[0]["live_trading_enabled"] is False
    assert alert_history[0]["notification"]["configured"] is False
    assert alert_history[0]["notification"]["contains_credentials"] is False


def test_native_public_market_stream_parser_rejects_mismatched_symbol_and_timeframe() -> None:
    state: dict = {}
    matching = market_contracts._apply_native_stream_message(
        raw=json.dumps(
            {
                "stream": "btcusdt@kline_1m",
                "data": {
                    "E": 1_700_000_000_300,
                    "k": {
                        "t": 1_700_000_000_000,
                        "T": 1_700_000_059_999,
                        "o": "64900",
                        "h": "65100",
                        "l": "64800",
                        "c": "65000.5",
                        "v": "10",
                        "q": "650005",
                        "n": 12,
                        "V": "5",
                        "Q": "325002.5",
                        "x": False,
                    },
                },
            }
        ),
        state=state,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    wrong_symbol = market_contracts._apply_native_stream_message(
        raw=json.dumps({"stream": "ethusdt@kline_1m", "data": matching["data"]}),
        state=state,
        symbol="BTCUSDT",
        timeframe="1m",
    )
    wrong_timeframe = market_contracts._apply_native_stream_message(
        raw=json.dumps({"stream": "btcusdt@kline_5m", "data": matching["data"]}),
        state=state,
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert matching is not None
    assert wrong_symbol is None
    assert wrong_timeframe is None
    assert state["candles"]["data"]["candles"][0]["close"] == 65000.5


def test_native_public_market_stream_parser_rejects_invalid_kline_ohlc() -> None:
    state: dict = {}

    response = market_contracts._apply_native_stream_message(
        raw=json.dumps(
            {
                "stream": "btcusdt@kline_1m",
                "data": {
                    "E": 1_700_000_000_300,
                    "k": {
                        "t": 1_700_000_000_000,
                        "T": 1_700_000_059_999,
                        "o": "65000",
                        "h": "64900",
                        "l": "65100",
                        "c": "65050",
                        "v": "10",
                        "q": "650005",
                        "n": 12,
                        "V": "5",
                        "Q": "325002.5",
                        "x": False,
                    },
                },
            }
        ),
        state=state,
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert response is not None
    assert response["data"]["candles"] == []
    assert response["data"]["candle_count"] == 0
    assert "valid_ohlc" in response["missing_fields"]
    assert any("Invalid public kline frame ignored" in warning for warning in response["warnings"])


def test_market_stream_telemetry_persists_without_account_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_TELEMETRY_STORE",
        str(tmp_path / "market_stream_telemetry.json"),
    )
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE",
        str(tmp_path / "market_stream_alert_history.jsonl"),
    )
    market_contracts.MARKET_STREAM_TELEMETRY.clear()

    market_contracts._record_market_stream_event(
        "ETHUSDT",
        source="binance_usdm_public_websocket_adapter",
        event="connect_attempt",
    )
    market_contracts._record_market_stream_event(
        "ETHUSDT",
        source="binance_usdm_public_websocket_adapter",
        event="native_frame",
    )

    market_contracts.MARKET_STREAM_TELEMETRY.clear()
    restored = market_contracts._market_stream_telemetry("ETHUSDT")

    assert restored["symbol"] == "ETHUSDT"
    assert restored["source"] == "binance_usdm_public_websocket_adapter"
    assert restored["connect_attempts"] == 1
    assert restored["native_frames"] == 1
    assert restored["last_frame_at"] is not None
    assert "credential" not in json.dumps(restored).lower()
    assert "secret" not in json.dumps(restored).lower()
    alert_summary = market_contracts.market_stream_alert_history_summary("ETHUSDT")
    assert alert_summary["event_count"] >= 1
    assert alert_summary["public_market_data_only"] is True
    assert alert_summary["production_alerting_integrated"] is False
    assert alert_summary["notifier"]["configured"] is False


def test_market_stream_alert_webhook_notifier_sends_public_payload_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE",
        str(tmp_path / "market_stream_alert_history.jsonl"),
    )
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_URL", "https://alerts.example.local/hook?token=hidden")
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_ENABLED", "true")
    captured: dict[str, object] = {}

    class _Response:
        status = 202

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def _fake_urlopen(request: object, timeout: float) -> _Response:
        captured["timeout"] = timeout
        data = getattr(request, "data")
        captured["payload"] = json.loads(data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr("app.services.market_stream_alert_notifier.urllib.request.urlopen", _fake_urlopen)

    record = market_contracts.append_market_stream_alert_record(
        "BTCUSDT",
        {
            "symbol": "BTCUSDT",
            "source": "binance_usdm_public_websocket_adapter",
            "event": "native_error",
            "last_error": "ConnectionClosed",
            "stale": True,
            "lag_ms": 12000,
        },
    )
    notification = record["notification"]
    status = market_contracts.market_stream_alert_history_summary("BTCUSDT")["notifier"]
    encoded_status = json.dumps(status).lower()
    encoded_payload = json.dumps(captured["payload"]).lower()

    assert notification["configured"] is True
    assert notification["enabled"] is True
    assert notification["delivered"] is True
    assert notification["contains_credentials"] is False
    assert status["configured"] is True
    assert "alerts.example" not in encoded_status
    assert "hidden" not in encoded_status
    assert "api_key" not in encoded_payload
    assert "api_secret" not in encoded_payload
    assert "password_hash" not in encoded_payload
    assert captured["payload"]["public_market_data_only"] is True
    assert captured["payload"]["live_trading_enabled"] is False
    assert captured["payload"]["exchange_mutation_enabled"] is False


def test_market_stream_alert_webhook_skips_clear_stream_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE",
        str(tmp_path / "market_stream_alert_history.jsonl"),
    )
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_URL", "https://alerts.example.local/hook?token=hidden")
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_ENABLED", "true")

    def _unexpected_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("clear stream status should not send a webhook")

    monkeypatch.setattr("app.services.market_stream_alert_notifier.urllib.request.urlopen", _unexpected_urlopen)

    record = market_contracts.append_market_stream_alert_record(
        "BTCUSDT",
        {
            "symbol": "BTCUSDT",
            "source": "binance_usdm_public_websocket_adapter",
            "event": "native_frame",
            "last_frame_at": "2026-06-14T00:00:00Z",
            "stale": False,
            "lag_ms": 500,
        },
    )

    notification = record["notification"]
    assert record["alert_status"] == "clear"
    assert notification["configured"] is True
    assert notification["enabled"] is True
    assert notification["delivered"] is False
    assert notification["skipped_reason"] == "No active market stream alert."


def test_market_stream_alert_webhook_requires_https_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "ALPHAFORGE_MARKET_STREAM_ALERT_HISTORY_STORE",
        str(tmp_path / "market_stream_alert_history.jsonl"),
    )
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_URL", "http://alerts.example.local/hook")
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_ALERT_WEBHOOK_ENABLED", "true")

    def _unexpected_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("insecure webhook should not be called")

    monkeypatch.setattr("app.services.market_stream_alert_notifier.urllib.request.urlopen", _unexpected_urlopen)

    record = market_contracts.append_market_stream_alert_record(
        "BTCUSDT",
        {
            "symbol": "BTCUSDT",
            "source": "binance_usdm_public_websocket_adapter",
            "event": "native_error",
            "stale": True,
        },
    )

    notification = record["notification"]
    assert notification["configured"] is True
    assert notification["enabled"] is True
    assert notification["delivered"] is False
    assert notification["delivery_supported"] is False
    assert "HTTPS" in notification["last_error"]
