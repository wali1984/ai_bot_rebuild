from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.feedback_enrichment import (
    build_strategy_hedge_exit_feedback,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.paper_trade_management import lifecycle
from v2.backend.app.services.paper_trade_management.outcomes import (
    PAPER_COST_RATE_SCOPE,
    PAPER_NET_PNL_FORMULA,
    PAPER_ROUND_TRIP_COST_ACCOUNTING_VERSION,
    build_close_event,
)
from v2.backend.app.services.paper_trade_management.position_state import (
    position_from_fill,
)


def _costed_fill(
    *,
    quantity: float = 10.0,
    entry_price: float = 100.0,
    fill_id: str = "cost-basis-fill",
) -> dict:
    return {
        "fill_id": fill_id,
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": quantity,
        "notional": quantity * entry_price,
        "notional_usdt": quantity * entry_price,
        "entry_price": entry_price,
        "fill_price": entry_price,
        "fill_price_utc": "2026-07-17T10:00:00Z",
        "generated_utc": "2026-07-17T10:00:00Z",
        "fee_bps": 4.0,
        "fee_bps_source": "READ_ONLY_ACCOUNT_TAKER_FEE_SCHEDULE",
        "expected_slippage_bps": 3.0,
        "expected_slippage_usd": quantity * entry_price * 3.0 / 10000.0,
        "expected_slippage_source": "ENTRY_ORDERBOOK_DEPTH_IMPACT_MODEL",
        "funding_rate": 0.0,
        "funding_interval_seconds": 28800.0,
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "fallback_cost_flag": False,
        "production_grade_cost_flag": True,
    }


def _position(*, quantity: float = 10.0, entry_price: float = 100.0):
    fill = _costed_fill(quantity=quantity, entry_price=entry_price)
    return position_from_fill(
        fill,
        fill_id=str(fill["fill_id"]),
        side="long",
        quantity=quantity,
        price=entry_price,
    )


def test_full_close_emits_complete_round_trip_cost_arithmetic() -> None:
    position = _position()

    close_event, outcome = build_close_event(
        position=position,
        close_quantity=10.0,
        exit_price=110.0,
        exit_time="2026-07-17T11:00:00Z",
        close_reason="UNIT_FULL_CLOSE",
        # Deliberately different: entry-bound account fee provenance wins for
        # the exit over the generic lifecycle fallback.
        fee_bps=9.0,
        slippage_bps=7.0,
        exit_spread_bps=8.0,
        exit_spread_source="EXIT_ORDERBOOK_TOP_OF_BOOK",
        exit_spread_available_at="2026-07-17T10:59:59Z",
    )

    # Entry: 1000 * (4 + 3) bps. Exit: 1100 * (4 + half-spread 4) bps.
    assert close_event["entry_fee_usd"] == pytest.approx(0.4)
    assert close_event["exit_fee_usd"] == pytest.approx(0.44)
    assert close_event["total_fees_usd"] == pytest.approx(0.84)
    assert close_event["entry_slippage_usd"] == pytest.approx(0.3)
    assert close_event["exit_slippage_usd"] == pytest.approx(0.44)
    assert close_event["total_slippage_usd"] == pytest.approx(0.74)
    assert close_event["realized_gross_pnl_usd"] == pytest.approx(100.0)
    assert close_event["funding_pnl_usd"] == pytest.approx(0.0)
    assert close_event["realized_net_pnl_usd"] == pytest.approx(98.42)
    assert close_event["paper_round_trip_cost_accounting_version"] == (
        PAPER_ROUND_TRIP_COST_ACCOUNTING_VERSION
    )
    assert close_event["paper_cost_rate_scope"] == PAPER_COST_RATE_SCOPE
    assert close_event["paper_net_pnl_formula"] == PAPER_NET_PNL_FORMULA
    assert close_event["outcome_cost_unit"] == "USD"
    assert close_event["funding_usd"] == pytest.approx(0.0)
    assert close_event["round_trip_cost_provenance_status"] == (
        "COMPLETE_ENTRY_AND_EXIT_COST_PROVENANCE"
    )
    assert close_event["round_trip_cost_fallback_used"] is False
    assert close_event["entry_fee_source"] == "READ_ONLY_ACCOUNT_TAKER_FEE_SCHEDULE"
    assert close_event["exit_fee_source"] == "READ_ONLY_ACCOUNT_TAKER_FEE_SCHEDULE"
    assert close_event["exit_slippage_source"] == "EXIT_ORDERBOOK_TOP_OF_BOOK"
    assert close_event["outcome_targets"]["fees_usd"] == pytest.approx(0.84)
    assert close_event["outcome_targets"]["slippage_usd"] == pytest.approx(0.74)
    for field in (
        "entry_fee_usd",
        "exit_fee_usd",
        "total_fees_usd",
        "entry_slippage_usd",
        "exit_slippage_usd",
        "total_slippage_usd",
    ):
        assert outcome[field] == pytest.approx(close_event[field])
        assert outcome["outcome_targets"][field] == pytest.approx(close_event[field])


def test_tight_exit_book_uses_observed_half_spread_without_static_floor() -> None:
    position = _position(quantity=1.0)

    close_event, _outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=101.0,
        exit_time="2026-07-17T11:00:00Z",
        close_reason="UNIT_TIGHT_BOOK",
        exit_spread_bps=0.2,
        exit_spread_source="EXIT_ORDERBOOK_TOP_OF_BOOK",
        exit_spread_available_at="2026-07-17T10:59:59Z",
    )

    assert close_event["exit_slippage_bps_per_side"] == pytest.approx(0.1)
    assert close_event["exit_slippage_usd"] == pytest.approx(101.0 * 0.1 / 10000.0)


