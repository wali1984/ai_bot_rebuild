"""Adaptive hedging: trigger/unwind pure functions + lifecycle pair routing.

Operator requirement (2026-07-16): hedge adverse moves instead of eating full
ATR stop-outs; all triggers/sizes/unwinds adaptive (fractions of the
position's own ATR stop and excursions), never static bps thresholds.
Paper-only; live gate stays BLOCKED.
"""
from __future__ import annotations

from v2.backend.app.services.paper_trade_management.exits import (
    PaperExitConfig,
    effective_atr_stop_bps,
    evaluate_exit,
)
from v2.backend.app.services.paper_trade_management.hedging import (
    evaluate_adaptive_hedge_trigger,
    evaluate_adaptive_hedge_unwind,
)
from v2.backend.app.services.paper_trade_management.lifecycle import (
    PaperLifecycleConfig,
    reconcile_paper_lifecycle,
)
from v2.backend.app.services.paper_trade_management.position_state import position_from_fill


def _fill(
    *,
    fill_id: str,
    symbol: str = "BTCUSDT",
    side: str = "long",
    qty: float = 1.0,
    price: float = 100.0,
    timeframe: str = "1m",
    **extra,
) -> dict:
    row = {
        "fill_id": fill_id,
        "ledger_row_id": fill_id,
        "intent_id": fill_id,
        "symbol": symbol,
        "side": side,
        "quantity": qty,
        "notional": qty * price,
        "notional_usdt": qty * price,
        "entry_price": price,
        "fill_price": price,
        "fill_price_utc": "2026-07-16T10:00:00Z",
        "generated_utc": "2026-07-16T10:00:00Z",
        "signal_id": f"sig_{fill_id}",
        "prediction_id": f"pred_{fill_id}",
        "risk_decision_id": f"risk_{fill_id}",
        "orchestrator_decision_id": f"orch_{fill_id}",
        "decision_id": f"orch_{fill_id}",
        "market_state_id": f"ms_{fill_id}",
        "feature_snapshot_id": f"feat_{fill_id}",
        "mtf_snapshot_id": f"mtf_{fill_id}",
        "feature_cutoff": "2026-07-16T09:59:00Z",
        "decision_time": "2026-07-16T10:00:00Z",
        "available_at": "2026-07-16T09:59:30Z",
        "selected_action": side,
        "model_version": "unit_model_v1",
        "checkpoint_id": f"ckpt_{fill_id}",
        "source_hashes": {"feature_vector_hash": f"hash_{fill_id}"},
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "timeframe": timeframe,
        "paper_fill_allowed": True,
    }
    row.update(extra)
    return row


def _hedge_fill(parent_fill: dict, *, hedge_ratio: float = 0.5, price: float = 99.0) -> dict:
    parent_id = f"paper_pos_{parent_fill['symbol']}"
    hedge_id = f"{parent_id}:hedge:2026-07-16T10:05:00Z"
    row = dict(parent_fill)
    qty = float(parent_fill["quantity"]) * hedge_ratio
    row.update(
        {
            "fill_id": hedge_id,
            "ledger_row_id": hedge_id,
            "intent_id": hedge_id,
            "side": "short" if parent_fill["side"] == "long" else "long",
            "quantity": qty,
            "notional": qty * price,
            "notional_usdt": qty * price,
            "entry_price": price,
            "fill_price": price,
            "hedge_intent": True,
            "hedge_parent_id": parent_id,
            "hedge_child_id": hedge_id,
            "hedge_ratio": hedge_ratio,
            "hedge_state": "HEDGE_CHILD",
            "hedge_reason": "ADAPTIVE_ADVERSE_EXCURSION_HEDGE",
            # Hedge entered at price 99 = parent long from 100 was at -100bps.
            "hedge_entry_parent_pnl_bps": -100.0,
        }
    )
    return row


# ── Trigger ────────────────────────────────────────────────────────────────


