from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from tools import trainer_trace_raw_context_association_receipt_v4 as association_module
from tools.trainer_feature_resolution_publication_bridge_v4 import (
    FeatureResolutionPublicationBridgeArtifactV4,
    build_feature_resolution_publication_bridge_v4,
)
from tools.trainer_raw_context_cas_receipt_v4 import (
    RawContextCasReceiptArtifactV4,
    build_raw_context_cas_receipt_v4,
)
from tools.trainer_trace_raw_context_association_receipt_v4 import (
    TRACE_RAW_CONTEXT_ASSOCIATION_LIMITATIONS,
    TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION,
    TraceRawContextAssociationReceiptArtifactV4,
    TraceRawContextAssociationReceiptV4ValidationError,
    build_trace_raw_context_association_receipt_v4,
)
from v2.backend.app.services.native_trainer.feature_resolution_trace_v4 import (
    FeatureResolutionTraceArtifactV4,
    build_feature_resolution_trace_v4,
)
from v2.backend.app.services.native_trainer.feature_snapshot_publication_ledger_v4 import (
    FeatureSnapshotPublicationLedgerEntryV4,
    FeatureSnapshotPublicationLedgerV4,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_feature_resolution_trace_v4 as trace_harness,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_feature_snapshot_publication_ledger_v4 as publication_harness,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_raw_context_cas_receipt_v4 as raw_context_harness,
)


@dataclass(slots=True)
class _Harness:
    publication_ledger: FeatureSnapshotPublicationLedgerV4
    publication_entry: FeatureSnapshotPublicationLedgerEntryV4
    raw_context_store: ImmutableSourcePayloadStore
    raw_context_bytes: bytes
    raw_context_artifact: RawContextCasReceiptArtifactV4
    tensor: FeatureTensorRecord
    trace_artifact: FeatureResolutionTraceArtifactV4
    bridge_artifact: FeatureResolutionPublicationBridgeArtifactV4
    association_artifact: TraceRawContextAssociationReceiptArtifactV4 | None


def _harness(
    tmp_path: Path,
    *,
    name: str = "p0f2-harness",
    publication_clock_offset_seconds: int = 1,
    raw_context_payload: object | None = None,
    trace_raw_context_sha256: str | None = None,
    build_association: bool = True,
) -> _Harness:
    root = tmp_path / name
    source_ledger, source_result, source_recorded_at = publication_harness._source_ledger(root)
    snapshot = publication_harness._declared_native_snapshot_for_source(source_result)
    feature_artifact = publication_harness._publish_artifact(
        root / "feature-artifact",
        snapshot,
    )
    publication_ledger = FeatureSnapshotPublicationLedgerV4(
        root / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )
    publication_result = publication_harness._append(
        publication_ledger,
        source_result,
        feature_artifact,
        source_recorded_at + timedelta(seconds=publication_clock_offset_seconds),
    )
    raw_context_bytes = raw_context_harness._raw_context_bytes(
        publication_result.entry.record,
        payload=raw_context_payload,
    )
    raw_context_store = ImmutableSourcePayloadStore(root / "raw-context-cas")
    raw_context_artifact = build_raw_context_cas_receipt_v4(
        raw_context_bytes=raw_context_bytes,
        source_payload_store=raw_context_store,
        publication_ledger=publication_ledger,
        publication_entry=publication_result.entry,
    )
    tensor = replace(
        trace_harness._tensor(),
        feature_snapshot_id=cast(str, snapshot["feature_snapshot_id"]),
        symbol=cast(str, snapshot["symbol"]),
        timeframe=cast(str, snapshot["timeframe"]),
    )
    trace_artifact = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=(
            hashlib.sha256(raw_context_bytes).hexdigest()
            if trace_raw_context_sha256 is None
            else trace_raw_context_sha256
        ),
        observations=trace_harness._observations(tensor),
    )
    bridge_artifact = build_feature_resolution_publication_bridge_v4(
        trace_artifact=trace_artifact,
        publication_ledger=publication_ledger,
        publication_entry=publication_result.entry,
    )
    association_artifact = (
        build_trace_raw_context_association_receipt_v4(
            bridge_artifact=bridge_artifact,
            raw_context_artifact=raw_context_artifact,
        )
        if build_association
        else None
    )
    return _Harness(
        publication_ledger=publication_ledger,
        publication_entry=publication_result.entry,
        raw_context_store=raw_context_store,
        raw_context_bytes=raw_context_bytes,
        raw_context_artifact=raw_context_artifact,
        tensor=tensor,
        trace_artifact=trace_artifact,
        bridge_artifact=bridge_artifact,
        association_artifact=association_artifact,
    )


