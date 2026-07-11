from __future__ import annotations

from v2.backend.app.services.microstructure_trust.feed_quality import evaluate_feed_quality, summarize_feed_quality


def test_feed_quality_fails_closed_when_available_after_decision() -> None:
    row = evaluate_feed_quality(
        exchange="binance",
        symbol="BTCUSDT",
        event_time="2026-07-02T12:00:00.000Z",
        transaction_time="2026-07-02T12:00:00.050Z",
        received_at="2026-07-02T12:00:00.100Z",
        available_at="2026-07-02T12:00:02.000Z",
        decision_time="2026-07-02T12:00:01.000Z",
    )

    assert row["fail_closed"] is True
    assert "AVAILABLE_AT_AFTER_DECISION_TIME" in row["fail_reasons"]
    assert row["local_latency_ms"] == 1950


def test_feed_quality_uses_observed_latency_when_event_time_missing() -> None:
    row = evaluate_feed_quality(
        exchange="binance",
        symbol="ETHUSDT",
        received_at="2026-07-02T12:00:00.000Z",
        available_at="2026-07-02T12:00:00.000Z",
        decision_time="2026-07-02T12:00:00.500Z",
        observed_local_latency_ms=42,
    )

    assert row["local_latency_ms"] == 42
    assert row["local_latency_source"] == "observed_local_latency_ms"
    assert "LOCAL_LATENCY_MISSING" not in row["fail_reasons"]


def test_feed_quality_uses_explicit_observed_latency_when_exchange_timestamps_exist() -> None:
    row = evaluate_feed_quality(
        exchange="binance",
        symbol="SOLUSDT",
        event_time="2026-07-02T12:00:00.000Z",
        transaction_time="2026-07-02T12:00:00.000Z",
        received_at="2026-07-02T12:00:03.000Z",
        available_at="2026-07-02T12:00:03.000Z",
        decision_time="2026-07-02T12:00:03.100Z",
        observed_local_latency_ms=96,
    )

    assert row["timestamp_delta_latency_ms"] == 3000
    assert row["observed_local_latency_ms"] == 96
    assert row["local_latency_ms"] == 96
    assert row["local_latency_source"] == "observed_local_latency_ms"
    assert "LATENCY_ABOVE_ADAPTIVE_BOUND" not in row["fail_reasons"]


def test_feed_quality_summary_counts_sequence_gaps() -> None:
    rows = [
        evaluate_feed_quality(exchange="binance", symbol="BTCUSDT", sequence_gap_count=1, unrepaired_sequence_gap=True),
        evaluate_feed_quality(exchange="kucoin", symbol="BTCUSDT"),
    ]

    summary = summarize_feed_quality(rows)

    assert summary["rows"] == 2
    assert summary["sequence_gap_rows"] == 1
    assert summary["fail_closed_rows"] >= 1
