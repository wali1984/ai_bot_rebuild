"""Central paper-exploration blocker classification (operator directive 2026-07-31).

One classification, applied mechanically at every downstream boundary:

    HARD_SAFETY          -> may block
    EXECUTION_INTEGRITY  -> may block
    TRADING_POLICY       -> telemetry only under paper exploration; never blocks

The prior design scattered per-lane exemptions (bootstrap positivity carve-out,
side-gate strip lists, Category-E advisory allow-lists) across the funnel.  This
module replaces that pattern with a single fail-closed taxonomy: a reason is
telemetry-only if and only if it is explicitly classified TRADING_POLICY here.
Anything unknown blocks exactly as before (UNCLASSIFIED == blocking), so a new
reason string can never silently lose authority.

TRADING_POLICY covers exactly the operator-enumerated families: expectancy,
expected P&L, utility, confidence, loss-probability preference, historical
side/bucket performance, regime preference, positive-edge requirement, trainer
readiness, posterior state, maturation state and serving-trust preference.

Explicitly NOT policy (always retain blocking authority): authentication,
PIT/causality/clock integrity, venue feasibility and exchange filters,
accounting/reservation/duplicate protection, exposure/leverage/liquidation/
drawdown envelopes, mandatory protective exits, portfolio-truth freezes,
kill-switch/guardian halts with catastrophic mandate, operator symbol
exclusions, allocator sizing authority, and every live-authorization rail.

Paper-only: this module is consulted only on paper intents; live authority is
untouched and remains BLOCKED.
"""
from __future__ import annotations

import os

HARD_SAFETY = "HARD_SAFETY"
EXECUTION_INTEGRITY = "EXECUTION_INTEGRITY"
TRADING_POLICY = "TRADING_POLICY"
UNCLASSIFIED_FAIL_CLOSED = "UNCLASSIFIED_FAIL_CLOSED"

PAPER_EXPLORATION_OVERRIDE_ENV = "PAPER_EXPLORATION_OVERRIDE"

# ---------------------------------------------------------------------------
# TRADING_POLICY — the ONLY class that loses blocking authority under paper
# exploration.  Exact strings first, then prefix families (reason strings that
# embed measured values, e.g. "CONFIDENCE_BELOW_ENTRY_GATE:0.61<0.70").
# ---------------------------------------------------------------------------

