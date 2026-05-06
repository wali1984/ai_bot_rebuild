from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.services.paper_execution_ledger import assemble_paper_execution_ledger_entry

from .errors import PaperExecutionLedgerCompositionError


PaperExecutionLedgerRecorder = Callable[..., PaperExecutionLedgerEntry]


def build_paper_execution_ledger_recorder(
    *,
    now_ms_clock: Callable[[], int],
) -> PaperExecutionLedgerRecorder:
    if not callable(now_ms_clock):
        raise PaperExecutionLedgerCompositionError("must_be_callable", field="now_ms_clock")

    _now_ms_clock = now_ms_clock

    def _recorder(*, decision: RiskDecisionRecord) -> PaperExecutionLedgerEntry:
        return assemble_paper_execution_ledger_entry(decision=decision, now_ms_clock=_now_ms_clock)

    return _recorder
