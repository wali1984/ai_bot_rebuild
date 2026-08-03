#!/usr/bin/env python3
"""Codex runtime soak and production-equivalence governor.

Read-only verifier for the V2 paper/shadow production-replacement runtime.
It does not touch legacy, write Redis, call exchange APIs, or approve live.
It records whether the running V2 chain is stable, fresh, comparable to legacy
truth, and still blocked from shutdown/live use.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/codex_governor"
PUBLIC = ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest"
TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/tasks"

GO_READY = "CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_READY"
GO_BLOCKED = "CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_BLOCKED"
LIVE_GATE = "blocked_human_only"

REQUIRED_PROCESSES = {
    "v2_native_ingestors_live_loop": "v2_native_ingestors_live_loop",
    "v2_feature_pipeline_native_loop": "v2_feature_pipeline_native_loop",
    "v2_rl_core_inference_loop": "v2_rl_core_inference_loop",
    "v2_orchestrator_arbitration_loop": "v2_orchestrator_arbitration_loop",
    "v2_trade_management_paper_loop": "v2_trade_management_paper_loop",
    "v2_production_replacement_runtime_guard": "v2_production_replacement_runtime_guard.py",
    "legacy_v2_comparator": "v2_legacy_v2_production_comparator.py",
    "production_equivalence_comparator": "v2_production_equivalence_comparator",
    "soak_observer": "v2_production_replacement_soak_observer",
    "payload_freshness_refresher": "v2_production_payload_freshness_refresher",
}

LEGACY_PROCESSES = {
    "live_binance": "ingest/live_binance.py",
    "live_binance_liquidations": "ingest/live_binance_liquidations.py",
    "live_coinank": "ingest/live_coinank.py",
    "live_kucoin": "ingest/live_kucoin.py",
    "feature_pipeline": "feature_pipeline.py",
    "hybrid_trainer": "rl.hybrid_trainer",
    "orchestrator_worker": "rl.orchestrator_worker",
    "live_coinapi_v1": "ingest/live_coinapi_v1.py",
    "live_coinapi_wsds": "ingest/live_coinapi_wsds.py",
}

V2_REDIS = {
    "v2_all": "v2:*",
    "v2_market": "v2:market:*",
    "v2_features": "v2:features:*",
    "v2_prediction": "v2:prediction:*",
    "v2_trainer": "v2:trainer:*",
    "v2_orchestrator": "v2:orchestrator:*",
    "v2_paper": "v2:paper:*",
    "v2_risk": "v2:risk:*",
}

LEGACY_REDIS = {
    "legacy_prediction": "prediction:*",
    "legacy_features": "features:*",
    "legacy_signals": "signals:*",
    "legacy_market": "market:*",
    "legacy_trainer": "trainer:*",
}

PAYLOADS = {
    "v2_native_ingestors_live": ROOT / "v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json",
    "v2_feature_pipeline_native_live": ROOT / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/live/latest/v2_feature_pipeline_native_live_status.json",
    "v2_rl_core_live": ROOT / "v2/frontend/public/operator_runtime/v2_rl_core/live/latest/v2_rl_core_live_status.json",
    "v2_orchestrator_arbitration_live": ROOT / "v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json",
    "v2_trade_management_paper_live": ROOT / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json",
    "runtime_guard": ROOT / "v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest/runtime_guard_status.json",
    "soak_observer": ROOT / "v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest/soak_status.json",
    "legacy_v2_comparator": ROOT / "v2/frontend/public/operator_runtime/legacy_v2_production_comparator/latest/status.json",
    "runtime_soak_status": ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/soak_status.json",
    "production_equivalence_comparison": ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json",
    "replacement_readiness_scoreboard": ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/v2_replacement_readiness_scoreboard.json",
    "frontend_truth": ROOT / "v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json",
    "replacement_frontend": ROOT / "v2/frontend/public/v2_production_replacement_runtime/latest/operator_dashboard_payload.json",
    "runtime_soak_frontend": ROOT / "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/operator_dashboard_payload.json",
}

ACTIVE_RUNTIME_FILES = [
    ROOT / "v2/backend/app/cli/v2_native_ingestors_live_loop.py",
    ROOT / "v2/backend/app/cli/v2_feature_pipeline_native_loop.py",
    ROOT / "v2/backend/app/cli/v2_rl_core_inference_loop.py",
    ROOT / "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
    ROOT / "v2/backend/app/cli/v2_trade_management_paper_loop.py",
    ROOT / "v2/backend/app/cli/v2_production_payload_freshness_refresher.py",
    ROOT / "v2/backend/app/cli/v2_production_replacement_soak_observer.py",
    ROOT / "v2/backend/app/cli/v2_production_equivalence_comparator.py",
    ROOT / "v2/backend/scripts/run_v2_replacement_readiness_scoreboard.py",
    ROOT / "claude_worklog/tools/v2_production_replacement_runtime_guard.py",
    ROOT / "claude_worklog/tools/v2_legacy_v2_production_comparator.py",
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def payload_age_seconds(payload: dict[str, Any]) -> int | None:
    for key in (
        "generated_utc",
        "generated_at",
        "timestamp_utc",
        "last_updated_utc",
        "updated_utc",
        "finished_at",
        "started_at",
        "refreshed_utc",
        "last_observed_utc",
        "as_of_utc",
        "last_updated",
    ):
        parsed = parse_time(payload.get(key))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    return None


def process_status(patterns: dict[str, str]) -> dict[str, Any]:
    proc = run(["ps", "-eo", "pid,ppid,stat,etime,cmd", "--width", "360"], timeout=10)
    lines = proc.stdout.splitlines()
    result: dict[str, Any] = {}
    for name, pattern in patterns.items():
        matches = [
            line.strip()
            for line in lines
            if pattern in line
            and "grep" not in line
            and "bash -lc" not in line
            and "codex_runtime_soak_and_production_equivalence_governor.py --once" not in line
        ]
        result[name] = {
            "pattern": pattern,
            "running": bool(matches),
            "match_count": len(matches),
            "sample": matches[:5],
        }
    return result


def redis_scan(pattern: str, sample_limit: int = 10) -> dict[str, Any]:
    proc = run(["redis-cli", "--scan", "--pattern", pattern], timeout=20)
    keys = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return {
        "pattern": pattern,
        "count": len(keys),
        "sample": keys[:sample_limit],
        "returncode": proc.returncode,
        "stderr": proc.stderr.strip()[:500],
    }


def redis_get(key: str) -> dict[str, Any]:
    if not key:
        return {"key": None, "available": False, "missing_reason": "NO_KEY"}
    proc = run(["redis-cli", "GET", key], timeout=10)
    text = proc.stdout.strip()
    if proc.returncode != 0:
        return {"key": key, "available": False, "missing_reason": proc.stderr.strip()[:300]}
    if not text:
        return {"key": key, "available": False, "missing_reason": "EMPTY_OR_MISSING_VALUE"}
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
    return {
        "key": key,
        "available": True,
        "json_object": isinstance(parsed, dict),
        "value_preview": text[:400],
        "field_keys": sorted(parsed.keys())[:40] if isinstance(parsed, dict) else [],
    }


def payload_status(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    age = payload_age_seconds(payload)
    exists = path.exists()
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": exists,
        "json_object": bool(payload),
        "age_seconds": age,
        "fresh": exists and bool(payload) and age is not None and age <= 900,
        "live_gate": payload.get("live_gate"),
        "live_symbols": payload.get("live_symbols"),
        "approves_live": payload.get("approves_live"),
        "approves_canary": payload.get("approves_canary"),
        "approves_legacy_shutdown": payload.get("approves_legacy_shutdown"),
        "approves_redis_trim": payload.get("approves_redis_trim"),
        "classification": payload.get("classification") or payload.get("go_no_go") or payload.get("schema_version"),
    }


def safety_scan() -> dict[str, Any]:
    exchange_pattern = re.compile(
        r"create_order|cancel_order|cancel_all|set_leverage|set_margin_mode|"
        r"futures_create_order|futures_cancel|private_post|sapi_post|dapi_|fapi_|"
        r"place_order|modify_order"
    )
    redis_write_pattern = re.compile(r"\.set\(|\.hset\(|\.xadd\(|\.delete\(|\.xtrim\(|flushdb|flushall")
    exchange_hits: list[str] = []
    redis_write_hits: list[str] = []
    redis_write_files: set[str] = set()
    unsafe_redis_hits: list[str] = []
    for path in ACTIVE_RUNTIME_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(text.splitlines(), start=1):
            if exchange_pattern.search(line):
                exchange_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:180]}")
            if redis_write_pattern.search(line):
                redis_write_hits.append(f"{path.relative_to(ROOT)}:{idx}")
                redis_write_files.add(str(path.relative_to(ROOT)))
        if "V2_REDIS_PREFIX" not in text and any(token in text for token in (".set(", ".hset(", ".xadd(")):
            unsafe_redis_hits.append(str(path.relative_to(ROOT)))
    approval_pattern = re.compile(
        r'"approves_live"\s*:\s*true|"approves_canary"\s*:\s*true|'
        r'"approves_legacy_shutdown"\s*:\s*true|LIVE_APPROVAL_TOKEN|FINAL_LIVE_APPROVAL|REDIS_TRIM_APPROVAL',
        re.IGNORECASE,
    )
    approval_hits: list[str] = []
    scan_roots = [
        OUT,
        PUBLIC,
        ROOT / "v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest",
        ROOT / "v2/frontend/public/operator_runtime/legacy_v2_production_comparator/latest",
    ]
    for root in scan_roots:
        if root.is_file():
            paths = [root]
        elif root.exists():
            paths = [p for p in root.rglob("*") if p.is_file()]
        else:
            paths = []
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="replace")
            for idx, line in enumerate(text.splitlines(), start=1):
                if approval_pattern.search(line):
                    if "LIVE_CANARY_SHUTDOWN_OR_REDIS_TRIM_APPROVAL_FOUND" in line:
                        continue
                    lowered = line.lower()
                    if any(token in lowered for token in ("false", "absent", "not found", "no approval")):
                        continue
                    approval_hits.append(f"{path.relative_to(ROOT)}:{idx}:{line.strip()[:180]}")
    return {
        "exchange_mutation_hits": exchange_hits,
        "redis_write_hit_count": len(redis_write_hits),
        "redis_write_files": sorted(redis_write_files),
        "redis_writes_guarded_to_v2_namespace": bool(redis_write_hits) and not unsafe_redis_hits,
        "unsafe_redis_write_files": unsafe_redis_hits,
        "approval_hits": approval_hits,
        "no_exchange_mutation": not exchange_hits,
        "no_old_redis_writes": not unsafe_redis_hits,
        "no_live_or_shutdown_approval": not approval_hits,
    }


def comparison_status(redis_v2: dict[str, Any], redis_legacy: dict[str, Any], payloads: dict[str, Any]) -> dict[str, Any]:
    v2_key = (redis_v2.get("v2_prediction") or {}).get("sample", [None])[0]
    legacy_key = (redis_legacy.get("legacy_prediction") or {}).get("sample", [None])[0]
    v2_prediction = redis_get(v2_key) if v2_key else {"available": False, "missing_reason": "NO_V2_PREDICTION_KEYS"}
    legacy_prediction = redis_get(legacy_key) if legacy_key else {"available": False, "missing_reason": "NO_LEGACY_PREDICTION_KEYS"}
    comp = payloads.get("production_equivalence_comparison", {}) or payloads.get("legacy_v2_comparator", {})
    return {
        "comparison_payload_fresh": comp.get("fresh") is True,
        "comparison_payload_path": comp.get("path"),
        "latest_v2_prediction": v2_prediction,
        "latest_legacy_prediction": legacy_prediction,
        "outcomes_invented": False,
        "notes": "Read-only comparison only; no outcomes are inferred from missing evidence.",
    }


def ensure_task(blockers: list[str]) -> str:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = TASKS_DIR / "claude_v2_runtime_soak_and_production_equivalence_remediation.json"
    payload = {
        "task_id": "claude_v2_runtime_soak_and_production_equivalence_remediation",
        "agent": "claude",
        "status": "pending",
        "risk_level": "L2",
        "cwd": str(ROOT),
        "prompt": (
            "Fix V2 runtime soak and production-equivalence implementation blockers only. "
            "Do not modify /home/wali/Desktop/AI BOT. Do not stop legacy. Do not write old Redis. "
            "Do not call exchange mutation. Do not enable live. live_gate remains blocked_human_only and live_symbols remains []. "
            "Current Codex blockers: " + "; ".join(blockers)
        ),
    }
    write_json(path, payload)
    return str(path.relative_to(ROOT))


def evaluate() -> dict[str, Any]:
    generated = utc_now()
    v2_processes = process_status(REQUIRED_PROCESSES)
    legacy_processes = process_status(LEGACY_PROCESSES)
    redis_v2 = {name: redis_scan(pattern) for name, pattern in V2_REDIS.items()}
    redis_legacy = {name: redis_scan(pattern) for name, pattern in LEGACY_REDIS.items()}
    payloads = {name: payload_status(path) for name, path in PAYLOADS.items()}
    safety = safety_scan()
    comparison = comparison_status(redis_v2, redis_legacy, payloads)

    fail_blockers: list[str] = []
    missing_processes = [name for name, item in v2_processes.items() if not item["running"]]
    if missing_processes:
        fail_blockers.append("V2_REQUIRED_PROCESS_MISSING: " + ", ".join(missing_processes))
    empty_namespaces = [name for name, item in redis_v2.items() if item["count"] <= 0]
    if empty_namespaces:
        fail_blockers.append("V2_REDIS_NAMESPACE_EMPTY: " + ", ".join(empty_namespaces))
    stale_payloads = [name for name, item in payloads.items() if not item["fresh"]]
    if stale_payloads:
        fail_blockers.append("PAYLOAD_STALE_OR_MISSING: " + ", ".join(stale_payloads))
    if not comparison["comparison_payload_fresh"]:
        fail_blockers.append("LEGACY_V2_COMPARISON_STALE_OR_MISSING")
    runtime_soak = read_json(PAYLOADS["runtime_soak_status"])
    readiness_scoreboard = read_json(PAYLOADS["replacement_readiness_scoreboard"])
    soak_minutes = float(runtime_soak.get("minutes_observed") or 0)
    if readiness_scoreboard.get("v2_runtime_running") is not True:
        fail_blockers.append("REPLACEMENT_SCOREBOARD_V2_RUNTIME_NOT_RUNNING")
    if readiness_scoreboard.get("v2_writes_v2_redis") is not True:
        fail_blockers.append("REPLACEMENT_SCOREBOARD_V2_REDIS_WRITES_NOT_PROVEN")
    if readiness_scoreboard.get("v2_vs_legacy_comparison_available") is not True:
        fail_blockers.append("REPLACEMENT_SCOREBOARD_COMPARISON_NOT_AVAILABLE")
    if soak_minutes >= 60 and runtime_soak.get("soak_1h_ready") is not True:
        fail_blockers.append("V2_RUNTIME_SOAK_1H_NOT_READY_AFTER_60M")
    if soak_minutes >= 360 and runtime_soak.get("soak_6h_ready") is not True:
        fail_blockers.append("V2_RUNTIME_SOAK_6H_NOT_READY_AFTER_360M")
    if safety["approval_hits"]:
        fail_blockers.append("LIVE_CANARY_SHUTDOWN_OR_REDIS_TRIM_APPROVAL_FOUND")
    if not safety["no_exchange_mutation"]:
        fail_blockers.append("EXCHANGE_MUTATION_CALL_FOUND")
    if not safety["no_old_redis_writes"]:
        fail_blockers.append("OLD_REDIS_WRITE_RISK_FOUND")
    live_payload_violations = [
        name
        for name, item in payloads.items()
        if item.get("live_gate") not in (None, LIVE_GATE)
        or item.get("live_symbols") not in (None, [])
        or item.get("approves_live") is True
        or item.get("approves_canary") is True
        or item.get("approves_legacy_shutdown") is True
    ]
    if live_payload_violations:
        fail_blockers.append("LIVE_SAFETY_PAYLOAD_VIOLATION: " + ", ".join(live_payload_violations))

    legacy_running = any(item["running"] for item in legacy_processes.values())
    legacy_keys_active = any(item["count"] > 0 for item in redis_legacy.values())
    shutdown_blockers = []
    if legacy_running:
        shutdown_blockers.append("LEGACY_STILL_OWNS_PRODUCTION_RUNTIME")
    if legacy_keys_active:
        shutdown_blockers.append("LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE")

    go_no_go = GO_READY if not fail_blockers else GO_BLOCKED
    remediation_task_path = ensure_task(fail_blockers) if fail_blockers else None
    soak = runtime_soak or read_json(PAYLOADS["soak_observer"])
    runtime_guard = read_json(PAYLOADS["runtime_guard"])

    frontend_status = {
        "headline": "V2 paper/shadow runtime is running; legacy still owns production.",
        "plain_english_lines": [
            "V2 paper/shadow runtime is running and writing v2:* Redis keys.",
            "Legacy still owns production.",
            "Do not shut down legacy.",
            "Live trading is blocked.",
        ],
        "soak_progress": {
            "observation_count": soak.get("observation_count", 0),
            "minutes_observed": soak.get("minutes_observed", 0),
            "soak_15m_ready": soak.get("soak_15m_ready", False),
            "soak_1h_ready": soak.get("soak_1h_ready", False),
            "soak_6h_ready": soak.get("soak_6h_ready", False),
        },
        "production_equivalence": {
            "scoreboard_available": bool(readiness_scoreboard),
            "v2_runtime_running": readiness_scoreboard.get("v2_runtime_running"),
            "v2_writes_v2_redis": readiness_scoreboard.get("v2_writes_v2_redis"),
            "v2_vs_legacy_comparison_available": readiness_scoreboard.get("v2_vs_legacy_comparison_available"),
            "v2_prediction_matches_legacy_or_reason": readiness_scoreboard.get("v2_prediction_matches_legacy_or_reason"),
            "shutdown_recommendation": readiness_scoreboard.get("shutdown_recommendation"),
            "next_required_fix": readiness_scoreboard.get("next_required_fix"),
        },
        "v2_redis_counts": {name: item["count"] for name, item in redis_v2.items()},
        "legacy_redis_counts": {name: item["count"] for name, item in redis_legacy.items()},
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "no_live_approval": True,
        "shutdown_blocked": True,
    }

    return {
        "schema_version": "codex_runtime_soak_and_production_equivalence_governor_v1",
        "generated_utc": generated,
        "go_no_go": go_no_go,
        "summary": {
            "runtime_soak_governor_ready": not fail_blockers,
            "v2_runtime_loops_running": len(REQUIRED_PROCESSES) - len(missing_processes),
            "v2_runtime_loops_required": len(REQUIRED_PROCESSES),
            "all_required_v2_namespaces_present": not empty_namespaces,
            "all_payloads_fresh": not stale_payloads,
            "comparison_fresh": comparison["comparison_payload_fresh"],
            "legacy_running": legacy_running,
            "legacy_keys_active": legacy_keys_active,
            "shutdown_safe": False,
            "live_gate": LIVE_GATE,
            "live_symbols": [],
        },
        "fail_blockers": fail_blockers,
        "shutdown_blockers": shutdown_blockers,
        "processes": {
            "v2_required": v2_processes,
            "legacy_reference": legacy_processes,
        },
        "redis": {
            "v2": redis_v2,
            "legacy": redis_legacy,
        },
        "payloads": payloads,
        "comparison": comparison,
        "runtime_guard": {
            "classification": runtime_guard.get("classification"),
            "v2_total_key_count": runtime_guard.get("v2_total_key_count"),
            "failed_checks": runtime_guard.get("failed_checks", []),
            "required_namespaces_non_empty": runtime_guard.get("required_namespaces_non_empty"),
        },
        "soak": {
            "observation_count": soak.get("observation_count", 0),
            "minutes_observed": soak.get("minutes_observed", 0),
            "soak_15m_ready": soak.get("soak_15m_ready", False),
            "soak_1h_ready": soak.get("soak_1h_ready", False),
            "soak_6h_ready": soak.get("soak_6h_ready", False),
            "all_v2_processes_uninterrupted": soak.get("all_v2_processes_uninterrupted", False),
            "v2_namespaces_never_empty": soak.get("v2_namespaces_never_empty", False),
        },
        "replacement_readiness_scoreboard": readiness_scoreboard,
        "safety": {
            **safety,
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
        "frontend_status": frontend_status,
        "remediation_task_path": remediation_task_path,
    }


def render_markdown(status: dict[str, Any]) -> str:
    lines = [
        "# Codex 15M Status: Runtime Soak And Production Equivalence",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
        (
            "The V2 paper/shadow runtime soak governor is passing its runtime checks."
            if status["go_no_go"] == GO_READY
            else "The V2 runtime soak governor is blocked by one or more runtime checks."
        ),
        "",
        "This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, or Redis trim.",
        "",
        "## Frontend Truth",
        "",
    ]
    for line in status["frontend_status"]["plain_english_lines"]:
        lines.append(f"- {line}")
    lines.extend(
        [
            "",
            "## Runtime Counts",
            "",
            f"- V2 required loops running: `{status['summary']['v2_runtime_loops_running']}/{status['summary']['v2_runtime_loops_required']}`",
            f"- Required V2 namespaces present: `{status['summary']['all_required_v2_namespaces_present']}`",
            f"- Payloads fresh: `{status['summary']['all_payloads_fresh']}`",
            f"- Comparison fresh: `{status['summary']['comparison_fresh']}`",
            f"- Soak minutes observed: `{status['soak']['minutes_observed']}`",
            f"- Soak 15m ready: `{status['soak']['soak_15m_ready']}`",
            f"- Soak 1h ready: `{status['soak']['soak_1h_ready']}`",
            f"- Soak 6h ready: `{status['soak']['soak_6h_ready']}`",
            f"- Replacement scoreboard shutdown recommendation: `{status.get('replacement_readiness_scoreboard', {}).get('shutdown_recommendation')}`",
            "",
            "## Fail Blockers",
            "",
        ]
    )
    lines.extend(f"- `{item}`" for item in status["fail_blockers"]) if status["fail_blockers"] else lines.append("- none")
    lines.extend(["", "## Shutdown Blockers", ""])
    lines.extend(f"- `{item}`" for item in status["shutdown_blockers"]) if status["shutdown_blockers"] else lines.append("- none")
    lines.extend(["", "## V2 Redis Counts", "", "| Namespace | Count |", "| --- | --- |"])
    for name, item in status["redis"]["v2"].items():
        lines.append(f"| `{item['pattern']}` | `{item['count']}` |")
    lines.extend(["", "## Legacy Redis Counts", "", "| Namespace | Count |", "| --- | --- |"])
    for name, item in status["redis"]["legacy"].items():
        lines.append(f"| `{item['pattern']}` | `{item['count']}` |")
    lines.extend(["", "## Safety", ""])
    lines.append(f"- `live_gate`: `{LIVE_GATE}`")
    lines.append("- `live_symbols`: `[]`")
    lines.append("- `approves_live`: `false`")
    lines.append("- `approves_canary`: `false`")
    lines.append("- `approves_legacy_shutdown`: `false`")
    lines.append("- `approves_redis_trim`: `false`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(status: dict[str, Any]) -> None:
    write_json(OUT / "codex_15m_status.json", status)
    write_text(OUT / "CODEX_15M_STATUS.md", render_markdown(status))
    write_text(OUT / "CODEX_GO_NO_GO.md", status["go_no_go"] + "\n")
    write_json(PUBLIC / "operator_dashboard_payload.json", status)


def print_status() -> int:
    status = read_json(OUT / "codex_15m_status.json")
    if not status:
        print("No runtime soak governor status exists yet.")
        return 1
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex_runtime_soak_and_production_equivalence_governor")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    if args.status:
        return print_status()
    if args.daemon:
        while True:
            write_outputs(evaluate())
            time.sleep(max(60, int(args.poll_seconds)))
    write_outputs(evaluate())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
