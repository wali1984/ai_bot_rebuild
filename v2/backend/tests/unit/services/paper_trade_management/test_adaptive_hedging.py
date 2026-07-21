"""Adaptive hedging: trigger/unwind pure functions + lifecycle pair routing.

Operator requirement (2026-07-16): hedge adverse moves instead of eating full
ATR stop-outs; all triggers/sizes/unwinds adaptive (fractions of the
position's own ATR stop and excursions), never static bps thresholds.
Paper-only; live gate stays BLOCKED.
"""
from __future__ import annotations

from v2.backend.app.services.paper_trade_management import lifecycle as lifecycle_module
from v2.backend.app.services.paper_trade_management.exits import (
    PaperExitConfig,
    effective_atr_stop_bps,
    evaluate_exit,
)
from v2.backend.app.services.paper_trade_management.hedging import (
    HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS,
    build_adaptive_hedge_directive_validity,
    evaluate_adaptive_hedge_trigger,
    evaluate_adaptive_hedge_unwind,
    hedge_directive_storage_ttl_seconds,
    validate_adaptive_hedge_directive_validity,
)
from v2.backend.app.services.paper_trade_management.lifecycle import (
    PaperLifecycleConfig,
    reconcile_paper_lifecycle,
)
from v2.backend.app.services.paper_trade_management.position_state import position_from_fill

_SESSION = "paper-session-adaptive-hedge-unit"


def _authoritative_mark_evidence(
    *,
    price: float = 99.5,
    event_time: str = "2026-07-16T10:00:59.500Z",
    generated_at: str = "2026-07-16T10:00:59.600Z",
    available_at: str = "2026-07-16T10:00:59.700Z",
    freshness_seconds: float = 1.0,
) -> dict:
    return {
        "price": price,
        "authority_complete": True,
        "event_time": event_time,
        "generated_at": generated_at,
        "available_at": available_at,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "authentication_boundary": "BINANCE_USDM_TLS_WSS_MARK_PRICE_PUBLIC_STREAM_V1",
        "consumer_validation_boundary": "PAPER_LOOP_EXCHANGE_MARK_CONSUMER_V1",
        "cadence_policy_version": "BINANCE_USDM_MARK_PRICE_STREAM_1S_CADENCE_V1",
        "freshness_budget_seconds": freshness_seconds,
        "expected_update_interval_seconds": freshness_seconds,
        "evidence_sha256": "a" * 64,
    }


def _directive_validity(*, previous: str) -> dict:
    return build_adaptive_hedge_directive_validity(
        previous_cycle_generated_utc=previous,
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        mark_evidence=_authoritative_mark_evidence(),
    )


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
        "paper_session_id": _SESSION,
    }
    row.update(extra)
    return row


def _hedge_fill(parent_fill: dict, *, hedge_ratio: float = 0.5, price: float = 99.0) -> dict:
    parent_position = position_from_fill(
        parent_fill,
        fill_id=str(parent_fill["fill_id"]),
        side=str(parent_fill["side"]),
        quantity=float(parent_fill["quantity"]),
        price=float(parent_fill["fill_price"]),
    )
    parent_id = parent_position.position_id
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
            "hedge_parent_generation_id": parent_position.position_generation_id,
            "hedge_child_id": hedge_id,
            "hedge_pair_session_id": _SESSION,
            "hedge_ratio": hedge_ratio,
            "hedge_state": "HEDGE_CHILD",
            "hedge_reason": "ADAPTIVE_ADVERSE_EXCURSION_HEDGE",
            # Hedge entered at price 99 = parent long from 100 was at -100bps.
            "hedge_entry_parent_pnl_bps": -100.0,
        }
    )
    return row


# ── Directive validity/queue cadence ──────────────────────────────────────


