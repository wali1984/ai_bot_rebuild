"""V2 Closed-Loop Claude/Codex Executor — phase 4 coordinator.

Continuously consumes pending Claude tasks, runs Codex reviews, detects
stalls, creates remediations, and advances until no automatable work
remains. The coordinator is the only component allowed to declare the
``V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_READY`` marker, and only
when:

* the Claude executor is available,
* the Codex executor is available,
* no operator-required tasks remain or all are already attributed,
* lane utilization is at its target (or there genuinely is no
  automatable work).
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import v2_claude_task_runner as claude_runner
import v2_codex_review_runner as codex_runner
import v2_current_work_filter as current_filter
from v2_closed_loop_lifecycle import (
    LIFECYCLE_DIR,
    PUBLIC_DIR,
    REPO_ROOT,
    TASKS_DIR,
    clear_active_worker_leases,
    ensure_dirs,
    expected_outputs_present,
    is_complete_marker,
    iter_task_files,
    normalize_descriptor,
    reconcile_source_truth_completions,
    pid_alive,
    read_heartbeat,
    read_json,
    utc_iso,
    write_json_atomic,
    source_truth_completion_suppresses_dispatch,
)

LIVE_BLOCKED_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "modifies_legacy_repo": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
}

CODEX_COMPLETED_TASK_REDISPATCH_REVIEW_PATH = (
    LIFECYCLE_DIR / "codex_review" / "codex_review_status.json"
)


def _load_completed_task_redispatch_codex_review() -> dict[str, Any] | None:
    payload = read_json(CODEX_COMPLETED_TASK_REDISPATCH_REVIEW_PATH)
    return payload if isinstance(payload, dict) else None


def _attach_completed_task_redispatch_codex_review(payload: dict[str, Any]) -> None:
    review = _load_completed_task_redispatch_codex_review()
    if not review:
        return
    payload["codex_completed_task_redispatch_review"] = review
    if review.get("go_no_go"):
        payload["codex_go_no_go"] = review["go_no_go"]
    if review.get("generated_utc"):
        payload["codex_review_generated_utc"] = review["generated_utc"]


def _reconciliation_marker(
    reconciliation: dict[str, Any],
    *,
    preflight_ok: bool,
) -> str:
    if not preflight_ok:
        return "V2_CLOSED_LOOP_COMPLETED_TASK_REDISPATCH_REMEDIATION_BLOCKED"
    if reconciliation.get("errors"):
        return "V2_CLOSED_LOOP_COMPLETED_TASK_REDISPATCH_REMEDIATION_BLOCKED"
    return "V2_CLOSED_LOOP_COMPLETED_TASK_REDISPATCH_REMEDIATION_READY"


def _write_task_lifecycle_reconciliation_payloads(
    reconciliation: dict[str, Any],
    lease_clear: dict[str, Any],
    marker: str,
) -> dict[str, Any]:
    now = utc_iso()
    stale_payload = {
        "schema_version": "v2_closed_loop_stale_completed_task_redispatch_status_v1",
        "generated_utc": now,
        "marker": marker,
        "source_truth_completed_count": len(
            reconciliation.get("stale_completed_reconciliations") or []
        ),
        "already_completed_source_truth_count": len(
            reconciliation.get("already_completed_source_truth") or []
        ),
        "stale_completed_reconciliations": reconciliation.get(
            "stale_completed_reconciliations",
            [],
        ),
        "already_completed_source_truth": reconciliation.get(
            "already_completed_source_truth",
            [],
        ),
        "leases_to_clear_count": len(reconciliation.get("leases_to_clear") or []),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    suppression_payload = {
        "schema_version": "v2_closed_loop_redispatch_suppression_status_v1",
        "generated_utc": now,
        "marker": marker,
        "redispatch_suppressed_count": len(
            reconciliation.get("redispatch_suppression") or []
        ),
        "already_completed_source_truth_count": len(
            reconciliation.get("already_completed_source_truth") or []
        ),
        "redispatch_suppression": reconciliation.get("redispatch_suppression", []),
        "already_completed_source_truth": reconciliation.get(
            "already_completed_source_truth",
            [],
        ),
        "leases_to_clear_count": len(reconciliation.get("leases_to_clear") or []),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    lifecycle_payload = {
        "schema_version": "v2_closed_loop_task_lifecycle_reconciliation_status_v1",
        "generated_utc": now,
        "marker": marker,
        "go_no_go": marker,
        "ready": marker.endswith("READY"),
        "source_truth_reconciliation": reconciliation,
        "active_lease_clear": lease_clear,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    for payload in (stale_payload, suppression_payload, lifecycle_payload):
        _attach_completed_task_redispatch_codex_review(payload)
    write_json_atomic(
        LIFECYCLE_DIR / "stale_completed_task_redispatch_status.json",
        stale_payload,
    )
    write_json_atomic(
        LIFECYCLE_DIR / "redispatch_suppression_status.json",
        suppression_payload,
    )
    write_json_atomic(
        LIFECYCLE_DIR / "task_lifecycle_reconciliation_status.json",
        lifecycle_payload,
    )
    write_json_atomic(PUBLIC_DIR / "stale_completed_task_redispatch_status.json", stale_payload)
    write_json_atomic(PUBLIC_DIR / "redispatch_suppression_status.json", suppression_payload)
    write_json_atomic(PUBLIC_DIR / "task_lifecycle_reconciliation_status.json", lifecycle_payload)
    write_json_atomic(LIFECYCLE_DIR / "GO_NO_GO.md", marker + "\n")
    (LIFECYCLE_DIR / "GO_NO_GO.md").write_text(marker + "\n", encoding="utf-8")
    (PUBLIC_DIR / "GO_NO_GO.md").write_text(marker + "\n", encoding="utf-8")
    return lifecycle_payload


def preflight_safety() -> dict[str, Any]:
    """Verify runtime safety invariants before doing anything.

    The coordinator refuses to start work if any of the protected
    runtime conditions are violated. The checks are deliberately
    minimal: they confirm we are operating in the V2 repo and that we
    cannot reach the legacy AI BOT directory through any write path.
    """
    legacy = (REPO_ROOT.parent / "AI BOT").resolve()
    legacy_under_repo = False
    try:
        legacy.relative_to(REPO_ROOT)
        legacy_under_repo = True
    except ValueError:
        legacy_under_repo = False
    checks = {
        "repo_root_is_v2": REPO_ROOT.name == "AI BOT REBUILD",
        "legacy_repo_is_outside": not legacy_under_repo,
        "no_live_env": os.environ.get("V2_LIVE") in (None, "", "0", "false", "blocked"),
        "no_canary_env": os.environ.get("V2_CANARY") in (None, "", "0", "false"),
        "no_redis_trim_env": os.environ.get("V2_REDIS_TRIM") in (None, "", "0", "false"),
        "host": socket.gethostname(),
        "envelope": LIVE_BLOCKED_ENVELOPE,
    }
    checks["preflight_ok"] = all(
        v is True for k, v in checks.items() if k.startswith("no_") or k in ("repo_root_is_v2", "legacy_repo_is_outside")
    )
    return checks


def collect_descriptors() -> list[dict[str, Any]]:
    current_ids: set[str] | None = None
    try:
        if "PYTEST_CURRENT_TEST" not in os.environ and current_filter.REAL_MODE_DIR.exists():
            result = current_filter.build_current_work_queue(active_window_hours=24)
            queue = result.get("queue") or {}
            current_ids = {
                str(row.get("task_id"))
                for row in queue.get("current", [])
                if row.get("task_id")
            }
            if not current_ids and len(list(iter_task_files())) <= 20:
                current_ids = None
    except Exception:  # noqa: BLE001
        current_ids = None
    out: list[dict[str, Any]] = []
    for f in iter_task_files():
        raw = read_json(f)
        if not isinstance(raw, dict):
            continue
        d = normalize_descriptor(raw, f)
        if current_ids is not None and str(d.get("task_id")) not in current_ids:
            continue
        out.append(d)
    return out


def count_real_active_lanes(descriptors: list[dict[str, Any]]) -> dict[str, int]:
    """Active lanes are anchored on living pids — never descriptors alone."""
    claude_active = 0
    codex_active = 0
    for d in descriptors:
        if d.get("status") != "running":
            continue
        pid = d.get("pid_or_job_id")
        if not pid_alive(pid):
            continue
        hb = read_heartbeat(d["task_id"])
        if not hb or not hb.get("alive"):
            continue
        if d["task_type"] in ("CLAUDE_IMPLEMENTATION", "REMEDIATION"):
            claude_active += 1
        elif d["task_type"] in ("CODEX_REVIEW", "CODEX_TAKEOVER"):
            codex_active += 1
    return {"claude": claude_active, "codex": codex_active}


def categorise(descriptors: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets = {
        "pending_claude": [],
        "pending_codex": [],
        "stale_claude": [],
        "stale_codex": [],
        "operator_required": [],
        "duplicates": [],
        "completed": [],
        "failed": [],
    }
    for d in descriptors:
        status = d.get("status")
        ttype = d.get("task_type")
        if status == "duplicate_suppressed":
            buckets["duplicates"].append(d)
            continue
        if status == "blocked_operator_required":
            buckets["operator_required"].append(d)
            continue
        if status == "stale":
            if ttype in ("CLAUDE_IMPLEMENTATION", "REMEDIATION"):
                buckets["stale_claude"].append(d)
            elif ttype in ("CODEX_REVIEW", "CODEX_TAKEOVER"):
                buckets["stale_codex"].append(d)
            continue
        if status == "completed":
            buckets["completed"].append(d)
            continue
        if status == "failed":
            buckets["failed"].append(d)
            continue
        if status in ("pending", "pending_redispatch", "running"):
            if ttype in ("CLAUDE_IMPLEMENTATION", "REMEDIATION"):
                buckets["pending_claude"].append(d)
            elif ttype in ("CODEX_REVIEW", "CODEX_TAKEOVER"):
                buckets["pending_codex"].append(d)
    return buckets


def pair_codex_reviews(
    descriptors: list[dict[str, Any]], *, dry_run: bool = False
) -> list[dict[str, Any]]:
    """For each Claude task whose expected outputs are present but has no
    paired Codex review descriptor yet, enqueue one. Safe-scoped: the
    descriptor is created as pending so the Codex runner picks it up.
    """
    enqueued: list[dict[str, Any]] = []
    existing_pairs = {
        d.get("codex_pair_task_id")
        for d in descriptors
        if d.get("task_type") in ("CODEX_REVIEW", "CODEX_TAKEOVER")
    }
    for d in descriptors:
        if d.get("task_type") != "CLAUDE_IMPLEMENTATION":
            continue
        if source_truth_completion_suppresses_dispatch(d):
            continue
        if d.get("status") not in ("completed",) and not (
            expected_outputs_present(d) or is_complete_marker(d)
        ):
            continue
        tid = d.get("task_id")
        if not tid or tid in existing_pairs:
            continue
        out_name = f"closed_loop_codex_review_{tid}.json"
        out_path = TASKS_DIR / out_name
        if out_path.exists():
            existing_pairs.add(tid)
            continue
        payload = {
            "task_id": out_name[:-5],
            "task_type": "CODEX_REVIEW",
            "owner": "CODEX",
            "status": "pending",
            "file_lock_group": d.get("file_lock_group"),
            "created_at": utc_iso(),
            "updated_at": utc_iso(),
            "codex_pair_task_id": tid,
            "scope_paths": d.get("expected_output_paths") or [],
            "prompt": (
                f"Codex review for paired Claude task {tid}. Scope: V2 changes "
                f"only. Do not approve live, canary, legacy shutdown or Redis "
                f"trim. End with <NAME>_CODEX_PASS or <NAME>_CODEX_FAIL."
            ),
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        }
        if not dry_run:
            write_json_atomic(out_path, payload)
        enqueued.append({
            "pair_for": tid,
            "path": str(out_path.relative_to(REPO_ROOT)),
            "dry_run": dry_run,
        })
        existing_pairs.add(tid)
    return enqueued


def compute_utilization(
    descriptors: list[dict[str, Any]],
    active: dict[str, int],
    target: int,
    *,
    last_dispatch_at: str | None,
    last_review_at: str | None,
    last_remediation_at: str | None,
) -> dict[str, Any]:
    buckets = categorise(descriptors)
    automatable = (
        len(buckets["pending_claude"])
        + len(buckets["pending_codex"])
        + len(buckets["stale_claude"])
        + len(buckets["stale_codex"])
    )
    active_lane_count = active["claude"] + active["codex"]
    util_pct = 100.0 if target == 0 else round(100.0 * active_lane_count / max(1, target), 1)
    blocker: str | None = None
    status = "OK"
    reason: str | None = None
    if automatable > 0 and active_lane_count < min(3, target):
        status = "BLOCKED"
        blocker = "ACTIVE_LANES_BELOW_MINIMUM"
        reason = (
            f"{automatable} automatable items but only {active_lane_count} "
            f"active lane(s); target is {target}."
        )
    elif automatable == 0:
        status = "MONITOR_ONLY"
        reason = "no automatable work remaining"
    payload = {
        "schema_version": "v2_closed_loop_utilization_status_v1",
        "generated_utc": utc_iso(),
        "active_claude_jobs": active["claude"],
        "active_codex_jobs": active["codex"],
        "pending_claude": len(buckets["pending_claude"]),
        "pending_codex": len(buckets["pending_codex"]),
        "stale_claude": len(buckets["stale_claude"]),
        "stale_codex": len(buckets["stale_codex"]),
        "automatable_work_count": automatable,
        "active_lane_count": active_lane_count,
        "target_active_lanes": target,
        "utilization_percent": util_pct,
        "status": status,
        "blocker": blocker,
        "reason_if_below_target": reason,
        "last_dispatch_at": last_dispatch_at,
        "last_review_at": last_review_at,
        "last_remediation_created_at": last_remediation_at,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    return payload


def write_engine_status(
    preflight: dict[str, Any],
    claude_state: dict[str, Any],
    codex_state: dict[str, Any],
    utilization: dict[str, Any],
    pairs: list[dict[str, Any]],
    task_lifecycle_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    executor_ready = bool(claude_state["executor"].get("available")) and bool(
        codex_state["executor"].get("available")
    )
    ready_blocked = (
        (not executor_ready)
        or (utilization["status"] == "BLOCKED")
        or (not preflight.get("preflight_ok"))
    )
    state = {
        "schema_version": "v2_closed_loop_execution_status_v1",
        "generated_utc": utc_iso(),
        "preflight": preflight,
        "claude_runner": claude_state,
        "codex_runner": codex_state,
        "utilization": utilization,
        "codex_review_pairs_enqueued": pairs,
        "task_lifecycle_reconciliation": task_lifecycle_reconciliation,
        "ready": not ready_blocked,
        "marker": (
            "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_READY"
            if not ready_blocked
            else "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_BLOCKED"
        ),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    _attach_completed_task_redispatch_codex_review(state)
    write_json_atomic(LIFECYCLE_DIR / "closed_loop_execution_status.json", state)
    write_json_atomic(PUBLIC_DIR / "closed_loop_execution_status.json", state)
    _write_engine_documents(state)
    _write_operator_payload(state)
    return state


def _write_engine_documents(state: dict[str, Any]) -> None:
    util = state.get("utilization", {})
    blockers = []
    if not state["claude_runner"]["executor"].get("available"):
        blockers.append("- CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED")
    if not state["codex_runner"]["executor"].get("available"):
        blockers.append("- Codex CLI not available on PATH")
    if util.get("status") == "BLOCKED":
        blockers.append(
            f"- {util.get('blocker')}: {util.get('reason_if_below_target')}"
        )
    body = [
        "# V2 Closed-Loop Claude/Codex Execution Engine Report",
        "",
        f"Marker: `{state['marker']}`",
        f"Generated: {state['generated_utc']}",
        "",
        "## Utilization Summary",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| active_claude_jobs | {util.get('active_claude_jobs')} |",
        f"| active_codex_jobs | {util.get('active_codex_jobs')} |",
        f"| pending_claude | {util.get('pending_claude')} |",
        f"| pending_codex | {util.get('pending_codex')} |",
        f"| stale_claude | {util.get('stale_claude')} |",
        f"| stale_codex | {util.get('stale_codex')} |",
        f"| automatable_work_count | {util.get('automatable_work_count')} |",
        f"| active_lane_count | {util.get('active_lane_count')} |",
        f"| target_active_lanes | {util.get('target_active_lanes')} |",
        f"| utilization_percent | {util.get('utilization_percent')} |",
        f"| status | {util.get('status')} |",
        f"| blocker | {util.get('blocker')} |",
        "",
        "## Executors",
        "",
        f"- Claude: available={state['claude_runner']['executor'].get('available')} ({state['claude_runner']['executor'].get('executor')})",
        f"- Codex:  available={state['codex_runner']['executor'].get('available')} ({state['codex_runner']['executor'].get('executor')})",
        "",
        "## Blockers",
        "",
        *(blockers or ["- (none)"]),
        "",
        "## Safety",
        "",
        "- live_gate=blocked_human_only",
        "- live_symbols=[]",
        "- approves_live=false",
        "- approves_canary=false",
        "- approves_legacy_shutdown=false",
        "- approves_redis_trim=false",
        "",
        "## Validation",
        "",
        "Tests under `v2/backend/tests/unit/tools/closed_loop_execution/` and the",
        "report-center registry tests must pass. See README in the same",
        "`v2_closed_loop_execution/latest/` directory for the exact command.",
        "",
    ]
    report_text = "\n".join(body)
    (LIFECYCLE_DIR / "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_REPORT.md").write_text(
        report_text, encoding="utf-8"
    )


def _write_operator_payload(state: dict[str, Any]) -> None:
    util = state.get("utilization", {})
    payload = {
        "schema_version": "v2_closed_loop_operator_payload_v1",
        "generated_utc": state["generated_utc"],
        "marker": state["marker"],
        "ready": state.get("ready", False),
        "active_claude_jobs": util.get("active_claude_jobs"),
        "active_codex_jobs": util.get("active_codex_jobs"),
        "pending_claude": util.get("pending_claude"),
        "pending_codex": util.get("pending_codex"),
        "stale_claude": util.get("stale_claude"),
        "stale_codex": util.get("stale_codex"),
        "automatable_work_count": util.get("automatable_work_count"),
        "active_lane_count": util.get("active_lane_count"),
        "target_active_lanes": util.get("target_active_lanes"),
        "utilization_percent": util.get("utilization_percent"),
        "status": util.get("status"),
        "blocker": util.get("blocker"),
        "last_dispatch_at": util.get("last_dispatch_at"),
        "last_review_at": util.get("last_review_at"),
        "last_remediation_created_at": util.get("last_remediation_created_at"),
        "claude_executor_available": bool(state["claude_runner"]["executor"].get("available")),
        "codex_executor_available": bool(state["codex_runner"]["executor"].get("available")),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
        "next_action": (
            "Engine READY. Continue monitoring via the closed-loop coordinator timer."
            if state.get("ready") else
            "Engine BLOCKED. See blockers in V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_REPORT.md."
        ),
    }
    _attach_completed_task_redispatch_codex_review(payload)
    write_json_atomic(LIFECYCLE_DIR / "operator_dashboard_payload.json", payload)
    write_json_atomic(PUBLIC_DIR / "operator_dashboard_payload.json", payload)


def _lifecycle_snapshot(descriptors: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = categorise(descriptors)
    snapshot = {
        "schema_version": "v2_closed_loop_task_lifecycle_status_v1",
        "generated_utc": utc_iso(),
        "counts": {k: len(v) for k, v in buckets.items()},
        "operator_required": [d.get("task_id") for d in buckets["operator_required"]],
        "stale_claude": [d.get("task_id") for d in buckets["stale_claude"]],
        "stale_codex": [d.get("task_id") for d in buckets["stale_codex"]],
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    _attach_completed_task_redispatch_codex_review(snapshot)
    write_json_atomic(LIFECYCLE_DIR / "task_lifecycle_status.json", snapshot)
    write_json_atomic(PUBLIC_DIR / "task_lifecycle_status.json", snapshot)
    return snapshot


def run_once(
    *,
    claude_lanes: int,
    codex_lanes: int,
    target_lanes: int,
    dry_run: bool,
) -> dict[str, Any]:
    ensure_dirs()
    preflight = preflight_safety()
    reconciliation = reconcile_source_truth_completions(apply_updates=True)
    lease_clear = clear_active_worker_leases(reconciliation.get("leases_to_clear", ()))
    reconciliation_marker = _reconciliation_marker(
        reconciliation,
        preflight_ok=bool(preflight.get("preflight_ok")),
    )
    reconciliation_payload = _write_task_lifecycle_reconciliation_payloads(
        reconciliation,
        lease_clear,
        reconciliation_marker,
    )

    if not preflight.get("preflight_ok"):
        write_json_atomic(LIFECYCLE_DIR / "preflight_block.json", preflight)
        return {
            "marker": "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_BLOCKED",
            "preflight": preflight,
            "task_lifecycle_reconciliation": reconciliation_payload,
            "ready": False,
        }

    # Always rebuild lifecycle snapshot first so the status file reflects
    # current truth even when dispatch is skipped.
    descriptors = collect_descriptors()
    _lifecycle_snapshot(descriptors)

    # Auto-enqueue Codex review pairs for any completed Claude work.
    pairs = pair_codex_reviews(descriptors, dry_run=dry_run)

    # Refresh after enqueue so the runners see the new descriptors.
    descriptors = collect_descriptors()

    claude_state = claude_runner.run_once(max_lanes=claude_lanes, dry_run=dry_run)
    codex_state = codex_runner.run_once(max_lanes=codex_lanes, dry_run=dry_run)

    descriptors = collect_descriptors()
    _lifecycle_snapshot(descriptors)
    active = count_real_active_lanes(descriptors)
    last_dispatch = (
        claude_state["dispatched"][-1].get("ended_utc") if claude_state.get("dispatched") else None
    ) or (claude_state["generated_utc"] if claude_state.get("dispatched") else None)
    last_review = (
        codex_state["reviews"][-1].get("ended_utc") if codex_state.get("reviews") else None
    )
    last_remediation = None
    if codex_state.get("remediations_created"):
        last_remediation = codex_state["generated_utc"]
    utilization = compute_utilization(
        descriptors,
        active,
        target_lanes,
        last_dispatch_at=last_dispatch,
        last_review_at=last_review,
        last_remediation_at=last_remediation,
    )
    write_json_atomic(LIFECYCLE_DIR / "closed_loop_utilization_status.json", utilization)
    write_json_atomic(PUBLIC_DIR / "closed_loop_utilization_status.json", utilization)

    return write_engine_status(
        preflight,
        claude_state,
        codex_state,
        utilization,
        pairs,
        reconciliation_payload,
    )


def loop(
    *,
    claude_lanes: int,
    codex_lanes: int,
    target_lanes: int,
    interval_seconds: int,
    dry_run: bool,
    iterations: int | None,
) -> int:
    count = 0
    while True:
        state = run_once(
            claude_lanes=claude_lanes,
            codex_lanes=codex_lanes,
            target_lanes=target_lanes,
            dry_run=dry_run,
        )
        print(json.dumps({
            "generated_utc": state.get("generated_utc"),
            "marker": state.get("marker"),
            "ready": state.get("ready"),
        }, indent=2, sort_keys=True))
        count += 1
        if iterations is not None and count >= iterations:
            return 0
        time.sleep(max(60, interval_seconds))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--claude-lanes", type=int, default=3)
    p.add_argument("--codex-lanes", type=int, default=3)
    p.add_argument("--target-lanes", type=int, default=3)
    p.add_argument("--interval-seconds", type=int, default=120)
    p.add_argument("--max-iterations", type=int, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.status:
        status_path = LIFECYCLE_DIR / "closed_loop_execution_status.json"
        if status_path.exists():
            print(status_path.read_text(encoding="utf-8"))
        else:
            print(json.dumps({"marker": "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_BLOCKED", "reason": "no_status_file_yet"}))
        return 0

    if args.loop:
        return loop(
            claude_lanes=args.claude_lanes,
            codex_lanes=args.codex_lanes,
            target_lanes=args.target_lanes,
            interval_seconds=args.interval_seconds,
            dry_run=args.dry_run,
            iterations=args.max_iterations,
        )

    state = run_once(
        claude_lanes=args.claude_lanes,
        codex_lanes=args.codex_lanes,
        target_lanes=args.target_lanes,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": state.get("generated_utc"),
            "marker": state.get("marker"),
            "ready": state.get("ready"),
            "active_lane_count": state.get("utilization", {}).get("active_lane_count"),
            "automatable_work_count": state.get("utilization", {}).get("automatable_work_count"),
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
