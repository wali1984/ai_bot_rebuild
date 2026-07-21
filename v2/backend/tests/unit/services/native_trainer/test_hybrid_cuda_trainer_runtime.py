from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    CanonicalCandle,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_PUBLISHED,
    append_lifecycle_event,
    archive_behavior_receipt,
    canonical_sha256,
    receipt_lifecycle_status,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    default_archive_path as default_canonical_5m_label_archive_path,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    PROVENANCE_CANONICAL_V3,
    PROVENANCE_LEGACY_V1_IMPORT,
    DurableFeatureSnapshotLedger,
    build_feature_snapshot_record,
    build_source_read_receipt,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    default_ledger_path as default_feature_snapshot_ledger_path,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    data_loader as data_loader_mod,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    runtime as runtime_mod,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    training_sample_identity as training_sample_identity_mod,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    REJECTED_ATTEMPT_LINEAGE,
    checkpoint_stores,
    reconcile_checkpoint_consumption,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    DEFAULT_TIMEFRAMES,
    HybridTrainerConfig,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    PPOTrainingResult,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _checkpoint_promotion_status_fields,
    _trusted_replay_backfill_limit_for_cycle,
    _trusted_replay_load_limit_for_cycle,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (
    OPTIONAL_MISSING_EVIDENCE_SEMANTICS,
    TrainingSampleIdentityError,
    build_checkpoint_sample_inventory,
    checkpoint_inventory_evidence,
    checkpoint_partition_manifest_projection_status,
    prepare_checkpoint_partition_manifest,
    publish_checkpoint_partition_manifest,
    read_published_checkpoint_partition_manifest,
    sample_identity_set_sha256,
    stable_json_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_state import (
    ppo_consumption_update_key,
    training_partition_digest,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    HORIZON_SECONDS,
    build_trusted_replay_row,
    target_action_index,
)


def test_trusted_replay_scan_cap_can_survive_normal_rejections_above_phase_two_floor() -> None:
    assert data_loader_mod.TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE >= 16_384


def _runtime_test_example(symbol: str, timeframe: str, index: int) -> TrainingExample:
    tensor = FeatureTensorRecord(
        tensor_id=f"tensor_{symbol}_{timeframe}",
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=f"feat_{symbol}_{timeframe}",
        values=(float(index),),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )
    return TrainingExample(
        symbol=symbol,
        timeframe=timeframe,
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row={
            "accepted_for_training": True,
            "reject_reasons": [],
            "feature_cutoff": "2026-07-11T00:00:00Z",
            "decision_time": "2026-07-11T00:01:00Z",
            "available_at": "2026-07-11T00:00:30Z",
        },
    )


_IDENTITY_BASE = datetime(2025, 1, 1, tzinfo=UTC)


def _identity_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _identity_source_receipt(
    source_label: str,
    *,
    event: datetime,
    seed: int,
) -> dict[str, object]:
    return build_source_read_receipt(
        source_label=source_label,
        payload_type="CANONICAL_JSON_SOURCE_PAYLOAD",
        payload_sha256=f"{seed:064x}",
        payload_byte_count=64,
        event_time=_identity_utc(event),
        available_at=_identity_utc(event + timedelta(milliseconds=100)),
        consumer_observed_at=_identity_utc(event + timedelta(milliseconds=200)),
        feature_cutoff=_identity_utc(event + timedelta(milliseconds=300)),
        read_locator_type="SQLITE_IMMUTABLE_ROW",
        read_locator=f"fixture.sqlite3/{source_label}/{seed}",
        read_locator_version=f"row:{source_label}:{seed}",
        finality_type=(
            "CLOSED_INTERVAL" if source_label.startswith("closed_") else "VERSIONED_SNAPSHOT"
        ),
        finality_cutoff=_identity_utc(event + timedelta(milliseconds=50)),
        finality_verified_at=_identity_utc(event + timedelta(milliseconds=150)),
        finality_verifier="unit-test-finality-gate",
    )


def _identity_feature_record(
    index: int,
    *,
    decision_minute: int,
    optional_missing: bool = False,
    legacy: bool = False,
    omit_feature: str | None = None,
    tamper_finality_timeframe: str | None = None,
) -> dict[str, object]:
    event = _IDENTITY_BASE + timedelta(minutes=decision_minute, seconds=-2)
    decision = _IDENTITY_BASE + timedelta(minutes=decision_minute)
    timeframe_receipts = {
        timeframe: _identity_source_receipt(
            f"closed_{timeframe}",
            event=event,
            seed=index * 100 + ordinal,
        )
        for ordinal, timeframe in enumerate(DEFAULT_TIMEFRAMES, start=1)
    }
    required_receipt = timeframe_receipts["5m"]
    optional_receipt = _identity_source_receipt(
        "optional_event",
        event=event,
        seed=index * 100 + 99,
    )
    # The ordinary receipt authenticates only the source read. It is not typed
    # negative evidence of absence; missing remains a structural mask claim.
    receipts = [
        *(timeframe_receipts[timeframe] for timeframe in DEFAULT_TIMEFRAMES),
        optional_receipt,
    ]
    timeframe_seconds = {
        "1m": 60,
        "5m": 5 * 60,
        "15m": 15 * 60,
        "1h": 60 * 60,
        "4h": 4 * 60 * 60,
    }
    timeframe_finality: dict[str, dict[str, object]] = {}
    for timeframe in DEFAULT_TIMEFRAMES:
        receipt = timeframe_receipts[timeframe]
        finality = receipt["finality_evidence"]
        assert isinstance(finality, dict)
        timeframe_finality[timeframe] = {
            "timeframe": timeframe,
            "candle_id": f"identity-candle:{timeframe}:{index}",
            "candle_open_time": _identity_utc(
                event - timedelta(seconds=timeframe_seconds[timeframe]) + timedelta(milliseconds=1)
            ),
            "candle_close_time": _identity_utc(event),
            "candle_closed_confirmed": True,
            "source_read_receipt_sha256": receipt["receipt_sha256"],
            "source_label": receipt["source_label"],
            "event_time": receipt["event_time"],
            "available_at": receipt["available_at"],
            "consumer_observed_at": receipt["consumer_observed_at"],
            "feature_cutoff": receipt["feature_cutoff"],
            "finality_cutoff": finality["finality_cutoff"],
            "finality_verified_at": finality["finality_verified_at"],
        }
    if tamper_finality_timeframe is not None:
        timeframe_finality[tamper_finality_timeframe]["candle_closed_confirmed"] = False
    names = [
        "close",
        "fee_bps",
        "spread_bps",
        "expected_slippage_bps",
        "funding_bps",
        "finality_receipt_anchor_1m",
        "finality_receipt_anchor_15m",
        "finality_receipt_anchor_1h",
        "finality_receipt_anchor_4h",
        "last_liq_bps_24h",
    ]
    values = [
        100.0,
        0.1,
        0.1,
        0.1,
        0.0,
        1.0,
        1.0,
        1.0,
        1.0,
        0.0 if optional_missing else float(index + 1),
    ]
    missing_mask = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1 if optional_missing else 0]
    stale_mask = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    availability_mask = [1, 1, 1, 1, 1, 1, 1, 1, 1, 0 if optional_missing else 1]
    source_labels = [
        "closed_5m",
        "closed_5m",
        "closed_5m",
        "closed_5m",
        "closed_5m",
        "closed_1m",
        "closed_15m",
        "closed_1h",
        "closed_4h",
        "optional_event",
    ]
    receipt_bindings = [
        required_receipt["receipt_sha256"],
        required_receipt["receipt_sha256"],
        required_receipt["receipt_sha256"],
        required_receipt["receipt_sha256"],
        required_receipt["receipt_sha256"],
        timeframe_receipts["1m"]["receipt_sha256"],
        timeframe_receipts["15m"]["receipt_sha256"],
        timeframe_receipts["1h"]["receipt_sha256"],
        timeframe_receipts["4h"]["receipt_sha256"],
        optional_receipt["receipt_sha256"],
    ]
    requirements = [
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "REQUIRED",
        "OPTIONAL_EVENT_DEPENDENT",
    ]
    if omit_feature is not None:
        omitted_index = names.index(omit_feature)
        for vector in (
            names,
            values,
            missing_mask,
            stale_mask,
            availability_mask,
            source_labels,
            receipt_bindings,
            requirements,
        ):
            vector.pop(omitted_index)
    return build_feature_snapshot_record(
        provenance_classification=(
            PROVENANCE_LEGACY_V1_IMPORT if legacy else PROVENANCE_CANONICAL_V3
        ),
        legacy_v1_snapshot_id=f"legacy:{index}" if legacy else None,
        symbol="BTCUSDT",
        timeframe="5m",
        feature_snapshot_id=f"feature:identity:{index}",
        tensor_decision_time=_identity_utc(decision),
        temporal_rejection_reasons=[],
        ordered_feature_names=names,
        feature_values=values,
        missing_mask=missing_mask,
        stale_mask=stale_mask,
        source_availability_mask=availability_mask,
        ordered_feature_source_labels=source_labels,
        feature_source_receipt_sha256s=receipt_bindings,
        source_read_receipts=receipts,
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=requirements,
        original_tensor_id=f"tensor:identity:{index}",
        source_lineage_material={
            "lineage_schema": "identity_fixture_v1",
            "ordered_sources": [
                *(f"closed_{timeframe}" for timeframe in DEFAULT_TIMEFRAMES),
                "optional_event",
            ],
            "mtf_snapshot_id": f"mtf:identity:{index}",
            "timeframe_finality": timeframe_finality,
        },
        feature_cutoff=_identity_utc(event + timedelta(seconds=1)),
        masa_feature_cutoff=_identity_utc(event + timedelta(seconds=1, milliseconds=100)),
        ppo_feature_cutoff=_identity_utc(event + timedelta(seconds=1, milliseconds=200)),
        ppo_decision_time=_identity_utc(decision),
        generated_at=_identity_utc(event + timedelta(seconds=1, milliseconds=500)),
    )


