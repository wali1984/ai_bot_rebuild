from __future__ import annotations

import hashlib
import inspect
import json
import struct
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    runtime_feature_snapshot_ledger_bridge as bridge_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
)
from v2.backend.app.services.native_trainer.runtime_feature_snapshot_ledger_bridge import (
    DIRECT_LATEST_CANDLE_FEATURES,
    RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS,
    RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION,
    RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS,
    RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS,
    RuntimeFeatureSnapshotLedgerBridgeError,
    append_unwired_runtime_feature_snapshot_quarantine,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_atomic_receipt_adapter as capture_harness,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_runtime_feature_publication_receipt as publication_harness,
)

_BASE_MS = 1_700_000_000_000
_ACTIVE_SELECTION_SCHEMA = "v2_feature_ohlcv_consumer_selection_v1"
_ACTIVE_SELECTION_KEYS = frozenset(
    {
        "schema_version",
        "selection_mode",
        "selected_source_keys",
        "legacy_raw_key_considered",
        "closed_key",
        "raw_key_row_count",
        "closed_key_row_count",
        "selected_row_count",
        "consumer_observation_cutoff_ms",
        "consumer_observation_clock_source",
        "expected_latest_finalized_close_time",
        "atomic_source_read_succeeded",
        "atomic_batch_id",
        "atomic_batch_material_json",
        "atomic_batch_material_sha256",
        "atomic_server_observed_at",
        "exact_payload_sha256",
        "exact_payload_byte_count",
        "exact_source_schema_validated",
        "entire_contiguous_suffix_bound",
        "selected_source_start_index",
        "selected_source_end_index_exclusive",
        "selected_candle_ids",
        "selected_first_candle_id",
        "selected_latest_candle_id",
        "selected_identity_storage",
        "selected_candle_id_chain_sha256",
        "selected_rows_material_sha256",
        "source_gap_indices",
        "source_gap_missing_interval_counts",
        "selected_source_provenance_counts",
        "selected_backfilled_row_count",
        "binding_selection_material_json",
        "binding_selection_sha256",
        "consumer_selection_material_json",
        "consumer_selection_sha256",
        "selection_material_retained_in_snapshot",
        "selection_rejection_reasons",
        "durable_source_receipt_emitted",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "live_execution_authorized",
    }
)