def _artifact(harness: _Harness) -> TraceRawContextAssociationReceiptArtifactV4:
    assert harness.association_artifact is not None
    return harness.association_artifact


def _direct_artifact(
    harness: _Harness,
    *,
    association_json: str,
    receipt_sha256: str,
    construction_token: object,
) -> TraceRawContextAssociationReceiptArtifactV4:
    return TraceRawContextAssociationReceiptArtifactV4(
        schema_version=TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION,
        receipt_sha256=receipt_sha256,
        association_json=association_json,
        _bridge_artifact=harness.bridge_artifact,
        _raw_context_artifact=harness.raw_context_artifact,
        _construction_token=construction_token,
    )


def _true_paths(value: object, *, prefix: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    if value is True:
        return [prefix]
    if type(value) is dict:
        result: list[tuple[object, ...]] = []
        for key, item in cast(dict[object, object], value).items():
            result.extend(_true_paths(item, prefix=(*prefix, key)))
        return result
    if type(value) is list:
        result = []
        for index, item in enumerate(cast(list[object], value)):
            result.extend(_true_paths(item, prefix=(*prefix, index)))
        return result
    return []


def _reseal(receipt: dict[str, Any]) -> None:
    p0e = cast(dict[str, Any], receipt["p0e_bridge_binding"])
    p0f1 = cast(dict[str, Any], receipt["p0f1_raw_context_binding"])
    cross = cast(dict[str, Any], receipt["cross_artifact_binding"])
    p0e_material = {key: item for key, item in p0e.items() if key != "p0e_bridge_binding_sha256"}
    p0e["p0e_bridge_binding_sha256"] = association_module._sha256_json(p0e_material)
    p0f1_material = {
        key: item for key, item in p0f1.items() if key != "p0f1_raw_context_binding_sha256"
    }
    p0f1["p0f1_raw_context_binding_sha256"] = association_module._sha256_json(p0f1_material)
    cross_material = {
        key: item for key, item in cross.items() if key != "association_binding_sha256"
    }
    cross["association_binding_sha256"] = association_module._sha256_json(cross_material)
    receipt_material = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = association_module._sha256_json(receipt_material)


def test_receipt_binds_exact_trace_cas_p0d_identity_and_only_one_true(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    artifact = _artifact(harness)
    receipt = artifact.receipt
    p0e = receipt["p0e_bridge_binding"]
    p0f1 = receipt["p0f1_raw_context_binding"]
    cross = receipt["cross_artifact_binding"]

    assert artifact.schema_version == TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_SCHEMA_VERSION
    assert receipt["receipt_sha256"] == artifact.receipt_sha256
    assert receipt["association_limitations"] == list(TRACE_RAW_CONTEXT_ASSOCIATION_LIMITATIONS)
    assert _true_paths(receipt) == [
        (association_module._TRUE_FIELD,),
    ]
    assert artifact.trace_to_raw_context_cas_association_verified is True
    for name in association_module._FALSE_FIELDS:
        assert receipt[name] is False
        assert getattr(artifact, name) is False

    expected_raw_sha256 = hashlib.sha256(harness.raw_context_bytes).hexdigest()
    assert p0e["trace_raw_context_sha256"] == expected_raw_sha256
    assert p0f1["raw_context_sha256"] == expected_raw_sha256
    assert p0f1["raw_context_cas_payload_sha256"] == expected_raw_sha256
    assert p0f1["raw_context_cas_payload_byte_count"] == len(harness.raw_context_bytes)
    assert cross["raw_context_sha256"] == expected_raw_sha256
    assert p0e["feature_snapshot_id"] == p0f1["feature_snapshot_id"]
    assert p0e["p0d_ledger_entry_sha256"] == p0f1["p0d_ledger_entry_sha256"]
    assert p0e["p0d_publication_identity_sha256"] == p0f1["p0d_publication_identity_sha256"]
    assert p0e["p0d_artifact_binding_sha256"] == p0f1["p0d_artifact_binding_sha256"]
    assert p0e["p0d_artifact_serialization_sha256"] == p0f1["p0d_artifact_serialization_sha256"]
    assert json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True) == (
        artifact.association_json
    )

    receipt["cross_artifact_binding"]["symbol"] = "MUTATED"
    assert artifact.receipt["cross_artifact_binding"]["symbol"] != "MUTATED"


@pytest.mark.parametrize(
    ("bad_bridge", "bad_raw", "reason"),
    [
        (object(), None, "EXACT_P0E_BRIDGE_REQUIRED"),
        (None, object(), "EXACT_P0F1_RECEIPT_REQUIRED"),
    ],
)
def test_exact_builtin_upstream_artifact_types_are_required(
    tmp_path: Path,
    bad_bridge: object | None,
    bad_raw: object | None,
    reason: str,
) -> None:
    harness = _harness(tmp_path)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match=reason,
    ):
        build_trace_raw_context_association_receipt_v4(
            bridge_artifact=cast(
                Any,
                harness.bridge_artifact if bad_bridge is None else bad_bridge,
            ),
            raw_context_artifact=cast(
                Any,
                harness.raw_context_artifact if bad_raw is None else bad_raw,
            ),
        )


