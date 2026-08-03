from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.a_plus_phase1_evidence import (
    CLOSED_TRADES_KEY,
    DIAGNOSTIC_COMPLETE,
    DIAGNOSTIC_INCOMPLETE,
    FEEDBACK_KEY,
    FEEDBACK_QUARANTINE_KEY,
    GOAL_ID,
    TRAINER_METRICS_KEY,
    build_a_plus_phase1_trainer_artifacts,
    write_a_plus_phase1_trainer_artifacts,
)


def _assert_non_runtime_boundary(payload: dict[str, Any]) -> None:
    assert payload["evidence_scope"] == "LEGACY_NON_CANONICAL_DIAGNOSTIC"
    assert payload["contract_test_only"] is False
    assert payload["canonical_current_cycle_contract_consumed"] is False
    assert payload["canonical_current_cycle_contract_verified"] is False
    assert payload["canonical_runtime_ready"] is False
    assert payload["serving_authorized"] is False
    assert payload["a_plus_authorized"] is False
    assert payload["paper_authorized"] is False
    assert payload["live_authorized"] is False
    assert payload["live_execution_authorized"] is False
    assert payload["routes_to_paper"] is False
    assert payload["routes_to_live"] is False
    assert payload["artifact_ttl_enforced"] is False
    assert payload["artifact_expires_at"] is None
    assert payload["artifact_freshness_authoritative"] is False


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads

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


def _feedback_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "paper_session_id": "paper_session_1",
        "prediction_id": "pred_1",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": "2026-07-06T10:00:00Z",
        "available_at": "2026-07-06T10:00:01Z",
        "decision_time": "2026-07-06T10:00:02Z",
        "side": "LONG",
        "action": "long",
        "selected_action": "long",
        "strategy_id": "trend_mode",
        "expected_move_after_cost_bps": 12.5,
        "realized_pnl_bps": 8.0,
        "realized_pnl_usd": 0.8,
        "fees": 0.01,
        "slippage": 0.02,
        "funding": 0.0,
        "MFE": 13.0,
        "MAE": 2.0,
        "exit_reason": "TIER_2_TRAILING_STOP",
        "outcome_label": "WIN",
        "trainer_consumable": True,
        "closed_trade_validity_status": "VALID_CLOSED_TRADE",
        "counts_as_production_grade_training_evidence": True,
        "quarantine_reason": "NONE",
    }
    row.update(overrides)
    return row


def _write_checkpoint(repo_root: Path, checkpoint_id: str, content: bytes, generated_utc: str) -> Path:
    model_dir = repo_root / ".local_models/v2_native_rl_masa_ppo"
    model_dir.mkdir(parents=True, exist_ok=True)
    weight_path = model_dir / f"{checkpoint_id}.weights.npz"
    weight_path.write_bytes(content)
    manifest = {
        "checkpoint_id": checkpoint_id,
        "generated_utc": generated_utc,
        "weight_blob_written": True,
        "weight_file_path": str(weight_path.relative_to(repo_root)),
        "weight_file_size_bytes": len(content),
        "external_deserialization_used": False,
        "torch_pickle_load_used": False,
    }
    (model_dir / f"{checkpoint_id}.json").write_text(json.dumps(manifest), encoding="utf-8")
    return weight_path


def _metrics(current_path: Path, repo_root: Path, checkpoint_id: str, checkpoint_hash: str) -> dict[str, Any]:
    return {
        "checkpoint_hash": checkpoint_hash,
        "prediction_count": 3,
        "checkpoint_reload_verified": True,
        "checkpoint": {
            "checkpoint_id": checkpoint_id,
            "weight_blob_written": True,
            "weight_file_path": str(current_path.relative_to(repo_root)),
        },
        "checkpoint_reload": {
            "checkpoint_id": checkpoint_id,
            "latest_checkpoint_loadable": True,
            "model_state_restored": True,
            "weight_file_path": str(current_path.relative_to(repo_root)),
        },
        "training": {
            "status": "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_CUDA_TRAINING_STEP_RAN",
            "training_steps": 64,
            "train_rows": 2,
            "validation_rows": 1,
            "loss_before": 2.0,
            "loss_after": 1.0,
            "action_distribution": {"1": 1, "2": 2},
            "metrics": {
                "trusted_rows_loaded": 3,
                "feedback_rows_entered_batch": 1,
                "optimizer_steps_this_cycle": 64,
                "optimizer_steps_last_hour": 64,
                "optimizer_steps_total": 64,
                "parameter_hash_before": "before",
                "parameter_hash_after": "after",
                "weight_delta_norm": 0.25,
                "checkpoint_weight_blob_written": True,
                "checkpoint_reload_verified": True,
                "checkpoint_path": str(current_path.relative_to(repo_root)),
                "checkpoint_hash": checkpoint_hash,
                "last_successful_weight_update_at": "2026-07-06T10:10:00Z",
                "learning_update_lane": "outcome_supervised",
                "online_learning_status": "WEIGHTS_UPDATING",
                "effective_trainer_mode": "ONLINE_PAPER_LEARNING",
                "outcome_supervised_update_used": True,
                "ppo_objective_used": False,
                "uses_expected_move_as_realized_reward": False,
                "rows_rejected_by_reason": {},
            },
        },
    }