_TRADING_POLICY_EXACT = frozenset(
    {
        # -- final admission: economics / tier gating -----------------------
        "FINAL_ADMISSION_CURRENT_EXPECTED_NET_PNL_NOT_POSITIVE",
        "FINAL_ADMISSION_ADAPTIVE_ACTION_MUST_NOT_USE_STATIC_REDUCED_TIER",
        "FINAL_ADMISSION_ADAPTIVE_ACTION_MUST_NOT_USE_STATIC_SIZE_HAIRCUT",
        "FINAL_ADMISSION_A_GRADE_MARKED_REDUCED_BUDGET",
        "FINAL_ADMISSION_REDUCED_BUDGET_FRACTION_INVALID",
        "FINAL_ADMISSION_REDUCED_BUDGET_INCREASED_NOTIONAL",
        "FINAL_ADMISSION_REDUCED_BUDGET_NOT_REALLOCATED",
        "FINAL_ADMISSION_REDUCED_TIER_CAP_PROVENANCE_INVALID",
        "FINAL_ADMISSION_REDUCED_TIER_FLAG_NOT_TRUE",
        "FINAL_ADMISSION_REDUCED_TIER_NOT_REALLOCATED",
        "FINAL_ADMISSION_RISK_EXPLORATION_ELIGIBILITY_INVALID",
        "FINAL_ADMISSION_TIER_NOT_EXECUTABLE",
        "A_GRADE_FINAL_ADMISSION_WITHOUT_A_PLUS_PASS",
        # -- preemptive edge control: loss-probability preference -----------
        "PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND",
        "PAPER_RISK_CONTROLLER_EXPLORATION_LOSS_PROBABILITY_ABOVE_BOUND",
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
        "BLOCK_NEGATIVE_EXPECTANCY",
        "BLOCK_PF_BELOW_1",
        "BLOCK_HIGH_CONFIDENCE_LOSS_CLUSTER",
        "BLOCK_ATR_STOP_CLUSTER",
        # serving-trust preference (directive: TRADING_POLICY)
        "BLOCK_MICROSTRUCTURE_UNSAFE",
        "PREEMPTIVE_DECISION_NO_TRADE_REQUIRES_EXPLORATION_POLICY_OVERRIDE",
        "PREEMPTIVE_EDGE_CONTROL_BLOCKED",
        # -- performance circuit: historical-performance policy -------------
        "PAPER_PERFORMANCE_CIRCUIT_BREAKER_BLOCK_REASON",
        "PAPER_BUCKET_QUARANTINE_BLOCKED_REENTRY",
        "PAPER_HIGH_CONFIDENCE_LOSS_CLUSTER_BLOCKED_REENTRY",
        "CLOSED_5_PROFIT_FACTOR_BELOW_1",
        "CLOSED_5_EXPECTANCY_NON_POSITIVE",
        "ROLLING_25_PF_BELOW_1_AND_EXPECTANCY_NON_POSITIVE",
        "ROLLING_50_PROFIT_FACTOR_BELOW_1",
        "ROLLING_50_EXPECTANCY_NON_POSITIVE",
        "FIRST_BOOTSTRAP_CLOSE_NEGATIVE",
        "HIGH_CONFIDENCE_LOSS_CLUSTER",
        # -- router: bucket-performance quarantine (historical performance) -
        "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE",
        "PAPER_LOSS_BUCKET_QUARANTINE",
        # -- one-minute labeling preference ---------------------------------
        "PAPER_STANDALONE_1M_ELIGIBILITY_BLOCKED",
        "PAPER_STANDALONE_1M_BLOCK_REASON",
        # -- authorization-lane policy preferences --------------------------
        "BOOTSTRAP_REQUIRES_NO_POSITIVE_UTILITY_EXPLORATION",
        "BOOTSTRAP_REQUIRES_FLAT_CHAMPION_BASELINE",
        # -- information-gain estimate: ranking feature, never a veto -------
        "BOOTSTRAP_REQUIRES_POSITIVE_INFORMATION_GAIN",
        "INFORMATION_GAIN_NONPOSITIVE",
        "NO_EXECUTABLE_INFORMATION_SEEKING_ACTION",
        "POSITIVE_UTILITY_EXPLORATION_EXISTS",
        # -- calibration age / tuning freshness (policy, not integrity) -----
        "ADAPTIVE_TUNING_EXPIRED_OR_INVALID_DURING_FINAL_ADMISSION",
        "ADAPTIVE_TUNING_AUTHORITY_NOT_VALID",
        # -- previous-paper-losses safety halts (historical performance) ----
        "B_GRADE_CALIBRATION_SAFETY_HALTED",
        "B_GRADE_PROFIT_FACTOR_BELOW_1",
        "B_GRADE_EXPECTANCY_NON_POSITIVE",
        "B_GRADE_HIGH_CONFIDENCE_LOSS",
        "B_GRADE_CHURN_INCREASED",
        # -- exploration quota / probe slots (policy quota) -----------------
        "HALTED_PROBE_SLOT_CAPACITY_EXHAUSTED",
        # -- allocator economics (final directive 2026-07-31 item 3) --------
        # The runtime allocator emits lowercase reason strings; the prior
        # uppercase-only enumeration missed them, which kept BLOCK_NO_EDGE
        # authoritative on paper intents (observed live 2026-07-31T03:32Z:
        # allocator_decision=BLOCK_NO_EDGE,
        # reason=expected_move_after_cost_not_positive -> REMAIN_FLAT).
        "expected_move_after_cost_not_positive",
        "BLOCK_NO_EDGE",
        "ALLOCATOR_HARD_BLOCK:BLOCK_NO_EDGE",
        "BLOCK_LOW_CONFIDENCE",
        "ALLOCATOR_HARD_BLOCK:BLOCK_LOW_CONFIDENCE",
        "confidence_below_adaptive_minimum",
        "CONFIDENCE_EXECUTABLE_TRADE_BELOW_DYNAMIC_EXPLORATION_FLOOR",
        "CONFIDENCE_EXECUTABLE_TRADE_MISSING",
        # -- loss-cluster / previous-losses preference ----------------------
        "LOSS_CLUSTER_OR_QUARANTINE_ACTIVE",
        "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE",
        "SIDE_CONFIDENCE_BELOW_FLOOR",
        "PAPER_CHURN_EQUITY_BLEED_GOVERNOR_BLOCKED",
        # -- router raw bucket-performance code (historical performance) ----
        "NEGATIVE_BUCKET_PERFORMANCE",
        # -- champion/challenger state preferences (lowercase runtime forms) -
        "bootstrap_requires_no_positive_utility_exploration",
        "bootstrap_requires_flat_champion_baseline",
        "bootstrap_requires_positive_information_gain",
        "CHAMPION_DIRECTIONAL_POSITIVE_UTILITY",
        # -- opportunity grade gating ---------------------------------------
        "NOT_A_PLUS_CANDIDATE",
    }
)

