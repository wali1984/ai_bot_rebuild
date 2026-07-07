from __future__ import annotations

from v2.backend.app.services.strategy_router import (
    MODE_BREAKOUT,
    MODE_NO_TRADE,
    MODE_REDUCE_SIZE,
    MODE_TREND,
    REQUIRED_REGIME_FEATURES,
    REQUIRED_STRATEGY_MODES,
    STRATEGY_LIQUIDITY_SWEEP_REVERSAL,
    STRATEGY_RISK_OFF_NO_TRADE,
    STRATEGY_TREND_CONTINUATION,
    route_strategy,
)


def _prediction(
    timeframe: str,
    *,
    action: str,
    confidence: float,
    expected_move_after_cost_bps: float,
    feature_cutoff: str = "2026-06-10T10:00:00Z",
) -> dict[str, object]:
    return {
        "timeframe": timeframe,
        "selected_action": action,
        "confidence_calibrated": confidence,
        "expected_move_after_cost_bps": expected_move_after_cost_bps,
        "feature_cutoff": feature_cutoff,
    }


def _envelope() -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-10T10:01:00Z",
        "confidence_calibrated": 0.71,
        "data_quality_score": 95.0,
        "expected_move_after_cost_bps": 12.0,
    }


def test_htf_bullish_and_ltf_bullish_allow_long() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.65, expected_move_after_cost_bps=12.0),
            _prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=22.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_TREND
    assert result["block_reason"] is None
    assert "long" in result["allowed_actions"]


def test_htf_bearish_and_ltf_bearish_allow_short() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[
            _prediction("1m", action="short", confidence=0.65, expected_move_after_cost_bps=-12.0),
            _prediction("15m", action="short", confidence=0.8, expected_move_after_cost_bps=-22.0),
        ],
        ppo_proposed_action="short",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_TREND
    assert result["block_reason"] is None
    assert "short" in result["allowed_actions"]


def test_htf_bullish_ltf_bearish_reduces_size() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[
            _prediction("1m", action="short", confidence=0.7, expected_move_after_cost_bps=-8.0),
            _prediction("5m", action="long", confidence=0.72, expected_move_after_cost_bps=10.0),
            _prediction("15m", action="long", confidence=0.82, expected_move_after_cost_bps=20.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_REDUCE_SIZE
    assert result["block_reason"] is None
    assert result["size_multiplier"] < 1.0


def test_masa_future_cutoff_blocks() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[
            _prediction(
                "15m",
                action="long",
                confidence=0.8,
                expected_move_after_cost_bps=20.0,
                feature_cutoff="2026-06-10T10:02:00Z",
            ),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "MASA_FUTURE_CUTOFF_BLOCK"


def test_low_execution_success_blocks() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[_prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=20.0)],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.2},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD"


def test_major_move_evidence_breaks_no_trade_mode_paper_only() -> None:
    envelope = {
        **_envelope(),
        "paper_only": True,
        "mode": "paper",
        "paper_major_move_candidate": True,
        "major_move_signal_id": "major_move_btc",
        "major_move_direction": "short",
        "major_move_evidence_score": 0.76,
        "expected_move_after_cost_bps": -45.0,
    }

    result = route_strategy(
        market_state_envelope=envelope,
        masa_predictions=[_prediction("15m", action="short", confidence=0.8, expected_move_after_cost_bps=-45.0)],
        ppo_proposed_action="short",
        current_position_state="FLAT",
        recent_execution_success_metrics={
            "execution_success_probability": 0.0,
            "execution_success_metric_source": "V2_PAPER_ACCEPTED_BLOCKED_FALLBACK",
            "execution_success_sample_status": "NO_CLOSED_OUTCOMES_FALLBACK",
            "closed_trade_outcome_count": 0,
        },
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] in {MODE_BREAKOUT, MODE_REDUCE_SIZE}
    assert result["block_reason"] is None
    assert "short" in result["allowed_actions"]
    assert "PAPER_MAJOR_MOVE_EVIDENCE_BREAKOUT" in result["reason_codes"]


def test_paper_loss_quarantine_keys_force_no_trade_before_allocation() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "timeframe": "15m",
            "confidence_calibrated": 0.65,
            "paper_only": True,
            "mode": "paper",
            "paper_loss_quarantine_status": "ACTIVE_WITH_QUARANTINES",
            "paper_loss_quarantine_blocked_bucket_keys": [
                "side:short",
                "timeframe:15m",
                "regime:TREND",
                "strategy_regime:trend_continuation|TREND",
                "confidence_regime:0.6-0.7|TREND",
            ],
        },
        masa_predictions=[
            _prediction("1m", action="short", confidence=0.72, expected_move_after_cost_bps=-16.0),
            _prediction("15m", action="short", confidence=0.82, expected_move_after_cost_bps=-26.0),
        ],
        ppo_proposed_action="short",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["strategy_mode"] == STRATEGY_RISK_OFF_NO_TRADE
    assert result["block_reason"] == "PAPER_LOSS_BUCKET_QUARANTINE"
    assert "short" not in result["allowed_actions"]
    assert result["bucket_quarantined"] is False
    assert "PAPER_LOSS_BUCKET_QUARANTINE" in result["reason_codes"]
    assert "side:short" in result["paper_loss_quarantine_matched_bucket_keys"]
    assert "timeframe:15m" in result["paper_loss_quarantine_matched_bucket_keys"]
    assert "strategy_regime:trend_continuation|TREND" in result[
        "paper_loss_quarantine_candidate_bucket_keys"
    ]
    assert result["paper_loss_quarantine_status"] == "ACTIVE_WITH_QUARANTINES"


