"""Unit tests for the operational escalation supervisor (FINAL PASS item #2).

Core guarantee under test: a persistent FLAT policy output NEVER means "wait for
data".  It either LAUNCHES a real tracked worker, or — only when every
controllable lever is exhausted — AWAITS on an EXACT numeric threshold (never a
passive wait).  Escalation is never terminal.
"""
from __future__ import annotations

from v2.backend.app.services.adaptive_system.escalation_ladder_v2 import (
    LADDER,
    PROHIBITED_TERMINAL_RESPONSES,
)
from v2.backend.app.services.adaptive_system.escalation_supervisor_v2 import (
    ACTION_AWAIT,
    ACTION_LAUNCH,
    ACTION_NO_ESCALATION,
    PASSIVE_WAIT_MARKERS,
    WORKER_COMMANDS,
    EscalationWorkPlan,
    SupervisorInputs,
    derive_conditions,
    kish_effective_n,
    plan_escalation,
)

RECALIBRATE = "RECALIBRATE_CURRENT_MODELS"
TRAIN_INCREMENTAL = "TRAIN_INCREMENTAL_ON_NEW_MATURED_OUTCOMES"
ALT_STRATEGY = "ACTIVATE_ALTERNATIVE_STRATEGY_FAMILIES"
EXPLORE = "INCREASE_BOUNDED_INFORMATION_SEEKING_EXPLORATION"


def _flat_inputs(**over) -> SupervisorInputs:
    """A persistently-FLAT state (directional=0 over the window, candidates present)."""
    base = dict(
        directional_authorized_count=0,
        flat_authorized_count=6,
        candidate_count=16,
        persistent_flat_cycles=5,
        min_persistent_flat_cycles=3,
        matured_outcome_count=3911,
        effective_n=181.0,
        baseline_matured_outcome_count=None,
        baseline_effective_n=None,
        min_new_matured_outcomes=250,
        min_new_effective_n=25.0,
        superior_challenger_available=False,
        input_manifest_sha="deadbeef",
    )
    base.update(over)
    return SupervisorInputs(**base)


# --------------------------------------------------------------------------- #
# Kish effective-N (reused corpus-diversity logic)
# --------------------------------------------------------------------------- #
def test_kish_effective_n_collapses_clustered_rows():
    # 100 rows all at the SAME decision-minute -> effective N == 1.
    same = ["2026-07-27T23:30:11Z"] * 100
    assert kish_effective_n(same) == 1.0
    # fully time-independent rows -> effective N == row count.
    distinct = [f"2026-07-27T23:{m:02d}:00Z" for m in range(30)]
    assert kish_effective_n(distinct) == 30.0
    # empty corpus is an honest zero, never silently non-zero.
    assert kish_effective_n([]) == 0.0


# --------------------------------------------------------------------------- #
# 1) persistent-flat + NEW info -> LAUNCH a real worker
# --------------------------------------------------------------------------- #
def test_persistent_flat_with_new_info_launches_worker():
    inp = _flat_inputs()  # matured=3911 vs null baseline -> new info exists
    assert inp.new_information_exists() is True
    plan = plan_escalation(inp)

    assert plan.action == ACTION_LAUNCH
    assert plan.selected_step in LADDER
    assert plan.worker_command is not None
    # the descriptor points at a real in-repo entrypoint and is paper-only
    assert plan.worker_command["entrypoint"] == WORKER_COMMANDS[plan.selected_step]["entrypoint"]
    assert plan.worker_command["paper_only"] is True
    assert plan.worker_command["routes_to_live"] is False
    assert plan.exact_trigger_condition is None
    assert plan.next_step is not None
    assert plan.interpretation == "CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE"
    assert plan.validate() == []


def test_launch_advances_to_training_worker_when_recalibrate_exhausted():
    inp = _flat_inputs(exhausted_steps=frozenset({RECALIBRATE}))
    plan = plan_escalation(inp)
    assert plan.action == ACTION_LAUNCH
    # recalibrate exhausted -> ladder advances to incremental training on new data
    assert plan.selected_step == TRAIN_INCREMENTAL
    assert plan.worker_command["entrypoint"].endswith("train_serving_feature_abi_v2_checkpoint.py")
    assert plan.validate() == []


