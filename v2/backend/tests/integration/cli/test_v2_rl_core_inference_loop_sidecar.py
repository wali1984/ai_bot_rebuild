from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_rl_core_inference_loop as loop


class _MemoryRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):  # noqa: ARG002
        self.store[key] = value
        return True


@dataclass(frozen=True)
class _Record:
    prediction_id: str = "pred_rl_core_btc_1m"
    feature_snapshot_id: str = "fs_btc_1m"
    trainer_source: str = "V2_NATIVE_RL_CORE"
    checkpoint_id: str | None = None
    checkpoint_blocker: str | None = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    expected_move_bps: float = 20.0
    expected_move_after_cost_bps: float = 8.0
    confidence_raw: float = 0.7
    confidence_calibrated: float = 0.65
    feature_freshness_state: str = "CURRENT"
    selected_action: str = "long"
    policy_action_probabilities: tuple[float, ...] = (0.1, 0.8, 0.1)
    hedge_action_classification: str = "HEDGE_FAIL_CLOSED"
    generated_utc: str = "2026-06-09T21:00:00Z"


def test_rl_core_loop_writes_sidecar_only(monkeypatch) -> None:
    redis = _MemoryRedis()

    monkeypatch.setattr(loop, "_connect_redis", lambda: redis)
    monkeypatch.setattr(loop, "_read_feature_snapshot", lambda r, symbol, tf: {"feature_snapshot_id": "fs_btc_1m"})
    monkeypatch.setattr(loop, "_read_checkpoint_evidence", lambda r: {})

    import v2.backend.app.services.rl_core.trainer_output as trainer_output

    monkeypatch.setattr(trainer_output, "emit_trainer_output", lambda snapshot, checkpoint_id=None, checkpoint_blocker=None: _Record())
    monkeypatch.setattr(
        trainer_output,
        "validate_for_paper_fill_gate",
        lambda rec: {
            "paper_fill_gate_status": "TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN",
            "paper_fill_allowed": True,
            "paper_fill_gate_block_reasons": [],
        },
    )

    status = loop.run_once(("BTCUSDT",), "1m")

    assert "v2:trainer:rl_core_prediction_sidecar:BTCUSDT:1m" in redis.store
    assert "v2:prediction:BTCUSDT:1m" not in redis.store
    assert status["routes_to_orchestrator"] is False
    assert status["routes_to_risk_gateway"] is False
    assert status["writes_primary_prediction_keys"] is False
    assert status["v2_prediction_keys_written"] == [
        "v2:trainer:rl_core_prediction_sidecar:BTCUSDT:1m"
    ]
    sidecar = json.loads(
        redis.store["v2:trainer:rl_core_prediction_sidecar:BTCUSDT:1m"]
    )
    assert sidecar["trainer_source"] == "V2_NATIVE_RL_CORE"


def test_rl_core_loop_uses_active_native_checkpoint_evidence_without_fake_sidecar_weight_load(
    monkeypatch,
) -> None:
    redis = _MemoryRedis()

    monkeypatch.setattr(loop, "_connect_redis", lambda: redis)
    monkeypatch.setattr(loop, "_read_feature_snapshot", lambda r, symbol, tf: {"feature_snapshot_id": "fs_btc_1m"})
    monkeypatch.setattr(
        loop,
        "_read_checkpoint_evidence",
        lambda r: {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "checkpoint_evidence_status": "V2_SAFE_NATIVE_CHECKPOINT_LOAD_VERIFIED_WITH_LEGACY_CHECKPOINT_METADATA_PRESENT",
            "trainer_online_mode": "V2_NATIVE_RL_CORE_WITH_V2_SAFE_NATIVE_CHECKPOINT",
            "selected_checkpoint_id": "legacy_ppo_checkpoint",
            "active_checkpoint_id": "v2_hybrid_ckpt_active",
            "active_checkpoint_source": "V2_SAFE_NATIVE_NPZ",
            "active_checkpoint_blocker": None,
            "active_checkpoint_weight_status": "V2_SAFE_NATIVE_WEIGHT_BLOB_LOADED",
            "native_model_weights_load_verified": True,
        },
    )

    import v2.backend.app.services.rl_core.trainer_output as trainer_output

    monkeypatch.setattr(
        trainer_output,
        "emit_trainer_output",
        lambda snapshot, checkpoint_id=None, checkpoint_blocker=None: _Record(
            checkpoint_id=checkpoint_id,
            checkpoint_blocker=checkpoint_blocker,
        ),
    )
    monkeypatch.setattr(
        trainer_output,
        "validate_for_paper_fill_gate",
        lambda rec: {
            "paper_fill_gate_status": "TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN",
            "paper_fill_allowed": True,
            "paper_fill_gate_block_reasons": [],
        },
    )

    status = loop.run_once(("BTCUSDT",), "1m")

    sidecar = json.loads(
        redis.store["v2:trainer:rl_core_prediction_sidecar:BTCUSDT:1m"]
    )
    assert sidecar["checkpoint_id"] == "v2_hybrid_ckpt_active"
    assert sidecar["checkpoint_blocker"] is None
    assert sidecar["checkpoint_weight_status"] == "V2_SAFE_NATIVE_WEIGHT_BLOB_LOADED"
    assert sidecar["checkpoint_evidence_model_weights_load_verified"] is True
    assert sidecar["rl_core_sidecar_loaded_active_native_checkpoint"] is False
    assert sidecar["model_weights_loaded_into_v2_process"] is False
    assert status["checkpoint_id"] == "v2_hybrid_ckpt_active"
    assert status["checkpoint_blocker"] is None
    assert status["checkpoint_evidence_model_weights_load_verified"] is True
    assert status["checkpoint_evidence"]["active_checkpoint_id"] == "v2_hybrid_ckpt_active"
    assert status["checkpoint_evidence"]["active_checkpoint_source"] == "V2_SAFE_NATIVE_NPZ"
    assert status["checkpoint_evidence"]["native_model_weights_load_verified"] is True
    assert status["checkpoint_evidence"]["model_weights_loaded_into_v2_process"] is False
    assert status["checkpoint_evidence"]["weight_deserialization_performed"] is False
