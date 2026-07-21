"""Model Track M1 real-inference routeability gate.

Read-only gate for separating proof/default prediction artifacts from real
PPO/MASA inference candidates. It does not enable live trading, does not submit
orders, and does not lower confidence thresholds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - import shape differs between pytest and python -m
    from app.cli.run_paper_shadow_edge_report import (
        confidence_value,
        prediction_confidence_provenance,
    )
except ModuleNotFoundError:  # pragma: no cover
    from v2.backend.app.cli.run_paper_shadow_edge_report import (
        confidence_value,
        prediction_confidence_provenance,
    )

LIQUID_SYMBOLS = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "AVAXUSDT",
    "LTCUSDT",
)
TRAINER_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
TRAINER_HEARTBEAT_KEY = "v2:trainer:hybrid_cuda:heartbeat"
BATCH_RECEIPT_KEY = "v2:trainer:real_inference_paper_batch:receipt"
BATCH_RECEIPT_SCHEMA = "v2_real_inference_paper_batch_execution_receipt_v1"
M1_TEST_PATH = "v2/backend/tests/unit/cli/test_run_real_inference_paper_batch.py"
M1_TEST_NODE = "test_m1_executed_batch_receipt_contract"
CURRENT_CYCLE_ENVELOPE_SCHEMA = (
    "v2_native_trainer_current_cycle_learning_envelope_v1"
)
LIVE_CONTROL_KEYS = (
    "v2:live_gate:state",
    "v2:trader:execution_state",
    "v2:live_order_transport:status",
)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def strict_utc(value: Any) -> datetime | None:
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


def positive_ttl(client: Any, key: str) -> int | None:
    if client is None or not hasattr(client, "ttl"):
        return None
    try:
        ttl = int(client.ttl(key))
    except (OSError, TypeError, ValueError):
        return None
    return ttl if ttl > 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_real_inference_paper_batch")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--symbols", default=",".join(LIQUID_SYMBOLS))
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--max-predictions", type=int, default=50)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())

    if not args.paper_only or not args.no_live:
        report = blocked_report(
            symbols=symbols,
            reason="PAPER_ONLY_AND_NO_LIVE_FLAGS_REQUIRED",
            max_predictions=args.max_predictions,
        )
        write_outputs(output_dir, report)
        print(json.dumps(report["m1_release_gate"], indent=2, sort_keys=True, default=str))
        return 1

    client = redis_client(args.redis_url)
    report = build_m1_report(client=client, symbols=symbols, max_predictions=args.max_predictions)
    write_outputs(output_dir, report)
    print(json.dumps(report["m1_release_gate"], indent=2, sort_keys=True, default=str))
    return 0 if report["m1_release_gate"]["verdict"] == "M1 GO" else 1


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def build_m1_report(*, client: Any, symbols: tuple[str, ...], max_predictions: int) -> dict[str, Any]:
    observed_utc = utc_now()
    observed_at = strict_utc(observed_utc)
    if observed_at is None:  # pragma: no cover - utc_now is strict by construction
        raise RuntimeError("m1_observation_clock_invalid")
    predictions = scan_json(client, "v2:prediction:*", limit=max_predictions * 10)
    proof_predictions = scan_json(client, "v2:proof:prediction:*", limit=max_predictions * 10)
    sidecar_predictions = scan_json(client, "v2:trainer:rl_core_prediction_sidecar:*", limit=max_predictions * 10)
    live_state = live_control_state(client)
    hybrid_status = read_json_key(client, TRAINER_STATUS_KEY)
    hybrid_heartbeat = read_json_key(client, TRAINER_HEARTBEAT_KEY)
    runtime_contract = current_runtime_contract(
        client=client,
        status=hybrid_status,
        heartbeat=hybrid_heartbeat,
        observed_at=observed_at,
    )
    checkpoint = checkpoint_status(client, hybrid_status=hybrid_status)

    confidence_counts = Counter(prediction_confidence_provenance(row) for row in predictions)
    candidate_rejections: Counter[str] = Counter()
    routeability_candidates: list[dict[str, Any]] = []
    for row in predictions:
        reasons = strict_routeability_rejection_reasons(
            row,
            runtime=runtime_contract,
            observed_at=observed_at,
        )
        if reasons:
            candidate_rejections.update(reasons)
        else:
            routeability_candidates.append(row)
    real_values = [confidence_value(row) for row in routeability_candidates]
    real_values = [value for value in real_values if value is not None]
    block_reasons = Counter()
    for row in predictions:
        if row in routeability_candidates:
            continue
        provenance = prediction_confidence_provenance(row)
        if provenance in {"PROOF_DEFAULT", "PLACEHOLDER"}:
            block_reasons["PLACEHOLDER_CONFIDENCE_BLOCK"] += 1
        elif provenance == "MISSING":
            block_reasons["MISSING_CONFIDENCE_BLOCK"] += 1
        elif provenance == "INFERRED":
            block_reasons["INFERRED_CONFIDENCE_NOT_ROUTEABLE"] += 1
        else:
            block_reasons["NOT_ROUTEABILITY_CANDIDATE"] += 1
    block_reasons.update(candidate_rejections)

    receipt_validation = batch_receipt_validation(
        client=client,
        candidates=routeability_candidates,
        runtime=runtime_contract,
        requested_symbols=symbols,
        observed_at=observed_at,
    )
    noncandidate_predictions = [
        row for row in predictions if row not in routeability_candidates
    ]
    placeholder_count = sum(
        1
        for row in noncandidate_predictions
        if prediction_confidence_provenance(row)
        in {"PROOF_DEFAULT", "PLACEHOLDER", "INFERRED"}
    )
    missing_count = sum(
        1
        for row in noncandidate_predictions
        if prediction_confidence_provenance(row) == "MISSING"
    )

    inventory = real_inference_producer_inventory(
        checkpoint=checkpoint,
        hybrid_status=hybrid_status,
        hybrid_heartbeat=hybrid_heartbeat,
        sidecar_count=len(sidecar_predictions),
        canonical_prediction_count=len(predictions),
    )
    root_cause = classify_root_cause(
        confidence_counts=confidence_counts,
        routeability_candidates=len(routeability_candidates),
        checkpoint=checkpoint,
        hybrid_status=hybrid_status,
        sidecar_count=len(sidecar_predictions),
    )
    gate = classify_m1_gate(
        real_model_count=len(routeability_candidates),
        placeholder_count=placeholder_count,
        missing_count=missing_count,
        live_state=live_state,
        root_cause=root_cause,
        runtime_contract=runtime_contract,
        batch_receipt=receipt_validation,
    )
    batch = {
        "generated_at": observed_utc,
        "symbols_requested": list(symbols),
        "max_predictions": max_predictions,
        "predictions_attempted": receipt_validation["predictions_attempted"],
        "predictions_attempted_semantics": (
            "ZERO_FOR_READ_ONLY_SCAN_UNLESS_EXACT_EXECUTION_RECEIPT_VALID"
        ),
        "predictions_emitted": len(routeability_candidates),
        "real_model_confidence_count": len(routeability_candidates),
        "placeholder_or_default_confidence_count": placeholder_count,
        "missing_confidence_count": missing_count,
        "confidence_distribution": distribution(real_values),
        "confidence_threshold": 0.66,
        "confidence_threshold_semantics": "LEGACY_TELEMETRY_ONLY_NOT_M1_ADMISSION",
        "predictions_above_threshold": sum(1 for value in real_values if value >= 0.66),
        "predictions_below_threshold": sum(1 for value in real_values if value < 0.66),
        "routeability_candidates": len(routeability_candidates),
        "accepted_paper_intents": 0,
        "accepted_shadow_intents": 0,
        "fills_created": 0,
        "positions_opened": 0,
        "closed_trades": 0,
        "block_reason_distribution": dict(sorted(block_reasons.items())),
        "proof_prediction_records": len(proof_predictions),
        "sidecar_prediction_records": len(sidecar_predictions),
        "canonical_prediction_records": len(predictions),
        "root_cause": root_cause,
        "live_control_state": live_state,
        "current_runtime_contract": runtime_contract,
        "batch_execution_receipt": receipt_validation,
    }
    return {
        "real_inference_producer_inventory": inventory,
        "real_inference_batch_report": batch,
        "m1_release_gate": gate,
    }


def blocked_report(*, symbols: tuple[str, ...], reason: str, max_predictions: int) -> dict[str, Any]:
    live_state = {
        "live_gate": "unknown",
        "order_transport_submit_enabled": None,
        "live_trading_enabled": None,
        "places_real_order": None,
        "exchange_action_taken": None,
        "any_live_submit_enabled": None,
        "evidence_complete": False,
    }
    gate = {
        "generated_at": utc_now(),
        "verdict": "M1 NO-GO",
        "reason": reason,
        "live_submit_disabled": False,
        "no_live_order_submitted": False,
        "real_model_confidence_count": 0,
        "placeholder_or_default_confidence_count": 0,
        "missing_confidence_count": 0,
        "routeability_candidates": 0,
    }
    return {
        "real_inference_producer_inventory": {"generated_at": utc_now(), "producers": real_inference_producer_rows()},
        "real_inference_batch_report": {
            "generated_at": utc_now(),
            "symbols_requested": list(symbols),
            "max_predictions": max_predictions,
            "predictions_attempted": 0,
            "predictions_emitted": 0,
            "root_cause": reason,
            "live_control_state": live_state,
        },
        "m1_release_gate": gate,
    }


def scan_json(client: Any, pattern: str, *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scan_truncated = False
    try:
        iterator = client.scan_iter(match=pattern, count=500)
    except Exception:
        return rows
    for key in iterator:
        if len(rows) >= limit:
            scan_truncated = True
            break
        payload = read_json_key(client, str(key))
        if payload:
            payload.setdefault("_key", str(key))
            payload["_redis_ttl_seconds"] = positive_ttl(client, str(key))
            rows.append(payload)
    for payload in rows:
        payload["_scan_truncated"] = scan_truncated
    return rows


def read_json_key(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def current_runtime_contract(
    *,
    client: Any,
    status: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    envelope = status.get("current_cycle_learning_envelope")
    envelope = dict(envelope) if isinstance(envelope, Mapping) else {}
    serving = status.get("current_cycle_verified_serving_checkpoint_evidence")
    serving = dict(serving) if isinstance(serving, Mapping) else {}
    cycle_id = str(envelope.get("cycle_id") or "")
    process_instance_id = str(envelope.get("process_instance_id") or "")
    checkpoint_id = str(envelope.get("checkpoint_id") or "")
    fingerprint = str(envelope.get("candidate_policy_fingerprint") or "")
    reasons: list[str] = []
    if not cycle_id or not process_instance_id or not checkpoint_id or len(fingerprint) != 64:
        reasons.append("CURRENT_RUNTIME_IDENTITY_INCOMPLETE")
    if envelope.get("schema_version") != CURRENT_CYCLE_ENVELOPE_SCHEMA:
        reasons.append("CURRENT_RUNTIME_ENVELOPE_SCHEMA_INVALID")
    for name, row in (("STATUS", status), ("HEARTBEAT", heartbeat)):
        if row.get("cycle_id") != cycle_id or row.get("process_instance_id") != process_instance_id:
            reasons.append(f"{name}_CURRENT_RUNTIME_IDENTITY_MISMATCH")
    if status.get("runtime_readiness_status") != "READY" or status.get("trainer_learning_ready") is not True:
        reasons.append("CURRENT_RUNTIME_NOT_READY")
    if status.get("status_publication_status") != "ACTIVE":
        reasons.append("CURRENT_RUNTIME_STATUS_PUBLICATION_NOT_ACTIVE")
    status_expires = strict_utc(status.get("status_payload_expires_at"))
    heartbeat_expires = strict_utc(heartbeat.get("expires_at"))
    envelope_generated = strict_utc(envelope.get("generated_utc"))
    heartbeat_generated = strict_utc(heartbeat.get("generated_utc"))
    if envelope_generated is None or envelope_generated > observed_at:
        reasons.append("CURRENT_RUNTIME_ENVELOPE_CLOCK_INVALID")
    if heartbeat_generated is None or heartbeat_generated > observed_at:
        reasons.append("CURRENT_RUNTIME_HEARTBEAT_CLOCK_INVALID")
    if status_expires is None or observed_at > status_expires:
        reasons.append("CURRENT_RUNTIME_STATUS_EXPIRED")
    if heartbeat_expires is None or observed_at > heartbeat_expires:
        reasons.append("CURRENT_RUNTIME_HEARTBEAT_EXPIRED")
    if positive_ttl(client, TRAINER_STATUS_KEY) is None:
        reasons.append("CURRENT_RUNTIME_STATUS_POSITIVE_TTL_UNPROVEN")
    if positive_ttl(client, TRAINER_HEARTBEAT_KEY) is None:
        reasons.append("CURRENT_RUNTIME_HEARTBEAT_POSITIVE_TTL_UNPROVEN")
    if (
        serving.get("checkpoint_artifact_verified") is not True
        or serving.get("causal_order_verified") is not True
        or serving.get("exact_optimizer_contract_durable") is not True
        or serving.get("manager_semantic_verification_recomputed_this_cycle") is not True
        or serving.get("checkpoint_id") != checkpoint_id
        or serving.get("model_parameter_fingerprint") != fingerprint
    ):
        reasons.append("CURRENT_VERIFIED_SERVING_CHECKPOINT_INVALID")
    return {
        "valid": not reasons,
        "cycle_id": cycle_id or None,
        "process_instance_id": process_instance_id or None,
        "checkpoint_id": checkpoint_id or None,
        "candidate_policy_fingerprint": fingerprint or None,
        "rejection_reasons": list(dict.fromkeys(reasons)),
    }


def strict_routeability_rejection_reasons(
    row: Mapping[str, Any],
    *,
    runtime: Mapping[str, Any],
    observed_at: datetime,
) -> list[str]:
    reasons: list[str] = []
    confidence_source = str(row.get("confidence_source") or "").upper()
    if confidence_source not in {
        "REAL_MODEL",
        "CHECKPOINT_BOUND_PER_ACTION_PROFITABILITY_MODEL",
    }:
        reasons.append("REAL_MODEL_PROVENANCE_UNVERIFIED")
    confidence = confidence_value(row)
    if confidence is None or not math.isfinite(confidence) or not 0.0 < confidence <= 1.0:
        reasons.append("CALIBRATED_CONFIDENCE_INVALID")
    if row.get("confidence_calibration_fitted") is not True:
        reasons.append("CONFIDENCE_CALIBRATION_NOT_FITTED")
    for field in ("model_consumable", "paper_intent_consumable", "routeability_candidate"):
        if row.get(field) is not True:
            reasons.append(f"{field.upper()}_NOT_EXPLICIT_TRUE")
    if row.get("proof_only") is not False:
        reasons.append("PROOF_ONLY_NOT_EXPLICIT_FALSE")
    if (
        row.get("live_gate") != "blocked_human_only"
        or row.get("live_symbols") != []
        or row.get("exchange_mutation") is not False
        or row.get("trainer_direct_trading") is not False
    ):
        reasons.append("NON_LIVE_SAFETY_CONTRACT_INVALID")
    for field in ("cycle_id", "process_instance_id", "checkpoint_id", "candidate_policy_fingerprint"):
        if row.get(field) != runtime.get(field):
            reasons.append(f"CURRENT_RUNTIME_{field.upper()}_MISMATCH")
    feature_cutoff = strict_utc(row.get("feature_cutoff"))
    available_at = strict_utc(row.get("available_at"))
    decision_time = strict_utc(row.get("decision_time"))
    generated_at = strict_utc(row.get("generated_at"))
    masa_cutoff = strict_utc(row.get("masa_feature_cutoff"))
    ppo_cutoff = strict_utc(row.get("ppo_feature_cutoff"))
    if (
        feature_cutoff is None
        or available_at is None
        or decision_time is None
        or generated_at is None
        or masa_cutoff is None
        or ppo_cutoff is None
        or feature_cutoff > decision_time
        or available_at > decision_time
        or masa_cutoff > decision_time
        or ppo_cutoff > decision_time
        or decision_time > generated_at
        or generated_at > observed_at
    ):
        reasons.append("PIT_CLOCK_CONTRACT_INVALID")
    if row.get("candle_closed_confirmed") is not True:
        reasons.append("FINAL_CANDLE_EVIDENCE_MISSING")
    if not isinstance(row.get("source_hashes"), Mapping) or not row.get("source_hashes"):
        reasons.append("SOURCE_HASH_LINEAGE_MISSING")
    trust = row.get("trust_gate_result")
    if not isinstance(trust, Mapping) or trust.get("allowed") is not True:
        reasons.append("TRUST_GATE_NOT_ALLOWED")
    if (
        row.get("replay_snapshot_write_success") is not True
        or row.get("replay_snapshot_readback_verified") is not True
    ):
        reasons.append("REPLAY_SNAPSHOT_EXACT_PUBLICATION_UNVERIFIED")
    if not isinstance(row.get("_redis_ttl_seconds"), int) or int(row.get("_redis_ttl_seconds") or 0) <= 0:
        reasons.append("PREDICTION_POSITIVE_TTL_UNPROVEN")
    if row.get("_scan_truncated") is True:
        reasons.append("PREDICTION_NAMESPACE_SCAN_TRUNCATED")
    return list(dict.fromkeys(reasons))


def _receipt_output_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                key: value
                for key, value in row.items()
                if key not in {"_key", "_redis_ttl_seconds", "_scan_truncated"}
            }
            for row in rows
        ],
        key=lambda row: str(row.get("prediction_id") or ""),
    )


def batch_receipt_validation(
    *,
    client: Any,
    candidates: list[dict[str, Any]],
    runtime: Mapping[str, Any],
    requested_symbols: tuple[str, ...],
    observed_at: datetime,
) -> dict[str, Any]:
    receipt = read_json_key(client, BATCH_RECEIPT_KEY)
    reasons: list[str] = []
    completed = strict_utc(receipt.get("completed_at"))
    expires = strict_utc(receipt.get("expires_at"))
    run_id = str(receipt.get("run_id") or "")
    candidate_ids = sorted(str(row.get("prediction_id") or "") for row in candidates)
    output_hash = canonical_sha256(_receipt_output_rows(candidates))
    repo_root = Path(__file__).resolve().parents[4]
    try:
        production_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        test_hash = hashlib.sha256((repo_root / M1_TEST_PATH).read_bytes()).hexdigest()
    except OSError:
        production_hash = ""
        test_hash = ""
    if receipt.get("schema_version") != BATCH_RECEIPT_SCHEMA:
        reasons.append("BATCH_EXECUTION_RECEIPT_SCHEMA_INVALID")
    if not run_id or any(row.get("batch_run_id") != run_id for row in candidates):
        reasons.append("BATCH_EXECUTION_RECEIPT_RUN_ID_MISMATCH")
    if completed is None or expires is None or not (completed <= observed_at <= expires):
        reasons.append("BATCH_EXECUTION_RECEIPT_NOT_CURRENT")
    for field in ("cycle_id", "process_instance_id", "checkpoint_id", "candidate_policy_fingerprint"):
        if receipt.get(field) != runtime.get(field):
            reasons.append(f"BATCH_EXECUTION_RECEIPT_{field.upper()}_MISMATCH")
    if receipt.get("safe_paper_execution_path_invoked") is not True:
        reasons.append("SAFE_PAPER_EXECUTION_PATH_NOT_INVOKED")
    if receipt.get("paper_only") is not True or receipt.get("routes_to_live") is not False:
        reasons.append("BATCH_EXECUTION_RECEIPT_NON_LIVE_CONTRACT_INVALID")
    if receipt.get("outcome") != "PASSED" or receipt.get("exit_code") != 0:
        reasons.append("BATCH_EXECUTION_RECEIPT_NOT_PASSED")
    runner_command = str(receipt.get("runner_command") or "")
    runner_command_sha256 = hashlib.sha256(runner_command.encode("utf-8")).hexdigest()
    if (
        not runner_command
        or receipt.get("runner_command_sha256") != runner_command_sha256
    ):
        reasons.append("BATCH_EXECUTION_RECEIPT_COMMAND_HASH_INVALID")
    if receipt.get("pytest_nodeid") != f"{M1_TEST_PATH}::{M1_TEST_NODE}":
        reasons.append("BATCH_EXECUTION_RECEIPT_NODE_MISMATCH")
    if receipt.get("production_source_sha256") != production_hash or not production_hash:
        reasons.append("BATCH_EXECUTION_RECEIPT_PRODUCTION_SOURCE_MISMATCH")
    if receipt.get("test_source_sha256") != test_hash or not test_hash:
        reasons.append("BATCH_EXECUTION_RECEIPT_TEST_SOURCE_MISMATCH")
    if receipt.get("prediction_ids") != candidate_ids or receipt.get("prediction_output_sha256") != output_hash:
        reasons.append("BATCH_EXECUTION_RECEIPT_OUTPUT_MISMATCH")
    if sorted(receipt.get("symbols_requested") or []) != sorted(requested_symbols):
        reasons.append("BATCH_EXECUTION_RECEIPT_SYMBOL_SET_MISMATCH")
    if sorted({str(row.get("symbol") or "") for row in candidates}) != sorted(requested_symbols):
        reasons.append("CURRENT_CANDIDATE_SYMBOL_SET_MISMATCH")
    if not isinstance(receipt.get("predictions_attempted"), int) or receipt.get("predictions_attempted") <= 0:
        reasons.append("BATCH_EXECUTION_ATTEMPT_COUNT_INVALID")
    unsigned = dict(receipt)
    claimed_hash = str(unsigned.pop("receipt_sha256", ""))
    try:
        actual_hash = canonical_sha256(unsigned)
    except (TypeError, ValueError):
        actual_hash = ""
    if not claimed_hash or claimed_hash != actual_hash:
        reasons.append("BATCH_EXECUTION_RECEIPT_HASH_INVALID")
    if positive_ttl(client, BATCH_RECEIPT_KEY) is None:
        reasons.append("BATCH_EXECUTION_RECEIPT_POSITIVE_TTL_UNPROVEN")
    return {
        "valid": not reasons,
        "run_id": run_id or None,
        "predictions_attempted": receipt.get("predictions_attempted") if not reasons else 0,
        "prediction_output_sha256": output_hash,
        "production_source_sha256": production_hash or None,
        "test_source_sha256": test_hash or None,
        "rejection_reasons": list(dict.fromkeys(reasons)),
    }


def live_control_state(client: Any) -> dict[str, Any]:
    state = {
        "live_gate": None,
        "order_transport_submit_enabled": None,
        "live_trading_enabled": None,
        "places_real_order": None,
        "exchange_action_taken": None,
        "any_live_submit_enabled": None,
    }
    keys_present: list[str] = []
    ttl_valid: list[str] = []
    for key in LIVE_CONTROL_KEYS:
        payload = read_json_key(client, key)
        if payload:
            keys_present.append(key)
        if positive_ttl(client, key) is not None:
            ttl_valid.append(key)
        for field in ("live_gate", "order_transport_submit_enabled", "live_trading_enabled", "places_real_order", "exchange_action_taken"):
            if field in payload:
                state[field] = payload[field]
        if any(payload.get(field) is True for field in ("order_transport_submit_enabled", "live_trading_enabled", "places_real_order", "exchange_action_taken")):
            state["any_live_submit_enabled"] = True
    explicit_safe = bool(
        state["live_gate"] == "blocked_human_only"
        and all(
            state[field] is False
            for field in (
                "order_transport_submit_enabled",
                "live_trading_enabled",
                "places_real_order",
                "exchange_action_taken",
            )
        )
    )
    state["keys_present"] = keys_present
    state["positive_ttl_keys"] = ttl_valid
    state["evidence_complete"] = bool(
        explicit_safe
        and set(keys_present) == set(LIVE_CONTROL_KEYS)
        and set(ttl_valid) == set(LIVE_CONTROL_KEYS)
    )
    if state["any_live_submit_enabled"] is not True:
        state["any_live_submit_enabled"] = False if state["evidence_complete"] else None
    return state


def checkpoint_status(
    client: Any,
    *,
    hybrid_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = read_json_key(client, "v2:trainer:checkpoint:evidence")
    status = dict(hybrid_status or {})
    serving = status.get("current_cycle_verified_serving_checkpoint_evidence")
    serving = dict(serving) if isinstance(serving, Mapping) else {}
    canonical = bool(
        serving.get("checkpoint_artifact_verified") is True
        and serving.get("causal_order_verified") is True
        and serving.get("exact_optimizer_contract_durable") is True
        and serving.get("manager_semantic_verification_recomputed_this_cycle") is True
        and serving.get("checkpoint_id")
        and serving.get("model_parameter_fingerprint")
    )
    return {
        "redis_checkpoint_evidence_present": bool(evidence),
        "redis_checkpoint_evidence": evidence,
        "legacy_metadata_evidence_counts_as_m1": False,
        "current_cycle_verified_serving_evidence": serving,
        "checkpoint_available_for_m1": canonical,
        "checkpoint_weight_status": (
            "CURRENT_CYCLE_VERIFIED_SERVING"
            if canonical
            else "CURRENT_CYCLE_VERIFIED_SERVING_EVIDENCE_MISSING"
        ),
    }


def real_inference_producer_inventory(
    *,
    checkpoint: Mapping[str, Any],
    hybrid_status: Mapping[str, Any],
    hybrid_heartbeat: Mapping[str, Any],
    sidecar_count: int,
    canonical_prediction_count: int,
) -> dict[str, Any]:
    rows = real_inference_producer_rows()
    for row in rows:
        if row["file_path"] == "v2/backend/app/cli/v2_rl_core_inference_loop.py":
            row["current_blocker"] = "writes sidecar namespace only; checkpoint status: " + str(checkpoint.get("checkpoint_weight_status"))
            row["current_sidecar_records"] = sidecar_count
        elif row["file_path"] == "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py":
            row["current_blocker"] = "no active REAL_MODEL canonical predictions observed" if canonical_prediction_count else "no canonical predictions observed"
            row["runtime_status_present"] = bool(hybrid_status)
            row["runtime_heartbeat_present"] = bool(hybrid_heartbeat)
    return {
        "generated_at": utc_now(),
        "checkpoint": dict(checkpoint),
        "producers": rows,
    }


def real_inference_producer_rows() -> list[dict[str, Any]]:
    return [
        producer_row(
            "v2/backend/app/cli/v2_rl_core_inference_loop.py",
            "run_once",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated", "policy_action_probabilities"),
            confidence_scale="0-1 probability",
            replay=False,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="sidecar_only_checkpoint_weight_required",
        ),
        producer_row(
            "v2/backend/app/cli/v2_rl_core_worker.py",
            "main",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated"),
            confidence_scale="0-1 probability",
            replay=False,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="status_worker_not_canonical_prediction_writer",
        ),
        producer_row(
            "v2/backend/app/services/rl_core/masa_adapter.py",
            "V2MASAAdapter.get_action_and_value",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence", "action_probabilities"),
            confidence_scale="0-1 probability",
            replay=True,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="adapter_output_not_canonical_prediction_writer_and_no_trained_checkpoint",
        ),
        producer_row(
            "v2/backend/app/services/rl_core/trainer_output.py",
            "emit_trainer_output",
            reads_trusted_market_state=True,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated"),
            confidence_scale="0-1 probability",
            replay=False,
            mtf=False,
            real_source=False,
            proof_confidence=False,
            routeable_namespace=False,
            paper_only=True,
            blocker="trainer_output_record_not_routeable_prediction",
        ),
        producer_row(
            "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py",
            "run_hybrid_trainer_cycle",
            reads_trusted_market_state=True,
            loads_ppo=True,
            loads_masa=True,
            produces_confidence=True,
            confidence_fields=("confidence_raw", "confidence_calibrated", "confidence_source"),
            confidence_scale="0-1 probability",
            replay=True,
            mtf=True,
            real_source=True,
            proof_confidence=False,
            routeable_namespace=True,
            paper_only=True,
            blocker="not_running_or_no_current_REAL_MODEL_canonical_predictions",
        ),
        producer_row(
            "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py",
            "V2HybridPredictionPublisher.publish_prediction",
            reads_trusted_market_state=False,
            loads_ppo=False,
            loads_masa=False,
            produces_confidence=False,
            confidence_fields=("passes_through_payload",),
            confidence_scale="payload_defined",
            replay=True,
            mtf=True,
            real_source=False,
            proof_confidence=True,
            routeable_namespace=True,
            paper_only=True,
            blocker="publisher_transport_depends_on_upstream_REAL_MODEL_payload",
        ),
    ]


def producer_row(
    file_path: str,
    function: str,
    *,
    reads_trusted_market_state: bool,
    loads_ppo: bool,
    loads_masa: bool,
    produces_confidence: bool,
    confidence_fields: tuple[str, ...],
    confidence_scale: str,
    replay: bool,
    mtf: bool,
    real_source: bool,
    proof_confidence: bool,
    routeable_namespace: bool,
    paper_only: bool,
    blocker: str,
) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "function_or_class": function,
        "reads_trusted_market_state": reads_trusted_market_state,
        "loads_ppo_policy_or_checkpoint": loads_ppo,
        "loads_masa_model_or_checkpoint": loads_masa,
        "produces_real_model_confidence": real_source and produces_confidence,
        "confidence_field_names": list(confidence_fields),
        "confidence_scale": confidence_scale,
        "writes_replay_snapshot_id": replay,
        "writes_mtf_snapshot_id": mtf,
        "writes_confidence_source_REAL_MODEL": real_source,
        "writes_proof_or_default_confidence": proof_confidence,
        "writes_to_routeable_namespace": routeable_namespace,
        "can_run_paper_only_no_live": paper_only,
        "current_blocker": blocker,
    }


def classify_root_cause(
    *,
    confidence_counts: Counter[str],
    routeability_candidates: int,
    checkpoint: Mapping[str, Any],
    hybrid_status: Mapping[str, Any],
    sidecar_count: int,
) -> str:
    if routeability_candidates > 0:
        return "REAL_INFERENCE_ROUTEABILITY_CANDIDATES_PRESENT"
    if confidence_counts.get("PROOF_DEFAULT", 0) or confidence_counts.get("PLACEHOLDER", 0):
        return "PREDICTION_WRITER_ONLY_PROOF_PUBLISHER_FOR_CURRENT_CANONICAL_KEYS"
    if sidecar_count:
        return "REAL_INFERENCE_WRITES_SIDECAR_NAMESPACE_NOT_EXPORTED_AS_ROUTEABLE"
    if not checkpoint.get("checkpoint_available_for_m1"):
        return "MODEL_CHECKPOINT_UNAVAILABLE"
    if not hybrid_status:
        return "REAL_INFERENCE_WORKER_NOT_RUNNING"
    return "REAL_INFERENCE_PATH_UNAVAILABLE"


def classify_m1_gate(
    *,
    real_model_count: int,
    placeholder_count: int,
    missing_count: int,
    live_state: Mapping[str, Any],
    root_cause: str,
    runtime_contract: Mapping[str, Any],
    batch_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    live_disabled = bool(
        live_state.get("evidence_complete") is True
        and live_state.get("any_live_submit_enabled") is False
    )
    no_live_order = bool(
        live_state.get("evidence_complete") is True
        and live_state.get("places_real_order") is False
        and live_state.get("exchange_action_taken") is False
    )
    if not live_disabled or not no_live_order:
        verdict = "M1 NO-GO"
        reason = "EXPLICIT_CURRENT_LIVE_DISABLE_EVIDENCE_MISSING_OR_UNSAFE"
    elif runtime_contract.get("valid") is not True:
        verdict = "M1 NO-GO"
        reason = "CURRENT_RUNTIME_CONTRACT_INVALID"
    elif real_model_count <= 0:
        verdict = "M1 NO-GO"
        reason = root_cause
    elif placeholder_count > 0:
        verdict = "M1 NO-GO"
        reason = "PLACEHOLDER_DEFAULT_CONFIDENCE_PRESENT_OUTSIDE_ROUTEABILITY"
    elif batch_receipt.get("valid") is not True:
        verdict = "M1 NO-GO"
        reason = "EXECUTED_CURRENT_BATCH_RECEIPT_INVALID_OR_MISSING"
    else:
        verdict = "M1 GO"
        reason = "CURRENT_RECEIPTED_REAL_MODEL_PAPER_BATCH_PRESENT"
    return {
        "generated_at": utc_now(),
        "verdict": verdict,
        "reason": reason,
        "real_model_confidence_count": real_model_count,
        "placeholder_or_default_confidence_count": placeholder_count,
        "missing_confidence_count": missing_count,
        "routeability_candidates": real_model_count,
        "live_submit_disabled": live_disabled,
        "no_live_order_submitted": no_live_order,
        "current_runtime_contract_valid": runtime_contract.get("valid") is True,
        "executed_batch_receipt_valid": batch_receipt.get("valid") is True,
        "batch_receipt_rejection_reasons": list(
            batch_receipt.get("rejection_reasons") or []
        ),
    }


def distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "max": None}
    values = sorted(values)
    return {
        "min": values[0],
        "p25": percentile(values, 0.25),
        "median": percentile(values, 0.5),
        "p75": percentile(values, 0.75),
        "max": values[-1],
    }


def percentile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def write_outputs(output_dir: Path, report: Mapping[str, Any]) -> None:
    write_json(output_dir / "real_inference_producer_inventory.json", report["real_inference_producer_inventory"])
    write_json(output_dir / "real_inference_batch_report.json", report["real_inference_batch_report"])
    write_json(output_dir / "m1_release_gate.json", report["m1_release_gate"])
    (output_dir / "real_inference_producer_inventory.md").write_text(
        render_inventory_markdown(report["real_inference_producer_inventory"]),
        encoding="utf-8",
    )
    (output_dir / "real_inference_batch_report.md").write_text(
        render_batch_markdown(report["real_inference_batch_report"], report["m1_release_gate"]),
        encoding="utf-8",
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def render_inventory_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Real Inference Producer Inventory",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        "| File | Function/class | Trusted state | PPO | MASA | Real confidence | Routeable namespace | Current blocker |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("producers", []):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| "
            + " | ".join(
                str(row.get(field, ""))
                for field in (
                    "file_path",
                    "function_or_class",
                    "reads_trusted_market_state",
                    "loads_ppo_policy_or_checkpoint",
                    "loads_masa_model_or_checkpoint",
                    "produces_real_model_confidence",
                    "writes_to_routeable_namespace",
                    "current_blocker",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_batch_markdown(report: Mapping[str, Any], gate: Mapping[str, Any]) -> str:
    fields = (
        "predictions_attempted",
        "predictions_emitted",
        "real_model_confidence_count",
        "placeholder_or_default_confidence_count",
        "missing_confidence_count",
        "routeability_candidates",
        "accepted_paper_intents",
        "accepted_shadow_intents",
        "fills_created",
        "positions_opened",
        "closed_trades",
        "root_cause",
    )
    lines = [
        "# M1 Real Inference Paper Batch Report",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        f"Verdict: `{gate.get('verdict')}`",
        f"Reason: `{gate.get('reason')}`",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in fields:
        lines.append(f"| `{field}` | `{report.get(field)}` |")
    return "\n".join(lines) + "\n"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
