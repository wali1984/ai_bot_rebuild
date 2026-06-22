"""V2 continuous legacy-log -> rebuild remediation loop (read-only legacy)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from v2.backend.app.services.legacy_log_intelligence import (  # noqa: E402
    discover_legacy_sources, enrich_comparison, observe_once,
    remediation_hints_from_summary,
)

WORKLOG_DIR = (
    REPO
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation"
)
PUBLIC_STATUS = (
    REPO
    / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation_status.json"
)
WORKLOG_STATUS = WORKLOG_DIR / "continuous_remediation_status.json"
GAP_MATRIX_WORKLOG = WORKLOG_DIR / "legacy_log_v2_gap_matrix.json"
GAP_MATRIX_PUBLIC = (
    REPO
    / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/legacy_log_v2_gap_matrix.json"
)
TASKS_DIR = REPO / "claude_worklog/agent_supervisor/tasks"
COMPARATOR_PATH = (
    REPO
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json"
)
SOAK_STATUS_PATH = (
    REPO
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/soak_status.json"
)
SOAK_CODEX_STATUS_PATH = (
    REPO
    / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/codex_governor/codex_15m_status.json"
)


GO_READY = "V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY"
GO_BLOCKED = "V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_BLOCKED"


def _ps_running(needle: str) -> bool:
    try:
        proc = subprocess.run(
            ["pgrep", "-f", needle], capture_output=True, text=True, timeout=5
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        return False


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write_json(p: Path, payload: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# Map mismatch cause -> narrow Claude fix gap id.
_CAUSE_TO_GAP_ID = {
    "missing_v2_prediction": "v2_prediction_missing_for_symbol",
    "missing_legacy_log_evidence": "legacy_log_missing_action_for_symbol",
    "V2_hold_due_strict_gate": "trainer_missing_checkpoint_weight_shape_contract",
    "checkpoint_weight_missing": "trainer_missing_checkpoint_weight_shape_contract",
    "feature_freshness_mismatch": "feature_pipeline_freshness_mismatch_for_symbol",
    "v2_paper_fill_gate_blocked": "paper_fill_gate_block_reason_passthrough_missing",
    "orchestrator_deconflict_mismatch": "orchestrator_missing_deconflict_rule_from_legacy_log",
}

# Gaps that require Codex review before auto-fix (no auto-implementation by this loop).
_AUTO_FIX_FORBIDDEN_GAP_IDS = frozenset({
    "trainer_missing_checkpoint_weight_shape_contract",
    "live_only_blocker_not_auto_fixable",
})


def _classify_gaps(enriched: dict) -> list[dict]:
    """Convert enriched per-symbol classification into normalized gap rows.

    Severity rules (align with codex_continuous_remediation_review_governor):
    - checkpoint_weight_missing -> BLOCKS_PRODUCTION_EQUIVALENCE
    - V2_hold_due_strict_gate when paired with checkpoint blocker gap_id
      -> OPERATOR_DECISION_REQUIRED (V2 is correctly holding; the only
      reason it does not act is that no checkpoint blob is loaded)
    - missing_legacy_log_action_evidence / missing_v2_prediction
      / missing_legacy_log_evidence -> NO_ACTION_REQUIRED_SAFE_BLOCK
    - v2_paper_fill_gate_blocked with explicit block reasons
      -> NO_ACTION_REQUIRED_SAFE_BLOCK
    - v2_paper_fill_gate_blocked without block reasons
      -> P1_FIX for passthrough remediation
    - all other causes -> P1_FIX
    """
    gaps: list[dict] = []
    for row in (enriched.get("per_symbol") or []):
        causes = row.get("mismatch_causes_classified") or []
        if not causes and row.get("match"):
            continue
        sym = row.get("symbol")
        for cause in causes:
            gap_id = _CAUSE_TO_GAP_ID.get(cause)
            if not gap_id:
                gap_id = f"unclassified_{cause}"
            block_reasons = list(row.get("v2_paper_fill_gate_block_reasons") or [])
            if cause == "v2_paper_fill_gate_blocked" and block_reasons:
                gap_id = "paper_fill_gate_blocked_with_reason"
                severity = "NO_ACTION_REQUIRED_SAFE_BLOCK"
            elif cause == "v2_paper_fill_gate_blocked" and not block_reasons:
                severity = "P1_FIX"
            elif cause == "checkpoint_weight_missing":
                severity = "BLOCKS_PRODUCTION_EQUIVALENCE"
            elif cause == "V2_hold_due_strict_gate" and gap_id == "trainer_missing_checkpoint_weight_shape_contract":
                severity = "OPERATOR_DECISION_REQUIRED"
            elif cause in (
                "missing_v2_prediction",
                "missing_legacy_log_evidence",
                "missing_legacy_log_action_evidence",
            ):
                severity = "NO_ACTION_REQUIRED_SAFE_BLOCK"
            else:
                severity = "P1_FIX"
            gap_row = {
                "gap_id": gap_id,
                "symbol": sym,
                "cause": cause,
                "legacy_action": row.get("legacy_redis_action"),
                "legacy_log_action": row.get("legacy_log_action"),
                "v2_action": row.get("v2_action"),
                "v2_paper_fill_allowed": row.get("v2_paper_fill_allowed"),
                "severity": severity,
            }
            if cause == "v2_paper_fill_gate_blocked":
                gap_row["paper_fill_gate_block_reasons"] = block_reasons
            gaps.append(gap_row)
    return gaps


def _claude_task_payload(gap: dict, observation: dict) -> dict:
    trainer_path = (observation.get("trainer_log_summary") or {}).get("source_path")
    orch_path = (observation.get("orchestrator_log_summary") or {}).get("source_path")
    files_to_modify: list[str] = []
    tests_required: list[str] = []
    if gap["gap_id"] == "trainer_missing_checkpoint_weight_shape_contract":
        files_to_modify = [
            "v2/backend/app/services/rl_core/checkpoints.py",
            "v2/backend/app/services/rl_core/policy.py",
        ]
        tests_required = ["v2/backend/tests/integration/cli/test_v2_rl_core_p0_2c_checkpoint.py"]
    elif gap["gap_id"] == "orchestrator_missing_deconflict_rule_from_legacy_log":
        files_to_modify = [
            "v2/backend/app/services/orchestrator_arbitration/deconflict.py",
        ]
        tests_required = [
            "v2/backend/tests/integration/cli/test_v2_orchestrator_arbitration_worker.py",
        ]
    elif gap["gap_id"] == "feature_pipeline_freshness_mismatch_for_symbol":
        files_to_modify = ["v2/backend/app/cli/v2_feature_pipeline_native_loop.py"]
        tests_required = []
    elif gap["gap_id"] == "paper_fill_gate_block_reason_passthrough_missing":
        files_to_modify = [
            "v2/backend/app/services/rl_core/trainer_output.py",
            "v2/backend/app/cli/v2_rl_core_inference_loop.py",
        ]
        tests_required = [
            "v2/backend/tests/integration/cli/test_v2_rl_core_p0_2f_trainer_output.py",
        ]
    return {
        "task_id": f"claude_fix_v2_gap_{gap['gap_id']}",
        "kind": "claude_narrow_remediation",
        "severity": gap["severity"],
        "symbol": gap.get("symbol"),
        "gap_id": gap["gap_id"],
        "cause": gap["cause"],
        "source_log_or_script": trainer_path if "trainer" in gap["gap_id"] else (orch_path or trainer_path),
        "legacy_evidence": {
            "legacy_action": gap.get("legacy_action"),
            "legacy_log_action": gap.get("legacy_log_action"),
        },
        "v2_evidence": {
            "v2_action": gap.get("v2_action"),
            "v2_paper_fill_allowed": gap.get("v2_paper_fill_allowed"),
        },
        "required_v2_files_to_modify": files_to_modify,
        "tests_required": tests_required,
        "forbidden_actions": [
            "modify /home/wali/Desktop/AI BOT",
            "stop or restart legacy",
            "write old Redis keys",
            "place/cancel/modify exchange orders",
            "change leverage or margin",
            "enable live",
            "create approval token",
            "execute legacy monitor scripts",
            "load torch weights into V2 process",
        ],
        "required_public_payload_update": "v2/frontend/public/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json",
        "paired_codex_review_task_id": f"codex_review_fix_v2_gap_{gap['gap_id']}",
        "auto_apply_allowed_by_this_loop": gap["gap_id"] not in _AUTO_FIX_FORBIDDEN_GAP_IDS,
        "created_utc": _utc_iso(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def _codex_review_task_payload(gap: dict) -> dict:
    return {
        "task_id": f"codex_review_fix_v2_gap_{gap['gap_id']}",
        "kind": "codex_review",
        "paired_claude_task_id": f"claude_fix_v2_gap_{gap['gap_id']}",
        "fail_conditions": [
            "legacy evidence not cited",
            "V2 issue not reproduced",
            "fix is report-only",
            "test missing",
            "old Redis write appears",
            "exchange mutation appears",
            "live_gate changes",
            "live_symbols not []",
            "frontend hides blocker",
            "broad migration claim from narrow fix",
        ],
        "severity": gap["severity"],
        "gap_id": gap["gap_id"],
        "created_utc": _utc_iso(),
    }


def _write_task_pair(claude_task: dict, codex_task: dict) -> dict:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    cp = TASKS_DIR / f"{claude_task['task_id']}.json"
    rp = TASKS_DIR / f"{codex_task['task_id']}.json"
    claude_existed = cp.exists()
    codex_existed = rp.exists()
    if claude_existed:
        existing = _load_json(cp)
        preserved = {
            k: existing[k]
            for k in ("status", "completed_utc", "result", "codex_decision")
            if k in existing
        }
        existing.update(claude_task)
        existing.update(preserved)
        existing["updated_utc"] = _utc_iso()
        cp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    else:
        cp.write_text(json.dumps(claude_task, indent=2, sort_keys=True) + "\n")
    if codex_existed:
        existing = _load_json(rp)
        preserved = {
            k: existing[k]
            for k in ("status", "completed_utc", "result", "codex_decision")
            if k in existing
        }
        existing.update(codex_task)
        existing.update(preserved)
        existing["updated_utc"] = _utc_iso()
        rp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    else:
        rp.write_text(json.dumps(codex_task, indent=2, sort_keys=True) + "\n")
    return {
        "claude_task_path": str(cp.relative_to(REPO)),
        "codex_task_path": str(rp.relative_to(REPO)),
        "claude_task_existed_before": claude_existed,
    }


def run_once() -> dict:
    observation = observe_once()
    comparison = _load_json(COMPARATOR_PATH)
    enriched = enrich_comparison(observation, comparison)
    hints = remediation_hints_from_summary(observation, enriched)
    gaps = _classify_gaps(enriched)
    written_tasks: list[dict] = []
    seen_gap_keys: set[tuple[str, str]] = set()
    # Loop spec (operator instruction): only actionable severities produce
    # narrow Claude+Codex task pairs. Operator-decision and safe-block rows
    # remain visible in the gap matrix but do not generate or refresh tasks.
    actionable_severities = {"P1_FIX", "BLOCKS_PRODUCTION_EQUIVALENCE"}
    for gap in gaps:
        if not gap.get("gap_id"):
            continue
        if gap["gap_id"].startswith("unclassified_"):
            continue
        if gap.get("severity") not in actionable_severities:
            continue
        key = (gap["gap_id"], str(gap.get("symbol") or ""))
        if key in seen_gap_keys:
            # Multiple rows can map to the same gap_id within one cycle
            # (e.g. V2_hold + checkpoint_weight_missing both -> checkpoint
            # gap). Suppress duplicate within-cycle task refreshes.
            continue
        seen_gap_keys.add(key)
        c = _claude_task_payload(gap, observation)
        r = _codex_review_task_payload(gap)
        written_tasks.append({"gap_id": gap["gap_id"], "symbol": gap.get("symbol"),
                              **_write_task_pair(c, r), "severity": gap["severity"]})
    severity_counts: dict[str, int] = {}
    for g in gaps:
        severity_counts[g["severity"]] = severity_counts.get(g["severity"], 0) + 1
    soak = _load_json(SOAK_STATUS_PATH)
    soak_codex = _load_json(SOAK_CODEX_STATUS_PATH)
    # PHASE 3: classify production-equivalence-blocking gaps vs informational ones.
    production_equivalence_gaps_open = sum(
        1 for g in gaps if g.get("severity") == "BLOCKS_PRODUCTION_EQUIVALENCE"
    )
    duplicate_task_suppression_count = sum(
        1 for t in written_tasks if t.get("claude_task_existed_before") is True
    )
    remediation_tasks_created_count = sum(
        1 for t in written_tasks if t.get("claude_task_existed_before") is False
    )
    # Self process status checks.
    legacy_log_observer_running = _ps_running(
        "v2.backend.app.cli.v2_legacy_log_intelligence_observer"
    )
    continuous_remediation_running = _ps_running(
        "v2_continuous_legacy_log_to_rebuild_remediation"
    )
    soak_runtime_active = (
        bool(soak)
        and soak.get("all_v2_processes_uninterrupted") is True
        and soak.get("v2_namespaces_never_empty") is True
        and soak.get("soak_1h_ready") is True
    )
    soak_governor_shutdown_decision = soak_codex.get("go_no_go") if soak_codex else None
    soak_governor_shutdown_ready = (
        soak_governor_shutdown_decision
        == "CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_READY"
    )
    # Self-declared READY: remediation-loop scoped only.
    self_fail_blockers: list[str] = []
    if not (
        (observation.get("trainer_log_summary") or {}).get("source_path")
        or (observation.get("orchestrator_log_summary") or {}).get("source_path")
    ):
        self_fail_blockers.append("LEGACY_LOG_SOURCES_NOT_FOUND")
    if not soak_runtime_active:
        self_fail_blockers.append("SOAK_RUNTIME_NOT_ACTIVE")
    if not legacy_log_observer_running:
        self_fail_blockers.append("LEGACY_LOG_OBSERVER_NOT_RUNNING")
    go_no_go = GO_READY if not self_fail_blockers else GO_BLOCKED
    gap_matrix = {
        "schema_version": "v2_legacy_log_v2_gap_matrix_v1",
        "generated_utc": _utc_iso(),
        "no_invented_outcomes": True,
        "gaps": gaps,
        "severity_counts": severity_counts,
        "production_equivalence_gaps_open": production_equivalence_gaps_open,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _write_json(GAP_MATRIX_WORKLOG, gap_matrix)
    _write_json(GAP_MATRIX_PUBLIC, gap_matrix)
    status = {
        "schema_version": "v2_continuous_legacy_log_remediation_status_v2",
        "generated_utc": _utc_iso(),
        "loop_iteration_at": _utc_iso(),
        "go_no_go": go_no_go,
        "self_fail_blockers": self_fail_blockers,
        "continuous_remediation_running": continuous_remediation_running,
        "legacy_log_observer_running": legacy_log_observer_running,
        "soak_runtime_active": soak_runtime_active,
        "soak_governor_shutdown_ready": soak_governor_shutdown_ready,
        "soak_governor_shutdown_decision": soak_governor_shutdown_decision,
        "observer_present": observation.get("trainer_log_summary", {}).get("source_path") is not None
                            or observation.get("orchestrator_log_summary", {}).get("source_path") is not None,
        "trainer_log_summary_path": (observation.get("trainer_log_summary") or {}).get("source_path"),
        "orchestrator_log_summary_path": (observation.get("orchestrator_log_summary") or {}).get("source_path"),
        "monitor_script_count": len(observation.get("monitor_scripts_summary") or []),
        "remediation_hints_emitted": len(hints),
        "remediation_hints_sample": hints[:5],
        "gaps_total": len(gaps),
        "gaps_severity_counts": severity_counts,
        "production_equivalence_gaps_open": production_equivalence_gaps_open,
        "remediation_tasks_created_count": remediation_tasks_created_count,
        "duplicate_task_suppression_count": duplicate_task_suppression_count,
        "claude_codex_task_pairs_written_or_existing": written_tasks,
        "soak_minutes_observed": (soak.get("minutes_observed") if soak else None),
        "soak_1h_ready": (soak.get("soak_1h_ready") if soak else None),
        "soak_6h_ready": (soak.get("soak_6h_ready") if soak else None),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_legacy_mutation": True,
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
        "no_legacy_script_executed": True,
    }
    _write_json(WORKLOG_STATUS, status)
    _write_json(PUBLIC_STATUS, status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_continuous_legacy_log_to_rebuild_remediation")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.status:
        s = _load_json(WORKLOG_STATUS)
        print(json.dumps({
            "gaps_total": s.get("gaps_total"),
            "gaps_severity_counts": s.get("gaps_severity_counts"),
            "soak_minutes_observed": s.get("soak_minutes_observed"),
        }))
        return 0
    if args.loop:
        while True:
            s = run_once()
            print(json.dumps({
                "gaps_total": s["gaps_total"],
                "severity_counts": s["gaps_severity_counts"],
                "task_pairs": len(s["claude_codex_task_pairs_written_or_existing"]),
            }))
            time.sleep(max(60, int(args.interval_seconds)))
    s = run_once()
    print(json.dumps({
        "gaps_total": s["gaps_total"],
        "severity_counts": s["gaps_severity_counts"],
        "task_pairs": len(s["claude_codex_task_pairs_written_or_existing"]),
        "soak_minutes_observed": s["soak_minutes_observed"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
