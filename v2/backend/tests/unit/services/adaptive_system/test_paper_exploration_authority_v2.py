"""Unit contract for the central paper-exploration blocker classifier.

One classification, applied mechanically at every downstream boundary:
TRADING_POLICY is the ONLY class that loses blocking authority under paper
exploration; everything else (HARD_SAFETY, EXECUTION_INTEGRITY, unknown)
retains it, fail-closed.
"""
from __future__ import annotations

import pytest

from v2.backend.app.services.adaptive_system.paper_exploration_authority_v2 import (
    EXECUTION_INTEGRITY,
    HARD_SAFETY,
    PAPER_EXPLORATION_OVERRIDE_ENV,
    TRADING_POLICY,
    UNCLASSIFIED_FAIL_CLOSED,
    classify_paper_blocker,
    paper_exploration_override_enabled,
    partition_paper_exploration_blockers,
)

_BLOCKING_CLASSES = frozenset(
    {HARD_SAFETY, EXECUTION_INTEGRITY, UNCLASSIFIED_FAIL_CLOSED}
)


@pytest.mark.parametrize(
    "reason",
    [
        "PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND",
        "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
        "BLOCK_NEGATIVE_EXPECTANCY",
        "CONFIDENCE_BELOW_ENTRY_GATE:0.61<0.70",
        "SIDE_GATE_BLOCK:SIDE_BUCKET_EXPECTANCY_NON_POSITIVE",
        "FINAL_ADMISSION_CURRENT_EXPECTED_NET_PNL_NOT_POSITIVE",
        "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE",
        "A_GRADE_FINAL_ADMISSION_WITHOUT_A_PLUS_PASS",
    ],
)
def test_trading_policy_reason_classifies_telemetry_only(reason: str) -> None:
    assert classify_paper_blocker(reason) == TRADING_POLICY
    blocking, telemetry = partition_paper_exploration_blockers([reason])
    assert blocking == []
    assert telemetry == [reason]


@pytest.mark.parametrize(
    "reason",
    [
        "FINAL_ADMISSION_QUANTITY_BELOW_EXCHANGE_MIN",
        "FINAL_ADMISSION_TIME_AFTER_DECISION",
        "FINAL_ADMISSION_LEVERAGE_EXCEEDS_ADAPTIVE_ENVELOPE",
        "FINAL_ADMISSION_ADAPTIVE_EXIT_PLAN_INVALID",
        "PRE_TRADE_LOSS_PROBABILITY_MISSING",
        "GUARDIAN_HALTED_PERFORMANCE_NO_NEW_ENTRY",
        "SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:XUSDT",
        "PAPER_NEW_ENTRIES_HALTED_BY_PORTFOLIO_TRUTH_FREEZE",
    ],
)
def test_non_policy_reason_retains_blocking_authority(reason: str) -> None:
    classified = classify_paper_blocker(reason)
    assert classified != TRADING_POLICY
    assert classified in _BLOCKING_CLASSES
    blocking, telemetry = partition_paper_exploration_blockers([reason])
    assert blocking == [reason]
    assert telemetry == []


@pytest.mark.parametrize(
    "reason",
    [
        "SOME_BRAND_NEW_UNSEEN_REJECTION_REASON",
        "",
        None,
    ],
)
def test_unknown_or_malformed_reason_fails_closed_to_blocking(
    reason: object,
) -> None:
    classified = classify_paper_blocker(reason)
    assert classified != TRADING_POLICY
    assert classified in _BLOCKING_CLASSES
    blocking, telemetry = partition_paper_exploration_blockers([reason])
    assert blocking == [reason]
    assert telemetry == []


def test_non_string_and_empty_inputs_are_unclassified_fail_closed() -> None:
    assert classify_paper_blocker(None) == UNCLASSIFIED_FAIL_CLOSED
    assert classify_paper_blocker("") == UNCLASSIFIED_FAIL_CLOSED


def test_partition_preserves_order_and_splits_mixed_list() -> None:
    mixed = [
        "FINAL_ADMISSION_TIME_AFTER_DECISION",
        "BLOCK_NEGATIVE_EXPECTANCY",
        "SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:XUSDT",
        "CONFIDENCE_BELOW_ENTRY_GATE:0.61<0.70",
        "SOME_BRAND_NEW_UNSEEN_REJECTION_REASON",
        "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE",
        # duplicate policy reason: duplicates must be preserved, in order
        "BLOCK_NEGATIVE_EXPECTANCY",
    ]

    blocking, telemetry = partition_paper_exploration_blockers(mixed)

    assert blocking == [
        "FINAL_ADMISSION_TIME_AFTER_DECISION",
        "SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:XUSDT",
        "SOME_BRAND_NEW_UNSEEN_REJECTION_REASON",
    ]
    assert telemetry == [
        "BLOCK_NEGATIVE_EXPECTANCY",
        "CONFIDENCE_BELOW_ENTRY_GATE:0.61<0.70",
        "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE",
        "BLOCK_NEGATIVE_EXPECTANCY",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),  # unset -> default ON per 2026-07-31 directive
        ("false", False),
        ("0", False),
        ("on", True),
    ],
)
def test_override_env_lever(
    monkeypatch: pytest.MonkeyPatch, raw: object, expected: bool
) -> None:
    if raw is None:
        monkeypatch.delenv(PAPER_EXPLORATION_OVERRIDE_ENV, raising=False)
    else:
        monkeypatch.setenv(PAPER_EXPLORATION_OVERRIDE_ENV, str(raw))
    assert paper_exploration_override_enabled() is expected
