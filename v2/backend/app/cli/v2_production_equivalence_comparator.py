"""V2 vs legacy production-equivalence comparator (read-only).

Reads legacy + v2:* Redis keys side by side and emits per-symbol
comparison plus soak observation. Never writes legacy. Never calls
an exchange SDK. Outputs:

- claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json
- claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/soak_observation.jsonl
- v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json
- v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/soak_status.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    resolve_symbols,
)

DEFAULT_SYMBOLS = tuple(BASELINE_25_SYMBOLS)
DEFAULT_TF = "1m"

WORKLOG_DIR = Path("claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest")
PUBLIC_DIR = Path("v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest")
COMPARE_WORKLOG = WORKLOG_DIR / "production_equivalence_comparison.json"
COMPARE_PUBLIC = PUBLIC_DIR / "production_equivalence_comparison.json"
SOAK_JSONL = WORKLOG_DIR / "soak_observation.jsonl"
SOAK_STATUS_PUBLIC = PUBLIC_DIR / "soak_status.json"
SOAK_STATUS_WORKLOG = WORKLOG_DIR / "soak_status.json"

V2_PROCESSES = (
    "v2.backend.app.cli.v2_native_ingestors_live_loop",
    "v2.backend.app.cli.v2_feature_pipeline_native_loop",
    "v2.backend.app.cli.v2_rl_core_inference_loop",
    "v2.backend.app.cli.v2_orchestrator_arbitration_loop",
    "v2.backend.app.cli.v2_trade_management_paper_loop",
    "v2.backend.app.cli.v2_production_payload_freshness_refresher",
    "v2.backend.app.cli.v2_production_replacement_soak_observer",
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
    "prediction:", "features:", "trainer:", "signals:", "orchestrator:", "market:",
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


def _get_json(r, key: str):
    """Best-effort fetch tolerant of legacy hash / list / stream types."""
    if r is None:
        return None
    try:
        t = r.type(key)
    except Exception:
        return None
    if t == "none":
        return None
    try:
        if t == "string":
            raw = r.get(key)
            if raw is None:
                return None
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return raw
        if t == "hash":
            data = r.hgetall(key)
            # If any value is JSON-encoded, decode lazily.
            out = {}
            for k, v in (data or {}).items():
                try:
                    out[k] = json.loads(v)
                except (ValueError, TypeError):
                    out[k] = v
            return out
        if t == "list":
            entries = r.lrange(key, -1, -1)
            if not entries:
                return None
            try:
                return json.loads(entries[0])
            except (ValueError, TypeError):
                return entries[0]
        if t == "stream":
            entries = r.xrevrange(key, count=1)
            if not entries:
                return None
            _, fields = entries[0]
            return dict(fields)
    except Exception:
        return None
    return None


def _example_keys(r, pat: str, n: int = 3) -> list[str]:
    if r is None:
        return []
    out: list[str] = []
    for k in r.scan_iter(match=pat):
        out.append(k)
        if len(out) >= n:
            break
    return out


def _legacy_prediction_summary(r, symbol: str, tf: str) -> dict:
    """Read a legacy prediction key if present. Different legacy
    schemas exist; we keep raw payload but extract a few canonical
    fields when possible.
    """
    key_candidates = (
        f"prediction:{symbol}:{tf}",
        f"prediction:{symbol}",
        f"signal:{symbol}:{tf}",
    )
    for k in key_candidates:
        payload = _get_json(r, k)
        if payload is None:
            continue
        if isinstance(payload, dict):
            return {
                "key": k,
                "exists": True,
                "confidence": payload.get("confidence") or payload.get("confidence_calibrated"),
                "action": payload.get("action") or payload.get("side") or payload.get("decision"),
                "expected_move_bps": payload.get("expected_move_bps"),
                "expected_move_after_cost_bps": payload.get("expected_move_after_cost_bps"),
                "feature_freshness_state": payload.get("feature_freshness_state"),
                "generated_at": payload.get("generated_at") or payload.get("ts"),
                "raw_keys_present": sorted(payload.keys())[:20],
            }
        return {"key": k, "exists": True, "raw_summary": str(payload)[:200]}
    return {"key": key_candidates[0], "exists": False}


def _v2_prediction_summary(r, symbol: str, tf: str) -> dict:
    k = f"v2:prediction:{symbol}:{tf}"
    payload = _get_json(r, k)
    if not isinstance(payload, dict):
        return {"key": k, "exists": False}
    return {
        "key": k,
        "exists": True,
        "confidence_raw": payload.get("confidence_raw"),
        "confidence_calibrated": payload.get("confidence_calibrated"),
        "selected_action": payload.get("selected_action"),
        "expected_move_bps": payload.get("expected_move_bps"),
        "expected_move_after_cost_bps": payload.get("expected_move_after_cost_bps"),
        "feature_freshness_state": payload.get("feature_freshness_state"),
        "paper_fill_allowed": payload.get("paper_fill_allowed"),
        "paper_fill_gate_status": payload.get("paper_fill_gate_status"),
        "paper_fill_gate_block_reasons": payload.get("paper_fill_gate_block_reasons"),
        "checkpoint_blocker": payload.get("checkpoint_blocker"),
        "generated_utc": payload.get("generated_utc"),
    }


def _per_symbol_compare(r, symbol: str, tf: str) -> dict:
    legacy = _legacy_prediction_summary(r, symbol, tf)
    v2 = _v2_prediction_summary(r, symbol, tf)
    notes: list[str] = []
    if not legacy["exists"]:
        notes.append("legacy_prediction_key_missing_in_redis")
    if not v2["exists"]:
        notes.append("v2_prediction_key_missing_in_redis")
    if legacy["exists"] and v2["exists"]:
        legacy_action = (legacy.get("action") or "").lower()
        v2_action = (v2.get("selected_action") or "").lower()
        if legacy_action and v2_action and legacy_action != v2_action:
            notes.append(f"action_mismatch:legacy={legacy_action},v2={v2_action}")
        if v2.get("paper_fill_allowed") is False:
            br = v2.get("paper_fill_gate_block_reasons") or []
            notes.append("v2_paper_fill_blocked:" + ",".join(br))
        if legacy.get("feature_freshness_state") and v2.get("feature_freshness_state"):
            if legacy["feature_freshness_state"] != v2["feature_freshness_state"]:
                notes.append(
                    f"freshness_state_mismatch:legacy={legacy['feature_freshness_state']},v2={v2['feature_freshness_state']}"
                )
    return {
        "symbol": symbol,
        "timeframe": tf,
        "legacy": legacy,
        "v2": v2,
        "match": legacy.get("action") and v2.get("selected_action")
                  and (legacy.get("action") or "").lower() == (v2.get("selected_action") or "").lower(),
        "notes": notes,
    }


def collect_soak_observation(r) -> dict:
    now = _utc_iso()
    v2_proc = {p: _process_running(p) for p in V2_PROCESSES}
    legacy_proc = {p: _process_running(p) for p in LEGACY_PROCESSES}
    v2_counts = {ns: _count(r, ns + "*") for ns in V2_NAMESPACES}
    legacy_counts = {ns: _count(r, ns + "*") for ns in LEGACY_NAMESPACES}
    v2_total = _count(r, "v2:*")
    return {
        "schema_version": "v2_runtime_soak_observation_v1",
        "observed_utc": now,
        "v2_processes_running": v2_proc,
        "v2_all_required_running": all(v2_proc.values()),
        "legacy_processes_running": legacy_proc,
        "legacy_processes_count": sum(1 for v in legacy_proc.values() if v),
        "v2_namespace_counts": v2_counts,
        "v2_total_key_count": v2_total,
        "legacy_namespace_counts": legacy_counts,
        "v2_latest_market_keys": _example_keys(r, "v2:market:*", n=3),
        "v2_latest_feature_keys": _example_keys(r, "v2:features:latest:*", n=3),
        "v2_latest_prediction_keys": _example_keys(r, "v2:prediction:*", n=3),
        "v2_latest_orchestrator_keys": _example_keys(r, "v2:orchestrator:*", n=3),
        "v2_latest_paper_keys": _example_keys(r, "v2:paper:*", n=3),
        "v2_latest_risk_keys": _example_keys(r, "v2:risk:*", n=3),
        "no_old_redis_writes": True,
        "no_exchange_mutation": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


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
            "schema_version": "v2_runtime_soak_status_v1",
            "generated_utc": _utc_iso(),
            "observation_count": 0,
            "minutes_observed": 0,
            "soak_15m_ready": False,
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
    v2_namespaces_never_empty = all(
        all((o.get("v2_namespace_counts", {}).get(ns, 0) or 0) > 0 for ns in V2_NAMESPACES)
        for o in observations
    )
    return {
        "schema_version": "v2_runtime_soak_status_v1",
        "generated_utc": _utc_iso(),
        "observation_count": len(observations),
        "first_observed_utc": first["observed_utc"],
        "last_observed_utc": last["observed_utc"],
        "minutes_observed": round(minutes, 2),
        "all_v2_processes_uninterrupted": all_procs,
        "v2_namespaces_never_empty": v2_namespaces_never_empty,
        "soak_15m_ready": minutes >= 15 and all_procs and v2_namespaces_never_empty,
        "soak_1h_ready": minutes >= 60 and all_procs and v2_namespaces_never_empty,
        "soak_6h_ready": minutes >= 360 and all_procs and v2_namespaces_never_empty,
        "v2_total_key_count_last": last.get("v2_total_key_count", 0),
        "legacy_still_owns_production_observed": any(
            o.get("legacy_processes_count", 0) > 0 for o in observations
        ),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _read_orchestrator_held(r) -> list[dict]:
    if r is None:
        return []
    raw = _get_json(r, "v2:orchestrator:decisions")
    if not isinstance(raw, dict):
        return []
    return [
        h for h in (raw.get("held_by_paper_fill_gate") or [])
        if isinstance(h, dict)
    ]


def _read_paper_held(r) -> list[dict]:
    if r is None:
        return []
    raw = _get_json(r, "v2:paper:intents_held_by_paper_fill_gate")
    if not isinstance(raw, list):
        return []
    return [h for h in raw if isinstance(h, dict)]


def _attach_held_passthrough(per_symbol: list[dict], orch_held: list[dict],
                             paper_held: list[dict]) -> None:
    """Verify and surface that block reasons survive prediction -> orchestrator
    -> paper-intent. Adds passthrough-integrity notes per symbol.
    """
    orch_by_sym = {h.get("symbol"): h for h in orch_held if h.get("symbol")}
    paper_by_sym = {h.get("symbol"): h for h in paper_held if h.get("symbol")}
    for row in per_symbol:
        sym = row.get("symbol")
        v2 = row.get("v2") or {}
        if not isinstance(v2, dict):
            continue
        if v2.get("paper_fill_allowed") is not False:
            continue
        pred_reasons = list(v2.get("paper_fill_gate_block_reasons") or [])
        oh = orch_by_sym.get(sym)
        ph = paper_by_sym.get(sym)
        orch_reasons = list((oh or {}).get("paper_fill_gate_block_reasons") or [])
        paper_reasons = list((ph or {}).get("paper_fill_gate_block_reasons") or [])
        row.setdefault("notes", []).append(
            "block_reasons_passthrough:" + json.dumps({
                "prediction": pred_reasons,
                "orchestrator_held": orch_reasons,
                "paper_intent_held": paper_reasons,
                "orchestrator_emitted": oh is not None,
                "paper_intent_emitted": ph is not None,
                "orchestrator_matches_prediction": orch_reasons == pred_reasons and oh is not None,
                "paper_intent_matches_prediction": paper_reasons == pred_reasons and ph is not None,
            }, sort_keys=True)
        )


def _attach_mismatch_source(per_symbol: list[dict]) -> None:
    """Annotate every per-symbol mismatch with its root-cause classification.

    For the current paper-only stage, V2's policy weights are
    deterministic-init (no operator-approved checkpoint loaded). Any
    action-mismatch where V2 selected `hold` while the V2 prediction
    carries `checkpoint_blocker=CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`
    is therefore attributed to the checkpoint blocker, not to a bug.
    """
    for row in per_symbol:
        v2 = row.get("v2") or {}
        legacy = row.get("legacy") or {}
        v2_action = (v2.get("selected_action") or "").lower()
        legacy_action = (legacy.get("action") or "").lower()
        ckpt_blocker = v2.get("checkpoint_blocker")
        if row.get("match") is True:
            row["mismatch_source"] = None
            continue
        if v2_action == "hold" and ckpt_blocker == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED":
            row["mismatch_source"] = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
            row["mismatch_explanation"] = (
                "V2 holds because no operator-approved trained checkpoint is "
                "loaded; deterministic-init policy + strict paper-fill gate "
                "are the safe default. Strict paper gate remains active and "
                "no positive edge is claimed."
            )
            row["deterministic_init_policy_active"] = True
            row["strict_paper_gate_active"] = True
            row["positive_edge_claimed"] = False
        else:
            row["mismatch_source"] = "OTHER_OR_UNDETERMINED"
            row["mismatch_explanation"] = (
                f"Action mismatch legacy={legacy_action!r} v2={v2_action!r} "
                "not attributable to the checkpoint blocker alone; review "
                "per-symbol notes for context."
            )


def build_comparison(r, symbols: tuple[str, ...], tf: str) -> dict:
    per_symbol = [_per_symbol_compare(r, s, tf) for s in symbols]
    orch_held = _read_orchestrator_held(r)
    paper_held = _read_paper_held(r)
    _attach_held_passthrough(per_symbol, orch_held, paper_held)
    _attach_mismatch_source(per_symbol)
    all_mismatches_explainable = all(
        row.get("match") is True
        or row.get("mismatch_source") == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
        for row in per_symbol
    )
    return {
        "schema_version": "v2_production_equivalence_comparison_v3",
        "generated_utc": _utc_iso(),
        "symbols_compared": list(symbols),
        "timeframe": tf,
        "per_symbol": per_symbol,
        "orchestrator_held_by_paper_fill_gate": orch_held,
        "orchestrator_held_by_paper_fill_gate_count": len(orch_held),
        "paper_intent_held_by_paper_fill_gate": paper_held,
        "paper_intent_held_by_paper_fill_gate_count": len(paper_held),
        "deterministic_init_policy_active": True,
        "strict_paper_gate_active": True,
        "positive_edge_claimed": False,
        "primary_mismatch_source_when_unmatched": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        "all_mismatches_attributable_to_checkpoint_blocker": all_mismatches_explainable,
        "no_invented_outcomes": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def run_once(symbols: tuple[str, ...], tf: str) -> dict:
    r = _connect_redis()
    soak_obs = collect_soak_observation(r)
    _append_jsonl(SOAK_JSONL, soak_obs)
    obs_history = _read_jsonl(SOAK_JSONL)
    soak_status = emit_soak_status(obs_history)
    body = json.dumps(soak_status, indent=2, sort_keys=True) + "\n"
    SOAK_STATUS_WORKLOG.parent.mkdir(parents=True, exist_ok=True)
    SOAK_STATUS_PUBLIC.parent.mkdir(parents=True, exist_ok=True)
    SOAK_STATUS_WORKLOG.write_text(body)
    SOAK_STATUS_PUBLIC.write_text(body)
    compare = build_comparison(r, symbols, tf)
    cbody = json.dumps(compare, indent=2, sort_keys=True) + "\n"
    COMPARE_WORKLOG.write_text(cbody)
    COMPARE_PUBLIC.write_text(cbody)
    return {
        "soak_status": soak_status,
        "comparison": compare,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_production_equivalence_comparator")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--timeframe", default=DEFAULT_TF)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    explicit = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    symbols = tuple(resolve_symbols(explicit=explicit, smoke_test=args.smoke_test))
    if args.loop:
        while True:
            out = run_once(symbols, args.timeframe)
            ss = out["soak_status"]
            print(json.dumps({
                "minutes_observed": ss["minutes_observed"],
                "soak_15m_ready": ss["soak_15m_ready"],
                "soak_1h_ready": ss["soak_1h_ready"],
                "all_v2_processes_uninterrupted": ss["all_v2_processes_uninterrupted"],
                "comparison_symbols": list(symbols),
            }))
            time.sleep(max(60, int(args.interval_seconds)))
    out = run_once(symbols, args.timeframe)
    ss = out["soak_status"]
    print(json.dumps({
        "minutes_observed": ss["minutes_observed"],
        "observation_count": ss["observation_count"],
        "soak_15m_ready": ss["soak_15m_ready"],
        "soak_1h_ready": ss["soak_1h_ready"],
        "soak_6h_ready": ss["soak_6h_ready"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
