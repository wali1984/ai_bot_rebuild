"""Orderbook feature computation for direct public feeds."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_from_epoch_ms(value: Any) -> str | None:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0 or numeric != numeric:
        return None
    if numeric > 1_000_000_000_000_000:
        numeric = numeric / 1_000_000.0
    elif numeric < 10_000_000_000:
        numeric = numeric * 1000.0
    return datetime.fromtimestamp(numeric / 1000.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def epoch_ms(value: Any) -> int | None:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.astimezone(timezone.utc).timestamp() * 1000)
        return None
    if numeric <= 0 or numeric != numeric:
        return None
    if numeric > 1_000_000_000_000_000:
        return int(numeric / 1_000_000.0)
    if numeric < 10_000_000_000:
        return int(numeric * 1000.0)
    return int(numeric)


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


def normalize_levels(rows: Any, *, limit: int | None = None) -> list[dict[str, float]]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, float]] = []
    for row in rows[:limit]:
        price: float | None = None
        qty: float | None = None
        if isinstance(row, Mapping):
            price = _float(row.get("price") or row.get("p"))
            qty = _float(row.get("quantity") or row.get("qty") or row.get("size") or row.get("q"))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            price = _float(row[0])
            qty = _float(row[1])
        if price is None or qty is None or price <= 0 or qty < 0:
            continue
        normalized.append({"price": float(price), "quantity": float(qty)})
    return normalized


def depth_usd(levels: list[dict[str, float]], depth: int) -> float:
    return float(sum(row["price"] * row["quantity"] for row in levels[:depth]))


def depth_quantity(levels: list[dict[str, float]], depth: int) -> float:
    return float(sum(row["quantity"] for row in levels[:depth]))


def depth_imbalance(bids: list[dict[str, float]], asks: list[dict[str, float]], depth: int) -> float | None:
    bid_qty = depth_quantity(bids, depth)
    ask_qty = depth_quantity(asks, depth)
    denom = bid_qty + ask_qty
    if denom <= 0:
        return None
    return float((bid_qty - ask_qty) / denom)


def _far_price(levels: list[dict[str, float]], depth: int) -> float | None:
    if not levels:
        return None
    index = min(depth, len(levels)) - 1
    if index < 0:
        return None
    return levels[index]["price"]


def orderbook_depth_slope_bps(
    bids: list[dict[str, float]],
    asks: list[dict[str, float]],
    *,
    depth: int = 20,
) -> float | None:
    if not bids or not asks:
        return None
    best_bid = bids[0]["price"]
    best_ask = asks[0]["price"]
    mid = (best_bid + best_ask) / 2.0
    bid_far = _far_price(bids, depth)
    ask_far = _far_price(asks, depth)
    if mid <= 0 or bid_far is None or ask_far is None:
        return None
    bid_slope = max(0.0, (best_bid - bid_far) / mid * 10000.0)
    ask_slope = max(0.0, (ask_far - best_ask) / mid * 10000.0)
    return float((bid_slope + ask_slope) / 2.0)


def _walk_side_price_impact_bps(
    levels: list[dict[str, float]],
    *,
    notional_usd: float,
    reference_price: float,
) -> float | None:
    if not levels or notional_usd <= 0 or reference_price <= 0:
        return None
    remaining = notional_usd
    cost = 0.0
    quantity = 0.0
    for row in levels:
        level_notional = row["price"] * row["quantity"]
        if level_notional <= 0:
            continue
        take_notional = min(remaining, level_notional)
        take_qty = take_notional / row["price"]
        cost += take_notional
        quantity += take_qty
        remaining -= take_notional
        if remaining <= 1e-9:
            break
    if quantity <= 0 or remaining > 1e-6:
        return None
    avg_price = cost / quantity
    return abs(avg_price - reference_price) / reference_price * 10000.0


def estimated_price_impact_bps(
    bids: list[dict[str, float]],
    asks: list[dict[str, float]],
    *,
    notional_usd: float = 1000.0,
) -> float | None:
    if not bids or not asks:
        return None
    mid = (bids[0]["price"] + asks[0]["price"]) / 2.0
    buy = _walk_side_price_impact_bps(asks, notional_usd=notional_usd, reference_price=mid)
    sell = _walk_side_price_impact_bps(bids, notional_usd=notional_usd, reference_price=mid)
    candidates = [value for value in (buy, sell) if value is not None]
    if not candidates:
        return None
    return float(max(candidates))


def _first_not_none(values: Iterable[Any]) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def build_orderbook_payloads(
    *,
    exchange: str,
    symbol: str,
    bids: Any,
    asks: Any,
    event_time_ms: Any = None,
    transaction_time_ms: Any = None,
    received_at: str | None = None,
    available_at: str | None = None,
    sequence_id: Any = None,
    previous_sequence_id: Any = None,
    sequence_gap: bool = False,
    source_latency_ms: float | None = None,
    update_type: str = "snapshot",
    depth_level: Any = None,
    feed_speed_ms: Any = None,
    depth_limit: int = 500,
    price_impact_notional_usd: float = 1000.0,
) -> dict[str, dict[str, Any]]:
    normalized_bids = normalize_levels(bids, limit=depth_limit)
    normalized_asks = normalize_levels(asks, limit=depth_limit)
    generated_at = utc_now_iso()
    received_at = received_at or generated_at
    event_time = iso_from_epoch_ms(event_time_ms)
    transaction_time = iso_from_epoch_ms(transaction_time_ms)
    available_at = available_at or received_at
    generated_ms = epoch_ms(generated_at)
    available_ms = epoch_ms(available_at)
    update_age_ms = None
    if generated_ms is not None and available_ms is not None:
        update_age_ms = max(0, generated_ms - available_ms)
    best_bid = normalized_bids[0]["price"] if normalized_bids else None
    best_ask = normalized_asks[0]["price"] if normalized_asks else None
    best_bid_size = normalized_bids[0]["quantity"] if normalized_bids else None
    best_ask_size = normalized_asks[0]["quantity"] if normalized_asks else None
    mid = None
    spread_bps = None
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
        mid = (best_bid + best_ask) / 2.0
        if mid > 0:
            spread_bps = abs(best_ask - best_bid) / mid * 10000.0
    top_payload = {
        "schema_version": "direct_orderbook_top_v1",
        "source": f"direct_{exchange}",
        "exchange": exchange,
        "symbol": symbol,
        "bid": best_bid,
        "ask": best_ask,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "best_bid_size": best_bid_size,
        "best_ask_size": best_ask_size,
        "bid_size": best_bid_size,
        "ask_size": best_ask_size,
        "mid": mid,
        "bid_ask_mid": mid,
        "spread_bps": spread_bps,
        "event_time": event_time,
        "transaction_time": transaction_time,
        "received_at": received_at,
        "available_at": available_at,
        "generated_at": generated_at,
        "sequence_id": sequence_id,
        "previous_sequence_id": previous_sequence_id,
        "sequence_gap": bool(sequence_gap),
        "sequence_gap_flag": 1 if sequence_gap else 0,
        "source_latency_ms": source_latency_ms,
        "update_age_ms": update_age_ms,
        "update_type": update_type,
        "depth_level": depth_level,
        "feed_speed_ms": feed_speed_ms,
    }
    depth_payload = {
        **top_payload,
        "schema_version": "direct_orderbook_depth_v1",
        "bids": normalized_bids,
        "asks": normalized_asks,
        "bid_levels": len(normalized_bids),
        "ask_levels": len(normalized_asks),
    }
    features = {
        **top_payload,
        "schema_version": "direct_orderbook_features_v1",
        "depth_5_bid_usd": depth_usd(normalized_bids, 5),
        "depth_5_ask_usd": depth_usd(normalized_asks, 5),
        "depth_20_bid_usd": depth_usd(normalized_bids, 20),
        "depth_20_ask_usd": depth_usd(normalized_asks, 20),
        "depth_50_bid_usd": depth_usd(normalized_bids, 50),
        "depth_50_ask_usd": depth_usd(normalized_asks, 50),
        "depth_500_bid_usd": depth_usd(normalized_bids, 500),
        "depth_500_ask_usd": depth_usd(normalized_asks, 500),
        "orderbook_imbalance": depth_imbalance(normalized_bids, normalized_asks, 20),
        "depth_imbalance": depth_imbalance(normalized_bids, normalized_asks, 20),
        "depth_slope": orderbook_depth_slope_bps(normalized_bids, normalized_asks, depth=20),
        "estimated_price_impact_bps": estimated_price_impact_bps(
            normalized_bids,
            normalized_asks,
            notional_usd=price_impact_notional_usd,
        ),
        "price_impact_notional_usd": float(price_impact_notional_usd),
        "orderbook_depth_usd": min(
            depth_usd(normalized_bids, 20),
            depth_usd(normalized_asks, 20),
        ) if normalized_bids and normalized_asks else None,
        "depth_total_usd": depth_usd(normalized_bids, 20) + depth_usd(normalized_asks, 20),
        "microstructure_liquidity_depth": min(
            depth_usd(normalized_bids, 20),
            depth_usd(normalized_asks, 20),
        ) if normalized_bids and normalized_asks else None,
    }
    received_ms = epoch_ms(received_at)
    event_ms = epoch_ms(_first_not_none((event_time_ms, transaction_time_ms)))
    if received_ms is not None and event_ms is not None:
        features["source_latency_ms"] = max(0, received_ms - event_ms)
        top_payload["source_latency_ms"] = features["source_latency_ms"]
        depth_payload["source_latency_ms"] = features["source_latency_ms"]
    return {
        "top": top_payload,
        "depth": depth_payload,
        "features": features,
    }
