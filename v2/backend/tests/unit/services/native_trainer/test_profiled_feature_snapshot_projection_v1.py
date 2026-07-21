from __future__ import annotations

import ast
import copy
import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as ledger_v3,
)
from v2.backend.app.services.native_trainer import (
    profiled_feature_snapshot_projection_v1 as projection_v1,
)
from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT,
)

_SNAPSHOT_ID = "profiled-projection-fixture-v1"
_DECISION_TIME = "2024-07-21T11:00:00.000000Z"
_GENERATED_AT = "2024-07-21T10:58:00.000000Z"
_ROOT_AVAILABLE_AT = "2024-07-21T10:56:00.000000Z"
_ROOT_OBSERVED_AT = "2024-07-21T10:57:00.000000Z"
_FIVE_MINUTE_CUTOFF = "2024-07-21T10:55:00.000000Z"
_ONE_HOUR_CUTOFF = "2024-07-21T10:00:00.000000Z"
_RESERVED_LINEAGE_FIELDS = frozenset(
    {
        "feature_abi_sha256",
        "ordered_feature_source_labels",
        "source_availability_mask",
        "feature_source_receipt_sha256s",
        "feature_source_bindings_sha256",
        "source_read_receipt_sha256s",
        "source_receipt_graph_sha256",
        "model_vector_sha256",
    }
)


@dataclass(frozen=True)
class _Evidence:
    values: tuple[float, ...]
    roots: tuple[str, ...]
    receipts: tuple[dict[str, Any], ...]
    captures: dict[str, dict[str, Any]]


def _capture_receipt(timeframe: str) -> dict[str, Any]:
    cutoff = _FIVE_MINUTE_CUTOFF if timeframe == "5m" else _ONE_HOUR_CUTOFF
    available_at = (
        "2024-07-21T10:55:10.000000Z" if timeframe == "5m" else "2024-07-21T10:00:10.000000Z"
    )
    observed_at = (
        "2024-07-21T10:55:20.000000Z" if timeframe == "5m" else "2024-07-21T10:00:20.000000Z"
    )
    payload = f"closed-{timeframe}-fixture".encode("ascii")
    return projection_v1.build_profiled_ohlcv_capture_receipt_v1(
        physical_timeframe=timeframe,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_byte_count=len(payload),
        latest_finalized_close_time=cutoff,
        available_at=available_at,
        consumer_observed_at=observed_at,
        read_locator=f"fixtures/closed/{timeframe}",
        read_locator_version="fixture-v1",
    )


def _feature_timeframes() -> dict[str, str]:
    profile = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1
    return {
        transform.feature_name: family.physical_timeframe
        for family in profile.timeframe_finality_transform_contracts
        for transform in family.transforms
    }


def _build_evidence(
    *,
    one_hour_capture: dict[str, Any] | None = None,
    root_available_at: str = _ROOT_AVAILABLE_AT,
    root_observed_at: str = _ROOT_OBSERVED_AT,
) -> _Evidence:
    profile = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1
    captures = {
        "5m": _capture_receipt("5m"),
        "1h": one_hour_capture or _capture_receipt("1h"),
    }
    values = tuple((ordinal + 1) / 8.0 for ordinal in range(39))
    receipts = list(captures.values())
    roots: list[str] = []
    feature_timeframes = _feature_timeframes()
    for physical_ordinal, feature_name in enumerate(profile.enabled_feature_names):
        receipt = projection_v1.build_profiled_model_feature_receipt_v1(
            feature_name=feature_name,
            feature_value=values[physical_ordinal],
            feature_snapshot_id=_SNAPSHOT_ID,
            capture_receipt=captures[feature_timeframes[feature_name]],
            available_at=root_available_at,
            consumer_observed_at=root_observed_at,
            read_locator=f"memory/model/{feature_name}",
            read_locator_version="fixture-v1",
        )
        receipts.append(receipt)
        roots.append(receipt["receipt_sha256"])
    for offset, feature_name in enumerate(projection_v1.AUXILIARY_LABEL_ONLY_FEATURE_NAMES):
        physical_ordinal = projection_v1.PHYSICAL_MODEL_FEATURE_COUNT + offset
        receipt = projection_v1.build_profiled_auxiliary_receipt_v1(
            feature_name=feature_name,
            feature_value=values[physical_ordinal],
            feature_snapshot_id=_SNAPSHOT_ID,
            event_time=_FIVE_MINUTE_CUTOFF,
            available_at=root_available_at,
            consumer_observed_at=root_observed_at,
            feature_cutoff=_FIVE_MINUTE_CUTOFF,
            read_locator=f"memory/auxiliary/{feature_name}",
            read_locator_version="fixture-v1",
        )
        receipts.append(receipt)
        roots.append(receipt["receipt_sha256"])
    return _Evidence(
        values=values,
        roots=tuple(roots),
        receipts=tuple(receipts),
        captures=captures,
    )


