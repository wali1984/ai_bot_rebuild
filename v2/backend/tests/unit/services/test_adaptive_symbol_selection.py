from __future__ import annotations

import math

import pytest

from v2.backend.app.services.adaptive_symbol_selection import (
    AdaptiveSymbolSelectionPolicy,
    select_adaptive_symbol_universe,
)

DECISION_TIME = "2026-07-20T05:10:00Z"


def _evidence(symbol: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": symbol,
        "exchange_confirmed": True,
        "candle_final": True,
        "candle_close_time": "2026-07-20T05:05:00Z",
        "feature_cutoff": "2026-07-20T05:05:00Z",
        "event_time": "2026-07-20T05:05:00.100Z",
        "ingested_at": "2026-07-20T05:05:00.200Z",
        "available_at": "2026-07-20T05:05:00.200Z",
        "market_event_time": "2026-07-20T05:09:30.000Z",
        "market_ingested_at": "2026-07-20T05:09:30.050Z",
        "market_available_at": "2026-07-20T05:09:30.050Z",
        "generated_at": "2026-07-20T05:09:50Z",
        "training_data_ready": True,
        "closed_candle_count": 100,
        "market_data_coverage_ratio": 1.0,
        "closed_quote_volume_usd": 100_000_000.0,
        "spread_bps": 0.5,
        "top_book_depth_usd": 500_000.0,
        "realized_volatility_bps": 50.0,
        "absolute_move_bps": 100.0,
    }
    row.update(overrides)
    return row


def _proven_validation() -> dict[str, object]:
    return {
        "validation_sample_count": 90,
        "after_cost_expectancy_bps": 12.0,
        "after_cost_ci_lower_bps": 5.0,
        "validation_out_of_sample": True,
        "validation_after_cost": True,
        "validation_leakage_free": True,
        "validation_cutoff": "2026-07-20T04:00:00Z",
        "validation_event_time": "2026-07-20T04:00:01Z",
        "validation_ingested_at": "2026-07-20T04:00:02Z",
        "validation_available_at": "2026-07-20T04:00:03Z",
        "validation_generated_at": "2026-07-20T04:00:04Z",
    }


def test_unsafe_custom_policy_bounds_fail_closed() -> None:
    invalid_policies = (
        AdaptiveSymbolSelectionPolicy(min_market_data_coverage_ratio=0.0),
        AdaptiveSymbolSelectionPolicy(max_feature_age_seconds=0.0),
        AdaptiveSymbolSelectionPolicy(max_executability_age_seconds=-1.0),
        AdaptiveSymbolSelectionPolicy(min_closed_quote_volume_usd=-1.0),
        AdaptiveSymbolSelectionPolicy(min_top_book_depth_usd=0.0),
        AdaptiveSymbolSelectionPolicy(max_spread_bps=0.0),
        AdaptiveSymbolSelectionPolicy(target_absolute_move_bps=-1.0),
        AdaptiveSymbolSelectionPolicy(min_validation_samples=0),
        AdaptiveSymbolSelectionPolicy(min_after_cost_expectancy_bps=-1.0),
        AdaptiveSymbolSelectionPolicy(target_after_cost_expectancy_bps=0.0),
        AdaptiveSymbolSelectionPolicy(min_after_cost_ci_lower_bps=-1.0),
        AdaptiveSymbolSelectionPolicy(target_after_cost_ci_lower_bps=0.0),
        AdaptiveSymbolSelectionPolicy(preferred_major_score_bonus=-0.01),
        AdaptiveSymbolSelectionPolicy(training_max_symbols=1.5),  # type: ignore[arg-type]
    )

    for policy in invalid_policies:
        with pytest.raises(ValueError, match="adaptive_symbol_policy_"):
            select_adaptive_symbol_universe(
                [_evidence("BTCUSDT")],
                decision_time=DECISION_TIME,
                policy=policy,
            )


