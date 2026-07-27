"""AdaptivePolicyActionV2 — the single unified adaptive trading-action contract.

FINAL PASS Phase 2 / task FP-030.

This is the ONE final trading authority emitted by the unified adaptive policy.
Downstream components (hard safety/physical validator, intent, reservation,
allocation, fill, position, management) may only revalidate identity, freshness,
physical feasibility, catastrophic safety, and accounting integrity — they may
NOT reapply confidence/loss/microstructure/entry/exit/strategy preferences that
this contract has already resolved (FINAL PASS Phase 14).

Every trading-action value here is a policy OUTPUT (model output / learned
function / portfolio-optimization result / state-dependent parameter), not a
manually fixed final-authority threshold (FINAL PASS Phase 1 / Category E).

``selected_action == FLAT`` is a temporary portfolio action, NOT a terminal
learning state: a flat action still carries expected_information_gain and a full
action_distribution so the learning loop keeps evaluating alternatives.

This module defines and VALIDATES the contract only. It does not itself pick an
action, place an order, or grant any live authority.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from v2.backend.app.contracts.runtime_v2.contracts import canonical_sha256

SCHEMA_VERSION = "adaptive_policy_action_v2"

# selected_action is the coarse portfolio intent. Fine action detail lives in the
# sizing/entry/exit/hedge fields. Discrete component verdicts (ALLOW/REDUCE/BLOCK)
# are diagnostics elsewhere and are NOT valid selected_action values here.
SELECTED_ACTIONS = (
    "DIRECTIONAL",              # single-leg long or short
    "MARKET_NEUTRAL_OR_HEDGED",  # multi-leg / hedged
    "REDUCE",                  # reduce existing exposure
    "CLOSE",                   # close existing exposure
    "FLAT",                    # remain flat (temporary, non-terminal)
)
DIRECTIONAL_SIDES = ("long", "short")
MARGIN_MODE_SIMULATIONS = ("ISOLATED", "CROSS")


def _is_prob(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) \
        and math.isfinite(value) and 0.0 <= float(value) <= 1.0


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _is_nonneg(value: Any) -> bool:
    return _is_finite_number(value) and float(value) >= 0.0


@dataclass(frozen=True)
class AdaptivePolicyActionV2:
    """One complete, self-describing adaptive trading action."""

    # --- identity / lineage ---
    decision_id: str
    state_id: str
    checkpoint_generation: int
    policy_id: str
    strategy_family: str

    # --- primary position ---
    selected_action: str
    primary_symbol: str | None
    primary_timeframe: str | None
    primary_side: str | None
    target_exposure_usd: float
    target_notional_usd: float
    leverage: float
    margin_mode_simulation: str
    margin_allocation_usd: float

    # --- entry policy ---
    entry_style: str
    entry_price_policy: str
    maximum_entry_slippage: float
    order_duration_policy: str

    # --- protective / exit policy ---
    protective_stop_policy: str
    stop_price: float | None
    stop_distance: float | None
    partial_reduction_policy: str
    profit_exit_policy: str
    time_exit_policy: str
    expected_holding_horizon: str

    # --- hedge legs ---
    hedge_enabled: bool
    hedge_legs: Sequence[Mapping[str, Any]]
    hedge_ratios: Sequence[float]

    # --- expected-utility estimates (all continuous / calibrated) ---
    expected_after_cost_return: float
    expected_return_distribution: Mapping[str, Any]
    expected_drawdown_contribution: float
    expected_tail_loss: float
    expected_fill_probability: float
    expected_slippage: float
    expected_market_impact: float
    expected_adverse_selection: float
    expected_information_gain: float

    # --- policy distribution ---
    flat_probability: float
    action_distribution: Mapping[str, float]
    policy_uncertainty: float

    # --- hard safety invariants (never trading preferences) ---
    paper_only: bool = True
    routes_to_live: bool = False
    places_real_order: bool = False
    live_eligible: bool = False

    def validate(self) -> list[str]:
        """Return the list of contract violations (empty == valid)."""
        r: list[str] = []
        # identity
        for name in ("decision_id", "state_id", "policy_id", "strategy_family"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                r.append(f"IDENTITY_FIELD_MISSING:{name}")
        _cg = self.checkpoint_generation
        if not isinstance(_cg, int) or isinstance(_cg, bool):
            r.append("CHECKPOINT_GENERATION_NOT_INT")

        # selected action enum
        if self.selected_action not in SELECTED_ACTIONS:
            r.append(f"SELECTED_ACTION_INVALID:{self.selected_action}")

        # directional actions require symbol/timeframe/side + positive sizing
        if self.selected_action == "DIRECTIONAL":
            if self.primary_side not in DIRECTIONAL_SIDES:
                r.append("DIRECTIONAL_SIDE_INVALID")
            if not self.primary_symbol:
                r.append("DIRECTIONAL_SYMBOL_MISSING")
            if not self.primary_timeframe:
                r.append("DIRECTIONAL_TIMEFRAME_MISSING")
            if not (_is_nonneg(self.target_notional_usd) and float(self.target_notional_usd) > 0.0):
                r.append("DIRECTIONAL_TARGET_NOTIONAL_NOT_POSITIVE")
            if self.protective_stop_policy in (None, "", "NONE"):
                r.append("DIRECTIONAL_MANDATORY_STOP_MISSING")

        # FLAT is non-terminal: it must still carry an action distribution and info-gain
        if self.selected_action == "FLAT":
            if not (_is_prob(self.flat_probability) and float(self.flat_probability) > 0.0):
                r.append("FLAT_PROBABILITY_NOT_POSITIVE")
            if not _is_finite_number(self.expected_information_gain):
                r.append("FLAT_MISSING_INFORMATION_GAIN")

        # margin mode enum
        if self.margin_mode_simulation not in MARGIN_MODE_SIMULATIONS:
            r.append(f"MARGIN_MODE_INVALID:{self.margin_mode_simulation}")

        # sizing must be finite / non-negative
        for name in ("target_exposure_usd", "target_notional_usd", "leverage",
                     "margin_allocation_usd", "maximum_entry_slippage"):
            if not _is_nonneg(getattr(self, name)):
                r.append(f"SIZING_FIELD_NOT_FINITE_NONNEG:{name}")

        # probability-domain estimates
        for name in ("expected_fill_probability", "expected_adverse_selection",
                     "flat_probability", "policy_uncertainty"):
            if not _is_prob(getattr(self, name)):
                r.append(f"PROBABILITY_DOMAIN_INVALID:{name}")

        # finite continuous estimates
        for name in ("expected_after_cost_return", "expected_drawdown_contribution",
                     "expected_tail_loss", "expected_slippage", "expected_market_impact",
                     "expected_information_gain"):
            if not _is_finite_number(getattr(self, name)):
                r.append(f"ESTIMATE_NOT_FINITE:{name}")

        # action_distribution must be a proper distribution over SELECTED_ACTIONS
        dist = self.action_distribution
        if not isinstance(dist, Mapping) or not dist:
            r.append("ACTION_DISTRIBUTION_MISSING")
        else:
            if any(k not in SELECTED_ACTIONS for k in dist):
                r.append("ACTION_DISTRIBUTION_UNKNOWN_KEY")
            if any(not _is_prob(v) for v in dist.values()):
                r.append("ACTION_DISTRIBUTION_NOT_PROBABILITIES")
            total = sum(float(v) for v in dist.values() if _is_finite_number(v))
            if not (0.999 <= total <= 1.001):
                r.append(f"ACTION_DISTRIBUTION_NOT_NORMALIZED:{total:.6f}")

        # hedge coherence
        if self.hedge_enabled:
            if not self.hedge_legs:
                r.append("HEDGE_ENABLED_WITHOUT_LEGS")
            if len(self.hedge_ratios) != len(self.hedge_legs):
                r.append("HEDGE_RATIOS_LEN_MISMATCH")

        # hard safety invariants (Category C/authorization — never relaxable here)
        if self.paper_only is not True:
            r.append("PAPER_ONLY_NOT_TRUE")
        if self.routes_to_live is not False:
            r.append("ROUTES_TO_LIVE_NOT_FALSE")
        if self.places_real_order is not False:
            r.append("PLACES_REAL_ORDER_NOT_FALSE")
        if self.live_eligible is not False:
            r.append("LIVE_ELIGIBLE_NOT_FALSE")
        return r

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "decision_id": self.decision_id,
            "state_id": self.state_id,
            "checkpoint_generation": self.checkpoint_generation,
            "policy_id": self.policy_id,
            "strategy_family": self.strategy_family,
            "selected_action": self.selected_action,
            "primary_symbol": self.primary_symbol,
            "primary_timeframe": self.primary_timeframe,
            "primary_side": self.primary_side,
            "target_exposure_usd": self.target_exposure_usd,
            "target_notional_usd": self.target_notional_usd,
            "leverage": self.leverage,
            "margin_mode_simulation": self.margin_mode_simulation,
            "margin_allocation_usd": self.margin_allocation_usd,
            "entry_style": self.entry_style,
            "entry_price_policy": self.entry_price_policy,
            "maximum_entry_slippage": self.maximum_entry_slippage,
            "order_duration_policy": self.order_duration_policy,
            "protective_stop_policy": self.protective_stop_policy,
            "stop_price": self.stop_price,
            "stop_distance": self.stop_distance,
            "partial_reduction_policy": self.partial_reduction_policy,
            "profit_exit_policy": self.profit_exit_policy,
            "time_exit_policy": self.time_exit_policy,
            "expected_holding_horizon": self.expected_holding_horizon,
            "hedge_enabled": self.hedge_enabled,
            "hedge_legs": [dict(leg) for leg in self.hedge_legs],
            "hedge_ratios": [float(x) for x in self.hedge_ratios],
            "expected_after_cost_return": self.expected_after_cost_return,
            "expected_return_distribution": dict(self.expected_return_distribution),
            "expected_drawdown_contribution": self.expected_drawdown_contribution,
            "expected_tail_loss": self.expected_tail_loss,
            "expected_fill_probability": self.expected_fill_probability,
            "expected_slippage": self.expected_slippage,
            "expected_market_impact": self.expected_market_impact,
            "expected_adverse_selection": self.expected_adverse_selection,
            "expected_information_gain": self.expected_information_gain,
            "flat_probability": self.flat_probability,
            "action_distribution": {k: float(v) for k, v in self.action_distribution.items()},
            "policy_uncertainty": self.policy_uncertainty,
            "paper_only": self.paper_only,
            "routes_to_live": self.routes_to_live,
            "places_real_order": self.places_real_order,
            "live_eligible": self.live_eligible,
        }

    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


__all__ = [
    "SCHEMA_VERSION",
    "SELECTED_ACTIONS",
    "DIRECTIONAL_SIDES",
    "MARGIN_MODE_SIMULATIONS",
    "AdaptivePolicyActionV2",
]
