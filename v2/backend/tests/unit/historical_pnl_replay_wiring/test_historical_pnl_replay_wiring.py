from __future__ import annotations

from dataclasses import fields

import pytest

from v2.backend.app.composition.paper_execution_ledger.errors import (
    PaperExecutionLedgerCompositionError,
)
from v2.backend.app.composition.paper_mode.errors import (
    PaperModeRuntimeCompositionError,
)
from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.paper_mode import PAPER_MODE_PAPER, PaperModeFlag
from v2.backend.tests.unit.historical_pnl_replay_wiring.fixtures import (
    build_historical_pnl_replay_evidence_pack,
    build_ledger_clock,
    build_paper_mode_clock,
)
from v2.backend.tests.unit.historical_pnl_replay_wiring.harness import (
    HistoricalPnLReplayComparisonRecord,
    replay_historical_pnl_evidence_pack,
)


EXPECTED_SCENARIOS = (
    "historical_pnl_pack_btc_winner_long",
    "historical_pnl_pack_eth_winner_short",
    "historical_pnl_pack_lab_loser_short",
    "historical_pnl_pack_sol_orchestrator_held",
)
DISALLOWED_LINEAGE_FIELDS = frozenset({"shadow_decision_id", "execution_intent_id"})
DISALLOWED_MARKET_FIELDS = frozenset(
    {
        "pnl",
        "realized_pnl",
        "size",
        "quantity",
        "price",
        "fees",
        "slippage",
        "funding",
        "oi",
        "liquidation",
        "orderbook",
        "hedge_state",
        "residual_exposure",
        "squeeze_risk",
    }
)


def test_harness_emits_paper_mode_flag_with_live_blocked_true_and_mode_in_allowed_set() -> None:
    paper_mode_flag, _trios = _replay_pack()

    assert isinstance(paper_mode_flag, PaperModeFlag)
    assert paper_mode_flag.live_blocked is True
    assert paper_mode_flag.mode in {"paper", "live_blocked"}


def test_harness_emits_one_trio_per_scenario_in_input_order() -> None:
    _paper_mode_flag, trios = _replay_pack()

    assert len(trios) == 4
    assert tuple(trio.scenario_slug for trio in trios) == EXPECTED_SCENARIOS


def test_each_trio_has_three_comparison_records() -> None:
    _paper_mode_flag, trios = _replay_pack()

    assert all(len(trio.comparisons) == 3 for trio in trios)
    assert sum(len(trio.comparisons) for trio in trios) == 12


def test_each_comparison_carries_lineage_from_input_risk_decision_record() -> None:
    evidence_pack = build_historical_pnl_replay_evidence_pack()
    _paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)

    for trio, (_evidence_run, inputs) in zip(trios, evidence_pack):
        for comparison, replay_input in zip(trio.comparisons, inputs):
            entry = comparison.v2_paper_execution_ledger_entry
            decision = replay_input.risk_decision_record
            assert entry.risk_decision_id == decision.risk_decision_id
            assert entry.decision_id == decision.decision_id
            assert entry.prediction_id == decision.prediction_id
            assert entry.feature_snapshot_id == decision.feature_snapshot_id
            assert entry.symbol == decision.symbol


def test_each_comparison_pointer_matches_input_pointer() -> None:
    evidence_pack = build_historical_pnl_replay_evidence_pack()
    _paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)

    for trio, (_evidence_run, inputs) in zip(trios, evidence_pack):
        for comparison, replay_input in zip(trio.comparisons, inputs):
            assert (
                comparison.legacy_realized_trade_evidence_pointer
                == replay_input.legacy_realized_trade_evidence_pointer
            )


def test_lab_loser_scenario_uses_lab_hedge_unwind_pointer_literal() -> None:
    evidence_pack = build_historical_pnl_replay_evidence_pack()
    lab_run, lab_inputs = evidence_pack[2]

    assert lab_run.scenario_slug == "historical_pnl_pack_lab_loser_short"
    assert tuple(
        replay_input.legacy_realized_trade_evidence_pointer
        for replay_input in lab_inputs
    ) == (
        "legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_1",
        "legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_2",
        "legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_3",
    )


