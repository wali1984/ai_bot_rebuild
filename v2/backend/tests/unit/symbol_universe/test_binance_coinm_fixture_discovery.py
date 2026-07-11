import json
from pathlib import Path

import pytest

from v2.backend.app.adapters.symbol_sources.binance_coinm import BinanceCoinMFuturesSource
from v2.backend.app.domain.symbols.models import ContractFamily, ContractType


class RedisLike:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


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


def test_binance_coinm_exchange_info_uses_websocket_cache_before_rest(monkeypatch):
    payload = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/binance_coinm_exchange_info_sample.json").read_text())
    redis_client = RedisLike({"v2:exchange:binance_coinm:exchangeInfo": json.dumps(payload)})

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("REST exchangeInfo fallback must not run when cache is present")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    fetched = BinanceCoinMFuturesSource(redis_client=redis_client).fetch_exchange_info()

    assert fetched["symbols"][0]["symbol"] == "BTCUSD_PERP"
    assert fetched["transport"] == "websocket_cache_primary"
    assert fetched["source_key"] == "v2:exchange:binance_coinm:exchangeInfo"
    assert fetched["rest_fallback_used"] is False


def test_binance_coinm_exchange_info_blocks_rest_when_cache_missing(monkeypatch):
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)

    with pytest.raises(RuntimeError, match="REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"):
        BinanceCoinMFuturesSource(redis_client=RedisLike({})).fetch_exchange_info()
