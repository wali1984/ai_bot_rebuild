"""A+ goal Phase 2 evidence for directional balance and side gates."""
from __future__ import annotations

import json
import hashlib
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
TRAINER_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
TRAINER_HEARTBEAT_KEY = "v2:trainer:hybrid_cuda:heartbeat"
PHASE2_CONTRACT_RECEIPT_KEY = (
    "v2:trainer:a_plus:phase2:negative_expectancy_contract_receipt"
)
PHASE2_RECEIPT_SCHEMA = "v2_a_plus_phase2_executed_contract_receipt_v1"
PHASE2_TEST_PATH = (
    "v2/backend/tests/unit/services/native_trainer/"
    "test_a_plus_phase2_directional_balance.py"
)
PHASE2_TEST_NODE = "test_phase2_negative_expectancy_gate_contract"
CURRENT_CYCLE_ENVELOPE_SCHEMA = (
    "v2_native_trainer_current_cycle_learning_envelope_v1"
)


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


def _strict_utc(value: Any) -> datetime | None:
    text = str(value or "")
    if not text or (not text.endswith("Z") and "+" not in text[10:]):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (
        parsed.tzinfo is None
        or parsed.utcoffset() is None
        or parsed.utcoffset() != timezone.utc.utcoffset(parsed)
    ):
        return None
    return parsed.astimezone(timezone.utc)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _positive_ttl(client: Any, key: str) -> int | None:
    if client is None or not hasattr(client, "ttl"):
        return None
    try:
        ttl = int(client.ttl(key))
    except (OSError, TypeError, ValueError):
        return None
    return ttl if ttl > 0 else None


def _not_expired(value: Any, *, observed_at: datetime) -> bool:
    parsed = _strict_utc(value)
    return parsed is not None and observed_at <= parsed


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
    sessions = {
        str(row.get("paper_session_id"))
        for row in feedback_rows
        if row.get("paper_session_id") not in (None, "")
        and row.get("trainer_consumable") is True
    }
    return next(iter(sessions)) if len(sessions) == 1 else None


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


