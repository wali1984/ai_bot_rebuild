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
PAPER_MODE_CLOCK_START_MS = BASE_TS_MS + 1_000_000
LEDGER_CLOCK_START_MS = BASE_TS_MS + 1_500_000

EvidenceScenario = tuple[
    "HistoricalPnLEvidenceRun",
    tuple["HistoricalPnLReplayInput", ...],
]

_REASON_TO_INPUT_DECISION = {
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG: ("open_long", "proceed_long"),
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT: ("open_short", "proceed_short"),
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD: ("hold", "hold_flat_direction"),
}


@dataclass(frozen=True, slots=True)
class HistoricalPnLEvidenceRun:
    scenario_slug: str
    symbol: str
    run_started_ts_ms: int
    run_ended_ts_ms: int


@dataclass(frozen=True, slots=True)
class HistoricalPnLReplayInput:
    legacy_realized_trade_evidence_pointer: str
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


def build_ledger_clock() -> Callable[[], int]:
    return build_test_clock(LEDGER_CLOCK_START_MS, 23)


def historical_pnl_pack_btc_winner_long() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="historical_pnl_pack_btc_winner_long",
        scenario_index=0,
        symbol="BTCUSDT",
        risk_action=RISK_DECISION_ACTION_ALLOW,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
        step_count=3,
    )


def historical_pnl_pack_eth_winner_short() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="historical_pnl_pack_eth_winner_short",
        scenario_index=1,
        symbol="ETHUSDT",
        risk_action=RISK_DECISION_ACTION_ALLOW,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        step_count=3,
    )


def historical_pnl_pack_lab_loser_short() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="historical_pnl_pack_lab_loser_short",
        scenario_index=2,
        symbol="LABUSDT",
        risk_action=RISK_DECISION_ACTION_ALLOW,
        risk_reason_code=RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
        step_count=3,
    )


def historical_pnl_pack_sol_orchestrator_held() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="historical_pnl_pack_sol_orchestrator_held",
        scenario_index=3,
        symbol="SOLUSDT",
        risk_action=RISK_DECISION_ACTION_DENY,
        risk_reason_code=RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
        step_count=3,
    )


def build_historical_pnl_replay_evidence_pack() -> tuple[EvidenceScenario, ...]:
    return (
        historical_pnl_pack_btc_winner_long(),
        historical_pnl_pack_eth_winner_short(),
        historical_pnl_pack_lab_loser_short(),
        historical_pnl_pack_sol_orchestrator_held(),
    )


def _build_scenario(
    *,
    scenario_slug: str,
    scenario_index: int,
    symbol: str,
    risk_action: str,
    risk_reason_code: str,
    step_count: int,
) -> EvidenceScenario:
    run_started_ts_ms = BASE_TS_MS + scenario_index * 60_000
    run_ended_ts_ms = run_started_ts_ms + step_count * 1_000
    evidence_run = HistoricalPnLEvidenceRun(
        scenario_slug=scenario_slug,
        symbol=symbol,
        run_started_ts_ms=run_started_ts_ms,
        run_ended_ts_ms=run_ended_ts_ms,
    )
    inputs = tuple(
        _build_input(
            scenario_slug=scenario_slug,
            ordinal=ordinal,
            symbol=symbol,
            risk_decision_ts_ms=run_started_ts_ms + ordinal * 100,
            risk_action=risk_action,
            risk_reason_code=risk_reason_code,
        )
        for ordinal in range(1, step_count + 1)
    )
    return evidence_run, inputs


def _build_input(
    *,
    scenario_slug: str,
    ordinal: int,
    symbol: str,
    risk_decision_ts_ms: int,
    risk_action: str,
    risk_reason_code: str,
) -> HistoricalPnLReplayInput:
    ordinal_id = f"{ordinal:03d}"
    input_action, input_reason_code = _REASON_TO_INPUT_DECISION[risk_reason_code]
    pointer = (
        f"legacy_realized_trade_evidence__{scenario_slug}__step_{ordinal}"
        if scenario_slug != "historical_pnl_pack_lab_loser_short"
        else f"legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_{ordinal}"
    )
    return HistoricalPnLReplayInput(
        legacy_realized_trade_evidence_pointer=pointer,
        risk_decision_record=RiskDecisionRecord(
            risk_decision_id=f"risk_decision_{scenario_slug}_{ordinal_id}",
            decision_id=f"decision_{scenario_slug}_{ordinal_id}",
            prediction_id=f"prediction_{scenario_slug}_{ordinal_id}",
            feature_snapshot_id=f"feature_snapshot_{scenario_slug}_{ordinal_id}",
            symbol=symbol,
            risk_decision_ts_ms=risk_decision_ts_ms,
            risk_action=risk_action,
            risk_reason_code=risk_reason_code,
            input_decision_action=input_action,
            input_decision_reason_code=input_reason_code,
            live_blocked=True,
        ),
    )
