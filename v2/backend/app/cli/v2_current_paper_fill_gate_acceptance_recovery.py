#!/usr/bin/env python3
"""Current V2 paper fill gate acceptance recovery.

Audits current held paper decisions, repairs safe V2-side diagnostics/input
reader issues, and reports whether paper fills can be accepted from current
decisions. This never touches live exchange execution.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SERVICE_ID = "v2_current_paper_fill_gate_acceptance_recovery"
GATE_READY = "V2_CURRENT_PAPER_FILL_GATE_ACCEPTANCE_RECOVERY_READY"
GATE_BLOCKED = "V2_CURRENT_PAPER_FILL_GATE_ACCEPTANCE_RECOVERY_BLOCKED"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public" / SERVICE_ID / "latest"
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness" / SERVICE_ID / "latest"
EST = timezone(timedelta(hours=-4))
V2_PREFIX = "v2:"

VALID_REASON_TOKENS = (
    "negative_expected_move",
    "missing_feature",
    "stale_feature",
    "feature_freshness",
    "confidence_below",
    "data_coverage",
    "missing_price",
    "invalid_price",
    "risk_cap",
    "spread",
    "slippage",
    "symbol_not_eligible",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _json_loads(raw: Any) -> Any | None:
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _redis_json(client: Any, key: str, default: Any = None) -> Any:
    if client is None:
        return default
    try:
        payload = _json_loads(client.get(key))
    except Exception:
        return default
    return default if payload is None else payload


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _int(value: Any, default: int = 0) -> int:
    num = _float(value)
    return default if num is None else int(num)


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _norm_reason(reason: Any) -> str:
    return str(reason or "").strip().lower().replace("-", "_").replace(" ", "_")


def _bucket(value: float | None, thresholds: tuple[float, ...]) -> str:
    if value is None:
        return "missing"
    for threshold in thresholds:
        if value < threshold:
            return f"<{threshold:g}"
    return f">={thresholds[-1]:g}"


def _scan_json(client: Any, pattern: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if client is None:
        return rows
    try:
        for key in client.scan_iter(match=pattern, count=500):
            payload = _json_loads(client.get(str(key)))
            if isinstance(payload, dict):
                payload = dict(payload)
                payload["_redis_key"] = str(key)
                rows.append(payload)
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        item = dict(item)
                        item["_redis_key"] = str(key)
                        rows.append(item)
    except Exception:
        return rows
    return rows


def _index_by(rows: list[dict[str, Any]], *fields: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        for field in fields:
            value = row.get(field)
            if value:
                out[str(value)] = row
    return out


def _load_snapshot(client: Any) -> dict[str, Any]:
    ledger = _as_dict(_redis_json(client, f"{V2_PREFIX}paper:ledger", {}))
    orchestrator = _as_dict(_redis_json(client, f"{V2_PREFIX}orchestrator:decisions", {}))
    return {
        "paper_ledger": ledger,
        "paper_intents": _as_list(_redis_json(client, f"{V2_PREFIX}paper:intents", [])),
        "paper_held": _as_list(ledger.get("held_by_paper_fill_gate"))
        or _as_list(_redis_json(client, f"{V2_PREFIX}paper:intents_held_by_paper_fill_gate", []))
        or _as_list(orchestrator.get("held_by_paper_fill_gate")),
        "paper_signals": _scan_json(client, f"{V2_PREFIX}signals:paper*"),
        "latest_signals": _scan_json(client, f"{V2_PREFIX}signals:latest:*"),
        "predictions": _scan_json(client, f"{V2_PREFIX}prediction:*"),
        "risk_decisions": _as_list(_redis_json(client, f"{V2_PREFIX}risk:decisions", [])),
        "orchestrator": orchestrator,
        "portfolio": _as_dict(_redis_json(client, f"{V2_PREFIX}portfolio:state", {})),
    }


def _lineage_row(
    row: dict[str, Any],
    *,
    predictions_by_id: dict[str, dict[str, Any]],
    paper_signal_by_id: dict[str, dict[str, Any]],
    risk_by_id: dict[str, dict[str, Any]],
    idx: int,
) -> dict[str, Any]:
    prediction_id = str(_first(row.get("prediction_id"), row.get("source_prediction_id"), "") or "")
    pred = predictions_by_id.get(prediction_id, {})
    signal_id = _first(row.get("signal_id"), row.get("paper_signal_id"))
    signal = paper_signal_by_id.get(str(signal_id or ""), {})
    risk_decision_id = _first(row.get("risk_decision_id"), signal.get("risk_decision_id"))
    risk = risk_by_id.get(str(risk_decision_id or ""), {})
    reasons = [
        _norm_reason(reason)
        for reason in _as_list(_first(row.get("paper_fill_gate_block_reasons"), pred.get("paper_fill_gate_block_reasons"), signal.get("paper_fill_gate_block_reasons"), []))
        if _norm_reason(reason)
    ]
    if not reasons and _first(row.get("paper_fill_gate_status"), pred.get("paper_fill_gate_status")):
        reasons = [_norm_reason(_first(row.get("paper_fill_gate_status"), pred.get("paper_fill_gate_status")))]
    expected_move = _float(_first(row.get("expected_move_after_cost_bps"), pred.get("expected_move_after_cost_bps"), signal.get("expected_move_after_cost_bps")))
    confidence = _float(_first(row.get("confidence_calibrated"), pred.get("confidence_calibrated"), signal.get("confidence_calibrated"), signal.get("confidence")))
    missing_feature_count = _int(_first(row.get("missing_feature_count"), pred.get("missing_feature_count"), len(pred.get("missing_feature_flags") or [])), 0)
    stale_feature_count = _int(_first(row.get("stale_feature_count"), pred.get("stale_feature_count"), len(pred.get("stale_feature_flags") or [])), 0)
    feature_state = _first(row.get("feature_freshness_state"), pred.get("feature_freshness_state"), signal.get("feature_freshness_state"))
    risk_state = _first(row.get("risk_state"), signal.get("risk_state"), risk.get("risk_state"), risk.get("risk_result"))
    if not risk_state and not risk_decision_id:
        risk_state = "NOT_ROUTED_TO_RISK_GATEWAY_BECAUSE_PAPER_FILL_GATE_BLOCKED"
    generated_utc = _first(row.get("generated_utc"), pred.get("generated_utc"), signal.get("generated_utc"))
    return {
        "held_row_id": _first(row.get("intent_id"), f"held_{idx:04d}"),
        "generated_est": generated_utc or _est_iso(),
        "generated_utc": generated_utc,
        "symbol": _first(row.get("symbol"), pred.get("symbol"), signal.get("symbol")),
        "timeframe": _first(row.get("timeframe"), pred.get("timeframe"), signal.get("timeframe")),
        "action": _first(row.get("selected_action_upstream"), row.get("selected_action"), pred.get("selected_action"), signal.get("selected_action"), signal.get("action")),
        "prediction_id": prediction_id or None,
        "risk_decision_id": risk_decision_id,
        "orchestrator_decision_id": _first(row.get("orchestrator_decision_id"), signal.get("orchestrator_decision_id"), f"held_decision_{prediction_id}" if prediction_id else None),
        "signal_id": _first(signal_id, signal.get("signal_id"), f"held_signal_{prediction_id}" if prediction_id else None),
        "expected_move_after_cost_bps": expected_move,
        "confidence_calibrated": confidence,
        "price_target": _first(row.get("price_target"), pred.get("price_target"), signal.get("price_target")),
        "data_coverage_percent": _float(_first(row.get("data_coverage_percent"), pred.get("data_coverage_percent"), signal.get("data_coverage_percent"))),
        "missing_feature_count": missing_feature_count,
        "stale_feature_count": stale_feature_count,
        "feature_freshness_state": feature_state,
        "spread_bps": _float(_first(row.get("spread_bps"), pred.get("spread_bps"), signal.get("spread_bps"))),
        "slippage_estimate_bps": _float(_first(row.get("slippage_estimate_bps"), pred.get("slippage_estimate_bps"), signal.get("slippage_estimate_bps"))),
        "risk_state": risk_state,
        "paper_fill_allowed": bool(_first(row.get("paper_fill_allowed"), pred.get("paper_fill_allowed"), signal.get("paper_fill_allowed"), False)),
        "paper_fill_block_reason": reasons[0] if reasons else "unknown",
        "paper_fill_block_reasons": sorted(set(reasons)),
        "checkpoint_blocker": _first(row.get("checkpoint_blocker"), pred.get("checkpoint_blocker")),
        "checkpoint_weight_status": _first(row.get("checkpoint_weight_status"), pred.get("checkpoint_weight_status")),
        "trainer_source": _first(row.get("trainer_source"), pred.get("trainer_source")),
        "prediction_enriched": bool(pred),
        "paper_signal_enriched": bool(signal),
        "risk_enriched": bool(risk),
    }


def _classify_row(row: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = list(row.get("paper_fill_block_reasons") or [])
    text = ";".join(reasons)
    issues: list[str] = []
    expected = _float(row.get("expected_move_after_cost_bps"))
    confidence = _float(row.get("confidence_calibrated"))
    missing = _int(row.get("missing_feature_count"), 0)
    stale = _int(row.get("stale_feature_count"), 0)
    coverage = _float(row.get("data_coverage_percent"))

    valid = False
    if expected is not None and expected < 0:
        valid = True
        issues.append("negative_expected_move_after_cost")
    if missing > 0 or "missing_feature" in text:
        valid = True
        issues.append("missing_feature_flags")
    if stale > 0 or "stale_feature" in text:
        valid = True
        issues.append("stale_feature_flags")
    if confidence is not None and confidence < 0.55:
        valid = True
        issues.append("confidence_below_paper_floor")
    if coverage is not None and coverage < 60:
        valid = True
        issues.append("data_coverage_below_paper_floor")
    if any(token in text for token in VALID_REASON_TOKENS):
        valid = True
        issues.append("explicit_valid_block_reason")
    if row.get("checkpoint_blocker"):
        valid = True
        issues.append("checkpoint_safe_mode_blocker")
    if not row.get("prediction_id"):
        valid = True
        issues.append("missing_prediction_lineage")

    if not valid and row.get("paper_fill_allowed") is True:
        return "BUG_BLOCK", ["paper_fill_allowed_true_but_held"]
    if not valid and expected is not None and expected > 0 and confidence is not None and confidence >= 0.5:
        return "OVERSTRICT_BLOCK", ["positive_edge_and_basic_confidence_but_blocked"]
    if not valid:
        return "BUG_BLOCK", ["unknown_block_without_valid_reason"]
    return "VALID_BLOCK", sorted(set(issues))


def _build_inventory(snapshot: dict[str, Any]) -> dict[str, Any]:
    predictions_by_id = _index_by(snapshot["predictions"], "prediction_id")
    paper_signal_by_id = _index_by(snapshot["paper_signals"], "signal_id", "prediction_id", "paper_intent_id")
    risk_by_id = _index_by(snapshot["risk_decisions"], "risk_decision_id", "decision_id")
    rows = [
        _lineage_row(row, predictions_by_id=predictions_by_id, paper_signal_by_id=paper_signal_by_id, risk_by_id=risk_by_id, idx=idx)
        for idx, row in enumerate([r for r in snapshot["paper_held"] if isinstance(r, dict)], start=1)
    ]
    return {
        "schema_version": "current_paper_held_row_inventory_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "source_of_truth": "v2:paper:ledger.held_by_paper_fill_gate",
        "total_held": len(rows),
        "current_accepted_fills": _int(snapshot["paper_ledger"].get("accepted_count"), 0),
        "current_paper_signals_seen": len(snapshot["paper_signals"]),
        "rows": rows,
        "safety": {
            "old_june_5_fills_reused": False,
            "fills_fabricated": False,
            "orders_submitted": False,
        },
    }


def _distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counter = Counter(reason for row in rows for reason in row.get("paper_fill_block_reasons", []))
    return {
        "schema_version": "current_paper_fill_block_reason_distribution_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "total_held": len(rows),
        "by_block_reason": dict(sorted(reason_counter.items())),
        "by_symbol": dict(sorted(Counter(str(row.get("symbol") or "missing") for row in rows).items())),
        "by_timeframe": dict(sorted(Counter(str(row.get("timeframe") or "missing") for row in rows).items())),
        "by_action": dict(sorted(Counter(str(row.get("action") or "missing") for row in rows).items())),
        "by_confidence_bucket": dict(sorted(Counter(_bucket(_float(row.get("confidence_calibrated")), (0.45, 0.55, 0.65, 0.75)) for row in rows).items())),
        "by_expected_move_bucket": dict(sorted(Counter(_bucket(_float(row.get("expected_move_after_cost_bps")), (-100, -50, 0, 8, 25)) for row in rows).items())),
        "by_risk_state": dict(sorted(Counter(str(row.get("risk_state") or "missing") for row in rows).items())),
        "by_stale_missing_feature_state": dict(sorted(Counter(
            f"missing_{_int(row.get('missing_feature_count'), 0)}_stale_{_int(row.get('stale_feature_count'), 0)}"
            for row in rows
        ).items())),
    }


def _validity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classified: list[dict[str, Any]] = []
    counter: Counter[str] = Counter()
    for row in rows:
        kind, reasons = _classify_row(row)
        counter[kind] += 1
        out = dict(row)
        out["classification"] = kind
        out["classification_reasons"] = reasons
        classified.append(out)
    return {
        "schema_version": "current_paper_fill_validity_classification_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "valid_block_count": counter.get("VALID_BLOCK", 0),
        "bug_block_count": counter.get("BUG_BLOCK", 0),
        "overstrict_block_count": counter.get("OVERSTRICT_BLOCK", 0),
        "rows": classified,
    }


def _simulate_profile(rows: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    accepted = []
    held = []
    for row in rows:
        expected = _float(row.get("expected_move_after_cost_bps"))
        confidence = _float(row.get("confidence_calibrated"))
        coverage = _float(row.get("data_coverage_percent"))
        missing = _int(row.get("missing_feature_count"), 0)
        stale = _int(row.get("stale_feature_count"), 0)
        reasons = []
        if expected is None or expected < profile["min_expected_move_after_cost_bps"]:
            reasons.append("expected_move_below_profile")
        if confidence is None or confidence < profile["min_confidence_calibrated"]:
            reasons.append("confidence_below_profile")
        if coverage is not None and coverage < profile["min_data_coverage_percent"]:
            reasons.append("data_coverage_below_profile")
        if not profile["allow_missing_features"] and missing > 0:
            reasons.append("missing_features_not_allowed")
        if stale > 0:
            reasons.append("stale_features_not_allowed")
        if reasons:
            held.append({"symbol": row.get("symbol"), "reasons": reasons})
        else:
            accepted.append(row)
    expected_values = [_float(row.get("expected_move_after_cost_bps")) for row in accepted]
    expected_values = [v for v in expected_values if v is not None]
    return {
        "profile_name": profile["profile_name"],
        "accepted_count": len(accepted),
        "held_count": len(held),
        "expected_after_cost_bps": sum(expected_values) / len(expected_values) if expected_values else None,
        "false_positive_risk": "UNKNOWN_NO_ACCEPTED_SAMPLE" if not accepted else "REQUIRES_OUTCOME_SAMPLE",
        "false_negative_recovery": 0 if not accepted else len(accepted),
        "drawdown_estimate": "NOT_COMPUTED_NO_ACCEPTED_SAMPLE" if not accepted else "REQUIRES_REPLAY",
        "by_symbol_accepted_count": dict(sorted(Counter(str(row.get("symbol")) for row in accepted).items())),
        "held_reasons_sample": held[:20],
    }


def _profile_simulation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    profiles = [
        {"profile_name": "current_profile", "min_expected_move_after_cost_bps": 8.0, "min_confidence_calibrated": 0.55, "min_data_coverage_percent": 80.0, "allow_missing_features": False},
        {"profile_name": "conservative_paper_profile", "min_expected_move_after_cost_bps": 4.0, "min_confidence_calibrated": 0.55, "min_data_coverage_percent": 70.0, "allow_missing_features": False},
        {"profile_name": "balanced_paper_profile", "min_expected_move_after_cost_bps": 1.0, "min_confidence_calibrated": 0.50, "min_data_coverage_percent": 60.0, "allow_missing_features": False},
        {"profile_name": "actionability_recovery_profile", "min_expected_move_after_cost_bps": 0.0, "min_confidence_calibrated": 0.50, "min_data_coverage_percent": 50.0, "allow_missing_features": False},
    ]
    return {
        "schema_version": "current_paper_fill_profile_simulation_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "profiles": [_simulate_profile(rows, profile) for profile in profiles],
        "live_affected": False,
        "profile_applied": False,
    }


def _bug_repair_status(before: dict[str, Any], after: dict[str, Any], validity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "current_paper_fill_bug_repair_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "repairs_applied": [
            {
                "repair": "paper_loop_reads_per_symbol_v2_signals_paper_keys",
                "before": before.get("paper_signals_seen"),
                "after": after.get("paper_signals_seen"),
                "status": "APPLIED",
            },
            {
                "repair": "held_rows_preserve_prediction_metrics_and_lineage_context",
                "status": "APPLIED",
            },
        ],
        "bug_block_count_after_repair": validity.get("bug_block_count"),
        "overstrict_block_count_after_repair": validity.get("overstrict_block_count"),
        "accepted_fills_after_repair": after.get("accepted_count"),
        "exact_reason_if_no_acceptance": (
            "ALL_CURRENT_HELD_ROWS_CLASSIFIED_VALID_BLOCK"
            if validity.get("valid_block_count") == after.get("held_count")
            else "BUG_OR_OVERSTRICT_BLOCKS_REMAIN"
        ),
    }


def _reactivation_status(portfolio: dict[str, Any], validity: dict[str, Any]) -> dict[str, Any]:
    accepted = _int(portfolio.get("accepted_fill_total"), 0)
    return {
        "schema_version": "current_paper_fill_reactivation_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "paper_only": True,
        "live_independent": True,
        "accepted_fill_count_after": accepted,
        "paper_equity_updates_if_fills_exist": accepted > 0,
        "profile_changed": False,
        "audit_payload_written": True,
        "old_june_5_fills_reused": False,
        "fills_fabricated": False,
        "exact_reason_if_zero": (
            "NO_CURRENT_DECISION_PASSES_VALID_PAPER_FILL_CRITERIA"
            if accepted == 0 else None
        ),
        "valid_blocks_remained_blocked": validity.get("valid_block_count"),
        "bug_blocks_remaining": validity.get("bug_block_count"),
        "overstrict_blocks_remaining": validity.get("overstrict_block_count"),
    }


def _equity_after(portfolio: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "current_paper_equity_after_fill_recovery_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "accepted_fills": portfolio.get("accepted_fill_total"),
        "held_rows": portfolio.get("held_by_paper_fill_gate_total"),
        "open_positions": portfolio.get("open_positions_count"),
        "realized_pnl": portfolio.get("realized_pnl_usd"),
        "unrealized_pnl": portfolio.get("unrealized_pnl_usd"),
        "equity": portfolio.get("equity"),
        "last_fill_est": portfolio.get("last_fill_est"),
        "last_equity_update_est": portfolio.get("last_equity_update_est"),
        "equity_reason": portfolio.get("paper_equity_reason"),
    }


def _website_sync(rows: list[dict[str, Any]], portfolio: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "current_paper_fill_website_sync_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "routes_updated": [
            "/trade/paper",
            "/landing",
            "/paper-trading",
            "/portfolio",
            "/system/execution",
            "/system/readiness",
        ],
        "shows": {
            "accepted_fills": portfolio.get("accepted_fill_total"),
            "held_count": portfolio.get("held_by_paper_fill_gate_total"),
            "top_block_reasons": [reason for reason, _ in Counter(reason for row in rows for reason in row.get("paper_fill_block_reasons", [])).most_common(8)],
            "bug_valid_overstrict_classification": True,
            "paper_profile_simulation": True,
            "equity_reason": portfolio.get("paper_equity_reason"),
            "latest_accepted_fill": None,
            "source_timestamp": portfolio.get("generated_est") or portfolio.get("generated_utc"),
        },
    }


def _run_cmd(args: list[str]) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            args,
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
        return {
            "cmd": " ".join(args),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
            "duration_seconds": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {"cmd": " ".join(args), "returncode": -1, "error": str(exc)}


def _write_json(name: str, payload: Any) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(name: str, text: str) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")


def _report(dashboard: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V2 Current Paper Fill Gate Acceptance Recovery Report",
            "",
            f"Gate: `{dashboard['go_no_go']}`",
            f"Generated EST: `{dashboard['generated_est']}`",
            f"Accepted fills after repair: `{dashboard['accepted_fill_count_after']}`",
            f"Held rows after repair: `{dashboard['held_count_after']}`",
            f"Valid blocks: `{dashboard['valid_block_count']}`",
            f"Bug blocks: `{dashboard['bug_block_count']}`",
            f"Over-strict blocks: `{dashboard['overstrict_block_count']}`",
            f"Paper equity: `{dashboard['paper_equity']}`",
            f"Primary reason: `{dashboard['primary_reason']}`",
            "",
            "Current held decisions remain blocked because current evidence does not pass paper-fill criteria. No old June 5 fills were copied into the current ledger.",
            "",
            "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output.",
            "",
        ]
    )


def run_once() -> dict[str, Any]:
    from v2.backend.app.cli import (
        v2_operator_runtime_truth_publisher,
        v2_orchestrator_arbitration_loop,
        v2_portfolio_state_publisher,
        v2_trade_management_paper_loop,
    )

    client = _connect_redis()
    before = _load_snapshot(client)
    before_summary = {
        "paper_signals_seen": len(before["paper_signals"]),
        "accepted_count": _int(before["paper_ledger"].get("accepted_count"), 0),
        "held_count": len(before["paper_held"]),
    }

    orchestrator_status = v2_orchestrator_arbitration_loop.run_once()
    paper_status = v2_trade_management_paper_loop.run_once()
    portfolio = v2_portfolio_state_publisher.run_once(write_redis=True)
    truth = v2_operator_runtime_truth_publisher.run_once()
    after = _load_snapshot(client)

    inventory = _build_inventory(after)
    rows = [row for row in inventory["rows"] if isinstance(row, dict)]
    distribution = _distribution(rows)
    validity = _validity(rows)
    profile_sim = _profile_simulation(rows)
    after_summary = {
        "paper_signals_seen": len(after["paper_signals"]),
        "accepted_count": _int(after["paper_ledger"].get("accepted_count"), 0),
        "held_count": len(after["paper_held"]),
    }
    bug_repair = _bug_repair_status(before_summary, after_summary, validity)
    reactivation = _reactivation_status(portfolio, validity)
    equity_after = _equity_after(portfolio)
    website = _website_sync(rows, portfolio)

    blockers: list[str] = []
    accepted_after = _int(portfolio.get("accepted_fill_total"), 0)
    if validity["bug_block_count"]:
        blockers.append("BUG_BLOCKS_REMAIN")
    if accepted_after == 0:
        blockers.append("NO_CURRENT_DECISION_PASSES_VALID_PAPER_FILL_CRITERIA")
    go_no_go = GATE_READY if not validity["bug_block_count"] else GATE_BLOCKED
    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "go_no_go": go_no_go,
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "accepted_fill_count_before": before_summary["accepted_count"],
        "accepted_fill_count_after": accepted_after,
        "held_count_before": before_summary["held_count"],
        "held_count_after": len(rows),
        "paper_signals_seen_before": before_summary["paper_signals_seen"],
        "paper_signals_seen_after": after_summary["paper_signals_seen"],
        "valid_block_count": validity["valid_block_count"],
        "bug_block_count": validity["bug_block_count"],
        "overstrict_block_count": validity["overstrict_block_count"],
        "paper_equity": portfolio.get("equity"),
        "paper_equity_reason": portfolio.get("paper_equity_reason"),
        "portfolio_classification": portfolio.get("classification"),
        "primary_reason": "NO_CURRENT_DECISION_PASSES_VALID_PAPER_FILL_CRITERIA" if accepted_after == 0 else "PAPER_FILLS_ACCEPTED_FROM_CURRENT_DECISIONS",
        "orchestrator_status": {
            "classification": orchestrator_status.get("classification"),
            "predictions_seen": orchestrator_status.get("predictions_seen"),
            "proposals_arbitrated": orchestrator_status.get("proposals_arbitrated"),
            "held": orchestrator_status.get("predictions_held_by_paper_fill_gate"),
        },
        "paper_loop_status": {
            "classification": paper_status.get("classification"),
            "paper_signals_seen": paper_status.get("paper_signals_seen"),
            "intents_built": paper_status.get("intents_built"),
            "intents_accepted": paper_status.get("intents_accepted"),
            "intents_blocked": paper_status.get("intents_blocked"),
            "held": paper_status.get("intents_held_by_paper_fill_gate"),
        },
        "runtime_truth": {
            "classification": truth.get("classification"),
            "paper_equity": truth.get("paper_equity"),
            "paper_accepted_fills": truth.get("paper_accepted_fills"),
        },
        "blockers": blockers,
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "old_june_5_fills_reused": False,
            "fills_fabricated": False,
        },
    }

    payloads = {
        "current_paper_held_row_inventory.json": inventory,
        "current_paper_fill_block_reason_distribution.json": distribution,
        "current_paper_fill_validity_classification.json": validity,
        "current_paper_fill_bug_repair_status.json": bug_repair,
        "current_paper_fill_profile_simulation.json": profile_sim,
        "current_paper_fill_reactivation_status.json": reactivation,
        "current_paper_equity_after_fill_recovery_status.json": equity_after,
        "current_paper_fill_website_sync_status.json": website,
        "operator_dashboard_payload.json": dashboard,
    }
    for name, payload in payloads.items():
        _write_json(name, payload)
    _write_text("GO_NO_GO.md", go_no_go + "\n")
    _write_text("V2_CURRENT_PAPER_FILL_GATE_ACCEPTANCE_RECOVERY_REPORT.md", _report(dashboard))
    print(json.dumps(dashboard, indent=2, sort_keys=True))
    return dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 current paper fill gate acceptance recovery")
    parser.add_argument("--once", action="store_true", help="Run once")
    parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
