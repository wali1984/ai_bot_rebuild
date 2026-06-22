"""V2 system observability status publisher.

Read-only replacement for the safe parts of the legacy Phase 0.5 monitors:

* vpn_monitor.py -> route/interface evidence only, no reconnect
* system_telegram_monitor.py -> credential-presence evidence only, no send
* monitor_system_memory.py / scripts/memory_monitor.py -> memory telemetry
* monitor_trainer_predictions.py -> V2 prediction key coverage

Writes only V2 status artifacts and a V2 Redis heartbeat. It never sends
Telegram messages, restarts VPN/networking, trims Redis, calls exchange APIs,
or writes legacy Redis keys.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKER_ID = "v2_system_observability_status_publisher"
V2_REDIS_PREFIX = "v2:"
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_system_observability/latest/v2_system_observability_status.json"
)
LOCAL_STATUS_PATH = (
    REPO_ROOT
    / "v2/runtime/v2_system_observability/latest/v2_system_observability_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _safe_set_json(redis_client: Any, key: str, payload: dict[str, Any], ttl_seconds: int) -> bool:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True), ex=int(ttl_seconds))
        return True
    except Exception:
        return False


def _safe_cmd(cmd: list[str], *, timeout: float = 3.0) -> tuple[int | None, str, str]:
    binary = shutil.which(cmd[0])
    if binary is None:
        return None, "", "binary_not_found"
    try:
        result = subprocess.run(
            [binary, *cmd[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "", str(exc)
    return int(result.returncode), result.stdout.strip(), result.stderr.strip()


def _read_meminfo() -> dict[str, Any]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            name, rest = line.split(":", 1)
            parts = rest.strip().split()
            if not parts:
                continue
            values[name] = int(parts[0])
    except Exception:
        return {"available": False, "classification": "MEMINFO_UNAVAILABLE"}
    total_kib = values.get("MemTotal")
    available_kib = values.get("MemAvailable")
    if not total_kib or available_kib is None:
        return {"available": False, "classification": "MEMINFO_INCOMPLETE"}
    used_pct = max(0.0, min(100.0, (1.0 - (available_kib / total_kib)) * 100.0))
    if used_pct >= 95.0:
        classification = "MEMORY_CRITICAL"
    elif used_pct >= 90.0:
        classification = "MEMORY_ELEVATED"
    elif used_pct >= 85.0:
        classification = "MEMORY_WARN"
    else:
        classification = "MEMORY_OK"
    return {
        "available": True,
        "classification": classification,
        "total_mib": round(total_kib / 1024.0, 2),
        "available_mib": round(available_kib / 1024.0, 2),
        "used_percent": round(used_pct, 3),
        "thresholds_percent": {"warn": 85, "elevated": 90, "critical": 95},
    }


def _redis_memory(redis_client: Any) -> dict[str, Any]:
    if redis_client is None:
        return {"available": False, "classification": "REDIS_UNAVAILABLE"}
    try:
        info = redis_client.info("memory")
    except Exception as exc:
        return {"available": False, "classification": "REDIS_MEMORY_INFO_UNAVAILABLE", "error_type": type(exc).__name__}
    used = info.get("used_memory")
    maxmemory = info.get("maxmemory")
    used_pct = None
    if isinstance(used, int) and isinstance(maxmemory, int) and maxmemory > 0:
        used_pct = round((used / maxmemory) * 100.0, 3)
    return {
        "available": True,
        "classification": "REDIS_MEMORY_OK",
        "used_memory": used,
        "used_memory_human": info.get("used_memory_human"),
        "maxmemory": maxmemory,
        "maxmemory_human": info.get("maxmemory_human"),
        "maxmemory_policy": info.get("maxmemory_policy"),
        "used_percent_of_maxmemory": used_pct,
    }


def _vpn_status() -> dict[str, Any]:
    code, stdout, stderr = _safe_cmd(["ip", "route", "get", "1.1.1.1"])
    text = stdout.lower()
    interface = None
    parts = stdout.split()
    if "dev" in parts:
        idx = parts.index("dev")
        if idx + 1 < len(parts):
            interface = parts[idx + 1]
    vpn_like = bool(interface and (interface.startswith("tun") or interface.startswith("ppp") or interface.startswith("wg")))
    return {
        "classification": "VPN_INTERFACE_DETECTED" if vpn_like else "VPN_NOT_DETECTED_OR_NOT_REQUIRED",
        "route_probe_exit_code": code,
        "default_route_interface": interface,
        "vpn_like_interface": vpn_like,
        "route_mentions_vpn": "vpn" in text,
        "probe_error": stderr[:160] if stderr else None,
        "operator_action_required_for_reconnect": True,
        "vpn_restart_attempted": False,
    }


def _telegram_status() -> dict[str, Any]:
    token_present = bool(os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN"))
    chat_present = bool(os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_ADMIN_CHAT_ID"))
    return {
        "classification": "TELEGRAM_CONFIG_PRESENT_NO_SEND" if token_present and chat_present else "TELEGRAM_CONFIG_MISSING_OR_OPERATOR_REQUIRED",
        "token_present": token_present,
        "chat_id_present": chat_present,
        "message_send_attempted": False,
        "raw_secret_emitted": False,
    }


def _prediction_status(redis_client: Any) -> dict[str, Any]:
    if redis_client is None:
        return {"classification": "REDIS_UNAVAILABLE", "prediction_key_count": 0}
    counts_by_timeframe: dict[str, int] = {}
    sidecar_count = 0
    total = 0
    try:
        keys = list(redis_client.scan_iter(match="v2:prediction:*", count=1000))
    except Exception:
        return {"classification": "PREDICTION_SCAN_FAILED", "prediction_key_count": 0}
    for key in keys:
        if not isinstance(key, str):
            continue
        total += 1
        parts = key.split(":")
        if len(parts) >= 5 and parts[2] == "rl_core":
            sidecar_count += 1
            timeframe = parts[-1]
        else:
            timeframe = parts[-1] if len(parts) >= 4 else "unknown"
        counts_by_timeframe[timeframe] = counts_by_timeframe.get(timeframe, 0) + 1
    return {
        "classification": "TRAINER_PREDICTIONS_PRESENT" if total else "TRAINER_PREDICTIONS_MISSING",
        "prediction_key_count": total,
        "rl_core_sidecar_prediction_count": sidecar_count,
        "prediction_counts_by_timeframe": dict(sorted(counts_by_timeframe.items())),
    }


def _process_status() -> dict[str, Any]:
    code, stdout, stderr = _safe_cmd(["systemctl", "--user", "list-units", "ai-bot-v2-*", "--type=service", "--all", "--no-pager", "--no-legend"], timeout=8.0)
    active = 0
    failed = 0
    loaded = 0
    if stdout:
        for line in stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            loaded += 1
            if len(parts) > 2 and parts[2] == "active":
                active += 1
            if " failed " in f" {line} ":
                failed += 1
    return {
        "classification": "V2_PROCESS_STATUS_OK" if code == 0 and failed == 0 else "V2_PROCESS_STATUS_DEGRADED",
        "systemctl_exit_code": code,
        "v2_units_seen": loaded,
        "v2_units_active": active,
        "v2_units_failed": failed,
        "probe_error": stderr[:160] if stderr else None,
    }


def run_once(*, ttl_seconds: int = 300) -> dict[str, Any]:
    redis_client = _connect_redis()
    memory = _read_meminfo()
    redis_memory = _redis_memory(redis_client)
    vpn = _vpn_status()
    telegram = _telegram_status()
    predictions = _prediction_status(redis_client)
    processes = _process_status()
    degraded = [
        name
        for name, section in {
            "memory": memory,
            "redis_memory": redis_memory,
            "processes": processes,
        }.items()
        if isinstance(section, dict)
        and str(section.get("classification", "")).endswith(("WARN", "ELEVATED", "CRITICAL", "DEGRADED", "UNAVAILABLE"))
    ]
    payload: dict[str, Any] = {
        "schema_version": "v2_system_observability_status_v1",
        "worker_id": WORKER_ID,
        "generated_utc": _utc_iso(),
        "classification": "V2_SYSTEM_OBSERVABILITY_OK" if not degraded else "V2_SYSTEM_OBSERVABILITY_DEGRADED",
        "degraded_sections": degraded,
        "memory": memory,
        "redis_memory": redis_memory,
        "vpn": vpn,
        "telegram": telegram,
        "trainer_predictions": predictions,
        "v2_processes": processes,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "telegram_message_send_attempted": False,
        "vpn_restart_attempted": False,
        "redis_trim_attempted": False,
    }
    _safe_set_json(redis_client, "v2:system:observability:heartbeat", payload, ttl_seconds)
    return payload


def _write_payload(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    for path in (PUBLIC_STATUS_PATH, LOCAL_STATUS_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--ttl-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once(ttl_seconds=args.ttl_seconds)
            _write_payload(payload)
            time.sleep(max(5, int(args.interval_seconds)))
    payload = run_once(ttl_seconds=args.ttl_seconds)
    _write_payload(payload)
    print(json.dumps({"classification": payload["classification"], "degraded_sections": payload["degraded_sections"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