_TRADING_POLICY_PREFIXES = (
    # value-bearing policy reason families
    "CONFIDENCE_BELOW_ENTRY_GATE:",
    "SIDE_GATE_BLOCK:",
    "OUTCOME_MEMORY_BLOCK:",
    "EXPECTED_MOVE_",
    "PRE_TRADE_LOSS_PROBABILITY_AT_OR_ABOVE_ADAPTIVE_THRESHOLD",
    "PREEMPTIVE_DECISION_DENIES_",
    "PAPER_LOSS_BUCKET_QUARANTINE_MATCH:",
    "FINAL_ADMISSION_CURRENT_EXPECTED_NET_PNL_NOT_POSITIVE",
    # opportunity grade / tier gating (value-suffixed variants included)
    "NON_EXECUTABLE_PAPER_TIER",
    "BLOCK_NON_EXECUTABLE_PAPER_TIER",
    "FINAL_ADMISSION_TIER_NOT_EXECUTABLE",
    "FINAL_ADMISSION_REDUCED_TIER_FLAG_NOT_TRUE",
    "FINAL_ADMISSION_REDUCED_TIER_FLAG_NOT_FALSE",
    # budget-fraction zeroing families (confidence/eligibility economics)
    "B_GRADE_EXPLORATION_BUDGET_FRACTION_ZERO",
    "POSITIVE_EDGE_PROBATION_BUDGET_FRACTION_ZERO",
    "A_PLUS_REDUCED_SIZE_BOOTSTRAP_BUDGET_FRACTION_ZERO",
    "PAPER_RISK_CONTROLLER_EXPLORATION_BUDGET_FRACTION_ZERO",
    "EXPECTED_EDGE_NOT_FAVORABLE_AFTER_COST",
    # lowercase allocator expected-move family (final directive 2026-07-31)
    "expected_move_",
)

# ---------------------------------------------------------------------------
# HARD_SAFETY — enumerated for honest telemetry labeling only; membership does
# NOT change behavior (safety blocks whether or not it appears here, because
# the default for anything non-policy is to block).
# ---------------------------------------------------------------------------

_HARD_SAFETY_EXACT = frozenset(
    {
        "FINAL_ADMISSION_ADAPTIVE_EXIT_PLAN_INVALID",
        "FINAL_ADMISSION_A_GRADE_GUARDIAN_NOT_ALLOWING_ENTRIES",
        "FINAL_ADMISSION_ALLOCATOR_FLAG_NOT_FALSE",
        "FINAL_ADMISSION_ALLOCATOR_NOT_PAPER_ONLY",
        "FINAL_ADMISSION_LIVE_OR_ORDER_FLAG_NOT_FALSE",
        "FINAL_ADMISSION_NOT_PAPER_ONLY",
        "FINAL_ADMISSION_MARGIN_MODE_NOT_ISOLATED",
        "FINAL_ADMISSION_PAPER_LIQUIDATION_BUFFER_INVALID",
        "FINAL_ADMISSION_LEVERAGE_ABOVE_1X_WITHOUT_VALID_ATR_RECEIPT",
        "FINAL_ADMISSION_LEVERAGE_EXCEEDS_ADAPTIVE_ENVELOPE",
        "FINAL_ADMISSION_LEVERAGE_EXCEEDS_RECEIPT_BOUND_TARGET",
        "FINAL_ADMISSION_LEVERAGE_NOT_BOUND_TO_BRACKET_LADDER",
        "FINAL_ADMISSION_MAINTENANCE_RATE_NOT_BOUND_TO_ALLOCATOR",
        "FINAL_ADMISSION_REVOCABLE_CONTROL",
        "GUARDIAN_HALTED_PERFORMANCE_NO_NEW_ENTRY",
        "PAPER_NEW_ENTRIES_HALTED_BY_PORTFOLIO_TRUTH_FREEZE",
        "PORTFOLIO_TRUTH_UNTRUSTED",
    }
)

