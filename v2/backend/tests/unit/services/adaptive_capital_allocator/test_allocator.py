from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import replace

import pytest

from v2.backend.app.services.adaptive_capital_allocator import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    AllocationInput,
    RiskEnvelope,
    allocate_live_candidate,
    allocate_paper_candidate,
)
from v2.backend.app.services.adaptive_capital_allocator.allocator import (
    PAPER_ALLOCATOR_ARITHMETIC_FORMULA,
    PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY,
    PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION,
    PAPER_ALLOCATOR_ARITHMETIC_VERSION,
    PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY,
    PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY,
    PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY,
    PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY,
    PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY,
    PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY,
    _maintenance_margin_contract,
    _select_margin_configuration,
    build_paper_liquidation_atr_evidence,
    paper_isolated_liquidation_geometry,
)
from v2.backend.app.services.adaptive_capital_allocator.contracts import (
    MAINTENANCE_MARGIN_INPUT_UNSET,
)
from v2.backend.tests.unit.services.adaptive_capital_allocator.growth_receipt_test_utils import (
    allocate_authorized_growth,
    authorize_growth,
)


def _row(*, with_liquidation_atr_evidence: bool = True, **overrides) -> AllocationInput:
    values = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "long",
        "price": 100.0,
        "equity": 10000.0,
        "available_margin": 5000.0,
        "wallet_balance": 10000.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 80.0,
        "market_state_integrity_score": 95.0,
        "volatility_bps": 50.0,
        "liquidity_score": 1.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "maintenance_margin_rate": 0.005,
        "drawdown_bps": 0.0,
        "symbol_exposure_usdt": 0.0,
        "total_exposure_usdt": 0.0,
        "correlation_exposure_pct": 0.0,
        "regime_score": 1.0,
        "lineage_ids": {"prediction_id": "pred"},
    }
    values.update(overrides)
    if with_liquidation_atr_evidence:
        entry_atr_bps = values.get("entry_atr_bps", values["volatility_bps"])
        values["entry_atr_bps"] = entry_atr_bps
        receipt, reasons = build_paper_liquidation_atr_evidence(
            feature_snapshot={
                "feature_snapshot_id": "allocator-test-snapshot",
                "symbol": values["symbol"],
                "timeframe": values["timeframe"],
                "feature_freshness_state": "CURRENT",
                "candle_closed_confirmed": True,
                "latest_unclosed_kline_excluded": True,
                "candle_close_time": "2026-07-18T11:59:59Z",
                "feature_cutoff": "2026-07-18T12:00:00Z",
                "available_at": "2026-07-18T12:00:01Z",
                "generated_at": "2026-07-18T12:00:02Z",
                "features": {"atr_bps": entry_atr_bps},
            },
            symbol=values["symbol"],
            timeframe=values["timeframe"],
            entry_price=values["price"],
            allocation_decision_time="2026-07-18T12:00:03Z",
        )
        assert not reasons
        assert receipt is not None
        lineage_ids = dict(values.get("lineage_ids") or {})
        lineage_ids[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY] = receipt
        lineage_ids[PAPER_LIQUIDATION_ATR_EVIDENCE_HASH_LINEAGE_KEY] = receipt["evidence_sha256"]
        values["lineage_ids"] = lineage_ids
    return AllocationInput(**values)


def _canonical_test_receipt_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reseal_growth_receipt(receipt: dict[str, object]) -> None:
    """Coherently reseal hostile edits so tests exercise semantic replay."""

    calculation = receipt["calculation_input_material"]
    assert isinstance(calculation, dict)
    authorization = calculation["growth_authorization_receipt"]
    assert isinstance(authorization, dict)
    components = authorization["component_receipts"]
    component_hashes = authorization["component_receipt_hashes"]
    assert isinstance(components, dict)
    assert isinstance(component_hashes, dict)
    for name, component_value in components.items():
        assert isinstance(component_value, dict)
        source_material = component_value.get("source_material")
        if isinstance(source_material, dict):
            component_value["source_material_hash"] = _canonical_test_receipt_hash(source_material)
        component_material = dict(component_value)
        component_material.pop("evidence_hash", None)
        component_value["evidence_hash"] = _canonical_test_receipt_hash(component_material)
        component_hashes[name] = component_value["evidence_hash"]
    authorization_material = dict(authorization)
    authorization_material.pop("evidence_hash", None)
    authorization["evidence_hash"] = _canonical_test_receipt_hash(authorization_material)
    calculation["growth_authorization_receipt_hash"] = authorization["evidence_hash"]
    receipt["calculation_input_hash"] = _canonical_test_receipt_hash(calculation)
    receipt_material = dict(receipt)
    receipt_material.pop("evidence_hash", None)
    receipt["evidence_hash"] = _canonical_test_receipt_hash(receipt_material)


def _replace_growth_receipt(
    row: AllocationInput,
    receipt: dict[str, object],
) -> AllocationInput:
    lineage = dict(row.lineage_ids)
    lineage[PAPER_GROWTH_ENVELOPE_AUTHORIZATION_LINEAGE_KEY] = receipt
    lineage[PAPER_GROWTH_ENVELOPE_AUTHORIZATION_HASH_LINEAGE_KEY] = receipt["evidence_hash"]
    return replace(row, lineage_ids=lineage)


def test_high_confidence_and_edge_sizes_larger_than_weak_edge() -> None:
    strong = allocate_paper_candidate(
        _row(confidence_calibrated=0.85, expected_move_after_cost_bps=90.0)
    )
    weak = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.56,
            expected_move_after_cost_bps=10.0,
            spread_bps=1.0,
            slippage_bps=1.0,
            stop_distance_bps=300.0,
        )
    )

    assert strong.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert weak.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert strong.target_notional_usdt > weak.target_notional_usdt


def test_paper_confidence_sizes_continuously_from_zero_while_live_gate_is_unchanged() -> None:
    below_former_admission_cliff = allocate_paper_candidate(_row(confidence_calibrated=0.29))
    above_former_admission_cliff = allocate_paper_candidate(_row(confidence_calibrated=0.31))
    below_former_sizing_cliff = allocate_paper_candidate(_row(confidence_calibrated=0.49))
    above_former_sizing_cliff = allocate_paper_candidate(_row(confidence_calibrated=0.51))
    zero = allocate_paper_candidate(_row(confidence_calibrated=0.0))

    assert below_former_admission_cliff.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert above_former_admission_cliff.risk_budget_usd > (
        below_former_admission_cliff.risk_budget_usd
    )
    assert below_former_sizing_cliff.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert above_former_sizing_cliff.risk_budget_usd > below_former_sizing_cliff.risk_budget_usd
    # Final paper directive 2026-07-31: zero confidence floors the size, it
    # never zeroes it (confidence is TRADING_POLICY; it scales, not vetoes).
    assert zero.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert zero.target_notional_usdt > 0.0
    assert zero.target_notional_usdt <= below_former_admission_cliff.target_notional_usdt

    # Live mode keeps the stricter 0.50 confidence floor.
    live = allocate_live_candidate(_row(confidence_calibrated=0.49))
    assert live.decision == "BLOCK_LOW_CONFIDENCE"
    assert live.target_notional_usdt == 0.0


def test_paper_market_integrity_sizes_continuously_across_former_floor() -> None:
    below = allocate_paper_candidate(_row(market_state_integrity_score=29.9))
    at = allocate_paper_candidate(_row(market_state_integrity_score=30.0))
    above = allocate_paper_candidate(_row(market_state_integrity_score=30.1))
    zero = allocate_paper_candidate(_row(market_state_integrity_score=0.0))

    assert below.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert below.risk_budget_usd < at.risk_budget_usd < above.risk_budget_usd
    assert zero.target_notional_usdt == 0.0

    # Live retains the exact historical 70-point admission boundary.
    live_below = allocate_live_candidate(_row(market_state_integrity_score=69.999))
    live_at = allocate_live_candidate(_row(market_state_integrity_score=70.0))
    assert live_below.decision == "BLOCK_BAD_MARKET_STATE"
    assert live_at.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}


def test_high_volatility_reduces_size() -> None:
    calm = allocate_paper_candidate(_row(volatility_bps=35.0))
    volatile = allocate_paper_candidate(_row(volatility_bps=300.0))

    assert calm.target_notional_usdt > volatile.target_notional_usdt


def test_paper_wide_spread_continuously_reduces_size_while_live_gate_is_unchanged() -> None:
    lower_cost = allocate_paper_candidate(
        _row(expected_move_after_cost_bps=8.0, spread_bps=11.0, slippage_bps=4.0)
    )
    above_former_two_x_cliff = allocate_paper_candidate(
        _row(expected_move_after_cost_bps=8.0, spread_bps=12.0, slippage_bps=5.0)
    )

    assert above_former_two_x_cliff.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert above_former_two_x_cliff.target_notional_usdt > 0.0
    assert above_former_two_x_cliff.target_notional_usdt < lower_cost.target_notional_usdt

    # Live mode keeps the strict 1x threshold: cost >= edge blocks.
    live = allocate_live_candidate(
        _row(expected_move_after_cost_bps=8.0, spread_bps=7.0, slippage_bps=2.0)
    )
    assert live.decision == "BLOCK_SPREAD_SLIPPAGE"


