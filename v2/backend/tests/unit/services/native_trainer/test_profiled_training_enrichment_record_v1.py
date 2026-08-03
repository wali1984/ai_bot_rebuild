from __future__ import annotations

import copy
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    durable_feature_snapshot_ledger as feature_ledger_module,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    build_causal_cost_evidence_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    DurableFeatureSnapshotLedger,
    build_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_training_enrichment_record_v1 import (
    ProfiledTrainingEnrichmentPairV1,
    ProfiledTrainingEnrichmentRecordV1Error,
    append_profiled_training_enrichment_pair_v1,
    build_profiled_training_enrichment_pair_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY,
    ProfiledTrainingLedgerLoaderV1Error,
    load_profiled_training_ledger_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_causal_cost_evidence_v1 as cost_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as parent_support,
)

_COST_AVAILABLE = "2026-07-21T12:00:00.900000Z"
_ENRICHMENT_AVAILABLE = "2026-07-21T12:00:00.900000Z"
_CHILD_GENERATED = "2026-07-21T12:00:00.900000Z"
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


@pytest.fixture(scope="module")
def parent_evidence(tmp_path_factory: pytest.TempPathFactory) -> Any:
    return parent_support._build_evidence(tmp_path_factory.mktemp("profiled-enrichment-parent"))


def _pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
    *,
    cost_available: str = _COST_AVAILABLE,
    enrichment_available: str = _ENRICHMENT_AVAILABLE,
    generated: str = _CHILD_GENERATED,
) -> tuple[
    ProfiledTrainingEnrichmentPairV1,
    ImmutableSourcePayloadStore,
]:
    parent = parent_evidence.record
    decision = parent["frozen_envelope"]["tensor_decision_time"]
    monkeypatch.setattr(
        cost_support,
        "_SNAPSHOT_IDENTITY",
        parent["durable_snapshot_id"],
    )
    monkeypatch.setattr(cost_support, "_DECISION_TIME", decision)
    monkeypatch.setattr(
        feature_ledger_module,
        "utc_now",
        lambda: "2026-07-21T12:00:02.000000Z",
    )
    cost = build_causal_cost_evidence_v1(**cost_support._inputs(tmp_path / "cost", monkeypatch))
    enrichment_store = ImmutableSourcePayloadStore(tmp_path / "enrichment-cas")
    pair = build_profiled_training_enrichment_pair_v1(
        parent_record=parent,
        transform_result=parent_evidence.transformed,
        capture_set_contract=parent_evidence.contract,
        capture_set_store=parent_evidence.capture_store,
        parent_artifact_store=parent_evidence.artifact_store,
        source_provenance_ledger=parent_evidence.source_ledger,
        source_provenance_entries=parent_evidence.source_entries,
        cost_evidence=cost,
        enrichment_store=enrichment_store,
        cost_artifact_available_at=cost_available,
        enrichment_available_at=enrichment_available,
        generated_at=generated,
    )
    return pair, enrichment_store


