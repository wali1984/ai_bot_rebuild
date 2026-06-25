"""V2 post-hoc replay outcome miner CLI.

Each invocation:

1. Appends the current ``v2:market:prices:{symbol}`` snapshot into the
   per-symbol price-timeline JSONL on disk.
2. Harvests paper evidence rows from ``v2:paper:ledger``,
   ``v2:paper:intents``, and ``v2:paper:intents_held_by_paper_fill_gate``
   and merges them into the replay-bundles JSONL store (dedup by
   intent_id).
3. Fills any outcome window (1m / 5m / 15m / 1h) whose endpoint now has
   a price timeline point.
4. Re-classifies the bundle's label objectively from the realized
   after-cost outcome plus the paper gate decision.
5. Feeds the mined bundles into the existing V2 native edge-proof
   evaluator and writes the refreshed metrics summary and operator
   dashboard payload.

Safety: read-only with respect to Redis (only ``v2:*``), the exchange,
and the legacy bot tree. Writes JSONL state under
``claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/state/``
and JSON status / dashboard payloads under the corresponding
``latest/`` directories.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.edge_proof.replay_schema import (  # noqa: E402
    OUTCOME_WINDOWS_SECONDS,
    OutcomeWindow,
    ReplayBundle,
    ReplayLabel,
)
from v2.backend.app.services.edge_proof.evaluator import (  # noqa: E402
    PRIMARY_OUTCOME_WINDOW_ID,
    evaluate,
    summary_to_dict,
)
from v2.backend.app.services.edge_proof.replay_miner import (  # noqa: E402
    PUBLIC_DIR,
    REPLAY_BUNDLES_PATH,
    STATE_DIR,
    WORKLOG_DIR,
    load_filled_bundles,
    load_eval_bundles_or_fallback,
    backfill_all_replay_bundle_stores,
    mine_once,
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _outcome_dict_to_window(d: dict[str, Any]) -> OutcomeWindow:
    return OutcomeWindow(
        window_id=d.get("window_id") or "",
        window_seconds=int(d.get("window_seconds") or 0),
        return_bps=d.get("return_bps"),
        after_cost_return_bps=d.get("after_cost_return_bps"),
        drawdown_bps=d.get("drawdown_bps"),
        stop_hit=bool(d.get("stop_hit")),
        samples=int(d.get("samples") or 0),
    )


def _dict_to_bundle(b: dict[str, Any]) -> ReplayBundle:
    outs: dict[str, OutcomeWindow] = {}
    for wid, secs in OUTCOME_WINDOWS_SECONDS:
        row = (b.get("future_outcomes") or {}).get(wid) or {
            "window_id": wid, "window_seconds": secs,
        }
        outs[wid] = _outcome_dict_to_window(row)
    label_value = b.get("label") or ReplayLabel.INSUFFICIENT_EVIDENCE.value
    try:
        label = ReplayLabel(label_value)
    except Exception:  # noqa: BLE001
        label = ReplayLabel.INSUFFICIENT_EVIDENCE
    return ReplayBundle(
        feature_snapshot_id=b.get("feature_snapshot_id") or "",
        prediction_id=b.get("prediction_id") or "",
        symbol=b.get("symbol") or "",
        timeframe=b.get("timeframe") or "1m",
        generated_at=b.get("generated_at") or "",
        features_hash=b.get("features_hash"),
        market_snapshot=b.get("market_snapshot") or {},
        altdata_snapshot=b.get("altdata_snapshot"),
        risk_decision=b.get("risk_decision"),
        trainer_output=b.get("trainer_output"),
        paper_gate_decision=b.get("paper_gate_decision"),
        orchestrator_decision=b.get("orchestrator_decision"),
        paper_intent=b.get("paper_intent"),
        legacy_reference_action=b.get("legacy_reference_action"),
        future_outcomes=outs,
        outcome_after_cost=b.get("outcome_after_cost"),
        label=label,
    )


def _label_counts(bundles: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for b in bundles:
        lab = b.get("label") or ReplayLabel.INSUFFICIENT_EVIDENCE.value
        counts[lab] = counts.get(lab, 0) + 1
    return counts


def _windows_filled_counts(bundles: list[dict[str, Any]]) -> dict[str, int]:
    counts = {wid: 0 for wid, _ in OUTCOME_WINDOWS_SECONDS}
    for b in bundles:
        outs = b.get("future_outcomes") or {}
        for wid, _ in OUTCOME_WINDOWS_SECONDS:
            row = outs.get(wid) or {}
            if row.get("after_cost_return_bps") is not None:
                counts[wid] += 1
    return counts


def run(*, symbols: tuple[str, ...]) -> dict[str, Any]:
    mine_status = mine_once(symbols=symbols)
    # Defensive: re-tag any persisted bundle whose market_snapshot still
    # carries the legacy cost-model marker (Codex re-review remediation).
    # This is idempotent on already-tagged rows.
    backfill_status = backfill_all_replay_bundle_stores()
    bundle_dicts = load_eval_bundles_or_fallback()
    bundles = [_dict_to_bundle(b) for b in bundle_dicts]
    summary = evaluate(bundles, outcome_window=PRIMARY_OUTCOME_WINDOW_ID)
    summary_dict = summary_to_dict(summary)

    label_counts = _label_counts(bundle_dicts)
    windows_filled = _windows_filled_counts(bundle_dicts)
    sufficient_5m = windows_filled.get("5m", 0)
    insufficient_5m = max(0, len(bundle_dicts) - sufficient_5m)

    status_payload = {
        "schema_version": "v2_post_hoc_replay_outcome_miner_status_v1",
        "generated_at": _utc_iso(),
        "go_no_go": "V2_POST_HOC_REPLAY_OUTCOME_MINER_READY",
        "symbols": list(symbols),
        "mining_cycle": mine_status,
        "bundles_total": len(bundle_dicts),
        "label_counts": label_counts,
        "windows_filled": windows_filled,
        "windows_insufficient_5m_evidence": insufficient_5m,
        "primary_outcome_window_id": PRIMARY_OUTCOME_WINDOW_ID,
        "outcome_windows": [
            {"window_id": wid, "window_seconds": secs}
            for wid, secs in OUTCOME_WINDOWS_SECONDS
        ],
        "cost_model_note": "DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE_OPERATOR_DECISION_REQUIRED",
        "cost_model_operator_override_required": True,
        "cost_model_default_fee_bps_visible": 5.0,
        "cost_model_default_slippage_estimate_bps_visible": 2.0,
        "cost_model_backfill": backfill_status,
        "evaluator_metric_summary": summary_dict,
        "feeds_into_native_edge_proof_evaluator": True,
        "no_fabricated_outcomes": True,
        "uses_only_v2_namespaces_and_comparator_mirror": True,
        "no_live_approval_implied": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }

    metrics_view = {
        "schema_version": "v2_post_hoc_replay_outcome_miner_edge_metrics_summary_v1",
        "generated_at": _utc_iso(),
        "bundles_total": len(bundle_dicts),
        "label_counts": label_counts,
        "windows_filled": windows_filled,
        "primary_outcome_window_id": PRIMARY_OUTCOME_WINDOW_ID,
        "metric_summary": summary_dict,
        "verdict": summary_dict["verdict"],
        "verdict_reason": summary_dict["verdict_reason"],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }

    operator_dashboard = {
        "schema_version": "v2_post_hoc_replay_outcome_miner_operator_dashboard_v1",
        "generated_at": _utc_iso(),
        "go_no_go": status_payload["go_no_go"],
        "verdict": summary_dict["verdict"],
        "verdict_reason": summary_dict["verdict_reason"],
        "bundles_total": len(bundle_dicts),
        "label_counts": label_counts,
        "windows_filled": windows_filled,
        "primary_outcome_window_id": PRIMARY_OUTCOME_WINDOW_ID,
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
        "fee_drag_bps": summary_dict["fee_drag_bps"],
        "slippage_estimate_bps": summary_dict["slippage_estimate_bps"],
        "thresholds_used": summary_dict["thresholds_used"],
        "thresholds_satisfied": summary_dict["thresholds_satisfied"],
        "required_visible_text": [
            "Live trading is blocked.",
            "Legacy shutdown is blocked.",
            "Candidate symbols are not adopted automatically.",
            "Recovery requires proof of edge before scaling.",
            "No fake readiness.",
            "READY means miner exists. READY does not mean edge proven.",
        ],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_fabricated_outcomes": True,
    }

    _write_json(WORKLOG_DIR / "post_hoc_replay_outcome_status.json", status_payload)
    _write_json(WORKLOG_DIR / "edge_metrics_summary.json", metrics_view)
    _write_json(WORKLOG_DIR / "operator_dashboard_payload.json", operator_dashboard)
    _write_json(PUBLIC_DIR / "post_hoc_replay_outcome_status.json", status_payload)
    _write_json(PUBLIC_DIR / "edge_metrics_summary.json", metrics_view)
    _write_json(PUBLIC_DIR / "operator_dashboard_payload.json", operator_dashboard)
    # The replay bundles JSONL is the canonical history store.
    if REPLAY_BUNDLES_PATH.exists():
        target = WORKLOG_DIR / "replay_outcome_bundles.jsonl"
        target.write_text(
            REPLAY_BUNDLES_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        # Mirror to public for the frontend operator dashboard. Bundle
        # payloads carry no secrets (already filtered to v2:* sources +
        # comparator mirror).
        (PUBLIC_DIR / "replay_outcome_bundles.jsonl").write_text(
            REPLAY_BUNDLES_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    # Also refresh the native edge-proof evaluator's edge_metrics_summary
    # so the existing dashboard reflects the mined evidence.
    native_dir = (
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_native_edge_proof"
        / "latest"
    )
    native_public = (
        REPO_ROOT / "v2" / "frontend" / "public" / "v2_native_edge_proof" / "latest"
    )
    _write_json(native_dir / "edge_metrics_summary.json", metrics_view)
    _write_json(native_public / "edge_metrics_summary.json", metrics_view)

    return status_payload


def main() -> int:
    p = argparse.ArgumentParser(prog="v2_post_hoc_replay_outcome_miner")
    p.add_argument("--symbols", default=None)
    p.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use BTC/ETH/SOL only for explicit smoke tests; never the default.",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    explicit = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    symbols = tuple(resolve_symbols(explicit=explicit, smoke_test=args.smoke_test))
    state = run(symbols=symbols)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True, default=str))
    else:
        ms = state["evaluator_metric_summary"]
        print(json.dumps({
            "generated_at": state["generated_at"],
            "go_no_go": state["go_no_go"],
            "bundles_total": state["bundles_total"],
            "label_counts": state["label_counts"],
            "windows_filled": state["windows_filled"],
            "verdict": ms["verdict"],
            "live_gate": state["live_gate"],
            "live_symbols": state["live_symbols"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
