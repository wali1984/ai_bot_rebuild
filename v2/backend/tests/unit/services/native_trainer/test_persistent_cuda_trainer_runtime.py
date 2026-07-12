from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from v2.backend.app.services.native_trainer import persistent_cuda_trainer_runtime as runtime_module
from v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime import (
    PersistentTrainerPaths,
    build_paper_drawdown_attribution,
    build_paper_drawdown_guard,
    build_persistent_runtime_status,
    build_resource_status,
    checkpoint_retention_status,
    publish_training_cycle_heartbeat,
    publish_persistent_payloads,
    record_cycle_state,
)


class _FakeRedis:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, key: str) -> str | None:
        value = self.values.get(key)
        if value is None:
            return None
        return json.dumps(value)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self.values[key] = json.loads(value)
        return True


def _trusted_feedback_row(
    *,
    feature_snapshot_id: str = "feat-1",
    embedded_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "trainer_consumable": True,
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "decision_id": "dec-1",
        "entry_feature_snapshot_id": feature_snapshot_id,
        "mtf_snapshot_id": "mtf-1",
        "feature_cutoff": "2026-06-22T00:00:00Z",
        "decision_time": "2026-06-22T00:01:00Z",
        "available_at": "2026-06-22T00:00:30Z",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "model_version": "model-1",
        "checkpoint_id": "ckpt-1",
        "source_hashes": {"feature_vector_hash": "hash-1"},
    }
    if embedded_snapshot is not None:
        row["entry_feature_snapshot"] = embedded_snapshot
    return row


def _feature_snapshot(feature_snapshot_id: str = "feat-1") -> dict[str, object]:
    return {
        "feature_snapshot_id": feature_snapshot_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-06-22T00:00:30Z",
        "feature_cutoff": "2026-06-22T00:00:00Z",
        "features": {"ret_pct": 1.0},
    }


