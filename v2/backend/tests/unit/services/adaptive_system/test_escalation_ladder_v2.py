from __future__ import annotations

from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import (
    LADDER,
    PROHIBITED_TERMINAL_RESPONSES,
    decide,
)


def test_no_trigger_is_healthy_no_action():
    d = decide(conditions={})
    assert d.triggered is False
    assert d.next_action is None
    assert d.validate() == []


def test_negative_edge_triggers_first_ladder_step():
    d = decide(conditions={"negative_after_cost_edge": True})
    assert d.triggered is True
    assert d.interpretation == "CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE"
    assert d.next_action == LADDER[0]
    assert d.is_operator_gated_stop is False
    assert d.validate() == []


def test_zero_fills_triggers_escalation_not_terminal():
    d = decide(conditions={"zero_fills": True, "corpus_stagnation": True})
    assert d.triggered is True
    assert d.next_action in LADDER
    # never a prohibited terminal response
    for bad in PROHIBITED_TERMINAL_RESPONSES:
        assert bad not in d.interpretation
        assert bad not in (d.next_action or "")


def test_exhausted_steps_advance_the_ladder():
    exhausted = {LADDER[0], LADDER[1]}
    d = decide(conditions={"negative_after_cost_edge": True}, exhausted_steps=exhausted)
    assert d.next_action == LADDER[2]


def test_unavailable_step_is_skipped_not_terminal():
    d = decide(
        conditions={"admission_starved": True},
        controllable_available={LADDER[0]: False, LADDER[1]: False},
    )
    assert d.next_action == LADDER[2]
    assert d.is_operator_gated_stop is False


def test_all_exhausted_with_external_blocker_is_operator_gated():
    d = decide(
        conditions={"corpus_stagnation": True},
        exhausted_steps=set(LADDER),
        external_blocker="missing_operator_credential",
    )
    assert d.is_operator_gated_stop is True
    assert d.external_blocker == "missing_operator_credential"
    assert d.interpretation == "CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE"
    assert d.validate() == []


def test_all_exhausted_without_external_blocker_reenters_ladder():
    d = decide(conditions={"negative_after_cost_edge": True}, exhausted_steps=set(LADDER))
    # never terminal: re-enters at recalibration
    assert d.is_operator_gated_stop is False
    assert d.next_action == LADDER[0]


def test_operator_gated_stop_requires_real_external_blocker():
    # a bogus external blocker name must fail validation
    d = decide(
        conditions={"zero_fills": True},
        exhausted_steps=set(LADDER),
        external_blocker="i_gave_up",
    )
    # decide() only sets stop for known kinds, so this falls through to re-enter
    assert d.is_operator_gated_stop is False
    assert d.next_action == LADDER[0]


def test_prohibited_terminal_responses_never_valid():
    # sanity: the validator would reject a hand-built prohibited response
    from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import EscalationDecision

    bad = EscalationDecision(
        triggered=True,
        interpretation="EXTERNAL_MARKET_OPPORTUNITY_PENDING",
        next_action=None,
        ladder_step_index=None,
        rationale="x",
        is_operator_gated_stop=False,
        external_blocker=None,
    )
    reasons = bad.validate()
    assert any("PROHIBITED_TERMINAL_RESPONSE_EMITTED" in r for r in reasons)