def _clock_after(value: str, *, milliseconds: int) -> str:
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    return (
        (parsed + timedelta(milliseconds=milliseconds))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _clock_from_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1_000, tz=UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _snapshot_id(snapshot_without_id: dict[str, Any]) -> str:
    material = json.dumps(snapshot_without_id, sort_keys=True).encode()
    return "v2_fsnap_" + hashlib.sha256(material).hexdigest()


def _active_selection(capture: object) -> dict[str, object]:
    binding = capture.full_window_binding
    selected_rows = capture.validated_window.rows[
        binding.selected_source_start_index : binding.selected_source_end_index_exclusive
    ]
    selected_rows_sha256 = _canonical_sha256([asdict(row) for row in selected_rows])
    provenance_counts = {
        source: sum(row.source == source for row in selected_rows)
        for source in ("binance_rest", "binance_wss")
        if any(row.source == source for row in selected_rows)
    }
    consumer_material = {
        "schema_version": _ACTIVE_SELECTION_SCHEMA,
        "source_key": capture.source_key,
        "atomic_batch_id": capture.atomic_batch_id,
        "atomic_batch_material_sha256": capture.atomic_batch_material_sha256,
        "exact_payload_sha256": capture.full_source_payload_address.payload_sha256,
        "exact_payload_byte_count": (capture.full_source_payload_address.payload_byte_count),
        "consumer_observation_cutoff_ms": capture.consumer_observed_at_ms,
        "expected_latest_finalized_close_time": (binding.expected_latest_finalized_close_time),
        "binding_selection_sha256": binding.selection_sha256,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (binding.selected_source_end_index_exclusive),
        "selected_row_count": binding.selected_row_count,
        "selected_candle_ids": list(binding.selected_candle_ids),
        "selected_candle_id_chain_sha256": (binding.selected_candle_id_chain_sha256),
        "selected_rows_material_sha256": selected_rows_sha256,
        "selected_raw_payload_hashes": [row.raw_payload_hash for row in selected_rows],
        "selected_source_provenance": [
            {
                "candle_id": row.candle_id,
                "source": row.source,
                "is_backfilled": row.is_backfilled,
                "source_sequence_id": row.source_sequence_id,
                "raw_payload_hash": row.raw_payload_hash,
            }
            for row in selected_rows
        ],
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }
    return {
        "schema_version": _ACTIVE_SELECTION_SCHEMA,
        "selection_mode": ("ATOMIC_CANONICAL_CLOSED_FULL_CONTIGUOUS_SUFFIX_BOUND"),
        "selected_source_keys": [capture.source_key],
        "legacy_raw_key_considered": False,
        "closed_key": capture.source_key,
        "raw_key_row_count": 0,
        "closed_key_row_count": capture.validated_window.row_count,
        "selected_row_count": binding.selected_row_count,
        "consumer_observation_cutoff_ms": capture.consumer_observed_at_ms,
        "consumer_observation_clock_source": "LOCAL_CLOCK_AFTER_ATOMIC_RESPONSE",
        "expected_latest_finalized_close_time": (binding.expected_latest_finalized_close_time),
        "atomic_source_read_succeeded": True,
        "atomic_batch_id": capture.atomic_batch_id,
        "atomic_batch_material_json": None,
        "atomic_batch_material_sha256": capture.atomic_batch_material_sha256,
        "atomic_server_observed_at": capture.atomic_server_observed_at,
        "exact_payload_sha256": capture.full_source_payload_address.payload_sha256,
        "exact_payload_byte_count": (capture.full_source_payload_address.payload_byte_count),
        "exact_source_schema_validated": True,
        "entire_contiguous_suffix_bound": True,
        "selected_source_start_index": binding.selected_source_start_index,
        "selected_source_end_index_exclusive": (binding.selected_source_end_index_exclusive),
        "selected_candle_ids": None,
        "selected_first_candle_id": binding.selected_candle_ids[0],
        "selected_latest_candle_id": binding.selected_candle_ids[-1],
        "selected_identity_storage": "HASH_CHAIN_AND_BOUNDARIES_ONLY",
        "selected_candle_id_chain_sha256": (binding.selected_candle_id_chain_sha256),
        "selected_rows_material_sha256": selected_rows_sha256,
        "source_gap_indices": list(binding.gap_indices),
        "source_gap_missing_interval_counts": list(binding.gap_missing_interval_counts),
        "selected_source_provenance_counts": provenance_counts,
        "selected_backfilled_row_count": sum(row.is_backfilled for row in selected_rows),
        "binding_selection_material_json": None,
        "binding_selection_sha256": binding.selection_sha256,
        "consumer_selection_material_json": None,
        "consumer_selection_sha256": _canonical_sha256(consumer_material),
        "selection_material_retained_in_snapshot": False,
        "selection_rejection_reasons": [],
        "durable_source_receipt_emitted": False,
        "feature_publication_receipt_emitted": False,
        "consumer_eligible": False,
        "trainer_admission_granted": False,
        "live_execution_authorized": False,
    }


def _snapshot_payload(
    capture: object,
    *,
    direct_overrides: dict[str, float] | None = None,
    selection_overrides: dict[str, object] | None = None,
    top_level_overrides: dict[str, object] | None = None,
) -> str:
    selected = capture.selected_candles
    latest_capture = selected[-1]
    latest = capture.validated_window.rows[latest_capture.source_index]
    features = {
        slot.feature_name: float(slot.ordinal + 1) for slot in FEATURE_SOURCE_REGISTRY_V4.slots
    }
    features.update(
        {
            "quote_volume": latest.quote_volume,
            "volume": latest.volume,
            "open": latest.open,
            "high": latest.high,
            "low": latest.low,
            "close": latest.close,
            "num_trades": latest.num_trades,
            "taker_buy_base_vol": latest.taker_buy_base_vol,
            "taker_buy_quote_vol": latest.taker_buy_quote_vol,
            "ohlcv_close": latest.close,
            "ohlcv_volume": latest.volume,
        }
    )
    if direct_overrides:
        features.update(direct_overrides)
    selection = _active_selection(capture)
    if selection_overrides:
        selection.update(selection_overrides)
    generated_at = _clock_after(
        latest_capture.source_read_receipt.receipt["consumer_observed_at"],
        milliseconds=25,
    )
    snapshot: dict[str, object] = {
        "schema_version": "v2_native_feature_snapshot_v2",
        "worker_id": "v2_feature_pipeline_native_loop",
        "symbol": capture.validated_window.symbol,
        "timeframe": capture.validated_window.timeframe,
        "features": features,
        "feature_cutoff": _clock_from_ms(latest.candle_close_time),
        "candle_closed_confirmed": True,
        "latest_candle_temporally_valid": True,
        "exact_source_clock_valid": True,
        "latest_finalized_candle_available_at_decision": True,
        "trainer_consumable": False,
        "valid_for_prediction": False,
        "valid_for_paper": False,
        "event_time": _clock_from_ms(latest.event_time),
        "ingested_at": _clock_from_ms(latest.ingested_at),
        "source_available_at": _clock_from_ms(latest.available_at),
        "source_observation_time": _clock_from_ms(capture.consumer_observed_at_ms),
        "expected_latest_finalized_candle_close_time": _clock_from_ms(
            capture.full_window_binding.expected_latest_finalized_close_time
        ),
        "generated_at": generated_at,
        "source_ohlcv_key": capture.source_key,
        "source_ohlcv_keys": [capture.source_key],
        "ohlcv_selection_mode": selection["selection_mode"],
        "ohlcv_raw_row_count": selection["raw_key_row_count"],
        "ohlcv_closed_key_row_count": selection["closed_key_row_count"],
        "ohlcv_selected_row_count": selection["selected_row_count"],
        "ohlcv_consumer_selection": selection,
    }
    if top_level_overrides:
        snapshot.update(top_level_overrides)
    snapshot["feature_snapshot_id"] = _snapshot_id(snapshot)
    return json.dumps(snapshot)


@dataclass(frozen=True)
class _Harness:
    payload: str
    capture: object
    publication: object
    ledger: DurableFeatureSnapshotLedger


def _harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    direct_overrides: dict[str, float] | None = None,
    selection_overrides: dict[str, object] | None = None,
    top_level_overrides: dict[str, object] | None = None,
) -> _Harness:
    monkeypatch.setattr(capture_harness, "BASE_MS", _BASE_MS)
    monkeypatch.setattr(capture_harness, "REDIS_TIME", (1_700_010_000, 123_456))
    capture_root = tmp_path / "capture"
    capture_root.mkdir()
    capture = capture_harness._capture(capture_root)[0]
    payload = _snapshot_payload(
        capture,
        direct_overrides=direct_overrides,
        selection_overrides=selection_overrides,
        top_level_overrides=top_level_overrides,
    )
    generated_at = json.loads(payload)["generated_at"]
    generated = datetime.fromisoformat(generated_at[:-1] + "+00:00")
    redis_client = publication_harness._FakeRedis()
    redis_client.clock_us = int(generated.timestamp() * 1_000_000) + 25_000
    publication = publication_harness._publish(redis_client, payload)
    return _Harness(
        payload=payload,
        capture=capture,
        publication=publication,
        ledger=DurableFeatureSnapshotLedger(tmp_path / "ledger.sqlite3"),
    )


