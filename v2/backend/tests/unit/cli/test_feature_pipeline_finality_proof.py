from __future__ import annotations

from v2.backend.app.cli.v2_feature_pipeline_native_loop import (
    _closed_klines_with_evidence,
    latest_unclosed_kline_exclusion_proof,
)


def test_finality_proven_when_latest_closed_at_or_before_decision():
    proven, method = latest_unclosed_kline_exclusion_proof(
        latest_closed_kline={"close_time": 1000},
        latest_closed_kline_close_ms=1000,
        decision_ms=1000,
    )
    assert proven is True
    assert method == "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1"


def test_finality_proven_strictly_before_decision():
    proven, _ = latest_unclosed_kline_exclusion_proof(
        latest_closed_kline={"close_time": 900},
        latest_closed_kline_close_ms=900,
        decision_ms=1000,
    )
    assert proven is True


def test_finality_unproven_when_no_closed_kline():
    proven, method = latest_unclosed_kline_exclusion_proof(
        latest_closed_kline=None, latest_closed_kline_close_ms=None, decision_ms=1000
    )
    assert proven is False
    assert method == "NO_CLOSED_KLINE_LATEST_UNCLOSED_EXCLUSION_UNPROVEN"


def test_finality_unproven_when_close_after_decision_no_lookahead():
    # A close AFTER the decision instant must NOT be credited as excluded — that
    # would be lookahead. The filter never produces such a latest_closed_kline,
    # but the proof is defensively fail-closed.
    proven, _ = latest_unclosed_kline_exclusion_proof(
        latest_closed_kline={"close_time": 1100},
        latest_closed_kline_close_ms=1100,
        decision_ms=1000,
    )
    assert proven is False


def test_closed_filter_excludes_unfinished_and_future_keeps_bounded():
    klines = [
        {"is_closed": True, "close_time": 500},
        {"is_closed": True, "close_time": 900},
        {"is_closed": False, "close_time": 1400},  # unfinished -> excluded
        {"is_closed": True, "close_time": 1500},  # future close -> excluded
    ]
    closed, latest, evidence = _closed_klines_with_evidence(klines, decision_ms=1000)
    assert [row["close_time"] for row in closed] == [500, 900]
    assert latest["close_time"] == 900
    assert evidence["unfinished_kline_excluded_count"] == 1
    assert evidence["future_close_kline_excluded_count"] == 1
    # Finality is proven from the filter's own decision-time-bounded output.
    proven, _ = latest_unclosed_kline_exclusion_proof(
        latest_closed_kline=latest,
        latest_closed_kline_close_ms=latest["close_time"],
        decision_ms=1000,
    )
    assert proven is True
