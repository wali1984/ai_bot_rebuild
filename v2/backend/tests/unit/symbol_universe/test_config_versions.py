from v2.backend.app.adapters.symbol_sources.binance_coinm import BinanceCoinMFuturesSource
from v2.backend.app.services.symbol_universe.service import HOT_RELOAD_COMPONENTS, SymbolUniverseService


def test_config_version_marks_all_runtime_components_for_hot_reload_on_change():
    source = BinanceCoinMFuturesSource()
    previous = []
    current = source.from_payload({"symbols": [{
        "symbol": "BTCUSD_PERP",
        "pair": "BTCUSD",
        "contractType": "PERPETUAL",
        "contractStatus": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
    }]})

    version = SymbolUniverseService().make_universe_version(previous, current, "fixture_discovery")

    assert version.added_symbols == [current[0].canonical_symbol_id]
    assert version.hot_reload_required_components == HOT_RELOAD_COMPONENTS


def test_config_version_with_no_change_requires_no_hot_reload():
    source = BinanceCoinMFuturesSource()
    current = source.from_payload({"symbols": [{
        "symbol": "BTCUSD_PERP",
        "pair": "BTCUSD",
        "contractType": "PERPETUAL",
        "contractStatus": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
    }]})

    version = SymbolUniverseService().make_universe_version(current, current, "no_change")

    assert version.changed_symbols == []
    assert version.hot_reload_required_components == []
