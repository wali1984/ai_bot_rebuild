from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_ACTION_RECORD_ALLOW,
    PAPER_LEDGER_ACTION_RECORD_DENY,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    PaperExecutionLedgerEntry,
)
from v2.backend.app.domain.replay_backtest_runner import RUN_MODE_REPLAY, ReplayBacktestRun


BASE_TS_MS = 1_700_000_000_000
PAPER_MODE_CLOCK_START_MS = BASE_TS_MS + 900_000
REPLAY_CLOCK_START_MS = BASE_TS_MS + 1_200_000

EvidenceScenario = tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]

_REASON_TO_INPUT_RISK = {
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG: ("allow", "allow_proceed_long"),
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT: ("allow", "allow_proceed_short"),
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED: (
        "deny",
        "deny_orchestrator_abstained",
    ),
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD: (
        "deny",
        "deny_orchestrator_held",
    ),
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT: ("deny", "deny_default"),
}


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


def build_replay_clock() -> Callable[[], int]:
    return build_test_clock(REPLAY_CLOCK_START_MS, 19)


def paper_mode_evidence_pack_btc_long() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="paper_mode_evidence_pack_btc_long",
        scenario_index=0,
        symbol="BTCUSDT",
        ledger_reason_code=PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        step_count=3,
    )


def paper_mode_evidence_pack_eth_short() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="paper_mode_evidence_pack_eth_short",
        scenario_index=1,
        symbol="ETHUSDT",
        ledger_reason_code=PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        step_count=3,
    )


def paper_mode_evidence_pack_sol_held() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="paper_mode_evidence_pack_sol_held",
        scenario_index=2,
        symbol="SOLUSDT",
        ledger_reason_code=PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        step_count=2,
    )


def paper_mode_evidence_pack_lab_abstained() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="paper_mode_evidence_pack_lab_abstained",
        scenario_index=3,
        symbol="LABUSDT",
        ledger_reason_code=PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED,
        step_count=2,
    )


def paper_mode_evidence_pack_btc_default_deny() -> EvidenceScenario:
    return _build_scenario(
        scenario_slug="paper_mode_evidence_pack_btc_default_deny",
        scenario_index=4,
        symbol="BTCUSDT",
        ledger_reason_code=PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
        step_count=2,
    )


def build_paper_mode_evidence_pack() -> tuple[EvidenceScenario, ...]:
    return (
        paper_mode_evidence_pack_btc_long(),
        paper_mode_evidence_pack_eth_short(),
        paper_mode_evidence_pack_sol_held(),
        paper_mode_evidence_pack_lab_abstained(),
        paper_mode_evidence_pack_btc_default_deny(),
    )


def _build_scenario(
    *,
    scenario_slug: str,
    scenario_index: int,
    symbol: str,
    ledger_reason_code: str,
    step_count: int,
) -> EvidenceScenario:
    run_started_ts_ms = BASE_TS_MS + scenario_index * 60_000
    run_ended_ts_ms = run_started_ts_ms + max(1, step_count) * 1_000
    replay_run = ReplayBacktestRun(
        replay_run_id="replay_run_" + scenario_slug,
        run_mode=RUN_MODE_REPLAY,
        symbol=symbol,
        run_started_ts_ms=run_started_ts_ms,
        run_ended_ts_ms=run_ended_ts_ms,
        live_blocked=True,
    )
    entries = tuple(
        _build_entry(
            scenario_slug=scenario_slug,
            ordinal=ordinal,
            symbol=symbol,
            ledger_entry_ts_ms=run_started_ts_ms + ordinal * 100,
            ledger_reason_code=ledger_reason_code,
        )
        for ordinal in range(1, step_count + 1)
    )
    return replay_run, entries


def _build_entry(
    *,
    scenario_slug: str,
    ordinal: int,
    symbol: str,
    ledger_entry_ts_ms: int,
    ledger_reason_code: str,
) -> PaperExecutionLedgerEntry:
    input_risk_action, input_risk_reason_code = _REASON_TO_INPUT_RISK[
        ledger_reason_code
    ]
    ledger_action = (
        PAPER_LEDGER_ACTION_RECORD_ALLOW
        if input_risk_action == "allow"
        else PAPER_LEDGER_ACTION_RECORD_DENY
    )
    ordinal_id = f"{ordinal:03d}"
    return PaperExecutionLedgerEntry(
        paper_trade_id=f"paper_trade_{scenario_slug}_{ordinal_id}",
        risk_decision_id=f"risk_decision_{scenario_slug}_{ordinal_id}",
        decision_id=f"decision_{scenario_slug}_{ordinal_id}",
        prediction_id=f"prediction_{scenario_slug}_{ordinal_id}",
        feature_snapshot_id=f"feature_snapshot_{scenario_slug}_{ordinal_id}",
        symbol=symbol,
        ledger_entry_ts_ms=ledger_entry_ts_ms,
        ledger_action=ledger_action,
        ledger_reason_code=ledger_reason_code,
        input_risk_action=input_risk_action,
        input_risk_reason_code=input_risk_reason_code,
        live_blocked=True,
    )
