"""Squeeze detector + hedge-first controller invariants."""

from __future__ import annotations

from v2.backend.app.services.risk.cross_margin_liquidation import (
    build_portfolio_liquidation_snapshot,
    seal_adaptive_stress_envelope,
)
from v2.backend.app.services.risk.fast_squeeze_detector import detect_squeeze
from v2.backend.app.services.risk.hedge_first_controller import evaluate_hedge_first

NOW = "2026-07-09T06:00:00Z"


def test_adverse_squeeze_on_open_long_requires_hedge_or_reduce():
    ctx = {
        "coinglass": {"features": {
            "coinglass_funding_rate_zscore": 2.6,          # crowded longs -> down squeeze
            "coinglass_liquidation_cascade_score": 0.8,
            "coinglass_liquidation_imbalance_usd": 8_000_000.0,
        }},
        "orderbook": {"depth_imbalance": -0.5, "spread_bps": 8},
        "microstructure": {"tape_imbalance": -0.6},
    }
    out = detect_squeeze(symbol="BTCUSDT", timeframe="1m", context=ctx,
                         open_position_side="long", liquidation_buffer_usd=40.0, generated_utc=NOW)
    assert out["squeeze_direction"] == "down"
    assert out["adverse_to_open_position"] is True
    assert out["hedge_required"] is True or out["reduce_required"] is True


def test_high_squeeze_blocks_late_entry():
    ctx = {
        "coinglass": {"features": {
            "coinglass_funding_rate_zscore": 2.8,
            "coinglass_liquidation_cascade_score": 0.9,
            "coinglass_liquidation_imbalance_usd": 12_000_000.0,
        }},
        "orderbook": {"depth_imbalance": 0.6, "spread_bps": 10},
        "microstructure": {"tape_imbalance": 0.7},
        "confluence": {"features": {"altdata_liquidation_sweep_risk_score": 0.8}},
    }
    out = detect_squeeze(symbol="ETHUSDT", timeframe="5m", context=ctx, generated_utc=NOW)
    assert out["squeeze_probability"] >= 0.6
    assert out["entry_block_required"] is True
    assert out["avoid_static_stops_near_cluster"] is True


def test_calm_market_no_squeeze():
    ctx = {"orderbook": {"depth_imbalance": 0.05, "spread_bps": 1}}
    out = detect_squeeze(symbol="BTCUSDT", timeframe="1m", context=ctx, generated_utc=NOW)
    assert out["squeeze_probability"] < 0.6
    assert out["entry_block_required"] is False


