"""Global V2 production-equivalence final blocker classification.

Reads the lane payloads listed in the requirement and emits a single
classification matrix plus next-action artifacts. Refuses to mark anything
SAFE_TO_SHUTDOWN unless every blocker is resolved or operator-accepted.

Categories (one per blocker):
- TECHNICAL_AUTOMATABLE
- EVENT_DEPENDENT
- POSITION_DEPENDENT
- EXTERNAL_SOURCE_REQUIRED
- OPERATOR_DECISION_REQUIRED
- CODEX_REVIEW_REQUIRED
- ALREADY_REMEDIATED_AWAITING_FRESH_EVIDENCE
- NOT_REQUIRED_FOR_V2_PAPER_ONLY
- BLOCKS_PRODUCTION_EQUIVALENCE (umbrella tag)

Mission categories (one or more per blocker):
- runtime stability / observation completeness / model/policy readiness /
  checkpoint readiness / decision match / paper edge / risk control /
  symbol selection / readiness-gate / website/report truth /
  startup manifest parity / bridge exit
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_production_equivalence_final_blocker_classification_and_next_action"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_production_equivalence_final_blocker_classification_and_next_action"
    / "latest"
)

READY_MARKER = "V2_PRODUCTION_EQUIVALENCE_FINAL_BLOCKER_CLASSIFICATION_AND_NEXT_ACTION_READY"
BLOCKED_MARKER = "V2_PRODUCTION_EQUIVALENCE_FINAL_BLOCKER_CLASSIFICATION_AND_NEXT_ACTION_BLOCKED"

INPUTS = {
    "war_room": "v2/frontend/public/v2_24h_parallel_recovery_war_room/latest/war_room_status.json",
    "replay_miner": "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/operator_dashboard_payload.json",
    "full_observation_builder": "v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json",
    "liquidation_burndown": "v2/frontend/public/v2_full_observation_liquidation_burndown/latest/operator_dashboard_payload.json",
    "bridge_exit_execution": "v2/frontend/public/v2_native_dynamic_runtime_and_trainer_bridge_exit_execution/latest/operator_dashboard_payload.json",
    "native_trainer_baseline": "v2/frontend/public/v2_native_trainer_dataset_and_baseline_model/latest/operator_dashboard_payload.json",
    "startup_manifest_runtime": "v2/frontend/public/v2_full_paper_only_startup_manifest_runtime/latest/operator_dashboard_payload.json",
    "legacy_startup_parity": "v2/frontend/public/v2_legacy_startup_manifest_parity_and_bridge_exit/latest/operator_dashboard_payload.json",
    "risk_gateway_canary_hard_gates": "v2/frontend/public/risk_gateway_canary_hard_gates/latest/operator_dashboard_payload.json",
    "final_capital_gate": "v2/frontend/public/final_live_capital_gate/latest/operator_dashboard_payload.json",
    "checkpoint_promotion": "v2/frontend/public/v2_checkpoint_promotion/latest/operator_dashboard_payload.json",
    "runtime_soak_production_equivalence": "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/operator_dashboard_payload.json",
    "worker_pool_mission_progress": "v2/frontend/public/v2_worker_pool_mission_progress/latest/worker_pool_mission_progress_status.json",
    "report_index": "v2/frontend/public/v2_report_center/latest/report_index.json",
}

SAFETY_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "modifies_legacy_repo": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
    "creates_approval_tokens": False,
    "fabricates_missing_observations": False,
    "fabricates_edge": False,
}


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def freshness_seconds(payload: dict[str, Any] | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in ("generated_utc", "generated_at", "updated_utc", "updated_at"):
        v = payload.get(key)
        if not isinstance(v, str):
            continue
        try:
            ts = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return int((datetime.now(timezone.utc) - ts).total_seconds())
        except ValueError:
            continue
    return None


def _push(rows: list[dict[str, Any]], **fields: Any) -> None:
    rows.append(fields)


def classify_blockers(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # 1. full_observation_builder
    fob = payloads.get("full_observation_builder") or {}
    if fob.get("operator_required") is True:
        ext = fob.get("external_source_required_families") or []
        opd = fob.get("operator_decision_required_families") or []
        if ext:
            _push(
                rows,
                blocker_id="full_observation_builder.external_sources",
                classification="EXTERNAL_SOURCE_REQUIRED",
                mission_categories=["observation completeness", "model/policy readiness"],
                requirement=(
                    "Operator must approve adoption of external sources: "
                    + ", ".join(sorted(set(str(e) for e in ext)))
                ),
                evidence_path=INPUTS["full_observation_builder"],
                operator_required=True,
                blocks_production_equivalence=True,
                blocks_shutdown=True,
                blocks_live=True,
                blocks_paper_only=False,
            )
        if opd:
            _push(
                rows,
                blocker_id="full_observation_builder.operator_decision_families",
                classification="OPERATOR_DECISION_REQUIRED",
                mission_categories=["observation completeness"],
                requirement=(
                    "Operator must decide unified-feature inclusion for: "
                    + ", ".join(sorted(set(str(o) for o in opd)))
                ),
                evidence_path=INPUTS["full_observation_builder"],
                operator_required=True,
                blocks_production_equivalence=True,
                blocks_shutdown=True,
                blocks_live=True,
                blocks_paper_only=False,
            )
        # liquidations event-dependent / TA conditional-undefined
        if isinstance(fob.get("event_dependent_families"), list) and fob["event_dependent_families"]:
            _push(
                rows,
                blocker_id="full_observation_builder.event_dependent",
                classification="EVENT_DEPENDENT",
                mission_categories=["observation completeness", "symbol selection"],
                requirement=(
                    "Wait for real per-symbol liquidation events: "
                    + ", ".join(sorted(set(str(e) for e in fob["event_dependent_families"])))
                    + ". Do not fabricate missing per-symbol fields."
                ),
                evidence_path=INPUTS["full_observation_builder"],
                operator_required=False,
                blocks_production_equivalence=False,
                blocks_shutdown=False,
                blocks_live=False,
                blocks_paper_only=False,
            )
        if isinstance(fob.get("conditionally_undefined_families"), list) and fob["conditionally_undefined_families"]:
            _push(
                rows,
                blocker_id="full_observation_builder.conditionally_undefined",
                classification="NOT_REQUIRED_FOR_V2_PAPER_ONLY",
                mission_categories=["observation completeness"],
                requirement=(
                    "Mathematically undefined fields in: "
                    + ", ".join(sorted(set(str(f) for f in fob["conditionally_undefined_families"])))
                    + ". Do not zero-fill or invent."
                ),
                evidence_path=INPUTS["full_observation_builder"],
                operator_required=False,
                blocks_production_equivalence=False,
                blocks_shutdown=False,
                blocks_live=False,
                blocks_paper_only=False,
            )

    # 2. checkpoint promotion
    cp = payloads.get("checkpoint_promotion") or {}
    if "OPERATOR_REQUIRED" in str(cp.get("go_no_go") or "") or cp.get("overall_state") == "CHECKPOINT_OPERATOR_REQUIRED":
        _push(
            rows,
            blocker_id="checkpoint_promotion",
            classification="OPERATOR_DECISION_REQUIRED",
            mission_categories=["checkpoint readiness", "model/policy readiness", "decision match"],
            requirement=(
                "Operator must provide or approve a checkpoint blob under the "
                "protected runtime policy. Claude/Codex must not deserialize, "
                "mutate, or promote checkpoints autonomously."
            ),
            evidence_path=INPUTS["checkpoint_promotion"],
            operator_required=True,
            blocks_production_equivalence=True,
            blocks_shutdown=True,
            blocks_live=True,
            blocks_paper_only=False,
        )

    # 3. paper edge proven
    war = payloads.get("war_room") or {}
    edge_summary = war.get("edge_gate_summary") or {}
    eval_summary = war.get("evaluator_summary") or {}
    if not edge_summary.get("edge_claimed", False) or (
        isinstance(eval_summary.get("expected_move_after_cost_bps"), (int, float))
        and eval_summary["expected_move_after_cost_bps"] <= 0
    ):
        _push(
            rows,
            blocker_id="paper_edge_not_proven",
            classification="EVENT_DEPENDENT",
            mission_categories=["paper edge", "model/policy readiness", "risk control"],
            requirement=(
                "Operator must accept numeric edge thresholds AND paper/shadow "
                "evidence must show statistically defensible positive after-cost "
                "expectancy. Worker activity, task completion, or one-off "
                "correct_no_trade rows do not prove edge."
            ),
            evidence_path=INPUTS["war_room"],
            operator_required=True,
            blocks_production_equivalence=True,
            blocks_shutdown=True,
            blocks_live=True,
            blocks_paper_only=False,
            edge_reason=str(edge_summary.get("edge_claim_blocked_reason") or "unset"),
            after_cost_expectancy_bps=eval_summary.get("expected_move_after_cost_bps"),
        )

    # 4. runtime soak / production equivalence
    soak = payloads.get("runtime_soak_production_equivalence") or {}
    shutdown_blockers = [str(b) for b in (soak.get("shutdown_blockers") or [])]
    if shutdown_blockers:
        _push(
            rows,
            blocker_id="legacy_shutdown.legacy_runtime_owner",
            classification="OPERATOR_DECISION_REQUIRED"
            if "LEGACY_STILL_OWNS_PRODUCTION_RUNTIME" in shutdown_blockers
            else "ALREADY_REMEDIATED_AWAITING_FRESH_EVIDENCE",
            mission_categories=["readiness-gate", "runtime stability"],
            requirement=(
                "Operator must explicitly approve legacy production runtime "
                "stop. CLAUDE.md forbids Claude/Codex from stopping legacy."
            ),
            evidence_path=INPUTS["runtime_soak_production_equivalence"],
            operator_required=True,
            blocks_production_equivalence=False,
            blocks_shutdown=True,
            blocks_live=False,
            blocks_paper_only=False,
        )
        if "LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE" in shutdown_blockers:
            _push(
                rows,
                blocker_id="legacy_shutdown.legacy_redis_keys_active",
                classification="OPERATOR_DECISION_REQUIRED",
                mission_categories=["readiness-gate", "runtime stability"],
                requirement=(
                    "Operator must approve Redis trim (approves_redis_trim=true) "
                    "before legacy production Redis keys can be removed. "
                    "CLAUDE.md forbids Claude/Codex from writing old Redis."
                ),
                evidence_path=INPUTS["runtime_soak_production_equivalence"],
                operator_required=True,
                blocks_production_equivalence=False,
                blocks_shutdown=True,
                blocks_live=False,
                blocks_paper_only=False,
            )

    # 5. governor freshness for runtime soak / production equivalence
    if "GOVERNOR_BLOCKED" in str(soak.get("go_no_go") or ""):
        fail_blockers = [str(b) for b in (soak.get("fail_blockers") or [])]
        _push(
            rows,
            blocker_id="runtime_soak_production_equivalence.governor_stale_or_blocked",
            classification="TECHNICAL_AUTOMATABLE"
            if any("PAYLOAD_STALE_OR_MISSING" in b for b in fail_blockers)
            else "CODEX_REVIEW_REQUIRED",
            mission_categories=["runtime stability", "readiness-gate"],
            requirement=(
                "Refresh scoreboard + soak observer outputs and re-run "
                "codex_runtime_soak_and_production_equivalence_governor.py --once."
                if any("PAYLOAD_STALE_OR_MISSING" in b for b in fail_blockers)
                else "Codex governor disagreed with V2; requires Codex re-run."
            ),
            evidence_path=INPUTS["runtime_soak_production_equivalence"],
            operator_required=False,
            blocks_production_equivalence=True,
            blocks_shutdown=True,
            blocks_live=False,
            blocks_paper_only=False,
            fail_blockers=fail_blockers,
        )

    # 6. risk caps / capital recovery (only block live; not paper)
    risk = payloads.get("risk_gateway_canary_hard_gates") or {}
    if not (risk.get("ready") or risk.get("go_no_go") in ("RISK_GATEWAY_CANARY_HARD_GATES_READY",)):
        _push(
            rows,
            blocker_id="risk_caps_canary_hard_gates_unset",
            classification="OPERATOR_DECISION_REQUIRED",
            mission_categories=["risk control", "readiness-gate"],
            requirement=(
                "Operator must set/confirm risk caps and canary hard gates "
                "before live can be considered. Does not block paper-only V2."
            ),
            evidence_path=INPUTS["risk_gateway_canary_hard_gates"],
            operator_required=True,
            blocks_production_equivalence=False,
            blocks_shutdown=False,
            blocks_live=True,
            blocks_paper_only=False,
            payload_freshness_seconds=freshness_seconds(risk),
        )
    cap = payloads.get("final_capital_gate") or {}
    if not (cap.get("ready") or cap.get("go_no_go") in ("FINAL_LIVE_CAPITAL_GATE_READY",)):
        _push(
            rows,
            blocker_id="capital_recovery_gate_unset",
            classification="OPERATOR_DECISION_REQUIRED",
            mission_categories=["risk control", "readiness-gate"],
            requirement=(
                "Operator must set/confirm capital recovery thresholds before "
                "live capital deployment. Does not block paper-only V2."
            ),
            evidence_path=INPUTS["final_capital_gate"],
            operator_required=True,
            blocks_production_equivalence=False,
            blocks_shutdown=False,
            blocks_live=True,
            blocks_paper_only=False,
            payload_freshness_seconds=freshness_seconds(cap),
        )

    # 7. startup / bridge / website lanes - check status
    sm = payloads.get("startup_manifest_runtime") or {}
    if "READY" not in str(sm.get("go_no_go") or ""):
        _push(
            rows,
            blocker_id="startup_manifest_runtime",
            classification="CODEX_REVIEW_REQUIRED",
            mission_categories=["startup manifest parity", "runtime stability"],
            requirement="Re-run startup manifest runtime to refresh evidence.",
            evidence_path=INPUTS["startup_manifest_runtime"],
            operator_required=False,
            blocks_production_equivalence=True,
            blocks_shutdown=True,
            blocks_live=False,
            blocks_paper_only=False,
        )
    bp = payloads.get("bridge_exit_execution") or {}
    if "READY" not in str(bp.get("go_no_go") or ""):
        _push(
            rows,
            blocker_id="bridge_exit_execution",
            classification="CODEX_REVIEW_REQUIRED",
            mission_categories=["bridge exit", "runtime stability"],
            requirement="Re-run bridge-exit execution and Codex review.",
            evidence_path=INPUTS["bridge_exit_execution"],
            operator_required=False,
            blocks_production_equivalence=True,
            blocks_shutdown=True,
            blocks_live=False,
            blocks_paper_only=False,
        )

    # 8. report_index residual lanes - sweep for any BLOCKED/FAIL/OPERATOR_DECISION_REQUIRED
    # not already covered above
    covered_lanes = {
        "checkpoint_promotion",
        "full_observation_builder",
        "runtime_soak_and_production_equivalence",
        "codex_24h_parallel_recovery_war_room_governor",
    }
    report_index = payloads.get("report_index") or {}
    for lane in report_index.get("lanes") or []:
        if not isinstance(lane, dict):
            continue
        rid = str(lane.get("report_id") or "")
        if rid in covered_lanes:
            continue
        if lane.get("status") not in ("BLOCKED", "FAIL", "OPERATOR_DECISION_REQUIRED"):
            continue
        op_required = lane.get("status") == "OPERATOR_DECISION_REQUIRED"
        marker = str(lane.get("go_no_go") or "")
        if any(t in marker for t in ("OPERATOR_REQUIRED", "OPERATOR_DECISION_REQUIRED")):
            op_required = True
        _push(
            rows,
            blocker_id=f"report_lane.{rid}",
            classification=(
                "OPERATOR_DECISION_REQUIRED" if op_required else "CODEX_REVIEW_REQUIRED"
            ),
            mission_categories=["website/report truth", "runtime stability"],
            requirement="Resolve underlying lane; re-index report center.",
            evidence_path=lane.get("public_payload_path"),
            operator_required=op_required,
            blocks_production_equivalence=bool(lane.get("blocks_production_equivalence")),
            blocks_shutdown=bool(lane.get("blocks_shutdown")),
            blocks_live=bool(lane.get("blocks_live")),
            blocks_paper_only=False,
        )

    return rows


def build_next_action(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for row in rows:
        cls = row["classification"]
        if cls == "TECHNICAL_AUTOMATABLE":
            action = "AUTOSEED_TECHNICAL_REMEDIATION"
        elif cls == "EVENT_DEPENDENT":
            action = "WAIT_FOR_EVENT_DO_NOT_FABRICATE"
        elif cls == "POSITION_DEPENDENT":
            action = "WAIT_FOR_POSITION_STATE_CHANGE"
        elif cls == "EXTERNAL_SOURCE_REQUIRED":
            action = "OPERATOR_APPROVES_OR_REJECTS_EXTERNAL_SOURCE"
        elif cls == "OPERATOR_DECISION_REQUIRED":
            action = "OPERATOR_DECISION_REQUIRED_NO_AUTOMATION"
        elif cls == "CODEX_REVIEW_REQUIRED":
            action = "RE_RUN_CODEX_REVIEW_OR_GOVERNOR"
        elif cls == "ALREADY_REMEDIATED_AWAITING_FRESH_EVIDENCE":
            action = "WAIT_FOR_FRESH_EVIDENCE_THEN_RE_INDEX"
        elif cls == "NOT_REQUIRED_FOR_V2_PAPER_ONLY":
            action = "NO_ACTION_REQUIRED_FOR_PAPER_ONLY"
        else:
            action = "REVIEW_BLOCKER_MANUALLY"
        actions.append({
            "blocker_id": row["blocker_id"],
            "classification": cls,
            "next_action": action,
            "requirement": row["requirement"],
            "operator_required": row["operator_required"],
            "blocks_production_equivalence": row["blocks_production_equivalence"],
            "blocks_shutdown": row["blocks_shutdown"],
            "blocks_live": row["blocks_live"],
            "blocks_paper_only": row.get("blocks_paper_only", False),
        })
    return actions


def build_operator_decision_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "blocker_id": r["blocker_id"],
            "classification": r["classification"],
            "requirement": r["requirement"],
            "evidence_path": r.get("evidence_path"),
            "mission_categories": r.get("mission_categories"),
        }
        for r in rows
        if r["classification"] in ("OPERATOR_DECISION_REQUIRED", "EXTERNAL_SOURCE_REQUIRED")
    ]


def build_event_dependent_watchlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "blocker_id": r["blocker_id"],
            "requirement": r["requirement"],
            "evidence_path": r.get("evidence_path"),
            "mission_categories": r.get("mission_categories"),
            "do_not_fabricate": True,
        }
        for r in rows
        if r["classification"] in ("EVENT_DEPENDENT", "POSITION_DEPENDENT")
    ]


def build_technical_automatable_queue_seed(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "blocker_id": r["blocker_id"],
            "requirement": r["requirement"],
            "evidence_path": r.get("evidence_path"),
            "mission_categories": r.get("mission_categories"),
            "suggested_seed_action": (
                "Append narrow safe Claude implementation descriptor + paired "
                "Codex review descriptor; let worker pool dispatch."
            ),
        }
        for r in rows
        if r["classification"] == "TECHNICAL_AUTOMATABLE"
    ]


def build_final_shutdown_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    op_required = [r for r in rows if r["operator_required"]]
    event_waits = [r for r in rows if r["classification"] in ("EVENT_DEPENDENT", "POSITION_DEPENDENT")]
    tech_left = [r for r in rows if r["classification"] == "TECHNICAL_AUTOMATABLE"]
    codex_left = [r for r in rows if r["classification"] == "CODEX_REVIEW_REQUIRED"]
    paper_edge_proven = not any(r["blocker_id"] == "paper_edge_not_proven" for r in rows)
    checkpoint_resolved = not any(r["blocker_id"] == "checkpoint_promotion" for r in rows)
    risk_caps_set = not any("risk_caps" in r["blocker_id"] or "capital_recovery_gate" in r["blocker_id"] for r in rows)
    if rows:
        recommendation = "DO_NOT_SHUTDOWN_LEGACY"
        reason = "Blockers remain unresolved."
    else:
        recommendation = "REQUIRES_OPERATOR_FINAL_REVIEW_BEFORE_SAFE_TO_SHUTDOWN"
        reason = (
            "Zero blockers detected; SAFE_TO_SHUTDOWN may only be emitted after "
            "operator review and Codex verification confirms the empty state."
        )
    return {
        "schema_version": "v2_final_shutdown_recommendation_v1",
        "generated_utc": utc_iso(),
        "recommendation": recommendation,
        "reason": reason,
        "operator_required_blocker_count": len(op_required),
        "event_or_position_dependent_count": len(event_waits),
        "technical_automatable_count": len(tech_left),
        "codex_review_required_count": len(codex_left),
        "paper_edge_proven": paper_edge_proven,
        "checkpoint_resolved": checkpoint_resolved,
        "risk_caps_set": risk_caps_set,
        "live_ready": False,
        "shutdown_safe": False,
        "safety": dict(SAFETY_ENVELOPE),
    }


def write_outputs(
    rows: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    operator_queue: list[dict[str, Any]],
    event_watch: list[dict[str, Any]],
    tech_seed: list[dict[str, Any]],
    shutdown_rec: dict[str, Any],
    autoseed_result: dict[str, Any],
    ready: bool,
    blockers_for_gate: list[str],
) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    marker = READY_MARKER if ready else BLOCKED_MARKER
    matrix = {
        "schema_version": "v2_global_blocker_classification_matrix_v1",
        "generated_utc": utc_iso(),
        "go_no_go": marker,
        "ready": ready,
        "blocker_count": len(rows),
        "by_classification": {
            cls: [r["blocker_id"] for r in rows if r["classification"] == cls]
            for cls in (
                "TECHNICAL_AUTOMATABLE",
                "EVENT_DEPENDENT",
                "POSITION_DEPENDENT",
                "EXTERNAL_SOURCE_REQUIRED",
                "OPERATOR_DECISION_REQUIRED",
                "CODEX_REVIEW_REQUIRED",
                "ALREADY_REMEDIATED_AWAITING_FRESH_EVIDENCE",
                "NOT_REQUIRED_FOR_V2_PAPER_ONLY",
            )
        },
        "blockers": rows,
        "safety": dict(SAFETY_ENVELOPE),
        **SAFETY_ENVELOPE,
    }
    payloads_to_write = {
        "global_blocker_classification_matrix.json": matrix,
        "next_action_by_blocker.json": {
            "schema_version": "v2_next_action_by_blocker_v1",
            "generated_utc": utc_iso(),
            "actions": actions,
            "safety": dict(SAFETY_ENVELOPE),
        },
        "operator_decision_queue.json": {
            "schema_version": "v2_global_operator_decision_queue_v1",
            "generated_utc": utc_iso(),
            "items": operator_queue,
            "safety": dict(SAFETY_ENVELOPE),
        },
        "event_dependent_watchlist.json": {
            "schema_version": "v2_event_dependent_watchlist_v1",
            "generated_utc": utc_iso(),
            "items": event_watch,
            "safety": dict(SAFETY_ENVELOPE),
        },
        "technical_automatable_queue_seed.json": {
            "schema_version": "v2_technical_automatable_queue_seed_v1",
            "generated_utc": utc_iso(),
            "items": tech_seed,
            "autoseed_invoked": autoseed_result.get("invoked", False),
            "autoseed_result": autoseed_result,
            "safety": dict(SAFETY_ENVELOPE),
        },
        "final_shutdown_recommendation.json": shutdown_rec,
        "operator_dashboard_payload.json": {
            "schema_version": "v2_production_equivalence_final_blocker_classification_v1",
            "generated_utc": utc_iso(),
            "go_no_go": marker,
            "ready": ready,
            "gate_blockers": blockers_for_gate,
            "blocker_count": len(rows),
            "operator_required_blocker_count": len(operator_queue),
            "event_or_position_dependent_count": len(event_watch),
            "technical_automatable_count": len(tech_seed),
            "matrix": matrix,
            "actions": actions,
            "operator_decision_queue": operator_queue,
            "event_dependent_watchlist": event_watch,
            "technical_automatable_queue_seed": tech_seed,
            "final_shutdown_recommendation": shutdown_rec,
            "autoseed_result": autoseed_result,
            "safety": dict(SAFETY_ENVELOPE),
            **SAFETY_ENVELOPE,
        },
    }
    for name, body in payloads_to_write.items():
        text = json.dumps(body, indent=2, sort_keys=True) + "\n"
        (WORKLOG_DIR / name).write_text(text, encoding="utf-8")
        (PUBLIC_DIR / name).write_text(text, encoding="utf-8")
    (WORKLOG_DIR / "GO_NO_GO.md").write_text(marker + "\n", encoding="utf-8")


def maybe_autoseed(tech_seed: list[dict[str, Any]]) -> dict[str, Any]:
    """Invoke autoseed only if TECHNICAL_AUTOMATABLE rows exist."""
    if not tech_seed:
        return {
            "invoked": False,
            "reason": "no_technical_automatable_blockers_present",
            "generated_tasks": [],
        }
    try:
        import sys
        tools_dir = str(REPO_ROOT / "claude_worklog" / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        repo_dir = str(REPO_ROOT)
        if repo_dir not in sys.path:
            sys.path.insert(0, repo_dir)
        import v2_autonomous_mission_backlog_autoseed as autoseed  # type: ignore
        if hasattr(autoseed, "seed_tasks"):
            seed = autoseed.seed_tasks(target_current_queue=3, max_new_implementation_tasks=3)
            generated = seed.get("generated_tasks") or []
            duplicate_suppressed = seed.get("duplicate_suppressed") or []
            refused = seed.get("refused") or []
        else:
            seed = autoseed.run_once(max_new_tasks=3)
            generated = seed.get("generated_pairs") or []
            duplicate_suppressed = []
            refused = []
        return {
            "invoked": True,
            "reason": "technical_automatable_blockers_present",
            "generated_tasks": generated,
            "duplicate_suppressed": duplicate_suppressed,
            "refused": refused,
        }
    except Exception as exc:
        return {
            "invoked": False,
            "reason": f"autoseed_error:{type(exc).__name__}",
            "generated_tasks": [],
        }


def evaluate_ready_gate(
    rows: list[dict[str, Any]],
    shutdown_rec: dict[str, Any],
    autoseed_result: dict[str, Any],
) -> tuple[bool, list[str]]:
    """READY only if classification packet itself is internally consistent.

    Note: READY here means *the classification packet is valid and current*,
    NOT that the system itself is ready to shut down. The shutdown
    recommendation is a separate field.
    """
    blockers: list[str] = []
    if shutdown_rec.get("recommendation") not in (
        "DO_NOT_SHUTDOWN_LEGACY",
        "REQUIRES_OPERATOR_FINAL_REVIEW_BEFORE_SAFE_TO_SHUTDOWN",
    ):
        blockers.append("INVALID_SHUTDOWN_RECOMMENDATION_VALUE")
    # Rule 7: never emit SAFE_TO_SHUTDOWN unless every blocker is resolved
    if not rows and shutdown_rec.get("recommendation") == "SAFE_TO_SHUTDOWN":
        blockers.append("SAFE_TO_SHUTDOWN_REQUIRES_OPERATOR_AND_CODEX_VERIFICATION")
    # Rule 1: if TECHNICAL_AUTOMATABLE exist, autoseed must have been invoked.
    tech = [r for r in rows if r["classification"] == "TECHNICAL_AUTOMATABLE"]
    if tech and not autoseed_result.get("invoked", False):
        blockers.append("TECHNICAL_AUTOMATABLE_PRESENT_BUT_AUTOSEED_NOT_INVOKED")
    ready = not blockers
    return ready, blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payloads: dict[str, dict[str, Any]] = {}
    for name, rel in INPUTS.items():
        data = read_json(REPO_ROOT / rel)
        payloads[name] = data if isinstance(data, dict) else {}
    rows = classify_blockers(payloads)
    actions = build_next_action(rows)
    operator_queue = build_operator_decision_queue(rows)
    event_watch = build_event_dependent_watchlist(rows)
    tech_seed = build_technical_automatable_queue_seed(rows)
    autoseed_result = maybe_autoseed(tech_seed)
    shutdown_rec = build_final_shutdown_recommendation(rows)
    ready, gate_blockers = evaluate_ready_gate(rows, shutdown_rec, autoseed_result)
    write_outputs(
        rows=rows,
        actions=actions,
        operator_queue=operator_queue,
        event_watch=event_watch,
        tech_seed=tech_seed,
        shutdown_rec=shutdown_rec,
        autoseed_result=autoseed_result,
        ready=ready,
        blockers_for_gate=gate_blockers,
    )
    summary = {
        "go_no_go": READY_MARKER if ready else BLOCKED_MARKER,
        "blocker_count": len(rows),
        "operator_decision_queue_count": len(operator_queue),
        "event_dependent_watchlist_count": len(event_watch),
        "technical_automatable_queue_seed_count": len(tech_seed),
        "autoseed_invoked": autoseed_result.get("invoked", False),
        "shutdown_recommendation": shutdown_rec.get("recommendation"),
        "gate_blockers": gate_blockers,
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
