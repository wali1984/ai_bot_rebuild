from __future__ import annotations

import copy

import pytest

from v2.backend.app.services.adaptive_system.data_utilization_report_v3 import (
    DataUtilizationReportError,
    build_data_utilization_report_v3,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _frozen() -> dict:
    return {
        "snapshot_id": "gen5_fixed_observation_v1:test",
        "snapshot_manifest_sha256": SHA_A,
        "dataset_id": "serving_dataset_v2_test",
        "dataset_sha256": SHA_B,
        "dataset_manifest_id": "serving_manifest_v2_test",
        "dataset_manifest_sha256": SHA_C,
        "raw_events": 302_183,
        "canonical_events": 302_183,
        "feature_snapshots": 810,
        "finality_proven_snapshots": 810,
        "cost_complete_snapshots": 397,
        "microstructure_complete_snapshots": 397,
        "labeled_snapshots": 386,
        "training_eligible_rows": 382,
        "historical_exclusions_by_stage": {
            "finality_proven_snapshots": {"CAUSAL_COST_RECEIPTS_ABSENT": 413},
            "microstructure_complete_snapshots": {"LABEL_PATH_GAP": 11},
            "labeled_snapshots": {"PREDECLARED_PURGE_EMBARGO_ROW": 4},
        },
        "source_integrity_verified": True,
        "complete_paid_source_inventory_bound": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _candidate(*, overlap: int = 0) -> dict:
    return {
        "candidate_outcome_rows": 8_471,
        "matured_candidate_outcome_rows": 7_854,
        "pending_reasons": {
            "HORIZON_NOT_YET_DUE": 271,
            "MATURATION_BATCH_LIMIT": 259,
            "LABEL_ARCHIVE_GAP": 4,
            "RECONCILED_ACTUAL_PAPER_CLOSE_REQUIRED": 83,
        },
        "gen5_exact_identity_overlap_rows": overlap,
        "archive_verified": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _training() -> dict:
    return {
        "dataset_id": "adaptive_serving_dataset_v2_test",
        "dataset_sha256": SHA_D,
        "manifest_id": "adaptive_serving_manifest_v2_test",
        "manifest_sha256": SHA_A,
        "base_dataset_sha256": SHA_B,
        "base_dataset_rows": 382,
        "serving_eligible_candidate_rows": 7_369,
        "dataset_admitted_candidate_rows": 4_618,
        "candidate_training_rows": 2_657,
        "candidate_validation_rows": 799,
        "candidate_holdout_rows": 1_162,
        "serving_rejections_by_reason": {
            "serving_feature_vector:FEATURE_STALENESS_LIMIT_EXCEEDED": 485,
        },
        "split_purge_reasons": {
            "FEATURE_GROUP_CROSSES_SPLIT_BOUNDARY": 43,
            "TRAIN_LABEL_NOT_AVAILABLE_BEFORE_VALIDATION": 1_180,
            "VALIDATION_LABEL_NOT_AVAILABLE_BEFORE_HOLDOUT": 1_528,
        },
        "candidate_records_fully_accounted": True,
        "counterfactual_counts_as_realized_paper_profit": False,
        "artifact_verified": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _registry() -> dict:
    return {
        "checkpoint_id": "active",
        "registry_generation": 3,
        "registry_binding_verified": True,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _checkpoints() -> list[dict]:
    return [
        {
            "checkpoint_id": "active",
            "content_sha256": SHA_D,
            "training_manifest_id": "active_manifest",
            "training_manifest_sha256": SHA_A,
            "training_rows": 147,
            "validation_rows": 23,
            "holdout_rows": 22,
            "source_paths": ["redis:active"],
        },
        {
            "checkpoint_id": "gen5_candidate",
            "content_sha256": SHA_C,
            "training_manifest_id": "serving_manifest_v2_test",
            "training_manifest_sha256": SHA_C,
            "training_rows": 289,
            "validation_rows": 46,
            "holdout_rows": 47,
            "source_paths": ["candidate.json"],
        },
    ]


def _build(**overrides):
    arguments = {
        "generated_at": "2026-07-28T12:00:00.000Z",
        "frozen_corpus": _frozen(),
        "candidate_outcomes": _candidate(),
        "candidate_training": _training(),
        "checkpoint_rows": _checkpoints(),
        "active_registry": _registry(),
    }
    arguments.update(overrides)
    return build_data_utilization_report_v3(**arguments)


def test_report_reconciles_matured_outcomes_into_adaptive_training_dataset():
    report = _build()
    assert report["paths_consistent"] is True
    assert report["source_integrity_verified"] is True
    assert report["status"] == "PASS"
    assert report["blockers"] == []
    assert report["typed_candidate_outcomes_joined_to_training"] is True
    assert report["candidate_outcome_training_join"]["complete"] is True
    assert report["candidate_outcome_training_join"]["legacy_gen5_exact_identity_overlap_rows"] == 0
    assert report["required_counters"]["rows_used_by_each_checkpoint"] == {
        "active": 192,
        "gen5_candidate": 382,
    }
    assert len(report["report_sha256"]) == 64


def test_report_blocks_when_candidate_training_artifact_is_not_verified():
    training = _training()
    training["artifact_verified"] = False
    report = _build(candidate_training=training)
    assert report["status"] == "BLOCK"
    assert report["source_integrity_verified"] is False
    assert "SOURCE_INTEGRITY_UNVERIFIED" in report["blockers"]


def test_bad_transition_reason_count_keeps_report_red():
    frozen = _frozen()
    frozen["historical_exclusions_by_stage"]["microstructure_complete_snapshots"] = {
        "LABEL_PATH_GAP": 10
    }
    report = _build(frozen_corpus=frozen)
    assert report["paths_consistent"] is False
    assert "IDENTITY_SCOPED_FUNNEL_INCONSISTENT" in report["blockers"]


def test_unsafe_authority_flag_keeps_report_red():
    candidate = _candidate()
    candidate["routes_to_live"] = True
    report = _build(candidate_outcomes=candidate)
    assert report["status"] == "BLOCK"
    assert "PAPER_LIVE_AUTHORITY_BOUNDARY_INVALID" in report["blockers"]


def test_unbound_paid_source_inventory_keeps_report_red():
    frozen = _frozen()
    frozen["complete_paid_source_inventory_bound"] = False
    report = _build(
        frozen_corpus=frozen,
        candidate_outcomes=_candidate(),
    )
    assert report["status"] == "BLOCK"
    assert "FULL_PAID_SOURCE_INVENTORY_NOT_BOUND_TO_FROZEN_GEN5_SCOPE" in report["blockers"]


def test_missing_active_checkpoint_usage_fails_closed():
    with pytest.raises(DataUtilizationReportError, match="ACTIVE_CHECKPOINT_USAGE_MISSING"):
        _build(checkpoint_rows=_checkpoints()[1:])


def test_duplicate_checkpoint_identity_conflict_fails_closed():
    rows = _checkpoints()
    conflicting = copy.deepcopy(rows[0])
    conflicting["training_rows"] += 1
    rows.append(conflicting)
    with pytest.raises(DataUtilizationReportError, match="CHECKPOINT_IDENTITY_CONFLICT"):
        _build(checkpoint_rows=rows)
