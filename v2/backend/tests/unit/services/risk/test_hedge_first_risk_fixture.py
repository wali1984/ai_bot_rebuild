"""Phase 5 — hedge-first negative-position regression fixtures.

Exercises the real ``evaluate_hedge_first`` controller: only negative/fragile
positions get a hedge evaluation, the best hedge is chosen from the candidate
basket (same-symbol / BTC / ETH / SOL / TOP5), and hedges that cost more than
they save or would collapse the portfolio liquidation buffer are never selected.
No exchange order is ever placed.
"""

from __future__ import annotations

import copy

import pytest

from v2.backend.app.services.risk import hedge_first_controller
from v2.backend.app.services.risk.hedge_first_controller import evaluate_hedge_first

_GEN = "2026-07-11T18:00:00Z"


class _ArithmeticBomb:
    def __float__(self) -> float:
        raise AssertionError("non-authoritative numeric evidence was inspected")


def _authoritative_snapshot(*, worst_buffer: float = 120.0) -> dict:
    scenario = {
        "btc_move": -0.2,
        "symbol_moves": {
            "BTCUSDT": -0.2,
            "ETHUSDT": -0.18,
            "SOLUSDT": -0.22,
            "TOP5_BASKET": -0.19,
        },
        "portfolio_pnl_delta_usd": -25.0,
        "shocked_margin_balance_usd": 125.0,
        "shocked_maintenance_margin_usd": 5.0,
        "shocked_liquidation_buffer_usd": worst_buffer,
        "liquidation_breached": worst_buffer <= 0.0,
    }
    return {
        "schema_version": "cross_margin_liquidation_v2",
        "generated_utc": _GEN,
        "portfolio_snapshot_sha256": "a" * 64,
        "adaptive_stress_authority_complete": True,
        "adaptive_stress_evidence_sha256": "b" * 64,
        "hedge_candidate_maintenance": {
            symbol: {
                "authority_complete": True,
                "source": "AUTHENTICATED_BINANCE_USDM_LEVERAGE_BRACKET",
                "maintenance_margin_rate": 0.005,
                "maintenance_margin_cum": 0.0,
                "evidence_sha256": "c" * 64,
            }
            for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "TOP5_BASKET")
        },
        "portfolio_liquidation_buffer_usd": 150.0,
        "worst_case_liquidation_buffer_usd": worst_buffer,
        "worst_case_liquidation_breached": worst_buffer <= 0.0,
        "worst_case_scenario": "btc_down_20pct",
        "correlated_shock_scenarios": {"btc_down_20pct": scenario},
        "open_position_count": 1,
        "authority_complete": True,
        "portfolio_level_computed": True,
        "per_position_only": False,
        "risk_decision_blocked": False,
        "block_reasons": [],
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


_SNAP = _authoritative_snapshot()


def _negative_position() -> dict:
    return {
        "symbol": "BTCUSDT",
        "side": "long",
        "notional_usd": 100.0,
        "unrealized_pnl_usd": -20.0,
    }


def test_negative_position_triggers_hedge_evaluation() -> None:
    result = evaluate_hedge_first(
        position={
            "symbol": "BTCUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": -20.0,
        },
        snapshot=_SNAP,
        hedge_mode=True,
        generated_utc=_GEN,
    )
    assert result["is_negative"] is True
    assert result["candidates"], "negative position must be evaluated against the hedge basket"
    assert result["hedge_required"] is True
    assert result["risk_decision_blocked"] is False
    assert result["places_real_order"] is False


def test_same_symbol_hedge_selected_when_best() -> None:
    result = evaluate_hedge_first(
        position={
            "symbol": "ETHUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": -20.0,
        },
        snapshot=_SNAP,
        hedge_mode=True,
        generated_utc=_GEN,
    )
    assert result["hedge_required"] is True
    assert result["hedge_symbol"] == "ETHUSDT"
    assert result["hedge_side"] == "short"


def test_btc_beta_hedge_selected_when_best() -> None:
    # One-way mode: same-symbol hedge is ineligible, so a BTC-beta hedge is used.
    result = evaluate_hedge_first(
        position={
            "symbol": "SOLUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": -20.0,
        },
        snapshot=_SNAP,
        hedge_mode=False,
        generated_utc=_GEN,
    )
    same = [c for c in result["candidates"] if c["hedge_symbol"] == "SOLUSDT"]
    assert any(c.get("eligible") is False for c in same)
    assert result["hedge_required"] is True
    assert result["hedge_symbol"] == "BTCUSDT"


def test_hedge_rejected_when_cost_exceeds_loss_reduction() -> None:
    # A profitable position needs no hedge (HOLD), and the engine never selects a
    # candidate whose maintenance drag exceeds its risk-reduction benefit.
    holding = evaluate_hedge_first(
        position={
            "symbol": "BTCUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": 12.0,
        },
        snapshot=_authoritative_snapshot(worst_buffer=145.0),
        hedge_mode=True,
        generated_utc=_GEN,
    )
    assert holding["hedge_required"] is False
    assert holding["recommended_action"] == "HOLD"

    hedged = evaluate_hedge_first(
        position={
            "symbol": "BTCUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": -20.0,
        },
        snapshot=_SNAP,
        hedge_mode=True,
        generated_utc=_GEN,
    )
    selected = [
        c
        for c in hedged["candidates"]
        if c["hedge_symbol"] == hedged["hedge_symbol"] and c.get("eligible")
    ]
    assert selected
    assert all(c["estimated_net_risk_benefit_usd"] > 0 for c in selected)
    assert all(c["maintenance_drag_exceeds_benefit"] is False for c in selected)


