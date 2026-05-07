from __future__ import annotations

from collections.abc import Callable

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
from .errors import ReplayBacktestRunnerServiceError


def assemble_replay_backtest_step(
    *,
    paper_ledger_entry: PaperExecutionLedgerEntry,
    replay_run: ReplayBacktestRun,
    now_ms_clock: Callable[[], int],
) -> ReplayBacktestStep:
    if not isinstance(paper_ledger_entry, PaperExecutionLedgerEntry):
        raise ReplayBacktestRunnerServiceError(
            "must_be_paper_execution_ledger_entry",
            field="paper_ledger_entry",
        )
    if not isinstance(replay_run, ReplayBacktestRun):
        raise ReplayBacktestRunnerServiceError(
            "must_be_replay_backtest_run",
            field="replay_run",
        )
    if not callable(now_ms_clock):
        raise ReplayBacktestRunnerServiceError(
            "must_be_callable",
            field="now_ms_clock",
        )

    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise ReplayBacktestRunnerServiceError(
            "must_be_int",
            field="now_ms_clock",
        )
    if now_ms < 0:
        raise ReplayBacktestRunnerServiceError(
            "must_be_nonnegative",
            field="now_ms_clock",
        )
    if now_ms < replay_run.run_started_ts_ms:
        raise ReplayBacktestRunnerServiceError(
            "must_be_at_or_after_run_started_ts_ms",
            field="now_ms_clock",
        )
    if paper_ledger_entry.symbol != replay_run.symbol:
        raise ReplayBacktestRunnerServiceError(
            "paper_ledger_entry_symbol_must_match_replay_run_symbol",
            field="paper_ledger_entry.symbol",
        )
    if len(paper_ledger_entry.paper_trade_id) > 122:
        raise ReplayBacktestRunnerServiceError(
            "paper_trade_id_too_long_for_replay_step_id_derivation",
            field="paper_ledger_entry.paper_trade_id",
        )

    if (
        paper_ledger_entry.ledger_reason_code
        == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG
    ):
        step_action = STEP_ACTION_RECORD_ALLOW
        step_reason_code = STEP_REASON_MIRROR_ALLOW_PROCEED_LONG
    elif (
        paper_ledger_entry.ledger_reason_code
        == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT
    ):
        step_action = STEP_ACTION_RECORD_ALLOW
        step_reason_code = STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT
    elif (
        paper_ledger_entry.ledger_reason_code
        == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
    ):
        step_action = STEP_ACTION_RECORD_DENY
        step_reason_code = STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
    elif (
        paper_ledger_entry.ledger_reason_code
        == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
    ):
        step_action = STEP_ACTION_RECORD_DENY
        step_reason_code = STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
    elif paper_ledger_entry.ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT:
        step_action = STEP_ACTION_RECORD_DENY
        step_reason_code = STEP_REASON_MIRROR_DENY_DEFAULT
    else:
        raise ReplayBacktestRunnerServiceError(
            "unrecognized_paper_ledger_reason_code",
            field="paper_ledger_entry.ledger_reason_code",
        )

    replay_step_id = "rstep_" + paper_ledger_entry.paper_trade_id
    return ReplayBacktestStep(
        replay_step_id=replay_step_id,
        replay_run_id=replay_run.replay_run_id,
        paper_trade_id=paper_ledger_entry.paper_trade_id,
        risk_decision_id=paper_ledger_entry.risk_decision_id,
        decision_id=paper_ledger_entry.decision_id,
        prediction_id=paper_ledger_entry.prediction_id,
        feature_snapshot_id=paper_ledger_entry.feature_snapshot_id,
        symbol=paper_ledger_entry.symbol,
        step_ts_ms=now_ms,
        step_action=step_action,
        step_reason_code=step_reason_code,
        input_paper_action=paper_ledger_entry.ledger_action,
        input_paper_reason_code=paper_ledger_entry.ledger_reason_code,
        live_blocked=True,
    )


