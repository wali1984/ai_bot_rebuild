"""Market structure: BOS/CHOCH, order blocks, equal highs/lows, premium/discount."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.market_structure.common import (
    closed_rows_available_for_decision,
    direction_code,
    payload_base,
    zone_code,
)
from v2.backend.app.services.market_structure.liquidity_zones import (
    _candle_vals,
    _equal_levels,
    _f,
    _swings,
)


def compute_structure(
    *,
    symbol: str,
    timeframe: str,
    candles: list[dict],
    price: float | None,
    decision_time: datetime | None = None,
    source: str = "closed_candles",
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    candles, lineage = closed_rows_available_for_decision(
        [c for c in (candles or []) if isinstance(c, dict)],
        decision_time=decision_time,
        max_rows=100,
    )
    highs = _candle_vals(candles, "high", "h")
    lows = _candle_vals(candles, "low", "l")
    closes = _candle_vals(candles, "close", "c")
    opens = _candle_vals(candles, "open", "o")
    px = _f(price)
    base = payload_base(
        schema_version="v2_market_structure_v1",
        feature_family="BOS_CHOCH",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source=source,
        rows=candles,
        lineage=lineage,
        now=now,
    )
    if len(closes) < 10 or px is None or px <= 0:
        return {**base, "bos_direction": None, "choch_direction": None,
                "missing_evidence": ["CLOSED_CANDLES_OR_PRICE"]}

    swing_highs, swing_lows = _swings(highs, lows)
    last_high = swing_highs[-1] if swing_highs else None
    prev_high = swing_highs[-2] if len(swing_highs) >= 2 else None
    last_low = swing_lows[-1] if swing_lows else None
    prev_low = swing_lows[-2] if len(swing_lows) >= 2 else None

    # Break of structure: close beyond the most recent swing extreme.
    bos_direction = None
    if last_high and closes[-1] > last_high:
        bos_direction = "up"
    elif last_low and closes[-1] < last_low:
        bos_direction = "down"

    # Change of character: trend of swings flips (HH/HL -> LH/LL or reverse).
    choch_direction = None
    if prev_high and last_high and prev_low and last_low:
        rising = last_high > prev_high and last_low > prev_low
        falling = last_high < prev_high and last_low < prev_low
        if falling and closes[-1] > last_high:
            choch_direction = "up"
        elif rising and closes[-1] < last_low:
            choch_direction = "down"

    # Order blocks: last opposing candle before an impulsive break.
    order_block_above = None
    order_block_below = None
    breaker_block_active = False
    if bos_direction == "up":
        for i in range(len(closes) - 2, max(0, len(closes) - 12), -1):
            if closes[i] < opens[i]:
                order_block_below = (opens[i] + closes[i]) / 2
                break
    elif bos_direction == "down":
        for i in range(len(closes) - 2, max(0, len(closes) - 12), -1):
            if closes[i] > opens[i]:
                order_block_above = (opens[i] + closes[i]) / 2
                break
    if order_block_below and px < order_block_below:
        breaker_block_active = True
    if order_block_above and px > order_block_above:
        breaker_block_active = True

    eq_highs = _equal_levels(sorted(swing_highs, reverse=True)[:20])
    eq_lows = _equal_levels(sorted(swing_lows)[:20])
    eq_high_above = min((v for v in eq_highs if v > px), default=None)
    eq_low_below = max((v for v in eq_lows if v < px), default=None)

    window_high = max(highs[-50:])
    window_low = min(lows[-50:])
    rng = window_high - window_low
    premium_discount_zone = None
    if rng > 0:
        pos = (px - window_low) / rng
        premium_discount_zone = (
            "premium" if pos > 0.62 else "discount" if pos < 0.38 else "equilibrium"
        )

    # Session sweep: did price take a 50-candle extreme and close back inside?
    session_sweep_status = None
    if highs[-1] >= window_high and closes[-1] < window_high:
        session_sweep_status = "high_swept_and_rejected"
    elif lows[-1] <= window_low and closes[-1] > window_low:
        session_sweep_status = "low_swept_and_rejected"

    return {
        **base,
        "bos_direction": bos_direction,
        "bos_direction_code": direction_code(bos_direction) or 0.0,
        "choch_direction": choch_direction,
        "choch_direction_code": direction_code(choch_direction) or 0.0,
        "order_block_above": order_block_above,
        "order_block_below": order_block_below,
        "order_block_strength": (
            1.0 if order_block_above is not None or order_block_below is not None else 0.0
        ),
        "breaker_block_active": breaker_block_active,
        "mitigation_block_active": bool(order_block_above or order_block_below) and not breaker_block_active,
        "equal_highs_distance_bps": (
            round((eq_high_above - px) / px * 10000, 2) if eq_high_above else None
        ),
        "equal_lows_distance_bps": (
            round((px - eq_low_below) / px * 10000, 2) if eq_low_below else None
        ),
        "premium_discount_zone": premium_discount_zone,
        "premium_discount_zone_code": zone_code(premium_discount_zone),
        "session_sweep_status": session_sweep_status,
        "session_high_sweep": session_sweep_status == "high_swept_and_rejected",
        "session_low_sweep": session_sweep_status == "low_swept_and_rejected",
        "structure_trend_state": (
            "trending_up" if bos_direction == "up" else
            "trending_down" if bos_direction == "down" else
            "range_or_unconfirmed"
        ),
        "structure_trend_state_code": direction_code(bos_direction) or 0.0,
        "swing_high": last_high,
        "swing_low": last_low,
        "range_high_50": window_high,
        "range_low_50": window_low,
    }
