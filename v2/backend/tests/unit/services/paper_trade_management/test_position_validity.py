from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.services.paper_trade_management.position_validity import (
    QUARANTINED_ACCOUNT_SCOPE,
    STRICT_WRITE_VALIDITY_CONFIG,
    validate_closed_trade,
    validate_open_position,
    validate_paper_fill_write_invariant,
)


def _valid_fill(**overrides):
    row = {
        "position_id": "paper_pos_BTCUSDT",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 0.01,
        "entry_price": 63000.0,
        "entry_price_source": "v2:market:prices.ticker_24hr.lastPrice",
        "fill_price": 63000.0,
        "fill_price_source": "v2:market:prices.ticker_24hr.lastPrice",
        "mark_price_at_fill": 63000.0,
        "entry_fill_id": "fill-1",
        "entry_time": "2026-07-05T12:00:00Z",
        "entry_prediction_id": "pred-1",
        "entry_signal_id": "sig-1",
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "risk_decision_id": "risk-1",
        "orchestrator_decision_id": "orch-1",
        "paper_fill_allowed": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "allocated_margin_usd": 63.0,
        "gross_notional_usd": 630.0,
        "effective_leverage": 10.0,
        "margin_mode_simulated": "isolated_paper_simulated",
        "feature_cutoff": "2026-07-05T11:59:00Z",
        "available_at": "2026-07-05T11:59:05Z",
        "decision_time": "2026-07-05T12:00:00Z",
        "production_grade_cost_flag": True,
    }
    row.update(overrides)
    return row


def test_btc_entry_100_with_current_mark_63000_fails() -> None:
    status = validate_open_position(
        _valid_fill(entry_price=100.0, fill_price=100.0, mark_price_at_fill=100.0),
        mark_price=63000.0,
        mark_source="TEST_MARK",
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_CURRENT_MARK" in status["reasons"]
    assert "ENTRY_PRICE_CURRENT_MARK_IMPOSSIBLE_RATIO" in status["reasons"]


def test_synthetic_coherent_small_price_fixture_can_pass() -> None:
    status = validate_open_position(
        _valid_fill(entry_price=100.0, fill_price=100.0, mark_price_at_fill=100.0),
        mark_price=110.0,
        mark_source="TEST_MARK",
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert "ENTRY_PRICE_CURRENT_MARK_IMPOSSIBLE_RATIO" not in status["reasons"]
    assert "BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_CURRENT_MARK" not in status["reasons"]


def test_shadow_gate_open_cannot_write_economic_position() -> None:
    status = validate_paper_fill_write_invariant(
        _valid_fill(source_tier="SHADOW_ONLY", reason="SHADOW GATE OPEN"),
        mark_price=63000.0,
        mark_source="TEST_MARK",
        mark_age_seconds=1.0,
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "SHADOW_ONLY_CANNOT_CREATE_ECONOMIC_POSITION" in status["reasons"]


def test_hold_action_cannot_write_position() -> None:
    status = validate_paper_fill_write_invariant(
        _valid_fill(action="hold"),
        mark_price=63000.0,
        mark_source="TEST_MARK",
        mark_age_seconds=1.0,
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "HOLD_ACTION_CANNOT_OPEN_POSITION" in status["reasons"]


def test_missing_mark_source_excludes_from_equity() -> None:
    status = validate_paper_fill_write_invariant(
        _valid_fill(),
        mark_price=None,
        mark_source=None,
        mark_age_seconds=None,
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "MISSING_CURRENT_MARK_PRICE" in status["reasons"]


def test_missing_risk_decision_blocks_fill() -> None:
    status = validate_paper_fill_write_invariant(
        _valid_fill(risk_decision_id=None),
        mark_price=63000.0,
        mark_source="TEST_MARK",
        mark_age_seconds=1.0,
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "MISSING_RISK_DECISION_ID" in status["reasons"]


def test_missing_production_cost_blocks_fill() -> None:
    status = validate_paper_fill_write_invariant(
        _valid_fill(production_grade_cost_flag=None),
        mark_price=63000.0,
        mark_source="TEST_MARK",
        mark_age_seconds=1.0,
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "MISSING_PRODUCTION_GRADE_COST_FLAG" in status["reasons"]


def test_stale_price_blocks_strict_fill() -> None:
    status = validate_paper_fill_write_invariant(
        _valid_fill(),
        mark_price=63000.0,
        mark_source="TEST_MARK",
        mark_age_seconds=STRICT_WRITE_VALIDITY_CONFIG.max_mark_age_seconds + 1.0,
        now=datetime(2026, 7, 5, 12, 1, tzinfo=timezone.utc),
    )

    assert status["valid"] is False
    assert "STALE_CURRENT_MARK_PRICE" in status["reasons"]


def test_closed_btc_trade_entry_price_100_vs_exit_63000_is_invalid() -> None:
    status = validate_closed_trade(
        {
            "close_id": "close_bad_btc",
            "entry_fill_id": "fill_bad_btc",
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 100.0,
            "exit_price": 63000.0,
            "realized_pnl_usd": 62900.0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )

    assert status["valid"] is False
    assert status["account_scope"] == QUARANTINED_ACCOUNT_SCOPE
    assert "ENTRY_PRICE_EXIT_PRICE_IMPOSSIBLE_RATIO" in status["reasons"]
    assert "BTC_ENTRY_PRICE_IMPOSSIBLE_WITH_EXIT_PRICE" in status["reasons"]
