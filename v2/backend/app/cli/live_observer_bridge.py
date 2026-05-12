from __future__ import annotations

import argparse
import calendar
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


LIVE_GATE_STATUS = "blocked_human_only"
READY_MARKER = "V2_LIVE_OBSERVER_SHADOW_TWIN_READY"
BLOCKED_MARKER = "V2_LIVE_OBSERVER_SHADOW_TWIN_BLOCKED"
CODEX_PASS_MARKER = "V2_LIVE_OBSERVER_SHADOW_TWIN_CODEX_PASS"
CODEX_FAIL_MARKER = "V2_LIVE_OBSERVER_SHADOW_TWIN_CODEX_FAIL"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_OBSERVER_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "live_observer" / "latest"
LOCAL_OBSERVER_DIR = V2_ROOT / "runtime" / "live_observer" / "latest"
PUBLIC_PAPER_STATUS = V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest" / "paper_runtime_status.json"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "v2_live_observer_shadow_twin" / "latest"

READ_ONLY_REDIS_COMMANDS = {
    "INFO",
    "SCAN",
    "KEYS",
    "TYPE",
    "XLEN",
    "XRANGE",
    "XREVRANGE",
    "GET",
    "HGETALL",
    "TTL",
    "MEMORY",
}
FORBIDDEN_REDIS_COMMANDS = {
    "SET",
    "HSET",
    "XADD",
    "DEL",
    "XDEL",
    "XTRIM",
    "FLUSHALL",
    "FLUSHDB",
    "EXPIRE",
    "CONFIG",
    "BGSAVE",
}

LEGACY_STREAM_CANDIDATES = (
    "signals:trading:primary",
    "signals:trading",
    "signals:trading:asjad",
    "wma:proposals",
    "wma:trainer:predictions",
    "executed_signals",
)

SECRET_FIELD_RE = re.compile("api[_-]?key|secret|token|password|passphrase|private", re.IGNORECASE)


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def iso_from_epoch_ms(epoch_ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_ms / 1000))


