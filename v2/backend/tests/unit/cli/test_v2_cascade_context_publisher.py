"""Cascade-context publisher: squeeze-detector input derivation (raw book/tape/premium)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest


class FakeRedis:
    def __init__(self, payloads: dict[str, object] | None = None) -> None:
        self.data = {
            key: json.dumps(value)
            for key, value in (payloads or {}).items()
        }
        self.get_calls: list[str] = []

    def get(self, key: str) -> str | None:
        self.get_calls.append(key)
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.data[key] = value
        return True


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _coinglass_v2_payload() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "provider": "coinglass",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": _utc(now - timedelta(seconds=30)),
        "available_at": _utc(now - timedelta(seconds=2)),
        "generated_at": _utc(now - timedelta(seconds=1)),
        "actual_payload_present": True,
        "provider_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "features": {
            "coinglass_trade_imbalance_usd": 2_000_000.0,
            "coinglass_liquidation_imbalance_usd": 8_000_000.0,
        },
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _moralis_self_declared_payload() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "schema_version": "moralis_feature_bridge_v1",
        "provider": "moralis",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": _utc(now - timedelta(seconds=30)),
        "available_at": _utc(now - timedelta(seconds=2)),
        "generated_at": _utc(now - timedelta(seconds=1)),
        "actual_payload_present": True,
        "provider_ready": True,
        "feature_bridge_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "source_temporal_contract_valid": True,
        "trainer_isolation_active": False,
        "trainer_consumption_prerequisites_bound": True,
        "consumer_receipts_bound": True,
        "features": {"moralis_net_exchange_flow_usd": 50_000_000.0},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _forged_raw_confluence() -> dict[str, Any]:
    return {
        "schema_version": "altdata_confluence_v1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "actual_payload_present": True,
        "decision_time_safe": True,
        "features": {"altdata_liquidation_sweep_risk_score": 1.0},
    }


def _publish_one(
    redis: FakeRedis,
    *,
    goal_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    from app.cli import v2_cascade_context_publisher as publisher

    monkeypatch.setattr(publisher, "_detect_existing_paper_loop_pid", lambda: None)
    publisher.publish_once(
        redis_client=redis,
        pairs=[("BTCUSDT", "1m")],
        coverage={"symbols": ["BTCUSDT"], "timeframes": ["1m"]},
        goal_dir=goal_dir,
        ttl_seconds=180,
    )
    return json.loads(redis.data["v2:microstructure:cascade_context:BTCUSDT:1m"])


def test_derive_orderbook_squeeze_inputs_from_raw_depth() -> None:
    """Regression: the raw Binance book has no derived metrics, so the squeeze
    detector ran for hours as a one-input (sweep-only) detector with direction
    permanently 'unclear' (trap == probability, block/ride never fired)."""
    from app.cli.v2_cascade_context_publisher import derive_orderbook_squeeze_inputs

    book = {
        "bids": [["100.0", "9.0"], ["99.9", "6.0"]],
        "asks": [["100.1", "3.0"], ["100.2", "2.0"]],
    }
    out = derive_orderbook_squeeze_inputs(book)
    assert out is not None
    assert out["depth_imbalance"] == pytest.approx((15.0 - 5.0) / 20.0)
    assert out["spread_bps"] == pytest.approx(0.1 / 100.05 * 10000.0)
    assert derive_orderbook_squeeze_inputs({"bids": [], "asks": []}) is None
    assert derive_orderbook_squeeze_inputs(None) is None
    # crossed/garbage books refuse rather than emit a fake signal
    assert derive_orderbook_squeeze_inputs({"bids": [["101", "1"]], "asks": [["100", "1"]]}) is None


def test_derive_tape_imbalance_notional_weighted_aggressor() -> None:
    from app.cli.v2_cascade_context_publisher import derive_tape_imbalance

    # m=False -> aggressive BUY, m=True -> aggressive SELL (Binance semantics)
    payload = {
        "trades": [
            {"p": "100", "q": "3", "m": False},
            {"p": "100", "q": "1", "m": True},
        ]
    }
    out = derive_tape_imbalance(payload)
    assert out is not None
    assert out["tape_imbalance"] == pytest.approx((300.0 - 100.0) / 400.0)
    assert derive_tape_imbalance({"trades": []}) is None
    assert derive_tape_imbalance(None) is None


def test_derive_mark_index_divergence_bps() -> None:
    from app.cli.v2_cascade_context_publisher import derive_mark_index_divergence

    out = derive_mark_index_divergence({"markPrice": "100.10", "indexPrice": "100.00"})
    assert out is not None
    assert out["mark_index_divergence_bps"] == pytest.approx(10.0, abs=1e-6)
    assert derive_mark_index_divergence({"markPrice": "x"}) is None
    assert derive_mark_index_divergence(None) is None


def test_live_source_shapes_receive_only_literal_producer_lineage() -> None:
    from app.cli.v2_cascade_context_publisher import _normalize_source_lineage

    open_interest = _normalize_source_lineage(
        "open_interest",
        {
            "open_interest": 123.0,
            "binance_time_ms": 1_800_000_000_000,
            "fetched_utc": "2027-01-15T08:00:01Z",
        },
    )
    assert open_interest is not None
    assert open_interest["event_time"] == 1_800_000_000_000
    assert open_interest["feature_cutoff"] == 1_800_000_000_000
    assert open_interest["ingested_at"] == "2027-01-15T08:00:01Z"
    assert open_interest["available_at"] == "2027-01-15T08:00:01Z"

    orderbook = _normalize_source_lineage(
        "orderbook",
        {
            "depth_imbalance": 0.2,
            "event_time": "2027-01-15T08:00:02.000Z",
            "received_at": "2027-01-15T08:00:02.050Z",
            "available_at": "2027-01-15T08:00:02.060Z",
        },
    )
    assert orderbook is not None
    assert orderbook["feature_cutoff"] == "2027-01-15T08:00:02.000Z"
    assert orderbook["ingested_at"] == "2027-01-15T08:00:02.050Z"

    tape = _normalize_source_lineage(
        "trade_tape",
        {
            "generated_utc": "2027-01-15T08:00:03.500Z",
            "trades": [
                {"T": 1_800_000_002_000},
                {"T": 1_800_000_003_000},
            ],
        },
    )
    assert tape is not None
    assert tape["event_time"] == 1_800_000_003_000
    assert tape["feature_cutoff"] == 1_800_000_003_000
    assert "ingested_at" not in tape
    assert "available_at" not in tape
    assert tape["generated_utc"] == "2027-01-15T08:00:03.500Z"

    tape_with_literal_receipt = _normalize_source_lineage(
        "trade_tape",
        {
            "received_at": "2027-01-15T08:00:03.400Z",
            "available_at": "2027-01-15T08:00:03.500Z",
            "trades": [{"T": 1_800_000_003_000}],
        },
    )
    assert tape_with_literal_receipt is not None
    assert tape_with_literal_receipt["ingested_at"] == (
        "2027-01-15T08:00:03.400Z"
    )
    assert tape_with_literal_receipt["available_at"] == (
        "2027-01-15T08:00:03.500Z"
    )


def test_unknown_liquidation_shape_is_not_stamped_with_publisher_now() -> None:
    from app.cli.v2_cascade_context_publisher import _normalize_source_lineage

    payload = {
        "notional": 100.0,
        "event_time_ms": 1_800_000_000_000,
        "generated_utc": "2027-01-15T08:00:01Z",
    }
    normalized = _normalize_source_lineage("liquidation_event", payload)

    assert normalized == payload
    assert "feature_cutoff" not in normalized
    assert "ingested_at" not in normalized
    assert "available_at" not in normalized


def test_observed_aggregate_is_preferred_but_not_statically_normalized() -> None:
    from app.cli.v2_cascade_context_publisher import _source_payloads
    from app.services.microstructure_trust.cascade_context import (
        build_cascade_context,
    )

    event_ms = 1_800_000_000_000
    observed = {
        "semantic_kind": "observed_binance_force_order_snapshots",
        "source_capture_semantics": (
            "latest_force_order_snapshot_per_symbol_per_1000ms"
        ),
        "source_capture_complete": False,
        "one_hour_retention_complete": True,
        "retention_window_complete": False,
        "retention_truncated": False,
        "window_1h_ms": 60 * 60 * 1000,
        "observed_notional_1h": 2_500_000.0,
        "observed_count_1h": 12,
        "event_time": event_ms,
        "feature_cutoff": event_ms,
        "ingested_at": event_ms + 100,
        "available_at": event_ms + 100,
        "generated_at": event_ms + 100,
    }
    redis = FakeRedis(
        {
            "v2:market:liquidations:observed_aggregate:BTCUSDT": observed,
            "v2:market:liquidations:latest:BTCUSDT": {
                "notional": 1.0,
            },
            "v2:market:liquidations:aggregate:BTCUSDT": {
                "notional_24h": 999_999_999.0,
            },
        }
    )

    sources = _source_payloads(redis, "BTCUSDT", "1m")
    liquidation = sources["liquidation_event"]
    assert liquidation is not None
    assert "notional_1h" not in liquidation
    assert "count_1h" not in liquidation
    assert "cascade_risk" not in liquidation
    assert liquidation["cascade_risk_semantics"] == (
        "OBSERVED_1H_LOWER_BOUND_REQUIRES_AUTHENTICATED_ADAPTIVE_NORMALIZATION"
    )
    assert liquidation["observed_lower_bound_only"] is True
    assert liquidation["cascade_observed_window_eligible"] is False
    assert liquidation["adaptive_normalization_available"] is False
    assert liquidation["source_redis_key"] == (
        "v2:market:liquidations:observed_aggregate:BTCUSDT"
    )
    assert "v2:market:liquidations:aggregate:BTCUSDT" not in redis.get_calls

    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        sources=sources,
        decision_time=event_ms + 1_000,
    )
    assert context["cascade_event_component"] is None


def test_incomplete_one_hour_retention_does_not_create_numeric_aliases() -> None:
    from app.cli.v2_cascade_context_publisher import _normalize_source_lineage

    normalized = _normalize_source_lineage(
        "liquidation_event",
        {
            "semantic_kind": "observed_binance_force_order_snapshots",
            "source_capture_complete": False,
            "one_hour_retention_complete": False,
            "retention_truncated": False,
            "window_1h_ms": 60 * 60 * 1000,
            "observed_notional_1h": 5_000_000.0,
            "observed_count_1h": 20,
        },
    )

    assert normalized is not None
    assert "cascade_risk" not in normalized
    assert normalized.get("cascade_observed_window_eligible") is not True


def test_cross_asset_fallback_uses_only_finalized_candle_clocks() -> None:
    from app.cli.v2_cascade_context_publisher import _cross_asset_source

    def candle(
        close: float,
        cutoff: int,
        *,
        closed: bool = True,
    ) -> dict:
        return {
            "close": close,
            "candle_close_time": cutoff,
            "candle_closed_confirmed": closed,
            "ingested_at": cutoff + 50,
            "available_at": cutoff + 60,
        }

    redis = FakeRedis(
        {
            "v2:market:ohlcv:binance:BTCUSDT:5m": [
                candle(100.0, 1_800_000_000_000),
                candle(101.0, 1_800_000_300_000),
                candle(999.0, 1_800_000_600_000, closed=False),
            ],
            "v2:market:ohlcv:binance:ETHUSDT:5m": [
                candle(200.0, 1_800_000_000_000),
                candle(198.0, 1_800_000_300_000),
            ],
        }
    )

    source = _cross_asset_source(redis)

    assert source["BTCUSDT_change_pct"] == pytest.approx(1.0)
    assert source["ETHUSDT_change_pct"] == pytest.approx(-1.0)
    assert source["feature_cutoff"] == 1_800_000_300_000
    assert source["event_time"] == 1_800_000_300_000
    assert source["ingested_at"] == 1_800_000_300_050
    assert source["available_at"] == 1_800_000_300_060
    assert source["covered_majors"] == ["BTCUSDT", "ETHUSDT"]
    assert source["major_coverage_complete"] is False
    assert "generated_at" not in source
    assert "generated_utc" not in source


@pytest.mark.parametrize(
    "mutation",
    [
        "legacy_v1",
        "stale",
        "future",
        "symbol_mismatch",
        "timeframe_mismatch",
        "forged_boolean",
        "nan_feature",
    ],
)
def test_raw_coinglass_cannot_bypass_canonical_fast_squeeze_gate(
    mutation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _coinglass_v2_payload()
    if mutation == "legacy_v1":
        payload["schema_version"] = "coinglass_aggregated_feature_payload_v1"
    elif mutation == "stale":
        now = datetime.now(UTC)
        payload.update(
            {
                "feature_cutoff": _utc(now - timedelta(minutes=12)),
                "available_at": _utc(now - timedelta(minutes=11)),
                "generated_at": _utc(now - timedelta(minutes=10)),
            }
        )
    elif mutation == "future":
        now = datetime.now(UTC)
        payload.update(
            {
                "feature_cutoff": _utc(now + timedelta(seconds=30)),
                "available_at": _utc(now + timedelta(seconds=31)),
                "generated_at": _utc(now + timedelta(seconds=32)),
            }
        )
    elif mutation == "symbol_mismatch":
        payload["symbol"] = "ETHUSDT"
    elif mutation == "timeframe_mismatch":
        payload["timeframe"] = "5m"
    elif mutation == "forged_boolean":
        payload["decision_time_safe"] = 1
    elif mutation == "nan_feature":
        payload["features"] = {"coinglass_trade_imbalance_usd": float("nan")}

    raw_confluence_key = "v2:altdata:confluence:BTCUSDT:1m"
    redis = FakeRedis(
        {
            "v2:features:coinglass:BTCUSDT:1m": payload,
            raw_confluence_key: _forged_raw_confluence(),
        }
    )

    context = _publish_one(redis, goal_dir=tmp_path, monkeypatch=monkeypatch)

    assert context["fast_squeeze_squeeze_probability"] == 0.0
    assert context["fast_squeeze_squeeze_direction"] == "unclear"
    assert context["fast_squeeze_entry_block_required"] is False
    assert context["fast_squeeze_provider_input_lineage"]["coinglass"][
        "admitted_to_fast_squeeze"
    ] is False
    assert raw_confluence_key not in redis.get_calls


def test_self_declared_moralis_release_stays_absent_from_fast_squeeze(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_confluence_key = "v2:altdata:confluence:BTCUSDT:1m"
    redis = FakeRedis(
        {
            "v2:features:moralis:BTCUSDT:1m": _moralis_self_declared_payload(),
            raw_confluence_key: _forged_raw_confluence(),
        }
    )

    context = _publish_one(redis, goal_dir=tmp_path, monkeypatch=monkeypatch)

    assert context["fast_squeeze_squeeze_probability"] == 0.0
    assert context["fast_squeeze_squeeze_direction"] == "unclear"
    assert context["fast_squeeze_provider_input_lineage"]["moralis"] == {
        "canonical_loader_present": False,
        "canonical_loader_stale": False,
        "admitted_to_fast_squeeze": False,
        "feature_cutoff": None,
        "available_at": None,
        "generated_at": None,
    }
    assert raw_confluence_key not in redis.get_calls


def test_fresh_exact_coinglass_v2_flows_with_causal_clocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _coinglass_v2_payload()
    raw_confluence_key = "v2:altdata:confluence:BTCUSDT:1m"
    redis = FakeRedis(
        {
            "v2:features:coinglass:BTCUSDT:1m": payload,
            # This opposite raw value is deliberately ignored; confluence is
            # rebuilt in process from the admitted ProviderInput.
            raw_confluence_key: _forged_raw_confluence(),
        }
    )

    context = _publish_one(redis, goal_dir=tmp_path, monkeypatch=monkeypatch)
    lineage = context["fast_squeeze_provider_input_lineage"]

    assert context["fast_squeeze_squeeze_probability"] > 0.0
    assert context["fast_squeeze_squeeze_direction"] == "up"
    assert context["fast_squeeze_entry_block_required"] is True
    assert lineage["coinglass"] == {
        "canonical_loader_present": True,
        "canonical_loader_stale": False,
        "admitted_to_fast_squeeze": True,
        "feature_cutoff": payload["feature_cutoff"],
        "available_at": payload["available_at"],
        "generated_at": payload["generated_at"],
    }
    assert lineage["confluence"]["reconstructed_from_canonical_inputs"] is True
    assert lineage["confluence"]["admitted_to_fast_squeeze"] is True
    assert lineage["confluence"]["feature_cutoff"] == payload["feature_cutoff"]
    assert lineage["confluence"]["providers_present"] == ["coinglass"]
    assert raw_confluence_key not in redis.get_calls


def test_isolated_release_imports_one_v2_confluence_type_origin(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[5]
    probe = f"""
