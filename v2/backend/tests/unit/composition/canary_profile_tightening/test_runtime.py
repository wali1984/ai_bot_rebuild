import sys

import pytest

from v2.backend.app.composition.canary_profile_tightening import (
    CanaryProfileTighteningCompositionError,
    build_canary_profile_tightening_runtime,
)


NOW_MS = 1_778_700_000_000


def _intent(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "BTCUSDT",
        "action": "OPEN_LONG",
        "confidence": 0.82,
        "signal_generated_at_ms": NOW_MS - 5_000,
        "feature_snapshot_generated_at_ms": NOW_MS - 10_000,
        "expected_move_bps": 12.0,
        "fee_bps": 4.0,
        "slippage_bps": 2.0,
        "funding_bps": 0.0,
    }
    payload.update(overrides)
    return payload


def _fill(*, seconds_ago: int, action: str = "OPEN_LONG", pnl_delta: float = -0.01) -> dict[str, object]:
    return {
        "generated_at_ms": NOW_MS - seconds_ago * 1000,
        "symbol": "BTCUSDT",
        "action": action,
        "paper_result": "FILLED_PAPER_ONLY",
        "ledger_action": "PAPER_FILL_SIMULATED",
        "paper_pnl_delta": pnl_delta,
    }


def _closed_position(*, seconds_ago: int, pnl_delta: float = -0.03) -> dict[str, object]:
    return {
        "generated_at_ms": NOW_MS - seconds_ago * 1000,
        "symbol": "BTCUSDT",
        "ledger_action": "PAPER_POSITION_CLOSED",
        "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        "realized_delta_usdt": pnl_delta,
    }


def _runtime(**kwargs: object):
    return build_canary_profile_tightening_runtime(now_ms_clock=lambda: NOW_MS, **kwargs)


def test_runtime_does_not_call_clock_at_build_time() -> None:
    calls = 0

    def clock() -> int:
        nonlocal calls
        calls += 1
        return NOW_MS

    build_canary_profile_tightening_runtime(now_ms_clock=clock)

    assert calls == 0


def test_high_confidence_fresh_intent_is_allowed_only_for_paper_simulation() -> None:
    record = _runtime().evaluate_now(intent_payload=_intent(), recent_events=[], approval_token_present=False)

    assert record["classification"] == "TIGHTENED_PROFILE_PAPER_SIMULATION_ELIGIBLE"
    assert record["paper_simulation_allowed"] is True
    assert "approval_token_absent_live_block" in record["live_blockers"]
    assert record["safe_for_live"] is False
    assert record["automation_can_enable_live"] is False


def test_low_confidence_is_blocked() -> None:
    record = _runtime().evaluate_now(intent_payload=_intent(confidence=0.62))

    assert record["classification"] == "TIGHTENED_PROFILE_BLOCKED"
    assert "confidence_below_canary_threshold" in record["blockers"]


def test_overtrading_is_blocked() -> None:
    recent = [_fill(seconds_ago=index * 60) for index in range(13)]

    record = _runtime(max_fills_per_hour=12).evaluate_now(intent_payload=_intent(), recent_events=recent)

    assert "fill_frequency_exceeds_canary_limit" in record["blockers"]


def test_churn_and_same_direction_cooldown_are_blocked() -> None:
    runtime = _runtime(cooldown_seconds=300)

    same = runtime.evaluate_now(intent_payload=_intent(action="OPEN_LONG"), recent_events=[_fill(seconds_ago=60, action="OPEN_LONG")])
    churn = runtime.evaluate_now(intent_payload=_intent(action="OPEN_SHORT"), recent_events=[_fill(seconds_ago=60, action="OPEN_LONG")])

    assert "same_symbol_same_direction_cooldown" in same["blockers"]
    assert "flip_churn_cooldown" in churn["blockers"]


def test_fee_slippage_negative_edge_is_blocked() -> None:
    record = _runtime().evaluate_now(intent_payload=_intent(expected_move_bps=5.0, fee_bps=4.0, slippage_bps=2.0))

    assert "expected_edge_below_costs" in record["blockers"]


def test_stale_signal_and_feature_are_blocked() -> None:
    record = _runtime().evaluate_now(
        intent_payload=_intent(
            signal_generated_at_ms=NOW_MS - 20_000,
            feature_snapshot_generated_at_ms=NOW_MS - 120_000,
        )
    )

    assert "stale_signal" in record["blockers"]
    assert "stale_feature_snapshot" in record["blockers"]


def test_symbol_not_whitelisted_is_blocked() -> None:
    record = _runtime().evaluate_now(intent_payload=_intent(symbol="ETHUSDT"))

    assert "symbol_not_whitelisted" in record["blockers"]


def test_recent_loss_cooldown_is_blocked() -> None:
    record = _runtime(loss_cooldown_seconds=600).evaluate_now(
        intent_payload=_intent(action="OPEN_SHORT"),
        recent_events=[_fill(seconds_ago=120, action="OPEN_LONG", pnl_delta=-0.25)],
    )

    assert "loss_cooldown_active" in record["blockers"]


def test_recent_closed_position_loss_cooldown_is_blocked_without_counting_as_fill() -> None:
    record = _runtime(loss_cooldown_seconds=600).evaluate_now(
        intent_payload=_intent(action="OPEN_SHORT"),
        recent_events=[_closed_position(seconds_ago=120, pnl_delta=-0.25)],
    )

    assert "loss_cooldown_active" in record["blockers"]
    assert record["recent_fill_stats"]["fills_last_hour"] == 0
    assert record["recent_fill_stats"]["total_recent_fills"] == 0


def test_runtime_rejects_bad_inputs() -> None:
    with pytest.raises(CanaryProfileTighteningCompositionError):
        build_canary_profile_tightening_runtime(now_ms_clock=1)  # type: ignore[arg-type]


def test_runtime_module_does_not_load_redis_or_exchange_clients_on_import() -> None:
    sys.modules.pop("redis", None)
    sys.modules.pop("ccxt", None)

    __import__("v2.backend.app.composition.canary_profile_tightening.runtime")

    assert "redis" not in sys.modules
    assert "ccxt" not in sys.modules
