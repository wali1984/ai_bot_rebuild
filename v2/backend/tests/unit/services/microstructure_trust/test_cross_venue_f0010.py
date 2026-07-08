"""F-0010 cross-venue confirmation honesty tests.

Rules under test:
- overlap symbols get a real two-venue score
- Binance-only symbols cannot fake a cross-venue pass
- missing KuCoin does not crash the evaluator
- a venue without depth evidence cannot zero out another venue's
  persistence via the multi-exchange combiner, and is reported unavailable
"""
from __future__ import annotations

from v2.backend.app.services.microstructure_trust.cross_venue_confirmation import (
    evaluate_cross_venue_confirmation,
)


def _book(mid: float, depth: float, imbalance: float = 0.1) -> dict:
    half = 0.01
    return {
        "best_bid": mid - half,
        "best_ask": mid + half,
        "orderbook_depth_usd": depth,
        "depth_imbalance": imbalance,
    }


class TestCrossVenueHonesty:
    def test_overlap_symbol_two_agreeing_venues_scores_high(self):
        out = evaluate_cross_venue_confirmation(
            symbol="ETHUSDT",
            binance=_book(1770.0, 500_000.0, 0.1),
            kucoin=_book(1770.05, 450_000.0, 0.12),
        )
        assert out["venues_present"] == 2
        assert out["lead_lag_classification"] == "venues_confirm"
        assert out["cross_venue_confirmation_score"] >= 0.5

    def test_binance_only_cannot_fake_pass(self):
        out = evaluate_cross_venue_confirmation(
            symbol="SYNUSDT",
            binance=_book(0.5, 20_000.0),
            kucoin=None,
        )
        assert out["venues_present"] == 1
        assert out["kucoin_present"] is False
        assert out["lead_lag_classification"] == "single_venue_unconfirmed"
        assert out["cross_venue_confirmation_score"] <= 0.45

    def test_missing_both_venues_does_not_crash(self):
        out = evaluate_cross_venue_confirmation(symbol="XUSDT", binance=None, kucoin=None)
        assert out["venues_present"] == 0
        assert out["cross_venue_confirmation_score"] <= 0.45

    def test_venue_conflict_detected(self):
        out = evaluate_cross_venue_confirmation(
            symbol="ETHUSDT",
            binance=_book(1770.0, 500_000.0, 0.4),
            kucoin=_book(1770.05, 450_000.0, -0.4),
        )
        assert out["lead_lag_classification"] == "venue_conflict"
        assert out["cross_venue_confirmation_score"] < 0.5


class TestCombinerUnavailableVenue:
    def test_no_evidence_venue_cannot_zero_out_persistence(self):
        from v2.backend.app.cli.v2_microstructure_feed_quality_monitor import (
            _combine_adversarial,
        )
        binance_row = {
            "exchange": "binance",
            "depth_persistence_ms": 4200,
            "depth_persistence_reason": "STABLE_DEPTH_WINDOW",
            "depth_series_stratum": "depth_level:20",
        }
        kucoin_row = {
            "exchange": "kucoin",
            "depth_persistence_ms": 0,
            "depth_persistence_reason": "INSUFFICIENT_DEPTH_WINDOW",
            "depth_series_stratum": None,
        }
        out = _combine_adversarial([binance_row, kucoin_row], symbol="ETHUSDT")
        assert out["depth_persistence_ms"] == 4200
        assert out["depth_persistence_reason"] == "STABLE_DEPTH_WINDOW"
        assert out["depth_persistence_unavailable_exchanges"] == ["kucoin"]

    def test_two_evidenced_venues_take_conservative_min(self):
        from v2.backend.app.cli.v2_microstructure_feed_quality_monitor import (
            _combine_adversarial,
        )
        rows = [
            {"exchange": "binance", "depth_persistence_ms": 5000,
             "depth_persistence_reason": "STABLE_DEPTH_WINDOW"},
            {"exchange": "kucoin", "depth_persistence_ms": 0,
             "depth_persistence_reason": "DEPTH_UNSTABLE"},
        ]
        out = _combine_adversarial(rows, symbol="ETHUSDT")
        assert out["depth_persistence_ms"] == 0
        assert out["depth_persistence_reason"] == "DEPTH_UNSTABLE"
        assert out["depth_persistence_unavailable_exchanges"] == []
