from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import math

import pytest

from v2.backend.app.domain.adaptive_policy_action_v2 import (
    ACTION_CLOSE_EXISTING_EXPOSURE,
    ACTION_DIRECTIONAL_TRADE,
    ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
    ACTION_REDUCE_EXISTING_EXPOSURE,
    ACTION_REMAIN_FLAT,
    LIVE_GATE_BLOCKED_HUMAN_ONLY,
    POLICY_MODE_BOOTSTRAP_INFORMATION_ACQUISITION,
    POLICY_MODE_BOUNDED_EXPLORATION,
    UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY,
    ActionProbabilityV2,
    AdaptivePolicyActionDomainError,
    AdaptivePolicyActionV2,
    EntryPolicyV2,
    ExitPolicyV2,
    ExpectedCostBreakdownV2,
    HedgeLegV2,
    HorizonReturnDistributionV2,
    PartialReductionStepV2,
    PositionAdjustmentV2,
    ReturnQuantileV2,
)


def _sha(character: str) -> str:
    return character * 64


def _action_distribution(
    *,
    directional: float = 0.55,
    hedged: float = 0.10,
    reduce: float = 0.05,
    close: float = 0.05,
    flat: float = 0.25,
) -> tuple[ActionProbabilityV2, ...]:
    return (
        ActionProbabilityV2(ACTION_DIRECTIONAL_TRADE, directional),
        ActionProbabilityV2(ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE, hedged),
        ActionProbabilityV2(ACTION_REDUCE_EXISTING_EXPOSURE, reduce),
        ActionProbabilityV2(ACTION_CLOSE_EXISTING_EXPOSURE, close),
        ActionProbabilityV2(ACTION_REMAIN_FLAT, flat),
    )


def _returns(expected: float = -2.5) -> tuple[HorizonReturnDistributionV2, ...]:
    return (
        HorizonReturnDistributionV2(
            horizon_seconds=3600,
            expected_return_bps=expected,
            standard_deviation_bps=8.0,
            quantiles=(
                ReturnQuantileV2(0.10, -12.0),
                ReturnQuantileV2(0.50, expected),
                ReturnQuantileV2(0.90, 8.0),
            ),
        ),
    )


def _entry_policy(*, active: bool = True) -> EntryPolicyV2:
    if not active:
        return EntryPolicyV2(
            False,
            "not_applicable",
            "not_applicable",
            None,
            None,
            0.0,
            "not_applicable",
            0,
            False,
        )
    return EntryPolicyV2(
        True,
        "policy_selected_limit",
        "optimizer_receipt_bound",
        100.0,
        99.5,
        3.0,
        "policy_selected_ioc",
        30,
        False,
    )


def _exit_policy(*, active: bool = True, side: str = "long") -> ExitPolicyV2:
    if not active:
        return ExitPolicyV2(
            False,
            "not_applicable",
            None,
            0.0,
            "not_applicable",
            (),
            "not_applicable",
            None,
            "not_applicable",
            0,
        )
    return ExitPolicyV2(
        True,
        "policy_tail_quantile_stop",
        98.0 if side == "long" else 102.0,
        200.0,
        "policy_distribution_bound",
        (PartialReductionStepV2(10.0, 0.25),),
        "policy_distribution_bound",
        104.0 if side == "long" else 96.0,
        "policy_horizon_bound",
        3_600,
    )


def _hedge_leg() -> HedgeLegV2:
    return HedgeLegV2(
        leg_id="hedge_leg_1",
        symbol="ETHUSDT",
        timeframe="1h",
        side="short",
        target_exposure_usd=-40.0,
        target_notional_usd=40.0,
        leverage=2.0,
        margin_allocation_usd=20.0,
        hedge_ratio=0.4,
        entry_price_policy="optimizer_receipt_bound",
        entry_policy=_entry_policy(),
        protective_stop_policy="policy_tail_quantile_stop",
        stop_price=102.0,
        exit_policy=_exit_policy(side="short"),
    )


