from __future__ import annotations

import fnmatch
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2" / "backend"))

from v2.backend.app.cli import run_pass3b_exact_live_path_dry_run as pass3b
from v2.backend.app.services.live_gate import binance_live_order_transport as transport_module
from v2.backend.app.services.live_gate.live_position_state_machine import (
    LiveCanaryConfig,
    validate_position_transition,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


class FakeRedis:
    def __init__(self, *, armed: bool = False) -> None:
        live_gate = {
            "live_gate": "blocked_human_only",
            "order_transport_submit_enabled": False,
            "live_trading_enabled": False,
            "live_blocked": True,
            "operator_approved": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "release_mode": "NON_LIVE",
        }
        if armed:
            live_gate.update(
                {
                    "live_gate": "enabled_operator_approved",
                    "order_transport_submit_enabled": True,
                    "live_trading_enabled": True,
                    "live_blocked": False,
                    "operator_approved": True,
                    "release_mode": "LIVE_CANARY_APPROVED",
                }
            )
        self.data: dict[str, object] = {
            "v2:live_gate:state": live_gate,
            "v2:trader:execution_state": {
                "trader_execution_enabled": False,
                "local_position": {"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0},
            },
            "v2:live_order_transport:status": {
                "order_submitted": False,
                "writes_exchange_orders": False,
                "places_real_order": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
            },
            "v2:prediction:BTCUSDT:1m": {
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "decision_id": "d_hold",
                "prediction_id": "p_hold",
                "mtf_snapshot_id": "mtf_hold",
                "replay_snapshot_id": "replay_hold",
                "feature_cutoff": "2026-06-13T00:00:00Z",
                "available_at": "2026-06-13T00:00:01Z",
                "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
                "routes_to_live": False,
                "live_order_allowed": False,
                "selected_action": "hold",
                "symbol": "BTCUSDT",
            },
        }
        self.writes: list[tuple[str, object]] = []

    def get(self, key: str):
        value = self.data.get(key)
        return json.dumps(value) if value is not None else None

    def scan_iter(self, match: str = "*", count: int = 500):
        del count
        for key in sorted(self.data):
            if fnmatch.fnmatch(key, match):
                yield key

    def set(self, key: str, value: object, *_args, **_kwargs) -> bool:
        self.writes.append((key, value))
        self.data[key] = value
        return True


def signed_reads(**overrides) -> dict:
    now_ms = int(time.time() * 1000)
    payload = {
        "available": True,
        "signed_read_ts_ms": now_ms,
        "exchange_position": {"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0, "margin_mode": "cross"},
        "open_orders": [],
        "margin_mode": "cross",
        "position_mode_status": {"ok": True, "dual_side_position": False, "source": "unit"},
        "account_margin_status": {
            "ok": True,
            "available_balance_checked": True,
            "available_balance_redacted": True,
            "_available_balance_usdt": 10.0,
            "_wallet_balance_usdt": 10.0,
            "margin_mode": "cross",
            "signed_read_ts_ms": now_ms,
        },
        "symbol_filter_status": {
            "ok": True,
            "symbol": "BTCUSDT",
            "status": "TRADING",
            "min_qty": "0.000001",
            "step_size": "0.000001",
            "min_notional": "5",
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def pass3b_runtime(monkeypatch):
    monkeypatch.setattr(pass3b, "latest_report_summary", lambda _root: {"critical_failures": 0, "active_stale_count": 0})
    monkeypatch.setattr(pass3b, "latest_recorded_summary", lambda _root: {"critical_failures": 0})
    monkeypatch.setattr(pass3b, "build_signed_read_context", lambda _symbol: signed_reads())
    monkeypatch.setattr(
        transport_module,
        "_exchange_credentials_status",
        lambda _path: {
            "api_key_present": True,
            "api_secret_present": True,
            "_api_key": "unit_key",
            "_api_secret": "unit_secret",
            "raw_credential_in_payload": "NEVER",
        },
    )


def run_report(tmp_path: Path, redis: FakeRedis | None = None) -> dict:
    return pass3b.run_exact_live_path_dry_run(
        client=redis or FakeRedis(),
        redis_url="redis://127.0.0.1:6379/0",
        output_dir=tmp_path,
        run_id="20260613_000000",
    )


def test_exact_live_path_dry_run_refuses_if_live_control_is_armed(tmp_path: Path, pass3b_runtime) -> None:
    report = run_report(tmp_path, FakeRedis(armed=True))

    assert report["status"] == "PASS3B_FAILED_LIVE_CONTROL_ARMED"
    assert report["submit_allowed"] is False
    assert report["submit_function_called"] is False
    assert report["live_order_submitted"] is False


def test_engineering_probe_is_not_persisted_or_counted_or_trained(tmp_path: Path, pass3b_runtime) -> None:
    redis = FakeRedis()
    report = run_report(tmp_path, redis)

    assert report["candidate_type"] == "ENGINEERING_CANARY_PROBE"
    assert report["candidate"]["probe_label"] == "NON_STRATEGY_TEST"
    assert report["persisted_probe_as_prediction"] is False
    assert report["persisted_probe_as_paper_signal"] is False
    assert report["persisted_probe_as_paper_intent"] is False
    assert report["counted_in_edge_proof"] is False
    assert report["training_sample_created"] is False
    assert redis.writes == []


def test_realistic_candidate_passes_state_machine_flat_to_long_open() -> None:
    result = validate_position_transition(
        local_position={"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0},
        exchange_position={"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0},
        requested_action="long",
        symbol="BTCUSDT",
        quantity=0.001,
        notional_usd=5.0,
        reduce_only=False,
        config=LiveCanaryConfig(allowed_symbols=("BTCUSDT",), max_notional_usd=10.0),
    )

    assert result.allowed is True
    assert result.transition_type == "FLAT_TO_LONG_OPEN"


def test_realistic_candidate_blocks_direct_flip_close_without_reduce_only_oversize_and_symbol() -> None:
    config = LiveCanaryConfig(allowed_symbols=("BTCUSDT",), max_notional_usd=10.0)

    direct_flip = validate_position_transition(
        local_position={"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.01},
        exchange_position={"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.01},
        requested_action="short",
        symbol="BTCUSDT",
        quantity=0.001,
        notional_usd=5.0,
        reduce_only=False,
        config=config,
    )
    close_without_reduce = validate_position_transition(
        local_position={"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.01},
        exchange_position={"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.01},
        requested_action="close_long",
        symbol="BTCUSDT",
        quantity=0.001,
        notional_usd=5.0,
        reduce_only=False,
        config=config,
    )
    oversized = validate_position_transition(
        local_position={"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0},
        exchange_position={"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0},
        requested_action="long",
        symbol="BTCUSDT",
        quantity=0.001,
        notional_usd=11.0,
        reduce_only=False,
        config=config,
    )
    unsupported = validate_position_transition(
        local_position={"symbol": "ETHUSDT", "side": "FLAT", "quantity": 0.0},
        exchange_position={"symbol": "ETHUSDT", "side": "FLAT", "quantity": 0.0},
        requested_action="long",
        symbol="ETHUSDT",
        quantity=0.001,
        notional_usd=5.0,
        reduce_only=False,
        config=config,
    )

    assert "DIRECT_FLIP_BLOCKED" in direct_flip.blockers
    assert "REDUCE_ONLY_REQUIRED_FOR_CLOSE" in close_without_reduce.blockers
    assert "MAX_NOTIONAL_EXCEEDED" in oversized.blockers
    assert "SYMBOL_NOT_ALLOWLISTED" in unsupported.blockers


def test_signed_read_unavailable_returns_specific_blocked_status(tmp_path: Path, monkeypatch, pass3b_runtime) -> None:
    monkeypatch.setattr(pass3b, "build_signed_read_context", lambda _symbol: {"available": False, "reason": "NO_CREDS"})

    report = run_report(tmp_path, FakeRedis())

    assert report["status"] == "PASS3B_BLOCKED_SIGNED_READ_UNAVAILABLE"
    assert report["submit_allowed"] is False
    assert report["submit_function_called"] is False


def test_submit_function_never_called_when_release_mode_non_live(tmp_path: Path, pass3b_runtime) -> None:
    report = run_report(tmp_path, FakeRedis())

    assert report["final_submit_block_reason"] in {
        "LIVE_CANARY:RELEASE_MODE_NON_LIVE",
        "LIVE_ORDER_TRANSPORT_SUBMIT_NOT_ENABLED",
        "LIVE_GATE_RUNTIME_NOT_ENABLED",
    }
    assert report["submit_function_called"] is False
    assert report["live_order_submitted"] is False
    assert report["places_real_order"] is False
    assert report["exchange_action_taken"] is False


def test_submit_guard_fails_if_submit_function_is_called() -> None:
    guard = pass3b.SubmitGuardTransport()

    with pytest.raises(AssertionError, match="PASS3B_SUBMIT_GUARD_CALLED"):
        guard.submit_market_order(candidate=object(), api_key="x", api_secret="y")

    assert guard.submit_function_called is True


def test_no_leverage_or_margin_mutation_and_live_control_remains_disabled(tmp_path: Path, pass3b_runtime) -> None:
    redis = FakeRedis()
    before = json.loads(redis.get("v2:live_gate:state"))
    report = run_report(tmp_path, redis)
    after = json.loads(redis.get("v2:live_gate:state"))

    assert report["leverage_changed"] is False
    assert report["margin_mode_changed"] is False
    assert report["post_run_live_control_check"]["ok"] is True
    assert before == after
    assert after["order_transport_submit_enabled"] is False
    assert after["live_trading_enabled"] is False
    assert after["places_real_order"] is False
    assert after["exchange_action_taken"] is False
