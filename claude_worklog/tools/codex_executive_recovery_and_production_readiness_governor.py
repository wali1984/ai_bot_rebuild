"""Codex executive recovery and production-readiness governor.

Reviews the executive command center and active automation against the
real objective: production-equivalent V2 with proven edge and no false
live/shutdown readiness.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
EXEC_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_executive_command_center"
    / "latest"
)
OUT_DIR = EXEC_DIR / "codex_governor"
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_executive_command_center"
    / "latest"
    / "codex_governor"
)
SELF_HEALING_CODEX_STATUS = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
    / "codex_governor"
    / "codex_full_rebuild_self_healing_status.json"
)
FULL_OBS_STATUS = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_rl_core"
    / "latest"
    / "full_observation_builder_status.json"
)

READY = "CODEX_EXECUTIVE_RECOVERY_AND_PRODUCTION_READINESS_GOVERNOR_READY"
BLOCKED = "CODEX_EXECUTIVE_RECOVERY_AND_PRODUCTION_READINESS_GOVERNOR_BLOCKED"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None


def _run_tool(script: str, *args: str) -> dict[str, Any]:
    cmd = [sys.executable, str(TOOLS_DIR / script), *args]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "command": " ".join(cmd),
            "returncode": res.returncode,
            "stdout_tail": (res.stdout or "")[-2000:],
            "stderr_tail": (res.stderr or "")[-2000:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"command": " ".join(cmd), "returncode": 1, "error": str(exc)}


def _scorecard_inflated(scorecard: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    overall = scorecard.get("overall_score")
    if overall is None or overall > 35:
        blockers.append("PRODUCTION_READINESS_SCORECARD_INFLATED_OR_MISSING")
    categories = scorecard.get("categories") or {}
    for name in (
        "live_canary_readiness",
        "model_policy_readiness",
        "checkpoint_readiness",
        "paper_edge_readiness",
    ):
        if (categories.get(name) or {}).get("score", 0) > 0:
            blockers.append(f"{name.upper()}_SCORE_INFLATED")
    return blockers


def _blocker_matrix_truth(blocker_matrix: dict[str, Any]) -> dict[str, Any]:
    blockers = blocker_matrix.get("blockers") or []
    ids = {b.get("blocker_id") for b in blockers}
    required = {
        "full_observation_partial_1687_missing",
        "policy_architecture_not_started",
        "checkpoint_model_not_loaded",
        "paper_edge_not_proven",
        "risk_gateway_caps_unset",
        "live_canary_human_only",
    }
    missing_required = sorted(required - ids)
    hidden = [b.get("blocker_id") for b in blockers if not b.get("frontend_visible")]
    live_unblocked = [
        b.get("blocker_id") for b in blockers
        if b.get("category") in ("live_canary", "checkpoint_model", "policy_architecture")
        and not b.get("blocks_live")
    ]
    return {
        "required_blockers_present": not missing_required,
        "missing_required_blockers": missing_required,
        "all_blockers_frontend_visible": not hidden,
        "hidden_blockers": hidden,
        "critical_live_blockers_block_live": not live_unblocked,
        "critical_live_blockers_not_blocking_live": live_unblocked,
    }


def _capital_gate_safe(capital_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_gate": capital_gate.get("live_gate"),
        "live_symbols": capital_gate.get("live_symbols"),
        "approves_live": capital_gate.get("approves_live"),
        "approves_canary": capital_gate.get("approves_canary"),
        "approves_legacy_shutdown": capital_gate.get("approves_legacy_shutdown"),
        "approves_redis_trim": capital_gate.get("approves_redis_trim"),
        "placeholder_caps_present": bool(capital_gate.get("placeholder_caps_pending_operator_decision")),
        "safe": (
            capital_gate.get("live_gate") == "blocked_human_only"
            and capital_gate.get("live_symbols") == []
            and capital_gate.get("approves_live") is False
            and capital_gate.get("approves_canary") is False
            and capital_gate.get("approves_legacy_shutdown") is False
            and capital_gate.get("approves_redis_trim") is False
        ),
    }


def run() -> dict[str, Any]:
    tool_runs = [
        _run_tool("codex_full_rebuild_self_healing_review_and_takeover_governor.py"),
        _run_tool("v2_executive_command_center.py", "--json"),
    ]
    mission = _read_json(EXEC_DIR / "mission_lock.json") or {}
    blocker_matrix = _read_json(EXEC_DIR / "executive_blocker_matrix.json") or {}
    scorecard = _read_json(EXEC_DIR / "production_readiness_scorecard.json") or {}
    capital_gate = _read_json(EXEC_DIR / "capital_recovery_gate_model.json") or {}
    automation = _read_json(EXEC_DIR / "executive_automation_status.json") or {}
    dashboard = _read_json(REPO_ROOT / "v2/frontend/public/v2_executive_command_center/latest/operator_dashboard_payload.json") or {}
    self_healing = _read_json(SELF_HEALING_CODEX_STATUS) or {}
    full_obs = _read_json(FULL_OBS_STATUS) or {}

    matrix = _blocker_matrix_truth(blocker_matrix)
    capital = _capital_gate_safe(capital_gate)
    fail_blockers: list[str] = []
    if not mission:
        fail_blockers.append("MISSION_LOCK_MISSING")
    if not matrix["required_blockers_present"]:
        fail_blockers.append("BLOCKER_MATRIX_MISSING_REQUIRED_BLOCKERS")
    if not matrix["all_blockers_frontend_visible"]:
        fail_blockers.append("BLOCKER_MATRIX_HIDES_BLOCKERS")
    if not matrix["critical_live_blockers_block_live"]:
        fail_blockers.append("CRITICAL_LIVE_BLOCKER_NOT_BLOCKING_LIVE")
    fail_blockers.extend(_scorecard_inflated(scorecard))
    if not capital["safe"]:
        fail_blockers.append("CAPITAL_RECOVERY_GATE_APPROVAL_DRIFT")
    if self_healing.get("go_no_go") != "CODEX_FULL_REBUILD_SELF_HEALING_REVIEW_AND_TAKEOVER_GOVERNOR_READY":
        fail_blockers.append("SELF_HEALING_CODEX_GOVERNOR_NOT_READY")
    if full_obs.get("state") == "FULL_OBSERVATION_BUILDER_COMPLETE":
        # This should only pass after 1911 genuine dims per symbol; the
        # current lane is not there.
        fail_blockers.append("FULL_OBSERVATION_COMPLETE_CLAIM_REQUIRES_REVIEW")
    if full_obs.get("checkpoint_compatibility_claimed"):
        fail_blockers.append("CHECKPOINT_COMPATIBILITY_CLAIMED_PREMATURELY")
    if full_obs.get("policy_architecture_parity_claimed"):
        fail_blockers.append("POLICY_ARCHITECTURE_PARITY_CLAIMED_PREMATURELY")

    next_auto = automation.get("next_automatable_task")
    ui_only_allowed = bool(
        isinstance(next_auto, dict)
        and next_auto.get("category") == "CODEX_REVIEW_FAIL"
        and "v2_8h_war_room" in str(next_auto.get("source") or "")
    )
    if isinstance(next_auto, dict):
        source = str(next_auto.get("source") or "").lower()
        if any(token in source for token in ("live_canary", "shutdown", "one_order", "approval", "redis_trim")):
            fail_blockers.append("EXECUTIVE_SELECTED_LIVE_SHUTDOWN_OR_APPROVAL_WORK")
        if "policy" in source and full_obs.get("state") != "FULL_OBSERVATION_BUILDER_COMPLETE":
            fail_blockers.append("EXECUTIVE_SELECTED_POLICY_BEFORE_OBSERVATION_GATE")
        if "checkpoint" in source and not full_obs.get("checkpoint_compatibility_claimed"):
            fail_blockers.append("EXECUTIVE_SELECTED_CHECKPOINT_BEFORE_ARTIFACT_GATE")

    dashboard_truth = {
        "exists": bool(dashboard),
        "age_seconds": _age_seconds(REPO_ROOT / "v2/frontend/public/v2_executive_command_center/latest/operator_dashboard_payload.json"),
        "live_blocked": dashboard.get("live_blocked") is True,
        "shutdown_blocked": dashboard.get("shutdown_blocked") is True,
        "approves_live": dashboard.get("approves_live"),
        "approves_canary": dashboard.get("approves_canary"),
        "approves_legacy_shutdown": dashboard.get("approves_legacy_shutdown"),
        "live_gate": dashboard.get("live_gate"),
        "live_symbols": dashboard.get("live_symbols"),
    }
    if not dashboard_truth["exists"] or not dashboard_truth["live_blocked"] or not dashboard_truth["shutdown_blocked"]:
        fail_blockers.append("FRONTEND_EXECUTIVE_PAYLOAD_HIDES_BLOCKERS")

    go = READY if not fail_blockers else BLOCKED
    status = {
        "schema_version": "codex_executive_recovery_and_production_readiness_governor_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": go,
        "fail_blockers": fail_blockers,
        "tool_runs": tool_runs,
        "executive_command_center": {
            "exists": all((mission, blocker_matrix, scorecard, capital_gate, automation)),
            "mission_lock_present": bool(mission),
            "blocker_matrix": matrix,
            "scorecard": {
                "overall_score": scorecard.get("overall_score"),
                "not_inflated": not _scorecard_inflated(scorecard),
            },
            "capital_gate": capital,
            "automation": {
                "pending_claude_count": automation.get("pending_claude_count"),
                "pending_codex_count": automation.get("pending_codex_count"),
                "stalled_claude_count": automation.get("stalled_claude_count"),
                "stalled_codex_count": automation.get("stalled_codex_count"),
                "next_automatable_task": next_auto,
                "ui_only_work_allowed_because_frontend_truth_blocker": ui_only_allowed,
            },
            "dashboard_truth": dashboard_truth,
        },
        "full_observation": {
            "state": full_obs.get("state"),
            "target_full_observation_dim": full_obs.get("target_full_observation_dim"),
            "checkpoint_compatibility_claimed": full_obs.get("checkpoint_compatibility_claimed"),
            "policy_architecture_parity_claimed": full_obs.get("policy_architecture_parity_claimed"),
            "zero_filled_field_count": full_obs.get("zero_filled_field_count"),
            "no_zero_fill_for_unknown_fields": full_obs.get("no_zero_fill_for_unknown_fields"),
        },
        "safety": {
            "did_not_touch_legacy": True,
            "did_not_write_redis": True,
            "did_not_call_exchange": True,
            "did_not_create_approvals": True,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
    }
    return status


def _write_status(status: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUT_DIR / "codex_executive_governor_status.json", status)
    _write_json(PUBLIC_DIR / "codex_executive_governor_status.json", status)
    (OUT_DIR / "CODEX_GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    (PUBLIC_DIR / "CODEX_GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    lines = [
        "# Codex Executive Recovery And Production-Readiness Governor",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
        (
            "Codex executive recovery and production-readiness governor is READY."
            if status["go_no_go"] == READY
            else "Codex executive recovery and production-readiness governor is BLOCKED."
        ),
        "",
        "This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.",
        "",
        "## Executive Truth",
        "",
        f"- Overall score: `{status['executive_command_center']['scorecard']['overall_score']}`",
        f"- Scorecard not inflated: `{status['executive_command_center']['scorecard']['not_inflated']}`",
        f"- Mission lock present: `{status['executive_command_center']['mission_lock_present']}`",
        f"- Dashboard live/shutdown blocked: `{status['executive_command_center']['dashboard_truth']['live_blocked']}` / `{status['executive_command_center']['dashboard_truth']['shutdown_blocked']}`",
        "",
        "## Full Observation",
        "",
        f"- State: `{status['full_observation']['state']}`",
        f"- checkpoint_compatibility_claimed: `{status['full_observation']['checkpoint_compatibility_claimed']}`",
        f"- policy_architecture_parity_claimed: `{status['full_observation']['policy_architecture_parity_claimed']}`",
        "",
        "## Fail Blockers",
        "",
    ]
    if status["fail_blockers"]:
        lines.extend(f"- `{b}`" for b in status["fail_blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Final Decision", "", f"`{status['go_no_go']}`", ""])
    (OUT_DIR / "CODEX_STATUS.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    status = run()
    _write_status(status)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "go_no_go": status["go_no_go"],
            "fail_blockers": status["fail_blockers"],
            "overall_score": status["executive_command_center"]["scorecard"]["overall_score"],
        }, indent=2, sort_keys=True))
    return 0 if status["go_no_go"] == READY else 1


if __name__ == "__main__":
    sys.exit(main())