def assemble_replay_backtest_summary(
    *,
    replay_run: ReplayBacktestRun,
    steps: tuple[ReplayBacktestStep, ...],
    now_ms_clock: Callable[[], int],
) -> ReplayBacktestSummary:
    if not isinstance(replay_run, ReplayBacktestRun):
        raise ReplayBacktestRunnerServiceError(
            "must_be_replay_backtest_run",
            field="replay_run",
        )
    if type(steps) is not tuple:
        raise ReplayBacktestRunnerServiceError("must_be_tuple", field="steps")

    for index in range(len(steps)):
        if not isinstance(steps[index], ReplayBacktestStep):
            raise ReplayBacktestRunnerServiceError(
                "must_be_replay_backtest_step",
                field=f"steps[{index}]",
            )
    for index in range(len(steps)):
        if steps[index].replay_run_id != replay_run.replay_run_id:
            raise ReplayBacktestRunnerServiceError(
                "step_replay_run_id_must_match_replay_run_id",
                field=f"steps[{index}].replay_run_id",
            )

    if not callable(now_ms_clock):
        raise ReplayBacktestRunnerServiceError(
            "must_be_callable",
            field="now_ms_clock",
        )

    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise ReplayBacktestRunnerServiceError(
            "must_be_int",
            field="now_ms_clock",
        )
    if now_ms < 0:
        raise ReplayBacktestRunnerServiceError(
            "must_be_nonnegative",
            field="now_ms_clock",
        )
    if now_ms < replay_run.run_started_ts_ms:
        raise ReplayBacktestRunnerServiceError(
            "must_be_at_or_after_run_started_ts_ms",
            field="now_ms_clock",
        )
    if len(replay_run.replay_run_id) > 123:
        raise ReplayBacktestRunnerServiceError(
            "replay_run_id_too_long_for_replay_summary_id_derivation",
            field="replay_run.replay_run_id",
        )

    total_steps_count = len(steps)
    record_allow_steps_count = 0
    record_deny_steps_count = 0
    mirror_allow_proceed_long_steps_count = 0
    mirror_allow_proceed_short_steps_count = 0
    mirror_deny_orchestrator_held_steps_count = 0
    mirror_deny_orchestrator_abstained_steps_count = 0
    mirror_deny_default_steps_count = 0

    for step in steps:
        if step.step_action == STEP_ACTION_RECORD_ALLOW:
            record_allow_steps_count += 1
        elif step.step_action == STEP_ACTION_RECORD_DENY:
            record_deny_steps_count += 1

        if step.step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_LONG:
            mirror_allow_proceed_long_steps_count += 1
        elif step.step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT:
            mirror_allow_proceed_short_steps_count += 1
        elif step.step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD:
            mirror_deny_orchestrator_held_steps_count += 1
        elif step.step_reason_code == STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED:
            mirror_deny_orchestrator_abstained_steps_count += 1
        elif step.step_reason_code == STEP_REASON_MIRROR_DENY_DEFAULT:
            mirror_deny_default_steps_count += 1

    replay_summary_id = "rsum_" + replay_run.replay_run_id
    return ReplayBacktestSummary(
        replay_summary_id=replay_summary_id,
        replay_run_id=replay_run.replay_run_id,
        summary_emitted_ts_ms=now_ms,
        total_steps_count=total_steps_count,
        record_allow_steps_count=record_allow_steps_count,
        record_deny_steps_count=record_deny_steps_count,
        mirror_allow_proceed_long_steps_count=mirror_allow_proceed_long_steps_count,
        mirror_allow_proceed_short_steps_count=mirror_allow_proceed_short_steps_count,
        mirror_deny_orchestrator_held_steps_count=mirror_deny_orchestrator_held_steps_count,
        mirror_deny_orchestrator_abstained_steps_count=mirror_deny_orchestrator_abstained_steps_count,
        mirror_deny_default_steps_count=mirror_deny_default_steps_count,
        live_blocked=True,
    )