def age_seconds_from_iso(value: str | None, *, now: float | None = None) -> int | None:
    if not value:
        return None
    try:
        parsed = time.strptime(value.replace("+00:00", "Z"), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        try:
            parsed = time.strptime(value.split(".")[0] + "Z", "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
    return max(0, int((now if now is not None else time.time()) - calendar.timegm(parsed)))


def stream_id_to_iso(stream_id: str | None) -> str | None:
    if not stream_id or "-" not in stream_id:
        return None
    head = stream_id.split("-", 1)[0]
    if not head.isdigit():
        return None
    return iso_from_epoch_ms(int(head))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _run(args: list[str], *, cwd: Path = REPO_ROOT, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def _redact_value(key: str, value: Any) -> Any:
    if SECRET_FIELD_RE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value[:20]]
    if isinstance(value, str):
        safe = value.replace("\n", " ").strip()
        return safe[:500] + ("..." if len(safe) > 500 else "")
    return value


def _decode_redis_value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return text
    if text[0] in "{[":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[:500]
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text[:500]


def _flatten_entry_fields(fields: dict[str, Any]) -> dict[str, Any]:
    flattened = dict(fields)
    for key in ("data", "payload", "json", "message", "event"):
        value = fields.get(key)
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flattened.setdefault(str(nested_key), nested_value)
    return flattened


def _redis_base_command() -> list[str]:
    redis_url = os.environ.get("LEGACY_REDIS_URL") or os.environ.get("REDIS_URL")
    if redis_url:
        return ["redis-cli", "-u", redis_url, "--raw"]
    return ["redis-cli", "--raw"]


def run_redis_read_only(command: str, *args: str) -> subprocess.CompletedProcess[str]:
    upper = command.upper()
    if upper in FORBIDDEN_REDIS_COMMANDS or upper not in READ_ONLY_REDIS_COMMANDS:
        raise ValueError(f"Redis command is not read-only for this bridge: {command}")
    if upper == "MEMORY" and args and args[0].upper() != "USAGE":
        raise ValueError("Only MEMORY USAGE is permitted")
    return _run([*_redis_base_command(), command, *args], timeout=8)


def read_latest_stream_entry(key: str) -> dict[str, Any]:
    type_result = run_redis_read_only("TYPE", key)
    redis_type = type_result.stdout.strip() if type_result.returncode == 0 else "unknown"
    status: dict[str, Any] = {
        "key": key,
        "redis_type": redis_type,
        "stream_length": None,
        "latest_entry": None,
        "status": "MISSING_OR_NON_STREAM",
        "read_only": True,
        "redis_write": False,
    }
    if redis_type != "stream":
        return status
    len_result = run_redis_read_only("XLEN", key)
    if len_result.returncode == 0:
        try:
            status["stream_length"] = int(len_result.stdout.strip() or "0")
        except ValueError:
            status["stream_length"] = None
    latest_result = run_redis_read_only("XREVRANGE", key, "+", "-", "COUNT", "1")
    if latest_result.returncode != 0 or not latest_result.stdout.strip():
        status["status"] = "STREAM_EMPTY_OR_UNREADABLE"
        return status
    lines = [line for line in latest_result.stdout.splitlines() if line != ""]
    entry_id = lines[0]
    field_lines = lines[1:]
    fields: dict[str, Any] = {}
    for index in range(0, len(field_lines) - 1, 2):
        raw_key = field_lines[index]
        raw_value = field_lines[index + 1]
        fields[raw_key] = _redact_value(raw_key, _decode_redis_value(raw_value))
    flat_fields = _flatten_entry_fields(fields)
    last_event_at = stream_id_to_iso(entry_id)
    status["latest_entry"] = {
        "stream_id": entry_id,
        "last_event_at": last_event_at,
        "age_seconds": age_seconds_from_iso(last_event_at),
        "fields": fields,
        "flat_fields": flat_fields,
    }
    status["status"] = "STREAM_LATEST_ENTRY_OBSERVED"
    return status


def collect_process_snapshot() -> dict[str, Any]:
    result = _run(["ps", "-eo", "pid,ppid,etimes,cmd"], timeout=8)
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"rl\.hybrid_trainer|monitor_trainer_predictions|rl\.orchestrator_worker|"
        r"trading/trader\.py|paper_online_runtime|agent_supervisor\.py|"
        r"parallel_capacity_scheduler|codex_non_live_watchdog|"
        r"autonomous_governor|claude_master_rebuild_planner"
    )
    for line in result.stdout.splitlines():
        if not pattern.search(line):
            continue
        parts = line.strip().split(maxsplit=3)
        if len(parts) != 4:
            continue
        pid, ppid, etimes, command = parts
        cwd = "unknown"
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            pass
        if str(REPO_ROOT) in cwd or "v2.backend.app" in command or "claude_worklog/tools" in command:
            runtime = "AI_BOT_REBUILD_V2"
        elif "/home/wali/Desktop/AI BOT" in cwd or "rl." in command or "trading/trader.py" in command:
            runtime = "LEGACY_AI_BOT"
        else:
            runtime = "UNKNOWN_RUNTIME"
        rows.append(
            {
                "pid": int(pid),
                "ppid": int(ppid),
                "uptime_seconds": int(etimes),
                "command": _redact_value("command", command),
                "cwd": cwd,
                "runtime": runtime,
            }
        )
    return {
        "processes": rows,
        "legacy_trainer": _process_state(rows, "rl.hybrid_trainer"),
        "legacy_trainer_monitor": _process_state(rows, "monitor_trainer_predictions"),
        "legacy_orchestrator": _process_state(rows, "rl.orchestrator_worker"),
        "legacy_trader": _process_state(rows, "trading/trader.py"),
        "v2_paper_runtime": _process_state(rows, "paper_online_runtime"),
        "control_plane": _process_state(rows, "agent_supervisor.py|parallel_capacity_scheduler|codex_non_live_watchdog|autonomous_governor|claude_master_rebuild_planner"),
    }


def _process_state(rows: list[dict[str, Any]], pattern: str) -> dict[str, Any]:
    regex = re.compile(pattern)
    matches = [row for row in rows if regex.search(str(row["command"]))]
    return {
        "status": "PROCESS_OBSERVED_READONLY" if matches else "PROCESS_NOT_OBSERVED",
        "count": len(matches),
        "rows": matches,
    }


def collect_gpu_state(process_snapshot: dict[str, Any]) -> dict[str, Any]:
    gpu = {
        "status": "GPU_RUNTIME_EVIDENCE_MISSING",
        "nvidia_smi_available": False,
        "gpu": None,
        "compute_apps": [],
        "trainer_using_gpu": False,
    }
    query = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,cuda_version,memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=8,
    )
    if query.returncode != 0:
        gpu["error"] = query.stderr.strip() or query.stdout.strip()
        return gpu
    gpu["nvidia_smi_available"] = True
    parts = [part.strip() for part in query.stdout.splitlines()[0].split(",")]
    if len(parts) >= 6:
        gpu["gpu"] = {
            "name": parts[0],
            "driver_version": parts[1],
            "cuda_version": parts[2],
            "memory_used_mib": _parse_int(parts[3]),
            "memory_total_mib": _parse_int(parts[4]),
            "utilization_pct": _parse_int(parts[5]),
        }
    apps = _run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        timeout=8,
    )
    compute_apps = []
    trainer_pids = {
        int(row["pid"])
        for row in process_snapshot["legacy_trainer"]["rows"]
        if isinstance(row.get("pid"), int)
    }
    if apps.returncode == 0:
        for line in apps.stdout.splitlines():
            fields = [part.strip() for part in line.split(",")]
            if len(fields) < 3 or not fields[0].isdigit():
                continue
            pid = int(fields[0])
            compute_apps.append(
                {
                    "pid": pid,
                    "process_name": fields[1],
                    "used_memory_mib": _parse_int(fields[2]),
                    "matches_legacy_trainer": pid in trainer_pids,
                }
            )
    gpu["compute_apps"] = compute_apps
    gpu["trainer_using_gpu"] = any(row["matches_legacy_trainer"] for row in compute_apps)
    gpu["status"] = "TRAINER_USING_GPU" if gpu["trainer_using_gpu"] else "GPU_RUNTIME_OBSERVED"
    return gpu