def _append(harness: _Harness):
    return append_unwired_runtime_feature_snapshot_quarantine(
        snapshot_payload=harness.payload,
        verified_publication=harness.publication,
        ohlcv_capture=harness.capture,
        ledger=harness.ledger,
    )


def test_active_producer_abi_intersection_is_durable_but_unwired_and_quarantined(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    payload = json.loads(harness.payload)

    assert "runtime_feature_cycle_id" not in payload
    selection = payload["ohlcv_consumer_selection"]
    assert set(selection) == _ACTIVE_SELECTION_KEYS
    assert "source_payload_cas_address" not in selection
    assert "suffix_manifest_cas_address" not in selection

    result = _append(harness)

    assert result.feature_slot_count == FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT == 446
    assert result.authenticated_available_slot_count == 11
    assert result.quarantined_missing_slot_count == 435
    assert result.unresolved_required_plan_slot_count == 83
    assert result.evidence_classification == (RUNTIME_FEATURE_LEDGER_BRIDGE_EVIDENCE_CLASSIFICATION)
    assert result.cycle_binding_status == RUNTIME_FEATURE_LEDGER_CYCLE_BINDING_STATUS
    assert result.historical_import_status == (RUNTIME_FEATURE_LEDGER_HISTORICAL_IMPORT_STATUS)
    assert result.strict_training_eligible is False
    assert result.fixed_cutoff_training_visible is False
    assert result.trainer_admission_authorized is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False

    stored = harness.ledger.get_snapshot(result.durable_snapshot_id)
    assert stored is not None
    envelope = stored.record["frozen_envelope"]
    assert sum(envelope["source_availability_mask"]) == 11
    assert sum(envelope["missing_mask"]) == result.quarantined_missing_slot_count
    assert envelope["strict_training_eligible"] is False
    lineage = envelope["source_lineage_material"]
    assert "runtime_feature_cycle_id" not in lineage
    assert "current_cycle_in_memory_factory_evidence" not in lineage
    assert "historical_redis_receipt_imported" not in lineage
    assert lineage["cycle_binding_status"] == result.cycle_binding_status
    assert lineage["historical_import_status"] == result.historical_import_status
    assert lineage["clock_semantics"]["execution_time"] is None
    assert lineage["source_scope_complete"] is False

    assert (
        harness.ledger.query_fixed_cutoff(
            decision_time_cutoff=envelope["ppo_decision_time"],
            training_observed_at=result.postcommit_readback_at,
            symbol=envelope["symbol"],
            timeframe=envelope["timeframe"],
        )
        == []
    )


def test_raw_leaves_and_receipt_bound_aliases_are_distinguished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DIRECT_LATEST_CANDLE_FEATURES == frozenset(
        {
            "quote_volume",
            "volume",
            "open",
            "high",
            "low",
            "close",
            "num_trades",
            "taker_buy_base_vol",
            "taker_buy_quote_vol",
        }
    )
    assert RECEIPT_BOUND_LATEST_CANDLE_ALIAS_TRANSFORMS == (
        ("ohlcv_close", "close", "TENSOR_BUILDER_OHLCV_CLOSE_IDENTITY_ALIAS_V1"),
        (
            "ohlcv_volume",
            "volume",
            "TENSOR_BUILDER_OHLCV_VOLUME_IDENTITY_ALIAS_V1",
        ),
    )
    harness = _harness(tmp_path, monkeypatch)

    result = _append(harness)
    stored = harness.ledger.get_snapshot(result.durable_snapshot_id)

    assert stored is not None
    envelope = stored.record["frozen_envelope"]
    lineage = envelope["source_lineage_material"]
    assert set(lineage["direct_latest_candle_feature_names"]) == (DIRECT_LATEST_CANDLE_FEATURES)
    names = envelope["ordered_feature_names"]
    roots = envelope["feature_source_receipt_sha256s"]
    source_labels = envelope["ordered_feature_source_labels"]
    receipt_by_sha = {
        receipt["receipt_sha256"]: receipt for receipt in envelope["source_read_receipts"]
    }
    direct_root = roots[names.index("close")]
    assert direct_root is not None
    assert receipt_by_sha[direct_root]["receipt_kind"] == "DIRECT_READ"
    assert receipt_by_sha[direct_root]["source_label"] == "v2:market:ohlcv"
    assert {roots[names.index(feature_name)] for feature_name in DIRECT_LATEST_CANDLE_FEATURES} == {
        direct_root
    }

    transform_by_name = {
        transform["feature_name"]: transform
        for transform in lineage["receipt_bound_latest_candle_alias_transforms"]
    }
    assert set(transform_by_name) == {"ohlcv_close", "ohlcv_volume"}
    alias_roots: set[str] = set()
    for alias in ("ohlcv_close", "ohlcv_volume"):
        ordinal = names.index(alias)
        alias_root = roots[ordinal]
        assert alias_root is not None
        alias_roots.add(alias_root)
        parent = receipt_by_sha[alias_root]
        evidence = transform_by_name[alias]
        scalar_material = evidence["scalar_material"]

        assert alias_root != direct_root
        assert parent["receipt_kind"] == "COMPOSITE_DERIVATION"
        assert parent["source_label"] == source_labels[ordinal]
        assert parent["source_label"] == evidence["source_label"]
        assert parent["child_read_bindings"] == [
            {
                "input_role": "canonical_ohlcv_latest_row",
                "receipt_sha256": direct_root,
            }
        ]
        assert evidence["root_receipt_sha256"] == alias_root
        assert evidence["child_receipt_sha256"] == direct_root
        assert parent["payload_sha256"] == evidence["scalar_payload_sha256"]
        assert parent["payload_sha256"] == _canonical_sha256(scalar_material)
        assert parent["read_evidence"]["payload_byte_count"] == len(
            _canonical_bytes(scalar_material)
        )
        expected_float32_hex = struct.pack("!f", envelope["feature_values"][ordinal]).hex()
        assert scalar_material["derived_value_float32_be_hex"] == (expected_float32_hex)
        assert scalar_material["source_value_float32_be_hex"] == (expected_float32_hex)
        assert parent["derivation_material"]["transform_sha256"] == (
            _canonical_sha256(evidence["transform_contract"])
        )
        assert parent["derivation_material"]["configuration_sha256"] == (
            _canonical_sha256(evidence["configuration_contract"])
        )

    assert len(alias_roots) == 2
    assert len(receipt_by_sha) == 3


@pytest.mark.parametrize("tamper", ["child_edge", "scalar_payload", "transform"])
def test_alias_composite_receipt_graph_tampering_fails_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    original_builder = bridge_module.build_source_read_receipt

    def tampered_builder(**kwargs: Any) -> dict[str, Any]:
        modified = dict(kwargs)
        if modified.get("receipt_kind") == "COMPOSITE_DERIVATION":
            if tamper == "child_edge":
                modified["child_read_bindings"] = [
                    {
                        "input_role": "canonical_ohlcv_latest_row",
                        "receipt_sha256": "0" * 64,
                    }
                ]
            elif tamper == "scalar_payload":
                modified["payload_sha256"] = "0" * 64
            else:
                derivation = dict(modified["derivation_material"])
                derivation["transform_sha256"] = "0" * 64
                modified["derivation_material"] = derivation
        return original_builder(**modified)

    monkeypatch.setattr(
        bridge_module,
        "build_source_read_receipt",
        tampered_builder,
    )

    with pytest.raises(
        RuntimeFeatureSnapshotLedgerBridgeError,
        match="RUNTIME_FEATURE_LEDGER_ALIAS_COMPOSITE_RECEIPT_BINDING_INVALID",
    ):
        _append(harness)

    assert not harness.ledger.path.exists()


@pytest.mark.parametrize(
    ("reason", "harness_kwargs"),
    [
        (
            "RUNTIME_FEATURE_LEDGER_DIRECT_PUBLISHED_VALUE_MISMATCH",
            {"direct_overrides": {"close": 999_999.0}},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_ALIAS_PUBLISHED_VALUE_MISMATCH",
            {"direct_overrides": {"ohlcv_close": 999_999.0}},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_CAPTURE_BINDING_MISMATCH",
            {"selection_overrides": {"exact_payload_sha256": "0" * 64}},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_FINALIZED_CUTOFF_BINDING_INVALID",
            {"top_level_overrides": {"feature_cutoff": "2023-01-01T00:00:00Z"}},
        ),
    ],
)
def test_value_capture_alias_and_finality_mismatches_fail_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    harness_kwargs: dict[str, object],
) -> None:
    harness = _harness(tmp_path, monkeypatch, **harness_kwargs)

    with pytest.raises(RuntimeFeatureSnapshotLedgerBridgeError, match=reason):
        _append(harness)

    assert not harness.ledger.path.exists()


