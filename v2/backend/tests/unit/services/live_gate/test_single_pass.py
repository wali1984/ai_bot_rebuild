from __future__ import annotations

import json
from pathlib import Path

from app.services.live_gate.single_pass import (
    GATE_BLOCKED,
    LIVE_GATE_BLOCKED,
    build_output_integrity_status,
    build_single_pass,
    default_paths,
    write_single_pass_artifacts,
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _prediction(symbol: str, timeframe: str) -> dict[str, object]:
    return {
        "prediction_id": f"pred_{symbol}_{timeframe}",
        "generated_est": "2026-06-05T01:00:00-04:00",
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_action": "hold",
        "action_probabilities": [1.0, 0.0, 0.0],
        "confidence_raw": 0.6,
        "confidence_calibrated": 0.55,
        "expected_move_bps": 1.0,
        "expected_move_after_cost_bps": -1.0,
        "price_target": 100.0,
        "price_target_after_cost": 99.9,
        "feature_snapshot_id": f"fs_{symbol}_{timeframe}",
        "data_coverage_percent": 100.0,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }


def test_output_integrity_requires_price_targets() -> None:
    status = build_output_integrity_status(
        {"prediction_rows": [_prediction("BTCUSDT", tf) for tf in ("1m", "5m", "15m", "1h", "4h")]},
        generated_est="2026-06-05T01:00:00-04:00",
    )
    assert status["status"] == "CUDA_TRAINER_OUTPUT_INTEGRITY_READY"
    assert status["price_target_missing_count"] == 0

    bad = _prediction("BTCUSDT", "1m")
    bad.pop("price_target")
    blocked = build_output_integrity_status({"prediction_rows": [bad]}, generated_est="2026-06-05T01:00:00-04:00")
    assert blocked["status"] == "CUDA_TRAINER_OUTPUT_INTEGRITY_BLOCKED"
    assert blocked["price_target_missing_count"] == 1


def test_single_pass_writes_blocked_artifacts_without_live_symbols(tmp_path: Path) -> None:
    paths = default_paths(tmp_path)
    predictions = [_prediction("BTCUSDT", tf) for tf in ("1m", "5m", "15m", "1h", "4h")]
    _write_json(
        paths.native_trainer_payload_path,
        {"metrics": {"training": {"batch_size": 5, "metrics": {"actual_batch_size": 5}}}},
    )
    _write_json(paths.all_tf_prediction_status_path, {"prediction_rows": predictions})
    _write_json(
        paths.all_tf_signal_status_path,
        {
            "published_signals": [
                {
                    "prediction_id": row["prediction_id"],
                    "risk_decision_id": f"risk_{row['prediction_id']}",
                    "orchestrator_decision_id": f"orch_{row['prediction_id']}",
                    "paper_intent_id": f"intent_{row['prediction_id']}",
                    "paper_ledger_id": f"ledger_{row['prediction_id']}",
                    "live_gate": LIVE_GATE_BLOCKED,
                    "live_symbols": [],
                }
                for row in predictions
            ]
        },
    )
    _write_json(paths.feature_inventory_path, {"current_blocked_field_rows_count": 1, "current_blocked_rows": []})
    _write_json(paths.tensor_coverage_path, {"missing_fields": 1})
    _write_json(paths.backtest_edge_path, {"edge_proven": False, "primary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"})
    _write_json(paths.backtest_worker_path, {"sample_count": 1})

    result = write_single_pass_artifacts(
        paths=paths,
        result=build_single_pass(paths=paths, network_probe_enabled=False),
    )

    assert result.go_no_go == GATE_BLOCKED
    payload = json.loads((paths.public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8"))
    assert payload["live_gate"] == LIVE_GATE_BLOCKED
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["trader_execution_enabled"] is False
    assert payload["places_real_order"] is False