def _identity_candle(slot: int) -> dict[str, object]:
    open_time = _IDENTITY_BASE + timedelta(minutes=5 * slot)
    close_time = open_time + timedelta(minutes=5) - timedelta(milliseconds=1)
    available_at = close_time + timedelta(milliseconds=1)
    close_price = 100.0 + slot * 0.1
    return CanonicalCandle(
        symbol="BTCUSDT",
        exchange="binance",
        timeframe="5m",
        candle_open_time=int(open_time.timestamp() * 1_000),
        candle_close_time=int(close_time.timestamp() * 1_000),
        event_time=int(close_time.timestamp() * 1_000),
        ingested_at=int(available_at.timestamp() * 1_000),
        available_at=int(available_at.timestamp() * 1_000),
        is_closed=True,
        source="binance_wss",
        source_sequence_id=f"identity:{slot}",
        raw_payload_hash=hashlib.sha256(f"identity:{slot}".encode()).hexdigest(),
        ohlcv={
            "open": 100.0 + max(0, slot - 1) * 0.1,
            "high": close_price + 0.2,
            "low": 99.8,
            "close": close_price,
            "volume": 1_000.0 + slot,
            "quote_volume": 100_000.0 + slot,
            "num_trades": 100 + slot,
        },
        is_backfilled=False,
        feature_eligible=True,
    ).to_dict()


def _identity_seed_label_archive(
    repo_root: Path,
    *,
    candle_count: int = 49,
) -> str:
    archive = DurableCanonical5mLabelArchive(default_canonical_5m_label_archive_path(repo_root))
    archive.append_candles([_identity_candle(slot) for slot in range(candle_count)])
    return _identity_utc(datetime.now(UTC))


def _identity_tensor(record: dict[str, object]) -> FeatureTensorRecord:
    envelope = record["frozen_envelope"]
    assert isinstance(envelope, dict)
    names = tuple(str(value) for value in envelope["ordered_feature_names"])
    missing = tuple(int(value) for value in envelope["missing_mask"])
    stale = tuple(int(value) for value in envelope["stale_mask"])
    availability = tuple(int(value) for value in envelope["source_availability_mask"])
    return FeatureTensorRecord(
        tensor_id=str(envelope["original_tensor_id"]),
        symbol=str(envelope["symbol"]),
        timeframe=str(envelope["timeframe"]),
        feature_snapshot_id=str(envelope["feature_snapshot_id"]),
        values=tuple(float(value) for value in envelope["feature_values"]),
        missing_mask=missing,
        stale_mask=stale,
        source_availability=availability,
        feature_names=names,
        source_labels=tuple(str(value) for value in envelope["ordered_feature_source_labels"]),
        missing_feature_names=tuple(
            name for name, flag in zip(names, missing, strict=True) if flag == 1
        ),
        stale_feature_names=tuple(
            name for name, flag in zip(names, stale, strict=True) if flag == 1
        ),
        data_coverage_percent=(100.0 * sum(availability) / len(availability)),
        source_availability_vector=availability,
        decision_time=str(envelope["tensor_decision_time"]),
        source_lineage_hash=str(envelope["source_lineage_sha256"]),
        temporal_rejection_reasons=tuple(
            str(value) for value in envelope["temporal_rejection_reasons"]
        ),
    )


def _identity_example(
    record: dict[str, object],
    *,
    repo_root: Path,
    observation: str,
    row_source: str,
) -> TrainingExample:
    envelope = record["frozen_envelope"]
    assert isinstance(envelope, dict)
    decision = str(envelope["ppo_decision_time"])
    tensor = _identity_tensor(record)
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(repo_root))
    items = ledger.query_fixed_cutoff(
        decision_time_cutoff=observation,
        training_observed_at=observation,
        limit=32,
    )
    item = next(
        item
        for item in items
        if dict(item.record["frozen_envelope"])["original_tensor_id"] == tensor.tensor_id
    )
    snapshot, _authenticated_envelope = (
        training_sample_identity_mod._feature_snapshot_for_label_rebuild(  # noqa: SLF001
            item
        )
    )
    archive = DurableCanonical5mLabelArchive(default_canonical_5m_label_archive_path(repo_root))
    integrity = archive.verify_integrity()
    rows, proof = archive.verified_label_path(
        symbol="BTCUSDT",
        decision_time=decision,
        training_observed_at=observation,
        horizon_seconds=HORIZON_SECONDS["4h"],
        archive_integrity_proof=integrity,
        require_receipt_committed_by_observation=True,
    )
    assert rows is not None
    label_path_sha256 = str(proof["label_path_sha256"])
    source_key = f"durable_canonical_5m_label_archive:{archive.path}:" f"{label_path_sha256}"
    replay_row, reasons = build_trusted_replay_row(
        snapshot,
        candles=rows,
        training_observed_at=observation,
        label_candle_source_key=source_key,
    )
    assert replay_row is not None, reasons
    trust_row = {
        **replay_row,
        "row_source": row_source,
        "trusted_replay_row": True,
        "historical_replay_row": True,
        "source_lineage": {
            "durable_canonical_5m_label_archive": True,
            "durable_canonical_5m_label_path_sha256": label_path_sha256,
        },
    }
    action = target_action_index(replay_row["target_action"])
    assert action is not None
    return TrainingExample(
        symbol=str(envelope["symbol"]),
        timeframe=str(envelope["timeframe"]),
        tensor=tensor,
        label_action_index=action,
        label_expected_move_after_cost_bps=float(replay_row["future_return_after_cost_bps"]),
        payload_keys=(source_key,),
        row_classification="TRAINABLE",
        trust_row=trust_row,
        decision_time=decision,
        label_available_at=str(replay_row["label_available_at"]),
    )


def test_checkpoint_sample_inventory_empty_set_is_deterministic(
    tmp_path: Path,
) -> None:
    inventory = build_checkpoint_sample_inventory(
        training_examples=[],
        validation_examples=[],
        repo_root=tmp_path,
        training_observed_at=_identity_utc(datetime.now(UTC)),
    )

    assert inventory["training_sample_identity_sha256s"] == []
    assert inventory["training_sample_identity_inventory_complete"] is True
    assert inventory["training_sample_identity_set_sha256"] == (sample_identity_set_sha256([]))
    assert inventory["sample_inventory_mutable_redis_used"] is False


