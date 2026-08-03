"""V2 production replacement runtime soak observer (paper-only).

Every interval (default 300s) records a JSONL observation:

- v2 / legacy process status (paper-only)
- v2:* Redis namespace counts + legacy namespace counts
- v2 heartbeat timestamps
- V2 latest decision examples + legacy latest decision examples
- paper-intent / paper-edge status
- safety invariants

Targets:

- 1-hour V2 runtime stability packet (60 minutes of observations)
- 6-hour V2 runtime stability packet (360 minutes of observations)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2_REDIS_PREFIX = "v2:"
JSONL_PATH = Path("claude_worklog/final_readiness/v2_production_replacement_runtime/latest/soak_observation.jsonl")
SOAK_STATUS_PUBLIC = Path("v2/frontend/public/operator_runtime/v2_production_replacement_runtime/latest/soak_status.json")
SOAK_STATUS_WORKLOG = Path("claude_worklog/final_readiness/v2_production_replacement_runtime/latest/soak_status.json")

V2_PROCESSES = (
    "v2.backend.app.cli.v2_native_ingestors_live_loop",
    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
    "v2.backend.app.cli.v2_rl_core_inference_loop",
    "v2.backend.app.cli.v2_orchestrator_arbitration_loop",
    "v2.backend.app.cli.v2_trade_management_paper_loop",
    "v2.backend.app.cli.v2_production_payload_freshness_refresher",
    "claude_worklog/tools/v2_production_replacement_runtime_guard.py",
    "claude_worklog/tools/v2_legacy_v2_production_comparator.py",
)
LEGACY_PROCESSES = (
    "ingest/live_binance.py",
    "ingest/live_binance_liquidations.py",
    "ingest/live_coinank.py",
    "ingest/live_kucoin.py",
    "ingest/live_coinapi_v1.py",
    "ingest/live_coinapi_wsds.py",
    "feature_pipeline.py",
    "rl.hybrid_trainer",
    "rl.orchestrator_worker",
    "monitor_portfolio_primary.py",
)
V2_NAMESPACES = (
    "v2:market:", "v2:features:", "v2:prediction:", "v2:trainer:",
    "v2:orchestrator:", "v2:signals:paper", "v2:paper:", "v2:risk:",
)
LEGACY_NAMESPACES = (
    "prediction:", "signals:", "kc:", "rl:", "heartbeat:", "binance:",
)


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


def _count(r, pat: str) -> int:
    if r is None:
        return 0
    n = 0
    for _ in r.scan_iter(match=pat):
        n += 1
    return n


def _process_running(pat: str) -> bool:
    try:
        out = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=5)
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _example_keys(r, pat: str, n: int = 3) -> list[str]:
    if r is None:
        return []
    out: list[str] = []
    for k in r.scan_iter(match=pat):
        out.append(k)
        if len(out) >= n:
            break
    return out


def _get_paper_ledger_snapshot(r) -> dict | None:
    if r is None:
        return None
    raw = r.get("v2:paper:ledger")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def collect_observation() -> dict:
    now = _utc_iso()
    r = _connect_redis()
    v2_proc = {p: _process_running(p) for p in V2_PROCESSES}
    legacy_proc = {p: _process_running(p) for p in LEGACY_PROCESSES}
    v2_counts = {ns: _count(r, ns + "*") for ns in V2_NAMESPACES}
    legacy_counts = {ns: _count(r, ns + "*") for ns in LEGACY_NAMESPACES}
    v2_total = _count(r, f"{V2_REDIS_PREFIX}*")
    ledger = _get_paper_ledger_snapshot(r)
    obs = {
        "schema_version": "v2_production_replacement_soak_observation_v1",
        "observed_utc": now,
        "v2_processes_running": v2_proc,
        "v2_all_required_running": all(v2_proc.values()),
        "legacy_processes_running": legacy_proc,
        "legacy_still_owns_production": any(legacy_proc.values()),
        "v2_namespace_counts": v2_counts,
        "v2_total_key_count": v2_total,
        "legacy_namespace_counts": legacy_counts,
        "v2_latest_decision_examples": _example_keys(r, "v2:prediction:*", n=5),
        "legacy_latest_decision_examples": _example_keys(r, "prediction:*", n=5),
        "paper_intent_accepted_count": (ledger or {}).get("accepted_count", 0),
        "paper_intent_blocked_count": (ledger or {}).get("blocked_count", 0),
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
    }
    return obs


def _append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(obj, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except (ValueError, TypeError):
            continue
    return out


def emit_soak_status(observations: list[dict]) -> dict:
    if not observations:
        return {
            "schema_version": "v2_production_replacement_soak_status_v1",
            "generated_utc": _utc_iso(),
            "observation_count": 0,
            "minutes_observed": 0,
            "all_v2_processes_uninterrupted": False,
            "v2_namespaces_never_empty": False,
            "soak_1h_ready": False,
            "soak_6h_ready": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }
    first = observations[0]
    last = observations[-1]
    first_ts = datetime.fromisoformat(first["observed_utc"].replace("Z", "+00:00"))
    last_ts = datetime.fromisoformat(last["observed_utc"].replace("Z", "+00:00"))
    minutes = (last_ts - first_ts).total_seconds() / 60.0
    all_procs = all(o.get("v2_all_required_running") for o in observations)
    namespaces_non_empty = all(
        all((o.get("v2_namespace_counts", {}).get(ns, 0) or 0) > 0 for ns in V2_NAMESPACES)
        for o in observations
    )
    paper_min = min((o.get("paper_intent_accepted_count", 0) for o in observations), default=0)
    paper_max = max((o.get("paper_intent_accepted_count", 0) for o in observations), default=0)
    return {
        "schema_version": "v2_production_replacement_soak_status_v1",
        "generated_utc": _utc_iso(),
        "observation_count": len(observations),
        "first_observed_utc": first["observed_utc"],
        "last_observed_utc": last["observed_utc"],
        "minutes_observed": round(minutes, 2),
        "all_v2_processes_uninterrupted": all_procs,
        "v2_namespaces_never_empty": namespaces_non_empty,
        "soak_1h_ready": minutes >= 60 and all_procs and namespaces_non_empty,
        "soak_6h_ready": minutes >= 360 and all_procs and namespaces_non_empty,
        "paper_intent_accepted_count_min": paper_min,
        "paper_intent_accepted_count_max": paper_max,
        "legacy_still_owns_production_observed": any(
            o.get("legacy_still_owns_production") for o in observations
        ),
        "v2_total_key_count_last": last.get("v2_total_key_count", 0),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def run_once() -> dict:
    obs = collect_observation()
    _append_jsonl(JSONL_PATH, obs)
    observations = _read_jsonl(JSONL_PATH)
    status = emit_soak_status(observations)
    body = json.dumps(status, indent=2, sort_keys=True) + "\n"
    SOAK_STATUS_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    SOAK_STATUS_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    SOAK_STATUS_WORKLOG.write_text(body)
    SOAK_STATUS_PUBLIC.write_text(body)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_production_replacement_soak_observer")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            status = run_once()
            print(json.dumps({
                "minutes_observed": status["minutes_observed"],
                "soak_1h_ready": status["soak_1h_ready"],
                "all_v2_processes_uninterrupted": status["all_v2_processes_uninterrupted"],
            }))
            time.sleep(max(60, int(args.interval_seconds)))
    status = run_once()
    print(json.dumps({
        "observation_count": status["observation_count"],
        "minutes_observed": status["minutes_observed"],
        "soak_1h_ready": status["soak_1h_ready"],
        "soak_6h_ready": status["soak_6h_ready"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
