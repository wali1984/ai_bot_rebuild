from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from v2.backend.app.composition.paper_execution_ledger.runtime import (
    build_paper_execution_ledger_recorder,
)
from v2.backend.app.composition.paper_mode.runtime import build_paper_mode_runtime
from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.paper_mode import (
    PAPER_MODE_LIVE_BLOCKED,
    PAPER_MODE_PAPER,
    PaperModeFlag,
)
from v2.backend.tests.unit.historical_pnl_replay_wiring.fixtures import (
    HistoricalPnLEvidenceRun,
    HistoricalPnLReplayInput,
)


@dataclass(frozen=True, slots=True)
class HistoricalPnLReplayComparisonRecord:
    legacy_realized_trade_evidence_pointer: str
    v2_paper_execution_ledger_entry: PaperExecutionLedgerEntry


@dataclass(frozen=True, slots=True)
class HistoricalPnLReplayEvidenceTrio:
    scenario_slug: str
    evidence_run: HistoricalPnLEvidenceRun
    comparisons: tuple[HistoricalPnLReplayComparisonRecord, ...]


def replay_historical_pnl_evidence_pack(
    *,
    evidence_pack: tuple[
        tuple[HistoricalPnLEvidenceRun, tuple[HistoricalPnLReplayInput, ...]],
        ...,
    ],
    requested_mode: str,
    paper_mode_clock: Callable[[], int],
    ledger_clock: Callable[[], int],
) -> tuple[PaperModeFlag, tuple[HistoricalPnLReplayEvidenceTrio, ...]]:
    paper_mode_runtime = build_paper_mode_runtime(now_ms_clock=paper_mode_clock)
    paper_mode_flag = paper_mode_runtime.paper_mode_now(requested_mode=requested_mode)
    assert paper_mode_flag.live_blocked is True
    assert paper_mode_flag.mode in {PAPER_MODE_PAPER, PAPER_MODE_LIVE_BLOCKED}

    ledger_recorder = build_paper_execution_ledger_recorder(
        now_ms_clock=ledger_clock,
    )

    trios: list[HistoricalPnLReplayEvidenceTrio] = []
    for evidence_run, inputs in evidence_pack:
        comparisons = tuple(
            HistoricalPnLReplayComparisonRecord(
                legacy_realized_trade_evidence_pointer=(
                    replay_input.legacy_realized_trade_evidence_pointer
                ),
                v2_paper_execution_ledger_entry=ledger_recorder(
                    decision=replay_input.risk_decision_record,
                ),
            )
            for replay_input in inputs
        )
        trios.append(
            HistoricalPnLReplayEvidenceTrio(
                scenario_slug=evidence_run.scenario_slug,
                evidence_run=evidence_run,
                comparisons=comparisons,
            )
        )

    return paper_mode_flag, tuple(trios)
