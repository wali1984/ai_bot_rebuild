import json
from pathlib import Path

import pytest

from v2.backend.app.domain.symbols.models import SymbolState, SymbolStateRecord
from v2.backend.app.domain.symbols.normalization import normalize_source_symbol
from v2.backend.app.domain.symbols.state_machine import transition


def _payload(name):
    return json.loads(Path("v2/backend/tests/fixtures/symbol_universe/source_symbol_payloads.json").read_text())[name]


def _identity(status="TRADING"):
    payload = _payload("binance_coinm_btc_perp")
    payload["contractStatus"] = status
    return normalize_source_symbol("binance_coinm", payload)


def test_trading_symbol_can_move_from_discovered_to_observed():
    record = SymbolStateRecord(identity=_identity())
    moved = transition(record, SymbolState.OBSERVED.value, "fresh_discovery_seen")
    assert moved.state == SymbolState.OBSERVED.value


def test_non_trading_symbol_cannot_be_observed_without_override():
    record = SymbolStateRecord(identity=_identity("DELIVERED"))
    with pytest.raises(ValueError):
        transition(record, SymbolState.OBSERVED.value, "not_allowed")
