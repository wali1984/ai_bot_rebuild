from __future__ import annotations

import json

from app.cli.verify_pipeline_trust import main


BASE_MS = 1_700_000_000_000


def test_verify_pipeline_trust_exits_nonzero_for_critical_failures(tmp_path):
    sample = {
        "candles": [
            {
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "open_time": 1_000_000,
                "close_time": 1_300_000,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
                "closed_candle": False,
            }
        ],
        "features": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "generated_at": 1_200_000,
                "feature_cutoff": 1_200_000,
                "source_candle_timestamps": [1_500_000],
                "features": {"ret_pct": 0.01},
            }
        ],
        "training_samples": [
            {
                "sample_id": "dirty-1",
                "row_classification": "STALE_MASKED",
                "used_for_training": True,
                "features": {"ret_pct": 0.01},
                "fee_bps": 5,
                "slippage_bps": 2,
            }
        ],
        "execution_records": [
            {
                "position_before": "long",
                "requested_action": "open_short",
                "position_after": "short",
                "fill_status": "filled",
            }
        ],
    }
    input_path = tmp_path / "sample.json"
    input_path.write_text(json.dumps(sample), encoding="utf-8")

    exit_code = main(["--input", str(input_path), "--output-dir", str(tmp_path)])

    assert exit_code == 1
    report = json.loads((tmp_path / "pipeline_trust_report.json").read_text(encoding="utf-8"))
    critical_titles = {
        finding["title"]
        for finding in report["findings"]
        if finding["status"] == "FAIL" and finding["severity"] == "Critical"
    }
    assert "future feature use detected" in critical_titles
    assert "dirty training sample accepted" in critical_titles
    assert "invalid position transition detected" in critical_titles


def test_verify_pipeline_trust_exits_zero_without_critical_failures(tmp_path):
    sample = {
        "candles": [
            {
                "exchange": "binance",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "open_time": BASE_MS,
                "close_time": BASE_MS + 60_000,
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 10,
                "closed_candle": True,
            }
        ],
        "features": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "generated_at": BASE_MS + 70_000,
                "feature_cutoff": BASE_MS + 60_000,
                "source_candle_timestamps": [BASE_MS + 60_000],
                "features": {"ret_pct": 0.005},
            }
        ],
        "model_decisions": [
            {
                "prediction_id": "p1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "decision_time": BASE_MS + 70_000,
                "masa_generated_at": BASE_MS + 65_000,
                "masa_feature_cutoff": BASE_MS + 60_000,
                "masa_forecast_horizon": "1m",
                "ppo_observation_time": BASE_MS + 65_000,
                "ppo_feature_cutoff": BASE_MS + 60_000,
                "selected_action": "hold",
                "masa_signal": 0.5,
            }
        ],
        "training_samples": [
            {
                "sample_id": "clean-1",
                "row_classification": "TRAINABLE",
                "used_for_training": True,
                "feature_cutoff": BASE_MS + 60_000,
                "label_start_time": BASE_MS + 60_000,
                "label_end_time": BASE_MS + 120_000,
                "prediction_horizon_seconds": 60,
                "features": {"ret_pct": 0.005},
                "fee_bps": 5,
                "slippage_bps": 2,
            }
        ],
        "execution_records": [
            {
                "position_before": "flat",
                "requested_action": "hold",
                "position_after": "flat",
                "fill_status": "none",
            }
        ],
        "config_admin": [
            {
                "live_gate": "blocked_human_only",
                "dangerous_settings_pending_approval": [],
                "approval_token_created": False,
                "approval_token_self_creatable": False,
                "secrets_written_to_payload": False,
                "old_redis_write": False,
                "exchange_action_taken": False,
                "leverage_or_margin_change": False,
                "settings_by_risk_class": {"safe": 1, "dangerous": 0},
            }
        ],
    }
    input_path = tmp_path / "sample.json"
    input_path.write_text(json.dumps(sample), encoding="utf-8")

    exit_code = main(["--input", str(input_path), "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "pipeline_trust_report.json").exists()
    assert (tmp_path / "pipeline_trust_report.md").exists()