def _trigger(*, conf: float, pnl_bps: float, atr_stop: float = 50.0, mae_bps: float | None = None, hedge_state: str = "NO_HEDGE"):
    return evaluate_adaptive_hedge_trigger(
        position_payload={
            "symbol": "BTCUSDT",
            "side": "short",
            "confidence_calibrated": conf,
            "hedge_state": hedge_state,
            "mae_bps": mae_bps if mae_bps is not None else abs(min(0.0, pnl_bps)),
        },
        pnl_bps=pnl_bps,
        atr_stop_bps=atr_stop,
        portfolio_drawdown_bps=0.0,
    )


def test_trigger_arms_earlier_for_higher_confidence() -> None:
    # At 70% of stop distance: high confidence hedges, low confidence does not.
    high = _trigger(conf=0.86, pnl_bps=-35.0, atr_stop=50.0)
    low = _trigger(conf=0.55, pnl_bps=-35.0, atr_stop=50.0)
    assert high["trigger"] is True
    assert high["hedge_side"] == "long"
    assert low["trigger"] is False
    assert low["reason"] == "ADVERSE_RATIO_BELOW_ADAPTIVE_ARM_FRACTION"
    assert low["arm_fraction"] > high.get("arm_fraction", 0.0)


def test_trigger_never_below_minimum_arm_fraction() -> None:
    # Even max confidence + max drawdown pressure keeps arm fraction >= 0.35.
    result = evaluate_adaptive_hedge_trigger(
        position_payload={
            "symbol": "BTCUSDT",
            "side": "long",
            "confidence_calibrated": 0.99,
            "hedge_state": "NO_HEDGE",
            "mae_bps": 17.0,
        },
        pnl_bps=-17.0,  # 34% of stop
        atr_stop_bps=50.0,
        portfolio_drawdown_bps=10_000.0,
    )
    assert result["trigger"] is False


def test_trigger_blocked_when_already_hedged_or_unwound() -> None:
    for state in ("HEDGED", "HEDGE_PENDING", "HEDGE_UNWOUND"):
        result = _trigger(conf=0.9, pnl_bps=-45.0, hedge_state=state)
        assert result["trigger"] is False, state


def test_trigger_blocked_when_move_already_recovering() -> None:
    # MAE was 45bps but position recovered to -20bps: no hedge on a recovery.
    result = _trigger(conf=0.9, pnl_bps=-20.0, atr_stop=25.0, mae_bps=45.0)
    assert result["trigger"] is False
    assert result["reason"] == "ADVERSE_MOVE_ALREADY_RECOVERING_FROM_MAE"


def test_trigger_blocked_when_cost_exceeds_protection() -> None:
    # Tiny stop distance: round-trip cost exceeds protected distance.
    result = evaluate_adaptive_hedge_trigger(
        position_payload={
            "symbol": "BTCUSDT",
            "side": "short",
            "confidence_calibrated": 0.9,
            "hedge_state": "NO_HEDGE",
            "mae_bps": 5.0,
        },
        pnl_bps=-5.0,
        atr_stop_bps=6.0,
        fee_bps=10.0,
        slippage_bps=10.0,
    )
    assert result["trigger"] is False
    assert result["reason"] == "HEDGE_COST_EXCEEDS_EXPECTED_PROTECTION"


def test_trigger_requires_adverse_excursion() -> None:
    assert _trigger(conf=0.9, pnl_bps=10.0)["trigger"] is False


# ── Unwind ─────────────────────────────────────────────────────────────────


def _unwind(**overrides):
    kwargs = dict(
        parent_payload={"symbol": "BTCUSDT", "confidence_calibrated": 0.8},
        hedge_payload={"hedge_entry_parent_pnl_bps": -40.0},
        parent_pnl_bps=-45.0,
        hedge_pnl_bps=5.0,
        hedge_best_excursion_bps=20.0,
        parent_atr_stop_bps=50.0,
        hedge_hold_seconds=600.0,
        max_hold_seconds=21600.0,
    )
    kwargs.update(overrides)
    return evaluate_adaptive_hedge_unwind(**kwargs)


def test_unwind_orphan_when_parent_missing() -> None:
    assert _unwind(parent_payload={})["action"] == "ORPHAN_UNWIND"