def test_factory_only_and_exact_canonical_receipt_json(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    artifact = _artifact(harness)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="FACTORY_REQUIRED",
    ):
        _direct_artifact(
            harness,
            association_json=artifact.association_json,
            receipt_sha256=artifact.receipt_sha256,
            construction_token=object(),
        )

    noncanonical = json.dumps(json.loads(artifact.association_json), indent=2)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="JSON_NOT_CANONICAL",
    ):
        _direct_artifact(
            harness,
            association_json=noncanonical,
            receipt_sha256=artifact.receipt_sha256,
            construction_token=association_module._CONSTRUCTION_TOKEN,
        )

    duplicate = '{"schema_version":"x","schema_version":"y"}'
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="DUPLICATE_JSON_KEY",
    ):
        _direct_artifact(
            harness,
            association_json=duplicate,
            receipt_sha256=artifact.receipt_sha256,
            construction_token=association_module._CONSTRUCTION_TOKEN,
        )


def test_trace_or_raw_context_substitution_fails_closed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    alternate_bytes = raw_context_harness._raw_context_bytes(
        harness.publication_entry.record,
        payload={"market": {"close": 999.0}, "optional_event_sources": {}},
    )
    alternate_store = ImmutableSourcePayloadStore(tmp_path / "alternate-raw-context-cas")
    alternate_raw = build_raw_context_cas_receipt_v4(
        raw_context_bytes=alternate_bytes,
        source_payload_store=alternate_store,
        publication_ledger=harness.publication_ledger,
        publication_entry=harness.publication_entry,
    )
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="RAW_CONTEXT_SHA256_MISMATCH",
    ):
        build_trace_raw_context_association_receipt_v4(
            bridge_artifact=harness.bridge_artifact,
            raw_context_artifact=alternate_raw,
        )

    wrong_trace = build_feature_resolution_trace_v4(
        tensor=harness.tensor,
        raw_context_sha256="f" * 64,
        observations=trace_harness._observations(harness.tensor),
    )
    wrong_bridge = build_feature_resolution_publication_bridge_v4(
        trace_artifact=wrong_trace,
        publication_ledger=harness.publication_ledger,
        publication_entry=harness.publication_entry,
    )
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="RAW_CONTEXT_SHA256_MISMATCH",
    ):
        build_trace_raw_context_association_receipt_v4(
            bridge_artifact=wrong_bridge,
            raw_context_artifact=harness.raw_context_artifact,
        )


