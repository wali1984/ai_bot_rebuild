#!/usr/bin/env python3
"""Native trainer autonomous-recovery watchdog (paper/control-plane; never live).

Operator directive 2026-07-24: no human gate for native-trainer operation.
Claude Code owns the native trainer; this watchdog keeps it alive without any
manual authorization step. It recovers BOTH failure modes that leave the trainer
not-actually-training:

1. DEAD/inactive service — e.g. the process was SIGTERM'd. systemd shows
   inactive/dead with a stale status file, which the freshness-based
   self-healing supervisor misses. (This left it down ~75 min on 2026-07-24.)
   The watchdog starts it unless the durable deliberate-stop registry holds it.
2. Sticky known-transient torn-read failure — a legacy immutable=1 read race
   can surface ``FeatureSnapshotReadbackError``.  Other FAIL_CLOSED states are
   evidence or contract failures and must remain visible for repair; restarting
   them would only discard the diagnostic and repeat the unsafe input.

Safety: paper-only, non-promotable trainer. Places no orders, changes no
leverage/margin, never enables live. Rate-limited; honors an operator
STOP_MARKER so auto-recovery can be paused for debugging.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path

SERVICE = "ai-bot-v2-native-cuda-trainer-persistent.service"
DELIBERATELY_STOPPED_FILE = Path(
    "/home/wali/Desktop/AI BOT REBUILD/claude_worklog/self_healing/"
    "deliberately_stopped_units.txt"
)
STATUS_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/status.json"
)
STATE_PATH = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/"
    "fail_closed_watchdog_state.json"
)
# Operator pause switch for the watchdog itself (NOT a human gate on the trainer;
# a debugging off-switch for auto-recovery).
STOP_MARKER = Path(
    "/home/wali/ai_bot_local_data/v2_native_trainer/local_profiled_research_v1/"
    "fail_closed_watchdog.stop"
)

FAIL_CLASSIFICATIONS = {"LOCAL_PROFILED_RESEARCH_FAIL_CLOSED"}
KNOWN_TRANSIENT_TORN_READ_FRAGMENTS = (
    "FeatureSnapshotReadbackError",
)

GRACE_SECONDS = 300          # FAIL_CLOSED must persist this long before acting
MIN_RESTART_INTERVAL = 600   # rate limit: at most one restart per 10 min


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


def _service_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", SERVICE],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return True  # fail safe: don't thrash if systemctl is unavailable


def _deliberate_stop_reason() -> str | None:
    """Return a fail-closed reason when the service must not be restarted."""

    try:
        marker_stat = os.lstat(DELIBERATELY_STOPPED_FILE)
    except OSError:
        return "deliberately_stopped_registry_unavailable"
    if (
        not stat.S_ISREG(marker_stat.st_mode)
        or marker_stat.st_nlink != 1
        or marker_stat.st_uid != os.geteuid()
        or marker_stat.st_size > 1024 * 1024
    ):
        return "deliberately_stopped_registry_invalid"
    try:
        units: set[str] = set()
        for line in DELIBERATELY_STOPPED_FILE.read_text(encoding="utf-8").splitlines():
            unit = line.strip()
            if not unit or unit.startswith("#"):
                continue
            if not unit.endswith(".service") or any(character.isspace() for character in unit):
                return "deliberately_stopped_registry_invalid"
            units.add(unit)
    except OSError:
        return "deliberately_stopped_registry_unreadable"
    return "service_deliberately_stopped" if SERVICE in units else None


def _restart(state: dict, reason: str) -> int:
    try:
        subprocess.run(
            ["systemctl", "--user", "reset-failed", SERVICE],
            timeout=30, capture_output=True, text=True,
        )
        subprocess.run(
            ["systemctl", "--user", "restart", SERVICE],
            check=True, timeout=90, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"watchdog: restart FAILED ({reason}) rc={exc.returncode} stderr={exc.stderr[:200]}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"watchdog: restart error ({reason}) {type(exc).__name__}: {exc}")
        return 1
    state["last_restart"] = _now()
    state["last_restart_reason"] = reason
    state["restart_count"] = int(state.get("restart_count", 0)) + 1
    state.pop("fail_first_seen", None)
    _save_state(state)
    print(f"watchdog: restart issued OK ({reason}); total restarts={state['restart_count']}")
    return 0


def _is_known_transient_torn_read(status: dict) -> bool:
    if str(status.get("classification")) not in FAIL_CLASSIFICATIONS:
        return False
    err = status.get("error")
    blob = json.dumps(err) if err else ""
    return any(fragment in blob for fragment in KNOWN_TRANSIENT_TORN_READ_FRAGMENTS)


def main() -> int:
    if STOP_MARKER.exists():
        print("watchdog: STOP_MARKER present; standing down")
        return 0

    state = _load_json(STATE_PATH)
    now = _now()
    rate_limited = (now - float(state.get("last_restart", 0))) < MIN_RESTART_INTERVAL

    # --- failure mode 1: DEAD/inactive service (highest priority) ---
    if not _service_active():
        deliberate_stop_reason = _deliberate_stop_reason()
        if deliberate_stop_reason is not None:
            print(f"watchdog: service DEAD but held ({deliberate_stop_reason}); standing down")
            return 0
        if rate_limited:
            print("watchdog: service DEAD but rate-limited; will retry next tick")
            return 0
        return _restart(state, "service_dead_or_inactive")

    # --- failure mode 2: sticky known-transient torn read while running ---
    status = _load_json(STATUS_PATH)
    if not status:
        print("watchdog: service active, no status.json; no action")
        return 0

    if str(status.get("classification")) in FAIL_CLASSIFICATIONS and not _is_known_transient_torn_read(status):
        print("watchdog: non-transient FAIL_CLOSED; preserving evidence and standing down")
        return 0

    if not _is_known_transient_torn_read(status):
        if state.get("fail_first_seen"):
            state.pop("fail_first_seen", None)
            _save_state(state)
        print(f"watchdog: healthy ({status.get('classification')}); no action")
        return 0

    first_seen = state.get("fail_first_seen")
    if first_seen is None:
        state["fail_first_seen"] = now
        _save_state(state)
        print(f"watchdog: FAIL_CLOSED first observed ({status.get('classification')}); grace timer started")
        return 0
    persisted = now - float(first_seen)
    if persisted < GRACE_SECONDS:
        print(f"watchdog: FAIL_CLOSED {persisted:.0f}s (< {GRACE_SECONDS}s grace); waiting")
        return 0
    if rate_limited:
        print(f"watchdog: FAIL_CLOSED {persisted:.0f}s but rate-limited; waiting")
        return 0
    return _restart(state, f"fail_closed_{persisted:.0f}s")


if __name__ == "__main__":
    raise SystemExit(main())
