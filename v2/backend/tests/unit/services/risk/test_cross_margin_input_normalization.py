"""Adversarial input-normalization tests for cross-margin snapshots."""

from __future__ import annotations

import pytest

from v2.backend.app.cli import v2_portfolio_cascade_guard_loop as cascade_guard
from v2.backend.app.services.risk.cross_margin_liquidation import (
    build_portfolio_liquidation_snapshot,
)

NOW = "2026-07-21T15:00:00Z"


def _account(**overrides):
    account = {
        "totalWalletBalance": 1_000.0,
        "totalCrossWalletBalance": 900.0,
        "totalUnrealizedProfit": 10.0,
        "totalInitialMargin": 100.0,
        "totalMaintMargin": 20.0,
        "totalMarginBalance": 1_010.0,
        "availableBalance": 910.0,
    }
    account.update(overrides)
    return account


def _position(**overrides):
    position = {
        "symbol": "BTCUSDT",
        "positionAmt": 2.0,
        "markPrice": 100.0,
        "maintMarginRatio": 0.01,
        "unRealizedProfit": 7.0,
    }
    position.update(overrides)
    return position


def test_every_primary_account_zero_beats_aliases_and_derived_fallbacks():
    account = {
        "totalWalletBalance": 0,
        "wallet_balance": 101,
        "totalCrossWalletBalance": 0,
        "cross_wallet_balance": 102,
        "totalUnrealizedProfit": 0,
        "unrealized_pnl": 103,
        "totalInitialMargin": 0,
        "initial_margin": 104,
        "totalMaintMargin": 0,
        "maintenance_margin": 105,
        "totalMarginBalance": 0,
        "margin_balance": 106,
        "availableBalance": 0,
        "available_balance": 107,
    }

    snapshot = build_portfolio_liquidation_snapshot(
        account=account,
        positions=[_position()],
        generated_utc=NOW,
    )

    output_fields = (
        "wallet_balance_usd",
        "cross_wallet_balance_usd",
        "unrealized_pnl_usd",
        "initial_margin_usd",
        "maintenance_margin_usd",
        "portfolio_margin_balance_usd",
        "available_balance_usd",
    )
    assert {field: snapshot[field] for field in output_fields} == {
        field: 0.0 for field in output_fields
    }
    diagnostics = snapshot["account_input_normalization"]
    assert all(item["status"] == "VALID" for item in diagnostics.values())
    assert all(item["fallback_used"] is False for item in diagnostics.values())
    assert all(item["explicit_zero"] is True for item in diagnostics.values())
    assert diagnostics["wallet_balance_usd"]["source_field"] == "totalWalletBalance"
    assert diagnostics["maintenance_margin_usd"]["source_field"] == "totalMaintMargin"


def test_every_snake_case_account_alias_preserves_explicit_zero():
    account = {
        "wallet_balance": "0",
        "cross_wallet_balance": "0",
        "unrealized_pnl": "0",
        "initial_margin": "0",
        "maintenance_margin": "0",
        "margin_balance": "0",
        "available_balance": "0",
    }

    snapshot = build_portfolio_liquidation_snapshot(
        account=account,
        positions=[_position()],
        generated_utc=NOW,
    )

    diagnostics = snapshot["account_input_normalization"]
    assert snapshot["wallet_balance_usd"] == 0.0
    assert snapshot["cross_wallet_balance_usd"] == 0.0
    assert snapshot["unrealized_pnl_usd"] == 0.0
    assert snapshot["initial_margin_usd"] == 0.0
    assert snapshot["maintenance_margin_usd"] == 0.0
    assert snapshot["portfolio_margin_balance_usd"] == 0.0
    assert snapshot["available_balance_usd"] == 0.0
    assert all(item["status"] == "VALID" for item in diagnostics.values())
    assert all(item["source_field"].islower() for item in diagnostics.values())
    assert all(item["explicit_zero"] is True for item in diagnostics.values())


