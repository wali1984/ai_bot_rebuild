from __future__ import annotations

import ast
import hashlib
import json
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer import (
    feature_resolution_observation_v4 as observation_module,
)
from v2.backend.app.services.native_trainer import (
    feature_resolution_trace_v4 as trace_module,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    feature_abi_contract,
    feature_requirement_classes_for_names,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_resolution_observation_v4 import (
    IDENTITY_TRANSFORM_CODE_SHA256,
    IDENTITY_TRANSFORM_CONFIG_SHA256,
    IDENTITY_TRANSFORM_ID,
    IDENTITY_TRANSFORM_VERSION,
    NEGATIVE_SOURCE_STALE,
    NEGATIVE_SOURCE_UNAVAILABLE,
    RESOLUTION_STATUS_RESOLVED,
    RESOLUTION_STATUS_TYPED_NEGATIVE,
    UNRESOLVED_TRANSFORM_CODE_SHA256,
    UNRESOLVED_TRANSFORM_CONFIG_SHA256,
    UNRESOLVED_TRANSFORM_ID,
    UNRESOLVED_TRANSFORM_VERSION,
    FeatureResolutionObservationV4ValidationError,
    build_feature_slot_resolution_observation_v4,
)
from v2.backend.app.services.native_trainer.feature_resolution_trace_v4 import (
    FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256,
    FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT,
    FeatureResolutionTraceArtifactV4,
    FeatureResolutionTraceV4ValidationError,
    build_feature_resolution_trace_v4,
    validate_feature_resolution_trace_v4,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
    FeatureTensorRecord,
)

_DECISION = "2026-07-20T00:00:01.000000Z"
_CUTOFF = "2026-07-20T00:00:00.500000Z"
_OBSERVED = "2026-07-20T00:00:02.000000Z"
_SHA_A = "1" * 64
_SHA_B = "2" * 64
_SHA_C = "3" * 64
_SHA_D = "4" * 64


def _tensor(*, negative_index: int | None = None, stale: bool = False) -> FeatureTensorRecord:
    names = tuple(name for name, _source in FEATURE_SPEC)
    sources = tuple(source for _name, source in FEATURE_SPEC)
    values = [float(index + 1) for index in range(len(names))]
    missing = [0] * len(names)
    stale_mask = [0] * len(names)
    available = [1] * len(names)
    if negative_index is not None:
        if stale:
            stale_mask[negative_index] = 1
        else:
            values[negative_index] = 0.0
            missing[negative_index] = 1
            available[negative_index] = 0
    missing_names = tuple(name for name, mask in zip(names, missing, strict=True) if mask == 1)
    stale_names = tuple(name for name, mask in zip(names, stale_mask, strict=True) if mask == 1)
    return FeatureTensorRecord(
        tensor_id="tensor_v4_test",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="snapshot_v4_test",
        values=tuple(values),
        missing_mask=tuple(missing),
        stale_mask=tuple(stale_mask),
        source_availability=tuple(available),
        feature_names=names,
        source_labels=sources,
        missing_feature_names=missing_names,
        stale_feature_names=stale_names,
        data_coverage_percent=100.0 * (len(names) - sum(missing)) / len(names),
        source_availability_vector=tuple(available),
        decision_time=_DECISION,
        source_lineage_hash=_SHA_A,
        temporal_rejection_reasons=(),
    )


def _observation(
    tensor: FeatureTensorRecord,
    index: int,
    *,
    selected_key: str | None = None,
    selected_alias: str | None = None,
) -> observation_module.FeatureSlotResolutionObservationV4:
    name = tensor.feature_names[index]
    negative = bool(
        tensor.missing_mask[index]
        or tensor.stale_mask[index]
        or not tensor.source_availability[index]
    )
    if negative:
        source_stale = tensor.stale_mask[index] == 1
        return build_feature_slot_resolution_observation_v4(
            abi_index=index,
            feature_name=name,
            resolution_status=RESOLUTION_STATUS_TYPED_NEGATIVE,
            selected_payload=None,
            selected_key=None,
            selected_path=None,
            selected_alias=None,
            resolver_version="v1",
            resolver_code_sha256=_SHA_B,
            resolver_config_sha256=_SHA_C,
            transform_id=UNRESOLVED_TRANSFORM_ID,
            transform_version=UNRESOLVED_TRANSFORM_VERSION,
            transform_code_sha256=UNRESOLVED_TRANSFORM_CODE_SHA256,
            transform_config_sha256=UNRESOLVED_TRANSFORM_CONFIG_SHA256,
            resolved_value=None,
            negative_reason=(
                NEGATIVE_SOURCE_STALE if source_stale else NEGATIVE_SOURCE_UNAVAILABLE
            ),
            source_root_sha256=_SHA_C if source_stale else None,
            dependency_root_sha256s=(_SHA_C,),
            negative_evidence_sha256=_SHA_D,
            event_time=("2026-07-20T00:00:00.000000Z" if source_stale else None),
            ingested_at=("2026-07-20T00:00:00.100000Z" if source_stale else None),
            available_at=("2026-07-20T00:00:00.300000Z" if source_stale else None),
            generated_at=("2026-07-20T00:00:00.200000Z" if source_stale else None),
            feature_cutoff=_CUTOFF,
            decision_time=_DECISION,
            masa_feature_cutoff=_CUTOFF,
            execution_time=None,
            consumer_observed_at=_OBSERVED,
        )
    key = selected_key or name
    alias = selected_alias or key
    return build_feature_slot_resolution_observation_v4(
        abi_index=index,
        feature_name=name,
        resolution_status=RESOLUTION_STATUS_RESOLVED,
        selected_payload="raw_context",
        selected_key=key,
        selected_path=("raw_context", key),
        selected_alias=alias,
        resolver_version="v1",
        resolver_code_sha256=_SHA_B,
        resolver_config_sha256=_SHA_C,
        transform_id=IDENTITY_TRANSFORM_ID,
        transform_version=IDENTITY_TRANSFORM_VERSION,
        transform_code_sha256=IDENTITY_TRANSFORM_CODE_SHA256,
        transform_config_sha256=IDENTITY_TRANSFORM_CONFIG_SHA256,
        resolved_value=tensor.values[index],
        negative_reason=None,
        source_root_sha256=_SHA_C,
        dependency_root_sha256s=(_SHA_D,),
        negative_evidence_sha256=None,
        event_time="2026-07-20T00:00:00.000000Z",
        ingested_at="2026-07-20T00:00:00.100000Z",
        available_at="2026-07-20T00:00:00.300000Z",
        generated_at="2026-07-20T00:00:00.200000Z",
        feature_cutoff=_CUTOFF,
        decision_time=_DECISION,
        masa_feature_cutoff=_CUTOFF,
        execution_time=None,
        consumer_observed_at=_OBSERVED,
    )


def _observations(
    tensor: FeatureTensorRecord,
) -> tuple[observation_module.FeatureSlotResolutionObservationV4, ...]:
    return tuple(_observation(tensor, index) for index in range(len(FEATURE_SPEC)))


def _model_bytes(tensor: FeatureTensorRecord) -> bytes:
    return struct.pack(f"!{len(tensor.model_vector)}f", *tensor.model_vector)


def _rehash_external_trace(
    trace: dict[str, Any],
    *,
    changed_slot_index: int | None = None,
) -> None:
    if changed_slot_index is not None:
        slot = trace["slot_observations"][changed_slot_index]
        slot_material = {
            key: value for key, value in slot.items() if key != "slot_observation_sha256"
        }
        slot["slot_observation_sha256"] = trace_module._sha256(slot_material)
        trace["slot_observation_graph_sha256"] = stable_sha256(
            [item["slot_observation_sha256"] for item in trace["slot_observations"]]
        )
    trace_material = {key: value for key, value in trace.items() if key != "trace_sha256"}
    trace["trace_sha256"] = trace_module._sha256(trace_material)


def test_exact_446_slot_abi_and_non_authorizing_artifact() -> None:
    names = tuple(name for name, _source in FEATURE_SPEC)
    requirements = feature_requirement_classes_for_names(names)
    assert len(names) == FEATURE_RESOLUTION_TRACE_V4_SLOT_COUNT == 446
    assert requirements.count("REQUIRED") == 383
    assert requirements.count("OPTIONAL_EVENT_DEPENDENT") == 63
    assert stable_sha256(feature_abi_contract(names)) == FEATURE_RESOLUTION_TRACE_V4_ABI_SHA256

    artifact = build_feature_resolution_trace_v4(
        tensor=_tensor(),
        raw_context_sha256=_SHA_D,
        observations=_observations(_tensor()),
    )
    trace = artifact.trace
    assert isinstance(artifact, FeatureResolutionTraceArtifactV4)
    assert len(trace["slot_observations"]) == 446
    assert len({slot["feature_name"] for slot in trace["slot_observations"]}) == 446
    assert trace["resolved_slot_count"] == 446
    assert trace["complete_slot_observation_set"] is True
    assert trace["declared_point_in_time_order_valid"] is True
    assert trace["required_value_contract_valid"] is True
    for field in trace_module._FALSE_FIELDS:
        assert trace[field] is False
        assert getattr(artifact, field) is False


def test_trace_creation_is_float32_byte_tensor_id_and_record_neutral() -> None:
    tensor = _tensor()
    before_bytes = _model_bytes(tensor)
    before_record = tensor
    artifact = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    )
    assert tensor is before_record
    assert tensor.tensor_id == "tensor_v4_test"
    assert _model_bytes(tensor) == before_bytes
    assert artifact.trace["tensor_binding"]["model_vector_float32_be_sha256"] == (
        hashlib.sha256(before_bytes).hexdigest()
    )


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("missing_nonzero", "TENSOR_MISSING_VALUE_NOT_ZERO"),
        ("missing_but_available", "TENSOR_MISSING_AVAILABILITY_MISMATCH"),
        ("present_but_unavailable", "TENSOR_MISSING_AVAILABILITY_MISMATCH"),
    ],
)
def test_forged_tensor_missing_value_and_availability_states_fail_closed(
    mode: str,
    reason: str,
) -> None:
    original = _tensor()
    values = list(original.values)
    missing = list(original.missing_mask)
    available = list(original.source_availability)
    if mode == "missing_nonzero":
        missing[0] = 1
        available[0] = 0
    elif mode == "missing_but_available":
        values[0] = 0.0
        missing[0] = 1
    else:
        available[0] = 0
    tensor = replace(
        original,
        values=tuple(values),
        missing_mask=tuple(missing),
        source_availability=tuple(available),
        source_availability_vector=tuple(available),
        missing_feature_names=(original.feature_names[0],) if missing[0] else (),
        data_coverage_percent=(100.0 * (len(FEATURE_SPEC) - sum(missing)) / len(FEATURE_SPEC)),
    )
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match=reason):
        build_feature_resolution_trace_v4(
            tensor=tensor,
            raw_context_sha256=_SHA_D,
            observations=_observations(tensor),
        )


