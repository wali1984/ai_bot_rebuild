from __future__ import annotations

from v2.backend.app.services.strategy_router import (
    MODE_BREAKOUT,
    MODE_NO_TRADE,
    MODE_REDUCE_SIZE,
    MODE_TREND,
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