def test_paper_loss_quarantine_keys_do_not_block_non_paper_routing() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "timeframe": "15m",
            "confidence_calibrated": 0.65,
            "paper_only": False,
            "mode": "live_shadow",
            "paper_loss_quarantine_status": "ACTIVE_WITH_QUARANTINES",
            "paper_loss_quarantine_blocked_bucket_keys": [
                "side:short",
                "timeframe:15m",
                "regime:TREND",
            ],
        },
        masa_predictions=[
            _prediction("1m", action="short", confidence=0.72, expected_move_after_cost_bps=-16.0),
            _prediction("15m", action="short", confidence=0.82, expected_move_after_cost_bps=-26.0),
        ],
        ppo_proposed_action="short",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_TREND
    assert result["block_reason"] is None
    assert "short" in result["allowed_actions"]
    assert result["paper_loss_quarantine_matched_bucket_keys"] == []


def test_weak_signal_remains_no_trade() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "paper_only": True,
            "mode": "paper",
            "paper_major_move_candidate": True,
            "major_move_direction": "long",
            "major_move_evidence_score": 0.30,
        },
        masa_predictions=[_prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=5.0)],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.2},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD"


def test_strategy_weights_can_select_non_no_trade_family() -> None:
    result = route_strategy(
        market_state_envelope={**_envelope(), "paper_only": True, "mode": "paper"},
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.7, expected_move_after_cost_bps=18.0),
            _prediction("15m", action="long", confidence=0.75, expected_move_after_cost_bps=24.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={
            "execution_success_probability": 0.0,
            "execution_success_metric_source": "V2_PAPER_ACCEPTED_BLOCKED_FALLBACK",
            "execution_success_sample_status": "NO_CLOSED_OUTCOMES_FALLBACK",
        },
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] in {MODE_TREND, MODE_REDUCE_SIZE}
    assert result["block_reason"] is None
    assert "long" in result["allowed_actions"]


def test_live_gates_do_not_loosen() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "paper_only": False,
            "paper_major_move_candidate": True,
            "major_move_signal_id": "major_move_btc",
            "major_move_direction": "long",
            "major_move_evidence_score": 0.95,
        },
        masa_predictions=[_prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=45.0)],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={
            "execution_success_probability": 0.0,
            "execution_success_metric_source": "V2_PAPER_ACCEPTED_BLOCKED_FALLBACK",
            "execution_success_sample_status": "NO_CLOSED_OUTCOMES_FALLBACK",
        },
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD"


def test_bad_data_quality_blocks() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[_prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=20.0)],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=45.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "DATA_QUALITY_BELOW_THRESHOLD"


def test_position_state_conflict_blocks() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[_prediction("15m", action="short", confidence=0.8, expected_move_after_cost_bps=-20.0)],
        ppo_proposed_action="short",
        current_position_state="LONG",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "POSITION_STATE_CONFLICT_BLOCK"


def test_invalid_position_state_blocks_directional_trade() -> None:
    result = route_strategy(
        market_state_envelope=_envelope(),
        masa_predictions=[_prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=20.0)],
        ppo_proposed_action="long",
        current_position_state="INVALID_CONFLICTING_OPEN_POSITIONS",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["block_reason"] == "POSITION_STATE_CONFLICT_BLOCK"


