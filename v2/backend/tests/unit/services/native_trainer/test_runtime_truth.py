from __future__ import annotations

import json
import socket
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import runtime_truth as rt
from v2.backend.app.services.native_trainer.learning_readiness import (
    CURRENT_CYCLE_ENVELOPE_SCHEMA,
    build_learning_readiness,
)
from v2.backend.app.services.native_trainer.runtime_truth import (
    ALL_TF_STATUS_REL,
    LIVE_GATE_REL,
    PAPER_TRIAL_REL,
    PARITY_REL,
    PORTFOLIO_REL,
    PREDICTION_STATUS_REL,
    RUNTIME_PAGES_REL,
    RUNTIME_TRUTH_REL,
    NativeTrainerRuntimePaths,
    build_native_trainer_runtime_payloads,
    build_semantic_validation,
    build_signals_status,
)


def test_semantic_validation_rejects_old_model_state_contradictions() -> None:
    runtime = {
        "payload_age_seconds": 0,
        "live_gate": "enabled_operator_approved",
        "paper_current_session_equity": 10030.0,
        "required_missing_parity_methods": 0,
        "training_steps_total": 2,
        "training_steps_last_hour": 0,
        "prediction_grid_rows": 665,
        "valid_symbol_count": 133,
        "timeframes": ["1m", "5m", "15m", "1h", "4h"],
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
    }
    status = build_semantic_validation(runtime, {"prediction_rows": []})

    failed = {row["assertion"] for row in status["failed_assertions"]}
    assert "training_steps_2_allowed_only_if_current_runtime_heartbeat_confirms" in failed


def test_signals_status_uses_readable_block_reasons() -> None:
    runtime = {"paper_threshold_trial": {"trial_promoted_signals": 3}, "rl_core_sidecar_rows": 1}
    prediction_payload = {
        "prediction_rows": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "selected_action": "long",
                "paper_fill_allowed": False,
                "paper_fill_gate_block_reasons": ["record_deny", "confidence_below_threshold"],
            }
        ]
    }

    status = build_signals_status(runtime, prediction_payload)

    row = status["sample_rows"][0]
    assert "risk or ledger denied this row" in row["readable_block_reasons"]
    assert "confidence below current paper threshold" in row["readable_block_reasons"]


def test_unbound_legacy_training_metrics_cannot_publish_learning_ready() -> None:
    fields = rt.online_learning_runtime_fields(
        training={
            "status": "TRAINED",
            "metrics": {
                "trusted_rows_loaded": 3,
                "trusted_replay_rows_loaded": 3,
                "optimizer_steps_this_cycle": 2,
                "optimizer_steps_last_hour": 2,
                "optimizer_steps_total": 7,
                "rows_rejected_by_reason": {"future_available_at": 1},
                "parameter_hash_before": "before",
                "parameter_hash_after": "after",
                "weight_delta_norm": 0.25,
                "loss_before": 1.5,
                "loss_after": 0.7,
                "checkpoint_weight_blob_written": True,
                "checkpoint_path": "/tmp/unit-checkpoint.pt",
                "checkpoint_hash": "checkpoint-sha256",
                "checkpoint_reload_verified": True,
                "last_successful_weight_update_at": "2026-06-22T04:00:00Z",
            },
        },
        prediction_rows=10,
    )

    assert fields["online_learning_status"] == (
        "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
    )
    assert fields["effective_trainer_mode"] == "INFERENCE_ONLY"
    assert fields["trainer_learning_ready"] is False
    assert fields["optimizer_steps_total"] == 0
    assert fields["rows_rejected_by_reason"] == {"future_available_at": 1}
    assert fields["loss_before"] == 1.5
    assert fields["loss_after"] == 0.7
    assert fields["checkpoint_path"] is None
    assert fields["checkpoint_hash"] is None
    assert "schema_version" not in fields
    assert fields["trainer_process_status"] == "INACTIVE"
    assert fields["cuda_inference_status"] == (
        "BLOCKED_NO_CURRENT_CUDA_PROBE_EVIDENCE"
    )
    assert "current_cycle_learning_envelope_present" in fields[
        "readiness_blocking_reasons"
    ]
    assert fields["unbound_legacy_evidence_used_for_readiness"] is False