@pytest.mark.parametrize("binary_alias", [1.0, True])
def test_forged_source_availability_vector_type_aliases_fail_closed(
    binary_alias: object,
) -> None:
    original = _tensor()
    vector: list[object] = list(original.source_availability_vector)
    vector[0] = binary_alias
    forged = replace(
        original,
        source_availability_vector=cast(tuple[int, ...], tuple(vector)),
    )
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="TENSOR_MASK_INVALID"):
        build_feature_resolution_trace_v4(
            tensor=forged,
            raw_context_sha256=_SHA_D,
            observations=_observations(forged),
        )


@pytest.mark.parametrize("invalid_rejections", ["", [], None])
def test_temporal_rejection_reasons_must_be_exact_empty_tuple(
    invalid_rejections: object,
) -> None:
    original = _tensor()
    forged = replace(
        original,
        temporal_rejection_reasons=cast(tuple[str, ...], invalid_rejections),
    )
    with pytest.raises(
        FeatureResolutionTraceV4ValidationError,
        match="TENSOR_TEMPORAL_REJECTION_PRESENT",
    ):
        build_feature_resolution_trace_v4(
            tensor=forged,
            raw_context_sha256=_SHA_D,
            observations=_observations(forged),
        )


@pytest.mark.parametrize(
    ("feature_name", "required_valid"),
    [
        ("last_price", False),
        ("coinapi_wsds_tape_imbalance", True),
        ("last_liq_bps_24h", True),
    ],
)
def test_typed_negatives_are_explicit_and_never_authorize(
    feature_name: str,
    required_valid: bool,
) -> None:
    index = [name for name, _source in FEATURE_SPEC].index(feature_name)
    tensor = _tensor(negative_index=index)
    artifact = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    )
    trace = artifact.trace
    slot = trace["slot_observations"][index]
    assert slot["resolution_status"] == RESOLUTION_STATUS_TYPED_NEGATIVE
    assert slot["negative_reason"] == NEGATIVE_SOURCE_UNAVAILABLE
    assert slot["negative_evidence_sha256"] == _SHA_D
    assert trace["required_value_contract_valid"] is required_valid
    assert trace["consumer_eligible"] is False
    assert trace["trainer_admission_granted"] is False