def test_router_emits_required_regime_features_and_canonical_strategy_mode() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "trend_strength": 0.74,
            "range_chop_score": 0.21,
            "atr_percentile": 0.64,
            "fakeout_reversal_probability": 0.08,
            "cross_asset_btc_eth_sol_regime": "btc_eth_sol_risk_on",
            "market_wide_risk": "risk_on",
            "liquidity_context": {"orderbook_depth_usd": 1_000_000.0, "depth_imbalance": 0.2},
            "liquidation_context": {
                "liquidation_sweep_target_short_distance_bps": 24.0,
                "liquidation_sweep_target_long_distance_bps": 60.0,
            },
            "microstructure_context": {
                "orderbook_imbalance": 0.2,
                "bid_ask_spread_bps": 2.0,
                "order_flow_imbalance": 0.12,
            },
            "oi_funding_context": {
                "funding_bps": 0.1,
                "oi_change_pct": 1.2,
                "long_short_ratio": 0.9,
            },
            "public_intel_context": {"market_breadth_score": 0.67},
        },
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.7, expected_move_after_cost_bps=18.0),
            _prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=24.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={
            "volatility_expansion": 0.03,
            "liquidity_score": 0.8,
            "bid_ask_spread_bps": 2.0,
            "expected_slippage_bps": 0.8,
        },
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["strategy_mode"] == STRATEGY_TREND_CONTINUATION
    assert result["strategy_modes_supported"] == list(REQUIRED_STRATEGY_MODES)
    assert set(result["regime_feature_status"]["required_features"]) == set(REQUIRED_REGIME_FEATURES)
    assert result["regime_feature_status"]["all_required_features_present"] is True
    assert result["regime_features"]["open_interest_change"] == 1.2
    assert result["strategy_bucket_key"]["strategy_mode"] == STRATEGY_TREND_CONTINUATION
    assert result["bucket_quarantined"] is False


def test_negative_strategy_bucket_quarantines_without_using_other_bucket_profit() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "bucket_performance": {
                "profit_factor": 0.72,
                "expectancy_bps": -3.4,
                "sample_count": 18,
            },
        },
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.72, expected_move_after_cost_bps=18.0),
            _prediction("15m", action="long", confidence=0.82, expected_move_after_cost_bps=25.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={
            "execution_success_probability": 0.9,
            "portfolio_profit_factor": 2.5,
            "portfolio_expectancy_bps": 9.0,
        },
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["selected_mode"] == MODE_NO_TRADE
    assert result["strategy_mode"] == STRATEGY_RISK_OFF_NO_TRADE
    assert result["block_reason"] == "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE"
    assert result["bucket_quarantined"] is True
    assert result["bucket_performance_state"]["profit_factor"] == 0.72
    assert "long" not in result["allowed_actions"]


def test_microstructure_trust_score_none_does_not_block() -> None:
    # None trust score (monitor not running) must NOT produce DATA_UNRELIABLE.
    # Previous behavior allowed trading when trust score was simply absent.
    result = route_strategy(
        market_state_envelope=_envelope(),  # no microstructure_trust_score key
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.65, expected_move_after_cost_bps=12.0),
            _prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=22.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )
    assert "DATA_UNRELIABLE" not in result["regime_labels"]
    assert "MICROSTRUCTURE_TRUST_SCORE_MISSING" not in result["reason_codes"]
    assert result["block_reason"] is None
    assert result["selected_mode"] == MODE_TREND


def test_microstructure_trust_score_below_threshold_blocks() -> None:
    # Explicit low trust score (monitor running, score computed as 0.2) must block with DATA_UNRELIABLE.
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "microstructure_trust_score": 0.2,  # below shadow_block_threshold=0.45
        },
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.65, expected_move_after_cost_bps=12.0),
            _prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=22.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )
    assert "DATA_UNRELIABLE" in result["regime_labels"]
    assert "MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED" in result["reason_codes"]
    assert result["block_reason"] == "MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED"
    assert result["selected_mode"] == MODE_NO_TRADE


def test_microstructure_action_no_trade_blocks() -> None:
    # Explicit microstructure_action=NO_TRADE must still produce DATA_UNRELIABLE block.
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "microstructure_action": "NO_TRADE",
        },
        masa_predictions=[
            _prediction("1m", action="long", confidence=0.65, expected_move_after_cost_bps=12.0),
            _prediction("15m", action="long", confidence=0.8, expected_move_after_cost_bps=22.0),
        ],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.01, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )
    assert "DATA_UNRELIABLE" in result["regime_labels"]
    assert "MICROSTRUCTURE_ACTION_NO_TRADE" in result["reason_codes"]
    assert result["block_reason"] == "MICROSTRUCTURE_ACTION_NO_TRADE"


def test_liquidation_fakeout_context_routes_to_liquidity_sweep_reversal() -> None:
    result = route_strategy(
        market_state_envelope={
            **_envelope(),
            "fakeout_reversal_probability": 0.66,
            "liquidation_context": {
                "liquidation_sweep_target_short_distance_bps": 12.0,
                "liquidation_short_strength": 8.0,
                "liquidation_long_strength": 2.0,
            },
        },
        masa_predictions=[],
        ppo_proposed_action="long",
        current_position_state="FLAT",
        recent_execution_success_metrics={"execution_success_probability": 0.9},
        volatility_liquidity_state={"volatility": 0.05, "liquidity_score": 0.8, "bid_ask_spread_bps": 3.0},
        data_quality_score=95.0,
        current_drawdown_risk_state={"current_drawdown_bps": 10.0},
    )

    assert result["strategy_mode"] == STRATEGY_LIQUIDITY_SWEEP_REVERSAL
    assert result["block_reason"] is None
    assert "long" in result["allowed_actions"]
