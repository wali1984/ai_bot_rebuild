from __future__ import annotations

from datetime import datetime, timedelta, timezone

from v2.backend.app.cli.paper_shadow_negative_pnl import (
    build_fill_quality_audit,
    build_negative_pnl_diagnosis,
    events_with_pnl_delta,
)


def _event(index: int, *, confidence: float = 0.7, reason: str = "allow_proceed_long") -> dict[str, object]:
    generated_at = (datetime(2026, 5, 13, tzinfo=timezone.utc) + timedelta(seconds=index * 30)).isoformat().replace("+00:00", "Z")
    return {
        "generated_at": generated_at,
        "symbol": "BTCUSDT",
        "paper_result": "FILLED_PAPER_ONLY",
        "ledger_action": "PAPER_FILL_SIMULATED",
        "risk_action": "allow",
        "risk_reason_code": reason,
        "confidence": confidence,
        "fee_usdt": 0.01,
        "paper_realized_pnl": round(-0.01 * index, 2),
    }


def test_events_with_pnl_delta_preserves_lineage_and_computes_delta() -> None:
    rows = events_with_pnl_delta([_event(2), _event(1)])

    assert rows[0]["generated_at"] == "2026-05-13T00:00:30Z"
    assert rows[1]["paper_pnl_delta"] == -0.01


def test_negative_pnl_diagnosis_identifies_fee_drag_and_overtrading() -> None:
    events = [_event(index, confidence=0.62 if index % 3 == 0 else 0.78) for index in range(1, 121)]
    observation = {
        "paper_pnl_current_usdt": -1.2,
        "fees_slippage_funding_assumptions": {
            "slippage_bps": 2,
            "funding": "zero_until_funding_feed_adapter_current",
        },
    }

    diagnosis = build_negative_pnl_diagnosis(observation, events)

    assert "PAPER_PNL_NEGATIVE_EARLY_WINDOW" in diagnosis["classifications"]
    assert "PAPER_PNL_NEGATIVE_FEES_SLIPPAGE_DRAG" in diagnosis["classifications"]
    assert "PAPER_PNL_NEGATIVE_OVERTRADING" in diagnosis["classifications"]
    assert diagnosis["paper_pnl_current_usdt"] == -1.2
    assert diagnosis["win_rate"] == 0


def test_fill_quality_audit_flags_high_frequency_and_low_confidence() -> None:
    events = [
        _event(index, confidence=0.6 if index % 2 == 0 else 0.8, reason="allow_proceed_long" if index % 2 else "allow_proceed_short")
        for index in range(1, 91)
    ]

    audit = build_fill_quality_audit(events)

    assert "FILL_RATE_TOO_HIGH" in audit["classifications"]
    assert "LOW_CONFIDENCE_FILL_RISK" in audit["classifications"]
    assert audit["paper_engine_should_throttle_fills_for_canary_simulation"] is True
    assert audit["cooldown_should_be_tested"] is True