def test_directive_validity_adapts_to_observed_lifecycle_cadence() -> None:
    fast = _directive_validity(previous="2026-07-16T10:00:45.000Z")
    slow = _directive_validity(previous="2026-07-16T09:59:30.000Z")

    assert fast["authority_complete"] is True
    assert slow["authority_complete"] is True
    assert fast["observed_lifecycle_update_cadence_seconds"] == 15.0
    assert slow["observed_lifecycle_update_cadence_seconds"] == 90.0
    assert fast["adaptive_freshness_budget_seconds"] == 16.0
    assert slow["adaptive_freshness_budget_seconds"] == 91.0
    assert fast["valid_until"] == "2026-07-16T10:01:16.000Z"
    assert slow["valid_until"] == "2026-07-16T10:02:31.000Z"


def test_directive_validity_expires_fail_closed_at_derived_boundary() -> None:
    validity = _directive_validity(previous="2026-07-16T10:00:45.000Z")

    before_expiry = validate_adaptive_hedge_directive_validity(
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        validity_envelope=validity,
        observed_at="2026-07-16T10:01:15.999Z",
    )
    after_expiry = validate_adaptive_hedge_directive_validity(
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        validity_envelope=validity,
        observed_at="2026-07-16T10:01:16.001Z",
    )

    assert before_expiry["valid"] is True
    assert after_expiry["valid"] is False
    assert after_expiry["expired"] is True
    assert "HEDGE_DIRECTIVE_ADAPTIVE_VALIDITY_EXPIRED" in after_expiry[
        "rejection_reasons"
    ]


def test_directive_validity_requires_observed_cadence_and_mark_authority() -> None:
    no_observation = build_adaptive_hedge_directive_validity(
        previous_cycle_generated_utc=None,
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        mark_evidence=_authoritative_mark_evidence(),
    )
    unauthenticated_mark = build_adaptive_hedge_directive_validity(
        previous_cycle_generated_utc="2026-07-16T10:00:45.000Z",
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        mark_evidence={
            **_authoritative_mark_evidence(),
            "authority_complete": False,
        },
    )
    wrong_source = build_adaptive_hedge_directive_validity(
        previous_cycle_generated_utc="2026-07-16T10:00:45.000Z",
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        mark_evidence={
            **_authoritative_mark_evidence(),
            "source": "ticker_fallback",
        },
    )

    assert no_observation["authority_complete"] is False
    assert unauthenticated_mark["authority_complete"] is False
    assert wrong_source["authority_complete"] is False
    assert "HEDGE_DIRECTIVE_CADENCE_CLOCK_MISSING_OR_INVALID" in no_observation[
        "rejection_reasons"
    ]
    assert "HEDGE_DIRECTIVE_MARK_AUTHORITY_INCOMPLETE" in unauthenticated_mark[
        "rejection_reasons"
    ]
    assert "HEDGE_DIRECTIVE_MARK_SOURCE_MISMATCH" in wrong_source[
        "rejection_reasons"
    ]


def test_directive_validity_tamper_fails_consumer_reconciliation() -> None:
    validity = _directive_validity(previous="2026-07-16T10:00:45.000Z")
    tampered = {
        **validity,
        "adaptive_freshness_budget_seconds": 17.0,
    }

    result = validate_adaptive_hedge_directive_validity(
        directive_generated_utc="2026-07-16T10:01:00.000Z",
        validity_envelope=tampered,
        observed_at="2026-07-16T10:01:01.000Z",
    )

    assert result["valid"] is False
    assert "HEDGE_DIRECTIVE_ADAPTIVE_BUDGET_RECONCILIATION_FAILED" in result[
        "rejection_reasons"
    ]


def test_directive_safety_ceiling_caps_stalled_cadence_without_becoming_authority() -> None:
    validity = _directive_validity(previous="2026-07-16T09:00:00.000Z")

    assert validity["observed_lifecycle_update_cadence_seconds"] == 3660.0
    assert validity["adaptive_freshness_budget_seconds"] == (
        HEDGE_DIRECTIVE_IMMUTABLE_MAX_SAFETY_LIFETIME_SECONDS
    )
    assert validity["valid_until"] == "2026-07-16T10:11:00.000Z"


