from __future__ import annotations

import copy
import hashlib
import struct
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as ledger_module,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
    FeatureTensorRecord,
)

EXPECTED_LEDGER_SCHEMA_VERSION = "durable_feature_snapshot_ledger_v3"
EXPECTED_ENVELOPE_SCHEMA_VERSION = "canonical_feature_tensor_envelope_v3"
EXPECTED_RECORD_SCHEMA_VERSION = "canonical_feature_snapshot_record_v3"
EXPECTED_FEATURE_ABI_SCHEMA_VERSION = "ordered_feature_tensor_abi_v3"
EXPECTED_SOURCE_RECEIPT_SCHEMA_VERSION = "feature_source_consumer_read_receipt_v3"
EXPECTED_PROVENANCE = "CANONICAL_RECEIPT_BACKED_V3"
EXPECTED_BINDING_SCHEMA_VERSION = "feature_source_binding_vector_v1"
EXPECTED_REQUIREMENT_POLICY_ID = "v2_hybrid_feature_requirements_v1"
EXPECTED_MODEL_VECTOR_DOMAIN = b"canonical_feature_model_vector_v3\0"
EXPECTED_BLOCK_ORDER = [
    "feature_values",
    "missing_mask",
    "stale_mask",
    "source_availability_mask",
]

LIVE_FEATURE_COUNT = 446
LIVE_MODEL_INPUT_COUNT = LIVE_FEATURE_COUNT * 4
LIVE_STATIC_SOURCE_COUNT = 40
LIVE_TA_FULL_SOURCE_MULTIPLICITY = 155

BASE = datetime(2025, 1, 1, tzinfo=UTC)


class _BombSequence(Sequence[Mapping[str, str]]):
    def __init__(self, length: int) -> None:
        self.length = length
        self.length_called = False
        self.consumed = False

    def __len__(self) -> int:
        self.length_called = True
        return self.length

    def __getitem__(self, index: int) -> Mapping[str, str]:
        self.consumed = True
        raise AssertionError(f"bomb_sequence_consumed:{index}")

    def __iter__(self) -> Iterator[Mapping[str, str]]:
        self.consumed = True
        raise AssertionError("bomb_sequence_consumed")


