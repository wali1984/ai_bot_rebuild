"""V2 Codex review runner — phase 3 of the closed-loop execution engine.

Consumes pending Codex review tasks, dispatches them through the
installed Codex CLI using valid forms only, writes the canonical
CODEX_REVIEW.md / CODEX_GO_NO_GO.md outputs, and translates fail
verdicts into safe scoped V2-side remediation descriptors when the
spec permits.

Valid CLI forms (per spec), with non-interactive Codex flags inserted
before the subcommand:

* ``codex --sandbox danger-full-access --ask-for-approval never review "<scoped review prompt>"``
* ``codex --sandbox danger-full-access --ask-for-approval never exec review "<scoped review prompt>"``
* ``codex --sandbox danger-full-access --ask-for-approval never exec "<scoped scripted prompt>"``

Scope and paths are embedded *inside* the prompt text — never as
invalid CLI flags.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from v2_closed_loop_lifecycle import (
    LIFECYCLE_DIR,
    LOG_DIR,
    PUBLIC_DIR,
    REPO_ROOT,
    TASKS_DIR,
    ensure_dirs,
    reconcile_source_truth_completions,
    source_truth_completion_suppresses_dispatch,
    file_lock,
    iter_task_files,
    normalize_descriptor,
    pid_alive,
    read_json,
    utc_iso,
    write_heartbeat,
    write_json_atomic,
)

CODEX_REVIEW_OUTPUTS_DIRNAME = "codex_review_outputs"
CODEX_NON_INTERACTIVE_FLAGS = ["--sandbox", "danger-full-access", "--ask-for-approval", "never"]


def _current_work_ids() -> set[str] | None:
    """Return the current-work allow set, or None if filtering is unavailable."""
    try:
        if "PYTEST_CURRENT_TEST" in os.environ:
            return None
        import v2_current_work_filter as current_filter  # type: ignore

        if not current_filter.REAL_MODE_DIR.exists():
            return None
        result = current_filter.build_current_work_queue(active_window_hours=24)
        queue = result.get("queue") or {}
        ids = {
            str(row.get("task_id"))
            for row in queue.get("current", [])
            if row.get("task_id")
        }
        if not ids and len(list(iter_task_files())) <= 20:
            return None
        return ids
    except Exception:  # noqa: BLE001
        return None


def discover_codex_executor() -> dict[str, Any]:
    cli = shutil.which("codex")
    if not cli:
        return {"available": False, "executor": None}
    try:
        r = subprocess.run([cli, "--version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {"available": False, "executor": None}
    return {
        "available": r.returncode == 0,
        "executor": "codex_cli",
        "binary": cli,
        "version": (r.stdout or "").strip().splitlines()[:1],
    }


def codex_pending_tasks() -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    current_ids = _current_work_ids()
    for f in iter_task_files():
        raw = read_json(f)
        if not isinstance(raw, dict):
            continue
        d = normalize_descriptor(raw, f)
        if current_ids is not None and str(d.get("task_id")) not in current_ids:
            continue
        if d["task_type"] not in ("CODEX_REVIEW", "CODEX_TAKEOVER"):
            continue
        if d["status"] not in ("pending", "pending_redispatch", "stale"):
            continue
        if source_truth_completion_suppresses_dispatch(d):
            continue
        out.append((f, d))
    return out


def _scoped_prompt(d: dict[str, Any]) -> str:
    base = d.get("prompt") or d.get("scoped_review_prompt") or (
        f"Review the V2-side scope for task {d.get('task_id')}. "
        "Do not approve live, canary, legacy shutdown, or Redis trim. "
        "Treat live_gate as blocked_human_only and live_symbols as []. "
        "Emit a CODEX_GO_NO_GO.md ending with _CODEX_PASS or _CODEX_FAIL."
    )
    scope_paths = d.get("scope_paths") or d.get("paths") or []
    if scope_paths:
        base += "\n\nScope paths (embedded in prompt, not CLI flags):\n"
        base += "\n".join(f"- {p}" for p in scope_paths)
    if d.get("codex_pair_task_id"):
        base += f"\n\nPaired Claude task id: {d['codex_pair_task_id']}"
    return base


def _outputs_dir(task_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", task_id)
    out = LIFECYCLE_DIR / CODEX_REVIEW_OUTPUTS_DIRNAME / safe
    out.mkdir(parents=True, exist_ok=True)
    return out


def _codex_command(executor: dict[str, Any], d: dict[str, Any]) -> list[str]:
    """Pick a valid Codex CLI invocation per spec."""
    binary = executor["binary"]
    base = [binary, *CODEX_NON_INTERACTIVE_FLAGS]
    form = (d.get("codex_cli_form") or "codex_exec_review").lower()
    prompt = _scoped_prompt(d)
    if form == "codex_exec_review_uncommitted":
        return [*base, "exec", "review", prompt]
    if form == "codex_exec":
        return [*base, "exec", prompt]
    if form == "codex_review":
        return [*base, "review", prompt]
    # Default form
    return [*base, "exec", "review", prompt]


def run_codex_review(
    descriptor_path: Path,
    d: dict[str, Any],
    executor: dict[str, Any],
    *,
    dry_run: bool,
    timeout: int = 900,
    heartbeat_callback: Callable[[], None] | None = None,
    heartbeat_interval: int = 15,
) -> dict[str, Any]:
    ensure_dirs()
    out_dir = _outputs_dir(d["task_id"])
    review_md = out_dir / "CODEX_REVIEW.md"
    verdict_md = out_dir / "CODEX_GO_NO_GO.md"
    log_path = LOG_DIR / f"{d['task_id']}_codex.log"
    if dry_run:
        return {
            "action": "dry_run",
            "task_id": d["task_id"],
            "review_md": str(review_md.relative_to(REPO_ROOT)),
            "verdict_md": str(verdict_md.relative_to(REPO_ROOT)),
        }
    if not executor.get("available"):
        return {
            "action": "blocked",
            "task_id": d["task_id"],
            "reason": "codex_cli_not_available",
        }
    cmd = _codex_command(executor, d)
    log_fp = open(log_path, "ab", buffering=0)
    started = utc_iso()
    rel_log_path = str(log_path.relative_to(REPO_ROOT))
    mark_descriptor(descriptor_path, {
        "status": "running",
        "pid_or_job_id": os.getpid(),
        "log_path": rel_log_path,
        "started_at": started,
    })
    write_heartbeat(
        d["task_id"],
        os.getpid(),
        {
            "task_type": d.get("task_type") or "CODEX_REVIEW",
            "log_path": rel_log_path,
            "file_lock_group": d.get("file_lock_group") or d["task_id"],
        },
    )
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + timeout
        timed_out = False
        returncode = -1
        while True:
            if heartbeat_callback is not None:
                heartbeat_callback()
            polled = proc.poll()
            if polled is not None:
                returncode = polled
                break
            if time.time() >= deadline:
                timed_out = True
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
                break
            time.sleep(min(heartbeat_interval, max(1, int(deadline - time.time()))))
    except subprocess.TimeoutExpired:
        returncode = -1
        timed_out = True
    finally:
        log_fp.close()

    log_text = ""
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        log_text = ""

    verdict, blockers = extract_verdict(log_text)
    review_md.write_text(_render_review_md(d, cmd, log_text, verdict, blockers), encoding="utf-8")
    verdict_md.write_text(verdict + "\n", encoding="utf-8")

    result = {
        "action": "completed" if returncode == 0 and not timed_out else "failed",
        "task_id": d["task_id"],
        "verdict": verdict,
        "fail_blockers": blockers,
        "started_utc": started,
        "ended_utc": utc_iso(),
        "returncode": returncode,
        "timed_out": timed_out,
        "review_md": str(review_md.relative_to(REPO_ROOT)),
        "verdict_md": str(verdict_md.relative_to(REPO_ROOT)),
        "log_path": rel_log_path,
        "command_form": cmd[:-1],
    }
    return result


VERDICT_RE = re.compile(r"\b([A-Z][A-Z0-9_]{4,})_CODEX_(PASS|FAIL)\b")


def extract_verdict(text: str) -> tuple[str, list[str]]:
    matches = VERDICT_RE.findall(text or "")
    if not matches:
        return ("CLOSED_LOOP_CODEX_REVIEW_UNDETERMINED", [])
    # Prefer the last verdict so a final summary line wins.
    name, kind = matches[-1]
    verdict = f"{name}_CODEX_{kind}"
    blockers: list[str] = []
    if kind == "FAIL":
        blockers = _extract_blockers(text)
    return (verdict, blockers)


def _extract_blockers(text: str) -> list[str]:
    blockers: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if low.startswith(("blocker", "blocking finding", "- blocker", "* blocker", "## blocking", "1. ")):
            blockers.append(s[:500])
        if len(blockers) >= 16:
            break
    return blockers


def _render_review_md(
    d: dict[str, Any], cmd: list[str], log: str, verdict: str, blockers: list[str]
) -> str:
    head = [
        f"# Codex Review: {d.get('task_id')}",
        "",
        f"GO/NO-GO: `{verdict}`",
        "",
        "## Command",
        "",
        "```text",
        " ".join(cmd[:-1]) + " <prompt>",
        "```",
        "",
    ]
    if blockers:
        head.append("## Blockers")
        head.append("")
        for b in blockers:
            head.append(f"- {b}")
        head.append("")
    head.extend([
        "## Raw Output (tail)",
        "",
        "```text",
        "\n".join((log or "").splitlines()[-200:]),
        "```",
        "",
    ])
    return "\n".join(head)


def is_safe_v2_scope_remediation_target(blocker: str) -> bool:
    """Refuse to auto-spawn remediation tasks for anything that smells
    like a live, shutdown, exchange, or legacy-repo concern. Those go
    to the operator instead.
    """
    lo = blocker.lower()
    danger = (
        "live trading", "live trade", "exchange", "redis trim", "legacy shutdown",
        "shutdown approval", "leverage", "margin", "live api key", "kill switch",
        "live gate", "legacy_reference/", "ai bot/", "ai bot ",
    )
    return not any(d in lo for d in danger)


def create_remediation_task(
    parent: dict[str, Any], blockers: list[str]
) -> tuple[Path | None, str]:
    safe_blockers = [b for b in blockers if is_safe_v2_scope_remediation_target(b)]
    if not safe_blockers:
        return (None, "no_safe_scope_remediation_targets")
    out_name = f"closed_loop_remediation_{parent['task_id']}.json"
    out_path = TASKS_DIR / out_name
    if out_path.exists():
        return (out_path, "already_exists")
    payload = {
        "task_id": out_name[:-5],
        "task_type": "REMEDIATION",
        "owner": "CLAUDE",
        "status": "pending",
        "file_lock_group": parent.get("file_lock_group"),
        "created_at": utc_iso(),
        "updated_at": utc_iso(),
        "codex_pair_task_id": parent.get("task_id"),
        "fail_blockers": safe_blockers,
        "next_action": (
            "Remediate the safe V2-side fail blockers listed in fail_blockers. "
            "Do not touch legacy. Do not call exchange mutation. Keep "
            "live_gate=blocked_human_only and live_symbols=[]."
        ),
        "safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "modifies_legacy_repo": False,
            "writes_old_redis": False,
            "calls_exchange_mutation": False,
        },
    }
    write_json_atomic(out_path, payload)
    return (out_path, "created")


def mark_descriptor(descriptor_path: Path, updates: dict[str, Any]) -> None:
    raw = read_json(descriptor_path) or {}
    if not isinstance(raw, dict):
        return
    raw.update(updates)
    raw["updated_at"] = utc_iso()
    write_json_atomic(descriptor_path, raw)


def run_once(*, max_lanes: int, dry_run: bool) -> dict[str, Any]:
    ensure_dirs()
    executor = discover_codex_executor()
    source_truth_reconciliation = reconcile_source_truth_completions(apply_updates=True)

    def _persist(path: Path, updates: dict[str, Any]) -> None:
        if dry_run:
            return
        mark_descriptor(path, updates)
    reviewed: list[dict[str, Any]] = []
    remediations: list[dict[str, Any]] = []
    operator_required: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    started = 0

    pending = codex_pending_tasks()
    for path, d in pending:
        if started >= max_lanes:
            blocked.append({"task_id": d["task_id"], "reason": "max_lanes_reached"})
            continue
        if not executor.get("available"):
            _persist(path, {
                "status": "blocked_operator_required",
                "operator_required_reason": "codex_cli_not_available",
            })
            operator_required.append({"task_id": d["task_id"], "reason": "codex_cli_not_available"})
            continue
        with file_lock(d.get("file_lock_group") or d["task_id"]) as locked:
            if not locked:
                blocked.append({"task_id": d["task_id"], "reason": "lock_unavailable"})
                continue
            started += 1
            _persist(path, {"status": "running", "started_at": utc_iso()})
            res = run_codex_review(path, d, executor, dry_run=dry_run)
        reviewed.append(res)
        verdict = res.get("verdict") or ""
        blockers = res.get("fail_blockers") or []
        if verdict.endswith("_CODEX_PASS"):
            _persist(path, {
                "status": "completed",
                "completed_at": utc_iso(),
                "fail_blockers": [],
                "next_action": f"Codex PASS recorded ({verdict}).",
            })
        elif verdict.endswith("_CODEX_FAIL"):
            rem_path, rem_status = create_remediation_task(d, blockers)
            _persist(path, {
                "status": "failed",
                "completed_at": utc_iso(),
                "fail_blockers": blockers,
                "next_action": (
                    f"Codex FAIL ({verdict}). Remediation: {rem_status}"
                    + (f" at {rem_path.relative_to(REPO_ROOT)}" if rem_path else "")
                ),
            })
            if rem_path and rem_status == "created":
                remediations.append({
                    "task_id": d["task_id"],
                    "remediation_path": str(rem_path.relative_to(REPO_ROOT)),
                })
            elif rem_status == "no_safe_scope_remediation_targets":
                operator_required.append({
                    "task_id": d["task_id"],
                    "reason": "fail_blockers_require_operator",
                })
        else:
            _persist(path, {
                "status": "blocked_operator_required",
                "operator_required_reason": "codex_verdict_undetermined",
            })
            operator_required.append({"task_id": d["task_id"], "reason": "verdict_undetermined"})

    state = {
        "schema_version": "v2_closed_loop_codex_review_runner_v1",
        "generated_utc": utc_iso(),
        "source_truth_reconciliation": source_truth_reconciliation,
        "executor": executor,
        "active_codex_jobs": 0,  # synchronous: lanes are not held between invocations
        "started_this_pass": started,
        "max_lanes": max_lanes,
        "reviews": reviewed,
        "remediations_created": remediations,
        "operator_required": operator_required,
        "actions_blocked": blocked,
        "safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "modifies_legacy_repo": False,
            "writes_old_redis": False,
            "calls_exchange_mutation": False,
        },
    }
    write_json_atomic(LIFECYCLE_DIR / "codex_review_runner_status.json", state)
    write_json_atomic(PUBLIC_DIR / "codex_review_runner_status.json", state)
    return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-lanes", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    state = run_once(max_lanes=args.max_lanes, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": state["generated_utc"],
            "started_this_pass": state["started_this_pass"],
            "remediations_created": len(state["remediations_created"]),
            "operator_required": len(state["operator_required"]),
            "executor_available": bool(state["executor"].get("available")),
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
