from __future__ import annotations

from collections.abc import Callable

from v2.backend.app.domain.paper_execution_ledger import (
    PAPER_LEDGER_ACTION_RECORD_ALLOW,
    PAPER_LEDGER_ACTION_RECORD_DENY,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
    PaperExecutionLedgerEntry,
)
from v2.backend.app.domain.replay_backtest_runner import ReplayBacktestRun


_SYMBOL = "LABUSDT"
_RUN_STARTED_TS_MS = 1_700_000_000_000
_RUN_ENDED_TS_MS = _RUN_STARTED_TS_MS + 3_000

_REASON_TO_INPUT_RISK_REASON = {
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG: "allow_proceed_long",
    PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT: "allow_proceed_short",
    PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD: "deny_orchestrator_held",
    PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT: "deny_default",
}


def build_test_clock(start_ms: int, step_ms: int) -> Callable[[], int]:
    clock_state = [start_ms - step_ms]

    def _clock() -> int:
        clock_state[0] += step_ms
        return clock_state[0]

    return _clock


def build_legacy_outcome() -> tuple[
    ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]
]:
    return _build_outcome(
        "legacy",
        (
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
        ),
    )


def build_keep_hedge_outcome() -> tuple[
    ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]
]:
    return _build_outcome(
        "keep_hedge",
        (
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
            PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD,
        ),
    )


def build_close_short_outcome() -> tuple[
    ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]
]:
    return _build_outcome(
        "close_short",
        (
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        ),
    )


def build_reduce_short_outcome() -> tuple[
    ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]
]:
    return _build_outcome(
        "reduce_short",
        (
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
        ),
    )


def build_block_hedge_close_outcome() -> tuple[
    ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]
]:
    return _build_outcome(
        "block_hedge_close",
        (
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT,
            PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG,
            PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT,
        ),
    )


def _build_outcome(
    outcome_slug: str,
    ledger_reason_codes: tuple[str, str, str],
) -> tuple[ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...]]:
    replay_run = ReplayBacktestRun(
        replay_run_id=f"replay_run_lab_hedge_unwind_{outcome_slug}",
        run_mode="replay",
        symbol=_SYMBOL,
        run_started_ts_ms=_RUN_STARTED_TS_MS,
        run_ended_ts_ms=_RUN_ENDED_TS_MS,
        live_blocked=True,
    )
    entries = tuple(
        _build_entry(
            outcome_slug=outcome_slug,
            step_idx_zero_based=step_idx_zero_based,
            ledger_reason_code=ledger_reason_code,
        )
        for step_idx_zero_based, ledger_reason_code in enumerate(ledger_reason_codes)
    )
    return replay_run, entries


def _build_entry(
    *,
    outcome_slug: str,
    step_idx_zero_based: int,
    ledger_reason_code: str,
) -> PaperExecutionLedgerEntry:
    step_id_fragment = f"{step_idx_zero_based + 1:03d}"
    ledger_action = (
        PAPER_LEDGER_ACTION_RECORD_ALLOW
        if ledger_reason_code.startswith("mirror_allow_")
        else PAPER_LEDGER_ACTION_RECORD_DENY
    )
    input_risk_action = (
        "allow" if ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW else "deny"
    )
    return PaperExecutionLedgerEntry(
        paper_trade_id=f"paper_trade_lab_hedge_unwind_{outcome_slug}_{step_id_fragment}",
        risk_decision_id=f"risk_decision_lab_hedge_unwind_{outcome_slug}_{step_id_fragment}",
        decision_id=f"decision_lab_hedge_unwind_{outcome_slug}_{step_id_fragment}",
        prediction_id=f"prediction_lab_hedge_unwind_{outcome_slug}_{step_id_fragment}",
        feature_snapshot_id=f"feature_snapshot_lab_hedge_unwind_{outcome_slug}_{step_id_fragment}",
        symbol=_SYMBOL,
        ledger_entry_ts_ms=_RUN_STARTED_TS_MS + step_idx_zero_based * 1_000,
        ledger_action=ledger_action,
        ledger_reason_code=ledger_reason_code,
        input_risk_action=input_risk_action,
        input_risk_reason_code=_REASON_TO_INPUT_RISK_REASON[ledger_reason_code],
        live_blocked=True,
    )
