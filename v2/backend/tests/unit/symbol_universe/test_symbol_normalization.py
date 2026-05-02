from v2.backend.app.domain.symbols.normalization import (
    match_cross_source_symbol,
    normalize_source_symbol,
    resolve_symbol_alias,
)


def test_coinm_perp_and_quarterly_do_not_collapse():
    perp = normalize_source_symbol("binance_coinm", {
        "symbol": "BTCUSD_PERP",
        "pair": "BTCUSD",
        "contractType": "PERPETUAL",
        "contractStatus": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
    })
    quarterly = normalize_source_symbol("binance_coinm", {
        "symbol": "BTCUSD_240628",
        "pair": "BTCUSD",
        "contractType": "CURRENT_QUARTER",
        "contractStatus": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
        "deliveryDate": 1719561600000,
    })

    assert perp.canonical_symbol_id != quarterly.canonical_symbol_id
    assert match_cross_source_symbol(perp, quarterly) == "none"


def test_legacy_alias_resolves_to_coinm_identity():
    identity = normalize_source_symbol("binance_coinm", {
        "symbol": "BTCUSD_PERP",
        "pair": "BTCUSD",
        "contractType": "PERPETUAL",
        "contractStatus": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
    })

    assert resolve_symbol_alias("BTCUSDT", "legacy_config", [identity]) == identity
    assert resolve_symbol_alias("BTCUSD_PERP", "binance_coinm", [identity]) == identity


def test_coinapi_and_kucoin_support_alias_registry_inputs():
    coinapi = normalize_source_symbol("coinapi_ws", {
        "symbol": "BINANCEFTS_PERP_BTC_USD",
        "pair": "BTC/USD",
        "base": "BTC",
        "quote": "USD",
        "settlement": "BTC",
        "contract_type": "PERPETUAL",
    })
    kucoin = normalize_source_symbol("kucoin", {
        "symbol": "XBTUSDTM",
        "pair": "BTC-USDT",
        "base": "BTC",
        "quote": "USDT",
        "settlement": "USDT",
        "contract_type": "PERPETUAL",
    })

    assert coinapi.source == "coinapi_ws"
    assert kucoin.source == "kucoin"
    assert match_cross_source_symbol(coinapi, kucoin) in {"medium", "none"}

