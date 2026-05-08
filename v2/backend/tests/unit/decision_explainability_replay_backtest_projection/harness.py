from __future__ import annotations

from dataclasses import dataclass

from v2.backend.app.composition.paper_execution_ledger.runtime import (
    build_paper_execution_ledger_recorder,
)
from v2.backend.app.composition.replay_backtest_runner.runtime import (
    build_replay_backtest_runner,
)
from v2.backend.app.domain.replay_backtest_runner import (
    RUN_MODE_REPLAY,
    ReplayBacktestRun,
    ReplayBacktestStep,
    ReplayBacktestSummary,
)
from v2.backend.tests.unit.decision_explainability_replay_backtest_projection.fixtures import (
    BASE_RISK_TS_MS,
    SCENARIO_SLUG_ORDER,
    ReplayBacktestStepExplainabilityFixtureInput,
    build_paper_ledger_clock,
    build_replay_backtest_explainability_fixture_inputs,
    build_replay_clock,
    build_summary_pointer,
)


@dataclass(frozen=True)
class ReplayBacktestStepExplainabilityEnvelope:
    replay_step_id: str
    replay_run_id: str
    paper_trade_id: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    step_ts_ms: int
    step_action: str
    step_reason_code: str
    input_paper_action: str
    input_paper_reason_code: str
    live_blocked: bool
    source_scenario_slug: str
    step_index: int
    legacy_evidence_pointer: str


@dataclass(frozen=True)
class ReplayBacktestSummaryExplainabilityEnvelope:
    replay_summary_id: str
    replay_run_id: str
    summary_emitted_ts_ms: int
    total_steps_count: int
    record_allow_steps_count: int
    record_deny_steps_count: int
    mirror_allow_proceed_long_steps_count: int
    mirror_allow_proceed_short_steps_count: int
    mirror_deny_orchestrator_held_steps_count: int
    mirror_deny_orchestrator_abstained_steps_count: int
    mirror_deny_default_steps_count: int
    live_blocked: bool
    source_scenario_slug: str
    legacy_evidence_pointer: str


@dataclass(frozen=True)
class ReplayBacktestProjectionHarnessResult:
    step_envelopes: tuple[ReplayBacktestStepExplainabilityEnvelope, ...]
    summary_envelopes: tuple[ReplayBacktestSummaryExplainabilityEnvelope, ...]


def run_replay_backtest_projection_harness() -> ReplayBacktestProjectionHarnessResult:
    input_rows = build_replay_backtest_explainability_fixture_inputs()
    paper_recorder = build_paper_execution_ledger_recorder(
        now_ms_clock=build_paper_ledger_clock()
    )
    runner = build_replay_backtest_runner(now_ms_clock=build_replay_clock())

    step_envelopes: list[ReplayBacktestStepExplainabilityEnvelope] = []
    summary_envelopes: list[ReplayBacktestSummaryExplainabilityEnvelope] = []

    for scenario_index, scenario_slug in enumerate(SCENARIO_SLUG_ORDER):
        scenario_rows = tuple(
            row for row in input_rows if row.source_scenario_slug == scenario_slug
        )
        replay_run = ReplayBacktestRun(
            replay_run_id=f"rr_2t_{scenario_index}",
            run_mode=RUN_MODE_REPLAY,
            symbol=scenario_rows[0].symbol,
            run_started_ts_ms=BASE_RISK_TS_MS + scenario_index * 60_000,
            run_ended_ts_ms=BASE_RISK_TS_MS + scenario_index * 60_000 + 1_000,
            live_blocked=True,
        )
        steps: list[ReplayBacktestStep] = []

        for input_row in scenario_rows:
            ledger_entry = paper_recorder(decision=input_row.risk_decision_record)
            step = runner.assemble_step(
                paper_ledger_entry=ledger_entry,
                replay_run=replay_run,
            )
            steps.append(step)
            step_envelopes.append(
                _project_step_to_envelope(input_row=input_row, step=step)
            )

        summary = runner.assemble_summary(
            replay_run=replay_run,
            steps=tuple(steps),
        )
        summary_envelopes.append(
            _project_summary_to_envelope(
                summary=summary,
                source_scenario_slug=scenario_slug,
                legacy_evidence_pointer=build_summary_pointer(
                    scenario_slug=scenario_slug
                ),
            )
        )

    return ReplayBacktestProjectionHarnessResult(
        step_envelopes=tuple(step_envelopes),
        summary_envelopes=tuple(summary_envelopes),
    )


def _project_step_to_envelope(
    *,
    input_row: ReplayBacktestStepExplainabilityFixtureInput,
    step: ReplayBacktestStep,
) -> ReplayBacktestStepExplainabilityEnvelope:
    return ReplayBacktestStepExplainabilityEnvelope(
        replay_step_id=step.replay_step_id,
        replay_run_id=step.replay_run_id,
        paper_trade_id=step.paper_trade_id,
        risk_decision_id=step.risk_decision_id,
        decision_id=step.decision_id,
        prediction_id=step.prediction_id,
        feature_snapshot_id=step.feature_snapshot_id,
        symbol=step.symbol,
        step_ts_ms=step.step_ts_ms,
        step_action=step.step_action,
        step_reason_code=step.step_reason_code,
        input_paper_action=step.input_paper_action,
        input_paper_reason_code=step.input_paper_reason_code,
        live_blocked=step.live_blocked,
        source_scenario_slug=input_row.source_scenario_slug,
        step_index=input_row.step_index,
        legacy_evidence_pointer=input_row.legacy_evidence_pointer,
    )


def _project_summary_to_envelope(
    *,
    summary: ReplayBacktestSummary,
    source_scenario_slug: str,
    legacy_evidence_pointer: str,
) -> ReplayBacktestSummaryExplainabilityEnvelope:
    return ReplayBacktestSummaryExplainabilityEnvelope(
        replay_summary_id=summary.replay_summary_id,
        replay_run_id=summary.replay_run_id,
        summary_emitted_ts_ms=summary.summary_emitted_ts_ms,
        total_steps_count=summary.total_steps_count,
        record_allow_steps_count=summary.record_allow_steps_count,
        record_deny_steps_count=summary.record_deny_steps_count,
        mirror_allow_proceed_long_steps_count=(
            summary.mirror_allow_proceed_long_steps_count
        ),
        mirror_allow_proceed_short_steps_count=(
            summary.mirror_allow_proceed_short_steps_count
        ),
        mirror_deny_orchestrator_held_steps_count=(
            summary.mirror_deny_orchestrator_held_steps_count
        ),
        mirror_deny_orchestrator_abstained_steps_count=(
            summary.mirror_deny_orchestrator_abstained_steps_count
        ),
        mirror_deny_default_steps_count=summary.mirror_deny_default_steps_count,
        live_blocked=summary.live_blocked,
        source_scenario_slug=source_scenario_slug,
        legacy_evidence_pointer=legacy_evidence_pointer,
    )
