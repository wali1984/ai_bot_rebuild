from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_research_calibration_admission_v1 as calibration,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_research_finalized_outcome_ledger_v1 as outcome_support,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _clock(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _row(
    index: int,
    *,
    decision_day: int,
    action: str,
    raw_probability: float,
    outcome: bool,
    fingerprint: str = "1" * 64,
    binding_sha: str = "2" * 64,
    late_label: bool = False,
) -> calibration._EvidenceRow:  # noqa: SLF001
    base = datetime(2026, 1, 1, tzinfo=UTC)
    decision = base + timedelta(days=decision_day)
    label = decision + timedelta(days=5 if late_label else 0, hours=1)
    maturation = max(label, decision + timedelta(hours=2))
    commit = maturation + timedelta(hours=1)
    postcommit = commit + timedelta(hours=1)
    readback = postcommit + timedelta(hours=1)
    payload = json.dumps(
        {"synthetic_source_index": index},
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return calibration._EvidenceRow(  # noqa: SLF001
        row_id=f"row-{index}",
        outcome_artifact_sha256=hashlib.sha256(payload).hexdigest(),
        outcome_artifact_byte_count=len(payload),
        outcome_material_sha256=_sha(f"outcome-{index}"),
        hypothesis_artifact_sha256=_sha(f"hypothesis-{index}"),
        record_chain_sha256=_sha(f"chain-{index}"),
        append_receipt_sha256=_sha(f"append-{index}"),
        postcommit_readback_receipt_sha256=_sha(f"postcommit-{index}"),
        checkpoint_id="checkpoint-test",
        checkpoint_generation=7,
        model_parameter_fingerprint=fingerprint,
        model_binding_sha256=binding_sha,
        decision_time=_clock(decision),
        actual_label_available_at=_clock(label),
        maturation_observed_at=_clock(maturation),
        outcome_commit_observed_at=_clock(commit),
        outcome_postcommit_observed_at=_clock(postcommit),
        outcome_postcommit_readback_at=_clock(readback),
        selected_action=action,
        raw_probability=raw_probability,
        observed_strictly_positive_net_pnl=outcome,
        outcome_artifact_bytes=payload,
    )


def _rows(
    *,
    offset: int = 0,
    fingerprint: str = "1" * 64,
    binding_sha: str = "2" * 64,
    include_purge: bool = True,
) -> tuple[calibration._EvidenceRow, ...]:  # noqa: SLF001
    rows: list[calibration._EvidenceRow] = []  # noqa: SLF001
    for index in range(8):
        rows.append(
            _row(
                offset + index,
                decision_day=index,
                action="long" if index % 2 == 0 else "short",
                raw_probability=0.9 if index % 2 == 0 else 0.1,
                outcome=index % 2 == 1,
                fingerprint=fingerprint,
                binding_sha=binding_sha,
            )
        )
    if include_purge:
        rows.append(
            _row(
                offset + 8,
                decision_day=8,
                action="long",
                raw_probability=0.9,
                outcome=False,
                fingerprint=fingerprint,
                binding_sha=binding_sha,
                late_label=True,
            )
        )
    validation = (
        ("long", 0.9, False),
        ("long", 0.1, True),
        ("short", 0.9, False),
        ("short", 0.1, True),
    )
    for suffix, (action, probability, outcome) in enumerate(validation):
        rows.append(
            _row(
                offset + 9 + suffix,
                decision_day=10 + suffix,
                action=action,
                raw_probability=probability,
                outcome=outcome,
                fingerprint=fingerprint,
                binding_sha=binding_sha,
            )
        )
    return tuple(rows)


def _prepared(
    *,
    offset: int = 0,
    fingerprint: str = "1" * 64,
    binding_sha: str = "2" * 64,
) -> calibration._PreparedAdmission:  # noqa: SLF001
    rows = _rows(
        offset=offset,
        fingerprint=fingerprint,
        binding_sha=binding_sha,
    )
    evaluation, partition, fitted, validation = calibration._evaluate_rows(rows)  # noqa: SLF001
    assert evaluation.admission_ready is True
    assert partition is not None
    assert fitted is not None
    assert validation is not None
    artifact, artifact_bytes = calibration._prepare_admission_artifact(  # noqa: SLF001
        rows,
        partition=partition,
        calibration_state=fitted,
        forward_validation=validation,
    )
    return calibration._PreparedAdmission(  # noqa: SLF001
        rows=rows,
        partition=partition,
        artifact=artifact,
        artifact_bytes=artifact_bytes,
    )


def _source_contracts(
    *prepared_values: calibration._PreparedAdmission,  # noqa: SLF001
) -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for prepared in prepared_values:
        for row in prepared.rows:
            contracts[row.outcome_artifact_sha256] = {
                "outcome_material_sha256": row.outcome_material_sha256,
                "hypothesis_binding": {
                    "hypothesis_artifact_sha256": row.hypothesis_artifact_sha256,
                },
                "calibration_row": {
                    "row_id": row.row_id,
                    "selected_directional_action": row.selected_action,
                    "raw_probability": row.raw_probability,
                    "observed_strictly_positive_net_pnl": (
                        row.observed_strictly_positive_net_pnl
                    ),
                    "model_binding_sha256": row.model_binding_sha256,
                },
            }
    return contracts


def _patch_source_validator(
    monkeypatch: pytest.MonkeyPatch,
    *prepared_values: calibration._PreparedAdmission,  # noqa: SLF001
) -> None:
    contracts = _source_contracts(*prepared_values)

    def validate(payload: object) -> dict[str, Any]:
        assert type(payload) is bytes
        return contracts[hashlib.sha256(payload).hexdigest()]

    monkeypatch.setattr(
        calibration,
        "validate_profiled_research_finalized_outcome_artifact_v1",
        validate,
    )


def _ledger(
    tmp_path: Path,
) -> calibration.ProfiledResearchCalibrationAdmissionLedgerV1:
    return calibration.ProfiledResearchCalibrationAdmissionLedgerV1(
        tmp_path / "calibration.sqlite3",
        store=ImmutableSourcePayloadStore(tmp_path / "calibration-cas"),
    )


def test_partition_is_purged_chronological_and_label_independent() -> None:
    rows = _rows()
    partition = calibration._chronological_partition(rows)  # noqa: SLF001
    assert partition is not None
    assert len(partition.train) == 8
    assert [row.row_id for row in partition.purge] == ["row-8"]
    assert len(partition.validation) == 4
    assert max(row.label_clock for row in partition.train) < min(
        row.decision_clock for row in partition.validation
    )

    flipped = tuple(
        replace(
            row,
            observed_strictly_positive_net_pnl=(
                not row.observed_strictly_positive_net_pnl
                if row in partition.validation
                else row.observed_strictly_positive_net_pnl
            ),
        )
        for row in rows
    )
    flipped_partition = calibration._chronological_partition(flipped)  # noqa: SLF001
    assert flipped_partition is not None
    assert [row.row_id for row in flipped_partition.train] == [
        row.row_id for row in partition.train
    ]
    assert [row.row_id for row in flipped_partition.purge] == [
        row.row_id for row in partition.purge
    ]
    assert [row.row_id for row in flipped_partition.validation] == [
        row.row_id for row in partition.validation
    ]


def test_partition_never_splits_equal_decision_time_cohort() -> None:
    rows = list(_rows(include_purge=False))
    validation_start = rows[8].decision_time
    tied = replace(
        rows[7],
        row_id="row-tied-boundary",
        outcome_artifact_sha256=_sha("tied-artifact"),
        decision_time=validation_start,
        actual_label_available_at=_clock(
            datetime.fromisoformat(validation_start.replace("Z", "+00:00"))
            + timedelta(hours=1)
        ),
    )
    rows[7] = tied
    partition = calibration._chronological_partition(rows)  # noqa: SLF001
    assert partition is not None
    tied_roles = {
        "train" if row in partition.train else "purge" if row in partition.purge else "validation"
        for row in rows
        if row.decision_time == validation_start
    }
    assert tied_roles == {"validation"}


def test_evaluation_and_artifact_recompute_every_proof() -> None:
    prepared = _prepared()
    artifact = calibration.validate_profiled_research_calibration_admission_artifact_v1(
        prepared.artifact_bytes
    )
    assert len(artifact["source_outcome_inventory"]) == 13
    assert artifact["partition"]["purged_gap_row_ids"] == ["row-8"]
    assert artifact["authorization"]["calibration_input_authorized"] is True
    assert (
        artifact["authorization"]["calibration_only_checkpoint_write_authorized"]
        is True
    )
    assert artifact["authorization"]["optimizer_execution_authorized"] is False
    assert artifact["authorization"]["model_weight_mutation_authorized"] is False
    assert artifact["authorization"]["serving_authorized"] is False
    assert artifact["authorization"]["paper_trading_authorized"] is False
    assert artifact["authorization"]["live_execution_authorized"] is False

    tampered = json.loads(prepared.artifact_bytes)
    tampered["calibration_state"]["temperature"] += 0.01
    material = {key: value for key, value in tampered.items() if key != "admission_material_sha256"}
    tampered["admission_material_sha256"] = calibration._sha256(material)  # noqa: SLF001
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="FIT_RECOMPUTATION_FAILED",
    ):
        calibration.validate_profiled_research_calibration_admission_artifact_v1(
            calibration._canonical_bytes(tampered, reason="test")  # noqa: SLF001
        )


def test_forward_validation_tamper_fails_even_after_rehash() -> None:
    prepared = _prepared()
    tampered = json.loads(prepared.artifact_bytes)
    tampered["forward_validation"]["global"]["paired_brier_delta_mean"] -= 1.0
    evidence = tampered["forward_validation"]["global"]
    evidence["uncertainty_evidence_digest"] = (
        calibration.confidence_uncertainty_evidence_digest(
            scope="GLOBAL", evidence=evidence
        )
    )
    material = {
        key: value
        for key, value in tampered.items()
        if key != "admission_material_sha256"
    }
    tampered["admission_material_sha256"] = calibration._sha256(material)  # noqa: SLF001
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="RECOMPUTATION_FAILED",
    ):
        calibration.validate_profiled_research_calibration_admission_artifact_v1(
            calibration._canonical_bytes(tampered, reason="test")  # noqa: SLF001
        )


