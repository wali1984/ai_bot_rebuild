"""Final microstructure trust score and action classification."""
from __future__ import annotations

from enum import StrEnum
from typing import Any, Mapping

from .feed_quality import iso_now


PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP = 0.51
FINAL_A_PLUS_MIN_COMPOSITE_TRUST = 0.60
REDUCED_SIZE_BOOTSTRAP_TIER = "A_PLUS_BOOTSTRAP_REDUCED_SIZE_PAPER_ONLY"


class MicrostructureAction(StrEnum):
    ALLOW = "ALLOW"
    REDUCE_SIZE = "REDUCE_SIZE"
    SHADOW_ONLY = "SHADOW_ONLY"
    NO_TRADE = "NO_TRADE"
    CLOSE_OR_REDUCE_ONLY = "CLOSE_OR_REDUCE_ONLY"


def _float(payload: Mapping[str, Any] | None, *keys: str, default: float | None = None) -> float | None:
    if not isinstance(payload, Mapping):
        return default
    for key in keys:
        value = payload.get(key)
        try:
            if value is None:
                continue
            out = float(value)
        except (TypeError, ValueError):
            continue
        if out == out and out not in (float("inf"), float("-inf")):
            return out
    return default


def _has_timestamp(payload: Mapping[str, Any] | None) -> bool:
    return isinstance(payload, Mapping) and bool(payload.get("available_at") or payload.get("generated_at"))


def _pass(value: bool) -> bool:
    return bool(value)


def _orderbook_adversarial_score(
    *,
    cancel_pressure: float,
    stuffing: float,
    pull: float,
    divergence: float,
) -> float:
    return max(
        0.0,
        1.0
        - (
            (cancel_pressure * 0.25)
            + (stuffing * 0.15)
            + (pull * 0.2)
            + (divergence * 0.25)
        ),
    )


def _confirmation_flags(
    *,
    feed_quality: Mapping[str, Any] | None,
    adversarial_features: Mapping[str, Any] | None,
    trade_tape: Mapping[str, Any] | None,
    cross_venue: Mapping[str, Any] | None,
    sweep_risk: Mapping[str, Any] | None,
) -> dict[str, bool]:
    latency_ms = _float(feed_quality, "latency_ms", "local_latency_ms")
    latency_bound = _float(feed_quality, "adaptive_latency_bound_ms", default=750.0) or 750.0
    sequence_gap_count = int(_float(feed_quality, "sequence_gap_count", default=1.0) or 0)
    feed_score = _float(feed_quality, "feed_quality_score", default=0.0) or 0.0
    tape_score = _float(trade_tape, "trade_tape_confirmation_score")
    cross_score = _float(cross_venue, "cross_venue_confirmation_score")
    venues_present = int(_float(cross_venue, "venues_present", default=0.0) or 0)
    sweep = _float(sweep_risk, "sweep_risk")
    cascade = _float(sweep_risk, "cascade_risk")
    spread_expansion_value = _float(adversarial_features, "spread_expansion_rate")
    spread_expansion = 1.0 if spread_expansion_value is None else spread_expansion_value
    depth_collapse_value = _float(adversarial_features, "depth_collapse_bps")
    depth_collapse_bps = 10000.0 if depth_collapse_value is None else depth_collapse_value
    price_impact_value = _float(adversarial_features, "price_impact_instability_score")
    price_impact_instability = 1.0 if price_impact_value is None else price_impact_value
    depth_persistence_ms = _float(adversarial_features, "depth_persistence_ms", default=0.0) or 0.0

    return {
        "feed_integrity_pass": _pass(
            isinstance(feed_quality, Mapping)
            and feed_quality.get("fail_closed") is not True
            and feed_score >= 0.50
        ),
        "sequence_gap_free": _pass(
            isinstance(feed_quality, Mapping)
            and sequence_gap_count == 0
            and feed_quality.get("unrepaired_sequence_gap") is not True
        ),
        "latency_within_bound": _pass(
            isinstance(feed_quality, Mapping)
            and latency_ms is not None
            and latency_ms <= latency_bound
        ),
        "trade_tape_confirmation_pass": _pass(
            _has_timestamp(trade_tape)
            and tape_score is not None
            and tape_score >= 0.60
            and _float(trade_tape, "book_trade_divergence_score", default=1.0) == 0.0
        ),
        "cross_venue_confirmation_pass": _pass(
            _has_timestamp(cross_venue)
            and cross_score is not None
            and cross_score >= 0.60
            and venues_present >= 2
            and cross_venue.get("imbalance_conflict") is not True
        ),
        "liquidation_sweep_risk_acceptable": _pass(
            _has_timestamp(sweep_risk)
            and sweep is not None
            and cascade is not None
            and max(sweep, cascade) < 0.55
            and sweep_risk.get("direction_uncertain") is not True
            and str(sweep_risk.get("risk_action") or "").upper() != "NO_TRADE"
        ),
        "oi_funding_long_short_confirmation_pass": _pass(
            isinstance(sweep_risk, Mapping)
            and sweep_risk.get("oi_funding_long_short_confirmation_pass") is True
        ),
        "real_spread_depth_cost_evidence_pass": _pass(
            _has_timestamp(adversarial_features)
            and adversarial_features.get("insufficient_book_history") is not True
            and depth_persistence_ms > 0.0
            and spread_expansion <= 0.50
            and depth_collapse_bps <= 2500.0
            and price_impact_instability <= 0.50
        ),
    }