def test_online_learning_runtime_fields_publish_checkpoint_evidence() -> None:
    fields = runtime_module.online_learning_runtime_fields(
        training={
            "status": "TRAINED",
            "metrics": {
                "trusted_rows_loaded": 3,
                "trusted_replay_rows_loaded": 3,
                "optimizer_steps_this_cycle": 2,
                "optimizer_steps_last_hour": 2,
                "optimizer_steps_total": 7,
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

    assert fields["online_learning_status"] == "WEIGHTS_UPDATING"
    assert fields["effective_trainer_mode"] == "TRUSTED_REPLAY_TRAINING"
    assert fields["trainer_learning_ready"] is True
    assert fields["checkpoint_path"] == "/tmp/unit-checkpoint.pt"
    assert fields["checkpoint_hash"] == "checkpoint-sha256"


def test_gpu_saturation_controller_backs_off_after_validation_checkpoint_rejection() -> None:
    decision = runtime_module.adaptive_gpu_saturation_decision(
        state={"steps_multiplier": 4},
        accepted_rows=16_384,
        data_loader_time_ms=100_000.0,
        gpu_train_time_ms=25_000.0,
        vram_reserved_mb=4_000.0,
        vram_total_mb=16_000.0,
        oom_occurred=False,
        checkpoint_promotion_rejected=True,
        checkpoint_promotion_reason="VALIDATION_LOSS_REGRESSED",
        validation_loss_delta=0.858461,
        overfit_gap_warning=True,
    )

    assert decision["classification"] == "VALIDATION_CHECKPOINT_BACKOFF"
    assert decision["steps_multiplier"] == 2
    assert decision["checkpoint_promotion_rejected"] is True
    assert decision["checkpoint_promotion_reason"] == "VALIDATION_LOSS_REGRESSED"
    assert decision["artificial_load_added"] is False


def test_gpu_saturation_controller_backs_off_on_validation_delta_without_rejection_flag() -> None:
    decision = runtime_module.adaptive_gpu_saturation_decision(
        state={"steps_multiplier": 3},
        accepted_rows=16_384,
        data_loader_time_ms=120_000.0,
        gpu_train_time_ms=20_000.0,
        vram_reserved_mb=4_000.0,
        vram_total_mb=16_000.0,
        oom_occurred=False,
        checkpoint_promotion_rejected=False,
        checkpoint_promotion_reason=None,
        validation_loss_delta=1.65997,
        overfit_gap_warning=False,
    )

    assert decision["classification"] == "VALIDATION_CHECKPOINT_BACKOFF"
    assert decision["steps_multiplier"] == 1
    assert decision["validation_regressed"] is True
    assert decision["validation_loss_backoff_delta"] == runtime_module.RESIDENT_VALIDATION_LOSS_BACKOFF_DELTA


def test_gpu_saturation_controller_uses_top_level_checkpoint_promotion() -> None:
    client = _FakeRedis(
        {
            runtime_module.RESIDENT_GPU_SATURATION_CONTROLLER_KEY: {
                "steps_multiplier": 4,
            }
        }
    )

    decision = runtime_module.update_gpu_saturation_controller(
        client=client,
        nested_training_metrics={
            "accepted_training_rows": 16_384,
            "data_loader_time_ms": 100_000.0,
            "gpu_train_time_ms": 25_000.0,
            "vram_reserved_mb": 4_000.0,
            "validation_loss_delta": -20.0,
            "overfit_gap_warning": False,
        },
        oom_occurred=False,
        checkpoint_promotion={
            "checkpoint_promotion_rejected": True,
            "checkpoint_promotion_reason": "TRAIN_VAL_OVERFIT_GAP",
        },
    )

    assert decision["classification"] == "VALIDATION_CHECKPOINT_BACKOFF"
    assert decision["steps_multiplier"] == 2
    assert decision["checkpoint_promotion_rejected"] is True
    assert decision["checkpoint_promotion_reason"] == "TRAIN_VAL_OVERFIT_GAP"
    assert client.values[runtime_module.RESIDENT_GPU_SATURATION_CONTROLLER_KEY][
        "checkpoint_promotion_rejected"
    ] is True


def test_drawdown_attribution_separates_trial_overlay_from_native() -> None:
    ledger = {
        "accepted": [
            {
                "fill_id": "normal-1",
                "symbol": "BTCUSDT",
                "unrealized_pnl": 2.5,
            },
            {
                "fill_id": "trial-1",
                "symbol": "ETHUSDT",
                "signal_id": "sig_paper_conf_trial_pred-1",
                "paper_confidence_threshold_trial": True,
                "unrealized_pnl": -6.0,
            },
        ]
    }
    portfolio = {"total_pnl_usd": -3.5, "unrealized_pnl_usd": -3.5, "realized_pnl_usd": 0.0}

    status = build_paper_drawdown_attribution(
        portfolio=portfolio,
        ledger=ledger,
        previous_paper_pnl=30.0,
    )

    assert status["normal_native_fill_count"] == 1
    assert status["trial_overlay_fill_count"] == 1
    assert status["normal_native_pnl"] == 2.5
    assert status["trial_overlay_pnl"] == -6.0
    assert status["delta"] == -33.5


def test_drawdown_guard_pauses_when_attribution_lost_and_delta_breaches() -> None:
    attribution = {
        "delta": -71.0,
        "trial_overlay_pnl": 0.0,
        "trial_overlay_fill_count": 0,
        "normal_native_fill_count": 20,
        "trial_attribution_lost_or_expired": True,
    }

    guard = build_paper_drawdown_guard(attribution=attribution, existing_trial_status={})

    assert guard["status"] == "TRIAL_PAUSED_DRAWDOWN_GUARD"
    assert guard["trial_enabled"] is False
    assert guard["stop_promoting_new_threshold_trial_signals"] is True


def test_checkpoint_retention_keeps_latest_below_300gb(tmp_path: Path) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    checkpoint_dir = paths.model_dir
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "v2_hybrid_ckpt_old.json").write_text("{}", encoding="utf-8")
    latest = checkpoint_dir / "v2_hybrid_ckpt_latest.json"
    latest.write_text("{}", encoding="utf-8")

    status = checkpoint_retention_status(
        paths=paths,
        latest_checkpoint_id="v2_hybrid_ckpt_latest",
        apply_rollover=True,
    )

    assert status["checkpoint_count"] == 2
    assert status["rollover_action_taken"] == "NONE"
    assert status["latest_checkpoint"] == "checkpoint_retention_manifest.json" or status["latest_checkpoint"] == latest.name
    assert latest.exists()


def test_resource_status_distinguishes_sample_set_below_target_from_training_blocker(monkeypatch) -> None:
    class _TrainerResult:
        metrics = {
            "training": {
                "batch_size": 668,
            }
        }

        status = {
            "cuda_cpu_resource_utilization": {
                "target_batch_size": 8192,
                "actual_batch_size": 668,
                "tensor_rows_per_second": 1000.0,
                "current_vram_used_mb": 1280.0,
                "vram_total_mb": 16384.0,
                "dataloader_workers": 0,
                "prefetch_factor": None,
                "pinned_memory": True,
                "mixed_precision_enabled": True,
            }
        }

    monkeypatch.setattr(
        runtime_module,
        "gpu_status_from_nvidia_smi",
        lambda: {"vram_used_mb": 1280.0, "vram_total_mb": 16384.0, "gpu_name": "test-gpu"},
    )
    monkeypatch.setattr(runtime_module, "memory_status", lambda: {"ram_total_gb": 64.0, "ram_used_gb": 16.0})
    monkeypatch.setattr(runtime_module, "cpu_utilization_percent", lambda: 12.0)

    resource = build_resource_status(trainer_result=_TrainerResult(), persistent_state={})

    assert resource["bottleneck_reason"] == "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH"
    assert resource["training_blocker_reason"] is None
    assert resource["batch_size"] == 668
    assert resource["target_batch_size"] == 8192
    assert resource["gpu_utilization_limit_percent"] == 75.0
    assert resource["vram_limit_mb"] == 12288
    assert resource["vram_target_mb"] == 12288.0
    assert resource["cpu_quota_percent"] == 50.0
    assert resource["ram_limit_gb"] == 75.0


def test_resource_status_prefers_training_window_gpu_utilization(monkeypatch) -> None:
    class _TrainerResult:
        metrics = {
            "training": {
                "batch_size": 4096,
                "metrics": {
                    "accepted_training_rows": 16384,
                    "available_examples": 16384,
                    "actual_batch_size": 16384,
                    "training_window_gpu_utilization_avg_percent": 68.5,
                    "training_window_gpu_utilization_max_percent": 74.0,
                    "training_window_gpu_utilization_sample_count": 12,
                    "data_loader_time_ms": 9000.0,
                    "gpu_train_time_ms": 18000.0,
                },
            }
        }

        status = {
            "cuda_cpu_resource_utilization": {
                "target_batch_size": 4096,
                "actual_batch_size": 16384,
                "current_vram_used_mb": 9000.0,
                "vram_total_mb": 16303.0,
            }
        }

    monkeypatch.setattr(
        runtime_module,
        "gpu_status_from_nvidia_smi",
        lambda: {
            "gpu_utilization_percent": 9.0,
            "vram_used_mb": 9560.0,
            "vram_total_mb": 16303.0,
            "gpu_name": "test-gpu",
        },
    )
    monkeypatch.setattr(runtime_module, "memory_status", lambda: {"ram_total_gb": 64.0, "ram_used_gb": 16.0})
    monkeypatch.setattr(runtime_module, "cpu_utilization_percent", lambda: 12.0)

    resource = build_resource_status(trainer_result=_TrainerResult(), persistent_state={})

    assert resource["gpu_utilization_percent"] == 68.5
    assert resource["gpu_utilization_source"] == "training_window_nvidia_smi_sampler"
    assert resource["current_gpu_utilization_percent"] == 9.0
    assert resource["training_window_gpu_utilization_max_percent"] == 74.0
    assert resource["training_window_gpu_utilization_sample_count"] == 12


def test_persistent_runtime_status_exposes_utc_and_liveness(tmp_path: Path, monkeypatch) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 10,
                "expected_prediction_count": 10,
                "blocked_prediction_rows_count": 2,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda _unit: {"ActiveState": "active", "MainPID": str(os.getpid())},
    )
    monkeypatch.setattr(
        runtime_module,
        "resolve_symbols_with_provenance",
        lambda: {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "smoke_test": False,
            "source_path": "unit-symbol-universe.json",
            "discovered_count": 4,
            "binance_usdm_confirmed_count": 4,
            "baseline_count": 25,
            "count": 4,
        },
    )
    now_ts = time.time()

    status = build_persistent_runtime_status(
        paths=paths,
        trainer_result=None,
        persistent_state={
            "started_ts": now_ts - 30,
            "training_steps_total": 7,
            "step_events": [
                {
                    "ts": now_ts - 1,
                    "training_steps": 1,
                    "prediction_rows": 10,
                    "samples_seen": 5,
                    "batches": 1,
                }
            ],
        },
        resource={
            "bottleneck_reason": "DATASET_TOO_SMALL",
            "batch_size": 8,
            "target_batch_size": 64,
            "current_vram_used_mb": 1024.0,
            "vram_total_mb": 16384.0,
            "gpu_name": "unit-test-gpu",
        },
        checkpoint={"latest_checkpoint_id": "ckpt", "generated_est": "2026-06-14T08:00:00-04:00"},
    )

    assert status["generated_utc"].endswith("Z")
    assert status["current_status_age_seconds"] == 0
    assert status["worker_health_status"] == "HEALTHY"
    assert status["trainer_liveness_status"] == "HEALTHY"
    assert status["heartbeat_age_seconds"] is not None
    assert status["heartbeat_age_seconds"] <= 5
    assert status["prediction_grid_rows"] == 10
    assert status["prediction_grid_expected_rows"] == 10
    assert status["expected_prediction_grid_rows"] == 10
    assert status["training_symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    assert status["training_symbols_count"] == 4
    assert status["trainer_symbol_profile"] == "dynamic_or_baseline"
    assert status["trainer_smoke_test_scope"] is False
    assert status["trainer_btc_eth_sol_only_scope"] is False
    assert status["trainer_all_runtime_symbols_enabled"] is True
    assert status["training_grid_expected_rows_from_symbol_scope"] == 20
    assert status["train_rows"] is None
    assert status["validation_rows"] is None
    assert status["current_batch_size"] == 8
    assert status["target_batch_size"] == 64
    assert status["current_vram_used_mb"] == 1024.0
    assert status["vram_total_mb"] == 16384.0
    assert status["gpu_name"] == "unit-test-gpu"


def test_training_cycle_heartbeat_refreshes_runtime_status_without_training(tmp_path: Path) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 680,
                "expected_prediction_count": 680,
                "current_prediction_count": 680,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 45,
            }
        ),
        encoding="utf-8",
    )
    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_path.write_text(json.dumps({"training_steps_total": 9}), encoding="utf-8")

    status = publish_training_cycle_heartbeat(
        paths=paths,
        persistent_state={"training_steps_total": 9},
        max_rows=8192,
        run_training=True,
    )

    public_status = json.loads(
        (paths.artifact_dir / "native_cuda_trainer_persistent_runtime_status.json").read_text(encoding="utf-8")
    )
    operator_status = json.loads(
        (paths.operator_dir / "native_cuda_trainer_persistent_runtime_status.json").read_text(encoding="utf-8")
    )
    merged_runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )
    assert status["training_cycle_status"] == "TRAINING_CYCLE_IN_PROGRESS"
    assert public_status["current_status_age_seconds"] == 0
    assert public_status["prediction_grid_rows"] == 680
    assert public_status["expected_prediction_grid_rows"] == 680
    assert public_status["prediction_grid_current"] is True
    assert public_status["blocked_prediction_rows"] == 45
    assert public_status["training_steps_total"] == 9
    assert operator_status["training_cycle_status"] == "TRAINING_CYCLE_IN_PROGRESS"
    assert merged_runtime["training_cycle_status"] == "TRAINING_CYCLE_IN_PROGRESS"
    assert merged_runtime["persistent_trainer_service_active"] is True
    assert merged_runtime["prediction_grid_current"] is True


