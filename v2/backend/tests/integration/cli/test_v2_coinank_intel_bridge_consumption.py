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

import importlib.util
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

    def hgetall(self, key: str) -> dict[str, str]:  # noqa: ARG002
        return {}

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = int(seconds)
        return True


def _load_legacy_global_aggregator():
    source_path = REPO_ROOT / "v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py"
    spec = importlib.util.spec_from_file_location("coinank_global_aggregator_test", source_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_legacy_coinank(client: FakeRedis, symbol: str, timeframe: str) -> None:
    now_ms = time.time() * 1000.0
    interval_ms = bridge.TIMEFRAME_SECONDS[timeframe] * 1000
    closed_open_ms = now_ms - interval_ms - 1_000
    # Global members (fresh).
    global_values = {
        "total_oi": 12_000_000.0,
        "total_volume": 2_000_000.0,
        "total_liquidations": 10_000.0,
        "long_short_ratio": 1.75,
        "funding_rate_avg": 0.0001,
        "btc_dominance": 55.0,
        "eth_dominance": 20.0,
        "alt_season_index": 42.0,
        "fear_greed": 60.0,
        "market_sentiment": 0.25,
        "volatility_index": 15.0,
    }
    global_units = {
        "total_volume": "usd",
        "total_liquidations": "usd",
        "long_short_ratio": "ratio",
        "funding_rate_avg": "fraction_per_funding_interval",
        "market_sentiment": "ratio_minus1_to_plus1",
    }
    for name in bridge.GLOBAL_NAMES:
        supported = name in bridge.SUPPORTED_GLOBAL_NAMES
        metadata = {
            "schema_version": "coinank_global_aggregate_v2",
            "supported": supported,
            "aggregate_valid": supported,
            "valid": supported,
            "temporal_contract_valid": supported,
            "n": 42 if supported else 0,
            "universe_n": 42,
            "coverage_ratio": 1.0 if supported else 0.0,
            "unit": global_units.get(name, "unsupported"),
            "available_at_ms": now_ms - 1_000,
            "feature_cutoff_ms": now_ms - 2_000,
            "generated_at_ms": now_ms,
            "aggregation_timeframe": timeframe,
            "aggregation_window_feature_cutoff_ms": now_ms - 2_000,
        }
        if name == "long_short_ratio":
            metadata.update({
                "source_endpoint": "ls_global_account_ratio",
                "semantic": "global_account_ratio",
            })
        client.set(
            f"features:global_coinank:{name}:latest",
            json.dumps({"value": global_values[name] if supported else None, **metadata}),
        )
    # Collision-prone generic family mirror deliberately points at a sibling
    # endpoint; the bridge must prefer the exact endpoint mirror below.
    client.set(
        bridge.LEGACY_LATEST.format(
            family="funding", symbol=symbol, timeframe=timeframe
        ),
        json.dumps({
            "data": {"data": [{"fundingRate": 99.0, "ts": closed_open_ms}]},
            "endpoint": "fundingRate_indicator",
            "ts_ms": now_ms,
        }),
    )
    # Per-symbol families in the legacy layout the extractor understands.
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="fundingRate_kline", symbol=symbol, timeframe=timeframe
        ),
        json.dumps({
            "data": {"data": [{"close": 0.1, "begin": closed_open_ms}]},
            "endpoint": "fundingRate_kline",
            "ts_ms": now_ms,
        }),
    )
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="ls_global_account_ratio", symbol=symbol, timeframe=timeframe
        ),
        json.dumps({
            "data": {"data": {
                "tss": [closed_open_ms - interval_ms, closed_open_ms],
                "longShortRatio": [1.8, 2.1],
            }},
            "endpoint": "ls_global_account_ratio",
            "ts_ms": now_ms,
        }),
    )
    for index, variant in enumerate(bridge.LONG_SHORT_VARIANTS, start=1):
        client.set(
            bridge.ENDPOINT_VARIANT_LATEST.format(
                endpoint="ls_kline",
                variant=variant,
                symbol=symbol,
                timeframe=timeframe,
            ),
            json.dumps({
                "data": {"data": [{
                    "begin": closed_open_ms,
                    "close": 3.0 + index,
                }]},
                "endpoint": "ls_kline",
                "endpoint_variant": variant,
                "request_parameters": {"type": variant},
                "ts_ms": now_ms,
            }),
        )
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="openInterest_kline", symbol=symbol, timeframe=timeframe
        ),
        json.dumps({
            "data": {"data": [{"begin": closed_open_ms, "openInterest": 12_000_000.0}]},
            "endpoint": "openInterest_kline",
            "ts_ms": now_ms,
        }),
    )
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="liquidation_history", symbol=symbol, timeframe=timeframe
        ),
        json.dumps(
            {
                "data": {"data": [{
                    "ts": closed_open_ms,
                    "longTurnover": 5000.0,
                    "shortTurnover": 1000.0,
                }]},
                "endpoint": "liquidation_history",
                "ts_ms": now_ms,
            }
        ),
    )