@pytest.mark.parametrize(
    ("reason", "selection_overrides", "top_level_overrides"),
    [
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_SCHEMA_MISMATCH",
            {"schema_version": "wrong"},
            {},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_OBSERVATION_BINDING_MISMATCH",
            {"consumer_observation_cutoff_ms": _BASE_MS},
            {},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_OBSERVATION_BINDING_MISMATCH",
            {},
            {"source_observation_time": "2023-01-01T00:00:00.000000Z"},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_FINALIZED_CUTOFF_BINDING_MISMATCH",
            {"expected_latest_finalized_close_time": _BASE_MS},
            {},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_SCHEMA_ATTESTATION_INVALID",
            {"exact_source_schema_validated": False},
            {},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_CONTIGUITY_INVALID",
            {"entire_contiguous_suffix_bound": False},
            {},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_BACKFILL_BINDING_MISMATCH",
            {"selected_backfilled_row_count": 999},
            {},
        ),
        (
            "RUNTIME_FEATURE_LEDGER_OHLCV_CAPTURE_BINDING_MISMATCH",
            {"selected_source_start_index": 0},
            {},
        ),
    ],
)
def test_selection_schema_cutoff_contiguity_backfill_and_observation_contradictions_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    selection_overrides: dict[str, object],
    top_level_overrides: dict[str, object],
) -> None:
    harness = _harness(
        tmp_path,
        monkeypatch,
        selection_overrides=selection_overrides,
        top_level_overrides=top_level_overrides,
    )

    with pytest.raises(RuntimeFeatureSnapshotLedgerBridgeError, match=reason):
        _append(harness)

    assert not harness.ledger.path.exists()


