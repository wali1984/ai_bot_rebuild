from __future__ import annotations

import json
from unittest.mock import MagicMock

from v2.backend.app.services.microstructure_trust.cascade_context import (
    CASCADE_ABSENT_NO_TRADE,
    CASCADE_EVENT_CONFIRMED,
    CASCADE_INSUFFICIENT_SHADOW_ONLY,
    CASCADE_PROXY_CONFIRMED,
    CASCADE_STALE_NO_TRADE,
    build_cascade_context,
    context_allows_short_trend_paper_entry,
)
from v2.backend.app.services.paper_trade_management.entry_gate import (
    PaperEntryGateConfig,
    evaluate_entry_gate,
)


def test_build_cascade_context_proxy_confirmed_without_liquidation_event() -> None:
    now = "2026-07-03T12:00:00Z"
    context = build_cascade_context(
        symbol="ETHUSDT",
        timeframe="15m",
        decision_time=now,
        sources={
            "open_interest": {"oi_change_pct": 0.06, "generated_at": now},
            "funding": {"funding_rate": 0.0012, "generated_at": now},
            "long_short": {"long_short_ratio": 2.8, "generated_at": now},
            "orderbook": {"orderbook_imbalance": -0.72, "generated_at": now},
            "spread": {"spread_bps": 18.0, "generated_at": now},
            "trade_tape": {"trade_tape_acceleration": 35.0, "generated_at": now},
            "mark_index": {"mark_index_divergence_bps": 55.0, "generated_at": now},
            "cross_asset": {"correlated_move_score": 0.9, "generated_at": now},
        },
    )

    assert context["cascade_context_status"] == CASCADE_PROXY_CONFIRMED
    assert context["cascade_risk_score"] >= 0.30
    assert context["cascade_event_component"] is None
    assert context["fabricated_liquidation_event"] is False
    assert "liquidation_event" in context["missing_mask"]


def test_build_cascade_context_absent_no_trade_with_explicit_missing_mask() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1h",
        decision_time="2026-07-03T12:00:00Z",
        sources={},
    )

    assert context["cascade_context_status"] == CASCADE_ABSENT_NO_TRADE
    assert context["cascade_risk_score"] == 0.0
    assert set(context["missing_mask"]) >= {"coinank_level", "liquidation_event", "open_interest"}


def test_build_cascade_context_accepts_live_liquidation_timestamp_fields() -> None:
    context = build_cascade_context(
        symbol="ZECUSDT",
        timeframe="1m",
        decision_time="2026-07-05T23:42:13.000Z",
        sources={
            "coinank_level": {
                "liquidation_cascade_risk": 1.0,
                "liquidation_updated_ts": 1783294921898,
            },
            "liquidation_event": {
                "notional": 6_000_000.0,
                "event_time_ms": 1783294800440,
            },
            "open_interest": {"oi_change_pct": 0.06, "fetched_utc": "2026-07-05T23:40:55.987Z"},
            "funding": {"funding_rate": 0.0012, "time": 1783294856003},
            "long_short": {"long_short_ratio": 3.0, "as_of_ms": 1783294500000},
        },
    )

    assert "coinank_level" not in context["stale_mask"]
    assert "liquidation_event" not in context["stale_mask"]
    assert "open_interest" not in context["stale_mask"]
    assert context["source_availability"]["coinank_level"]["available"] is True
    assert context["source_availability"]["liquidation_event"]["available"] is True
    assert context["source_availability"]["open_interest"]["available"] is True
    assert context["cascade_context_status"] == CASCADE_EVENT_CONFIRMED
    assert context["cascade_risk_score"] >= 0.30
    assert context["available_at"] <= context["decision_time"]


def test_build_cascade_context_rejects_future_source_timestamp_fields() -> None:
    context = build_cascade_context(
        symbol="ZECUSDT",
        timeframe="1m",
        decision_time="2026-07-05T23:42:13.000Z",
        sources={
            "coinank_level": {
                "liquidation_cascade_risk": 0.42,
                "liquidation_updated_ts": 1783294994000,
            },
        },
    )

    assert "coinank_level" in context["stale_mask"]
    assert context["source_availability"]["coinank_level"]["available"] is False
    assert context["cascade_context_status"] == CASCADE_STALE_NO_TRADE


def test_absent_cascade_context_uses_explicit_provider_covered_reason() -> None:
    allowed, reason = context_allows_short_trend_paper_entry(
        {"cascade_context_status": CASCADE_ABSENT_NO_TRADE, "cascade_risk_score": 0.0}
    )

    assert allowed is False
    assert reason == "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE"


def test_entry_gate_consumes_proxy_confirmed_cascade_context_without_lowering_threshold() -> None:
    context = {
        "schema_version": "cascade_context_v1",
        "cascade_context_status": CASCADE_PROXY_CONFIRMED,
        "cascade_risk_score": 0.42,
        "paper_only": True,
        "threshold_lowered": False,
    }
    redis_mock = MagicMock()
    redis_mock.get.return_value = json.dumps(context)

    result = evaluate_entry_gate(
        symbol="ETHUSDT",
        timeframe="15m",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=-9.0,
        redis_client=redis_mock,
        config=PaperEntryGateConfig(),
    )

    assert result["allowed"] is True
    assert PaperEntryGateConfig().short_trend_cascade_risk_min == 0.30
    assert not any("REGIME_GATE" in reason for reason in result["reasons"])
    redis_mock.get.assert_any_call("v2:microstructure:cascade_context:ETHUSDT:15m")


def test_entry_gate_blocks_shadow_only_cascade_context() -> None:
    context = {
        "schema_version": "cascade_context_v1",
        "cascade_context_status": CASCADE_INSUFFICIENT_SHADOW_ONLY,
        "cascade_risk_score": 0.18,
        "paper_only": True,
        "threshold_lowered": False,
    }
    redis_mock = MagicMock()
    redis_mock.get.return_value = json.dumps(context)

    result = evaluate_entry_gate(
        symbol="BNBUSDT",
        timeframe="1h",
        side="short",
        strategy_mode="trend_mode",
        confidence_calibrated=0.72,
        expected_move_after_cost_bps=-9.0,
        redis_client=redis_mock,
        config=PaperEntryGateConfig(),
    )

    assert result["allowed"] is False
    assert any("REGIME_GATE_CASCADE_CONTEXT_SHADOW_ONLY" in reason for reason in result["reasons"])
