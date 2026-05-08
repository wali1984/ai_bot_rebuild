from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
    OrchestratorDecisionRecord,
)


BASE_TS_MS = 1_700_000_000_000
SHADOW_MODE_CLOCK_START_MS = BASE_TS_MS + 1_500_000
RISK_DECISION_CLOCK_START_MS = BASE_TS_MS + 1_800_000
LEGACY_ACTION_EVIDENCE_POINTER_PREFIX = (
    "claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md#shadow_"
)


@dataclass(frozen=True, slots=True)
class ShadowModeComparisonInput:
    orchestrator_decision: OrchestratorDecisionRecord
    legacy_action_evidence_pointer: str


EvidenceScenario = tuple[str, tuple[ShadowModeComparisonInput, ...]]


class _TestClock:
    __slots__ = ("_next_ms", "_step_ms")

    def __init__(self, *, start_ms: int, step_ms: int) -> None:
        self._next_ms = start_ms
        self._step_ms = step_ms

    def __call__(self) -> int:
        current_ms = self._next_ms
        self._next_ms = current_ms + self._step_ms
        return current_ms


def build_test_clock(start_ms: int, step_ms: int) -> Callable[[], int]:
    return _TestClock(start_ms=start_ms, step_ms=step_ms)


def build_shadow_mode_clock() -> Callable[[], int]:
    return build_test_clock(SHADOW_MODE_CLOCK_START_MS, 17)


def build_risk_decision_clock() -> Callable[[], int]:
    return build_test_clock(RISK_DECISION_CLOCK_START_MS, 19)


def shadow_mode_evidence_pack_btc_long() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="shadow_mode_evidence_pack_btc_long",
        scenario_index=0,
        symbol="BTCUSDT",
        decision_action=DECISION_ACTION_OPEN_LONG,
        decision_reason_code=DECISION_REASON_PROCEED_LONG,
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.75,
    )


def shadow_mode_evidence_pack_eth_short() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="shadow_mode_evidence_pack_eth_short",
        scenario_index=1,
        symbol="ETHUSDT",
        decision_action=DECISION_ACTION_OPEN_SHORT,
        decision_reason_code=DECISION_REASON_PROCEED_SHORT,
        input_prediction_direction="short",
        input_prediction_confidence_calibrated=0.75,
    )


def shadow_mode_evidence_pack_sol_held() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="shadow_mode_evidence_pack_sol_held",
        scenario_index=2,
        symbol="SOLUSDT",
        decision_action=DECISION_ACTION_HOLD,
        decision_reason_code=DECISION_REASON_HOLD_FLAT_DIRECTION,
        input_prediction_direction="flat",
        input_prediction_confidence_calibrated=0.50,
    )


def shadow_mode_evidence_pack_lab_abstained() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="shadow_mode_evidence_pack_lab_abstained",
        scenario_index=3,
        symbol="LABUSDT",
        decision_action=DECISION_ACTION_ABSTAIN,
        decision_reason_code=DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
        input_prediction_direction="long",
        input_prediction_confidence_calibrated=0.10,
    )


def build_shadow_mode_evidence_pack() -> tuple[EvidenceScenario, ...]:
    return (
        shadow_mode_evidence_pack_btc_long(),
        shadow_mode_evidence_pack_eth_short(),
        shadow_mode_evidence_pack_sol_held(),
        shadow_mode_evidence_pack_lab_abstained(),
    )


def _build_scenario(
    *,
    scenario_slug: str,
    scenario_index: int,
    symbol: str,
    decision_action: str,
    decision_reason_code: str,
    input_prediction_direction: str,
    input_prediction_confidence_calibrated: float,
) -> EvidenceScenario:
    inputs = tuple(
        _build_input(
            scenario_slug=scenario_slug,
            scenario_index=scenario_index,
            ordinal=ordinal,
            symbol=symbol,
            decision_action=decision_action,
            decision_reason_code=decision_reason_code,
            input_prediction_direction=input_prediction_direction,
            input_prediction_confidence_calibrated=input_prediction_confidence_calibrated,
        )
        for ordinal in range(1, 4)
    )
    return scenario_slug, inputs


def _build_input(
    *,
    scenario_slug: str,
    scenario_index: int,
    ordinal: int,
    symbol: str,
    decision_action: str,
    decision_reason_code: str,
    input_prediction_direction: str,
    input_prediction_confidence_calibrated: float,
) -> ShadowModeComparisonInput:
    ordinal_id = f"{ordinal:03d}"
    return ShadowModeComparisonInput(
        orchestrator_decision=OrchestratorDecisionRecord(
            decision_id=f"decision_{scenario_slug}_{ordinal_id}",
            prediction_id=f"prediction_{scenario_slug}_{ordinal_id}",
            feature_snapshot_id=f"feature_snapshot_{scenario_slug}_{ordinal_id}",
            symbol=symbol,
            decision_ts_ms=BASE_TS_MS + scenario_index * 60_000 + ordinal * 100,
            decision_action=decision_action,
            decision_reason_code=decision_reason_code,
            input_prediction_direction=input_prediction_direction,
            input_prediction_confidence_calibrated=input_prediction_confidence_calibrated,
            input_prediction_freshness_flag="fresh",
            input_worker_health_status="HEALTHY",
            live_blocked=True,
        ),
        legacy_action_evidence_pointer=(
            f"{LEGACY_ACTION_EVIDENCE_POINTER_PREFIX}{scenario_slug}_{ordinal_id}"
        ),
    )
