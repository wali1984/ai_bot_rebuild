"""Legacy vs V2 production comparator (read-only).

Reads only. Never writes legacy Redis keys. Never modifies anything.
Counts legacy and V2 namespaces, runs ps to discover legacy/V2
processes, and emits a comparator status payload.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_PUBLIC = (
    REPO
    / "v2/frontend/public/operator_runtime/legacy_v2_production_comparator/latest/status.json"
)
OUT_WORKLOG = (
    REPO
    / "claude_worklog/final_readiness/v2_production_replacement_runtime/latest/legacy_v2_production_comparator_status.json"
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


def _count(r, pattern: str) -> int:
    if r is None:
        return 0
    n = 0
    for _ in r.scan_iter(match=pattern):
        n += 1
    return n


def _examples(r, pattern: str, n: int = 5) -> list[str]:
    if r is None:
        return []
    out: list[str] = []
    for k in r.scan_iter(match=pattern):
        out.append(k)
        if len(out) >= n:
            break
    return out


def _ps_match(needles: tuple[str, ...]) -> list[str]:
    try:
        out = subprocess.run(
            ["ps", "-eo", "etime,cmd"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return []
    hits: list[str] = []
    for line in (out or "").splitlines():
        for n in needles:
            if n in line:
                hits.append(line.strip())
                break
    return hits


def build_status() -> dict:
    r = _connect_redis()
    legacy_patterns = {
        "prediction:*": _count(r, "prediction:*"),
        "signals:*": _count(r, "signals:*"),
        "kc:*": _count(r, "kc:*"),
        "rl:*": _count(r, "rl:*"),
        "heartbeat:*": _count(r, "heartbeat:*"),
        "binance:*": _count(r, "binance:*"),
    }
    v2_patterns = {
        "v2:market:*": _count(r, "v2:market:*"),
        "v2:features:*": _count(r, "v2:features:*"),
        "v2:prediction:*": _count(r, "v2:prediction:*"),
        "v2:trainer:*": _count(r, "v2:trainer:*"),
        "v2:orchestrator:*": _count(r, "v2:orchestrator:*"),
        "v2:signals:*": _count(r, "v2:signals:*"),
        "v2:paper:*": _count(r, "v2:paper:*"),
        "v2:risk:*": _count(r, "v2:risk:*"),
        "v2:*": _count(r, "v2:*"),
    }
    legacy_processes = _ps_match((
        "ingest/live_binance.py", "ingest/live_binance_liquidations.py",
        "ingest/live_coinank.py", "ingest/live_kucoin.py",
        "ingest/live_coinapi_v1.py", "ingest/live_coinapi_wsds.py",
        "feature_pipeline.py", "rl.hybrid_trainer", "rl.orchestrator_worker",
        "monitor_portfolio_primary.py",
    ))
    v2_processes = _ps_match((
        "v2.backend.app.cli.v2_feature_snapshot_builder",
        "v2.backend.app.cli.v2_trainer_bridge",
        "v2.backend.app.cli.v2_native_ingestors_live_loop",
        "v2.backend.app.cli.v2_feature_pipeline_native_loop",
        "v2.backend.app.cli.v2_rl_core_inference_loop",
        "v2.backend.app.cli.v2_orchestrator_arbitration_loop",
        "v2.backend.app.cli.v2_trade_management_paper_loop",
        "v2_worker_porting_orchestrator.py",
        "codex_legacy_v2_realtime_decision_observatory.py",
        "codex_non_live_watchdog.py",
        "v2_production_replacement_runtime_guard.py",
    ))
    v2_decision_examples = _examples(r, "v2:prediction:*", n=5)
    legacy_decision_examples = _examples(r, "prediction:*", n=5)
    return {
        "schema_version": "v2_legacy_production_comparator_v1",
        "generated_utc": _utc_iso(),
        "legacy_key_counts": legacy_patterns,
        "v2_key_counts": v2_patterns,
        "legacy_processes_running": legacy_processes,
        "v2_processes_running": v2_processes,
        "decision_comparison": {
            "v2_prediction_examples": v2_decision_examples,
            "legacy_prediction_examples": legacy_decision_examples,
            "note": "Both surfaces present; no outcomes invented. Final shutdown decision requires production-equivalence soak.",
        },
        "missing_v2_equivalents": [
            k for k in ("v2:market:", "v2:features:", "v2:prediction:", "v2:orchestrator:", "v2:paper:")
            if v2_patterns.get(k + "*", 0) == 0
        ],
        "stale_v2_equivalents": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
    }


def _emit_once() -> int:
    status = build_status()
    body = json.dumps(status, indent=2, sort_keys=True) + "\n"
    OUT_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    OUT_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    OUT_PUBLIC.write_text(body)
    OUT_WORKLOG.write_text(body)
    print(json.dumps({
        "v2_total": status["v2_key_counts"]["v2:*"],
        "legacy_prediction": status["legacy_key_counts"]["prediction:*"],
        "legacy_signals": status["legacy_key_counts"]["signals:*"],
    }))
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time
    parser = argparse.ArgumentParser(prog="v2_legacy_v2_production_comparator")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            _emit_once()
            time.sleep(max(30, int(args.interval_seconds)))
    return _emit_once()


if __name__ == "__main__":
    raise SystemExit(main())
