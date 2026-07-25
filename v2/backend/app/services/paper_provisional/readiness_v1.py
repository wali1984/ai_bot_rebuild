"""Evidence-based paper/live readiness — 7 SEPARATE dimensions (Phase 11).

Replaces the idea that "100 rows means live" with explicit, independently-reported
readiness. No single aggregate boolean may hide which dimension failed, and
``live_submission_ready`` is ALWAYS False here — it is only ever flipped by a
separate, human-gated real-readiness process, never by this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

READINESS_DIMENSIONS = (
    "paper_checkpoint_ready",
    "paper_runtime_ready",
    "execution_dry_run_ready",
    "economic_ready",
    "accounting_ready",
    "operational_ready",
    "live_submission_ready",
)


def compute_readiness(
    *,
    recovery_checkpoint_train_rows: int | None,
    paper_min_train_rows: int = 100,
    paper_loop_running: bool,
    provisional_gate_wired: bool,
    dry_run_no_submit_proven: bool,
    accounting_reconciled: bool,
    economic_edge_proven: bool,
    natural_closes: int,
) -> dict[str, Any]:
    """Return the 7 readiness dimensions, each with its own evidence.

    live_submission_ready is unconditionally False: this pass proves at most the
    first three dimensions; real-money readiness is a separate human-gated gate.
    """
    have = (
        int(recovery_checkpoint_train_rows)
        if isinstance(recovery_checkpoint_train_rows, int | float)
        else None
    )
    paper_checkpoint_ready = have is not None and have >= int(paper_min_train_rows)
    paper_runtime_ready = bool(paper_loop_running and provisional_gate_wired)
    execution_dry_run_ready = bool(dry_run_no_submit_proven)
    accounting_ready = bool(accounting_reconciled)
    # Economic readiness requires a genuinely proven after-cost edge over enough
    # natural closes — NOT merely a trained checkpoint. Provisional by design here.
    economic_ready = bool(economic_edge_proven and natural_closes >= 100)
    operational_ready = bool(
        paper_checkpoint_ready
        and paper_runtime_ready
        and execution_dry_run_ready
        and accounting_ready
    )
    return {
        "schema_version": "v2_paper_provisional_readiness_v1",
        "paper_checkpoint_ready": paper_checkpoint_ready,
        "paper_runtime_ready": paper_runtime_ready,
        "execution_dry_run_ready": execution_dry_run_ready,
        "economic_ready": economic_ready,
        "accounting_ready": accounting_ready,
        "operational_ready": operational_ready,
        # NEVER true from this module — real-money readiness is human-gated.
        "live_submission_ready": False,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "exchange_action_taken": False,
        "evidence": {
            "recovery_checkpoint_train_rows": have,
            "paper_min_train_rows": int(paper_min_train_rows),
            "natural_closes": int(natural_closes),
            "economic_certification": "PROVISIONAL",
        },
    }


def readiness_summary(readiness: Mapping[str, Any]) -> str:
    parts = [f"{dim}={'Y' if readiness.get(dim) else 'N'}" for dim in READINESS_DIMENSIONS]
    return " ".join(parts)
