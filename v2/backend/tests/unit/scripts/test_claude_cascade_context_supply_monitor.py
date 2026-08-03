from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_monitor_module():
    repo_root = Path(__file__).resolve().parents[5]
    path = repo_root / "tools" / "claude_cascade_context_supply_monitor.py"
    spec = importlib.util.spec_from_file_location("claude_cascade_context_supply_monitor", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_router_consumption_ignores_context_generated_after_candidate_decision() -> None:
    monitor = _load_monitor_module()

    cascade = {
        "fresh_symbols": ["TRUMPUSDT"],
        "fresh_by_symbol_tf": {"TRUMPUSDT": {"1m": 0.34}},
        "confirmed_context_by_symbol_tf": {
            "TRUMPUSDT": {
                "1m": {
                    "score": 0.34,
                    "available_ms": monitor._parse_time_ms("2026-07-06T00:04:15.480Z"),
                    "generated_ms": monitor._parse_time_ms("2026-07-06T00:04:52.687Z"),
                    "available_at": "2026-07-06T00:04:15.480Z",
                    "generated_at": "2026-07-06T00:04:52.687Z",
                }
            }
        },
    }
    block_counts = {
        "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE:short:trend_mode:TRUMPUSDT:1m": 1
    }
    blocked_rows = [
        {
            "symbol": "TRUMPUSDT",
            "timeframe": "1m",
            "decision_time": "2026-07-06T00:03:20.952Z",
            "generated_utc": "2026-07-06T00:05:24.232Z",
            "entry_gate_block_reasons": [
                "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE:short:trend_mode:TRUMPUSDT:1m"
            ],
        }
    ]

    result = monitor._check_router_consumption(cascade, block_counts, blocked_rows)

    assert result["regression_detected"] is False
    assert result["temporal_skip_count"] == 1
    assert result["temporal_skips"][0]["reason"] == "CONTEXT_NOT_AVAILABLE_AT_CANDIDATE_DECISION_TIME"


def test_router_consumption_flags_temporally_eligible_fresh_context_block() -> None:
    monitor = _load_monitor_module()

    cascade = {
        "fresh_symbols": ["RIVERUSDT"],
        "fresh_by_symbol_tf": {"RIVERUSDT": {"5m": 0.64}},
        "confirmed_context_by_symbol_tf": {
            "RIVERUSDT": {
                "5m": {
                    "score": 0.64,
                    "available_ms": monitor._parse_time_ms("2026-07-06T00:01:00.000Z"),
                    "generated_ms": monitor._parse_time_ms("2026-07-06T00:01:30.000Z"),
                    "available_at": "2026-07-06T00:01:00.000Z",
                    "generated_at": "2026-07-06T00:01:30.000Z",
                }
            }
        },
    }
    block_counts = {
        "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE:short:trend_mode:RIVERUSDT:5m": 1
    }
    blocked_rows = [
        {
            "symbol": "RIVERUSDT",
            "timeframe": "5m",
            "decision_time": "2026-07-06T00:03:20.000Z",
            "generated_utc": "2026-07-06T00:03:40.000Z",
            "entry_gate_block_reasons": [
                "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE:short:trend_mode:RIVERUSDT:5m"
            ],
        }
    ]

    result = monitor._check_router_consumption(cascade, block_counts, blocked_rows)

    assert result["regression_detected"] is True
    assert result["regression_symbols"] == [
        {
            "symbol": "RIVERUSDT",
            "blocked_tfs": ["5m"],
            "fresh_tfs_also_blocked": ["5m"],
            "cascade_risk_values": {"5m": 0.64},
            "row_decision_time": "2026-07-06T00:03:20.000Z",
            "row_generated_at": "2026-07-06T00:03:40.000Z",
            "context_available_at": "2026-07-06T00:01:00.000Z",
            "context_generated_at": "2026-07-06T00:01:30.000Z",
        }
    ]
