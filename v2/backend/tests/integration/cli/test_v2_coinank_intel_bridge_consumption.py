"""Regression tests for the CoinAnk intel bridge and its downstream consumers.

Locks in the three gap fixes that closed the CoinAnk consumption gaps:

  Gap 1  v2_coinank_intel_bridge mirrors fresh legacy ``features:global_coinank:*``
         and ``latest:coinank:*`` into the V2 namespace (``v2:coinank:*`` /
         ``v2:features:coinank:*``) that every V2 consumer actually reads.
  Gap 2  the alt-data consumer honors CoinAnk's explicit trainer/prediction/paper
         holds, so a source-visible but non-consumable payload remains masked.
  Gap 3  the alt-data symbol-scoring contract exposes the CoinAnk sub-scores
         without mutating the weighted ``altdata_symbol_score`` aggregate.

Read-only against providers; never routes to live; never places an order.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_coinank_intel_bridge as bridge
from v2.backend.app.services.altdata.altdata_confluence_engine import (
    ProviderInput,
    build_confluence,
)
from v2.backend.app.services.altdata.provider_feature_bridge import load_coinank_input
from v2.backend.app.services.alternative_data.symbol_scoring_contract import (
    build_symbol_score_payload,
)


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def scan_iter(self, match: str = "*", count: int = 500):  # noqa: ARG002
        prefix = match[:-1] if match.endswith("*") else match
        for key in sorted(self.store):
            if key.startswith(prefix):
                yield key


def _seed_legacy_coinank(client: FakeRedis, symbol: str, timeframe: str) -> None:
    now_ms = time.time() * 1000.0
    # Global members (fresh).
    for name in bridge.GLOBAL_NAMES:
        client.set(
            f"features:global_coinank:{name}:latest",
            json.dumps({"value": 1.75, "timestamp": now_ms, "n": 42}),
        )
    # Per-symbol families in the legacy layout the extractor understands.
    client.set(
        bridge.LEGACY_LATEST.format(family="funding", symbol=symbol, timeframe=timeframe),
        json.dumps({"data": {"data": [{"fundingRate": 0.001}]}, "ts_ms": now_ms}),
    )
    client.set(
        bridge.LEGACY_LATEST.format(family="long_short", symbol=symbol, timeframe=timeframe),
        json.dumps({"data": {"data": {"longShortRatios": [1.8, 2.1]}}, "ts_ms": now_ms}),
    )
    client.set(
        bridge.LEGACY_LATEST.format(family="open_interest", symbol=symbol, timeframe=timeframe),
        json.dumps({"data": {"data": [{"openInterest": 12_000_000.0}]}, "ts_ms": now_ms}),
    )
    client.set(
        bridge.LEGACY_LATEST.format(family="liquidations", symbol=symbol, timeframe=timeframe),
        json.dumps(
            {"data": {"data": [{"longTurnover": 5000.0, "shortTurnover": 1000.0}]}, "ts_ms": now_ms}
        ),
    )


def test_gap1_bridge_mirrors_legacy_coinank_into_v2_namespace() -> None:
    client = FakeRedis()
    _seed_legacy_coinank(client, "RAVEUSDT", "4h")

    status = bridge.run_once(client)

    assert status["global_present_members"] == len(bridge.GLOBAL_NAMES)
    assert status["global_is_fresh"] is True
    assert status["symbol_intel_written"] == 1
    assert status["feature_payloads_written"] == 1

    # Global snapshot mirrored to the V2 key consumers read.
    snap = json.loads(client.get(bridge.GLOBAL_SNAPSHOT_KEY))
    assert snap["present_member_count"] == len(bridge.GLOBAL_NAMES)
    assert snap["market_regime_context"]["aggregate_long_short_ratio"] == 1.75
    assert snap["routes_to_live"] is False
    assert snap["places_real_order"] is False

    # Per-symbol feature payload with derived sub-score.
    feat = json.loads(client.get(bridge.FEATURE_KEY.format(symbol="RAVEUSDT", timeframe="4h")))
    assert feat["actual_payload_present"] is True
    assert feat["features"]["coinank_funding_rate"] == 0.001
    assert feat["features"]["coinank_long_short_ratio"] == 2.1
    assert feat["features"]["coinank_liquidation_imbalance_usd"] == 4000.0
    assert feat["coinank_derivatives_score"] is not None

    # Bridge only ever writes v2: keys; the legacy keys are untouched.
    assert all(k.startswith("v2:") for k in client.store if "coinank" in k and ":latest" in k and k.startswith("v2:"))
    assert client.get("features:global_coinank:total_oi:latest") is not None


def test_gap2_confluence_honors_coinank_consumption_hold() -> None:
    client = FakeRedis()
    _seed_legacy_coinank(client, "RAVEUSDT", "4h")
    bridge.run_once(client)

    coinank = load_coinank_input(client, "RAVEUSDT", "4h")
    assert coinank.present is False
    assert coinank.stale is False

    payload = build_confluence(
        symbol="RAVEUSDT",
        timeframe="4h",
        coinglass=ProviderInput(provider="coinglass", present=False),
        moralis=ProviderInput(provider="moralis", present=False),
        coinank=coinank,
        generated_utc="2026-07-14T21:15:00Z",
    )

    assert payload["providers_present"] == []
    assert payload["actual_payload_present"] is False
    assert payload["heartbeat_only"] is True
    assert payload["decision_time_safe"] is False
    feats = payload["features"]
    assert feats["altdata_derivatives_pressure_score"] is None
    assert feats["altdata_liquidation_sweep_risk_score"] is None
    assert payload["single_provider_can_approve"] is False
    assert payload["raw_key_exposed"] is False
    assert "STANDALONE_APPROVE" in payload["forbidden_actions"]


def _score(symbol: str, feature_payloads: dict[str, Any]) -> dict[str, Any]:
    return build_symbol_score_payload(
        symbol,
        coingecko_payload=None,
        surf_payload=None,
        coinglass_payload=None,
        public_intel_payload=None,
        whale_walls_payload=None,
        market_payloads={},
        feature_payloads=feature_payloads,
        generated_utc="2026-07-14T21:15:00Z",
    )


def test_gap3_symbol_score_exposes_coinank_without_changing_aggregate() -> None:
    client = FakeRedis()
    _seed_legacy_coinank(client, "RAVEUSDT", "4h")
    bridge.run_once(client)
    coinank_feature = json.loads(
        client.get(bridge.FEATURE_KEY.format(symbol="RAVEUSDT", timeframe="4h"))
    )

    baseline = _score("RAVEUSDT", {"latest": None})
    with_coinank = _score("RAVEUSDT", {"latest": None, "coinank": coinank_feature})

    # Additive exposure of the CoinAnk sub-scores.
    assert with_coinank["coinank_signal_present"] is True
    assert with_coinank["coinank_derivatives_score"] is not None
    assert with_coinank["coinank_long_short_ratio"] == 2.1
    assert with_coinank["coinank_liquidation_imbalance_usd"] == 4000.0
    assert with_coinank["input_presence"]["coinank_feature_bridge"] is True
    assert set(with_coinank["coinank_feature_bridge"]) >= {
        "provider",
        "coinank_derivatives_score",
        "coinank_funding_rate",
        "coinank_long_short_ratio",
        "coinank_liquidation_imbalance_usd",
    }

    # The weighted aggregate must be unchanged: CoinAnk is exposed, not folded in.
    assert with_coinank["altdata_symbol_score"] == baseline["altdata_symbol_score"]
    assert baseline["coinank_signal_present"] is False


def test_bridge_never_writes_legacy_keys() -> None:
    client = FakeRedis()
    _seed_legacy_coinank(client, "RAVEUSDT", "4h")
    before = set(client.store)
    bridge.run_once(client)
    new_keys = set(client.store) - before
    assert new_keys, "bridge should have written V2 keys"
    assert all(k.startswith("v2:") for k in new_keys)
