from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.a_plus_phase2_directional_balance import (
    FEEDBACK_KEY,
    GOAL_ID,
    PHASE2_CONTRACT_RECEIPT_KEY,
    TRAINER_HEARTBEAT_KEY,
    TRAINER_METRICS_KEY,
    TRAINER_STATUS_KEY,
    build_a_plus_phase2_directional_balance_artifacts,
    write_a_plus_phase2_directional_balance_artifacts,
)


class FakeRedis:
    def __init__(
        self,
        payloads: dict[str, Any],
        *,
        ttls: dict[str, int] | None = None,
    ) -> None:
        self.payloads = payloads
        self.ttls = ttls or {}

    def get(self, key: str) -> str | None:
        value = self.payloads.get(key)
        if value is None:
            return None
        return json.dumps(value)

    def scan_iter(self, match: str | None = None, count: int | None = None):
        del count
        prefix = str(match or "").replace("*", "")
        for key in sorted(self.payloads):
            if key.startswith(prefix):
                yield key

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, 120)


def _row(side: str, pnl_bps: float, *, confidence: float = 0.70) -> dict[str, Any]:
    return {
        "paper_session_id": "paper_session_1",
        "trainer_consumable": True,
        "side": side,
        "action": side.lower(),
        "selected_action": side.lower(),
        "realized_net_pnl_bps": pnl_bps,
        "realized_pnl_usd": pnl_bps / 100.0,
        "confidence_calibrated": confidence,
        "trainer_feedback_id": f"fb_{side}_{pnl_bps}",
    }


def _metrics(*, class_weighted: bool = True) -> dict[str, Any]:
    weights = [1.0, 1.6, 0.5, 0.25, 0.25, 0.25, 0.25] if class_weighted else [1.0] * 7
    envelope = {
        "schema_version": "v2_native_trainer_current_cycle_learning_envelope_v1",
        "generated_utc": "2026-07-06T12:00:00Z",
        "cycle_id": "cycle_current",
        "process_instance_id": "host:123:nonce",
        "checkpoint_id": "ckpt_current",
        "candidate_policy_fingerprint": "a" * 64,
        "optimizer_steps_this_cycle": 1,
        "parameter_hash_before": "b" * 64,
        "parameter_hash_after": "c" * 64,
        "exact_optimizer_contract": {
            "valid": True,
            "ppo_objective_used": True,
            "optimizer_parameter_fingerprints_bound": True,
            "ledger_disposition": "SERVING_PROMOTED",
        },
    }
    return {
        "cycle_id": "cycle_current",
        "process_instance_id": "host:123:nonce",
        "current_cycle_learning_envelope": envelope,
        "checkpoint": {"checkpoint_id": "ckpt_current"},
        "training": {
            "action_distribution": {"0": 2, "1": 12, "2": 24, "3": 0, "4": 0, "5": 0, "6": 0},
            "metrics": {
                "action_class_weights": weights,
                "policy_bias_class_balance_nudge": [1.0, -0.25, -0.75, 0.0, 0.0, 0.0, 0.0],
                "policy_bias_nudge_strategy": "present_label_class_balance_no_majority_reinforcement",
                "target_long_fraction": 0.315789,
                "target_short_fraction": 0.631579,
                "long_label_present": True,
                "short_label_present": True,
                "single_direction_expected_move_guard_active": False,
                "single_direction_policy_action_guard_active": False,
            },
        },
    }


def _payloads(*, class_weighted: bool = True) -> dict[str, Any]:
    metrics = _metrics(class_weighted=class_weighted)
    envelope = metrics["current_cycle_learning_envelope"]
    base_signal = {
        "checkpoint_id": "ckpt_current",
        "cycle_id": "cycle_current",
        "process_instance_id": "host:123:nonce",
        "candidate_policy_fingerprint": "a" * 64,
        "feature_cutoff": "2026-07-06T11:59:00Z",
        "available_at": "2026-07-06T11:59:30Z",
        "decision_time": "2026-07-06T12:00:00Z",
        "source_hashes": {"feature_vector_hash": "d" * 64},
    }
    return {
        FEEDBACK_KEY: [
            _row("LONG", 20.0),
            _row("LONG", -4.0),
            _row("SHORT", 30.0),
            _row("SHORT", -5.0),
        ],
        TRAINER_METRICS_KEY: metrics,
        TRAINER_STATUS_KEY: {
            "cycle_id": "cycle_current",
            "process_instance_id": "host:123:nonce",
            "runtime_readiness_status": "READY",
            "trainer_learning_ready": True,
            "status_publication_status": "ACTIVE",
            "status_payload_expires_at": "2026-07-06T12:10:00Z",
            "current_cycle_learning_envelope": envelope,
        },
        TRAINER_HEARTBEAT_KEY: {
            "generated_utc": "2026-07-06T12:00:00Z",
            "cycle_id": "cycle_current",
            "process_instance_id": "host:123:nonce",
            "expires_at": "2026-07-06T12:10:00Z",
        },
        "v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1h": {
            **base_signal,
            "selected_action": "long",
        },
        "v2:trainer:hybrid_cuda:signals:paper:ETHUSDT:1h": {
            **base_signal,
            "selected_action": "short",
        },
    }