def test_sequential_partial_closes_conserve_entry_cost_basis() -> None:
    position = _position()
    positions = {"BTCUSDT": position}

    first, first_outcome, first_block = lifecycle._close_position(
        positions=positions,
        symbol="BTCUSDT",
        close_quantity=4.0,
        exit_price=105.0,
        exit_time="2026-07-17T10:30:00Z",
        close_reason="UNIT_PARTIAL_ONE",
        fee_bps=9.0,
        slippage_bps=7.0,
        exit_spread_bps=6.0,
        exit_spread_source="EXIT_BOOK_ONE",
        exit_spread_available_at="2026-07-17T10:29:59Z",
    )
    assert first_block is None
    assert first is not None and first_outcome is not None
    assert first["entry_cost_allocation_fraction_of_pre_close_position"] == pytest.approx(
        0.4
    )
    assert first["entry_fee_usd"] == pytest.approx(0.16)
    assert first["entry_slippage_usd"] == pytest.approx(0.12)
    assert first["exit_fee_usd"] == pytest.approx(0.168)
    assert first["exit_slippage_usd"] == pytest.approx(0.126)
    assert first["realized_net_pnl_usd"] == pytest.approx(19.426)
    assert position.net_quantity == pytest.approx(6.0)
    assert position.entry_fees_remaining_usd == pytest.approx(0.24)
    assert position.entry_slippage_remaining_usd == pytest.approx(0.18)
    assert position.entry_fees_allocated_to_closes_usd == pytest.approx(0.16)
    assert position.entry_slippage_allocated_to_closes_usd == pytest.approx(0.12)

    feedback = build_strategy_hedge_exit_feedback(
        close_event=first,
        outcome_label=first_outcome,
    )
    loader_targets = V2HybridTrainerDataLoader._outcome_targets_from_row(feedback)
    for field in (
        "entry_fee_usd",
        "exit_fee_usd",
        "total_fees_usd",
        "entry_slippage_usd",
        "exit_slippage_usd",
        "total_slippage_usd",
        "total_execution_costs_usd",
    ):
        assert feedback[field] == pytest.approx(first[field])
        assert loader_targets[field] == pytest.approx(first[field])
    assert loader_targets["paper_round_trip_cost_accounting_version"] == (
        PAPER_ROUND_TRIP_COST_ACCOUNTING_VERSION
    )
    assert loader_targets["round_trip_cost_fallback_used"] is False
    assert loader_targets["outcome_cost_unit"] == "USD"
    assert loader_targets["funding_usd"] == pytest.approx(first["funding_pnl_usd"])
    assert loader_targets["entry_fee_source"] == first["entry_fee_source"]
    assert loader_targets["exit_fee_source"] == first["exit_fee_source"]
    assert loader_targets["exit_slippage_source"] == first["exit_slippage_source"]
    assert loader_targets["exit_slippage_provenance_status"] == (
        "EXIT_SPREAD_AVAILABLE_BY_CLOSE_TIME"
    )

    second, second_outcome, second_block = lifecycle._close_position(
        positions=positions,
        symbol="BTCUSDT",
        close_quantity=6.0,
        exit_price=90.0,
        exit_time="2026-07-17T11:00:00Z",
        close_reason="UNIT_PARTIAL_TWO",
        fee_bps=9.0,
        slippage_bps=7.0,
        exit_spread_bps=2.0,
        exit_spread_source="EXIT_BOOK_TWO",
        exit_spread_available_at="2026-07-17T10:59:59Z",
    )
    assert second_block is None
    assert second is not None and second_outcome is not None
    assert second["entry_cost_is_final_close"] is True
    assert second["entry_fee_usd"] == pytest.approx(0.24)
    assert second["entry_slippage_usd"] == pytest.approx(0.18)
    assert second["exit_fee_usd"] == pytest.approx(0.216)
    assert second["exit_slippage_usd"] == pytest.approx(0.054)
    assert second["realized_net_pnl_usd"] == pytest.approx(-60.69)
    assert "BTCUSDT" not in positions

    # Final-close remainder allocation prevents floating drift. Every entry
    # dollar is charged exactly once across the two close rows.
    assert first["entry_fee_usd"] + second["entry_fee_usd"] == pytest.approx(0.4)
    assert first["entry_slippage_usd"] + second["entry_slippage_usd"] == pytest.approx(
        0.3
    )
    assert position.entry_fees_remaining_usd == pytest.approx(0.0)
    assert position.entry_slippage_remaining_usd == pytest.approx(0.0)
    assert position.entry_fees_allocated_to_closes_usd == pytest.approx(0.4)
    assert position.entry_slippage_allocated_to_closes_usd == pytest.approx(0.3)


