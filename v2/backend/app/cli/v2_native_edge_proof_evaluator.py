"""V2 Native Edge-Proof Evaluator CLI.

Reads V2 paper/shadow inputs (paper ledger, paper intents, paper
intents held by the paper fill gate, position history, prediction,
risk decisions, orchestrator decisions, plus optional V2-vs-legacy
comparator and legacy log observer mirrors) — assembles replay
bundles — and emits the canonical edge-proof metric summary.

The evaluator never claims edge unless every operator-set threshold
is satisfied. It writes only JSON under:

  claude_worklog/final_readiness/v2_native_edge_proof/latest/
  v2/frontend/public/v2_native_edge_proof/latest/

Read-only with respect to legacy code, Redis writes outside v2:*,
exchange endpoints, approval tokens, and shutdown / live state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.edge_proof.evaluator import (  # noqa: E402
    PRIMARY_OUTCOME_WINDOW_ID,
    evaluate,
    summary_to_dict,
)
from v2.backend.app.services.edge_proof.replay_schema import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    OUTCOME_WINDOWS_SECONDS,
    OutcomeWindow,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    ReplayBundle,
    ReplayLabel,
    emit_canonical_schema,
)


WORKLOG_DIR = (
    REPO_ROOT / "claude_worklog" / "final_readiness" / "v2_native_edge_proof" / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_native_edge_proof" / "latest"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _safe_redis_read(key: str) -> Any:
    """Read v2:* key only. Returns None on any error and never writes."""
    if not key.startswith("v2:"):
        return None
    try:
        import redis  # type: ignore

        r = redis.Redis(decode_responses=True, socket_connect_timeout=2)
        r.ping()
        raw = r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None


def _legacy_reference_action_for(symbol: str) -> dict[str, Any] | None:
    """Read the V2-vs-legacy comparator's public mirror only (NEVER
    read legacy current-truth Redis keys directly). Pick the row for
    ``symbol`` if present.
    """
    mirror = (
        REPO_ROOT
        / "v2"
        / "frontend"
        / "public"
        / "v2_legacy_v2_production_comparator"
        / "latest"
        / "operator_dashboard_payload.json"
    )
    try:
        doc = json.loads(mirror.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    rows = doc.get("symbol_rows") or doc.get("per_symbol") or []
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and (row.get("symbol") or "").upper() == symbol.upper():
            action = row.get("legacy_action") or row.get("action")
            if isinstance(action, str):
                return {"action": action, "source": "v2_legacy_v2_production_comparator_mirror"}
    return None


def _features_hash(snapshot: Any) -> str | None:
    if snapshot is None:
        return None
    try:
        text = json.dumps(snapshot, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def build_outcome_windows_empty() -> dict[str, OutcomeWindow]:
    """Build empty (INSUFFICIENT_EVIDENCE) outcome windows.

    The realtime evaluator does NOT fabricate future returns — it only
    fills in outcomes that can be safely derived from existing V2
    paper data (e.g., position-history tracker realised returns).
    All others stay None with samples=0 and the bundle is labelled
    INSUFFICIENT_EVIDENCE until a later post-hoc evaluator runs.
    """
    return {
        wid: OutcomeWindow(
            window_id=wid,
            window_seconds=secs,
            return_bps=None,
            after_cost_return_bps=None,
            drawdown_bps=None,
            stop_hit=False,
            samples=0,
        )
        for wid, secs in OUTCOME_WINDOWS_SECONDS
    }


def assemble_bundles(symbols: Iterable[str], timeframe: str = "1m") -> list[ReplayBundle]:
    """Assemble one ReplayBundle per symbol from current V2 paper state.

    For ``--dry-run`` / ``--once`` use this is intentionally
    sample-of-one-per-symbol: it does NOT mine the paper ledger for
    historical bundles. The post-hoc replay miner is a separate task.
    """
    bundles: list[ReplayBundle] = []
    paper_ledger = _safe_redis_read("v2:paper:ledger") or {}
    paper_intents = _safe_redis_read("v2:paper:intents") or []
    paper_intents_held = (
        _safe_redis_read("v2:paper:intents_held_by_paper_fill_gate") or []
    )
    risk_decisions = _safe_redis_read("v2:risk:decisions") or []
    orch = _safe_redis_read("v2:orchestrator:decisions") or {}
    for symbol in symbols:
        prediction = _safe_redis_read(f"v2:prediction:{symbol}:{timeframe}") or {}
        features = _safe_redis_read(f"v2:features:latest:{symbol}:{timeframe}")
        market_price = _safe_redis_read(f"v2:market:prices:{symbol}") or {}
        market_funding = _safe_redis_read(f"v2:market:funding:{symbol}") or {}
        market_oi = _safe_redis_read(f"v2:market:open_interest:{symbol}") or {}
        liq_latest = _safe_redis_read(f"v2:market:liquidations:latest:{symbol}")
        liq_aggregate = _safe_redis_read(f"v2:market:liquidations:aggregate:{symbol}")
        altdata = _safe_redis_read(f"v2:altdata:symbol_score:{symbol}")
        position_history = _safe_redis_read(f"v2:paper:position_history:{symbol}")
        risk_row = next(
            (
                r
                for r in (risk_decisions if isinstance(risk_decisions, list) else [])
                if isinstance(r, dict)
                and (r.get("symbol") or "").upper() == symbol.upper()
            ),
            None,
        )
        legacy_reference = _legacy_reference_action_for(symbol)

        market_snapshot = {
            "price": market_price.get("price") if isinstance(market_price, dict) else None,
            "funding": market_funding if isinstance(market_funding, dict) else None,
            "open_interest": market_oi if isinstance(market_oi, dict) else None,
            "liquidations_latest": liq_latest,
            "liquidations_aggregate": liq_aggregate,
            "fee_bps": (market_price or {}).get("fee_bps") if isinstance(market_price, dict) else None,
            "slippage_estimate_bps": (market_price or {}).get("slippage_estimate_bps")
            if isinstance(market_price, dict)
            else None,
        }

        bundles.append(
            ReplayBundle(
                feature_snapshot_id=f"{symbol}:{timeframe}:{_utc_iso()}",
                prediction_id=(prediction.get("prediction_id") or f"{symbol}:{_utc_iso()}"),
                symbol=symbol,
                timeframe=timeframe,
                generated_at=_utc_iso(),
                features_hash=_features_hash(features),
                market_snapshot=market_snapshot,
                altdata_snapshot=altdata if isinstance(altdata, dict) else None,
                risk_decision=risk_row,
                trainer_output=prediction if isinstance(prediction, dict) else None,
                paper_gate_decision={
                    "paper_fill_allowed": (prediction or {}).get("paper_fill_allowed"),
                    "paper_fill_gate_block_reasons": (
                        (prediction or {}).get("paper_fill_gate_block_reasons") or []
                    ),
                    "latency_seconds": (prediction or {}).get("latency_seconds"),
                },
                orchestrator_decision=orch if isinstance(orch, dict) else None,
                paper_intent=next(
                    (
                        i
                        for i in (paper_intents if isinstance(paper_intents, list) else [])
                        if isinstance(i, dict)
                        and (i.get("symbol") or "").upper() == symbol.upper()
                    ),
                    None,
                ),
                legacy_reference_action=legacy_reference,
                future_outcomes=build_outcome_windows_empty(),
                outcome_after_cost=None,
                label=ReplayLabel.INSUFFICIENT_EVIDENCE,
            )
        )
    return bundles


def run(
    *,
    symbols: list[str],
    timeframe: str,
    thresholds_overrides: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    bundles = assemble_bundles(symbols, timeframe=timeframe)
    summary = evaluate(
        bundles,
        thresholds=thresholds_overrides,
        outcome_window=PRIMARY_OUTCOME_WINDOW_ID,
    )
    summary_dict = summary_to_dict(summary)

    canonical_schema = emit_canonical_schema()
    payload = {
        "schema_version": "v2_native_edge_proof_status_v1",
        "generated_at": _utc_iso(),
        "go_no_go": "V2_NATIVE_EDGE_PROOF_SPEC_AND_REPLAY_EVALUATOR_READY",
        "evaluator_metric_summary": summary_dict,
        "primary_outcome_window_id": PRIMARY_OUTCOME_WINDOW_ID,
        "bundle_count": len(bundles),
        "outcome_windows": [
            {"window_id": w, "window_seconds": s} for w, s in OUTCOME_WINDOWS_SECONDS
        ],
        "symbols_evaluated": symbols,
        "timeframe": timeframe,
        "canonical_input_keys": canonical_schema["canonical_input_keys"],
        "default_thresholds": dict(DEFAULT_THRESHOLDS),
        "thresholds_used": summary_dict["thresholds_used"],
        "thresholds_satisfied": summary_dict["thresholds_satisfied"],
        "no_live_approval_implied": True,
        "no_canary_approval_implied": True,
        "no_shutdown_approval_implied": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    metrics_view = {
        "schema_version": "v2_native_edge_proof_edge_metrics_summary_v1",
        "generated_at": _utc_iso(),
        "metric_summary": summary_dict,
        "primary_outcome_window_id": PRIMARY_OUTCOME_WINDOW_ID,
        "bundle_count": len(bundles),
        "verdict": summary_dict["verdict"],
        "verdict_reason": summary_dict["verdict_reason"],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    operator_dashboard = {
        "schema_version": "v2_native_edge_proof_operator_dashboard_v1",
        "generated_at": _utc_iso(),
        "go_no_go": payload["go_no_go"],
        "verdict": summary_dict["verdict"],
        "verdict_reason": summary_dict["verdict_reason"],
        "sample_count": summary_dict["sample_count"],
        "minimum_sample_satisfied": summary_dict["minimum_sample_satisfied"],
        "after_cost_pnl_delta": summary_dict["after_cost_pnl_delta"],
        "expected_move_after_cost_bps": summary_dict["expected_move_after_cost_bps"],
        "false_positive_rate": summary_dict["false_positive_rate"],
        "false_negative_rate": summary_dict["false_negative_rate"],
        "downside_pre_cascade_recall": summary_dict["downside_pre_cascade_recall"],
        "downside_pre_cascade_precision": summary_dict["downside_pre_cascade_precision"],
        "gate_block_reason_distribution": summary_dict["gate_block_reason_distribution"],
        "v2_vs_legacy_action_match_rate": summary_dict["v2_vs_legacy_action_match_rate"],
        "v2_hold_due_checkpoint_count": summary_dict["v2_hold_due_checkpoint_count"],
        "v2_hold_due_strict_gate_count": summary_dict["v2_hold_due_strict_gate_count"],
        "thresholds_used": summary_dict["thresholds_used"],
        "thresholds_satisfied": summary_dict["thresholds_satisfied"],
        "required_visible_text": [
            "Live trading is blocked.",
            "Legacy shutdown is blocked.",
            "Candidate symbols are not adopted automatically.",
            "Recovery requires proof of edge before scaling.",
            "No fake readiness.",
            "READY means evaluator exists. READY does not mean edge proven.",
        ],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }

    if not dry_run:
        _write_json(WORKLOG_DIR / "native_edge_proof_status.json", payload)
        _write_json(WORKLOG_DIR / "edge_metrics_summary.json", metrics_view)
        _write_json(WORKLOG_DIR / "replay_bundle_schema.json", canonical_schema)
        _write_json(PUBLIC_DIR / "operator_dashboard_payload.json", operator_dashboard)
        _write_json(PUBLIC_DIR / "edge_metrics_summary.json", metrics_view)
        _write_json(PUBLIC_DIR / "replay_bundle_schema.json", canonical_schema)
    return payload


def main() -> int:
    p = argparse.ArgumentParser(prog="v2_native_edge_proof_evaluator")
    p.add_argument(
        "--symbols",
        default=None,
        help="comma-separated symbols; default is the dynamic V2 universe with the 25-symbol baseline",
    )
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use BTC/ETH/SOL only for explicit smoke tests; never the default.",
    )
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    explicit = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else None
    )
    symbols = resolve_symbols(explicit=explicit, smoke_test=args.smoke_test)
    payload = run(
        symbols=symbols,
        timeframe=args.timeframe,
        thresholds_overrides=None,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        ms = payload["evaluator_metric_summary"]
        print(
            json.dumps(
                {
                    "generated_at": payload["generated_at"],
                    "go_no_go": payload["go_no_go"],
                    "verdict": ms["verdict"],
                    "sample_count": ms["sample_count"],
                    "after_cost_pnl_delta": ms["after_cost_pnl_delta"],
                    "downside_pre_cascade_recall": ms["downside_pre_cascade_recall"],
                    "v2_vs_legacy_action_match_rate": ms["v2_vs_legacy_action_match_rate"],
                    "thresholds_satisfied": ms["thresholds_satisfied"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
