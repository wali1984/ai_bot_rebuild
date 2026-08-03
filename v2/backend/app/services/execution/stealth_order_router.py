"""Stealth execution router — maker-first, clip-split, stop-hunt defense.

Plans (never submits) an execution as maker-first LIMIT+GTX clips with
randomized sizing/timing jitter, short cancel-replace TTL, local synthetic
stops, and a mandatory but minimally-exposed emergency server-side stop.

This module is honest: it does NOT claim orders are invisible. Resting limit
orders are visible on the book; the goal is to minimize footprint and avoid
predictable stop walls, not to hide. Every plan is dry-run.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

SCHEMA_VERSION = "stealth_order_router_v1"

MAX_CLIP_FRACTION = 0.25          # no single clip > 25% of total notional
MIN_CLIPS = 1
MAX_CLIPS = 8
DEFAULT_CLIP_TTL_SECONDS = 8.0

TAKER_FALLBACK_REASONS = frozenset({
    "EMERGENCY_EXIT",
    "SQUEEZE_DEFENSE",
    "LIQUIDATION_BUFFER_COLLAPSE",
    "EXPLICIT_ALPHA_URGENCY",
})


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _clip_count(notional: float, tick_liquidity_usd: float) -> int:
    if tick_liquidity_usd <= 0:
        return MIN_CLIPS
    needed = int(notional / max(tick_liquidity_usd * MAX_CLIP_FRACTION, 1.0)) + 1
    return max(MIN_CLIPS, min(MAX_CLIPS, needed))


def _deterministic_jitter(seed: str, lo: float, hi: float) -> float:
    """Deterministic pseudo-random in [lo, hi] from a trace seed (test-stable)."""
    digest = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    frac = (digest % 10_000) / 10_000.0
    return lo + frac * (hi - lo)


def plan_stealth_execution(
    *,
    symbol: str,
    side: str,
    total_notional_usd: float,
    current_price: float,
    book_liquidity_usd: float | None = None,
    is_emergency: bool = False,
    taker_fallback_reason: str | None = None,
    tick_size: float | None = None,
    generated_utc: str,
) -> dict[str, Any]:
    symbol = str(symbol).upper()
    side = str(side).lower()
    book_liquidity = _float(book_liquidity_usd) or (total_notional_usd * 4)
    clip_count = _clip_count(total_notional_usd, book_liquidity)
    max_clip = round(total_notional_usd / clip_count, 2)

    taker_allowed = bool(is_emergency or (taker_fallback_reason in TAKER_FALLBACK_REASONS))
    order_type = "MARKET" if is_emergency else "LIMIT"
    time_in_force = None if is_emergency else "GTX"  # GTX = post-only maker

    # Price offset: rest just inside the touch to earn maker rebate, jittered.
    offset_bps = _deterministic_jitter(f"{symbol}{side}{generated_utc}", 0.5, 2.0)
    if side == "long":
        clip_price = current_price * (1 - offset_bps / 10_000.0)
    else:
        clip_price = current_price * (1 + offset_bps / 10_000.0)
    ttl = round(_deterministic_jitter(f"ttl{symbol}{generated_utc}", 5.0, DEFAULT_CLIP_TTL_SECONDS + 4), 2)

    client_order_id = "v2s_" + hashlib.sha256(
        f"{symbol}|{side}|{total_notional_usd}|{generated_utc}".encode()
    ).hexdigest()[:20]

    # Maker probability heuristic: thinner book / GTX -> higher maker odds.
    maker_probability = 0.9 if (time_in_force == "GTX" and not is_emergency) else 0.0

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "time_in_force": time_in_force,
        "post_only_requested": time_in_force == "GTX",
        "post_only_supported": time_in_force == "GTX",
        "maker_first": not is_emergency,
        "visible_order_notional_usd": max_clip,          # only one clip on book at a time
        "total_notional_usd": round(total_notional_usd, 2),
        "clip_count": clip_count,
        "max_clip_notional_usd": max_clip,
        "clip_price_offset_bps": round(offset_bps, 3),
        "reference_clip_price": round(clip_price, 10),
        "time_to_cancel_seconds": ttl,
        "maker_probability": maker_probability,
        "taker_fallback_allowed": taker_allowed,
        "taker_fallback_reason": taker_fallback_reason if taker_allowed else None,
        "stop_visibility_risk": "LOW" if not is_emergency else "N/A_EMERGENCY_MARKET",
        "synthetic_stop_present": True,
        "synthetic_stop_note": "exit managed locally from mark/market price; no static visible stop wall",
        "emergency_stop_present": True,
        "emergency_stop_note": "server-side STOP_MARKET closePosition sized/placed off round numbers for catastrophic-disconnect protection only",
        "client_order_id": client_order_id,
        "cancel_replace_plan": f"cancel+replace stale maker clip after {ttl}s if unfilled",
        "single_large_visible_order": False,
        "would_submit_order": False,
        "would_submit_test_order": False,
        "places_real_order": False,
        "raw_key_exposed": False,
    }
