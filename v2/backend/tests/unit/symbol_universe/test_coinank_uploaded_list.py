from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.adapters.symbol_sources.coinank import CoinAnkSymbolSource
from v2.backend.app.domain.symbols.coinank_rows import (
    confirm_coinank_against_usdm,
)
from v2.backend.app.domain.symbols.normalization import (
    match_cross_source_symbol,
    normalize_source_symbol,
)


SYNTHETIC_FIXTURE = Path(
    "v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json"
)
USDM_FIXTURE = Path(
    "v2/backend/tests/fixtures/symbol_universe/source_symbol_payloads.json"
)


def _load_synthetic():
    return json.loads(SYNTHETIC_FIXTURE.read_text())["rows"]


def _by_label(rows, label):
    return next(r for r in rows if r.get("_label") == label)


def _usdm(name):
    return json.loads(USDM_FIXTURE.read_text())[name]


def test_coinank_btcusdt_is_discovery_only_with_low_confidence():
    row = _by_label(_load_synthetic(), "binance_usdm_candidate_btc_perp")
    identity = normalize_source_symbol("coinank", row)
    assert identity.source == "coinank"
    assert identity.normalization_confidence == "low"
    assert identity.status == "discovery_only"
    assert identity.contract_family == "unknown"
    assert identity.canonical_symbol_id.startswith("COINANK-DISC-BINANCE-")
    assert identity.metadata["candidate_for_usdm_confirmation"] is True
    assert identity.metadata["requires_confirmation"] is True


def test_coinank_btcusdt_does_not_collapse_with_usdm_btcusdt():
    coinank = normalize_source_symbol(
        "coinank", _by_label(_load_synthetic(), "binance_usdm_candidate_btc_perp")
    )
    usdm = normalize_source_symbol("binance_usdm", _usdm("binance_usdm_btc_perp"))
    assert coinank.canonical_symbol_id != usdm.canonical_symbol_id
    assert match_cross_source_symbol(coinank, usdm) == "none"


def test_coinank_btcusd_perp_marked_inverse_and_does_not_collapse_with_usdm():
    row = _by_label(_load_synthetic(), "coinm_inverse_perp_must_not_collapse")
    identity = normalize_source_symbol("coinank", row)
    assert identity.metadata["is_perp_inverse"] is True
    assert identity.metadata["candidate_for_usdm_confirmation"] is False
    usdm = normalize_source_symbol("binance_usdm", _usdm("binance_usdm_btc_perp"))
    assert match_cross_source_symbol(identity, usdm) == "none"


def test_coinank_dated_does_not_collapse_with_perpetuals():
    row = _by_label(_load_synthetic(), "dated_quarterly_must_not_collapse")
    identity = normalize_source_symbol("coinank", row)
    assert identity.metadata["is_dated"] is True
    assert identity.contract_type == "dated_delivery"
    assert identity.metadata["candidate_for_usdm_confirmation"] is False


def test_coinank_usdc_separate_from_usdt():
    usdc = normalize_source_symbol(
        "coinank", _by_label(_load_synthetic(), "usdc_pair_separate_from_usdt")
    )
    usdt = normalize_source_symbol(
        "coinank", _by_label(_load_synthetic(), "binance_usdm_candidate_btc_perp")
    )
    assert usdc.quote_asset == "USDC"
    assert usdt.quote_asset == "USDT"
    assert usdc.canonical_symbol_id != usdt.canonical_symbol_id
    assert match_cross_source_symbol(usdc, usdt) == "none"


def test_ethbtc_not_usdm_candidate():
    row = _by_label(_load_synthetic(), "ethbtc_must_not_be_usdm")
    identity = normalize_source_symbol("coinank", row)
    assert identity.quote_asset == "BTC"
    assert identity.metadata["candidate_for_usdm_confirmation"] is False


def test_stock_like_marked_and_blocked_from_confirmation():
    row = _by_label(_load_synthetic(), "stock_like_must_not_auto_eligible")
    identity = normalize_source_symbol("coinank", row)
    assert identity.metadata["is_stock_like"] is True
    assert identity.metadata["candidate_for_usdm_confirmation"] is False
    usdm = normalize_source_symbol("binance_usdm", _usdm("binance_usdm_btc_perp"))
    assert confirm_coinank_against_usdm(identity, [usdm]) is None


def test_chinese_name_preserved_and_blocked_from_confirmation():
    row = _by_label(_load_synthetic(), "chinese_name_preserved_requires_confirmation")
    identity = normalize_source_symbol("coinank", row)
    assert identity.metadata["is_chinese_name"] is True
    assert identity.metadata["coinank_raw"]["baseCoin"] == "\u8305\u53f0"
    assert identity.metadata["candidate_for_usdm_confirmation"] is False
    assert identity.base_asset.startswith("CJK")


def test_confirmation_requires_usdm_present_and_trading():
    coinank = normalize_source_symbol(
        "coinank", _by_label(_load_synthetic(), "binance_usdm_candidate_btc_perp")
    )
    usdm = normalize_source_symbol("binance_usdm", _usdm("binance_usdm_btc_perp"))
    confirmed = confirm_coinank_against_usdm(coinank, [usdm])
    assert confirmed is not None and confirmed.source == "binance_usdm"
    assert confirm_coinank_against_usdm(coinank, []) is None
    settling = normalize_source_symbol("binance_usdm", _usdm("binance_usdm_old_settling"))
    assert confirm_coinank_against_usdm(coinank, [settling]) is None


def test_adapter_emits_identities_with_alias_set():
    adapter = CoinAnkSymbolSource()
    identities = adapter.from_payload({"rows": _load_synthetic()})
    assert len(identities) == 8
    for identity in identities:
        assert identity.source == "coinank"
        assert identity.canonical_symbol_id in identity.alias_set
        assert identity.normalization_confidence == "low"


def test_adapter_confirm_against_usdm_returns_only_valid_matches():
    adapter = CoinAnkSymbolSource()
    coinank = adapter.from_payload({"rows": _load_synthetic()})
    usdm = normalize_source_symbol("binance_usdm", _usdm("binance_usdm_btc_perp"))
    confirmed = adapter.confirm_against_usdm(coinank, [usdm])
    btc_usdt_id = next(
        c.canonical_symbol_id
        for c in coinank
        if c.metadata["coinank_raw"]["symbol"] == "BTCUSDT"
    )
    assert btc_usdt_id in confirmed
    assert confirmed[btc_usdt_id].source == "binance_usdm"
    eth_btc_id = next(
        c.canonical_symbol_id
        for c in coinank
        if c.metadata["coinank_raw"]["symbol"] == "ETHBTC"
    )
    assert eth_btc_id not in confirmed
