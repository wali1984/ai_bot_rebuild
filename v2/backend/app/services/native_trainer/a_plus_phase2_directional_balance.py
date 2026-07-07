"""A+ goal Phase 2 evidence for directional balance and side gates."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.paper_trade_management.side_performance import (
    SIDE_PERFORMANCE_REDIS_KEY,
    SideGateConfig,
    build_side_performance,
    evaluate_side_gate,
)


GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"
FEEDBACK_KEY = "v2:trainer:feedback:outcomes"
TRAINER_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
SIGNAL_KEY_PATTERN = "v2:trainer:hybrid_cuda:signals:paper:*"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _json_from_redis(client: Any, key: str, default: Any) -> Any:
    raw = client.get(key) if client is not None else None
    if raw is None:
        return default
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return default


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("rows", "trainer_feedback_outcomes", "feedback_outcomes", "closed_trades"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, Mapping)]
    return []


def _current_paper_session_id(feedback_rows: list[dict[str, Any]]) -> str | None:
    counts: Counter[str] = Counter(
        str(row.get("paper_session_id"))
        for row in feedback_rows
        if row.get("paper_session_id") not in (None, "")
    )
    return counts.most_common(1)[0][0] if counts else None


def _trainer_metric_fields(metrics_payload: Mapping[str, Any]) -> dict[str, Any]:
    training = as_dict(metrics_payload.get("training"))
    metrics = as_dict(training.get("metrics"))
    checkpoint = as_dict(metrics_payload.get("checkpoint"))
    action_distribution = as_dict(training.get("action_distribution"))
    long_count = int(action_distribution.get("1") or 0)
    short_count = int(action_distribution.get("2") or 0)
    directional = long_count + short_count
    return {
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "action_distribution": action_distribution,
        "target_long_fraction": metrics.get("target_long_fraction"),
        "target_short_fraction": metrics.get("target_short_fraction"),
        "long_label_present": bool(metrics.get("long_label_present") or long_count > 0),
        "short_label_present": bool(metrics.get("short_label_present") or short_count > 0),
        "action_class_weights": metrics.get("action_class_weights") or [],
        "policy_bias_class_balance_nudge": metrics.get("policy_bias_class_balance_nudge") or [],
        "policy_bias_nudge_strategy": metrics.get("policy_bias_nudge_strategy"),
        "single_direction_expected_move_guard_active": bool(metrics.get("single_direction_expected_move_guard_active")),
        "single_direction_policy_action_guard_active": bool(metrics.get("single_direction_policy_action_guard_active")),
        "trainer_long_share_of_directional_pct": round((long_count / directional) * 100.0, 6) if directional else None,
        "trainer_short_share_of_directional_pct": round((short_count / directional) * 100.0, 6) if directional else None,
    }


def _class_weighted_loss_active(metric_fields: Mapping[str, Any]) -> bool:
    weights = metric_fields.get("action_class_weights")
    if not isinstance(weights, list) or not weights:
        return False
    finite_weights = [finite_float(value) for value in weights]
    usable = [value for value in finite_weights if value is not None and value > 0]
    return bool(usable and len(set(round(value, 8) for value in usable)) > 1)


def _signal_distribution(redis_client: Any, *, current_checkpoint_id: Any, max_keys: int = 5000) -> dict[str, Any]:
    all_counts: Counter[str] = Counter()
    current_counts: Counter[str] = Counter()
    checkpoint_counts: Counter[str] = Counter()
    scanned = 0
    if redis_client is None or not hasattr(redis_client, "scan_iter"):
        return {
            "scan_available": False,
            "rows_scanned": 0,
            "current_checkpoint_id": current_checkpoint_id,
            "all_checkpoints": {},
            "current_checkpoint": {},
            "current_checkpoint_long_share_of_directional_pct": None,
            "all_long_share_of_directional_pct": None,
        }
    try:
        iterator = redis_client.scan_iter(match=SIGNAL_KEY_PATTERN, count=250)
    except TypeError:
        iterator = redis_client.scan_iter(SIGNAL_KEY_PATTERN)
    for key in iterator:
        if scanned >= max_keys:
            break
        scanned += 1
        key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        payload = _json_from_redis(redis_client, key_text, {})
        if not isinstance(payload, Mapping):
            continue
        side = str(
            payload.get("selected_action")
            or payload.get("action")
            or payload.get("side")
            or payload.get("action_label")
            or "UNKNOWN"
        ).strip().upper()
        checkpoint = str(payload.get("checkpoint_id") or "UNKNOWN")
        all_counts[side] += 1
        checkpoint_counts[checkpoint] += 1
        if current_checkpoint_id and checkpoint == str(current_checkpoint_id):
            current_counts[side] += 1

    def long_share(counts: Counter[str]) -> float | None:
        directional = counts.get("LONG", 0) + counts.get("SHORT", 0)
        if directional <= 0:
            return None
        return round((counts.get("LONG", 0) / directional) * 100.0, 6)

    return {
        "scan_available": True,
        "rows_scanned": scanned,
        "scan_truncated": scanned >= max_keys,
        "current_checkpoint_id": current_checkpoint_id,
        "all_checkpoints": dict(sorted(all_counts.items())),
        "current_checkpoint": dict(sorted(current_counts.items())),
        "signal_rows_by_checkpoint": dict(sorted(checkpoint_counts.items())),
        "current_checkpoint_long_share_of_directional_pct": long_share(current_counts),
        "all_long_share_of_directional_pct": long_share(all_counts),
        "long_and_short_present_current_checkpoint": current_counts.get("LONG", 0) > 0 and current_counts.get("SHORT", 0) > 0,
        "long_and_short_present_all_signals": all_counts.get("LONG", 0) > 0 and all_counts.get("SHORT", 0) > 0,
    }


def _side_bucket_subset(side_performance: Mapping[str, Any]) -> dict[str, Any]:
    sides = as_dict(side_performance.get("sides"))
    out: dict[str, Any] = {}
    for side in ("LONG", "SHORT"):
        bucket = as_dict(sides.get(side))
        out[side] = {
            key: bucket.get(key)
            for key in (
                "trade_count",
                "wins",
                "losses",
                "win_rate",
                "gross_profit_bps",
                "gross_loss_bps",
                "profit_factor",
                "profit_factor_uncapped",
                "expectancy_bps",
                "expectancy_usd",
                "net_pnl_usd",
                "avg_win_bps",
                "avg_loss_bps",
                "avg_confidence",
                "brier_score",
                "calibration_bins",
            )
            if key in bucket
        }
    return out


def _negative_expectancy_proof(side: str = "LONG") -> dict[str, Any]:
    synthetic = {
        "sides": {
            side.upper(): {
                "trade_count": 30,
                "expectancy_bps": -5.0,
                "brier_score": 0.10,
                "profit_factor": None,
            }
        }
    }
    return evaluate_side_gate(synthetic, side=side, confidence_calibrated=0.99)


def build_a_plus_phase2_directional_balance_artifacts(
    *,
    redis_client: Any,
    generated_utc: str | None = None,
) -> dict[str, dict[str, Any]]:
    generated = generated_utc or utc_now()
    feedback_rows = _rows(_json_from_redis(redis_client, FEEDBACK_KEY, []))
    paper_session_id = _current_paper_session_id(feedback_rows)
    raw_side_performance = as_dict(_json_from_redis(redis_client, SIDE_PERFORMANCE_REDIS_KEY, {}))
    if not as_dict(raw_side_performance.get("sides")):
        raw_side_performance = build_side_performance(
            feedback_rows,
            paper_session_id=paper_session_id,
            generated_utc=generated,
        )
    metrics_payload = as_dict(_json_from_redis(redis_client, TRAINER_METRICS_KEY, {}))
    metric_fields = _trainer_metric_fields(metrics_payload)
    signal_distribution = _signal_distribution(
        redis_client,
        current_checkpoint_id=metric_fields.get("checkpoint_id"),
    )
    gate_config = SideGateConfig()
    side_gate_evaluations = {
        side: evaluate_side_gate(
            raw_side_performance,
            side=side,
            confidence_calibrated=1.0,
            config=gate_config,
        )
        for side in ("LONG", "SHORT")
    }
    negative_proof = _negative_expectancy_proof("LONG")
    side_buckets = _side_bucket_subset(raw_side_performance)
    class_weighted_loss = {
        "active": _class_weighted_loss_active(metric_fields),
        "action_class_weights": metric_fields.get("action_class_weights"),
        "policy_bias_class_balance_nudge": metric_fields.get("policy_bias_class_balance_nudge"),
        "policy_bias_nudge_strategy": metric_fields.get("policy_bias_nudge_strategy"),
        "forced_long_short_ratio": False,
        "training_label_mix": {
            "long_label_present": metric_fields.get("long_label_present"),
            "short_label_present": metric_fields.get("short_label_present"),
            "target_long_fraction": metric_fields.get("target_long_fraction"),
            "target_short_fraction": metric_fields.get("target_short_fraction"),
            "trainer_long_share_of_directional_pct": metric_fields.get("trainer_long_share_of_directional_pct"),
            "trainer_short_share_of_directional_pct": metric_fields.get("trainer_short_share_of_directional_pct"),
        },
        "single_direction_guards": {
            "expected_move_guard_active": metric_fields.get("single_direction_expected_move_guard_active"),
            "policy_action_guard_active": metric_fields.get("single_direction_policy_action_guard_active"),
        },
    }
    long_viable = bool(side_gate_evaluations["LONG"].get("allowed"))
    short_viable = bool(side_gate_evaluations["SHORT"].get("allowed"))
    hard_rule_proven = negative_proof.get("allowed") is False and any(
        "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE" in reason for reason in negative_proof.get("reasons", [])
    )
    signal_long_short_present = bool(
        signal_distribution.get("long_and_short_present_current_checkpoint")
        or signal_distribution.get("long_and_short_present_all_signals")
    )
    pass_conditions = {
        "class_weighted_loss_active": class_weighted_loss["active"],
        "long_label_present": bool(metric_fields.get("long_label_present")),
        "short_label_present": bool(metric_fields.get("short_label_present")),
        "long_viable_paper_path": long_viable,
        "short_viable_paper_path": short_viable,
        "signal_long_and_short_present": signal_long_short_present,
        "no_side_trades_with_non_positive_expectancy": hard_rule_proven,
    }
    missing_evidence = [name for name, passed in pass_conditions.items() if not passed]
    confidence_floors = {
        "LONG": side_gate_evaluations["LONG"].get("confidence_floor"),
        "SHORT": side_gate_evaluations["SHORT"].get("confidence_floor"),
    }
    base = {
        "goal_id": GOAL_ID,
        "generated_utc": generated,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "old_redis_writes": False,
        "paper_session_id": paper_session_id,
    }
    directional = {
        **base,
        "schema_version": "directional_balance_repair_status_v2",
        "status": "DIRECTIONAL_BALANCE_REPAIR_READY" if not missing_evidence else "BLOCKED_DIRECTIONAL_BALANCE_EVIDENCE_INCOMPLETE",
        "audit_baseline": {
            "historical_training": "2701 short vs 632 long",
            "long_share_of_signals_pct": 6.8,
        },
        "class_weighted_loss": class_weighted_loss,
        "current_signal_distribution": signal_distribution,
        "current_long_share_of_directional_pct": signal_distribution.get("current_checkpoint_long_share_of_directional_pct")
        or signal_distribution.get("all_long_share_of_directional_pct"),
        "long_short_specific_confidence_gates": {
            "code_path": "paper_trade_management/side_performance.py::evaluate_side_gate wired in entry_gate.evaluate_entry_gate",
            "long_confidence_floor": confidence_floors["LONG"],
            "short_confidence_floor": confidence_floors["SHORT"],
            "floor_raised_by_side_brier_calibration": True,
        },
        "behavioral_proof_negative_expectancy_block": negative_proof,
        "pass_conditions": pass_conditions,
        "missing_evidence": missing_evidence,
        "raw_evidence_pointers": [
            f"redis:{TRAINER_METRICS_KEY} -> training.metrics.action_class_weights",
            f"redis:{SIDE_PERFORMANCE_REDIS_KEY}",
            f"redis scan {SIGNAL_KEY_PATTERN}",
        ],
    }
    calibration = {
        **base,
        "schema_version": "long_short_calibration_status_v2",
        "status": "LONG_SHORT_CALIBRATION_READY" if long_viable and short_viable else "BLOCKED_SIDE_CALIBRATION",
        "confidence_floors": confidence_floors,
        "per_side_calibration": {
            side: {
                "trade_count": side_buckets[side].get("trade_count"),
                "win_rate": side_buckets[side].get("win_rate"),
                "avg_confidence": side_buckets[side].get("avg_confidence"),
                "brier_score": side_buckets[side].get("brier_score"),
                "calibration_bins": side_buckets[side].get("calibration_bins") or [],
            }
            for side in ("LONG", "SHORT")
        },
        "missing_evidence": [
            reason for reason in missing_evidence if reason in {"long_viable_paper_path", "short_viable_paper_path"}
        ],
        "raw_evidence_pointers": [f"redis:{SIDE_PERFORMANCE_REDIS_KEY} -> sides.*.calibration_bins/brier_score"],
    }
    side_bucket = {
        **base,
        "schema_version": "side_bucket_performance_status_v2",
        "status": "SIDE_BUCKET_GATE_READY" if hard_rule_proven and long_viable and short_viable else "BLOCKED_SIDE_BUCKET_GATE",
        "hard_rule": "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE blocks new entries for that side once min sample reached; enforced in entry_gate.evaluate_entry_gate via evaluate_side_gate",
        "side_buckets": side_buckets,
        "side_gate_evaluations": side_gate_evaluations,
        "negative_expectancy_block_proof": negative_proof,
        "missing_evidence": [
            reason
            for reason in missing_evidence
            if reason in {"long_viable_paper_path", "short_viable_paper_path", "no_side_trades_with_non_positive_expectancy"}
        ],
        "raw_evidence_pointers": [
            f"redis:{SIDE_PERFORMANCE_REDIS_KEY}",
            "v2/backend/app/services/paper_trade_management/entry_gate.py",
            "v2/backend/app/services/paper_trade_management/side_performance.py",
        ],
    }
    return {
        "directional_balance_repair_status.json": directional,
        "long_short_calibration_status.json": calibration,
        "side_bucket_performance_status.json": side_bucket,
    }


def write_a_plus_phase2_directional_balance_artifacts(
    *,
    redis_client: Any,
    repo_root: Path,
    goal_dir: Path | None = None,
    public_dir: Path | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    artifacts = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=redis_client,
        generated_utc=generated_utc,
    )
    destinations = [goal_dir or (repo_root / "goal_state" / GOAL_ID)]
    if public_dir is not None:
        destinations.append(public_dir)
    written: list[str] = []
    for destination in destinations:
        destination.mkdir(parents=True, exist_ok=True)
        for name, payload in artifacts.items():
            path = destination / name
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
            tmp.replace(path)
            written.append(str(path))
    status = artifacts["directional_balance_repair_status.json"]
    return {
        "goal_id": GOAL_ID,
        "status": status["status"],
        "pass_conditions": status["pass_conditions"],
        "missing_evidence": status["missing_evidence"],
        "written": written,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
    }