def test_gap1_bridge_mirrors_legacy_coinank_into_v2_namespace() -> None:
    client = FakeRedis()
    _seed_legacy_coinank(client, "RAVEUSDT", "4h")

    status = bridge.run_once(client)

    assert status["global_present_members"] == len(bridge.SUPPORTED_GLOBAL_NAMES)
    assert status["global_is_fresh"] is True
    assert status["symbol_intel_written"] == 1
    assert status["feature_payloads_written"] == 1

    # Global snapshot mirrored to the V2 key consumers read.
    snap = json.loads(client.get(bridge.GLOBAL_SNAPSHOT_KEY))
    assert snap["present_member_count"] == len(bridge.SUPPORTED_GLOBAL_NAMES)
    assert snap["market_regime_context"]["aggregate_long_short_ratio"] == 1.75
    assert snap["routes_to_live"] is False
    assert snap["places_real_order"] is False

    # Per-symbol feature payload with derived sub-score.
    feat = json.loads(client.get(bridge.FEATURE_KEY.format(symbol="RAVEUSDT", timeframe="4h")))
    assert feat["actual_payload_present"] is True
    assert feat["features"]["coinank_funding_rate"] == 0.001
    assert feat["features"]["coinank_funding_rate_raw_percent_points"] == 0.1
    assert feat["feature_units"]["coinank_funding_rate"] == (
        "fraction_per_provider_funding_interval_duration_unknown"
    )
    assert feat["feature_provenance"]["coinank_funding_rate"][
        "funding_interval_duration_known"
    ] is False
    assert feat["features"]["coinank_long_short_ratio"] == 2.1
    assert feat["features"]["coinank_global_account_long_short_ratio"] == 2.1
    assert feat["features"]["coinank_global_account_long_short_ratio_kline"] == 4.0
    assert feat["features"]["coinank_top_trader_position_long_short_ratio_kline"] == 5.0
    assert feat["features"]["coinank_top_trader_account_long_short_ratio_kline"] == 6.0
    assert feat["feature_provenance"]["coinank_long_short_ratio"]["endpoint"] == "ls_global_account_ratio"
    assert feat["features"]["coinank_liquidation_imbalance_usd"] == 4000.0
    assert feat["coinank_derivatives_score"] is not None
    assert feat["feature_cutoff"] <= feat["available_at"]
    assert feat["temporal_contract_valid"] is True
    assert feat["trainer_consumable"] is False

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


def test_coinank_consolidated_fallback_cannot_cross_timeframes() -> None:
    client = FakeRedis()
    now_iso = bridge._utc_iso()
    client.set(
        "v2:coinank:symbol:RAVEUSDT",
        json.dumps({
            "actual_payload_present": True,
            "feature_eligible": True,
            "temporal_contract_valid": True,
            "symbol": "RAVEUSDT",
            "timeframe": "1d",
            "available_at": now_iso,
            "feature_cutoff": now_iso,
            "features": {"coinank_long_short_ratio": 2.0},
        }),
    )

    loaded = load_coinank_input(client, "RAVEUSDT", "1m")

    assert loaded.present is False


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


