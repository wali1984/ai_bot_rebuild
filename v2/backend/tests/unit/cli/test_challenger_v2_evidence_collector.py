from __future__ import annotations

from v2.backend.app.cli.v2_challenger_v2_evidence_collector import (
    ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS,
    added_paper_governance_blocker_audit,
    append_matured_labels,
    append_pending_lockbox,
    blind_lockbox_pass_contract_audit,
    bounded_paper_signal_scan,
    cost_evidence_for_row,
    cost_replay_paper_parity_audit_from_evidence,
    cost_identity_join_recovery_audit,
    distribution_drift_coverage_audit,
    distribution_drift_artifact,
    distribution_drift_mapping_confidence_audit,
    enrich_current_snapshots_with_top_book,
    enrich_snapshots_with_paper_intents_from_rows,
    forward_paper_canary_pass_contract_audit_from_rows,
    forward_paper_canary_pass_contract_audit_from_redis,
    frozen_candidate_integrity_audit,
    future_lockbox_integrity_audit,
    future_runtime_cost_evidence_acceptance_contract,
    future_runtime_cost_evidence_acceptance_decision,
    challenger_goal_phase_completion_audit,
    goal_rollup_summary_aliases,
    goal_requirement_traceability_matrix,
    label_for_record,
    lockbox_performance,
    paper_binding_identity_preflight_from_rows,
    paper_binding_rows_from_redis_value,
    paper_canary_binding_readiness_artifact,
    paper_chain_binding_readiness_audit,
    paper_challenger_credit_attribution_guard,
    paper_cost_source_group,
    paper_cost_telemetry_readiness_from_rows,
    read_local_paper_cost_event_rows,
    parse_orderbook_top_book,
    parse_kline_candle,
    point_in_time_violation_count,
    production_cost_capture_gap_audit,
    production_cost_evidence_artifacts,
    psi_statistic,
    replay_drift_split,
    row_hash,
    runtime_cost_capture_contract_audit,
    runtime_cost_capture_approval_subject,
    runtime_cost_capture_operator_approval_packet,
    runtime_cost_capture_operator_approval_receipt_status,
    runtime_cost_capture_operator_approval_receipt_template,
    runtime_cost_capture_remediation_contract,
    runtime_cost_capture_write_path_audit,
    runtime_identity_binding_implementation_plan,
    shadow_supply_artifact,
    shadow_supply_contract_audit,
    append_shadow_cost_evidence,
    shadow_cost_reconciliation_audit,
    shadow_cost_evidence_record,
    shadow_cost_evidence_status,
    shadow_lockbox_outcome_actionability_audit,
    write_shadow_cost_hash_chain,
    shadow_label_outcome_diagnostics,
    source_presence_for_required_field,
    summarize_cost_rows,
    summarize_source_presence,
    temporal_semantics_audit,
    update_forward_blockers,
    write_hash_chain,
    zero_candidate_supply_diagnosis,
)

import copy
import json
import sys
from datetime import timedelta
from types import SimpleNamespace

from v2.backend.app.services.native_trainer.challenger_v2_cost_model import cost_model_hash
from v2.backend.app.services.native_trainer.challenger_v2_feature_adapter import (
    NormalizationSpec,
    feature_schema_hash,
    normalization_hash,
    stable_hash,
)


def test_goal_rollup_summary_aliases_expose_unprefixed_completion_fields() -> None:
    aliases = goal_rollup_summary_aliases(
        {
            "status": "BLOCKED_GOAL_COMPLETION_AUDIT",
            "goal_complete": False,
            "blocked_phases": ["phase_1_production_grade_cost_evidence"],
            "blocked_phase_count": 1,
            "blocked_conditions": ["phase_1.production_grade_cost_coverage_gte_95pct"],
            "blocked_condition_count": 1,
            "blocked_by_phase": {"phase_1_production_grade_cost_evidence": 1},
            "phase_statuses": {"phase_1_production_grade_cost_evidence": "BLOCKED"},
            "phase_blockers": {"phase_1_production_grade_cost_evidence": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
            "pass_conditions": {"phase_1_production_grade_cost_evidence_passed": False},
        },
        {
            "status": "BLOCKED_GOAL_REQUIREMENTS_REMAIN",
            "total_requirement_count": 116,
            "passed_requirement_count": 72,
            "blocked_requirement_count": 44,
            "failed_requirement_count": 44,
            "blocked_requirements": 44,
            "failed_by_phase": {"phase_1_production_grade_cost_evidence": 13},
            "blocked_by_phase": {"phase_1_production_grade_cost_evidence": 13},
        },
    )

    assert aliases["goal_phase_completion_status"] == "BLOCKED_GOAL_COMPLETION_AUDIT"
    assert aliases["goal_complete"] is False
    assert aliases["blocked_phases"] == aliases["goal_blocked_phases"]
    assert aliases["blocked_phase_count"] == 1
    assert aliases["blocked_condition_count"] == 1
    assert aliases["blocked_by_phase"] == {"phase_1_production_grade_cost_evidence": 1}
    assert aliases["goal_requirement_traceability_status"] == "BLOCKED_GOAL_REQUIREMENTS_REMAIN"
    assert aliases["total_requirement_count"] == 116
    assert aliases["passed_requirement_count"] == 72
    assert aliases["blocked_requirement_count"] == 44
    assert aliases["failed_requirement_count"] == 44
    assert aliases["failed_by_phase"] == {"phase_1_production_grade_cost_evidence": 13}


def test_goal_rollup_summary_aliases_fall_back_to_legacy_requirement_counts() -> None:
    aliases = goal_rollup_summary_aliases(
        {"status": "PASS_GOAL_COMPLETION_AUDIT", "goal_complete": True},
        {
            "status": "PASS_GOAL_REQUIREMENT_TRACEABILITY_MATRIX",
            "total_requirements": 10,
            "passed_requirements": 10,
            "blocked_requirements": 0,
            "failed_requirements": 0,
            "blocked_by_phase": {},
        },
    )

    assert aliases["total_requirement_count"] == 10
    assert aliases["passed_requirement_count"] == 10
    assert aliases["blocked_requirement_count"] == 0
    assert aliases["failed_requirement_count"] == 0
    assert aliases["failed_by_phase"] == {}


def test_fallback_cost_missing_rows_are_explained_not_production_grade() -> None:
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_freshness_state": "CURRENT",
        "features": {"close": 100.0},
    }

    evidence = cost_evidence_for_row(row, source_context="replay")
    summary = summarize_cost_rows([evidence])

    assert evidence["fallback"] is True
    assert evidence["production_grade"] is False
    assert evidence["unexplained_missing"] is False
    assert evidence["replay_paper_cost_parity"] is True
    assert evidence["replay_paper_cost_parity_by_side"] == {"long": True, "short": True}
    assert evidence["replay_paper_cost_parity_mismatch_sides"] == []
    assert summary["production_grade_cost_coverage"] == 0.0
    assert summary["unexplained_cost_missing_rows"] == 0
    assert summary["replay_paper_cost_parity_mismatch_rows"] == 0
    assert summary["replay_paper_cost_parity_mismatch_side_counts"] == {}


def test_cost_summary_counts_short_side_parity_mismatch() -> None:
    summary = summarize_cost_rows(
        [
            {
                "source_context": "test",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "snapshot_id": "snap-1",
                "decision_time": "2026-06-25T00:01:00Z",
                "production_grade": False,
                "unexplained_missing": False,
                "fallback": False,
                "evidence_flags": {},
                "fallback_components": [],
                "replay_paper_cost_parity": False,
                "replay_paper_cost_parity_by_side": {"long": True, "short": False},
                "replay_paper_cost_parity_mismatch_sides": ["short"],
            }
        ]
    )

    assert summary["replay_paper_cost_parity_mismatch_rows"] == 1
    assert summary["replay_paper_cost_parity_mismatch_side_counts"] == {"short": 1}
    assert summary["sample_replay_paper_cost_parity_mismatch_rows"][0]["mismatch_sides"] == ["short"]


def test_cost_replay_paper_parity_audit_passes_side_level_identity() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    evidence = [
        {
            "source_context": "replay",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "snapshot_id": "snap-1",
            "decision_time": "2026-06-25T00:01:00Z",
            "feature_cutoff": "2026-06-25T00:00:00Z",
            "available_at": "2026-06-25T00:00:30Z",
            "replay_paper_cost_parity_by_side": {"long": True, "short": True},
        },
        {
            "source_context": "current_runtime",
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "snapshot_id": "snap-2",
            "decision_time": "2026-06-25T00:02:00Z",
            "feature_cutoff": "2026-06-25T00:01:00Z",
            "available_at": "2026-06-25T00:01:30Z",
            "replay_paper_cost_parity_by_side": {"long": True, "short": True},
        },
    ]

    payload = cost_replay_paper_parity_audit_from_evidence(policy=policy, evidence_rows=evidence)

    assert payload["status"] == "PASS_COST_REPLAY_PAPER_PARITY_AUDIT"
    assert payload["rows_examined"] == 2
    assert payload["comparable_rows"] == 2
    assert payload["compared_rows"] == 2
    assert payload["matched_rows"] == 2
    assert payload["same_snapshot_order_comparison_rows"] == 2
    assert payload["same_snapshot_order_side_comparisons"] == 4
    assert payload["matched_side_comparisons"] == 4
    assert payload["replay_paper_cost_parity_comparable_rows"] == 2
    assert payload["replay_paper_cost_parity_compared_side_count"] == 4
    assert payload["replay_paper_cost_parity_matched_rows"] == 2
    assert payload["replay_paper_cost_parity_matched_side_count"] == 4
    assert payload["replay_paper_cost_parity_mismatch_rows"] == 0
    assert payload["source_context_counts"] == {"current_runtime": 1, "replay": 1}
    assert payload["mismatch_rows"] == 0
    assert payload["side_mismatch_counts"] == {}
    assert all(payload["pass_conditions"].values())
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_cost_replay_paper_parity_audit_reports_side_mismatch() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    evidence = [
        {
            "source_context": "replay",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "snapshot_id": "snap-1",
            "decision_time": "2026-06-25T00:01:00Z",
            "feature_cutoff": "2026-06-25T00:00:00Z",
            "available_at": "2026-06-25T00:00:30Z",
            "replay_paper_cost_parity_by_side": {"long": True, "short": False},
        }
    ]

    payload = cost_replay_paper_parity_audit_from_evidence(policy=policy, evidence_rows=evidence)

    assert payload["status"] == "FAIL_COST_REPLAY_PAPER_PARITY_AUDIT"
    assert payload["mismatch_rows"] == 1
    assert payload["comparable_rows"] == 1
    assert payload["same_snapshot_order_side_comparisons"] == 2
    assert payload["matched_rows"] == 0
    assert payload["matched_side_comparisons"] == 1
    assert payload["replay_paper_cost_parity_mismatch_rows"] == 1
    assert payload["side_mismatch_counts"] == {"short": 1}
    assert payload["pass_conditions"]["short_side_mismatch_rows_eq_0"] is False
    assert payload["sample_mismatch_rows"][0]["mismatch_sides"] == ["short"]
    assert payload["promotion_evidence"] is False


def test_cost_replay_paper_parity_audit_blocks_vacuous_empty_comparison() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = cost_replay_paper_parity_audit_from_evidence(policy=policy, evidence_rows=[])

    assert payload["status"] == "FAIL_COST_REPLAY_PAPER_PARITY_AUDIT"
    assert payload["rows_examined"] == 0
    assert payload["comparable_rows"] == 0
    assert payload["same_snapshot_order_comparison_rows"] == 0
    assert payload["same_snapshot_order_side_comparisons"] == 0
    assert payload["pass_conditions"]["rows_examined_gt_0"] is False
    assert payload["pass_conditions"]["same_snapshot_order_comparison_rows_gt_0"] is False
    assert payload["pass_conditions"]["same_snapshot_order_side_comparisons_gt_0"] is False
    assert payload["replay_paper_cost_parity_mismatch_rows"] == 0
    assert payload["paper_fill_allowed"] is False


def test_production_cost_artifacts_expose_top_level_phase_1_audit_fields() -> None:
    policy = SimpleNamespace(candidate_id="challenger_v2_test", policy_fingerprint="fingerprint")
    replay_row = SimpleNamespace(
        snapshot={
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "snapshot_id": "replay-1",
            "decision_time": "2026-06-25T00:01:00Z",
            "feature_cutoff": "2026-06-25T00:00:00Z",
            "available_at": "2026-06-25T00:00:01Z",
            "feature_freshness_state": "CURRENT",
            "features": {
                "actual_observed_spread_entry_bps": 2.0,
                "ask_depth_usd": 10_000.0,
                "expected_funding_bps": 0.1,
                "mark_price": 100.0,
                "index_price": 100.0,
            },
        }
    )
    current_row = {
        "symbol": "ETHUSDT",
        "timeframe": "1m",
        "snapshot_id": "current-1",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_freshness_state": "CURRENT",
        "best_bid": 100.0,
        "best_ask": 100.1,
        "top_book_bid_depth_usd": 1_000.0,
        "top_book_ask_depth_usd": 1_100.0,
        "features": {
            "expected_funding_bps": 0.1,
            "mark_price": 100.0,
            "index_price": 100.0,
        },
    }

    status, matrix = production_cost_evidence_artifacts(
        policy=policy,
        replay_rows=[replay_row],
        current_snapshots=[current_row],
        current_source="unit_test",
    )

    assert status["replay_rows_examined"] == 1
    assert status["current_rows_examined"] == 1
    assert status["total_rows"] == status["total_cost_evidence_rows"] == 2
    assert status["replay_paper_cost_parity_comparable_rows"] == 2
    assert status["replay_paper_cost_parity_same_snapshot_order_rows"] == 2
    assert status["replay_paper_cost_parity_compared_side_count"] == 4
    assert status["replay_paper_cost_parity_matched_rows"] == 2
    assert status["replay_paper_cost_parity_matched_side_count"] == 4
    assert status["replay_paper_cost_parity_non_vacuous"] is True
    assert status["replay_paper_cost_parity_comparison_contract"]["comparable_rows"] == 2
    assert status["replay_paper_cost_parity_comparison_contract"]["side_comparisons"] == 4
    assert status["replay_paper_cost_parity_comparison_contract"]["mismatch_rows"] == 0
    assert status["replay_paper_cost_parity_comparison_contract"]["non_vacuous"] is True
    assert status["production_grade_rows"] == status["production_grade_cost_rows"]
    assert status["fallback_rows"] == status["fallback_true_rows"]
    assert status["shadow_only_fallback_rows"] == status["fallback_true_rows"]
    assert status["required_fields"] == status["required_evidence_fields"]
    assert status["required_cost_fields"] == status["required_evidence_fields"]
    assert status["required_production_cost_fields"] == status["required_evidence_fields"]
    assert status["cost_evidence_fields"] == matrix["fields"]
    assert status["field_coverage"] == matrix["fields"]
    assert status["required_coverage"] == 0.95
    assert status["production_grade_cost_coverage_required"] == ">=0.95"
    assert status["production_grade_cost_coverage_shortfall_to_required"] == 0.95
    assert status["required_evidence_fields_present"] is False
    assert status["required_cost_fields_present_for_all_rows"] is False
    assert status["required_evidence_fields_covered_gte_95pct"] is False
    assert status["required_cost_fields_covered_gte_95pct"] is False
    assert status["missing_field_counts"] == matrix["missing_field_counts"]
    assert status["missing_cost_field_counts"] == status["missing_field_counts"]
    assert status["required_field_missing_counts"] == status["missing_field_counts"]
    assert status["missing_required_field_counts"] == status["missing_field_counts"]
    assert set(status["required_fields_present_counts"]) == set(status["required_fields"])
    assert status["source_group_summary"] == matrix["coverage_by_source_group"]
    assert status["source_group_coverage"] == matrix["coverage_by_source_group"]
    assert "order_size" in status["hard_blocking_fields"]
    assert status["hard_blocking_cost_fields"] == status["hard_blocking_fields"]
    assert status["hard_blocker_fields"] == status["hard_blocking_fields"]
    assert "order_size" in status["hard_blocking_missing_fields"]
    assert status["hard_blocking_missing_cost_fields"] == status["hard_blocking_missing_fields"]
    assert status["hard_blocker_missing_fields"] == status["hard_blocking_missing_fields"]
    assert status["hard_blocking_missing_field_counts"]["order_size"] == 2
    assert status["hard_blocking_missing_cost_field_counts"] == status["hard_blocking_missing_field_counts"]
    assert status["hard_blocker_missing_field_counts"] == status["hard_blocking_missing_field_counts"]
    assert status["hard_blocking_present_counts"]["order_size"] == 0
    assert status["hard_blocking_cost_present_counts"] == status["hard_blocking_present_counts"]
    assert status["hard_blocking_missing_field_count"] == len(status["hard_blocking_missing_fields"])
    assert status["hard_blocking_cost_field_count"] == status["hard_blocking_field_count"]
    assert status["hard_blocking_missing_cost_field_count"] == status["hard_blocking_missing_field_count"]
    assert status["hard_blocker_missing_field_count"] == status["hard_blocking_missing_field_count"]
    assert status["hard_blocking_missing_row_total"] == sum(status["hard_blocking_missing_field_counts"].values())
    assert status["hard_blocking_missing_cost_row_total"] == status["hard_blocking_missing_row_total"]
    assert status["hard_blocker_missing_row_total"] == status["hard_blocking_missing_row_total"]
    assert status["safe_next_capture_boundary"]["order_size"] == "adaptive_allocator_or_paper_intent_pre_submit"
    assert status["source_group_recovery_classification"]["replay"]["recovery_class"] == (
        "HISTORICAL_REPLAY_COST_EVIDENCE_IRRECOVERABLE_WITHOUT_NEW_POINT_IN_TIME_CAPTURE"
    )
    assert "order_size" in status["replay_irrecoverable_cost_evidence_fields"]
    assert "order_size" in status["current_runtime_future_capture_required_fields"]
    assert "order_size" in status["combined_hard_missing_cost_evidence_fields"]
    assert status["existing_replay_rows_may_be_backfilled_for_credit"] is False
    assert status["existing_current_runtime_rows_may_be_backfilled_for_credit"] is False
    assert status["cost_evidence_recovery_classification"]["paper_fill_allowed"] is False
    assert status["cost_evidence_recovery_classification"]["routes_to_live"] is False
    assert status["sample_missing_cost_evidence_rows"][0]["source_context"] == "replay"
    assert status["sample_missing_cost_evidence_rows_by_source_group"]["replay"][0]["snapshot_id"] == "replay-1"
    assert status["shortfall_to_95pct"] == status["phase_1_exit_minimum_new_candidate_bound_production_grade_rows"]
    assert status["fallback_true_rows_may_count_as_production_evidence"] is False
    assert status["fallback_rows_shadow_only"] is True
    assert status["fallback_rows_are_shadow_only"] is True
    assert status["fallback_rows_count_as_production_grade_evidence"] is False
    assert status["fallback_rows_count_as_production_grade_training_evidence"] is False
    assert status["fallback_rows_count_as_lockbox_evidence"] is False
    assert status["fallback_rows_count_as_promotion_evidence"] is False
    assert status["production_evidence_rules"] == {
        "fallback_true_rows_may_be_shadow_scored": True,
        "fallback_true_rows_may_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
        "fallback_true_rows_may_count_as_production_grade_evidence": False,
        "fallback_true_rows_may_count_as_lockbox_evidence": False,
        "fallback_true_rows_may_count_as_promotion_evidence": False,
        "required_cost_fields_must_be_present_for_all_rows": True,
        "production_grade_cost_coverage_required": ">=0.95",
        "unexplained_cost_missing_rows_required": 0,
        "replay_and_paper_costs_identical_for_same_snapshot_order_required": True,
    }
    assert status["paper_fill_allowed"] is False
    assert status["routes_to_live"] is False
    assert status["counts_as_a_grade_evidence"] is False
    assert status["promotion_evidence"] is False
    assert status["replay_paper_cost_parity"] is True
    assert status["replay_paper_cost_parity_for_same_snapshot_order"] is True
    assert status["replay_paper_identical_costs_for_same_snapshot_order"] is True
    assert status["replay_paper_identical_costs"] is True
    assert status["replay_and_paper_produce_identical_costs_for_same_snapshot_order"] is True
    assert status["pass_conditions"]["replay_paper_cost_parity_comparable_rows_gt_0"] is True
    assert status["pass_conditions"]["replay_paper_cost_parity_side_comparisons_gt_0"] is True
    assert (
        status["replay_paper_cost_parity_for_same_snapshot_order"]
        == status["pass_conditions"]["replay_paper_cost_parity_for_same_snapshot_order"]
    )
    assert "production_grade_cost_coverage_gte_95pct" in status["blocked_reasons"]
    assert status["pass_conditions"]["required_cost_field_order_size_present_for_all_rows"] is False
    assert "required_cost_field_order_size_present_for_all_rows" in status["blocked_reasons"]
    assert status["required_field_pass_conditions"]["required_cost_field_order_size_present_for_all_rows"] is False
    assert status["required_field_all_rows_pass_conditions"] == status["required_field_pass_conditions"]
    assert status["required_field_coverage_pass_conditions"]["required_cost_field_order_size_coverage_gte_95pct"] is False
    assert any(
        detail["field"] == "order_size"
        and detail["pass_condition"] == "required_cost_field_order_size_present_for_all_rows"
        and detail["hard_blocking_field"] is True
        for detail in status["required_field_blocker_details"]
    )
    assert any(detail["field"] == "order_size" for detail in status["hard_blocking_field_blocker_details"])
    assert "required_cost_field_order_size_present_for_all_rows" in status["hard_blocking_field_blocked_reasons"]
    assert status["cost_evidence_blocker_details"][0]["passed"] is False
    assert status["blocker_details"] == status["cost_evidence_blocker_details"]
    assert status["failed_blocker_details"] == status["cost_evidence_blocker_details"]
    assert status["actuals"]["production_grade_cost_coverage_gte_95pct"] == 0.0
    assert status["required"]["production_grade_cost_coverage_gte_95pct"] == ">=0.95"
    assert status["actuals"]["required_cost_fields_present_for_all_rows"]["missing_required_field_counts"] == status[
        "missing_required_field_counts"
    ]
    assert status["required"]["required_cost_fields_present_for_all_rows"]["missing_required_field_counts"] == {
        field: 0 for field in status["required_fields"]
    }
    assert status["sample_blockers"] == status["cost_evidence_blocker_details"][:25]
    assert status["source_recovery_summary"] == status["source_group_recovery_classification"]
    assert status["replay_paper_cost_parity"] is True
    assert status["replay_paper_cost_parity_mismatch_side_counts"] == {}
    assert matrix["status"] == "FAIL_COST_SOURCE_COVERAGE_MATRIX"
    assert matrix["overall_status"] == matrix["status"]
    assert matrix["pass_conditions"]["replay_source_presence_computed"] is True
    assert matrix["pass_conditions"]["current_runtime_source_presence_computed"] is True
    assert matrix["required_fields"] == matrix["required_evidence_fields"]
    assert matrix["required_cost_evidence_fields"] == matrix["required_evidence_fields"]
    assert matrix["required_cost_fields"] == matrix["required_evidence_fields"]
    assert matrix["required_production_cost_fields"] == matrix["required_evidence_fields"]
    assert matrix["required_source_fields"] == matrix["required_evidence_fields"]
    assert matrix["required_coverage"] == 0.95
    assert matrix["source_field_coverage_required"] == ">=0.95"
    assert matrix["total_rows"] == matrix["total_cost_evidence_rows"] == 2
    assert matrix["combined_coverage"] == 0.0
    assert matrix["combined_source_coverage"] == matrix["combined_coverage"]
    assert matrix["combined_required_field_min_coverage"] == matrix["combined_coverage"]
    assert matrix["production_grade_cost_coverage"] == status["production_grade_cost_coverage"]
    assert matrix["production_grade_rows"] == matrix["production_grade_cost_rows"]
    assert matrix["fallback_rows"] == matrix["shadow_only_fallback_rows"]
    assert matrix["source_coverage"] == matrix["coverage_by_source_group"]
    assert matrix["coverage_by_source"] == matrix["coverage_by_source_group"]
    assert matrix["source_coverage_matrix"] == matrix["coverage_by_source_group"]
    assert matrix["source_coverage_by_group"] == matrix["coverage_by_source_group"]
    assert matrix["cost_source_coverage_by_group"] == matrix["coverage_by_source_group"]
    assert matrix["field_coverage_by_source_group"] == matrix["coverage_by_source_group"]
    assert matrix["required_cost_field_coverage_by_source_group"] == matrix["coverage_by_source_group"]
    assert matrix["source_group_coverage"] == matrix["coverage_by_source_group"]
    assert matrix["source_group_summary"] == matrix["source_group_summaries"]
    assert matrix["source_group_cost_coverage_summary"] == matrix["source_group_summary"]
    assert matrix["source_group_summary"]["combined"]["row_count"] == 2
    assert matrix["source_group_summary"]["combined"]["required_cost_fields"] == matrix["required_cost_fields"]
    assert matrix["source_group_summary"]["combined"]["required_cost_fields_present_for_all_rows"] is False
    assert matrix["source_group_summary"]["combined"]["required_cost_fields_covered_gte_95pct"] is False
    assert matrix["source_group_summary"]["combined"]["minimum_required_cost_field_coverage"] == 0.0
    assert matrix["source_group_summary"]["combined"]["missing_cost_field_counts"]["order_size"] == 2
    assert "order_size" in matrix["source_group_summary"]["combined"]["hard_blocking_missing_cost_fields"]
    assert matrix["source_group_summary"]["combined"]["field_coverage"] == matrix["coverage_by_source_group"]["combined"]
    assert matrix["field_coverage"] == matrix["fields"]
    assert matrix["coverage_by_field"] == matrix["fields"]
    assert matrix["source_coverage_by_field"] == matrix["coverage_by_field"]
    assert matrix["source_field_coverage_summary"] == matrix["fields"]
    assert matrix["source_groups"] == ["replay", "current_runtime", "combined"]
    assert matrix["coverage_by_source_group"]["combined"]["observed_bid_ask_spread"]["present_rows"] == 2
    assert matrix["missing_field_counts_by_source_group"]["combined"]["order_size"] == 2
    assert matrix["missing_field_counts_by_source_group"]["replay"]["order_size"] == 1
    assert matrix["missing_field_counts_by_source_group"]["current_runtime"]["order_size"] == 1
    assert matrix["coverage_by_source_group"]["replay"]["order_size"]["sample_missing_rows"][0]["snapshot_id"] == "replay-1"
    assert matrix["source_presence"]["combined"]["fields"]["order_size"]["sample_missing_rows"][0]["snapshot_id"] == "replay-1"
    assert matrix["source_group_recovery_classification"] == status["source_group_recovery_classification"]
    assert matrix["replay_irrecoverable_cost_evidence_fields"] == status["replay_irrecoverable_cost_evidence_fields"]
    assert matrix["fields"]["observed_bid_ask_spread"]["present_rows"] == 2
    assert matrix["missing_field_counts"]["order_size"] == 2
    assert matrix["missing_cost_field_counts"] == matrix["missing_field_counts"]
    assert matrix["missing_required_field_counts"] == matrix["missing_field_counts"]
    assert matrix["missing_by_field"] == matrix["missing_field_counts"]
    assert matrix["missing_source_field_counts"] == matrix["missing_field_counts"]
    assert matrix["missing_required_source_field_counts"] == matrix["missing_field_counts"]
    assert matrix["missing_cost_field_counts_by_source_group"] == matrix["missing_field_counts_by_source_group"]
    assert matrix["missing_required_field_counts_by_source_group"] == matrix["missing_field_counts_by_source_group"]
    assert matrix["field_source_coverage"]["order_size"] == 0.0
    assert matrix["source_coverage_rate_by_field"] == matrix["field_source_coverage"]
    assert matrix["source_field_coverage_rate_summary"] == matrix["field_source_coverage"]
    assert matrix["source_type_summary"] == matrix["source_group_summary"]
    assert matrix["sample_missing_rows"] == matrix["sample_missing_cost_evidence_rows"]
    assert any(detail["field"] == "order_size" for detail in matrix["source_coverage_blocker_details"])
    assert matrix["source_coverage_blocker_details"][0]["pass_condition"].startswith("required_cost_field_")
    assert matrix["source_coverage_blocker_details"][0]["required"] == ">=0.95"
    assert matrix["blocker_details"] == matrix["source_coverage_blocker_details"]
    assert matrix["failed_blocker_details"] == matrix["source_coverage_blocker_details"]
    assert matrix["actuals"]["all_required_source_fields_covered_gte_95pct"] == matrix["field_source_coverage"]
    assert matrix["required"]["all_required_source_fields_covered_gte_95pct"]["order_size"] == ">=0.95"
    assert matrix["sample_blockers"] == matrix["source_coverage_blocker_details"][:25]
    assert matrix["source_recovery_summary"] == matrix["source_group_recovery_classification"]
    assert "order_size" in matrix["hard_blocking_fields"]
    assert matrix["hard_blocking_cost_fields"] == matrix["hard_blocking_fields"]
    assert matrix["hard_blocker_fields"] == matrix["hard_blocking_fields"]
    assert status["hard_blocker_count"] == len(status["hard_blocker_fields"])
    assert status["hard_blocking_field_count"] == len(status["hard_blocking_fields"])
    assert matrix["hard_blocker_count"] == len(matrix["hard_blocker_fields"])
    assert matrix["hard_blocking_field_count"] == len(matrix["hard_blocking_fields"])
    assert matrix["hard_blocking_missing_fields"] == status["hard_blocking_missing_fields"]
    assert matrix["hard_blocking_missing_cost_fields"] == matrix["hard_blocking_missing_fields"]
    assert matrix["hard_blocker_missing_fields"] == matrix["hard_blocking_missing_fields"]
    assert matrix["hard_blocker_missing_field_counts"] == matrix["hard_blocking_missing_field_counts"]
    assert matrix["hard_blocking_missing_cost_field_counts"] == matrix["hard_blocking_missing_field_counts"]
    assert matrix["hard_blocker_missing_field_count"] == matrix["hard_blocking_missing_field_count"]
    assert matrix["hard_blocking_cost_field_count"] == matrix["hard_blocking_field_count"]
    assert matrix["hard_blocking_missing_cost_field_count"] == matrix["hard_blocking_missing_field_count"]
    assert matrix["hard_blocker_missing_row_total"] == matrix["hard_blocking_missing_row_total"]
    assert matrix["hard_blocking_missing_cost_row_total"] == matrix["hard_blocking_missing_row_total"]
    assert matrix["hard_blocking_missing_field_counts"] == status["hard_blocking_missing_field_counts"]
    assert matrix["hard_blocking_missing_field_count"] == status["hard_blocking_missing_field_count"]
    assert matrix["hard_blocking_missing_row_total"] == status["hard_blocking_missing_row_total"]
    assert matrix["hard_blocking_present_counts"] == status["hard_blocking_present_counts"]
    assert matrix["hard_blocking_cost_present_counts"] == matrix["hard_blocking_present_counts"]
    assert matrix["paper_fill_allowed"] is False
    assert matrix["routes_to_live"] is False
    assert matrix["counts_as_a_grade_evidence"] is False
    assert matrix["promotion_evidence"] is False
    assert matrix["fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence"] is False
    assert matrix["fallback_rows_shadow_only"] is True
    assert matrix["fallback_rows_are_shadow_only"] is True
    assert matrix["fallback_rows_count_as_production_grade_evidence"] is False
    assert matrix["fallback_rows_count_as_production_grade_training_evidence"] is False
    assert matrix["fallback_rows_count_as_lockbox_evidence"] is False
    assert matrix["fallback_rows_count_as_promotion_evidence"] is False
    assert matrix["production_evidence_rules"] == {
        "fallback_true_rows_may_be_shadow_scored": True,
        "fallback_true_rows_may_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
        "fallback_true_rows_may_count_as_production_grade_evidence": False,
        "fallback_true_rows_may_count_as_lockbox_evidence": False,
        "fallback_true_rows_may_count_as_promotion_evidence": False,
        "required_cost_fields_must_be_present_for_all_rows": True,
        "source_field_coverage_required": ">=0.95",
        "unexplained_cost_missing_rows_required": 0,
    }
    assert matrix["total_runtime_rows"] == 1
    assert matrix["unexplained_cost_missing_rows"] == status["unexplained_cost_missing_rows"]
    assert matrix["coverage_by_field_summary"] == matrix["field_source_coverage"]
    assert matrix["required_evidence_fields_present"] is False
    assert matrix["required_cost_fields_present_for_all_rows"] is False
    assert matrix["required_source_fields_covered_gte_95pct"] is False
    assert matrix["required_cost_fields_covered_gte_95pct"] is False
    assert "all_required_source_fields_covered_gte_95pct" in matrix["blocked_reasons"]


def _frozen_policy_test_payload() -> tuple[dict, SimpleNamespace]:
    feature_names = tuple(f"feature_{idx}" for idx in range(32))
    normalization = NormalizationSpec(
        feature_names=feature_names,
        means=tuple(float(idx) for idx in range(32)),
        stds=tuple(1.0 for _ in range(32)),
        mins=tuple(0.0 for _ in range(32)),
        maxs=tuple(10.0 for _ in range(32)),
    )
    weights = tuple(float(idx) / 100.0 for idx in range(32))
    payload = {
        "schema_version": "challenger_v2_frozen_policy_status_v1",
        "generated_utc": "2026-06-25T00:00:00Z",
        "goal_id": "V2_CHALLENGER_V2_REPRODUCIBLE_COST_PARITY_FEATURE_ADAPTER_BLIND_LOCKBOX_AND_FORWARD_CANARY",
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "freeze_status": "FROZEN_VALIDATION_SELECTED_PENDING_BLIND_LOCKBOX",
        "feature_schema_hash": feature_schema_hash(feature_names),
        "normalization_hash": normalization_hash(normalization),
        "cost_model_hash": cost_model_hash(),
        "dataset_manifest_hash": "dataset-hash",
        "weights_hash": stable_hash({"weights": list(weights)}),
        "threshold": 20.0,
        "target_clipping_bps": 100.0,
        "ridge_lambda": 1000.0,
        "paper_only": True,
        "routes_to_live": False,
        "promotion_allowed": False,
        "post_freeze_source_or_parameter_change_invalidates_candidate": True,
        "feature_names_in_order": list(feature_names),
        "normalization": normalization.to_jsonable(),
        "weights": list(weights),
        "bias": 0.25,
    }
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
        feature_names=feature_names,
        weights=weights,
    )
    return payload, policy


def test_frozen_candidate_integrity_audit_recomputes_freeze_hashes(tmp_path) -> None:
    payload, policy = _frozen_policy_test_payload()
    (tmp_path / "challenger_v2_frozen_policy_status.json").write_text(json.dumps(payload), encoding="utf-8")

    audit = frozen_candidate_integrity_audit(tmp_path, policy)

    assert audit["status"] == "PASS_FROZEN_CANDIDATE_INTEGRITY_AUDIT"
    assert audit["feature_count"] == 32
    assert audit["weight_count"] == 32
    assert audit["recorded_hashes"]["feature_schema_hash"] == audit["recomputed_hashes"]["feature_schema_hash"]
    assert audit["recorded_hashes"]["normalization_hash"] == audit["recomputed_hashes"]["normalization_hash"]
    assert audit["recorded_hashes"]["cost_model_hash"] == audit["recomputed_hashes"]["cost_model_hash"]
    assert audit["pass_conditions"]["previous_frozen_policy_hash_unchanged_or_baseline_initialized"] is True
    assert audit["frozen_candidate_modified_since_previous_evidence_run"] is False
    assert audit["new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes"] is True
    assert audit["paper_only"] is True
    assert audit["promotion_allowed"] is False
    assert audit["post_freeze_source_or_parameter_change_invalidates_candidate"] is True
    assert audit["frozen_policy_safety_contract"] == {
        "paper_only": True,
        "routes_to_live": False,
        "promotion_allowed": False,
        "post_freeze_source_or_parameter_change_invalidates_candidate": True,
        "new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes": True,
    }
    assert audit["paper_fill_allowed"] is False
    assert audit["routes_to_live"] is False
    assert audit["counts_as_a_grade_evidence"] is False


def test_frozen_candidate_integrity_audit_detects_previous_hash_mismatch(tmp_path) -> None:
    payload, policy = _frozen_policy_test_payload()
    (tmp_path / "challenger_v2_frozen_policy_status.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "challenger_v2_frozen_candidate_integrity_audit.json").write_text(
        json.dumps({"frozen_policy_file_sha256": "previous-hash"}),
        encoding="utf-8",
    )

    audit = frozen_candidate_integrity_audit(tmp_path, policy)

    assert audit["status"] == "FAIL_FROZEN_CANDIDATE_INTEGRITY_AUDIT"
    assert audit["pass_conditions"]["previous_frozen_policy_hash_unchanged_or_baseline_initialized"] is False
    assert audit["frozen_candidate_modified_since_previous_evidence_run"] is True
    assert audit["frozen_candidate_modified"] is False


def test_production_cost_capture_gap_audit_quarantines_old_policy_cost_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = production_cost_capture_gap_audit(
        policy=policy,
        cost_status={
            "status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_rows": 0,
            "production_grade_cost_coverage": 0.0,
            "required_coverage": 0.95,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
            "fallback_true_rows": 100,
            "pass_conditions": {
                "production_grade_cost_coverage_gte_95pct": False,
                "unexplained_cost_missing_rows_eq_0": True,
                "replay_paper_cost_parity_for_same_snapshot_order": True,
            },
            "blocker_diagnosis": {
                "hard_blocking_fields": ["order_size", "maker_taker_assumption_and_probability"],
            },
        },
        coverage_matrix={
            "coverage_by_source_group": {
                "combined": {
                    "order_size": {"present_rows": 0, "missing_rows": 100, "coverage": 0.0},
                }
            },
            "source_presence": {
                "combined": {
                    "fields": {
                        "order_size": {"present_rows": 0, "missing_rows": 100, "coverage": 0.0},
                        "maker_taker_assumption_and_probability": {
                            "present_rows": 0,
                            "missing_rows": 100,
                            "coverage": 0.0,
                        },
                    },
                },
            },
        },
        paper_intent_join_status={
            "paper_intent_rows_scanned": 10,
            "candidate_bound_intents": 0,
            "trusted_snapshot_matches": 0,
            "positive_order_size_matches": 0,
        },
        paper_cost_telemetry={
            "paper_telemetry_production_grade_rows": 5,
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 5,
        },
        top_book_enrichment_status={"top_book_enriched_rows": 8, "top_book_enrichment_coverage": 0.08},
    )

    assert payload["status"] == "BLOCKED_EXISTING_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    assert payload["total_rows"] == 100
    assert payload["total_cost_evidence_rows"] == 100
    assert payload["required_coverage"] == 0.95
    assert payload["field_coverage"]["order_size"]["missing_rows"] == 100
    assert payload["required_field_missing_counts"]["order_size"] == 100
    assert payload["missing_required_field_counts"] == payload["required_field_missing_counts"]
    assert payload["missing_cost_field_counts"] == payload["required_field_missing_counts"]
    assert payload["required_fields_present_counts"]["order_size"] == 0
    assert payload["source_group_summary"]["combined"]["order_size"]["missing_rows"] == 100
    assert payload["source_gap_summary"]["hard_blocking_missing_fields"] == [
        "order_size",
        "maker_taker_assumption_and_probability",
    ]
    assert payload["top_gap_patterns"] == payload["priority_field_shortfalls"][:25]
    assert payload["sample_gap_rows"][0]["field"] == "maker_taker_assumption_and_probability"
    assert payload["minimum_rows_required_for_95pct_coverage"] == 95
    assert payload["production_grade_cost_row_shortfall_to_95pct"] == 95
    assert payload["shortfall_to_95pct"] == 95
    assert payload["minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["required_new_candidate_bound_production_grade_rows"] == 95
    assert payload["phase_1_exit_minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["runtime_cost_capture_remediation_contract_path"] == (
        "challenger_v2_runtime_cost_capture_remediation_contract.json"
    )
    assert payload["runtime_cost_capture_operator_approval_packet_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_packet.json"
    )
    assert payload["runtime_cost_capture_operator_approval_receipt_template_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    )
    assert payload["runtime_cost_capture_operator_approval_receipt_status_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    )
    assert payload["approval_packet_path"] == "challenger_v2_runtime_cost_capture_operator_approval_packet.json"
    assert payload["receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    assert payload["receipt_status_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    assert payload["operator_approval_required"] is True
    assert payload["required_runtime_write_groups"] == sorted(payload["required_runtime_source_groups"])
    assert payload["source_group_gaps"] == payload["priority_source_groups"]
    assert "production_grade_cost_coverage_gte_95pct" in payload["blocked_reasons"]
    assert payload["phase_1_blocker_details"][0]["passed"] is False
    assert payload["blocker_details"] == payload["phase_1_blocker_details"]
    assert payload["failed_blocker_details"] == payload["phase_1_blocker_details"]
    assert payload["actuals"]["production_grade_cost_coverage_gte_95pct"] == 0.0
    assert payload["required"]["production_grade_cost_coverage_gte_95pct"] == ">=0.95"
    assert payload["sample_blockers"] == payload["phase_1_blocker_details"][:25]
    assert payload["phase_1_exit_criteria"]["minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["phase_1_exit_criteria"]["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["phase_1_exit_criteria"]["existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"] is True
    assert payload["phase_1_exit_criteria"]["fallback_true_rows_may_count_as_production_evidence"] is False
    assert payload["field_shortfalls"]["order_size"]["additional_rows_needed_for_95pct"] == 95
    limiting_fields = {field["field"]: field for field in payload["limiting_cost_fields_for_95pct"]}
    assert limiting_fields["order_size"]["additional_rows_needed_for_95pct"] == 95
    assert limiting_fields["maker_taker_assumption_and_probability"]["hard_blocking_field"] is True
    hard_blocking_fields = {field["field"] for field in payload["hard_blocking_field_shortfalls"]}
    assert {"order_size", "maker_taker_assumption_and_probability"}.issubset(hard_blocking_fields)
    assert payload["hard_blocking_missing_fields"] == ["order_size", "maker_taker_assumption_and_probability"]
    assert payload["hard_blocking_missing_field_counts"] == {
        "maker_taker_assumption_and_probability": 100,
        "order_size": 100,
    }
    assert payload["hard_blocking_missing_field_count"] == 2
    assert payload["hard_blocking_missing_row_total"] == 200
    assert payload["hard_blocking_present_counts"] == {
        "maker_taker_assumption_and_probability": 0,
        "order_size": 0,
    }
    assert payload["candidate_bound_production_grade_rows"] == 0
    assert payload["old_policy_or_unbound_production_grade_rows"] == 5
    assert payload["fallback_rows"] == 100
    assert payload["old_policy_or_unbound_production_grade_paper_rows"] == 5
    assert payload["old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["fallback_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False
    assert payload["can_recover_from_existing_authoritative_sources_without_new_capture"] is False
    assert payload["can_recover_from_existing_sources"] is False
    assert {
        field["field"]: field
        for field in payload["priority_field_shortfalls"]
    }["order_size"]["required_capture_source_groups"] == ["paper_intent", "paper_ledger", "paper_online_ledger"]
    assert {
        group["source_group"]: group
        for group in payload["priority_source_groups"]
    }["paper_intent"]["priority"] == "HIGH"
    assert payload["source_group_shortfalls"] == payload["priority_source_groups"]
    assert {
        group["source_group"]: group
        for group in payload["next_capture_batch_contract"]["priority_source_groups"]
    }["paper_ledger"]["existing_rows_may_not_be_backfilled_for_credit"] is True
    assert payload["next_capture_batch_contract"]["limiting_cost_fields_for_95pct"] == payload[
        "limiting_cost_fields_for_95pct"
    ]
    assert payload["next_capture_batch_contract"]["hard_blocking_field_shortfalls"] == payload[
        "hard_blocking_field_shortfalls"
    ]
    assert payload["next_capture_batch_contract"]["hard_blocking_missing_fields"] == payload[
        "hard_blocking_missing_fields"
    ]
    assert payload["next_capture_batch_contract"]["hard_blocking_missing_field_counts"] == payload[
        "hard_blocking_missing_field_counts"
    ]
    assert payload["next_capture_batch_contract"]["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["required_next_capture_contract"] == payload["next_capture_batch_contract"]
    assert payload["implementation_handoff"] == payload["operator_handoff"]
    assert payload["implementation_handoff"]["handoff_status"] == (
        "AWAITING_OPERATOR_APPROVAL_FOR_RUNTIME_COST_CAPTURE"
    )
    assert payload["implementation_handoff"]["approval_required_before_runtime_write_path_edits"] is True
    assert payload["implementation_handoff"]["minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["implementation_handoff"]["hard_blocking_missing_fields"] == [
        "order_size",
        "maker_taker_assumption_and_probability",
    ]
    assert "runtime_write_path_edits" in payload["implementation_handoff"]["prohibited_without_approval"]
    assert "read_only_audits" in payload["implementation_handoff"]["allowed_before_approval"]
    assert payload["implementation_handoff"]["paper_fill_allowed"] is False
    assert payload["implementation_handoff"]["routes_to_live"] is False
    assert payload["implementation_handoff"]["counts_as_a_grade_evidence"] is False
    assert payload["failed_phase_1_blocker_details"] == payload["phase_1_blocker_details"]
    assert payload["pass_conditions"]["old_policy_or_unbound_rows_not_counted"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_production_cost_capture_gap_audit_passes_when_existing_candidate_bound_sources_cover_95pct() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = production_cost_capture_gap_audit(
        policy=policy,
        cost_status={
            "status": "PASS",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_rows": 95,
            "production_grade_cost_coverage": 0.95,
            "required_coverage": 0.95,
            "required_field_missing_counts": {"order_size": 0},
            "required_fields_present_counts": {"order_size": 100},
            "field_coverage": {"order_size": {"present_rows": 100, "missing_rows": 0, "coverage": 1.0}},
            "source_group_summary": {
                "combined": {
                    "order_size": {"present_rows": 100, "missing_rows": 0, "coverage": 1.0},
                }
            },
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
            "pass_conditions": {
                "production_grade_cost_coverage_gte_95pct": True,
                "unexplained_cost_missing_rows_eq_0": True,
                "replay_paper_cost_parity_for_same_snapshot_order": True,
            },
            "blocker_diagnosis": {"hard_blocking_fields": []},
        },
        coverage_matrix={"source_presence": {"combined": {"fields": {}}}},
        paper_intent_join_status={
            "paper_intent_rows_scanned": 100,
            "candidate_bound_intents": 95,
            "trusted_snapshot_matches": 95,
            "positive_order_size_matches": 95,
        },
        paper_cost_telemetry={
            "paper_telemetry_production_grade_rows": 95,
            "challenger_bound_production_grade_rows": 95,
            "old_policy_or_unbound_production_grade_rows": 0,
        },
        top_book_enrichment_status={"top_book_enriched_rows": 95, "top_book_enrichment_coverage": 0.95},
    )

    assert payload["status"] == "PASS_PRODUCTION_COST_CAPTURE_READY"
    assert payload["total_rows"] == 100
    assert payload["required_coverage"] == 0.95
    assert payload["required_field_missing_counts"] == {"order_size": 0}
    assert payload["required_fields_present_counts"] == {"order_size": 100}
    assert payload["field_coverage"]["order_size"]["coverage"] == 1.0
    assert payload["source_group_summary"]["combined"]["order_size"]["coverage"] == 1.0
    assert payload["production_grade_cost_row_shortfall_to_95pct"] == 0
    assert payload["shortfall_to_95pct"] == 0
    assert payload["required_new_candidate_bound_production_grade_rows"] == 0
    assert payload["phase_1_exit_minimum_new_candidate_bound_production_grade_rows"] == 0
    assert payload["runtime_cost_capture_remediation_contract_path"] == (
        "challenger_v2_runtime_cost_capture_remediation_contract.json"
    )
    assert payload["blocked_reasons"] == []
    assert payload["phase_1_blocker_details"] == []
    assert payload["failed_phase_1_blocker_details"] == []
    assert payload["can_recover_from_existing_authoritative_sources_without_new_capture"] is True
    assert payload["can_recover_from_existing_sources"] is True
    assert payload["next_capture_batch_contract"]["minimum_new_candidate_bound_production_grade_rows"] == 0
    assert payload["implementation_handoff"]["handoff_status"] == "READY_NO_RUNTIME_PATCH_REQUIRED"
    assert payload["implementation_handoff"]["minimum_new_candidate_bound_production_grade_rows"] == 0
    assert all(payload["pass_conditions"].values())


def test_runtime_cost_capture_contract_blocks_unbound_old_policy_cost_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = runtime_cost_capture_contract_audit(
        policy=policy,
        cost_status={
            "status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_coverage": 0.0,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
            "required_cost_fields_present_for_all_rows": False,
            "required_cost_fields_covered_gte_95pct": False,
            "required_evidence_fields_present": False,
            "required_evidence_fields_covered_gte_95pct": False,
            "missing_required_field_counts": {
                "maker_taker_assumption_and_probability": 100,
                "order_size": 100,
            },
            "field_coverage": {
                "maker_taker_assumption_and_probability": {"coverage": 0.0, "missing_rows": 100},
                "order_size": {"coverage": 0.0, "missing_rows": 100},
            },
        },
        cost_capture_gap={
            "status": "BLOCKED_EXISTING_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_rows": 0,
            "production_grade_cost_coverage": 0.0,
            "minimum_rows_required_for_95pct_coverage": 95,
            "production_grade_cost_row_shortfall_to_95pct": 95,
            "hard_blocking_fields": ["order_size", "maker_taker_assumption_and_probability"],
            "hard_blocking_missing_fields": ["order_size", "maker_taker_assumption_and_probability"],
            "hard_blocking_missing_field_counts": {
                "maker_taker_assumption_and_probability": 100,
                "order_size": 100,
            },
            "hard_blocking_present_counts": {
                "maker_taker_assumption_and_probability": 0,
                "order_size": 0,
            },
            "top_book_enriched_rows": 8,
            "candidate_bound_intents": 0,
            "trusted_candidate_bound_intent_matches": 0,
            "positive_order_size_matches": 0,
            "paper_telemetry_production_grade_rows": 5,
            "challenger_bound_production_grade_paper_rows": 0,
            "old_policy_or_unbound_production_grade_paper_rows": 5,
            "old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
        },
        paper_intent_join_status={"candidate_bound_intents": 0, "trusted_snapshot_matches": 0, "positive_order_size_matches": 0},
        paper_cost_telemetry={"live_route_rows": 0, "paper_fill_allowed_rows": 0},
        top_book_enrichment_status={"top_book_enriched_rows": 8},
        paper_binding_preflight={"live_route_violation_rows": 0},
    )

    assert payload["status"] == "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    assert payload["runtime_cost_capture_contract_status"] == payload["status"]
    assert payload["production_cost_status"] == "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"
    assert payload["production_cost_evidence_status"] == "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"
    assert payload["required_rows"] == 95
    assert payload["required_production_grade_cost_rows"] == 95
    assert payload["minimum_production_grade_cost_rows_required"] == 95
    assert payload["required_cost_fields_present_for_all_rows"] is False
    assert payload["required_cost_fields_covered_gte_95pct"] is False
    assert payload["required_evidence_fields_present"] is False
    assert payload["required_evidence_fields_covered_gte_95pct"] is False
    assert payload["operator_approval_required"] is True
    assert payload["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["operator_action_required"] is True
    assert payload["required_runtime_source_groups"] == sorted(payload["required_write_groups"])
    assert set(payload["required_source_groups"]) == {
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    }
    assert payload["required_cost_fields"] == payload["required_cost_evidence_fields"]
    assert payload["required_production_cost_fields"] == payload["required_cost_evidence_fields"]
    assert [phase["phase"] for phase in payload["implementation_phases"]] == [
        "operator_approval_boundary",
        "decision_time_and_pre_submit_capture",
        "lifecycle_outcome_and_feedback_linkage",
        "post_capture_verification",
    ]
    assert payload["operator_approval_boundary"] == payload["implementation_phases"][0]
    assert payload["operator_approval_boundary"]["required_source_groups"] == payload["required_runtime_source_groups"]
    assert payload["acceptance_criteria"]["operator_approval_required_before_runtime_write_path_edits"] is True
    assert "production_grade_cost_evidence_passed" in payload["blocked_reasons"]
    assert "challenger_bound_production_grade_paper_rows_gte_required_rows" in payload["blocked_reasons"]
    assert payload["blocker_details"]["production_grade_cost_evidence_passed"] == {
        "passed": False,
        "observed": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
        "required": "PASS",
    }
    assert payload["blocker_details"]["hard_blocking_fields_resolved"]["observed"] == [
        "order_size",
        "maker_taker_assumption_and_probability",
    ]
    assert payload["hard_blocking_missing_fields"] == ["order_size", "maker_taker_assumption_and_probability"]
    assert payload["hard_blocking_missing_cost_fields"] == ["order_size", "maker_taker_assumption_and_probability"]
    assert payload["hard_blocking_cost_fields"] == ["order_size", "maker_taker_assumption_and_probability"]
    assert payload["hard_blocking_missing_field_counts"] == {
        "maker_taker_assumption_and_probability": 100,
        "order_size": 100,
    }
    assert payload["hard_blocking_missing_cost_field_counts"] == {
        "maker_taker_assumption_and_probability": 100,
        "order_size": 100,
    }
    assert payload["hard_blocking_missing_field_count"] == 2
    assert payload["hard_blocking_missing_cost_field_count"] == 2
    assert payload["hard_blocking_missing_row_total"] == 200
    assert payload["missing_required_field_counts"] == {
        "maker_taker_assumption_and_probability": 100,
        "order_size": 100,
    }
    assert payload["missing_cost_field_counts"] == {
        "maker_taker_assumption_and_probability": 100,
        "order_size": 100,
    }
    assert payload["field_coverage"]["order_size"]["coverage"] == 0.0
    assert payload["cost_capture_contract_evidence_summary"] == {
        "production_cost_status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
        "total_cost_evidence_rows": 100,
        "minimum_rows_required_for_95pct_coverage": 95,
        "production_grade_cost_rows": 0,
        "production_grade_cost_coverage": 0.0,
        "production_grade_cost_row_shortfall_to_95pct": 95,
        "unexplained_cost_missing_rows": 0,
        "replay_paper_cost_parity_mismatch_rows": 0,
        "required_cost_fields_present_for_all_rows": False,
        "required_cost_fields_covered_gte_95pct": False,
        "missing_required_field_counts": {
            "maker_taker_assumption_and_probability": 100,
            "order_size": 100,
        },
        "hard_blocking_missing_cost_fields": ["order_size", "maker_taker_assumption_and_probability"],
        "hard_blocking_missing_cost_field_counts": {
            "maker_taker_assumption_and_probability": 100,
            "order_size": 100,
        },
        "top_book_enriched_rows": 8,
        "candidate_bound_intents": 0,
        "trusted_candidate_bound_intent_matches": 0,
        "positive_order_size_matches": 0,
        "challenger_bound_production_grade_paper_rows": 0,
        "old_policy_or_unbound_production_grade_paper_rows": 5,
    }
    assert payload["hard_blocking_present_counts"] == {
        "maker_taker_assumption_and_probability": 0,
        "order_size": 0,
    }
    assert payload["blocker_details"]["challenger_bound_production_grade_paper_rows_gte_required_rows"] == {
        "passed": False,
        "observed": 0,
        "required": ">=95",
        "shortfall": 95,
    }
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["phase_1_blocker_details"] == payload["blocker_details"]
    assert payload["failed_phase_1_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["production_grade_cost_evidence_passed"] == "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"
    assert payload["required"]["production_grade_cost_evidence_passed"] == "PASS"
    assert payload["actuals"]["challenger_bound_production_grade_paper_rows_gte_required_rows"] == 0
    assert payload["required"]["challenger_bound_production_grade_paper_rows_gte_required_rows"] == ">=95"
    assert payload["sample_blockers"][0]["pass_condition"] == "production_grade_cost_evidence_passed"
    assert payload["sample_blockers"][0]["observed"] == "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"
    assert payload["condition_details"]["candidate_bound_paper_fill_allowed_rows_eq_0"]["passed"] is True
    assert payload["condition_details"]["paper_telemetry_fill_allowed_rows_quarantined_when_not_candidate_bound"][
        "passed"
    ] is True
    assert payload["hard_blocking_field_recovery_boundaries"]["order_size"] == "adaptive_allocator_or_paper_intent_pre_submit"
    assert payload["current_capture_counts"]["old_policy_or_unbound_production_grade_paper_rows"] == 5
    assert payload["old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["fallback_true_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_runtime_cost_capture_remediation_contract_ranks_future_identity_binding_gap() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = runtime_cost_capture_remediation_contract(
        policy=policy,
        cost_capture_gap={
            "total_cost_evidence_rows": 100,
            "minimum_rows_required_for_95pct_coverage": 95,
            "challenger_bound_production_grade_paper_rows": 0,
            "old_policy_or_unbound_production_grade_paper_rows": 5,
        },
        paper_cost_telemetry={
            "status": "BLOCKED_CHALLENGER_IDENTITY_MISSING_FOR_COST_TELEMETRY",
            "paper_rows_scanned": 7,
            "source_group_readiness": {
                "trainer_feedback": {
                    "rows": 4,
                    "production_grade_rows": 4,
                    "candidate_identity_complete_production_grade_rows": 0,
                    "challenger_bound_production_grade_rows": 0,
                    "old_policy_or_unbound_production_grade_rows": 4,
                    "candidate_identity_complete_rows": 0,
                    "candidate_identity_partial_rows": 0,
                    "candidate_identity_none_rows": 4,
                    "all_required_source_fields_present_rows": 4,
                    "missing_required_source_fields_rows": 0,
                    "paper_fill_allowed_rows": 1,
                    "live_route_rows": 0,
                    "missing_required_cost_source_field_counts": {},
                },
                "paper_signal": {
                    "rows": 3,
                    "production_grade_rows": 0,
                    "candidate_identity_complete_production_grade_rows": 0,
                    "challenger_bound_production_grade_rows": 0,
                    "old_policy_or_unbound_production_grade_rows": 0,
                    "candidate_identity_complete_rows": 3,
                    "candidate_identity_partial_rows": 0,
                    "candidate_identity_none_rows": 0,
                    "all_required_source_fields_present_rows": 0,
                    "missing_required_source_fields_rows": 3,
                    "paper_fill_allowed_rows": 0,
                    "live_route_rows": 0,
                    "missing_required_cost_source_field_counts": {"order_size": 3},
                },
            },
        },
        cost_identity_join_recovery={
            "status": "BLOCKED_COST_IDENTITY_JOIN_OVERLAP_DIAGNOSTIC_ONLY",
            "exact_join_key_overlap_count": 2,
            "overlapping_paper_rows": 2,
            "overlapping_paper_rows_with_production_grade_cost": 1,
            "overlapping_paper_rows_with_complete_challenger_identity": 0,
            "recoverable_candidate_bound_production_grade_rows": 0,
            "diagnostic_only_external_identity_overlap_rows": 2,
        },
        runtime_cost_capture_contract={"status": "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"},
    )

    assert payload["status"] == "BLOCKED_REQUIRES_FUTURE_CANDIDATE_BOUND_PRODUCTION_GRADE_CAPTURE"
    assert payload["blocked_reasons"] == [
        "runtime_cost_capture_contract_ready",
        "current_challenger_bound_production_grade_rows_gte_required",
        "old_policy_or_unbound_production_grade_rows_present",
        "diagnostic_only_external_identity_overlap_rows_present",
    ]
    assert payload["remediation_blocker_details"][1]["actual"] == {"current": 0, "required": 95, "shortfall": 95}
    assert payload["blocker_details"] == payload["remediation_blocker_details"]
    assert payload["failed_blocker_details"] == payload["remediation_blocker_details"]
    assert payload["actuals"]["runtime_cost_capture_contract_ready"] == (
        "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    )
    assert payload["required"]["runtime_cost_capture_contract_ready"] == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"
    assert payload["actuals"]["current_challenger_bound_production_grade_rows_gte_required"] == {
        "current": 0,
        "required": 95,
        "shortfall": 95,
    }
    assert payload["required"]["current_challenger_bound_production_grade_rows_gte_required"] == ">=95"
    assert payload["sample_blockers"] == payload["remediation_blocker_details"][:25]
    assert payload["runtime_cost_capture_status"] == "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    assert payload["required_new_candidate_bound_production_grade_rows"] == 95
    assert payload["required_new_candidate_bound_rows"] == 95
    assert payload["old_policy_or_unbound_production_grade_rows"] == 5
    assert payload["diagnostic_only_external_identity_overlap_rows"] == 2
    assert payload["required_runtime_source_groups"] == sorted(payload["required_source_groups"])
    assert payload["approval_required_source_groups"] == payload["required_source_groups"]
    assert payload["operator_approval_required_source_groups"] == payload["required_source_groups"]
    assert payload["source_groups"] == payload["required_source_groups"]
    assert payload["source_group_count"] == len(payload["required_source_groups"])
    assert set(payload["required_source_groups"]) == {
        "paper_signal",
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "paper_closed_trades",
        "trainer_feedback",
    }
    assert payload["required_cost_fields"] == payload["acceptance_criteria"]["cost_evidence_fields_required"]
    assert payload["required_production_cost_fields"] == payload["required_cost_fields"]
    assert payload["priority_source_groups"][0]["source_group"] == "trainer_feedback"
    assert payload["top_source_group"] == "trainer_feedback"
    assert payload["top_decision_time_capture_source_group"] == "paper_signal"
    assert payload["top_outcome_linkage_source_group"] == "trainer_feedback"
    assert payload["source_group_decisions"][0]["source_group"] == "trainer_feedback"
    assert payload["source_group_decisions"][0]["counts_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["priority_source_groups"][0]["capture_stage"] == "trainer_feedback_outcome"
    assert payload["priority_source_groups"][0]["runtime_write_point"]["redis_keys"] == [
        "v2:trainer:feedback:outcomes",
        "v2:trainer:feedback:outcomes:quarantine",
    ]
    assert payload["priority_source_groups"][0]["can_anchor_decision_time_selection"] is False
    assert payload["priority_source_groups"][0]["remediation_class"] == "future_identity_binding_required_existing_rows_not_counted"
    assert payload["priority_source_groups"][0]["old_policy_or_unbound_production_grade_rows"] == 4
    assert "do_not_backfill_identity_into_existing_old_or_unbound_rows" in payload["priority_source_groups"][0]["required_actions"]
    assert "link_to_immutable_decision_or_pre_submit_record_before_outcome_credit" in payload["priority_source_groups"][0]["required_actions"]
    assert payload["decision_time_capture_priority_source_groups"][0]["source_group"] == "paper_signal"
    assert payload["outcome_linkage_priority_source_groups"][0]["source_group"] == "trainer_feedback"
    assert payload["priority_source_groups"][1]["ranked_missing_required_cost_fields"][0]["field"] == "order_size"
    assert [phase["phase"] for phase in payload["implementation_phases"]] == [
        "operator_approval_boundary",
        "decision_time_and_pre_submit_capture",
        "lifecycle_outcome_and_feedback_linkage",
        "post_capture_verification",
    ]
    assert payload["implementation_phases"][0]["status"] == "AWAITING_OPERATOR_APPROVAL"
    assert payload["implementation_phases"][0]["required_receipt_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    )
    assert payload["implementation_phases"][0]["approved_patch_scope"] == (
        "telemetry_only_future_runtime_cost_and_identity_capture"
    )
    assert "order_submission" in payload["implementation_phases"][0]["prohibited_patch_scope"]
    assert payload["implementation_phases"][1]["priority_source_groups"] == ["paper_signal"]
    assert payload["implementation_phases"][1]["required_identity_fields"] == [
        "candidate_id",
        "policy_fingerprint",
        "model_source",
    ]
    assert "observed_bid_ask_spread" in payload["implementation_phases"][1]["required_cost_fields"]
    assert payload["implementation_phases"][2]["priority_source_groups"] == ["trainer_feedback"]
    assert payload["implementation_phases"][2]["acceptance_criteria"][1] == (
        "old-policy or unbound rows remain quarantined and non-counting"
    )
    assert payload["implementation_phases"][3]["minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["implementation_steps"] == payload["implementation_phases"]
    assert payload["implementation_plan"] == payload["implementation_phases"]
    assert payload["required_operator_approval"] is True
    assert payload["operator_approval_required"] is True
    assert payload["approval_packet_path"] == "challenger_v2_runtime_cost_capture_operator_approval_packet.json"
    assert payload["approval_receipt_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    assert payload["approval_receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    assert payload["approval_receipt_status_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    assert payload["approved_patch_scope"] == "telemetry_only_future_runtime_cost_and_identity_capture"
    assert "paper_binding_before_blind_lockbox_pass" in payload["prohibited_patch_scope"]
    assert payload["acceptance_criteria"]["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["acceptance_criteria"]["existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"] is True
    assert payload["acceptance_criteria"]["paper_fill_allowed"] is False
    assert payload["operator_approval_boundary"] == payload["implementation_phases"][0]
    assert payload["cost_identity_join_summary"]["recoverable_candidate_bound_production_grade_rows"] == 0
    assert payload["next_capture_batch_contract"]["existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"] is True
    assert payload["next_capture_batch_contract"]["fallback_true_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["next_capture_batch_contract"]["runtime_write_path_edits_require_operator_approval"] is True
    assert payload["status_blockers"]["current_challenger_bound_production_grade_rows_gte_required"] is False
    assert payload["operator_action_required"] is True
    assert payload["future_capture_credit_rules"]["existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"] is True
    assert payload["future_capture_credit_rules"]["fallback_true_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["next_capture_batch_contract"]["runtime_capture_write_points"]["paper_intent"]["files"] == [
        "v2/backend/app/cli/v2_trade_management_paper_loop.py"
    ]
    assert "paper_intent" in payload["next_capture_batch_contract"]["field_capture_requirements"]["order_size"]
    assert all(payload["pass_conditions"].values())
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_runtime_cost_capture_write_path_audit_blocks_missing_exact_identity(tmp_path) -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    source_payload = """
model_source = "old_policy_model"
selector_policy_fingerprint = "diagnostic_only"
best_bid = best_ask = spread_bps = top_book_bid_depth_usd = top_book_ask_depth_usd = 1
order_size_usd = depth_price_impact_bps = maker_probability = taker_probability = 1
maker_taker_probability = fee_bps = expected_funding_bps = latency_reserve_bps = 1
partial_fill_probability = mark_index_divergence_bps = source_timestamp = 1
available_at = decision_time = fallback = True
redis_keys = ["v2:paper:intents", "v2:paper:ledger", "v2:paper:closed_trades"]
"""
    files = {
        "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py": source_payload
        + '\nsignal_key = "v2:signals:paper:*"\n',
        "v2/backend/app/cli/paper_online_runtime.py": source_payload + '\nsignal_key = f"v2:signals:paper:{symbol_key}:1m"\n',
        "v2/backend/app/cli/v2_trade_management_paper_loop.py": source_payload,
        "v2/backend/app/services/paper_shadow_outcome_observer/service.py": source_payload
        + '\ntrainer_key = "v2:trainer:feedback:outcomes"\n',
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    payload = runtime_cost_capture_write_path_audit(
        repo_root=tmp_path,
        policy=policy,
        runtime_cost_capture_remediation={"status": "BLOCKED_REQUIRES_FUTURE_CANDIDATE_BOUND_PRODUCTION_GRADE_CAPTURE"},
    )

    assert payload["status"] == "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_IDENTITY_BINDING_MISSING"
    assert payload["unreadable_source_files"] == []
    assert set(payload["missing_required_identity_fields"]) == {"candidate_id", "policy_fingerprint"}
    assert payload["missing_identity_fields"] == payload["missing_required_identity_fields"]
    assert "paper_intent" in payload["missing_identity_fields_by_group"]
    assert payload["missing_required_cost_fields"] == []
    assert payload["missing_cost_fields"] == []
    assert payload["source_files_to_patch"] == payload["source_files_scanned"]
    assert payload["write_path_files"] == payload["source_files_scanned"]
    assert payload["source_file_count"] == len(payload["source_files_scanned"])
    assert set(payload["required_source_groups"]) >= {
        "paper_intent",
        "paper_ledger",
        "paper_online_ledger",
        "trainer_feedback",
    }
    assert payload["required_write_groups"] == payload["required_source_groups"]
    assert payload["required_runtime_write_groups"] == payload["required_source_groups"]
    assert payload["source_groups"] == payload["required_source_groups"]
    assert payload["source_group_count"] == len(payload["required_source_groups"])
    assert payload["writable_paths"]
    assert payload["telemetry_only_runtime_paths"][0]["approved_change_class"] == "telemetry_only_identity_and_cost_persistence"
    assert "order_submission" in payload["prohibited_patch_scope"]
    assert payload["operator_approval_boundary"]["existing_rows_may_not_be_backfilled_for_credit"] is True
    assert "required_identity_fields_exactly_present_in_required_write_groups" in payload["blocked_reasons"]
    assert payload["source_group_readiness"]["paper_intent"]["status"] == "BLOCKED_IDENTITY_BINDING_MISSING"
    assert payload["source_group_readiness"]["paper_intent"]["requires_operator_approval"] is True
    assert payload["source_group_readiness"]["paper_intent"]["identity_field_coverage"] == 1 / 3
    assert payload["source_group_readiness"]["paper_intent"]["cost_field_coverage"] == 1.0
    assert payload["source_group_readiness"]["paper_intent"]["combined_required_field_coverage"] < 1.0
    matrix = payload["source_group_field_coverage_matrix"]
    assert payload["field_coverage_by_group"] == matrix
    assert matrix["paper_intent"]["identity"]["present_fields"] == ["model_source"]
    assert matrix["paper_intent"]["identity"]["missing_fields"] == ["candidate_id", "policy_fingerprint"]
    assert matrix["paper_intent"]["identity"]["coverage"] == 1 / 3
    assert matrix["paper_intent"]["cost"]["coverage"] == 1.0
    assert matrix["paper_intent"]["field_evidence_summary"]["candidate_id"]["present"] is False
    assert matrix["paper_intent"]["field_evidence_summary"]["candidate_id"]["occurrence_count"] == 0
    assert matrix["paper_intent"]["field_evidence_summary"]["policy_fingerprint"]["present"] is False
    assert matrix["paper_intent"]["field_evidence_summary"]["model_source"]["present"] is True
    assert matrix["paper_intent"]["field_evidence_summary"]["model_source"]["occurrence_count"] > 0
    assert payload["required_identity_field_coverage_by_group"]["paper_intent"] == matrix["paper_intent"]["identity"]
    assert payload["required_cost_field_coverage_by_group"]["paper_intent"] == matrix["paper_intent"]["cost"]
    assert payload["write_path_findings"]
    assert payload["sample_write_path_findings"] == payload["write_path_findings"][:10]
    assert any(plan["source_group"] == "paper_intent" for plan in payload["remediation_plan"])
    assert payload["blocked_reason_details"]["required_identity_fields_exactly_present_in_required_write_groups"]["passed"] is False
    assert payload["blocked_reason_details"]["runtime_write_path_edits_require_operator_approval"]["passed"] is True
    assert payload["blocker_details"] == {
        "required_identity_fields_exactly_present_in_required_write_groups": payload["blocked_reason_details"][
            "required_identity_fields_exactly_present_in_required_write_groups"
        ]
    }
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["sample_blockers"][0]["pass_condition"] == (
        "required_identity_fields_exactly_present_in_required_write_groups"
    )
    assert payload["actuals"]["required_identity_fields_exactly_present_in_required_write_groups"] == payload[
        "missing_identity_fields_by_group"
    ]
    assert payload["required"]["required_identity_fields_exactly_present_in_required_write_groups"] == {}
    assert payload["actuals"]["required_cost_fields_present_in_required_write_groups"] == {}
    assert payload["required"]["required_cost_fields_present_in_required_write_groups"] == {}
    assert payload["actuals"]["paper_fill_allowed_false"] == {"paper_fill_allowed": False}
    assert payload["actuals"]["routes_to_live_false"] == {"routes_to_live": False}
    assert payload["actuals"]["frozen_candidate_modified_false"] == {"frozen_candidate_modified": False}
    assert payload["exact_identity_occurrences"]["policy_fingerprint"] == []
    assert payload["alternate_identity_occurrences"]["selector_policy_fingerprint"]
    assert payload["runtime_write_path_edits_require_operator_approval"] is True
    assert payload["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["operator_approval_required_before_applying_plan"] is True
    assert payload["approval_receipt_status_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_runtime_cost_capture_operator_approval_packet_scopes_identity_binding() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    payload = runtime_cost_capture_operator_approval_packet(
        policy=policy,
        runtime_cost_capture_remediation={
            "status": "BLOCKED_REQUIRES_FUTURE_CANDIDATE_BOUND_PRODUCTION_GRADE_CAPTURE",
            "required_new_candidate_bound_production_grade_rows": 95,
        },
        runtime_cost_capture_write_path={
            "status": "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_IDENTITY_BINDING_MISSING",
            "missing_identity_fields_by_group": {
                "paper_signal": ["candidate_id", "policy_fingerprint"],
                "paper_intent": ["candidate_id", "policy_fingerprint"],
            },
            "missing_cost_fields_by_group": {},
            "source_group_field_coverage_matrix": {
                "paper_signal": {
                    "identity": {
                        "coverage": 1 / 3,
                        "present_fields": ["model_source"],
                        "missing_fields": ["candidate_id", "policy_fingerprint"],
                    },
                    "cost": {"coverage": 1.0, "present_fields": ["top_book_evidence"], "missing_fields": []},
                    "combined": {"coverage": 0.75, "missing_fields": ["candidate_id", "policy_fingerprint"]},
                    "field_evidence_summary": {
                        "candidate_id": {"present": False, "occurrence_count": 0},
                        "policy_fingerprint": {"present": False, "occurrence_count": 0},
                        "model_source": {"present": True, "occurrence_count": 1},
                    },
                },
                "paper_intent": {
                    "identity": {
                        "coverage": 1 / 3,
                        "present_fields": ["model_source"],
                        "missing_fields": ["candidate_id", "policy_fingerprint"],
                    },
                    "cost": {"coverage": 1.0, "present_fields": ["order_size"], "missing_fields": []},
                    "combined": {"coverage": 0.8, "missing_fields": ["candidate_id", "policy_fingerprint"]},
                    "field_evidence_summary": {
                        "candidate_id": {"present": False, "occurrence_count": 0},
                        "policy_fingerprint": {"present": False, "occurrence_count": 0},
                        "model_source": {"present": True, "occurrence_count": 1},
                    },
                },
            },
        },
    )

    assert payload["status"] == "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
    assert payload["approval_required"] is True
    assert payload["operator_approval_required"] is True
    assert payload["operator_action_required"] is True
    assert payload["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["operator_approval_required_before_applying_plan"] is True
    assert payload["operator_approval_status"] == "AWAITING_OPERATOR_APPROVAL_RECEIPT"
    assert payload["write_path_status"] == "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_IDENTITY_BINDING_MISSING"
    assert payload["blocked_reasons"] == ["operator_approval_required"]
    assert payload["blocker_details"][0]["pass_condition"] == "operator_approval_required"
    assert payload["blocker_details"][0]["source_artifact"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    )
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["approval_required_source_groups"] == ["paper_signal", "paper_intent"]
    assert payload["operator_approval_required_source_groups"] == payload["approval_required_source_groups"]
    assert payload["required_source_groups"] == payload["approval_required_source_groups"]
    assert set(payload["required_runtime_write_groups"]) >= {"paper_signal", "paper_intent", "trainer_feedback"}
    assert payload["approved_source_groups"] == payload["approval_required_source_groups"]
    assert payload["source_groups"] == payload["approval_required_source_groups"]
    assert payload["source_group_count"] == len(payload["approval_required_source_groups"])
    assert payload["approved_source_group_count"] == len(payload["approval_required_source_groups"])
    assert payload["missing_identity_fields_by_group"] == {
        "paper_signal": ["candidate_id", "policy_fingerprint"],
        "paper_intent": ["candidate_id", "policy_fingerprint"],
    }
    assert payload["missing_required_identity_fields_by_group"] == payload["missing_identity_fields_by_group"]
    assert payload["missing_identity_fields"] == ["candidate_id", "policy_fingerprint"]
    assert payload["missing_required_identity_fields"] == payload["missing_identity_fields"]
    assert payload["missing_cost_fields_by_group"] == {}
    assert payload["missing_required_cost_fields_by_group"] == {}
    assert payload["missing_cost_fields"] == []
    assert payload["missing_required_cost_fields"] == []
    assert payload["missing_required_fields_by_group"] == payload["missing_identity_fields_by_group"]
    assert payload["source_group_readiness"]["paper_signal"]["status"] == (
        "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
    )
    assert payload["source_group_readiness"]["paper_signal"]["requires_operator_approval"] is True
    assert payload["source_group_readiness"]["paper_signal"]["missing_required_fields"] == [
        "candidate_id",
        "policy_fingerprint",
    ]
    assert payload["source_group_readiness"]["paper_signal"]["identity_field_coverage"] == 1 / 3
    assert payload["source_group_readiness"]["paper_signal"]["cost_field_coverage"] == 1.0
    assert payload["source_group_readiness"]["paper_signal"]["combined_required_field_coverage"] == 0.75
    assert payload["source_group_readiness"]["paper_signal"]["paper_fill_allowed"] is False
    assert payload["source_group_readiness"]["paper_signal"]["routes_to_live"] is False
    assert payload["source_group_readiness"]["paper_signal"]["places_real_order"] is False
    assert payload["source_group_readiness"]["trainer_feedback"]["status"] == "READY_NO_OPERATOR_APPROVAL_REQUIRED"
    assert payload["source_group_readiness"]["trainer_feedback"]["requires_operator_approval"] is False
    assert payload["approval_readiness_summary"] == payload["operator_approval_readiness_summary"]
    assert payload["approval_readiness_summary"]["approval_required_source_groups"] == payload[
        "approval_required_source_groups"
    ]
    assert payload["approval_readiness_summary"]["approval_required_source_group_count"] == 2
    assert payload["approval_readiness_summary"]["missing_identity_source_group_count"] == 2
    assert payload["approval_readiness_summary"]["missing_cost_source_group_count"] == 0
    assert payload["approval_readiness_summary"]["missing_required_identity_fields"] == [
        "candidate_id",
        "policy_fingerprint",
    ]
    assert payload["approval_readiness_summary"]["missing_required_cost_fields"] == []
    assert payload["approval_readiness_summary"]["missing_required_fields_by_group"] == payload[
        "missing_required_fields_by_group"
    ]
    assert payload["approval_readiness_summary"]["minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["approval_readiness_summary"]["operator_approval_receipt_required_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    )
    assert payload["approval_readiness_summary"]["paper_fill_allowed"] is False
    assert payload["approval_readiness_summary"]["routes_to_live"] is False
    assert payload["source_files_to_patch"] == [
        "v2/backend/app/cli/paper_online_runtime.py",
        "v2/backend/app/cli/v2_trade_management_paper_loop.py",
        "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
        "v2/backend/app/services/paper_shadow_outcome_observer/service.py",
    ]
    assert payload["write_path_files"] == payload["source_files_to_patch"]
    assert payload["source_file_count"] == len(payload["source_files_to_patch"])
    assert payload["approval_packet_path"] == "challenger_v2_runtime_cost_capture_operator_approval_packet.json"
    assert payload["approved_patch_scope"] == "telemetry_only_future_runtime_cost_and_identity_capture"
    assert payload["approval_patch_scope"] == payload["approved_patch_scope"]
    assert payload["approval_subject_hash"] is None
    assert payload["approval_subject_hash_status"] == "PENDING_RUNTIME_IDENTITY_BINDING_PLAN"
    assert payload["operator_approval_subject_hash_status"] == payload["approval_subject_hash_status"]
    assert payload["approval_receipt_required_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    assert payload["approval_receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    assert payload["approval_receipt_status_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    assert payload["operator_approval_receipt_path"] == payload["approval_receipt_required_path"]
    assert payload["operator_approval_receipt_template_path"] == payload["approval_receipt_template_path"]
    assert payload["runtime_cost_capture_operator_approval_receipt_path"] == payload["approval_receipt_required_path"]
    assert payload["runtime_cost_capture_operator_approval_receipt_template_path"] == payload["approval_receipt_template_path"]
    assert payload["runtime_cost_capture_operator_approval_receipt_status_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    )
    assert payload["receipt_path"] == payload["approval_receipt_required_path"]
    assert payload["receipt_required_path"] == payload["approval_receipt_required_path"]
    assert payload["receipt_template_path"] == payload["approval_receipt_template_path"]
    assert payload["missing_or_invalid_receipt_fields"] is None
    assert payload["approval_receipt_present"] is False
    assert payload["operator_approved_runtime_cost_capture"] is False
    assert payload["operator_approved_identity_binding"] is False
    assert payload["required_acknowledgements"] == [
        "acknowledges_no_historical_backfill_for_credit",
        "acknowledges_no_frozen_candidate_or_model_changes",
        "acknowledges_paper_fill_and_live_routes_remain_false",
    ]
    assert payload["required_operator_acknowledgements"] == payload["required_acknowledgements"]
    assert payload["acknowledgements"] == payload["required_acknowledgements"]
    assert len(payload["telemetry_only_runtime_paths"]) == 6
    assert any(path["source_group"] == "paper_online_ledger" for path in payload["telemetry_only_runtime_paths"])
    assert "order_submission" in payload["prohibited_patch_scope"]
    assert "frozen_candidate_artifact_change" in payload["prohibited_patch_scope"]
    assert "strategy_threshold_or_weight_change" in payload["prohibited_patch_scope"]
    assert payload["receipt_acceptance_rule"]["approved_patch_scope"] == payload["approved_patch_scope"]
    assert payload["receipt_acceptance_rule"]["required_operator_acknowledgements"] == payload["required_acknowledgements"]
    assert payload["minimum_new_candidate_bound_production_grade_rows"] == 95
    assert payload["approval_scope"][0]["source_group"] == "paper_signal"
    assert payload["approval_scope"][0]["missing_identity_fields"] == ["candidate_id", "policy_fingerprint"]
    assert payload["approval_scope"][0]["identity_field_coverage"] == 1 / 3
    assert payload["approval_scope"][0]["cost_field_coverage"] == 1.0
    assert payload["approval_scope"][0]["combined_required_field_coverage"] == 0.75
    assert payload["approval_scope"][0]["field_evidence_summary"]["candidate_id"]["present"] is False
    assert payload["approval_scope"][0]["field_evidence_summary"]["model_source"]["present"] is True
    assert payload["source_group_field_coverage_matrix"]["paper_signal"]["identity"]["coverage"] == 1 / 3
    assert payload["approval_scope_field_coverage_summary"]["paper_signal"] == {
        "identity_field_coverage": 1 / 3,
        "cost_field_coverage": 1.0,
        "combined_required_field_coverage": 0.75,
        "missing_identity_fields": ["candidate_id", "policy_fingerprint"],
        "missing_cost_fields": [],
    }
    assert "historical_identity_backfill_for_credit" in payload["approval_scope"][0]["forbidden_change_classes"]
    assert "production_grade_cost_coverage >= 0.95" in payload["post_approval_acceptance_tests"]
    assert payload["pass_conditions"]["approval_scope_includes_write_path_field_coverage"] is True
    assert payload["pass_conditions"]["minimum_future_candidate_bound_rows_declared"] is True
    assert payload["actuals"]["operator_approval_status"] == "AWAITING_OPERATOR_APPROVAL_RECEIPT"
    assert payload["actuals"]["operator_approval_receipt_present"] is False
    assert payload["actuals"]["paper_fill_allowed_false_until_gates_pass"] is True
    assert payload["actuals"]["routes_to_live_false_until_gates_pass"] is True
    assert payload["actuals"]["required_runtime_write_groups"] == payload["required_runtime_write_groups"]
    assert payload["required"]["operator_approval_receipt_present"] is True
    assert payload["required"]["runtime_cost_capture_write_path_audit_status"] == (
        "PASS_RUNTIME_COST_CAPTURE_WRITE_PATH_AUDIT"
    )
    assert payload["sample_blockers"] == payload["blocker_details"][:25]
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["frozen_candidate_modified"] is False
    assert payload["no_live_or_paper_fill_mutation"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_runtime_cost_capture_approval_subject_binds_write_path_coverage_to_receipt() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    approval_packet = runtime_cost_capture_operator_approval_packet(
        policy=policy,
        runtime_cost_capture_remediation={
            "status": "BLOCKED_REQUIRES_FUTURE_CANDIDATE_BOUND_PRODUCTION_GRADE_CAPTURE",
            "required_new_candidate_bound_production_grade_rows": 95,
        },
        runtime_cost_capture_write_path={
            "status": "BLOCKED_RUNTIME_COST_CAPTURE_WRITE_PATH_IDENTITY_BINDING_MISSING",
            "missing_identity_fields_by_group": {
                "paper_signal": ["candidate_id", "policy_fingerprint"],
            },
            "missing_cost_fields_by_group": {},
            "source_group_field_coverage_matrix": {
                "paper_signal": {
                    "identity": {
                        "coverage": 1 / 3,
                        "present_fields": ["model_source"],
                        "missing_fields": ["candidate_id", "policy_fingerprint"],
                    },
                    "cost": {"coverage": 1.0, "present_fields": ["top_book_evidence"], "missing_fields": []},
                    "combined": {"coverage": 0.75, "missing_fields": ["candidate_id", "policy_fingerprint"]},
                    "field_evidence_summary": {
                        "candidate_id": {"present": False, "occurrence_count": 0},
                        "policy_fingerprint": {"present": False, "occurrence_count": 0},
                        "model_source": {"present": True, "occurrence_count": 1},
                    },
                },
            },
        },
    )
    identity_plan = {
        "status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
        "implementation_steps": [{"source_group": "paper_signal"}],
    }

    subject = runtime_cost_capture_approval_subject(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    scope_by_group = {row["source_group"]: row for row in subject["approval_scope"]}
    assert subject["approval_scope_field_coverage_summary"]["paper_signal"]["identity_field_coverage"] == 1 / 3
    assert subject["source_group_field_coverage_matrix"]["paper_signal"]["identity"]["coverage"] == 1 / 3
    assert subject["source_group_field_coverage_matrix_hash"] == row_hash(
        {"source_group_field_coverage_matrix": subject["source_group_field_coverage_matrix"]}
    )
    assert scope_by_group["paper_signal"]["missing_identity_fields"] == ["candidate_id", "policy_fingerprint"]

    changed_packet = copy.deepcopy(approval_packet)
    changed_packet["source_group_field_coverage_matrix"]["paper_signal"]["identity"]["coverage"] = 1.0
    changed_packet["approval_scope_field_coverage_summary"]["paper_signal"]["identity_field_coverage"] = 1.0
    changed_subject = runtime_cost_capture_approval_subject(
        policy=policy,
        runtime_cost_capture_operator_approval=changed_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    assert row_hash(changed_subject) != row_hash(subject)

    template = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    assert template["approval_subject_hash"] == row_hash(subject)
    assert template["approval_subject_hash_status"] == "READY"
    assert template["operator_approval_subject_hash_status"] == "READY"
    assert template["approval_receipt_required_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    assert template["receipt_required_path"] == template["approval_receipt_required_path"]
    assert template["approval_receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    assert template["receipt_template_path"] == template["approval_receipt_template_path"]
    assert template["operator_approval_receipt_path"] == template["approval_receipt_required_path"]
    assert template["operator_approval_receipt_template_path"] == template["approval_receipt_template_path"]
    assert template["runtime_cost_capture_operator_approval_receipt_path"] == template["approval_receipt_required_path"]
    assert template["runtime_cost_capture_operator_approval_receipt_template_path"] == template["approval_receipt_template_path"]
    assert template["runtime_cost_capture_operator_approval_receipt_status_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    )
    assert template["receipt_path"] == template["approval_receipt_required_path"]
    assert template["required_source_groups"] == subject["approval_required_source_groups"]
    assert template["approved_source_groups"] == subject["approval_required_source_groups"]
    assert template["approved_patch_scope"] == subject["approved_patch_scope"]
    assert template["expected_approved_patch_scope"] == subject["approved_patch_scope"]
    assert template["required_acknowledgements"] == subject["required_operator_acknowledgements"]
    assert template["required_operator_acknowledgements"] == subject["required_operator_acknowledgements"]
    assert template["prohibited_patch_scope"] == subject["prohibited_patch_scope"]
    assert template["operator_instructions"]["write_receipt_to"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    )
    assert template["operator_instructions"]["approval_scope"] == (
        "telemetry-only future runtime cost and identity capture"
    )
    assert template["operator_instructions"]["existing_rows_remain_non_counting"] is True
    assert template["operator_instructions"]["paper_fill_allowed_after_approval"] is False
    assert template["operator_instructions"]["routes_to_live_after_approval"] is False
    assert set(template["operator_instructions"]["do_not_change"]) >= {
        "candidate_id",
        "policy_fingerprint",
        "approval_subject_hash",
        "approved_source_groups",
        "approved_patch_scope",
    }
    assert template["receipt_template"]["approval_subject_hash"] == row_hash(subject)
    receipt = dict(template["receipt_template"])
    receipt.update(
        {
            "operator_approval_granted": True,
            "approval_utc": "2026-06-25T20:30:00Z",
            "approved_by": "unit-test-operator",
            "acknowledges_no_historical_backfill_for_credit": True,
            "acknowledges_no_frozen_candidate_or_model_changes": True,
            "acknowledges_paper_fill_and_live_routes_remain_false": True,
        }
    )

    payload = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=changed_packet,
        runtime_identity_binding_plan=identity_plan,
        receipt=receipt,
    )

    assert payload["status"] == "BLOCKED_INVALID_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    assert "approval_subject_hash_matches_current_plan" in payload["blocked_reasons"]
    assert payload["pass_conditions"]["approval_subject_hash_matches_current_plan"] is False
    assert payload["approval_subject_hash_status"] == "READY"
    assert payload["operator_approval_subject_hash_status"] == "READY"
    assert payload["expected_approval_subject_hash"] == row_hash(changed_subject)
    assert payload["receipt_approval_subject_hash"] == row_hash(subject)
    assert payload["approved_patch_scope"] == subject["approved_patch_scope"]
    assert payload["expected_approved_patch_scope"] == changed_subject["approved_patch_scope"]
    assert payload["required_acknowledgements"] == changed_subject["required_operator_acknowledgements"]
    assert payload["required_operator_acknowledgements"] == changed_subject["required_operator_acknowledgements"]
    assert payload["prohibited_patch_scope"] == changed_subject["prohibited_patch_scope"]
    assert payload["operator_instructions"]["required_approval_subject_hash"] == row_hash(changed_subject)
    assert payload["operator_instructions"]["existing_rows_remain_non_counting"] is True
    assert payload["operator_instructions"]["paper_fill_allowed_after_approval"] is False
    assert payload["operator_instructions"]["routes_to_live_after_approval"] is False
    assert payload["receipt_required_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    assert payload["receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"


def test_runtime_identity_binding_implementation_plan_maps_line_targets(tmp_path) -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    files = {
        "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py": """
trainer_source = prediction.get("trainer_source")
model_source = prediction.get("model_source")
signal_id = prediction.get("signal_id")
paper_fill_allowed = prediction.get("paper_fill_allowed")
signal_key = "v2:signals:paper"
""",
        "v2/backend/app/cli/paper_online_runtime.py": 'legacy_signal_key = "v2:signals:paper"\n',
        "v2/backend/app/cli/v2_trade_management_paper_loop.py": """
intent = {
    "model_id": s.get("model_id"),
    "trainer_source": s.get("trainer_source"),
}
paper_intents_key = "paper:intents"
held_key = "paper:intents_held_by_paper_fill_gate"
accepted_for_ledger = []
accepted_open_fills = []
ledger_payload = {
    "accepted_intents": accepted_for_ledger,
}
ledger_key = "paper:ledger"
closed_trades = []
close_state_sample = []
closed_key = "paper:closed_trades"
def _build_trainer_feedback_rows():
    return []
trainer_feedback_consumable_rows = []
feedback_key = "trainer:feedback:outcomes"
feedback_quarantine_key = "trainer:feedback:outcomes:quarantine"
""",
        "v2/backend/app/services/paper_shadow_outcome_observer/service.py": """
def _build_trainer_feedback_rows():
    return []
trainer_feedback_consumable_rows = []
trainer_feedback_key = "trainer:feedback:outcomes"
trainer_feedback_quarantine_key = "trainer:feedback:outcomes:quarantine"
""",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    payload = runtime_identity_binding_implementation_plan(
        repo_root=tmp_path,
        policy=policy,
        runtime_cost_capture_operator_approval={
            "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "operator_approval_required": True,
            "approval_required_source_groups": [
                "paper_signal",
                "paper_intent",
                "paper_ledger",
                "paper_closed_trades",
                "trainer_feedback",
            ],
            "approval_scope": [
                {
                    "source_group": "paper_signal",
                    "capture_stage": "decision_time_signal",
                    "files": [
                        "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
                        "v2/backend/app/cli/paper_online_runtime.py",
                    ],
                    "redis_keys": ["v2:signals:paper:*"],
                    "required_cost_fields": ["observed_bid_ask_spread", "top_book_evidence"],
                    "missing_identity_fields": ["candidate_id", "policy_fingerprint"],
                    "missing_cost_fields": [],
                    "required_join_key_fields": {
                        "snapshot_id": ["feature_snapshot_id", "snapshot_id"],
                        "signal_id": ["signal_id", "paper_signal_id"],
                    },
                },
                {
                    "source_group": "paper_intent",
                    "capture_stage": "pre_submit_intent",
                    "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
                    "redis_keys": ["v2:paper:intents"],
                    "required_cost_fields": ["order_size"],
                    "missing_identity_fields": ["candidate_id", "policy_fingerprint"],
                    "missing_cost_fields": [],
                },
                {
                    "source_group": "paper_ledger",
                    "capture_stage": "paper_lifecycle_or_fill",
                    "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
                    "redis_keys": ["v2:paper:ledger"],
                },
                {
                    "source_group": "paper_closed_trades",
                    "capture_stage": "closed_outcome",
                    "files": ["v2/backend/app/cli/v2_trade_management_paper_loop.py"],
                    "redis_keys": ["v2:paper:closed_trades"],
                },
                {
                    "source_group": "trainer_feedback",
                    "capture_stage": "trainer_feedback_outcome",
                    "files": [
                        "v2/backend/app/cli/v2_trade_management_paper_loop.py",
                        "v2/backend/app/services/paper_shadow_outcome_observer/service.py",
                    ],
                    "redis_keys": ["v2:trainer:feedback:outcomes"],
                },
            ],
        },
    )

    assert payload["status"] == "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"
    assert payload["incomplete_source_groups"] == []
    assert len(payload["implementation_steps"]) == 5
    assert payload["implementation_plan"] == payload["implementation_steps"]
    assert payload["required_source_groups"] == payload["approval_required_source_groups"]
    assert payload["operator_approval_required_source_groups"] == payload["approval_required_source_groups"]
    assert payload["source_groups"] == payload["approval_required_source_groups"]
    assert payload["source_group_count"] == len(payload["approval_required_source_groups"])
    assert payload["complete_source_groups"] == payload["approval_required_source_groups"]
    assert payload["required_identity_fields"] == ["candidate_id", "policy_fingerprint", "model_source"]
    assert payload["source_files_to_patch"] == payload["source_files_scanned"]
    assert payload["write_path_files"] == payload["source_files_scanned"]
    assert payload["source_file_count"] == len(payload["source_files_scanned"])
    assert payload["source_group_implementation_plan_count"] == len(payload["implementation_steps"])
    assert set(payload["source_group_implementation_plans"]) == set(payload["approval_required_source_groups"])
    assert payload["missing_identity_fields_by_group"]["paper_signal"] == ["candidate_id", "policy_fingerprint"]
    assert payload["missing_cost_fields_by_group"]["paper_signal"] == []
    assert payload["missing_fields_by_source_group"]["paper_signal"] == {
        "missing_identity_fields": ["candidate_id", "policy_fingerprint"],
        "missing_cost_fields": [],
    }
    assert payload["required_cost_fields_by_group"]["paper_signal"] == [
        "observed_bid_ask_spread",
        "top_book_evidence",
    ]
    assert payload["required_join_key_fields"]["paper_signal"] == {
        "snapshot_id": ["feature_snapshot_id", "snapshot_id"],
        "signal_id": ["signal_id", "paper_signal_id"],
    }
    assert payload["implementation_steps"][0]["source_group"] == "paper_signal"
    assert payload["implementation_steps"][0]["missing_line_target_terms"] == []
    assert "stamp frozen candidate_id onto existing old-policy or unbound rows" in payload["implementation_steps"][0]["forbidden_shortcuts"]
    assert payload["pass_conditions"]["line_targets_found_for_all_approval_required_groups"] is True
    assert payload["operator_approval_required_before_applying_plan"] is True
    assert payload["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["approval_receipt_required_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    assert payload["approval_receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    assert payload["approval_receipt_status_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["frozen_candidate_modified"] is False
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_future_runtime_cost_evidence_acceptance_decision_accepts_clean_future_row() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    row = {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "decision_time": "2026-06-25T00:01:00Z",
        "available_at": "2026-06-25T00:00:30Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "source_timestamp": "2026-06-25T00:00:20Z",
        "feature_freshness_state": "CURRENT",
        "best_bid": 100.0,
        "best_ask": 100.02,
        "top_book_bid_depth_usd": 100_000.0,
        "top_book_ask_depth_usd": 100_000.0,
        "bid_depth_usd": 100_000.0,
        "ask_depth_usd": 100_000.0,
        "order_size_usd": 100.0,
        "depth_price_impact_bps": 0.1,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.2,
        "latency_reserve_bps": 0.05,
        "partial_fill_probability": 0.0,
        "mark_index_divergence_bps": 0.0,
        "fallback": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }

    for source_group in ("paper_intent", "paper_online_ledger"):
        payload = future_runtime_cost_evidence_acceptance_decision(
            row,
            policy=policy,
            source_group=source_group,
            operator_approved=True,
        )

        assert payload["accepted_as_phase_1_production_grade_evidence"] is True
        assert payload["rejection_reasons"] == []
        assert payload["source_group"] == source_group
        assert payload["identity_state"] == "complete"
        assert payload["production_grade"] is True
        assert payload["fallback"] is False
        assert payload["paper_fill_allowed"] is False
        assert payload["routes_to_live"] is False
        assert payload["counts_as_a_grade_evidence"] is False


def test_future_runtime_cost_evidence_acceptance_contract_blocks_preapproval_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    payload = future_runtime_cost_evidence_acceptance_contract(
        policy=policy,
        paper_cost_telemetry={
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 12,
            "paper_fill_allowed_rows": 0,
            "live_route_rows": 0,
            "source_group_readiness": {
                "paper_intent": {
                    "rows": 12,
                    "production_grade_rows": 12,
                    "challenger_bound_production_grade_rows": 0,
                    "old_policy_or_unbound_production_grade_rows": 12,
                    "paper_fill_allowed_rows": 0,
                    "live_route_rows": 0,
                    "blocked_reasons": ["challenger_bound_production_grade_rows_gt_0"],
                }
            },
        },
        runtime_cost_capture_operator_approval={
            "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "operator_approval_required": True,
        },
        runtime_identity_binding_plan={
            "status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH",
        },
    )

    assert payload["status"] == "AWAITING_OPERATOR_APPROVAL_BEFORE_ACCEPTING_FUTURE_RUNTIME_COST_ROWS"
    assert payload["current_runtime_cost_capture_operator_approved"] is False
    assert payload["operator_approved"] is False
    assert payload["current_operator_approved"] is False
    assert payload["current_operator_approval_packet_status"] == "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
    assert payload["current_operator_approval_receipt_status"] is None
    assert payload["current_operator_approval_receipt_blocked_conditions"] is None
    assert payload["current_operator_approval_missing_or_invalid_receipt_fields"] is None
    assert payload["current_operator_approval_receipt_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    )
    assert payload["current_operator_approval_receipt_template_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    )
    assert payload["current_operator_approval_receipt_status_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    )
    assert payload["required_source_groups"] == []
    assert payload["approved_source_groups"] == []
    assert payload["current_challenger_bound_production_grade_rows"] == 0
    assert payload["future_challenger_bound_production_grade_rows"] == 0
    assert payload["current_old_policy_or_unbound_production_grade_rows_quarantined"] == 12
    assert payload["old_policy_or_unbound_production_grade_rows"] == 12
    assert payload["paper_fill_allowed_rows"] == 0
    assert payload["live_route_rows"] == 0
    assert payload["pass_conditions"]["operator_approval_granted"] is False
    assert payload["future_runtime_row_acceptance_gate_open"] is False
    assert payload["gate_open"] is False
    assert payload["future_runtime_cost_acceptance_gate_open"] is False
    assert payload["currently_countable_phase_1_production_grade_rows"] == 0
    assert "operator_approval_granted" in payload["blocked_reasons"]
    assert "future_challenger_bound_production_grade_rows_present" in payload["blocked_reasons"]
    assert payload["acceptance_blocker_details"]["operator_approval_granted"] == {
        "passed": False,
        "observed": False,
        "required": True,
    }
    assert payload["acceptance_blocker_details"]["operator_approval_receipt_valid_or_packet_explicitly_approved"][
        "observed"
    ] == "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
    assert payload["blocker_details"] == {
        key: payload["acceptance_blocker_details"][key]
        for key in payload["blocked_reasons"]
    }
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["sample_blockers"][0]["pass_condition"] == "operator_approval_granted"
    assert payload["actuals"]["operator_approval_granted"] is False
    assert payload["required"]["operator_approval_granted"] is True
    assert payload["actuals"]["future_challenger_bound_production_grade_rows_present"] == 0
    assert payload["required"]["future_challenger_bound_production_grade_rows_present"] == ">0"
    assert payload["actuals"]["old_or_unbound_rows_not_counted"] == 12
    assert payload["actuals"]["future_runtime_row_acceptance_gate_open"] is False
    assert payload["pass_conditions"]["old_or_unbound_rows_not_counted"] is True
    assert payload["acceptance_predicate"]["historical_backfill_allowed_for_credit"] is False
    assert payload["rows_count_only_after_operator_approval"] is True
    assert payload["existing_old_or_unbound_rows_may_not_be_backfilled_for_credit"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_runtime_cost_capture_operator_approval_receipt_status_blocks_missing_receipt() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    approval_packet = {
        "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "approval_required_source_groups": ["paper_intent"],
    }
    identity_plan = {"status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"}

    template = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    payload = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        receipt={},
    )

    assert template["status"] == "TEMPLATE_ONLY_NOT_OPERATOR_APPROVAL"
    assert template["receipt_template"]["operator_approval_granted"] is False
    assert payload["status"] == "AWAITING_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    assert payload["operator_approval_required"] is True
    assert payload["operator_approval_granted"] is False
    assert payload["approval_receipt_present"] is False
    assert payload["operator_approval_receipt_present"] is False
    assert payload["operator_approval_receipt_status"] == payload["status"]
    assert payload["operator_approval_receipt_valid"] is False
    assert payload["approval_gate_open"] is False
    assert payload["operator_approved_runtime_cost_capture"] is False
    assert payload["operator_approved_identity_binding"] is False
    assert payload["approval_required_before_runtime_write_path_edits"] is True
    assert payload["operator_approval_required_before_runtime_write_path_edits"] is True
    assert payload["operator_approval_required_before_applying_plan"] is True
    assert payload["approval_subject_hash"] == template["approval_subject_hash"]
    assert payload["pass_conditions"]["approval_receipt_present"] is False
    assert payload["blocked_reasons"] == payload["blocked_conditions"]
    assert "approval_receipt_present" in payload["blocked_reasons"]
    assert "operator_approval_granted_true" in payload["blocked_reasons"]
    assert payload["blocker_details"][0]["pass_condition"] == "approval_receipt_present"
    assert payload["blocker_details"][0]["source_artifact"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    )
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["sample_blockers"] == payload["blocker_details"][:25]
    assert payload["actuals"]["approval_receipt_present"] is False
    assert payload["required"]["approval_receipt_present"] is True
    assert payload["actuals"]["operator_approval_granted_true"] is None
    assert payload["required"]["operator_approval_granted_true"] is True
    assert payload["actuals"]["approved_source_groups_exact_match"] == []
    assert payload["required"]["approved_source_groups_exact_match"] == ["paper_intent"]
    assert "__receipt__" in payload["missing_or_invalid_receipt_fields"]
    assert "operator_approval_granted" in payload["missing_or_invalid_receipt_fields"]
    assert payload["missing_receipt_fields"] == payload["missing_or_invalid_receipt_fields"]
    assert "operator_approval_granted" in payload["required_receipt_fields"]
    assert "approval_subject_hash" in payload["required_receipt_fields"]
    assert payload["operator_action_required"] is True
    assert payload["approval_receipt_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt.json"
    assert payload["approval_receipt_template_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_template.json"
    assert payload["approval_receipt_status_path"] == "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    assert payload["operator_approval_receipt_path"] == payload["approval_receipt_path"]
    assert payload["operator_approval_receipt_template_path"] == payload["approval_receipt_template_path"]
    assert payload["runtime_cost_capture_operator_approval_receipt_path"] == payload["approval_receipt_path"]
    assert payload["runtime_cost_capture_operator_approval_receipt_template_path"] == payload[
        "approval_receipt_template_path"
    ]
    assert payload["runtime_cost_capture_operator_approval_receipt_status_path"] == (
        "challenger_v2_runtime_cost_capture_operator_approval_receipt_status.json"
    )
    assert payload["receipt_path"] == payload["approval_receipt_path"]
    assert payload["approval_required_source_groups"] == ["paper_intent"]
    assert payload["operator_approval_required_source_groups"] == ["paper_intent"]
    assert payload["required_source_groups"] == ["paper_intent"]
    assert payload["source_groups"] == ["paper_intent"]
    assert payload["expected_source_groups"] == ["paper_intent"]
    assert payload["expected_approved_source_groups"] == ["paper_intent"]
    assert payload["source_group_count"] == 1
    assert payload["approved_source_group_count"] == 0
    assert payload["required_source_group_count"] == 1
    assert payload["approved_source_groups"] == []
    assert payload["receipt_acceptance_rule"]["approval_subject_hash"] == template["approval_subject_hash"]
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_runtime_cost_capture_operator_approval_receipt_status_passes_exact_receipt() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    approval_packet = {
        "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "approval_required_source_groups": ["paper_intent", "paper_ledger"],
    }
    identity_plan = {"status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"}
    template = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    receipt = dict(template["receipt_template"])
    receipt.update(
        {
            "operator_approval_granted": True,
            "approval_utc": "2026-06-25T20:30:00Z",
            "approved_by": "unit-test-operator",
            "acknowledges_no_historical_backfill_for_credit": True,
            "acknowledges_no_frozen_candidate_or_model_changes": True,
            "acknowledges_paper_fill_and_live_routes_remain_false": True,
        }
    )

    payload = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        receipt=receipt,
    )

    assert payload["status"] == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    assert payload["operator_approval_granted"] is True
    assert payload["approval_receipt_present"] is True
    assert payload["operator_approval_receipt_present"] is True
    assert payload["operator_approval_receipt_status"] == payload["status"]
    assert payload["operator_approval_receipt_valid"] is True
    assert payload["approval_gate_open"] is True
    assert payload["operator_approved_runtime_cost_capture"] is True
    assert payload["operator_approved_identity_binding"] is True
    assert payload["blocked_conditions"] == []
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == []
    assert payload["failed_blocker_details"] == []
    assert payload["sample_blockers"] == []
    assert payload["actuals"]["approval_receipt_present"] is True
    assert payload["actuals"]["operator_approval_granted_true"] is True
    assert payload["actuals"]["approved_source_groups_exact_match"] == ["paper_intent", "paper_ledger"]
    assert payload["required"]["approval_subject_hash_matches_current_plan"] == template["approval_subject_hash"]
    assert payload["required"]["approved_source_groups_exact_match"] == ["paper_intent", "paper_ledger"]
    assert payload["missing_or_invalid_receipt_fields"] == []
    assert payload["missing_receipt_fields"] == []
    assert "approved_patch_scope" in payload["required_receipt_fields"]
    assert payload["operator_action_required"] is False
    assert all(payload["pass_conditions"].values())
    assert payload["approved_source_groups_observed"] == ["paper_intent", "paper_ledger"]
    assert payload["approved_source_groups"] == ["paper_intent", "paper_ledger"]
    assert payload["expected_approved_source_groups"] == ["paper_intent", "paper_ledger"]
    assert payload["source_group_count"] == 2
    assert payload["approved_source_group_count"] == 2
    assert payload["required_source_group_count"] == 2
    assert payload["promotion_evidence"] is False


def test_future_runtime_cost_evidence_acceptance_contract_uses_valid_approval_receipt() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    approval_packet = {
        "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "approval_required_source_groups": ["paper_intent"],
    }
    identity_plan = {"status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"}
    template = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    receipt = dict(template["receipt_template"])
    receipt.update(
        {
            "operator_approval_granted": True,
            "approval_utc": "2026-06-25T20:30:00Z",
            "approved_by": "unit-test-operator",
            "acknowledges_no_historical_backfill_for_credit": True,
            "acknowledges_no_frozen_candidate_or_model_changes": True,
            "acknowledges_paper_fill_and_live_routes_remain_false": True,
        }
    )
    receipt_status = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        receipt=receipt,
    )

    payload = future_runtime_cost_evidence_acceptance_contract(
        policy=policy,
        paper_cost_telemetry={
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 0,
            "paper_fill_allowed_rows": 0,
            "live_route_rows": 0,
        },
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        runtime_cost_capture_operator_approval_receipt=receipt_status,
    )

    assert receipt_status["status"] == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    assert payload["status"] == "AWAITING_FUTURE_CHALLENGER_BOUND_PRODUCTION_GRADE_RUNTIME_ROWS"
    assert payload["current_runtime_cost_capture_operator_approved"] is True
    assert payload["operator_approved"] is True
    assert payload["current_operator_approved"] is True
    assert payload["operator_approval_receipt_status"] == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    assert payload["current_operator_approval_packet_status"] == "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING"
    assert payload["current_operator_approval_receipt_status"] == "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    assert payload["current_operator_approval_receipt_blocked_conditions"] == []
    assert payload["current_operator_approval_missing_or_invalid_receipt_fields"] == []
    assert payload["current_operator_approval_receipt_path"] == receipt_status["operator_approval_receipt_path"]
    assert payload["current_operator_approval_receipt_template_path"] == receipt_status[
        "operator_approval_receipt_template_path"
    ]
    assert payload["current_operator_approval_receipt_status_path"] == receipt_status[
        "runtime_cost_capture_operator_approval_receipt_status_path"
    ]
    assert payload["required_source_groups"] == ["paper_intent"]
    assert payload["approved_source_groups"] == ["paper_intent"]
    assert payload["current_operator_approval_subject_hash"] == receipt_status["approval_subject_hash"]
    assert payload["future_runtime_row_acceptance_gate_open"] is True
    assert payload["gate_open"] is True
    assert payload["future_runtime_cost_acceptance_gate_open"] is True
    assert payload["currently_countable_phase_1_production_grade_rows"] == 0
    assert payload["blocked_reasons"] == ["future_challenger_bound_production_grade_rows_present"]
    assert payload["blocker_details"] == {
        "future_challenger_bound_production_grade_rows_present": payload["acceptance_blocker_details"][
            "future_challenger_bound_production_grade_rows_present"
        ]
    }
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["sample_blockers"][0]["pass_condition"] == "future_challenger_bound_production_grade_rows_present"
    assert payload["actuals"]["operator_approval_granted"] is True
    assert payload["actuals"]["operator_approval_receipt_valid_or_packet_explicitly_approved"] == (
        "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"
    )
    assert payload["actuals"]["future_challenger_bound_production_grade_rows_present"] == 0
    assert payload["actuals"]["future_runtime_row_acceptance_gate_open"] is True
    assert payload["required"]["currently_countable_phase_1_production_grade_rows"] == (
        ">0 after approval and future candidate-bound capture"
    )
    assert payload["future_challenger_bound_production_grade_rows"] == 0
    assert payload["old_policy_or_unbound_production_grade_rows"] == 0
    assert payload["pass_conditions"]["operator_approval_receipt_valid_or_packet_explicitly_approved"] is True


def test_future_runtime_cost_acceptance_quarantines_old_unbound_fill_allowed_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    approval_packet = {
        "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "approval_required_source_groups": ["paper_intent"],
    }
    identity_plan = {"status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"}
    template = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    receipt = dict(template["receipt_template"])
    receipt.update(
        {
            "operator_approval_granted": True,
            "approval_utc": "2026-06-25T20:30:00Z",
            "approved_by": "unit-test-operator",
            "acknowledges_no_historical_backfill_for_credit": True,
            "acknowledges_no_frozen_candidate_or_model_changes": True,
            "acknowledges_paper_fill_and_live_routes_remain_false": True,
        }
    )
    receipt_status = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        receipt=receipt,
    )

    payload = future_runtime_cost_evidence_acceptance_contract(
        policy=policy,
        paper_cost_telemetry={
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 3,
            "paper_fill_allowed_rows": 3,
            "live_route_rows": 0,
            "candidate_bound_paper_fill_allowed_rows": 0,
            "candidate_bound_live_route_rows": 0,
        },
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        runtime_cost_capture_operator_approval_receipt=receipt_status,
    )

    assert payload["status"] == "AWAITING_FUTURE_CHALLENGER_BOUND_PRODUCTION_GRADE_RUNTIME_ROWS"
    assert payload["future_runtime_row_acceptance_gate_open"] is True
    assert payload["blocked_reasons"] == ["future_challenger_bound_production_grade_rows_present"]
    assert payload["paper_fill_allowed_rows"] == 3
    assert payload["candidate_bound_paper_fill_allowed_rows"] == 0
    assert payload["quarantined_non_candidate_bound_paper_fill_allowed_rows"] == 3
    assert payload["pass_conditions"]["old_or_unbound_paper_fill_allowed_rows_quarantined"] is True
    assert payload["pass_conditions"]["candidate_bound_paper_fill_allowed_rows_eq_0"] is True


def test_future_runtime_cost_acceptance_blocks_candidate_bound_fill_allowed_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    approval_packet = {
        "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
        "approval_required_source_groups": ["paper_intent"],
    }
    identity_plan = {"status": "READY_FOR_OPERATOR_APPROVED_TELEMETRY_ONLY_IDENTITY_BINDING_PATCH"}
    template = runtime_cost_capture_operator_approval_receipt_template(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
    )
    receipt = dict(template["receipt_template"])
    receipt.update(
        {
            "operator_approval_granted": True,
            "approval_utc": "2026-06-25T20:30:00Z",
            "approved_by": "unit-test-operator",
            "acknowledges_no_historical_backfill_for_credit": True,
            "acknowledges_no_frozen_candidate_or_model_changes": True,
            "acknowledges_paper_fill_and_live_routes_remain_false": True,
        }
    )
    receipt_status = runtime_cost_capture_operator_approval_receipt_status(
        policy=policy,
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        receipt=receipt,
    )

    payload = future_runtime_cost_evidence_acceptance_contract(
        policy=policy,
        paper_cost_telemetry={
            "challenger_bound_production_grade_rows": 1,
            "old_policy_or_unbound_production_grade_rows": 0,
            "paper_fill_allowed_rows": 1,
            "live_route_rows": 0,
            "candidate_bound_paper_fill_allowed_rows": 1,
            "candidate_bound_live_route_rows": 0,
        },
        runtime_cost_capture_operator_approval=approval_packet,
        runtime_identity_binding_plan=identity_plan,
        runtime_cost_capture_operator_approval_receipt=receipt_status,
    )

    assert payload["status"] == "BLOCKED_RUNTIME_COST_ACCEPTANCE_ROUTE_OR_FILL_ALLOWED"
    assert payload["future_runtime_row_acceptance_gate_open"] is False
    assert payload["currently_countable_phase_1_production_grade_rows"] == 0
    assert payload["blocked_reasons"] == ["candidate_bound_paper_fill_allowed_rows_eq_0"]
    assert payload["candidate_bound_paper_fill_allowed_rows"] == 1
    assert payload["quarantined_non_candidate_bound_paper_fill_allowed_rows"] == 0
    assert payload["blocker_details"]["candidate_bound_paper_fill_allowed_rows_eq_0"]["observed"] == 1


def test_runtime_cost_capture_contract_passes_when_candidate_bound_capture_covers_95pct() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = runtime_cost_capture_contract_audit(
        policy=policy,
        cost_status={
            "status": "PASS",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_coverage": 0.95,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
        },
        cost_capture_gap={
            "status": "PASS_PRODUCTION_COST_CAPTURE_READY",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_rows": 95,
            "production_grade_cost_coverage": 0.95,
            "minimum_rows_required_for_95pct_coverage": 95,
            "production_grade_cost_row_shortfall_to_95pct": 0,
            "hard_blocking_fields": [],
            "top_book_enriched_rows": 95,
            "candidate_bound_intents": 95,
            "trusted_candidate_bound_intent_matches": 95,
            "positive_order_size_matches": 95,
            "paper_telemetry_production_grade_rows": 95,
            "challenger_bound_production_grade_paper_rows": 95,
            "old_policy_or_unbound_production_grade_paper_rows": 0,
            "old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
        },
        paper_intent_join_status={"candidate_bound_intents": 95, "trusted_snapshot_matches": 95, "positive_order_size_matches": 95},
        paper_cost_telemetry={"live_route_rows": 0, "paper_fill_allowed_rows": 0},
        top_book_enrichment_status={"top_book_enriched_rows": 95},
        paper_binding_preflight={"live_route_violation_rows": 0},
    )

    assert payload["status"] == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == {}
    assert payload["failed_blocker_details"] == {}
    assert payload["phase_1_blocker_details"] == {}
    assert payload["failed_phase_1_blocker_details"] == {}
    assert all(payload["pass_conditions"].values())
    assert payload["promotion_evidence"] is False


def test_runtime_cost_capture_contract_quarantines_old_unbound_fill_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = runtime_cost_capture_contract_audit(
        policy=policy,
        cost_status={
            "status": "PASS",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_coverage": 0.95,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
        },
        cost_capture_gap={
            "status": "PASS_PRODUCTION_COST_CAPTURE_READY",
            "total_cost_evidence_rows": 100,
            "production_grade_cost_rows": 95,
            "production_grade_cost_coverage": 0.95,
            "minimum_rows_required_for_95pct_coverage": 95,
            "production_grade_cost_row_shortfall_to_95pct": 0,
            "hard_blocking_fields": [],
            "top_book_enriched_rows": 95,
            "candidate_bound_intents": 95,
            "trusted_candidate_bound_intent_matches": 95,
            "positive_order_size_matches": 95,
            "paper_telemetry_production_grade_rows": 98,
            "challenger_bound_production_grade_paper_rows": 95,
            "old_policy_or_unbound_production_grade_paper_rows": 3,
            "old_policy_or_unbound_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
        },
        paper_intent_join_status={"candidate_bound_intents": 95, "trusted_snapshot_matches": 95, "positive_order_size_matches": 95},
        paper_cost_telemetry={
            "live_route_rows": 0,
            "paper_fill_allowed_rows": 3,
            "candidate_bound_live_route_rows": 0,
            "candidate_bound_paper_fill_allowed_rows": 0,
        },
        top_book_enrichment_status={"top_book_enriched_rows": 95},
        paper_binding_preflight={"live_route_violation_rows": 0},
    )

    assert payload["status"] == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"
    assert payload["blocked_reasons"] == []
    assert payload["condition_details"]["paper_telemetry_fill_allowed_rows_quarantined_when_not_candidate_bound"][
        "quarantined_non_candidate_bound_paper_fill_allowed_rows"
    ] == 3
    assert payload["condition_details"]["candidate_bound_paper_fill_allowed_rows_eq_0"]["observed"] == 0
    assert payload["current_capture_counts"]["paper_telemetry_fill_allowed_rows"] == 3
    assert payload["current_capture_counts"]["candidate_bound_paper_fill_allowed_rows"] == 0
    assert all(payload["pass_conditions"].values())


def test_zero_candidate_supply_diagnosis_identifies_cost_liquidity_blocker() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    scored = [
        {
            "candidate_id": "challenger_v2_test",
            "policy_fingerprint": "fingerprint",
            "model_source": "test_model",
            "snapshot_id": "snap-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-25T00:01:00Z",
            "predicted_direction": "LONG",
            "predicted_gross_edge_bps": 30.0,
            "production_cost_bps": 12.0,
            "predicted_net_edge_bps": 18.0,
            "threshold_distance_bps": -2.0,
            "estimated_production_cost": {"production_grade_evidence": False},
            "selected": False,
            "rejection_reasons": ["cost_not_production_grade", "liquidity_missing_depth_or_order_size", "threshold"],
            "feature_drift": {"out_of_training_range_features": []},
            "liquidity_status": "MISSING_DEPTH_OR_ORDER_SIZE",
        },
        {
            "candidate_id": "challenger_v2_test",
            "policy_fingerprint": "fingerprint",
            "model_source": "test_model",
            "snapshot_id": "snap-2",
            "symbol": "ETHUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-25T00:01:00Z",
            "predicted_direction": "SHORT",
            "predicted_gross_edge_bps": 50.0,
            "production_cost_bps": 12.0,
            "predicted_net_edge_bps": 38.0,
            "threshold_distance_bps": 18.0,
            "estimated_production_cost": {"production_grade_evidence": False},
            "selected": False,
            "rejection_reasons": ["cost_not_production_grade", "liquidity_missing_depth_or_order_size"],
            "feature_drift": {"out_of_training_range_features": ["ret_pct"]},
            "liquidity_status": "MISSING_DEPTH_OR_ORDER_SIZE",
        },
    ]

    payload = zero_candidate_supply_diagnosis(
        policy=policy,
        scored_rows=scored,
        cost_status={
            "production_grade_cost_coverage": 0.0,
            "blocker_diagnosis": {"hard_blocking_fields": ["order_size"]},
        },
        drift_status={"high_drift_features_current_runtime": ["ret_pct"]},
        paper_intent_join_status={"candidate_bound_intents": 0, "positive_order_size_matches": 0},
    )

    assert payload["status"] == "ZERO_SUPPLY_DIAGNOSED"
    assert payload["root_cause_classification"] == "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED"
    assert payload["root_cause"] == "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED"
    assert payload["zero_supply_root_cause"] == "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED"
    assert payload["zero_supply_root_causes"][0]["root_cause"] == "cost_not_production_grade"
    assert payload["zero_supply_root_causes"][0]["blocked_rows"] == 2
    assert payload["root_cause_summary"]["classification"] == "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED"
    assert payload["root_cause_summary"]["zero_supply_root_causes"] == payload["zero_supply_root_causes"]
    assert payload["root_cause_summary"]["next_actions"] == payload["next_actions"]
    assert payload["pass_conditions"]["root_cause_classification_present"] is True
    assert payload["pass_conditions"]["blocker_details_present_when_zero_supply"] is True
    assert payload["blocked_reasons"] == ["cost_not_production_grade", "liquidity_missing_depth_or_order_size", "threshold"]
    assert payload["blocker_details"][0]["blocker"] == "cost_not_production_grade"
    assert payload["zero_supply_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["current_rows_scored_gt_0"] == 2
    assert payload["actuals"]["zero_supply_status_matches_selected_rows"] == {
        "status": "ZERO_SUPPLY_DIAGNOSED",
        "selected_rows": 0,
    }
    assert payload["actuals"]["production_grade_cost_rows"] == 0
    assert payload["actuals"]["rows_above_threshold"] == 1
    assert payload["required"]["current_rows_scored_gt_0"] == ">0"
    assert payload["required"]["paper_fill_allowed_false"] is False
    assert payload["sample_blockers"] == payload["blocker_details"][:25]
    assert "capture_order_size_depth_top_book_and_depth_derived_impact_before_candidate_credit" in payload["next_actions"]
    assert payload["current_rows_scanned"] == 2
    assert payload["current_valid_rows"] == 2
    assert payload["shadow_scored_rows"] == 2
    assert payload["total_scored_rows"] == 2
    assert payload["total_rows"] == 2
    assert payload["qualified_rows"] == 0
    assert payload["rows_above_threshold"] == 1
    assert payload["above_threshold_rows"] == 1
    assert payload["rows_with_production_grade_cost"] == 0
    assert payload["production_grade_cost_rows"] == 0
    assert payload["rows_with_liquidity_pass"] == 0
    assert payload["liquidity_pass_rows"] == 0
    assert payload["rows_without_distribution_drift"] == 1
    assert payload["drift_pass_rows"] == 1
    assert payload["threshold_band_counts"]["gte_threshold"] == 1
    assert payload["threshold_band_counts"]["within_5bps_below_threshold"] == 1
    assert payload["threshold_distance_summary"] == {
        "count": 2,
        "min": -2.0,
        "median": 8.0,
        "max": 18.0,
        "above_threshold_rows": 1,
    }
    assert payload["threshold_distance_bands"] == payload["threshold_band_counts"]
    assert payload["threshold_bands_by_side"] == payload["threshold_band_counts_by_side"]
    assert payload["liquidity_status_counts"] == {"MISSING_DEPTH_OR_ORDER_SIZE": 2}
    assert payload["rejection_reason_counts"]["cost_not_production_grade"] == 2
    assert payload["reason_counts"] == payload["rejection_reason_counts"]
    assert payload["rejection_reason_by_side"] == payload["rejection_reason_counts_by_side"]
    assert payload["rejection_reason_counts_by_side"]["SHORT"]["liquidity_missing_depth_or_order_size"] == 1
    assert payload["shadow_supply_blocker_details"]["cost_not_production_grade"]["all_rows_blocked"] is True
    assert payload["shadow_supply_blocker_details"]["liquidity_missing_depth_or_order_size"]["all_rows_blocked"] is True
    assert payload["shadow_supply_blocker_details"]["threshold"]["rows_above_threshold"] == 1
    assert payload["sample_near_threshold_rows"] == payload["near_threshold_rejected_sample"]
    assert payload["sample_above_threshold_rejected_rows"] == payload["above_threshold_rejected_sample"]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["pass_conditions"]["places_real_order_false"] is True
    assert payload["promotion_evidence"] is False
    assert payload["pass_conditions"]["promotion_evidence_false"] is True
    assert payload["sample_near_threshold_rows"][0]["places_real_order"] is False
    assert payload["sample_near_threshold_rows"][0]["promotion_evidence"] is False


def _shadow_policy() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
        threshold_bps=20.0,
    )


def _shadow_scored_row(side: str, idx: int) -> dict:
    net_edge = 50.0 - float(idx)
    score = net_edge if side == "LONG" else -net_edge
    return {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "snapshot_id": f"snap-{side.lower()}-{idx}",
        "symbol": f"SYM{idx:02d}USDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:00Z",
        "predicted_direction": side,
        "score": score,
        "predicted_gross_edge_bps": net_edge + 12.0,
        "production_cost_bps": 12.0,
        "predicted_net_edge_bps": net_edge,
        "threshold_distance_bps": net_edge - 20.0,
        "feature_drift": {"out_of_training_range_features": []},
        "liquidity_status": "MISSING_DEPTH_OR_ORDER_SIZE",
        "estimated_production_cost": {"production_grade_evidence": False},
        "selected": False,
        "rejection_reasons": ["cost_not_production_grade", "liquidity_missing_depth_or_order_size"],
    }


def test_shadow_supply_artifact_publishes_phase_4_contract_fields() -> None:
    policy = _shadow_policy()
    scored = [
        *[_shadow_scored_row("LONG", idx) for idx in range(30)],
        *[_shadow_scored_row("SHORT", idx) for idx in range(30)],
    ]

    shadow = shadow_supply_artifact(
        policy=policy,
        scored_rows=scored,
        current_source="unit",
        cost_status={"production_grade_cost_coverage": 0.0},
        drift_status={"high_drift_features_current_runtime": []},
    )
    audit = shadow_supply_contract_audit(policy=policy, shadow_status=shadow)

    assert len(shadow["top_25_long_candidates"]) == 25
    assert len(shadow["top_25_short_candidates"]) == 25
    assert shadow["top_25_long_candidates"] == shadow["top_long"]
    assert shadow["top_25_short_candidates"] == shadow["top_short"]
    assert shadow["total_scored_rows"] == 60
    assert shadow["total_rows_scored"] == 60
    assert shadow["current_rows_scored"] == 60
    assert shadow["scored_current_valid_rows"] == 60
    assert shadow["valid_rows_scored"] == 60
    assert shadow["total_current_valid_rows"] == 60
    assert shadow["current_valid_rows"] == 60
    assert shadow["total_shadow_scored_rows"] == 60
    assert shadow["unscored_current_valid_rows"] == 0
    assert shadow["shadow_scoring_coverage"] == 1.0
    assert shadow["score_every_current_valid_row_contract"] == {
        "total_current_valid_rows": 60,
        "total_scored_rows": 60,
        "unscored_current_valid_rows": 0,
        "shadow_scoring_coverage": 1.0,
        "scored_rows_equal_current_valid_rows": True,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    assert shadow["qualified_economic_candidates"] == 0
    assert shadow["selected_rows"] == 0
    assert shadow["rejected_rows"] == 60
    assert shadow["rejection_reason_counts"] == {
        "cost_not_production_grade": 60,
        "liquidity_missing_depth_or_order_size": 60,
    }
    assert shadow["liquidity_status_counts"] == {"MISSING_DEPTH_OR_ORDER_SIZE": 60}
    assert shadow["paper_fill_allowed"] is False
    assert shadow["routes_to_live"] is False
    assert shadow["places_real_order"] is False
    assert shadow["counts_as_a_grade_evidence"] is False
    assert shadow["promotion_evidence"] is False
    assert shadow["top_25_long_candidates"][0]["predicted_gross_edge_bps"] == 62.0
    assert shadow["top_25_long_candidates"][0]["production_cost_bps"] == 12.0
    assert shadow["top_25_long_candidates"][0]["predicted_net_edge_bps"] == 50.0
    assert shadow["top_25_long_candidates"][0]["threshold_distance_bps"] == 30.0
    assert shadow["top_25_long_candidates"][0]["feature_drift"] == {"out_of_training_range_features": []}
    assert shadow["top_25_long_candidates"][0]["liquidity_status"] == "MISSING_DEPTH_OR_ORDER_SIZE"
    assert shadow["top_25_long_candidates"][0]["rejection_reason"] == "cost_not_production_grade"
    assert shadow["top_25_long_candidates"][0]["paper_fill_allowed"] is False
    assert shadow["top_25_long_candidates"][0]["routes_to_live"] is False
    assert shadow["top_25_long_candidates"][0]["places_real_order"] is False
    assert shadow["top_25_long_candidates"][0]["counts_as_a_grade_evidence"] is False
    assert shadow["top_25_long_candidates"][0]["promotion_evidence"] is False
    assert audit["status"] == "PASS_SHADOW_SUPPLY_CONTRACT"
    assert audit["score_every_current_valid_row"] is True
    assert audit["total_candidates"] == 60
    assert audit["total_rows_scored"] == 60
    assert audit["current_rows_scored"] == 60
    assert audit["scored_current_valid_rows"] == 60
    assert audit["valid_rows_scored"] == 60
    assert audit["total_current_valid_rows"] == 60
    assert audit["current_valid_rows"] == 60
    assert audit["total_shadow_scored_rows"] == 60
    assert audit["unscored_current_valid_rows"] == 0
    assert audit["shadow_scoring_coverage"] == 1.0
    assert audit["score_every_current_valid_row_contract"]["scored_rows_equal_current_valid_rows"] is True
    assert audit["qualified_economic_candidates"] == 0
    assert audit["selected_rows"] == 0
    assert audit["rejected_rows"] == 60
    assert audit["rejection_reason_counts"] == shadow["rejection_reason_counts"]
    assert audit["liquidity_status_counts"] == shadow["liquidity_status_counts"]
    assert audit["top_25_long_candidates"] == shadow["top_25_long_candidates"]
    assert audit["top_25_short_candidates"] == shadow["top_25_short_candidates"]
    assert audit["top_long_count"] == 25
    assert audit["top_short_count"] == 25
    assert audit["top_25_long_count"] == audit["top_long_count"]
    assert audit["top_25_short_count"] == audit["top_short_count"]
    assert len(audit["top_25_long_candidate_hashes"]) == 25
    assert len(audit["top_25_short_candidate_hashes"]) == 25
    assert len(set(audit["published_candidate_row_hashes"])) == 50
    assert audit["pass_conditions"]["top_25_long_candidates_published"] is True
    assert audit["pass_conditions"]["top_25_short_candidates_published"] is True
    assert audit["pass_conditions"]["top_25_candidate_rows_mirrored_in_contract"] is True
    assert audit["pass_conditions"]["current_valid_and_scored_row_counts_reported"] is True
    assert audit["pass_conditions"]["scored_all_current_valid_rows"] is True
    assert audit["pass_conditions"]["unscored_current_valid_rows_eq_0"] is True
    assert audit["pass_conditions"]["shadow_scoring_coverage_eq_1"] is True
    assert audit["pass_conditions"]["required_edge_cost_drift_liquidity_fields_present"] is True
    assert audit["pass_conditions"]["artifact_places_real_order_false"] is True
    assert audit["pass_conditions"]["artifact_promotion_evidence_false"] is True
    assert audit["places_real_order"] is False
    assert audit["promotion_evidence"] is False


def test_shadow_supply_contract_audit_fails_unscored_current_valid_rows() -> None:
    policy = _shadow_policy()
    scored = [
        *[_shadow_scored_row("LONG", idx) for idx in range(25)],
        *[_shadow_scored_row("SHORT", idx) for idx in range(25)],
    ]
    shadow = shadow_supply_artifact(
        policy=policy,
        scored_rows=scored,
        current_source="unit",
        cost_status={"production_grade_cost_coverage": 0.0},
        drift_status={"high_drift_features_current_runtime": []},
    )
    shadow["total_current_valid_rows"] = 51
    shadow["current_valid_rows"] = 51

    audit = shadow_supply_contract_audit(policy=policy, shadow_status=shadow)

    assert audit["status"] == "FAIL_SHADOW_SUPPLY_CONTRACT"
    assert audit["total_scored_rows"] == 50
    assert audit["total_current_valid_rows"] == 51
    assert audit["unscored_current_valid_rows"] == 1
    assert audit["shadow_scoring_coverage"] == 50 / 51
    assert audit["score_every_current_valid_row_contract"]["scored_rows_equal_current_valid_rows"] is False
    assert audit["pass_conditions"]["scored_all_current_valid_rows"] is False
    assert audit["pass_conditions"]["unscored_current_valid_rows_eq_0"] is False
    assert audit["pass_conditions"]["shadow_scoring_coverage_eq_1"] is False


def test_shadow_supply_contract_audit_fails_missing_required_row_field() -> None:
    policy = _shadow_policy()
    scored = [
        *[_shadow_scored_row("LONG", idx) for idx in range(25)],
        *[_shadow_scored_row("SHORT", idx) for idx in range(25)],
    ]
    shadow = shadow_supply_artifact(
        policy=policy,
        scored_rows=scored,
        current_source="unit",
        cost_status={"production_grade_cost_coverage": 0.0},
        drift_status={"high_drift_features_current_runtime": []},
    )
    shadow["top_25_long_candidates"][0]["production_cost_bps"] = None

    audit = shadow_supply_contract_audit(policy=policy, shadow_status=shadow)

    assert audit["status"] == "FAIL_SHADOW_SUPPLY_CONTRACT"
    assert audit["missing_required_row_field_counts"] == {"production_cost_bps": 1}
    assert audit["pass_conditions"]["required_edge_cost_drift_liquidity_fields_present"] is False
    assert audit["paper_fill_allowed"] is False
    assert audit["routes_to_live"] is False
    assert audit["places_real_order"] is False
    assert audit["counts_as_a_grade_evidence"] is False
    assert audit["promotion_evidence"] is False


def test_paper_binding_identity_preflight_passes_clean_prelockbox_state() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    rows = [
        {
            "_paper_binding_source_key": "v2:paper:intents",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "model_id": "old-policy",
            "paper_fill_allowed": False,
            "places_real_order": False,
            "live_order": False,
        }
    ]

    payload = paper_binding_identity_preflight_from_rows(
        policy=policy,
        rows=rows,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
        lockbox_perf={"pass": False},
        source_counts={"v2:paper:intents": 1},
    )

    assert payload["status"] == "PASS_PRELOCKBOX_NO_BINDING_LEAKS"
    assert payload["candidate_identity_complete_rows"] == 0
    assert payload["partial_challenger_identity_rows"] == 0
    assert payload["live_route_violation_rows"] == 0
    assert payload["paper_binding_allowed"] is False
    assert payload["old_policy_silent_control_ruled_out_for_candidate"] is True
    assert payload["source_counts"] == {"v2:paper:intents": 1}
    assert payload["redis_scan_source_counts"] == {"v2:paper:intents": 1}
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_paper_binding_identity_preflight_detects_partial_challenger_identity() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    rows = [
        {
            "_paper_binding_source_key": "v2:paper:intents",
            "candidate_id": "challenger_v2_test",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "paper_fill_allowed": False,
            "places_real_order": False,
            "live_order": False,
        }
    ]

    payload = paper_binding_identity_preflight_from_rows(
        policy=policy,
        rows=rows,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
        lockbox_perf={"pass": False},
    )

    assert payload["status"] == "FAIL_PAPER_BINDING_IDENTITY_PREFLIGHT"
    assert payload["candidate_identity_complete_rows"] == 0
    assert payload["partial_challenger_identity_rows"] == 1
    assert payload["old_policy_silent_credit_risk_rows"] == 1
    assert payload["pass_conditions"]["no_partial_challenger_identity_rows"] is False


def test_paper_canary_binding_readiness_blocks_until_cost_and_lockbox_pass() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = paper_canary_binding_readiness_artifact(
        policy=policy,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE", "production_grade_cost_coverage": 0.0},
        lockbox_perf={
            "status": "BLOCKED_LOCKBOX_PASS_CONDITIONS_NOT_MET",
            "pass": False,
            "selected_economic_candidates": 0,
            "point_in_time_violations": 0,
        },
        paper_binding_preflight={
            "status": "PASS_PRELOCKBOX_NO_BINDING_LEAKS",
            "candidate_identity_complete_rows": 0,
            "partial_challenger_identity_rows": 0,
            "live_route_violation_rows": 0,
            "pass_conditions": {
                "no_candidate_bound_rows_before_lockbox_pass": True,
                "no_partial_challenger_identity_rows": True,
                "no_routes_to_live": True,
            },
        },
        paper_cost_telemetry={
            "paper_telemetry_production_grade_rows": 36,
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 36,
            "production_grade_identity_missing_counts": {
                "candidate_id": 36,
                "policy_fingerprint": 36,
                "model_source": 36,
            },
        },
    )

    assert payload["status"] == "BLOCKED_PAPER_CANARY_BINDING_NOT_READY"
    assert payload["binding_allowed"] is False
    assert payload["paper_canary_binding_allowed"] is False
    assert payload["paper_binding_ready"] is False
    assert payload["paper_chain_ready"] is False
    assert "production_grade_cost_evidence_passed" in payload["blocked_reasons"]
    assert "blind_lockbox_passed" in payload["blocked_reasons"]
    assert "no_routes_to_live" not in payload["blocked_reasons"]
    assert payload["paper_binding_prerequisites_satisfied"] is False
    assert payload["prerequisites_satisfied"] is False
    assert payload["paper_binding_blocked_until"] == payload["blocked_reasons"]
    assert payload["actuals"]["production_grade_cost_evidence_passed"] == "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"
    assert payload["required"]["production_grade_cost_evidence_passed"] == "PASS"
    assert payload["sample_blockers"] == list(payload["failed_binding_prerequisite_details"].values())[:25]
    assert payload["paper_cost_telemetry_readiness_status"] is None
    assert payload["binding_prerequisite_details"]["production_grade_cost_evidence_passed"] == {
        "passed": False,
        "observed": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
        "required": "PASS",
    }
    assert payload["binding_prerequisite_details"]["blind_lockbox_passed"] == {
        "passed": False,
        "observed": "BLOCKED_LOCKBOX_PASS_CONDITIONS_NOT_MET",
        "required": "PASS",
    }
    assert payload["chain_prerequisite_details"] == payload["binding_prerequisite_details"]
    assert payload["binding_blocker_details"] == payload["binding_prerequisite_details"]
    assert payload["blocker_details"] == payload["failed_binding_blocker_details"]
    assert payload["failed_blocker_details"] == payload["failed_binding_blocker_details"]
    assert payload["failed_binding_blocker_details"]["production_grade_cost_evidence_passed"] == payload[
        "binding_prerequisite_details"
    ]["production_grade_cost_evidence_passed"]
    assert payload["failed_binding_prerequisite_details"] == payload["failed_binding_blocker_details"]
    assert payload["paper_canary_chain_declared"] is True
    assert payload["required_chain_components"] == 10
    assert payload["required_chain_links"] == payload["paper_canary_chain"]
    assert payload["old_policy_rows_count_as_challenger_evidence"] is False
    assert payload["required_paper_record_identity_fields"] == [
        "candidate_id",
        "policy_fingerprint",
        "model_source",
    ]
    assert payload["required_identity_fields"] == payload["required_paper_record_identity_fields"]
    assert payload["paper_record_identity_fields"] == payload["required_paper_record_identity_fields"]
    assert payload["paper_record_identity_contract_declared"] is True
    assert payload["paper_record_identity_contract"]["candidate_id"] == "challenger_v2_test"
    assert payload["paper_record_identity_contract"]["policy_fingerprint"] == "fingerprint"
    assert payload["paper_record_identity_contract"]["model_source"] == "test_model"
    assert payload["paper_record_identity_contract"]["all_fields_required_on_every_paper_record"] is True
    assert payload["paper_record_identity_contract"]["old_policy_rows_count_as_challenger_evidence"] is False
    assert payload["credit_attribution_contract"] == payload["paper_record_identity_contract"]
    assert payload["identity_complete_rows"] == 0
    assert payload["partial_identity_rows"] == 0
    assert payload["credit_attribution_contract"]["old_policy_rows_count_as_challenger_evidence"] is False
    assert payload["old_policy_credit_prevention_status"] == "PASS_OLD_POLICY_ROWS_CANNOT_RECEIVE_CHALLENGER_CREDIT"
    assert payload["identity_ready"] is False
    assert payload["signal_ready"] is False
    assert payload["strategy_ready"] is False
    assert payload["adaptive_allocator_ready"] is False
    assert payload["risk_ready"] is False
    assert payload["orchestrator_ready"] is False
    assert payload["paper_lifecycle_ready"] is False
    assert payload["exit_ready"] is False
    assert payload["pnl_ready"] is False
    assert payload["trainer_feedback_ready"] is False
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False


def test_paper_canary_binding_readiness_allows_operator_review_after_gates_pass() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = paper_canary_binding_readiness_artifact(
        policy=policy,
        cost_status={"status": "PASS", "production_grade_cost_coverage": 0.96},
        lockbox_perf={
            "status": "PASS",
            "pass": True,
            "selected_economic_candidates": 300,
            "point_in_time_violations": 0,
        },
        paper_binding_preflight={
            "status": "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT",
            "candidate_identity_complete_rows": 0,
            "partial_challenger_identity_rows": 0,
            "live_route_violation_rows": 0,
            "pass_conditions": {
                "no_candidate_bound_rows_before_lockbox_pass": True,
                "no_partial_challenger_identity_rows": True,
                "no_routes_to_live": True,
            },
        },
        paper_cost_telemetry={
            "paper_telemetry_production_grade_rows": 36,
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 36,
        },
    )

    assert payload["status"] == "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT"
    assert payload["binding_allowed"] is True
    assert payload["paper_canary_binding_allowed"] is True
    assert payload["blocked_reasons"] == []
    assert payload["paper_binding_prerequisites_satisfied"] is True
    assert payload["prerequisites_satisfied"] is True
    assert all(detail["passed"] is True for detail in payload["binding_prerequisite_details"].values())
    assert payload["binding_blocker_details"] == payload["binding_prerequisite_details"]
    assert payload["failed_binding_blocker_details"] == {}
    assert payload["failed_binding_prerequisite_details"] == {}
    assert payload["paper_record_identity_contract"]["all_fields_required_on_every_paper_record"] is True
    assert payload["old_policy_rows_count_as_challenger_evidence"] is False
    assert payload["paper_canary_chain"][0] == "challenger"
    assert payload["paper_canary_chain"][-1] == "trainer_feedback"
    assert payload["required_chain_links"] == payload["paper_canary_chain"]
    assert payload["identity_ready"] is True
    assert payload["signal_ready"] is True
    assert payload["strategy_ready"] is True
    assert payload["adaptive_allocator_ready"] is True
    assert payload["risk_ready"] is True
    assert payload["orchestrator_ready"] is True
    assert payload["paper_lifecycle_ready"] is True
    assert payload["exit_ready"] is True
    assert payload["pnl_ready"] is True
    assert payload["trainer_feedback_ready"] is True


def test_paper_chain_binding_readiness_blocks_with_full_chain_declared() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = paper_chain_binding_readiness_audit(
        policy=policy,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
        lockbox_pass_contract={"status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"},
        paper_canary_binding={
            "status": "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
            "binding_allowed": False,
            "required_paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
            "old_policy_rows_count_as_challenger_evidence": False,
            "routes_to_live": False,
            "places_real_order": False,
        },
        forward_canary_contract={
            "status": "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
            "closed_challenger_economic_outcomes": 0,
            "live_route_rows": 0,
        },
    )

    assert payload["status"] == "BLOCKED_PAPER_CHAIN_BINDING_NOT_READY"
    assert payload["ready"] is False
    assert payload["binding_allowed"] is False
    assert payload["chain_binding_allowed"] is False
    assert payload["paper_canary_binding_allowed"] is False
    assert payload["chain_ready"] is False
    assert payload["paper_chain_ready"] is False
    assert payload["required_components"] == 10
    assert payload["complete_components"] == 0
    assert payload["incomplete_components"] == 10
    assert payload["missing_component_count"] == 10
    assert payload["missing_or_blocked_chain_components_count"] == 10
    assert payload["chain_component_shortfall_to_required"] == 10
    assert payload["component_shortfall_to_required"] == 10
    assert payload["minimum_paper_chain_binding_evidence"] == {
        "required_chain_declared": payload["required_chain"],
        "required_components": 10,
        "complete_components": 10,
        "missing_component_count": 0,
        "paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
        "production_grade_cost_evidence_status": "PASS",
        "blind_lockbox_pass_contract_status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "paper_canary_binding_allowed": True,
        "old_policy_rows_count_as_challenger_evidence": False,
        "routes_to_live": False,
        "places_real_order": False,
        "forward_canary_live_route_rows": 0,
        "forward_challenger_outcomes_before_binding": 0,
    }
    assert payload["minimum_paper_chain_binding_observed"] == {
        "required_chain_declared": payload["required_chain"],
        "required_components": 10,
        "complete_components": 0,
        "missing_component_count": 10,
        "paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
        "production_grade_cost_evidence_status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
        "blind_lockbox_pass_contract_status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT",
        "paper_canary_binding_allowed": False,
        "old_policy_rows_count_as_challenger_evidence": False,
        "routes_to_live": False,
        "places_real_order": False,
        "forward_canary_live_route_rows": 0,
        "forward_challenger_outcomes_before_binding": 0,
    }
    assert payload["minimum_paper_chain_binding_shortfalls"] == {
        "required_chain_declared": 0,
        "required_components": 0,
        "complete_components": 10,
        "missing_component_count": 10,
        "paper_record_identity_fields": 0,
        "production_grade_cost_evidence_status": 1,
        "blind_lockbox_pass_contract_status": 1,
        "paper_canary_binding_allowed": 1,
        "old_policy_rows_count_as_challenger_evidence": 0,
        "routes_to_live": 0,
        "places_real_order": 0,
        "forward_canary_live_route_rows": 0,
        "forward_challenger_outcomes_before_binding": 0,
    }
    assert payload["minimum_paper_chain_binding_pass_conditions"] == payload["pass_conditions"]
    assert payload["actuals"] == payload["minimum_paper_chain_binding_observed"]
    assert payload["required"] == payload["minimum_paper_chain_binding_evidence"]
    assert payload["sample_blockers"] == list(payload["failed_binding_blocker_details"].values())[:25]
    assert payload["missing_component_names"] == [
        "challenger",
        "signal",
        "strategy",
        "adaptive_allocator",
        "risk",
        "orchestrator",
        "paper_lifecycle",
        "exit",
        "pnl",
        "trainer_feedback",
    ]
    assert len(payload["missing_or_blocked_components"]) == 10
    assert payload["required_chain"] == [
        "challenger",
        "signal",
        "strategy",
        "adaptive_allocator",
        "risk",
        "orchestrator",
        "paper_lifecycle",
        "exit",
        "pnl",
        "trainer_feedback",
    ]
    assert payload["required_chain_links"] == payload["required_chain"]
    assert len(payload["chain_components"]) == 10
    assert payload["component_readiness"] == payload["chain_components"]
    assert payload["chain_link_readiness"] == payload["chain_components"]
    assert set(payload["component_statuses"]) == set(payload["required_chain"])
    assert payload["component_statuses"]["challenger"] == "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS"
    assert payload["chain_components"][0]["component"] == "challenger"
    assert payload["chain_components"][-1]["component"] == "trainer_feedback"
    assert payload["chain_components"][0]["must_emit_or_preserve_identity_fields"] == [
        "candidate_id",
        "policy_fingerprint",
        "model_source",
    ]
    assert payload["paper_record_identity_fields"] == payload["required_paper_record_identity_fields"]
    assert "production_grade_cost_evidence_passed" in payload["blocked_reasons"]
    assert "blind_lockbox_passed" in payload["blocked_reasons"]
    assert payload["chain_prerequisite_details"]["production_grade_cost_evidence_passed"] == {
        "passed": False,
        "observed": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
        "required": "PASS",
    }
    assert payload["chain_prerequisite_details"]["paper_canary_binding_allowed"] == {
        "passed": False,
        "observed": False,
        "required": True,
    }
    assert payload["binding_blocker_details"] == payload["chain_prerequisite_details"]
    assert payload["blocker_details"] == payload["failed_binding_blocker_details"]
    assert payload["failed_blocker_details"] == payload["failed_binding_blocker_details"]
    assert payload["failed_binding_blocker_details"]["production_grade_cost_evidence_passed"] == payload["chain_prerequisite_details"][
        "production_grade_cost_evidence_passed"
    ]
    assert payload["pass_conditions"]["all_chain_components_have_identity_contract"] is True
    assert payload["old_policy_rows_count_as_challenger_evidence"] is False
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_paper_chain_binding_readiness_allows_operator_review_when_gates_pass() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = paper_chain_binding_readiness_audit(
        policy=policy,
        cost_status={"status": "PASS"},
        lockbox_pass_contract={"status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT"},
        paper_canary_binding={
            "status": "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT",
            "binding_allowed": True,
            "required_paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
            "old_policy_rows_count_as_challenger_evidence": False,
            "routes_to_live": False,
            "places_real_order": False,
        },
        forward_canary_contract={
            "status": "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
            "closed_challenger_economic_outcomes": 0,
            "live_route_rows": 0,
        },
    )

    assert payload["status"] == "READY_FOR_OPERATOR_REVIEW_PAPER_CHAIN_BINDING"
    assert payload["ready"] is True
    assert payload["binding_allowed"] is True
    assert payload["chain_binding_allowed"] is True
    assert payload["paper_canary_binding_allowed"] is True
    assert payload["chain_ready"] is True
    assert payload["paper_chain_ready"] is True
    assert payload["required_components"] == 10
    assert payload["complete_components"] == 10
    assert payload["incomplete_components"] == 0
    assert payload["component_readiness"] == payload["chain_components"]
    assert payload["chain_link_readiness"] == payload["chain_components"]
    assert payload["required_chain_links"] == payload["required_chain"]
    assert payload["paper_record_identity_fields"] == payload["required_paper_record_identity_fields"]
    assert set(payload["component_statuses"]) == set(payload["required_chain"])
    assert all(status == "READY_FOR_OPERATOR_REVIEW_BINDING" for status in payload["component_statuses"].values())
    assert payload["blocker_details"] == {}
    assert payload["failed_binding_blocker_details"] == {}
    assert payload["failed_blocker_details"] == {}
    assert payload["missing_component_count"] == 0
    assert payload["missing_or_blocked_chain_components_count"] == 0
    assert payload["chain_component_shortfall_to_required"] == 0
    assert payload["component_shortfall_to_required"] == 0
    assert payload["actuals"] == payload["minimum_paper_chain_binding_observed"]
    assert payload["required"] == payload["minimum_paper_chain_binding_evidence"]
    assert payload["sample_blockers"] == []
    assert payload["minimum_paper_chain_binding_observed"]["complete_components"] == 10
    assert payload["minimum_paper_chain_binding_observed"]["missing_component_count"] == 0
    assert payload["minimum_paper_chain_binding_observed"]["production_grade_cost_evidence_status"] == "PASS"
    assert payload["minimum_paper_chain_binding_observed"]["blind_lockbox_pass_contract_status"] == (
        "PASS_BLIND_LOCKBOX_PASS_CONTRACT"
    )
    assert payload["minimum_paper_chain_binding_observed"]["paper_canary_binding_allowed"] is True
    assert payload["minimum_paper_chain_binding_shortfalls"] == {
        "required_chain_declared": 0,
        "required_components": 0,
        "complete_components": 0,
        "missing_component_count": 0,
        "paper_record_identity_fields": 0,
        "production_grade_cost_evidence_status": 0,
        "blind_lockbox_pass_contract_status": 0,
        "paper_canary_binding_allowed": 0,
        "old_policy_rows_count_as_challenger_evidence": 0,
        "routes_to_live": 0,
        "places_real_order": 0,
        "forward_canary_live_route_rows": 0,
        "forward_challenger_outcomes_before_binding": 0,
    }
    assert payload["minimum_paper_chain_binding_pass_conditions"] == payload["pass_conditions"]
    assert payload["missing_component_names"] == []
    assert payload["missing_or_blocked_components"] == []
    assert payload["blocked_reasons"] == []
    assert all(detail["passed"] is True for detail in payload["chain_prerequisite_details"].values())
    assert all(payload["pass_conditions"].values())
    assert all(component["status"] == "READY_FOR_OPERATOR_REVIEW_BINDING" for component in payload["chain_components"])


def test_paper_challenger_credit_attribution_guard_passes_prebinding_quarantine() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = paper_challenger_credit_attribution_guard(
        policy=policy,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
        lockbox_pass_contract={"status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"},
        paper_binding_preflight={
            "status": "PASS_PRELOCKBOX_NO_BINDING_LEAKS",
            "candidate_identity_complete_rows": 0,
            "partial_challenger_identity_rows": 0,
            "candidate_bound_rows_before_lockbox_pass": 0,
            "pass_conditions": {
                "no_candidate_bound_rows_before_lockbox_pass": True,
                "no_partial_challenger_identity_rows": True,
                "no_routes_to_live": True,
            },
        },
        paper_cost_telemetry={
            "status": "BLOCKED_CHALLENGER_IDENTITY_MISSING_FOR_COST_TELEMETRY",
            "paper_rows_scanned": 10,
            "paper_telemetry_production_grade_rows": 5,
            "candidate_identity_complete_production_grade_rows": 0,
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 5,
            "paper_fill_allowed_rows": 2,
            "sample_production_grade_identity_gap_rows": [{"snapshot_id": "old-policy"}],
            "source_group_readiness": {
                "paper_ledger": {
                    "rows": 10,
                    "production_grade_rows": 5,
                    "challenger_bound_production_grade_rows": 0,
                    "old_policy_or_unbound_production_grade_rows": 5,
                    "paper_fill_allowed_rows": 2,
                    "blocked_reasons": ["challenger_bound_production_grade_rows_gt_0"],
                }
            },
        },
        paper_canary_binding={
            "status": "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
            "binding_allowed": False,
            "required_paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
            "old_policy_rows_count_as_challenger_evidence": False,
            "routes_to_live": False,
            "places_real_order": False,
        },
        forward_canary_contract={
            "status": "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
            "paper_rows_scanned": 10,
            "closed_challenger_economic_outcomes": 0,
            "excluded_row_counts": {"challenger_identity_not_complete": 10},
            "live_route_rows": 0,
        },
    )

    assert payload["status"] == "PASS_PREBINDING_CHALLENGER_CREDIT_ATTRIBUTION_GUARD"
    assert payload["blocked_reasons"] == []
    assert payload["credit_attribution_guard_passed"] is True
    assert payload["old_policy_or_unbound_production_grade_rows_quarantined"] == 5
    assert payload["old_unbound_rows_quarantined"] == 5
    assert payload["rows_scanned"] == 10
    assert payload["scanned_rows"] == 10
    assert payload["total_rows_scanned"] == 10
    assert payload["candidate_bound_rows"] == 0
    assert payload["old_policy_or_unbound_rows_quarantined"] == 10
    assert payload["identity_incomplete_rows"] == 10
    assert payload["non_counting_row_count"] == 10
    assert payload["paper_fill_allowed_rows_quarantined"] == 2
    assert payload["required_identity_fields"] == ["candidate_id", "policy_fingerprint", "model_source"]
    assert payload["old_policy_rows_count_as_challenger_evidence"] is False
    assert payload["forward_identity_excluded_rows"] == 10
    assert payload["forward_canary_old_policy_rows_excluded_by_identity"] is True
    assert payload["sample_old_or_unbound_rows"] == [{"snapshot_id": "old-policy"}]
    assert payload["credit_attribution_contract"]["forward_rows_without_complete_identity_count_as_challenger_evidence"] is False
    assert payload["forward_canary_excluded_row_counts"] == {"challenger_identity_not_complete": 10}
    assert payload["paper_cost_source_group_credit_summary"]["paper_ledger"]["old_policy_or_unbound_production_grade_rows"] == 5
    assert payload["source_group_credit_summary"] == payload["paper_cost_source_group_credit_summary"]
    assert payload["actuals"]["paper_fill_allowed_rows_not_counted_as_challenger_evidence"] == {
        "paper_fill_allowed_rows": 2,
        "challenger_bound_production_grade_rows": 0,
    }
    assert payload["required"]["old_policy_rows_count_as_challenger_evidence_false"] is False
    assert payload["failed_blocker_details"] == {}
    assert payload["sample_blockers"] == []
    assert all(payload["pass_conditions"].values())
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["promotion_evidence"] is False


def test_paper_challenger_credit_attribution_guard_fails_if_old_policy_credit_allowed() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = paper_challenger_credit_attribution_guard(
        policy=policy,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
        lockbox_pass_contract={"status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"},
        paper_binding_preflight={
            "status": "PASS_PRELOCKBOX_NO_BINDING_LEAKS",
            "pass_conditions": {
                "no_candidate_bound_rows_before_lockbox_pass": True,
                "no_partial_challenger_identity_rows": True,
                "no_routes_to_live": True,
            },
        },
        paper_cost_telemetry={
            "challenger_bound_production_grade_rows": 0,
            "candidate_identity_complete_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 1,
            "paper_fill_allowed_rows": 0,
        },
        paper_canary_binding={
            "binding_allowed": True,
            "required_paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
            "old_policy_rows_count_as_challenger_evidence": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        forward_canary_contract={
            "paper_rows_scanned": 1,
            "closed_challenger_economic_outcomes": 1,
            "excluded_row_counts": {},
            "live_route_rows": 0,
        },
    )

    assert payload["status"] == "FAIL_CHALLENGER_CREDIT_ATTRIBUTION_GUARD"
    assert payload["credit_attribution_guard_passed"] is False
    assert "old_policy_rows_count_as_challenger_evidence_false" in payload["blocked_reasons"]
    assert "binding_disallowed_until_cost_and_lockbox_pass" in payload["blocked_reasons"]
    assert payload["pass_conditions"]["forward_canary_has_no_challenger_outcomes_while_binding_blocked"] is True
    assert payload["actuals"]["old_policy_rows_count_as_challenger_evidence_false"] is True
    assert payload["required"]["old_policy_rows_count_as_challenger_evidence_false"] is False
    assert payload["sample_blockers"] == list(payload["failed_blocker_details"].values())[:25]


def test_forward_paper_canary_contract_blocks_before_binding_and_outcomes() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = forward_paper_canary_pass_contract_audit_from_rows(
        policy=policy,
        rows=[],
        paper_canary_binding={
            "status": "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
            "binding_allowed": False,
        },
        lockbox_pass_contract={"status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"},
    )

    assert payload["status"] == "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT"
    assert payload["closed_challenger_economic_outcomes"] == 0
    assert payload["paper_rows_scanned"] == 0
    assert payload["scanned_rows"] == 0
    assert payload["total_rows_scanned"] == 0
    assert payload["candidate_bound_rows"] == 0
    assert payload["old_policy_or_unbound_rows_quarantined"] == 0
    assert payload["identity_incomplete_rows"] == 0
    assert payload["non_counting_row_count"] == 0
    assert payload["pass_conditions"]["paper_canary_binding_allowed"] is False
    assert payload["pass_conditions"]["paper_canary_start_time_present"] is False
    assert payload["pass_conditions"]["new_closed_challenger_economic_outcomes_gte_100"] is False
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["required_identity_fields"] == ["candidate_id", "policy_fingerprint", "model_source"]
    assert payload["required_new_closed_challenger_economic_outcomes"] == 100
    assert payload["required_closed_challenger_economic_outcomes"] == 100
    assert payload["minimum_forward_canary_evidence"] == {
        "paper_canary_binding_allowed": True,
        "paper_canary_start_time": "present",
        "blind_lockbox_pass_contract_status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
        "new_closed_challenger_economic_outcomes": ">=100",
        "symbols": ">=30",
        "long_candidates": ">0",
        "short_candidates": ">0",
        "after_cost_expectancy_bps": ">0",
        "profit_factor": ">=1.5",
        "accounting_mismatch_rows": 0,
        "accounting_evidence_missing_rows": 0,
        "liquidation_rows": 0,
        "point_in_time_violations": 0,
        "live_route_rows": 0,
    }
    assert payload["minimum_forward_canary_observed"] == {
        "paper_canary_binding_allowed": False,
        "paper_canary_start_time": None,
        "blind_lockbox_pass_contract_status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT",
        "new_closed_challenger_economic_outcomes": 0,
        "symbols": 0,
        "long_candidates": 0,
        "short_candidates": 0,
        "after_cost_expectancy_bps": None,
        "profit_factor": None,
        "accounting_mismatch_rows": 0,
        "accounting_evidence_missing_rows": 0,
        "liquidation_rows": 0,
        "point_in_time_violations": 0,
        "live_route_rows": 0,
    }
    assert payload["minimum_forward_canary_shortfalls"] == {
        "paper_canary_binding_allowed": 1,
        "paper_canary_start_time": 1,
        "blind_lockbox_pass_contract_status": 1,
        "new_closed_challenger_economic_outcomes": 100,
        "symbols": 30,
        "long_candidates": 1,
        "short_candidates": 1,
        "after_cost_expectancy_bps": None,
        "profit_factor": None,
        "accounting_mismatch_rows": 0,
        "accounting_evidence_missing_rows": None,
        "liquidation_rows": 0,
        "point_in_time_violations": 0,
        "live_route_rows": 0,
    }
    assert payload["minimum_forward_canary_pass_conditions"] == payload["pass_conditions"]
    assert payload["actuals"] == payload["minimum_forward_canary_observed"]
    assert payload["required"] == payload["minimum_forward_canary_evidence"]
    assert payload["closed_outcome_shortfall_to_100"] == 100
    assert payload["closed_challenger_economic_outcome_shortfall"] == 100
    assert payload["closed_challenger_economic_outcome_shortfall_to_100"] == 100
    assert payload["closed_challenger_economic_outcome_shortfall_to_required"] == 100
    assert payload["new_closed_challenger_economic_outcome_shortfall_to_required"] == 100
    assert payload["new_closed_challenger_economic_outcomes_shortfall_to_100"] == 100
    assert payload["required_symbols"] == 30
    assert payload["symbol_count"] == 0
    assert payload["symbol_shortfall_to_30"] == 30
    assert payload["long_candidates"] == 0
    assert payload["short_candidates"] == 0
    assert payload["long_candidate_shortfall_to_1"] == 1
    assert payload["short_candidate_shortfall_to_1"] == 1
    assert payload["liquidation_events"] == 0
    assert payload["canary_counting_evidence_allowed"] is False
    assert payload["counting_evidence_allowed"] is False
    assert payload["available_metric_count"] == 0
    assert payload["unavailable_metric_count"] == 3
    assert payload["metric_availability"]["after_cost_expectancy_bps"] == {
        "available": False,
        "observed": None,
        "unavailable_reasons": [
            "blind_lockbox_pass_contract_not_passed",
            "no_closed_challenger_economic_outcomes",
            "paper_canary_binding_not_allowed",
            "paper_canary_start_time_missing",
        ],
    }
    assert payload["unavailable_metric_reasons"]["profit_factor"] == [
        "blind_lockbox_pass_contract_not_passed",
        "no_closed_challenger_economic_outcomes",
        "paper_canary_binding_not_allowed",
        "paper_canary_start_time_missing",
    ]
    assert payload["outcome_count_by_direction"] == {"LONG": 0, "SHORT": 0}
    assert payload["candidate_count_by_direction"] == {"LONG": 0, "SHORT": 0}
    assert payload["expectancy_after_cost"] is None
    assert "new_closed_challenger_economic_outcomes_gte_100" in payload["blocked_reasons"]
    assert "blind_lockbox_pass_contract_passed" in payload["blocked_reasons"]
    assert payload["forward_canary_blocker_details"]["new_closed_challenger_economic_outcomes_gte_100"] == {
        "passed": False,
        "observed": 0,
        "required": ">=100",
        "shortfall": 100,
    }
    assert payload["blocker_details"] == payload["forward_canary_blocker_details"]
    assert payload["failed_forward_canary_blocker_details"]["new_closed_challenger_economic_outcomes_gte_100"] == payload[
        "forward_canary_blocker_details"
    ]["new_closed_challenger_economic_outcomes_gte_100"]
    assert payload["failed_blocker_details"] == payload["failed_forward_canary_blocker_details"]
    assert payload["sample_blockers"] == list(payload["failed_forward_canary_blocker_details"].values())[:25]
    assert payload["sample_failures"] == payload["sample_blockers"]
    assert payload["sample_outcomes"] == payload["sample_closed_challenger_outcomes"]


def test_forward_paper_canary_redis_zero_signal_limit_skips_scan_iter(monkeypatch) -> None:
    class FakeRedisClient:
        def ping(self) -> bool:
            return True

        def get(self, _key: str) -> None:
            return None

        def scan_iter(self, **_kwargs):
            raise AssertionError("scan_iter should not be called when signal_scan_limit is zero")

    class FakeRedisModule:
        @staticmethod
        def Redis(**_kwargs) -> FakeRedisClient:
            return FakeRedisClient()

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = forward_paper_canary_pass_contract_audit_from_redis(
        policy=policy,
        paper_canary_binding={
            "status": "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
            "binding_allowed": False,
        },
        lockbox_pass_contract={"status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"},
        signal_scan_limit=0,
    )

    assert payload["status"] == "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT"
    assert payload["redis_status"] == "READ_REDIS_FORWARD_PAPER_CANARY_ROWS_BOUNDED"
    assert payload["scan_limit_reached"] is True
    assert payload["paper_rows_scanned"] == 0


def test_bounded_paper_signal_scan_zero_limit_skips_scan_iter() -> None:
    class FakeRedisClient:
        def scan_iter(self, **_kwargs):
            raise AssertionError("scan_iter should not be called when signal_scan_limit is zero")

    rows, source_counts, signal_count, scan_limit_reached = bounded_paper_signal_scan(
        FakeRedisClient(),
        signal_scan_limit=0,
        row_reader=lambda _raw, _key: [{"unexpected": True}],
    )

    assert rows == []
    assert dict(source_counts) == {}
    assert signal_count == 0
    assert scan_limit_reached is True


def _closed_canary_row(idx: int) -> dict:
    net_return = 30.0 if idx % 5 else -5.0
    return {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "symbol": f"SYM{idx % 30:02d}USDT",
        "timeframe": ("1m", "5m", "15m", "1h")[idx % 4],
        "decision_time": f"2026-06-{1 + idx % 10:02d}T00:00:00Z",
        "feature_cutoff": f"2026-06-{1 + idx % 10:02d}T00:00:00Z",
        "available_at": f"2026-06-{1 + idx % 10:02d}T00:00:00Z",
        "closed_utc": f"2026-06-{1 + idx % 10:02d}T00:30:00Z",
        "predicted_direction": "LONG" if idx % 2 == 0 else "SHORT",
        "net_return_bps": net_return,
        "accounting_mismatch": False,
        "liquidated": False,
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "live_order": False,
        "_paper_canary_source_key": "unit",
    }


def test_forward_paper_canary_contract_passes_diversified_closed_paper_outcomes() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = forward_paper_canary_pass_contract_audit_from_rows(
        policy=policy,
        rows=[_closed_canary_row(idx) for idx in range(100)],
        paper_canary_binding={
            "status": "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT",
            "binding_allowed": True,
            "paper_canary_started_at": "2026-05-31T23:59:00Z",
        },
        lockbox_pass_contract={"status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT"},
    )

    assert payload["status"] == "PASS_FORWARD_PAPER_CANARY_CONTRACT"
    assert payload["paper_rows_scanned"] == 100
    assert payload["scanned_rows"] == 100
    assert payload["total_rows_scanned"] == 100
    assert payload["candidate_bound_rows"] == 100
    assert payload["old_policy_or_unbound_rows_quarantined"] == 0
    assert payload["identity_incomplete_rows"] == 0
    assert payload["non_counting_row_count"] == 0
    assert payload["closed_challenger_economic_outcomes"] == 100
    assert payload["symbols"] == 30
    assert payload["long_count"] == 50
    assert payload["short_count"] == 50
    assert payload["accounting_mismatch_rows"] == 0
    assert payload["accounting_missing_rows"] == 0
    assert payload["liquidation_rows"] == 0
    assert payload["point_in_time_violations"] == 0
    assert payload["live_route_rows"] == 0
    assert payload["profit_factor"] >= 1.5
    assert payload["required_new_closed_challenger_economic_outcomes"] == 100
    assert payload["required_closed_challenger_economic_outcomes"] == 100
    assert payload["minimum_forward_canary_evidence"]["new_closed_challenger_economic_outcomes"] == ">=100"
    assert payload["minimum_forward_canary_evidence"]["symbols"] == ">=30"
    assert payload["minimum_forward_canary_evidence"]["profit_factor"] == ">=1.5"
    assert payload["minimum_forward_canary_observed"]["paper_canary_binding_allowed"] is True
    assert payload["minimum_forward_canary_observed"]["paper_canary_start_time"] == "2026-05-31T23:59:00Z"
    assert payload["minimum_forward_canary_observed"]["blind_lockbox_pass_contract_status"] == (
        "PASS_BLIND_LOCKBOX_PASS_CONTRACT"
    )
    assert payload["minimum_forward_canary_observed"]["new_closed_challenger_economic_outcomes"] == 100
    assert payload["minimum_forward_canary_observed"]["symbols"] == 30
    assert payload["minimum_forward_canary_observed"]["long_candidates"] == 50
    assert payload["minimum_forward_canary_observed"]["short_candidates"] == 50
    assert payload["minimum_forward_canary_observed"]["after_cost_expectancy_bps"] == payload[
        "after_cost_expectancy_bps"
    ]
    assert payload["minimum_forward_canary_observed"]["profit_factor"] == payload["profit_factor"]
    assert payload["minimum_forward_canary_shortfalls"] == {
        "paper_canary_binding_allowed": 0,
        "paper_canary_start_time": 0,
        "blind_lockbox_pass_contract_status": 0,
        "new_closed_challenger_economic_outcomes": 0,
        "symbols": 0,
        "long_candidates": 0,
        "short_candidates": 0,
        "after_cost_expectancy_bps": 0.0,
        "profit_factor": 0.0,
        "accounting_mismatch_rows": 0,
        "accounting_evidence_missing_rows": 0,
        "liquidation_rows": 0,
        "point_in_time_violations": 0,
        "live_route_rows": 0,
    }
    assert payload["minimum_forward_canary_pass_conditions"] == payload["pass_conditions"]
    assert payload["closed_outcome_shortfall_to_100"] == 0
    assert payload["closed_challenger_economic_outcome_shortfall"] == 0
    assert payload["closed_challenger_economic_outcome_shortfall_to_required"] == 0
    assert payload["new_closed_challenger_economic_outcomes_shortfall_to_100"] == 0
    assert payload["new_closed_challenger_economic_outcome_shortfall_to_required"] == 0
    assert payload["symbol_count"] == 30
    assert payload["symbol_shortfall_to_30"] == 0
    assert payload["long_candidates"] == 50
    assert payload["short_candidates"] == 50
    assert payload["long_candidate_shortfall_to_1"] == 0
    assert payload["short_candidate_shortfall_to_1"] == 0
    assert payload["outcome_count_by_direction"] == {"LONG": 50, "SHORT": 50}
    assert payload["candidate_count_by_direction"] == {"LONG": 50, "SHORT": 50}
    assert payload["accounting_mismatch_count"] == 0
    assert payload["liquidation_count"] == 0
    assert payload["liquidation_event_rows"] == 0
    assert payload["liquidation_events"] == 0
    assert payload["point_in_time_violation_count"] == 0
    assert payload["canary_counting_evidence_allowed"] is True
    assert payload["counting_evidence_allowed"] is True
    assert payload["available_metric_count"] == 3
    assert payload["unavailable_metric_count"] == 0
    assert payload["unavailable_metric_reasons"] == {}
    assert payload["metric_availability"]["after_cost_expectancy_bps"]["available"] is True
    assert payload["metric_availability"]["profit_factor"]["available"] is True
    assert payload["metric_availability"]["false_positive_rate"]["available"] is True
    assert payload["blocked_reasons"] == []
    assert all(detail["passed"] is True for detail in payload["forward_canary_blocker_details"].values())
    assert payload["blocker_details"] == payload["forward_canary_blocker_details"]
    assert payload["failed_forward_canary_blocker_details"] == {}
    assert payload["failed_blocker_details"] == {}
    assert all(payload["pass_conditions"].values())


def test_forward_paper_canary_status_mirrors_pass_contract_scan(tmp_path) -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    update_forward_blockers(
        tmp_path,
        policy=policy,
        cost_status={"status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"},
        lockbox_perf={"pass": False},
        forward_canary_contract={
            "status": "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
            "paper_rows_scanned": 7,
            "closed_challenger_economic_outcomes": 2,
            "new_closed_challenger_economic_outcomes": 2,
            "required_new_closed_economic_outcomes": 100,
            "required_new_closed_challenger_economic_outcomes": 100,
            "required_closed_challenger_economic_outcomes": 100,
            "closed_outcome_shortfall_to_100": 98,
            "closed_challenger_economic_outcome_shortfall_to_required": 98,
            "excluded_row_counts": {"challenger_identity_not_complete": 5},
            "identity_exclusion_counts": {"challenger_identity_not_complete": 5},
            "non_counting_reasons": [{"reason": "challenger_identity_not_complete", "rows": 5}],
            "symbols": 1,
            "symbol_count": 1,
            "required_symbols": 30,
            "symbol_shortfall_to_30": 29,
            "long_count": 1,
            "short_count": 1,
            "long_candidates": 1,
            "short_candidates": 1,
            "long_candidate_shortfall_to_1": 0,
            "short_candidate_shortfall_to_1": 0,
            "outcome_count_by_direction": {"LONG": 1, "SHORT": 1},
            "candidate_count_by_direction": {"LONG": 1, "SHORT": 1},
            "after_cost_expectancy_bps": 3.5,
            "profit_factor": 1.2,
            "accounting_mismatch_rows": 0,
            "accounting_mismatch_count": 0,
            "liquidation_rows": 0,
            "liquidation_events": 0,
            "point_in_time_violations": 0,
            "point_in_time_violation_count": 0,
            "live_route_rows": 0,
            "canary_counting_evidence_allowed": False,
            "counting_evidence_allowed": False,
            "paper_canary_binding_allowed": False,
            "lockbox_pass_contract_status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT",
            "pass_conditions": {"new_closed_challenger_economic_outcomes_gte_100": False},
            "minimum_forward_canary_evidence": {
                "new_closed_challenger_economic_outcomes": ">=100",
                "symbols": ">=30",
                "profit_factor": ">=1.5",
                "live_route_rows": 0,
            },
            "minimum_forward_canary_observed": {
                "new_closed_challenger_economic_outcomes": 2,
                "symbols": 1,
                "profit_factor": 1.2,
                "live_route_rows": 0,
            },
            "minimum_forward_canary_shortfalls": {
                "new_closed_challenger_economic_outcomes": 98,
                "symbols": 29,
                "profit_factor": 0.3,
                "live_route_rows": 0,
            },
            "minimum_forward_canary_pass_conditions": {
                "new_closed_challenger_economic_outcomes_gte_100": False,
                "paper_only_no_live_routes": True,
            },
            "blocked_reasons": ["new_closed_challenger_economic_outcomes_gte_100"],
            "forward_canary_blocker_details": {
                "new_closed_challenger_economic_outcomes_gte_100": {
                    "passed": False,
                    "observed": 2,
                    "required": ">=100",
                    "shortfall": 98,
                }
            },
        },
    )

    status = json.loads((tmp_path / "challenger_v2_forward_paper_canary_status.json").read_text())
    chain_status = json.loads((tmp_path / "challenger_v2_paper_chain_binding_status.json").read_text())
    promotion = json.loads((tmp_path / "challenger_v2_champion_promotion_status.json").read_text())
    assert chain_status["status"] == "NOT_STARTED_BLIND_LOCKBOX_NOT_PASSED"
    assert chain_status["required_components"] == 10
    assert chain_status["complete_components"] == 0
    assert chain_status["incomplete_components"] == 10
    assert set(chain_status["component_statuses"]) == {
        "challenger",
        "signal",
        "strategy",
        "adaptive_allocator",
        "risk",
        "orchestrator",
        "paper_lifecycle",
        "exit",
        "pnl",
        "trainer_feedback",
    }
    assert "production_grade_cost_evidence_not_passed" in chain_status["blocked_reasons"]
    assert "blind_lockbox_not_passed" in chain_status["blocked_reasons"]
    assert chain_status["failed_blocker_details"] == chain_status["blocker_details"]
    assert chain_status["paper_fill_allowed"] is False
    assert chain_status["routes_to_live"] is False
    assert chain_status["counts_as_a_grade_evidence"] is False
    assert chain_status["promotion_evidence"] is False
    assert status["status"] == "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT"
    assert status["paper_rows_scanned"] == 7
    assert status["scanned_rows"] == 7
    assert status["total_rows_scanned"] == 7
    assert status["candidate_bound_rows"] == 2
    assert status["old_policy_or_unbound_rows_quarantined"] == 5
    assert status["identity_incomplete_rows"] == 5
    assert status["non_counting_row_count"] == 5
    assert status["closed_challenger_economic_outcomes"] == 2
    assert status["required_closed_challenger_economic_outcomes"] == 100
    assert status["closed_outcome_shortfall_to_100"] == 98
    assert status["closed_challenger_economic_outcome_shortfall"] == 98
    assert status["closed_challenger_economic_outcome_shortfall_to_required"] == 98
    assert status["minimum_forward_canary_evidence"] == {
        "new_closed_challenger_economic_outcomes": ">=100",
        "symbols": ">=30",
        "profit_factor": ">=1.5",
        "live_route_rows": 0,
    }
    assert status["minimum_forward_canary_observed"] == {
        "new_closed_challenger_economic_outcomes": 2,
        "symbols": 1,
        "profit_factor": 1.2,
        "live_route_rows": 0,
    }
    assert status["minimum_forward_canary_shortfalls"] == {
        "new_closed_challenger_economic_outcomes": 98,
        "symbols": 29,
        "profit_factor": 0.3,
        "live_route_rows": 0,
    }
    assert status["minimum_forward_canary_pass_conditions"] == {
        "new_closed_challenger_economic_outcomes_gte_100": False,
        "paper_only_no_live_routes": True,
    }
    assert status["actuals"] == status["minimum_forward_canary_observed"]
    assert status["required"] == status["minimum_forward_canary_evidence"]
    assert status["sample_blockers"] == [
        {
            "pass_condition": "new_closed_challenger_economic_outcomes_gte_100",
            "passed": False,
            "observed": 2,
            "required": ">=100",
            "shortfall": 98,
        }
    ]
    assert status["excluded_row_counts"] == {"challenger_identity_not_complete": 5}
    assert status["symbol_count"] == 1
    assert status["required_symbols"] == 30
    assert status["symbol_shortfall_to_30"] == 29
    assert status["long_candidates"] == 1
    assert status["short_candidates"] == 1
    assert status["long_candidate_shortfall_to_1"] == 0
    assert status["short_candidate_shortfall_to_1"] == 0
    assert status["candidate_count_by_direction"] == {"LONG": 1, "SHORT": 1}
    assert status["accounting_mismatch_count"] == 0
    assert status["liquidation_events"] == 0
    assert status["point_in_time_violation_count"] == 0
    assert status["canary_counting_evidence_allowed"] is False
    assert status["counting_evidence_allowed"] is False
    assert status["blocked_reasons"] == ["new_closed_challenger_economic_outcomes_gte_100"]
    assert status["paper_fill_allowed"] is False
    assert status["routes_to_live"] is False
    assert status["counts_as_a_grade_evidence"] is False
    assert status["promotion_evidence"] is False
    assert status["blocker_details"] == status["forward_canary_blocker_details"]
    assert status["failed_blocker_details"] == status["failed_forward_canary_blocker_details"]
    assert promotion["status"] == "BLOCKED"
    assert promotion["model_source"] == "test_model"
    assert promotion["paper_only"] is True
    assert promotion["paper_fill_allowed"] is False
    assert promotion["routes_to_live"] is False
    assert promotion["places_real_order"] is False
    assert promotion["counts_as_a_grade_evidence"] is False
    assert promotion["promotion_evidence"] is False
    assert promotion["promotion_allowed"] is False
    assert promotion["a_grade"] is False
    assert promotion["read_only_audit_no_runtime_change"] is True
    assert promotion["frozen_candidate_modified"] is False
    assert promotion["required_promotion_gates"] == [
        "production_grade_cost_evidence_passed",
        "blind_lockbox_passed",
        "forward_paper_canary_passed",
    ]
    assert promotion["pass_conditions"]["production_grade_cost_evidence_passed"] is False
    assert promotion["pass_conditions"]["blind_lockbox_passed"] is False
    assert promotion["pass_conditions"]["forward_paper_canary_passed"] is False
    assert promotion["pass_conditions"]["promotion_allowed_false_until_all_gates_pass"] is True
    assert promotion["blocked_reasons"] == [
        "production_grade_cost_evidence_passed",
        "blind_lockbox_passed",
        "forward_paper_canary_passed",
    ]
    assert promotion["blocker_details"]["production_grade_cost_evidence_passed"]["observed"] == (
        "FAIL_PRODUCTION_GRADE_COST_EVIDENCE"
    )
    assert promotion["blocker_details"]["blind_lockbox_passed"]["observed"] is False
    assert promotion["blocker_details"]["forward_paper_canary_passed"]["observed"] == (
        "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT"
    )
    assert promotion["failed_blocker_details"] == promotion["blocker_details"]


def test_added_paper_governance_blocker_audit_blocks_current_repair_gate() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = added_paper_governance_blocker_audit(
        policy=policy,
        paper_governance_summary={
            "generated_utc": "2026-06-25T20:08:37Z",
            "added_goal_id": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR",
            "final_gate": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_BLOCKED",
            "status": "BLOCKED_POST_FIX_PAPER_VALIDATION",
            "artifacts_written": list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "required_artifacts_present": True,
            "required_artifact_count": len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "source_required_artifact_count": len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "missing_required_artifact_count": 0,
            "raw_close_record_count": 3573,
            "economic_trade_count": 150,
            "old_policy_trade_count": 3573,
            "challenger_trade_count": 0,
            "current_1m_share": 0.045,
            "current_1m_economic_trade_share": 0.12,
            "hardcoded_1m_path_count": 4,
            "silent_1m_fallback_path_count": 2,
            "timeframe_routing_violation_count": 6,
            "silent_1m_fallback_paths": [
                {
                    "path": "v2/backend/app/cli/paper_online_runtime.py",
                    "line": 181,
                    "function": "_paper_thesis_timeframe",
                    "reason": "unsafe_thesis_or_economic_timeframe_default_to_execution_1m",
                    "text": "return PAPER_EXECUTION_TIMING_TIMEFRAME",
                }
            ],
            "routing_owner_blocked_reasons": ["silent_1m_thesis_or_economic_fallbacks_absent"],
            "routing_repair_blocked_reasons": ["silent_1m_fallbacks_absent"],
            "paper_entry_production_grade_cost_coverage": 0.0,
            "paper_entry_required_coverage": 0.95,
            "paper_entry_missing_required_fields": ["latency_reserve"],
            "paper_entry_missing_required_field_counts": {"latency_reserve": 12},
            "paper_entry_missing_required_field_count": 1,
            "paper_entry_shadow_only_missing_cost_rows": 12,
            "routing_status": "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
            "paper_churn_governor_status": "BLOCKED_PAPER_CHURN_GOVERNOR_NOT_WIRED_TO_ENTRY_GATE",
            "operator_dashboard_truth_contract_status": "BLOCKED_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
            "operator_dashboard_truth_contract_blocked_reasons": ["turnover_total_present"],
            "operator_dashboard_missing_required_fields": ["turnover"],
            "paper_edge_to_cost_gate_status": "BLOCKED_PAPER_EDGE_TO_COST_GATE",
            "paper_edge_to_cost_production_grade_cost_coverage": 0.0,
            "paper_edge_to_cost_admitted_candidate_count": 0,
            "paper_edge_to_cost_shadow_only_candidate_count": 12,
            "paper_edge_to_cost_missing_gate_input_counts": {"production_grade_cost_evidence": 12},
            "dynamic_timeframe_execution_eligibility_status": "BLOCKED_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY",
            "dynamic_timeframe_bucket_count": 2,
            "dynamic_timeframe_bucket_state_counts": {"SHADOW_ONLY": 1, "TIMING_ONLY": 1},
            "dynamic_timeframe_sample_bucket_statuses": [{"timeframe": "1m", "state": "TIMING_ONLY"}],
            "dynamic_timeframe_sample_blocked_buckets": [{"timeframe": "1m", "state": "TIMING_ONLY"}],
            "dynamic_timeframe_sample_shadow_only_buckets": [{"timeframe": "1m", "state": "TIMING_ONLY"}],
            "timeframe_execution_concentration_guard_status": "BLOCKED_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD",
            "timeframe_execution_concentration_violation_count": 2,
            "timeframe_execution_concentration_operator_envelope": {
                "max_share": 0.30,
                "dimensions": ["economic_trade_share_by_timeframe"],
                "no_unproven_concentration_required": True,
            },
            "timeframe_execution_concentration_sample_violations": [
                {"timeframe": "4h", "dimension": "economic_trade_share_by_timeframe"}
            ],
            "timeframe_execution_concentration_violation_samples": [
                {"timeframe": "4h", "dimension": "economic_trade_share_by_timeframe"}
            ],
            "timeframe_execution_concentration_violation_sample_count": 1,
            "paper_reentry_and_signal_dedup_status": "BLOCKED_PAPER_REENTRY_AND_SIGNAL_DEDUP",
            "economic_trade_compaction_status": "BLOCKED_ECONOMIC_TRADE_COMPACTION",
            "economic_trade_compaction_missing_raw_identity_fields": ["economic_trade_id"],
            "economic_trade_compaction_raw_identity_missing_field_counts": {"economic_trade_id": 3573},
            "economic_trade_compaction_accounting_reconciliation_status": "BLOCKED_ECONOMIC_TRADE_RECONCILIATION",
            "multi_timeframe_thesis_execution_contract_status": "BLOCKED_MULTI_TIMEFRAME_THESIS_EXECUTION_CONTRACT",
            "multi_timeframe_thesis_execution_required_fields_present_for_all_rows": False,
            "multi_timeframe_thesis_execution_required_fields_present": False,
            "multi_timeframe_thesis_execution_missing_required_fields": ["thesis_prediction_id"],
            "multi_timeframe_thesis_execution_missing_required_field_counts": {"thesis_prediction_id": 20},
            "multi_timeframe_thesis_execution_standalone_1m_requires_eligible_strategy": False,
            "multi_timeframe_thesis_execution_close_outcome_attributed_to_thesis_timeframe": True,
            "multi_timeframe_thesis_execution_higher_tf_position_not_reopened_on_each_1m_tick": True,
            "multi_timeframe_thesis_execution_higher_tf_1m_timing_preserves_thesis": True,
            "post_fix_paper_validation_status": "BLOCKED_POST_FIX_PAPER_VALIDATION",
            "post_fix_sample_status": "POST_FIX_SAMPLE_NOT_STARTED",
            "post_fix_sample_started": False,
            "post_fix_sample_raw_close_rows": 3573,
            "post_fix_sample_eligible_raw_close_rows": 0,
            "post_fix_sample_excluded_raw_close_rows": 3573,
            "post_fix_sample_exclusion_reason_counts": {"missing_explicit_economic_identity": 3573},
            "post_fix_sample_source_counts": {"redis_v2_paper_closed_trades": 3573},
            "post_fix_sample_eligible_source_counts": {},
            "post_fix_sample_excluded_source_counts": {"redis_v2_paper_closed_trades": 3573},
            "post_fix_sample_source_read_status": {
                "redis_v2_paper_closed_trades": {"exists": True, "closed_paper_outcome_rows": 3573}
            },
            "post_fix_sample_sample_excluded_rows": [
                {
                    "source": "redis_v2_paper_closed_trades",
                    "exclusion_reasons": ["missing_explicit_economic_identity"],
                }
            ],
            "post_fix_sample_excluded_row_samples": [
                {
                    "source": "redis_v2_paper_closed_trades",
                    "exclusion_reasons": ["missing_explicit_economic_identity"],
                }
            ],
            "sample_excluded_rows": [
                {
                    "source": "redis_v2_paper_closed_trades",
                    "exclusion_reasons": ["missing_explicit_economic_identity"],
                }
            ],
            "excluded_row_samples": [
                {
                    "source": "redis_v2_paper_closed_trades",
                    "exclusion_reasons": ["missing_explicit_economic_identity"],
                }
            ],
            "post_fix_sample_sample_excluded_rows_by_source": {
                "redis_v2_paper_closed_trades": [
                    {
                        "source": "redis_v2_paper_closed_trades",
                        "exclusion_reasons": ["missing_explicit_economic_identity"],
                    }
                ]
            },
            "post_fix_sample_sample_compacted_economic_trades": [],
            "new_compacted_economic_paper_outcomes": 0,
            "required_new_compacted_economic_paper_outcomes": 100,
            "post_fix_validation_actuals": {"production_cost_coverage_gte_95pct": 0.0},
            "post_fix_validation_actuals_alias": {"production_cost_coverage_gte_95pct": 0.0},
            "post_fix_validation_required": {"production_cost_coverage_gte_95pct": ">= 0.95"},
            "post_fix_validation_required_alias": {"production_cost_coverage_gte_95pct": ">= 0.95"},
            "post_fix_duplicate_economic_trades": 7,
            "post_fix_unexplained_same_candle_reentries": 3,
            "post_fix_accounting_reconciliation_status": "BLOCKED_ECONOMIC_TRADE_RECONCILIATION",
            "routes_to_live": False,
            "places_real_order": False,
            "source_statuses": {
                "paper_timeframe_routing_owner_status": "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
                "paper_entry_cost_coverage_status": "BLOCKED_PAPER_ENTRY_COST_COVERAGE",
                "paper_edge_to_cost_gate_status": "BLOCKED_PAPER_EDGE_TO_COST_GATE",
                "post_fix_paper_validation_status": "BLOCKED_POST_FIX_PAPER_VALIDATION",
            },
            "blocker_summary": {
                "blocker_count": 2,
                "blocked_pass_conditions": ["production_cost_coverage_gte_95pct", "edge_to_cost_gate_pass"],
                "blocker_details": [
                    {
                        "pass_condition": "production_cost_coverage_gte_95pct",
                        "source_artifact": "paper_entry_cost_coverage_status",
                        "source_status": "BLOCKED_PAPER_ENTRY_COST_COVERAGE",
                    }
                ],
            },
            "source_phase_blocker_count": 2,
            "source_phase_blockers": {
                "phase_7_entry_cost_coverage": [
                    "missing_cost_fields_eq_0",
                    "production_grade_cost_coverage_gte_95pct",
                ]
            },
        },
    )

    assert payload["status"] == "BLOCKED_ADDED_PAPER_GOVERNANCE_REPAIR"
    assert payload["blocked_condition_count"] == len(payload["blocked_conditions"])
    assert payload["blocked_reasons"] == payload["blocked_conditions"]
    assert payload["pass_conditions"]["current_closed_ledger_recomputed"] is True
    assert payload["pass_conditions"]["current_timeframe_distribution_proven"] is True
    assert payload["pass_conditions"]["required_artifacts_written"] is True
    assert payload["pass_conditions"]["operator_dashboard_website_truth_contract_passed"] is False
    assert payload["pass_conditions"]["final_gate_ready"] is False
    assert payload["pass_conditions"]["hardcoded_1m_economic_paths_removed"] is False
    assert payload["pass_conditions"]["silent_1m_fallbacks_absent"] is False
    assert payload["pass_conditions"]["source_paper_governance_blockers_cleared"] is False
    assert payload["pass_conditions"]["source_paper_governance_phase_blockers_cleared"] is False
    assert payload["final_gate_ready"] is False
    assert payload["source_paper_governance_blockers_cleared"] is False
    assert payload["source_paper_governance_phase_blockers_cleared"] is False
    assert "source_paper_governance_blockers_cleared" in payload["blocked_conditions"]
    assert "source_paper_governance_phase_blockers_cleared" in payload["blocked_conditions"]
    assert payload["blocker_details"]
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["failed_added_paper_governance_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["paper_entry_production_grade_cost_coverage_gte_95pct"] == 0.0
    assert payload["required"]["paper_entry_production_grade_cost_coverage_gte_95pct"] == ">=0.95"
    assert payload["sample_blockers"] == payload["blocker_details"][:25]
    assert payload["final_gate"] == "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_BLOCKED"
    assert payload["source_final_gate"] == payload["final_gate"]
    assert payload["source_summary_status"] == "BLOCKED_POST_FIX_PAPER_VALIDATION"
    assert payload["source_summary_final_gate"] == payload["final_gate"]
    assert payload["required_artifacts"] == list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["required_artifact_count"] == len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["required_artifacts_present"] is True
    assert payload["source_required_artifact_count"] == len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["source_summary_required_artifact_count"] == len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["source_required_artifacts_present"] is True
    assert payload["source_summary_required_artifacts_present"] is True
    assert payload["missing_required_artifacts"] == []
    assert payload["missing_required_artifact_count"] == 0
    assert payload["source_missing_required_artifact_count"] == 0
    assert payload["source_summary_missing_required_artifact_count"] == 0
    assert payload["source_artifacts_written"] == list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["silent_1m_fallback_path_count"] == 2
    assert payload["timeframe_routing_violation_count"] == 6
    assert payload["silent_1m_fallback_paths"][0]["function"] == "_paper_thesis_timeframe"
    assert payload["routing_owner_blocked_reasons"] == ["silent_1m_thesis_or_economic_fallbacks_absent"]
    assert payload["routing_repair_blocked_reasons"] == ["silent_1m_fallbacks_absent"]
    assert payload["source_blocker_count"] == 2
    assert payload["source_blocked_pass_conditions"] == ["production_cost_coverage_gte_95pct", "edge_to_cost_gate_pass"]
    assert payload["source_blocker_details"][0]["source_artifact"] == "paper_entry_cost_coverage_status"
    assert payload["source_phase_blocker_count"] == 2
    assert payload["source_phase_blockers"] == {
        "phase_7_entry_cost_coverage": [
            "missing_cost_fields_eq_0",
            "production_grade_cost_coverage_gte_95pct",
        ]
    }
    assert payload["operator_dashboard_truth_contract_status"] == "BLOCKED_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT"
    assert payload["operator_dashboard_truth_contract_blocked_reasons"] == ["turnover_total_present"]
    assert payload["operator_dashboard_missing_required_fields"] == ["turnover"]
    assert payload["paper_entry_required_coverage"] == 0.95
    assert payload["paper_entry_missing_required_fields"] == ["latency_reserve"]
    assert payload["paper_entry_missing_required_field_counts"] == {"latency_reserve": 12}
    assert payload["paper_entry_missing_required_field_count"] == 1
    assert payload["paper_entry_shadow_only_missing_cost_rows"] == 12
    assert payload["paper_edge_to_cost_production_grade_cost_coverage"] == 0.0
    assert payload["paper_edge_to_cost_admitted_candidate_count"] == 0
    assert payload["paper_edge_to_cost_shadow_only_candidate_count"] == 12
    assert payload["paper_edge_to_cost_missing_gate_input_counts"] == {"production_grade_cost_evidence": 12}
    assert payload["dynamic_timeframe_execution_eligibility_status"] == "BLOCKED_DYNAMIC_TIMEFRAME_EXECUTION_ELIGIBILITY"
    assert payload["dynamic_timeframe_bucket_count"] == 2
    assert payload["dynamic_timeframe_bucket_state_counts"] == {"SHADOW_ONLY": 1, "TIMING_ONLY": 1}
    assert payload["dynamic_timeframe_sample_bucket_statuses"][0]["timeframe"] == "1m"
    assert payload["dynamic_timeframe_sample_blocked_buckets"][0]["state"] == "TIMING_ONLY"
    assert payload["dynamic_timeframe_sample_shadow_only_buckets"][0]["state"] == "TIMING_ONLY"
    assert payload["timeframe_execution_concentration_guard_status"] == "BLOCKED_TIMEFRAME_EXECUTION_CONCENTRATION_GUARD"
    assert payload["timeframe_execution_concentration_violation_count"] == 2
    assert payload["timeframe_execution_concentration_operator_envelope"]["max_share"] == 0.30
    assert payload["timeframe_execution_concentration_sample_violations"] == [
        {"timeframe": "4h", "dimension": "economic_trade_share_by_timeframe"}
    ]
    assert (
        payload["timeframe_execution_concentration_violation_samples"]
        == payload["timeframe_execution_concentration_sample_violations"]
    )
    assert payload["timeframe_execution_concentration_violation_sample_count"] == 1
    assert payload["paper_reentry_and_signal_dedup_status"] == "BLOCKED_PAPER_REENTRY_AND_SIGNAL_DEDUP"
    assert payload["economic_trade_compaction_missing_raw_identity_fields"] == ["economic_trade_id"]
    assert payload["economic_trade_compaction_raw_identity_missing_field_counts"] == {"economic_trade_id": 3573}
    assert payload["economic_trade_compaction_accounting_reconciliation_status"] == "BLOCKED_ECONOMIC_TRADE_RECONCILIATION"
    assert payload["multi_timeframe_thesis_execution_required_fields_present_for_all_rows"] is False
    assert payload["multi_timeframe_thesis_execution_required_fields_present"] is False
    assert payload["multi_timeframe_thesis_execution_missing_required_fields"] == ["thesis_prediction_id"]
    assert payload["multi_timeframe_thesis_execution_missing_required_field_counts"] == {"thesis_prediction_id": 20}
    assert payload["multi_timeframe_thesis_execution_standalone_1m_requires_eligible_strategy"] is False
    assert payload["multi_timeframe_thesis_execution_close_outcome_attributed_to_thesis_timeframe"] is True
    assert payload["multi_timeframe_thesis_execution_higher_tf_position_not_reopened_on_each_1m_tick"] is True
    assert payload["multi_timeframe_thesis_execution_higher_tf_1m_timing_preserves_thesis"] is True
    assert payload["post_fix_validation_actuals"] == {"production_cost_coverage_gte_95pct": 0.0}
    assert payload["post_fix_validation_actuals_alias"] == payload["post_fix_validation_actuals"]
    assert payload["post_fix_validation_required"] == {"production_cost_coverage_gte_95pct": ">= 0.95"}
    assert payload["post_fix_validation_required_alias"] == payload["post_fix_validation_required"]
    assert payload["post_fix_sample_status"] == "POST_FIX_SAMPLE_NOT_STARTED"
    assert payload["post_fix_sample_started"] is False
    assert payload["post_fix_sample_raw_close_rows"] == 3573
    assert payload["post_fix_sample_eligible_raw_close_rows"] == 0
    assert payload["post_fix_sample_excluded_raw_close_rows"] == 3573
    assert payload["post_fix_sample_exclusion_reason_counts"] == {"missing_explicit_economic_identity": 3573}
    assert payload["post_fix_sample_source_counts"] == {"redis_v2_paper_closed_trades": 3573}
    assert payload["post_fix_sample_eligible_source_counts"] == {}
    assert payload["post_fix_sample_excluded_source_counts"] == {"redis_v2_paper_closed_trades": 3573}
    assert payload["post_fix_sample_source_read_status"]["redis_v2_paper_closed_trades"]["closed_paper_outcome_rows"] == 3573
    assert payload["post_fix_sample_sample_excluded_rows"][0]["source"] == "redis_v2_paper_closed_trades"
    assert payload["post_fix_sample_excluded_row_samples"] == payload["post_fix_sample_sample_excluded_rows"]
    assert payload["sample_excluded_rows"] == payload["post_fix_sample_sample_excluded_rows"]
    assert payload["excluded_row_samples"] == payload["post_fix_sample_sample_excluded_rows"]
    assert payload["post_fix_sample_sample_excluded_rows_by_source"]["redis_v2_paper_closed_trades"][0]["source"] == (
        "redis_v2_paper_closed_trades"
    )
    assert payload["post_fix_sample_sample_compacted_economic_trades"] == []
    assert payload["new_compacted_economic_paper_outcomes"] == 0
    assert payload["required_new_compacted_economic_paper_outcomes"] == 100
    assert payload["post_fix_duplicate_economic_trades"] == 7
    assert payload["post_fix_unexplained_same_candle_reentries"] == 3
    assert payload["post_fix_accounting_reconciliation_status"] == "BLOCKED_ECONOMIC_TRADE_RECONCILIATION"
    assert payload["old_policy_trade_count"] == 3573
    assert payload["challenger_trade_count"] == 0
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_added_paper_governance_blocker_audit_passes_ready_summary() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = added_paper_governance_blocker_audit(
        policy=policy,
        paper_governance_summary={
            "generated_utc": "2026-06-25T20:08:37Z",
            "added_goal_id": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR",
            "final_gate": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY",
            "status": "READY",
            "artifacts_written": list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "required_artifacts_present": True,
            "required_artifact_count": len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "source_required_artifact_count": len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "missing_required_artifact_count": 0,
            "raw_close_record_count": 3573,
            "economic_trade_count": 250,
            "old_policy_trade_count": 3573,
            "challenger_trade_count": 100,
            "current_1m_share": 0.10,
            "current_1m_economic_trade_share": 0.20,
            "hardcoded_1m_path_count": 0,
            "silent_1m_fallback_path_count": 0,
            "timeframe_routing_violation_count": 0,
            "silent_1m_fallback_paths": [],
            "paper_entry_production_grade_cost_coverage": 0.95,
            "routing_status": "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
            "paper_churn_governor_status": "PASS_PAPER_CHURN_GOVERNOR_WIRED_TO_ENTRY_GATE",
            "operator_dashboard_truth_contract_status": "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
            "operator_dashboard_truth_contract_blocked_reasons": [],
            "operator_dashboard_missing_required_fields": [],
            "paper_edge_to_cost_gate_status": "PASS_PAPER_EDGE_TO_COST_GATE",
            "post_fix_paper_validation_status": "PASS_POST_FIX_PAPER_VALIDATION",
            "post_fix_sample_status": "POST_FIX_SAMPLE_READY",
            "post_fix_sample_started": True,
            "post_fix_sample_raw_close_rows": 100,
            "post_fix_sample_eligible_raw_close_rows": 100,
            "post_fix_sample_excluded_raw_close_rows": 0,
            "post_fix_sample_exclusion_reason_counts": {},
            "post_fix_sample_source_counts": {"paper_online_latest_jsonl": 100},
            "post_fix_sample_eligible_source_counts": {"paper_online_latest_jsonl": 100},
            "post_fix_sample_excluded_source_counts": {},
            "post_fix_sample_source_read_status": {
                "paper_online_latest_jsonl": {
                    "status": "PASS_LOCAL_PAPER_EVENTS_JSONL_READ",
                    "closed_paper_outcome_rows": 100,
                }
            },
            "post_fix_sample_sample_excluded_rows": [],
            "post_fix_sample_sample_excluded_rows_by_source": {},
            "post_fix_sample_sample_compacted_economic_trades": [{"economic_trade_id": "econ-ready-1"}],
            "new_compacted_economic_paper_outcomes": 100,
            "required_new_compacted_economic_paper_outcomes": 100,
            "routes_to_live": False,
            "places_real_order": False,
        },
    )

    assert payload["status"] == "PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT"
    assert payload["blocked_conditions"] == []
    assert payload["blocked_reasons"] == []
    assert payload["blocked_condition_count"] == 0
    assert payload["blocker_details"] == []
    assert payload["failed_blocker_details"] == []
    assert payload["failed_added_paper_governance_blocker_details"] == []
    assert all(payload["pass_conditions"].values())
    assert payload["pass_conditions"]["source_paper_governance_blockers_cleared"] is True
    assert payload["pass_conditions"]["source_paper_governance_phase_blockers_cleared"] is True
    assert payload["pass_conditions"]["required_artifacts_written"] is True
    assert payload["pass_conditions"]["operator_dashboard_website_truth_contract_passed"] is True
    assert payload["final_gate_ready"] is True
    assert payload["source_paper_governance_blockers_cleared"] is True
    assert payload["post_fix_sample_status"] == "POST_FIX_SAMPLE_READY"
    assert payload["post_fix_sample_started"] is True
    assert payload["post_fix_sample_eligible_raw_close_rows"] == 100
    assert payload["post_fix_sample_source_counts"] == {"paper_online_latest_jsonl": 100}
    assert payload["post_fix_sample_eligible_source_counts"] == {"paper_online_latest_jsonl": 100}
    assert payload["post_fix_sample_sample_compacted_economic_trades"] == [{"economic_trade_id": "econ-ready-1"}]
    assert payload["new_compacted_economic_paper_outcomes"] == 100
    assert payload["required_new_compacted_economic_paper_outcomes"] == 100
    assert payload["source_paper_governance_phase_blockers_cleared"] is True
    assert payload["final_gate"] == "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY"
    assert payload["source_summary_status"] == "READY"
    assert payload["required_artifact_count"] == len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["required_artifacts_present"] is True
    assert payload["source_required_artifact_count"] == len(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS)
    assert payload["source_required_artifacts_present"] is True
    assert payload["missing_required_artifacts"] == []
    assert payload["missing_required_artifact_count"] == 0
    assert payload["source_missing_required_artifact_count"] == 0
    assert payload["promotion_evidence"] is True


def test_goal_phase_completion_audit_blocks_until_cost_lockbox_binding_and_forward_canary_pass() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = challenger_goal_phase_completion_audit(
        policy=policy,
        cost_status={
            "status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
            "production_grade_cost_coverage": 0.0,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
            "required_cost_fields_present_for_all_rows": False,
            "required_cost_fields_covered_gte_95pct": False,
            "hard_blocker_count": 1,
            "hard_blocker_fields": ["order_size"],
        },
        cost_capture_gap={
            "status": "BLOCKED_EXISTING_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY",
            "can_recover_from_existing_authoritative_sources_without_new_capture": False,
        },
        runtime_cost_capture_contract={"status": "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"},
        append_status={"pending_path": "pending.jsonl", "new_pending_rows_appended": 1},
        label_status={"labelled_path": "labelled.jsonl"},
        hash_chain={"pending": {"last_chain_hash": "pending"}, "labelled": {"row_count": 0}},
        pending_rows=[{"lockbox_record_id": "record-1"}],
        labelled_rows=[],
        drift_coverage={"status": "PASS_DRIFT_COVERAGE_AUDIT"},
        drift_mapping_confidence={
            "status": "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT",
            "candidate_id_change_required": False,
            "frozen_candidate_kept": True,
        },
        shadow_supply_contract={
            "status": "PASS_SHADOW_SUPPLY_CONTRACT",
            "top_25_long_count": 25,
            "top_25_short_count": 25,
            "routes_to_live": False,
            "paper_fill_allowed": False,
            "counts_as_a_grade_evidence": False,
        },
        zero_supply={"status": "ZERO_SUPPLY_DIAGNOSED", "root_cause_classification": "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED"},
        lockbox_integrity={"status": "PASS_INTEGRITY_AUDIT"},
        lockbox_pass_contract={
            "status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT",
            "independent_economic_candidates": 0,
            "point_in_time_violations": 0,
            "production_grade_cost_coverage": 0.0,
        },
        paper_canary_binding={
            "status": "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
            "binding_allowed": False,
            "old_policy_rows_count_as_challenger_evidence": False,
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {"paper_record_identity_contract_declared": True},
        },
        paper_chain_binding_readiness={
            "status": "BLOCKED_PAPER_CHAIN_BINDING_NOT_READY",
            "chain_ready": False,
            "required_components": 10,
            "complete_components": 0,
            "missing_component_count": 10,
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {
                "required_chain_declared": True,
                "all_chain_components_have_identity_contract": True,
                "paper_record_identity_fields_declared": True,
            },
        },
        forward_canary_contract={
            "status": "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
            "closed_challenger_economic_outcomes": 0,
            "symbols": 0,
            "long_count": 0,
            "short_count": 0,
            "profit_factor": None,
            "accounting_mismatch_rows": 0,
            "liquidation_rows": 0,
            "point_in_time_violations": 0,
            "live_route_rows": 0,
        },
        added_paper_governance={
            "status": "BLOCKED_ADDED_PAPER_GOVERNANCE_REPAIR",
            "pass_conditions": {
                "final_gate_ready": False,
                "hardcoded_1m_economic_paths_removed": False,
                "operator_dashboard_website_truth_contract_passed": False,
                "paper_entry_production_grade_cost_coverage_gte_95pct": False,
                "post_fix_paper_validation_passed": False,
                "no_live_routes": True,
            },
        },
    )

    assert payload["status"] == "BLOCKED_GOAL_COMPLETION_AUDIT"
    assert payload["goal_phase_completion_status"] == payload["status"]
    assert payload["goal_complete"] is False
    assert payload["phases"]["phase_2_append_only_future_lockbox_collector"]["status"] == "PASS"
    assert payload["phases"]["phase_3_distribution_drift_diagnosis"]["status"] == "PASS"
    assert payload["phases"]["phase_4_continuous_shadow_supply"]["status"] == "PASS"
    assert payload["phase_statuses"]["phase_1_production_grade_cost_evidence"] == "BLOCKED"
    assert payload["phase_statuses"]["phase_2_append_only_future_lockbox_collector"] == "PASS"
    assert payload["phase_blockers"]["phase_1_production_grade_cost_evidence"] == (
        "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY"
    )
    assert payload["pass_conditions"]["phase_1_production_grade_cost_evidence_passed"] is False
    assert payload["pass_conditions"]["phase_2_append_only_future_lockbox_collector_passed"] is True
    assert "phase_1_production_grade_cost_evidence" in payload["blocked_phases"]
    assert "phase_5_blind_lockbox_pass" in payload["blocked_phases"]
    assert "phase_6_bind_to_paper_after_lockbox_pass" in payload["blocked_phases"]
    assert "phase_7_forward_paper_canary" in payload["blocked_phases"]
    assert "added_p0_paper_timeframe_churn_governance_repair" in payload["blocked_phases"]
    assert payload["blocked_phase_count"] == len(payload["blocked_phases"])
    assert payload["blocked_reasons"] == payload["blocked_phases"]
    assert payload["blocked_by_phase"]["phase_1_production_grade_cost_evidence"] >= 1
    assert payload["blocked_by_phase"]["phase_5_blind_lockbox_pass"] >= 1
    assert payload["blocked_condition_count"] == len(payload["blocked_conditions"])
    assert payload["phase_blocker_count"] == payload["blocked_condition_count"]
    assert payload["phase_blocked_conditions"] == payload["blocked_conditions"]
    assert "phase_1_production_grade_cost_evidence.production_grade_cost_evidence_passed" in payload[
        "blocked_conditions"
    ]
    assert "phase_1_production_grade_cost_evidence.required_cost_fields_present_for_all_rows" in payload[
        "blocked_conditions"
    ]
    assert "phase_1_production_grade_cost_evidence.required_cost_fields_covered_gte_95pct" in payload[
        "blocked_conditions"
    ]
    assert "phase_1_production_grade_cost_evidence.hard_blocking_cost_fields_cleared" in payload[
        "blocked_conditions"
    ]
    assert "phase_5_blind_lockbox_pass.symbols_gte_30" in payload["blocked_conditions"]
    assert "phase_5_blind_lockbox_pass.after_cost_expectancy_gt_0" in payload["blocked_conditions"]
    assert "phase_5_blind_lockbox_pass.false_positive_rate_lte_0_40" in payload["blocked_conditions"]
    assert "phase_6_bind_to_paper_after_lockbox_pass.paper_chain_binding_ready" in payload["blocked_conditions"]
    assert "phase_6_bind_to_paper_after_lockbox_pass.paper_chain_components_ready" in payload["blocked_conditions"]
    assert "challenger_v2_paper_chain_binding_readiness_audit.json" in payload["phase_summary"][
        "phase_6_bind_to_paper_after_lockbox_pass"
    ]["primary_artifacts"]
    assert "challenger_v2_paper_chain_binding_readiness_audit.json" in payload["blocker_details"][
        "phase_6_bind_to_paper_after_lockbox_pass"
    ]["primary_artifacts"]
    assert "phase_7_forward_paper_canary.paper_canary_after_cost_expectancy_gt_0" in payload["blocked_conditions"]
    assert payload["phase_summary"]["phase_1_production_grade_cost_evidence"]["blocked_condition_count"] >= 1
    assert payload["phase_summary"]["phase_5_blind_lockbox_pass"]["blocked_condition_count"] >= 11
    assert payload["phase_summary"]["phase_2_append_only_future_lockbox_collector"]["blocked_condition_count"] == 0
    assert payload["blocker_details"]["phase_1_production_grade_cost_evidence"]["status"] == "BLOCKED"
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["promotion_evidence"] is False


def test_goal_phase_completion_audit_passes_when_all_phase_contracts_pass() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = challenger_goal_phase_completion_audit(
        policy=policy,
        cost_status={
            "status": "PASS",
            "production_grade_cost_coverage": 0.95,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
            "required_cost_fields_present_for_all_rows": True,
            "required_cost_fields_covered_gte_95pct": True,
            "hard_blocker_count": 0,
            "hard_blocker_fields": [],
        },
        cost_capture_gap={"can_recover_from_existing_authoritative_sources_without_new_capture": True},
        runtime_cost_capture_contract={"status": "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"},
        runtime_cost_capture_operator_approval_receipt={"status": "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"},
        append_status={"pending_path": "pending.jsonl", "new_pending_rows_appended": 1},
        label_status={"labelled_path": "labelled.jsonl"},
        hash_chain={"pending": {"last_chain_hash": "pending"}, "labelled": {"last_chain_hash": "labelled"}},
        pending_rows=[{"lockbox_record_id": "record-1"}],
        labelled_rows=[{"lockbox_record_id": "record-1"}],
        drift_coverage={"status": "PASS_DRIFT_COVERAGE_AUDIT"},
        drift_mapping_confidence={
            "status": "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT",
            "candidate_id_change_required": False,
            "frozen_candidate_kept": True,
        },
        shadow_supply_contract={
            "status": "PASS_SHADOW_SUPPLY_CONTRACT",
            "top_25_long_count": 25,
            "top_25_short_count": 25,
            "routes_to_live": False,
            "paper_fill_allowed": False,
            "counts_as_a_grade_evidence": False,
        },
        zero_supply={"status": "ZERO_SUPPLY_DIAGNOSED"},
        lockbox_integrity={"status": "PASS_INTEGRITY_AUDIT"},
        lockbox_pass_contract={
            "status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
            "independent_economic_candidates": 300,
            "symbols": 30,
            "long_count": 150,
            "short_count": 150,
            "after_cost_expectancy_bps": 1.0,
            "expectancy_95pct_lower_bound_bps": 0.1,
            "profit_factor": 1.5,
            "false_positive_rate": 0.4,
            "max_concentration_pct": 0.3,
            "worst_1pct_loss_bps": -10.0,
            "point_in_time_violations": 0,
            "production_grade_cost_coverage": 0.95,
        },
        paper_canary_binding={
            "status": "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT",
            "binding_allowed": True,
            "old_policy_rows_count_as_challenger_evidence": False,
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {"paper_record_identity_contract_declared": True},
        },
        paper_chain_binding_readiness={
            "status": "READY_FOR_OPERATOR_REVIEW_PAPER_CHAIN_BINDING",
            "chain_ready": True,
            "required_components": 10,
            "complete_components": 10,
            "missing_component_count": 0,
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {
                "required_chain_declared": True,
                "all_chain_components_have_identity_contract": True,
                "paper_record_identity_fields_declared": True,
            },
        },
        forward_canary_contract={
            "status": "PASS_FORWARD_PAPER_CANARY_CONTRACT",
            "closed_challenger_economic_outcomes": 100,
            "symbols": 30,
            "long_count": 50,
            "short_count": 50,
            "after_cost_expectancy_bps": 1.0,
            "profit_factor": 1.5,
            "accounting_mismatch_rows": 0,
            "liquidation_rows": 0,
            "point_in_time_violations": 0,
            "live_route_rows": 0,
        },
        added_paper_governance={
            "status": "PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT",
            "pass_conditions": {
                "final_gate_ready": True,
                "hardcoded_1m_economic_paths_removed": True,
                "operator_dashboard_website_truth_contract_passed": True,
                "paper_entry_production_grade_cost_coverage_gte_95pct": True,
                "post_fix_paper_validation_passed": True,
                "source_paper_governance_blockers_cleared": True,
                "source_paper_governance_phase_blockers_cleared": True,
                "no_live_routes": True,
            },
        },
    )

    assert payload["status"] == "PASS_GOAL_COMPLETION_AUDIT"
    assert payload["goal_phase_completion_status"] == payload["status"]
    assert payload["goal_complete"] is True
    assert payload["blocked_phases"] == []
    assert payload["blocked_phase_count"] == 0
    assert payload["blocked_by_phase"] == {}
    assert payload["blocked_conditions"] == []
    assert payload["blocked_condition_count"] == 0
    assert payload["phase_blocker_count"] == 0
    assert payload["phase_blocked_conditions"] == []
    assert all(status == "PASS" for status in payload["phase_statuses"].values())
    assert all(summary["blocked_condition_count"] == 0 for summary in payload["phase_summary"].values())
    assert payload["phase_blockers"] == {}
    assert all(payload["pass_conditions"].values())
    assert all(phase["status"] == "PASS" for phase in payload["phases"].values())
    assert payload["promotion_evidence"] is True


def _traceability_common_kwargs(policy: SimpleNamespace) -> dict:
    lockbox_pass_conditions = {
        "pending_required_fields_present": True,
        "pending_lockbox_ids_unique": True,
        "pending_decision_keys_unique": True,
        "selection_fields_marked_immutable": True,
        "labels_append_outcomes_only": True,
        "labels_created_after_pending_records": True,
        "labels_have_pending_selection_record": True,
        "labels_use_future_data_as_label_only": True,
        "selection_record_hashes_match_pending_records": True,
        "point_in_time_violations_eq_0": True,
    }
    shadow_pass_conditions = {
        "top_25_long_candidates_published": True,
        "top_25_short_candidates_published": True,
        "top_25_candidate_rows_mirrored_in_contract": True,
        "required_edge_cost_drift_liquidity_fields_present": True,
        "row_safety_flags_false": True,
        "score_every_current_valid_row_declared": True,
    }
    return {
        "policy": policy,
        "frozen_candidate_integrity": {
            "status": "PASS_FROZEN_CANDIDATE_INTEGRITY_AUDIT",
            "candidate_id": policy.candidate_id,
            "policy_fingerprint": policy.policy_fingerprint,
            "model_source": policy.model_source,
            "frozen_policy_file_sha256": "frozen-policy-sha",
            "frozen_candidate_modified_since_previous_evidence_run": False,
            "frozen_candidate_modified": False,
            "paper_only": True,
            "routes_to_live": False,
            "promotion_allowed": False,
            "paper_fill_allowed": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
            "pass_conditions": {
                "candidate_id_matches_expected": True,
                "policy_fingerprint_matches_expected": True,
                "model_source_matches_expected": True,
                "feature_names_match_loaded_policy": True,
                "normalization_hash_matches_recomputed": True,
                "cost_model_hash_matches_recomputed": True,
                "weights_match_loaded_policy": True,
                "paper_only_true": True,
                "routes_to_live_false": True,
                "promotion_allowed_false": True,
                "post_freeze_change_invalidates_candidate": True,
            },
            "frozen_policy_safety_contract": {
                "new_candidate_required_if_feature_normalization_cost_model_weight_or_threshold_changes": True,
            },
        },
        "shadow_cost_status": {
            "shadow_cost_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "shadow_cost_evidence_hash_chain_status": "PASS_SHADOW_COST_EVIDENCE_HASH_CHAIN_AUDIT",
            "pass_conditions": {"hash_chain_contract_passed": True},
        },
        "shadow_cost_reconciliation": {},
        "append_status": {"pending_path": "pending.jsonl"},
        "label_status": {"labelled_path": "labelled.jsonl"},
        "hash_chain": {
            "status": "PASS_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT",
            "pending": {
                "row_count": 1,
                "path": "pending.jsonl",
                "file_sha256": "pending-file-hash",
                "last_chain_hash": "pending",
            },
            "labelled": {
                "row_count": 1,
                "path": "labelled.jsonl",
                "file_sha256": "labelled-file-hash",
                "last_chain_hash": "labelled",
            },
            "pending_rows": 1,
            "labelled_rows": 1,
            "pending_path": "pending.jsonl",
            "labelled_path": "labelled.jsonl",
            "pending_file_sha256": "pending-file-hash",
            "labelled_file_sha256": "labelled-file-hash",
            "pass_conditions": {
                "pending_file_hash_present": True,
                "labelled_file_hash_present": True,
                "pending_chain_algorithm_declared": True,
                "labelled_chain_algorithm_declared": True,
                "pending_terminal_hash_present_or_file_empty": True,
                "labelled_terminal_hash_present_or_file_empty": True,
                "pending_hash_bounds_match_row_count": True,
                "labelled_hash_bounds_match_row_count": True,
                "top_level_row_counts_match_nested_chains": True,
                "selection_records_are_append_only": True,
                "labels_are_append_only_and_separate": True,
                "paper_fill_allowed_false": True,
                "routes_to_live_false": True,
                "counts_as_a_grade_evidence_false": True,
                "promotion_evidence_false": True,
            },
            "blocker_details": [],
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        },
        "runtime_cost_capture_operator_approval": {
            "status": "AWAITING_OPERATOR_APPROVAL_RUNTIME_COST_CAPTURE_IDENTITY_BINDING",
            "approval_subject_hash": "approval-subject-hash",
            "approval_subject_hash_status": "READY",
            "approval_required_source_groups": ["paper_intent"],
            "operator_approval_required_source_groups": ["paper_intent"],
            "approved_source_groups": ["paper_intent"],
            "approved_patch_scope": "telemetry_only_future_runtime_cost_and_identity_capture",
            "required_operator_acknowledgements": [
                "acknowledges_no_historical_backfill_for_credit",
                "acknowledges_no_frozen_candidate_or_model_changes",
                "acknowledges_paper_fill_and_live_routes_remain_false",
            ],
            "telemetry_only_runtime_paths": [{"source_group": "paper_intent"}],
            "prohibited_patch_scope": [
                "order_submission",
                "frozen_candidate_artifact_change",
                "strategy_threshold_or_weight_change",
                "paper_binding_before_blind_lockbox_pass",
            ],
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "frozen_candidate_modified": False,
        },
        "runtime_cost_capture_remediation": {
            "status": "BLOCKED_REQUIRES_FUTURE_CANDIDATE_BOUND_PRODUCTION_GRADE_CAPTURE",
            "blocked_reasons": ["current_challenger_bound_production_grade_rows_gte_required"],
            "remediation_blocker_details": [
                {
                    "pass_condition": "current_challenger_bound_production_grade_rows_gte_required",
                    "passed": False,
                    "actual": {"current": 0, "required": 95, "shortfall": 95},
                    "expected": ">=95",
                }
            ],
            "source_group_decisions": [
                {
                    "source_group": "paper_intent",
                    "capture_stage": "pre_submit_intent",
                    "remediation_class": "future_identity_binding_required_existing_rows_not_counted",
                    "required_actions": ["persist_candidate_id_policy_fingerprint_and_model_source_on_future_rows"],
                    "counts_as_training_lockbox_or_promotion_evidence": False,
                }
            ],
            "required_new_candidate_bound_production_grade_rows": 95,
            "top_source_group": "paper_intent",
            "top_decision_time_capture_source_group": "paper_intent",
            "future_capture_credit_rules": {
                "existing_old_or_unbound_rows_may_not_be_backfilled_for_credit": True,
                "fallback_true_rows_count_as_training_lockbox_or_promotion_evidence": False,
            },
            "paper_fill_allowed": False,
            "routes_to_live": False,
        },
        "lockbox_integrity": {"status": "PASS_INTEGRITY_AUDIT", "pass_conditions": lockbox_pass_conditions},
        "drift_status": {
            "status": "PASS_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT",
            "feature_count": 32,
            "root_cause_classification": "GENUINE_RUNTIME_DISTRIBUTION_SHIFT_OR_TRAINING_RANGE_EXHAUSTION",
            "candidate_id_change_required": False,
            "frozen_candidate_kept": True,
            "features_requiring_new_candidate_if_fixed": [],
            "blocker_details": [],
            "pass_conditions": {
                "root_cause_classification_present": True,
                "candidate_change_decision_matches_root_cause": True,
            },
            "drift_decision_contract": {
                "new_candidate_required_if_any_feature_mapping_or_normalization_changes": True,
                "frozen_candidate_tuning_allowed_from_drift_results": False,
                "runtime_reject_drifted_conditions": True,
                "paper_fill_allowed": False,
                "routes_to_live": False,
            },
        },
        "drift_coverage": {
            "status": "PASS_DRIFT_COVERAGE_AUDIT",
            "policy_feature_count": 32,
            "required_feature_count": 32,
            "required_cohort_count": 5,
            "reported_required_cohort_count": 5,
            "cohorts_present": ["training", "validation", "previous_holdout", "current_runtime", "future_lockbox"],
            "pass_conditions": {"top_level_feature_and_cohort_summary_present": True},
        },
        "drift_mapping_confidence": {
            "status": "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT",
            "candidate_id_change_required": False,
            "frozen_candidate_kept": True,
        },
        "shadow_supply_contract": {"pass_conditions": shadow_pass_conditions},
        "zero_supply": {
            "status": "ZERO_SUPPLY_DIAGNOSED",
            "root_cause": "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED",
            "root_cause_classification": "ZERO_SUPPLY_ALL_ROWS_COST_AND_LIQUIDITY_BLOCKED",
            "blocked_reasons": ["cost_not_production_grade", "liquidity_missing_depth_or_order_size"],
            "blocker_details": [
                {
                    "blocker": "cost_not_production_grade",
                    "blocked_rows": 2,
                    "total_rows": 2,
                    "all_rows_blocked": True,
                }
            ],
            "zero_supply_blocker_details": [
                {
                    "blocker": "cost_not_production_grade",
                    "blocked_rows": 2,
                    "total_rows": 2,
                    "all_rows_blocked": True,
                }
            ],
            "next_actions": ["continue_future_candidate_bound_production_grade_cost_capture"],
            "pass_conditions": {
                "paper_fill_allowed_false": True,
                "routes_to_live_false": True,
                "counts_as_a_grade_evidence_false": True,
            },
        },
        "paper_binding_preflight": {},
        "paper_credit_attribution_guard": {
            "status": "PASS_PREBINDING_CHALLENGER_CREDIT_ATTRIBUTION_GUARD",
            "pass_conditions": {
                "old_policy_rows_count_as_challenger_evidence_false": True,
                "old_policy_or_unbound_cost_rows_quarantined": True,
                "forward_canary_has_no_challenger_outcomes_while_binding_blocked": True,
                "paper_fill_allowed_rows_not_counted_as_challenger_evidence": True,
            },
        },
        "paper_chain_binding_readiness": {
            "status": "BLOCKED_PAPER_CHAIN_BINDING_NOT_READY",
            "chain_ready": False,
            "required_chain": [
                "challenger",
                "signal",
                "strategy",
                "adaptive_allocator",
                "risk",
                "orchestrator",
                "paper_lifecycle",
                "exit",
                "pnl",
                "trainer_feedback",
            ],
            "required_components": 10,
            "complete_components": 0,
            "incomplete_components": 10,
            "missing_component_count": 10,
            "component_statuses": {
                "challenger": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "signal": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "strategy": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "adaptive_allocator": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "risk": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "orchestrator": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "paper_lifecycle": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "exit": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "pnl": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
                "trainer_feedback": "BLOCKED_UNTIL_COST_AND_LOCKBOX_PASS",
            },
            "required_paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
            "chain_prerequisite_details": {
                "production_grade_cost_evidence_passed": {"passed": False},
                "blind_lockbox_passed": {"passed": False},
                "paper_record_identity_fields_declared": {"passed": True},
            },
            "failed_binding_blocker_details": {
                "production_grade_cost_evidence_passed": {"passed": False},
                "blind_lockbox_passed": {"passed": False},
            },
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "places_real_order": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
        },
    }


def test_goal_requirement_traceability_matrix_blocks_unmet_explicit_requirements() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    kwargs = _traceability_common_kwargs(policy)

    payload = goal_requirement_traceability_matrix(
        **kwargs,
        cost_status={
            "status": "FAIL_PRODUCTION_GRADE_COST_EVIDENCE",
            "production_grade_cost_coverage": 0.0,
            "unexplained_cost_missing_rows": 0,
            "replay_paper_cost_parity_mismatch_rows": 0,
            "pass_conditions": {"replay_paper_cost_parity_for_same_snapshot_order": True},
        },
        cost_capture_gap={
            "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "field_shortfalls": {
                "order_size": {
                    "coverage": 0.0,
                    "missing_rows": 10,
                    "recovery_boundary": "adaptive_allocator_or_paper_intent_pre_submit",
                }
            },
        },
        runtime_cost_capture_contract={"status": "BLOCKED_RUNTIME_COST_CAPTURE_CONTRACT_NOT_SATISFIED"},
        paper_cost_telemetry={"challenger_bound_production_grade_rows": 0},
        lockbox_pass_contract={
            "status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT",
            "independent_economic_candidates": 0,
            "production_grade_cost_coverage": 0.0,
            "pass_conditions": {
                "independent_economic_candidates_gte_300": False,
                "point_in_time_violations_eq_0": True,
            },
        },
        paper_canary_binding={
            "status": "BLOCKED_PAPER_CANARY_BINDING_NOT_READY",
            "binding_allowed": False,
            "pass_conditions": {
                "production_grade_cost_evidence_passed": False,
                "blind_lockbox_passed": False,
                "paper_record_identity_contract_declared": True,
                "paper_canary_forced_paper_only": True,
                "no_candidate_bound_rows_before_lockbox_pass": True,
                "no_partial_challenger_identity_rows": True,
                "no_routes_to_live": True,
            },
            "binding_prerequisite_details": {
                "production_grade_cost_evidence_passed": {"passed": False},
                "blind_lockbox_passed": {"passed": False},
                "paper_record_identity_contract_declared": {"passed": True},
                "paper_canary_forced_paper_only": {"passed": True},
                "no_candidate_bound_rows_before_lockbox_pass": {"passed": True},
                "no_partial_challenger_identity_rows": {"passed": True},
                "no_routes_to_live": {"passed": True},
            },
            "failed_binding_blocker_details": {
                "production_grade_cost_evidence_passed": {"passed": False},
                "blind_lockbox_passed": {"passed": False},
            },
        },
        forward_canary_contract={
            "status": "BLOCKED_FORWARD_PAPER_CANARY_CONTRACT",
            "closed_challenger_economic_outcomes": 0,
            "pass_conditions": {
                "new_closed_challenger_economic_outcomes_gte_100": False,
                "accounting_mismatch_rows_eq_0": True,
                "liquidation_rows_eq_0": True,
                "point_in_time_violations_eq_0": True,
                "paper_only_no_live_routes": True,
            },
        },
        goal_phase_completion={"goal_complete": False},
        added_paper_governance={
            "status": "BLOCKED_ADDED_PAPER_GOVERNANCE_REPAIR",
            "added_goal_id": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR",
            "source_generated_utc": "2026-06-25T20:08:37Z",
            "source_final_gate": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_BLOCKED",
            "source_routing_status": "FAIL_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
            "raw_close_record_count": 3573,
            "economic_trade_count": 150,
            "current_1m_share": 0.045,
            "current_1m_economic_trade_share": 0.12,
            "hardcoded_1m_path_count": 4,
            "silent_1m_fallback_path_count": 2,
            "timeframe_routing_violation_count": 6,
            "silent_1m_fallback_paths": [
                {
                    "path": "v2/backend/app/cli/paper_online_runtime.py",
                    "line": 181,
                    "function": "_paper_thesis_timeframe",
                    "reason": "unsafe_thesis_or_economic_timeframe_default_to_execution_1m",
                    "text": "return PAPER_EXECUTION_TIMING_TIMEFRAME",
                }
            ],
            "paper_churn_governor_status": "BLOCKED_PAPER_CHURN_GOVERNOR_NOT_WIRED_TO_ENTRY_GATE",
            "operator_dashboard_truth_contract_status": "BLOCKED_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
            "operator_dashboard_truth_contract_blocked_reasons": ["turnover_total_present"],
            "operator_dashboard_missing_required_fields": ["turnover"],
            "paper_edge_to_cost_gate_status": "BLOCKED_PAPER_EDGE_TO_COST_GATE",
            "paper_entry_production_grade_cost_coverage": 0.0,
            "post_fix_paper_validation_status": "BLOCKED_POST_FIX_PAPER_VALIDATION",
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {
                "paper_governance_summary_present": True,
                "added_goal_id_matches": True,
                "current_closed_ledger_recomputed": True,
                "economic_trade_compaction_present": True,
                "current_timeframe_distribution_proven": True,
                "paper_routing_owner_audit_passed": False,
                "hardcoded_1m_economic_paths_removed": False,
                "silent_1m_fallbacks_absent": False,
                "paper_churn_governor_wired": False,
                "operator_dashboard_website_truth_contract_passed": False,
                "paper_edge_to_cost_gate_passed": False,
                "paper_entry_production_grade_cost_coverage_gte_95pct": False,
                "post_fix_paper_validation_passed": False,
                "final_gate_ready": False,
                "no_live_routes": True,
            },
        },
    )

    assert payload["status"] == "BLOCKED_GOAL_REQUIREMENTS_REMAIN"
    assert payload["goal_requirement_traceability_status"] == payload["status"]
    assert payload["goal_complete"] is False
    assert payload["blocked_requirements"] > 0
    assert payload["blocked_requirement_count"] == payload["blocked_requirements"]
    assert payload["failed_requirement_count"] == payload["blocked_requirements"]
    assert payload["failed_requirements"] == payload["blocked_requirements"]
    assert payload["passed_requirement_count"] == payload["passed_requirements"]
    assert payload["total_requirement_count"] == payload["total_requirements"]
    assert payload["requirements_total"] == payload["total_requirements"]
    assert "phase_1.production_grade_cost_evidence_passed" in payload["blocked_requirement_ids"]
    assert "phase_1.required_cost_field.order_size" in payload["blocked_requirement_ids"]
    assert "phase_1.runtime_cost_capture_operator_approval_receipt_passed" in payload["blocked_requirement_ids"]
    assert "phase_1.cost_capture_recovery_plan_published" in payload["blocked_requirement_ids"]
    assert "phase_5.blind_lockbox_pass_contract_passed" in payload["blocked_requirement_ids"]
    assert "phase_5.independent_economic_candidates_gte_300" in payload["blocked_requirement_ids"]
    assert "phase_6.paper_canary_binding_allowed" in payload["blocked_requirement_ids"]
    assert "phase_6.paper_chain_binding_ready" in payload["blocked_requirement_ids"]
    assert "phase_6.paper_chain_components_ready" in payload["blocked_requirement_ids"]
    assert "phase_7.forward_paper_canary_contract_passed" in payload["blocked_requirement_ids"]
    assert "phase_7.new_closed_challenger_economic_outcomes_gte_100" in payload["blocked_requirement_ids"]
    assert "added_paper_governance.added_paper_governance_blocker_audit_passed" in payload[
        "blocked_requirement_ids"
    ]
    assert "added_paper_governance.final_gate_ready" in payload["blocked_requirement_ids"]
    assert "added_paper_governance.silent_1m_fallbacks_absent" in payload["blocked_requirement_ids"]
    assert "added_paper_governance.source_paper_governance_blockers_cleared" in payload["blocked_requirement_ids"]
    assert "added_paper_governance.source_paper_governance_phase_blockers_cleared" in payload["blocked_requirement_ids"]
    assert payload["blocked_reasons"] == payload["blocked_requirement_ids"]
    assert payload["pass_conditions"]["total_requirements_gt_0"] is True
    assert payload["pass_conditions"]["passed_plus_blocked_equals_total"] is True
    assert payload["pass_conditions"]["blocked_requirement_count_eq_0"] is False
    assert payload["pass_conditions"]["goal_phase_completion_true"] is False
    assert payload["pass_conditions"]["blocker_details_cover_blocked_requirements"] is True
    assert payload["pass_conditions"]["paper_only_no_live_routes"] is True
    assert payload["blocker_details"]["phase_1.required_cost_field.order_size"]["artifact"] == (
        "challenger_v2_production_cost_capture_gap_audit.json"
    )
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert "phase_2.pending_decision_keys_unique" not in payload["blocked_requirement_ids"]
    assert "phase_1.runtime_cost_capture_operator_approval_packet_subject_hash_ready" not in payload[
        "blocked_requirement_ids"
    ]
    assert "phase_1.runtime_cost_capture_operator_approval_packet_scope_telemetry_only" not in payload[
        "blocked_requirement_ids"
    ]
    assert "phase_1.runtime_cost_capture_operator_approval_packet_acknowledgements_declared" not in payload[
        "blocked_requirement_ids"
    ]
    assert "phase_1.runtime_cost_capture_operator_approval_packet_forbidden_scope_declared" not in payload[
        "blocked_requirement_ids"
    ]
    assert "phase_6.binding_prerequisite_details_published" not in payload["blocked_requirement_ids"]
    assert any(
        row["requirement_id"] == "phase_2.pending_decision_keys_unique" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_1.runtime_cost_capture_operator_approval_packet_subject_hash_ready"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_2.hash_chain_contract_published" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert payload["blocked_by_phase"]["phase_1_production_grade_cost_evidence"] >= 1
    assert payload["blocked_by_phase"]["added_p0_paper_timeframe_churn_governance_repair"] >= 1
    assert payload["failed_by_phase"] == payload["blocked_by_phase"]
    assert payload["requirements_by_phase"]["phase_1_production_grade_cost_evidence"]["blocked_requirements"] >= 1
    assert payload["requirements_by_phase"]["added_p0_paper_timeframe_churn_governance_repair"][
        "blocked_requirements"
    ] >= 1
    assert payload["phase_summary"] == payload["requirements_by_phase"]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False


def test_goal_requirement_traceability_matrix_passes_when_all_requirements_are_met() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    kwargs = _traceability_common_kwargs(policy)
    kwargs["paper_chain_binding_readiness"] = {
        "status": "READY_FOR_OPERATOR_REVIEW_PAPER_CHAIN_BINDING",
        "chain_ready": True,
        "required_chain": [
            "challenger",
            "signal",
            "strategy",
            "adaptive_allocator",
            "risk",
            "orchestrator",
            "paper_lifecycle",
            "exit",
            "pnl",
            "trainer_feedback",
        ],
        "required_components": 10,
        "complete_components": 10,
        "incomplete_components": 0,
        "missing_component_count": 0,
        "component_statuses": {
            "challenger": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "signal": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "strategy": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "adaptive_allocator": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "risk": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "orchestrator": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "paper_lifecycle": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "exit": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "pnl": "READY_FOR_OPERATOR_REVIEW_BINDING",
            "trainer_feedback": "READY_FOR_OPERATOR_REVIEW_BINDING",
        },
        "required_paper_record_identity_fields": ["candidate_id", "policy_fingerprint", "model_source"],
        "chain_prerequisite_details": {
            "production_grade_cost_evidence_passed": {"passed": True},
            "blind_lockbox_passed": {"passed": True},
            "paper_record_identity_fields_declared": {"passed": True},
        },
        "failed_binding_blocker_details": {},
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
    }
    lockbox_pass_conditions = {
        "independent_economic_candidates_gte_300": True,
        "symbols_gte_30": True,
        "long_gt_0": True,
        "short_gt_0": True,
        "after_cost_expectancy_gt_0": True,
        "expectancy_95pct_lower_bound_gt_0": True,
        "profit_factor_gte_1_5": True,
        "false_positive_rate_lte_0_40": True,
        "no_concentration_dimension_gt_30pct": True,
        "worst_1pct_loss_inside_risk_envelope": True,
        "point_in_time_violations_eq_0": True,
        "production_grade_cost_coverage_gte_95pct": True,
    }
    paper_binding_conditions = {
        "production_grade_cost_evidence_passed": True,
        "blind_lockbox_passed": True,
        "paper_record_identity_contract_declared": True,
        "paper_canary_forced_paper_only": True,
        "no_candidate_bound_rows_before_lockbox_pass": True,
        "no_partial_challenger_identity_rows": True,
        "no_routes_to_live": True,
    }
    forward_conditions = {
        "new_closed_challenger_economic_outcomes_gte_100": True,
        "symbols_gte_30": True,
        "long_gt_0": True,
        "short_gt_0": True,
        "after_cost_expectancy_gt_0": True,
        "profit_factor_gte_1_5": True,
        "accounting_mismatch_rows_eq_0": True,
        "liquidation_rows_eq_0": True,
        "point_in_time_violations_eq_0": True,
        "paper_only_no_live_routes": True,
    }

    payload = goal_requirement_traceability_matrix(
        **kwargs,
        cost_status={
            "status": "PASS",
            "required_coverage": 0.95,
                "production_grade_cost_coverage": 0.96,
                "unexplained_cost_missing_rows": 0,
                "replay_paper_cost_parity_mismatch_rows": 0,
                "replay_paper_cost_parity_comparable_rows": 100,
                "replay_paper_cost_parity_compared_side_count": 200,
                "field_coverage": {"order_size": {"coverage": 1.0, "missing_rows": 0}},
            "blocker_details": [],
            "hard_blocking_fields": [],
            "fallback_rows_may_be_shadow_scored": True,
            "fallback_rows_count_as_production_grade_training_lockbox_or_promotion_evidence": False,
            "paper_fill_allowed": False,
            "routes_to_live": False,
            "counts_as_a_grade_evidence": False,
            "promotion_evidence": False,
            "pass_conditions": {"replay_paper_cost_parity_for_same_snapshot_order": True},
        },
        cost_capture_gap={
            "fallback_rows_count_as_training_lockbox_or_promotion_evidence": False,
            "field_shortfalls": {},
        },
        runtime_cost_capture_contract={"status": "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"},
        runtime_cost_capture_operator_approval_receipt={"status": "PASS_RUNTIME_COST_CAPTURE_OPERATOR_APPROVAL_RECEIPT"},
        paper_cost_telemetry={"challenger_bound_production_grade_rows": 1},
        lockbox_pass_contract={
            "status": "PASS_BLIND_LOCKBOX_PASS_CONTRACT",
            "independent_economic_candidates": 300,
            "symbols": 30,
            "long_count": 150,
            "short_count": 150,
            "after_cost_expectancy_bps": 1.0,
            "expectancy_95pct_lower_bound_bps": 0.1,
            "profit_factor": 1.5,
            "false_positive_rate": 0.4,
            "max_concentration_pct": 0.3,
            "worst_1pct_loss_bps": -10,
            "point_in_time_violations": 0,
            "production_grade_cost_coverage": 0.96,
            "pass_conditions": lockbox_pass_conditions,
        },
        paper_canary_binding={
            "status": "READY_FOR_OPERATOR_REVIEW_BINDING_PREFLIGHT",
            "binding_allowed": True,
            "pass_conditions": paper_binding_conditions,
            "binding_prerequisite_details": {
                "production_grade_cost_evidence_passed": {"passed": True},
                "blind_lockbox_passed": {"passed": True},
                "paper_record_identity_contract_declared": {"passed": True},
                "paper_canary_forced_paper_only": {"passed": True},
                "no_candidate_bound_rows_before_lockbox_pass": {"passed": True},
                "no_partial_challenger_identity_rows": {"passed": True},
                "no_routes_to_live": {"passed": True},
            },
            "failed_binding_blocker_details": {},
        },
        forward_canary_contract={
            "status": "PASS_FORWARD_PAPER_CANARY_CONTRACT",
            "closed_challenger_economic_outcomes": 100,
            "symbols": 30,
            "long_count": 50,
            "short_count": 50,
            "after_cost_expectancy_bps": 1.0,
            "profit_factor": 1.5,
            "accounting_mismatch_rows": 0,
            "liquidation_rows": 0,
            "point_in_time_violations": 0,
            "live_route_rows": 0,
            "pass_conditions": forward_conditions,
        },
        goal_phase_completion={"goal_complete": True},
        added_paper_governance={
            "status": "PASS_ADDED_PAPER_GOVERNANCE_BLOCKER_AUDIT",
            "added_goal_id": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR",
            "source_generated_utc": "2026-06-25T20:08:37Z",
            "source_final_gate": "V2_PAPER_TIMEFRAME_ROUTING_CHURN_COST_AND_ECONOMIC_TRADE_GOVERNANCE_REPAIR_READY",
            "source_routing_status": "PASS_PAPER_TIMEFRAME_ROUTING_OWNER_AUDIT",
            "required_artifacts": list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "source_artifacts_written": list(ADDED_PAPER_GOVERNANCE_REQUIRED_ARTIFACTS),
            "missing_required_artifacts": [],
            "raw_close_record_count": 3573,
            "economic_trade_count": 250,
            "current_1m_share": 0.10,
            "current_1m_economic_trade_share": 0.20,
            "hardcoded_1m_path_count": 0,
            "silent_1m_fallback_path_count": 0,
            "timeframe_routing_violation_count": 0,
            "silent_1m_fallback_paths": [],
            "paper_churn_governor_status": "PASS_PAPER_CHURN_GOVERNOR_WIRED_TO_ENTRY_GATE",
            "operator_dashboard_truth_contract_status": "PASS_OPERATOR_DASHBOARD_WEBSITE_TRUTH_CONTRACT",
            "operator_dashboard_truth_contract_blocked_reasons": [],
            "operator_dashboard_missing_required_fields": [],
            "paper_edge_to_cost_gate_status": "PASS_PAPER_EDGE_TO_COST_GATE",
            "paper_entry_production_grade_cost_coverage": 0.95,
            "post_fix_paper_validation_status": "PASS_POST_FIX_PAPER_VALIDATION",
            "routes_to_live": False,
            "places_real_order": False,
            "pass_conditions": {
                "paper_governance_summary_present": True,
                "added_goal_id_matches": True,
                "required_artifacts_written": True,
                "current_closed_ledger_recomputed": True,
                "economic_trade_compaction_present": True,
                "current_timeframe_distribution_proven": True,
                "paper_routing_owner_audit_passed": True,
                "hardcoded_1m_economic_paths_removed": True,
                "silent_1m_fallbacks_absent": True,
                "paper_churn_governor_wired": True,
                "operator_dashboard_website_truth_contract_passed": True,
                "paper_edge_to_cost_gate_passed": True,
                "paper_entry_production_grade_cost_coverage_gte_95pct": True,
                "post_fix_paper_validation_passed": True,
                "source_paper_governance_blockers_cleared": True,
                "source_paper_governance_phase_blockers_cleared": True,
                "final_gate_ready": True,
                "no_live_routes": True,
            },
        },
    )

    assert payload["status"] == "PASS_GOAL_REQUIREMENT_TRACEABILITY_MATRIX"
    assert any(
        row["requirement_id"] == "phase_6.binding_prerequisite_details_published" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_1.cost_capture_recovery_plan_published" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "freeze.frozen_candidate_integrity_contract_published"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_1.production_cost_status_blocker_contract_published"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_1.production_grade_cost_evidence_passed"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_2.hash_chain_contract_published" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_6.paper_chain_binding_contract_published"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_5.blind_lockbox_pass_contract_passed"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_6.paper_canary_binding_allowed" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_6.paper_chain_binding_ready" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_6.paper_chain_components_ready" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_7.forward_paper_canary_contract_passed"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "added_paper_governance.added_paper_governance_blocker_audit_passed"
        and row["passed"] is True
        for row in payload["requirements"]
    )
    assert any(
        row["requirement_id"] == "phase_2.pending_decision_keys_unique" and row["passed"] is True
        for row in payload["requirements"]
    )
    assert payload["goal_complete"] is True
    assert payload["goal_requirement_traceability_status"] == payload["status"]
    assert payload["blocked_requirements"] == 0
    assert payload["blocked_requirement_count"] == 0
    assert payload["failed_requirement_count"] == 0
    assert payload["failed_requirements"] == 0
    assert payload["blocked_requirement_ids"] == []
    assert payload["passed_requirements"] == payload["total_requirements"]
    assert payload["passed_requirement_count"] == payload["passed_requirements"]
    assert payload["total_requirement_count"] == payload["total_requirements"]
    assert payload["requirements_total"] == payload["total_requirements"]
    assert payload["failed_by_phase"] == {}
    assert all(summary["blocked_requirements"] == 0 for summary in payload["requirements_by_phase"].values())
    assert all(payload["pass_conditions"].values())
    assert payload["promotion_evidence"] is True


def _drift_policy() -> SimpleNamespace:
    feature_names = ("ret_pct", "volume")
    return SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
        feature_names=feature_names,
        normalization=NormalizationSpec(
            feature_names=feature_names,
            means=(0.0, 10.0),
            stds=(1.0, 5.0),
            mins=(-1.0, 0.0),
            maxs=(1.0, 100.0),
        ),
    )


def _drift_cohort(row_count: int, observed_count: int, *, null_stats: bool = False) -> dict:
    value = None if null_stats else 1.0
    return {
        "row_count": row_count,
        "observed_value_count": observed_count,
        "mean": value,
        "standard_deviation": value,
        "quantiles": {
            "p01": value,
            "p05": value,
            "p25": value,
            "p50": value,
            "p75": value,
            "p95": value,
            "p99": value,
        },
        "missing_rate": None if row_count == 0 else 0.0,
        "stale_rate": None if row_count == 0 else 0.0,
        "psi_vs_training": None if null_stats else 0.0,
        "ks_statistic_vs_training": None if null_stats else 0.0,
        "out_of_training_range_rate": None if row_count == 0 else 0.0,
    }


def _complete_drift_status() -> dict:
    features = {}
    for feature in ("ret_pct", "volume"):
        features[feature] = {
            "training": _drift_cohort(10, 10),
            "validation": _drift_cohort(5, 5),
            "previous_holdout": _drift_cohort(2, 2),
            "current_runtime": _drift_cohort(3, 3),
            "future_lockbox": _drift_cohort(4, 4),
        }
    return {
        "feature_count": 2,
        "feature_names": ["ret_pct", "volume"],
        "cohort_row_counts": {
            "training": 10,
            "validation": 5,
            "previous_holdout": 2,
            "current_runtime": 3,
            "future_lockbox": 4,
        },
        "cohorts": {
            "training": {"row_count": 10, "counts_as_promotion_evidence": False},
            "validation": {"row_count": 5, "counts_as_promotion_evidence": False},
            "previous_holdout": {"row_count": 2, "counts_as_promotion_evidence": False},
            "current_runtime": {"row_count": 3, "counts_as_promotion_evidence": False},
            "future_lockbox": {"row_count": 4, "counts_as_promotion_evidence": False},
        },
        "root_cause_classification": "GENUINE_RUNTIME_DISTRIBUTION_SHIFT_OR_TRAINING_RANGE_EXHAUSTION",
        "broken_transformation_or_source_mapping_detected": False,
        "candidate_id_change_required": False,
        "frozen_candidate_kept": True,
        "high_drift_features_current_runtime": [],
        "feature_distribution": features,
        "promotion_evidence": False,
    }


def _complete_drift_status_with_parity() -> dict:
    drift_status = _complete_drift_status()
    drift_status["feature_parity_status"] = {
        "status": "PASS",
        "schema_mismatch_rows": 0,
        "normalization_mismatch_rows": 0,
        "unexplained_missing_feature_rows": 0,
        "current_integrity_pass_rate": 1.0,
    }
    drift_status["feature_distribution"]["ret_pct"]["current_runtime"]["psi_vs_training"] = 0.3
    drift_status["feature_distribution"]["ret_pct"]["future_lockbox"]["psi_vs_training"] = 0.35
    drift_status["high_drift_features_current_runtime"] = ["ret_pct"]
    return drift_status


def _drift_snapshot(snapshot_id: str, ret_pct: float, volume: float) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
        "candle_close_time": "2026-06-25T00:00:00Z",
        "candle_closed_confirmed": True,
        "trainer_consumable": True,
        "features": {
            "ret_pct": ret_pct,
            "volume": volume,
        },
    }


def test_distribution_drift_root_cause_artifact_publishes_contract_and_summaries() -> None:
    policy = _drift_policy()
    replay_rows = [
        SimpleNamespace(snapshot=_drift_snapshot("train-1", 0.0, 10.0)),
        SimpleNamespace(snapshot=_drift_snapshot("train-2", 0.1, 11.0)),
        SimpleNamespace(snapshot=_drift_snapshot("train-3", -0.1, 9.0)),
        SimpleNamespace(snapshot=_drift_snapshot("valid-1", 0.2, 12.0)),
    ]

    payload = distribution_drift_artifact(
        policy=policy,
        replay_rows=replay_rows,
        current_snapshots=[
            _drift_snapshot("runtime-1", 2.0, 15.0),
            _drift_snapshot("runtime-2", 2.1, 16.0),
        ],
        previous_holdout_rows=[
            {
                "feature_values_by_name": {"ret_pct": 0.0, "volume": 10.0},
                "decision_time": "2026-06-25T00:01:00Z",
                "feature_cutoff": "2026-06-25T00:00:00Z",
                "available_at": "2026-06-25T00:00:30Z",
            },
        ],
        future_lockbox_rows=[
            {
                "feature_values_by_name": {"ret_pct": 2.0, "volume": 15.0},
                "decision_time": "2026-06-25T00:01:00Z",
                "feature_cutoff": "2026-06-25T00:00:00Z",
                "available_at": "2026-06-25T00:00:30Z",
            },
        ],
        feature_parity_status={
            "status": "PASS",
            "schema_mismatch_rows": 0,
            "normalization_mismatch_rows": 0,
            "unexplained_missing_feature_rows": 0,
        },
    )

    assert payload["status"] == "PASS_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT"
    assert payload["feature_count"] == len(policy.feature_names)
    assert payload["policy_feature_count"] == len(policy.feature_names)
    assert payload["expected_feature_count"] == len(policy.feature_names)
    assert payload["required_feature_count"] == len(policy.feature_names)
    assert payload["all_policy_features_present"] is True
    assert payload["all_32_features_present"] is False
    assert payload["features"] == list(policy.feature_names)
    assert "stale_rate" in payload["required_metrics"]
    assert payload["required_cohorts"] == ["training", "validation", "previous_holdout", "current_runtime", "future_lockbox"]
    assert payload["rows"] == payload["cohort_row_counts"]
    assert payload["pass_conditions"]["all_required_cohorts_have_rows_for_drift_comparison"] is True
    assert payload["pass_conditions"]["all_required_drift_metric_keys_published"] is True
    assert payload["pass_conditions"]["all_required_drift_metric_values_available"] is True
    assert payload["pass_conditions"]["complete_required_drift_metric_coverage"] is True
    assert payload["pass_conditions"]["previous_holdout_diagnostic_comparison_rows_gt_0"] is True
    assert payload["pass_conditions"]["previous_holdout_not_promotion_or_lockbox_evidence"] is True
    assert payload["pass_conditions"]["candidate_change_decision_matches_root_cause"] is True
    assert payload["blocker_details"] == []
    assert payload["missing_required_metrics_by_feature"] == {}
    assert payload["missing_required_quantiles_by_feature"] == {}
    assert payload["null_required_metrics_by_feature"] == {}
    assert payload["null_required_quantiles_by_feature"] == {}
    assert payload["drift_metric_publish_contract"]["complete_required_drift_metric_feature_count"] == len(
        policy.feature_names
    )
    assert payload["feature_metric_coverage_summary"]["ret_pct"]["complete_required_drift_metric_coverage"] is True
    assert payload["candidate_id_change_required"] is False
    assert payload["frozen_candidate_kept"] is True
    assert payload["root_cause"] == payload["root_cause_classification"]
    assert payload["drift_root_cause"] == payload["root_cause_classification"]
    assert payload["genuine_market_regime_change_detected"] is True
    assert payload["candidate_change_decision"] == "KEEP_FROZEN_CANDIDATE_AND_REJECT_DRIFTED_RUNTIME_CONDITIONS"
    assert payload["candidate_action"] == payload["candidate_change_decision"]
    assert payload["frozen_candidate_action"] == "reject_drifted_runtime_conditions_without_tuning"
    assert payload["root_cause_summary"]["classification"] == payload["root_cause_classification"]
    assert payload["root_cause_summary"]["feature_count"] == len(policy.feature_names)
    assert payload["root_cause_summary"]["all_policy_features_present"] is True
    assert payload["features_requiring_new_candidate_if_fixed"] == []
    assert payload["drift_decision_contract"]["new_candidate_required_if_any_feature_mapping_or_normalization_changes"] is True
    assert payload["drift_decision_contract"]["frozen_candidate_tuning_allowed_from_drift_results"] is False
    assert payload["drift_decision_contract"]["runtime_reject_drifted_conditions"] is True
    assert payload["drift_decision_contract"]["places_real_order"] is False
    assert payload["drift_decision_contract"]["promotion_evidence"] is False
    assert payload["cohorts"]["current_runtime"]["row_count"] == 2
    assert payload["feature_distribution"]["ret_pct"]["future_lockbox"]["stale_rate"] == 0.0
    assert payload["training_row_count"] == 2
    assert payload["validation_row_count"] == 1
    assert payload["previous_holdout_row_count"] == 1
    assert payload["current_runtime_row_count"] == 2
    assert payload["future_lockbox_row_count"] == 1
    assert payload["current_runtime_status"] == "AVAILABLE_FOR_DRIFT_COMPARISON"
    assert payload["future_lockbox_status"] == "AVAILABLE_FOR_DRIFT_COMPARISON"
    assert payload["missing_or_stale_summary"]["current_runtime"]["missing_rate"]["known_rate_feature_count"] == 2
    assert payload["out_of_training_range_summary"]["current_runtime"]["out_of_training_range_rate"][
        "features_at_or_above_threshold"
    ] == ["ret_pct"]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["pass_conditions"]["places_real_order_false"] is True
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_replay_drift_split_uses_chronological_70_15_15_tail() -> None:
    rows = [SimpleNamespace(snapshot=_drift_snapshot(f"row-{idx}", float(idx), 10.0 + idx)) for idx in range(10)]

    payload = replay_drift_split(rows)

    assert payload["split_policy"] == "chronological_70_15_15_replay_drift_diagnostic_only"
    assert payload["training_row_count"] == 7
    assert payload["validation_row_count"] == 1
    assert payload["previous_holdout_row_count"] == 2
    assert [row.snapshot["snapshot_id"] for row in payload["previous_holdout_rows"]] == ["row-8", "row-9"]
    assert payload["counts_as_promotion_evidence"] is False


def test_distribution_drift_root_cause_can_use_replay_tail_as_diagnostic_previous_holdout() -> None:
    policy = _drift_policy()
    replay_rows = [
        SimpleNamespace(snapshot=_drift_snapshot(f"replay-{idx}", idx / 10.0, 10.0 + idx))
        for idx in range(10)
    ]

    payload = distribution_drift_artifact(
        policy=policy,
        replay_rows=replay_rows,
        current_snapshots=[
            _drift_snapshot("runtime-1", 2.0, 15.0),
            _drift_snapshot("runtime-2", 2.1, 16.0),
        ],
        previous_holdout_rows=[],
        future_lockbox_rows=[
            {
                "feature_values_by_name": {"ret_pct": 2.0, "volume": 15.0},
                "decision_time": "2026-06-25T00:01:00Z",
                "feature_cutoff": "2026-06-25T00:00:00Z",
                "available_at": "2026-06-25T00:00:30Z",
            },
        ],
        feature_parity_status={
            "status": "PASS",
            "schema_mismatch_rows": 0,
            "normalization_mismatch_rows": 0,
            "unexplained_missing_feature_rows": 0,
        },
        use_replay_tail_as_previous_holdout=True,
    )

    assert payload["status"] == "PASS_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT"
    assert payload["cohort_row_counts"] == {
        "training": 7,
        "validation": 1,
        "previous_holdout": 2,
        "current_runtime": 2,
        "future_lockbox": 1,
    }
    assert payload["previous_holdout_source"] == "replay_tail_chronological_previous_holdout_diagnostic_only"
    assert payload["previous_holdout_origin"] == "derived_from_replay_tail_after_freeze_for_distribution_diagnosis_only"
    assert payload["previous_holdout_diagnostic_surrogate_used"] is True
    assert payload["previous_holdout_is_original_model_selection_holdout"] is False
    assert payload["previous_holdout_used_for_model_or_threshold_selection"] is False
    assert payload["previous_holdout_counts_as_promotion_evidence"] is False
    assert payload["previous_holdout_counts_as_blind_lockbox_evidence"] is False
    assert payload["cohorts"]["previous_holdout"]["comparison_available"] is True
    assert payload["pass_conditions"]["all_required_cohorts_have_rows_for_drift_comparison"] is True
    assert payload["pass_conditions"]["previous_holdout_diagnostic_comparison_rows_gt_0"] is True
    assert payload["pass_conditions"]["previous_holdout_not_promotion_or_lockbox_evidence"] is True


def test_distribution_drift_root_cause_blocks_empty_previous_holdout_diagnostic_comparison() -> None:
    policy = _drift_policy()
    replay_rows = [
        SimpleNamespace(snapshot=_drift_snapshot("train-1", 0.0, 10.0)),
        SimpleNamespace(snapshot=_drift_snapshot("train-2", 0.1, 11.0)),
        SimpleNamespace(snapshot=_drift_snapshot("train-3", -0.1, 9.0)),
        SimpleNamespace(snapshot=_drift_snapshot("valid-1", 0.2, 12.0)),
    ]

    payload = distribution_drift_artifact(
        policy=policy,
        replay_rows=replay_rows,
        current_snapshots=[
            _drift_snapshot("runtime-1", 2.0, 15.0),
            _drift_snapshot("runtime-2", 2.1, 16.0),
        ],
        previous_holdout_rows=[],
        future_lockbox_rows=[
            {
                "feature_values_by_name": {"ret_pct": 2.0, "volume": 15.0},
                "decision_time": "2026-06-25T00:01:00Z",
                "feature_cutoff": "2026-06-25T00:00:00Z",
                "available_at": "2026-06-25T00:00:30Z",
            },
        ],
        feature_parity_status={
            "status": "PASS",
            "schema_mismatch_rows": 0,
            "normalization_mismatch_rows": 0,
            "unexplained_missing_feature_rows": 0,
        },
    )

    assert payload["status"] == "FAIL_DISTRIBUTION_DRIFT_ROOT_CAUSE_AUDIT"
    assert payload["pass_conditions"]["all_required_cohorts_have_rows_for_drift_comparison"] is False
    assert payload["pass_conditions"]["all_required_drift_metric_values_available"] is False
    assert payload["pass_conditions"]["previous_holdout_diagnostic_comparison_rows_gt_0"] is False
    assert payload["cohorts"]["previous_holdout"]["comparison_available"] is False
    assert "incomplete" in payload["previous_holdout_note"]
    assert "previous_holdout_diagnostic_comparison_rows_gt_0" in payload["blocked_reasons"]
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert {
        "all_required_cohorts_have_rows_for_drift_comparison",
        "previous_holdout_diagnostic_comparison_rows_gt_0",
    }.issubset({detail["pass_condition"] for detail in payload["blocker_details"]})


def test_distribution_drift_coverage_audit_passes_complete_artifact() -> None:
    payload = distribution_drift_coverage_audit(
        policy=_drift_policy(),
        drift_status=_complete_drift_status(),
    )

    assert payload["status"] == "PASS_DRIFT_COVERAGE_AUDIT"
    assert payload["policy_feature_count"] == 2
    assert payload["required_feature_count"] == 2
    assert payload["required_cohort_count"] == 5
    assert payload["reported_required_cohort_count"] == 5
    assert payload["cohorts_present"] == ["training", "validation", "previous_holdout", "current_runtime", "future_lockbox"]
    assert payload["reported_all_required_features"] is True
    assert payload["missing_required_metric_total"] == 0
    assert payload["required_non_holdout_empty_or_unobserved_total"] == 0
    assert payload["required_all_cohort_empty_or_unobserved_total"] == 0
    assert payload["drift_coverage_blocker_details"] == []
    assert payload["pass_conditions"]["all_required_metric_keys_present"] is True
    assert payload["pass_conditions"]["all_required_metric_values_present"] is True
    assert payload["pass_conditions"]["complete_required_drift_metric_coverage"] is True
    assert payload["pass_conditions"]["top_level_feature_and_cohort_summary_present"] is True
    assert payload["pass_conditions"]["all_required_cohorts_have_rows_for_drift_comparison"] is True
    assert payload["pass_conditions"]["previous_holdout_diagnostic_comparison_rows_gt_0"] is True
    assert payload["pass_conditions"]["previous_holdout_not_reused_for_promotion"] is True
    assert payload["missing_required_metrics_by_feature"] == {}
    assert payload["missing_required_quantiles_by_feature"] == {}
    assert payload["null_required_metrics_by_feature"] == {}
    assert payload["null_required_quantiles_by_feature"] == {}
    assert payload["complete_required_drift_metric_feature_count"] == 2
    assert payload["features_with_complete_required_drift_metric_coverage"] == ["ret_pct", "volume"]
    assert payload["feature_metric_coverage_summary"]["ret_pct"]["required_metric_key_count"] == 50
    assert payload["feature_metric_coverage_summary"]["ret_pct"]["complete_required_drift_metric_coverage"] is True
    assert payload["drift_metric_publish_contract"]["required_metric_cell_count"] == 100
    assert payload["missing_metric_key_counts"] == {}
    assert payload["required_non_holdout_empty_or_unobserved_counts"] == {}
    assert payload["counts_as_a_grade_evidence"] is False


def test_distribution_drift_coverage_audit_blocks_empty_previous_holdout() -> None:
    drift_status = _complete_drift_status()
    drift_status["cohort_row_counts"]["previous_holdout"] = 0
    drift_status["cohorts"]["previous_holdout"]["row_count"] = 0
    for feature_payload in drift_status["feature_distribution"].values():
        feature_payload["previous_holdout"] = _drift_cohort(0, 0, null_stats=True)

    payload = distribution_drift_coverage_audit(
        policy=_drift_policy(),
        drift_status=drift_status,
    )

    assert payload["status"] == "FAIL_DRIFT_COVERAGE_AUDIT"
    assert payload["pass_conditions"]["all_required_cohorts_have_rows_for_drift_comparison"] is False
    assert payload["pass_conditions"]["previous_holdout_diagnostic_comparison_rows_gt_0"] is False
    assert payload["required_all_cohort_empty_or_unobserved_counts"] == {"previous_holdout": 2}
    assert "previous_holdout_diagnostic_comparison_rows_gt_0" in payload["blocked_reasons"]
    assert payload["blocker_details"] == payload["drift_coverage_blocker_details"]
    assert payload["failed_blocker_details"] == payload["drift_coverage_blocker_details"]
    assert {
        "all_required_cohorts_have_rows_for_drift_comparison",
        "previous_holdout_diagnostic_comparison_rows_gt_0",
    }.issubset({detail["pass_condition"] for detail in payload["drift_coverage_blocker_details"]})


def test_distribution_drift_mapping_confidence_audit_passes_clean_parity_shift() -> None:
    drift_status = _complete_drift_status_with_parity()
    coverage = distribution_drift_coverage_audit(policy=_drift_policy(), drift_status=drift_status)

    payload = distribution_drift_mapping_confidence_audit(
        policy=_drift_policy(),
        drift_status=drift_status,
        drift_coverage=coverage,
    )

    assert payload["status"] == "PASS_DRIFT_MAPPING_CONFIDENCE_AUDIT"
    assert payload["candidate_id_change_required"] is False
    assert payload["frozen_candidate_kept"] is True
    assert payload["computed_high_drift_features_current_runtime"] == ["ret_pct"]
    assert payload["high_drift_feature_count_current_runtime"] == 1
    assert payload["computed_high_drift_feature_count_current_runtime"] == 1
    assert payload["mapping_suspicion_feature_count"] == 0
    assert payload["genuine_shift_support_feature_count"] == 1
    assert payload["features_requiring_new_candidate_if_fixed"] == []
    assert payload["drift_mapping_blocker_details"] == []
    assert payload["drift_decision_contract"]["mapping_fix_required"] is False
    assert payload["drift_decision_contract"]["runtime_reject_drifted_conditions"] is True
    assert payload["drift_decision_contract"]["places_real_order"] is False
    assert payload["drift_decision_contract"]["promotion_evidence"] is False
    assert payload["drift_decision_contract"]["frozen_candidate_tuning_allowed_from_drift_results"] is False
    assert payload["pass_conditions"]["feature_parity_status_passed"] is True
    assert payload["pass_conditions"]["reported_high_drift_features_match_computed_thresholds"] is True
    assert payload["feature_diagnosis"][0]["feature_root_cause"] == "LIKELY_GENUINE_DISTRIBUTION_SHIFT_OR_TRAINING_RANGE_EXHAUSTION"
    assert "shared_replay_runtime_feature_adapter_parity_passed" in payload["feature_diagnosis"][0]["genuine_shift_support_reasons"]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_distribution_drift_mapping_confidence_blocks_incomplete_coverage_without_new_candidate_id() -> None:
    drift_status = _complete_drift_status_with_parity()
    drift_status["cohort_row_counts"]["previous_holdout"] = 0
    drift_status["cohorts"]["previous_holdout"]["row_count"] = 0
    for feature_payload in drift_status["feature_distribution"].values():
        feature_payload["previous_holdout"] = _drift_cohort(0, 0, null_stats=True)
    coverage = distribution_drift_coverage_audit(policy=_drift_policy(), drift_status=drift_status)

    payload = distribution_drift_mapping_confidence_audit(
        policy=_drift_policy(),
        drift_status=drift_status,
        drift_coverage=coverage,
    )

    assert payload["status"] == "FAIL_DRIFT_MAPPING_CONFIDENCE_AUDIT"
    assert payload["pass_conditions"]["drift_coverage_audit_passed"] is False
    assert payload["broken_transformation_or_source_mapping_detected"] is False
    assert payload["candidate_id_change_required"] is False
    assert payload["frozen_candidate_kept"] is True
    assert payload["drift_evidence_incomplete_without_mapping_fix"] is True
    assert payload["features_requiring_new_candidate_if_fixed"] == []
    assert payload["blocked_reasons"] == ["drift_coverage_audit_passed"]
    assert payload["blocker_details"] == payload["drift_mapping_blocker_details"]
    assert payload["failed_blocker_details"] == payload["drift_mapping_blocker_details"]
    assert payload["drift_decision_contract"]["mapping_fix_required"] is False
    assert payload["drift_decision_contract"]["candidate_id_change_required"] is False


def test_distribution_drift_mapping_confidence_audit_fails_schema_mismatch() -> None:
    drift_status = _complete_drift_status_with_parity()
    drift_status["feature_parity_status"]["status"] = "FAIL"
    drift_status["feature_parity_status"]["schema_mismatch_rows"] = 2
    coverage = distribution_drift_coverage_audit(policy=_drift_policy(), drift_status=drift_status)

    payload = distribution_drift_mapping_confidence_audit(
        policy=_drift_policy(),
        drift_status=drift_status,
        drift_coverage=coverage,
    )

    assert payload["status"] == "FAIL_DRIFT_MAPPING_CONFIDENCE_AUDIT"
    assert payload["broken_transformation_or_source_mapping_detected"] is True
    assert payload["candidate_id_change_required"] is True
    assert payload["frozen_candidate_kept"] is False
    assert payload["pass_conditions"]["feature_parity_status_passed"] is False
    assert payload["pass_conditions"]["schema_mismatch_rows_eq_0"] is False
    assert "schema_mismatch_rows_eq_0" in {detail["pass_condition"] for detail in payload["drift_mapping_blocker_details"]}
    assert payload["drift_decision_contract"]["mapping_fix_required"] is True
    assert payload["features_requiring_new_candidate_if_fixed"] == ["ret_pct", "volume"]


def test_distribution_drift_coverage_audit_detects_missing_metric_key() -> None:
    drift_status = _complete_drift_status()
    del drift_status["feature_distribution"]["ret_pct"]["current_runtime"]["psi_vs_training"]

    payload = distribution_drift_coverage_audit(
        policy=_drift_policy(),
        drift_status=drift_status,
    )

    assert payload["status"] == "FAIL_DRIFT_COVERAGE_AUDIT"
    assert payload["missing_metric_key_counts"]["current_runtime.psi_vs_training"] == 1
    assert payload["missing_required_metrics_by_feature"]["ret_pct"]["missing_metrics_by_cohort"][
        "current_runtime"
    ] == ["psi_vs_training"]
    assert payload["missing_required_metric_total"] == 1
    assert payload["drift_coverage_blocker_details"][0]["passed"] is False
    assert payload["pass_conditions"]["all_required_metric_keys_present"] is False
    assert payload["pass_conditions"]["complete_required_drift_metric_coverage"] is False


def test_distribution_drift_coverage_audit_detects_null_required_metric_value() -> None:
    drift_status = _complete_drift_status()
    drift_status["feature_distribution"]["ret_pct"]["future_lockbox"]["stale_rate"] = None

    payload = distribution_drift_coverage_audit(
        policy=_drift_policy(),
        drift_status=drift_status,
    )

    assert payload["status"] == "FAIL_DRIFT_COVERAGE_AUDIT"
    assert payload["pass_conditions"]["all_required_metric_values_present"] is False
    assert payload["pass_conditions"]["complete_required_drift_metric_coverage"] is False
    assert payload["null_required_metrics_by_feature"]["ret_pct"]["null_metrics_by_cohort"][
        "future_lockbox"
    ] == ["stale_rate"]
    assert "all_required_metric_values_present" in payload["blocked_reasons"]


def test_append_pending_lockbox_is_idempotent(tmp_path) -> None:
    scored = {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_vector_hash": "features",
        "feature_values_by_name": {"close": 100.0},
        "predicted_direction": "LONG",
        "predicted_move_bps": 5.0,
        "score": 5.0,
        "estimated_production_cost": {"fallback": True},
        "selected": False,
        "rejected": True,
        "rejection_reasons": ["cost_not_production_grade"],
    }

    first = append_pending_lockbox(tmp_path, [scored])
    second = append_pending_lockbox(tmp_path, [scored])

    assert first["new_pending_rows_appended"] == 1
    assert second["new_pending_rows_appended"] == 0
    assert second["pending_rows_after_append"] == 1
    assert second["immutability_conflict_count"] == 0


def test_append_pending_lockbox_deduplicates_same_batch(tmp_path) -> None:
    scored = {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_vector_hash": "features",
        "feature_values_by_name": {"close": 100.0},
        "predicted_direction": "LONG",
        "predicted_move_bps": 5.0,
        "score": 5.0,
        "estimated_production_cost": {"fallback": True},
        "selected": False,
        "rejected": True,
        "rejection_reasons": ["cost_not_production_grade"],
    }

    status = append_pending_lockbox(tmp_path, [scored, scored])

    assert status["new_pending_rows_appended"] == 1
    assert status["pending_rows_after_append"] == 1
    assert status["immutability_conflict_count"] == 0


def test_append_pending_lockbox_detects_selection_conflict(tmp_path) -> None:
    scored = {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_vector_hash": "features",
        "feature_values_by_name": {"close": 100.0},
        "predicted_direction": "LONG",
        "predicted_move_bps": 5.0,
        "score": 5.0,
        "estimated_production_cost": {"fallback": True},
        "selected": False,
        "rejected": True,
        "rejection_reasons": ["cost_not_production_grade"],
    }
    rewritten = dict(scored)
    rewritten["selected"] = True
    rewritten["rejected"] = False
    rewritten["rejection_reasons"] = []

    first = append_pending_lockbox(tmp_path, [scored])
    second = append_pending_lockbox(tmp_path, [rewritten])

    assert first["new_pending_rows_appended"] == 1
    assert second["new_pending_rows_appended"] == 0
    assert second["pending_rows_after_append"] == 1
    assert second["immutability_conflict_count"] == 1


def test_psi_statistic_detects_distribution_shift() -> None:
    reference = [0.0, 1.0, 2.0, 3.0, 4.0] * 20
    same = [0.0, 1.0, 2.0, 3.0, 4.0] * 20
    shifted = [10.0, 11.0, 12.0, 13.0, 14.0] * 20

    assert psi_statistic(reference, same) == 0.0
    assert (psi_statistic(reference, shifted) or 0.0) > 1.0


def test_point_in_time_violation_count_rejects_unavailable_features() -> None:
    clean = {
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
    }
    leaked = {
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:01:01Z",
    }

    assert point_in_time_violation_count([clean, leaked]) == 1


def test_temporal_semantics_audit_passes_distinct_timestamp_ordering() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    pending = {
        "lockbox_record_id": "record-1",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
        "record_created_utc": "2026-06-25T00:01:01Z",
    }
    label = {
        **pending,
        "label_source_timestamp": "2026-06-25T00:02:00Z",
        "label_created_utc": "2026-06-25T00:02:01Z",
        "label_uses_future_data_as_label_only": True,
    }
    shadow = {
        **pending,
        "record_created_utc": "2026-06-25T00:01:02Z",
        "source_event_time_est": "2026-06-25T00:00:00Z",
    }

    payload = temporal_semantics_audit(
        policy=policy,
        pending_rows=[pending],
        labelled_rows=[label],
        shadow_cost_rows=[shadow],
    )

    assert payload["status"] == "PASS_TEMPORAL_SEMANTICS_AUDIT"
    assert payload["violation_counts"] == {}
    assert payload["point_in_time_violations"] == 0
    assert payload["feature_available_after_decision_rows"] == 0
    assert payload["available_at_after_decision_rows"] == 0
    assert payload["feature_cutoff_after_decision_rows"] == 0
    assert payload["decision_input_event_time_after_decision_rows"] == 0
    assert payload["event_time_after_available_at_rows"] == 0
    assert payload["masa_feature_cutoff_after_ppo_decision_rows"] == 0
    assert payload["execution_time_before_decision_rows"] == 0
    assert payload["lockbox_label_event_time_not_after_decision_rows"] == 0
    assert payload["lockbox_label_future_data_flag_not_true_rows"] == 0
    assert payload["unfinished_higher_timeframe_candle_rows"] == 0
    assert payload["pass_conditions"]["timestamp_fields_are_distinguished"] is True
    assert payload["pass_conditions"]["available_at_lte_decision_time"] is True
    assert payload["pass_conditions"]["masa_feature_cutoff_lte_ppo_decision_time"] is True
    assert payload["cohorts"]["future_lockbox_labelled"]["field_coverage"]["event_time"]["aliases_observed"] == {
        "label_source_timestamp": 1,
    }
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_temporal_semantics_audit_detects_timestamp_and_masa_ordering_violations() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    pending = {
        "lockbox_record_id": "record-1",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:01:01Z",
        "available_at": "2026-06-25T00:01:02Z",
        "masa_feature_cutoff": "2026-06-25T00:01:03Z",
        "candle_closed_confirmed": False,
    }
    label = {
        "lockbox_record_id": "record-1",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
        "label_source_timestamp": "2026-06-25T00:00:59Z",
        "label_uses_future_data_as_label_only": False,
    }

    payload = temporal_semantics_audit(
        policy=policy,
        pending_rows=[pending],
        labelled_rows=[label],
        shadow_cost_rows=[],
    )

    assert payload["status"] == "FAIL_TEMPORAL_SEMANTICS_AUDIT"
    assert payload["violation_counts"]["feature_cutoff_after_decision_time"] == 1
    assert payload["violation_counts"]["available_at_after_decision_time"] == 1
    assert payload["violation_counts"]["masa_feature_cutoff_after_ppo_decision_time"] == 1
    assert payload["violation_counts"]["label_event_time_not_after_decision_time"] == 1
    assert payload["violation_counts"]["label_future_data_flag_not_true"] == 1
    assert payload["violation_counts"]["unfinished_higher_timeframe_candle_used"] == 1
    assert payload["point_in_time_violations"] == 6
    assert payload["feature_cutoff_after_decision_rows"] == 1
    assert payload["feature_available_after_decision_rows"] == 1
    assert payload["available_at_after_decision_rows"] == 1
    assert payload["masa_feature_cutoff_after_ppo_decision_rows"] == 1
    assert payload["lockbox_label_event_time_not_after_decision_rows"] == 1
    assert payload["lockbox_label_future_data_flag_not_true_rows"] == 1
    assert payload["unfinished_higher_timeframe_candle_rows"] == 1
    assert payload["pass_conditions"]["required_temporal_fields_present"] is True
    assert payload["pass_conditions"]["no_explicit_unfinished_higher_timeframe_candles"] is False
    assert payload["promotion_evidence"] is False


def test_source_presence_matrix_identifies_recovery_boundaries() -> None:
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "snap-1",
        "decision_time": "2026-06-25T00:01:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "features": {
            "actual_observed_spread_entry_bps": 2.0,
            "orderbook_depth_usd": 10_000.0,
            "fee_bps": 4.0,
            "funding_rate": 0.0001,
            "mark_price": 100.0,
            "index_price": 99.9,
        },
    }

    assert source_presence_for_required_field(row, "observed_bid_ask_spread") == (
        True,
        "features.actual_observed_spread_entry_bps",
    )
    assert source_presence_for_required_field(row, "order_size") == (False, None)
    summary = summarize_source_presence([row], source_context="test")

    assert summary["fields"]["order_size"]["coverage"] == 0.0
    assert summary["fields"]["order_size"]["recovery_boundary"] == "adaptive_allocator_or_paper_intent_pre_submit"
    assert summary["fields"]["fallback_flag"]["coverage"] == 1.0
    assert summary["fields"]["fee_schedule"]["coverage"] == 1.0


def test_zero_notional_does_not_satisfy_production_grade_order_size() -> None:
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "feature_freshness_state": "CURRENT",
        "order_size_usd": 0.0,
        "target_notional_usdt": 0.0,
        "depth_price_impact_bps": 0.0,
        "features": {
            "actual_observed_spread_entry_bps": 2.0,
            "orderbook_depth_usd": 10_000.0,
            "fee_bps": 4.0,
            "expected_funding_bps": 0.1,
            "mark_price": 100.0,
            "index_price": 100.0,
        },
    }

    evidence = cost_evidence_for_row(row, source_context="current_runtime")
    summary = summarize_source_presence([row], source_context="test")

    assert evidence["evidence_flags"]["order_size"] is False
    assert "order_size" in evidence["missing_evidence_fields"]
    assert source_presence_for_required_field(row, "order_size") == (False, None)
    assert summary["fields"]["order_size"]["coverage"] == 0.0
    assert summary["fields"]["depth_evidence"]["coverage"] == 1.0
    assert summary["fields"]["depth_derived_price_impact"]["coverage"] == 1.0


def test_positive_notional_satisfies_order_size_source_presence() -> None:
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:01Z",
        "order_size_usd": 100.0,
        "orderbook_depth_usd": 10_000.0,
    }

    assert source_presence_for_required_field(row, "order_size") == (True, "row.order_size_usd")
    assert source_presence_for_required_field(row, "depth_derived_price_impact") == (
        True,
        "row.orderbook_depth_usd+row.order_size_usd",
    )


def test_parse_orderbook_top_book_recovers_pit_cost_evidence_fields() -> None:
    top_book = parse_orderbook_top_book(
        {
            "T": 1782400000000,
            "bids": [["100.0", "2.0"], ["99.5", "3.0"]],
            "asks": [["101.0", "4.0"], ["101.5", "5.0"]],
        },
        source_key="v2:market:orderbook:binance:BTCUSDT",
    )

    assert top_book is not None
    assert top_book["best_bid"] == 100.0
    assert top_book["best_ask"] == 101.0
    assert top_book["top_book_bid_depth_usd"] == 200.0
    assert top_book["top_book_ask_depth_usd"] == 404.0
    assert top_book["top_book_source_timestamp"] == "2026-06-25T15:06:40.000Z"

    row = {
        "decision_time": "2026-06-25T17:47:00Z",
        "available_at": "2026-06-25T17:46:45Z",
        "feature_cutoff": "2026-06-25T17:46:00Z",
        **top_book,
    }
    assert source_presence_for_required_field(row, "top_book_evidence")[0] is True
    assert source_presence_for_required_field(row, "depth_evidence")[0] is True


def test_parse_orderbook_top_book_rejects_crossed_book() -> None:
    top_book = parse_orderbook_top_book(
        {"T": 1782400000000, "bids": [["102.0", "2.0"]], "asks": [["101.0", "4.0"]]},
        source_key="v2:market:orderbook:binance:BTCUSDT",
    )

    assert top_book is None


def test_top_book_enrichment_reports_partial_coverage_blocker(monkeypatch) -> None:
    class FakeRedisClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def ping(self) -> bool:
            return True

        def get(self, key: str) -> str | None:
            payloads = {
                "v2:market:orderbook:binance:BTCUSDT": json.dumps(
                    {
                        "T": 1782345630000,
                        "bids": [["100.0", "2.0"]],
                        "asks": [["100.5", "3.0"]],
                    }
                )
            }
            return payloads.get(key)

    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=FakeRedisClient))

    enriched, status = enrich_current_snapshots_with_top_book(
        [
            {
                "feature_snapshot_id": "snap-1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "decision_time": "2026-06-25T00:01:00Z",
            },
            {
                "feature_snapshot_id": "snap-2",
                "symbol": "ETHUSDT",
                "timeframe": "1m",
                "decision_time": "2026-06-25T00:01:00Z",
            },
        ]
    )

    assert enriched[0]["best_bid"] == 100.0
    assert "best_bid" not in enriched[1]
    assert status["status"] == "BLOCKED_TOP_BOOK_ENRICHMENT_INCOMPLETE"
    assert status["top_book_enriched_rows"] == 1
    assert status["top_book_missing_rows"] == 1
    assert status["top_book_enrichment_coverage"] == 0.5
    assert status["required_top_book_enrichment_coverage"] == 0.95
    assert status["pass_conditions"]["top_book_enrichment_coverage_gte_95pct"] is False
    assert status["pass_conditions"]["top_book_missing_rows_eq_0"] is False
    assert status["blocked_reasons"] == [
        "top_book_enrichment_coverage_gte_95pct",
        "top_book_missing_rows_eq_0",
    ]
    assert {
        detail["pass_condition"] for detail in status["blocker_details"]
    } == set(status["blocked_reasons"])
    assert status["failed_blocker_details"] == status["blocker_details"]
    assert status["actuals"]["top_book_enrichment_coverage_gte_95pct"] == 0.5
    assert status["required"]["top_book_enrichment_coverage_gte_95pct"] == ">=0.95"
    assert status["actuals"]["top_book_missing_rows_eq_0"] == 1
    assert status["required"]["top_book_missing_rows_eq_0"] == 0
    assert status["sample_blockers"] == status["blocker_details"][:25]
    assert status["sample_missing_rows"][0]["reject_reason"] == "orderbook_key_missing"
    assert status["paper_fill_allowed"] is False
    assert status["routes_to_live"] is False


def test_paper_intent_cost_join_requires_challenger_binding() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    snapshots = [
        {
            "feature_snapshot_id": "snap-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-25T00:01:00Z",
            "available_at": "2026-06-25T00:00:30Z",
            "feature_cutoff": "2026-06-25T00:00:00Z",
        }
    ]
    intents = [
        {
            "intent_id": "old-policy-intent",
            "feature_snapshot_id": "snap-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "generated_utc": "2026-06-25T00:00:45Z",
            "target_notional_usdt": 100.0,
            "maker_probability": 0.0,
            "taker_probability": 1.0,
        }
    ]

    enriched, status = enrich_snapshots_with_paper_intents_from_rows(snapshots, intents, policy=policy)

    assert enriched[0].get("order_size_usd") is None
    assert status["trusted_snapshot_matches"] == 0
    assert status["reject_reason_counts"]["candidate_id_missing_or_mismatch"] == 1
    assert status["reject_reason_counts"]["policy_fingerprint_missing_or_mismatch"] == 1
    assert status["reject_reason_counts"]["model_source_missing_or_mismatch"] == 1
    assert status["counts_as_a_grade_evidence"] is False


def test_paper_intent_cost_join_copies_only_trusted_pit_safe_cost_fields() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    snapshots = [
        {
            "feature_snapshot_id": "snap-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "decision_time": "2026-06-25T00:01:00Z",
            "available_at": "2026-06-25T00:00:30Z",
            "feature_cutoff": "2026-06-25T00:00:00Z",
        }
    ]
    intents = [
        {
            "intent_id": "challenger-intent",
            "candidate_id": "challenger_v2_test",
            "policy_fingerprint": "fingerprint",
            "model_source": "test_model",
            "feature_snapshot_id": "snap-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "generated_utc": "2026-06-25T00:00:45Z",
            "target_notional_usdt": 100.0,
            "actual_observed_spread_entry_bps": 2.0,
            "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
            "market_cost_evidence_source_fields": {
                "actual_observed_spread_entry_bps": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT"
            },
            "bid_depth_usd": 10_000.0,
            "ask_depth_usd": 10_000.0,
            "entry_orderbook_depth_usd": 10_000.0,
            "depth_price_impact_bps": 0.2,
            "maker_probability": 0.0,
            "taker_probability": 1.0,
            "latency_ms": 250.0,
            "partial_fill_count": 1,
            "partial_fill_plan": {"model": "PAPER_SINGLE_IMMEDIATE_FILL"},
        }
    ]

    enriched, status = enrich_snapshots_with_paper_intents_from_rows(snapshots, intents, policy=policy)

    assert enriched[0]["order_size_usd"] == 100.0
    assert enriched[0]["actual_observed_spread_entry_bps"] == 2.0
    assert enriched[0]["entry_spread_source"] == "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT"
    assert enriched[0]["bid_depth_usd"] == 10_000.0
    assert enriched[0]["ask_depth_usd"] == 10_000.0
    assert enriched[0]["depth_price_impact_bps"] == 0.2
    assert enriched[0]["maker_probability"] == 0.0
    assert enriched[0]["taker_probability"] == 1.0
    assert enriched[0]["latency_ms"] == 250.0
    assert enriched[0]["partial_fill_count"] == 1
    assert enriched[0]["paper_intent_cost_evidence_binding_status"] == "CHALLENGER_CANDIDATE_POLICY_MODEL_MATCH"
    assert source_presence_for_required_field(enriched[0], "top_book_evidence") == (
        True,
        "row.top_book_spread_lineage",
    )
    assert source_presence_for_required_field(enriched[0], "depth_evidence") == (
        True,
        "row.ask_depth_usd",
    )
    assert status["trusted_snapshot_matches"] == 1
    assert status["positive_order_size_matches"] == 1
    assert status["field_enrichment_counts"]["order_size_usd"] == 1
    assert status["field_enrichment_counts"]["actual_observed_spread_entry_bps"] == 1
    assert status["field_enrichment_counts"]["ask_depth_usd"] == 1


def _production_grade_paper_cost_row() -> dict:
    return {
        "_paper_binding_source_key": "v2:paper:intents",
        "feature_snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "generated_utc": "2026-06-25T00:00:45Z",
        "target_notional_usdt": 100.0,
        "best_bid": 99.9,
        "best_ask": 100.1,
        "ask_depth_usd": 10_000.0,
        "bid_depth_usd": 10_000.0,
        "depth_price_impact_bps": 0.2,
        "maker_probability": 0.0,
        "taker_probability": 1.0,
        "latency_ms": 250.0,
        "partial_fill_count": 1,
        "funding_bps": 0.0,
        "mark_price": 100.0,
        "index_price": 100.0,
        "feature_freshness_state": "CURRENT",
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "live_order": False,
    }


def _shadow_cost_scored_row() -> dict:
    return {
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
        "feature_vector_hash": "feature-hash",
        "predicted_direction": "LONG",
        "predicted_move_bps": 12.0,
        "score": 12.0,
        "selected": False,
        "rejected": True,
        "rejection_reasons": ["candidate_ranked_non_executable"],
        "estimated_production_cost": {"production_grade_evidence": True, "fallback": False},
    }


def test_cost_identity_join_recovery_audit_treats_external_identity_overlap_as_diagnostic_only() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    candidate_bound = _shadow_cost_scored_row()
    paper_row = _production_grade_paper_cost_row()
    paper_row.pop("candidate_id", None)
    paper_row.pop("policy_fingerprint", None)
    paper_row.pop("model_source", None)

    payload = cost_identity_join_recovery_audit(
        policy=policy,
        paper_rows=[paper_row],
        candidate_bound_rows=[candidate_bound],
        source_counts={"v2:paper:intents": 1},
    )

    assert payload["status"] == "BLOCKED_COST_IDENTITY_JOIN_OVERLAP_DIAGNOSTIC_ONLY"
    assert payload["exact_join_key_overlap_count"] == 1
    assert payload["overlapping_paper_rows"] == 1
    assert payload["overlapping_paper_rows_with_production_grade_cost"] == 1
    assert payload["overlapping_paper_rows_with_complete_challenger_identity"] == 0
    assert payload["recoverable_candidate_bound_production_grade_rows"] == 0
    assert payload["diagnostic_only_external_identity_overlap_rows"] == 1
    assert payload["can_recover_from_existing_authoritative_sources_without_new_capture"] is False
    assert payload["pass_conditions"]["exact_join_key_overlap_gt_0"] is True
    assert payload["pass_conditions"]["overlap_with_complete_paper_identity_gt_0"] is False
    assert "overlap_with_complete_paper_identity_gt_0" in payload["blocked_reasons"]
    assert payload["blocker_details"]["overlap_with_complete_paper_identity_gt_0"]["observed"] == 0
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["exact_join_key_overlap_gt_0"] == 1
    assert payload["actuals"]["overlap_with_complete_paper_identity_gt_0"] == 0
    assert payload["required"]["overlap_with_complete_paper_identity_gt_0"] == ">0"
    assert payload["actuals"]["recoverable_candidate_bound_production_grade_rows_gt_0"] == 0
    assert payload["required"]["overlap_paper_fill_allowed_rows_eq_0"] == 0
    assert payload["sample_blockers"] == list(payload["blocker_details"].values())[:25]
    assert payload["sample_overlap_rows"][0]["paper_identity_state"] == "none"
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False


def test_cost_identity_join_recovery_audit_recovers_only_when_paper_row_has_own_challenger_identity() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    candidate_bound = _shadow_cost_scored_row()
    paper_row = {
        **_production_grade_paper_cost_row(),
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
    }

    payload = cost_identity_join_recovery_audit(
        policy=policy,
        paper_rows=[paper_row],
        candidate_bound_rows=[candidate_bound],
        source_counts={"v2:paper:intents": 1},
    )

    assert payload["status"] == "PASS_COST_IDENTITY_JOIN_RECOVERY_READY"
    assert payload["overlapping_paper_rows_with_complete_challenger_identity"] == 1
    assert payload["overlapping_paper_rows_with_production_grade_cost"] == 1
    assert payload["recoverable_candidate_bound_production_grade_rows"] == 1
    assert payload["diagnostic_only_external_identity_overlap_rows"] == 0
    assert payload["can_recover_from_existing_authoritative_sources_without_new_capture"] is True
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == {}
    assert payload["failed_blocker_details"] == {}
    assert payload["actuals"]["recoverable_candidate_bound_production_grade_rows_gt_0"] == 1
    assert payload["required"]["recoverable_candidate_bound_production_grade_rows_gt_0"] == ">0"
    assert payload["sample_blockers"] == []
    assert all(payload["pass_conditions"].values())


def test_shadow_cost_evidence_append_is_candidate_bound_append_only_and_non_promotional(tmp_path) -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    snapshot = {
        **_production_grade_paper_cost_row(),
        "feature_snapshot_id": "snap-1",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
    }
    scored = _shadow_cost_scored_row()

    record = shadow_cost_evidence_record(snapshot, scored)

    assert record["candidate_id"] == "challenger_v2_test"
    assert record["production_grade_cost_evidence"] is True
    assert record["fallback"] is False
    assert record["required_cost_source_presence"]["order_size"]["present"] is True
    assert record["required_cost_source_presence"]["maker_taker_assumption_and_probability"]["present"] is True
    assert record["paper_fill_allowed"] is False
    assert record["routes_to_live"] is False
    assert record["counts_as_phase_1_production_grade_evidence"] is False
    assert record["counts_as_training_lockbox_or_promotion_evidence"] is False
    assert record["counts_as_a_grade_evidence"] is False

    first_append = append_shadow_cost_evidence(tmp_path, [snapshot], [scored])
    second_append = append_shadow_cost_evidence(tmp_path, [snapshot], [scored])
    hash_chain = write_shadow_cost_hash_chain(tmp_path, append_status=second_append, policy=policy)
    rows = [
        json.loads(line)
        for line in (tmp_path / "challenger_v2_candidate_bound_shadow_cost_evidence.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    status = shadow_cost_evidence_status(policy=policy, append_status=second_append, hash_chain=hash_chain, rows=rows)

    assert first_append["new_shadow_cost_evidence_rows_appended"] == 1
    assert second_append["new_shadow_cost_evidence_rows_appended"] == 0
    assert second_append["immutability_conflict_count"] == 0
    assert len(rows) == 1
    assert hash_chain["status"] == "PASS_SHADOW_COST_EVIDENCE_HASH_CHAIN_AUDIT"
    assert hash_chain["shadow_cost_evidence"]["row_count"] == 1
    assert hash_chain["shadow_cost_evidence_rows"] == 1
    assert hash_chain["shadow_cost_evidence_path"] == hash_chain["shadow_cost_evidence"]["path"]
    assert hash_chain["shadow_cost_evidence_file_sha256"] == hash_chain["shadow_cost_evidence"]["file_sha256"]
    assert hash_chain["shadow_cost_evidence_last_chain_hash"] == hash_chain["shadow_cost_evidence"]["last_chain_hash"]
    assert hash_chain["shadow_cost_evidence"]["last_chain_hash"]
    assert all(hash_chain["pass_conditions"].values())
    assert hash_chain["blocker_details"] == []
    assert hash_chain["paper_fill_allowed"] is False
    assert hash_chain["routes_to_live"] is False
    assert hash_chain["places_real_order"] is False
    assert hash_chain["pass_conditions"]["places_real_order_false"] is True
    assert hash_chain["counts_as_a_grade_evidence"] is False
    assert hash_chain["promotion_evidence"] is False
    assert status["status"] == "COLLECTING_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE"
    assert status["pass_conditions"]["hash_chain_contract_passed"] is True
    assert status["shadow_cost_evidence_hash_chain_status"] == "PASS_SHADOW_COST_EVIDENCE_HASH_CHAIN_AUDIT"
    assert status["shadow_cost_evidence_hash_chain_row_count"] == 1
    assert status["shadow_cost_evidence_last_chain_hash"] == hash_chain["shadow_cost_evidence"]["last_chain_hash"]
    assert status["production_grade_shadow_cost_rows"] == 1
    assert status["shadow_cost_rows_count_as_phase_1_production_grade_evidence"] is False
    assert status["promotion_evidence"] is False
    assert status["paper_fill_allowed"] is False
    assert status["routes_to_live"] is False
    assert status["places_real_order"] is False
    assert all(status["pass_conditions"].values())


def test_shadow_cost_evidence_status_blocks_point_in_time_violation() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    snapshot = {
        **_production_grade_paper_cost_row(),
        "feature_snapshot_id": "snap-1",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:02:00Z",
    }
    scored = {
        **_shadow_cost_scored_row(),
        "available_at": "2026-06-25T00:02:00Z",
    }
    record = shadow_cost_evidence_record(snapshot, scored)

    status = shadow_cost_evidence_status(
        policy=policy,
        append_status={"immutability_conflict_count": 0},
        hash_chain={"shadow_cost_evidence": {"row_count": 1, "last_chain_hash": "hash"}},
        rows=[record],
    )

    assert status["status"] == "BLOCKED_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE_INTEGRITY"
    assert status["point_in_time_violations"] == 1
    assert status["pass_conditions"]["point_in_time_violations_eq_0"] is False
    assert status["paper_fill_allowed"] is False
    assert status["routes_to_live"] is False


def test_shadow_cost_evidence_status_requires_matching_hash_chain() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    snapshot = {
        **_production_grade_paper_cost_row(),
        "feature_snapshot_id": "snap-1",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
    }
    record = shadow_cost_evidence_record(snapshot, _shadow_cost_scored_row())

    status = shadow_cost_evidence_status(
        policy=policy,
        append_status={"immutability_conflict_count": 0},
        hash_chain={"shadow_cost_evidence": {"row_count": 0, "last_chain_hash": None}},
        rows=[record],
    )

    assert status["status"] == "BLOCKED_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE_INTEGRITY"
    assert status["pass_conditions"]["hash_chain_row_count_matches"] is False
    assert status["pass_conditions"]["hash_chain_terminal_hash_present"] is False


def test_shadow_cost_reconciliation_audit_blocks_fallback_rows_and_quarantines_old_policy_costs() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    fallback_snapshot = {
        "feature_snapshot_id": "snap-fallback",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:01:00Z",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
        "feature_freshness_state": "CURRENT",
    }
    fallback_scored = {
        **_shadow_cost_scored_row(),
        "snapshot_id": "snap-fallback",
        "estimated_production_cost": {"production_grade_evidence": False, "fallback": True},
    }
    production_grade_snapshot = {
        **_production_grade_paper_cost_row(),
        "feature_snapshot_id": "snap-production",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
    }
    production_grade_scored = {
        **_shadow_cost_scored_row(),
        "snapshot_id": "snap-production",
    }
    rows = [
        shadow_cost_evidence_record(fallback_snapshot, fallback_scored),
        shadow_cost_evidence_record(production_grade_snapshot, production_grade_scored),
    ]

    payload = shadow_cost_reconciliation_audit(
        policy=policy,
        shadow_cost_status={"status": "COLLECTING_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE"},
        shadow_rows=rows,
        paper_cost_telemetry={
            "paper_telemetry_production_grade_rows": 5,
            "challenger_bound_production_grade_rows": 0,
            "old_policy_or_unbound_production_grade_rows": 5,
            "sample_production_grade_identity_gap_rows": [{"snapshot_id": "old-policy"}],
        },
        cost_capture_gap={
            "minimum_rows_required_for_95pct_coverage": 2,
            "production_grade_cost_row_shortfall_to_95pct": 2,
        },
        runtime_cost_capture_contract={
            "status": "BLOCKED_EXISTING_RUNTIME_COST_TELEMETRY_UNBOUND_OR_OLD_POLICY",
            "blocked_reasons": ["challenger_bound_production_grade_paper_rows_gte_required_rows"],
        },
    )

    assert payload["status"] == "BLOCKED_SHADOW_COST_RECONCILIATION_REQUIRES_PRODUCTION_GRADE_CANDIDATE_BOUND_COST"
    assert payload["shadow_cost_evidence_rows"] == 2
    assert payload["candidate_identity_complete_rows"] == 2
    assert payload["candidate_bound_fallback_rows"] == 1
    assert payload["production_grade_shadow_cost_rows"] == 1
    assert payload["production_grade_non_counting_shadow_cost_rows"] == 1
    assert payload["field_gap_counts"]["order_size"] == 1
    assert payload["field_gap_counts"]["depth_derived_price_impact"] == 1
    assert payload["field_gap_counts"]["maker_taker_assumption_and_probability"] == 1
    assert payload["field_recovery_boundaries"]["order_size"] == "adaptive_allocator_or_paper_intent_pre_submit"
    assert payload["blocked_shadow_cost_row_categories"]["old_policy_or_unbound_paper_rows_quarantined"] == 5
    assert payload["pass_conditions"]["fallback_shadow_cost_rows_eq_0"] is False
    assert payload["pass_conditions"]["old_policy_or_unbound_rows_not_counted"] is True
    assert payload["pass_conditions"]["shadow_rows_non_executable"] is True
    assert "fallback_shadow_cost_rows_eq_0" in payload["blocked_reasons"]
    assert payload["blocker_details"]["fallback_shadow_cost_rows_eq_0"]["observed"] == 1
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["fallback_shadow_cost_rows_eq_0"] == 1
    assert payload["required"]["fallback_shadow_cost_rows_eq_0"] == 0
    assert payload["actuals"]["field_gap_counts_empty"]["order_size"] == 1
    assert payload["required"]["runtime_cost_capture_contract_ready"] == "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY"
    assert payload["sample_blockers"] == list(payload["blocker_details"].values())[:25]
    assert payload["sample_old_or_unbound_production_grade_paper_rows"] == [{"snapshot_id": "old-policy"}]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_shadow_cost_reconciliation_audit_passes_clean_candidate_bound_shadow_stream_without_promoting_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    snapshot = {
        **_production_grade_paper_cost_row(),
        "feature_snapshot_id": "snap-1",
        "feature_cutoff": "2026-06-25T00:00:00Z",
        "available_at": "2026-06-25T00:00:30Z",
    }
    record = shadow_cost_evidence_record(snapshot, _shadow_cost_scored_row())

    payload = shadow_cost_reconciliation_audit(
        policy=policy,
        shadow_cost_status={"status": "COLLECTING_CANDIDATE_BOUND_SHADOW_COST_EVIDENCE"},
        shadow_rows=[record],
        paper_cost_telemetry={
            "paper_telemetry_production_grade_rows": 1,
            "challenger_bound_production_grade_rows": 1,
            "old_policy_or_unbound_production_grade_rows": 0,
            "sample_challenger_bound_production_grade_rows": [{"snapshot_id": "snap-1"}],
        },
        cost_capture_gap={
            "minimum_rows_required_for_95pct_coverage": 1,
            "production_grade_cost_row_shortfall_to_95pct": 0,
        },
        runtime_cost_capture_contract={
            "status": "PASS_RUNTIME_COST_CAPTURE_CONTRACT_READY",
            "blocked_reasons": [],
        },
    )

    assert payload["status"] == "PASS_SHADOW_COST_RECONCILIATION_READY"
    assert payload["production_grade_shadow_cost_rows"] == 1
    assert payload["production_grade_non_counting_shadow_cost_rows"] == 1
    assert payload["fallback_shadow_cost_rows"] == 0
    assert payload["field_gap_counts"] == {}
    assert payload["phase_1_counting_shadow_cost_rows"] == 0
    assert payload["training_lockbox_or_promotion_counting_shadow_rows"] == 0
    assert payload["sample_challenger_bound_production_grade_paper_rows"] == [{"snapshot_id": "snap-1"}]
    assert all(payload["pass_conditions"].values())
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == {}
    assert payload["failed_blocker_details"] == {}
    assert payload["shadow_rows_count_as_phase_1_production_grade_evidence"] is False
    assert payload["shadow_rows_count_as_training_lockbox_or_promotion_evidence"] is False
    assert payload["read_only_audit_no_runtime_change"] is True


def test_paper_binding_rows_extracts_durable_ledger_and_feedback_lists() -> None:
    raw = json.dumps(
        {
            "current_cycle_accepted": [{"symbol": "BTCUSDT", "feature_snapshot_id": "accepted"}],
            "blocked": [{"symbol": "ETHUSDT", "feature_snapshot_id": "blocked"}],
            "trainer_feedback_rows": [{"symbol": "SOLUSDT", "feature_snapshot_id": "feedback"}],
            "closed_trades": [{"symbol": "XRPUSDT", "feature_snapshot_id": "closed"}],
            "audit_quality_clean_rows": 4,
        }
    )

    rows = paper_binding_rows_from_redis_value(raw, source_key="v2:paper:ledger")

    assert [row["feature_snapshot_id"] for row in rows] == ["accepted", "blocked", "closed", "feedback"]
    assert [row["_paper_binding_source_key"] for row in rows] == [
        "v2:paper:ledger.current_cycle_accepted",
        "v2:paper:ledger.blocked",
        "v2:paper:ledger.closed_trades",
        "v2:paper:ledger.trainer_feedback_rows",
    ]


def test_paper_cost_telemetry_readiness_does_not_credit_unbound_old_policy_rows() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    row = _production_grade_paper_cost_row()
    row["selector_policy_fingerprint"] = "old-selector"
    row["frozen_selector_fingerprint"] = "old-selector"
    row["trainer_source"] = "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
    row["model_id"] = "old-model"

    payload = paper_cost_telemetry_readiness_from_rows(
        policy=policy,
        rows=[row],
        source_counts={"v2:paper:intents": 1},
    )

    assert payload["status"] == "BLOCKED_CHALLENGER_IDENTITY_MISSING_FOR_COST_TELEMETRY"
    assert payload["paper_telemetry_production_grade_rows"] == 1
    assert payload["candidate_identity_complete_production_grade_rows"] == 0
    assert payload["route_or_fill_blocked_production_grade_rows"] == 0
    assert payload["candidate_bound_route_or_fill_blocked_production_grade_rows"] == 0
    assert payload["candidate_bound_route_or_fill_rows"] == 0
    assert payload["candidate_bound_paper_fill_allowed_rows"] == 0
    assert payload["candidate_bound_live_route_rows"] == 0
    assert payload["challenger_bound_production_grade_rows"] == 0
    assert payload["old_policy_or_unbound_production_grade_rows"] == 1
    assert payload["candidate_identity_counts"] == {"complete": 0, "partial": 0, "none": 1}
    assert payload["production_grade_identity_missing_counts"] == {
        "candidate_id": 1,
        "model_source": 1,
        "policy_fingerprint": 1,
    }
    assert payload["production_grade_identity_field_coverage"]["candidate_id"]["coverage"] == 0.0
    assert payload["production_grade_alternate_identity_value_counts"]["selector_policy_fingerprint"] == {"old-selector": 1}
    assert payload["sample_production_grade_identity_gap_rows"][0]["missing_required_identity_fields"] == [
        "candidate_id",
        "policy_fingerprint",
        "model_source",
    ]
    assert payload["sample_production_grade_identity_gap_rows"][0]["model_id"] == "old-model"
    assert payload["blocker_counts"]["challenger_identity_not_complete"] == 1
    assert payload["blocked_reasons"] == [
        "challenger_bound_production_grade_rows_gt_0",
    ]
    assert payload["blocker_details"] == payload["blocked_reason_details"]
    assert payload["failed_blocker_details"] == payload["blocked_reason_details"]
    assert payload["blocker_details"]["challenger_bound_production_grade_rows_gt_0"]["observed"] == 0
    assert payload["blocker_details"]["challenger_bound_production_grade_rows_gt_0"]["required"] == ">0"
    assert payload["actuals"]["challenger_bound_production_grade_rows_gt_0"] == 0
    assert payload["required"]["challenger_bound_production_grade_rows_gt_0"] == ">0"
    assert payload["sample_blockers"] == list(payload["failed_blocker_details"].values())[:25]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False
    assert payload["pass_conditions"]["production_grade_paper_cost_rows_gt_0"] is True
    assert payload["pass_conditions"]["challenger_bound_production_grade_rows_gt_0"] is False
    assert payload["pass_conditions"]["old_policy_or_unbound_rows_not_counted"] is True
    assert payload["pass_conditions"]["paper_fill_allowed_rows_eq_0"] is True
    assert payload["source_counts"] == {"v2:paper:intents": 1}
    assert payload["redis_scan_source_counts"] == {"v2:paper:intents": 1}
    assert payload["source_group_readiness"]["paper_intent"]["rows"] == 1
    assert payload["source_group_readiness"]["paper_intent"]["production_grade_rows"] == 1
    assert payload["source_group_readiness"]["paper_intent"]["old_policy_or_unbound_production_grade_rows"] == 1
    assert payload["source_group_readiness"]["paper_intent"]["challenger_bound_production_grade_rows"] == 0
    assert payload["source_group_readiness"]["paper_intent"]["blocked_reasons"] == [
        "challenger_bound_production_grade_rows_gt_0",
        "old_policy_or_unbound_production_grade_rows_present",
    ]
    assert payload["source_group_readiness_summary"]["paper_intent"]["old_policy_or_unbound_production_grade_rows"] == 1
    assert payload["source_group_readiness_summary"]["paper_intent"]["blocked_reasons"] == [
        "challenger_bound_production_grade_rows_gt_0",
        "old_policy_or_unbound_production_grade_rows_present",
    ]
    assert payload["counts_as_a_grade_evidence"] is False


def test_paper_cost_telemetry_readiness_includes_trainer_feedback_outcomes_without_crediting_identity_gaps() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    row = _production_grade_paper_cost_row()
    row["_paper_binding_source_key"] = "v2:trainer:feedback:outcomes"
    row["selector_policy_fingerprint"] = "old-selector"
    row["model_id"] = "old-model"

    payload = paper_cost_telemetry_readiness_from_rows(
        policy=policy,
        rows=[row],
        source_counts={"v2:trainer:feedback:outcomes": 1},
    )

    assert paper_cost_source_group("v2:trainer:feedback:outcomes") == "trainer_feedback"
    assert paper_cost_source_group("v2:trainer:feedback:outcomes:quarantine") == "trainer_feedback"
    assert payload["source_counts"] == {"v2:trainer:feedback:outcomes": 1}
    assert payload["redis_scan_source_counts"] == {"v2:trainer:feedback:outcomes": 1}
    assert payload["source_group_readiness"]["trainer_feedback"]["rows"] == 1
    assert payload["source_group_readiness"]["trainer_feedback"]["production_grade_rows"] == 1
    assert payload["source_group_readiness"]["trainer_feedback"]["old_policy_or_unbound_production_grade_rows"] == 1
    assert payload["source_group_readiness"]["trainer_feedback"]["challenger_bound_production_grade_rows"] == 0
    assert payload["source_group_readiness_summary"]["trainer_feedback"]["production_grade_rows"] == 1
    assert payload["challenger_bound_production_grade_rows"] == 0
    assert payload["old_policy_or_unbound_production_grade_rows"] == 1
    assert payload["counts_as_a_grade_evidence"] is False


def test_local_paper_cost_event_rows_are_diagnostic_paper_online_ledger_source(tmp_path) -> None:
    path = tmp_path / "v2/runtime/paper_online/latest/paper_events.jsonl"
    path.parent.mkdir(parents=True)
    fill_row = {
        **_production_grade_paper_cost_row(),
        "paper_result": "FILLED_PAPER_ONLY",
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
    }
    blocked_row = {**_production_grade_paper_cost_row(), "paper_result": "NO_FILL_RISK_BLOCKED"}
    path.write_text(
        "\n".join(
            [
                json.dumps(blocked_row),
                "not-json FILLED_PAPER_ONLY",
                json.dumps(fill_row),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows, status = read_local_paper_cost_event_rows(tmp_path)
    payload = paper_cost_telemetry_readiness_from_rows(
        policy=SimpleNamespace(
            candidate_id="challenger_v2_test",
            policy_fingerprint="fingerprint",
            model_source="test_model",
        ),
        rows=rows,
        source_counts=status["result_counts"],
        local_source_status=status,
    )

    assert len(rows) == 1
    assert rows[0]["_paper_binding_source_key"] == "local:paper_online:paper_events.FILLED_PAPER_ONLY"
    assert rows[0]["_paper_local_event_line_number"] == 3
    assert status["line_count"] == 3
    assert status["candidate_cost_event_line_count"] == 2
    assert status["paper_cost_event_rows"] == 1
    assert status["json_decode_error_count"] == 1
    assert status["status"] == "READ_LOCAL_PAPER_COST_EVENTS_JSONL_WITH_ERRORS"
    assert paper_cost_source_group("local:paper_online:paper_events.FILLED_PAPER_ONLY") == "paper_online_ledger"
    assert payload["status"] == "READY_CHALLENGER_BOUND_PRODUCTION_GRADE_COST_TELEMETRY_PRESENT"
    assert payload["source_counts"] == {"local:paper_online:paper_events.FILLED_PAPER_ONLY": 1}
    assert payload["local_source_status"]["paper_cost_event_rows"] == 1
    assert payload["source_group_readiness"]["paper_online_ledger"]["rows"] == 1
    assert payload["source_group_readiness"]["paper_online_ledger"]["challenger_bound_production_grade_rows"] == 1
    assert payload["counts_as_a_grade_evidence"] is False


def test_top_book_orderbook_lineage_satisfies_top_book_evidence_without_raw_quotes() -> None:
    row = _production_grade_paper_cost_row()
    row.pop("best_bid")
    row.pop("best_ask")
    row["observed_bid_ask_spread_bps"] = 2.0
    row["entry_spread_source"] = "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT"
    row["market_cost_evidence_source_fields"] = {
        "actual_observed_spread_entry_bps": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT"
    }

    evidence = cost_evidence_for_row(row, source_context="paper_runtime")

    assert source_presence_for_required_field(row, "top_book_evidence") == (
        True,
        "row.top_book_spread_lineage",
    )
    assert evidence["evidence_flags"]["top_book_evidence"] is True
    assert evidence["production_grade"] is True


def test_paper_cost_telemetry_readiness_detects_challenger_bound_cost_evidence() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    row = {
        **_production_grade_paper_cost_row(),
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
    }

    payload = paper_cost_telemetry_readiness_from_rows(policy=policy, rows=[row])

    assert payload["status"] == "READY_CHALLENGER_BOUND_PRODUCTION_GRADE_COST_TELEMETRY_PRESENT"
    assert payload["paper_telemetry_production_grade_rows"] == 1
    assert payload["candidate_identity_complete_production_grade_rows"] == 1
    assert payload["route_or_fill_blocked_production_grade_rows"] == 0
    assert payload["candidate_bound_route_or_fill_blocked_production_grade_rows"] == 0
    assert payload["candidate_bound_route_or_fill_rows"] == 0
    assert payload["candidate_bound_paper_fill_allowed_rows"] == 0
    assert payload["candidate_bound_live_route_rows"] == 0
    assert payload["challenger_bound_production_grade_rows"] == 1
    assert payload["old_policy_or_unbound_production_grade_rows"] == 0
    assert payload["candidate_identity_counts"] == {"complete": 1, "partial": 0, "none": 0}
    assert payload["production_grade_identity_missing_counts"] == {}
    assert payload["production_grade_identity_field_coverage"]["candidate_id"]["coverage"] == 1.0
    assert payload["production_grade_identity_field_coverage"]["policy_fingerprint"]["coverage"] == 1.0
    assert payload["production_grade_identity_field_coverage"]["model_source"]["coverage"] == 1.0
    assert payload["sample_production_grade_identity_gap_rows"] == []
    assert payload["field_coverage"]["order_size"]["coverage"] == 1.0
    assert payload["blocked_reasons"] == []
    assert payload["blocker_details"] == {}
    assert payload["failed_blocker_details"] == {}
    assert payload["actuals"]["challenger_bound_production_grade_rows_gt_0"] == 1
    assert payload["required"]["paper_fill_allowed_rows_eq_0"] == 0
    assert payload["sample_blockers"] == []
    assert all(payload["pass_conditions"].values())
    assert payload["source_group_readiness"]["paper_intent"]["blocked_reasons"] == []
    assert payload["source_group_readiness"]["paper_intent"]["challenger_bound_production_grade_rows"] == 1
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False


def test_paper_cost_telemetry_readiness_blocks_incomplete_signal_scan_even_with_clean_row() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    row = {
        **_production_grade_paper_cost_row(),
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
    }

    payload = paper_cost_telemetry_readiness_from_rows(
        policy=policy,
        rows=[row],
        scan_limit_reached=True,
    )

    assert payload["status"] == "BLOCKED_PAPER_COST_TELEMETRY_SCAN_LIMIT_REACHED"
    assert payload["challenger_bound_production_grade_rows"] == 1
    assert payload["blocked_reasons"] == ["redis_scan_limit_not_reached"]
    assert payload["scan_completeness_status"] == "SCAN_INCOMPLETE_LIMIT_REACHED"
    assert payload["blocked_reason_details"]["redis_scan_limit_not_reached"]["observed"] == {
        "scan_limit_reached": True
    }
    assert payload["blocked_reason_details"]["redis_scan_limit_not_reached"]["required"] == {
        "scan_limit_reached": False
    }
    assert payload["pass_conditions"]["redis_scan_limit_not_reached"] is False
    assert payload["pass_conditions"]["challenger_bound_production_grade_rows_gt_0"] is True


def test_paper_cost_telemetry_readiness_blocks_identity_bound_rows_with_paper_fill_allowed() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    row = {
        **_production_grade_paper_cost_row(),
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "paper_fill_allowed": True,
    }

    payload = paper_cost_telemetry_readiness_from_rows(policy=policy, rows=[row])

    assert payload["status"] == "BLOCKED_PAPER_COST_TELEMETRY_ROUTE_OR_FILL_ALLOWED"
    assert payload["paper_telemetry_production_grade_rows"] == 1
    assert payload["candidate_identity_complete_production_grade_rows"] == 1
    assert payload["route_or_fill_blocked_production_grade_rows"] == 1
    assert payload["candidate_bound_route_or_fill_blocked_production_grade_rows"] == 1
    assert payload["candidate_bound_route_or_fill_rows"] == 1
    assert payload["candidate_bound_paper_fill_allowed_rows"] == 1
    assert payload["candidate_bound_live_route_rows"] == 0
    assert payload["challenger_bound_production_grade_rows"] == 0
    assert payload["old_policy_or_unbound_production_grade_rows"] == 0
    assert payload["paper_fill_allowed_rows"] == 1
    assert payload["blocker_counts"]["paper_fill_allowed_true"] == 1
    assert payload["blocked_reasons"] == [
        "challenger_bound_production_grade_rows_gt_0",
        "paper_fill_allowed_rows_eq_0",
        "candidate_bound_paper_fill_allowed_rows_eq_0",
    ]
    assert payload["actuals"]["paper_fill_allowed_rows_eq_0"] == 1
    assert payload["required"]["paper_fill_allowed_rows_eq_0"] == 0
    assert payload["sample_blockers"] == list(payload["failed_blocker_details"].values())[:25]
    assert payload["pass_conditions"]["old_policy_or_unbound_rows_not_counted"] is True
    assert payload["pass_conditions"]["candidate_bound_paper_fill_allowed_rows_eq_0"] is False
    assert payload["paper_fill_allowed_source_counts"] == {"v2:paper:intents": 1}
    assert payload["sample_paper_fill_allowed_rows"][0]["source_group"] == "paper_intent"
    assert payload["sample_paper_fill_allowed_rows"][0]["route_or_fill_reason"] == "paper_fill_allowed_true"
    assert payload["sample_blocked_rows"][0]["paper_fill_allowed"] is True
    assert payload["sample_blocked_rows"][0]["blockers"] == ["paper_fill_allowed_true"]
    assert payload["source_group_readiness"]["paper_intent"]["route_or_fill_blocked_production_grade_rows"] == 1
    assert payload["source_group_readiness"]["paper_intent"]["candidate_bound_route_or_fill_blocked_production_grade_rows"] == 1
    assert payload["source_group_readiness"]["paper_intent"]["candidate_bound_paper_fill_allowed_rows"] == 1
    assert payload["source_group_readiness"]["paper_intent"]["sample_paper_fill_allowed_rows"][0][
        "candidate_id"
    ] == "challenger_v2_test"
    assert payload["source_group_readiness"]["paper_intent"]["blocked_reasons"] == [
        "challenger_bound_production_grade_rows_gt_0",
        "paper_fill_allowed_rows_eq_0",
        "candidate_bound_paper_fill_allowed_rows_eq_0",
    ]


def test_paper_cost_telemetry_readiness_surfaces_unbound_route_fill_samples_by_source_group() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    fill_row = {
        **_production_grade_paper_cost_row(),
        "_paper_binding_source_key": "v2:paper:ledger.accepted",
        "paper_fill_allowed": True,
        "selector_policy_fingerprint": "old-selector",
        "model_id": "old-model",
    }
    live_route_row = {
        **_production_grade_paper_cost_row(),
        "_paper_binding_source_key": "v2:signals:paper:BTCUSDT",
        "routes_to_live": True,
        "selector_policy_fingerprint": "old-selector",
        "model_id": "old-model",
    }

    payload = paper_cost_telemetry_readiness_from_rows(policy=policy, rows=[fill_row, live_route_row])

    assert payload["status"] == "BLOCKED_CHALLENGER_IDENTITY_MISSING_FOR_COST_TELEMETRY"
    assert payload["candidate_bound_paper_fill_allowed_rows"] == 0
    assert payload["candidate_bound_live_route_rows"] == 0
    assert payload["paper_fill_allowed_source_counts"] == {"v2:paper:ledger.accepted": 1}
    assert payload["live_route_source_counts"] == {"v2:signals:paper:BTCUSDT": 1}
    assert payload["sample_paper_fill_allowed_rows"][0]["source_group"] == "paper_ledger"
    assert payload["sample_paper_fill_allowed_rows"][0]["identity_state"] == "none"
    assert payload["sample_paper_fill_allowed_rows"][0]["selector_policy_fingerprint"] == "old-selector"
    assert payload["sample_live_route_rows"][0]["source_group"] == "paper_signal"
    assert payload["sample_live_route_rows"][0]["route_or_fill_reason"] == "routes_to_live_true"
    assert payload["source_group_readiness"]["paper_ledger"]["sample_paper_fill_allowed_rows"][0][
        "model_id"
    ] == "old-model"
    assert payload["source_group_readiness"]["paper_signal"]["sample_live_route_rows"][0][
        "source_key"
    ] == "v2:signals:paper:BTCUSDT"
    assert payload["source_group_readiness"]["paper_ledger"]["candidate_bound_paper_fill_allowed_rows"] == 0
    assert payload["source_group_readiness"]["paper_signal"]["candidate_bound_live_route_rows"] == 0


def _integrity_policy() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )


def _pending_lockbox_row() -> dict:
    row = {
        "schema_version": "challenger_v2_future_lockbox_pending_v1",
        "record_created_utc": "2026-06-25T00:00:05Z",
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:00:00Z",
        "feature_cutoff": "2026-06-24T23:59:59Z",
        "available_at": "2026-06-24T23:59:59Z",
        "feature_vector_hash": "features",
        "feature_values_by_name": {"close": 100.0},
        "predicted_direction": "LONG",
        "predicted_move_bps": 5.0,
        "score": 5.0,
        "estimated_production_cost": {"fallback": True, "production_grade_evidence": False},
        "selected": False,
        "rejected": True,
        "rejection_reasons": ["cost_not_production_grade"],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "selection_fields_are_immutable_after_outcomes_exist": True,
        "lockbox_record_id": "record-1",
    }
    row["selection_payload_hash"] = "selection"
    return row


def _labelled_lockbox_row(pending: dict, *, selection_hash: str | None = None) -> dict:
    return {
        "schema_version": "challenger_v2_future_lockbox_labelled_v1",
        "label_created_utc": "2026-06-25T00:16:00Z",
        "lockbox_record_id": pending["lockbox_record_id"],
        "candidate_id": pending["candidate_id"],
        "policy_fingerprint": pending["policy_fingerprint"],
        "snapshot_id": pending["snapshot_id"],
        "symbol": pending["symbol"],
        "timeframe": pending["timeframe"],
        "decision_time": pending["decision_time"],
        "feature_cutoff": pending["feature_cutoff"],
        "available_at": pending["available_at"],
        "selection_record_hash": selection_hash or row_hash(pending),
        "predicted_direction": pending["predicted_direction"],
        "label_source": "redis_binance_ohlcv_1m",
        "label_source_timestamp": "2026-06-25T00:15:00Z",
        "label_horizon_minutes": 15,
        "label_uses_future_data_as_label_only": True,
        "future_finalized_price": 101.0,
        "gross_return_bps": 100.0,
        "fees_bps": 4.0,
        "spread_bps": 1.0,
        "slippage_bps": 2.0,
        "funding_bps": 0.1,
        "net_return_bps": 92.9,
        "mfe_bps": 110.0,
        "mae_bps": -20.0,
        "selected": pending["selected"],
        "rejected": pending["rejected"],
        "rejection_reasons": pending["rejection_reasons"],
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
        "counts_as_a_grade_evidence": False,
        "promotion_evidence": False,
        "label_record_id": "label-1",
    }


def test_append_matured_labels_counts_unlabelled_pending_once(tmp_path) -> None:
    out_dir = tmp_path / "goal_state"
    out_dir.mkdir()
    pending_rows = [
        {**_pending_lockbox_row(), "lockbox_record_id": "record-1", "decision_time": "2999-01-01T00:00:00Z"},
        {**_pending_lockbox_row(), "lockbox_record_id": "record-2", "decision_time": "2999-01-01T00:00:00Z"},
        {**_pending_lockbox_row(), "lockbox_record_id": "record-3", "decision_time": "2999-01-01T00:00:00Z"},
    ]
    labelled_rows = [
        _labelled_lockbox_row(pending_rows[0]),
        {**_labelled_lockbox_row(pending_rows[1]), "lockbox_record_id": "record-2", "label_record_id": "label-2"},
    ]
    (out_dir / "challenger_v2_future_lockbox_pending.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in pending_rows),
        encoding="utf-8",
    )
    (out_dir / "challenger_v2_future_lockbox_labelled.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in labelled_rows),
        encoding="utf-8",
    )

    payload = append_matured_labels(
        tmp_path,
        out_dir,
        horizon_minutes=15,
        archive_scan_limit=0,
        allow_public_labels=False,
        public_label_symbol_limit=0,
    )

    assert payload["pending_rows_examined"] == 3
    assert payload["unlabelled_pending_rows_examined"] == 1
    assert payload["not_matured_unlabelled_rows"] == 1
    assert payload["new_labels_appended"] == 0
    assert payload["labelled_rows_after_append"] == 2


def test_write_hash_chain_publishes_self_verifying_non_executable_contract(tmp_path) -> None:
    out_dir = tmp_path / "goal_state"
    out_dir.mkdir()
    pending = _pending_lockbox_row()
    label = _labelled_lockbox_row(pending)
    (out_dir / "challenger_v2_future_lockbox_pending.jsonl").write_text(
        json.dumps(pending, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out_dir / "challenger_v2_future_lockbox_labelled.jsonl").write_text(
        json.dumps(label, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    payload = write_hash_chain(
        out_dir,
        append_status={"pending_path": str(out_dir / "challenger_v2_future_lockbox_pending.jsonl")},
        label_status={"labelled_path": str(out_dir / "challenger_v2_future_lockbox_labelled.jsonl")},
        policy=_integrity_policy(),
    )
    written = json.loads((out_dir / "challenger_v2_future_lockbox_hash_chain.json").read_text(encoding="utf-8"))

    assert payload["status"] == "PASS_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT"
    assert written["status"] == "PASS_FUTURE_LOCKBOX_HASH_CHAIN_AUDIT"
    assert all(payload["pass_conditions"].values())
    assert payload["blocker_details"] == []
    assert payload["pending"]["row_count"] == 1
    assert payload["labelled"]["row_count"] == 1
    assert payload["pending_rows"] == 1
    assert payload["labelled_rows"] == 1
    assert payload["pending_path"] == payload["pending"]["path"]
    assert payload["labelled_path"] == payload["labelled"]["path"]
    assert payload["pending_file_sha256"] == payload["pending"]["file_sha256"]
    assert payload["labelled_file_sha256"] == payload["labelled"]["file_sha256"]
    assert payload["pending_last_chain_hash"] == payload["pending"]["last_chain_hash"]
    assert payload["labelled_last_chain_hash"] == payload["labelled"]["last_chain_hash"]
    assert payload["pass_conditions"]["top_level_row_counts_match_nested_chains"] is True
    assert payload["pass_conditions"]["places_real_order_false"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False
    assert payload["pending"]["last_chain_hash"]
    assert payload["labelled"]["last_chain_hash"]
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_future_lockbox_integrity_audit_accepts_append_only_label_pair() -> None:
    pending = _pending_lockbox_row()
    label = _labelled_lockbox_row(pending)
    hash_chain = {
        "pending": {
            "row_count": 1,
            "file_sha256": "pending-file-hash",
            "first_chain_hash": "pending-first",
            "last_chain_hash": "pending-last",
            "chain_algorithm": "sha256(canonical_json({previous_hash,row_hash}))",
        },
        "labelled": {
            "row_count": 1,
            "file_sha256": "labelled-file-hash",
            "first_chain_hash": "labelled-first",
            "last_chain_hash": "labelled-last",
            "chain_algorithm": "sha256(canonical_json({previous_hash,row_hash}))",
        },
    }

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
        hash_chain=hash_chain,
    )

    assert payload["status"] == "PASS_INTEGRITY_AUDIT"
    assert payload["hash_chain_artifact_present"] is True
    assert payload["hash_chain_pending_row_count_matches_jsonl"] is True
    assert payload["hash_chain_labelled_row_count_matches_jsonl"] is True
    assert payload["hash_chain_terminal_hashes_present"] is True
    assert payload["hash_chain_file_hashes_present"] is True
    assert payload["hash_chain_status"] == "PASS_HASH_CHAIN_AUDIT"
    assert payload["hash_chain_pending_row_count"] == 1
    assert payload["hash_chain_labelled_row_count"] == 1
    assert payload["hash_chain_integrity"]["pending"]["last_chain_hash"] == "pending-last"
    assert payload["required_pending_fields"] == payload["pending_required_fields"]
    assert payload["required_label_fields"] == payload["labelled_required_fields"]
    assert payload["required_selection_fields"] == payload["pending_required_fields"]
    assert payload["required_labelled_fields"] == payload["labelled_required_fields"]
    assert payload["pending_missing_required_field_counts"] == {}
    assert payload["labelled_missing_required_field_counts"] == {}
    assert payload["label_missing_required_field_counts"] == {}
    assert payload["missing_required_selection_field_counts"] == {}
    assert payload["missing_required_label_field_counts"] == {}
    assert payload["pending_missing_non_execution_flag_counts"] == {}
    assert payload["labelled_missing_non_execution_flag_counts"] == {}
    assert payload["pending_non_execution_flag_violation_counts"] == {}
    assert payload["labelled_non_execution_flag_violation_counts"] == {}
    assert payload["legacy_rows_missing_explicit_non_execution_flags"] == 0
    assert payload["non_execution_flag_contract"]["new_pending_records_write_explicit_false_flags"] is True
    assert payload["non_execution_flag_contract"]["new_label_records_write_explicit_false_flags"] is True
    assert payload["pass_conditions"]["pending_non_execution_flags_false_when_present"] is True
    assert payload["pass_conditions"]["labelled_non_execution_flags_false_when_present"] is True
    assert payload["pending_missing_required_field_total"] == 0
    assert payload["labelled_missing_required_field_total"] == 0
    assert payload["label_missing_required_field_total"] == 0
    assert payload["missing_required_selection_field_total"] == 0
    assert payload["missing_required_label_field_total"] == 0
    assert payload["duplicate_pending_record_count"] == 0
    assert payload["duplicate_pending_decision_key_count"] == 0
    assert payload["duplicate_label_record_count"] == 0
    assert payload["duplicate_labelled_record_count"] == 0
    assert payload["duplicate_labelled_lockbox_record_count"] == 0
    assert payload["label_selection_hash_mismatch_count"] == 0
    assert payload["selection_fields_rewritten_after_label_count"] == 0
    assert payload["selection_fields_rewritten_after_outcome_count"] == 0
    assert payload["selection_fields_rewritten_after_outcomes"] == 0
    assert payload["selection_fields_rewritten_after_outcomes_count"] == 0
    assert payload["selection_fields_rewritten_after_outcomes_exist"] is False
    assert payload["selection_fields_immutable_after_outcomes"] is True
    assert payload["selection_fields_immutable_after_outcomes_exist"] is True
    assert payload["selection_fields_marked_immutable"] is True
    assert payload["selection_fields_nonimmutable_count"] == 0
    assert payload["pending_append_immutability_conflicts"] == 0
    assert payload["selection_fields_never_rewritten_after_outcomes"] is True
    assert payload["append_only_violation_count"] == 0
    assert payload["append_only_violations"] == 0
    assert payload["append_only_status"] == "PASS_APPEND_ONLY_LOCKBOX_AUDIT"
    assert payload["point_in_time_violation_count"] == 0
    assert payload["append_only_contract"]["pending_append_immutability_conflicts"] == 0
    assert payload["append_only_contract"]["selection_fields_immutable_after_outcomes"] is True
    assert payload["append_only_contract"]["selection_fields_immutable_after_outcomes_exist"] is True
    assert payload["append_only_contract"]["selection_fields_marked_immutable"] is True
    assert payload["append_only_contract"]["append_only_violations_eq_0"] is True
    assert payload["append_only_contract"]["selection_record_hashes_match_pending_records"] is True
    assert payload["pending_label_outcome_field_count"] == 0
    assert payload["label_fields_absent_from_pending"] is True
    assert payload["selection_fields_absent_from_labels"] is True
    assert payload["labels_append_outcomes_only_status"] == "PASS_LABELS_APPEND_OUTCOMES_ONLY"
    assert payload["pass_conditions"]["pending_records_do_not_contain_label_outcomes"] is True
    assert payload["pass_conditions"]["selection_fields_marked_immutable"] is True
    assert payload["pass_conditions"]["pending_append_immutability_conflicts_eq_0"] is True
    assert payload["pass_conditions"]["selection_fields_rewritten_after_label_eq_0"] is True
    assert payload["pass_conditions"]["append_only_violations_eq_0"] is True
    assert payload["pass_conditions"]["selection_record_hashes_match_pending_records"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_future_lockbox_integrity_audit_flags_row_level_execution_flags() -> None:
    pending = _pending_lockbox_row()
    pending.pop("places_real_order")
    label = _labelled_lockbox_row(_pending_lockbox_row())
    label["routes_to_live"] = True

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["pending_missing_non_execution_flag_counts"] == {"places_real_order": 1}
    assert payload["pending_missing_non_execution_flag_total"] == 1
    assert payload["labelled_non_execution_flag_violation_counts"] == {"routes_to_live": 1}
    assert payload["labelled_non_execution_flag_violation_total"] == 1
    assert payload["legacy_rows_missing_explicit_non_execution_flags"] == 1
    assert payload["non_execution_flag_contract"]["legacy_rows_missing_explicit_flags_are_not_rewritten"] is True
    assert payload["non_execution_flag_contract"]["missing_legacy_flags_do_not_count_as_executable"] is True
    assert payload["non_execution_flag_contract"]["true_execution_or_credit_flags_fail_integrity"] is False
    assert payload["pass_conditions"]["pending_non_execution_flags_false_when_present"] is True
    assert payload["pass_conditions"]["labelled_non_execution_flags_false_when_present"] is False


def test_future_lockbox_integrity_audit_reports_required_field_alias_counts() -> None:
    pending = _pending_lockbox_row()
    pending["snapshot_id"] = None
    label = _labelled_lockbox_row(_pending_lockbox_row())
    label["gross_return_bps"] = None

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["pending_missing_required_field_counts"] == {"snapshot_id": 1}
    assert payload["missing_required_selection_field_counts"] == {"snapshot_id": 1}
    assert payload["pending_missing_required_field_total"] == 1
    assert payload["missing_required_selection_field_total"] == 1
    assert payload["labelled_missing_required_field_counts"] == {"gross_return_bps": 1}
    assert payload["label_missing_required_field_counts"] == {"gross_return_bps": 1}
    assert payload["missing_required_label_field_counts"] == {"gross_return_bps": 1}
    assert payload["labelled_missing_required_field_total"] == 1
    assert payload["label_missing_required_field_total"] == 1
    assert payload["missing_required_label_field_total"] == 1
    assert payload["pass_conditions"]["pending_required_fields_present"] is False
    assert payload["pass_conditions"]["label_required_fields_present"] is False


def test_future_lockbox_integrity_audit_reports_duplicate_pending_decision_keys() -> None:
    pending = _pending_lockbox_row()
    duplicate = dict(pending)
    duplicate["selection_payload_hash"] = pending["selection_payload_hash"]

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending, duplicate],
        labelled_rows=[],
        point_in_time_violations=0,
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["duplicate_pending_record_count"] == 1
    assert payload["duplicate_pending_decision_key_count"] == 1
    assert payload["pass_conditions"]["pending_lockbox_ids_unique"] is False
    assert payload["pass_conditions"]["pending_decision_keys_unique"] is False
    assert payload["append_only_violation_count"] == 2


def test_future_lockbox_integrity_audit_detects_hash_chain_row_count_mismatch() -> None:
    pending = _pending_lockbox_row()
    label = _labelled_lockbox_row(pending)

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
        hash_chain={
            "pending": {"row_count": 2, "file_sha256": "pending-file-hash", "last_chain_hash": "pending-last"},
            "labelled": {"row_count": 1, "file_sha256": "labelled-file-hash", "last_chain_hash": "labelled-last"},
        },
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["hash_chain_artifact_present"] is True
    assert payload["hash_chain_pending_row_count_matches_jsonl"] is False
    assert payload["hash_chain_labelled_row_count_matches_jsonl"] is True
    assert payload["pass_conditions"]["hash_chain_pending_row_count_matches_jsonl"] is False


def test_future_lockbox_integrity_audit_detects_selection_hash_mismatch() -> None:
    pending = _pending_lockbox_row()
    label = _labelled_lockbox_row(pending, selection_hash="stale-selection-hash")

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["label_selection_hash_mismatch_count"] == 1
    assert payload["selection_fields_rewritten_after_label_count"] == 1
    assert payload["selection_fields_rewritten_after_outcomes"] == 1
    assert payload["selection_fields_rewritten_after_outcomes_count"] == 1
    assert payload["selection_fields_rewritten_after_outcomes_exist"] is True
    assert payload["selection_fields_immutable_after_outcomes"] is False
    assert payload["selection_fields_immutable_after_outcomes_exist"] is False
    assert payload["selection_fields_never_rewritten_after_outcomes"] is False
    assert payload["append_only_contract"]["selection_fields_immutable_after_outcomes"] is False
    assert payload["append_only_contract"]["selection_fields_immutable_after_outcomes_exist"] is False
    assert payload["append_only_contract"]["selection_record_hashes_match_pending_records"] is False
    assert payload["pass_conditions"]["selection_record_hashes_match_pending_records"] is False
    assert payload["pass_conditions"]["selection_fields_rewritten_after_label_eq_0"] is False


def test_future_lockbox_integrity_audit_detects_append_immutability_conflict() -> None:
    pending = _pending_lockbox_row()
    label = _labelled_lockbox_row(pending)

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
        append_status={"immutability_conflict_count": 1},
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["pending_append_immutability_conflict_count"] == 1
    assert payload["pending_append_immutability_conflicts"] == 1
    assert payload["selection_fields_rewritten_after_label_count"] == 1
    assert payload["selection_fields_rewritten_after_outcomes"] == 1
    assert payload["selection_fields_rewritten_after_outcomes_exist"] is True
    assert payload["selection_fields_immutable_after_outcomes"] is False
    assert payload["selection_fields_never_rewritten_after_outcomes"] is False
    assert payload["append_only_violation_count"] == 1
    assert payload["append_only_contract"]["pending_selection_records_are_append_only"] is False
    assert payload["append_only_contract"]["pending_append_immutability_conflicts"] == 1
    assert payload["append_only_contract"]["selection_fields_immutable_after_outcomes"] is False
    assert payload["append_only_contract"]["append_only_violations_eq_0"] is False
    assert payload["pass_conditions"]["pending_append_immutability_conflicts_eq_0"] is False
    assert payload["pass_conditions"]["append_only_violations_eq_0"] is False
    assert payload["sample_violations"][0]["violation"] == "pending_append_immutability_conflict"


def test_future_lockbox_integrity_audit_detects_selection_label_field_leakage() -> None:
    pending = {
        **_pending_lockbox_row(),
        "net_return_bps": 10.0,
    }
    label = {
        **_labelled_lockbox_row(_pending_lockbox_row()),
        "feature_vector_hash": "selection-field-leak",
    }

    payload = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
    )

    assert payload["status"] == "FAIL_LOCKBOX_INTEGRITY_AUDIT"
    assert payload["pending_label_outcome_field_count"] == 1
    assert payload["label_forbidden_selection_field_count"] == 1
    assert payload["label_selection_only_field_count"] == 1
    assert payload["append_only_violation_count"] == 2
    assert payload["label_fields_absent_from_pending"] is False
    assert payload["selection_fields_absent_from_labels"] is False
    assert payload["labels_append_outcomes_only_status"] == "FAIL_LABEL_SELECTION_OUTCOME_SEPARATION"
    assert payload["pass_conditions"]["pending_records_do_not_contain_label_outcomes"] is False
    assert payload["pass_conditions"]["labels_append_outcomes_only"] is False


def test_blind_lockbox_pass_contract_blocks_zero_independent_candidates() -> None:
    pending = _pending_lockbox_row()
    label = _labelled_lockbox_row(pending)
    integrity = future_lockbox_integrity_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        point_in_time_violations=0,
    )

    payload = blind_lockbox_pass_contract_audit(
        policy=_integrity_policy(),
        pending_rows=[pending],
        labelled_rows=[label],
        cost_status={"production_grade_cost_coverage": 0.0},
        lockbox_integrity=integrity,
    )

    assert payload["status"] == "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT"
    assert payload["independent_economic_candidates"] == 0
    assert payload["required_independent_economic_candidates"] == 300
    assert payload["independent_economic_candidate_shortfall_to_300"] == 300
    assert payload["independent_candidate_shortfall_to_300"] == 300
    assert payload["independent_economic_candidate_shortfall_to_required"] == 300
    assert payload["independent_candidate_shortfall_to_required"] == 300
    assert payload["required_symbols"] == 30
    assert payload["symbol_shortfall_to_30"] == 30
    assert payload["long_candidate_shortfall_to_1"] == 1
    assert payload["short_candidate_shortfall_to_1"] == 1
    assert payload["symbol_count"] == payload["symbols"] == 0
    assert payload["long_candidates"] == payload["long_count"] == 0
    assert payload["short_candidates"] == payload["short_count"] == 0
    assert payload["selected_label_count"] == 0
    assert payload["selected_pending_rows"] == 0
    assert payload["selected_pending_count"] == 0
    assert payload["rejected_pending_rows"] == 1
    assert payload["rejected_pending_count"] == 1
    assert payload["selection_summary"] == {
        "pending_rows": 1,
        "labelled_rows": 1,
        "selected_pending_rows": 0,
        "rejected_pending_rows": 1,
        "selected_label_rows": 0,
        "independent_economic_candidates": 0,
        "excluded_selected_candidate_total": 0,
    }
    assert payload["next_countability_gate"] == "raw_pending_rows"
    assert payload["lockbox_countability_funnel"] == payload["countability_funnel"]
    assert payload["lockbox_countability_funnel"]["required_independent_economic_candidates"] == 300
    assert payload["lockbox_countability_funnel"]["next_countability_gate"] == "raw_pending_rows"
    assert payload["lockbox_countability_funnel"]["raw_pending_rows"] == 1
    assert payload["lockbox_countability_funnel"]["rejected_pending_rows"] == 1
    assert payload["lockbox_countability_funnel"]["selected_pending_rows"] == 0
    assert payload["lockbox_countability_funnel"]["raw_labelled_rows"] == 1
    assert payload["lockbox_countability_funnel"]["selected_label_rows"] == 0
    assert payload["lockbox_countability_funnel"]["selected_label_rows_with_pending_record"] == 0
    assert payload["lockbox_countability_funnel"]["candidate_identity_bound_selected_label_rows"] == 0
    assert payload["lockbox_countability_funnel"]["production_grade_cost_at_decision_selected_label_rows"] == 0
    assert payload["lockbox_countability_funnel"]["fallback_free_cost_at_decision_selected_label_rows"] == 0
    assert payload["lockbox_countability_funnel"]["unique_independent_economic_candidates"] == 0
    assert payload["lockbox_countability_funnel"]["shortfall_to_required"] == 300
    assert payload["lockbox_countability_funnel"]["pending_rows_rejected_before_selection"] == 1
    assert payload["lockbox_countability_funnel"]["primary_pending_rejection_reasons"] == [
        {"reason": "cost_not_production_grade", "count": 1, "pct_of_pending_rows": 1.0}
    ]
    assert payload["lockbox_countability_funnel_steps"][0] == {
        "gate": "raw_pending_rows",
        "description": "Immutable future decision records appended after the freeze.",
        "observed": 1,
        "required": ">=300",
        "passed": False,
        "dropped_from_previous_gate": 0,
        "shortfall_to_required": 299,
    }
    assert payload["lockbox_countability_funnel_steps"][1]["gate"] == "selected_pending_rows"
    assert payload["lockbox_countability_funnel_steps"][1]["observed"] == 0
    assert payload["lockbox_countability_funnel_steps"][1]["dropped_from_previous_gate"] == 1
    assert payload["lockbox_countability_funnel_steps"][-1]["gate"] == "unique_independent_economic_candidates"
    assert payload["lockbox_countability_funnel_steps"][-1]["shortfall_to_required"] == 300
    assert payload["zero_independent_candidate_root_cause"] == payload[
        "phase_5_zero_independent_candidate_root_cause"
    ]
    assert payload["zero_independent_candidate_root_cause"]["status"] == "ZERO_INDEPENDENT_ECONOMIC_CANDIDATES"
    assert payload["zero_independent_candidate_root_cause"]["next_countability_gate"] == "raw_pending_rows"
    assert payload["zero_independent_candidate_root_cause"]["dominant_pending_rejection_reason"] == {
        "reason": "cost_not_production_grade",
        "count": 1,
        "pct_of_pending_rows": 1.0,
    }
    assert payload["rejection_reason_counts"] == {"cost_not_production_grade": 1}
    assert payload["pending_rejection_reason_counts"] == {"cost_not_production_grade": 1}
    assert payload["minimum_lockbox_evidence"] == {
        "independent_economic_candidates": ">=300",
        "symbols": ">=30",
        "long_candidates": ">0",
        "short_candidates": ">0",
        "after_cost_expectancy_bps": ">0",
        "expectancy_95pct_lower_bound_bps": ">0",
        "profit_factor": ">=1.5",
        "false_positive_rate": "<=0.4",
        "max_concentration_pct": "<=0.3",
        "worst_1pct_loss_bps": ">=-500.0",
        "point_in_time_violations": 0,
        "production_grade_cost_coverage": ">=0.95",
    }
    assert payload["minimum_lockbox_observed"]["independent_economic_candidates"] == 0
    assert payload["minimum_lockbox_observed"]["production_grade_cost_coverage"] == 0.0
    assert payload["actuals"] == payload["minimum_lockbox_observed"]
    assert payload["required"] == payload["minimum_lockbox_evidence"]
    assert payload["lockbox_candidate_count"] == 0
    assert payload["independent_economic_candidate_count"] == 0
    assert payload["minimum_lockbox_shortfalls"]["independent_economic_candidates"] == 300
    assert payload["minimum_lockbox_shortfalls"]["symbols"] == 30
    assert payload["minimum_lockbox_shortfalls"]["long_candidates"] == 1
    assert payload["minimum_lockbox_shortfalls"]["short_candidates"] == 1
    assert payload["minimum_lockbox_shortfalls"]["production_grade_cost_coverage"] == 0.95
    assert payload["minimum_lockbox_pass_conditions"] == payload["pass_conditions"]
    assert payload["sample_failures"] == list(payload["failed_blocker_details"].values())[:25]
    assert payload["sample_blockers"] == payload["sample_failures"]
    assert payload["sample_blocked_candidates"] == payload["sample_excluded_selected_candidates"]
    assert payload["expectancy_after_cost"] is None
    assert payload["expectancy_95_lower_bound"] is None
    assert payload["max_concentration_dimension_share"] is None
    assert payload["worst_1pct_loss_inside_risk_envelope"] is False
    assert payload["point_in_time_violation_count"] == 0
    assert payload["candidate_count_by_direction"] == {"LONG": 0, "SHORT": 0}
    assert payload["selected_label_count_by_direction"] == {"LONG": 0, "SHORT": 0}
    assert payload["lockbox_integrity_status"] == "PASS_INTEGRITY_AUDIT"
    assert payload["labels_have_pending_selection_record"] is True
    assert payload["selection_record_hashes_match_pending_records"] is True
    assert payload["selection_fields_marked_immutable"] is True
    assert payload["selected_fallback_rows_eq_0"] is True
    assert payload["selected_fallback_rows"] == 0
    assert payload["label_selection_hash_mismatch_count"] == 0
    assert payload["selection_fields_rewritten_after_label_count"] == 0
    assert payload["selection_fields_rewritten_after_outcomes_count"] == 0
    assert payload["selection_fields_rewritten_after_outcomes_exist"] is False
    assert payload["excluded_counts"] == {}
    assert payload["excluded_selected_candidate_total"] == 0
    assert payload["available_metric_count"] == 0
    assert payload["unavailable_metric_count"] == 6
    assert payload["metric_availability"]["after_cost_expectancy_bps"] == {
        "available": False,
        "observed": None,
        "unavailable_reasons": ["no_independent_economic_candidates", "no_selected_label_rows"],
    }
    assert payload["metric_availability"]["expectancy_95pct_lower_bound_bps"] == {
        "available": False,
        "observed": None,
        "unavailable_reasons": [
            "no_independent_economic_candidates",
            "no_selected_label_rows",
            "requires_at_least_2_independent_candidates",
        ],
    }
    assert payload["unavailable_metric_reasons"]["worst_1pct_loss_bps"] == [
        "no_independent_economic_candidates",
        "no_selected_label_rows",
        "requires_independent_candidate_distribution",
    ]
    assert "no_selected_label_rows" in payload["non_counting_reasons"]
    assert "independent_economic_candidates_below_300" in payload["non_counting_reasons"]
    assert "production_grade_cost_coverage_below_95pct" in payload["non_counting_reasons"]
    assert "independent_economic_candidates_gte_300" in payload["blocked_reasons"]
    assert "production_grade_cost_coverage_gte_95pct" in payload["blocked_reasons"]
    assert payload["lockbox_pass_blocker_details"]["independent_economic_candidates_gte_300"] == {
        "passed": False,
        "observed": 0,
        "required": ">=300",
        "shortfall": 300,
    }
    assert payload["blocker_details"] == payload["lockbox_pass_blocker_details"]
    assert payload["failed_blocker_details"]["independent_economic_candidates_gte_300"] == payload["lockbox_pass_blocker_details"][
        "independent_economic_candidates_gte_300"
    ]
    assert payload["failed_lockbox_blocker_details"] == payload["failed_blocker_details"]
    assert payload["phase_5_failed_blocker_details"] == payload["failed_blocker_details"]
    assert payload["production_grade_cost_coverage_shortfall_to_95pct"] == 0.95
    assert payload["independent_candidate_counting_contract"] == payload["lockbox_counting_contract"]
    assert payload["independent_candidate_counting_contract"]["raw_pending_rows"] == 1
    assert payload["independent_candidate_counting_contract"]["raw_labelled_rows"] == 1
    assert payload["independent_candidate_counting_contract"]["selected_pending_rows"] == 0
    assert payload["independent_candidate_counting_contract"]["selected_label_rows"] == 0
    assert payload["independent_candidate_counting_contract"]["independent_economic_candidates"] == 0
    assert payload["independent_candidate_counting_contract"][
        "pending_rows_not_countable_as_independent_economic_candidates"
    ] == 1
    assert payload["independent_candidate_counting_contract"][
        "labelled_rows_not_countable_as_independent_economic_candidates"
    ] == 1
    assert payload["independent_candidate_counting_contract"]["pending_rejection_reason_counts"] == {
        "cost_not_production_grade": 1
    }
    assert payload["independent_candidate_counting_contract"]["primary_pending_rejection_reasons"] == [
        {"reason": "cost_not_production_grade", "count": 1, "pct_of_pending_rows": 1.0}
    ]
    assert payload["independent_candidate_counting_contract"]["countability_funnel"] == payload[
        "lockbox_countability_funnel"
    ]
    assert payload["independent_candidate_counting_contract"]["next_countability_gate"] == "raw_pending_rows"
    assert payload["independent_candidate_counting_contract"]["production_grade_cost_gate_passed"] is False
    assert payload["independent_candidate_counting_contract"]["raw_row_volume_counts_as_lockbox_pass_evidence"] is False
    assert payload["independent_candidate_counting_contract"]["selected_and_labelled_rows_required_for_metrics"] is True
    assert payload["independent_candidate_counting_contract"]["candidate_bound_identity_required"] is True
    assert payload["independent_candidate_counting_contract"]["production_grade_cost_required_at_decision_time"] is True
    assert (
        payload["independent_candidate_counting_contract"]["fallback_true_rows_count_as_lockbox_or_promotion_evidence"]
        is False
    )
    assert payload["pending_rows_not_countable_as_independent_economic_candidates"] == 1
    assert payload["labelled_rows_not_countable_as_independent_economic_candidates"] == 1
    assert payload["raw_row_volume_counts_as_lockbox_pass_evidence"] is False
    assert payload["selected_and_labelled_rows_required_for_metrics"] is True
    assert payload["pass_conditions"]["independent_economic_candidates_gte_300"] is False
    assert payload["pass_conditions"]["production_grade_cost_coverage_gte_95pct"] is False
    assert payload["lockbox_counting_evidence_allowed"] is False
    assert payload["counting_evidence_allowed"] is False
    assert payload["lockbox_prerequisite_for_paper_canary_binding_satisfied"] is False
    assert payload["do_not_tune_frozen_candidate_after_viewing_lockbox_results"] is True
    assert payload["new_candidate_required_if_tuning_needed"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False


def test_lockbox_performance_publishes_blocker_contract_for_blocked_gate() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )

    payload = lockbox_performance(
        [{"selected": False, "symbol": "BTCUSDT", "predicted_direction": "LONG"}],
        policy=policy,
        cost_status={"production_grade_cost_coverage": 0.0},
        point_in_time_violations=0,
    )

    assert payload["status"] == "BLOCKED_LOCKBOX_PASS_CONDITIONS_NOT_MET"
    assert payload["candidate_id"] == "challenger_v2_test"
    assert payload["policy_fingerprint"] == "fingerprint"
    assert payload["model_source"] == "test_model"
    assert payload["selected_economic_candidates"] == 0
    assert payload["independent_economic_candidates"] == 0
    assert payload["required_independent_economic_candidates"] == 300
    assert payload["independent_economic_candidate_shortfall_to_300"] == 300
    assert payload["minimum_pass"]["selected_candidates_gte_300"] is False
    assert payload["pass_conditions"]["independent_economic_candidates_gte_300"] is False
    assert payload["pass_conditions"]["production_grade_cost_coverage_gte_95pct"] is False
    assert payload["blocked_reasons"] == [
        "independent_economic_candidates_gte_300",
        "symbols_gte_30",
        "long_gt_0",
        "short_gt_0",
        "after_cost_expectancy_gt_0",
        "expectancy_95pct_lower_bound_gt_0",
        "profit_factor_gte_1_5",
        "false_positive_rate_lte_0_40",
        "no_concentration_dimension_gt_30pct",
        "worst_1pct_loss_inside_risk_envelope",
        "production_grade_cost_coverage_gte_95pct",
    ]
    assert payload["blocker_details"]["independent_economic_candidates_gte_300"] == {
        "passed": False,
        "observed": 0,
        "required": ">=300",
        "shortfall": 300,
    }
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["actuals"]["independent_economic_candidates"] == 0
    assert payload["actuals"]["production_grade_cost_coverage"] == 0.0
    assert payload["required"]["independent_economic_candidates"] == ">=300"
    assert payload["required"]["production_grade_cost_coverage"] == ">=0.95"
    assert payload["sample_blockers"][0]["pass_condition"] == "independent_economic_candidates_gte_300"
    assert payload["sample_blockers"][0]["shortfall"] == 300
    assert payload["lockbox_performance_condition_details"]["point_in_time_violations_eq_0"]["passed"] is True
    assert "production_grade_cost_coverage_below_95pct" in payload["non_counting_reasons"]
    assert payload["lockbox_counting_evidence_allowed"] is False
    assert payload["lockbox_prerequisite_for_paper_canary_binding_satisfied"] is False
    assert payload["paper_only"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False
    assert payload["read_only_audit_no_runtime_change"] is True
    assert payload["frozen_candidate_modified"] is False


def _selected_lockbox_pair(idx: int) -> tuple[dict, dict]:
    side = "LONG" if idx % 2 == 0 else "SHORT"
    symbol = f"SYM{idx % 30:02d}USDT"
    timeframe = ("1m", "5m", "15m", "1h")[idx % 4]
    decision_time = f"2026-06-{1 + idx % 10:02d}T00:00:00Z"
    record_id = f"record-{idx}"
    pending = {
        "lockbox_record_id": record_id,
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "model_source": "test_model",
        "symbol": symbol,
        "timeframe": timeframe,
        "decision_time": decision_time,
        "estimated_production_cost": {"fallback": False, "production_grade_evidence": True},
        "selected": True,
    }
    net_return = 30.0 if idx % 5 else -5.0
    label = {
        "lockbox_record_id": record_id,
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "symbol": symbol,
        "timeframe": timeframe,
        "decision_time": decision_time,
        "predicted_direction": side,
        "net_return_bps": net_return,
        "selected": True,
    }
    return pending, label


def test_blind_lockbox_pass_contract_accepts_diversified_positive_evidence() -> None:
    pairs = [_selected_lockbox_pair(idx) for idx in range(300)]
    pending = [pair[0] for pair in pairs]
    labelled = [pair[1] for pair in pairs]
    integrity = {
        "status": "PASS_INTEGRITY_AUDIT",
        "point_in_time_violations": 0,
        "pass_conditions": {
            "labels_have_pending_selection_record": True,
            "selection_record_hashes_match_pending_records": True,
            "selection_fields_marked_immutable": True,
            "selected_fallback_rows_eq_0": True,
        },
        "selected_fallback_rows": 0,
        "label_selection_hash_mismatch_count": 0,
        "selection_fields_rewritten_after_label_count": 0,
        "selection_fields_rewritten_after_outcomes": 0,
        "selection_fields_rewritten_after_outcomes_count": 0,
        "selection_fields_rewritten_after_outcomes_exist": False,
        "append_only_violation_count": 0,
        "pending_append_immutability_conflict_count": 0,
    }

    payload = blind_lockbox_pass_contract_audit(
        policy=_integrity_policy(),
        pending_rows=pending,
        labelled_rows=labelled,
        cost_status={"production_grade_cost_coverage": 0.95},
        lockbox_integrity=integrity,
    )

    assert payload["status"] == "PASS_BLIND_LOCKBOX_PASS_CONTRACT"
    assert payload["independent_economic_candidates"] == 300
    assert payload["selected_label_count"] == 300
    assert payload["independent_economic_candidate_shortfall_to_300"] == 0
    assert payload["independent_candidate_shortfall_to_300"] == 0
    assert payload["independent_economic_candidate_shortfall_to_required"] == 0
    assert payload["independent_candidate_shortfall_to_required"] == 0
    assert payload["symbol_shortfall_to_30"] == 0
    assert payload["long_candidate_shortfall_to_1"] == 0
    assert payload["short_candidate_shortfall_to_1"] == 0
    assert payload["symbols"] == 30
    assert payload["symbol_count"] == 30
    assert payload["long_count"] == 150
    assert payload["short_count"] == 150
    assert payload["long_candidates"] == 150
    assert payload["short_candidates"] == 150
    assert payload["candidate_count_by_direction"] == {"LONG": 150, "SHORT": 150}
    assert payload["selected_label_count_by_direction"] == {"LONG": 150, "SHORT": 150}
    assert payload["minimum_lockbox_evidence"]["independent_economic_candidates"] == ">=300"
    assert payload["minimum_lockbox_observed"]["independent_economic_candidates"] == 300
    assert payload["minimum_lockbox_observed"]["symbols"] == 30
    assert payload["minimum_lockbox_observed"]["long_candidates"] == 150
    assert payload["minimum_lockbox_observed"]["short_candidates"] == 150
    assert payload["minimum_lockbox_shortfalls"]["independent_economic_candidates"] == 0
    assert payload["minimum_lockbox_shortfalls"]["symbols"] == 0
    assert payload["minimum_lockbox_shortfalls"]["long_candidates"] == 0
    assert payload["minimum_lockbox_shortfalls"]["short_candidates"] == 0
    assert payload["minimum_lockbox_shortfalls"]["production_grade_cost_coverage"] == 0.0
    assert payload["minimum_lockbox_pass_conditions"] == payload["pass_conditions"]
    assert payload["next_countability_gate"] is None
    assert payload["lockbox_countability_funnel"] == payload["countability_funnel"]
    assert payload["lockbox_countability_funnel"]["required_independent_economic_candidates"] == 300
    assert payload["lockbox_countability_funnel"]["next_countability_gate"] is None
    assert payload["lockbox_countability_funnel"]["raw_pending_rows"] == 300
    assert payload["lockbox_countability_funnel"]["rejected_pending_rows"] == 0
    assert payload["lockbox_countability_funnel"]["selected_pending_rows"] == 300
    assert payload["lockbox_countability_funnel"]["raw_labelled_rows"] == 300
    assert payload["lockbox_countability_funnel"]["selected_label_rows"] == 300
    assert payload["lockbox_countability_funnel"]["selected_label_rows_with_pending_record"] == 300
    assert payload["lockbox_countability_funnel"]["candidate_identity_bound_selected_label_rows"] == 300
    assert payload["lockbox_countability_funnel"]["production_grade_cost_at_decision_selected_label_rows"] == 300
    assert payload["lockbox_countability_funnel"]["fallback_free_cost_at_decision_selected_label_rows"] == 300
    assert payload["lockbox_countability_funnel"]["unique_independent_economic_candidates"] == 300
    assert payload["lockbox_countability_funnel"]["shortfall_to_required"] == 0
    assert payload["lockbox_countability_funnel"]["primary_pending_rejection_reasons"] == []
    assert all(step["passed"] is True for step in payload["lockbox_countability_funnel_steps"])
    assert payload["zero_independent_candidate_root_cause"] == payload[
        "phase_5_zero_independent_candidate_root_cause"
    ]
    assert payload["zero_independent_candidate_root_cause"]["status"] == "INDEPENDENT_ECONOMIC_CANDIDATES_PRESENT"
    assert payload["zero_independent_candidate_root_cause"]["next_countability_gate"] is None
    assert payload["zero_independent_candidate_root_cause"]["candidate_counting_blockers"] == []
    assert payload["independent_candidate_counting_contract"] == payload["lockbox_counting_contract"]
    assert payload["independent_candidate_counting_contract"]["raw_pending_rows"] == 300
    assert payload["independent_candidate_counting_contract"]["raw_labelled_rows"] == 300
    assert payload["independent_candidate_counting_contract"]["selected_pending_rows"] == 300
    assert payload["independent_candidate_counting_contract"]["selected_label_rows"] == 300
    assert payload["independent_candidate_counting_contract"]["independent_economic_candidates"] == 300
    assert payload["independent_candidate_counting_contract"][
        "pending_rows_not_countable_as_independent_economic_candidates"
    ] == 0
    assert payload["independent_candidate_counting_contract"][
        "labelled_rows_not_countable_as_independent_economic_candidates"
    ] == 0
    assert payload["independent_candidate_counting_contract"]["production_grade_cost_gate_passed"] is True
    assert payload["independent_candidate_counting_contract"]["raw_row_volume_counts_as_lockbox_pass_evidence"] is False
    assert payload["independent_candidate_counting_contract"]["countability_funnel"] == payload[
        "lockbox_countability_funnel"
    ]
    assert payload["independent_candidate_counting_contract"]["next_countability_gate"] is None
    assert payload["pending_rows_not_countable_as_independent_economic_candidates"] == 0
    assert payload["labelled_rows_not_countable_as_independent_economic_candidates"] == 0
    assert payload["lockbox_integrity_status"] == "PASS_INTEGRITY_AUDIT"
    assert payload["labels_have_pending_selection_record"] is True
    assert payload["selection_record_hashes_match_pending_records"] is True
    assert payload["selection_fields_marked_immutable"] is True
    assert payload["selected_fallback_rows_eq_0"] is True
    assert payload["selected_fallback_rows"] == 0
    assert payload["label_selection_hash_mismatch_count"] == 0
    assert payload["selection_fields_rewritten_after_label_count"] == 0
    assert payload["selection_fields_rewritten_after_outcomes_count"] == 0
    assert payload["selection_fields_rewritten_after_outcomes_exist"] is False
    assert payload["append_only_violation_count"] == 0
    assert payload["pending_append_immutability_conflict_count"] == 0
    assert payload["concentration_by_dimension"] == payload["concentration_dimensions"]
    assert payload["non_counting_reasons"] == []
    assert payload["blocked_reasons"] == []
    assert payload["false_positive_rate"] == 0.2
    assert payload["profit_factor"] >= 1.5
    assert payload["max_concentration_pct"] <= 0.30
    assert payload["production_grade_cost_coverage_shortfall_to_95pct"] == 0.0
    assert payload["lockbox_counting_evidence_allowed"] is True
    assert payload["counting_evidence_allowed"] is True
    assert payload["lockbox_prerequisite_for_paper_canary_binding_satisfied"] is True
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert all(detail["passed"] is True for detail in payload["lockbox_pass_blocker_details"].values())
    assert payload["blocker_details"] == payload["lockbox_pass_blocker_details"]
    assert payload["failed_blocker_details"] == {}
    assert payload["failed_lockbox_blocker_details"] == {}
    assert payload["phase_5_failed_blocker_details"] == {}
    assert all(payload["pass_conditions"].values())


def test_public_kline_row_can_label_matured_lockbox_record() -> None:
    candle = parse_kline_candle(
        [
            1782403200000,
            "100.0",
            "103.0",
            "99.0",
            "102.0",
            "10.0",
            1782403259999,
            "1000.0",
        ],
        source="binance_usdm_public_klines_1m",
    )
    assert candle is not None
    record = {
        "lockbox_record_id": "record-1",
        "candidate_id": "challenger_v2_test",
        "policy_fingerprint": "fingerprint",
        "snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-25T00:00:00Z",
        "feature_cutoff": "2026-06-24T23:59:59Z",
        "available_at": "2026-06-25T00:00:00Z",
        "feature_values_by_name": {"close": 100.0},
        "predicted_direction": "LONG",
        "estimated_production_cost": {"total_cost_bps": 12.0, "fee_bps": 4.0},
        "selected": False,
        "rejected": True,
        "rejection_reasons": ["cost_not_production_grade"],
    }

    label = label_for_record(record, [candle], horizon=timedelta(minutes=1))

    assert label is not None
    assert label["label_source"] == "binance_usdm_public_klines_1m"
    assert label["future_finalized_price"] == 102.0
    assert label["gross_return_bps"] == 200.0
    assert label["net_return_bps"] == 188.0
    assert label["label_uses_future_data_as_label_only"] is True


def test_shadow_label_diagnostics_never_counts_as_promotion_evidence() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    pending = [
        {
            "lockbox_record_id": "record-1",
            "score": 25.0,
            "predicted_net_edge_bps": 25.0,
            "threshold_distance_bps": 5.0,
            "production_cost_bps": 12.0,
            "liquidity_status": "MISSING_DEPTH_OR_ORDER_SIZE",
        }
    ]
    labels = [
        {
            "lockbox_record_id": "record-1",
            "symbol": "BTCUSDT",
            "predicted_direction": "LONG",
            "net_return_bps": 10.0,
            "selected": False,
            "rejection_reasons": ["cost_not_production_grade"],
            "label_source": "redis_binance_ohlcv_1m",
        }
    ]

    payload = shadow_label_outcome_diagnostics(
        policy=policy,
        pending_rows=pending,
        labelled_rows=labels,
        cost_status={"production_grade_cost_coverage": 0.0},
    )

    assert payload["labelled_shadow_rows"] == 1
    assert payload["selected_economic_rows"] == 0
    assert payload["all_labelled_stats"]["after_cost_expectancy_bps"] == 10.0
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False


def test_shadow_lockbox_outcome_actionability_audit_fails_shadow_metrics_without_counting_evidence() -> None:
    policy = SimpleNamespace(
        candidate_id="challenger_v2_test",
        policy_fingerprint="fingerprint",
        model_source="test_model",
    )
    shadow_diagnostics = {
        "labelled_shadow_rows": 400,
        "selected_economic_rows": 0,
        "all_labelled_stats": {
            "row_count": 400,
            "symbols": 40,
            "long_count": 200,
            "short_count": 200,
            "after_cost_expectancy_bps": -5.0,
            "expectancy_95pct_lower_bound_bps": -7.0,
            "profit_factor": 0.8,
            "false_positive_rate": 0.55,
            "worst_1pct_loss_bps": -250.0,
        },
    }

    payload = shadow_lockbox_outcome_actionability_audit(
        policy=policy,
        shadow_label_diagnostics=shadow_diagnostics,
        lockbox_pass_contract={
            "status": "BLOCKED_BLIND_LOCKBOX_PASS_CONTRACT",
            "independent_economic_candidates": 0,
            "point_in_time_violations": 0,
        },
        cost_status={"production_grade_cost_coverage": 0.0},
    )

    assert payload["status"] == "DIAGNOSTIC_SHADOW_OUTCOMES_FAIL_PHASE_5_THRESHOLDS_NON_COUNTING"
    assert payload["shadow_rows"] == 400
    assert payload["labelled_shadow_rows"] == 400
    assert payload["selected_shadow_rows"] == 0
    assert payload["economic_shadow_rows"] == 0
    assert payload["after_cost_expectancy_bps"] == -5.0
    assert payload["profit_factor"] == 0.8
    assert payload["shadow_metric_conditions"]["shadow_labelled_rows_gte_300"] is True
    assert payload["shadow_metric_conditions"]["shadow_after_cost_expectancy_gt_0"] is False
    assert payload["shadow_metric_conditions"]["shadow_profit_factor_gte_1_5"] is False
    assert payload["failed_metric_conditions"] == payload["failed_shadow_metric_conditions"]
    assert payload["pass_conditions"]["shadow_after_cost_expectancy_gt_0"] is False
    assert "shadow_after_cost_expectancy_gt_0" in payload["blocked_reasons"]
    assert payload["actuals"]["shadow_after_cost_expectancy_gt_0"] == -5.0
    assert payload["actuals"]["official_independent_economic_candidates_gte_300"] == 0
    assert payload["required"]["shadow_profit_factor_gte_1_5"] == ">=1.5"
    assert payload["required"]["official_production_grade_cost_coverage_gte_95pct"] == ">=0.95"
    assert payload["blocker_details"]["shadow_after_cost_expectancy_gt_0"]["observed"] == -5.0
    assert payload["blocker_details"]["shadow_after_cost_expectancy_gt_0"]["pass_condition"] == (
        "shadow_after_cost_expectancy_gt_0"
    )
    assert payload["failed_blocker_details"] == payload["blocker_details"]
    assert payload["sample_blockers"] == list(payload["blocker_details"].values())[:25]
    assert payload["official_counting_conditions"]["official_independent_economic_candidates_gte_300"] is False
    assert payload["official_counting_conditions"]["official_production_grade_cost_coverage_gte_95pct"] is False
    assert "production_grade_cost_coverage_below_95pct" in payload["non_counting_reasons"]
    assert payload["official_blind_lockbox_rejection_allowed"] is False
    assert payload["official_blind_lockbox_promotion_allowed"] is False
    assert payload["frozen_candidate_tuning_allowed_from_shadow_labels"] is False
    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_live"] is False
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["promotion_evidence"] is False
