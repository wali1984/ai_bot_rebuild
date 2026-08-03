"""V2 Closed-Loop Persistent Worker Pool — enablement orchestrator.

One-shot orchestrator that:

* installs the templated user systemd units for the worker pool,
* enables and starts ``ai-bot-v2-closed-loop-claude-worker@1..3`` and
  ``ai-bot-v2-closed-loop-codex-worker@1``,
* fires the pool maintainer once to refresh status / reclaim stale
  leases,
* waits long enough for at least one heartbeat cycle so the proof is
  not measured on cold state,
* emits the canonical GO_NO_GO marker and the spec's required output
  payloads.

Active-lane accounting is delegated to ``v2_closed_loop_worker_pool``:
the worker daemon's own pid + a fresh heartbeat is what counts as a
lane — *never* the short-lived child Claude/Codex CLI processes the
worker spawns.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import v2_closed_loop_worker_pool as pool
import v2_current_work_filter as current_filter
from v2_closed_loop_lifecycle import (
    REPO_ROOT,
    ensure_dirs,
    read_json,
    utc_iso,
    write_json_atomic,
)

POOL_LATEST_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_persistent_worker_pool"
    / "latest"
)
POOL_PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_closed_loop_persistent_worker_pool"
    / "latest"
)
SYSTEMD_SRC = POOL_LATEST_DIR / "systemd"
SYSTEMD_DST = Path(os.path.expanduser("~/.config/systemd/user"))

UNIT_FILES = (
    "ai-bot-v2-closed-loop-claude-worker@.service",
    "ai-bot-v2-closed-loop-codex-worker@.service",
    "ai-bot-v2-closed-loop-worker-pool.service",
    "ai-bot-v2-closed-loop-worker-pool.timer",
)

LIVE_BLOCKED_ENVELOPE = dict(pool.LIVE_BLOCKED_ENVELOPE)


def ensure_dirs_for_outputs() -> None:
    POOL_LATEST_DIR.mkdir(parents=True, exist_ok=True)
    POOL_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------- systemd ----------------------------- #


def _systemctl(args: list[str]) -> dict[str, Any]:
    cmd = ["systemctl", *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return {"cmd": cmd, "returncode": r.returncode, "stdout": (r.stdout or "").strip(), "stderr": (r.stderr or "").strip()}
    except FileNotFoundError:
        return {"cmd": cmd, "returncode": -127, "stdout": "", "stderr": "systemctl_not_found"}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "returncode": -1, "stdout": "", "stderr": "timeout"}


def install_units(*, install: bool, enable: bool, claude_instances: list[int], codex_instances: list[int]) -> dict[str, Any]:
    """Copy units into ``~/.config/systemd/user`` and (optionally) issue
    ``systemctl --user enable --now`` for the requested instance ids.
    """
    out: dict[str, Any] = {
        "src": str(SYSTEMD_SRC),
        "dst": str(SYSTEMD_DST),
        "installed": install,
        "enabled": enable,
        "copied": [],
        "skipped": [],
        "errors": [],
        "daemon_reload": None,
        "enable_commands": [],
        "verification": {},
    }
    if not SYSTEMD_SRC.exists():
        out["errors"].append(f"systemd source missing: {SYSTEMD_SRC}")
        return out
    SYSTEMD_DST.mkdir(parents=True, exist_ok=True)

    if install:
        for unit in UNIT_FILES:
            src = SYSTEMD_SRC / unit
            dst = SYSTEMD_DST / unit
            if not src.exists():
                out["errors"].append(f"missing unit: {src}")
                continue
            try:
                if dst.exists() and dst.read_bytes() == src.read_bytes():
                    out["skipped"].append(unit)
                    continue
            except OSError:
                pass
            try:
                shutil.copyfile(src, dst)
                out["copied"].append(unit)
            except OSError as exc:
                out["errors"].append(f"copy failed: {unit} ({exc})")
        out["daemon_reload"] = _systemctl(["--user", "daemon-reload"])

    if enable:
        for i in claude_instances:
            out["enable_commands"].append(_systemctl([
                "--user", "enable", "--now", f"ai-bot-v2-closed-loop-claude-worker@{i}.service",
            ]))
        for i in codex_instances:
            out["enable_commands"].append(_systemctl([
                "--user", "enable", "--now", f"ai-bot-v2-closed-loop-codex-worker@{i}.service",
            ]))
        out["enable_commands"].append(_systemctl([
            "--user", "enable", "--now", "ai-bot-v2-closed-loop-worker-pool.timer",
        ]))

    # Verification.
    for i in claude_instances:
        name = f"ai-bot-v2-closed-loop-claude-worker@{i}.service"
        out["verification"][name] = {
            "is_enabled": _systemctl(["--user", "is-enabled", name]),
            "is_active": _systemctl(["--user", "is-active", name]),
        }
    for i in codex_instances:
        name = f"ai-bot-v2-closed-loop-codex-worker@{i}.service"
        out["verification"][name] = {
            "is_enabled": _systemctl(["--user", "is-enabled", name]),
            "is_active": _systemctl(["--user", "is-active", name]),
        }
    out["verification"]["ai-bot-v2-closed-loop-worker-pool.timer"] = {
        "is_enabled": _systemctl(["--user", "is-enabled", "ai-bot-v2-closed-loop-worker-pool.timer"]),
        "is_active": _systemctl(["--user", "is-active", "ai-bot-v2-closed-loop-worker-pool.timer"]),
    }
    return out


# ----------------------------- direct-spawn fallback ----------------------------- #


def direct_spawn_workers(claude_count: int, codex_count: int) -> dict[str, Any]:
    """Bring workers up *without* systemd. Used as a fallback when
    ``systemctl --user`` is unavailable (e.g., running outside a
    session DBus). Spawned workers are detached via start_new_session.
    """
    pool.ensure_worker_dirs()
    spawned: list[dict[str, Any]] = []
    # Re-use the pool's maintain_pool so the spawn counters / id
    # generation stay consistent.
    res = pool.maintain_pool(target_claude=claude_count, target_codex=codex_count, spawn=True)
    spawned.extend(res["actions"])
    return {"actions": spawned, "claude_needed": res["claude_needed"], "codex_needed": res["codex_needed"]}


# ----------------------------- outputs ----------------------------- #


def emit_outputs(state: dict[str, Any]) -> None:
    ensure_dirs_for_outputs()
    write_json_atomic(POOL_LATEST_DIR / "worker_pool_status.json", state["pool_status"])
    write_json_atomic(POOL_PUBLIC_DIR / "worker_pool_status.json", state["pool_status"])
    write_json_atomic(POOL_LATEST_DIR / "worker_heartbeats.json", {
        "schema_version": "v2_closed_loop_worker_heartbeats_v1",
        "generated_utc": utc_iso(),
        "heartbeats": state["pool_status"]["heartbeats"],
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    })
    write_json_atomic(POOL_LATEST_DIR / "worker_leases.json", {
        "schema_version": "v2_closed_loop_worker_leases_v1",
        "generated_utc": utc_iso(),
        "leases": state["pool_status"]["leases"],
        "active_leases_count": state["pool_status"]["active_leases_count"],
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    })
    write_json_atomic(POOL_LATEST_DIR / "persistent_worker_pool_utilization.json", _utilization_payload(state))
    write_json_atomic(POOL_PUBLIC_DIR / "persistent_worker_pool_utilization.json", _utilization_payload(state))
    write_json_atomic(POOL_LATEST_DIR / "persistent_worker_pool_enablement_status.json", state)
    write_json_atomic(POOL_PUBLIC_DIR / "persistent_worker_pool_enablement_status.json", state)
    write_json_atomic(POOL_LATEST_DIR / "operator_dashboard_payload.json", _operator_payload(state))
    write_json_atomic(POOL_PUBLIC_DIR / "operator_dashboard_payload.json", _operator_payload(state))
    (POOL_LATEST_DIR / "GO_NO_GO.md").write_text(state["marker"] + "\n", encoding="utf-8")
    (POOL_LATEST_DIR / "V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_REPORT.md").write_text(
        _render_report(state), encoding="utf-8",
    )


def _utilization_payload(state: dict[str, Any]) -> dict[str, Any]:
    ps = state["pool_status"]
    return {
        "schema_version": "v2_closed_loop_persistent_worker_pool_utilization_v1",
        "generated_utc": utc_iso(),
        "worker_count_total": ps["worker_count_total"],
        "worker_count_active": ps["worker_count_active"],
        "worker_count_busy": ps["worker_count_busy"],
        "worker_count_idle_ready": ps["worker_count_idle_ready"],
        "active_lane_count": ps["active_lane_count"],
        "active_claude_workers": ps["active_claude_workers"],
        "active_codex_workers": ps["active_codex_workers"],
        "current_automatable_count": ps["current_automatable_count"],
        "current_automatable_count_by_lane": ps["current_automatable_count_by_lane"],
        "active_lane_shortfall_reason": ps["active_lane_shortfall_reason"],
        "current_task_assignments": ps["current_task_assignments"],
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }


def _operator_payload(state: dict[str, Any]) -> dict[str, Any]:
    ps = state["pool_status"]
    return {
        "schema_version": "v2_closed_loop_persistent_worker_pool_operator_payload_v1",
        "generated_utc": utc_iso(),
        "go_no_go": state["marker"],
        "marker": state["marker"],
        "ready": state["ready"],
        "blockers": state["blockers"],
        "active_lane_count": ps["active_lane_count"],
        "active_claude_workers": ps["active_claude_workers"],
        "active_codex_workers": ps["active_codex_workers"],
        "worker_count_total": ps["worker_count_total"],
        "worker_count_busy": ps["worker_count_busy"],
        "worker_count_idle_ready": ps["worker_count_idle_ready"],
        "current_automatable_count": ps["current_automatable_count"],
        "current_automatable_count_by_lane": ps["current_automatable_count_by_lane"],
        "active_lane_shortfall_reason": ps["active_lane_shortfall_reason"],
        "current_task_assignments": ps["current_task_assignments"],
        "systemd": state.get("systemd"),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
        "next_action": (
            "Persistent worker pool READY — daemons are alive and beating."
            if state["ready"] else
            f"Persistent worker pool BLOCKED — {state['blockers'][0] if state['blockers'] else 'unknown'}."
        ),
    }


def _render_report(state: dict[str, Any]) -> str:
    ps = state["pool_status"]
    sys_info = state.get("systemd") or {}
    verif = sys_info.get("verification") or {}
    lines = [
        "# V2 Closed-Loop Persistent Worker Pool Report",
        "",
        f"Marker: `{state['marker']}`",
        f"Generated: {state['generated_utc']}",
        "",
        "## Worker Pool Utilization",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| worker_count_total | {ps['worker_count_total']} |",
        f"| worker_count_active | {ps['worker_count_active']} |",
        f"| worker_count_busy | {ps['worker_count_busy']} |",
        f"| worker_count_idle_ready | {ps['worker_count_idle_ready']} |",
        f"| active_lane_count | {ps['active_lane_count']} |",
        f"| active_claude_workers | {ps['active_claude_workers']} |",
        f"| active_codex_workers | {ps['active_codex_workers']} |",
        f"| current_automatable_count | {ps['current_automatable_count']} |",
        f"| active_lane_shortfall_reason | {ps['active_lane_shortfall_reason']} |",
        f"| blocker | {ps['blocker']} |",
        "",
        "## Workers (fresh heartbeat only)",
        "",
        "| worker_id | lane_type | pid | state | current_task_id | last_heartbeat |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for hb in ps["heartbeats"]:
        if not pool.worker_is_active(hb):
            continue
        lines.append(
            f"| {hb.get('worker_id')} | {hb.get('lane_type')} | "
            f"{hb.get('pid')} | {hb.get('state')} | "
            f"{hb.get('current_task_id')} | {hb.get('last_heartbeat')} |"
        )
    lines.extend([
        "",
        "## Current Task Assignments",
        "",
        "| worker_id | task_id | lane_type | file_lock_group | leased_at |",
        "| --- | --- | --- | --- | --- |",
    ])
    for a in ps["current_task_assignments"]:
        lines.append(
            f"| {a['worker_id']} | {a['task_id']} | {a['lane_type']} | "
            f"{a.get('file_lock_group')} | {a.get('leased_at')} |"
        )
    if verif:
        lines.extend([
            "",
            "## Systemd Units",
            "",
            "| unit | is-enabled | is-active |",
            "| --- | --- | --- |",
        ])
        for unit, info in verif.items():
            lines.append(
                f"| {unit} | {info.get('is_enabled', {}).get('stdout')} | "
                f"{info.get('is_active', {}).get('stdout')} |"
            )
    lines.extend([
        "",
        "## Blockers",
        "",
        *([f"- {b}" for b in state.get("blockers") or []] or ["- (none)"]),
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
    ])
    return "\n".join(lines)


# ----------------------------- run ----------------------------- #


def run_once(
    *,
    install_systemd: bool,
    enable_systemd: bool,
    direct_spawn: bool,
    target_claude: int,
    target_codex: int,
    wait_seconds: int,
) -> dict[str, Any]:
    ensure_dirs()
    ensure_dirs_for_outputs()

    systemd_info: dict[str, Any] = {}
    if install_systemd or enable_systemd:
        systemd_info = install_units(
            install=install_systemd,
            enable=enable_systemd,
            claude_instances=list(range(1, target_claude + 1)),
            codex_instances=list(range(1, target_codex + 1)),
        )

    direct_spawn_info: dict[str, Any] = {}
    if direct_spawn:
        direct_spawn_info = direct_spawn_workers(target_claude, target_codex)

    # Give workers time to write their first heartbeat.
    if wait_seconds > 0:
        time.sleep(wait_seconds)

    # Fire the pool maintainer once (no spawn) so the status snapshot
    # is fresh and stale leases get a reclaim breadcrumb.
    pool_status = pool.run_pool_once(
        target_claude=target_claude,
        target_codex=target_codex,
        spawn=False,
        reclaim=True,
    )

    # Build the GO_NO_GO state.
    blockers: list[str] = []
    if systemd_info.get("errors"):
        blockers.append("SYSTEMD_UNIT_INSTALL_OR_ENABLE_ERROR")
    verification = systemd_info.get("verification") or {}
    if enable_systemd and verification:
        inactive = [
            unit for unit, info in verification.items()
            if (info.get("is_active") or {}).get("stdout") not in ("active",)
        ]
        if inactive:
            blockers.append("SYSTEMD_WORKER_UNITS_NOT_ACTIVE")
    if pool_status["blocker"]:
        blockers.append(pool_status["blocker"])
    if (pool_status.get("reclaim") or {}).get("second_time"):
        blockers.append("SECOND_STALE_LEASE_REQUIRES_TAKEOVER_OR_OPERATOR_REMEDIATION")
    # Executor preflight (each worker reports its own blocker; here we
    # aggregate so the marker is honest if all workers are blocked).
    blocked_claude_executor = [
        hb for hb in pool_status["heartbeats"]
        if hb.get("lane_type") == pool.LANE_TYPE_CLAUDE
        and hb.get("state") == "blocked_executor"
        and pool.worker_is_active(hb)
    ]
    claude_work = pool_status["current_automatable_count_by_lane"].get(
        pool.LANE_TYPE_CLAUDE, 0
    )
    if (
        claude_work > 0
        and pool_status["active_claude_workers"] > 0
        and len(blocked_claude_executor) >= pool_status["active_claude_workers"]
    ):
        blockers.append("CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED")
    blocked_codex_executor = [
        hb for hb in pool_status["heartbeats"]
        if hb.get("lane_type") == pool.LANE_TYPE_CODEX
        and hb.get("state") == "blocked_executor"
        and pool.worker_is_active(hb)
    ]
    codex_work = (
        pool_status["current_automatable_count_by_lane"].get(pool.LANE_TYPE_CODEX, 0)
        + pool_status["current_automatable_count_by_lane"].get(pool.LANE_TYPE_TAKEOVER, 0)
    )
    if (
        codex_work > 0
        and pool_status["active_codex_workers"] > 0
        and len(blocked_codex_executor) >= pool_status["active_codex_workers"]
    ):
        blockers.append("CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED")

    ready = not blockers
    marker = (
        "V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_READY"
        if ready else
        "V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_BLOCKED"
    )

    state = {
        "schema_version": "v2_closed_loop_persistent_worker_pool_enablement_status_v1",
        "generated_utc": utc_iso(),
        "go_no_go": marker,
        "marker": marker,
        "ready": ready,
        "blockers": blockers,
        "target_claude_workers": target_claude,
        "target_codex_workers": target_codex,
        "wait_seconds": wait_seconds,
        "systemd": systemd_info,
        "direct_spawn": direct_spawn_info,
        "pool_status": pool_status,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    emit_outputs(state)
    return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--install-systemd", action="store_true", default=False)
    p.add_argument("--enable-systemd", action="store_true", default=False)
    p.add_argument("--direct-spawn", action="store_true", default=False,
                   help="Spawn worker daemons directly via Popen (fallback when systemd --user is unavailable).")
    p.add_argument("--target-claude", type=int, default=pool.DEFAULT_MAX_CLAUDE_WORKERS)
    p.add_argument("--target-codex", type=int, default=pool.DEFAULT_MAX_CODEX_WORKERS)
    p.add_argument("--wait-seconds", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    state = run_once(
        install_systemd=args.install_systemd,
        enable_systemd=args.enable_systemd,
        direct_spawn=args.direct_spawn,
        target_claude=args.target_claude,
        target_codex=args.target_codex,
        wait_seconds=args.wait_seconds,
    )
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        ps = state["pool_status"]
        print(json.dumps({
            "marker": state["marker"],
            "ready": state["ready"],
            "blockers": state["blockers"],
            "active_lane_count": ps["active_lane_count"],
            "active_claude_workers": ps["active_claude_workers"],
            "active_codex_workers": ps["active_codex_workers"],
            "current_automatable_count": ps["current_automatable_count"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
