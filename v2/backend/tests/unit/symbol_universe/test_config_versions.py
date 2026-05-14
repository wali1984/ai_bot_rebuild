import json
from pathlib import Path

from v2.backend.app.adapters.symbol_sources.binance_usdm import BinanceUsdMFuturesSource
from v2.backend.app.services.symbol_universe.service import (
    DYNAMIC_SYMBOL_SOURCES,
    HOT_RELOAD_COMPONENTS,
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
    SymbolUniverseService,
)


def _payload(name):
    return json.loads(Path("v2/backend/tests/fixtures/symbol_universe/source_symbol_payloads.json").read_text())[name]


def test_config_version_marks_all_runtime_components_for_hot_reload_on_change():
    source = BinanceUsdMFuturesSource()
    previous = []
    current = source.from_payload({"symbols": [_payload("binance_usdm_btc_perp")]})

    version = SymbolUniverseService().make_universe_version(previous, current, "fixture_discovery")

    assert version.added_symbols == [current[0].canonical_symbol_id]
    assert version.hot_reload_required_components == HOT_RELOAD_COMPONENTS


def test_config_version_with_no_change_requires_no_hot_reload():
    source = BinanceUsdMFuturesSource()
    current = source.from_payload({"symbols": [_payload("binance_usdm_btc_perp")]})

    version = SymbolUniverseService().make_universe_version(current, current, "no_change")

    assert version.changed_symbols == []
    assert version.hot_reload_required_components == []


def test_legacy_active_symbols_are_explicit_subset_not_discovered_universe():
    fixture = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/legacy_config_active_symbols.json").read_text())
    service = SymbolUniverseService(legacy_active_symbols=fixture["symbols"])

    assert len(service.legacy_active_symbols()) == 25
    assert "BTCUSDT" in service.legacy_active_symbols()
    assert set(service.legacy_active_symbols()) == set(LEGACY_ACTIVE_SYMBOLS_25)


def test_default_symbol_universe_preserves_current_25_legacy_scope():
    service = SymbolUniverseService()

    assert service.legacy_active_symbols() == LEGACY_ACTIVE_SYMBOLS_25
    assert DYNAMIC_SYMBOL_SOURCES == [
        "binance_futures",
        "coinank",
        "coinapi",
        "kucoin",
        "future_ingestors",
    ]
    assert "model_confidence" in SYMBOL_SELECTION_SCORE_FACTORS
    assert "operator_overrides" in SYMBOL_SELECTION_SCORE_FACTORS
