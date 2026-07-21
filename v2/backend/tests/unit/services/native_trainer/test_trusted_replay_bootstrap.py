from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    CanonicalCandle,
    canonical_candle_id,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record,
    content_sha256,
    load_snapshot,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    data_loader as data_loader_mod,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    profitability_target_from_trust_row,
)
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
    _quarantine_legacy_v1_manifest,
    bootstrap_trusted_replay_dataset,
    build_temporal_split_manifest,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    TRUSTED_REPLAY_COST_EVIDENCE_SCHEMA_VERSION,
    TRUSTED_REPLAY_LABEL_POLICY_VERSION,
    build_trusted_replay_row,
    target_action_index,
    trusted_replay_cost_evidence,
)

FEATURE_CUTOFF = "2026-06-22T00:00:00Z"
AVAILABLE_AT = "2026-06-22T00:00:30Z"
DECISION_TIME = "2026-06-22T00:01:00Z"
TRAINING_OBSERVED_AT = datetime(2026, 6, 22, 5, 0, tzinfo=timezone.utc)
LABEL_PATH_START = datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)
LABEL_HORIZON_SLOT = {"5m": 1, "15m": 3, "1h": 12, "4h": 48}


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
        "fee_bps": 1.0,
        "actual_observed_spread_entry_bps": 0.5,
        "expected_slippage_bps": 0.25,
        "expected_funding_bps": 0.25,
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
            "trainer_consumable": True,
            "model_version": "unit",
            "checkpoint_id": "ckpt",
        },
    )
    snapshot.update(overrides)
    snapshot["content_sha256"] = content_sha256(snapshot)
    return snapshot


def _candles(
    *,
    horizon_closes: dict[str, float] | None = None,
    path_high: float | None = None,
    path_low: float | None = None,
) -> list[dict[str, object]]:
    """Build the exact finalized 5m label frontier used by replay.

    The decision occurs inside slot 0.  Forty-nine contiguous base candles are
    therefore required to reach the first finalized 5m close at or after the
    4h target without borrowing the snapshot's own timeframe.
    """

    selected_closes = dict(horizon_closes or {})
    rows: list[dict[str, object]] = []
    close_override_by_slot = {
        LABEL_HORIZON_SLOT[horizon]: close
        for horizon, close in selected_closes.items()
    }
    for slot in range(LABEL_HORIZON_SLOT["4h"] + 1):
        open_time = LABEL_PATH_START + timedelta(minutes=5 * slot)
        close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
        default_close = 100.0 if selected_closes else 100.0 + (slot + 1) * 0.1
        close = close_override_by_slot.get(slot, default_close)
        high = max(100.0, close, path_high if path_high is not None else close + 0.5)
        low = min(100.0, close, path_low if path_low is not None else close - 0.5)
        ingested_at = close_time + timedelta(milliseconds=1)
        raw_hash = hashlib.sha256(
            f"BTCUSDT:5m:{slot}:{close}:{high}:{low}".encode("utf-8")
        ).hexdigest()
        rows.append(
            CanonicalCandle(
                symbol="BTCUSDT",
                exchange="binance",
                timeframe="5m",
                candle_open_time=int(open_time.timestamp() * 1000),
                candle_close_time=int(close_time.timestamp() * 1000),
                event_time=int(close_time.timestamp() * 1000),
                ingested_at=int(ingested_at.timestamp() * 1000),
                available_at=int(ingested_at.timestamp() * 1000),
                is_closed=True,
                source="binance_wss",
                source_sequence_id=f"unit-5m-{slot}",
                raw_payload_hash=raw_hash,
                ohlcv={
                    "open": 100.0,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 1_000.0 + slot,
                },
                is_backfilled=False,
                feature_eligible=True,
            ).to_dict()
        )
    return rows


