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

from v2.backend.app.cli import run_pass3c_tiny_live_canary_readiness_check as pass3c
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


class FakeRedis:
    def __init__(
        self,
        *,
        armed: bool = True,
        human_armed: bool = True,
        kill_switch_active: bool = False,
        include_replay: bool = True,
        include_mtf: bool = True,
        leverage_mutation: bool = False,
        margin_mutation: bool = False,
        local_position: dict | None = None,
    ) -> None:
        live_gate = {
            "live_gate": "blocked_human_only",
            "order_transport_submit_enabled": False,
            "live_trading_enabled": False,
            "live_blocked": True,
            "operator_approved": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "release_mode": "NON_LIVE",
            "accepted_live_symbols": ["BTCUSDT"],
            "kill_switch_active": kill_switch_active,
            "kill_switch_enabled": True,
            "live_canary_human_armed": human_armed,
            "live_canary_config": {
                "live_canary_enabled": False,
                "allowed_symbols": ["BTCUSDT"],
                "max_notional_usd": 10.0,
                "max_daily_orders": 3,
                "max_daily_loss_usd": 10.0,
                "max_open_positions": 1,
                "allow_leverage_mutation": False,
                "allow_margin_mode_mutation": False,
            },
        }
        if armed:
            live_gate.update(
                {
                    "release_mode": "LIVE_CANARY_APPROVED",
                    "order_transport_submit_enabled": True,
                    "live_trading_enabled": True,
                    "live_blocked": False,
                    "operator_approved": True,
                }
            )
            live_gate["live_canary_config"]["live_canary_enabled"] = True
        if leverage_mutation:
            live_gate["leverage_mutation_requested"] = True
        if margin_mutation:
            live_gate["margin_mode_mutation_requested"] = True
        self.data: dict[str, object] = {
            "v2:live_gate:state": live_gate,
            "v2:trader:execution_state": {
                "trader_execution_enabled": armed,
                "local_position": local_position or {"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0},
            },
            "v2:live_order_transport:status": {
                "order_submitted": False,
                "writes_exchange_orders": False,
                "places_real_order": False,
            },
            "v2:prediction:BTCUSDT:1m": {
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "decision_id": "d1",
                "prediction_id": "p1",
                "mtf_snapshot_id": "mtf1",
                "replay_snapshot_id": "rs1",
                "feature_cutoff": "2026-06-13T00:00:00Z",
                "available_at": "2026-06-13T00:00:01Z",
                "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
                "routes_to_live": False,
                "live_order_allowed": False,
                "selected_action": "hold",
                "symbol": "BTCUSDT",
            },
        }
        if include_replay:
            self.data["v2:replay:snapshots:p1"] = {"prediction_id": "p1", "replay_snapshot_id": "rs1"}
        if include_mtf:
            self.data["v2:market:mtf_snapshot:mtf1"] = {"prediction_id": "p1", "mtf_snapshot_id": "mtf1"}
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


def signed_reads(
    *,
    available_balance: float = 100.0,
    exchange_position: dict | None = None,
    open_orders: list[dict] | None = None,
    available: bool = True,
) -> dict:
    if not available:
        return {"available": False, "reason": "SIGNED_READ_UNAVAILABLE"}
    now_ms = int(time.time() * 1000)
    return {
        "available": True,
        "signed_read_ts_ms": now_ms,
        "exchange_position": exchange_position or {"symbol": "BTCUSDT", "side": "FLAT", "quantity": 0.0, "margin_mode": "cross"},
        "open_orders": open_orders or [],
        "margin_mode": "cross",
        "position_mode_status": {"ok": True, "dual_side_position": False},
        "account_margin_status": {
            "ok": True,
            "available_balance_checked": True,
            "_available_balance_usdt": available_balance,
            "_wallet_balance_usdt": available_balance,
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


def mark_price(*, price: float = 5000.0, age_ms: int = 0, available: bool = True) -> dict:
    if not available:
        return {"available": False, "reason": "SIGNED_MARK_PRICE_MISSING"}
    return {
        "available": True,
        "symbol": "BTCUSDT",
        "signed_mark_price": price,
        "signed_mark_price_ts_ms": int(time.time() * 1000) - age_ms,
        "source": "unit_signed_mark_price",
    }


@pytest.fixture
def pass3c_defaults(monkeypatch):
    monkeypatch.setattr(pass3c, "latest_report_summary", lambda _roots: {"critical_failures": 0, "active_stale_count": 0})
    monkeypatch.setattr(pass3c, "latest_recorded_summary", lambda _roots: {"critical_failures": 0})
    monkeypatch.setattr(
        pass3c,
        "latest_pass2b_summary",
        lambda: {
            "verdict": "INSUFFICIENT_SAMPLE",
            "total_trusted_predictions": 10,
            "actionable_predictions": 0,
            "closed_paper_trades": 0,
            "invalid_feedback_count": 0,
        },
    )
    monkeypatch.setattr(pass3c, "build_signed_read_context", lambda _symbol: signed_reads())
    monkeypatch.setattr(pass3c, "build_mark_price_context", lambda _symbol: mark_price())


def run_report(tmp_path: Path, redis: FakeRedis, *, ack: bool = True) -> dict:
    return pass3c.run_readiness_check(
        client=redis,
        redis_url="redis://127.0.0.1:6379/0",
        output_dir=tmp_path,
        run_id="20260613_000000",
        execution_validation_canary_acknowledged=ack,
    )


def test_readiness_blocked_when_edge_insufficient_and_ack_absent(tmp_path: Path, pass3c_defaults) -> None:
    report = run_report(tmp_path, FakeRedis(), ack=False)

    assert report["status"] == pass3c.STATUS_BLOCKED_EDGE_INSUFFICIENT_SAMPLE
    assert any(item["reason"] == "PASS2B_EDGE_INSUFFICIENT_SAMPLE_ACK_REQUIRED" for item in report["blockers"])


def test_readiness_blocked_when_available_balance_is_insufficient(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "build_signed_read_context", lambda _symbol: signed_reads(available_balance=0.0))

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_INSUFFICIENT_BALANCE
    assert report["futures_balance"]["insufficient"] is True


def test_notional_mismatch_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "build_mark_price_context", lambda _symbol: mark_price(price=100000.0))

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "CANDIDATE_NOTIONAL_MARK_PRICE_MISMATCH" in report["notional_validation"]["blockers"]


def test_stale_mark_price_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "build_mark_price_context", lambda _symbol: mark_price(age_ms=10_000))

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "SIGNED_MARK_PRICE_STALE" in report["notional_validation"]["blockers"]


def test_missing_mark_price_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "build_mark_price_context", lambda _symbol: mark_price(available=False))

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "SIGNED_MARK_PRICE_MISSING" in report["notional_validation"]["blockers"]


