from __future__ import annotations

from v2.backend.app.services.live_gate.phase7_readiness import (
    build_first_live_canary_operator_packet,
    build_live_pre_submit_dry_run_status,
    build_phase7_status_bundle,
)


def _runtime(*, enabled: bool = True) -> dict[str, object]:
    return {
        "live_gate": "enabled_operator_approved" if enabled else "blocked_human_only",
        "release_mode": "LIVE_CANARY_APPROVED" if enabled else "NON_LIVE",
        "operator_approved": enabled,
        "kill_switch_enabled": True,
        "kill_switch_active": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "leverage_mutation_allowed": False,
        "margin_mutation_allowed": False,
        "available_margin": 1_000.0,
        "risk_profile": {
            "profile_name": "conservative_min_executable",
            "fields": {
                "max_symbol_exposure": 1_000.0,
                "max_total_exposure": 2_000.0,
                "max_drawdown": 75.0,
            },
        },
        "live_canary_config": {
            "live_canary_enabled": True,
            "allowed_symbols": ["BTCUSDT"],
            "max_notional_usd": 1_000.0,
            "max_open_positions": 1,
            "require_human_operator_arm": False,
        },
    }


def _account(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "signed_account_read_ok": True,
        "available_margin": 1_000.0,
        "local_position": {"symbol": "BTCUSDT", "side": "flat", "quantity": 0.0},
        "exchange_position": {"symbol": "BTCUSDT", "side": "flat", "quantity": 0.0},
        "current_positions": [{"symbol": "BTCUSDT", "side": "flat", "quantity": 0.0}],
        "open_orders": [],
        "hedge_mode": False,
        "margin_mode": "cross",
        "signed_read_ts_ms": 1_000,
    }
    values.update(overrides)
    return values


def _filters(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "ok": True,
        "symbol": "BTCUSDT",
        "status": "TRADING",
        "min_qty": "0.0001",
        "step_size": "0.0001",
        "tick_size": "0.10",
        "min_notional": "5",
    }
    values.update(overrides)
    return values


def _allocation(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "action": "long",
        "price": 50_000.0,
        "target_quantity": 0.01,
        "target_notional_usd": 500.0,
        "allocated_margin_usd": 250.0,
        "recommended_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 120.0,
        "max_loss_if_stop_hit": 6.0,
        "liquidation_buffer_bps": 2_000.0,
        "risk_reward": 2.5,
        "risk_of_ruin_contribution": 0.001,
        "expected_net_pnl_usd": 4.0,
        "portfolio_exposure_after_trade": 500.0,
        "allocator_decision": "ALLOW_WITH_SIZE",
    }
    values.update(overrides)
    return values


def test_phase7_live_gate_blocked_keeps_dry_run_and_no_mutation() -> None:
    status = build_live_pre_submit_dry_run_status(
        _runtime(enabled=False),
        account_snapshot=_account(),
        symbol_filter_snapshot=_filters(),
        allocation_payload=_allocation(),
        now_ms=1_000,
    )

    assert status["submit_allowed"] is False
    assert status["operator_review_ready"] is True
    assert status["would_submit_if_operator_approved"] is True
    assert "LIVE_GATE_NOT_ENABLED" in status["blockers"]
    assert status["dry_run"] is True
    assert status["order_submitted"] is False
    assert status["test_order_submitted"] is False
    assert status["exchange_leverage_mutated"] is False
    assert status["exchange_margin_mutated"] is False
    assert status["places_real_order"] is False


def test_phase7_missing_signed_reads_and_filters_block_readiness() -> None:
    bundle = build_phase7_status_bundle(
        runtime_payload=_runtime(),
        account_snapshot={},
        symbol_filter_snapshot={},
        allocation_payload=_allocation(),
        now_ms=1_000,
    )

    readiness = bundle["real_trader_readiness_status"]
    pre_submit = bundle["live_pre_submit_dry_run_status"]

    assert readiness["ready_for_operator_review"] is False
    assert "SIGNED_ACCOUNT_READ_MISSING" in pre_submit["blockers"]
    assert "SYMBOL_FILTERS_NOT_VERIFIED" in pre_submit["blockers"]
    assert "TICK_SIZE_MISSING" in pre_submit["blockers"]
    assert "SIGNED_READ_TIMESTAMP_MISSING" in pre_submit["blockers"]
    assert readiness["checklist"]["read_only_signed_account_check"] is False
    assert readiness["checklist"]["symbol_filters_check"] is False


