from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from v2.backend.app.services.live_gate.live_position_state_machine import (
    LiveCanaryConfig,
    can_create_positive_training_feedback,
    evaluate_live_canary_preflight,
    reconcile_exchange_local_state,
    reconcile_order_lifecycle,
    validate_canary_caps,
    validate_position_transition,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


def cfg(**overrides) -> LiveCanaryConfig:
    values = {"allowed_symbols": ("BTCUSDT",), "max_notional_usd": 100.0}
    values.update(overrides)
    return LiveCanaryConfig(**values)


def pos(side: str, quantity: float = 1.0) -> dict:
    return {"symbol": "BTCUSDT", "side": side, "quantity": quantity}


def trusted_decision(**overrides) -> dict:
    record = {
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
    }
    record.update(overrides)
    return record


def test_flat_to_long_open_allowed() -> None:
    result = validate_position_transition(
        local_position=pos("flat", 0), exchange_position=pos("flat", 0), requested_action="long",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    assert result.allowed is True
    assert result.transition_type == "FLAT_TO_LONG_OPEN"


def test_flat_to_short_open_allowed() -> None:
    result = validate_position_transition(
        local_position=pos("flat", 0), exchange_position=pos("flat", 0), requested_action="short",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    assert result.allowed is True
    assert result.transition_type == "FLAT_TO_SHORT_OPEN"


def test_long_close_requires_reduce_only() -> None:
    result = validate_position_transition(
        local_position=pos("long"), exchange_position=pos("long"), requested_action="close_long",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    assert result.allowed is False
    assert "REDUCE_ONLY_REQUIRED_FOR_CLOSE" in result.blockers


def test_short_close_requires_reduce_only() -> None:
    result = validate_position_transition(
        local_position=pos("short"), exchange_position=pos("short"), requested_action="close_short",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    assert result.allowed is False
    assert "REDUCE_ONLY_REQUIRED_FOR_CLOSE" in result.blockers


def test_direct_flips_blocked() -> None:
    long_to_short = validate_position_transition(
        local_position=pos("long"), exchange_position=pos("long"), requested_action="short",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    short_to_long = validate_position_transition(
        local_position=pos("short"), exchange_position=pos("short"), requested_action="long",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    assert "DIRECT_FLIP_BLOCKED" in long_to_short.blockers
    assert "DIRECT_FLIP_BLOCKED" in short_to_long.blockers


def test_add_exposure_blocked_by_default() -> None:
    long_add = validate_position_transition(
        local_position=pos("long"), exchange_position=pos("long"), requested_action="long",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    short_add = validate_position_transition(
        local_position=pos("short"), exchange_position=pos("short"), requested_action="short",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    assert "AVERAGING_DOWN_DISABLED" in long_add.blockers
    assert "AVERAGING_DOWN_DISABLED" in short_add.blockers


def test_unknown_states_and_hedge_transition_block() -> None:
    unknown_local = validate_position_transition(
        local_position=pos("mystery"), exchange_position=pos("flat", 0), requested_action="long",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    unknown_exchange = validate_position_transition(
        local_position=pos("flat", 0), exchange_position=pos("mystery"), requested_action="long",
        symbol="BTCUSDT", quantity=1, notional_usd=10, reduce_only=False, config=cfg()
    )
    reconciliation = reconcile_exchange_local_state(
        exchange_position=pos("flat", 0), local_position=pos("flat", 0), open_orders=[], hedge_mode=True,
        margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()
    )
    assert "UNKNOWN_LOCAL_POSITION_STATE" in unknown_local.blockers
    assert "UNKNOWN_EXCHANGE_POSITION_STATE" in unknown_exchange.blockers
    assert "HEDGE_MODE_DISABLED" in reconciliation["blockers"]


def test_matching_exchange_local_state_passes() -> None:
    result = reconcile_exchange_local_state(
        exchange_position=pos("flat", 0), local_position=pos("flat", 0), open_orders=[], hedge_mode=False,
        margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()
    )
    assert result["reconciled"] is True


def test_reconciliation_blocks_drift_and_stale_reads() -> None:
    cases = [
        reconcile_exchange_local_state(exchange_position=pos("short"), local_position=pos("long"), open_orders=[], hedge_mode=False, margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()),
        reconcile_exchange_local_state(exchange_position=pos("long", 2), local_position=pos("long", 1), open_orders=[], hedge_mode=False, margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()),
        reconcile_exchange_local_state(exchange_position=pos("flat", 0), local_position=pos("flat", 0), open_orders=[], hedge_mode=False, margin_mode="cross", signed_read_ts_ms=1, now_ms=10_000, config=cfg()),
        reconcile_exchange_local_state(exchange_position=pos("unknown"), local_position=pos("flat", 0), open_orders=[], hedge_mode=False, margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()),
        reconcile_exchange_local_state(exchange_position=pos("flat", 0), local_position=pos("flat", 0), open_orders=[{"order_id": "o1"}], hedge_mode=False, margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()),
        reconcile_exchange_local_state(exchange_position=pos("flat", 0), local_position=pos("flat", 0), open_orders=[], hedge_mode=True, margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, config=cfg()),
        reconcile_exchange_local_state(exchange_position=pos("flat", 0), local_position=pos("flat", 0), open_orders=[], hedge_mode=False, margin_mode="isolated", signed_read_ts_ms=1000, now_ms=1000, config=cfg()),
    ]
    assert all(case["reconciled"] is False for case in cases)


def test_lifecycle_status_handling() -> None:
    filled = reconcile_order_lifecycle(local_position=pos("flat", 0), order_update={"status": "FILLED", "side": "long", "quantity": 1, "filled_quantity": 1, "avg_fill_price": 100, "fee": 0.1})
    partial = reconcile_order_lifecycle(local_position=pos("flat", 0), order_update={"status": "PARTIALLY_FILLED", "side": "long", "quantity": 2, "filled_quantity": 1, "avg_fill_price": 100})
    rejected = reconcile_order_lifecycle(local_position=pos("flat", 0), order_update={"status": "REJECTED", "side": "long", "quantity": 1})
    canceled = reconcile_order_lifecycle(local_position=pos("flat", 0), order_update={"status": "CANCELED", "side": "long", "quantity": 1})
    expired = reconcile_order_lifecycle(local_position=pos("flat", 0), order_update={"status": "EXPIRED", "side": "long", "quantity": 1})
    unknown = reconcile_order_lifecycle(local_position=pos("flat", 0), order_update={"status": "UNKNOWN", "side": "long", "quantity": 1})
    assert filled["update_local_position"] is True
    assert filled["position_after"]["side"] == "LONG"
    assert partial["filled_quantity"] == 1
    assert partial["remaining_quantity"] == 1
    assert partial["blocks_future_orders_for_symbol"] is True
    assert rejected["update_local_position"] is False
    assert canceled["update_local_position"] is False
    assert expired["update_local_position"] is False
    assert unknown["blocks_future_orders_for_symbol"] is True


def test_bad_terminal_orders_cannot_create_positive_training_feedback() -> None:
    for status in ["REJECTED", "CANCELED", "EXPIRED", "UNKNOWN"]:
        assert can_create_positive_training_feedback({"status": status}) is False
    assert can_create_positive_training_feedback({"status": "FILLED"}) is True


def test_canary_caps_and_mutation_gates_block() -> None:
    result = validate_canary_caps(
        config=cfg(live_canary_enabled=False, max_notional_usd=10, max_daily_orders=1, max_daily_loss_usd=5),
        symbol="ETHUSDT", notional_usd=20, open_positions_count=1, daily_order_count=1, daily_loss_usd=5,
        kill_switch_active=True, human_operator_armed=False, leverage_mutation_attempt=True, margin_mode_mutation_attempt=True,
    )
    blockers = set(result["blockers"])
    assert "LIVE_CANARY_DISABLED" in blockers
    assert "SYMBOL_NOT_ALLOWLISTED" in blockers
    assert "MAX_OPEN_POSITIONS_EXCEEDED" in blockers
    assert "MAX_NOTIONAL_EXCEEDED" in blockers
    assert "MAX_DAILY_ORDERS_EXCEEDED" in blockers
    assert "MAX_DAILY_LOSS_EXCEEDED" in blockers
    assert "KILL_SWITCH_ACTIVE" in blockers
    assert "HUMAN_OPERATOR_ARM_REQUIRED" in blockers
    assert "LEVERAGE_MUTATION_BLOCKED" in blockers
    assert "MARGIN_MODE_MUTATION_BLOCKED" in blockers


def test_preflight_blocks_missing_trust_and_disabled_runtime_gates() -> None:
    result = evaluate_live_canary_preflight(
        config=cfg(), decision=trusted_decision(), replay_snapshot_exists=False, mtf_snapshot_exists=False,
        strict_pipeline_trust_ok=False, pass2a_trusted_decision_ok=False,
        runtime_payload={"release_mode": "NON_LIVE", "order_transport_submit_enabled": False, "live_trading_enabled": False},
        local_position=pos("flat", 0), exchange_position=pos("flat", 0), open_orders=[], hedge_mode=False,
        margin_mode="cross", signed_read_ts_ms=1000, now_ms=1000, requested_action="long", symbol="BTCUSDT",
        quantity=1, notional_usd=10, reduce_only=False,
    )
    blockers = set(result["blockers"])
    assert "LIVE_CANARY_DISABLED" in blockers
    assert "STRICT_PIPELINE_TRUST_NOT_PASSING" in blockers
    assert "PASS2A_TRUSTED_DECISION_MISSING" in blockers
    assert "REPLAY_SNAPSHOT_MISSING" in blockers
    assert "MTF_SNAPSHOT_MISSING" in blockers
    assert "RELEASE_MODE_NON_LIVE" in blockers
    assert "ORDER_TRANSPORT_SUBMIT_DISABLED" in blockers
    assert "LIVE_TRADING_DISABLED" in blockers
    assert result["submit_allowed"] is False
