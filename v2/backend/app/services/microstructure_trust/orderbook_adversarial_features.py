"""Adversarial orderbook features from visible public-book changes."""
from __future__ import annotations

import statistics
from typing import Any, Mapping

from .feed_quality import iso_now, parse_time_ms


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


def _levels(payload: Mapping[str, Any], side: str) -> list[tuple[float, float]]:
    raw = payload.get(f"{side}s") or payload.get(side[:1])
    if not isinstance(raw, list):
        return []
    out: list[tuple[float, float]] = []
    for row in raw:
        px = qty = None
        if isinstance(row, Mapping):
            px = _float(row.get("price") or row.get("p"))
            qty = _float(row.get("quantity") or row.get("qty") or row.get("q") or row.get("size"))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            px = _float(row[0])
            qty = _float(row[1])
        if px is not None and qty is not None and px > 0 and qty >= 0:
            out.append((px, qty))
    return out


def _depth(payload: Mapping[str, Any], side: str, depth: int = 20) -> float:
    explicit = _float(payload.get(f"depth_{depth}_{side}_usd"))
    if explicit is not None:
        return explicit
    return sum(px * qty for px, qty in _levels(payload, side)[:depth])


def _imbalance(payload: Mapping[str, Any]) -> float | None:
    direct = _float(payload.get("depth_imbalance") or payload.get("orderbook_imbalance"))
    if direct is not None:
        return direct
    bid_qty = sum(qty for _px, qty in _levels(payload, "bid")[:20])
    ask_qty = sum(qty for _px, qty in _levels(payload, "ask")[:20])
    denom = bid_qty + ask_qty
    if denom <= 0:
        return None
    return (bid_qty - ask_qty) / denom


def _spread(payload: Mapping[str, Any]) -> float | None:
    direct = _float(payload.get("spread_bps") or payload.get("bid_ask_spread_bps"))
    if direct is not None:
        return direct
    bid = _float(payload.get("best_bid") or payload.get("bid"))
    ask = _float(payload.get("best_ask") or payload.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    mid = (bid + ask) / 2.0
    return abs(ask - bid) / mid * 10000.0 if mid > 0 else None


def _top_qty(payload: Mapping[str, Any], side: str) -> float | None:
    direct = _float(payload.get(f"best_{side}_size") or payload.get(f"{side}_size"))
    if direct is not None:
        return direct
    levels = _levels(payload, side)
    return levels[0][1] if levels else None


def _score_ratio(value: float | None, bound: float) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, value / max(1e-9, bound)))


DEPTH_STABILITY_RATIO = 0.55
MIN_STRATUM_SAMPLES = 5

DEPTH_PERSISTENCE_STABLE = "STABLE_DEPTH_WINDOW"
DEPTH_PERSISTENCE_UNSTABLE = "DEPTH_UNSTABLE"
DEPTH_PERSISTENCE_INSUFFICIENT = "INSUFFICIENT_DEPTH_WINDOW"
DEPTH_PERSISTENCE_MISSING_FIELDS = "MISSING_DEPTH_FIELDS"


def _stratum_key(payload: Mapping[str, Any]) -> str:
    level = payload.get("depth_level")
    if level is not None:
        return f"depth_level:{level}"
    return f"update:{payload.get('update_type') or 'unknown'}"


def _select_depth_stratum(
    rows: list[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], str, str | None]:
    """Pick one consistent visible-book view for depth-series metrics.

    The recorder subscribes to several partial-depth streams per symbol
    (levels 5/10/20) and emits one row per message. Depth sums computed from
    different stream depths differ ~5x by construction, so a window that
    mixes strata measures the subscription mix, not the market (F-0010:
    depth persistence was pinned to 0 for every symbol). Prefer the deepest
    stratum that has enough samples; report insufficiency explicitly.
    """
    strata: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        strata.setdefault(_stratum_key(row), []).append(row)
    if not strata:
        return [], "", DEPTH_PERSISTENCE_INSUFFICIENT

    def _depth_rank(key: str) -> tuple[int, float]:
        if key.startswith("depth_level:"):
            try:
                return (0, -float(key.split(":", 1)[1]))
            except ValueError:
                return (1, 0.0)
        return (1, 0.0)

    sufficient = [key for key in strata if len(strata[key]) >= MIN_STRATUM_SAMPLES]
    if not sufficient:
        largest = max(strata, key=lambda key: len(strata[key]))
        return list(strata[largest]), largest, DEPTH_PERSISTENCE_INSUFFICIENT
    best = sorted(sufficient, key=_depth_rank)[0]
    return list(strata[best]), best, None


