from __future__ import annotations

from typing import Any, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import LIVE_GATE_STATUS, safety_footer, utc_now


def _nested_get(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _reviewed_false_block_count_is_current_enough(*, reviewed: int, current: int) -> bool:
    """Avoid routing churn when a live observer adds a few samples after review.

    The false-block observer is continuously updated, so a completed model-review
    packet can be one or two samples behind immediately after it is written. That
    should keep monitoring active, not requeue the same implementation task every
    loop. A materially larger drift still requires a fresh review.
    """

    if current <= reviewed:
        return True
    drift = current - reviewed
    tolerance = max(10, int(max(reviewed, 1) * 0.25))
    return drift <= tolerance


def build_decision_improvement_recommendations(
    *,
    scoreboard_status: Mapping[str, Any],
    paper_loss_status: Mapping[str, Any] | None = None,
    trainer_status: Mapping[str, Any] | None = None,
    paper_edge_status: Mapping[str, Any] | None = None,
    shadow_outcome_status: Mapping[str, Any] | None = None,
    shadow_learning_status: Mapping[str, Any] | None = None,
    expected_move_model_review_status: Mapping[str, Any] | None = None,
    protective_behavior_status: Mapping[str, Any] | None = None,
    symbol_status: Mapping[str, Any] | None = None,
    risk_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    shadow_outcome_status = shadow_outcome_status or {}
    shadow_learning_status = shadow_learning_status or {}
    expected_move_model_review_status = expected_move_model_review_status or {}
    paper_edge_status = paper_edge_status or {}
    protective_behavior_status = protective_behavior_status or {}
    false_block_count = int(shadow_outcome_status.get("false_block_count") or 0)
    resolved_controls = set(paper_edge_status.get("resolved_controls") or [])
    expected_move_review = (
        paper_edge_status.get("expected_move_after_cost_false_block_model_review")
        or _nested_get(paper_edge_status, "paper_pnl", "expected_move_after_cost_false_block_model_review")
        or {}
    )
    reviewed_false_block_count = int(expected_move_review.get("false_block_count") or 0)
    expected_move_review_ready = (
        (
            expected_move_review.get("classification")
            == "EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING"
            or expected_move_review.get("remediation_status")
            == "PAPER_EXPECTED_MOVE_COVERAGE_REMEDIATION_READY"
        )
        and _reviewed_false_block_count_is_current_enough(
            reviewed=reviewed_false_block_count,
            current=false_block_count,
        )
    )
    expected_move_model_review_go_no_go = (
        expected_move_model_review_status.get("go_no_go")
        or expected_move_model_review_status.get("classification")
    )
    expected_move_model_review_false_block_count = int(
        expected_move_model_review_status.get("false_block_count")
        or _nested_get(expected_move_model_review_status, "false_block_audit", "false_block_count")
        or 0
    )
    expected_move_model_review_ready = (
        expected_move_model_review_go_no_go
        in {
            "V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT",
            "V2_EXPECTED_MOVE_MODEL_REVIEW_READY_SELECTIVE_THRESHOLD_UPDATE",
            "V2_EXPECTED_MOVE_MODEL_REVIEW_BLOCKED_EDGE_NOT_FOUND",
            "V2_EXPECTED_MOVE_MODEL_REVIEW_BLOCKED_INSUFFICIENT_SAMPLE",
        }
        and _reviewed_false_block_count_is_current_enough(
            reviewed=expected_move_model_review_false_block_count,
            current=false_block_count,
        )
    )
    recommended_paper_gate_action = (
        expected_move_model_review_status.get("recommended_gate_action")
        or _nested_get(
            expected_move_model_review_status,
            "recommended_paper_gate_changes",
            "recommended_gate_action",
        )
        or "PENDING_EXPECTED_MOVE_MODEL_REVIEW"
    )
    shadow_learning_ready = (
        shadow_learning_status.get("go_no_go")
        == "SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING"
        or shadow_learning_status.get("learning_status")
        == "SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING"
    )
    protective_map_ready = (
        protective_behavior_status.get("go_no_go")
        == "LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP_READY_EDGE_PENDING"
        or protective_behavior_status.get("mapping_status")
        == "READY_EDGE_PENDING_WITH_EXPLICIT_GAPS"
        or protective_behavior_status.get("mapping_status")
        == "READY_EDGE_PENDING_WITH_PAPER_ONLY_EQUIVALENTS"
    )
    remaining_protective_gaps = list(
        protective_behavior_status.get("remaining_protective_behavior_gaps")
        or protective_behavior_status.get("remaining_gaps")
        or []
    )
    core_edge_controls = {
        "missing_expected_move_after_cost_bps_blocks_fill",
        "missing_trainer_source_blocks_fill",
        "missing_feature_freshness_state_blocks_fill",
        "symbol_not_in_paper_symbols_blocks_fill",
        "confidence_alone_cannot_allow_fill",
    }
    tasks = []
    if not core_edge_controls.issubset(resolved_controls):
        tasks.append(
            {
                "task_id": "claude_v2_paper_edge_recovery_and_cost_aware_trade_selection",
                "priority": "P0",
                "reason": "Paper loss attribution found fee/slippage/churn loss and missing edge-after-cost evidence.",
                "required_result": "Confidence alone cannot permit paper fills; missing expected edge blocks and records shadow observation.",
            }
        )
    if not shadow_learning_ready:
        tasks.append(
            {
                "task_id": "claude_add_shadow_outcome_learning_for_blocked_intents",
                "priority": "P1",
                "reason": "Post-filter no-fill state is safe but cannot prove edge without outcome observations.",
                "required_result": "Blocked intents collect 5m/15m/30m/1h after-cost outcomes without paper fees.",
            }
        )
    if not protective_map_ready:
        tasks.append(
            {
                "task_id": "claude_map_legacy_protective_behaviors_to_v2_paper",
                "priority": "P1",
                "reason": "Legacy closure includes churn, lifecycle, TP/stop, reduce-only, and adaptive gate behavior not silently droppable.",
                "required_result": "Each protective behavior is implemented in paper-only form or emitted as an explicit blocker.",
            }
        )
    elif remaining_protective_gaps:
        tasks.append(
            {
                "task_id": "claude_implement_v2_paper_remaining_protective_behavior_gaps",
                "priority": "P1",
                "reason": (
                    "The legacy protective behavior map is complete and explicitly carries remaining paper-only gaps: "
                    + ", ".join(remaining_protective_gaps)
                ),
                "required_result": (
                    "Implement paper-only equivalents or keep exact explicit blockers with tests and no live, "
                    "old Redis, exchange, leverage, or margin mutation."
                ),
            }
        )
    if not {
        "missing_trainer_source_blocks_fill",
        "missing_feature_freshness_state_blocks_fill",
    }.issubset(resolved_controls):
        tasks.insert(
            1,
            {
                "task_id": "claude_add_per_fill_trainer_source_and_feature_freshness",
                "priority": "P0",
                "reason": "Per-fill trainer source and feature freshness are missing or not yet enforced in current paper recovery evidence.",
                "required_result": "Every intent/fill/block carries trainer_source and feature_freshness_state.",
            },
        )
    if false_block_count > 0 and not expected_move_review_ready:
        tasks.insert(
            0,
            {
                "task_id": "claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks",
                "priority": "P0",
                "reason": (
                    f"Shadow outcome observer found {false_block_count} blocked intents that beat costs; "
                    "current false-block reasons show expected-move coverage/model review is required."
                ),
                "required_result": (
                    "Increase native or explicitly accepted expected_move_after_cost_bps coverage from trainer/feature evidence; "
                    "do not use future outcome labels to permit fills and do not loosen the strict paper fill gate."
                ),
            },
        )
    elif false_block_count > 0 and not expected_move_model_review_ready:
        tasks.insert(
            0,
            {
                "task_id": "claude_v2_expected_move_model_review_and_false_block_calibration",
                "priority": "P0",
                "reason": (
                    f"Shadow outcome observer found {false_block_count} false blocks after expected-move "
                    "coverage was added; calibrate the model and thresholds without using hindsight labels "
                    "as fill permission."
                ),
                "required_result": (
                    "Audit false blocks by symbol, side, reason, expected-edge bucket, trainer source, and "
                    "feature freshness; replay thresholds; recommend keep-strict or selective paper-only "
                    "changes without live/canary/shutdown approval."
                ),
            },
        )
    elif (
        expected_move_model_review_go_no_go
        == "V2_EXPECTED_MOVE_MODEL_REVIEW_READY_SELECTIVE_THRESHOLD_UPDATE"
        and recommended_paper_gate_action == "SELECTIVE_THRESHOLD_UPDATE_RECOMMENDED"
    ):
        tasks.insert(
            0,
            {
                "task_id": "claude_apply_v2_expected_move_selective_threshold_update",
                "priority": "P0",
                "reason": (
                    "Expected-move model review found evidence for a selective paper-only gate adjustment."
                ),
                "required_result": (
                    "Apply only the reviewed symbol/timeframe-specific paper gate change, keep confidence "
                    "from authorizing fills alone, and keep live blocked."
                ),
            },
        )
    if not tasks:
        tasks.append(
            {
                "task_id": "monitor_shadow_outcome_observer_and_trainer_parity",
                "priority": "INFO",
                "reason": (
                    "Paper fill boundary, shadow learning, and protective behavior routing have no immediate "
                    "implementation task; edge sample and trainer parity evidence remain unresolved."
                ),
                "required_result": (
                    "Keep V2 paper/shadow observing after-cost outcomes, keep live blocked, and route trainer "
                    "native/derived evidence decisions through shutdown-readiness control."
                ),
            }
        )
    status = {
        "worker_id": "v2_decision_improvement_recommender",
        "generated_at": utc_now(),
        "recommendation_basis": [
            "legacy_v2_decision_comparator",
            "legacy_signal_outcome_observer",
            "decision_quality_scoreboard",
            "paper_loss_attribution",
            "trainer_bridge",
            "paper_edge_recovery",
            "paper_shadow_outcome_observer",
            "symbol_universe",
            "risk_gateway",
        ],
        "shadow_outcome_status": shadow_outcome_status.get("outcome_status"),
        "shadow_learning_status": shadow_learning_status.get("go_no_go")
        or shadow_learning_status.get("learning_status"),
        "protective_behavior_mapping_status": protective_behavior_status.get("go_no_go")
        or protective_behavior_status.get("mapping_status"),
        "remaining_protective_behavior_gaps": remaining_protective_gaps,
        "shadow_false_block_count": false_block_count,
        "shadow_false_block_reason_counts": shadow_outcome_status.get("false_block_reason_counts") or {},
        "expected_move_model_review_go_no_go": expected_move_model_review_go_no_go,
        "expected_move_model_review_false_block_count": expected_move_model_review_false_block_count,
        "recommended_paper_gate_action": recommended_paper_gate_action,
        "next_tasks": tasks,
        "claude_task_ready": tasks[0]["task_id"],
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "does_not_approve_live": True,
        "does_not_approve_legacy_shutdown": True,
    }
    status.update(safety_footer())
    return status
