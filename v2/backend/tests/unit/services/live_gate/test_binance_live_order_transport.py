from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

import json
from typing import Any

from v2.backend.app.services.live_gate.binance_live_order_transport import (
    KEY_DEDUPE,
    KEY_KILL_SWITCH,
    LiveOrderCandidate,
    _position_read_ready,
    est_now,
    evaluate_live_order_transport,
)


class RedisLike:
    def __init__(self, risk_records: list[dict[str, Any]] | None = None) -> None:
        self.values: dict[str, str] = {}
        self.writes: dict[str, Any] = {}
        if risk_records is not None:
            self.values["v2:risk:gateway:decisions"] = json.dumps(risk_records)

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        assert key.startswith("v2:")
        self.values[key] = value
        self.writes[key] = {"value": json.loads(value), "ex": ex}
        return True


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[LiveOrderCandidate] = []

    def submit_market_order(self, *, candidate: LiveOrderCandidate, api_key: str, api_secret: str) -> dict[str, Any]:
        self.calls.append(candidate)
        assert api_key == "key"
        assert api_secret == "secret"
        return {
            "submitted": True,
            "status_code": 200,
            "client_order_id": "v2livefake",
            "endpoint": "POST /fapi/v1/order",
        }

    def fetch_symbol_filters(self, symbol: str) -> dict[str, Any]:
        return {
            "ok": True,
            "symbol": symbol,
            "status": "TRADING",
            "min_qty": "0.00001",
            "step_size": "0.00001",
            "min_notional": "5",
            "endpoint": "GET /fapi/v1/exchangeInfo",
        }

    def fetch_account_margin_status(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        return {
            "ok": True,
            "available_balance_checked": True,
            "available_balance_redacted": True,
            "_available_balance_usdt": 1000.0,
            "_wallet_balance_usdt": 10000.0,
            "endpoint": "GET /fapi/v3/account",
        }


class HedgeModeFakeTransport(FakeTransport):
    def fetch_position_mode(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        assert api_key == "key"
        assert api_secret == "secret"
        return {
            "ok": True,
            "dual_side_position": True,
            "endpoint": "GET /fapi/v1/positionSide/dual",
        }


class InsufficientMarginFakeTransport(FakeTransport):
    def fetch_position_mode(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        return {
            "ok": True,
            "dual_side_position": False,
            "endpoint": "GET /fapi/v1/positionSide/dual",
        }

    def fetch_account_margin_status(self, *, api_key: str, api_secret: str) -> dict[str, Any]:
        return {
            "ok": True,
            "available_balance_checked": True,
            "available_balance_redacted": True,
            "_available_balance_usdt": 1.0,
            "_wallet_balance_usdt": 10000.0,
            "endpoint": "GET /fapi/v3/account",
        }


def _runtime_payload(generated_est: str | None = None) -> dict[str, Any]:
    generated_est = generated_est or est_now()
    return {
        "generated_est": generated_est,
        "enabled_at_est": generated_est,
        "live_gate": "enabled_operator_approved",
        "trader_execution_enabled": True,
        "accepted_live_symbols": ["BTCUSDT"],
        "live_symbols": ["BTCUSDT"],
        "execution_live_symbols": ["BTCUSDT"],
        "accepted_risk_audit_id": "risk_audit",
        "accepted_symbols_audit_id": "symbols_audit",
        "final_approval_audit_id": "final_audit",
        "enable_audit_id": "enable_audit",
        "risk_profile": {
            "profile_name": "conservative",
            "fields": {
                "max_leverage": 1.0,
                "max_notional_per_trade": 25.0,
                "min_confidence_calibrated": 0.66,
                "min_expected_move_after_cost_bps": 12.0,
            },
        },
        "kill_switch_active": False,
        "margin_mutation_allowed": False,
        "leverage_mutation_allowed": False,
        "order_transport_write_guard_enabled": True,
        "order_transport_submit_enabled": True,
        "release_mode": "LIVE_CANARY_APPROVED",
    }


def _signal(generated_est: str | None = None) -> dict[str, Any]:
    generated_est = generated_est or est_now()
    return {
        "symbol": "BTCUSDT",
        "action": "long",
        "prediction_id": "pred_1",
        "risk_decision_id": "risk_1",
        "orchestrator_decision_id": "orch_1",
        "signal_id": "sig_1",
        "expected_move_after_cost_bps": 20.0,
        "confidence": 0.7,
        "market_state_integrity_score": 95.0,
        "price_target_after_cost": 100.0,
        "paper_state": "ACCEPTED_PAPER_FILL",
        "generated_est": generated_est,
    }


def _trader_status() -> dict[str, Any]:
    return {
        "binance_private_readonly": {
            "position_read_status": "WEBSOCKET_PRIMARY_READY",
            "position_read_endpoint": "WS account.position",
            "account_read_status": "WEBSOCKET_PRIMARY_READY",
            "account_read_endpoint": "WS account.status",
            "rest_fallback_used": False,
        }
    }


def test_position_read_ready_does_not_accept_plain_http_200_as_primary() -> None:
    assert _position_read_ready({"position_read_status": "WEBSOCKET_PRIMARY_READY"}) is True
    assert _position_read_ready({"position_read_status": "SIGNED_WS_READ_EXECUTED"}) is True
    assert _position_read_ready({"position_read_status": "HTTP_200"}) is False
    assert (
        _position_read_ready(
            {
                "position_read_status": "HTTP_200",
                "position_read_endpoint": "GET /fapi/v3/positionRisk",
                "rest_fallback_used": True,
            }
        )
        is True
    )


def _write_env(root: Path) -> None:
    env_path = root / "v2/.env.local"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("BINANCE_API_KEY=key\nBINANCE_API_SECRET=secret\n", encoding="utf-8")


def test_blocks_stale_runtime_state(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={
            "source": "test",
            "payload": _runtime_payload("2026-06-01T00:00:00-04:00"),
            "validation": {"valid": False, "blockers": ["LIVE_GATE_RUNTIME_STATE_STALE"]},
        },
        redis_client=redis,
        transport=FakeTransport(),
    )
    assert result["order_submitted"] is False
    assert "LIVE_GATE_RUNTIME_STATE_STALE" in result["blockers"]


def test_blocks_armed_runtime_when_release_mode_not_approved(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    runtime = _runtime_payload()
    runtime["release_mode"] = "NON_LIVE"
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": runtime, "validation": {"valid": False, "blockers": ["LIVE_SUBMIT_RELEASE_MODE_NOT_APPROVED"]}},
        redis_client=redis,
        transport=FakeTransport(),
    )
    assert result["order_submitted"] is False
    assert result["runtime_submit_enabled"] is False
    assert result["transport_submit_enabled"] is False
    assert "LIVE_ORDER_TRANSPORT_RELEASE_MODE_NOT_APPROVED" in result["blockers"]


def test_blocks_unaccepted_symbol(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "ETHUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    signal = _signal()
    signal["symbol"] = "ETHUSDT"
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [signal]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=FakeTransport(),
    )
    assert result["order_submitted"] is False
    assert "NO_ACCEPTED_SYMBOL_SIGNAL_CANDIDATE" in result["blockers"]


def test_blocks_missing_signal_lineage(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    signal = _signal()
    signal["signal_id"] = ""
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [signal]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=FakeTransport(),
    )
    assert result["order_submitted"] is False
    assert "MISSING_LINEAGE:signal_id" in result["blockers"]


def test_blocks_when_runtime_write_guard_disabled(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    runtime = _runtime_payload()
    runtime["order_transport_write_guard_enabled"] = False
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": runtime, "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=FakeTransport(),
    )
    assert result["order_submitted"] is False
    assert result["live_order_transport_bound"] is True
    assert "LIVE_ORDER_TRANSPORT_WRITE_GUARD_NOT_ENABLED" in result["blockers"]


def test_blocks_risk_gateway_decision_id_mismatch(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_other", "risk_action": "allow"}])
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=FakeTransport(),
    )
    assert result["order_submitted"] is False
    assert "RISK_GATEWAY_DECISION_ID_MISMATCH" in result["blockers"]


def test_reconciles_stale_signal_risk_id_by_prediction_id(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike(
        [
            {
                "symbol": "BTCUSDT",
                "prediction_id": "pred_1",
                "risk_decision_id": "risk_current",
                "risk_action": "allow",
            }
        ]
    )
    signal = _signal()
    signal["risk_decision_id"] = "v2:risk:decisions:BTCUSDT"
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [signal]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=FakeTransport(),
        dry_run=True,
    )
    assert result["status"] == "LIVE_ORDER_TRANSPORT_BLOCKED"
    assert result["selected_candidate"]["lineage"]["risk_decision_id"] == "risk_current"
    assert "LIVE_CANARY_PREFLIGHT_BLOCKED" in result["blockers"]


def test_pre_submit_dry_run_does_not_call_transport_when_canary_disabled(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = FakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
        dry_run=True,
    )
    assert result["order_submitted"] is False
    assert result["would_submit"] is False
    assert result["status"] == "LIVE_ORDER_TRANSPORT_BLOCKED"
    assert "LIVE_CANARY_PREFLIGHT_BLOCKED" in result["blockers"]
    assert "LIVE_CANARY:LIVE_CANARY_DISABLED" in result["blockers"]
    assert len(fake.calls) == 0


def test_no_submit_occurs_when_legacy_guards_pass_but_canary_disabled(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = FakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
    )
    assert result["order_submitted"] is False
    assert result["submit_result"] is None
    assert "LIVE_CANARY_PREFLIGHT_BLOCKED" in result["blockers"]
    assert len(fake.calls) == 0
    assert KEY_DEDUPE not in redis.writes


def test_hedge_mode_candidate_is_built_but_canary_blocks_submit_by_default(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = HedgeModeFakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
    )
    assert result["order_submitted"] is False
    assert result["position_mode_status"]["dual_side_position"] is True
    assert result["selected_candidate"]["position_side"] == "LONG"
    assert "LIVE_CANARY:HEDGE_MODE_DISABLED" in result["blockers"]
    assert len(fake.calls) == 0


def test_blocks_when_available_margin_below_min_order(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = InsufficientMarginFakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_trader_status(),
        runtime_read={"source": "test", "payload": _runtime_payload(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
    )
    assert result["order_submitted"] is False
    assert "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER" in result["blockers"]
    assert result["account_margin_status"]["available_balance_redacted"] is True
    assert "_available_balance_usdt" not in result["account_margin_status"]
    assert len(fake.calls) == 0


def _trusted_live_signal(generated_est: str | None = None) -> dict[str, Any]:
    signal = _signal(generated_est)
    signal.update(
        {
            "trust_schema_version": "pipeline_trust_v3",
            "decision_id": "dec_1",
            "mtf_snapshot_id": "mtf_1",
            "replay_snapshot_id": "rs_1",
            "feature_cutoff": "2026-06-13T00:00:00Z",
            "available_at": "2026-06-13T00:00:01Z",
            "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
            "routes_to_live": False,
            "live_order_allowed": False,
        }
    )
    return signal


def _canary_runtime(local_side: str = "flat", local_qty: float = 0.0) -> dict[str, Any]:
    runtime = _runtime_payload()
    runtime.update(
        {
            "live_canary_config": {
                "live_canary_enabled": True,
                "allowed_symbols": ["BTCUSDT"],
                "max_open_positions": 1,
                "max_notional_usd": 100.0,
                "max_daily_orders": 3,
                "max_daily_loss_usd": 10.0,
            },
            "live_canary_human_armed": True,
            "local_position": {"symbol": "BTCUSDT", "side": local_side, "quantity": local_qty},
            "open_positions_count": 0,
            "daily_order_count": 0,
            "daily_loss_usd": 0.0,
        }
    )
    return runtime


def _canary_trader_status(exchange_side: str = "flat", exchange_qty: float = 0.0) -> dict[str, Any]:
    status = _trader_status()
    status["binance_private_readonly"].update(
        {
            "exchange_position": {"symbol": "BTCUSDT", "side": exchange_side, "quantity": exchange_qty},
            "open_orders": [],
            "margin_mode": "cross",
            "signed_read_ts_ms": int(__import__("time").time() * 1000),
        }
    )
    return status


def test_transport_preflight_blocks_missing_trust_evidence_before_submit(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "prediction_id": "pred_1", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = FakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_signal()]},
        trader_status=_canary_trader_status(),
        runtime_read={"source": "test", "payload": _canary_runtime(), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
    )
    assert result["order_submitted"] is False
    assert "LIVE_CANARY:TRUST_SCHEMA_MISSING" in result["blockers"]
    assert len(fake.calls) == 0


def test_transport_preflight_blocks_state_machine_reject_before_submit(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "prediction_id": "pred_1", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = FakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_trusted_live_signal()]},
        trader_status=_canary_trader_status("long", 1.0),
        runtime_read={"source": "test", "payload": _canary_runtime("long", 1.0), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
    )
    assert result["order_submitted"] is False
    assert "LIVE_CANARY:AVERAGING_DOWN_DISABLED" in result["blockers"]
    assert len(fake.calls) == 0


def test_transport_preflight_blocks_reconciliation_failure_before_submit(tmp_path: Path) -> None:
    _write_env(tmp_path)
    redis = RedisLike([{"symbol": "BTCUSDT", "prediction_id": "pred_1", "risk_decision_id": "risk_1", "risk_action": "allow"}])
    redis.values[KEY_KILL_SWITCH] = "false"
    fake = FakeTransport()
    result = evaluate_live_order_transport(
        repo_root=tmp_path,
        signal_status={"published_signals": [_trusted_live_signal()]},
        trader_status=_canary_trader_status("short", 1.0),
        runtime_read={"source": "test", "payload": _canary_runtime("flat", 0.0), "validation": {"valid": True, "blockers": []}},
        redis_client=redis,
        transport=fake,
    )
    assert result["order_submitted"] is False
    assert "LIVE_CANARY:LOCAL_EXCHANGE_SIDE_MISMATCH" in result["blockers"]
    assert len(fake.calls) == 0