def test_checkpoint_sample_inventory_authenticates_replay_and_optional_missing(
    tmp_path: Path,
) -> None:
    fresh_record = _identity_feature_record(1, decision_minute=2)
    replay_record = _identity_feature_record(
        2,
        decision_minute=3,
        optional_missing=True,
    )
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path))
    ledger.append_snapshots([fresh_record, replay_record])
    observation = _identity_seed_label_archive(tmp_path)
    fresh = _identity_example(
        fresh_record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    replay = _identity_example(
        replay_record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )

    inventory = build_checkpoint_sample_inventory(
        training_examples=[fresh, replay],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    assert inventory["training_sample_count"] == 2
    assert len(inventory["training_sample_identity_sha256s"]) == 2
    assert inventory["sample_inventory_durable_v3_only"] is True
    assert replay.tensor.missing_mask[-1] == 1
    assert sum(replay.tensor.missing_mask) == 1
    assert replay.tensor.missing_feature_names == ("last_liq_bps_24h",)
    assert inventory["optional_missing_evidence_semantics"] == (OPTIONAL_MISSING_EVIDENCE_SEMANTICS)
    assert inventory["optional_missing_typed_negative_receipts_verified"] is False
    assert inventory["optional_missing_observed_zero_claimed"] is False


def test_checkpoint_sample_inventory_is_stable_across_later_valid_appends(
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(31, decision_minute=2)
    ledger = DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(tmp_path)
    )
    ledger.append_snapshot(record)
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    planned = build_checkpoint_sample_inventory(
        training_examples=[example],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    # These are legitimate immutable suffix appends, but neither receipt was
    # observable at the cycle-start cutoff used for the exact optimizer row.
    ledger.append_snapshot(_identity_feature_record(32, decision_minute=3))
    label_archive = DurableCanonical5mLabelArchive(
        default_canonical_5m_label_archive_path(tmp_path)
    )
    label_archive.append_candles([_identity_candle(49)])

    actual = build_checkpoint_sample_inventory(
        training_examples=[example],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    assert runtime_mod._sample_inventory_comparison_reasons(planned, actual) == ()
    assert planned["sample_inventory_feature_ledger_high_water"] == actual[
        "sample_inventory_feature_ledger_high_water"
    ]
    assert planned["sample_inventory_label_archive_high_water"] == actual[
        "sample_inventory_label_archive_high_water"
    ]
    assert planned["training_sample_provenance_bindings_sha256"] == actual[
        "training_sample_provenance_bindings_sha256"
    ]
    assert (
        actual["sample_inventory_feature_ledger_integrity"]["verified_records"]
        == planned["sample_inventory_feature_ledger_integrity"]["verified_records"]
        + 1
    )
    assert (
        actual["sample_inventory_label_archive_integrity"]["verified_rows"]
        == planned["sample_inventory_label_archive_integrity"]["verified_rows"]
        + 1
    )


def test_feature_high_water_uses_verified_head_frontier_at_equal_clock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixed_clock = "2026-07-21T12:00:00.000000Z"
    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger.utc_now",
        lambda: fixed_clock,
    )
    ledger = DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(tmp_path)
    )
    ledger.append_snapshot(_identity_feature_record(33, decision_minute=2))
    old_report = ledger.verify_integrity_streaming()
    observation = datetime(2026, 7, 21, 12, 0, 0, 1, tzinfo=UTC)
    old_high_water = (
        training_sample_identity_mod.feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=old_report,
            observation_cutoff=observation,
            scan_limit=8,
        )
    )

    # This append is physically later but deliberately has the same durable
    # clock.  The old integrity frontier must exclude it from the old prefix.
    ledger.append_snapshot(_identity_feature_record(34, decision_minute=3))
    stale_report_reproduction = (
        training_sample_identity_mod.feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=old_report,
            observation_cutoff=observation,
            scan_limit=8,
        )
    )
    current_high_water = (
        training_sample_identity_mod.feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=ledger.verify_integrity_streaming(),
            observation_cutoff=observation,
            scan_limit=8,
        )
    )

    assert stale_report_reproduction == old_high_water
    assert current_high_water != old_high_water
    assert current_high_water["verified_records"] == 2


def test_label_high_water_uses_authenticated_monotonic_receipt_frontier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixed_clock = "2026-07-21T12:00:00.000Z"
    # Deliberately reverse lexical UUID order.  UUID sorting must never be able
    # to insert a later valid receipt ahead of an already authenticated prefix.
    transaction_ids = iter(("f" * 32, "0" * 32))
    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive.utc_now",
        lambda: fixed_clock,
    )
    monkeypatch.setattr(
        "v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive.uuid.uuid4",
        lambda: SimpleNamespace(hex=next(transaction_ids)),
    )
    archive = DurableCanonical5mLabelArchive(
        default_canonical_5m_label_archive_path(tmp_path)
    )
    archive.append_candles([_identity_candle(slot) for slot in range(49)])
    old_integrity = archive.verify_integrity()
    assert old_integrity["append_receipt_ordering_verified"] is True
    observation = datetime(2026, 7, 21, 12, 0, 0, 500, tzinfo=UTC)
    old_high_water = (
        training_sample_identity_mod.label_archive_fixed_observation_high_water(
            archive=archive,
            integrity=old_integrity,
            observation_cutoff=observation,
            scan_limit=64,
        )
    )

    archive.append_candles([_identity_candle(49)])
    stale_report_reproduction = (
        training_sample_identity_mod.label_archive_fixed_observation_high_water(
            archive=archive,
            integrity=old_integrity,
            observation_cutoff=observation,
            scan_limit=64,
        )
    )
    current_integrity = archive.verify_integrity()
    current_same_cutoff = (
        training_sample_identity_mod.label_archive_fixed_observation_high_water(
            archive=archive,
            integrity=current_integrity,
            observation_cutoff=observation,
            scan_limit=64,
        )
    )
    later_high_water = (
        training_sample_identity_mod.label_archive_fixed_observation_high_water(
            archive=archive,
            integrity=current_integrity,
            observation_cutoff=datetime(
                2026,
                7,
                21,
                12,
                0,
                0,
                1_500,
                tzinfo=UTC,
            ),
            scan_limit=64,
        )
    )

    assert stale_report_reproduction == old_high_water
    assert current_same_cutoff == old_high_water
    assert current_integrity["append_receipt_cumulative_state_verified"] is True
    assert current_integrity["postcommit_clock_causality_verified"] is True
    assert current_integrity["verified_last_commit_prepared_at"] == (
        "2026-07-21T12:00:00.001Z"
    )
    assert later_high_water["verified_rows"] == 50


def test_fixed_prefix_remains_verifiable_after_suffix_crosses_scan_limit(
    tmp_path: Path,
) -> None:
    ledger = DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(tmp_path)
    )
    ledger.append_snapshot(_identity_feature_record(35, decision_minute=2))
    observation = datetime.now(UTC)
    ledger.append_snapshot(_identity_feature_record(36, decision_minute=3))

    feature_high_water = (
        training_sample_identity_mod.feature_ledger_fixed_observation_high_water(
            ledger=ledger,
            report=ledger.verify_integrity_streaming(),
            observation_cutoff=observation,
            scan_limit=1,
        )
    )

    archive = DurableCanonical5mLabelArchive(
        default_canonical_5m_label_archive_path(tmp_path)
    )
    archive.append_candles([_identity_candle(slot) for slot in range(49)])
    label_observation = datetime.now(UTC)
    archive.append_candles([_identity_candle(49)])
    label_high_water = (
        training_sample_identity_mod.label_archive_fixed_observation_high_water(
            archive=archive,
            integrity=archive.verify_integrity(),
            observation_cutoff=label_observation,
            scan_limit=49,
        )
    )

    assert feature_high_water["verified_records"] == 1
    assert feature_high_water["verified_append_receipts"] == 1
    assert label_high_water["verified_rows"] == 49
    assert label_high_water["verified_append_receipts"] == 1


