from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli import v2_prediction_signal_natural_language_explainer as explainer


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_default_limit_covers_full_current_prediction_grid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(explainer, "REPO", tmp_path)
    monkeypatch.setattr(explainer, "_connect_redis", lambda: None)
    monkeypatch.setattr(explainer, "is_valid_runtime_symbol", lambda symbol: symbol.endswith("USDT"))

    rows = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "selected_action": "short",
            "confidence_raw": 0.42,
            "confidence_calibrated": 0.48,
            "expected_move_bps": -20.0,
            "expected_move_after_cost_bps": -32.0,
            "data_coverage_percent": 80.0,
            "paper_fill_gate_block_reasons": ["confidence_below_threshold"],
            "action_probabilities": {"hold": 0.29, "long": 0.28, "short": 0.43},
        }
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        for timeframe in explainer.TIMEFRAMES
    ]
    _write_json(
        tmp_path / "v2/frontend/public/operator_runtime/v2_signals/latest/signals_payload.json",
        {
            "prediction_contract": {"prediction_rows": rows},
            "signal_publisher": {"published_signals": []},
        },
    )
    _write_json(
        tmp_path / "v2/frontend/public/operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
        {
            "live_gate": "enabled_operator_approved",
            "trader_state": "LIVE_ARMED_BALANCE_HOLD",
            "live_order_submit_blocker": "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
        },
    )

    args = explainer.parse_args([])
    payload = explainer.build_payload(limit=args.limit)

    assert args.limit == explainer.DEFAULT_EXPLANATION_LIMIT
    assert payload["summary"]["prediction_rows"] == len(rows)
    assert payload["summary"]["explanation_rows"] == len(rows)
    assert payload["explanation_count"] == len(rows)
    assert payload["summary"]["explanation_count"] == len(rows)
    assert payload["unique_symbols"] == 3
    assert payload["summary"]["unique_symbols"] == 3
    assert payload["unique_timeframes"] == list(explainer.TIMEFRAMES)
    assert payload["summary"]["unique_timeframes"] == list(explainer.TIMEFRAMES)
    assert payload["symbols_explained"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert payload["timeframes_explained"] == list(explainer.TIMEFRAMES)
    assert payload["top_prediction_paper_gate_block_reasons"] == {"confidence_below_threshold": len(rows)}
    assert len(payload["explanations"]) == len(rows)
    assert {row["symbol"] for row in payload["explanations"]} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    assert {row["timeframe"] for row in payload["explanations"]} == set(explainer.TIMEFRAMES)
    assert payload["explanations"][0]["confidence_explanation"]["drivers"]
    assert len(payload["explanations"][0]["feature_value_samples"]) <= explainer.DEFAULT_FEATURE_SAMPLE_LIMIT
    assert payload["safety"]["real_order_mutation"] is False
    assert payload["real_order_mutation_attempted"] is False
    assert payload["test_order_called"] is False
    assert payload["leverage_or_margin_mutation_attempted"] is False
    assert payload["old_redis_write_attempted"] is False
    assert payload["legacy_restart_attempted"] is False
    assert payload["raw_credentials_emitted"] is False