def test_unwind_on_parent_recovery() -> None:
    result = _unwind(parent_pnl_bps=-5.0, hedge_pnl_bps=25.0)
    assert result["action"] == "UNWIND_HEDGE"
    assert result["reason"] == "PARENT_THESIS_RESUMED_PAST_HEDGE_ENTRY"


def test_unwind_when_adverse_move_exhausted() -> None:
    # Hedge banked 60bps best excursion, retraced to 10bps: move exhausted.
    result = _unwind(hedge_pnl_bps=10.0, hedge_best_excursion_bps=60.0)
    assert result["action"] == "UNWIND_HEDGE"
    assert result["reason"] == "ADVERSE_MOVE_EXHAUSTED_HEDGE_BANKS_PROFIT"


def test_close_both_on_pair_drawdown() -> None:
    # Baseline at hedge entry was -40; pair now at -160 = 120bps additional
    # deterioration >= 1.5 x parent stop (75).
    result = _unwind(parent_pnl_bps=-150.0, hedge_pnl_bps=-10.0)
    assert result["action"] == "CLOSE_BOTH"
    assert result["reason"] == "PAIR_DRAWDOWN_EXCEEDED_ADAPTIVE_LIMIT"


def test_hold_when_pair_drawdown_measured_from_hedge_entry() -> None:
    # Absolute net pair PnL is deeply negative (-100) but unchanged since
    # hedge entry (baseline -100): the hedge is doing its job, HOLD.
    result = _unwind(
        parent_pnl_bps=-100.0,
        hedge_pnl_bps=0.0,
        hedge_payload={"hedge_entry_parent_pnl_bps": -100.0},
        hedge_best_excursion_bps=0.0,
    )
    assert result["action"] == "HOLD"


def test_close_both_on_max_hold() -> None:
    result = _unwind(hedge_hold_seconds=30000.0, max_hold_seconds=21600.0)
    assert result["action"] == "CLOSE_BOTH"


def test_hold_while_move_persists() -> None:
    result = _unwind(hedge_pnl_bps=18.0, hedge_best_excursion_bps=20.0)
    assert result["action"] == "HOLD"


# ── Lifecycle routing ──────────────────────────────────────────────────────


def _hedge_config() -> PaperLifecycleConfig:
    return PaperLifecycleConfig(
        allow_explicit_hedge=True,
        portfolio_equity_usdt=10_000.0,
        exit_config=PaperExitConfig(
            static_stop_loss_enabled=False,
            static_take_profit_enabled=False,
            static_profit_lock_enabled=False,
            static_profit_bank_enabled=False,
            static_max_hold_enabled=False,
        ),
    )


def test_tagged_hedge_fill_opens_pair_instead_of_netting() -> None:
    parent = _fill(fill_id="f1", side="long", price=100.0)
    hedge = _hedge_fill(parent, price=99.0)
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 99.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
    )
    keys = set(result["positions_by_symbol"])
    assert "BTCUSDT" in keys
    assert "BTCUSDT::HEDGE" in keys
    parent_row = result["positions_by_symbol"]["BTCUSDT"]
    hedge_row = result["positions_by_symbol"]["BTCUSDT::HEDGE"]
    assert parent_row["hedge_state"] == "HEDGED"
    assert hedge_row["hedge_state"] == "HEDGE_CHILD"
    assert hedge_row["hedge_parent_id"] == "paper_pos_BTCUSDT"
    assert hedge_row["side"] == "short"
    # No netting close happened.
    assert not [
        row
        for row in result["closed_trades"]
        if row.get("close_reason") == "TIER_3_MODEL_REVERSAL_NETTING"
    ]
    events = {e["event"] for e in result["paper_hedge_netting_status"]["events"]}
    assert "EXPLICIT_HEDGE_OPENED" in events


def test_untagged_opposite_fill_still_nets() -> None:
    parent = _fill(fill_id="f1", side="long", price=100.0)
    reversal = _fill(fill_id="f2", side="short", price=99.0)
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[parent, reversal],
        mark_prices={"BTCUSDT": {"price": 99.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
    )
    assert "BTCUSDT::HEDGE" not in result["positions_by_symbol"]
    assert [
        row
        for row in result["closed_trades"]
        if row.get("close_reason") == "TIER_3_MODEL_REVERSAL_NETTING"
    ]


def test_hedge_fill_nets_when_feature_disabled() -> None:
    parent = _fill(fill_id="f1", side="long", price=100.0)
    hedge = _hedge_fill(parent, price=99.0)
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 99.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=PaperLifecycleConfig(allow_explicit_hedge=False, portfolio_equity_usdt=10_000.0),
    )
    assert "BTCUSDT::HEDGE" not in result["positions_by_symbol"]


