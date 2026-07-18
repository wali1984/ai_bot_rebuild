from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record,
    load_snapshot,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import data_loader as data_loader_mod
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
    V2UnifiedFeatureTensorBuilder,
)
from v2.backend.app.services.native_trainer.trusted_replay.bootstrap import (
    build_temporal_split_manifest,
    bootstrap_trusted_replay_dataset,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    build_trusted_replay_row,
)


FEATURE_CUTOFF = "2026-06-22T00:00:00Z"
AVAILABLE_AT = "2026-06-22T00:00:30Z"
DECISION_TIME = "2026-06-22T00:01:00Z"


def _snapshot(**overrides: object) -> dict[str, object]:
    features = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "last_price": 100.0,
        "ema_12": 101.0,
        "ema_26": 99.0,
        "rsi_14": 55.0,
        "macd": 1.0,
        "macd_signal": 0.0,
    }
    snapshot: dict[str, object] = build_archive_record(
        snapshot_id="replay-snapshot-1",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_cutoff=FEATURE_CUTOFF,
        decision_time=DECISION_TIME,
        available_at=AVAILABLE_AT,
        mtf_snapshot_id="mtf-1",
        features=features,
        missing_mask={name: False for name in features},
        stale_mask={name: False for name in features},
        source_availability={"ohlcv": True},
        source_hashes={"feature_payload_hash": "hash"},
        created_at=AVAILABLE_AT,
        extra={
            "decision_id": "decision-1",
            "candle_closed_confirmed": True,
            "model_version": "unit",
            "checkpoint_id": "ckpt",
        },
    )
    snapshot.update(overrides)
    if overrides:
        snapshot["content_sha256"] = build_archive_record(
            snapshot_id=snapshot["snapshot_id"],
            symbol=snapshot["symbol"],
            timeframe=snapshot["timeframe"],
            feature_cutoff=snapshot["feature_cutoff"],
            decision_time=snapshot["decision_time"],
            available_at=snapshot["available_at"],
            mtf_snapshot_id=snapshot["mtf_snapshot_id"],
            features=snapshot["features"],
            missing_mask=snapshot["missing_mask"],
            stale_mask=snapshot["stale_mask"],
            source_availability=snapshot["source_availability"],
            source_hashes=snapshot["source_hashes"],
            created_at=snapshot["created_at"],
            extra={
                "decision_id": snapshot.get("decision_id"),
                "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
                "model_version": snapshot.get("model_version"),
                "checkpoint_id": snapshot.get("checkpoint_id"),
            },
        )["content_sha256"]
    return snapshot


def _candles() -> list[dict[str, object]]:
    start = datetime(2026, 6, 22, 0, 1, tzinfo=timezone.utc)
    rows: list[dict[str, object]] = []
    for minute in range(1, 260):
        close_time = start + timedelta(minutes=minute)
        close = 100.0 + minute * 0.02
        rows.append(
            {
                "candle_close_time": close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "close": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "is_closed": True,
                "closed_candle": True,
                "candle_closed_confirmed": True,
            }
        )
    return rows