def test_bridge_rejects_duplicate_quote_and_null_only_payloads() -> None:
    client = FakeRedis()
    now_ms = time.time() * 1000.0
    client.set(
        "latest:coinank:open_interest:1000FLOKIUSDTUSDT:1m",
        json.dumps({"data": {"data": []}, "ts_ms": now_ms}),
    )
    client.set(
        "latest:coinank:open_interest:NULLUSDT:1m",
        json.dumps({
            "data": {"data": [{"begin": now_ms - 120_000, "openInterest": None}]},
            "ts_ms": now_ms,
        }),
    )

    status = bridge.run_once(client)

    assert status["symbols_discovered"] == 1
    assert status["symbol_intel_written"] == 0
    assert status["feature_payloads_written"] == 0
    assert client.get("v2:features:coinank:1000FLOKIUSDTUSDT:1m") is None
    assert client.get("v2:features:coinank:NULLUSDT:1m") is None


def test_bridge_uses_latest_closed_coinank_bar_and_conservative_source_age() -> None:
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    minute_ms = 60_000
    closed_open = now_ms - (2 * minute_ms)
    older_closed_open = now_ms - (10 * minute_ms)
    open_bar = now_ms - 10_000
    client.set(
        bridge.LEGACY_LATEST.format(family="funding", symbol="TESTUSDT", timeframe="1m"),
        json.dumps({
            "data": {"data": [
                {"close": 0.1, "begin": closed_open},
                {"close": 9.9, "begin": open_bar},
            ]},
            "endpoint": "fundingRate_kline",
            "ts_ms": now_ms - 10_000,
        }),
    )
    client.set(
        bridge.LEGACY_LATEST.format(
            family="open_interest", symbol="TESTUSDT", timeframe="1m"
        ),
        json.dumps({
            "data": {"data": [{"begin": older_closed_open, "close": 1234.0}]},
            "endpoint": "openInterest_kline",
            "ts_ms": now_ms - 500_000,
        }),
    )

    payload = bridge._extract_symbol_features(client, "TESTUSDT", "1m")

    assert payload is not None
    assert payload["features"]["coinank_funding_rate"] == 0.001
    assert payload["features"]["coinank_funding_rate_raw_percent_points"] == 0.1
    assert 499 <= payload["source_freshness_seconds"] <= 502
    assert payload["feature_cutoff"] <= payload["available_at"]


def test_unclocked_coinank_family_cannot_leak_through_another_valid_family() -> None:
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    closed_open = now_ms - 120_000
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="fundingRate_kline", symbol="TESTUSDT", timeframe="1m"
        ),
        json.dumps({
            "endpoint": "fundingRate_kline",
            "ts_ms": now_ms,
            "data": {"data": [{"begin": closed_open, "close": 0.1}]},
        }),
    )
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="openInterest_kline", symbol="TESTUSDT", timeframe="1m"
        ),
        json.dumps({
            "endpoint": "openInterest_kline",
            "ts_ms": now_ms,
            "data": {"data": [{"close": 999_999_999.0}]},
        }),
    )

    payload = bridge._extract_symbol_features(client, "TESTUSDT", "1m")

    assert payload is not None
    assert payload["features"]["coinank_funding_rate"] == 0.001
    assert "coinank_open_interest" not in payload["features"]
    assert payload["family_names_present"] == ["funding"]


