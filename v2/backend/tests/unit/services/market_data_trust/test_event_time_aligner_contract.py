from __future__ import annotations

from v2.backend.app.services.market_state_integrity import (
    EventTimeAligner,
    build_market_state_envelope_from_snapshot,
)


def test_event_time_aligner_rejects_unfinished_higher_timeframe() -> None:
    envelope = build_market_state_envelope_from_snapshot(
        {
            "symbol": "BTCUSDT",
            "exchange": "binance",
            "decision_time": "2026-06-11T00:01:05Z",
            "generated_at": "2026-06-11T00:01:05Z",
            "timeframe": "1m",
            "feature_cutoff": "2026-06-11T00:01:00Z",
            "timeframe_cutoffs": {
                "1m": "2026-06-11T00:01:00Z",
                "5m": "2026-06-11T00:05:00Z",
            },
            "feature_hash": "aligner_hash",
            "data_quality_score": 0.95,
            "is_final_candle": True,
        }
    )
    result = EventTimeAligner().evaluate(envelope=envelope)
    assert result.accepted is False
    assert "mixed_timeframe_cutoff:5m" in result.reject_reasons