class _BombMapping(Mapping[str, Any]):
    def __init__(self, length: int) -> None:
        self.length = length
        self.length_called = False
        self.consumed = False

    def __len__(self) -> int:
        self.length_called = True
        return self.length

    def __getitem__(self, key: str) -> Any:
        self.consumed = True
        raise AssertionError(f"bomb_mapping_consumed:{key}")

    def __iter__(self) -> Iterator[str]:
        self.consumed = True
        raise AssertionError("bomb_mapping_consumed")


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _receipt(
    source_label: str,
    *,
    offset_seconds: int = 0,
    offset_milliseconds: int = 0,
    available_delay_ms: int = 100,
    consumer_observed_delay_ms: int = 200,
    feature_cutoff_delay_ms: int = 300,
    finality_cutoff_delay_ms: int = 50,
    finality_verified_delay_ms: int = 150,
    receipt_kind: str = "DIRECT_READ",
    child_read_bindings: Sequence[Mapping[str, str]] = (),
    derivation_material: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Exercise the proposed v3 receipt API with deterministic causal clocks."""

    event = BASE + timedelta(
        seconds=offset_seconds,
        milliseconds=offset_milliseconds,
    )
    return ledger_module.build_source_read_receipt(
        source_label=source_label,
        payload_type=(
            "CANONICAL_COMPOSITE_FEATURE_PAYLOAD"
            if receipt_kind == "COMPOSITE_DERIVATION"
            else "CANONICAL_SOURCE_PAYLOAD"
        ),
        payload_sha256=_sha256_text(
            f"payload:{source_label}:{offset_seconds}:{receipt_kind}"
        ),
        payload_byte_count=128,
        event_time=_utc(event),
        available_at=_utc(event + timedelta(milliseconds=available_delay_ms)),
        consumer_observed_at=_utc(
            event + timedelta(milliseconds=consumer_observed_delay_ms)
        ),
        feature_cutoff=_utc(
            event + timedelta(milliseconds=feature_cutoff_delay_ms)
        ),
        read_locator_type="IN_MEMORY_IMMUTABLE_OBJECT",
        read_locator=f"unit/live-abi/{source_label}/{offset_seconds}",
        read_locator_version=f"snapshot:{offset_seconds}",
        finality_type="VERSIONED_SNAPSHOT",
        finality_cutoff=_utc(
            event + timedelta(milliseconds=finality_cutoff_delay_ms)
        ),
        finality_verified_at=_utc(
            event + timedelta(milliseconds=finality_verified_delay_ms)
        ),
        finality_verifier="live-abi-unit-finality-gate",
        receipt_kind=receipt_kind,
        child_read_bindings=child_read_bindings,
        derivation_material=derivation_material,
    )


def _live_tensor() -> FeatureTensorRecord:
    names = tuple(name for name, _source in FEATURE_SPEC)
    sources = tuple(source for _name, source in FEATURE_SPEC)
    # Binary fractions remain exact through the canonical float32 conversion.
    values = tuple((index - (len(names) // 2)) / 16.0 for index in range(len(names)))
    zeros = (0,) * len(names)
    ones = (1,) * len(names)
    return FeatureTensorRecord(
        tensor_id="v2_hybrid_tensor_live_abi_fixture",
        symbol="BTCUSDT",
        timeframe="5m",
        feature_snapshot_id="v2_fsnap_live_abi_fixture",
        values=values,
        missing_mask=zeros,
        stale_mask=zeros,
        source_availability=ones,
        feature_names=names,
        source_labels=sources,
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=ones,
        decision_time=_utc(BASE + timedelta(seconds=8)),
        source_lineage_hash=_sha256_text("live-abi-source-lineage"),
        temporal_rejection_reasons=(),
    )


def _direct_receipts(
    labels: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    by_label = {label: _receipt(label) for label in sorted(set(labels))}
    return list(by_label.values()), by_label


def _record(
    *,
    tensor: FeatureTensorRecord | None = None,
    receipts: Sequence[Mapping[str, Any]] | None = None,
    bindings: Sequence[str | None] | None = None,
    requirement_classes: Sequence[str] | None = None,
    requirement_policy_id: str = EXPECTED_REQUIREMENT_POLICY_ID,
) -> dict[str, Any]:
    """Freeze the expected public v3 record-builder keyword contract."""

    tensor = tensor or _live_tensor()
    defaults, by_label = _direct_receipts(tensor.source_labels)
    resolved_bindings = (
        list(bindings)
        if bindings is not None
        else [str(by_label[label]["receipt_sha256"]) for label in tensor.source_labels]
    )
    return ledger_module.build_feature_snapshot_record(
        provenance_classification=EXPECTED_PROVENANCE,
        legacy_v1_snapshot_id=None,
        symbol=tensor.symbol,
        timeframe=tensor.timeframe,
        feature_snapshot_id=tensor.feature_snapshot_id,
        tensor_decision_time=str(tensor.decision_time),
        temporal_rejection_reasons=list(tensor.temporal_rejection_reasons),
        ordered_feature_names=list(tensor.feature_names),
        feature_values=list(tensor.values),
        missing_mask=list(tensor.missing_mask),
        stale_mask=list(tensor.stale_mask),
        source_availability_mask=list(tensor.source_availability),
        ordered_feature_source_labels=list(tensor.source_labels),
        feature_source_receipt_sha256s=resolved_bindings,
        source_read_receipts=list(receipts) if receipts is not None else defaults,
        feature_requirement_policy_id=requirement_policy_id,
        ordered_feature_requirement_classes=list(
            requirement_classes
            if requirement_classes is not None
            else ledger_module.feature_requirement_classes_for_names(
                tensor.feature_names
            )
        ),
        original_tensor_id=tensor.tensor_id,
        source_lineage_material={
            "schema_version": "live_feature_tensor_lineage_fixture_v1",
            "producer": "test_durable_feature_snapshot_ledger_live_abi",
            "source_lineage_hash": tensor.source_lineage_hash,
        },
        feature_cutoff=_utc(BASE + timedelta(seconds=5)),
        masa_feature_cutoff=_utc(BASE + timedelta(seconds=6)),
        ppo_feature_cutoff=_utc(BASE + timedelta(seconds=7)),
        ppo_decision_time=_utc(BASE + timedelta(seconds=9)),
        generated_at=_utc(BASE + timedelta(seconds=7, milliseconds=500)),
    )


def _model_vector_sha256(envelope: Mapping[str, Any]) -> str:
    vector = (
        list(envelope["feature_values"])
        + list(envelope["missing_mask"])
        + list(envelope["stale_mask"])
        + list(envelope["source_availability_mask"])
    )
    digest = hashlib.sha256()
    digest.update(EXPECTED_MODEL_VECTOR_DOMAIN)
    digest.update(bytes.fromhex(str(envelope["feature_abi_sha256"])))
    digest.update(struct.pack(">I", len(envelope["ordered_feature_names"])))
    for value in vector:
        digest.update(struct.pack(">f", float(value)))
    return digest.hexdigest()


def _composite_material(
    *,
    include_children: bool = True,
    include_orphan: bool = False,
    child_offset_seconds: int = 0,
    child_receipt_kwargs: Mapping[str, int] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    tensor = _live_tensor()
    direct, by_label = _direct_receipts(tensor.source_labels)
    child_kwargs = {"offset_seconds": child_offset_seconds}
    child_kwargs.update(dict(child_receipt_kwargs or {}))
    children = [
        _receipt("raw:closed_ohlcv", **child_kwargs),
        _receipt("raw:versioned_orderbook", **child_kwargs),
    ]
    parent = _receipt(
        "v2:features:latest",
        offset_seconds=1,
        receipt_kind="COMPOSITE_DERIVATION",
        child_read_bindings=[
            {
                "input_role": "ohlcv/closed/000000",
                "receipt_sha256": str(children[0]["receipt_sha256"]),
            },
            {
                "input_role": "orderbook/versioned/000000",
                "receipt_sha256": str(children[1]["receipt_sha256"]),
            },
        ],
        derivation_material={
            "schema_version": "feature_source_derivation_v1",
            "producer_id": "v2_feature_pipeline_native",
            "producer_version": "v2_native_feature_snapshot_v1",
            "transform_sha256": _sha256_text("live-composite-transform-v1"),
            "configuration_sha256": _sha256_text("live-composite-config-v1"),
        },
    )
    direct.remove(by_label["v2:features:latest"])
    receipts = [*direct, parent, *(children if include_children else [])]
    if include_orphan:
        receipts.append(_receipt("raw:orphaned_source"))
    roots = dict(by_label)
    roots["v2:features:latest"] = parent
    bindings = [str(roots[label]["receipt_sha256"]) for label in tensor.source_labels]
    return receipts, bindings


def test_v3_public_contract_versions_are_explicit() -> None:
    assert ledger_module.LEDGER_SCHEMA_VERSION == EXPECTED_LEDGER_SCHEMA_VERSION
    assert (
        ledger_module.FROZEN_ENVELOPE_SCHEMA_VERSION
        == EXPECTED_ENVELOPE_SCHEMA_VERSION
    )
    assert ledger_module.RECORD_SCHEMA_VERSION == EXPECTED_RECORD_SCHEMA_VERSION
    assert (
        ledger_module.FEATURE_ABI_SCHEMA_VERSION
        == EXPECTED_FEATURE_ABI_SCHEMA_VERSION
    )
    assert (
        ledger_module.SOURCE_READ_RECEIPT_SCHEMA_VERSION
        == EXPECTED_SOURCE_RECEIPT_SCHEMA_VERSION
    )
    assert ledger_module.PROVENANCE_CANONICAL_V3 == EXPECTED_PROVENANCE


def test_live_feature_spec_freezes_446_by_4_layout_and_duplicate_sources() -> None:
    tensor = _live_tensor()
    assert len(FEATURE_SPEC) == LIVE_FEATURE_COUNT
    assert len(tensor.model_vector) == LIVE_MODEL_INPUT_COUNT
    assert len(set(tensor.source_labels)) == LIVE_STATIC_SOURCE_COUNT
    assert (
        tensor.source_labels.count("v2:features:ta_full")
        == LIVE_TA_FULL_SOURCE_MULTIPLICITY
    )
    assert len(
        {
            len(tensor.values),
            len(tensor.missing_mask),
            len(tensor.stale_mask),
            len(tensor.source_availability),
            len(tensor.source_availability_vector),
            len(tensor.feature_names),
            len(tensor.source_labels),
        }
    ) == 1


def test_live_446_tensor_round_trips_exact_1784_model_vector() -> None:
    tensor = _live_tensor()
    record = _record(tensor=tensor)
    envelope = record["frozen_envelope"]
    reconstructed = tuple(envelope["feature_values"]) + tuple(
        float(value) for value in envelope["missing_mask"]
    ) + tuple(float(value) for value in envelope["stale_mask"]) + tuple(
        float(value) for value in envelope["source_availability_mask"]
    )

    assert ledger_module.validate_feature_snapshot_record(record)[
        "strict_training_eligible"
    ] == 1
    assert reconstructed == tensor.model_vector
    assert len(reconstructed) == LIVE_MODEL_INPUT_COUNT
    assert envelope["ordered_feature_source_labels"] == list(tensor.source_labels)
    assert len(envelope["feature_source_receipt_sha256s"]) == LIVE_FEATURE_COUNT
    assert len(envelope["source_read_receipts"]) == LIVE_STATIC_SOURCE_COUNT
    assert envelope["feature_abi"]["model_vector"] == {
        "dtype": "float32",
        "encoding": "IEEE754_BINARY32_BIG_ENDIAN",
        "rank": 1,
        "shape": [LIVE_MODEL_INPUT_COUNT],
        "block_order": EXPECTED_BLOCK_ORDER,
        "block_width": LIVE_FEATURE_COUNT,
    }
    assert envelope["feature_abi"]["source_availability_mask"]["shape"] == [
        LIVE_FEATURE_COUNT
    ]
    assert envelope["model_vector_sha256"] == _model_vector_sha256(envelope)
    expected_binding_hash = ledger_module.stable_sha256(
        {
            "schema_version": EXPECTED_BINDING_SCHEMA_VERSION,
            "ordered_feature_names": list(tensor.feature_names),
            "ordered_feature_source_labels": list(tensor.source_labels),
            "feature_source_receipt_sha256s": envelope[
                "feature_source_receipt_sha256s"
            ],
        }
    )
    assert envelope["feature_source_bindings_sha256"] == expected_binding_hash


def test_dynamic_provider_route_changes_binding_but_not_model_abi() -> None:
    baseline_tensor = _live_tensor()
    baseline = _record(tensor=baseline_tensor)
    labels = list(baseline_tensor.source_labels)
    labels[baseline_tensor.feature_names.index("last_price")] = (
        "provider_feature_bridge"
    )
    rerouted_tensor = replace(baseline_tensor, source_labels=tuple(labels))
    rerouted = _record(tensor=rerouted_tensor)

    baseline_envelope = baseline["frozen_envelope"]
    rerouted_envelope = rerouted["frozen_envelope"]
    assert baseline_envelope["feature_abi_sha256"] == (
        rerouted_envelope["feature_abi_sha256"]
    )
    assert baseline_envelope["model_vector_sha256"] == (
        rerouted_envelope["model_vector_sha256"]
    )
    assert baseline_envelope["feature_source_bindings_sha256"] != (
        rerouted_envelope["feature_source_bindings_sha256"]
    )
    assert baseline["durable_snapshot_id"] != rerouted["durable_snapshot_id"]


def test_present_slots_require_exact_n_resolved_label_matching_bindings() -> None:
    tensor = _live_tensor()
    receipts, by_label = _direct_receipts(tensor.source_labels)
    bindings: list[str | None] = [
        str(by_label[label]["receipt_sha256"]) for label in tensor.source_labels
    ]
    bindings[0] = None
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="PRESENT_FEATURE_SOURCE_RECEIPT_MISSING|FEATURE_SOURCE_BINDING_MISSING",
    ):
        _record(tensor=tensor, receipts=receipts, bindings=bindings)

    bindings[0] = str(by_label["v2:market:funding"]["receipt_sha256"])
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="FEATURE_SOURCE_RECEIPT_LABEL_MISMATCH|SOURCE_LABEL_BINDING_MISMATCH",
    ):
        _record(tensor=tensor, receipts=receipts, bindings=bindings)


def test_repeated_logical_source_requires_one_exact_root_receipt() -> None:
    tensor = _live_tensor()
    receipts, by_label = _direct_receipts(tensor.source_labels)
    alternate_root = _receipt("v2:features:ta_full", offset_seconds=1)
    receipts.append(alternate_root)
    bindings = [
        str(by_label[label]["receipt_sha256"]) for label in tensor.source_labels
    ]
    repeated_indices = [
        index
        for index, source_label in enumerate(tensor.source_labels)
        if source_label == "v2:features:ta_full"
    ]
    bindings[repeated_indices[1]] = str(alternate_root["receipt_sha256"])

    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="FEATURE_SOURCE_LABEL_ROOT_RECEIPT_MISMATCH",
    ):
        _record(tensor=tensor, receipts=receipts, bindings=bindings)


def test_requirement_policy_is_code_owned_categorical_and_threshold_free() -> None:
    tensor = _live_tensor()
    index = tensor.feature_names.index("paper_position_present")
    values = list(tensor.values)
    missing = list(tensor.missing_mask)
    availability = list(tensor.source_availability)
    values[index] = 0.0
    missing[index] = 1
    availability[index] = 0
    masked = replace(
        tensor,
        values=tuple(values),
        missing_mask=tuple(missing),
        source_availability=tuple(availability),
        source_availability_vector=tuple(availability),
        missing_feature_names=(tensor.feature_names[index],),
        data_coverage_percent=100.0 * (LIVE_FEATURE_COUNT - 1) / LIVE_FEATURE_COUNT,
    )
    policy = list(
        ledger_module.feature_requirement_classes_for_names(tensor.feature_names)
    )
    assert policy[index] == "OPTIONAL_EVENT_DEPENDENT"
    assert policy[tensor.feature_names.index("last_price")] == "REQUIRED"

    optional = _record(tensor=masked, requirement_classes=policy)
    assert optional["frozen_envelope"]["strict_training_eligible"] is True
    assert all(
        "threshold" not in key.lower()
        for key in optional["frozen_envelope"]["feature_abi"]
    )
    assert "data_coverage_percent" not in optional["frozen_envelope"]

    attacker_policy = list(policy)
    attacker_policy[tensor.feature_names.index("last_price")] = (
        "OPTIONAL_EVENT_DEPENDENT"
    )
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="FEATURE_REQUIREMENT_CLASSES_POLICY_MISMATCH",
    ):
        _record(tensor=masked, requirement_classes=attacker_policy)
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="FEATURE_REQUIREMENT_POLICY_ID_MISMATCH",
    ):
        _record(
            tensor=masked,
            requirement_classes=policy,
            requirement_policy_id="attacker_selected_policy_v1",
        )

    forged = copy.deepcopy(optional)
    forged["frozen_envelope"]["feature_abi"][
        "ordered_feature_requirement_classes"
    ][tensor.feature_names.index("last_price")] = "OPTIONAL_EVENT_DEPENDENT"
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="FEATURE_REQUIREMENT_CLASSES_POLICY_MISMATCH",
    ):
        ledger_module.validate_feature_snapshot_record(forged)


def test_valid_composite_receipt_dag_binds_children_once() -> None:
    receipts, bindings = _composite_material()
    record = _record(receipts=receipts, bindings=bindings)
    envelope = record["frozen_envelope"]
    receipt_by_sha = {
        receipt["receipt_sha256"]: receipt
        for receipt in envelope["source_read_receipts"]
    }
    parent = next(
        receipt
        for receipt in envelope["source_read_receipts"]
        if receipt["source_label"] == "v2:features:latest"
    )

    assert parent["receipt_kind"] == "COMPOSITE_DERIVATION"
    assert parent["derivation_sha256"] == ledger_module.stable_sha256(
        parent["derivation_material"]
    )
    assert all(
        edge["receipt_sha256"] in receipt_by_sha
        for edge in parent["child_read_bindings"]
    )
    assert ledger_module.validate_feature_snapshot_record(record)[
        "strict_training_eligible"
    ] == 1


@pytest.mark.parametrize(
    ("include_children", "include_orphan", "child_offset_seconds", "reason"),
    [
        (
            False,
            False,
            0,
            "COMPOSITE_CHILD_RECEIPT_MISSING|SOURCE_RECEIPT_GRAPH_CHILD_MISSING",
        ),
        (
            True,
            True,
            0,
            "SOURCE_RECEIPT_ORPHAN|SOURCE_RECEIPT_GRAPH_UNREACHABLE",
        ),
        (
            True,
            False,
            2,
            "COMPOSITE_CHILD_.*AFTER_PARENT|SOURCE_RECEIPT_GRAPH_CLOCK_ORDER",
        ),
    ],
)
def test_composite_receipt_dag_fails_closed(
    include_children: bool,
    include_orphan: bool,
    child_offset_seconds: int,
    reason: str,
) -> None:
    receipts, bindings = _composite_material(
        include_children=include_children,
        include_orphan=include_orphan,
        child_offset_seconds=child_offset_seconds,
    )
    with pytest.raises(ledger_module.FeatureSnapshotValidationError, match=reason):
        _record(receipts=receipts, bindings=bindings)


@pytest.mark.parametrize(
    ("child_receipt_kwargs", "exact_reason"),
    [
        (
            {
                "offset_seconds": 1,
                "offset_milliseconds": 50,
                "available_delay_ms": 10,
                "finality_cutoff_delay_ms": 5,
                "finality_verified_delay_ms": 12,
                "consumer_observed_delay_ms": 14,
                "feature_cutoff_delay_ms": 15,
            },
            "COMPOSITE_CHILD_EVENT_TIME_AFTER_PARENT",
        ),
        (
            {"consumer_observed_delay_ms": 1_120},
            "COMPOSITE_CHILD_CONSUMER_OBSERVED_AT_AFTER_PARENT_AVAILABLE_AT",
        ),
        (
            {
                "finality_verified_delay_ms": 1_120,
                "consumer_observed_delay_ms": 1_130,
            },
            "COMPOSITE_CHILD_FINALITY_VERIFIED_AT_AFTER_PARENT_AVAILABLE_AT",
        ),
        (
            {
                "finality_verified_delay_ms": 1_160,
                "consumer_observed_delay_ms": 1_170,
            },
            "COMPOSITE_CHILD_FINALITY_VERIFIED_AT_AFTER_PARENT",
        ),
    ],
)
def test_composite_child_clocks_are_fully_causal_before_parent_derivation(
    child_receipt_kwargs: Mapping[str, int],
    exact_reason: str,
) -> None:
    receipts, bindings = _composite_material(
        child_receipt_kwargs=child_receipt_kwargs
    )
    with pytest.raises(ledger_module.FeatureSnapshotValidationError) as exc_info:
        _record(receipts=receipts, bindings=bindings)
    assert exact_reason in exc_info.value.reasons


def test_source_receipt_builder_bounds_containers_without_consuming_bombs() -> None:
    oversized_children = [{}] * (ledger_module.MAX_SOURCE_RECEIPTS + 1)
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_CHILD_BINDING_COUNT_EXCEEDED",
    ):
        _receipt("raw:oversized_children", child_read_bindings=oversized_children)

    custom_children = _BombSequence(ledger_module.MAX_SOURCE_RECEIPTS + 1)
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_CHILD_BINDINGS_NOT_BOUNDED_SEQUENCE",
    ):
        _receipt("raw:custom_children", child_read_bindings=custom_children)
    assert custom_children.length_called is False
    assert custom_children.consumed is False

    oversized_binding = {
        "input_role": "raw/input",
        "receipt_sha256": "a" * 64,
        "unexpected": "field",
    }
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_CHILD_BINDING_ENTRY_COUNT_EXCEEDED",
    ):
        _receipt(
            "raw:oversized_binding",
            child_read_bindings=(oversized_binding,),
        )

    custom_binding = _BombMapping(3)
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_CHILD_BINDING_NOT_BOUNDED_OBJECT",
    ):
        _receipt(
            "raw:custom_binding",
            child_read_bindings=(custom_binding,),
        )
    assert custom_binding.length_called is False
    assert custom_binding.consumed is False

    oversized_derivation = {
        "schema_version": "feature_source_derivation_v1",
        "producer_id": "test",
        "producer_version": "v1",
        "transform_sha256": "a" * 64,
        "configuration_sha256": "b" * 64,
        "unexpected": "field",
    }
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_DERIVATION_ENTRY_COUNT_EXCEEDED",
    ):
        _receipt(
            "raw:oversized_derivation",
            derivation_material=oversized_derivation,
        )

    custom_derivation = _BombMapping(6)
    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_DERIVATION_NOT_BOUNDED_OBJECT",
    ):
        _receipt(
            "raw:custom_derivation",
            derivation_material=custom_derivation,
        )
    assert custom_derivation.length_called is False
    assert custom_derivation.consumed is False

    generator_consumed = False

    def unbounded_generator() -> Iterator[Mapping[str, str]]:
        nonlocal generator_consumed
        generator_consumed = True
        raise AssertionError("unbounded_generator_consumed")
        yield {}

    with pytest.raises(
        ledger_module.FeatureSnapshotValidationError,
        match="SOURCE_CHILD_BINDINGS_NOT_BOUNDED_SEQUENCE",
    ):
        _receipt(
            "raw:generator",
            child_read_bindings=unbounded_generator(),  # type: ignore[arg-type]
        )
    assert generator_consumed is False