def test_invalid_primary_account_alias_is_not_silently_replaced_by_secondary_alias():
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(totalWalletBalance="not-a-number", wallet_balance=999.0),
        positions=[],
        generated_utc=NOW,
    )

    assert snapshot["wallet_balance_usd"] is None
    assert snapshot["calculated_account_values"]["wallet_balance_usd"] == 0.0
    diagnostic = snapshot["account_input_normalization"]["wallet_balance_usd"]
    assert diagnostic == {
        "status": "INVALID",
        "source_field": "totalWalletBalance",
        "fallback_used": True,
        "fallback_source": "ZERO_DEFAULT",
        "explicit_zero": False,
    }


@pytest.mark.parametrize(
    (
        "position_overrides",
        "expected_amount",
        "expected_side",
        "expected_resolution",
        "expected_source",
        "expected_sign_conflict",
    ),
    [
        (
            {"positionAmt": -2.0, "positionSide": "BOTH"},
            -2.0,
            "short",
            "SIGNED_QUANTITY",
            None,
            False,
        ),
        (
            {"positionAmt": -2.0, "positionSide": "SHORT"},
            -2.0,
            "short",
            "EXCHANGE_POSITION_SIDE",
            "positionSide",
            False,
        ),
        (
            {"positionAmt": 2.0, "positionSide": "SHORT"},
            -2.0,
            "short",
            "EXCHANGE_POSITION_SIDE",
            "positionSide",
            True,
        ),
        (
            {"positionAmt": -2.0, "positionSide": "LONG"},
            2.0,
            "long",
            "EXCHANGE_POSITION_SIDE",
            "positionSide",
            True,
        ),
        (
            {"positionAmt": None, "position_amt": 2.0, "direction": "SELL"},
            -2.0,
            "short",
            "GENERIC_EXPLICIT_DIRECTION",
            "direction",
            True,
        ),
        (
            {"positionAmt": None, "qty": 2.0, "side": "BUY"},
            2.0,
            "long",
            "GENERIC_EXPLICIT_DIRECTION",
            "side",
            False,
        ),
    ],
)
def test_signed_exchange_and_explicit_direction_cases(
    position_overrides,
    expected_amount,
    expected_side,
    expected_resolution,
    expected_source,
    expected_sign_conflict,
):
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=[_position(**position_overrides)],
        generated_utc=NOW,
    )

    row = snapshot["calculated_positions"][0]
    diagnostics = row["input_normalization"]
    assert row["position_amt"] == expected_amount
    assert row["side"] == expected_side
    assert diagnostics["side_resolution"] == expected_resolution
    assert diagnostics["side_source_field"] == expected_source
    assert diagnostics["quantity_sign_side_conflict"] is expected_sign_conflict
    assert diagnostics["quantity_sign_adjusted"] is expected_sign_conflict
    if position_overrides.get("positionSide") == "BOTH":
        assert diagnostics["nondirectional_side_fields"] == ["positionSide"]


def test_canonical_positive_short_magnitude_controls_correlated_shock_direction():
    position = _position(
        positionAmt=None,
        net_quantity=2.0,
        side="short",
    )

    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(totalUnrealizedProfit=0.0),
        positions=[position],
        generated_utc=NOW,
    )

    row = snapshot["calculated_positions"][0]
    assert row["position_amt"] == -2.0
    assert row["side"] == "short"
    assert row["input_normalization"]["quantity_source_field"] == "net_quantity"
    assert row["input_normalization"]["position_schema"] == "CANONICAL_POSITION"
    assert row["input_normalization"]["side_resolution"] == "CANONICAL_POSITION_SIDE"
    assert row["input_normalization"]["quantity_sign_side_conflict"] is True
    assert snapshot["position_direction_evidence_complete"] is True
    assert snapshot["portfolio_level_computed"] is True
    shocks = snapshot["correlated_shock_scenarios"]
    assert shocks["btc_down_10pct"]["portfolio_pnl_delta_usd"] == 20.0
    assert shocks["btc_up_10pct"]["portfolio_pnl_delta_usd"] == -20.0
    assert snapshot["worst_case_scenario"] == "btc_up_10pct"


