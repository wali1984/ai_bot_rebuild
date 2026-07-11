"""Tests for the BTC/ETH/SOL symbol-priority policy (Workstream A).

Preference is not permission: majors get priority 1 but only trade when their
own USD edge is positive and market data is valid; valid alts still compete.
No hardcoded exclusion of the wider approved universe.
"""

from __future__ import annotations

from v2.backend.app.services.risk.symbol_priority_policy import (
    MAJOR_SYMBOLS,
    classify_symbol_priority,
)


def _classify(**overrides):
    base = dict(
        symbol="BTCUSDT",
        expected_net_pnl_usd=1.0,
        current_price=60000.0,
        liquidity_usd=1000.0,
        universe_allowed=True,
    )
    base.update(overrides)
    return classify_symbol_priority(**base)


def test_majors_are_btc_eth_sol() -> None:
    assert MAJOR_SYMBOLS == frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})


def test_majors_get_priority_1() -> None:
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        out = _classify(symbol=sym)
        assert out["symbol_priority"] == 1
        assert out["liquidity_tier"] == "MAJOR"
        assert out["major_coin_flag"] is True


def test_top5_alt_gets_priority_2_and_alt_gets_3() -> None:
    assert _classify(symbol="BNBUSDT")["symbol_priority"] == 2
    assert _classify(symbol="FOOUSDT")["symbol_priority"] == 3


def test_major_skipped_when_edge_non_positive() -> None:
    out = _classify(symbol="BTCUSDT", expected_net_pnl_usd=-1.0)
    assert out["candidate_allowed_by_symbol_policy"] is False
    assert out["why_major_skipped"] == "MAJOR_SKIPPED_NON_POSITIVE_USD_EDGE"


def test_valid_alt_competes_when_positive_edge() -> None:
    out = _classify(symbol="FOOUSDT", expected_net_pnl_usd=2.0)
    assert out["candidate_allowed_by_symbol_policy"] is True
    assert out["why_alt_allowed"] == (
        "ALT_ALLOWED_BY_POSITIVE_USD_EDGE_AND_VALID_MARKET_DATA"
    )


def test_alt_blocked_when_not_in_universe() -> None:
    out = _classify(symbol="FOOUSDT", universe_allowed=False)
    assert out["candidate_allowed_by_symbol_policy"] is False
    assert out["symbol_policy_block_reason"] == "SYMBOL_NOT_IN_APPROVED_UNIVERSE"


def test_preference_is_not_exclusion() -> None:
    out = _classify(symbol="FOOUSDT", expected_net_pnl_usd=2.0)
    assert out["forces_major_coin"] is False
    assert out["blocks_alt_only_for_not_major"] is False


def test_major_needs_valid_market_data() -> None:
    out = _classify(symbol="ETHUSDT", liquidity_usd=1.0)
    assert out["candidate_allowed_by_symbol_policy"] is False
    assert out["why_major_skipped"] == "MAJOR_SKIPPED_MARKET_DATA_OR_LIQUIDITY_INVALID"
