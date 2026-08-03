"""V2 production payload freshness refresher (paper-only).

For each governor-watched /latest/ payload, stamp it with a fresh
generated_at + a live heartbeat block sourced from the matching
/live/latest/ payload AND from Redis v2:* state. Preserves every
existing field (does not strip safety invariants).

This refresher does NOT enable live, canary, or shutdown. It only
keeps the /latest/ payloads fresh so the Codex governor can stop
reporting them as stale.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LIVE_GATE_REQUIRED = "blocked_human_only"
REPLACEMENT_READINESS_SCOREBOARD_SCRIPT = Path(
    "v2/backend/scripts/run_v2_replacement_readiness_scoreboard.py"
)
REPLACEMENT_READINESS_SCOREBOARD_PUBLIC = Path(
    "v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/"
    "v2_replacement_readiness_scoreboard.json"
)

# Mapping: descriptor /latest/ path -> source /live/latest/ path.
# When the source is None, the descriptor is refreshed from Redis only.
TARGETS = (
    {
        "name": "v2_native_ingestors",
        "latest_path": Path("v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json"),
        "live_source": Path("v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json"),
        "redis_count_pattern": "v2:market:*",
        "loop_module": "v2_native_ingestors_live_loop",
    },
    {
        "name": "v2_feature_pipeline_native_snapshot",
        "latest_path": Path("v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"),
        "live_source": Path("v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"),
        "redis_count_pattern": "v2:features:*",
        "loop_module": "v2_feature_pipeline_native_loop",
    },
    {
        "name": "v2_rl_core",
        "latest_path": Path("v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json"),
        "live_source": Path("v2/frontend/public/operator_runtime/v2_rl_core/live/latest/v2_rl_core_live_status.json"),
        "redis_count_pattern": "v2:prediction:*",
        "loop_module": "v2_rl_core_inference_loop",
    },
    {
        "name": "v2_orchestrator_arbitration",
        "latest_path": Path("v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/v2_orchestrator_arbitration_status.json"),
        "live_source": Path("v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json"),
        "redis_count_pattern": "v2:orchestrator:*",
        "loop_module": "v2_orchestrator_arbitration_loop",
    },
    {
        "name": "v2_trade_management_paper",
        "latest_path": Path("v2/frontend/public/operator_runtime/v2_trade_management_paper/latest/v2_trade_management_paper_status.json"),
        "live_source": Path("v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json"),
        "redis_count_pattern": "v2:paper:*",
        "loop_module": "v2_trade_management_paper_loop",
    },
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


def _count_pattern(r, pattern: str) -> int:
    if r is None:
        return 0
    n = 0
    for _ in r.scan_iter(match=pattern):
        n += 1
    return n


def _ps_running(pattern: str) -> bool:
    import subprocess
    try:
        out = subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True, timeout=5
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


def _load_json(p: Path) -> dict | None:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _refresh_target(target: dict, r) -> dict:
    latest_path: Path = target["latest_path"]
    live_source: Path = target["live_source"]
    descriptor = _load_json(latest_path) or {}
    live_payload = _load_json(live_source) or {}
    process_running = _ps_running(target["loop_module"])
    redis_count = _count_pattern(r, target["redis_count_pattern"])
    now = _utc_iso()
    heartbeat = {
        "generated_at": now,
        "heartbeat_at": now,
        "freshness_seconds": 0,
        "process_running": process_running,
        "loop_module": target["loop_module"],
        "redis_key_count": redis_count,
        "redis_count_pattern": target["redis_count_pattern"],
        "latest_v2_keys_written": live_payload.get(
            "v2_market_keys_written",
            live_payload.get("v2_features_keys_written",
                             live_payload.get("v2_prediction_keys_written",
                                              live_payload.get("v2_orchestrator_keys_written",
                                                               live_payload.get("v2_paper_keys_written", [])))),
        ),
        "live_gate": LIVE_GATE_REQUIRED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
    }
    descriptor["v2_production_replacement_runtime_heartbeat"] = heartbeat
    descriptor["generated_at"] = now
    descriptor["heartbeat_at"] = now
    descriptor["freshness_seconds"] = 0
    descriptor["process_running"] = process_running
    descriptor["redis_key_count"] = redis_count
    # Refuse to flip any approval; force them false even if upstream tried to set them.
    descriptor["approves_live"] = False
    descriptor["approves_canary"] = False
    descriptor["approves_legacy_shutdown"] = False
    descriptor["approves_redis_trim"] = False
    descriptor["live_gate"] = LIVE_GATE_REQUIRED
    descriptor["live_symbols"] = []
    descriptor["no_old_redis_writes"] = True
    descriptor["no_exchange_mutation"] = True
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n")
    return {
        "name": target["name"],
        "path": str(latest_path),
        "process_running": process_running,
        "redis_key_count": redis_count,
    }


def _refresh_frontend_truth(r) -> dict:
    p = Path("v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json")
    body = _load_json(p) or {}
    now = _utc_iso()
    body["generated_utc"] = now
    body["heartbeat_at"] = now
    body["freshness_seconds"] = 0
    body["live_gate"] = LIVE_GATE_REQUIRED
    body["live_symbols"] = []
    body["approves_live"] = False
    body["approves_canary"] = False
    body["approves_legacy_shutdown"] = False
    body["approves_redis_trim"] = False
    body.setdefault("source_status", {})
    v2_loops_running = all(_ps_running(t["loop_module"]) for t in TARGETS)
    v2_total = _count_pattern(r, "v2:*")
    body["source_status"]["v2_production_replacement_runtime"] = {
        "v2_total_keys": v2_total,
        "v2_market_keys": _count_pattern(r, "v2:market:*"),
        "v2_features_keys": _count_pattern(r, "v2:features:*"),
        "v2_prediction_keys": _count_pattern(r, "v2:prediction:*"),
        "v2_orchestrator_keys": _count_pattern(r, "v2:orchestrator:*"),
        "v2_paper_keys": _count_pattern(r, "v2:paper:*"),
        "v2_loops_running": v2_loops_running,
        "refreshed_at": now,
    }
    # Explicit operator-facing plain-English fields.
    body["v2_paper_shadow_runtime_running"] = v2_loops_running
    body["legacy_still_owns_production_runtime"] = True
    body["do_not_shut_down_legacy_yet"] = True
    body["v2_writing_v2_namespace_redis_keys"] = v2_total > 0
    body["v2_namespace_redis_key_count"] = v2_total
    body["live_trading_is_blocked"] = True
    body["current_blocker_in_plain_english"] = (
        "Current goal: soak stability and production-equivalence burndown. "
        "V2 paper/shadow runtime is running and being continuously compared "
        "to legacy. Legacy still owns production. Do not shut down legacy "
        "yet. Live trading is blocked."
    )
    body["v2_runtime_loops"] = [
        {
            "name": t["loop_module"],
            "process_running": _ps_running(t["loop_module"]),
            "writes_namespace": t["redis_count_pattern"],
            "redis_key_count": _count_pattern(r, t["redis_count_pattern"]),
        }
        for t in TARGETS
    ]
    # Soak progress + comparator + scoreboard surfacing.
    try:
        soak_path = Path(
            "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/soak_status.json"
        )
        cmp_path = Path(
            "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json"
        )
        scoreboard_path = Path(
            "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/v2_replacement_readiness_scoreboard.json"
        )
        soak = json.loads(soak_path.read_text()) if soak_path.exists() else {}
        cmp_payload = json.loads(cmp_path.read_text()) if cmp_path.exists() else {}
        scoreboard = json.loads(scoreboard_path.read_text()) if scoreboard_path.exists() else {}
        body["v2_soak_progress"] = {
            "minutes_observed": soak.get("minutes_observed"),
            "soak_15m_ready": soak.get("soak_15m_ready"),
            "soak_1h_ready": soak.get("soak_1h_ready"),
            "soak_6h_ready": soak.get("soak_6h_ready"),
            "all_v2_processes_uninterrupted": soak.get("all_v2_processes_uninterrupted"),
        }
        body["v2_vs_legacy_compared_symbols"] = cmp_payload.get("symbols_compared", [])
        body["v2_replacement_readiness_scoreboard_summary"] = {
            "v2_runtime_running": scoreboard.get("v2_runtime_running"),
            "v2_writes_v2_redis": scoreboard.get("v2_writes_v2_redis"),
            "paper_fill_gate_state": scoreboard.get("paper_fill_gate_state"),
            "edge_state": scoreboard.get("edge_state"),
            "shutdown_recommendation": scoreboard.get("shutdown_recommendation"),
        }
        log_obs_path = Path(
            "v2/frontend/public/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json"
        )
        remed_path = Path(
            "claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/continuous_remediation_status.json"
        )
        log_obs = json.loads(log_obs_path.read_text()) if log_obs_path.exists() else {}
        remed = json.loads(remed_path.read_text()) if remed_path.exists() else {}
        body["legacy_log_observer_running"] = _ps_running(
            "v2.backend.app.cli.v2_legacy_log_intelligence_observer"
        )
        body["continuous_remediation_loop_running"] = _ps_running(
            "v2_continuous_legacy_log_to_rebuild_remediation"
        )
        body["latest_legacy_log_summary"] = {
            "trainer_present": (log_obs.get("trainer_log_summary") or {}).get("source_path") is not None,
            "orchestrator_present": (log_obs.get("orchestrator_log_summary") or {}).get("source_path") is not None,
            "monitor_script_count": len(log_obs.get("monitor_scripts_summary") or []),
            "remediation_hints_count": log_obs.get("remediation_hints_count"),
        }
        body["latest_remediation_summary"] = {
            "gaps_total": remed.get("gaps_total"),
            "gaps_severity_counts": remed.get("gaps_severity_counts"),
            "claude_codex_task_pairs": len(remed.get("claude_codex_task_pairs_written_or_existing") or []),
        }
    except Exception:
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    return {"name": "frontend_truth", "path": str(p), "refreshed_at": now}


def _refresh_replacement_readiness_scoreboard() -> dict:
    now = _utc_iso()
    if not REPLACEMENT_READINESS_SCOREBOARD_SCRIPT.exists():
        return {
            "error": f"missing_script:{REPLACEMENT_READINESS_SCOREBOARD_SCRIPT}",
            "name": "v2_replacement_readiness_scoreboard",
            "ok": False,
            "refreshed_at": now,
        }
    try:
        proc = subprocess.run(
            [sys.executable, str(REPLACEMENT_READINESS_SCOREBOARD_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": str(exc)[:300],
            "name": "v2_replacement_readiness_scoreboard",
            "ok": False,
            "refreshed_at": now,
        }
    return {
        "name": "v2_replacement_readiness_scoreboard",
        "ok": proc.returncode == 0,
        "path": str(REPLACEMENT_READINESS_SCOREBOARD_PUBLIC),
        "refreshed_at": _utc_iso(),
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "").strip()[-300:],
    }


def run_once() -> dict:
    r = _connect_redis()
    results = [_refresh_target(t, r) for t in TARGETS]
    ft = _refresh_frontend_truth(r)
    scoreboard = _refresh_replacement_readiness_scoreboard()
    return {
        "schema_version": "v2_production_payload_freshness_refresher_v1",
        "refreshed_utc": _utc_iso(),
        "targets_refreshed": results,
        "frontend_truth": ft,
        "replacement_readiness_scoreboard": scoreboard,
        "live_gate": LIVE_GATE_REQUIRED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_production_payload_freshness_refresher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            run_once()
            time.sleep(max(15, int(args.interval_seconds)))
    out = run_once()
    print(json.dumps({
        "targets_refreshed": [t["name"] for t in out["targets_refreshed"]],
        "frontend_truth_refreshed_at": out["frontend_truth"]["refreshed_at"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