def _valid_action(**overrides: object) -> AdaptivePolicyActionV2:
    values: dict[str, object] = {
        "state_id": "state_001",
        "feature_snapshot_id": "feature_snapshot_001",
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint_003",
        "checkpoint_sha256": _sha("a"),
        "feature_abi_sha256": _sha("b"),
        "feature_builder_sha256": _sha("c"),
        "policy_id": "adaptive_policy_001",
        "policy_generation": 1,
        "policy_mode": POLICY_MODE_BOUNDED_EXPLORATION,
        "policy_parameter_fingerprint": _sha("d"),
        "calibration_sha256": _sha("e"),
        "state_sha256": _sha("f"),
        "source_receipt_sha256s": (_sha("1"), _sha("2")),
        "selection_receipt_sha256": _sha("3"),
        "state_event_time_ms": 1_000,
        "state_ingested_at_ms": 1_100,
        "feature_cutoff_ms": 1_150,
        "source_available_at_ms": 1_200,
        "producer_generated_at_ms": 1_400,
        "record_available_at_ms": 1_400,
        "decision_time_ms": 1_600,
        "execution_time_ms": None,
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "close_time_strictly_before_cutoff",
        "latest_unclosed_exclusion_decision_time_ms": 1_550,
        "latest_closed_kline_close_time_ms": 900,
        "primary_symbol": "BTCUSDT",
        "primary_timeframe": "1h",
        "primary_side": "long",
        "target_exposure_usd": 100.0,
        "target_notional_usd": 100.0,
        "leverage": 2.0,
        "margin_mode_simulation": "isolated_paper_simulated",
        "margin_allocation_usd": 50.0,
        "entry_style": "policy_selected_limit",
        "entry_price_policy": "optimizer_receipt_bound",
        "maximum_entry_slippage": 3.0,
        "order_duration_policy": "policy_selected_ioc",
        "entry_policy": _entry_policy(),
        "protective_stop_policy": "policy_tail_quantile_stop",
        "stop_price": 98.0,
        "stop_distance": 200.0,
        "partial_reduction_policy": "policy_distribution_bound",
        "profit_exit_policy": "policy_distribution_bound",
        "time_exit_policy": "policy_horizon_bound",
        "expected_holding_horizon": 3_600,
        "exit_policy": _exit_policy(),
        "hedge_enabled": False,
        "hedge_legs": (),
        "hedge_ratios": (),
        "expected_before_cost_return": 5.5,
        "expected_cost_breakdown": ExpectedCostBreakdownV2(4.0, 1.0, 2.0, 1.0, 0.0, 8.0),
        "expected_after_cost_return": -2.5,
        "expected_return_distribution": _returns(),
        "policy_evaluation_horizon_seconds": 3_600,
        "expected_drawdown_contribution": 4.0,
        "expected_tail_loss": 12.0,
        "expected_fill_probability": 0.40,
        "expected_slippage": 2.0,
        "expected_market_impact": 1.0,
        "expected_adverse_selection": 0.30,
        "expected_information_gain": 0.80,
        "flat_probability": 0.25,
        "selected_action": ACTION_DIRECTIONAL_TRADE,
        "action_distribution": _action_distribution(),
        "policy_uncertainty": 0.70,
        "decision_rationale_codes": ("BOUNDED_EXPLORATION", "HIGH_INFORMATION_GAIN"),
        "learning_continuation_action": "mature_candidate_and_incremental_retrain",
        "affected_position_ids": (),
        "position_adjustments": (),
        "reduce_only": False,
        "operator_catastrophic_envelope_id": "operator_envelope_v1",
        "operator_catastrophic_envelope_sha256": _sha("4"),
        "integrity_evidence_sha256": _sha("5"),
        "execution_domain": "PAPER",
        "policy_authority_scope": "trading_action_only",
        "requires_hard_validator": True,
        "execution_authority": False,
        "hard_validator_decision_id": None,
        "unit_contract": UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY,
        "paper_only": True,
        "live_gate": LIVE_GATE_BLOCKED_HUMAN_ONLY,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "live_eligible": False,
        "live_submission_ready": False,
    }
    values.update(overrides)
    return AdaptivePolicyActionV2.create(**values)


def test_directional_action_accepts_negative_after_cost_edge_for_learning() -> None:
    action = _valid_action()
    assert action.expected_after_cost_return == -2.5
    assert action.selected_action == ACTION_DIRECTIONAL_TRADE
    assert action.execution_authority is False