def test_ambiguous_ls_kline_cannot_populate_generic_long_short_alias() -> None:
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    closed_open = now_ms - 120_000
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="ls_kline", symbol="TESTUSDT", timeframe="1m"
        ),
        json.dumps({
            "endpoint": "ls_kline",
            "ts_ms": now_ms,
            "data": {"data": [{"begin": closed_open, "close": 99.0}]},
        }),
    )
    client.set(
        bridge.ENDPOINT_VARIANT_LATEST.format(
            endpoint="ls_kline",
            variant="longShortPosition",
            symbol="TESTUSDT",
            timeframe="1m",
        ),
        json.dumps({
            "endpoint": "ls_kline",
            "endpoint_variant": "longShortPosition",
            "request_parameters": {"type": "longShortPosition"},
            "ts_ms": now_ms,
            "data": {"data": [{"begin": closed_open, "close": 1.7}]},
        }),
    )

    payload = bridge._extract_symbol_features(client, "TESTUSDT", "1m")

    assert payload is not None
    assert "coinank_long_short_ratio" not in payload["features"]
    assert payload["features"][
        "coinank_top_trader_position_long_short_ratio_kline"
    ] == 1.7


def test_fresh_receipt_cannot_relabel_an_old_coinank_bar_as_fresh() -> None:
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    old_open = now_ms - (60 * 60 * 1000)
    client.set(
        bridge.ENDPOINT_LATEST.format(
            endpoint="ls_global_account_ratio",
            symbol="TESTUSDT",
            timeframe="5m",
        ),
        json.dumps({
            "endpoint": "ls_global_account_ratio",
            "ts_ms": now_ms,
            "data": {"data": {
                "tss": [old_open],
                "longShortRatio": [1.5],
            }},
        }),
    )

    payload = bridge._extract_symbol_features(client, "TESTUSDT", "5m")

    assert payload is None


def test_global_bridge_rejects_legacy_payload_without_strict_schema() -> None:
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    for name in bridge.SUPPORTED_GLOBAL_NAMES:
        client.set(
            f"features:global_coinank:{name}:latest",
            json.dumps({"value": 1.0, "timestamp": now_ms}),
        )

    snapshot = bridge.build_global_snapshot(client)

    assert snapshot["present_member_count"] == 0
    assert snapshot["coverage_complete"] is False
    assert snapshot["is_fresh"] is False


def test_global_bridge_rejects_future_generated_clock() -> None:
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    client.set(
        "features:global_coinank:total_volume:latest",
        json.dumps({
            "schema_version": "coinank_global_aggregate_v2",
            "value": 100.0,
            "valid": True,
            "supported": True,
            "aggregate_valid": True,
            "temporal_contract_valid": True,
            "n": 1,
            "universe_n": 1,
            "coverage_ratio": 1.0,
            "unit": "usd",
            "feature_cutoff_ms": now_ms - 2_000,
            "available_at_ms": now_ms - 1_000,
            "generated_at_ms": now_ms + 60_000,
            "aggregation_timeframe": "1m",
            "aggregation_window_feature_cutoff_ms": now_ms - 2_000,
        }),
    )

    snapshot = bridge.build_global_snapshot(client)

    assert snapshot["present_member_count"] == 0
    assert snapshot["members"]["total_volume"]["valid"] is False


def test_legacy_coinank_flat_mirror_canonicalizes_an_already_quoted_symbol() -> None:
    source_path = REPO_ROOT / "v2/legacy_owned_runtime/ingest/live_coinank.py"
    source = source_path.read_text()
    assert 'sym_for_key = f"{base_coin}USDT"' not in source
    assert "flat_sym = _canonical_usdt(str(base_coin))" in source
    assert "canonical = list(dict.fromkeys(" in source
    assert "return canonical_usdt_symbol(sym)" in source
    assert "CANONICAL_COINANK_ENDPOINT_BY_FAMILY.get(family) == key" in source
    assert '"funding": "fundingRate_kline"' in source
    assert '"attempt_budget_satisfied": attempt_budget_satisfied' in source
    assert '"capacity_satisfies_sla": effective_capacity' in source
    assert 'effective_scheduler_plan = select_parameter_batch(' in source
    assert 'select_due_critical_endpoint(' in source
    assert "if cand_key in CRITICAL_COINANK_SCHEDULER_ENDPOINTS:" in source
    assert "minimum_visit_interval_seconds=_endpoint_min_interval" in source
    assert "endpoint_interval_seconds=scheduler_visit_interval_seconds" in source
    assert "derive_critical_spend_budget_seconds(" in source
    assert "COINANK_CRITICAL_REQUEST_BUDGET_SECONDS" in source
    assert 'COINANK_CRITICAL_LIVE_ROW_LIMIT", "3"' in source
    assert "and scheduler_cadence_observed" in source
    assert '"cadence_observed": scheduler_cadence_observed' in source
    assert "if provider_no_data or semantic_invalid:" in source
    assert source.index("semantic_invalid = bool(") < source.index(
        "persist(key, p, data, r, message_counters)"
    )
    assert '"semantic_invalid_this_tick"' in source
    assert source.count('flat_key = f"latest:coinank:{family}:') == 1
    assert 'f"latest:coinank_endpoint:{ep_identity}' in source
    assert "return str(aligned_current_end_time_ms(_now_ms(), interval))" in source
    assert "safe_end_time_ms = now_ms - (60 * 60 * 1000)" not in source


