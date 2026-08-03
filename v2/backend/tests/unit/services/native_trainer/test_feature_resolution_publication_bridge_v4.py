from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from tools import trainer_feature_resolution_publication_bridge_v4 as bridge_module
from tools.trainer_feature_resolution_publication_bridge_v4 import (
    AUTHENTICATION_GAP_REASONS,
    FeatureResolutionPublicationBridgeArtifactV4,
    FeatureResolutionPublicationBridgeV4ValidationError,
    build_feature_resolution_publication_bridge_v4,
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
from v2.backend.tests.unit.services.native_trainer import (
    test_feature_resolution_trace_v4 as trace_harness,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_feature_snapshot_publication_ledger_v4 as publication_harness,
)


def _harness(
    tmp_path: Path,
) -> tuple[
    FeatureSnapshotPublicationLedgerV4,
    FeatureSnapshotPublicationLedgerEntryV4,
    FeatureTensorRecord,
    FeatureResolutionTraceArtifactV4,
    FeatureResolutionPublicationBridgeArtifactV4,
]:
    root = tmp_path / "bridge-harness"
    source_ledger, source_result, source_recorded_at = publication_harness._source_ledger(root)
    snapshot = publication_harness._declared_native_snapshot_for_source(source_result)
    artifact = publication_harness._publish_artifact(root / "artifact", snapshot)
    publication_ledger = FeatureSnapshotPublicationLedgerV4(
        root / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )
    publication_result = publication_harness._append(
        publication_ledger,
        source_result,
        artifact,
        source_recorded_at + timedelta(seconds=1),
    )
    tensor = replace(
        trace_harness._tensor(),
        feature_snapshot_id=cast(str, snapshot["feature_snapshot_id"]),
        symbol=cast(str, snapshot["symbol"]),
        timeframe=cast(str, snapshot["timeframe"]),
    )
    trace = build_feature_resolution_trace_v4(
        tensor=tensor,
        raw_context_sha256=trace_harness._SHA_D,
        observations=trace_harness._observations(tensor),
    )
    bridge = build_feature_resolution_publication_bridge_v4(
        trace_artifact=trace,
        publication_ledger=publication_ledger,
        publication_entry=publication_result.entry,
    )
    return publication_ledger, publication_result.entry, tensor, trace, bridge


def test_bridge_binds_only_the_safe_intersection_and_never_authorizes(
    tmp_path: Path,
) -> None:
    publication_ledger, publication_entry, _tensor, _trace, bridge = _harness(tmp_path)
    record = bridge.bridge

    assert record["authentication_gap_reasons"] == list(AUTHENTICATION_GAP_REASONS)
    assert record["trace_structural_integrity_revalidated"] is True
    assert record["p0d_durable_ledger_entry_and_owned_cas_revalidated"] is True
    assert record["cross_artifact_identity_abi_value_and_masks_bound"] is True
    assert record["p0d_audit_evidence_recorded_no_later_than_trace_decision"] is True
    assert record["cross_artifact_binding"]["source_availability_vectors_equal"] is False
    assert (
        record["cross_artifact_binding"]["source_availability_comparison_only_not_authenticated"]
        is True
    )
    for name in bridge_module._FALSE_FIELDS:
        assert record[name] is False
        assert getattr(bridge, name) is False
    assert publication_ledger.read_entries()[0].entry_sha256 == publication_entry.entry_sha256


def test_cross_snapshot_identity_is_rejected(tmp_path: Path) -> None:
    publication_ledger, publication_entry, tensor, _trace, _bridge = _harness(tmp_path)
    wrong_tensor = replace(tensor, feature_snapshot_id="snapshot_v4_wrong_identity")
    wrong_trace = build_feature_resolution_trace_v4(
        tensor=wrong_tensor,
        raw_context_sha256=trace_harness._SHA_D,
        observations=trace_harness._observations(wrong_tensor),
    )

    with pytest.raises(
        FeatureResolutionPublicationBridgeV4ValidationError,
        match="SNAPSHOT_IDENTITY_MISMATCH",
    ):
        build_feature_resolution_publication_bridge_v4(
            trace_artifact=wrong_trace,
            publication_ledger=publication_ledger,
            publication_entry=publication_entry,
        )


def test_value_mask_root_clock_and_upstream_auth_mutations_fail_closed(
    tmp_path: Path,
) -> None:
    _ledger, entry, _tensor, trace_artifact, _bridge = _harness(tmp_path)
    trace = trace_artifact.trace
    publication = entry.record

    cases: list[tuple[str, Any, str]] = [
        (
            "value",
            lambda row: row["feature_vector_binding"]["ordered_feature_values"].__setitem__(
                0, 999.0
            ),
            "FEATURE_VALUES_MISMATCH",
        ),
        (
            "missing_mask",
            lambda row: row["feature_vector_binding"]["missing_mask"].__setitem__(0, 1),
            "MISSING_MASK_MISMATCH",
        ),
        (
            "stale_mask",
            lambda row: row["feature_vector_binding"]["stale_mask"].__setitem__(0, 1),
            "STALE_MASK_MISMATCH",
        ),
        (
            "root",
            lambda row: row["feature_vector_binding"]["per_field_root_receipt_sha256s"].__setitem__(
                0, "a" * 64
            ),
            "P0D_PER_FIELD_ROOTS_PRESENT",
        ),
        (
            "available_at",
            lambda row: row["feature_vector_binding"]["per_field_available_at"].__setitem__(
                0, "2026-07-19T23:59:59.000000Z"
            ),
            "P0D_PER_FIELD_CLOCKS_PRESENT",
        ),
        (
            "synthetic_source_label",
            lambda row: row["feature_vector_binding"]["ordered_resolved_source_labels"].__setitem__(
                0, trace["slot_observations"][0]["resolved_source_label"]
            ),
            "P0D_SOURCE_LABELS_NOT_UNRESOLVED",
        ),
        (
            "recorded_after_decision",
            lambda row: row.__setitem__("ledger_recorded_at", "2026-07-20T00:00:01.000001Z"),
            "P0D_RECORDED_AFTER_DECISION",
        ),
        (
            "generated_after_decision",
            lambda row: row["feature_artifact_binding"].__setitem__(
                "generated_at", "2026-07-20T00:00:01.000001Z"
            ),
            "ARTIFACT_GENERATED_AFTER_DECISION",
        ),
        (
            "candle_equal_decision",
            lambda row: row["feature_artifact_binding"].__setitem__(
                "candle_close_time", "2026-07-20T00:00:01.000000Z"
            ),
            "CANDLE_NOT_CLOSED_BEFORE_DECISION",
        ),
        (
            "upstream_auth_flag",
            lambda row: row.__setitem__("trainer_admission_granted", True),
            "UPSTREAM_CONTRACT_MISMATCH",
        ),
    ]
    for _name, mutate, reason in cases:
        candidate = deepcopy(publication)
        mutate(candidate)
        with pytest.raises(
            FeatureResolutionPublicationBridgeV4ValidationError,
            match=reason,
        ):
            bridge_module._build_material(trace, candidate)


def test_coherently_rehashed_bridge_authorization_flags_remain_false(
    tmp_path: Path,
) -> None:
    publication_ledger, publication_entry, _tensor, trace, bridge = _harness(tmp_path)
    for field_name in (
        "authenticated_complete_snapshot_ready",
        "feature_snapshot_published",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    ):
        forged = json.loads(bridge.bridge_json)
        forged[field_name] = True
        material = {key: value for key, value in forged.items() if key != "bridge_sha256"}
        forged["bridge_sha256"] = bridge_module._sha256(material)

        with pytest.raises(
            FeatureResolutionPublicationBridgeV4ValidationError,
            match="CONSTANT_OR_FLAG_MISMATCH",
        ):
            FeatureResolutionPublicationBridgeArtifactV4(
                schema_version=bridge.schema_version,
                bridge_sha256=forged["bridge_sha256"],
                bridge_json=bridge_module._canonical_json(forged),
                _trace_artifact=trace,
                _publication_ledger=publication_ledger,
                _publication_entry=publication_entry,
                _construction_token=bridge_module._CONSTRUCTION_TOKEN,
            )


def test_every_access_freshly_revalidates_durable_p0d_and_trace(
    tmp_path: Path,
) -> None:
    publication_ledger, _entry, _tensor, trace, bridge = _harness(tmp_path)
    original_ledger_bytes = publication_ledger.path.read_bytes()
    publication_ledger.path.write_bytes(b"")
    publication_ledger.path.chmod(0o600)
    with pytest.raises(
        FeatureResolutionPublicationBridgeV4ValidationError,
        match="P0D_REVALIDATION_FAILED",
    ):
        _ = bridge.bridge
    publication_ledger.path.write_bytes(original_ledger_bytes)
    publication_ledger.path.chmod(0o600)
    assert bridge.bridge["bridge_sha256"] == bridge.bridge_sha256

    original_trace_json = trace.trace_json
    object.__setattr__(trace, "trace_json", "{}")
    with pytest.raises(
        FeatureResolutionPublicationBridgeV4ValidationError,
        match="TRACE_REVALIDATION_FAILED",
    ):
        _ = bridge.bridge
    object.__setattr__(trace, "trace_json", original_trace_json)


def test_runtime_remains_unwired() -> None:
    repo = Path(__file__).resolve().parents[6]
    app_root = repo / "v2" / "backend" / "app"
    imports = []
    for path in app_root.rglob("*.py"):
        if "trainer_feature_resolution_publication_bridge_v4" in path.read_text(
            encoding="utf-8",
            errors="ignore",
        ):
            imports.append(path)
    assert imports == []
