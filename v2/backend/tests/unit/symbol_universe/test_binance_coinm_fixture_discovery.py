import json
from pathlib import Path

from v2.backend.app.adapters.symbol_sources.binance_coinm import BinanceCoinMFuturesSource
from v2.backend.app.domain.symbols.models import ContractFamily, ContractType


def test_binance_coinm_fixture_discovers_all_contracts_without_network():
    payload = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/binance_coinm_exchange_info_sample.json").read_text())
    identities = BinanceCoinMFuturesSource().from_payload(payload)

    assert len(identities) == 3
    btc = identities[0]
    assert btc.source_symbol == "BTCUSD_PERP"
    assert btc.source_pair == "BTCUSD"
    assert btc.contract_family == ContractFamily.COIN_M.value
    assert btc.contract_type == ContractType.PERPETUAL.value
    assert btc.settlement_asset == "BTC"
    assert "BTCUSD_PERP" in btc.alias_set
    assert btc.legacy_symbol is None
    assert btc.is_trading()


def test_delivered_contract_is_discovered_but_not_trading():
    payload = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/binance_coinm_exchange_info_sample.json").read_text())
    delivered = BinanceCoinMFuturesSource().from_payload(payload)[2]

    assert delivered.source_symbol == "BNBUSD_200925"
    assert delivered.status == "DELIVERED"
    assert not delivered.is_trading()
