#!/usr/bin/env python3
"""Trainer FAIL_CLOSED watchdog (paper/control-plane; never touches live).

Root cause it guards (2026-07-24): the native CUDA trainer opens its live,
concurrently-appended durable ledger with SQLite ``immutable=1``.  When a write
lands mid-read the header tears -> "file is not a database" ->
``FeatureSnapshotReadbackError`` -> ``LOCAL_PROFILED_RESEARCH_FAIL_CLOSED``.
That state is STICKY (it kept train_rows=0 for ~6 days) yet keeps a *fresh*
status heartbeat, so the freshness-based self-healing supervisor never restarts
it.  A plain ``systemctl --user restart`` clears it (verified: train_rows 0->45).

This watchdog restarts the trainer ONLY when it has been FAIL_CLOSED
continuously past a grace window, is rate-limited, and is not operator-stopped.
It is a stopgap until the proper in-code read-retry fix ships via re-commission.

Read/write boundary: reads a status.json, restarts one paper-only systemd user
service.  Places no orders, changes no leverage/margin, never enables live.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SERVICE = "ai-bot-v2-native-cuda-trainer-persistent.service"
STATUS_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/status.json"
)
STATE_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/"
    "fail_closed_watchdog_state.json"
)
# Operator kill switch: if this file exists, the watchdog does nothing.
STOP_MARKER = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/"
    "fail_closed_watchdog.stop"
)

FAIL_CLASSIFICATIONS = {"LOCAL_PROFILED_RESEARCH_FAIL_CLOSED"}
# Readback/torn-read reason fragments that specifically warrant a restart.
TORN_READ_FRAGMENTS = (
    "FeatureSnapshotReadbackError",
    "FIXED_OBSERVATION_READ_FAILED",
    "MANIFEST_BUILD_FAILED",
    "file is not a database",
    "checkpoint_provenance_unattested",
)

GRACE_SECONDS = 300          # FAIL_CLOSED must persist this long before acting
MIN_RESTART_INTERVAL = 1800  # rate limit: at most one restart per 30 min


def _now() -> float:
    return time.time()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state, indent=1))
    except Exception:
        pass


def _is_fail_closed(status: dict) -> bool:
    if str(status.get("classification")) in FAIL_CLASSIFICATIONS:
        return True
    err = status.get("error")
    blob = json.dumps(err) if err else ""
    return any(frag in blob for frag in TORN_READ_FRAGMENTS)


def main() -> int:
    if STOP_MARKER.exists():
        print("watchdog: STOP_MARKER present; standing down")
        return 0

    status = _load_json(STATUS_PATH)
    if not status:
        print("watchdog: no status.json; no action")
        return 0

    state = _load_json(STATE_PATH)
    now = _now()
    fail = _is_fail_closed(status)
    cls = status.get("classification")

    if not fail:
        # Healthy: clear the fail-first-seen marker.
        if state.get("fail_first_seen"):
            state.pop("fail_first_seen", None)
            _save_state(state)
        print(f"watchdog: healthy ({cls}); no action")
        return 0

    first_seen = state.get("fail_first_seen")
    if first_seen is None:
        state["fail_first_seen"] = now
        _save_state(state)
        print(f"watchdog: FAIL_CLOSED first observed ({cls}); starting grace timer")
        return 0

    persisted = now - float(first_seen)
    last_restart = float(state.get("last_restart", 0))
    if persisted < GRACE_SECONDS:
        print(f"watchdog: FAIL_CLOSED for {persisted:.0f}s (< {GRACE_SECONDS}s grace); waiting")
        return 0
    if now - last_restart < MIN_RESTART_INTERVAL:
        print(
            f"watchdog: FAIL_CLOSED {persisted:.0f}s but last restart "
            f"{now - last_restart:.0f}s ago (< {MIN_RESTART_INTERVAL}s); rate-limited"
        )
        return 0

    print(f"watchdog: restarting {SERVICE} (FAIL_CLOSED {persisted:.0f}s, cls={cls})")
    try:
        subprocess.run(
            ["systemctl", "--user", "restart", SERVICE],
            check=True, timeout=60, capture_output=True, text=True,
        )
        state["last_restart"] = now
        state["last_restart_reason"] = str(cls)
        state["restart_count"] = int(state.get("restart_count", 0)) + 1
        state.pop("fail_first_seen", None)
        _save_state(state)
        print(f"watchdog: restart issued OK (total restarts: {state['restart_count']})")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"watchdog: restart FAILED rc={exc.returncode} stderr={exc.stderr[:200]}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"watchdog: restart error {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