def test_uncertainty_delta_matches_aggregate_brier_and_method_digest() -> None:
    prepared = _prepared()
    evidence = prepared.artifact["forward_validation"]["global"]
    assert evidence["method"] == calibration.CONFIDENCE_UNCERTAINTY_METHOD
    assert evidence["paired_brier_delta_mean"] == pytest.approx(
        evidence["calibrated_brier"] - evidence["raw_brier"]
    )
    assert evidence["uncertainty_evidence_digest"] == (
        calibration.confidence_uncertainty_evidence_digest(
            scope="GLOBAL", evidence=evidence
        )
    )


def test_regressing_forward_evidence_is_held() -> None:
    rows = _rows()
    partition = calibration._chronological_partition(rows)  # noqa: SLF001
    assert partition is not None
    validation_ids = {row.row_id for row in partition.validation}
    regressing = tuple(
        replace(
            row,
            observed_strictly_positive_net_pnl=(
                not row.observed_strictly_positive_net_pnl
                if row.row_id in validation_ids
                else row.observed_strictly_positive_net_pnl
            ),
        )
        for row in rows
    )
    evaluation, selected, fitted, validation = calibration._evaluate_rows(regressing)  # noqa: SLF001
    assert selected is not None
    assert fitted is not None
    assert validation is not None
    assert evaluation.status == "HELD_FORWARD_VALIDATION_NON_REGRESSION_NOT_PROVEN"
    assert evaluation.admission_ready is False
    assert evaluation.uncertainty_non_regression_proven is False