# --------------------------------------------------------------------------- #
# 2) persistent-flat + NO new info + cheap levers exhausted -> AWAIT with an
#    EXACT numeric threshold (never a passive wait)
# --------------------------------------------------------------------------- #
def test_persistent_flat_without_new_info_awaits_exact_threshold():
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,   # new matured = 0  (< 250)
        effective_n=10.0,
        baseline_effective_n=10.0,            # new effective_N = 0 (< 25)
        superior_challenger_available=False,
        exhausted_steps=frozenset({RECALIBRATE, ALT_STRATEGY, EXPLORE}),
    )
    assert inp.new_information_exists() is False
    plan = plan_escalation(inp)

    assert plan.action == ACTION_AWAIT
    assert plan.is_operator_gated is False
    # EXACT numeric threshold: baseline(100)+250 and baseline(10)+25
    cond = plan.exact_trigger_condition
    assert cond == "matured_outcomes >= 350 OR effective_N >= 35.0"
    assert any(ch.isdigit() for ch in cond)
    assert ">=" in cond
    assert "matured_outcomes" in cond and "effective_N" in cond
    # it still names the worker it will launch once the threshold is met
    assert plan.next_step == TRAIN_INCREMENTAL
    assert plan.selected_step == TRAIN_INCREMENTAL
    assert plan.validate() == []


def test_await_threshold_tracks_the_baseline():
    inp = _flat_inputs(
        matured_outcome_count=500,
        baseline_matured_outcome_count=500,
        effective_n=40.0,
        baseline_effective_n=40.0,
        min_new_matured_outcomes=300,
        min_new_effective_n=50.0,
        exhausted_steps=frozenset({RECALIBRATE, ALT_STRATEGY, EXPLORE}),
    )
    plan = plan_escalation(inp)
    assert plan.action == ACTION_AWAIT
    assert plan.exact_trigger_condition == "matured_outcomes >= 800 OR effective_N >= 90.0"


# --------------------------------------------------------------------------- #
# 3) the supervisor NEVER emits a passive wait / prohibited terminal response
# --------------------------------------------------------------------------- #
def test_never_emits_passive_wait_across_states():
    scenarios = [
        _flat_inputs(),  # launch
        _flat_inputs(  # data-gated await
            matured_outcome_count=100,
            baseline_matured_outcome_count=100,
            effective_n=10.0,
            baseline_effective_n=10.0,
            exhausted_steps=frozenset({RECALIBRATE, ALT_STRATEGY, EXPLORE}),
        ),
        _flat_inputs(  # operator-gated await
            matured_outcome_count=100,
            baseline_matured_outcome_count=100,
            effective_n=10.0,
            baseline_effective_n=10.0,
            exhausted_steps=frozenset(LADDER),
            external_blocker="missing_operator_credential",
        ),
        _flat_inputs(directional_authorized_count=5, persistent_flat_cycles=0),  # healthy
    ]
    for inp in scenarios:
        plan = plan_escalation(inp)
        assert plan.validate() == [], f"validation failed: {plan.validate()} for {plan.action}"
        blob = " ".join(
            str(x).lower()
            for x in (
                plan.interpretation,
                plan.exact_trigger_condition or "",
                plan.rationale,
            )
        )
        for marker in PASSIVE_WAIT_MARKERS:
            assert marker not in blob, f"passive-wait marker {marker!r} leaked in {plan.action}"
        for bad in PROHIBITED_TERMINAL_RESPONSES:
            assert bad.lower() not in blob


def test_hand_built_passive_await_fails_validation():
    # A plan that says "wait for more data" must be rejected by validate().
    bad = EscalationWorkPlan(
        trigger=["persistent_flat_without_information_gain"],
        interpretation="CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE",
        action=ACTION_AWAIT,
        selected_step=TRAIN_INCREMENTAL,
        next_step=TRAIN_INCREMENTAL,
        worker_command=None,
        exact_trigger_condition="wait for more data",
        input_manifest_sha="x",
        is_operator_gated=False,
        external_blocker=None,
        rationale="x",
        decision=plan_escalation(_flat_inputs()).decision,
    )
    errors = bad.validate()
    assert any("PASSIVE_WAIT_LANGUAGE_EMITTED" in e for e in errors)
    assert any("AWAIT_TRIGGER_NOT_QUANTITATIVE" in e for e in errors)