def _build_replay(
    snapshot: dict[str, object],
    *,
    candles: list[dict[str, object]] | None = None,
    training_observed_at: datetime | str | None = TRAINING_OBSERVED_AT,
) -> tuple[dict[str, object] | None, list[str]]:
    return build_trusted_replay_row(
        snapshot,
        candles=_candles() if candles is None else candles,
        training_observed_at=training_observed_at,
    )


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
            "fee_bps": 1.0,
            "actual_observed_spread_entry_bps": 0.5,
            "expected_slippage_bps": 0.25,
            "expected_funding_bps": 0.25,
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
                "trainer_consumable": True,
                "model_version": "unit",
                "checkpoint_id": "ckpt",
            },
        )
        append_snapshot(record, root=root, update_checksum_manifest=False)


def test_future_labels_not_in_feature_tensor() -> None:
    snapshot = _snapshot(features={**_snapshot()["features"], "future_return_5m_bps": 10.0})

    row, reasons = _build_replay(snapshot)

    assert row is None
    assert "FUTURE_LABEL_PRESENT_IN_FEATURES" in reasons


def test_available_at_after_decision_rejected() -> None:
    snapshot = _snapshot(available_at="2026-06-22T00:02:00Z")

    row, reasons = _build_replay(snapshot)

    assert row is None
    assert "AVAILABLE_AT_AFTER_DECISION_TIME" in reasons


def test_open_candle_rejected() -> None:
    snapshot = _snapshot(candle_closed_confirmed=False)

    row, reasons = _build_replay(snapshot)

    assert row is None
    assert "OPEN_CANDLE_REJECTED" in reasons


def test_costs_cannot_flip_small_down_move_into_profitable_long() -> None:
    candles = _candles(
        horizon_closes={
            "5m": 100.0,
            "15m": 99.99,  # raw 15m return = -1 bps
            "1h": 100.0,
            "4h": 100.0,
        }
    )

    row, reasons = _build_replay(
        _snapshot(selected_action="long"),
        candles=candles,
    )

    assert row is not None, reasons
    assert row["raw_future_return_15m_bps"] == pytest.approx(-1.0)
    assert row["counterfactual_long_net_pnl_bps"] == pytest.approx(-4.25)
    assert row["counterfactual_short_net_pnl_bps"] == pytest.approx(-2.25)
    assert row["target_action"] == "hold"
    assert row["future_return_after_cost_bps"] == 0.0
    assert row["directional_outcome"] == "DOWN"
    assert row["counterfactual_action_was_profitable"] is False
    assert row["actual_behavior_net_pnl_bps"] == pytest.approx(-4.25)
    assert row["actual_behavior_trade_outcome"] == "LOSS"
    assert row["actual_behavior_action_was_profitable"] is False
    assert row["trade_outcome"] == "BREAKEVEN"


def test_missing_cost_component_fails_closed_without_flat_fallback() -> None:
    snapshot = _snapshot()
    del snapshot["features"]["expected_funding_bps"]  # type: ignore[index]
    snapshot["content_sha256"] = content_sha256(snapshot)

    row, reasons = _build_replay(snapshot)

    assert row is None
    assert reasons == ["COST_EVIDENCE_FUNDING_MISSING"]


def test_nonfinite_cost_component_fails_closed() -> None:
    snapshot = _snapshot()
    snapshot["features"]["expected_slippage_bps"] = float("nan")  # type: ignore[index]
    snapshot["content_sha256"] = content_sha256(snapshot)

    row, reasons = _build_replay(snapshot)

    assert row is None
    assert reasons == ["COST_EVIDENCE_SLIPPAGE_NONFINITE_OR_INVALID"]


def test_stale_cost_component_fails_closed() -> None:
    snapshot = _snapshot()
    snapshot["stale_mask"]["fee_bps"] = True  # type: ignore[index]
    snapshot["content_sha256"] = content_sha256(snapshot)

    row, reasons = _build_replay(snapshot)

    assert row is None
    assert reasons == ["COST_EVIDENCE_FEE_FLAGGED_STALE"]


def test_future_cost_evidence_clock_fails_closed() -> None:
    snapshot = _snapshot(available_at="2026-06-22T00:02:00Z")

    evidence, reasons = trusted_replay_cost_evidence(snapshot)

    assert evidence is None
    assert "COST_EVIDENCE_AVAILABLE_AT_AFTER_DECISION_TIME" in reasons


