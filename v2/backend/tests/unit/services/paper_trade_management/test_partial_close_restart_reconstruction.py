from __future__ import annotations

from copy import deepcopy

import pytest

from v2.backend.app.services.paper_trade_management import lifecycle
from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig
from v2.backend.app.services.paper_trade_management.lifecycle import (
    PaperLifecycleConfig,
    reconcile_paper_lifecycle,
)
from v2.backend.app.services.paper_trade_management.position_state import (
    PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION,
    paper_position_reconstruction_hash,
    validate_paper_position_reconstruction,
)


def _fill(
    *,
    fill_id: str,
    side: str,
    quantity: float,
    price: float,
    generated_at: str,
    exact_entry_costs: bool = True,
) -> dict:
    row = {
        "fill_id": fill_id,
        "ledger_row_id": fill_id,
        "intent_id": fill_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": side,
        "selected_action": side,
        "quantity": quantity,
        "notional": quantity * price,
        "notional_usdt": quantity * price,
        "entry_price": price,
        "fill_price": price,
        "fill_price_utc": generated_at,
        "generated_utc": generated_at,
        "decision_time": generated_at,
        "available_at": generated_at,
        "signal_id": f"signal-{fill_id}",
        "prediction_id": f"prediction-{fill_id}",
        "risk_decision_id": f"risk-{fill_id}",
        "orchestrator_decision_id": f"orchestrator-{fill_id}",
        "market_state_id": f"market-{fill_id}",
        "feature_snapshot_id": f"feature-{fill_id}",
        "checkpoint_id": f"checkpoint-{fill_id}",
        "paper_fill_allowed": True,
        "effective_leverage": 2.0,
        "allocated_margin_usd": quantity * price / 2.0,
        "gross_notional_usd": quantity * price,
        "actual_observed_spread_exit_bps": 2.0,
        "exit_spread_source": "UNIT_EXIT_TOP_OF_BOOK",
        "exit_spread_available_at": generated_at,
        "funding_rate": 0.0,
        "funding_interval_seconds": 28800.0,
        "paper_only": True,
        "places_real_order": False,
    }
    if exact_entry_costs:
        row.update(
            {
                "fee_bps": 4.0,
                "fee_bps_source": "UNIT_ACCOUNT_FEE_SCHEDULE",
                "expected_slippage_bps": 3.0,
                "expected_slippage_usd": quantity * price * 3.0 / 10000.0,
                "expected_slippage_source": "UNIT_ENTRY_DEPTH_MODEL",
                "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
                "fallback_cost_flag": False,
                "production_grade_cost_flag": True,
            }
        )
    return row


def _config(*, fee_bps: float = 4.0, slippage_bps: float = 2.0) -> PaperLifecycleConfig:
    return PaperLifecycleConfig(
        portfolio_equity_usdt=100_000.0,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        exit_config=PaperExitConfig(
            static_stop_loss_enabled=False,
            static_take_profit_enabled=False,
            static_profit_lock_enabled=False,
            static_profit_bank_enabled=False,
            static_max_hold_enabled=False,
            trailing_stop_enabled=False,
        ),
    )


def _open_multi_fill_position() -> tuple[dict, dict, dict]:
    first = _fill(
        fill_id="entry-one",
        side="long",
        quantity=4.0,
        price=100.0,
        generated_at="2026-07-17T10:00:00Z",
    )
    second = _fill(
        fill_id="entry-two",
        side="long",
        quantity=6.0,
        price=200.0,
        generated_at="2026-07-17T10:01:00Z",
    )
    opened = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[first, second],
        mark_prices={"BTCUSDT": 160.0},
        generated_utc="2026-07-17T10:02:00Z",
        config=_config(),
    )
    return opened, first, second