def test_bootstrap_information_acquisition_policy_mode_is_accepted_and_round_trips() -> None:
    action = _valid_action(
        policy_mode=POLICY_MODE_BOOTSTRAP_INFORMATION_ACQUISITION,
    )
    assert action.policy_mode == "bootstrap_information_acquisition"
    assert AdaptivePolicyActionV2.from_payload(action.to_payload()) == action
    assert AdaptivePolicyActionV2.from_json(action.canonical_json()) == action


def test_unknown_policy_mode_still_fails_closed() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="invalid_policy_mode"):
        _valid_action(policy_mode="unbounded_speculative_acquisition")


def test_short_action_requires_signed_negative_exposure() -> None:
    action = _valid_action(
        primary_side="short",
        target_exposure_usd=-100.0,
        stop_price=102.0,
        exit_policy=_exit_policy(side="short"),
    )
    assert action.target_exposure_usd == -100.0
    with pytest.raises(AdaptivePolicyActionDomainError, match="short_requires_negative"):
        _valid_action(primary_side="short", target_exposure_usd=100.0)


def test_flat_action_is_nonterminal_learning_state() -> None:
    action = _valid_action(
        primary_side="flat",
        target_exposure_usd=0.0,
        target_notional_usd=0.0,
        leverage=0.0,
        margin_mode_simulation="none",
        margin_allocation_usd=0.0,
        stop_price=None,
        stop_distance=0.0,
        expected_holding_horizon=0,
        entry_style="not_applicable",
        entry_price_policy="not_applicable",
        maximum_entry_slippage=0.0,
        order_duration_policy="not_applicable",
        entry_policy=_entry_policy(active=False),
        protective_stop_policy="not_applicable",
        partial_reduction_policy="not_applicable",
        profit_exit_policy="not_applicable",
        time_exit_policy="not_applicable",
        exit_policy=_exit_policy(active=False),
        selected_action=ACTION_REMAIN_FLAT,
    )
    assert action.learning_continuation_action == "mature_candidate_and_incremental_retrain"
    with pytest.raises(AdaptivePolicyActionDomainError, match="nonterminal_declared"):
        _valid_action(learning_continuation_action="terminal_market_classification")


def test_hedged_action_requires_complete_distinct_leg() -> None:
    leg = _hedge_leg()
    action = _valid_action(
        selected_action=ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
        hedge_enabled=True,
        hedge_legs=(leg,),
        hedge_ratios=(0.4,),
    )
    assert action.hedge_legs == (leg,)
    with pytest.raises(AdaptivePolicyActionDomainError, match="hedged_trade_requires_enabled"):
        _valid_action(selected_action=ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_ingested_at_ms", 900),
        ("source_available_at_ms", 1_050),
        ("feature_cutoff_ms", 1_300),
        ("producer_generated_at_ms", 1_150),
        ("record_available_at_ms", 1_300),
        ("decision_time_ms", 1_300),
    ],
)
def test_point_in_time_clock_reordering_fails_closed(field: str, value: int) -> None:
    with pytest.raises(
        AdaptivePolicyActionDomainError,
        match="point_in_time_order_invalid|must_equal_effective_record_availability",
    ):
        _valid_action(**{field: value})


def test_unclosed_candle_exclusion_and_close_time_are_hard_contracts() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="latest_unclosed_kline_excluded"):
        _valid_action(latest_unclosed_kline_excluded=False)
    with pytest.raises(AdaptivePolicyActionDomainError, match="feature_cutoff"):
        _valid_action(latest_closed_kline_close_time_ms=1_151)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paper_only", False),
        ("routes_to_live", True),
        ("places_real_order", True),
        ("exchange_action_taken", True),
        ("live_eligible", True),
        ("live_submission_ready", True),
        ("requires_hard_validator", False),
        ("execution_authority", True),
    ],
)
def test_paper_and_hard_validator_authority_is_fail_closed(field: str, value: bool) -> None:
    with pytest.raises(AdaptivePolicyActionDomainError):
        _valid_action(**{field: value})


def test_live_gate_and_execution_domain_are_exact() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="blocked_human_only"):
        _valid_action(live_gate="enabled_operator_approved")
    with pytest.raises(AdaptivePolicyActionDomainError, match="must_be_paper"):
        _valid_action(execution_domain="LIVE")


def test_action_distribution_requires_complete_normalized_support() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="cover_each_schema_action"):
        _valid_action(action_distribution=_action_distribution()[:-1])
    with pytest.raises(AdaptivePolicyActionDomainError, match="sum_to_one"):
        _valid_action(action_distribution=_action_distribution(flat=0.20))
    with pytest.raises(AdaptivePolicyActionDomainError, match="remain_flat_probability"):
        _valid_action(flat_probability=0.20)


