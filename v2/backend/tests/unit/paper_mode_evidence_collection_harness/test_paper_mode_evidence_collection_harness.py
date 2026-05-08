from __future__ import annotations

from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_ACTION_RECORD_ALLOW,
    PAPER_LEDGER_ACTION_RECORD_DENY,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    PaperExecutionLedgerEntry,
)
from v2.backend.app.domain.paper_mode import (
    PAPER_MODE_LIVE_BLOCKED,
    PAPER_MODE_PAPER,
    PaperModeFlag,
)
from v2.backend.app.domain.replay_backtest_runner import (
    STEP_ACTION_RECORD_ALLOW,
    STEP_ACTION_RECORD_DENY,
    STEP_REASON_MIRROR_ALLOW_PROCEED_LONG,
    STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    STEP_REASON_MIRROR_DENY_DEFAULT,
    STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
    STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    ReplayBacktestRun,
    ReplayBacktestStep,
    ReplayBacktestSummary,
)
from v2.backend.tests.unit.paper_mode_evidence_collection_harness.fixtures import (
    PAPER_MODE_CLOCK_START_MS,
    build_paper_mode_clock,
    build_paper_mode_evidence_pack,
    build_replay_clock,
)
from v2.backend.tests.unit.paper_mode_evidence_collection_harness.harness import (
    PaperModeEvidenceTrio,
    replay_paper_mode_evidence_pack,
)


EXPECTED_STEP_COUNTS = (3, 3, 2, 2, 2)
EXPECTED_REASON_COUNTS = (
    (3, 0, 3, 0, 0, 0, 0),
    (3, 0, 0, 3, 0, 0, 0),
    (0, 2, 0, 0, 2, 0, 0),
    (0, 2, 0, 0, 0, 2, 0),
    (0, 2, 0, 0, 0, 0, 2),
)
LEDGER_REASON_TO_STEP_PROJECTION = {
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG: (
        STEP_ACTION_RECORD_ALLOW,
        STEP_REASON_MIRROR_ALLOW_PROCEED_LONG,
    ),
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT: (
        STEP_ACTION_RECORD_ALLOW,
        STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    ),
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD: (
        STEP_ACTION_RECORD_DENY,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    ),
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED: (
        STEP_ACTION_RECORD_DENY,
        STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
    ),
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT: (
        STEP_ACTION_RECORD_DENY,
        STEP_REASON_MIRROR_DENY_DEFAULT,
    ),
}
DISALLOWED_ATTRIBUTES = (
    "shadow_decision_id",
    "execution_intent_id",
    "pnl",
    "realized_pnl",
    "unrealized_pnl",
    "position_size",
    "quantity",
    "price",
    "fees",
    "slippage",
    "funding",
    "oi",
    "open_interest",
    "liquidation_map",
    "orderbook_depth",
    "hedge_state",
    "residual_exposure",
    "squeeze_risk",
)


def test_paper_mode_evidence_pack_emits_paper_mode_flag() -> None:
    paper_mode_flag, _trios = _replay_pack(PAPER_MODE_PAPER)

    assert isinstance(paper_mode_flag, PaperModeFlag)
    assert paper_mode_flag.mode == PAPER_MODE_PAPER
    assert paper_mode_flag.live_blocked is True
    assert paper_mode_flag.flag_emitted_ts_ms == PAPER_MODE_CLOCK_START_MS


def test_paper_mode_evidence_pack_emits_live_blocked_flag_under_live_blocked_request() -> None:
    paper_mode_flag, _trios = _replay_pack(PAPER_MODE_LIVE_BLOCKED)

    assert paper_mode_flag.mode == PAPER_MODE_LIVE_BLOCKED
    assert paper_mode_flag.live_blocked is True


def test_paper_mode_evidence_pack_emits_one_trio_per_scenario() -> None:
    _paper_mode_flag, trios = _replay_pack(PAPER_MODE_PAPER)

    assert len(trios) == 5
    assert all(isinstance(trio, PaperModeEvidenceTrio) for trio in trios)


def test_paper_mode_evidence_pack_step_counts_match_per_scenario() -> None:
    _paper_mode_flag, trios = _replay_pack(PAPER_MODE_PAPER)

    assert tuple(len(trio.steps) for trio in trios) == EXPECTED_STEP_COUNTS
    assert sum(len(trio.steps) for trio in trios) == 12


def test_paper_mode_evidence_pack_lineage_carry_over() -> None:
    evidence_pack = build_paper_mode_evidence_pack()
    _paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)

    for trio, (replay_run, ledger_entries) in zip(trios, evidence_pack):
        assert trio.replay_run == replay_run
        for step, entry in zip(trio.steps, ledger_entries):
            assert step.feature_snapshot_id == entry.feature_snapshot_id
            assert step.prediction_id == entry.prediction_id
            assert step.decision_id == entry.decision_id
            assert step.risk_decision_id == entry.risk_decision_id
            assert step.paper_trade_id == entry.paper_trade_id
            assert step.replay_run_id == replay_run.replay_run_id
            assert step.symbol == entry.symbol


def test_paper_mode_evidence_pack_typed_action_reason_projection() -> None:
    evidence_pack = build_paper_mode_evidence_pack()
    _paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)

    for trio, (_replay_run, ledger_entries) in zip(trios, evidence_pack):
        for step, entry in zip(trio.steps, ledger_entries):
            expected_action, expected_reason = LEDGER_REASON_TO_STEP_PROJECTION[
                entry.ledger_reason_code
            ]
            assert step.step_action == expected_action
            assert step.step_reason_code == expected_reason
            assert step.input_paper_action == entry.ledger_action
            assert step.input_paper_reason_code == entry.ledger_reason_code