def test_a_plus_phase1_artifacts_ready_from_current_feedback_and_checkpoint(tmp_path: Path) -> None:
    previous = _write_checkpoint(
        tmp_path,
        "v2_hybrid_ckpt_previous",
        b"previous-weights",
        "2026-07-06T09:00:00Z",
    )
    current = _write_checkpoint(
        tmp_path,
        "v2_hybrid_ckpt_current",
        b"current-weights-mutated",
        "2026-07-06T10:10:00Z",
    )
    os.utime(previous, (1, 1))
    os.utime(current, (2, 2))
    import hashlib

    current_hash = hashlib.sha256(current.read_bytes()).hexdigest()
    client = FakeRedis(
        {
            FEEDBACK_KEY: [_feedback_row()],
            FEEDBACK_QUARANTINE_KEY: [],
            CLOSED_TRADES_KEY: [_feedback_row()],
            TRAINER_METRICS_KEY: _metrics(current, tmp_path, "v2_hybrid_ckpt_current", current_hash),
            "v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1h": {
                "checkpoint_id": "v2_hybrid_ckpt_current",
                "prediction_id": "pred_current",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "confidence_calibrated": 0.61,
                "selected_action": "long",
            },
        }
    )

    artifacts = build_a_plus_phase1_trainer_artifacts(
        redis_client=client,
        repo_root=tmp_path,
        generated_utc="2026-07-06T10:11:00Z",
    )

    repair = artifacts["trainer_online_learning_repair_status.json"]
    feedback = artifacts["trainer_feedback_consumption_status.json"]
    weights = artifacts["trainer_weight_update_proof.json"]
    checkpoint = artifacts["trainer_checkpoint_update_proof.json"]
    assert repair["status"] == DIAGNOSTIC_COMPLETE
    assert repair["diagnostic_conditions"] == {
        "checkpoint_weight_blob_updated": True,
        "consumable_feedback_rows_gt_0": True,
        "trusted_rows_loaded_gt_0": True,
        "weights_updated": True,
    }
    assert feedback["consumable_feedback_rows"] == 1
    assert feedback["required_field_coverage_complete"] is True
    assert weights["weights_updated"] is True
    assert checkpoint["checkpoint_hash_matches_metrics"] is True
    assert checkpoint["checkpoint_weight_blob_updated"] is True
    assert checkpoint["predictions_changed_after_feedback"] is True
    assert checkpoint["published_prediction_sample"]["prediction_id"] == "pred_current"
    for payload in artifacts.values():
        _assert_non_runtime_boundary(payload)
    assert feedback["status"] == "DIAGNOSTIC_FEEDBACK_CONTRACT_OBSERVED_NON_CANONICAL"


def test_a_plus_phase1_writer_blocks_missing_feedback_fields_without_live_mutation(tmp_path: Path) -> None:
    current = _write_checkpoint(
        tmp_path,
        "v2_hybrid_ckpt_current",
        b"current-weights-mutated",
        "2026-07-06T10:10:00Z",
    )
    import hashlib

    current_hash = hashlib.sha256(current.read_bytes()).hexdigest()
    incomplete = _feedback_row()
    incomplete.pop("feature_snapshot_id")
    client = FakeRedis(
        {
            FEEDBACK_KEY: [incomplete],
            FEEDBACK_QUARANTINE_KEY: [],
            CLOSED_TRADES_KEY: [incomplete],
            TRAINER_METRICS_KEY: _metrics(current, tmp_path, "v2_hybrid_ckpt_current", current_hash),
            "v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1h": {
                "checkpoint_id": "v2_hybrid_ckpt_current",
                "prediction_id": "pred_current",
            },
        }
    )
    goal_dir = tmp_path / "goal_state" / GOAL_ID
    public_dir = tmp_path / "public" / "latest"

    status = write_a_plus_phase1_trainer_artifacts(
        redis_client=client,
        repo_root=tmp_path,
        goal_dir=goal_dir,
        public_dir=public_dir,
        generated_utc="2026-07-06T10:11:00Z",
    )

    assert status["status"] == DIAGNOSTIC_INCOMPLETE
    _assert_non_runtime_boundary(status)
    assert status["places_real_order"] is False
    assert status["exchange_leverage_mutated"] is False
    feedback = json.loads((goal_dir / "trainer_feedback_consumption_status.json").read_text())
    assert feedback["consumable_feedback_rows"] == 0
    assert feedback["contract_missing_counts"] == {"feature_snapshot_id": 1}
    assert (public_dir / "trainer_online_learning_repair_status.json").exists()
