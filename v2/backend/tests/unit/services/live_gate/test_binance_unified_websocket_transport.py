from __future__ import annotations

# ruff: noqa: S105,S106
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from v2.backend.app.services import binance_unified_websocket_transport as policy
from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_rest_fallback_decision,
    build_signed_ws_api_request,
    canonical_signature_payload,
    redact_ws_api_payload,
    resolve_binance_credential_binding,
    transport_policy_snapshot,
)
from v2.backend.app.services.live_gate.binance_live_order_transport import (
    BinanceUsdMLiveOrderTransport,
    BinanceUsdMWebSocketPrimaryTransport,
    LiveOrderCandidate,
)


def _candidate() -> LiveOrderCandidate:
    return LiveOrderCandidate(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.001,
        requested_notional_usdt=50.0,
        price_reference=50000.0,
        prediction_id="pred_1",
        risk_decision_id="risk_1",
        orchestrator_decision_id="orch_1",
        signal_id="sig_1",
        live_gate_audit_id="gate_1",
        risk_profile_audit_id="risk_profile_1",
        symbols_audit_id="symbols_1",
        final_approval_audit_id="approval_1",
        expected_move_after_cost_bps=20.0,
        confidence=0.75,
        source_generated_est="2026-06-16T10:00:00-04:00",
        position_side="LONG",
        best_bid=50000.0,
        best_ask=50001.0,
        symbol_filters={
            "tick_size": 0.1,
            "step_size": 0.001,
            "min_qty": 0.001,
            "min_notional": 5.0,
        },
        hedge_mode=True,
    )


