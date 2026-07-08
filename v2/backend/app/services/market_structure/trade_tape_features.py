"""Trade-tape imbalance and large-print confirmation features."""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from v2.backend.app.services.market_structure.common import (
    as_float,
    closed_rows_available_for_decision,
    payload_base,
)


def compute_trade_tape_features(
    *,
    symbol: str,
    timeframe: str,
    trades: list[dict],
    decision_time: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows, lineage = closed_rows_available_for_decision(
        [t for t in (trades or []) if isinstance(t, dict)],
        decision_time=decision_time,
        max_rows=1000,
    )
    base = payload_base(
        schema_version="v2_trade_tape_features_v1",
        feature_family="TRADE_TAPE_IMBALANCE",
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        source="trade_tape",
        rows=rows,
        lineage=lineage,
        now=now,
    )
    buys = 0.0
    sells = 0.0
    notionals: list[float] = []
    sweep_prints = 0
    for row in rows:
        price = as_float(row.get("price") or row.get("p")) or 0.0
        qty = as_float(row.get("quantity") or row.get("qty") or row.get("q")) or 0.0
        notional = max(0.0, price * qty)
        if notional > 0:
            notionals.append(notional)
        side = str(row.get("side") or row.get("aggressor_side") or "").lower()
        if side in {"buy", "buyer", "long"}:
            buys += notional or qty
        elif side in {"sell", "seller", "short"}:
            sells += notional or qty
        if row.get("sweep_print") is True or str(row.get("event_type") or "").lower() == "sweep":
            sweep_prints += 1
    if buys + sells <= 0:
        return {
            **base,
            "trade_imbalance": None,
            "large_trade_cluster": None,
            "sweep_prints": None,
            "trade_tape_confirmation_score": None,
            "missing_evidence": ["SIGNED_TRADE_TAPE"],
        }
    imbalance = (buys - sells) / (buys + sells)
    avg_notional = mean(notionals) if notionals else 0.0
    large_threshold = avg_notional * 3.0
    large_count = sum(1 for value in notionals if avg_notional > 0 and value >= large_threshold)
    confirmation = 0.5 + 0.5 * min(1.0, abs(imbalance))
    if large_count:
        confirmation = min(1.0, confirmation + 0.1)
    return {
        **base,
        "aggressive_buy_volume": round(buys, 8),
        "aggressive_sell_volume": round(sells, 8),
        "trade_imbalance": round(imbalance, 8),
        "large_trade_cluster": large_count,
        "sweep_prints": sweep_prints,
        "trade_tape_confirmation_score": round(confirmation, 4),
    }
