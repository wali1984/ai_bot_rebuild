"""Canonical preemptive edge-control actions and block reasons."""

from __future__ import annotations

CANONICAL_PREEMPTIVE_ACTIONS: tuple[str, ...] = (
    "ALLOW_A_PLUS_CANDIDATE",
    "ALLOW_PROBATION_PAPER",
    "ALLOW_REDUCE_SIZE_PAPER",
    "SHADOW_ONLY",
    "BLOCK_NO_EDGE",
    "BLOCK_NEGATIVE_EXPECTANCY",
    "BLOCK_PF_BELOW_1",
    "BLOCK_HIGH_CONFIDENCE_LOSS_CLUSTER",
    "BLOCK_ATR_STOP_CLUSTER",
    "BLOCK_BUCKET_QUARANTINE",
    "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
    "BLOCK_MICROSTRUCTURE_UNSAFE",
    "BLOCK_FVG_STRUCTURE_INVALID",
    "BLOCK_LIQUIDITY_SWEEP_RISK",
    "BLOCK_GUARDIAN_HALTED",
    "BLOCK_MISSING_LINEAGE",
    "BLOCK_MISSING_COST",
    "BLOCK_LIVE_NOT_ALLOWED",
)

ALLOW_ACTIONS: frozenset[str] = frozenset(
    {
        "ALLOW_A_PLUS_CANDIDATE",
        "ALLOW_PROBATION_PAPER",
        "ALLOW_REDUCE_SIZE_PAPER",
    }
)

PAPER_ONLY_ALLOW_ACTIONS: frozenset[str] = frozenset(
    {
        "ALLOW_PROBATION_PAPER",
        "ALLOW_REDUCE_SIZE_PAPER",
    }
)

BLOCK_REASON_PRIORITY: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "BLOCK_HIGH_CONFIDENCE_LOSS_CLUSTER",
        ("HIGH_CONFIDENCE_LOSS", "CONFIDENCE_LOSS_CLUSTER"),
    ),
    ("BLOCK_ATR_STOP_CLUSTER", ("ATR_STOP", "ATR STOP")),
    ("BLOCK_BUCKET_QUARANTINE", ("BUCKET_QUARANTINE", "QUARANTINE_MATCH")),
    ("BLOCK_PF_BELOW_1", ("BUCKET_PF", "PROFIT_FACTOR_BELOW_1", "NEGATIVE_BUCKET")),
    (
        "BLOCK_NEGATIVE_EXPECTANCY",
        (
            "EXPECTANCY_NON_POSITIVE",
            "EXPECTED_EDGE_NON_POSITIVE",
            "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE",
            "NEGATIVE_EXPECTANCY",
        ),
    ),
    (
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
        ("LOSS_PROBABILITY_TOO_HIGH", "PRE_TRADE_LOSS_PROBABILITY"),
    ),
    ("BLOCK_MICROSTRUCTURE_UNSAFE", ("MICROSTRUCTURE", "ORDERBOOK_TRUST")),
    ("BLOCK_FVG_STRUCTURE_INVALID", ("FVG", "STRUCTURE", "BOS", "CHOCH")),
    ("BLOCK_LIQUIDITY_SWEEP_RISK", ("SWEEP", "LIQUIDITY")),
    ("BLOCK_GUARDIAN_HALTED", ("GUARDIAN", "HALTED_PERFORMANCE")),
    ("BLOCK_MISSING_COST", ("COST", "SLIPPAGE", "FUNDING", "SPREAD")),
    ("BLOCK_MISSING_LINEAGE", ("LINEAGE", "MISSING_DECISION", "CANDIDATE_PAYLOAD_MISSING")),
)


def canonical_block_action(
    *,
    legacy_decision: str,
    reasons: list[str],
    loss_probability: float | None,
) -> str:
    """Map legacy decision names and free-form reasons to the canonical action."""

    decision = str(legacy_decision or "").upper()
    if decision == "ALLOW":
        return "ALLOW_A_PLUS_CANDIDATE"
    if decision == "POSITIVE_EDGE_PROBATION_PAPER":
        return "ALLOW_PROBATION_PAPER"
    if decision == "REDUCE_SIZE_PAPER_ONLY":
        return "ALLOW_REDUCE_SIZE_PAPER"
    if decision in {"SHADOW_ONLY", "CLOSE_OR_REDUCE_ONLY"}:
        return "SHADOW_ONLY"
    if loss_probability is not None and loss_probability >= 0.80:
        return "BLOCK_LOSS_PROBABILITY_TOO_HIGH"
    haystack = " ".join(str(reason).upper() for reason in reasons)
    for action, tokens in BLOCK_REASON_PRIORITY:
        if any(token in haystack for token in tokens):
            return action
    return "BLOCK_NO_EDGE"


def canonicalize_block_reasons(reasons: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for reason in reasons:
        text = str(reason).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
