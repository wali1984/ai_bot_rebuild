"""Fair value gaps (3-candle imbalances) from closed candles."""

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


def _ohlc(candles: list[dict]) -> list[tuple[float, float, float, float]]:
    out = []
    for c in candles:
        o = _f(c.get("open")) or _f(c.get("o"))
        h = _f(c.get("high")) or _f(c.get("h"))
        l = _f(c.get("low")) or _f(c.get("l"))
        cl = _f(c.get("close")) or _f(c.get("c"))
        if None not in (o, h, l, cl):
            out.append((o, h, l, cl))
    return out


def compute_fvg(
    *,
    symbol: str,
    timeframe: str,
    candles: list[dict],
    price: float | None,
    htf_fvg: dict | None = None,
    liquidity_zones: dict | None = None,
    orderbook_trust_score: float | None = None,
    trade_tape: dict | None = None,
    decision_time: datetime | None = None,
    source: str = "closed_candles",
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    filtered_rows, lineage = closed_rows_available_for_decision(
        [c for c in (candles or []) if isinstance(c, dict)],
        decision_time=decision_time,
        max_rows=100,
    )
    rows = _ohlc(filtered_rows)
    px = _f(price)
    base = payload_base(
        schema_version="v2_fvg_v1",
        feature_family="FAIR_VALUE_GAP",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source=source,
        rows=filtered_rows,
        lineage=lineage,
        now=now,
    )
    if len(rows) < 3 or px is None or px <= 0:
        return {
            **base,
            "bullish_fvg_present": None,
            "bearish_fvg_present": None,
            "missing_evidence": (
                (["CLOSED_CANDLES"] if len(rows) < 3 else [])
                + (["REFERENCE_PRICE"] if px is None or px <= 0 else [])
            ),
        }

    # Newest unfilled gap wins. Bullish FVG: candle[i-2].high < candle[i].low.
    gaps: list[dict] = []
    for i in range(2, len(rows)):
        _, h2, l2, _ = rows[i - 2]
        _, h0, l0, _ = rows[i]
        if h2 < l0:
            gaps.append({"kind": "bullish", "top": l0, "bottom": h2, "idx": i})
        if l2 > h0:
            gaps.append({"kind": "bearish", "top": l2, "bottom": h0, "idx": i})

    def _fill_percent(gap):
        top, bottom = gap["top"], gap["bottom"]
        size = top - bottom
        if size <= 0:
            return 100.0
        after = rows[gap["idx"] + 1 :]
        if gap["kind"] == "bullish":
            worst = min((r[2] for r in after), default=top)
            filled = max(0.0, min(1.0, (top - worst) / size))
        else:
            worst = max((r[1] for r in after), default=bottom)
            filled = max(0.0, min(1.0, (worst - bottom) / size))
        return round(filled * 100.0, 2)

    active = []
    for gap in gaps:
        fill = _fill_percent(gap)
        if fill < 100.0:
            gap["fill_percent"] = fill
            gap["age_candles"] = len(rows) - 1 - gap["idx"]
            active.append(gap)

    bullish = [g for g in active if g["kind"] == "bullish"]
    bearish = [g for g in active if g["kind"] == "bearish"]
    newest = max(active, key=lambda g: g["idx"]) if active else None

    def _dist_bps(level):
        return (level - px) / px * 10000 if level else None

    zones = liquidity_zones if isinstance(liquidity_zones, dict) else {}
    tape = trade_tape if isinstance(trade_tape, dict) else {}
    htf = htf_fvg if isinstance(htf_fvg, dict) else {}

    payload = {
        **base,
        "bullish_fvg_present": bool(bullish),
        "bearish_fvg_present": bool(bearish),
        "active_fvg_count": len(active),
    }
    if newest:
        top, bottom = newest["top"], newest["bottom"]
        mid = (top + bottom) / 2
        payload.update({
            "fvg_kind": newest["kind"],
            "fvg_top": top,
            "fvg_bottom": bottom,
            "fvg_mid": mid,
            "fvg_size_bps": round((top - bottom) / px * 10000, 2),
            "distance_to_fvg_bps": round(_dist_bps(mid), 2),
            "fvg_fill_percent": newest["fill_percent"],
            "fvg_age_candles": newest["age_candles"],
            "fvg_invalidated": False,
            "fvg_retest_confirmed": bool(
                newest["fill_percent"] > 0.0 and newest["fill_percent"] < 100.0
            ),
            "htf_fvg_alignment": (
                htf.get("fvg_kind") == newest["kind"]
                if htf.get("fvg_kind")
                # HTF payload present with no active gap = known non-alignment;
                # only a MISSING HTF payload stays None (unknown).
                else (False if htf else None)
            ),
            "fvg_liquidity_confluence": (
                abs((_f(zones.get("liquidity_zone_below")) or 0) - mid) / px * 10000 < 30
                or abs((_f(zones.get("liquidity_zone_above")) or 0) - mid) / px * 10000 < 30
                if zones.get("liquidity_zone_above") or zones.get("liquidity_zone_below")
                else None
            ),
            "fvg_orderbook_trust_confluence": (
                orderbook_trust_score if orderbook_trust_score is not None else None
            ),
            "fvg_trade_tape_confirmation": _f(tape.get("trade_tape_confirmation_score")),
            "fvg_expected_edge_after_cost": _f(tape.get("expected_edge_after_cost_bps")),
        })
    elif gaps:
        newest_invalidated = max(gaps, key=lambda g: g["idx"])
        top, bottom = newest_invalidated["top"], newest_invalidated["bottom"]
        mid = (top + bottom) / 2
        payload.update({
            "fvg_kind": newest_invalidated["kind"],
            "fvg_top": top,
            "fvg_bottom": bottom,
            "fvg_mid": mid,
            "fvg_size_bps": round((top - bottom) / px * 10000, 2),
            "distance_to_fvg_bps": round(_dist_bps(mid), 2),
            "fvg_fill_percent": 100.0,
            "fvg_age_candles": len(rows) - 1 - newest_invalidated["idx"],
            "fvg_invalidated": True,
            "fvg_retest_confirmed": False,
            "htf_fvg_alignment": None,
            "fvg_liquidity_confluence": None,
            "fvg_orderbook_trust_confluence": (
                orderbook_trust_score if orderbook_trust_score is not None else None
            ),
            "fvg_trade_tape_confirmation": _f(tape.get("trade_tape_confirmation_score")),
            "fvg_expected_edge_after_cost": _f(tape.get("expected_edge_after_cost_bps")),
        })
    else:
        payload.update({
            "fvg_kind": None, "fvg_top": None, "fvg_bottom": None, "fvg_mid": None,
            "fvg_size_bps": None, "distance_to_fvg_bps": None,
            "fvg_fill_percent": None, "fvg_age_candles": None,
            "fvg_invalidated": None, "fvg_retest_confirmed": None,
            "htf_fvg_alignment": None, "fvg_liquidity_confluence": None,
            "fvg_orderbook_trust_confluence": None, "fvg_trade_tape_confirmation": None,
            "fvg_expected_edge_after_cost": None,
        })
    payload["standalone_entry_trigger"] = False
    payload["fvg_alone_can_approve_trade"] = False
    return payload