def test_multi_fill_partial_closes_survive_distinct_cycle_restarts_exactly_once() -> None:
    opened, first, second = _open_multi_fill_position()
    initial = opened["open_positions"][0]
    assert initial["net_quantity"] == pytest.approx(10.0)
    assert initial["avg_entry_price"] == pytest.approx(160.0)
    assert initial["source_fill_ids"] == ["entry-one", "entry-two"]
    assert initial["entry_fees_incurred_usd"] == pytest.approx(0.64)
    assert initial["entry_slippage_incurred_usd"] == pytest.approx(0.48)
    assert validate_paper_position_reconstruction(initial) == []

    close_one = _fill(
        fill_id="close-one",
        side="short",
        quantity=3.0,
        price=170.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    first_partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[first, second, close_one],
        mark_prices={"BTCUSDT": 170.0},
        generated_utc="2026-07-17T10:03:01Z",
        config=_config(),
    )
    remaining_one = first_partial["open_positions"][0]
    assert len(first_partial["new_close_events"]) == 1
    assert remaining_one["net_quantity"] == pytest.approx(7.0)
    assert remaining_one["source_fill_ids"] == ["entry-one", "entry-two"]
    assert remaining_one["entry_fees_remaining_usd"] == pytest.approx(0.448)
    assert remaining_one["entry_fees_allocated_to_closes_usd"] == pytest.approx(
        0.192
    )
    assert remaining_one["entry_slippage_remaining_usd"] == pytest.approx(0.336)
    assert remaining_one[
        "entry_slippage_allocated_to_closes_usd"
    ] == pytest.approx(0.144)
    assert validate_paper_position_reconstruction(remaining_one) == []
    assert first_partial["new_close_events"][0]["entry_cost_is_final_close"] is False

    close_two = _fill(
        fill_id="close-two",
        side="short",
        quantity=2.0,
        price=180.0,
        generated_at="2026-07-17T10:04:00Z",
    )
    second_partial = reconcile_paper_lifecycle(
        existing_ledger=first_partial,
        accepted_fills=[*first_partial["accepted_open_fills"], close_two],
        mark_prices={"BTCUSDT": 180.0},
        generated_utc="2026-07-17T10:04:01Z",
        config=_config(),
    )
    remaining_two = second_partial["open_positions"][0]
    assert len(second_partial["new_close_events"]) == 1
    assert len(second_partial["closed_trades"]) == 2
    assert remaining_two["net_quantity"] == pytest.approx(5.0)
    assert remaining_two["source_fill_ids"] == ["entry-one", "entry-two"]
    assert remaining_two["entry_fees_remaining_usd"] == pytest.approx(0.32)
    assert remaining_two["entry_fees_allocated_to_closes_usd"] == pytest.approx(0.32)
    assert remaining_two["entry_slippage_remaining_usd"] == pytest.approx(0.24)
    assert remaining_two[
        "entry_slippage_allocated_to_closes_usd"
    ] == pytest.approx(0.24)
    assert validate_paper_position_reconstruction(remaining_two) == []

    close_three = _fill(
        fill_id="close-three",
        side="short",
        quantity=5.0,
        price=190.0,
        generated_at="2026-07-17T10:05:00Z",
    )
    completed = reconcile_paper_lifecycle(
        existing_ledger=second_partial,
        accepted_fills=[*second_partial["accepted_open_fills"], close_three],
        mark_prices={"BTCUSDT": 190.0},
        generated_utc="2026-07-17T10:05:01Z",
        config=_config(),
    )
    assert completed["open_positions"] == []
    assert len(completed["new_close_events"]) == 1
    assert len(completed["closed_trades"]) == 3
    closes = completed["closed_trades"]
    assert sum(row["entry_fee_usd"] for row in closes) == pytest.approx(0.64)
    assert sum(row["entry_slippage_usd"] for row in closes) == pytest.approx(0.48)
    assert closes[-1]["entry_cost_is_final_close"] is True

    replayed = reconcile_paper_lifecycle(
        existing_ledger=completed,
        accepted_fills=completed["accepted_open_fills"],
        mark_prices={"BTCUSDT": 191.0},
        generated_utc="2026-07-17T10:06:00Z",
        config=_config(),
    )
    assert replayed["open_positions"] == []
    assert replayed["new_close_events"] == []