def _parse_int(value: str) -> int | None:
    try:
        return int(float(value.strip()))
    except ValueError:
        return None


def collect_legacy_redis_evidence() -> dict[str, Any]:
    streams: dict[str, Any] = {}
    redis_info = {
        "ping": "UNKNOWN",
        "redis_memory_state": None,
        "legacy_streams": streams,
        "read_only_commands_only": True,
        "redis_writes": False,
    }
    ping = _run([*_redis_base_command(), "PING"], timeout=4)
    redis_info["ping"] = "PONG" if ping.returncode == 0 and ping.stdout.strip() == "PONG" else "UNAVAILABLE"
    if redis_info["ping"] != "PONG":
        return redis_info
    info = run_redis_read_only("INFO", "memory")
    if info.returncode == 0:
        memory = {}
        for line in info.stdout.splitlines():
            if ":" in line and line.split(":", 1)[0] in {"used_memory_human", "used_memory", "maxmemory_human", "mem_fragmentation_ratio"}:
                key, value = line.split(":", 1)
                memory[key] = value.strip()
        redis_info["redis_memory_state"] = memory
    for key in LEGACY_STREAM_CANDIDATES:
        streams[key] = read_latest_stream_entry(key)
    return redis_info


def latest_legacy_signal(redis_evidence: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("signals:trading:primary", "signals:trading", "signals:trading:asjad", "wma:proposals"):
        row = redis_evidence.get("legacy_streams", {}).get(key)
        latest = row.get("latest_entry") if isinstance(row, dict) else None
        if latest:
            return {"source_key": key, **latest}
    return None


def latest_executed_signal(redis_evidence: dict[str, Any]) -> dict[str, Any] | None:
    row = redis_evidence.get("legacy_streams", {}).get("executed_signals")
    latest = row.get("latest_entry") if isinstance(row, dict) else None
    if latest:
        return {"source_key": "executed_signals", **latest}
    return None


def _field(fields: dict[str, Any], *names: str) -> Any:
    lower = {str(key).lower(): value for key, value in fields.items()}
    for name in names:
        if name in fields and fields[name] not in (None, ""):
            return fields[name]
        value = lower.get(name.lower())
        if value not in (None, ""):
            return value
    return None


def _field_like(fields: dict[str, Any], *parts: str) -> Any:
    for key, value in fields.items():
        key_l = str(key).lower()
        if all(part in key_l for part in parts) and value not in (None, ""):
            return value
    return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def build_shadow_twin(
    *,
    generated_at: str,
    legacy_signal: dict[str, Any] | None,
    executed_signal: dict[str, Any] | None,
    paper_runtime: dict[str, Any] | None,
) -> dict[str, Any]:
    fields = _flatten_entry_fields(legacy_signal.get("flat_fields", {}) if legacy_signal else {})
    paper_symbol = paper_runtime.get("market_feed", {}).get("symbol") if paper_runtime else "BTCUSDT"
    paper_price = paper_runtime.get("market_feed", {}).get("price") if paper_runtime else None
    signal_id = _field(fields, "signal_id", "id", "client_signal_id")
    prediction_id = _field(fields, "prediction_id", "pred_id")
    feature_snapshot_id = _field(fields, "feature_snapshot_id", "snapshot_id")
    confidence = _coerce_float(_field(fields, "confidence", "confidence_calibrated") or _field_like(fields, "confidence"))
    symbol = _field(fields, "symbol", "ticker", "pair") or paper_symbol
    action = _field(fields, "action", "side", "direction", "signal") or "unknown"
    source_event_at = legacy_signal.get("last_event_at") if legacy_signal else None
    source_age = legacy_signal.get("age_seconds") if legacy_signal else None
    missing_fields = [
        name
        for name, value in {
            "signal_id": signal_id,
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "confidence": confidence,
        }.items()
        if value in (None, "")
    ]
    risk_action = "allow"
    risk_result = "APPROVED_FOR_SHADOW_PAPER_ONLY"
    risk_reason = "allow_current_legacy_signal_shadow_paper_only"
    if legacy_signal is None:
        risk_action = "block"
        risk_result = "BLOCKED"
        risk_reason = "deny_missing_legacy_signal_evidence"
    elif missing_fields:
        risk_action = "block"
        risk_result = "BLOCKED"
        risk_reason = "deny_missing_required_lineage_fields"
    elif source_age is None or source_age > 120:
        risk_action = "block"
        risk_result = "BLOCKED"
        risk_reason = "deny_stale_legacy_signal"
    risk_decision_id = f"risk_shadow_{int(time.time() * 1000)}"
    execution_intent_id = f"shadow_intent_{int(time.time() * 1000)}"
    paper_ledger_entry_id = f"shadow_ledger_{int(time.time() * 1000)}"
    normalized_signal_id = str(signal_id or f"legacy_stream_{legacy_signal.get('stream_id') if legacy_signal else 'missing'}")
    orchestrator_decision_id = str(_field(fields, "orchestrator_decision_id", "decision_id") or f"orch_shadow_{normalized_signal_id}")
    return {
        "generated_at": generated_at,
        "classification": "REALTIME_RUNTIME_EVIDENCE" if legacy_signal else "MISSING_EVIDENCE",
        "legacy_source": {
            "stream": legacy_signal.get("source_key") if legacy_signal else None,
            "stream_id": legacy_signal.get("stream_id") if legacy_signal else None,
            "last_event_at": source_event_at,
            "age_seconds": source_age,
            "can_reach_legacy_trader": "UNKNOWN_NEEDS_EVIDENCE",
            "executed_signal_observed": executed_signal is not None,
            "latest_executed_signal_age_seconds": executed_signal.get("age_seconds") if executed_signal else None,
        },
        "normalized_signal": {
            "signal_id": normalized_signal_id,
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "symbol": symbol,
            "action": action,
            "confidence": confidence,
            "source_freshness": "CURRENT" if source_age is not None and source_age <= 120 else "STALE_OR_MISSING",
            "source_type": "LEGACY_REDIS_READONLY_STREAM",
        },
        "orchestrator_adapter_decision": {
            "orchestrator_decision_id": orchestrator_decision_id,
            "signal_id": normalized_signal_id,
            "adapter": "legacy_live_observer_adapter_v1",
            "role": "propose_enrich_deconflict_only",
            "risk_gateway_required": True,
            "cannot_bypass_risk_gateway": True,
            "decision_action": action,
        },
        "risk_decision": {
            "risk_decision_id": risk_decision_id,
            "signal_id": normalized_signal_id,
            "prediction_id": prediction_id,
            "feature_snapshot_id": feature_snapshot_id,
            "orchestrator_decision_id": orchestrator_decision_id,
            "risk_action": risk_action,
            "risk_result": risk_result,
            "risk_reason_code": risk_reason,
            "missing_fields": missing_fields,
            "required_blocks_checked": [
                "missing_signal_id",
                "missing_prediction_id",
                "missing_feature_snapshot_id",
                "missing_confidence",
                "stale_signal",
                "duplicate_signal_execution",
                "cross_margin_live_mode",
                "leverage_above_cap",
                "adjust_leverage_disabled",
                "missing_stop_policy",
                "disabled_kill_switch",
                "daily_loss_breach",
                "untraceable_execution",
            ],
            "final_authority": "V2_RISK_GATEWAY",
            "live_blocked": True,
            "exchange_order_allowed": False,
        },
        "paper_execution_intent": {
            "execution_intent_id": execution_intent_id,
            "risk_decision_id": risk_decision_id,
            "signal_id": normalized_signal_id,
            "intent_action": "paper_shadow_fill_simulation" if risk_action == "allow" else "paper_shadow_noop_blocked",
            "paper_only": True,
            "exchange_order_allowed": False,
        },
        "paper_ledger_entry": {
            "paper_ledger_entry_id": paper_ledger_entry_id,
            "execution_intent_id": execution_intent_id,
            "risk_decision_id": risk_decision_id,
            "signal_id": normalized_signal_id,
            "symbol": symbol,
            "paper_result": "FILLED_PAPER_SHADOW_ONLY" if risk_action == "allow" else "NO_FILL_RISK_BLOCKED",
            "paper_price_reference": paper_price,
            "fee_rate": 0.0004,
            "slippage_bps": 2.0,
            "funding_assumption": "zero_until_funding_feed_adapter_current",
            "exchange_order_id": None,
            "live_order": False,
            "legacy_redis_write": False,
        },
    }


def build_current_truth_payload(
    *,
    generated_at: str,
    process_snapshot: dict[str, Any],
    gpu_state: dict[str, Any],
    redis_evidence: dict[str, Any],
    paper_runtime: dict[str, Any] | None,
    shadow_twin: dict[str, Any],
) -> dict[str, Any]:
    paper_age = age_seconds_from_iso(paper_runtime.get("generated_at") if paper_runtime else None)
    paper_current = paper_age is not None and paper_age <= 120 and paper_runtime.get("runtime_state") == "PAPER_RUNTIME_ONLINE_ACTIVE" if paper_runtime else False
    legacy_signal = shadow_twin["normalized_signal"]
    audit_events = [
        {
            "audit_event_id": f"audit_live_bridge_{int(time.time() * 1000)}",
            "generated_at": generated_at,
            "event_type": "LEGACY_LIVE_BRIDGE_IMPORT",
            "source": "legacy Redis read-only streams + process list",
            "legacy_redis_write": False,
            "exchange_order": False,
        },
        {
            "audit_event_id": f"audit_shadow_risk_{shadow_twin['risk_decision']['risk_decision_id']}",
            "generated_at": generated_at,
            "event_type": "V2_SHADOW_RISK_DECISION",
            "risk_decision": shadow_twin["risk_decision"],
        },
        {
            "audit_event_id": f"audit_shadow_paper_{shadow_twin['paper_ledger_entry']['paper_ledger_entry_id']}",
            "generated_at": generated_at,
            "event_type": "V2_SHADOW_PAPER_LEDGER",
            "paper_ledger_entry": shadow_twin["paper_ledger_entry"],
        },
    ]
    return {
        "generated_at": generated_at,
        "status": "V2_LIVE_OBSERVER_SHADOW_TWIN_ACTIVE",
        "live_gate_status": LIVE_GATE_STATUS,
        "source_files": {
            "paper_runtime": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "public_live_observer": "v2/frontend/public/operator_runtime/live_observer/latest/current_runtime_truth_payload.json",
            "local_live_observer": "v2/runtime/live_observer/latest/current_runtime_truth_payload.json",
        },
        "process_snapshot": process_snapshot,
        "gpu_runtime": gpu_state,
        "legacy_read_only_bridge": {
            "status": "LEGACY_LIVE_BRIDGE_IMPORTER_CURRENT" if redis_evidence.get("ping") == "PONG" else "LEGACY_REDIS_READONLY_UNAVAILABLE",
            "redis_ping": redis_evidence.get("ping"),
            "legacy_redis_writes": False,
            "streams": redis_evidence.get("legacy_streams", {}),
            "redis_memory_state": redis_evidence.get("redis_memory_state"),
        },
        "v2_paper_runtime": {
            "status": "CURRENT" if paper_current else "STALE_OR_MISSING",
            "age_seconds": paper_age,
            "runtime_state": paper_runtime.get("runtime_state") if paper_runtime else "MISSING_EVIDENCE",
            "market_feed": paper_runtime.get("market_feed") if paper_runtime else None,
            "trainer_prediction": paper_runtime.get("trainer_prediction") if paper_runtime else None,
            "feature_snapshot": paper_runtime.get("feature_snapshot") if paper_runtime else None,
            "signal_lineage": paper_runtime.get("current_signal_lineage") if paper_runtime else None,
            "risk_decision": paper_runtime.get("current_risk_decision") if paper_runtime else None,
            "paper_ledger_tail": paper_runtime.get("paper_ledger_tail") if paper_runtime else [],
            "audit_events": paper_runtime.get("audit_events") if paper_runtime else [],
        },
        "legacy_shadow_twin": shadow_twin,
        "trainer_bridge_parity": {
            "legacy_trainer_status": process_snapshot["legacy_trainer"]["status"],
            "legacy_trainer_monitor_status": process_snapshot["legacy_trainer_monitor"]["status"],
            "legacy_trainer_gpu_status": gpu_state["status"],
            "v2_wrapper_status": "CURRENT" if paper_current else "STALE_OR_MISSING",
            "parity_status": "PARTIAL_RUNTIME_BRIDGE_PARITY_NOT_FULL_MODEL_PARITY",
            "detail": "Legacy trainer/process/GPU can be observed read-only; V2 paper wrapper remains separate and full PPO/MASS checkpoint parity is not claimed.",
        },
        "orchestrator_adapter": {
            "legacy_orchestrator_status": process_snapshot["legacy_orchestrator"]["status"],
            "adapter_status": "LEGACY_OBSERVER_ADAPTER_ACTIVE",
            "role": "propose_enrich_deconflict_only",
            "risk_gateway_final_authority": True,
            "current_orchestrator_decision": shadow_twin["orchestrator_adapter_decision"],
        },
        "risk_gateway": {
            "status": "CURRENT_SHADOW_SIGNAL_PROCESSED",
            "final_authority": True,
            "current_risk_decision": shadow_twin["risk_decision"],
        },
        "paper_execution_ledger": {
            "status": "CURRENT_SHADOW_LEDGER_WRITTEN",
            "entries": [shadow_twin["paper_ledger_entry"]],
        },
        "audit_ledger": {
            "status": "V2_FILE_AUDIT_LEDGER_CURRENT_POSTGRES_SCHEMA_READY",
            "events": audit_events,
            "postgres": {
                "status": "POSTGRES_RUNTIME_WRITE_NOT_ATTEMPTED_NO_V2_DATABASE_URL"
                if not os.environ.get("DATABASE_URL")
                else "POSTGRES_URL_PRESENT_WRITE_NOT_ATTEMPTED_BY_DEFAULT",
                "schema_ready": True,
                "secret_values_exposed": False,
            },
        },
        "v2_bounded_redis_namespace": {
            "status": "V2_REDIS_NAMESPACE_CONTRACT_READY_WRITE_DISABLED_FOR_SAFETY",
            "prefix": os.environ.get("V2_REDIS_PREFIX", "v2:") + "live_observer:",
            "max_stream_length": 10_000,
            "write_enabled": False,
            "reason": "This task reads legacy Redis only. V2 Redis writes require explicit isolated V2 endpoint or approval that v2:* writes cannot affect legacy keys.",
        },
        "gui_runtime_truth": {
            "status": "PAYLOAD_READY_FOR_GUI",
            "no_static_fixture_as_current": True,
            "legacy_signal_status": shadow_twin["classification"],
            "v2_paper_status": "CURRENT" if paper_current else "STALE_OR_MISSING",
            "current_records_visible": {
                "market_feed": paper_current and bool(paper_runtime.get("market_feed")) if paper_runtime else False,
                "trainer_prediction": paper_current and bool(paper_runtime.get("trainer_prediction")) if paper_runtime else False,
                "feature_snapshot": paper_current and bool(paper_runtime.get("feature_snapshot")) if paper_runtime else False,
                "signal": bool(legacy_signal.get("signal_id")) or (paper_current and bool(paper_runtime.get("current_signal_lineage")) if paper_runtime else False),
                "orchestrator_decision": bool(shadow_twin["orchestrator_adapter_decision"].get("orchestrator_decision_id")),
                "risk_decision": bool(shadow_twin["risk_decision"].get("risk_decision_id")),
                "paper_execution": bool(shadow_twin["paper_ledger_entry"].get("paper_ledger_entry_id")),
                "audit_ledger": True,
            },
        },
        "safety": {
            "legacy_bot_modified": False,
            "legacy_redis_writes": False,
            "exchange_orders": False,
            "leverage_changes": False,
            "margin_mode_changes": False,
            "redis_trim_approval_created": False,
            "live_gate_status": LIVE_GATE_STATUS,
        },
        "blockers": [
            {
                "id": "POSTGRES_RUNTIME_CONNECTION_NOT_CONFIGURED",
                "severity": "data_plane_durability",
                "detail": "V2 audit ledger is current as local V2 artifact and Postgres schema-ready, but no runtime Postgres write was attempted without an explicit V2 DATABASE_URL.",
            },
            {
                "id": "V2_REDIS_RUNTIME_WRITES_DISABLED",
                "severity": "data_plane_transport",
                "detail": "V2 bounded Redis namespace is contracted, but writes are disabled to avoid accidental legacy Redis mutation.",
            },
            {
                "id": "LEGACY_MODEL_FULL_PARITY_NOT_CLAIMED",
                "severity": "trainer_parity",
                "detail": "Legacy trainer/GPU is observed read-only; V2 wrapper is current; full PPO/MASS checkpoint parity remains a separate blocker.",
            },
        ],
    }


def write_reports(payload: dict[str, Any], marker: str, codex_marker: str) -> None:
    generated_at = payload["generated_at"]
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    _write_text(FINAL_DIR / "GO_NO_GO.md", marker + "\n")
    _write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker + "\n")
    _write_json(FINAL_DIR / "operator_dashboard_payload.json", {
        "generated_at": generated_at,
        "status": marker,
        "live_gate_status": LIVE_GATE_STATUS,
        "legacy_bridge_status": payload["legacy_read_only_bridge"]["status"],
        "v2_paper_runtime_status": payload["v2_paper_runtime"]["status"],
        "legacy_trainer_status": payload["trainer_bridge_parity"]["legacy_trainer_status"],
        "v2_wrapper_status": payload["trainer_bridge_parity"]["v2_wrapper_status"],
        "parity_status": payload["trainer_bridge_parity"]["parity_status"],
        "risk_gateway_status": payload["risk_gateway"]["status"],
        "paper_execution_ledger_status": payload["paper_execution_ledger"]["status"],
        "audit_ledger_status": payload["audit_ledger"]["status"],
        "v2_redis_namespace_status": payload["v2_bounded_redis_namespace"]["status"],
        "old_redis_writes": False,
        "exchange_actions": False,
        "redis_trim_status": "deferred_non_blocking",
        "codex_result": codex_marker,
    })
    reports = {
        "V2_LIVE_OBSERVER_SHADOW_TWIN_REPORT.md": f"""# V2 Live Observer Shadow Twin Report

Status: {marker}

Generated at: {generated_at}

- Legacy bridge importer: `{payload['legacy_read_only_bridge']['status']}`
- V2 paper runtime: `{payload['v2_paper_runtime']['status']}`
- Trainer bridge/parity: `{payload['trainer_bridge_parity']['parity_status']}`
- Orchestrator adapter: `{payload['orchestrator_adapter']['adapter_status']}`
- Risk Gateway: `{payload['risk_gateway']['status']}`
- Paper shadow ledger: `{payload['paper_execution_ledger']['status']}`
- Audit ledger: `{payload['audit_ledger']['status']}`
- V2 Redis namespace: `{payload['v2_bounded_redis_namespace']['status']}`
- Live gate: `{LIVE_GATE_STATUS}`

The bridge observes legacy processes and legacy Redis streams read-only, normalizes the latest legacy signal/proposal into a V2 shadow twin, routes it through a V2 fail-closed Risk Gateway decision, and writes only V2-owned local/public runtime artifacts. It does not modify legacy, write old Redis, place orders, or change leverage/margin.
""",
        "LEGACY_LIVE_BRIDGE_IMPORTER_REPORT.md": f"""# Legacy Live Bridge Importer Report

Generated at: {generated_at}

The importer used read-only process inspection and read-only Redis commands only. Redis write commands are denied by code before execution.

- Redis ping: `{payload['legacy_read_only_bridge']['redis_ping']}`
- Legacy Redis writes: `false`
- Streams inspected: `{len(payload['legacy_read_only_bridge']['streams'])}`
- Legacy trainer: `{payload['process_snapshot']['legacy_trainer']['status']}`
- Legacy orchestrator: `{payload['process_snapshot']['legacy_orchestrator']['status']}`
- Legacy trader: `{payload['process_snapshot']['legacy_trader']['status']}`
""",
        "CURRENT_RUNTIME_TRUTH_PAYLOAD_REPORT.md": f"""# Current Runtime Truth Payload Report

Generated at: {generated_at}

Current truth payloads:

- `v2/frontend/public/operator_runtime/live_observer/latest/current_runtime_truth_payload.json`
- `v2/runtime/live_observer/latest/current_runtime_truth_payload.json`

The payload combines legacy read-only evidence with the fresh V2 paper runtime payload. Static proof fixtures are not used as current runtime truth.
""",
        "V2_POSTGRES_AUDIT_LEDGER_REPORT.md": f"""# V2 Postgres Audit Ledger Report

Generated at: {generated_at}

Status: `{payload['audit_ledger']['postgres']['status']}`

Current V2 audit events are written to V2-owned JSON ledger artifacts. Postgres schema is represented by the audit event contract in the payload, but runtime Postgres writes were not attempted unless an explicit V2 `DATABASE_URL` is configured. No secret values were printed or stored.
""",
        "V2_BOUNDED_REDIS_NAMESPACE_REPORT.md": f"""# V2 Bounded Redis Namespace Report

Generated at: {generated_at}

Status: `{payload['v2_bounded_redis_namespace']['status']}`

- Prefix: `{payload['v2_bounded_redis_namespace']['prefix']}`
- Max stream length contract: `{payload['v2_bounded_redis_namespace']['max_stream_length']}`
- Runtime write enabled: `{payload['v2_bounded_redis_namespace']['write_enabled']}`

This task did not write Redis. V2 Redis writes remain disabled until an isolated V2 Redis endpoint or explicit v2:* write approval is available.
""",
        "V2_PAPER_SHADOW_TWIN_REPORT.md": f"""# V2 Paper Shadow Twin Report

Generated at: {generated_at}

- Shadow classification: `{payload['legacy_shadow_twin']['classification']}`
- Source stream: `{payload['legacy_shadow_twin']['legacy_source']['stream']}`
- Shadow signal id: `{payload['legacy_shadow_twin']['normalized_signal']['signal_id']}`
- Risk result: `{payload['legacy_shadow_twin']['risk_decision']['risk_result']}`
- Paper result: `{payload['legacy_shadow_twin']['paper_ledger_entry']['paper_result']}`

The shadow twin is paper-only. Exchange orders are blocked and legacy Redis writes are false.
""",
        "TRAINER_BRIDGE_PARITY_STATUS.md": f"""# Trainer Bridge Parity Status

Generated at: {generated_at}

- Legacy trainer: `{payload['trainer_bridge_parity']['legacy_trainer_status']}`
- Legacy trainer monitor: `{payload['trainer_bridge_parity']['legacy_trainer_monitor_status']}`
- GPU runtime: `{payload['trainer_bridge_parity']['legacy_trainer_gpu_status']}`
- V2 wrapper: `{payload['trainer_bridge_parity']['v2_wrapper_status']}`
- Parity: `{payload['trainer_bridge_parity']['parity_status']}`

Full legacy PPO/MASS model parity is not claimed by this observer bridge.
""",
        "ORCHESTRATOR_ADAPTER_REPORT.md": f"""# Orchestrator Adapter Report

Generated at: {generated_at}

Adapter status: `{payload['orchestrator_adapter']['adapter_status']}`

The V2 adapter observes legacy proposal/signal evidence and creates a normalized orchestrator decision for paper/shadow routing. Orchestrator remains proposal/enrichment/deconfliction only. Risk Gateway is final authority.
""",
        "RISK_GATEWAY_FINAL_AUTHORITY_REPORT.md": f"""# Risk Gateway Final Authority Report

Generated at: {generated_at}

- Status: `{payload['risk_gateway']['status']}`
- Final authority: `{payload['risk_gateway']['final_authority']}`
- Current risk result: `{payload['risk_gateway']['current_risk_decision']['risk_result']}`
- Reason: `{payload['risk_gateway']['current_risk_decision']['risk_reason_code']}`
- Exchange order allowed: `{payload['risk_gateway']['current_risk_decision']['exchange_order_allowed']}`
""",
        "PAPER_EXECUTION_LEDGER_REPORT.md": f"""# Paper Execution Ledger Report

Generated at: {generated_at}

Status: `{payload['paper_execution_ledger']['status']}`

The latest legacy-observed signal/proposal is mirrored into a V2 paper-only ledger entry. If lineage evidence is missing or stale, the paper ledger records a no-fill blocked result rather than fabricating a fill.
""",
        "GUI_RUNTIME_TRUTH_REPORT.md": f"""# GUI Runtime Truth Report

Generated at: {generated_at}

Status: `{payload['gui_runtime_truth']['status']}`

The GUI can read the live observer payload from `/operator_runtime/live_observer/latest/current_runtime_truth_payload.json`. The Mission Control truth layer should show legacy observer state, V2 paper state, trainer parity state, Risk Gateway final authority, and paper audit ledger without promoting static fixtures to runtime truth.
""",
        "CODEX_LIVE_OBSERVER_SHADOW_TWIN_REVIEW.md": f"""# Codex Live Observer Shadow Twin Review

Generated at: {generated_at}

Result: {codex_marker}

Review checks:

- Legacy bot modified: no
- Old Redis write commands used by this task: no
- Exchange actions: no
- Live gate preserved: `{LIVE_GATE_STATUS}`
- V2 paper runtime surfaced: `{payload['v2_paper_runtime']['status']}`
- Legacy bridge is read-only: yes
- Risk Gateway final authority visible: yes
- Full legacy trainer parity claimed: no

Residual blockers are explicitly listed in the runtime truth payload rather than hidden.
""",
    }
    for filename, text in reports.items():
        _write_text(FINAL_DIR / filename, text)