def test_quantity_below_min_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(
        pass3c,
        "build_signed_read_context",
        lambda _symbol: signed_reads(
            available_balance=100.0,
        ) | {"symbol_filter_status": {"ok": True, "symbol": "BTCUSDT", "status": "TRADING", "min_qty": "0.01", "step_size": "0.000001", "min_notional": "5"}},
    )

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "QUANTITY_BELOW_MIN_QTY" in report["notional_validation"]["blockers"]


def test_step_size_violation_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(
        pass3c,
        "build_signed_read_context",
        lambda _symbol: signed_reads() | {"symbol_filter_status": {"ok": True, "symbol": "BTCUSDT", "status": "TRADING", "min_qty": "0.000001", "step_size": "0.0003", "min_notional": "5"}},
    )

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "QUANTITY_STEP_SIZE_VIOLATION" in report["notional_validation"]["blockers"]


def test_below_exchange_min_notional_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(
        pass3c,
        "build_signed_read_context",
        lambda _symbol: signed_reads() | {"symbol_filter_status": {"ok": True, "symbol": "BTCUSDT", "status": "TRADING", "min_qty": "0.000001", "step_size": "0.000001", "min_notional": "10"}},
    )

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "NOTIONAL_BELOW_EXCHANGE_MIN_NOTIONAL" in report["notional_validation"]["blockers"]


def test_above_canary_cap_blocks(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "build_mark_price_context", lambda _symbol: mark_price(price=20000.0))

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_CANDIDATE_NOTIONAL
    assert "NOTIONAL_ABOVE_CANARY_CAP" in report["notional_validation"]["blockers"]


