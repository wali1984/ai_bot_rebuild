#!/usr/bin/env python3
"""Publish the V2 monthly 10k net-profit target monitor artifacts.

Read-only/paper-only evidence publisher. It never submits orders, never calls
test-order, never changes leverage/margin, and never writes Redis.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.profit_target_monitor import (  # noqa: E402
    READY,
    ProfitTargetMonitorPaths,
    publish_all,
)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_loop_lock(repo_root: Path) -> tuple[bool, Path, int | None]:
    paths = ProfitTargetMonitorPaths(
        repo_root=repo_root,
        public_root=repo_root / "v2/frontend/public",
    )
    pid_file = paths.operator_dir / "monitor.pid"
    try:
        existing_text = pid_file.read_text(encoding="utf-8").strip()
        existing_pid = int(existing_text) if existing_text else 0
    except (OSError, ValueError):
        existing_pid = 0
    if existing_pid and existing_pid != os.getpid() and _pid_is_alive(existing_pid):
        return False, pid_file, existing_pid
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return True, pid_file, None


def _publish_once(repo_root: Path) -> tuple[int, dict[str, Any]]:
    payloads = publish_all(
        ProfitTargetMonitorPaths(
            repo_root=repo_root,
            public_root=repo_root / "v2/frontend/public",
        )
    )
    dashboard = payloads["operator_dashboard_payload.json"]
    output = {
        "gate": dashboard.get("gate"),
        "generated_est": dashboard.get("generated_est"),
        "goal_status": dashboard.get("goal_status"),
        "trainer_capability_status": dashboard.get("trainer_capability_status"),
        "hedging_status": dashboard.get("hedging_status"),
        "goal_simulation_status": dashboard.get("goal_simulation_status"),
        "paper_equity": dashboard.get("paper_equity"),
        "paper_run_rate_monthly_pnl": dashboard.get("paper_run_rate_monthly_pnl"),
        "required_monthly_return_pct": dashboard.get("required_monthly_return_pct"),
        "live_available_margin": dashboard.get("live_available_margin"),
        "live_target_executable": dashboard.get("live_target_executable"),
        "adaptive_leverage_margin_selection_status": dashboard.get("adaptive_leverage_margin_selection_status"),
        "paper_recommended_leverage": dashboard.get("paper_recommended_leverage"),
        "live_leverage_margin_action_status": dashboard.get("live_leverage_margin_action_status"),
        "blockers": dashboard.get("blockers"),
        "safety": dashboard.get("safety"),
    }
    return (0 if dashboard.get("gate") == READY else 2), output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_monthly_10k_profit_target_monitor")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--loop", action="store_true", help="continuously publish read-only monitor artifacts")
    parser.add_argument("--interval-seconds", type=float, default=300.0)
    parser.add_argument("--max-iterations", type=int, default=0, help="0 means unlimited when --loop is set")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.loop and args.max_iterations <= 0:
        acquired, pid_file, existing_pid = _acquire_loop_lock(repo_root)
        if not acquired:
            print(
                json.dumps(
                    {
                        "status": "MONITOR_LOOP_ALREADY_RUNNING",
                        "pid_file": str(pid_file),
                        "existing_pid": existing_pid,
                        "current_pid": os.getpid(),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                flush=True,
            )
            return 0
    interval_seconds = max(1.0, float(args.interval_seconds))
    iterations = 0
    latest_code = 0
    while True:
        latest_code, output = _publish_once(repo_root)
        print(json.dumps(output, indent=2, sort_keys=True), flush=True)
        iterations += 1
        if not args.loop or (args.max_iterations > 0 and iterations >= args.max_iterations):
            return latest_code
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
