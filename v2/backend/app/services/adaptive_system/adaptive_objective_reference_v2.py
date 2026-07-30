"""Independent reference implementation of the adaptive objective formula."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Sequence

from v2.backend.app.domain.adaptive_policy_action_v2 import (
    ACTION_DIRECTIONAL_TRADE,
    ACTION_REMAIN_FLAT,
)
from v2.backend.app.services.adaptive_system.adaptive_objective_v2 import (
    BOUNDED_EXPLORATION,
    CHAMPION_EXPLOITATION,
    ActionObjectiveInputsV2,
    LearnedObjectiveWeightsV2,
)


@dataclass(frozen=True, slots=True)
class ReferenceObjectiveResultV2:
    utilities: tuple[tuple[str, float | None], ...]
    champion_action_id: str | None
    exploration_action_id: str | None


def evaluate_reference_objective(
    actions: Sequence[ActionObjectiveInputsV2],
    weights: LearnedObjectiveWeightsV2,
) -> ReferenceObjectiveResultV2:
    """Recompute utilities without calling the production objective evaluator."""

    utilities: dict[str, float | None] = {}
    by_id = {item.action_id: item for item in actions}
    if len(by_id) != len(actions):
        raise ValueError("actions:unique_ids_required")
    for action in actions:
        if not action.hard_constraints_satisfied:
            utilities[action.action_id] = None
            continue
        penalties = (
            weights.drawdown_penalty * action.expected_drawdown_contribution_bps
            + weights.tail_loss_penalty * action.expected_tail_loss_bps
            + weights.liquidation_risk_penalty * action.liquidation_risk_probability
            + weights.market_impact_penalty * action.expected_market_impact_bps
            + weights.funding_cost_penalty * action.expected_funding_cost_bps
            + weights.turnover_penalty * action.expected_turnover_bps
            + weights.concentration_penalty * action.expected_concentration_bps
            + weights.correlation_penalty
            * action.terminal_equity_projection.correlation_exposure_bps
        )
        utilities[action.action_id] = (
            weights.expected_after_cost_return * action.expected_after_cost_return_bps
            + weights.expected_log_equity_growth_reward
            * action.terminal_equity_projection.expected_log_equity_growth_per_opportunity
            - penalties
            + weights.information_gain_reward * action.expected_information_gain
        )
    hard_flat = any(
        action.selected_action == ACTION_REMAIN_FLAT
        and action.policy_mode == CHAMPION_EXPLOITATION
        and utilities[action.action_id] is not None
        for action in actions
    )

    def best(mode: str) -> str | None:
        eligible: list[tuple[float, str]] = []
        for action in actions:
            utility = utilities[action.action_id]
            if action.policy_mode != mode or utility is None:
                continue
            if mode == BOUNDED_EXPLORATION and (
                action.selected_action == ACTION_REMAIN_FLAT
                or utility <= 0.0
                or action.expected_information_gain <= 0.0
            ):
                continue
            eligible.append((utility, action.action_id))
        if mode == CHAMPION_EXPLOITATION and not hard_flat:
            return None
        return max(eligible)[1] if eligible else None

    return ReferenceObjectiveResultV2(
        utilities=tuple(sorted(utilities.items())),
        champion_action_id=best(CHAMPION_EXPLOITATION),
        exploration_action_id=best(BOUNDED_EXPLORATION),
    )


def select_reference_action_id(
    result: ReferenceObjectiveResultV2,
    actions: Sequence[ActionObjectiveInputsV2],
    *,
    candidate_id: str,
    calibration_sha256: str,
    bounded_exploration_probability: float,
    bootstrap_designation: Mapping[str, Any] | None = None,
) -> str | None:
    """Independently replay the final exploit/explore selection.

    A positive learned-objective exploration action is selected
    deterministically when the champion is the hard-valid flat action.  A
    validated terminal-equity-ranked bootstrap designation may select its
    designated hard-valid action even when its learned utility is nonpositive.
    Otherwise the fitted mode allocation remains the selector.  This
    deliberately duplicates the small production selection rule instead of
    importing it, so a production-only change becomes a parity disagreement.
    """

    by_id = {item.action_id: item for item in actions}
    if len(by_id) != len(actions):
        raise ValueError("actions:unique_ids_required")
    if not 0.0 < bounded_exploration_probability < 1.0:
        raise ValueError("bounded_exploration_probability:open_unit_interval_required")
    champion = by_id.get(result.champion_action_id or "")
    champion_is_flat = (
        champion is not None
        and champion.selected_action == ACTION_REMAIN_FLAT
        and champion.hard_constraints_satisfied is True
    )
    deterministic_information_seeking = (
        champion_is_flat and result.exploration_action_id is not None
    )
    draw = int(
        hashlib.sha256(
            f"{candidate_id}:{calibration_sha256}".encode("utf-8")
        ).hexdigest()[:16],
        16,
    ) / float(2**64)
    choose_exploration = draw < bounded_exploration_probability
    if (
        result.exploration_action_id is not None
        and (choose_exploration or deterministic_information_seeking)
    ):
        return result.exploration_action_id
    if (
        bootstrap_designation is not None
        and result.exploration_action_id is None
        and champion_is_flat
        and bootstrap_designation.get("side") in {"LONG", "SHORT"}
    ):
        bootstrap_side = str(bootstrap_designation["side"]).lower()
        side_suffixes = (
            f":{BOUNDED_EXPLORATION}:{bootstrap_side}",
            f":{BOUNDED_EXPLORATION}:{bootstrap_side}:venue_minimum",
        )
        bootstrap_matches = [
            action
            for action in actions
            if action.policy_mode == BOUNDED_EXPLORATION
            and action.selected_action == ACTION_DIRECTIONAL_TRADE
            and action.action_id.endswith(side_suffixes)
            and action.hard_constraints_satisfied is True
            and action.expected_information_gain > 0.0
        ]
        if len(bootstrap_matches) == 1:
            return bootstrap_matches[0].action_id
    return result.champion_action_id


__all__ = (
    "ReferenceObjectiveResultV2",
    "evaluate_reference_objective",
    "select_reference_action_id",
)