def test_stale_mask_requires_source_stale_reason_and_source_evidence() -> None:
    tensor = _tensor(negative_index=0, stale=True)
    observations = list(_observations(tensor))
    valid = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=observations,
    )
    assert valid.trace["slot_observations"][0]["negative_reason"] == NEGATIVE_SOURCE_STALE

    stale = observations[0]
    stale_candle_kwargs = {
        field: getattr(stale, field)
        for field in stale.__dataclass_fields__
        if field != "_construction_token"
    }
    stale_candle_kwargs.update(
        candle_close_time="2026-07-20T00:00:00.300000Z",
        candle_final=True,
    )
    with pytest.raises(
        FeatureResolutionObservationV4ValidationError,
        match="CANDLE_CLOSE_NOT_BEFORE_AVAILABLE_AT",
    ):
        build_feature_slot_resolution_observation_v4(**stale_candle_kwargs)

    kwargs = {
        field: getattr(stale, field)
        for field in stale.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs.update(
        negative_reason=NEGATIVE_SOURCE_UNAVAILABLE,
        source_root_sha256=None,
        event_time=None,
        ingested_at=None,
        available_at=None,
        generated_at=None,
    )
    observations[0] = build_feature_slot_resolution_observation_v4(**kwargs)
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="STALE_REASON_MASK"):
        build_feature_resolution_trace_v4(
            tensor=tensor,
            raw_context_sha256=_SHA_D,
            observations=observations,
        )