def test_selected_action_may_be_non_argmax_but_not_zero_probability() -> None:
    action = _valid_action(
        selected_action=ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
        hedge_enabled=True,
        hedge_legs=(
            _hedge_leg(),
        ),
        hedge_ratios=(0.4,),
    )
    assert action.selected_action == ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE
    with pytest.raises(AdaptivePolicyActionDomainError, match="probability_must_be_positive"):
        _valid_action(
            selected_action=ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
            action_distribution=_action_distribution(directional=0.65, hedged=0.0),
            hedge_enabled=True,
            hedge_legs=action.hedge_legs,
            hedge_ratios=(0.4,),
        )


def test_expected_return_mean_must_match_selected_after_cost_horizon() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="after_cost_distribution_mean"):
        _valid_action(expected_before_cost_return=10.0, expected_after_cost_return=2.0)


def test_nonfinite_estimates_and_malformed_sha_fail() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="must_be_finite"):
        _valid_action(expected_information_gain=math.nan)
    with pytest.raises(AdaptivePolicyActionDomainError, match="lowercase_sha256"):
        _valid_action(checkpoint_sha256="not-a-sha")


def test_existing_exposure_actions_require_reduce_only_position_lineage() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="reduce_only_lineage"):
        _valid_action(selected_action=ACTION_CLOSE_EXISTING_EXPOSURE)
    action = _valid_action(
        selected_action=ACTION_REDUCE_EXISTING_EXPOSURE,
        affected_position_ids=("paper_position_1",),
        position_adjustments=(
            PositionAdjustmentV2("paper_position_1", 150.0, 100.0, 50.0),
        ),
        reduce_only=True,
        entry_style="not_applicable",
        entry_price_policy="not_applicable",
        maximum_entry_slippage=0.0,
        order_duration_policy="not_applicable",
        entry_policy=_entry_policy(active=False),
    )
    assert action.reduce_only is True


def test_close_requires_zero_target_and_exact_position_adjustment() -> None:
    action = _valid_action(
        selected_action=ACTION_CLOSE_EXISTING_EXPOSURE,
        primary_side="flat",
        target_exposure_usd=0.0,
        target_notional_usd=0.0,
        leverage=0.0,
        margin_mode_simulation="none",
        margin_allocation_usd=0.0,
        entry_style="not_applicable",
        entry_price_policy="not_applicable",
        maximum_entry_slippage=0.0,
        order_duration_policy="not_applicable",
        entry_policy=_entry_policy(active=False),
        protective_stop_policy="not_applicable",
        stop_price=None,
        stop_distance=0.0,
        partial_reduction_policy="not_applicable",
        profit_exit_policy="not_applicable",
        time_exit_policy="not_applicable",
        expected_holding_horizon=0,
        exit_policy=_exit_policy(active=False),
        affected_position_ids=("paper_position_1",),
        position_adjustments=(
            PositionAdjustmentV2("paper_position_1", -100.0, 0.0, 100.0),
        ),
        reduce_only=True,
    )
    assert action.position_adjustments[0].target_exposure_usd == 0.0


def test_cost_breakdown_prevents_double_or_missing_cost_subtraction() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="before_cost_minus_total"):
        _valid_action(expected_before_cost_return=5.0)
    with pytest.raises(AdaptivePolicyActionDomainError, match="component_sum"):
        ExpectedCostBreakdownV2(4.0, 1.0, 2.0, 1.0, 0.0, 7.0)


def test_notional_leverage_margin_and_stop_direction_are_coherent() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="margin_must_equal"):
        _valid_action(margin_allocation_usd=49.0)
    with pytest.raises(AdaptivePolicyActionDomainError, match="short_stop_must_be_above"):
        _valid_action(primary_side="short", target_exposure_usd=-100.0)
    with pytest.raises(AdaptivePolicyActionDomainError, match="entry_to_stop_distance"):
        _valid_action(
            stop_distance=999.0,
            exit_policy=dataclasses.replace(_exit_policy(), stop_distance_bps=999.0),
        )