def test_global_aggregator_uses_only_closed_endpoint_specific_coinank_values() -> None:
    aggregator = _load_legacy_global_aggregator()
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    hour_ms = 3_600_000
    closed_open = now_ms - (2 * hour_ms)
    unfinished_open = now_ms - 60_000

    def seed_endpoint(endpoint: str, rows: list[Any]) -> None:
        client.set(
            f"latest:coinank_endpoint:{endpoint}:BTCUSDT:1h",
            json.dumps({
                "endpoint": endpoint,
                "ts_ms": now_ms,
                "data": {"data": rows},
            }),
        )

    seed_endpoint(
        "openInterest_kline",
        [
            {"begin": closed_open, "close": 100.0},
            {"begin": unfinished_open, "close": 999_999.0},
        ],
    )
    seed_endpoint(
        "fundingRate_kline",
        [
            {"begin": closed_open, "close": 0.1},
            {"begin": unfinished_open, "close": 99.0},
        ],
    )
    client.set(
        "latest:coinank_endpoint:ls_global_account_ratio:BTCUSDT:1h",
        json.dumps({
            "endpoint": "ls_global_account_ratio",
            "ts_ms": now_ms,
            "data": {"data": {
                "tss": [closed_open],
                "longShortRatio": [1.5],
            }},
        }),
    )
    seed_endpoint(
        "liquidation_history",
        [{"ts": closed_open, "longTurnover": 20.0, "shortTurnover": 10.0}],
    )
    seed_endpoint(
        "marketOrder_getBuySellValue",
        [
            [closed_open, 100.0, 50.0],
            [unfinished_open, -1e12, 1e20],
        ],
    )
    # A collided generic mirror must not contaminate the endpoint-specific lane.
    client.set(
        "latest:coinank:market_order_flow:BTCUSDT:1h",
        json.dumps({
            "endpoint": "marketOrder_getCvd",
            "ts_ms": now_ms,
            "data": {"data": [[closed_open, -1e12, 1e20]]},
        }),
    )

    stats = aggregator.compute_and_persist(client, ["BTCUSDT"], tf="1h", ttl_sec=300)

    assert stats["total_volume"] == 150.0
    assert stats["market_sentiment"] == 1 / 3
    assert stats["funding_rate_avg"] is None
    assert stats["long_short_ratio"] == 1.5
    volume = json.loads(client.get("features:global_coinank:total_volume:latest"))
    sentiment = json.loads(client.get("features:global_coinank:market_sentiment:latest"))
    total_oi = json.loads(client.get("features:global_coinank:total_oi:latest"))
    fear_greed = json.loads(client.get("features:global_coinank:fear_greed:latest"))
    funding = json.loads(client.get("features:global_coinank:funding_rate_avg:latest"))
    assert volume["value"] == 150.0
    assert volume["coverage_ratio"] == 1.0
    assert volume["feature_cutoff_ms"] <= volume["available_at_ms"] <= volume["generated_at_ms"]
    assert volume["ts_ms"] == volume["available_at_ms"]
    assert sentiment["value"] == 1 / 3
    assert -1 <= sentiment["value"] <= 1
    assert total_oi["value"] is None
    assert total_oi["invalid_reason"] == "CROSS_SYMBOL_OPEN_INTEREST_UNIT_NOT_PROVEN"
    assert funding["value"] is None
    assert funding["invalid_reason"] == "CROSS_SYMBOL_FUNDING_INTERVAL_NOT_PROVEN"
    assert fear_greed["value"] is None
    assert fear_greed["invalid_reason"] == "COINANK_ENDPOINT_NOT_CONFIGURED_FOR_AGGREGATE"