def test_checkpoint_sample_inventory_rejects_unsupported_label_lane(
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(16, decision_minute=2)
    DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path)).append_snapshot(
        record
    )
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="fresh_closed_trade",
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="TRAINING_SAMPLE_LABEL_LANE_UNSUPPORTED:fresh_closed_trade",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[example],
            repo_root=tmp_path,
            training_observed_at=observation,
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        ("action_label", "TRAINING_SAMPLE_ACTION_LABEL_MISMATCH"),
        ("after_cost_label", "TRAINING_SAMPLE_AFTER_COST_LABEL_MISMATCH"),
        (
            "trust_action",
            "TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISMATCH:target_action",
        ),
        (
            "trust_missing",
            "TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISSING:cost_evidence_hash",
        ),
        ("timing", "TRAINING_SAMPLE_LABEL_AVAILABLE_AT_MISMATCH"),
        (
            "cost",
            "TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISMATCH:round_trip_cost_bps",
        ),
        ("path", "TRAINING_SAMPLE_DURABLE_LABEL_SOURCE_LINEAGE_MISMATCH"),
        (
            "archive_source_path",
            "TRAINING_SAMPLE_AUTHENTICATED_TRUST_FIELD_MISMATCH:"
            "trusted_replay_label_candle_source_key",
        ),
    ),
)
def test_checkpoint_sample_identity_rejects_label_or_trust_tampering(
    tmp_path: Path,
    mutation: str,
    reason: str,
) -> None:
    record = _identity_feature_record(15, decision_minute=2)
    DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path)).append_snapshot(
        record
    )
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    assert example.trust_row is not None
    trust_row = dict(example.trust_row)
    if mutation == "action_label":
        mutated = replace(
            example,
            label_action_index=(example.label_action_index + 1) % 3,
        )
    elif mutation == "after_cost_label":
        mutated = replace(
            example,
            label_expected_move_after_cost_bps=(example.label_expected_move_after_cost_bps + 1.0),
        )
    elif mutation == "trust_action":
        trust_row["target_action"] = "short"
        mutated = replace(example, trust_row=trust_row)
    elif mutation == "trust_missing":
        trust_row.pop("cost_evidence_hash")
        mutated = replace(example, trust_row=trust_row)
    elif mutation == "timing":
        assert example.label_available_at is not None
        changed_timing = _identity_utc(
            datetime.fromisoformat(example.label_available_at.replace("Z", "+00:00"))
            + timedelta(minutes=1)
        )
        trust_row["label_available_at"] = changed_timing
        trust_row["outcome_available_at"] = changed_timing
        mutated = replace(
            example,
            trust_row=trust_row,
            label_available_at=changed_timing,
        )
    elif mutation == "cost":
        trust_row["round_trip_cost_bps"] = float(trust_row["round_trip_cost_bps"]) + 1.0
        mutated = replace(example, trust_row=trust_row)
    elif mutation == "path":
        trust_row["source_lineage"] = {
            **dict(trust_row["source_lineage"]),
            "durable_canonical_5m_label_path_sha256": "f" * 64,
        }
        mutated = replace(example, trust_row=trust_row)
    else:
        trust_row["trusted_replay_label_candle_source_key"] = "tampered:path"
        mutated = replace(
            example,
            trust_row=trust_row,
        )

    build_checkpoint_sample_inventory(
        training_examples=[example],
        repo_root=tmp_path,
        training_observed_at=observation,
    )
    with pytest.raises(TrainingSampleIdentityError, match=reason):
        build_checkpoint_sample_inventory(
            training_examples=[mutated],
            repo_root=tmp_path,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_rejects_duplicate_and_tampered_actual_rows(
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(3, decision_minute=2)
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path))
    ledger.append_snapshot(record)
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="OPTIMIZER_TRAINING_SAMPLE_IDENTITY_DUPLICATE",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[example, example],
            repo_root=tmp_path,
            training_observed_at=observation,
        )

    tampered_tensor = replace(
        example.tensor,
        values=tuple(999.0 + index for index, _ in enumerate(example.tensor.values)),
    )
    tampered = replace(example, tensor=tampered_tensor)
    with pytest.raises(
        TrainingSampleIdentityError,
        match="TRAINING_SAMPLE_FEATURE_VALUES_MISMATCH",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[tampered],
            repo_root=tmp_path,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_rejects_ledger_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(4, decision_minute=2)
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path))
    ledger.append_snapshot(record)
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    original_verify = DurableFeatureSnapshotLedger.verify_integrity_streaming
    calls = 0

    def changing_integrity(self: DurableFeatureSnapshotLedger):
        nonlocal calls
        calls += 1
        report = original_verify(self)
        if calls == 2:
            return replace(report, archive_chain_sha256="f" * 64)
        return report

    monkeypatch.setattr(
        DurableFeatureSnapshotLedger,
        "verify_integrity_streaming",
        changing_integrity,
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="FEATURE_LEDGER_HIGH_WATER_INTEGRITY_FRONTIER_MISMATCH",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[example],
            repo_root=tmp_path,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_rejects_trust_cost_without_durable_cost_input(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "cost-authority"
    authority_record = _identity_feature_record(17, decision_minute=2)
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(authority_root)
    ).append_snapshot(authority_record)
    authority_observation = _identity_seed_label_archive(authority_root)
    authority_example = _identity_example(
        authority_record,
        repo_root=authority_root,
        observation=authority_observation,
        row_source="trusted_replay_archive",
    )

    missing_cost_root = tmp_path / "missing-cost"
    missing_cost_record = _identity_feature_record(
        17,
        decision_minute=2,
        omit_feature="fee_bps",
    )
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(missing_cost_root)
    ).append_snapshot(missing_cost_record)
    observation = _identity_seed_label_archive(missing_cost_root)
    claimed_example = replace(
        authority_example,
        tensor=_identity_tensor(missing_cost_record),
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="TRAINING_SAMPLE_DURABLE_LABEL_REBUILD_INVALID:COST_EVIDENCE_FEE_MISSING",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[claimed_example],
            repo_root=missing_cost_root,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_rejects_unfinished_higher_timeframe(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "finality-authority"
    authority_record = _identity_feature_record(21, decision_minute=2)
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(authority_root)
    ).append_snapshot(authority_record)
    authority_observation = _identity_seed_label_archive(authority_root)
    authority_example = _identity_example(
        authority_record,
        repo_root=authority_root,
        observation=authority_observation,
        row_source="trusted_replay_archive",
    )

    unfinished_root = tmp_path / "unfinished-4h"
    unfinished_record = _identity_feature_record(
        21,
        decision_minute=2,
        tamper_finality_timeframe="4h",
    )
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(unfinished_root)
    ).append_snapshot(unfinished_record)
    observation = _identity_seed_label_archive(unfinished_root)
    claimed_example = replace(
        authority_example,
        tensor=_identity_tensor(unfinished_record),
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="TRAINING_SAMPLE_TIMEFRAME_FINALITY_INVALID:" "TIMEFRAME_FINALITY_4H_NOT_CLOSED",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[claimed_example],
            repo_root=unfinished_root,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_rejects_missing_canonical_label_path(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "path-authority"
    record = _identity_feature_record(18, decision_minute=2)
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(authority_root)
    ).append_snapshot(record)
    authority_observation = _identity_seed_label_archive(authority_root)
    example = _identity_example(
        record,
        repo_root=authority_root,
        observation=authority_observation,
        row_source="trusted_replay_archive",
    )

    missing_path_root = tmp_path / "missing-path"
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(missing_path_root)
    ).append_snapshot(record)
    observation = _identity_seed_label_archive(
        missing_path_root,
        candle_count=48,
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="TRAINING_SAMPLE_DURABLE_LABEL_PATH_UNVERIFIED:"
        ".*LABEL_ARCHIVE_RANGE_ROW_COUNT_MISMATCH",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[example],
            repo_root=missing_path_root,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_rejects_tampered_label_archive(
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(19, decision_minute=2)
    DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path)).append_snapshot(
        record
    )
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    archive_path = default_canonical_5m_label_archive_path(tmp_path)
    with sqlite3.connect(archive_path) as connection:
        connection.execute("DROP TRIGGER canonical_5m_candles_no_update")
        connection.execute("UPDATE canonical_5m_candles SET payload_json = '{}' WHERE sequence = 1")

    with pytest.raises(
        TrainingSampleIdentityError,
        match="LABEL_ARCHIVE_INTEGRITY_UNVERIFIED",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[example],
            repo_root=tmp_path,
            training_observed_at=observation,
        )


def test_checkpoint_sample_inventory_accepts_valid_label_suffix_during_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(20, decision_minute=2)
    DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path)).append_snapshot(
        record
    )
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    original = DurableCanonical5mLabelArchive.verified_label_path
    raced = False

    def append_after_path(self: DurableCanonical5mLabelArchive, **kwargs):
        nonlocal raced
        result = original(self, **kwargs)
        if not raced:
            raced = True
            self.append_candles([_identity_candle(49)])
        return result

    monkeypatch.setattr(
        DurableCanonical5mLabelArchive,
        "verified_label_path",
        append_after_path,
    )

    inventory = build_checkpoint_sample_inventory(
        training_examples=[example],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    assert raced is True
    assert inventory["training_sample_count"] == 1
    assert inventory["sample_inventory_label_archive_high_water"]["verified_rows"] == 49
    assert DurableCanonical5mLabelArchive(
        default_canonical_5m_label_archive_path(tmp_path)
    ).verify_integrity()["verified_rows"] == 50


def test_checkpoint_sample_inventory_rejects_legacy_and_truncated_scan(
    tmp_path: Path,
) -> None:
    legacy_root = tmp_path / "legacy"
    legacy_record = _identity_feature_record(
        12,
        decision_minute=2,
        legacy=True,
    )
    DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(legacy_root)).append_snapshot(
        legacy_record
    )
    legacy_observation = _identity_seed_label_archive(legacy_root)
    authority_root = tmp_path / "legacy-example-authority"
    canonical_record = _identity_feature_record(12, decision_minute=2)
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(authority_root)
    ).append_snapshot(canonical_record)
    authority_observation = _identity_seed_label_archive(authority_root)
    legacy_example = _identity_example(
        canonical_record,
        repo_root=authority_root,
        observation=authority_observation,
        row_source="trusted_replay_archive",
    )

    with pytest.raises(
        TrainingSampleIdentityError,
        match="TRAINING_SAMPLE_NOT_IN_DURABLE_V3_LEDGER",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[legacy_example],
            repo_root=legacy_root,
            training_observed_at=legacy_observation,
        )

    truncated_root = tmp_path / "truncated"
    records = [
        _identity_feature_record(13, decision_minute=2),
        _identity_feature_record(14, decision_minute=3),
    ]
    DurableFeatureSnapshotLedger(
        default_feature_snapshot_ledger_path(truncated_root)
    ).append_snapshots(records)
    truncated_observation = _identity_seed_label_archive(truncated_root)
    truncated_example = _identity_example(
        records[0],
        repo_root=truncated_root,
        observation=truncated_observation,
        row_source="trusted_replay_archive",
    )
    with pytest.raises(
        TrainingSampleIdentityError,
        match="FEATURE_LEDGER_SCAN_TRUNCATED_NO_PREFIX_ADMISSION",
    ):
        build_checkpoint_sample_inventory(
            training_examples=[truncated_example],
            repo_root=truncated_root,
            training_observed_at=truncated_observation,
            scan_limit=1,
        )