def test_hedge_stop_distance_must_match_entry_and_stop_prices() -> None:
    leg = _hedge_leg()
    with pytest.raises(AdaptivePolicyActionDomainError, match="entry_to_stop_distance"):
        dataclasses.replace(
            leg,
            exit_policy=dataclasses.replace(leg.exit_policy, stop_distance_bps=999.0),
        )


def test_new_exposure_return_horizon_must_match_holding_horizon() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="expected_holding_horizon"):
        _valid_action(
            policy_evaluation_horizon_seconds=7_200,
            expected_return_distribution=(
                *_returns(),
                HorizonReturnDistributionV2(
                    horizon_seconds=7_200,
                    expected_return_bps=-2.5,
                    standard_deviation_bps=9.0,
                    quantiles=(
                        ReturnQuantileV2(0.10, -14.0),
                        ReturnQuantileV2(0.50, -2.5),
                        ReturnQuantileV2(0.90, 9.0),
                    ),
                ),
            ),
        )


def test_typed_policy_aliases_cannot_disagree() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="top_level_fields_must_match"):
        _valid_action(entry_style="manual_override")
    with pytest.raises(AdaptivePolicyActionDomainError, match="top_level_fields_must_match"):
        _valid_action(stop_distance=199.0)


def test_position_adjustment_rejects_side_flip_and_non_reduction() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="must_not_flip_side"):
        PositionAdjustmentV2("position_1", 100.0, -50.0, 50.0)
    with pytest.raises(AdaptivePolicyActionDomainError, match="strictly_reduce"):
        PositionAdjustmentV2("position_1", 100.0, 100.0, 0.0)


def test_partial_reduction_fractions_cannot_overconsume_position() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="must_not_exceed_one"):
        ExitPolicyV2(
            True,
            "stop",
            98.0,
            200.0,
            "partial",
            (PartialReductionStepV2(5.0, 0.6), PartialReductionStepV2(10.0, 0.5)),
            "profit",
            104.0,
            "time",
            3_600,
        )


def test_hedge_ratio_and_nested_policy_round_trip_are_exact() -> None:
    leg = _hedge_leg()
    action = _valid_action(
        selected_action=ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
        hedge_enabled=True,
        hedge_legs=(leg,),
        hedge_ratios=(0.4,),
    )
    assert AdaptivePolicyActionV2.from_json(action.canonical_json()) == action
    with pytest.raises(AdaptivePolicyActionDomainError, match="leg_to_primary_notional_ratio"):
        _valid_action(
            selected_action=ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
            hedge_enabled=True,
            hedge_legs=(dataclasses.replace(leg, hedge_ratio=0.5),),
            hedge_ratios=(0.5,),
        )


def test_payload_and_hash_are_deterministic_and_complete() -> None:
    first = _valid_action()
    second = _valid_action()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_sha256 == second.content_sha256
    assert len(first.content_sha256) == 64
    payload = first.to_payload()
    for required in (
        "decision_id",
        "action_fingerprint_sha256",
        "state_id",
        "checkpoint_generation",
        "policy_id",
        "primary_symbol",
        "primary_timeframe",
        "primary_side",
        "target_exposure_usd",
        "target_notional_usd",
        "leverage",
        "margin_mode_simulation",
        "margin_allocation_usd",
        "entry_style",
        "entry_price_policy",
        "maximum_entry_slippage",
        "order_duration_policy",
        "protective_stop_policy",
        "stop_price",
        "stop_distance",
        "partial_reduction_policy",
        "profit_exit_policy",
        "time_exit_policy",
        "expected_holding_horizon",
        "hedge_enabled",
        "hedge_legs",
        "hedge_ratios",
        "expected_after_cost_return",
        "expected_return_distribution",
        "expected_drawdown_contribution",
        "expected_tail_loss",
        "expected_fill_probability",
        "expected_slippage",
        "expected_market_impact",
        "expected_adverse_selection",
        "expected_information_gain",
        "flat_probability",
        "selected_action",
        "action_distribution",
        "policy_uncertainty",
    ):
        assert required in payload


def test_strict_payload_and_json_round_trip() -> None:
    action = _valid_action()
    assert AdaptivePolicyActionV2.from_payload(action.to_payload()) == action
    assert AdaptivePolicyActionV2.from_json(action.canonical_json()) == action


