from __future__ import annotations

from v2.backend.app.services.microstructure_trust.status import (
    final_a_plus_trust_gate_status,
    microstructure_composite_trust_status,
)
from v2.backend.app.services.microstructure_trust.trust_score import (
    FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
    PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
    REDUCED_SIZE_BOOTSTRAP_TIER,
    score_microstructure_trust,
)


def _feed() -> dict[str, object]:
    return {
        "feed_quality_score": 0.9,
        "latency_ms": 100.0,
        "adaptive_latency_bound_ms": 750.0,
        "sequence_gap_count": 0,
        "unrepaired_sequence_gap": False,
        "fail_closed": False,
        "generated_at": "2026-07-06T12:00:00Z",
    }


def _adversarial() -> dict[str, object]:
    return {
        "depth_persistence_ms": 6000,
        "cancel_burst_score": 0.0,
        "quote_stuffing_score": 0.0,
        "top_book_pull_rate": 0.0,
        "book_trade_divergence_score": 0.0,
        "spread_expansion_rate": 0.0,
        "depth_collapse_bps": 0.0,
        "price_impact_instability_score": 0.0,
        "insufficient_book_history": False,
        "generated_at": "2026-07-06T12:00:00Z",
    }


def _tape() -> dict[str, object]:
    return {
        "trade_tape_confirmation_score": 0.8,
        "book_trade_divergence_score": 0.0,
        "generated_at": "2026-07-06T12:00:00Z",
    }


def _cross(score: float = 0.75, venues: int = 2) -> dict[str, object]:
    return {
        "cross_venue_confirmation_score": score,
        "venues_present": venues,
        "imbalance_conflict": False,
        "generated_at": "2026-07-06T12:00:00Z",
    }


def _sweep() -> dict[str, object]:
    return {
        "sweep_risk": 0.1,
        "cascade_risk": 0.1,
        "direction_uncertain": False,
        "risk_action": "ALLOW",
        "oi_funding_long_short_confirmation_pass": True,
        "generated_at": "2026-07-06T12:00:00Z",
    }


def test_public_orderbook_score_is_capped_and_not_final_a_plus_alone() -> None:
    trust = score_microstructure_trust(
        symbol="BTCUSDT",
        timeframe="1m",
        feed_quality=_feed(),
        adversarial_features=_adversarial(),
        trade_tape=_tape(),
        cross_venue=_cross(),
        sweep_risk=_sweep(),
    )

    assert trust["public_orderbook_trust_score"] <= PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP
    assert trust["orderbook_trust_score"] == trust["public_orderbook_trust_score"]
    assert trust["composite_microstructure_trust_score"] >= FINAL_A_PLUS_MIN_COMPOSITE_TRUST
    assert trust["microstructure_trust_score"] == trust["composite_microstructure_trust_score"]
    assert trust["public_book_can_approve_trade_alone"] is False
    assert trust["final_a_plus_eligible"] is True


def test_composite_cannot_cross_final_threshold_with_missing_confirmation() -> None:
    trust = score_microstructure_trust(
        symbol="BTCUSDT",
        timeframe="1m",
        feed_quality=_feed(),
        adversarial_features=_adversarial(),
        trade_tape=_tape(),
        cross_venue=_cross(score=0.4, venues=1),
        sweep_risk=_sweep(),
    )

    assert trust["public_orderbook_trust_score"] <= PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP
    assert trust["composite_microstructure_trust_score"] < FINAL_A_PLUS_MIN_COMPOSITE_TRUST
    assert "cross_venue_confirmation_pass" in trust["composite_confirmation_missing_fields"]
    assert trust["reduced_size_bootstrap_tier"] == REDUCED_SIZE_BOOTSTRAP_TIER
    assert trust["reduced_size_counts_as_final_a_plus"] is False
    assert trust["reduced_size_routes_to_live"] is False
    assert trust["reduced_size_paper_only"] is True


def test_status_hard_fails_composite_missing_above_threshold() -> None:
    rows = [
        {
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "microstructure_trust_score": 0.72,
            "public_orderbook_trust_score": 0.51,
            "final_a_plus_eligible": True,
        }
    ]

    composite = microstructure_composite_trust_status(rows)
    final_gate = final_a_plus_trust_gate_status(rows)

    assert composite["hard_fail"] is True
    assert "COMPOSITE_SCORE_SILENTLY_DEFAULTS_ABOVE_FINAL_THRESHOLD" in composite["hard_fail_reasons"]
    assert final_gate["hard_fail"] is True
    assert "COMPOSITE_TRUST_MISSING_BUT_CANDIDATE_PASSES_FINAL_A_PLUS" in final_gate["hard_fail_reasons"]