def test_training_cycle_heartbeat_exposes_full_trainer_symbol_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 20,
                "expected_prediction_count": 20,
                "current_prediction_count": 20,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "resolve_symbols_with_provenance",
        lambda: {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "smoke_test": False,
            "source_path": "unit-symbol-universe.json",
            "discovered_count": 4,
            "binance_usdm_confirmed_count": 4,
            "baseline_count": 25,
            "count": 4,
        },
    )

    status = publish_training_cycle_heartbeat(
        paths=paths,
        persistent_state={"training_steps_total": 9},
        max_rows=8192,
        run_training=True,
    )
    merged_runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )

    assert status["training_symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
    assert status["training_symbols_count"] == 4
    assert status["trainer_btc_eth_sol_only_scope"] is False
    assert status["trainer_all_runtime_symbols_enabled"] is True
    assert status["training_grid_expected_rows_from_symbol_scope"] == 20
    assert merged_runtime["training_symbols_count"] == 4
    assert merged_runtime["trainer_btc_eth_sol_only_scope"] is False
    assert merged_runtime["trainer_all_runtime_symbols_enabled"] is True


def test_run_native_training_cycle_uses_full_resolved_symbol_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(runtime_module, "connect_redis", lambda: None)
    monkeypatch.setattr(
        runtime_module,
        "resolve_symbols_with_provenance",
        lambda: {
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "smoke_test": False,
            "count": 4,
        },
    )

    def _fake_run_hybrid_trainer_cycle(*, config, io, publish, replay_buffer, prefetched_backfill_examples=None):
        captured["symbols"] = config.symbols
        captured["timeframes"] = config.timeframes
        captured["live_gate"] = config.live_gate
        captured["live_symbols"] = config.live_symbols
        captured["max_training_rows_per_cycle"] = config.max_training_rows_per_cycle
        captured["batch_size"] = config.batch_size
        captured["train_steps"] = config.train_steps
        captured["publish"] = publish
        return object()

    monkeypatch.setattr(runtime_module, "run_hybrid_trainer_cycle", _fake_run_hybrid_trainer_cycle)

    runtime_module.run_native_training_cycle(paths=paths, max_rows=64, risk_caps_configured=True)

    assert captured["symbols"] == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert captured["timeframes"] == ("1m", "5m", "15m", "1h", "4h")
    assert captured["live_gate"] == "blocked_human_only"
    assert captured["live_symbols"] == ()
    assert captured["max_training_rows_per_cycle"] == 64
    assert captured["batch_size"] == 64
    assert captured["train_steps"] == 1
    assert captured["publish"] is True


def test_run_native_training_cycle_caps_batch_size_for_large_max_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(runtime_module, "connect_redis", lambda: None)
    monkeypatch.setattr(
        runtime_module,
        "resolve_symbols_with_provenance",
        lambda: {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "smoke_test": False,
            "count": 2,
        },
    )

    def _fake_run_hybrid_trainer_cycle(*, config, io, publish, replay_buffer, prefetched_backfill_examples=None):
        captured["max_training_rows_per_cycle"] = config.max_training_rows_per_cycle
        captured["batch_size"] = config.batch_size
        captured["train_steps"] = config.train_steps
        captured["publish"] = publish
        return object()

    monkeypatch.setattr(runtime_module, "run_hybrid_trainer_cycle", _fake_run_hybrid_trainer_cycle)

    runtime_module.run_native_training_cycle(paths=paths, max_rows=32768, risk_caps_configured=True)

    assert captured["max_training_rows_per_cycle"] == 32768
    assert captured["batch_size"] == runtime_module.RESIDENT_MAX_BATCH_SIZE
    assert captured["train_steps"] == runtime_module.RESIDENT_MAX_TRAIN_STEPS_PER_CYCLE
    assert captured["publish"] is True


def test_legacy_grade_runtime_config_defaults_fast_live_cadence_and_flags_partitioning(
    monkeypatch,
) -> None:
    for name in runtime_module.LEGACY_RUNTIME_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("RL_SAFE_ENV_CAP", raising=False)
    monkeypatch.delenv("V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER", raising=False)
    symbols = [f"SYM{i}USDT" for i in range(135)]

    config = runtime_module.legacy_grade_runtime_config(
        symbols=symbols,
        timeframes=("1m", "5m", "15m", "1h", "4h"),
        max_rows=32768,
    )
    effective = config["effective_config"]

    assert config["symbol_timeframe_pairs"] == 675
    assert config["n_envs"] == runtime_module.LEGACY_RUNTIME_SAFE_ENV_CAP
    assert config["coverage_mode"] == "DETERMINISTIC_ROTATING_PARTITIONS_REQUIRED"
    assert config["coverage_not_silent"] is True
    assert config["coverage_cycles_to_touch_all_pairs"] == 3
    assert effective["n_steps"] == runtime_module.DEFAULT_ROLLOUT_N_STEPS
    assert effective["batch_size"] == runtime_module.RESIDENT_MAX_BATCH_SIZE
    assert effective["prediction_loop_seconds"] == 5
    assert effective["post_training_pause_seconds"] == 0
    assert effective["amp_enabled_default"] is True
    assert effective["tf32_enabled_default"] is True
    assert effective["cudnn_benchmark_enabled_default"] is True
    assert effective["grad_scaler_enabled_default"] is True


def test_run_native_training_cycle_uses_legacy_runtime_env_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setenv("RL_N_ENVS", "3")
    monkeypatch.setenv("RL_N_STEPS", "1024")
    monkeypatch.setenv("RL_BATCH_SIZE", "2048")
    monkeypatch.setenv("PPO_N_EPOCHS", "2")
    monkeypatch.delenv("ENABLE_AUTO_GPU_SCALE", raising=False)
    monkeypatch.delenv("V2_NATIVE_TRAINER_ADAPTIVE_GPU_CONTROLLER", raising=False)
    monkeypatch.setattr(runtime_module, "connect_redis", lambda: None)
    monkeypatch.setattr(
        runtime_module,
        "resolve_symbols_with_provenance",
        lambda: {
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "smoke_test": False,
            "count": 2,
        },
    )

    def _fake_run_hybrid_trainer_cycle(*, config, io, publish, replay_buffer, prefetched_backfill_examples=None):
        captured["rollout_max_envs"] = config.rollout_max_envs
        captured["rollout_n_steps"] = config.rollout_n_steps
        captured["batch_size"] = config.batch_size
        captured["train_steps"] = config.train_steps
        captured["publish"] = publish
        return object()

    monkeypatch.setattr(runtime_module, "run_hybrid_trainer_cycle", _fake_run_hybrid_trainer_cycle)

    runtime_module.run_native_training_cycle(paths=paths, max_rows=4096, risk_caps_configured=True)

    assert captured["rollout_max_envs"] == 3
    assert captured["rollout_n_steps"] == 1024
    assert captured["batch_size"] == 2048
    assert captured["train_steps"] == 16
    assert captured["publish"] is True


def test_training_cycle_heartbeat_preserves_partial_prediction_grid_status(tmp_path: Path) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 10,
                "expected_prediction_count": 10,
                "current_prediction_count": 8,
                "missing_prediction_rows_count": 2,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 8,
                "coverage_status": "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS",
                "actionability_status": "PAPER_ACTIONABILITY_BLOCKED_BY_GATES",
                "missing_prediction_symbols": ["HIGHUSDT"],
                "missing_prediction_timeframes_by_symbol": {"HIGHUSDT": ["1m", "5m"]},
            }
        ),
        encoding="utf-8",
    )

    status = publish_training_cycle_heartbeat(
        paths=paths,
        persistent_state={"training_steps_total": 9},
        max_rows=8192,
        run_training=True,
    )

    merged_runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )
    assert status["prediction_grid_current"] is False
    assert status["current_prediction_count"] == 8
    assert status["missing_prediction_rows_count"] == 2
    assert status["non_current_prediction_rows_count"] == 2
    assert merged_runtime["prediction_grid_current"] is False
    assert merged_runtime["current_prediction_count"] == 8
    assert merged_runtime["missing_prediction_rows_count"] == 2
    assert merged_runtime["prediction_coverage_status"] == "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS"
    assert merged_runtime["prediction_actionability_status"] == "PAPER_ACTIONABILITY_BLOCKED_BY_GATES"
    assert merged_runtime["missing_prediction_symbols"] == ["HIGHUSDT"]
    assert merged_runtime["missing_prediction_timeframes_by_symbol"] == {"HIGHUSDT": ["1m", "5m"]}