def test_partial_actual_optimizer_inventory_is_not_exact_match(
    tmp_path: Path,
) -> None:
    records = [
        _identity_feature_record(5, decision_minute=2),
        _identity_feature_record(6, decision_minute=3),
    ]
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path))
    ledger.append_snapshots(records)
    observation = _identity_seed_label_archive(tmp_path)
    examples = [
        _identity_example(
            record,
            repo_root=tmp_path,
            observation=observation,
            row_source="trusted_replay_archive",
        )
        for record in records
    ]
    planned = build_checkpoint_sample_inventory(
        training_examples=examples,
        repo_root=tmp_path,
        training_observed_at=observation,
    )
    actual = build_checkpoint_sample_inventory(
        training_examples=examples[:1],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    reasons = runtime_mod._sample_inventory_comparison_reasons(planned, actual)

    assert "ACTUAL_SAMPLE_INVENTORY_TRAINING_SAMPLE_COUNT_MISMATCH" in reasons
    assert "ACTUAL_SAMPLE_INVENTORY_TRAINING_SAMPLE_IDENTITY_SET_SHA256_MISMATCH" in reasons


def test_actual_inventory_comparison_binds_cycle_observation_cutoff() -> None:
    planned = {"sample_inventory_training_observed_at": "2026-07-21T12:00:00.000000Z"}
    actual = {"sample_inventory_training_observed_at": "2026-07-21T12:00:00.000001Z"}

    reasons = runtime_mod._sample_inventory_comparison_reasons(planned, actual)

    assert "ACTUAL_SAMPLE_INVENTORY_SAMPLE_INVENTORY_TRAINING_OBSERVED_AT_MISMATCH" in reasons


def test_actual_inventory_comparison_binds_both_authenticated_high_waters() -> None:
    planned = {
        "sample_inventory_feature_ledger_high_water": {"high_water_sha256": "a" * 64},
        "sample_inventory_label_archive_high_water": {"high_water_sha256": "b" * 64},
    }
    actual = {
        "sample_inventory_feature_ledger_high_water": {"high_water_sha256": "c" * 64},
        "sample_inventory_label_archive_high_water": {"high_water_sha256": "d" * 64},
    }

    reasons = runtime_mod._sample_inventory_comparison_reasons(planned, actual)

    assert (
        "ACTUAL_SAMPLE_INVENTORY_SAMPLE_INVENTORY_FEATURE_LEDGER_HIGH_WATER_MISMATCH"
        in reasons
    )
    assert (
        "ACTUAL_SAMPLE_INVENTORY_SAMPLE_INVENTORY_LABEL_ARCHIVE_HIGH_WATER_MISMATCH"
        in reasons
    )


def test_checkpoint_inventory_evidence_digest_excludes_working_objects(
    tmp_path: Path,
) -> None:
    record = _identity_feature_record(7, decision_minute=2)
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path))
    ledger.append_snapshot(record)
    observation = _identity_seed_label_archive(tmp_path)
    example = _identity_example(
        record,
        repo_root=tmp_path,
        observation=observation,
        row_source="trusted_replay_archive",
    )
    inventory = build_checkpoint_sample_inventory(
        training_examples=[example],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    evidence = checkpoint_inventory_evidence(inventory)

    assert all(not key.startswith("_") for key in evidence)
    assert stable_json_sha256(evidence) == stable_json_sha256(
        checkpoint_inventory_evidence(inventory)
    )


def test_checkpoint_partition_manifest_keeps_equal_timestamp_holdout_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    records = [
        _identity_feature_record(8, decision_minute=2),
        _identity_feature_record(9, decision_minute=3),
        _identity_feature_record(10, decision_minute=4),
        _identity_feature_record(11, decision_minute=4),
    ]
    ledger = DurableFeatureSnapshotLedger(default_feature_snapshot_ledger_path(tmp_path))
    ledger.append_snapshots(records)
    observation = _identity_seed_label_archive(tmp_path)
    examples = [
        _identity_example(
            record,
            repo_root=tmp_path,
            observation=observation,
            row_source="trusted_replay_archive",
        )
        for record in records
    ]
    inventory = build_checkpoint_sample_inventory(
        training_examples=[examples[0]],
        validation_examples=[examples[1]],
        repo_root=tmp_path,
        training_observed_at=observation,
    )

    manifest = prepare_checkpoint_partition_manifest(
        inventory=inventory,
        training_partition_digest=training_partition_digest([]),
        repo_root=tmp_path,
        generated_utc=_identity_utc(datetime.now(UTC)),
    )

    assert manifest["schema_version"] == ("trusted_replay_train_validation_holdout_manifest_v2")
    assert manifest["training_window"]["rows"] == 1
    assert manifest["validation_window"]["rows"] == 1
    assert manifest["holdout_window"]["rows"] == 2
    assert (
        manifest["holdout_window"]["start_decision_time"]
        == (manifest["holdout_window"]["end_decision_time"])
    )
    assert manifest["partition_evidence"]["training_holdout_disjoint"] is True
    unsigned_manifest = {
        str(key): value for key, value in manifest.items() if str(key) != "manifest_payload_sha256"
    }
    unsigned_manifest["checkpoint_binding"] = {
        "checkpoint_id": "unit-serving-checkpoint",
        "checkpoint_evidence_digest": "a" * 64,
        "training_partition_digest": manifest["partition_evidence"]["training_partition_digest"],
        "training_sample_identity_set_sha256": manifest["partition_evidence"][
            "training_sample_identity_set_sha256"
        ],
        "validation_sample_identity_set_sha256": manifest["partition_evidence"][
            "validation_sample_identity_set_sha256"
        ],
        "training_feature_identity_set_sha256": manifest["partition_evidence"][
            "training_feature_identity_set_sha256"
        ],
        "validation_feature_identity_set_sha256": manifest["partition_evidence"][
            "validation_feature_identity_set_sha256"
        ],
    }
    manifest = {
        **unsigned_manifest,
        "manifest_payload_sha256": stable_json_sha256(unsigned_manifest),
    }
    publication_paths = publish_checkpoint_partition_manifest(
        manifest=manifest,
        repo_root=tmp_path,
    )
    assert len(publication_paths) == 3
    assert all(
        json.loads(Path(path).read_text(encoding="utf-8")) == manifest for path in publication_paths
    )
    assert read_published_checkpoint_partition_manifest(repo_root=tmp_path) == manifest

    tampered_projection = dict(manifest)
    tampered_projection["checkpoint_binding"] = {
        **manifest["checkpoint_binding"],
        "checkpoint_id": "tampered-serving-checkpoint",
    }
    tampered_unsigned = {
        str(key): value
        for key, value in tampered_projection.items()
        if str(key) != "manifest_payload_sha256"
    }
    tampered_projection["manifest_payload_sha256"] = stable_json_sha256(tampered_unsigned)
    Path(publication_paths[0]).write_text(
        json.dumps(tampered_projection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert read_published_checkpoint_partition_manifest(repo_root=tmp_path) == manifest
    projection_status = checkpoint_partition_manifest_projection_status(repo_root=tmp_path)
    assert projection_status["all_secondary_projections_match_primary"] is False
    assert projection_status["secondary_projections"][0]["mismatch_reason"] == (
        "HOLDOUT_MANIFEST_PROJECTION_READBACK_MISMATCH"
    )

    next_unsigned = {
        str(key): value for key, value in manifest.items() if str(key) != "manifest_payload_sha256"
    }
    next_unsigned["checkpoint_binding"] = {
        **manifest["checkpoint_binding"],
        "checkpoint_id": "next-unit-serving-checkpoint",
    }
    next_manifest = {
        **next_unsigned,
        "manifest_payload_sha256": stable_json_sha256(next_unsigned),
    }
    real_atomic_write = training_sample_identity_mod._atomic_write_json  # noqa: SLF001
    for crash_after_write in (1, 2):
        publish_checkpoint_partition_manifest(
            manifest=manifest,
            repo_root=tmp_path,
        )
        writes = 0

        def crash_after_secondary(
            path: Path,
            payload,
            crash_after_write: int = crash_after_write,
        ) -> None:
            nonlocal writes
            real_atomic_write(path, payload)
            writes += 1
            if writes == crash_after_write:
                raise RuntimeError("simulated-publication-crash")

        with monkeypatch.context() as scoped_patch:
            scoped_patch.setattr(
                training_sample_identity_mod,
                "_atomic_write_json",
                crash_after_secondary,
            )
            with pytest.raises(RuntimeError, match="simulated-publication-crash"):
                publish_checkpoint_partition_manifest(
                    manifest=next_manifest,
                    repo_root=tmp_path,
                )

        assert read_published_checkpoint_partition_manifest(repo_root=tmp_path) == manifest
        crash_status = checkpoint_partition_manifest_projection_status(repo_root=tmp_path)
        assert crash_status["all_secondary_projections_match_primary"] is False


def test_parallel_prediction_grid_loader_preserves_pair_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_build_example(
        self: V2HybridTrainerDataLoader,
        *,
        symbol: str,
        timeframe: str,
        snapshot_fast_path: bool = False,
    ) -> TrainingExample:
        del self
        calls.append((symbol, timeframe, snapshot_fast_path))
        return _runtime_test_example(symbol, timeframe, len(calls))

    monkeypatch.setattr(V2HybridTrainerDataLoader, "build_example", fake_build_example)
    loader = V2HybridTrainerDataLoader()

    examples = loader.load_prediction_grid_examples(
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1m", "5m"),
        max_workers=2,
    )

    assert [(row.symbol, row.timeframe) for row in examples] == [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "5m"),
        ("ETHUSDT", "1m"),
        ("ETHUSDT", "5m"),
    ]
    assert all(snapshot_fast_path is True for *_pair, snapshot_fast_path in calls)
    assert loader.last_prediction_grid_load["parallel_loader_used"] is True
    assert loader.last_prediction_grid_load["parallel_workers"] == 2


def test_resident_replay_load_limit_uses_replay_buffer_capacity() -> None:
    replay_buffer = deque(maxlen=4096)

    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=replay_buffer,
    )

    assert limit == 4096


def test_nonresident_replay_load_limit_uses_requested_rows() -> None:
    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=None,
    )

    assert limit == 32768


