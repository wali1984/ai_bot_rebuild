import pytest

from v2.backend.app.domain.symbols.models import SymbolState, SymbolStateRecord
from v2.backend.app.domain.symbols.normalization import normalize_source_symbol
from v2.backend.app.domain.symbols.state_machine import transition


def _identity(status="TRADING"):
    return normalize_source_symbol("binance_coinm", {
        "symbol": "BTCUSD_PERP",
        "pair": "BTCUSD",
        "contractType": "PERPETUAL",
        "contractStatus": status,
        "baseAsset": "BTC",
        "quoteAsset": "USD",
        "marginAsset": "BTC",
    })


def test_trading_symbol_can_move_from_discovered_to_observed():
    record = SymbolStateRecord(identity=_identity())
    moved = transition(record, SymbolState.OBSERVED.value, "fresh_discovery_seen")
    assert moved.state == SymbolState.OBSERVED.value


def test_non_trading_symbol_cannot_be_observed_without_override():
    record = SymbolStateRecord(identity=_identity("DELIVERED"))
    with pytest.raises(ValueError):
        transition(record, SymbolState.OBSERVED.value, "not_allowed")