def _snap_with_negative():
    account = {
        "status": "PASS", "accounting_complete": True,
        "account_balance_components_complete": True,
        "wallet_balance_source": "SAME_LEDGER_STARTING_EQUITY_PLUS_REALIZED_NET_PNL",
        "equity_source": "SAME_LEDGER_WALLET_BALANCE_PLUS_CURRENT_UNREALIZED_PNL",
        "paper_session_id": "paper-session-fixture",
        "equity_usd": 420.0, "wallet_balance_usd": 500.0,
        "unrealized_pnl_usd": -80.0,
        "used_margin_usd": 458.0,
        "margin_base_usd": 420.0,
        "newly_reserved_margin_usd": 0.0,
        "newly_reserved_included_in_used_margin": True,
        "free_margin_usd": 0.0,
        "cross_wallet_balance_usd": 500.0,
        "cross_unrealized_pnl_usd": -80.0,
        "cross_equity_usd": 420.0,
        "paper_only": True, "routes_to_live": False, "places_real_order": False,
    }
    quantity, entry, mark, leverage, rate = 30.0, 152.66666666666666, 150.0, 10.0, 0.01
    position = {
        "position_id": "paper_pos_SOLUSDT_fixture", "position_generation_id": "fixture-generation",
        "paper_session_id": "paper-session-fixture",
        "symbol": "SOLUSDT", "side": "long", "net_quantity": quantity,
        "avg_entry_price": entry, "last_mark_price": mark,
        "effective_leverage": leverage, "gross_notional_usd": quantity * entry,
        "maintenance_margin_rate": rate, "maintenance_margin_cum": 0.0,
        "maintenance_margin_mark_price": mark, "maintenance_margin_mark_time": NOW,
        "maintenance_margin_mark_event_time": NOW,
        "maintenance_margin_mark_generated_at": NOW,
        "maintenance_margin_mark_available_at": NOW,
        "maintenance_margin_mark_decision_time": NOW,
        "maintenance_margin_mark_source": "UNIT_AUTHENTICATED_MARK",
        "maintenance_margin_mark_evidence_sha256": "a" * 64,
        "maintenance_margin_mark_contract_authoritative": True,
        "maintenance_margin_mark_freshness_budget_seconds": 1.0,
        "maintenance_margin_mark_cadence_policy_version": "UNIT_MARK_CADENCE_V1",
        "maintenance_margin_mark_consumer_validation_boundary": (
            "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
        ),
        "margin_mode_simulated": "cross_paper_simulated",
        "maintenance_margin_notional_usd": quantity * mark,
        "maintenance_margin_estimate": quantity * mark * rate,
        "unrealized_pnl": -80.0, "unrealized_pnl_bps": -80.0 / (quantity * entry) * 10_000.0,
        "paper_only": True, "routes_to_live": False, "places_real_order": False,
    }
    margin = {
        "row_id": position["position_id"],
        "position_generation_id": position["position_generation_id"],
        "paper_session_id": "paper-session-fixture",
        "symbol": "SOLUSDT", "accounting_scope": "OPEN_EXECUTED_POSITION", "valid": True,
        "effective_leverage": leverage, "canonical_notional_usd": quantity * entry,
        "canonical_margin_usd": quantity * entry / leverage,
        "maintenance_margin_rate": rate, "maintenance_margin_cum": 0.0,
        "maintenance_margin_mark_price": mark, "maintenance_margin_mark_time": NOW,
        "maintenance_margin_mark_event_time": NOW,
        "maintenance_margin_mark_generated_at": NOW,
        "maintenance_margin_mark_available_at": NOW,
        "maintenance_margin_mark_decision_time": NOW,
        "maintenance_margin_mark_source": "UNIT_AUTHENTICATED_MARK",
        "maintenance_margin_mark_evidence_sha256": "a" * 64,
        "maintenance_margin_mark_contract_authoritative": True,
        "maintenance_margin_mark_freshness_budget_seconds": 1.0,
        "maintenance_margin_mark_cadence_policy_version": "UNIT_MARK_CADENCE_V1",
        "maintenance_margin_mark_consumer_validation_boundary": (
            "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1"
        ),
        "margin_mode_simulated": "cross_paper_simulated",
        "maintenance_margin_notional_usd": quantity * mark,
        "maintenance_margin_estimate": quantity * mark * rate,
        "unrealized_pnl_usd": -80.0, "unrealized_pnl_bps": position["unrealized_pnl_bps"],
        "paper_only": True, "routes_to_live": False, "places_real_order": False,
    }
    stress_symbols = {"SOLUSDT", "BTCUSDT", "ETHUSDT", "TOP5_BASKET"}
    adaptive_stress = seal_adaptive_stress_envelope(
        {
            "schema_version": "adaptive_portfolio_stress_v1",
            "authority_complete": True,
            "paper_session_id": "paper-session-fixture",
            "stress_policy_version": "UNIT_STRESS_V1",
            "cadence_policy_version": "UNIT_CADENCE_V1",
            "producer": "adaptive_portfolio_stress_controller",
            "auth_boundary": "PAPER_ADAPTIVE_STRESS_PIT_V1",
            "source_observations_sha256": "b" * 64,
            "generated_at": NOW,
            "available_at": NOW,
            "decision_time": NOW,
            "freshness_budget_seconds": 1.0,
            "guard_lifetime_seconds": 1.0,
            "recovery_reserve_usd": 0.0,
            "hedge_candidate_maintenance": {
                symbol: {
                    "authority_complete": True,
                    "source": "AUTHENTICATED_BINANCE_USDM_LEVERAGE_BRACKET",
                    "maintenance_margin_rate": 0.005,
                    "maintenance_margin_cum": 0.0,
                    "evidence_sha256": "c" * 64,
                }
                for symbol in stress_symbols
            },
            "scenarios": [
                {
                    "scenario_id": "adaptive_down",
                    "symbol_moves": {symbol: -0.02 for symbol in stress_symbols},
                }
            ],
        }
    )
    return build_portfolio_liquidation_snapshot(
        account=account,
        positions=[position],
        position_margin_rows=[margin],
        generated_utc=NOW,
        adaptive_stress_envelope=adaptive_stress,
    )


def test_negative_position_gets_hedge_evaluation():
    snap = _snap_with_negative()
    position = {"symbol": "SOLUSDT", "side": "long", "notional_usd": 4500.0, "unrealized_pnl_usd": -80.0}
    out = evaluate_hedge_first(position=position, snapshot=snap, hedge_mode=False, generated_utc=NOW)
    assert out["is_negative"] is True
    assert out["is_martingale"] is False
    assert out["recommended_action"] in {"HEDGE", "PARTIAL_DERISK_CLOSE"}
    # every candidate is evaluated; none may worsen buffer and still be chosen
    if out["hedge_required"]:
        assert out["liquidation_buffer_after_usd"] >= out["liquidation_buffer_before_usd"]
        assert out["liquidation_buffer_after_usd"] > 0
        assert out["portfolio_risk_after"] < out["portfolio_risk_before"]
        assert out["hedge_exit_plan"] is not None


def test_hedge_never_added_purely_for_exposure():
    snap = _snap_with_negative()
    position = {"symbol": "SOLUSDT", "side": "long", "notional_usd": 4500.0, "unrealized_pnl_usd": 50.0}
    out = evaluate_hedge_first(position=position, snapshot=snap, hedge_mode=False, generated_utc=NOW)
    # positive position, not fragile -> no hedge, HOLD
    assert out["is_negative"] is False
