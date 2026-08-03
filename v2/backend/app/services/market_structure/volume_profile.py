"""Volume profile features from timestamp-safe closed candles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.market_structure.common import (
    as_float,
    closed_rows_available_for_decision,
    payload_base,
)


def compute_volume_profile(
    *,
    symbol: str,
    timeframe: str,
    candles: list[dict],
    price: float | None,
    decision_time: datetime | None = None,
    now: datetime | None = None,
    bins: int = 24,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows, lineage = closed_rows_available_for_decision(
        [c for c in (candles or []) if isinstance(c, dict)],
        decision_time=decision_time,
        max_rows=240,
    )
    base = payload_base(
        schema_version="v2_volume_profile_v1",
        feature_family="VOLUME_PROFILE",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source="closed_candles",
        rows=rows,
        lineage=lineage,
        now=now,
    )
    px = as_float(price)
    prices: list[float] = []
    weighted: list[tuple[float, float]] = []
    for row in rows:
        high = as_float(row.get("high") or row.get("h"))
        low = as_float(row.get("low") or row.get("l"))
        close = as_float(row.get("close") or row.get("c"))
        volume = as_float(row.get("volume") or row.get("v")) or 0.0
        if high is None or low is None or close is None:
            continue
        typical = (high + low + close) / 3.0
        prices.append(typical)
        weighted.append((typical, max(0.0, volume)))
    if len(weighted) < 5 or px is None or px <= 0:
        return {
            **base,
            "volume_profile_poc": None,
            "high_volume_node_above": None,
            "high_volume_node_below": None,
            "low_volume_node_above": None,
            "low_volume_node_below": None,
            "missing_evidence": ["CLOSED_CANDLES_OR_REFERENCE_PRICE"],
        }

    lo = min(prices)
    hi = max(prices)
    if hi <= lo:
        return {
            **base,
            "volume_profile_poc": px,
            "high_volume_node_above": None,
            "high_volume_node_below": None,
            "low_volume_node_above": None,
            "low_volume_node_below": None,
        }
    bins = max(4, int(bins))
    width = (hi - lo) / bins
    profile = [0.0 for _ in range(bins)]
    for typical, volume in weighted:
        idx = min(bins - 1, max(0, int((typical - lo) / width)))
        profile[idx] += volume
    levels = [lo + (i + 0.5) * width for i in range(bins)]
    max_vol = max(profile)
    min_vol = min(profile)
    poc = levels[profile.index(max_vol)]

    high_nodes = [levels[i] for i, vol in enumerate(profile) if vol >= max_vol * 0.70]
    low_nodes = [levels[i] for i, vol in enumerate(profile) if vol <= max(min_vol, max_vol * 0.20)]
    return {
        **base,
        "volume_profile_poc": poc,
        "distance_to_volume_poc_bps": round((poc - px) / px * 10000.0, 4),
        "high_volume_node_above": min((v for v in high_nodes if v > px), default=None),
        "high_volume_node_below": max((v for v in high_nodes if v < px), default=None),
        "low_volume_node_above": min((v for v in low_nodes if v > px), default=None),
        "low_volume_node_below": max((v for v in low_nodes if v < px), default=None),
        "volume_profile_bin_count": bins,
    }