def test_paper_short_uses_negative_signed_move_as_positive_economic_edge() -> None:
    result = allocate_paper_candidate(
        _row(
            action="short",
            confidence_calibrated=0.8,
            expected_move_after_cost_bps=-80.0,
            spread_bps=2.0,
            slippage_bps=2.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.expected_move_after_cost_bps == -80.0
    assert result.expected_net_pnl_usd > 0.0
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == -80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 80.0
    assert result.model_inputs["allocator_edge_sign_convention"] == (
        "paper_short_negative_signed_move_is_positive_economic_edge"
    )
    recommendation = result.model_inputs["phase8_leverage_recommendation"]
    assert result.model_inputs["leverage_signed_expected_market_move_after_cost_bps"] == -80.0
    assert result.model_inputs["leverage_sizing_economic_edge_after_cost_bps"] == 80.0
    assert result.model_inputs["leverage_recommender_edge_semantics"] == (
        "SIGNED_MARKET_MOVE_LONG_POSITIVE_SHORT_NEGATIVE"
    )
    assert recommendation["direction_aligned_after_cost_edge_bps"] == 80.0
    assert recommendation["direction_aligned_edge_source"] == ("SIGNED_EDGE_ALIGNED_TO_SHORT")
    assert result.model_inputs["raw_leverage_target"] > 1.0


def test_paper_long_and_short_symmetric_edge_have_equal_raw_leverage() -> None:
    common = {
        "confidence_calibrated": 0.8,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
    }
    long = allocate_paper_candidate(
        _row(
            action="long",
            expected_move_after_cost_bps=80.0,
            **common,
        )
    )
    short = allocate_paper_candidate(
        _row(
            action="short",
            expected_move_after_cost_bps=-80.0,
            **common,
        )
    )

    assert long.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert short.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert long.model_inputs["raw_leverage_target"] == short.model_inputs["raw_leverage_target"]
    assert long.model_inputs["leverage_target"] == short.model_inputs["leverage_target"]


def test_paper_short_with_positive_signed_move_floors_size_at_1x() -> None:
    # Final paper directive 2026-07-31: a direction-misaligned expected move
    # is zero economic edge — TRADING_POLICY.  It floors the paper size at 1x
    # instead of rejecting the hard-valid candidate.
    result = allocate_paper_candidate(
        _row(
            action="short",
            expected_move_after_cost_bps=80.0,
            spread_bps=2.0,
            slippage_bps=2.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.target_notional_usdt > 0.0
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == 80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 0.0


def test_paper_long_with_negative_signed_move_floors_size_at_1x() -> None:
    result = allocate_paper_candidate(
        _row(
            action="long",
            expected_move_after_cost_bps=-80.0,
            spread_bps=2.0,
            slippage_bps=2.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.target_notional_usdt > 0.0
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == -80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 0.0


def test_live_allocator_keeps_existing_positive_edge_semantics_for_shorts() -> None:
    result = allocate_live_candidate(_row(action="short", expected_move_after_cost_bps=-80.0))

    assert result.decision == "BLOCK_NO_EDGE"
    assert result.model_inputs["signed_expected_move_after_cost_bps"] == -80.0
    assert result.model_inputs["allocator_economic_edge_after_cost_bps"] == 0.0
    assert result.model_inputs["allocator_edge_sign_convention"] == (
        "live_existing_positive_edge_semantics"
    )


def test_paper_liquidity_sizes_continuously_above_zero_and_zero_blocks() -> None:
    below_former_cliff = allocate_paper_candidate(_row(liquidity_score=0.009))
    above_former_cliff = allocate_paper_candidate(_row(liquidity_score=0.011))
    zero = allocate_paper_candidate(_row(liquidity_score=0.0))

    assert below_former_cliff.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert below_former_cliff.target_notional_usdt > 0.0
    assert above_former_cliff.target_notional_usdt > below_former_cliff.target_notional_usdt
    assert zero.decision == "BLOCK_INSUFFICIENT_LIQUIDITY"
    assert zero.target_notional_usdt == 0.0


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("confidence_calibrated", None, "NONFINITE_CONFIDENCE_CALIBRATED"),
        ("market_state_integrity_score", None, "NONFINITE_MARKET_STATE_INTEGRITY_SCORE"),
        ("liquidity_score", None, "NONFINITE_LIQUIDITY_SCORE"),
        ("liquidity_score", float("nan"), "NONFINITE_LIQUIDITY_SCORE"),
    ],
)
def test_missing_or_nonfinite_paper_policy_evidence_still_fails_closed(
    field: str,
    value: float | None,
    reason: str,
) -> None:
    result = allocate_paper_candidate(_row(**{field: value}))

    assert result.decision == "BLOCK_BAD_MARKET_STATE"
    assert result.target_notional_usdt == 0.0
    assert reason in result.model_inputs["paper_allocator_input_rejection_reasons"]


def test_paper_after_cost_edge_ranks_and_sizes_but_never_rejects() -> None:
    # Final paper directive 2026-07-31: nonpositive after-cost edge is
    # TRADING_POLICY — it floors the size, it may not reject.  Live keeps the
    # historical strict gate (see test_live_policy_cliff_decisions_are_unchanged).
    negative = allocate_paper_candidate(_row(expected_move_after_cost_bps=-0.1))
    zero = allocate_paper_candidate(_row(expected_move_after_cost_bps=0.0))
    positive = allocate_paper_candidate(_row(expected_move_after_cost_bps=0.1))

    assert negative.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert negative.target_notional_usdt > 0.0
    assert zero.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert zero.target_notional_usdt > 0.0
    assert positive.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert positive.target_notional_usdt > 0.0


@pytest.mark.parametrize(
    ("overrides", "expected_decision"),
    [
        ({"market_state_integrity_score": 69.999}, "BLOCK_BAD_MARKET_STATE"),
        ({"confidence_calibrated": 0.499999}, "BLOCK_LOW_CONFIDENCE"),
        ({"expected_move_after_cost_bps": 0.0}, "BLOCK_NO_EDGE"),
        ({"liquidity_score": 0.05}, "BLOCK_INSUFFICIENT_LIQUIDITY"),
        (
            {
                "expected_move_after_cost_bps": 8.0,
                "spread_bps": 7.0,
                "slippage_bps": 1.0,
            },
            "BLOCK_SPREAD_SLIPPAGE",
        ),
    ],
)
def test_live_policy_cliff_decisions_are_unchanged(
    overrides: dict[str, float],
    expected_decision: str,
) -> None:
    result = allocate_live_candidate(_row(**overrides))

    assert result.decision == expected_decision
    assert result.target_notional_usdt == 0.0


def test_drawdown_guard_blocks() -> None:
    result = allocate_paper_candidate(_row(drawdown_bps=600.0))

    assert result.decision == "BLOCK_DRAWDOWN_GUARD"


def test_existing_exposure_reduces_or_blocks_size() -> None:
    no_exposure = allocate_paper_candidate(_row())
    heavy_exposure = allocate_paper_candidate(_row(total_exposure_usdt=5500.0))

    assert heavy_exposure.target_notional_usdt < no_exposure.target_notional_usdt


def test_exchange_min_notional_is_respected() -> None:
    result = allocate_paper_candidate(
        _row(min_notional=50.0, confidence_calibrated=0.56, expected_move_after_cost_bps=10.0)
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.target_notional_usdt >= 50.0


def test_insufficient_margin_blocks_live_submit() -> None:
    result = allocate_live_candidate(_row(available_margin=0.0))

    assert result.decision == "BLOCK_INSUFFICIENT_MARGIN"


def test_no_fixed_200_usdt_runtime_allocation() -> None:
    result = allocate_paper_candidate(_row())

    assert result.target_notional_usdt != 200.0
    assert (
        result.final_size_reason
        == "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget"
    )


def test_low_risk_candidate_does_not_reserve_hedge_budget() -> None:
    result = allocate_paper_candidate(_row())

    assert result.hedge_budget_usd == 0.0
    assert result.model_inputs["selected_hedge_budget_pct_of_risk"] == 0.0
    assert (
        result.model_inputs["hedge_budget_selection_reason"]
        == "hedge_budget_not_required_for_current_risk"
    )


def test_allocator_selects_hedge_budget_from_correlation_and_drawdown_risk() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.86,
            expected_move_after_cost_bps=95.0,
            correlation_exposure_pct=0.16,
            drawdown_bps=250.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.hedge_budget_usd > 0.0
    assert result.hedge_budget_usd <= round(result.risk_budget_usd * 0.35, 8)
    assert result.model_inputs["selected_hedge_budget_pct_of_risk"] > 0.0
    assert result.model_inputs["hedge_correlation_pressure"] > 0.0
    assert result.model_inputs["hedge_drawdown_pressure"] > 0.0
    assert (
        result.model_inputs["hedge_budget_selection_reason"]
        == "correlation_drawdown_volatility_cost_pressure"
    )


def test_operator_hedge_budget_floor_is_preserved() -> None:
    result = allocate_paper_candidate(_row(hedge_budget_pct_of_risk=0.2))

    assert result.hedge_budget_usd == round(result.risk_budget_usd * 0.2, 8)
    assert result.model_inputs["selected_hedge_budget_pct_of_risk"] == 0.2
    assert result.model_inputs["hedge_budget_selection_reason"] == "operator_hedge_budget_floor"


def test_paper_input_receipt_extension_does_not_change_live_payload_schema() -> None:
    row = _row()
    paper = allocate_paper_candidate(row)
    live = allocate_live_candidate(row)

    receipt_fields = {
        "allocation_input_schema_version",
        "allocation_input_hash",
        "allocation_input_hash_algorithm",
        "allocation_input_material",
    }
    assert receipt_fields <= paper.to_payload().keys()
    assert receipt_fields.isdisjoint(live.to_payload().keys())
    assert live.to_payload().keys() == (paper.to_payload().keys() - receipt_fields)
    assert PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY in paper.model_inputs
    assert PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY not in live.model_inputs


def test_sizable_paper_allocation_seals_exact_prepublication_arithmetic() -> None:
    result = allocate_authorized_growth(
        _row(
            price=100.123456789,
            step_size=3.0,
            min_notional=250.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision == "REDUCE_SIZE"
    assert result.target_quantity == 6.0
    assert result.gross_notional_usd == 600.74074073
    assert result.effective_leverage == 2.0
    assert result.allocated_margin_usd == 300.37037037
    receipt = result.model_inputs[PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert set(receipt) == {
        "schema_version",
        "arithmetic_version",
        "formula",
        "raw_post_step_quantity_binary64_hex",
        "input_price_binary64_hex",
        "raw_post_step_notional_binary64_hex",
        "selected_leverage_binary64_hex",
        "receipt_sha256",
    }
    assert receipt["schema_version"] == PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION
    assert receipt["arithmetic_version"] == PAPER_ALLOCATOR_ARITHMETIC_VERSION
    assert receipt["formula"] == PAPER_ALLOCATOR_ARITHMETIC_FORMULA
    material = dict(receipt)
    receipt_hash = material.pop("receipt_sha256")
    assert receipt_hash == _canonical_test_receipt_hash(material)
    raw_quantity = float.fromhex(receipt["raw_post_step_quantity_binary64_hex"])
    input_price = float.fromhex(receipt["input_price_binary64_hex"])
    raw_notional = float.fromhex(receipt["raw_post_step_notional_binary64_hex"])
    raw_leverage = float.fromhex(receipt["selected_leverage_binary64_hex"])
    assert raw_notional == abs(raw_quantity * input_price)
    assert round(raw_quantity, 12) == result.target_quantity
    assert round(raw_notional, 8) == result.gross_notional_usd
    assert round(raw_leverage, 8) == result.effective_leverage
    assert round(raw_notional / raw_leverage, 8) == result.allocated_margin_usd


def test_sizable_one_x_paper_allocation_receipt_binds_exact_selected_leverage() -> None:
    result = allocate_paper_candidate(_row())

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.effective_leverage == 1.0
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["selected_leverage"] == 1.0
    receipt = result.model_inputs[PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY]
    assert receipt["selected_leverage_binary64_hex"] == (1.0).hex()
    assert float.fromhex(receipt["selected_leverage_binary64_hex"]) == (result.effective_leverage)


def test_blocked_paper_and_live_allocations_do_not_emit_arithmetic_receipt() -> None:
    blocked_paper = allocate_paper_candidate(
        _row(risk_veto=True, risk_veto_reason="operator_drawdown_budget_locked")
    )
    live = allocate_live_candidate(_row())

    assert blocked_paper.decision == "BLOCK_EXPOSURE_BUDGET"
    assert PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY not in (blocked_paper.model_inputs)
    assert PAPER_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY not in live.model_inputs


def test_all_allowed_allocations_emit_explicit_margin_leverage_and_cost_fields() -> None:
    result = allocate_paper_candidate(
        _row(confidence_calibrated=0.86, expected_move_after_cost_bps=95.0)
    )
    payload = result.to_payload()

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    for field in (
        "risk_budget_usd",
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "stop_distance_bps",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
        "target_notional_usd",
        "max_loss_if_stop_hit",
        "risk_reward",
        "risk_of_ruin_contribution",
        "portfolio_exposure_after_trade",
        "correlation_exposure_after_trade",
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "expected_gross_pnl_usd",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "hedge_budget_usd",
        "hedge_action",
        "hedge_reason",
        "cross_margin_stress_used_usd",
        "cross_margin_available_buffer_usd",
        "portfolio_liquidation_buffer_usd",
        "margin_call_risk",
        "capital_allocation_reason",
    ):
        assert field in payload
        assert payload[field] is not None
    assert payload["gross_notional_usd"] == payload["target_notional_usdt"]
    assert payload["target_notional_usd"] == payload["target_notional_usdt"]
    assert payload["adaptive_capital_policy_version"] == ADAPTIVE_CAPITAL_POLICY_VERSION
    assert payload["allocated_margin_usd"] <= payload["gross_notional_usd"]
    assert payload["recommended_margin_mode"] == "isolated_paper_simulated"
    assert payload["capital_allocation_reason"] == result.final_size_reason
    assert payload["max_loss_if_stop_hit"] > 0.0
    assert payload["max_loss_usd"] == payload["max_loss_if_stop_hit"]
    assert payload["stop_loss_usd"] is not None
    assert payload["take_profit_usd"] is not None
    assert payload["liquidation_distance_usd"] is not None
    assert payload["risk_reward"] > 0.0
    assert payload["expected_gross_pnl_usd"] >= payload["expected_net_pnl_usd"]
    assert 0.0 <= payload["risk_of_ruin_contribution"] <= 1.0
    assert payload["portfolio_exposure_after_trade"] >= payload["gross_notional_usd"]
    assert 0.0 <= payload["correlation_exposure_after_trade"] <= 1.0
    assert payload["hedge_action"] in {
        "NO_HEDGE",
        "REDUCE_POSITION",
        "CLOSE_POSITION",
        "PROTECTIVE_HEDGE",
        "PAIR_HEDGE",
        "BETA_HEDGE",
        "MARKET_REGIME_HEDGE",
        "CROSS_MARGIN_RISK_OFF",
    }
    assert payload["cross_margin_safe"] in {True, False}
    assert payload["model_inputs"]["hedge_engine"]["places_real_order"] is False
    assert (
        payload["model_inputs"]["cross_margin_stress"]["exchange_margin_mode_mutation_allowed"]
        is False
    )


def test_allowed_allocation_payload_exposes_selected_capital_attribution_contract() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.90,
            expected_move_after_cost_bps=180.0,
            volatility_bps=20.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.08,
            drawdown_bps=120.0,
        )
    )
    payload = result.to_payload()
    model_inputs = payload["model_inputs"]

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert payload["expected_move_after_cost_bps"] == 180.0
    assert payload["gross_notional_usd"] == payload["target_notional_usdt"]
    assert payload["allocated_margin_usd"] == result.allocated_margin_usd
    assert payload["recommended_leverage"] == result.recommended_leverage
    assert payload["recommended_margin_mode"] == result.recommended_margin_mode
    assert payload["hedge_budget_usd"] == result.hedge_budget_usd
    assert model_inputs["selected_allocated_margin_usd"] == payload["allocated_margin_usd"]
    assert model_inputs["selected_leverage"] == payload["recommended_leverage"]
    assert model_inputs["selected_margin_mode"] == payload["recommended_margin_mode"]
    assert model_inputs["selected_hedge_budget_pct_of_risk"] > 0.0
    assert (
        model_inputs["hedge_budget_selection_reason"]
        == "correlation_drawdown_volatility_cost_pressure"
    )
    assert model_inputs["leverage_selection_reason"]
    assert model_inputs["margin_mode_selection_reason"]
    assert model_inputs["leverage_edge_cost_ratio"] > 0.0
    assert model_inputs["margin_mode_edge_cost_ratio"] > 0.0
    assert model_inputs["hedge_correlation_pressure"] > 0.0
    assert model_inputs["hedge_drawdown_pressure"] > 0.0
    assert model_inputs["leverage_live_mutation_allowed"] is False
    assert model_inputs["margin_mode_live_mutation_allowed"] is False


def test_paper_margin_mode_keeps_isolated_until_account_wide_cross_model_exists() -> None:
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.0,
            drawdown_bps=0.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 2.0
    assert result.recommended_margin_mode == "isolated_paper_simulated"
    # A candidate-only stress calculation cannot certify account-wide cross
    # margin safety.  The positive net-benefit remains counterfactual while
    # the executable paper recommendation stays isolated.
    assert result.cross_margin_safe is False
    assert result.model_inputs["cross_margin_account_wide_positions_included"] is False
    assert result.model_inputs["selected_margin_mode"] == "isolated_paper_simulated"
    assert result.model_inputs["margin_mode_live_mutation_allowed"] is False
    assert result.model_inputs["margin_mode_cross_net_benefit"] > 0.0
    assert result.model_inputs["portfolio_cross_margin_liquidation_model_available"] is False
    assert result.model_inputs["margin_mode_counterfactual_candidate"] == ("cross_paper_simulated")
    assert result.model_inputs["margin_mode_selection_reason"] == (
        "isolated_until_account_wide_cross_margin_liquidation_model_is_proven"
    )


def test_paper_margin_mode_stays_isolated_under_correlation_pressure() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.12,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_margin_mode == "isolated_paper_simulated"
    assert result.cross_margin_safe is False
    assert result.model_inputs["selected_margin_mode"] == "isolated_paper_simulated"
    assert (
        result.model_inputs["margin_mode_selection_reason"]
        == "isolated_limits_tail_contagion_for_current_risk"
    )


def test_allocator_emits_protective_hedge_when_net_delta_benefit_is_positive() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.13,
            spread_bps=0.5,
            slippage_bps=0.5,
            fee_bps=0.5,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.hedge_action in {"PROTECTIVE_HEDGE", "REDUCE_POSITION"}
    if result.hedge_action == "PROTECTIVE_HEDGE":
        assert result.hedge_required is True
        assert result.hedge_notional_usd > 0.0
        assert result.hedge_net_benefit_usd > 0.0
        assert result.hedge_exit_plan["status"] == "HEDGE_EXIT_PLAN_ACTIVE"
    assert result.model_inputs["hedge_engine"]["paper_only"] is True


def test_paper_margin_scarcity_cannot_force_leverage_above_evidence_target() -> None:
    tight_margin = allocate_authorized_growth(
        _row(
            available_margin=330.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=80.0,
        )
    )
    ample_margin = allocate_authorized_growth(
        _row(
            available_margin=5000.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=80.0,
        )
    )

    assert tight_margin.decision == "BLOCK_LIQUIDATION_RISK"
    assert ample_margin.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert tight_margin.recommended_leverage == 1.0
    assert tight_margin.allocated_margin_usd == 0.0
    assert tight_margin.model_inputs["paper_margin_may_exceed_evidence_leverage_target"] is False
    assert ample_margin.recommended_leverage == 2.0


def test_paper_allocator_fails_closed_when_account_wide_free_margin_is_zero() -> None:
    result = allocate_paper_candidate(
        _row(
            available_margin=0.0,
            confidence_calibrated=0.90,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision == "BLOCK_INSUFFICIENT_MARGIN"
    assert result.allocated_margin_usd == 0.0
    assert result.risk_veto_reason_if_blocked == "paper_free_margin_missing_or_zero"


def test_paper_allocator_fails_closed_without_maintenance_margin_evidence() -> None:
    result = allocate_paper_candidate(
        _row(
            maintenance_margin_rate=None,
            confidence_calibrated=0.99,
            expected_move_after_cost_bps=500.0,
        )
    )

    assert result.decision == "BLOCK_LIQUIDATION_RISK"
    assert result.target_notional_usdt == 0.0
    assert result.liquidation_price_estimate is None
    assert result.liquidation_buffer_bps is None
    assert result.maintenance_margin_estimate_usd is None
    assert result.model_inputs["maintenance_margin_evidence_status"] == (
        "MISSING_OR_INVALID_FAIL_CLOSED"
    )
    assert result.model_inputs["cross_margin_stress"]["liquidation_simulation_status"] == (
        "NOT_RUN_MAINTENANCE_MARGIN_MISSING"
    )


def test_paper_allocator_rejects_out_of_contract_maintenance_margin_rate() -> None:
    for maintenance_margin_rate in (0.0, 1.0, -0.001, 1.5):
        result = allocate_paper_candidate(_row(maintenance_margin_rate=maintenance_margin_rate))

        assert result.decision == "BLOCK_LIQUIDATION_RISK"
        assert result.liquidation_price_estimate is None
        assert result.liquidation_buffer_bps is None
        assert result.maintenance_margin_estimate_usd is None


def test_live_explicit_none_maintenance_preserves_legacy_exception_surface() -> None:
    with pytest.raises(
        TypeError,
        match="'>' not supported between instances of 'NoneType' and 'float'",
    ):
        allocate_live_candidate(_row(maintenance_margin_rate=None))


class _LiveMaintenanceArbitraryValue:
    pass


@pytest.mark.parametrize(
    "maintenance_margin_rate",
    [
        None,
        -0.01,
        float("nan"),
        float("inf"),
        float("-inf"),
        "0.005",
        _LiveMaintenanceArbitraryValue(),
        1,
        True,
        False,
    ],
    ids=(
        "explicit-none",
        "finite-negative",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "numeric-string",
        "arbitrary-object",
        "integer",
        "boolean-true",
        "boolean-false",
    ),
)
def test_live_maintenance_contract_returns_every_explicit_value_unchanged(
    maintenance_margin_rate: object,
) -> None:
    effective, diagnostics = _maintenance_margin_contract(
        _row(
            with_liquidation_atr_evidence=False,
            maintenance_margin_rate=maintenance_margin_rate,
        ),
        mode="live",
    )

    assert effective is maintenance_margin_rate
    assert diagnostics == {}


@pytest.mark.parametrize(
    (
        "maintenance_margin_rate",
        "expected_decision",
        "expected_target_notional",
        "expected_allocated_margin",
        "expected_liquidation_price",
        "expected_liquidation_buffer_bps",
        "expected_maintenance_estimate",
        "expected_cross_maintenance_estimate",
        "expected_reason",
    ),
    [
        (
            MAINTENANCE_MARGIN_INPUT_UNSET,
            "ALLOW_WITH_SIZE",
            800.0,
            800.0,
            0.5,
            9869.0,
            4.0,
            4.0,
            "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        ),
        (
            -0.01,
            "ALLOW_WITH_SIZE",
            800.0,
            800.0,
            0.0,
            9919.0,
            0.0,
            0.0,
            "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        ),
        (
            float("nan"),
            "ALLOW_WITH_SIZE",
            800.0,
            800.0,
            0.0,
            9919.0,
            0.0,
            0.0,
            "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        ),
        (
            float("inf"),
            "BLOCK_LIQUIDATION_RISK",
            0.0,
            0.0,
            None,
            None,
            math.nan,
            math.nan,
            "no_safe_leverage_margin_configuration",
        ),
        (
            float("-inf"),
            "ALLOW_WITH_SIZE",
            800.0,
            800.0,
            0.0,
            9919.0,
            0.0,
            0.0,
            "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        ),
        (
            1,
            "BLOCK_LIQUIDATION_RISK",
            0.0,
            0.0,
            None,
            None,
            0.0,
            0.0,
            "no_safe_leverage_margin_configuration",
        ),
        (
            True,
            "BLOCK_LIQUIDATION_RISK",
            0.0,
            0.0,
            None,
            None,
            0.0,
            0.0,
            "no_safe_leverage_margin_configuration",
        ),
        (
            False,
            "ALLOW_WITH_SIZE",
            800.0,
            800.0,
            0.0,
            9919.0,
            0.0,
            0.0,
            "adaptive_allocation_from_confidence_edge_market_quality_and_risk_budget",
        ),
    ],
    ids=(
        "omitted-default",
        "finite-negative",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "integer",
        "boolean-true",
        "boolean-false",
    ),
)
def test_live_maintenance_result_matches_head_golden_payload(
    maintenance_margin_rate: object,
    expected_decision: str,
    expected_target_notional: float,
    expected_allocated_margin: float,
    expected_liquidation_price: float | None,
    expected_liquidation_buffer_bps: float | None,
    expected_maintenance_estimate: float,
    expected_cross_maintenance_estimate: float,
    expected_reason: str,
) -> None:
    result = allocate_live_candidate(
        _row(
            with_liquidation_atr_evidence=False,
            maintenance_margin_rate=maintenance_margin_rate,
        )
    )

    assert result.decision == expected_decision
    assert result.target_notional_usdt == expected_target_notional
    assert result.recommended_leverage == 1.0
    assert result.allocated_margin_usd == expected_allocated_margin
    assert result.liquidation_price_estimate == expected_liquidation_price
    assert result.liquidation_buffer_bps == expected_liquidation_buffer_bps
    if math.isnan(expected_maintenance_estimate):
        assert math.isnan(result.maintenance_margin_estimate_usd)
    else:
        assert result.maintenance_margin_estimate_usd == expected_maintenance_estimate
    cross_maintenance_estimate = result.model_inputs["cross_margin_stress"][
        "maintenance_margin_estimate_usd"
    ]
    if math.isnan(expected_cross_maintenance_estimate):
        assert math.isnan(cross_maintenance_estimate)
    else:
        assert cross_maintenance_estimate == expected_cross_maintenance_estimate
    expected_model_value = (
        0.005
        if maintenance_margin_rate is MAINTENANCE_MARGIN_INPUT_UNSET
        else maintenance_margin_rate
    )
    model_value = result.model_inputs["maintenance_margin_rate"]
    if isinstance(expected_model_value, float) and math.isnan(expected_model_value):
        assert math.isnan(model_value)
    else:
        assert model_value == expected_model_value
        assert type(model_value) is type(expected_model_value)
    assert result.final_size_reason == expected_reason


@pytest.mark.parametrize(
    ("maintenance_margin_rate", "expected_message"),
    [
        (
            None,
            "'>' not supported between instances of 'NoneType' and 'float'",
        ),
        (
            "0.005",
            "'>' not supported between instances of 'str' and 'float'",
        ),
        (
            _LiveMaintenanceArbitraryValue(),
            "'>' not supported between instances of "
            "'_LiveMaintenanceArbitraryValue' and 'float'",
        ),
    ],
    ids=("explicit-none", "numeric-string", "arbitrary-object"),
)
def test_live_maintenance_exception_matches_head_golden_surface(
    maintenance_margin_rate: object,
    expected_message: str,
) -> None:
    with pytest.raises(TypeError) as error:
        allocate_live_candidate(
            _row(
                with_liquidation_atr_evidence=False,
                maintenance_margin_rate=maintenance_margin_rate,
            )
        )

    assert str(error.value) == expected_message


def test_live_explicit_none_early_block_matches_head_golden_exception() -> None:
    with pytest.raises(TypeError) as error:
        allocate_live_candidate(
            _row(
                with_liquidation_atr_evidence=False,
                maintenance_margin_rate=None,
                risk_veto=True,
                risk_veto_reason="head-golden-veto",
            )
        )

    assert str(error.value) == ("'>' not supported between instances of 'NoneType' and 'float'")


def test_live_omitted_maintenance_preserves_legacy_default_behavior() -> None:
    omitted = allocate_live_candidate(
        replace(
            _row(),
            maintenance_margin_rate=MAINTENANCE_MARGIN_INPUT_UNSET,
        )
    )
    explicit_legacy_value = allocate_live_candidate(_row(maintenance_margin_rate=0.005))

    assert omitted.decision == explicit_legacy_value.decision
    assert omitted.target_notional_usdt == explicit_legacy_value.target_notional_usdt
    assert omitted.recommended_leverage == explicit_legacy_value.recommended_leverage
    assert omitted.liquidation_price_estimate == (explicit_legacy_value.liquidation_price_estimate)
    assert omitted.liquidation_buffer_bps == (explicit_legacy_value.liquidation_buffer_bps)
    assert "maintenance_margin_rate_effective" not in omitted.model_inputs
    assert "maintenance_margin_evidence_status" not in omitted.model_inputs


def test_untrusted_high_leverage_envelope_is_explicitly_capped_at_1x() -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=1000.0,
            volatility_bps=1.0,
            stop_distance_bps=1.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            fee_bps=0.0,
            permitted_leverage_values=tuple(float(value) for value in range(1, 76)),
        ),
        RiskEnvelope(max_effective_leverage=75.0),
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == result.effective_leverage == 1.0
    assert result.model_inputs["paper_above_1x_growth_authorized"] is False
    assert result.model_inputs["paper_growth_envelope_authorization_status"] == ("BLOCKED")
    assert result.model_inputs["paper_1x_cap_classification"] == (
        "UNTRUSTED_OR_INCOMPLETE_GROWTH_RECEIPT_FAIL_CLOSED_1X"
    )


def test_envelope_already_capped_at_1x_does_not_claim_authentication() -> None:
    result = allocate_paper_candidate(
        _row(confidence_calibrated=1.0, expected_move_after_cost_bps=1000.0),
        RiskEnvelope(max_effective_leverage=1.0),
    )

    assert result.effective_leverage == 1.0
    assert result.model_inputs["paper_above_1x_growth_authorized"] is False
    assert result.model_inputs["paper_growth_envelope_authorization_status"] == (
        "NOT_REQUIRED_ENVELOPE_ALREADY_CAPPED_AT_1X"
    )
    assert result.model_inputs["paper_1x_cap_classification"] == (
        "ENVELOPE_ALREADY_CAPPED_AT_1X_NO_GROWTH_AUTHORITY"
    )


def test_authentic_growth_receipt_is_the_only_path_above_1x() -> None:
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=1000.0,
            volatility_bps=1.0,
            stop_distance_bps=1.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            fee_bps=0.0,
            permitted_leverage_values=tuple(float(value) for value in range(1, 76)),
        ),
        RiskEnvelope(max_effective_leverage=75.0),
    )

    assert result.effective_leverage > 1.0
    assert result.model_inputs["paper_above_1x_growth_authorized"] is True
    assert result.model_inputs["paper_growth_envelope_authorization_status"] == ("READY")
    assert result.model_inputs["paper_1x_cap_classification"] == (
        "AUTHENTICATED_DYNAMIC_ENVELOPE_RESULT"
    )


def test_coherently_resealed_forged_edge_cohort_fails_semantic_replay() -> None:
    row, envelope, original = authorize_growth(
        _row(
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=1000.0,
            volatility_bps=1.0,
        ),
        RiskEnvelope(max_effective_leverage=75.0),
    )
    receipt = deepcopy(original)
    calculation = receipt["calculation_input_material"]
    authorization = calculation["growth_authorization_receipt"]
    edge = authorization["component_receipts"]["strict_after_cost_edge"]
    edge_source = edge["source_material"]
    cohort = edge_source["strict_after_cost_edge_cohort_material"]
    cohort["rows"][0]["realized_after_cost_bps"] = 5000.0
    edge_source["strict_after_cost_edge_cohort_material_hash"] = _canonical_test_receipt_hash(
        cohort
    )
    _reseal_growth_receipt(receipt)

    result = allocate_paper_candidate(
        _replace_growth_receipt(row, receipt),
        envelope,
    )

    assert result.effective_leverage == 1.0
    assert result.model_inputs["paper_growth_envelope_authorization_status"] == ("BLOCKED")
    assert any(
        reason.startswith("PAPER_STRICT_EDGE_REPLAY_MISMATCH:")
        for reason in result.model_inputs["paper_growth_envelope_authorization_rejection_reasons"]
    )


def test_resealed_unpromoted_checkpoint_cannot_borrow_growth_authority() -> None:
    row, envelope, original = authorize_growth(
        _row(confidence_calibrated=1.0, expected_move_after_cost_bps=1000.0),
        RiskEnvelope(max_effective_leverage=75.0),
    )
    receipt = deepcopy(original)
    calculation = receipt["calculation_input_material"]
    authorization = calculation["growth_authorization_receipt"]
    checkpoint = authorization["component_receipts"]["promoted_checkpoint"]
    checkpoint["source_material"]["checkpoint_promotion_allowed"] = False
    _reseal_growth_receipt(receipt)

    result = allocate_paper_candidate(
        _replace_growth_receipt(row, receipt),
        envelope,
    )

    assert result.effective_leverage == 1.0
    assert (
        "PAPER_CANDIDATE_CHECKPOINT_PROMOTION_INVALID"
        in result.model_inputs["paper_growth_envelope_authorization_rejection_reasons"]
    )


def test_active_safe_checkpoint_fallback_cannot_authorize_growth() -> None:
    row, envelope, original = authorize_growth(
        _row(confidence_calibrated=1.0, expected_move_after_cost_bps=1000.0),
        RiskEnvelope(max_effective_leverage=75.0),
    )
    receipt = deepcopy(original)
    calculation = receipt["calculation_input_material"]
    authorization = calculation["growth_authorization_receipt"]
    checkpoint = authorization["component_receipts"]["promoted_checkpoint"]
    checkpoint["candidate_checkpoint_id_source"] = "active_safe_checkpoint_id"
    _reseal_growth_receipt(receipt)

    result = allocate_paper_candidate(
        _replace_growth_receipt(row, receipt),
        envelope,
    )

    assert result.effective_leverage == 1.0
    assert (
        "PAPER_CANDIDATE_CHECKPOINT_LINEAGE_INVALID"
        in result.model_inputs["paper_growth_envelope_authorization_rejection_reasons"]
    )


def test_resealed_market_context_cannot_forge_allocator_liquidity_score() -> None:
    row, envelope, original = authorize_growth(
        _row(confidence_calibrated=1.0, expected_move_after_cost_bps=1000.0),
        RiskEnvelope(max_effective_leverage=75.0),
    )
    receipt = deepcopy(original)
    calculation = receipt["calculation_input_material"]
    authorization = calculation["growth_authorization_receipt"]
    context = authorization["component_receipts"]["candidate_market_context"]
    liquidity_material = context["liquidity_source_material"]
    liquidity_material["derivation_inputs"]["market_microstructure"]["liquidity_score"] = 0.1
    liquidity_hash = _canonical_test_receipt_hash(liquidity_material)
    context["liquidity_source_material_hash"] = liquidity_hash
    lineage = dict(row.lineage_ids)
    lineage[PAPER_ALLOCATOR_LIQUIDITY_SOURCE_MATERIAL_LINEAGE_KEY] = liquidity_material
    lineage[PAPER_ALLOCATOR_LIQUIDITY_SOURCE_HASH_LINEAGE_KEY] = liquidity_hash
    row = replace(row, lineage_ids=lineage)
    _reseal_growth_receipt(receipt)

    result = allocate_paper_candidate(
        _replace_growth_receipt(row, receipt),
        envelope,
    )

    assert result.effective_leverage == 1.0
    assert (
        "PAPER_LIQUIDITY_SOURCE_DERIVATION_MISMATCH"
        in result.model_inputs["paper_growth_envelope_authorization_rejection_reasons"]
    )


def test_paper_isolated_liquidation_geometry_is_side_aware() -> None:
    long_geometry = paper_isolated_liquidation_geometry(
        side="long",
        entry_price=100.0,
        leverage=20.0,
        maintenance_margin_rate=0.005,
    )
    short_geometry = paper_isolated_liquidation_geometry(
        side="short",
        entry_price=100.0,
        leverage=20.0,
        maintenance_margin_rate=0.005,
    )

    assert long_geometry is not None
    assert short_geometry is not None
    expected_long_fraction = (1.0 / 20.0 - 0.005) / (1.0 - 0.005)
    expected_short_fraction = (1.0 / 20.0 - 0.005) / (1.0 + 0.005)
    assert long_geometry == pytest.approx(
        (expected_long_fraction * 10000.0, 100.0 * (1.0 - expected_long_fraction))
    )
    assert short_geometry == pytest.approx(
        (
            expected_short_fraction * 10000.0,
            100.0 * (1.0 + expected_short_fraction),
        )
    )


def test_sol_short_20x_liquidation_buffer_boundary_uses_short_denominator() -> None:
    row = _row(
        symbol="SOLUSDT",
        action="short",
        price=100.0,
        fee_bps=0.0,
        slippage_bps=0.0,
        expected_funding_bps=0.0,
        permitted_leverage_values=(20.0,),
    )
    envelope = RiskEnvelope(
        max_effective_leverage=20.0,
        min_liquidation_buffer_bps=0.0,
    )
    geometry = paper_isolated_liquidation_geometry(
        side="short",
        entry_price=100.0,
        leverage=20.0,
        maintenance_margin_rate=0.005,
    )
    assert geometry is not None
    residual_buffer = geometry[0] - 100.0

    just_safe = _select_margin_configuration(
        row,
        gross_notional=1000.0,
        stop_distance_bps=100.0,
        envelope=envelope,
        maintenance_margin_rate=0.005,
        target_leverage=20.0,
        minimum_liquidation_buffer_bps=residual_buffer - 1e-6,
        paper_mode=True,
    )
    just_unsafe = _select_margin_configuration(
        row,
        gross_notional=1000.0,
        stop_distance_bps=100.0,
        envelope=envelope,
        maintenance_margin_rate=0.005,
        target_leverage=20.0,
        minimum_liquidation_buffer_bps=residual_buffer + 1e-6,
        paper_mode=True,
    )

    assert just_safe is not None
    assert just_safe[0] == 20.0
    assert just_safe[2] == pytest.approx(geometry[1])
    assert just_unsafe is None


def test_nonfinite_paper_evidence_fails_closed_before_adaptive_math() -> None:
    result = allocate_paper_candidate(
        _row(
            expected_move_after_cost_bps=float("nan"),
            confidence_calibrated=0.99,
        )
    )

    assert result.decision == "BLOCK_BAD_MARKET_STATE"
    assert result.target_notional_usdt == 0.0
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["paper_allocator_input_validation_status"] == "FAIL_CLOSED"
    assert (
        "NONFINITE_EXPECTED_MOVE_AFTER_COST_BPS"
        in result.model_inputs["paper_allocator_input_rejection_reasons"]
    )


def test_recommendation_invariant_violation_cannot_be_overridden_by_confidence(
    monkeypatch,
) -> None:
    from v2.backend.app.services.paper_trade_management import leverage_recommendation

    monkeypatch.setattr(
        leverage_recommendation,
        "validate_leverage_recommendation",
        lambda _recommendation: ["INVARIANT_VIOLATED:test"],
    )
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=500.0,
            volatility_bps=1.0,
        ),
        RiskEnvelope(max_effective_leverage=10.0),
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["phase8_leverage_recommendation_violations"]
    assert result.model_inputs["leverage_selection_reason"] == (
        "phase8_leverage_recommendation_invariant_violation_fail_closed"
    )


def test_leverage_target_has_no_discontinuity_at_removed_legacy_edge_threshold() -> None:
    just_below = allocate_authorized_growth(
        _row(
            expected_move_after_cost_bps=34.99,
            volatility_bps=15.0,
            confidence_calibrated=0.8,
        )
    )
    just_above = allocate_authorized_growth(
        _row(
            expected_move_after_cost_bps=35.01,
            volatility_bps=15.0,
            confidence_calibrated=0.8,
        )
    )

    below_target = just_below.model_inputs["leverage_target"]
    above_target = just_above.model_inputs["leverage_target"]
    assert above_target > below_target
    assert above_target - below_target < 0.01


def test_leverage_target_responds_to_liquidity_regime_and_dynamic_envelope() -> None:
    strong = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.95,
            expected_move_after_cost_bps=250.0,
            volatility_bps=10.0,
            liquidity_score=1.0,
            regime_score=1.0,
        ),
        RiskEnvelope(max_effective_leverage=3.0),
    )
    degraded = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.95,
            expected_move_after_cost_bps=250.0,
            volatility_bps=10.0,
            liquidity_score=0.4,
            regime_score=0.5,
        ),
        RiskEnvelope(max_effective_leverage=3.0),
    )
    capped = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.95,
            expected_move_after_cost_bps=250.0,
            volatility_bps=10.0,
            liquidity_score=1.0,
            regime_score=1.0,
        ),
        RiskEnvelope(max_effective_leverage=1.5),
    )

    assert strong.recommended_leverage > 1.0
    assert degraded.model_inputs["leverage_target"] < strong.model_inputs["leverage_target"]
    assert capped.model_inputs["leverage_target"] <= 1.5
    assert capped.recommended_leverage <= 1.5


def test_paper_leverage_uses_phase8_target_for_high_confidence_low_volatility_edge() -> None:
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    # The recommendation exposes the authorized adaptive symbol/volatility
    # ceiling, while selection is further bounded by the supplied dynamic
    # envelope and the permitted exchange ladder.
    assert result.recommended_leverage == 2.0
    assert result.effective_leverage == 2.0
    assert result.allocated_margin_usd < result.gross_notional_usd
    assert (
        result.model_inputs["raw_leverage_target"]
        == result.model_inputs["phase8_leverage_recommendation"]["recommended_leverage"]
    )
    assert 2.0 < result.model_inputs["leverage_target"] < 3.0
    assert result.model_inputs["leverage_target"] <= result.model_inputs["raw_leverage_target"]
    assert result.model_inputs["selected_leverage"] == 2.0
    assert result.model_inputs["leverage_formula"] == (
        "min(phase8_recommended_leverage, "
        "1 + (min(dynamic_envelope_cap, authorized_symbol_ceiling) - 1)"
        " * adaptive_quality)"
    )
    assert result.model_inputs["leverage_live_mutation_allowed"] is False
    assert result.model_inputs["phase8_leverage_recommendation"]["paper_only"] is True
    assert result.model_inputs["phase8_leverage_recommendation"]["mutates_exchange"] is False


def test_phase6_simulation_fields_scale_with_risk_and_do_not_mutate_live() -> None:
    low_risk = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            total_exposure_usdt=100.0,
            correlation_exposure_pct=0.01,
        )
    )
    higher_pressure = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            total_exposure_usdt=100.0,
            correlation_exposure_pct=0.12,
            drawdown_bps=200.0,
        )
    )

    low_payload = low_risk.to_payload()
    pressure_payload = higher_pressure.to_payload()

    assert low_risk.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert higher_pressure.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert low_payload["max_loss_if_stop_hit"] > low_payload["expected_fees_usd"]
    assert low_payload["risk_reward"] == round(
        low_payload["expected_net_pnl_usd"] / low_payload["max_loss_if_stop_hit"],
        8,
    )
    assert low_payload["portfolio_exposure_after_trade"] == (
        low_payload["gross_notional_usd"] + 100.0
    )
    assert pressure_payload["risk_of_ruin_contribution"] > low_payload["risk_of_ruin_contribution"]
    assert (
        pressure_payload["correlation_exposure_after_trade"]
        > low_payload["correlation_exposure_after_trade"]
    )
    assert pressure_payload["model_inputs"]["leverage_live_mutation_allowed"] is False
    assert pressure_payload["model_inputs"]["margin_mode_live_mutation_allowed"] is False


