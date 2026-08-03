"""Liquidation sweep and fakeout risk scoring."""
from __future__ import annotations

from typing import Any, Mapping

from .feed_quality import iso_now


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def detect_liquidation_sweep(
    *,
    symbol: str,
    timeframe: str,
    liquidation_context: Mapping[str, Any] | None = None,
    long_short_ratio: float | None = None,
    funding_rate: float | None = None,
    open_interest_change_pct: float | None = None,
    mark_index_divergence_bps: float | None = None,
    depth_collapse_bps: float | None = None,
    trade_tape_acceleration: float | None = None,
    trade_imbalance: float | None = None,
    cross_venue_basis_bps: float | None = None,
) -> dict[str, Any]:
    liq = liquidation_context or {}

    def _first_float(*keys: str) -> float | None:
        # Explicit None-checked chain: `a or b` skips honest 0.0 values.
        for key in keys:
            value = _float(liq.get(key))
            if value is not None:
                return value
        return None

    # cascade carries intensity-percentile semantics (v2): how extreme the
    # symbol's current liquidation activity is vs its own rolling history.
    # It is DIRECTIONLESS — direction comes from liquidation_pressure_direction.
    cascade = _first_float("liquidation_cascade_risk", "cascade_risk") or 0.0
    pressure_direction = _first_float("liquidation_pressure_direction") or 0.0
    # Split the directionless intensity across sides by the observed
    # long/short liquidation pressure balance. The v1 code added the full
    # value symmetrically to BOTH sides, which inflated long_sweep and
    # short_sweep together and latched direction_uncertain (→ composite
    # trust hard-capped at 0.24 system-wide).
    long_side_share = _clamp((1.0 + pressure_direction) / 2.0)
    short_side_share = _clamp((1.0 - pressure_direction) / 2.0)
    long_dist = _first_float("distance_to_long_liq_bps", "long_distance_bps")
    short_dist = _first_float("distance_to_short_liq_bps", "short_distance_bps")
    depth_risk = _clamp((depth_collapse_bps or 0.0) / 3500.0)
    tape_risk = _clamp((trade_tape_acceleration or 0.0) / 30.0)
    oi_risk = _clamp(abs(open_interest_change_pct or 0.0) / 0.05)
    basis_risk = _clamp(abs(cross_venue_basis_bps or mark_index_divergence_bps or 0.0) / 50.0)
    funding_skew = _clamp(abs(funding_rate or 0.0) / 0.001)
    long_crowding = _clamp(((long_short_ratio or 1.0) - 1.0) / 2.0)
    short_crowding = _clamp((1.0 - (long_short_ratio or 1.0)) / 0.75)
    long_proximity = 0.0 if long_dist is None else _clamp((250.0 - long_dist) / 250.0)
    short_proximity = 0.0 if short_dist is None else _clamp((250.0 - short_dist) / 250.0)

    long_sweep = _clamp(0.25 * cascade * long_side_share + 0.25 * long_crowding + 0.2 * long_proximity + 0.15 * depth_risk + 0.15 * tape_risk)
    short_sweep = _clamp(0.25 * cascade * short_side_share + 0.25 * short_crowding + 0.2 * short_proximity + 0.15 * depth_risk + 0.15 * tape_risk)
    stop_hunt = _clamp(max(long_sweep, short_sweep) * 0.6 + basis_risk * 0.2 + funding_skew * 0.2)
    fake_breakout = _clamp(short_sweep * 0.45 + depth_risk * 0.25 + (0.2 if (trade_imbalance or 0.0) < -0.2 else 0.0) + oi_risk * 0.1)
    fake_breakdown = _clamp(long_sweep * 0.45 + depth_risk * 0.25 + (0.2 if (trade_imbalance or 0.0) > 0.2 else 0.0) + oi_risk * 0.1)
    cascade_risk = _clamp(max(cascade, depth_risk * 0.6 + tape_risk * 0.4))
    uncertainty = _clamp(abs(long_sweep - short_sweep))
    direction_uncertain = uncertainty < 0.15 and max(long_sweep, short_sweep) >= 0.55
    reversal_probability = _clamp(max(fake_breakout, fake_breakdown) * 0.7 + stop_hunt * 0.3)
    continuation_probability = _clamp(cascade_risk * 0.6 + (1.0 - reversal_probability) * 0.4)
    oi_funding_long_short_inputs_present = (
        long_short_ratio is not None
        and funding_rate is not None
        and open_interest_change_pct is not None
    )
    oi_funding_long_short_confirmation_pass = (
        oi_funding_long_short_inputs_present
        and oi_risk < 0.75
        and funding_skew < 0.75
        and max(long_crowding, short_crowding) < 0.75
    )
    return {
        "schema_version": "microstructure_liquidation_sweep_risk_v1",
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "long_liquidation_sweep_risk": round(long_sweep, 8),
        "short_liquidation_sweep_risk": round(short_sweep, 8),
        "stop_hunt_risk": round(stop_hunt, 8),
        "fake_breakout_risk": round(fake_breakout, 8),
        "fake_breakdown_risk": round(fake_breakdown, 8),
        "cascade_risk": round(cascade_risk, 8),
        "sweep_risk": round(max(long_sweep, short_sweep, stop_hunt), 8),
        "direction_uncertain": bool(direction_uncertain),
        "post_sweep_reversal_probability": round(reversal_probability, 8),
        "continuation_probability": round(continuation_probability, 8),
        "oi_funding_long_short_inputs_present": bool(oi_funding_long_short_inputs_present),
        "oi_funding_long_short_confirmation_pass": bool(oi_funding_long_short_confirmation_pass),
        "oi_risk": round(oi_risk, 8),
        "funding_skew": round(funding_skew, 8),
        "long_short_crowding_risk": round(max(long_crowding, short_crowding), 8),
        "risk_action": "NO_TRADE" if direction_uncertain else ("REDUCE_SIZE" if max(long_sweep, short_sweep, stop_hunt) >= 0.55 else "ALLOW"),
        "generated_at": iso_now(),
    }
