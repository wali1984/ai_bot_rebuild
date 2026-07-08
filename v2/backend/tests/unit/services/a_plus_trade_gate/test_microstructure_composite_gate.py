from __future__ import annotations

from v2.backend.app.services.a_plus_trade_gate.service import APlusGateConfig, _microstructure_check
from v2.backend.app.services.microstructure_trust.trust_score import (
    FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
)


def _confirmed_payload(score: float = 0.72) -> dict[str, object]:
    return {
        "public_orderbook_trust_score": 0.51,
        "composite_microstructure_trust_score": score,
        "orderbook_trust_tier": "NORMAL_SIZE_ALLOWED",
        "microstructure_action": "ALLOW",
        "public_book_can_approve_trade_alone": False,
        "public_orderbook_can_produce_final_a_plus": False,
        "feed_integrity_pass": True,
        "sequence_gap_free": True,
        "latency_within_bound": True,
        "trade_tape_confirmation_pass": True,
        "cross_venue_confirmation_pass": True,
        "liquidation_sweep_risk_acceptable": True,
        "oi_funding_long_short_confirmation_pass": True,
        "real_spread_depth_cost_evidence_pass": True,
        "composite_confirmation_missing_fields": [],
    }


def test_microstructure_check_rejects_public_book_only_payload() -> None:
    result = _microstructure_check(
        microstructure_trust={
            "public_orderbook_trust_score": 0.51,
            "orderbook_trust_score": 0.82,
            "orderbook_trust_tier": "HIGH_TRUST",
            "microstructure_action": "ALLOW",
        },
        config=APlusGateConfig(),
    )

    assert result["passed"] is False
    assert result["missing_evidence"] is True
    assert result["reason"] == "COMPOSITE_MICROSTRUCTURE_TRUST_SCORE_MISSING"


def test_microstructure_check_requires_all_composite_confirmations() -> None:
    payload = _confirmed_payload()
    payload["cross_venue_confirmation_pass"] = False
    payload["composite_confirmation_missing_fields"] = ["cross_venue_confirmation_pass"]

    result = _microstructure_check(microstructure_trust=payload, config=APlusGateConfig())

    assert result["passed"] is False
    assert result["missing_evidence"] is True
    assert result["reason"].startswith("COMPOSITE_CONFIRMATION_MISSING:")


def test_microstructure_check_passes_confirmed_composite_score() -> None:
    result = _microstructure_check(
        microstructure_trust=_confirmed_payload(FINAL_A_PLUS_MIN_COMPOSITE_TRUST),
        config=APlusGateConfig(),
    )

    assert result["passed"] is True


def test_microstructure_check_rejects_reduced_size_as_final_a_plus() -> None:
    payload = _confirmed_payload(0.59)
    payload["orderbook_trust_tier"] = "REDUCED_SIZE"
    payload["microstructure_action"] = "REDUCE_SIZE"
    payload["bootstrap_reduced_size_paper_only"] = True

    result = _microstructure_check(microstructure_trust=payload, config=APlusGateConfig())

    assert result["passed"] is False
    assert "REDUCED_SIZE_BOOTSTRAP_NOT_FINAL_A_PLUS" in result["reason"]
