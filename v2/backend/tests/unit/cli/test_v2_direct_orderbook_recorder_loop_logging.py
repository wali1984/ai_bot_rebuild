from __future__ import annotations

import json

from v2.backend.app.cli import v2_direct_orderbook_recorder as recorder


def _large_run_payload() -> dict[str, object]:
    symbols = [f"COIN{index:04d}USDT" for index in range(1_000)]
    return {
        "worker_id": "v2_direct_orderbook_recorder",
        "started_at": "2026-07-18T14:00:00.000Z",
        "finished_at": "2026-07-18T14:03:00.000Z",
        "loop_run_index": 42,
        "exchange": "binance",
        "symbols": symbols,
        "symbol_count": len(symbols),
        "requested_symbols": symbols,
        "requested_symbol_count": len(symbols),
        "provider_filtered_symbols": symbols[:100],
        "provider_symbol_support": {symbol: {"status": "TRADING"} for symbol in symbols},
        "shard_index": 1,
        "shard_count": 4,
        "processed_messages": 25_000,
        "processed_exchanges": ["binance"],
        "direct_binance_active": True,
        "direct_kucoin_active": False,
        "redis_enabled": True,
        "redis_available": True,
        "redis_freshness_check": {
            "enabled": True,
            "status": "PASS",
            "redis_available": True,
            "symbols_checked": 250,
            "fresh_symbol_count": 250,
            "missing_symbol_count": 0,
            "stale_symbol_count": 0,
            "invalid_payload_count": 0,
            "read_error_count": 0,
            "stale_bound_ms": 1500.0,
            "by_symbol": {symbol: {"fresh": True} for symbol in symbols},
        },
        "run_errors": [],
        "sample_processed": [{"payload": "x" * 100_000}],
        "replay_capture": False,
        "old_redis_writes": False,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "live_gate": "blocked_human_only",
    }


def test_compact_loop_log_is_constant_size_and_preserves_safety_truth() -> None:
    payload = _large_run_payload()

    compact = recorder._loop_log_payload(payload)
    encoded = json.dumps(compact, sort_keys=True, separators=(",", ":"))

    assert len(json.dumps(payload)) > 200_000
    assert len(encoded) < 4_000
    assert compact["symbol_count"] == 1_000
    assert compact["provider_filtered_symbol_count"] == 100
    assert compact["redis_freshness"]["fresh_symbol_count"] == 250
    assert compact["old_redis_writes"] is False
    assert compact["places_real_order"] is False
    assert compact["leverage_mutation"] is False
    assert "symbols" not in compact
    assert "provider_symbol_support" not in compact
    assert "sample_processed" not in compact


def test_loop_log_mode_defaults_to_compact_and_supports_explicit_modes() -> None:
    assert recorder.parse_args(["--loop"]).loop_log_mode == "compact"
    assert recorder.parse_args(["--loop", "--loop-log-mode", "full"]).loop_log_mode == "full"
    assert recorder.parse_args(["--loop", "--loop-log-mode", "silent"]).loop_log_mode == "silent"