def test_paper_mode_evidence_pack_live_blocked_invariant_on_every_record() -> None:
    evidence_pack = build_paper_mode_evidence_pack()
    paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)

    assert paper_mode_flag.live_blocked is True
    for trio, (replay_run, ledger_entries) in zip(trios, evidence_pack):
        assert replay_run.live_blocked is True
        assert trio.replay_run.live_blocked is True
        assert trio.summary.live_blocked is True
        for entry in ledger_entries:
            assert entry.live_blocked is True
        for step in trio.steps:
            assert step.live_blocked is True


def test_paper_mode_evidence_pack_per_scenario_summary_aggregation() -> None:
    _paper_mode_flag, trios = _replay_pack(PAPER_MODE_PAPER)

    for trio, expected_counts in zip(trios, EXPECTED_REASON_COUNTS):
        (
            allow_count,
            deny_count,
            allow_long_count,
            allow_short_count,
            deny_held_count,
            deny_abstained_count,
            deny_default_count,
        ) = expected_counts
        assert trio.summary.replay_run_id == trio.replay_run.replay_run_id
        assert trio.summary.total_steps_count == allow_count + deny_count
        assert trio.summary.record_allow_steps_count == allow_count
        assert trio.summary.record_deny_steps_count == deny_count
        assert trio.summary.mirror_allow_proceed_long_steps_count == allow_long_count
        assert trio.summary.mirror_allow_proceed_short_steps_count == allow_short_count
        assert trio.summary.mirror_deny_orchestrator_held_steps_count == deny_held_count
        assert (
            trio.summary.mirror_deny_orchestrator_abstained_steps_count
            == deny_abstained_count
        )
        assert trio.summary.mirror_deny_default_steps_count == deny_default_count


def test_paper_mode_evidence_pack_distinct_replay_run_ids() -> None:
    _paper_mode_flag, trios = _replay_pack(PAPER_MODE_PAPER)
    replay_run_ids = tuple(trio.replay_run.replay_run_id for trio in trios)

    assert len(set(replay_run_ids)) == len(replay_run_ids)


def test_paper_mode_evidence_pack_distinct_paper_trade_ids() -> None:
    _paper_mode_flag, trios = _replay_pack(PAPER_MODE_PAPER)
    paper_trade_ids = tuple(
        step.paper_trade_id for trio in trios for step in trio.steps
    )

    assert len(paper_trade_ids) == 12
    assert len(set(paper_trade_ids)) == len(paper_trade_ids)


def test_paper_mode_evidence_pack_no_disallowed_lineage_rows() -> None:
    evidence_pack = build_paper_mode_evidence_pack()
    paper_mode_flag, trios = _replay_evidence_pack(evidence_pack)
    records = [paper_mode_flag]

    for replay_run, ledger_entries in evidence_pack:
        records.append(replay_run)
        records.extend(ledger_entries)
    for trio in trios:
        records.append(trio.replay_run)
        records.extend(trio.steps)
        records.append(trio.summary)

    assert all(isinstance(record, _ALLOWED_RECORD_TYPES) for record in records)
    for record in records:
        for attribute in DISALLOWED_ATTRIBUTES:
            assert not hasattr(record, attribute)


def test_paper_mode_evidence_pack_propagates_paper_mode_runtime_composition_error() -> None:
    try:
        replay_paper_mode_evidence_pack(
            evidence_pack=build_paper_mode_evidence_pack(),
            requested_mode=PAPER_MODE_PAPER,
            paper_mode_clock=123,
            replay_clock=build_replay_clock(),
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "PaperModeRuntimeCompositionError"
        assert exc.code == "must_be_callable"
        assert exc.field == "now_ms_clock"
    else:
        raise AssertionError("PaperModeRuntimeCompositionError was not raised")


def test_paper_mode_evidence_pack_propagates_replay_backtest_runner_composition_error() -> None:
    try:
        replay_paper_mode_evidence_pack(
            evidence_pack=build_paper_mode_evidence_pack(),
            requested_mode=PAPER_MODE_PAPER,
            paper_mode_clock=build_paper_mode_clock(),
            replay_clock=123,
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "ReplayBacktestRunnerCompositionError"
        assert exc.code == "must_be_callable"
        assert exc.field == "now_ms_clock"
    else:
        raise AssertionError("ReplayBacktestRunnerCompositionError was not raised")


_ALLOWED_RECORD_TYPES = (
    PaperModeFlag,
    ReplayBacktestRun,
    ReplayBacktestStep,
    ReplayBacktestSummary,
    PaperExecutionLedgerEntry,
)


def _replay_pack(
    requested_mode: str,
) -> tuple[PaperModeFlag, tuple[PaperModeEvidenceTrio, ...]]:
    return _replay_evidence_pack(
        build_paper_mode_evidence_pack(),
        requested_mode=requested_mode,
    )


def _replay_evidence_pack(
    evidence_pack: tuple[
        tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]], ...
    ],
    requested_mode: str = PAPER_MODE_PAPER,
) -> tuple[PaperModeFlag, tuple[PaperModeEvidenceTrio, ...]]:
    return replay_paper_mode_evidence_pack(
        evidence_pack=evidence_pack,
        requested_mode=requested_mode,
        paper_mode_clock=build_paper_mode_clock(),
        replay_clock=build_replay_clock(),
    )
