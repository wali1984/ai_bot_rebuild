import json
from pathlib import Path

from v2.backend.app.domain.symbols.normalization import (
    match_cross_source_symbol,
    normalize_source_symbol,
    resolve_symbol_alias,
)


def _payload(name):
    return json.loads(Path("v2/backend/tests/fixtures/symbol_universe/source_symbol_payloads.json").read_text())[name]


def test_coinm_perp_and_quarterly_do_not_collapse():
    perp = normalize_source_symbol("binance_coinm", _payload("binance_coinm_btc_perp"))
    quarterly = normalize_source_symbol("binance_coinm", _payload("binance_coinm_btc_quarter"))

    assert perp.canonical_symbol_id != quarterly.canonical_symbol_id
    assert match_cross_source_symbol(perp, quarterly) == "none"


def test_usdm_btcusdt_maps_to_legacy_btcusdt_with_high_confidence():
    identity = normalize_source_symbol("binance_usdm", _payload("binance_usdm_btc_perp"))

    assert resolve_symbol_alias("BTCUSDT", "legacy_config", [identity]) == identity
    assert resolve_symbol_alias("BTCUSDT", "binance_usdm", [identity]) == identity
    assert identity.normalization_confidence == "high"


def test_coinm_perp_does_not_equal_usdm_perp():
    usdm = normalize_source_symbol("binance_usdm", _payload("binance_usdm_btc_perp"))
    coinm = normalize_source_symbol("binance_coinm", _payload("binance_coinm_btc_perp"))

    assert match_cross_source_symbol(usdm, coinm) == "none"


def test_coinapi_and_kucoin_support_alias_registry_inputs():
    usdm = normalize_source_symbol("binance_usdm", _payload("binance_usdm_btc_perp"))
    coinapi = normalize_source_symbol("coinapi_ws", _payload("coinapi_ws_btc_perp"))
    kucoin = normalize_source_symbol("kucoin", _payload("kucoin_btc_perp"))

    assert coinapi.source == "coinapi_ws"
    assert kucoin.source == "kucoin"
    assert match_cross_source_symbol(usdm, coinapi) == "high"
    assert match_cross_source_symbol(usdm, kucoin) == "high"