@pytest.mark.parametrize(
    ("max_rows", "frontier_rows", "buffered_rows", "expected"),
    (
        (512, 0, 0, 512),
        (512, 100, 0, 412),
        (512, 0, 16_000, 384),
        (512, 100, 16_000, 284),
        (16_384, 0, 0, 16_384),
        (0, 0, 0, 0),
    ),
)
def test_trusted_replay_backfill_is_bounded_by_cycle_and_buffer_capacity(
    max_rows: int,
    frontier_rows: int,
    buffered_rows: int,
    expected: int,
) -> None:
    replay_buffer = deque(range(buffered_rows), maxlen=16_384)

    limit = _trusted_replay_backfill_limit_for_cycle(
        max_training_rows_per_cycle=max_rows,
        replay_buffer=replay_buffer,
        frontier_rows=frontier_rows,
    )

    assert limit == expected


def _runtime_promotion_metrics(**overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "validation_split_pit_safe": True,
        "validation_split_reason": "PIT_SAFE_CHRONOLOGICAL_PURGED_SPLIT",
        "validation_split_actual_training_rows": 1,
        "validation_split_actual_validation_rows": 2,
        "validation_split_temporal_overlap": False,
        "validation_split_label_overlap": False,
        "validation_policy_edge_status": "VALID",
        "validation_policy_edge_evidence_valid": True,
        "validation_policy_edge_after_cost_bps": -1.0,
        "validation_policy_edge_standard_error_bps": 1.0,
        "validation_policy_edge_lower_confidence_bound_bps": -2.0,
        "validation_policy_edge_uncertainty_multiplier": 1.0,
        "validation_policy_edge_rows_evaluated": 2,
    }
    metrics.update(overrides)
    return metrics


def test_runtime_suppresses_rejected_candidate_forward_and_backtest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    example = _runtime_test_example("BTCUSDT", "1m", 1)
    training_observation_cutoffs: list[str] = []
    inventory_observation_cutoffs: list[str] = []
    trainer_input_counts: list[int] = []

    def fake_checkpoint_sample_inventory(**kwargs):
        cutoff = kwargs["training_observed_at"]
        inventory_observation_cutoffs.append(cutoff)
        return build_checkpoint_sample_inventory(
            training_examples=[],
            validation_examples=[],
            repo_root=tmp_path,
            training_observed_at=cutoff,
        )

    class FakeLoader:
        def __init__(self, **_kwargs) -> None:
            self.last_prediction_grid_load = {}
            self.last_trusted_replay_scan = {}
            self.last_trusted_replay_backfill_scan = {}

        def load_prediction_grid_examples(self, **_kwargs):
            return [example]

        def load_training_examples(self, **kwargs):
            training_observation_cutoffs.append(kwargs["training_observed_at"])
            return [example]

        def load_trusted_replay_examples(self, **kwargs):
            training_observation_cutoffs.append(kwargs["training_observed_at"])
            return []

    class FakeModel:
        forward_calls = 0

        def __init__(self, *, input_dim: int) -> None:
            self.input_dim = input_dim
            self.model_id = "model_rejected_candidate"
            self.device = "cpu"
            self.cuda_active = False
            self.torch_available = False
            self._fallback_weights = [0.1, -0.1]

        @property
        def confidence_calibration_state(self) -> dict[str, object]:
            return {"fitted": False, "reason": "TEST_UNFITTED"}

        def forward(self, _tensor):
            type(self).forward_calls += 1
            raise AssertionError("a rejected candidate must never run inference")

        def model_tensors_device_verified(self) -> bool:
            return True

        def architecture_status(self) -> dict[str, object]:
            return {"test_model": True}

    class FakeCheckpointManager:
        def __init__(self, _model_dir) -> None:
            pass

        def load_latest_weights(self, _model) -> dict[str, object]:
            return {
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST",
            }

        def latest_manifest(self, **_kwargs):
            return None

        def write_checkpoint(self, **_kwargs):
            raise AssertionError("a rejected candidate must never be written")

        def status(self, checkpoint) -> dict[str, object]:
            return {
                "checkpoint_id": checkpoint.checkpoint_id,
                "weight_file_path": checkpoint.weight_file_path,
            }

    class FakeTrainer:
        def __init__(self, **kwargs) -> None:
            training_observation_cutoffs.append(kwargs["training_observed_at"])

        def plan_exact_ppo_optimizer_attempts(self, examples, **_kwargs):
            return {
                "optimizer_attempt_descriptors": [],
                "eligible_examples": [],
                "ordered_update_keys": [],
                "ordered_update_keys_complete": True,
                "ordered_update_keys_unique": True,
                "duplicate_update_keys": [],
                "available_rows": list(examples),
                "trusted_rows": list(examples),
                "all_ppo_rows": [],
                "ppo_rows": [],
                "outcome_rows": list(examples),
                "learnable_rows": list(examples),
                "selected_rows_for_split": list(examples),
                "train_rows": list(examples),
                "validation_rows": [],
                "learning_mode": "outcome_supervised",
                "target_batch_size": 1,
                "tuned_batch_size": 1,
                "rejection_metrics": {},
                "split_metrics": {},
            }

        def train(self, examples, **_kwargs) -> PPOTrainingResult:
            trainer_input_counts.append(len(examples))
            return PPOTrainingResult(
                status="TEST_REJECTED_CANDIDATE",
                device="cpu",
                cuda_active=False,
                cuda_claim_verified=True,
                gpu_name=None,
                vram_allocated_mb=None,
                batch_size=1,
                training_steps=1,
                train_rows=1,
                validation_rows=2,
                loss_before=1.0,
                loss_after=0.9,
                action_distribution={"hold": 1},
                metrics=_runtime_promotion_metrics(
                    validation_rows_evaluated=2,
                    validation_split_actual_validation_rows=2,
                    validation_policy_edge_rows_evaluated=2,
                    validation_policy_edge_after_cost_bps=-1.0,
                    validation_policy_edge_lower_confidence_bound_bps=-2.0,
                    optimizer_steps_this_cycle=1,
                    parameter_hash_before="before",
                    parameter_hash_after="after",
                    weight_delta_norm=1.0,
                    training_trusted_rows=1,
                ),
            )

    class FakeEnv:
        def __init__(self, _examples) -> None:
            pass

        def reset(self):
            return [0.0], {"reset": True}

        def step(self, _action):
            return [0.0], 0.0, False, False, {"step": True}

    class FakePublisher:
        def __init__(self, **_kwargs) -> None:
            pass

        def publish_prediction(self, _payload):
            raise AssertionError("rejected candidate prediction publication attempted")

        def publish_lineage(self, **_kwargs):
            raise AssertionError("rejected candidate lineage publication attempted")

    monkeypatch.setattr(runtime_mod, "V2HybridTrainerDataLoader", FakeLoader)
    monkeypatch.setattr(runtime_mod, "V2HybridPolicyModel", FakeModel)
    monkeypatch.setattr(runtime_mod, "V2HybridCheckpointManager", FakeCheckpointManager)
    monkeypatch.setattr(runtime_mod, "V2HybridPPOTrainer", FakeTrainer)
    monkeypatch.setattr(runtime_mod, "V2PaperShadowHybridEnv", FakeEnv)
    monkeypatch.setattr(runtime_mod, "V2HybridPredictionPublisher", FakePublisher)
    monkeypatch.setattr(
        runtime_mod,
        "build_checkpoint_sample_inventory",
        fake_checkpoint_sample_inventory,
    )
    monkeypatch.setattr(
        runtime_mod,
        "run_policy_archive_backtest",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("rejected candidate backtest attempted")
        ),
    )
    monkeypatch.setattr(
        runtime_mod,
        "run_parallel_env_rollout_proof",
        lambda *_args, **_kwargs: SimpleNamespace(to_jsonable=lambda: {}),
    )

    result = runtime_mod.run_hybrid_trainer_cycle(
        config=HybridTrainerConfig(
            symbols=("BTCUSDT",),
            timeframes=("1m",),
            model_dir=tmp_path / ".local_models/rejected_candidate_test",
            max_training_rows_per_cycle=1,
            batch_size=1,
        ),
        publish=False,
    )

    assert FakeModel.forward_calls == 0
    assert result.predictions == []
    assert result.lineages == []
    assert result.status["prediction_suppressed_count"] == 1
    assert result.status["prediction_publication_status"] == (
        "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
    )
    assert result.status["model_serving_allowed"] is False
    assert result.metrics["cuda_cpu_resource_utilization"]["policy_backtest"]["status"] == (
        "SUPPRESSED_REJECTED_CANDIDATE_NO_VERIFIED_RESTORE"
    )
    assert len(training_observation_cutoffs) == 3
    assert len(set(training_observation_cutoffs)) == 1
    assert len(inventory_observation_cutoffs) == 2
    assert inventory_observation_cutoffs[0] == inventory_observation_cutoffs[1]
    assert inventory_observation_cutoffs[0] == training_observation_cutoffs[0]
    assert trainer_input_counts == [1]
    assert (
        datetime.fromisoformat(training_observation_cutoffs[0].replace("Z", "+00:00")).tzinfo
        is not None
    )


