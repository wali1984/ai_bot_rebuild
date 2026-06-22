from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.native_trainer import runtime_truth as rt
from v2.backend.app.services.native_trainer.runtime_truth import (
    ALL_TF_STATUS_REL,
    LIVE_GATE_REL,
    NativeTrainerRuntimePaths,
    PAPER_TRIAL_REL,
    PARITY_REL,
    PORTFOLIO_REL,
    PREDICTION_STATUS_REL,
    RUNTIME_PAGES_REL,
    RUNTIME_TRUTH_REL,
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
            "blocked_prediction_rows_count": 0,
        },
    )
    _write_minimal_runtime_sources(public)
    _patch_runtime_truth_side_effects(monkeypatch)

    payloads = build_native_trainer_runtime_payloads(
        NativeTrainerRuntimePaths(repo_root=repo, public_root=public)
    )
    runtime = payloads["native_trainer_runtime_status.json"]

    assert runtime["predictions_by_symbol_count"] == 90
    assert runtime["predictions_by_symbol_display_scope"] == "FULL_SCROLLABLE_TRAINER_GRID"
    assert len(runtime["predictions_by_symbol"]) == 90
    assert runtime["predictions_by_symbol"][-1]["symbol"] == "SYM089USDT"
    assert runtime["prediction_grid_current"] is True
    assert runtime["current_prediction_count"] == 90
    assert runtime["missing_prediction_rows_count"] == 0
    assert runtime["stale_prediction_rows_count"] == 0


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
