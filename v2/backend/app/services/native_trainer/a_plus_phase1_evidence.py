"""Legacy A+ Phase 1 trainer-learning diagnostics.

This module is intentionally read-only with respect to Redis and exchange
state. It builds goal artifacts from current trainer feedback, CUDA trainer
metrics, and local checkpoint blobs. Those mutable inputs are not the
canonical identity-bound current-cycle runtime contract, so the artifacts are
non-authoritative diagnostics even when every local condition is observed.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"

EVIDENCE_SCOPE = "LEGACY_NON_CANONICAL_DIAGNOSTIC"
DIAGNOSTIC_COMPLETE = "LEGACY_DIAGNOSTIC_EVIDENCE_COMPLETE_NON_CANONICAL"
DIAGNOSTIC_INCOMPLETE = "LEGACY_DIAGNOSTIC_EVIDENCE_INCOMPLETE"

FEEDBACK_KEY = "v2:trainer:feedback:outcomes"
FEEDBACK_QUARANTINE_KEY = "v2:trainer:feedback:outcomes:quarantine"
CLOSED_TRADES_KEY = "v2:paper:closed_trades"
TRAINER_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
SIGNAL_KEY_PATTERN = "v2:trainer:hybrid_cuda:signals:paper:*"

REQUIRED_FEEDBACK_CONTRACT_FIELDS: tuple[str, ...] = (
    "paper_session_id",
    "prediction_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "available_at",
    "decision_time",
    "side",
    "action",
    "strategy_id",
    "expected_move_after_cost_bps",
    "realized_pnl_bps",
    "realized_pnl_usd",
    "fees",
    "slippage",
    "funding",
    "MFE",
    "MAE",
    "exit_reason",
    "outcome_label",
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "prediction_id": ("prediction_id", "entry_prediction_id"),
    "feature_snapshot_id": ("feature_snapshot_id", "entry_feature_snapshot_id"),
    "side": ("side", "selected_action", "action"),
    "realized_pnl_usd": ("realized_pnl_usd", "realized_net_pnl_usd", "realized_pnl"),
    "fees": ("fees", "fee_usd", "commission_usd"),
    "slippage": ("slippage", "realized_slippage_usd", "expected_slippage_usd"),
    "funding": ("funding", "funding_usd", "holding_period_funding_usd", "holding_period_funding_bps"),
    "MFE": ("MFE", "mfe", "mfe_bps", "mfe_usd"),
    "MAE": ("MAE", "mae", "mae_bps", "mae_usd"),
    "outcome_label": ("outcome_label", "outcome_label_id", "trade_outcome"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _non_runtime_evidence_boundary(generated_utc: str) -> dict[str, Any]:
    """Make the legacy artifact's lack of runtime authority machine-readable.

    Phase 1 reads mutable ``latest`` Redis payloads and local checkpoint paths.
    It does not consume the canonical, identity-bound current-cycle runtime
    contract, so even a complete diagnostic must never authorize readiness,
    serving, A+ classification, paper routing, or live execution.
    """

    return {
        "evidence_scope": EVIDENCE_SCOPE,
        "contract_test_only": False,
        "canonical_current_cycle_contract_consumed": False,
        "canonical_current_cycle_contract_verified": False,
        "canonical_runtime_ready": False,
        "serving_authorized": False,
        "a_plus_authorized": False,
        "paper_authorized": False,
        "live_authorized": False,
        "live_execution_authorized": False,
        "routes_to_paper": False,
        "routes_to_live": False,
        "paper_only": True,
        "producer_clock_field": "generated_utc",
        "artifact_generated_at": generated_utc,
        "artifact_persistence": "OVERWRITTEN_NON_EXPIRING_JSON_SNAPSHOT",
        "artifact_ttl_enforced": False,
        "artifact_expires_at": None,
        "artifact_freshness_authoritative": False,
        "runtime_authority_block_reason": (
            "CANONICAL_IDENTITY_BOUND_CURRENT_CYCLE_RUNTIME_CONTRACT_NOT_CONSUMED"
        ),
    }


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


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def first_number(*values: Any) -> float:
    for value in values:
        parsed = finite_float(value)
        if parsed is not None:
            return parsed
    return 0.0


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


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in (
            "trainer_feedback_outcomes",
            "feedback_outcomes",
            "rows",
            "closed_trades",
            "closed_positions",
            "trainer_feedback_outcomes_quarantine",
            "quarantine",
            "items",
            "trades",
        ):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def _value_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _field_present(row: Mapping[str, Any], field: str) -> bool:
    aliases = FIELD_ALIASES.get(field, (field,))
    return any(_value_present(row.get(alias)) for alias in aliases)


def _feedback_contract_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    coverage: dict[str, int] = {field: 0 for field in REQUIRED_FEEDBACK_CONTRACT_FIELDS}
    missing_counts: Counter[str] = Counter()
    complete_rows = 0
    complete_consumable_rows = 0
    invalid_consumed_rows = 0
    session_counts: Counter[str] = Counter()
    side_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()

    for row in rows_list:
        missing: list[str] = []
        for field in REQUIRED_FEEDBACK_CONTRACT_FIELDS:
            if _field_present(row, field):
                coverage[field] += 1
            else:
                missing.append(field)
                missing_counts[field] += 1
        complete = not missing
        if complete:
            complete_rows += 1
        trainer_consumable = row.get("trainer_consumable") is True
        valid_closed = str(row.get("closed_trade_validity_status") or "").upper() in {
            "VALID_CLOSED_TRADE",
            "VALID",
            "OK",
        }
        production_grade = row.get("counts_as_production_grade_training_evidence") is not False
        quarantined = str(row.get("quarantine_reason") or "NONE").upper() not in {"", "NONE"}
        if complete and trainer_consumable and valid_closed and production_grade and not quarantined:
            complete_consumable_rows += 1
        if trainer_consumable and (quarantined or not valid_closed):
            invalid_consumed_rows += 1
        session = row.get("paper_session_id")
        if _value_present(session):
            session_counts[str(session)] += 1
        side = first_present(row.get("side"), row.get("selected_action"), row.get("action"))
        if _value_present(side):
            side_counts[str(side).upper()] += 1
        outcome = first_present(row.get("outcome_label"), row.get("trade_outcome"))
        if _value_present(outcome):
            outcome_counts[str(outcome).upper()] += 1

    current_session_id = session_counts.most_common(1)[0][0] if session_counts else None
    return {
        "feedback_rows_total": len(rows_list),
        "feedback_rows_current_session": int(session_counts.get(current_session_id, 0)) if current_session_id else 0,
        "paper_session_id": current_session_id,
        "required_fields": list(REQUIRED_FEEDBACK_CONTRACT_FIELDS),
        "required_field_coverage": coverage,
        "required_field_coverage_complete": bool(rows_list and complete_rows == len(rows_list)),
        "contract_complete_rows": complete_rows,
        "consumable_feedback_rows": complete_consumable_rows,
        "contract_missing_counts": dict(sorted(missing_counts.items())),
        "invalid_consumed_rows": invalid_consumed_rows,
        "side_counts": dict(sorted(side_counts.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
    }


def _quarantine_reason_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        emitted = False
        for field in (
            "trust_envelope_rejection_reasons",
            "trust_reconstruction_rejection_reasons",
            "audit_quality_rejection_reasons",
            "missing_feedback_classifications",
            "missing_feedback_fields",
        ):
            values = row.get(field)
            if isinstance(values, list):
                for value in values:
                    if _value_present(value):
                        counts[str(value)] += 1
                        emitted = True
            elif _value_present(values):
                counts[str(values)] += 1
                emitted = True
        if not emitted:
            reason = str(row.get("quarantine_reason") or "quarantined_without_reason")
            for part in reason.split(","):
                text = part.strip() or "quarantined_without_reason"
                if text.upper() != "NONE":
                    counts[text] += 1
    return dict(sorted(counts.items()))


def _trainer_metrics_summary(metrics_payload: Mapping[str, Any]) -> dict[str, Any]:
    training = as_dict(metrics_payload.get("training"))
    nested = as_dict(training.get("metrics"))
    checkpoint = as_dict(metrics_payload.get("checkpoint"))
    checkpoint_load = as_dict(metrics_payload.get("checkpoint_load"))
    checkpoint_reload = as_dict(metrics_payload.get("checkpoint_reload"))
    trusted_rows_loaded = int(
        first_number(
            nested.get("trusted_rows_loaded"),
            training.get("trusted_rows_loaded"),
            training.get("train_rows"),
        )
    )
    feedback_rows_entered_batch = int(
        first_number(
            nested.get("feedback_rows_entered_batch"),
            nested.get("closed_trade_feedback_rows_loaded"),
        )
    )
    optimizer_steps_this_cycle = int(first_number(nested.get("optimizer_steps_this_cycle")))
    optimizer_steps_total = int(first_number(nested.get("optimizer_steps_total"), optimizer_steps_this_cycle))
    parameter_hash_before = first_present(nested.get("parameter_hash_before"), training.get("parameter_hash_before"))
    parameter_hash_after = first_present(nested.get("parameter_hash_after"), training.get("parameter_hash_after"))
    weight_delta_norm = first_number(nested.get("weight_delta_norm"))
    checkpoint_path = first_present(
        nested.get("checkpoint_path"),
        training.get("checkpoint_path"),
        checkpoint.get("weight_file_path"),
        checkpoint_reload.get("weight_file_path"),
        checkpoint_load.get("weight_file_path"),
    )
    checkpoint_hash = first_present(
        nested.get("checkpoint_hash"),
        metrics_payload.get("checkpoint_hash"),
        training.get("checkpoint_hash"),
    )
    checkpoint_weight_blob_written = bool(
        first_present(
            nested.get("checkpoint_weight_blob_written"),
            training.get("checkpoint_weight_blob_written"),
            checkpoint.get("weight_blob_written"),
        )
    )
    checkpoint_reload_verified = bool(
        first_present(
            nested.get("checkpoint_reload_verified"),
            metrics_payload.get("checkpoint_reload_verified"),
            training.get("checkpoint_reload_verified"),
        )
    )
    return {
        "training_status": training.get("status"),
        "training_steps": training.get("training_steps"),
        "train_rows": training.get("train_rows"),
        "validation_rows": training.get("validation_rows"),
        "loss_before": training.get("loss_before"),
        "loss_after": training.get("loss_after"),
        "action_distribution": training.get("action_distribution"),
        "trusted_rows_loaded": trusted_rows_loaded,
        "trusted_replay_rows_loaded": int(first_number(nested.get("trusted_replay_rows_loaded"))),
        "feedback_rows_entered_batch": feedback_rows_entered_batch,
        "optimizer_steps_this_cycle": optimizer_steps_this_cycle,
        "optimizer_steps_last_hour": int(first_number(nested.get("optimizer_steps_last_hour"))),
        "optimizer_steps_total": optimizer_steps_total,
        "parameter_hash_before": parameter_hash_before,
        "parameter_hash_after": parameter_hash_after,
        "parameter_hash_changed": bool(parameter_hash_before and parameter_hash_after and parameter_hash_before != parameter_hash_after),
        "weight_delta_norm": weight_delta_norm,
        "checkpoint_weight_blob_written": checkpoint_weight_blob_written,
        "checkpoint_path": checkpoint_path,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_reload_verified": checkpoint_reload_verified,
        "last_successful_weight_update_at": first_present(
            nested.get("last_successful_weight_update_at"),
            training.get("last_successful_weight_update_at"),
        ),
        "learning_update_lane": nested.get("learning_update_lane"),
        "online_learning_status": nested.get("online_learning_status"),
        "effective_trainer_mode": nested.get("effective_trainer_mode"),
        "outcome_supervised_update_used": nested.get("outcome_supervised_update_used"),
        "ppo_objective_used": nested.get("ppo_objective_used"),
        "uses_expected_move_as_realized_reward": nested.get("uses_expected_move_as_realized_reward"),
        "rows_rejected_by_reason": as_dict(nested.get("rows_rejected_by_reason")),
        "prediction_count": int(first_number(metrics_payload.get("prediction_count"))),
        "checkpoint_id": first_present(
            checkpoint.get("checkpoint_id"),
            checkpoint_reload.get("checkpoint_id"),
            checkpoint_load.get("checkpoint_id"),
        ),
        "checkpoint_manifest_path": checkpoint.get("checkpoint_manifest_path"),
        "checkpoint_load": checkpoint_load,
        "checkpoint_reload": checkpoint_reload,
    }


def _resolve_repo_path(repo_root: Path, path_value: Any) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    if path.is_absolute():
        return path
    return repo_root / path


def _relative_path(repo_root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path_for_weight(path: Path | None) -> Path | None:
    if path is None:
        return None
    text = str(path)
    if text.endswith(".weights.npz"):
        return Path(text[: -len(".weights.npz")] + ".json")
    return path.with_suffix(".json")


def _load_json_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    try:
        return as_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _checkpoint_file_summary(repo_root: Path, weight_path_value: Any) -> dict[str, Any]:
    weight_path = _resolve_repo_path(repo_root, weight_path_value)
    manifest_path = _manifest_path_for_weight(weight_path)
    manifest = _load_json_file(manifest_path)
    stat = weight_path.stat() if weight_path is not None and weight_path.exists() else None
    return {
        "checkpoint_id": manifest.get("checkpoint_id"),
        "weight_file": _relative_path(repo_root, weight_path),
        "weight_file_exists": bool(stat),
        "weight_file_size_bytes": int(stat.st_size) if stat else None,
        "weight_file_mtime": stat.st_mtime if stat else None,
        "sha256": _sha256_file(weight_path),
        "manifest_path": _relative_path(repo_root, manifest_path),
        "manifest_generated_utc": manifest.get("generated_utc"),
        "manifest_weight_file_size_bytes": manifest.get("weight_file_size_bytes"),
        "manifest_weight_blob_written": manifest.get("weight_blob_written"),
        "manifest_external_deserialization_used": manifest.get("external_deserialization_used"),
        "manifest_torch_pickle_load_used": manifest.get("torch_pickle_load_used"),
    }


def _previous_checkpoint_summary(repo_root: Path, current_weight_path_value: Any) -> dict[str, Any]:
    current = _resolve_repo_path(repo_root, current_weight_path_value)
    model_dir = repo_root / ".local_models/v2_native_rl_masa_ppo"
    if not model_dir.exists():
        return {}
    candidates = sorted(
        (path for path in model_dir.glob("v2_hybrid_ckpt_*.weights.npz") if path.exists()),
        key=lambda path: path.stat().st_mtime,
    )
    if current is not None:
        current_resolved = current.resolve()
        before = [path for path in candidates if path.resolve() != current_resolved and path.stat().st_mtime <= current.stat().st_mtime]
    else:
        before = candidates[:-1]
    if not before:
        return {}
    return _checkpoint_file_summary(repo_root, before[-1])


def _published_prediction_sample(client: Any, current_checkpoint_id: Any) -> dict[str, Any]:
    if client is None or not current_checkpoint_id or not hasattr(client, "scan_iter"):
        return {}
    try:
        keys = list(client.scan_iter(match=SIGNAL_KEY_PATTERN, count=100))
    except TypeError:
        keys = list(client.scan_iter(SIGNAL_KEY_PATTERN))
    except Exception:  # noqa: BLE001 - diagnostic only
        return {}
    for key in sorted(str(item.decode("utf-8") if isinstance(item, bytes) else item) for item in keys):
        payload = _json_from_redis(client, key, {})
        if not isinstance(payload, Mapping):
            continue
        if payload.get("checkpoint_id") != current_checkpoint_id:
            continue
        return {
            "sample_key": key,
            "prediction_id": payload.get("prediction_id"),
            "checkpoint_id": payload.get("checkpoint_id"),
            "symbol": payload.get("symbol"),
            "timeframe": payload.get("timeframe"),
            "generated_at": first_present(payload.get("generated_at"), payload.get("generated_utc"), payload.get("generated_est")),
            "confidence_calibrated": payload.get("confidence_calibrated"),
            "selected_action": first_present(payload.get("selected_action"), payload.get("action")),
        }
    return {}


def build_a_plus_phase1_trainer_artifacts(
    *,
    redis_client: Any,
    repo_root: Path,
    generated_utc: str | None = None,
) -> dict[str, dict[str, Any]]:
    generated = generated_utc or utc_now()
    feedback_rows = _extract_rows(_json_from_redis(redis_client, FEEDBACK_KEY, []))
    quarantine_rows = _extract_rows(_json_from_redis(redis_client, FEEDBACK_QUARANTINE_KEY, []))
    closed_trade_rows = _extract_rows(_json_from_redis(redis_client, CLOSED_TRADES_KEY, []))
    metrics_payload = as_dict(_json_from_redis(redis_client, TRAINER_METRICS_KEY, {}))

    feedback = _feedback_contract_summary(feedback_rows)
    metrics = _trainer_metrics_summary(metrics_payload)
    checkpoint_after = _checkpoint_file_summary(repo_root, metrics.get("checkpoint_path"))
    checkpoint_before = _previous_checkpoint_summary(repo_root, metrics.get("checkpoint_path"))
    current_checkpoint_hash = checkpoint_after.get("sha256") or metrics.get("checkpoint_hash")
    previous_checkpoint_hash = checkpoint_before.get("sha256")
    checkpoint_hash_matches_metrics = bool(
        current_checkpoint_hash
        and metrics.get("checkpoint_hash")
        and current_checkpoint_hash == metrics.get("checkpoint_hash")
    )
    weights_updated = bool(
        metrics.get("optimizer_steps_this_cycle", 0) > 0
        and metrics.get("parameter_hash_changed")
        and float(metrics.get("weight_delta_norm") or 0.0) > 0.0
    )
    checkpoint_weight_blob_updated = bool(
        metrics.get("checkpoint_weight_blob_written")
        and metrics.get("checkpoint_reload_verified")
        and current_checkpoint_hash
        and (not previous_checkpoint_hash or current_checkpoint_hash != previous_checkpoint_hash)
    )
    published_prediction = _published_prediction_sample(redis_client, metrics.get("checkpoint_id"))
    predictions_published_under_current_checkpoint = bool(published_prediction)
    predictions_changed_after_feedback = bool(
        weights_updated
        and predictions_published_under_current_checkpoint
        and metrics.get("prediction_count", 0) > 0
    )

    diagnostic_conditions = {
        "consumable_feedback_rows_gt_0": feedback["consumable_feedback_rows"] > 0,
        "trusted_rows_loaded_gt_0": metrics["trusted_rows_loaded"] > 0,
        "weights_updated": weights_updated,
        "checkpoint_weight_blob_updated": checkpoint_weight_blob_updated,
    }
    missing_evidence = [name for name, passed in diagnostic_conditions.items() if not passed]
    base = {
        "goal_id": GOAL_ID,
        "generated_utc": generated,
        **_non_runtime_evidence_boundary(generated),
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "old_redis_writes": False,
    }

    trainer_feedback_consumption = {
        **base,
        "schema_version": "trainer_feedback_consumption_status_v3",
        "status": (
            "DIAGNOSTIC_FEEDBACK_CONTRACT_OBSERVED_NON_CANONICAL"
            if diagnostic_conditions["consumable_feedback_rows_gt_0"]
            else "DIAGNOSTIC_BLOCKED_NO_CONSUMABLE_FEEDBACK"
        ),
        **feedback,
        "source_feedback_key": FEEDBACK_KEY,
        "source_closed_trades_key": CLOSED_TRADES_KEY,
        "closed_trade_rows_seen": len(closed_trade_rows),
        "quarantine_key": FEEDBACK_QUARANTINE_KEY,
        "quarantine_rows": len(quarantine_rows),
        "quarantine_reason_counts": _quarantine_reason_counts(quarantine_rows),
        "quarantined_rows_excluded_from_training": True,
        "invalid_quarantined_rows_consumed": feedback["invalid_consumed_rows"] > 0,
        "trainer_consumable_contract": "trainer_consumable true + valid closed-trade status + complete Phase 1 fields",
    }
    trainer_weight_update_proof = {
        **base,
        "schema_version": "trainer_weight_update_proof_v3",
        "status": "WEIGHTS_UPDATED" if weights_updated else "BLOCKED_NO_WEIGHT_MUTATION_PROOF",
        "weights_updated": weights_updated,
        "weight_update_key_before": metrics.get("parameter_hash_before"),
        "weight_update_key_after": metrics.get("parameter_hash_after"),
        "parameter_hash_before": metrics.get("parameter_hash_before"),
        "parameter_hash_after": metrics.get("parameter_hash_after"),
        "parameter_hash_changed": metrics.get("parameter_hash_changed"),
        "weight_delta_norm": metrics.get("weight_delta_norm"),
        "optimizer_steps_this_cycle": metrics.get("optimizer_steps_this_cycle"),
        "optimizer_steps_last_hour": metrics.get("optimizer_steps_last_hour"),
        "optimizer_steps_total": metrics.get("optimizer_steps_total"),
        "trusted_rows_loaded": metrics.get("trusted_rows_loaded"),
        "feedback_rows_entered_batch": metrics.get("feedback_rows_entered_batch"),
        "learning_update_lane": metrics.get("learning_update_lane"),
        "outcome_supervised_update_used": metrics.get("outcome_supervised_update_used"),
        "ppo_objective_used": metrics.get("ppo_objective_used"),
        "uses_expected_move_as_realized_reward": metrics.get("uses_expected_move_as_realized_reward"),
        "loss_before": metrics.get("loss_before"),
        "loss_after": metrics.get("loss_after"),
        "last_successful_weight_update_at": metrics.get("last_successful_weight_update_at"),
        "rows_rejected_by_reason": metrics.get("rows_rejected_by_reason"),
    }
    trainer_checkpoint_update_proof = {
        **base,
        "schema_version": "trainer_checkpoint_update_proof_v3",
        "status": "CHECKPOINT_WEIGHT_BLOB_UPDATED" if checkpoint_weight_blob_updated else "BLOCKED_NO_CHECKPOINT_BLOB_UPDATE_PROOF",
        "checkpoint_weight_blob_updated": checkpoint_weight_blob_updated,
        "checkpoint_hash_matches_metrics": checkpoint_hash_matches_metrics,
        "checkpoint_reload_verified": metrics.get("checkpoint_reload_verified"),
        "checkpoint_weight_blob_written": metrics.get("checkpoint_weight_blob_written"),
        "checkpoint_before": checkpoint_before,
        "checkpoint_after": checkpoint_after,
        "checkpoint_hash_changed_against_previous": bool(
            current_checkpoint_hash
            and previous_checkpoint_hash
            and current_checkpoint_hash != previous_checkpoint_hash
        ),
        "current_checkpoint_hash": current_checkpoint_hash,
        "previous_checkpoint_hash": previous_checkpoint_hash,
        "predictions_published_under_current_checkpoint": predictions_published_under_current_checkpoint,
        "predictions_changed_after_feedback": predictions_changed_after_feedback,
        "prediction_change_evidence_status": (
            "DERIVED_FROM_PARAMETER_HASH_CHANGE_AND_CURRENT_CHECKPOINT_PUBLICATION"
            if predictions_changed_after_feedback
            else "BLOCKED_NO_CURRENT_CHECKPOINT_SIGNAL_SAMPLE"
        ),
        "published_prediction_sample": published_prediction,
        "prediction_count": metrics.get("prediction_count"),
        "last_successful_weight_update_at": metrics.get("last_successful_weight_update_at"),
    }
    trainer_online_learning_repair_status = {
        **base,
        "schema_version": "trainer_online_learning_repair_status_v3",
        "status": (
            DIAGNOSTIC_COMPLETE
            if all(diagnostic_conditions.values())
            else DIAGNOSTIC_INCOMPLETE
        ),
        "online_learning_status": metrics.get("online_learning_status"),
        "effective_trainer_mode": metrics.get("effective_trainer_mode"),
        "learning_update_lane": metrics.get("learning_update_lane"),
        "last_successful_weight_update_at": metrics.get("last_successful_weight_update_at"),
        "diagnostic_conditions": diagnostic_conditions,
        "missing_diagnostic_evidence": missing_evidence,
        "consumable_feedback_rows": feedback.get("consumable_feedback_rows"),
        "trusted_rows_loaded": metrics.get("trusted_rows_loaded"),
        "feedback_rows_entered_batch": metrics.get("feedback_rows_entered_batch"),
        "weights_updated": weights_updated,
        "checkpoint_weight_blob_updated": checkpoint_weight_blob_updated,
        "predictions_changed_after_feedback": predictions_changed_after_feedback,
        "training_status": metrics.get("training_status"),
        "training_steps": metrics.get("training_steps"),
        "train_rows": metrics.get("train_rows"),
        "validation_rows": metrics.get("validation_rows"),
        "action_distribution": metrics.get("action_distribution"),
        "required_field_coverage_complete": feedback.get("required_field_coverage_complete"),
        "quarantine_rows": len(quarantine_rows),
        "quarantined_rows_excluded_from_training": True,
        "raw_evidence_pointers": [
            f"redis:{FEEDBACK_KEY}",
            f"redis:{FEEDBACK_QUARANTINE_KEY}",
            f"redis:{TRAINER_METRICS_KEY}",
            str(checkpoint_after.get("weight_file") or ""),
        ],
    }

    return {
        "trainer_online_learning_repair_status.json": trainer_online_learning_repair_status,
        "trainer_feedback_consumption_status.json": trainer_feedback_consumption,
        "trainer_weight_update_proof.json": trainer_weight_update_proof,
        "trainer_checkpoint_update_proof.json": trainer_checkpoint_update_proof,
    }


def write_a_plus_phase1_trainer_artifacts(
    *,
    redis_client: Any,
    repo_root: Path,
    goal_dir: Path | None = None,
    public_dir: Path | None = None,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    artifacts = build_a_plus_phase1_trainer_artifacts(
        redis_client=redis_client,
        repo_root=repo_root,
        generated_utc=generated_utc,
    )
    destinations: list[Path] = [goal_dir or (repo_root / "goal_state" / GOAL_ID)]
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

    readiness = artifacts["trainer_online_learning_repair_status.json"]
    return {
        "goal_id": GOAL_ID,
        "status": readiness["status"],
        "diagnostic_conditions": readiness["diagnostic_conditions"],
        "missing_diagnostic_evidence": readiness["missing_diagnostic_evidence"],
        **_non_runtime_evidence_boundary(str(readiness["generated_utc"])),
        "written": written,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
    }