def test_different_committed_p0d_entry_substitution_fails_closed(tmp_path: Path) -> None:
    first = _harness(
        tmp_path,
        name="first-p0d",
        publication_clock_offset_seconds=1,
    )
    second = _harness(
        tmp_path,
        name="second-p0d",
        publication_clock_offset_seconds=2,
    )
    assert first.publication_entry.entry_sha256 != second.publication_entry.entry_sha256

    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="SHARED_P0D_IDENTITY_MISMATCH",
    ):
        build_trace_raw_context_association_receipt_v4(
            bridge_artifact=first.bridge_artifact,
            raw_context_artifact=second.raw_context_artifact,
        )


def test_coherent_reseal_cannot_promote_flags_or_replace_bound_raw_context(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    artifact = _artifact(harness)

    for promoted_field in association_module._FALSE_FIELDS:
        forged = json.loads(artifact.association_json)
        forged[promoted_field] = True
        _reseal(forged)
        with pytest.raises(
            TraceRawContextAssociationReceiptV4ValidationError,
            match="CONSTANT_OR_FLAG_MISMATCH",
        ):
            TraceRawContextAssociationReceiptArtifactV4(
                schema_version=artifact.schema_version,
                receipt_sha256=forged["receipt_sha256"],
                association_json=association_module._canonical_json(forged),
                _bridge_artifact=harness.bridge_artifact,
                _raw_context_artifact=harness.raw_context_artifact,
                _construction_token=association_module._CONSTRUCTION_TOKEN,
            )

    demoted = json.loads(artifact.association_json)
    demoted[association_module._TRUE_FIELD] = False
    _reseal(demoted)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="CONSTANT_OR_FLAG_MISMATCH",
    ):
        association_module._validate_material(demoted)

    forged = json.loads(artifact.association_json)
    replacement_sha256 = "e" * 64
    forged["p0e_bridge_binding"]["trace_raw_context_sha256"] = replacement_sha256
    forged["p0f1_raw_context_binding"]["raw_context_sha256"] = replacement_sha256
    forged["p0f1_raw_context_binding"]["raw_context_cas_payload_sha256"] = replacement_sha256
    forged["cross_artifact_binding"]["raw_context_sha256"] = replacement_sha256
    _reseal(forged)
    assert association_module._validate_material(forged) == forged
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="ARTIFACT_BINDING_MISMATCH",
    ):
        TraceRawContextAssociationReceiptArtifactV4(
            schema_version=artifact.schema_version,
            receipt_sha256=forged["receipt_sha256"],
            association_json=association_module._canonical_json(forged),
            _bridge_artifact=harness.bridge_artifact,
            _raw_context_artifact=harness.raw_context_artifact,
            _construction_token=association_module._CONSTRUCTION_TOKEN,
        )


def _close_equal_capture(receipt: dict[str, Any]) -> None:
    capture = receipt["p0f1_raw_context_binding"]["raw_context_capture_completed_at"]
    receipt["p0f1_raw_context_binding"]["candle_close_time"] = capture
    receipt["cross_artifact_binding"]["candle_close_time"] = capture


def _capture_after_generated(receipt: dict[str, Any]) -> None:
    after_generated = "2023-11-14T23:24:00.233000Z"
    receipt["p0f1_raw_context_binding"]["raw_context_capture_completed_at"] = after_generated
    receipt["cross_artifact_binding"]["raw_context_capture_completed_at"] = after_generated


def _generated_after_recorded(receipt: dict[str, Any]) -> None:
    after_recorded = "2026-07-20T00:00:00.999999Z"
    receipt["p0e_bridge_binding"]["p0d_snapshot_generated_at"] = after_recorded
    receipt["p0f1_raw_context_binding"]["p0d_snapshot_generated_at"] = after_recorded
    receipt["cross_artifact_binding"]["snapshot_generated_at"] = after_recorded


