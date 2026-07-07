from __future__ import annotations

from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
    compute_orderbook_adversarial_features,
)


def test_orderbook_wall_pull_and_depth_collapse_are_detected() -> None:
    rows = [
        {
            "available_at": "2026-07-02T12:00:00.000Z",
            "bids": [[100.0, 10.0], [99.5, 10.0]],
            "asks": [[100.5, 10.0], [101.0, 10.0]],
            "spread_bps": 5.0,
        },
        {
            "available_at": "2026-07-02T12:00:00.500Z",
            "bids": [[100.0, 1.0], [99.5, 2.0]],
            "asks": [[100.5, 8.0], [101.0, 8.0]],
            "spread_bps": 8.0,
        },
    ]

    features = compute_orderbook_adversarial_features(exchange="binance", symbol="BTCUSDT", snapshots=rows)

    assert features["top_book_pull_rate"] > 0.5
    assert features["depth_collapse_bps"] > 1000
    assert features["spread_expansion_rate"] > 0.0


def test_missing_book_history_is_untrusted() -> None:
    features = compute_orderbook_adversarial_features(exchange="binance", symbol="BTCUSDT", snapshots=[])

    assert features["insufficient_book_history"] is True
    assert features["cancel_burst_score"] == 1.0
    assert features["depth_persistence_ms"] == 0
