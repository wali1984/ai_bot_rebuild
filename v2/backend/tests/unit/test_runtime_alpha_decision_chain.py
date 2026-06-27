from __future__ import annotations

from v2.backend.app.cli.run_runtime_alpha_decision_chain_remediation import build_one_shot_status
from v2.backend.app.services.adaptive_capital_allocator.strategy_weights import compute_adaptive_strategy_weights
from v2.backend.app.services.native_trainer.feedback_enrichment import build_strategy_hedge_exit_feedback
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import V2UnifiedFeatureTensorBuilder
from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig, evaluate_exit
from v2.backend.app.services.paper_trade_management.hedging import build_hedge_cost_benefit, evaluate_adaptive_hedge
from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.pnl_reconciliation import reconcile_paper_pnl
from v2.backend.app.services.paper_trade_management.position_state import PaperNetPosition
from v2.backend.app.services.risk_gateway.alpha_liquidity import evaluate_alpha_liquidity_risk


def _position(**overrides) -> PaperNetPosition:
    base = dict(
        position_id="paper_pos_test",
        symbol="BTCUSDT",
        side="long",
        net_quantity=1.0,
        avg_entry_price=100.0,
        opened_est="2026-06-14T00:00:00Z",
        source_signal_id="signal_test",
        prediction_id="pred_test",
        market_state_id="market_state_test",
        timeframe="1m",
        feature_snapshot_id="feature_snapshot_test",
        entry_market_state_id="market_state_test",
        strategy_id="trend_following",
        strategy_family="trend_following",
        strategy_selected_mode="trend_following",
        hedge_state="NO_HEDGE",
        hedge_reason="NO_HEDGE_CONTEXT",
        drawdown_at_entry=0.0,
        market_regime_at_entry="trend",
        liquidity_zone_context={"liquidity_zone_above": 106.0, "liquidity_zone_below": 98.0},
        liquidation_distance_context={"distance_to_long_liq_bps": 700.0, "distance_to_short_liq_bps": 550.0},
        microstructure_context={
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
            "bid_ask_spread_bps": 1.4,
            "microstructure_liquidity_depth": 25000.0,
        },
        squeeze_evidence_score=0.0,
        squeeze_evidence_source="DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        squeeze_evidence_components={"spread_stress": 0.0},
        entry_observed_spread_bps=1.4,
        entry_spread_source="V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        expected_slippage_bps=0.9,
        expected_slippage_source="MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        expected_slippage_modeled=True,
        fill_ids=["fill_test"],
        best_favorable_price=100.0,
        intra_trade_high_price=100.0,
        intra_trade_low_price=100.0,
        last_mark_price=100.0,
        last_mark_est="2026-06-14T00:00:00Z",
        # Trust envelope fields required for trainer_consumable=True
        decision_id="decision_test",
        mtf_snapshot_id="mtf_test",
        feature_cutoff="2026-06-13T23:59:59Z",
        decision_time="2026-06-14T00:00:00Z",
        available_at="2026-06-14T00:00:00Z",
        selected_action="long",
        model_version="v2_test",
        checkpoint_id="checkpoint_test",
        source_hashes={"model": "abc123", "feature": "def456"},
    )
    base.update(overrides)
    return PaperNetPosition(**base)


def test_liquidation_zone_enters_trainer_tensor() -> None:
    tensor = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="1m",
        payloads={
            "ohlcv": {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10, "candle_closed_confirmed": True},
            "liquidation_levels": {
                "nearest_liquidation_level_above": 106.0,
                "nearest_liquidation_level_below": 94.0,
                "distance_to_long_liq_bps": 500.0,
                "distance_to_short_liq_bps": 400.0,
                "liquidation_cluster_strength_long": 0.3,
                "liquidation_cluster_strength_short": 0.4,
                "liquidation_cascade_risk": 0.2,
            },
            "liquidity_zones": {
                "liquidity_zone_above": 105.0,
                "liquidity_zone_below": 95.0,
                "distance_to_liquidity_zone_bps": 250.0,
            },
            "orderbook": {"best_bid": 99.9, "best_ask": 100.1, "bid_size": 5, "ask_size": 4, "orderbook_wall_strength": 0.25},
            "microstructure": {"microstructure_liquidity_depth": 10000.0, "coinapi_wsds_tape_imbalance": 0.2},
        },
    )
    names = set(tensor.feature_names)
    for name in (
        "nearest_liquidation_level_above",
        "distance_to_long_liq_bps",
        "liquidity_zone_above",
        "distance_to_liquidity_zone_bps",
        "orderbook_wall_strength",
        "microstructure_liquidity_depth",
        "coinapi_wsds_tape_imbalance",
    ):
        assert name in names
        index = tensor.feature_names.index(name)
        assert tensor.missing_mask[index] == 0


def test_liquidation_proximity_affects_risk_orchestrator_decision() -> None:
    result = evaluate_alpha_liquidity_risk(
        action="long",
        context={
            "distance_to_long_liq_bps": 10.0,
            "distance_to_short_liq_bps": 400.0,
            "liquidation_cascade_risk": 0.2,
            "microstructure_liquidity_depth": 10000.0,
        },
    )
    assert result["allowed"] is False
    assert "LONG_LIQUIDATION_DISTANCE_TOO_CLOSE" in result["risk_blockers"]
    assert result["orchestrator_signal_adjustment"] == "block"


