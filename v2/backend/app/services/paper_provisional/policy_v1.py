"""PaperProvisionalCheckpointPolicyV1 — the NORMAL autonomous 100-row paper gate.

This is a distinct, evidence-honest gate that lets a checkpoint trained from at
least 100 admitted rows trade autonomously in PAPER mode WITHOUT the single-use
engineering-canary arm or any per-trade economic-control exception. It is:

* paper-only, non-promotable, never live-eligible, never routes to live;
* separate from the strict champion promotion gate (1000 rows, unchanged) and from
  the paper-recovery floor (256) — a 100-row checkpoint does NOT auto-pass strict.

It also carries the Phase-8 provisional risk limits (1 position, tiny notional,
lowest leverage, mandatory stop, reduce-only) and the cohort identity that lets the
new cohort's performance circuit breaker start fresh from its own results without
erasing or relabeling the historical (July-17) losing cohort.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

PAPER_PROVISIONAL_MIN_TRAIN_ROWS = 100
STRICT_CHAMPION_MIN_TRAIN_ROWS = 1000  # unchanged; never lowered by this policy
REQUIRED_LIVE_GATE = "blocked_human_only"

PAPER_PROVISIONAL_CHECKPOINT_CLASSIFICATION = "PAPER_PROVISIONAL_100_ROW_CHECKPOINT"

# Non-bypassable safety anchors — a provisional checkpoint can NEVER acquire these.
PAPER_PROVISIONAL_SAFETY_TAGS: dict[str, Any] = {
    "paper_only": True,
    "checkpoint_promotable": False,
    "non_promotable": True,
    "live_eligible": False,
    "routes_to_live": False,
    "places_real_order": False,
    "economic_certification": "PROVISIONAL",
}


# Documented operator-configured provisional paper exposure cap (USD). Large
# enough that a venue minimum survives a REDUCE_SIZE liquidity haircut, i.e. it is
# NOT a hardcoded $10. Overridable via PAPER_PROVISIONAL_MAX_NOTIONAL_USD.
DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD = 100.0


@dataclass(frozen=True)
class PaperProvisionalLimitsV1:
    """Phase-8 paper risk limits for the provisional cohort (paper controls)."""

    maximum_concurrent_positions: int = 1
    # Operator-configured paper exposure cap — NOT a per-symbol hardcoded $10.
    maximum_notional_per_position_usd: float = DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD
    maximum_total_exposure_usd: float = DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD
    lowest_permitted_leverage: float = 1.0
    mandatory_stop: bool = True
    reduce_only_close: bool = True
    pyramiding: bool = False
    averaging_down: bool = False
    automatic_hedging: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "maximum_concurrent_positions": self.maximum_concurrent_positions,
            "maximum_notional_per_position_usd": self.maximum_notional_per_position_usd,
            "maximum_total_exposure_usd": self.maximum_total_exposure_usd,
            "lowest_permitted_leverage": self.lowest_permitted_leverage,
            "mandatory_stop": self.mandatory_stop,
            "reduce_only_close": self.reduce_only_close,
            "pyramiding": self.pyramiding,
            "averaging_down": self.averaging_down,
            "automatic_hedging": self.automatic_hedging,
        }


def minimum_valid_notional(
    *,
    venue_minimum_notional_usd: float,
    microstructure_liquidity_multiplier: float,
) -> float:
    """Smallest requested notional whose executable slice clears the venue minimum.

    A microstructure REDUCE_SIZE haircut multiplies the executable size by
    ``microstructure_liquidity_multiplier`` (e.g. 0.35), so the REQUESTED notional
    must be venue_minimum / multiplier for the post-haircut slice to still meet the
    exchange minimum notional.
    """
    mult = float(microstructure_liquidity_multiplier)
    if mult <= 0.0:
        return float(venue_minimum_notional_usd)
    return float(venue_minimum_notional_usd) / mult


def provisional_notional_plan(
    *,
    venue_minimum_notional_usd: float,
    minimum_quantity: float,
    mark_price_usd: float,
    microstructure_liquidity_multiplier: float,
    exposure_cap_usd: float,
    free_margin_usd: float,
    effective_leverage: float = 1.0,
) -> dict[str, Any]:
    """Compute the smallest valid provisional request, or a precise rejection.

    Never rounds above the risk-approved budget: if the smallest venue-valid
    request cannot fit under the cohort exposure cap or free margin, the symbol is
    rejected (choose another) rather than forcing a fit.
    """
    min_notional = minimum_valid_notional(
        venue_minimum_notional_usd=venue_minimum_notional_usd,
        microstructure_liquidity_multiplier=microstructure_liquidity_multiplier,
    )
    # Also honor the exchange LOT_SIZE minimum quantity at the current mark.
    min_qty_notional = float(minimum_quantity) * float(mark_price_usd)
    request_notional = max(min_notional, min_qty_notional)
    leverage = max(1.0, float(effective_leverage))
    allocated_margin = request_notional / leverage
    fits = (
        request_notional <= float(exposure_cap_usd)
        and allocated_margin <= float(free_margin_usd)
    )
    return {
        "minimum_valid_notional_usd": round(min_notional, 6),
        "request_notional_usd": round(request_notional, 6) if fits else None,
        "allocated_margin_usd": round(allocated_margin, 6) if fits else None,
        "effective_leverage": leverage,
        "fits_within_cohort_exposure_cap": fits,
        "reject_reason": None
        if fits
        else "PROVISIONAL_MIN_VALID_NOTIONAL_EXCEEDS_CAP_OR_MARGIN_CHOOSE_ANOTHER_SYMBOL",
    }


@dataclass(frozen=True)
class PaperProvisionalCheckpointPolicyV1:
    minimum_paper_provisional_train_rows: int = PAPER_PROVISIONAL_MIN_TRAIN_ROWS
    strict_champion_min_train_rows: int = STRICT_CHAMPION_MIN_TRAIN_ROWS
    live_gate_required: str = REQUIRED_LIVE_GATE
    limits: PaperProvisionalLimitsV1 = field(default_factory=PaperProvisionalLimitsV1)

    def gate(self, *, train_rows: int | None) -> dict[str, Any]:
        """Evaluate the 100-row paper gate. Never gates on the strict 1000 count."""
        have = int(train_rows) if isinstance(train_rows, int | float) else None
        satisfied = have is not None and have >= self.minimum_paper_provisional_train_rows
        return {
            "paper_min_train_rows": self.minimum_paper_provisional_train_rows,
            "paper_provisional_train_rows": have,
            "paper_provisional_gate_satisfied": satisfied,
            "strict_champion_min_train_rows": self.strict_champion_min_train_rows,
            "paper_not_blocked_by_strict_train_row_gate": True,
            "display": (
                f"paper checkpoint: {have}/{self.minimum_paper_provisional_train_rows} "
                f"{'PASS' if satisfied else 'PENDING'}"
            ),
        }

    def classify(self, *, train_rows: int | None) -> str:
        """Return the checkpoint classification when the gate passes, else PENDING."""
        if self.gate(train_rows=train_rows)["paper_provisional_gate_satisfied"]:
            return PAPER_PROVISIONAL_CHECKPOINT_CLASSIFICATION
        return "PAPER_PROVISIONAL_TRAIN_ROWS_PENDING"

    def eligibility_tags(self, *, train_rows: int | None) -> dict[str, Any]:
        """Paper-eligibility tags for a satisfied provisional checkpoint.

        paper_eligible becomes True (normal paper mode) ONLY when the 100-row gate
        passes; the never-live safety anchors are always present. This is NOT an
        engineering-canary artifact: no single-use arm, no excluded_from_economic_
        metrics, no per-trade economic-control exception.
        """
        satisfied = self.gate(train_rows=train_rows)["paper_provisional_gate_satisfied"]
        return {
            "paper_provisional_checkpoint": bool(satisfied),
            "paper_eligible": bool(satisfied),
            "checkpoint_classification": self.classify(train_rows=train_rows),
            "engineering_canary": False,
            "requires_per_trade_economic_exception": False,
            **PAPER_PROVISIONAL_SAFETY_TAGS,
            "live_gate": self.live_gate_required,
        }


def cohort_identity(
    *,
    checkpoint_id: str,
    activation_time_utc: str,
    initial_paper_equity_usd: float,
) -> dict[str, Any]:
    """Fresh cohort identity so the new cohort's breaker starts from ITS results.

    The cohort id is derived from the checkpoint + activation time; it is stamped
    onto new filled rows only. Historical rows keep their old/absent cohort id and
    are NEVER relabeled — the strict losing cohort's global HALTED_PERFORMANCE stays
    fully in force for any intent carrying the old/no cohort id.
    """
    cohort_id = f"paper_provisional:{checkpoint_id}:{activation_time_utc}"
    return {
        "paper_strategy_cohort_id": cohort_id,
        "checkpoint_id": checkpoint_id,
        "paper_cohort_activation_utc": activation_time_utc,
        "paper_cohort_initial_equity_usd": float(initial_paper_equity_usd),
        "paper_only": True,
        "live_eligible": False,
    }


def load_paper_provisional_policy_v1(
    environ: Mapping[str, str] | None = None,
) -> PaperProvisionalCheckpointPolicyV1:
    import os

    source = os.environ if environ is None else environ

    def _as_int(raw: Any, default: int, *, minimum: int) -> int:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    def _as_float(raw: Any, default: float, *, minimum: float) -> float:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            return default
        return max(minimum, value)

    cap = _as_float(
        source.get("PAPER_PROVISIONAL_MAX_NOTIONAL_USD"),
        DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD,
        minimum=1.0,
    )
    return PaperProvisionalCheckpointPolicyV1(
        minimum_paper_provisional_train_rows=_as_int(
            source.get("PAPER_MIN_TRAIN_ROWS"),
            PAPER_PROVISIONAL_MIN_TRAIN_ROWS,
            minimum=1,
        ),
        # Strict champion gate is a hard constant here — never env-lowered by this
        # policy (the strict real-money gate is redesigned separately, not here).
        strict_champion_min_train_rows=STRICT_CHAMPION_MIN_TRAIN_ROWS,
        limits=PaperProvisionalLimitsV1(
            maximum_notional_per_position_usd=cap,
            maximum_total_exposure_usd=cap,
        ),
    )
