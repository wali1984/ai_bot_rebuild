"""Timeframe-aware, latency-gated forgiveness of batch-cadence book age.

The batch orderbook recorder writes each symbol's book in bursts, so a fresh
feed still shows book_update_age ~2s between bursts, tripping the 1.5s scalping
staleness bound and clamping microstructure trust to 0.24 -- which blocked
A-grade universally even on a 500ms-fresh BTC feed. For directional (1m+)
decisions this age is adequate when the feed LATENCY is fresh, so a
BOOK_UPDATE_AGE_TOO_HIGH-only fail_closed is forgiven within a timeframe-scaled
tolerance. Genuinely stale/untrustworthy feeds are still fail-closed.
"""
from __future__ import annotations

from tests.unit.services.microstructure_trust.test_composite_trust_semantics import (
    _adversarial,
    _cross,
    _sweep,
    _tape,
)

from v2.backend.app.services.microstructure_trust.trust_score import (
    FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
    score_microstructure_trust,
)


def _feed_batch_age(*, latency_ms=517.0, age_ms=1825, reasons=("BOOK_UPDATE_AGE_TOO_HIGH",)):
    return {
        "feed_quality_score": 0.9,
        "latency_ms": latency_ms,
        "local_latency_ms": latency_ms,
        "adaptive_latency_bound_ms": 750.0,
        "book_update_age_ms": age_ms,
        "stale_bound_ms": 1500.0,
        "sequence_gap_count": 0,
        "unrepaired_sequence_gap": False,
        "fail_closed": True,
        "fail_reasons": list(reasons),
        "all_feed_fail_reasons": list(reasons),
        "generated_at": "2026-07-06T12:00:00Z",
    }


def _score(feed, timeframe="1m"):
    return score_microstructure_trust(
        symbol="BTCUSDT",
        timeframe=timeframe,
        feed_quality=feed,
        adversarial_features=_adversarial(),
        trade_tape=_tape(),
        cross_venue=_cross(),
        sweep_risk=_sweep(),
    )


def test_fresh_feed_batch_age_is_forgiven_and_reaches_a_plus() -> None:
    # Fresh latency (517ms) + book-age-only fail + age within 1m tolerance (4.5s).
    trust = _score(_feed_batch_age())
    assert trust["book_age_fail_forgiven"] is True
    # Not clamped to 0.24 -> composite reaches the A+ threshold (was 0.24 before).
    assert trust["composite_microstructure_trust_score"] >= FINAL_A_PLUS_MIN_COMPOSITE_TRUST


def test_slow_feed_latency_is_not_forgiven() -> None:
    # A genuine latency failure means an untrustworthy feed -> stays clamped.
    feed = _feed_batch_age(
        latency_ms=900.0, reasons=("LATENCY_ABOVE_ADAPTIVE_BOUND", "BOOK_UPDATE_AGE_TOO_HIGH")
    )
    trust = _score(feed)
    assert trust["book_age_fail_forgiven"] is False
    assert trust["composite_microstructure_trust_score"] <= 0.24


def test_minutes_old_snapshot_is_not_forgiven() -> None:
    # A 135s-old book blows even the 1m tolerance (4.5s) -> stays clamped.
    trust = _score(_feed_batch_age(age_ms=135000))
    assert trust["book_age_fail_forgiven"] is False
    assert trust["composite_microstructure_trust_score"] <= 0.24


def test_non_age_hard_fail_is_not_forgiven() -> None:
    # A sequence gap (non-age) means the book is untrustworthy -> stays clamped.
    trust = _score(_feed_batch_age(reasons=("UNREPAIRED_SEQUENCE_GAP",)))
    assert trust["book_age_fail_forgiven"] is False
    assert trust["composite_microstructure_trust_score"] <= 0.24


def test_env_hard_revert_disables_forgiveness(monkeypatch) -> None:
    monkeypatch.setenv("V2_MICROSTRUCTURE_TF_AGE_FORGIVENESS", "0")
    trust = _score(_feed_batch_age())
    assert trust["book_age_fail_forgiven"] is False
    assert trust["composite_microstructure_trust_score"] <= 0.24


def test_non_book_confirmation_critical_soft_policy() -> None:
    from v2.backend.app.services.microstructure_trust.trust_score import (
        _non_book_confirmation_pass,
    )

    def flags(**over):
        base = {
            "feed_integrity_pass": True,
            "sequence_gap_free": True,
            "latency_within_bound": True,
            "liquidation_sweep_risk_acceptable": True,
            "trade_tape_confirmation_pass": True,
            "cross_venue_confirmation_pass": True,
            "real_spread_depth_cost_evidence_pass": True,
            "oi_funding_long_short_confirmation_pass": True,
        }
        base.update(over)
        return base

    # All pass -> pass.
    assert _non_book_confirmation_pass(flags()) is True
    # A critical failure -> fail, even with every soft flag passing.
    assert _non_book_confirmation_pass(flags(latency_within_bound=False)) is False
    assert _non_book_confirmation_pass(flags(liquidation_sweep_risk_acceptable=False)) is False
    # One soft failure (1 of 4 soft) -> 75% soft >= 60% -> still passes.
    assert _non_book_confirmation_pass(flags(cross_venue_confirmation_pass=False)) is True
    # Three soft failures (1 of 4 soft = 25% < 60%) -> fails.
    assert _non_book_confirmation_pass(
        flags(cross_venue_confirmation_pass=False, trade_tape_confirmation_pass=False,
              real_spread_depth_cost_evidence_pass=False)
    ) is False


def test_env_strict_requires_all_confirmations(monkeypatch) -> None:
    from v2.backend.app.services.microstructure_trust.trust_score import (
        _non_book_confirmation_pass,
    )

    monkeypatch.setenv("V2_MICROSTRUCTURE_ALL_CONFIRMATIONS_REQUIRED", "1")
    passes = {"feed_integrity_pass": True, "latency_within_bound": True,
              "sequence_gap_free": True, "liquidation_sweep_risk_acceptable": True,
              "cross_venue_confirmation_pass": False}
    # Strict mode: a single soft failure fails again.
    assert _non_book_confirmation_pass(passes) is False


def test_tight_timeframe_tolerance_scales() -> None:
    # 15m tolerates a larger book age (15s) than 1m (4.5s); a 6s book age is
    # forgiven at 15m but NOT at 1m... actually 6s > 4.5s so 1m rejects it.
    feed = _feed_batch_age(age_ms=6000)
    assert _score(feed, timeframe="15m")["book_age_fail_forgiven"] is True
    assert _score(feed, timeframe="1m")["book_age_fail_forgiven"] is False