def test_training_and_trading_eligibility_are_separate_and_preference_is_order_only() -> None:
    doge = _evidence("DOGEUSDT", **_proven_validation())
    btc = _evidence(
        "BTCUSDT",
        closed_quote_volume_usd=20_000_000.0,
        top_book_depth_usd=50_000.0,
        **_proven_validation(),
    )
    eth_without_validation = _evidence("ETHUSDT")

    payload = select_adaptive_symbol_universe(
        [doge, btc, eth_without_validation], decision_time=DECISION_TIME
    )

    assert payload["training_eligible_symbols"][:2] == ["BTCUSDT", "ETHUSDT"]
    assert payload["trading_eligible_symbols"][0] == "BTCUSDT"
    assert "DOGEUSDT" in payload["trading_eligible_symbols"]
    assert "ETHUSDT" not in payload["trading_eligible_symbols"]
    eth = payload["symbol_explanations"]["ETHUSDT"]
    assert eth["training_eligible"] is True
    assert eth["trading_eligible"] is False
    assert eth["predictability_evidence_state"] == "unavailable"
    assert "insufficient_oos_validation_samples" in eth["trading_blockers"]
    assert payload["selection_is_execution_authorization"] is False


def test_explicit_preference_extension_cannot_replace_btc_eth_sol() -> None:
    payload = select_adaptive_symbol_universe(
        [_evidence("DOGEUSDT")],
        decision_time=DECISION_TIME,
        preferred_symbols=("DOGEUSDT",),
    )

    assert payload["preferred_symbols"] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "DOGEUSDT",
    ]


def test_current_prediction_confidence_cannot_substitute_for_oos_after_cost_evidence() -> None:
    row = _evidence(
        "BTCUSDT",
        current_prediction_confidence=0.999,
        current_prediction_expected_after_cost_bps=500.0,
    )

    payload = select_adaptive_symbol_universe([row], decision_time=DECISION_TIME)

    assert payload["training_eligible_symbols"] == ["BTCUSDT"]
    assert payload["trading_eligible_symbols"] == []
    assert payload["metrics"]["predictability_proven_symbol_count"] == 0
    assert payload["uses_current_prediction_confidence_as_proven_benefit"] is False


def test_future_stale_nonfinal_and_nan_evidence_fail_closed() -> None:
    future = _evidence(
        "BTCUSDT",
        market_available_at="2026-07-20T05:11:00Z",
        generated_at="2026-07-20T05:11:01Z",
    )
    stale = _evidence(
        "ETHUSDT",
        candle_close_time="2026-07-20T04:00:00Z",
        feature_cutoff="2026-07-20T04:00:00Z",
        event_time="2026-07-20T04:00:00.100Z",
        ingested_at="2026-07-20T04:00:00.200Z",
        available_at="2026-07-20T04:00:00.200Z",
    )
    dirty = _evidence(
        "SOLUSDT",
        candle_final=False,
        realized_volatility_bps=math.nan,
    )

    payload = select_adaptive_symbol_universe([future, stale, dirty], decision_time=DECISION_TIME)

    assert payload["training_eligible_symbols"] == []
    assert payload["trading_eligible_symbols"] == []
    assert (
        "executability_available_after_decision_time"
        in payload["symbol_explanations"]["BTCUSDT"]["training_blockers"]
    )
    assert (
        "closed_market_data_stale" in payload["symbol_explanations"]["ETHUSDT"]["training_blockers"]
    )
    sol_blockers = payload["symbol_explanations"]["SOLUSDT"]["training_blockers"]
    assert "candle_not_explicitly_final" in sol_blockers
    assert "missing_or_nonfinite_realized_volatility_bps" in sol_blockers


def test_unrepresentable_clock_fails_only_its_evidence_row() -> None:
    invalid = _evidence("BTCUSDT", generated_at=1.0e300)
    valid = _evidence("ETHUSDT")

    payload = select_adaptive_symbol_universe(
        [invalid, valid], decision_time=DECISION_TIME
    )

    assert payload["training_eligible_symbols"] == ["ETHUSDT"]
    assert (
        "missing_or_invalid_generated_at"
        in payload["symbol_explanations"]["BTCUSDT"]["training_blockers"]
    )


