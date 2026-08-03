from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.v2_native_cuda_trainer_runtime_signal_burn_in_live_gate import main
from v2.backend.app.services.native_trainer.cuda_trainer_live_gate import (
    GATE_BLOCKED,
    GATE_READY,
    CudaTrainerLiveGatePaths,
    build_runtime_signal_gate,
    write_runtime_signal_gate_artifacts,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    CHECKPOINT_SOURCE,
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    TRAINER_SOURCE,
    TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
)


def _prediction(prediction_id: str, *, symbol: str = "BTCUSDT", timeframe: str = "1m") -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "generated_est": "2026-06-04T15:10:00-04:00",
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_action": "hold",
        "selected_action_index": 0,
        "action_labels": ["hold", "long", "short", "close_long", "close_short", "reduce", "hedge_reserved_fail_closed"],
        "action_probabilities": [0.72, 0.05, 0.04, 0.05, 0.04, 0.05, 0.05],
        "expected_move_bps": 4.0,
        "expected_move_after_cost_bps": -8.0,
        "confidence_raw": 0.62,
        "confidence_calibrated": 0.54,
        "confidence_calibration": "temperature_scaled",
        "policy_value": 0.1,
        "masa_signal": 0.2,
        "feature_snapshot_id": f"v2_fsnap_{symbol}_{timeframe}_cuda_test",
        "feature_tensor_id": f"v2_tensor_{prediction_id}",
        "data_coverage_percent": 100.0,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "market_state_id": f"mstate_{symbol}_{timeframe}",
        "market_state_integrity_score": 96.0,
        "valid_for_prediction": True,
        "valid_for_risk": True,
        "valid_for_orchestrator": True,
        "valid_for_paper": True,
        "missing_feature_names": [],
        "stale_feature_names": [],
        "source_availability_vector": [1, 1, 1],
        "feature_names": ["price_last", "paper_position_present", "ohlcv_close"],
        "source_labels": ["v2:market:prices", "v2:paper:positions", "v2:market:ohlcv"],
        "trainer_source": TRAINER_SOURCE,
        "model_source": MODEL_SOURCE,
        "checkpoint_source": CHECKPOINT_SOURCE,
        "checkpoint_id": "v2_hybrid_ckpt_test",
        "checkpoint_manifest_path": ".local_models/v2_native_rl_masa_ppo/v2_hybrid_ckpt_test.json",
        "model_id": "v2_hybrid_model_test",
        "model_device": "cuda:0",
        "cuda_active": True,
        "model_tensors_device_verified": True,
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
        "paper_fill_gate_block_reasons": ["confidence_below_threshold"],
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "exchange_mutation": False,
        "trainer_direct_trading": False,
    }


