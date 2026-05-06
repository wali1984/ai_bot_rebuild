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
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)
from .errors import PaperExecutionLedgerServiceError


def assemble_paper_execution_ledger_entry(
    *,
    decision: RiskDecisionRecord,
    now_ms_clock: Callable[[], int],
) -> PaperExecutionLedgerEntry:
    if not isinstance(decision, RiskDecisionRecord):
        raise PaperExecutionLedgerServiceError(
            "must_be_risk_decision_record",
            field="decision",
        )
    if not callable(now_ms_clock):
        raise PaperExecutionLedgerServiceError(
            "must_be_callable",
            field="now_ms_clock",
        )

    now_ms = now_ms_clock()
    if type(now_ms) is not int:
        raise PaperExecutionLedgerServiceError(
            "must_be_int",
            field="now_ms_clock",
        )
    if now_ms < 0:
        raise PaperExecutionLedgerServiceError(
            "must_be_nonnegative",
            field="now_ms_clock",
        )
    if len(decision.risk_decision_id) > 125:
        raise PaperExecutionLedgerServiceError(
            "risk_decision_id_too_long_for_paper_trade_id_derivation",
            field="decision.risk_decision_id",
        )

    if decision.risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_LONG:
        ledger_action = PAPER_LEDGER_ACTION_RECORD_ALLOW
        ledger_reason_code = PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG
    elif decision.risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_SHORT:
        ledger_action = PAPER_LEDGER_ACTION_RECORD_ALLOW
        ledger_reason_code = PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT
    elif decision.risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD:
        ledger_action = PAPER_LEDGER_ACTION_RECORD_DENY
        ledger_reason_code = PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD
    elif decision.risk_reason_code == RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED:
        ledger_action = PAPER_LEDGER_ACTION_RECORD_DENY
        ledger_reason_code = PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED
    elif decision.risk_reason_code == RISK_DECISION_REASON_DENY_DEFAULT:
        ledger_action = PAPER_LEDGER_ACTION_RECORD_DENY
        ledger_reason_code = PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT
    else:
        raise PaperExecutionLedgerServiceError(
            "unrecognized_risk_reason_code",
            field="decision.risk_reason_code",
        )

    return PaperExecutionLedgerEntry(
        paper_trade_id="pt_" + decision.risk_decision_id,
        risk_decision_id=decision.risk_decision_id,
        decision_id=decision.decision_id,
        prediction_id=decision.prediction_id,
        feature_snapshot_id=decision.feature_snapshot_id,
        symbol=decision.symbol,
        ledger_entry_ts_ms=now_ms,
        ledger_action=ledger_action,
        ledger_reason_code=ledger_reason_code,
        input_risk_action=decision.risk_action,
        input_risk_reason_code=decision.risk_reason_code,
        live_blocked=True,
    )
