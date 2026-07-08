"""Canonical service facade for preemptive edge-control decisions."""

from __future__ import annotations

from typing import Any

from v2.backend.app.services.preemptive_edge_control.decision import (
    evaluate_candidate,
    summarize_decisions,
)


def evaluate_preemptive_decision(
    candidate: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Evaluate a candidate and return the canonical runtime contract."""

    return evaluate_candidate(candidate, **kwargs)


__all__ = ["evaluate_preemptive_decision", "evaluate_candidate", "summarize_decisions"]
