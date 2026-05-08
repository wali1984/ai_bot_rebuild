from __future__ import annotations

from dataclasses import fields

from v2.backend.app.domain.orchestrator_decision import OrchestratorDecisionRecord
from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)
from v2.backend.app.domain.shadow_mode_readiness import (
    SHADOW_MODE_NOT_READY,
    SHADOW_MODE_READY,
    ShadowModeReadinessFlag,
)
from v2.backend.tests.unit.shadow_mode_evidence_collection_harness.fixtures import (
    LEGACY_ACTION_EVIDENCE_POINTER_PREFIX,
    SHADOW_MODE_CLOCK_START_MS,
    EvidenceScenario,
    ShadowModeComparisonInput,
    build_risk_decision_clock,
    build_shadow_mode_clock,
    build_shadow_mode_evidence_pack,
)
from v2.backend.tests.unit.shadow_mode_evidence_collection_harness.harness import (
    ShadowModeComparisonRecord,
    ShadowModeEvidenceTrio,
    replay_shadow_mode_evidence_pack,
)


EXPECTED_STEP_COUNTS = (3, 3, 3, 3)
EXPECTED_RISK_PROJECTION = {
    "open_long": (
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    ),
    "open_short": (
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    ),
    "hold": (
        RISK_DECISION_ACTION_DENY,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    ),
    "abstain": (
        RISK_DECISION_ACTION_DENY,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    ),
}
DISALLOWED_ATTRIBUTES = (
    "shadow_decision_id",
    "execution_intent_id",
    "paper_trade_id",
)


def test_evidence_pack_scenario_count_is_four() -> None:
    assert len(build_shadow_mode_evidence_pack()) == 4


def test_evidence_pack_total_input_step_count_is_twelve() -> None:
    evidence_pack = build_shadow_mode_evidence_pack()

    assert sum(len(inputs) for _scenario_slug, inputs in evidence_pack) == 12
    assert all(
        isinstance(comparison_input.orchestrator_decision, OrchestratorDecisionRecord)
        for _scenario_slug, inputs in evidence_pack
        for comparison_input in inputs
    )


def test_evidence_pack_per_scenario_step_counts() -> None:
    evidence_pack = build_shadow_mode_evidence_pack()

    assert tuple(len(inputs) for _scenario_slug, inputs in evidence_pack) == EXPECTED_STEP_COUNTS


def test_evidence_pack_lineage_id_namespacing() -> None:
    for scenario_slug, inputs in build_shadow_mode_evidence_pack():
        for ordinal, comparison_input in enumerate(inputs, start=1):
            ordinal_id = f"{ordinal:03d}"
            decision = comparison_input.orchestrator_decision

            assert decision.decision_id == f"decision_{scenario_slug}_{ordinal_id}"
            assert decision.prediction_id == f"prediction_{scenario_slug}_{ordinal_id}"
            assert (
                decision.feature_snapshot_id
                == f"feature_snapshot_{scenario_slug}_{ordinal_id}"
            )


def test_evidence_pack_legacy_action_evidence_pointer_namespacing() -> None:
    for scenario_slug, inputs in build_shadow_mode_evidence_pack():
        for ordinal, comparison_input in enumerate(inputs, start=1):
            ordinal_id = f"{ordinal:03d}"

            assert comparison_input.legacy_action_evidence_pointer == (
                f"{LEGACY_ACTION_EVIDENCE_POINTER_PREFIX}{scenario_slug}_{ordinal_id}"
            )


def test_evidence_pack_uniform_live_blocked() -> None:
    assert all(
        comparison_input.orchestrator_decision.live_blocked is True
        for _scenario_slug, inputs in build_shadow_mode_evidence_pack()
        for comparison_input in inputs
    )


def test_harness_returns_ready_flag_when_requested_ready() -> None:
    shadow_mode_readiness_flag, _trios = _replay_pack(SHADOW_MODE_READY)

    assert isinstance(shadow_mode_readiness_flag, ShadowModeReadinessFlag)
    assert shadow_mode_readiness_flag.state == SHADOW_MODE_READY
    assert shadow_mode_readiness_flag.live_blocked is True
    assert shadow_mode_readiness_flag.flag_emitted_ts_ms == SHADOW_MODE_CLOCK_START_MS