def test_global_aggregator_cannot_refresh_a_stale_source_receipt() -> None:
    aggregator = _load_legacy_global_aggregator()
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    source_available_ms = now_ms - aggregator.MAX_SOURCE_RECEIPT_AGE_MS - 1_000
    closed_open = source_available_ms - 60_000
    client.set(
        "latest:coinank_endpoint:marketOrder_getBuySellValue:BTCUSDT:1m",
        json.dumps({
            "endpoint": "marketOrder_getBuySellValue",
            "ts_ms": source_available_ms,
            "data": {"data": [[closed_open, 100.0, 50.0]]},
        }),
    )

    aggregator.compute_and_persist(client, ["BTCUSDT"], tf="1m", ttl_sec=300)

    volume = json.loads(client.get("features:global_coinank:total_volume:latest"))
    assert volume["value"] is None
    assert volume["valid"] is False
    assert volume["coverage_ratio"] == 0.0
    assert volume["ts_ms"] is None


def test_global_aggregator_holds_numeric_value_below_minimum_coverage() -> None:
    aggregator = _load_legacy_global_aggregator()
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    closed_open = now_ms - 60_000
    client.set(
        "latest:coinank_endpoint:marketOrder_getBuySellValue:BTCUSDT:1m",
        json.dumps({
            "endpoint": "marketOrder_getBuySellValue",
            "ts_ms": now_ms,
            "data": {"data": [[closed_open, 100.0, 50.0]]},
        }),
    )

    aggregator.compute_and_persist(
        client,
        ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        tf="1m",
        ttl_sec=300,
    )

    volume = json.loads(client.get("features:global_coinank:total_volume:latest"))
    assert volume["coverage_ratio"] == 1 / 3
    assert volume["aggregate_valid"] is False
    assert volume["valid"] is False
    assert volume["value"] is None


def test_global_aggregator_never_combines_adjacent_cutoff_buckets() -> None:
    aggregator = _load_legacy_global_aggregator()
    client = FakeRedis()
    now_ms = int(time.time() * 1000)
    newest_open = now_ms - 60_000
    older_open = now_ms - 120_000
    rows = {
        "BTCUSDT": (newest_open, 100.0, 50.0),
        "ETHUSDT": (newest_open, 100.0, 50.0),
        "SOLUSDT": (older_open, 1_000.0, 500.0),
        "ADAUSDT": (older_open, 1_000.0, 500.0),
    }
    for symbol, (open_ms, buy, sell) in rows.items():
        client.set(
            f"latest:coinank_endpoint:marketOrder_getBuySellValue:{symbol}:1m",
            json.dumps({
                "endpoint": "marketOrder_getBuySellValue",
                "ts_ms": now_ms,
                "data": {"data": [[open_ms, buy, sell]]},
            }),
        )

    aggregator.compute_and_persist(
        client,
        list(rows),
        tf="1m",
        ttl_sec=300,
    )

    volume = json.loads(client.get("features:global_coinank:total_volume:latest"))
    assert volume["value"] == 300.0
    assert volume["n"] == 2
    assert volume["coverage_ratio"] == 0.5
    assert volume["aggregation_window_feature_cutoff_ms"] == now_ms
    assert volume["source_observation_count"] == 2
