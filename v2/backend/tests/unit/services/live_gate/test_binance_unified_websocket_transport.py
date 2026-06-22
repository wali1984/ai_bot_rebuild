from __future__ import annotations

# ruff: noqa: S105,S106
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from v2.backend.app.services.binance_unified_websocket_transport import (
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
    assert sent[0]["payload"]["params"]["type"] == "MARKET"
    serialized_result = json.dumps(result)
    assert "secret" not in serialized_result
    assert '"apiKey": "key"' not in serialized_result


def test_legacy_rest_order_transport_is_disabled_by_default(monkeypatch: Any) -> None:
    monkeypatch.delenv("V2_BINANCE_REST_ORDER_FALLBACK_ENABLED", raising=False)

    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("REST order fallback should not open a network request")

    transport = BinanceUsdMLiveOrderTransport(urlopen=fail_if_called)
    result = transport.submit_market_order(
        candidate=_candidate(),
        api_key="key",
        api_secret="secret",
    )

    assert result["submitted"] is False
    assert result["error_type"] == "REST_ORDER_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"
    assert result["rest_fallback_disabled"] is True


def test_transport_policy_keeps_rest_order_fallback_and_mutations_disabled() -> None:
    policy = transport_policy_snapshot()

    assert policy["trading_private_primary"] == "binance_usdm_websocket_api"
    assert policy["order_place_method"] == "order.place"
    assert policy["rest_fallback_enabled_for_order_submit"] is False
    assert policy["cancel_modify_enabled"] is False
    assert policy["test_order_enabled"] is False
    assert policy["leverage_margin_mutation_enabled"] is False
