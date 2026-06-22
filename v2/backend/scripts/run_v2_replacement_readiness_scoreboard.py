"""Emit the V2 replacement readiness scoreboard."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKLOG_DIR = Path("claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest")
PUBLIC_DIR = Path("v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest")
SOAK_STATUS_PATH = WORKLOG_DIR / "soak_status.json"
COMPARE_PATH = WORKLOG_DIR / "production_equivalence_comparison.json"
SCOREBOARD_WORKLOG = WORKLOG_DIR / "v2_replacement_readiness_scoreboard.json"
SCOREBOARD_PUBLIC = PUBLIC_DIR / "v2_replacement_readiness_scoreboard.json"

V2_REQUIRED = (
    "v2.backend.app.cli.v2_native_ingestors_live_loop",
    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
    "v2.backend.app.cli.v2_rl_core_inference_loop",
    "v2.backend.app.cli.v2_orchestrator_arbitration_loop",
    "v2.backend.app.cli.v2_trade_management_paper_loop",
    "v2.backend.app.cli.v2_production_payload_freshness_refresher",
    "v2.backend.app.cli.v2_production_replacement_soak_observer",
    "v2.backend.app.cli.v2_production_equivalence_comparator",
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


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ps_running(pat: str) -> bool:
    try:
        out = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=5)
        return out.returncode == 0 and bool(out.stdout.strip())
    except Exception:
        return False


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


def _load(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def main() -> int:
    r = _connect_redis()
    v2_running = {p: _ps_running(p) for p in V2_REQUIRED}
    legacy_running = {p: _ps_running(p) for p in LEGACY_PROCESSES}
    soak = _load(SOAK_STATUS_PATH)
    cmp_payload = _load(COMPARE_PATH)
    v2_total = _count(r, "v2:*")
    legacy_pred = _count(r, "prediction:*")
    legacy_signals = _count(r, "signals:*")
    # Pull a sample paper_fill_allowed from comparator output.
    paper_fill_state = "NEGATIVE_EDGE_OR_MISSING"
    edge_state = "NOT_PROVEN_POSITIVE"
    sample_v2_match = None
    per_symbol = cmp_payload.get("per_symbol") or []
    if per_symbol:
        first = per_symbol[0]
        sample_v2_match = first.get("match")
        v2 = first.get("v2") or {}
        if v2.get("paper_fill_allowed") is True:
            paper_fill_state = "OPEN_PAPER_ONLY"
        em = v2.get("expected_move_after_cost_bps")
        if isinstance(em, (int, float)):
            edge_state = "POSITIVE_PAPER_ONLY" if em > 0 else "NEGATIVE_OR_ZERO"

    scoreboard = {
        "schema_version": "v2_replacement_readiness_scoreboard_v1",
        "generated_utc": _utc_iso(),
        "v2_runtime_running": all(v2_running.values()),
        "v2_runtime_process_status": v2_running,
        "v2_soak_15m_ready": bool(soak.get("soak_15m_ready")),
        "v2_soak_1h_ready": bool(soak.get("soak_1h_ready")),
        "v2_soak_6h_ready": bool(soak.get("soak_6h_ready")),
        "v2_writes_v2_redis": v2_total > 0,
        "v2_total_redis_key_count": v2_total,
        "legacy_still_running": any(legacy_running.values()),
        "legacy_processes_status": legacy_running,
        "legacy_still_writes_production_redis": (legacy_pred > 0 or legacy_signals > 0),
        "legacy_redis_key_counts": {"prediction:*": legacy_pred, "signals:*": legacy_signals},
        "v2_vs_legacy_comparison_available": bool(per_symbol),
        "v2_prediction_matches_legacy_or_reason": (
            "MATCH_PER_FIRST_SYMBOL" if sample_v2_match is True else
            ("LEGACY_OR_V2_PREDICTION_MISSING_OR_MISMATCH" if per_symbol else "NO_COMPARISON_AVAILABLE")
        ),
        "paper_fill_gate_state": paper_fill_state,
        "edge_state": edge_state,
        "shutdown_recommendation": "BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "next_required_fix": (
            "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED. 6h paper-only soak is "
            f"complete (minutes_observed={soak.get('minutes_observed', 0)}). "
            "Production-equivalence still blocked by missing approved "
            "checkpoint weight blob and by legacy still owning production "
            "Redis namespaces. Shutdown remains blocked. Live remains "
            "blocked_human_only."
            if bool(soak.get("soak_6h_ready")) and all(v2_running.values()) and v2_total > 0
            else (
                "Continue soak window. Minutes observed so far: "
                f"{soak.get('minutes_observed', 0)}. "
                "Wait for soak_1h_ready=true and soak_6h_ready=true while maintaining "
                "v2_runtime_running and v2_writes_v2_redis. Operator must then create the "
                "paper-only acceptance file and Codex must re-pass."
            )
        ),
    }
    body = json.dumps(scoreboard, indent=2, sort_keys=True) + "\n"
    SCOREBOARD_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    SCOREBOARD_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    SCOREBOARD_WORKLOG.write_text(body)
    SCOREBOARD_PUBLIC.write_text(body)
    print(json.dumps({
        "v2_runtime_running": scoreboard["v2_runtime_running"],
        "v2_writes_v2_redis": scoreboard["v2_writes_v2_redis"],
        "soak_1h_ready": scoreboard["v2_soak_1h_ready"],
        "soak_6h_ready": scoreboard["v2_soak_6h_ready"],
        "shutdown_recommendation": scoreboard["shutdown_recommendation"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
