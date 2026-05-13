from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.cli.paper_shadow_metrics_analyzer import analyze_metrics


def test_negative_pnl_blocks_canary() -> None:
    result = analyze_metrics(
        {"elapsed_observation_seconds": 7 * 3600, "paper_pnl_current_usdt": -2.5},
        {"generated_at": "2026-05-13T00:00:00Z"},
        [
            {"paper_result": "FILLED_PAPER_ONLY", "paper_pnl_delta": -1.0, "symbol": "BTCUSDT", "confidence": 0.8},
            {"paper_result": "BLOCKED_PAPER_ONLY", "symbol": "ETHUSDT"},
        ],
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
    )

    assert "PAPER_PNL_NEGATIVE_BLOCKS_CANARY" in result["classifications"]
    assert "PAPER_SHADOW_24H_PENDING" in result["canary_blockers"]
    assert result["paper_runtime_called"] is False


def test_missing_24h_proof_remains_blocker_even_with_positive_pnl() -> None:
    result = analyze_metrics(
        {"elapsed_observation_seconds": 8 * 3600, "paper_pnl_current_usdt": 1.25},
        {"generated_at": "2026-05-13T00:00:00Z"},
        [{"paper_result": "FILLED_PAPER_ONLY", "paper_pnl_delta": 1.25, "confidence": 0.9}],
        now=datetime(2026, 5, 13, tzinfo=timezone.utc),
    )

    assert "PAPER_PNL_POSITIVE_BUT_NEEDS_24H" in result["classifications"]
    assert "PAPER_SHADOW_24H_PENDING" in result["canary_blockers"]
    assert "PAPER_EDGE_UNPROVEN" in result["classifications"]
