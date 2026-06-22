from __future__ import annotations

import json
import os
import time
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

    def _fake_run_hybrid_trainer_cycle(*, config, io, publish, replay_buffer):
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
