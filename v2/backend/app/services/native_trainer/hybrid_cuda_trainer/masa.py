"""MASA auxiliary signal adapter for the V2 hybrid trainer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MASAOutput:
    masa_signal: float
    auxiliary_loss_target: float
    regime_score: float
    explanation: str


class V2MASAAdapter:
    """Small V2-native MASA head adapter.

    The legacy MASA agent used auxiliary market-state agreement. This adapter
    keeps that behavior shape by producing a bounded signal from expected move,
    data coverage, and action probabilities.
    """

    def evaluate(
        self,
        *,
        expected_move_bps: float,
        action_probabilities: tuple[float, ...],
        data_coverage_percent: float,
    ) -> MASAOutput:
        long_prob = action_probabilities[1] if len(action_probabilities) > 1 else 0.0
        short_prob = action_probabilities[2] if len(action_probabilities) > 2 else 0.0
        directional = long_prob - short_prob
        edge = max(-1.0, min(1.0, expected_move_bps / 100.0))
        coverage = max(0.0, min(1.0, data_coverage_percent / 100.0))
        signal = max(-1.0, min(1.0, 0.6 * directional + 0.4 * edge)) * coverage
        return MASAOutput(
            masa_signal=float(signal),
            auxiliary_loss_target=float(edge * coverage),
            regime_score=float(coverage),
            explanation="directional_action_agreement_plus_expected_move_coverage",
        )
