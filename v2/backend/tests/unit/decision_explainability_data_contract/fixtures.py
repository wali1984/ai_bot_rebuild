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


BASE_TS_MS = 1_700_000_000_000
PAPER_MODE_CLOCK_START_MS = BASE_TS_MS + 5_000_000

SCENARIO_BTC_SLUG = "decision_explainability_pack_btc_winner_long"
SCENARIO_ETH_SLUG = "decision_explainability_pack_eth_winner_short"
SCENARIO_LAB_SLUG = "decision_explainability_pack_lab_loser_short"
SCENARIO_SOL_SLUG = "decision_explainability_pack_sol_orchestrator_held"

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
        False,
        "pack_btc_winner_long",
    ),
    (
        SCENARIO_ETH_SLUG,
        "ETHUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        "open_short",
        "proceed_short",
        False,
        "pack_eth_winner_short",
    ),
    (
        SCENARIO_LAB_SLUG,
        "LABUSDT",
        RISK_DECISION_ACTION_ALLOW,
        RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        "open_short",
        "proceed_short",
        True,
        "lab_hedge_unwind_squeeze",
    ),
    (
        SCENARIO_SOL_SLUG,
        "SOLUSDT",
        RISK_DECISION_ACTION_DENY,
        RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        "hold",
        "hold_flat_direction",
        False,
        "pack_sol_orchestrator_held",
    ),
)


@dataclass(frozen=True, slots=True)
class DecisionExplainabilityFixtureInput:
    scenario_slug: str
    step_index: int
    legacy_evidence_pointer: str
    has_lab_pointer: bool
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


def build_paper_mode_clock() -> Callable[[], int]:
    return build_test_clock(PAPER_MODE_CLOCK_START_MS, 17)


def build_decision_explainability_pack_btc_winner_long() -> tuple[
    DecisionExplainabilityFixtureInput, ...
]:
    return _build_scenario_inputs(scenario_index=0)


def build_decision_explainability_pack_eth_winner_short() -> tuple[
    DecisionExplainabilityFixtureInput, ...
]:
    return _build_scenario_inputs(scenario_index=1)


def build_decision_explainability_pack_lab_loser_short() -> tuple[
    DecisionExplainabilityFixtureInput, ...
]:
    return _build_scenario_inputs(scenario_index=2)


def build_decision_explainability_pack_sol_orchestrator_held() -> tuple[
    DecisionExplainabilityFixtureInput, ...
]:
    return _build_scenario_inputs(scenario_index=3)


def build_decision_explainability_fixture_inputs() -> tuple[
    DecisionExplainabilityFixtureInput, ...
]:
    rows: list[DecisionExplainabilityFixtureInput] = []
    for scenario_index in range(len(SCENARIO_SPECS)):
        rows.extend(_build_scenario_inputs(scenario_index=scenario_index))
    return tuple(rows)


def _build_scenario_inputs(
    *, scenario_index: int
) -> tuple[DecisionExplainabilityFixtureInput, ...]:
    (
        scenario_slug,
        symbol,
        risk_action,
        risk_reason,
        input_decision_action,
        input_decision_reason_code,
        has_lab_pointer,
        pointer_suffix,
    ) = SCENARIO_SPECS[scenario_index]
    rows: list[DecisionExplainabilityFixtureInput] = []
    for step_ordinal in range(1, 4):
        ordinal_id = f"{step_ordinal:03d}"
        rows.append(
            DecisionExplainabilityFixtureInput(
                scenario_slug=scenario_slug,
                step_index=step_ordinal,
                legacy_evidence_pointer=(
                    f"legacy_evidence__decision_explainability__"
                    f"{pointer_suffix}__step_{step_ordinal}"
                ),
                has_lab_pointer=has_lab_pointer,
                risk_decision_record=RiskDecisionRecord(
                    risk_decision_id=(
                        f"risk_decision_phase2r_{scenario_slug}_{ordinal_id}"
                    ),
                    decision_id=f"decision_phase2r_{scenario_slug}_{ordinal_id}",
                    prediction_id=(
                        f"prediction_phase2r_{scenario_slug}_{ordinal_id}"
                    ),
                    feature_snapshot_id=(
                        f"feature_snapshot_phase2r_{scenario_slug}_{ordinal_id}"
                    ),
                    symbol=symbol,
                    risk_decision_ts_ms=(
                        BASE_TS_MS + scenario_index * 60_000 + step_ordinal * 100
                    ),
                    risk_action=risk_action,
                    risk_reason_code=risk_reason,
                    input_decision_action=input_decision_action,
                    input_decision_reason_code=input_decision_reason_code,
                    live_blocked=True,
                ),
            )
        )
    return tuple(rows)
END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/fixtures.py
