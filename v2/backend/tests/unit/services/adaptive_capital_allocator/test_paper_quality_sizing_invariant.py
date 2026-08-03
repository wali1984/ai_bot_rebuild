from __future__ import annotations

from dataclasses import asdict

import pytest

from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    RiskEnvelope,
    allocate_live_candidate,
    allocate_paper_candidate,
)


def _row(**overrides: object) -> AllocationInput:
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "action": "long",
        "price": 100.0,
        "equity": 10_000.0,
        "available_margin": 5_000.0,
        "wallet_balance": 10_000.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 80.0,
        "market_state_integrity_score": 95.0,
        "volatility_bps": 50.0,
        "liquidity_score": 1.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 1.0,
        "stop_distance_bps": 100.0,
        "maintenance_margin_rate": 0.005,
        "drawdown_bps": 0.0,
        "symbol_exposure_usdt": 0.0,
        "total_exposure_usdt": 0.0,
        "correlation_exposure_pct": 0.0,
        "regime_score": 1.0,
        "lineage_ids": {"prediction_id": "prediction-quality-invariant"},
    }
    values.update(overrides)
    return AllocationInput(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("weight", [1e-6, 0.25, 1.0])
def test_positive_open_closed_unit_quality_weight_is_admitted(weight: float) -> None:
    result = allocate_paper_candidate(_row(paper_quality_sizing_weight=weight))

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.target_notional_usdt > 0.0
    assert result.model_inputs["paper_quality_sizing_weight"] == weight


@pytest.mark.parametrize(
    "weight",
    [None, float("nan"), float("inf"), float("-inf"), -1e-9, 0.0, 1.000000001],
)
def test_quality_weight_outside_open_closed_unit_interval_fails_closed(
    weight: float | None,
) -> None:
    result = allocate_paper_candidate(_row(paper_quality_sizing_weight=weight))

    assert result.decision == "BLOCK_BAD_MARKET_STATE"
    assert result.target_notional_usdt == 0.0
    assert result.risk_budget_usd == 0.0
    assert (
        "PAPER_QUALITY_SIZING_WEIGHT_OUTSIDE_OPEN_CLOSED_UNIT_INTERVAL"
        in result.model_inputs["paper_allocator_input_rejection_reasons"]
    )


def test_quality_weight_monotonically_contracts_budget_and_gross_ceiling() -> None:
    full = allocate_paper_candidate(_row(paper_quality_sizing_weight=1.0))
    half = allocate_paper_candidate(_row(paper_quality_sizing_weight=0.5))
    quarter = allocate_paper_candidate(_row(paper_quality_sizing_weight=0.25))

    assert quarter.target_notional_usdt < half.target_notional_usdt < full.target_notional_usdt
    assert quarter.risk_budget_usd < half.risk_budget_usd < full.risk_budget_usd
    assert half.target_notional_usdt == pytest.approx(full.target_notional_usdt * 0.5)
    assert quarter.target_notional_usdt == pytest.approx(full.target_notional_usdt * 0.25)
    assert half.risk_budget_usd == pytest.approx(full.risk_budget_usd * 0.5)
    assert quarter.risk_budget_usd == pytest.approx(full.risk_budget_usd * 0.25)
    assert half.model_inputs[
        "gross_notional_ceiling_after_paper_quality_weight_usd"
    ] == pytest.approx(
        half.model_inputs["gross_notional_ceiling_after_paper_fraction_usd"] * 0.5
    )
    assert quarter.model_inputs[
        "risk_budget_after_paper_quality_weight_usd"
    ] == pytest.approx(
        quarter.model_inputs["risk_budget_after_paper_fraction_usd"] * 0.25
    )


@pytest.mark.parametrize(
    ("confidence", "edge_bps", "quality_weight"),
    [
        (0.001, 0.001, 1.0),
        (0.01, 0.1, 0.1),
        (0.2, 2.0, 0.5),
        (0.8, 80.0, 1.0),
    ],
)
def test_paper_reported_max_loss_never_exceeds_quality_weighted_budget(
    confidence: float,
    edge_bps: float,
    quality_weight: float,
) -> None:
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=confidence,
            expected_move_after_cost_bps=edge_bps,
            paper_quality_sizing_weight=quality_weight,
            paper_risk_budget_fraction=1.0,
        ),
        RiskEnvelope(
            max_single_symbol_exposure_pct=1.0,
            max_loss_per_trade_pct=0.001,
        ),
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.max_loss_if_stop_hit is not None
    assert result.max_loss_if_stop_hit <= result.risk_budget_usd
    assert result.max_loss_usd == result.max_loss_if_stop_hit