def test_lifecycle_fallback_rates_are_applied_once_per_execution_side() -> None:
    fill = _costed_fill()
    for field in (
        "fee_bps",
        "fee_bps_source",
        "expected_slippage_bps",
        "expected_slippage_usd",
        "expected_slippage_source",
    ):
        fill.pop(field, None)
    position = position_from_fill(
        fill,
        fill_id=str(fill["fill_id"]),
        side="long",
        quantity=10.0,
        price=100.0,
    )

    close_event, _ = build_close_event(
        position=position,
        close_quantity=10.0,
        exit_price=110.0,
        exit_time="2026-07-17T11:00:00Z",
        close_reason="UNIT_PER_SIDE_FALLBACK",
        fee_bps=4.0,
        slippage_bps=2.0,
    )

    # The config values are per-side rates, never already-doubled round-trip
    # rates: entry uses entry notional and exit uses exit notional exactly once.
    assert close_event["entry_fee_usd"] == pytest.approx(0.4)
    assert close_event["exit_fee_usd"] == pytest.approx(0.44)
    assert close_event["entry_slippage_usd"] == pytest.approx(0.2)
    assert close_event["exit_slippage_usd"] == pytest.approx(0.22)
    assert close_event["total_execution_costs_usd"] == pytest.approx(1.26)
    assert close_event["exit_fee_fallback"] is True
    assert close_event["exit_slippage_fallback"] is True
    assert close_event["round_trip_cost_fallback_used"] is True
    assert close_event["round_trip_cost_provenance_status"] == (
        "FALLBACK_OR_INCOMPLETE_ENTRY_EXIT_COST_PROVENANCE"
    )


