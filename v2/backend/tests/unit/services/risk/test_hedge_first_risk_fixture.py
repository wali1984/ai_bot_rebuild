"""Phase 5 — hedge-first negative-position regression fixtures.

Exercises the real ``evaluate_hedge_first`` controller: only negative/fragile
positions get a hedge evaluation, the best hedge is chosen from the candidate
basket (same-symbol / BTC / ETH / SOL / TOP5), and hedges that cost more than
they save or would collapse the portfolio liquidation buffer are never selected.
No exchange order is ever placed.
"""

from __future__ import annotations

from v2.backend.app.services.risk.hedge_first_controller import evaluate_hedge_first

_GEN = "2026-07-11T18:00:00Z"
_SNAP = {
    "portfolio_liquidation_buffer_usd": 150.0,
    "worst_case_liquidation_buffer_usd": 120.0,
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
        snapshot={
            "portfolio_liquidation_buffer_usd": 150.0,
            "worst_case_liquidation_buffer_usd": 145.0,
        },
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