def test_risk_limited_paper_size_uses_every_reported_loss_component() -> None:
    result = allocate_paper_candidate(
        _row(
            fee_bps=11.0,
            slippage_bps=7.0,
            expected_funding_bps=-13.0,
            permitted_leverage_values=(1.0,),
        ),
        RiskEnvelope(
            max_single_symbol_exposure_pct=1.0,
            max_loss_per_trade_pct=0.001,
        ),
    )

    assert result.decision == "ALLOW_WITH_SIZE"
    assert result.model_inputs["paper_modeled_loss_bps"] == 131.0
    assert result.model_inputs["paper_modeled_loss_formula"] == (
        "stop_distance_bps + max(fee_bps, 0) + max(slippage_bps, 0) "
        "+ abs(expected_funding_bps)"
    )
    assert result.max_loss_if_stop_hit == result.risk_budget_usd
    assert result.max_loss_if_stop_hit == pytest.approx(
        (result.stop_loss_usd or 0.0)
        + result.expected_fees_usd
        + result.expected_slippage_usd
        + result.expected_funding_usd,
        abs=2e-8,
    )


def test_ordinary_fraction_one_never_rounds_tiny_target_up_to_venue_minimum() -> None:
    # Final paper directive 2026-07-31: the policy-factor floor keeps a tiny
    # confidence/edge candidate above zero size, so a venue minimum of 5 USD
    # is now genuinely affordable for this fixture.  The invariant under test
    # is unchanged: a target BELOW the venue minimum is never silently
    # rounded up — it hard-blocks as venue-infeasible.
    result = allocate_paper_candidate(
        _row(
            confidence_calibrated=0.001,
            expected_move_after_cost_bps=0.001,
            paper_quality_sizing_weight=1.0,
            paper_risk_budget_fraction=1.0,
            min_notional=1_000.0,
        )
    )

    assert result.decision == "BLOCK_RISK_BUDGET_BELOW_EXECUTABLE_MINIMUM"
    assert result.target_notional_usdt == 0.0
    assert result.max_loss_if_stop_hit == 0.0
    assert result.final_size_reason == "paper_risk_budget_below_exact_executable_minimum"
    assert result.model_inputs["target_notional_before_exchange_minimum_usd"] < 1_000.0
    assert result.model_inputs["exchange_min_order_notional_usd"] == 1_000.0
    assert result.model_inputs["paper_risk_budget_fraction"] == 1.0


def test_paper_quality_weight_is_materialized_and_hash_bound() -> None:
    lower = allocate_paper_candidate(_row(paper_quality_sizing_weight=0.49))
    higher = allocate_paper_candidate(_row(paper_quality_sizing_weight=0.51))

    assert lower.allocation_input_material["allocation_input"][
        "paper_quality_sizing_weight"
    ] == 0.49
    assert higher.allocation_input_material["allocation_input"][
        "paper_quality_sizing_weight"
    ] == 0.51
    assert lower.allocation_input_hash != higher.allocation_input_hash
    assert lower.allocation_id != higher.allocation_id


def test_paper_quality_weight_does_not_change_live_allocation_output() -> None:
    lower = allocate_live_candidate(_row(paper_quality_sizing_weight=0.01))
    full = allocate_live_candidate(_row(paper_quality_sizing_weight=1.0))

    assert asdict(lower) == asdict(full)
    assert "paper_quality_sizing_weight" not in lower.allocation_input_material[
        "allocation_input"
    ]