def test_old_factory_evidence_is_not_reclassified_as_current_or_nonhistorical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)

    assert harness.capture.consumer_observed_at.startswith("2023-")
    result = _append(harness)

    assert "CURRENT_CYCLE" not in result.evidence_classification
    assert result.cycle_binding_status == ("NOT_ATTESTED_ACTIVE_PRODUCER_ABI_HAS_NO_CYCLE_ID")
    assert result.historical_import_status == (
        "NOT_ATTESTED_BY_ACTIVE_PRODUCER_ABI_OR_FACTORY_RESULTS"
    )
    assert not hasattr(result, "historical_redis_receipt_imported")


def test_factory_capture_reuse_with_a_different_observation_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    observed = datetime.fromisoformat(harness.capture.consumer_observed_at[:-1] + "+00:00")
    reuse_root = tmp_path / "reused-capture"
    reuse_root.mkdir()
    reused_capture = capture_harness._capture(
        reuse_root,
        observed_at=observed + timedelta(seconds=1),
    )[0]

    with pytest.raises(
        RuntimeFeatureSnapshotLedgerBridgeError,
        match="RUNTIME_FEATURE_LEDGER_OHLCV_SELECTION_OBSERVATION_BINDING_MISMATCH",
    ):
        append_unwired_runtime_feature_snapshot_quarantine(
            snapshot_payload=harness.payload,
            verified_publication=harness.publication,
            ohlcv_capture=reused_capture,
            ledger=harness.ledger,
        )

    assert not harness.ledger.path.exists()