def test_phase2_directional_balance_artifacts_ready_with_side_gates() -> None:
    artifacts = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(_payloads()),
        generated_utc="2026-07-06T12:00:00Z",
    )

    directional = artifacts["directional_balance_repair_status.json"]
    calibration = artifacts["long_short_calibration_status.json"]
    side_bucket = artifacts["side_bucket_performance_status.json"]

    assert directional["status"] == "DIRECTIONAL_BALANCE_REPAIR_READY"
    assert directional["pass_conditions"]["class_weighted_loss_active"] is True
    assert directional["pass_conditions"]["signal_long_and_short_present"] is True
    assert directional["pass_conditions"]["current_cycle_runtime_evidence_valid"] is True
    assert directional["current_signal_distribution"]["current_checkpoint"] == {"LONG": 1, "SHORT": 1}
    assert directional["behavioral_proof_negative_expectancy_block"]["allowed"] is False
    assert any(
        "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE" in reason
        for reason in directional["behavioral_proof_negative_expectancy_block"]["reasons"]
    )
    assert calibration["status"] == "LONG_SHORT_CALIBRATION_CURRENT_EVIDENCE_READY"
    assert set(calibration["confidence_floors"]) == {"LONG", "SHORT"}
    assert side_bucket["status"] == "BLOCKED_SIDE_BUCKET_GATE_NO_CURRENT_RUNTIME_BLOCK_OBSERVED"
    assert side_bucket["side_gate_evaluations"]["LONG"]["allowed"] is True
    assert side_bucket["side_gate_evaluations"]["SHORT"]["allowed"] is True
    assert directional["behavioral_proof_counts_as_a_plus_readiness"] is False


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_phase2_negative_expectancy_gate_contract() -> None:
    payloads = _payloads()
    initial = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(payloads),
        generated_utc="2026-07-06T12:01:00Z",
    )["directional_balance_repair_status.json"]
    validation = initial["executed_contract_receipt"]
    receipt = {
        "schema_version": "v2_a_plus_phase2_executed_contract_receipt_v1",
        "cycle_id": "cycle_current",
        "process_instance_id": "host:123:nonce",
        "completed_at": "2026-07-06T12:00:30Z",
        "expires_at": "2026-07-06T12:10:00Z",
        "pytest_nodeid": (
            "v2/backend/tests/unit/services/native_trainer/"
            "test_a_plus_phase2_directional_balance.py::"
            "test_phase2_negative_expectancy_gate_contract"
        ),
        "outcome": "PASSED",
        "exit_code": 0,
        "runner_command": (
            ".venv/bin/pytest -q v2/backend/tests/unit/services/native_trainer/"
            "test_a_plus_phase2_directional_balance.py::"
            "test_phase2_negative_expectancy_gate_contract"
        ),
        "production_source_sha256": validation["production_source_sha256"],
        "test_source_sha256": validation["test_source_sha256"],
        "diagnostic_output_sha256": validation["diagnostic_output_sha256"],
    }
    receipt["runner_command_sha256"] = hashlib.sha256(
        receipt["runner_command"].encode("utf-8")
    ).hexdigest()
    receipt["receipt_sha256"] = _canonical_sha256(receipt)
    payloads[PHASE2_CONTRACT_RECEIPT_KEY] = receipt

    directional = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(payloads),
        generated_utc="2026-07-06T12:01:00Z",
    )["directional_balance_repair_status.json"]

    assert directional["executed_contract_receipt"]["valid"] is True
    assert directional["executed_contract_receipt"]["counts_as_a_plus_readiness"] is False
    assert directional["behavioral_proof_counts_as_a_plus_readiness"] is False


def test_phase2_stale_cross_cycle_signal_cannot_reuse_ready_evidence() -> None:
    payloads = _payloads()
    signal = payloads["v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1h"]
    signal["cycle_id"] = "old_cycle"
    artifacts = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(payloads),
        generated_utc="2026-07-06T12:01:00Z",
    )

    directional = artifacts["directional_balance_repair_status.json"]
    assert directional["status"] == "BLOCKED_DIRECTIONAL_BALANCE_EVIDENCE_INCOMPLETE"
    assert directional["pass_conditions"]["signal_long_and_short_present"] is False
    assert directional["current_signal_distribution"]["rejection_counts"][
        "CURRENT_CYCLE_IDENTITY_MISMATCH"
    ] == 1


def test_phase2_missing_or_nonpositive_redis_ttl_fails_closed() -> None:
    payloads = _payloads()
    client = FakeRedis(payloads, ttls={TRAINER_METRICS_KEY: -1})
    directional = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=client,
        generated_utc="2026-07-06T12:01:00Z",
    )["directional_balance_repair_status.json"]

    assert directional["status"] == "BLOCKED_DIRECTIONAL_BALANCE_EVIDENCE_INCOMPLETE"
    assert directional["pass_conditions"]["current_cycle_runtime_evidence_valid"] is False
    assert f"POSITIVE_TTL_UNPROVEN:{TRAINER_METRICS_KEY}" in directional[
        "current_cycle_evidence"
    ]["rejection_reasons"]


def test_phase2_directional_balance_blocks_when_class_weight_evidence_missing(tmp_path: Path) -> None:
    status = write_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(_payloads(class_weighted=False)),
        repo_root=tmp_path,
        goal_dir=tmp_path / "goal_state" / GOAL_ID,
        public_dir=tmp_path / "public" / "latest",
        generated_utc="2026-07-06T12:00:00Z",
    )

    assert status["status"] == "BLOCKED_DIRECTIONAL_BALANCE_EVIDENCE_INCOMPLETE"
    assert status["places_real_order"] is False
    assert status["exchange_leverage_mutated"] is False
    assert "class_weighted_loss_active" in status["missing_evidence"]
    payload = json.loads(
        (tmp_path / "goal_state" / GOAL_ID / "directional_balance_repair_status.json").read_text()
    )
    assert payload["class_weighted_loss"]["active"] is False
    assert (tmp_path / "public" / "latest" / "side_bucket_performance_status.json").exists()