_HARD_SAFETY_PREFIXES = (
    "SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:",
    "TREND_MODE_MICRO_CAP_GAP_RISK:",
    "CATASTROPHIC_",
    "FINAL_ADMISSION_REVOCABLE_CONTROL:",
)


def classify_paper_blocker(reason: object) -> str:
    """Classify one rejection reason.  Fail-closed: unknown strings block."""

    if type(reason) is not str or not reason:
        return UNCLASSIFIED_FAIL_CLOSED
    if reason in _TRADING_POLICY_EXACT:
        return TRADING_POLICY
    for prefix in _TRADING_POLICY_PREFIXES:
        if reason.startswith(prefix):
            return TRADING_POLICY
    if reason in _HARD_SAFETY_EXACT:
        return HARD_SAFETY
    for prefix in _HARD_SAFETY_PREFIXES:
        if reason.startswith(prefix):
            return HARD_SAFETY
    # Everything else (identity, hash, clock, venue, accounting, reservation,
    # duplicate, data-validity, unknown) retains blocking authority.
    return EXECUTION_INTEGRITY


PAPER_POLICY_GATE_AUTHORITY = False
"""Structural constant: no policy gate has blocking authority over paper."""

# Retained as a NAME only so older imports don't break; the hook itself has
# no behavior anymore (final directive 2026-07-31 item 1: no environment
# variable — test-named or otherwise — may condition paper semantics).
LEGACY_AUTHORITY_TEST_HOOK_ENV = "PAPER_EXPLORATION_LEGACY_AUTHORITY_FOR_TESTS"


def paper_exploration_override_enabled() -> bool:
    """Paper execution semantics: policy gates carry ZERO authority.

    FINAL directive 2026-07-31 item 1: this is STRUCTURAL and derives from
    the candidate being paper — never from an environment variable, bootstrap
    mode, exploration mode, opportunity tier, champion/challenger state,
    Guardian status or trainer readiness.  The former
    PAPER_EXPLORATION_LEGACY_AUTHORITY_FOR_TESTS hook is removed: even a
    test-named env var was an environment lever over production semantics.
    PAPER_EXPLORATION_OVERRIDE remains readable via
    paper_exploration_override_env_status() for telemetry only.
    """

    return True


def structural_paper_candidate(intent) -> bool:
    """True iff the candidate is structurally paper (the ONLY basis on which
    TRADING_POLICY reasons lose blocking authority)."""

    try:
        return bool(
            intent.get("paper_only") is True
            and intent.get("routes_to_live") is not True
            and intent.get("places_real_order") is not True
        )
    except AttributeError:
        return False


def paper_exploration_override_env_status() -> str:
    """Observability only: the raw PAPER_EXPLORATION_OVERRIDE env value."""

    return str(os.environ.get(PAPER_EXPLORATION_OVERRIDE_ENV, "<unset>"))


def partition_paper_exploration_blockers(
    reasons,
) -> tuple[list[str], list[str]]:
    """Mechanical partition: (still_blocking, trading_policy_telemetry).

    Order-preserving and duplicate-preserving so downstream evidence records
    keep their exact shape.  The caller applies this on every structurally
    paper candidate; no env lever conditions it.
    """

    blocking: list[str] = []
    telemetry: list[str] = []
    for reason in reasons:
        if classify_paper_blocker(reason) == TRADING_POLICY:
            telemetry.append(reason)
        else:
            blocking.append(reason)
    return blocking, telemetry
