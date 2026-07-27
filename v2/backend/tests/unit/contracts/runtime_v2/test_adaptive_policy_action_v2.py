from __future__ import annotations

from v2.backend.app.contracts.runtime_v2.adaptive_policy_action_v2 import (
    AdaptivePolicyActionV2,
)


def _base(**overrides):
    kw = dict(
        decision_id="dec-1",
        state_id="state-1",
        checkpoint_generation=4,
        policy_id="policy-1",
        strategy_family="momentum",
        selected_action="DIRECTIONAL",
        primary_symbol="OPUSDT",
        primary_timeframe="1h",
        primary_side="long",
        target_exposure_usd=100.0,
        target_notional_usd=100.0,
        leverage=3.0,
        margin_mode_simulation="ISOLATED",
        margin_allocation_usd=33.3,
        entry_style="LIMIT_MAKER",
        entry_price_policy="MID_MINUS_SPREAD_FRACTION",
        maximum_entry_slippage=5.0,
        order_duration_policy="GTC_BOUNDED",
        protective_stop_policy="ATR_SCALED",
        stop_price=1.23,
        stop_distance=45.0,
        partial_reduction_policy="LADDERED",
        profit_exit_policy="EXPECTED_UTILITY_TRAIL",
        time_exit_policy="HORIZON_BOUNDED",
        expected_holding_horizon="4h",
        hedge_enabled=False,
        hedge_legs=[],
        hedge_ratios=[],
        expected_after_cost_return=12.0,
        expected_return_distribution={"mean_bps": 12.0, "std_bps": 40.0},
        expected_drawdown_contribution=8.0,
        expected_tail_loss=25.0,
        expected_fill_probability=0.8,
        expected_slippage=3.0,
        expected_market_impact=1.0,
        expected_adverse_selection=0.2,
        expected_information_gain=0.4,
        flat_probability=0.1,
        action_distribution={"DIRECTIONAL": 0.7, "FLAT": 0.3},
        policy_uncertainty=0.25,
    )
    kw.update(overrides)
    return AdaptivePolicyActionV2(**kw)


def test_valid_directional_action_passes():
    assert _base().validate() == []


def test_valid_flat_action_is_non_terminal():
    a = _base(
        selected_action="FLAT",
        primary_symbol=None,
        primary_timeframe=None,
        primary_side=None,
        target_notional_usd=0.0,
        target_exposure_usd=0.0,
        margin_allocation_usd=0.0,
        action_distribution={"FLAT": 0.6, "DIRECTIONAL": 0.4},
        flat_probability=0.6,
        expected_information_gain=0.5,
    )
    assert a.validate() == []


def test_directional_requires_mandatory_stop():
    reasons = _base(protective_stop_policy="NONE", stop_price=None, stop_distance=None).validate()
    assert "DIRECTIONAL_MANDATORY_STOP_MISSING" in reasons


def test_directional_requires_positive_notional():
    reasons = _base(target_notional_usd=0.0).validate()
    assert "DIRECTIONAL_TARGET_NOTIONAL_NOT_POSITIVE" in reasons


def test_action_distribution_must_normalize():
    reasons = _base(action_distribution={"DIRECTIONAL": 0.7, "FLAT": 0.1}).validate()
    assert any(x.startswith("ACTION_DISTRIBUTION_NOT_NORMALIZED") for x in reasons)


def test_probability_domain_enforced():
    reasons = _base(expected_fill_probability=1.5).validate()
    assert "PROBABILITY_DOMAIN_INVALID:expected_fill_probability" in reasons


def test_live_authority_is_hard_blocked():
    reasons = _base(places_real_order=True).validate()
    assert "PLACES_REAL_ORDER_NOT_FALSE" in reasons
    reasons2 = _base(routes_to_live=True).validate()
    assert "ROUTES_TO_LIVE_NOT_FALSE" in reasons2
    reasons3 = _base(live_eligible=True).validate()
    assert "LIVE_ELIGIBLE_NOT_FALSE" in reasons3


def test_hedge_requires_legs_and_matching_ratios():
    reasons = _base(
        selected_action="MARKET_NEUTRAL_OR_HEDGED",
        hedge_enabled=True,
        hedge_legs=[{"symbol": "ETHUSDT", "side": "short"}],
        hedge_ratios=[],
    ).validate()
    assert "HEDGE_RATIOS_LEN_MISMATCH" in reasons


def test_content_hash_is_deterministic():
    assert _base().content_sha256() == _base().content_sha256()
    assert _base().content_sha256() != _base(decision_id="dec-2").content_sha256()


def test_unknown_selected_action_rejected():
    reasons = _base(selected_action="ALLOW").validate()
    assert any(x.startswith("SELECTED_ACTION_INVALID") for x in reasons)
