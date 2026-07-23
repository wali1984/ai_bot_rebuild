"""Focused coverage for API ingestor-freshness timestamp extraction."""

from __future__ import annotations

import time

from v2.backend.app.api.v2 import system_metrics


def test_extract_epoch_seconds_uses_fresh_numeric_derived_lifecycle_clock() -> None:
    """A current derived level is live even when its last source event is old."""
    now_ms = int(time.time() * 1000)
    result = system_metrics._extract_epoch_seconds(
        {
            "event_time": now_ms - 15 * 60 * 1000,
            "generated_at": now_ms,
            "available_at": now_ms,
            "feature_cutoff": now_ms - 15 * 60 * 1000,
        }
    )

    assert result is not None
    assert abs(result - now_ms / 1000) < 0.01