def _clear_binance_env(monkeypatch: Any) -> None:
    for name in (
        "ALPHAFORGE_INITIAL_TRADER_ID",
        "ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF",
        "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY",
        "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "BINANCE_FUT_API_KEY",
        "BINANCE_FUT_API_SECRET",
        "BINANCE_SECRET_KEY",
        "BINANCE_LIVE_API_KEY",
        "BINANCE_LIVE_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def test_trader_wajid_scoped_credentials_resolve_from_env_file(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _clear_binance_env(monkeypatch)
    env_path = tmp_path / "v2/.env.local"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "\n".join(
            [
                "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY=scoped-key",
                "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET=scoped-secret",
                "BINANCE_API_KEY=generic-key",
                "BINANCE_API_SECRET=generic-secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    binding = resolve_binance_credential_binding(repo_root=tmp_path)

    assert binding.trader_id == "trader-wajidali1984"
    assert binding.credential_ref == "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY"
    assert binding.api_key == "scoped-key"
    assert binding.api_secret == "scoped-secret"
    assert binding.account_specific is True
    status_json = json.dumps(binding.safe_status())
    assert "scoped-key" not in status_json
    assert "scoped-secret" not in status_json
    assert binding.safe_status()["raw_credentials_exposed"] is False


def test_generic_binance_env_file_credentials_are_legacy_fallback(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _clear_binance_env(monkeypatch)
    env_path = tmp_path / "v2/.env.local"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("BINANCE_API_KEY=key\nBINANCE_API_SECRET=secret\n", encoding="utf-8")

    binding = resolve_binance_credential_binding(repo_root=tmp_path)

    assert binding.api_key == "key"
    assert binding.api_secret == "secret"
    assert binding.account_specific is False
    assert binding.safe_status()["key_names_used"] == {
        "api_key": "BINANCE_API_KEY",
        "api_secret": "BINANCE_API_SECRET",
    }


def test_signed_websocket_request_uses_sorted_params_and_redacts_secret_fields() -> None:
    params = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": "0.001",
        "newClientOrderId": "v2live123",
    }
    request = build_signed_ws_api_request(
        method="order.place",
        params=params,
        api_key="key",
        api_secret="secret",
        request_id="req_1",
        clock_ms=lambda: 1700000000000,
    )

    signable = dict(request["params"])
    signature = signable.pop("signature")
    expected = hmac.new(
        b"secret",
        canonical_signature_payload(signable).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert request["id"] == "req_1"
    assert request["method"] == "order.place"
    assert request["params"]["timestamp"] == 1700000000000
    assert signature == expected

    redacted = redact_ws_api_payload(request)
    redacted_json = json.dumps(redacted)
    assert "key" not in redacted_json
    assert signature not in redacted_json
    assert redacted["params"]["apiKey"] == "[redacted]"
    assert redacted["params"]["signature"] == "[redacted]"


def test_websocket_primary_transport_submits_order_place_with_fake_sender() -> None:
    sent: list[dict[str, Any]] = []

    def fake_sender(*, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        sent.append({"endpoint": endpoint, "payload": payload, "timeout": timeout})
        return {
            "ok": True,
            "status_code": 200,
            "error_type": None,
            "response": {
                "id": payload["id"],
                "status": 200,
                "result": {"clientOrderId": payload["params"]["newClientOrderId"]},
            },
        }

    transport = BinanceUsdMWebSocketPrimaryTransport(
        ws_api_url="wss://unit.test/ws-fapi/v1",
        ws_sender=fake_sender,
        clock_ms=lambda: 1700000000000,
    )
    result = transport.submit_market_order(
        candidate=_candidate(),
        api_key="key",
        api_secret="secret",
    )

    assert result["submitted"] is True
    assert result["endpoint"] == "WS order.place"
    assert result["rest_fallback_used"] is False
    assert sent[0]["endpoint"] == "wss://unit.test/ws-fapi/v1"
    assert sent[0]["payload"]["method"] == "order.place"
    params = sent[0]["payload"]["params"]
    assert params["type"] == "LIMIT"
    assert params["timeInForce"] == "GTX"
    assert params["positionSide"] == "LONG"
    assert params["selfTradePreventionMode"] == "EXPIRE_TAKER"
    assert params["newClientOrderId"].startswith("v2live")
    assert "reduceOnly" not in params
    serialized_result = json.dumps(result)
    assert "secret" not in serialized_result
    assert '"apiKey": "key"' not in serialized_result


def test_websocket_primary_transport_blocks_order_place_without_maker_context() -> None:
    sent: list[dict[str, Any]] = []

    def fake_sender(*, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        sent.append({"endpoint": endpoint, "payload": payload, "timeout": timeout})
        raise AssertionError("WebSocket sender should not run without maker context")

    transport = BinanceUsdMWebSocketPrimaryTransport(
        ws_api_url="wss://unit.test/ws-fapi/v1",
        ws_sender=fake_sender,
        clock_ms=lambda: 1700000000000,
    )
    candidate = LiveOrderCandidate(
        symbol="BTCUSDT",
        side="BUY",
        quantity=0.001,
        requested_notional_usdt=50.0,
        price_reference=50000.0,
        prediction_id="pred_1",
        risk_decision_id="risk_1",
        orchestrator_decision_id="orch_1",
        signal_id="sig_1",
        live_gate_audit_id="gate_1",
        risk_profile_audit_id="risk_profile_1",
        symbols_audit_id="symbols_1",
        final_approval_audit_id="approval_1",
        expected_move_after_cost_bps=20.0,
        confidence=0.75,
        source_generated_est="2026-06-16T10:00:00-04:00",
    )

    result = transport.submit_market_order(
        candidate=candidate,
        api_key="key",
        api_secret="secret",
    )

    assert result["submitted"] is False
    assert result["error_type"] == "MAKER_FIRST_SYMBOL_FILTERS_MISSING"
    assert result["endpoint"] == "WS order.place"
    assert result["order_type"] == "LIMIT"
    assert result["timeInForce"] == "GTX"
    assert result["maker_first"] is True
    assert sent == []


def test_websocket_primary_transport_reads_symbol_filters_from_cache_before_rest() -> None:
    class RedisLike:
        def get(self, key: str) -> str | None:
            assert key == "v2:exchange:symbol_filters:BTCUSDT"
            return json.dumps(
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "min_qty": "0.001",
                    "step_size": "0.001",
                    "tick_size": "0.10",
                    "min_notional": "5",
                }
            )

    class RestFallbackShouldNotRun:
        def fetch_symbol_filters(self, symbol: str) -> dict[str, Any]:
            raise AssertionError("REST exchangeInfo fallback should not run with cache filters present")

    transport = BinanceUsdMWebSocketPrimaryTransport(
        redis_client=RedisLike(),
        rest_metadata_transport=RestFallbackShouldNotRun(),  # type: ignore[arg-type]
    )

    filters = transport.fetch_symbol_filters("btcusdt")

    assert filters["ok"] is True
    assert filters["symbol"] == "BTCUSDT"
    assert filters["source"] == "binance_symbol_filter_cache_primary"
    assert filters["transport"] == "websocket_cache_primary"
    assert filters["endpoint"] == "redis:v2:exchange:symbol_filters:BTCUSDT"
    assert filters["rest_fallback_used"] is False
    assert filters["min_notional"] == "5"
    assert filters["step_size"] == "0.001"
    assert filters["tick_size"] == "0.10"


def test_websocket_primary_transport_reads_open_orders_over_ws() -> None:
    sent: list[dict[str, Any]] = []

    def fake_sender(*, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        sent.append({"endpoint": endpoint, "payload": payload, "timeout": timeout})
        return {
            "ok": True,
            "status_code": 200,
            "error_type": None,
            "response": {
                "id": payload["id"],
                "status": 200,
                "result": [
                    {"symbol": "BTCUSDT", "clientOrderId": "existing-open-order"},
                ],
            },
        }

    transport = BinanceUsdMWebSocketPrimaryTransport(
        ws_api_url="wss://unit.test/ws-fapi/v1",
        ws_sender=fake_sender,
        clock_ms=lambda: 1700000000000,
    )

    result = transport.fetch_open_orders(api_key="key", api_secret="secret", symbol="BTCUSDT")

    assert result["ok"] is True
    assert result["endpoint"] == "WS openOrders.status"
    assert result["transport"] == "websocket_api_primary"
    assert result["rest_fallback_used"] is False
    assert result["open_orders_count"] == 1
    assert sent[0]["payload"]["method"] == "openOrders.status"
    assert sent[0]["payload"]["params"]["symbol"] == "BTCUSDT"
    serialized_result = json.dumps(result)
    assert "secret" not in serialized_result
    assert '"apiKey": "key"' not in serialized_result


def test_legacy_rest_order_transport_cannot_submit_even_when_old_flags_enabled(monkeypatch: Any) -> None:
    monkeypatch.setenv("V2_BINANCE_REST_ORDER_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")

    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("REST order fallback should not open a network request")

    transport = BinanceUsdMLiveOrderTransport(urlopen=fail_if_called)
    result = transport.submit_market_order(
        candidate=_candidate(),
        api_key="key",
        api_secret="secret",
    )

    assert result["submitted"] is False
    assert result["error_type"] == "REST_ORDER_SUBMIT_DISABLED_WEBSOCKET_API_REQUIRED"
    assert result["endpoint"] == "WS order.place"
    assert result["blocked_rest_endpoint"] == "POST /fapi/v1/order"
    assert result["rest_fallback_used"] is False
    assert result["rest_order_fallback_supported"] is False


def test_legacy_rest_read_helpers_are_blocked_without_fallback_flag(monkeypatch: Any) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)

    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("REST read fallback should not open a network request without the fallback flag")

    transport = BinanceUsdMLiveOrderTransport(urlopen=fail_if_called)

    position = transport.fetch_position_mode(api_key="key", api_secret="secret")
    account = transport.fetch_account_margin_status(api_key="key", api_secret="secret")
    filters = transport.fetch_symbol_filters("BTCUSDT")

    for result in (position, account, filters):
        assert result["ok"] is False
        assert str(result["error_type"]).startswith("REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY")
        assert result["transport"] == "rest_fallback_blocked_websocket_primary"
        assert result["rest_fallback_used"] is False
        assert result["required_env"] == "BINANCE_REST_FALLBACK_ALLOWED=true"
        assert result["rest_used_as_primary"] is False


def test_binance_rest_fallback_decision_requires_explicit_reason(monkeypatch: Any) -> None:
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(
        policy,
        "_rest_fallback_budget_check",
        lambda **_kwargs: (
            True,
            None,
            {"budget_scope": "test", "budget_used_this_minute": 1},
        ),
    )

    blocked = binance_rest_fallback_decision(
        endpoint="GET /fapi/v1/depth",
        fallback_reason=None,
        role="public_market_data_recovery",
    )
    allowed = binance_rest_fallback_decision(
        endpoint="GET /fapi/v1/depth",
        fallback_reason="websocket_depth_cache_stale",
        role="public_market_data_recovery",
    )

    assert blocked["request_allowed"] is False
    assert blocked["rest_fallback_blocked_reason"] == "REST_FALLBACK_REASON_REQUIRED_WEBSOCKET_PRIMARY"
    assert blocked["rest_used_as_primary"] is False
    assert allowed["request_allowed"] is True
    assert allowed["transport"] == "rest_fallback"
    assert allowed["rest_fallback_reason"] == "websocket_depth_cache_stale"
    assert allowed["rest_used_as_primary"] is False


def test_legacy_rest_read_helpers_mark_success_as_fallback(monkeypatch: Any) -> None:
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(
        policy,
        "_rest_fallback_budget_check",
        lambda **_kwargs: (
            True,
            None,
            {"budget_scope": "test", "budget_used_this_minute": 1},
        ),
    )
    calls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload
            self.status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        calls.append(url)
        assert "/fapi/v1/order" not in url
        if "/positionSide/dual" in url:
            return FakeResponse({"dualSidePosition": True})
        if "/fapi/v3/account" in url:
            return FakeResponse(
                {
                    "canTrade": True,
                    "availableBalance": "25",
                    "totalWalletBalance": "100",
                    "totalUnrealizedProfit": "1.5",
                    "assets": [],
                }
            )
        if "/exchangeInfo" in url:
            return FakeResponse(
                {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "status": "TRADING",
                            "quantityPrecision": 3,
                            "pricePrecision": 2,
                            "filters": [
                                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                                {"filterType": "MIN_NOTIONAL", "notional": "5"},
                            ],
                        }
                    ]
                }
            )
        raise AssertionError(f"unexpected URL {url}")

    transport = BinanceUsdMLiveOrderTransport(urlopen=fake_urlopen, clock_ms=lambda: 1700000000000)

    position = transport.fetch_position_mode(api_key="key", api_secret="secret")
    account = transport.fetch_account_margin_status(api_key="key", api_secret="secret")
    filters = transport.fetch_symbol_filters("BTCUSDT")

    assert position["transport"] == "rest_fallback"
    assert position["rest_fallback_used"] is True
    assert position["rest_fallback_reason"] == "websocket_position_mode_read_unavailable"
    assert account["transport"] == "rest_fallback"
    assert account["rest_fallback_used"] is True
    assert account["rest_fallback_reason"] == "websocket_account_status_read_unavailable"
    assert filters["transport"] == "rest_fallback"
    assert filters["rest_fallback_used"] is True
    assert filters["rest_fallback_reason"] == "symbol_filter_cache_missing"
    assert len(calls) == 3


def test_binance_http_capable_app_and_script_files_require_rest_fallback_guard() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    scan_roots = (
        repo_root / "v2/backend/app",
        repo_root / "v2/backend/scripts",
        repo_root / "tools",
    )
    offenders: list[str] = []
    for root in scan_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if not any(token in text for token in ("fapi.binance.com", "dapi.binance.com", "api.binance.com", "/fapi/", "/dapi/")):
                continue
            if not any(token in text for token in ("urlopen", "httpx.Client", "requests.", "signed_get", "rest_get_json")):
                continue
            if not any(
                token in text
                for token in (
                    "binance_rest_fallback_allowed",
                    "binance_rest_fallback_decision",
                    "require_binance_rest_fallback",
                    "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                    "BINANCE_REST_FALLBACK_ALLOWED",
                )
            ):
                offenders.append(str(path.relative_to(repo_root)))
    assert offenders == []


def test_transport_policy_keeps_rest_order_fallback_and_mutations_disabled() -> None:
    policy = transport_policy_snapshot()

    assert policy["trading_private_primary"] == "binance_usdm_websocket_api"
    assert policy["order_place_method"] == "order.place"
    assert policy["rest_fallback_enabled_for_order_submit"] is False
    assert policy["cancel_modify_enabled"] is False
    assert policy["test_order_enabled"] is False
    assert policy["leverage_margin_mutation_enabled"] is False


class _BudgetRedis:
    def __init__(self, *, cooldown_ttl_ms: int = -2) -> None:
        self.cooldown_ttl_ms = cooldown_ttl_ms
        self.counts: dict[str, int] = {}
        self.cooldown_payload: str | None = None
        self.incrby_calls: list[tuple[str, int]] = []

    def ttl(self, _key: str) -> int:
        if self.cooldown_ttl_ms in {-1, -2}:
            return self.cooldown_ttl_ms
        return self.cooldown_ttl_ms // 1_000

    def incrby(self, key: str, amount: int) -> int:
        self.incrby_calls.append((key, amount))
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    def expire(self, _key: str, _seconds: int) -> bool:
        return True

    def eval(
        self,
        _script: str,
        _key_count: int,
        _key: str,
        requested_ttl_ms: int,
        payload: str,
    ) -> int:
        if self.cooldown_ttl_ms == -1:
            return -1
        if self.cooldown_ttl_ms < requested_ttl_ms:
            self.cooldown_ttl_ms = requested_ttl_ms
            self.cooldown_payload = payload
        return self.cooldown_ttl_ms


def test_shared_rest_budget_consumes_exact_request_weight(
    monkeypatch: Any,
) -> None:
    redis = _BudgetRedis()
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(policy, "_rest_budget_redis", lambda: redis)

    decision = policy.binance_rest_fallback_decision(
        endpoint="GET /fapi/v1/klines",
        fallback_reason="historical_gap",
        request_weight=5,
        require_shared_budget=True,
    )

    assert decision["request_allowed"] is True
    assert decision["budget_scope"] == "host_redis"
    assert decision["budget_used_this_minute"] == 5
    assert decision["request_weight"] == 5
    assert redis.incrby_calls[0][1] == 5


def test_required_shared_rest_budget_fails_closed_without_redis(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(policy, "_rest_budget_redis", lambda: None)

    decision = policy.binance_rest_fallback_decision(
        endpoint="GET /fapi/v1/klines",
        fallback_reason="historical_gap",
        request_weight=5,
        require_shared_budget=True,
    )

    assert decision["request_allowed"] is False
    assert decision["rest_fallback_blocked_reason"] == (
        "REST_FALLBACK_SHARED_BUDGET_UNAVAILABLE"
    )
    assert decision["budget_scope"] == "shared_unavailable"


def test_persistent_shared_cooldown_key_blocks_instead_of_bypassing(
    monkeypatch: Any,
) -> None:
    redis = _BudgetRedis(cooldown_ttl_ms=-1)
    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(policy, "_rest_budget_redis", lambda: redis)

    decision = policy.binance_rest_fallback_decision(
        endpoint="GET /fapi/v1/klines",
        fallback_reason="historical_gap",
        request_weight=5,
        require_shared_budget=True,
    )

    assert decision["request_allowed"] is False
    assert decision["rest_fallback_blocked_reason"] == (
        "REST_FALLBACK_COOLDOWN_PERSISTENT_KEY_FAIL_CLOSED"
    )
    assert redis.incrby_calls == []


def test_shared_418_cooldown_cannot_be_shortened_by_later_429(
    monkeypatch: Any,
) -> None:
    redis = _BudgetRedis()
    monkeypatch.setattr(policy, "_rest_budget_redis", lambda: redis)

    assert policy.report_binance_rest_response(status_code=418) is True
    first_payload = redis.cooldown_payload
    assert redis.cooldown_ttl_ms == 1_800_000
    assert policy.report_binance_rest_response(status_code=429) is True

    assert redis.cooldown_ttl_ms == 1_800_000
    assert redis.cooldown_payload == first_payload
    assert json.loads(str(redis.cooldown_payload))["status_code"] == 418
