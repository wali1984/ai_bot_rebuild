from __future__ import annotations

import json
from unittest.mock import MagicMock

from v2.backend.app.services.microstructure_trust.cascade_context import (
    CASCADE_ABSENT_NO_TRADE,
    CASCADE_EVENT_CONFIRMED,
    CASCADE_INSUFFICIENT_SHADOW_ONLY,
    CASCADE_LEVEL_PROXIMITY_CONFIRMED,
    CASCADE_PROXY_CONFIRMED,
    CASCADE_STALE_NO_TRADE,
    build_cascade_context,
    context_allows_short_trend_paper_entry,
)
from v2.backend.app.services.paper_trade_management.entry_gate import (
    PaperEntryGateConfig,
    evaluate_entry_gate,
)


def _with_lineage(payload: dict, at: str | int) -> dict:
    return {
        **payload,
        "feature_cutoff": at,
        "ingested_at": at,
        "available_at": at,
    }


def test_build_cascade_context_proxy_confirmed_without_liquidation_event() -> None:
    now = "2026-07-03T12:00:00Z"
    context = build_cascade_context(
        symbol="ETHUSDT",
        timeframe="15m",
        decision_time=now,
        sources={
            "open_interest": _with_lineage({"oi_change_pct": 0.06}, now),
            "funding": _with_lineage({"funding_rate": 0.0012}, now),
            "long_short": _with_lineage({"long_short_ratio": 2.8}, now),
            "orderbook": _with_lineage({"orderbook_imbalance": -0.72}, now),
            "spread": _with_lineage({"spread_bps": 18.0}, now),
            "trade_tape": _with_lineage({"trade_tape_acceleration": 35.0}, now),
            "mark_index": _with_lineage({"mark_index_divergence_bps": 55.0}, now),
            "cross_asset": _with_lineage({"correlated_move_score": 0.9}, now),
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
                "liquidation_last_event_ts": 1783294921898,
                "feature_cutoff": 1783294921898,
                "ingested_at": 1783294922000,
                "available_at": 1783294923000,
                "liquidation_semantic_kind": "observed_forced_liquidation_clusters",
                "liquidation_observation_coverage_complete": 1,
                "liquidation_current_price_execution_grade": 1,
                "liquidation_current_price_source": "current_price_resolver:mark_price",
            },
            "liquidation_event": {
                "notional": 6_000_000.0,
                "event_time_ms": 1783294800440,
                "feature_cutoff": 1783294800440,
                "ingested_at": 1783294800500,
                "available_at": 1783294800600,
            },
            "open_interest": _with_lineage({"oi_change_pct": 0.06}, 1783294855987),
            "funding": _with_lineage(
                {"funding_rate": 0.0012, "time": 1783294856003}, 1783294856003
            ),
            "long_short": _with_lineage(
                {"long_short_ratio": 3.0, "as_of_ms": 1783294500000},
                1783294500000,
            ),
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
    assert context["event_time"] == context["feature_cutoff"]
    assert context["ingested_at"] == "2026-07-05T23:42:02.000Z"
    assert context["available_at"] > context["decision_time"]
    assert context["decision_time_safe"] is False
    assert context["decision_time_safety_reason"] == "context_generated_after_decision_time"


def test_build_cascade_context_rejects_future_source_timestamp_fields() -> None:
    context = build_cascade_context(
        symbol="ZECUSDT",
        timeframe="1m",
        decision_time="2026-07-05T23:42:13.000Z",
        sources={
            "coinank_level": {
                "liquidation_cascade_risk": 0.42,
                "liquidation_last_event_ts": 1783294994000,
                "feature_cutoff": 1783294994000,
                "ingested_at": 1783294994000,
                "available_at": 1783294994000,
            },
        },
    )

    assert "coinank_level" in context["stale_mask"]
    assert context["source_availability"]["coinank_level"]["available"] is False
    assert context["cascade_context_status"] == CASCADE_STALE_NO_TRADE


def test_liquidation_declared_stale_fails_closed_despite_fresh_heartbeat() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T23:42:13.000Z",
        sources={
            "coinank_level": {
                "liquidation_cascade_risk": 1.0,
                "distance_to_long_liq_bps": 1.0,
                "liquidation_last_event_ts": 1783290000000,
                "liquidation_updated_ts": 1783294932000,
                "liquidation_is_stale": 1,
                "feature_cutoff": 1783290000000,
                "ingested_at": 1783290001000,
                "available_at": 1783290002000,
            },
        },
    )

    row = context["source_availability"]["coinank_level"]
    assert row["available"] is False
    assert row["invalid"] is True
    assert row["invalid_reason"] == "source_declared_stale"
    assert context["liquidation_level_proximity_component"] is None
    assert context["cascade_context_status"] == CASCADE_STALE_NO_TRADE