def test_semantic_identity_is_deterministic_and_changes_with_action() -> None:
    first = _valid_action()
    second = _valid_action()
    changed = _valid_action(expected_information_gain=0.81)

    assert first.action_fingerprint_sha256 == second.action_fingerprint_sha256
    assert first.decision_id == second.decision_id
    assert first.action_fingerprint_sha256 != changed.action_fingerprint_sha256
    assert first.decision_id != changed.decision_id


def test_transport_clock_change_preserves_semantic_identity() -> None:
    first = _valid_action()
    delayed_transport = _valid_action(
        producer_generated_at_ms=1_450,
        record_available_at_ms=1_450,
    )

    assert first.action_fingerprint_sha256 == delayed_transport.action_fingerprint_sha256
    assert first.decision_id == delayed_transport.decision_id
    assert first.content_sha256 != delayed_transport.content_sha256


def test_direct_semantic_mutation_cannot_reuse_decision_identity() -> None:
    action = _valid_action()
    with pytest.raises(
        AdaptivePolicyActionDomainError,
        match="must_match_deterministic_identity",
    ):
        dataclasses.replace(
            action,
            learning_continuation_action="evaluate_alternative_strategy_family",
        )


def test_payload_rejects_tampered_identity_and_action_fingerprint() -> None:
    payload = _valid_action().to_payload()
    wrong_identity = dict(payload)
    wrong_identity["decision_id"] = f"apa2_{'0' * 64}"
    with pytest.raises(
        AdaptivePolicyActionDomainError,
        match="must_match_deterministic_identity",
    ):
        AdaptivePolicyActionV2.from_payload(wrong_identity)

    wrong_fingerprint = dict(payload)
    wrong_fingerprint["action_fingerprint_sha256"] = "0" * 64
    with pytest.raises(
        AdaptivePolicyActionDomainError,
        match="must_match_semantic_payload",
    ):
        AdaptivePolicyActionV2.from_payload(wrong_fingerprint)


def test_golden_semantic_fingerprint_and_decision_identity() -> None:
    action = _valid_action()
    assert (
        action.action_fingerprint_sha256
        == "113bb73a1b84c2ef364f631d6ec3c3380f00c734f8cc8c8bef98706087ff63bb"
    )
    assert (
        action.decision_id
        == "apa2_af6fc65334b22bf72adcfd98d70b428914b49360bf6b264cf84334a709b5c86c"
    )
    assert (
        action.content_sha256
        == "79a64a1c220d259a58f6abb63a9a360bb10c4518b8edfbc7c2d9340d5577415b"
    )


def test_contract_module_has_no_io_or_external_runtime_dependency() -> None:
    record_module = importlib.import_module(
        "v2.backend.app.domain.adaptive_policy_action_v2.record"
    )
    syntax_tree = ast.parse(inspect.getsource(record_module))
    imported_roots: set[str] = set()
    forbidden_calls = {
        "connect",
        "getenv",
        "open",
        "publish",
        "request",
        "send",
        "set",
        "system",
    }
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_roots.add(node.module.split(".", maxsplit=1)[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls

    assert imported_roots == {
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "re",
        "typing",
    }


def test_strict_payload_rejects_missing_extra_and_wrong_nested_keys() -> None:
    payload = _valid_action().to_payload()
    missing = dict(payload)
    missing.pop("policy_id")
    with pytest.raises(AdaptivePolicyActionDomainError, match="exact_keys_required"):
        AdaptivePolicyActionV2.from_payload(missing)

    extra = dict(payload)
    extra["manual_confidence_threshold"] = 0.5
    with pytest.raises(AdaptivePolicyActionDomainError, match="exact_keys_required"):
        AdaptivePolicyActionV2.from_payload(extra)

    nested = dict(payload)
    nested["expected_return_distribution"] = [
        {**payload["expected_return_distribution"][0], "unknown": True}
    ]
    with pytest.raises(AdaptivePolicyActionDomainError, match="exact_keys_required"):
        AdaptivePolicyActionV2.from_payload(nested)


def test_json_parser_rejects_duplicate_keys() -> None:
    with pytest.raises(AdaptivePolicyActionDomainError, match="duplicate_json_key"):
        AdaptivePolicyActionV2.from_json('{"decision_id":"a","decision_id":"b"}')


def test_record_and_nested_records_are_frozen() -> None:
    action = _valid_action()
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.primary_symbol = "ETHUSDT"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        action.action_distribution[0].probability = 0.0  # type: ignore[misc]
