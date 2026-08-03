"""Cross-venue confirmation for public books and tape."""
from __future__ import annotations

from typing import Any, Mapping

from .feed_quality import iso_now


CROSS_VENUE_EXECUTABLE_DEPTH_FLOOR_USD = 50_000.0
DEEP_ALIGNED_DEPTH_DISAGREEMENT_PENALTY_CAP = 0.08
THIN_OR_UNCONFIRMED_DEPTH_DISAGREEMENT_PENALTY_CAP = 0.25


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


def _mid(payload: Mapping[str, Any] | None) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    direct = _float(payload.get("mid") or payload.get("bid_ask_mid") or payload.get("mid_price"))
    if direct is not None:
        return direct
    bid = _float(payload.get("best_bid") or payload.get("bid"))
    ask = _float(payload.get("best_ask") or payload.get("ask"))
    if bid is None or ask is None:
        return None
    return (bid + ask) / 2.0


def evaluate_cross_venue_confirmation(
    *,
    symbol: str,
    binance: Mapping[str, Any] | None = None,
    kucoin: Mapping[str, Any] | None = None,
    coinank_liquidation_context: Mapping[str, Any] | None = None,
    correlated_move_confirmation: float | None = None,
    trade_tape_confirmation_score: float | None = None,
) -> dict[str, Any]:
    b_mid = _mid(binance)
    k_mid = _mid(kucoin)
    price_divergence_bps = None
    if b_mid is not None and k_mid is not None and b_mid > 0 and k_mid > 0:
        price_divergence_bps = abs(b_mid - k_mid) / ((b_mid + k_mid) / 2.0) * 10000.0
    b_depth = _float((binance or {}).get("orderbook_depth_usd") if isinstance(binance, Mapping) else None)
    k_depth = _float((kucoin or {}).get("orderbook_depth_usd") if isinstance(kucoin, Mapping) else None)
    depth_disagreement = 0.0
    if b_depth is not None and k_depth is not None and max(b_depth, k_depth) > 0:
        depth_disagreement = abs(b_depth - k_depth) / max(b_depth, k_depth)
    b_imb = _float((binance or {}).get("depth_imbalance") if isinstance(binance, Mapping) else None)
    k_imb = _float((kucoin or {}).get("depth_imbalance") if isinstance(kucoin, Mapping) else None)
    imbalance_conflict = b_imb is not None and k_imb is not None and abs(b_imb) > 0.15 and abs(k_imb) > 0.15 and (b_imb > 0) != (k_imb > 0)
    venues_present = int(binance is not None) + int(kucoin is not None)
    price_aligned = price_divergence_bps is not None and price_divergence_bps <= 5.0
    executable_depth_confirmed = (
        b_depth is not None
        and k_depth is not None
        and min(b_depth, k_depth) >= CROSS_VENUE_EXECUTABLE_DEPTH_FLOOR_USD
    )
    depth_penalty_cap = (
        DEEP_ALIGNED_DEPTH_DISAGREEMENT_PENALTY_CAP
        if venues_present >= 2 and price_aligned and executable_depth_confirmed and not imbalance_conflict
        else THIN_OR_UNCONFIRMED_DEPTH_DISAGREEMENT_PENALTY_CAP
    )
    depth_disagreement_penalty = min(depth_penalty_cap, depth_disagreement * 0.25)
    score = 0.25 if venues_present <= 1 else 0.65
    if price_divergence_bps is not None:
        score -= min(0.3, price_divergence_bps / 100.0)
    score -= depth_disagreement_penalty
    if imbalance_conflict:
        score -= 0.25
    if trade_tape_confirmation_score is not None:
        score += (trade_tape_confirmation_score - 0.5) * 0.2
    if correlated_move_confirmation is not None:
        score += (correlated_move_confirmation - 0.5) * 0.15
    if isinstance(coinank_liquidation_context, Mapping) and coinank_liquidation_context:
        score += 0.05
    score = max(0.0, min(1.0, score))
    return {
        "schema_version": "microstructure_cross_venue_confirmation_v1",
        "symbol": symbol.upper(),
        "venues_present": venues_present,
        "binance_present": binance is not None,
        "kucoin_present": kucoin is not None,
        "price_divergence_bps": None if price_divergence_bps is None else round(price_divergence_bps, 8),
        "depth_disagreement_score": round(depth_disagreement, 8),
        "depth_disagreement_penalty": round(depth_disagreement_penalty, 8),
        "depth_penalty_cap": depth_penalty_cap,
        "executable_depth_floor_usd": CROSS_VENUE_EXECUTABLE_DEPTH_FLOOR_USD,
        "executable_depth_confirmed": bool(executable_depth_confirmed),
        "price_aligned": bool(price_aligned),
        "imbalance_conflict": bool(imbalance_conflict),
        "lead_lag_classification": "single_venue_unconfirmed" if venues_present <= 1 else ("venue_conflict" if imbalance_conflict else "venues_confirm"),
        "cross_venue_confirmation_score": round(score, 8),
        "generated_at": iso_now(),
    }