def test_decision_clock_is_strictly_after_exact_cost_observation() -> None:
    observed = datetime.now(UTC) + timedelta(seconds=5)

    decision = runtime_mod._causal_decision_time_after_cost_observation(
        {
            "exact_cost_provenance": {
                "consumer_observed_at": observed.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                )
            }
        }
    )

    parsed = datetime.fromisoformat(decision.replace("Z", "+00:00"))
    assert parsed > observed


class _TerminalAttemptLedger:
    def __init__(self, attempt: dict[str, object]) -> None:
        self.attempt = dict(attempt)
        self.sync_sequence = 0
        self.archive_binding: dict[str, object] | None = None

    def attempt_rows(
        self,
        update_keys: list[str] | None = None,
    ) -> list[dict[str, object]]:
        if update_keys is not None and update_keys != [self.attempt["update_key"]]:
            return []
        return [dict(self.attempt)]

    def archive_sync_status(self) -> dict[str, object]:
        return {
            "archive_sync_integrity_verified": True,
            "archive_sync_rejection_reasons": [],
            "activation_sequence": 1,
            "sync_sequence": self.sync_sequence,
            "sync_chain_hash": (
                str(self.attempt["chain_hash"]) if self.sync_sequence else "0" * 64
            ),
            "ledger_row_count": 1,
            "legacy_terminal_attempts_not_archive_bound": 0,
            "unsynced_terminal_attempts": 1 - self.sync_sequence,
        }

    def unsynced_attempt_rows(self) -> list[dict[str, object]]:
        return [dict(self.attempt)] if self.sync_sequence == 0 else []

    def archive_sync_bindings(self) -> list[dict[str, object]]:
        return [] if self.archive_binding is None else [dict(self.archive_binding)]

    def mark_archive_synced(
        self,
        *,
        sequence: int,
        chain_hash: str,
        receipt_hash: str,
        trainer_consumed_event_hash: str,
    ) -> dict[str, object]:
        assert sequence == 1
        assert chain_hash == self.attempt["chain_hash"]
        assert receipt_hash == self.attempt["receipt_hash"]
        self.archive_binding = {
            **self.attempt,
            "ledger_chain_hash": chain_hash,
            "trainer_consumed_event_hash": trainer_consumed_event_hash,
        }
        self.sync_sequence = 1
        return {**self.archive_sync_status(), "watermark_advanced": True}


def _archived_terminal_attempt(
    root: Path,
    *,
    finalized_digest: str = "e" * 64,
) -> tuple[dict[str, object], str]:
    receipt: dict[str, object] = {
        "schema_version": "unit_exact_receipt_v1",
        "prediction_id": "prediction-sync-1",
        "symbol": "BTCUSDT",
        "paper_only": True,
        "routes_to_live": False,
    }
    receipt["receipt_hash"] = canonical_sha256(receipt)
    receipt_hash = str(receipt["receipt_hash"])
    parent_fingerprint = "d" * 64
    update_key = ppo_consumption_update_key(
        receipt_hash=receipt_hash,
        finalized_outcome_digest=finalized_digest,
        parent_policy_fingerprint=parent_fingerprint,
    )
    archive_behavior_receipt(receipt, root=root)
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_PUBLISHED,
        binding={
            "prediction_id": "prediction-sync-1",
            "decision_time": "2026-07-18T00:00:00Z",
        },
        root=root,
        recorded_at="2026-07-18T00:00:00Z",
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_ENTRY_ACCEPTED,
        binding={
            "paper_fill_id": "fill-sync-1",
            "decision_time": "2026-07-18T00:00:00Z",
            "entry_time": "2026-07-18T00:01:00Z",
        },
        root=root,
        recorded_at="2026-07-18T00:01:00Z",
    )
    append_lifecycle_event(
        receipt_hash=receipt_hash,
        event_type=EVENT_OUTCOME_FINALIZED,
        binding={
            "finalized_outcome_id": "outcome-sync-1",
            "finalized_outcome_digest": finalized_digest,
            "ppo_consumption_update_key": update_key,
            "outcome_available_at": "2026-07-18T00:02:00Z",
        },
        root=root,
        recorded_at="2026-07-18T00:02:00Z",
    )
    return (
        {
            "sequence": 1,
            "update_key": update_key,
            "receipt_hash": receipt_hash,
            "finalized_outcome_digest": finalized_digest,
            "parent_policy_fingerprint": parent_fingerprint,
            "child_policy_fingerprint": "f" * 64,
            "disposition": "NON_SERVING_CANDIDATE_PERSISTED",
            "checkpoint_id": "checkpoint-sync-1",
            "recorded_utc": "2026-07-18T00:03:00Z",
            "chain_hash": "a" * 64,
        },
        receipt_hash,
    )


def test_terminal_ledger_attempt_advances_watermark_and_skips_historical_rescan(
    tmp_path: Path,
) -> None:
    attempt, receipt_hash = _archived_terminal_attempt(tmp_path)
    ledger = _TerminalAttemptLedger(attempt)

    first = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
    )
    second = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
        update_keys=[str(attempt["update_key"])],
    )

    assert first["trainer_consumed_events_appended"] == 1
    assert first["archive_sync_after"]["sync_sequence"] == 1
    assert second["ledger_attempts_checked"] == 0
    assert second["trainer_consumed_events_already_present"] == 0
    status = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert status["trainer_consumed_durable"] is True
    assert status["retention_required"] is False
    consumed = status["event_bindings"]["TRAINER_CONSUMED"]
    assert consumed["ppo_consumption_update_key"] == attempt["update_key"]
    assert consumed["ledger_disposition"] == attempt["disposition"]
    assert consumed["finalized_outcome_digest"] == attempt["finalized_outcome_digest"]


def test_synced_archive_event_deletion_revokes_watermark_readiness(
    tmp_path: Path,
) -> None:
    attempt, _receipt_hash = _archived_terminal_attempt(tmp_path)
    ledger = _TerminalAttemptLedger(attempt)
    first = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
    )
    # Resolve the event named by the ledger's exact per-sequence binding and
    # delete it after the watermark has already advanced.
    bound_event_hash = str(ledger.archive_sync_bindings()[0]["trainer_consumed_event_hash"])
    paths = list(tmp_path.rglob(f"{bound_event_hash}.json"))
    assert len(paths) == 1
    assert first["archive_sync_after"]["archive_event_bindings_verified"] is True
    paths[0].unlink()

    with pytest.raises(
        RuntimeError,
        match="durable_receipt_consumption_watermark_invalid",
    ):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=ledger,
            archive_root=tmp_path,
        )


def test_terminal_consumption_retries_existing_event_after_pre_watermark_crash(
    tmp_path: Path,
) -> None:
    attempt, receipt_hash = _archived_terminal_attempt(tmp_path)

    class _CrashAfterArchiveEventLedger(_TerminalAttemptLedger):
        crash_once = True

        def mark_archive_synced(
            self,
            *,
            sequence: int,
            chain_hash: str,
            receipt_hash: str,
            trainer_consumed_event_hash: str,
        ) -> dict[str, object]:
            if self.crash_once:
                self.crash_once = False
                raise RuntimeError("simulated_crash_before_watermark")
            return super().mark_archive_synced(
                sequence=sequence,
                chain_hash=chain_hash,
                receipt_hash=receipt_hash,
                trainer_consumed_event_hash=trainer_consumed_event_hash,
            )

    ledger = _CrashAfterArchiveEventLedger(attempt)

    with pytest.raises(
        RuntimeError,
        match="durable_receipt_consumption_watermark_advance_failed",
    ):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=ledger,
            archive_root=tmp_path,
        )

    after_crash = receipt_lifecycle_status(receipt_hash, root=tmp_path)
    assert after_crash["trainer_consumed_durable"] is True
    assert ledger.sync_sequence == 0

    retried = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=ledger,
        archive_root=tmp_path,
    )

    assert retried["trainer_consumed_events_appended"] == 0
    assert retried["trainer_consumed_events_already_present"] == 1
    assert retried["archive_sync_after"]["sync_sequence"] == 1