def test_source_stale_reason_requires_stale_mask_and_missing_stale_is_supported() -> None:
    missing_only = _tensor(negative_index=0)
    observations = list(_observations(missing_only))
    unavailable = observations[0]
    kwargs = {
        field: getattr(unavailable, field)
        for field in unavailable.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs.update(
        negative_reason=NEGATIVE_SOURCE_STALE,
        source_root_sha256=_SHA_C,
        event_time="2026-07-20T00:00:00.000000Z",
        ingested_at="2026-07-20T00:00:00.100000Z",
        available_at="2026-07-20T00:00:00.300000Z",
        generated_at="2026-07-20T00:00:00.200000Z",
    )
    observations[0] = build_feature_slot_resolution_observation_v4(**kwargs)
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="STALE_REASON_MASK"):
        build_feature_resolution_trace_v4(
            tensor=missing_only,
            raw_context_sha256=_SHA_D,
            observations=observations,
        )

    stale_mask = list(missing_only.stale_mask)
    stale_mask[0] = 1
    missing_and_stale = replace(
        missing_only,
        stale_mask=tuple(stale_mask),
        stale_feature_names=(missing_only.feature_names[0],),
    )
    accepted = build_feature_resolution_trace_v4(
        tensor=missing_and_stale,
        raw_context_sha256=_SHA_D,
        observations=_observations(missing_and_stale),
    )
    assert accepted.trace["slot_observations"][0]["negative_reason"] == (NEGATIVE_SOURCE_STALE)