def test_adaptive_cost_increase_moves_marginal_direction_to_hold() -> None:
    candles = _candles(
        horizon_closes={
            "5m": 100.0,
            "15m": 100.04,
            "1h": 100.04,
            "4h": 100.04,
        }
    )
    low_cost = _snapshot(snapshot_id="low-cost")
    high_cost = _snapshot(snapshot_id="high-cost")
    high_cost["features"]["fee_bps"] = 3.0  # type: ignore[index]
    high_cost["content_sha256"] = content_sha256(high_cost)

    low_row, low_reasons = _build_replay(low_cost, candles=candles)
    high_row, high_reasons = _build_replay(high_cost, candles=candles)

    assert low_row is not None, low_reasons
    assert high_row is not None, high_reasons
    assert low_row["target_action"] == "long"
    assert high_row["target_action"] == "hold"
    assert high_row["action_dead_zone_bps"] > low_row["action_dead_zone_bps"]


def test_replay_label_contract_has_no_static_threshold_or_cost_fallback() -> None:
    row, reasons = _build_replay(_snapshot())

    assert row is not None, reasons
    assert row["trusted_replay_label_policy_version"] == TRUSTED_REPLAY_LABEL_POLICY_VERSION
    assert row["cost_evidence_schema_version"] == TRUSTED_REPLAY_COST_EVIDENCE_SCHEMA_VERSION
    assert row["round_trip_cost_bps"] == pytest.approx(
        (2.0 * row["fee_bps"])
        + row["spread_bps"]
        + (2.0 * row["slippage_bps"])
        + abs(row["funding_bps"])
    )
    assert row["action_dead_zone_bps"] == pytest.approx(
        row["round_trip_cost_bps"]
    )
    assert row["round_trip_fee_drag_bps"] == pytest.approx(
        2.0 * row["fee_bps"]
    )
    assert row["round_trip_slippage_drag_bps"] == pytest.approx(
        2.0 * row["slippage_bps"]
    )
    assert row["flat_round_trip_cost_fallback_used"] is False
    assert row["static_action_threshold_used"] is False
    assert target_action_index(row["target_action"]) == row["target_action_index"]


@pytest.mark.parametrize(
    ("close_15m", "expected_action", "expected_mfe", "expected_mae"),
    (
        (101.0, "long", 200.0, -1500.0),
        (99.0, "short", 1500.0, -200.0),
        (100.01, "hold", 0.0, 0.0),
    ),
)
def test_counterfactual_excursion_is_side_aware(
    close_15m: float,
    expected_action: str,
    expected_mfe: float,
    expected_mae: float,
) -> None:
    candles = _candles(
        horizon_closes={
            "5m": 100.0,
            "15m": close_15m,
            "1h": close_15m,
            "4h": close_15m,
        },
        path_high=102.0,
        path_low=85.0,
    )

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is not None, reasons
    assert row["target_action"] == expected_action
    assert row["counterfactual_excursion_action"] == expected_action
    assert row["counterfactual_excursion_scope"] == (
        "FULL_FINALIZED_5M_CANDLES_OPENING_AT_OR_AFTER_DECISION_TIME"
    )
    assert row["maximum_favorable_excursion_bps"] == pytest.approx(
        expected_mfe
    )
    assert row["maximum_adverse_excursion_bps"] == pytest.approx(expected_mae)
    assert row["outcome_targets"]["MFE"] == pytest.approx(expected_mfe)
    assert row["outcome_targets"]["MAE"] == pytest.approx(expected_mae)