def _recorded_after_decision(receipt: dict[str, Any]) -> None:
    after_decision = "2026-07-20T00:00:01.000001Z"
    receipt["p0e_bridge_binding"]["p0d_ledger_recorded_at"] = after_decision
    receipt["p0f1_raw_context_binding"]["p0d_ledger_recorded_at"] = after_decision
    receipt["cross_artifact_binding"]["ledger_recorded_at"] = after_decision


@pytest.mark.parametrize(
    "mutate",
    [
        _close_equal_capture,
        _capture_after_generated,
        _generated_after_recorded,
        _recorded_after_decision,
    ],
)
def test_coherently_resealed_pit_inversions_fail_closed(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    receipt = json.loads(_artifact(_harness(tmp_path)).association_json)
    mutate(receipt)
    _reseal(receipt)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="PIT_CLOCK_ORDER_INVALID",
    ):
        association_module._validate_material(receipt)


@pytest.mark.parametrize("corruption", ["raw_cas", "p0d_ledger", "trace"])
def test_every_receipt_access_freshly_revalidates_cas_ledger_and_trace(
    tmp_path: Path,
    corruption: str,
) -> None:
    harness = _harness(tmp_path)
    artifact = _artifact(harness)
    if corruption == "raw_cas":
        object_path = harness.raw_context_store.path_for(
            harness.raw_context_artifact.raw_context_sha256
        )
        object_path.chmod(0o600)
        object_path.write_bytes(harness.raw_context_bytes[:-1])
        object_path.chmod(0o400)
        reason = "P0F1_REVALIDATION_FAILED"
    elif corruption == "p0d_ledger":
        harness.publication_ledger.path.write_bytes(b"")
        harness.publication_ledger.path.chmod(0o600)
        reason = "P0E_REVALIDATION_FAILED"
    else:
        object.__setattr__(harness.trace_artifact, "trace_json", "{}")
        reason = "P0E_REVALIDATION_FAILED"

    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match=reason,
    ):
        _ = artifact.receipt


def test_exact_byte_node_and_depth_resource_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = association_module._canonical_json({"padding": ""})
    fill_count = association_module.MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES - len(
        empty.encode("ascii")
    )
    exact = association_module._canonical_json({"padding": "z" * fill_count})
    assert len(exact.encode("ascii")) == (
        association_module.MAX_TRACE_RAW_CONTEXT_ASSOCIATION_RECEIPT_V4_BYTES
    )
    assert association_module._parse_json(exact)["padding"] == "z" * fill_count

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("oversized receipt must fail before json.loads")

    monkeypatch.setattr(json, "loads", forbidden)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="JSON_SIZE_INVALID",
    ):
        association_module._parse_json(exact[:-2] + "z" + exact[-2:])

    exact_nodes = [None] * (association_module.MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_NODES - 1)
    assert association_module._canonical_json(exact_nodes)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="NODE_LIMIT_EXCEEDED",
    ):
        association_module._canonical_json([None, *exact_nodes])

    exact_depth: object = 0
    for _ in range(association_module.MAX_TRACE_RAW_CONTEXT_ASSOCIATION_JSON_DEPTH):
        exact_depth = [exact_depth]
    assert association_module._canonical_json(exact_depth)
    with pytest.raises(
        TraceRawContextAssociationReceiptV4ValidationError,
        match="DEPTH_LIMIT_EXCEEDED",
    ):
        association_module._canonical_json([exact_depth])


def test_runtime_remains_unwired_and_module_has_no_io_clients() -> None:
    repo = Path(__file__).resolve().parents[6]
    app_root = repo / "v2" / "backend" / "app"
    runtime_imports = [
        path
        for path in app_root.rglob("*.py")
        if "trainer_trace_raw_context_association_receipt_v4"
        in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert runtime_imports == []

    module_source = (
        repo / "tools" / "trainer_trace_raw_context_association_receipt_v4.py"
    ).read_text(encoding="utf-8")
    for forbidden_import in (
        "import redis",
        "import requests",
        "import httpx",
        "import socket",
        "import subprocess",
    ):
        assert forbidden_import not in module_source