def test_external_validator_rechecks_stale_reason_mask_equivalence() -> None:
    tensor = _tensor(negative_index=0, stale=True)
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    ).trace
    slot = trace["slot_observations"][0]
    slot.update(
        negative_reason=NEGATIVE_SOURCE_UNAVAILABLE,
        source_root_sha256=None,
        event_time=None,
        ingested_at=None,
        available_at=None,
        generated_at=None,
    )
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="STALE_REASON_MASK"):
        validate_feature_resolution_trace_v4(trace)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered"])
def test_observation_set_rejects_missing_duplicate_or_reordered(mutation: str) -> None:
    tensor = _tensor()
    observations = list(_observations(tensor))
    if mutation == "missing":
        observations.pop()
    elif mutation == "duplicate":
        observations[-1] = observations[0]
    else:
        observations[0], observations[1] = observations[1], observations[0]
    with pytest.raises(FeatureResolutionTraceV4ValidationError):
        build_feature_resolution_trace_v4(
            tensor=tensor,
            raw_context_sha256=_SHA_D,
            observations=observations,
        )


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"available_at": "2026-07-20T00:00:01.100000Z"}, "AVAILABLE_AT_AFTER_DECISION"),
        ({"feature_cutoff": "2026-07-20T00:00:01.100000Z"}, "FEATURE_CUTOFF_AFTER_DECISION"),
        (
            {"masa_feature_cutoff": "2026-07-20T00:00:01.100000Z"},
            "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION",
        ),
        (
            {
                "candle_close_time": "2026-07-20T00:00:00.400000Z",
                "candle_final": False,
            },
            "UNFINISHED_CANDLE",
        ),
        (
            {
                "candle_close_time": "2026-07-20T00:00:00.300000Z",
                "candle_final": True,
            },
            "CANDLE_CLOSE_NOT_BEFORE_AVAILABLE_AT",
        ),
    ],
)
def test_observation_factory_fails_closed_on_pit_and_finality(
    override: dict[str, object],
    reason: str,
) -> None:
    tensor = _tensor()
    base = _observation(tensor, 0)
    kwargs = {
        field: getattr(base, field)
        for field in base.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs.update(override)
    with pytest.raises(FeatureResolutionObservationV4ValidationError) as exc:
        build_feature_slot_resolution_observation_v4(**kwargs)
    assert reason in str(exc.value)


@pytest.mark.parametrize(
    ("decision_time", "consumer_observed_at", "feature_cutoff", "candle_close_time"),
    [
        (_DECISION, _OBSERVED, _DECISION, _DECISION),
        (_OBSERVED, _OBSERVED, _OBSERVED, _OBSERVED),
    ],
)
def test_candle_close_is_strictly_before_decision_and_transitively_consumer(
    decision_time: str,
    consumer_observed_at: str,
    feature_cutoff: str,
    candle_close_time: str,
) -> None:
    negative = _observation(_tensor(negative_index=0), 0)
    kwargs = {
        field: getattr(negative, field)
        for field in negative.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs.update(
        decision_time=decision_time,
        consumer_observed_at=consumer_observed_at,
        feature_cutoff=feature_cutoff,
        masa_feature_cutoff=feature_cutoff,
        candle_close_time=candle_close_time,
        candle_final=True,
    )
    with pytest.raises(
        FeatureResolutionObservationV4ValidationError,
        match="CANDLE_CLOSE_NOT_BEFORE_DECISION_TIME",
    ):
        build_feature_slot_resolution_observation_v4(**kwargs)


@pytest.mark.parametrize(
    ("clock_name", "clock_value", "reason"),
    [
        (
            "event_time",
            "2026-07-20T00:00:01.100000Z",
            "EVENT_TIME_AFTER_DECISION_TIME",
        ),
        (
            "ingested_at",
            "2026-07-20T00:00:01.100000Z",
            "INGESTED_AT_AFTER_DECISION_TIME",
        ),
        (
            "generated_at",
            "2026-07-20T00:00:01.100000Z",
            "GENERATED_AT_AFTER_DECISION_TIME",
        ),
        (
            "available_at",
            "2026-07-20T00:00:01.100000Z",
            "AVAILABLE_AT_AFTER_DECISION_TIME",
        ),
        (
            "execution_time",
            "2026-07-20T00:00:02.100000Z",
            "EXECUTION_TIME_AFTER_CONSUMER_OBSERVED_AT",
        ),
    ],
)
def test_nonstale_negative_supplied_clocks_are_still_causally_bounded(
    clock_name: str,
    clock_value: str,
    reason: str,
) -> None:
    negative = _observation(_tensor(negative_index=0), 0)
    kwargs = {
        field: getattr(negative, field)
        for field in negative.__dataclass_fields__
        if field != "_construction_token"
    }
    assert kwargs["available_at"] is None
    kwargs[clock_name] = clock_value
    with pytest.raises(FeatureResolutionObservationV4ValidationError, match=reason):
        build_feature_slot_resolution_observation_v4(**kwargs)


def test_supplied_event_time_cannot_follow_generated_at() -> None:
    negative = _observation(_tensor(negative_index=0), 0)
    kwargs = {
        field: getattr(negative, field)
        for field in negative.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs.update(
        event_time="2026-07-20T00:00:00.250000Z",
        generated_at="2026-07-20T00:00:00.200000Z",
    )
    with pytest.raises(
        FeatureResolutionObservationV4ValidationError,
        match="EVENT_TIME_AFTER_GENERATED_AT",
    ):
        build_feature_slot_resolution_observation_v4(**kwargs)


def test_downstream_generation_cannot_precede_source_ingestion() -> None:
    resolved = _observation(_tensor(), 0)
    kwargs = {
        field: getattr(resolved, field)
        for field in resolved.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs["generated_at"] = "2026-07-20T00:00:00.050000Z"
    with pytest.raises(
        FeatureResolutionObservationV4ValidationError,
        match="INGESTED_AT_AFTER_GENERATED_AT",
    ):
        build_feature_slot_resolution_observation_v4(**kwargs)


def test_fully_rehashed_trace_cannot_hide_generation_before_ingestion() -> None:
    tensor = _tensor()
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    ).trace
    trace["slot_observations"][0]["generated_at"] = "2026-07-20T00:00:00.050000Z"
    _rehash_external_trace(trace, changed_slot_index=0)
    with pytest.raises(
        FeatureResolutionTraceV4ValidationError,
        match="INGESTED_AT_AFTER_GENERATED_AT",
    ):
        validate_feature_resolution_trace_v4(trace)


def test_external_rehash_cannot_hide_unbounded_negative_clock() -> None:
    tensor = _tensor(negative_index=0)
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    ).trace
    trace["slot_observations"][0]["generated_at"] = "2026-07-20T00:00:01.100000Z"
    _rehash_external_trace(trace, changed_slot_index=0)
    with pytest.raises(
        FeatureResolutionTraceV4ValidationError,
        match="GENERATED_AT_AFTER_DECISION_TIME",
    ):
        validate_feature_resolution_trace_v4(trace)


def test_generic_missing_reason_and_forged_identity_transform_are_rejected() -> None:
    tensor = _tensor(negative_index=0)
    negative = _observation(tensor, 0)
    kwargs = {
        field: getattr(negative, field)
        for field in negative.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs["negative_reason"] = "MISSING"
    with pytest.raises(FeatureResolutionObservationV4ValidationError):
        build_feature_slot_resolution_observation_v4(**kwargs)

    resolved = _observation(_tensor(), 0)
    kwargs = {
        field: getattr(resolved, field)
        for field in resolved.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs["selected_path"] = ("different_payload", resolved.selected_key)
    with pytest.raises(
        FeatureResolutionObservationV4ValidationError,
        match="SELECTOR_PARTIAL",
    ):
        build_feature_slot_resolution_observation_v4(**kwargs)

    kwargs = {
        field: getattr(resolved, field)
        for field in resolved.__dataclass_fields__
        if field != "_construction_token"
    }
    kwargs["transform_code_sha256"] = "f" * 64
    with pytest.raises(FeatureResolutionObservationV4ValidationError):
        build_feature_slot_resolution_observation_v4(**kwargs)


def test_equal_valued_candidates_are_not_inferred_or_silently_collapsed() -> None:
    tensor = _tensor()
    observations_a = list(_observations(tensor))
    observations_b = list(observations_a)
    observations_a[0] = _observation(
        tensor,
        0,
        selected_key="price",
        selected_alias="price",
    )
    observations_b[0] = _observation(
        tensor,
        0,
        selected_key="last",
        selected_alias="last",
    )
    trace_a = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=observations_a,
    )
    trace_b = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=observations_b,
    )
    assert trace_a.trace["slot_observations"][0]["selected_key"] == "price"
    assert trace_b.trace["slot_observations"][0]["selected_key"] == "last"
    assert trace_a.trace_sha256 != trace_b.trace_sha256
    assert trace_a.raw_context_cas_verified is False
    assert trace_b.resolver_branch_capture_authenticated is False


@pytest.mark.parametrize(
    "binding_field",
    [
        "ordered_source_labels_sha256",
        "missing_mask_sha256",
        "stale_mask_sha256",
        "source_availability_mask_sha256",
        "model_vector_float32_be_sha256",
    ],
)
def test_external_validation_reconstructs_tensor_binding_hashes(binding_field: str) -> None:
    tensor = _tensor()
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    ).trace
    trace["tensor_binding"][binding_field] = "f" * 64
    with pytest.raises(
        FeatureResolutionTraceV4ValidationError,
        match="TENSOR_BINDING_RECONSTRUCTION_MISMATCH",
    ):
        validate_feature_resolution_trace_v4(trace)


@pytest.mark.parametrize(
    ("field_name", "malicious_value", "reason"),
    [
        ("tensor_value", True, "TENSOR_VALUE_NOT_EXACT_FLOAT"),
        ("resolved_value", True, "RESOLVED_VALUE_NOT_EXACT_FLOAT"),
        ("tensor_value", 1, "TENSOR_VALUE_NOT_EXACT_FLOAT"),
        ("resolved_value", 1, "RESOLVED_VALUE_NOT_EXACT_FLOAT"),
        ("tensor_value", 1.00000001, "TENSOR_VALUE_NOT_CANONICAL_FLOAT32"),
        ("resolved_value", 1.00000001, "RESOLVED_VALUE_NOT_CANONICAL_FLOAT32"),
        ("tensor_value", -0.0, "TENSOR_VALUE_NEGATIVE_ZERO_FORBIDDEN"),
        ("resolved_value", -0.0, "RESOLVED_VALUE_NEGATIVE_ZERO_FORBIDDEN"),
        ("resolved_value", 2.0, "RESOLVED_RAW_SCALAR_MISMATCH"),
    ],
)
def test_external_rehash_cannot_create_float32_scalar_aliases(
    field_name: str,
    malicious_value: object,
    reason: str,
) -> None:
    tensor = _tensor()
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    ).trace
    trace["slot_observations"][0][field_name] = malicious_value
    _rehash_external_trace(trace, changed_slot_index=0)
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match=reason):
        validate_feature_resolution_trace_v4(trace)


