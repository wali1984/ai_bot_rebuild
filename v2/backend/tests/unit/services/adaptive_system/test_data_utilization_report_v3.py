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
        "checkpoint_rows": _checkpoints(),
        "active_registry": _registry(),
    }
    arguments.update(overrides)
    return build_data_utilization_report_v3(**arguments)


def test_report_is_consistent_but_blocks_unjoined_identity_domains():
    report = _build()
    assert report["paths_consistent"] is True
    assert report["source_integrity_verified"] is True
    assert report["status"] == "BLOCK"
    assert report["blockers"] == [
        "TYPED_CANDIDATE_OUTCOMES_NOT_JOINED_TO_GEN5_TRAINING_ROWS"
    ]
    assert report["required_counters"]["rows_used_by_each_checkpoint"] == {
        "active": 192,
        "gen5_candidate": 382,
    }
    assert len(report["report_sha256"]) == 64


def test_report_passes_only_when_exact_typed_outcome_join_is_complete():
    report = _build(candidate_outcomes=_candidate(overlap=382))
    assert report["status"] == "PASS"
    assert report["complete_eligible_data_utilized"] is True
    assert report["blockers"] == []


def test_bad_transition_reason_count_keeps_report_red():
    frozen = _frozen()
    frozen["historical_exclusions_by_stage"]["microstructure_complete_snapshots"] = {
        "LABEL_PATH_GAP": 10
    }
    report = _build(frozen_corpus=frozen)
    assert report["paths_consistent"] is False
    assert "IDENTITY_SCOPED_FUNNEL_INCONSISTENT" in report["blockers"]


def test_unsafe_authority_flag_keeps_report_red():
    candidate = _candidate(overlap=382)
    candidate["routes_to_live"] = True
    report = _build(candidate_outcomes=candidate)
    assert report["status"] == "BLOCK"
    assert "PAPER_LIVE_AUTHORITY_BOUNDARY_INVALID" in report["blockers"]


def test_unbound_paid_source_inventory_keeps_report_red():
    frozen = _frozen()
    frozen["complete_paid_source_inventory_bound"] = False
    report = _build(
        frozen_corpus=frozen,
        candidate_outcomes=_candidate(overlap=382),
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