def test_orphan_hedge_unwinds_immediately() -> None:
    parent = _fill(fill_id="f1", side="long", price=100.0)
    hedge = _hedge_fill(parent, price=99.0)
    # Parent's fill already closed in a prior cycle: only the hedge replays.
    existing = {
        "closed_trades": [
            {
                "symbol": "BTCUSDT",
                "close_reason": "TIER_2_TRAILING_STOP",
                "source_fill_ids": ["f1"],
                "realized_pnl_usd": 1.0,
                "realized_net_pnl_usd": 1.0,
            }
        ]
    }
    result = reconcile_paper_lifecycle(
        existing_ledger=existing,
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 99.5}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
    )
    assert "BTCUSDT::HEDGE" not in result["positions_by_symbol"]
    unwinds = [
        row
        for row in result["new_close_events"]
        if row.get("close_reason") == "TIER_2_HEDGE_UNWIND_EXHAUSTED"
    ]
    assert unwinds, result["paper_adaptive_hedge_status"]


def test_hedge_close_accounting_matches_ledger_totals() -> None:
    # G08 invariant: sum of closed-trade realized pnl == ledger realized total
    # with hedge closes present.
    parent = _fill(fill_id="f1", side="long", price=100.0)
    hedge = _hedge_fill(parent, price=99.0)
    existing = {
        "closed_trades": [
            {
                "symbol": "BTCUSDT",
                "close_reason": "TIER_2_TRAILING_STOP",
                "source_fill_ids": ["f1"],
                "realized_pnl_usd": 1.0,
                "realized_net_pnl_usd": 1.0,
            }
        ]
    }
    result = reconcile_paper_lifecycle(
        existing_ledger=existing,
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 99.5}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
    )
    trade_sum = sum(
        float(
            row.get("realized_net_pnl_usd")
            if row.get("realized_net_pnl_usd") is not None
            else row.get("realized_pnl_usd") or 0.0
        )
        for row in result["closed_trades"]
    )
    assert abs(trade_sum - float(result["realized_net_pnl_usd"])) < 1e-9


def test_hedge_status_block_present() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="f1")],
        mark_prices={"BTCUSDT": {"price": 100.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
    )
    status = result["paper_adaptive_hedge_status"]
    assert status["enabled"] is True
    assert status["paper_only"] is True
    assert status["places_real_order"] is False


# ── exits/allocator stop consistency ───────────────────────────────────────


def test_effective_stop_helper_matches_evaluate_exit() -> None:
    cfg = PaperExitConfig(atr_stop_overshoot_premium_bps=12.0)
    fill = _fill(fill_id="f1", side="long", price=100.0)
    fill["confidence_calibrated"] = 0.86
    fill["entry_atr_bps"] = 8.0
    fill["market_regime"] = "HIGH_VOLATILITY,RISK_OFF"
    position = position_from_fill(fill, fill_id="f1", side="long", quantity=1.0, price=100.0)
    position.market_regime_at_entry = "HIGH_VOLATILITY,RISK_OFF"
    expected_stop = effective_atr_stop_bps(
        atr_bps=8.0,
        confidence_calibrated=0.86,
        strategy_selected_mode=None,
        market_regime="HIGH_VOLATILITY,RISK_OFF",
        config=cfg,
    )
    # Price far below the stop so the ATR stop fires and reports its distance.
    result = evaluate_exit(
        position=position,
        mark_price=100.0 * (1.0 - (expected_stop + 5.0) / 10000.0),
        generated_utc="2026-07-16T10:06:00Z",
        config=cfg,
        atr_bps=8.0,
    )
    assert result["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert abs(result["atr_stop_bps"] - expected_stop) < 1e-9