def test_phase7_stale_runtime_snapshots_block_readiness() -> None:
    account = _account(
        fresh=False,
        generated_est="2026-01-01T00:00:00Z",
        open_orders_snapshot={"ok": True, "fresh": False, "open_orders_count": 0},
        position_mode_snapshot={"ok": True, "fresh": False, "dual_side_position": False},
    )
    filters = _filters(fresh=False)

    status = build_live_pre_submit_dry_run_status(
        _runtime(),
        account_snapshot=account,
        symbol_filter_snapshot=filters,
        allocation_payload=_allocation(),
        now_ms=1_000,
    )

    assert status["submit_allowed"] is False
    assert "SIGNED_READ_STALE" in status["blockers"]
    assert "OPEN_ORDERS_SNAPSHOT_STALE" in status["blockers"]
    assert "POSITION_MODE_SNAPSHOT_STALE" in status["blockers"]
    assert "SYMBOL_FILTERS_STALE" in status["blockers"]
    assert status["pass_conditions"]["symbol_filters_verified"] is False
    readiness = build_phase7_status_bundle(
        runtime_payload=_runtime(),
        account_snapshot=account,
        symbol_filter_snapshot=filters,
        allocation_payload=_allocation(),
        now_ms=1_000,
    )["real_trader_readiness_status"]
    assert readiness["checklist"]["open_orders_check"] is False
    assert readiness["checklist"]["position_mode_check"] is False
    assert readiness["checklist"]["symbol_filters_check"] is False
    assert readiness["checklist"]["min_notional_check"] is False
    assert status["order_submitted"] is False


def test_phase7_candidate_price_reference_satisfies_min_executable_sizing() -> None:
    allocation = _allocation()
    allocation.pop("price")
    status = build_live_pre_submit_dry_run_status(
        _runtime(),
        account_snapshot=_account(),
        symbol_filter_snapshot=_filters(min_notional="50", min_qty="0.001", step_size="0.001"),
        allocation_payload=allocation,
        candidate_signal={"price_reference": 50_000.0},
        now_ms=1_000,
    )

    assert "MIN_EXECUTABLE:MARK_PRICE_MISSING_OR_INVALID" not in status["blockers"]
    assert status["symbol_filter_status"]["min_executable_order"]["ok"] is True
    assert status["submit_allowed"] is True


def test_phase7_complete_fixture_builds_operator_packet_fields() -> None:
    bundle = build_phase7_status_bundle(
        runtime_payload=_runtime(),
        operator_truth={"live_gate": "enabled_operator_approved", "live_order_submit_allowed": True},
        account_snapshot=_account(),
        symbol_filter_snapshot=_filters(),
        allocation_payload=_allocation(),
        now_ms=1_000,
    )

    readiness = bundle["real_trader_readiness_status"]
    pre_submit = bundle["live_pre_submit_dry_run_status"]
    packet = bundle["first_live_canary_operator_packet"]

    assert pre_submit["status"] == "LIVE_PRE_SUBMIT_DRY_RUN_READY"
    assert pre_submit["submit_allowed"] is True
    assert readiness["status"] == "REAL_TRADER_READY_FOR_OPERATOR_REVIEW"
    assert packet["candidate_symbol"] == "BTCUSDT"
    assert packet["side"] == "BUY"
    assert packet["quantity"] == 0.01
    assert packet["notional"] == 500.0
    assert packet["margin"] == 250.0
    assert packet["leverage_recommendation"] == 2.0
    assert packet["margin_mode_recommendation"] == "isolated_paper_simulated"
    assert packet["max_loss"] == 6.0
    assert packet["liquidation_buffer"] == 2_000.0
    assert packet["reduce_only_plan"]["reduce_only_required_for_closes"] is True
    assert packet["order_submitted"] is False
    assert packet["test_order_submitted"] is False


def test_phase7_invalid_position_transition_blocks_before_order_preview_ready() -> None:
    account = _account(
        local_position={"symbol": "BTCUSDT", "side": "long", "quantity": 0.01},
        exchange_position={"symbol": "BTCUSDT", "side": "long", "quantity": 0.01},
        current_positions=[{"symbol": "BTCUSDT", "side": "long", "quantity": 0.01}],
    )

    status = build_live_pre_submit_dry_run_status(
        _runtime(),
        account_snapshot=account,
        symbol_filter_snapshot=_filters(),
        allocation_payload=_allocation(),
        now_ms=1_000,
    )

    assert status["submit_allowed"] is False
    assert "AVERAGING_DOWN_DISABLED" in status["blockers"]
    assert status["position_transition"]["allowed"] is False
    assert status["order_submitted"] is False


def test_phase7_packet_preserves_blockers_as_why_not_allowed() -> None:
    pre_submit = build_live_pre_submit_dry_run_status(
        _runtime(enabled=False),
        account_snapshot=_account(),
        symbol_filter_snapshot=_filters(),
        allocation_payload=_allocation(),
        now_ms=1_000,
    )

    packet = build_first_live_canary_operator_packet(pre_submit, allocation_payload=_allocation())

    assert "LIVE_GATE_NOT_ENABLED" in packet["why_not_allowed"]
    assert "all_non_operator_pre_submit_checks_pass" in packet["why_allowed"]
