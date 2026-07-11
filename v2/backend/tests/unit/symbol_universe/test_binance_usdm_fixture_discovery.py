import json
from pathlib import Path

import pytest

from v2.backend.app.adapters.symbol_sources.binance_usdm import BinanceUsdMFuturesSource
from v2.backend.app.domain.symbols.models import ContractFamily, ContractType


class RedisLike:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


def test_binance_usdm_fixture_is_primary_futures_discovery_without_network():
    payload = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/binance_usdm_exchange_info_sample.json").read_text())
    identities = BinanceUsdMFuturesSource().from_payload(payload)

    assert len(identities) == 3
    btc = identities[0]
    assert BinanceUsdMFuturesSource().exchange_info_url.endswith("/fapi/v1/exchangeInfo")
    assert btc.canonical_symbol_id == "BINANCE-USDM-BTC-USDT-PERP"
    assert btc.source == "binance_usdm"
    assert btc.source_symbol == "BTCUSDT"
    assert btc.contract_family == ContractFamily.USD_M.value
    assert btc.contract_type == ContractType.PERPETUAL.value
    assert btc.settlement_asset == "USDT"
    assert btc.legacy_symbol == "BTCUSDT"
    assert btc.metadata["linear"] is True
    assert btc.is_trading()


def test_usdm_non_trading_symbol_is_discovered_but_not_active():
    payload = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/binance_usdm_exchange_info_sample.json").read_text())
    settling = BinanceUsdMFuturesSource().from_payload(payload)[2]

    assert settling.source_symbol == "OLDUSDT"
    assert settling.status == "SETTLING"
    assert not settling.is_trading()


def test_binance_usdm_exchange_info_uses_websocket_cache_before_rest(monkeypatch):
    payload = json.loads(Path("v2/backend/tests/fixtures/symbol_universe/binance_usdm_exchange_info_sample.json").read_text())
    redis_client = RedisLike({"v2:exchange:binance:exchangeInfo": json.dumps(payload)})

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("REST exchangeInfo fallback must not run when cache is present")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    fetched = BinanceUsdMFuturesSource(redis_client=redis_client).fetch_exchange_info()

    assert fetched["symbols"][0]["symbol"] == "BTCUSDT"
    assert fetched["transport"] == "websocket_cache_primary"
    assert fetched["source_key"] == "v2:exchange:binance:exchangeInfo"
    assert fetched["rest_fallback_used"] is False


def test_binance_usdm_exchange_info_blocks_rest_when_cache_missing(monkeypatch):
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)

    with pytest.raises(RuntimeError, match="REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"):
        BinanceUsdMFuturesSource(redis_client=RedisLike({})).fetch_exchange_info()
