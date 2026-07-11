from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


ISO_CLOSE = "2026-06-11T00:01:00Z"
ISO_DECISION = "2026-06-11T00:01:01Z"


class FakeModel:
    torch_available = False
    cuda_active = False
    torch = None
    input_dim = 1
    device = "cpu"

    def forward(self, _tensor: Any) -> SimpleNamespace:
        return SimpleNamespace(action_probabilities=[1.0, 0.0, 0.0], expected_move_bps=0.0)


def _tensor() -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id="tensor-1",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="feature-1",
        values=(0.1,),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )


def _trust_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "sample_id": "row-1",
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "feature-1",
        "feature_vector_hash": "tensor-1",
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "accepted_for_training": True,
        "valid_for_training": True,
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-11T00:00:00Z",
        "candle_close_time": ISO_CLOSE,
        "source_event_time_est": ISO_CLOSE,
        "source_received_time_est": ISO_CLOSE,
        "source_available_time": ISO_CLOSE,
        "available_at": ISO_CLOSE,
        "feature_cutoff": ISO_CLOSE,
        "decision_time": ISO_DECISION,
        "decision_time_est": ISO_DECISION,
        "masa_feature_cutoff": ISO_CLOSE,
        "ppo_feature_cutoff": ISO_CLOSE,
        "decision_id": "decision-1",
        "prediction_id": "prediction-1",
        "mtf_snapshot_id": "mtf-1",
        "replay_snapshot_id": "replay-1",
        "mtf_snapshot_valid": True,
        "mtf_snapshot_reject_reasons": [],
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "ret_pct": 0.1,
        },
        "latency_ms": 100,
        "outcome_targets": {
            "realized_net_pnl_bps": 10.0,
            "directional_outcome": "UP",
        },
        "realized_after_cost_reward": 0.1,
        "uses_expected_move_as_realized_reward": False,
    }
    row.update(overrides)
    return row


def _example(**overrides: Any) -> TrainingExample:
    row_classification = str(overrides.pop("row_classification", "TRAINABLE"))
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=_tensor(),
        label_action_index=1,
        label_expected_move_after_cost_bps=10.0,
        payload_keys=("unit",),
        row_classification=row_classification,
        trust_row=_trust_row(**overrides),
    )


def test_historical_replay_missing_mask_admitted_for_training_only() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train(
        [
            _example(
                row_source="trusted_replay_archive",
                update_lane="OUTCOME_SUPERVISED_TRUSTED_REPLAY",
                trainer_feedback_source="V2_DURABLE_FEATURE_SNAPSHOT_TRUSTED_REPLAY",
                row_classification="MISSING_MASKED",
                missing_feature_names=["critical_family_absent:orderbook_depth"],
                missing_feature_count=1,
                safe_to_train_with_missing_mask=True,
                safe_missing_mask_training_scope="HISTORICAL_REPLAY_ONLY",
                feature_family_introduced_after_snapshot_time=True,
                source_availability={"ohlcv": {"available_at": ISO_CLOSE}},
                source_availability_recorded=True,
                lineage_mask_present=True,
                classification_mask_present=True,
                historical_replay_row=True,
                trusted_replay_row=True,
            )
        ],
        batch_size=4,
    )

    assert result.status != "NO_TRUSTED_TRAINING_ROWS"
    assert result.train_rows == 1
    reasons = result.metrics["training_rejection_reason_counts"]
    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in reasons
    assert "ROW_CLASSIFICATION_MISSING_MASKED" not in reasons
    assert result.metrics["trusted_replay_rows_loaded"] == 1


def test_historical_replay_missing_mask_still_rejects_stale_features() -> None:
    trainer = V2HybridPPOTrainer(model=FakeModel())

    result = trainer.train(
        [
            _example(
                row_source="trusted_replay_archive",
                update_lane="OUTCOME_SUPERVISED_TRUSTED_REPLAY",
                row_classification="MISSING_MASKED",
                missing_feature_names=["critical_family_absent:orderbook_depth"],
                missing_feature_count=1,
                stale_feature_names=["funding_rate"],
                stale_feature_count=1,
                safe_to_train_with_missing_mask=True,
                safe_missing_mask_training_scope="HISTORICAL_REPLAY_ONLY",
                feature_family_introduced_after_snapshot_time=True,
                source_availability={"ohlcv": {"available_at": ISO_CLOSE}},
                source_availability_recorded=True,
                lineage_mask_present=True,
                classification_mask_present=True,
                historical_replay_row=True,
                trusted_replay_row=True,
            )
        ],
        batch_size=4,
    )

    assert result.status == "NO_TRUSTED_TRAINING_ROWS"
    assert "STALE_FEATURE_FAMILY" in result.metrics["training_rejection_reason_counts"]
    diagnostic = result.metrics["training_rejection_family_diagnostics"][0]
    assert diagnostic["unsafe_to_train_reason"] == "STALE_FEATURE_FAMILY"