def _observation() -> str:
    return (
        max(
            datetime.now(tz=UTC) + timedelta(seconds=5),
            datetime(2026, 7, 22, tzinfo=UTC),
        )
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _rebuild_child(
    child: dict[str, Any],
    *,
    mutate: Any,
) -> dict[str, Any]:
    envelope = copy.deepcopy(child["frozen_envelope"])
    core = {
        key: value
        for key, value in envelope["source_lineage_material"].items()
        if key not in _RESERVED_LINEAGE_FIELDS
    }
    mutate(envelope, core)
    return build_feature_snapshot_record(
        provenance_classification=envelope["provenance_classification"],
        legacy_v1_snapshot_id=envelope["legacy_v1_snapshot_id"],
        symbol=envelope["symbol"],
        timeframe=envelope["timeframe"],
        feature_snapshot_id=envelope["feature_snapshot_id"],
        tensor_decision_time=envelope["tensor_decision_time"],
        temporal_rejection_reasons=envelope["temporal_rejection_reasons"],
        ordered_feature_names=envelope["ordered_feature_names"],
        feature_values=envelope["feature_values"],
        missing_mask=envelope["missing_mask"],
        stale_mask=envelope["stale_mask"],
        source_availability_mask=envelope["source_availability_mask"],
        ordered_feature_source_labels=envelope["ordered_feature_source_labels"],
        feature_source_receipt_sha256s=envelope["feature_source_receipt_sha256s"],
        source_read_receipts=envelope["source_read_receipts"],
        feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
        ordered_feature_requirement_classes=["REQUIRED"] * len(envelope["ordered_feature_names"]),
        original_tensor_id=envelope["original_tensor_id"],
        source_lineage_material=core,
        feature_cutoff=envelope["feature_cutoff"],
        masa_feature_cutoff=envelope["masa_feature_cutoff"],
        ppo_feature_cutoff=envelope["ppo_feature_cutoff"],
        ppo_decision_time=envelope["ppo_decision_time"],
        generated_at=envelope["generated_at"],
    )


def _append_tampered_and_load(
    tmp_path: Path,
    pair: ProfiledTrainingEnrichmentPairV1,
    child: dict[str, Any],
    *,
    trusted_immutable_cost_store_root: Path,
) -> None:
    ledger = DurableFeatureSnapshotLedger(tmp_path / "tampered-ledger.sqlite3")
    result = ledger.append_snapshots([pair.parent_record, child])
    assert result.inserted_rows == 2
    with pytest.raises(ProfiledTrainingLedgerLoaderV1Error):
        load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=trusted_immutable_cost_store_root,
            training_observed_at=_observation(),
        )


def test_atomic_pair_is_admitted_and_receipts_are_shared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")

    append = append_profiled_training_enrichment_pair_v1(
        ledger=ledger,
        pair=pair,
    )
    batch = load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=store.root_path,
        training_observed_at=_observation(),
    )

    assert append.parent_sequence == 1
    assert append.child_sequence == 2
    assert append.transaction_committed is True
    assert append.transaction_readback_verified is True
    assert append.runtime_wired is False
    assert len(batch.samples) == 1
    sample = batch.samples[0]
    assert sample.parent_durable_snapshot_id == pair.parent_durable_snapshot_id
    assert sample.durable_snapshot_id == pair.child_durable_snapshot_id
    assert sample.append_transaction_id == append.transaction_id
    assert sample.append_receipt_sha256 == append.append_receipt_sha256
    assert sample.postcommit_receipt_sha256 == append.postcommit_receipt_sha256
    assert sample.trainer_admission_authorized is True
    assert sample.prediction_authorized is False
    assert sample.paper_trading_authorized is False
    assert sample.live_execution_authorized is False
    assert sample.runtime_wired is False
    parent_envelope = pair.parent_record["frozen_envelope"]
    child_envelope = pair.child_record["frozen_envelope"]
    assert child_envelope["feature_cutoff"] > parent_envelope["feature_cutoff"]
    assert child_envelope["ppo_feature_cutoff"] == child_envelope["feature_cutoff"]
    assert child_envelope["masa_feature_cutoff"] == parent_envelope["masa_feature_cutoff"]


def test_parent_committed_first_cannot_be_completed_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, _store = _pair(tmp_path, monkeypatch, parent_evidence)
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    first = ledger.append_snapshot(pair.parent_record)
    assert first.inserted_rows == 1

    with pytest.raises(
        ProfiledTrainingEnrichmentRecordV1Error,
        match="PROFILED_TRAINING_ENRICHMENT_PARENT_ALREADY_COMMITTED",
    ):
        append_profiled_training_enrichment_pair_v1(ledger=ledger, pair=pair)

    assert ledger.get_snapshot(pair.parent_durable_snapshot_id) is not None
    assert ledger.get_snapshot(pair.child_durable_snapshot_id) is None