def test_strategy_weights_update_from_realized_outcomes() -> None:
    outcomes = [{"strategy_family": "trend_following", "realized_pnl_bps": 20.0} for _ in range(10)]
    outcomes += [{"strategy_family": "mean_reversion", "realized_pnl_bps": -20.0} for _ in range(10)]
    result = compute_adaptive_strategy_weights(outcomes)
    assert result["strategy_weights"]["trend_following"] > 1.0
    assert result["strategy_weights"]["mean_reversion"] < 1.0
    assert result["static_strategy_selection"] is False


def test_insufficient_sample_strategy_stays_capped() -> None:
    result = compute_adaptive_strategy_weights([{"strategy_family": "breakout", "realized_pnl_bps": 100.0}])
    assert result["strategy_weights"]["breakout"] <= 0.35


def test_hedge_requires_explicit_intent_and_exit_condition() -> None:
    result = evaluate_adaptive_hedge(
        position={"symbol": "BTCUSDT", "side": "long", "notional": 100.0},
        hedge_intent={"symbol": "BTCUSDT", "hedge_side": "short", "hedge_budget_usd": 10.0, "risk_approved": True},
    )
    assert result["hedge_allowed"] is False
    assert "HEDGE_INTENT_REQUIRED" in result["hedge_blockers"]
    assert "HEDGE_EXIT_CONDITION_REQUIRED" in result["hedge_blockers"]


def test_hedge_cost_benefit_is_tracked() -> None:
    result = build_hedge_cost_benefit(
        hedge_id="h1",
        hedge_notional_usd=10.0,
        fees=0.05,
        slippage=0.03,
        pnl_without_hedge=-2.0,
        pnl_with_hedge=-1.0,
    )
    assert result["hedge_cost_benefit_tracked"] is True
    assert result["net_hedge_benefit_usd"] == 0.92


def test_take_profit_closes_position() -> None:
    result = evaluate_exit(
        position=_position(),
        mark_price=102.0,
        generated_utc="2026-06-14T00:01:00Z",
        config=PaperExitConfig(take_profit_bps=150.0, profit_bank_bps=500.0),
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TAKE_PROFIT"


def test_stop_loss_closes_position() -> None:
    result = evaluate_exit(position=_position(), mark_price=99.0, generated_utc="2026-06-14T00:01:00Z", config=PaperExitConfig(stop_loss_bps=50.0))
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_STOP_LOSS"


def test_trailing_stop_closes_position() -> None:
    result = evaluate_exit(
        position=_position(best_favorable_price=105.0),
        mark_price=104.0,
        generated_utc="2026-06-14T00:01:00Z",
        config=PaperExitConfig(take_profit_bps=1000.0, profit_bank_bps=1000.0, trailing_stop_bps=50.0),
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_TRAILING_STOP"


def test_model_reversal_closes_position() -> None:
    result = evaluate_exit(
        position=_position(),
        mark_price=100.0,
        generated_utc="2026-06-14T00:01:00Z",
        config=PaperExitConfig(),
        model_context={"model_reversal": True},
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_1_MODEL_REVERSAL_EXIT"


def test_profit_bank_locks_realized_gains() -> None:
    result = evaluate_exit(
        position=_position(),
        mark_price=102.0,
        generated_utc="2026-06-14T00:01:00Z",
        config=PaperExitConfig(take_profit_bps=300.0, profit_bank_bps=180.0),
    )
    assert result["should_close"] is True
    assert result["close_reason"] == "TIER_2_PROFIT_BANK"


def test_paper_pnl_reconciles_to_fills_positions_marks() -> None:
    position = _position(last_mark_price=102.0)
    close_event, _ = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=102.0,
        exit_time="2026-06-14T00:01:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
    )
    result = reconcile_paper_pnl(
        fills=[{"fill_id": "fill_test", "symbol": "BTCUSDT", "quantity": 1.0, "fill_price": 100.0}],
        open_positions=[],
        closed_trades=[close_event],
        mark_prices={"BTCUSDT": {"price": 102.0}},
        starting_equity=1000.0,
    )
    assert result["reconciliation_status"] == "RECONCILED"
    assert result["realized_pnl"] > 0.0


def test_trainer_consumes_strategy_hedge_exit_feedback() -> None:
    position = _position()
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=102.0,
        exit_time="2026-06-14T00:01:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
    )
    row = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=outcome)
    assert row["trainer_consumable"] is True
    assert row["strategy_family"] == "trend_following"
    assert row["liquidity_zone_context"]["liquidity_zone_above"] == 106.0


def test_runtime_alpha_one_shot_does_not_claim_guaranteed_10k_or_live_mutation() -> None:
    status = build_one_shot_status()
    assert status["gate"] == "V2_RUNTIME_ALPHA_DECISION_CHAIN_REMEDIATION_READY"
    assert status["monthly_10k_goal_feasibility_after_alpha_remediation"]["guaranteed_profit"] is False
    assert status["monthly_10k_goal_feasibility_after_alpha_remediation"]["goal_status"] == "INSUFFICIENT_SAMPLE_FOR_10K_TARGET"
    assert status["safety"]["live_order_submitted"] is False
    assert status["safety"]["leverage_changed"] is False
    assert status["safety"]["margin_mode_changed"] is False
