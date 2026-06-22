"""Tests for the V2-native liquidation observation aggregator.

Paper-only. No torch import. No legacy filesystem mutation. No
silent zero-fill.
"""
from __future__ import annotations

import importlib
import sys


def _agg():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.liquidation_observation_aggregator"
    )


def _sample_features() -> dict:
    return {"last_liq_bps_24h": 17.0}


def _sample_coinank_intel() -> dict:
    return {
        "schema_version": "v2_coinank_market_intelligence_status_v1",
        "freshness_seconds": 35.5,
        "liquidations_persisted_total": 0,
        "global_aggregate_result": {
            "total_liquidations": 0.0,
        },
    }


def test_subfamily_returns_12_slots_named_per_legacy_target() -> None:
    mod = _agg()
    rows = mod.build_liquidation_subfamily(
        symbol="BTCUSDT",
        v2_features=_sample_features(),
        coinank_intel=_sample_coinank_intel(),
    )
    assert len(rows) == 12
    names = [r[0] for r in rows]
    assert names[0].endswith(".latest_liquidation_notional")
    assert names[3].endswith(".last_liq_bps_24h")
    assert names[11].endswith(".v2_liquidation_source_available")


def test_v2_features_present_paths_are_filled() -> None:
    mod = _agg()
    rows = mod.build_liquidation_subfamily(
        symbol="BTCUSDT",
        v2_features=_sample_features(),
        coinank_intel=_sample_coinank_intel(),
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    val, src = by_name["liquidations.last_liq_bps_24h"]
    assert val == 17.0
    assert src == "V2_NATIVE_FEATURE_SNAPSHOT"
    val, src = by_name["liquidations.last_liq_bps_24h_abs"]
    assert val == 17.0
    assert src == "V2_DERIVED_FROM_FEATURES"
    val, src = by_name["liquidations.last_liq_direction"]
    assert val == 1.0
    val, src = by_name["liquidations.liquidation_direction_bias"]
    assert val == 1.0
    val, src = by_name["liquidations.liquidation_notional_24h_proxy"]
    assert val == 17.0


def test_coinank_global_aggregate_surfaced_with_explicit_label() -> None:
    mod = _agg()
    rows = mod.build_liquidation_subfamily(
        symbol="BTCUSDT",
        v2_features=_sample_features(),
        coinank_intel=_sample_coinank_intel(),
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    val, src = by_name["liquidations.liquidation_count_proxy_global"]
    assert val == 0.0
    assert src == "V2_COINANK_GLOBAL_AGGREGATE_NOT_PER_SYMBOL"
    val, src = by_name["liquidations.liquidation_freshness_seconds"]
    assert val == 35.5
    assert src == "V2_COINANK_MARKET_INTELLIGENCE"


def test_per_symbol_aggregator_source_flag_is_zero() -> None:
    mod = _agg()
    rows = mod.build_liquidation_subfamily(
        symbol="BTCUSDT",
        v2_features=_sample_features(),
        coinank_intel=_sample_coinank_intel(),
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    val, src = by_name["liquidations.v2_liquidation_source_available"]
    assert val == 0.0
    assert src == "V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT"


def test_missing_when_no_inputs() -> None:
    mod = _agg()
    rows = mod.build_liquidation_subfamily(
        symbol="BTCUSDT", v2_features=None, coinank_intel=None
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    # Only the always-present probe flag survives.
    flag = by_name["liquidations.v2_liquidation_source_available"]
    assert flag == (0.0, "V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT")
    # last_liq, abs, direction, count, notional, bias, freshness all missing.
    for nm in (
        "liquidations.last_liq_bps_24h",
        "liquidations.last_liq_bps_24h_abs",
        "liquidations.last_liq_direction",
        "liquidations.liquidation_count_proxy_global",
        "liquidations.liquidation_notional_24h_proxy",
        "liquidations.liquidation_direction_bias",
        "liquidations.liquidation_freshness_seconds",
    ):
        val, src = by_name[nm]
        assert val is None
        assert src == "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"


def test_per_symbol_v2_liquidation_snapshot_fills_four_gap_fields() -> None:
    mod = _agg()
    rows = mod.build_liquidation_subfamily(
        symbol="BTCUSDT",
        v2_features=_sample_features(),
        coinank_intel=_sample_coinank_intel(),
        v2_liquidation_per_symbol={
            "latest": {"notional": 1234.5, "side": "long"},
            "aggregate": {"notional_1h": 9876.5},
            "any_populated": True,
            "v2_per_symbol_aggregator_present": True,
        },
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    assert by_name["liquidations.latest_liquidation_notional"] == (
        1234.5,
        "V2_MARKET_LIQUIDATIONS_LATEST",
    )
    assert by_name["liquidations.latest_liquidation_side_long"] == (
        1.0,
        "V2_MARKET_LIQUIDATIONS_LATEST",
    )
    assert by_name["liquidations.latest_liquidation_side_short"] == (
        0.0,
        "V2_MARKET_LIQUIDATIONS_LATEST",
    )
    assert by_name["liquidations.liquidation_notional_1h_proxy"] == (
        9876.5,
        "V2_MARKET_LIQUIDATIONS_AGGREGATE",
    )
    assert by_name["liquidations.v2_liquidation_source_available"] == (
        1.0,
        "V2_MARKET_LIQUIDATIONS_PER_SYMBOL_PRESENT",
    )


def test_read_v2_liquidation_per_symbol_from_reuses_existing_client() -> None:
    mod = _agg()

    class FakeRedis:
        def __init__(self) -> None:
            self.keys_read: list[str] = []

        def get(self, key: str) -> str | None:
            self.keys_read.append(key)
            if key.endswith(":latest:BTCUSDT"):
                return '{"notional": 12.5, "side": "short"}'
            if key.endswith(":aggregate:BTCUSDT"):
                return '{"notional_1h": 88.0}'
            return None

    fake = FakeRedis()
    result = mod.read_v2_liquidation_per_symbol_from(fake, "BTCUSDT")
    assert fake.keys_read == [
        "v2:market:liquidations:latest:BTCUSDT",
        "v2:market:liquidations:aggregate:BTCUSDT",
    ]
    assert result["any_populated"] is True
    assert result["v2_per_symbol_aggregator_present"] is True
    assert result["latest"]["side"] == "short"
    assert result["aggregate"]["notional_1h"] == 88.0


def test_aggregator_status_payload_safety_invariants() -> None:
    mod = _agg()
    p = mod.build_aggregator_status(symbols=("BTCUSDT",), timeframe="1m")
    assert p["live_gate"] == "blocked_human_only"
    assert p["live_symbols"] == []
    assert p["approves_live"] is False
    assert p["approves_canary"] is False
    assert p["approves_legacy_shutdown"] is False
    assert p["approves_redis_trim"] is False
    assert p["no_zero_fill_for_unknown_fields"] is True
    assert isinstance(p["v2_liquidation_aggregator_per_symbol_source_available"], bool)


def test_no_torch_imported() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.rl_core.liquidation_observation_aggregator"
    )
    importlib.import_module(
        "v2.backend.app.cli.v2_liquidation_observation_aggregator_status"
    )
    assert "torch" not in sys.modules


def test_builder_uses_aggregator_and_lifts_liquidations_per_symbol() -> None:
    fob = importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )
    result = fob.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot={
            "feature_snapshot_id": "v2_fsnap_test",
            "feature_freshness_state": "CURRENT",
            "features": {"last_liq_bps_24h": 17.0},
        },
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=None,
        market_funding=None,
        market_open_interest=None,
        liquidation_per_symbol={
            "latest": {"notional": 1234.5, "side": "long"},
            "aggregate": {"notional_1h": 9876.5},
            "any_populated": True,
            "v2_per_symbol_aggregator_present": True,
        },
    )
    # The aggregator should push liquidations subfamily present count past
    # the round-2 value of 4 — at least 5 of 12 with last_liq_bps_24h alone
    # (last_liq, abs, direction, notional_24h_proxy, direction_bias,
    # source_flag = 6) — but coinank fields require the intelligence file.
    sf = result.subfamily_present_counts.get("liquidations", 0)
    assert sf >= 10
    by_name = {
        name: (value, source)
        for name, value, source in zip(
            result.field_names,
            result.field_values,
            result.field_sources,
            strict=True,
        )
    }
    assert by_name["liquidations.latest_liquidation_notional"] == (
        1234.5,
        "V2_MARKET_LIQUIDATIONS_LATEST",
    )
    assert by_name["liquidations.liquidation_notional_1h_proxy"] == (
        9876.5,
        "V2_MARKET_LIQUIDATIONS_AGGREGATE",
    )
