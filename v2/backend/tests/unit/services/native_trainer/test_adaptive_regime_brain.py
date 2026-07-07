from __future__ import annotations

from v2.backend.app.services.native_trainer.adaptive_regime_brain import (
    build_adaptive_regime_brain_status,
    build_strategy_quarantine_status,
    build_strategy_selector_bucket_performance,
)
from v2.backend.app.services.strategy_router.service import REQUIRED_STRATEGY_MODES


def _decision(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "prediction_id": "pred_1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "strategy_mode": "trend_continuation",
        "market_regime": "TREND",
        "size_multiplier": 1.0,
        "regime_features": {
            "trend_strength": 0.74,
            "range_chop_score": 0.21,
            "volatility_expansion": 0.03,
            "atr_percentile": 0.64,
            "funding_skew": 0.1,
            "open_interest_change": 1.2,
            "long_short_ratio": 0.9,
            "liquidation_cluster_proximity": 24.0,
            "orderbook_imbalance": 0.2,
            "spread_depth_slippage": {
                "bid_ask_spread_bps": 2.0,
                "orderbook_depth_usd": 1_000_000.0,
                "expected_slippage_bps": 0.8,
            },
            "aggressive_flow": 0.12,
            "cross_asset_btc_eth_sol_regime": "risk_on",
            "market_wide_risk": "risk_on",
            "fakeout_reversal_probability": 0.08,
        },
    }
    row.update(overrides)
    return row


def _outcome(
    prediction_id: str,
    *,
    realized: float,
    strategy: str = "trend_continuation",
    side: str = "long",
) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": side,
        "strategy_mode": strategy,
        "market_regime": "TREND",
        "realized_after_cost_return_bps": realized,
    }


def test_adaptive_regime_brain_reports_required_feature_coverage() -> None:
    status = build_adaptive_regime_brain_status([_decision()], outcome_rows=[])

    assert status["status"] == "ADAPTIVE_REGIME_BRAIN_READY"
    assert status["required_strategy_modes"] == list(REQUIRED_STRATEGY_MODES)
    assert status["regime_feature_coverage"]["all_rows_have_required_features"] is True
    assert status["pass_conditions"]["all_required_regime_features_present"] is True
    assert status["no_live_mutation"] is True


def test_adaptive_regime_brain_blocks_when_required_feature_missing() -> None:
    features = dict(_decision()["regime_features"])  # type: ignore[arg-type]
    features.pop("trend_strength")

    status = build_adaptive_regime_brain_status([_decision(regime_features=features)], outcome_rows=[])

    assert status["status"] == "ADAPTIVE_REGIME_BRAIN_BLOCKED_FEATURE_COVERAGE"
    assert "trend_strength" in status["regime_feature_coverage"]["missing_features"]


def test_strategy_selector_bucket_performance_flags_negative_bucket() -> None:
    performance = build_strategy_selector_bucket_performance(
        [
            _outcome("loss_1", realized=-10.0),
            _outcome("loss_2", realized=-5.0),
            _outcome("win_1", realized=2.0, strategy="range_scalp", side="short"),
            _outcome("win_2", realized=4.0, strategy="range_scalp", side="short"),
        ],
        min_bucket_samples=2,
    )

    negative = [row for row in performance["buckets"] if row["negative_bucket"] is True]
    assert len(negative) == 1
    assert negative[0]["bucket_key"] == "BTCUSDT|1m|trend_continuation|TREND|long"
    assert negative[0]["quarantine_required"] is True
    assert performance["no_live_mutation"] is True


def test_strategy_quarantine_status_flags_full_size_negative_bucket_violation() -> None:
    performance = build_strategy_selector_bucket_performance(
        [_outcome("loss_1", realized=-10.0), _outcome("loss_2", realized=-5.0)],
        min_bucket_samples=2,
    )
    clean = build_strategy_quarantine_status(
        performance,
        decision_rows=[
            _decision(
                bucket_quarantined=True,
                strategy_bucket_key={
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "strategy_mode": "trend_continuation",
                    "market_regime": "TREND",
                    "position_state": "FLAT",
                },
            )
        ],
    )
    violating = build_strategy_quarantine_status(
        performance,
        decision_rows=[
            _decision(
                bucket_quarantined=False,
                strategy_bucket_key={
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "strategy_mode": "trend_continuation",
                    "market_regime": "TREND",
                    "position_state": "FLAT",
                },
            )
        ],
    )

    assert clean["status"] == "STRATEGY_QUARANTINE_PASS"
    assert clean["no_negative_bucket_continues_full_size"] is True
    assert violating["status"] == "STRATEGY_QUARANTINE_BLOCKED"
    assert violating["violations"][0]["violation"] == "NEGATIVE_BUCKET_CONTINUED_FULL_SIZE"
