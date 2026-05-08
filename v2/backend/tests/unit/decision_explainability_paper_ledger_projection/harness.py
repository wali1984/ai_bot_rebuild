from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.composition.paper_execution_ledger.runtime import (
    build_paper_execution_ledger_recorder,
)
from v2.backend.app.domain.paper_execution_ledger import PaperExecutionLedgerEntry
from v2.backend.tests.unit.decision_explainability_paper_ledger_projection.fixtures import (
    PaperLedgerExplainabilityFixtureInput,
    build_paper_ledger_clock,
)


@dataclass(frozen=True, slots=True)
class PaperLedgerExplainabilityEnvelope:
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    ledger_entry_ts_ms: int
    ledger_action: str
    ledger_reason_code: str
    input_risk_action: str
    input_risk_reason_code: str
    live_blocked: bool
    legacy_evidence_pointer: str
    source_scenario_slug: str
    step_index: int


@dataclass(frozen=True, slots=True)
class PaperLedgerExplainabilityHarnessResult:
    envelopes: tuple[PaperLedgerExplainabilityEnvelope, ...]
    ledger_entries: tuple[PaperExecutionLedgerEntry, ...]


def decision_explainability_paper_ledger_projection_harness(
    inputs: tuple[PaperLedgerExplainabilityFixtureInput, ...],
) -> PaperLedgerExplainabilityHarnessResult:
    paper_execution_ledger_recorder = build_paper_execution_ledger_recorder(
        now_ms_clock=build_paper_ledger_clock()
    )
    ledger_entries = tuple(
        paper_execution_ledger_recorder(decision=input_row.risk_decision_record)
        for input_row in inputs
    )
    envelopes = tuple(
        _project_envelope(input_row=input_row, ledger_entry=ledger_entry)
        for input_row, ledger_entry in zip(inputs, ledger_entries, strict=True)
    )
    return PaperLedgerExplainabilityHarnessResult(
        envelopes=envelopes,
        ledger_entries=ledger_entries,
    )


def _project_envelope(
    *,
    input_row: PaperLedgerExplainabilityFixtureInput,
    ledger_entry: PaperExecutionLedgerEntry,
) -> PaperLedgerExplainabilityEnvelope:
    return PaperLedgerExplainabilityEnvelope(
        paper_trade_id=ledger_entry.paper_trade_id,
        risk_decision_id=ledger_entry.risk_decision_id,
        decision_id=ledger_entry.decision_id,
        prediction_id=ledger_entry.prediction_id,
        feature_snapshot_id=ledger_entry.feature_snapshot_id,
        symbol=ledger_entry.symbol,
        ledger_entry_ts_ms=ledger_entry.ledger_entry_ts_ms,
        ledger_action=ledger_entry.ledger_action,
        ledger_reason_code=ledger_entry.ledger_reason_code,
        input_risk_action=ledger_entry.input_risk_action,
        input_risk_reason_code=ledger_entry.input_risk_reason_code,
        live_blocked=ledger_entry.live_blocked,
        legacy_evidence_pointer=input_row.legacy_evidence_pointer,
        source_scenario_slug=input_row.scenario_slug,
        step_index=input_row.step_index,
    )