def test_tampered_partial_snapshot_fails_closed_instead_of_reinferring() -> None:
    opened, first, second = _open_multi_fill_position()
    close = _fill(
        fill_id="partial-close",
        side="short",
        quantity=3.0,
        price=170.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[first, second, close],
        mark_prices={"BTCUSDT": 170.0},
        generated_utc="2026-07-17T10:03:01Z",
        config=_config(),
    )
    tampered = deepcopy(partial)
    tampered["open_positions"][0]["net_quantity"] = 9.0
    tampered["positions_by_symbol"]["BTCUSDT"]["net_quantity"] = 9.0

    result = reconcile_paper_lifecycle(
        existing_ledger=tampered,
        accepted_fills=[first, second],
        mark_prices={"BTCUSDT": 175.0},
        generated_utc="2026-07-17T10:04:00Z",
        config=_config(),
    )

    assert result["open_positions"] == []
    assert result["new_close_events"] == []
    status = result["paper_position_lifecycle_status"]
    assert status["position_reconstruction_block_count"] == 1
    assert "POSITION_RECONSTRUCTION_HASH_MISMATCH" in status[
        "position_reconstruction_blocks"
    ][0]["paper_lifecycle_block_reasons"]


def test_same_side_add_cannot_erase_partial_positions_exact_cost_basis() -> None:
    opened, first, second = _open_multi_fill_position()
    partial_close = _fill(
        fill_id="partial-close-before-add",
        side="short",
        quantity=3.0,
        price=170.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[first, second, partial_close],
        mark_prices={"BTCUSDT": 170.0},
        generated_utc="2026-07-17T10:03:01Z",
        config=_config(),
    )
    before_add = partial["open_positions"][0]
    incomplete_add = _fill(
        fill_id="incomplete-same-side-add",
        side="long",
        quantity=1.0,
        price=175.0,
        generated_at="2026-07-17T10:04:00Z",
        exact_entry_costs=False,
    )

    result = reconcile_paper_lifecycle(
        existing_ledger=partial,
        accepted_fills=[*partial["accepted_open_fills"], incomplete_add],
        mark_prices={"BTCUSDT": 175.0},
        generated_utc="2026-07-17T10:04:01Z",
        config=_config(),
    )

    after_add = result["open_positions"][0]
    assert after_add["net_quantity"] == pytest.approx(before_add["net_quantity"])
    assert after_add["source_fill_ids"] == before_add["source_fill_ids"]
    assert after_add["entry_fees_incurred_usd"] == pytest.approx(
        before_add["entry_fees_incurred_usd"]
    )
    assert after_add["entry_fees_remaining_usd"] == pytest.approx(
        before_add["entry_fees_remaining_usd"]
    )
    assert after_add["entry_fees_allocated_to_closes_usd"] == pytest.approx(
        before_add["entry_fees_allocated_to_closes_usd"]
    )
    assert validate_paper_position_reconstruction(after_add) == []
    blocked = [
        row
        for row in result["blocked_entries"]
        if row.get("fill_id") == "incomplete-same-side-add"
    ]
    assert len(blocked) == 1
    assert blocked[0]["paper_same_side_capital_error"] == (
        "MIXED_FEE_ENTRY_COST_BASIS_WOULD_DESTROY_EXACT_LEDGER"
    )


@pytest.mark.parametrize(
    ("generated_at", "entry_at", "expected_blocker"),
    (
        (
            "2026-07-17T10:02:00",
            "2026-07-17T10:00:00Z",
            "POSITION_RECONSTRUCTION_GENERATED_TIME_NOT_AWARE_UTC",
        ),
        (
            "2026-07-17T10:02:00Z",
            "2026-07-17T10:03:00Z",
            "POSITION_RECONSTRUCTION_ENTRY_AFTER_GENERATED_TIME",
        ),
        (
            "2026-07-17T10:05:00Z",
            "2026-07-17T10:00:00Z",
            "POSITION_RECONSTRUCTION_GENERATED_AFTER_OBSERVED_TIME",
        ),
    ),
)
def test_rehashed_snapshot_with_naive_or_future_clock_still_fails_closed(
    generated_at: str,
    entry_at: str,
    expected_blocker: str,
) -> None:
    opened, first, second = _open_multi_fill_position()
    ambiguous = deepcopy(opened)
    for container in (
        ambiguous["open_positions"][0],
        ambiguous["positions_by_symbol"]["BTCUSDT"],
    ):
        container["position_reconstruction_generated_at"] = generated_at
        container["entry_generation_time_utc"] = entry_at
        container["position_reconstruction_hash"] = paper_position_reconstruction_hash(
            container
        )

    result = reconcile_paper_lifecycle(
        existing_ledger=ambiguous,
        accepted_fills=[first, second],
        mark_prices={"BTCUSDT": 160.0},
        generated_utc="2026-07-17T10:04:00Z",
        config=_config(),
    )

    assert result["open_positions"] == []
    blockers = result["paper_position_lifecycle_status"][
        "position_reconstruction_blocks"
    ][0]["paper_lifecycle_block_reasons"]
    assert expected_blocker in blockers


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_blocker"),
    (
        (
            "realized_pnl",
            "not-a-number",
            "POSITION_RECONSTRUCTION_REALIZED_PNL_INVALID",
        ),
        (
            "entry_fees_incurred_usd",
            "not-a-number",
            "POSITION_RECONSTRUCTION_ENTRY_FEES_LEDGER_INVALID",
        ),
        (
            "entry_fee_fallback_bps_per_side",
            -1.0,
            "POSITION_RECONSTRUCTION_ENTRY_FEE_FALLBACK_BPS_PER_SIDE_INVALID",
        ),
        (
            "entry_fee_cost_sources",
            "not-a-list",
            "POSITION_RECONSTRUCTION_ENTRY_FEE_COST_SOURCES_INVALID",
        ),
    ),
)
def test_rehashed_invalid_economic_field_is_still_rejected(
    field_name: str,
    invalid_value: object,
    expected_blocker: str,
) -> None:
    opened, _, _ = _open_multi_fill_position()
    snapshot = deepcopy(opened["open_positions"][0])
    snapshot[field_name] = invalid_value
    snapshot["position_reconstruction_hash"] = paper_position_reconstruction_hash(
        snapshot
    )

    assert expected_blocker in validate_paper_position_reconstruction(snapshot)