def _current_cycle_contract(
    *,
    redis_client: Any,
    metrics_payload: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    status = as_dict(_json_from_redis(redis_client, TRAINER_STATUS_KEY, {}))
    heartbeat = as_dict(_json_from_redis(redis_client, TRAINER_HEARTBEAT_KEY, {}))
    envelope = as_dict(metrics_payload.get("current_cycle_learning_envelope"))
    status_envelope = as_dict(status.get("current_cycle_learning_envelope"))
    cycle_id = str(envelope.get("cycle_id") or "")
    process_instance_id = str(envelope.get("process_instance_id") or "")
    checkpoint_id = str(envelope.get("checkpoint_id") or "")
    policy_fingerprint = str(envelope.get("candidate_policy_fingerprint") or "")
    exact_optimizer = as_dict(envelope.get("exact_optimizer_contract"))
    reasons: list[str] = []

    if not cycle_id or not process_instance_id:
        reasons.append("CURRENT_CYCLE_IDENTITY_MISSING")
    if envelope.get("schema_version") != CURRENT_CYCLE_ENVELOPE_SCHEMA:
        reasons.append("CURRENT_CYCLE_ENVELOPE_SCHEMA_INVALID")
    if not checkpoint_id or len(policy_fingerprint) != 64:
        reasons.append("CURRENT_CYCLE_CHECKPOINT_IDENTITY_MISSING")
    if status_envelope != envelope or not envelope:
        reasons.append("STATUS_METRICS_ENVELOPE_MISMATCH")
    for name, row in (("STATUS", status), ("HEARTBEAT", heartbeat), ("METRICS", metrics_payload)):
        if row.get("cycle_id") != cycle_id or row.get("process_instance_id") != process_instance_id:
            reasons.append(f"{name}_CURRENT_CYCLE_IDENTITY_MISMATCH")
    if status.get("runtime_readiness_status") != "READY" or status.get("trainer_learning_ready") is not True:
        reasons.append("TRAINER_CURRENT_CYCLE_NOT_READY")
    if status.get("status_publication_status") != "ACTIVE":
        reasons.append("TRAINER_STATUS_PUBLICATION_NOT_ACTIVE")
    if not _not_expired(status.get("status_payload_expires_at"), observed_at=observed_at):
        reasons.append("TRAINER_STATUS_EXPIRED_OR_INVALID")
    if not _not_expired(heartbeat.get("expires_at"), observed_at=observed_at):
        reasons.append("TRAINER_HEARTBEAT_EXPIRED_OR_INVALID")
    heartbeat_generated = _strict_utc(heartbeat.get("generated_utc"))
    if heartbeat_generated is None or heartbeat_generated > observed_at:
        reasons.append("TRAINER_HEARTBEAT_GENERATED_AT_INVALID")
    if _strict_utc(envelope.get("generated_utc")) is None:
        reasons.append("CURRENT_CYCLE_GENERATED_AT_INVALID")
    elif _strict_utc(envelope.get("generated_utc")) > observed_at:
        reasons.append("CURRENT_CYCLE_GENERATED_IN_FUTURE")
    for key in (TRAINER_STATUS_KEY, TRAINER_HEARTBEAT_KEY, TRAINER_METRICS_KEY):
        if _positive_ttl(redis_client, key) is None:
            reasons.append(f"POSITIVE_TTL_UNPROVEN:{key}")
    if (
        exact_optimizer.get("valid") is not True
        or exact_optimizer.get("ppo_objective_used") is not True
        or exact_optimizer.get("optimizer_parameter_fingerprints_bound") is not True
        or exact_optimizer.get("ledger_disposition") != "SERVING_PROMOTED"
        or int(envelope.get("optimizer_steps_this_cycle") or 0) <= 0
        or not envelope.get("parameter_hash_before")
        or envelope.get("parameter_hash_before") == envelope.get("parameter_hash_after")
    ):
        reasons.append("EXACT_CURRENT_CYCLE_OPTIMIZER_EVIDENCE_INVALID")
    return {
        "valid": not reasons,
        "cycle_id": cycle_id or None,
        "process_instance_id": process_instance_id or None,
        "checkpoint_id": checkpoint_id or None,
        "candidate_policy_fingerprint": policy_fingerprint or None,
        "status_expires_at": status.get("status_payload_expires_at"),
        "heartbeat_expires_at": heartbeat.get("expires_at"),
        "rejection_reasons": list(dict.fromkeys(reasons)),
    }


def _phase2_contract_receipt_validation(
    *,
    redis_client: Any,
    current_cycle: Mapping[str, Any],
    observed_at: datetime,
    diagnostic_output_sha256: str,
) -> dict[str, Any]:
    receipt = as_dict(
        _json_from_redis(redis_client, PHASE2_CONTRACT_RECEIPT_KEY, {})
    )
    repo_root = Path(__file__).resolve().parents[5]
    production_paths = (
        "v2/backend/app/services/paper_trade_management/side_performance.py",
        "v2/backend/app/services/paper_trade_management/entry_gate.py",
    )
    try:
        production_hashes = {
            path: _sha256_path(repo_root / path) for path in production_paths
        }
        test_hash = _sha256_path(repo_root / PHASE2_TEST_PATH)
    except OSError:
        production_hashes = {}
        test_hash = ""
    reasons: list[str] = []
    completed = _strict_utc(receipt.get("completed_at"))
    expires = _strict_utc(receipt.get("expires_at"))
    if receipt.get("schema_version") != PHASE2_RECEIPT_SCHEMA:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_SCHEMA_INVALID")
    if (
        receipt.get("cycle_id") != current_cycle.get("cycle_id")
        or receipt.get("process_instance_id")
        != current_cycle.get("process_instance_id")
    ):
        reasons.append("EXECUTED_CONTRACT_RECEIPT_CYCLE_IDENTITY_MISMATCH")
    if completed is None or expires is None or not (
        completed <= observed_at <= expires
    ):
        reasons.append("EXECUTED_CONTRACT_RECEIPT_NOT_CURRENT")
    if receipt.get("pytest_nodeid") != f"{PHASE2_TEST_PATH}::{PHASE2_TEST_NODE}":
        reasons.append("EXECUTED_CONTRACT_RECEIPT_NODE_MISMATCH")
    if receipt.get("outcome") != "PASSED" or receipt.get("exit_code") != 0:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_NOT_PASSED")
    runner_command = str(receipt.get("runner_command") or "")
    runner_command_sha256 = hashlib.sha256(runner_command.encode("utf-8")).hexdigest()
    if (
        not runner_command
        or receipt.get("runner_command_sha256") != runner_command_sha256
    ):
        reasons.append("EXECUTED_CONTRACT_RECEIPT_COMMAND_HASH_INVALID")
    if receipt.get("production_source_sha256") != production_hashes or not production_hashes:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_PRODUCTION_SOURCE_MISMATCH")
    if receipt.get("test_source_sha256") != test_hash or not test_hash:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_TEST_SOURCE_MISMATCH")
    if receipt.get("diagnostic_output_sha256") != diagnostic_output_sha256:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_OUTPUT_MISMATCH")
    unsigned = dict(receipt)
    claimed_hash = str(unsigned.pop("receipt_sha256", ""))
    try:
        actual_hash = _canonical_sha256(unsigned)
    except (TypeError, ValueError):
        actual_hash = ""
    if not claimed_hash or claimed_hash != actual_hash:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_HASH_INVALID")
    if _positive_ttl(redis_client, PHASE2_CONTRACT_RECEIPT_KEY) is None:
        reasons.append("EXECUTED_CONTRACT_RECEIPT_POSITIVE_TTL_UNPROVEN")
    return {
        "valid": not reasons,
        "evidence_class": "NONCANONICAL_EXECUTED_CODE_CONTRACT_DIAGNOSTIC",
        "counts_as_a_plus_readiness": False,
        "rejection_reasons": list(dict.fromkeys(reasons)),
        "receipt_sha256": claimed_hash or None,
        "diagnostic_output_sha256": diagnostic_output_sha256,
        "production_source_sha256": production_hashes,
        "test_source_sha256": test_hash or None,
    }


def _signal_distribution(
    redis_client: Any,
    *,
    current_cycle: Mapping[str, Any],
    observed_at: datetime,
    max_keys: int = 5000,
) -> dict[str, Any]:
    all_counts: Counter[str] = Counter()
    current_counts: Counter[str] = Counter()
    checkpoint_counts: Counter[str] = Counter()
    rejection_counts: Counter[str] = Counter()
    scanned = 0
    scan_truncated = False
    current_checkpoint_id = current_cycle.get("checkpoint_id")
    if redis_client is None or not hasattr(redis_client, "scan_iter"):
        return {
            "scan_available": False,
            "rows_scanned": 0,
            "current_checkpoint_id": current_checkpoint_id,
            "all_checkpoints": {},
            "current_checkpoint": {},
            "current_checkpoint_long_share_of_directional_pct": None,
            "all_long_share_of_directional_pct": None,
            "current_cycle_evidence_valid": False,
            "rejection_counts": {"REDIS_SCAN_UNAVAILABLE": 1},
        }
    try:
        iterator = redis_client.scan_iter(match=SIGNAL_KEY_PATTERN, count=250)
    except TypeError:
        iterator = redis_client.scan_iter(SIGNAL_KEY_PATTERN)
    for key in iterator:
        if scanned >= max_keys:
            scan_truncated = True
            break
        scanned += 1
        key_text = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        payload = _json_from_redis(redis_client, key_text, {})
        if not isinstance(payload, Mapping):
            rejection_counts["PAYLOAD_INVALID"] += 1
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
        row_reasons: list[str] = []
        if (
            payload.get("cycle_id") != current_cycle.get("cycle_id")
            or payload.get("process_instance_id")
            != current_cycle.get("process_instance_id")
            or checkpoint != str(current_checkpoint_id)
            or payload.get("candidate_policy_fingerprint")
            != current_cycle.get("candidate_policy_fingerprint")
        ):
            row_reasons.append("CURRENT_CYCLE_IDENTITY_MISMATCH")
        if _positive_ttl(redis_client, key_text) is None:
            row_reasons.append("POSITIVE_TTL_UNPROVEN")
        feature_cutoff = _strict_utc(payload.get("feature_cutoff"))
        available_at = _strict_utc(payload.get("available_at"))
        decision_time = _strict_utc(payload.get("decision_time"))
        if (
            feature_cutoff is None
            or available_at is None
            or decision_time is None
            or feature_cutoff > decision_time
            or available_at > decision_time
            or decision_time > observed_at
        ):
            row_reasons.append("PIT_CLOCK_CONTRACT_INVALID")
        if not as_dict(payload.get("source_hashes")):
            row_reasons.append("SOURCE_HASH_LINEAGE_MISSING")
        if side not in {"LONG", "SHORT"}:
            row_reasons.append("DIRECTIONAL_ACTION_MISSING")
        if row_reasons:
            for reason in set(row_reasons):
                rejection_counts[reason] += 1
        else:
            current_counts[side] += 1

    def long_share(counts: Counter[str]) -> float | None:
        directional = counts.get("LONG", 0) + counts.get("SHORT", 0)
        if directional <= 0:
            return None
        return round((counts.get("LONG", 0) / directional) * 100.0, 6)

    return {
        "scan_available": True,
        "rows_scanned": scanned,
        "scan_truncated": scan_truncated,
        "current_checkpoint_id": current_checkpoint_id,
        "all_checkpoints": dict(sorted(all_counts.items())),
        "current_checkpoint": dict(sorted(current_counts.items())),
        "signal_rows_by_checkpoint": dict(sorted(checkpoint_counts.items())),
        "current_checkpoint_long_share_of_directional_pct": long_share(current_counts),
        "all_long_share_of_directional_pct": long_share(all_counts),
        "long_and_short_present_current_checkpoint": current_counts.get("LONG", 0) > 0 and current_counts.get("SHORT", 0) > 0,
        "long_and_short_present_all_signals": all_counts.get("LONG", 0) > 0 and all_counts.get("SHORT", 0) > 0,
        "current_cycle_evidence_valid": bool(
            current_counts.get("LONG", 0) > 0
            and current_counts.get("SHORT", 0) > 0
            and not scan_truncated
        ),
        "rejection_counts": dict(sorted(rejection_counts.items())),
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
    observed_at = _strict_utc(generated)
    observed_clock_valid = observed_at is not None
    if observed_at is None:
        observed_at = datetime.min.replace(tzinfo=timezone.utc)
    feedback_rows = _rows(_json_from_redis(redis_client, FEEDBACK_KEY, []))
    paper_session_id = _current_paper_session_id(feedback_rows)
    session_ids = sorted(
        {
            str(row.get("paper_session_id"))
            for row in feedback_rows
            if row.get("trainer_consumable") is True
            and row.get("paper_session_id") not in (None, "")
        }
    )
    # A cached aggregate can outlive its feedback/session.  Recompute the
    # evidence from the exact current Redis feedback rows on every report run.
    raw_side_performance = build_side_performance(
        feedback_rows,
        paper_session_id=paper_session_id,
        generated_utc=generated,
    )
    metrics_payload = as_dict(_json_from_redis(redis_client, TRAINER_METRICS_KEY, {}))
    metric_fields = _trainer_metric_fields(metrics_payload)
    current_cycle = _current_cycle_contract(
        redis_client=redis_client,
        metrics_payload=metrics_payload,
        observed_at=observed_at,
    )
    signal_distribution = _signal_distribution(
        redis_client,
        current_cycle=current_cycle,
        observed_at=observed_at,
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
    negative_proof["evidence_class"] = (
        "NONCANONICAL_DIAGNOSTIC_SYNTHETIC_SCENARIO"
    )
    negative_proof["counts_as_a_plus_readiness"] = False
    negative_proof_sha256 = _canonical_sha256(negative_proof)
    negative_contract_receipt = _phase2_contract_receipt_validation(
        redis_client=redis_client,
        current_cycle=current_cycle,
        observed_at=observed_at,
        diagnostic_output_sha256=negative_proof_sha256,
    )
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
    hard_rule_observed_current = any(
        evaluation.get("allowed") is False
        and any(
            "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE" in reason
            for reason in evaluation.get("reasons", [])
        )
        for evaluation in side_gate_evaluations.values()
    )
    metric_checkpoint_bound = bool(
        metric_fields.get("checkpoint_id")
        and metric_fields.get("checkpoint_id") == current_cycle.get("checkpoint_id")
    )
    signal_long_short_present = bool(
        signal_distribution.get("long_and_short_present_current_checkpoint")
        and signal_distribution.get("current_cycle_evidence_valid")
    )
    side_feedback_current_session = bool(
        observed_clock_valid
        and paper_session_id
        and len(session_ids) == 1
        and side_buckets["LONG"].get("trade_count", 0) > 0
        and side_buckets["SHORT"].get("trade_count", 0) > 0
    )
    pass_conditions = {
        "observed_clock_strict_utc": observed_clock_valid,
        "current_cycle_runtime_evidence_valid": current_cycle["valid"],
        "metric_checkpoint_bound_to_current_cycle": metric_checkpoint_bound,
        "single_exact_paper_session_with_both_sides": side_feedback_current_session,
        "class_weighted_loss_active": class_weighted_loss["active"],
        "long_label_present": bool(metric_fields.get("long_label_present")),
        "short_label_present": bool(metric_fields.get("short_label_present")),
        "long_viable_paper_path": long_viable,
        "short_viable_paper_path": short_viable,
        "signal_long_and_short_present": signal_long_short_present,
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
        "paper_session_ids_observed": session_ids,
        "current_cycle_evidence": current_cycle,
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
        "current_long_share_of_directional_pct": signal_distribution.get(
            "current_checkpoint_long_share_of_directional_pct"
        ),
        "long_short_specific_confidence_gates": {
            "code_path": "paper_trade_management/side_performance.py::evaluate_side_gate wired in entry_gate.evaluate_entry_gate",
            "long_confidence_floor": confidence_floors["LONG"],
            "short_confidence_floor": confidence_floors["SHORT"],
            "floor_raised_by_side_brier_calibration": True,
        },
        "behavioral_proof_negative_expectancy_block": negative_proof,
        "behavioral_proof_evidence_class": (
            "NONCANONICAL_DIAGNOSTIC_SYNTHETIC_SCENARIO"
        ),
        "behavioral_proof_counts_as_a_plus_readiness": False,
        "executed_contract_receipt": negative_contract_receipt,
        "pass_conditions": pass_conditions,
        "missing_evidence": missing_evidence,
        "raw_evidence_pointers": [
            f"redis:{TRAINER_METRICS_KEY} -> training.metrics.action_class_weights",
            f"redis:{SIDE_PERFORMANCE_REDIS_KEY}",
            f"redis scan {SIGNAL_KEY_PATTERN}",
            f"redis:{TRAINER_STATUS_KEY}",
            f"redis:{TRAINER_HEARTBEAT_KEY}",
        ],
    }
    calibration = {
        **base,
        "schema_version": "long_short_calibration_status_v2",
        "status": (
            "LONG_SHORT_CALIBRATION_CURRENT_EVIDENCE_READY"
            if current_cycle["valid"]
            and side_feedback_current_session
            and long_viable
            and short_viable
            else "BLOCKED_SIDE_CALIBRATION"
        ),
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
        "status": (
            "SIDE_BUCKET_GATE_CURRENT_RUNTIME_OBSERVATION_READY"
            if current_cycle["valid"]
            and side_feedback_current_session
            and hard_rule_observed_current
            else "BLOCKED_SIDE_BUCKET_GATE_NO_CURRENT_RUNTIME_BLOCK_OBSERVED"
        ),
        "hard_rule": "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE blocks new entries for that side once min sample reached; enforced in entry_gate.evaluate_entry_gate via evaluate_side_gate",
        "side_buckets": side_buckets,
        "side_gate_evaluations": side_gate_evaluations,
        "negative_expectancy_block_proof": negative_proof,
        "negative_expectancy_contract_receipt": negative_contract_receipt,
        "current_runtime_negative_expectancy_block_observed": (
            hard_rule_observed_current
        ),
        "missing_evidence": [
            reason
            for reason in missing_evidence
            if reason in {"long_viable_paper_path", "short_viable_paper_path"}
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
