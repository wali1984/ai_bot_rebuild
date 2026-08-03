"""Phase 2 directional-balance repair: side-level performance gate tests."""
from __future__ import annotations

from v2.backend.app.services.paper_trade_management.entry_gate import evaluate_entry_gate
from v2.backend.app.services.paper_trade_management.side_performance import (
    SideGateConfig,
    build_side_performance,
    evaluate_side_gate,
)


def _row(side: str, pnl_bps: float, *, confidence: float = 0.7, session: str = "sess_1") -> dict:
    return {
        "paper_session_id": session,
        "trainer_consumable": True,
        "side": side,
        "realized_net_pnl_bps": pnl_bps,
        "realized_pnl_usd": pnl_bps / 100.0,
        "confidence_calibrated": confidence,
        "trainer_feedback_id": f"fb_{side}_{pnl_bps}",
    }


def test_build_side_performance_buckets_split_by_side() -> None:
    rows = [_row("LONG", 50.0), _row("LONG", -20.0), _row("SHORT", 30.0)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    assert perf["sides"]["LONG"]["trade_count"] == 2
    assert perf["sides"]["SHORT"]["trade_count"] == 1
    assert perf["sides"]["LONG"]["expectancy_bps"] == 15.0
    assert perf["sides"]["LONG"]["profit_factor"] == 2.5


def test_side_with_non_positive_expectancy_is_blocked() -> None:
    rows = [_row("SHORT", -10.0) for _ in range(10)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    gate = evaluate_side_gate(perf, side="SHORT", confidence_calibrated=0.99)
    assert gate["allowed"] is False
    assert any("SIDE_BUCKET_EXPECTANCY_NON_POSITIVE" in r for r in gate["reasons"])


def test_side_with_insufficient_evidence_keeps_exploration_path() -> None:
    rows = [_row("LONG", -5.0), _row("LONG", -5.0)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    gate = evaluate_side_gate(perf, side="LONG", confidence_calibrated=0.70)
    assert gate["allowed"] is True
    assert gate["exploration_path"] is True


def test_side_specific_confidence_floor_blocks_low_confidence() -> None:
    rows = [_row("LONG", 25.0) for _ in range(10)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    cfg = SideGateConfig(long_confidence_floor=0.60)
    gate = evaluate_side_gate(perf, side="LONG", confidence_calibrated=0.55, config=cfg)
    assert gate["allowed"] is False
    assert any("SIDE_CONFIDENCE_BELOW_FLOOR" in r for r in gate["reasons"])


def test_poor_calibration_raises_confidence_floor() -> None:
    # Confident but wrong: high confidence, all losses -> high Brier.
    rows = [_row("SHORT", -10.0, confidence=0.95) for _ in range(6)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    gate = evaluate_side_gate(perf, side="SHORT", confidence_calibrated=0.60)
    assert gate["confidence_floor"] > 0.55


def test_entry_gate_integrates_side_gate_block() -> None:
    rows = [_row("SHORT", -10.0) for _ in range(10)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="1h",
        side="short",
        strategy_mode="mean_reversion_mode",
        confidence_calibrated=0.99,
        expected_move_after_cost_bps=-25.0,
        side_performance=perf,
    )
    assert result["allowed"] is False
    assert any("SIDE_GATE_BLOCK" in r for r in result["reasons"])
    assert result["side_gate_result"]["allowed"] is False


def test_entry_gate_side_gate_allows_positive_side() -> None:
    rows = [_row("LONG", 25.0) for _ in range(10)]
    perf = build_side_performance(rows, paper_session_id="sess_1")
    result = evaluate_entry_gate(
        symbol="BTCUSDT",
        timeframe="1h",
        side="long",
        strategy_mode="trend_mode",
        confidence_calibrated=0.70,
        expected_move_after_cost_bps=25.0,
        side_performance=perf,
    )
    assert not any("SIDE_GATE_BLOCK" in r for r in result["reasons"])
