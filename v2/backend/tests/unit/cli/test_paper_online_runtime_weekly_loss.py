from __future__ import annotations

from v2.backend.app.cli.paper_online_runtime import (
    MarketSnapshot,
    build_feature_snapshot,
    build_paper_ledger_entry,
    build_risk_runtime_payload,
    build_signal_lineage,
    build_trainer_prediction,
)


def _market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="BTCUSDT",
        price=100.0,
        source_type="READONLY_MARKET_FEED",
        source="unit_test",
        source_pointer="unit_test",
        generated_at="2026-05-13T07:30:00Z",
        last_event_at="2026-05-13T07:29:59Z",
        age_seconds=1,
        freshness_state="CURRENT",
        errors=[],
        candles=[
            {"close": 99.0, "volume": 10},
            {"close": 100.0, "volume": 11},
            {"close": 101.0, "volume": 12},
            {"close": 100.0, "volume": 13},
            {"close": 99.0, "volume": 14},
            {"close": 98.0, "volume": 15},
            {"close": 100.0, "volume": 16},
            {"close": 101.0, "volume": 17},
            {"close": 100.0, "volume": 18},
            {"close": 100.0, "volume": 19},
        ],
    )


def test_paper_runtime_risk_decision_declares_weekly_loss_block() -> None:
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )

    assert "weekly_loss_breach" in lineage["risk_decision"]["required_blocks_checked"]


def test_risk_runtime_payload_proves_weekly_loss_gate_without_live_side_effects() -> None:
    market = _market()
    feature = build_feature_snapshot(market, "tick_unit")
    prediction = build_trainer_prediction(feature, "tick_unit")
    lineage = build_signal_lineage(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        feature_snapshot=feature,
        prediction=prediction,
        market=market,
    )
    ledger, account = build_paper_ledger_entry(
        tick_id="tick_unit",
        generated_at="2026-05-13T07:30:00Z",
        market=market,
        lineage=lineage,
        previous_equity=10000.0,
    )

    payload = build_risk_runtime_payload(
        generated_at="2026-05-13T07:30:00Z",
        lineage=lineage,
        ledger_entry=ledger,
        paper_account=account,
    )

    assert payload["weekly_loss_gate_required"] is True
    assert payload["daily_loss_gate_required"] is True
    assert payload["exchange_order"] is False
    assert payload["legacy_redis_write"] is False
    assert payload["live_gate_status"] == "blocked_human_only"
