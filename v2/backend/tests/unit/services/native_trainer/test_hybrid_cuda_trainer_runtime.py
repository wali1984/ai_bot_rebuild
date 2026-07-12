from __future__ import annotations

from collections import deque

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _checkpoint_promotion_decision,
    _checkpoint_promotion_status_fields,
    _trusted_replay_load_limit_for_cycle,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import data_loader as data_loader_mod
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)


def test_trusted_replay_scan_cap_can_survive_normal_rejections_above_phase_two_floor() -> None:
    assert data_loader_mod.TRUSTED_REPLAY_MAX_SCAN_PER_CYCLE >= 16_384


def _runtime_test_example(symbol: str, timeframe: str, index: int) -> TrainingExample:
    tensor = FeatureTensorRecord(
        tensor_id=f"tensor_{symbol}_{timeframe}",
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=f"feat_{symbol}_{timeframe}",
        values=(float(index),),
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
    return TrainingExample(
        symbol=symbol,
        timeframe=timeframe,
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row={
            "accepted_for_training": True,
            "reject_reasons": [],
            "feature_cutoff": "2026-07-11T00:00:00Z",
            "decision_time": "2026-07-11T00:01:00Z",
            "available_at": "2026-07-11T00:00:30Z",
        },
    )


def test_parallel_prediction_grid_loader_preserves_pair_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, bool]] = []

    def fake_build_example(
        self: V2HybridTrainerDataLoader,
        *,
        symbol: str,
        timeframe: str,
        snapshot_fast_path: bool = False,
    ) -> TrainingExample:
        del self
        calls.append((symbol, timeframe, snapshot_fast_path))
        return _runtime_test_example(symbol, timeframe, len(calls))

    monkeypatch.setattr(V2HybridTrainerDataLoader, "build_example", fake_build_example)
    loader = V2HybridTrainerDataLoader()

    examples = loader.load_prediction_grid_examples(
        symbols=("BTCUSDT", "ETHUSDT"),
        timeframes=("1m", "5m"),
        max_workers=2,
    )

    assert [(row.symbol, row.timeframe) for row in examples] == [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "5m"),
        ("ETHUSDT", "1m"),
        ("ETHUSDT", "5m"),
    ]
    assert all(snapshot_fast_path is True for *_pair, snapshot_fast_path in calls)
    assert loader.last_prediction_grid_load["parallel_loader_used"] is True
    assert loader.last_prediction_grid_load["parallel_workers"] == 2


def test_resident_replay_load_limit_uses_replay_buffer_capacity() -> None:
    replay_buffer = deque(maxlen=4096)

    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=replay_buffer,
    )

    assert limit == 4096


def test_nonresident_replay_load_limit_uses_requested_rows() -> None:
    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=None,
    )

    assert limit == 32768


def _loadable_checkpoint() -> dict[str, object]:
    return {
        "latest_checkpoint_loadable": True,
        "model_state_restored": True,
        "load_status": "LOADED",
    }


def test_checkpoint_promotion_rejects_large_validation_loss_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A genuine, large regression at the real supervised-loss scale (~8-10) is
    # still rejected: 8.0 -> 10.0 is a 25% regression, above the 15% relative
    # tolerance.
    monkeypatch.delenv("V2_TRAINER_VALIDATION_CHECKPOINT_GUARD", raising=False)
    monkeypatch.delenv("V2_TRAINER_VALIDATION_MAX_LOSS_INCREASE_FRAC", raising=False)

    decision = _checkpoint_promotion_decision(
        training_metrics={
            "validation_rows_evaluated": 64,
            "validation_supervised_loss_before": 8.0,
            "validation_supervised_loss_after": 10.0,
            "overfit_gap_warning": False,
        },
        checkpoint_load=_loadable_checkpoint(),
    )

    assert decision["checkpoint_promotion_allowed"] is False
    assert decision["checkpoint_promotion_rejected"] is True
    assert decision["checkpoint_promotion_reason"] == "VALIDATION_LOSS_REGRESSED"


