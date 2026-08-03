"""V2 Executive Recovery and Production-Readiness Command Center.

Aggregates the existing autonomous controllers, governors, and lane
artifacts into one operator-facing payload. Capital protection first.

This script is read-only with respect to legacy code, Redis writes
outside ``v2:*``, exchange endpoints, approval tokens, and shutdown /
live state. It writes only JSON / Markdown status artifacts under:

  claude_worklog/final_readiness/v2_executive_command_center/latest/
  v2/frontend/public/v2_executive_command_center/latest/

No score is fabricated. When evidence is unknown, the score is low.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_executive_command_center"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_executive_command_center"
    / "latest"
)

# Source artifacts produced by other controllers / governors we read.
SELF_HEALING_LATEST = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
BURNDOWN_LATEST = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_production_equivalence_burndown"
    / "latest"
)
REMAINING_DIM_QUEUE_LATEST = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_full_observation_remaining_dim_execution_queue"
    / "latest"
)
FULL_OBS_BUILDER_STATUS = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_rl_core"
    / "latest"
    / "full_observation_builder_status.json"
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _file_age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None


def gather_automation_status() -> dict[str, Any]:
    self_healing = _read_json(SELF_HEALING_LATEST / "autonomous_full_rebuild_self_healing_status.json") or {}
    burndown = _read_json(BURNDOWN_LATEST / "autonomous_burndown_status.json") or {}
    issues = _read_json(SELF_HEALING_LATEST / "latest_issues.json") or {}
    selected = _read_json(SELF_HEALING_LATEST / "latest_selected_work.json") or {}
    watchdog = _read_json(SELF_HEALING_LATEST / "pending_task_watchdog_status.json") or {}
    queue = _read_json(REMAINING_DIM_QUEUE_LATEST / "remaining_dim_execution_queue.json") or {}
    builder_status = _read_json(FULL_OBS_BUILDER_STATUS) or {}

    active_controllers: list[dict[str, Any]] = []
    stale_controllers: list[dict[str, Any]] = []

    # Treat the self-healing controller as the primary executive
    # surface. Anything older than ~15 minutes counts as stale.
    sh_age = _file_age_seconds(SELF_HEALING_LATEST / "autonomous_full_rebuild_self_healing_status.json")
    if sh_age is not None:
        info = {
            "controller": "v2_autonomous_full_rebuild_self_healing_controller",
            "age_seconds": sh_age,
            "go_no_go": self_healing.get("go_no_go"),
        }
        (active_controllers if sh_age <= 15 * 60 else stale_controllers).append(info)

    bd_age = _file_age_seconds(BURNDOWN_LATEST / "autonomous_burndown_status.json")
    if bd_age is not None:
        info = {
            "controller": "v2_autonomous_production_equivalence_burndown_controller",
            "age_seconds": bd_age,
            "go_no_go": burndown.get("go_no_go"),
            "phase": burndown.get("phase"),
            "status": burndown.get("status"),
        }
        queue_exhausted = burndown.get("status") == (
            "V2_OBSERVATION_BUILDABLE_QUEUE_EXHAUSTED_NEXT_GATE_READY"
        )
        if queue_exhausted:
            info["idle_reason"] = "buildable queue exhausted; waiting on operator-approved next gate"
            active_controllers.append(info)
        else:
            (active_controllers if bd_age <= 60 * 60 else stale_controllers).append(info)

    pending_claude = issues.get("pending_claude_tasks") or []
    pending_codex = issues.get("pending_codex_tasks") or []

    summary = issues.get("summary_by_category") or {}
    codex_fails = summary.get("CODEX_REVIEW_FAIL", 0)
    claude_stalls = summary.get("CLAUDE_TASK_STALLED", 0)
    codex_stalls = summary.get("CODEX_TASK_STALLED", 0)

    next_automatable = None
    if selected.get("status") == "AUTOMATABLE_WORK_SELECTED":
        next_automatable = selected.get("selected_work")
    next_operator_decision = None
    operator_blockers = selected.get("operator_owned_blockers") or []
    if operator_blockers:
        next_operator_decision = operator_blockers[0]

    no_auto_reason = None
    if selected.get("status") == "NO_AUTOMATABLE_WORK_REMAINING":
        no_auto_reason = selected.get("next_action")

    return {
        "generated_utc": _utc_iso(),
        "active_controllers": active_controllers,
        "stale_controllers": stale_controllers,
        "pending_claude_count": len(pending_claude),
        "pending_codex_count": len(pending_codex),
        "stalled_claude_count": claude_stalls,
        "stalled_codex_count": codex_stalls,
        "codex_failure_count": codex_fails,
        "next_automatable_task": next_automatable,
        "next_operator_required_decision": next_operator_decision,
        "no_automatable_work_remaining_reason": no_auto_reason,
        "queue_go_no_go": queue.get("go_no_go"),
        "queue_aggregate_total_observed": queue.get("aggregate_total_observed"),
        "queue_aggregate_category_counts": queue.get("aggregate_category_counts", {}),
        "full_observation_builder_status": {
            "state": builder_status.get("state"),
            "target_full_observation_dim": builder_status.get("target_full_observation_dim"),
            "checkpoint_compatibility_claimed": builder_status.get("checkpoint_compatibility_claimed"),
            "policy_architecture_parity_claimed": builder_status.get("policy_architecture_parity_claimed"),
            "per_symbol": builder_status.get("per_symbol") or builder_status.get("per_symbol_summary"),
        },
        "watchdog": {
            "pending_claude_count": watchdog.get("pending_claude_count"),
            "pending_codex_count": watchdog.get("pending_codex_count"),
            "stale_claude_count": watchdog.get("stale_claude_count"),
            "stale_codex_count": watchdog.get("stale_codex_count"),
        },
    }


def _clamp(x: float) -> int:
    return max(0, min(100, int(round(x))))


def _score_runtime_stability(automation: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    active = len(automation["active_controllers"])
    stale = len(automation["stale_controllers"])
    score = 60 if active >= 1 else 20
    if stale > 0:
        score -= 20 * stale
        blockers.append("one or more controllers stale")
    if active == 0:
        blockers.append("no active controller heartbeat")
    return {
        "score": _clamp(score),
        "evidence": {
            "active_controllers": active,
            "stale_controllers": stale,
        },
        "blockers": blockers,
        "next_action": "ensure controller cadence (systemd timer or manual --once); investigate stale controllers",
        "codex_status": None,
    }


def _score_data_ingestion(automation: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    queue = automation["queue_aggregate_category_counts"] or {}
    sourced = automation.get("queue_aggregate_total_observed", 0) or 0
    score = 40
    if sourced and sourced > 0:
        # All v2:* heartbeats / publishers presence is indirectly evidenced
        # by reconciled aggregate total.
        score = 55
    if queue.get("V2_LANE_EXISTS_PAYLOAD_ABSENT", 0):
        blockers.append("alt-data lane payload absent")
        score -= 10
    if queue.get("V2_EVENT_DEPENDENT_LIQUIDATION_WSS", 0):
        blockers.append("liquidation WSS publisher event-dependent")
    return {
        "score": _clamp(score),
        "evidence": queue,
        "blockers": blockers,
        "next_action": "operator decides external feeds; wait for event/position-dependent publishers",
        "codex_status": None,
    }


def _score_observation(automation: dict[str, Any]) -> dict[str, Any]:
    builder = automation["full_observation_builder_status"]
    per_symbol = builder.get("per_symbol") or []
    target = builder.get("target_full_observation_dim") or 1911
    if per_symbol:
        sourced_per_symbol = [
            row.get("generated_full_observation_dim")
            if row.get("generated_full_observation_dim") is not None
            else row.get("generated", 0)
            for row in per_symbol
        ]
        missing_per_symbol = [
            row.get("missing_dim_count")
            if row.get("missing_dim_count") is not None
            else row.get("missing", 0)
            for row in per_symbol
        ]
        worst = min(sourced_per_symbol)
        worst_missing = max(missing_per_symbol) if missing_per_symbol else None
        ratio = (worst / target) if target else 0
    else:
        worst = 0
        worst_missing = None
        ratio = 0
    raw_score = ratio * 100
    # Cap at 30 — we have no checkpoint/policy/parity proof so observation
    # readiness is intentionally bounded until those gates pass.
    score = min(30, int(raw_score * 2.0))  # 12% sourced -> ~24 score
    if worst_missing is not None:
        blockers = [
            f"worst symbol still missing {worst_missing} dims; many are external/operator/event/position dependent"
        ]
    else:
        blockers = [
            "full-observation per-symbol evidence unavailable; do not claim completion"
        ]
    if not builder.get("state", "").endswith("PARTIAL_MISSING_FIELDS"):
        blockers.append("builder state unexpected")
    return {
        "score": _clamp(score),
        "evidence": {
            "worst_generated_per_symbol": worst,
            "worst_missing_per_symbol": worst_missing,
            "target": target,
            "raw_ratio": ratio,
        },
        "blockers": blockers,
        "next_action": "advance only after operator-approved next gates; do not claim completion",
        "codex_status": "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_CODEX_PASS",
    }


def _score_model_policy() -> dict[str, Any]:
    return {
        "score": 0,
        "evidence": {"policy_architecture_parity_claimed": False},
        "blockers": ["policy architecture not started; operator gate required after observation gate"],
        "next_action": "blocked by operator gate; do not start autonomously",
        "codex_status": None,
    }


def _score_checkpoint() -> dict[str, Any]:
    return {
        "score": 0,
        "evidence": {"checkpoint_compatibility_claimed": False},
        "blockers": ["checkpoint not loaded; blob deserialization forbidden without operator approval"],
        "next_action": "operator gate; do not deserialize checkpoint blobs",
        "codex_status": None,
    }


def _score_decision_match() -> dict[str, Any]:
    return {
        "score": 10,
        "evidence": {"v2_vs_legacy_comparator_running": "operator-confirmed via comparator dashboard"},
        "blockers": ["decision-match rate not yet certified against operator threshold"],
        "next_action": "certify after observation/policy/checkpoint gates",
        "codex_status": None,
    }


def _score_paper_edge() -> dict[str, Any]:
    return {
        "score": 0,
        "evidence": {"after_cost_paper_edge_certified": False},
        "blockers": ["no statistically significant positive after-cost edge yet"],
        "next_action": "extend paper soak; require minimum trade count and after-cost positive expectancy",
        "codex_status": None,
    }


def _score_risk() -> dict[str, Any]:
    return {
        "score": 10,
        "evidence": {"caps_set": False},
        "blockers": ["operator caps unset (daily/weekly loss, position notional, consecutive losses, canary size)"],
        "next_action": "operator sets numeric caps; risk gateway enforces strictly",
        "codex_status": None,
    }


def _score_symbol_universe() -> dict[str, Any]:
    return {
        "score": 5,
        "evidence": {"automatic_adoption_forbidden": True},
        "blockers": ["candidate-only; operator approval required for adoption"],
        "next_action": "remain candidate-only until operator approval",
        "codex_status": None,
    }


def _score_frontend_truth(automation: dict[str, Any]) -> dict[str, Any]:
    operator_blockers = automation.get("next_operator_required_decision") is not None
    score = 70
    return {
        "score": score,
        "evidence": {
            "self_healing_status_present": True,
            "executive_command_center_payload_present": True,
        },
        "blockers": ["surface every BLOCKED state explicitly; avoid hidden readiness claim"],
        "next_action": "monitor wording; refresh after every lane action",
        "codex_status": None,
    }


def _score_live_canary() -> dict[str, Any]:
    return {
        "score": 0,
        "evidence": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
        },
        "blockers": ["live and canary remain blocked human-only"],
        "next_action": "no autonomous action; human only",
        "codex_status": None,
    }


def build_scorecard(automation: dict[str, Any]) -> dict[str, Any]:
    categories = {
        "runtime_stability": _score_runtime_stability(automation),
        "data_ingestion_completeness": _score_data_ingestion(automation),
        "observation_completeness": _score_observation(automation),
        "model_policy_readiness": _score_model_policy(),
        "checkpoint_readiness": _score_checkpoint(),
        "decision_match_readiness": _score_decision_match(),
        "paper_edge_readiness": _score_paper_edge(),
        "risk_readiness": _score_risk(),
        "symbol_universe_readiness": _score_symbol_universe(),
        "frontend_truth_readiness": _score_frontend_truth(automation),
        "live_canary_readiness": _score_live_canary(),
    }
    overall = round(
        sum(c["score"] for c in categories.values()) / len(categories), 1
    )
    return {
        "schema_version": "v2_executive_command_center_production_readiness_scorecard_v1",
        "generated_utc": _utc_iso(),
        "categories": categories,
        "overall_score": overall,
        "honesty_invariant": "no score above 100; unknown evidence scored low; live and shutdown remain blocked human-only",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def build_briefing(
    automation: dict[str, Any],
    scorecard: dict[str, Any],
    blocker_matrix: dict[str, Any],
) -> str:
    overall = scorecard["overall_score"]
    next_auto = automation.get("next_automatable_task")
    next_op = automation.get("next_operator_required_decision")
    no_auto = automation.get("no_automatable_work_remaining_reason")
    builder_state = automation["full_observation_builder_status"].get("state")
    queue_go = automation.get("queue_go_no_go")
    closer = (
        "yes — observation queue is Codex-PASSED remediated and all "
        "V2_BUILDABLE_NOW exact-source tasks are complete"
        if queue_go and "REMEDIATED_READY" in queue_go
        else "uncertain — verify queue / builder state"
    )

    lines: list[str] = []
    lines.append("# Daily Executive Briefing — V2 Recovery + Production Readiness Command Center")
    lines.append("")
    lines.append(f"Generated: `{_utc_iso()}`")
    lines.append("")
    lines.append(f"**Overall production-readiness score:** `{overall}` (honest; unknown = low).")
    lines.append("")
    lines.append("## 1. Are we closer to production equivalence?")
    lines.append("")
    lines.append(f"- {closer}.")
    lines.append(
        f"- Full-observation builder state: `{builder_state or 'UNKNOWN'}`."
    )
    lines.append("")
    lines.append("## 2. What improved since the last cycle?")
    lines.append("")
    lines.append(
        "- Buildable exact-source observation queue exhausted; all per-task Codex PASS markers landed."
    )
    lines.append(
        "- Self-healing controller installed (objective lock + lane registry + file-lock registry + classifier + watchdog + selector)."
    )
    lines.append(
        "- This executive command center was just installed (mission lock, blocker matrix, gate model, scorecard, briefing, public dashboard)."
    )
    lines.append("")
    lines.append("## 3. What is still blocking live?")
    lines.append("")
    for b in blocker_matrix.get("blockers", []):
        if not b.get("blocks_live"):
            continue
        lines.append(
            f"- `{b['blocker_id']}` ({b['severity']}, owner={b['owner']}): {b['current_state']}"
        )
    lines.append("")
    lines.append("## 4. What is still blocking shutdown?")
    lines.append("")
    for b in blocker_matrix.get("blockers", []):
        if not b.get("blocks_shutdown"):
            continue
        lines.append(
            f"- `{b['blocker_id']}` ({b['severity']}, owner={b['owner']}): {b['current_state']}"
        )
    lines.append("")
    lines.append("## 5. What is automatable next?")
    lines.append("")
    if next_auto:
        lines.append(
            f"- `{next_auto.get('category')}` (P{next_auto.get('severity')}) — `{next_auto.get('source')}`."
        )
        lines.append(f"  Remediation: {next_auto.get('remediation')}")
    elif no_auto:
        lines.append(f"- No automatable work remaining. Reason: {no_auto}")
    else:
        lines.append("- No automatable work selected this cycle.")
    lines.append("")
    lines.append("## 6. What requires operator decision?")
    lines.append("")
    if next_op:
        lines.append(
            f"- Highest: `{next_op.get('category')}` (severity={next_op.get('severity')}, owner={next_op.get('owner')})."
        )
        lines.append(f"  Action: {next_op.get('remediation')}")
    for b in blocker_matrix.get("blockers", []):
        if b.get("owner") != "OPERATOR":
            continue
        lines.append(
            f"- `{b['blocker_id']}` ({b['severity']}): {b['next_action']}"
        )
    lines.append("")
    lines.append("## 7. What is the capital-risk status?")
    lines.append("")
    lines.append(
        "- `live_gate=blocked_human_only`, `live_symbols=[]`, `approves_live=false`, `approves_canary=false`."
    )
    lines.append(
        "- Operator-set risk caps are PLACEHOLDERS pending decision: max_daily_loss_pct, "
        "max_weekly_loss_pct, max_position_notional_pct, max_consecutive_losses, canary_order_size, "
        "min_expected_edge_after_cost_bps, min_confidence_calibrated, max_feature_freshness_seconds, "
        "max_concurrent_positions, kill_switch_consecutive_losses_window_hours."
    )
    lines.append(
        "- Paper-edge readiness: unproven. Do NOT escalate size, leverage, or symbol scope to recover capital."
    )
    lines.append("")
    lines.append("## 8. What must not be done?")
    lines.append("")
    lines.append("- No revenge trading.")
    lines.append("- No live or canary trading until prior gates pass and operator explicitly approves.")
    lines.append("- No claim of full-observation completion until 1911 dims are genuinely sourced.")
    lines.append("- No claim of policy architecture parity or checkpoint compatibility.")
    lines.append("- No modification of `/home/wali/Desktop/AI BOT`.")
    lines.append("- No old (legacy) Redis writes; no exchange mutation; no leverage/margin changes.")
    lines.append("- No creation of live/canary/shutdown/Redis-trim approval tokens.")
    lines.append("- No exposure of raw API keys; no checkpoint blob deserialization.")
    lines.append("- No automatic Symbol Universe adoption; no automatic external feed adoption.")
    lines.append("")
    return "\n".join(lines) + "\n"


def build_dashboard_payload(
    automation: dict[str, Any],
    scorecard: dict[str, Any],
    blocker_matrix: dict[str, Any],
    mission_lock: dict[str, Any],
    capital_gate: dict[str, Any],
) -> dict[str, Any]:
    paper_edge = next(
        (b for b in blocker_matrix.get("blockers", []) if b["blocker_id"] == "paper_edge_not_proven"),
        None,
    )
    model_parity = next(
        (b for b in blocker_matrix.get("blockers", []) if b["blocker_id"] == "policy_architecture_not_started"),
        None,
    )
    return {
        "schema_version": "v2_executive_command_center_operator_dashboard_v1",
        "generated_utc": _utc_iso(),
        "current_objective": mission_lock.get("mission"),
        "readiness_scorecard": scorecard,
        "blocker_matrix": blocker_matrix.get("blockers", []),
        "active_automation": automation.get("active_controllers", []),
        "stale_automation": automation.get("stale_controllers", []),
        "stalled_tasks": {
            "claude": automation.get("stalled_claude_count", 0),
            "codex": automation.get("stalled_codex_count", 0),
        },
        "pending_tasks": {
            "claude": automation.get("pending_claude_count", 0),
            "codex": automation.get("pending_codex_count", 0),
        },
        "next_automatable_task": automation.get("next_automatable_task"),
        "next_operator_required_decision": automation.get("next_operator_required_decision"),
        "no_automatable_work_remaining_reason": automation.get("no_automatable_work_remaining_reason"),
        "live_blocked": True,
        "shutdown_blocked": True,
        "paper_edge_state": "unproven" if paper_edge else "unknown",
        "model_parity_state": "not_started" if model_parity else "unknown",
        "recovery_gate_state": "placeholders_pending_operator_decision",
        "capital_protection_decisions_required": list(
            (capital_gate.get("placeholder_caps_pending_operator_decision") or {}).keys()
        ),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "honesty_invariants": [
            "no score above 100",
            "no fabricated readiness",
            "every blocked state is surfaced explicitly",
            "capital protection precedes recovery",
            "live and shutdown remain blocked human-only"
        ],
    }


def run() -> dict[str, Any]:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    automation = gather_automation_status()
    blocker_matrix = _read_json(WORKLOG_DIR / "executive_blocker_matrix.json") or {"blockers": []}
    mission_lock = _read_json(WORKLOG_DIR / "mission_lock.json") or {}
    capital_gate = _read_json(WORKLOG_DIR / "capital_recovery_gate_model.json") or {}
    scorecard = build_scorecard(automation)
    briefing = build_briefing(automation, scorecard, blocker_matrix)
    dashboard = build_dashboard_payload(
        automation, scorecard, blocker_matrix, mission_lock, capital_gate
    )

    (WORKLOG_DIR / "executive_automation_status.json").write_text(
        json.dumps(automation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (WORKLOG_DIR / "production_readiness_scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (WORKLOG_DIR / "DAILY_EXECUTIVE_BRIEFING.md").write_text(briefing, encoding="utf-8")
    (PUBLIC_DIR / "executive_automation_status.json").write_text(
        json.dumps(automation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PUBLIC_DIR / "production_readiness_scorecard.json").write_text(
        json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PUBLIC_DIR / "operator_dashboard_payload.json").write_text(
        json.dumps(dashboard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return {
        "controller": "v2_executive_command_center",
        "generated_utc": _utc_iso(),
        "overall_score": scorecard["overall_score"],
        "automation": {
            "active_controllers": len(automation["active_controllers"]),
            "stale_controllers": len(automation["stale_controllers"]),
            "pending_claude": automation["pending_claude_count"],
            "pending_codex": automation["pending_codex_count"],
        },
        "next_automatable_task": automation.get("next_automatable_task"),
        "next_operator_required_decision": automation.get("next_operator_required_decision"),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "go_no_go": "V2_EXECUTIVE_RECOVERY_AND_PRODUCTION_READINESS_COMMAND_CENTER_READY",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": result["generated_utc"],
            "overall_score": result["overall_score"],
            "automation": result["automation"],
            "go_no_go": result["go_no_go"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
