from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun, ReplayBacktestStep, ReplayBacktestSummary
from v2.backend.app.services.replay_backtest_runner import assemble_replay_backtest_step, assemble_replay_backtest_summary

from .errors import ReplayBacktestRunnerCompositionError


class ReplayBacktestRunner:
    __slots__ = ("assemble_step", "assemble_summary")

    def __init__(
        self,
        *,
        assemble_step: Callable[..., ReplayBacktestStep],
        assemble_summary: Callable[..., ReplayBacktestSummary],
    ) -> None:
        self.assemble_step = assemble_step
        self.assemble_summary = assemble_summary


def build_replay_backtest_runner(
    *,
    now_ms_clock: Callable[[], int],
) -> ReplayBacktestRunner:
    if not callable(now_ms_clock):
        raise ReplayBacktestRunnerCompositionError(
            "must_be_callable",
            field="now_ms_clock",
        )

    _now_ms_clock = now_ms_clock

    def _assemble_step(
        *,
        paper_ledger_entry: PaperExecutionLedgerEntry,
        replay_run: ReplayBacktestRun,
    ) -> ReplayBacktestStep:
        return assemble_replay_backtest_step(paper_ledger_entry=paper_ledger_entry, replay_run=replay_run, now_ms_clock=_now_ms_clock)

    def _assemble_summary(
        *,
        replay_run: ReplayBacktestRun,
        steps: tuple[ReplayBacktestStep, ...],
    ) -> ReplayBacktestSummary:
        return assemble_replay_backtest_summary(replay_run=replay_run, steps=steps, now_ms_clock=_now_ms_clock)

    return ReplayBacktestRunner(
        assemble_step=_assemble_step,
        assemble_summary=_assemble_summary,
    )