def test_preferred_major_never_bypasses_pipeline_health() -> None:
    payload = select_adaptive_symbol_universe(
        [_evidence("BTCUSDT", training_data_ready=False, **_proven_validation())],
        decision_time=DECISION_TIME,
    )

    assert payload["training_selected_symbols"] == []
    assert payload["trading_selected_symbols"] == []
    status = payload["preferred_symbol_status"]["BTCUSDT"]
    assert status["training_eligible"] is False
    assert status["trading_eligible"] is False
    assert status["preference_bypassed_health_checks"] is False


def test_hysteresis_caps_normal_churn_but_forces_health_removal() -> None:
    policy = AdaptiveSymbolSelectionPolicy(
        max_training_additions_per_cycle=1,
        max_training_removals_per_cycle=0,
        training_max_symbols=3,
    )
    btc_unhealthy = _evidence("BTCUSDT", training_data_ready=False)
    eth_below_exit_but_healthy = _evidence(
        "ETHUSDT",
        market_data_coverage_ratio=0.95,
        closed_quote_volume_usd=policy.min_closed_quote_volume_usd,
        spread_bps=policy.max_spread_bps,
        top_book_depth_usd=policy.min_top_book_depth_usd,
        realized_volatility_bps=policy.min_realized_volatility_bps,
        absolute_move_bps=0.0,
        candle_close_time="2026-07-20T04:55:01Z",
        feature_cutoff="2026-07-20T04:55:01Z",
        event_time="2026-07-20T04:55:01.100Z",
        ingested_at="2026-07-20T04:55:01.200Z",
        available_at="2026-07-20T04:55:01.200Z",
    )
    sol_new = _evidence("SOLUSDT")

    payload = select_adaptive_symbol_universe(
        [btc_unhealthy, eth_below_exit_but_healthy, sol_new],
        decision_time=DECISION_TIME,
        previous_state={
            "training_selected_symbols": ["BTCUSDT", "ETHUSDT"],
            "trading_selected_symbols": [],
        },
        policy=policy,
    )

    turnover = payload["turnover"]["training"]
    assert turnover["forced_health_removals"] == ["BTCUSDT"]
    assert turnover["deferred_exit_symbols"] == ["ETHUSDT"]
    assert turnover["added_symbols"] == ["SOLUSDT"]
    assert payload["training_selected_symbols"] == ["ETHUSDT", "SOLUSDT"]


def test_duplicate_symbol_evidence_fails_closed() -> None:
    payload = select_adaptive_symbol_universe(
        [_evidence("BTCUSDT"), _evidence("BTCUSDT", **_proven_validation())],
        decision_time=DECISION_TIME,
    )

    assert payload["training_eligible_symbols"] == []
    assert payload["trading_eligible_symbols"] == []
    assert payload["metrics"]["duplicate_symbol_row_count"] == 1
    assert (
        "duplicate_symbol_evidence"
        in payload["symbol_explanations"]["BTCUSDT"]["training_blockers"]
    )


def test_trading_selection_is_always_subset_of_current_training_selection() -> None:
    policy = AdaptiveSymbolSelectionPolicy(
        training_max_symbols=1,
        trading_max_symbols=2,
    )
    payload = select_adaptive_symbol_universe(
        [
            _evidence("BTCUSDT", **_proven_validation()),
            _evidence("ETHUSDT", **_proven_validation()),
        ],
        decision_time=DECISION_TIME,
        policy=policy,
    )

    assert payload["training_selected_symbols"] == ["BTCUSDT"]
    assert payload["trading_selected_symbols"] == ["BTCUSDT"]
    assert payload["trading_selected_subset_of_training_selected"] is True
    assert payload["turnover"]["trading"]["cross_scope_excluded_symbols"] == ["ETHUSDT"]
    assert (
        "trading_excluded_outside_current_training_scope"
        in payload["symbol_explanations"]["ETHUSDT"]["selection_reasons"]
    )
