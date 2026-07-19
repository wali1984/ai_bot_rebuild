"""Offline hyperparameter sweep: ranks stable configs, never touches live path."""
from __future__ import annotations

import pytest

from v2.backend.app.cli import v2_trainer_offline_hyperparameter_sweep as sweep_mod
from v2.backend.app.cli.v2_trainer_offline_hyperparameter_sweep import (
    main,
    point_in_time_safety_report,
    run_hyperparameter_sweep,
    stage_recovery_checkpoint,
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
            "closed_candle": True,
            "candle_open_time": "2026-06-18T23:59:00Z",
            "candle_close_time": "2026-06-19T00:00:00Z",
            "event_time": "2026-06-19T00:00:00Z",
            "ingested_at": "2026-06-19T00:00:01Z",
            "feature_cutoff": "2026-06-19T00:00:00Z",
            "generated_at": "2026-06-19T00:00:02Z",
            "available_at": "2026-06-19T00:00:03Z",
            "masa_feature_cutoff": "2026-06-19T00:00:10Z",
            "ppo_feature_cutoff": "2026-06-19T00:00:20Z",
            "decision_time": "2026-06-19T00:01:00Z",
            "ppo_decision_time": "2026-06-19T00:01:00Z",
            "execution_time": "2026-06-19T00:01:05Z",
            "outcome_available_at": "2026-06-19T00:02:00Z",
            "label_available_at": "2026-06-19T00:02:01Z",
            "training_observed_at": "2026-06-19T00:03:00Z",
            "evaluation_observed_at": "2026-06-19T00:03:00Z",
            "outcome_finalized": True,
            "label_finalized": True,
            "features": {"ret_pct": 0.0},
            "selected_action": selected, "model_version": "unit", "checkpoint_id": "ckpt_unit",
            "source_hashes": {"feature_vector_hash": f"tensor_{index}"},
            "outcome_targets": {
                "realized_net_pnl_bps": expected,
                "directional_outcome": (
                    "UP" if expected > 0 else ("DOWN" if expected < 0 else "FLAT")
                ),
            },
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


def test_sweep_does_not_select_overfit_gap_config(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _rows(3)
    grid = [
        {"learning_rate": 1e-4, "entropy_coefficient": 0.01},
        {"learning_rate": 3e-5, "entropy_coefficient": 0.005},
    ]

    def fake_train(
        examples,
        *,
        config,
        steps,
        batch_size,
        validation_fraction,
        load_checkpoint,
    ):
        if config["learning_rate"] == 1e-4:
            return {
                "config": config,
                "loss_before": 4.0,
                "loss_after": 1.0,
                "validation_supervised_loss": 0.5,
                "train_val_generalization_gap": 3.0,
                "overfit_gap_warning": True,
                "ppo_entropy": 0.8,
                "diverged": False,
                "train_rows": 2,
                "validation_rows": 1,
            }
        return {
            "config": config,
            "loss_before": 4.0,
            "loss_after": 1.8,
            "validation_supervised_loss": 1.2,
            "train_val_generalization_gap": 0.2,
            "overfit_gap_warning": False,
            "ppo_entropy": 0.5,
            "diverged": False,
            "train_rows": 2,
            "validation_rows": 1,
        }

    monkeypatch.setattr(sweep_mod, "_train_one_config", fake_train)
    report = run_hyperparameter_sweep(rows, grid=grid, steps=1, batch_size=2)

    assert report["non_diverged_config_count"] == 2
    assert report["overfit_rejected_config_count"] == 1
    assert report["stable_config_count"] == 1
    assert report["promotable_config_count"] == 1
    assert report["best"]["config"]["learning_rate"] == 3e-5
    assert report["best"]["overfit_gap_warning"] is False


def test_stage_recovery_checkpoint_writes_isolated_reloadable_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = _rows(3)
    input_dim = len(rows[0].tensor.model_vector)

    def fake_train_model_for_config(
        examples,
        *,
        config,
        steps,
        batch_size,
        validation_fraction,
        load_checkpoint,
    ):
        return V2HybridPolicyModel(input_dim=input_dim), {
            "config": config,
            "loss_before": 4.0,
            "loss_after": 1.0,
            "validation_supervised_loss": 0.5,
            "train_val_generalization_gap": 0.1,
            "overfit_gap_warning": False,
            "ppo_entropy": 0.5,
            "diverged": False,
            "train_rows": 2,
            "validation_rows": 1,
        }

    monkeypatch.setattr(sweep_mod, "_train_model_for_config", fake_train_model_for_config)
    stage_dir = tmp_path / ".local_models" / "v2_native_rl_masa_ppo_offline_recovery_candidate"

    report = stage_recovery_checkpoint(
        rows,
        config={"learning_rate": 3e-5, "entropy_coefficient": 0.005},
        stage_model_dir=stage_dir,
        steps=1,
        batch_size=2,
    )

    assert report["status"] == "STAGED_PROMOTABLE_CANDIDATE"
    assert report["staged_checkpoint_written"] is True
    assert report["runtime_checkpoint_written"] is False
    assert report["writes_current_checkpoint"] is False
    assert report["checkpoint_reload_verified"] is True
    assert report["checkpoint_weight_file_format"] == "npz"
    assert report["checkpoint_hash"]
    assert str(stage_dir) in report["checkpoint_weight_file_path"]
    assert report["places_real_order"] is False
    assert report["test_order_submitted"] is False
    assert report["leverage_mutated"] is False
    assert report["margin_mutated"] is False
    assert report["routes_to_live"] is False


def test_stage_recovery_checkpoint_refuses_runtime_model_dir() -> None:
    assert sweep_mod._looks_like_runtime_model_dir(
        sweep_mod.RUNTIME_MODEL_DIR.parent / ".." / ".local_models" / "v2_native_rl_masa_ppo"
    )
    with pytest.raises(ValueError, match="active runtime model directory"):
        stage_recovery_checkpoint(
            _rows(2),
            config={"learning_rate": 3e-5, "entropy_coefficient": 0.005},
            stage_model_dir=sweep_mod.RUNTIME_MODEL_DIR,
            steps=1,
            batch_size=2,
        )


def test_stage_recovery_checkpoint_rejects_overfit_candidate_without_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = _rows(3)

    class _FakeModel:
        model_id = "v2_hybrid_policy_" + ("b" * 24)
        device = "cpu"
        cuda_active = False

        def save_weight_blob(self, path):
            raise AssertionError("overfit candidates must not write checkpoint blobs")

    def fake_train_model_for_config(
        examples,
        *,
        config,
        steps,
        batch_size,
        validation_fraction,
        load_checkpoint,
    ):
        return _FakeModel(), {
            "config": config,
            "loss_before": 4.0,
            "loss_after": 1.0,
            "validation_supervised_loss": 0.5,
            "train_val_generalization_gap": 3.0,
            "overfit_gap_warning": True,
            "ppo_entropy": 0.8,
            "diverged": False,
            "train_rows": 2,
            "validation_rows": 1,
        }

    monkeypatch.setattr(sweep_mod, "_train_model_for_config", fake_train_model_for_config)
    stage_dir = tmp_path / ".local_models" / "candidate"

    report = stage_recovery_checkpoint(
        rows,
        config={"learning_rate": 3e-5, "entropy_coefficient": 0.005},
        stage_model_dir=stage_dir,
        steps=1,
        batch_size=2,
    )

    assert report["status"] == "REJECTED_NOT_PROMOTABLE"
    assert report["staged_checkpoint_written"] is False
    assert report["runtime_checkpoint_written"] is False
    assert report["candidate"]["overfit_gap_warning"] is True
    assert not list(stage_dir.glob("*.npz"))


def test_point_in_time_safety_report_passes_good_rows() -> None:
    report = point_in_time_safety_report(_rows(3))
    assert report["passed"] is True
    assert report["schema_version"] == "trainer_offline_point_in_time_safety_v2"
    assert report["checked_rows"] == 3
    assert report["violation_count"] == 0
    assert not any(report["missing_clock_counts"].values())
    assert not any(report["invalid_clock_counts"].values())
    assert not any(report["missing_finality_counts"].values())
    assert report["training_evaluation_observation_cutoff_field"] == (
        "training_observed_at"
    )


def test_pit_gate_rejects_naive_2099_clocks_and_missing_candle_finality() -> None:
    rows = _rows(1)
    assert rows[0].trust_row is not None
    rows[0].trust_row.update(
        {
            "candle_open_time": "2099-01-01T00:00:00Z",
            "candle_close_time": "2099-01-01T00:00:10Z",
            "event_time": "2099-01-01T00:00:10Z",
            "ingested_at": "2099-01-01T00:00:11Z",
            "feature_cutoff": "2099-01-01T00:00:10Z",
            "generated_at": "2099-01-01T00:00:12Z",
            "available_at": "2099-01-01T00:00:13Z",
            "masa_feature_cutoff": "2099-01-01T00:00:20Z",
            "ppo_feature_cutoff": "2099-01-01T00:00:30Z",
            "decision_time": "2099-01-01T00:01:00",
            "ppo_decision_time": "2099-01-01T00:01:00Z",
            "execution_time": "2099-01-01T00:01:05Z",
            "outcome_available_at": "2099-01-01T00:02:00Z",
            "label_available_at": "2099-01-01T00:02:01Z",
            "training_observed_at": "2099-01-01T00:03:00Z",
            "evaluation_observed_at": "2099-01-01T00:03:00Z",
            "candle_closed_confirmed": None,
        }
    )

    report = point_in_time_safety_report(rows)
    assert report["passed"] is False
    assert "DECISION_TIME_NOT_TIMEZONE_AWARE_OR_INVALID" in report[
        "violation_reasons"
    ]
    assert "CANDLE_CLOSED_CONFIRMED_NOT_EXPLICITLY_FINAL" in report[
        "violation_reasons"
    ]
    assert "TRAINING_OBSERVED_AT_AFTER_EVALUATION_OBSERVED_AT" in report[
        "violation_reasons"
    ]
    with pytest.raises(ValueError, match="point-in-time safety"):
        run_hyperparameter_sweep(rows, grid=[], steps=0, batch_size=1)


def test_pit_gate_fails_closed_when_any_required_clock_is_missing() -> None:
    baseline = point_in_time_safety_report(_rows(1))
    for field in baseline["required_clock_fields"]:
        rows = _rows(1)
        assert rows[0].trust_row is not None
        rows[0].trust_row.pop(field)
        report = point_in_time_safety_report(rows)
        assert report["passed"] is False
        assert f"{field.upper()}_MISSING" in report["violation_reasons"]


@pytest.mark.parametrize(
    "field",
    ["candle_closed_confirmed", "outcome_finalized", "label_finalized"],
)
def test_pit_gate_requires_explicit_candle_label_and_outcome_finality(
    field: str,
) -> None:
    rows = _rows(1)
    assert rows[0].trust_row is not None
    rows[0].trust_row[field] = None
    report = point_in_time_safety_report(rows)
    assert report["passed"] is False
    assert f"{field.upper()}_NOT_EXPLICITLY_FINAL" in report["violation_reasons"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "available_at",
            "2026-06-19T00:01:01Z",
            "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME",
        ),
        (
            "masa_feature_cutoff",
            "2026-06-19T00:01:01Z",
            "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        ),
        (
            "ppo_feature_cutoff",
            "2026-06-19T00:01:01Z",
            "PPO_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        ),
        (
            "outcome_available_at",
            "2026-06-19T00:03:01Z",
            "OUTCOME_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT",
        ),
        (
            "label_available_at",
            "2026-06-19T00:01:59Z",
            "LABEL_AVAILABLE_BEFORE_OUTCOME",
        ),
    ],
)
def test_pit_gate_enforces_feature_model_and_outcome_causality(
    field: str,
    value: str,
    reason: str,
) -> None:
    rows = _rows(1)
    assert rows[0].trust_row is not None
    rows[0].trust_row[field] = value
    report = point_in_time_safety_report(rows)
    assert report["passed"] is False
    assert reason in report["violation_reasons"]


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
