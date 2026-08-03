from __future__ import annotations

import json

from v2.backend.app.cli.v2_market_chart_payload_publisher import (
    _bounded_loop_log_summary,
)


def test_loop_log_summary_omits_unbounded_symbol_payloads() -> None:
    summary = {
        "generated_utc": "2026-07-20T08:00:00Z",
        "generated_est": "2026-07-20T04:00:00-04:00",
        "status": "V2_MARKET_CHART_PAYLOADS_PARTIAL",
        "symbols": [f"SYM{index}USDT" for index in range(155)],
        "symbols_count": 155,
        "timeframe": "1m",
        "require_wsds": False,
        "status_counts": {"CURRENT": 130, "STALE": 25},
        "current_wsds_count": 130,
        "non_current_symbols": [f"SYM{index}USDT" for index in range(25)],
        "payloads": {
            f"SYM{index}USDT": {"unbounded": "x" * 1024} for index in range(155)
        },
        "live_gate": "blocked_human_only",
    }

    compact = _bounded_loop_log_summary(summary)
    encoded = json.dumps(compact, sort_keys=True)

    assert compact["schema_version"] == "v2_market_chart_payload_publisher_loop_log_v1"
    assert compact["symbols_count"] == 155
    assert compact["non_current_symbol_count"] == 25
    assert compact["non_current_symbols_omitted_count"] == 9
    assert len(compact["non_current_symbols_sample"]) == 16
    assert compact["full_payloads_omitted_from_loop_log"] is True
    assert compact["writes_exchange_orders"] is False
    assert "payloads" not in compact
    assert "symbols" not in compact
    assert "unbounded" not in encoded
    assert len(encoded.encode("utf-8")) < 2048


def test_loop_log_summary_treats_invalid_non_current_list_as_empty() -> None:
    compact = _bounded_loop_log_summary(
        {
            "non_current_symbols": "BTCUSDT",
            "status_counts": {},
            "live_gate": "blocked_human_only",
        }
    )

    assert compact["non_current_symbol_count"] == 0
    assert compact["non_current_symbols_sample"] == []
    assert compact["non_current_symbols_omitted_count"] == 0
