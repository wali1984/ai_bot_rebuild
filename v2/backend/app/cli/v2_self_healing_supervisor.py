"""Freshness-based self-healing supervisor for non-ingestor V2 components.

Restarts a systemd user service when its process is DEAD or its published
heartbeat is STALE (alive-but-hung), with hard safety pins (see
``app.services.self_healing``). It never enables trading, never mutates exchange
risk parameters, never touches the exchange, and never restarts
ingestors/live/canary/legacy units.

Usage:
    -m v2.backend.app.cli.v2_self_healing_supervisor --once [--dry-run]
    -m v2.backend.app.cli.v2_self_healing_supervisor --loop --interval-seconds 60
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.self_healing.component_registry import (
    NON_INGESTOR_COMPONENTS,
    ComponentSpec,
    decide_heal_action,
    ACTION_RESTART_DEAD,
    ACTION_RESTART_STALE,
    ACTION_STALE_PENDING,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
STATUS_KEY = "v2:self_healing:status"
RESTART_LEDGER_KEY = "v2:self_healing:restart_ledger"
STALE_STREAK_KEY = "v2:self_healing:stale_streak"
MIN_STALE_OBSERVATIONS = 2
DELIBERATELY_STOPPED_KEY = "v2:self_healing:deliberately_stopped"
DELIBERATELY_STOPPED_FILE = REPO_ROOT / "claude_worklog/self_healing/deliberately_stopped_units.txt"
STATUS_FILE = REPO_ROOT / "claude_worklog/self_healing/self_healing_status.json"
RESTART_WINDOW_SECONDS = 1800  # 30 min
MAX_RESTARTS_PER_WINDOW = 3
STATUS_TTL_SECONDS = 300

_RESTART_ACTIONS = {ACTION_RESTART_DEAD, ACTION_RESTART_STALE}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def _unit_state(unit: str, now: datetime) -> dict[str, Any]:
    active = (_run(["systemctl", "--user", "is-active", unit]).stdout or "").strip() or "unknown"
    enabled = (_run(["systemctl", "--user", "is-enabled", unit]).stdout or "").strip() or "unknown"
    installed = enabled not in {"not-found", "masked"} and "not-found" not in enabled
    enabled_bool = enabled in {"enabled", "enabled-runtime", "static", "indirect", "generated", "alias"}
    active_since: float | None = None
    show = _run(["systemctl", "--user", "show", unit, "-p", "ActiveEnterTimestamp"]).stdout or ""
    ts_str = show.split("=", 1)[1].strip() if "=" in show else ""
    if ts_str and ts_str.lower() not in {"", "n/a"}:
        entered = _parse_systemd_timestamp(ts_str)
        if entered is not None:
            active_since = max(0.0, (now - entered).total_seconds())
    return {
        "active": active,
        "enabled": enabled,
        "installed": installed,
        "enabled_bool": enabled_bool,
        "active_since_seconds": active_since,
    }


def _parse_systemd_timestamp(value: str) -> datetime | None:
    # systemd format e.g. "Tue 2026-07-14 18:34:43 EDT" -> parse the date/time part.
    parts = value.split()
    if len(parts) >= 3:
        try:
            naive = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
            # systemd prints local time; treat as local and convert to UTC.
            return naive.astimezone().astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        ts = float(s)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def _heartbeat_age_seconds(client: Any, spec: ComponentSpec, now: datetime) -> float | None:
    def payload_age(payload: Any) -> float | None:
        if not isinstance(payload, dict):
            return None
        stamp = _parse_timestamp(payload.get(spec.heartbeat_field))
        if stamp is None:
            for alt in (
                "generated_utc",
                "generated_at",
                "generated_est",
                "updated_at",
                "ts",
                "timestamp",
            ):
                stamp = _parse_timestamp(payload.get(alt))
                if stamp is not None:
                    break
        if stamp is None:
            return None
        return max(0.0, (now - stamp).total_seconds())

    if spec.heartbeat_redis_key and client is not None:
        try:
            raw = client.get(spec.heartbeat_redis_key)
            redis_age = payload_age(json.loads(raw) if raw else None)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            redis_age = None
        if redis_age is not None:
            return redis_age

    file_ages: list[float] = []
    heartbeat_files = tuple(
        path
        for path in (spec.heartbeat_file, *spec.heartbeat_files)
        if path is not None
    )
    for heartbeat_file in heartbeat_files:
        fp = REPO_ROOT / heartbeat_file
        try:
            age = payload_age(json.loads(fp.read_text()))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            age = None
        if age is not None:
            file_ages.append(age)
    return min(file_ages) if file_ages else None


def _deliberately_stopped(client: Any) -> set[str]:
    units: set[str] = set()
    try:
        if DELIBERATELY_STOPPED_FILE.exists():
            for line in DELIBERATELY_STOPPED_FILE.read_text().splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    units.add(s)
    except Exception:
        pass
    if client is not None:
        try:
            units.update(client.smembers(DELIBERATELY_STOPPED_KEY) or [])
        except Exception:
            pass
    return units


def _recent_restarts(client: Any, unit: str, now: datetime) -> int:
    if client is None:
        return 0
    try:
        raw = client.get(RESTART_LEDGER_KEY)
        ledger = json.loads(raw) if raw else {}
    except Exception:
        return 0
    stamps = ledger.get(unit, []) if isinstance(ledger, dict) else []
    cutoff = now.timestamp() - RESTART_WINDOW_SECONDS
    return sum(1 for t in stamps if isinstance(t, (int, float)) and t >= cutoff)


def _record_restart(client: Any, unit: str, now: datetime) -> None:
    if client is None:
        return
    try:
        raw = client.get(RESTART_LEDGER_KEY)
        ledger = json.loads(raw) if raw else {}
        if not isinstance(ledger, dict):
            ledger = {}
        cutoff = now.timestamp() - RESTART_WINDOW_SECONDS
        stamps = [t for t in ledger.get(unit, []) if isinstance(t, (int, float)) and t >= cutoff]
        stamps.append(now.timestamp())
        ledger[unit] = stamps
        client.set(RESTART_LEDGER_KEY, json.dumps(ledger), ex=RESTART_WINDOW_SECONDS * 2)
    except Exception:
        pass


def _read_stale_streaks(client: Any) -> dict[str, int]:
    if client is None:
        return {}
    try:
        raw = client.get(STALE_STREAK_KEY)
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_stale_streaks(client: Any, streaks: dict[str, int]) -> None:
    if client is None:
        return
    try:
        client.set(STALE_STREAK_KEY, json.dumps(streaks), ex=3600)
    except Exception:
        pass


def run_once(client: Any, *, dry_run: bool, write_redis: bool) -> dict[str, Any]:
    now = _utc_now()
    stopped = _deliberately_stopped(client)
    stale_streaks = _read_stale_streaks(client)
    next_streaks: dict[str, int] = {}
    decisions: list[dict[str, Any]] = []
    action_counts: dict[str, int] = {}
    restarted: list[str] = []

    for spec in NON_INGESTOR_COMPONENTS:
        st = _unit_state(spec.unit, now)
        age = _heartbeat_age_seconds(client, spec, now)
        prior_stale_streak = int(stale_streaks.get(spec.unit, 0) or 0)
        decision = decide_heal_action(
            spec,
            installed=bool(st["installed"]),
            enabled=bool(st["enabled_bool"]),
            active_state=st["active"],
            heartbeat_age_seconds=age,
            deliberately_stopped=spec.unit in stopped,
            recent_restart_count=_recent_restarts(client, spec.unit, now),
            max_restarts_per_window=MAX_RESTARTS_PER_WINDOW,
            active_since_seconds=st["active_since_seconds"],
            consecutive_stale_count=prior_stale_streak,
            min_stale_observations=MIN_STALE_OBSERVATIONS,
        )
        # Track the consecutive-stale streak: grows while stale/pending, resets on
        # anything else (incl. a restart, so post-restart starts fresh).
        if decision.action in (ACTION_STALE_PENDING,):
            next_streaks[spec.unit] = prior_stale_streak + 1
        elif decision.action != ACTION_RESTART_STALE:
            next_streaks[spec.unit] = 0
        action_counts[decision.action] = action_counts.get(decision.action, 0) + 1
        row: dict[str, Any] = {
            "name": spec.name,
            "unit": spec.unit,
            "category": spec.category,
            "criticality": spec.criticality,
            "action": decision.action,
            "reason": decision.reason,
            "active_state": st["active"],
            "enabled_state": st["enabled"],
            "heartbeat_age_seconds": round(age, 1) if age is not None else None,
            "max_staleness_seconds": spec.max_staleness_seconds,
        }
        if decision.action in _RESTART_ACTIONS:
            if dry_run:
                row["remediation"] = "dry_run"
            else:
                # Clear any StartLimitBurst "failed" latch first.  Once a unit
                # trips the start-limit it stays in the failed state, and a
                # plain `restart` is rejected ("start request repeated too
                # quickly") until the failure is reset — so without this a
                # crash-looped unit sits dead indefinitely despite the
                # supervisor running.  reset-failed is a harmless no-op on a
                # healthy unit, so it is safe to run unconditionally here.
                reset = _run(["systemctl", "--user", "reset-failed", spec.unit])
                proc = _run(["systemctl", "--user", "restart", spec.unit])
                row["remediation"] = {
                    "returncode": proc.returncode,
                    "reset_failed_returncode": reset.returncode,
                    "stderr": proc.stderr.strip()[-500:],
                }
                if proc.returncode == 0:
                    restarted.append(spec.unit)
                    _record_restart(client, spec.unit, now)
        decisions.append(row)

    _write_stale_streaks(client, next_streaks)

    payload = {
        "schema_version": "v2_self_healing_supervisor_status_v1",
        "generated_utc": _iso(now),
        "component_count": len(NON_INGESTOR_COMPONENTS),
        "action_counts": action_counts,
        "restarted_units": restarted,
        "restarted_count": len(restarted),
        "dry_run": bool(dry_run),
        "decisions": decisions,
        "live_gate": "blocked_human_only",
        "routes_to_exchange": False,
        "places_exchange_action": False,
        "mutates_exchange_risk_params": False,
    }
    if write_redis and client is not None:
        try:
            client.set(STATUS_KEY, json.dumps(payload, default=str), ex=STATUS_TTL_SECONDS)
        except Exception:
            pass
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    except Exception:
        pass
    return payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval-seconds", type=float, default=60.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-write-redis", action="store_true")
    args = p.parse_args(argv)

    client = _connect_redis()
    write_redis = not args.no_write_redis

    if args.loop:
        while True:
            payload = run_once(client, dry_run=args.dry_run, write_redis=write_redis)
            print(json.dumps({k: payload[k] for k in ("generated_utc", "action_counts", "restarted_units")}))
            time.sleep(max(5.0, float(args.interval_seconds)))
    payload = run_once(client, dry_run=args.dry_run, write_redis=write_redis)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