def test_queue_ttl_tracks_remaining_directive_lifetime_and_never_extends_it() -> None:
    fast = {
        "generated_utc": "2026-07-16T10:01:00.000Z",
        "validity_envelope": _directive_validity(
            previous="2026-07-16T10:00:45.000Z"
        ),
    }
    slow = {
        "generated_utc": "2026-07-16T10:01:00.000Z",
        "validity_envelope": _directive_validity(
            previous="2026-07-16T09:59:30.000Z"
        ),
    }

    assert hedge_directive_storage_ttl_seconds(
        [fast], observed_at="2026-07-16T10:01:01.000Z"
    ) == 15
    assert hedge_directive_storage_ttl_seconds(
        [slow], observed_at="2026-07-16T10:01:01.000Z"
    ) == 90
    assert (
        hedge_directive_storage_ttl_seconds(
            [fast], observed_at="2026-07-16T10:01:16.001Z"
        )
        is None
    )


def test_lifecycle_pending_hedge_uses_hashed_adaptive_expiry_across_restarts() -> None:
    parent = _fill(
        fill_id="adaptive-validity-parent",
        side="long",
        price=100.0,
        confidence_calibrated=0.9,
        entry_atr_bps=20.0,
    )
    opened = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[parent],
        mark_prices={"BTCUSDT": {"price": 100.0}},
        generated_utc="2026-07-16T10:00:00.000Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )
    triggered = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[parent],
        mark_prices={
            "BTCUSDT": _authoritative_mark_evidence(price=99.3),
        },
        generated_utc="2026-07-16T10:01:00.000Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )

    assert len(triggered["hedge_directives"]) == 1, {
        "hedge": triggered["paper_adaptive_hedge_status"],
        "exit": triggered["paper_exit_coordinator_status"]["evaluations"],
    }
    pending = triggered["positions_by_symbol"]["BTCUSDT"]
    assert pending["hedge_state"] == "HEDGE_PENDING"
    assert pending["hedge_pending_validity_envelope"]["valid_until"] == (
        "2026-07-16T10:02:01.000Z"
    )

    deferred = reconcile_paper_lifecycle(
        existing_ledger=triggered,
        accepted_fills=[parent],
        mark_prices={"BTCUSDT": {"price": 98.8}},
        generated_utc="2026-07-16T10:01:30.000Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )
    deferred_evaluation = deferred["paper_exit_coordinator_status"]["evaluations"][0]
    assert deferred_evaluation["blocker"] == "ATR_STOP_DEFERRED_HEDGE_FILL_IN_FLIGHT"
    assert deferred["positions_by_symbol"]["BTCUSDT"]["hedge_state"] == (
        "HEDGE_PENDING"
    )

    expired = reconcile_paper_lifecycle(
        existing_ledger=deferred,
        accepted_fills=[parent],
        mark_prices={"BTCUSDT": {"price": 98.8}},
        generated_utc="2026-07-16T10:02:01.001Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )
    expired_evaluation = expired["paper_exit_coordinator_status"]["evaluations"][0]
    assert expired_evaluation["close_reason"] == "TIER_1_ATR_VOLATILITY_STOP"
    assert "HEDGE_DIRECTIVE_ADAPTIVE_VALIDITY_EXPIRED" in expired_evaluation[
        "hedge_pending_expiry_reasons"
    ]
    assert "BTCUSDT" not in expired["positions_by_symbol"]
    assert any(
        row.get("close_reason") == "TIER_1_ATR_VOLATILITY_STOP"
        for row in expired["new_close_events"]
    )


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
        paper_session_id=_SESSION,
    )
    keys = set(result["positions_by_symbol"])
    assert "BTCUSDT" in keys
    assert "BTCUSDT::HEDGE" in keys
    parent_row = result["positions_by_symbol"]["BTCUSDT"]
    hedge_row = result["positions_by_symbol"]["BTCUSDT::HEDGE"]
    assert parent_row["hedge_state"] == "HEDGED"
    assert hedge_row["hedge_state"] == "HEDGE_CHILD"
    assert hedge_row["hedge_parent_id"] == parent_row["position_id"]
    assert hedge_row["hedge_parent_generation_id"] == parent_row[
        "position_generation_id"
    ]
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
        paper_session_id=_SESSION,
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
        paper_session_id=_SESSION,
    )
    assert "BTCUSDT::HEDGE" not in result["positions_by_symbol"]