def test_excursion_excludes_5m_candle_overlapping_decision_boundary() -> None:
    candles = _candles(
        horizon_closes={
            "5m": 100.0,
            "15m": 101.0,
            "1h": 101.0,
            "4h": 101.0,
        },
        path_high=102.0,
        path_low=98.0,
    )
    overlapping = candles[0]
    overlapping_ohlcv = dict(overlapping["ohlcv"])  # type: ignore[arg-type]
    overlapping_ohlcv.update({"high": 150.0, "low": 50.0})
    overlapping["ohlcv"] = overlapping_ohlcv
    overlapping["high"] = 150.0
    overlapping["low"] = 50.0
    overlapping["raw_payload_hash"] = hashlib.sha256(
        b"predecision-overlap-extremes"
    ).hexdigest()
    overlapping["candle_id"] = canonical_candle_id(overlapping)

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is not None, reasons
    assert row["maximum_favorable_excursion_bps"] == pytest.approx(200.0)
    assert row["maximum_adverse_excursion_bps"] == pytest.approx(-200.0)
    assert row["trusted_replay_label_path_candle_count"] == 49
    assert row["trusted_replay_excursion_candle_count"] == 48
    assert row[
        "trusted_replay_excursion_excluded_overlapping_decision_candle_ids"
    ] == [overlapping["candle_id"]]
    assert overlapping["candle_id"] not in row[
        "trusted_replay_excursion_candle_ids"
    ]
    assert row["trusted_replay_excursion_predecision_overlap_excluded"] is True


def test_counterfactual_excursion_missing_path_price_fails_closed() -> None:
    candles = _candles()
    candles[0].pop("high")

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is None
    assert "LABEL_CANDLE_HIGH_MISSING_OR_INVALID" in reasons
    assert "LABEL_CANDLE_OHLCV_CANONICAL_COPY_MISMATCH" in reasons


def test_4h_snapshot_uses_canonical_5m_candle_for_15m_target() -> None:
    candles = _candles(
        horizon_closes={
            "5m": 100.1,
            "15m": 101.0,
            "1h": 102.0,
            "4h": 103.0,
        }
    )

    row, reasons = _build_replay(
        _snapshot(timeframe="4h", snapshot_id="four-hour-feature-row"),
        candles=candles,
    )

    assert row is not None, reasons
    assert row["timeframe"] == "4h"
    assert row["trusted_replay_label_base_timeframe"] == "5m"
    assert row["trusted_replay_label_horizon_candle_ids"]["15m"] == (
        candles[LABEL_HORIZON_SLOT["15m"]]["candle_id"]
    )
    assert row["raw_future_return_15m_bps"] == pytest.approx(100.0)


def test_canonical_5m_label_path_gap_fails_closed() -> None:
    candles = _candles()
    del candles[5]

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is None
    assert reasons == ["CANONICAL_5M_LABEL_PATH_GAP"]


def test_canonical_5m_duplicate_close_conflict_fails_closed() -> None:
    candles = _candles()
    conflicting = dict(candles[5])
    conflicting["raw_payload_hash"] = hashlib.sha256(
        b"conflicting-source-payload"
    ).hexdigest()
    conflicting["candle_id"] = canonical_candle_id(conflicting)
    candles.append(conflicting)

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is None
    assert reasons == ["CANONICAL_5M_DUPLICATE_CLOSE_CONFLICT"]


def test_canonical_5m_label_available_after_observation_fails_closed() -> None:
    candles = _candles()
    future_available_ms = int(
        (TRAINING_OBSERVED_AT + timedelta(seconds=1)).timestamp() * 1000
    )
    candles[5]["ingested_at"] = future_available_ms
    candles[5]["available_at"] = future_available_ms

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is None
    assert reasons == [
        "CANONICAL_5M_LABEL_AVAILABLE_AFTER_TRAINING_OBSERVED_AT"
    ]


@pytest.mark.parametrize(
    ("case", "reason"),
    (
        ("wss_backfill_flag", "LABEL_CANDLE_WSS_BACKFILL_STATE_INVALID"),
        ("exchange_case", "LABEL_CANDLE_EXCHANGE_MISMATCH"),
        ("candle_id_whitespace", "LABEL_CANDLE_ID_NOT_CANONICAL"),
        (
            "optional_ohlcv_copy",
            "LABEL_CANDLE_OHLCV_CANONICAL_COPY_MISMATCH",
        ),
    ),
)
def test_frontier_replay_uses_same_strict_canonical_validator(
    case: str,
    reason: str,
) -> None:
    candles = _candles()
    candle = candles[5]
    if case == "wss_backfill_flag":
        candle["is_backfilled"] = True
    elif case == "exchange_case":
        candle["exchange"] = "BINANCE"
        candle["candle_id"] = canonical_candle_id(candle)
    elif case == "candle_id_whitespace":
        candle["candle_id"] = f" {candle['candle_id']} "
    else:
        candle["taker_buy_base_vol"] = 1.0

    row, reasons = _build_replay(_snapshot(), candles=candles)

    assert row is None
    assert reason in reasons


