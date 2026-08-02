"""The A-grade performance gate must be observable without being circular.

The gate blocks every new entry until a rolling 100/300-trade window exists,
while blocking the entries that would build that window. In the paper learning
lane it is therefore observed, not enforced -- but the real verdict must survive
verbatim so the GUI never shows a healthier picture than the truth.
"""

from __future__ import annotations

import pytest

from v2.backend.app.cli.v2_trade_management_paper_loop import (
    _apply_guardian_monitor_only,
    _continuous_edge_guardian_allows_new_entries,
)


def _halted_gate(**overrides: object) -> dict[str, object]:
    gate: dict[str, object] = {
        "status": "A_GRADE_HALTED_PERFORMANCE",
        "a_grade_new_entries_allowed": False,
        "block_all_new_a_grade_entries": True,
        "allowed_runtime_actions": ["reduce", "close", "emergency_de_risk"],
        "failure_reasons": [
            {"reason": "INSUFFICIENT_ROLLING_100_TRADE_WINDOW", "observed": 0, "required": 100},
            {"reason": "AFTER_COST_EXPECTANCY_NOT_POSITIVE", "required": "> 0"},
        ],
    }
    gate.update(overrides)
    return gate


def test_monitor_only_unblocks_admission() -> None:
    monitored = _apply_guardian_monitor_only(_halted_gate())
    assert monitored["guardian_enforcement_mode"] == "MONITOR_ONLY"
    assert _continuous_edge_guardian_allows_new_entries(monitored) is True
    assert monitored["block_all_new_a_grade_entries"] is False
    assert "open" in monitored["allowed_runtime_actions"]


def test_monitor_only_preserves_the_real_verdict_verbatim() -> None:
    original = _halted_gate()
    monitored = _apply_guardian_monitor_only(original)
    assert monitored["monitor_only_observed_a_grade_new_entries_allowed"] is False
    assert monitored["monitor_only_observed_block_all_new_a_grade_entries"] is True
    assert monitored["monitor_only_observed_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert monitored["monitor_only_observed_failure_reasons"] == original["failure_reasons"]


def test_monitor_only_does_not_mutate_the_source_gate() -> None:
    original = _halted_gate()
    _apply_guardian_monitor_only(original)
    assert original["a_grade_new_entries_allowed"] is False
    assert original["status"] == "A_GRADE_HALTED_PERFORMANCE"


@pytest.mark.parametrize("field", ["routes_to_live", "places_real_order"])
def test_monitor_only_fails_closed_on_anything_reaching_an_exchange(field: str) -> None:
    gate = _halted_gate(**{field: True})
    monitored = _apply_guardian_monitor_only(gate)
    # Untouched: a live-routable gate is never demoted to monitoring.
    assert monitored["a_grade_new_entries_allowed"] is False
    assert _continuous_edge_guardian_allows_new_entries(monitored) is False
    assert "guardian_enforcement_mode" not in monitored


def test_an_already_allowing_gate_is_left_alone() -> None:
    gate = _halted_gate(
        status="A_GRADE_READY",
        a_grade_new_entries_allowed=True,
        block_all_new_a_grade_entries=False,
    )
    monitored = _apply_guardian_monitor_only(gate)
    assert "guardian_enforcement_mode" not in monitored
    assert _continuous_edge_guardian_allows_new_entries(monitored) is True


def test_empty_gate_is_not_promoted_into_permission() -> None:
    # No evidence must never become "allowed".
    assert _apply_guardian_monitor_only({}) == {}
    assert _continuous_edge_guardian_allows_new_entries({}) is False