def test_legacy_partial_snapshot_without_exact_envelope_fails_closed() -> None:
    opened, first, second = _open_multi_fill_position()
    close = _fill(
        fill_id="legacy-partial-close",
        side="short",
        quantity=3.0,
        price=170.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[first, second, close],
        mark_prices={"BTCUSDT": 170.0},
        generated_utc="2026-07-17T10:03:01Z",
        config=_config(),
    )
    legacy = deepcopy(partial)
    for container in (
        legacy["open_positions"][0],
        legacy["positions_by_symbol"]["BTCUSDT"],
    ):
        for field in (
            "position_reconstruction_schema_version",
            "position_reconstruction_generated_at",
            "position_reconstruction_hash",
            "entry_fees_remaining_usd",
            "entry_slippage_remaining_usd",
        ):
            container.pop(field, None)

    result = reconcile_paper_lifecycle(
        existing_ledger=legacy,
        accepted_fills=[first, second],
        mark_prices={"BTCUSDT": 175.0},
        generated_utc="2026-07-17T10:04:00Z",
        config=_config(),
    )

    assert result["open_positions"] == []
    block = result["paper_position_lifecycle_status"][
        "position_reconstruction_blocks"
    ][0]
    assert block["paper_lifecycle_status"] == (
        "LEGACY_PARTIAL_POSITION_RECONSTRUCTION_BLOCKED"
    )


def test_tampered_historical_netting_receipt_is_quarantined_not_reapplied() -> None:
    opened, first, second = _open_multi_fill_position()
    close = _fill(
        fill_id="receipt-partial-close",
        side="short",
        quantity=3.0,
        price=170.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[first, second, close],
        mark_prices={"BTCUSDT": 170.0},
        generated_utc="2026-07-17T10:03:01Z",
        config=_config(),
    )
    tampered_rows = deepcopy(partial["accepted_open_fills"])
    receipt = next(
        row for row in tampered_rows if row.get("paper_netting_close_id")
    )
    receipt["paper_netting_consumed_quantity"] = 8.0

    result = reconcile_paper_lifecycle(
        existing_ledger=partial,
        accepted_fills=tampered_rows,
        mark_prices={"BTCUSDT": 175.0},
        generated_utc="2026-07-17T10:04:00Z",
        config=_config(),
    )

    assert result["new_close_events"] == []
    assert result["open_positions"][0]["net_quantity"] == pytest.approx(7.0)
    receipt_block = next(
        row
        for row in result["blocked_entries"]
        if row.get("paper_lifecycle_status")
        == "HISTORICAL_NETTING_FILL_RECEIPT_BLOCKED"
    )
    assert "PAPER_NETTING_FILL_RECEIPT_HASH_INVALID" in receipt_block[
        "paper_lifecycle_block_reasons"
    ]