def test_multi_fill_partial_close_conserves_aggregated_entry_cost_basis() -> None:
    position = _position(quantity=4.0, entry_price=100.0)
    incoming_fill = _costed_fill(
        quantity=6.0,
        entry_price=200.0,
        fill_id="cost-basis-fill-two",
    )
    incoming = position_from_fill(
        incoming_fill,
        fill_id=str(incoming_fill["fill_id"]),
        side="long",
        quantity=6.0,
        price=200.0,
    )
    position.apply_same_side_fill(
        fill_id=str(incoming_fill["fill_id"]),
        quantity=6.0,
        price=200.0,
        incoming_position=incoming,
    )
    positions = {"BTCUSDT": position}

    close, _, blocked = lifecycle._close_position(
        positions=positions,
        symbol="BTCUSDT",
        close_quantity=5.0,
        exit_price=170.0,
        exit_time="2026-07-17T11:00:00Z",
        close_reason="UNIT_MULTI_FILL_PARTIAL",
        fee_bps=9.0,
        slippage_bps=7.0,
        exit_spread_bps=4.0,
        exit_spread_source="EXIT_MULTI_FILL_BOOK",
        exit_spread_available_at="2026-07-17T10:59:59Z",
    )

    assert blocked is None and close is not None
    assert position.avg_entry_price == pytest.approx(160.0)
    assert position.entry_fees_incurred_usd == pytest.approx(0.64)
    assert position.entry_slippage_incurred_usd == pytest.approx(0.48)
    assert close["entry_cost_allocation_fraction_of_pre_close_position"] == 0.5
    assert close["entry_fee_usd"] == pytest.approx(0.32)
    assert close["entry_slippage_usd"] == pytest.approx(0.24)
    assert position.entry_fees_remaining_usd == pytest.approx(0.32)
    assert position.entry_slippage_remaining_usd == pytest.approx(0.24)
    assert position.entry_fees_allocated_to_closes_usd == pytest.approx(0.32)
    assert position.entry_slippage_allocated_to_closes_usd == pytest.approx(0.24)


def test_trainer_loader_preserves_exact_zero_after_cost_outcome() -> None:
    row = {
        "realized_net_pnl_bps": 0.0,
        "realized_pnl_bps": 25.0,
        "realized_net_pnl_usd": 0.0,
        "realized_pnl_usd": 2.5,
        "directional_outcome": "FLAT",
        "selected_action": "long",
    }

    targets = V2HybridTrainerDataLoader._outcome_targets_from_row(row)

    assert targets["realized_net_pnl_bps"] == 0.0
    assert targets["realized_net_pnl_usd"] == 0.0
    assert targets["realized_after_cost_reward"] == 0.0
    assert targets["trade_outcome"] == "BREAKEVEN"
    assert V2HybridTrainerDataLoader._directional_label_bps_from_outcome(row) == 0.0


def test_failed_close_publication_does_not_consume_entry_cost_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    position = _position()
    positions = {"BTCUSDT": position}

    def reject_publication(close_event, outcome):
        return close_event, outcome, ["OUTCOME_AVAILABLE_AT_BEFORE_OUTCOME_GENERATED_AT"]

    monkeypatch.setattr(
        lifecycle,
        "capture_close_outcome_availability",
        reject_publication,
    )
    close_event, outcome, blocked = lifecycle._close_position(
        positions=positions,
        symbol="BTCUSDT",
        close_quantity=4.0,
        exit_price=105.0,
        exit_time="2026-07-17T10:30:00Z",
        close_reason="UNIT_REJECTED_PUBLICATION",
        fee_bps=9.0,
        slippage_bps=7.0,
        exit_spread_bps=6.0,
        exit_spread_source="EXIT_BOOK_REJECTED",
        exit_spread_available_at="2026-07-17T10:29:59Z",
    )

    assert close_event is None and outcome is None
    assert blocked is not None and blocked["paper_close_blocked"] is True
    assert position.net_quantity == pytest.approx(10.0)
    assert position.entry_fees_remaining_usd == pytest.approx(0.4)
    assert position.entry_slippage_remaining_usd == pytest.approx(0.3)
    assert position.entry_fees_allocated_to_closes_usd == pytest.approx(0.0)
    assert position.entry_slippage_allocated_to_closes_usd == pytest.approx(0.0)
