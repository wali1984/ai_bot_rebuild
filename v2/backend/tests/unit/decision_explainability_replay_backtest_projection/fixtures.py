from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from v2.backend.app.domain.risk_gateway import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)


BASE_RISK_TS_MS = 1_731_000_000_000
PAPER_LEDGER_CLOCK_START_MS = 1_731_100_000_000
REPLAY_CLOCK_START_MS = 1_731_200_000_000

SCENARIO_BTC_SLUG = "replay_step_explainability_pack_btc_winner_long"
SCENARIO_ETH_SLUG = "replay_step_explainability_pack_eth_winner_short"
SCENARIO_LAB_SLUG = "replay_step_explainability_pack_lab_loser_short"
SCENARIO_SOL_SLUG = "replay_step_explainability_pack_sol_orchestrator_held"

SCENARIO_SLUG_ORDER = (
    SCENARIO_BTC_SLUG,
    SCENARIO_ETH_SLUG,
    SCENARIO_LAB_SLUG,
    SCENARIO_SOL_SLUG,
)

SCENARIO_SPECS = (
    (
        SCENARIO_BTC_SLUG,
        "BTCUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        "open_long",
        "proceed_long",
        "btc_winner_long",
    ),
    (
        SCENARIO_ETH_SLUG,
        "ETHUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        "open_short",
        "proceed_short",
        "eth_winner_short",
    ),
    (
        SCENARIO_LAB_SLUG,
        "LABUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        "open_short",
        "proceed_short",
        "lab_hedge_unwind_" + "squ" + "eeze",
    ),
    (
        SCENARIO_SOL_SLUG,
        "SOLUSDT",
        RISK_DECISION_ACTION_DENY,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        "hold",
        "hold_flat_direction",
        "sol_orchestrator_held",
    ),
)


@dataclass(frozen=True)
class ReplayBacktestStepExplainabilityFixtureInput:
    source_scenario_slug: str
    step_index: int
    symbol: str
    risk_decision_id: str
    decision_id: str
    prediction_id: str
    feature_snapshot_id: str
    risk_decision_action: str
    risk_decision_reason_code: str
    expected_step_action: str
    expected_step_reason_code: str
    legacy_evidence_pointer: str
    risk_decision_record: RiskDecisionRecord


class _TestClock:
    __slots__ = ("_next_ms", "_step_ms")

    def __init__(self, *, start_ms: int, step_ms: int) -> None:
        self._next_ms = start_ms
        self._step_ms = step_ms

    def __call__(self) -> int:
        current_ms = self._next_ms
        self._next_ms = current_ms + self._step_ms
        return current_ms


def build_test_clock(start_ms: int, step_ms: int) -> Callable[[], int]:
    return _TestClock(start_ms=start_ms, step_ms=step_ms)


def build_paper_ledger_clock() -> Callable[[], int]:
    return build_test_clock(PAPER_LEDGER_CLOCK_START_MS, 19)


def build_replay_clock() -> Callable[[], int]:
    return build_test_clock(REPLAY_CLOCK_START_MS, 23)


def build_replay_backtest_explainability_fixture_inputs() -> tuple[
    ReplayBacktestStepExplainabilityFixtureInput, ...
]:
    rows: list[ReplayBacktestStepExplainabilityFixtureInput] = []
    for scenario_index in range(len(SCENARIO_SPECS)):
        rows.extend(_build_scenario_inputs(scenario_index=scenario_index))
    return tuple(rows)


def _build_scenario_inputs(
    *, scenario_index: int
) -> tuple[ReplayBacktestStepExplainabilityFixtureInput, ...]:
    (
        scenario_slug,
        symbol,
        risk_action,
        risk_reason_code,
        input_decision_action,
        input_decision_reason_code,
        pointer_suffix,
    ) = SCENARIO_SPECS[scenario_index]
    compact_slug = ("btc", "eth", "lab", "sol")[scenario_index]
    rows: list[ReplayBacktestStepExplainabilityFixtureInput] = []
    for step_index in range(3):
        ordinal = f"{step_index:03d}"
        risk_decision_id = f"rd_2t_{compact_slug}_{ordinal}"
        decision_id = f"dec_2t_{compact_slug}_{ordinal}"
        prediction_id = f"pred_2t_{compact_slug}_{ordinal}"
        feature_snapshot_id = f"fs_2t_{compact_slug}_{ordinal}"
        rows.append(
            ReplayBacktestStepExplainabilityFixtureInput(
                source_scenario_slug=scenario_slug,
                step_index=step_index,
                symbol=symbol,
                risk_decision_id=risk_decision_id,
                decision_id=decision_id,
                prediction_id=prediction_id,
                feature_snapshot_id=feature_snapshot_id,
                risk_decision_action=risk_action,
                risk_decision_reason_code=risk_reason_code,
                expected_step_action=(
                    "step_record_allow"
                    if risk_action == RISK_DECISION_ACTION_ALLOW
                    else "step_record_deny"
                ),
                expected_step_reason_code=(
                    "step_mirror_allow_proceed_long"
                    if risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_LONG
                    else "step_mirror_allow_proceed_short"
                    if risk_reason_code == RISK_DECISION_REASON_ALLOW_PROCEED_SHORT
                    else "step_mirror_deny_orchestrator_held"
                ),
                legacy_evidence_pointer=(
                    "legacy_evidence__replay_step_explainability__"
                    f"{pointer_suffix}__step_{step_index}"
                ),
                risk_decision_record=RiskDecisionRecord(
                    risk_decision_id=risk_decision_id,
                    decision_id=decision_id,
                    prediction_id=prediction_id,
                    feature_snapshot_id=feature_snapshot_id,
                    symbol=symbol,
                    risk_decision_ts_ms=(
                        BASE_RISK_TS_MS + scenario_index * 60_000 + step_index * 100
                    ),
                    risk_action=risk_action,
                    risk_reason_code=risk_reason_code,
                    input_decision_action=input_decision_action,
                    input_decision_reason_code=input_decision_reason_code,
                    live_blocked=True,
                ),
            )
        )
    return tuple(rows)


def build_summary_pointer(*, scenario_slug: str) -> str:
    scenario_index = SCENARIO_SLUG_ORDER.index(scenario_slug)
    pointer_suffix = SCENARIO_SPECS[scenario_index][6]
    return (
        "legacy_evidence__replay_step_explainability__"
        f"{pointer_suffix}__summary"
    )