def test_valid_candidate_passes_notional_filter_validation(tmp_path: Path, pass3c_defaults) -> None:
    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["notional_validation"]["valid"] is True
    assert report["notional_validation"]["computed_notional_usd"] == 5.0
    assert report["notional_validation"]["blockers"] == []


def test_readiness_blocked_when_strict_verifier_fails(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "latest_report_summary", lambda _roots: {"critical_failures": 1, "active_stale_count": 0})

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_STRICT_TRUST


def test_readiness_blocked_when_recorded_state_fails(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "latest_recorded_summary", lambda _roots: {"critical_failures": 1})

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_STRICT_TRUST


def test_readiness_blocked_when_active_stale_present(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "latest_report_summary", lambda _roots: {"critical_failures": 0, "active_stale_count": 1})

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_STRICT_TRUST


def test_readiness_blocked_when_replay_or_mtf_missing(tmp_path: Path, pass3c_defaults) -> None:
    report = run_report(tmp_path, FakeRedis(include_replay=False, include_mtf=False), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_STRICT_TRUST
    assert report["trusted_evidence"]["missing_replay_or_mtf"] is True


def test_readiness_blocked_when_exchange_local_reconciliation_fails(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(
        pass3c,
        "build_signed_read_context",
        lambda _symbol: signed_reads(exchange_position={"symbol": "BTCUSDT", "side": "SHORT", "quantity": 0.1, "margin_mode": "cross"}),
    )

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_RECONCILIATION


def test_readiness_blocked_with_open_position(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    position = {"symbol": "BTCUSDT", "side": "LONG", "quantity": 0.1, "margin_mode": "cross"}
    monkeypatch.setattr(pass3c, "build_signed_read_context", lambda _symbol: signed_reads(exchange_position=position))

    report = run_report(tmp_path, FakeRedis(local_position=position), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_OPEN_POSITION


def test_readiness_blocked_with_unexpected_open_order(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "build_signed_read_context", lambda _symbol: signed_reads(open_orders=[{"orderId": 1, "symbol": "BTCUSDT"}]))

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_RECONCILIATION
    assert any(item["reason"] in {"UNEXPECTED_OPEN_EXCHANGE_ORDERS", "UNEXPECTED_OPEN_ORDER"} for item in report["blockers"])


def test_readiness_blocked_when_kill_switch_active(tmp_path: Path, pass3c_defaults) -> None:
    report = run_report(tmp_path, FakeRedis(kill_switch_active=True), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_KILL_SWITCH


def test_readiness_blocked_when_human_arm_missing(tmp_path: Path, pass3c_defaults) -> None:
    report = run_report(tmp_path, FakeRedis(human_armed=False), ack=True)

    assert report["status"] == pass3c.STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED


def test_readiness_blocked_when_leverage_or_margin_mutation_required(tmp_path: Path, pass3c_defaults) -> None:
    leverage = run_report(tmp_path, FakeRedis(leverage_mutation=True), ack=True)
    margin = run_report(tmp_path, FakeRedis(margin_mutation=True), ack=True)

    assert leverage["status"] == pass3c.STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED
    assert margin["status"] == pass3c.STATUS_BLOCKED_LIVE_CONTROL_NOT_ARMED


def test_readiness_can_reach_operator_review_only_when_all_gates_pass_and_ack_is_explicit(tmp_path: Path, monkeypatch, pass3c_defaults) -> None:
    monkeypatch.setattr(pass3c, "latest_pass2b_summary", lambda: {"verdict": "INSUFFICIENT_SAMPLE"})

    report = run_report(tmp_path, FakeRedis(), ack=True)

    assert report["status"] == pass3c.STATUS_READY


def test_readiness_check_is_read_only_and_does_not_enable_live(tmp_path: Path, pass3c_defaults) -> None:
    redis = FakeRedis(armed=False, human_armed=False)
    before = json.loads(redis.get("v2:live_gate:state"))
    report = run_report(tmp_path, redis, ack=False)
    after = json.loads(redis.get("v2:live_gate:state"))

    assert redis.writes == []
    assert before == after
    assert report["submit_allowed"] is False
    assert report["live_order_submitted"] is False
    assert report["places_real_order"] is False
    assert report["exchange_action_taken"] is False
    assert after["order_transport_submit_enabled"] is False
    assert after["live_trading_enabled"] is False