def test_orphan_hedge_fill_is_rejected_before_pair_mutation() -> None:
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
        accepted_fills=[hedge],
        mark_prices={"BTCUSDT": {"price": 99.5}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )
    assert "BTCUSDT::HEDGE" not in result["positions_by_symbol"]
    assert any(
        "HEDGE_PARENT_POSITION_NOT_OPEN"
        in (row.get("paper_lifecycle_block_reasons") or [])
        for row in result["blocked_entries"]
    )


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
        paper_session_id=_SESSION,
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


def test_hedge_pair_cannot_mutate_from_unauthenticated_fallback_mark() -> None:
    parent = _fill(fill_id="mark-authority-parent", side="long", price=100.0)
    hedge = _hedge_fill(parent, price=99.0)
    opened = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 99.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )

    held = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 90.0}},
        generated_utc="2026-07-17T10:06:00Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )

    assert set(held["positions_by_symbol"]) == {"BTCUSDT", "BTCUSDT::HEDGE"}
    assert not held["new_close_events"]
    assert any(
        event.get("reason")
        == "AUTHENTICATED_CURRENT_MARK_REQUIRED_FOR_HEDGE_PAIR_MUTATION"
        for event in held["paper_adaptive_hedge_status"]["pair_events"]
    )


def test_close_both_is_atomic_when_second_leg_preflight_fails(monkeypatch) -> None:
    parent = _fill(fill_id="atomic-parent", side="long", price=100.0)
    hedge = _hedge_fill(parent, price=99.0)
    opened = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[parent, hedge],
        mark_prices={"BTCUSDT": {"price": 99.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )
    assert set(opened["positions_by_symbol"]) == {"BTCUSDT", "BTCUSDT::HEDGE"}

    real_close = lifecycle_module._close_position

    def _fail_parent_leg(**kwargs):
        if kwargs.get("symbol") == "BTCUSDT":
            return None, None, {"reason": "INJECTED_PARENT_LEG_FAILURE"}
        return real_close(**kwargs)

    monkeypatch.setattr(lifecycle_module, "_close_position", _fail_parent_leg)
    result = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[parent, hedge],
        mark_prices={
            "BTCUSDT": _authoritative_mark_evidence(
                price=90.0,
                event_time="2026-07-17T10:05:59.500Z",
                generated_at="2026-07-17T10:05:59.600Z",
                available_at="2026-07-17T10:05:59.700Z",
            )
        },
        generated_utc="2026-07-17T10:06:00Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
    )

    assert set(result["positions_by_symbol"]) == {"BTCUSDT", "BTCUSDT::HEDGE"}
    assert not [
        row
        for row in result["new_close_events"]
        if row.get("close_reason") == "TIER_2_HEDGE_PAIR_CLOSE"
    ]
    assert any(
        row.get("paper_lifecycle_status") == "HEDGE_PAIR_CLOSE_BLOCKED_ATOMIC"
        for row in result["paper_exit_coordinator_status"]["dirty_close_blocks"]
    )


def test_hedge_status_block_present() -> None:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill(fill_id="f1")],
        mark_prices={"BTCUSDT": {"price": 100.0}},
        generated_utc="2026-07-16T10:06:00Z",
        config=_hedge_config(),
        paper_session_id=_SESSION,
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