def test_checkpoint_promotion_relative_tolerance_allows_exploration_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The deadlock fix: a small regression at the real loss scale (entropy-driven
    # exploration noise) must NOT block promotion. 8.0 -> 8.5 is ~6% < 15%, so the
    # brain still promotes and durable learning is not frozen.
    monkeypatch.delenv("V2_TRAINER_VALIDATION_CHECKPOINT_GUARD", raising=False)
    monkeypatch.delenv("V2_TRAINER_VALIDATION_MAX_LOSS_INCREASE_FRAC", raising=False)

    decision = _checkpoint_promotion_decision(
        training_metrics={
            "validation_rows_evaluated": 64,
            "validation_supervised_loss_before": 8.0,
            "validation_supervised_loss_after": 8.5,
            "overfit_gap_warning": False,
        },
        checkpoint_load=_loadable_checkpoint(),
    )

    assert decision["checkpoint_promotion_allowed"] is True
    assert decision["checkpoint_promotion_rejected"] is False
    assert decision["max_validation_loss_increase"] >= 1.0  # relative to ~8.0 loss


def test_checkpoint_promotion_rejects_overfit_gap_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("V2_TRAINER_VALIDATION_CHECKPOINT_GUARD", raising=False)
    monkeypatch.delenv("V2_TRAINER_REJECT_OVERFIT_CHECKPOINTS", raising=False)

    decision = _checkpoint_promotion_decision(
        training_metrics={
            "validation_rows_evaluated": 64,
            "validation_supervised_loss_before": 0.50,
            "validation_supervised_loss_after": 0.51,
            "train_val_generalization_gap": 1.25,
            "overfit_gap_warning": True,
        },
        checkpoint_load=_loadable_checkpoint(),
    )

    assert decision["checkpoint_promotion_allowed"] is False
    assert decision["checkpoint_promotion_rejected"] is True
    assert decision["checkpoint_promotion_reason"] == "TRAIN_VAL_OVERFIT_GAP"


def test_checkpoint_promotion_allows_validation_improvement_with_residual_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("V2_TRAINER_VALIDATION_CHECKPOINT_GUARD", raising=False)
    monkeypatch.delenv("V2_TRAINER_REJECT_OVERFIT_CHECKPOINTS", raising=False)

    decision = _checkpoint_promotion_decision(
        training_metrics={
            "validation_rows_evaluated": 3276,
            "validation_supervised_loss_before": 30.87943458557129,
            "validation_supervised_loss_after": 10.78960132598877,
            "train_val_generalization_gap": 6.911758,
            "overfit_gap_warning": True,
        },
        checkpoint_load=_loadable_checkpoint(),
    )

    assert decision["checkpoint_promotion_allowed"] is True
    assert decision["checkpoint_promotion_rejected"] is False
    assert decision["validation_improved"] is True
    assert decision["overfit_gap_warning_advisory"] is True
    assert (
        decision["checkpoint_promotion_reason"]
        == "VALIDATION_IMPROVED_WITH_OVERFIT_GAP_ADVISORY"
    )


def test_checkpoint_promotion_allows_first_checkpoint_without_prior_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("V2_TRAINER_VALIDATION_CHECKPOINT_GUARD", raising=False)

    decision = _checkpoint_promotion_decision(
        training_metrics={
            "validation_rows_evaluated": 64,
            "validation_supervised_loss_before": 0.50,
            "validation_supervised_loss_after": 0.95,
            "overfit_gap_warning": True,
        },
        checkpoint_load={
            "latest_checkpoint_loadable": False,
            "model_state_restored": False,
            "load_status": "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST",
        },
    )

    assert decision["checkpoint_promotion_allowed"] is True
    assert decision["checkpoint_promotion_rejected"] is False
    assert decision["checkpoint_promotion_reason"] == "NO_PRIOR_CHECKPOINT_TO_RESTORE"


def test_checkpoint_promotion_guard_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("V2_TRAINER_VALIDATION_CHECKPOINT_GUARD", "0")

    decision = _checkpoint_promotion_decision(
        training_metrics={
            "validation_rows_evaluated": 64,
            "validation_supervised_loss_before": 0.50,
            "validation_supervised_loss_after": 1.20,
            "overfit_gap_warning": True,
        },
        checkpoint_load=_loadable_checkpoint(),
    )

    assert decision["checkpoint_promotion_allowed"] is True
    assert decision["checkpoint_promotion_rejected"] is False
    assert decision["checkpoint_promotion_reason"] == "VALIDATION_GUARD_DISABLED"


def test_checkpoint_promotion_status_fields_surface_rejection_streak() -> None:
    fields = _checkpoint_promotion_status_fields(
        {
            "checkpoint_promotion_guard_active": True,
            "checkpoint_promotion_allowed": False,
            "checkpoint_promotion_rejected": True,
            "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
            "overfit_gap_warning_advisory": None,
            "prior_promotion_rejection_streak": 2,
            "promotion_rejection_streak_after": 0,
            "max_promotion_rejection_streak": 3,
            "forced_promote_after_rejection_streak": 3,
        }
    )

    assert fields == {
        "checkpoint_promotion_guard_active": True,
        "checkpoint_promotion_allowed": False,
        "checkpoint_promotion_rejected": True,
        "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
        "overfit_gap_warning_advisory": None,
        "prior_promotion_rejection_streak": 2,
        "promotion_rejection_streak_after": 0,
        "max_promotion_rejection_streak": 3,
        "forced_promote_after_rejection_streak": 3,
    }