def test_partial_close_lineage_does_not_claim_every_source_fill_is_closed() -> None:
    opened, first, second = _open_multi_fill_position()
    close = _fill(
        fill_id="lineage-partial-close",
        side="short",
        quantity=3.0,
        price=170.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[first, second, close],
        mark_prices={"BTCUSDT": 170.0},
        generated_utc="2026-07-17T10:03:01Z",
        config=_config(),
    )
    partial_close = partial["new_close_events"][0]
    assert partial_close["source_fill_ids"] == ["entry-one", "entry-two"]
    assert lifecycle._closed_generation_evidence(
        first,
        fill_id="entry-one",
        closed_trades=[partial_close],
    ) is None

    proven_final = dict(partial_close)
    proven_final["entry_cost_is_final_close"] = True
    assert lifecycle._closed_generation_evidence(
        first,
        fill_id="entry-one",
        closed_trades=[proven_final],
    ) is None
    proven_final["entry_cost_pre_close_quantity"] = 3.0
    proven_final["entry_cost_closed_quantity"] = 3.0
    assert lifecycle._closed_generation_evidence(
        first,
        fill_id="entry-one",
        closed_trades=[proven_final],
    ) is not None


def test_fallback_entry_basis_is_materialized_once_and_survives_restart() -> None:
    entry = _fill(
        fill_id="fallback-entry",
        side="long",
        quantity=10.0,
        price=100.0,
        generated_at="2026-07-17T10:00:00Z",
        exact_entry_costs=False,
    )
    opened = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[entry],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-07-17T10:01:00Z",
        config=_config(fee_bps=4.0, slippage_bps=2.0),
    )
    first_close = _fill(
        fill_id="fallback-close-one",
        side="short",
        quantity=4.0,
        price=105.0,
        generated_at="2026-07-17T10:02:00Z",
    )
    partial = reconcile_paper_lifecycle(
        existing_ledger=opened,
        accepted_fills=[entry, first_close],
        mark_prices={"BTCUSDT": 105.0},
        generated_utc="2026-07-17T10:02:01Z",
        config=_config(fee_bps=4.0, slippage_bps=2.0),
    )
    remaining = partial["open_positions"][0]
    assert remaining["entry_fees_incurred_usd"] == pytest.approx(0.4)
    assert remaining["entry_fees_remaining_usd"] == pytest.approx(0.24)
    assert remaining["entry_fees_allocated_to_closes_usd"] == pytest.approx(0.16)
    assert remaining["entry_slippage_incurred_usd"] == pytest.approx(0.2)
    assert remaining["entry_slippage_remaining_usd"] == pytest.approx(0.12)
    assert remaining[
        "entry_slippage_allocated_to_closes_usd"
    ] == pytest.approx(0.08)
    assert remaining["entry_fee_fallback_bps_per_side"] == pytest.approx(4.0)
    assert remaining["entry_slippage_fallback_bps_per_side"] == pytest.approx(2.0)
    assert validate_paper_position_reconstruction(remaining) == []

    final_close = _fill(
        fill_id="fallback-close-two",
        side="short",
        quantity=6.0,
        price=110.0,
        generated_at="2026-07-17T10:03:00Z",
    )
    completed = reconcile_paper_lifecycle(
        existing_ledger=partial,
        accepted_fills=[*partial["accepted_open_fills"], final_close],
        mark_prices={"BTCUSDT": 110.0},
        generated_utc="2026-07-17T10:03:01Z",
        # Deliberately changed generic fallback config: the persisted entry
        # basis must retain the rate materialized at the first close.
        config=_config(fee_bps=9.0, slippage_bps=8.0),
    )
    assert completed["open_positions"] == []
    closes = completed["closed_trades"]
    assert sum(row["entry_fee_usd"] for row in closes) == pytest.approx(0.4)
    assert sum(row["entry_slippage_usd"] for row in closes) == pytest.approx(0.2)
    assert closes[-1]["entry_fee_fallback"] is True
    assert closes[-1]["entry_slippage_fallback"] is True
    assert closes[-1]["entry_fee_fallback_bps_per_side"] == pytest.approx(4.0)
    assert closes[-1]["entry_slippage_fallback_bps_per_side"] == pytest.approx(2.0)
    assert (
        completed["paper_position_lifecycle_status"]
        ["position_reconstruction_schema_version"]
        == PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION
    )