def test_late_cost_or_enrichment_evidence_fails_before_record_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    with pytest.raises(
        ProfiledTrainingEnrichmentRecordV1Error,
        match="PROFILED_TRAINING_ENRICHMENT_PUBLICATION_CLOCK_ORDER_INVALID",
    ):
        _pair(
            tmp_path,
            monkeypatch,
            parent_evidence,
            cost_available="2026-07-21T12:00:00.900001Z",
            enrichment_available="2026-07-21T12:00:00.900001Z",
            generated="2026-07-21T12:00:00.900001Z",
        )


def test_cost_evidence_for_another_parent_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    parent = parent_evidence.record
    monkeypatch.setattr(cost_support, "_SNAPSHOT_IDENTITY", "different-parent")
    monkeypatch.setattr(
        cost_support,
        "_DECISION_TIME",
        parent["frozen_envelope"]["tensor_decision_time"],
    )
    cost = build_causal_cost_evidence_v1(**cost_support._inputs(tmp_path / "cost", monkeypatch))
    with pytest.raises(
        ProfiledTrainingEnrichmentRecordV1Error,
        match="PROFILED_TRAINING_ENRICHMENT_COST_PARENT_IDENTITY_INVALID",
    ):
        build_profiled_training_enrichment_pair_v1(
            parent_record=parent,
            transform_result=parent_evidence.transformed,
            capture_set_contract=parent_evidence.contract,
            capture_set_store=parent_evidence.capture_store,
            parent_artifact_store=parent_evidence.artifact_store,
            source_provenance_ledger=parent_evidence.source_ledger,
            source_provenance_entries=parent_evidence.source_entries,
            cost_evidence=cost,
            enrichment_store=ImmutableSourcePayloadStore(tmp_path / "enrichment-cas"),
            cost_artifact_available_at=_COST_AVAILABLE,
            enrichment_available_at=_ENRICHMENT_AVAILABLE,
            generated_at=_CHILD_GENERATED,
        )


def test_loader_rejects_auxiliary_value_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)

    def tamper(envelope: dict[str, Any], _core: dict[str, Any]) -> None:
        envelope["feature_values"][-1] += 0.5

    child = _rebuild_child(pair.child_record, mutate=tamper)
    _append_tampered_and_load(
        tmp_path,
        pair,
        child,
        trusted_immutable_cost_store_root=store.root_path,
    )


@pytest.mark.parametrize("field", ["name", "value"])
def test_loader_rejects_parent_model_slot_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
    field: str,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)

    def tamper(envelope: dict[str, Any], _core: dict[str, Any]) -> None:
        if field == "name":
            envelope["ordered_feature_names"][0] = "tampered_parent_model_slot"
        else:
            envelope["feature_values"][0] += 0.25

    child = _rebuild_child(pair.child_record, mutate=tamper)
    _append_tampered_and_load(
        tmp_path,
        pair,
        child,
        trusted_immutable_cost_store_root=store.root_path,
    )


def test_parent_model_mask_tampering_is_never_admitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)

    def tamper(envelope: dict[str, Any], _core: dict[str, Any]) -> None:
        envelope["stale_mask"][0] = 1

    child = _rebuild_child(pair.child_record, mutate=tamper)
    ledger = DurableFeatureSnapshotLedger(tmp_path / "masked-ledger.sqlite3")
    result = ledger.append_snapshots([pair.parent_record, child])
    assert result.inserted_rows == 2
    batch = load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=store.root_path,
        training_observed_at=_observation(),
    )
    assert batch.samples == ()


def test_loader_rejects_enrichment_lineage_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)

    def tamper(_envelope: dict[str, Any], core: dict[str, Any]) -> None:
        core[PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY]["projection_implementation_sha256"] = (
            "0" * 64
        )

    child = _rebuild_child(pair.child_record, mutate=tamper)
    _append_tampered_and_load(
        tmp_path,
        pair,
        child,
        trusted_immutable_cost_store_root=store.root_path,
    )