def test_durable_append_idempotence_readback_and_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    _patch_source_validator(monkeypatch, prepared)
    ledger = _ledger(tmp_path)
    result = ledger._append_prepared(prepared)  # noqa: SLF001

    assert ledger._append_prepared(prepared).sequence == 1  # noqa: SLF001
    assert result.sequence == 1
    assert result.calibration_input_authorized is True
    assert result.calibration_only_checkpoint_write_authorized is True
    assert result.optimizer_execution_authorized is False
    assert result.model_weight_mutation_authorized is False
    assert result.serving_authorized is False
    assert result.paper_trading_authorized is False
    assert result.live_execution_authorized is False
    assert result.runtime_wired is False
    assert result.admission_contract["status"]["runtime_wired"] is False
    report = ledger.verify_integrity()
    assert report.total_admissions == 1
    assert report.source_rows_verified == 13
    assert report.append_receipts_verified == 1
    assert report.head_anchors_verified == 1
    assert report.admission_cas_artifacts_verified == 1
    assert report.source_outcome_cas_artifacts_verified == 13
    assert report.head_catalog_artifacts_verified == 1
    assert report.replayed_source_rows == 0
    latest_source = max(
        datetime.fromisoformat(
            row.outcome_postcommit_readback_at.replace("Z", "+00:00")
        )
        for row in prepared.rows
    )
    admitted = datetime.fromisoformat(
        result.admitted_observed_at.replace("Z", "+00:00")
    )
    assert latest_source < admitted

    reopened_ledger = calibration.ProfiledResearchCalibrationAdmissionLedgerV1(
        ledger.path,
        store=ledger.store,
    )
    reopened = reopened_ledger.open_admission(
        model_parameter_fingerprint=result.model_parameter_fingerprint
    )
    assert reopened.admission_contract == result.admission_contract


