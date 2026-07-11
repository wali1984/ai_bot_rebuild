"""Symbol priority policy for A+ candidate routing.

Preference is not permission. BTC/ETH/SOL/top-5 liquid symbols get priority
only when their own USD edge is positive and market data/liquidity are valid.
Valid approved-universe alts are allowed to compete when majors are flat.
"""

from __future__ import annotations

from typing import Any, Mapping

SCHEMA_VERSION = "symbol_priority_policy_v1"

MAJOR_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
DEFAULT_TOP5 = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def classify_symbol_priority(
    *,
    symbol: str,
    expected_net_pnl_usd: float | None,
    current_price: float | None,
    liquidity_usd: float | None,
    universe_allowed: bool,
    top5_symbols: tuple[str, ...] | list[str] = DEFAULT_TOP5,
    min_liquidity_usd: float = 200.0,
) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    edge = _float(expected_net_pnl_usd)
    price = _float(current_price)
    liquidity = _float(liquidity_usd)
    top5_set = {str(item).upper() for item in top5_symbols}
    major = symbol in MAJOR_SYMBOLS
    top5 = symbol in top5_set
    market_data_ok = price is not None and price > 0 and liquidity is not None and liquidity >= min_liquidity_usd
    positive_edge = edge is not None and edge > 0

    if major and not positive_edge:
        why_major_skipped = "MAJOR_SKIPPED_NON_POSITIVE_USD_EDGE"
    elif major and not market_data_ok:
        why_major_skipped = "MAJOR_SKIPPED_MARKET_DATA_OR_LIQUIDITY_INVALID"
    else:
        why_major_skipped = None

    if not universe_allowed:
        why_alt_allowed = None
        allowed = False
        block_reason = "SYMBOL_NOT_IN_APPROVED_UNIVERSE"
    elif not market_data_ok:
        why_alt_allowed = None
        allowed = False
        block_reason = "MARKET_DATA_OR_LIQUIDITY_INVALID"
    elif not positive_edge:
        why_alt_allowed = None
        allowed = False
        block_reason = "NON_POSITIVE_USD_EDGE"
    else:
        allowed = True
        block_reason = None
        why_alt_allowed = None if major else "ALT_ALLOWED_BY_POSITIVE_USD_EDGE_AND_VALID_MARKET_DATA"

    if major:
        priority = 1
        tier = "MAJOR"
    elif top5:
        priority = 2
        tier = "TOP5"
    else:
        priority = 3
        tier = "APPROVED_ALT"

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "symbol_priority": priority,
        "liquidity_tier": tier,
        "major_coin_flag": major,
        "top5_coin_flag": top5,
        "universe_allowed": bool(universe_allowed),
        "market_data_ok": market_data_ok,
        "expected_net_pnl_usd": edge,
        "candidate_allowed_by_symbol_policy": allowed,
        "symbol_policy_block_reason": block_reason,
        "why_major_skipped": why_major_skipped,
        "why_alt_allowed": why_alt_allowed,
        "stablecoin_preference": False,
        "forces_major_coin": False,
        "blocks_alt_only_for_not_major": False,
    }
