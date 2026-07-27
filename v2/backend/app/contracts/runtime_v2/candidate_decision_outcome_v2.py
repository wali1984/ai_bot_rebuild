"""CandidateDecisionOutcomeV2 — the complete candidate-outcome learning record.

FINAL PASS Phase 5 / task FP-060.

EVERY candidate the adaptive policy evaluates — whether it is traded, rejected,
infeasible, risk-reduced, flat, or hedged — is recorded here at decision time,
then completed with matured labels once outcomes are observable. This is the
learning substrate that makes "no edge" a training signal rather than a terminal
classification: rejected and flat candidates are labeled too, so gate-performance
attribution and counterfactual policy evaluation have full coverage.

Hard rule: counterfactual outcomes (what a DIFFERENT action would have earned) are
valid training / policy-evaluation evidence but are NEVER counted as realized
paper profit. This contract enforces that separation structurally:
``MaturedLabelsV2.counts_as_paper_profit`` is True only for the action actually
taken and persisted as a paper fill; every counterfactual arm is
``counts_as_paper_profit == False`` by construction.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from v2.backend.app.contracts.runtime_v2.contracts import canonical_sha256

SCHEMA_VERSION = "candidate_decision_outcome_v2"

# Every candidate must carry one disposition — none may be silently dropped.
CANDIDATE_DISPOSITIONS = (
    "TRADED",
    "REJECTED",
    "INFEASIBLE",
    "RISK_REDUCED",
    "FLAT",
    "HEDGED",
)

# Counterfactual arms that must be labeled for policy evaluation (never profit).
COUNTERFACTUAL_ARMS = (
    "unhedged",
    "hedged",
    "alternative_side",
    "alternative_size",
    "alternative_leverage",
    "alternative_entry",
    "alternative_exit",
)


def _finite(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


@dataclass(frozen=True)
class MaturedLabelsV2:
    """Observed outcomes for one candidate, matured after the decision horizon."""

    matured: bool
    future_returns_bps_by_horizon: Mapping[str, float]
    max_favorable_excursion_bps: float | None
    max_adverse_excursion_bps: float | None
    realized_volatility_bps: float | None
    estimated_executable_entry: float | None
    estimated_executable_exit: float | None
    fees_bps: float | None
    spread_bps: float | None
    slippage_bps: float | None
    funding_bps: float | None
    market_impact_bps: float | None
    stop_result: str | None
    time_exit_result: str | None
    profit_exit_result: str | None
    # Realized P&L of the action ACTUALLY taken. Only this may count as profit,
    # and only when the candidate produced a persisted paper fill.
    realized_action_pnl_bps: float | None
    counts_as_paper_profit: bool
    # Counterfactual arms: {arm_name: {"pnl_bps": float, "counts_as_paper_profit": False, ...}}
    counterfactual_outcomes: Mapping[str, Mapping[str, Any]]

    def validate(self) -> list[str]:
        r: list[str] = []
        if not isinstance(self.matured, bool):
            r.append("MATURED_FLAG_INVALID")
        if not isinstance(self.counterfactual_outcomes, Mapping):
            r.append("COUNTERFACTUALS_NOT_MAPPING")
        else:
            for arm, payload in self.counterfactual_outcomes.items():
                if arm not in COUNTERFACTUAL_ARMS:
                    r.append(f"COUNTERFACTUAL_ARM_UNKNOWN:{arm}")
                if not isinstance(payload, Mapping):
                    r.append(f"COUNTERFACTUAL_PAYLOAD_INVALID:{arm}")
                    continue
                # Hard invariant: a counterfactual can NEVER be booked as paper profit.
                if payload.get("counts_as_paper_profit") is not False:
                    r.append(f"COUNTERFACTUAL_COUNTS_AS_PROFIT_FORBIDDEN:{arm}")
        # Only a TRADED/persisted action may count as profit; enforced by the caller
        # supplying counts_as_paper_profit. Here we require finite realized pnl when it does.
        if self.counts_as_paper_profit and not _finite(self.realized_action_pnl_bps):
            r.append("PROFIT_CLAIMED_WITHOUT_FINITE_REALIZED_PNL")
        if self.matured and not isinstance(self.future_returns_bps_by_horizon, Mapping):
            r.append("MATURED_WITHOUT_HORIZON_RETURNS")
        return r


@dataclass(frozen=True)
class CandidateDecisionOutcomeV2:
    """One candidate, its decision-time context, and (later) its matured labels."""

    # --- identity / lineage (decision time) ---
    candidate_id: str
    state_id: str
    prediction_id: str
    policy_id: str
    checkpoint_generation: int
    symbol: str
    timeframe: str

    # --- decision-time context ---
    disposition: str
    proposed_action: Mapping[str, Any]
    selected_action: Mapping[str, Any]
    model_distributions: Mapping[str, Any]
    component_estimates: Mapping[str, Any]
    portfolio_state: Mapping[str, Any]
    execution_state: Mapping[str, Any]
    decision_rationale: str
    decision_time: str
    # Explicit reason a candidate was NOT traded — so rejections are never an
    # unexplained drop (acceptance: unexplained_candidate_drops=0).
    disposition_reason: str

    # --- matured labels (filled in later; may be unmatured at decision time) ---
    matured_labels: MaturedLabelsV2 | None = None

    def validate(self) -> list[str]:
        r: list[str] = []
        for name in ("candidate_id", "state_id", "prediction_id", "policy_id",
                     "symbol", "timeframe", "decision_time", "disposition_reason"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                r.append(f"IDENTITY_FIELD_MISSING:{name}")
        _cg = self.checkpoint_generation
        if not isinstance(_cg, int) or isinstance(_cg, bool):
            r.append("CHECKPOINT_GENERATION_NOT_INT")
        if self.disposition not in CANDIDATE_DISPOSITIONS:
            r.append(f"DISPOSITION_INVALID:{self.disposition}")
        # Every non-traded disposition must carry an explicit reason (no silent drop).
        if self.disposition != "TRADED" and not self.disposition_reason:
            r.append("NON_TRADED_WITHOUT_REASON")
        for name in ("proposed_action", "selected_action", "model_distributions",
                     "component_estimates", "portfolio_state", "execution_state"):
            if not isinstance(getattr(self, name), Mapping):
                r.append(f"CONTEXT_FIELD_NOT_MAPPING:{name}")
        if self.matured_labels is not None:
            r.extend(self.matured_labels.validate())
            # Only a TRADED candidate may ever book realized paper profit.
            if self.matured_labels.counts_as_paper_profit and self.disposition != "TRADED":
                r.append("NON_TRADED_CANDIDATE_CLAIMS_PAPER_PROFIT")
        return r

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "state_id": self.state_id,
            "prediction_id": self.prediction_id,
            "policy_id": self.policy_id,
            "checkpoint_generation": self.checkpoint_generation,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "disposition": self.disposition,
            "disposition_reason": self.disposition_reason,
            "proposed_action": dict(self.proposed_action),
            "selected_action": dict(self.selected_action),
            "model_distributions": dict(self.model_distributions),
            "component_estimates": dict(self.component_estimates),
            "portfolio_state": dict(self.portfolio_state),
            "execution_state": dict(self.execution_state),
            "decision_rationale": self.decision_rationale,
            "decision_time": self.decision_time,
        }
        if self.matured_labels is not None:
            ml = self.matured_labels
            d["matured_labels"] = {
                "matured": ml.matured,
                "future_returns_bps_by_horizon": dict(ml.future_returns_bps_by_horizon),
                "max_favorable_excursion_bps": ml.max_favorable_excursion_bps,
                "max_adverse_excursion_bps": ml.max_adverse_excursion_bps,
                "realized_volatility_bps": ml.realized_volatility_bps,
                "estimated_executable_entry": ml.estimated_executable_entry,
                "estimated_executable_exit": ml.estimated_executable_exit,
                "fees_bps": ml.fees_bps,
                "spread_bps": ml.spread_bps,
                "slippage_bps": ml.slippage_bps,
                "funding_bps": ml.funding_bps,
                "market_impact_bps": ml.market_impact_bps,
                "stop_result": ml.stop_result,
                "time_exit_result": ml.time_exit_result,
                "profit_exit_result": ml.profit_exit_result,
                "realized_action_pnl_bps": ml.realized_action_pnl_bps,
                "counts_as_paper_profit": ml.counts_as_paper_profit,
                "counterfactual_outcomes": {
                    k: dict(v) for k, v in ml.counterfactual_outcomes.items()
                },
            }
        return d

    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())


__all__ = [
    "SCHEMA_VERSION",
    "CANDIDATE_DISPOSITIONS",
    "COUNTERFACTUAL_ARMS",
    "MaturedLabelsV2",
    "CandidateDecisionOutcomeV2",
]
