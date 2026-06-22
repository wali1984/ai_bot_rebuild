from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .masa_ppo_disagreement import classify_masa_ppo_disagreement
from .replay_snapshot import build_replay_snapshot
from .sample_rejection import classify_training_sample
from .scoring import score_market_state

EST = timezone(timedelta(hours=-4))


def est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_loads(raw: Any) -> Any | None:
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def scan_json(redis_client: Any, pattern: str, limit: int = 1000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if redis_client is None:
        return rows
    try:
        for key in redis_client.scan_iter(match=pattern, count=500):
            payload = json_loads(redis_client.get(str(key)))
            if isinstance(payload, dict):
                row = dict(payload)
                row["_redis_key"] = str(key)
                rows.append(row)
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        row = dict(item)
                        row["_redis_key"] = str(key)
                        rows.append(row)
            if len(rows) >= limit:
                break
    except Exception:
        return rows
    return rows


def build_market_state_integrity_payloads(redis_client: Any = None) -> dict[str, dict[str, Any]]:
    predictions = scan_json(redis_client, "v2:prediction:*", limit=1500)
    feature_rows = scan_json(redis_client, "v2:features:latest:*", limit=1500)
    candidate_rows = predictions or feature_rows
    training_rows = feature_rows or predictions
    scored = [score_market_state(row).to_dict() for row in candidate_rows]
    feature_training_scores = [score_market_state(row).to_dict() for row in feature_rows]
    training = [classify_training_sample(row) for row in training_rows]
    disagreements = [classify_masa_ppo_disagreement(row) for row in predictions[:500]]
    rejected_training = [row for row in training if not row["accepted_for_training"]]
    accepted_training = [row for row in training if row["accepted_for_training"]]
    reject_counter = Counter(reason for row in rejected_training for reason in row.get("reject_reasons", []))
    by_symbol = Counter(str(row.get("symbol") or "missing") for row in candidate_rows)
    by_tf = Counter(str(row.get("timeframe") or row.get("tf") or "missing") for row in candidate_rows)
    score_values = [row["market_state_integrity_score"] for row in scored]
    avg_score = sum(score_values) / len(score_values) if score_values else None
    valid_prediction = sum(1 for row in scored if row["valid_for_prediction"])
    valid_risk = sum(1 for row in scored if row["valid_for_risk"])
    valid_paper = sum(1 for row in scored if row["valid_for_paper"])
    valid_live = sum(1 for row in scored if row["valid_for_live"])
    feature_valid_training = sum(1 for row in feature_training_scores if row["valid_for_training"])
    generated_est = est_now()
    generated_utc = utc_now()

    service_status = {
        "schema_version": "market_state_integrity_service_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "prediction_rows_scored": len(predictions),
        "feature_rows_scored": len(feature_rows),
        "market_states_scored": len(scored),
        "training_rows_scored": len(training_rows),
        "average_market_state_integrity_score": avg_score,
        "feature_training_rows_valid": feature_valid_training,
        "valid_for_prediction_count": valid_prediction,
        "valid_for_risk_count": valid_risk,
        "valid_for_paper_count": valid_paper,
        "valid_for_live_count": valid_live,
        "thresholds": {
            "training_min_score": 80,
            "prediction_min_score": 70,
            "risk_min_score": 80,
            "paper_min_score": 70,
            "live_min_score": 90,
        },
        "top_reject_reasons": dict(reject_counter.most_common(20)),
        "sample_states": scored[:25],
        "no_missing_field_defaults_clean": True,
    }
    alignment_rows = [
        {
            "market_state_id": row["market_state_id"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "status": "TF_ALIGNED" if "feature_timestamp_after_decision_cutoff" not in row["reject_reasons"] else "FUTURE_LEAKAGE",
            "reject_reasons": [
                reason
                for reason in row["reject_reasons"]
                if reason in {"decision_cutoff_time_missing", "source_event_time_missing", "feature_timestamp_after_decision_cutoff", "source_available_after_decision_cutoff"}
            ],
        }
        for row in scored[:100]
    ]
    candle_rows = [
        {
            "market_state_id": row["market_state_id"],
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "status": "UNCLOSED_CANDLE" if "candle_not_closed_confirmed" in row["reject_reasons"] else "CANDLE_CLOSED_OR_UNKNOWN",
            "reject_reasons": [
                reason
                for reason in row["reject_reasons"]
                if reason.startswith("candle_")
            ],
        }
        for row in scored[:100]
    ]
    source_disagreement = {
        "schema_version": "source_disagreement_detection_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "symbols_checked": len(by_symbol),
        "source_count": "derived_from_available_v2_market_state_rows",
        "primary_source": "v2:market:prices",
        "secondary_sources": ["v2:features:latest", "v2:prediction:*"],
        "rows": [
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "price_disagreement_bps": row.get("price_disagreement_bps"),
                "disagreement_status": "MAJOR_SOURCE_DISAGREEMENT" if "MAJOR_SOURCE_DISAGREEMENT" in score_market_state(row).reject_reasons else "NO_MAJOR_DISAGREEMENT_IN_AVAILABLE_FIELDS",
            }
            for row in candidate_rows[:100]
        ],
    }
    latency_freshness = {
        "schema_version": "runtime_latency_freshness_gate_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "rows_checked": len(candidate_rows),
        "freshness_status_counts": dict(Counter(
            "CURRENT" if score_market_state(row).data_freshness_score >= 100 else "STALE_OR_MISSING"
            for row in candidate_rows
        )),
        "by_symbol": dict(by_symbol.most_common(50)),
    }
    training_status = {
        "schema_version": "training_sample_rejection_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "accepted_training_rows": len(accepted_training),
        "rejected_training_rows": len(rejected_training),
        "rejection_reason_counts": dict(reject_counter.most_common(30)),
        "by_symbol_rejections": dict(Counter(str(row.get("symbol") or "missing") for row in training_rows if classify_training_sample(row)["accepted_for_training"] is False).most_common(50)),
        "by_timeframe_rejections": dict(Counter(str(row.get("timeframe") or row.get("tf") or "missing") for row in training_rows if classify_training_sample(row)["accepted_for_training"] is False).most_common(20)),
        "trainer_row_count_before": len(training_rows),
        "trainer_row_count_after": len(accepted_training),
        "sample_rejections": rejected_training[:50],
    }
    prediction_gate = {
        "schema_version": "prediction_integrity_gate_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "prediction_rows": len(predictions),
        "valid_for_prediction": valid_prediction,
        "invalid_for_prediction": max(0, len(scored) - valid_prediction),
        "required_fields": ["market_state_id", "market_state_integrity_score", "valid_for_prediction", "decision_cutoff_time_est", "feature_snapshot_id", "source_lineage"],
        "invalid_action_contract": {
            "selected_action": "hold",
            "paper_fill_allowed": False,
            "prediction_status": "MARKET_STATE_REJECTED",
        },
        "sample_rows": scored[:25],
    }
    risk_orch = {
        "schema_version": "risk_orchestrator_integrity_enforcement_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "valid_for_risk_count": valid_risk,
        "valid_for_orchestrator_count": valid_risk,
        "reject_if_missing_market_state_id": True,
        "reject_if_market_state_mismatch": True,
        "reject_if_stale_prediction": True,
        "reject_if_missing_lineage": True,
    }
    paper_live = {
        "schema_version": "paper_live_candidate_integrity_gate_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "valid_for_paper_count": valid_paper,
        "valid_for_live_count": valid_live,
        "paper_min_score": 70,
        "live_min_score": 90,
        "live_order_submit_allowed": False,
        "live_order_submit_blocker": "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451",
        "paper_requires_lineage": ["prediction_id", "risk_decision_id", "orchestrator_decision_id", "signal_id"],
        "live_requires_signed_account_reads_ok": True,
    }
    masa_status = {
        "schema_version": "masa_ppo_role_isolation_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "roles": {
            "MASA": "forecast_direction_expected_move_confidence_regime",
            "PPO": "action_policy_position_intent_hold_close_flip",
            "Risk": "final_gate",
            "Orchestrator": "arbitration",
            "Trader": "execution",
        },
        "disagreement_rows": len(disagreements),
        "disagreement_class_counts": dict(Counter(reason for row in disagreements for reason in row.get("disagreement_classes", []))),
    }
    replay_rows = [
        build_replay_snapshot(
            decision_id=str(row.get("prediction_id") or row.get("feature_snapshot_id") or idx),
            prediction=row,
            integrity=scored[idx] if idx < len(scored) else None,
        )
        for idx, row in enumerate(predictions[:50])
    ]
    replay_status = {
        "schema_version": "state_replay_debugger_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "snapshots_available": len(replay_rows),
        "query_modes": [
            "v2_state_replay_debugger --decision-id <id>",
            "v2_state_replay_debugger --prediction-id <id>",
            "v2_state_replay_debugger --symbol BTCUSDT --latest",
        ],
        "sample_snapshots": replay_rows[:10],
    }
    backtest_impact = {
        "schema_version": "market_state_integrity_backtest_impact_status_v1",
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "before_integrity_filtering": {"samples": len(candidate_rows), "edge_claimed": False},
        "after_integrity_filtering": {"samples": len(accepted_training), "edge_claimed": False},
        "rejected_samples": len(rejected_training),
        "expectancy": None,
        "ci_lower": None,
        "false_positives": None,
        "false_negatives": None,
        "drawdown": None,
        "verdict": "NO_EDGE_CLAIM_INTEGRITY_FILTER_STATUS_ONLY",
    }
    return {
        "market_state_integrity_service_status.json": service_status,
        "event_time_alignment_validator_status.json": {
            "schema_version": "event_time_alignment_validator_status_v1",
            "generated_est": generated_est,
            "generated_utc": generated_utc,
            "rows_checked": len(alignment_rows),
            "rows": alignment_rows,
            "reject_statuses": ["TF_MISALIGNED", "UNCLOSED_CANDLE", "FUTURE_LEAKAGE", "SOURCE_EVENT_TIME_MISSING", "BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME"],
        },
        "candle_completion_validation_status.json": {
            "schema_version": "candle_completion_validation_status_v1",
            "generated_est": generated_est,
            "generated_utc": generated_utc,
            "rows_checked": len(candle_rows),
            "rows": candle_rows,
        },
        "source_disagreement_detection_status.json": source_disagreement,
        "runtime_latency_freshness_gate_status.json": latency_freshness,
        "training_sample_rejection_status.json": training_status,
        "prediction_integrity_gate_status.json": prediction_gate,
        "risk_orchestrator_integrity_enforcement_status.json": risk_orch,
        "paper_live_candidate_integrity_gate_status.json": paper_live,
        "masa_ppo_role_isolation_status.json": masa_status,
        "masa_ppo_disagreement_log.json": {
            "schema_version": "masa_ppo_disagreement_log_v1",
            "generated_est": generated_est,
            "generated_utc": generated_utc,
            "rows": disagreements[:200],
        },
        "state_replay_debugger_status.json": replay_status,
        "market_state_integrity_backtest_impact_status.json": backtest_impact,
    }


def write_payloads(payloads: dict[str, dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_dir / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