def test_record_cycle_state_status_only_heartbeat_does_not_increment_training_steps(tmp_path: Path) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)

    state = record_cycle_state(
        paths=paths,
        training_steps=0,
        prediction_rows=680,
        samples_seen=0,
        batches=0,
    )

    assert state["training_steps_total"] == 0
    assert state["step_events"][-1]["training_steps"] == 0
    assert state["step_events"][-1]["prediction_rows"] == 680
    assert state["step_events"][-1]["heartbeat_only"] is True


def test_run_one_persistent_cycle_timeout_is_fail_closed_zero_step(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 10,
                "expected_prediction_count": 10,
                "current_prediction_count": 10,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
            }
        ),
        encoding="utf-8",
    )
    (paths.public_root / runtime_module.PORTFOLIO_REL).parent.mkdir(parents=True, exist_ok=True)
    (paths.public_root / runtime_module.PORTFOLIO_REL).write_text(json.dumps({"total_pnl_usd": 0.0}), encoding="utf-8")
    monkeypatch.setattr(runtime_module, "RESIDENT_NATIVE_CYCLE_TIMEOUT_SECONDS", 1)

    @contextmanager
    def _timeout(_seconds: int):
        raise runtime_module.NativeCycleTimeout("unit timeout")
        yield

    monkeypatch.setattr(runtime_module, "resident_native_cycle_timeout", _timeout)
    monkeypatch.setattr(runtime_module, "connect_redis", lambda: _FakeRedis({}))
    monkeypatch.setattr(runtime_module, "refresh_all_timeframe_payload", lambda _repo_root: {"ran": False})
    monkeypatch.setattr(
        runtime_module,
        "checkpoint_retention_status",
        lambda **_kwargs: {"checkpoint_count": 0, "checkpoint_total_size_gb": 0.0, "checkpoint_dir_size_bytes": 0},
    )
    monkeypatch.setattr(
        runtime_module,
        "build_resource_status",
        lambda **_kwargs: {"bottleneck_reason": "NATIVE_CYCLE_TIMEOUT_1s"},
    )
    monkeypatch.setattr(
        runtime_module,
        "build_persistent_runtime_status",
        lambda **kwargs: {
            "service_active": True,
            "pid": os.getpid(),
            "training_steps_total": kwargs["persistent_state"]["training_steps_total"],
            "training_steps_last_hour": 0,
            "last_training_blocker_reason": kwargs["persistent_state"]["last_training_blocker_reason"],
            "prediction_grid_rows": 10,
            "prediction_grid_expected_rows": 10,
        },
    )
    monkeypatch.setattr(
        runtime_module,
        "publish_persistent_payloads",
        lambda **kwargs: {"operator_dashboard_payload.json": {"trainer": kwargs["persistent"]}},
    )

    payloads = runtime_module.run_one_persistent_cycle(paths=paths, max_rows=64, run_training=True)
    state = json.loads(paths.state_path.read_text(encoding="utf-8"))

    assert state["training_steps_total"] == 0
    assert state["last_training_blocker_reason"] == "NATIVE_CYCLE_TIMEOUT_1s"
    assert state["step_events"][-1]["heartbeat_only"] is True
    assert payloads["operator_dashboard_payload.json"]["trainer"]["last_training_blocker_reason"] == "NATIVE_CYCLE_TIMEOUT_1s"


def test_publish_persistent_payloads_merges_current_runtime_liveness_fields(tmp_path: Path, monkeypatch) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )
    persistent = {
        "service_active": True,
        "pid": os.getpid(),
        "uptime_seconds": 30,
        "training_steps_total": 7,
        "training_steps_last_hour": 4,
        "prediction_grid_rows": 10,
        "prediction_grid_expected_rows": 10,
        "blocked_prediction_rows": 2,
        "worker_health_status": "HEALTHY",
        "trainer_liveness_status": "HEALTHY",
        "heartbeat_age_seconds": 1.0,
        "last_batch_age_seconds": 1.0,
        "last_prediction_age_seconds": 1.0,
    }

    publish_persistent_payloads(
        paths=paths,
        persistent=persistent,
        resource={"bottleneck_reason": "DATASET_TOO_SMALL"},
        checkpoint={"checkpoint_count": 1, "checkpoint_total_size_gb": 0.0, "checkpoint_dir_size_bytes": 1},
        attribution={},
        guard={"status": "TRIAL_ACTIVE", "drawdown_guard_reason": "DRAWDOWN_GUARD_NOT_BREACHED"},
        trainer_result=None,
        all_timeframe_refresh={"ran": False},
    )

    runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )

    assert runtime["generated_utc"].endswith("Z")
    assert runtime["current_status_age_seconds"] == 0
    assert runtime["worker_health_status"] == "HEALTHY"
    assert runtime["trainer_liveness_status"] == "HEALTHY"
    assert runtime["heartbeat_age_seconds"] == 1.0
    assert runtime["prediction_grid_current"] is True