def compute_orderbook_adversarial_features(
    *,
    exchange: str,
    symbol: str,
    snapshots: list[Mapping[str, Any]],
    trade_imbalance: float | None = None,
) -> dict[str, Any]:
    rows = [row for row in snapshots if isinstance(row, Mapping)]
    if not rows:
        return {
            "schema_version": "microstructure_orderbook_adversarial_features_v1",
            "exchange": exchange,
            "symbol": symbol.upper(),
            "public_orderbook_default_trust": "LOW",
            "insufficient_book_history": True,
            "depth_persistence_ms": 0,
            "depth_persistence_reason": DEPTH_PERSISTENCE_INSUFFICIENT,
            "depth_series_stratum": None,
            "depth_series_sample_count": 0,
            "level_lifetime_distribution": [],
            "add_cancel_ratio": 1.0,
            "cancel_burst_score": 1.0,
            "quote_stuffing_score": 1.0,
            "book_flip_rate": 1.0,
            "top_book_pull_rate": 1.0,
            "depth_collapse_bps": 10000.0,
            "spread_expansion_rate": 1.0,
            "bid_wall_pull_score": 1.0,
            "ask_wall_pull_score": 1.0,
            "imbalance_persistence_score": 0.0,
            "imbalance_flip_score": 1.0,
            "book_trade_divergence_score": 1.0,
            "price_impact_instability_score": 1.0,
            "generated_at": iso_now(),
        }
    rows, depth_series_stratum, stratum_insufficiency = _select_depth_stratum(rows)
    first_ms = parse_time_ms(rows[0].get("available_at") or rows[0].get("received_at") or rows[0].get("event_time")) or 0
    last_ms = parse_time_ms(rows[-1].get("available_at") or rows[-1].get("received_at") or rows[-1].get("event_time")) or first_ms
    window_ms = max(1, last_ms - first_ms)
    bid_depths = [_depth(row, "bid", 20) for row in rows]
    ask_depths = [_depth(row, "ask", 20) for row in rows]
    total_depths = [b + a for b, a in zip(bid_depths, ask_depths, strict=True)]
    spreads = [value for value in (_spread(row) for row in rows) if value is not None]
    imbalances = [value for value in (_imbalance(row) for row in rows) if value is not None]
    bid_top = [value for value in (_top_qty(row, "bid") for row in rows) if value is not None]
    ask_top = [value for value in (_top_qty(row, "ask") for row in rows) if value is not None]

    if stratum_insufficiency is not None:
        depth_persistence_ms = 0
        depth_persistence_reason = stratum_insufficiency
    elif not total_depths or max(total_depths) <= 0.0:
        depth_persistence_ms = 0
        depth_persistence_reason = DEPTH_PERSISTENCE_MISSING_FIELDS
    elif min(total_depths) >= max(total_depths) * DEPTH_STABILITY_RATIO:
        depth_persistence_ms = window_ms
        depth_persistence_reason = DEPTH_PERSISTENCE_STABLE
    else:
        depth_persistence_ms = 0
        depth_persistence_reason = DEPTH_PERSISTENCE_UNSTABLE
    cancels = 0.0
    adds = 0.0
    for prev, cur in zip(total_depths, total_depths[1:]):
        if cur < prev:
            cancels += prev - cur
        elif cur > prev:
            adds += cur - prev
    add_cancel_ratio = cancels / max(1.0, adds)
    cancel_burst_score = _score_ratio(add_cancel_ratio, 3.0)
    quote_stuffing_score = _score_ratio(len(rows) / (window_ms / 1000.0), 25.0)
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in imbalances]
    flips = sum(1 for prev, cur in zip(signs, signs[1:]) if prev and cur and prev != cur)
    book_flip_rate = flips / max(1, len(signs) - 1)
    bid_pull = max(0.0, (max(bid_top) - bid_top[-1]) / max(1e-9, max(bid_top))) if bid_top else 1.0
    ask_pull = max(0.0, (max(ask_top) - ask_top[-1]) / max(1e-9, max(ask_top))) if ask_top else 1.0
    top_book_pull_rate = max(bid_pull, ask_pull)
    depth_collapse_bps = 0.0
    if total_depths and max(total_depths) > 0:
        depth_collapse_bps = max(0.0, (max(total_depths) - total_depths[-1]) / max(total_depths) * 10000.0)
    spread_expansion_rate = 0.0
    if spreads and spreads[0] > 0:
        spread_expansion_rate = max(0.0, (spreads[-1] - spreads[0]) / spreads[0])
    imbalance_persistence_score = 0.0
    if imbalances:
        dominant_sign = 1 if sum(1 for value in imbalances if value > 0) >= sum(1 for value in imbalances if value < 0) else -1
        imbalance_persistence_score = sum(1 for value in imbalances if (value > 0) == (dominant_sign > 0)) / len(imbalances)
    divergence = 1.0
    if trade_imbalance is not None and imbalances:
        book_sign = 1 if imbalances[-1] > 0 else -1 if imbalances[-1] < 0 else 0
        tape_sign = 1 if trade_imbalance > 0 else -1 if trade_imbalance < 0 else 0
        divergence = 1.0 if book_sign and tape_sign and book_sign != tape_sign else 0.0
    impact_values = [value for value in (_float(row.get("estimated_price_impact_bps")) for row in rows) if value is not None]
    impact_instability = min(1.0, statistics.pstdev(impact_values) / 10.0) if len(impact_values) >= 2 else 0.0
    return {
        "schema_version": "microstructure_orderbook_adversarial_features_v1",
        "exchange": exchange,
        "symbol": symbol.upper(),
        "public_orderbook_default_trust": "LOW",
        "insufficient_book_history": len(rows) < 3,
        "depth_persistence_ms": int(depth_persistence_ms),
        "depth_persistence_reason": depth_persistence_reason,
        "depth_series_stratum": depth_series_stratum or None,
        "depth_series_sample_count": len(rows),
        "depth_series_window_ms": int(window_ms),
        "level_lifetime_distribution": [int(depth_persistence_ms)],
        "add_cancel_ratio": round(add_cancel_ratio, 8),
        "cancel_burst_score": round(cancel_burst_score, 8),
        "quote_stuffing_score": round(quote_stuffing_score, 8),
        "book_flip_rate": round(book_flip_rate, 8),
        "top_book_pull_rate": round(top_book_pull_rate, 8),
        "depth_collapse_bps": round(depth_collapse_bps, 8),
        "spread_expansion_rate": round(spread_expansion_rate, 8),
        "bid_wall_pull_score": round(bid_pull, 8),
        "ask_wall_pull_score": round(ask_pull, 8),
        "imbalance_persistence_score": round(imbalance_persistence_score, 8),
        "imbalance_flip_score": round(book_flip_rate, 8),
        "book_trade_divergence_score": round(divergence, 8),
        "price_impact_instability_score": round(impact_instability, 8),
        "generated_at": iso_now(),
    }
