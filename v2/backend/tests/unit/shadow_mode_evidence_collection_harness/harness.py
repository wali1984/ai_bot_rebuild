from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from v2.backend.app.composition.risk_gateway.runtime import build_risk_decision_evaluator
from v2.backend.app.composition.shadow_mode_readiness.runtime import (
    build_shadow_mode_readiness_runtime,
)
from v2.backend.app.domain.risk_gateway import RiskDecisionRecord
from v2.backend.app.domain.shadow_mode_readiness import (
    SHADOW_MODE_NOT_READY,
    SHADOW_MODE_READY,
    ShadowModeReadinessFlag,
)
from v2.backend.tests.unit.shadow_mode_evidence_collection_harness.fixtures import (
    ShadowModeComparisonInput,
)


@dataclass(frozen=True, slots=True)
class ShadowModeComparisonRecord:
    legacy_action_evidence_pointer: str
    v2_risk_decision_record: RiskDecisionRecord


@dataclass(frozen=True, slots=True)
class ShadowModeEvidenceTrio:
    scenario_slug: str
    inputs: tuple[ShadowModeComparisonInput, ...]
    comparisons: tuple[ShadowModeComparisonRecord, ...]


def replay_shadow_mode_evidence_pack(
    *,
    evidence_pack: tuple[tuple[str, tuple[ShadowModeComparisonInput, ...]], ...],
    requested_state: str,
    shadow_mode_clock: Callable[[], int],
    risk_decision_clock: Callable[[], int],
) -> tuple[ShadowModeReadinessFlag, tuple[ShadowModeEvidenceTrio, ...]]:
    shadow_mode_runtime = build_shadow_mode_readiness_runtime(
        now_ms_clock=shadow_mode_clock,
    )
    assert shadow_mode_runtime is not None

    shadow_mode_readiness_flag = shadow_mode_runtime.shadow_mode_readiness_now(
        requested_state=requested_state,
    )
    assert shadow_mode_readiness_flag.live_blocked is True
    assert shadow_mode_readiness_flag.state in {SHADOW_MODE_NOT_READY, SHADOW_MODE_READY}

    risk_decision_evaluator = build_risk_decision_evaluator(
        now_ms_clock=risk_decision_clock,
    )
    assert risk_decision_evaluator is not None

    trios: list[ShadowModeEvidenceTrio] = []
    for scenario_slug, inputs in evidence_pack:
        comparisons = tuple(
            ShadowModeComparisonRecord(
                legacy_action_evidence_pointer=comparison_input.legacy_action_evidence_pointer,
                v2_risk_decision_record=risk_decision_evaluator(
                    decision=comparison_input.orchestrator_decision,
                ),
            )
            for comparison_input in inputs
        )
        trios.append(
            ShadowModeEvidenceTrio(
                scenario_slug=scenario_slug,
                inputs=inputs,
                comparisons=comparisons,
            )
        )

    return shadow_mode_readiness_flag, tuple(trios)