def test_replay_row_preserves_microsecond_decision_lineage_under_v2_contract() -> None:
    exact_decision = "2026-06-22T00:01:00.999600Z"

    row, reasons = _build_replay(
        _snapshot(decision_time=exact_decision),
    )

    assert row is not None, reasons
    assert row["decision_time"] == exact_decision
    assert row["decision_time_est"] == exact_decision
    assert row["decision_time_epoch_us"] % 1_000_000 == 999_600
    assert row["training_observed_at"].endswith(".000000Z")
    assert row["training_observed_at_epoch_us"]
    assert row["trusted_replay_label_candle_contract_version"].endswith(
        "_v2"
    )
    assert row["trusted_replay_label_horizon_lateness_us"]
    assert row["trusted_replay_label_horizon_target_epoch_us"]


@pytest.mark.parametrize("training_observed_at", (None, "2026-06-22T05:00:00"))
def test_training_observation_cutoff_is_explicit_and_timezone_aware(
    training_observed_at: str | None,
) -> None:
    row, reasons = _build_replay(
        _snapshot(),
        training_observed_at=training_observed_at,
    )

    assert row is None
    assert reasons == ["TRAINING_OBSERVED_AT_MISSING_OR_INVALID"]


def test_bootstrap_does_not_claim_checkpoint_specific_temporal_split() -> None:
    items = [
        (f"2026-06-22T00:{minute:02d}:00Z", f"row-{minute}")
        for minute in range(20)
    ]
    items.extend(
        [
            ("2026-06-22T00:19:00Z", "same-clock-a"),
            ("2026-06-22T00:19:00Z", "same-clock-b"),
        ]
    )

    status = build_temporal_split_manifest(items)

    assert status["status"] == "BLOCKED_RUNTIME_CHECKPOINT_BINDING_REQUIRED"
    assert status["authoritative_manifest_published"] is False
    assert status["legacy_v1_manifest_published"] is False
    assert status["static_fractional_split_used"] is False
    assert status["equal_decision_timestamps_partitioned"] is False
    assert "training_window" not in status
    assert "validation_window" not in status
    assert "holdout_window" not in status


def test_bootstrap_quarantines_only_legacy_v1_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "latest"
    output_dir.mkdir(parents=True)
    manifest_path = (
        output_dir / "trusted_replay_train_validation_holdout_manifest.json"
    )
    legacy_payload = {
        "schema_version": "trusted_replay_train_validation_holdout_manifest_v1",
        "training_window": {"rows": 10},
    }
    manifest_path.write_text(json.dumps(legacy_payload), encoding="utf-8")

    quarantined = _quarantine_legacy_v1_manifest(output_dir)

    assert quarantined is not None
    assert not manifest_path.exists()
    assert json.loads(Path(quarantined).read_text(encoding="utf-8")) == (
        legacy_payload
    )

    v2_payload = {
        "schema_version": "trusted_replay_train_validation_holdout_manifest_v2"
    }
    manifest_path.write_text(json.dumps(v2_payload), encoding="utf-8")
    assert _quarantine_legacy_v1_manifest(output_dir) is None
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == v2_payload


def test_snapshot_hash_mismatch_rejected(tmp_path: Path) -> None:
    result = append_snapshot(_snapshot(), root=tmp_path)
    payload = json.loads(result.blob_path.read_text(encoding="utf-8"))
    payload["features"]["close"] = 200.0
    result.blob_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotArchiveError, match="CONTENT_SHA256_MISMATCH"):
        load_snapshot("replay-snapshot-1", root=tmp_path)


