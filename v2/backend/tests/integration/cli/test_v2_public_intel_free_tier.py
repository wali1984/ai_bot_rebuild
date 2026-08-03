"""Tests for the public/free intelligence worker.

The worker may call public APIs in production, but tests inject HTTP fixtures.
It must write only V2 keys, expose no credentials, and keep execution empty.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Mapping

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _mod():
    return importlib.import_module("v2.backend.app.cli.v2_public_intel_free_tier")


def test_public_intel_builds_symbol_payloads_and_keeps_execution_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _mod()
    monkeypatch.setenv("CRYPTOCOMPARE_API_KEY", "dummy-cryptocompare-key")
    monkeypatch.setenv("CRYPTOPANIC_AUTH_TOKEN", "dummy-cryptopanic-token")
    monkeypatch.setattr(mod, "WORKLOG_STATUS", tmp_path / "worklog/status.json")
    monkeypatch.setattr(mod, "WORKLOG_REPORT", tmp_path / "worklog/report.md")
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item>
        <title>Bitcoin rally extends while Aave launches liquidity upgrade</title>
        <description>BTC inflow and AAVE adoption improve market sentiment.</description>
        <link>https://example.test/a</link>
        <pubDate>Thu, 04 Jun 2026 05:00:00 GMT</pubDate>
      </item>
      <item>
        <title>Solana exploit probe pressures SOL</title>
        <description>Security teams watch SOL after a hack report.</description>
        <link>https://example.test/b</link>
        <pubDate>Thu, 04 Jun 2026 05:01:00 GMT</pubDate>
      </item>
    </channel></rss>"""

    def fake_http(url: str, _headers: Mapping[str, str], _timeout: float):
        if "api.llama.fi/protocols" in url:
            return mod.HttpResult(
                200,
                [
                    {
                        "name": "Aave",
                        "slug": "aave",
                        "symbol": "AAVE",
                        "category": "Lending",
                        "chain": "Ethereum",
                        "tvl": 2_500_000_000,
                        "change_1d": 2.5,
                        "change_7d": 8.0,
                    },
                    {
                        "name": "USDC Stablecoin",
                        "slug": "usdc",
                        "symbol": "USDC",
                        "tvl": 40_000_000_000,
                    },
                ],
            )
        if "alternative.me/fng" in url:
            return mod.HttpResult(
                200,
                {
                    "data": [
                        {
                            "value": "72",
                            "value_classification": "Greed",
                            "time_until_update": "3600",
                        }
                    ]
                },
            )
        if "api/mempool" in url:
            return mod.HttpResult(200, {"count": 50_000, "vsize": 120_000_000, "total_fee": 9_000_000})
        if "fees/recommended" in url:
            return mod.HttpResult(200, {"fastestFee": 40, "hourFee": 25, "economyFee": 8})
        if "min-api.cryptocompare.com/data/v2/news" in url:
            return mod.HttpResult(
                200,
                {
                    "Response": "Success",
                    "Data": [
                        {
                            "title": "Bitcoin ETF inflow boosts BTC sentiment",
                            "body": "BTC adoption and inflow remain strong.",
                            "url": "https://example.test/cc",
                            "published_on": 1_717_480_000,
                            "source": "ExampleWire",
                            "categories": "BTC|ETF",
                        }
                    ],
                },
            )
        if "cryptopanic.com/api/free/v1/posts" in url:
            return mod.HttpResult(
                200,
                {
                    "results": [
                        {
                            "title": "AAVE upgrade attracts whale interest",
                            "url": "https://example.test/cp",
                            "published_at": "2026-06-04T05:02:00Z",
                            "currencies": [{"code": "AAVE", "title": "Aave"}],
                            "votes": {"positive": 3, "negative": 0},
                            "source": {"title": "CryptoPanicFixture"},
                        }
                    ]
                },
            )
        if "coindesk" in url or "cointelegraph" in url or "decrypt" in url:
            return mod.HttpResult(200, rss)
        raise AssertionError(url)

    fake_redis = FakeRedis()
    public_a = tmp_path / "public_a/status.json"
    public_b = tmp_path / "public_b/status.json"
    payload = mod.run_once(
        symbols=("AAVEUSDT", "BTCUSDT", "SOLUSDT"),
        redis_client_override=fake_redis,
        http_get=fake_http,
        public_paths=(public_a, public_b),
        max_news_items_per_feed=5,
    )

    assert payload["go_no_go"] == "V2_PUBLIC_INTEL_FREE_TIER_LIVE_OK"
    assert payload["symbol_count"] == 3
    assert payload["successful_symbol_count"] == 3
    assert payload["defillama_status"]["symbol_count"] == 1
    assert payload["news_status"]["symbol_count"] == 3
    assert payload["news_status"]["source_status_by_provider"]["cryptocompare_news"] == "API_OK"
    assert payload["news_status"]["source_status_by_provider"]["cryptopanic_news"] == "API_OK"
    assert payload["json_news_credential_presence"]["CRYPTOCOMPARE_API_KEY"] is True
    assert payload["json_news_credential_presence"]["CRYPTOPANIC_AUTH_TOKEN"] is True
    assert payload["fear_greed_status"]["fear_greed_score"] == 0.72
    assert payload["mempool_status"]["btc_mempool_pressure_score"] is not None
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["raw_credential_value_exposed"] is False
    rendered_payload = json.dumps(payload)
    assert "dummy-cryptocompare-key" not in rendered_payload
    assert "dummy-cryptopanic-token" not in rendered_payload

    aave = json.loads(fake_redis.store["v2:altdata:public_intel:symbol:AAVEUSDT"])
    btc = json.loads(fake_redis.store["v2:altdata:public_intel:symbol:BTCUSDT"])
    sol = json.loads(fake_redis.store["v2:altdata:public_intel:symbol:SOLUSDT"])
    assert aave["defillama_liquidity_score"] is not None
    assert aave["news_attention_score"] is not None
    assert btc["btc_mempool_pressure_score"] is not None
    assert sol["news_sentiment_score"] < 0

    written_keys = sorted(key for key, _value, _ex in fake_redis.write_log)
    assert "v2:altdata:public_intel:global" in written_keys
    assert "v2:altdata:public_intel:status" in written_keys
    assert all(key.startswith("v2:") for key in written_keys)
    assert all(not key.startswith(("prediction:", "signals:", "ta:")) for key in written_keys)
    assert all(
        ex == mod.DEFAULT_REDIS_RETENTION_SECONDS
        for _key, _value, ex in fake_redis.write_log
    )
    assert payload["producer_interval_seconds"] == mod.DEFAULT_INTERVAL_SECONDS
    assert payload["redis_retention_seconds"] == mod.DEFAULT_REDIS_RETENTION_SECONDS
    assert payload["redis_retention_headroom_seconds"] == (
        mod.DEFAULT_REDIS_RETENTION_SECONDS - mod.DEFAULT_INTERVAL_SECONDS
    )
    assert payload[
        "redis_retention_is_storage_availability_not_event_freshness"
    ] is True
    assert json.loads(public_a.read_text()) == json.loads(public_b.read_text())


def test_safe_redis_set_refuses_old_and_unlisted_namespaces() -> None:
    mod = _mod()
    fake = FakeRedis()
    assert mod._safe_redis_set(fake, "v2:altdata:public_intel:status", {"ok": True})
    assert mod._safe_redis_set(fake, "v2:altdata:public_intel:symbol:BTCUSDT", {"ok": True})
    assert not mod._safe_redis_set(fake, "prediction:BTCUSDT", {"bad": True})
    assert not mod._safe_redis_set(fake, "v2:paper:positions", {"bad": True})
    assert sorted(fake.store) == [
        "v2:altdata:public_intel:status",
        "v2:altdata:public_intel:symbol:BTCUSDT",
    ]