# --------------------------------------------------------------------------- #
# 4) ladder step advances when a step is exhausted
# --------------------------------------------------------------------------- #
def test_ladder_step_advances_when_step_exhausted():
    inp0 = _flat_inputs()
    step0 = plan_escalation(inp0).selected_step
    assert step0 == LADDER[0]

    inp1 = _flat_inputs(exhausted_steps=frozenset({LADDER[0]}))
    step1 = plan_escalation(inp1).selected_step
    assert step1 == LADDER[1]

    inp2 = _flat_inputs(exhausted_steps=frozenset({LADDER[0], LADDER[1]}))
    step2 = plan_escalation(inp2).selected_step
    assert step2 == LADDER[2]


# --------------------------------------------------------------------------- #
# 5) escalation is never terminal
# --------------------------------------------------------------------------- #
def test_escalation_never_terminal_even_operator_gated():
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,
        effective_n=10.0,
        baseline_effective_n=10.0,
        exhausted_steps=frozenset(LADDER),
        external_blocker="missing_operator_credential",
    )
    plan = plan_escalation(inp)
    assert plan.action == ACTION_AWAIT
    assert plan.is_operator_gated is True
    # names the exact external resolution — not a market verdict, not a passive wait
    assert plan.exact_trigger_condition == "operator_resolves:missing_operator_credential"
    assert plan.external_blocker == "missing_operator_credential"
    # still forward-pointing: it knows the worker it will launch once unblocked
    assert plan.next_step is not None
    assert plan.interpretation == "CURRENT_POLICY_FAILED_TO_DISCOVER_EDGE"
    for bad in PROHIBITED_TERMINAL_RESPONSES:
        assert bad not in plan.interpretation
    assert plan.validate() == []


def test_all_exhausted_no_blocker_still_awaits_with_numeric_threshold():
    # Ladder fully exhausted, no external blocker, no new info -> NOT terminal:
    # a data-gated AWAIT with an exact numeric threshold.
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,
        effective_n=10.0,
        baseline_effective_n=10.0,
        exhausted_steps=frozenset(LADDER),
        external_blocker=None,
    )
    plan = plan_escalation(inp)
    assert plan.action == ACTION_AWAIT
    assert plan.is_operator_gated is False
    assert plan.exact_trigger_condition == "matured_outcomes >= 350 OR effective_N >= 35.0"
    assert plan.next_step is not None
    assert plan.validate() == []


# --------------------------------------------------------------------------- #
# Healthy state + condition derivation
# --------------------------------------------------------------------------- #
def test_directional_authorized_is_healthy_not_escalation():
    inp = _flat_inputs(directional_authorized_count=5, persistent_flat_cycles=0)
    plan = plan_escalation(inp)
    assert plan.action == ACTION_NO_ESCALATION
    assert plan.worker_command is None
    assert plan.exact_trigger_condition is None
    assert plan.validate() == []


def test_derive_conditions_flags_admission_starved_and_persistence():
    inp = _flat_inputs(
        matured_outcome_count=100,
        baseline_matured_outcome_count=100,
        effective_n=10.0,
        baseline_effective_n=10.0,
    )
    cond = derive_conditions(inp)
    assert cond["admission_starved"] is True
    assert cond["persistent_flat_without_information_gain"] is True
    assert cond["corpus_stagnation"] is True
    # with abundant NEW info, "without information gain" is False but admission
    # starvation still triggers escalation (never a passive wait).
    cond2 = derive_conditions(_flat_inputs())
    assert cond2["persistent_flat_without_information_gain"] is False
    assert cond2["admission_starved"] is True


def test_negative_after_cost_edge_triggers():
    inp = _flat_inputs(directional_authorized_count=3, after_cost_edge_bps=-4.2)
    cond = derive_conditions(inp)
    assert cond["negative_after_cost_edge"] is True
    plan = plan_escalation(inp)
    assert plan.action == ACTION_LAUNCH
    assert plan.validate() == []