class _NoScanRedis:
    def scan_iter(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("archive-only bootstrap must not scan Redis snapshots")

    def get(self, _key: str) -> None:
        return None

    def hgetall(self, _key: str) -> dict[str, object]:
        return {}


def _append_archive_series(root: Path, *, rows: int = 270) -> None:
    base = datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)
    for minute in range(rows):
        close_time = base + timedelta(minutes=minute)
        decision_time = close_time + timedelta(seconds=1)
        close = 100.0 + minute * 0.02
        features = {
            "open": close - 0.01,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "last_price": close,
            "volume": 1000.0 + minute,
            "ema_12": close + 0.1,
            "ema_26": close - 0.1,
            "rsi_14": 55.0,
            "macd": 1.0,
            "macd_signal": 0.0,
        }
        for offset, (name, _source) in enumerate(V2UnifiedFeatureTensorBuilder.feature_spec):
            features.setdefault(str(name), close + (offset * 0.001))
        record = build_archive_record(
            snapshot_id=f"archive-only-{minute:04d}",
            symbol="BTCUSDT",
            timeframe="1m",
            feature_cutoff=close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            decision_time=decision_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            available_at=close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            mtf_snapshot_id=f"mtf-archive-only-{minute:04d}",
            features=features,
            missing_mask={name: False for name in features},
            stale_mask={name: False for name in features},
            source_availability={"ohlcv": True},
            source_hashes={"feature_payload_hash": f"hash-{minute}"},
            created_at=close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            extra={
                "decision_id": f"decision-archive-only-{minute:04d}",
                "candle_closed_confirmed": True,
                "model_version": "unit",
                "checkpoint_id": "ckpt",
            },
        )
        append_snapshot(record, root=root, update_checksum_manifest=False)


def test_future_labels_not_in_feature_tensor() -> None:
    snapshot = _snapshot(features={**_snapshot()["features"], "future_return_5m_bps": 10.0})

    row, reasons = build_trusted_replay_row(snapshot, candles=_candles())

    assert row is None
    assert "FUTURE_LABEL_PRESENT_IN_FEATURES" in reasons


def test_available_at_after_decision_rejected() -> None:
    snapshot = _snapshot(available_at="2026-06-22T00:02:00Z")

    row, reasons = build_trusted_replay_row(snapshot, candles=_candles())

    assert row is None
    assert "AVAILABLE_AT_AFTER_DECISION_TIME" in reasons


def test_open_candle_rejected() -> None:
    snapshot = _snapshot(candle_closed_confirmed=False)

    row, reasons = build_trusted_replay_row(snapshot, candles=_candles())

    assert row is None
    assert "OPEN_CANDLE_REJECTED" in reasons


def test_costs_cannot_flip_small_down_move_into_profitable_long() -> None:
    decision_time = datetime(2026, 6, 22, 0, 1, tzinfo=timezone.utc)
    candles = []
    for seconds, close in (
        (5 * 60, 100.0),
        (15 * 60, 99.99),  # raw 15m return = -1 bps
        (60 * 60, 100.0),
        (4 * 60 * 60, 100.0),
    ):
        candles.append(
            {
                "candle_close_time": (decision_time + timedelta(seconds=seconds))
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "close": close,
                "high": max(100.0, close),
                "low": min(100.0, close),
                "candle_closed_confirmed": True,
            }
        )

    row, reasons = build_trusted_replay_row(
        _snapshot(selected_action="long"),
        candles=candles,
        round_trip_cost_bps=2.0,
        action_threshold_bps=0.5,
    )

    assert row is not None, reasons
    assert row["raw_future_return_15m_bps"] == pytest.approx(-1.0)
    assert row["counterfactual_long_net_pnl_bps"] == pytest.approx(-3.0)
    assert row["counterfactual_short_net_pnl_bps"] == pytest.approx(-1.0)
    assert row["target_action"] == "hold"
    assert row["future_return_after_cost_bps"] == 0.0
    assert row["directional_outcome"] == "DOWN"
    assert row["counterfactual_action_was_profitable"] is False
    assert row["actual_behavior_net_pnl_bps"] == pytest.approx(-3.0)
    assert row["actual_behavior_trade_outcome"] == "LOSS"
    assert row["actual_behavior_action_was_profitable"] is False
    assert row["trade_outcome"] == "BREAKEVEN"


@pytest.mark.parametrize(
    ("label_kwargs", "expected_reason"),
    (
        ({"round_trip_cost_bps": float("nan")}, "ROUND_TRIP_COST_BPS_INVALID"),
        ({"action_threshold_bps": float("inf")}, "ACTION_THRESHOLD_BPS_INVALID"),
    ),
)
def test_invalid_cost_label_inputs_fail_closed(
    label_kwargs: dict[str, float],
    expected_reason: str,
) -> None:
    row, reasons = build_trusted_replay_row(
        _snapshot(),
        candles=_candles(),
        **label_kwargs,
    )

    assert row is None
    assert reasons == [expected_reason]


