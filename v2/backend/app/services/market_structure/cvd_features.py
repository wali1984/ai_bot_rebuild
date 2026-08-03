"""Cumulative volume delta features from trade tape or taker-volume candles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.market_structure.common import (
    as_float,
    closed_rows_available_for_decision,
    payload_base,
)


def compute_cvd_features(
    *,
    symbol: str,
    timeframe: str,
    candles: list[dict] | None = None,
    trades: list[dict] | None = None,
    price: float | None = None,
    decision_time: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows, lineage = closed_rows_available_for_decision(
        [r for r in (trades or candles or []) if isinstance(r, dict)],
        decision_time=decision_time,
        max_rows=500,
    )
    base = payload_base(
        schema_version="v2_cvd_features_v1",
        feature_family="CVD",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source="trade_tape_or_closed_candles",
        rows=rows,
        lineage=lineage,
        now=now,
    )
    deltas: list[float] = []
    closes: list[float] = []
    aggressive_buy = 0.0
    aggressive_sell = 0.0
    for row in rows:
        close = as_float(row.get("close") or row.get("c") or row.get("price") or row.get("p"))
        if close is not None:
            closes.append(close)
        qty = as_float(row.get("quantity") or row.get("qty") or row.get("q"))
        side = str(row.get("side") or row.get("aggressor_side") or "").lower()
        if qty is not None and side in {"buy", "buyer", "long"}:
            aggressive_buy += qty
            deltas.append(qty)
            continue
        if qty is not None and side in {"sell", "seller", "short"}:
            aggressive_sell += qty
            deltas.append(-qty)
            continue
        taker_buy = as_float(row.get("taker_buy_base_vol") or row.get("takerBuyBaseVolume"))
        volume = as_float(row.get("volume") or row.get("v"))
        if taker_buy is not None and volume is not None:
            sell = max(0.0, volume - taker_buy)
            aggressive_buy += max(0.0, taker_buy)
            aggressive_sell += sell
            deltas.append(taker_buy - sell)
    if not deltas:
        return {
            **base,
            "cvd": None,
            "cvd_slope": None,
            "cvd_divergence": None,
            "aggressive_buy_volume": None,
            "aggressive_sell_volume": None,
            "missing_evidence": ["TRADE_TAPE_OR_TAKER_VOLUME"],
        }
    cvd = sum(deltas)
    recent = sum(deltas[-max(1, min(20, len(deltas))):])
    prior = sum(deltas[: max(1, len(deltas) - min(20, len(deltas)))])
    cvd_slope = recent - prior / max(1, len(deltas))
    px = as_float(price)
    price_slope = None
    if len(closes) >= 2 and closes[0] not in (None, 0.0):
        price_slope = (closes[-1] - closes[0]) / closes[0]
    cvd_divergence = None
    if price_slope is not None:
        if price_slope > 0 and cvd_slope < 0:
            cvd_divergence = -1.0
        elif price_slope < 0 and cvd_slope > 0:
            cvd_divergence = 1.0
        else:
            cvd_divergence = 0.0
    return {
        **base,
        "cvd": round(cvd, 8),
        "cvd_slope": round(cvd_slope, 8),
        "cvd_divergence": cvd_divergence,
        "aggressive_buy_volume": round(aggressive_buy, 8),
        "aggressive_sell_volume": round(aggressive_sell, 8),
        "reference_price": px,
    }
