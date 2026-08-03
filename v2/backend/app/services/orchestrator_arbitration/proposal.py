"""Proposal dataclass + deterministic scoring (PaperOnly).

Lifted from the legacy ``rl/orchestrator_worker.py::_score_candidate_open_static``
shape (SHA256 a7ff83f9...). Legacy weights blended confidence, expected edge,
toxicity, liquidation distance, and data-quality terms. The V2 paper-only port
keeps the deterministic spirit but pares the surface down to the fields we
actually persist in V2 today: ``confidence_calibrated``,
``expected_move_after_cost_bps``, and ``freshness_seconds``.

Stale proposals (``freshness_seconds > max_age_seconds``) return ``-inf`` so
that the arbitration loop will never pick them. No network IO. No exchange
SDK. No Redis client.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple


PROPOSAL_SIDE_LONG = "long"
PROPOSAL_SIDE_SHORT = "short"
PROPOSAL_ALLOWED_SIDES: Tuple[str, ...] = (PROPOSAL_SIDE_LONG, PROPOSAL_SIDE_SHORT)

# Default scoring weights (deterministic).
SCORE_WEIGHT_CONFIDENCE: float = 1.5
SCORE_WEIGHT_EXPECTED_MOVE: float = 0.8
SCORE_WEIGHT_FRESHNESS_PENALTY: float = 0.4

DEFAULT_MAX_AGE_SECONDS: int = 300


@dataclass(frozen=True)
class Proposal:
    """A paper-only proposal candidate for arbitration.

    The legacy ``Proposal`` carried many more fields (PDS, toxicity, hedge
    role, account scope, etc.); the V2 port keeps the minimal subset needed
    for the deterministic arbitration loop and explicit fail-closed checks.
    """

    proposal_id: str
    symbol: str
    side: str
    confidence_calibrated: float
    expected_move_after_cost_bps: float
    generated_utc: str
    source: str
    freshness_seconds: float
    model_version: str
    # Optional notes the arbitration loop can carry forward as audit detail.
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise ValueError("proposal_id must be a non-empty string")
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("symbol must be a non-empty string")
        if self.side not in PROPOSAL_ALLOWED_SIDES:
            raise ValueError(f"side must be one of {PROPOSAL_ALLOWED_SIDES}")
        if (
            not isinstance(self.confidence_calibrated, (int, float))
            or isinstance(self.confidence_calibrated, bool)
            or not math.isfinite(float(self.confidence_calibrated))
        ):
            raise ValueError("confidence_calibrated must be a finite number")
        if not 0.0 <= float(self.confidence_calibrated) <= 1.0:
            raise ValueError("confidence_calibrated must be in [0.0, 1.0]")
        if (
            not isinstance(self.expected_move_after_cost_bps, (int, float))
            or isinstance(self.expected_move_after_cost_bps, bool)
            or not math.isfinite(float(self.expected_move_after_cost_bps))
        ):
            raise ValueError("expected_move_after_cost_bps must be a finite number")
        if not isinstance(self.generated_utc, str) or not self.generated_utc:
            raise ValueError("generated_utc must be a non-empty ISO-8601 string")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("source must be a non-empty string")
        if (
            not isinstance(self.freshness_seconds, (int, float))
            or isinstance(self.freshness_seconds, bool)
            or not math.isfinite(float(self.freshness_seconds))
            or float(self.freshness_seconds) < 0.0
        ):
            raise ValueError("freshness_seconds must be a finite non-negative number")
        if not isinstance(self.model_version, str) or not self.model_version:
            raise ValueError("model_version must be a non-empty string")


def _clamp_unit(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def score_proposal(
    proposal: Proposal,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    weight_confidence: float = SCORE_WEIGHT_CONFIDENCE,
    weight_expected_move: float = SCORE_WEIGHT_EXPECTED_MOVE,
    weight_freshness_penalty: float = SCORE_WEIGHT_FRESHNESS_PENALTY,
) -> float:
    """Return a deterministic score for ``proposal``.

    Returns ``-inf`` for stale or invalid input so the arbitration loop can
    fail-closed by simply taking the maximum.
    """
    if not isinstance(proposal, Proposal):
        return float("-inf")
    if not isinstance(max_age_seconds, int) or max_age_seconds <= 0:
        return float("-inf")
    if proposal.freshness_seconds > float(max_age_seconds):
        return float("-inf")

    conf = _clamp_unit(float(proposal.confidence_calibrated))
    # Normalize bps to ~[-1, 1] via a soft clamp at +/- 200bps so that very
    # large model outputs do not dominate the confidence term.
    expected_move_normalized = max(
        -1.0, min(1.0, float(proposal.expected_move_after_cost_bps) / 200.0)
    )
    # Freshness penalty: 0.0 when generated_utc is "now", 1.0 at max_age.
    freshness_penalty = min(
        1.0, max(0.0, float(proposal.freshness_seconds) / float(max_age_seconds))
    )

    score = (
        weight_confidence * conf
        + weight_expected_move * expected_move_normalized
        - weight_freshness_penalty * freshness_penalty
    )
    if not math.isfinite(score):
        return float("-inf")
    return float(score)