def test_live_blocked_is_true_on_every_paper_execution_ledger_entry() -> None:
    _paper_mode_flag, trios = _replay_pack()

    for trio in trios:
        for comparison in trio.comparisons:
            assert comparison.v2_paper_execution_ledger_entry.live_blocked is True


def test_input_risk_action_and_reason_carry_into_paper_execution_ledger_entry() -> None:
    evidence_pack = build_historical_pnl_replay_evidence_pack()
    _paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)

    for trio, (_evidence_run, inputs) in zip(trios, evidence_pack):
        for comparison, replay_input in zip(trio.comparisons, inputs):
            entry = comparison.v2_paper_execution_ledger_entry
            decision = replay_input.risk_decision_record
            assert entry.input_risk_action == decision.risk_action
            assert entry.input_risk_reason_code == decision.risk_reason_code


def test_evidence_run_symbol_matches_per_step_risk_decision_record_symbol() -> None:
    evidence_pack = build_historical_pnl_replay_evidence_pack()

    for evidence_run, inputs in evidence_pack:
        assert all(
            replay_input.risk_decision_record.symbol == evidence_run.symbol
            for replay_input in inputs
        )


def test_harness_does_not_emit_shadow_decision_id_or_execution_intent_id_or_paper_trade_id_lineage_row() -> None:
    records = _all_records_from_replay()

    for record in records:
        field_names = {field.name for field in fields(record)}
        assert field_names.isdisjoint(DISALLOWED_LINEAGE_FIELDS)
        if "paper_trade_id" in field_names:
            assert isinstance(record, PaperExecutionLedgerEntry)


def test_harness_does_not_introduce_pnl_or_size_or_price_or_fees_or_funding_field() -> None:
    records = _all_records_from_replay()

    for record in records:
        field_names = {field.name for field in fields(record)}
        assert field_names.isdisjoint(DISALLOWED_MARKET_FIELDS)


def test_harness_propagates_paper_mode_runtime_composition_error_unchanged() -> None:
    with pytest.raises(PaperModeRuntimeCompositionError) as exc_info:
        replay_historical_pnl_evidence_pack(
            evidence_pack=build_historical_pnl_replay_evidence_pack(),
            requested_mode=PAPER_MODE_PAPER,
            paper_mode_clock=123,
            ledger_clock=build_ledger_clock(),
        )

    assert exc_info.value.code == "must_be_callable"
    assert exc_info.value.field == "now_ms_clock"


def test_harness_propagates_paper_execution_ledger_composition_error_unchanged() -> None:
    with pytest.raises(PaperExecutionLedgerCompositionError) as exc_info:
        replay_historical_pnl_evidence_pack(
            evidence_pack=build_historical_pnl_replay_evidence_pack(),
            requested_mode=PAPER_MODE_PAPER,
            paper_mode_clock=build_paper_mode_clock(),
            ledger_clock=123,
        )

    assert exc_info.value.code == "must_be_callable"
    assert exc_info.value.field == "now_ms_clock"


def _replay_pack() -> tuple[PaperModeFlag, tuple]:
    return _replay_evidence_pack(build_historical_pnl_replay_evidence_pack())


def _replay_evidence_pack(evidence_pack: tuple) -> tuple[PaperModeFlag, tuple]:
    return replay_historical_pnl_evidence_pack(
        evidence_pack=evidence_pack,
        requested_mode=PAPER_MODE_PAPER,
        paper_mode_clock=build_paper_mode_clock(),
        ledger_clock=build_ledger_clock(),
    )


def _all_records_from_replay() -> tuple:
    paper_mode_flag, trios = _replay_pack()
    records = [paper_mode_flag]
    for trio in trios:
        records.append(trio.evidence_run)
        records.append(trio)
        records.extend(trio.comparisons)
        records.extend(
            comparison.v2_paper_execution_ledger_entry
            for comparison in trio.comparisons
        )
    assert all(
        isinstance(record, HistoricalPnLReplayComparisonRecord)
        or hasattr(record, "__dataclass_fields__")
        for record in records
    )
    return tuple(records)