@pytest.mark.parametrize("malicious_count", [7136.0, True, 7132])
def test_external_rehash_rejects_model_vector_byte_count_type_aliases(
    malicious_count: object,
) -> None:
    tensor = _tensor()
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    ).trace
    trace["tensor_binding"]["model_vector_float32_be_byte_count"] = malicious_count
    _rehash_external_trace(trace)
    with pytest.raises(
        FeatureResolutionTraceV4ValidationError,
        match="MODEL_VECTOR_BYTE_COUNT_INVALID",
    ):
        validate_feature_resolution_trace_v4(trace)


def test_artifact_is_factory_only_and_tamper_evident() -> None:
    tensor = _tensor()
    artifact = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    )
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="FACTORY_CONSTRUCTION"):
        FeatureResolutionTraceArtifactV4(
            schema_version=artifact.schema_version,
            trace_sha256=artifact.trace_sha256,
            trace_json=artifact.trace_json,
            _construction_token=object(),
        )
    trace = artifact.trace
    trace["slot_observations"][0]["selected_alias"] = "tampered"
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="SLOT_SHA256_MISMATCH"):
        validate_feature_resolution_trace_v4(trace)


def test_recursive_external_json_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tensor = _tensor()
    artifact = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=_SHA_D,
        observations=_observations(tensor),
    )

    def raise_recursion(*_args: object, **_kwargs: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", raise_recursion)
    with pytest.raises(FeatureResolutionTraceV4ValidationError, match="JSON_INVALID"):
        _ = artifact.trace


def test_observation_leaf_is_stdlib_only_and_runtime_remains_unwired() -> None:
    leaf_path = Path(observation_module.__file__)
    tree = ast.parse(leaf_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "datetime",
        "hashlib",
        "json",
        "math",
        "re",
        "struct",
        "typing",
    }

    app_root = leaf_path.parents[2]
    allowed_audit_only_consumers = {
        app_root / "services" / "native_trainer" / "authenticated_feature_resolution_capture_v4.py",
    }
    imports = []
    for path in app_root.rglob("*.py"):
        if path in {
            leaf_path,
            Path(trace_module.__file__),
            *allowed_audit_only_consumers,
        }:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if any(
            module_name in source
            for module_name in (
                "feature_resolution_observation_v4",
                "feature_resolution_trace_v4",
            )
        ):
            imports.append(path)
    assert imports == []


def test_audit_only_capture_import_closure_excludes_runtime_and_paper_paths() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    script = r"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import v2.backend.app.services.native_trainer.authenticated_feature_resolution_capture_v4

print(json.dumps(sorted(
    name for name in sys.modules if name == "v2" or name.startswith("v2.")
)))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and static import probe
        [sys.executable, "-I", "-B", "-c", script, str(repo_root)],
        cwd="/",
        env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [
        "v2",
        "v2.backend",
        "v2.backend.app",
        "v2.backend.app.services",
        "v2.backend.app.services.native_trainer",
        ("v2.backend.app.services.native_trainer." "authenticated_feature_resolution_capture_v4"),
        "v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger",
        "v2.backend.app.services.native_trainer.feature_resolution_observation_v4",
        "v2.backend.app.services.native_trainer.feature_resolution_trace_v4",
        "v2.backend.app.services.native_trainer.feature_source_registry_v4",
        "v2.backend.app.services.native_trainer.ordered_feature_tensor_spec_v3",
    ]
