from __future__ import annotations

import pytest

from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    RiskEnvelope,
    allocate_authorized_adaptive_paper_action,
)
from v2.backend.app.services.adaptive_capital_allocator.allocator import (
    ADAPTIVE_POLICY_EXACT_PAPER_ALLOCATION_VERSION,
)
from v2.backend.app.services.adaptive_system import adaptive_hard_validator_v2
from v2.backend.app.services.adaptive_system import adaptive_objective_v2
from v2.backend.app.services.adaptive_system.adaptive_paper_policy_authorization_v2 import (
    authorize_adaptive_paper_policy_action,
)
from v2.backend.tests.unit.services.adaptive_system.test_adaptive_paper_policy_authorization_v2 import (
    _result,
)
from v2.backend.tests.unit.services.adaptive_system.test_adaptive_policy_shadow_v2 import (
    _PUBLIC_HEX,
)


@pytest.fixture(autouse=True)
def _validator_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adaptive_objective_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _PUBLIC_HEX,
    )
    monkeypatch.setattr(
        adaptive_hard_validator_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _PUBLIC_HEX,
    )


def _authorization_and_result():
    result = _result(directional=True)
    authorization = authorize_adaptive_paper_policy_action(
        result,
        authorized_at_ms=4_000_001,
    )
    return authorization, result


def _row(authorization, **changes: object) -> AllocationInput:
    values: dict[str, object] = {
        "symbol": authorization.primary_symbol,
        "timeframe": authorization.primary_timeframe,
        "action": authorization.primary_side,
        "price": float(authorization.exact_entry_price),
        "equity": 10_000.0,
        "available_margin": 5_000.0,
        "wallet_balance": 10_000.0,
        # These former Category-E values are deliberately hostile.  The
        # adaptive action has already consumed calibrated continuous estimates;
        # the physical validator must not reapply these as trading policy.
        "confidence_calibrated": 0.0,
        "expected_move_after_cost_bps": 0.0,
        "market_state_integrity_score": 0.0,
        "volatility_bps": 50.0,
        "liquidity_score": 0.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "fee_bps": 4.0,
        "expected_funding_bps": 0.0,
        "stop_distance_bps": float(
            abs(authorization.exact_entry_price - authorization.exact_stop_price)
            / authorization.exact_entry_price
            * 10_000
        ),
        "maintenance_margin_rate": 0.005,
        "permitted_leverage_values": (1.0, 2.0, 3.0),
        "drawdown_bps": 0.0,
        "symbol_exposure_usdt": 0.0,
        "total_exposure_usdt": 0.0,
        "correlation_exposure_pct": 0.0,
        "regime_score": 0.0,
        "lineage_ids": {
            "prediction_id": "prediction-1",
            "paper_cycle_reservation_snapshot_hash": (
                authorization.operator_catastrophic_envelope_sha256
            ),
        },
    }
    values.update(changes)
    return AllocationInput(**values)  # type: ignore[arg-type]


def test_returns_exact_policy_action_without_reapplying_category_e_vetoes() -> None:
    authorization, policy_result = _authorization_and_result()

    allocation = allocate_authorized_adaptive_paper_action(
        _row(authorization),
        authorization=authorization,
        policy_result=policy_result,
    )

    assert allocation.decision == "ALLOW_WITH_SIZE"
    assert allocation.adaptive_capital_policy_version == (
        ADAPTIVE_POLICY_EXACT_PAPER_ALLOCATION_VERSION
    )
    assert allocation.action == authorization.primary_side
    assert allocation.target_notional_usdt == pytest.approx(
        float(authorization.exact_target_notional_usd),
        abs=1e-8,
    )
    assert allocation.target_quantity == pytest.approx(
        float(authorization.exact_target_quantity),
        abs=1e-12,
    )
    assert allocation.allocated_margin_usd == pytest.approx(
        float(authorization.exact_margin_allocation_usd),
        abs=1e-8,
    )
    assert allocation.effective_leverage == float(authorization.exact_leverage)
    assert allocation.max_loss_if_stop_hit == pytest.approx(
        float(authorization.exact_bounded_loss_usd),
        abs=1e-8,
    )
    assert allocation.model_inputs[
        "adaptive_policy_exact_physical_validation_status"
    ] == "PASS"
    assert allocation.model_inputs["policy_action_resized"] is False
    assert allocation.model_inputs["static_category_e_final_authority"] is False


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"price": 101.0}, "ALLOCATION_ENTRY_PRICE_AUTHORIZATION_MISMATCH"),
        (
            {"lineage_ids": {"paper_cycle_reservation_snapshot_hash": "f" * 64}},
            "CURRENT_RESERVATION_SNAPSHOT_AUTHORIZATION_MISMATCH",
        ),
        ({"available_margin": 1.0}, "AVAILABLE_MARGIN_BUFFER_EXCEEDED"),
        ({"maintenance_margin_rate": None}, "MAINTENANCE_MARGIN_EVIDENCE"),
    ),
)
def test_physical_boundary_failures_block_without_resizing(
    changes: dict[str, object],
    reason: str,
) -> None:
    authorization, policy_result = _authorization_and_result()

    allocation = allocate_authorized_adaptive_paper_action(
        _row(authorization, **changes),
        authorization=authorization,
        policy_result=policy_result,
    )

    assert allocation.decision == "BLOCK_EXECUTION_FEASIBILITY_CONTRACT_MISMATCH"
    assert allocation.target_notional_usdt == 0.0
    assert allocation.model_inputs["policy_action_resized"] is False
    assert any(
        reason in item
        for item in allocation.model_inputs[
            "adaptive_policy_exact_physical_rejection_reasons"
        ]
    )


def test_catastrophic_notional_envelope_blocks_exact_action() -> None:
    authorization, policy_result = _authorization_and_result()
    envelope = RiskEnvelope(emergency_absolute_cap_usdt=1.0)

    allocation = allocate_authorized_adaptive_paper_action(
        _row(authorization),
        authorization=authorization,
        policy_result=policy_result,
        envelope=envelope,
    )

    assert allocation.decision == "BLOCK_EXECUTION_FEASIBILITY_CONTRACT_MISMATCH"
    assert "CATASTROPHIC_NOTIONAL_ENVELOPE_EXCEEDED" in allocation.model_inputs[
        "adaptive_policy_exact_physical_rejection_reasons"
    ]


def test_forged_authorization_fields_fail_independent_replay() -> None:
    authorization, policy_result = _authorization_and_result()
    object.__setattr__(authorization, "exact_target_notional_usd", authorization.exact_target_notional_usd / 2)
    object.__setattr__(authorization, "authorization_id", authorization.expected_authorization_id)
    try:
        allocation = allocate_authorized_adaptive_paper_action(
            _row(authorization),
            authorization=authorization,
            policy_result=policy_result,
        )
    finally:
        # The object is local to this test; restore a self-consistent value only
        # to avoid leaving a surprising object for pytest failure rendering.
        object.__setattr__(authorization, "exact_target_notional_usd", authorization.exact_target_notional_usd * 2)
        object.__setattr__(authorization, "authorization_id", authorization.expected_authorization_id)

    assert allocation.decision == "BLOCK_EXECUTION_FEASIBILITY_CONTRACT_MISMATCH"
    assert "ADAPTIVE_POLICY_AUTHORIZATION_REPLAY_MISMATCH" in allocation.model_inputs[
        "adaptive_policy_exact_physical_rejection_reasons"
    ]
