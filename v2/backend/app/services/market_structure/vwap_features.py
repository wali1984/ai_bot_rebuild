"""VWAP and anchored VWAP features from point-in-time candles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.market_structure.common import (
    as_float,
    closed_rows_available_for_decision,
    payload_base,
)


def compute_vwap_features(
    *,
    symbol: str,
    timeframe: str,
    candles: list[dict],
    price: float | None,
    anchor_index: int | None = None,
    decision_time: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows, lineage = closed_rows_available_for_decision(
        [c for c in (candles or []) if isinstance(c, dict)],
        decision_time=decision_time,
        max_rows=240,
    )
    base = payload_base(
        schema_version="v2_vwap_features_v1",
        feature_family="VWAP_DEVIATION",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source="closed_candles",
        rows=rows,
        lineage=lineage,
        now=now,
    )
    px = as_float(price)
    typical_volume: list[tuple[float, float]] = []
    for row in rows:
        high = as_float(row.get("high") or row.get("h"))
        low = as_float(row.get("low") or row.get("l"))
        close = as_float(row.get("close") or row.get("c"))
        volume = as_float(row.get("volume") or row.get("v")) or 0.0
        if high is None or low is None or close is None:
            continue
        typical_volume.append(((high + low + close) / 3.0, max(0.0, volume)))
    if len(typical_volume) < 3 or px is None or px <= 0:
        return {
            **base,
            "session_vwap": None,
            "anchored_vwap": None,
            "distance_to_vwap_bps": None,
            "vwap_slope": None,
            "missing_evidence": ["CLOSED_CANDLES_OR_REFERENCE_PRICE"],
        }

    def _vwap(items: list[tuple[float, float]]) -> float | None:
        total_volume = sum(volume for _typical, volume in items)
        if total_volume <= 0:
            return None
        return sum(typical * volume for typical, volume in items) / total_volume

    session = _vwap(typical_volume)
    anchor = max(0, min(len(typical_volume) - 1, anchor_index or 0))
    anchored = _vwap(typical_volume[anchor:])
    prior_window = _vwap(typical_volume[max(0, len(typical_volume) - 20): max(1, len(typical_volume) - 10)])
    recent_window = _vwap(typical_volume[-10:])
    slope = None
    if prior_window not in (None, 0.0) and recent_window is not None:
        slope = (recent_window - prior_window) / float(prior_window) * 10000.0
    return {
        **base,
        "session_vwap": session,
        "anchored_vwap": anchored,
        "distance_to_vwap_bps": (
            round((px - session) / px * 10000.0, 4) if session is not None else None
        ),
        "anchored_vwap_distance_bps": (
            round((px - anchored) / px * 10000.0, 4) if anchored is not None else None
        ),
        "vwap_slope": round(slope, 4) if slope is not None else None,
    }
