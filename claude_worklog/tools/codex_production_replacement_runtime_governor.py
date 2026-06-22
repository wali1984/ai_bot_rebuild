#!/usr/bin/env python3
"""Codex production-replacement runtime governor.

Read-only runtime verifier for the V2 production-equivalent paper/shadow
replacement stack. This intentionally does not start workers, write Redis, touch
legacy, or perform exchange actions. It records whether V2 is actually running
production-equivalent paper/shadow loops and writing V2 namespace state.
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
OUT = ROOT / "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/codex_governor"
PUBLIC = ROOT / "v2/frontend/public/v2_production_replacement_runtime/latest"
TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/tasks"

GO_READY = "CODEX_PRODUCTION_REPLACEMENT_RUNTIME_GOVERNOR_READY"
GO_BLOCKED = "CODEX_PRODUCTION_REPLACEMENT_RUNTIME_GOVERNOR_BLOCKED"
LIVE_GATE = "blocked_human_only"

LEGACY_REQUIRED = {
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

V2_REQUIRED = {
    "v2_native_ingestors_live_loop": "v2_native_ingestors_live_loop",
    "v2_feature_pipeline_native_loop": "v2_feature_pipeline_native_loop",
    "v2_rl_core_inference_loop": "v2_rl_core_inference_loop",
    "v2_orchestrator_arbitration_loop": "v2_orchestrator_arbitration_loop",
    "v2_trade_management_paper_loop": "v2_trade_management_paper_loop",
    "v2_production_replacement_runtime_guard": "v2_production_replacement_runtime_guard.py",
    "legacy_v2_comparator": "codex_legacy_v2_realtime_decision_observatory.py",
}

REDIS_REQUIRED_PATTERNS = {
    "v2_all": "v2:*",
    "v2_market": "v2:market:*",
    "v2_features": "v2:features:*",
    "v2_prediction": "v2:prediction:*",
    "v2_orchestrator": "v2:orchestrator:*",
    "v2_paper": "v2:paper:*",
}

LEGACY_SIGNAL_PATTERNS = {
    "prediction": "prediction:*",
    "features": "features:*",
    "market": "market:*",
    "trainer": "trainer:*",
    "signals": "signals:*",
    "orchestrator": "orchestrator:*",
}

REQUESTED_PROCESS_CHECKS = {
    "legacy_production": "pgrep -af 'live_binance|live_coinank|live_kucoin|feature_pipeline|hybrid_trainer|orchestrator_worker'",
    "v2_replacement": "pgrep -af 'v2_native_ingestors_live_loop|v2_feature_pipeline_native_loop|v2_rl_core_inference_loop|v2_orchestrator_arbitration_loop|v2_trade_management_paper_loop'",
}

REQUESTED_REDIS_CHECKS = {
    "v2": "redis-cli KEYS 'v2:*' | wc -l",
    "prediction": "redis-cli KEYS 'prediction:*' | wc -l",
    "features": "redis-cli KEYS 'features:*' | wc -l",
    "signals": "redis-cli KEYS 'signals:*' | wc -l",
}

PAYLOADS = {
    "v2_native_ingestors_live": ROOT / "v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json",
    "v2_feature_pipeline_native_live": ROOT / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/live/latest/v2_feature_pipeline_native_live_status.json",
    "v2_rl_core_live": ROOT / "v2/frontend/public/operator_runtime/v2_rl_core/live/latest/v2_rl_core_live_status.json",
    "v2_orchestrator_arbitration_live": ROOT / "v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json",
    "v2_trade_management_paper_live": ROOT / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json",
    "legacy_v2_comparator": ROOT / "claude_worklog/final_readiness/legacy_v2_realtime_decision_observatory/latest/operator_dashboard_payload.json",
    "frontend_truth": ROOT / "v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json",
}

REMEDIATION_TASK_ID = "claude_v2_production_replacement_runtime_loop_implementation"


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


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
        "as_of_utc",
        "last_updated",
    ):
        parsed = parse_time(payload.get(key))
        if parsed is not None:
            return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))
    return None


def process_lines() -> list[str]:
    proc = run(["ps", "-eo", "pid,ppid,stat,etime,cmd", "--width", "360"], timeout=10)
    return proc.stdout.splitlines()


def process_status(required: dict[str, str], lines: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, pattern in required.items():
        matches = [
            line.strip()
            for line in lines
            if pattern in line
            and " rg " not in line
            and "grep" not in line
            and "bash -lc" not in line
        ]
        out[name] = {
            "pattern": pattern,
            "running": bool(matches),
            "match_count": len(matches),
            "sample": matches[:5],
        }
    return out


def redis_scan_count(pattern: str, limit_sample: int = 20) -> dict[str, Any]:
    try:
        proc = run(["redis-cli", "--scan", "--pattern", pattern], timeout=20)
        keys = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return {
            "pattern": pattern,
            "available": proc.returncode == 0,
            "count": len(keys),
            "sample": keys[:limit_sample],
            "stderr": proc.stderr.strip()[:500],
        }
    except Exception as exc:
        return {"pattern": pattern, "available": False, "count": 0, "sample": [], "stderr": repr(exc)}


def run_requested_process_check(command: str) -> dict[str, Any]:
    proc = run(["bash", "-lc", command], timeout=10)
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return {
        "command": command,
        "returncode": proc.returncode,
        "running_count": len(lines),
        "matched": bool(lines),
        "sample": lines[:20],
        "stderr": proc.stderr.strip()[:500],
    }


def run_requested_redis_check(command: str) -> dict[str, Any]:
    proc = run(["bash", "-lc", command], timeout=20)
    text = proc.stdout.strip()
    try:
        count = int(text.splitlines()[-1]) if text else 0
    except Exception:
        count = 0
    return {
        "command": command,
        "returncode": proc.returncode,
        "count": count,
        "stdout": text[:200],
        "stderr": proc.stderr.strip()[:500],
    }


def requested_command_checks() -> dict[str, Any]:
    return {
        "cadence": "every_15_minutes",
        "process_checks": {
            name: run_requested_process_check(command) for name, command in REQUESTED_PROCESS_CHECKS.items()
        },
        "redis_checks": {name: run_requested_redis_check(command) for name, command in REQUESTED_REDIS_CHECKS.items()},
    }


def payload_status(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    exists = path.exists()
    text = ""
    if exists:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:300_000]
        except Exception:
            text = ""
    age = payload_age_seconds(payload) if isinstance(payload, dict) else None
    stale = age is None or age > 900
    lower = text.lower()
    unsafe_truth_terms = [term for term in ("mock", "static", "fixture", "hist_") if term in lower]
    return {
        "path": str(path.relative_to(ROOT)),
        "exists": exists,
        "json_object": isinstance(payload, dict) and bool(payload),
        "age_seconds": age,
        "fresh": bool(exists and isinstance(payload, dict) and not stale),
        "stale_or_missing": stale,
        "live_gate": payload.get("live_gate") if isinstance(payload, dict) else None,
        "live_symbols": payload.get("live_symbols") if isinstance(payload, dict) else None,
        "approves_live": payload.get("approves_live") if isinstance(payload, dict) else None,
        "approves_canary": payload.get("approves_canary") if isinstance(payload, dict) else None,
        "approves_legacy_shutdown": payload.get("approves_legacy_shutdown") if isinstance(payload, dict) else None,
        "unsafe_truth_terms": unsafe_truth_terms[:10],
    }


def source_declarations() -> dict[str, int]:
    scans = {
        "missing_in_v2": "MISSING_IN_V2",
        "paper_only": "PAPER_ONLY|paper-only",
        "fail_closed": "FAIL_CLOSED|fail-closed",
        "approves_legacy_shutdown_false": 'approves_legacy_shutdown["\\\']?\\s*[:=]\\s*False|approves_legacy_shutdown"\\s*:\\s*false',
    }
    out: dict[str, int] = {}
    roots = [ROOT / "v2/backend/app", ROOT / "v2/frontend/public/operator_runtime"]
    for name, pattern in scans.items():
        compiled = re.compile(pattern)
        count = 0
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".map"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                count += len(compiled.findall(text))
        out[name] = count
    return out


def ensure_remediation_task(blockers: list[str]) -> str:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = TASKS_DIR / f"{REMEDIATION_TASK_ID}.json"
    payload = {
        "task_id": REMEDIATION_TASK_ID,
        "agent": "claude",
        "risk_level": "L2",
        "status": "pending",
        "lane": "primary_claude_lane",
        "cwd": str(ROOT),
        "emit_files": True,
        "blocked_by": [],
        "next_gate": "V2_PRODUCTION_REPLACEMENT_RUNTIME_LOOP_IMPLEMENTATION_READY",
        "allowed_output_prefixes": [
            "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/claude_remediation/",
            "v2/frontend/public/v2_production_replacement_runtime/latest/",
        ],
        "required_output_files": [
            "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/claude_remediation/PRODUCTION_REPLACEMENT_RUNTIME_LOOP_IMPLEMENTATION_REPORT.md",
            "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/claude_remediation/production_replacement_runtime_loop_status.json",
            "v2/frontend/public/v2_production_replacement_runtime/latest/operator_dashboard_payload.json",
        ],
        "prompt": (
            "Implement V2 production-equivalent paper/shadow runtime loops. Work only in AI BOT REBUILD. "
            "Do not modify /home/wali/Desktop/AI BOT. Do not stop legacy. Do not write old Redis. "
            "Do not place/cancel/modify orders. Do not change leverage or margin. Do not enable live. "
            "live_gate remains blocked_human_only and live_symbols remains []. Required running loops: "
            "v2_native_ingestors_live_loop, v2_feature_pipeline_native_loop, v2_rl_core_inference_loop, "
            "v2_orchestrator_arbitration_loop, v2_trade_management_paper_loop, and a runtime guard. "
            "They must write only v2:* Redis namespace keys: v2:market:*, v2:features:*, v2:prediction:*, "
            "v2:orchestrator:*, v2:paper:*; never legacy production keys. Payloads must be fresh, V2-owned, "
            "and not mock/static/current-truth fixtures. Current blockers from Codex governor: "
            + "; ".join(blockers[:30])
        ),
        "next_recommended_action": "After implementation, rerun codex_production_replacement_runtime_governor.py --once.",
    }
    write_json(path, payload)
    return str(path.relative_to(ROOT))


def frontend_status(command_checks: dict[str, Any], blockers: list[str]) -> dict[str, Any]:
    process_checks = command_checks.get("process_checks", {})
    legacy_count = int(process_checks.get("legacy_production", {}).get("running_count") or 0)
    v2_count = int(process_checks.get("v2_replacement", {}).get("running_count") or 0)
    if legacy_count > 0 and v2_count == 0:
        headline = "Legacy still owns production."
        lines = [
            "Legacy still owns production.",
            "V2 replacement runtime is not running yet.",
            "Do not shut down legacy.",
        ]
        severity = "HARD_NO_GO"
    elif legacy_count > 0:
        headline = "Legacy still owns production."
        lines = [
            "Legacy still owns production.",
            "V2 replacement runtime is running, but it is not cleared to replace legacy.",
            "Do not shut down legacy.",
        ]
        severity = "NO_GO"
    elif v2_count == 0:
        headline = "V2 replacement runtime is not running yet."
        lines = [
            "V2 replacement runtime is not running yet.",
            "Do not shut down legacy.",
        ]
        severity = "HARD_NO_GO"
    elif blockers:
        headline = "V2 replacement runtime still has blockers."
        lines = [
            "V2 replacement runtime is running, but blockers remain.",
            "Do not shut down legacy.",
        ]
        severity = "NO_GO"
    else:
        headline = "V2 replacement runtime is running for paper and shadow."
        lines = [
            "V2 replacement runtime is running for paper and shadow.",
            "Live trading is still blocked.",
            "Do not shut down legacy unless the final Codex gate approves it.",
        ]
        severity = "WATCH_ONLY"
    return {
        "surface": "frontend",
        "severity": severity,
        "headline": headline,
        "plain_english_lines": lines,
        "conditional_required_message": {
            "condition": "legacy pgrep has matches and V2 replacement pgrep has zero matches",
            "lines": [
                "Legacy still owns production.",
                "V2 replacement runtime is not running yet.",
                "Do not shut down legacy.",
            ],
        },
        "live_gate": LIVE_GATE,
        "live_symbols": [],
    }


def evaluate() -> dict[str, Any]:
    now = utc_now()
    lines = process_lines()
    legacy = process_status(LEGACY_REQUIRED, lines)
    v2 = process_status(V2_REQUIRED, lines)
    redis_v2 = {name: redis_scan_count(pattern) for name, pattern in REDIS_REQUIRED_PATTERNS.items()}
    redis_legacy = {name: redis_scan_count(pattern) for name, pattern in LEGACY_SIGNAL_PATTERNS.items()}
    payloads = {name: payload_status(path) for name, path in PAYLOADS.items()}
    declarations = source_declarations()
    command_checks = requested_command_checks()

    blockers: list[str] = []
    if not all(item["running"] for item in v2.values()):
        missing = [name for name, item in v2.items() if not item["running"]]
        blockers.append("V2_PRODUCTION_EQUIVALENT_LOOPS_NOT_RUNNING: " + ", ".join(missing))
    if any(item["running"] for item in legacy.values()):
        blockers.append("LEGACY_STILL_OWNS_PRODUCTION_RUNTIME")
    if redis_v2["v2_all"]["count"] <= 0:
        blockers.append("V2_REDIS_NAMESPACE_EMPTY")
    for name in ("v2_market", "v2_features", "v2_prediction", "v2_orchestrator", "v2_paper"):
        if redis_v2[name]["count"] <= 0:
            blockers.append(f"{name.upper()}_REDIS_KEYS_MISSING")
    if any(item["count"] > 0 for item in redis_legacy.values()):
        blockers.append("LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE")
    stale_payloads = [name for name, item in payloads.items() if item["stale_or_missing"]]
    if stale_payloads:
        blockers.append("V2_PAYLOADS_STALE_OR_MISSING: " + ", ".join(stale_payloads))
    unsafe_terms = [name for name, item in payloads.items() if item["unsafe_truth_terms"]]
    if unsafe_terms:
        blockers.append("PAYLOADS_CONTAIN_MOCK_STATIC_OR_FIXTURE_TERMS: " + ", ".join(unsafe_terms))

    live_violations = []
    for name, item in payloads.items():
        if item["live_gate"] not in (None, LIVE_GATE):
            live_violations.append(f"{name}.live_gate={item['live_gate']}")
        if item["live_symbols"] not in (None, []):
            live_violations.append(f"{name}.live_symbols={item['live_symbols']}")
        if item["approves_live"] is True or item["approves_canary"] is True:
            live_violations.append(f"{name}.live_or_canary_approval")
    if live_violations:
        blockers.append("LIVE_SAFETY_PAYLOAD_VIOLATION: " + ", ".join(live_violations[:10]))

    if declarations.get("missing_in_v2", 0) > 0 or declarations.get("approves_legacy_shutdown_false", 0) > 0:
        blockers.append("V2_SOURCE_STILL_SELF_DECLARES_MISSING_OR_NO_SHUTDOWN_APPROVAL")

    remediation_task_path = ensure_remediation_task(blockers) if blockers else None
    go_no_go = GO_READY if not blockers else GO_BLOCKED
    frontend = frontend_status(command_checks, blockers)

    return {
        "schema_version": "codex_production_replacement_runtime_governor_v1",
        "generated_utc": now,
        "go_no_go": go_no_go,
        "summary": {
            "runtime_governor_ready": True,
            "production_replacement_runtime_ready": not blockers,
            "legacy_shutdown_safe": False,
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "blocker_count": len(blockers),
        },
        "blockers": blockers,
        "process_ownership": {
            "legacy_required": legacy,
            "v2_required": v2,
        },
        "redis_ownership": {
            "v2_namespace": redis_v2,
            "legacy_production_like": redis_legacy,
            "uses_readonly_scan": True,
        },
        "requested_command_checks": command_checks,
        "frontend_status": frontend,
        "payload_ownership": payloads,
        "source_declarations": declarations,
        "safety": {
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "old_redis_write_performed": False,
            "exchange_mutation_performed": False,
        },
        "remediation_task_path": remediation_task_path,
    }


def render_markdown(status: dict[str, Any]) -> str:
    legacy_running = sum(1 for item in status["process_ownership"]["legacy_required"].values() if item["running"])
    v2_running = sum(1 for item in status["process_ownership"]["v2_required"].values() if item["running"])
    v2_required = len(status["process_ownership"]["v2_required"])
    redis_v2_total = status["redis_ownership"]["v2_namespace"]["v2_all"]["count"]
    frontend = status.get("frontend_status", {})
    command_checks = status.get("requested_command_checks", {})
    lines = [
        "# Codex 15M Runtime Status: V2 Production Replacement Runtime",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
        (
            "The governor is installed and reporting, but the production-equivalent "
            "V2 runtime is blocked."
            if status["go_no_go"] == GO_BLOCKED
            else "The governor sees the required production-equivalent paper/shadow runtime loops."
        ),
        "",
        "This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, or Redis trim.",
        "",
        "## Current Runtime Facts",
        "",
        f"- Legacy production-like processes running: `{legacy_running}`",
        f"- Required V2 production-equivalent loops running: `{v2_running}/{v2_required}`",
        f"- Redis `v2:*` key count: `{redis_v2_total}`",
        f"- `live_gate`: `{LIVE_GATE}`",
        "- `live_symbols`: `[]`",
        "",
        "## Frontend Status",
        "",
    ]
    for item in frontend.get("plain_english_lines", []):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Requested Command Checks",
            "",
            "| Check | Command | Result | Count |",
            "| --- | --- | --- | --- |",
        ]
    )
    for name, item in command_checks.get("process_checks", {}).items():
        lines.append(
            f"| `{name}` | `{item['command']}` | `matched={item['matched']}` | `{item['running_count']}` |"
        )
    for name, item in command_checks.get("redis_checks", {}).items():
        lines.append(f"| `redis_{name}` | `{item['command']}` | `returncode={item['returncode']}` | `{item['count']}` |")
    lines.extend(
        [
            "",
        "## Blockers",
        "",
        ]
    )
    if status["blockers"]:
        lines.extend(f"- `{item}`" for item in status["blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Required V2 Loops",
            "",
            "| Loop | Running | Match count |",
            "| --- | --- | --- |",
        ]
    )
    for name, item in status["process_ownership"]["v2_required"].items():
        lines.append(f"| `{name}` | `{item['running']}` | `{item['match_count']}` |")
    lines.extend(["", "## Redis V2 Namespace", "", "| Pattern | Count |", "| --- | --- |"])
    for name, item in status["redis_ownership"]["v2_namespace"].items():
        lines.append(f"| `{item['pattern']}` | `{item['count']}` |")
    lines.extend(["", "## Remediation", ""])
    if status.get("remediation_task_path"):
        lines.append(f"Created/updated Claude remediation task: `{status['remediation_task_path']}`")
    else:
        lines.append("No remediation task needed.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(status: dict[str, Any]) -> None:
    write_json(OUT / "codex_15m_runtime_status.json", status)
    write_text(OUT / "CODEX_15M_RUNTIME_STATUS.md", render_markdown(status))
    write_text(OUT / "CODEX_GO_NO_GO.md", status["go_no_go"] + "\n")
    write_json(PUBLIC / "operator_dashboard_payload.json", status)


def print_status() -> int:
    status = read_json(OUT / "codex_15m_runtime_status.json")
    if not status:
        print("No production replacement runtime governor status exists yet.")
        return 1
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
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