def test_hedge_rejected_when_liquidation_buffer_worsens() -> None:
    # The selected hedge must never collapse the portfolio liquidation buffer.
    result = evaluate_hedge_first(
        position={
            "symbol": "BTCUSDT",
            "side": "long",
            "notional_usd": 100.0,
            "unrealized_pnl_usd": -20.0,
        },
        snapshot=_SNAP,
        hedge_mode=True,
        generated_utc=_GEN,
    )
    if result["hedge_required"]:
        assert result["liquidation_buffer_after_usd"] > 0.0
        selected = [
            c
            for c in result["candidates"]
            if c["hedge_symbol"] == result["hedge_symbol"] and c.get("eligible")
        ]
        assert all(c["liquidation_buffer_collapses"] is False for c in selected)
    assert result["places_real_order"] is False


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        (
            {
                "authority_complete": False,
                "portfolio_liquidation_buffer_usd": _ArithmeticBomb(),
            },
            "PORTFOLIO_STRESS_NOT_AUTHORITATIVE",
        ),
        (
            {"portfolio_liquidation_buffer_usd": None},
            "PORTFOLIO_LIQUIDATION_BUFFER_MISSING_OR_NONFINITE",
        ),
        (
            {"worst_case_liquidation_buffer_usd": "malformed"},
            "WORST_CASE_LIQUIDATION_BUFFER_MISSING_OR_NONFINITE",
        ),
        (
            {"correlated_shock_scenarios": None},
            "CORRELATED_STRESS_SCENARIOS_MISSING_OR_MALFORMED",
        ),
    ],
)
def test_invalid_stress_snapshot_blocks_before_marginal_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    mutation: dict,
    expected_reason: str,
) -> None:
    snapshot = copy.deepcopy(_SNAP)
    snapshot.update(mutation)
    calls = 0

    def _forbidden_marginal_call(**_: object) -> dict:
        nonlocal calls
        calls += 1
        raise AssertionError("marginal arithmetic must not run for invalid stress evidence")

    monkeypatch.setattr(
        hedge_first_controller,
        "marginal_liquidation_impact",
        _forbidden_marginal_call,
    )
    result = evaluate_hedge_first(
        position=_negative_position(),
        snapshot=snapshot,
        hedge_mode=True,
        generated_utc=_GEN,
    )

    assert calls == 0
    assert result["authority_complete"] is False
    assert result["risk_decision_blocked"] is True
    assert result["recommended_action"] == "BLOCKED"
    assert result["hedge_required"] is False
    assert result["candidates"] == []
    assert expected_reason in result["block_reasons"]
    assert result["places_real_order"] is False


def test_missing_stress_evidence_blocks_before_marginal_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = copy.deepcopy(_SNAP)
    snapshot.pop("portfolio_liquidation_buffer_usd")
    monkeypatch.setattr(
        hedge_first_controller,
        "marginal_liquidation_impact",
        lambda **_: pytest.fail("marginal evaluation must not run"),
    )
    result = evaluate_hedge_first(
        position=_negative_position(),
        snapshot=snapshot,
        hedge_mode=True,
        generated_utc=_GEN,
    )
    assert result["risk_decision_blocked"] is True
    assert "PORTFOLIO_LIQUIDATION_BUFFER_MISSING_OR_NONFINITE" in result["block_reasons"]


def test_none_stress_snapshot_blocks_without_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hedge_first_controller,
        "marginal_liquidation_impact",
        lambda **_: pytest.fail("marginal evaluation must not run"),
    )
    result = evaluate_hedge_first(
        position=_negative_position(),
        snapshot=None,  # type: ignore[arg-type] - adversarial runtime input
        hedge_mode=True,
        generated_utc=_GEN,
    )
    assert result["risk_decision_blocked"] is True
    assert result["block_reasons"] == ["PORTFOLIO_STRESS_SNAPSHOT_NOT_MAPPING"]


@pytest.mark.parametrize(
    "impact",
    [
        None,
        {},
        {
            "authority_complete": False,
            "risk_decision_blocked": True,
            "block_reasons": ["UPSTREAM_BLOCKED"],
            "liquidation_buffer_before_usd": _ArithmeticBomb(),
            "liquidation_buffer_after_usd": _ArithmeticBomb(),
            "maintenance_margin_added_usd": _ArithmeticBomb(),
            "worsens_liquidation_buffer": None,
            "added_symbol": "BTCUSDT",
            "added_side": "short",
        },
        {
            "authority_complete": True,
            "risk_decision_blocked": False,
            "block_reasons": [],
            "liquidation_buffer_before_usd": 150.0,
            "liquidation_buffer_after_usd": "malformed",
            "maintenance_margin_added_usd": None,
            "worsens_liquidation_buffer": True,
            "added_symbol": "BTCUSDT",
            "added_side": "short",
        },
    ],
)
def test_missing_or_malformed_marginal_evidence_blocks_without_arithmetic(
    monkeypatch: pytest.MonkeyPatch,
    impact: object,
) -> None:
    calls = 0

    def _marginal(**_: object) -> object:
        nonlocal calls
        calls += 1
        return impact

    monkeypatch.setattr(hedge_first_controller, "marginal_liquidation_impact", _marginal)
    result = evaluate_hedge_first(
        position=_negative_position(),
        snapshot=copy.deepcopy(_SNAP),
        hedge_mode=True,
        generated_utc=_GEN,
    )

    assert calls == 1
    assert result["authority_complete"] is False
    assert result["risk_decision_blocked"] is True
    assert result["recommended_action"] == "BLOCKED"
    assert result["hedge_required"] is False
    assert result["candidates"] == []
    assert result["block_reasons"]
    assert result["places_real_order"] is False