def classify_microstructure_trust(score: float | None, *, position_open: bool = False) -> tuple[str, MicrostructureAction]:
    if score is None:
        return "UNTRUSTED_NO_TRADE", MicrostructureAction.NO_TRADE
    score = max(0.0, min(1.0, float(score)))
    if score < 0.25:
        return "UNTRUSTED_NO_TRADE", MicrostructureAction.CLOSE_OR_REDUCE_ONLY if position_open else MicrostructureAction.NO_TRADE
    if score < 0.45:
        return "SHADOW_ONLY", MicrostructureAction.SHADOW_ONLY
    if score < 0.65:
        return "REDUCED_SIZE", MicrostructureAction.REDUCE_SIZE
    if score < 0.80:
        return "NORMAL_SIZE_ALLOWED", MicrostructureAction.ALLOW
    return "HIGH_TRUST", MicrostructureAction.ALLOW


def score_microstructure_trust(
    *,
    symbol: str,
    timeframe: str,
    feed_quality: Mapping[str, Any] | None = None,
    adversarial_features: Mapping[str, Any] | None = None,
    trade_tape: Mapping[str, Any] | None = None,
    cross_venue: Mapping[str, Any] | None = None,
    sweep_risk: Mapping[str, Any] | None = None,
    realized_slippage_error: float | None = None,
    historical_bucket_performance: float | None = None,
    adaptive_minimum: float = 0.65,
    position_open: bool = False,
) -> dict[str, Any]:
    missing_components = [
        name
        for name, payload in (
            ("feed_quality", feed_quality),
            ("adversarial_features", adversarial_features),
            ("trade_tape_confirmation", trade_tape),
            ("cross_venue_confirmation", cross_venue),
            ("sweep_risk", sweep_risk),
        )
        if not isinstance(payload, Mapping)
    ]
    feed_score = _float(feed_quality, "feed_quality_score", default=0.0) or 0.0
    persistence = min(1.0, (_float(adversarial_features, "depth_persistence_ms", default=0.0) or 0.0) / 5000.0)
    cancel_value = _float(adversarial_features, "cancel_burst_score")
    cancel_pressure = 1.0 if cancel_value is None else cancel_value
    stuffing_value = _float(adversarial_features, "quote_stuffing_score")
    stuffing = 1.0 if stuffing_value is None else stuffing_value
    pull_value = _float(adversarial_features, "top_book_pull_rate")
    pull = 1.0 if pull_value is None else pull_value
    divergence_value = _float(adversarial_features, "book_trade_divergence_score")
    divergence = 1.0 if divergence_value is None else divergence_value
    tape_score = _float(trade_tape, "trade_tape_confirmation_score", default=0.0) or 0.0
    cross_score = _float(cross_venue, "cross_venue_confirmation_score", default=0.0) or 0.0
    sweep = _float(sweep_risk, "sweep_risk", default=1.0) or 1.0
    cascade = _float(sweep_risk, "cascade_risk", default=1.0) or 1.0
    slippage_penalty = min(1.0, abs(realized_slippage_error or 0.0) / 15.0)
    bucket_score = max(0.0, min(1.0, historical_bucket_performance if historical_bucket_performance is not None else 0.5))
    adversarial_score = _orderbook_adversarial_score(
        cancel_pressure=cancel_pressure,
        stuffing=stuffing,
        pull=pull,
        divergence=divergence,
    )
    public_score = (
        feed_score * 0.30
        + persistence * 0.25
        + adversarial_score * 0.30
        + max(
            0.0,
            1.0
            - min(
                1.0,
                _float(adversarial_features, "price_impact_instability_score", default=1.0),
            ),
        )
        * 0.15
    )
    public_score = max(0.0, min(PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP, public_score))

    confirmation_passes = _confirmation_flags(
        feed_quality=feed_quality,
        adversarial_features=adversarial_features,
        trade_tape=trade_tape,
        cross_venue=cross_venue,
        sweep_risk=sweep_risk,
    )
    missing_confirmation_fields = [
        field for field, passed in confirmation_passes.items() if passed is not True
    ]
    non_book_confirmation_pass = all(confirmation_passes.values())
    composite_score = (
        feed_score * 0.18
        + persistence * 0.12
        + adversarial_score * 0.18
        + tape_score * 0.16
        + cross_score * 0.14
        + (1.0 - max(sweep, cascade)) * 0.14
        + (1.0 - slippage_penalty) * 0.04
        + bucket_score * 0.04
    )
    if not non_book_confirmation_pass:
        composite_score = min(composite_score, FINAL_A_PLUS_MIN_COMPOSITE_TRUST - 0.01)
    if missing_components:
        composite_score = min(composite_score, 0.44)
    if isinstance(feed_quality, Mapping) and feed_quality.get("fail_closed") is True:
        composite_score = min(composite_score, 0.24)
    if isinstance(sweep_risk, Mapping) and sweep_risk.get("direction_uncertain") is True:
        composite_score = min(composite_score, 0.24)
    composite_score = max(0.0, min(1.0, composite_score))
    tier, action = classify_microstructure_trust(composite_score, position_open=position_open)
    if composite_score < adaptive_minimum and action == MicrostructureAction.ALLOW:
        action = MicrostructureAction.REDUCE_SIZE
        tier = "REDUCED_SIZE"
    reduced_size_bootstrap_candidate = (
        tier == "REDUCED_SIZE"
        and public_score >= 0.45
        and composite_score < FINAL_A_PLUS_MIN_COMPOSITE_TRUST
    )
    final_a_plus_eligible = (
        composite_score >= FINAL_A_PLUS_MIN_COMPOSITE_TRUST
        and non_book_confirmation_pass
        and action == MicrostructureAction.ALLOW
    )
    return {
        "schema_version": "microstructure_trust_score_v2",
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "public_orderbook_default_trust": "LOW",
        "public_orderbook_default_trust_cap": PUBLIC_ORDERBOOK_DEFAULT_TRUST_CAP,
        "public_book_can_approve_trade_alone": False,
        "public_orderbook_can_produce_final_a_plus": False,
        "decision_requires_cross_validation": True,
        "final_a_plus_min_composite_trust": FINAL_A_PLUS_MIN_COMPOSITE_TRUST,
        "public_orderbook_trust_score": round(public_score, 8),
        "composite_microstructure_trust_score": round(composite_score, 8),
        "microstructure_trust_score": round(composite_score, 8),
        "orderbook_trust_score": round(public_score, 8),
        "orderbook_trust_tier": tier,
        "microstructure_action": str(action),
        "adaptive_minimum": float(adaptive_minimum),
        "eligible_for_a_grade": bool(final_a_plus_eligible),
        "final_a_plus_eligible": bool(final_a_plus_eligible),
        "final_a_plus_requires_composite_trust": True,
        "non_book_confirmation_pass": bool(non_book_confirmation_pass),
        "composite_confirmation_passes": confirmation_passes,
        "composite_confirmation_missing_fields": missing_confirmation_fields,
        **confirmation_passes,
        "missing_components": missing_components,
        "feed_latency_ms": _float(feed_quality, "latency_ms", "local_latency_ms"),
        "sequence_gap_flag": 1 if (feed_quality or {}).get("sequence_gap_count", 0) else 0,
        "spread_instability": _float(adversarial_features, "spread_expansion_rate"),
        "depth_persistence": persistence,
        "depth_persistence_reason": (adversarial_features or {}).get("depth_persistence_reason"),
        "depth_series_stratum": (adversarial_features or {}).get("depth_series_stratum"),
        "cancel_pressure": cancel_pressure,
        "book_trade_divergence": max(divergence, _float(trade_tape, "book_trade_divergence_score", default=0.0) or 0.0),
        "cross_venue_confirmation": cross_score,
        "sweep_risk": sweep,
        "oi_funding_long_short_confirmation": sweep_risk.get("oi_funding_long_short_confirmation_pass")
        if isinstance(sweep_risk, Mapping)
        else False,
        "post_sweep_reversal_probability": _float(sweep_risk, "post_sweep_reversal_probability"),
        "liquidation_cascade_risk": cascade,
        "realized_slippage_error": realized_slippage_error,
        "reduced_size_tier_allowed": True,
        "reduced_size_bootstrap_tier": REDUCED_SIZE_BOOTSTRAP_TIER
        if reduced_size_bootstrap_candidate
        else None,
        "reduced_size_counts_as_final_a_plus": False,
        "reduced_size_routes_to_live": False,
        "reduced_size_paper_only": True,
        "bootstrap_reduced_size_paper_only": bool(reduced_size_bootstrap_candidate),
        "generated_at": iso_now(),
    }
