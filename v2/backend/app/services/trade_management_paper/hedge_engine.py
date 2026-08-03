"""V2 native adaptive hedge paper engine (paper-only).

Pure stdlib paper-only evaluation. Decides whether a hedge would be
proposed for a given position snapshot. Emits:

- hedge_needed (bool)
- hedge_side ("long" / "short" / null)
- hedge_size_ratio (in [0, max])
- hedge_budget_check ({allowed, ratio, max})
- hedge_block_reason (string or empty)
- hedge_fail_closed_when_missing_inputs (bool)

NEVER places live orders. NEVER writes legacy Redis. When required
inputs are missing or operator policy says the paper hedge engine is
not approved, the engine fail-closes with the reason recorded.

Legacy behavior sources (read-only) consulted:

- rl/hedge_manager_v3.py
    sha256=8cc0c991bcace41853ec5304a27767d30ee332f669474c27a3d606c38f746edf
- rl/hedge_harvest_engine.py
    sha256=1368cf021fe6c707bd99bcffc4bbd6fe4785760073a2e7702df3a319732e8cb8
- rl/hedge_budget_governor.py
    sha256=9d9d40f0a62d850fe3bd2a6b23e61746a4c973e1cc1ee963cfa95a838255722b
- rl/dynamic_runner_hedge.py
    sha256=24494ad59c88c0badc57fe2ece460ced6fbabc1beae38018f81a34d9f2b53df2
- trading/adaptive_hedge_builder.py
    sha256=55464cec53f7c2d6daec11a43a9c58cb874a34aafc556e09bcbad02730e83e85
- trading/dynamic_adaptive_hedge.py
    sha256=745f5c2a2fc5eaee14622b731d2caade7cd0786e147c68c0dab67a4736528cf4
- trading/hedge_context.py
    sha256=b7d40b6b41025df0c106b918c474b9a9900c8b637e820a8bde4f61f3b59a230a
- trading/hedge_intelligence_engine.py
    sha256=c177b29b8f0ea9a6c54ed7089732b051645f70679206a33e85f1f85459279724
- trading/hedge_pair_coordinator.py
    sha256=b7059809f8946a8be812da61c227705d128422c3d75b5c51081b01d0abee40c8
- trading/leg_manager.py
    sha256=1da61c132ffd96649f31511398610d39ab49e38bdb22adfa9a38d32632679474
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

HEDGE_ENGINE_SCHEMA_VERSION = "v2_native_hedge_paper_engine_v1"

# Default thresholds. Tunable per call.
DEFAULT_DRAWDOWN_BPS_TRIGGER = 100.0
DEFAULT_MAX_HEDGE_SIZE_RATIO = 0.6
DEFAULT_MIN_OPEN_AGE_SECONDS = 60
DEFAULT_MAX_BUDGET_RATIO = 0.5

REASON_FAIL_CLOSED_MISSING_INPUTS = "HEDGE_FAIL_CLOSED_MISSING_INPUTS"
REASON_FAIL_CLOSED_OPERATOR_NOT_APPROVED = "HEDGE_FAIL_CLOSED_OPERATOR_NOT_APPROVED"
REASON_FAIL_CLOSED_LIVE_POSTURE_LEAK = "HEDGE_FAIL_CLOSED_LIVE_POSTURE_LEAK"
REASON_HEDGE_NOT_NEEDED_BELOW_TRIGGER = "HEDGE_NOT_NEEDED_BELOW_TRIGGER"
REASON_HEDGE_NOT_NEEDED_FLAT_POSITION = "HEDGE_NOT_NEEDED_FLAT_POSITION"
REASON_HEDGE_NOT_NEEDED_MIN_AGE = "HEDGE_NOT_NEEDED_MIN_AGE_NOT_MET"
REASON_HEDGE_NEEDED_BUDGET_OK = "HEDGE_NEEDED_BUDGET_OK"
REASON_HEDGE_NEEDED_BUDGET_BLOCKED = "HEDGE_NEEDED_BUDGET_BLOCKED"

LEGACY_SOURCES = {
    "rl/hedge_manager_v3.py": "8cc0c991bcace41853ec5304a27767d30ee332f669474c27a3d606c38f746edf",
    "rl/hedge_harvest_engine.py": "1368cf021fe6c707bd99bcffc4bbd6fe4785760073a2e7702df3a319732e8cb8",
    "rl/hedge_budget_governor.py": "9d9d40f0a62d850fe3bd2a6b23e61746a4c973e1cc1ee963cfa95a838255722b",
    "rl/dynamic_runner_hedge.py": "24494ad59c88c0badc57fe2ece460ced6fbabc1beae38018f81a34d9f2b53df2",
    "trading/adaptive_hedge_builder.py": "55464cec53f7c2d6daec11a43a9c58cb874a34aafc556e09bcbad02730e83e85",
    "trading/dynamic_adaptive_hedge.py": "745f5c2a2fc5eaee14622b731d2caade7cd0786e147c68c0dab67a4736528cf4",
    "trading/hedge_context.py": "b7d40b6b41025df0c106b918c474b9a9900c8b637e820a8bde4f61f3b59a230a",
    "trading/hedge_intelligence_engine.py": "c177b29b8f0ea9a6c54ed7089732b051645f70679206a33e85f1f85459279724",
    "trading/hedge_pair_coordinator.py": "b7059809f8946a8be812da61c227705d128422c3d75b5c51081b01d0abee40c8",
    "trading/leg_manager.py": "1da61c132ffd96649f31511398610d39ab49e38bdb22adfa9a38d32632679474",
}


@dataclass(frozen=True)
class HedgePositionInputs:
    symbol: str
    side: str  # "long" | "short" | "flat"
    notional_usd: float
    unrealized_pnl_bps: float
    age_seconds: int
    drawdown_bps_abs: float
    live_gate: str = "blocked_human_only"
    live_symbols: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HedgeBudgetCheck:
    allowed: bool
    ratio: float
    max_ratio: float


@dataclass(frozen=True)
class HedgeEvaluation:
    schema_version: str
    hedge_needed: bool
    hedge_side: Optional[str]
    hedge_size_ratio: float
    hedge_budget_check: HedgeBudgetCheck
    hedge_block_reason: str
    hedge_fail_closed_when_missing_inputs: bool
    operator_paper_hedge_engine_approved: bool
    generated_utc: str
    # Phase 7 enrichment fields
    hedge_recommendation: str = "NO_HEDGE"  # NO_HEDGE | HEDGE_PROPOSED | HEDGE_BLOCKED_BUDGET | HEDGE_FAIL_CLOSED
    hedge_cost_bps: float = 0.0             # estimated round-trip fee for the hedge leg
    hedge_benefit_bps: float = 0.0          # expected drawdown protection in bps
    unwind_reason: str = ""                 # condition that should trigger hedge unwind


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_valid_inputs(inp: HedgePositionInputs) -> bool:
    if not inp.symbol:
        return False
    if inp.side not in ("long", "short", "flat"):
        return False
    if inp.notional_usd is None or inp.notional_usd < 0:
        return False
    if inp.age_seconds is None or inp.age_seconds < 0:
        return False
    return True


def evaluate_hedge(
    inp: HedgePositionInputs,
    *,
    drawdown_bps_trigger: float = DEFAULT_DRAWDOWN_BPS_TRIGGER,
    max_hedge_size_ratio: float = DEFAULT_MAX_HEDGE_SIZE_RATIO,
    min_open_age_seconds: int = DEFAULT_MIN_OPEN_AGE_SECONDS,
    max_budget_ratio: float = DEFAULT_MAX_BUDGET_RATIO,
    operator_paper_hedge_engine_approved: bool = False,
) -> HedgeEvaluation:
    """Evaluate whether a paper hedge would be proposed.

    The engine fail-closes when:

    - inputs are missing/invalid
    - operator has not approved the paper hedge engine
    - the live posture leaked (live_gate not blocked or live_symbols
      non-empty)
    """
    now = _utc_iso()
    no_budget = HedgeBudgetCheck(allowed=False, ratio=0.0, max_ratio=float(max_budget_ratio))

    if not operator_paper_hedge_engine_approved:
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=False,
            hedge_side=None,
            hedge_size_ratio=0.0,
            hedge_budget_check=no_budget,
            hedge_block_reason=REASON_FAIL_CLOSED_OPERATOR_NOT_APPROVED,
            hedge_fail_closed_when_missing_inputs=False,
            operator_paper_hedge_engine_approved=False,
            generated_utc=now,
        )

    if not _is_valid_inputs(inp):
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=False,
            hedge_side=None,
            hedge_size_ratio=0.0,
            hedge_budget_check=no_budget,
            hedge_block_reason=REASON_FAIL_CLOSED_MISSING_INPUTS,
            hedge_fail_closed_when_missing_inputs=True,
            operator_paper_hedge_engine_approved=True,
            generated_utc=now,
        )

    if inp.live_gate != "blocked_human_only" or inp.live_symbols != ():
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=False,
            hedge_side=None,
            hedge_size_ratio=0.0,
            hedge_budget_check=no_budget,
            hedge_block_reason=REASON_FAIL_CLOSED_LIVE_POSTURE_LEAK,
            hedge_fail_closed_when_missing_inputs=False,
            operator_paper_hedge_engine_approved=True,
            generated_utc=now,
        )

    if inp.side == "flat" or inp.notional_usd <= 0:
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=False,
            hedge_side=None,
            hedge_size_ratio=0.0,
            hedge_budget_check=no_budget,
            hedge_block_reason=REASON_HEDGE_NOT_NEEDED_FLAT_POSITION,
            hedge_fail_closed_when_missing_inputs=False,
            operator_paper_hedge_engine_approved=True,
            generated_utc=now,
        )

    if inp.age_seconds < int(min_open_age_seconds):
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=False,
            hedge_side=None,
            hedge_size_ratio=0.0,
            hedge_budget_check=no_budget,
            hedge_block_reason=REASON_HEDGE_NOT_NEEDED_MIN_AGE,
            hedge_fail_closed_when_missing_inputs=False,
            operator_paper_hedge_engine_approved=True,
            generated_utc=now,
        )

    if inp.drawdown_bps_abs < float(drawdown_bps_trigger):
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=False,
            hedge_side=None,
            hedge_size_ratio=0.0,
            hedge_budget_check=no_budget,
            hedge_block_reason=REASON_HEDGE_NOT_NEEDED_BELOW_TRIGGER,
            hedge_fail_closed_when_missing_inputs=False,
            operator_paper_hedge_engine_approved=True,
            generated_utc=now,
        )

    # Sizing: linear ramp from trigger to 2x trigger, capped by max ratio.
    trigger = float(drawdown_bps_trigger)
    over = max(0.0, inp.drawdown_bps_abs - trigger) / max(1e-9, trigger)
    raw_ratio = min(float(max_hedge_size_ratio), 0.25 + 0.75 * min(1.0, over))
    hedge_side = "short" if inp.side == "long" else "long"

    # Cost/benefit: round-trip fee ~8 bps; benefit = drawdown excess capped by budget.
    hedge_cost_bps = 8.0
    hedge_benefit_bps = round(
        min(inp.drawdown_bps_abs - trigger, trigger) * raw_ratio, 2
    )
    # Unwind condition: when position PnL recovers above half the trigger threshold.
    unwind_reason = (
        f"UNWIND_WHEN_DRAWDOWN_RECOVERS_BELOW_{trigger * 0.5:.0f}BPS_OR_POSITION_CLOSED"
    )

    budget_ratio = raw_ratio  # the proposed hedge size as a fraction of notional
    budget_allowed = budget_ratio <= float(max_budget_ratio)
    budget = HedgeBudgetCheck(
        allowed=bool(budget_allowed),
        ratio=float(budget_ratio),
        max_ratio=float(max_budget_ratio),
    )
    if not budget.allowed:
        return HedgeEvaluation(
            schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
            hedge_needed=True,
            hedge_side=hedge_side,
            hedge_size_ratio=float(raw_ratio),
            hedge_budget_check=budget,
            hedge_block_reason=REASON_HEDGE_NEEDED_BUDGET_BLOCKED,
            hedge_fail_closed_when_missing_inputs=False,
            operator_paper_hedge_engine_approved=True,
            generated_utc=now,
            hedge_recommendation="HEDGE_BLOCKED_BUDGET",
            hedge_cost_bps=hedge_cost_bps,
            hedge_benefit_bps=hedge_benefit_bps,
            unwind_reason=unwind_reason,
        )
    return HedgeEvaluation(
        schema_version=HEDGE_ENGINE_SCHEMA_VERSION,
        hedge_needed=True,
        hedge_side=hedge_side,
        hedge_size_ratio=float(raw_ratio),
        hedge_budget_check=budget,
        hedge_block_reason=REASON_HEDGE_NEEDED_BUDGET_OK,
        hedge_fail_closed_when_missing_inputs=False,
        operator_paper_hedge_engine_approved=True,
        generated_utc=now,
        hedge_recommendation="HEDGE_PROPOSED",
        hedge_cost_bps=hedge_cost_bps,
        hedge_benefit_bps=hedge_benefit_bps,
        unwind_reason=unwind_reason,
    )


def hedge_engine_invariants_snapshot() -> dict:
    return {
        "schema_version": HEDGE_ENGINE_SCHEMA_VERSION,
        "legacy_sources": LEGACY_SOURCES,
        "imports_torch": False,
        "imports_numpy": False,
        "imports_redis": False,
        "imports_exchange_sdk": False,
        "places_exchange_orders": False,
        "writes_legacy_redis": False,
        "default_paper_hedge_engine_operator_approved": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