def test_harness_returns_not_ready_flag_when_requested_not_ready() -> None:
    shadow_mode_readiness_flag, trios = _replay_pack(SHADOW_MODE_NOT_READY)

    assert shadow_mode_readiness_flag.state == SHADOW_MODE_NOT_READY
    assert shadow_mode_readiness_flag.live_blocked is True
    assert len(trios) == 4
    assert sum(len(trio.comparisons) for trio in trios) == 12


def test_harness_produces_one_trio_per_scenario_with_twelve_total_comparisons() -> None:
    _shadow_mode_readiness_flag, trios = _replay_pack(SHADOW_MODE_READY)

    assert len(trios) == 4
    assert all(isinstance(trio, ShadowModeEvidenceTrio) for trio in trios)
    assert sum(len(trio.comparisons) for trio in trios) == 12


def test_harness_lineage_carry_over() -> None:
    evidence_pack = build_shadow_mode_evidence_pack()
    _shadow_mode_readiness_flag, trios = _replay_evidence_pack(evidence_pack)

    for trio, (scenario_slug, inputs) in zip(trios, evidence_pack):
        assert trio.scenario_slug == scenario_slug
        assert trio.inputs == inputs
        for comparison, comparison_input in zip(trio.comparisons, inputs):
            decision = comparison_input.orchestrator_decision
            risk_decision = comparison.v2_risk_decision_record

            assert risk_decision.decision_id == decision.decision_id
            assert risk_decision.prediction_id == decision.prediction_id
            assert risk_decision.feature_snapshot_id == decision.feature_snapshot_id
            assert risk_decision.symbol == decision.symbol
            assert risk_decision.risk_decision_id == "rd_" + decision.decision_id


def test_harness_risk_action_and_reason_per_decision_action() -> None:
    _shadow_mode_readiness_flag, trios = _replay_pack(SHADOW_MODE_READY)

    for trio in trios:
        for comparison, comparison_input in zip(trio.comparisons, trio.inputs):
            decision = comparison_input.orchestrator_decision
            expected_action, expected_reason = EXPECTED_RISK_PROJECTION[
                decision.decision_action
            ]
            risk_decision = comparison.v2_risk_decision_record

            assert risk_decision.risk_action == expected_action
            assert risk_decision.risk_reason_code == expected_reason
            assert risk_decision.input_decision_action == decision.decision_action
            assert (
                risk_decision.input_decision_reason_code
                == decision.decision_reason_code
            )


def test_harness_comparison_record_pairs_legacy_pointer_with_v2_risk_decision_record() -> None:
    _shadow_mode_readiness_flag, trios = _replay_pack(SHADOW_MODE_READY)

    for trio in trios:
        for comparison, comparison_input in zip(trio.comparisons, trio.inputs):
            assert isinstance(comparison.v2_risk_decision_record, RiskDecisionRecord)
            assert (
                comparison.legacy_action_evidence_pointer
                == comparison_input.legacy_action_evidence_pointer
            )
            assert comparison.v2_risk_decision_record.decision_id == (
                comparison_input.orchestrator_decision.decision_id
            )


def test_harness_no_shadow_decision_id_field_introduced() -> None:
    assert {field.name for field in fields(ShadowModeComparisonRecord)} == {
        "legacy_action_evidence_pointer",
        "v2_risk_decision_record",
    }

    for record_type in (
        ShadowModeComparisonRecord,
        ShadowModeComparisonInput,
        ShadowModeEvidenceTrio,
    ):
        for attribute in DISALLOWED_ATTRIBUTES:
            assert not hasattr(record_type, attribute)


def _replay_pack(
    requested_state: str,
) -> tuple[ShadowModeReadinessFlag, tuple[ShadowModeEvidenceTrio, ...]]:
    return _replay_evidence_pack(
        build_shadow_mode_evidence_pack(),
        requested_state=requested_state,
    )


def _replay_evidence_pack(
    evidence_pack: tuple[EvidenceScenario, ...],
    requested_state: str = SHADOW_MODE_READY,
) -> tuple[ShadowModeReadinessFlag, tuple[ShadowModeEvidenceTrio, ...]]:
    return replay_shadow_mode_evidence_pack(
        evidence_pack=evidence_pack,
        requested_state=requested_state,
        shadow_mode_clock=build_shadow_mode_clock(),
        risk_decision_clock=build_risk_decision_clock(),
    )