import json
import pathlib
import sys

sys.path.insert(0, {json.dumps(str(repo_root))})
from v2.backend.app.cli import v2_cascade_context_publisher as cascade
from v2.backend.app.services.altdata import altdata_confluence_engine as engine
from v2.backend.app.services.altdata import provider_feature_bridge as bridge

print(json.dumps({{
    "bridge_file": str(pathlib.Path(bridge.__file__).resolve()),
    "engine_file": str(pathlib.Path(engine.__file__).resolve()),
    "cascade_file": str(pathlib.Path(cascade.__file__).resolve()),
    "provider_type_module": bridge.ProviderInput.__module__,
    "builder_module": cascade.build_confluence.__module__,
    "same_provider_type": bridge.ProviderInput is engine.ProviderInput,
    "same_builder": cascade.build_confluence is engine.build_confluence,
    "top_level_engine_loaded": (
        "app.services.altdata.altdata_confluence_engine" in sys.modules
    ),
}}))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter, literal probe
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(completed.stdout)

    assert observed["same_provider_type"] is True
    assert observed["same_builder"] is True
    assert observed["provider_type_module"] == (
        "v2.backend.app.services.altdata.altdata_confluence_engine"
    )
    assert observed["builder_module"] == (
        "v2.backend.app.services.altdata.altdata_confluence_engine"
    )
    assert observed["top_level_engine_loaded"] is False
    for field in ("bridge_file", "engine_file", "cascade_file"):
        assert Path(observed[field]).is_relative_to(repo_root)