def test_conflicting_explicit_direction_evidence_is_visible_and_precedence_is_stable():
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=[
            _position(
                positionAmt=None,
                net_quantity=3.0,
                side="short",
                direction="sell",
                positionSide="LONG",
            )
        ],
        generated_utc=NOW,
    )

    row = snapshot["calculated_positions"][0]
    diagnostics = row["input_normalization"]
    assert row["position_amt"] == -3.0
    assert row["side"] == "short"
    assert diagnostics["side_source_field"] == "side"
    assert diagnostics["direction_evidence_conflict"] is True
    assert diagnostics["directional_evidence"] == [
        {"field": "side", "side": "short"},
        {"field": "direction", "side": "short"},
        {"field": "positionSide", "side": "long"},
    ]
    assert snapshot["position_direction_evidence_complete"] is False
    assert snapshot["portfolio_risk_computation_blocked"] is True
    assert snapshot["portfolio_level_computed"] is False
    assert snapshot["worst_case_scenario"] is None
    assert snapshot["worst_case_liquidation_buffer_usd"] is None
    assert snapshot["worst_case_liquidation_breached"] is None
    assert snapshot["worst_case_liquidation_result_authoritative"] is False


def test_exchange_order_side_alias_cannot_override_signed_position_direction():
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=[_position(positionAmt=-2.0, side="BUY", direction="buy")],
        generated_utc=NOW,
    )

    row = snapshot["positions"][0]
    diagnostics = row["input_normalization"]
    assert row["position_amt"] == -2.0
    assert row["side"] == "short"
    assert diagnostics["position_schema"] == "EXCHANGE_SIGNED_POSITION"
    assert diagnostics["side_resolution"] == "SIGNED_QUANTITY"
    assert diagnostics["side_source_field"] is None
    assert diagnostics["controlling_directional_evidence"] == []
    assert diagnostics["ignored_directional_evidence"] == [
        {"field": "side", "side": "long"},
        {"field": "direction", "side": "long"},
    ]
    assert snapshot["position_direction_evidence_complete"] is True


def test_exchange_position_side_conflict_blocks_authoritative_portfolio_result():
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(totalMarginBalance=50.0, totalWalletBalance=50.0),
        positions=[
            _position(
                positionAmt=100.0,
                positionSide="SHORT",
                side="BUY",
            )
        ],
        generated_utc=NOW,
    )

    row = snapshot["calculated_positions"][0]
    diagnostics = row["input_normalization"]
    assert row["position_amt"] == -100.0
    assert row["side"] == "short"
    assert diagnostics["side_source_field"] == "positionSide"
    assert diagnostics["direction_evidence_conflict"] is True
    assert snapshot["position_direction_evidence_complete"] is False
    assert snapshot["portfolio_level_computed"] is False
    assert snapshot["worst_case_liquidation_breached"] is None
    assert snapshot["calculated_worst_case_liquidation_breached"] is True
    assert (
        cascade_guard.decide_directives(
            [{"symbol": "BTCUSDT", "unrealized_pnl_bps": -1.0}],
            {},
            snapshot,
        )
        == []
    )