def test_archive_only_bootstrap_blocks_without_durable_indexed_5m_labels(
    tmp_path: Path,
) -> None:
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
    assert status["trusted_replay_rows"] == 0
    assert status["trusted_replay_rows_requirement_met"] is False
    assert status["historical_label_source_status"] == (
        "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"
    )
    assert status["replay_rejections_by_reason"] == {
        "DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED": 1
    }
    assert status["same_timeframe_label_fallback_used"] is False
    assert status["mutable_redis_history_used_for_historical_labels"] is False
    published = tmp_path / "goal_state" / "V2_TRUSTED_REPLAY_BOOTSTRAP_PAPER_EXPLORATION_AND_ONLINE_LEARNING_ACTIVATION" / "trusted_replay_dataset_status.json"
    assert json.loads(published.read_text(encoding="utf-8"))[
        "historical_label_source_status"
    ] == "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"


def test_backfill_reads_only_verified_durable_canonical_5m_ranges(
    tmp_path: Path,
) -> None:
    feature_archive_root = tmp_path / "feature-archive"
    _append_archive_series(feature_archive_root, rows=1)
    label_archive_path = tmp_path / "canonical-5m.sqlite3"
    DurableCanonical5mLabelArchive(label_archive_path).append_candles(
        _candles()
    )
    loader = V2HybridTrainerDataLoader(
        trusted_replay_archive_root=feature_archive_root,
        canonical_5m_label_archive_path=label_archive_path,
    )

    examples = loader.load_trusted_replay_examples(
        limit=1,
        backfill=True,
        training_observed_at=TRAINING_OBSERVED_AT,
    )

    assert len(examples) == 1
    trust_row = examples[0].trust_row or {}
    source_lineage = trust_row["source_lineage"]
    assert source_lineage["durable_canonical_5m_label_archive"] is True
    assert source_lineage["durable_canonical_5m_label_path_sha256"]
    assert str(trust_row["trusted_replay_label_candle_source_key"]).startswith(
        f"durable_canonical_5m_label_archive:{label_archive_path}:"
    )
    status = loader.last_trusted_replay_backfill_scan
    assert status["status"] == (
        "VERIFIED_DURABLE_CANONICAL_5M_HISTORICAL_LABELS_LOADED"
    )
    assert status[
        "durable_canonical_5m_label_archive_integrity_verified"
    ] is True
    assert status["durable_canonical_5m_label_ranges_verified"] == 1
    assert status["same_timeframe_label_fallback_used"] is False
    assert status["mutable_redis_history_used_for_historical_labels"] is False


def test_backfill_preserves_cursor_until_durable_label_gap_is_filled(
    tmp_path: Path,
) -> None:
    feature_archive_root = tmp_path / "feature-archive"
    _append_archive_series(feature_archive_root, rows=1)
    label_archive_path = tmp_path / "canonical-5m.sqlite3"
    candles = _candles()
    label_archive = DurableCanonical5mLabelArchive(label_archive_path)
    label_archive.append_candles(candles[:-1])
    loader = V2HybridTrainerDataLoader(
        trusted_replay_archive_root=feature_archive_root,
        canonical_5m_label_archive_path=label_archive_path,
    )

    waiting = loader.load_trusted_replay_examples(
        limit=1,
        backfill=True,
        training_observed_at=TRAINING_OBSERVED_AT,
    )

    assert waiting == []
    waiting_status = loader.last_trusted_replay_backfill_scan
    assert waiting_status["status"] == (
        "WAITING_FOR_DURABLE_CANONICAL_5M_LABEL_COVERAGE_RETRY"
    )
    assert waiting_status["cursor_offset"] == 0
    assert waiting_status[
        "cursor_preserved_for_retryable_archive_coverage"
    ] is True

    label_archive.append_candles([candles[-1]])
    loaded = loader.load_trusted_replay_examples(
        limit=1,
        backfill=True,
        training_observed_at=TRAINING_OBSERVED_AT,
    )

    assert len(loaded) == 1
    assert loader.last_trusted_replay_backfill_scan["cursor_offset"] > 0


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
                "trainer_consumable": True,
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


