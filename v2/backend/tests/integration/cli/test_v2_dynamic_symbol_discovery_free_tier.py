"""Tests for free-tier dynamic symbol discovery.

The worker may call provider APIs in production, but these tests inject a
fake HTTP transport. It must write only V2 keys, expose no raw credentials,
keep execution empty, and publish symbol fields consumed by the Symbol
Universe publisher.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _mod():
    return importlib.import_module(
        "v2.backend.app.cli.v2_dynamic_symbol_discovery_free_tier"
    )


def test_dynamic_discovery_expands_tradable_symbols_and_keeps_execution_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _mod()
    monkeypatch.setenv("COINGECKO_API_KEY", "raw_coingecko_value")
    monkeypatch.setenv("ASKSURF_API_KEY", "raw_surf_value")
    monkeypatch.setenv("COINGLASS_API_KEY", "raw_coinglass_value")

    def fake_http(url: str, _headers: Mapping[str, str], _timeout: float):
        if "exchangeInfo" in url:
            return mod.HttpResult(
                200,
                {
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "quoteAsset": "USDT",
                            "contractType": "PERPETUAL",
                            "status": "TRADING",
                        },
                        {
                            "symbol": "1000BONKUSDT",
                            "quoteAsset": "USDT",
                            "contractType": "PERPETUAL",
                            "status": "TRADING",
                        },
                        {
                            "symbol": "SOLUSDT",
                            "quoteAsset": "USDT",
                            "contractType": "PERPETUAL",
                            "status": "TRADING",
                        },
                    ]
                },
            )
        if "coins/markets" in url:
            return mod.HttpResult(
                200,
                [
                    {
                        "id": "bitcoin",
                        "symbol": "btc",
                        "name": "Bitcoin",
                        "current_price": 70000,
                        "total_volume": 1000000000,
                        "market_cap": 1400000000000,
                        "market_cap_rank": 1,
                        "price_change_percentage_1h_in_currency": 0.5,
                        "price_change_percentage_24h_in_currency": 3.0,
                        "price_change_percentage_7d_in_currency": 9.0,
                    },
                    {
                        "id": "bonk",
                        "symbol": "bonk",
                        "name": "Bonk",
                        "current_price": 0.00002,
                        "total_volume": 700000000,
                        "market_cap": 2000000000,
                        "market_cap_rank": 70,
                        "price_change_percentage_1h_in_currency": 4.0,
                        "price_change_percentage_24h_in_currency": 11.0,
                        "price_change_percentage_7d_in_currency": 18.0,
                    },
                    {
                        "id": "usd-coin",
                        "symbol": "usdc",
                        "name": "USDC",
                        "current_price": 1,
                        "total_volume": 900000000,
                        "market_cap": 40000000000,
                        "market_cap_rank": 6,
                    },
                ],
            )
        if "search/trending" in url:
            return mod.HttpResult(
                200,
                {"coins": [{"item": {"symbol": "BONK"}}, {"item": {"symbol": "BTC"}}]},
            )
        if "asksurf" in url:
            return mod.HttpResult(
                200,
                {
                    "summary": {"first": 1.0, "last": 1.2, "high": 1.25, "low": 0.98},
                    "data": [{"metric": "price", "value": 1.0}, {"metric": "price", "value": 1.2}],
                },
            )
        if "coinglass" in url:
            return mod.HttpResult(200, {"code": "401", "msg": "Upgrade plan"})
        raise AssertionError(url)

    fake_redis = FakeRedis()
    payload = mod.run_once(
        redis_client_override=fake_redis,
        http_get=fake_http,
        max_symbols=10,
        surf_symbol_limit=1,
        public_paths=(tmp_path / "public_a.json", tmp_path / "public_b.json"),
    )

    assert payload["go_no_go"] == "V2_DYNAMIC_SYMBOL_DISCOVERY_FREE_TIER_LIVE_OK"
    assert "BTCUSDT" in payload["dynamic_discovered_symbols"]
    assert "1000BONKUSDT" in payload["dynamic_discovered_symbols"]
    assert "USDCUSDT" not in payload["dynamic_discovered_symbols"]
    assert payload["training_symbols"] == payload["dynamic_discovered_symbols"]
    assert payload["paper_symbols"] == payload["dynamic_discovered_symbols"]
    assert payload["binance_usdm_tradable_symbol_count"] == 3
    assert payload["binance_usdm_tradable_symbols"] == [
        "1000BONKUSDT",
        "BTCUSDT",
        "SOLUSDT",
    ]
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["coinglass_status"]["source_status_counts"] == {
        "API_PLAN_BLOCKED_401_UPGRADE_PLAN": 1
    }

    written_keys = sorted(key for key, _value, _ex in fake_redis.write_log)
    assert "v2:symbol_universe:dynamic_discovery_status" in written_keys
    assert "v2:symbol_universe:dynamic_discovered_symbols" in written_keys
    assert all(key.startswith("v2:") for key in written_keys)
    assert all(not key.startswith(("prediction:", "signals:", "ta:")) for key in written_keys)

    serialized = json.dumps(payload) + json.dumps(fake_redis.store)
    assert "raw_coingecko_value" not in serialized
    assert "raw_surf_value" not in serialized
    assert "raw_coinglass_value" not in serialized
    assert json.loads((tmp_path / "public_a.json").read_text()) == json.loads(
        (tmp_path / "public_b.json").read_text()
    )


def test_safe_redis_set_refuses_non_v2_and_unlisted_keys() -> None:
    mod = _mod()
    fake = FakeRedis()
    assert mod._safe_redis_set(fake, "v2:altdata:coingecko:status", {"ok": True})
    assert mod._safe_redis_set(fake, "v2:altdata:coingecko:symbol:BTCUSDT", {"ok": True})
    assert not mod._safe_redis_set(fake, "ta:BTCUSDT", {"bad": True})
    assert not mod._safe_redis_set(fake, "v2:paper:positions", {"bad": True})
    assert sorted(fake.store) == [
        "v2:altdata:coingecko:status",
        "v2:altdata:coingecko:symbol:BTCUSDT",
    ]


def test_dynamic_discovery_reads_binance_cache_before_exchange_info_http(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _mod()
    monkeypatch.setenv("COINGECKO_API_KEY", "raw_coingecko_value")
    fake_redis = FakeRedis()
    fake_redis.store["v2:exchange:binance:exchangeInfo"] = json.dumps(
        {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                },
                {
                    "symbol": "SOLUSDT",
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                },
            ],
            "source": "binance_usdm_wss_exchange_info_cache",
        }
    )

    def fake_http(url: str, _headers: Mapping[str, str], _timeout: float):
        if "exchangeInfo" in url:
            raise AssertionError("Binance exchangeInfo REST fallback should not run with cache coverage")
        if "coins/markets" in url:
            return mod.HttpResult(
                200,
                [
                    {
                        "id": "bitcoin",
                        "symbol": "btc",
                        "name": "Bitcoin",
                        "current_price": 70000,
                        "total_volume": 1000000000,
                        "market_cap": 1400000000000,
                        "market_cap_rank": 1,
                        "price_change_percentage_1h_in_currency": 0.5,
                    },
                    {
                        "id": "solana",
                        "symbol": "sol",
                        "name": "Solana",
                        "current_price": 180,
                        "total_volume": 600000000,
                        "market_cap": 80000000000,
                        "market_cap_rank": 5,
                        "price_change_percentage_1h_in_currency": 0.4,
                    },
                ],
            )
        if "search/trending" in url:
            return mod.HttpResult(200, {"coins": [{"item": {"symbol": "BTC"}}]})
        if "asksurf" in url:
            return mod.HttpResult(200, {"summary": {}, "data": []})
        if "coinglass" in url:
            return mod.HttpResult(200, {"code": "401", "msg": "Upgrade plan"})
        raise AssertionError(url)

    payload = mod.run_once(
        redis_client_override=fake_redis,
        http_get=fake_http,
        max_symbols=10,
        surf_symbol_limit=0,
        public_paths=(tmp_path / "public_a.json", tmp_path / "public_b.json"),
    )

    assert payload["binance_usdm_status"]["provider"] == "binance_usdm_websocket_cache_primary"
    assert payload["binance_usdm_status"]["network_call_attempted"] is False
    assert payload["binance_usdm_status"]["rest_fallback_used"] is False
    assert payload["binance_usdm_tradable_symbols"] == ["BTCUSDT", "SOLUSDT"]
    assert "BTCUSDT" in payload["dynamic_discovered_symbols"]
