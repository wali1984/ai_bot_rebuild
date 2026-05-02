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


def test_configured_legacy_alias_resolves_to_coinm_identity():
    payload = _payload("binance_coinm_btc_perp")
    payload["legacy_symbol"] = "BTCUSDT"
    identity = normalize_source_symbol("binance_coinm", payload)

    assert resolve_symbol_alias("BTCUSDT", "legacy_config", [identity]) == identity
    assert resolve_symbol_alias("BTCUSD_PERP", "binance_coinm", [identity]) == identity


def test_discovered_coinm_symbol_does_not_become_legacy_active_by_default():
    identity = normalize_source_symbol("binance_coinm", _payload("binance_coinm_btc_perp"))

    assert identity.legacy_symbol is None


def test_coinapi_and_kucoin_support_alias_registry_inputs():
    coinapi = normalize_source_symbol("coinapi_ws", _payload("coinapi_ws_btc_perp"))
    kucoin = normalize_source_symbol("kucoin", _payload("kucoin_btc_perp"))

    assert coinapi.source == "coinapi_ws"
    assert kucoin.source == "kucoin"
    assert match_cross_source_symbol(coinapi, kucoin) in {"medium", "none"}