def test_trusted_replay_loader_streams_snapshots_without_chunk_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    def fake_iter_snapshots_from_offset(
        _root: Path,
        *,
        start_offset: int = 0,
        limit: int | None = None,
    ) -> object:
        assert start_offset == 0
        assert limit is None
        for index in range(3):
            events.append(f"yield:{index}")
            yield index + 1, {
                "snapshot_id": f"stream-{index}",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "decision_time": DECISION_TIME,
                "trainer_consumable": True,
                "large_feature_payload": "x" * 100_000,
            }

    def fake_build_trusted_replay_row(
        snapshot: dict[str, object],
        **_kwargs: object,
    ) -> tuple[None, list[str]]:
        events.append(f"build:{snapshot['snapshot_id']}")
        return None, ["UNIT_REJECTION"]

    monkeypatch.setattr(
        data_loader_mod,
        "iter_snapshots_from_offset",
        fake_iter_snapshots_from_offset,
    )
    monkeypatch.setattr(
        data_loader_mod,
        "build_trusted_replay_row",
        fake_build_trusted_replay_row,
    )
    loader = V2HybridTrainerDataLoader(
        trusted_replay_archive_root=tmp_path,
    )

    examples = loader.load_trusted_replay_examples(
        limit=1,
        training_observed_at=TRAINING_OBSERVED_AT,
    )

    assert examples == []
    assert events == [
        "yield:0",
        "build:stream-0",
        "yield:1",
        "build:stream-1",
        "yield:2",
        "build:stream-2",
    ]
    assert loader.last_trusted_replay_scan[
        "streaming_snapshot_processing"
    ] is True
    assert loader.last_trusted_replay_scan[
        "maximum_resident_snapshot_rows"
    ] == 1


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
    label = target_action_index(row["target_action"])
    assert label is not None
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
    long_row, reasons = _build_replay(_snapshot(snapshot_id="replay-long"))
    assert long_row is not None, reasons
    short_snapshot = _snapshot(snapshot_id="replay-short")
    short_candles = _candles(
        horizon_closes={
            "5m": 99.8,
            "15m": 99.6,
            "1h": 98.7,
            "4h": 95.1,
        }
    )
    short_row, reasons = _build_replay(short_snapshot, candles=short_candles)
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
    row, reasons = _build_replay(_snapshot())

    assert row is not None, reasons
    assert row["uses_expected_move_as_realized_reward"] is False
    assert row["realized_reward_source"] == "counterfactual_target_after_cost_from_finalized_candles"


def test_counterfactual_economics_are_standardized_and_not_exact_close_ledger() -> None:
    row, reasons = _build_replay(_snapshot())

    assert row is not None, reasons
    economics = row["standardized_counterfactual_economics"]
    assert economics["standardized_entry_notional_usd"] == 1.0
    assert economics["long"]["net_pnl_usd"] == pytest.approx(
        economics["long"]["net_pnl_bps"] / 10_000.0
    )
    assert economics["short"]["net_pnl_usd"] == pytest.approx(
        economics["short"]["net_pnl_bps"] / 10_000.0
    )
    assert economics["confidence_exact_close_contract_claimed"] is False
    assert row["confidence_exact_close_contract_eligible"] is False
    assert row["confidence_target_action_not_substituted_from_hindsight"] is True
    assert "ACTUAL_SELECTED_BEHAVIOR_ACTION_MISSING" in row[
        "confidence_exact_close_contract_blockers"
    ]


def test_counterfactual_replay_does_not_weaken_exact_confidence_contract() -> None:
    row, reasons = _build_replay(_snapshot())

    assert row is not None, reasons
    confidence_target = profitability_target_from_trust_row(row)

    assert confidence_target["eligible"] is False
    assert confidence_target["target"] is None
    assert confidence_target["reason"] == "CONFIDENCE_TARGET_LABEL_FINALITY_TIME_UNPROVEN"
