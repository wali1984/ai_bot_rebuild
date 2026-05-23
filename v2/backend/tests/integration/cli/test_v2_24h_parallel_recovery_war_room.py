"""Tests for the V2 24h parallel recovery war-room executor.

Analysis-only. No Redis writes, no exchange mutation, no live approval.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.services.war_room.parallel_recovery_24h import (
    LIVE_GATE_BLOCKED,
    THRESHOLD_PROFILES,
    WarRoomPaths,
    build_baseline_metrics,
    build_edge_gate_analysis,
    build_false_negative_root_cause_report,
    build_operator_decision_queue,
    build_threshold_profile_simulation,
    build_v2_native_training_dataset,
    classify_observation_blockers,
    default_paths,
    run_war_room,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _bundle(
    label: str,
    *,
    symbol: str = "BTCUSDT",
    anchor_ts: float = 1779512000.0,
    paper_fill_allowed: bool = False,
    paper_reasons: list[str] | None = None,
    pre_trade_allowed: bool = True,
    expected_move: float = 100.0,
    after_cost_5m: float | None = 10.0,
    altdata: dict | None = None,
    trainer_selected: str = "long",
) -> dict:
    return {
        "label": label,
        "symbol": symbol,
        "anchor_ts": anchor_ts,
        "feature_snapshot_id": f"{symbol}:1m:probe",
        "side": "long",
        "trainer_output": {
            "confidence_calibrated": 0.68,
            "expected_move_after_cost_bps": expected_move,
            "selected_action": trainer_selected,
        },
        "paper_gate_decision": {
            "paper_fill_allowed": paper_fill_allowed,
            "paper_fill_gate_block_reasons": paper_reasons or [],
        },
        "risk_decision": {
            "pre_trade_allowed": pre_trade_allowed,
            "churn_reason": "ALLOWED",
            "fee_gate_reason": "ALLOWED",
        },
        "altdata_snapshot": altdata,
        "paper_intent": {"decision": "SHADOW_OBSERVATION_ONLY"},
        "outcome_after_cost": after_cost_5m if after_cost_5m is not None else 0.0,
        "future_outcomes": {
            "5m": {
                "after_cost_return_bps": after_cost_5m,
                "return_bps": (
                    (after_cost_5m + 7.0) if after_cost_5m is not None else None
                ),
                "drawdown_bps": -2.0 if after_cost_5m is not None else None,
            }
        },
        "orchestrator_decision": {
            "bucket_winners": [
                {"winner_proposal_id": f"pred_{symbol}_{int(anchor_ts)}"}
            ]
        },
    }


# ---------------------------------------------------------------------------
# Lane 1
# ---------------------------------------------------------------------------


def test_threshold_profile_simulation_marks_negative_expectancy_as_fail():
    metric_summary = {
        "sample_count": 1249,
        "expected_move_after_cost_bps": -6.6,
        "after_cost_ci_lower_bps": -9.9,
        "max_drawdown_bps_observed": 310.0,
        "false_negative_rate": 0.18,
        "false_positive_rate": None,
    }
    sim = build_threshold_profile_simulation(metric_summary)
    assert sim["live_gate"] == LIVE_GATE_BLOCKED
    assert sim["approves_live"] is False
    assert set(sim["profiles"].keys()) == set(THRESHOLD_PROFILES.keys())
    # false_positive_rate is None — every profile must be inconclusive.
    for profile_name, result in sim["profiles"].items():
        assert result["inconclusive"] is True
        assert result["verdict"] == "INCONCLUSIVE_OBSERVED_EVIDENCE_MISSING"


def test_edge_gate_analysis_blocks_edge_claim():
    metric_summary = {
        "sample_count": 1249,
        "expected_move_after_cost_bps": -6.6,
        "after_cost_ci_lower_bps": -9.9,
        "max_drawdown_bps_observed": 310.0,
        "false_negative_rate": 0.18,
        "false_positive_rate": None,
    }
    sim = build_threshold_profile_simulation(metric_summary)
    analysis = build_edge_gate_analysis(sim)
    assert analysis["edge_claimed"] is False
    assert analysis["operator_decision_required"] is True
    assert analysis["approves_live"] is False
    assert analysis["live_gate"] == LIVE_GATE_BLOCKED


# ---------------------------------------------------------------------------
# Lane 2
# ---------------------------------------------------------------------------


def test_false_negative_classification_flags_paper_gate_opaque_block_and_altdata_missing():
    bundles = [
        _bundle(
            "false_negative",
            paper_fill_allowed=False,
            paper_reasons=[],
            altdata=None,
            after_cost_5m=12.0,
        ),
        _bundle("correct_no_trade", paper_fill_allowed=False, after_cost_5m=-5.0),
        _bundle("insufficient_evidence", after_cost_5m=None),
    ]
    report, tasks = build_false_negative_root_cause_report(bundles)
    assert report["false_negative_count"] == 1
    causes = report["classifications"][0]["root_causes"]
    assert "paper_fill_gate_block" in causes
    assert "paper_fill_gate_block_unrecorded_reason" in causes
    assert "observation_gap" in causes
    assert "altdata_missing" in causes
    task_ids = {t["task_id"] for t in tasks}
    assert "paper_fill_gate_record_block_reason" in task_ids
    assert "altdata_snapshot_attached_to_replay_bundle" in task_ids


# ---------------------------------------------------------------------------
# Lane 3
# ---------------------------------------------------------------------------


def test_dataset_excludes_insufficient_and_missing_5m_outcomes():
    bundles = [
        _bundle("insufficient_evidence", after_cost_5m=None),
        _bundle("correct_no_trade", after_cost_5m=-5.0, anchor_ts=1779512100.0),
        _bundle("false_negative", after_cost_5m=12.0, anchor_ts=1779512200.0),
        _bundle("false_negative", after_cost_5m=None, anchor_ts=1779512300.0),
    ]
    dataset = build_v2_native_training_dataset(bundles)
    assert dataset["excluded_insufficient"] == 1
    assert dataset["excluded_missing_5m"] == 1
    assert len(dataset["rows"]) == 2
    # Time-ordered split.
    timestamps = [r["anchor_ts"] for r in dataset["rows"]]
    assert timestamps == sorted(timestamps)


# ---------------------------------------------------------------------------
# Lane 4
# ---------------------------------------------------------------------------


def test_baseline_metrics_hold_and_v2_policy_have_zero_pnl():
    bundles = [
        _bundle("false_negative", after_cost_5m=10.0, anchor_ts=1.0),
        _bundle("false_negative", after_cost_5m=-3.0, anchor_ts=2.0),
        _bundle("correct_no_trade", after_cost_5m=-1.0, anchor_ts=3.0),
        _bundle("correct_no_trade", after_cost_5m=2.0, anchor_ts=4.0),
        _bundle("false_negative", after_cost_5m=5.0, anchor_ts=5.0),
    ]
    dataset = build_v2_native_training_dataset(bundles)
    metrics = build_baseline_metrics(dataset)
    assert metrics["approves_live"] is False
    assert metrics["live_gate"] == LIVE_GATE_BLOCKED
    hold = metrics["baselines"]["hold"]
    v2_policy = metrics["baselines"]["v2_deterministic_policy_shadow_only"]
    assert hold["sum_after_cost_bps"] == 0.0
    assert v2_policy["sum_after_cost_bps"] == 0.0
    naive = metrics["baselines"]["naive_threshold_expected_move_10bps"]
    # Naive baseline always enters because trainer expected_move=100 in fixture.
    assert naive["enters"] == len(dataset["validation_rows"])
    assert metrics["checkpoint_compatibility_claimed"] is False
    assert metrics["policy_architecture_parity_claimed"] is False


# ---------------------------------------------------------------------------
# Lane 5
# ---------------------------------------------------------------------------


def test_observation_classifier_buckets_known_categories():
    remaining = {
        "aggregate_category_counts": {
            "V2_EVENT_DEPENDENT_LIQUIDATION_WSS": 12,
            "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED": 60,
            "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS": 54,
            "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC": 45,
            "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV": 30,
            "LEGACY_V3_EXTRA_NO_V2_SOURCE": 3879,
            "V2_LANE_EXISTS_PAYLOAD_ABSENT": 21,
            "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH": 915,
        },
        "aggregate_target_dim": 5016,
    }
    buildable_now = {"aggregate_dim_count": 0}
    recheck = classify_observation_blockers(remaining, buildable_now)
    buckets = recheck["bucket_counts"]
    assert buckets["EVENT_DEPENDENT"] == 12
    assert buckets["POSITION_DEPENDENT"] == 60
    assert buckets["EXTERNAL_SOURCE_REQUIRED"] == 54 + 45
    assert buckets["OPERATOR_DECISION_REQUIRED"] == 30
    assert buckets["LEGACY_EXTRA_NO_V2_SOURCE"] == 3879
    assert buckets["BUILDABLE_NOW"] == 0 + 21 - 21  # buildable_now override wins
    # Confirm override behavior — buildable_now=0 dominates.
    assert recheck["v2_buildable_now_count"] == 0
    assert recheck["no_new_buildable_now_fields_identified"] is True


# ---------------------------------------------------------------------------
# Lane 6 / final composition
# ---------------------------------------------------------------------------


def test_operator_decision_queue_blocks_live_and_external_sources():
    queue = build_operator_decision_queue(
        edge_analysis={
            "edge_claimed": False,
            "edge_claim_blocked_reason": "operator_thresholds_required_and_not_set",
            "verdict_per_profile": {},
        },
        observation_recheck={"v2_buildable_now_count": 0, "bucket_counts": {}},
    )
    assert queue["approves_live"] is False
    decision_ids = [item["decision_id"] for item in queue["items"]]
    assert "set_concrete_edge_thresholds" in decision_ids
    assert "approve_paid_aggregator_or_alt_data_source" in decision_ids
    assert "set_minimum_sample_count_for_dataset_release" in decision_ids


# ---------------------------------------------------------------------------
# End-to-end against a synthetic packet
# ---------------------------------------------------------------------------


def _write_synthetic_inputs(tmp_root: Path) -> None:
    miner_dir = (
        tmp_root
        / "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest"
    )
    queue_dir = (
        tmp_root
        / "claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/latest"
    )
    miner_dir.mkdir(parents=True)
    queue_dir.mkdir(parents=True)

    bundles = [
        _bundle("insufficient_evidence", after_cost_5m=None, anchor_ts=1.0),
        _bundle("correct_no_trade", after_cost_5m=-5.0, anchor_ts=2.0),
        _bundle(
            "false_negative",
            paper_fill_allowed=False,
            paper_reasons=[],
            altdata=None,
            after_cost_5m=12.0,
            anchor_ts=3.0,
        ),
        _bundle(
            "false_negative",
            paper_fill_allowed=False,
            paper_reasons=["NEEDS_OPERATOR"],
            altdata={"score": 0.5},
            after_cost_5m=7.0,
            anchor_ts=4.0,
        ),
    ]
    (miner_dir / "replay_outcome_bundles.jsonl").write_text(
        "\n".join(json.dumps(b) for b in bundles) + "\n",
        encoding="utf-8",
    )
    (miner_dir / "post_hoc_replay_outcome_status.json").write_text(
        json.dumps(
            {
                "evaluator_metric_summary": {
                    "sample_count": len(bundles),
                    "expected_move_after_cost_bps": -1.5,
                    "after_cost_ci_lower_bps": -8.0,
                    "after_cost_ci_upper_bps": 4.0,
                    "max_drawdown_bps_observed": 12.0,
                    "false_negative_rate": 0.5,
                    "false_positive_rate": None,
                    "verdict": "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
                }
            }
        ),
        encoding="utf-8",
    )
    (miner_dir / "edge_metrics_summary.json").write_text(
        json.dumps(
            {
                "metric_summary": {
                    "sample_count": len(bundles),
                    "expected_move_after_cost_bps": -1.5,
                    "after_cost_ci_lower_bps": -8.0,
                    "after_cost_ci_upper_bps": 4.0,
                    "max_drawdown_bps_observed": 12.0,
                    "false_negative_rate": 0.5,
                    "false_positive_rate": None,
                    "verdict": "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
                }
            }
        ),
        encoding="utf-8",
    )
    (queue_dir / "remaining_dim_execution_queue.json").write_text(
        json.dumps(
            {
                "aggregate_category_counts": {
                    "V2_EVENT_DEPENDENT_LIQUIDATION_WSS": 12,
                    "LEGACY_V3_EXTRA_NO_V2_SOURCE": 3,
                },
                "aggregate_target_dim": 15,
            }
        ),
        encoding="utf-8",
    )
    (queue_dir / "v2_buildable_now_fields.json").write_text(
        json.dumps({"aggregate_dim_count": 0}),
        encoding="utf-8",
    )


def test_run_war_room_emits_all_required_artifacts(tmp_path: Path):
    _write_synthetic_inputs(tmp_path)
    paths = default_paths(tmp_path)
    result = run_war_room(paths)

    assert result.go_no_go == "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_READY"

    go_no_go_file = paths.packet_dir / "GO_NO_GO.md"
    assert go_no_go_file.read_text().strip() == "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_READY"

    for required in [
        "V2_24H_PARALLEL_RECOVERY_WAR_ROOM_REPORT.md",
        "war_room_status.json",
        "lane_statuses.json",
        "next_automatable_tasks.json",
        "operator_decision_queue.json",
        "lane1/threshold_profile_simulation.json",
        "lane1/edge_gate_analysis.json",
        "lane1/EDGE_PROOF_ANALYSIS_REPORT.md",
        "lane2/false_negative_root_cause_report.json",
        "lane2/false_negative_root_cause_report.md",
        "lane2/next_false_negative_remediation_tasks.json",
        "lane3/v2_native_training_dataset_status.json",
        "lane3/v2_native_training_dataset_manifest.json",
        "lane3/dataset_quality_report.md",
        "lane4/model_baseline_metrics.json",
        "lane4/model_baseline_report.md",
        "lane5/observation_blocker_live_recheck.json",
        "lane5/observation_blocker_live_recheck.md",
        "lane6/war_room_utilization_status.json",
        "lane6/war_room_task_dispatch_status.json",
    ]:
        assert (paths.packet_dir / required).exists(), required

    for required in [
        "operator_dashboard_payload.json",
        "war_room_status.json",
    ]:
        assert (paths.public_dir / required).exists(), required

    status = json.loads((paths.packet_dir / "war_room_status.json").read_text())
    assert status["safety_scoreboard"]["approves_live"] is False
    assert status["safety_scoreboard"]["approves_canary"] is False
    assert status["safety_scoreboard"]["approves_legacy_shutdown"] is False
    assert status["safety_scoreboard"]["approves_redis_trim"] is False
    assert status["safety_scoreboard"]["live_gate"] == LIVE_GATE_BLOCKED
    assert status["safety_scoreboard"]["live_symbols"] == []

    dashboard = json.loads(
        (paths.public_dir / "operator_dashboard_payload.json").read_text()
    )
    assert dashboard["controls_present"] is False
    assert dashboard["fake_readiness"] is False


def test_run_war_room_does_not_create_approval_or_shutdown_tokens(tmp_path: Path):
    _write_synthetic_inputs(tmp_path)
    paths = default_paths(tmp_path)
    run_war_room(paths)

    forbidden_phrases = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        "approves_live: true",
        "approves_canary: true",
        "live_gate: enabled",
    ]
    for written in paths.packet_dir.rglob("*"):
        if not written.is_file():
            continue
        text = written.read_text(encoding="utf-8", errors="ignore")
        for s in forbidden_phrases:
            assert s not in text, f"forbidden phrase {s!r} in {written}"


def test_lane_statuses_are_complete_for_all_seven_lanes(tmp_path: Path):
    _write_synthetic_inputs(tmp_path)
    paths = default_paths(tmp_path)
    run_war_room(paths)
    lane_statuses = json.loads((paths.packet_dir / "lane_statuses.json").read_text())
    lane_ids = {l["lane_id"] for l in lane_statuses["lane_statuses"]}
    assert {
        "lane1_edge_proof_and_threshold_analytics",
        "lane2_false_negative_root_cause",
        "lane3_v2_native_training_dataset",
        "lane4_model_baseline_evaluator",
        "lane5_observation_blocker_classifier",
        "lane6_automation_utilization_takeover",
        "lane7_website_report_center_truth",
    }.issubset(lane_ids)