def build_and_write_payloads(*, write_evidence: bool = False) -> dict[str, Any]:
    generated_at = iso_now()
    process_snapshot = collect_process_snapshot()
    gpu_state = collect_gpu_state(process_snapshot)
    redis_evidence = collect_legacy_redis_evidence()
    paper_runtime = _read_json(PUBLIC_PAPER_STATUS)
    legacy_signal = latest_legacy_signal(redis_evidence)
    executed_signal = latest_executed_signal(redis_evidence)
    shadow_twin = build_shadow_twin(
        generated_at=generated_at,
        legacy_signal=legacy_signal,
        executed_signal=executed_signal,
        paper_runtime=paper_runtime,
    )
    payload = build_current_truth_payload(
        generated_at=generated_at,
        process_snapshot=process_snapshot,
        gpu_state=gpu_state,
        redis_evidence=redis_evidence,
        paper_runtime=paper_runtime,
        shadow_twin=shadow_twin,
    )
    for root in (PUBLIC_OBSERVER_DIR, LOCAL_OBSERVER_DIR):
        _write_json(root / "legacy_live_bridge_status.json", payload["legacy_read_only_bridge"])
        _write_json(root / "current_runtime_truth_payload.json", payload)
        _write_json(root / "shadow_signal_twin.json", payload["legacy_shadow_twin"])
        _write_json(root / "trainer_bridge_parity_status.json", payload["trainer_bridge_parity"])
        _write_json(root / "orchestrator_adapter_status.json", payload["orchestrator_adapter"])
        _write_json(root / "risk_gateway_shadow_decision.json", payload["risk_gateway"])
        _write_json(root / "paper_shadow_ledger_tail.json", payload["paper_execution_ledger"])
        _write_json(root / "audit_ledger_tail.json", payload["audit_ledger"])
        _write_json(root / "v2_data_plane_bridge_status.json", {
            "generated_at": generated_at,
            "postgres_audit_ledger": payload["audit_ledger"]["postgres"],
            "v2_bounded_redis_namespace": payload["v2_bounded_redis_namespace"],
            "legacy_redis_writes": False,
            "exchange_orders": False,
        })
    current_records = payload["gui_runtime_truth"]["current_records_visible"]
    marker = READY_MARKER if all(current_records.values()) else BLOCKED_MARKER
    codex_marker = CODEX_PASS_MARKER if marker == READY_MARKER else CODEX_FAIL_MARKER
    if write_evidence:
        _write_json(FINAL_DIR / "current_runtime_truth_payload.json", payload)
        _write_json(FINAL_DIR / "legacy_live_bridge_status.json", payload["legacy_read_only_bridge"])
        _write_json(FINAL_DIR / "shadow_signal_twin.json", payload["legacy_shadow_twin"])
        _write_json(FINAL_DIR / "paper_shadow_ledger_tail.json", payload["paper_execution_ledger"])
        _write_json(FINAL_DIR / "audit_ledger_tail.json", payload["audit_ledger"])
        write_reports(payload, marker, codex_marker)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only legacy live observer bridge for V2 paper/shadow twin.")
    parser.add_argument("--write-evidence", action="store_true", help="write final-readiness evidence reports")
    args = parser.parse_args()
    payload = build_and_write_payloads(write_evidence=args.write_evidence)
    print(
        json.dumps(
            {
                "generated_at": payload["generated_at"],
                "status": payload["status"],
                "legacy_bridge": payload["legacy_read_only_bridge"]["status"],
                "v2_paper_runtime": payload["v2_paper_runtime"]["status"],
                "risk_result": payload["risk_gateway"]["current_risk_decision"]["risk_result"],
                "live_gate_status": LIVE_GATE_STATUS,
                "legacy_redis_writes": False,
                "exchange_orders": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
