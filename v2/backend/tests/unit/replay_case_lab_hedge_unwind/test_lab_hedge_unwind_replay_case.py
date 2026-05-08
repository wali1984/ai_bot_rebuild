from __future__ import annotations

import pytest

from v2.backend.app.composition.replay_backtest_runner import build_replay_backtest_runner
from v2.backend.tests.unit.replay_case_lab_hedge_unwind.fixtures import (
    build_block_hedge_close_outcome,
    build_close_short_outcome,
    build_keep_hedge_outcome,
    build_legacy_outcome,
    build_reduce_short_outcome,
    build_test_clock,
)


_STEP_REASON_BY_LEDGER_REASON = {
    "mirror_allow_proceed_long": "step_mirror_allow_proceed_long",
    "mirror_allow_proceed_short": "step_mirror_allow_proceed_short",
    "mirror_deny_orchestrator_held": "step_mirror_deny_orchestrator_held",
    "mirror_deny_default": "step_mirror_deny_default",
}
_STEP_ACTION_BY_LEDGER_ACTION = {
    "record_allow": "step_record_allow",
    "record_deny": "step_record_deny",
}
_OUTCOME_BUILDERS = (
    build_legacy_outcome,
    build_keep_hedge_outcome,
    build_close_short_outcome,
    build_reduce_short_outcome,
    build_block_hedge_close_outcome,
)


@pytest.mark.parametrize(
    ("outcome_builder", "expected_allow_count", "expected_deny_count"),
    (
        (build_legacy_outcome, 3, 0),
        (build_keep_hedge_outcome, 2, 1),
        (build_close_short_outcome, 3, 0),
        (build_reduce_short_outcome, 3, 0),
        (build_block_hedge_close_outcome, 2, 1),
    ),
)
def test_lab_hedge_unwind_replay_case_records_typed_mirror_sequence(
    outcome_builder,
    expected_allow_count,
    expected_deny_count,
):
    replay_run, paper_ledger_entries = outcome_builder()
    steps, summary = _run_case(replay_run, paper_ledger_entries)

    assert replay_run.live_blocked is True
    assert len(steps) == 3
    for paper_ledger_entry, step in zip(paper_ledger_entries, steps, strict=True):
        assert paper_ledger_entry.live_blocked is True
        assert step.live_blocked is True
        assert step.replay_run_id == replay_run.replay_run_id
        assert step.paper_trade_id == paper_ledger_entry.paper_trade_id
        assert step.risk_decision_id == paper_ledger_entry.risk_decision_id
        assert step.decision_id == paper_ledger_entry.decision_id
        assert step.prediction_id == paper_ledger_entry.prediction_id
        assert step.feature_snapshot_id == paper_ledger_entry.feature_snapshot_id
        assert step.symbol == "LABUSDT"
        assert step.input_paper_action == paper_ledger_entry.ledger_action
        assert step.input_paper_reason_code == paper_ledger_entry.ledger_reason_code
        assert step.step_action == _STEP_ACTION_BY_LEDGER_ACTION[
            paper_ledger_entry.ledger_action
        ]
        assert step.step_reason_code == _STEP_REASON_BY_LEDGER_REASON[
            paper_ledger_entry.ledger_reason_code
        ]

    assert summary.live_blocked is True
    assert summary.replay_run_id == replay_run.replay_run_id
    assert summary.total_steps_count == 3
    assert summary.record_allow_steps_count == expected_allow_count
    assert summary.record_deny_steps_count == expected_deny_count


def test_lab_hedge_unwind_legacy_replay_case_records_typed_mirror_sequence():
    replay_run, paper_ledger_entries = build_legacy_outcome()
    steps, summary = _run_case(replay_run, paper_ledger_entries)

    assert _ledger_projection(paper_ledger_entries) == (
        ("record_allow", "mirror_allow_proceed_short"),
        ("record_allow", "mirror_allow_proceed_long"),
        ("record_allow", "mirror_allow_proceed_long"),
    )
    assert tuple(step.step_action for step in steps) == (
        "step_record_allow",
        "step_record_allow",
        "step_record_allow",
    )
    assert summary.record_allow_steps_count == 3
    assert summary.record_deny_steps_count == 0


def test_lab_hedge_unwind_keep_hedge_replay_case_records_typed_mirror_sequence():
    replay_run, paper_ledger_entries = build_keep_hedge_outcome()
    steps, summary = _run_case(replay_run, paper_ledger_entries)

    assert _ledger_projection(paper_ledger_entries) == (
        ("record_allow", "mirror_allow_proceed_short"),
        ("record_allow", "mirror_allow_proceed_long"),
        ("record_deny", "mirror_deny_orchestrator_held"),
    )
    assert steps[2].step_action == "step_record_deny"
    assert steps[2].step_reason_code == "step_mirror_deny_orchestrator_held"
    assert summary.record_allow_steps_count == 2
    assert summary.record_deny_steps_count == 1