def test_temporal_split_has_no_overlap() -> None:
    items = [
        (f"2026-06-22T00:{minute:02d}:00Z", f"row-{minute}")
        for minute in range(20)
    ]

    manifest = build_temporal_split_manifest(items)

    assert manifest["temporal_overlap"] is False
    assert manifest["training_window"]["end_decision_time"] < manifest["validation_window"]["start_decision_time"]
    assert manifest["validation_window"]["end_decision_time"] < manifest["holdout_window"]["start_decision_time"]


def test_snapshot_hash_mismatch_rejected(tmp_path: Path) -> None:
    result = append_snapshot(_snapshot(), root=tmp_path)
    payload = json.loads(result.blob_path.read_text(encoding="utf-8"))
    payload["features"]["close"] = 200.0
    result.blob_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotArchiveError, match="CONTENT_SHA256_MISMATCH"):
        load_snapshot("replay-snapshot-1", root=tmp_path)


def test_archive_only_bootstrap_refreshes_replay_status_without_redis_scan(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    _append_archive_series(archive_root)

    result = bootstrap_trusted_replay_dataset(
        client=_NoScanRedis(),
        repo_root=tmp_path,
        scan_limit=0,
        replay_limit=20,
        archive_root=archive_root,
        import_from_redis=False,
    )

    status = result["dataset_status"]
    assert status["redis_snapshot_import_enabled"] is False
    assert status["redis_snapshots_scanned"] == 0
    assert status["trusted_replay_rows"] == 20
    assert status["trusted_replay_rows_requirement_met"] is False
    assert status["label_distribution"]["positive_directional_labels"] > 0
    published = tmp_path / "goal_state" / "V2_TRUSTED_REPLAY_BOOTSTRAP_PAPER_EXPLORATION_AND_ONLINE_LEARNING_ACTIVATION" / "trusted_replay_dataset_status.json"
    assert json.loads(published.read_text(encoding="utf-8"))["trusted_replay_rows"] == 20


def test_trusted_replay_loader_skips_critical_missing_rows(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    base = datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)
    for minute in range(260):
        close_time = base + timedelta(minutes=minute)
        decision_time = close_time + timedelta(seconds=1)
        close = 100.0 + minute * 0.02
        features = {
            "open": close - 0.01,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "last_price": close,
            "ema_12": close + 0.1,
            "ema_26": close - 0.1,
            "rsi_14": 55.0,
            "macd": 1.0,
            "macd_signal": 0.0,
        }
        record = build_archive_record(
            snapshot_id=f"critical-missing-{minute:04d}",
            symbol="BTCUSDT",
            timeframe="1m",
            feature_cutoff=close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            decision_time=decision_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            available_at=close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            mtf_snapshot_id=f"mtf-critical-missing-{minute:04d}",
            features=features,
            missing_mask={name: False for name in features},
            stale_mask={name: False for name in features},
            source_availability={"ohlcv": True},
            source_hashes={"feature_payload_hash": f"hash-{minute}"},
            created_at=close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
            extra={
                "decision_id": f"decision-critical-missing-{minute:04d}",
                "candle_closed_confirmed": True,
                "model_version": "unit",
                "checkpoint_id": "ckpt",
            },
        )
        append_snapshot(record, root=archive_root, update_checksum_manifest=False)
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=archive_root)

    examples = loader.load_trusted_replay_examples(limit=20)

    assert examples == []