def test_stale_persistent_runtime_cannot_supply_checkpoint_evidence() -> None:
    fields = rt.online_learning_runtime_fields(
        training={
            "status": "TRAINING_NOT_RUN",
            "metrics": {
                "trusted_rows_loaded": 0,
                "optimizer_steps_this_cycle": 0,
                "checkpoint_weight_blob_written": False,
                "checkpoint_reload_verified": False,
            },
        },
        persistent_runtime={
            "checkpoint_path": "/tmp/persistent-checkpoint.pt",
            "checkpoint_hash": "persistent-sha256",
        },
        prediction_rows=10,
    )

    assert fields["online_learning_status"] == (
        "BLOCKED_NO_COHERENT_CURRENT_CYCLE_LEARNING_ENVELOPE"
    )
    assert fields["checkpoint_path"] is None
    assert fields["checkpoint_hash"] is None
    assert fields["unbound_legacy_evidence_used_for_readiness"] is False


def _write_json(root: Path, rel: Path, payload: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_minimal_runtime_sources(public: Path) -> None:
    _write_json(public, ALL_TF_STATUS_REL, {})
    _write_json(public, RUNTIME_TRUTH_REL, {})
    _write_json(public, RUNTIME_PAGES_REL, {})
    _write_json(public, PORTFOLIO_REL, {})
    _write_json(public, PAPER_TRIAL_REL, {})
    _write_json(public, PARITY_REL, {})
    _write_json(public, LIVE_GATE_REL, {})


def _patch_runtime_truth_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(rt, "connect_redis", lambda: None)
    monkeypatch.setattr(rt, "systemctl_show", lambda _unit: {})
    monkeypatch.setattr(rt, "gpu_status_from_nvidia_smi", lambda: {"available": False})
    monkeypatch.setattr(rt, "memory_status", lambda: {})
    monkeypatch.setattr(
        rt,
        "checkpoint_retention_status",
        lambda _repo, _checkpoint_id: {
            "checkpoint_count": 0,
            "checkpoint_total_size_gb": 0,
            "checkpoint_dir_size_bytes": 0,
            "checkpoint_rollover_limit_bytes": 0,
            "checkpoint_rollover_status": "CHECKPOINT_STATUS_PENDING",
        },
    )


def test_native_runtime_payload_keeps_full_scrollable_prediction_grid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public = tmp_path / "public"
    repo = tmp_path / "repo"
    rows = [
        {
            "prediction_id": f"prediction-{idx}",
            "symbol": f"SYM{idx:03d}USDT",
            "timeframe": "1m",
            "selected_action": "hold",
            "expected_move_after_cost_bps": 0.0,
            "confidence_calibrated": 0.5,
            "data_coverage_percent": 100.0,
            "missing_feature_count": 0,
            "stale_feature_count": 0,
            "paper_fill_allowed": False,
            "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
            "status": "PRESENT_CURRENT",
        }
        for idx in range(90)
    ]
    _write_json(
        public,
        PREDICTION_STATUS_REL,
        {
            "generated_est": "2026-06-14T12:00:00-04:00",
            "prediction_rows": rows,
            "prediction_rows_count": len(rows),
            "expected_prediction_count": len(rows),
            "current_prediction_count": len(rows),
            "missing_prediction_rows_count": 0,
            "stale_prediction_rows_count": 0,
            "publication_complete": True,
            "blocked_prediction_rows_count": 0,
        },
    )
    _write_minimal_runtime_sources(public)
    _patch_runtime_truth_side_effects(monkeypatch)

    payloads = build_native_trainer_runtime_payloads(
        NativeTrainerRuntimePaths(repo_root=repo, public_root=public)
    )
    runtime = payloads["native_trainer_runtime_status.json"]

    assert runtime["schema_version"] == "native_trainer_runtime_status_v1"
    assert runtime["predictions_by_symbol_count"] == 90
    assert runtime["predictions_by_symbol_display_scope"] == "FULL_SCROLLABLE_TRAINER_GRID"
    assert len(runtime["predictions_by_symbol"]) == 90
    assert runtime["predictions_by_symbol"][-1]["symbol"] == "SYM089USDT"
    assert runtime["prediction_grid_current"] is True
    assert runtime["current_prediction_count"] == 90
    assert runtime["missing_prediction_rows_count"] == 0
    assert runtime["stale_prediction_rows_count"] == 0
    assert runtime["go_no_go"] == rt.BLOCKED
    assert runtime["payload_age_seconds"] is None


def test_native_runtime_payload_marks_partial_prediction_grid_not_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public = tmp_path / "public"
    repo = tmp_path / "repo"
    rows = [
        {
            "prediction_id": f"prediction-{idx}",
            "symbol": f"SYM{idx:03d}USDT",
            "timeframe": "1m",
            "status": "PRESENT_CURRENT" if idx < 85 else "MISSING_TF_PREDICTION",
            "paper_fill_allowed": False,
            "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
        }
        for idx in range(90)
    ]
    _write_json(
        public,
        PREDICTION_STATUS_REL,
        {
            "generated_est": "2026-06-14T12:00:00-04:00",
            "prediction_rows": rows,
            "prediction_rows_count": len(rows),
            "expected_prediction_count": len(rows),
            "current_prediction_count": 85,
            "missing_prediction_rows_count": 5,
            "stale_prediction_rows_count": 0,
            "publication_complete": True,
            "coverage_status": "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS",
            "actionability_status": "PAPER_ACTIONABILITY_BLOCKED_BY_GATES",
            "missing_prediction_symbols": ["SYM085USDT"],
            "paper_actionability_allowed_rows_count": 0,
            "paper_actionability_blocked_rows_count": 85,
            "paper_actionability_block_reason_counts": {
                "confidence_below_threshold": 85,
                "data_coverage_below_threshold": 4,
            },
        },
    )
    _write_minimal_runtime_sources(public)
    _patch_runtime_truth_side_effects(monkeypatch)

    payloads = build_native_trainer_runtime_payloads(
        NativeTrainerRuntimePaths(repo_root=repo, public_root=public)
    )
    runtime = payloads["native_trainer_runtime_status.json"]

    assert runtime["prediction_grid_current"] is False
    assert runtime["current_prediction_count"] == 85
    assert runtime["missing_prediction_rows_count"] == 5
    assert runtime["stale_prediction_rows_count"] == 0
    assert runtime["non_current_prediction_rows_count"] == 5
    assert runtime["prediction_coverage_status"] == "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS"
    assert runtime["prediction_actionability_status"] == "PAPER_ACTIONABILITY_BLOCKED_BY_GATES"
    assert runtime["missing_prediction_symbols"] == ["SYM085USDT"]
    assert runtime["paper_actionability_allowed_rows_count"] == 0
    assert runtime["paper_actionability_blocked_rows_count"] == 85
    assert runtime["paper_actionability_block_reason_counts"] == {
        "confidence_below_threshold": 85,
        "data_coverage_below_threshold": 4,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coherent_readiness_evidence(
    now_utc: datetime | None = None,
) -> dict[str, object]:
    now = now_utc or datetime.now(tz=timezone.utc)
    cycle_id = "cycle-20260718-0001"
    process_instance_id = f"{socket.gethostname()}:4242"
    checkpoint_id = "v2_hybrid_ckpt_unit"
    parent_checkpoint_id = "v2_hybrid_ckpt_parent"
    parent_fingerprint = "a" * 64
    candidate_fingerprint = "b" * 64
    checkpoint_hash = "c" * 64
    prediction_rows = [
        {
            "prediction_id": f"prediction-{index}",
            "symbol": symbol,
            "timeframe": "1m",
            "status": "PRESENT_CURRENT",
            "cycle_id": cycle_id,
            "process_instance_id": process_instance_id,
            "checkpoint_id": checkpoint_id,
            "candidate_policy_fingerprint": candidate_fingerprint,
        }
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"))
    ]
    envelope = {
        "schema_version": CURRENT_CYCLE_ENVELOPE_SCHEMA,
        "generated_utc": _iso(now),
        "checkpoint_generated_utc": _iso(now),
        "expected_cycle_cadence_seconds": 60,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "trusted_rows_loaded": 4,
        "trusted_replay_rows_loaded": 2,
        "feedback_rows_entered_batch": 2,
        "optimizer_steps_this_cycle": 2,
        "optimizer_steps_last_hour": 2,
        "optimizer_steps_total": 9,
        "parameter_hash_before": parent_fingerprint,
        "parameter_hash_after": candidate_fingerprint,
        "parent_policy_fingerprint": parent_fingerprint,
        "candidate_policy_fingerprint": candidate_fingerprint,
        "weight_delta_norm": 0.25,
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": parent_checkpoint_id,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_path": ".local_models/unit.weights.npz",
        "checkpoint_weight_blob_written": True,
        "checkpoint_reload_verified": True,
        "verified_serving": True,
        "last_successful_weight_update_at": _iso(now),
        "exact_optimizer_contract": {
            "valid": True,
            "ppo_objective_used": True,
            "optimizer_parameter_fingerprints_bound": True,
            "ledger_disposition": "SERVING_PROMOTED",
            "checkpoint_id": checkpoint_id,
        },
        "ppo_ledger_integrity": {"integrity_verified": True},
        "receipt_archive_sync_status": {
            "archive_sync_integrity_verified": True,
            "unsynced_terminal_attempts": 0,
            "sync_sequence": 1,
            "sync_chain_hash": "d" * 64,
            "sync_state_digest": "e" * 64,
        },
        "status_publication": {
            "publication_complete": True,
            "cycle_id": cycle_id,
            "process_instance_id": process_instance_id,
        },
        "trainer_process_status": "ACTIVE_CURRENT_CYCLE",
        "cuda_inference_status": "ACTIVE",
        "prediction_publication_status": "ACTIVE",
        "online_learning_status": "WEIGHTS_UPDATING",
        "runtime_readiness_status": "READY",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    heartbeat = {
        "generated_utc": _iso(now),
        "expires_at": _iso(now + timedelta(seconds=180)),
        "expected_cycle_cadence_seconds": 60,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
    }
    process_evidence = {
        "service_active": True,
        "service_unit": rt.PERSISTENT_TRAINER_UNIT,
        "process_id": 4242,
        "process_instance_id": process_instance_id,
    }
    runtime_status = {
        "generated_utc": _iso(now),
        "status_payload_expires_at": _iso(now + timedelta(seconds=180)),
        "expected_cycle_cadence_seconds": 60,
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "checkpoint_id": checkpoint_id,
        "candidate_policy_fingerprint": candidate_fingerprint,
        "status_publication_status": "ACTIVE",
        "runtime_readiness_status": "READY",
        "trainer_learning_ready": True,
        "current_cycle_learning_envelope": envelope,
    }
    serving = {
        "checkpoint_artifact_verified": True,
        "causal_order_verified": True,
        "lineage_kind": "VERIFIED_SERVING_POLICY",
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": parent_checkpoint_id,
        "model_parameter_fingerprint": candidate_fingerprint,
        "parent_policy_fingerprint": parent_fingerprint,
        "weight_file_sha256": checkpoint_hash,
        "exact_optimizer_contract_durable": True,
        "ledger_disposition": "SERVING_PROMOTED",
        "generated_utc": _iso(now),
    }
    prediction = {
        "generated_utc": _iso(now),
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "checkpoint_id": checkpoint_id,
        "candidate_policy_fingerprint": candidate_fingerprint,
        "publication_complete": True,
        "prediction_rows_count": 2,
        "expected_prediction_count": 2,
        "current_prediction_count": 2,
        "missing_prediction_rows_count": 0,
        "stale_prediction_rows_count": 0,
        "lineages_published": 2,
        "prediction_rows": prediction_rows,
    }
    resource = {
        "generated_utc": _iso(now),
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "cuda_available": True,
        "cuda_active": True,
        "gpu_name": "Unit CUDA GPU",
        "vram_reserved_mb": 1024,
        "batch_size": 16,
    }
    parity = {
        "generated_utc": _iso(now),
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "parity_complete": True,
        "required_missing_parity_methods": 0,
        "method_count": 324,
        "status": "FULL_FUNCTION_PARITY_VERIFIED",
    }
    return {
        "now": now,
        "envelope": envelope,
        "runtime_status": runtime_status,
        "process": process_evidence,
        "heartbeat": heartbeat,
        "serving": serving,
        "prediction": prediction,
        "resource": resource,
        "parity": parity,
    }


def _build_coherent_readiness(evidence: dict[str, object]) -> dict[str, object]:
    return build_learning_readiness(
        current_cycle_learning_envelope=evidence["envelope"],
        runtime_status_evidence=evidence["runtime_status"],
        trainer_process_evidence=evidence["process"],
        heartbeat_evidence=evidence["heartbeat"],
        verified_serving_checkpoint=evidence["serving"],
        prediction_publication_evidence=evidence["prediction"],
        resource_evidence=evidence["resource"],
        parity_evidence=evidence["parity"],
        trainer_process_active=True,
        cuda_inference_active=True,
        now_utc=evidence["now"],
    )


def test_coherent_identity_bound_current_cycle_envelope_is_ready() -> None:
    readiness = _build_coherent_readiness(_coherent_readiness_evidence())

    assert readiness["canonical_readiness_status"] == "READY"
    assert readiness["trainer_learning_ready"] is True
    assert readiness["online_learning_status"] == "WEIGHTS_UPDATING"
    assert readiness["effective_trainer_mode"] == "REPLAY_AND_ONLINE_LEARNING"
    assert readiness["readiness_blocking_reasons"] == []


def test_dead_service_blocks_otherwise_coherent_readiness() -> None:
    evidence = _coherent_readiness_evidence()
    readiness = build_learning_readiness(
        current_cycle_learning_envelope=evidence["envelope"],
        runtime_status_evidence=evidence["runtime_status"],
        trainer_process_evidence=evidence["process"],
        heartbeat_evidence=evidence["heartbeat"],
        verified_serving_checkpoint=evidence["serving"],
        prediction_publication_evidence=evidence["prediction"],
        resource_evidence=evidence["resource"],
        parity_evidence=evidence["parity"],
        trainer_process_active=False,
        cuda_inference_active=True,
        now_utc=evidence["now"],
    )

    assert readiness["canonical_readiness_status"] == "BLOCKED"
    assert "actual_trainer_process_active" in readiness["readiness_blocking_reasons"]


@pytest.mark.parametrize(
    ("mutation", "expected_blocker"),
    [
        ("missing_timestamp", "current_cycle_generated_utc_current"),
        ("stale_timestamp", "current_cycle_generated_utc_current"),
        ("nonfinite_cadence", "expected_cycle_cadence_positive_finite"),
    ],
)
def test_missing_nonfinite_or_stale_cycle_clock_blocks(
    mutation: str,
    expected_blocker: str,
) -> None:
    evidence = _coherent_readiness_evidence()
    envelope = evidence["envelope"]
    assert isinstance(envelope, dict)
    if mutation == "missing_timestamp":
        envelope.pop("generated_utc")
    elif mutation == "stale_timestamp":
        envelope["generated_utc"] = _iso(
            evidence["now"] - timedelta(seconds=181)
        )
    else:
        envelope["expected_cycle_cadence_seconds"] = float("nan")

    readiness = _build_coherent_readiness(evidence)

    assert readiness["canonical_readiness_status"] == "BLOCKED"
    assert expected_blocker in readiness["readiness_blocking_reasons"]


@pytest.mark.parametrize(
    ("target", "field", "value", "expected_blocker"),
    [
        ("heartbeat", "cycle_id", "other-cycle", "heartbeat_identity_bound"),
        (
            "process",
            "process_instance_id",
            "other-host:4242",
            "trainer_process_instance_identity_bound",
        ),
        (
            "runtime_status",
            "runtime_readiness_status",
            "BLOCKED",
            "runtime_status_readiness_consistent",
        ),
        ("serving", "checkpoint_id", "other-checkpoint", "manager_checkpoint_id_bound"),
        ("serving", "weight_file_sha256", "f" * 64, "manager_checkpoint_hash_bound"),
        (
            "prediction",
            "candidate_policy_fingerprint",
            "f" * 64,
            "prediction_publication_fingerprint_bound",
        ),
    ],
)
def test_mismatched_cycle_checkpoint_or_hashes_block(
    target: str,
    field: str,
    value: object,
    expected_blocker: str,
) -> None:
    evidence = _coherent_readiness_evidence()
    target_payload = evidence[target]
    assert isinstance(target_payload, dict)
    target_payload[field] = value

    readiness = _build_coherent_readiness(evidence)

    assert readiness["canonical_readiness_status"] == "BLOCKED"
    assert expected_blocker in readiness["readiness_blocking_reasons"]


def test_stale_resource_and_absent_parity_each_block() -> None:
    stale_resource = _coherent_readiness_evidence()
    resource = stale_resource["resource"]
    assert isinstance(resource, dict)
    resource["generated_utc"] = _iso(
        stale_resource["now"] - timedelta(seconds=181)
    )
    stale_readiness = _build_coherent_readiness(stale_resource)

    no_parity = _coherent_readiness_evidence()
    no_parity["parity"] = {}
    parity_readiness = _build_coherent_readiness(no_parity)

    assert "resource_generated_utc_current" in stale_readiness[
        "readiness_blocking_reasons"
    ]
    assert "parity_evidence_present" in parity_readiness[
        "readiness_blocking_reasons"
    ]


@pytest.mark.parametrize("published_rows", [0, 1])
def test_no_or_partial_predictions_block(published_rows: int) -> None:
    evidence = _coherent_readiness_evidence()
    prediction = evidence["prediction"]
    assert isinstance(prediction, dict)
    prediction["prediction_rows"] = prediction["prediction_rows"][:published_rows]
    prediction["prediction_rows_count"] = published_rows
    prediction["current_prediction_count"] = published_rows
    prediction["lineages_published"] = published_rows
    prediction["publication_complete"] = published_rows == 2

    readiness = _build_coherent_readiness(evidence)

    assert readiness["canonical_readiness_status"] == "BLOCKED"
    assert "prediction_grid_complete" in readiness["readiness_blocking_reasons"]


@pytest.mark.parametrize(
    ("field", "value", "expected_blocker"),
    [
        (
            "unsynced_terminal_attempts",
            1,
            "receipt_archive_terminal_attempts_fully_synced",
        ),
        (
            "archive_sync_integrity_verified",
            False,
            "receipt_archive_sync_integrity_verified",
        ),
        ("sync_chain_hash", "corrupt", "receipt_archive_sync_chain_hash_valid"),
    ],
)
def test_archive_unsynced_or_corrupt_blocks(
    field: str,
    value: object,
    expected_blocker: str,
) -> None:
    evidence = _coherent_readiness_evidence()
    envelope = evidence["envelope"]
    assert isinstance(envelope, dict)
    archive = envelope["receipt_archive_sync_status"]
    assert isinstance(archive, dict)
    archive[field] = value

    readiness = _build_coherent_readiness(evidence)

    assert readiness["canonical_readiness_status"] == "BLOCKED"
    assert expected_blocker in readiness["readiness_blocking_reasons"]


def test_stale_service_active_json_is_not_actual_process_evidence() -> None:
    assert rt.service_process_active({"ActiveState": "inactive", "MainPID": "4242"}) is False
    assert rt.service_process_active({"ActiveState": "active", "MainPID": "0"}) is False
    assert rt.service_process_active({"ActiveState": "active", "MainPID": "4242"}) is True


def test_serving_checkpoint_truth_uses_manager_causal_order_not_mtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    update_key = "1" * 64
    parent_fingerprint = "a" * 64
    candidate_fingerprint = "b" * 64

    class _Manifest:
        checkpoint_id = "causal-serving"
        generated_utc = "2026-07-18T12:00:00Z"

    class _Manager:
        manifest_filters: dict[str, object] = {}

        def manifests(self, **kwargs):
            self.manifest_filters = kwargs
            return (_Manifest(),)

        def verify_manifest_artifact(self, _manifest):
            return {
                "checkpoint_artifact_verified": True,
                "checkpoint_generation": 9,
                "checkpoint_causal_order_schema_version": "causal-v1",
                "checkpoint_causal_record_digest": "2" * 64,
                "checkpoint_id": "causal-serving",
                "parent_checkpoint_id": "causal-parent",
                "model_parameter_fingerprint": candidate_fingerprint,
                "parent_policy_fingerprint": parent_fingerprint,
                "weight_file_sha256": "c" * 64,
                "lineage_kind": "VERIFIED_SERVING_POLICY",
                "consumed_ppo_update_keys": [update_key],
                "checkpoint_evidence": {
                    "checkpoint_role": "VERIFIED_SERVING_POLICY",
                    "ledger_disposition": "SERVING_PROMOTED",
                    "candidate_progress_decision": {
                        "candidate_progress_allowed": True
                    },
                    "serving_promotion_decision": {
                        "checkpoint_promotion_allowed": True
                    },
                    "optimizer_evidence": {
                        "exact_optimizer_contract_valid": True,
                        "ppo_objective_used": True,
                        "optimizer_parameter_fingerprints_bound": True,
                        "ppo_consumed_update_keys_complete": True,
                        "ppo_consumed_update_keys_ordered": True,
                        "ppo_consumed_update_keys_unique": True,
                        "ppo_rows_consumed": 1,
                        "ppo_clipped_surrogate_rows": 1,
                        "ppo_rows_available_but_optimizer_unavailable": 0,
                    },
                },
            }

    manager = _Manager()

    monkeypatch.setattr(rt, "V2HybridCheckpointManager", lambda _model_dir: manager)

    evidence = rt.causal_verified_serving_checkpoint_evidence(tmp_path)

    assert evidence["checkpoint_artifact_verified"] is True
    assert evidence["causal_order_verified"] is True
    assert evidence["exact_optimizer_contract_durable"] is True
    assert evidence["checkpoint_id"] == "causal-serving"
    assert manager.manifest_filters == {
        "allowed_lineage_kinds": frozenset({"VERIFIED_SERVING_POLICY"}),
        "require_weight_blob": True,
    }


def test_runtime_payload_can_be_ready_only_with_coherent_current_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    public = tmp_path / "public"
    repo = tmp_path / "repo"
    evidence = _coherent_readiness_evidence()
    runtime_status = deepcopy(evidence["runtime_status"])
    assert isinstance(runtime_status, dict)
    envelope = runtime_status["current_cycle_learning_envelope"]
    assert isinstance(envelope, dict)
    heartbeat = deepcopy(evidence["heartbeat"])
    serving = deepcopy(evidence["serving"])
    prediction_evidence = deepcopy(evidence["prediction"])
    resource_evidence = deepcopy(evidence["resource"])
    parity_evidence = deepcopy(evidence["parity"])
    assert isinstance(prediction_evidence, dict)
    rows = prediction_evidence["prediction_rows"]
    assert isinstance(rows, list)

    _write_minimal_runtime_sources(public)
    _write_json(
        public,
        PREDICTION_STATUS_REL,
        {
            "generated_utc": prediction_evidence["generated_utc"],
            "publication_complete": True,
            "prediction_rows": rows,
            "prediction_rows_count": 2,
            "expected_prediction_count": 2,
            "current_prediction_count": 2,
            "missing_prediction_rows_count": 0,
            "stale_prediction_rows_count": 0,
            "lineages_published": 2,
            "current_cycle_prediction_publication_evidence": prediction_evidence,
        },
    )
    _write_json(
        public,
        rt.PERSISTENT_RESOURCE_REL,
        {"current_cycle_resource_evidence": resource_evidence},
    )
    _write_json(
        public,
        PARITY_REL,
        {"current_cycle_parity_evidence": parity_evidence},
    )

    redis_payloads = {
        rt.TRAINER_METRICS_KEY: {},
        rt.TRAINER_STATUS_KEY: runtime_status,
        rt.TRAINER_HEARTBEAT_KEY: heartbeat,
    }
    monkeypatch.setattr(rt, "connect_redis", lambda: object())
    monkeypatch.setattr(
        rt,
        "redis_json",
        lambda _client, key, default=None: redis_payloads.get(key, default or {}),
    )
    monkeypatch.setattr(rt, "scan_redis_json", lambda *_args, **_kwargs: [])

    def service_state(unit: str) -> dict[str, str]:
        if unit == rt.PERSISTENT_TRAINER_UNIT:
            return {"ActiveState": "active", "MainPID": "4242"}
        if unit == rt.TRAINER_BRIDGE_UNIT:
            return {"ActiveState": "inactive", "MainPID": "0", "UnitFileState": "masked"}
        return {"ActiveState": "inactive", "MainPID": "0"}

    monkeypatch.setattr(rt, "systemctl_show", service_state)
    monkeypatch.setattr(
        rt,
        "gpu_status_from_nvidia_smi",
        lambda: {
            "available": True,
            "gpu_name": "Unit CUDA GPU",
            "gpu_utilization_percent": 50.0,
            "vram_used_mb": 1024.0,
            "vram_total_mb": 4096.0,
        },
    )
    monkeypatch.setattr(rt, "memory_status", lambda: {"ram_used_gb": 1.0, "ram_total_gb": 4.0})
    monkeypatch.setattr(rt, "causal_verified_serving_checkpoint_evidence", lambda _repo: serving)
    monkeypatch.setattr(
        rt,
        "checkpoint_retention_status",
        lambda _repo, _checkpoint_id: {
            "checkpoint_count": 1,
            "checkpoint_total_size_gb": 0.1,
            "checkpoint_dir_size_bytes": 100,
            "checkpoint_rollover_limit_bytes": 1000,
            "checkpoint_rollover_status": "BELOW_LIMIT_NO_ACTION",
        },
    )

    payloads = build_native_trainer_runtime_payloads(
        NativeTrainerRuntimePaths(repo_root=repo, public_root=public)
    )
    runtime = payloads["native_trainer_runtime_status.json"]

    assert runtime["go_no_go"] == rt.READY
    assert runtime["canonical_readiness_status"] == "READY"
    assert runtime["trainer_learning_ready"] is True
    assert runtime["payload_age_seconds"] is not None
    assert runtime["prediction_grid_current"] is True
    assert runtime["persistent_trainer_service_active"] is True
    assert runtime["cuda_active"] is True
    assert runtime["live_execution_authorized"] is False
