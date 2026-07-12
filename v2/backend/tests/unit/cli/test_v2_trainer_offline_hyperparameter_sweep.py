"""Offline hyperparameter sweep: ranks stable configs, never touches live path."""
from __future__ import annotations

import pytest

from v2.backend.app.cli.v2_trainer_offline_hyperparameter_sweep import (
    main,
    point_in_time_safety_report,
    run_hyperparameter_sweep,
    _diverged,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import TrainingExample
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FeatureTensorRecord
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


def _tensor(index: int) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id=f"tensor_{index}", symbol="BTCUSDT", timeframe="1m",
        feature_snapshot_id=f"feat_{index}", values=(float(index),),
        missing_mask=(0,), stale_mask=(0,), source_availability=(1,),
        feature_names=("ret_pct",), source_labels=("unit",),
        missing_feature_names=(), stale_feature_names=(),
        data_coverage_percent=100.0, source_availability_vector=(1,),
    )


def _example(index: int, action_index: int) -> TrainingExample:
    expected = 12.0 if action_index == 1 else (-12.0 if action_index == 2 else 0.0)
    selected = ("hold", "long", "short")[action_index]
    return TrainingExample(
        symbol="BTCUSDT", timeframe="1m", tensor=_tensor(index),
        label_action_index=action_index, label_expected_move_after_cost_bps=expected,
        payload_keys=("unit",), row_classification="TRAINABLE",
        trust_row={
            "accepted_for_training": True, "reject_reasons": [],
            "trust_schema_version": TRUST_SCHEMA_VERSION,
            "mtf_snapshot_id": f"mtf_{index}", "mtf_snapshot_valid": True,
            "replay_snapshot_id": f"replay_{index}", "candle_closed_confirmed": True,
            "feature_cutoff": "2026-06-19T00:00:00Z", "available_at": "2026-06-19T00:00:00Z",
            "decision_time": "2026-06-19T00:01:00Z", "features": {"ret_pct": 0.0},
            "selected_action": selected, "model_version": "unit", "checkpoint_id": "ckpt_unit",
            "source_hashes": {"feature_vector_hash": f"tensor_{index}"},
            "outcome_targets": {"realized_net_pnl_bps": expected, "directional_outcome": "UP" if expected > 0 else ("DOWN" if expected < 0 else "FLAT")},
            "realized_after_cost_reward": expected / 100.0,
            "uses_expected_move_as_realized_reward": False,
        },
    )


def _rows(n: int) -> list[TrainingExample]:
    return [_example(i, (1, 2, 0)[i % 3]) for i in range(n)]


def test_sweep_returns_ranked_results_and_offline_safety() -> None:
    rows = _rows(8)
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    grid = [
        {"learning_rate": 1e-4, "entropy_coefficient": 0.01, "supervised_entropy_bonus": 0.0, "weight_decay": 0.02, "dropout": 0.10},
        {"learning_rate": 3e-4, "entropy_coefficient": 0.02, "supervised_entropy_bonus": 0.0, "weight_decay": 0.02, "dropout": 0.10},
    ]
    report = run_hyperparameter_sweep(rows, grid=grid, steps=2, batch_size=8, validation_fraction=0.34)
    assert report["config_count"] == 2
    assert report["places_real_order"] is False
    assert report["offline_only"] is True
    assert len(report["results"]) == 2
    for r in report["results"]:
        assert "validation_supervised_loss" in r
        assert "diverged" in r
        assert "config" in r
    # best (if any stable) must be a non-diverged result
    if report["best"] is not None:
        assert report["best"]["diverged"] is False
    assert report["point_in_time_safety"]["passed"] is True
    assert report["writes_checkpoint"] is False
    assert report["test_order_submitted"] is False
    assert report["leverage_mutated"] is False
    assert report["margin_mutated"] is False


def test_point_in_time_safety_report_passes_good_rows() -> None:
    report = point_in_time_safety_report(_rows(3))
    assert report["passed"] is True
    assert report["checked_rows"] == 3
    assert report["violation_count"] == 0


def test_sweep_rejects_future_leaking_rows_before_training() -> None:
    rows = _rows(2)
    assert rows[0].trust_row is not None
    rows[0].trust_row["available_at"] = "2026-06-19T00:02:00Z"
    with pytest.raises(ValueError, match="point-in-time safety"):
        run_hyperparameter_sweep(rows, grid=[], steps=0, batch_size=2)


def test_promote_flag_fails_closed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--promote"]) == 3
    captured = capsys.readouterr()
    assert "not implemented" in captured.out
    assert '"writes_checkpoint": false' in captured.out


def test_diverged_flag() -> None:
    class _R:
        loss_before = 5.0
        loss_after = 9.0  # >5*1.25 -> diverged
    assert _diverged(_R()) is True

    class _S:
        loss_before = 5.0
        loss_after = 4.0
    assert _diverged(_S()) is False