def test_trusted_replay_loader_uses_persistent_cursor_not_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-0013: the lane must walk oldest-first from a persisted byte cursor
    (never a bounded newest-first scan, which only ever inspects rows younger
    than the label horizon and starves training forever)."""
    seen: dict[str, object] = {}

    def fake_iter_snapshots_from_offset(root: Path, *, start_offset: int = 0, limit: int | None = None):
        seen["root"] = Path(root)
        seen["start_offset"] = start_offset
        return iter(())

    archive_root = tmp_path / "archive"
    archive_root.mkdir(parents=True)
    (archive_root / "trusted_replay_cursor.json").write_text(
        json.dumps({"manifest_offset": 12345}), encoding="utf-8"
    )
    monkeypatch.setattr(
        data_loader_mod, "iter_snapshots_from_offset", fake_iter_snapshots_from_offset
    )
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=archive_root)

    examples = loader.load_trusted_replay_examples(limit=32768)

    assert examples == []
    assert seen == {"root": archive_root, "start_offset": 12345}
    scan = loader.last_trusted_replay_scan
    assert scan["cursor_offset"] == 12345
    assert scan["embargo_seconds"] == data_loader_mod.TRUSTED_REPLAY_LABEL_EMBARGO_SECONDS


def _tensor(feature_snapshot_id: str, value: float) -> FeatureTensorRecord:
    values = (value, value + 1.0, value - 1.0, value * 0.5)
    return FeatureTensorRecord(
        tensor_id=f"tensor-{feature_snapshot_id}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=feature_snapshot_id,
        values=values,
        missing_mask=(0, 0, 0, 0),
        stale_mask=(0, 0, 0, 0),
        source_availability=(1, 1, 1, 1),
        feature_names=("open", "high", "low", "close"),
        source_labels=("ohlcv", "ohlcv", "ohlcv", "ohlcv"),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1, 1, 1, 1),
    )


def _example_from_row(row: dict[str, object], idx: int) -> TrainingExample:
    label = 1 if float(row["future_return_after_cost_bps"]) > 0 else 2
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=_tensor(f"replay-{idx}", 1.0 + idx),
        label_action_index=label,
        label_expected_move_after_cost_bps=float(row["future_return_after_cost_bps"]),
        payload_keys=(str(row["sample_id"]),),
        row_classification="TRAINABLE",
        trust_row=row,
    )


def test_trusted_replay_changes_parameter_hash() -> None:
    long_row, reasons = build_trusted_replay_row(_snapshot(snapshot_id="replay-long"), candles=_candles())
    assert long_row is not None, reasons
    short_snapshot = _snapshot(snapshot_id="replay-short")
    short_candles = []
    start = datetime(2026, 6, 22, 0, 1, tzinfo=timezone.utc)
    for minute in range(1, 260):
        close_time = start + timedelta(minutes=minute)
        close = 100.0 - minute * 0.02
        short_candles.append(
            {
                "candle_close_time": close_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "close": close,
                "high": close + 0.5,
                "low": close - 0.5,
                "candle_closed_confirmed": True,
            }
        )
    short_row, reasons = build_trusted_replay_row(short_snapshot, candles=short_candles)
    assert short_row is not None, reasons
    trainer = V2HybridPPOTrainer(model=V2HybridPolicyModel(input_dim=16))

    result = trainer.train(
        [_example_from_row(long_row, 1), _example_from_row(short_row, 2)],
        steps=2,
        batch_size=2,
        validation_fraction=0.0,
    )

    assert result.metrics["learning_update_lane"] == "outcome_supervised"
    assert result.metrics["trusted_replay_rows_loaded"] == 2
    assert result.metrics["parameter_hash_before"] != result.metrics["parameter_hash_after"]
    assert result.metrics["weight_delta_norm"] > 0.0


def test_expected_move_not_used_as_realized_reward() -> None:
    row, reasons = build_trusted_replay_row(_snapshot(), candles=_candles())

    assert row is not None, reasons
    assert row["uses_expected_move_as_realized_reward"] is False
    assert row["realized_reward_source"] == "counterfactual_target_after_cost_from_finalized_candles"