def _build_record(
    evidence: _Evidence,
    *,
    decision_time: str = _DECISION_TIME,
    generated_at: str = _GENERATED_AT,
    values: tuple[float, ...] | list[float] | None = None,
    roots: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    return projection_v1.build_profiled_feature_snapshot_record_v1(
        symbol="BTCUSDT",
        feature_snapshot_id=_SNAPSHOT_ID,
        physical_feature_values=values or evidence.values,
        physical_feature_receipt_sha256s=roots or evidence.roots,
        source_read_receipts=evidence.receipts,
        decision_time=decision_time,
        generated_at=generated_at,
    )


@pytest.fixture(scope="module")
def evidence() -> _Evidence:
    return _build_evidence()


@pytest.fixture(scope="module")
def record(evidence: _Evidence) -> dict[str, Any]:
    return _build_record(evidence)


def _builder_kwargs(record: dict[str, Any]) -> dict[str, Any]:
    envelope = record["frozen_envelope"]
    lineage = envelope["source_lineage_material"]
    return {
        "provenance_classification": envelope["provenance_classification"],
        "legacy_v1_snapshot_id": envelope["legacy_v1_snapshot_id"],
        "symbol": envelope["symbol"],
        "timeframe": envelope["timeframe"],
        "feature_snapshot_id": envelope["feature_snapshot_id"],
        "tensor_decision_time": envelope["tensor_decision_time"],
        "temporal_rejection_reasons": envelope["temporal_rejection_reasons"],
        "ordered_feature_names": envelope["ordered_feature_names"],
        "feature_values": envelope["feature_values"],
        "missing_mask": envelope["missing_mask"],
        "stale_mask": envelope["stale_mask"],
        "source_availability_mask": envelope["source_availability_mask"],
        "ordered_feature_source_labels": envelope["ordered_feature_source_labels"],
        "feature_source_receipt_sha256s": envelope["feature_source_receipt_sha256s"],
        "source_read_receipts": envelope["source_read_receipts"],
        "feature_requirement_policy_id": (ledger_v3.FEATURE_REQUIREMENT_POLICY_ID),
        "ordered_feature_requirement_classes": envelope["feature_abi"][
            "ordered_feature_requirement_classes"
        ],
        "original_tensor_id": envelope["original_tensor_id"],
        "source_lineage_material": {
            key: value for key, value in lineage.items() if key not in _RESERVED_LINEAGE_FIELDS
        },
        "feature_cutoff": envelope["feature_cutoff"],
        "masa_feature_cutoff": envelope["masa_feature_cutoff"],
        "ppo_feature_cutoff": envelope["ppo_feature_cutoff"],
        "ppo_decision_time": envelope["ppo_decision_time"],
        "generated_at": envelope["generated_at"],
    }


def _rebuild_v3(record: dict[str, Any], **overrides: object) -> dict[str, Any]:
    kwargs = _builder_kwargs(record)
    kwargs.update(overrides)
    return ledger_v3.build_feature_snapshot_record(**kwargs)


def _resign_record(record: dict[str, Any]) -> None:
    envelope = record["frozen_envelope"]
    envelope["source_lineage_sha256"] = ledger_v3.stable_sha256(envelope["source_lineage_material"])
    envelope_sha256 = ledger_v3.stable_sha256(envelope)
    record["frozen_envelope_sha256"] = envelope_sha256
    record["durable_snapshot_id"] = f"feature_snapshot_v3_{envelope_sha256}"
    record["record_sha256"] = ledger_v3.stable_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _assert_projection_error(
    expected_reason: str,
    callback: Any,
) -> None:
    with pytest.raises(projection_v1.ProfiledFeatureSnapshotProjectionV1Error) as exc_info:
        callback()
    assert expected_reason in exc_info.value.reasons


def test_physical_record_is_exact_required_39_and_uses_real_v3_ledger(
    tmp_path: Path,
    record: dict[str, Any],
) -> None:
    envelope = record["frozen_envelope"]
    assert record["schema_version"] == ledger_v3.RECORD_SCHEMA_VERSION
    assert envelope["ordered_feature_names"] == list(projection_v1.PHYSICAL_ORDERED_FEATURE_NAMES)
    assert envelope["ordered_feature_names"][:35] == list(
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_feature_names
    )
    assert envelope["ordered_feature_names"][35:] == list(
        projection_v1.AUXILIARY_LABEL_ONLY_FEATURE_NAMES
    )
    assert envelope["feature_abi"]["ordered_feature_requirement_classes"] == ["REQUIRED"] * 39
    assert envelope["missing_mask"] == [0] * 39
    assert envelope["stale_mask"] == [0] * 39
    assert envelope["source_availability_mask"] == [1] * 39
    assert all(envelope["feature_source_receipt_sha256s"])
    assert envelope["strict_training_eligible"] is False
    ledger_v3.validate_feature_snapshot_record(record)

    ledger = ledger_v3.DurableFeatureSnapshotLedger(tmp_path / "profiled-physical-v3.sqlite3")
    append = ledger.append_snapshot(record)
    stored = ledger.get_snapshot(record["durable_snapshot_id"])
    assert append.inserted_rows == 1
    assert append.transaction_committed is True
    assert append.transaction_readback_verified is True
    assert stored is not None
    assert stored.record == record
    assert ledger.verify_integrity_streaming().verified_records == 1


def test_projection_reconstructs_only_selected_base_abi_ordinals(
    evidence: _Evidence,
    record: dict[str, Any],
) -> None:
    result = projection_v1.validate_profiled_feature_snapshot_projection_v1(record)
    enabled_ordinals = ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals
    assert len(result.logical_feature_values) == FEATURE_SOURCE_REGISTRY_V4_SLOT_COUNT
    assert len(result.logical_profile_selection_mask) == 446
    assert sum(result.logical_profile_selection_mask) == 35
    assert {
        ordinal
        for ordinal, selected in enumerate(result.logical_profile_selection_mask)
        if selected
    } == set(enabled_ordinals)
    for physical_ordinal, logical_ordinal in enumerate(enabled_ordinals):
        assert result.logical_feature_values[logical_ordinal] == evidence.values[physical_ordinal]
        assert result.logical_source_availability_mask[logical_ordinal] == 1
        assert (
            result.logical_feature_receipt_sha256s[logical_ordinal]
            == evidence.roots[physical_ordinal]
        )
        assert result.logical_feature_source_labels[logical_ordinal] is not None
    for ordinal, selected in enumerate(result.logical_profile_selection_mask):
        if selected:
            continue
        assert result.logical_feature_values[ordinal] == 0.0
        assert result.logical_missing_mask[ordinal] == 0
        assert result.logical_stale_mask[ordinal] == 0
        assert result.logical_source_availability_mask[ordinal] == 0
        assert result.logical_feature_source_labels[ordinal] is None
        assert result.logical_feature_receipt_sha256s[ordinal] is None

    assert result.logical_ordered_feature_names[32] == "spread_bps"
    assert result.logical_profile_selection_mask[32] == 0
    assert result.logical_feature_values[32] == 0.0
    physical_aux_spread = evidence.values[36]
    assert physical_aux_spread != 0.0
    assert physical_aux_spread not in result.logical_feature_values


def test_selection_mask_lineage_mapping_roles_and_hashes_are_authenticated(
    record: dict[str, Any],
) -> None:
    envelope = record["frozen_envelope"]
    lineage = envelope["source_lineage_material"]
    result = projection_v1.validate_profiled_feature_snapshot_projection_v1(record)
    assert lineage["profile_id"] == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID
    assert lineage["profile_sha256"] == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
    assert lineage["base_abi_sha256"] == FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
    assert lineage["logical_slot_count"] == 446
    assert lineage["logical_profile_selection_mask"] == list(
        projection_v1.LOGICAL_PROFILE_SELECTION_MASK
    )
    assert lineage["logical_profile_selection_mask_sha256"] == (
        projection_v1.PROFILED_FEATURE_SNAPSHOT_LOGICAL_SELECTION_MASK_SHA256
    )
    assert lineage["logical_profile_selection_mask_sha256"] == (
        ledger_v3.stable_sha256(list(projection_v1.LOGICAL_PROFILE_SELECTION_MASK))
    )
    assert (
        result.logical_profile_selection_mask_sha256
        == lineage["logical_profile_selection_mask_sha256"]
    )
    assert len(lineage["enabled_ordinal_mapping"]) == 35
    assert [
        item["logical_base_abi_ordinal"] for item in lineage["enabled_ordinal_mapping"]
    ] == list(ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals)
    assert [item["role"] for item in lineage["physical_feature_roles"]] == list(
        projection_v1.PHYSICAL_ORDERED_FEATURE_ROLES
    )
    assert lineage["projection_implementation_sha256"] == (
        projection_v1.PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_IMPLEMENTATION_SHA256
    )
    assert lineage["projection_configuration_sha256"] == (
        projection_v1.PROFILED_FEATURE_SNAPSHOT_PROJECTION_V1_CONFIGURATION_SHA256
    )
    assert envelope["source_lineage_sha256"] == ledger_v3.stable_sha256(lineage)
    assert result.logical_tensor_sha256 == (
        projection_v1.validate_profiled_feature_snapshot_projection_v1(
            copy.deepcopy(record)
        ).logical_tensor_sha256
    )
    assert result.projection_sha256 == (
        projection_v1.validate_profiled_feature_snapshot_projection_v1(
            copy.deepcopy(record)
        ).projection_sha256
    )


def test_exact_5m_and_true_1h_capture_transform_graph_is_bound(
    evidence: _Evidence,
    record: dict[str, Any],
) -> None:
    envelope = record["frozen_envelope"]
    lineage = envelope["source_lineage_material"]
    timeframe_evidence = {
        item["physical_timeframe"]: item for item in lineage["timeframe_evidence"]
    }
    assert set(timeframe_evidence) == {"5m", "1h"}
    assert timeframe_evidence["5m"]["capture_feature_cutoff"] == (_FIVE_MINUTE_CUTOFF)
    assert timeframe_evidence["1h"]["capture_feature_cutoff"] == (_ONE_HOUR_CUTOFF)
    assert timeframe_evidence["1h"]["capture_payload_type"] == (
        "CANONICAL_CLOSED_OHLCV_WINDOW_1H_V1"
    )
    assert (
        timeframe_evidence["1h"]["capture_finality_evidence"]["finality_type"] == "CLOSED_INTERVAL"
    )
    assert timeframe_evidence["1h"]["capture_finality_evidence"]["event_final"] is True
    assert len(timeframe_evidence["5m"]["transform_evidence"]) == 27
    assert len(timeframe_evidence["1h"]["transform_evidence"]) == 8
    assert {
        item["logical_base_abi_ordinal"] for item in timeframe_evidence["1h"]["transform_evidence"]
    } == set(range(434, 442))
    assert all(
        item["transform_contract"]["proxy_higher_timeframe_allowed"] is False
        for item in timeframe_evidence["1h"]["transform_evidence"]
    )

    receipt_by_sha = {item["receipt_sha256"]: item for item in envelope["source_read_receipts"]}
    feature_timeframes = _feature_timeframes()
    for physical_ordinal, feature_name in enumerate(
        ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_feature_names
    ):
        root = receipt_by_sha[evidence.roots[physical_ordinal]]
        timeframe = feature_timeframes[feature_name]
        assert root["receipt_kind"] == "COMPOSITE_DERIVATION"
        assert root["finality_evidence"]["event_final"] is True
        assert root["child_read_bindings"] == [
            {
                "input_role": f"canonical_closed_{timeframe}_capture",
                "receipt_sha256": evidence.captures[timeframe]["receipt_sha256"],
            }
        ]
    for root_sha256 in evidence.roots[35:]:
        root = receipt_by_sha[root_sha256]
        assert root["receipt_kind"] == "DIRECT_READ"
        assert root["finality_evidence"]["event_final"] is True


def test_label_rebuild_snapshot_contains_all_physical_and_auxiliary_evidence(
    evidence: _Evidence,
    record: dict[str, Any],
) -> None:
    result = projection_v1.validate_profiled_feature_snapshot_projection_v1(record)
    rebuild = result.label_rebuild_physical_snapshot
    assert rebuild["ordered_feature_names"] == list(projection_v1.PHYSICAL_ORDERED_FEATURE_NAMES)
    assert rebuild["ordered_feature_roles"] == list(projection_v1.PHYSICAL_ORDERED_FEATURE_ROLES)
    assert rebuild["feature_values"] == list(evidence.values)
    assert rebuild["feature_snapshot_id"] == _SNAPSHOT_ID
    assert rebuild["feature_cutoff"] == _FIVE_MINUTE_CUTOFF
    assert rebuild["decision_time"] == _DECISION_TIME
    assert (
        rebuild["ordered_feature_source_labels"]
        == record["frozen_envelope"]["ordered_feature_source_labels"]
    )
    assert rebuild["feature_source_receipt_sha256s"] == list(evidence.roots)
    assert rebuild["auxiliary_label_values"] == {
        name: evidence.values[35 + offset]
        for offset, name in enumerate(projection_v1.AUXILIARY_LABEL_ONLY_FEATURE_NAMES)
    }
    assert rebuild["auxiliary_excluded_from_model_projection"] is True
    assert (
        hashlib.sha256(result.label_rebuild_physical_snapshot_json.encode("ascii")).hexdigest()
        == result.label_rebuild_physical_snapshot_sha256
    )


def test_no_runtime_authority_and_no_runtime_import_wiring(
    record: dict[str, Any],
) -> None:
    result = projection_v1.validate_profiled_feature_snapshot_projection_v1(record)
    assert result.runtime_wired is False
    assert result.trainer_admission_authorized is False
    assert result.prediction_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    _assert_projection_error(
        "PROFILED_PROJECTION_RESULT_INVARIANT_INVALID",
        lambda: replace(result, live_execution_authorized=True),
    )

    module_path = Path(projection_v1.__file__)
    source = module_path.read_text(encoding="utf-8")
    imported_modules = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "DEFAULT_TIMEFRAMES" not in source
    assert "sqlite3" not in imported_modules
    assert {module for module in imported_modules if module.startswith("v2.backend")} == {
        "v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1",
        "v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger",
        "v2.backend.app.services.native_trainer.feature_source_registry_v4",
    }


def test_logical_claim_accepts_exact_projection_and_rejects_aux_leakage(
    evidence: _Evidence,
    record: dict[str, Any],
) -> None:
    result = projection_v1.validate_profiled_feature_snapshot_projection_v1(record)
    claim = {
        "ordered_feature_names": result.logical_ordered_feature_names,
        "feature_values": result.logical_feature_values,
        "missing_mask": result.logical_missing_mask,
        "stale_mask": result.logical_stale_mask,
        "source_availability_mask": result.logical_source_availability_mask,
        "profile_selection_mask": result.logical_profile_selection_mask,
    }
    projection_v1.validate_profiled_logical_tensor_claim_v1(result, **claim)
    leaking_values = list(result.logical_feature_values)
    leaking_values[32] = evidence.values[36]
    claim["feature_values"] = leaking_values
    _assert_projection_error(
        "PROFILED_PROJECTION_DISABLED_VALUE_NONZERO",
        lambda: projection_v1.validate_profiled_logical_tensor_claim_v1(result, **claim),
    )


def test_swapped_model_ordinals_are_v3_valid_but_profile_invalid(
    record: dict[str, Any],
) -> None:
    envelope = record["frozen_envelope"]
    swapped_vectors: dict[str, list[Any]] = {}
    for field in (
        "ordered_feature_names",
        "feature_values",
        "ordered_feature_source_labels",
        "feature_source_receipt_sha256s",
    ):
        values = list(envelope[field])
        values[0], values[1] = values[1], values[0]
        swapped_vectors[field] = values
    swapped = _rebuild_v3(record, **swapped_vectors)
    ledger_v3.validate_feature_snapshot_record(swapped)
    _assert_projection_error(
        "PROFILED_PROJECTION_PHYSICAL_FEATURE_ORDER_INVALID",
        lambda: projection_v1.validate_profiled_feature_snapshot_projection_v1(swapped),
    )


def test_auxiliary_in_model_ordinal_is_v3_valid_but_profile_invalid(
    record: dict[str, Any],
) -> None:
    envelope = record["frozen_envelope"]
    spread_aux_ordinal = 36
    swapped_vectors: dict[str, list[Any]] = {}
    for field in (
        "ordered_feature_names",
        "feature_values",
        "ordered_feature_source_labels",
        "feature_source_receipt_sha256s",
    ):
        values = list(envelope[field])
        values[0], values[spread_aux_ordinal] = (
            values[spread_aux_ordinal],
            values[0],
        )
        swapped_vectors[field] = values
    leaked = _rebuild_v3(record, **swapped_vectors)
    ledger_v3.validate_feature_snapshot_record(leaked)
    assert leaked["frozen_envelope"]["ordered_feature_names"][0] == "spread_bps"
    _assert_projection_error(
        "PROFILED_PROJECTION_PHYSICAL_FEATURE_ORDER_INVALID",
        lambda: projection_v1.validate_profiled_feature_snapshot_projection_v1(leaked),
    )


def test_missing_auxiliary_is_v3_valid_but_profile_invalid(
    record: dict[str, Any],
) -> None:
    envelope = record["frozen_envelope"]
    dropped_root = envelope["feature_source_receipt_sha256s"][-1]
    shortened = _rebuild_v3(
        record,
        ordered_feature_names=envelope["ordered_feature_names"][:-1],
        feature_values=envelope["feature_values"][:-1],
        missing_mask=envelope["missing_mask"][:-1],
        stale_mask=envelope["stale_mask"][:-1],
        source_availability_mask=envelope["source_availability_mask"][:-1],
        ordered_feature_source_labels=envelope["ordered_feature_source_labels"][:-1],
        feature_source_receipt_sha256s=envelope["feature_source_receipt_sha256s"][:-1],
        source_read_receipts=[
            receipt
            for receipt in envelope["source_read_receipts"]
            if receipt["receipt_sha256"] != dropped_root
        ],
        ordered_feature_requirement_classes=envelope["feature_abi"][
            "ordered_feature_requirement_classes"
        ][:-1],
    )
    ledger_v3.validate_feature_snapshot_record(shortened)
    _assert_projection_error(
        "PROFILED_PROJECTION_PHYSICAL_FEATURE_ORDER_INVALID",
        lambda: projection_v1.validate_profiled_feature_snapshot_projection_v1(shortened),
    )


@pytest.mark.parametrize(
    "lineage_field",
    [
        "profile_sha256",
        "base_abi_sha256",
        "projection_implementation_sha256",
        "projection_configuration_sha256",
    ],
)
def test_profile_and_contract_hash_tamper_is_v3_valid_but_profile_invalid(
    lineage_field: str,
    record: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(record)
    lineage = tampered["frozen_envelope"]["source_lineage_material"]
    lineage[lineage_field] = "0" * 64
    _resign_record(tampered)
    ledger_v3.validate_feature_snapshot_record(tampered)
    _assert_projection_error(
        "PROFILED_PROJECTION_SOURCE_LINEAGE_BINDING_INVALID",
        lambda: projection_v1.validate_profiled_feature_snapshot_projection_v1(tampered),
    )


def test_selection_mask_tamper_is_v3_valid_but_profile_invalid(
    record: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(record)
    lineage = tampered["frozen_envelope"]["source_lineage_material"]
    lineage["logical_profile_selection_mask"][10] = 0
    lineage["logical_profile_selection_mask_sha256"] = ledger_v3.stable_sha256(
        lineage["logical_profile_selection_mask"]
    )
    _resign_record(tampered)
    ledger_v3.validate_feature_snapshot_record(tampered)
    _assert_projection_error(
        "PROFILED_PROJECTION_SOURCE_LINEAGE_BINDING_INVALID",
        lambda: projection_v1.validate_profiled_feature_snapshot_projection_v1(tampered),
    )


def test_receipt_payload_tamper_is_rejected_by_v3_first(
    record: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(record)
    envelope = tampered["frozen_envelope"]
    root_sha256 = envelope["feature_source_receipt_sha256s"][0]
    root = next(
        receipt
        for receipt in envelope["source_read_receipts"]
        if receipt["receipt_sha256"] == root_sha256
    )
    root["payload_sha256"] = "f" * 64
    _resign_record(tampered)
    _assert_projection_error(
        "PROFILED_PROJECTION_PHYSICAL_V3_RECORD_INVALID",
        lambda: projection_v1.validate_profiled_feature_snapshot_projection_v1(tampered),
    )


def test_swapped_model_receipt_roots_are_rejected(evidence: _Evidence) -> None:
    roots = list(evidence.roots)
    roots[0], roots[1] = roots[1], roots[0]
    _assert_projection_error(
        "PROFILED_PROJECTION_MODEL_TRANSFORM_BINDING_INVALID",
        lambda: _build_record(evidence, roots=roots),
    )


def test_non_closed_one_hour_capture_finality_is_rejected() -> None:
    payload = b"not-closed-one-hour-capture"
    bad_capture = ledger_v3.build_source_read_receipt(
        source_label="profiled:ohlcv_bootstrap:capture:1h",
        payload_type="CANONICAL_CLOSED_OHLCV_WINDOW_1H_V1",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_byte_count=len(payload),
        event_time=_ONE_HOUR_CUTOFF,
        available_at="2024-07-21T10:00:10.000000Z",
        consumer_observed_at="2024-07-21T10:00:20.000000Z",
        feature_cutoff=_ONE_HOUR_CUTOFF,
        read_locator_type="FILE_CONTENT_ADDRESS",
        read_locator="fixtures/not-closed/1h",
        read_locator_version="fixture-v1",
        finality_type="VERSIONED_SNAPSHOT",
        finality_cutoff="2024-07-21T10:00:10.000000Z",
        finality_verified_at="2024-07-21T10:00:10.000000Z",
        finality_verifier="adversarial-wrong-finality",
    )
    evidence = _build_evidence(one_hour_capture=bad_capture)
    _assert_projection_error(
        "PROFILED_PROJECTION_CAPTURE_FINALITY_BINDING_INVALID",
        lambda: _build_record(evidence),
    )


def test_unfinished_one_hour_capture_at_decision_time_is_rejected() -> None:
    payload = b"unfinished-one-hour-capture"
    bad_capture = projection_v1.build_profiled_ohlcv_capture_receipt_v1(
        physical_timeframe="1h",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_byte_count=len(payload),
        latest_finalized_close_time=_DECISION_TIME,
        available_at=_DECISION_TIME,
        consumer_observed_at=_DECISION_TIME,
        read_locator="fixtures/unfinished/1h",
        read_locator_version="fixture-v1",
    )
    evidence = _build_evidence(
        one_hour_capture=bad_capture,
        root_available_at=_DECISION_TIME,
        root_observed_at=_DECISION_TIME,
    )
    _assert_projection_error(
        "PROFILED_PROJECTION_CAPTURE_NOT_FINAL_BEFORE_DECISION",
        lambda: _build_record(
            evidence,
            decision_time=_DECISION_TIME,
            generated_at=_DECISION_TIME,
        ),
    )


@pytest.mark.parametrize("invalid_value", [float("nan"), 3.5e38])
def test_nan_and_float32_overflow_are_rejected(
    invalid_value: float,
    evidence: _Evidence,
) -> None:
    values = list(evidence.values)
    values[0] = invalid_value
    _assert_projection_error(
        "PROFILED_PROJECTION_PHYSICAL_VALUE_INVALID",
        lambda: _build_record(evidence, values=values),
    )
