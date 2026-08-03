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


def _snap(t_ms: int, depth_usd: float, depth_level: int = 20) -> dict:
    return {
        "available_at": t_ms,
        "depth_level": depth_level,
        "depth_20_bid_usd": depth_usd / 2.0,
        "depth_20_ask_usd": depth_usd / 2.0,
        "best_bid": 100.0,
        "best_ask": 100.01,
        "depth_imbalance": 0.1,
    }


class TestDepthPersistenceStratification:
    """F-0010: persistence must compare like-with-like book views and carry
    an explicit reason instead of a silent 0.0."""

    def test_stable_single_stratum_window_scores_positive(self):
        from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
            compute_orderbook_adversarial_features,
        )
        rows = [_snap(1_000_000 + i * 250, 50_000.0 + (i % 3) * 100.0) for i in range(25)]
        out = compute_orderbook_adversarial_features(exchange="binance", symbol="XUSDT", snapshots=rows)
        assert out["depth_persistence_ms"] >= 5000
        assert out["depth_persistence_reason"] == "STABLE_DEPTH_WINDOW"
        assert out["depth_series_stratum"] == "depth_level:20"

    def test_mixed_strata_no_longer_pins_zero(self):
        # The production bug: interleaved 5/10/20-level streams, each stable,
        # but cross-strata min/max ~0.2 -> old code returned 0 for everything.
        from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
            compute_orderbook_adversarial_features,
        )
        rows = []
        for i in range(24):
            level = (5, 10, 20)[i % 3]
            depth = {5: 10_000.0, 10: 25_000.0, 20: 55_000.0}[level]
            rows.append(_snap(1_000_000 + i * 300, depth + (i % 2) * 50.0, depth_level=level))
        out = compute_orderbook_adversarial_features(exchange="binance", symbol="XUSDT", snapshots=rows)
        assert out["depth_persistence_ms"] > 0
        assert out["depth_persistence_reason"] == "STABLE_DEPTH_WINDOW"
        assert out["depth_series_stratum"] == "depth_level:20"

    def test_unstable_window_reports_depth_unstable(self):
        from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
            compute_orderbook_adversarial_features,
        )
        rows = [_snap(1_000_000 + i * 250, 50_000.0 if i % 2 else 5_000.0) for i in range(20)]
        out = compute_orderbook_adversarial_features(exchange="binance", symbol="XUSDT", snapshots=rows)
        assert out["depth_persistence_ms"] == 0
        assert out["depth_persistence_reason"] == "DEPTH_UNSTABLE"

    def test_insufficient_window_reports_reason(self):
        from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
            compute_orderbook_adversarial_features,
        )
        rows = [_snap(1_000_000 + i * 250, 50_000.0) for i in range(3)]
        out = compute_orderbook_adversarial_features(exchange="binance", symbol="XUSDT", snapshots=rows)
        assert out["depth_persistence_ms"] == 0
        assert out["depth_persistence_reason"] == "INSUFFICIENT_DEPTH_WINDOW"

    def test_missing_depth_fields_reports_reason(self):
        from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
            compute_orderbook_adversarial_features,
        )
        rows = [
            {"available_at": 1_000_000 + i * 250, "depth_level": 20,
             "depth_20_bid_usd": 0.0, "depth_20_ask_usd": 0.0}
            for i in range(10)
        ]
        out = compute_orderbook_adversarial_features(exchange="binance", symbol="XUSDT", snapshots=rows)
        assert out["depth_persistence_ms"] == 0
        assert out["depth_persistence_reason"] == "MISSING_DEPTH_FIELDS"

    def test_empty_snapshots_reports_insufficient(self):
        from v2.backend.app.services.microstructure_trust.orderbook_adversarial_features import (
            compute_orderbook_adversarial_features,
        )
        out = compute_orderbook_adversarial_features(exchange="binance", symbol="XUSDT", snapshots=[])
        assert out["depth_persistence_ms"] == 0
        assert out["depth_persistence_reason"] == "INSUFFICIENT_DEPTH_WINDOW"