def test_liquidation_last_event_clock_precedes_heartbeat_for_freshness() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T23:42:13.000Z",
        sources={
            "coinank_level": {
                "liquidation_cascade_risk": 0.9,
                "distance_to_short_liq_bps": 5.0,
                "liquidation_last_event_ts": 1783260000000,
                "liquidation_updated_ts": 1783294932000,
                "feature_cutoff": 1783260000000,
                "ingested_at": 1783260001000,
                "available_at": 1783260002000,
                "liquidation_semantic_kind": "observed_forced_liquidation_clusters",
                "liquidation_observation_coverage_complete": 1,
                "liquidation_current_price_execution_grade": 1,
                "liquidation_current_price_source": "current_price_resolver:mark_price",
            },
        },
    )

    row = context["source_availability"]["coinank_level"]
    assert row["available"] is False
    assert row["stale"] is True
    assert row["age_seconds"] > row["freshness_bound_seconds"]
    assert context["cascade_context_status"] == CASCADE_STALE_NO_TRADE


def test_incomplete_or_non_market_level_cannot_confirm_proximity() -> None:
    now = "2026-07-05T23:42:13.000Z"
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=now,
        sources={
            "coinank_level": {
                "liquidation_semantic_kind": "observed_forced_liquidation_clusters",
                "liquidation_cascade_risk": 1.0,
                "distance_to_long_liq_bps": 1.0,
                "liquidation_last_event_ts": 1783294920000,
                "liquidation_updated_ts": 1783294932000,
                "liquidation_observation_coverage_complete": 0,
                "liquidation_current_price_source": "liquidation_event_price_ewma_fallback",
                "liquidation_current_price_execution_grade": 0,
                "feature_cutoff": 1783294920000,
                "ingested_at": 1783294921000,
                "available_at": 1783294922000,
            },
            "open_interest": _with_lineage({"oi_change_pct": 0.06}, now),
        },
    )

    assert context["source_availability"]["coinank_level"]["available"] is False
    assert context["liquidation_level_proximity_component"] is None
    assert context["cascade_context_status"] != CASCADE_LEVEL_PROXIMITY_CONFIRMED


def test_context_preserves_event_ingest_available_lineage_order() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T12:01:00.000Z",
        sources={
            "coinank_level": {
                "liquidation_semantic_kind": "observed_forced_liquidation_clusters",
                "liquidation_last_event_ts": "2026-07-05T12:00:00.000Z",
                "feature_cutoff": "2026-07-05T12:00:00.000Z",
                "ingested_at": "2026-07-05T12:00:01.000Z",
                "available_at": "2026-07-05T12:00:02.000Z",
                "liquidation_updated_ts": "2026-07-05T12:00:59.000Z",
                "liquidation_is_stale": 0,
                "liquidation_observation_coverage_complete": 1,
                "liquidation_current_price_source": "current_price_resolver:mark_price",
                "liquidation_current_price_execution_grade": 1,
                "liquidation_cascade_risk": 0.2,
            },
        },
    )

    assert context["event_time"] == "2026-07-05T12:00:00.000Z"
    assert context["feature_cutoff"] == context["event_time"]
    assert context["ingested_at"] == "2026-07-05T12:00:01.000Z"
    assert context["available_at"] > "2026-07-05T12:01:00.000Z"
    assert context["generated_at"] == context["available_at"]
    assert context["event_time"] < context["ingested_at"] < context["available_at"]
    assert context["decision_time_safe"] is False


def test_source_available_after_decision_is_invalid() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T12:01:00.000Z",
        sources={
            "coinank_level": {
                "liquidation_last_event_ts": "2026-07-05T12:00:00.000Z",
                "feature_cutoff": "2026-07-05T12:00:00.000Z",
                "ingested_at": "2026-07-05T12:00:01.000Z",
                "available_at": "2026-07-05T12:02:00.000Z",
                "liquidation_cascade_risk": 1.0,
            },
        },
    )
    row = context["source_availability"]["coinank_level"]
    assert row["available"] is False
    assert row["invalid_reason"] == "source_available_after_decision"
    assert context["liquidation_level_proximity_component"] is None


