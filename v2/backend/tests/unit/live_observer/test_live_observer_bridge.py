from __future__ import annotations

import time
import calendar

import pytest

from v2.backend.app.cli.live_observer_bridge import (
    age_seconds_from_iso,
    build_shadow_twin,
    run_redis_read_only,
)


def test_age_seconds_uses_utc_not_local_timezone() -> None:
    now = calendar.timegm(time.strptime("2026-05-12T20:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))

    assert age_seconds_from_iso("2026-05-12T19:59:00Z", now=now) == 60


def test_redis_write_commands_are_rejected_before_execution() -> None:
    with pytest.raises(ValueError, match="not read-only"):
        run_redis_read_only("SET", "legacy:key", "value")


def test_shadow_twin_blocks_legacy_signal_missing_required_lineage() -> None:
    generated_at = "2026-05-12T20:00:00Z"
    legacy_signal = {
        "source_key": "signals:trading:primary",
        "stream_id": "1778615900000-0",
        "last_event_at": "2026-05-12T20:00:00Z",
        "age_seconds": 0,
        "flat_fields": {
            "signal_id": "sig_legacy_current",
            "symbol": "BTCUSDT",
            "action": "BUY",
            "confidence": "0.91",
        },
    }

    twin = build_shadow_twin(
        generated_at=generated_at,
        legacy_signal=legacy_signal,
        executed_signal=None,
        paper_runtime={"market_feed": {"symbol": "BTCUSDT", "price": 100.0}},
    )

    assert twin["risk_decision"]["risk_result"] == "BLOCKED"
    assert twin["risk_decision"]["risk_reason_code"] == "deny_missing_required_lineage_fields"
    assert twin["risk_decision"]["exchange_order_allowed"] is False
    assert twin["paper_ledger_entry"]["paper_result"] == "NO_FILL_RISK_BLOCKED"
    assert twin["paper_ledger_entry"]["legacy_redis_write"] is False