def _lineage(prediction_id: str, *, symbol: str = "BTCUSDT") -> dict[str, object]:
    decision_id = f"dec_{prediction_id}"
    risk_id = f"rd_{decision_id}"
    return {
        "trainer_prediction_record": {
            "prediction_id": prediction_id,
            "symbol": symbol,
            "feature_snapshot_id": f"v2_fsnap_{symbol}_1m_cuda_test",
            "model_version": MODEL_SOURCE,
        },
        "orchestrator_decision_record": {
            "decision_id": decision_id,
            "prediction_id": prediction_id,
            "feature_snapshot_id": f"v2_fsnap_{symbol}_1m_cuda_test",
            "symbol": symbol,
            "decision_action": "abstain",
            "decision_reason_code": "abstain_low_confidence",
            "live_blocked": True,
        },
        "risk_decision_record": {
            "risk_decision_id": risk_id,
            "decision_id": decision_id,
            "prediction_id": prediction_id,
            "feature_snapshot_id": f"v2_fsnap_{symbol}_1m_cuda_test",
            "symbol": symbol,
            "risk_action": "deny",
            "risk_reason_code": "deny_orchestrator_abstained",
            "live_blocked": True,
        },
        "paper_execution_ledger_entry": {
            "paper_trade_id": f"pt_{risk_id}",
            "risk_decision_id": risk_id,
            "decision_id": decision_id,
            "prediction_id": prediction_id,
            "symbol": symbol,
            "ledger_action": "record_deny",
            "ledger_reason_code": "mirror_deny_orchestrator_abstained",
            "live_blocked": True,
        },
        "paper_signal_lineage": {
            "trainer_prediction_id": prediction_id,
            "risk_decision_id": risk_id,
            "orchestrator_decision_id": decision_id,
            "selected_action": "hold",
            "expected_move_after_cost_bps": -8.0,
            "confidence_calibrated": 0.54,
            "data_coverage_percent": 100.0,
            "paper_fill_result": "record_deny",
            "pnl_outcome": None,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
    }


def _source_payload() -> dict[str, object]:
    predictions = [_prediction("v2h_cuda_1", symbol="BTCUSDT"), _prediction("v2h_cuda_2", symbol="ETHUSDT")]
    return {
        "schema_version": "v2_native_rl_masa_ppo_cuda_trainer_operator_dashboard_v1",
        "generated_est": "2026-06-04T15:10:00-04:00",
        "generated_at": "2026-06-04T15:10:00-04:00",
        "go_no_go": TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
        "trainer": {
            "schema_version": "v2_native_rl_masa_ppo_cuda_trainer_status_v1",
            "trainer_source": TRAINER_SOURCE,
            "model_source": MODEL_SOURCE,
            "checkpoint_source": CHECKPOINT_SOURCE,
            "checkpoint_id": "v2_hybrid_ckpt_test",
            "cuda_active": True,
            "model_device": "cuda:0",
            "model_tensors_device_verified": True,
            "examples_built": 2,
            "input_dim": 140,
            "paper_shadow_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "risk_caps_configured": False,
        },
        "metrics": {
            "training": {
                "status": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINING_STEP_RAN",
                "cuda_active": True,
                "cuda_claim_verified": True,
                "device": "cuda:0",
                "gpu_name": "NVIDIA GeForce RTX 5080",
                "vram_allocated_mb": 18.25,
                "training_steps": 2,
                "train_rows": 2,
                "validation_rows": 1,
                "loss_before": 4.2,
                "loss_after": 2.1,
                "action_distribution": {"0": 2},
            },
            "data_coverage_avg": 100.0,
            "missing_feature_count_total": 0,
            "stale_feature_count_total": 0,
            "v2_io_audit": {
                "keys_written": [
                    "v2:prediction:BTCUSDT:1m",
                    "v2:prediction:ETHUSDT:1m",
                    "v2:risk:decisions",
                    "v2:orchestrator:decisions",
                    "v2:paper:ledger",
                ],
                "old_redis_write_attempts": 0,
            },
        },
        "prediction_count": 2,
        "lineage_count": 2,
        "predictions_by_symbol": predictions,
        "lineage_samples": [_lineage("v2h_cuda_1", symbol="BTCUSDT"), _lineage("v2h_cuda_2", symbol="ETHUSDT")],
        "live_switch": {
            "visible": True,
            "enabled": False,
            "backend_live_enable_callable": False,
            "disabled_reason": "LIVE_GATE=blocked_human_only",
        },
    }


def _paths(tmp_path: Path, source: Path) -> CudaTrainerLiveGatePaths:
    return CudaTrainerLiveGatePaths(
        repo_root=tmp_path,
        worklog_dir=tmp_path / "claude_worklog/final_readiness/v2_native_cuda_trainer_runtime_signal_burn_in_and_website_live_gate/latest",
        public_dir=tmp_path / "v2/frontend/public/v2_native_cuda_trainer_runtime_signal_burn_in_and_website_live_gate/latest",
        source_payload_path=source,
    )


def test_runtime_signal_burn_in_live_gate_writes_required_ready_artifacts(tmp_path: Path) -> None:
    source = _source_payload()
    result = build_runtime_signal_gate(source, generated_est="2026-06-04T15:30:00-04:00")
    written = write_runtime_signal_gate_artifacts(paths=_paths(tmp_path, tmp_path / "unused.json"), result=result)

    assert written.go_no_go == GATE_READY
    required = {
        "GO_NO_GO.md",
        "V2_NATIVE_CUDA_TRAINER_RUNTIME_SIGNAL_BURN_IN_AND_WEBSITE_LIVE_GATE_REPORT.md",
        "v2_native_cuda_trainer_burn_in_status.json",
        "v2_native_cuda_prediction_contract_status.json",
        "v2_risk_consumes_cuda_trainer_status.json",
        "v2_orchestrator_consumes_cuda_trainer_status.json",
        "v2_paper_trader_cuda_signal_lineage_status.json",
        "v2_cuda_trainer_edge_recompute_status.json",
        "v2_cuda_trainer_website_live_gate_status.json",
        "operator_dashboard_payload.json",
    }
    public_dir = tmp_path / "v2/frontend/public/v2_native_cuda_trainer_runtime_signal_burn_in_and_website_live_gate/latest"
    assert required == {path.name for path in public_dir.iterdir()}
    assert (public_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip() == GATE_READY

    payload = json.loads((public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8"))
    assert payload["trainer"]["cuda_active"] is True
    assert payload["prediction_contract"]["contract_pass"] is True
    assert payload["risk_consumption"]["risk_caps_status"] == "OPERATOR_REQUIRED_BLOCKED"
    assert payload["orchestrator_consumption"]["risk_decision_pairing"]["status"] == "PAIRED_LINEAGE_VERIFIED"
    assert payload["paper_signal_lineage"]["consumption_pass"] is True
    assert payload["edge_recompute"]["edge_proven"] is False
    assert payload["live_readiness"]["live_ready"] is False
    assert payload["live_readiness"]["canary_ready"] is False
    assert payload["live_readiness"]["recommendations"] == [
        "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
        "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
    ]
    assert payload["live_readiness"]["live_gate"] == LIVE_GATE_BLOCKED
    assert payload["live_readiness"]["live_symbols"] == []
    assert payload["live_readiness"]["execution_live_symbols"] == []
    assert payload["live_switch"]["enabled"] is False

    emitted = json.dumps(payload)
    assert "LIVE_READY" not in emitted
    assert "CANARY_READY" not in emitted


def test_runtime_signal_gate_blocks_bad_prediction_contract() -> None:
    source = _source_payload()
    bad_prediction = dict(source["predictions_by_symbol"][0])  # type: ignore[index]
    bad_prediction["trainer_source"] = "V2_NATIVE_BASELINE_PAPER_SHADOW"
    source["predictions_by_symbol"] = [bad_prediction]

    result = build_runtime_signal_gate(source, generated_est="2026-06-04T15:30:00-04:00")

    assert result.go_no_go == GATE_BLOCKED
    contract = result.artifacts["v2_native_cuda_prediction_contract_status.json"]
    assert contract["contract_pass"] is False
    assert any("trainer_source_mismatch" in violation for violation in contract["violations"])
    assert result.operator_dashboard_payload["live_switch"]["enabled"] is False


def test_cli_generates_live_gate_from_source_payload(tmp_path: Path, capsys) -> None:
    source_path = tmp_path / "source_operator_dashboard_payload.json"
    source_path.write_text(json.dumps(_source_payload()), encoding="utf-8")

    code = main(["--repo-root", str(tmp_path), "--source-payload", str(source_path)])

    assert code == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["go_no_go"] == GATE_READY
    assert stdout["live_gate"] == LIVE_GATE_BLOCKED
    public_dir = tmp_path / "v2/frontend/public/v2_native_cuda_trainer_runtime_signal_burn_in_and_website_live_gate/latest"
    assert (public_dir / "operator_dashboard_payload.json").exists()
