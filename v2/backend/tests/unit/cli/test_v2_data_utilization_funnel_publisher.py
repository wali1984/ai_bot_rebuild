from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from v2.backend.app.cli.v2_data_utilization_funnel_publisher import (
    DataUtilizationCollectorError,
    _candidate_profile,
    _candidate_training_profile,
)


def _archive_row(candidate_id: str, decision_time_ms: int, *, matured: bool) -> dict:
    return {
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "record": {
            "decision": {
                "candidate_id": candidate_id,
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "decision_time_ms": decision_time_ms,
            },
            "matured_labels": {"matured": True} if matured else None,
        },
    }


def _status(path: Path) -> dict:
    return {
        "archive": {
            "archive_path": str(path),
            "row_count": 2,
            "candidate_count": 2,
            "matured_revision_count": 1,
            "verified": True,
            "invalid_row_count": 0,
            "duplicate_archive_record_count": 0,
            "terminal_chain_sha256": "a" * 64,
        },
        "maturation": {
            "unmatured_candidate_count": 1,
            "pending_reason_counts": {},
            "unexplained_maturation_drops": 0,
            "counterfactual_counts_as_paper_profit": False,
        },
    }


def test_candidate_profile_streams_archive_and_computes_exact_overlap(tmp_path: Path):
    path = tmp_path / "archive.jsonl"
    rows = [
        _archive_row("one", 1_000, matured=True),
        _archive_row("two", 2_000, matured=False),
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    profile = _candidate_profile(
        _status(path),
        {("BTCUSDT", "5m", 1_000)},
    )
    assert profile["candidate_outcome_rows"] == 2
    assert profile["matured_candidate_outcome_rows"] == 1
    assert profile["gen5_exact_identity_overlap_rows"] == 1
    assert profile["pending_reasons"] == {"HORIZON_NOT_YET_DUE": 1}
    assert profile["archive_verified"] is True


def test_candidate_profile_rejects_live_authority(tmp_path: Path):
    path = tmp_path / "archive.jsonl"
    row = _archive_row("one", 1_000, matured=True)
    row["routes_to_live"] = True
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    status = _status(path)
    status["archive"].update(
        row_count=1,
        candidate_count=1,
        matured_revision_count=1,
    )
    status["maturation"]["unmatured_candidate_count"] = 0
    with pytest.raises(DataUtilizationCollectorError, match="AUTHORITY_INVALID"):
        _candidate_profile(status, set())


def test_candidate_profile_rejects_conflicting_revision_identity(tmp_path: Path):
    path = tmp_path / "archive.jsonl"
    rows = [
        _archive_row("same", 1_000, matured=False),
        _archive_row("same", 2_000, matured=True),
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    status = _status(path)
    status["archive"]["candidate_count"] = 1
    with pytest.raises(DataUtilizationCollectorError, match="IDENTITY_CONFLICT"):
        _candidate_profile(status, set())


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _write_pretty(path: Path, value: object) -> str:
    data = (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _adaptive_artifacts(root: Path) -> tuple[dict, dict]:
    root.mkdir()
    sha_a = "a" * 64
    sha_b = "b" * 64
    rows = [
        {
            "row_id": "gen5:one",
            "source_kind": "GEN5_AUTHENTICATED_PROFILED_OBSERVATION",
            "split": "train",
        },
        {
            "row_id": "candidate_outcome:one",
            "source_kind": "CANDIDATE_DECISION_OUTCOME_V2",
            "split": "validation",
            "candidate_id": "candidate-one",
            "snapshot_id": "snapshot-one",
            "counterfactual_counts_as_realized_paper_profit": False,
        },
    ]
    dataset_material = {
        "schema_version": "adaptive_serving_compatible_dataset_v2",
        "feature_abi_sha256": sha_a,
        "feature_builder_sha256": sha_b,
        "ordered_feature_names": ["feature"],
        "rows": rows,
    }
    dataset_sha = _canonical_sha(dataset_material)
    dataset = {
        **dataset_material,
        "dataset_id": "adaptive-test",
        "dataset_sha256": dataset_sha,
    }
    manifest_material = {
        "schema_version": "adaptive_serving_compatible_dataset_manifest_v2",
        "dataset_id": "adaptive-test",
        "dataset_sha256": dataset_sha,
        "feature_abi_sha256": sha_a,
        "feature_builder_sha256": sha_b,
        "ordered_feature_names": ["feature"],
        "training_rows": 1,
        "validation_rows": 1,
        "holdout_rows": 0,
        "source_high_watermark": {
            "base_dataset_sha256": "c" * 64,
            "candidate_archive_candidate_count": 3,
            "candidate_archive_matured_revision_count": 2,
            "candidate_archive_terminal_chain_sha256": "d" * 64,
        },
        "source_row_counts": {
            "CANDIDATE_DECISION_OUTCOME_V2": 1,
            "GEN5_AUTHENTICATED_PROFILED_OBSERVATION": 1,
        },
        "source_split_counts": {
            "CANDIDATE_DECISION_OUTCOME_V2": {
                "train": 0,
                "validation": 1,
                "holdout": 0,
            },
            "GEN5_AUTHENTICATED_PROFILED_OBSERVATION": {
                "train": 1,
                "validation": 0,
                "holdout": 0,
            },
        },
        "candidate_records_considered": 3,
        "candidate_matured_records_considered": 2,
        "candidate_rows_before_split_purge": 1,
        "candidate_exclusion_reasons": {"STALE": 1},
        "purge_reason_counts": {},
        "candidate_records_fully_accounted": True,
        "counterfactual_counts_as_realized_paper_profit": False,
        "paper_only": True,
        "live_eligible": False,
    }
    manifest_sha = _canonical_sha(manifest_material)
    manifest = {
        **manifest_material,
        "manifest_id": "adaptive-manifest-test",
        "manifest_sha256": manifest_sha,
    }
    parity = {
        "schema_version": "adaptive_train_serve_feature_parity_report_v2",
        "feature_abi_sha256": sha_a,
        "training_feature_builder_sha256": sha_b,
        "serving_feature_builder_sha256": sha_b,
        "builder_match": True,
        "ordered_feature_names_match": True,
        "required_feature_missing_rate": 0.0,
        "training_rows": 1,
        "validation_rows": 1,
        "holdout_rows": 0,
        "activation_eligible": False,
        "live_eligible": False,
    }
    dataset_path = root / "adaptive_serving_compatible_dataset_v2.json"
    manifest_path = root / "adaptive_serving_compatible_dataset_manifest_v2.json"
    parity_path = root / "adaptive_train_serve_feature_parity_report_v2.json"
    artifact_hashes = {
        dataset_path.name: _write_pretty(dataset_path, dataset),
        manifest_path.name: _write_pretty(manifest_path, manifest),
        parity_path.name: _write_pretty(parity_path, parity),
    }
    receipt = {
        "schema_version": "candidate_outcome_dataset_build_receipt_v2",
        "status": "PASS",
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": dataset_sha,
        "manifest_id": manifest["manifest_id"],
        "manifest_sha256": manifest_sha,
        "artifact_file_sha256s": artifact_hashes,
        "candidate_archive_verification": {
            "candidate_count": 3,
            "matured_revision_count": 2,
            "terminal_chain_sha256": "d" * 64,
            "verified": True,
            "invalid_row_count": 0,
            "duplicate_archive_record_count": 0,
        },
        "candidate_records_fully_accounted": True,
        "counterfactual_counts_as_realized_paper_profit": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    _write_pretty(root / "candidate_outcome_dataset_build_receipt_v2.json", receipt)
    frozen = {"dataset_sha256": "c" * 64, "training_eligible_rows": 1}
    candidate = {
        "candidate_outcome_rows": 3,
        "matured_candidate_outcome_rows": 2,
        "archive_terminal_chain_sha256": "d" * 64,
    }
    return frozen, candidate


def test_candidate_training_profile_verifies_exact_dataset_accounting(tmp_path: Path):
    root = tmp_path / "adaptive"
    frozen, candidate = _adaptive_artifacts(root)
    profile = _candidate_training_profile(
        root,
        frozen_corpus=frozen,
        candidate_outcomes=candidate,
    )
    assert profile["serving_eligible_candidate_rows"] == 1
    assert profile["dataset_admitted_candidate_rows"] == 1
    assert profile["candidate_validation_rows"] == 1
    assert profile["artifact_verified"] is True


def test_candidate_training_profile_rejects_artifact_tamper(tmp_path: Path):
    root = tmp_path / "adaptive"
    frozen, candidate = _adaptive_artifacts(root)
    dataset_path = root / "adaptive_serving_compatible_dataset_v2.json"
    dataset_path.write_text(dataset_path.read_text() + " ", encoding="utf-8")
    with pytest.raises(DataUtilizationCollectorError, match="FILE_HASH_MISMATCH"):
        _candidate_training_profile(
            root,
            frozen_corpus=frozen,
            candidate_outcomes=candidate,
        )