def test_loader_rejects_auxiliary_receipt_graph_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)

    def tamper(envelope: dict[str, Any], core: dict[str, Any]) -> None:
        direct_receipt = next(
            item
            for item in envelope["source_read_receipts"]
            if item["source_label"].endswith(":authoritative_fee_schedule")
        )
        core[PROFILED_TRAINING_ENRICHMENT_LINEAGE_V1_KEY]["cost_capture_binding"][
            "auxiliary_feature_receipt_sha256s"
        ][0] = direct_receipt["receipt_sha256"]

    child = _rebuild_child(pair.child_record, mutate=tamper)
    _append_tampered_and_load(
        tmp_path,
        pair,
        child,
        trusted_immutable_cost_store_root=store.root_path,
    )


def test_cost_scalar_cas_tampering_fails_before_atomic_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)
    child = pair.child_record
    scalar_receipt = next(
        item
        for item in child["frozen_envelope"]["source_read_receipts"]
        if item["source_label"] == "causal_cost:auxiliary:fee_bps"
    )
    object_path = store.root_path / scalar_receipt["read_evidence"]["read_locator"]
    os.chmod(object_path, 0o600)
    object_path.write_bytes(b"bad!")
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")

    with pytest.raises(
        ProfiledTrainingEnrichmentRecordV1Error,
        match="PROFILED_TRAINING_ENRICHMENT_FEE_BPS_CAS_INVALID",
    ):
        append_profiled_training_enrichment_pair_v1(ledger=ledger, pair=pair)

    assert not ledger.path.exists()


@pytest.mark.parametrize("mutation", ["delete", "replace", "overwrite"])
def test_loader_reopens_cost_cas_and_rejects_postappend_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
    mutation: str,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    append_profiled_training_enrichment_pair_v1(ledger=ledger, pair=pair)
    child = pair.child_record
    scalar_receipt = next(
        item
        for item in child["frozen_envelope"]["source_read_receipts"]
        if item["source_label"] == "causal_cost:auxiliary:fee_bps"
    )
    object_path = store.root_path / scalar_receipt["read_evidence"]["read_locator"]
    if mutation == "delete":
        object_path.unlink()
    elif mutation == "replace":
        replacement = tmp_path / "replacement-object"
        replacement.write_bytes(b"bad!")
        object_path.unlink()
        object_path.symlink_to(replacement)
    else:
        os.chmod(object_path, 0o600)
        object_path.write_bytes(b"bad!")

    with pytest.raises(
        ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_CAS_READBACK_FAILED",
    ):
        load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=store.root_path,
            training_observed_at=_observation(),
        )


def test_loader_rejects_postappend_cost_artifact_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parent_evidence: Any,
) -> None:
    pair, store = _pair(tmp_path, monkeypatch, parent_evidence)
    ledger = DurableFeatureSnapshotLedger(tmp_path / "feature-ledger.sqlite3")
    append_profiled_training_enrichment_pair_v1(ledger=ledger, pair=pair)
    capture_receipt = next(
        item
        for item in pair.child_record["frozen_envelope"]["source_read_receipts"]
        if item["source_label"].startswith("causal_cost:capture:")
    )
    object_path = store.root_path / capture_receipt["read_evidence"]["read_locator"]
    byte_count = capture_receipt["read_evidence"]["payload_byte_count"]
    os.chmod(object_path, 0o600)
    object_path.write_bytes(b"x" * byte_count)

    with pytest.raises(
        ProfiledTrainingLedgerLoaderV1Error,
        match="PROFILED_TRAINING_COST_CAS_READBACK_FAILED",
    ):
        load_profiled_training_ledger_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=store.root_path,
            training_observed_at=_observation(),
        )