def test_unrecognized_controlling_side_blocks_authority_but_keeps_calculation_diagnostic():
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=[
            _position(
                positionAmt=None,
                net_quantity=2.0,
                side="sideways",
            )
        ],
        generated_utc=NOW,
    )

    assert snapshot["position_direction_evidence_complete"] is False
    assert snapshot["portfolio_risk_result_authoritative"] is False
    assert snapshot["portfolio_level_computed"] is False
    assert snapshot["positions"] is None
    assert snapshot["correlated_shock_scenarios"] is None
    assert snapshot["portfolio_liquidation_buffer_usd"] is None
    assert snapshot["calculated_positions"][0]["side"] == "long"
    assert snapshot["calculated_correlated_shock_scenarios"]
    assert (
        "POSITION_DIRECTION_EVIDENCE_UNRECOGNIZED"
        in snapshot["portfolio_risk_block_reasons"]
    )
    assert snapshot["unrecognized_position_directions"] == [
        {
            "symbol": "BTCUSDT",
            "quantity_source_field": "net_quantity",
            "position_schema": "CANONICAL_POSITION",
            "unrecognized_controlling_side_fields": ["side"],
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_status"),
    [
        ("totalMarginBalance", "bad", "INVALID"),
        ("totalMarginBalance", None, "MISSING"),
        ("totalMarginBalance", -1.0, "VALID"),
        ("totalMaintMargin", "bad", "INVALID"),
        ("totalMaintMargin", None, "MISSING"),
        ("totalMaintMargin", -1.0, "VALID"),
    ],
)
def test_invalid_or_missing_dependency_critical_account_input_blocks_authority(
    field,
    value,
    expected_status,
):
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(**{field: value}),
        positions=[_position()],
        generated_utc=NOW,
    )

    output_field = (
        "portfolio_margin_balance_usd"
        if field == "totalMarginBalance"
        else "maintenance_margin_usd"
    )
    assert snapshot[output_field] is None
    assert snapshot["account_input_normalization"][output_field]["status"] == expected_status
    assert snapshot["account_dependency_evidence_complete"] is False
    assert snapshot["portfolio_risk_result_authoritative"] is False
    assert snapshot["worst_case_liquidation_breached"] is None
    assert snapshot["calculated_account_values"][output_field] is not None
    assert (
        "ACCOUNT_DEPENDENCY_EVIDENCE_INCOMPLETE"
        in snapshot["portfolio_risk_block_reasons"]
    )


def test_position_maintenance_fallback_blocks_authority():
    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=[_position(maintMarginRatio=None)],
        generated_utc=NOW,
    )

    assert snapshot["maintenance_margin_evidence_complete"] is False
    assert snapshot["maintenance_margin_fallback_symbols"] == ["BTCUSDT"]
    assert snapshot["portfolio_risk_result_authoritative"] is False
    assert snapshot["positions"] is None
    assert snapshot["calculated_positions"][0]["maintenance_margin_rate_source"] == (
        "LEGACY_CONSERVATIVE_FALLBACK"
    )
    assert (
        "MAINTENANCE_MARGIN_EVIDENCE_INCOMPLETE"
        in snapshot["portfolio_risk_block_reasons"]
    )


def test_invalid_or_zero_quantity_and_mark_are_excluded():
    positions = [
        _position(symbol="ZEROQTY", positionAmt=0.0, net_quantity=5.0),
        _position(symbol="BADQTY", positionAmt="bad", net_quantity=5.0),
        _position(symbol="ZEROMARK", markPrice=0.0),
        _position(symbol="NEGATIVEMARK", markPrice=-1.0),
        _position(symbol="BADMARK", markPrice="bad"),
        _position(symbol="VALID"),
    ]

    snapshot = build_portfolio_liquidation_snapshot(
        account=_account(),
        positions=positions,
        generated_utc=NOW,
    )

    assert snapshot["open_position_count"] == 1
    assert snapshot["expected_position_count"] == 6
    assert snapshot["computed_position_count"] == 1
    assert snapshot["dropped_position_count"] == 5
    assert snapshot["position_count_evidence_complete"] is False
    assert snapshot["portfolio_risk_result_authoritative"] is False
    assert "POSITION_ROWS_DROPPED" in snapshot["portfolio_risk_block_reasons"]
    assert "POSITION_COUNT_MISMATCH" in snapshot["portfolio_risk_block_reasons"]
    assert snapshot["positions"] is None
    assert [row["symbol"] for row in snapshot["calculated_positions"]] == ["VALID"]
