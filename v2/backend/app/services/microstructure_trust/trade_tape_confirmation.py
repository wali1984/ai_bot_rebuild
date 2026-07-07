"""Trade-tape confirmation for visible orderbook intent."""
from __future__ import annotations

from typing import Any, Mapping

from .feed_quality import iso_now


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


def _aggressor_side(trade: Mapping[str, Any]) -> str | None:
    side = str(trade.get("aggressor_side") or trade.get("side") or "").lower()
    if side in {"buy", "sell"}:
        return side
    if trade.get("is_buyer_maker") is True or trade.get("m") is True:
        return "sell"
    if trade.get("is_buyer_maker") is False or trade.get("m") is False:
        return "buy"
    return None


def evaluate_trade_tape_confirmation(
    *,
    symbol: str,
    trades: list[Mapping[str, Any]],
    book_imbalance: float | None = None,
    mark_price: float | None = None,
    index_price: float | None = None,
    basis_bps: float | None = None,
) -> dict[str, Any]:
    aggressive_buy_volume = 0.0
    aggressive_sell_volume = 0.0
    notionals: list[float] = []
    prices: list[float] = []
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        px = _float(trade.get("price") or trade.get("p"))
        qty = _float(trade.get("quantity") or trade.get("qty") or trade.get("q"))
        notional = _float(trade.get("notional"))
        if notional is None and px is not None and qty is not None:
            notional = px * qty
        if notional is None:
            continue
        notionals.append(notional)
        if px is not None:
            prices.append(px)
        side = _aggressor_side(trade)
        if side == "buy":
            aggressive_buy_volume += notional
        elif side == "sell":
            aggressive_sell_volume += notional
    total = aggressive_buy_volume + aggressive_sell_volume
    trade_imbalance = 0.0 if total <= 0 else (aggressive_buy_volume - aggressive_sell_volume) / total
    large_threshold = (sum(notionals) / len(notionals) * 3.0) if notionals else 0.0
    large_trade_cluster = sum(1 for value in notionals if value >= large_threshold and large_threshold > 0)
    price_move_bps = 0.0
    if len(prices) >= 2 and prices[0] > 0:
        price_move_bps = (prices[-1] - prices[0]) / prices[0] * 10000.0
    book_trade_divergence = False
    if book_imbalance is not None and abs(book_imbalance) >= 0.15 and abs(trade_imbalance) >= 0.15:
        book_trade_divergence = (book_imbalance > 0) != (trade_imbalance > 0)
    mark_price_confirmation = True
    if mark_price is not None and prices and prices[-1] > 0:
        mark_price_confirmation = abs(mark_price - prices[-1]) / prices[-1] * 10000.0 <= 10.0
    index_price_confirmation = True
    if index_price is not None and prices and prices[-1] > 0:
        index_price_confirmation = abs(index_price - prices[-1]) / prices[-1] * 10000.0 <= 15.0
    basis_confirmation = True if basis_bps is None else abs(basis_bps) <= 25.0
    confirmation_score = 0.5
    if total > 0:
        confirmation_score += min(0.25, abs(trade_imbalance) * 0.25)
    if book_trade_divergence:
        confirmation_score -= 0.35
    if not mark_price_confirmation:
        confirmation_score -= 0.1
    if not index_price_confirmation:
        confirmation_score -= 0.1
    if not basis_confirmation:
        confirmation_score -= 0.1
    sweep_prints = large_trade_cluster > 0 and abs(price_move_bps) >= 10.0
    if sweep_prints:
        confirmation_score -= 0.1
    confirmation_score = max(0.0, min(1.0, confirmation_score))
    return {
        "schema_version": "microstructure_trade_tape_confirmation_v1",
        "symbol": symbol.upper(),
        "aggressive_buy_volume": round(aggressive_buy_volume, 8),
        "aggressive_sell_volume": round(aggressive_sell_volume, 8),
        "trade_imbalance": round(trade_imbalance, 8),
        "volume_acceleration": round(float(len(notionals)), 8),
        "large_trade_cluster": int(large_trade_cluster),
        "sweep_prints": bool(sweep_prints),
        "price_move_vs_book_imbalance": round(price_move_bps, 8),
        "book_trade_divergence_score": 1.0 if book_trade_divergence else 0.0,
        "mark_price_confirmation": bool(mark_price_confirmation),
        "index_price_confirmation": bool(index_price_confirmation),
        "basis_confirmation": bool(basis_confirmation),
        "trade_tape_confirmation_score": round(confirmation_score, 8),
        "generated_at": iso_now(),
    }
