"""Adaptation escalation state machine — FINAL PASS Phase 10 / task FP-110.

Encodes the guiding principle: a lack of profitable edge is NEVER a terminal
market classification. It is a failure signal that deterministically selects the
next controllable escalation action (recalibrate → incremental train → rebuild
features → horizon/symbol/regime challengers → alternative architectures →
alternative strategy families → hedged/relative-value → increase bounded
exploration → promote a superior challenger).

The prohibited terminal responses are impossible to emit here:

    NO_POSITIVE_EDGE_FOUND
    EXTERNAL_MARKET_OPPORTUNITY_PENDING
    LEAVE_STACK_RUNNING

While ANY controllable escalation step remains un-exhausted, ``decide`` returns
that step. It returns an operator-gated stop ONLY when every controllable step is
exhausted AND the sole remaining blocker is genuinely external (missing operator
credential, proven provider outage, catastrophic-safety boundary) — and even then
it is classified as CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE, not a market verdict.

This module never relaxes the catastrophic-safety envelope.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

SCHEMA_VERSION = "adaptation_escalation_ladder_v2"

# Ordered controllable escalation ladder (FINAL PASS Phase 10, steps 1-10).
LADDER = (
    "RECALIBRATE_CURRENT_MODELS",
    "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES",
    "REBUILD_FEATURE_SELECTION_OR_REPRESENTATION",
    "TRAIN_HORIZON_SPECIFIC_CHALLENGERS",
    "TRAIN_SYMBOL_OR_REGIME_SPECIFIC_CHALLENGERS",
    "TRAIN_ALTERNATIVE_MODEL_ARCHITECTURES",
    "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES",
    "TRAIN_HEDGED_AND_RELATIVE_VALUE_POLICIES",
    "INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION",
    "PROMOTE_SUPERIOR_CHALLENGER",
)

# Trigger conditions (Phase 10 + operator item 7: corpus stagnation).
TRIGGER_CONDITIONS = (
    "negative_after_cost_edge",
    "admission_starved",
    "persistent_flat_without_information_gain",
    "calibration_degraded",
    "regime_shifted",
    "candidate_false_negative_rate_rising",
    "zero_fills",
    "corpus_stagnation",
)

PROHIBITED_TERMINAL_RESPONSES = (
    "NO_POSITIVE_EDGE_FOUND",
    "EXTERNAL_MARKET_OPPORTUNITY_PENDING",
    "LEAVE_STACK_RUNNING",
)

# External blockers that only the operator/infra can clear. Even when all
# controllable steps are exhausted, these are NOT market verdicts.
EXTERNAL_BLOCKER_KINDS = (
    "missing_operator_credential",
    "proven_provider_outage",
    "explicit_reboot_required",
    "catastrophic_safety_boundary",
)


@dataclass(frozen=True)
class EscalationDecision:
    triggered: bool
    interpretation: str
    next_action: str | None
    ladder_step_index: int | None
    rationale: str
    is_operator_gated_stop: bool
    external_blocker: str | None
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> list[str]:
        r: list[str] = []
        if self.next_action is not None and self.next_action not in LADDER:
            r.append(f"NEXT_ACTION_NOT_IN_LADDER:{self.next_action}")
        # The prohibited terminal strings may never appear as an interpretation/action.
        for token in (self.interpretation, self.next_action or "", self.rationale):
            for bad in PROHIBITED_TERMINAL_RESPONSES:
                if bad in str(token):
                    r.append(f"PROHIBITED_TERMINAL_RESPONSE_EMITTED:{bad}")
        # An operator-gated stop must name a genuine external blocker.
        if self.is_operator_gated_stop and self.external_blocker not in EXTERNAL_BLOCKER_KINDS:
            r.append("OPERATOR_GATED_STOP_WITHOUT_EXTERNAL_BLOCKER")
        # If not a stop and triggered, a controllable next action is required.
        if self.triggered and not self.is_operator_gated_stop and self.next_action is None:
            r.append("TRIGGERED_WITHOUT_NEXT_ACTION")
        return r


def decide(
    *,
    conditions: Mapping[str, bool],
    exhausted_steps: set[str] | frozenset[str] | None = None,
    controllable_available: Mapping[str, bool] | None = None,
    external_blocker: str | None = None,
) -> EscalationDecision:
    """Return the next escalation action for the current adaptation state.

    conditions: subset of TRIGGER_CONDITIONS -> True when detected.
    exhausted_steps: ladder steps already attempted this cycle with no remaining
        controllable work (e.g. no new matured outcomes to incrementally train on).
    controllable_available: optional gating of specific steps by resource
        availability (e.g. {"TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES": False}
        when no new labels exist yet). A step whose availability is explicitly
        False is treated as not-yet-actionable and skipped (but NOT terminal).
    external_blocker: when every controllable step is exhausted/unavailable AND a
        genuine external blocker remains, name it (one of EXTERNAL_BLOCKER_KINDS).
    """
    exhausted = set(exhausted_steps or set())
    available = dict(controllable_available or {})

    triggered = any(bool(conditions.get(c)) for c in TRIGGER_CONDITIONS)

    if not triggered:
        return EscalationDecision(
            triggered=False,
            interpretation="POLICY_HEALTHY_CONTINUE_EXPLOITATION_AND_MONITORING",
            next_action=None,
            ladder_step_index=None,
            rationale="No adaptation trigger condition detected.",
            is_operator_gated_stop=False,
            external_blocker=None,
        )

    # Walk the ladder for the first step that is neither exhausted nor explicitly
    # unavailable. Availability defaults to True (actionable) when unspecified.
    for idx, step in enumerate(LADDER):
        if step in exhausted:
            continue
        if available.get(step, True) is False:
            continue
        active = sorted(c for c in TRIGGER_CONDITIONS if conditions.get(c))
        return EscalationDecision(
            triggered=True,
            interpretation="CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE",
            next_action=step,
            ladder_step_index=idx,
            rationale=f"Trigger(s) {active} -> next controllable ladder action.",
            is_operator_gated_stop=False,
            external_blocker=None,
        )

    # Every controllable step is exhausted/unavailable. This is NOT a market
    # verdict. It is a policy failure that is gated on an external dependency.
    if external_blocker in EXTERNAL_BLOCKER_KINDS:
        return EscalationDecision(
            triggered=True,
            interpretation="CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE",
            next_action=None,
            ladder_step_index=None,
            rationale=(
                "All controllable escalation steps exhausted/unavailable; "
                f"remaining blocker is external: {external_blocker}."
            ),
            is_operator_gated_stop=True,
            external_blocker=external_blocker,
        )

    # No external blocker named but ladder exhausted: loop back to recalibration
    # rather than emit a terminal 'no edge' classification (never terminal).
    return EscalationDecision(
        triggered=True,
        interpretation="CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE",
        next_action=LADDER[0],
        ladder_step_index=0,
        rationale=(
            "Ladder exhausted with no named external blocker; re-enter at "
            "recalibration — learning continues, never terminal."
        ),
        is_operator_gated_stop=False,
        external_blocker=None,
    )


__all__ = [
    "SCHEMA_VERSION",
    "LADDER",
    "TRIGGER_CONDITIONS",
    "PROHIBITED_TERMINAL_RESPONSES",
    "EXTERNAL_BLOCKER_KINDS",
    "EscalationDecision",
    "decide",
]