def test_result_mutation_cannot_cross_factory_seal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    _patch_source_validator(monkeypatch, prepared)
    result = _ledger(tmp_path)._append_prepared(prepared)  # noqa: SLF001
    object.__setattr__(result, "transaction_id", "f" * 64)
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="RESULT_SEAL_INVALID",
    ):
        _ = result.admission_contract


def test_same_model_different_evidence_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _prepared()
    second = _prepared(offset=100)
    _patch_source_validator(monkeypatch, first, second)
    ledger = _ledger(tmp_path)
    ledger._append_prepared(first)  # noqa: SLF001
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ConflictError,
        match="MODEL_ALREADY_ADMITTED_WITH_DIFFERENT_EVIDENCE",
    ):
        ledger._append_prepared(second)  # noqa: SLF001


def test_schema_mutation_and_cas_mutation_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    _patch_source_validator(monkeypatch, prepared)
    ledger = _ledger(tmp_path)
    ledger._append_prepared(prepared)  # noqa: SLF001

    connection = sqlite3.connect(ledger.path)
    connection.execute("DROP TRIGGER profiled_calibration_admissions_no_update")
    connection.commit()
    connection.close()
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="SCHEMA_INVALID",
    ):
        ledger.verify_integrity()

    # Restore a clean ledger, then prove the immutable artifact is re-read.
    other = tmp_path / "cas-case"
    other.mkdir()
    clean = _ledger(other)
    clean_result = clean._append_prepared(prepared)  # noqa: SLF001
    artifact_path = (
        other
        / "calibration-cas"
        / clean_result.admission_artifact_address.relative_path
    )
    os.chmod(artifact_path, 0o600)
    artifact_path.write_bytes(b"{}")
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="CAS_READ_FAILED",
    ):
        clean.verify_integrity()


def test_suffix_head_recovery_and_interior_gap_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _prepared()
    second = _prepared(offset=100, fingerprint="3" * 64, binding_sha="4" * 64)
    _patch_source_validator(monkeypatch, first, second)
    ledger = _ledger(tmp_path)
    one = ledger._append_prepared(first)  # noqa: SLF001
    two = ledger._append_prepared(second)  # noqa: SLF001
    head_root = Path(str(ledger.path) + ".head-anchor-cas")
    second_path = head_root / f"sha256/{two.head_anchor_sha256[:2]}/{two.head_anchor_sha256}"
    os.chmod(second_path, 0o600)
    second_path.unlink()
    assert ledger.recover_head_catalog() == 1
    assert ledger.verify_integrity().head_catalog_artifacts_verified == 2

    first_path = head_root / f"sha256/{one.head_anchor_sha256[:2]}/{one.head_anchor_sha256}"
    os.chmod(first_path, 0o600)
    first_path.unlink()
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="INTERIOR_GAP",
    ):
        ledger.recover_head_catalog()


def test_unknown_head_and_source_cas_tamper_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    _patch_source_validator(monkeypatch, prepared)
    ledger = _ledger(tmp_path)
    ledger._append_prepared(prepared)  # noqa: SLF001
    catalog = ImmutableSourcePayloadStore(
        Path(str(ledger.path) + ".head-anchor-cas")
    )
    catalog.put(b'{"unknown":"head"}')
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="MEMBERSHIP_INVALID",
    ):
        ledger.verify_integrity()
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="UNKNOWN_HEAD",
    ):
        ledger.recover_head_catalog()

    other = tmp_path / "source-tamper"
    other.mkdir()
    clean = _ledger(other)
    clean._append_prepared(prepared)  # noqa: SLF001
    source = prepared.rows[0]
    source_path = (
        other
        / "calibration-cas"
        / f"sha256/{source.outcome_artifact_sha256[:2]}/{source.outcome_artifact_sha256}"
    )
    os.chmod(source_path, 0o600)
    source_path.write_bytes(b"{}")
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="CAS_READ_FAILED",
    ):
        clean.verify_integrity()


