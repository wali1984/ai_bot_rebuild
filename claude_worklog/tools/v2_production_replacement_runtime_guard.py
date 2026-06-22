"""V2 production replacement runtime guard.

Runs the five V2 production-equivalent loops once each, verifies the
expected v2:* Redis namespaces are non-empty, emits a heartbeat
payload, and refuses to say "monitoring ready" unless the required
chain is live.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
V2_REDIS_PREFIX = "v2:"
WORKLOG_STATUS = (
    REPO
    / "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/runtime_guard_status.json"
)
PUBLIC_STATUS = (
    REPO
    / "v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest/runtime_guard_status.json"
)
WORKLOG_STATUS_MD = (
    REPO
    / "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/RUNTIME_GUARD_STATUS.md"
)

PHASES = ("ingestors", "features", "rl_core", "orchestrator", "trade_mgmt")
EXPECTED_NAMESPACES = (
    "v2:market:",
    "v2:features:",
    "v2:prediction:",
    "v2:orchestrator:",
    "v2:signals:paper",
    "v2:paper:",
    "v2:risk:",
    "v2:trainer:",
)
REQUIRED_PROCESSES = (
    "v2.backend.app.cli.v2_native_ingestors_live_loop",
    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
    "v2.backend.app.cli.v2_rl_core_inference_loop",
    "v2.backend.app.cli.v2_orchestrator_arbitration_loop",
    "v2.backend.app.cli.v2_trade_management_paper_loop",
    "v2.backend.app.cli.v2_production_payload_freshness_refresher",
    "v2.backend.app.cli.v2_production_equivalence_comparator",
    "claude_worklog/tools/v2_production_replacement_runtime_guard.py",
    "claude_worklog/tools/v2_legacy_v2_production_comparator.py",
)
FRESHNESS_MAX_AGE_S = 180
LIVE_PAYLOADS_TO_CHECK = (
    "v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json",
    "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/live/latest/v2_feature_pipeline_native_live_status.json",
    "v2/frontend/public/operator_runtime/v2_rl_core/live/latest/v2_rl_core_live_status.json",
    "v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json",
    "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json",
)


def _process_running(pattern: str) -> bool:
    import subprocess
    try:
        out = subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _payload_fresh(path: str) -> tuple[bool, int]:
    import os as _os
    import time as _time
    if not _os.path.exists(path):
        return False, -1
    try:
        age = int(_time.time() - _os.path.getmtime(path))
    except OSError:
        return False, -1
    return age <= FRESHNESS_MAX_AGE_S, age


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _count_pattern(r, pattern: str) -> int:
    if r is None:
        return 0
    n = 0
    for _ in r.scan_iter(match=pattern):
        n += 1
    return n


def _run_phase(phase: str) -> dict:
    cmd = [
        ".venv/bin/python",
        "v2/backend/scripts/run_v2_production_chain_once.py",
        "--phase",
        phase,
    ]
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    try:
        r = subprocess.run(
            cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60
        )
        return {
            "phase": phase,
            "returncode": r.returncode,
            "stdout_tail": (r.stdout or "")[-400:],
            "stderr_tail": (r.stderr or "")[-200:],
        }
    except Exception as exc:
        return {
            "phase": phase,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": f"{type(exc).__name__}: {exc}",
        }


def run_guard() -> dict:
    started = _utc_iso()
    phases_results = [_run_phase(p) for p in PHASES]
    r = _connect_redis()
    redis_ok = r is not None
    namespace_counts = {ns: _count_pattern(r, ns + "*") for ns in EXPECTED_NAMESPACES}
    total_v2 = _count_pattern(r, f"{V2_REDIS_PREFIX}*")
    required_workers_running = all(p["returncode"] == 0 for p in phases_results)
    namespace_non_empty = all(
        namespace_counts[ns] > 0
        for ns in (
            "v2:market:", "v2:features:", "v2:prediction:",
            "v2:orchestrator:", "v2:paper:", "v2:risk:", "v2:trainer:",
        )
    )
    process_status = {p: _process_running(p) for p in REQUIRED_PROCESSES}
    all_required_processes_running = all(process_status.values())
    payload_freshness = {p: _payload_fresh(p) for p in LIVE_PAYLOADS_TO_CHECK}
    all_payloads_fresh = all(ok for ok, _ in payload_freshness.values())
    failed_checks: list[str] = []
    if not redis_ok:
        failed_checks.append("redis_unavailable")
    for p, ok in process_status.items():
        if not ok:
            failed_checks.append(f"process_missing:{p}")
    if not namespace_non_empty:
        for ns in (
            "v2:market:", "v2:features:", "v2:prediction:",
            "v2:orchestrator:", "v2:paper:", "v2:risk:", "v2:trainer:",
        ):
            if namespace_counts[ns] == 0:
                failed_checks.append(f"namespace_empty:{ns}*")
    for path, (ok, age) in payload_freshness.items():
        if not ok:
            failed_checks.append(f"payload_stale:{path}:age_seconds={age}")
    if not required_workers_running:
        failed_checks.append("phase_returncode_nonzero")
    if not failed_checks:
        classification = "V2_PRODUCTION_REPLACEMENT_RUNTIME_READY_STABLE"
    elif required_workers_running and namespace_non_empty and redis_ok:
        classification = "V2_PRODUCTION_REPLACEMENT_RUNTIME_LIVE"
    else:
        classification = "V2_PRODUCTION_REPLACEMENT_RUNTIME_DEGRADED"
    status = {
        "schema_version": "v2_production_replacement_runtime_guard_v2",
        "started_at": started,
        "finished_at": _utc_iso(),
        "phases": phases_results,
        "redis_ok": redis_ok,
        "v2_namespace_counts": namespace_counts,
        "v2_total_key_count": total_v2,
        "required_workers_returncode_ok": required_workers_running,
        "required_namespaces_non_empty": namespace_non_empty,
        "required_processes_status": process_status,
        "all_required_processes_running": all_required_processes_running,
        "live_payload_freshness": {p: {"fresh": ok, "age_seconds": age} for p, (ok, age) in payload_freshness.items()},
        "all_payloads_fresh": all_payloads_fresh,
        "failed_checks": failed_checks,
        "classification": classification,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }
    return status


def write_outputs(status: dict) -> None:
    body = json.dumps(status, indent=2, sort_keys=True) + "\n"
    WORKLOG_STATUS.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_STATUS.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_STATUS.write_text(body)
    PUBLIC_STATUS.write_text(body)
    md = [
        "# V2 Production Replacement Runtime Guard Status",
        "",
        f"Generated: `{status['finished_at']}`",
        f"Classification: `{status['classification']}`",
        f"Total v2:* keys: `{status['v2_total_key_count']}`",
        "",
        "## Per-namespace counts",
        "",
    ]
    for ns, n in status["v2_namespace_counts"].items():
        md.append(f"- `{ns}*` -> {n}")
    md.append("")
    md.append("## Per-phase results")
    md.append("")
    for p in status["phases"]:
        md.append(
            f"- phase=`{p['phase']}` returncode={p['returncode']} stdout_tail=`{p['stdout_tail'].strip()}`"
        )
    md.append("")
    md.append("## Safety posture")
    md.append("")
    md.append("- live_gate: blocked_human_only")
    md.append("- live_symbols: []")
    md.append("- approves_live: false")
    md.append("- approves_legacy_shutdown: false")
    md.append("- writes_legacy_redis: false")
    md.append("- places_exchange_orders: false")
    WORKLOG_STATUS_MD.write_text("\n".join(md) + "\n")


def main(argv: list[str] | None = None) -> int:
    import time
    parser = argparse.ArgumentParser(prog="v2_production_replacement_runtime_guard")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            status = run_guard()
            write_outputs(status)
            time.sleep(max(30, int(args.interval_seconds)))
    status = run_guard()
    write_outputs(status)
    print(json.dumps({
        "classification": status["classification"],
        "v2_total_key_count": status["v2_total_key_count"],
        "required_namespaces_non_empty": status["required_namespaces_non_empty"],
    }))
    cls = status["classification"]
    return 0 if (cls.endswith("_LIVE") or cls.endswith("_STABLE")) else 2


if __name__ == "__main__":
    sys.exit(main())
