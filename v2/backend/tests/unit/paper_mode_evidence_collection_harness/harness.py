from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from v2.backend.app.composition.paper_mode.runtime import build_paper_mode_runtime
from v2.backend.app.composition.replay_backtest_runner.runtime import (
    build_replay_backtest_runner,
)
from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.paper_mode import (
    PAPER_MODE_LIVE_BLOCKED,
    PAPER_MODE_PAPER,
    PaperModeFlag,
)
from v2.backend.app.domain.replay_backtest_runner import (
    ReplayBacktestRun,
    ReplayBacktestStep,
    ReplayBacktestSummary,
)


@dataclass(frozen=True, slots=True)
class PaperModeEvidenceTrio:
    replay_run: ReplayBacktestRun
    steps: tuple[ReplayBacktestStep, ...]
    summary: ReplayBacktestSummary


def replay_paper_mode_evidence_pack(
    *,
    evidence_pack: tuple[tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]], ...],
    requested_mode: str,
    paper_mode_clock: Callable[[], int],
    replay_clock: Callable[[], int],
) -> tuple[PaperModeFlag, tuple[PaperModeEvidenceTrio, ...]]:
    paper_mode_runtime = build_paper_mode_runtime(now_ms_clock=paper_mode_clock)
    replay_runner = build_replay_backtest_runner(now_ms_clock=replay_clock)

    paper_mode_flag = paper_mode_runtime.paper_mode_now(requested_mode=requested_mode)
    assert paper_mode_flag.live_blocked is True
    assert paper_mode_flag.mode in {PAPER_MODE_PAPER, PAPER_MODE_LIVE_BLOCKED}

    trios: list[PaperModeEvidenceTrio] = []
    for replay_run, ledger_entries in evidence_pack:
        steps = tuple(
            replay_runner.assemble_step(
                paper_ledger_entry=ledger_entry,
                replay_run=replay_run,
            )
            for ledger_entry in ledger_entries
        )
        summary = replay_runner.assemble_summary(replay_run=replay_run, steps=steps)
        trios.append(
            PaperModeEvidenceTrio(
                replay_run=replay_run,
                steps=steps,
                summary=summary,
            )
        )

    return paper_mode_flag, tuple(trios)
