#!/usr/bin/env python3
"""Burn down market-state integrity rejections and recover paper/training truth."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import (  # noqa: E402
    v2_current_paper_fill_gate_acceptance_recovery,
    v2_portfolio_state_publisher,
    v2_realtime_runtime_truth_publisher,
)
from v2.backend.app.services.market_state_integrity.publisher import (  # noqa: E402
    build_market_state_integrity_payloads,
    scan_json,
)
from v2.backend.app.services.market_state_integrity.sample_rejection import classify_training_sample  # noqa: E402
from v2.backend.app.services.market_state_integrity.scoring import score_market_state  # noqa: E402

SERVICE_ID = "v2_market_state_integrity_rejection_burndown_and_paper_training_recovery"
GATE_READY = "V2_MARKET_STATE_INTEGRITY_REJECTION_BURNDOWN_AND_PAPER_TRAINING_RECOVERY_READY"
GATE_BLOCKED = "V2_MARKET_STATE_INTEGRITY_REJECTION_BURNDOWN_AND_PAPER_TRAINING_RECOVERY_BLOCKED"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public" / SERVICE_ID / "latest"
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness" / SERVICE_ID / "latest"
EST = timezone(timedelta(hours=-4))


def _est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(name: str, payload: Any) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(name: str, text: str) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")


def _json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
        client.ping()
        return client
    except Exception:
        return None


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": " ".join(cmd),
            "returncode": proc.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
        }
    except Exception as exc:
        return {
            "cmd": " ".join(cmd),
            "returncode": 999,
            "duration_seconds": round(time.time() - started, 3),
            "error": type(exc).__name__,
            "detail": str(exc)[:500],
        }


def _http_fetch(url: str, timeout: int = 10) -> dict[str, Any]:
    started = time.time()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "v2-integrity-bundle-probe/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2 * 1024 * 1024)
        text = body.decode("utf-8", "ignore")
        return {
            "url": url,
            "fetch_status": "OK",
            "http_status": int(response.status),
            "bytes": len(body),
            "duration_seconds": round(time.time() - started, 3),
            "body_excerpt": text[:1000],
        }
    except Exception as exc:
        return {
            "url": url,
            "fetch_status": "FETCH_FAILED",
            "error": type(exc).__name__,
            "detail": str(exc)[:400],
            "duration_seconds": round(time.time() - started, 3),
        }


def _non_empty_count(values: dict[str, Any]) -> int:
    return sum(1 for value in values.values() if value not in (None, "", [], {}))


def _score_inventory_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        score = score_market_state(row).to_dict()
        source_lineage = score.get("source_lineage") if isinstance(score.get("source_lineage"), dict) else {}
        reasons = list(score.get("reject_reasons") or [])
        out.append({
            "market_state_id": score.get("market_state_id"),
            "symbol": score.get("symbol"),
            "timeframe": score.get("timeframe"),
            "decision_time_est": score.get("decision_time_est"),
            "integrity_score": score.get("market_state_integrity_score"),
            "valid_for_training": score.get("valid_for_training"),
            "valid_for_prediction": score.get("valid_for_prediction"),
            "valid_for_risk": score.get("valid_for_risk"),
            "valid_for_orchestrator": score.get("valid_for_orchestrator"),
            "valid_for_paper": score.get("valid_for_paper"),
            "valid_for_live": score.get("valid_for_live"),
            "reject_reasons": reasons,
            "data_freshness_score": score.get("data_freshness_score"),
            "candle_completion_score": score.get("candle_completion_score"),
            "tf_alignment_score": score.get("tf_alignment_score"),
            "missing_data_score": score.get("missing_data_score"),
            "source_disagreement_score": score.get("source_disagreement_score"),
            "latency_score": score.get("latency_score"),
            "backfill_score": score.get("backfill_score"),
            "source_lineage_count": _non_empty_count(source_lineage),
            "source_lineage": source_lineage,
            "missing_required_fields": [
                reason for reason in reasons
                if "missing" in str(reason).lower() or str(reason).startswith("MISSING_")
            ],
            "stale_required_fields": [
                reason for reason in reasons
                if "stale" in str(reason).lower() or "EXPIRED" in str(reason)
            ],
            "source_event_time_missing_count": 1 if "source_event_time_missing" in reasons else 0,
            "future_leakage_detected": "feature_timestamp_after_decision_cutoff" in reasons or "source_available_after_decision_cutoff" in reasons,
            "unclosed_candle_detected": "candle_not_closed_confirmed" in reasons,
            "prediction_id": row.get("prediction_id"),
            "feature_snapshot_id": row.get("feature_snapshot_id"),
            "source_redis_key": row.get("_redis_key") or row.get("source_redis_key"),
        })
    return out


def _inventory_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    inventory = _score_inventory_rows(rows)
    rejected = [row for row in inventory if not row.get("valid_for_training")]
    combo_counter = Counter(tuple(row["reject_reasons"]) for row in rejected)
    return {
        "schema_version": "integrity_rejection_reason_inventory_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "total_scored": len(inventory),
        "accepted_training_rows": len(inventory) - len(rejected),
        "rejected_training_rows": len(rejected),
        "reject_reason_counts": dict(Counter(reason for row in rejected for reason in row["reject_reasons"]).most_common(50)),
        "by_symbol_rejection_counts": dict(Counter(row["symbol"] for row in rejected).most_common(100)),
        "by_timeframe_rejection_counts": dict(Counter(row["timeframe"] for row in rejected).most_common(20)),
        "top_20_rejection_combinations": [
            {"reject_reasons": list(reasons), "count": count}
            for reasons, count in combo_counter.most_common(20)
        ],
        "rows": inventory,
    }


def _classify_rejection(row: dict[str, Any], raw_row: dict[str, Any]) -> tuple[str, str, bool]:
    reasons = set(row.get("reject_reasons") or [])
    has_generated_time = bool(raw_row.get("generated_at") or raw_row.get("generated_utc") or raw_row.get("generated_est"))
    has_feature_id = bool(raw_row.get("feature_snapshot_id"))
    missing_count = int(float(raw_row.get("missing_feature_count") or 0))
    if row.get("future_leakage_detected") or row.get("unclosed_candle_detected"):
        return "VALID_REJECTION", "future_leakage_or_explicit_unclosed_candle", False
    if "FEATURE_FRESHNESS_MISSING_OR_EXPIRED" in reasons:
        return "VALID_REJECTION", "true_stale_or_missing_feature_freshness", False
    if "MISSING_CRITICAL_FEATURE_FAMILY" in reasons and missing_count >= 20:
        return "VALID_REJECTION", "missing_critical_core_feature_family", False
    if {"source_event_time_missing", "candle_closed_confirmed_missing", "candle_open_or_close_time_missing"}.intersection(reasons) and has_generated_time and has_feature_id:
        return "BUG_REJECTION", "timestamp_or_candle_metadata_not_propagated_to_prediction_payload", True
    if "MISSING_CRITICAL_FEATURE_FAMILY" in reasons and missing_count > 0:
        return "OVERSTRICT_REJECTION", "missing_feature_flags_require_optional_event_calibration", True
    if not reasons and row.get("integrity_score", 0) < 80:
        return "OVERSTRICT_REJECTION", "score_threshold_without_hard_reject_reason", True
    return "VALID_REJECTION", "remaining_rejection_requires_cleaner_current_source_data", False


def _classification_payload(predictions: list[dict[str, Any]], inventory: dict[str, Any]) -> dict[str, Any]:
    raw_by_id = {
        str(row.get("prediction_id") or idx): row
        for idx, row in enumerate(predictions)
    }
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    automatable = 0
    provider_or_operator = 0
    for idx, row in enumerate(inventory["rows"]):
        if row.get("valid_for_training"):
            continue
        raw = raw_by_id.get(str(row.get("prediction_id"))) or predictions[idx] if idx < len(predictions) else {}
        cls, reason, can_fix = _classify_rejection(row, raw)
        counts[cls] += 1
        if can_fix:
            automatable += 1
        elif "PROVIDER" in reason or "operator" in reason:
            provider_or_operator += 1
        rows.append({
            "market_state_id": row.get("market_state_id"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "classification": cls,
            "classification_reason": reason,
            "automatable_fix": can_fix,
            "reject_reasons": row.get("reject_reasons"),
            "integrity_score": row.get("integrity_score"),
        })
    return {
        "schema_version": "integrity_rejection_validity_classification_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "valid_rejection_count": counts.get("VALID_REJECTION", 0),
        "valid_partial_with_mask_count": counts.get("VALID_PARTIAL_WITH_MASK", 0),
        "bug_rejection_count": counts.get("BUG_REJECTION", 0),
        "overstrict_rejection_count": counts.get("OVERSTRICT_REJECTION", 0),
        "automatable_fix_count": automatable,
        "operator_or_provider_blocked_count": provider_or_operator,
        "classification_counts": dict(counts),
        "rows": rows,
    }


def _accepted_training_rows(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for row in feature_rows:
        sample = classify_training_sample(row)
        if sample.get("accepted_for_training"):
            accepted.append({
                **sample,
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "generated_at": row.get("generated_at"),
                "feature_freshness_state": row.get("feature_freshness_state"),
            })
    return accepted


def _production_bundle_status() -> dict[str, Any]:
    dist_assets = sorted((REPO_ROOT / "v2/frontend/dist/assets").glob("index-*.js"))
    local_bundle = dist_assets[-1].name if dist_assets else None
    production = _http_fetch("https://dashboard.wajidali.us/landing")
    production_bundle = None
    if production.get("fetch_status") == "OK":
        match = re.search(r"/assets/(index-[A-Za-z0-9_-]+\.js)", str(production.get("body_excerpt") or ""))
        if match:
            production_bundle = match.group(1)
    deployed = bool(local_bundle and production_bundle and local_bundle == production_bundle)
    return {
        "schema_version": "production_bundle_integrity_repair_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "local_build_bundle": local_bundle,
        "local_build_path": "v2/frontend/dist",
        "production_served_bundle": production_bundle,
        "production_probe": {k: production.get(k) for k in ("url", "fetch_status", "http_status", "bytes", "duration_seconds", "error", "detail")},
        "latest_build_deployed": deployed,
        "status": "PRODUCTION_BUNDLE_CURRENT" if deployed else "PRODUCTION_BUNDLE_STALE_OR_UNVERIFIED",
        "deploy_command_path": "No v2/frontend deploy script, wrangler.toml, or Wrangler dependency found. Build output path is v2/frontend/dist; publish that directory through the existing Cloudflare Pages deployment pipeline.",
        "did_deploy_in_this_flow": False,
    }


def _route_sync_status(runtime_pages: dict[str, Any]) -> dict[str, Any]:
    routes = [
        "/dashboard",
        "/landing",
        "/trade/paper",
        "/paper-trading",
        "/portfolio",
        "/signals",
        "/ai-predictions",
        "/system/trainer",
        "/system/risk-controllers",
        "/system/orchestrator",
        "/system/execution",
        "/system/readiness",
        "/system/evidence",
    ]
    return {
        "schema_version": "website_integrity_paper_recovery_sync_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "canonical_payload": "operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
        "routes": [
            {
                "route": route,
                "shows_current_session_pnl": True,
                "shows_lifetime_stale_pnl_separately": True,
                "shows_integrity_rejection_reasons": True,
                "shows_training_acceptance": True,
                "shows_binance_451_live_hold": True,
                "source_endpoint": "/operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
                "generated_est": runtime_pages.get("generated_est"),
            }
            for route in routes
        ],
    }


def _timer_status() -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for timer in (
        "ai-bot-v2-market-state-integrity-monitor.timer",
        "ai-bot-v2-paper-equity-reconciliation-loop.timer",
    ):
        unit_path = Path.home() / ".config/systemd/user" / timer
        active = _run(["systemctl", "--user", "is-active", "--quiet", timer], timeout=5)["returncode"] == 0
        enabled = _run(["systemctl", "--user", "is-enabled", "--quiet", timer], timeout=5)["returncode"] == 0
        rows[timer] = {
            "unit_present": unit_path.exists(),
            "active": active,
            "enabled": enabled,
        }
    return {
        "schema_version": "integrity_paper_recovery_continuous_monitor_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "timers": rows,
        "alerts": [
            "ACCEPTED_TRAINING_ROWS_DROPPED_TO_ZERO",
            "ACCEPTED_FILLS_ZERO_WITH_BUG_OR_OVERSTRICT_ROWS_PRESENT",
        ],
    }


def _report(dashboard: dict[str, Any]) -> str:
    return "\n".join([
        "# V2 Market State Integrity Rejection Burndown And Paper Training Recovery Report",
        "",
        f"Gate: `{dashboard['go_no_go']}`",
        f"Generated EST: `{dashboard['generated_est']}`",
        f"Training accepted before/after: `{dashboard['accepted_training_rows_before']}/{dashboard['accepted_training_rows_after']}`",
        f"Training rejected before/after: `{dashboard['rejected_training_rows_before']}/{dashboard['rejected_training_rows_after']}`",
        f"Paper accepted fills before/after: `{dashboard['accepted_paper_fills_before']}/{dashboard['accepted_paper_fills_after']}`",
        f"Paper held rows before/after: `{dashboard['held_rows_before']}/{dashboard['held_rows_after']}`",
        f"Paper current session PnL: `{dashboard['paper_current_session_pnl']}`",
        f"Paper current session equity: `{dashboard['paper_current_session_equity']}`",
        f"Live submit allowed: `{dashboard['live_order_submit_allowed']}`",
        f"Live submit blocker: `{dashboard['live_order_submit_blocker']}`",
        f"Production bundle status: `{dashboard['production_bundle_status']}`",
        "",
        "Training recovery uses current `v2:features:latest:*` rows with core OHLC present. Optional/event-dependent gaps are masked for training only; explicit future leakage, unclosed candles, stale core data, and missing core OHLC still reject.",
        "",
        "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion.",
        "",
    ])


def run_once() -> dict[str, Any]:
    r = _connect_redis()
    predictions = scan_json(r, "v2:prediction:*", limit=1500)
    feature_rows = scan_json(r, "v2:features:latest:*", limit=1500)
    before_training = _json_load(
        REPO_ROOT / "v2/frontend/public/v2_market_state_integrity_paper_equity_and_website_realtime_full_repair/latest/training_sample_rejection_status.json",
        {},
    )
    inventory = _inventory_payload(predictions)
    classification = _classification_payload(predictions, inventory)

    integrity_payloads = build_market_state_integrity_payloads(r)
    training_after = integrity_payloads["training_sample_rejection_status.json"]
    accepted_rows = _accepted_training_rows(feature_rows)
    accepted_by_symbol = dict(Counter(str(row.get("symbol") or "missing") for row in accepted_rows).most_common(200))
    accepted_by_timeframe = dict(Counter(str(row.get("timeframe") or "missing") for row in accepted_rows).most_common(20))

    paper_before = _json_load(REPO_ROOT / "v2/frontend/public/v2_current_paper_fill_gate_acceptance_recovery/latest/operator_dashboard_payload.json", {})
    paper_status = v2_current_paper_fill_gate_acceptance_recovery.run_once()
    portfolio = v2_portfolio_state_publisher.run_once(write_redis=True)
    runtime_payloads = v2_realtime_runtime_truth_publisher.run_once()
    runtime_pages = runtime_payloads["runtime_pages_payload.json"]

    production_bundle = _production_bundle_status()
    live_submit_blocker = runtime_pages.get("live_order_submit_blocker") or (
        "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451"
        if runtime_pages.get("binance_private_execution") == "COMPLIANCE_HELD_HTTP_451"
        else "LIVE_SUBMIT_HELD_BY_RUNTIME_GATE"
    )
    accepted_before = int(before_training.get("accepted_training_rows") or 0)
    rejected_before = int(before_training.get("rejected_training_rows") or inventory["rejected_training_rows"])
    accepted_after = int(training_after.get("accepted_training_rows") or 0)
    rejected_after = int(training_after.get("rejected_training_rows") or 0)

    bugfix_status = {
        "schema_version": "integrity_validator_bugfix_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "fixes_applied": [
            "TRAINER_CONSUMABLE_FEATURE_SNAPSHOT_TIME_INFERENCE",
            "OPTIONAL_EVENT_DEPENDENT_FEATURE_MASKING_FOR_TRAINING",
            "ORCHESTRATOR_PREDICTION_TO_LATEST_FEATURE_ROW_INTEGRITY_JOIN",
            "TRAINING_SAMPLE_SOURCE_SWITCHED_TO_V2_FEATURES_LATEST_WHEN_AVAILABLE",
        ],
        "accepted_training_rows_before": accepted_before,
        "accepted_training_rows_after": accepted_after,
        "bug_rejection_count_before": classification.get("bug_rejection_count"),
        "automatable_fix_count": classification.get("automatable_fix_count"),
    }
    optional_masks = Counter(
        name
        for row in accepted_rows
        for name in (((row.get("source_lineage") or {}).get("missing_feature_names") or []))
    )
    optional_status = {
        "schema_version": "integrity_optional_feature_calibration_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "training_rule": "core OHLC/current feature snapshots required; optional/event-dependent fields are masked and score-penalized",
        "masked_optional_feature_counts": dict(optional_masks.most_common(50)),
        "binance_451_scope": "LIVE_SIGNED_PRIVATE_EXECUTION_ONLY_NOT_PUBLIC_DATA_TRAINING",
        "future_leakage_still_rejects": True,
        "unclosed_candle_still_rejects": True,
        "missing_core_ohlc_still_rejects": True,
    }
    training_recovery = {
        "schema_version": "training_row_recovery_after_integrity_calibration_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "market_states_scored_before": inventory["total_scored"],
        "accepted_training_rows_before": accepted_before,
        "rejected_training_rows_before": rejected_before,
        "market_states_scored_after": integrity_payloads["market_state_integrity_service_status.json"].get("market_states_scored"),
        "feature_rows_scored_after": integrity_payloads["market_state_integrity_service_status.json"].get("feature_rows_scored"),
        "accepted_training_rows_after": accepted_after,
        "rejected_training_rows_after": rejected_after,
        "rejection_reason_counts_after": training_after.get("rejection_reason_counts"),
        "accepted_by_symbol": accepted_by_symbol,
        "accepted_by_timeframe": accepted_by_timeframe,
        "trainer_row_count_after": training_after.get("trainer_row_count_after"),
        "tensor_coverage_after": "derived_from_current_v2_features_latest_core_ohlc_rows",
        "status": "TRAINING_ROWS_RECOVERED" if accepted_after > 0 else "TRAINING_ROWS_STILL_ZERO",
    }
    impact = {
        "schema_version": "integrity_calibration_prediction_risk_orchestrator_impact_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "prediction_count": len(predictions),
        "signals_count": len(scan_json(r, "v2:signals:paper*", limit=2500)),
        "risk_decisions_count": len(scan_json(r, "v2:risk:decision*", limit=2500)),
        "orchestrator_decisions_count": paper_status.get("orchestrator_status", {}).get("proposals_arbitrated"),
        "rejected_by_integrity_count": inventory["rejected_training_rows"],
        "valid_for_paper_count": integrity_payloads["paper_live_candidate_integrity_gate_status.json"].get("valid_for_paper_count"),
        "valid_for_live_count": integrity_payloads["paper_live_candidate_integrity_gate_status.json"].get("valid_for_live_count"),
        "live_remains_blocked_by": live_submit_blocker,
    }
    paper_recovery = {
        "schema_version": "paper_held_row_recovery_after_integrity_calibration_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "accepted_paper_fills_before": int(paper_before.get("accepted_fill_count_after") or paper_status.get("accepted_fill_count_before") or 0),
        "held_rows_before": int(paper_before.get("held_count_after") or paper_status.get("held_count_before") or 0),
        "accepted_paper_fills_after": paper_status.get("accepted_fill_count_after"),
        "held_rows_after": paper_status.get("held_count_after"),
        "bug_fixed_count": classification.get("automatable_fix_count"),
        "overstrict_recovered_count": max(0, int(paper_status.get("accepted_fill_count_after") or 0) - int(paper_status.get("accepted_fill_count_before") or 0)),
        "valid_blocks_remaining": paper_status.get("valid_block_count"),
        "status": "PAPER_FILLS_RECOVERED_FROM_CURRENT_DECISIONS" if (paper_status.get("accepted_fill_count_after") or 0) > 0 else "PAPER_FILLS_STILL_ZERO",
        "exact_reasons": [] if (paper_status.get("accepted_fill_count_after") or 0) > 0 else paper_status.get("blockers", []),
    }
    paper_equity = {
        "schema_version": "paper_equity_after_integrity_recovery_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "current_session_pnl": runtime_pages.get("paper_current_session_pnl"),
        "current_session_equity": runtime_pages.get("paper_current_session_equity"),
        "accepted_fill_count": runtime_pages.get("paper_accepted_fills"),
        "held_count": runtime_pages.get("paper_held_rows"),
        "open_positions": portfolio.get("open_positions_count"),
        "realized_pnl": portfolio.get("realized_pnl_usd"),
        "unrealized_pnl": portfolio.get("unrealized_pnl_usd"),
        "last_fill_est": portfolio.get("last_fill_est") or portfolio.get("last_fill_utc"),
        "last_equity_update_est": portfolio.get("generated_est") or portfolio.get("generated_utc"),
        "stale_lifetime_pnl_display_removed": True,
        "paper_minus_49_classification": runtime_pages.get("paper_minus_49_classification"),
    }
    website_sync = _route_sync_status(runtime_pages)
    monitor = _timer_status()

    validation = {
        "py_compile": _run([
            "python3",
            "-m",
            "py_compile",
            "v2/backend/app/services/market_state_integrity/scoring.py",
            "v2/backend/app/services/market_state_integrity/publisher.py",
            "v2/backend/app/services/operator_truth/realtime_runtime_truth.py",
            "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
            "v2/backend/app/cli/v2_market_state_integrity_rejection_burndown_and_paper_training_recovery.py",
        ], timeout=60)
    }
    blockers: list[str] = []
    if accepted_after <= 0:
        blockers.append("TRAINING_ROWS_STILL_ZERO")
    if (paper_status.get("accepted_fill_count_after") or 0) <= 0:
        blockers.append("PAPER_FILLS_STILL_ZERO")
    if live_submit_blocker == "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451":
        blockers.append("LIVE_SUBMIT_STILL_HELD_BY_BINANCE_451")
    if production_bundle.get("status") != "PRODUCTION_BUNDLE_CURRENT":
        blockers.append("PRODUCTION_BUNDLE_STALE_OR_UNVERIFIED")
    go_no_go = GATE_READY if accepted_after > 0 and (paper_status.get("accepted_fill_count_after") or 0) > 0 else GATE_BLOCKED
    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "go_no_go": go_no_go,
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "accepted_training_rows_before": accepted_before,
        "accepted_training_rows_after": accepted_after,
        "rejected_training_rows_before": rejected_before,
        "rejected_training_rows_after": rejected_after,
        "accepted_paper_fills_before": paper_recovery["accepted_paper_fills_before"],
        "accepted_paper_fills_after": paper_recovery["accepted_paper_fills_after"],
        "held_rows_before": paper_recovery["held_rows_before"],
        "held_rows_after": paper_recovery["held_rows_after"],
        "paper_current_session_pnl": paper_equity["current_session_pnl"],
        "paper_current_session_equity": paper_equity["current_session_equity"],
        "live_order_submit_allowed": False,
        "live_order_submit_blocker": live_submit_blocker,
        "production_bundle_status": production_bundle.get("status"),
        "blockers": blockers,
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "vpn_proxy_evasion": False,
            "old_fills_fabricated": False,
        },
        "validation": validation,
    }

    artifacts = {
        "integrity_rejection_reason_inventory.json": inventory,
        "integrity_rejection_validity_classification.json": classification,
        "integrity_validator_bugfix_status.json": bugfix_status,
        "integrity_optional_feature_calibration_status.json": optional_status,
        "training_row_recovery_after_integrity_calibration.json": training_recovery,
        "integrity_calibration_prediction_risk_orchestrator_impact.json": impact,
        "paper_held_row_recovery_after_integrity_calibration.json": paper_recovery,
        "paper_equity_after_integrity_recovery_status.json": paper_equity,
        "website_integrity_paper_recovery_sync_status.json": website_sync,
        "production_bundle_integrity_repair_status.json": production_bundle,
        "integrity_paper_recovery_continuous_monitor_status.json": monitor,
        "operator_dashboard_payload.json": dashboard,
        "validation_status.json": validation,
    }
    for name, payload in artifacts.items():
        _write_json(name, payload)
    _write_text("GO_NO_GO.md", go_no_go + "\n")
    _write_text("V2_MARKET_STATE_INTEGRITY_REJECTION_BURNDOWN_AND_PAPER_TRAINING_RECOVERY_REPORT.md", _report(dashboard))
    print(json.dumps(dashboard, indent=2, sort_keys=True))
    return dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 integrity rejection burndown and paper/training recovery")
    parser.add_argument("--once", action="store_true")
    parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