def test_read_verification_never_creates_missing_state(tmp_path: Path) -> None:
    root = tmp_path / "absent" / "nested"
    ledger = calibration.ProfiledResearchCalibrationAdmissionLedgerV1(
        root / "calibration.sqlite3",
        store=ImmutableSourcePayloadStore(tmp_path / "unused-cas"),
    )
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ConflictError
    ):
        ledger.verify_integrity()
    assert not root.exists()


def test_reader_fails_while_exclusive_writer_is_held(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    _patch_source_validator(monkeypatch, prepared)
    ledger = _ledger(tmp_path)
    ledger._append_prepared(prepared)  # noqa: SLF001
    with calibration._database_lease(  # noqa: SLF001
        ledger.path, exclusive=True, create_database=False
    ):
        with pytest.raises(
            calibration.ProfiledResearchCalibrationAdmissionV1ConflictError,
            match="LEASE_ALREADY_HELD",
        ):
            ledger.verify_integrity()


def test_aggregate_source_cas_cap_rejects_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepared()
    ledger = _ledger(tmp_path)
    monkeypatch.setattr(
        calibration,
        "_MAX_SOURCE_ARTIFACT_BYTES_PER_ADMISSION",
        1,
    )
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ValidationError,
        match="AGGREGATE_CAP_EXCEEDED",
    ):
        ledger._append_prepared(prepared)  # noqa: SLF001
    assert not ledger.path.exists()
    assert not Path(str(ledger.path) + ".writer.lock").exists()
    assert not [
        path
        for path in (tmp_path / "calibration-cas").rglob("*")
        if path.is_file()
    ]


def test_one_exact_finalized_outcome_waits_without_calibration_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inference = outcome_support.commitment_support.inference_support.inference
    with inference._PROCESS_SOURCE_ORDER_LOCK:  # noqa: SLF001
        inference._PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.clear()  # noqa: SLF001
    ready = outcome_support._ready_bundle(  # noqa: SLF001
        tmp_path / "source",
        monkeypatch,
    )
    matured = outcome_support._mature(ready)  # noqa: SLF001
    target = tmp_path / "target"
    target.mkdir()
    store = ImmutableSourcePayloadStore(target / "cas")
    ledger = calibration.ProfiledResearchCalibrationAdmissionLedgerV1(
        target / "calibration.sqlite3",
        store=store,
    )
    evaluation = ledger.admit_outcomes([matured])
    assert isinstance(
        evaluation, calibration.ProfiledResearchCalibrationEvaluationV1
    )
    assert evaluation.total_outcomes == 1
    assert evaluation.eligible_rows == 1
    assert evaluation.admission_ready is False
    assert evaluation.configured_sample_count_threshold_used is False
    assert evaluation.static_market_threshold_used is False
    assert not ledger.path.exists()
    assert not Path(str(ledger.path) + ".writer.lock").exists()
    assert not [path for path in (target / "cas").rglob("*") if path.is_file()]


def test_mixed_models_duplicates_and_non_sequences_fail_closed() -> None:
    rows = list(_rows())
    rows[-1] = replace(rows[-1], model_parameter_fingerprint="3" * 64)
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ValidationError,
        match="MIXED_MODEL_IDENTITIES",
    ):
        calibration._evaluate_rows(rows)  # noqa: SLF001
    duplicate = list(_rows())
    duplicate.append(duplicate[0])
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ValidationError,
        match="DUPLICATE_SOURCE_ROW",
    ):
        calibration._evaluate_rows(duplicate)  # noqa: SLF001
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ValidationError,
        match="EXACT_OUTCOME_SEQUENCE_REQUIRED",
    ):
        calibration.evaluate_profiled_research_finalized_outcomes_for_calibration_v1(
            "not-a-sequence"
        )
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1ValidationError,
        match="EXACT_BYTES_REQUIRED",
    ):
        calibration.validate_profiled_research_calibration_admission_artifact_v1(
            "{}"
        )
    with pytest.raises(
        calibration.ProfiledResearchCalibrationAdmissionV1IntegrityError,
        match="ARTIFACT_JSON_INVALID",
    ):
        calibration.validate_profiled_research_calibration_admission_artifact_v1(
            b'{"duplicate":1,"duplicate":2}'
        )