def test_present_source_without_explicit_pit_lineage_is_shadow_only() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T12:01:00.000Z",
        sources={"open_interest": {"oi_change_pct": 0.10}},
    )
    row = context["source_availability"]["open_interest"]
    assert row["available"] is False
    assert row["invalid_reason"] == "missing_feature_cutoff"
    assert context["oi_change_component"] is None
    assert context["cascade_context_status"] == CASCADE_STALE_NO_TRADE


def test_derived_source_cutoff_after_available_is_invalid() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T12:01:00.000Z",
        sources={
            "orderbook": {
                "orderbook_imbalance": 0.9,
                "feature_cutoff": "2026-07-05T12:00:10.000Z",
                "ingested_at": "2026-07-05T12:00:05.000Z",
                "available_at": "2026-07-05T12:00:06.000Z",
            },
        },
    )
    row = context["source_availability"]["orderbook"]
    assert row["available"] is False
    assert row["invalid_reason"] == "feature_cutoff_after_ingested_at"
    assert context["orderbook_depth_component"] is None


def test_realized_cluster_semantics_cannot_confirm_future_level_proximity() -> None:
    at = "2026-07-05T12:00:00.000Z"
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T12:01:00.000Z",
        sources={
            "coinank_level": _with_lineage(
                {
                    "liquidation_semantic_kind": "observed_forced_liquidation_clusters",
                    "liquidation_last_event_ts": at,
                    "liquidation_observation_coverage_complete": 1,
                    "liquidation_current_price_execution_grade": 1,
                    "liquidation_current_price_source": "current_price_resolver:mark_price",
                    "liquidation_cascade_risk": 1.0,
                    "distance_to_long_liq_bps": 1.0,
                },
                at,
            ),
            "open_interest": _with_lineage({"oi_change_pct": 0.06}, at),
        },
    )
    assert context["source_availability"]["coinank_level"]["available"] is True
    assert context["liquidation_level_proximity_component"] is None
    assert context["cascade_context_status"] != CASCADE_LEVEL_PROXIMITY_CONFIRMED


def test_pit_safe_wss_event_alone_can_supply_real_event_confirmation() -> None:
    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-05T12:01:00.000Z",
        sources={
            "liquidation_event": {
                "semantic_kind": "observed_binance_force_order_snapshots",
                "notional": 6_000_000.0,
                "event_time": "2026-07-05T12:00:00.000Z",
                "feature_cutoff": "2026-07-05T12:00:00.000Z",
                "ingested_at": "2026-07-05T12:00:01.000Z",
                "available_at": "2026-07-05T12:00:01.000Z",
                "generated_at": "2026-07-05T12:00:01.000Z",
            },
        },
    )
    row = context["source_availability"]["liquidation_event"]
    assert row["available"] is True
    assert context["cascade_event_component"] == 1.0
    assert context["cascade_context_status"] == CASCADE_EVENT_CONFIRMED
    assert context["cascade_risk_score"] == 0.35


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
        "feature_cutoff": "2026-07-05T12:00:00.000Z",
        "ingested_at": "2026-07-05T12:00:01.000Z",
        "available_at": "2026-07-05T12:00:02.000Z",
        "generated_at": "2026-07-05T12:00:02.000Z",
        "decision_time": "2026-07-05T12:01:00.000Z",
        "decision_time_safe": True,
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


def test_confirmed_context_missing_safety_metadata_fails_closed() -> None:
    allowed, reason = context_allows_short_trend_paper_entry(
        {
            "cascade_context_status": CASCADE_PROXY_CONFIRMED,
            "cascade_risk_score": 0.9,
        }
    )
    assert allowed is False
    assert reason == "REGIME_GATE_CASCADE_CONTEXT_AVAILABLE_AFTER_DECISION"


def test_confirmed_context_missing_clocks_fails_closed() -> None:
    allowed, reason = context_allows_short_trend_paper_entry(
        {
            "cascade_context_status": CASCADE_PROXY_CONFIRMED,
            "cascade_risk_score": 0.9,
            "decision_time_safe": True,
        }
    )
    assert allowed is False
    assert reason == "REGIME_GATE_CASCADE_CONTEXT_INVALID_LINEAGE"
