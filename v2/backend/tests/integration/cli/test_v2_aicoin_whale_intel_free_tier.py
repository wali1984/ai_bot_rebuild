"""Tests for the V2 AICoin + whale-wall free-tier intelligence worker."""
from __future__ import annotations

import importlib
import json
from pathlib import Path


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _mod():
    return importlib.import_module("v2.backend.app.cli.v2_aicoin_whale_intel_free_tier")


def test_worker_derives_whale_walls_and_keeps_aicoin_missing_state_visible(
    tmp_path: Path,
) -> None:
    mod = _mod()
    fake = FakeRedis()
    fake.store["v2:market:orderbook:BTCUSDT"] = json.dumps(
        {
            "bids": [
                ["100.00", "1200"],
                ["99.90", "10"],
                ["99.80", "10"],
            ],
            "asks": [
                ["100.10", "2"],
                ["100.20", "2"],
                ["100.30", "2"],
            ],
        }
    )
    fake.store["v2:market:orderbook:ETHUSDT"] = json.dumps(
        {
            "bids": [["50.00", "1"], ["49.90", "1"]],
            "asks": [["50.10", "3000"], ["50.20", "1"]],
        }
    )
    public_path = tmp_path / "operator_runtime/status.json"
    payload = mod.run_once(
        symbols=("BTCUSDT", "ETHUSDT"),
        redis_client_override=fake,
        public_paths=(public_path,),
        min_notional_usd=1_000.0,
        min_base_quantity=1.0,
        env={},
    )

    assert payload["go_no_go"] == "V2_AICOIN_WHALE_INTEL_FREE_TIER_LIVE_OK"
    assert payload["symbol_count"] == 2
    assert payload["whale_walls_status"]["successful_symbol_count"] == 2
    assert payload["aicoin_status"]["source_status"] == "KEY_MISSING_NO_NETWORK"
    assert payload["aicoin_status"]["network_call_attempted"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["raw_credential_value_exposed"] is False

    btc = json.loads(fake.store["v2:altdata:whale_walls:symbol:BTCUSDT"])
    eth = json.loads(fake.store["v2:altdata:whale_walls:symbol:ETHUSDT"])
    assert btc["source_status"] == "DERIVED_OK"
    assert btc["whale_wall_score"] > 0.5
    assert eth["whale_wall_score"] < 0.5
    assert btc["network_call_attempted"] is False

    aicoin_btc = json.loads(fake.store["v2:altdata:aicoin:symbol:BTCUSDT"])
    assert aicoin_btc["source_status"] == "KEY_MISSING_NO_NETWORK"
    assert aicoin_btc["aicoin_order_flow_score"] is None
    assert aicoin_btc["credential_raw_value_exposed"] is False
    assert json.loads(public_path.read_text())["symbol_count"] == 2

    for key, _value, _ex in fake.write_log:
        assert key.startswith("v2:altdata:aicoin:") or key.startswith(
            "v2:altdata:whale_walls:"
        )
        assert not key.startswith(("prediction:", "signals:", "ta:", "paper:"))


def test_safe_redis_set_refuses_old_and_unlisted_namespaces() -> None:
    mod = _mod()
    fake = FakeRedis()
    assert mod._safe_redis_set(fake, "v2:altdata:aicoin:status", {"ok": True})
    assert mod._safe_redis_set(fake, "v2:altdata:whale_walls:symbol:BTCUSDT", {"ok": True})
    assert not mod._safe_redis_set(fake, "v2:paper:positions", {"bad": True})
    assert not mod._safe_redis_set(fake, "prediction:BTCUSDT", {"bad": True})
    assert sorted(fake.store) == [
        "v2:altdata:aicoin:status",
        "v2:altdata:whale_walls:symbol:BTCUSDT",
    ]