def test_lab_hedge_unwind_close_short_replay_case_records_typed_mirror_sequence():
    replay_run, paper_ledger_entries = build_close_short_outcome()
    steps, summary = _run_case(replay_run, paper_ledger_entries)

    assert _ledger_projection(paper_ledger_entries) == (
        ("record_allow", "mirror_allow_proceed_short"),
        ("record_allow", "mirror_allow_proceed_long"),
        ("record_allow", "mirror_allow_proceed_short"),
    )
    assert steps[2].step_reason_code == "step_mirror_allow_proceed_short"
    assert summary.record_allow_steps_count == 3
    assert summary.record_deny_steps_count == 0


def test_lab_hedge_unwind_reduce_short_replay_case_records_typed_mirror_sequence():
    replay_run, paper_ledger_entries = build_reduce_short_outcome()
    steps, summary = _run_case(replay_run, paper_ledger_entries)

    assert _ledger_projection(paper_ledger_entries) == (
        ("record_allow", "mirror_allow_proceed_short"),
        ("record_allow", "mirror_allow_proceed_long"),
        ("record_allow", "mirror_allow_proceed_short"),
    )
    assert steps[2].step_reason_code == "step_mirror_allow_proceed_short"
    assert summary.record_allow_steps_count == 3
    assert summary.record_deny_steps_count == 0


def test_lab_hedge_unwind_block_hedge_close_replay_case_records_typed_mirror_sequence():
    replay_run, paper_ledger_entries = build_block_hedge_close_outcome()
    steps, summary = _run_case(replay_run, paper_ledger_entries)

    assert _ledger_projection(paper_ledger_entries) == (
        ("record_allow", "mirror_allow_proceed_short"),
        ("record_allow", "mirror_allow_proceed_long"),
        ("record_deny", "mirror_deny_default"),
    )
    assert steps[2].step_action == "step_record_deny"
    assert steps[2].step_reason_code == "step_mirror_deny_default"
    assert summary.record_allow_steps_count == 2
    assert summary.record_deny_steps_count == 1


def test_lab_hedge_unwind_outcomes_have_distinct_replay_run_ids():
    replay_run_ids = tuple(
        outcome_builder()[0].replay_run_id for outcome_builder in _OUTCOME_BUILDERS
    )

    assert len(set(replay_run_ids)) == 5


def test_lab_hedge_unwind_outcomes_have_distinct_paper_trade_ids():
    paper_trade_ids = tuple(
        paper_ledger_entry.paper_trade_id
        for outcome_builder in _OUTCOME_BUILDERS
        for paper_ledger_entry in outcome_builder()[1]
    )

    assert len(paper_trade_ids) == 15
    assert len(set(paper_trade_ids)) == 15


def test_lab_hedge_unwind_close_short_and_reduce_short_have_identical_typed_mirror_sequences():
    _, close_short_entries = build_close_short_outcome()
    _, reduce_short_entries = build_reduce_short_outcome()

    assert _typed_mirror_sequence(close_short_entries) == _typed_mirror_sequence(
        reduce_short_entries
    )


def test_lab_hedge_unwind_legacy_outcome_records_close_as_mirror_allow_proceed_long():
    _, paper_ledger_entries = build_legacy_outcome()

    assert paper_ledger_entries[2].ledger_action == "record_allow"
    assert paper_ledger_entries[2].ledger_reason_code == "mirror_allow_proceed_long"


def test_lab_hedge_unwind_block_hedge_close_outcome_records_third_step_as_mirror_deny_default():
    _, paper_ledger_entries = build_block_hedge_close_outcome()

    assert paper_ledger_entries[2].ledger_action == "record_deny"
    assert paper_ledger_entries[2].ledger_reason_code == "mirror_deny_default"


def _run_case(replay_run, paper_ledger_entries):
    test_clock = build_test_clock(start_ms=1_700_000_000_010, step_ms=1_000)
    runner = build_replay_backtest_runner(now_ms_clock=test_clock)
    steps = tuple(
        runner.assemble_step(
            paper_ledger_entry=paper_ledger_entry,
            replay_run=replay_run,
        )
        for paper_ledger_entry in paper_ledger_entries
    )
    summary = runner.assemble_summary(replay_run=replay_run, steps=steps)
    return steps, summary


def _ledger_projection(paper_ledger_entries):
    return tuple(
        (paper_ledger_entry.ledger_action, paper_ledger_entry.ledger_reason_code)
        for paper_ledger_entry in paper_ledger_entries
    )


def _typed_mirror_sequence(paper_ledger_entries):
    return tuple(
        (
            paper_ledger_entry.ledger_action,
            paper_ledger_entry.ledger_reason_code,
            paper_ledger_entry.input_risk_action,
            paper_ledger_entry.input_risk_reason_code,
        )
        for paper_ledger_entry in paper_ledger_entries
    )