def test_startup_repairs_checkpoint_and_archive_crash_windows_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove both post-optimizer restart repairs with real durable stores."""

    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0")
    archive_root = tmp_path / "behavior_receipts"
    model_dir = tmp_path / ".local_models" / "crash_window_models"
    archived_attempt, receipt_hash = _archived_terminal_attempt(archive_root)
    descriptor = {
        field: archived_attempt[field]
        for field in (
            "update_key",
            "receipt_hash",
            "finalized_outcome_digest",
            "parent_policy_fingerprint",
        )
    }
    update_key = str(descriptor["update_key"])
    partition_digest = training_partition_digest([update_key])
    dead_owner = "00000000-0000-0000-0000-000000000000:999999999:0"

    before_crash = checkpoint_stores(model_dir)
    claim = before_crash.ledger.claim_attempts(
        attempts=[descriptor],
        owner_id=dead_owner,
    )
    assert claim["claimed_update_keys"] == [update_key]
    before_crash.ledger.mark_optimizer_started(
        owner_id=dead_owner,
        update_keys=[update_key],
        partition_digest=partition_digest,
    )
    model = V2HybridPolicyModel(input_dim=4, seed=701)
    artifact = before_crash.rejected_attempt.write_checkpoint(
        model=model,
        input_dim=4,
        device=model.device,
        cuda_active=model.cuda_active,
        lineage_kind=REJECTED_ATTEMPT_LINEAGE,
        parent_checkpoint_id=None,
        parent_policy_fingerprint=str(descriptor["parent_policy_fingerprint"]),
        consumed_ppo_update_keys=(update_key,),
        training_partition_digest=partition_digest,
        checkpoint_evidence={
            "checkpoint_role": REJECTED_ATTEMPT_LINEAGE,
            "ledger_disposition": "REJECTED_TRAINING_ATTEMPT_PERSISTED",
            "candidate_progress_decision": {
                "candidate_progress_allowed": False,
            },
            "serving_promotion_decision": {
                "checkpoint_promotion_allowed": False,
            },
        },
    )
    assert before_crash.ledger.attempt_rows() == []
    assert (
        receipt_lifecycle_status(receipt_hash, root=archive_root)["trainer_consumed_durable"]
        is False
    )

    # Simulated crash after the child checkpoint's atomic write but before the
    # terminal ledger commit. Startup discovers the dead fenced claim in the
    # verified artifact and commits exactly one terminal disposition.
    after_checkpoint_restart = checkpoint_stores(model_dir)
    reconciliation = reconcile_checkpoint_consumption(after_checkpoint_restart)
    assert reconciliation["verified_checkpoint_reconciled_attempts"] == 1
    assert reconciliation["ambiguous_optimizer_attempts_consumed"] == 0
    rows = after_checkpoint_restart.ledger.attempt_rows([update_key])
    assert len(rows) == 1
    terminal = rows[0]
    assert terminal["disposition"] == "REJECTED_TRAINING_ATTEMPT_PERSISTED"
    assert terminal["checkpoint_id"] == artifact.checkpoint_id
    assert terminal["checkpoint_path"] == artifact.weight_file_path
    assert terminal["checkpoint_sha256"] == artifact.weight_file_sha256
    assert terminal["child_policy_fingerprint"] == artifact.model_parameter_fingerprint
    assert terminal["training_partition_digest"] == partition_digest
    assert (
        receipt_lifecycle_status(receipt_hash, root=archive_root)["trainer_consumed_durable"]
        is False
    )

    # Simulated second crash after the terminal ledger commit but before its
    # archive event. The next startup mirrors the exact ledger binding.
    after_ledger_restart = checkpoint_stores(model_dir)
    archive_repair = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=after_ledger_restart.ledger,
        archive_root=archive_root,
    )
    assert archive_repair["trainer_consumed_events_appended"] == 1
    assert archive_repair["archive_sync_after"]["sync_sequence"] == 1
    lifecycle = receipt_lifecycle_status(receipt_hash, root=archive_root)
    assert lifecycle["event_count"] == 4
    assert lifecycle["trainer_consumed_durable"] is True
    assert lifecycle["retention_required"] is False
    consumed = lifecycle["event_bindings"]["TRAINER_CONSUMED"]
    assert consumed["ppo_consumption_update_key"] == update_key
    assert consumed["ledger_sequence"] == terminal["sequence"]
    assert consumed["ledger_chain_hash"] == terminal["chain_hash"]
    assert consumed["ledger_disposition"] == terminal["disposition"]
    assert consumed["checkpoint_id"] == artifact.checkpoint_id
    assert consumed["child_policy_fingerprint"] == terminal["child_policy_fingerprint"]
    assert consumed["finalized_outcome_digest"] == terminal["finalized_outcome_digest"]
    assert consumed["ledger_recorded_utc"] == terminal["recorded_utc"]

    # A further restart is idempotent, and the terminal row fences the same
    # optimizer input permanently instead of admitting a replay.
    final_restart = checkpoint_stores(model_dir)
    repeated_reconciliation = reconcile_checkpoint_consumption(final_restart)
    repeated_sync = runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
        ledger=final_restart.ledger,
        archive_root=archive_root,
    )
    replay_claim = final_restart.ledger.claim_attempts(
        attempts=[descriptor],
        owner_id=final_restart.ledger.process_owner_id(),
    )
    assert repeated_reconciliation["verified_checkpoint_reconciled_attempts"] == 0
    assert repeated_sync["ledger_attempts_checked"] == 0
    assert final_restart.ledger.attempt_rows([update_key]) == [terminal]
    assert replay_claim["claimed_update_keys"] == []
    assert replay_claim["unavailable_update_keys"] == [update_key]
    assert receipt_lifecycle_status(receipt_hash, root=archive_root)["event_count"] == 4


def test_consumption_sync_fails_closed_when_archive_is_missing(tmp_path: Path) -> None:
    attempt, _receipt_hash = _archived_terminal_attempt(tmp_path / "source")

    with pytest.raises(RuntimeError, match="archive_invalid"):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=_TerminalAttemptLedger(attempt),
            archive_root=tmp_path / "missing",
        )


def test_consumption_sync_rejects_finalized_digest_binding_tamper(
    tmp_path: Path,
) -> None:
    attempt, _receipt_hash = _archived_terminal_attempt(tmp_path)
    attempt["finalized_outcome_digest"] = "b" * 64
    attempt["update_key"] = ppo_consumption_update_key(
        receipt_hash=str(attempt["receipt_hash"]),
        finalized_outcome_digest=str(attempt["finalized_outcome_digest"]),
        parent_policy_fingerprint=str(attempt["parent_policy_fingerprint"]),
    )

    with pytest.raises(RuntimeError, match="finalized_binding_invalid"):
        runtime_mod._sync_durable_receipt_consumption(  # noqa: SLF001
            ledger=_TerminalAttemptLedger(attempt),
            archive_root=tmp_path,
        )


def test_exact_claim_contract_rejects_cpu_fallback_key_echo_without_ppo() -> None:
    update_key = "a" * 64
    attempt = {"update_key": update_key}
    fallback_metrics = {
        "ppo_consumed_update_keys": [update_key],
        "ppo_consumed_update_keys_complete": True,
        "ppo_consumed_update_keys_ordered": True,
        "ppo_consumed_update_keys_unique": True,
        "ppo_objective_used": False,
        "ppo_rows_consumed": 0,
        "ppo_rows_available_but_optimizer_unavailable": 1,
        "ppo_clipped_surrogate_rows": 0,
        "optimizer_steps_this_cycle": 1,
    }

    assert (
        runtime_mod._exact_ppo_optimizer_contract_valid(  # noqa: SLF001
            metrics=fallback_metrics,
            optimizer_attempts=[attempt],
            ordered_update_keys=[update_key],
        )
        is False
    )


def test_checkpoint_promotion_status_fields_surface_rejection_streak() -> None:
    fields = _checkpoint_promotion_status_fields(
        {
            "checkpoint_promotion_guard_active": True,
            "checkpoint_promotion_allowed": False,
            "checkpoint_promotion_rejected": True,
            "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
            "overfit_gap_warning_advisory": None,
            "prior_promotion_rejection_streak": 2,
            "promotion_rejection_streak_after": 0,
            "max_promotion_rejection_streak": 3,
            "forced_promote_after_rejection_streak": 3,
        }
    )

    assert fields == {
        "pit_edge_promotion_gate_active": None,
        "mandatory_pit_edge_gate_passed": None,
        "checkpoint_promotion_guard_active": True,
        "checkpoint_promotion_allowed": False,
        "checkpoint_promotion_rejected": True,
        "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
        "overfit_gap_warning_advisory": None,
        "prior_promotion_rejection_streak": 2,
        "promotion_rejection_streak_after": 0,
        "max_promotion_rejection_streak": 3,
        "forced_promote_after_rejection_streak": 3,
        "forced_promote_after_rejection_streak_blocked": None,
        "forced_promote_block_reason": None,
        "hard_promotion_rejection_reason": None,
        "pit_edge_hard_rejection_reason": None,
        "force_promote_after_rejection_streak_enabled": None,
        "validation_split_pit_safe": None,
        "validation_split_reason": None,
        "validation_policy_edge_status": None,
        "validation_policy_edge_after_cost_bps": None,
        "validation_policy_edge_lower_confidence_bound_bps": None,
        "validation_policy_edge_rows_evaluated": None,
        "model_serving_allowed": None,
        "model_serving_source": None,
        "rejected_candidate_serving_suppressed": None,
        "model_serving_suppression_reason": None,
    }
