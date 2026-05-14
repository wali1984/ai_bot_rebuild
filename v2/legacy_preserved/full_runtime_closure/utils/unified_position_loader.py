"""
Unified Position Loader (Feb 2026)
===================================
Single canonical loader for position data used across all modules.

Reads from Redis with a well-defined priority:
  1. positions:live:{symbol}  (full hedge-mode: long + short JSON fields)
  2. positions:live:{account}:{symbol}  (net-only fallback)
  3. portfolio:positions:{account}  (legacy hash)

Returns a standardized schema per symbol with BOTH legs.

Usage:
    from utils.unified_position_loader import load_all_positions

    positions = load_all_positions(redis_client, account_id="primary")
    # Returns: {
    #   "BTCUSDT": {
    #       "LONG": { "size": 0.098, "side": "LONG", "margin_used": 88.0, ... } or None,
    #       "SHORT": { "size": 0.222, "side": "SHORT", "margin_used": 199.4, ... } or None,
    #       "net_side": "SHORT",
    #       "net_size": 0.124,
    #       "gross_size": 0.320,
    #       "gross_margin": 287.4,
    #       "gross_notional": 21234.0,
    #       "net_notional": -8353.0,
    #       "unrealized_pnl": -57.09,
    #       "has_long": True,
    #       "has_short": True,
    #   }, ...
    # }
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Standard per-leg schema fields
_LEG_FIELDS = {
    "size": 0.0,
    "side": "",
    "entry_price": 0.0,
    "current_price": 0.0,
    "mark_price": 0.0,
    "unrealized_pnl": 0.0,
    "pnl_pct": 0.0,
    "roi_pct": 0.0,
    "leverage": 1.0,
    "margin_used": 0.0,
    "notional": 0.0,
    "liquidation_price": 0.0,
    "margin_type": "cross",
    "has_position": False,
}


def _normalize_leg(raw: dict) -> Optional[dict]:
    """Normalize a raw per-leg dict to standard schema."""
    if not isinstance(raw, dict):
        return None

    size = abs(float(
        raw.get("size", 0)
        or raw.get("positionAmt", 0)
        or raw.get("position_amt", 0)
        or 0
    ))
    if size <= 0:
        return None

    side = str(raw.get("side", raw.get("positionSide", ""))).upper()
    if side not in ("LONG", "SHORT"):
        # Infer from signed positionAmt
        amt = float(raw.get("positionAmt", raw.get("position_amt", 0)) or 0)
        side = "LONG" if amt > 0 else "SHORT"

    mark = float(raw.get("mark_price", 0) or raw.get("markPrice", 0) or raw.get("current_price", 0) or 0)
    entry = float(raw.get("entry_price", 0) or raw.get("entryPrice", 0) or 0)
    leverage = float(raw.get("leverage", 1) or 1)

    margin = float(
        raw.get("margin_used", 0)
        or raw.get("initialMargin", 0)
        or raw.get("initial_margin_usd", 0)
        or 0
    )
    # Approximate margin from notional/leverage if missing
    if margin <= 0 and mark > 0 and leverage > 0:
        margin = (size * mark) / leverage

    notional = float(raw.get("notional", 0) or raw.get("positionNotional", 0) or 0)
    if notional <= 0 and mark > 0:
        notional = size * mark

    unrealized_pnl = float(
        raw.get("unrealized_pnl", 0)
        or raw.get("unRealizedProfit", 0)
        or raw.get("unrealizedProfit", 0)
        or raw.get("unrealized_pnl_usd", 0)
        or 0
    )
    pnl_pct = float(raw.get("pnl_pct", 0) or raw.get("pnl_percentage", 0) or 0)
    roi_pct = float(raw.get("roi_pct", 0) or 0)

    return {
        "size": size,
        "side": side,
        "entry_price": entry,
        "current_price": mark,
        "mark_price": mark,
        "unrealized_pnl": unrealized_pnl,
        "pnl_pct": pnl_pct,
        "roi_pct": roi_pct,
        "leverage": leverage,
        "margin_used": margin,
        "notional": notional,
        "liquidation_price": float(raw.get("liquidation_price", 0) or raw.get("liq_price", 0) or 0),
        "margin_type": str(raw.get("margin_type", "cross")),
        "has_position": True,
    }


def _build_symbol_record(long_leg: Optional[dict], short_leg: Optional[dict]) -> dict:
    """Build a unified symbol record from (possibly None) LONG and SHORT legs."""
    has_long = long_leg is not None
    has_short = short_leg is not None

    long_notional = long_leg["notional"] if has_long else 0.0
    short_notional = short_leg["notional"] if has_short else 0.0
    long_margin = long_leg["margin_used"] if has_long else 0.0
    short_margin = short_leg["margin_used"] if has_short else 0.0
    long_pnl = long_leg["unrealized_pnl"] if has_long else 0.0
    short_pnl = short_leg["unrealized_pnl"] if has_short else 0.0
    long_size = long_leg["size"] if has_long else 0.0
    short_size = short_leg["size"] if has_short else 0.0

    gross_notional = long_notional + short_notional
    net_notional = long_notional - short_notional
    gross_margin = long_margin + short_margin

    if has_long and not has_short:
        net_side = "LONG"
    elif has_short and not has_long:
        net_side = "SHORT"
    elif has_long and has_short:
        net_side = "LONG" if long_notional >= short_notional else "SHORT"
    else:
        net_side = "FLAT"

    return {
        "LONG": long_leg,
        "SHORT": short_leg,
        "net_side": net_side,
        "net_size": abs(long_size - short_size),
        "gross_size": long_size + short_size,
        "gross_margin": gross_margin,
        "gross_notional": gross_notional,
        "net_notional": net_notional,
        "unrealized_pnl": long_pnl + short_pnl,
        "has_long": has_long,
        "has_short": has_short,
    }


def load_all_positions(
    redis_client,
    account_id: str = "primary",
    symbols: Optional[list] = None,
) -> Dict[str, dict]:
    """
    Load all positions from Redis with hedge-mode support.

    Parameters
    ----------
    redis_client : Redis client
    account_id   : Account ID (default "primary")
    symbols      : Optional list of symbols to load. If None, auto-discover.

    Returns
    -------
    Dict mapping symbol (e.g. "BTCUSDT") to unified position record.
    Only includes symbols with at least one active leg.
    """
    if not redis_client:
        return {}

    result: Dict[str, dict] = {}

    try:
        # Step 1: Discover symbols with positions
        if symbols is None:
            sym_set = redis_client.smembers(f"positions:live:symbols:{account_id}") or set()
            symbols = [s.decode() if isinstance(s, bytes) else str(s) for s in sym_set]

        # Step 2: Load per-symbol hedge data from positions:live:{symbol}
        for sym in symbols:
            long_leg = None
            short_leg = None

            try:
                raw_hash = redis_client.hgetall(f"positions:live:{sym}")
                if raw_hash:
                    for side_key in (b"long", "long"):
                        raw_json = raw_hash.get(side_key)
                        if raw_json:
                            raw_str = raw_json.decode() if isinstance(raw_json, bytes) else str(raw_json)
                            parsed = json.loads(raw_str)
                            if isinstance(parsed, dict) and parsed.get("has_position"):
                                leg = _normalize_leg(parsed)
                                if leg and leg["side"] == "LONG":
                                    long_leg = leg
                                elif leg and leg["side"] == "SHORT":
                                    short_leg = leg

                    for side_key in (b"short", "short"):
                        raw_json = raw_hash.get(side_key)
                        if raw_json:
                            raw_str = raw_json.decode() if isinstance(raw_json, bytes) else str(raw_json)
                            parsed = json.loads(raw_str)
                            if isinstance(parsed, dict) and parsed.get("has_position"):
                                leg = _normalize_leg(parsed)
                                if leg and leg["side"] == "SHORT":
                                    short_leg = leg
                                elif leg and leg["side"] == "LONG":
                                    long_leg = leg
            except Exception as e:
                logger.debug("UPL: positions:live:%s read error: %s", sym, e)

            # Step 3: Fallback to positions:live:{account}:{symbol} (net-only)
            if long_leg is None and short_leg is None:
                try:
                    net_hash = redis_client.hgetall(f"positions:live:{account_id}:{sym}")
                    if net_hash:
                        net_data = {
                            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                            for k, v in net_hash.items()
                        }
                        amt = float(net_data.get("position_amt", 0) or 0)
                        if abs(amt) > 0:
                            leg = _normalize_leg(net_data)
                            if leg:
                                if leg["side"] == "LONG":
                                    long_leg = leg
                                else:
                                    short_leg = leg
                except Exception as e:
                    logger.debug("UPL: positions:live:%s:%s fallback error: %s", account_id, sym, e)

            if long_leg or short_leg:
                result[sym] = _build_symbol_record(long_leg, short_leg)

    except Exception as e:
        logger.warning("UPL: load_all_positions error: %s", e)

    return result


def get_position_for_symbol(
    redis_client,
    symbol: str,
    account_id: str = "primary",
) -> dict:
    """
    Load position for a single symbol.

    Returns unified record or empty dict if no position.
    """
    all_pos = load_all_positions(redis_client, account_id, symbols=[symbol])
    return all_pos.get(symbol, {})


def has_any_leg(symbol_record: dict, side: str = None) -> bool:
    """Check if a unified symbol record has an active leg.

    Args:
        symbol_record: Output from load_all_positions for one symbol
        side: Optional "LONG" or "SHORT" to check specific side. 
              If None, returns True if any leg exists.
    """
    if not symbol_record:
        return False
    if side:
        leg = symbol_record.get(side.upper())
        return leg is not None and leg.get("has_position", False)
    return symbol_record.get("has_long", False) or symbol_record.get("has_short", False)