def test_publish_persistent_payloads_overwrites_stale_checkpoint_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    paths.operator_dir.mkdir(parents=True, exist_ok=True)
    (paths.operator_dir / "native_trainer_runtime_status.json").write_text(
        json.dumps(
            {
                "checkpoint_id": "v2_hybrid_ckpt_old",
                "checkpoint_path": ".local_models/v2_native_rl_masa_ppo/v2_hybrid_ckpt_old.weights.npz",
                "checkpoint_hash": "old_hash",
                "checkpoint_reload_verified": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )

    class _TrainerResult:
        predictions = [{"prediction_id": "pred_1"}]
        status = {"checkpoint_id": "v2_hybrid_ckpt_new"}
        metrics = {
            "training": {
                "status": "TRAINED",
                "training_steps": 2,
                "train_rows": 1,
                "validation_rows": 0,
                "metrics": {
                    "trusted_rows_loaded": 1,
                    "feedback_rows_entered_batch": 1,
                    "optimizer_steps_this_cycle": 2,
                    "optimizer_steps_last_hour": 2,
                    "optimizer_steps_total": 2,
                    "parameter_hash_before": "before",
                    "parameter_hash_after": "after",
                    "weight_delta_norm": 0.1,
                    "checkpoint_weight_blob_written": True,
                    "checkpoint_path": ".local_models/v2_native_rl_masa_ppo/v2_hybrid_ckpt_new.weights.npz",
                    "checkpoint_hash": "new_hash",
                    "checkpoint_reload_verified": True,
                    "last_successful_weight_update_at": "2026-07-10T06:40:00Z",
                    "online_learning_status": "WEIGHTS_UPDATING",
                    "effective_trainer_mode": "ONLINE_PAPER_LEARNING",
                },
            }
        }

    publish_persistent_payloads(
        paths=paths,
        persistent={
            "service_active": True,
            "pid": os.getpid(),
            "uptime_seconds": 30,
            "training_steps_total": 2,
            "training_steps_last_hour": 2,
            "prediction_grid_rows": 1,
            "prediction_grid_expected_rows": 1,
            "worker_health_status": "HEALTHY",
            "trainer_liveness_status": "HEALTHY",
            "heartbeat_age_seconds": 1.0,
            "last_batch_age_seconds": 1.0,
            "last_prediction_age_seconds": 1.0,
        },
        resource={"bottleneck_reason": None},
        checkpoint={"checkpoint_count": 1, "checkpoint_total_size_gb": 0.0, "checkpoint_dir_size_bytes": 1},
        attribution={},
        guard={"status": "TRIAL_ACTIVE", "drawdown_guard_reason": "DRAWDOWN_GUARD_NOT_BREACHED"},
        trainer_result=_TrainerResult(),
        all_timeframe_refresh={"ran": False},
    )

    runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )
    assert runtime["checkpoint_id"] == "v2_hybrid_ckpt_new"
    assert runtime["checkpoint_path"] == ".local_models/v2_native_rl_masa_ppo/v2_hybrid_ckpt_new.weights.npz"
    assert runtime["checkpoint_hash"] == "new_hash"
    assert runtime["checkpoint_weight_blob_written"] is True
    assert runtime["checkpoint_reload_verified"] is True


def test_publish_persistent_payloads_does_not_reuse_stale_trusted_rows_when_feedback_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 10,
                "expected_prediction_count": 10,
                "current_prediction_count": 10,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
            }
        ),
        encoding="utf-8",
    )
    paths.operator_dir.mkdir(parents=True, exist_ok=True)
    (paths.operator_dir / "native_trainer_runtime_status.json").write_text(
        json.dumps(
            {
                "latest_training_metrics": {
                    "status": "TRAINING_NOT_RUN",
                    "metrics": {
                        "trusted_rows_loaded": 402,
                        "training_trusted_rows": 402,
                    },
                },
                "trusted_rows_loaded": 402,
                "online_learning_status": "BLOCKED_NO_DURABLE_WEIGHT_UPDATE",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )
    monkeypatch.setattr(runtime_module, "connect_redis", lambda: None)

    publish_persistent_payloads(
        paths=paths,
        persistent={
            "service_active": True,
            "pid": os.getpid(),
            "uptime_seconds": 30,
            "training_steps_total": 7,
            "training_steps_last_hour": 0,
            "prediction_grid_rows": 10,
            "prediction_grid_expected_rows": 10,
            "worker_health_status": "HEALTHY",
            "trainer_liveness_status": "HEALTHY",
            "heartbeat_age_seconds": 1.0,
            "last_batch_age_seconds": 1.0,
            "last_prediction_age_seconds": 1.0,
        },
        resource={"bottleneck_reason": "NO_TRUSTED_FEEDBACK_ROWS"},
        checkpoint={"checkpoint_count": 1, "checkpoint_total_size_gb": 0.0, "checkpoint_dir_size_bytes": 1},
        attribution={},
        guard={"status": "TRIAL_ACTIVE", "drawdown_guard_reason": "DRAWDOWN_GUARD_NOT_BREACHED"},
        trainer_result=None,
        all_timeframe_refresh={"ran": False},
    )

    runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )
    assert runtime["trusted_rows_loaded"] == 0
    assert runtime["latest_training_metrics"]["metrics"]["trusted_rows_loaded"] == 0
    assert runtime["latest_training_metrics"]["metrics"]["feedback_source_status"] == "REDIS_UNAVAILABLE"
    assert runtime["online_learning_status"] == "BLOCKED_NO_TRUSTED_FEEDBACK"
    assert runtime["effective_trainer_mode"] == "INFERENCE_ONLY"


def test_current_feedback_metrics_require_dereferenceable_trust_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis(
            {
                "v2:trainer:feedback:outcomes": [
                    _trusted_feedback_row(feature_snapshot_id="missing-snapshot")
                ],
            }
        ),
    )

    metrics = runtime_module.latest_training_metrics_from_current_feedback(fail_closed=True)

    assert metrics is not None
    assert metrics["metrics"]["trusted_rows_loaded"] == 0
    assert metrics["metrics"]["rows_rejected_by_reason"] == {"entry_feature_snapshot_not_found": 1}


def test_current_feedback_metrics_accept_embedded_trust_snapshot_when_archive_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis(
            {
                "v2:trainer:feedback:outcomes": [
                    _trusted_feedback_row(
                        feature_snapshot_id="feat-1",
                        embedded_snapshot=_feature_snapshot("feat-1"),
                    )
                ],
            }
        ),
    )

    metrics = runtime_module.latest_training_metrics_from_current_feedback(fail_closed=True)

    assert metrics is not None
    assert metrics["metrics"]["trusted_rows_loaded"] == 1
    assert metrics["metrics"]["rows_rejected_by_reason"] == {}


def test_current_feedback_metrics_reject_invalid_paper_admission_quarantine(monkeypatch) -> None:
    row = _trusted_feedback_row(
        feature_snapshot_id="feat-1",
        embedded_snapshot=_feature_snapshot("feat-1"),
    )
    row["trainer_consumable"] = False
    row["quarantine_reason"] = "P0_ENTRY_GATE_BLOCKED_NOT_EXPLORATION_RELAXABLE"
    row["quarantine_reasons"] = ["P0_ENTRY_GATE_BLOCKED_NOT_EXPLORATION_RELAXABLE"]

    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis({"v2:trainer:feedback:outcomes": [row]}),
    )

    metrics = runtime_module.latest_training_metrics_from_current_feedback(fail_closed=True)

    assert metrics is not None
    assert metrics["metrics"]["trusted_rows_loaded"] == 0
    assert metrics["metrics"]["rows_rejected_by_reason"] == {
        "P0_ENTRY_GATE_BLOCKED_NOT_EXPLORATION_RELAXABLE": 1
    }


def test_current_feedback_metrics_reject_mismatched_embedded_trust_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis(
            {
                "v2:trainer:feedback:outcomes": [
                    _trusted_feedback_row(
                        feature_snapshot_id="feat-1",
                        embedded_snapshot=_feature_snapshot("other-feat"),
                    )
                ],
            }
        ),
    )

    metrics = runtime_module.latest_training_metrics_from_current_feedback(fail_closed=True)

    assert metrics is not None
    assert metrics["metrics"]["trusted_rows_loaded"] == 0
    assert metrics["metrics"]["rows_rejected_by_reason"] == {"entry_feature_snapshot_id_mismatch": 1}


def test_current_feedback_metrics_publish_quarantine_rejection_reasons(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis(
            {
                "v2:trainer:feedback:outcomes": [],
                "v2:trainer:feedback:outcomes:quarantine": [
                    {
                        "trust_reconstruction_rejection_reasons": [
                            "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND"
                        ],
                        "audit_quality_rejection_reasons": [
                            "MISSING_EXPECTED_SLIPPAGE_BPS"
                        ],
                    }
                ],
            }
        ),
    )

    metrics = runtime_module.latest_training_metrics_from_current_feedback(fail_closed=True)

    assert metrics is not None
    assert metrics["metrics"]["trusted_rows_loaded"] == 0
    assert metrics["metrics"]["rows_rejected_by_reason"] == {
        "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND": 1,
        "MISSING_EXPECTED_SLIPPAGE_BPS": 1,
    }


def test_persistent_payloads_expose_latest_completed_training_metrics(tmp_path: Path, monkeypatch) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 403,
                "expected_prediction_count": 403,
                "current_prediction_count": 403,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 403,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )

    class _TrainerResult:
        status = {"checkpoint_id": "unit_ckpt"}
        metrics = {
            "training": {
                "status": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINING_STEP_RAN",
                "device": "cuda:0",
                "cuda_active": True,
                "cuda_claim_verified": True,
                "gpu_name": "unit-gpu",
                "batch_size": 403,
                "training_steps": 256,
                "train_rows": 323,
                "validation_rows": 80,
                "loss_before": 115.59666443,
                "loss_after": 110.44487,
                "action_distribution": {"0": 403},
                "metrics": {
                    "selected_examples": 403,
                    "available_examples": 403,
                    "actual_batch_size": 403,
                    "target_batch_size": 32768,
                    "parameter_finite_guard_active": True,
                    "non_finite_parameter_value_count_sanitized": 0,
                },
            }
        }

    persistent_status = build_persistent_runtime_status(
        paths=paths,
        trainer_result=_TrainerResult(),
        persistent_state={
            "started_ts": time.time() - 10,
            "training_steps_total": 256,
            "step_events": [{"ts": time.time(), "training_steps": 256, "prediction_rows": 403}],
        },
        resource={"bottleneck_reason": "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH"},
        checkpoint={"latest_checkpoint_id": "unit_ckpt"},
    )
    assert persistent_status["latest_training_metrics"]["training_steps"] == 256
    assert persistent_status["latest_training_metrics"]["metrics"]["parameter_finite_guard_active"] is True

    publish_persistent_payloads(
        paths=paths,
        persistent={
            **persistent_status,
            "service_active": True,
            "pid": os.getpid(),
            "uptime_seconds": 30,
            "worker_health_status": "HEALTHY",
            "trainer_liveness_status": "HEALTHY",
            "heartbeat_age_seconds": 1.0,
            "last_batch_age_seconds": 1.0,
            "last_prediction_age_seconds": 1.0,
        },
        resource={
            "bottleneck_reason": "APPROVED_SAMPLE_SET_BELOW_TARGET_BATCH",
            "batch_size": 403,
            "target_batch_size": 32768,
        },
        checkpoint={"checkpoint_count": 1, "checkpoint_total_size_gb": 0.0, "checkpoint_dir_size_bytes": 1},
        attribution={},
        guard={"status": "TRIAL_ACTIVE", "drawdown_guard_reason": "DRAWDOWN_GUARD_NOT_BREACHED"},
        trainer_result=_TrainerResult(),
        all_timeframe_refresh={"ran": False},
    )

    runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )
    latest = runtime["latest_training_metrics"]
    assert latest["training_steps"] == 256
    assert latest["train_rows"] == 323
    assert latest["validation_rows"] == 80
    assert latest["metrics"]["selected_examples"] == 403
    assert latest["metrics"]["parameter_finite_guard_active"] is True