def test_paper_leverage_continuously_tracks_small_edge_without_a_pass_cliff() -> None:
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.70,
            expected_move_after_cost_bps=28.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            spread_bps=1.0,
            slippage_bps=1.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert (
        result.model_inputs["raw_leverage_target"]
        == result.model_inputs["phase8_leverage_recommendation"]["recommended_leverage"]
    )
    assert 1.0 < result.model_inputs["leverage_target"] < 2.0
    assert result.model_inputs["leverage_target"] <= result.model_inputs["raw_leverage_target"]
    assert result.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )


def test_high_spread_and_funding_pressure_caps_dynamic_leverage() -> None:
    # Cost drag (spread + slippage + fees + funding) that approaches the edge
    # continuously shrinks the target onto the permitted 1x rung.
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.70,
            expected_move_after_cost_bps=120.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            spread_bps=25.0,
            slippage_bps=10.0,
            expected_funding_bps=60.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert 1.0 < result.model_inputs["leverage_target"] < 2.0
    assert result.model_inputs["leverage_cost_drag_bps"] == 99.0
    assert result.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )


def test_paper_correlation_pressure_continuously_shrinks_leverage_target() -> None:
    result = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.78,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.16,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert (
        result.model_inputs["raw_leverage_target"]
        == result.model_inputs["phase8_leverage_recommendation"]["recommended_leverage"]
    )
    assert 1.0 < result.model_inputs["leverage_target"] < 2.0
    assert result.model_inputs["leverage_target"] <= result.model_inputs["raw_leverage_target"]
    assert result.model_inputs["leverage_correlation_resilience"] < 0.12
    assert result.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )


def test_phase8_volatility_liquidation_ceiling_remains_binding_on_allocator() -> None:
    result = allocate_authorized_growth(
        _row(
            symbol="BTCUSDT",
            confidence_calibrated=0.99,
            expected_move_after_cost_bps=500.0,
            volatility_bps=100.0,
            liquidity_score=1.0,
            regime_score=1.0,
            stop_distance_bps=200.0,
            permitted_leverage_values=tuple(float(value) for value in range(1, 76)),
        ),
        RiskEnvelope(max_effective_leverage=75.0),
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    recommendation = result.model_inputs["phase8_leverage_recommendation"]
    assert recommendation["symbol_leverage_ceiling"] == 75
    assert (
        1.0
        < recommendation["recommended_leverage"]
        <= recommendation["liquidation_safe_leverage_ceiling"]
    )
    assert recommendation["liquidation_distance_bps"] >= (5.0 * 100.0) - 1e-9
    assert result.model_inputs["raw_leverage_target"] == recommendation["recommended_leverage"]
    assert (
        1.0 < result.model_inputs["leverage_target"] <= result.model_inputs["raw_leverage_target"]
    )
    assert result.effective_leverage in result.model_inputs["permitted_leverage_values"]
    assert result.effective_leverage <= result.model_inputs["leverage_target"]


def test_receipt_bound_low_atr_btc_can_select_above_1x_with_g10_identity(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT", "5")
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_MAJOR_TIER1", "75")
    result = allocate_authorized_growth(
        _row(
            symbol="BTCUSDT",
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=1000.0,
            volatility_bps=1.0,
            stop_distance_bps=1.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            fee_bps=0.0,
            expected_funding_bps=0.0,
            maintenance_margin_rate=0.004,
            permitted_leverage_values=tuple(float(value) for value in range(1, 76)),
        ),
        RiskEnvelope(max_effective_leverage=75.0),
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert 1.0 < result.effective_leverage <= 75.0
    assert result.effective_leverage <= result.model_inputs["leverage_dynamic_envelope_cap"]
    assert (
        result.liquidation_buffer_bps
        >= result.model_inputs["paper_required_liquidation_buffer_bps"]
    )
    assert result.model_inputs["paper_required_liquidation_buffer_bps"] == 5.0
    assert result.model_inputs["paper_liquidation_atr_evidence_status"] == "READY"
    assert result.model_inputs["paper_liquidation_buffer_contract_status"] == "READY"
    assert result.allocated_margin_usd * result.effective_leverage == pytest.approx(
        result.gross_notional_usd,
        rel=1e-9,
        abs=1e-8,
    )


@pytest.mark.parametrize(
    ("symbol", "permitted_ceiling", "envelope_ceiling", "expected_ceiling"),
    (
        ("BTCUSDT", 17, 75.0, 17.0),
        ("SOLUSDT", 75, 75.0, 50.0),
        ("DOGEUSDT", 75, 75.0, 20.0),
    ),
)
def test_receipt_bound_leverage_respects_bracket_and_authorized_symbol_caps(
    monkeypatch,
    symbol: str,
    permitted_ceiling: int,
    envelope_ceiling: float,
    expected_ceiling: float,
) -> None:
    monkeypatch.setenv("PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT", "5")
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_MAJOR_TIER1", "75")
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_MAJOR_TIER2", "50")
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_ALT", "20")
    result = allocate_authorized_growth(
        _row(
            symbol=symbol,
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=1000.0,
            volatility_bps=1.0,
            stop_distance_bps=1.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            fee_bps=0.0,
            expected_funding_bps=0.0,
            maintenance_margin_rate=0.004,
            permitted_leverage_values=tuple(
                float(value) for value in range(1, permitted_ceiling + 1)
            ),
        ),
        RiskEnvelope(max_effective_leverage=envelope_ceiling),
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert 1.0 < result.effective_leverage <= expected_ceiling
    assert result.effective_leverage in result.model_inputs["permitted_leverage_values"]


def test_receipt_bound_atr_increase_cannot_increase_selected_leverage(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT", "5")
    selected = []
    results = []
    for atr_bps in (1.0, 10.0, 20.0, 50.0, 80.0):
        result = allocate_authorized_growth(
            _row(
                confidence_calibrated=1.0,
                expected_move_after_cost_bps=1000.0,
                volatility_bps=atr_bps,
                stop_distance_bps=1.0,
                spread_bps=0.0,
                slippage_bps=0.0,
                fee_bps=0.0,
                expected_funding_bps=0.0,
                maintenance_margin_rate=0.004,
                permitted_leverage_values=tuple(float(value) for value in range(1, 76)),
            ),
            RiskEnvelope(max_effective_leverage=75.0),
        )
        selected.append(result.effective_leverage)
        results.append((atr_bps, result))

    assert selected == sorted(selected, reverse=True)
    assert selected[0] > 1.0
    assert 1.0 < selected[-1] < selected[0]
    for atr_bps, result in results:
        recommendation = result.model_inputs["phase8_leverage_recommendation"]
        assert recommendation["symbol_leverage_ceiling"] == 75
        assert (
            recommendation["recommended_leverage"]
            <= recommendation["liquidation_safe_leverage_ceiling"]
        )
        assert recommendation["liquidation_distance_bps"] >= (5.0 * atr_bps) - 1e-9
        assert result.effective_leverage in result.model_inputs["permitted_leverage_values"]
        assert result.effective_leverage <= result.model_inputs["leverage_target"]
        assert result.effective_leverage <= 75.0


def test_missing_or_tampered_liquidation_atr_receipt_caps_paper_at_1x() -> None:
    common = {
        "confidence_calibrated": 1.0,
        "expected_move_after_cost_bps": 1000.0,
        "volatility_bps": 1.0,
        "entry_atr_bps": 1.0,
        "stop_distance_bps": 1.0,
        "permitted_leverage_values": tuple(float(value) for value in range(1, 76)),
    }
    missing = allocate_paper_candidate(
        _row(with_liquidation_atr_evidence=False, **common),
        RiskEnvelope(max_effective_leverage=75.0),
    )
    valid_row = _row(**common)
    tampered_lineage = dict(valid_row.lineage_ids)
    tampered_receipt = dict(tampered_lineage[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY])
    tampered_receipt["atr_bps"] = 0.1
    tampered_lineage[PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY] = tampered_receipt
    tampered = allocate_paper_candidate(
        replace(valid_row, lineage_ids=tampered_lineage),
        RiskEnvelope(max_effective_leverage=75.0),
    )

    for result in (missing, tampered):
        assert result.effective_leverage == 1.0
        assert result.model_inputs["leverage_target"] == 1.0
        assert result.model_inputs["paper_liquidation_atr_evidence_status"] == "BLOCKED"
        assert result.model_inputs["paper_liquidation_buffer_contract_status"] == "BLOCKED"
        assert result.model_inputs["phase8_leverage_recommendation"]["recommended_leverage"] == 1
        assert result.model_inputs["raw_leverage_target"] == 1.0


def test_live_allocator_does_not_consume_paper_liquidation_atr_contract() -> None:
    result = allocate_live_candidate(
        _row(
            with_liquidation_atr_evidence=False,
            confidence_calibrated=1.0,
            expected_move_after_cost_bps=1000.0,
            volatility_bps=1.0,
            entry_atr_bps=1.0,
            permitted_leverage_values=tuple(float(value) for value in range(1, 76)),
        ),
        RiskEnvelope(max_effective_leverage=75.0),
    )

    assert result.effective_leverage == 1.0
    assert result.model_inputs["leverage_selection_reason"] == (
        "live_mode_requires_operator_approval_for_dynamic_leverage_change"
    )
    assert "paper_required_liquidation_buffer_bps" not in result.model_inputs
    assert result.recommended_leverage == 1.0


def test_high_confidence_never_overrides_cost_drawdown_or_correlation_evidence() -> None:
    small_edge = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=28.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            spread_bps=1.0,
            slippage_bps=1.0,
        )
    )
    assert small_edge.recommended_leverage == 2.0
    assert small_edge.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )

    high_correlation = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            correlation_exposure_pct=0.16,
        )
    )
    assert high_correlation.recommended_leverage == 1.0
    assert high_correlation.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )

    high_drawdown = allocate_authorized_growth(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            drawdown_bps=400.0,
        )
    )
    assert high_drawdown.recommended_leverage == 1.0
    assert high_drawdown.model_inputs["leverage_selection_reason"] == (
        "continuous_market_evidence_within_supplied_dynamic_envelope"
    )

    assert (
        high_correlation.model_inputs["leverage_target"]
        < small_edge.model_inputs["leverage_target"]
    )
    assert (
        high_drawdown.model_inputs["leverage_target"] < small_edge.model_inputs["leverage_target"]
    )
    for adaptive in (small_edge, high_correlation, high_drawdown):
        assert adaptive.model_inputs["leverage_live_mutation_allowed"] is False
        assert adaptive.recommended_leverage <= RiskEnvelope().max_effective_leverage

    # Live mode remains 1x without operator approval.
    live = allocate_live_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
            drawdown_bps=400.0,
        )
    )
    assert live.recommended_leverage == 1.0
    assert live.model_inputs["leverage_selection_reason"] == (
        "live_mode_requires_operator_approval_for_dynamic_leverage_change"
    )


