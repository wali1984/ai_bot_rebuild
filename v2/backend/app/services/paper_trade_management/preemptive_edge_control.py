"""Paper-only adapter for preemptive edge-control evaluation and replay."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from v2.backend.app.services.preemptive_edge_control.decision import (
    PAPER_EXACT_ZERO_LOSS_SEMANTICS_CONTROL_FLAG,
    PreemptiveReplayError,
    evaluate_candidate,
    replay_preemptive_decision,
)


def evaluate_paper_candidate(
    candidate: dict[str, Any],
    *,
    closed_rows: list[dict[str, Any]] | None = None,
    bucket_health: dict[str, dict[str, Any]] | None = None,
    continuous_edge_guardian_gate: dict[str, Any] | None = None,
    bucket_quarantine_status: dict[str, Any] | None = None,
    allow_positive_edge_probation: bool = False,
    allow_paper_risk_controller_exploration: bool = False,
    allow_reduce_or_close: bool = False,
    altdata_confluence: dict[str, Any] | None = None,
    adaptive_tuning_state: Mapping[str, Any] | None = None,
    decision_time: str | datetime | None = None,
) -> dict[str, Any]:
    """Evaluate a paper candidate without treating an exact zero as missing.

    The mode is written into the authenticated preemptive input material, so a
    paper receipt cannot be replayed accidentally with shared/live semantics.
    """

    return evaluate_candidate(
        candidate,
        closed_rows=closed_rows,
        bucket_health=bucket_health,
        continuous_edge_guardian_gate=continuous_edge_guardian_gate,
        bucket_quarantine_status=bucket_quarantine_status,
        allow_positive_edge_probation=allow_positive_edge_probation,
        allow_paper_risk_controller_exploration=(
            allow_paper_risk_controller_exploration
        ),
        allow_reduce_or_close=allow_reduce_or_close,
        altdata_confluence=altdata_confluence,
        adaptive_tuning_state=adaptive_tuning_state,
        decision_time=decision_time,
        _paper_exact_zero_loss_semantics=True,
    )


def replay_paper_preemptive_decision(
    input_material: Mapping[str, Any],
    *,
    expected_input_hash: str | None = None,
) -> dict[str, Any]:
    """Replay paper receipts with their authenticated loss semantics.

    Receipts created before the paper-only semantic marker remain replayable
    with the unchanged shared evaluator.  A marked receipt must use the
    paper-only evaluator and cannot cross into shared/live replay unnoticed.
    """

    control_flags = input_material.get("control_flags")
    if not isinstance(control_flags, Mapping):
        raise PreemptiveReplayError("PREEMPTIVE_REPLAY_CONTROL_FLAGS_NOT_MAPPING")
    paper_exact_zero = (
        control_flags.get(PAPER_EXACT_ZERO_LOSS_SEMANTICS_CONTROL_FLAG) is True
    )
    return replay_preemptive_decision(
        input_material,
        expected_input_hash=expected_input_hash,
        _paper_exact_zero_loss_semantics=paper_exact_zero,
    )