def test_publish_persistent_payloads_preserves_partial_prediction_grid_status(tmp_path: Path, monkeypatch) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    paths.operator_dir.mkdir(parents=True, exist_ok=True)
    (paths.operator_dir / "native_trainer_runtime_status.json").write_text(
        json.dumps(
            {
                "prediction_grid_expected_rows": 10,
                "current_prediction_count": 8,
                "missing_prediction_rows_count": 2,
                "stale_prediction_rows_count": 0,
                "prediction_coverage_status": "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS",
                "missing_prediction_symbols": ["OLDUSDT"],
                "missing_prediction_timeframes_by_symbol": {"OLDUSDT": ["1m", "5m"]},
            }
        ),
        encoding="utf-8",
    )
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 10,
                "expected_prediction_count": 10,
                "current_prediction_count": 9,
                "missing_prediction_rows_count": 1,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 8,
                "coverage_status": "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS",
                "actionability_status": "PAPER_ACTIONABILITY_BLOCKED_BY_GATES",
                "missing_prediction_symbols": ["HIGHUSDT"],
                "missing_prediction_timeframes_by_symbol": {"HIGHUSDT": ["4h"]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )

    publish_persistent_payloads(
        paths=paths,
        persistent={
            "service_active": True,
            "pid": os.getpid(),
            "uptime_seconds": 30,
            "training_steps_total": 7,
            "training_steps_last_hour": 4,
            "prediction_grid_rows": 10,
            "prediction_grid_expected_rows": 10,
            "worker_health_status": "HEALTHY",
            "trainer_liveness_status": "HEALTHY",
            "heartbeat_age_seconds": 1.0,
            "last_batch_age_seconds": 1.0,
            "last_prediction_age_seconds": 1.0,
        },
        resource={"bottleneck_reason": "DATASET_TOO_SMALL"},
        checkpoint={"checkpoint_count": 1, "checkpoint_total_size_gb": 0.0, "checkpoint_dir_size_bytes": 1},
        attribution={},
        guard={"status": "TRIAL_ACTIVE", "drawdown_guard_reason": "DRAWDOWN_GUARD_NOT_BREACHED"},
        trainer_result=None,
        all_timeframe_refresh={"ran": False},
    )

    runtime = json.loads(
        (paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8")
    )
    assert runtime["prediction_grid_current"] is False
    assert runtime["current_prediction_count"] == 9
    assert runtime["missing_prediction_rows_count"] == 1
    assert runtime["prediction_coverage_status"] == "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS"
    assert runtime["prediction_actionability_status"] == "PAPER_ACTIONABILITY_BLOCKED_BY_GATES"
    assert runtime["missing_prediction_symbols"] == ["HIGHUSDT"]
    assert runtime["missing_prediction_timeframes_by_symbol"] == {"HIGHUSDT": ["4h"]}


def test_run_one_persistent_cycle_heartbeats_when_no_trusted_examples(tmp_path: Path, monkeypatch) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 10,
                "expected_prediction_count": 10,
                "blocked_prediction_rows_count": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )
    monkeypatch.setattr(runtime_module, "connect_redis", lambda: None)
    monkeypatch.setattr(
        runtime_module,
        "refresh_all_timeframe_payload",
        lambda _repo_root: {"ran": False, "status": "SKIPPED_TEST"},
    )

    def _no_trusted_examples(**_kwargs):
        raise RuntimeError("no trusted examples built")

    monkeypatch.setattr(runtime_module, "run_native_training_cycle", _no_trusted_examples)

    runtime_module.run_one_persistent_cycle(paths=paths, max_rows=64, risk_caps_configured=True, run_training=True)

    state = json.loads(paths.state_path.read_text(encoding="utf-8"))
    runtime = json.loads((paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8"))
    resource = json.loads((paths.operator_dir / "native_trainer_gpu_status.json").read_text(encoding="utf-8"))

    assert state["training_steps_total"] == 0
    assert state["last_training_blocker_reason"] == "NO_TRUSTED_EXAMPLES_BUILT"
    assert state["step_events"][-1]["heartbeat_only"] is True
    assert runtime["generated_utc"].endswith("Z")
    assert runtime["training_loop_active"] is True
    assert runtime["training_cycle_blocked_reason"] == "NO_TRUSTED_EXAMPLES_BUILT"
    assert resource["bottleneck_reason"] == "NO_TRUSTED_EXAMPLES_BUILT"


def test_run_one_persistent_cycle_keeps_inference_active_with_empty_feedback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 1,
                "expected_prediction_count": 1,
                "current_prediction_count": 1,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )
    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis(
            {
                "v2:trainer:feedback:outcomes": [],
                "v2:paper:ledger": {},
                runtime_module.TRIAL_STATUS_REDIS_KEY: {},
            }
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "refresh_all_timeframe_payload",
        lambda _repo_root: {"ran": False, "status": "SKIPPED_TEST"},
    )
    monkeypatch.setattr(runtime_module, "gpu_status_from_nvidia_smi", lambda: {"available": False})
    monkeypatch.setattr(runtime_module, "memory_status", lambda: {"ram_total_gb": 64.0, "ram_used_gb": 12.0})
    monkeypatch.setattr(runtime_module, "cpu_utilization_percent", lambda: 5.0)
    calls = {"count": 0}

    class _TrainerResult:
        predictions = [{"prediction_id": "pred_1"}]
        status = {
            "checkpoint_id": "ckpt_1",
            "cuda_cpu_resource_utilization": {
                "target_batch_size": 64,
                "actual_batch_size": 0,
                "throughput_predictions_per_second": 1.0,
            },
        }
        metrics = {
            "training": {
                "status": "NO_TRUSTED_TRAINING_ROWS",
                "training_steps": 0,
                "train_rows": 0,
                "validation_rows": 0,
                "batch_size": 64,
                "metrics": {
                    "trusted_rows_loaded": 0,
                    "training_trusted_rows": 0,
                    "optimizer_steps_this_cycle": 0,
                    "optimizer_steps_total": 0,
                    "rows_rejected_by_reason": {"entry_feature_snapshot_not_found": 1},
                    "loss_before": None,
                    "loss_after": None,
                    "online_learning_status": "BLOCKED_NO_TRUSTED_FEEDBACK",
                    "effective_trainer_mode": "INFERENCE_ONLY",
                },
            }
        }

    def _fake_native_cycle(**_kwargs):
        calls["count"] += 1
        return _TrainerResult()

    monkeypatch.setattr(runtime_module, "run_native_training_cycle", _fake_native_cycle)

    runtime_module.run_one_persistent_cycle(paths=paths, max_rows=64, risk_caps_configured=True, run_training=True)

    state = json.loads(paths.state_path.read_text(encoding="utf-8"))
    runtime = json.loads((paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8"))

    assert calls["count"] == 1
    assert state["training_steps_total"] == 0
    assert state["last_training_blocker_reason"] == "NO_TRUSTED_FEEDBACK_ROWS"
    assert runtime["prediction_publication_status"] == "ACTIVE"
    assert runtime["online_learning_status"] == "BLOCKED_NO_TRUSTED_FEEDBACK"
    assert runtime["effective_trainer_mode"] == "INFERENCE_ONLY"
    assert runtime["trusted_rows_loaded"] == 0
    assert runtime["optimizer_steps_this_cycle"] == 0
    assert runtime["optimizer_steps_total"] == 0
    assert runtime["rows_rejected_by_reason"] == {"entry_feature_snapshot_not_found": 1}
    assert runtime["loss_before"] is None
    assert runtime["loss_after"] is None


def test_run_one_persistent_cycle_merges_quarantine_rejections_when_result_has_none(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PersistentTrainerPaths(repo_root=tmp_path)
    prediction_path = paths.public_root / runtime_module.PREDICTION_REL
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_text(
        json.dumps(
            {
                "prediction_rows_count": 1,
                "expected_prediction_count": 1,
                "current_prediction_count": 1,
                "missing_prediction_rows_count": 0,
                "stale_prediction_rows_count": 0,
                "blocked_prediction_rows_count": 0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_module,
        "systemctl_show",
        lambda unit: {"ActiveState": "active", "MainPID": str(os.getpid()), "UnitFileState": "masked"}
        if unit == runtime_module.LEGACY_BRIDGE_UNIT
        else {"ActiveState": "active", "MainPID": str(os.getpid())},
    )
    monkeypatch.setattr(
        runtime_module,
        "connect_redis",
        lambda: _FakeRedis(
            {
                "v2:trainer:feedback:outcomes": [],
                "v2:trainer:feedback:outcomes:quarantine": [
                    {
                        "trust_reconstruction_rejection_reasons": [
                            "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND"
                        ],
                        "audit_quality_rejection_reasons": [
                            "MISSING_EXPECTED_SLIPPAGE_BPS"
                        ],
                    }
                ],
                "v2:paper:ledger": {},
                runtime_module.TRIAL_STATUS_REDIS_KEY: {},
            }
        ),
    )
    monkeypatch.setattr(
        runtime_module,
        "refresh_all_timeframe_payload",
        lambda _repo_root: {"ran": False, "status": "SKIPPED_TEST"},
    )
    monkeypatch.setattr(runtime_module, "gpu_status_from_nvidia_smi", lambda: {"available": False})
    monkeypatch.setattr(runtime_module, "memory_status", lambda: {"ram_total_gb": 64.0, "ram_used_gb": 12.0})
    monkeypatch.setattr(runtime_module, "cpu_utilization_percent", lambda: 5.0)

    class _TrainerResult:
        predictions = [{"prediction_id": "pred_1"}]
        status = {
            "checkpoint_id": "ckpt_1",
            "cuda_cpu_resource_utilization": {
                "target_batch_size": 64,
                "actual_batch_size": 0,
                "throughput_predictions_per_second": 1.0,
            },
        }
        metrics = {
            "training": {
                "status": "NO_TRUSTED_TRAINING_ROWS",
                "training_steps": 0,
                "train_rows": 0,
                "validation_rows": 0,
                "batch_size": 64,
                "metrics": {
                    "trusted_rows_loaded": 0,
                    "training_trusted_rows": 0,
                    "optimizer_steps_this_cycle": 0,
                    "optimizer_steps_total": 0,
                    "rows_rejected_by_reason": {},
                    "loss_before": None,
                    "loss_after": None,
                    "online_learning_status": "BLOCKED_NO_TRUSTED_FEEDBACK",
                    "effective_trainer_mode": "INFERENCE_ONLY",
                },
            }
        }

    monkeypatch.setattr(runtime_module, "run_native_training_cycle", lambda **_kwargs: _TrainerResult())

    runtime_module.run_one_persistent_cycle(paths=paths, max_rows=64, risk_caps_configured=True, run_training=True)

    runtime = json.loads((paths.operator_dir / "native_trainer_runtime_status.json").read_text(encoding="utf-8"))

    assert runtime["online_learning_status"] == "BLOCKED_NO_TRUSTED_FEEDBACK"
    assert runtime["effective_trainer_mode"] == "INFERENCE_ONLY"
    assert runtime["trusted_rows_loaded"] == 0
    assert runtime["rows_rejected_by_reason"] == {
        "ENTRY_FEATURE_SNAPSHOT_NOT_FOUND": 1,
        "MISSING_EXPECTED_SLIPPAGE_BPS": 1,
    }


def test_paper_exploration_artifacts_select_paper_only_b_grade_candidates() -> None:
    prediction_row = {
        "prediction_id": "pred_1",
        "signal_id": "sig_1",
        "decision_id": "decision_1",
        "feature_snapshot_id": "fs_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": "2026-06-22T10:00:00Z",
        "decision_time": "2026-06-22T10:00:01Z",
        "available_at": "2026-06-22T10:00:00Z",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "model_version": "unit",
        "checkpoint_id": "ckpt",
        "source_hashes": {"features": "hash"},
        "expected_move_after_cost_bps": 12.0,
        "confidence_calibrated": 0.51,
        "data_coverage_percent": 90.0,
        "market_state_integrity_score": 95.0,
        "actual_observed_spread_entry_bps": 1.0,
        "stale_feature_count": 0,
        "paper_fill_allowed": False,
        "paper_fill_gate_block_reasons": ["confidence_below_threshold"],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }

    artifacts = runtime_module.build_paper_exploration_artifacts(
        prediction_public={"prediction_rows": [prediction_row]},
        generated_utc="2026-06-22T10:00:02Z",
    )

    tier = artifacts["paper_exploration_tier_status.json"]
    risk = artifacts["paper_exploration_risk_budget_status.json"]
    assert tier["status"] == "ACTIVE_PAPER_ONLY_EXPLORATION_SELECTION"
    assert tier["tiers"]["B_GRADE_EXPLORATION_PAPER"] == 1
    assert tier["paper_only"] is True
    assert tier["routes_to_live"] is False
    assert risk["fixed_usdt_sizing"] is False
    assert risk["exchange_mutation"] is False


def test_confidence_artifacts_report_reachability_without_fake_holdout_calibration(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "_redis_json_list", lambda _key: [])

    artifacts = runtime_module.build_confidence_artifacts(
        prediction_public={
            "prediction_rows": [
                {
                    "confidence_raw": 0.45,
                    "confidence_calibrated": 0.61,
                    "data_coverage_percent": 90.0,
                    "missing_feature_count": 2,
                    "stale_feature_count": 0,
                }
            ]
        },
        generated_utc="2026-06-22T10:00:02Z",
    )

    reachability = artifacts["confidence_gate_reachability_status.json"]
    calibration = artifacts["trusted_confidence_calibration_status.json"]
    assert reachability["status"] == "CONFIDENCE_GATE_REACHABLE_BY_CURRENT_CALIBRATION"
    assert reachability["rows_capable_of_reaching_current_gate"] == 1
    assert calibration["status"] == "BLOCKED_NO_CONFIDENCE_OUTCOME_JOIN_FOR_TRUSTED_HOLDOUT"


def test_confidence_artifacts_compute_brier_ece_from_trusted_feedback(monkeypatch) -> None:
    row1 = _trusted_feedback_row(feature_snapshot_id="feat-1")
    row1.update(
        {
            "feature_snapshot_id": "feat-1",
            "confidence_calibrated": 0.75,
            "expected_move_after_cost_bps": 18.0,
            "realized_net_pnl_bps": 20.0,
            "action_was_profitable": True,
            "trade_outcome": "WIN",
        }
    )
    row2 = _trusted_feedback_row(feature_snapshot_id="feat-2")
    row2.update(
        {
            "prediction_id": "pred-2",
            "signal_id": "sig-2",
            "feature_snapshot_id": "feat-2",
            "confidence_calibrated": 0.25,
            "expected_move_after_cost_bps": -12.0,
            "realized_net_pnl_bps": -10.0,
            "action_was_profitable": False,
            "trade_outcome": "LOSS",
        }
    )
    monkeypatch.setattr(runtime_module, "_redis_json_list", lambda _key: [row1, row2])

    artifacts = runtime_module.build_confidence_artifacts(
        prediction_public={"prediction_rows": []},
        generated_utc="2026-06-22T10:00:02Z",
    )

    calibration = artifacts["trusted_confidence_calibration_status.json"]
    reliability = artifacts["confidence_reliability_matrix.json"]
    assert calibration["status"] == "ACTIVE_TRUSTED_CONFIDENCE_OUTCOME_CALIBRATION"
    assert calibration["confidence_outcome_join_available"] is True
    assert calibration["trusted_confidence_outcome_rows"] == 2
    assert abs(calibration["brier_score"] - 0.0625) < 1e-9
    assert abs(calibration["ece"] - 0.25) < 1e-9
    assert reliability["sample_count"] == 2
    assert len(reliability["buckets"]) == 2


def test_confidence_artifacts_activate_from_trusted_replay_holdout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(runtime_module, "_redis_json_list", lambda _key: [])

    def _fake_holdout(*, repo_root, model_dir, generated_utc):
        assert repo_root == tmp_path
        assert model_dir == tmp_path / ".local_models/v2_native_rl_masa_ppo"
        return {
            "schema_version": "trusted_replay_holdout_calibration_status_v1",
            "generated_utc": generated_utc,
            "status": "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION",
            "calibration_source": "TRUSTED_REPLAY_TEMPORAL_HOLDOUT_CURRENT_CHECKPOINT_FORWARD",
            "confidence_outcome_join_available": True,
            "evaluated_rows": 2,
            "trusted_holdout_rows": 2,
            "manifest_holdout_rows": 4500,
            "checkpoint_id": "ckpt_holdout",
            "checkpoint_hash": "hash_after",
            "future_labels_used_as_features": False,
            "uses_expected_move_as_realized_reward": False,
            "rows_rejected_by_reason": {},
            "_calibration_rows": [
                {"confidence": 0.80, "outcome": 1.0},
                {"confidence": 0.20, "outcome": 0.0},
            ],
        }

    monkeypatch.setattr(
        runtime_module,
        "build_trusted_replay_holdout_calibration",
        _fake_holdout,
    )

    artifacts = runtime_module.build_confidence_artifacts(
        prediction_public={"prediction_rows": []},
        generated_utc="2026-06-22T10:00:02Z",
        repo_root=tmp_path,
        model_dir=tmp_path / ".local_models/v2_native_rl_masa_ppo",
    )

    calibration = artifacts["trusted_confidence_calibration_status.json"]
    reliability = artifacts["confidence_reliability_matrix.json"]
    holdout = artifacts["trusted_replay_holdout_calibration_status.json"]
    assert calibration["status"] == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
    assert calibration["trusted_holdout_rows"] == 2
    assert calibration["trusted_replay_holdout_evaluated_rows"] == 2
    assert calibration["trusted_replay_holdout_manifest_rows"] == 4500
    assert calibration["trusted_replay_holdout_source"] == "TRUSTED_REPLAY_TEMPORAL_HOLDOUT_CURRENT_CHECKPOINT_FORWARD"
    assert calibration["future_labels_used_as_features"] is False
    assert calibration["uses_expected_move_as_realized_reward"] is False
    assert abs(calibration["brier_score"] - 0.04) < 1e-9
    assert abs(calibration["ece"] - 0.20) < 1e-9
    assert reliability["sample_count"] == 2
    assert reliability["reason"] == "confidence reliability buckets computed from trusted replay holdout rows"
    assert "_calibration_rows" not in holdout


def test_confidence_artifacts_reuse_recent_holdout_without_rescanning(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "_redis_json_list", lambda _key: [])

    def _unexpected_holdout(**_kwargs):
        raise AssertionError("holdout calibration should be cadence-reused")

    monkeypatch.setattr(
        runtime_module,
        "build_trusted_replay_holdout_calibration",
        _unexpected_holdout,
    )

    previous = {
        "schema_version": "trusted_confidence_calibration_status_v1",
        "generated_utc": "2026-06-22T10:00:00Z",
        "status": "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION",
        "trusted_holdout_rows": 149,
        "trusted_replay_holdout_status": "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION",
        "trusted_replay_holdout_evaluated_rows": 149,
        "trusted_replay_holdout_source": "TRUSTED_REPLAY_TEMPORAL_HOLDOUT_CURRENT_CHECKPOINT_FORWARD",
        "trusted_replay_holdout_checkpoint_hash": "hash_before",
        "brier_score": 0.04,
        "ece": 0.2,
    }

    artifacts = runtime_module.build_confidence_artifacts(
        prediction_public={"prediction_rows": []},
        generated_utc="2026-06-22T10:01:00Z",
        run_holdout_calibration=False,
        previous_trusted_confidence_calibration=previous,
        holdout_calibration_reuse_age_seconds=60.0,
        holdout_calibration_min_interval_seconds=900,
    )

    calibration = artifacts["trusted_confidence_calibration_status.json"]
    assert calibration["status"] == "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION"
    assert calibration["trusted_holdout_rows"] == 149
    assert calibration["trusted_replay_holdout_checkpoint_hash"] == "hash_before"
    assert calibration["holdout_calibration_reused"] is True
    assert calibration["holdout_calibration_reuse_age_seconds"] == 60.0
    assert calibration["holdout_calibration_min_interval_seconds"] == 900
    assert calibration["brier_score"] == 0.04
    assert calibration["ece"] == 0.2


def test_holdout_calibration_due_respects_recent_active_publish() -> None:
    previous = {
        "generated_utc": "2026-06-22T10:00:00Z",
        "status": "ACTIVE_TRUSTED_HOLDOUT_CALIBRATION",
    }

    due, age = runtime_module.holdout_calibration_due(
        previous,
        generated_utc="2026-06-22T10:10:00Z",
        min_interval_seconds=900,
    )
    assert due is False
    assert age == 600.0

    due, age = runtime_module.holdout_calibration_due(
        previous,
        generated_utc="2026-06-22T10:16:00Z",
        min_interval_seconds=900,
    )
    assert due is True
    assert age == 960.0


def test_selected_action_outcome_uses_realized_direction_not_trade_outcome_label() -> None:
    assert runtime_module._selected_action_outcome("long", 5.0) == 1.0
    assert runtime_module._selected_action_outcome("long", -5.0) == 0.0
    assert runtime_module._selected_action_outcome("short", -5.0) == 1.0
    assert runtime_module._selected_action_outcome("short", 5.0) == 0.0
    assert runtime_module._selected_action_outcome("hold", 2.0) == 1.0
    assert runtime_module._selected_action_outcome("hold", 12.0) == 0.0
    assert runtime_module._selected_action_outcome("close_long", 5.0) is None


def test_trainer_quality_artifact_computes_expected_move_mae_and_calibration(monkeypatch) -> None:
    row1 = _trusted_feedback_row(feature_snapshot_id="feat-1")
    row1.update(
        {
            "feature_snapshot_id": "feat-1",
            "confidence_calibrated": 0.75,
            "expected_move_after_cost_bps": 18.0,
            "realized_net_pnl_bps": 20.0,
            "directional_outcome": "UP",
            "action_was_profitable": True,
            "trade_outcome": "WIN",
        }
    )
    row2 = _trusted_feedback_row(feature_snapshot_id="feat-2")
    row2.update(
        {
            "prediction_id": "pred-2",
            "signal_id": "sig-2",
            "feature_snapshot_id": "feat-2",
            "selected_action": "short",
            "confidence_calibrated": 0.25,
            "expected_move_after_cost_bps": -12.0,
            "realized_net_pnl_bps": -10.0,
            "directional_outcome": "UP",
            "action_was_profitable": False,
            "trade_outcome": "LOSS",
        }
    )
    monkeypatch.setattr(runtime_module, "_redis_json_list", lambda _key: [row1, row2])

    quality = runtime_module.build_trainer_quality_artifact(
        generated_utc="2026-06-22T10:00:02Z"
    )

    assert quality["status"] == "ACTIVE_REALIZED_PAPER_QUALITY_METRICS"
    assert quality["sample_count"] == 2
    assert quality["expected_move_mae"] == 2.0
    assert quality["expected_move_mae_sample_count"] == 2
    assert quality["calibration_sample_count"] == 2
    assert abs(quality["brier_score"] - 0.0625) < 1e-9
    assert abs(quality["ece"] - 0.25) < 1e-9
