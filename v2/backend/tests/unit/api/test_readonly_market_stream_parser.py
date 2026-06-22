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
        (
            "/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "/operator_runtime/paper_online/latest/paper_runtime_status.json",
        ),
        (
            "/v2_8h_war_room/latest/operator_dashboard_payload.json?_rt=123",
            "/v2_8h_war_room/latest/operator_dashboard_payload.json?_rt=123",
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
    def __init__(self, values: dict[str, dict]) -> None:
        self.values = values

    def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return json.dumps(value) if value is not None else None


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