@pytest.mark.parametrize(
    "authority_field",
    [
        "strict_training_eligible",
        "fixed_cutoff_training_visible",
        "trainer_admission_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    ],
)
def test_result_authority_booleans_cannot_be_forged_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_field: str,
) -> None:
    result = _append(_harness(tmp_path, monkeypatch))

    with pytest.raises(
        RuntimeFeatureSnapshotLedgerBridgeError,
        match="RUNTIME_FEATURE_LEDGER_RESULT_QUARANTINE_INVARIANT_INVALID",
    ):
        replace(result, **{authority_field: True})


def test_duplicate_json_error_is_normalized_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(tmp_path, monkeypatch)
    symbol = harness.capture.validated_window.symbol
    needle = f'"symbol": "{symbol}"'
    duplicate_payload = harness.payload.replace(
        needle,
        f'{needle}, "symbol": "{symbol}"',
        1,
    )

    with pytest.raises(
        RuntimeFeatureSnapshotLedgerBridgeError,
        match="RUNTIME_FEATURE_LEDGER_SNAPSHOT_JSON_DUPLICATE_KEY",
    ):
        append_unwired_runtime_feature_snapshot_quarantine(
            snapshot_payload=duplicate_payload,
            verified_publication=harness.publication,
            ohlcv_capture=harness.capture,
            ledger=harness.ledger,
        )

    assert not harness.ledger.path.exists()


def test_generated_clock_before_source_read_fails_before_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _harness(
        tmp_path,
        monkeypatch,
        top_level_overrides={"generated_at": "2023-01-01T00:00:00.000000Z"},
    )

    with pytest.raises(
        RuntimeFeatureSnapshotLedgerBridgeError,
        match="RUNTIME_FEATURE_LEDGER_CAUSAL_CLOCK_ORDER_INVALID",
    ):
        _append(harness)

    assert not harness.ledger.path.exists()


def test_public_api_is_explicitly_unwired_and_has_no_cycle_or_history_surface() -> None:
    assert tuple(
        inspect.signature(append_unwired_runtime_feature_snapshot_quarantine).parameters
    ) == (
        "snapshot_payload",
        "verified_publication",
        "ohlcv_capture",
        "ledger",
    )
