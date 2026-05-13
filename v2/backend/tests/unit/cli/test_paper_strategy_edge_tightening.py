from __future__ import annotations

from datetime import datetime, timedelta, timezone

from v2.backend.app.cli.paper_strategy_edge_tightening import (
    build_root_cause,
    build_tightened_evaluation,
)


def _event(index: int, *, confidence: float = 0.8, expected_move_bps: float | None = None) -> dict[str, object]:
    ts = (datetime(2026, 5, 13, 12, tzinfo=timezone.utc) + timedelta(seconds=index * 30)).isoformat().replace("+00:00", "Z")
    event: dict[str, object] = {
        "generated_at": ts,
        "symbol": "BTCUSDT",
        "paper_result": "FILLED_PAPER_ONLY",
        "ledger_action": "PAPER_FILL_SIMULATED",
        "risk_action": "allow",
        "risk_reason_code": "allow_proceed_long",
        "confidence": confidence,
        "fee_usdt": 0.01,
        "fee_rate": 0.0004,
        "slippage_bps": 2.0,
        "paper_realized_pnl": round(-0.01 * index, 2),
        "prediction_id": f"pred_{index}",
        "signal_id": f"sig_{index}",
        "risk_decision_id": f"risk_{index}",
        "execution_intent_id": f"pei_{index}",
    }
    if expected_move_bps is not None:
        event["expected_move_bps"] = expected_move_bps
    return event


def test_root_cause_keeps_negative_6h_explicit() -> None:
    observation = {
        "paper_pnl_current_usdt": -3.0,
        "windows": {
            "6h": {"paper_pnl_delta_usdt": -1.25},
            "24h": {"paper_pnl_delta_usdt": -3.0},
        },
        "fees_slippage_funding_assumptions": {"funding": "zero", "slippage_bps": 2.0},
    }

    result = build_root_cause(observation, [_event(index) for index in range(1, 121)])

    assert "NEGATIVE_EDGE_CONFIRMED_6H" in result["classifications"]
    assert "CANARY_BLOCKED_BY_NEGATIVE_PNL" in result["classifications"]
    assert result["paper_pnl_6h_delta_usdt"] == -1.25


def test_tightened_evaluation_overblocks_when_expected_edge_is_missing() -> None:
    result = build_tightened_evaluation(
        datetime(2026, 5, 13, 13, tzinfo=timezone.utc),
        [_event(index, expected_move_bps=None) for index in range(1, 10)],
    )

    assert "TIGHTENED_PROFILE_OVER_BLOCKS" in result["classifications"]
    assert result["tightened_allowed_fills"] == 0
    assert result["top_tightening_blockers"]["missing_expected_move_after_costs"] == 9


def test_tightened_evaluation_can_allow_high_confidence_with_edge_before_cooldown_limit() -> None:
    result = build_tightened_evaluation(
        datetime(2026, 5, 13, 13, tzinfo=timezone.utc),
        [_event(index, expected_move_bps=12.0) for index in range(1, 3)],
    )

    assert result["tightened_allowed_fills"] == 1
    assert result["tightened_blocked_fills"] == 1