def test_live_leverage_selection_remains_lowest_safe_without_operator_approval() -> None:
    result = allocate_live_candidate(
        _row(
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.recommended_leverage == 1.0
    assert result.model_inputs["leverage_target"] == 1.0
    assert result.model_inputs["leverage_selection_reason"] == (
        "live_mode_requires_operator_approval_for_dynamic_leverage_change"
    )
    assert result.model_inputs["leverage_live_mutation_allowed"] is False
    assert result.recommended_margin_mode == "isolated"
    assert result.model_inputs["selected_margin_mode"] == "isolated"
    assert result.model_inputs["margin_mode_live_mutation_allowed"] is False
    assert result.model_inputs["margin_mode_selection_reason"] == (
        "live_mode_requires_operator_approval_for_margin_mode_change"
    )


def test_live_explicit_negative_maintenance_rate_preserves_legacy_payload() -> None:
    result = allocate_live_candidate(
        _row(
            maintenance_margin_rate=-0.01,
            confidence_calibrated=0.88,
            expected_move_after_cost_bps=95.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.model_inputs["maintenance_margin_rate"] == -0.01
    assert "maintenance_margin_rate_effective" not in result.model_inputs
    assert "maintenance_margin_evidence_status" not in result.model_inputs


def test_no_safe_liquidation_buffer_blocks_even_when_edge_is_positive() -> None:
    result = allocate_paper_candidate(
        _row(
            available_margin=100.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=6000.0,
        )
    )

    assert result.decision == "BLOCK_LIQUIDATION_RISK"
    assert result.target_notional_usdt == 0.0


def test_no_safe_live_liquidation_block_excludes_paper_leverage_diagnostics() -> None:
    result = allocate_live_candidate(
        _row(
            available_margin=100.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=120.0,
            stop_distance_bps=9000.0,
            maintenance_margin_rate=0.2,
        )
    )

    assert result.decision == "BLOCK_LIQUIDATION_RISK"
    assert result.target_notional_usdt == 0.0
    assert result.model_inputs["leverage_selection_reason"] == (
        "blocked_allocation_uses_1x_leverage:no_safe_leverage_margin_configuration"
    )
    assert result.model_inputs["leverage_edge_cost_ratio"] == 0.0
    assert {
        "paper_margin_may_exceed_evidence_leverage_target",
        "paper_quality_sizing_weight",
        "paper_risk_budget_fraction",
        "phase8_leverage_recommendation",
    }.isdisjoint(result.model_inputs)


def test_risk_envelope_can_veto_allocator_output() -> None:
    result = allocate_paper_candidate(
        _row(risk_veto=True, risk_veto_reason="operator_drawdown_budget_locked"),
        RiskEnvelope(),
    )

    assert result.decision == "BLOCK_EXPOSURE_BUDGET"
    assert result.risk_veto_reason_if_blocked == "operator_drawdown_budget_locked"


def test_hedge_flag_cannot_amplify_size_without_atomic_funded_hedge_proof() -> None:
    base_kwargs = dict(
        confidence_calibrated=0.9,
        expected_move_after_cost_bps=60.0,
        entry_atr_bps=400.0,
    )
    unhedged = allocate_paper_candidate(_row(**base_kwargs))
    hedged = allocate_paper_candidate(_row(**base_kwargs, adaptive_hedge_sizing_enabled=True))
    assert unhedged.decision == "ALLOW_WITH_SIZE"
    assert hedged.decision == "ALLOW_WITH_SIZE"
    assert hedged.gross_notional_usd == unhedged.gross_notional_usd
    assert hedged.risk_budget_usd == unhedged.risk_budget_usd
    assert hedged.max_loss_if_stop_hit == unhedged.max_loss_if_stop_hit
    diag = hedged.model_inputs.get("hedge_aware_sizing")
    assert diag is not None
    assert diag["status"] == "DISABLED_NO_ATOMIC_FUNDED_HEDGE_PROOF"
    assert diag["enabled"] is False
    assert diag["size_amplification"] == 1.0


def test_live_golden_identity_payload_and_hedge_sizing_match_legacy_contract() -> None:
    common = {
        "confidence_calibrated": 0.9,
        "expected_move_after_cost_bps": 120.0,
        "stop_distance_bps": 1_000.0,
        "entry_atr_bps": None,
        "adaptive_hedge_sizing_enabled": True,
        "lineage_ids": {"prediction_id": "live-golden"},
    }
    result = allocate_live_candidate(
        _row(with_liquidation_atr_evidence=False, **common),
        RiskEnvelope(
            max_total_portfolio_risk_pct=1.0,
            max_single_symbol_exposure_pct=1.0,
        ),
    )
    raw_identity = "|".join(
        (
            "live",
            "BTCUSDT",
            "1m",
            "long",
            "live-golden",
            "0.90000000",
            "120.00000000",
        )
    )
    expected_id = "alloc_" + hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()[:24]
    payload = result.to_payload()

    assert result.allocation_id == expected_id
    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert {
        "allocation_input_schema_version",
        "allocation_input_hash",
        "allocation_input_hash_algorithm",
        "allocation_input_material",
    }.isdisjoint(payload)
    assert "allocation_input_hash" not in result.model_inputs
    assert "paper_risk_budget_fraction" not in result.model_inputs
    assert "max_qty" not in result.model_inputs
    assert "margin_mode_requested_before_stress" not in result.model_inputs
    assert result.model_inputs["margin_mode_volatility_pressure"] == 0.0
    assert "liquidation_simulation_status" not in result.model_inputs["cross_margin_stress"]
    hedge = result.model_inputs["hedge_aware_sizing"]
    assert set(hedge) == {
        "hedge_arm_fraction",
        "hedge_leg_drag_bps",
        "full_stop_bps",
        "hedge_sizing_stop_bps",
        "size_amplification",
    }
    assert hedge["size_amplification"] > 1.0


def test_hedge_aware_sizing_disabled_leaves_sizing_unchanged() -> None:
    row = _row(confidence_calibrated=0.9, entry_atr_bps=120.0)
    result = allocate_paper_candidate(row)
    assert result.model_inputs.get("hedge_aware_sizing") is None


def test_paper_probe_fraction_is_applied_before_filters_and_all_derivations() -> None:
    base = allocate_paper_candidate(
        _row(step_size=0.1, min_notional=5.0, paper_risk_budget_fraction=1.0)
    )
    probe = allocate_paper_candidate(
        _row(step_size=0.1, min_notional=5.0, paper_risk_budget_fraction=0.25)
    )

    assert base.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert probe.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert probe.target_notional_usdt == pytest.approx(base.target_notional_usdt * 0.25)
    assert probe.target_quantity == pytest.approx(base.target_quantity * 0.25)
    assert probe.risk_budget_usd == pytest.approx(base.risk_budget_usd * 0.25)
    assert probe.allocated_margin_usd * probe.effective_leverage == pytest.approx(
        probe.gross_notional_usd
    )
    for field in (
        "expected_fees_usd",
        "expected_slippage_usd",
        "expected_funding_usd",
        "expected_gross_pnl_usd",
        "expected_net_pnl_usd",
        "expected_shortfall_usd",
        "max_loss_if_stop_hit",
        "max_loss_usd",
        "stop_loss_usd",
        "take_profit_usd",
        "mfe_usd",
        "mae_usd",
        "liquidation_distance_usd",
        "hedge_budget_usd",
        "net_delta_usd",
        "gross_exposure_usd",
        "long_exposure_usd",
        "short_exposure_usd",
        "btc_beta_exposure_usd",
        "eth_beta_exposure_usd",
        "isolated_margin_required_usd",
        "cross_margin_stress_used_usd",
        "worst_case_portfolio_loss_usd",
        "maintenance_margin_estimate_usd",
    ):
        assert getattr(probe, field) == pytest.approx(getattr(base, field) * 0.25)
    # Correlation dollars are intentionally nonlinear: the reduced notional
    # also reduces the post-trade correlation ratio used by the hedge model.
    assert probe.correlation_exposure_usd == pytest.approx(
        probe.gross_notional_usd * probe.correlation_exposure_after_trade
    )
    assert probe.model_inputs["paper_risk_budget_fraction"] == 0.25
    assert probe.model_inputs["paper_reduced_risk_budget_applied_pre_quantization"] is True
    assert probe.model_inputs["hedge_engine"]["gross_exposure_usd"] == pytest.approx(
        probe.gross_exposure_usd
    )
    assert probe.model_inputs["cross_margin_stress"][
        "isolated_margin_required_usd"
    ] == pytest.approx(probe.isolated_margin_required_usd)
    assert probe.final_size_reason == (
        "paper_allocation_from_reduced_risk_budget_and_ceiling_pre_quantization"
    )


def test_paper_probe_fraction_never_rounds_up_to_exchange_minimum() -> None:
    result = allocate_paper_candidate(
        _row(
            step_size=0.1,
            min_notional=250.0,
            paper_risk_budget_fraction=0.25,
        )
    )

    assert result.decision == "BLOCK_RISK_BUDGET_BELOW_EXECUTABLE_MINIMUM"
    assert result.target_notional_usdt == 0.0
    assert result.final_size_reason == "paper_risk_budget_below_exact_executable_minimum"
    assert result.model_inputs["paper_execution_minimum"]["feasible"] is False
    assert result.model_inputs["paper_risk_budget_fraction"] == 0.25


@pytest.mark.parametrize(
    ("exchange_filter", "failed_filter_field"),
    [
        ({"min_notional": 700.0}, "paper_post_quantization_below_min_notional"),
        ({"min_qty": 7.0}, "paper_post_quantization_below_min_qty"),
    ],
)
def test_paper_coarse_step_fails_closed_when_final_size_is_below_exchange_minimum(
    exchange_filter: dict[str, float],
    failed_filter_field: str,
) -> None:
    result = allocate_paper_candidate(
        _row(
            step_size=3.0,
            **exchange_filter,
        )
    )

    # The adaptive target is $800 (8 units), but a 3-unit step can emit only
    # 6 units / $600.  The allocator may not round that result up to satisfy a
    # venue minimum and may not carry the pre-step PASS into the final result.
    assert result.decision == "BLOCK_RISK_BUDGET_BELOW_EXECUTABLE_MINIMUM"
    assert result.target_quantity == 0.0
    assert result.target_notional_usdt == 0.0
    assert result.allocated_margin_usd == 0.0
    assert result.final_size_reason == "paper_risk_budget_below_exact_executable_minimum"
    minimum = result.model_inputs["paper_execution_minimum"]
    assert minimum["feasible"] is False
    assert minimum["final_target_notional"] == 800.0
    assert minimum["minimum_executable_notional"] == 900.0
    assert minimum["execution_headroom_usd"] == -100.0


def test_paper_post_quantization_notional_drives_margin_and_liquidation_stress() -> None:
    result = allocate_authorized_growth(
        _row(
            step_size=3.0,
            min_notional=250.0,
            confidence_calibrated=0.9,
            expected_move_after_cost_bps=180.0,
            volatility_bps=15.0,
            stop_distance_bps=80.0,
        )
    )

    assert result.decision == "REDUCE_SIZE"
    assert result.target_quantity == 6.0
    assert result.target_notional_usdt == round(
        abs(result.target_quantity * 100.0),
        8,
    )
    assert result.gross_notional_usd == result.target_notional_usdt == 600.0
    assert result.recommended_leverage == result.effective_leverage == 2.0
    assert result.allocated_margin_usd == round(
        result.target_notional_usdt / result.effective_leverage,
        8,
    )
    assert result.allocated_margin_usd == 300.0
    assert result.model_inputs["selected_allocated_margin_usd"] == 300.0
    assert result.isolated_margin_required_usd == 300.0
    assert result.model_inputs["cross_margin_stress"]["isolated_margin_required_usd"] == 300.0
    assert result.maintenance_margin_estimate_usd == round(
        result.target_notional_usdt * 0.005,
        8,
    )
    assert result.liquidation_distance_usd == round(
        result.target_notional_usdt * result.liquidation_buffer_bps / 10000.0,
        8,
    )
    assert result.model_inputs["paper_margin_configuration_uses_post_quantization_notional"] is True
    assert result.model_inputs["paper_target_notional_before_step_quantization_usd"] == 800.0
    assert result.model_inputs["paper_target_notional_after_step_quantization_usd"] == 600.0


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.1, float("nan")])
def test_invalid_paper_probe_fraction_fails_closed(fraction: float) -> None:
    result = allocate_paper_candidate(_row(paper_risk_budget_fraction=fraction))

    assert result.decision == "BLOCK_BAD_MARKET_STATE"
    assert result.target_notional_usdt == 0.0
    assert (
        "PAPER_RISK_BUDGET_FRACTION_OUTSIDE_OPEN_CLOSED_UNIT_INTERVAL"
        in result.model_inputs["paper_allocator_input_rejection_reasons"]
    )


def test_paper_allocation_identity_is_bound_to_bracket_generation_and_account() -> None:
    common_lineage = {
        "prediction_id": "pred",
        "maintenance_bracket_account_binding_id": "account-binding-a",
        "maintenance_bracket_environment_id": "binance-usdm-mainnet",
        "maintenance_bracket_id": 1,
        "maintenance_bracket_available_at": "2026-07-17T12:00:00Z",
    }
    first = allocate_paper_candidate(
        _row(
            maintenance_margin_rate=0.004,
            lineage_ids={
                **common_lineage,
                "maintenance_bracket_evidence_id": "bracket-generation-a",
            },
        )
    )
    changed_generation = allocate_paper_candidate(
        _row(
            maintenance_margin_rate=0.004,
            lineage_ids={
                **common_lineage,
                "maintenance_bracket_evidence_id": "bracket-generation-b",
            },
        )
    )
    changed_account = allocate_paper_candidate(
        _row(
            maintenance_margin_rate=0.004,
            lineage_ids={
                **common_lineage,
                "maintenance_bracket_evidence_id": "bracket-generation-a",
                "maintenance_bracket_account_binding_id": "account-binding-b",
            },
        )
    )
    changed_rate = allocate_paper_candidate(
        _row(
            maintenance_margin_rate=0.0065,
            lineage_ids={
                **common_lineage,
                "maintenance_bracket_evidence_id": "bracket-generation-a",
            },
        )
    )

    assert (
        len(
            {
                first.allocation_id,
                changed_generation.allocation_id,
                changed_account.allocation_id,
                changed_rate.allocation_id,
            }
        )
        == 4
    )


def test_paper_exchange_max_qty_caps_then_step_quantizes_the_final_allocation() -> None:
    result = allocate_paper_candidate(
        _row(
            min_qty=0.5,
            step_size=0.5,
            max_qty=5.75,
            min_notional=25.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.model_inputs["paper_exchange_max_qty_reduction_applied"] is True
    assert result.model_inputs["paper_quantity_before_exchange_max_cap"] > 5.75
    assert result.model_inputs["max_qty"] == 5.75
    assert result.allocation_input_material["allocation_input"]["max_qty"] == 5.75
    assert result.target_quantity == 5.5
    assert result.target_quantity <= 5.75
    assert result.target_quantity % 0.5 == 0.0
    assert (
        result.model_inputs["paper_target_quantity_after_step_quantization"]
        == result.target_quantity
    )
    assert result.target_notional_usdt == round(
        result.target_quantity * result.model_inputs["price"],
        8,
    )
    assert result.target_notional_usdt <= round(
        5.75 * result.model_inputs["price"],
        8,
    )


@pytest.mark.parametrize(
    ("max_qty", "expected_rejection_reason"),
    [
        (0.0, "MAX_QTY_NOT_POSITIVE"),
        (-1.0, "MAX_QTY_NOT_POSITIVE"),
        (float("nan"), "NONFINITE_MAX_QTY"),
        (float("inf"), "NONFINITE_MAX_QTY"),
        (float("-inf"), "NONFINITE_MAX_QTY"),
    ],
)
def test_invalid_or_nonfinite_paper_exchange_max_qty_fails_closed(
    max_qty: float,
    expected_rejection_reason: str,
) -> None:
    result = allocate_paper_candidate(_row(max_qty=max_qty))

    assert result.decision == "BLOCK_BAD_MARKET_STATE"
    assert result.target_quantity == 0.0
    assert result.target_notional_usdt == 0.0
    assert result.allocated_margin_usd == 0.0
    assert (
        expected_rejection_reason in result.model_inputs["paper_allocator_input_rejection_reasons"]
    )


def test_paper_exchange_min_qty_above_max_qty_fails_closed() -> None:
    result = allocate_paper_candidate(_row(min_qty=2.0, step_size=0.1, max_qty=1.5))

    assert result.decision == "BLOCK_BAD_MARKET_STATE"
    assert result.target_quantity == 0.0
    assert result.target_notional_usdt == 0.0
    assert (
        "MIN_QTY_EXCEEDS_MAX_QTY" in result.model_inputs["paper_allocator_input_rejection_reasons"]
    )


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("price", 101.0),
        ("equity", 10_001.0),
        ("available_margin", 4_999.0),
        ("wallet_balance", 10_002.0),
        ("market_state_integrity_score", 94.0),
        ("volatility_bps", 51.0),
        ("liquidity_score", 0.95),
        ("spread_bps", 2.1),
        ("slippage_bps", 2.1),
        ("fee_bps", 4.1),
        ("expected_funding_bps", 0.1),
        ("stop_distance_bps", 125.0),
        ("maintenance_margin_rate", 0.006),
        ("permitted_leverage_values", (1.0, 2.0)),
        ("hedge_budget_pct_of_risk", 0.1),
        ("drawdown_bps", 1.0),
        ("symbol_exposure_usdt", 1.0),
        ("total_exposure_usdt", 1.0),
        ("correlation_exposure_pct", 0.01),
        ("regime_score", 0.95),
        ("min_qty", 0.01),
        ("step_size", 0.01),
        ("max_qty", 7.5),
        ("min_notional", 25.0),
        ("ppo_action_probability", 0.7),
        ("masa_confidence", 0.75),
        (
            "lineage_ids",
            {"prediction_id": "pred", "feature_snapshot_hash": "feature-a"},
        ),
        ("risk_veto", True),
        ("risk_veto_reason", "canonical-risk-veto"),
        ("entry_atr_bps", 75.0),
        ("strategy_selected_mode", "trend"),
        ("market_regime", "calm"),
        ("exit_overshoot_premium_bps", 5.0),
        ("adaptive_hedge_sizing_enabled", True),
    ],
)
def test_paper_identity_binds_each_previously_omitted_allocation_input(
    field: str,
    changed_value: object,
) -> None:
    baseline = allocate_paper_candidate(_row())
    changed = allocate_paper_candidate(_row(**{field: changed_value}))

    if field == "lineage_ids":
        changed_lineage = changed.allocation_input_material["allocation_input"][field]
        assert all(changed_lineage.get(key) == value for key, value in changed_value.items())
        assert PAPER_LIQUIDATION_ATR_EVIDENCE_LINEAGE_KEY in changed_lineage
    else:
        assert changed.allocation_input_material["allocation_input"][field] == changed_value
    assert changed.allocation_input_hash != baseline.allocation_input_hash
    assert changed.allocation_id != baseline.allocation_id


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("max_total_portfolio_risk_pct", 0.59),
        ("max_single_symbol_exposure_pct", 0.07),
        ("max_daily_drawdown_pct", 0.04),
        ("max_loss_per_trade_pct", 0.009),
        ("min_available_margin_buffer_pct", 0.14),
        ("max_correlation_exposure_pct", 0.17),
        ("min_liquidation_buffer_bps", 550.0),
        ("max_effective_leverage", 2.5),
        ("tail_loss_multiplier", 1.6),
        ("emergency_absolute_cap_usdt", 900.0),
    ],
)
def test_paper_identity_binds_each_risk_envelope_input(
    field: str,
    changed_value: float,
) -> None:
    baseline = allocate_paper_candidate(_row(), RiskEnvelope())
    changed = allocate_paper_candidate(
        _row(),
        RiskEnvelope(**{field: changed_value}),
    )

    assert changed.allocation_input_material["risk_envelope"][field] == changed_value
    assert changed.allocation_input_hash != baseline.allocation_input_hash
    assert changed.allocation_id != baseline.allocation_id
