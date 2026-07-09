"""Allocator alt-data consumption invariants: block, shrink, hedge — never grow."""

from __future__ import annotations

from v2.backend.app.services.allocator import build_allocator_simulation

from .test_allocator_simulation import _prediction

ACCOUNT = {
    "signed_account_read_ok": True,
    "available_margin_usd": 1_000.0,
    "wallet_balance": 1_000.0,
}
FILTERS = {"min_qty": "0.0001", "step_size": "0.0001", "min_notional": "5"}


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": "cand-altdata",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "expected_net_pnl_usd": 10.0,
        "pre_trade_loss_probability": 0.20,
    }
    row.update(overrides)
    return row


def _packet(**row_overrides: object) -> dict[str, object]:
    return build_allocator_simulation(
        _row(**row_overrides),
        prediction=_prediction(),
        account_state=ACCOUNT,
        symbol_filters=FILTERS,
        generated_utc="2026-07-09T00:00:00Z",
    )


def test_high_altdata_block_score_rejects() -> None:
    packet = _packet(altdata_trade_block_score=0.9)
    assert packet["allocator_decision"] == "REJECT"
    assert "ALLOCATOR_ALTDATA_TRADE_BLOCK_SCORE_HIGH" in packet["block_reasons"]


def test_reduce_score_shrinks_notional_never_grows() -> None:
    baseline = _packet()
    reduced = _packet(altdata_reduce_size_score=0.6)
    assert baseline["allocator_decision"] == "PASS"
    assert reduced["allocator_decision"] == "PASS"
    assert reduced["gross_notional_usd"] < baseline["gross_notional_usd"]
    assert reduced["altdata_size_factor"] < 1.0
    assert "ALTDATA_REDUCE_SIZE_SCORE_ELEVATED" in reduced["altdata_size_reasons"]
    assert "altdata_reduce_size_score" in reduced["provider_features_used"]


def test_sweep_risk_halves_size_conservatively() -> None:
    baseline = _packet()
    swept = _packet(altdata_liquidation_sweep_risk_score=0.8)
    assert swept["gross_notional_usd"] <= baseline["gross_notional_usd"] * 0.55
    assert "ALTDATA_LIQUIDATION_SWEEP_RISK_CONSERVATIVE_SIZING" in swept["altdata_size_reasons"]


def test_hedge_score_sets_hedge_required() -> None:
    packet = _packet(altdata_hedge_required_score=0.7)
    assert packet["altdata_hedge_required"] is True
    assert packet["hedge_required"] is True


def test_missing_altdata_recorded_not_blocking() -> None:
    packet = _packet()
    assert packet["allocator_decision"] == "PASS"
    assert "altdata_trade_block_score" in packet["provider_features_missing"]
    assert packet["altdata_size_factor"] == 1.0
