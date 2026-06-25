from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from v2.backend.app.services.native_trainer.challenger_v2_feature_adapter import (
    SCHEMA_VERSION,
    adapt_replay_snapshot,
    adapt_runtime_snapshot,
    build_normalization_spec,
    feature_schema_hash,
    normalization_hash,
)


BASE_TIME = datetime(2026, 6, 25, 0, 0, tzinfo=timezone.utc)


def _iso(seconds: int) -> str:
    return (BASE_TIME + timedelta(seconds=seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _snapshot(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_id": "snap-v2-1",
        "feature_snapshot_id": "snap-v2-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": _iso(0),
        "available_at": _iso(10),
        "decision_time": _iso(60),
        "generated_at": _iso(60),
        "candle_open_time": _iso(-60),
        "candle_close_time": _iso(0),
        "candle_closed_confirmed": True,
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "edge": 3.0,
            "funding_rate": 0.0001,
        },
        "missing_mask": {
            "open": False,
            "edge": False,
            "funding_rate": False,
        },
        "stale_mask": {
            "open": False,
            "edge": False,
            "funding_rate": False,
        },
    }
    row.update(overrides)
    return row


def _normalization():
    rows = [
        _snapshot(features={"open": 100.0, "edge": 2.0, "funding_rate": 0.0001}),
        _snapshot(features={"open": 101.0, "edge": 4.0, "funding_rate": 0.0002}),
        _snapshot(features={"open": 99.0, "edge": 1.0, "funding_rate": -0.0001}),
    ]
    return build_normalization_spec(rows, feature_names=("open", "edge", "funding_rate"))


def test_same_snapshot_produces_same_replay_and_runtime_vector() -> None:
    spec = _normalization()
    snapshot = _snapshot()

    replay = adapt_replay_snapshot(snapshot, normalization=spec)
    runtime = adapt_runtime_snapshot(snapshot, normalization=spec)

    assert replay.feature_vector_hash == runtime.feature_vector_hash
    assert replay.raw_vector == runtime.raw_vector
    assert replay.normalized_vector == runtime.normalized_vector


def test_feature_order_identical() -> None:
    spec = _normalization()
    replay = adapt_replay_snapshot(_snapshot(), normalization=spec)
    runtime = adapt_runtime_snapshot(_snapshot(), normalization=spec)

    assert replay.feature_names_in_order == ("open", "edge", "funding_rate")
    assert runtime.feature_names_in_order == replay.feature_names_in_order
    assert feature_schema_hash(replay.feature_names_in_order) == feature_schema_hash(runtime.feature_names_in_order)
    assert replay.feature_schema_version == SCHEMA_VERSION


def test_normalization_identical() -> None:
    spec = _normalization()
    replay = adapt_replay_snapshot(_snapshot(), normalization=spec)
    runtime = adapt_runtime_snapshot(_snapshot(), normalization=spec)

    assert replay.normalization_status == "PASS"
    assert runtime.normalization_status == "PASS"
    assert normalization_hash(spec) == normalization_hash(spec)
    assert runtime.normalized_vector == pytest.approx(replay.normalized_vector)


def test_missing_mask_identical() -> None:
    spec = _normalization()
    snapshot = _snapshot(features={"open": 100.0, "funding_rate": 0.0001}, missing_mask={"edge": True})

    replay = adapt_replay_snapshot(snapshot, normalization=spec)
    runtime = adapt_runtime_snapshot(snapshot, normalization=spec)

    assert replay.missing_feature_names == ("edge",)
    assert runtime.missing_feature_names == replay.missing_feature_names
    assert "MISSING_MODEL_FEATURE" in replay.rejection_reasons


def test_stale_mask_identical() -> None:
    spec = _normalization()
    snapshot = _snapshot(stale_mask={"edge": True}, stale_feature_flags=["edge"])

    replay = adapt_replay_snapshot(snapshot, normalization=spec)
    runtime = adapt_runtime_snapshot(snapshot, normalization=spec)

    assert replay.stale_feature_names == ("edge",)
    assert runtime.stale_feature_names == replay.stale_feature_names
    assert "STALE_MODEL_FEATURE" in replay.rejection_reasons


def test_integrity_result_identical() -> None:
    spec = _normalization()
    snapshot = _snapshot()

    replay = adapt_replay_snapshot(snapshot, normalization=spec)
    runtime = adapt_runtime_snapshot(snapshot, normalization=spec)

    assert replay.integrity_status == runtime.integrity_status
    assert replay.integrity_status["accepted_for_training"] is True
    assert replay.rejection_reasons == runtime.rejection_reasons

