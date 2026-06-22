"""Continuous Spark parallel automation runner.

This runner executes safe V2 automation components in parallel on each cycle.
It is lock-aware, writes operator-visible status artifacts, and keeps live/canary
and legacy operations disabled in-process via conservative environment defaults.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_parallel_spark_automation"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_parallel_spark_automation"
    / "latest"
)
LOCK_PATH = WORKLOG_DIR / ".parallel_spark_automation_runner.lock"
STATUS_PATH = WORKLOG_DIR / "parallel_automation_status.json"
PUBLIC_STATUS_PATH = PUBLIC_DIR / "parallel_automation_status.json"
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"

SAFE_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "creates_approval_tokens": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
}

MAX_STDOUT_CHARS = 12_000


@dataclass(frozen=True)
class Lane:
    name: str
    script: str
    args: tuple[str, ...]
    required: bool = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return text[:keep] + "\n... [truncated] ...\n" + text[-keep:]


def _is_alive_pid(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as exc:  # noqa: BLE001
        if exc.errno == errno.ESRCH:
            return False
        return False
    return True


def _acquire_lock(path: Path, stale_seconds: int) -> int | None:
    now = time.time()
    payload = {
        "pid": os.getpid(),
        "started_utc": utc_now_iso(),
        "hostname": os.uname().nodename,
        "script": Path(__file__).name,
    }
    for _ in range(3):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fp.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            return os.getpid()
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                existing = {}
            pid = existing.get("pid")
            if isinstance(pid, int) and _is_alive_pid(pid):
                return None

            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0

            if now - mtime < stale_seconds:
                return None

            try:
                path.unlink()
            except OSError:
                return None

    return None


def _release_lock(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _extract_json_payload(stdout: str) -> Any | None:
    marker = stdout.strip()
    if not marker:
        return None

    try:
        return json.loads(marker)
    except Exception:  # noqa: BLE001
        pass

    # Try trailing JSON block when script may emit logs before JSON.
    start = marker.rfind("{")
    if start < 0:
        return None
    try:
        return json.loads(marker[start:])
    except Exception:  # noqa: BLE001
        return None


def _run_lane(lane: Lane, python_exec: str, env: dict[str, str], timeout: int = 180) -> dict[str, Any]:
    cmd = [python_exec, str(TOOLS_DIR / lane.script), *lane.args]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        payload = _extract_json_payload(stdout)
        return {
            "lane": lane.name,
            "command": shlex.join([str(c) for c in cmd]),
            "required": lane.required,
            "returncode": proc.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": _safe_truncate(stdout, MAX_STDOUT_CHARS),
            "stderr": _safe_truncate(stderr, MAX_STDOUT_CHARS),
            "parsed": payload,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "lane": lane.name,
            "command": shlex.join([str(c) for c in cmd]),
            "required": lane.required,
            "returncode": 124,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": _safe_truncate(exc.stdout or "", MAX_STDOUT_CHARS),
            "stderr": _safe_truncate(str(exc), MAX_STDOUT_CHARS),
            "parsed": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "lane": lane.name,
            "command": shlex.join([str(c) for c in cmd]),
            "required": lane.required,
            "returncode": 1,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": "",
            "stderr": _safe_truncate(f"runner exception: {exc}", MAX_STDOUT_CHARS),
            "parsed": None,
        }


def _lane_ready(parsed: Any, fallback_rc: int, required: bool) -> tuple[bool, str | None]:
    if not isinstance(parsed, dict):
        if required:
            return fallback_rc == 0, None
        return True, None

    if "ready" in parsed and isinstance(parsed.get("ready"), bool):
        return bool(parsed["ready"]), parsed.get("go_no_go") if not parsed.get("ready") else None

    marker = str(parsed.get("marker") or "")
    if marker:
        if marker.endswith("READY"):
            return True, None
        if marker.endswith("BLOCKED") or marker.endswith("FAIL"):
            return False, marker

    go_no_go = str(parsed.get("go_no_go") or "")
    if go_no_go and "BLOCKED" in go_no_go:
        return False, go_no_go

    if fallback_rc != 0:
        return False, "non_zero_exit"

    return True, None


def _collect_default_lanes(
    *,
    claude_lanes: int,
    codex_lanes: int,
    target_lanes: int,
) -> list[Lane]:
    return [
        Lane(
            "autonomous_no_manual_next_task_policy",
            "v2_autonomous_no_manual_next_task_policy.py",
            ("--json",),
            required=True,
        ),
        Lane(
            "mission_backlog_autoseed",
            "v2_autonomous_mission_backlog_autoseed.py",
            ("--json", "--wait-seconds", "5"),
            required=True,
        ),
        Lane(
            "closed_loop_claude_codex_executor",
            "v2_closed_loop_claude_codex_executor.py",
            (
                "--once",
                "--json",
                "--claude-lanes",
                str(claude_lanes),
                "--codex-lanes",
                str(codex_lanes),
                "--target-lanes",
                str(target_lanes),
            ),
            required=True,
        ),
        Lane(
            "mission_execution_burndown",
            "v2_autonomous_mission_execution_burndown.py",
            ("--json",),
            required=False,
        ),
    ]


def run_cycle(*, python_exec: str, lanes: list[Lane], workers: int, timeout: int, env: dict[str, str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_run_lane, lane, python_exec, env, timeout): lane
            for lane in lanes
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    blockers: list[str] = []
    ready = True
    for result in results:
        parsed = result.get("parsed")
        lane_ready, blocker = _lane_ready(
            parsed,
            result["returncode"],
            bool(result["required"]),
        )
        result["lane_ready"] = lane_ready
        result["lane_blocker"] = blocker
        if result["required"] and not lane_ready:
            ready = False
            if blocker:
                blockers.append(f"{result['lane']}:{blocker}")

    if not blockers and any(
        not result["required"] and result["lane_blocker"] and "_BLOCKED" in result["lane_blocker"]
        for result in results
    ):
        blockers.append("optional_burndown_or_blocked")

    go_no_go = "V2_PARALLEL_SPARK_AUTOMATION_READY" if ready else "V2_PARALLEL_SPARK_AUTOMATION_BLOCKED"

    return {
        "schema_version": "v2_parallel_spark_automation_status_v1",
        "generated_utc": utc_now_iso(),
        "lane_count": len(results),
        "ready": ready,
        "go_no_go": go_no_go,
        "safe_envelope": SAFE_ENVELOPE.copy(),
        "blockers": blockers,
        "lane_results": sorted(results, key=lambda row: row["lane"]),
    }


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(body, encoding="utf-8")


def cmd_status() -> int:
    if STATUS_PATH.exists():
        print(STATUS_PATH.read_text(encoding="utf-8"))
    else:
        print(json.dumps({"go_no_go": "NEVER_RAN"}, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--loop-interval-seconds", type=int, default=150)
    parser.add_argument("--max-cycles", type=int, default=0)
    parser.add_argument("--parallel-workers", type=int, default=4)
    parser.add_argument("--lane-timeout-seconds", type=int, default=180)
    parser.add_argument("--lock-stale-seconds", type=int, default=1200)
    parser.add_argument("--claude-lanes", type=int, default=3)
    parser.add_argument("--codex-lanes", type=int, default=3)
    parser.add_argument("--target-lanes", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.max_cycles < 0:
        args.max_cycles = 0
    if not args.once and not args.loop:
        args.loop = True
    return args


def main() -> int:
    args = parse_args()
    if args.status:
        return cmd_status()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}:{REPO_ROOT / 'claude_worklog/tools'}"
    )
    env["LIVE_GATE"] = "blocked_human_only"
    python_exec = sys.executable

    lanes = _collect_default_lanes(
        claude_lanes=args.claude_lanes,
        codex_lanes=args.codex_lanes,
        target_lanes=args.target_lanes,
    )

    pid = _acquire_lock(LOCK_PATH, stale_seconds=max(30, args.lock_stale_seconds))
    if pid is None:
        payload = {
            "schema_version": "v2_parallel_spark_automation_status_v1",
            "generated_utc": utc_now_iso(),
            "go_no_go": "V2_PARALLEL_SPARK_AUTOMATION_LOCKED",
            "ready": False,
            "safe_envelope": SAFE_ENVELOPE.copy(),
            "blockers": ["parallel_runner_lock_held"],
            "lane_results": [],
        }
        write_status(STATUS_PATH, payload)
        write_status(PUBLIC_STATUS_PATH, payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1

    try:
        cycle = 0
        last_payload: dict[str, Any] = {}
        interval = max(30, int(args.loop_interval_seconds))

        def step_once() -> dict[str, Any]:
            return run_cycle(
                python_exec=python_exec,
                lanes=lanes,
                workers=args.parallel_workers,
                timeout=args.lane_timeout_seconds,
                env=env,
            )

        if args.once:
            cycle += 1
            last_payload = {
                "runner": Path(__file__).name,
                "cycle": cycle,
                "runner_pid": os.getpid(),
                "mode": "once",
                **step_once(),
            }
            write_status(STATUS_PATH, last_payload)
            write_status(PUBLIC_STATUS_PATH, last_payload)
            if args.json:
                print(json.dumps(last_payload, indent=2, sort_keys=True))
            return 0 if last_payload["ready"] else 1

        max_cycles = 0 if args.max_cycles == 0 else max(1, args.max_cycles)
        while True:
            cycle += 1
            last_payload = {
                "runner": Path(__file__).name,
                "cycle": cycle,
                "runner_pid": os.getpid(),
                "mode": "loop",
                **step_once(),
            }
            write_status(STATUS_PATH, last_payload)
            write_status(PUBLIC_STATUS_PATH, last_payload)
            if args.json:
                print(json.dumps(last_payload, indent=2, sort_keys=True))

            if max_cycles and cycle >= max_cycles:
                break
            time.sleep(interval)

        return 0 if last_payload.get("ready") else 1
    finally:
        _release_lock(LOCK_PATH)


if __name__ == "__main__":
    raise SystemExit(main())
