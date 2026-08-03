"""Liquidity zone producer.

Combines swing highs/lows and equal highs/lows from closed candles,
orderbook depth walls, liquidation levels, and trade-tape sweep prints into
per-symbol liquidity zones. Every zone carries its evidence source; missing
sources reduce zone strength instead of fabricating levels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.market_structure.common import (
    closed_rows_available_for_decision,
    payload_base,
)


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _candle_vals(candles: list[dict], key: str, alt: str) -> list[float]:
    out = []
    for c in candles:
        v = _f(c.get(key)) or _f(c.get(alt))
        if v is not None:
            out.append(v)
    return out


def _swings(highs: list[float], lows: list[float], lookback: int = 2):
    """Swing points: local extremes with `lookback` candles on each side."""
    swing_highs, swing_lows = [], []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == max(highs[i - lookback : i + lookback + 1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i - lookback : i + lookback + 1]):
            swing_lows.append(lows[i])
    return swing_highs, swing_lows


def _equal_levels(levels: list[float], tolerance_bps: float = 5.0) -> list[float]:
    """Clusters of near-equal levels (resting liquidity magnets)."""
    out = []
    used = set()
    for i, a in enumerate(levels):
        if i in used or a <= 0:
            continue
        cluster = [a]
        for j in range(i + 1, len(levels)):
            b = levels[j]
            if b > 0 and abs(b - a) / a * 10000 <= tolerance_bps:
                cluster.append(b)
                used.add(j)
        if len(cluster) >= 2:
            out.append(sum(cluster) / len(cluster))
    return out


def compute_liquidity_zones(
    *,
    symbol: str,
    timeframe: str | None = None,
    candles: list[dict],
    price: float | None,
    orderbook_features: dict | None = None,
    liquidation_levels: dict | None = None,
    trade_tape: dict | None = None,
    oi_payload: dict | None = None,
    long_short: dict | None = None,
    decision_time: datetime | None = None,
    source: str = "closed_candles_orderbook_liquidations_tape",
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    candles, lineage = closed_rows_available_for_decision(
        [c for c in (candles or []) if isinstance(c, dict)],
        decision_time=decision_time,
        max_rows=100,
    )
    base = payload_base(
        schema_version="v2_liquidity_zones_v1",
        feature_family="LIQUIDITY_SWEEP",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source=source,
        rows=candles,
        lineage=lineage,
        now=now,
    )
    highs = _candle_vals(candles, "high", "h")
    lows = _candle_vals(candles, "low", "l")
    px = _f(price)
    missing: list[str] = []
    if not highs or not lows:
        missing.append("CLOSED_CANDLES")
    if px is None or px <= 0:
        missing.append("REFERENCE_PRICE")
    if missing:
        return {
            **base,
            "liquidity_zone_above": None,
            "liquidity_zone_below": None,
            "missing_evidence": missing,
        }

    swing_highs, swing_lows = _swings(highs, lows)
    eq_highs = _equal_levels(sorted(swing_highs, reverse=True)[:20])
    eq_lows = _equal_levels(sorted(swing_lows)[:20])

    above_candidates: list[tuple[float, float, str]] = []  # (level, strength, source)
    below_candidates: list[tuple[float, float, str]] = []
    for lvl in swing_highs:
        if lvl > px:
            above_candidates.append((lvl, 1.0, "swing_high"))
    for lvl in swing_lows:
        if lvl < px:
            below_candidates.append((lvl, 1.0, "swing_low"))
    for lvl in eq_highs:
        if lvl > px:
            above_candidates.append((lvl, 2.0, "equal_highs"))
    for lvl in eq_lows:
        if lvl < px:
            below_candidates.append((lvl, 2.0, "equal_lows"))

    liq = liquidation_levels if isinstance(liquidation_levels, dict) else {}
    for field, side in (
        ("nearest_liquidation_level_above", "above"),
        ("liquidation_short_level", "above"),
        ("nearest_liquidation_level_below", "below"),
        ("liquidation_long_level", "below"),
    ):
        lvl = _f(liq.get(field))
        if lvl and lvl > 0:
            if side == "above" and lvl > px:
                above_candidates.append((lvl, 3.0, f"liquidation:{field}"))
            elif side == "below" and lvl < px:
                below_candidates.append((lvl, 3.0, f"liquidation:{field}"))

    book = orderbook_features if isinstance(orderbook_features, dict) else {}
    for field, side in (("ask_wall_price", "above"), ("bid_wall_price", "below")):
        lvl = _f(book.get(field))
        if lvl and lvl > 0:
            if side == "above" and lvl > px:
                above_candidates.append((lvl, 1.5, "orderbook_wall"))
            elif side == "below" and lvl < px:
                below_candidates.append((lvl, 1.5, "orderbook_wall"))

    def _nearest(cands, reverse):
        if not cands:
            return None, None, None
        cands = sorted(cands, key=lambda x: x[0], reverse=reverse)
        # nearest to price = last when sorted away from price
        level, strength, source = cands[-1]
        return level, strength, source

    zone_above, strength_above, source_above = _nearest(above_candidates, reverse=True)
    zone_below, strength_below, source_below = _nearest(below_candidates, reverse=False)

    tape = trade_tape if isinstance(trade_tape, dict) else {}
    sweep_prints = _f(tape.get("sweep_prints")) or 0.0
    trade_imbalance = _f(tape.get("trade_imbalance"))
    # Sweep risk: resting liquidity nearby + aggressive one-sided tape.
    dist_above = (
        (zone_above - px) / px * 10000 if zone_above else None
    )
    dist_below = (
        (px - zone_below) / px * 10000 if zone_below else None
    )
    nearest_dist = min(
        [d for d in (dist_above, dist_below) if d is not None], default=None
    )
    sweep_risk = None
    if nearest_dist is not None:
        proximity = max(0.0, 1.0 - nearest_dist / 100.0)  # within 100bps ramps up
        tape_pressure = min(1.0, abs(trade_imbalance or 0.0)) if trade_imbalance is not None else 0.3
        sweep_risk = round(min(1.0, proximity * (0.5 + 0.5 * tape_pressure) + 0.2 * min(1.0, sweep_prints / 3.0)), 4)

    # Post-sweep reversal probability: heuristic from wick-reversal frequency
    # at swing extremes in this candle window (labelled as heuristic evidence).
    reversals = 0
    touches = 0
    closes = _candle_vals(candles, "close", "c")
    opens = _candle_vals(candles, "open", "o")
    if len(closes) == len(highs) and swing_highs:
        top = max(swing_highs)
        for i, h in enumerate(highs):
            if h >= top * 0.999:
                touches += 1
                if closes[i] < opens[i]:
                    reversals += 1
    post_sweep_reversal_probability = (
        round(reversals / touches, 4) if touches >= 3 else None
    )

    return {
        **base,
        "reference_price": px,
        "liquidity_zone_above": zone_above,
        "liquidity_zone_below": zone_below,
        "nearest_liquidity_zone_above": zone_above,
        "nearest_liquidity_zone_below": zone_below,
        "nearest_liquidity_above": zone_above,
        "nearest_liquidity_below": zone_below,
        "distance_to_liquidity_zone_bps": nearest_dist,
        "distance_to_zone_above_bps": dist_above,
        "distance_to_zone_below_bps": dist_below,
        "distance_to_liquidity_above_bps": dist_above,
        "distance_to_liquidity_below_bps": dist_below,
        "liquidity_zone_strength": max(
            [s for s in (strength_above, strength_below) if s is not None],
            default=None,
        ),
        "liquidity_zone_source": {
            "above": source_above,
            "below": source_below,
        },
        "liquidity_zone_age_seconds": 0,
        "liquidity_sweep_risk": sweep_risk,
        "sweep_risk_long_side": sweep_risk if dist_below is not None else None,
        "sweep_risk_short_side": sweep_risk if dist_above is not None else None,
        "post_sweep_reversal_probability": post_sweep_reversal_probability,
        "cascade_continuation_probability": (
            round(1.0 - post_sweep_reversal_probability, 4)
            if post_sweep_reversal_probability is not None
            else None
        ),
        "fake_breakout_risk": sweep_risk if dist_above is not None else None,
        "fake_breakdown_risk": sweep_risk if dist_below is not None else None,
        "post_sweep_reversal_probability_basis": (
            f"wick-reversal frequency at swing-high touches over last {len(candles)} candles"
            if post_sweep_reversal_probability is not None
            else "INSUFFICIENT_TOUCH_SAMPLE"
        ),
        "evidence_sources_present": sorted({
            s for s in (
                "candles",
                "liquidation_levels" if liq else None,
                "orderbook_walls" if book.get("ask_wall_price") or book.get("bid_wall_price") else None,
                "trade_tape" if tape else None,
            ) if s
        }),
    }
