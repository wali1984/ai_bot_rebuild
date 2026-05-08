from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.composition.paper_mode.runtime import build_paper_mode_runtime
from v2.backend.app.domain.paper_mode.flag import PaperModeFlag
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.tests.unit.decision_explainability_data_contract.fixtures import (
    DecisionExplainabilityFixtureInput,
    build_paper_mode_clock,
)


@dataclass(frozen=True, slots=True)
class DecisionExplainabilityEnvelope:
    feature_snapshot_id: str
    prediction_id: str
    decision_id: str
    risk_decision_id: str
    symbol: str
    input_decision_action: str
    input_decision_reason_code: str
    risk_action: str
    risk_reason_code: str
    risk_live_blocked: bool
    risk_decision_ts_ms: int
    paper_mode_live_blocked: bool
    paper_mode_mode: str
    legacy_evidence_pointer: str
    source_scenario_slug: str
    step_index: int


@dataclass(frozen=True, slots=True)
class DecisionExplainabilityHarnessResult:
    paper_mode_flag: PaperModeFlag
    envelopes: tuple[DecisionExplainabilityEnvelope, ...]


def decision_explainability_data_contract_harness(
    inputs: tuple[DecisionExplainabilityFixtureInput, ...],
) -> DecisionExplainabilityHarnessResult:
    paper_mode_runtime = build_paper_mode_runtime(now_ms_clock=build_paper_mode_clock())
    paper_mode_flag = paper_mode_runtime.paper_mode_now(requested_mode="paper")
    assert paper_mode_flag.live_blocked is True
    assert paper_mode_flag.mode in {"paper", "live_blocked"}

    envelopes = tuple(
        _project_envelope(input_row=input_row, paper_mode_flag=paper_mode_flag)
        for input_row in inputs
    )
    return DecisionExplainabilityHarnessResult(
        paper_mode_flag=paper_mode_flag,
        envelopes=envelopes,
    )


def _project_envelope(
    *,
    input_row: DecisionExplainabilityFixtureInput,
    paper_mode_flag: PaperModeFlag,
) -> DecisionExplainabilityEnvelope:
    record: RiskDecisionRecord = input_row.risk_decision_record
    return DecisionExplainabilityEnvelope(
        feature_snapshot_id=record.feature_snapshot_id,
        prediction_id=record.prediction_id,
        decision_id=record.decision_id,
        risk_decision_id=record.risk_decision_id,
        symbol=record.symbol,
        input_decision_action=record.input_decision_action,
        input_decision_reason_code=record.input_decision_reason_code,
        risk_action=record.risk_action,
        risk_reason_code=record.risk_reason_code,
        risk_live_blocked=record.live_blocked,
        risk_decision_ts_ms=record.risk_decision_ts_ms,
        paper_mode_live_blocked=paper_mode_flag.live_blocked,
        paper_mode_mode=paper_mode_flag.mode,
        legacy_evidence_pointer=input_row.legacy_evidence_pointer,
        source_scenario_slug=input_row.scenario_slug,
        step_index=input_row.step_index,
    )
END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/harness.py
